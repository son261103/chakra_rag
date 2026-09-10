"""Provider Jina AI: jina-embeddings-v3/v4/v5 + Batch API /v1/batch/embeddings.

- Sync: /v1/embeddings (OpenAI-shaped) + đặc thù riêng:
  `task` = retrieval.query / retrieval.passage (bắt nghĩa tốt hơn cho search —
  ánh xạ từ input_kind của Embedder), `dimensions` (Matryoshka truncation).
- Batch (docs 2026): endpoint RIÊNG /v1/batch/embeddings (không tương thích
  OpenAI batches) — inline input tối đa 10.000 items, submit → HTTP 202
  {batch_id} → poll GET /v1/batch/{batch_id} (stats.total/completed) → tải
  GET /v1/batch/{batch_id}/output (JSONL: custom_id "request-N" + response.body.data).
  Output custom_id là ID sinh theo vị trí (request-N) chứ không phải chunk_id
  mình gửi ⇒ kết quả dùng `ordered` (vector theo thứ tự submit), không dùng by_id.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from core.providers.base import (
    BatchError,
    BatchResults,
    BatchStatus,
    EmbeddingConfig,
    InputKind,
    ModelPreset,
    ProviderSpec,
)
from core.providers.openai_compat import OpenAICompatAdapter

logger = logging.getLogger(__name__)

JINA_SPEC = ProviderSpec(
    id="jina",
    display_name="Jina AI",
    default_base_url="https://api.jina.ai/v1",
    requires_api_key=True,
    supports_batch=True,
    # Inline input: tối đa 10.000 items / batch (docs 2026).
    batch_limit=10_000,
    models=(
        ModelPreset("jina-embeddings-v5-text-small", (32, 64, 128, 256, 512, 1024)),
        ModelPreset("jina-embeddings-v5-text-nano", (32, 64, 128, 256, 512, 768)),
        ModelPreset("jina-embeddings-v3", (32, 64, 128, 256, 512, 1024)),
        ModelPreset("jina-embeddings-v4", (2048,)),
    ),
)

_TASK_MAP: dict[str, str] = {"query": "retrieval.query", "passage": "retrieval.passage"}

_STATE_MAP = {
    "submitted": "queued",
    "processing": "running",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
}

_POLL_TIMEOUT = 60.0


class JinaAdapter(OpenAICompatAdapter):
    spec = JINA_SPEC

    def _model_kwargs(self, cfg: EmbeddingConfig, input_kind: InputKind) -> dict[str, Any]:
        # `task` chỉ cho model preset của Jina — model lạ nhận request thuần.
        preset = self.spec.preset_for(cfg.model)
        if preset is None:
            return {}
        kwargs: dict[str, Any] = {"task": _TASK_MAP[input_kind]}
        if len(preset.dimensions) > 1:
            kwargs["dimensions"] = cfg.dimension
        return kwargs

    # ---------- Batch API (REST riêng của Jina) ----------

    def _http(self, cfg: EmbeddingConfig, timeout: float) -> httpx.Client:
        return httpx.Client(
            base_url=cfg.base_url,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=timeout,
        )

    def submit_batch(
        self, client: Any, cfg: EmbeddingConfig, items: list[tuple[str, str]]
    ) -> str:
        limit = self.spec.batch_limit or 0
        if len(items) > limit:
            raise BatchError(
                f"File có {len(items)} chunk, vượt giới hạn inline batch của Jina "
                f"({limit} items). Hãy nạp theo phần nhỏ hơn."
            )
        # Custom_id của Jina là ID do server sinh theo vị trí → gửi theo vị trí
        # request-N để map kết quả về thứ tự submit khi đọc output.
        payload = {
            "model": cfg.model,
            "input": [text for _, text in items],
            "task": _TASK_MAP["passage"],
            "custom_id_prefix": "request-",
        }
        preset = self.spec.preset_for(cfg.model)
        if preset is not None and len(preset.dimensions) > 1:
            payload["dimensions"] = cfg.dimension
        with self._http(cfg, _POLL_TIMEOUT) as http:
            r = http.post("/batch/embeddings", json=payload)
            if r.status_code >= 400:
                logger.warning(
                    "Jina batch submit thất bại: HTTP %s %s", r.status_code, r.text[:300]
                )
                raise BatchError(
                    f"Jina batch — nộp job thất bại: HTTP {r.status_code}: {r.text[:200]}"
                )
            batch_id = r.json().get("batch_id")
        if not batch_id:
            raise BatchError(f"Jina batch — response submit thiếu batch_id: {r.text[:200]}")
        return str(batch_id)

    def batch_status(self, client: Any, cfg: EmbeddingConfig, job_id: str) -> BatchStatus:
        with self._http(cfg, _POLL_TIMEOUT) as http:
            r = http.get(f"/batch/{job_id}")
            if r.status_code >= 400:
                logger.warning(
                    "Jina batch status thất bại: HTTP %s %s", r.status_code, r.text[:300]
                )
                raise BatchError(
                    f"Jina batch — xem trạng thái thất bại: HTTP {r.status_code}: {r.text[:200]}"
                )
            job = r.json()
        stats = job.get("stats") or {}
        return BatchStatus(
            state=_STATE_MAP.get(str(job.get("status", "")).lower(), "unknown"),
            completed=int(stats.get("completed", 0) or 0),
            total=int(stats.get("total", 0) or 0),
        )

    def fetch_batch_results(
        self, client: Any, cfg: EmbeddingConfig, job_id: str
    ) -> BatchResults:
        with self._http(cfg, _POLL_TIMEOUT) as http:
            r = http.get(f"/batch/{job_id}")
            if r.status_code >= 400:
                raise BatchError(
                    f"Jina batch — đọc metadata thất bại: HTTP {r.status_code}: {r.text[:200]}"
                )
            job = r.json()
            if str(job.get("status", "")).lower() != "completed":
                raise BatchError(
                    f"Jina batch job {job_id} chưa hoàn tất (status={job.get('status')})."
                )
            output_url = job.get("output_url")
            if not output_url:
                raise BatchError(f"Jina batch job {job_id} không có output_url.")
            # output_url tuyệt đối (host download khác api.jina.ai) → không ép base_url.
            r = http.get(output_url, headers={"Authorization": f"Bearer {cfg.api_key}"})
            if r.status_code >= 400:
                raise BatchError(
                    f"Jina batch — tải output thất bại: HTTP {r.status_code}: {r.text[:200]}"
                )
        ordered: list[list[float]] = []
        for line in r.text.splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            body = (rec.get("response") or {}).get("body") or {}
            data = body.get("data") or []
            embedding = data[0].get("embedding") if data else None
            if embedding is None:
                raise BatchError(
                    f"Dòng output batch Jina không đọc được (request có thể đã lỗi): {line[:200]}"
                )
            ordered.append(embedding)
        return BatchResults(ordered=ordered)

"""Provider Mistral AI: mistral-embed / codestral-embed + Batch API /v1/batch/jobs.

- Sync: /v1/embeddings nhận thêm `output_dimension` ("when feature available" —
  chỉ preset hỗ trợ chọn chiều mới gửi; mistral-embed cố định 1024).
- Batch (docs 2026): KHÔNG tương thích OpenAI batches — path riêng `/v1/batch/jobs`
  (`input_files` số nhiều, `model` ở cấp job) nên phải dùng httpx, giảm 50% giá.
  Output JSONL mirror format OpenAI (custom_id + response.body.data).
"""

from __future__ import annotations

import io
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

MISTRAL_SPEC = ProviderSpec(
    id="mistral",
    display_name="Mistral AI",
    default_base_url="https://api.mistral.ai/v1",
    requires_api_key=True,
    supports_batch=True,
    # Batch theo file — docs không nêu trần request cụ thể; đặt cao, vượt giới
    # hạn thật thì provider trả lỗi tường minh.
    batch_limit=100_000,
    models=(
        ModelPreset("mistral-embed", (1024,)),
        # codestral-embed (code) hỗ trợ chọn output_dimension theo MRL.
        ModelPreset("codestral-embed", (256, 512, 1024, 1536)),
    ),
)

_STATE_MAP = {
    "QUEUED": "queued",
    "RUNNING": "running",
    "SUCCESS": "completed",
    "FAILED": "failed",
    "CANCELLED": "cancelled",
}

_UPLOAD_TIMEOUT = 120.0


class MistralAdapter(OpenAICompatAdapter):
    spec = MISTRAL_SPEC

    def _model_kwargs(self, cfg: EmbeddingConfig, input_kind: InputKind) -> dict[str, Any]:
        preset = self.spec.preset_for(cfg.model)
        if preset is not None and len(preset.dimensions) > 1:
            return {"output_dimension": cfg.dimension}
        return {}

    # ---------- Batch API (REST riêng của Mistral, không dùng openai SDK) ----------

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
                f"File có {len(items)} chunk, vượt giới hạn batch của Mistral "
                f"({limit} request/file). Hãy nạp theo phần nhỏ hơn."
            )
        buf = io.BytesIO()
        body_kwargs = self._model_kwargs(cfg, "passage")
        for custom_id, text in items:
            line = {
                "custom_id": custom_id,
                "body": {"model": cfg.model, "input": text, **body_kwargs},
            }
            buf.write(json.dumps(line, ensure_ascii=False).encode("utf-8") + b"\n")
        buf.seek(0)
        with self._http(cfg, _UPLOAD_TIMEOUT) as http:
            r = http.post(
                "/files",
                files={"file": ("chakra_rag_batch_input.jsonl", buf, "application/jsonl")},
                data={"purpose": "batch"},
            )
            self._raise_if_error(r, "upload file batch")
            file_id = r.json()["id"]
            r = http.post(
                "/batch/jobs",
                json={
                    "input_files": [file_id],
                    "model": cfg.model,
                    "endpoint": "/v1/embeddings",
                },
            )
            self._raise_if_error(r, "tạo batch job")
            return r.json()["id"]

    def batch_status(self, client: Any, cfg: EmbeddingConfig, job_id: str) -> BatchStatus:
        with self._http(cfg, _UPLOAD_TIMEOUT) as http:
            r = http.get(f"/batch/jobs/{job_id}")
            self._raise_if_error(r, "xem trạng thái batch job")
            job = r.json()
        state = _STATE_MAP.get(str(job.get("status", "")).upper(), "unknown")
        # Provider có thể báo tiến độ trong các trường khác nhau — đọc kiểu tự vệ.
        counts = job.get("request_counts") or {}
        return BatchStatus(
            state=state,
            completed=int(counts.get("completed", 0) or 0),
            total=int(counts.get("total", 0) or 0),
        )

    def fetch_batch_results(
        self, client: Any, cfg: EmbeddingConfig, job_id: str
    ) -> BatchResults:
        with self._http(cfg, _UPLOAD_TIMEOUT) as http:
            r = http.get(f"/batch/jobs/{job_id}")
            self._raise_if_error(r, "tải metadata batch job")
            job = r.json()
            if str(job.get("status", "")).upper() != "SUCCESS":
                raise BatchError(f"Batch job {job_id} chưa hoàn tất (status={job.get('status')}).")
            output_file_id = job.get("output_file_id")
            if not output_file_id:
                raise BatchError(f"Batch job {job_id} không có output_file_id.")
            r = http.get(f"/files/{output_file_id}/content")
            self._raise_if_error(r, "tải kết quả batch")
        by_id: dict[str, list[float]] = {}
        for line in r.text.splitlines():
            if not line.strip():
                continue
            custom_id, embedding = self._parse_output_line(line)
            if custom_id is None or embedding is None:
                raise BatchError(
                    "Dòng output batch Mistral không đọc được "
                    f"(request có thể đã lỗi): {line[:200]}"
                )
            by_id[custom_id] = embedding
        return BatchResults(by_id=by_id)

    @staticmethod
    def _parse_output_line(line: str) -> tuple[str | None, list[float] | None]:
        """Parse 1 dòng output — thử các shape khả dĩ (format chính thức mirror OpenAI)."""
        rec = json.loads(line)
        custom_id = rec.get("custom_id")
        body = (rec.get("response") or {}).get("body") or rec.get("body") or rec
        data = body.get("data") or []
        embedding = data[0].get("embedding") if data else body.get("embedding")
        return custom_id, embedding

    @staticmethod
    def _raise_if_error(r: httpx.Response, action: str) -> None:
        if r.status_code >= 400:
            logger.warning(
                "Mistral batch %s thất bại: HTTP %s %s", action, r.status_code, r.text[:300]
            )
            raise BatchError(
                f"Mistral batch — {action} thất bại: HTTP {r.status_code}: {r.text[:200]}"
            )

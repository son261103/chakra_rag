"""Provider Mistral AI: mistral-embed / codestral-embed + Batch API qua official mistralai SDK.

- Sync: dùng `client.embeddings.create(model=..., inputs=...)`.
  Với codestral-embed, hỗ trợ gửi thêm `output_dimension` theo MRL.
- Batch: dùng `client.files.upload` và `client.batch.jobs.create`.
"""

from __future__ import annotations

import io
import json
import logging
from typing import Any

from mistralai.client import Mistral

from core.providers.base import (
    BatchError,
    BatchResults,
    BatchState,
    BatchStatus,
    EmbeddingConfig,
    InputKind,
    ModelPreset,
    ProviderSpec,
)

logger = logging.getLogger(__name__)

MISTRAL_SPEC = ProviderSpec(
    id="mistral",
    display_name="Mistral AI",
    default_base_url="https://api.mistral.ai/v1",
    requires_api_key=True,
    supports_batch=True,
    batch_limit=100_000,
    models=(
        ModelPreset("mistral-embed", (1024,)),
        # codestral-embed (code) hỗ trợ chọn output_dimension theo MRL.
        ModelPreset("codestral-embed", (256, 512, 1024, 1536)),
    ),
)

_STATE_MAP: dict[str, BatchState] = {
    "QUEUED": "queued",
    "RUNNING": "running",
    "SUCCESS": "completed",
    "FAILED": "failed",
    "CANCELLED": "cancelled",
    "TIMEOUT_EXCEEDED": "failed",
    "CANCELLATION_REQUESTED": "running",
}


class MistralAdapter:
    """Adapter tích hợp Mistral AI qua official mistralai SDK."""

    spec = MISTRAL_SPEC

    def build_client(self, cfg: EmbeddingConfig, timeout: float) -> Mistral:
        # SDK paths đã có sẵn /v1 (/v1/embeddings, /v1/batch/jobs) → loại bỏ /v1 ở server_url
        raw_url = cfg.base_url.strip() or self.spec.default_base_url
        server_url = (
            raw_url.rstrip("/").removesuffix("/v1").rstrip("/") or "https://api.mistral.ai"
        )
        timeout_ms = int(timeout * 1000) if timeout else None
        return Mistral(
            api_key=cfg.api_key or "dummy",
            server_url=server_url,
            timeout_ms=timeout_ms,
        )

    def _model_kwargs(self, cfg: EmbeddingConfig, input_kind: InputKind) -> dict[str, Any]:
        preset = self.spec.preset_for(cfg.model)
        if preset is not None and len(preset.dimensions) > 1:
            return {"output_dimension": cfg.dimension}
        return {}

    def sync_embed(
        self, client: Any, cfg: EmbeddingConfig, texts: list[str], input_kind: InputKind
    ) -> list[list[float]]:
        if not texts:
            return []
        kwargs: dict[str, Any] = {"model": cfg.model, "inputs": list(texts)}
        kwargs.update(self._model_kwargs(cfg, input_kind))
        try:
            resp = client.embeddings.create(**kwargs)
        except Exception as exc:
            logger.warning("Mistral sync embed thất bại: %s", exc)
            raise
        return [item.embedding for item in resp.data]

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

        try:
            uploaded = client.files.upload(
                file={"file_name": "chakra_rag_batch_input.jsonl", "content": buf},
                purpose="batch",
            )
            file_id = getattr(uploaded, "id", None)
            if not file_id:
                raise BatchError("Upload file batch Mistral không trả về file_id.")

            job = client.batch.jobs.create(
                input_files=[file_id],
                model=cfg.model,
                endpoint="/v1/embeddings",
            )
            job_id = getattr(job, "id", None)
            if not job_id:
                raise BatchError("Tạo batch job Mistral không trả về job_id.")
            return str(job_id)
        except Exception as exc:
            if isinstance(exc, BatchError):
                raise
            raise BatchError(f"Mistral batch — nộp job thất bại: {exc}") from exc

    def batch_status(self, client: Any, cfg: EmbeddingConfig, job_id: str) -> BatchStatus:
        try:
            job = client.batch.jobs.get(job_id=job_id)
        except Exception as exc:
            raise BatchError(f"Mistral batch — xem trạng thái thất bại: {exc}") from exc

        raw_status = str(getattr(job, "status", "")).upper()
        state = _STATE_MAP.get(raw_status, "unknown")
        completed = getattr(job, "completed_requests", None) or 0
        total = getattr(job, "total_requests", None) or 0
        return BatchStatus(
            state=state,
            completed=int(completed),
            total=int(total),
        )

    def fetch_batch_results(
        self, client: Any, cfg: EmbeddingConfig, job_id: str
    ) -> BatchResults:
        try:
            job = client.batch.jobs.get(job_id=job_id)
            raw_status = str(getattr(job, "status", "")).upper()
            if raw_status != "SUCCESS":
                raise BatchError(f"Batch job {job_id} chưa hoàn tất (status={raw_status}).")
            output_file_id = getattr(job, "output_file", None)
            if not output_file_id:
                raise BatchError(f"Batch job {job_id} không có output_file_id.")

            resp = client.files.download(file_id=output_file_id)
            if hasattr(resp, "text"):
                text_content = resp.text
            elif isinstance(resp, bytes):
                text_content = resp.decode("utf-8")
            else:
                text_content = str(resp)

            by_id: dict[str, list[float]] = {}
            for line in text_content.splitlines():
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
        except Exception as exc:
            if isinstance(exc, BatchError):
                raise
            raise BatchError(f"Mistral batch — tải kết quả thất bại: {exc}") from exc

    @staticmethod
    def _parse_output_line(line: str) -> tuple[str | None, list[float] | None]:
        rec = json.loads(line)
        custom_id = rec.get("custom_id")
        body = (rec.get("response") or {}).get("body") or rec.get("body") or rec
        data = body.get("data") or []
        embedding = data[0].get("embedding") if data else body.get("embedding")
        return custom_id, embedding

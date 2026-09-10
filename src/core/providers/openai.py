"""Provider OpenAI: text-embedding-3-* (MRL `dimensions`) + Batch API /v1/batches.

Batch (docs 2026): upload file JSONL `purpose="batch"` (mỗi dòng `custom_id`,
`method`, `url`, `body`) → POST /v1/batches `completion_window="24h"` → poll
`batches.retrieve` (status + request_counts) → kết quả từ `output_file_id`
(map theo `custom_id`), giảm 50% giá. Giới hạn 50.000 request / 200MB / file.
"""

from __future__ import annotations

import io
import json
from typing import Any

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

OPENAI_SPEC = ProviderSpec(
    id="openai",
    display_name="OpenAI",
    default_base_url="https://api.openai.com/v1",
    requires_api_key=True,
    supports_batch=True,
    batch_limit=50_000,
    models=(
        ModelPreset("text-embedding-3-small", (256, 512, 1024, 1536)),
        ModelPreset("text-embedding-3-large", (256, 512, 1024, 1536, 2048, 3072)),
        # Legacy: không nhận tham số dimensions → chiều cố định.
        ModelPreset("text-embedding-ada-002", (1536,)),
    ),
)

_STATE_MAP = {
    "validating": "running",
    "in_progress": "running",
    "finalizing": "running",
    "completed": "completed",
    "failed": "failed",
    "expired": "expired",
    "cancelling": "cancelled",
    "cancelled": "cancelled",
}


class OpenAIAdapter(OpenAICompatAdapter):
    spec = OPENAI_SPEC

    def _model_kwargs(self, cfg: EmbeddingConfig, input_kind: InputKind) -> dict[str, Any]:
        """`dimensions` (MRL) chỉ gửi khi model preset hỗ trợ chọn chiều."""
        preset = self.spec.preset_for(cfg.model)
        if preset is not None and len(preset.dimensions) > 1:
            return {"dimensions": cfg.dimension}
        return {}

    # ---------- Batch API ----------

    _INPUT_FILE_NAME = "chakra_rag_batch_input.jsonl"

    def submit_batch(
        self, client: Any, cfg: EmbeddingConfig, items: list[tuple[str, str]]
    ) -> str:
        limit = self.spec.batch_limit or 0
        if len(items) > limit:
            raise BatchError(
                f"File có {len(items)} chunk, vượt giới hạn Batch API của OpenAI "
                f"({limit} request/file). Hãy nạp theo phần nhỏ hơn."
            )
        buf = io.BytesIO()
        body_kwargs = self._model_kwargs(cfg, "passage")
        for custom_id, text in items:
            line = {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/embeddings",
                "body": {"model": cfg.model, "input": text, **body_kwargs},
            }
            buf.write(json.dumps(line, ensure_ascii=False).encode("utf-8") + b"\n")
        buf.seek(0)
        uploaded = client.files.create(
            file=(self._INPUT_FILE_NAME, buf, "application/jsonl"), purpose="batch"
        )
        job = client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/embeddings",
            completion_window="24h",
        )
        return job.id

    def batch_status(self, client: Any, cfg: EmbeddingConfig, job_id: str) -> BatchStatus:
        job = client.batches.retrieve(job_id)
        counts = getattr(job, "request_counts", None)
        return BatchStatus(
            state=_STATE_MAP.get(getattr(job, "status", ""), "unknown"),
            completed=getattr(counts, "completed", 0) or 0,
            total=getattr(counts, "total", 0) or 0,
        )

    def fetch_batch_results(
        self, client: Any, cfg: EmbeddingConfig, job_id: str
    ) -> BatchResults:
        job = client.batches.retrieve(job_id)
        if getattr(job, "status", "") != "completed" or not getattr(
            job, "output_file_id", None
        ):
            raise BatchError(f"Batch job {job_id} chưa có kết quả để tải.")
        content = client.files.content(job.output_file_id).read().decode("utf-8")
        by_id: dict[str, list[float]] = {}
        for line in content.splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            custom_id = rec.get("custom_id")
            body = (rec.get("response") or {}).get("body") or {}
            data = body.get("data") or []
            embedding = data[0].get("embedding") if data else None
            if custom_id is None or embedding is None:
                # Request lỗi trong job (error_file_id) sẽ rơi vào đây — để phần
                # thiếu được phát hiện ở worker với thông báo rõ thay vì im lặng.
                raise BatchError(
                    f"Dòng output batch không đọc được (request có thể đã lỗi "
                    f"trên provider): {line[:200]}"
                )
            by_id[custom_id] = embedding
        return BatchResults(by_id=by_id)

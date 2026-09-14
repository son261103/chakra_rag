"""Provider Cohere: embed v3 qua official cohere SDK + Batch Embed Jobs.

- Sync: dùng `cohere.Client.embed` với input_type ("search_query" / "search_document")
  và embedding_types=["float"]. Chunk tối đa 96 text/request theo giới hạn của Cohere.
- Batch: dùng Cohere Embed Jobs API:
  1. Upload dataset dạng `embed-input` qua `client.datasets.create(..., keep_fields=["custom_id"])`
  2. Đợi validation hoàn tất (`validation_status == 'validated'`)
  3. Khởi tạo embed job qua `client.embed_jobs.create`
  4. Trả job_id dạng `dataset_id:job_id`
  5. Poll status (`processing` -> `complete` / `failed`)
  6. Tải output dataset qua `client.datasets.get` và parse JSONL theo custom_id.
"""

from __future__ import annotations

import io
import json
import logging
import time
import urllib.request
import uuid
from typing import Any

import cohere

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

COHERE_SPEC = ProviderSpec(
    id="cohere",
    display_name="Cohere",
    default_base_url="",
    requires_api_key=True,
    requires_base_url=False,
    supports_batch=True,
    batch_limit=100_000,
    models=(
        ModelPreset("embed-multilingual-v3.0", (1024,)),
        ModelPreset("embed-multilingual-light-v3.0", (384,)),
        ModelPreset("embed-english-v3.0", (1024,)),
        ModelPreset("embed-english-light-v3.0", (384,)),
    ),
)

_STATE_MAP: dict[str, BatchState] = {
    "processing": "running",
    "complete": "completed",
    "cancelling": "running",
    "cancelled": "cancelled",
    "failed": "failed",
}

MAX_COHERE_SYNC_BATCH = 96


class CohereAdapter:
    """Adapter tích hợp Cohere qua official cohere Python SDK."""

    spec = COHERE_SPEC

    def build_client(self, cfg: EmbeddingConfig, timeout: float) -> cohere.Client:
        kwargs: dict[str, Any] = {
            "api_key": cfg.api_key or "dummy",
            "timeout": timeout,
            "client_name": "chakra_rag",
        }
        if cfg.base_url.strip():
            kwargs["base_url"] = cfg.base_url.strip()
        return cohere.Client(**kwargs)

    def sync_embed(
        self, client: Any, cfg: EmbeddingConfig, texts: list[str], input_kind: InputKind
    ) -> list[list[float]]:
        if not texts:
            return []
        input_type = "search_query" if input_kind == "query" else "search_document"
        results: list[list[float]] = []

        # Cohere giới hạn tối đa 96 text mỗi call sync embed
        for i in range(0, len(texts), MAX_COHERE_SYNC_BATCH):
            chunk = texts[i : i + MAX_COHERE_SYNC_BATCH]
            try:
                resp = client.embed(
                    texts=list(chunk),
                    model=cfg.model,
                    input_type=input_type,
                    embedding_types=["float"],
                )
            except Exception as exc:
                logger.warning("Cohere sync embed thất bại: %s", exc)
                raise

            emb = getattr(resp, "embeddings", None)
            if hasattr(emb, "float") and emb.float is not None:
                results.extend([list(vec) for vec in emb.float])
            elif isinstance(emb, dict) and "float" in emb:
                results.extend([list(vec) for vec in emb["float"]])
            elif isinstance(emb, (list, tuple)):
                results.extend([list(vec) for vec in emb])
            elif emb is not None and hasattr(emb, "__iter__"):
                results.extend([list(vec) for vec in emb])
            else:
                raise ValueError(f"Cohere API trả về định dạng vector không hợp lệ: {resp}")

        return results

    def submit_batch(
        self, client: Any, cfg: EmbeddingConfig, items: list[tuple[str, str]]
    ) -> str:
        limit = self.spec.batch_limit or 0
        if limit and len(items) > limit:
            raise BatchError(
                f"File có {len(items)} chunk, vượt giới hạn Batch API của Cohere "
                f"({limit} request/file). Hãy nạp theo phần nhỏ hơn."
            )
        buf = io.BytesIO()
        for custom_id, text in items:
            line = {"text": text, "custom_id": custom_id}
            buf.write(json.dumps(line, ensure_ascii=False).encode("utf-8") + b"\n")
        buf.seek(0)

        try:
            dataset = client.datasets.create(
                name=f"chakra_rag_{uuid.uuid4().hex[:8]}",
                type="embed-input",
                data=buf,
                keep_fields=["custom_id"],
            )
            dataset_id = getattr(dataset, "id", None)
            if not dataset_id:
                raise BatchError("Cohere Datasets API không trả về dataset_id hợp lệ.")

            # Đợi validation dataset (thường 1-2 giây)
            start_time = time.monotonic()
            while True:
                res = client.datasets.get(dataset_id)
                ds_obj = getattr(res, "dataset", res)
                val_status = str(getattr(ds_obj, "validation_status", "")).lower()
                if val_status in ("validated", "valid"):
                    break
                if val_status in ("failed", "invalid"):
                    err = getattr(ds_obj, "validation_error", "Validation dataset thất bại")
                    raise BatchError(f"Cohere dataset validation thất bại: {err}")
                if time.monotonic() - start_time > 60.0:
                    raise BatchError("Timeout khi đợi Cohere validate dataset (quá 60s).")
                time.sleep(1.0)

            job = client.embed_jobs.create(
                dataset_id=dataset_id,
                model=cfg.model,
                input_type="search_document",
                embedding_types=["float"],
            )
            job_id = getattr(job, "job_id", getattr(job, "id", None))
            if not job_id:
                raise BatchError("Cohere Embed Jobs API không trả về job_id.")
            return f"{dataset_id}:{job_id}"
        except Exception as exc:
            if isinstance(exc, BatchError):
                raise
            raise BatchError(f"Không thể nộp batch job tới Cohere: {exc}") from exc

    def batch_status(self, client: Any, cfg: EmbeddingConfig, job_id: str) -> BatchStatus:
        actual_job_id = job_id.split(":")[-1] if ":" in job_id else job_id
        try:
            job = client.embed_jobs.get(actual_job_id)
            raw_state = str(getattr(job, "status", "unknown")).lower()
            state = _STATE_MAP.get(raw_state, "running")
            return BatchStatus(state=state, completed=0, total=0)
        except Exception as exc:
            raise BatchError(
                f"Không thể kiểm tra trạng thái batch job Cohere ({actual_job_id}): {exc}"
            ) from exc

    def fetch_batch_results(
        self, client: Any, cfg: EmbeddingConfig, job_id: str
    ) -> BatchResults:
        actual_job_id = job_id.split(":")[-1] if ":" in job_id else job_id
        try:
            job = client.embed_jobs.get(actual_job_id)
            raw_state = str(getattr(job, "status", "unknown")).lower()
            if raw_state != "complete":
                raise BatchError(
                    f"Batch job {actual_job_id} chưa hoàn tất (trạng thái: {raw_state})"
                )

            output_dataset_id = getattr(job, "output_dataset_id", None)
            if not output_dataset_id:
                raise BatchError(
                    f"Batch job {actual_job_id} hoàn tất nhưng thiếu output_dataset_id"
                )

            dataset_res = client.datasets.get(output_dataset_id)
            dataset = getattr(dataset_res, "dataset", dataset_res)
            parts = getattr(dataset, "dataset_parts", []) or []
            if not parts:
                raise BatchError(
                    f"Output dataset {output_dataset_id} không có file kết quả (dataset_parts rỗng)"
                )

            by_id: dict[str, list[float]] = {}
            for part in parts:
                url = getattr(part, "url", None)
                if not url:
                    continue
                req = urllib.request.Request(url, headers={"User-Agent": "chakra_rag"})
                with urllib.request.urlopen(req, timeout=120.0) as resp:
                    for line_bytes in resp:
                        line = line_bytes.decode("utf-8").strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        cid = data.get("custom_id")
                        embeddings = data.get("embeddings")
                        if isinstance(embeddings, dict) and "float" in embeddings:
                            vec = embeddings["float"]
                        elif isinstance(embeddings, list):
                            vec = embeddings
                        else:
                            continue
                        if cid:
                            by_id[str(cid)] = [float(x) for x in vec]

            if not by_id:
                raise BatchError(
                    f"Không đọc được vector nào từ kết quả batch job {actual_job_id}"
                )
            return BatchResults(by_id=by_id)
        except Exception as exc:
            if isinstance(exc, BatchError):
                raise
            raise BatchError(
                f"Lỗi khi tải kết quả batch job Cohere ({actual_job_id}): {exc}"
            ) from exc

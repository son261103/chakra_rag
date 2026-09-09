"""Embedding qua API (OpenAI-compatible /v1/embeddings).

Model KHÔNG chạy local trong RAM: mỗi provider là một tích hợp trong bảng
`embedding_integrations` (base URL + model + API key mã hóa DEK/KEK + số chiều),
quản lý qua Settings UI — cùng pattern với tích hợp LLM.

KHÔNG có fallback env cho credential: chưa cấu hình integration → raise
`EmbeddingConfigError` với thông báo rõ ràng. Mỗi lần nhúng resolve tích hợp
active, cache client theo fingerprint `(base_url, model, api_key)` — đổi tích
hợp không cần restart server.

Vector được chuẩn hóa L2 thủ công bằng numpy trước khi trả về ⇒ khoảng cách L2
trong pgvector tương đương cosine (<->), công thức score `1 - d/2` và index
HNSW `vector_l2_ops` giữ nguyên hợp lệ.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from config import Config
from core.security import decrypt_integration_key

logger = logging.getLogger(__name__)


class EmbeddingConfigError(RuntimeError):
    """Chưa cấu hình embedding integration, hoặc chiều trả về khác khai báo."""


_NOT_CONFIGURED = "Chưa cấu hình model embedding — thêm tích hợp trong Cài đặt (tab Embedding)."


class Embedder:
    """Client embedding API: resolve tích hợp active mỗi lần gọi, cache theo fingerprint."""

    def __init__(self, cfg: Config, integration_repo: Any):
        self.cfg = cfg
        self.integration_repo = integration_repo
        self._client: Any | None = None
        self._fingerprint: tuple[str, str, str] | None = None

    # ---------- resolve cấu hình ----------

    def resolve_active_config(self) -> tuple[str, str, str, int]:
        """(base_url, api_key, model, dimension) của embedding integration đang active.

        Không có row nào đang active → raise (không fallback env).
        """
        row = (
            self.integration_repo.get_active_integration()
            if self.integration_repo is not None
            else None
        )
        if not row:
            raise EmbeddingConfigError(_NOT_CONFIGURED)
        base_url = (row.get("base_url") or "").strip()
        model = (row.get("model") or "").strip()
        try:
            dimension = int(row["dimension"])
        except (KeyError, TypeError, ValueError):
            dimension = 0
        if not base_url or not model or dimension <= 0:
            raise EmbeddingConfigError(
                "Tích hợp embedding thiếu base_url/model/dimension — kiểm tra lại trong "
                "Cài đặt (tab Embedding)."
            )
        api_key = decrypt_integration_key(
            row.get("encrypted_api_key", ""),
            row.get("encrypted_dek", ""),
            self.cfg.encryption_key,
        )
        return base_url, api_key, model, dimension

    @property
    def dim(self) -> int:
        """Số chiều vector — lấy từ khai báo của tích hợp active, không gọi API."""
        return self.resolve_active_config()[3]

    def invalidate(self) -> None:
        """Hủy cache client — lần gọi sau sẽ resolve lại integration active."""
        self._client = None
        self._fingerprint = None

    def _embeddings(self) -> tuple[Any, int]:
        """Trả (OpenAIEmbeddings client, dimension); dựng lại client khi fingerprint đổi."""
        from langchain_openai import OpenAIEmbeddings

        base_url, api_key, model, dimension = self.resolve_active_config()
        fingerprint = (base_url, model, api_key)
        if self._client is None or self._fingerprint != fingerprint:
            self._client = OpenAIEmbeddings(
                model=model,
                openai_api_key=api_key or "not-needed",
                openai_api_base=base_url,
                check_embedding_ctx_length=False,
                timeout=min(self.cfg.llm_timeout, 60.0),
                max_retries=2,
            )
            self._fingerprint = fingerprint
        return self._client, dimension

    # ---------- embedding ----------

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed một batch → ma trận float32 đã chuẩn hóa L2.

        Validate chiều thực tế của API so với khai báo `dimension` — lệch là
        raise sớm thay vì để pgvector báo lỗi khó hiểu lúc insert.
        """
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        client, dimension = self._embeddings()
        vectors = client.embed_documents(list(texts))
        arr = np.asarray(vectors, dtype=np.float32)
        if arr.ndim != 2 or arr.shape[1] != dimension:
            got = arr.shape[1] if arr.ndim == 2 else "?"
            raise EmbeddingConfigError(
                f"Model embedding trả về {got} chiều, khác khai báo {dimension} chiều — "
                "sửa lại 'Chiều vector' trong Cài đặt (tab Embedding)."
            )
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

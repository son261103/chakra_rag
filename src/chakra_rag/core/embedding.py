"""Embedding local bằng sentence-transformers.

Chọn model đa ngôn ngữ (mặc định paraphrase-multilingual-MiniLM-L12-v2, 384 chiều)
vì corpus tiếng Việt và người chấm chạy được ngay không cần API key.

Vector được chuẩn hóa L2 trước khi trả về ⇒ khoảng cách L2 trong sqlite-vec
tương đương cosine, không phụ thuộc option distance_metric của từng phiên bản.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np


@lru_cache
def _load_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


class Embedder:
    """Bọc model embedding: lazy-load, cache theo tên model."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            self._model = _load_model(self.model_name)
        return self._model

    @property
    def dim(self) -> int:
        if hasattr(self.model, "get_embedding_dimension"):
            return self.model.get_embedding_dimension()
        return self.model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed một batch, trả về ma trận float32 đã chuẩn hóa L2."""
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vectors, dtype=np.float32)

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]

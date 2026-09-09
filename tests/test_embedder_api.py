"""Unit tests cho Embedder API (core.embedding) — không mạng, fake OpenAIEmbeddings.

Embedding KHÔNG có fallback env: không có integration active → EmbeddingConfigError.
"""

from __future__ import annotations

import numpy as np
import pytest

from config import Config
from core.embedding import Embedder, EmbeddingConfigError
from core.security import encrypt_integration_key


class _FakeOpenAIEmbeddings:
    """Fake OpenAIEmbeddings: trả vector thô (CHƯA normalize) với chiều cấu hình được."""

    dim = 4
    last_kwargs: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs

    def embed_documents(self, texts):
        return [[2.0] * self.dim for _ in texts]


@pytest.fixture(autouse=True)
def _patch_embeddings(monkeypatch):
    import langchain_openai

    monkeypatch.setattr(langchain_openai, "OpenAIEmbeddings", _FakeOpenAIEmbeddings)
    _FakeOpenAIEmbeddings.dim = 4
    _FakeOpenAIEmbeddings.last_kwargs = None


def _cfg() -> Config:
    # Embedding KHÔNG có cấu hình env — Config chỉ còn encryption_key cho giải mã key.
    return Config(encryption_key="test-kek")


def _row(base_url="http://fake/v1", model="fake-embed", dimension=4, api_key=""):
    enc = encrypt_integration_key(api_key, "test-kek")
    return {
        "base_url": base_url,
        "model": model,
        "dimension": dimension,
        "encrypted_api_key": enc.encrypted_api_key,
        "encrypted_dek": enc.encrypted_dek,
    }


class _FakeRepo:
    def __init__(self, row=None):
        self.row = row

    def get_active_integration(self):
        return self.row


def test_embed_uses_active_row_normalizes():
    embedder = Embedder(_cfg(), _FakeRepo(_row(api_key="k1")))
    out = embedder.embed(["a", "b"])
    assert out.shape == (2, 4)
    assert out.dtype == np.float32
    # Vector thô [2,2,2,2] → L2-normalize → mỗi thành phần 0.5
    assert np.allclose(out, 0.5)
    kwargs = _FakeOpenAIEmbeddings.last_kwargs
    assert kwargs["model"] == "fake-embed"
    assert kwargs["openai_api_base"] == "http://fake/v1"
    assert kwargs["openai_api_key"] == "k1"


def test_embed_one():
    embedder = Embedder(_cfg(), _FakeRepo(_row()))
    v = embedder.embed_one("hello")
    assert v.shape == (4,)
    assert np.isclose(np.linalg.norm(v), 1.0)


def test_empty_texts_returns_zero_matrix():
    embedder = Embedder(_cfg(), _FakeRepo(_row()))
    assert embedder.embed([]).shape == (0, 4)


def test_dimension_mismatch_raises():
    _FakeOpenAIEmbeddings.dim = 3
    embedder = Embedder(_cfg(), _FakeRepo(_row()))
    with pytest.raises(EmbeddingConfigError, match="3 chiều"):
        embedder.embed(["a"])


def test_no_active_row_raises_no_env_fallback():
    """Không có integration nào → raise thẳng, KHÔNG âm thầm dùng env."""
    embedder = Embedder(_cfg(), _FakeRepo(None))
    with pytest.raises(EmbeddingConfigError, match="Chưa cấu hình"):
        embedder.embed(["a"])
    with pytest.raises(EmbeddingConfigError):
        _ = embedder.dim


def test_incomplete_row_raises():
    embedder = Embedder(_cfg(), _FakeRepo(_row(base_url="  ", model="")))
    with pytest.raises(EmbeddingConfigError, match="thiếu base_url/model/dimension"):
        embedder.embed(["a"])


def test_key_decrypted_with_envelope():
    row = _row(api_key="secret-key")
    embedder = Embedder(_cfg(), _FakeRepo(row))
    embedder.embed(["x"])
    assert _FakeOpenAIEmbeddings.last_kwargs["openai_api_key"] == "secret-key"


def test_fingerprint_rebuilds_client_on_change():
    repo = _FakeRepo(_row())
    embedder = Embedder(_cfg(), repo)
    embedder.embed(["a"])
    first = dict(_FakeOpenAIEmbeddings.last_kwargs)
    repo.row = _row(base_url="http://other/v1", model="other-embed")
    embedder.embed(["a"])
    second = _FakeOpenAIEmbeddings.last_kwargs
    assert second["model"] == "other-embed"
    assert second["openai_api_base"] == "http://other/v1"
    assert first != second


def test_invalidate_clears_cached_client():
    embedder = Embedder(_cfg(), _FakeRepo(_row()))
    embedder.embed(["a"])
    assert embedder._client is not None
    embedder.invalidate()
    assert embedder._client is None
    assert embedder._fingerprint is None

"""Unit tests cho Embedder API (core.embedding) — không mạng, fake adapter.

Embedding KHÔNG có fallback env: không có integration active → EmbeddingConfigError.
Seam patch: `core.embedding.get_adapter` — Embedder gọi hàm này để lấy adapter
(theo provider id trong row), nên thay adapter thật bằng fake là đủ.
"""

from __future__ import annotations

import numpy as np
import pytest

from config import Config
from core.embedding import Embedder, EmbeddingConfigError
from core.providers import PROVIDER_REGISTRY
from core.providers.base import BatchResults, BatchStatus
from core.security import encrypt_integration_key

DIM = 4


class _FakeAdapter:
    """Adapter fake: sync_embed trả vector thô (CHƯA normalize) chiều cấu hình được."""

    def __init__(self, spec=None, dim=DIM):
        self.spec = spec or PROVIDER_REGISTRY["custom"]
        self.dim = dim
        self.sync_calls: list[tuple[list[str], str]] = []
        self.built_clients: list[tuple[str, str, str]] = []
        self.fetch_results = BatchResults(by_id={})

    def build_client(self, cfg, timeout):
        self.built_clients.append((cfg.base_url, cfg.model, cfg.api_key))
        return object()  # client dummy — không dùng gì ngoài truyền lại

    def sync_embed(self, client, cfg, texts, input_kind):
        self.sync_calls.append((list(texts), input_kind))
        return [[2.0] * self.dim for _ in texts]

    def submit_batch(self, client, cfg, items):
        return "job-1"

    def batch_status(self, client, cfg, job_id):
        return BatchStatus(state="completed", completed=1, total=1)

    def fetch_batch_results(self, client, cfg, job_id):
        return self.fetch_results


@pytest.fixture(autouse=True)
def _patch_adapter(monkeypatch):
    import core.embedding as emb_mod
    import core.providers as prov_mod

    adapter = _FakeAdapter()
    # Validate provider id bằng registry THẬT (id lạ vẫn raise ValueError →
    # EmbeddingConfigError), chỉ thay phần dựng adapter/call network bằng fake.
    def _fake_get_adapter(provider_id):
        prov_mod.get_adapter(provider_id)
        return adapter

    monkeypatch.setattr(emb_mod, "get_adapter", _fake_get_adapter)
    _patch_adapter.adapter = adapter  # type: ignore[attr-defined]
    return adapter


def _cfg() -> Config:
    # Embedding KHÔNG có cấu hình env — Config chỉ còn encryption_key cho giải mã key.
    return Config(encryption_key="test-kek")


def _row(
    base_url="http://fake/v1", model="fake-embed", dimension=DIM, api_key="", provider="custom"
):
    enc = encrypt_integration_key(api_key, "test-kek")
    return {
        "id": "int-1",
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "dimension": dimension,
        "use_batch": 0,
        "encrypted_api_key": enc.encrypted_api_key,
        "encrypted_dek": enc.encrypted_dek,
    }


class _FakeRepo:
    def __init__(self, row=None):
        self.row = row

    def get_active_integration(self):
        return self.row

    def get_integration(self, integration_id):
        return self.row


def _adapter() -> _FakeAdapter:
    return _patch_adapter.adapter  # type: ignore[attr-defined]


def test_embed_uses_active_row_normalizes():
    embedder = Embedder(_cfg(), _FakeRepo(_row(api_key="k1")))
    out = embedder.embed(["a", "b"])
    assert out.shape == (2, 4)
    assert out.dtype == np.float32
    # Vector thô [2,2,2,2] → L2-normalize → mỗi thành phần 0.5
    assert np.allclose(out, 0.5)
    texts, input_kind = _adapter().sync_calls[0]
    assert texts == ["a", "b"]
    assert input_kind == "passage"
    assert _adapter().built_clients[0] == ("http://fake/v1", "fake-embed", "k1")


def test_embed_one_defaults_to_passage():
    embedder = Embedder(_cfg(), _FakeRepo(_row()))
    v = embedder.embed_one("hello")
    assert v.shape == (4,)
    assert np.isclose(np.linalg.norm(v), 1.0)
    assert _adapter().sync_calls[0][1] == "passage"


def test_input_kind_query_forwarded():
    embedder = Embedder(_cfg(), _FakeRepo(_row()))
    embedder.embed_one("câu hỏi?", input_kind="query")
    assert _adapter().sync_calls[0][1] == "query"


def test_empty_texts_returns_zero_matrix():
    embedder = Embedder(_cfg(), _FakeRepo(_row()))
    assert embedder.embed([]).shape == (0, 4)


def test_dimension_mismatch_raises():
    _adapter().dim = 3
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


def test_unknown_provider_raises_clear_error():
    embedder = Embedder(_cfg(), _FakeRepo(_row(provider="no-such-provider")))
    with pytest.raises(EmbeddingConfigError, match="không hỗ trợ"):
        embedder.embed(["a"])


def test_key_decrypted_with_envelope():
    embedder = Embedder(_cfg(), _FakeRepo(_row(api_key="secret-key")))
    embedder.embed(["x"])
    assert _adapter().built_clients[0][2] == "secret-key"


def test_fingerprint_rebuilds_client_on_change():
    repo = _FakeRepo(_row())
    embedder = Embedder(_cfg(), repo)
    embedder.embed(["a"])
    assert len(_adapter().built_clients) == 1
    repo.row = _row(base_url="http://other/v1", model="other-embed")
    embedder.embed(["a"])
    assert len(_adapter().built_clients) == 2
    assert _adapter().built_clients[1] == ("http://other/v1", "other-embed", "")


def test_invalidate_clears_cached_clients():
    embedder = Embedder(_cfg(), _FakeRepo(_row()))
    embedder.embed(["a"])
    assert embedder._clients
    embedder.invalidate()
    assert not embedder._clients


def test_can_batch_requires_use_batch_and_provider_support():
    cfg = Embedder(_cfg(), _FakeRepo(_row())).resolve_active_config()
    # provider "custom" không hỗ trợ batch
    assert not Embedder(_cfg(), _FakeRepo(_row())).can_batch(cfg)
    # provider hỗ trợ + integration bật use_batch
    openai_spec = PROVIDER_REGISTRY["openai"]
    _patch_adapter.adapter.spec = openai_spec  # type: ignore[attr-defined]
    row = _row(provider="openai")
    row["use_batch"] = 1
    embedder = Embedder(_cfg(), _FakeRepo(row))
    assert embedder.can_batch(embedder.resolve_active_config())
    # provider hỗ trợ nhưng integration chưa bật
    row["use_batch"] = 0
    assert not embedder.can_batch(embedder.resolve_active_config())


def test_fetch_batch_results_validates_and_normalizes():
    _patch_adapter.adapter.spec = PROVIDER_REGISTRY["openai"]  # type: ignore[attr-defined]
    row = _row(provider="openai")
    row["use_batch"] = 1
    embedder = Embedder(_cfg(), _FakeRepo(row))
    cfg = embedder.resolve_active_config()
    _patch_adapter.adapter.fetch_results = BatchResults(by_id={"c1": [2.0] * DIM})  # type: ignore[attr-defined]
    out = embedder.fetch_batch_results("job-1", cfg)
    assert np.allclose(out.by_id["c1"], 0.5)

    # Sai chiều → raise tường minh
    _patch_adapter.adapter.fetch_results = BatchResults(by_id={"c1": [2.0] * 3})  # type: ignore[attr-defined]
    with pytest.raises(EmbeddingConfigError, match="3 chiều"):
        embedder.fetch_batch_results("job-1", cfg)


def test_fetch_batch_results_ordered_normalized():
    _patch_adapter.adapter.spec = PROVIDER_REGISTRY["jina"]  # type: ignore[attr-defined]
    row = _row(provider="jina")
    row["use_batch"] = 1
    embedder = Embedder(_cfg(), _FakeRepo(row))
    cfg = embedder.resolve_active_config()
    _patch_adapter.adapter.fetch_results = BatchResults(ordered=[[2.0] * DIM])  # type: ignore[attr-defined]
    out = embedder.fetch_batch_results("job-1", cfg)
    assert np.allclose(out.ordered[0], 0.5)

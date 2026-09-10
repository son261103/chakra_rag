"""Unit tests cho provider adapters (core.providers) — không mạng, fake client.

Mỗi adapter: `_model_kwargs` chỉ gửi tham số riêng khi model nằm trong preset;
openai SDK sync_embed sort lại data theo index; batch: format JSONL + map kết quả
+ giới hạn item; provider không batch → BatchError tường minh.
"""

from __future__ import annotations

import json

import pytest

from core.providers import PROVIDER_REGISTRY, get_adapter, get_provider
from core.providers.base import BatchError, EmbeddingConfig, ModelPreset, ProviderSpec
from core.providers.jina import JinaAdapter
from core.providers.mistral import MistralAdapter
from core.providers.openai import OpenAIAdapter


def _cfg(provider="openai", model="text-embedding-3-small", dimension=1024, **kw):
    return EmbeddingConfig(
        integration_id="int-1",
        provider=provider,
        base_url=kw.get("base_url", "http://fake/v1"),
        api_key=kw.get("api_key", "k"),
        model=model,
        dimension=dimension,
        use_batch=kw.get("use_batch", True),
    )


# ---------- registry ----------


def test_registry_has_five_providers():
    assert set(PROVIDER_REGISTRY) == {"openai", "mistral", "jina", "ollama", "custom"}


def test_unknown_provider_raises_no_fallback():
    with pytest.raises(ValueError, match="không hỗ trợ"):
        get_provider("nope")
    with pytest.raises(ValueError, match="không hỗ trợ"):
        get_adapter("nope")


def test_batch_capability_flags():
    assert get_provider("openai").supports_batch
    assert get_provider("mistral").supports_batch
    assert get_provider("jina").supports_batch
    assert not get_provider("ollama").supports_batch
    assert not get_provider("custom").supports_batch


def test_custom_provider_has_no_presets():
    assert get_provider("custom").models == ()
    assert get_provider("custom").default_base_url == ""


# ---------- sync param mapping ----------


def test_openai_dimensions_only_for_preset_with_multi_dims():
    adapter = OpenAIAdapter()
    # preset 3-small hỗ trợ MRL → gửi dimensions theo khai báo
    assert adapter._model_kwargs(_cfg(dimension=1024), "passage") == {"dimensions": 1024}
    # ada-002 cố định 1536 → KHÔNG gửi
    assert adapter._model_kwargs(_cfg(model="text-embedding-ada-002"), "passage") == {}
    # model lạ → request thuần
    assert adapter._model_kwargs(_cfg(model="whatever"), "passage") == {}


def test_mistral_output_dimension_only_for_codestral():
    adapter = MistralAdapter()
    # mistral-embed cố định 1024 → KHÔNG gửi output_dimension
    assert adapter._model_kwargs(_cfg(provider="mistral", model="mistral-embed"), "passage") == {}
    # codestral-embed hỗ trợ chọn chiều
    assert adapter._model_kwargs(
        _cfg(provider="mistral", model="codestral-embed", dimension=512), "passage"
    ) == {"output_dimension": 512}


def test_jina_task_maps_from_input_kind():
    adapter = JinaAdapter()
    cfg = _cfg(provider="jina", model="jina-embeddings-v5-text-small", dimension=512)
    assert adapter._model_kwargs(cfg, "query") == {
        "task": "retrieval.query",
        "dimensions": 512,
    }
    assert adapter._model_kwargs(cfg, "passage") == {
        "task": "retrieval.passage",
        "dimensions": 512,
    }
    # model lạ → thuần (không task/dimensions)
    assert adapter._model_kwargs(_cfg(provider="jina", model="other"), "query") == {}


# ---------- sync_embed (openai SDK shape) ----------


class _Datum:
    def __init__(self, index, embedding):
        self.index = index
        self.embedding = embedding


class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeEmbeddingsAPI:
    def __init__(self):
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        data = [_Datum(i, [1.0, 0.0, 0.0, 0.0]) for i in range(len(kwargs["input"]))]
        return _Resp(list(reversed(data)))  # cố tình trả ngược → adapter phải sort


class _FakeClient:
    def __init__(self):
        self.embeddings = _FakeEmbeddingsAPI()


def test_sync_embed_sorts_by_index():
    adapter = OpenAIAdapter()
    client = _FakeClient()
    out = adapter.sync_embed(client, _cfg(), ["a", "b", "c"], "query")
    assert len(out) == 3
    # sort theo index — output giữ đúng thứ tự input
    assert out[0] == [1.0, 0.0, 0.0, 0.0]
    assert client.embeddings.kwargs["input"] == ["a", "b", "c"]
    assert client.embeddings.kwargs["dimensions"] == 1024


# ---------- openai batch ----------


class _FileObj:
    def __init__(self, id):
        self.id = id


class _FilesAPI:
    def __init__(self):
        self.captured = None

    def create(self, file, purpose):
        self.captured = {"file": file, "purpose": purpose}
        return _FileObj("file-1")


class _JobObj:
    def __init__(self, id, status="in_progress", completed=0, total=0, output_file_id=None):
        self.id = id
        self.status = status
        self.request_counts = type("C", (), {"completed": completed, "total": total})()
        self.output_file_id = output_file_id


class _BatchesAPI:
    def __init__(self, job=None):
        self.kwargs = None
        self.job = job or _JobObj("job-1")

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.job

    def retrieve(self, job_id):
        return self.job


class _ContentObj:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload


class _OpenAIBatchClient:
    def __init__(self, job=None, output=b""):
        self.files = _FilesAPI()
        self.files.content = lambda file_id: _ContentObj(output)
        self.batches = _BatchesAPI(job)


def test_openai_submit_batch_builds_jsonl():
    adapter = OpenAIAdapter()
    client = _OpenAIBatchClient()
    job_id = adapter.submit_batch(client, _cfg(), [("c1", "văn bản một"), ("c2", "hai")])
    assert job_id == "job-1"
    assert client.files.captured["purpose"] == "batch"
    assert client.batches.kwargs["endpoint"] == "/v1/embeddings"
    assert client.batches.kwargs["completion_window"] == "24h"
    name, buf, mime = client.files.captured["file"]
    assert name.endswith(".jsonl") and mime == "application/jsonl"
    lines = [json.loads(x) for x in buf.read().decode("utf-8").splitlines()]
    assert lines[0]["custom_id"] == "c1"
    assert lines[0]["url"] == "/v1/embeddings"
    assert lines[0]["body"] == {
        "model": "text-embedding-3-small",
        "input": "văn bản một",
        "dimensions": 1024,
    }


def test_openai_submit_batch_over_limit_raises():
    adapter = OpenAIAdapter()
    adapter.spec = ProviderSpec(
        id="openai", display_name="OpenAI", default_base_url="", requires_api_key=True,
        supports_batch=True, batch_limit=2, models=(ModelPreset("m", (4,)),),
    )
    with pytest.raises(BatchError, match="vượt giới hạn"):
        adapter.submit_batch(_OpenAIBatchClient(), _cfg(), [("a", "1"), ("b", "2"), ("c", "3")])


def test_openai_batch_status_mapping():
    adapter = OpenAIAdapter()
    client = _OpenAIBatchClient(job=_JobObj("j", status="completed", completed=2, total=3))
    st = adapter.batch_status(client, _cfg(), "j")
    assert st.state == "completed"
    assert (st.completed, st.total) == (2, 3)


def test_openai_fetch_results_maps_by_custom_id():
    output = b"\n".join(
        [
            json.dumps({
                "custom_id": "c1",
                "response": {"body": {"data": [{"index": 0, "embedding": [1.0, 2.0, 3.0, 4.0]}]}},
            }).encode(),
            json.dumps({
                "custom_id": "c2",
                "response": {"body": {"data": [{"index": 0, "embedding": [4.0, 3.0, 2.0, 1.0]}]}},
            }).encode(),
        ]
    )
    adapter = OpenAIAdapter()
    client = _OpenAIBatchClient(
        job=_JobObj("j", status="completed", output_file_id="out-1"), output=output
    )
    results = adapter.fetch_batch_results(client, _cfg(), "j")
    assert set(results.by_id) == {"c1", "c2"}
    assert results.by_id["c1"] == [1.0, 2.0, 3.0, 4.0]
    assert results.ordered == []


# ---------- non-batch providers ----------


def test_non_batch_provider_raises_clear_error():
    from core.providers.ollama import OllamaAdapter

    with pytest.raises(BatchError, match="không hỗ trợ Batch API"):
        OllamaAdapter().submit_batch(object(), _cfg(provider="ollama"), [("a", "b")])


def test_mistral_submit_over_limit_raises():
    adapter = MistralAdapter()
    adapter.spec = ProviderSpec(
        id="mistral", display_name="Mistral", default_base_url="", requires_api_key=True,
        supports_batch=True, batch_limit=1, models=(ModelPreset("m", (4,)),),
    )
    with pytest.raises(BatchError, match="vượt giới hạn"):
        adapter.submit_batch(object(), _cfg(provider="mistral"), [("a", "1"), ("b", "2")])

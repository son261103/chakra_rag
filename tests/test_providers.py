"""Unit tests cho provider adapters (core.providers) — không mạng, fake client.

Mỗi adapter: `_model_kwargs` chỉ gửi tham số riêng khi model nằm trong preset;
openai SDK sync_embed sort lại data theo index; batch: format JSONL + map kết quả
+ giới hạn item; provider không batch → BatchError tường minh.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from core.providers import PROVIDER_REGISTRY, get_adapter, get_provider
from core.providers.base import BatchError, EmbeddingConfig, ModelPreset, ProviderSpec
from core.providers.cohere import CohereAdapter
from core.providers.jina import JinaAdapter
from core.providers.mistral import MistralAdapter
from core.providers.ollama import OllamaAdapter
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


def test_registry_has_providers():
    assert set(PROVIDER_REGISTRY) == {"openai", "mistral", "jina", "ollama", "cohere", "custom"}


def test_unknown_provider_raises_no_fallback():
    with pytest.raises(ValueError, match="không hỗ trợ"):
        get_provider("nope")
    with pytest.raises(ValueError, match="không hỗ trợ"):
        get_adapter("nope")


def test_batch_capability_flags():
    assert get_provider("openai").supports_batch
    assert get_provider("mistral").supports_batch
    assert get_provider("jina").supports_batch
    assert get_provider("cohere").supports_batch
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


# ---------- cohere provider ----------


def test_cohere_empty_base_url_builds_client():
    adapter = CohereAdapter()
    cfg = _cfg(provider="cohere", base_url="", api_key="test-key")
    client = adapter.build_client(cfg, timeout=30.0)
    assert client is not None
    assert getattr(client._client_wrapper, "_base_url", None) == "https://api.cohere.com"


def test_cohere_sync_embed_chunks_over_96_texts():
    adapter = CohereAdapter()
    client = MagicMock()
    # 150 texts -> 2 calls (96 + 54)
    texts = [f"text-{i}" for i in range(150)]

    def _mock_embed(texts, model, input_type, embedding_types):
        res = MagicMock()
        res.embeddings.float = [[float(j)] * 4 for j in range(len(texts))]
        return res

    client.embed.side_effect = _mock_embed
    cfg = _cfg(provider="cohere", model="embed-multilingual-v3.0", dimension=4)

    vectors = adapter.sync_embed(client, cfg, texts, "passage")
    assert len(vectors) == 150
    assert client.embed.call_count == 2
    # Verify input_type is search_document for passage
    assert client.embed.call_args_list[0].kwargs["input_type"] == "search_document"
    assert client.embed.call_args_list[0].kwargs["embedding_types"] == ["float"]

    # Verify query input_type is search_query
    adapter.sync_embed(client, cfg, ["question"], "query")
    assert client.embed.call_args_list[-1].kwargs["input_type"] == "search_query"


def test_cohere_submit_batch_creates_dataset_and_job():
    adapter = CohereAdapter()
    client = MagicMock()
    mock_ds = MagicMock(id="ds-123")
    client.datasets.create.return_value = mock_ds
    mock_ds_res = MagicMock()
    mock_ds_res.dataset.validation_status = "validated"
    client.datasets.get.return_value = mock_ds_res
    client.embed_jobs.create.return_value = MagicMock(job_id="job-789")

    cfg = _cfg(provider="cohere", model="embed-multilingual-v3.0", dimension=4)
    encoded_id = adapter.submit_batch(client, cfg, [("c1", "text 1"), ("c2", "text 2")])

    assert encoded_id == "ds-123:job-789"
    assert client.datasets.create.call_count == 1
    assert client.embed_jobs.create.call_args.kwargs["dataset_id"] == "ds-123"
    assert client.embed_jobs.create.call_args.kwargs["model"] == "embed-multilingual-v3.0"


def test_cohere_batch_status_maps_statuses():
    adapter = CohereAdapter()
    client = MagicMock()
    cfg = _cfg(provider="cohere")

    client.embed_jobs.get.return_value = MagicMock(status="processing")
    s = adapter.batch_status(client, cfg, "ds-123:job-789")
    assert s.state == "running"

    client.embed_jobs.get.return_value = MagicMock(status="complete")
    s = adapter.batch_status(client, cfg, "ds-123:job-789")
    assert s.state == "completed"

    client.embed_jobs.get.return_value = MagicMock(status="failed")
    s = adapter.batch_status(client, cfg, "ds-123:job-789")
    assert s.state == "failed"


def test_cohere_fetch_batch_results_downloads_and_parses_jsonl(monkeypatch):
    adapter = CohereAdapter()
    client = MagicMock()
    cfg = _cfg(provider="cohere", dimension=2)

    client.embed_jobs.get.return_value = MagicMock(
        status="complete", output_dataset_id="out-ds-456"
    )
    part_mock = MagicMock(url="https://fake-download.cohere.com/part1.jsonl")
    ds_res_mock = MagicMock()
    ds_res_mock.dataset.dataset_parts = [part_mock]
    client.datasets.get.return_value = ds_res_mock

    import httpx

    jsonl_content = (
        '{"custom_id": "c1", "embeddings": {"float": [0.1, 0.2]}}\n'
        '{"custom_id": "c2", "embeddings": {"float": [0.3, 0.4]}}\n'
    )

    class _MockHttpxResponse:
        text = jsonl_content

        def raise_for_status(self):
            pass

    monkeypatch.setattr(httpx, "get", lambda url, timeout: _MockHttpxResponse())

    results = adapter.fetch_batch_results(client, cfg, "ds-123:job-789")
    assert set(results.by_id) == {"c1", "c2"}
    assert results.by_id["c1"] == [0.1, 0.2]
    assert results.by_id["c2"] == [0.3, 0.4]


# ---------- mistral provider tests ----------


def test_mistral_build_client_strips_v1():
    adapter = MistralAdapter()
    for raw in ("https://api.mistral.ai/v1", "https://api.mistral.ai/v1/", "https://api.mistral.ai"):
        client = adapter.build_client(_cfg(provider="mistral", base_url=raw), timeout=10.0)
        server_url = client.sdk_configuration.get_server_details()[0]
        assert server_url == "https://api.mistral.ai"


def test_mistral_sync_embed_calls_sdk():
    adapter = MistralAdapter()
    client = MagicMock()
    mock_item = MagicMock(embedding=[0.1, 0.2, 0.3, 0.4])
    client.embeddings.create.return_value = MagicMock(data=[mock_item])

    cfg = _cfg(provider="mistral", model="mistral-embed", dimension=4)
    vectors = adapter.sync_embed(client, cfg, ["Xin chào"], "passage")

    assert vectors == [[0.1, 0.2, 0.3, 0.4]]
    assert client.embeddings.create.call_args.kwargs["model"] == "mistral-embed"
    assert client.embeddings.create.call_args.kwargs["inputs"] == ["Xin chào"]


def test_mistral_batch_flow_calls_sdk():
    adapter = MistralAdapter()
    client = MagicMock()
    client.files.upload.return_value = MagicMock(id="file-123")
    client.batch.jobs.create.return_value = MagicMock(id="job-456")
    client.batch.jobs.get.return_value = MagicMock(
        status="SUCCESS", completed_requests=2, total_requests=2, output_file="out-file-789"
    )

    jsonl_text = (
        '{"custom_id": "c1", "response": {"body": {"data": [{"embedding": [1.0, 2.0]}]}}}\n'
        '{"custom_id": "c2", "response": {"body": {"data": [{"embedding": [3.0, 4.0]}]}}}\n'
    )
    client.files.download.return_value = MagicMock(text=jsonl_text)

    cfg = _cfg(provider="mistral", model="mistral-embed", dimension=2)
    job_id = adapter.submit_batch(client, cfg, [("c1", "text 1"), ("c2", "text 2")])
    assert job_id == "job-456"

    status = adapter.batch_status(client, cfg, job_id)
    assert status.state == "completed"
    assert (status.completed, status.total) == (2, 2)

    results = adapter.fetch_batch_results(client, cfg, job_id)
    assert set(results.by_id) == {"c1", "c2"}
    assert results.by_id["c1"] == [1.0, 2.0]
    assert results.by_id["c2"] == [3.0, 4.0]


# ---------- ollama provider tests ----------


def test_ollama_build_client_strips_v1():
    adapter = OllamaAdapter()
    for raw in ("http://192.168.1.100:11434/v1", "http://192.168.1.100:11434/v1/", "http://192.168.1.100:11434"):
        client = adapter.build_client(_cfg(provider="ollama", base_url=raw), timeout=20.0)
        assert "192.168.1.100:11434" in str(client._client.base_url)
        assert not str(client._client.base_url).endswith("/v1")
        assert not str(client._client.base_url).endswith("/v1/")


def test_ollama_sync_embed_calls_sdk():
    adapter = OllamaAdapter()
    client = MagicMock()
    client.embed.return_value = {"embeddings": [[0.5, 0.6, 0.7, 0.8]]}

    cfg = _cfg(provider="ollama", model="bge-m3", dimension=4)
    vectors = adapter.sync_embed(client, cfg, ["Văn bản tiếng Việt"], "passage")

    assert vectors == [[0.5, 0.6, 0.7, 0.8]]
    assert client.embed.call_args.kwargs["model"] == "bge-m3"
    assert client.embed.call_args.kwargs["input"] == ["Văn bản tiếng Việt"]

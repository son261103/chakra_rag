"""Unit tests cho observability.tracing — không cần network/key."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from chakra_rag.observability.tracing import ls_client, submit_feedback, trace_metadata


def test_trace_metadata_shape():
    cfgdict = trace_metadata("conv-1", "agent", streamed=False)
    assert cfgdict == {
        "metadata": {"conversation_id": "conv-1", "mode": "agent", "streamed": False},
        "tags": ["sync"],
    }
    cfgdict2 = trace_metadata(None, "stuff", streamed=True)
    assert cfgdict2["metadata"]["conversation_id"] is None
    assert cfgdict2["tags"] == ["stream"]


def test_ls_client_none_without_key(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    assert ls_client() is None


def test_submit_feedback_noop_when_unconfigured(monkeypatch):
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    submit_feedback(key="low_confidence", score=True)  # must not raise


def test_submit_feedback_calls_client(monkeypatch):
    # Tracing phải "được cấu hình" thì ls_client mới trả về client
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-test")
    fake_rt = MagicMock()
    fake_rt.id = "run-1"
    fake_rt.trace_id = "trace-1"
    fake_rt.session_name = "chakra_rag"
    fake_client = MagicMock()
    fake_client.create_project.return_value.id = "proj-1"
    import chakra_rag.observability.tracing as tracing_mod
    with patch("chakra_rag.observability.tracing.get_current_run_tree", return_value=fake_rt):
        old = tracing_mod._client_cache
        tracing_mod._client_cache = fake_client
        try:
            submit_feedback(key="low_confidence", score=1, comment="below threshold")
        finally:
            tracing_mod._client_cache = old
    kwargs = fake_client.create_feedback.call_args.kwargs
    assert kwargs["key"] == "low_confidence"
    assert kwargs["score"] == 1
    assert kwargs["run_id"] == "run-1"
    assert kwargs["trace_id"] == "trace-1"
    assert kwargs["session_id"] == "proj-1"

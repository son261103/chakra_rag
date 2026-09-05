"""ServiceContainer không còn phụ thuộc Telemetry; feedback được gọi với đúng metrics."""
from __future__ import annotations

from unittest.mock import patch

import pytest


class _FakeEmbedder:
    dim = 4

    def __init__(self, model: str):
        pass

    def embed_one(self, text: str) -> list[float]:
        return [0.0] * 4

    def embed_many(self, texts):
        return [[0.0] * 4 for _ in texts]


@pytest.fixture()
def make_service(tmp_path, monkeypatch):
    """ServiceContainer với FakeEmbedder — không load model thật."""
    from config import Config
    from service import container as rs

    monkeypatch.setattr(rs, "Embedder", _FakeEmbedder)

    def factory():
        cfg = Config(db_path=tmp_path / "t.db", uploads_dir=tmp_path, logs_dir=tmp_path / "logs")
        return rs.ServiceContainer(cfg)

    return factory


class FakeAgentResult:
    answer = "trả lời [a1]"
    tool_returned = {
        "a1": {"chunk_id": "a1", "doc": "d", "section": "s", "text": "trả lời", "score": 0.9}
    }
    search_trace = []
    reasoning = ""
    low_confidence = False


def test_telemetry_module_removed():
    with pytest.raises(ModuleNotFoundError):
        import observability.telemetry  # noqa: F401


def test_ask_submits_feedback_scores(make_service):
    svc = make_service()
    fake_result = FakeAgentResult()
    with patch.object(svc.chat, "agent") as mock_agent:
        mock_agent.ask_agent.return_value = fake_result
        with patch("service.container.submit_feedback") as fb:
            payload = svc.chat.ask("câu hỏi?")
    assert payload["answer"]
    called_keys = {c.args[0] for c in fb.call_args_list}
    assert {"invalid_citations", "unsupported_claims", "low_confidence"} <= called_keys


def test_ask_stream_yields_done_with_payload(make_service):
    svc = make_service()

    def events():
        yield {"type": "answer", "delta": "xin chào"}
        yield {"type": "_final", "result": FakeAgentResult()}

    with patch.object(svc.chat, "agent") as mock_agent:
        mock_agent.stream_agent.return_value = iter(events())
        collected = list(svc.chat.ask_stream("hi"))
    types = [e["type"] for e in collected]
    assert types[-1] == "done"
    done = collected[-1]
    assert done["answer"] == "trả lời [a1]"

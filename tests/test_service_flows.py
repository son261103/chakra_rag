"""Service flows với fake LLM + fake embedder: không mạng, chạy nhanh, deterministic."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from chakra_rag.config import Config

# 11-key payload contract (ask() return và event "done" của ask_stream)
PAYLOAD_KEYS = {
    "question",
    "answer",
    "mode",
    "citations",
    "invalid_citations",
    "unsupported_claims",
    "search_trace",
    "reasoning",
    "low_confidence",
    "latency_ms",
    "conversation_id",
}


@pytest.fixture()
def service(tmp_path, monkeypatch):
    from chakra_rag.service import rag_service as rs

    fake_embedder = MagicMock(return_value=None)
    fake_embedder.dim = 4
    fake_embedder.embed_one = lambda t: [0.0] * 4
    monkeypatch.setattr(rs, "Embedder", MagicMock(return_value=fake_embedder))
    cfg = Config(db_path=tmp_path / "s.db", uploads_dir=tmp_path, logs_dir=tmp_path / "logs")
    svc = rs.RagService(cfg)
    yield svc
    svc.close()


def test_ask_happy_path_stores_turn(service):
    fr = MagicMock()
    fr.answer = "trả lời [c1]"
    fr.tool_returned = {
        "c1": {"chunk_id": "c1", "doc": "d", "section": "s", "text": "trả lời đây", "score": 0.8}
    }
    fr.search_trace = [{"query": "q", "n_results": 1, "chunk_ids": ["c1"], "max_score": 0.8}]  # noqa: E501
    fr.reasoning = ""
    fr.low_confidence = False
    fr.mode = "agent"

    cid = service.store.create_conversation()["id"]
    with patch.object(service, "agent") as ag:
        ag.ask.return_value = fr
        payload = service.ask("hỏi gì đó", conversation_id=cid)
    assert payload["low_confidence"] is False
    msgs = service.store.list_messages(cid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["payload"] is not None  # payload_json vẫn ghi (UI replay cần)


def test_stream_done_event_validated(service):
    fr = MagicMock()
    fr.answer = "ok"
    fr.tool_returned = {}
    fr.search_trace = []
    fr.reasoning = ""
    fr.low_confidence = True
    fr.mode = "agent"

    def gen():
        yield {"type": "thinking", "delta": "hm"}
        yield {"type": "_final", "result": fr}

    with patch.object(service, "agent") as ag:
        ag.stream_agent.return_value = iter(gen())
        events = list(service.ask_stream("x"))
    assert events[0]["type"] == "thinking"
    assert events[-1]["type"] == "done"
    assert events[-1]["low_confidence"] is True


def test_ask_payload_exact_key_contract(service):
    """Khóa payload của ask() phải đúng 11 key — không thừa, không thiếu."""
    fr = MagicMock()
    fr.answer = "trả lời [c1]"
    fr.tool_returned = {
        "c1": {"chunk_id": "c1", "doc": "d", "section": "s", "text": "trả lời đây", "score": 0.8}
    }
    fr.search_trace = []
    fr.reasoning = ""
    fr.low_confidence = False
    fr.mode = "agent"

    with patch.object(service, "agent") as ag:
        ag.ask.return_value = fr
        payload = service.ask("hỏi gì đó")
    assert set(payload.keys()) == PAYLOAD_KEYS


def test_stream_done_payload_exact_key_contract(service):
    """Event "done" của ask_stream mang đúng 11 key payload (+ type)."""
    fr = MagicMock()
    fr.answer = "ok"
    fr.tool_returned = {}
    fr.search_trace = []
    fr.reasoning = ""
    fr.low_confidence = False
    fr.mode = "agent"

    def gen():
        yield {"type": "_final", "result": fr}

    with patch.object(service, "agent") as ag:
        ag.stream_agent.return_value = iter(gen())
        events = list(service.ask_stream("x"))
    assert events[-1]["type"] == "done"
    assert set(events[-1].keys()) - {"type"} == PAYLOAD_KEYS


def test_ask_feedback_score_values(service):
    """submit_feedback được gọi với giá trị đúng: invalid_citations/unsupported_claims là số lượng, low_confidence là 0/1."""  # noqa: E501
    fr = MagicMock()
    fr.answer = "Công ty tặng xe máy [c1] [fake1]."
    fr.tool_returned = {
        "c1": {
            "chunk_id": "c1",
            "doc": "d",
            "section": "s",
            "text": "thời tiết hôm nay đẹp",
            "score": 0.1,
        }
    }
    fr.search_trace = []
    fr.reasoning = ""
    fr.low_confidence = True
    fr.mode = "agent"

    with patch.object(service, "agent") as ag:
        ag.ask.return_value = fr
        with patch("chakra_rag.service.rag_service.submit_feedback") as fb:
            service.ask("hỏi gì đó")
    scores = {c.args[0]: c.args[1] for c in fb.call_args_list}
    assert scores["invalid_citations"] == 1  # [fake1] không nằm trong tool_returned
    assert scores["unsupported_claims"] == 1  # claim không được chunk đỡ
    assert scores["low_confidence"] == 1  # int(bool(True))

"""Tầng ghép nối (composition root): khởi tạo các thành phần và orchestrate luồng ask.

Cả API lẫn CLI đều đi qua `RagService` — không nơi nào tự ghép pipeline,
để logic chỉ tồn tại một chỗ.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from chakra_rag.core.agent import AgentResult, RagAgent
from chakra_rag.config import Config, get_config
from chakra_rag.core.embedding import Embedder
from chakra_rag.core.retrieval import Retriever
from chakra_rag.storage.store import Store
from chakra_rag.observability.telemetry import Telemetry, elapsed_ms, timed
from chakra_rag.core.verification import VerifiedAnswer, verify_answer

logger = logging.getLogger(__name__)


class RagService:
    """Facade duy nhất của ứng dụng: giữ store/embedder/retriever/agent."""

    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or get_config()
        self.cfg.ensure_dirs()
        self.embedder = Embedder(self.cfg.embed_model)
        self.store = Store(self.cfg.db_path, embed_dim=self.embedder.dim)
        self.retriever = Retriever(
            self.store,
            self.embedder,
            top_k=self.cfg.top_k,
            rrf_k=self.cfg.rrf_k,
            min_score=self.cfg.min_score,
        )
        self.agent = RagAgent(self.cfg, self.retriever)
        self.telemetry = Telemetry(self.cfg.logs_dir)

    def _history_for_conversation(self, conversation_id: str | None) -> list[dict[str, str]]:
        if not conversation_id:
            return []
        return self.store.list_history_for_llm(
            conversation_id, max_turns=self.cfg.chat_history_turns
        )

    def _persist_turn(
        self,
        conversation_id: str | None,
        question: str,
        payload: dict[str, Any],
    ) -> str | None:
        """Lưu user + assistant vào conversation; auto-title từ câu hỏi đầu. Trả về conversation_id."""
        if not conversation_id:
            return None
        conv = self.store.get_conversation(conversation_id)
        if conv is None:
            return None
        prior = self.store.list_messages(conversation_id)
        self.store.add_message(conversation_id, "user", question)
        self.store.add_message(
            conversation_id,
            "assistant",
            payload.get("answer") or "",
            payload=payload,
        )
        if not prior and (not conv.get("title") or conv["title"] == "Hội thoại mới"):
            title = question.strip().replace("\n", " ")
            if len(title) > 60:
                title = title[:57].rstrip() + "…"
            self.store.rename_conversation(conversation_id, title or "Hội thoại mới")
        return conversation_id

    def ask(
        self,
        question: str,
        mode: str = "agent",
        top_k: int | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Hỏi → agent loop → verify citations → log → trả về payload chuẩn."""
        if top_k:
            self.retriever.top_k = top_k

        history = self._history_for_conversation(conversation_id)
        t0 = timed()
        logger.info(
            "ask start mode=%s conv=%s history_turns=%d q=%r",
            mode,
            conversation_id,
            len(history) // 2,
            question[:120],
        )
        agent_result: AgentResult = self.agent.ask(question, mode=mode, history=history)
        verified: VerifiedAnswer = verify_answer(
            agent_result.answer,
            agent_result.tool_returned,
            low_confidence=agent_result.low_confidence,
            support_threshold=self.cfg.support_threshold,
        )
        latency = elapsed_ms(t0)

        payload = {
            "question": question,
            "answer": verified.answer,
            "mode": agent_result.mode,
            "citations": verified.citations,
            "invalid_citations": verified.invalid_citations,
            "unsupported_claims": verified.unsupported_claims,
            "search_trace": agent_result.search_trace,
            "reasoning": agent_result.reasoning,
            "low_confidence": verified.low_confidence,
            "latency_ms": latency,
            "conversation_id": conversation_id,
        }

        self._persist_turn(conversation_id, question, payload)

        self.telemetry.log_ask(
            {
                "question": question,
                "mode": agent_result.mode,
                "conversation_id": conversation_id,
                "tool_calls": [
                    {"query": t["query"], "n_results": t["n_results"], "max_score": t["max_score"]}
                    for t in agent_result.search_trace
                ],
                "answer": verified.answer,
                "citations": [c["chunk_id"] for c in verified.citations],
                "invalid_citations": verified.invalid_citations,
                "unsupported_claims": verified.unsupported_claims,
                "low_confidence": verified.low_confidence,
                "latency_ms": latency,
            }
        )
        logger.info(
            "ask done mode=%s latency_ms=%d tools=%d citations=%d low_conf=%s",
            agent_result.mode,
            latency,
            len(agent_result.search_trace),
            len(verified.citations),
            verified.low_confidence,
        )
        return payload

    def ask_stream(
        self,
        question: str,
        mode: str = "agent",
        top_k: int | None = None,
        conversation_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Streaming version của ask(): pass-through events của agent, cuối cùng
        verify citations + log telemetry rồi phát event "done" với payload chuẩn.

        UI nhận events theo thời gian thực (thinking gõ dần, tool call hiện ngay,
        answer gõ dần) và dùng event "done" để chốt trạng thái cuối.
        """
        if top_k:
            self.retriever.top_k = top_k

        history = self._history_for_conversation(conversation_id)
        t0 = timed()
        logger.info(
            "ask_stream start mode=%s conv=%s history_turns=%d q=%r",
            mode,
            conversation_id,
            len(history) // 2,
            question[:120],
        )
        final: AgentResult | None = None
        for event in self.agent.stream_agent(question, history=history):
            if event["type"] == "_final":
                final = event["result"]
                continue
            if event.get("type") == "error":
                logger.error("ask_stream agent error: %s", event.get("message"))
            yield event

        if final is None:
            logger.warning("ask_stream ended without final result conv=%s", conversation_id)
            return  # stream_agent đã phát event "error"

        verified: VerifiedAnswer = verify_answer(
            final.answer,
            final.tool_returned,
            low_confidence=final.low_confidence,
            support_threshold=self.cfg.support_threshold,
        )
        latency = elapsed_ms(t0)

        payload = {
            "question": question,
            "answer": verified.answer,
            "mode": final.mode,
            "citations": verified.citations,
            "invalid_citations": verified.invalid_citations,
            "unsupported_claims": verified.unsupported_claims,
            "search_trace": final.search_trace,
            "reasoning": final.reasoning,
            "low_confidence": verified.low_confidence,
            "latency_ms": latency,
            "conversation_id": conversation_id,
        }

        self._persist_turn(conversation_id, question, payload)

        self.telemetry.log_ask(
            {
                "question": question,
                "mode": final.mode,
                "conversation_id": conversation_id,
                "tool_calls": [
                    {"query": t["query"], "n_results": t["n_results"], "max_score": t["max_score"]}
                    for t in final.search_trace
                ],
                "answer": verified.answer,
                "citations": [c["chunk_id"] for c in verified.citations],
                "invalid_citations": verified.invalid_citations,
                "unsupported_claims": verified.unsupported_claims,
                "low_confidence": verified.low_confidence,
                "latency_ms": latency,
                "streamed": True,
            }
        )
        logger.info(
            "ask_stream done mode=%s latency_ms=%d tools=%d citations=%d low_conf=%s",
            final.mode,
            latency,
            len(final.search_trace),
            len(verified.citations),
            verified.low_confidence,
        )
        yield {"type": "done", **payload}

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        return self.store.get_chunk(chunk_id)

    def close(self) -> None:
        self.store.close()

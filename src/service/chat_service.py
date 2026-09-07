"""Service điều phối luồng hỏi đáp RAG (Agent, Retrieval, Verification, Streaming)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from agent.agent import AgentResult, RagAgent
from config import Config, get_config
from core.verification import VerifiedAnswer, verify_answer
from observability.timing import elapsed_ms, timed
from observability.tracing import trace_metadata
from repositories import ChunkRepository
from service.conversation_service import ConversationService

logger = logging.getLogger(__name__)


class ChatService:
    """Nghiệp vụ hỏi đáp RAG: điều phối Agent, kiểm tra trích dẫn và stream kết quả."""

    def __init__(
        self,
        chunk_repo: ChunkRepository,
        agent: RagAgent,
        conversations: ConversationService,
        cfg: Config | None = None,
    ):
        self.chunk_repo = chunk_repo
        self.agent = agent
        self.conversations = conversations
        self.cfg = cfg or get_config()

    def _prepare_question(
        self,
        question: str,
        conversation_id: str | None,
        *,
        log_label: str,
    ) -> list[dict[str, str]]:
        """Prelude chung cho ask/ask_stream: lấy history + log start.

        top_k KHÔNG bị ghi vào Retriever dùng chung ở đây — nó được truyền
        tường minh theo từng request (xem ask/ask_stream), tránh request này
        làm đổi trạng thái của request khác đang chạy song song.
        """
        history = self.conversations.list_history_for_llm(conversation_id)
        logger.info(
            "%s start conv=%s history_turns=%d q=%r",
            log_label,
            conversation_id,
            len(history) // 2,
            question[:120],
        )
        return history

    def _build_payload(
        self,
        question: str,
        verified: VerifiedAnswer,
        result: AgentResult,
        latency_ms: int,
        conversation_id: str | None,
    ) -> dict[str, Any]:
        return {
            "question": question,
            "answer": verified.answer,
            "citations": verified.citations,
            "invalid_citations": verified.invalid_citations,
            "unsupported_claims": verified.unsupported_claims,
            "search_trace": result.search_trace,
            "reasoning": result.reasoning,
            "low_confidence": verified.low_confidence,
            "latency_ms": latency_ms,
            "conversation_id": conversation_id,
        }

    def _submit_quality_feedback(self, verified: VerifiedAnswer) -> None:
        """Ghi 3 feedback scores lên root run LangSmith (no-op khi chưa cấu hình)."""
        import service.container as rs

        rs.submit_feedback(
            "invalid_citations",
            len(verified.invalid_citations),
            comment=", ".join(verified.invalid_citations),
        )
        rs.submit_feedback(
            "unsupported_claims",
            len(verified.unsupported_claims),
            comment="; ".join(verified.unsupported_claims[:5]),
        )
        rs.submit_feedback("low_confidence", int(bool(verified.low_confidence)))

    def ask(
        self,
        question: str,
        top_k: int | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Hỏi → agent loop → verify citations → log → trả về payload chuẩn.

        top_k là override theo request cho lượt retrieve dự phòng khi agent
        loop lỗi (agent.py fallback) — truyền tường minh, không đụng shared state.
        """
        history = self._prepare_question(question, conversation_id, log_label="ask")
        t0 = timed()
        agent_cfg = trace_metadata(conversation_id, streamed=False)
        agent_result: AgentResult = self.agent.ask_agent(
            question, history=history, config=agent_cfg, top_k=top_k
        )
        verified: VerifiedAnswer = verify_answer(
            agent_result.answer,
            agent_result.tool_returned,
            low_confidence=agent_result.low_confidence,
            support_threshold=self.cfg.support_threshold,
        )
        latency = elapsed_ms(t0)

        payload = self._build_payload(question, verified, agent_result, latency, conversation_id)
        self.conversations.persist_turn(conversation_id, question, payload)
        self._submit_quality_feedback(verified)
        logger.info(
            "ask done latency_ms=%d tools=%d citations=%d low_conf=%s",
            latency,
            len(agent_result.search_trace),
            len(verified.citations),
            verified.low_confidence,
        )
        return payload

    def ask_stream(
        self,
        question: str,
        top_k: int | None = None,
        conversation_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Streaming version của ask(): pass-through events của agent và verify cuối cùng.

        top_k chỉ có tác dụng ở luồng đồng bộ (lượt retrieve dự phòng trong
        fallback của ask_agent) — luồng stream không có lượt dự phòng nên
        không dùng đến; vẫn nhận vào để giữ nguyên hợp đồng API.
        """
        history = self._prepare_question(
            question, conversation_id, log_label="ask_stream"
        )
        t0 = timed()
        agent_cfg = trace_metadata(conversation_id, streamed=True)
        final: AgentResult | None = None
        for event in self.agent.stream_agent(question, history=history, config=agent_cfg):
            if event["type"] == "_final":
                final = event["result"]
                continue
            if event.get("type") == "error":
                logger.error("ask_stream agent error: %s", event.get("message"))
            yield event

        if final is None:
            logger.warning("ask_stream ended without final result conv=%s", conversation_id)
            return

        verified: VerifiedAnswer = verify_answer(
            final.answer,
            final.tool_returned,
            low_confidence=final.low_confidence,
            support_threshold=self.cfg.support_threshold,
        )
        latency = elapsed_ms(t0)

        payload = self._build_payload(question, verified, final, latency, conversation_id)
        self.conversations.persist_turn(conversation_id, question, payload)
        self._submit_quality_feedback(verified)
        logger.info(
            "ask_stream done latency_ms=%d tools=%d citations=%d low_conf=%s",
            latency,
            len(final.search_trace),
            len(verified.citations),
            verified.low_confidence,
        )
        yield {"type": "done", **payload}

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        """Lấy thông tin chunk gốc để phục vụ xem trích dẫn."""
        return self.chunk_repo.get_chunk(chunk_id)

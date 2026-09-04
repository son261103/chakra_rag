"""Tầng ghép nối (composition root): khởi tạo các thành phần và orchestrate luồng ask.

Cả API lẫn CLI đều đi qua `RagService` — không nơi nào tự ghép pipeline,
để logic chỉ tồn tại một chỗ.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from chakra_rag.config import Config, get_config
from chakra_rag.core.agent import AgentResult, RagAgent
from chakra_rag.core.embedding import Embedder
from chakra_rag.core.retrieval import Retriever
from chakra_rag.core.verification import VerifiedAnswer, verify_answer
from chakra_rag.observability.timing import elapsed_ms, timed
from chakra_rag.observability.tracing import submit_feedback, trace_metadata
from chakra_rag.storage.store import Store

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
        self._ensure_default_integration()
        self.agent = RagAgent(self.cfg, self.retriever, store=self.store)

    def _ensure_default_integration(self) -> None:
        """Nếu DB chưa có tích hợp nào, khởi tạo cấu hình mặc định vào database."""
        try:
            if self.store.count_integrations() == 0:
                from chakra_rag.core.security import encrypt_integration_key

                model_name = self.cfg.llm_model or "gpt-4o-mini"
                base_url = self.cfg.llm_base_url or "https://api.openai.com/v1"
                enc = encrypt_integration_key(self.cfg.llm_api_key, self.cfg.encryption_key)
                self.store.create_integration(
                    name="OpenAI (Mặc định)",
                    model=model_name,
                    base_url=base_url,
                    provider="openai",
                    encrypted_api_key=enc.encrypted_api_key,
                    encrypted_dek=enc.encrypted_dek,
                    is_active=True,
                )
                logger.info("Đã khởi tạo tích hợp LLM mặc định vào database.")
        except Exception:
            logger.exception("Lỗi khi tạo tích hợp mặc định từ .env (bỏ qua)")

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
        """Lưu user + assistant vào conversation; auto-title từ câu hỏi đầu. Trả về conversation_id."""  # noqa: E501
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

    def _prepare_question(
        self,
        question: str,
        top_k: int | None,
        conversation_id: str | None,
        *,
        mode: str,
        log_label: str,
    ) -> list[dict[str, str]]:
        """Prelude chung cho ask/ask_stream: clamp top_k + lấy history + log start."""
        if top_k:
            self.retriever.top_k = top_k
        history = self._history_for_conversation(conversation_id)
        logger.info(
            "%s start mode=%s conv=%s history_turns=%d q=%r",
            log_label,
            mode,
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
            "mode": result.mode,
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
        submit_feedback("invalid_citations", len(verified.invalid_citations),
                        comment=", ".join(verified.invalid_citations))
        submit_feedback("unsupported_claims", len(verified.unsupported_claims),
                        comment="; ".join(verified.unsupported_claims[:5]))
        submit_feedback("low_confidence", int(bool(verified.low_confidence)))

    def ask(
        self,
        question: str,
        mode: str = "agent",
        top_k: int | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Hỏi → agent loop → verify citations → log → trả về payload chuẩn."""
        history = self._prepare_question(
            question, top_k, conversation_id, mode=mode, log_label="ask"
        )
        t0 = timed()
        agent_cfg = trace_metadata(conversation_id, mode, streamed=False)
        agent_result: AgentResult = self.agent.ask(
            question, mode=mode, history=history, config=agent_cfg
        )
        verified: VerifiedAnswer = verify_answer(
            agent_result.answer,
            agent_result.tool_returned,
            low_confidence=agent_result.low_confidence,
            support_threshold=self.cfg.support_threshold,
        )
        latency = elapsed_ms(t0)

        payload = self._build_payload(question, verified, agent_result, latency, conversation_id)

        self._persist_turn(conversation_id, question, payload)

        self._submit_quality_feedback(verified)
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
        verify citations + submit feedback scores rồi phát event "done" với payload chuẩn.

        UI nhận events theo thời gian thực (thinking gõ dần, tool call hiện ngay,
        answer gõ dần) và dùng event "done" để chốt trạng thái cuối.
        """
        history = self._prepare_question(
            question, top_k, conversation_id, mode=mode, log_label="ask_stream"
        )
        t0 = timed()
        agent_cfg = trace_metadata(conversation_id, mode, streamed=True)
        final: AgentResult | None = None
        for event in self.agent.stream_agent(
            question, history=history, config=agent_cfg
        ):
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

        payload = self._build_payload(question, verified, final, latency, conversation_id)

        self._persist_turn(conversation_id, question, payload)

        self._submit_quality_feedback(verified)
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

    def get_active_integration_info(self) -> dict[str, Any]:
        """Lấy thông tin cấu hình LLM đang kích hoạt (đã che API key)."""
        from chakra_rag.core.security import decrypt_integration_key, mask_api_key

        active = self.store.get_active_integration()
        if not active:
            return {
                "id": "env-fallback",
                "name": "Môi trường (.env)",
                "provider": "openai",
                "base_url": self.cfg.llm_base_url,
                "model": self.cfg.llm_model,
                "masked_api_key": mask_api_key(self.cfg.llm_api_key),
                "has_api_key": bool(self.cfg.llm_api_key),
                "is_active": True,
            }
        try:
            raw_key = decrypt_integration_key(
                active.get("encrypted_api_key", ""),
                active.get("encrypted_dek", ""),
                self.cfg.encryption_key,
            )
        except Exception:
            raw_key = ""
        return {
            "id": active["id"],
            "name": active["name"],
            "provider": active.get("provider", "openai"),
            "base_url": active["base_url"],
            "model": active["model"],
            "masked_api_key": mask_api_key(raw_key),
            "has_api_key": bool(raw_key),
            "is_active": True,
            "created_at": active.get("created_at"),
            "updated_at": active.get("updated_at"),
        }

    def reload_agent(self) -> None:
        """Xóa cache agent khi cấu hình tích hợp thay đổi để lượt hỏi tiếp theo áp dụng ngay."""
        self.agent.invalidate_agent()

    def test_llm_connection(
        self,
        model: str,
        base_url: str,
        api_key: str,
    ) -> dict[str, Any]:
        """Kiểm tra kết nối tới provider LLM với thông số truyền vào."""
        from chakra_rag.core.llm import ThinkingChatOpenAI

        start = timed()
        llm = ThinkingChatOpenAI(
            model=model.strip(),
            base_url=base_url.strip(),
            api_key=api_key.strip() or "not-needed",
            temperature=0,
            timeout=min(self.cfg.llm_timeout, 20.0),
            max_retries=1,
            max_tokens=16,
        )
        resp = llm.invoke("Hi")
        ms = elapsed_ms(start)
        return {
            "ok": True,
            "model": model,
            "response": str(resp.content).strip()[:100],
            "latency_ms": ms,
        }

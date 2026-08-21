"""Tầng ghép nối (composition root): khởi tạo các thành phần và orchestrate luồng ask.

Cả API lẫn CLI đều đi qua `RagService` — không nơi nào tự ghép pipeline,
để logic chỉ tồn tại một chỗ.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict
from typing import Any

from chakra_rag.core.agent import AgentResult, RagAgent
from chakra_rag.config import Config, get_config
from chakra_rag.core.embedding import Embedder
from chakra_rag.core.retrieval import Retriever
from chakra_rag.storage.store import Store
from chakra_rag.observability.telemetry import Telemetry, elapsed_ms, timed
from chakra_rag.core.verification import VerifiedAnswer, verify_answer


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

    def ask(self, question: str, mode: str = "agent", top_k: int | None = None) -> dict[str, Any]:
        """Hỏi → agent loop → verify citations → log → trả về payload chuẩn."""
        if top_k:
            self.retriever.top_k = top_k

        t0 = timed()
        agent_result: AgentResult = self.agent.ask(question, mode=mode)
        verified: VerifiedAnswer = verify_answer(
            agent_result.answer,
            agent_result.tool_returned,
            low_confidence=agent_result.low_confidence,
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
        }

        self.telemetry.log_ask(
            {
                "question": question,
                "mode": agent_result.mode,
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
        return payload

    def ask_stream(self, question: str, mode: str = "agent", top_k: int | None = None) -> Iterator[dict[str, Any]]:
        """Streaming version của ask(): pass-through events của agent, cuối cùng
        verify citations + log telemetry rồi phát event "done" với payload chuẩn.

        UI nhận events theo thời gian thực (thinking gõ dần, tool call hiện ngay,
        answer gõ dần) và dùng event "done" để chốt trạng thái cuối.
        """
        if top_k:
            self.retriever.top_k = top_k

        t0 = timed()
        final: AgentResult | None = None
        for event in self.agent.stream_agent(question):
            if event["type"] == "_final":
                final = event["result"]
                continue
            yield event

        if final is None:
            return  # stream_agent đã phát event "error"

        verified: VerifiedAnswer = verify_answer(
            final.answer,
            final.tool_returned,
            low_confidence=final.low_confidence,
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
        }

        self.telemetry.log_ask(
            {
                "question": question,
                "mode": final.mode,
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
        yield {"type": "done", **payload}

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        return self.store.get_chunk(chunk_id)

    def close(self) -> None:
        self.store.close()

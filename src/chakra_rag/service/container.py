"""Composition root & container: khởi tạo hạ tầng và liên kết các domain service.

Các domain service chuyên biệt:
- `chat`: ChatService (RAG agent loop, retrieval, verification, streaming)
- `conversations`: ConversationService (lịch sử, tin nhắn, auto-titling)
- `files`: FileService (upload, listing, chunk inspector, reingest)
- `integrations`: IntegrationService (quản lý LLM provider, mã hóa DEK/KEK, test kết nối)
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from chakra_rag.config import Config, get_config
from chakra_rag.core.agent import RagAgent
from chakra_rag.core.embedding import Embedder
from chakra_rag.core.retrieval import Retriever
from chakra_rag.ingestion.worker import IngestWorker
from chakra_rag.observability.tracing import submit_feedback  # noqa: F401
from chakra_rag.service.chat_service import ChatService
from chakra_rag.service.conversation_service import ConversationService
from chakra_rag.service.file_service import FileService
from chakra_rag.service.integration_service import IntegrationService
from chakra_rag.storage.store import Store

logger = logging.getLogger(__name__)


class ServiceContainer:
    """Container gom và khởi tạo các domain services của ứng dụng."""

    def __init__(self, cfg: Config | None = None, worker: IngestWorker | None = None):
        self.cfg = cfg or get_config()
        self.cfg.ensure_dirs()
        self.embedder = Embedder(self.cfg.embed_model)
        self.store = Store(self.cfg.db_path, embed_dim=self.embedder.dim)
        self.worker = worker

        # 1. Integration Service (quản lý model & API key)
        self.integrations = IntegrationService(
            self.store, self.cfg, on_change=self.reload_agent
        )
        self.integrations.ensure_default_integration()

        # 2. Retrieval & Agent
        self.retriever = Retriever(
            self.store,
            self.embedder,
            top_k=self.cfg.top_k,
            rrf_k=self.cfg.rrf_k,
            min_score=self.cfg.min_score,
        )
        self.agent = RagAgent(self.cfg, self.retriever, store=self.store)

        # 3. Conversation Service
        self.conversations = ConversationService(self.store, self.cfg)

        # 4. File Service
        self.files = FileService(self.store, self.worker, self.cfg)

        # 5. Chat Service (RAG execution)
        self.chat = ChatService(
            self.store,
            self.retriever,
            self.agent,
            self.conversations,
            self.cfg,
        )

    def attach_worker(self, worker: IngestWorker) -> None:
        """Gắn IngestWorker sau khi worker được khởi chạy (từ lifespan FastAPI)."""
        self.worker = worker
        self.files.worker = worker

    # ---------- Delegation methods (backward compatibility) ----------

    def ask(
        self,
        question: str,
        mode: str = "agent",
        top_k: int | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        self.chat.agent = self.agent
        self.chat.retriever = self.retriever
        return self.chat.ask(question, mode=mode, top_k=top_k, conversation_id=conversation_id)

    def ask_stream(
        self,
        question: str,
        mode: str = "agent",
        top_k: int | None = None,
        conversation_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        self.chat.agent = self.agent
        self.chat.retriever = self.retriever
        return self.chat.ask_stream(
            question, mode=mode, top_k=top_k, conversation_id=conversation_id
        )

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        return self.chat.get_chunk(chunk_id)

    def get_active_integration_info(self) -> dict[str, Any]:
        return self.integrations.get_active_integration_info()

    def reload_agent(self) -> None:
        self.agent.invalidate_agent()

    def test_llm_connection(
        self,
        model: str,
        base_url: str,
        api_key: str,
    ) -> dict[str, Any]:
        return self.integrations.test_connection(model, base_url, api_key=api_key)

    def close(self) -> None:
        self.store.close()


# Alias hỗ trợ backward compatibility
RagService = ServiceContainer

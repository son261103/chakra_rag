"""Composition root & container: khởi tạo hạ tầng và liên kết các domain service.

Tầng dữ liệu: `Database` (storage/connection.py) = SQLAlchemy engine + schema;
các repository (repositories/, SQLAlchemy Core) chứa truy vấn theo domain và
được wire vào service.

Các domain service chuyên biệt:
- `chat`: ChatService (RAG agent loop, retrieval, verification, streaming)
- `conversations`: ConversationService (lịch sử, tin nhắn, auto-titling)
- `files`: FileService (upload, listing, chunk inspector, reingest)
- `integrations`: IntegrationService (quản lý LLM provider, mã hóa DEK/KEK, test kết nối)
"""

from __future__ import annotations

from agent.agent import RagAgent
from config import Config, get_config
from core.embedding import Embedder
from core.retrieval import Retriever
from ingestion.worker import IngestWorker
from observability.tracing import submit_feedback  # noqa: F401
from repositories import (
    ChunkRepository,
    ConversationRepository,
    FileRepository,
    IntegrationRepository,
)
from service.chat_service import ChatService
from service.conversation_service import ConversationService
from service.file_service import FileService
from service.integration_service import IntegrationService
from storage.connection import Database


class ServiceContainer:
    """Container gom và khởi tạo các domain services của ứng dụng."""

    def __init__(self, cfg: Config | None = None, worker: IngestWorker | None = None):
        self.cfg = cfg or get_config()
        self.cfg.ensure_dirs()
        self.embedder = Embedder(self.cfg.embed_model)
        # Database = SQLAlchemy engine + schema; repositories (SQLAlchemy Core)
        # chứa truy vấn theo domain.
        self.db = Database(self.cfg.db_path, embed_dim=self.embedder.dim)
        self.chunk_repo = ChunkRepository(self.db)
        self.file_repo = FileRepository(self.db)
        self.conversation_repo = ConversationRepository(self.db)
        self.integration_repo = IntegrationRepository(self.db)
        self.worker = worker

        # 1. Integration Service (quản lý model & API key)
        self.integrations = IntegrationService(
            self.integration_repo, self.cfg, on_change=self.reload_agent
        )
        self.integrations.ensure_default_integration()

        # 2. Retrieval & Agent
        self.retriever = Retriever(
            self.chunk_repo,
            self.embedder,
            top_k=self.cfg.top_k,
            rrf_k=self.cfg.rrf_k,
            min_score=self.cfg.min_score,
        )
        self.agent = RagAgent(
            self.cfg,
            self.retriever,
            chunk_repo=self.chunk_repo,
            file_repo=self.file_repo,
            integration_repo=self.integration_repo,
        )

        # 3. Conversation Service
        self.conversations = ConversationService(self.conversation_repo, self.cfg)

        # 4. File Service
        self.files = FileService(self.file_repo, self.chunk_repo, self.worker, self.cfg)

        # 5. Chat Service (RAG execution)
        self.chat = ChatService(
            self.chunk_repo,
            self.retriever,
            self.agent,
            self.conversations,
            self.cfg,
        )

    def attach_worker(self, worker: IngestWorker) -> None:
        """Gắn IngestWorker sau khi worker được khởi chạy (từ lifespan FastAPI)."""
        self.worker = worker
        self.files.worker = worker

    def reload_agent(self) -> None:
        self.agent.invalidate_agent()

    def close(self) -> None:
        self.db.close()


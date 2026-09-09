"""Repository — tầng truy vấn theo domain, viết bằng SQLAlchemy Core trên
`Database` (storage/connection.py).

- `ChunkRepository`        : chunks + vec0 + FTS5 (vec/FTS5 qua text() — extension).
- `FileRepository`         : metadata file ingest.
- `ConversationRepository` : hội thoại + tin nhắn.
- `IntegrationRepository`  : cấu hình LLM provider.
- `EmbeddingIntegrationRepository`: cấu hình embedding provider (API + số chiều).
"""

from repositories.chunk_repository import ChunkRepository
from repositories.conversation_repository import ConversationRepository
from repositories.embedding_integration_repository import EmbeddingIntegrationRepository
from repositories.file_repository import FileRepository
from repositories.integration_repository import IntegrationRepository

__all__ = [
    "ChunkRepository",
    "ConversationRepository",
    "EmbeddingIntegrationRepository",
    "FileRepository",
    "IntegrationRepository",
]

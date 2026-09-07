"""Repository — tầng truy vấn SQL theo domain, dùng chung `Database` (storage/connection).

- `ChunkRepository`        : chunks + vec0 + FTS5 (tìm kiếm hybrid).
- `FileRepository`         : metadata file ingest.
- `ConversationRepository` : hội thoại + tin nhắn.
- `IntegrationRepository`  : cấu hình LLM provider.
"""

from repositories.chunk_repository import ChunkRepository
from repositories.conversation_repository import ConversationRepository
from repositories.file_repository import FileRepository
from repositories.integration_repository import IntegrationRepository

__all__ = [
    "ChunkRepository",
    "ConversationRepository",
    "FileRepository",
    "IntegrationRepository",
]

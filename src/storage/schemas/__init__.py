"""Gói chứa các schema DDL tách biệt theo từng bảng/domain dữ liệu."""

from __future__ import annotations

from storage.schemas.chunks import CHUNKS_SCHEMA
from storage.schemas.conversations import CONVERSATIONS_SCHEMA
from storage.schemas.embedding_integrations import (
    EMBEDDING_INTEGRATIONS_MIGRATIONS,
    EMBEDDING_INTEGRATIONS_SCHEMA,
)
from storage.schemas.files import FILES_MIGRATIONS, FILES_SCHEMA
from storage.schemas.integrations import INTEGRATIONS_SCHEMA
from storage.schemas.messages import MESSAGES_SCHEMA

# Thứ tự tạo bảng: chunks & files -> conversations -> messages (FK) -> integrations
TABLE_SCHEMAS: list[str] = [
    CHUNKS_SCHEMA,
    FILES_SCHEMA,
    CONVERSATIONS_SCHEMA,
    MESSAGES_SCHEMA,
    INTEGRATIONS_SCHEMA,
    EMBEDDING_INTEGRATIONS_SCHEMA,
]

# Phần schema không chứa `{dim}` — chạy trước khi biết số chiều embedding
# (Database tự resolve dimension từ embedding_integrations đang active).
NONCHUNKS_SCHEMAS: list[str] = [
    FILES_SCHEMA,
    CONVERSATIONS_SCHEMA,
    MESSAGES_SCHEMA,
    INTEGRATIONS_SCHEMA,
    EMBEDDING_INTEGRATIONS_SCHEMA,
]

# Migration cộng dồn cho DB tạo từ phiên bản cũ (chạy sau toàn bộ CREATE TABLE,
# ADD COLUMN IF NOT EXISTS nên chạy lại vô hại).
SCHEMA_MIGRATIONS: list[str] = [
    FILES_MIGRATIONS,
    EMBEDDING_INTEGRATIONS_MIGRATIONS,
]

__all__ = [
    "CHUNKS_SCHEMA",
    "FILES_SCHEMA",
    "CONVERSATIONS_SCHEMA",
    "MESSAGES_SCHEMA",
    "INTEGRATIONS_SCHEMA",
    "EMBEDDING_INTEGRATIONS_SCHEMA",
    "TABLE_SCHEMAS",
    "NONCHUNKS_SCHEMAS",
    "SCHEMA_MIGRATIONS",
]

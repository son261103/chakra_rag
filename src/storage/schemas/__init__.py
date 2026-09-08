"""Gói chứa các schema DDL tách biệt theo từng bảng/domain dữ liệu."""

from __future__ import annotations

from storage.schemas.chunks import CHUNKS_SCHEMA
from storage.schemas.conversations import CONVERSATIONS_SCHEMA
from storage.schemas.files import FILES_SCHEMA
from storage.schemas.integrations import INTEGRATIONS_SCHEMA
from storage.schemas.messages import MESSAGES_SCHEMA

# Thứ tự tạo bảng: chunks & files -> conversations -> messages (FK) -> integrations
TABLE_SCHEMAS: list[str] = [
    CHUNKS_SCHEMA,
    FILES_SCHEMA,
    CONVERSATIONS_SCHEMA,
    MESSAGES_SCHEMA,
    INTEGRATIONS_SCHEMA,
]

__all__ = [
    "CHUNKS_SCHEMA",
    "FILES_SCHEMA",
    "CONVERSATIONS_SCHEMA",
    "MESSAGES_SCHEMA",
    "INTEGRATIONS_SCHEMA",
    "TABLE_SCHEMAS",
]

"""Định nghĩa toàn bộ schema PostgreSQL: bảng + chỉ mục (DDL thuần, không logic truy vấn).

File này đóng vai trò là nguồn sự thật duy nhất (single entrypoint) tổng hợp
DDL từ các module schema riêng lẻ trong package `storage/schemas/`.

- `chunks`          : text + metadata + vector embedding (pgvector) + tsvector (FTS).
- `files`           : trạng thái ingest từng file (phục vụ UI: danh sách file, %).
- `conversations`   : danh sách hội thoại.
- `messages`        : lịch sử tin nhắn (payload JSON cho UI replay).
- `llm_integrations`: cấu hình LLM provider (API key mã hóa).
- `embedding_integrations`: cấu hình embedding provider (API key mã hóa + số chiều).

`SCHEMA` chứa placeholder `{dim}` cho số chiều embedding của vector — `Database`
(connection.py) format trước khi execute lúc khởi tạo. `SCHEMA_NO_CHUNKS` là phần
không phụ thuộc `{dim}` — chạy trước khi resolve dimension từ bảng
`embedding_integrations`.
"""

from __future__ import annotations

from storage.schemas import (
    CHUNKS_SCHEMA,
    CONVERSATIONS_SCHEMA,
    EMBEDDING_INTEGRATIONS_SCHEMA,
    FILES_SCHEMA,
    INTEGRATIONS_SCHEMA,
    MESSAGES_SCHEMA,
    NONCHUNKS_SCHEMAS,
    TABLE_SCHEMAS,
)

SCHEMA = "\n\n".join(TABLE_SCHEMAS).strip() + "\n"
SCHEMA_NO_CHUNKS = "\n\n".join(NONCHUNKS_SCHEMAS).strip() + "\n"

__all__ = [
    "SCHEMA",
    "SCHEMA_NO_CHUNKS",
    "CHUNKS_SCHEMA",
    "FILES_SCHEMA",
    "CONVERSATIONS_SCHEMA",
    "MESSAGES_SCHEMA",
    "INTEGRATIONS_SCHEMA",
    "EMBEDDING_INTEGRATIONS_SCHEMA",
    "TABLE_SCHEMAS",
    "NONCHUNKS_SCHEMAS",
]

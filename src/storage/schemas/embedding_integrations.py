"""Schema DDL cho bảng `embedding_integrations`: embedding provider (API) + số chiều."""

from __future__ import annotations

EMBEDDING_INTEGRATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS embedding_integrations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    use_batch INTEGER NOT NULL DEFAULT 0,
    encrypted_api_key TEXT NOT NULL,
    encrypted_dek TEXT NOT NULL,
    is_active INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_embedding_integrations_active
    ON embedding_integrations(is_active);
""".strip()

# DB cũ chưa có cột `use_batch` — ADD COLUMN IF NOT EXISTS chạy lại vô hại.
EMBEDDING_INTEGRATIONS_MIGRATIONS = """
ALTER TABLE embedding_integrations ADD COLUMN IF NOT EXISTS use_batch INTEGER NOT NULL DEFAULT 0;
""".strip()


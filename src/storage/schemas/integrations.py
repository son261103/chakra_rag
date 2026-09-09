"""Định nghĩa schema DDL cho bảng `llm_integrations`: cấu hình LLM provider & API key mã hóa."""

from __future__ import annotations

INTEGRATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_integrations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model TEXT NOT NULL,
    encrypted_api_key TEXT NOT NULL,
    encrypted_dek TEXT NOT NULL,
    is_active INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_integrations_active
    ON llm_integrations(is_active);
""".strip()

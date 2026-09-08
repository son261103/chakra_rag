"""Định nghĩa schema DDL cho bảng `conversations`: danh sách phiên hội thoại."""

from __future__ import annotations

CONVERSATIONS_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
""".strip()

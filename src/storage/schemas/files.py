"""Định nghĩa schema DDL cho bảng `files`: trạng thái ingest từng file (phục vụ UI)."""

from __future__ import annotations

FILES_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    file_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'upload',
    status TEXT NOT NULL DEFAULT 'queued',
    chunks_total INTEGER NOT NULL DEFAULT 0,
    chunks_done INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    batch_job_id TEXT NOT NULL DEFAULT '',
    batch_meta TEXT NOT NULL DEFAULT ''
);
""".strip()

# DB cũ chưa có cột batch — ADD COLUMN IF NOT EXISTS chạy lại vô hại.
FILES_MIGRATIONS = """
ALTER TABLE files ADD COLUMN IF NOT EXISTS batch_job_id TEXT NOT NULL DEFAULT '';
ALTER TABLE files ADD COLUMN IF NOT EXISTS batch_meta TEXT NOT NULL DEFAULT '';
""".strip()

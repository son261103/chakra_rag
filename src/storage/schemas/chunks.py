"""Định nghĩa schema DDL cho bảng `chunks`: vector embedding (pgvector) + tsvector (FTS)."""

from __future__ import annotations

CHUNKS_SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

CREATE TABLE IF NOT EXISTS chunks (
    id BIGSERIAL PRIMARY KEY,
    chunk_id TEXT UNIQUE NOT NULL,
    doc TEXT NOT NULL,
    section TEXT NOT NULL,
    text TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end INTEGER NOT NULL,
    embedding vector({dim}) NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc);
CREATE INDEX IF NOT EXISTS idx_chunks_char_pos ON chunks(doc, char_start, id);
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON chunks USING gin(tsv);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks USING hnsw (embedding vector_l2_ops);
""".strip()

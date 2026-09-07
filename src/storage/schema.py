"""Định nghĩa toàn bộ schema SQLite: bảng + chỉ mục (DDL thuần, không logic truy vấn).

- `chunks`     : bảng thường — text + metadata (nguồn của trích dẫn).
- `vec_chunks` : sqlite-vec (vec0) — vector embedding, rowid = chunks.id.
- `fts_chunks` : FTS5 — chỉ mục lexical, content đồng bộ với chunks.
- `files`      : trạng thái ingest từng file (phục vụ UI: danh sách file, %).
- `conversations` / `messages`: lịch sử hội thoại (payload JSON cho UI replay).
- `llm_integrations`: cấu hình LLM provider (API key mã hóa).

Vector + metadata + lexical nằm cùng một database nên join ra citation rất gọn
và mọi thao tác ingest đều transactional.

`SCHEMA` chứa placeholder `{dim}` cho số chiều embedding của vec0 — `Database`
(connection.py) format trước khi executescript lúc khởi tạo.
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id         INTEGER PRIMARY KEY,
    chunk_id   TEXT UNIQUE NOT NULL,
    doc        TEXT NOT NULL,
    section    TEXT NOT NULL,
    text       TEXT NOT NULL,
    char_start INTEGER NOT NULL,
    char_end   INTEGER NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    embedding float[{dim}]
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
    text,
    content='chunks',
    content_rowid='id'
);

CREATE TABLE IF NOT EXISTS files (
    file_id      TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'upload',  -- 'seed' | 'upload'
    status       TEXT NOT NULL DEFAULT 'queued',  -- queued|parsing|chunking|embedding|ready|failed
    chunks_total INTEGER NOT NULL DEFAULT 0,
    chunks_done  INTEGER NOT NULL DEFAULT 0,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL,
    role             TEXT NOT NULL,  -- 'user' | 'assistant'
    content          TEXT NOT NULL,
    payload_json     TEXT,           -- AskResponse JSON cho assistant
    created_at       TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation
    ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS llm_integrations (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    provider          TEXT NOT NULL DEFAULT 'openai',
    base_url          TEXT NOT NULL DEFAULT 'https://api.openai.com/v1',
    model             TEXT NOT NULL,
    encrypted_api_key TEXT NOT NULL DEFAULT '',
    encrypted_dek     TEXT NOT NULL DEFAULT '',
    is_active         INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_integrations_active
    ON llm_integrations(is_active);
"""

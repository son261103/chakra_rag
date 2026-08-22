"""Tầng lưu trữ: một file SQLite duy nhất chứa cả 3 chỉ mục.

- `chunks`     : bảng thường — text + metadata (nguồn của trích dẫn).
- `vec_chunks` : sqlite-vec (vec0) — vector embedding, rowid = chunks.id.
- `fts_chunks` : FTS5 — chỉ mục lexical, content đồng bộ với chunks.
- `files`      : trạng thái ingest từng file (phục vụ UI: danh sách file, %).

Vector + metadata + lexical nằm cùng một database nên join ra citation rất gọn
và mọi thao tác ingest đều transactional.

Về thread-safety: ingest worker chạy ở thread riêng, FastAPI endpoint chạy ở
threadpool, tất cả dùng chung Store này. Một connection sqlite3 KHÔNG an toàn
khi dùng đồng thời từ nhiều thread (kể cả với check_same_thread=False — cờ đó
chỉ tắt kiểm tra, không thêm bảo vệ). Vì vậy mọi thao tác DB đều đi qua một
RLock để serialize truy cập trên connection duy nhất.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import sqlite_vec


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex

_SCHEMA = """
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
"""


def _serialize(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


class Store:
    """SQLite + sqlite-vec + FTS5. Một connection duy nhất, serialize bằng RLock."""

    def __init__(self, db_path: Path | str, embed_dim: int = 384):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False để connection dùng được từ worker thread lẫn
        # threadpool của FastAPI; an toàn thực sự do self._lock bên dưới.
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        self.conn.executescript(_SCHEMA.format(dim=embed_dim))
        self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ---------- chunks ----------

    def insert_chunk(
        self,
        chunk_id: str,
        doc: str,
        section: str,
        text: str,
        char_start: int,
        char_end: int,
        embedding: np.ndarray,
    ) -> int:
        """Thêm 1 chunk vào cả 3 chỉ mục. Trả về rowid."""
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO chunks (chunk_id, doc, section, text, char_start, char_end)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (chunk_id, doc, section, text, char_start, char_end),
            )
            rowid = cur.lastrowid
            self.conn.execute(
                "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
                (rowid, _serialize(embedding)),
            )
            self.conn.execute(
                "INSERT INTO fts_chunks (rowid, text) VALUES (?, ?)",
                (rowid, text),
            )
            self.conn.commit()
            return rowid

    def delete_chunks_by_doc(self, doc: str) -> int:
        """Xóa toàn bộ chunk của một tài liệu (dùng khi ingest lại file)."""
        with self._lock:
            rowids = [r["id"] for r in self.conn.execute(
                "SELECT id FROM chunks WHERE doc = ?", (doc,)
            )]
            if not rowids:
                return 0
            placeholders = ",".join("?" * len(rowids))
            self.conn.execute(f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})", rowids)
            self.conn.execute(f"DELETE FROM fts_chunks WHERE rowid IN ({placeholders})", rowids)
            self.conn.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", rowids)
            self.conn.commit()
            return len(rowids)

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_chunks_by_doc(self, doc: str) -> list[dict[str, Any]]:
        """Toàn bộ chunk của một tài liệu, theo thứ tự vị trí trong file."""
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT id, chunk_id, doc, section, text, char_start, char_end
                FROM chunks
                WHERE doc = ?
                ORDER BY char_start ASC, id ASC
                """,
                (doc,),
            ).fetchall()
        return [dict(row) for row in rows]

    def count_chunks(self) -> int:
        with self._lock:
            return self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    # ---------- vector search ----------

    def vector_search(self, query_embedding: np.ndarray, top_k: int) -> list[dict[str, Any]]:
        """KNN bằng khoảng cách L2 (vector đã chuẩn hóa ⇒ tương đương cosine).

        Corpus nhỏ nên brute-force quét tuyến tính là lựa chọn đúng,
        không cần ANN index.
        """
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT c.chunk_id, c.doc, c.section, c.text, c.char_start, c.char_end,
                       v.distance
                FROM vec_chunks v
                JOIN chunks c ON c.id = v.rowid
                WHERE v.embedding MATCH ? AND v.k = ?
                ORDER BY v.distance
                """,
                (_serialize(query_embedding), top_k),
            ).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            # distance L2 của vector chuẩn hóa ∈ [0, 2] → similarity ∈ [0, 1]
            item["score"] = 1.0 - item.pop("distance") / 2.0
            results.append(item)
        return results

    # ---------- lexical search ----------

    def fts_search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        """BM25 trên FTS5. Escape query để tránh lỗi cú pháp FTS5."""
        safe_query = _fts_escape(query)
        if not safe_query:
            return []
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT c.chunk_id, c.doc, c.section, c.text, c.char_start, c.char_end,
                       bm25(fts_chunks) AS rank
                FROM fts_chunks
                JOIN chunks c ON c.id = fts_chunks.rowid
                WHERE fts_chunks MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (safe_query, top_k),
            ).fetchall()
        return [dict(row) for row in rows]

    # ---------- files ----------

    def upsert_file(
        self,
        file_id: str,
        name: str,
        source: str = "upload",
        status: str = "queued",
        chunks_total: int = 0,
    ) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO files (file_id, name, source, status, chunks_total)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(file_id) DO UPDATE SET
                    name = excluded.name,
                    status = excluded.status,
                    chunks_total = excluded.chunks_total,
                    chunks_done = 0,
                    error = NULL
                """,
                (file_id, name, source, status, chunks_total),
            )
            self.conn.commit()

    def set_file_status(self, file_id: str, status: str, error: str | None = None) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE files SET status = ?, error = ? WHERE file_id = ?",
                (status, error, file_id),
            )
            self.conn.commit()

    def set_file_progress(self, file_id: str, chunks_done: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE files SET chunks_done = ? WHERE file_id = ?",
                (chunks_done, file_id),
            )
            self.conn.commit()

    def list_files(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT file_id, name, source, status, chunks_total, chunks_done, error"
                " FROM files ORDER BY rowid"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM files WHERE file_id = ?", (file_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_file(self, file_id: str) -> dict[str, Any] | None:
        """Xóa metadata file + mọi chunk của doc cùng tên. Trả về row đã xóa hoặc None."""
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM files WHERE file_id = ?", (file_id,)
            ).fetchone()
            if row is None:
                return None
            meta = dict(row)
            doc = meta["name"]
            rowids = [
                r["id"]
                for r in self.conn.execute("SELECT id FROM chunks WHERE doc = ?", (doc,))
            ]
            if rowids:
                placeholders = ",".join("?" * len(rowids))
                self.conn.execute(f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})", rowids)
                self.conn.execute(f"DELETE FROM fts_chunks WHERE rowid IN ({placeholders})", rowids)
                self.conn.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", rowids)
            self.conn.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
            self.conn.commit()
            meta["chunks_removed"] = len(rowids)
            return meta

    def fail_interrupted_ingests(self) -> int:
        """Đánh failed các job dở (queued/parsing/…) sau restart — không tự nhúng lại."""
        with self._lock:
            cur = self.conn.execute(
                """
                UPDATE files
                SET status = 'failed',
                    error = 'Bị gián đoạn khi server dừng — bấm Nhúng lại RAG'
                WHERE status IN ('queued', 'parsing', 'chunking', 'embedding')
                """
            )
            self.conn.commit()
            return cur.rowcount

    # ---------- conversations / messages ----------

    def create_conversation(self, title: str = "Hội thoại mới") -> dict[str, Any]:
        cid = _new_id()
        now = _utcnow_iso()
        with self._lock:
            self.conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (cid, title, now, now),
            )
            self.conn.commit()
        return {"id": cid, "title": title, "created_at": now, "updated_at": now}

    def list_conversations(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT c.id, c.title, c.created_at, c.updated_at,
                       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
                FROM conversations c
                ORDER BY c.updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def rename_conversation(self, conversation_id: str, title: str) -> None:
        now = _utcnow_iso()
        with self._lock:
            self.conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, conversation_id),
            )
            self.conn.commit()

    def touch_conversation(self, conversation_id: str) -> None:
        now = _utcnow_iso()
        with self._lock:
            self.conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            self.conn.commit()

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._lock:
            # SQLite FK cascade cần PRAGMA; xóa messages thủ công cho chắc.
            self.conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            cur = self.conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            self.conn.commit()
            return cur.rowcount > 0

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mid = _new_id()
        now = _utcnow_iso()
        payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (mid, conversation_id, role, content, payload_json, now),
            )
            self.conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            self.conn.commit()
        return {
            "id": mid,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "payload": payload,
            "created_at": now,
        }

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT id, conversation_id, role, content, payload_json, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (conversation_id,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = item.pop("payload_json", None)
            if raw:
                try:
                    item["payload"] = json.loads(raw)
                except json.JSONDecodeError:
                    item["payload"] = None
            else:
                item["payload"] = None
            out.append(item)
        return out

    def list_history_for_llm(self, conversation_id: str, max_turns: int = 8) -> list[dict[str, str]]:
        """Lấy tối đa max_turns cặp user/assistant gần nhất (chỉ role + content text)."""
        messages = self.list_messages(conversation_id)
        # Giữ đúng thứ tự thời gian; cắt theo số message (2 * turns).
        limit = max(0, max_turns) * 2
        trimmed = messages[-limit:] if limit else []
        return [{"role": m["role"], "content": m["content"]} for m in trimmed if m["role"] in ("user", "assistant")]


def _fts_escape(query: str) -> str:
    """Biến query tự do thành FTS5 query an toàn: mỗi token thành một phrase.

    FTS5 unicode61 không tách từ tiếng Việt hoàn hảo, nhưng bắt exact term tốt;
    nối các token bằng OR để không bỏ sót kết quả khi một token không khớp.
    """
    tokens = [t for t in query.replace('"', " ").split() if t]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)

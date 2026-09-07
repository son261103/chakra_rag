"""Truy vấn chunk: bảng `chunks` + vec0 (`vec_chunks`) + FTS5 (`fts_chunks`).

Đây là tầng truy vấn SQL theo domain — DDL tương ứng nằm ở storage/schema.py.
Vector search (sqlite-vec) và BM25 (FTS5) là SQL đặc thù của extension nên
giữ raw string thay vì nhét vào ORM.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from storage.connection import Database


def _serialize(vector: np.ndarray) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def _fts_escape(query: str) -> str:
    """Biến query tự do thành FTS5 query an toàn: mỗi token thành một phrase.

    FTS5 unicode61 không tách từ tiếng Việt hoàn hảo, nhưng bắt exact term tốt;
    nối các token bằng OR để không bỏ sót kết quả khi một token không khớp.
    """
    tokens = [t for t in query.replace('"', " ").split() if t]
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


class ChunkRepository:
    """Truy vấn chunk + chỉ mục tìm kiếm (vector & lexical) trên một `Database`."""

    def __init__(self, db: Database):
        self.db = db

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
        with self.db.lock:
            cur = self.db.conn.execute(
                "INSERT INTO chunks (chunk_id, doc, section, text, char_start, char_end)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (chunk_id, doc, section, text, char_start, char_end),
            )
            rowid = cur.lastrowid
            self.db.conn.execute(
                "INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
                (rowid, _serialize(embedding)),
            )
            self.db.conn.execute(
                "INSERT INTO fts_chunks (rowid, text) VALUES (?, ?)",
                (rowid, text),
            )
            self.db.conn.commit()
            return rowid

    def delete_chunks_by_doc(self, doc: str) -> int:
        """Xóa toàn bộ chunk của một tài liệu (dùng khi ingest lại file)."""
        with self.db.lock:
            rowids = [
                r["id"]
                for r in self.db.conn.execute("SELECT id FROM chunks WHERE doc = ?", (doc,))
            ]
            if not rowids:
                return 0
            placeholders = ",".join("?" * len(rowids))
            self.db.conn.execute(
                f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})", rowids
            )
            self.db.conn.execute(
                f"DELETE FROM fts_chunks WHERE rowid IN ({placeholders})", rowids
            )
            self.db.conn.execute(
                f"DELETE FROM chunks WHERE id IN ({placeholders})", rowids
            )
            self.db.conn.commit()
            return len(rowids)

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_chunk_neighborhood(self, chunk_id: str) -> dict[str, Any] | None:
        """Chunk được hỏi + đúng 1 chunk kề trước/sau trong cùng tài liệu.

        read_chunk dùng điều này để trả cả vùng ngữ cảnh (đúng tinh thần
        Read của Claude Code): chunk dễ cắt lỡ câu, ngữ cảnh kề giúp LLM
        hiểu trọn ý mà không phải nạp cả tài liệu. Trả None khi chunk_id
        không tồn tại.
        """
        with self.db.lock:
            center = self.db.conn.execute(
                "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
            ).fetchone()
            if center is None:
                return None
            before = self.db.conn.execute(
                """
                SELECT chunk_id, doc, section, text FROM chunks
                WHERE doc = ? AND (char_start, id) < (?, ?)
                ORDER BY char_start DESC, id DESC LIMIT 1
                """,
                (center["doc"], center["char_start"], center["id"]),
            ).fetchall()
            after = self.db.conn.execute(
                """
                SELECT chunk_id, doc, section, text FROM chunks
                WHERE doc = ? AND (char_start, id) > (?, ?)
                ORDER BY char_start ASC, id ASC LIMIT 1
                """,
                (center["doc"], center["char_start"], center["id"]),
            ).fetchall()
        return {
            "chunk": dict(center),
            "before": [dict(r) for r in before],
            "after": [dict(r) for r in after],
        }

    def list_chunks_by_doc(self, doc: str) -> list[dict[str, Any]]:
        """Toàn bộ chunk của một tài liệu, theo thứ tự vị trí trong file."""
        with self.db.lock:
            rows = self.db.conn.execute(
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
        with self.db.lock:
            return self.db.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]

    # ---------- vector search ----------

    def vector_search(self, query_embedding: np.ndarray, top_k: int) -> list[dict[str, Any]]:
        """KNN bằng khoảng cách L2 (vector đã chuẩn hóa ⇒ tương đương cosine).

        Corpus nhỏ nên brute-force quét tuyến tính là lựa chọn đúng,
        không cần ANN index.
        """
        with self.db.lock:
            rows = self.db.conn.execute(
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
        with self.db.lock:
            rows = self.db.conn.execute(
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

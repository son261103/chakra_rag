"""Truy vấn chunk: bảng `chunks` + vec0 (`vec_chunks`) + FTS5 (`fts_chunks`).

Viết bằng SQLAlchemy Core (bảng `chunks` reflect từ DB — schema.py là nguồn
DDL duy nhất, không duplicate định nghĩa). Riêng vec0/FTS5 là extension không
mô hình hóa được bằng expression → giữ `text()` cho MATCH và ghi/xóa virtual
table. DDL tương ứng nằm ở storage/schema.py.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sqlalchemy import MetaData, Table, and_, delete, func, insert, or_, select
from sqlalchemy import text as sql_text

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


def _delete_chunk_rows(conn, chunks_table: Table, rowids: list[int]) -> None:
    """Xóa hàng chunk ở cả 3 chỉ mục (chunks + vec_chunks + fts_chunks).

    Chạy trong transaction của `conn` đang mở — dùng chung cho xóa theo doc
    (ChunkRepository) và xóa file kèm chunk (FileRepository) để khỏi duplicate.
    vec/fts là virtual table nên xóa qua text().
    """
    if not rowids:
        return
    placeholders = ", ".join(f":id{i}" for i in range(len(rowids)))
    params = {f"id{i}": value for i, value in enumerate(rowids)}
    conn.execute(
        sql_text(f"DELETE FROM vec_chunks WHERE rowid IN ({placeholders})"), params
    )
    conn.execute(
        sql_text(f"DELETE FROM fts_chunks WHERE rowid IN ({placeholders})"), params
    )
    conn.execute(delete(chunks_table).where(chunks_table.c.id.in_(rowids)))


class ChunkRepository:
    """Truy vấn chunk + chỉ mục tìm kiếm (vector & lexical) trên một `Database`."""

    def __init__(self, db: Database):
        self.db = db
        meta = MetaData()
        # Reflect từ DB thật: schema.py giữ định nghĩa, không khai báo lại cột ở đây.
        self.chunks = Table("chunks", meta, autoload_with=db.engine)

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
        with self.db.engine.begin() as conn:
            rowid = conn.execute(
                insert(self.chunks)
                .values(
                    chunk_id=chunk_id,
                    doc=doc,
                    section=section,
                    text=text,
                    char_start=char_start,
                    char_end=char_end,
                )
                .returning(self.chunks.c.id)
            ).scalar_one()
            conn.execute(
                sql_text("INSERT INTO vec_chunks (rowid, embedding) VALUES (:rowid, :embedding)"),
                {"rowid": rowid, "embedding": _serialize(embedding)},
            )
            conn.execute(
                sql_text("INSERT INTO fts_chunks (rowid, text) VALUES (:rowid, :text)"),
                {"rowid": rowid, "text": text},
            )
        return rowid

    def delete_chunks_by_doc(self, doc: str) -> int:
        """Xóa toàn bộ chunk của một tài liệu (dùng khi ingest lại file)."""
        with self.db.engine.begin() as conn:
            rowids = conn.execute(
                select(self.chunks.c.id).where(self.chunks.c.doc == doc)
            ).scalars().all()
            if not rowids:
                return 0
            _delete_chunk_rows(conn, self.chunks, rowids)
        return len(rowids)

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        with self.db.engine.connect() as conn:
            row = conn.execute(
                select(self.chunks).where(self.chunks.c.chunk_id == chunk_id)
            ).mappings().first()
        return dict(row) if row else None

    def get_chunk_neighborhood(self, chunk_id: str) -> dict[str, Any] | None:
        """Chunk được hỏi + đúng 1 chunk kề trước/sau trong cùng tài liệu.

        read_chunk dùng điều này để trả cả vùng ngữ cảnh (đúng tinh thần
        Read của Claude Code): chunk dễ cắt lỡ câu, ngữ cảnh kề giúp LLM
        hiểu trọn ý mà không phải nạp cả tài liệu. Trả None khi chunk_id
        không tồn tại.
        """
        with self.db.engine.connect() as conn:
            center_row = conn.execute(
                select(self.chunks).where(self.chunks.c.chunk_id == chunk_id)
            ).mappings().first()
            if center_row is None:
                return None
            center = dict(center_row)
            # So khớp "(char_start, id) < (?, ?)" — tuple-compare của SQLite
            # tương đương char_start nhỏ hơn, hoặc bằng mà id nhỏ hơn.
            before_cond = or_(
                self.chunks.c.char_start < center["char_start"],
                and_(
                    self.chunks.c.char_start == center["char_start"],
                    self.chunks.c.id < center["id"],
                ),
            )
            after_cond = or_(
                self.chunks.c.char_start > center["char_start"],
                and_(
                    self.chunks.c.char_start == center["char_start"],
                    self.chunks.c.id > center["id"],
                ),
            )
            cols = (
                self.chunks.c.chunk_id,
                self.chunks.c.doc,
                self.chunks.c.section,
                self.chunks.c.text,
            )
            before = conn.execute(
                select(*cols)
                .where(self.chunks.c.doc == center["doc"], before_cond)
                .order_by(self.chunks.c.char_start.desc(), self.chunks.c.id.desc())
                .limit(1)
            ).mappings().all()
            after = conn.execute(
                select(*cols)
                .where(self.chunks.c.doc == center["doc"], after_cond)
                .order_by(self.chunks.c.char_start.asc(), self.chunks.c.id.asc())
                .limit(1)
            ).mappings().all()
        return {
            "chunk": center,
            "before": [dict(r) for r in before],
            "after": [dict(r) for r in after],
        }

    def list_chunks_by_doc(self, doc: str) -> list[dict[str, Any]]:
        """Toàn bộ chunk của một tài liệu, theo thứ tự vị trí trong file."""
        cols = (
            self.chunks.c.id,
            self.chunks.c.chunk_id,
            self.chunks.c.doc,
            self.chunks.c.section,
            self.chunks.c.text,
            self.chunks.c.char_start,
            self.chunks.c.char_end,
        )
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                select(*cols)
                .where(self.chunks.c.doc == doc)
                .order_by(self.chunks.c.char_start.asc(), self.chunks.c.id.asc())
            ).mappings().all()
        return [dict(row) for row in rows]

    def count_chunks(self) -> int:
        with self.db.engine.connect() as conn:
            return conn.scalar(select(func.count()).select_from(self.chunks))

    # ---------- vector search ----------

    def vector_search(self, query_embedding: np.ndarray, top_k: int) -> list[dict[str, Any]]:
        """KNN bằng khoảng cách L2 (vector đã chuẩn hóa ⇒ tương đương cosine).

        Corpus nhỏ nên brute-force quét tuyến tính là lựa chọn đúng,
        không cần ANN index. MATCH của vec0 không viết bằng expression được.
        """
        sql = """
        SELECT c.chunk_id, c.doc, c.section, c.text, c.char_start, c.char_end,
               v.distance
        FROM vec_chunks v
        JOIN chunks c ON c.id = v.rowid
        WHERE v.embedding MATCH :vec AND v.k = :k
        ORDER BY v.distance
        """
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                sql_text(sql), {"vec": _serialize(query_embedding), "k": top_k}
            ).mappings().all()
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
        sql = """
        SELECT c.chunk_id, c.doc, c.section, c.text, c.char_start, c.char_end,
               bm25(fts_chunks) AS rank
        FROM fts_chunks
        JOIN chunks c ON c.id = fts_chunks.rowid
        WHERE fts_chunks MATCH :query
        ORDER BY rank
        LIMIT :k
        """
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                sql_text(sql), {"query": safe_query, "k": top_k}
            ).mappings().all()
        return [dict(row) for row in rows]

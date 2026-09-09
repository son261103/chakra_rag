"""Truy vấn chunk: bảng `chunks` tích hợp pgvector và PostgreSQL Full-Text Search (tsvector).

Viết bằng SQLAlchemy Core (bảng `chunks` reflect từ DB — schema.py là nguồn
DDL duy nhất, không duplicate định nghĩa).
Vector search dùng toán tử khoảng cách L2 của pgvector (<->).
Lexical search dùng tsvector với ts_rank.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np
from pgvector.sqlalchemy import Vector  # noqa: F401
from sqlalchemy import MetaData, Table, and_, delete, func, insert, or_, select
from sqlalchemy import text as sql_text

from storage.connection import Database


def _fts_escape(query: str) -> str:
    """Biến query tự do thành tsquery an toàn với các từ khóa phân tách bởi OR (|)."""
    cleaned = re.sub(r"[^\w\s]", " ", query)
    tokens = [t.strip() for t in cleaned.split() if t.strip()]
    if not tokens:
        return ""
    return " | ".join(f"'{t}'" for t in tokens)


def _delete_chunk_rows(conn, chunks_table: Table, rowids: list[int]) -> None:
    """Xóa các hàng chunk theo danh sách id."""
    if not rowids:
        return
    conn.execute(delete(chunks_table).where(chunks_table.c.id.in_(rowids)))


class ChunkRepository:
    """Truy vấn chunk + chỉ mục tìm kiếm (vector pgvector & lexical FTS) trên một `Database`."""

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
        """Thêm 1 chunk vào bảng chunks (pgvector + FTS tự động). Trả về id."""
        emb_val = embedding.tolist() if isinstance(embedding, np.ndarray) else embedding
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
                    embedding=emb_val,
                )
                .returning(self.chunks.c.id)
            ).scalar_one()
        return rowid

    def delete_chunks_by_doc(self, doc: str) -> int:
        """Xóa toàn bộ chunk của một tài liệu (dùng khi ingest lại file)."""
        with self.db.engine.begin() as conn:
            result = conn.execute(delete(self.chunks).where(self.chunks.c.doc == doc))
        return result.rowcount

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
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
            row = conn.execute(
                select(*cols).where(self.chunks.c.chunk_id == chunk_id)
            ).mappings().first()
        return dict(row) if row else None

    def get_chunk_neighborhood(self, chunk_id: str) -> dict[str, Any] | None:
        """Chunk được hỏi + đúng 1 chunk kề trước/sau trong cùng tài liệu.

        read_chunk dùng điều này để trả cả vùng ngữ cảnh:
        chunk dễ cắt lỡ câu, ngữ cảnh kề giúp LLM hiểu trọn ý mà không
        phải nạp cả tài liệu. Trả None khi chunk_id không tồn tại.
        """
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
            center_row = conn.execute(
                select(*cols).where(self.chunks.c.chunk_id == chunk_id)
            ).mappings().first()
            if center_row is None:
                return None
            center = dict(center_row)
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
            before_cols = (
                self.chunks.c.chunk_id,
                self.chunks.c.doc,
                self.chunks.c.section,
                self.chunks.c.text,
            )
            before = conn.execute(
                select(*before_cols)
                .where(self.chunks.c.doc == center["doc"], before_cond)
                .order_by(self.chunks.c.char_start.desc(), self.chunks.c.id.desc())
                .limit(1)
            ).mappings().all()
            after = conn.execute(
                select(*before_cols)
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
            return conn.scalar(select(func.count()).select_from(self.chunks)) or 0

    # ---------- số chiều cột vector ----------

    def vector_dimension(self) -> int | None:
        """Chiều thực tế của cột `chunks.embedding` (pgvector lưu atttypmod = dim + 4).

        Trả None nếu bảng/chưa có dimension ràng buộc.
        """
        sql = (
            "SELECT atttypmod FROM pg_attribute "
            "WHERE attrelid = 'chunks'::regclass "
            "AND attname = 'embedding' AND NOT attisdropped"
        )
        with self.db.engine.connect() as conn:
            typmod = conn.scalar(sql_text(sql))
        if typmod is None or int(typmod) < 0:
            return None
        return int(typmod) - 4

    def migrate_dimension(self, new_dim: int) -> None:
        """Đổi chiều cột embedding: hạ HNSW index → truncate chunks → ALTER TYPE → tạo lại index.

        Vector cũ vô nghĩa với model chiều khác — CHỈ gọi sau khi user xác nhận
        đổi chiều trong UI (file giữ nguyên trên đĩa + bảng files, reingest thủ công).
        """
        new_dim = int(new_dim)
        if new_dim <= 0:
            raise ValueError("dimension phải là số nguyên dương")
        with self.db.engine.begin() as conn:
            conn.execute(sql_text("DROP INDEX IF EXISTS idx_chunks_embedding"))
            conn.execute(sql_text("TRUNCATE TABLE chunks"))
            conn.execute(
                sql_text(f"ALTER TABLE chunks ALTER COLUMN embedding TYPE vector({new_dim})")
            )
            conn.execute(
                sql_text(
                    "CREATE INDEX idx_chunks_embedding "
                    "ON chunks USING hnsw (embedding vector_l2_ops)"
                )
            )

    # ---------- vector search ----------

    def vector_search(self, query_embedding: np.ndarray, top_k: int) -> list[dict[str, Any]]:
        """KNN bằng khoảng cách L2 qua pgvector (<->).

        Vector đã chuẩn hóa L2 ⇒ khoảng cách L2 ∈ [0, 2] tương đương cosine.
        """
        emb_val = (
            query_embedding.tolist()
            if isinstance(query_embedding, np.ndarray)
            else query_embedding
        )
        sql = """
        SELECT chunk_id, doc, section, text, char_start, char_end,
               (embedding <-> :vec) AS distance
        FROM chunks
        ORDER BY distance ASC
        LIMIT :k
        """
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                sql_text(sql), {"vec": str(emb_val), "k": top_k}
            ).mappings().all()
        results = []
        for row in rows:
            item = dict(row)
            # distance L2 của vector chuẩn hóa ∈ [0, 2] → similarity ∈ [0, 1]
            item["score"] = 1.0 - float(item.pop("distance")) / 2.0
            results.append(item)
        return results

    # ---------- lexical search ----------

    def fts_search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        """Tìm kiếm lexical bằng PostgreSQL Full-Text Search (tsvector + ts_rank)."""
        safe_query = _fts_escape(query)
        if not safe_query:
            return []
        sql = """
        SELECT chunk_id, doc, section, text, char_start, char_end,
               ts_rank(tsv, to_tsquery('simple', :query)) AS rank
        FROM chunks
        WHERE tsv @@ to_tsquery('simple', :query)
        ORDER BY rank DESC
        LIMIT :k
        """
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                sql_text(sql), {"query": safe_query, "k": top_k}
            ).mappings().all()
        return [dict(row) for row in rows]

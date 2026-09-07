"""Truy vấn bảng `files`: trạng thái ingest từng file (phục vụ UI danh sách + %).

SQLAlchemy Core; bảng reflect từ DB (schema.py là nguồn DDL duy nhất).
`delete_file` có cascade sang chunk (vec/fts) trong cùng transaction — việc xóa
doc gắn với vòng đời file nên giữ trọn ở đây thay vì tách nửa vời sang
ChunkRepository. Xóa vec/fts vẫn là `text()` vì virtual table.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, Table, delete, select, update
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from repositories.chunk_repository import _delete_chunk_rows
from storage.connection import Database


class FileRepository:
    """Truy vấn metadata file ingest trên một `Database`."""

    def __init__(self, db: Database):
        self.db = db
        meta = MetaData()
        self.files = Table("files", meta, autoload_with=db.engine)
        self.chunks = Table("chunks", meta, autoload_with=db.engine)

    def upsert_file(
        self,
        file_id: str,
        name: str,
        source: str = "upload",
        status: str = "queued",
        chunks_total: int = 0,
    ) -> None:
        stmt = sqlite_insert(self.files).values(
            file_id=file_id,
            name=name,
            source=source,
            status=status,
            chunks_total=chunks_total,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[self.files.c.file_id],
            set_={
                "name": name,
                "status": status,
                "chunks_total": chunks_total,
                "chunks_done": 0,
                "error": None,
            },
        )
        with self.db.engine.begin() as conn:
            conn.execute(stmt)

    def set_file_status(self, file_id: str, status: str, error: str | None = None) -> None:
        with self.db.engine.begin() as conn:
            conn.execute(
                update(self.files)
                .where(self.files.c.file_id == file_id)
                .values(status=status, error=error)
            )

    def set_file_progress(self, file_id: str, chunks_done: int) -> None:
        with self.db.engine.begin() as conn:
            conn.execute(
                update(self.files)
                .where(self.files.c.file_id == file_id)
                .values(chunks_done=chunks_done)
            )

    def list_files(self) -> list[dict[str, Any]]:
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                select(self.files).order_by(sql_text("rowid"))
            ).mappings().all()
        return [dict(row) for row in rows]

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        with self.db.engine.connect() as conn:
            row = conn.execute(
                select(self.files).where(self.files.c.file_id == file_id)
            ).mappings().first()
        return dict(row) if row else None

    def delete_file(self, file_id: str) -> dict[str, Any] | None:
        """Xóa metadata file + mọi chunk của doc cùng tên. Trả về row đã xóa hoặc None."""
        with self.db.engine.begin() as conn:
            row = conn.execute(
                select(self.files).where(self.files.c.file_id == file_id)
            ).mappings().first()
            if row is None:
                return None
            meta = dict(row)
            doc = meta["name"]
            rowids = conn.execute(
                select(self.chunks.c.id).where(self.chunks.c.doc == doc)
            ).scalars().all()
            _delete_chunk_rows(conn, self.chunks, rowids)
            conn.execute(delete(self.files).where(self.files.c.file_id == file_id))
        meta["chunks_removed"] = len(rowids)
        return meta

    def fail_interrupted_ingests(self) -> int:
        """Đánh failed các job dở (queued/parsing/…) sau restart — không tự nhúng lại."""
        with self.db.engine.begin() as conn:
            result = conn.execute(
                update(self.files)
                .where(self.files.c.status.in_(("queued", "parsing", "chunking", "embedding")))
                .values(
                    status="failed",
                    error="Bị gián đoạn khi server dừng — bấm Nhúng lại RAG",
                )
            )
        return result.rowcount

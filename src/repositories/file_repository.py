"""Truy vấn bảng `files`: trạng thái ingest từng file (phục vụ UI danh sách + %).

SQLAlchemy Core; bảng reflect từ DB (schema.py là nguồn DDL duy nhất).
`delete_file` có cascade xóa chunk trong cùng transaction.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, Table, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

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
        stmt = pg_insert(self.files).values(
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
                # Batch cũ của lần ingest trước không còn nghĩa lý — reset sạch.
                "batch_job_id": "",
                "batch_meta": "",
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

    def set_file_batch(
        self, file_id: str, batch_job_id: str, batch_meta: str, chunks_done: int = 0
    ) -> None:
        """Ghi batch job đã submit (status 'batching' do worker set riêng)."""
        with self.db.engine.begin() as conn:
            conn.execute(
                update(self.files)
                .where(self.files.c.file_id == file_id)
                .values(
                    status="batching",
                    batch_job_id=batch_job_id,
                    batch_meta=batch_meta,
                    chunks_done=chunks_done,
                )
            )

    def update_batch_progress(self, file_id: str, chunks_done: int) -> None:
        """Cập nhật tiến độ của file đang chờ batch (không đổi status)."""
        with self.db.engine.begin() as conn:
            conn.execute(
                update(self.files)
                .where(self.files.c.file_id == file_id)
                .values(chunks_done=chunks_done)
            )

    def list_batching_files(self) -> list[dict[str, Any]]:
        """Các file đang chờ batch job hoàn tất — worker poll mỗi vòng lặp."""
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                select(self.files).where(self.files.c.status == "batching")
            ).mappings().all()
        return [dict(row) for row in rows]

    def list_files(self) -> list[dict[str, Any]]:
        with self.db.engine.connect() as conn:
            rows = conn.execute(
                select(self.files).order_by(self.files.c.file_id.asc())
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
            res = conn.execute(delete(self.chunks).where(self.chunks.c.doc == doc))
            conn.execute(delete(self.files).where(self.files.c.file_id == file_id))
        meta["chunks_removed"] = res.rowcount
        return meta

    def fail_interrupted_ingests(self) -> int:
        """Đánh failed các job dở (queued/parsing/…) sau restart — không tự nhúng lại.

        File status 'batching' KHÔNG bị đánh failed: batch job nằm ở provider,
        chạy tiếp độc lập với server — worker sẽ resume poll từ batch_meta khi
        khởi động lại (job đã mất/hết hạn ở provider → failed rõ ràng lúc poll).
        """
        transient_statuses = ("queued", "parsing", "chunking", "embedding")
        with self.db.engine.begin() as conn:
            result = conn.execute(
                update(self.files)
                .where(self.files.c.status.in_(transient_statuses))
                .values(
                    status="failed",
                    error="Bị gián đoạn do server restart (không tự nhúng lại)",
                )
            )
        return result.rowcount

    def mark_all_stale(self, error: str) -> int:
        """Đánh dấu TOÀN BỘ file failed kèm thông báo (dùng khi đổi chiều vector —
        index cũ đã reset, mọi file cần bấm ↻ nạp lại; không tự reingest)."""
        with self.db.engine.begin() as conn:
            result = conn.execute(
                update(self.files).values(status="failed", error=error)
            )
        return result.rowcount

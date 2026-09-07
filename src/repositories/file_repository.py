"""Truy vấn bảng `files`: trạng thái ingest từng file (phục vụ UI danh sách + %).

DDL tương ứng nằm ở storage/schema.py. `delete_file` có cascade sang chunk
(vec/fts) trong cùng transaction — việc xóa doc gắn với vòng đời file nên giữ
trọn ở đây thay vì tách nửa vời sang ChunkRepository.
"""

from __future__ import annotations

from typing import Any

from storage.connection import Database


class FileRepository:
    """Truy vấn metadata file ingest trên một `Database`."""

    def __init__(self, db: Database):
        self.db = db

    def upsert_file(
        self,
        file_id: str,
        name: str,
        source: str = "upload",
        status: str = "queued",
        chunks_total: int = 0,
    ) -> None:
        with self.db.lock:
            self.db.conn.execute(
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
            self.db.conn.commit()

    def set_file_status(self, file_id: str, status: str, error: str | None = None) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE files SET status = ?, error = ? WHERE file_id = ?",
                (status, error, file_id),
            )
            self.db.conn.commit()

    def set_file_progress(self, file_id: str, chunks_done: int) -> None:
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE files SET chunks_done = ? WHERE file_id = ?",
                (chunks_done, file_id),
            )
            self.db.conn.commit()

    def list_files(self) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                "SELECT file_id, name, source, status, chunks_total, chunks_done, error"
                " FROM files ORDER BY rowid"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT * FROM files WHERE file_id = ?", (file_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_file(self, file_id: str) -> dict[str, Any] | None:
        """Xóa metadata file + mọi chunk của doc cùng tên. Trả về row đã xóa hoặc None."""
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT * FROM files WHERE file_id = ?", (file_id,)
            ).fetchone()
            if row is None:
                return None
            meta = dict(row)
            doc = meta["name"]
            rowids = [
                r["id"]
                for r in self.db.conn.execute("SELECT id FROM chunks WHERE doc = ?", (doc,))
            ]
            if rowids:
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
            self.db.conn.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
            self.db.conn.commit()
            meta["chunks_removed"] = len(rowids)
            return meta

    def fail_interrupted_ingests(self) -> int:
        """Đánh failed các job dở (queued/parsing/…) sau restart — không tự nhúng lại."""
        with self.db.lock:
            cur = self.db.conn.execute(
                """
                UPDATE files
                SET status = 'failed',
                    error = 'Bị gián đoạn khi server dừng — bấm Nhúng lại RAG'
                WHERE status IN ('queued', 'parsing', 'chunking', 'embedding')
                """
            )
            self.db.conn.commit()
            return cur.rowcount

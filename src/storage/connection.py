"""Sở hữu SQLAlchemy engine cho SQLite + sqlite-vec + FTS5.

Thread-safety: mỗi thao tác DB mở một connection riêng qua engine (pool
`NullPool` — không giữ connection chờ). SQLite tự serialize ghi giữa các
connection bằng file lock; đặt `timeout=30` để chờ thay vì lỗi "database is
locked" khi worker ingest và API ghi đồng thời.

Điểm đặc thù sqlite-vec: extension phải được load trên TỪNG connection, nên
đăng ký qua sự kiện `connect` của engine (không chỉ 1 lần như hồi dùng chung
một connection). FTS5 là extension SQLite nội tại, không cần load.

Schema (storage/schema.py) được chạy đúng 1 lần lúc khởi tạo Database
(IF NOT EXISTS nên chạy lại vô hại).
"""

from __future__ import annotations

from pathlib import Path

import sqlite_vec
from sqlalchemy import URL, create_engine, event
from sqlalchemy.pool import NullPool

from storage.schema import SCHEMA


def _load_sqlite_vec(dbapi_conn, _record) -> None:
    """Load extension sqlite-vec trên connection mới (bắt buộc với NullPool)."""
    dbapi_conn.enable_load_extension(True)
    sqlite_vec.load(dbapi_conn)
    dbapi_conn.enable_load_extension(False)


class Database:
    """SQLAlchemy engine SQLite; chạy schema lúc khởi tạo. Repository dùng `db.engine`."""

    def __init__(self, db_path: Path | str, embed_dim: int = 384):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        url = URL.create("sqlite", database=str(self.db_path))
        # check_same_thread=False: engine dùng từ worker thread lẫn threadpool FastAPI;
        # timeout=30s: chờ SQLite lock thay vì fail ngay khi 2 thread ghi đè nhau.
        self.engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
            poolclass=NullPool,
        )
        event.listen(self.engine, "connect", _load_sqlite_vec)
        with self.engine.connect() as conn:
            conn.connection.driver_connection.executescript(SCHEMA.format(dim=embed_dim))
            conn.commit()

    def close(self) -> None:
        self.engine.dispose()

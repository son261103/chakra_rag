"""Sở hữu connection SQLite duy nhất + serial hóa truy cập.

Về thread-safety: ingest worker chạy ở thread riêng, FastAPI endpoint chạy ở
threadpool, tất cả chia sẻ một `Database`. Một connection sqlite3 KHÔNG an toàn
khi dùng đồng thời từ nhiều thread (kể cả với `check_same_thread=False` — cờ đó
chỉ tắt kiểm tra, không thêm bảo vệ). Vì vậy mọi thao tác DB phải nằm trong
`with db.lock:` (RLock để serialize truy cập trên connection duy nhất).

Định nghĩa bảng nằm ở `schema.py` — connection chỉ lo mở DB, load extension
sqlite-vec và chạy schema lúc khởi tạo (IF NOT EXISTS, chạy lại vô hại).
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import sqlite_vec

from storage.schema import SCHEMA


class Database:
    """Một connection sqlite3 + sqlite-vec + FTS5, schema tạo sẵn lúc khởi tạo.

    Repository nhận `db` này và truy vấn qua `db.conn` (connection duy nhất)
    bên trong `with db.lock:` — đừng tạo connection thứ hai ở nơi khác.
    """

    def __init__(self, db_path: Path | str, embed_dim: int = 384):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False để connection dùng được từ worker thread lẫn
        # threadpool của FastAPI; an toàn thực sự do RLock bên dưới.
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
        self.conn.executescript(SCHEMA.format(dim=embed_dim))
        self.conn.commit()

    def close(self) -> None:
        with self.lock:
            self.conn.close()

"""Tầng lưu trữ: schema (DDL) + connection.

- `schema.py`    : toàn bộ định nghĩa bảng/chỉ mục (không logic truy vấn).
- `connection.py`: `Database` — sở hữu connection sqlite3 + sqlite-vec + FTS5,
                   RLock serialize truy cập; chạy schema khi khởi tạo.

Truy vấn SQL theo domain nằm ở package `repositories/` (ngoài storage/).
"""

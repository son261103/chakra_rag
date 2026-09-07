"""Tầng lưu trữ: schema (DDL) + connection.

- `schema.py`    : toàn bộ định nghĩa bảng/chỉ mục (không logic truy vấn).
- `connection.py`: `Database` — SQLAlchemy engine (SQLite + sqlite-vec + FTS5,
                   vec load trên từng connection), chạy schema khi khởi tạo.

Truy vấn SQL theo domain nằm ở package `repositories/` (ngoài storage/),
viết bằng SQLAlchemy Core — bảng reflect từ DB nên schema.py là nguồn DDL
duy nhất, không duplicate định nghĩa.
"""

"""Tầng lưu trữ: schema (DDL) + connection.

- `schema.py`    : toàn bộ định nghĩa bảng/chỉ mục PostgreSQL (DDL thuần, không logic truy vấn),
                   tổng hợp từ package `schemas/`.
- `schemas/`     : package chứa định nghĩa DDL từng bảng riêng biệt
                   (`chunks.py`, `files.py`, `conversations.py`, `messages.py`, `integrations.py`).
- `connection.py`: `Database` — SQLAlchemy engine (PostgreSQL + pgvector), chạy schema khi khởi tạo.

Truy vấn SQL theo domain nằm ở package `repositories/` (ngoài storage/),
viết bằng SQLAlchemy Core — bảng reflect từ DB nên schema là nguồn DDL
duy nhất, không duplicate định nghĩa.
"""

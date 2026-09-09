"""Sở hữu SQLAlchemy engine cho PostgreSQL + pgvector.

Thread-safety: SQLAlchemy connection pool (QueuePool) quản lý kết nối an toàn
giữa các worker thread và API threadpool. Bật `pool_pre_ping=True` để tự động
phục hồi khi kết nối bị ngắt.

Hỗ trợ schema-level isolation cho test: khi truyền đường dẫn tạm thời hoặc
`schema_name`, Database tự sinh một schema riêng biệt trong PostgreSQL, gán
`search_path` và dọn dẹp (DROP CASCADE) khi đóng kết nối.

Schema (storage/schema.py) được chạy đúng 1 lần lúc khởi tạo Database
(IF NOT EXISTS nên chạy lại vô hại).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from sqlalchemy import create_engine, text

from config import build_db_url, get_config
from storage.schema import SCHEMA, SCHEMA_NO_CHUNKS


def _normalize_db_url(url: str) -> str:
    """Đảm bảo URL PostgreSQL dùng driver psycopg (v3)."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _get_configured_url(is_test: bool = False) -> str:
    """Lấy URL kết nối từ cấu hình môi trường mà không hardcode thông tin nhạy cảm."""
    cfg = get_config()
    if is_test:
        test_url = os.environ.get("TEST_DB_URL")
        if test_url:
            return _normalize_db_url(test_url)
        test_db = os.environ.get("TEST_DB_NAME", f"{cfg.db_name}_test")
        return build_db_url(
            user=cfg.db_user,
            password=cfg.db_password,
            host=cfg.db_host,
            port=cfg.db_port,
            database=test_db,
        )
    return cfg.db_url

class Database:
    """SQLAlchemy engine PostgreSQL; chạy schema lúc khởi tạo. Repository dùng `db.engine`."""

    def __init__(
        self,
        db_url: str | Path | None = None,
        embed_dim: int | None = None,
        schema_name: str | None = None,
    ):
        raw_url = str(db_url) if db_url is not None else ""
        self.is_test_schema = False


        # Phát hiện chế độ test: nếu truyền Path hoặc file .db từ test fixture
        if (
            isinstance(db_url, Path)
            or raw_url.endswith(".db")
            or ("test" in raw_url.lower() and not raw_url.startswith("postgres"))
            or schema_name is not None
        ):
            self.is_test_schema = True
            self.schema_name = schema_name or f"test_{uuid.uuid4().hex[:12]}"
            resolved_url = _get_configured_url(is_test=True)
        elif raw_url:
            resolved_url = raw_url
            self.schema_name = schema_name
        else:
            resolved_url = _get_configured_url(is_test=False)
            self.schema_name = schema_name

        self.url = _normalize_db_url(resolved_url)
        self._admin_engine = create_engine(self.url, pool_pre_ping=True)

        if self.schema_name:
            with self._admin_engine.begin() as conn:
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self.schema_name};"))
            connect_args = {"options": f"-c search_path={self.schema_name},public"}
        else:
            connect_args = {}

        self.engine = create_engine(
            self.url,
            connect_args=connect_args,
            pool_pre_ping=True,
        )

        with self.engine.begin() as conn:
            if embed_dim is None:
                # Auto-resolve số chiều cho DDL `chunks`: chạy phần schema không
                # chứa `{dim}` trước (bảng `embedding_integrations` phải tồn tại),
                # đọc dimension của integration đang active. DB mới chưa có
                # integration nào → cfg.embed_dim (env EMBED_DIM = chiều mặc định
                # của DB, không phải fallback credential; thêm integration đầu
                # tiên sẽ đồng bộ chiều theo model khai báo trong UI).
                conn.execute(text(SCHEMA_NO_CHUNKS))
                dim_row = conn.execute(
                    text(
                        "SELECT dimension FROM embedding_integrations "
                        "WHERE is_active = 1 LIMIT 1"
                    )
                ).scalar()
                embed_dim = int(dim_row) if dim_row else get_config().embed_dim
            conn.execute(text(SCHEMA.format(dim=embed_dim)))

    def close(self) -> None:
        if self.is_test_schema and self.schema_name:
            try:
                with self._admin_engine.begin() as conn:
                    conn.execute(text(f"DROP SCHEMA IF EXISTS {self.schema_name} CASCADE;"))
            except Exception:
                pass
        self.engine.dispose()
        self._admin_engine.dispose()

"""Cấu hình tập trung: đọc từ biến môi trường / file .env, có giá trị mặc định.

Mọi module khác chỉ nhận Config qua tham số hoặc qua `get_config()`,
không tự đọc env — để dễ test và dễ đổi nguồn cấu hình.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    """Nạp .env ở thư mục gốc project (không cần thư viện ngoài)."""
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    return int(os.environ.get(key, str(default)))


def _env_float(key: str, default: float) -> float:
    return float(os.environ.get(key, str(default)))


def build_db_url(
    user: str = "postgres",
    password: str = "",
    host: str = "localhost",
    port: int = 5432,
    database: str = "chakra_rag",
    driver: str = "postgresql+psycopg",
) -> str:
    """Xây dựng chuỗi kết nối PostgreSQL an toàn (URL-encoded credentials)."""
    auth = f"{quote_plus(user)}:{quote_plus(password)}" if password else quote_plus(user)
    return f"{driver}://{auth}@{host}:{port}/{database}"
@dataclass(frozen=True)
class Config:
    # LLM: KHÔNG có credential/base_url/model trong env — mọi thứ cấu hình
    # qua Settings UI (bảng `integrations`). Chỉ giữ tham số vận hành
    # (retry/timeout) vì chúng là hành vi SDK, không phải định danh provider.
    # Retry gateway/connect flaky (502/5xx/timeout) — openai SDK backoff.
    llm_max_retries: int = 5
    llm_timeout: float = 90.0

    # Mã hóa API key (Envelope encryption KEK)
    encryption_key: str = "chakra-default-secret-encryption-key-2026"

    # Embedding: KHÔNG có credential/base_url/model trong env — mọi thứ cấu hình
    # qua Settings UI (bảng `embedding_integrations`). Duy nhất `embed_dim` là
    # CHIỀU MẶC ĐỊNH cho DB (env EMBED_DIM): DB mới chưa có integration nào dùng
    # nó để dựng bảng `chunks` rỗng; thêm integration đầu tiên sẽ đồng bộ chiều
    # theo model khai báo trong UI. Muốn đổi chiều mặc định → sửa EMBED_DIM.
    embed_dim: int = 1024

    # Database (PostgreSQL + pgvector)
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = ""
    db_name: str = "chakra_rag"
    db_url: str = ""
    db_path: Path | None = None
    uploads_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "uploads")
    logs_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")
    # Tham số pipeline
    chunk_size: int = 300
    chunk_overlap: int = 50
    top_k: int = 5
    rrf_k: int = 60
    min_score: float = 0.25
    max_agent_turns: int = 12
    # Số lượt user+assistant gần nhất đưa vào multi-turn (mỗi lượt = 1 user + 1 assistant).
    chat_history_turns: int = 8

    # API/CORS
    api_allowed_origins: list[str] = field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    # Ingestion
    supported_suffixes: set[str] = field(default_factory=lambda: {".md", ".txt", ".pdf"})
    embed_batch_size: int = 16

    # Verification
    support_threshold: float = 0.30

    def ensure_dirs(self) -> None:
        if self.db_path is not None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

@lru_cache
def get_config() -> Config:
    _load_dotenv()
    db_user = _env("DB_USER", _env("POSTGRES_USER", "postgres"))
    db_password = _env("DB_PASSWORD", _env("POSTGRES_PASSWORD", ""))
    db_name = _env("DB_NAME", _env("POSTGRES_DB", "chakra_rag"))
    db_host = _env("DB_HOST", _env("POSTGRES_HOST", "localhost"))
    db_port = _env_int("DB_PORT", _env_int("POSTGRES_PORT", 5432))

    raw_db_url = _env("DB_URL", _env("DATABASE_URL", ""))
    if raw_db_url:
        db_url = raw_db_url
        if db_url.startswith("postgresql://"):
            db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    else:
        db_url = build_db_url(
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port,
            database=db_name,
        )
    cfg = Config(
        llm_max_retries=_env_int("LLM_MAX_RETRIES", 5),
        llm_timeout=_env_float("LLM_TIMEOUT", 90.0),
        embed_dim=_env_int("EMBED_DIM", 1024),
        db_host=db_host,
        db_port=db_port,
        db_user=db_user,
        db_password=db_password,
        db_name=db_name,
        db_url=db_url,
        db_path=Path(_env("DB_PATH", "")) if _env("DB_PATH", "") else None,
        uploads_dir=Path(_env("UPLOADS_DIR", str(PROJECT_ROOT / "data" / "uploads"))),
        logs_dir=Path(_env("LOGS_DIR", str(PROJECT_ROOT / "logs"))),
        chunk_size=_env_int("CHUNK_SIZE", 300),
        chunk_overlap=_env_int("CHUNK_OVERLAP", 50),
        top_k=_env_int("TOP_K", 5),
        rrf_k=_env_int("RRF_K", 60),
        min_score=_env_float("MIN_SCORE", 0.25),
        max_agent_turns=_env_int("MAX_AGENT_TURNS", 12),
        chat_history_turns=_env_int("CHAT_HISTORY_TURNS", 8),
        api_allowed_origins=[
            s.strip()
            for s in _env("API_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if s.strip()
        ],
        supported_suffixes={
            s.strip().lower()
            for s in _env("SUPPORTED_SUFFIXES", ".md,.txt,.pdf").split(",")
            if s.strip()
        },
        embed_batch_size=_env_int("EMBED_BATCH_SIZE", 16),
        support_threshold=_env_float("SUPPORT_THRESHOLD", 0.30),
        encryption_key=_env("ENCRYPTION_KEY", "chakra-default-secret-encryption-key-2026"),
    )
    cfg.ensure_dirs()
    return cfg

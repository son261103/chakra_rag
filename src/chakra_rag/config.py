"""Cấu hình tập trung: đọc từ biến môi trường / file .env, có giá trị mặc định.

Mọi module khác chỉ nhận Config qua tham số hoặc qua `get_config()`,
không tự đọc env — để dễ test và dễ đổi nguồn cấu hình.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


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


@dataclass(frozen=True)
class Config:
    # LLM (OpenAI-compatible)
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    # Retry gateway/connect flaky (502/5xx/timeout) — openai SDK backoff.
    llm_max_retries: int = 5
    llm_timeout: float = 90.0

    # Embedding (local)
    embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # Đường dẫn
    db_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "chakra.db")
    docs_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "docs")
    uploads_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "uploads")
    logs_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "logs")

    # Tham số pipeline
    chunk_size: int = 300
    chunk_overlap: int = 50
    top_k: int = 5
    rrf_k: int = 60
    min_score: float = 0.25
    max_agent_turns: int = 4
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
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_config() -> Config:
    _load_dotenv()
    cfg = Config(
        llm_base_url=_env("LLM_BASE_URL", "https://api.openai.com/v1"),
        llm_api_key=_env("LLM_API_KEY", ""),
        llm_model=_env("LLM_MODEL", "gpt-4o-mini"),
        llm_max_retries=_env_int("LLM_MAX_RETRIES", 5),
        llm_timeout=_env_float("LLM_TIMEOUT", 90.0),
        embed_model=_env(
            "EMBED_MODEL",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        ),
        db_path=Path(_env("DB_PATH", str(PROJECT_ROOT / "data" / "chakra.db"))),
        docs_dir=Path(_env("DOCS_DIR", str(PROJECT_ROOT / "data" / "docs"))),
        uploads_dir=Path(_env("UPLOADS_DIR", str(PROJECT_ROOT / "data" / "uploads"))),
        logs_dir=Path(_env("LOGS_DIR", str(PROJECT_ROOT / "logs"))),
        chunk_size=_env_int("CHUNK_SIZE", 300),
        chunk_overlap=_env_int("CHUNK_OVERLAP", 50),
        top_k=_env_int("TOP_K", 5),
        rrf_k=_env_int("RRF_K", 60),
        min_score=_env_float("MIN_SCORE", 0.25),
        max_agent_turns=_env_int("MAX_AGENT_TURNS", 4),
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
    )
    cfg.ensure_dirs()
    return cfg

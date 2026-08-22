"""Cấu hình logging chuẩn cho backend — in ra stdout (uvicorn/terminal).

Gọi `setup_logging()` một lần khi app start. Các module khác chỉ cần:
    logger = logging.getLogger(__name__)
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def setup_logging(level: str | None = None) -> None:
    """Idempotent: cấu hình root logger + dịu bớt noise thư viện ngoài."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    level_name = (level or os.environ.get("LOG_LEVEL", "INFO")).upper()
    log_level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Ồn ào / ít giá trị khi debug RAG
    for noisy in (
        "httpx",
        "httpcore",
        "openai",
        "urllib3",
        "multipart",
        "sentence_transformers",
        "transformers",
        "torch",
        "filelock",
        "asyncio",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # uvicorn access vẫn giữ; chỉ hạ logger nội bộ nếu cần
    logging.getLogger("chakra_rag").setLevel(log_level)
    logging.getLogger("chakra_rag").info("Logging sẵn sàng (level=%s)", level_name)

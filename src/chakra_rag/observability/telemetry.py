"""Logs tự thu (thay LangSmith): mỗi lần ask ghi 1 dòng JSONL.

File logs/asks.jsonl đồng thời là dataset thật để phân tích chất lượng
sau này — offline, tự sở hữu, không gửi dữ liệu ra ngoài.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Telemetry:
    """Append-only JSONL logger cho mỗi lần hỏi."""

    def __init__(self, logs_dir: Path):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.logs_dir / "asks.jsonl"

    def log_ask(self, record: dict[str, Any]) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            **record,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(json.loads(line))
        return entries


def timed() -> float:
    """Helper đo latency: t0 = timed(); ...; latency_ms = elapsed_ms(t0)."""
    return time.perf_counter()


def elapsed_ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)

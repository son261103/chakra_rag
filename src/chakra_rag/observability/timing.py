"""Helper đo latency dùng chung."""
from __future__ import annotations

import time


def timed() -> float:
    """t0 = timed(); ...; latency_ms = elapsed_ms(t0)."""
    return time.perf_counter()


def elapsed_ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)

"""Event bus ingest: worker báo hiệu mỗi khi trạng thái đổi, SSE endpoint chờ tín hiệu.

Worker chạy trong thread riêng nên bus dùng threading.Condition (an toàn
thread): `notify()` gọi từ worker thread, `wait_for()` gọi từ thread pool của
asyncio (qua asyncio.to_thread ở route SSE). Version tăng đơn điệu để client
chỉ nhận snapshot khi thực sự có thay đổi mới.
"""

from __future__ import annotations

import threading


class IngestEventBus:
    """Bộ đếm version + Condition: chờ tới khi version vượt mốc đã biết."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._version = 0

    @property
    def version(self) -> int:
        with self._condition:
            return self._version

    def notify(self) -> None:
        """Worker gọi sau mỗi lần ghi trạng thái ingest (queued/progress/ready/...)."""
        with self._condition:
            self._version += 1
            self._condition.notify_all()

    def wait_for(self, since: int, timeout: float) -> int | None:
        """Chặn tới khi version > since. Trả version mới, None nếu hết timeout."""
        with self._condition:
            if self._version <= since:
                self._condition.wait(timeout)
            return self._version if self._version > since else None

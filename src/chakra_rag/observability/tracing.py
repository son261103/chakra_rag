"""LangSmith observability — thay hệ JSONL tự thu (telemetry.py cũ).

Thiết kế theo docs.langchain.com/langsmith (langsmith>=0.11.1):
- Tracing bật qua env LANGSMITH_* ; langchain-core tự gắn tracer vào graph runs,
  KHÔNG cần wiring runtime ở đây.
- Module này chỉ cung cấp: client factory (lazy, guard khi chưa cấu hình),
  metadata per-invocation tại ranh giới ask(), và submit feedback scores
  (invalid_citations/unsupported_claims/low_confidence) lên root run.
- Khi LANGSMITH không cấu hình: mọi hàm là no-op an toàn.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from langsmith import get_current_run_tree

logger = logging.getLogger(__name__)

_client_cache: Any = None  # langsmith.Client | None — lazy singleton


def _tracing_requested() -> bool:
    return os.environ.get("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes")


def ls_client() -> Any | None:
    """Trả về langsmith.Client hoặc None nếu chưa cấu hình (auth từ env)."""
    global _client_cache
    if _client_cache is not None:
        return _client_cache
    if not (_tracing_requested() and os.environ.get("LANGSMITH_API_KEY")):
        return None
    try:
        import langsmith as ls

        _client_cache = ls.Client()  # đọc LANGSMITH_API_KEY/ENDPOINT từ env
        return _client_cache
    except Exception:  # noqa: BLE001 — không bao giờ làm hỏng flow chính vì tracing
        logger.exception("khởi tạo langsmith.Client thất bại — tiếp tục không trace")
        return None


def trace_metadata(
    conversation_id: str | None, mode: str, *, streamed: bool
) -> dict[str, Any]:
    """Config dict cho agent.invoke/stream: metadata + tags của cả trace."""
    return {
        "metadata": {
            "conversation_id": conversation_id,
            "mode": mode,
            "streamed": streamed,
        },
        "tags": ["stream" if streamed else "sync"],
    }


def submit_feedback(key: str, score: float | int | bool, comment: str = "") -> None:
    """Ghi feedback score lên root run hiện tại (nếu đang trong một trace).

    Mapping chất lượng: invalid_citations→số lượng cite sai,
    unsupported_claims→số claim thiếu đỡ, low_confidence→0/1.
    Không trace / chưa cấu hình → no-op im lặng.
    """
    client = ls_client()
    if client is None:
        return
    try:
        rt = get_current_run_tree()
        if rt is None:
            return
        client.create_feedback(
            key=key,
            score=score,
            comment=comment,
            run_id=rt.id,
            trace_id=rt.trace_id,
            session_id=client.create_project(project_name=rt.session_name, upsert=True).id,
        )
    except Exception:  # noqa: BLE001 — feedback thất bại không được phá trả lời
        logger.warning("submit_feedback failed key=%s", key, exc_info=True)

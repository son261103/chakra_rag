"""Tiện ích dùng chung cho repository: sinh id ngẫu nhiên + timestamp ISO.

Tách riêng để conversation/integration repository không phải duplicate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def utcnow_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex

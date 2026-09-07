"""Truy vấn `conversations` + `messages`: lịch sử hội thoại (payload JSON cho UI replay).

SQLAlchemy Core; bảng reflect từ DB (schema.py là nguồn DDL duy nhất).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import MetaData, Table, delete, func, insert, select, update
from sqlalchemy import text as sql_text

from repositories.common import new_id, utcnow_iso
from storage.connection import Database


class ConversationRepository:
    """Truy vấn hội thoại và tin nhắn trên một `Database`."""

    def __init__(self, db: Database):
        self.db = db
        meta = MetaData()
        self.conversations = Table("conversations", meta, autoload_with=db.engine)
        self.messages = Table("messages", meta, autoload_with=db.engine)

    # ---------- conversations ----------

    def create_conversation(self, title: str = "Hội thoại mới") -> dict[str, Any]:
        cid = new_id()
        now = utcnow_iso()
        with self.db.engine.begin() as conn:
            conn.execute(
                insert(self.conversations).values(
                    id=cid, title=title, created_at=now, updated_at=now
                )
            )
        return {"id": cid, "title": title, "created_at": now, "updated_at": now}

    def list_conversations(self) -> list[dict[str, Any]]:
        message_count = (
            select(func.count())
            .select_from(self.messages)
            .where(self.messages.c.conversation_id == self.conversations.c.id)
            .scalar_subquery()
            .label("message_count")
        )
        stmt = (
            select(
                self.conversations.c.id,
                self.conversations.c.title,
                self.conversations.c.created_at,
                self.conversations.c.updated_at,
                message_count,
            )
            .order_by(self.conversations.c.updated_at.desc())
        )
        with self.db.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        stmt = (
            select(
                self.conversations.c.id,
                self.conversations.c.title,
                self.conversations.c.created_at,
                self.conversations.c.updated_at,
            )
            .where(self.conversations.c.id == conversation_id)
        )
        with self.db.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
        return dict(row) if row else None

    def rename_conversation(self, conversation_id: str, title: str) -> None:
        with self.db.engine.begin() as conn:
            conn.execute(
                update(self.conversations)
                .where(self.conversations.c.id == conversation_id)
                .values(title=title, updated_at=utcnow_iso())
            )

    def delete_conversation(self, conversation_id: str) -> bool:
        with self.db.engine.begin() as conn:
            # SQLite FK cascade cần PRAGMA; xóa messages thủ công cho chắc.
            conn.execute(
                delete(self.messages).where(self.messages.c.conversation_id == conversation_id)
            )
            result = conn.execute(
                delete(self.conversations).where(self.conversations.c.id == conversation_id)
            )
        return result.rowcount > 0

    # ---------- messages ----------

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        mid = new_id()
        now = utcnow_iso()
        payload_json = json.dumps(payload, ensure_ascii=False) if payload is not None else None
        with self.db.engine.begin() as conn:
            conn.execute(
                insert(self.messages).values(
                    id=mid,
                    conversation_id=conversation_id,
                    role=role,
                    content=content,
                    payload_json=payload_json,
                    created_at=now,
                )
            )
            conn.execute(
                update(self.conversations)
                .where(self.conversations.c.id == conversation_id)
                .values(updated_at=now)
            )
        return {
            "id": mid,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "payload": payload,
            "created_at": now,
        }

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(
                self.messages.c.id,
                self.messages.c.conversation_id,
                self.messages.c.role,
                self.messages.c.content,
                self.messages.c.payload_json,
                self.messages.c.created_at,
            )
            .where(self.messages.c.conversation_id == conversation_id)
            .order_by(self.messages.c.created_at, sql_text("rowid"))
        )
        with self.db.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = item.pop("payload_json", None)
            if raw:
                try:
                    item["payload"] = json.loads(raw)
                except json.JSONDecodeError:
                    item["payload"] = None
            else:
                item["payload"] = None
            out.append(item)
        return out

    def list_history_for_llm(
        self, conversation_id: str, max_turns: int = 8
    ) -> list[dict[str, str]]:
        """Lấy tối đa max_turns cặp user/assistant gần nhất (chỉ role + content text)."""
        messages = self.list_messages(conversation_id)
        # Giữ đúng thứ tự thời gian; cắt theo số message (2 * turns).
        limit = max(0, max_turns) * 2
        trimmed = messages[-limit:] if limit else []
        return [
            {"role": m["role"], "content": m["content"]}
            for m in trimmed
            if m["role"] in ("user", "assistant")
        ]

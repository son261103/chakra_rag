"""Truy vấn `conversations` + `messages`: lịch sử hội thoại (payload JSON cho UI replay).

DDL tương ứng nằm ở storage/schema.py.
"""

from __future__ import annotations

import json
from typing import Any

from repositories.common import new_id, utcnow_iso
from storage.connection import Database


class ConversationRepository:
    """Truy vấn hội thoại và tin nhắn trên một `Database`."""

    def __init__(self, db: Database):
        self.db = db

    # ---------- conversations ----------

    def create_conversation(self, title: str = "Hội thoại mới") -> dict[str, Any]:
        cid = new_id()
        now = utcnow_iso()
        with self.db.lock:
            self.db.conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (cid, title, now, now),
            )
            self.db.conn.commit()
        return {"id": cid, "title": title, "created_at": now, "updated_at": now}

    def list_conversations(self) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                """
                SELECT c.id, c.title, c.created_at, c.updated_at,
                       (SELECT COUNT(*) FROM messages m
                        WHERE m.conversation_id = c.id) AS message_count
                FROM conversations c
                ORDER BY c.updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def rename_conversation(self, conversation_id: str, title: str) -> None:
        now = utcnow_iso()
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, conversation_id),
            )
            self.db.conn.commit()

    def touch_conversation(self, conversation_id: str) -> None:
        now = utcnow_iso()
        with self.db.lock:
            self.db.conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            self.db.conn.commit()

    def delete_conversation(self, conversation_id: str) -> bool:
        with self.db.lock:
            # SQLite FK cascade cần PRAGMA; xóa messages thủ công cho chắc.
            self.db.conn.execute(
                "DELETE FROM messages WHERE conversation_id = ?", (conversation_id,)
            )
            cur = self.db.conn.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
            self.db.conn.commit()
            return cur.rowcount > 0

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
        with self.db.lock:
            self.db.conn.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (mid, conversation_id, role, content, payload_json, now),
            )
            self.db.conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
            self.db.conn.commit()
        return {
            "id": mid,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "payload": payload,
            "created_at": now,
        }

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                """
                SELECT id, conversation_id, role, content, payload_json, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (conversation_id,),
            ).fetchall()
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

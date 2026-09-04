"""Service quản lý lịch sử hội thoại và tin nhắn của người dùng."""

from __future__ import annotations

import logging
from typing import Any

from chakra_rag.config import Config, get_config
from chakra_rag.storage.store import Store

logger = logging.getLogger(__name__)


class ConversationService:
    """Nghiệp vụ lưu trữ, truy xuất và quản lý ngữ cảnh hội thoại."""

    def __init__(self, store: Store, cfg: Config | None = None):
        self.store = store
        self.cfg = cfg or get_config()

    def list_conversations(self) -> list[dict[str, Any]]:
        """Lấy danh sách các cuộc hội thoại, sắp xếp theo thời gian cập nhật gần nhất."""
        return self.store.list_conversations()

    def create_conversation(self, title: str | None = None) -> dict[str, Any]:
        """Tạo cuộc hội thoại mới."""
        return self.store.create_conversation(title=title or "Hội thoại mới")

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """Lấy chi tiết cuộc hội thoại kèm danh sách tin nhắn."""
        conv = self.store.get_conversation(conversation_id)
        if conv is None:
            return None
        messages = self.store.list_messages(conversation_id)
        return {**conv, "messages": messages}

    def delete_conversation(self, conversation_id: str) -> bool:
        """Xóa cuộc hội thoại và toàn bộ tin nhắn liên quan (CASCADE)."""
        return self.store.delete_conversation(conversation_id)

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        """Đổi tên tiêu đề cuộc hội thoại."""
        return self.store.rename_conversation(conversation_id, title)

    def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        """Lấy toàn bộ tin nhắn của một cuộc hội thoại."""
        return self.store.list_messages(conversation_id)

    def list_history_for_llm(
        self, conversation_id: str | None, max_turns: int | None = None
    ) -> list[dict[str, str]]:
        """Lấy ngữ cảnh lịch sử chat (tối đa max_turns lượt) gửi cho LLM."""
        if not conversation_id:
            return []
        turns = max_turns if max_turns is not None else self.cfg.chat_history_turns
        return self.store.list_history_for_llm(conversation_id, max_turns=turns)

    def persist_turn(
        self,
        conversation_id: str | None,
        question: str,
        payload: dict[str, Any],
    ) -> str | None:
        """Lưu lượt hỏi đáp (user + assistant); tự động đặt tiêu đề từ câu đầu."""
        if not conversation_id:
            return None
        conv = self.store.get_conversation(conversation_id)
        if conv is None:
            return None
        prior = self.store.list_messages(conversation_id)
        self.store.add_message(conversation_id, "user", question)
        self.store.add_message(
            conversation_id,
            "assistant",
            payload.get("answer") or "",
            payload=payload,
        )
        # Tự động đặt tên theo câu hỏi đầu tiên nếu hội thoại còn mang tên mặc định
        if not prior and (not conv.get("title") or conv["title"] == "Hội thoại mới"):
            title = question.strip().replace("\n", " ")
            if len(title) > 60:
                title = title[:57].rstrip() + "…"
            self.store.rename_conversation(conversation_id, title or "Hội thoại mới")
        return conversation_id

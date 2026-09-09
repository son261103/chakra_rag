"""Endpoints quản lý lịch sử hội thoại."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import Services

router = APIRouter(tags=["conversations"])


class CreateConversationRequest(BaseModel):
    title: str = Field(default="Hội thoại mới", min_length=1, max_length=200)


@router.get("/conversations")
def list_conversations(service: Services) -> dict[str, Any]:
    return {"conversations": service.conversations.list_conversations()}


@router.post("/conversations")
def create_conversation(
    service: Services,
    req: CreateConversationRequest | None = None,
) -> dict[str, Any]:
    title = (req.title if req else None) or "Hội thoại mới"
    return service.conversations.create_conversation(title=title)


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, service: Services) -> dict[str, Any]:
    conv = service.conversations.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(404, "Không tìm thấy hội thoại")
    return conv


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, service: Services) -> dict[str, Any]:
    if not service.conversations.delete_conversation(conversation_id):
        raise HTTPException(404, "Không tìm thấy hội thoại")
    return {"ok": True}

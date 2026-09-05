"""Endpoints xử lý hỏi đáp RAG (hỏi đồng bộ, SSE stream, xem chunk)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from service.container import ServiceContainer

router = APIRouter(tags=["chat"])


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)
    conversation_id: str | None = None


class ChunkRef(BaseModel):
    chunk_id: str
    doc: str | None = None
    section: str | None = None
    score: float | None = None
    text: str | None = None


class AskResponseModel(BaseModel):
    question: str
    answer: str
    citations: list[ChunkRef]
    invalid_citations: list[str]
    unsupported_claims: list[str]
    search_trace: list[dict[str, Any]]
    reasoning: str
    low_confidence: bool
    latency_ms: int
    conversation_id: str | None


@router.post("/ask", response_model=AskResponseModel)
def ask(req: AskRequest, request: Request) -> AskResponseModel:
    service: ServiceContainer = request.app.state.service
    progress = service.files.get_progress()
    if progress["status"] not in ("ready", "partial"):
        raise HTTPException(503, "Index chưa sẵn sàng — chờ ingest hoàn tất")
    if req.conversation_id and service.conversations.get_conversation(req.conversation_id) is None:
        raise HTTPException(404, "Không tìm thấy hội thoại")
    return service.chat.ask(
        req.question,
        top_k=req.top_k,
        conversation_id=req.conversation_id,
    )


@router.post("/ask/stream")
def ask_stream(req: AskRequest, request: Request):
    """SSE: mỗi event là 1 dòng `data: {json}`.

    Events: thinking (delta), tool_call (kết quả 1 lượt search), answer (delta),
    done (payload chuẩn đã verify), error.
    """
    service: ServiceContainer = request.app.state.service
    progress = service.files.get_progress()
    if progress["status"] not in ("ready", "partial"):
        raise HTTPException(503, "Index chưa sẵn sàng — chờ ingest hoàn tất")
    if req.conversation_id and service.conversations.get_conversation(req.conversation_id) is None:
        raise HTTPException(404, "Không tìm thấy hội thoại")

    def event_stream():
        for event in service.chat.ask_stream(
            req.question,
            top_k=req.top_k,
            conversation_id=req.conversation_id,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: str, request: Request) -> dict[str, Any]:
    service: ServiceContainer = request.app.state.service
    chunk = service.chat.get_chunk(chunk_id)
    if chunk is None:
        raise HTTPException(404, "Không tìm thấy chunk")
    return chunk

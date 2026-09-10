"""Endpoints xử lý hỏi đáp RAG (hỏi đồng bộ, SSE stream, xem chunk)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent.agent import LLMConfigError
from api.deps import Services

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
def ask(req: AskRequest, service: Services) -> AskResponseModel:
    if req.conversation_id and service.conversations.get_conversation(req.conversation_id) is None:
        raise HTTPException(404, "Không tìm thấy hội thoại")
    try:
        return service.chat.ask(
            req.question,
            top_k=req.top_k,
            conversation_id=req.conversation_id,
        )
    except LLMConfigError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/ask/stream")
def ask_stream(req: AskRequest, service: Services):
    """SSE: mỗi event là 1 dòng `data: {json}`.

    Events: thinking (delta), tool_call (kết quả 1 lượt search), answer (delta),
    done (payload chuẩn đã verify), error.
    """
    if req.conversation_id and service.conversations.get_conversation(req.conversation_id) is None:
        raise HTTPException(404, "Không tìm thấy hội thoại")
    # Guard TRƯỚC khi mở stream: chưa cấu hình LLM → 503 tường minh (fetch bên
    # UI bắt !res.ok và hiển thị thông báo), không nhét lỗi vào luồng SSE.
    try:
        service.agent.resolve_active_llm_config()
    except LLMConfigError as exc:
        raise HTTPException(503, str(exc)) from exc

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
def get_chunk(chunk_id: str, service: Services) -> dict[str, Any]:
    chunk = service.chat.get_chunk(chunk_id)
    if chunk is None:
        raise HTTPException(404, "Không tìm thấy chunk")
    return chunk

"""Endpoint kiểm tra sức khỏe hệ thống."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    chunks: int


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    service = request.app.state.service
    return {"status": "ok", "chunks": service.store.count_chunks()}

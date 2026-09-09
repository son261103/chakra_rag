"""Endpoint kiểm tra sức khỏe hệ thống."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from api.deps import Services

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    chunks: int


@router.get("/health", response_model=HealthResponse)
def health(service: Services) -> HealthResponse:
    return {"status": "ok", "chunks": service.chunk_repo.count_chunks()}

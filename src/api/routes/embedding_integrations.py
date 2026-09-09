"""Endpoints quản lý tích hợp embedding (API OpenAI-compatible /embeddings).

Mirror `integrations.py` (LLM), thêm:
- `dimension` (số chiều vector) trong payload create/update/response.
- Flow đổi chiều: nếu chiều mới khác chiều index hiện tại và index còn chunk →
  409 `{error: "dimension_mismatch", current_dimension, new_dimension}`;
  client xác nhận với user rồi gửi lại kèm `force=true` → server reset index.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import Services
from service.embedding_integration_service import EmbeddingDimensionConflict

logger = logging.getLogger(__name__)

router = APIRouter(tags=["embedding-integrations"])


def _conflict_http(exc: EmbeddingDimensionConflict) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "error": "dimension_mismatch",
            "current_dimension": exc.current_dimension,
            "new_dimension": exc.new_dimension,
            "message": str(exc),
        },
    )


class EmbeddingIntegrationResponseModel(BaseModel):
    id: str
    name: str
    provider: str = "openai"
    base_url: str
    model: str
    dimension: int
    masked_api_key: str
    has_api_key: bool
    is_active: bool
    created_at: str
    updated_at: str


class CreateEmbeddingIntegrationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: str = Field(default="openai")
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    dimension: int = Field(gt=0, le=16384)
    api_key: str = Field(default="")
    is_active: bool = Field(default=False)
    force: bool = Field(default=False)


class UpdateEmbeddingIntegrationRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider: str | None = None
    base_url: str | None = None
    model: str | None = Field(default=None, min_length=1)
    dimension: int | None = Field(default=None, gt=0, le=16384)
    api_key: str | None = None
    is_active: bool | None = None
    force: bool = Field(default=False)


class TestEmbeddingIntegrationRequest(BaseModel):
    model: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    dimension: int | None = Field(default=None, gt=0)
    api_key: str | None = None
    integration_id: str | None = None


@router.get("/embedding-integrations")
def list_embedding_integrations(service: Services) -> dict[str, Any]:
    """Danh sách cấu hình tích hợp embedding (API key đã được che an toàn)."""
    return {"integrations": service.embedding_integrations.list_integrations()}


@router.get("/embedding-integrations/active")
def get_active_embedding_integration(service: Services) -> dict[str, Any] | None:
    """Thông tin tích hợp embedding đang kích hoạt — null khi chưa cấu hình (không fallback env)."""
    return service.embedding_integrations.get_active_integration_info()


@router.post("/embedding-integrations", response_model=EmbeddingIntegrationResponseModel)
def create_embedding_integration(
    req: CreateEmbeddingIntegrationRequest, service: Services
) -> dict[str, Any]:
    """Tạo cấu hình tích hợp embedding mới, mã hóa API key bằng DEK/KEK."""
    try:
        created = service.embedding_integrations.create_integration(
            name=req.name,
            model=req.model,
            dimension=req.dimension,
            base_url=req.base_url,
            provider=req.provider,
            api_key=req.api_key,
            is_active=req.is_active,
            force=req.force,
        )
    except EmbeddingDimensionConflict as exc:
        raise _conflict_http(exc) from exc
    logger.info(
        "Tạo tích hợp embedding mới id=%s name=%r model=%r dim=%d",
        created["id"],
        req.name,
        req.model,
        req.dimension,
    )
    return created


@router.put(
    "/embedding-integrations/{integration_id}",
    response_model=EmbeddingIntegrationResponseModel,
)
def update_embedding_integration(
    integration_id: str,
    req: UpdateEmbeddingIntegrationRequest,
    service: Services,
) -> dict[str, Any]:
    """Cập nhật cấu hình tích hợp embedding. Nếu api_key được truyền vào thì mã hóa lại."""
    try:
        updated = service.embedding_integrations.update_integration(
            integration_id=integration_id,
            name=req.name,
            model=req.model,
            dimension=req.dimension,
            base_url=req.base_url,
            provider=req.provider,
            api_key=req.api_key,
            is_active=req.is_active,
            force=req.force,
        )
    except EmbeddingDimensionConflict as exc:
        raise _conflict_http(exc) from exc
    if not updated:
        raise HTTPException(404, "Không tìm thấy cấu hình tích hợp embedding")
    logger.info(
        "Cập nhật tích hợp embedding id=%s name=%r model=%r",
        integration_id,
        updated["name"],
        updated["model"],
    )
    return updated


@router.delete("/embedding-integrations/{integration_id}")
def delete_embedding_integration(
    integration_id: str, service: Services, force: bool = False
) -> dict[str, Any]:
    """Xóa một cấu hình tích hợp embedding."""
    try:
        deleted = service.embedding_integrations.delete_integration(
            integration_id, force=force
        )
    except EmbeddingDimensionConflict as exc:
        raise _conflict_http(exc) from exc
    if not deleted:
        raise HTTPException(404, "Không tìm thấy cấu hình tích hợp embedding")
    logger.info("Xóa tích hợp embedding id=%s", integration_id)
    return {"ok": True}


@router.post(
    "/embedding-integrations/{integration_id}/activate",
    response_model=EmbeddingIntegrationResponseModel,
)
def activate_embedding_integration(
    integration_id: str, service: Services, force: bool = False
) -> dict[str, Any]:
    """Kích hoạt một cấu hình tích hợp embedding làm mặc định.

    Nếu chiều khác index hiện tại và còn chunk → 409; gửi lại force=true sau khi
    user xác nhận để reset index (mọi file chuyển 'cần nạp lại').
    """
    try:
        activated = service.embedding_integrations.activate_integration(
            integration_id, force=force
        )
    except EmbeddingDimensionConflict as exc:
        raise _conflict_http(exc) from exc
    if not activated:
        raise HTTPException(404, "Không tìm thấy cấu hình tích hợp embedding")
    logger.info(
        "Kích hoạt tích hợp embedding id=%s name=%r dim=%d",
        integration_id,
        activated["name"],
        activated["dimension"],
    )
    return activated


@router.post("/embedding-integrations/test")
def test_embedding_integration(
    req: TestEmbeddingIntegrationRequest, service: Services
) -> dict[str, Any]:
    """Kiểm tra kết nối tới embedding provider — embed thử 1 text, trả chiều thực tế."""
    try:
        return service.embedding_integrations.test_connection(
            model=req.model,
            base_url=req.base_url,
            dimension=req.dimension,
            api_key=req.api_key,
            integration_id=req.integration_id,
        )
    except Exception as exc:
        logger.warning("Test kết nối embedding thất bại: %s", exc)
        raise HTTPException(400, f"Kiểm tra kết nối thất bại: {exc}") from exc

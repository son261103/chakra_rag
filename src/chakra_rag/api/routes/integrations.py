"""Endpoints quản lý tích hợp LLM (OpenAI-compatible)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from chakra_rag.service.container import ServiceContainer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["integrations"])


class IntegrationResponseModel(BaseModel):
    id: str
    name: str
    provider: str = "openai"
    base_url: str
    model: str
    masked_api_key: str
    has_api_key: bool
    is_active: bool
    created_at: str
    updated_at: str


class CreateIntegrationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: str = Field(default="openai")
    base_url: str = Field(default="https://api.openai.com/v1")
    model: str = Field(min_length=1)
    api_key: str = Field(default="")
    is_active: bool = Field(default=False)


class UpdateIntegrationRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    provider: str | None = None
    base_url: str | None = None
    model: str | None = Field(default=None, min_length=1)
    api_key: str | None = None
    is_active: bool | None = None


class TestIntegrationRequest(BaseModel):
    model: str = Field(min_length=1)
    base_url: str = Field(default="https://api.openai.com/v1")
    api_key: str | None = None
    integration_id: str | None = None


@router.get("/integrations")
def list_integrations(request: Request) -> dict[str, Any]:
    """Danh sách các cấu hình tích hợp LLM (API key đã được che an toàn)."""
    service: ServiceContainer = request.app.state.service
    return {"integrations": service.integrations.list_integrations()}


@router.get("/integrations/active")
def get_active_integration(request: Request) -> dict[str, Any]:
    """Lấy thông tin tích hợp LLM đang được kích hoạt."""
    service: ServiceContainer = request.app.state.service
    return service.integrations.get_active_integration_info()


@router.post("/integrations", response_model=IntegrationResponseModel)
def create_integration(req: CreateIntegrationRequest, request: Request) -> dict[str, Any]:
    """Tạo cấu hình tích hợp LLM mới, mã hóa API key bằng DEK/KEK."""
    service: ServiceContainer = request.app.state.service
    created = service.integrations.create_integration(
        name=req.name,
        model=req.model,
        base_url=req.base_url,
        provider=req.provider,
        api_key=req.api_key,
        is_active=req.is_active,
    )
    logger.info("Tạo tích hợp LLM mới id=%s name=%r model=%r", created["id"], req.name, req.model)
    return created


@router.put("/integrations/{integration_id}", response_model=IntegrationResponseModel)
def update_integration(
    integration_id: str,
    req: UpdateIntegrationRequest,
    request: Request,
) -> dict[str, Any]:
    """Cập nhật cấu hình tích hợp LLM. Nếu api_key được truyền vào thì mã hóa lại."""
    service: ServiceContainer = request.app.state.service
    updated = service.integrations.update_integration(
        integration_id=integration_id,
        name=req.name,
        model=req.model,
        base_url=req.base_url,
        provider=req.provider,
        api_key=req.api_key,
        is_active=req.is_active,
    )
    if not updated:
        raise HTTPException(404, "Không tìm thấy cấu hình tích hợp")
    logger.info(
        "Cập nhật tích hợp LLM id=%s name=%r model=%r",
        integration_id,
        updated["name"],
        updated["model"],
    )
    return updated


@router.delete("/integrations/{integration_id}")
def delete_integration(integration_id: str, request: Request) -> dict[str, Any]:
    """Xóa một cấu hình tích hợp LLM."""
    service: ServiceContainer = request.app.state.service
    if not service.integrations.delete_integration(integration_id):
        raise HTTPException(404, "Không tìm thấy cấu hình tích hợp")
    logger.info("Xóa tích hợp LLM id=%s", integration_id)
    return {"ok": True}


@router.post("/integrations/{integration_id}/activate", response_model=IntegrationResponseModel)
def activate_integration(integration_id: str, request: Request) -> dict[str, Any]:
    """Kích hoạt một cấu hình tích hợp LLM làm mặc định."""
    service: ServiceContainer = request.app.state.service
    activated = service.integrations.activate_integration(integration_id)
    if not activated:
        raise HTTPException(404, "Không tìm thấy cấu hình tích hợp")
    logger.info("Kích hoạt tích hợp LLM id=%s name=%r", integration_id, activated["name"])
    return activated


@router.post("/integrations/test")
def test_integration(req: TestIntegrationRequest, request: Request) -> dict[str, Any]:
    """Kiểm tra kết nối tới LLM provider với model và API key được chỉ định."""
    service: ServiceContainer = request.app.state.service
    try:
        return service.integrations.test_connection(
            model=req.model,
            base_url=req.base_url,
            api_key=req.api_key,
            integration_id=req.integration_id,
        )
    except Exception as exc:
        logger.warning("Test kết nối LLM thất bại: %s", exc)
        raise HTTPException(400, f"Kiểm tra kết nối thất bại: {exc}") from exc

"""Dependency dùng chung cho các route: expose ServiceContainer qua Depends."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from service.container import ServiceContainer


def get_service(request: Request) -> ServiceContainer:
    """Lấy composition root được lifespan gắn lên app.state."""
    return request.app.state.service

# app.dependency_overrides[get_service].
Services = Annotated[ServiceContainer, Depends(get_service)]

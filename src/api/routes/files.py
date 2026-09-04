"""Endpoints quản lý tệp tin và tiến trình ingest (embedding)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile

from service.container import ServiceContainer

logger = logging.getLogger(__name__)

router = APIRouter(tags=["files"])


@router.post("/files")
async def upload_file(file: UploadFile, request: Request) -> dict[str, Any]:
    """Lưu file upload và đưa vào hàng đợi ingest."""
    from config import get_config

    service: ServiceContainer = request.app.state.service
    suffix = (file.filename or "").rsplit(".", 1)[-1]
    supported = get_config().supported_suffixes
    if f".{suffix}".lower() not in supported:
        raise HTTPException(400, f"Chỉ hỗ trợ: {', '.join(sorted(supported))}")
    content = await file.read()
    if not content.strip():
        raise HTTPException(400, "File rỗng")

    return service.files.upload_file(file.filename or "uploaded.txt", content)


@router.get("/files")
def list_files(request: Request) -> dict[str, Any]:
    service: ServiceContainer = request.app.state.service
    return {"files": service.files.list_files()}


@router.get("/files/{file_id}/chunks")
def list_file_chunks(file_id: str, request: Request) -> dict[str, Any]:
    """Xem dữ liệu đã ingest (chunks) + full text gốc trên đĩa — UI inspector."""
    service: ServiceContainer = request.app.state.service
    result = service.files.inspect_file(file_id)
    if result is None:
        raise HTTPException(404, "Không tìm thấy file")
    return result


@router.post("/files/{file_id}/reingest")
def reingest_file(file_id: str, request: Request) -> dict[str, Any]:
    """Nhúng lại (parse → chunk → embed) một file đã có trên đĩa."""
    service: ServiceContainer = request.app.state.service
    try:
        return service.files.reingest_file(file_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(404, str(exc)) from exc


@router.delete("/files/{file_id}")
def delete_file(file_id: str, request: Request) -> dict[str, Any]:
    """Xóa file khỏi index (+ file trên đĩa nếu nằm trong uploads/docs)."""
    service: ServiceContainer = request.app.state.service
    try:
        return service.files.delete_file(file_id, remove_disk=True)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/ingest/reingest")
def reingest_all(request: Request) -> dict[str, Any]:
    """Nhúng lại toàn bộ file còn trên đĩa (nút “Nhúng lại RAG” trên UI)."""
    service: ServiceContainer = request.app.state.service
    return service.files.reingest_all()


@router.get("/ingest/progress")
def ingest_progress(request: Request) -> dict[str, Any]:
    service: ServiceContainer = request.app.state.service
    return service.files.get_progress()

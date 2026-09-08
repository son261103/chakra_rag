"""Endpoints quản lý tệp tin và tiến trình ingest (embedding)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

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
    """Xóa file khỏi index (+ file trên đĩa nếu nằm trong uploads)."""
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


@router.get("/ingest/events")
async def ingest_events(request: Request) -> StreamingResponse:
    """SSE thay cho polling: đẩy snapshot {files, progress} mỗi khi ingest đổi trạng thái.

    Worker notify qua IngestEventBus sau mỗi lần ghi (queued/parsing/embedding
    progress/ready/failed/delete); ở đây chờ tín hiệu rồi đẩy snapshot mới.
    Giữa 2 lần đổi trạng thái gửi keepalive comment mỗi 15s để proxy không đóng
    kết nối. Snapshot đọc DB là hàm sync nên chạy qua to_thread khỏi chặn event loop.
    """
    service: ServiceContainer = request.app.state.service

    async def stream():
        version = await asyncio.to_thread(service.files.ingest_version)
        snapshot = await asyncio.to_thread(service.files.ingest_snapshot)
        yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
        while True:
            if await request.is_disconnected():
                return
            changed = await asyncio.to_thread(service.files.wait_ingest_change, version, 15.0)
            if changed is None:
                yield ": keepalive\n\n"
                continue
            version = changed
            snapshot = await asyncio.to_thread(service.files.ingest_snapshot)
            yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

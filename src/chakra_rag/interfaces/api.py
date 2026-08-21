"""FastAPI — lớp mỏng bọc RagService + IngestWorker, không chứa nghiệp vụ.

Endpoints:
- POST /files            upload file (.md/.txt) → đưa vào hàng đợi ingest
- GET  /files            danh sách file + trạng thái từng file
- GET  /ingest/progress  tiến trình embedding tổng hợp (UI poll)
- POST /ask              hỏi → agent loop → verified answer + citations
- POST /ask/stream       như /ask nhưng trả SSE: thinking/tool_call/answer gõ dần
- GET  /chunks/{id}      xem chunk gốc (kiểm tra trích dẫn)
- GET  /health
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from chakra_rag.config import get_config
from chakra_rag.ingestion.worker import (
    SUPPORTED_SUFFIXES,
    IngestWorker,
)
from chakra_rag.service.rag_service import RagService

ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    service = RagService(cfg)
    worker = IngestWorker(cfg, service.store, service.embedder)
    # Không auto-seed data/docs: chỉ index file user upload qua POST /files
    # (hoặc chạy tay: python -m chakra_rag ingest).

    worker.start()
    app.state.service = service
    app.state.worker = worker
    yield
    worker.stop()
    service.close()


app = FastAPI(title="Chakra RAG", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    mode: str = Field(default="agent", pattern="^(agent|stuff)$")
    top_k: int | None = Field(default=None, ge=1, le=20)


@app.get("/health")
def health():
    service: RagService = app.state.service
    return {"status": "ok", "chunks": service.store.count_chunks()}


@app.post("/files")
async def upload_file(file: UploadFile):
    """Lưu file upload và đưa vào hàng đợi ingest."""
    cfg = get_config()
    worker: IngestWorker = app.state.worker

    suffix = (file.filename or "").rsplit(".", 1)[-1]
    if f".{suffix}".lower() not in SUPPORTED_SUFFIXES:
        raise HTTPException(400, f"Chỉ hỗ trợ: {', '.join(sorted(SUPPORTED_SUFFIXES))}")

    content = await file.read()
    if not content.strip():
        raise HTTPException(400, "File rỗng")

    dest = cfg.uploads_dir / file.filename
    dest.write_bytes(content)
    file_id = worker.enqueue(dest, source="upload")
    return {"file_id": file_id, "name": file.filename, "status": "queued"}


@app.get("/files")
def list_files():
    service: RagService = app.state.service
    return {"files": service.store.list_files()}


@app.get("/ingest/progress")
def ingest_progress():
    worker: IngestWorker = app.state.worker
    return worker.progress()


@app.post("/ask")
def ask(req: AskRequest):
    service: RagService = app.state.service
    progress = app.state.worker.progress()
    if progress["status"] not in ("ready", "partial"):
        raise HTTPException(503, "Index chưa sẵn sàng — chờ ingest hoàn tất")
    return service.ask(req.question, mode=req.mode, top_k=req.top_k)


@app.post("/ask/stream")
def ask_stream(req: AskRequest):
    """SSE: mỗi event là 1 dòng `data: {json}`.

    Events: thinking (delta), tool_call (kết quả 1 lượt search), answer (delta),
    done (payload chuẩn đã verify), error.
    """
    service: RagService = app.state.service
    progress = app.state.worker.progress()
    if progress["status"] not in ("ready", "partial"):
        raise HTTPException(503, "Index chưa sẵn sàng — chờ ingest hoàn tất")

    def event_stream():
        for event in service.ask_stream(req.question, mode=req.mode, top_k=req.top_k):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/chunks/{chunk_id}")
def get_chunk(chunk_id: str):
    service: RagService = app.state.service
    chunk = service.get_chunk(chunk_id)
    if chunk is None:
        raise HTTPException(404, "Không tìm thấy chunk")
    return chunk

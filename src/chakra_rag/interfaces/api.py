"""FastAPI — lớp mỏng bọc RagService + IngestWorker, không chứa nghiệp vụ.

Endpoints:
- POST /files            upload file (.md/.txt/.pdf) → đưa vào hàng đợi ingest
- GET  /files            danh sách file + trạng thái từng file
- GET  /ingest/progress  tiến trình embedding tổng hợp (UI poll)
- GET/POST/DELETE /conversations  lịch sử hội thoại (SQLite)
- POST /ask              hỏi → agent loop → verified answer + citations
- POST /ask/stream       như /ask nhưng trả SSE: thinking/tool_call/answer gõ dần
- GET  /chunks/{id}      xem chunk gốc (kiểm tra trích dẫn)
- GET  /health
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from chakra_rag.config import get_config
from chakra_rag.ingestion.worker import IngestWorker
from chakra_rag.observability.logging_setup import setup_logging
from chakra_rag.service.rag_service import RagService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    cfg = get_config()
    service = RagService(cfg)
    worker = IngestWorker(cfg, service.store, service.embedder)
    # Không auto-seed data/docs: chỉ index file user upload qua POST /files
    # (hoặc chạy tay: python -m chakra_rag ingest).

    # Không auto-seed / không auto-reingest khi start.
    # Job dở (queued/parsing/…) từ process trước → failed, user bấm "Nhúng lại RAG".
    interrupted = service.store.fail_interrupted_ingests()
    if interrupted:
        logger.warning(
            "marked %d interrupted ingest job(s) as failed (no auto-reingest on startup)",
            interrupted,
        )

    worker.start()
    app.state.service = service
    app.state.worker = worker
    logger.info(
        "API up db=%s uploads=%s chunks=%d files=%d (ready statuses only from previous successful ingest)",
        cfg.db_path,
        cfg.uploads_dir,
        service.store.count_chunks(),
        len(service.store.list_files()),
    )
    yield
    worker.stop()
    service.close()
    logger.info("API shutdown")


app = FastAPI(title="Chakra RAG", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_config().api_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    mode: str = Field(default="agent", pattern="^(agent|stuff)$")
    top_k: int | None = Field(default=None, ge=1, le=20)
    conversation_id: str | None = None


class CreateConversationRequest(BaseModel):
    title: str = Field(default="Hội thoại mới", min_length=1, max_length=200)


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
    supported = get_config().supported_suffixes
    if f".{suffix}".lower() not in supported:
        raise HTTPException(400, f"Chỉ hỗ trợ: {', '.join(sorted(supported))}")

    content = await file.read()
    if not content.strip():
        raise HTTPException(400, "File rỗng")

    dest = cfg.uploads_dir / file.filename
    dest.write_bytes(content)
    file_id = worker.enqueue(dest, source="upload")
    logger.info("upload accepted file_id=%s name=%s bytes=%d", file_id, file.filename, len(content))
    return {"file_id": file_id, "name": file.filename, "status": "queued"}


@app.get("/files")
def list_files():
    service: RagService = app.state.service
    return {"files": service.store.list_files()}


@app.get("/files/{file_id}/chunks")
def list_file_chunks(file_id: str):
    """Xem dữ liệu đã ingest (chunks) + full text gốc trên đĩa — UI inspector."""
    from chakra_rag.ingestion.worker import extract_text

    service: RagService = app.state.service
    worker: IngestWorker = app.state.worker
    meta = service.store.get_file(file_id)
    if meta is None:
        raise HTTPException(404, "Không tìm thấy file")
    chunks = service.store.list_chunks_by_doc(meta["name"])
    full_text = ""
    full_text_error = None
    path = worker.resolve_path(meta["name"], meta.get("source"))
    if path is None:
        full_text_error = "Không tìm thấy file gốc trên đĩa"
    else:
        try:
            full_text = extract_text(path)
        except (OSError, ValueError, RuntimeError) as exc:
            full_text_error = str(exc)
            logger.warning("inspect extract failed file_id=%s err=%s", file_id, exc)
        except Exception as exc:  # noqa: BLE001 — parser libs raise misc; log & degrade
            full_text_error = f"{type(exc).__name__}: {exc}"
            logger.warning("inspect extract failed (unexpected) file_id=%s", file_id, exc_info=True)
    logger.info(
        "inspect file_id=%s name=%s chunks=%d full_chars=%d status=%s",
        file_id,
        meta["name"],
        len(chunks),
        len(full_text),
        meta.get("status"),
    )
    return {
        "file": {
            "file_id": meta["file_id"],
            "name": meta["name"],
            "source": meta["source"],
            "status": meta["status"],
            "chunks_total": meta["chunks_total"],
            "chunks_done": meta["chunks_done"],
            "error": meta.get("error"),
        },
        "chunks": chunks,
        "chunk_count": len(chunks),
        "full_text": full_text,
        "full_text_chars": len(full_text),
        "full_text_error": full_text_error,
    }


@app.post("/files/{file_id}/reingest")
def reingest_file(file_id: str):
    """Nhúng lại (parse → chunk → embed) một file đã có trên đĩa."""
    worker: IngestWorker = app.state.worker
    try:
        result = worker.requeue_file_id(file_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return result


@app.delete("/files/{file_id}")
def delete_file(file_id: str):
    """Xóa file khỏi index (+ file trên đĩa nếu nằm trong uploads/docs)."""
    worker: IngestWorker = app.state.worker
    try:
        result = worker.delete_file(file_id, remove_disk=True)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return result


@app.post("/ingest/reingest")
def reingest_all():
    """Nhúng lại toàn bộ file còn trên đĩa (nút “Nhúng lại RAG” trên UI)."""
    worker: IngestWorker = app.state.worker
    result = worker.requeue_all()
    logger.info(
        "reingest-all api queued=%d skipped=%d",
        len(result["queued"]),
        len(result["skipped"]),
    )
    return result


@app.get("/ingest/progress")
def ingest_progress():
    worker: IngestWorker = app.state.worker
    return worker.progress()


@app.get("/conversations")
def list_conversations():
    service: RagService = app.state.service
    return {"conversations": service.store.list_conversations()}


@app.post("/conversations")
def create_conversation(req: CreateConversationRequest | None = None):
    service: RagService = app.state.service
    title = (req.title if req else None) or "Hội thoại mới"
    return service.store.create_conversation(title=title)


@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    service: RagService = app.state.service
    conv = service.store.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(404, "Không tìm thấy hội thoại")
    messages = service.store.list_messages(conversation_id)
    return {**conv, "messages": messages}


@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str):
    service: RagService = app.state.service
    if not service.store.delete_conversation(conversation_id):
        raise HTTPException(404, "Không tìm thấy hội thoại")
    return {"ok": True}


@app.post("/ask")
def ask(req: AskRequest):
    service: RagService = app.state.service
    progress = app.state.worker.progress()
    if progress["status"] not in ("ready", "partial"):
        raise HTTPException(503, "Index chưa sẵn sàng — chờ ingest hoàn tất")
    if req.conversation_id and service.store.get_conversation(req.conversation_id) is None:
        raise HTTPException(404, "Không tìm thấy hội thoại")
    return service.ask(
        req.question,
        mode=req.mode,
        top_k=req.top_k,
        conversation_id=req.conversation_id,
    )


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
    if req.conversation_id and service.store.get_conversation(req.conversation_id) is None:
        raise HTTPException(404, "Không tìm thấy hội thoại")

    def event_stream():
        for event in service.ask_stream(
            req.question,
            mode=req.mode,
            top_k=req.top_k,
            conversation_id=req.conversation_id,
        ):
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

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
from typing import Any

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
        "API up db=%s uploads=%s chunks=%d files=%d "
        "(ready statuses only from previous successful ingest)",
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


class ChunkRef(BaseModel):
    chunk_id: str
    doc: str | None = None
    section: str | None = None
    score: float | None = None
    text: str | None = None


class AskResponseModel(BaseModel):
    question: str
    answer: str
    mode: str
    citations: list[ChunkRef]
    invalid_citations: list[str]
    unsupported_claims: list[str]
    search_trace: list[dict[str, Any]]
    reasoning: str
    low_confidence: bool
    latency_ms: int
    conversation_id: str | None


class HealthResponse(BaseModel):
    status: str
    chunks: int


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


def _format_integration_item(item: dict[str, Any], kek_secret: str) -> dict[str, Any]:
    from chakra_rag.core.security import decrypt_integration_key, mask_api_key

    raw_key = ""
    try:
        raw_key = decrypt_integration_key(
            item.get("encrypted_api_key", ""),
            item.get("encrypted_dek", ""),
            kek_secret,
        )
    except Exception:
        raw_key = ""

    return {
        "id": item["id"],
        "name": item["name"],
        "provider": item.get("provider", "openai"),
        "base_url": item["base_url"],
        "model": item["model"],
        "masked_api_key": mask_api_key(raw_key),
        "has_api_key": bool(raw_key),
        "is_active": bool(item.get("is_active", 0)),
        "created_at": item.get("created_at", ""),
        "updated_at": item.get("updated_at", ""),
    }

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    service: RagService = app.state.service
    return {"status": "ok", "chunks": service.store.count_chunks()}


@app.post("/files")
async def upload_file(file: UploadFile) -> dict[str, Any]:
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
def list_files() -> dict[str, Any]:
    service: RagService = app.state.service
    return {"files": service.store.list_files()}


@app.get("/files/{file_id}/chunks")
def list_file_chunks(file_id: str) -> dict[str, Any]:
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
def reingest_file(file_id: str) -> dict[str, Any]:
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
def delete_file(file_id: str) -> dict[str, Any]:
    """Xóa file khỏi index (+ file trên đĩa nếu nằm trong uploads/docs)."""
    worker: IngestWorker = app.state.worker
    try:
        result = worker.delete_file(file_id, remove_disk=True)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return result


@app.post("/ingest/reingest")
def reingest_all() -> dict[str, Any]:
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
def ingest_progress() -> dict[str, Any]:
    worker: IngestWorker = app.state.worker
    return worker.progress()


@app.get("/conversations")
def list_conversations() -> dict[str, Any]:
    service: RagService = app.state.service
    return {"conversations": service.store.list_conversations()}


@app.post("/conversations")
def create_conversation(
    req: CreateConversationRequest | None = None,
) -> dict[str, Any]:
    service: RagService = app.state.service
    title = (req.title if req else None) or "Hội thoại mới"
    return service.store.create_conversation(title=title)


@app.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict[str, Any]:
    service: RagService = app.state.service
    conv = service.store.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(404, "Không tìm thấy hội thoại")
    messages = service.store.list_messages(conversation_id)
    return {**conv, "messages": messages}


@app.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, Any]:
    service: RagService = app.state.service
    if not service.store.delete_conversation(conversation_id):
        raise HTTPException(404, "Không tìm thấy hội thoại")
    return {"ok": True}


@app.post("/ask", response_model=AskResponseModel)
def ask(req: AskRequest) -> AskResponseModel:
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
def get_chunk(chunk_id: str) -> dict[str, Any]:
    service: RagService = app.state.service
    chunk = service.get_chunk(chunk_id)
    if chunk is None:
        raise HTTPException(404, "Không tìm thấy chunk")
    return chunk


# ---------- Integrations (Cấu hình LLM) ----------

@app.get("/integrations")
def list_integrations() -> dict[str, Any]:
    """Danh sách các cấu hình tích hợp LLM (API key đã được che an toàn)."""
    service: RagService = app.state.service
    cfg = get_config()
    rows = service.store.list_integrations()
    items = [_format_integration_item(r, cfg.encryption_key) for r in rows]
    return {"integrations": items}


@app.get("/integrations/active")
def get_active_integration() -> dict[str, Any]:
    """Lấy thông tin tích hợp LLM đang được kích hoạt."""
    service: RagService = app.state.service
    return service.get_active_integration_info()


@app.post("/integrations", response_model=IntegrationResponseModel)
def create_integration(req: CreateIntegrationRequest) -> dict[str, Any]:
    """Tạo cấu hình tích hợp LLM mới, mã hóa API key bằng DEK/KEK."""
    from chakra_rag.core.security import encrypt_integration_key

    service: RagService = app.state.service
    cfg = get_config()
    enc = encrypt_integration_key(req.api_key, cfg.encryption_key)
    created = service.store.create_integration(
        name=req.name,
        model=req.model,
        base_url=req.base_url,
        provider=req.provider,
        encrypted_api_key=enc.encrypted_api_key,
        encrypted_dek=enc.encrypted_dek,
        is_active=req.is_active,
    )
    service.reload_agent()
    logger.info("Tạo tích hợp LLM mới id=%s name=%r model=%r", created["id"], req.name, req.model)
    return _format_integration_item(created, cfg.encryption_key)


@app.put("/integrations/{integration_id}", response_model=IntegrationResponseModel)
def update_integration(integration_id: str, req: UpdateIntegrationRequest) -> dict[str, Any]:
    """Cập nhật cấu hình tích hợp LLM. Nếu api_key được truyền vào thì mã hóa lại."""
    service: RagService = app.state.service
    cfg = get_config()
    existing = service.store.get_integration(integration_id)
    if not existing:
        raise HTTPException(404, "Không tìm thấy cấu hình tích hợp")

    enc_key: str | None = None
    enc_dek: str | None = None
    if req.api_key is not None:
        from chakra_rag.core.security import encrypt_integration_key

        enc = encrypt_integration_key(req.api_key, cfg.encryption_key)
        enc_key = enc.encrypted_api_key
        enc_dek = enc.encrypted_dek

    updated = service.store.update_integration(
        integration_id=integration_id,
        name=req.name,
        model=req.model,
        base_url=req.base_url,
        provider=req.provider,
        encrypted_api_key=enc_key,
        encrypted_dek=enc_dek,
        is_active=req.is_active,
    )
    if not updated:
        raise HTTPException(404, "Cập nhật thất bại")
    service.reload_agent()
    logger.info(
        "Cập nhật tích hợp LLM id=%s name=%r model=%r",
        integration_id,
        updated["name"],
        updated["model"],
    )
    return _format_integration_item(updated, cfg.encryption_key)


@app.delete("/integrations/{integration_id}")
def delete_integration(integration_id: str) -> dict[str, Any]:
    """Xóa một cấu hình tích hợp LLM."""
    service: RagService = app.state.service
    if not service.store.delete_integration(integration_id):
        raise HTTPException(404, "Không tìm thấy cấu hình tích hợp")
    service.reload_agent()
    logger.info("Xóa tích hợp LLM id=%s", integration_id)
    return {"ok": True}


@app.post("/integrations/{integration_id}/activate", response_model=IntegrationResponseModel)
def activate_integration(integration_id: str) -> dict[str, Any]:
    """Kích hoạt một cấu hình tích hợp LLM làm mặc định."""
    service: RagService = app.state.service
    cfg = get_config()
    activated = service.store.set_active_integration(integration_id)
    if not activated:
        raise HTTPException(404, "Không tìm thấy cấu hình tích hợp")
    service.reload_agent()
    logger.info("Kích hoạt tích hợp LLM id=%s name=%r", integration_id, activated["name"])
    return _format_integration_item(activated, cfg.encryption_key)


@app.post("/integrations/test")
def test_integration(req: TestIntegrationRequest) -> dict[str, Any]:
    """Kiểm tra kết nối tới LLM provider với model và API key được chỉ định."""
    service: RagService = app.state.service
    cfg = get_config()
    api_key = req.api_key
    if not api_key and req.integration_id:
        existing = service.store.get_integration(req.integration_id)
        if existing:
            from chakra_rag.core.security import decrypt_integration_key

            try:
                api_key = decrypt_integration_key(
                    existing.get("encrypted_api_key", ""),
                    existing.get("encrypted_dek", ""),
                    cfg.encryption_key,
                )
            except Exception as exc:
                raise HTTPException(400, f"Không thể giải mã API key đã lưu: {exc}") from exc
    try:
        return service.test_llm_connection(
            model=req.model,
            base_url=req.base_url,
            api_key=api_key or "",
        )
    except Exception as exc:
        logger.warning("Test kết nối LLM thất bại: %s", exc)
        raise HTTPException(400, f"Kiểm tra kết nối thất bại: {exc}") from exc

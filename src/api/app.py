"""FastAPI Application Factory & Lifecycle Management."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import (
    chat_router,
    conversations_router,
    files_router,
    health_router,
    integrations_router,
)
from config import get_config
from ingestion.worker import IngestWorker
from observability.logging_setup import setup_logging
from service.container import ServiceContainer

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    cfg = get_config()
    services = ServiceContainer(cfg)
    worker = IngestWorker(cfg, services.store, services.embedder)
    services.attach_worker(worker)

    interrupted = services.store.fail_interrupted_ingests()
    if interrupted:
        logger.warning(
            "marked %d interrupted ingest job(s) as failed (no auto-reingest on startup)",
            interrupted,
        )

    worker.start()
    app.state.service = services
    app.state.worker = worker
    logger.info(
        "API up db=%s uploads=%s chunks=%d files=%d "
        "(ready statuses only from previous successful ingest)",
        cfg.db_path,
        cfg.uploads_dir,
        services.store.count_chunks(),
        len(services.store.list_files()),
    )
    yield
    worker.stop()
    services.close()
    logger.info("API shutdown")

def create_app() -> FastAPI:
    cfg = get_config()
    application = FastAPI(title="Chakra RAG", version="0.1.0", lifespan=lifespan)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.api_allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(health_router)
    application.include_router(files_router)
    application.include_router(conversations_router)
    application.include_router(chat_router)
    application.include_router(integrations_router)

    return application


app = create_app()

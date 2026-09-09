"""FastAPI TestClient suite — upload validation, conversations CRUD-lite, ask không chặn index."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import api as api_mod


@pytest.fixture()
def client(tmp_path):
    """App instance với lifespan mocked: no real store/embedder/worker threads."""
    app = api_mod.app
    service = MagicMock(name="service")
    worker = MagicMock(name="worker")
    service.chunk_repo.count_chunks.return_value = 7
    service.conversations.create_conversation.return_value = {"id": "c1", "title": "Hội thoại mới"}
    service.conversations.list_conversations.return_value = []
    service.files.upload_file.return_value = {
        "file_id": "fid1",
        "name": "notes.md",
        "status": "queued",
    }
    # bypass lifespan init entirely; restore original after tests:
    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _StaticLifespan(app, service=service, worker=worker)
    try:
        with TestClient(app) as c:
            c.service = service  # type: ignore[attr-defined]
            c.worker = worker  # type: ignore[attr-defined]
            yield c
    finally:
        app.router.lifespan_context = original_lifespan


class _StaticLifespan:
    def __init__(self, app, service, worker):
        self.app = app
        self.service = service
        self.worker = worker

    def __call__(self, app):
        # Starlette gọi lifespan_context(app) — trả về chính instance (async CM)
        return self

    async def __aenter__(self):
        self.app.state.service = self.service
        self.app.state.worker = self.worker
        return None

    async def __aexit__(self, *exc):
        return False


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "chunks": 7}


def test_upload_rejects_bad_suffix(client):
    r = client.post("/files", files={"file": ("x.exe", b"MZ", "application/x-msdownload")})
    assert r.status_code == 400


def test_upload_accepts_md(client):
    client.worker.enqueue.return_value = "fid1"
    r = client.post("/files", files={"file": ("notes.md", b"# hi", "text/markdown")})
    assert r.status_code == 200
    assert r.json()["file_id"] == "fid1"

def test_ask_works_when_index_empty(client):
    client.service.chat.ask.return_value = {
        "question": "hi?",
        "answer": "Không tìm thấy thông tin trong tài liệu.",
        "citations": [],
        "invalid_citations": [],
        "unsupported_claims": [],
        "search_trace": [],
        "reasoning": "",
        "low_confidence": True,
        "latency_ms": 5,
        "conversation_id": None,
    }
    r = client.post("/ask", json={"question": "hi?"})
    assert r.status_code == 200
    assert r.json()["low_confidence"] is True


def test_conversations_roundtrip(client):
    r = client.post("/conversations", json={"title": "abc"})
    assert r.status_code == 200
    assert r.json()["id"] == "c1"


def test_list_integrations(client):
    client.service.integrations.list_integrations.return_value = [
        {
            "id": "i1",
            "name": "Default",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "masked_api_key": "sk-...",
            "has_api_key": True,
            "is_active": True,
            "created_at": "2026-09-04T00:00:00",
            "updated_at": "2026-09-04T00:00:00",
        }
    ]
    r = client.get("/integrations")
    assert r.status_code == 200
    items = r.json()["integrations"]
    assert len(items) == 1
    assert items[0]["id"] == "i1"
    assert items[0]["is_active"] is True


def test_create_and_delete_integration(client):
    client.service.integrations.create_integration.return_value = {
        "id": "new-1",
        "name": "New Integration",
        "provider": "openai",
        "base_url": "https://api.test/v1",
        "model": "deepseek-chat",
        "masked_api_key": "sk-...",
        "has_api_key": True,
        "is_active": True,
        "created_at": "2026-09-04T00:00:00",
        "updated_at": "2026-09-04T00:00:00",
    }
    client.service.integrations.delete_integration.return_value = True

    r = client.post(
        "/integrations",
        json={
            "name": "New Integration",
            "base_url": "https://api.test/v1",
            "model": "deepseek-chat",
            "api_key": "sk-123",
            "is_active": True,
        },
    )
    assert r.status_code == 200
    assert r.json()["id"] == "new-1"

    del_res = client.delete("/integrations/new-1")
    assert del_res.status_code == 200
    assert del_res.json() == {"ok": True}


def test_test_integration_endpoint(client):
    client.service.integrations.test_connection.return_value = {
        "ok": True,
        "model": "gpt-4o-mini",
        "response": "Hello",
        "latency_ms": 120,
    }
    r = client.post(
        "/integrations/test",
        json={
            "model": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["latency_ms"] == 120


# ---------- embedding integrations ----------

_EMBED_ROW = {
    "id": "e1",
    "name": "Mistral",
    "provider": "openai",
    "base_url": "https://api.mistral.ai/v1",
    "model": "mistral-embed",
    "dimension": 1024,
    "masked_api_key": "abc...xyz",
    "has_api_key": True,
    "is_active": True,
    "created_at": "2026-09-09T00:00:00",
    "updated_at": "2026-09-09T00:00:00",
}


def test_list_embedding_integrations(client):
    client.service.embedding_integrations.list_integrations.return_value = [_EMBED_ROW]
    r = client.get("/embedding-integrations")
    assert r.status_code == 200
    items = r.json()["integrations"]
    assert items[0]["id"] == "e1"
    assert items[0]["dimension"] == 1024


def test_create_embedding_integration(client):
    client.service.embedding_integrations.create_integration.return_value = _EMBED_ROW
    r = client.post(
        "/embedding-integrations",
        json={
            "name": "Mistral",
            "base_url": "https://api.mistral.ai/v1",
            "model": "mistral-embed",
            "dimension": 1024,
            "api_key": "k",
            "is_active": True,
        },
    )
    assert r.status_code == 200
    assert r.json()["dimension"] == 1024
    client.service.embedding_integrations.create_integration.assert_called_once()


def test_activate_embedding_dimension_conflict_409_then_force(client):
    from service.embedding_integration_service import EmbeddingDimensionConflict

    client.service.embedding_integrations.activate_integration.side_effect = (
        EmbeddingDimensionConflict(384, 1024)
    )
    r = client.post("/embedding-integrations/e1/activate")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["error"] == "dimension_mismatch"
    assert detail["current_dimension"] == 384
    assert detail["new_dimension"] == 1024

    # UI xác nhận xong → gửi lại force=true
    client.service.embedding_integrations.activate_integration.side_effect = None
    client.service.embedding_integrations.activate_integration.return_value = _EMBED_ROW
    r2 = client.post("/embedding-integrations/e1/activate?force=true")
    assert r2.status_code == 200
    client.service.embedding_integrations.activate_integration.assert_called_with(
        "e1", force=True
    )


def test_test_embedding_endpoint(client):
    client.service.embedding_integrations.test_connection.return_value = {
        "ok": True,
        "model": "mistral-embed",
        "dimension": 1024,
        "latency_ms": 50,
    }
    r = client.post(
        "/embedding-integrations/test",
        json={
            "model": "mistral-embed",
            "base_url": "https://api.mistral.ai/v1",
            "dimension": 1024,
        },
    )
    assert r.status_code == 200
    assert r.json()["dimension"] == 1024

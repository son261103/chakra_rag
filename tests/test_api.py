"""FastAPI TestClient suite — index gating, upload validation, conversations CRUD-lite."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from chakra_rag.interfaces import api as api_mod


@pytest.fixture()
def client(tmp_path):
    """App instance với lifespan mocked: no real store/embedder/worker threads."""
    app = api_mod.app
    service = MagicMock(name="service")
    worker = MagicMock(name="worker")
    service.store.count_chunks.return_value = 7
    service.store.list_files.return_value = []
    service.store.list_conversations.return_value = []
    service.store.create_conversation.return_value = {"id": "c1", "title": "Hội thoại mới"}
    worker.progress.return_value = {
        "status": "ready",
        "percent": 100,
        "chunks_done": 1,
        "chunks_total": 1,
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


def test_ask_503_when_index_not_ready(client):
    client.worker.progress.return_value = {"status": "parsing"}
    r = client.post("/ask", json={"question": "hi?"})
    assert r.status_code == 503


def test_conversations_roundtrip(client):
    r = client.post("/conversations", json={"title": "abc"})
    assert r.status_code == 200
    assert r.json()["id"] == "c1"


def test_list_integrations(client):
    client.service.store.list_integrations.return_value = [
        {
            "id": "i1",
            "name": "Default",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
            "encrypted_api_key": "",
            "encrypted_dek": "",
            "is_active": 1,
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
    client.service.store.create_integration.return_value = {
        "id": "new-1",
        "name": "New Integration",
        "provider": "openai",
        "base_url": "https://api.test/v1",
        "model": "deepseek-chat",
        "encrypted_api_key": "",
        "encrypted_dek": "",
        "is_active": 1,
        "created_at": "2026-09-04T00:00:00",
        "updated_at": "2026-09-04T00:00:00",
    }
    client.service.store.delete_integration.return_value = True

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
    assert client.service.reload_agent.called

    del_res = client.delete("/integrations/new-1")
    assert del_res.status_code == 200
    assert del_res.json() == {"ok": True}


def test_test_integration_endpoint(client):
    client.service.test_llm_connection.return_value = {
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

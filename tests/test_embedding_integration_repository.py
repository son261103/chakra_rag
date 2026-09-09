"""Unit tests cho repository `embedding_integrations` + service đồng bộ chiều vector.

Bao gồm flow đổi chiều: conflict → force → reset index (truncate + ALTER + mark file stale).
Không có seed mặc định, không có fallback env — DB trống nghĩa là chưa cấu hình.
"""

from __future__ import annotations

import numpy as np
import pytest

from config import Config
from core.security import encrypt_integration_key
from repositories import ChunkRepository, EmbeddingIntegrationRepository, FileRepository
from service.embedding_integration_service import (
    EmbeddingDimensionConflict,
    EmbeddingIntegrationService,
)
from storage.connection import Database

_FAKE_URL = "http://fake/v1"


def _cfg() -> Config:
    # Embedding KHÔNG có credential env — duy nhất embed_dim (env EMBED_DIM) là
    # chiều mặc định của DB; test tạo Database(embed_dim=4) tường minh nên không phụ thuộc.
    return Config(encryption_key="test-kek")


def _repo(tmp_path) -> EmbeddingIntegrationRepository:
    return EmbeddingIntegrationRepository(Database(tmp_path / "repo.db", embed_dim=4))


# ---------- repository ----------

def test_create_and_list(tmp_path):
    repo = _repo(tmp_path)
    assert repo.count_integrations() == 0

    enc = encrypt_integration_key("api-key-1", "test-kek")
    item = repo.create_integration(
        name="Mistral",
        model="mistral-embed",
        base_url="https://api.mistral.ai/v1",
        dimension=1024,
        encrypted_api_key=enc.encrypted_api_key,
        encrypted_dek=enc.encrypted_dek,
    )
    # Bản ghi đầu tiên tự động active
    assert item["is_active"] == 1
    assert item["dimension"] == 1024

    item2 = repo.create_integration(
        name="OpenAI",
        model="text-embedding-3-small",
        base_url="https://api.openai.com/v1",
        dimension=1536,
        is_active=True,
    )
    assert item2["is_active"] == 1
    assert repo.get_integration(item["id"])["is_active"] == 0
    active = repo.get_active_integration()
    assert active is not None and active["id"] == item2["id"]


def test_update_and_delete(tmp_path):
    repo = _repo(tmp_path)
    item = repo.create_integration(
        name="A", model="m-a", base_url=_FAKE_URL, dimension=4, is_active=True
    )
    updated = repo.update_integration(item["id"], name="A ren", dimension=512)
    assert updated is not None
    assert updated["name"] == "A ren"
    assert updated["dimension"] == 512

    item_b = repo.create_integration(
        name="B", model="m-b", base_url=_FAKE_URL, dimension=8, is_active=False
    )
    assert repo.delete_integration(item["id"]) is True
    active = repo.get_active_integration()
    assert active is not None
    assert active["id"] == item_b["id"]
    assert active["is_active"] == 1


# ---------- chunk repo: dimension ----------

def test_vector_dimension(tmp_path):
    chunk_repo = ChunkRepository(Database(tmp_path / "v.db", embed_dim=4))
    assert chunk_repo.vector_dimension() == 4


def test_migrate_dimension(tmp_path):
    db = Database(tmp_path / "m.db", embed_dim=4)
    chunk_repo = ChunkRepository(db)
    chunk_repo.insert_chunk(
        "c1", "d.md", "s", "text", 0, 4, np.ones(4, dtype=np.float32)
    )
    assert chunk_repo.count_chunks() == 1

    chunk_repo.migrate_dimension(8)
    assert chunk_repo.count_chunks() == 0
    assert chunk_repo.vector_dimension() == 8
    # Insert chiều mới hoạt động, index HNSW đã dựng lại
    chunk_repo.insert_chunk("c2", "d.md", "s", "text 2", 0, 6, np.ones(8, dtype=np.float32))
    assert chunk_repo.count_chunks() == 1
    hits = chunk_repo.vector_search(np.ones(8, dtype=np.float32), top_k=1)
    assert hits and hits[0]["chunk_id"] == "c2"
    db.close()


# ---------- service: flow đổi chiều ----------

def _service(tmp_path):
    db = Database(tmp_path / "svc.db", embed_dim=4)
    repo = EmbeddingIntegrationRepository(db)
    chunk_repo = ChunkRepository(db)
    file_repo = FileRepository(db)
    service = EmbeddingIntegrationService(
        repo, _cfg(), chunk_repo=chunk_repo, file_repo=file_repo
    )
    return db, repo, chunk_repo, file_repo, service


def test_activate_conflict_then_force_resets_index(tmp_path):
    db, repo, chunk_repo, file_repo, service = _service(tmp_path)
    a = repo.create_integration(
        name="A", model="m-a", base_url=_FAKE_URL, dimension=4, is_active=True
    )
    b = repo.create_integration(
        name="B", model="m-b", base_url=_FAKE_URL, dimension=8, is_active=False
    )

    # Index còn chunk → activate config chiều khác phải raise conflict
    chunk_repo.insert_chunk("c1", "d.md", "s", "text", 0, 4, np.ones(4, dtype=np.float32))
    file_repo.upsert_file("f1", "d.md", status="ready", chunks_total=1)
    with pytest.raises(EmbeddingDimensionConflict) as exc:
        service.activate_integration(b["id"])
    assert exc.value.current_dimension == 4
    assert exc.value.new_dimension == 8
    # Conflict KHÔNG được thay đổi gì
    assert repo.get_active_integration()["id"] == a["id"]
    assert chunk_repo.count_chunks() == 1

    # force=True → reset index: vector cũ mất, cột đổi chiều, file marked stale
    activated = service.activate_integration(b["id"], force=True)
    assert activated is not None and activated["dimension"] == 8
    assert chunk_repo.count_chunks() == 0
    assert chunk_repo.vector_dimension() == 8
    files = file_repo.list_files()
    assert files[0]["status"] == "failed"
    assert "nạp lại" in files[0]["error"]
    db.close()


def test_migrate_silent_when_index_empty(tmp_path):
    db, repo, chunk_repo, _, service = _service(tmp_path)
    repo.create_integration(
        name="A", model="m-a", base_url=_FAKE_URL, dimension=4, is_active=True
    )
    b = repo.create_integration(
        name="B", model="m-b", base_url=_FAKE_URL, dimension=8, is_active=False
    )
    # Không có chunk nào → không cần confirm, migrate âm thầm
    activated = service.activate_integration(b["id"])
    assert activated is not None
    assert chunk_repo.vector_dimension() == 8
    db.close()


def test_create_active_with_new_dimension_checks(tmp_path):
    db, repo, chunk_repo, _, service = _service(tmp_path)
    repo.create_integration(
        name="A", model="m-a", base_url=_FAKE_URL, dimension=4, is_active=True
    )
    chunk_repo.insert_chunk("c1", "d.md", "s", "text", 0, 4, np.ones(4, dtype=np.float32))
    with pytest.raises(EmbeddingDimensionConflict):
        service.create_integration(
            name="C",
            model="m-c",
            base_url=_FAKE_URL,
            dimension=8,
            is_active=True,
        )
    # Không có row C được tạo
    assert repo.count_integrations() == 1
    db.close()


def test_delete_active_fallback_dimension_checks(tmp_path):
    db, repo, chunk_repo, _, service = _service(tmp_path)
    a = repo.create_integration(
        name="A", model="m-a", base_url=_FAKE_URL, dimension=4, is_active=True
    )
    repo.create_integration(
        name="B", model="m-b", base_url=_FAKE_URL, dimension=8, is_active=False
    )
    chunk_repo.insert_chunk("c1", "d.md", "s", "text", 0, 4, np.ones(4, dtype=np.float32))
    # Xóa A → fallback sang B (chiều 8 ≠ index 4) → conflict trước khi xóa
    with pytest.raises(EmbeddingDimensionConflict):
        service.delete_integration(a["id"])
    assert repo.count_integrations() == 2
    # force → xóa được + reset index
    assert service.delete_integration(a["id"], force=True) is True
    assert chunk_repo.vector_dimension() == 8
    db.close()


def test_no_seed_no_active_info(tmp_path):
    """DB mới không tự seed gì; get_active_info trả None khi chưa cấu hình."""
    db = Database(tmp_path / "nosseed.db", embed_dim=4)
    repo = EmbeddingIntegrationRepository(db)
    service = EmbeddingIntegrationService(repo, _cfg())
    assert repo.count_integrations() == 0
    assert service.list_integrations() == []
    assert service.get_active_integration_info() is None
    db.close()


def test_reconcile_migrates_empty_stale_index(tmp_path):
    """DB cũ còn chunks ở chiều khác + index trống → startup reconcile migrate âm thầm."""
    db = Database(tmp_path / "rec.db", embed_dim=4)
    repo = EmbeddingIntegrationRepository(db)
    chunk_repo = ChunkRepository(db)
    service = EmbeddingIntegrationService(repo, _cfg(), chunk_repo=chunk_repo)
    # Active integration khai 8 chiều, nhưng bảng chunks đang 4 chiều, trống
    repo.create_integration(
        name="M", model="m", base_url=_FAKE_URL, dimension=8, is_active=True
    )
    assert chunk_repo.vector_dimension() == 4
    service.reconcile_index_dimension()
    assert chunk_repo.vector_dimension() == 8
    db.close()


def test_reconcile_does_not_touch_nonempty_index(tmp_path):
    """Index còn chunk mà lệch chiều → reconcile chỉ cảnh báo, KHÔNG tự xóa."""
    db = Database(tmp_path / "rec2.db", embed_dim=4)
    repo = EmbeddingIntegrationRepository(db)
    chunk_repo = ChunkRepository(db)
    service = EmbeddingIntegrationService(
        repo, _cfg(), chunk_repo=chunk_repo, file_repo=FileRepository(db)
    )
    repo.create_integration(
        name="M", model="m", base_url=_FAKE_URL, dimension=8, is_active=True
    )
    chunk_repo.insert_chunk("c1", "d.md", "s", "t", 0, 1, np.ones(4, dtype=np.float32))
    service.reconcile_index_dimension()
    # Vẫn 4 chiều, chunk còn nguyên
    assert chunk_repo.vector_dimension() == 4
    assert chunk_repo.count_chunks() == 1
    db.close()

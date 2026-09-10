"""Flow batch ingestion của IngestWorker: submit → 'batching' → poll → insert → ready.

Dùng fake Embedder (đúng protocol: resolve_active_config/can_batch/submit_batch/
batch_status/fetch_batch_results/embed) + Database thật (Postgres test schema) —
kiểm tra đúng state machine và mapping vector ↔ chunk, không gọi mạng.

Sync path (provider không batch / integration không bật) vẫn qua embed() như cũ.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from config import Config
from ingestion.worker import IngestWorker, file_id_for
from repositories import ChunkRepository, FileRepository
from storage.connection import Database

DIM = 4


class _FakeBatchEmbedder:
    """Embedder fake: tùy chỉnh qua flag `batch_mode` + hàng đợi kết quả batch."""

    def __init__(self, batch_mode: bool = True):
        self.batch_mode = batch_mode
        self.dim = DIM
        self.submitted: list[list[tuple[str, str]]] = []
        self.statuses: dict[str, str] = {}  # job_id → state
        self.results: dict[str, list[np.ndarray]] = {}

    def resolve_active_config(self):
        from core.providers.base import EmbeddingConfig

        return EmbeddingConfig(
            integration_id="int-1",
            provider="openai" if self.batch_mode else "ollama",
            base_url="http://fake/v1",
            api_key="k",
            model="fake-embed",
            dimension=DIM,
            use_batch=self.batch_mode,
        )

    def resolve_batch_config(self, meta):
        from core.providers.base import EmbeddingConfig

        return EmbeddingConfig(
            integration_id=str(meta.get("integration_id", "int-1")),
            provider=str(meta.get("provider", "openai")),
            base_url=str(meta.get("base_url", "http://fake/v1")),
            api_key="k",
            model=str(meta.get("model", "fake-embed")),
            dimension=int(meta.get("dimension", DIM)),
            use_batch=True,
        )

    def can_batch(self, cfg=None):
        return self.batch_mode

    def submit_batch(self, items, cfg=None):
        job_id = f"job-{len(self.submitted) + 1}"
        self.submitted.append(list(items))
        self.statuses[job_id] = "completed"
        return job_id

    def batch_status(self, job_id, cfg):
        from core.providers.base import BatchStatus

        state = self.statuses.get(job_id, "failed")
        return BatchStatus(state=state, completed=len(self.results.get(job_id, [])), total=0)

    def fetch_batch_results(self, job_id, cfg):
        from core.providers.base import BatchResults

        return BatchResults(ordered=self.results[job_id])

    def embed(self, texts, input_kind="passage", cfg=None):
        return np.stack([self._vec(t) for t in texts])

    def embed_one(self, text, input_kind="passage"):
        return self._vec(text)

    def invalidate(self):
        pass

    @staticmethod
    def _vec(text: str) -> np.ndarray:
        v = np.zeros(DIM, dtype=np.float32)
        v[hash(text) % DIM] = 1.0
        return v


@pytest.fixture()
def env(tmp_path):
    db = Database(tmp_path / "w.db", embed_dim=DIM)
    file_repo = FileRepository(db)
    chunk_repo = ChunkRepository(db)
    cfg = Config(
        db_path=tmp_path / "w.db",
        uploads_dir=tmp_path,
        logs_dir=tmp_path / "logs",
        embed_batch_size=2,
    )
    cfg.ensure_dirs()
    yield tmp_path, cfg, file_repo, chunk_repo
    db.close()


def _make_file(tmp_path: Path, n_chunks: int = 3) -> Path:
    # Heading rõ ràng → chunk theo section (deterministic, đúng n_chunks).
    sections = "\n\n".join(
        f"## Phần {i}\nNội dung chi tiết của phần số {i} dành cho test batch ingestion."
        for i in range(n_chunks)
    )
    path = tmp_path / "doc.txt"
    path.write_text(sections, "utf-8")
    return path


def test_batch_flow_submit_collect_ready(env):
    tmp_path, cfg, file_repo, chunk_repo = env
    embedder = _FakeBatchEmbedder(batch_mode=True)
    worker = IngestWorker(cfg, file_repo, chunk_repo, embedder)
    path = _make_file(tmp_path)
    fid = file_id_for(path)

    worker._process_file(path)

    # Submit xong → status 'batching' + job + meta đầy đủ
    meta = file_repo.get_file(fid)
    assert meta["status"] == "batching"
    assert meta["batch_job_id"] == "job-1"
    assert "openai" in meta["batch_meta"]
    assert len(embedder.submitted[0]) == 3  # mọi chunk được nộp batch
    assert chunk_repo.count_chunks() == 0  # chưa insert gì

    # Kết quả batch: vector theo THỨ TỰ submit (Jina-style ordered)
    embedder.results["job-1"] = [embedder._vec(t) for _, t in embedder.submitted[0]]
    worker._collect_batch_file(file_repo.get_file(fid))

    meta = file_repo.get_file(fid)
    assert meta["status"] == "ready"
    assert meta["chunks_done"] == 3
    assert chunk_repo.count_chunks() == 3
    rows = chunk_repo.fts_search("batch", 10)
    assert len(rows) == 3  # text insert đúng theo chunk_id


def test_batch_count_mismatch_raises_no_silent_insert(env):
    tmp_path, cfg, file_repo, chunk_repo = env
    embedder = _FakeBatchEmbedder()
    worker = IngestWorker(cfg, file_repo, chunk_repo, embedder)
    path = _make_file(tmp_path, n_chunks=3)
    fid = file_id_for(path)
    worker._process_file(path)

    # Provider trả SAI số vector → raise, không insert gì cả
    embedder.results["job-1"] = [embedder._vec("x")]  # thiếu
    with pytest.raises(Exception, match="khác số chunk"):
        worker._collect_batch_file(file_repo.get_file(fid))
    assert chunk_repo.count_chunks() == 0
    assert file_repo.get_file(fid)["status"] == "batching"  # chưa bị đánh failed lung tung


def test_batch_job_failed_marks_file_failed(env):
    tmp_path, cfg, file_repo, chunk_repo = env
    embedder = _FakeBatchEmbedder()
    worker = IngestWorker(cfg, file_repo, chunk_repo, embedder)
    path = _make_file(tmp_path)
    fid = file_id_for(path)
    worker._process_file(path)
    embedder.statuses["job-1"] = "failed"
    worker._poll_batching_files()  # BatchError vĩnh viễn → đánh failed ngay
    meta = file_repo.get_file(fid)
    assert meta["status"] == "failed"
    assert "batch" in (meta["error"] or "").lower()


def test_sync_path_when_not_batch(env):
    tmp_path, cfg, file_repo, chunk_repo = env
    embedder = _FakeBatchEmbedder(batch_mode=False)
    worker = IngestWorker(cfg, file_repo, chunk_repo, embedder)
    path = _make_file(tmp_path, n_chunks=5)
    fid = file_id_for(path)

    worker._process_file(path)
    meta = file_repo.get_file(fid)
    assert meta["status"] == "ready"
    assert meta["batch_job_id"] == ""
    assert chunk_repo.count_chunks() == 5


def test_fail_interrupted_keeps_batching_but_fails_orphan(env):
    tmp_path, cfg, file_repo, chunk_repo = env
    embedder = _FakeBatchEmbedder()
    worker = IngestWorker(cfg, file_repo, chunk_repo, embedder)
    file_repo.upsert_file("f1", "a.txt", status="embedding")
    file_repo.upsert_file("f2", "b.txt", status="batching")
    # set_file_batch gọi SAU upsert (upsert reset batch fields) — đúng thứ tự worker.
    file_repo.set_file_batch("f2", "job-x", '{"provider": "openai"}')
    file_repo.upsert_file("f3", "c.txt", status="batching")  # orphan: chưa kịp set job

    failed = file_repo.fail_interrupted_ingests()

    assert failed == 1  # f1 (embedding) — file 'batching' KHÔNG bị fail_interrupted đụng tới
    assert file_repo.get_file("f1")["status"] == "failed"
    # f2 có job → GIỮ 'batching' cho worker resume poll; f3 orphan → poll đầu tiên đánh failed
    assert file_repo.get_file("f2")["status"] == "batching"
    assert file_repo.get_file("f3")["status"] == "batching"
    embedder.statuses["job-x"] = "completed"  # fake: job vẫn chạy tốt trên provider
    worker._poll_batching_files()
    assert file_repo.get_file("f2")["status"] == "batching"  # job-x vẫn 'completed' ở fake
    assert file_repo.get_file("f3")["status"] == "failed"
    assert "batch_job_id" in (file_repo.get_file("f3")["error"] or "")


def test_reingest_blocked_while_batching(env):
    tmp_path, cfg, file_repo, chunk_repo = env
    embedder = _FakeBatchEmbedder()
    worker = IngestWorker(cfg, file_repo, chunk_repo, embedder)
    path = _make_file(tmp_path)
    fid = file_id_for(path)
    worker._process_file(path)
    with pytest.raises(ValueError, match="batch job"):
        worker.requeue_file_id(fid)

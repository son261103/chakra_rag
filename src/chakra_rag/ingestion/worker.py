"""Ingest: parse file → chunk → embed → ghi vào Store, có tiến trình.

Chạy trong worker nền 1 thread (queue + thread) để:
- tránh ghi SQLite đồng thời,
- tiến trình embedding deterministic (UI đọc % qua bảng `files`).

State machine mỗi file: queued → parsing → chunking → embedding → ready | failed.
"""

from __future__ import annotations

import hashlib
import queue
import re
import threading
import unicodedata
from pathlib import Path

from chakra_rag.core.chunking import Chunk, chunk_markdown, chunk_plain_text
from chakra_rag.config import Config
from chakra_rag.core.embedding import Embedder
from chakra_rag.storage.store import Store

EMBED_BATCH_SIZE = 16
SUPPORTED_SUFFIXES = {".md", ".txt"}


def file_id_for(path: Path) -> str:
    """ID ổn định theo tên file (không theo đường dẫn) để seed/upload trùng tên không đụng."""
    return hashlib.sha1(path.name.encode("utf-8")).hexdigest()[:12]


def _slug(text: str) -> str:
    """Slug hóa section thành ASCII để ghép chunk_id: 'Số ngày phép năm' → 'so-ngay-phep-nam'.

    Cố tình bỏ dấu tiếng Việt → chunk_id thuần ASCII. Lý do: LLM phải tái tạo
    chính xác chunk_id khi trích dẫn; ID có dấu dễ bị model viết sai ký tự,
    làm citation mismatch. ASCII an toàn hơn cho grounding.
    """
    text = text.lower().replace("đ", "d")
    # NFD tách dấu khỏi ký tự gốc, xóa các combining mark → còn ký tự ASCII gốc
    text = "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))
    text = text.replace(">", " ")
    words = re.findall(r"[a-z0-9]+", text)
    return "-".join(words) or "doc"


def _assign_chunk_ids(chunks: list[Chunk]) -> list[tuple[str, Chunk]]:
    """Gán chunk_id `<doc-stem>#<section-slug>#<idx>`; idx tăng theo thứ tự trong file."""
    seen: dict[str, int] = {}
    result = []
    for chunk in chunks:
        base = f"{Path(chunk.doc).stem}#{_slug(chunk.section)}"
        idx = seen.get(base, 0)
        seen[base] = idx + 1
        result.append((f"{base}#{idx}", chunk))
    return result


class IngestWorker:
    """Hàng đợi ingest chạy nền, 1 thread."""

    def __init__(self, cfg: Config, store: Store, embedder: Embedder):
        self.cfg = cfg
        self.store = store
        self.embedder = embedder
        self._queue: queue.Queue[Path] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ---------- public API ----------

    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True, name="ingest-worker")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._queue.put_nowait(None)  # type: ignore[arg-type]  # sentinel

    def enqueue(self, path: Path, source: str = "upload") -> str:
        """Đăng ký file vào bảng files và đưa vào hàng đợi. Trả về file_id."""
        fid = file_id_for(path)
        self.store.upsert_file(fid, path.name, source=source, status="queued")
        self._queue.put_nowait(path)
        return fid

    def progress(self) -> dict:
        """Tiến trình tổng hợp cho UI."""
        files = self.store.list_files()
        total = sum(f["chunks_total"] for f in files)
        done = sum(f["chunks_done"] for f in files)
        statuses = {f["status"] for f in files}
        if not files:
            status = "empty"
        elif "failed" in statuses and len(statuses) == 1:
            status = "failed"
        elif statuses <= {"ready"}:
            status = "ready"
        elif statuses & {"parsing", "chunking", "embedding", "queued"}:
            status = "processing"
        else:
            status = "partial"  # có file ready, có file lỗi
        percent = round(done * 100 / total) if total else (100 if status == "ready" else 0)
        return {
            "status": status,
            "files_total": len(files),
            "files_ready": sum(1 for f in files if f["status"] == "ready"),
            "chunks_total": total,
            "chunks_done": done,
            "percent": percent,
        }

    # ---------- worker loop ----------

    def _run(self) -> None:
        while not self._stop.is_set():
            path = self._queue.get()
            if path is None:
                break
            try:
                self._process_file(path)
            except Exception as exc:  # noqa: BLE001 — lỗi file không được giết worker
                fid = file_id_for(path)
                self.store.set_file_status(fid, "failed", error=str(exc))

    def _process_file(self, path: Path) -> None:
        fid = file_id_for(path)
        doc_name = path.name

        self.store.set_file_status(fid, "parsing")
        text = path.read_text(encoding="utf-8", errors="replace")

        self.store.set_file_status(fid, "chunking")
        if path.suffix.lower() == ".md":
            chunks = chunk_markdown(text, doc_name, self.cfg.chunk_size, self.cfg.chunk_overlap)
        else:
            chunks = chunk_plain_text(text, doc_name, self.cfg.chunk_size, self.cfg.chunk_overlap)

        if not chunks:
            raise ValueError("File không có nội dung để cắt chunk")

        # Ingest lại: xóa chunk cũ của file này trước (idempotent)
        self.store.delete_chunks_by_doc(doc_name)
        self.store.upsert_file(fid, doc_name, status="embedding", chunks_total=len(chunks))

        done = 0
        for batch_start in range(0, len(chunks), EMBED_BATCH_SIZE):
            batch = chunks[batch_start : batch_start + EMBED_BATCH_SIZE]
            vectors = self.embedder.embed([c.text for c in batch])
            for (chunk_id, chunk), vector in zip(_assign_chunk_ids(batch), vectors):
                self.store.insert_chunk(
                    chunk_id=chunk_id,
                    doc=chunk.doc,
                    section=chunk.section,
                    text=chunk.text,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    embedding=vector,
                )
            done += len(batch)
            self.store.set_file_progress(fid, done)

        self.store.set_file_status(fid, "ready")


def ingest_directory_sync(
    cfg: Config, store: Store, embedder: Embedder, directory: Path, source: str = "seed"
) -> int:
    """Ingest đồng bộ một thư mục (dùng cho CLI / seed corpus). Trả về số file."""
    worker = IngestWorker(cfg, store, embedder)
    paths = sorted(p for p in directory.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES)
    for path in paths:
        fid = worker.enqueue(path, source=source)
        try:
            worker._process_file(path)  # noqa: SLF001 — chạy đồng bộ, không qua thread
        except Exception as exc:  # noqa: BLE001
            store.set_file_status(fid, "failed", error=str(exc))
    return len(paths)

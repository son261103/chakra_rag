"""Ingest: parse file → chunk → embed → ghi vào Store, có tiến trình.

Chạy trong worker nền 1 thread (queue + thread) để:
- tránh ghi SQLite đồng thời,
- tiến trình embedding deterministic (UI đọc % qua bảng `files`).

State machine mỗi file: queued → parsing → chunking → embedding → ready | failed.
"""

from __future__ import annotations

import hashlib
import logging
import queue
import re
import threading
import time
import traceback
import unicodedata
from pathlib import Path

from chakra_rag.core.chunking import Chunk, chunk_markdown, chunk_plain_text
from chakra_rag.config import Config
from chakra_rag.core.embedding import Embedder
from chakra_rag.storage.store import Store

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 16
SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf"}


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


def _pdf_via_pdftotext(path: Path) -> str | None:
    """Ưu tiên poppler pdftotext -layout (đủ chữ hơn pypdf trên nhiều CV)."""
    import shutil
    import subprocess

    if not shutil.which("pdftotext"):
        return None
    try:
        proc = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("pdftotext failed path=%s err=%s", path.name, exc)
        return None
    if proc.returncode != 0:
        logger.warning("pdftotext rc=%s stderr=%s", proc.returncode, (proc.stderr or "")[:200])
        return None
    text = (proc.stdout or "").replace("\x0c", "\n\n").strip()
    return text or None


def _pdf_via_pypdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages: list[str] = []
    for i, page in enumerate(reader.pages, start=1):
        page_text = (page.extract_text() or "").strip()
        if page_text:
            pages.append(f"[Trang {i}]\n{page_text}")
    return "\n\n".join(pages).strip()


def extract_text(path: Path) -> str:
    """Đọc nội dung text từ .md/.txt/.pdf (PDF text-layer, không OCR)."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _pdf_via_pdftotext(path)
        source = "pdftotext"
        if not text:
            text = _pdf_via_pypdf(path)
            source = "pypdf"
        if not text:
            raise ValueError(
                "PDF không có lớp text (có thể là bản scan/ảnh). "
                "Hãy dùng PDF digital hoặc chuyển sang .md/.txt."
            )
        # Chuẩn hóa hyphen bị ngắt dòng + khoảng trắng thừa từ layout PDF
        text = re.sub(r"([A-Za-z])-\n([A-Za-z])", r"\1\2", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        logger.info("pdf extract source=%s name=%s chars=%d", source, path.name, len(text))
        return text
    return path.read_text(encoding="utf-8", errors="replace")


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
        logger.info("enqueue file_id=%s name=%s source=%s path=%s", fid, path.name, source, path)
        return fid

    def resolve_path(self, name: str, source: str | None = None) -> Path | None:
        """Tìm file trên đĩa theo tên (+ source gợi ý). Ưu tiên uploads rồi docs."""
        candidates: list[Path] = []
        if source == "seed":
            candidates = [self.cfg.docs_dir / name, self.cfg.uploads_dir / name]
        elif source == "upload":
            candidates = [self.cfg.uploads_dir / name, self.cfg.docs_dir / name]
        else:
            candidates = [self.cfg.uploads_dir / name, self.cfg.docs_dir / name]
        for p in candidates:
            if p.is_file():
                return p
        return None

    def requeue_file_id(self, file_id: str) -> dict:
        """Xếp hàng nhúng lại 1 file đã có trong bảng files. Raise ValueError nếu không được."""
        meta = self.store.get_file(file_id)
        if meta is None:
            raise ValueError(f"Không tìm thấy file_id={file_id}")
        name = meta["name"]
        source = meta.get("source") or "upload"
        path = self.resolve_path(name, source)
        if path is None:
            raise FileNotFoundError(
                f"Không thấy file trên đĩa: {name} (đã thử uploads_dir và docs_dir)"
            )
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Định dạng không hỗ trợ: {path.suffix}")
        logger.info("reingest request file_id=%s name=%s status_was=%s", file_id, name, meta.get("status"))
        new_id = self.enqueue(path, source=source)
        return {"file_id": new_id, "name": name, "status": "queued", "path": str(path)}

    def requeue_all(self) -> dict:
        """Nhúng lại mọi file còn trên đĩa trong bảng files. Bỏ qua file mất path."""
        queued: list[dict] = []
        skipped: list[dict] = []
        for meta in self.store.list_files():
            name = meta["name"]
            source = meta.get("source") or "upload"
            path = self.resolve_path(name, source)
            if path is None:
                logger.warning("reingest-all skip missing name=%s file_id=%s", name, meta["file_id"])
                skipped.append({"file_id": meta["file_id"], "name": name, "reason": "missing_on_disk"})
                continue
            fid = self.enqueue(path, source=source)
            queued.append({"file_id": fid, "name": name, "status": "queued"})
        logger.info("reingest-all queued=%d skipped=%d", len(queued), len(skipped))
        return {"queued": queued, "skipped": skipped}

    def delete_file(self, file_id: str, remove_disk: bool = True) -> dict:
        """Xóa index + (mặc định) file trên đĩa uploads/docs. Không tự ingest gì cả."""
        meta = self.store.get_file(file_id)
        if meta is None:
            raise ValueError(f"Không tìm thấy file_id={file_id}")
        name = meta["name"]
        source = meta.get("source") or "upload"
        path = self.resolve_path(name, source)
        deleted = self.store.delete_file(file_id)
        disk_removed = False
        if remove_disk and path is not None and path.is_file():
            # Chỉ xóa trong uploads_dir / docs_dir đã cấu hình — không đụng path lạ.
            allowed_roots = {self.cfg.uploads_dir.resolve(), self.cfg.docs_dir.resolve()}
            try:
                resolved = path.resolve()
                if any(resolved == root or root in resolved.parents for root in allowed_roots):
                    resolved.unlink()
                    disk_removed = True
            except OSError as exc:
                logger.warning("delete disk failed name=%s err=%s", name, exc)
        logger.info(
            "delete file_id=%s name=%s chunks_removed=%s disk_removed=%s",
            file_id,
            name,
            (deleted or {}).get("chunks_removed"),
            disk_removed,
        )
        return {
            "file_id": file_id,
            "name": name,
            "chunks_removed": (deleted or {}).get("chunks_removed", 0),
            "disk_removed": disk_removed,
        }

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
        logger.info("ingest worker started")
        while not self._stop.is_set():
            path = self._queue.get()
            if path is None:
                break
            fid = file_id_for(path)
            try:
                self._process_file(path)
            except Exception as exc:  # noqa: BLE001 — lỗi file không được giết worker
                err = f"{type(exc).__name__}: {exc}"
                logger.error(
                    "ingest FAILED file_id=%s name=%s error=%s\n%s",
                    fid,
                    getattr(path, "name", path),
                    err,
                    traceback.format_exc(),
                )
                self.store.set_file_status(fid, "failed", error=err)
        logger.info("ingest worker stopped")

    def _process_file(self, path: Path) -> None:
        fid = file_id_for(path)
        doc_name = path.name
        t0 = time.perf_counter()
        logger.info("ingest START file_id=%s name=%s suffix=%s", fid, doc_name, path.suffix.lower())

        self.store.set_file_status(fid, "parsing")
        text = extract_text(path)
        logger.info("ingest parsed file_id=%s chars=%d", fid, len(text))

        self.store.set_file_status(fid, "chunking")
        suffix = path.suffix.lower()
        # PDF/CV: chunk lớn hơn một chút + section theo heading ALL-CAPS (trong chunk_plain_text)
        if suffix == ".pdf":
            chunk_size = max(self.cfg.chunk_size, 480)
            chunk_overlap = max(self.cfg.chunk_overlap, 80)
            chunks = chunk_plain_text(text, doc_name, chunk_size, chunk_overlap)
        elif suffix == ".md":
            chunks = chunk_markdown(text, doc_name, self.cfg.chunk_size, self.cfg.chunk_overlap)
        else:
            chunks = chunk_plain_text(text, doc_name, self.cfg.chunk_size, self.cfg.chunk_overlap)

        if not chunks:
            raise ValueError("File không có nội dung để cắt chunk")

        # Gán chunk_id một lần cho cả file — không gán theo batch kẻo idx reset
        # về 0 và đụng UNIQUE (plain text / PDF thường chung 1 section).
        numbered = _assign_chunk_ids(chunks)
        logger.info("ingest chunked file_id=%s n_chunks=%d", fid, len(numbered))

        # Ingest lại: xóa chunk cũ của file này trước (idempotent)
        deleted = self.store.delete_chunks_by_doc(doc_name)
        if deleted:
            logger.info("ingest deleted old chunks file_id=%s removed=%d", fid, deleted)
        self.store.upsert_file(fid, doc_name, status="embedding", chunks_total=len(numbered))

        done = 0
        for batch_start in range(0, len(numbered), EMBED_BATCH_SIZE):
            batch = numbered[batch_start : batch_start + EMBED_BATCH_SIZE]
            vectors = self.embedder.embed([c.text for _, c in batch])
            for (chunk_id, chunk), vector in zip(batch, vectors):
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
            logger.debug(
                "ingest embed progress file_id=%s %d/%d",
                fid,
                done,
                len(numbered),
            )

        self.store.set_file_status(fid, "ready")
        ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "ingest READY file_id=%s name=%s chunks=%d latency_ms=%d",
            fid,
            doc_name,
            len(numbered),
            ms,
        )


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

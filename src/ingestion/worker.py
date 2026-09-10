"""Ingest: parse file → chunk → embed → ghi vào database (qua repository), có tiến trình.

Chạy trong worker nền 1 thread (queue + thread) để:
- quản lý ghi database tuần tự và ổn định,
- tiến trình embedding deterministic (UI đọc % qua bảng `files`).

State machine mỗi file: queued → parsing → chunking → embedding → ready | failed,
HOẶC (integration bật Batch API + provider hỗ trợ):
queued → parsing → chunking → embedding → batching → ready | failed.
Ở trạng thái 'batching' job nằm ở provider (chạy độc lập với server) — worker
poll định kỳ, restart giữa chừng không mất job (resume từ batch_meta của file).
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import re
import threading
import time
import traceback
import unicodedata
from pathlib import Path

from config import Config
from core.chunking import Chunk, chunk_markdown, chunk_plain_text
from core.embedding import Embedder, EmbeddingConfigError
from core.providers.base import BatchError
from ingestion.events import IngestEventBus
from repositories import ChunkRepository, FileRepository

logger = logging.getLogger(__name__)

# Khoảng cách poll batch job ở provider (job chạy hàng chục phút — poll dày là spam).
BATCH_POLL_INTERVAL_S = 30.0
# Timeout queue.get — cho phép worker luân phiên poll batch giữa các file.
_QUEUE_POLL_TIMEOUT_S = 2.0


def file_id_for(path: Path) -> str:
    """ID ổn định theo tên file (không theo đường dẫn) — trùng tên upsert cùng bản ghi."""
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

    def __init__(
        self,
        cfg: Config,
        file_repo: FileRepository,
        chunk_repo: ChunkRepository,
        embedder: Embedder,
    ):
        self.cfg = cfg
        self.file_repo = file_repo
        self.chunk_repo = chunk_repo
        self.embedder = embedder
        self._queue: queue.Queue[Path | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._next_batch_poll = 0.0
        # SSE /ingest/events chờ trên bus này — mỗi notify() là 1 snapshot đẩy xuống UI.
        self.events = IngestEventBus()

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
        self.file_repo.upsert_file(fid, path.name, source=source, status="queued")
        self.events.notify()
        self._queue.put_nowait(path)
        logger.info("enqueue file_id=%s name=%s source=%s path=%s", fid, path.name, source, path)
        return fid

    def resolve_path(self, name: str) -> Path | None:
        """Tìm file gốc trên đĩa trong uploads_dir theo tên."""
        p = self.cfg.uploads_dir / name
        return p if p.is_file() else None

    def requeue_file_id(self, file_id: str) -> dict:
        """Xếp hàng nhúng lại 1 file đã có trong bảng files. Raise ValueError nếu không được."""
        meta = self.file_repo.get_file(file_id)
        if meta is None:
            raise ValueError(f"Không tìm thấy file_id={file_id}")
        if meta.get("status") == "batching":
            raise ValueError(
                "File đang chờ kết quả batch job — đợi hoàn tất rồi mới nạp lại được."
            )
        name = meta["name"]
        source = meta.get("source") or "upload"
        path = self.resolve_path(name)
        if path is None:
            raise FileNotFoundError(f"Không thấy file gốc trên đĩa trong uploads_dir: {name}")
        if path.suffix.lower() not in self.cfg.supported_suffixes:
            raise ValueError(f"Định dạng không hỗ trợ: {path.suffix}")
        logger.info(
            "reingest request file_id=%s name=%s status_was=%s",
            file_id,
            name,
            meta.get("status"),
        )
        new_id = self.enqueue(path, source=source)
        return {"file_id": new_id, "name": name, "status": "queued", "path": str(path)}

    def requeue_all(self) -> dict:
        """Nhúng lại mọi file còn trên đĩa trong bảng files. Bỏ qua file mất path."""
        queued: list[dict] = []
        skipped: list[dict] = []
        for meta in self.file_repo.list_files():
            name = meta["name"]
            source = meta.get("source") or "upload"
            path = self.resolve_path(name)
            if path is None:
                logger.warning(
                    "reingest-all skip missing name=%s file_id=%s", name, meta["file_id"]
                )
                skipped.append(
                    {"file_id": meta["file_id"], "name": name, "reason": "missing_on_disk"}
                )
                continue
            fid = self.enqueue(path, source=source)
            queued.append({"file_id": fid, "name": name, "status": "queued"})
        logger.info("reingest-all queued=%d skipped=%d", len(queued), len(skipped))
        return {"queued": queued, "skipped": skipped}

    def delete_file(self, file_id: str, remove_disk: bool = True) -> dict:
        """Xóa index + (mặc định) file trên đĩa uploads. Không tự ingest gì cả."""
        meta = self.file_repo.get_file(file_id)
        if meta is None:
            raise ValueError(f"Không tìm thấy file_id={file_id}")
        name = meta["name"]
        path = self.resolve_path(name)
        deleted = self.file_repo.delete_file(file_id)
        self.events.notify()
        disk_removed = False
        if remove_disk and path is not None and path.is_file():
            # Chỉ xóa trong uploads_dir đã cấu hình — không đụng path lạ.
            root = self.cfg.uploads_dir.resolve()
            try:
                resolved = path.resolve()
                if resolved == root or root in resolved.parents:
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
        files = self.file_repo.list_files()
        total = sum(f["chunks_total"] for f in files)
        done = sum(f["chunks_done"] for f in files)
        statuses = {f["status"] for f in files}
        if not files:
            status = "empty"
        elif "failed" in statuses and len(statuses) == 1:
            status = "failed"
        elif statuses <= {"ready"}:
            status = "ready"
        elif statuses & {"parsing", "chunking", "embedding", "batching", "queued"}:
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
            self._poll_batching_files()
            try:
                path = self._queue.get(timeout=_QUEUE_POLL_TIMEOUT_S)
            except queue.Empty:
                continue
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
                self.file_repo.set_file_status(fid, "failed", error=err)
                self.events.notify()
        logger.info("ingest worker stopped")

    def _poll_batching_files(self) -> None:
        """Poll các file đang chờ batch job ở provider.

        Gọi mỗi vòng lặp nhưng chỉ gọi API thật theo BATCH_POLL_INTERVAL_S —
        job batch chạy hàng chục phút, poll dày là spam provider. Lỗi poll 1
        file (mạng chập chờn…) không được giết worker — file giữ status
        'batching', vòng sau thử lại.
        """
        batching = self.file_repo.list_batching_files()
        if not batching:
            return
        now = time.monotonic()
        if now < self._next_batch_poll:
            return
        self._next_batch_poll = now + BATCH_POLL_INTERVAL_S
        for meta in batching:
            fid = str(meta["file_id"])
            try:
                self._collect_batch_file(meta)
            except BatchError as exc:
                # Lỗi vĩnh viễn (job failed/hết hạn, thiếu kết quả, file mất trên
                # đĩa…) → đánh failed ngay để user thấy và bấm ↻, không retry vô ích.
                logger.error(
                    "batch FAILED file_id=%s job=%s: %s", fid, meta.get("batch_job_id"), exc
                )
                self.file_repo.set_file_status(fid, "failed", error=str(exc))
            except Exception as exc:  # noqa: BLE001 — lỗi tạm thời (mạng…), thử lại vòng sau
                logger.warning(
                    "batch poll failed file_id=%s job=%s: %s",
                    fid,
                    meta.get("batch_job_id"),
                    exc,
                )
        self.events.notify()

    def _collect_batch_file(self, meta: dict) -> None:
        """Kiểm tra 1 file 'batching': job xong → insert vectors; job lỗi → failed."""
        fid = str(meta["file_id"])
        job_id = str(meta.get("batch_job_id") or "")
        if not job_id or not meta.get("batch_meta"):
            raise BatchError(f"File {fid} thiếu batch_job_id/batch_meta — bấm ↻ để nạp lại.")
        batch_meta = json.loads(str(meta["batch_meta"]))
        cfg = self.embedder.resolve_batch_config(batch_meta)
        status = self.embedder.batch_status(job_id, cfg)
        logger.debug(
            "batch poll file_id=%s job=%s state=%s %d/%d",
            fid, job_id, status.state, status.completed, status.total,
        )
        if status.state in ("queued", "running", "unknown"):
            if status.completed and status.total and status.completed != meta.get("chunks_done"):
                self.file_repo.update_batch_progress(fid, status.completed)
            return
        if status.state == "cancelled":
            raise BatchError("Batch job đã bị hủy ở provider — bấm ↻ để nạp lại (không batch).")
        if status.state == "expired":
            raise BatchError("Batch job đã hết hạn ở provider — bấm ↻ để nạp lại (không batch).")
        if status.state == "failed":
            raise BatchError("Batch job thất bại ở provider — xem log chi tiết, bấm ↻ để nạp lại.")
        # state == "completed" → tải kết quả + insert
        results = self.embedder.fetch_batch_results(job_id, cfg)
        disk_path = self.resolve_path(str(meta["name"]))
        if disk_path is None:
            raise BatchError(
                f"Không thấy file gốc trên đĩa ({meta['name']}) — không thể ghép kết quả batch."
            )
        fresh_text = extract_text(disk_path)
        numbered = self._chunks_for_file(fresh_text, disk_path)
        if results.by_id:
            by_id = results.by_id
            missing = [cid for cid, _ in numbered if cid not in by_id]
            if missing:
                raise BatchError(
                    f"Batch job thiếu kết quả của {len(missing)}/{len(numbered)} chunk "
                    f"(vd {missing[0]}) — bấm ↻ để nạp lại."
                )
            vectors = [by_id[cid] for cid, _ in numbered]
        else:
            if len(results.ordered) != len(numbered):
                raise BatchError(
                    f"Batch job trả {len(results.ordered)} vector, khác số chunk "
                    f"{len(numbered)} (file có thể đã đổi nội dung giữa chừng) — "
                    "bấm ↻ để nạp lại."
                )
            vectors = results.ordered
        for (chunk_id, chunk), vector in zip(numbered, vectors, strict=False):
            self.chunk_repo.insert_chunk(
                chunk_id=chunk_id,
                doc=chunk.doc,
                section=chunk.section,
                text=chunk.text,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                embedding=vector,
            )
        self.file_repo.set_file_progress(fid, len(numbered))
        self.file_repo.set_file_status(fid, "ready")
        self.events.notify()
        logger.info(
            "batch READY file_id=%s name=%s chunks=%d job=%s",
            fid, meta["name"], len(numbered), job_id,
        )

    def _chunks_for_file(self, text: str, path: Path) -> list[tuple[str, Chunk]]:
        """Chunk file + gán chunk_id — GIỐNG HỆT mọi lần chạy (deterministic).

        Batch API chỉ trả vector theo thứ tự submit, không kèm text → khi hoàn
        tất phải ghép vector với chunk gốc. Chunking là deterministic theo nội
        dung file (không có timestamp/random) nên file chưa đổi là ra đúng bộ
        chunk cũ; file đổi nội dung giữa chừng sẽ lệch số lượng → raise tường
        minh (không insert vector sai cặp).
        """
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            chunk_size = max(self.cfg.chunk_size, 480)
            chunk_overlap = max(self.cfg.chunk_overlap, 80)
            chunks = chunk_plain_text(text, path.name, chunk_size, chunk_overlap)
        elif suffix == ".md":
            chunks = chunk_markdown(text, path.name, self.cfg.chunk_size, self.cfg.chunk_overlap)
        else:
            chunks = chunk_plain_text(text, path.name, self.cfg.chunk_size, self.cfg.chunk_overlap)
        # Gán chunk_id một lần cho cả file — không gán theo batch kẻo idx reset
        # về 0 và đụng UNIQUE (plain text / PDF thường chung 1 section).
        return _assign_chunk_ids(chunks)

    def _process_file(self, path: Path) -> None:
        fid = file_id_for(path)
        doc_name = path.name
        t0 = time.perf_counter()
        logger.info("ingest START file_id=%s name=%s suffix=%s", fid, doc_name, path.suffix.lower())

        self.file_repo.set_file_status(fid, "parsing")
        self.events.notify()
        text = extract_text(path)
        logger.info("ingest parsed file_id=%s chars=%d", fid, len(text))

        self.file_repo.set_file_status(fid, "chunking")
        self.events.notify()
        numbered = self._chunks_for_file(text, path)

        if not numbered:
            raise ValueError("File không có nội dung để cắt chunk")
        logger.info("ingest chunked file_id=%s n_chunks=%d", fid, len(numbered))

        # Ingest lại: xóa chunk cũ của file này trước (idempotent)
        deleted = self.chunk_repo.delete_chunks_by_doc(doc_name)
        if deleted:
            logger.info("ingest deleted old chunks file_id=%s removed=%d", fid, deleted)
        self.file_repo.upsert_file(fid, doc_name, status="embedding", chunks_total=len(numbered))
        self.events.notify()

        # Batch path: integration bật use_batch + provider hỗ trợ → nộp job và
        # trả ngay (worker quay lại xử lý file khác, poll định kỳ ở _run loop).
        try:
            active_cfg = self.embedder.resolve_active_config()
        except EmbeddingConfigError:
            active_cfg = None
        if active_cfg is not None and self.embedder.can_batch(active_cfg):
            self._submit_file_batch(fid, numbered, active_cfg)
            ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "ingest SUBMITTED batch file_id=%s name=%s chunks=%d latency_ms=%d",
                fid, doc_name, len(numbered), ms,
            )
            return

        done = 0
        batch_size = self.cfg.embed_batch_size
        for batch_start in range(0, len(numbered), batch_size):
            batch = numbered[batch_start : batch_start + batch_size]
            vectors = self.embedder.embed([c.text for _, c in batch], input_kind="passage")
            for (chunk_id, chunk), vector in zip(batch, vectors, strict=False):
                self.chunk_repo.insert_chunk(
                    chunk_id=chunk_id,
                    doc=chunk.doc,
                    section=chunk.section,
                    text=chunk.text,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    embedding=vector,
                )
            done += len(batch)
            self.file_repo.set_file_progress(fid, done)
            self.events.notify()
            logger.debug(
                "ingest embed progress file_id=%s %d/%d",
                fid,
                done,
                len(numbered),
            )

        self.file_repo.set_file_status(fid, "ready")
        self.events.notify()
        ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "ingest READY file_id=%s name=%s chunks=%d latency_ms=%d",
            fid,
            doc_name,
            len(numbered),
            ms,
        )

    def _submit_file_batch(
        self,
        fid: str,
        numbered: list[tuple[str, Chunk]],
        cfg,  # EmbeddingConfig — tránh import vòng, type trong core.embedding
    ) -> None:
        """Nộp toàn bộ chunks vào Batch API của provider + đánh dấu file 'batching'."""
        job_id = self.embedder.submit_batch(
            [(chunk_id, chunk.text) for chunk_id, chunk in numbered], cfg=cfg
        )
        batch_meta = json.dumps(
            {
                "integration_id": cfg.integration_id,
                "provider": cfg.provider,
                "base_url": cfg.base_url,
                "model": cfg.model,
                "dimension": cfg.dimension,
            },
            ensure_ascii=False,
        )
        self.file_repo.set_file_batch(fid, job_id, batch_meta)
        self.events.notify()
        logger.info("batch SUBMITTED file_id=%s job=%s provider=%s", fid, job_id, cfg.provider)


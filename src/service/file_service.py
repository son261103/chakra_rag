"""Service quản lý tệp tin tải lên, inspector tài liệu và tiến trình nhúng dữ liệu."""

from __future__ import annotations

import logging
from typing import Any

from config import Config, get_config
from ingestion.worker import IngestWorker, extract_text
from storage.store import Store

logger = logging.getLogger(__name__)


class FileService:
    """Nghiệp vụ lưu trữ tệp, trích xuất văn bản và điều phối IngestWorker."""

    def __init__(
        self,
        store: Store,
        worker: IngestWorker | None = None,
        cfg: Config | None = None,
    ):
        self.store = store
        self.worker = worker
        self.cfg = cfg or get_config()

    def upload_file(self, filename: str, content: bytes) -> dict[str, Any]:
        """Lưu file tải lên vào thư mục uploads_dir và đưa vào hàng đợi ingest."""
        if not self.worker:
            raise RuntimeError("IngestWorker chưa được khởi tạo trong FileService")
        dest = self.cfg.uploads_dir / filename
        dest.write_bytes(content)
        file_id = self.worker.enqueue(dest, source="upload")
        logger.info("upload accepted file_id=%s name=%s bytes=%d", file_id, filename, len(content))
        return {"file_id": file_id, "name": filename, "status": "queued"}

    def list_files(self) -> list[dict[str, Any]]:
        """Lấy danh sách tệp tin cùng trạng thái ingest từ database."""
        return self.store.list_files()

    def inspect_file(self, file_id: str) -> dict[str, Any] | None:
        """Xem dữ liệu chunks đã index cùng full text gốc trên đĩa."""
        meta = self.store.get_file(file_id)
        if meta is None:
            return None

        chunks = self.store.list_chunks_by_doc(meta["name"])
        full_text = ""
        full_text_error = None

        path = self.worker.resolve_path(meta["name"], meta.get("source")) if self.worker else None
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
                logger.warning(
                    "inspect extract failed (unexpected) file_id=%s", file_id, exc_info=True
                )

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

    def reingest_file(self, file_id: str) -> dict[str, Any]:
        """Đưa một file vào hàng đợi nhúng lại (parse → chunk → embed)."""
        if not self.worker:
            raise RuntimeError("IngestWorker chưa được khởi tạo trong FileService")
        return self.worker.requeue_file_id(file_id)

    def reingest_all(self) -> dict[str, Any]:
        """Nhúng lại toàn bộ các file còn tồn tại trên đĩa."""
        if not self.worker:
            raise RuntimeError("IngestWorker chưa được khởi tạo trong FileService")
        result = self.worker.requeue_all()
        logger.info(
            "reingest-all service queued=%d skipped=%d",
            len(result["queued"]),
            len(result["skipped"]),
        )
        return result

    def delete_file(self, file_id: str, remove_disk: bool = True) -> dict[str, Any]:
        """Xóa file khỏi database index và tùy chọn xóa khỏi đĩa."""
        if not self.worker:
            raise RuntimeError("IngestWorker chưa được khởi tạo trong FileService")
        return self.worker.delete_file(file_id, remove_disk=remove_disk)

    def get_progress(self) -> dict[str, Any]:
        """Lấy thông tin tiến trình tổng thể của worker embedding."""
        if not self.worker:
            return {"status": "ready", "percent": 100, "chunks_done": 0, "chunks_total": 0}
        return self.worker.progress()

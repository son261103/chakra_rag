"""Service quản lý cấu hình tích hợp embedding (API OpenAI-compatible /embeddings).

Mirror `integration_service.py` (LLM) — nhưng KHÔNG seed tích hợp mặc định và
KHÔNG có fallback env: người dùng phải tự thêm integration trong Settings UI.
Hai đặc thù embedding:
- `dimension`: số chiều vector khai báo cho provider.
- Đổi chiều = index cũ không dùng được: khi activate/update config có chiều khác
  chiều cột `chunks.embedding` hiện tại → nếu còn chunk thì raise
  `EmbeddingDimensionConflict` (route trả 409, UI xác nhận, gửi lại force=true);
  force hoặc index trống → reset index (truncate + ALTER TYPE + đánh dấu mọi
  file 'cần nạp lại' — user tự bấm ↻, không auto-reingest).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from config import Config, get_config
from core.security import decrypt_integration_key, encrypt_integration_key, mask_api_key
from observability.timing import elapsed_ms, timed
from repositories import ChunkRepository, EmbeddingIntegrationRepository, FileRepository

logger = logging.getLogger(__name__)


class EmbeddingDimensionConflict(Exception):
    """Chiều của config khác chiều index hiện tại và index còn chunk — cần user xác nhận."""

    def __init__(self, current_dimension: int, new_dimension: int):
        self.current_dimension = current_dimension
        self.new_dimension = new_dimension
        super().__init__(
            f"Đổi chiều vector: index hiện tại {current_dimension} chiều, "
            f"model mới {new_dimension} chiều"
        )


class EmbeddingIntegrationService:
    """Nghiệp vụ quản lý tích hợp embedding, bảo mật khóa và đồng bộ chiều index."""

    def __init__(
        self,
        repo: EmbeddingIntegrationRepository,
        cfg: Config | None = None,
        chunk_repo: ChunkRepository | None = None,
        file_repo: FileRepository | None = None,
        on_change: Callable[[], None] | None = None,
    ):
        self.repo = repo
        self.cfg = cfg or get_config()
        self.chunk_repo = chunk_repo
        self.file_repo = file_repo
        self.on_change = on_change

    # ---------- format ----------

    def format_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Format 1 record từ DB ra payload an toàn (giải mã rồi che API key, kèm dimension)."""
        raw_key = ""
        try:
            raw_key = decrypt_integration_key(
                item.get("encrypted_api_key", ""),
                item.get("encrypted_dek", ""),
                self.cfg.encryption_key,
            )
        except Exception:
            raw_key = ""

        return {
            "id": item["id"],
            "name": item["name"],
            "provider": item.get("provider", "openai"),
            "base_url": item["base_url"],
            "model": item["model"],
            "dimension": int(item["dimension"]),
            "masked_api_key": mask_api_key(raw_key),
            "has_api_key": bool(raw_key),
            "is_active": bool(item.get("is_active", 0)),
            "created_at": item.get("created_at", ""),
            "updated_at": item.get("updated_at", ""),
        }

    def list_integrations(self) -> list[dict[str, Any]]:
        rows = self.repo.list_integrations()
        return [self.format_item(r) for r in rows]

    def get_active_integration_info(self) -> dict[str, Any] | None:
        """Integration active — None khi chưa cấu hình (không có row env giả lập)."""
        active = self.repo.get_active_integration()
        return self.format_item(active) if active else None

    # ---------- đồng bộ chiều index ----------

    def _check_dimension(self, dimension: int, force: bool) -> None:
        """Đảm bảo index khớp chiều `dimension` trước khi config này trở thành active.

        - Chiều bằng cột hiện tại (hoặc chưa đọc được) → không làm gì.
        - Index còn chunk và chưa force → raise conflict (UI xác nhận).
        - Index trống, hoặc force → reset index (truncate + ALTER + đánh dấu file stale).
        """
        if self.chunk_repo is None:
            return
        current = self.chunk_repo.vector_dimension()
        if current is None or current == dimension:
            return
        if self.chunk_repo.count_chunks() > 0 and not force:
            raise EmbeddingDimensionConflict(current, dimension)
        self._reset_index(dimension)

    def _reset_index(self, dimension: int) -> None:
        """Xóa toàn bộ vector cũ (không dùng được với chiều mới) + ALTER cột + mark file stale."""
        if self.chunk_repo is None:
            return
        self.chunk_repo.migrate_dimension(dimension)
        if self.file_repo is not None:
            self.file_repo.mark_all_stale("Đổi chiều vector — cần nạp lại file (bấm ↻)")
        logger.warning("Đã reset index vector sang chiều %d (mọi file cần reingest)", dimension)
        if self.on_change:
            self.on_change()

    def reconcile_index_dimension(self) -> None:
        """Đối chiếu chiều index lúc khởi động.

        DB cũ (vd MiniLM 384) có thể còn bảng `chunks` ở chiều khác với integration
        active mới. Index TRỐNG → migrate âm thầm (không mất gì); index CÒN chunk →
        chỉ log cảnh báo, KHÔNG tự xóa (user phải xác nhận force qua UI).
        """
        if self.chunk_repo is None:
            return
        active = self.repo.get_active_integration()
        if not active:
            return
        target = int(active["dimension"])
        current = self.chunk_repo.vector_dimension()
        if current is None or current == target:
            return
        if self.chunk_repo.count_chunks() == 0:
            logger.info("Reconcile chiều index trống %d → %d", current, target)
            self._reset_index(target)
        else:
            logger.warning(
                "Chiều index (%d) khác integration active (%d) và còn chunk — "
                "vào Cài đặt → Embedding kích hoạt lại config để reset (cần nạp lại file).",
                current,
                target,
            )

    # ---------- CRUD ----------

    def create_integration(
        self,
        name: str,
        model: str,
        dimension: int,
        base_url: str,
        provider: str = "openai",
        api_key: str = "",
        is_active: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        will_be_active = is_active or self.repo.count_integrations() == 0
        if will_be_active:
            self._check_dimension(int(dimension), force)
        enc = encrypt_integration_key(api_key, self.cfg.encryption_key)
        created = self.repo.create_integration(
            name=name,
            model=model,
            dimension=int(dimension),
            base_url=base_url,
            provider=provider,
            encrypted_api_key=enc.encrypted_api_key,
            encrypted_dek=enc.encrypted_dek,
            is_active=is_active,
        )
        if self.on_change:
            self.on_change()
        return self.format_item(created)

    def update_integration(
        self,
        integration_id: str,
        name: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
        base_url: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        is_active: bool | None = None,
        force: bool = False,
    ) -> dict[str, Any] | None:
        row = self.repo.get_integration(integration_id)
        if row is None:
            return None
        # Chỉ kiểm chiều khi row này đang/sẽ là active (thay đổi có ảnh hưởng index).
        still_active = is_active is not False and bool(row.get("is_active"))
        is_or_will_be_active = bool(is_active) or still_active
        if is_or_will_be_active and dimension is not None:
            self._check_dimension(int(dimension), force)

        enc_key: str | None = None
        enc_dek: str | None = None
        if api_key is not None:
            enc = encrypt_integration_key(api_key, self.cfg.encryption_key)
            enc_key = enc.encrypted_api_key
            enc_dek = enc.encrypted_dek

        updated = self.repo.update_integration(
            integration_id=integration_id,
            name=name,
            model=model,
            dimension=dimension,
            base_url=base_url,
            provider=provider,
            encrypted_api_key=enc_key,
            encrypted_dek=enc_dek,
            is_active=is_active,
        )
        if not updated:
            return None
        if self.on_change:
            self.on_change()
        return self.format_item(updated)

    def delete_integration(self, integration_id: str, force: bool = False) -> bool:
        row = self.repo.get_integration(integration_id)
        if row is None:
            return False
        # Xóa row active → repo tự promote row updated_at mới nhất; chiều của nó
        # có thể khác index → kiểm tra TRƯỚC khi xóa để còn raise conflict được.
        if bool(row.get("is_active")):
            remaining = [r for r in self.repo.list_integrations() if r["id"] != integration_id]
            if remaining:
                fallback_dim = int(remaining[0]["dimension"])
                self._check_dimension(fallback_dim, force)
        deleted = self.repo.delete_integration(integration_id)
        if deleted and self.on_change:
            self.on_change()
        return deleted

    def activate_integration(
        self,
        integration_id: str,
        force: bool = False,
    ) -> dict[str, Any] | None:
        row = self.repo.get_integration(integration_id)
        if row is None:
            return None
        self._check_dimension(int(row["dimension"]), force)
        activated = self.repo.set_active_integration(integration_id)
        if not activated:
            return None
        if self.on_change:
            self.on_change()
        return self.format_item(activated)

    # ---------- test kết nối ----------

    def test_connection(
        self,
        model: str,
        base_url: str,
        dimension: int | None = None,
        api_key: str | None = None,
        integration_id: str | None = None,
    ) -> dict[str, Any]:
        """Gọi thật /embeddings với 1 text ngắn — trả chiều thực tế để bắt lỗi khai sai chiều."""
        from langchain_openai import OpenAIEmbeddings

        resolved_key = api_key
        if not resolved_key and integration_id:
            item = self.repo.get_integration(integration_id)
            if item:
                resolved_key = decrypt_integration_key(
                    item.get("encrypted_api_key", ""),
                    item.get("encrypted_dek", ""),
                    self.cfg.encryption_key,
                )

        start = timed()
        embeddings = OpenAIEmbeddings(
            model=model.strip(),
            openai_api_key=resolved_key.strip() if resolved_key else "not-needed",
            openai_api_base=base_url.strip(),
            check_embedding_ctx_length=False,
            timeout=min(self.cfg.llm_timeout, 20.0),
            max_retries=1,
        )
        vectors = embeddings.embed_documents(["Hi"])
        ms = elapsed_ms(start)
        actual_dim = len(vectors[0]) if vectors else 0
        result: dict[str, Any] = {
            "ok": True,
            "model": model,
            "dimension": actual_dim,
            "latency_ms": ms,
        }
        if dimension and actual_dim and int(dimension) != actual_dim:
            result["dimension_mismatch"] = True
        return result

"""Service quản lý các cấu hình tích hợp LLM (OpenAI-compatible).

Đảm nhiệm:
- Khởi tạo tích hợp mặc định nếu DB trống
- Quản lý danh sách tích hợp (mã hóa DEK/KEK và che API key)
- Lấy thông tin tích hợp đang kích hoạt
- Thêm / sửa / xóa / kích hoạt tích hợp
- Kiểm tra kết nối tới LLM provider
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from config import Config, get_config
from core.security import decrypt_integration_key, encrypt_integration_key, mask_api_key
from observability.timing import elapsed_ms, timed
from storage.store import Store

logger = logging.getLogger(__name__)


class IntegrationService:
    """Nghiệp vụ quản lý tích hợp LLM & bảo mật khóa."""

    def __init__(
        self,
        store: Store,
        cfg: Config | None = None,
        on_change: Callable[[], None] | None = None,
    ):
        self.store = store
        self.cfg = cfg or get_config()
        self.on_change = on_change

    def ensure_default_integration(self) -> None:
        """Nếu DB chưa có tích hợp nào, khởi tạo cấu hình mặc định vào database."""
        try:
            if self.store.count_integrations() == 0:
                model_name = self.cfg.llm_model or "gpt-4o-mini"
                base_url = self.cfg.llm_base_url or "https://api.openai.com/v1"
                enc = encrypt_integration_key(self.cfg.llm_api_key, self.cfg.encryption_key)
                self.store.create_integration(
                    name="OpenAI (Mặc định)",
                    model=model_name,
                    base_url=base_url,
                    provider="openai",
                    encrypted_api_key=enc.encrypted_api_key,
                    encrypted_dek=enc.encrypted_dek,
                    is_active=True,
                )
                logger.info("Đã khởi tạo tích hợp LLM mặc định vào database.")
        except Exception:
            logger.exception("Lỗi khi tạo tích hợp mặc định (bỏ qua)")

    def format_item(self, item: dict[str, Any]) -> dict[str, Any]:
        """Format 1 record từ DB ra payload an toàn (giải mã rồi che API key)."""
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
            "masked_api_key": mask_api_key(raw_key),
            "has_api_key": bool(raw_key),
            "is_active": bool(item.get("is_active", 0)),
            "created_at": item.get("created_at", ""),
            "updated_at": item.get("updated_at", ""),
        }

    def list_integrations(self) -> list[dict[str, Any]]:
        rows = self.store.list_integrations()
        return [self.format_item(r) for r in rows]

    def get_active_integration_info(self) -> dict[str, Any]:
        active = self.store.get_active_integration()
        if not active:
            return {
                "id": "env-fallback",
                "name": "Môi trường (.env)",
                "provider": "openai",
                "base_url": self.cfg.llm_base_url,
                "model": self.cfg.llm_model,
                "masked_api_key": mask_api_key(self.cfg.llm_api_key),
                "has_api_key": bool(self.cfg.llm_api_key),
                "is_active": True,
            }
        return self.format_item(active)

    def create_integration(
        self,
        name: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        provider: str = "openai",
        api_key: str = "",
        is_active: bool = False,
    ) -> dict[str, Any]:
        enc = encrypt_integration_key(api_key, self.cfg.encryption_key)
        created = self.store.create_integration(
            name=name,
            model=model,
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
        base_url: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any] | None:
        enc_key: str | None = None
        enc_dek: str | None = None
        if api_key is not None:
            enc = encrypt_integration_key(api_key, self.cfg.encryption_key)
            enc_key = enc.encrypted_api_key
            enc_dek = enc.encrypted_dek

        updated = self.store.update_integration(
            integration_id=integration_id,
            name=name,
            model=model,
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

    def delete_integration(self, integration_id: str) -> bool:
        deleted = self.store.delete_integration(integration_id)
        if deleted and self.on_change:
            self.on_change()
        return deleted

    def activate_integration(self, integration_id: str) -> dict[str, Any] | None:
        activated = self.store.set_active_integration(integration_id)
        if not activated:
            return None
        if self.on_change:
            self.on_change()
        return self.format_item(activated)

    def test_connection(
        self,
        model: str,
        base_url: str,
        api_key: str | None = None,
        integration_id: str | None = None,
    ) -> dict[str, Any]:
        from agent.llm import ThinkingChatOpenAI

        resolved_key = api_key
        if not resolved_key and integration_id:
            item = self.store.get_integration(integration_id)
            if item:
                resolved_key = decrypt_integration_key(
                    item.get("encrypted_api_key", ""),
                    item.get("encrypted_dek", ""),
                    self.cfg.encryption_key,
                )

        start = timed()
        llm = ThinkingChatOpenAI(
            model=model.strip(),
            base_url=base_url.strip(),
            api_key=resolved_key.strip() if resolved_key else "not-needed",
            temperature=0,
            timeout=min(self.cfg.llm_timeout, 20.0),
            max_retries=1,
            max_tokens=16,
        )
        resp = llm.invoke("Hi")
        ms = elapsed_ms(start)
        return {
            "ok": True,
            "model": model,
            "response": str(resp.content).strip()[:100],
            "latency_ms": ms,
        }

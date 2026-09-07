"""Truy vấn bảng `llm_integrations`: cấu hình LLM provider (API key mã hóa).

DDL tương ứng nằm ở storage/schema.py. Mã hóa/giải mã key KHÔNG nằm ở đây —
repository chỉ lưu/đọc chuỗi đã mã hóa; nghiệp vụ xử lý key ở service tầng trên.
"""

from __future__ import annotations

from typing import Any

from repositories.common import new_id, utcnow_iso
from storage.connection import Database


class IntegrationRepository:
    """Truy vấn cấu hình LLM integration trên một `Database`."""

    def __init__(self, db: Database):
        self.db = db

    def create_integration(
        self,
        name: str,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        provider: str = "openai",
        encrypted_api_key: str = "",
        encrypted_dek: str = "",
        is_active: bool = False,
        integration_id: str | None = None,
    ) -> dict[str, Any]:
        iid = integration_id or new_id()
        now = utcnow_iso()
        with self.db.lock:
            count = self.db.conn.execute(
                "SELECT COUNT(*) FROM llm_integrations"
            ).fetchone()[0]
            should_activate = is_active or (count == 0)
            if should_activate:
                self.db.conn.execute("UPDATE llm_integrations SET is_active = 0")
            self.db.conn.execute(
                """
                INSERT INTO llm_integrations (
                    id, name, provider, base_url, model,
                    encrypted_api_key, encrypted_dek, is_active,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iid,
                    name.strip(),
                    provider.strip() or "openai",
                    base_url.strip() or "https://api.openai.com/v1",
                    model.strip(),
                    encrypted_api_key,
                    encrypted_dek,
                    1 if should_activate else 0,
                    now,
                    now,
                ),
            )
            self.db.conn.commit()
        return self.get_integration(iid)  # type: ignore[return-value]

    def update_integration(
        self,
        integration_id: str,
        name: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        provider: str | None = None,
        encrypted_api_key: str | None = None,
        encrypted_dek: str | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any] | None:
        now = utcnow_iso()
        with self.db.lock:
            existing = self.db.conn.execute(
                "SELECT * FROM llm_integrations WHERE id = ?", (integration_id,)
            ).fetchone()
            if existing is None:
                return None

            updates: list[str] = ["updated_at = ?"]
            params: list[Any] = [now]

            if name is not None:
                updates.append("name = ?")
                params.append(name.strip())
            if model is not None:
                updates.append("model = ?")
                params.append(model.strip())
            if base_url is not None:
                updates.append("base_url = ?")
                params.append(base_url.strip())
            if provider is not None:
                updates.append("provider = ?")
                params.append(provider.strip())
            if encrypted_api_key is not None:
                updates.append("encrypted_api_key = ?")
                params.append(encrypted_api_key)
            if encrypted_dek is not None:
                updates.append("encrypted_dek = ?")
                params.append(encrypted_dek)
            if is_active is not None:
                if is_active:
                    self.db.conn.execute("UPDATE llm_integrations SET is_active = 0")
                updates.append("is_active = ?")
                params.append(1 if is_active else 0)

            params.append(integration_id)
            self.db.conn.execute(
                f"UPDATE llm_integrations SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            self.db.conn.commit()
        return self.get_integration(integration_id)

    def delete_integration(self, integration_id: str) -> bool:
        with self.db.lock:
            existing = self.db.conn.execute(
                "SELECT is_active FROM llm_integrations WHERE id = ?", (integration_id,)
            ).fetchone()
            if existing is None:
                return False
            was_active = bool(existing["is_active"])
            self.db.conn.execute("DELETE FROM llm_integrations WHERE id = ?", (integration_id,))
            if was_active:
                fallback = self.db.conn.execute(
                    "SELECT id FROM llm_integrations ORDER BY updated_at DESC LIMIT 1"
                ).fetchone()
                if fallback:
                    self.db.conn.execute(
                        "UPDATE llm_integrations SET is_active = 1 WHERE id = ?",
                        (fallback["id"],),
                    )
            self.db.conn.commit()
            return True

    def get_integration(self, integration_id: str) -> dict[str, Any] | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT * FROM llm_integrations WHERE id = ?", (integration_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_integrations(self) -> list[dict[str, Any]]:
        with self.db.lock:
            rows = self.db.conn.execute(
                """
                SELECT id, name, provider, base_url, model,
                       encrypted_api_key, encrypted_dek, is_active,
                       created_at, updated_at
                FROM llm_integrations
                ORDER BY is_active DESC, updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_active_integration(self) -> dict[str, Any] | None:
        with self.db.lock:
            row = self.db.conn.execute(
                "SELECT * FROM llm_integrations WHERE is_active = 1 LIMIT 1"
            ).fetchone()
            if row:
                return dict(row)
            first = self.db.conn.execute(
                "SELECT id FROM llm_integrations ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if first:
                self.db.conn.execute(
                    "UPDATE llm_integrations SET is_active = 1 WHERE id = ?", (first["id"],)
                )
                self.db.conn.commit()
                row = self.db.conn.execute(
                    "SELECT * FROM llm_integrations WHERE id = ?", (first["id"],)
                ).fetchone()
                return dict(row) if row else None
        return None

    def set_active_integration(self, integration_id: str) -> dict[str, Any] | None:
        with self.db.lock:
            existing = self.db.conn.execute(
                "SELECT id FROM llm_integrations WHERE id = ?", (integration_id,)
            ).fetchone()
            if not existing:
                return None
            self.db.conn.execute("UPDATE llm_integrations SET is_active = 0")
            self.db.conn.execute(
                "UPDATE llm_integrations SET is_active = 1, updated_at = ? WHERE id = ?",
                (utcnow_iso(), integration_id),
            )
            self.db.conn.commit()
        return self.get_integration(integration_id)

    def count_integrations(self) -> int:
        with self.db.lock:
            return self.db.conn.execute("SELECT COUNT(*) FROM llm_integrations").fetchone()[0]

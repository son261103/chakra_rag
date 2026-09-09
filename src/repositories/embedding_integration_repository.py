"""Truy vấn bảng `embedding_integrations`: cấu hình embedding provider (API key mã hóa + chiều).

SQLAlchemy Core; bảng reflect từ DB (schema.py là nguồn DDL duy nhất).
Mã hóa/giải mã key KHÔNG nằm ở đây — repository chỉ lưu/đọc chuỗi đã mã hóa;
nghiệp vụ xử lý key + dimension ở service tầng trên.

Mirror `integration_repository.py` (LLM), thêm cột `dimension` (số chiều vector).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData, Table, delete, func, insert, select, update

from repositories.common import new_id, utcnow_iso
from storage.connection import Database


class EmbeddingIntegrationRepository:
    """Truy vấn cấu hình embedding integration trên một `Database`."""

    def __init__(self, db: Database):
        self.db = db
        meta = MetaData()
        self.embedding_integrations = Table(
            "embedding_integrations", meta, autoload_with=db.engine
        )

    def create_integration(
        self,
        name: str,
        model: str,
        dimension: int,
        base_url: str,
        provider: str = "openai",
        encrypted_api_key: str = "",
        encrypted_dek: str = "",
        is_active: bool = False,
        integration_id: str | None = None,
    ) -> dict[str, Any]:
        iid = integration_id or new_id()
        now = utcnow_iso()
        with self.db.engine.begin() as conn:
            count = conn.scalar(
                select(func.count()).select_from(self.embedding_integrations)
            )
            should_activate = is_active or (count == 0)
            if should_activate:
                conn.execute(update(self.embedding_integrations).values(is_active=0))
            conn.execute(
                insert(self.embedding_integrations).values(
                    id=iid,
                    name=name.strip(),
                    provider=provider.strip() or "openai",
                    base_url=base_url.strip(),
                    model=model.strip(),
                    dimension=int(dimension),
                    encrypted_api_key=encrypted_api_key,
                    encrypted_dek=encrypted_dek,
                    is_active=should_activate,
                    created_at=now,
                    updated_at=now,
                )
            )
        return self.get_integration(iid)  # type: ignore[return-value]

    def update_integration(
        self,
        integration_id: str,
        name: str | None = None,
        model: str | None = None,
        dimension: int | None = None,
        base_url: str | None = None,
        provider: str | None = None,
        encrypted_api_key: str | None = None,
        encrypted_dek: str | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any] | None:
        now = utcnow_iso()
        values: dict[str, Any] = {"updated_at": now}
        if name is not None:
            values["name"] = name.strip()
        if model is not None:
            values["model"] = model.strip()
        if dimension is not None:
            values["dimension"] = int(dimension)
        if base_url is not None:
            values["base_url"] = base_url.strip()
        if provider is not None:
            values["provider"] = provider.strip()
        if encrypted_api_key is not None:
            values["encrypted_api_key"] = encrypted_api_key
        if encrypted_dek is not None:
            values["encrypted_dek"] = encrypted_dek
        if is_active is not None:
            values["is_active"] = is_active

        with self.db.engine.begin() as conn:
            existing = conn.execute(
                select(self.embedding_integrations).where(
                    self.embedding_integrations.c.id == integration_id
                )
            ).mappings().first()
            if existing is None:
                return None
            if is_active:
                # Kích hoạt integration này → tắt mọi integration khác.
                conn.execute(update(self.embedding_integrations).values(is_active=0))
            conn.execute(
                update(self.embedding_integrations)
                .where(self.embedding_integrations.c.id == integration_id)
                .values(**values)
            )
        return self.get_integration(integration_id)

    def delete_integration(self, integration_id: str) -> bool:
        with self.db.engine.begin() as conn:
            existing = conn.execute(
                select(self.embedding_integrations.c.is_active).where(
                    self.embedding_integrations.c.id == integration_id
                )
            ).mappings().first()
            if existing is None:
                return False
            was_active = bool(existing["is_active"])
            conn.execute(
                delete(self.embedding_integrations).where(
                    self.embedding_integrations.c.id == integration_id
                )
            )
            if was_active:
                fallback = conn.execute(
                    select(self.embedding_integrations.c.id)
                    .order_by(self.embedding_integrations.c.updated_at.desc())
                    .limit(1)
                ).mappings().first()
                if fallback:
                    conn.execute(
                        update(self.embedding_integrations)
                        .where(self.embedding_integrations.c.id == fallback["id"])
                        .values(is_active=1)
                    )
        return True

    def get_integration(self, integration_id: str) -> dict[str, Any] | None:
        with self.db.engine.connect() as conn:
            row = conn.execute(
                select(self.embedding_integrations).where(
                    self.embedding_integrations.c.id == integration_id
                )
            ).mappings().first()
        return dict(row) if row else None

    def list_integrations(self) -> list[dict[str, Any]]:
        stmt = select(self.embedding_integrations).order_by(
            self.embedding_integrations.c.is_active.desc(),
            self.embedding_integrations.c.updated_at.desc(),
        )
        with self.db.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def get_active_integration(self) -> dict[str, Any] | None:
        """Integration đang active; nếu chưa có thì tự kích hoạt bản mới nhất."""
        with self.db.engine.begin() as conn:
            row = conn.execute(
                select(self.embedding_integrations)
                .where(self.embedding_integrations.c.is_active == 1)
                .limit(1)
            ).mappings().first()
            if row:
                return dict(row)
            first = conn.execute(
                select(self.embedding_integrations.c.id)
                .order_by(self.embedding_integrations.c.updated_at.desc())
                .limit(1)
            ).mappings().first()
            if first:
                conn.execute(
                    update(self.embedding_integrations)
                    .where(self.embedding_integrations.c.id == first["id"])
                    .values(is_active=1)
                )
                row = conn.execute(
                    select(self.embedding_integrations).where(
                        self.embedding_integrations.c.id == first["id"]
                    )
                ).mappings().first()
                return dict(row) if row else None
        return None

    def set_active_integration(self, integration_id: str) -> dict[str, Any] | None:
        with self.db.engine.begin() as conn:
            existing = conn.execute(
                select(self.embedding_integrations.c.id).where(
                    self.embedding_integrations.c.id == integration_id
                )
            ).mappings().first()
            if not existing:
                return None
            conn.execute(update(self.embedding_integrations).values(is_active=0))
            conn.execute(
                update(self.embedding_integrations)
                .where(self.embedding_integrations.c.id == integration_id)
                .values(is_active=1, updated_at=utcnow_iso())
            )
        return self.get_integration(integration_id)

    def count_integrations(self) -> int:
        with self.db.engine.connect() as conn:
            return conn.scalar(
                select(func.count()).select_from(self.embedding_integrations)
            )

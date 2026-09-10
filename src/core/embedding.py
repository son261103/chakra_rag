"""Embedding qua API — route qua provider adapter (src/core/providers/).

Model KHÔNG chạy local trong RAM: mỗi tích hợp là một row trong bảng
`embedding_integrations` (provider + base URL + model + API key mã hóa
DEK/KEK + số chiều + cờ use_batch), quản lý qua Settings UI.

KHÔNG có fallback env cho credential: chưa cấu hình integration → raise
`EmbeddingConfigError` với thông báo rõ ràng. Mỗi lần nhúng resolve tích hợp
active, cache client theo fingerprint `(base_url, model, api_key, provider)` —
đổi tích hợp không cần restart server.

Hành vi khác nhau giữa các nhà (tham số request, Batch API) nằm hết ở adapter;
lớp này chỉ: resolve config → gọi adapter → validate chiều → L2-normalize.
Vector được chuẩn hóa L2 thủ công bằng numpy trước khi trả về ⇒ khoảng cách L2
trong pgvector tương đương cosine (<->), công thức score `1 - d/2` và index
HNSW `vector_l2_ops` giữ nguyên hợp lệ.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import replace
from typing import Any

import numpy as np

from config import Config
from core.providers import get_adapter
from core.providers.base import (
    BatchError,
    BatchResults,
    BatchStatus,
    EmbeddingConfig,
    InputKind,
)
from core.security import decrypt_integration_key

logger = logging.getLogger(__name__)


class EmbeddingConfigError(RuntimeError):
    """Chưa cấu hình embedding integration, provider lạ, hoặc chiều trả về khác khai báo."""


_NOT_CONFIGURED = "Chưa cấu hình model embedding — thêm tích hợp trong Cài đặt (tab Embedding)."

# Số client giữ lại cùng lúc (sync query + batch poll dùng config khác nhau).
_MAX_CACHED_CLIENTS = 4


class Embedder:
    """Facade embedding: resolve tích hợp active → adapter → validate + normalize."""

    def __init__(self, cfg: Config, integration_repo: Any):
        self.cfg = cfg
        self.integration_repo = integration_repo
        self._clients: OrderedDict[tuple[str, str, str, str], Any] = OrderedDict()

    # ---------- resolve cấu hình ----------

    def resolve_active_config(self) -> EmbeddingConfig:
        """Cấu hình (đã giải mã key) của embedding integration đang active.

        Không có row nào đang active → raise (không fallback env).
        """
        row = (
            self.integration_repo.get_active_integration()
            if self.integration_repo is not None
            else None
        )
        if not row:
            raise EmbeddingConfigError(_NOT_CONFIGURED)
        return self._config_from_row(row)

    def resolve_batch_config(self, meta: dict[str, Any]) -> EmbeddingConfig:
        """Cấu hình để poll/tải kết quả batch job đã submit trước đó.

        Batch job chạy bất đồng bộ (restart server giữa chừng là chuyện bình
        thường) nên poll phải dựng lại config từ `batch_meta` của file: dùng
        đúng provider/base_url/model/dimension lúc submit, nhưng key giải mã
        tươi từ integration row (KHÔNG lưu key plaintext trong batch_meta).
        """
        integration_id = str(meta.get("integration_id") or "")
        row = (
            self.integration_repo.get_integration(integration_id)
            if integration_id and self.integration_repo is not None
            else None
        )
        if row is None:
            raise EmbeddingConfigError(
                "Tích hợp embedding dùng cho batch job này đã bị xóa — "
                "không thể tải kết quả. Bấm ↻ để nạp lại file."
            )
        cfg = self._config_from_row(row)
        try:
            cfg = replace(
                cfg,
                provider=str(meta["provider"]),
                base_url=str(meta["base_url"]),
                model=str(meta["model"]),
                dimension=int(meta["dimension"]),
                use_batch=True,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingConfigError(
                f"batch_meta của file không đọc được: {exc}"
            ) from exc
        return cfg

    def _config_from_row(self, row: dict[str, Any]) -> EmbeddingConfig:
        base_url = (row.get("base_url") or "").strip()
        model = (row.get("model") or "").strip()
        try:
            dimension = int(row["dimension"])
        except (KeyError, TypeError, ValueError):
            dimension = 0
        provider = (row.get("provider") or "").strip()
        if not base_url or not model or dimension <= 0:
            raise EmbeddingConfigError(
                "Tích hợp embedding thiếu base_url/model/dimension — kiểm tra lại trong "
                "Cài đặt (tab Embedding)."
            )
        try:
            get_adapter(provider)
        except ValueError as exc:
            raise EmbeddingConfigError(
                f"{exc} — sửa 'Nhà cung cấp' của tích hợp trong Cài đặt (tab Embedding)."
            ) from exc
        api_key = decrypt_integration_key(
            row.get("encrypted_api_key", ""),
            row.get("encrypted_dek", ""),
            self.cfg.encryption_key,
        )
        return EmbeddingConfig(
            integration_id=str(row.get("id", "")),
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
            dimension=dimension,
            use_batch=bool(row.get("use_batch", 0)),
        )

    @property
    def dim(self) -> int:
        """Số chiều vector — lấy từ khai báo của tích hợp active, không gọi API."""
        return self.resolve_active_config().dimension

    def invalidate(self) -> None:
        """Hủy cache client — lần gọi sau sẽ resolve lại integration active."""
        self._clients.clear()

    # ---------- client cache ----------

    def _client_for(self, cfg: EmbeddingConfig) -> Any:
        fingerprint = (cfg.base_url, cfg.model, cfg.api_key, cfg.provider)
        client = self._clients.get(fingerprint)
        if client is None:
            adapter = get_adapter(cfg.provider)
            client = adapter.build_client(cfg, timeout=min(self.cfg.llm_timeout, 60.0))
            self._clients[fingerprint] = client
            while len(self._clients) > _MAX_CACHED_CLIENTS:
                self._clients.popitem(last=False)
        else:
            self._clients.move_to_end(fingerprint)
        return client

    # ---------- embedding đồng bộ ----------

    def embed(
        self,
        texts: list[str],
        input_kind: InputKind = "passage",
        cfg: EmbeddingConfig | None = None,
    ) -> np.ndarray:
        """Embed một batch → ma trận float32 đã chuẩn hóa L2.

        `input_kind` phân biệt ngữ nghĩa query (khi tìm kiếm) và passage (khi
        nạp tài liệu) — chỉ provider có tham số riêng (Jina `task`) dùng tới,
        nhà khác bỏ qua. Validate chiều thực tế của API so với khai báo
        `dimension` — lệch là raise sớm thay vì để pgvector báo lỗi khó hiểu
        lúc insert.
        """
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        cfg = cfg or self.resolve_active_config()
        adapter = get_adapter(cfg.provider)
        vectors = adapter.sync_embed(self._client_for(cfg), cfg, list(texts), input_kind)
        arr = np.asarray(vectors, dtype=np.float32)
        return self._validated(arr, cfg.dimension)

    def embed_one(self, text: str, input_kind: InputKind = "passage") -> np.ndarray:
        return self.embed([text], input_kind=input_kind)[0]

    def _validated(self, arr: np.ndarray, dimension: int) -> np.ndarray:
        if arr.ndim != 2 or arr.shape[1] != dimension:
            got = arr.shape[1] if arr.ndim == 2 else "?"
            raise EmbeddingConfigError(
                f"Model embedding trả về {got} chiều, khác khai báo {dimension} chiều — "
                "sửa lại 'Chiều vector' trong Cài đặt (tab Embedding)."
            )
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms

    # ---------- batch (Batch API của provider) ----------

    def can_batch(self, cfg: EmbeddingConfig | None = None) -> bool:
        """Batch path khả dụng: integration bật use_batch VÀ provider hỗ trợ."""
        cfg = cfg or self.resolve_active_config()
        if not cfg.use_batch:
            return False
        return get_adapter(cfg.provider).spec.supports_batch

    def submit_batch(self, items: list[tuple[str, str]], cfg: EmbeddingConfig | None = None) -> str:
        """Nộp toàn bộ chunks của file vào Batch API → job_id."""
        cfg = cfg or self.resolve_active_config()
        adapter = get_adapter(cfg.provider)
        try:
            return adapter.submit_batch(self._client_for(cfg), cfg, items)
        except BatchError:
            raise
        except Exception as exc:  # noqa: BLE001 — lỗi provider bọc thông báo rõ
            logger.warning("submit batch thất bại provider=%s: %s", cfg.provider, exc)
            raise BatchError(f"Nộp batch job thất bại ({cfg.provider}): {exc}") from exc

    def batch_status(self, job_id: str, cfg: EmbeddingConfig) -> BatchStatus:
        return get_adapter(cfg.provider).batch_status(self._client_for(cfg), cfg, job_id)

    def fetch_batch_results(self, job_id: str, cfg: EmbeddingConfig) -> BatchResults:
        results = get_adapter(cfg.provider).fetch_batch_results(
            self._client_for(cfg), cfg, job_id
        )
        # Validate + L2-normalize từng vector ngay khi tải — lệch chiều là raise
        # thay vì để insert lỗi giữa chừng.
        if results.by_id:
            normalized = {
                cid: self._validated(np.asarray([vec], dtype=np.float32), cfg.dimension)[0]
                for cid, vec in results.by_id.items()
            }
            return replace(results, by_id=normalized)
        normalized_order = [
            self._validated(np.asarray([vec], dtype=np.float32), cfg.dimension)[0]
            for vec in results.ordered
        ]
        return replace(results, ordered=normalized_order)

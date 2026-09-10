"""Types + protocol chung cho tầng provider adapter (embedding).

Mỗi provider (OpenAI, Mistral, Jina, Ollama, custom) có một adapter khai báo
`ProviderSpec` (thông số + model presets kèm các chiều hỗ trợ) và cài đặt sync
embed + (nếu hỗ trợ) Batch API. `Embedder` (core/embedding.py) resolve tích hợp
active rồi gọi adapter tương ứng — hành vi khác nhau giữa các nhà nằm hết ở đây,
không rải rác trong core/worker.

`ModelPreset.dimensions` = các chiều model cho phép chọn (theo docs hiện tại,
MRL/Matryoshka truncation). Model chỉ có 1 chiều cố định (vd mistral-embed,
ada-002) → tuple 1 phần tử ⇒ adapter KHÔNG gửi tham số dimensions/output_dimension.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

InputKind = Literal["query", "passage"]

BatchState = Literal[
    "queued", "running", "completed", "failed", "expired", "cancelled", "unknown"
]


class BatchError(RuntimeError):
    """Lỗi nghiệp vụ Batch API (vượt giới hạn, output không đọc được, job lỗi…)."""


@dataclass(frozen=True)
class ModelPreset:
    """Một model embedding nổi tiếng của provider + các chiều nó hỗ trợ."""

    name: str
    dimensions: tuple[int, ...]

    @property
    def native_dimension(self) -> int:
        return max(self.dimensions)


@dataclass(frozen=True)
class ProviderSpec:
    """Thông số khai báo của một provider — nguồn sự thật cho UI (form preset)."""

    id: str
    display_name: str
    default_base_url: str
    requires_api_key: bool
    supports_batch: bool
    batch_limit: int | None  # số item tối đa / batch job (None = không hỗ trợ batch)
    models: tuple[ModelPreset, ...]

    def preset_for(self, model: str) -> ModelPreset | None:
        """Preset khớp tên model (so khớp chính xác); model lạ → None."""
        return next((m for m in self.models if m.name == model.strip()), None)

    def to_public_dict(self) -> dict[str, Any]:
        """Payload cho GET /embedding-integrations/providers (UI render form)."""
        return {
            "id": self.id,
            "display_name": self.display_name,
            "default_base_url": self.default_base_url,
            "requires_api_key": self.requires_api_key,
            "supports_batch": self.supports_batch,
            "batch_limit": self.batch_limit,
            "models": [
                {"name": m.name, "dimensions": list(m.dimensions)} for m in self.models
            ],
        }


@dataclass(frozen=True)
class EmbeddingConfig:
    """Cấu hình đã resolve của một tích hợp embedding (đã giải mã API key)."""

    integration_id: str
    provider: str
    base_url: str
    api_key: str
    model: str
    dimension: int
    use_batch: bool = False


@dataclass(frozen=True)
class BatchStatus:
    """Trạng thái batch job chuẩn hóa (map từ state riêng từng provider)."""

    state: BatchState
    completed: int = 0
    total: int = 0


@dataclass(frozen=True)
class BatchResults:
    """Kết quả batch đã tải về.

    - `by_id`: map custom_id → vector (OpenAI/Mistral — output mang custom_id).
    - `ordered`: danh sách vector theo thứ tự submit (Jina — custom_id là
      "request-N" sinh theo vị trí, không phải chunk_id của mình).
    Worker ưu tiên `by_id`; không có thì ghép `ordered` với danh sách chunk
    re-chunk lại (deterministic) theo vị trí.
    """

    by_id: dict[str, list[float]] = field(default_factory=dict)
    ordered: list[list[float]] = field(default_factory=list)


class EmbeddingAdapter(Protocol):
    """Hợp đồng adapter embedding — mọi provider cài theo đúng chữ ký này."""

    spec: ProviderSpec

    def build_client(self, cfg: EmbeddingConfig, timeout: float) -> Any:
        """Dựng HTTP client cho sync embed (cache theo fingerprint ở Embedder)."""
        ...

    def sync_embed(
        self, client: Any, cfg: EmbeddingConfig, texts: list[str], input_kind: InputKind
    ) -> list[list[float]]:
        """Embed đồng bộ 1 lô text → list vector thô (chưa L2-normalize)."""
        ...

    def submit_batch(
        self, client: Any, cfg: EmbeddingConfig, items: list[tuple[str, str]]
    ) -> str:
        """Nộp batch job: items = [(custom_id, text)] → job_id."""
        ...

    def batch_status(self, client: Any, cfg: EmbeddingConfig, job_id: str) -> BatchStatus:
        """Hỏi trạng thái job (chuẩn hóa BatchState + số request hoàn tất)."""
        ...

    def fetch_batch_results(
        self, client: Any, cfg: EmbeddingConfig, job_id: str
    ) -> BatchResults:
        """Tải kết quả job hoàn tất."""
        ...

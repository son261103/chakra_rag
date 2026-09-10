"""Adapter nền: endpoint /v1/embeddings chuẩn OpenAI-compatible.

Vừa là adapter cho provider "custom" (mọi nhà tương thích OpenAI mà không có
preset riêng), vừa là lớp cha của OpenAI/Mistral/Jina/Ollama — dùng chung cách
dựng client (openai SDK) và parse response; con chỉ override `_model_kwargs`
(tham số riêng) và các phương thức batch.

KHÔNG dùng wrapper `OpenAIEmbeddings` của langchain: wrapper tokenize bằng
tiktoken (sai với provider khác — trước đây phải tắt bằng
`check_embedding_ctx_length=False`) và không cho truyền tham số riêng từng nhà.
openai SDK truyền thẳng body, đủ kiểm soát.
"""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from core.providers.base import (
    BatchError,
    BatchResults,
    BatchStatus,
    EmbeddingConfig,
    InputKind,
    ProviderSpec,
)


class OpenAICompatAdapter:
    """Adapter nền OpenAI-compatible — sync embed qua openai SDK, không batch."""

    spec: ProviderSpec

    def build_client(self, cfg: EmbeddingConfig, timeout: float) -> Any:
        return OpenAI(
            base_url=cfg.base_url,
            api_key=cfg.api_key or "not-needed",
            timeout=timeout,
            max_retries=2,
        )

    def sync_embed(
        self, client: Any, cfg: EmbeddingConfig, texts: list[str], input_kind: InputKind
    ) -> list[list[float]]:
        kwargs: dict[str, Any] = {"model": cfg.model, "input": list(texts)}
        kwargs.update(self._model_kwargs(cfg, input_kind))
        resp = client.embeddings.create(**kwargs)
        # API có thể trả data không đúng thứ tự input — sắp lại theo `index`.
        data = sorted(resp.data, key=lambda d: getattr(d, "index", 0))
        return [d.embedding for d in data]

    def _model_kwargs(self, cfg: EmbeddingConfig, input_kind: InputKind) -> dict[str, Any]:
        """Tham số riêng của provider gửi kèm body. Model KHÔNG nằm trong preset
        (model lạ / custom) → rỗng ⇒ request OpenAI-compatible thuần, an toàn."""
        return {}

    # ---------- Batch: mặc định không hỗ trợ ----------
    # OpenAI cài qua SDK batches; Mistral/Jina cài qua httpx trong module của
    # chúng. Provider nào không có Batch API sẽ raise tường minh ở đây.

    def submit_batch(
        self, client: Any, cfg: EmbeddingConfig, items: list[tuple[str, str]]
    ) -> str:
        raise BatchError(
            f"Provider '{self.spec.display_name}' không hỗ trợ Batch API — "
            "hãy tắt 'Dùng Batch API' hoặc chọn provider khác."
        )

    def batch_status(self, client: Any, cfg: EmbeddingConfig, job_id: str) -> BatchStatus:
        raise BatchError(
            f"Provider '{self.spec.display_name}' không hỗ trợ Batch API."
        )

    def fetch_batch_results(
        self, client: Any, cfg: EmbeddingConfig, job_id: str
    ) -> BatchResults:
        raise BatchError(
            f"Provider '{self.spec.display_name}' không hỗ trợ Batch API."
        )

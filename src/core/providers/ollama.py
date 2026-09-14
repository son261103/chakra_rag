"""Provider Ollama (self-host): OpenAI-compatible /v1/embeddings local qua official ollama SDK.

- Dùng `ollama.Client(host=...).embed(model=..., input=...)`.
- KHÔNG cần API key, không có Batch API.
"""

from __future__ import annotations

import logging
from typing import Any

import ollama

from core.providers.base import (
    BatchError,
    BatchResults,
    BatchStatus,
    EmbeddingConfig,
    InputKind,
    ModelPreset,
    ProviderSpec,
)

logger = logging.getLogger(__name__)

OLLAMA_SPEC = ProviderSpec(
    id="ollama",
    display_name="Ollama (self-host)",
    default_base_url="http://localhost:11434/v1",
    requires_api_key=False,
    supports_batch=False,
    batch_limit=None,
    models=(
        ModelPreset("nomic-embed-text", (768,)),
        ModelPreset("mxbai-embed-large", (1024,)),
        ModelPreset("bge-m3", (1024,)),
        ModelPreset("all-minilm", (384,)),
    ),
)


class OllamaAdapter:
    """Adapter tích hợp Ollama qua official ollama Python SDK."""

    spec = OLLAMA_SPEC

    def build_client(self, cfg: EmbeddingConfig, timeout: float) -> ollama.Client:
        raw_url = cfg.base_url.strip() or self.spec.default_base_url
        host = raw_url.rstrip("/").removesuffix("/v1").rstrip("/") or "http://localhost:11434"
        return ollama.Client(host=host, timeout=timeout)

    def sync_embed(
        self, client: Any, cfg: EmbeddingConfig, texts: list[str], input_kind: InputKind
    ) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = client.embed(model=cfg.model, input=list(texts))
        except Exception as exc:
            logger.warning("Ollama embed thất bại: %s", exc)
            raise

        embeddings = (
            resp.get("embeddings")
            if isinstance(resp, dict)
            else getattr(resp, "embeddings", None)
        )
        if embeddings is None:
            raise ValueError(f"Ollama API không trả về embeddings: {resp}")
        return [list(vec) for vec in embeddings]

    def submit_batch(
        self, client: Any, cfg: EmbeddingConfig, items: list[tuple[str, str]]
    ) -> str:
        raise BatchError(
            f"Provider '{self.spec.display_name}' không hỗ trợ Batch API."
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

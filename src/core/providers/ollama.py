"""Provider Ollama (self-host): OpenAI-compatible /v1/embeddings local.

- KHÔNG cần API key (header Authorization bị bỏ qua), không có Batch API.
- Không gửi tham số riêng: chiều do model user pull về máy quyết định — user
  phải khai báo đúng `dimension` (VD nomic-embed-text=768, bge-m3=1024); khai
  sai sẽ bị Embedder bắt lệch chiều ngay khi embed đầu tiên.
"""

from __future__ import annotations

from core.providers.base import ModelPreset, ProviderSpec
from core.providers.openai_compat import OpenAICompatAdapter

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


class OllamaAdapter(OpenAICompatAdapter):
    spec = OLLAMA_SPEC

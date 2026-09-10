"""Registry các embedding provider — nguồn sự thật cho backend lẫn UI.

Thêm provider mới: viết adapter trong module này + đăng ký vào
`PROVIDER_REGISTRY`. UI tự render form preset từ GET /embedding-integrations/
providers (không phải sửa frontend khi thêm nhà).

Không fallback "về openai" khi id lạ — raise tường minh (nguyên tắc không
silent fallback của dự án).
"""

from __future__ import annotations

from core.providers.base import ProviderSpec
from core.providers.jina import JINA_SPEC, JinaAdapter
from core.providers.mistral import MISTRAL_SPEC, MistralAdapter
from core.providers.ollama import OLLAMA_SPEC, OllamaAdapter
from core.providers.openai import OPENAI_SPEC, OpenAIAdapter
from core.providers.openai_compat import OpenAICompatAdapter

CUSTOM_SPEC = ProviderSpec(
    id="custom",
    display_name="Tùy chỉnh (OpenAI-compatible)",
    default_base_url="",
    requires_api_key=True,
    supports_batch=False,
    batch_limit=None,
    models=(),  # không preset — user tự nhập base_url/model/dimension
)

PROVIDER_REGISTRY: dict[str, ProviderSpec] = {
    spec.id: spec
    for spec in (OPENAI_SPEC, MISTRAL_SPEC, JINA_SPEC, OLLAMA_SPEC, CUSTOM_SPEC)
}


def get_provider(provider_id: str) -> ProviderSpec:
    """Spec theo id — id lạ raise ValueError (không fallback)."""
    try:
        return PROVIDER_REGISTRY[provider_id.strip()]
    except KeyError as exc:
        raise ValueError(
            f"Provider embedding không hỗ trợ: '{provider_id}'. "
            f"Các provider khả dụng: {', '.join(sorted(PROVIDER_REGISTRY))}"
        ) from exc


def get_adapter(provider_id: str) -> OpenAICompatAdapter:
    """Adapter instance theo provider id.

    Mọi adapter hiện kế thừa OpenAICompatAdapter (khác nhau ở `_model_kwargs`
    + batch methods); provider mới không kế thừa nền này thì thêm nhánh
    tường minh tại đây.
    """
    if provider_id == "openai":
        return OpenAIAdapter()
    if provider_id == "mistral":
        return MistralAdapter()
    if provider_id == "jina":
        return JinaAdapter()
    if provider_id == "ollama":
        return OllamaAdapter()
    spec = get_provider(provider_id)
    adapter = OpenAICompatAdapter()
    adapter.spec = spec
    return adapter


def list_provider_specs() -> list[ProviderSpec]:
    return list(PROVIDER_REGISTRY.values())

from __future__ import annotations

from ..config import get_settings
from .base import LLMProvider, LLMResult, parse_json_object
from .providers import AnthropicProvider, FakeProvider, OpenAICompatibleProvider

__all__ = ["LLMProvider", "LLMResult", "parse_json_object", "get_provider", "FakeProvider", "PROVIDERS"]

OPENROUTER_URL = "https://openrouter.ai/api/v1"
PROVIDERS = ("anthropic", "openrouter", "openai_compatible")


def get_provider(provider: str | None = None, model: str | None = None, base_url: str | None = None) -> LLMProvider:
    """Build a provider from tenant settings, falling back to environment defaults."""
    s = get_settings()
    provider = provider or s.llm_provider
    model = model or s.llm_model
    if provider == "anthropic":
        return AnthropicProvider(model=model, api_key=s.anthropic_api_key)
    if provider == "openrouter":
        p = OpenAICompatibleProvider(model=model, base_url=OPENROUTER_URL, api_key=s.openrouter_api_key or "missing",
                                     extra_headers={"HTTP-Referer": "https://www.onpointpersonnel.com",
                                                    "X-Title": "OnPoint CRM"})
        p.name = "openrouter"
        return p
    if provider == "openai_compatible":
        return OpenAICompatibleProvider(
            model=model, base_url=base_url or s.openai_compatible_base_url, api_key=s.openai_compatible_api_key
        )
    raise ValueError(f"Unknown LLM provider: {provider}")

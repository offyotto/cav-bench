"""Provider registry."""
from __future__ import annotations

from .anthropic import AnthropicProvider
from .base import Provider, ProviderError, ProviderResponse
from .generic_openai_compatible import OpenAICompatibleProvider
from .mock import MockProvider
from .openai import OpenAIProvider

REGISTRY: dict[str, type[Provider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "mock": MockProvider,
}


def build_provider(spec: dict) -> Provider:
    spec = dict(spec)
    kind = spec.pop("provider")
    if kind not in REGISTRY:
        raise ValueError(f"unknown provider {kind!r}; known: {sorted(REGISTRY)}")
    spec.pop("label", None)
    spec.pop("access_tier", None)
    return REGISTRY[kind](**spec)


__all__ = [
    "Provider", "ProviderError", "ProviderResponse", "REGISTRY", "build_provider",
    "AnthropicProvider", "OpenAIProvider", "OpenAICompatibleProvider", "MockProvider",
]

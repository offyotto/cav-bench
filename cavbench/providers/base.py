"""Provider-neutral adapter interface."""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ProviderResponse:
    text: str
    model: str
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)  # attempts, latency, provider-specific ids
    raw: dict | None = None


class ProviderError(RuntimeError):
    pass


class Provider(ABC):
    """A model endpoint. Subclasses implement `_complete`."""

    name = "base"

    def __init__(self, model: str, temperature: float = 0.0, max_tokens: int = 1024,
                 system_prompt: str | None = None, api_key_env: str | None = None,
                 base_url: str | None = None, extra: dict | None = None, **_: object):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self.api_key_env = api_key_env
        self.base_url = base_url
        self.extra = extra or {}

    def api_key(self) -> str:
        if not self.api_key_env:
            raise ProviderError(f"{self.name}: api_key_env not configured")
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ProviderError(f"{self.name}: environment variable {self.api_key_env} is not set")
        return key

    def complete(self, messages: list[dict], **kwargs) -> ProviderResponse:
        return self._complete(messages, **kwargs)

    @abstractmethod
    def _complete(self, messages: list[dict], **kwargs) -> ProviderResponse: ...

    def describe(self) -> dict:
        """Deterministic metadata for logs (never includes secrets)."""
        return {
            "provider": self.name,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "system_prompt": self.system_prompt,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "extra": self.extra,
        }

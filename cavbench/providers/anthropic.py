"""Anthropic Messages API adapter.

Verified-access comparisons (e.g., CVP vs standard) are run by pointing two
configs at two different API keys / organizations via `api_key_env`.
"""
from __future__ import annotations

from ..http import post_json
from .base import Provider, ProviderResponse


class AnthropicProvider(Provider):
    name = "anthropic"
    DEFAULT_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(self, model: str, api_key_env: str | None = "ANTHROPIC_API_KEY", **kw):
        super().__init__(model, api_key_env=api_key_env, **kw)

    def _complete(self, messages, **kwargs) -> ProviderResponse:
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": messages,
        }
        if self.system_prompt:
            payload["system"] = self.system_prompt
        payload.update(self.extra.get("payload", {}))
        headers = {"x-api-key": self.api_key(), "anthropic-version": self.API_VERSION}
        data, meta = post_json(self.base_url or self.DEFAULT_URL, payload, headers)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        meta["response_id"] = data.get("id")
        return ProviderResponse(
            text=text,
            model=data.get("model", self.model),
            stop_reason=data.get("stop_reason"),
            usage=data.get("usage", {}),
            meta=meta,
            raw=data,
        )

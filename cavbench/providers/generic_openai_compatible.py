"""OpenAI Chat Completions adapter and a generic OpenAI-compatible adapter."""
from __future__ import annotations

from ..http import post_json
from .base import Provider, ProviderResponse


class OpenAICompatibleProvider(Provider):
    """Any endpoint implementing POST {base_url}/chat/completions."""

    name = "openai_compatible"
    DEFAULT_BASE = None

    def _complete(self, messages, **kwargs) -> ProviderResponse:
        base = (self.base_url or self.DEFAULT_BASE or "").rstrip("/")
        if not base:
            raise ValueError(f"{self.name}: base_url is required")
        msgs = ([{"role": "system", "content": self.system_prompt}] if self.system_prompt else []) + messages
        payload = {
            "model": self.model,
            "messages": msgs,
            "temperature": self.temperature,
            self.extra.get("max_tokens_field", "max_tokens"): self.max_tokens,
        }
        payload.update(self.extra.get("payload", {}))
        headers = {"authorization": f"Bearer {self.api_key()}"} if self.api_key_env else {}
        data, meta = post_json(f"{base}/chat/completions", payload, headers)
        choice = (data.get("choices") or [{}])[0]
        meta["response_id"] = data.get("id")
        return ProviderResponse(
            text=(choice.get("message") or {}).get("content") or "",
            model=data.get("model", self.model),
            stop_reason=choice.get("finish_reason"),
            usage=data.get("usage", {}),
            meta=meta,
            raw=data,
        )

"""OpenAI adapter (Chat Completions)."""
from __future__ import annotations

from .generic_openai_compatible import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    DEFAULT_BASE = "https://api.openai.com/v1"

    def __init__(self, model: str, api_key_env: str | None = "OPENAI_API_KEY", **kw):
        super().__init__(model, api_key_env=api_key_env, **kw)

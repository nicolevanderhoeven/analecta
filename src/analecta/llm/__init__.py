"""Model providers. Add a provider by implementing llm.base.LLMProvider and registering it here."""
from __future__ import annotations

from ..config import ConfigError, Settings
from .base import LLMProvider


def make_provider(settings: Settings) -> LLMProvider:
    if settings.provider == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=settings.api_key, model=settings.model, reasoning_effort=settings.reasoning_effort
        )
    raise ConfigError(f"Unknown LLM_PROVIDER: {settings.provider}")

"""Resolve LLM provider configuration (OpenAI primary, xAI fallback)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

_XAI_BASE_URL = "https://api.x.ai/v1"


@dataclass
class OpenAIConfig:
    api_key: str
    model: str = "gpt-4o-mini"
    base_url: str | None = None


class ChatCompleter(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


def resolve_openai_config() -> OpenAIConfig | None:
    """Return config for the primary provider (OpenAI) or xAI as fallback."""
    key = os.getenv("OPENAI_API_KEY")
    if key:
        model = os.getenv("FINAGENT_OPENAI_MODEL", "gpt-4o-mini")
        return OpenAIConfig(api_key=key, model=model)

    # Fallback: xAI (Grok) — OpenAI-compatible endpoint
    xai_key = os.getenv("XAI_API_KEY")
    if xai_key:
        model = os.getenv("FINAGENT_XAI_MODEL", "grok-3-mini")
        return OpenAIConfig(api_key=xai_key, model=model, base_url=_XAI_BASE_URL)

    return None

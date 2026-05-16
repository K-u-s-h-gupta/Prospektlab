"""Resolve LLM provider configuration (OpenAI primary)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


@dataclass
class OpenAIConfig:
    api_key: str
    model: str = "gpt-4o-mini"
    base_url: str | None = None


class ChatCompleter(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


def resolve_openai_config() -> OpenAIConfig | None:
    
    key = os.getenv("OPENAI_API_KEY")
    if key:
        model = os.getenv("FINAGENT_OPENAI_MODEL", "gpt-4o-mini")
        return OpenAIConfig(api_key=key, model=model)
    return None

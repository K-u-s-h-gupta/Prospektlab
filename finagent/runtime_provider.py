"""Resolve LLM provider configuration (OpenAI primary)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


@dataclass
class OpenAIConfig:
    api_key: str
    model: str = "qwen/qwen3.5-plus-20260420"


class ChatCompleter(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


def resolve_openai_config() -> OpenAIConfig | None:
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return None
    model = os.getenv("FINAGENT_OPENAI_MODEL", "qwen/qwen3.5-plus-20260420")
    return OpenAIConfig(api_key=key, model=model)

"""Resolve LLM provider (Anthropic primary)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


@dataclass
class AnthropicConfig:
    api_key: str
    model: str = "claude-sonnet-4-20250514"


class ChatCompleter(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


def resolve_anthropic_config() -> AnthropicConfig | None:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    model = os.getenv("FINAGENT_ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    return AnthropicConfig(api_key=key, model=model)

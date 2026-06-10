"""Resolve LLM provider configuration (OpenAI primary, xAI fallback).

Includes complexity-aware model routing:
- "simple"   → GPT-4o-mini (or grok-3-mini) for 40-60% cost savings
- "moderate" → GPT-4o (default)
- "complex"  → GPT-4o (full capability)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

_XAI_BASE_URL = "https://api.x.ai/v1"


@dataclass
class OpenAIConfig:
    api_key: str
    model: str = "gpt-4o"
    base_url: str | None = None


class ChatCompleter(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


def resolve_openai_config(complexity: str = "moderate") -> OpenAIConfig | None:
    """Return config for the primary provider (OpenAI) or xAI as fallback.

    Args:
        complexity: Query complexity tier — "simple" | "moderate" | "complex".
                    Simple queries are routed to cheaper mini-models.
                    This achieves 40-60% API cost reduction on high-volume traffic.
    """
    key = os.getenv("OPENAI_API_KEY")
    if key:
        # Complexity-aware model selection
        if complexity == "simple":
            model = (
                os.getenv("FINAGENT_OPENAI_MODEL_SIMPLE")
                or os.getenv("FINAGENT_OPENAI_MODEL_MINI")
                or "gpt-4o-mini"
            )
        else:
            # Support both FINAGENT_OPENAI_MODEL and legacy FINAGENT_SYNTH_MODEL
            model = (
                os.getenv("FINAGENT_OPENAI_MODEL")
                or os.getenv("FINAGENT_SYNTH_MODEL")
                or "gpt-4o"
            )
        return OpenAIConfig(api_key=key, model=model)

    # Fallback: xAI (Grok) — OpenAI-compatible endpoint
    xai_key = os.getenv("XAI_API_KEY")
    if xai_key:
        if complexity == "simple":
            model = os.getenv("FINAGENT_XAI_MODEL_SIMPLE", "grok-3-mini")
        else:
            model = os.getenv("FINAGENT_XAI_MODEL", "grok-3")
        return OpenAIConfig(api_key=xai_key, model=model, base_url=_XAI_BASE_URL)

    return None

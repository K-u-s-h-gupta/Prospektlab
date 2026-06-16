"""Context window compression hooks (LLM summarization wired at integration time)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class CompressedFacts:
    bullets: list[str]
    max_tokens: int = 500


def compress_facts_stub(history_snippets: list[str]) -> CompressedFacts:
    """Placeholder until an LLM summarizer is injected."""
    bullets = [s[:200] for s in history_snippets[:25]]
    return CompressedFacts(bullets=bullets)


def approx_token_count(text: str) -> int:
    """Rough heuristic (~4 chars per token)."""
    return max(1, len(text) // 4)

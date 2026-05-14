"""Load and assemble FinAgent system prompt (Section 1–8)."""

from __future__ import annotations

import os
from pathlib import Path


def _builtin_prompt_path() -> Path:
    return Path(__file__).resolve().parent / "prompts" / "finagent_system.txt"


def default_system_prompt() -> str:
    """Load bundled prompt, or FINAGENT_PROMPT_PATH when set."""
    override = os.getenv("FINAGENT_PROMPT_PATH")
    if override:
        return load_system_prompt_from_path(Path(override))
    p = _builtin_prompt_path()
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return _FALLBACK_PROMPT


def load_system_prompt_from_path(path: Path) -> str:
    return path.read_text(encoding="utf-8")


_FALLBACK_PROMPT = (
    "You are FinAgent, a long-running autonomous financial research agent for ProspektLab. "
    "Follow pre-flight clarification, checkpoints every 5 steps, source hierarchy, "
    "triangulation for material claims, and human gates before exports."
)

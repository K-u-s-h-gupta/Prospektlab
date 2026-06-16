"""Emit structured conflict blocks for memos."""

from __future__ import annotations


def conflict_block(source_a: str, value_a: str, source_b: str, value_b: str) -> str:
    return (
        "[CONFLICT DETECTED]\n"
        f"- {source_a}: {value_a}\n"
        f"- {source_b}: {value_b}\n"
        "[CONFLICTED — needs verification]\n"
        "[GATE — waiting for human confirmation]"
    )

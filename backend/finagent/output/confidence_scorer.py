"""Aggregate per-section confidence into overall label."""

from __future__ import annotations

from collections import Counter


def aggregate_confidence(tags: list[str]) -> str:
    c = Counter(t.upper() for t in tags if t)
    if c.get("LOW", 0) >= max(1, len(tags) // 3):
        return "LOW"
    if c.get("HIGH", 0) >= len(tags) // 2:
        return "HIGH"
    return "MEDIUM"

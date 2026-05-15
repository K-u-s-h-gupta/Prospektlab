from __future__ import annotations


def should_enable_deep_research(objective: str) -> bool:
    lower = (objective or "").lower()
    return any(term in lower for term in ("deep", "comprehensive", "forensic", "detailed", "due diligence"))

from __future__ import annotations

import re


_ENTITY_RE = re.compile(r"\b([A-Z][A-Za-z&]{2,}(?:\s+[A-Z][A-Za-z&]{2,}){0,2})\b")


def extract_related_entities(text: str, *, exclude: tuple[str, ...] = ()) -> list[str]:
    exclude_lc = {e.lower() for e in exclude}
    names: list[str] = []
    for match in _ENTITY_RE.findall(text or ""):
        candidate = match.strip()
        if candidate.lower() in exclude_lc:
            continue
        if candidate not in names:
            names.append(candidate)
    return names[:12]


def score_entity_relationship(query: str, text: str, aliases: tuple[str, ...]) -> float:
    q = query.lower()
    t = text.lower()
    score = 0.0
    if any(alias.lower() in t for alias in aliases if alias):
        score += 1.0
    if any(term in q for term in ("subsidiary", "competitor", "peer", "supplier", "customer", "board")):
        related = extract_related_entities(text, exclude=aliases)
        score += min(len(related), 4) * 0.2
    return score

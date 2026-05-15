from __future__ import annotations

import re


_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\.\-/&]{1,}")


def tokenize(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}


def score_sparse(query: str, text: str) -> float:
    q_tokens = tokenize(query)
    t_tokens = tokenize(text)
    if not q_tokens or not t_tokens:
        return 0.0
    exact = len(q_tokens & t_tokens)
    ticker_hits = sum(1 for tok in q_tokens if tok.isupper() and tok.lower() in t_tokens)
    return float(exact) + (0.5 * ticker_hits)

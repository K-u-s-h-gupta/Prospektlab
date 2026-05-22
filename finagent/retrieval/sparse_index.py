from __future__ import annotations

import re


_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\.\-/&]{1,}")


def tokenize(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")}


def sanitize_search_query(query: str) -> str:
    """Strip search operators and literal quotes from a query to produce
    a clean text-only phrase suitable for content filtering or rerankers.
    """
    if not query:
        return ""
    # Strip operators like site:..., filetype:..., ext:...
    q = re.sub(
        r"\b(site|filetype|ext|inurl|intitle|intext|allinurl|allintitle|allintext|related|cache|info|link|maps|book|stocks|define|phonebook):\S*",
        "",
        query,
        flags=re.IGNORECASE,
    )
    # Strip quotes
    q = re.sub(r"[\'\"]", " ", q)
    # Strip standalone logical operators (AND, OR, NOT)
    q = re.sub(r"\b(AND|OR|NOT)\b", " ", q)
    # Strip extra whitespace
    q = re.sub(r"\s+", " ", q).strip()
    return q


def score_sparse(query: str, text: str) -> float:
    sanitized_query = sanitize_search_query(query)
    q_tokens = tokenize(sanitized_query)
    t_tokens = tokenize(text)
    if not q_tokens or not t_tokens:
        return 0.0
    exact = len(q_tokens & t_tokens)
    ticker_hits = sum(1 for tok in q_tokens if tok.isupper() and tok.lower() in t_tokens)
    return float(exact) + (0.5 * ticker_hits)

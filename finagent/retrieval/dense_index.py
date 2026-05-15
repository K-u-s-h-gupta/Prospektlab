from __future__ import annotations

from finagent.retrieval.sparse_index import tokenize


_SEMANTIC_SYNONYMS: dict[str, set[str]] = {
    "earnings": {"results", "profit", "eps", "quarter"},
    "annual": {"yearly", "fiscal"},
    "investor": {"shareholder", "ir"},
    "risk": {"headwind", "litigation", "investigation", "volatility"},
    "guidance": {"forecast", "outlook"},
    "competitor": {"peer", "rival", "alternative"},
    "valuation": {"multiple", "intrinsic", "dcf", "pe", "pb"},
    "transcript": {"concall", "conference", "call"},
}


def _expand(tokens: set[str]) -> set[str]:
    out = set(tokens)
    for tok in list(tokens):
        out.update(_SEMANTIC_SYNONYMS.get(tok, set()))
    return out


def score_semantic(query: str, text: str) -> float:
    q = _expand(tokenize(query))
    t = _expand(tokenize(text))
    if not q or not t:
        return 0.0
    overlap = len(q & t)
    union = len(q | t)
    return overlap / union if union else 0.0

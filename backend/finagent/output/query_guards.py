"""Central guards to prevent query misclassification collisions.

When a portfolio query contains comparison words like "vs", "compared to",
"against", the system must treat it as a PORTFOLIO query, not a company
comparison. This module provides a single source of truth for that guard.
"""

from __future__ import annotations

from finagent.router.intent_router import is_portfolio_scope_query


def is_portfolio_comparison_query(query: str) -> bool:
    """Return True if the query is a portfolio query that contains comparison words.

    This is used to PREVENT misclassification as a company comparison.
    When this returns True, downstream code should treat it as a portfolio
    query (portfolio audit / snapshot) and NOT as a company-vs-company comparison.
    """
    return is_portfolio_scope_query(query) and _has_comparison_word(query)


def _has_comparison_word(query: str) -> bool:
    lower = (query or "").lower()
    return any(term in lower for term in _COMPARISON_WORDS)


_COMPARISON_WORDS = (
    "compare",
    " vs ",
    " versus ",
    "against",
    "head to head",
    "compared to",
    "compared with",
    "relative to",
    "benchmark against",
    "how does",
    "performance against",
    "outperform",
    "underperform",
)

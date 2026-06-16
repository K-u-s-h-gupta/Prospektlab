"""Filing Materiality Triage — classify a corporate announcement's importance.

Powers real-time filing alerts: BSE/NSE announcements are noisy (most are
routine board meetings); this scores each filing so only material events page a
user. Rule-based core (high-signal Indian corporate-action keywords) with an
optional LLM escalation for ambiguous cases.

Design:
  - `classify_materiality(filing)` is PURE (no DB / no LLM) → unit-testable.
  - `triage_filing(filing, llm_classify=...)` applies rules, then escalates
    only genuinely ambiguous filings to an injected LLM callable.

Bands: HIGH (alert immediately), MEDIUM (digest), ROUTINE (suppress).
"""

from __future__ import annotations

import re
from typing import Any, Callable

# High-materiality signals — events that move prices or signal governance risk.
_HIGH_PATTERNS = [
    (r"\bauditor'?s?\s+(resign|removal|change)|resignation of (statutory )?auditor", "auditor_change"),
    (r"\bresignation of (the )?(cfo|chief financial|managing director|md|ceo|chairman|company secretary)", "key_mgmt_exit"),
    (r"\bpledge|\bencumbr", "pledge"),
    (r"\bdefault\b|delay in payment|failure to pay|insolvenc|\bnclt\b|\bibc\b", "default_insolvency"),
    (r"\bfraud|misappropriat|diversion of funds|forensic audit", "fraud"),
    (r"\bsebi\b.*\b(order|penalty|notice|adjudicat)|show cause notice", "regulatory_action"),
    (r"credit rating.*(downgrade|revis|withdraw)|rating (downgrade|revision)", "rating_change"),
    (r"\b(qip|preferential|rights issue|fund\s?rais|fpo|allotment of (equity|shares))", "fundraise"),
    (r"\b(amalgamation|merger|demerger|acquisition|scheme of arrangement|open offer|buyback)", "ma"),
    (r"\bstock split|bonus issue|special dividend", "capital_action"),
    (r"\bresult.*(loss|fraud|qualif)|qualified opinion|going concern", "adverse_result"),
]

# Routine signals — suppress unless a HIGH pattern also matches.
_ROUTINE_PATTERNS = [
    r"\bboard meeting (intimation|to be held|scheduled)",
    r"\bnewspaper (publication|advertisement)",
    r"\btrading window (closure|opening)",
    r"\binvestor (presentation|call) (schedul|intimation)",
    r"\bcompliance certificate|reg\.?\s?\d+|regulation \d+",
    r"\bloss of share certificate|duplicate share",
    r"\brecord date (for|intimation)",
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def classify_materiality(filing: dict[str, Any]) -> dict[str, Any]:
    """Classify a filing from its text fields. Pure rules.

    filing shape: {"subject"|"headline"|"title", "category", "body"|"description"}
    Returns {band, category, score, reasons, ambiguous}.
    """
    text = _norm(" ".join(str(filing.get(k) or "") for k in
                          ("subject", "headline", "title", "category", "body", "description")))
    if not text:
        return {"band": "ROUTINE", "category": "empty", "score": 0, "reasons": [], "ambiguous": False}

    high_hits: list[str] = []
    for pattern, tag in _HIGH_PATTERNS:
        if re.search(pattern, text):
            high_hits.append(tag)

    routine_hit = any(re.search(p, text) for p in _ROUTINE_PATTERNS)

    if high_hits:
        # Any high-signal keyword dominates even if a routine phrase co-occurs.
        score = min(100, 60 + 15 * len(high_hits))
        return {
            "band": "HIGH",
            "category": high_hits[0],
            "score": score,
            "reasons": high_hits,
            "ambiguous": False,
        }
    if routine_hit:
        return {"band": "ROUTINE", "category": "routine", "score": 5, "reasons": ["routine_pattern"], "ambiguous": False}

    # No clear signal either way — ambiguous; candidate for LLM escalation.
    return {"band": "MEDIUM", "category": "unclassified", "score": 40, "reasons": [], "ambiguous": True}


def triage_filing(
    filing: dict[str, Any],
    *,
    llm_classify: Callable[[dict[str, Any]], str] | None = None,
) -> dict[str, Any]:
    """Rule classification, escalating only ambiguous filings to an LLM callable.

    `llm_classify(filing) -> "HIGH"|"MEDIUM"|"ROUTINE"` is injected (keeps this
    testable and provider-agnostic). On any LLM error the rule result stands.
    """
    result = classify_materiality(filing)
    if result["ambiguous"] and llm_classify is not None:
        try:
            verdict = (llm_classify(filing) or "").strip().upper()
            if verdict in {"HIGH", "MEDIUM", "ROUTINE"}:
                result["band"] = verdict
                result["category"] = "llm_classified"
                result["reasons"] = result["reasons"] + ["llm"]
                result["ambiguous"] = False
        except Exception:
            # LLM failure must not drop the filing — keep the rule verdict.
            result["reasons"] = result["reasons"] + ["llm_error"]
    return result


def should_alert(result: dict[str, Any]) -> bool:
    """Whether a triage result warrants an immediate user alert."""
    return result.get("band") == "HIGH"

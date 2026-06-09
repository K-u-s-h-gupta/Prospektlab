"""SEBI-aware final-answer guardrails.

This module is intentionally deterministic. Prompt instructions reduce the
chance of advisory wording, but this final pass makes the saved/rendered answer
use objective research language even when an upstream model or tool emits
recommendation-style prose.
"""

from __future__ import annotations

import re


SEBI_COMPLIANCE_NOTE = (
    "Regulatory note: This is an educational, evidence-based research summary for Indian securities. "
    "It is not investment advice, a research recommendation, or a solicitation to buy, sell, or hold any security. "
    "Please consult a SEBI-registered Investment Adviser or Research Analyst before making investment decisions."
)


_HEADER_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^(#{1,6}\s*)Investment\s+Verdict\b", re.I | re.M), r"\1Evidence-Based View"),
    (re.compile(r"^(#{1,6}\s*)Verdict\b", re.I | re.M), r"\1Evidence-Based View"),
    (re.compile(r"^(#{1,6}\s*)Investment\s+View\b", re.I | re.M), r"\1Research View"),
    (re.compile(r"^(#{1,6}\s*)Recommendation\b", re.I | re.M), r"\1Research Summary"),
    (re.compile(r"^(#{1,6}\s*)Bottom\s+Line\b", re.I | re.M), r"\1Key Takeaways"),
)


_PHRASE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(strong\s+buy|buy|accumulate)\b", re.I), "positive setup under the stated assumptions"),
    (re.compile(r"\b(strong\s+sell|sell|exit|dump)\b", re.I), "negative setup under the stated assumptions"),
    (re.compile(r"\bhold\b", re.I), "monitor"),
    (re.compile(r"\bunderweight\b", re.I), "lower relative exposure context"),
    (re.compile(r"\boverweight\b", re.I), "higher relative exposure context"),
    (re.compile(r"\bmultibagger\b", re.I), "high-upside claim requiring independent verification"),
    (re.compile(r"\bprice\s+target\b", re.I), "scenario-implied value"),
    (re.compile(r"\btarget\s+price\b", re.I), "scenario-implied value"),
    (re.compile(r"\binvestment\s+recommendation\b", re.I), "research observation"),
    (re.compile(r"\brecommendation\b", re.I), "research observation"),
    (re.compile(r"\brecommend(?:ed|s)?\b", re.I), "indicates"),
    (re.compile(r"\bshould\s+(?:buy|sell|hold|exit|enter|accumulate|invest)\b", re.I), "should review the evidence and risk profile for"),
    (re.compile(r"\bconsider\s+(?:buying|selling|exiting|entering|accumulating|trimming)\b", re.I), "review the scenario impact of"),
    (re.compile(r"\btrim(?:ming)?\s+(\d+(?:\.\d+)?%)\b", re.I), r"review concentration impact of \1 exposure"),
    (re.compile(r"\bbook\s+profits?\b", re.I), "review realized/unrealized gain and tax impact"),
)


_VALUATION_LABELS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bpotentially\s+UNDERVALUED\b", re.I), "trading below the model-implied value under these assumptions"),
    (re.compile(r"\bpotentially\s+OVERVALUED\b", re.I), "trading above the model-implied value under these assumptions"),
    (re.compile(r"\bFAIRLY\s+VALUED\b", re.I), "near the model-implied value range under these assumptions"),
    (re.compile(r"\bUNDERVALUED\b", re.I), "below model-implied value"),
    (re.compile(r"\bOVERVALUED\b", re.I), "above model-implied value"),
)


_DIRECTIVE_SENTENCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[^.\n]*(?:you|investors?|users?)\s+should\s+(?:buy|sell|hold|exit|enter|invest|accumulate)[^.\n]*[.\n]", re.I),
    re.compile(r"[^.\n]*(?:buy|sell|hold|exit|enter)\s+(?:now|today|at current levels)[^.\n]*[.\n]", re.I),
)


def enforce_sebi_compliance(text: str, *, include_regulatory_note: bool = True) -> str:
    """Return a safer, research-only version of generated finance prose."""
    if not text:
        return text

    out = text.replace("\r\n", "\n").replace("\xa0", " ")

    for pattern, replacement in _HEADER_REPLACEMENTS:
        out = pattern.sub(replacement, out)

    for pattern in _DIRECTIVE_SENTENCE_PATTERNS:
        out = pattern.sub(
            " The evidence should be reviewed against the user's suitability, risk profile, time horizon, and professional advice.\n",
            out,
        )

    for pattern, replacement in _VALUATION_LABELS:
        out = pattern.sub(replacement, out)

    for pattern, replacement in _PHRASE_REPLACEMENTS:
        out = pattern.sub(replacement, out)

    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    if (
        include_regulatory_note
        and "not investment advice" not in out.lower()
        and "educational, evidence-based research summary" not in out.lower()
    ):
        out = f"{out}\n\n---\n{SEBI_COMPLIANCE_NOTE}"
    return out

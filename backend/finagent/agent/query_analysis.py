"""Query analysis for chatbot Standard / Deep research modes.

Pure, testable primitives (no LLM / no IO):

  - classify_query_complexity:  detects numeric, comparative, and
    governance-sensitive queries so Standard mode can enable verification
    phases for the queries that actually need them (not blunt pattern match).
  - detect_export_intent:       robust verb+object intent extraction (with
    negation handling) for "export this as a report" — replaces fragile
    single-keyword regex; no auto-export unless the user truly asks.
  - adaptive_wall_budget:       query-adaptive Deep-mode wall-clock budget
    instead of a fixed 55s cap.
  - reflection_rounds_for_budget: how many reflection rounds (0-3) the
    remaining budget permits.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ── Signal lexicons ───────────────────────────────────────────────────────────
_NUMERIC_RE = re.compile(
    r"(?<![\w])[₹$]?\d[\d,]*\.?\d*\s?(%|bps|cr|crore|lakh|bn|billion|trillion|x|pe|p/e)?|"
    r"\b(how much|how many|what is the|calculate|ratio|margin|growth rate|cagr|yield|valuation|dcf|"
    r"intrinsic value|fair value|eps|pe ratio|roe|roce|debt to equity)\b",
    re.IGNORECASE,
)
_COMPARATIVE_RE = re.compile(
    r"\b(vs\.?|versus|compare|compared to|better than|worse than|against|between .+ and |"
    r"which is (better|stronger|cheaper|safer)|outperform|relative to|peer)\b",
    re.IGNORECASE,
)
_GOVERNANCE_RE = re.compile(
    r"\b(governance|promoter (pledge|holding)|pledge|auditor|audit (firm|qualif)|related party|rpt|"
    r"sebi|enforcement|fraud|insider trading|board (change|exit)|resignation|forensic|"
    r"red flag|default|insolvenc|nclt|ibc|rating downgrade|misappropriat)\b",
    re.IGNORECASE,
)


@dataclass
class ComplexityResult:
    tier: str                       # "simple" | "standard" | "complex"
    enable_verification: bool       # turn on verification phases even in Standard
    signals: dict[str, bool] = field(default_factory=dict)
    score: float = 0.0


def classify_query_complexity(message: str) -> ComplexityResult:
    """Detect numeric/comparative/governance sensitivity to decide verification."""
    text = (message or "").strip()
    if not text:
        return ComplexityResult(tier="simple", enable_verification=False, signals={}, score=0.0)

    numeric = bool(_NUMERIC_RE.search(text))
    comparative = bool(_COMPARATIVE_RE.search(text))
    governance = bool(_GOVERNANCE_RE.search(text))
    multi_entity = len(re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", text)) >= 3
    long_query = len(text.split()) >= 18

    signals = {
        "numeric": numeric,
        "comparative": comparative,
        "governance": governance,
        "multi_entity": multi_entity,
        "long_query": long_query,
    }
    # Weighted score; governance and comparative are the strongest verification triggers.
    score = (
        1.4 * governance + 1.2 * comparative + 1.0 * numeric
        + 0.5 * multi_entity + 0.4 * long_query
    )
    # Governance/comparative/numeric → verification is worth the latency.
    enable_verification = governance or comparative or numeric
    if score >= 1.8:
        tier = "complex"
    elif score >= 0.9:
        tier = "standard"
    else:
        tier = "simple"
    return ComplexityResult(tier=tier, enable_verification=enable_verification, signals=signals, score=round(score, 2))


# ── Export-intent extraction (NLP-style verb+object, negation-aware) ──────────
_EXPORT_VERBS = {
    "export", "download", "generate", "produce", "create", "save", "compile",
    "render", "build", "draft", "prepare", "send", "email",
}
_EXPORT_OBJECTS = {
    "report", "document", "doc", "pdf", "docx", "file", "memo", "writeup",
    "write-up", "deck", "paper", "dossier", "brief", "copy",
}
_EXPORT_PHRASES = [
    "save as", "save it as", "download as", "export as", "generate a report",
    "generate report", "create a report", "as a pdf", "as a doc", "as docx",
    "in pdf", "to pdf", "downloadable", "make a report", "give me a document",
    "i want a report", "send me the report",
]
_NEGATION_RE = re.compile(r"\b(do not|don'?t|no need to|without|skip|not? (a )?(export|download|report))\b", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z\-']+", (text or "").lower())


@dataclass
class ExportIntent:
    wants_export: bool
    confidence: float
    matched: list[str] = field(default_factory=list)
    negated: bool = False


def detect_export_intent(message: str) -> ExportIntent:
    """Robust export-intent detection: verb+object proximity + phrases, negation-aware.

    More robust than a flat keyword regex: an export VERB must co-occur with an
    export OBJECT (within a short window) OR a known export PHRASE must appear.
    Negation ("don't export", "no report needed") suppresses the intent.
    """
    text = (message or "").lower().strip()
    if not text:
        return ExportIntent(wants_export=False, confidence=0.0)

    matched: list[str] = []
    # Phrase hits are high-confidence.
    for ph in _EXPORT_PHRASES:
        if ph in text:
            matched.append(ph)

    # Verb+object co-occurrence within a 4-token window.
    toks = _tokens(text)
    verb_obj_hit = False
    for i, tok in enumerate(toks):
        if tok in _EXPORT_VERBS:
            window = toks[i + 1 : i + 5]
            obj = next((w for w in window if w in _EXPORT_OBJECTS), None)
            if obj:
                verb_obj_hit = True
                matched.append(f"{tok}+{obj}")

    negated = bool(_NEGATION_RE.search(text))

    confidence = 0.0
    if matched:
        confidence = min(1.0, 0.55 + 0.2 * len(matched))
    if verb_obj_hit and confidence < 0.75:
        confidence = 0.75
    if negated:
        confidence *= 0.2

    wants_export = confidence >= 0.5 and not negated
    return ExportIntent(
        wants_export=wants_export,
        confidence=round(confidence, 2),
        matched=matched,
        negated=negated,
    )


# ── Deep-mode adaptive wall-clock budget ─────────────────────────────────────

def adaptive_wall_budget(
    message: str,
    *,
    base_seconds: float = 55.0,
    min_seconds: float = 45.0,
    max_seconds: float = 300.0,
    user_max: float | None = None,
) -> float:
    """Query-adaptive Deep-mode budget instead of a fixed cap.

    Scales the base budget by query complexity: governance/comparative/numeric
    and long multi-entity queries earn more wall-clock time, simple ones less.
    Honors an explicit user_max ceiling if provided.
    """
    c = classify_query_complexity(message)
    multiplier = 1.0
    if c.signals.get("governance"):
        multiplier += 0.9
    if c.signals.get("comparative"):
        multiplier += 0.7
    if c.signals.get("numeric"):
        multiplier += 0.5
    if c.signals.get("multi_entity"):
        multiplier += 0.4
    if c.signals.get("long_query"):
        multiplier += 0.3
    budget = base_seconds * multiplier
    budget = max(min_seconds, min(max_seconds, budget))
    if user_max is not None and user_max > 0:
        budget = min(budget, float(user_max))
    return round(budget, 1)


def reflection_rounds_for_budget(
    total_budget_s: float,
    elapsed_s: float,
    *,
    per_round_s: float = 30.0,
    max_rounds: int = 3,
) -> int:
    """How many reflection rounds (0-3) the remaining budget permits."""
    remaining = total_budget_s - elapsed_s
    if remaining <= per_round_s:
        return 0
    rounds = int(remaining // per_round_s)
    return max(0, min(max_rounds, rounds))

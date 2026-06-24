"""Story archetype classification + grounded-title anchoring.

The accuracy gate's headline check (``content_accuracy.ungrounded_headline_numbers``)
is numbers-only: it flags hard stats in a title that no sourced evidence backs.
That is necessary but not sufficient — it *rewards* vague, number-free titles. A
real audit produced:

    "TCS Q4 FY25: revenue, margins and dividend keep investor focus on FY26 demand"

which carries no anchor at all and sailed through free. Separately, some material
events have NO numbers ("Auditor resigns", "SEBI bars promoter") and must still
earn a strong, grounded headline.

This module adds a rule-based layer (mirroring the style of ``filing_triage.py``):

  - ``classify_archetype(target, content_type, text)`` -> one of
    {earnings, personnel, regulatory, ma, rating, trend, company}. Pure regex.
  - ``title_anchor_ok(title, archetype, grounded_text)`` -> (ok, reason_code).
    A title must carry a GROUNDED specific anchor of its archetype's type, or it
    is rejected with a short reason_code.

No IO, no LLM. The editorial gate calls these; everything is unit-testable.
"""

from __future__ import annotations

import re

from finagent.content.content_accuracy import (
    _FY_QUARTER_RE,
    ungrounded_headline_numbers,
)

# ── Archetype signal patterns (order matters: most specific first) ───────────

# Personnel: a key role + a movement verb.
_PERSONNEL_RE = re.compile(
    r"\b(auditor|cfo|chief financial officer|ceo|chief executive|managing director|"
    r"\bmd\b|chairman|chairperson|company secretary|director)\b.{0,60}"
    r"\b(resign|resigned|steps? down|stepped down|quits?|quit|exits?|exited|"
    r"appointed|appoint|named|joins?|joined|elevat)\b",
    re.I | re.S,
)
_PERSONNEL_RE_REV = re.compile(
    r"\b(resign|resigned|steps? down|stepped down|quits?|quit|appointed|named|"
    r"joins?|joined|elevat)\b.{0,60}"
    r"\b(auditor|cfo|ceo|managing director|\bmd\b|chairman|chairperson|"
    r"company secretary|director)\b",
    re.I | re.S,
)

_REGULATORY_RE = re.compile(
    r"\b(sebi|rbi|nse|bse|mca|nclt|nclat)\b.{0,80}"
    r"\b(order|penalt|fine|notice|adjudicat|show cause|probe|investigat|bar(?:s|red)?|"
    r"direct|debar|settlement)\b"
    r"|\b(show cause notice|adjudication order|interim order)\b"
    r"|\b(sebi|rbi)\b.{0,40}\b(penalt|order|notice)\b",
    re.I | re.S,
)

_MA_RE = re.compile(
    r"\b(merger|merge[ds]?|acquisition|acquir|demerger|amalgamation|qip|"
    r"open offer|buyback|buy[- ]back|scheme of arrangement|takeover|"
    r"preferential allotment|stake sale|divestment)\b",
    re.I,
)

_RATING_RE = re.compile(
    r"\b(rating|ratings)\b.{0,40}\b(downgrade|upgrade|revis|reaffirm|withdraw|"
    r"placed on watch)\b"
    r"|\b(downgrade[ds]?|upgrade[ds]?)\b.{0,30}\b(rating|ratings|outlook)\b"
    r"|\bcredit rating\b",
    re.I | re.S,
)

_EARNINGS_RE = re.compile(
    r"\b(results?|earnings?|\bq[1-4]\b|\bfy\s?\d{2,4}\b|\bpat\b|revenue|profit|"
    r"net profit|ebitda|ebit\b|margins?|dividend|quarterly|annual report|"
    r"top[- ]?line|bottom[- ]?line|topline|bottomline)\b",
    re.I,
)

_TREND_RE = re.compile(
    r"\b(sector|industry|macro|macroeconomic|theme|thematic|outlook|trend|"
    r"market structure|nifty|sensex|gdp|inflation|rate cut|rate hike|"
    r"monetary policy|fii|dii|crude|commodity|rupee|usd[- ]inr|pli scheme)\b",
    re.I,
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def classify_archetype(target: str, content_type: str, text: str) -> str:
    """Classify a story into a single archetype. Pure rules, no IO.

    Returns one of: earnings, personnel, regulatory, ma, rating, trend, company.

    `content_type` is the operator/pipeline label ("earnings", "sebi", "trend",
    "company", "manual"); it nudges but never overrides a strong textual signal.
    """
    blob = _norm(" ".join(str(part or "") for part in (target, content_type, text)))
    ct = _norm(content_type)

    if not blob:
        return "company"

    # Most-specific, governance-/event-driven signals win over generic earnings.
    if _PERSONNEL_RE.search(blob) or _PERSONNEL_RE_REV.search(blob):
        return "personnel"
    if _REGULATORY_RE.search(blob) or ct == "sebi":
        # "sebi" content_type is an explicit regulatory routing hint.
        return "regulatory"
    if _MA_RE.search(blob):
        return "ma"
    if _RATING_RE.search(blob):
        return "rating"
    if _EARNINGS_RE.search(blob) or ct == "earnings":
        return "earnings"
    if _TREND_RE.search(blob) or ct == "trend":
        return "trend"
    return "company"


# ── Title anchoring ──────────────────────────────────────────────────────────

# A "number token" in the title — any digit run, OR a money/percent unit
# attached to a figure. We also accept bare digits so "14%" or "Rs 1,240 cr"
# count, while a year like FY25 is handled by content_accuracy's trivia filter.
_TITLE_NUMBER_RE = re.compile(r"\d")

_PERSONNEL_ROLE_RE = re.compile(
    r"\b(ceo|cfo|chief executive|chief financial officer|managing director|\bmd\b|"
    r"chairman|chairperson|auditor|director|company secretary)\b",
    re.I,
)
_PERSONNEL_ACTION_RE = re.compile(
    r"\b(resign|resigned|resigns|steps? down|stepped down|quits?|quit|exits?|exited|"
    r"appointed|appoint|named|joins?|joined|elevated)\b",
    re.I,
)

_REGULATOR_TOKEN_RE = re.compile(r"\b(sebi|rbi|nse|bse|mca|nclt|nclat)\b", re.I)
_REGULATOR_ACTION_RE = re.compile(
    r"\b(order|orders|ordered|bars?|barred|penalt(?:y|ies)|fine[ds]?|fines|notice|"
    r"probe|investigat|directs?|directed|debars?|settlement|show cause|adjudicat)\b",
    re.I,
)

# Words that, ALONE, do not make a title concrete — adjectives / hedges / abstract
# nouns. A trend/company title built only from these (plus stopwords) is rejected.
_VAGUE_WORDS = frozenset({
    "evolving", "robust", "strong", "stronger", "strongest", "landscape", "focus",
    "outlook", "resilient", "resilience", "momentum", "positive", "negative",
    "growth", "weak", "weaker", "soft", "softer", "healthy", "stable", "steady",
    "improving", "improved", "rising", "falling", "mixed", "dynamic", "changing",
    "shifting", "emerging", "promising", "challenging", "uncertain", "volatile",
    "remains", "remain", "keeps", "keep", "stays", "stay", "amid", "amidst",
    "ahead", "story", "narrative", "demand", "supply", "sentiment", "trends",
    "trend", "themes", "theme", "investor", "investors", "market", "markets",
    "sector", "outlooks", "performance", "developments", "development", "update",
    "updates", "context", "data", "the", "a", "an", "and", "or", "as", "to",
    "in", "on", "of", "for", "with", "keeps", "continue", "continues",
})

# Concrete-noun cues: a money/percent figure, a quarter/FY tag, or an uppercase
# named entity / ticker token signal that the title carries a real subject.
_CONCRETE_TOKEN_RE = re.compile(
    r"[₹$%]|\brs\b|\bcr\b|\bcrore\b|\blakh\b|\bbn\b|\bbillion\b|\bbps\b|"
    r"\bq[1-4]\b|\bfy\s?\d{2,4}\b|\d",
    re.I,
)
_PROPER_NAME_RE = re.compile(r"\b[A-Z][A-Za-z&.\-]{1,}\b")


def _title_has_number(title: str) -> bool:
    """True only for a REAL stat digit — FY/quarter period tags don't count.

    A title whose only digits are period tags ("Q4 FY25", "FY26") carries no
    anchor, which is precisely the audit failure this layer exists to catch.
    """
    stripped = _FY_QUARTER_RE.sub(" ", title or "")
    # Also drop bare quarter/fiscal tokens with attached short year (Q4, FY26).
    stripped = re.sub(r"\b(?:q[1-4]|h[12]|fy)\s?\d{0,4}\b", " ", stripped, flags=re.I)
    return bool(_TITLE_NUMBER_RE.search(stripped))


def _grounded_name_tokens(grounded_text: str) -> set[str]:
    return {tok.lower() for tok in re.findall(r"[A-Za-z][A-Za-z&.\-]{2,}", grounded_text or "")}


def title_anchor_ok(title: str, archetype: str, grounded_text: str) -> tuple[bool, str]:
    """Whether a title carries a GROUNDED, archetype-appropriate specific anchor.

    Returns ``(ok, reason_code)``. ``reason_code`` is "" when ok, otherwise a
    short machine-readable failure code (e.g. "title_no_number",
    "title_ungrounded_number", "personnel_no_action", "vague_title").

    `grounded_text` should be the concatenation of sourced layers only — evidence
    claims + timeline + any supplied source material — NOT the model's free prose.
    """
    raw = (title or "").strip()
    arch = (archetype or "").strip().lower()
    if not raw:
        return False, "empty_title"

    # ── number-anchored archetypes ───────────────────────────────────────────
    if arch in {"earnings", "rating", "ma"}:
        if not _title_has_number(raw):
            return False, "title_no_number"
        ungrounded = ungrounded_headline_numbers(raw, grounded_text)
        if ungrounded:
            return False, "title_ungrounded_number"
        return True, ""

    # ── personnel: role/name + action verb, name grounded ────────────────────
    if arch == "personnel":
        has_action = bool(_PERSONNEL_ACTION_RE.search(raw))
        if not has_action:
            return False, "personnel_no_action"
        if _PERSONNEL_ROLE_RE.search(raw):
            return True, ""
        # No explicit role keyword — fall back to a proper-name token that is
        # actually present in the grounded evidence (not invented in the title).
        grounded_names = _grounded_name_tokens(grounded_text)
        for name in _PROPER_NAME_RE.findall(raw):
            if name.lower() in grounded_names:
                return True, ""
        return False, "personnel_no_grounded_subject"

    # ── regulatory: regulator token + action, both grounded ──────────────────
    if arch == "regulatory":
        reg = _REGULATOR_TOKEN_RE.search(raw)
        if not reg:
            return False, "regulatory_no_regulator"
        if not _REGULATOR_ACTION_RE.search(raw):
            return False, "regulatory_no_action"
        grounded_low = _norm(grounded_text)
        if reg.group(0).lower() not in grounded_low:
            return False, "regulatory_ungrounded"
        return True, ""

    # ── trend / company: entity/topic + a concrete noun, reject all-vague ─────
    if arch in {"trend", "company"}:
        words = re.findall(r"[A-Za-z0-9₹$%&.\-]+", raw)
        meaningful = [w for w in words if w.lower() not in _VAGUE_WORDS and len(w) > 1]
        if not meaningful:
            return False, "vague_title"
        # Require at least one concrete cue: a number/period/money token OR a
        # grounded proper-name subject that is not itself a vague word.
        if _CONCRETE_TOKEN_RE.search(raw):
            return True, ""
        grounded_names = _grounded_name_tokens(grounded_text)
        for name in _PROPER_NAME_RE.findall(raw):
            low = name.lower()
            if low in _VAGUE_WORDS:
                continue
            if low in grounded_names:
                return True, ""
        return False, "vague_title"

    # Unknown archetype → do not block (caller should fall back to numbers-only).
    return True, ""

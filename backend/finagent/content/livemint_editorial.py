"""LiveMint-style editorial quality scoring for generated articles.

Scores an article on four journalism dimensions and decides whether it reads
like premium financial journalism (LiveMint/Mint) or like a rigid SEO template.
Articles failing the gate trigger a guided revision pass.

Dimensions (0-100 each):
  - headline_punch:    60-100 char headline anchored on a specific data point.
  - narrative_flow:    continuous prose, not isolated bullet/section dumps.
  - data_integration:  numbers embedded inside narrative sentences, not just
                       in metric/table blocks.
  - journalistic_cadence: inverted-pyramid lede + market context + analyst voice,
                       with varied sentence rhythm.

Pure functions only (no LLM / no IO) → unit-testable. The revision guidance is
a list of concrete instructions an LLM reviser can act on.
"""

from __future__ import annotations

import re
from typing import Any

# Gate: below this composite, the article must be revised before publish.
PASS_THRESHOLD = 70.0

_NUM_RE = re.compile(r"(?<![\w])[₹$]?\s?-?\d[\d,]*\.?\d*\s?(%|bps|bn|cr|crore|lakh|trillion|x|pp)?", re.IGNORECASE)
_HEDGE_RE = re.compile(r"\b(comprehensive|robust|in this article|we will explore|leverage|delve|seamless)\b", re.IGNORECASE)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p for p in parts if len(p.split()) >= 3]


def _count_numbers(text: str) -> int:
    return len(_NUM_RE.findall(text or ""))


def _word_count(text: str) -> int:
    return len((text or "").split())


def score_headline(title: str) -> dict[str, Any]:
    title = (title or "").strip()
    n = len(title)
    reasons: list[str] = []
    score = 0.0
    # Length band 60-100 is the LiveMint sweet spot.
    if 60 <= n <= 100:
        score += 45
    elif 45 <= n < 60 or 100 < n <= 115:
        score += 28
        reasons.append("headline length outside 60-100 char sweet spot")
    else:
        reasons.append(f"headline {n} chars — far from 60-100 target")
    # Anchored on a concrete data point / proper noun.
    if _count_numbers(title) > 0:
        score += 30
    else:
        reasons.append("headline lacks a specific number/data anchor")
    # Specificity: has a capitalised entity beyond the first word.
    if re.search(r"\b[A-Z][a-zA-Z]{2,}", title[1:]):
        score += 15
    else:
        reasons.append("headline lacks a specific named entity")
    # Penalise generic SEO filler.
    if _HEDGE_RE.search(title):
        score -= 20
        reasons.append("headline uses generic SEO filler")
    return {"score": max(0.0, min(100.0, score)), "reasons": reasons}


def score_narrative_flow(article: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    score = 0.0
    lede = article.get("narrative_lede") or ""
    market = article.get("market_context") or ""
    commentary = article.get("analyst_commentary") or ""

    if _word_count(lede) >= 35:
        score += 25
    else:
        reasons.append("missing or thin narrative_lede (need >=35 words)")
    if _word_count(market) >= 40:
        score += 20
    else:
        reasons.append("missing or thin market_context")
    if _word_count(commentary) >= 40:
        score += 20
    else:
        reasons.append("missing or thin analyst_commentary")

    # Sections should be prose-led, not bullet-dominated.
    sections = article.get("sections") or []
    if sections:
        para_words = sum(_word_count(p) for s in sections for p in (s.get("paragraphs") or []))
        bullet_count = sum(len(s.get("bullets") or []) for s in sections)
        avg_paras = para_words / max(1, len(sections))
        if avg_paras >= 60:
            score += 25
        elif avg_paras >= 35:
            score += 14
            reasons.append("sections are thin on prose")
        else:
            reasons.append("sections are bullet-heavy, not narrative prose")
        if bullet_count > para_words / 25:
            score -= 8
            reasons.append("too many bullets relative to prose")
    else:
        reasons.append("no body sections")
    return {"score": max(0.0, min(100.0, score)), "reasons": reasons}


def score_data_integration(article: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    # Numbers must appear INSIDE narrative prose, not only in metric blocks.
    prose = " ".join(
        [article.get("narrative_lede") or "", article.get("market_context") or "",
         article.get("analyst_commentary") or ""]
        + [p for s in (article.get("sections") or []) for p in (s.get("paragraphs") or [])]
    )
    prose_numbers = _count_numbers(prose)
    prose_words = max(1, _word_count(prose))
    density = prose_numbers / (prose_words / 100.0)  # numbers per 100 words
    score = 0.0
    if density >= 2.5:
        score += 60
    elif density >= 1.2:
        score += 38
        reasons.append("data density in prose is moderate; weave in more hard numbers")
    else:
        reasons.append("prose lacks embedded numbers — data sits only in blocks")
    # Reward presence of at least one supporting table/metric set too.
    if article.get("tables"):
        score += 20
    if article.get("metrics"):
        score += 20
    return {"score": max(0.0, min(100.0, score)), "reasons": reasons}


def score_cadence(article: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    score = 0.0
    lede = article.get("narrative_lede") or ""
    # Inverted pyramid: lede must front-load a number.
    lede_sents = _sentences(lede)
    if lede_sents and _count_numbers(lede_sents[0]) > 0:
        score += 30
    else:
        reasons.append("lede does not front-load a hard number (inverted pyramid)")
    # Sentence-length variety across the whole body.
    body = " ".join([lede, article.get("market_context") or "", article.get("analyst_commentary") or ""]
                    + [p for s in (article.get("sections") or []) for p in (s.get("paragraphs") or [])])
    lengths = [len(s.split()) for s in _sentences(body)]
    if len(lengths) >= 6:
        score += 20
        avg = sum(lengths) / len(lengths)
        var = sum((l - avg) ** 2 for l in lengths) / len(lengths)
        if var >= 25:
            score += 30
        else:
            score += 12
            reasons.append("sentence rhythm is monotonous — vary short and long sentences")
    else:
        reasons.append("body too short for journalistic cadence")
    # Penalise SEO filler anywhere in body.
    if _HEDGE_RE.search(body):
        score -= 15
        reasons.append("body contains generic filler phrases")
    else:
        score += 20
    return {"score": max(0.0, min(100.0, score)), "reasons": reasons}


def evaluate_livemint_quality(article: dict[str, Any]) -> dict[str, Any]:
    """Composite LiveMint editorial score with per-dimension breakdown + guidance."""
    h = score_headline(article.get("title") or article.get("hero_title") or "")
    nf = score_narrative_flow(article)
    di = score_data_integration(article)
    ca = score_cadence(article)

    dims = {
        "headline_punch": h,
        "narrative_flow": nf,
        "data_integration": di,
        "journalistic_cadence": ca,
    }
    weights = {"headline_punch": 0.25, "narrative_flow": 0.30, "data_integration": 0.25, "journalistic_cadence": 0.20}
    composite = round(sum(dims[k]["score"] * w for k, w in weights.items()), 1)
    guidance: list[str] = []
    for name, d in dims.items():
        for r in d["reasons"]:
            guidance.append(f"[{name}] {r}")
    return {
        "score": composite,
        "passed": composite >= PASS_THRESHOLD,
        "dimensions": {k: round(v["score"], 1) for k, v in dims.items()},
        "revision_guidance": guidance,
    }

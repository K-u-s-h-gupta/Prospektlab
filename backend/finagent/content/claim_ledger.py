"""Numeric claim ledger — anti-hallucination grounding for generated articles.

Builds a ledger of every number that appears in the SOURCED evidence layers
(evidence pack + supplied source material), then lets the gate check that every
number in the article's prose traces back to that ledger. A number in the body
with no ledger entry is a candidate hallucination.

Pure: no IO, no LLM, no network. The pipeline imports `build_ledger` +
`verify_article_numbers`; everything here is unit-testable in isolation.
"""
from __future__ import annotations

import re
from typing import Any

from finagent.content.content_accuracy import (
    _FY_QUARTER_RE,
    _TRIVIAL_NUMBERS,
    extract_number_tokens,
)

# A figure plus an optional trailing unit. Captures "Rs 42,310 crore", "8.6%",
# "USD 3.8 billion", "40 bps", "13.4x", "3,29,900".
_UNIT = r"(?:%|pct|bps|bp|pp|x|cr|crore|lakh|lakhs|bn|billion|mn|million|trillion)"
_FIGURE_RE = re.compile(
    r"(?:(?:rs|inr|usd|\$|₹)\s*)?"          # optional currency lead
    r"(\d[\d,]*\.?\d*)"                       # the figure
    r"\s*(" + _UNIT + r")?",                  # optional unit
    re.I,
)


def _canon(raw_number: str) -> str | None:
    """Canonical numeric token (commas stripped, trailing .0 dropped)."""
    try:
        val = float(raw_number.replace(",", ""))
    except ValueError:
        return None
    return "%g" % val


def _iter_sourced_strings(evidence_pack: dict[str, Any], source_markdown: str):
    if source_markdown:
        yield source_markdown
    if not isinstance(evidence_pack, dict):
        return
    for key in ("sources_used", "official_document_evidence", "trusted_supporting_sources",
                "research_pipeline_context", "company_context"):
        for entry in evidence_pack.get(key) or []:
            if isinstance(entry, dict):
                yield " ".join(str(entry.get(k) or "") for k in ("title", "snippet", "summary"))
    for claim in evidence_pack.get("evidence_claims") or []:
        if isinstance(claim, dict):
            yield str(claim.get("claim") or "")
    for tbl in evidence_pack.get("attachment_tables") or []:
        if isinstance(tbl, dict):
            yield " ".join(str(c) for row in (tbl.get("rows") or []) for c in row)


def build_ledger(evidence_pack: dict[str, Any], source_markdown: str = "") -> list[dict[str, Any]]:
    """Extract every grounded numeric claim into typed ledger entries.

    Each entry: {value, raw, unit, label, source_title, source_url}.
    `label` is a short context window around the figure so a human can audit it.
    """
    ledger: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _harvest(text: str, source_title: str = "", source_url: str = "") -> None:
        if not text:
            return
        for m in _FIGURE_RE.finditer(text):
            canon = _canon(m.group(1))
            if canon is None or canon in _TRIVIAL_NUMBERS:
                continue
            unit = (m.group(2) or "").lower() or None
            start = max(0, m.start() - 32)
            label = " ".join(text[start:m.end() + 8].split())
            key = (canon, unit or "")
            if key in seen:
                continue
            seen.add(key)
            ledger.append({
                "value": float(m.group(1).replace(",", "")),
                "raw": m.group(0).strip(),
                "unit": unit,
                "label": label,
                "source_title": source_title,
                "source_url": source_url,
            })

    # source_markdown first (richest), then structured evidence entries.
    if source_markdown:
        _harvest(source_markdown, "supplied source material")
    if isinstance(evidence_pack, dict):
        for entry in evidence_pack.get("sources_used") or []:
            if isinstance(entry, dict):
                _harvest(
                    " ".join(str(entry.get(k) or "") for k in ("title", "snippet", "summary")),
                    str(entry.get("title") or ""),
                    str(entry.get("url") or ""),
                )
        for claim in evidence_pack.get("evidence_claims") or []:
            if isinstance(claim, dict):
                _harvest(str(claim.get("claim") or ""),
                         str(claim.get("source_title") or ""),
                         str(claim.get("source_url") or ""))
        for tbl in evidence_pack.get("attachment_tables") or []:
            if isinstance(tbl, dict):
                _harvest(" ".join(str(c) for row in (tbl.get("rows") or []) for c in row),
                         str(tbl.get("title") or "attachment table"))
    return ledger


def ledger_number_set(ledger: list[dict[str, Any]]) -> set[str]:
    """Canonical numeric tokens present in the ledger."""
    out: set[str] = set()
    for entry in ledger:
        canon = _canon(str(entry.get("value", "")))
        if canon:
            out.add(canon)
    return out


def verify_article_numbers(article_text: str, ledger: list[dict[str, Any]]) -> list[str]:
    """Numbers in the article prose with NO grounding in the ledger.

    Trivial numbers (0-4) and year/FY/quarter tokens are ignored. A non-empty
    result means the article asserts figures no source backs — the hard-gate
    signal for a likely hallucination.
    """
    cleaned = _FY_QUARTER_RE.sub(" ", article_text or "")
    cleaned = re.sub(r"\b(?:q[1-4]|h[12]|fy)\s?\d{0,4}\b", " ", cleaned, flags=re.I)
    article_nums = extract_number_tokens(cleaned) - _TRIVIAL_NUMBERS
    grounded = ledger_number_set(ledger)
    return sorted(n for n in article_nums if n not in grounded)


def ledger_coverage(article_text: str, ledger: list[dict[str, Any]]) -> dict[str, Any]:
    """Grounded vs ungrounded number counts for the article."""
    cleaned = _FY_QUARTER_RE.sub(" ", article_text or "")
    cleaned = re.sub(r"\b(?:q[1-4]|h[12]|fy)\s?\d{0,4}\b", " ", cleaned, flags=re.I)
    article_nums = extract_number_tokens(cleaned) - _TRIVIAL_NUMBERS
    grounded_set = ledger_number_set(ledger)
    grounded = sum(1 for n in article_nums if n in grounded_set)
    ungrounded = len(article_nums) - grounded
    total = len(article_nums)
    return {
        "grounded": grounded,
        "ungrounded": ungrounded,
        "ratio": round(grounded / total, 3) if total else 1.0,
    }

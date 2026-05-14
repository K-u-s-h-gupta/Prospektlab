"""Cross-source numeric conflict detection.

The FinAgent spec calls for explicit [CONFLICT] markers when two sources disagree
on a material number (revenue, market cap, EPS, headcount...). This module
extracts those numbers with regexes, normalises them to a common unit, and flags
any pair that diverges by more than a configurable tolerance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from finagent.tools.web.scraper import ScrapedDoc

# Numeric token: $1,234.5, 1.2 billion, 3.4B, 12%, etc.
_NUMBER_TOKEN = r"\$?[0-9]{1,3}(?:[\,\.][0-9]{3})*(?:\.[0-9]+)?"
_SCALE_WORD = r"(?:trillion|billion|million|thousand|[KMBT])"
# Lookbehind / lookahead prevent the regex from greedily grabbing partial digits
# out of larger numbers (e.g. picking up "4" from "2024" or "202" from "2024").
_NUMERIC = re.compile(
    rf"(?<![0-9.])({_NUMBER_TOKEN})(?![0-9])\s*({_SCALE_WORD})?",
    re.IGNORECASE,
)

_SCALE_FACTORS = {
    "thousand": 1_000.0,
    "k": 1_000.0,
    "million": 1_000_000.0,
    "m": 1_000_000.0,
    "billion": 1_000_000_000.0,
    "b": 1_000_000_000.0,
    "trillion": 1_000_000_000_000.0,
    "t": 1_000_000_000_000.0,
}

# Each metric is a regex that, when matched, marks the surrounding number as the
# value. We capture a 60-char window around the number to allow context display.
_METRIC_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "revenue": [
        re.compile(r"\brevenue[s]?\b", re.IGNORECASE),
        re.compile(r"\btotal\s+revenue\b", re.IGNORECASE),
        re.compile(r"\bnet\s+sales\b", re.IGNORECASE),
    ],
    "market_cap": [
        re.compile(r"\bmarket\s*cap(?:italization)?\b", re.IGNORECASE),
        re.compile(r"\bvaluation\b", re.IGNORECASE),
    ],
    "net_income": [
        re.compile(r"\bnet\s+income\b", re.IGNORECASE),
        re.compile(r"\bnet\s+earnings\b", re.IGNORECASE),
    ],
    "eps": [
        re.compile(r"\b(?:diluted\s+)?eps\b", re.IGNORECASE),
        re.compile(r"\bearnings\s+per\s+share\b", re.IGNORECASE),
    ],
    "employees": [
        re.compile(r"\bemployees?\b", re.IGNORECASE),
        re.compile(r"\bheadcount\b", re.IGNORECASE),
        re.compile(r"\bworkforce\b", re.IGNORECASE),
    ],
}


@dataclass
class MetricObservation:
    metric: str
    value: float
    raw: str
    context: str
    url: str
    domain: str
    tier: int


@dataclass
class ConflictReport:
    metric: str
    observations: list[MetricObservation]
    spread_pct: float  # max-min / max * 100
    note: str = ""


@dataclass
class _CandidateNumber:
    value: float
    raw: str
    span: tuple[int, int]
    has_scale: bool


def _parse_number(raw: str, scale: str | None) -> float | None:
    cleaned = raw.replace("$", "").replace(",", "").strip()
    try:
        v = float(cleaned)
    except ValueError:
        return None
    if scale:
        factor = _SCALE_FACTORS.get(scale.lower())
        if factor is not None:
            # Single-letter scales (K, M, B, T) are unambiguous; a 1-3 digit number
            # paired with one of those almost always means scaled. Word scales
            # (million / billion) always mean scaled.
            v *= factor
    return v


def _candidate_numbers(text: str) -> list[_CandidateNumber]:
    out: list[_CandidateNumber] = []
    for match in _NUMERIC.finditer(text):
        raw = match.group(1)
        scale = match.group(2)
        val = _parse_number(raw, scale)
        if val is None or val == 0:
            continue
        out.append(
            _CandidateNumber(
                value=val,
                raw=match.group(0).strip(),
                span=match.span(),
                has_scale=bool(scale),
            )
        )
    return out


def _score_candidate(cand: _CandidateNumber, keyword_end: int, metric: str) -> float:
    distance = min(abs(cand.span[0] - keyword_end), abs(cand.span[1] - keyword_end))
    if distance > 120:
        return -1.0
    # Distance penalty (closer is better, but flat past 60 chars)
    score = 1000.0 - min(distance, 120) * 5
    # Prefer numbers AFTER the keyword ("revenue was 391.04 billion")
    if cand.span[0] >= keyword_end:
        score += 250
    # Explicit scale words are huge — almost always the right number
    if cand.has_scale:
        score += 800
    # Year heuristic: 4-digit, no scale, in 1900-2099 -> almost certainly a date
    if not cand.has_scale and 1900 <= cand.value <= 2099 and float(int(cand.value)) == cand.value:
        score -= 1500
    # Metric-specific sanity bands (very loose — only used to break ties)
    if metric in ("revenue", "market_cap", "net_income") and not cand.has_scale and cand.value < 1_000_000:
        # An unscaled "revenue ... 12" is almost never a real revenue value
        score -= 400
    if metric == "employees" and (cand.value < 50 or cand.value > 5_000_000):
        score -= 200
    if metric == "eps" and (cand.value < 0.01 or cand.value > 100):
        score -= 200
    return score


def _extract_for_doc(doc: ScrapedDoc) -> list[MetricObservation]:
    text = (doc.excerpt or "")[:4000]
    if not text:
        return []
    numbers = _candidate_numbers(text)
    if not numbers:
        return []

    obs: list[MetricObservation] = []
    for metric, patterns in _METRIC_PATTERNS.items():
        best_for_metric: tuple[_CandidateNumber, int, int] | None = None
        best_score = 0.0
        for pat in patterns:
            for m in pat.finditer(text):
                keyword_end = m.end()
                for n in numbers:
                    score = _score_candidate(n, keyword_end, metric)
                    if score > best_score:
                        best_score = score
                        best_for_metric = (n, m.start(), m.end())
        if best_for_metric is None:
            continue
        n, anchor_start, anchor_end = best_for_metric
        start = max(0, min(anchor_start, n.span[0]) - 20)
        end = min(len(text), max(anchor_end, n.span[1]) + 20)
        obs.append(
            MetricObservation(
                metric=metric,
                value=n.value,
                raw=n.raw,
                context=text[start:end].replace("\n", " ").strip(),
                url=doc.final_url,
                domain=doc.domain,
                tier=doc.tier,
            )
        )
    return obs


def extract_metrics(docs: list[ScrapedDoc]) -> list[MetricObservation]:
    out: list[MetricObservation] = []
    for d in docs:
        out.extend(_extract_for_doc(d))
    return out


def detect_conflicts(docs: list[ScrapedDoc], *, tolerance_pct: float = 5.0) -> list[ConflictReport]:
    observations = extract_metrics(docs)
    by_metric: dict[str, list[MetricObservation]] = {}
    for o in observations:
        by_metric.setdefault(o.metric, []).append(o)

    reports: list[ConflictReport] = []
    for metric, obs in by_metric.items():
        # Dedup by domain to avoid same-source noise
        seen_domains: dict[str, MetricObservation] = {}
        for o in obs:
            prev = seen_domains.get(o.domain)
            # Keep the one with the higher-tier (lower number) authority
            if prev is None or o.tier < prev.tier:
                seen_domains[o.domain] = o
        unique = list(seen_domains.values())
        if len(unique) < 2:
            continue
        values = [o.value for o in unique]
        hi = max(values)
        lo = min(values)
        if hi == 0:
            continue
        spread = (hi - lo) / hi * 100.0
        if spread >= tolerance_pct:
            note = (
                f"{len(unique)} sources disagree on {metric}: "
                f"min={lo:,.0f}, max={hi:,.0f}, spread={spread:.1f}%."
            )
            reports.append(ConflictReport(metric=metric, observations=unique, spread_pct=spread, note=note))
    reports.sort(key=lambda r: r.spread_pct, reverse=True)
    return reports

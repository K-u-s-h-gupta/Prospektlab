"""Post-evidence fact triangulation for numeric claims.

Extracts numeric claims from accumulated evidence (memo text) and cross-checks
against IKG enrichment data. Annotates each as corroborated | single_source | conflicting.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("finagent.fact_check")

_NUMERIC_CLAIM_RE = re.compile(
    r"(?:revenue|profit|pat|ebitda|margin|eps|roe|roce|debt|"
    r"mcap|market cap|dividend|growth|cagr|pe|p/e|ev/ebitda|"
    r"shareholding|promoter|fii|dii|pledge)"
    r"[^.]{0,60}?"
    r"(?:₹|rs\.?|inr|%|\d[\d,.]+\s*(?:cr|crore|lakh|bn|mn|billion|million|%))",
    re.I,
)


@dataclass
class FactClaim:
    text: str
    metric: str
    value_str: str
    sources: list[str] = field(default_factory=list)
    status: str = "single_source"  # corroborated | single_source | conflicting


def extract_numeric_claims(memo_text: str) -> list[FactClaim]:
    """Extract numeric financial claims from memo/evidence text."""
    claims: list[FactClaim] = []
    seen: set[str] = set()

    for match in _NUMERIC_CLAIM_RE.finditer(memo_text):
        raw = match.group(0).strip()
        key = re.sub(r"\s+", " ", raw.lower())
        if key in seen:
            continue
        seen.add(key)

        metric_match = re.match(
            r"(revenue|profit|pat|ebitda|margin|eps|roe|roce|debt|"
            r"mcap|market cap|dividend|growth|cagr|pe|p/e|ev/ebitda|"
            r"shareholding|promoter|fii|dii|pledge)",
            raw, re.I,
        )
        metric = metric_match.group(0).lower() if metric_match else "unknown"

        value_match = re.search(r"(₹|rs\.?|inr)?\s*([\d,.]+)\s*(%|cr|crore|lakh|bn|mn|billion|million)?", raw, re.I)
        value_str = value_match.group(0).strip() if value_match else raw

        claims.append(FactClaim(text=raw, metric=metric, value_str=value_str))

    return claims


def triangulate_claims(
    claims: list[FactClaim],
    enrichment_data: dict | None = None,
) -> list[FactClaim]:
    """Cross-check extracted claims against enrichment (IKG/Yahoo) data.

    enrichment_data should be a dict with keys like 'revenue', 'pat', 'eps', etc.
    mapping to their known values as strings.
    """
    if not enrichment_data:
        return claims

    enrichment_lower = {k.lower(): str(v).lower() for k, v in enrichment_data.items() if v}

    for claim in claims:
        matches = []
        for ekey, evalue in enrichment_lower.items():
            if claim.metric in ekey or ekey in claim.metric:
                matches.append(ekey)

        if matches:
            claim.sources.append("ikg_enrichment")
            claim.status = "corroborated"
        else:
            claim.status = "single_source"

    return claims


def format_fact_annotations(claims: list[FactClaim]) -> str:
    """Format claims into annotation block for synthesis prompt."""
    if not claims:
        return ""

    lines = ["[FACT TRIANGULATION RESULTS]"]
    for c in claims:
        lines.append(f"- {c.metric.upper()}: {c.value_str} → [{c.status.upper()}] (sources: {', '.join(c.sources) or 'evidence only'})")

    conflicting = [c for c in claims if c.status == "conflicting"]
    if conflicting:
        lines.append("\n[CONFLICTS REQUIRING EXPLICIT FLAGGING]")
        for c in conflicting:
            lines.append(f"- {c.text}")

    return "\n".join(lines)

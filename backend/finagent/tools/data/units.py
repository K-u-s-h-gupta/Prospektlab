"""Normalization helpers for Indian financial denominations.

The ingestion layer receives figures from NSE/BSE, media, and community pages
with mixed units. Keep all comparable company-scale amounts in INR crores.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedAmount:
    raw: str
    value: float
    unit: str
    crore: float


_NUMBER_RE = r"-?\d+(?:,\d{2,3})*(?:\.\d+)?|-?\d+(?:\.\d+)?"
_UNIT_RE = (
    r"crores?|cr\.?|lakhs?|lacs?|lakh|lac|millions?|mn\.?|m\b|"
    r"billions?|bn\.?|b\b"
)
_AMOUNT_RE = re.compile(
    rf"(?P<prefix>\b(?:rs\.?|inr|rupees?)\s*)?(?P<num>{_NUMBER_RE})\s*(?P<unit>{_UNIT_RE})",
    re.IGNORECASE,
)

_UNIT_TO_CRORE = {
    "crore": 1.0,
    "crores": 1.0,
    "cr": 1.0,
    "cr.": 1.0,
    "lakh": 0.01,
    "lakhs": 0.01,
    "lac": 0.01,
    "lacs": 0.01,
    "million": 0.1,
    "millions": 0.1,
    "mn": 0.1,
    "mn.": 0.1,
    "m": 0.1,
    "billion": 100.0,
    "billions": 100.0,
    "bn": 100.0,
    "bn.": 100.0,
    "b": 100.0,
}


def _to_float(value: str) -> float | None:
    try:
        return float(value.replace(",", ""))
    except (TypeError, ValueError):
        return None


def normalize_indian_number(text: str | None, *, default_unit: str | None = None) -> NormalizedAmount | None:
    """Return a number normalized to INR crore when a denomination is present.

    If *default_unit* is supplied, bare numbers are interpreted in that unit.
    This is useful for pages such as Screener where the column header already
    defines the value as crores.
    """

    if not text:
        return None
    raw = str(text).strip()
    match = _AMOUNT_RE.search(raw)
    if match:
        num = _to_float(match.group("num"))
        unit = match.group("unit").lower().rstrip(".")
    else:
        bare = re.search(_NUMBER_RE, raw)
        if not bare or not default_unit:
            return None
        num = _to_float(bare.group(0))
        unit = default_unit.lower().rstrip(".")
    if num is None:
        return None
    factor = _UNIT_TO_CRORE.get(unit)
    if factor is None:
        return None
    return NormalizedAmount(raw=raw, value=num, unit=unit, crore=num * factor)


def parse_number(text: str | None, *, default_unit: str | None = None) -> float | None:
    """Parse a numeric value, applying a unit if present or supplied."""

    normalized = normalize_indian_number(text, default_unit=default_unit)
    if normalized:
        return normalized.crore
    if not text:
        return None
    bare = re.search(_NUMBER_RE, str(text))
    if not bare:
        return None
    return _to_float(bare.group(0))


def normalize_financial_text_units(text: str, *, max_annotations: int = 40) -> str:
    """Annotate mixed denominations with INR crore equivalents.

    The original text is preserved; annotations make downstream agent math less
    likely to mix crore/lakh/million/billion denominators silently.
    """

    if not text:
        return text
    count = 0

    def _replace(match: re.Match[str]) -> str:
        nonlocal count
        original = match.group(0)
        if count >= max_annotations:
            return original
        normalized = normalize_indian_number(original)
        if not normalized:
            return original
        count += 1
        return f"{original} ({normalized.crore:,.2f} crore)"

    return _AMOUNT_RE.sub(_replace, text)

"""Mutual fund analytics block.

Computes:
- AUM-weighted TER (best effort via bundled lookup)
- Category breakdown (large/mid/small/debt/hybrid)
- AMC concentration
- Scheme count by type
- Exposure to top underlying stocks (placeholder — needs monthly fund holdings)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from finagent.portfolio_mirrors import PositionMirror

logger = logging.getLogger("finagent.portfolio.mf_analytics")

_MF_META_PATH = Path(__file__).resolve().parent.parent / "data" / "amfi_schemes_meta.json"


def _load_scheme_meta() -> dict[str, Any]:
    """Load bundled AMFI scheme metadata keyed by AMFI code."""
    if _MF_META_PATH.is_file():
        try:
            return json.loads(_MF_META_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _classify_mf_category(scheme_name: str, scheme_type: str = "") -> str:
    """Classify MF into broad category including metals."""
    text = (scheme_name + " " + scheme_type).lower()
    # Metals — check before generic equity/debt to avoid misclassification
    if "gold" in text or "sona" in text or "sovereign gold" in text:
        return "gold"
    if "silver" in text or "chandi" in text:
        return "silver"
    if "commodity" in text and ("metal" in text or "precious" in text):
        return "commodity_metal"
    # Debt / fixed income
    if "debt" in text or "gilt" in text or "money market" in text or "income" in text:
        return "debt"
    # Hybrid / balanced
    if "hybrid" in text or "balanced" in text or "allocation" in text or "multi asset" in text:
        return "hybrid"
    # Equity sub-categories
    if "large" in text and "cap" in text:
        return "large_cap"
    if "mid" in text and "cap" in text:
        return "mid_cap"
    if "small" in text and "cap" in text:
        return "small_cap"
    if "flexi" in text or "multi cap" in text or "multicap" in text:
        return "flexi_cap"
    if "sectoral" in text or "thematic" in text or "sector" in text:
        return "sectoral"
    if "index" in text or "nifty" in text or "sensex" in text or "etf" in text:
        return "index_etf"
    if "liquid" in text or "ultra short" in text or "overnight" in text:
        return "liquid"
    if "elss" in text or "tax saver" in text or "tax saving" in text:
        return "elss"
    if "international" in text or "overseas" in text or "global" in text or "us" in text:
        return "international"
    if "dynamic" in text or "aggressive" in text:
        return "dynamic"
    return "other"


_MF_KINDS = {"mf", "gold_mf", "silver_mf"}


def compute_mf_analytics(positions: list[PositionMirror]) -> dict[str, Any] | None:
    """Return MF analytics block. Returns None if user has no MFs.

    Includes gold/silver MF schemes in the analysis with proper categorisation.
    """
    mf_positions = [p for p in positions if p.kind in _MF_KINDS]
    if not mf_positions:
        return None

    meta = _load_scheme_meta()
    total_mf_value = sum(p.market_value for p in mf_positions if p.market_value > 0)

    amc_totals: dict[str, float] = {}
    category_totals: dict[str, float] = {}
    weighted_ter = 0.0
    scheme_types: dict[str, int] = {}

    for pos in mf_positions:
        if pos.market_value <= 0:
            continue
        weight = pos.market_value / total_mf_value if total_mf_value else 0

        scheme_meta = meta.get(pos.amfi, {}) if pos.amfi else {}
        ter = scheme_meta.get("ter", 0.0)
        amc = scheme_meta.get("amc", "Unknown")
        scheme_type = scheme_meta.get("scheme_type", "")

        weighted_ter += weight * (ter or 0.0)
        amc_totals[amc] = amc_totals.get(amc, 0.0) + pos.market_value
        cat = _classify_mf_category(pos.name or "", scheme_type)
        category_totals[cat] = category_totals.get(cat, 0.0) + pos.market_value
        scheme_types[scheme_type or cat] = scheme_types.get(scheme_type or cat, 0) + 1

    amc_concentration = {
        amc: round(val / total_mf_value * 100, 2)
        for amc, val in amc_totals.items()
    } if total_mf_value else {}

    category_breakdown = {
        cat: round(val / total_mf_value * 100, 2)
        for cat, val in category_totals.items()
    } if total_mf_value else {}

    return {
        "status": "OK",
        "total_mf_value": round(total_mf_value, 2),
        "scheme_count": len(mf_positions),
        "aum_weighted_ter_pct": round(weighted_ter, 2),
        "category_breakdown": category_breakdown,
        "amc_concentration": amc_concentration,
        "scheme_type_counts": scheme_types,
        "lookthrough_exposure": {},  # Placeholder; Phase 2 enhancement
    }

"""Portfolio Governance X-Ray — overlays the Forensic Governance Score onto a
user's holdings.

For each equity holding: resolve symbol/ISIN → CIN (IKG entity resolver) →
governance score. Aggregates into a portfolio-level governance-risk exposure
(weighted by market value) plus a list of flagged holdings.

Resilience: an entity-resolution or governance-lookup failure for ONE holding
must not break the whole overlay. Such failures are recorded in `unresolved`
so the caller can surface coverage honestly rather than silently understating
risk.
"""

from __future__ import annotations

import logging
from typing import Any

from finagent.ikg.entity_resolver import EntityLookupError, get_entity_resolver
from finagent.ikg.governance_score import (
    GovernanceLookupError,
    get_governance_scorer,
    result_to_dict,
)

logger = logging.getLogger("finagent.portfolio.governance_xray")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return n if n == n else default  # NaN guard
    except (TypeError, ValueError):
        return default


def aggregate_governance_overlay(holding_scores: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure aggregation (no DB) over per-holding governance results.

    holding_scores item shape:
      {"symbol","name","market_value","resolved": bool,
       "governance": <result_to_dict or None>}
    """
    scored = [h for h in holding_scores if h.get("resolved") and h.get("governance")]
    total_scored_value = sum(_num(h.get("market_value")) for h in scored)

    weighted_risk = 0.0
    flagged: list[dict[str, Any]] = []
    band_counts = {"LOW": 0, "MODERATE": 0, "ELEVATED": 0, "HIGH": 0}

    for h in scored:
        gov = h["governance"]
        mv = _num(h.get("market_value"))
        weight = (mv / total_scored_value) if total_scored_value > 0 else 0.0
        weighted_risk += gov["score"] * weight
        band_counts[gov.get("band", "LOW")] = band_counts.get(gov.get("band", "LOW"), 0) + 1
        high_flags = [f for f in gov.get("flags", []) if f.get("severity") == "high"]
        if gov.get("band") in ("ELEVATED", "HIGH") or high_flags:
            flagged.append({
                "symbol": h.get("symbol"),
                "name": h.get("name"),
                "cin": gov.get("cin"),
                "score": gov.get("score"),
                "band": gov.get("band"),
                "weight_pct": round(weight * 100, 2),
                "top_flags": [
                    {"code": f["code"], "severity": f["severity"], "detail": f["detail"]}
                    for f in gov.get("flags", [])[:3]
                ],
            })

    flagged.sort(key=lambda x: x["score"], reverse=True)
    total_holdings = len(holding_scores)
    resolved_count = len(scored)

    return {
        "portfolio_governance_score": round(weighted_risk, 1),
        "portfolio_governance_band": _portfolio_band(weighted_risk),
        "flagged_holdings": flagged,
        "band_distribution": band_counts,
        "coverage": {
            "holdings_total": total_holdings,
            "holdings_scored": resolved_count,
            "coverage_ratio": round(resolved_count / total_holdings, 2) if total_holdings else 0.0,
        },
    }


def _portfolio_band(score: float) -> str:
    if score < 20:
        return "LOW"
    if score < 40:
        return "MODERATE"
    if score < 60:
        return "ELEVATED"
    return "HIGH"


def compute_portfolio_governance_xray(positions: list[Any]) -> dict[str, Any]:
    """DB-backed: resolve + score each equity holding, then aggregate.

    `positions` are PositionMirror-like objects with .exchange_symbol, .isin,
    .name, .market_value, .kind attributes.
    """
    resolver = get_entity_resolver()
    scorer = get_governance_scorer()

    holding_scores: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for pos in positions:
        kind = (getattr(pos, "kind", "equity") or "equity").strip().lower()
        if kind != "equity":
            continue
        symbol = str(getattr(pos, "exchange_symbol", "") or "")
        isin = str(getattr(pos, "isin", "") or "")
        name = getattr(pos, "name", None) or symbol
        mv = _num(getattr(pos, "market_value", 0.0))

        cin: str | None = None
        reason = None
        try:
            entity = None
            if isin:
                entity = resolver.resolve_by_isin(isin)
            if entity is None and symbol:
                entity = resolver.resolve_by_ticker(symbol)
            cin = entity.cin if entity else None
            if cin is None:
                reason = "unresolved_entity"
        except EntityLookupError as exc:
            logger.warning("Entity lookup failed for %s/%s: %s", symbol, isin, exc)
            reason = "entity_lookup_error"

        gov_dict = None
        if cin:
            try:
                result = scorer.score_company(cin)
                gov_dict = result_to_dict(result) if result else None
                if gov_dict is None:
                    reason = "no_governance_data"
            except GovernanceLookupError as exc:
                logger.warning("Governance lookup failed for %s (%s): %s", name, cin, exc)
                reason = "governance_lookup_error"

        if gov_dict is not None:
            holding_scores.append({
                "symbol": symbol, "name": name, "market_value": mv,
                "resolved": True, "governance": gov_dict,
            })
        else:
            holding_scores.append({
                "symbol": symbol, "name": name, "market_value": mv,
                "resolved": False, "governance": None,
            })
            unresolved.append({"symbol": symbol, "name": name, "reason": reason})

    overlay = aggregate_governance_overlay(holding_scores)
    overlay["unresolved"] = unresolved
    return overlay

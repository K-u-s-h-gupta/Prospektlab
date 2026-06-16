"""Unit tests for portfolio governance X-Ray aggregation (pure, no DB)."""

from __future__ import annotations

from finagent.portfolio.governance_xray import aggregate_governance_overlay


def _gov(score, band, flags=None):
    return {"cin": "LX", "score": score, "band": band, "flags": flags or [], "subscores": {}, "coverage": {}}


def test_empty_portfolio():
    out = aggregate_governance_overlay([])
    assert out["portfolio_governance_score"] == 0.0
    assert out["coverage"]["coverage_ratio"] == 0.0
    assert out["flagged_holdings"] == []


def test_weighted_risk_by_market_value():
    holdings = [
        {"symbol": "A", "name": "A", "market_value": 100.0, "resolved": True, "governance": _gov(80, "HIGH")},
        {"symbol": "B", "name": "B", "market_value": 300.0, "resolved": True, "governance": _gov(0, "LOW")},
    ]
    out = aggregate_governance_overlay(holdings)
    # 80*0.25 + 0*0.75 = 20
    assert out["portfolio_governance_score"] == 20.0
    assert out["portfolio_governance_band"] == "MODERATE"


def test_flagged_holdings_surfaced_and_sorted():
    holdings = [
        {"symbol": "A", "name": "A", "market_value": 100.0, "resolved": True,
         "governance": _gov(55, "ELEVATED", [{"code": "PLEDGE_HIGH", "severity": "high", "detail": "x"}])},
        {"symbol": "B", "name": "B", "market_value": 100.0, "resolved": True,
         "governance": _gov(90, "HIGH", [{"code": "ENFORCEMENT_ACTION", "severity": "high", "detail": "y"}])},
        {"symbol": "C", "name": "C", "market_value": 100.0, "resolved": True, "governance": _gov(5, "LOW")},
    ]
    out = aggregate_governance_overlay(holdings)
    assert len(out["flagged_holdings"]) == 2
    assert out["flagged_holdings"][0]["symbol"] == "B"  # highest score first
    assert out["band_distribution"]["HIGH"] == 1
    assert out["band_distribution"]["LOW"] == 1


def test_unresolved_excluded_from_score_but_counted():
    holdings = [
        {"symbol": "A", "name": "A", "market_value": 100.0, "resolved": True, "governance": _gov(60, "ELEVATED")},
        {"symbol": "B", "name": "B", "market_value": 100.0, "resolved": False, "governance": None},
    ]
    out = aggregate_governance_overlay(holdings)
    assert out["portfolio_governance_score"] == 60.0  # only resolved holding drives score
    assert out["coverage"]["holdings_total"] == 2
    assert out["coverage"]["holdings_scored"] == 1
    assert out["coverage"]["coverage_ratio"] == 0.5


def test_high_severity_flag_surfaces_even_if_band_low():
    holdings = [
        {"symbol": "A", "name": "A", "market_value": 100.0, "resolved": True,
         "governance": _gov(15, "LOW", [{"code": "ENFORCEMENT_ACTION", "severity": "high", "detail": "z"}])},
    ]
    out = aggregate_governance_overlay(holdings)
    assert len(out["flagged_holdings"]) == 1
    assert out["flagged_holdings"][0]["symbol"] == "A"

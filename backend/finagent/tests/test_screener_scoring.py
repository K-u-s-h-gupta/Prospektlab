from __future__ import annotations

from finagent.screener.scoring import (
    check_filter_match,
    compute_scores,
    compute_technicals,
    detect_contradictions,
    parse_nl_filters,
)


def test_parse_nl_filters_extracts_bounds_and_heuristics():
    parsed = parse_nl_filters(
        "quality value momentum stocks with ROCE > 18 and ROE >= 15 and PE < 20 and debt free and no pledge and above 200 dma"
    )

    assert parsed.min_roce == 18
    assert parsed.min_roe == 15
    assert parsed.max_pe == 20
    assert parsed.require_no_pledge is True
    assert parsed.require_above_200dma is True
    assert parsed.max_debt_to_equity == 0.1
    assert parsed.min_rsi == 50


def test_compute_technicals_produces_expected_shape():
    prices = [100 + idx * 0.8 for idx in range(320)]
    dates = [f"2025-01-{(idx % 28) + 1:02d}" for idx in range(320)]

    technicals = compute_technicals(dates, prices)

    assert technicals["status"] == "ok"
    assert technicals["above_200dma"] is True
    assert technicals["trend_bias"] in {"bullish", "uptrend"}
    assert technicals["rsi14"] is not None
    assert technicals["sma200"] is not None


def test_compute_scores_returns_grade_and_pillars():
    snapshot = {
        "fundamentals": {
            "metrics": {
                "roce": 23.5,
                "roe": 18.2,
                "pe_ratio": 21.0,
                "debt_to_equity": 0.35,
                "promoter_holding_pct": 52.0,
                "promoter_pledge_pct": 0.0,
                "free_cashflow": 1000,
                "revenue_growth_pct": 14.0,
            }
        },
        "technicals": {
            "rsi14": 58.0,
            "trend_bias": "bullish",
            "above_200dma": True,
            "return_1m_pct": 5.2,
            "return_3m_pct": 12.4,
        },
        "governance": {"score": 24.0},
        "ikg": {"coverage": {"directors": "complete", "facts": "complete", "auditors": "partial"}},
        "risk_signals": {"enforcement_count": 0},
    }

    scored = compute_scores(snapshot)

    assert 0 <= scored["prospekt_score"] <= 100
    assert scored["grade"] in {"A", "B", "C", "D"}
    assert "pillars" in scored and "fundamental_quality" in scored["pillars"]


def test_detect_contradictions_flags_key_conflicts():
    snapshot = {
        "fundamentals": {
            "metrics": {
                "pe_ratio": 55.0,
                "revenue_growth_pct": 7.0,
                "net_income": 120.0,
                "free_cashflow": -45.0,
                "promoter_pledge_pct": 30.0,
            }
        },
        "technicals": {"trend_bias": "uptrend"},
        "governance": {"score": 82.0},
    }
    conflicts = detect_contradictions(snapshot)
    codes = {row["code"] for row in conflicts}

    assert "VALUATION_VS_GROWTH" in codes
    assert "PROFIT_VS_CASHFLOW" in codes
    assert "PROMOTER_PLEDGE_STRESS" in codes
    assert "TECHNICALS_VS_GOVERNANCE" in codes


def test_check_filter_match_applies_constraints():
    parsed = parse_nl_filters("roce > 15 and roe > 12 and pe < 25 and above 200 dma")
    passed, reasons = check_filter_match(
        parsed,
        price=512.5,
        metrics={"roce": 21.0, "roe": 15.0, "pe_ratio": 19.0},
        technicals={"above_200dma": True, "rsi14": 56.0},
    )

    assert passed is True
    assert reasons

    failed, reasons2 = check_filter_match(
        parsed,
        price=512.5,
        metrics={"roce": 14.0, "roe": 11.0, "pe_ratio": 35.0},
        technicals={"above_200dma": False, "rsi14": 36.0},
    )

    assert failed is False
    assert reasons2


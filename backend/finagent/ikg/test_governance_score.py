"""Unit tests for the Forensic Governance Score pure scoring core."""

from __future__ import annotations

from finagent.ikg.governance_score import (
    BAND_ELEVATED,
    compute_governance_score,
    result_to_dict,
)


def test_clean_company_low_band():
    signals = {
        "pledge_quarters": [
            {"quarter": "Q4FY26", "total_pledge_pct": 0.0, "total_promoter_holding_pct": 55.0, "as_on_date": "2026-03-31"},
            {"quarter": "Q3FY26", "total_pledge_pct": 0.0, "total_promoter_holding_pct": 55.0, "as_on_date": "2025-12-31"},
        ],
        "enforcement": [],
        "auditors": [{"auditor_name": "Deloitte Haskins & Sells", "fiscal_year": "FY26"}],
        "board": {"recent_cessations": 0, "total": 10},
    }
    res = compute_governance_score(signals, cin="L00000XX0000XXX000000")
    assert res.band == "LOW"
    assert res.score < 25.0
    assert res.flags == []


def test_high_pledge_flagged():
    signals = {
        "pledge_quarters": [
            {"quarter": "Q4FY26", "total_pledge_pct": 70.0, "total_promoter_holding_pct": 50.0, "source_url": "http://x", "as_on_date": "2026-03-31"},
        ],
        "enforcement": [],
        "auditors": [],
        "board": None,
    }
    res = compute_governance_score(signals)
    codes = {f.code for f in res.flags}
    assert "PLEDGE_HIGH" in codes
    assert res.subscores["pledge"] >= 100.0 - 1e-6
    # evidence carries the source
    flag = next(f for f in res.flags if f.code == "PLEDGE_HIGH")
    assert flag.evidence["source_table"] == "shp_raw"
    assert flag.evidence["value_pct"] == 70.0


def test_rising_pledge_trend_bump():
    signals = {
        "pledge_quarters": [
            {"quarter": "Q4FY26", "total_pledge_pct": 40.0, "total_promoter_holding_pct": 48.0, "as_on_date": "2026-03-31"},
            {"quarter": "Q3FY26", "total_pledge_pct": 20.0, "total_promoter_holding_pct": 50.0, "as_on_date": "2025-12-31"},
        ],
        "enforcement": [], "auditors": [], "board": None,
    }
    res = compute_governance_score(signals)
    codes = {f.code for f in res.flags}
    assert "PLEDGE_RISING" in codes
    assert "PROMOTER_DILUTION" not in codes  # only 2pp drop, below 5pp threshold


def test_enforcement_action_high_severity():
    signals = {
        "pledge_quarters": [],
        "enforcement": [
            {"violation_type": "Insider trading", "penalty_amount_inr": 5_000_000, "order_date": "2025-01-01", "status": "active", "pdf_url": "http://sebi/x.pdf"},
        ],
        "auditors": None, "board": None,
    }
    res = compute_governance_score(signals)
    flag = next(f for f in res.flags if f.code == "ENFORCEMENT_ACTION")
    assert flag.severity == "high"
    assert flag.evidence["count"] == 1
    assert res.subscores["enforcement"] == 30.0


def test_reversed_enforcement_ignored():
    signals = {
        "pledge_quarters": [],
        "enforcement": [{"violation_type": "X", "penalty_amount_inr": 1000, "status": "reversed"}],
        "auditors": None, "board": None,
    }
    res = compute_governance_score(signals)
    assert all(f.code != "ENFORCEMENT_ACTION" for f in res.flags)
    assert res.subscores["enforcement"] == 0.0


def test_auditor_churn_flagged():
    signals = {
        "pledge_quarters": [],
        "enforcement": None,
        "auditors": [
            {"auditor_name": "Firm A", "fiscal_year": "FY26"},
            {"auditor_name": "Firm B", "fiscal_year": "FY25"},
            {"auditor_name": "Firm C", "fiscal_year": "FY24"},
        ],
        "board": None,
    }
    res = compute_governance_score(signals)
    flag = next(f for f in res.flags if f.code == "AUDITOR_CHURN")
    assert flag.severity == "high"
    assert res.subscores["auditor_instability"] == 80.0


def test_board_churn_flagged():
    signals = {
        "pledge_quarters": [], "enforcement": None, "auditors": None,
        "board": {"recent_cessations": 3, "total": 8},
    }
    res = compute_governance_score(signals)
    flag = next(f for f in res.flags if f.code == "BOARD_CHURN")
    assert flag.severity == "watch"
    assert res.subscores["board_churn"] > 0.0


def test_compound_blowup_pattern_high_band():
    """Pledge rising + enforcement + auditor churn = the classic blowup signature."""
    signals = {
        "pledge_quarters": [
            {"quarter": "Q4FY26", "total_pledge_pct": 85.0, "total_promoter_holding_pct": 40.0, "as_on_date": "2026-03-31"},
            {"quarter": "Q3FY26", "total_pledge_pct": 60.0, "total_promoter_holding_pct": 52.0, "as_on_date": "2025-12-31"},
        ],
        "enforcement": [
            {"violation_type": "Fund diversion", "penalty_amount_inr": 50_000_000, "status": "active", "order_date": "2025-06-01"},
        ],
        "auditors": [
            {"auditor_name": "Firm A", "fiscal_year": "FY26"},
            {"auditor_name": "Firm B", "fiscal_year": "FY25"},
        ],
        "board": {"recent_cessations": 3, "total": 9},
    }
    res = compute_governance_score(signals, cin="L99999ZZ9999ZZZ999999")
    assert res.band in ("ELEVATED", "HIGH")
    assert res.score >= BAND_ELEVATED - 25.0
    codes = {f.code for f in res.flags}
    assert {"PLEDGE_HIGH", "PLEDGE_RISING", "ENFORCEMENT_ACTION", "AUDITOR_CHURN"}.issubset(codes)
    # high-severity flags must sort first
    assert res.flags[0].severity == "high"


def test_no_data_returns_zero_low():
    signals = {"pledge_quarters": [], "enforcement": None, "auditors": None, "board": None}
    res = compute_governance_score(signals)
    assert res.score == 0.0
    assert res.band == "LOW"


def test_result_to_dict_shape():
    signals = {
        "pledge_quarters": [{"quarter": "Q4FY26", "total_pledge_pct": 60.0, "total_promoter_holding_pct": 50.0, "as_on_date": "2026-03-31"}],
        "enforcement": [], "auditors": None, "board": None,
    }
    d = result_to_dict(compute_governance_score(signals, cin="LTEST"))
    assert set(d) == {"cin", "score", "band", "subscores", "flags", "coverage", "computed_at"}
    assert d["cin"] == "LTEST"
    assert isinstance(d["flags"], list)
    assert all({"code", "severity", "detail", "evidence"} == set(f) for f in d["flags"])


def test_coverage_renormalization():
    """Only-pledge company should not be diluted by zero scores from absent signals."""
    high_pledge_only = {
        "pledge_quarters": [{"quarter": "Q4FY26", "total_pledge_pct": 50.0, "total_promoter_holding_pct": 50.0, "as_on_date": "2026-03-31"}],
        "enforcement": None, "auditors": None, "board": None,
    }
    res = compute_governance_score(high_pledge_only)
    # pledge subscore 100; only pledge+promoter_dilution covered → composite must reflect pledge strongly
    assert res.coverage["pledge"] is True
    assert res.coverage["enforcement"] is False
    assert res.score > 50.0

"""Tests for the quantitative pre-pass."""
from finagent.content.quant_prepass import (
    detect_trend_breaks,
    flag_anomalies,
    peer_cross_section,
)


def test_peer_ranking_top():
    target = {"name": "Infosys", "ebit_margin": 21.3, "rev_growth": 8.6}
    peers = [
        {"name": "TCS", "ebit_margin": 24.5, "rev_growth": 5.9},
        {"name": "HCLTech", "ebit_margin": 18.2, "rev_growth": 6.5},
        {"name": "Wipro", "ebit_margin": 16.0, "rev_growth": 1.0},
    ]
    res = peer_cross_section(target, peers, ["ebit_margin", "rev_growth"])
    assert res["rev_growth"]["rank"] == 1          # 8.6 highest
    assert res["rev_growth"]["of"] == 4
    assert res["ebit_margin"]["rank"] == 2          # behind TCS 24.5
    assert "median" in res["ebit_margin"]


def test_peer_skips_missing_metric():
    target = {"name": "X", "roe": None}
    peers = [{"name": "Y", "roe": 10.0}]
    assert peer_cross_section(target, peers, ["roe"]) == {}


def test_trend_break_peak():
    breaks = detect_trend_breaks([10, 12, 15, 14, 9], ["Q1", "Q2", "Q3", "Q4", "Q5"])
    kinds = {b["kind"] for b in breaks}
    assert "peak" in kinds


def test_trend_break_sign_flip():
    breaks = detect_trend_breaks([5, 2, -3], ["a", "b", "c"])
    assert any(b["kind"] == "sign_flip" for b in breaks)


def test_trend_break_too_short():
    assert detect_trend_breaks([1, 2]) == []


def test_anomaly_receivables():
    flags = flag_anomalies({"revenue_growth": 8.0, "receivables_growth": 25.0})
    assert any(f["code"] == "receivables_outpacing_revenue" for f in flags)


def test_anomaly_cashflow():
    flags = flag_anomalies({"pat": 100.0, "ocf": 40.0})
    assert any(f["code"] == "cashflow_below_profit" for f in flags)


def test_anomaly_pledge_rise():
    flags = flag_anomalies({"promoter_pledge_pct": 30.0, "promoter_pledge_pct_prev": 20.0})
    assert any(f["code"] == "rising_promoter_pledge" for f in flags)


def test_anomaly_debt_up_margin_down():
    flags = flag_anomalies({"debt_growth": 15.0, "margin_change": -2.0})
    assert any(f["code"] == "debt_up_margin_down" for f in flags)


def test_clean_financials_no_flags():
    flags = flag_anomalies({"revenue_growth": 10.0, "receivables_growth": 9.0,
                            "pat": 100.0, "ocf": 95.0, "fcf_pat_ratio": 1.0})
    assert flags == []


def test_missing_keys_safe():
    assert flag_anomalies({}) == []

from __future__ import annotations

from finagent.ikg.scrapers.nse_index import _configured_index_universe, parse_nse_companies
from finagent.ikg.scrapers.sebi_corporate_filings import _resolve_limit


def test_configured_index_universe_defaults_to_nifty500(monkeypatch):
    monkeypatch.delenv("FINAGENT_NSE_UNIVERSE", raising=False)
    monkeypatch.delenv("FINAGENT_NSE_INDEX_CSV_URLS", raising=False)
    spec = _configured_index_universe()
    assert spec["key"] == "nifty500"
    assert spec["label"] == "Nifty 500"
    assert any("ind_nifty500list.csv" in url for url in spec["urls"])


def test_configured_index_universe_supports_nifty1000(monkeypatch):
    monkeypatch.setenv("FINAGENT_NSE_UNIVERSE", "nifty1000")
    spec = _configured_index_universe()
    assert spec["key"] == "nifty1000"
    assert spec["source"] == "nse_nifty1000_csv"
    assert any("ind_nifty1000list.csv" in url for url in spec["urls"])


def test_parse_nse_companies_uses_supplied_source():
    rows = [
        {
            "Symbol": "ABC",
            "Company Name": "ABC Limited",
            "ISIN Code": "INE000A01011",
            "Industry": "Banks",
            "Series": "EQ",
        }
    ]
    parsed = parse_nse_companies(rows, source="nse_nifty1000_csv", universe_label="Nifty 1000")
    assert parsed[0]["source"] == "nse_nifty1000_csv"
    assert parsed[0]["sector"] == "Financials"


def test_resolve_limit_uses_unlimited_mode_for_small_backfills(monkeypatch):
    monkeypatch.delenv("FINAGENT_CORP_FILINGS_EXTRACT_LIMIT", raising=False)
    cap = _resolve_limit(
        None,
        env_key="FINAGENT_CORP_FILINGS_EXTRACT_LIMIT",
        default_value="25",
        records_count=12,
    )
    assert cap == 0


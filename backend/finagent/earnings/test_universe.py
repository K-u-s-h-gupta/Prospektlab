from finagent.earnings import universe


def test_earnings_universe_filters_indexed_companies(monkeypatch):
    monkeypatch.setenv("FINAGENT_EARNINGS_FILTER_UNIVERSE", "true")
    monkeypatch.setenv("FINAGENT_EARNINGS_UNIVERSE_LIMIT", "2")
    monkeypatch.setattr(
        universe,
        "_load_indexed_companies",
        lambda: [
            {"nse_symbol": "AAA", "isin": "INEAAA", "bse_scrip_code": "500001"},
            {"nse_symbol": "BBB", "isin": "INEBBB", "bse_scrip_code": "500002"},
            {"nse_symbol": "CCC", "isin": "INECCC", "bse_scrip_code": "500003"},
        ],
    )
    universe.get_earnings_universe.cache_clear()
    try:
        assert universe.record_in_earnings_universe({"symbol": "AAA"})
        assert universe.record_in_earnings_universe({"isin": "INEBBB"})
        assert not universe.record_in_earnings_universe({"symbol": "CCC", "isin": "INECCC"})
        assert not universe.filter_earnings_universe_records([{"symbol": "CCC"}])

        sql, params = universe.earnings_universe_sql_filter("a")
        assert "a.symbol" in sql
        assert "a.isin" in sql
        assert "a.bse_scrip_code" in sql
        assert any("AAA" in values for values in params)
    finally:
        universe.get_earnings_universe.cache_clear()
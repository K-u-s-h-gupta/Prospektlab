from finagent.geo.entity_resolver import resolve_entities, resolve_entity


def test_compound_indian_name_beats_single_token_symbol():
    entity = resolve_entity("CG Power latest results")
    assert entity.ticker_label == "CGPOWER"
    assert entity.yahoo_ticker == "CGPOWER.NS"


def test_comparison_extracts_multiple_indian_entities():
    entities = resolve_entities("Compare BHARTIARTL and IDEA valuation", limit=4)
    tickers = [e.ticker_label for e in entities]
    assert "BHARTIARTL" in tickers
    assert "IDEA" in tickers

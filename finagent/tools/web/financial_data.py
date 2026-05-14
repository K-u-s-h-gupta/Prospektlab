"""Aggregator sanity-check helpers only (not primary sources)."""

async def yahoo_quote_stub(symbol: str) -> dict:
    return {"symbol": symbol, "note": "sanity check only — verify against primary"}

"""Yahoo Finance v8 chart API.

`query1.finance.yahoo.com/v8/finance/chart/<TICKER>` returns a JSON payload
with `chart.result[0].meta` (regularMarketPrice, previousClose, marketCap,
fiftyTwoWeekHigh / Low, currency, exchange) and `indicators.quote[0]` for the
price series. The endpoint accepts ordinary browser User-Agents and does not
require auth for basic data — good enough for our "live quote at memo time"
snapshot.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from finagent.tools.web.http_fetcher import fetch

logger = logging.getLogger("finagent.yahoo")

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1mo&interval=1d"


@dataclass
class YahooQuote:
    ticker: str
    name: str | None
    currency: str | None
    exchange: str | None
    price: float | None
    previous_close: float | None
    change_pct: float | None
    market_cap: float | None
    fifty_two_week_high: float | None
    fifty_two_week_low: float | None
    series_dates: list[str]
    series_closes: list[float]
    source_url: str


async def fetch_yahoo_quote(ticker: str, *, timeout_s: float = 12.0) -> YahooQuote | None:
    if not ticker:
        return None
    url = _CHART_URL.format(ticker=ticker.upper())
    res = await fetch(url, respect_robots=False, timeout_s=timeout_s)
    if res.status != 200 or not res.text:
        logger.info("yahoo chart fetch failed for %s (status=%s)", ticker, res.status)
        return None
    try:
        payload = json.loads(res.text)
    except Exception as exc:
        logger.warning("yahoo chart parse failed: %s", exc)
        return None
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        return None
    r0 = result[0]
    meta = r0.get("meta") or {}
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    change_pct: float | None = None
    if price is not None and prev:
        try:
            change_pct = (price - prev) / prev * 100.0
        except Exception:
            change_pct = None
    timestamps = r0.get("timestamp") or []
    indicators = (r0.get("indicators") or {}).get("quote") or [{}]
    closes_raw = indicators[0].get("close") if indicators else []
    series_dates: list[str] = []
    series_closes: list[float] = []
    if timestamps and closes_raw:
        import datetime as _dt

        for ts, close in zip(timestamps, closes_raw):
            if close is None:
                continue
            try:
                d = _dt.datetime.fromtimestamp(int(ts), tz=_dt.timezone.utc).strftime("%Y-%m-%d")
                series_dates.append(d)
                series_closes.append(float(close))
            except Exception:
                continue
    return YahooQuote(
        ticker=ticker.upper(),
        name=meta.get("longName") or meta.get("shortName"),
        currency=meta.get("currency"),
        exchange=meta.get("exchangeName"),
        price=float(price) if price is not None else None,
        previous_close=float(prev) if prev is not None else None,
        change_pct=change_pct,
        market_cap=float(meta["marketCap"]) if meta.get("marketCap") else None,
        fifty_two_week_high=float(meta["fiftyTwoWeekHigh"]) if meta.get("fiftyTwoWeekHigh") else None,
        fifty_two_week_low=float(meta["fiftyTwoWeekLow"]) if meta.get("fiftyTwoWeekLow") else None,
        series_dates=series_dates,
        series_closes=series_closes,
        source_url=f"https://finance.yahoo.com/quote/{ticker.upper()}",
    )

"""Dividend tracker.

Parses CAS transaction history for "DIVIDEND" type entries → trailing 12m dividend received.
Forward yield estimate from yfinance dividendYield × current value.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from finagent.portfolio_mirrors import PositionMirror
from finagent.portfolio.analytics import _is_valid_ticker

logger = logging.getLogger("finagent.portfolio.dividends")


def _fetch_dividend_yield(ticker: str) -> float:
    """Fetch forward dividend yield from yfinance."""
    if not _is_valid_ticker(ticker):
        return 0.0
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        return float(t.info.get("dividendYield", 0) or 0.0)
    except Exception as exc:
        logger.debug("Dividend yield fetch failed for %s: %s", ticker, exc)
        return 0.0


def compute_dividend_summary(positions: list[PositionMirror]) -> dict[str, Any]:
    """Compute dividend tracker summary.

    Since we don't yet parse CAS transaction history for dividends in real time,
    we estimate forward yield from current yfinance data.
    """
    if not positions:
        return {"status": "NO_DATA", "trailing_12m": 0.0, "forward_estimate": 0.0, "positions": []}

    total_forward = 0.0
    pos_dividends = []
    for pos in positions:
        if pos.kind != "equity":
            continue
        yield_pct = _fetch_dividend_yield(pos.exchange_symbol)
        fwd = pos.market_value * yield_pct if yield_pct else 0.0
        total_forward += fwd
        pos_dividends.append({
            "symbol": pos.exchange_symbol,
            "name": pos.name,
            "market_value": pos.market_value,
            "yield_pct": round(yield_pct * 100, 2) if yield_pct else None,
            "forward_annual": round(fwd, 2),
        })

    # Sort by forward annual descending
    pos_dividends.sort(key=lambda x: x.get("forward_annual", 0), reverse=True)

    return {
        "status": "OK",
        "trailing_12m": None,  # Would come from CAS transaction parsing
        "forward_estimate": round(total_forward, 2),
        "positions": pos_dividends,
        "top_yielders": pos_dividends[:5],
    }


def get_next_ex_dates(positions: list[PositionMirror], max_results: int = 3) -> list[dict[str, Any]]:
    """Best-effort next ex-dividend dates from yfinance.

    Note: yfinance doesn't reliably provide future ex-dates.
    We return a placeholder with last known ex-date if available.
    """
    results = []
    for pos in positions:
        if pos.kind != "equity":
            continue
        try:
            import yfinance as yf
            t = yf.Ticker(pos.exchange_symbol)
            divs = t.dividends
            if divs is not None and len(divs) > 0:
                last_ex = divs.index[-1]
                results.append({
                    "symbol": pos.exchange_symbol,
                    "name": pos.name,
                    "last_ex_date": last_ex.strftime("%Y-%m-%d"),
                })
            if len(results) >= max_results:
                break
        except Exception:
            continue
    return results

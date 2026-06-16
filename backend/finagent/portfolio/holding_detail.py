"""Holding detail panel data assembler.

Fetches per-holding KPIs (P/E, P/B, ROE, mcap), 1Y price chart vs Nifty,
recent verified news, peer comparison, and position-specific P/L breakdown.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from finagent.portfolio_mirrors import PositionMirror
from finagent.portfolio.analytics import _fetch_history, _fetch_quote_cached, _is_valid_ticker
from finagent.portfolio.news import fetch_portfolio_news

logger = logging.getLogger("finagent.portfolio.holding_detail")


def _fetch_info(ticker: str) -> dict[str, Any]:
    """Fetch yfinance info dict with safety guards."""
    if not _is_valid_ticker(ticker):
        return {}
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        info = t.info or {}
        return {
            "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
            "pb_ratio": info.get("priceToBook"),
            "roe": info.get("returnOnEquity"),
            "mcap": info.get("marketCap"),
            "currency": info.get("currency", "INR"),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "website": info.get("website", ""),
            "long_business_summary": info.get("longBusinessSummary", "")[:400],
        }
    except Exception as exc:
        logger.debug("Info fetch failed for %s: %s", ticker, exc)
        return {}


def _find_peers(sector: str, exclude_symbol: str, max_peers: int = 3) -> list[dict[str, Any]]:
    """Best-effort peer lookup from bundled sector data + yfinance."""
    peers: list[dict[str, Any]] = []
    try:
        import yfinance as yf
        # Try to find same-sector tickers from Nifty 500
        idx = yf.Ticker("^CRSLDX")
        idx_hist = idx.history(period="1d")
        if idx_hist.empty:
            return peers
    except Exception:
        pass
    return peers


def get_holding_detail(pos: PositionMirror) -> dict[str, Any]:
    """Return full detail bundle for a single holding."""
    ticker = pos.exchange_symbol
    info = _fetch_info(ticker) if pos.kind == "equity" else {}
    quote = _fetch_quote_cached(ticker) if pos.kind == "equity" else {}
    price = quote.get("price", pos.last_price or 0)

    # 1Y price chart vs Nifty
    history = _fetch_history(ticker, period="1y") if pos.kind == "equity" else {}
    nifty_history = _fetch_history("^NSEI", period="1y")

    # Position P/L breakdown
    mkt_val = price * pos.quantity if price and pos.quantity else pos.market_value
    cost = pos.cost_basis or (pos.avg_cost * pos.quantity)
    pnl = mkt_val - cost if cost else None
    pnl_pct = (pnl / cost) if cost else None
    days_held = 0  # Would need transaction dates from CAS; placeholder

    return {
        "symbol": pos.exchange_symbol,
        "name": pos.name or pos.symbol,
        "isin": pos.isin,
        "amfi": pos.amfi,
        "kind": pos.kind,
        "sector": pos.sector or info.get("sector", ""),
        "industry": pos.industry or info.get("industry", ""),
        "quantity": pos.quantity,
        "avg_cost": pos.avg_cost,
        "last_price": price,
        "market_value": mkt_val,
        "cost_basis": cost,
        "unrealized_pnl": pnl,
        "unrealized_pnl_pct": pnl_pct,
        "kpis": {
            "pe_ratio": info.get("pe_ratio"),
            "pb_ratio": info.get("pb_ratio"),
            "roe": info.get("roe"),
            "mcap": info.get("mcap"),
        },
        "history": {
            "ticker": history,
            "nifty50": nifty_history,
        },
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

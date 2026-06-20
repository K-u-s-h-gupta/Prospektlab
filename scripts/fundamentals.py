"""Real fundamentals enrichment for the publisher.

Resolves a topic to an NSE ticker, pulls live fundamentals via yfinance, and
returns (a) a hard-number context block injected into the research wave and
synthesis, (b) a list of real metric dicts, and (c) a real annual-revenue chart
series. This is what lets the agent write "operating margin 24.2%" instead of
"operating margin disclosed".

No fabrication: every number comes from the Yahoo Finance fundamentals feed.
If the ticker cannot be resolved or the feed is empty, returns empty enrichment
and the downstream gate drops any qualitative placeholder metrics.
"""

from __future__ import annotations

import re
from typing import Any

# Curated name → NSE symbol map for the large caps the publisher rotates over.
# Keys are lowercase substrings matched against the topic.
NSE_TICKERS: dict[str, str] = {
    "reliance": "RELIANCE",
    "tcs": "TCS",
    "tata consultancy": "TCS",
    "infosys": "INFY",
    "hdfc bank": "HDFCBANK",
    "icici bank": "ICICIBANK",
    "axis bank": "AXISBANK",
    "kotak mahindra": "KOTAKBANK",
    "state bank of india": "SBIN",
    "sbi ": "SBIN",
    "bharti airtel": "BHARTIARTL",
    "tata motors": "TATAMOTORS",
    "maruti suzuki": "MARUTI",
    "larsen": "LT",
    "l&t": "LT",
    "sun pharma": "SUNPHARMA",
    "hindustan unilever": "HINDUNILVR",
    "asian paints": "ASIANPAINT",
    "bajaj finance": "BAJFINANCE",
    "adani enterprises": "ADANIENT",
    "adani ports": "ADANIPORTS",
    "tata steel": "TATASTEEL",
    "jsw steel": "JSWSTEEL",
    "ongc": "ONGC",
    "coal india": "COALINDIA",
    "ultratech": "ULTRACEMCO",
    "power grid": "POWERGRID",
    "ntpc": "NTPC",
    "wipro": "WIPRO",
    "hcltech": "HCLTECH",
    "ltimindtree": "LTIM",
    "itc": "ITC",
}


def resolve_ticker(target: str) -> str | None:
    t = (target or "").lower()
    # Longest key first so "tata consultancy" wins over "tata".
    for name in sorted(NSE_TICKERS, key=len, reverse=True):
        if name in t:
            return NSE_TICKERS[name]
    return None


def _fmt_cr(value: float | None) -> str | None:
    if value is None:
        return None
    cr = value / 1e7  # rupees -> crore
    if abs(cr) >= 1e5:
        return f"Rs {cr/1e5:.2f} lakh crore"
    return f"Rs {cr:,.0f} crore"


def _fmt_pct(value: float | None, *, already_pct: bool = False) -> str | None:
    if value is None:
        return None
    pct = value if already_pct else value * 100.0
    return f"{pct:.1f}%"


def _fmt_x(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.1f}x"


async def fetch_fundamentals(target: str) -> dict[str, Any]:
    """Return {ticker, context_block, metrics, chart} or {} when unavailable."""
    symbol = resolve_ticker(target)
    if not symbol:
        return {}
    try:
        from finagent.tools.data.yahoo_finance import fetch_yahoo_quote
    except Exception:
        return {}
    try:
        q = await fetch_yahoo_quote(f"{symbol}.NS", timeout_s=30.0)
    except Exception:
        return {}
    if q is None:
        return {}

    fm = dict(getattr(q, "financial_metrics", {}) or {})
    price = getattr(q, "price", None)
    mcap = getattr(q, "market_cap", None)

    # Build real metric tiles (value + period + source) — numbers only.
    metrics: list[dict[str, str]] = []

    def add(label: str, value: str | None, change: str = "", period: str = "TTM") -> None:
        if value:
            metrics.append({"label": label, "value": value, "change": change, "period": period, "source": "Yahoo Finance fundamentals (TTM)"})

    add("Revenue (TTM)", _fmt_cr(fm.get("total_revenue")))
    add("EBITDA (TTM)", _fmt_cr(fm.get("ebitda")))
    add("Operating margin", _fmt_pct(fm.get("operating_margins")))
    add("Profit margin", _fmt_pct(fm.get("profit_margins")))
    add("Revenue growth (YoY)", _fmt_pct(fm.get("revenue_growth")))
    add("Return on equity", _fmt_pct(fm.get("return_on_equity")))
    add("Trailing P/E", _fmt_x(fm.get("trailing_pe")))
    add("Debt-to-equity", (f"{fm.get('debt_to_equity'):.0f}%" if fm.get("debt_to_equity") is not None else None))
    add("Dividend yield", _fmt_pct(fm.get("dividend_yield"), already_pct=(fm.get("dividend_yield", 0) or 0) > 1))
    if mcap:
        add("Market capitalisation", _fmt_cr(mcap), period="current")
    if price:
        add("Share price", f"Rs {price:,.0f}", period="latest close")

    # Real annual-revenue chart series (in Rs crore).
    chart: dict[str, Any] = {}
    rev = list(getattr(q, "annual_revenue", []) or [])
    rev_dates = list(getattr(q, "annual_revenue_dates", []) or [])
    if len(rev) >= 2:
        pts = []
        for i, v in enumerate(rev[-5:]):
            label = rev_dates[-5:][i][:4] if i < len(rev_dates[-5:]) else f"Y{i+1}"
            pts.append({"label": label, "value": round(v / 1e7, 0)})
        if len({p["value"] for p in pts}) >= 2:
            chart = {"kind": "bar", "title": "Annual revenue (Rs crore)", "points": pts, "note": "Source: Yahoo Finance reported annual revenue."}

    # Context block fed to the wave + synthesis so the model writes real numbers.
    lines = [f"[REAL FUNDAMENTALS — {symbol}.NS, Yahoo Finance, use these exact numbers; do not write 'disclosed']"]
    for m in metrics:
        lines.append(f"- {m['label']}: {m['value']} ({m['period']})")
    if chart:
        series = ", ".join(f"{p['label']}: Rs {p['value']:,.0f} cr" for p in chart["points"])
        lines.append(f"- Annual revenue series: {series}")
    context_block = "\n".join(lines)

    return {"ticker": symbol, "context_block": context_block, "metrics": metrics, "chart": chart}

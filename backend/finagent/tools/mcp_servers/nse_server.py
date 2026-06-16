"""
ORACLE FIOS - NSE Market Data MCP Server
==========================================
Powered by NseIndiaApi (https://github.com/BennyThadikaran/NseIndiaApi)

Exposes MCP tools:
  - nse_get_quote        : real-time stock quote
  - nse_get_historical   : historical OHLCV data (from NSE directly)
  - nse_get_option_chain : option chain with PCR, max pain
  - nse_get_index        : live index data (Nifty 50, Bank Nifty, etc.)
  - nse_get_shareholding : promoter / public / FII holding pattern
  - nse_get_actions      : upcoming corporate actions (dividends, splits)
  - nse_get_announcements: corporate announcements

All data comes directly from NSE India — free, no API key required.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import date, datetime, timedelta
from typing import Any

from fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("oracle.nse_mcp")

# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "ORACLE NSE Market Data",
    instructions=(
        "Real-time and historical market data for all NSE-listed Indian equities. "
        "Powered by NseIndiaApi. Part of the ORACLE Financial Intelligence OS."
    ),
)

# ---------------------------------------------------------------------------
# NSE client helper  (lazy init to avoid cookie issues at import time)
# ---------------------------------------------------------------------------
_nse_instance = None
_download_folder = os.path.join(tempfile.gettempdir(), "oracle_nse_data")


def _get_nse():
    """Return a lazily-initialised NSE client."""
    global _nse_instance
    if _nse_instance is None:
        from nse import NSE
        os.makedirs(_download_folder, exist_ok=True)
        _nse_instance = NSE(_download_folder)
    return _nse_instance


def _safe_get(data: dict, *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dicts."""
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def _parse_date(date_str: str | None, fallback: date | None = None) -> date:
    """Parse DD-MM-YYYY or YYYY-MM-DD into a date object."""
    if date_str is None:
        if fallback is not None:
            return fallback
        raise ValueError("Date string is required")
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f"Could not parse date '{date_str}'. Use DD-MM-YYYY or YYYY-MM-DD."
    )


# ---------------------------------------------------------------------------
# Tool: nse_get_quote
# ---------------------------------------------------------------------------
@mcp.tool
def nse_get_quote(symbol: str) -> dict:
    """
    Fetch the real-time stock quote from NSE India.

    Args:
        symbol: NSE stock symbol (e.g. "RELIANCE", "TCS", "INFY").

    Returns:
        dict with: symbol, company_name, last_price, change, pct_change,
        open, high, low, close, prev_close, volume, 52-week high/low,
        sector_pe, symbol_pe, face_value, isin, industry, market_cap.
    """
    symbol = symbol.strip().upper()
    logger.info("nse_get_quote: %s", symbol)

    try:
        nse = _get_nse()
        raw = nse.quote(symbol)
    except Exception as exc:
        logger.error("nse_get_quote failed for %s: %s", symbol, exc)
        return {"error": True, "message": f"Failed to fetch quote for '{symbol}': {str(exc)}"}

    # Detect invalid / empty symbols
    price_info = raw.get("priceInfo", {})
    if price_info.get("lastPrice") is None:
        return {"error": True, "message": f"No data found for symbol '{symbol}'. Check the symbol is correct."}

    info = raw.get("info", {})
    metadata = raw.get("metadata", {})
    security_info = raw.get("securityInfo", {})
    industry_info = raw.get("industryInfo", {})

    quote = {
        "symbol": info.get("symbol", symbol),
        "company_name": info.get("companyName", metadata.get("companyName", "N/A")),
        "isin": info.get("isin", metadata.get("isin")),
        "series": metadata.get("series"),
        "listing_date": metadata.get("listingDate"),
        # Industry
        "sector": industry_info.get("sector", metadata.get("pdSectorInd", "").strip()),
        "industry": industry_info.get("industry", metadata.get("industry")),
        "basic_industry": industry_info.get("basicIndustry"),
        # Price data
        "last_price": price_info.get("lastPrice"),
        "change": price_info.get("change"),
        "pct_change": price_info.get("pChange"),
        "open": price_info.get("open"),
        "high": _safe_get(price_info, "intraDayHighLow", "max"),
        "low": _safe_get(price_info, "intraDayHighLow", "min"),
        "close": price_info.get("close"),
        "prev_close": price_info.get("previousClose"),
        "vwap": price_info.get("vwap"),
        # 52-week
        "week_high_52": _safe_get(price_info, "weekHighLow", "max"),
        "week_low_52": _safe_get(price_info, "weekHighLow", "min"),
        "week_high_52_date": _safe_get(price_info, "weekHighLow", "maxDate"),
        "week_low_52_date": _safe_get(price_info, "weekHighLow", "minDate"),
        # PE
        "sector_pe": metadata.get("pdSectorPe"),
        "symbol_pe": metadata.get("pdSymbolPe"),
        # Security info
        "face_value": security_info.get("faceValue"),
        "issued_size": security_info.get("issuedSize"),
        "is_fno": info.get("isFNOSec", False),
    }

    logger.info("nse_get_quote OK: %s @ Rs.%s", quote["symbol"], quote["last_price"])
    return {"error": False, "data": quote}


# ---------------------------------------------------------------------------
# Tool: nse_get_trade_info
# ---------------------------------------------------------------------------
@mcp.tool
def nse_get_trade_info(symbol: str) -> dict:
    """
    Fetch market cap, delivery data, order book, and volatility for a stock.

    Args:
        symbol: NSE stock symbol.

    Returns:
        dict with: total_traded_volume, total_traded_value, total_market_cap,
        free_float_market_cap, delivery_quantity, delivery_to_traded_pct,
        daily_volatility, annual_volatility.
    """
    symbol = symbol.strip().upper()
    logger.info("nse_get_trade_info: %s", symbol)

    try:
        nse = _get_nse()
        raw = nse.quote(symbol, section="trade_info")
    except Exception as exc:
        logger.error("nse_get_trade_info failed for %s: %s", symbol, exc)
        return {"error": True, "message": f"Failed: {str(exc)}"}

    trade = _safe_get(raw, "marketDeptOrderBook", "tradeInfo", default={})
    dp = raw.get("securityWiseDP", {})

    return {
        "error": False,
        "data": {
            "symbol": symbol,
            "total_traded_volume": trade.get("totalTradedVolume"),
            "total_traded_value": trade.get("totalTradedValue"),
            "total_market_cap": trade.get("totalMarketCap"),
            "free_float_market_cap": trade.get("ffmc"),
            "impact_cost": trade.get("impactCost"),
            "daily_volatility": trade.get("cmDailyVolatility"),
            "annual_volatility": trade.get("cmAnnualVolatility"),
            "delivery_quantity": dp.get("deliveryQuantity"),
            "quantity_traded": dp.get("quantityTraded"),
            "delivery_to_traded_pct": dp.get("deliveryToTradedQuantity"),
        },
    }


# ---------------------------------------------------------------------------
# Tool: nse_get_historical
# ---------------------------------------------------------------------------
@mcp.tool
def nse_get_historical(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int = 365,
) -> dict:
    """
    Fetch historical OHLCV data directly from NSE India.

    Args:
        symbol:     NSE stock symbol (e.g. "RELIANCE", "TCS").
        start_date: Start date (DD-MM-YYYY or YYYY-MM-DD). Optional.
        end_date:   End date. Defaults to today.
        days:       If start_date not given, fetch last N days (default 365).

    Returns:
        dict with records list of {date, open, high, low, close, volume}.
    """
    symbol = symbol.strip().upper()
    logger.info("nse_get_historical: %s, start=%s, end=%s, days=%d", symbol, start_date, end_date, days)

    try:
        nse = _get_nse()

        ed = _parse_date(end_date, fallback=date.today())
        if start_date:
            sd = _parse_date(start_date)
        else:
            sd = ed - timedelta(days=days)

        raw_records = nse.fetch_equity_historical_data(
            symbol=symbol,
            from_date=sd,
            to_date=ed,
            series="EQ",
        )

        if not raw_records:
            return {"error": True, "message": f"No historical data for '{symbol}' in the given range."}

        records = []
        for r in raw_records:
            records.append({
                "date": r.get("mtimestamp", ""),
                "open": r.get("chOpeningPrice"),
                "high": r.get("chTradeHighPrice"),
                "low": r.get("chTradeLowPrice"),
                "close": r.get("chClosingPrice"),
                "ltp": r.get("chLastTradedPrice"),
                "prev_close": r.get("chPreviousClsPrice"),
                "volume": r.get("chTotTradedQty"),
                "value": r.get("chTotTradedVal"),
                "vwap": r.get("vwap"),
                "total_trades": r.get("chTotalTrades"),
            })

        logger.info("nse_get_historical OK: %s - %d records", symbol, len(records))
        return {
            "error": False,
            "data": {
                "symbol": symbol,
                "total_records": len(records),
                "date_range": {"start": records[0]["date"], "end": records[-1]["date"]},
                "records": records,
            },
        }

    except Exception as exc:
        logger.error("nse_get_historical failed: %s - %s", symbol, exc)
        return {"error": True, "message": f"Failed to fetch historical data for '{symbol}': {str(exc)}"}


# ---------------------------------------------------------------------------
# Tool: nse_get_option_chain
# ---------------------------------------------------------------------------
@mcp.tool
def nse_get_option_chain(symbol: str) -> dict:
    """
    Fetch option chain data for a stock or index from NSE.

    Args:
        symbol: Stock symbol (e.g. "RELIANCE") or index ("nifty", "banknifty").

    Returns:
        dict with: underlying_value, expiry_dates, total_ce_oi, total_pe_oi, pcr.
    """
    symbol_upper = symbol.strip().upper()
    # NseIndiaApi expects lowercase for index futures
    sym = symbol.strip().lower() if symbol.strip().upper() in ("NIFTY", "BANKNIFTY", "FINNIFTY", "NIFTYIT") else symbol_upper
    logger.info("nse_get_option_chain: %s", sym)

    try:
        nse = _get_nse()
        raw = nse.optionChain(sym)

        records = raw.get("records", {})
        filtered = raw.get("filtered", {})

        ce_oi = _safe_get(filtered, "CE", "totOI", default=0)
        pe_oi = _safe_get(filtered, "PE", "totOI", default=0)
        pcr = round(pe_oi / ce_oi, 2) if ce_oi > 0 else None

        return {
            "error": False,
            "data": {
                "symbol": symbol_upper,
                "underlying_value": records.get("underlyingValue"),
                "expiry_dates": records.get("expiryDates", [])[:5],
                "total_ce_oi": ce_oi,
                "total_pe_oi": pe_oi,
                "pcr": pcr,
                "strikePrices": records.get("strikePrices", []),
            },
        }
    except Exception as exc:
        logger.error("nse_get_option_chain failed: %s - %s", sym, exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: nse_get_index
# ---------------------------------------------------------------------------
@mcp.tool
def nse_get_index(index_name: str = "NIFTY 50") -> dict:
    """
    Fetch live index data (NIFTY 50, NIFTY BANK, NIFTY IT, etc.) with all constituents.

    Args:
        index_name: Index name (e.g. "NIFTY 50", "NIFTY BANK", "NIFTY IT").

    Returns:
        dict with index value, change, advance/decline counts, and constituent list.
    """
    logger.info("nse_get_index: %s", index_name)
    try:
        nse = _get_nse()
        raw = nse.listEquityStocksByIndex(index=index_name)
        return {"error": False, "data": raw}
    except Exception as exc:
        logger.error("nse_get_index failed: %s - %s", index_name, exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: nse_get_shareholding
# ---------------------------------------------------------------------------
@mcp.tool
def nse_get_shareholding(symbol: str) -> dict:
    """
    Fetch quarterly shareholding pattern (promoter, public, FII holding).

    Args:
        symbol: NSE stock symbol.

    Returns:
        List of quarterly shareholding records with promoter %, public %, etc.
    """
    symbol = symbol.strip().upper()
    logger.info("nse_get_shareholding: %s", symbol)
    try:
        nse = _get_nse()
        raw = nse.shareholding(symbol)
        return {"error": False, "data": raw}
    except Exception as exc:
        logger.error("nse_get_shareholding failed: %s - %s", symbol, exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: nse_get_actions
# ---------------------------------------------------------------------------
@mcp.tool
def nse_get_actions(symbol: str | None = None) -> dict:
    """
    Fetch upcoming corporate actions (dividends, splits, bonuses, rights).

    Args:
        symbol: Optional. If given, filter actions for this stock only.

    Returns:
        List of upcoming corporate actions.
    """
    logger.info("nse_get_actions: symbol=%s", symbol)
    try:
        nse = _get_nse()
        if symbol:
            raw = nse.actions(symbol=symbol.strip().upper())
        else:
            raw = nse.actions()
        return {"error": False, "data": raw}
    except Exception as exc:
        logger.error("nse_get_actions failed: %s", exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: nse_get_announcements
# ---------------------------------------------------------------------------
@mcp.tool
def nse_get_announcements(symbol: str | None = None) -> dict:
    """
    Fetch latest corporate announcements from NSE.

    Args:
        symbol: Optional. If given, filter for this stock only.

    Returns:
        List of announcements with subject, date, and attachment links.
    """
    logger.info("nse_get_announcements: symbol=%s", symbol)
    try:
        nse = _get_nse()
        if symbol:
            raw = nse.announcements(symbol=symbol.strip().upper())
        else:
            raw = nse.announcements()
        return {"error": False, "data": raw}
    except Exception as exc:
        logger.error("nse_get_announcements failed: %s", exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: nse_get_board_meetings
# ---------------------------------------------------------------------------
@mcp.tool
def nse_get_board_meetings(symbol: str | None = None) -> dict:
    """
    Fetch upcoming board meetings (earnings dates, dividends, etc.).

    Args:
        symbol: Optional. Filter for a specific stock.

    Returns:
        List of upcoming board meetings.
    """
    logger.info("nse_get_board_meetings: symbol=%s", symbol)
    try:
        nse = _get_nse()
        if symbol:
            raw = nse.boardMeetings(symbol=symbol.strip().upper())
        else:
            raw = nse.boardMeetings()
        return {"error": False, "data": raw}
    except Exception as exc:
        logger.error("nse_get_board_meetings failed: %s", exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting ORACLE NSE Market Data MCP Server ...")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8001)

"""
ORACLE FIOS - Fundamentals MCP Server (yfinance)
==================================================
All financial data powered by yfinance — completely FREE, no API key needed.

Exposes MCP tools:
  - profile           : company snapshot (sector, market cap, CEO, description)
  - income_statement  : annual/quarterly income statements (revenue, net income, EPS)
  - balance_sheet     : assets, liabilities, equity
  - cash_flow         : operating, investing, financing cash flows
  - key_metrics       : calculated ratios (PE, PB, ROE, D/E, dividend yield, etc.)

For Indian stocks: pass symbol as "RELIANCE", "TCS", etc.
    → auto-appends ".NS" for NSE lookup
For US stocks: pass symbol as "AAPL", "MSFT" directly.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from functools import lru_cache
from typing import Any

# ---------------------------------------------------------------------------
# Fix: curl_cffi (used by yfinance) cannot encode CA cert paths containing
# non-ASCII characters (e.g. Hindi directory names on Windows).
# ---------------------------------------------------------------------------
import certifi

_safe_cacert = os.path.join(tempfile.gettempdir(), "cacert.pem")
if not os.path.exists(_safe_cacert):
    shutil.copy2(certifi.where(), _safe_cacert)
os.environ["CURL_CA_BUNDLE"] = _safe_cacert
os.environ["REQUESTS_CA_BUNDLE"] = _safe_cacert
os.environ["SSL_CERT_FILE"] = _safe_cacert

import yfinance as yf
from fastmcp import FastMCP

# Set yfinance timezone cache to a safe location
yf.set_tz_cache_location(os.path.join(tempfile.gettempdir(), "yfinance_cache"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("oracle.fundamentals_mcp")

LEGAL_SUFFIXES = {
    "LIMITED",
    "LTD",
    "LIMITED.",
    "LTD.",
    "INDIA",
    "INDIAN",
    "COMPANY",
    "CO",
    "CORPORATION",
    "CORP",
    "INC",
    "PLC",
    "PRIVATE",
    "PVT",
}
COMMON_SYMBOL_ALIASES = {
    "INFOSYS": "INFY",
    "INFOSYS LIMITED": "INFY",
    "TATA CONSULTANCY SERVICES": "TCS",
    "TATA CONSULTANCY SERVICES LIMITED": "TCS",
    "RELIANCE INDUSTRIES": "RELIANCE",
    "RELIANCE INDUSTRIES LIMITED": "RELIANCE",
    "HDFC BANK": "HDFCBANK",
    "ICICI BANK": "ICICIBANK",
    "STATE BANK OF INDIA": "SBIN",
    "LARSEN TOUBRO": "LT",
    "LARSEN AND TOUBRO": "LT",
    "BHARTI AIRTEL": "BHARTIARTL",
    "ITC": "ITC",
    "WIPRO": "WIPRO",
    "HCL TECHNOLOGIES": "HCLTECH",
    "HCLTECH": "HCLTECH",
    "AXIS BANK": "AXISBANK",
    "KOTAK MAHINDRA BANK": "KOTAKBANK",
    "MARUTI SUZUKI": "MARUTI",
    "TITAN COMPANY": "TITAN",
    "SUN PHARMACEUTICAL INDUSTRIES": "SUNPHARMA",
    "ULTRATECH CEMENT": "ULTRACEMCO",
}

# ---------------------------------------------------------------------------
# FastMCP server instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "ORACLE Fundamentals",
    instructions=(
        "Company fundamentals, financial statements, and key metrics "
        "via yfinance (free). Part of the ORACLE Financial Intelligence OS."
    ),
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_ticker(symbol: str, exchange: str = "NSE") -> str:
    """Convert a plain symbol to a yfinance ticker string."""
    symbol = symbol.strip().upper()
    if "." in symbol:
        return symbol  # Already has suffix
    exchange = exchange.strip().upper()
    if exchange in ("NSE", "NS"):
        return f"{symbol}.NS"
    elif exchange in ("BSE", "BO"):
        return f"{symbol}.BO"
    return symbol  # US / global


def _normalize_company_key(symbol: str) -> str:
    cleaned = re.sub(r"[^A-Z0-9]+", " ", symbol.upper()).strip()
    parts = [part for part in cleaned.split() if part and part not in LEGAL_SUFFIXES]
    return " ".join(parts)


def _candidate_symbols(symbol: str) -> list[str]:
    upper = symbol.strip().upper()
    compact = re.sub(r"[^A-Z0-9]", "", upper)
    normalized_key = _normalize_company_key(upper)
    candidates: list[str] = []

    def add(value: str):
        if value and value not in candidates:
            candidates.append(value)

    add(upper)
    add(compact)
    add(COMMON_SYMBOL_ALIASES.get(upper, ""))
    add(COMMON_SYMBOL_ALIASES.get(normalized_key, ""))

    words = [word for word in normalized_key.split() if word]
    if len(words) > 1:
        add("".join(words))
        add("".join(word[0] for word in words))

    return candidates


def _df_to_records(df, orient: str = "index") -> list[dict]:
    """Convert a pandas DataFrame (with date index, metric columns) to
    a list of dicts suitable for JSON serialisation."""
    if df is None or df.empty:
        return []

    records = []
    if orient == "index":
        # Financial statements: index = metric names, columns = dates
        for col in df.columns:
            period_data = {"date": col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)}
            for metric in df.index:
                val = df.loc[metric, col]
                # Convert numpy types to Python native
                if hasattr(val, "item"):
                    val = val.item()
                period_data[str(metric)] = val
            records.append(period_data)
    return records


@lru_cache(maxsize=128)
def _get_info(ticker_str: str) -> dict:
    """Cache repeated yfinance info lookups within the server process."""
    return yf.Ticker(ticker_str).info


@lru_cache(maxsize=128)
def _resolve_ticker_and_info(symbol: str, exchange: str = "NSE") -> tuple[str, dict]:
    """Resolve either a ticker or a common company name to a valid yfinance ticker."""
    for candidate in _candidate_symbols(symbol):
        ticker_str = _to_ticker(candidate, exchange)
        try:
            info = _get_info(ticker_str)
            price = info.get("regularMarketPrice") or info.get("currentPrice")
            if info and price is not None:
                return ticker_str, info
        except Exception:
            continue
    fallback_ticker = _to_ticker(symbol, exchange)
    return fallback_ticker, {}


# ---------------------------------------------------------------------------
# Tool: profile
# ---------------------------------------------------------------------------
@mcp.tool
def profile(symbol: str, exchange: str = "NSE") -> dict:
    """
    Fetch company profile / snapshot.

    Args:
        symbol:   Stock ticker (e.g. "RELIANCE", "TCS", "AAPL").
        exchange: "NSE" (default) or "BSE" for Indian stocks. "US" for US stocks.

    Returns:
        Company info: name, sector, industry, market_cap, CEO, description,
        employees, website, country, currency, PE, PB, dividend yield, beta, etc.
    """
    ticker_str, info = _resolve_ticker_and_info(symbol, exchange)
    logger.info("profile: %s -> %s", symbol, ticker_str)

    try:
        if not info or info.get("regularMarketPrice") is None:
            return {"error": True, "message": f"No data found for '{symbol}'. Verify the symbol."}

        profile_data = {
            "symbol": ticker_str,
            "short_name": info.get("shortName"),
            "long_name": info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "website": info.get("website"),
            "description": info.get("longBusinessSummary"),
            "full_time_employees": info.get("fullTimeEmployees"),
            "currency": info.get("currency"),
            "exchange": info.get("exchange"),
            # Price
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "previous_close": info.get("previousClose"),
            "52_week_high": info.get("fiftyTwoWeekHigh"),
            "52_week_low": info.get("fiftyTwoWeekLow"),
            "50_day_avg": info.get("fiftyDayAverage"),
            "200_day_avg": info.get("twoHundredDayAverage"),
            # Valuation
            "market_cap": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "price_to_sales_trailing": info.get("priceToSalesTrailing12Months"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            "ev_to_revenue": info.get("enterpriseToRevenue"),
            # Profitability
            "profit_margins": info.get("profitMargins"),
            "operating_margins": info.get("operatingMargins"),
            "gross_margins": info.get("grossMargins"),
            "return_on_equity": info.get("returnOnEquity"),
            "return_on_assets": info.get("returnOnAssets"),
            # Dividend
            "dividend_yield": info.get("dividendYield"),
            "dividend_rate": info.get("dividendRate"),
            "payout_ratio": info.get("payoutRatio"),
            # Other
            "beta": info.get("beta"),
            "total_revenue": info.get("totalRevenue"),
            "revenue_per_share": info.get("revenuePerShare"),
            "earnings_per_share": info.get("trailingEps"),
            "book_value": info.get("bookValue"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "free_cash_flow": info.get("freeCashflow"),
            "total_debt": info.get("totalDebt"),
            "total_cash": info.get("totalCash"),
        }

        logger.info("profile OK: %s (%s)", profile_data["long_name"], ticker_str)
        return {"error": False, "data": profile_data}

    except Exception as exc:
        logger.error("profile failed for %s: %s", ticker_str, exc)
        return {"error": True, "message": f"Failed to fetch profile: {str(exc)}"}


# ---------------------------------------------------------------------------
# Tool: income_statement
# ---------------------------------------------------------------------------
@mcp.tool
def income_statement(
    symbol: str,
    exchange: str = "NSE",
    period: str = "annual",
) -> dict:
    """
    Fetch income statement (P&L) data for a company.

    Args:
        symbol:   Stock ticker (e.g. "RELIANCE", "TCS", "AAPL").
        exchange: "NSE" (default) or "BSE" or "US".
        period:   "annual" (default) or "quarterly".

    Returns:
        List of income statement records with: Total Revenue, Gross Profit,
        Operating Income, EBITDA, Net Income, Basic EPS, Diluted EPS, etc.
    """
    ticker_str = _to_ticker(symbol, exchange)
    logger.info("income_statement: %s, period=%s", ticker_str, period)

    try:
        ticker = yf.Ticker(ticker_str)

        if period == "quarterly":
            df = ticker.quarterly_income_stmt
        else:
            df = ticker.income_stmt

        if df is None or df.empty:
            return {"error": True, "message": f"No income statement data for '{symbol}'."}

        records = _df_to_records(df)

        logger.info("income_statement OK: %s - %d periods", ticker_str, len(records))
        return {
            "error": False,
            "data": {
                "symbol": ticker_str,
                "period": period,
                "total_records": len(records),
                "statements": records,
            },
        }

    except Exception as exc:
        logger.error("income_statement failed for %s: %s", ticker_str, exc)
        return {"error": True, "message": f"Failed: {str(exc)}"}


# ---------------------------------------------------------------------------
# Tool: balance_sheet
# ---------------------------------------------------------------------------
@mcp.tool
def balance_sheet(
    symbol: str,
    exchange: str = "NSE",
    period: str = "annual",
) -> dict:
    """
    Fetch balance sheet data for a company.

    Args:
        symbol:   Stock ticker.
        exchange: "NSE" (default) or "BSE" or "US".
        period:   "annual" (default) or "quarterly".

    Returns:
        List of balance sheet records with: Total Assets, Total Liabilities,
        Stockholders Equity, Total Debt, Cash, Inventory, etc.
    """
    ticker_str = _to_ticker(symbol, exchange)
    logger.info("balance_sheet: %s, period=%s", ticker_str, period)

    try:
        ticker = yf.Ticker(ticker_str)

        if period == "quarterly":
            df = ticker.quarterly_balance_sheet
        else:
            df = ticker.balance_sheet

        if df is None or df.empty:
            return {"error": True, "message": f"No balance sheet data for '{symbol}'."}

        records = _df_to_records(df)

        logger.info("balance_sheet OK: %s - %d periods", ticker_str, len(records))
        return {
            "error": False,
            "data": {
                "symbol": ticker_str,
                "period": period,
                "total_records": len(records),
                "statements": records,
            },
        }

    except Exception as exc:
        logger.error("balance_sheet failed for %s: %s", ticker_str, exc)
        return {"error": True, "message": f"Failed: {str(exc)}"}


# ---------------------------------------------------------------------------
# Tool: cash_flow
# ---------------------------------------------------------------------------
@mcp.tool
def cash_flow(
    symbol: str,
    exchange: str = "NSE",
    period: str = "annual",
) -> dict:
    """
    Fetch cash flow statement for a company.

    Args:
        symbol:   Stock ticker.
        exchange: "NSE" (default) or "BSE" or "US".
        period:   "annual" (default) or "quarterly".

    Returns:
        List of cash flow records with: Operating Cash Flow, Capital Expenditure,
        Free Cash Flow, Investing Cash Flow, Financing Cash Flow, etc.
    """
    ticker_str = _to_ticker(symbol, exchange)
    logger.info("cash_flow: %s, period=%s", ticker_str, period)

    try:
        ticker = yf.Ticker(ticker_str)

        if period == "quarterly":
            df = ticker.quarterly_cashflow
        else:
            df = ticker.cashflow

        if df is None or df.empty:
            return {"error": True, "message": f"No cash flow data for '{symbol}'."}

        records = _df_to_records(df)

        logger.info("cash_flow OK: %s - %d periods", ticker_str, len(records))
        return {
            "error": False,
            "data": {
                "symbol": ticker_str,
                "period": period,
                "total_records": len(records),
                "statements": records,
            },
        }

    except Exception as exc:
        logger.error("cash_flow failed for %s: %s", ticker_str, exc)
        return {"error": True, "message": f"Failed: {str(exc)}"}


# ---------------------------------------------------------------------------
# Tool: key_metrics
# ---------------------------------------------------------------------------
@mcp.tool
def key_metrics(symbol: str, exchange: str = "NSE") -> dict:
    """
    Fetch key financial metrics and ratios for a company.

    Args:
        symbol:   Stock ticker (e.g. "RELIANCE", "HDFCBANK", "AAPL").
        exchange: "NSE" (default) or "BSE" or "US".

    Returns:
        dict with: pe_ratio, pb_ratio, ev_to_ebitda, roe, roa, current_ratio,
        debt_to_equity, dividend_yield, profit_margin, operating_margin,
        revenue_growth, earnings_growth, book_value, free_cash_flow, etc.
    """
    ticker_str, info = _resolve_ticker_and_info(symbol, exchange)
    logger.info("key_metrics: %s", ticker_str)

    try:
        if not info or info.get("regularMarketPrice") is None:
            return {"error": True, "message": f"No data found for '{symbol}'."}

        metrics = {
            "symbol": ticker_str,
            "currency": info.get("currency"),
            # Valuation
            "market_cap": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_book": info.get("priceToBook"),
            "price_to_sales": info.get("priceToSalesTrailing12Months"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            "ev_to_revenue": info.get("enterpriseToRevenue"),
            # Profitability
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "profit_margin": info.get("profitMargins"),
            "ebitda_margins": info.get("ebitdaMargins"),
            # Growth
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "earnings_quarterly_growth": info.get("earningsQuarterlyGrowth"),
            # Per share
            "trailing_eps": info.get("trailingEps"),
            "forward_eps": info.get("forwardEps"),
            "book_value": info.get("bookValue"),
            "revenue_per_share": info.get("revenuePerShare"),
            # Leverage & Liquidity
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
            "total_debt": info.get("totalDebt"),
            "total_cash": info.get("totalCash"),
            "total_cash_per_share": info.get("totalCashPerShare"),
            # Cash flow
            "operating_cash_flow": info.get("operatingCashflow"),
            "free_cash_flow": info.get("freeCashflow"),
            # Dividends
            "dividend_yield": info.get("dividendYield"),
            "dividend_rate": info.get("dividendRate"),
            "payout_ratio": info.get("payoutRatio"),
            "five_year_avg_dividend_yield": info.get("fiveYearAvgDividendYield"),
            # Other
            "beta": info.get("beta"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "float_shares": info.get("floatShares"),
            "short_ratio": info.get("shortRatio"),
        }

        logger.info("key_metrics OK: %s", ticker_str)
        return {"error": False, "data": metrics}

    except Exception as exc:
        logger.error("key_metrics failed for %s: %s", ticker_str, exc)
        return {"error": True, "message": f"Failed: {str(exc)}"}


# ---------------------------------------------------------------------------
# Tool: get_quarterly_results
# ---------------------------------------------------------------------------
@mcp.tool
def get_quarterly_results(symbol: str, exchange: str = "NSE") -> dict:
    """
    Fetch last 4 quarters revenue and profit for a company.

    Args:
        symbol:   Stock ticker (e.g. "TCS", "RELIANCE").
        exchange: "NSE" (default) or "BSE" or "US".

    Returns:
        Last 4 quarterly results with revenue and net income.
    """
    ticker_str = _to_ticker(symbol, exchange)
    logger.info("get_quarterly_results: %s", ticker_str)
    try:
        ticker = yf.Ticker(ticker_str)
        inc = ticker.quarterly_income_stmt
        if inc is None or inc.empty:
            return {"error": True, "message": f"No quarterly data for '{symbol}'."}
        results = []
        for col in inc.columns[:4]:
            period = {"date": col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)}
            for metric in ["Total Revenue", "Net Income", "EBITDA", "Operating Income", "Basic EPS"]:
                if metric in inc.index:
                    val = inc.loc[metric, col]
                    period[metric] = val.item() if hasattr(val, "item") else val
            results.append(period)
        return {"error": False, "data": {"symbol": ticker_str, "quarters": results}}
    except Exception as exc:
        logger.error("get_quarterly_results failed for %s: %s", ticker_str, exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: get_shareholding
# ---------------------------------------------------------------------------
@mcp.tool
def get_shareholding(symbol: str, exchange: str = "NSE") -> dict:
    """
    Fetch shareholding pattern — promoter, FII, DII holdings.

    Args:
        symbol:   Stock ticker (e.g. "TCS", "RELIANCE").
        exchange: "NSE" (default) or "BSE" or "US".

    Returns:
        Major holders and institutional holders breakdown.
    """
    ticker_str = _to_ticker(symbol, exchange)
    logger.info("get_shareholding: %s", ticker_str)
    try:
        ticker = yf.Ticker(ticker_str)
        holders = {}
        mh = ticker.major_holders
        if mh is not None and not mh.empty:
            holder_list = []
            for _, row in mh.iterrows():
                holder_list.append({"value": str(row.iloc[0]), "description": str(row.iloc[1])})
            holders["major_holders"] = holder_list
        ih = ticker.institutional_holders
        if ih is not None and not ih.empty:
            inst = []
            for _, row in ih.head(10).iterrows():
                inst.append({
                    "holder": str(row.get("Holder", "")),
                    "shares": int(row["Shares"]) if "Shares" in row else None,
                    "pct_out": float(row["% Out"]) if "% Out" in row else None,
                })
            holders["institutional_holders"] = inst
        if not holders:
            return {"error": True, "message": f"No shareholding data for '{symbol}'."}
        return {"error": False, "data": {"symbol": ticker_str, **holders}}
    except Exception as exc:
        logger.error("get_shareholding failed for %s: %s", ticker_str, exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: compare_stocks
# ---------------------------------------------------------------------------
@mcp.tool
def compare_stocks(symbols: list[str], exchange: str = "NSE") -> dict:
    """
    Side-by-side ratio comparison of multiple stocks.

    Args:
        symbols:  List of tickers (e.g. ["TCS", "INFY", "WIPRO"]).
        exchange: "NSE" (default) or "BSE" or "US".

    Returns:
        Comparison table with PE, PB, ROE, market cap, margins for each stock.
    """
    logger.info("compare_stocks: %s", symbols)
    comparison = []
    for sym in symbols[:5]:
        ticker_str, info = _resolve_ticker_and_info(sym, exchange)
        try:
            if not info:
                info = _get_info(ticker_str)
            comparison.append({
                "requested_symbol": sym,
                "symbol": ticker_str,
                "name": info.get("shortName"),
                "market_cap": info.get("marketCap"),
                "trailing_pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "price_to_book": info.get("priceToBook"),
                "roe": info.get("returnOnEquity"),
                "profit_margin": info.get("profitMargins"),
                "revenue_growth": info.get("revenueGrowth"),
                "dividend_yield": info.get("dividendYield"),
                "debt_to_equity": info.get("debtToEquity"),
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            })
        except Exception as exc:
            comparison.append({"symbol": ticker_str, "error": str(exc)})
    return {"error": False, "data": {"comparison": comparison}}


# ---------------------------------------------------------------------------
# Tool: get_peer_comparison
# ---------------------------------------------------------------------------
@mcp.tool
def get_peer_comparison(symbol: str, exchange: str = "NSE") -> dict:
    """
    Compare a stock against its sector peers using industry classification.

    Args:
        symbol:   Stock ticker (e.g. "TCS").
        exchange: "NSE" (default) or "BSE" or "US".

    Returns:
        The target stock's metrics alongside sector/industry averages.
    """
    ticker_str, info = _resolve_ticker_and_info(symbol, exchange)
    logger.info("get_peer_comparison: %s", ticker_str)
    try:
        if not info or not info.get("sector"):
            return {"error": True, "message": f"No sector info for '{symbol}'."}
        target = {
            "symbol": ticker_str,
            "name": info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "trailing_pe": info.get("trailingPE"),
            "price_to_book": info.get("priceToBook"),
            "roe": info.get("returnOnEquity"),
            "profit_margin": info.get("profitMargins"),
            "market_cap": info.get("marketCap"),
            "revenue_growth": info.get("revenueGrowth"),
            "dividend_yield": info.get("dividendYield"),
        }
        return {"error": False, "data": {"target": target, "note": "Use compare_stocks with sector peers for full comparison."}}
    except Exception as exc:
        logger.error("get_peer_comparison failed for %s: %s", ticker_str, exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Tool: get_dividend_history
# ---------------------------------------------------------------------------
@mcp.tool
def get_dividend_history(symbol: str, exchange: str = "NSE") -> dict:
    """
    Fetch past dividend payments with dates.

    Args:
        symbol:   Stock ticker (e.g. "TCS", "INFY").
        exchange: "NSE" (default) or "BSE" or "US".

    Returns:
        List of dividend payments with ex-date and amount.
    """
    ticker_str = _to_ticker(symbol, exchange)
    logger.info("get_dividend_history: %s", ticker_str)
    try:
        ticker = yf.Ticker(ticker_str)
        divs = ticker.dividends
        if divs is None or divs.empty:
            return {"error": True, "message": f"No dividend history for '{symbol}'."}
        records = []
        for date_idx, amount in divs.tail(20).items():
            records.append({
                "date": date_idx.strftime("%Y-%m-%d"),
                "dividend": round(float(amount), 2),
            })
        info = _get_info(ticker_str)
        return {
            "error": False,
            "data": {
                "symbol": ticker_str,
                "current_yield": info.get("dividendYield"),
                "annual_rate": info.get("dividendRate"),
                "payout_ratio": info.get("payoutRatio"),
                "history": records,
            },
        }
    except Exception as exc:
        logger.error("get_dividend_history failed for %s: %s", ticker_str, exc)
        return {"error": True, "message": str(exc)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting ORACLE Fundamentals MCP Server (yfinance) ...")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8002)

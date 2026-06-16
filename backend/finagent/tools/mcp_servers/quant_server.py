# quant_server.py
# ==============================================================================
# ORACLE FIOS - Consolidated Quantitative Compute Core (MCP Server)
# Port: 8005
# Merged: Fundamentals (yfinance) + Valuation Engine + Portfolio Risk Engine
# Runs completely independently of the LLM layer with deterministic calculations.
# ==============================================================================

from __future__ import annotations

import os
import re
import shutil
import tempfile
import logging
from functools import lru_cache
from typing import Any
import certifi

# ------------------------------------------------------------------------------
# Fix: curl_cffi / requests CA Cert handling on Windows
# ------------------------------------------------------------------------------
_safe_cacert = os.path.join(tempfile.gettempdir(), "cacert.pem")
try:
    _safe_cacert.encode('ascii')
except UnicodeEncodeError:
    _safe_cacert = "C:\\temp\\cacert.pem"
    os.makedirs("C:\\temp", exist_ok=True)
if not os.path.exists(_safe_cacert):
    shutil.copy2(certifi.where(), _safe_cacert)
os.environ["CURL_CA_BUNDLE"] = _safe_cacert
os.environ["REQUESTS_CA_BUNDLE"] = _safe_cacert
os.environ["SSL_CERT_FILE"] = _safe_cacert

import yfinance as yf
yf.set_tz_cache_location(os.path.join(tempfile.gettempdir(), "yfinance_cache"))

import pandas as pd
import numpy as np
from fastmcp import FastMCP

from finagent.tools import valuation_engine
from finagent.tools.valuation_engine import (
    dcf_valuation, graham_valuation, pe_valuation, ddm_valuation,
    ev_ebitda_valuation, calculate_piotroski_score, calculate_altman_z_score,
    calculate_wacc, calculate_cost_of_equity_capm, dupont_analysis,
    calculate_cagr, analyze_ratios, full_valuation,
)

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("oracle.quant_server")

# ------------------------------------------------------------------------------
# FastMCP Server Instance
# ------------------------------------------------------------------------------
mcp = FastMCP(
    "ORACLE Quantitative Compute Core",
    instructions=(
        "Consolidated Quantitative Compute Core containing Fundamentals, "
        "Valuation models, and the deterministic Portfolio Risk Engine. "
        "Part of the ORACLE Financial Intelligence OS."
    ),
)

# ------------------------------------------------------------------------------
# Helpers from Fundamentals Server
# ------------------------------------------------------------------------------

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

def nse_ticker(symbol: str) -> str:
    """Valuation-specific helper to map to NSE."""
    s = symbol.upper().replace(".NS", "").replace(".BO", "")
    if s in ("^NSEI", "^BSESN", "^GSPC", "^IXIC"):
        return s
    return f"{s}.NS"

def safe(v):
    if v is None:
        return 0
    try:
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            return float(v)
    except Exception:
        pass
    return float(v) if isinstance(v, (int, float)) else 0



def _df_to_records(df, orient: str = "index") -> list[dict]:
    """Convert a pandas DataFrame to a list of dicts suitable for JSON."""
    if df is None or df.empty:
        return []

    records = []
    if orient == "index":
        for col in df.columns:
            period_data = {"date": col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)}
            for metric in df.index:
                val = df.loc[metric, col]
                if hasattr(val, "item"):
                    val = val.item()
                period_data[str(metric)] = val
            records.append(period_data)
    return records

@lru_cache(maxsize=128)
def _get_info(ticker_str: str) -> dict:
    return yf.Ticker(ticker_str).info

@lru_cache(maxsize=128)
def _resolve_ticker_and_info(symbol: str, exchange: str = "NSE") -> tuple[str, dict]:
    ticker_str = _to_ticker(symbol, exchange)
    try:
        info = _get_info(ticker_str)
        return ticker_str, info
    except Exception:
        return ticker_str, {}

@lru_cache(maxsize=64)
def get_stock_data(symbol: str) -> dict:
    """Fetch all required data from yfinance for valuation models."""
    t = yf.Ticker(nse_ticker(symbol))
    info = t.info

    financials = t.financials
    balance = t.balance_sheet
    cashflow = t.cashflow

    def latest(df, key):
        if df is not None and not df.empty and key in df.index:
            return safe(df.loc[key, df.columns[0]])
        return 0

    def prev(df, key):
        if df is not None and not df.empty and key in df.index and len(df.columns) > 1:
            return safe(df.loc[key, df.columns[1]])
        return 0

    shares = safe(info.get("sharesOutstanding", 0))
    shares_cr = shares / 1e7 if shares > 0 else 1

    return {
        "symbol": symbol.upper(),
        "current_price": safe(info.get("currentPrice", info.get("regularMarketPrice", 0))),
        "eps": safe(info.get("trailingEps", 0)),
        "beta": safe(info.get("beta", 1)),
        "dividend_per_share": safe(info.get("dividendRate", 0)),
        "shares_outstanding_cr": round(shares_cr, 2),
        "shares_outstanding_raw": shares,
        "pe": safe(info.get("trailingPE", 0)),
        "pb": safe(info.get("priceToBook", 0)),
        "roe": safe(info.get("returnOnEquity", 0)) * 100,
        "debt_to_equity": safe(info.get("debtToEquity", 0)),
        "revenue_growth": safe(info.get("revenueGrowth", 0)) * 100,
        "profit_margin": safe(info.get("profitMargins", 0)) * 100,
        "sector": info.get("sector", "Unknown"),
        "industry": info.get("industry", "Unknown"),
        "net_income": latest(financials, "Net Income"),
        "revenue": latest(financials, "Total Revenue"),
        "ebitda": latest(financials, "EBITDA"),
        "operating_income": latest(financials, "Operating Income"),
        "prev_net_income": prev(financials, "Net Income"),
        "total_assets": latest(balance, "Total Assets"),
        "prev_total_assets": prev(balance, "Total Assets"),
        "total_liabilities": latest(balance, "Total Liabilities Net Minority Interest"),
        "shareholders_equity": latest(balance, "Stockholders Equity"),
        "total_debt": latest(balance, "Total Debt"),
        "cash": latest(balance, "Cash And Cash Equivalents"),
        "current_assets": latest(balance, "Current Assets"),
        "current_liabilities": latest(balance, "Current Liabilities"),
        "prev_current_assets": prev(balance, "Current Assets"),
        "prev_current_liabilities": prev(balance, "Current Liabilities"),
        "long_term_debt": latest(balance, "Long Term Debt"),
        "prev_long_term_debt": prev(balance, "Long Term Debt"),
        "retained_earnings": latest(balance, "Retained Earnings"),
        "operating_cash_flow": latest(cashflow, "Operating Cash Flow"),
        "free_cash_flow": latest(cashflow, "Free Cash Flow"),
        "gross_profit": latest(financials, "Gross Profit"),
        "prev_gross_profit": prev(financials, "Gross Profit"),
        "prev_revenue": prev(financials, "Total Revenue"),
        "market_cap": safe(info.get("marketCap", 0)),
    }

# ==============================================================================
# SECTION 1: Fundamentals Tools
# ==============================================================================

@mcp.tool()
def profile(symbol: str, exchange: str = "NSE") -> dict:
    """Fetch company profile snapshot (sector, industry, CEO, business summary, description)."""
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
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "previous_close": info.get("previousClose"),
            "52_week_high": info.get("fiftyTwoWeekHigh"),
            "52_week_low": info.get("fiftyTwoWeekLow"),
            "50_day_avg": info.get("fiftyDayAverage"),
            "200_day_avg": info.get("twoHundredDayAverage"),
            "market_cap": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "price_to_book": info.get("priceToBook"),
            "price_to_sales_trailing": info.get("priceToSalesTrailing12Months"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            "ev_to_revenue": info.get("enterpriseToRevenue"),
            "profit_margins": info.get("profitMargins"),
            "operating_margins": info.get("operatingMargins"),
            "gross_margins": info.get("grossMargins"),
            "return_on_equity": info.get("returnOnEquity"),
            "return_on_assets": info.get("returnOnAssets"),
            "dividend_yield": info.get("dividendYield"),
            "dividend_rate": info.get("dividendRate"),
            "payout_ratio": info.get("payoutRatio"),
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
        return {"error": False, "data": profile_data}
    except Exception as exc:
        logger.error("profile failed for %s: %s", ticker_str, exc)
        return {"error": True, "message": f"Failed to fetch profile: {str(exc)}"}

@mcp.tool()
def income_statement(symbol: str, exchange: str = "NSE", period: str = "annual") -> dict:
    """Fetch income statement (P&L) data (revenue, operating income, net income, EPS)."""
    ticker_str = _to_ticker(symbol, exchange)
    try:
        ticker = yf.Ticker(ticker_str)
        df = ticker.quarterly_income_stmt if period == "quarterly" else ticker.income_stmt
        if df is None or df.empty:
            return {"error": True, "message": f"No income statement data for '{symbol}'."}
        records = _df_to_records(df)
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
        return {"error": True, "message": f"Failed: {str(exc)}"}

@mcp.tool()
def balance_sheet(symbol: str, exchange: str = "NSE", period: str = "annual") -> dict:
    """Fetch balance sheet data (assets, liabilities, equity, cash, debt)."""
    ticker_str = _to_ticker(symbol, exchange)
    try:
        ticker = yf.Ticker(ticker_str)
        df = ticker.quarterly_balance_sheet if period == "quarterly" else ticker.balance_sheet
        if df is None or df.empty:
            return {"error": True, "message": f"No balance sheet data for '{symbol}'."}
        records = _df_to_records(df)
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
        return {"error": True, "message": f"Failed: {str(exc)}"}

@mcp.tool()
def cash_flow(symbol: str, exchange: str = "NSE", period: str = "annual") -> dict:
    """Fetch cash flow statement (operating, investing, financing cash flows, capex, FCF)."""
    ticker_str = _to_ticker(symbol, exchange)
    try:
        ticker = yf.Ticker(ticker_str)
        df = ticker.quarterly_cashflow if period == "quarterly" else ticker.cashflow
        if df is None or df.empty:
            return {"error": True, "message": f"No cash flow data for '{symbol}'."}
        records = _df_to_records(df)
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
        return {"error": True, "message": f"Failed: {str(exc)}"}

@mcp.tool()
def key_metrics(symbol: str, exchange: str = "NSE") -> dict:
    """Fetch key financial metrics and valuation ratios (PE, PB, peg_ratio, ROE, debt_to_equity, FCF)."""
    ticker_str, info = _resolve_ticker_and_info(symbol, exchange)
    try:
        if not info or info.get("regularMarketPrice") is None:
            return {"error": True, "message": f"No data found for '{symbol}'."}
        metrics = {
            "symbol": ticker_str,
            "currency": info.get("currency"),
            "market_cap": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_book": info.get("priceToBook"),
            "price_to_sales": info.get("priceToSalesTrailing12Months"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            "ev_to_revenue": info.get("enterpriseToRevenue"),
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
            "gross_margin": info.get("grossMargins"),
            "operating_margin": info.get("operatingMargins"),
            "profit_margin": info.get("profitMargins"),
            "ebitda_margins": info.get("ebitdaMargins"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "trailing_eps": info.get("trailingEps"),
            "forward_eps": info.get("forwardEps"),
            "book_value": info.get("bookValue"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "quick_ratio": info.get("quickRatio"),
            "total_debt": info.get("totalDebt"),
            "total_cash": info.get("totalCash"),
            "free_cash_flow": info.get("freeCashflow"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "shares_outstanding": info.get("sharesOutstanding"),
        }
        return {"error": False, "data": metrics}
    except Exception as exc:
        return {"error": True, "message": f"Failed: {str(exc)}"}

@mcp.tool()
def get_quarterly_results(symbol: str, exchange: str = "NSE") -> dict:
    """Fetch last 4 quarters revenue and profit for a stock."""
    ticker_str = _to_ticker(symbol, exchange)
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
        return {"error": True, "message": str(exc)}

@mcp.tool()
def get_shareholding(symbol: str, exchange: str = "NSE") -> dict:
    """Fetch shareholding pattern — promoter, institutional, FII, DII holdings."""
    ticker_str = _to_ticker(symbol, exchange)
    try:
        ticker = yf.Ticker(ticker_str)
        holders = {}
        mh = ticker.major_holders
        if mh is not None and not mh.empty:
            holders["major_holders"] = [{"value": str(row.iloc[0]), "description": str(row.iloc[1])} for _, row in mh.iterrows()]
        ih = ticker.institutional_holders
        if ih is not None and not ih.empty:
            holders["institutional_holders"] = [{
                "holder": str(row.get("Holder", "")),
                "shares": int(row["Shares"]) if "Shares" in row else None,
                "pct_out": float(row["% Out"]) if "% Out" in row else None,
            } for _, row in ih.head(10).iterrows()]
        if not holders:
            return {"error": True, "message": f"No shareholding data for '{symbol}'."}
        return {"error": False, "data": {"symbol": ticker_str, **holders}}
    except Exception as exc:
        return {"error": True, "message": str(exc)}

@mcp.tool()
def compare_stocks(symbols: list[str], exchange: str = "NSE") -> dict:
    """Side-by-side ratio comparison of multiple stocks."""
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

@mcp.tool()
def get_peer_comparison(symbol: str, exchange: str = "NSE") -> dict:
    """Compare a stock against its sector peers."""
    ticker_str, info = _resolve_ticker_and_info(symbol, exchange)
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
        return {"error": True, "message": str(exc)}

@mcp.tool()
def get_dividend_history(symbol: str, exchange: str = "NSE") -> dict:
    """Fetch past 20 dividend payments with dates and amounts."""
    ticker_str = _to_ticker(symbol, exchange)
    try:
        ticker = yf.Ticker(ticker_str)
        divs = ticker.dividends
        if divs is None or divs.empty:
            return {"error": True, "message": f"No dividend history for '{symbol}'."}
        records = [{"date": date_idx.strftime("%Y-%m-%d"), "dividend": round(float(amount), 2)} for date_idx, amount in divs.tail(20).items()]
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
        return {"error": True, "message": str(exc)}

# ==============================================================================
# SECTION 2: Valuation Tools
# ==============================================================================

@mcp.tool()
def run_dcf_valuation(
    symbol: str,
    growth_rate_high: float = 0.12,
    growth_rate_stable: float = 0.06,
    high_growth_years: int = 5,
    discount_rate: float = 0,
    terminal_growth_rate: float = 0.04,
) -> dict:
    """Run DCF valuation. Automatically fetches FCF, shares, debt, cash from yfinance."""
    data = get_stock_data(symbol)
    if data["free_cash_flow"] == 0:
        return {"error": f"No FCF data for {symbol}. Cannot run DCF."}

    if discount_rate == 0:
        capm = calculate_cost_of_equity_capm(0.072, data["beta"], 0.13)
        wacc = calculate_wacc(
            data["market_cap"], data["total_debt"],
            capm["cost_of_equity"], 0.09, 0.25,
        )
        discount_rate = wacc["wacc"]

    result = dcf_valuation(
        free_cash_flow=data["free_cash_flow"],
        growth_rate_high=growth_rate_high,
        growth_rate_stable=growth_rate_stable,
        high_growth_years=high_growth_years,
        discount_rate=discount_rate,
        terminal_growth_rate=terminal_growth_rate,
        shares_outstanding=data["shares_outstanding_raw"],
        net_debt=data["total_debt"] - data["cash"],
    )

    result["current_price"] = data["current_price"]
    if result.get("intrinsic_value_per_share") and data["current_price"] > 0:
        iv = result["intrinsic_value_per_share"]
        result["upside_pct"] = round(((iv - data["current_price"]) / data["current_price"]) * 100, 2)
        result["valuation_context"] = (
            "below_model_implied_value" if iv > data["current_price"] * 1.1
            else "near_model_implied_value" if iv > data["current_price"] * 0.9
            else "above_model_implied_value"
        )
    return result

@mcp.tool()
def run_graham_valuation(symbol: str, expected_growth: float = 0) -> dict:
    """Run Benjamin Graham's intrinsic value formula."""
    data = get_stock_data(symbol)
    if data["eps"] <= 0:
        return {"error": f"EPS is negative/zero for {symbol}. Graham formula needs positive EPS."}
    growth = expected_growth if expected_growth > 0 else max(data["revenue_growth"], 5)
    return graham_valuation(
        eps=data["eps"],
        growth_rate=growth,
        aaa_bond_yield=0.0725,
        current_price=data["current_price"],
    )

@mcp.tool()
def run_pe_valuation(symbol: str, sector_avg_pe: float = 0) -> dict:
    """Run PE-based relative valuation."""
    data = get_stock_data(symbol)
    if data["eps"] <= 0:
        return {"error": f"Negative EPS for {symbol}. PE valuation not applicable."}
    s_pe = sector_avg_pe if sector_avg_pe > 0 else data["pe"] * 0.85
    growth = data["revenue_growth"] / 100 if data["revenue_growth"] > 0 else 0.10
    return pe_valuation(
        eps=data["eps"],
        sector_avg_pe=s_pe,
        historical_avg_pe=data["pe"],
        current_pe=data["pe"],
        current_price=data["current_price"],
        eps_growth_rate=growth,
    )

@mcp.tool()
def run_ev_ebitda_valuation(symbol: str, sector_avg_ev_ebitda: float = 15) -> dict:
    """Run EV/EBITDA valuation."""
    data = get_stock_data(symbol)
    if data["ebitda"] <= 0:
        return {"error": f"No EBITDA data for {symbol}."}
    return ev_ebitda_valuation(
        ebitda=data["ebitda"],
        sector_avg_ev_ebitda=sector_avg_ev_ebitda,
        total_debt=data["total_debt"],
        cash=data["cash"],
        shares_outstanding=data["shares_outstanding_raw"],
        current_price=data["current_price"],
    )

@mcp.tool()
def run_ddm_valuation(symbol: str, dividend_growth: float = 0.08) -> dict:
    """Run Dividend Discount Model (DDM)."""
    data = get_stock_data(symbol)
    if data["dividend_per_share"] <= 0:
        return {"error": f"{symbol} doesn't pay dividends. DDM not applicable."}
    capm = calculate_cost_of_equity_capm(0.072, data["beta"], 0.13)
    return ddm_valuation(
        dividend_per_share=data["dividend_per_share"],
        dividend_growth_rate=dividend_growth,
        required_return=capm["cost_of_equity"],
        current_price=data["current_price"],
        high_growth_rate=data["revenue_growth"] / 100 if data["revenue_growth"] > 5 else 0.10,
        high_growth_years=5,
    )

@mcp.tool()
def run_piotroski_score(symbol: str) -> dict:
    """Calculate Piotroski F-Score (0-9) to assess financial strength."""
    data = get_stock_data(symbol)
    ta = data["total_assets"] or 1
    prev_ta = data["prev_total_assets"] or 1
    rev = data["revenue"] or 1
    prev_rev = data["prev_revenue"] or 1
    cl = data["current_liabilities"] or 1
    prev_cl = data["prev_current_liabilities"] or 1

    return calculate_piotroski_score(
        net_income=data["net_income"],
        operating_cash_flow=data["operating_cash_flow"],
        roa_current=data["net_income"] / ta,
        roa_previous=data["prev_net_income"] / prev_ta,
        long_term_debt_current=data["long_term_debt"],
        long_term_debt_previous=data["prev_long_term_debt"],
        current_ratio_current=data["current_assets"] / cl,
        current_ratio_previous=data["prev_current_assets"] / prev_cl,
        shares_current=data["shares_outstanding_raw"],
        shares_previous=data["shares_outstanding_raw"],
        gross_margin_current=data["gross_profit"] / rev,
        gross_margin_previous=data["prev_gross_profit"] / prev_rev,
        asset_turnover_current=rev / ta,
        asset_turnover_previous=prev_rev / prev_ta,
    )

@mcp.tool()
def run_altman_z_score(symbol: str) -> dict:
    """Calculate Altman Z-Score to assess bankruptcy risk."""
    data = get_stock_data(symbol)
    working_capital = data["current_assets"] - data["current_liabilities"]
    return calculate_altman_z_score(
        working_capital=working_capital,
        total_assets=data["total_assets"],
        retained_earnings=data["retained_earnings"],
        ebit=data["operating_income"],
        market_cap=data["market_cap"],
        total_liabilities=data["total_liabilities"],
        revenue=data["revenue"],
    )

@mcp.tool()
def run_dupont_analysis(symbol: str) -> dict:
    """Decompose ROE into Profit Margin, Asset Turnover, and Equity Multiplier."""
    data = get_stock_data(symbol)
    return dupont_analysis(
        net_income=data["net_income"],
        revenue=data["revenue"],
        total_assets=data["total_assets"],
        shareholders_equity=data["shareholders_equity"],
    )

@mcp.tool()
def run_ratio_scorecard(symbol: str) -> dict:
    """Score a stock on 8 fundamental metrics (0-16 points) with research context."""
    data = get_stock_data(symbol)
    cl = data["current_liabilities"] or 1
    return analyze_ratios(
        pe=data["pe"],
        pb=data["pb"],
        roe=data["roe"],
        debt_to_equity=data["debt_to_equity"],
        current_ratio=data["current_assets"] / cl,
        dividend_yield=(data["dividend_per_share"] / data["current_price"] * 100) if data["current_price"] > 0 else 0,
        profit_margin=data["profit_margin"],
        revenue_growth=data["revenue_growth"],
        sector=data["sector"],
    )

@mcp.tool()
def run_full_valuation(
    symbol: str, 
    growth_rate: float = 0.12, 
    sector_avg_pe: float = 25, 
    sector_avg_ev_ebitda: float = 15
) -> dict:
    """Run ALL valuation models at once (DCF, Graham, PE, EV/EBITDA, DDM, DuPont)."""
    data = get_stock_data(symbol)
    return full_valuation(
        symbol=symbol.upper(),
        current_price=data["current_price"],
        eps=data["eps"],
        free_cash_flow=data["free_cash_flow"],
        shares_outstanding=data["shares_outstanding_raw"],
        total_debt=data["total_debt"],
        cash=data["cash"],
        ebitda=data["ebitda"],
        net_income=data["net_income"],
        revenue=data["revenue"],
        total_assets=data["total_assets"],
        shareholders_equity=data["shareholders_equity"],
        dividend_per_share=data["dividend_per_share"],
        beta=data["beta"],
        growth_rate=growth_rate,
        sector_avg_pe=sector_avg_pe,
        sector_avg_ev_ebitda=sector_avg_ev_ebitda,
    )

@mcp.tool()
def run_cagr(beginning_value: float, ending_value: float, years: float) -> dict:
    """Calculate CAGR (Compound Annual Growth Rate)."""
    return calculate_cagr(beginning_value, ending_value, years)

@mcp.tool()
def run_wacc(symbol: str) -> dict:
    """Calculate WACC (Weighted Average Cost of Capital) for a stock."""
    data = get_stock_data(symbol)
    capm = calculate_cost_of_equity_capm(0.072, data["beta"], 0.13)
    return calculate_wacc(
        market_cap=data["market_cap"],
        total_debt=data["total_debt"],
        cost_of_equity=capm["cost_of_equity"],
        cost_of_debt=0.09,
        tax_rate=0.25,
    )

# ==============================================================================
# SECTION 3: New Portfolio Risk Engine
# ==============================================================================

def compute_hhi(weights: dict[str, float]) -> dict:
    """Calculates the Herfindahl-Hirschman Index (HHI)."""
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("Total portfolio weight must be greater than zero.")
    
    weights_normalized = {sym.upper(): w / total for sym, w in weights.items()}
    hhi_decimal = sum(w**2 for w in weights_normalized.values())
    hhi_scaled = hhi_decimal * 10000
    
    if hhi_scaled < 1500:
        concentration = "Low (Highly Diversified)"
    elif hhi_scaled < 2500:
        concentration = "Moderate Concentration"
    else:
        concentration = "High (Concentrated)"
        
    effective_assets = 1.0 / hhi_decimal
    
    return {
        "weights_normalized": weights_normalized,
        "hhi_decimal": round(hhi_decimal, 6),
        "hhi_scaled": round(hhi_scaled, 2),
        "concentration_level": concentration,
        "effective_number_of_assets": round(effective_assets, 2)
    }

def get_portfolio_historical_data(tickers: list[str], benchmark: str, lookback_period: str = "1y") -> pd.DataFrame:
    """Downloads daily adjusted close prices and computes returns for assets and benchmark."""
    benchmark = benchmark.upper()
    all_tickers = list(set([nse_ticker(t) for t in tickers] + [nse_ticker(benchmark)]))
    
    ticker_map = {}
    for t in tickers:
        ticker_map[nse_ticker(t)] = t.upper()
    ticker_map[nse_ticker(benchmark)] = benchmark
    
    logger.info("Downloading historical prices for portfolio risk calculation: %s", all_tickers)
    
    df = yf.download(all_tickers, period=lookback_period, progress=False)
    if df.empty:
        raise ValueError("Failed to retrieve price data from yfinance.")
        
    if "Adj Close" in df:
        prices = df["Adj Close"]
    elif "Close" in df:
        prices = df["Close"]
    else:
        raise ValueError("Close / Adj Close column missing in downloaded data.")
        
    if isinstance(prices, pd.Series):
        prices = prices.to_frame(name=all_tickers[0])
        
    prices = prices.rename(columns=ticker_map)
    
    # Filter out columns that are entirely NaN (e.g. failed downloads)
    valid_cols = [col for col in prices.columns if not prices[col].isna().all()]
    if not valid_cols:
        raise ValueError("All tickers failed to download valid price data.")
    prices = prices[valid_cols]
    
    # Defensive price matrix cleaning: forward-fill then backward-fill
    prices = prices.ffill().bfill().fillna(0.0)
    
    # Compute returns and fill NaN with 0.0 (prevents dropping date rows)
    returns = prices.pct_change().fillna(0.0)
    return returns

def _ledoit_wolf_covariance(returns: pd.DataFrame) -> pd.DataFrame:
    """Daily Ledoit-Wolf covariance via PyPortfolioOpt, with pandas fallback."""
    clean_returns = returns.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    try:
        from pypfopt import risk_models

        cov = risk_models.CovarianceShrinkage(
            clean_returns,
            returns_data=True,
            frequency=1,
        ).ledoit_wolf()
        if isinstance(cov, pd.DataFrame) and not cov.empty:
            return cov.reindex(index=clean_returns.columns, columns=clean_returns.columns).fillna(0.0)
    except Exception as exc:
        logger.warning("PyPortfolioOpt Ledoit-Wolf covariance unavailable, falling back to pandas covariance: %s", exc)
    return clean_returns.cov()

def compute_portfolio_beta(returns: pd.DataFrame, weights_normalized: dict[str, float], benchmark: str) -> dict:
    """Computes weighted beta and systemic volatility."""
    benchmark = benchmark.upper()
    if benchmark not in returns.columns:
        raise ValueError(f"Benchmark {benchmark} data is missing from returns DataFrame.")
        
    cov_matrix = _ledoit_wolf_covariance(returns)
    benchmark_var = cov_matrix.loc[benchmark, benchmark]
    
    if benchmark_var <= 0 or pd.isna(benchmark_var):
        raise ValueError(f"Benchmark variance is invalid: {benchmark_var}")
        
    asset_betas = {}
    for sym in weights_normalized.keys():
        if sym == benchmark:
            asset_betas[sym] = 1.0
        elif sym in returns.columns:
            asset_betas[sym] = cov_matrix.loc[sym, benchmark] / benchmark_var
        else:
            asset_betas[sym] = 1.0 # fallback
            
    portfolio_beta = sum(weights_normalized[sym] * asset_betas[sym] for sym in weights_normalized.keys())
    
    benchmark_vol_annual = returns[benchmark].std() * np.sqrt(252)
    systemic_vol_annual = portfolio_beta * benchmark_vol_annual
    
    asset_cols = [sym for sym in weights_normalized.keys() if sym in returns.columns]
    w_vec = np.array([weights_normalized[sym] for sym in asset_cols])
    cov_assets = cov_matrix.loc[asset_cols, asset_cols]
    
    portfolio_var_daily = np.dot(w_vec, np.dot(cov_assets, w_vec))
    portfolio_vol_annual = np.sqrt(portfolio_var_daily) * np.sqrt(252)
    
    if portfolio_vol_annual > abs(systemic_vol_annual):
        idiosyncratic_vol_annual = np.sqrt(portfolio_vol_annual**2 - systemic_vol_annual**2)
    else:
        idiosyncratic_vol_annual = 0.0
        
    return {
        "asset_betas": {sym: round(b, 4) for sym, b in asset_betas.items()},
        "portfolio_beta": round(portfolio_beta, 4),
        "benchmark_annual_volatility_pct": round(benchmark_vol_annual * 100, 2),
        "portfolio_annual_volatility_pct": round(portfolio_vol_annual * 100, 2),
        "systemic_volatility_pct": round(systemic_vol_annual * 100, 2),
        "idiosyncratic_volatility_pct": round(idiosyncratic_vol_annual * 100, 2)
    }

def compute_ccb(weights_normalized: dict[str, float], asset_betas: dict[str, float], portfolio_beta: float) -> dict:
    """Computes Component Contribution to Beta."""
    ccb_absolute = {}
    ccb_percentage = {}
    
    for sym, w in weights_normalized.items():
        beta = asset_betas.get(sym, 1.0)
        abs_contrib = w * beta
        ccb_absolute[sym] = abs_contrib
        ccb_percentage[sym] = (abs_contrib / portfolio_beta * 100) if abs(portfolio_beta) > 0 else 0.0
        
    return {
        "ccb_absolute": {sym: round(val, 6) for sym, val in ccb_absolute.items()},
        "ccb_percentage": {sym: round(val, 2) for sym, val in ccb_percentage.items()}
    }

def compute_portfolio_var(
    returns: pd.DataFrame, 
    weights_normalized: dict[str, float], 
    confidence_level: float = 0.95,
    portfolio_value: float = 0.0
) -> dict:
    """Computes 95% (or custom) Parametric VaR with marginal and component risk contributions."""
    asset_cols = [sym for sym in weights_normalized.keys() if sym in returns.columns]
    w_vec = np.array([weights_normalized[sym] for sym in asset_cols])
    
    cov_matrix = _ledoit_wolf_covariance(returns)
    cov_assets = cov_matrix.loc[asset_cols, asset_cols]
    
    portfolio_var_daily = np.dot(w_vec, np.dot(cov_assets, w_vec))
    portfolio_vol_daily = np.sqrt(portfolio_var_daily)
    
    lookup = {
        0.90: 1.28155,
        0.95: 1.64485,
        0.975: 1.95996,
        0.99: 2.32635
    }
    z_score = lookup.get(confidence_level, 1.64485)
    
    var_daily_pct = z_score * portfolio_vol_daily
    var_5day_pct = var_daily_pct * np.sqrt(5)
    var_21day_pct = var_daily_pct * np.sqrt(21)
    var_252day_pct = var_daily_pct * np.sqrt(252)
    
    sigma_w = np.dot(cov_assets, w_vec)
    
    marginal_var = {}
    component_var = {}
    component_var_pct = {}
    
    for idx, sym in enumerate(asset_cols):
        mvar = z_score * (sigma_w[idx] / portfolio_vol_daily) if portfolio_vol_daily > 0 else 0.0
        marginal_var[sym] = mvar
        cvar = weights_normalized[sym] * mvar
        component_var[sym] = cvar
        component_var_pct[sym] = (cvar / var_daily_pct * 100) if abs(var_daily_pct) > 0 else 0.0
        
    var_results = {
        "confidence_level": confidence_level,
        "z_score": z_score,
        "var_daily_pct": round(var_daily_pct * 100, 4),
        "var_5day_pct": round(var_5day_pct * 100, 4),
        "var_21day_pct": round(var_21day_pct * 100, 4),
        "var_252day_pct": round(var_252day_pct * 100, 4),
        "marginal_var_pct": {sym: round(m * 100, 4) for sym, m in marginal_var.items()},
        "component_var_pct_contribution": {sym: round(p, 2) for sym, p in component_var_pct.items()},
        "component_var_daily_pct": {sym: round(c * 100, 4) for sym, c in component_var.items()}
    }
    
    if portfolio_value > 0:
        var_results.update({
            "portfolio_value": portfolio_value,
            "var_daily_currency": round(var_daily_pct * portfolio_value, 2),
            "var_5day_currency": round(var_5day_pct * portfolio_value, 2),
            "var_21day_currency": round(var_21day_pct * portfolio_value, 2),
            "var_252day_currency": round(var_252day_pct * portfolio_value, 2),
            "component_var_daily_currency": {sym: round(c * portfolio_value, 2) for sym, c in component_var.items()}
        })
        
    return var_results

@mcp.tool()
def run_portfolio_hhi(weights: dict[str, float]) -> dict:
    """
    Calculate the Herfindahl-Hirschman Index (HHI) for asset weights.
    HHI measures portfolio concentration.
    weights maps ticker (str) to weight (float). Example: {"RELIANCE": 0.40, "TCS": 0.60}
    """
    try:
        return compute_hhi(weights)
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def run_portfolio_beta(weights: dict[str, float], benchmark: str = "^NSEI", lookback_period: str = "1y") -> dict:
    """
    Calculate individual asset betas and the weighted portfolio beta relative to a index benchmark.
    weights maps ticker (str) to weight (float). Example: {"RELIANCE": 0.4, "TCS": 0.6}
    """
    try:
        hhi_res = compute_hhi(weights)
        weights_normalized = hhi_res["weights_normalized"]
        returns = get_portfolio_historical_data(list(weights.keys()), benchmark, lookback_period)
        beta_res = compute_portfolio_beta(returns, weights_normalized, benchmark)
        return beta_res
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def run_portfolio_ccb(weights: dict[str, float], benchmark: str = "^NSEI", lookback_period: str = "1y") -> dict:
    """
    Calculate Component Contribution to Beta (CCB) of assets.
    Shows the relative risk contribution of each component to portfolio systemic risk.
    """
    try:
        hhi_res = compute_hhi(weights)
        weights_normalized = hhi_res["weights_normalized"]
        returns = get_portfolio_historical_data(list(weights.keys()), benchmark, lookback_period)
        beta_res = compute_portfolio_beta(returns, weights_normalized, benchmark)
        ccb_res = compute_ccb(weights_normalized, beta_res["asset_betas"], beta_res["portfolio_beta"])
        return ccb_res
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def run_portfolio_var(
    weights: dict[str, float], 
    benchmark: str = "^NSEI", 
    lookback_period: str = "1y", 
    confidence_level: float = 0.95,
    portfolio_value: float = 0.0
) -> dict:
    """
    Calculate 95% (or custom) Parametric Value-at-Risk (VaR) matrix and decomposition.
    """
    try:
        hhi_res = compute_hhi(weights)
        weights_normalized = hhi_res["weights_normalized"]
        returns = get_portfolio_historical_data(list(weights.keys()), benchmark, lookback_period)
        asset_returns = returns[[sym for sym in weights_normalized.keys() if sym in returns.columns]]
        var_res = compute_portfolio_var(asset_returns, weights_normalized, confidence_level, portfolio_value)
        return var_res
    except Exception as e:
        return {"error": str(e)}

@mcp.tool()
def run_full_portfolio_risk(
    weights: dict[str, float], 
    benchmark: str = "^NSEI", 
    lookback_period: str = "1y", 
    portfolio_value: float = 0.0
) -> dict:
    """
    Execute a consolidated Portfolio Risk Analysis covering HHI, Beta, CCB, and 95% Parametric VaR.
    This runs completely deterministically on quantitative asset matrices.
    """
    try:
        hhi_res = compute_hhi(weights)
        weights_normalized = hhi_res["weights_normalized"]
        returns = get_portfolio_historical_data(list(weights.keys()), benchmark, lookback_period)
        
        beta_res = compute_portfolio_beta(returns, weights_normalized, benchmark)
        ccb_res = compute_ccb(weights_normalized, beta_res["asset_betas"], beta_res["portfolio_beta"])
        
        asset_returns = returns[[sym for sym in weights_normalized.keys() if sym in returns.columns]]
        var_res = compute_portfolio_var(asset_returns, weights_normalized, 0.95, portfolio_value)
        
        return {
            "hhi_analysis": hhi_res,
            "beta_analysis": beta_res,
            "ccb_analysis": ccb_res,
            "var_analysis": var_res,
            "lookback_period": lookback_period,
            "benchmark_used": benchmark.upper()
        }
    except Exception as e:
        return {"error": str(e)}

# ------------------------------------------------------------------------------
# Entry Point
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting ORACLE Quantitative Compute Core MCP Server on Port 8005 ...")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8005)

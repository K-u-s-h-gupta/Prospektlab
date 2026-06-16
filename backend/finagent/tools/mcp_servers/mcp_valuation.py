# mcp_valuation.py
# =================
# MCP Server that wraps valuation_engine.py
# LLM calls these tools → gets exact math results → explains to user

from __future__ import annotations

import os
import shutil
import tempfile
from functools import lru_cache

import certifi

# Match the fundamentals server's Windows-safe TLS handling for yfinance.
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

from fastmcp import FastMCP
from finagent.tools import valuation_engine
from finagent.tools.valuation_engine import (
    dcf_valuation, graham_valuation, pe_valuation, ddm_valuation,
    ev_ebitda_valuation, calculate_piotroski_score, calculate_altman_z_score,
    calculate_wacc, calculate_cost_of_equity_capm, dupont_analysis,
    calculate_cagr, analyze_ratios, full_valuation,
)

mcp = FastMCP("ORACLE Valuation Engine")


def nse_ticker(symbol: str) -> str:
    s = symbol.upper().replace(".NS", "").replace(".BO", "")
    return f"{s}.NS"


def safe(v):
    if v is None:
        return 0
    try:
        import numpy as np
        if isinstance(v, (np.integer,)):
            return int(v)
        if isinstance(v, (np.floating,)):
            return float(v)
    except ImportError:
        pass
    return float(v) if isinstance(v, (int, float)) else 0


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
    if shares > 0:
        shares_cr = shares / 1e7  # Convert to crores
    else:
        shares_cr = 1

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


# -------------------------------------------------------
# MCP Tools — LLM calls these
# -------------------------------------------------------

@mcp.tool()
def run_dcf_valuation(
    symbol: str,
    growth_rate_high: float = 0.12,
    growth_rate_stable: float = 0.06,
    high_growth_years: int = 5,
    discount_rate: float = 0,
    terminal_growth_rate: float = 0.04,
) -> dict:
    """Run DCF valuation on an Indian stock. Automatically fetches FCF,
    shares, debt, cash from yfinance. Override growth assumptions if needed.
    Returns intrinsic value per share with margin of safety prices."""
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
    """Run Graham intrinsic value formula on an Indian stock.
    Fetches EPS automatically. Provide expected_growth as percentage (e.g., 15 = 15%).
    If not provided, uses revenue growth from yfinance."""
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
    """Run PE-based relative valuation. Fetches EPS and current PE automatically.
    Provide sector_avg_pe or it will use a default estimate."""
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
    """Run EV/EBITDA valuation. Fetches EBITDA, debt, cash automatically."""
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
    """Run Dividend Discount Model. Only works for dividend-paying stocks."""
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
    """Calculate Piotroski F-Score (0-9) for financial strength assessment."""
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
    """Decompose ROE into Profit Margin × Asset Turnover × Equity Multiplier."""
    data = get_stock_data(symbol)
    return dupont_analysis(
        net_income=data["net_income"],
        revenue=data["revenue"],
        total_assets=data["total_assets"],
        shareholders_equity=data["shareholders_equity"],
    )


@mcp.tool()
def run_ratio_scorecard(symbol: str) -> dict:
    """Score a stock on 8 fundamental metrics (0-16 points) with verdict."""
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
def run_full_valuation(symbol: str, growth_rate: float = 0.12, sector_avg_pe: float = 25, sector_avg_ev_ebitda: float = 15) -> dict:
    """Run ALL valuation models at once — DCF, Graham, PE, EV/EBITDA, DDM, DuPont.
    Returns combined report with average intrinsic value and verdict.
    This is the recommended tool for comprehensive stock analysis."""
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
    """Calculate CAGR (Compound Annual Growth Rate) between two values."""
    return calculate_cagr(beginning_value, ending_value, years)


@mcp.tool()
def run_wacc(symbol: str) -> dict:
    """Calculate WACC for a stock using CAPM for cost of equity."""
    data = get_stock_data(symbol)
    capm = calculate_cost_of_equity_capm(0.072, data["beta"], 0.13)
    return calculate_wacc(
        market_cap=data["market_cap"],
        total_debt=data["total_debt"],
        cost_of_equity=capm["cost_of_equity"],
        cost_of_debt=0.09,
        tax_rate=0.25,
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8005)

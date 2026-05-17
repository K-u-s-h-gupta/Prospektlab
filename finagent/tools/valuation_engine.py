# valuation_engine.py
# =====================
# Deterministic financial calculation engine for ORACLE
# LLM NEVER does math — it calls these functions with inputs,
# gets exact outputs, then explains them in natural language.
#
# Architecture:
#   User: "What's the intrinsic value of TCS?"
#   LLM decides: I need DCF → calls get_financials() for inputs → calls dcf_valuation()
#   Engine: runs exact math → returns {"intrinsic_value": 4250.32, "upside": "12.3%", ...}
#   LLM: explains the result in plain English with the exact numbers

from dataclasses import dataclass
from typing import Optional
import math


# ============================================================
# 1. DCF (Discounted Cash Flow) Valuation
# ============================================================

def dcf_valuation(
    free_cash_flow: float,
    growth_rate_high: float,
    growth_rate_stable: float,
    high_growth_years: int,
    discount_rate: float,
    terminal_growth_rate: float,
    shares_outstanding: float,
    net_debt: float = 0,
    cash_and_equivalents: float = 0,
) -> dict:
    """
    Multi-stage DCF valuation model.

    Args:
        free_cash_flow: Latest annual Free Cash Flow (in crores or absolute)
        growth_rate_high: Expected FCF growth rate for high-growth phase (e.g., 0.15 = 15%)
        growth_rate_stable: Expected FCF growth rate for stable phase (e.g., 0.08 = 8%)
        high_growth_years: Number of years for high growth (typically 5)
        discount_rate: WACC or required rate of return (e.g., 0.12 = 12%)
        terminal_growth_rate: Long-term perpetual growth rate (e.g., 0.04 = 4%)
        shares_outstanding: Total shares outstanding
        net_debt: Total debt minus cash (positive = debt, negative = net cash)
        cash_and_equivalents: Cash on balance sheet (if net_debt not provided)

    Returns:
        dict with intrinsic value per share, margin of safety prices, and full breakdown
    """
    if discount_rate <= terminal_growth_rate:
        return {"error": "Discount rate must be greater than terminal growth rate"}

    if shares_outstanding <= 0:
        return {"error": "Shares outstanding must be positive"}

    projected_fcf = []
    pv_fcf = []
    fcf = free_cash_flow

    # Phase 1: High growth period
    for year in range(1, high_growth_years + 1):
        fcf = fcf * (1 + growth_rate_high)
        pv = fcf / ((1 + discount_rate) ** year)
        projected_fcf.append({
            "year": year,
            "fcf": round(fcf, 2),
            "present_value": round(pv, 2),
            "growth_rate": growth_rate_high,
            "phase": "high_growth",
        })
        pv_fcf.append(pv)

    # Phase 2: Stable growth (5 more years)
    stable_years = 5
    for i in range(stable_years):
        year = high_growth_years + i + 1
        fcf = fcf * (1 + growth_rate_stable)
        pv = fcf / ((1 + discount_rate) ** year)
        projected_fcf.append({
            "year": year,
            "fcf": round(fcf, 2),
            "present_value": round(pv, 2),
            "growth_rate": growth_rate_stable,
            "phase": "stable_growth",
        })
        pv_fcf.append(pv)

    total_projection_years = high_growth_years + stable_years

    # Terminal Value (Gordon Growth Model)
    terminal_fcf = fcf * (1 + terminal_growth_rate)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth_rate)
    pv_terminal = terminal_value / ((1 + discount_rate) ** total_projection_years)

    # Enterprise Value
    sum_pv_fcf = sum(pv_fcf)
    enterprise_value = sum_pv_fcf + pv_terminal

    # Equity Value
    equity_value = enterprise_value - net_debt + cash_and_equivalents

    # Per Share
    intrinsic_value_per_share = equity_value / shares_outstanding

    return {
        "model": "DCF (Multi-Stage)",
        "intrinsic_value_per_share": round(intrinsic_value_per_share, 2),
        "margin_of_safety_25pct": round(intrinsic_value_per_share * 0.75, 2),
        "margin_of_safety_50pct": round(intrinsic_value_per_share * 0.50, 2),
        "enterprise_value": round(enterprise_value, 2),
        "equity_value": round(equity_value, 2),
        "sum_of_pv_fcf": round(sum_pv_fcf, 2),
        "terminal_value": round(terminal_value, 2),
        "pv_terminal_value": round(pv_terminal, 2),
        "terminal_value_pct": round((pv_terminal / enterprise_value) * 100, 2),
        "projected_fcf": projected_fcf,
        "assumptions": {
            "base_fcf": free_cash_flow,
            "high_growth_rate": growth_rate_high,
            "stable_growth_rate": growth_rate_stable,
            "high_growth_years": high_growth_years,
            "discount_rate_wacc": discount_rate,
            "terminal_growth_rate": terminal_growth_rate,
            "shares_outstanding": shares_outstanding,
            "net_debt": net_debt,
        },
    }


# ============================================================
# 2. Graham's Intrinsic Value Formula
# ============================================================

def graham_valuation(
    eps: float,
    growth_rate: float,
    aaa_bond_yield: float = 0.0725,
    current_price: Optional[float] = None,
) -> dict:
    """
    Benjamin Graham's intrinsic value formula.
    V = EPS × (8.5 + 2g) × 4.4 / Y

    Args:
        eps: Earnings Per Share (trailing 12 months)
        growth_rate: Expected annual EPS growth rate for next 7-10 years (e.g., 15 = 15%)
        aaa_bond_yield: Current AAA corporate bond yield (default 7.25% for India)
        current_price: Current stock price (optional, for upside calculation)
    """
    if eps <= 0:
        return {"error": "Graham formula works best with positive EPS", "eps": eps}

    if aaa_bond_yield <= 0:
        return {"error": "Bond yield must be positive"}

    intrinsic_value = (eps * (8.5 + 2 * growth_rate) * 4.4) / (aaa_bond_yield * 100)

    result = {
        "model": "Graham's Intrinsic Value",
        "formula": "V = EPS × (8.5 + 2g) × 4.4 / Y",
        "intrinsic_value": round(intrinsic_value, 2),
        "margin_of_safety_25pct": round(intrinsic_value * 0.75, 2),
        "margin_of_safety_50pct": round(intrinsic_value * 0.50, 2),
        "assumptions": {
            "eps": eps,
            "growth_rate_pct": growth_rate,
            "pe_no_growth": 8.5,
            "aaa_bond_yield_pct": aaa_bond_yield * 100,
        },
    }

    if current_price and current_price > 0:
        upside = ((intrinsic_value - current_price) / current_price) * 100
        result["current_price"] = current_price
        result["upside_pct"] = round(upside, 2)
        result["verdict"] = "UNDERVALUED" if upside > 0 else "OVERVALUED"

    return result


# ============================================================
# 3. PE-Based (Relative) Valuation
# ============================================================

def pe_valuation(
    eps: float,
    sector_avg_pe: float,
    historical_avg_pe: float,
    current_pe: float,
    current_price: float,
    eps_growth_rate: float = 0,
) -> dict:
    """
    PE multiple-based relative valuation.

    Calculates fair value using sector average PE, historical average PE,
    and PEG-adjusted PE.

    Args:
        eps: Current EPS (TTM)
        sector_avg_pe: Average PE of sector/industry peers
        historical_avg_pe: Stock's own 5-year average PE
        current_pe: Current PE ratio
        current_price: Current stock price
        eps_growth_rate: Expected EPS growth rate (e.g., 0.15 = 15%) for PEG
    """
    fair_value_sector = eps * sector_avg_pe
    fair_value_historical = eps * historical_avg_pe

    result = {
        "model": "PE Relative Valuation",
        "current_price": current_price,
        "current_pe": current_pe,
        "eps_ttm": eps,
        "valuations": {
            "sector_avg_pe_basis": {
                "fair_value": round(fair_value_sector, 2),
                "pe_used": sector_avg_pe,
                "upside_pct": round(((fair_value_sector - current_price) / current_price) * 100, 2),
            },
            "historical_avg_pe_basis": {
                "fair_value": round(fair_value_historical, 2),
                "pe_used": historical_avg_pe,
                "upside_pct": round(((fair_value_historical - current_price) / current_price) * 100, 2),
            },
        },
    }

    if eps_growth_rate > 0:
        peg_ratio = current_pe / (eps_growth_rate * 100)
        fair_pe_peg = eps_growth_rate * 100  # PEG = 1 fair value
        fair_value_peg = eps * fair_pe_peg
        result["valuations"]["peg_basis"] = {
            "peg_ratio": round(peg_ratio, 2),
            "fair_pe_at_peg_1": round(fair_pe_peg, 2),
            "fair_value": round(fair_value_peg, 2),
            "upside_pct": round(((fair_value_peg - current_price) / current_price) * 100, 2),
            "peg_verdict": "UNDERVALUED" if peg_ratio < 1 else ("FAIRLY VALUED" if peg_ratio < 1.5 else "OVERVALUED"),
        }

    avg_fair = (fair_value_sector + fair_value_historical) / 2
    result["average_fair_value"] = round(avg_fair, 2)
    result["overall_upside_pct"] = round(((avg_fair - current_price) / current_price) * 100, 2)

    return result


# ============================================================
# 4. Dividend Discount Model (DDM)
# ============================================================

def ddm_valuation(
    dividend_per_share: float,
    dividend_growth_rate: float,
    required_return: float,
    current_price: Optional[float] = None,
    high_growth_rate: Optional[float] = None,
    high_growth_years: int = 5,
) -> dict:
    """
    Dividend Discount Model — Gordon Growth & Multi-Stage.

    Args:
        dividend_per_share: Current annual dividend per share
        dividend_growth_rate: Expected long-term dividend growth rate (e.g., 0.08 = 8%)
        required_return: Investor's required rate of return (e.g., 0.12 = 12%)
        current_price: Current stock price (optional)
        high_growth_rate: Initial high dividend growth rate for multi-stage (optional)
        high_growth_years: Years of high growth before stable phase
    """
    if required_return <= dividend_growth_rate:
        return {"error": "Required return must be > dividend growth rate for Gordon model"}

    if dividend_per_share <= 0:
        return {"error": "Company must pay dividends for DDM", "dividend": dividend_per_share}

    # Gordon Growth Model (single stage)
    gordon_value = (dividend_per_share * (1 + dividend_growth_rate)) / (required_return - dividend_growth_rate)

    result = {
        "model": "Dividend Discount Model",
        "gordon_growth_value": round(gordon_value, 2),
    }

    # Multi-stage DDM if high_growth_rate provided
    if high_growth_rate and high_growth_rate > dividend_growth_rate:
        pv_dividends = []
        div = dividend_per_share
        total_pv = 0

        for year in range(1, high_growth_years + 1):
            div = div * (1 + high_growth_rate)
            pv = div / ((1 + required_return) ** year)
            total_pv += pv
            pv_dividends.append({
                "year": year, "dividend": round(div, 2), "pv": round(pv, 2)
            })

        # Terminal value at end of high growth
        terminal_div = div * (1 + dividend_growth_rate)
        terminal_value = terminal_div / (required_return - dividend_growth_rate)
        pv_terminal = terminal_value / ((1 + required_return) ** high_growth_years)

        multi_stage_value = total_pv + pv_terminal

        result["multi_stage_value"] = round(multi_stage_value, 2)
        result["pv_high_growth_dividends"] = round(total_pv, 2)
        result["pv_terminal_value"] = round(pv_terminal, 2)
        result["projected_dividends"] = pv_dividends

    if current_price and current_price > 0:
        best_value = result.get("multi_stage_value", gordon_value)
        result["current_price"] = current_price
        result["upside_pct"] = round(((best_value - current_price) / current_price) * 100, 2)
        result["dividend_yield"] = round((dividend_per_share / current_price) * 100, 2)

    result["assumptions"] = {
        "dividend_per_share": dividend_per_share,
        "long_term_growth": dividend_growth_rate,
        "required_return": required_return,
        "high_growth_rate": high_growth_rate,
        "high_growth_years": high_growth_years,
    }

    return result


# ============================================================
# 5. EV/EBITDA Valuation
# ============================================================

def ev_ebitda_valuation(
    ebitda: float,
    sector_avg_ev_ebitda: float,
    total_debt: float,
    cash: float,
    shares_outstanding: float,
    current_price: Optional[float] = None,
    historical_avg_ev_ebitda: Optional[float] = None,
) -> dict:
    """
    Enterprise Value / EBITDA multiple valuation.

    Args:
        ebitda: Annual EBITDA
        sector_avg_ev_ebitda: Sector average EV/EBITDA multiple
        total_debt: Total debt on balance sheet
        cash: Cash and cash equivalents
        shares_outstanding: Total shares outstanding
        current_price: Current stock price (optional)
        historical_avg_ev_ebitda: Stock's own historical EV/EBITDA (optional)
    """
    fair_ev = ebitda * sector_avg_ev_ebitda
    fair_equity = fair_ev - total_debt + cash
    fair_value_per_share = fair_equity / shares_outstanding

    result = {
        "model": "EV/EBITDA Valuation",
        "sector_basis": {
            "fair_ev": round(fair_ev, 2),
            "fair_equity_value": round(fair_equity, 2),
            "fair_value_per_share": round(fair_value_per_share, 2),
            "ev_ebitda_used": sector_avg_ev_ebitda,
        },
    }

    if historical_avg_ev_ebitda:
        hist_ev = ebitda * historical_avg_ev_ebitda
        hist_equity = hist_ev - total_debt + cash
        hist_per_share = hist_equity / shares_outstanding
        result["historical_basis"] = {
            "fair_ev": round(hist_ev, 2),
            "fair_equity_value": round(hist_equity, 2),
            "fair_value_per_share": round(hist_per_share, 2),
            "ev_ebitda_used": historical_avg_ev_ebitda,
        }

    if current_price and current_price > 0:
        current_mcap = current_price * shares_outstanding
        current_ev = current_mcap + total_debt - cash
        current_ev_ebitda = current_ev / ebitda if ebitda > 0 else None
        result["current_metrics"] = {
            "current_price": current_price,
            "current_market_cap": round(current_mcap, 2),
            "current_ev": round(current_ev, 2),
            "current_ev_ebitda": round(current_ev_ebitda, 2) if current_ev_ebitda else None,
        }
        result["upside_pct"] = round(((fair_value_per_share - current_price) / current_price) * 100, 2)

    return result


# ============================================================
# 6. Financial Health Scores (Deterministic)
# ============================================================

def calculate_piotroski_score(
    net_income: float,
    operating_cash_flow: float,
    roa_current: float,
    roa_previous: float,
    long_term_debt_current: float,
    long_term_debt_previous: float,
    current_ratio_current: float,
    current_ratio_previous: float,
    shares_current: float,
    shares_previous: float,
    gross_margin_current: float,
    gross_margin_previous: float,
    asset_turnover_current: float,
    asset_turnover_previous: float,
) -> dict:
    """
    Piotroski F-Score (0-9) — measures financial strength.
    Used by value investors to filter quality stocks.

    Each criterion scores 1 (pass) or 0 (fail).
    Score 8-9 = Strong, 5-7 = Moderate, 0-4 = Weak
    """
    scores = {}

    # Profitability (4 points)
    scores["positive_net_income"] = 1 if net_income > 0 else 0
    scores["positive_operating_cf"] = 1 if operating_cash_flow > 0 else 0
    scores["roa_improving"] = 1 if roa_current > roa_previous else 0
    scores["cf_greater_than_income"] = 1 if operating_cash_flow > net_income else 0

    # Leverage / Liquidity (3 points)
    scores["debt_decreasing"] = 1 if long_term_debt_current < long_term_debt_previous else 0
    scores["current_ratio_improving"] = 1 if current_ratio_current > current_ratio_previous else 0
    scores["no_dilution"] = 1 if shares_current <= shares_previous else 0

    # Efficiency (2 points)
    scores["gross_margin_improving"] = 1 if gross_margin_current > gross_margin_previous else 0
    scores["asset_turnover_improving"] = 1 if asset_turnover_current > asset_turnover_previous else 0

    total = sum(scores.values())

    if total >= 8:
        verdict = "STRONG — High quality value stock"
    elif total >= 5:
        verdict = "MODERATE — Mixed signals"
    else:
        verdict = "WEAK — Potential value trap"

    return {
        "model": "Piotroski F-Score",
        "total_score": total,
        "max_score": 9,
        "verdict": verdict,
        "breakdown": {
            "profitability": {
                "positive_net_income": scores["positive_net_income"],
                "positive_operating_cf": scores["positive_operating_cf"],
                "roa_improving": scores["roa_improving"],
                "cf_greater_than_income": scores["cf_greater_than_income"],
                "subtotal": sum([scores["positive_net_income"], scores["positive_operating_cf"],
                                 scores["roa_improving"], scores["cf_greater_than_income"]]),
            },
            "leverage_liquidity": {
                "debt_decreasing": scores["debt_decreasing"],
                "current_ratio_improving": scores["current_ratio_improving"],
                "no_dilution": scores["no_dilution"],
                "subtotal": sum([scores["debt_decreasing"], scores["current_ratio_improving"],
                                 scores["no_dilution"]]),
            },
            "efficiency": {
                "gross_margin_improving": scores["gross_margin_improving"],
                "asset_turnover_improving": scores["asset_turnover_improving"],
                "subtotal": sum([scores["gross_margin_improving"], scores["asset_turnover_improving"]]),
            },
        },
    }


def calculate_altman_z_score(
    working_capital: float,
    total_assets: float,
    retained_earnings: float,
    ebit: float,
    market_cap: float,
    total_liabilities: float,
    revenue: float,
) -> dict:
    """
    Altman Z-Score — predicts bankruptcy probability.

    Z = 1.2A + 1.4B + 3.3C + 0.6D + 1.0E
    Where:
        A = Working Capital / Total Assets
        B = Retained Earnings / Total Assets
        C = EBIT / Total Assets
        D = Market Cap / Total Liabilities
        E = Revenue / Total Assets
    """
    if total_assets <= 0 or total_liabilities <= 0:
        return {"error": "Total assets and liabilities must be positive"}

    a = working_capital / total_assets
    b = retained_earnings / total_assets
    c = ebit / total_assets
    d = market_cap / total_liabilities
    e = revenue / total_assets

    z_score = 1.2 * a + 1.4 * b + 3.3 * c + 0.6 * d + 1.0 * e

    if z_score > 2.99:
        zone = "SAFE ZONE — Low bankruptcy risk"
    elif z_score > 1.81:
        zone = "GREY ZONE — Moderate risk, monitor closely"
    else:
        zone = "DISTRESS ZONE — High bankruptcy risk"

    return {
        "model": "Altman Z-Score",
        "z_score": round(z_score, 4),
        "zone": zone,
        "components": {
            "A_working_capital_ratio": round(a, 4),
            "B_retained_earnings_ratio": round(b, 4),
            "C_ebit_ratio": round(c, 4),
            "D_market_cap_to_liabilities": round(d, 4),
            "E_asset_turnover": round(e, 4),
        },
        "weighted_components": {
            "1.2A": round(1.2 * a, 4),
            "1.4B": round(1.4 * b, 4),
            "3.3C": round(3.3 * c, 4),
            "0.6D": round(0.6 * d, 4),
            "1.0E": round(1.0 * e, 4),
        },
        "thresholds": {
            "safe": "> 2.99",
            "grey": "1.81 - 2.99",
            "distress": "< 1.81",
        },
    }


# ============================================================
# 7. WACC Calculator (needed for DCF discount rate)
# ============================================================

def calculate_wacc(
    market_cap: float,
    total_debt: float,
    cost_of_equity: float,
    cost_of_debt: float,
    tax_rate: float,
) -> dict:
    """
    Weighted Average Cost of Capital.

    WACC = (E/V × Re) + (D/V × Rd × (1-T))

    Args:
        market_cap: Market capitalization (equity value)
        total_debt: Total debt
        cost_of_equity: Required return on equity (e.g., 0.14 = 14%)
        cost_of_debt: Interest rate on debt (e.g., 0.09 = 9%)
        tax_rate: Corporate tax rate (e.g., 0.25 = 25%)
    """
    total_value = market_cap + total_debt
    if total_value <= 0:
        return {"error": "Total value must be positive"}

    equity_weight = market_cap / total_value
    debt_weight = total_debt / total_value
    wacc = (equity_weight * cost_of_equity) + (debt_weight * cost_of_debt * (1 - tax_rate))

    return {
        "model": "WACC",
        "wacc": round(wacc, 6),
        "wacc_pct": round(wacc * 100, 2),
        "equity_weight": round(equity_weight, 4),
        "debt_weight": round(debt_weight, 4),
        "after_tax_cost_of_debt": round(cost_of_debt * (1 - tax_rate), 4),
        "inputs": {
            "market_cap": market_cap,
            "total_debt": total_debt,
            "cost_of_equity": cost_of_equity,
            "cost_of_debt": cost_of_debt,
            "tax_rate": tax_rate,
        },
    }


def calculate_cost_of_equity_capm(
    risk_free_rate: float,
    beta: float,
    market_return: float,
) -> dict:
    """
    CAPM: Cost of Equity = Rf + β(Rm - Rf)

    Args:
        risk_free_rate: 10-year govt bond yield (e.g., 0.072 = 7.2% for India)
        beta: Stock's beta
        market_return: Expected market return (e.g., 0.13 = 13% for Nifty long-term)
    """
    equity_risk_premium = market_return - risk_free_rate
    cost_of_equity = risk_free_rate + beta * equity_risk_premium

    return {
        "model": "CAPM",
        "cost_of_equity": round(cost_of_equity, 6),
        "cost_of_equity_pct": round(cost_of_equity * 100, 2),
        "equity_risk_premium": round(equity_risk_premium, 4),
        "inputs": {
            "risk_free_rate": risk_free_rate,
            "beta": beta,
            "market_return": market_return,
        },
    }


# ============================================================
# 8. DuPont Analysis (ROE Decomposition)
# ============================================================

def dupont_analysis(
    net_income: float,
    revenue: float,
    total_assets: float,
    shareholders_equity: float,
) -> dict:
    """
    DuPont 3-factor ROE decomposition.
    ROE = Profit Margin × Asset Turnover × Equity Multiplier
    """
    if revenue <= 0 or total_assets <= 0 or shareholders_equity <= 0:
        return {"error": "All inputs must be positive"}

    profit_margin = net_income / revenue
    asset_turnover = revenue / total_assets
    equity_multiplier = total_assets / shareholders_equity
    roe = profit_margin * asset_turnover * equity_multiplier

    return {
        "model": "DuPont Analysis (3-Factor)",
        "roe": round(roe, 4),
        "roe_pct": round(roe * 100, 2),
        "components": {
            "profit_margin": round(profit_margin, 4),
            "profit_margin_pct": round(profit_margin * 100, 2),
            "asset_turnover": round(asset_turnover, 4),
            "equity_multiplier": round(equity_multiplier, 4),
        },
        "interpretation": {
            "profit_margin": "How much profit per ₹1 of revenue",
            "asset_turnover": "How efficiently assets generate revenue",
            "equity_multiplier": "Financial leverage (higher = more debt)",
        },
        "formula": "ROE = {:.2f}% × {:.2f} × {:.2f} = {:.2f}%".format(
            profit_margin * 100, asset_turnover, equity_multiplier, roe * 100
        ),
    }


# ============================================================
# 9. Compound Growth Calculators
# ============================================================

def calculate_cagr(
    beginning_value: float,
    ending_value: float,
    years: float,
) -> dict:
    """CAGR = (Ending/Beginning)^(1/n) - 1"""
    if beginning_value <= 0 or ending_value <= 0 or years <= 0:
        return {"error": "All values must be positive"}

    cagr = (ending_value / beginning_value) ** (1 / years) - 1

    return {
        "model": "CAGR",
        "cagr": round(cagr, 6),
        "cagr_pct": round(cagr * 100, 2),
        "beginning_value": beginning_value,
        "ending_value": ending_value,
        "years": years,
        "total_growth_pct": round(((ending_value - beginning_value) / beginning_value) * 100, 2),
    }


def calculate_future_value(
    present_value: float,
    growth_rate: float,
    years: int,
) -> dict:
    """FV = PV × (1 + r)^n"""
    future_value = present_value * ((1 + growth_rate) ** years)
    yearly = []
    val = present_value
    for y in range(1, years + 1):
        val = val * (1 + growth_rate)
        yearly.append({"year": y, "value": round(val, 2)})

    return {
        "model": "Future Value",
        "future_value": round(future_value, 2),
        "present_value": present_value,
        "growth_rate": growth_rate,
        "years": years,
        "total_growth_pct": round(((future_value - present_value) / present_value) * 100, 2),
        "year_by_year": yearly,
    }


# ============================================================
# 10. Quick Ratio Analysis
# ============================================================

def analyze_ratios(
    pe: float,
    pb: float,
    roe: float,
    debt_to_equity: float,
    current_ratio: float,
    dividend_yield: float,
    profit_margin: float,
    revenue_growth: float,
    sector: str = "Unknown",
) -> dict:
    """
    Deterministic ratio analysis with scoring.
    Each metric gets a score: Good (2), Moderate (1), Poor (0).
    """
    scores = {}

    # PE Ratio
    if pe < 15:
        scores["pe"] = {"value": pe, "score": 2, "label": "Attractive"}
    elif pe < 25:
        scores["pe"] = {"value": pe, "score": 1, "label": "Fair"}
    else:
        scores["pe"] = {"value": pe, "score": 0, "label": "Expensive"}

    # PB Ratio
    if pb < 2:
        scores["pb"] = {"value": pb, "score": 2, "label": "Attractive"}
    elif pb < 4:
        scores["pb"] = {"value": pb, "score": 1, "label": "Fair"}
    else:
        scores["pb"] = {"value": pb, "score": 0, "label": "Expensive"}

    # ROE
    if roe > 20:
        scores["roe"] = {"value": roe, "score": 2, "label": "Excellent"}
    elif roe > 12:
        scores["roe"] = {"value": roe, "score": 1, "label": "Good"}
    else:
        scores["roe"] = {"value": roe, "score": 0, "label": "Poor"}

    # Debt to Equity
    if debt_to_equity < 0.5:
        scores["debt_to_equity"] = {"value": debt_to_equity, "score": 2, "label": "Low debt"}
    elif debt_to_equity < 1.0:
        scores["debt_to_equity"] = {"value": debt_to_equity, "score": 1, "label": "Moderate"}
    else:
        scores["debt_to_equity"] = {"value": debt_to_equity, "score": 0, "label": "High debt"}

    # Current Ratio
    if current_ratio > 2:
        scores["current_ratio"] = {"value": current_ratio, "score": 2, "label": "Strong"}
    elif current_ratio > 1:
        scores["current_ratio"] = {"value": current_ratio, "score": 1, "label": "Adequate"}
    else:
        scores["current_ratio"] = {"value": current_ratio, "score": 0, "label": "Risky"}

    # Dividend Yield
    if dividend_yield > 3:
        scores["dividend_yield"] = {"value": dividend_yield, "score": 2, "label": "High yield"}
    elif dividend_yield > 1:
        scores["dividend_yield"] = {"value": dividend_yield, "score": 1, "label": "Moderate"}
    else:
        scores["dividend_yield"] = {"value": dividend_yield, "score": 0, "label": "Low/None"}

    # Profit Margin
    if profit_margin > 20:
        scores["profit_margin"] = {"value": profit_margin, "score": 2, "label": "High margin"}
    elif profit_margin > 10:
        scores["profit_margin"] = {"value": profit_margin, "score": 1, "label": "Moderate"}
    else:
        scores["profit_margin"] = {"value": profit_margin, "score": 0, "label": "Low margin"}

    # Revenue Growth
    if revenue_growth > 15:
        scores["revenue_growth"] = {"value": revenue_growth, "score": 2, "label": "High growth"}
    elif revenue_growth > 5:
        scores["revenue_growth"] = {"value": revenue_growth, "score": 1, "label": "Moderate"}
    else:
        scores["revenue_growth"] = {"value": revenue_growth, "score": 0, "label": "Slow/Decline"}

    total_score = sum(s["score"] for s in scores.values())
    max_score = len(scores) * 2

    if total_score >= 13:
        overall = "STRONG BUY — Excellent fundamentals"
    elif total_score >= 10:
        overall = "BUY — Good fundamentals"
    elif total_score >= 7:
        overall = "HOLD — Mixed signals"
    else:
        overall = "AVOID — Weak fundamentals"

    return {
        "model": "Fundamental Ratio Scorecard",
        "total_score": total_score,
        "max_score": max_score,
        "score_pct": round((total_score / max_score) * 100, 1),
        "verdict": overall,
        "sector": sector,
        "metrics": scores,
    }


# ============================================================
# MASTER FUNCTION — Auto-valuation with all models
# ============================================================

def full_valuation(
    symbol: str,
    current_price: float,
    eps: float,
    free_cash_flow: float,
    shares_outstanding: float,
    total_debt: float,
    cash: float,
    ebitda: float,
    net_income: float,
    revenue: float,
    total_assets: float,
    shareholders_equity: float,
    dividend_per_share: float,
    beta: float,
    growth_rate: float,
    sector_avg_pe: float,
    sector_avg_ev_ebitda: float,
) -> dict:
    """
    Run ALL valuation models at once and return a combined report.
    The LLM calls this single function with data from yfinance,
    and gets a complete valuation report back.
    """
    results = {"symbol": symbol, "current_price": current_price}

    # 1. CAPM → Cost of Equity
    capm = calculate_cost_of_equity_capm(
        risk_free_rate=0.072,  # India 10Y bond
        beta=beta,
        market_return=0.13,    # Nifty long-term ~13%
    )
    cost_of_equity = capm["cost_of_equity"]

    # 2. WACC
    market_cap = current_price * shares_outstanding
    wacc_result = calculate_wacc(
        market_cap=market_cap,
        total_debt=total_debt,
        cost_of_equity=cost_of_equity,
        cost_of_debt=0.09,
        tax_rate=0.25,
    )
    wacc = wacc_result["wacc"]

    # 3. DCF
    results["dcf"] = dcf_valuation(
        free_cash_flow=free_cash_flow,
        growth_rate_high=growth_rate,
        growth_rate_stable=max(growth_rate * 0.5, 0.05),
        high_growth_years=5,
        discount_rate=wacc,
        terminal_growth_rate=0.04,
        shares_outstanding=shares_outstanding,
        net_debt=total_debt - cash,
    )

    # 4. Graham
    results["graham"] = graham_valuation(
        eps=eps,
        growth_rate=growth_rate * 100,
        current_price=current_price,
    )

    # 5. PE Relative
    historical_pe = current_price / eps if eps > 0 else 0
    results["pe_valuation"] = pe_valuation(
        eps=eps,
        sector_avg_pe=sector_avg_pe,
        historical_avg_pe=historical_pe,
        current_pe=historical_pe,
        current_price=current_price,
        eps_growth_rate=growth_rate,
    )

    # 6. EV/EBITDA
    if ebitda > 0:
        results["ev_ebitda"] = ev_ebitda_valuation(
            ebitda=ebitda,
            sector_avg_ev_ebitda=sector_avg_ev_ebitda,
            total_debt=total_debt,
            cash=cash,
            shares_outstanding=shares_outstanding,
            current_price=current_price,
        )

    # 7. DDM (only if dividends exist)
    if dividend_per_share > 0:
        results["ddm"] = ddm_valuation(
            dividend_per_share=dividend_per_share,
            dividend_growth_rate=0.08,
            required_return=cost_of_equity,
            current_price=current_price,
            high_growth_rate=growth_rate,
            high_growth_years=5,
        )

    # 8. DuPont
    results["dupont"] = dupont_analysis(
        net_income=net_income,
        revenue=revenue,
        total_assets=total_assets,
        shareholders_equity=shareholders_equity,
    )

    # 9. Supporting calcs
    results["wacc"] = wacc_result
    results["capm"] = capm

    # 10. Summary — collect all intrinsic values
    intrinsic_values = {}
    if "dcf" in results and "intrinsic_value_per_share" in results["dcf"]:
        intrinsic_values["DCF"] = results["dcf"]["intrinsic_value_per_share"]
    if "graham" in results and "intrinsic_value" in results["graham"]:
        intrinsic_values["Graham"] = results["graham"]["intrinsic_value"]
    if "pe_valuation" in results and "average_fair_value" in results["pe_valuation"]:
        intrinsic_values["PE_Relative"] = results["pe_valuation"]["average_fair_value"]
    if "ev_ebitda" in results:
        ev_val = results["ev_ebitda"].get("sector_basis", {}).get("fair_value_per_share")
        if ev_val:
            intrinsic_values["EV_EBITDA"] = ev_val
    if "ddm" in results:
        ddm_val = results["ddm"].get("multi_stage_value") or results["ddm"].get("gordon_growth_value")
        if ddm_val:
            intrinsic_values["DDM"] = ddm_val

    if intrinsic_values:
        avg_intrinsic = sum(intrinsic_values.values()) / len(intrinsic_values)
        results["summary"] = {
            "intrinsic_values_by_model": intrinsic_values,
            "average_intrinsic_value": round(avg_intrinsic, 2),
            "current_price": current_price,
            "upside_pct": round(((avg_intrinsic - current_price) / current_price) * 100, 2),
            "margin_of_safety_25pct": round(avg_intrinsic * 0.75, 2),
            "verdict": (
                "UNDERVALUED" if avg_intrinsic > current_price * 1.15
                else "FAIRLY VALUED" if avg_intrinsic > current_price * 0.85
                else "OVERVALUED"
            ),
        }

    return results


# ============================================================
# EXAMPLE: How the LLM uses this
# ============================================================

if __name__ == "__main__":
    import json

    # Simulated: LLM fetched this data from yfinance MCP
    result = full_valuation(
        symbol="TCS",
        current_price=4125,
        eps=124.5,
        free_cash_flow=42000,     # crores
        shares_outstanding=366,    # crores
        total_debt=5000,           # crores
        cash=45000,                # crores
        ebitda=58000,              # crores
        net_income=45600,          # crores
        revenue=240000,            # crores
        total_assets=120000,       # crores
        shareholders_equity=85000, # crores
        dividend_per_share=75,
        beta=0.6,
        growth_rate=0.12,
        sector_avg_pe=25,
        sector_avg_ev_ebitda=18,
    )

    print(json.dumps(result["summary"], indent=2))

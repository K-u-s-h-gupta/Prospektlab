"""Agent-specific context factory functions.

Each function queries the relevant data sources and returns a compact,
agent-specific context block that is injected ONLY into the relevant agent.
This prevents context bloat and keeps each agent focused on its domain.
"""

from __future__ import annotations

import logging
from typing import Any

from finagent.ikg.service import IKGCompanyBundle

logger = logging.getLogger("finagent.agents.context_loaders")


async def load_governance_context(
    cin: str | None,
    ticker: str | None = None,
    ikg_bundle: IKGCompanyBundle | None = None,
) -> dict[str, Any]:
    """Load governance context: IKG subgraph + pledge trends + governance flags.

    Returns:
        dict with keys: ikg_subgraph, pledge_summary, director_history, enforcement_actions
    """
    context: dict[str, Any] = {
        "cin": cin,
        "ticker": ticker,
        "ikg_subgraph": None,
        "pledge_summary": None,
        "director_history": [],
        "enforcement_actions": [],
        "data_sources": [],
    }

    if ikg_bundle is not None:
        context["ikg_subgraph"] = {
            "company": ikg_bundle.company,
            "directors": ikg_bundle.governance.get("directors") or [],
            "promoters": ikg_bundle.ownership.get("promoters") or [],
            "enforcement_actions": ikg_bundle.risk.get("enforcement_actions") or [],
            "audit_firm": ikg_bundle.governance.get("audit_firm") or [],
        }
        context["pledge_summary"] = ikg_bundle.ownership.get("pledge_summary")
        context["director_history"] = ikg_bundle.governance.get("director_history") or []
        context["enforcement_actions"] = ikg_bundle.risk.get("enforcement_actions") or []
        context["data_sources"].append("ikg_bundle")
        return context

    if cin:
        try:
            from finagent.ikg.graph_client import get_graph_client
            client = get_graph_client()
            if client:
                subgraph = await client.get_company_subgraph(cin)
                context["ikg_subgraph"] = subgraph
                context["pledge_summary"] = await client.get_pledge_risk(cin)
                context["director_history"] = await client.get_director_history(cin)
                context["enforcement_actions"] = await client.get_enforcement_actions(cin)
                context["data_sources"].append("ikg_graph")
        except Exception as exc:
            logger.debug("IKG governance context unavailable for CIN %s: %s", cin, exc)

    return context


async def load_valuation_context(
    ticker: str | None,
    cin: str | None = None,
    ikg_bundle: IKGCompanyBundle | None = None,
) -> dict[str, Any]:
    """Load valuation context: normalized financials + comparable multiples + WACC params.

    Returns:
        dict with keys: financials_5yr, peer_multiples, wacc_params, sector
    """
    context: dict[str, Any] = {
        "ticker": ticker,
        "cin": cin,
        "financials_5yr": None,
        "peer_multiples": None,
        "wacc_params": {
            "risk_free_rate": 0.072,      # India 10Y gilt
            "equity_risk_premium": 0.055,  # India ERP
            "market_return": 0.13,         # Nifty long-term CAGR
        },
        "data_sources": [],
    }

    if ikg_bundle is not None:
        fin_data = ikg_bundle.financials.get("company_financials")
        if fin_data:
            context["financials_5yr"] = fin_data
            context["data_sources"].append("ikg_bundle")
            return context

    if ticker:
        try:
            from finagent.ikg.graph_client import get_graph_client
            client = get_graph_client()
            if client:
                fin_data = await client.get_company_financials(ticker)
                if fin_data:
                    context["financials_5yr"] = fin_data
                    context["data_sources"].append("ikg_financials")
        except Exception as exc:
            logger.debug("IKG valuation context unavailable for ticker %s: %s", ticker, exc)

    return context


async def load_risk_context(
    ticker: str | None,
    cin: str | None = None,
    ikg_bundle: IKGCompanyBundle | None = None,
) -> dict[str, Any]:
    """Load risk context: beta/volatility + sector cyclicality + pledge exposure.

    Returns:
        dict with keys: beta, volatility_30d, pledge_pct, sector_cyclicality
    """
    context: dict[str, Any] = {
        "ticker": ticker,
        "cin": cin,
        "beta": None,
        "volatility_30d": None,
        "pledge_pct": None,
        "sector_cyclicality": "unknown",
        "risk_flags": [],
        "data_sources": [],
    }

    if ikg_bundle is not None:
        pledge_data = ikg_bundle.ownership.get("pledge_summary") or {}
        context["pledge_pct"] = pledge_data.get("total_pledge_pct")
        if pledge_data.get("total_pledge_pct", 0) > 50:
            context["risk_flags"].append("HIGH_PLEDGE_RISK: promoter pledge >50%")
        elif pledge_data.get("total_pledge_pct", 0) > 25:
            context["risk_flags"].append("MODERATE_PLEDGE_RISK: promoter pledge >25%")
        enforcement_actions = ikg_bundle.risk.get("enforcement_actions") or []
        if enforcement_actions:
            context["risk_flags"].append(f"ENFORCEMENT_HISTORY: {len(enforcement_actions)} linked action(s)")
        context["data_sources"].append("ikg_bundle")
        return context

    if cin:
        try:
            from finagent.ikg.graph_client import get_graph_client
            client = get_graph_client()
            if client:
                pledge_data = await client.get_pledge_risk(cin)
                if pledge_data:
                    context["pledge_pct"] = pledge_data.get("total_pledge_pct")
                    if pledge_data.get("total_pledge_pct", 0) > 50:
                        context["risk_flags"].append("HIGH_PLEDGE_RISK: promoter pledge >50%")
                    elif pledge_data.get("total_pledge_pct", 0) > 25:
                        context["risk_flags"].append("MODERATE_PLEDGE_RISK: promoter pledge >25%")
                    context["data_sources"].append("ikg_pledge_data")
        except Exception as exc:
            logger.debug("IKG risk context unavailable for CIN %s: %s", cin, exc)

    return context


async def load_news_context(ticker: str | None, days: int = 90) -> dict[str, Any]:
    """Load news context: last N days of verified news items + management commentary.

    Returns:
        dict with keys: recent_news_items, management_commentary, verified_count
    """
    return {
        "ticker": ticker,
        "days_window": days,
        "recent_news_items": [],
        "management_commentary": [],
        "verified_count": 0,
        "data_sources": ["real_time_search"],
    }


async def load_financials_context(
    ticker: str | None,
    cin: str | None = None,
    ikg_bundle: IKGCompanyBundle | None = None,
) -> dict[str, Any]:
    """Load financials context: normalized multi-year P&L, BS, CF data.

    Returns:
        dict with keys: income_statement, balance_sheet, cash_flow, ratios
    """
    context: dict[str, Any] = {
        "ticker": ticker,
        "cin": cin,
        "income_statement": None,
        "balance_sheet": None,
        "cash_flow": None,
        "ratios": None,
        "data_sources": [],
    }

    if ikg_bundle is not None:
        fin_data = ikg_bundle.financials.get("company_financials") or {}
        if fin_data:
            context["income_statement"] = fin_data.get("income_statement")
            context["balance_sheet"] = fin_data.get("balance_sheet")
            context["cash_flow"] = fin_data.get("cash_flow")
            context["ratios"] = fin_data.get("ratios")
            context["data_sources"].append("ikg_bundle")
            return context

    if ticker:
        try:
            from finagent.ikg.graph_client import get_graph_client
            client = get_graph_client()
            if client:
                fin_data = await client.get_company_financials(ticker)
                if fin_data:
                    context["income_statement"] = fin_data.get("income_statement")
                    context["balance_sheet"] = fin_data.get("balance_sheet")
                    context["cash_flow"] = fin_data.get("cash_flow")
                    context["data_sources"].append("ikg_financials")
        except Exception as exc:
            logger.debug("IKG financials context unavailable for %s: %s", ticker, exc)

    return context


async def load_accounting_context(
    ticker: str | None,
    cin: str | None = None,
    ikg_bundle: IKGCompanyBundle | None = None,
) -> dict[str, Any]:
    """Load accounting context: audit quality signals, related party transactions."""
    context: dict[str, Any] = {
        "ticker": ticker,
        "cin": cin,
        "audit_firm": None,
        "auditor_tenure_years": None,
        "related_party_transactions": [],
        "audit_qualifications": [],
        "data_sources": [],
    }

    if ikg_bundle is not None:
        auditors = ikg_bundle.governance.get("auditors") or []
        context["audit_firm"] = (
            auditors[0].get("auditor_name")
            if auditors
            else ikg_bundle.governance.get("audit_firm")
        )
        context["related_party_transactions"] = ikg_bundle.risk.get("related_party_transactions") or []
        context["data_sources"].append("ikg_bundle")
        return context

    if cin:
        try:
            from finagent.ikg.graph_client import get_graph_client
            client = get_graph_client()
            if client:
                subgraph = await client.get_company_subgraph(cin)
                if subgraph:
                    context["audit_firm"] = subgraph.get("audit_firm")
                    context["related_party_transactions"] = subgraph.get("related_party_transactions", [])
                    context["data_sources"].append("ikg_accounting")
        except Exception as exc:
            logger.debug("IKG accounting context unavailable for CIN %s: %s", cin, exc)

    return context


async def load_technical_context(ticker: str | None) -> dict[str, Any]:
    """Load technical context: price data, moving averages, volume signals."""
    return {
        "ticker": ticker,
        "price_data": None,
        "moving_averages": {},
        "volume_profile": None,
        "support_resistance": [],
        "data_sources": ["bse_eod", "yfinance"],
    }


async def load_competitor_context(ticker: str | None, sector: str | None = None) -> dict[str, Any]:
    """Load competitor context: peer list, comparative multiples."""
    return {
        "ticker": ticker,
        "sector": sector,
        "peer_list": [],
        "peer_multiples": {},
        "market_share_data": None,
        "data_sources": [],
    }


async def load_community_context(ticker: str | None) -> dict[str, Any]:
    """Load community context: social sentiment, retail investor signals."""
    return {
        "ticker": ticker,
        "sentiment_score": None,
        "retail_interest_trend": None,
        "data_sources": [],
    }


async def load_macro_context(sector: str | None = None) -> dict[str, Any]:
    """Load macro context: sector-level and macro-level data."""
    return {
        "sector": sector,
        "rbi_policy_rate": None,
        "inflation_rate": None,
        "gdp_growth_latest": None,
        "sector_pmi": None,
        "data_sources": ["rbi_public", "mospi"],
    }


# ── Master loader: dispatches by agent type ───────────────────────────────────

_LOADER_REGISTRY: dict[str, Any] = {
    "governance": load_governance_context,
    "valuation": load_valuation_context,
    "risk": load_risk_context,
    "news": load_news_context,
    "financials": load_financials_context,
    "accounting": load_accounting_context,
    "technical": load_technical_context,
    "competitor": load_competitor_context,
    "community": load_community_context,
    "macro": load_macro_context,
}


async def load_agent_context(
    agent_type: str,
    *,
    ticker: str | None = None,
    cin: str | None = None,
    sector: str | None = None,
    ikg_bundle: IKGCompanyBundle | None = None,
) -> dict[str, Any]:
    """Dispatch to the appropriate context loader by agent type.

    Args:
        agent_type: One of the 10 specialist agent names.
        ticker: NSE/BSE ticker symbol.
        cin: MCA Corporate Identity Number.
        sector: SEBI sector classification.

    Returns:
        Agent-specific context dict (never raises; returns empty on error).
    """
    loader = _LOADER_REGISTRY.get(agent_type.lower())
    if not loader:
        logger.warning("No context loader registered for agent type '%s'", agent_type)
        return {}

    try:
        import inspect
        sig = inspect.signature(loader)
        params = set(sig.parameters.keys())

        kwargs: dict[str, Any] = {}
        if "ticker" in params:
            kwargs["ticker"] = ticker
        if "cin" in params:
            kwargs["cin"] = cin
        if "sector" in params:
            kwargs["sector"] = sector
        if "ikg_bundle" in params:
            kwargs["ikg_bundle"] = ikg_bundle
        # For loaders with positional-first arg, handle specially
        if "ticker" not in params and "cin" not in params and "sector" not in params:
            return await loader()

        result = await loader(**kwargs)
        if result is None:
            return {}
        return result
    except Exception as exc:
        logger.warning("Context loader for '%s' failed: %s", agent_type, exc)
        return {}

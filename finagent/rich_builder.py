"""
ORACLE FIOS - Rich (structured) response builder
================================================
Takes the JSON tool outputs observed during a LangGraph run, classifies the
user intent, and assembles a typed RichResponse that the React frontend can
render as metric cards, charts, comparison tables, strengths/risks panels,
and other structured visuals.

The response always carries the supervisor's markdown narrative under
`markdown_body`. When the available tool outputs are too thin to build any
visuals, build(...) returns None and the frontend renders the markdown only.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from pydantic import BaseModel, Field

from .intent import (
    RICH_MODE_CHAT,
    RICH_MODE_COMPARISON,
    RICH_MODE_DOC_COMPARE,
    RICH_MODE_FILING,
    RICH_MODE_NEWS,
    RICH_MODE_SNAPSHOT,
    RICH_MODE_VALUATION,
    classify_rich_mode,
    detect_primary_intent,
    PRIMARY_INTENT_EVENT_EXPLAINER,
)

logger = logging.getLogger("oracle.rich_builder")

# ---------------------------------------------------------------------------
# Pydantic schema (mirrored by Frontend/app/_components/lib/types.ts)
# ---------------------------------------------------------------------------


class Entity(BaseModel):
    label: str
    ticker: Optional[str] = None
    exchange: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    currency: Optional[str] = "INR"
    market_cap: Optional[float] = None
    current_price: Optional[float] = None
    change_pct: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None
    roe: Optional[float] = None
    profit_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    revenue_growth: Optional[float] = None
    debt_to_equity: Optional[float] = None
    dividend_yield: Optional[float] = None
    description: Optional[str] = None


class MetricCard(BaseModel):
    label: str
    value: str
    sub_value: Optional[str] = None
    change: Optional[str] = None
    change_type: Optional[str] = None  # "positive" | "negative" | "neutral"
    tooltip: Optional[str] = None
    icon: Optional[str] = None
    entity_ref: Optional[str] = None  # "primary" | "secondary"
    is_partial: bool = False


class ChartSeries(BaseModel):
    name: str
    color: Optional[str] = None
    values: list[Optional[float]]
    unit: Optional[str] = None


class Chart(BaseModel):
    id: str
    kind: str  # "bar" | "line" | "area" | "donut" | "multi_bar" | "multi_line" | "gauge"
    title: str
    subtitle: Optional[str] = None
    x_labels: list[str] = Field(default_factory=list)
    series: list[ChartSeries] = Field(default_factory=list)
    currency: Optional[str] = None
    y_unit: Optional[str] = None  # "%", "x", "Cr", "L", "USD", "INR"
    is_partial: bool = False


class ComparisonRow(BaseModel):
    metric: str
    primary_value: str
    secondary_value: str
    winner: Optional[str] = None  # "primary" | "secondary" | "tie"
    delta: Optional[str] = None


class StrengthsRisksBlock(BaseModel):
    entity_label: str
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class NewsHeadline(BaseModel):
    title: str
    url: Optional[str] = None
    source: Optional[str] = None
    published: Optional[str] = None
    snippet: Optional[str] = None


class DataSource(BaseModel):
    label: str
    url: Optional[str] = None


class RichResponse(BaseModel):
    mode: str  # one of RICH_MODE_* constants
    title: Optional[str] = None
    subtitle: Optional[str] = None
    primary_entity: Optional[Entity] = None
    secondary_entity: Optional[Entity] = None
    extra_entities: list[Entity] = Field(default_factory=list)
    metric_cards: list[MetricCard] = Field(default_factory=list)
    charts: list[Chart] = Field(default_factory=list)
    comparison_rows: list[ComparisonRow] = Field(default_factory=list)
    strengths_risks: list[StrengthsRisksBlock] = Field(default_factory=list)
    headlines: list[NewsHeadline] = Field(default_factory=list)
    valuation_summary: Optional[dict[str, Any]] = None
    filing_sections: list[dict[str, Any]] = Field(default_factory=list)
    data_sources: list[DataSource] = Field(default_factory=list)
    disclaimer: Optional[str] = (
        "Data for illustrative purposes only. Not investment advice."
    )
    markdown_body: Optional[str] = None
    is_partial: bool = False


# ---------------------------------------------------------------------------
# ToolOutput collector (filled by api.py while the LangGraph runs)
# ---------------------------------------------------------------------------


class ToolOutput(BaseModel):
    """One captured tool call from the LangGraph stream."""

    agent: Optional[str] = None
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    content: Any = None  # parsed JSON if possible, else raw string


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_INR_SUFFIXES = (".NS", ".BO", ".NSE", ".BSE")


def _is_inr_symbol(symbol: Optional[str], hint: Optional[str] = None) -> bool:
    if not symbol:
        if hint and ("nse" in hint.lower() or "bse" in hint.lower() or "india" in hint.lower()):
            return True
        return False
    s = symbol.upper()
    return any(s.endswith(suf) for suf in _INR_SUFFIXES)


def _currency_for(symbol: Optional[str], info_currency: Optional[str] = None) -> str:
    if info_currency:
        return info_currency.upper()
    if _is_inr_symbol(symbol):
        return "INR"
    return "USD"


def _money(value: Optional[float], currency: str = "INR") -> str:
    if value is None:
        return "n/a"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "n/a"
    sign = "-" if v < 0 else ""
    a = abs(v)
    cur = (currency or "INR").upper()
    if cur == "INR":
        if a >= 1e7:
            return f"{sign}\u20b9{a / 1e7:,.2f} Cr"
        if a >= 1e5:
            return f"{sign}\u20b9{a / 1e5:,.2f} L"
        return f"{sign}\u20b9{a:,.0f}"
    if cur == "USD":
        if a >= 1e9:
            return f"{sign}${a / 1e9:,.2f}B"
        if a >= 1e6:
            return f"{sign}${a / 1e6:,.2f}M"
        if a >= 1e3:
            return f"{sign}${a / 1e3:,.2f}K"
        return f"{sign}${a:,.0f}"
    if a >= 1e9:
        return f"{sign}{cur} {a / 1e9:,.2f}B"
    if a >= 1e6:
        return f"{sign}{cur} {a / 1e6:,.2f}M"
    return f"{sign}{cur} {a:,.0f}"


def _price(value: Optional[float], currency: str = "INR") -> str:
    if value is None:
        return "n/a"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if (currency or "INR").upper() == "INR":
        return f"\u20b9{v:,.2f}"
    if (currency or "USD").upper() == "USD":
        return f"${v:,.2f}"
    return f"{currency} {v:,.2f}"


def _pct(value: Optional[float], assume_fraction: bool = True) -> str:
    """Format as percentage. yfinance returns most ratios as fractions
    (0.155 = 15.5%) but a few like dividend_yield are already in percent."""
    if value is None:
        return "n/a"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if assume_fraction:
        v = v * 100
    return f"{v:+.2f}%" if v < 0 else f"{v:.2f}%"


def _ratio(value: Optional[float], suffix: str = "x") -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.2f}{suffix}"
    except (TypeError, ValueError):
        return "n/a"


def _change_type(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v > 0:
        return "positive"
    if v < 0:
        return "negative"
    return "neutral"


# ---------------------------------------------------------------------------
# Tool output normalisation
# ---------------------------------------------------------------------------


def _coerce_json(content: Any) -> Any:
    """Tool messages arrive as str (JSON) or already parsed dict/list."""
    if content is None:
        return None
    if isinstance(content, (dict, list)):
        return content
    if isinstance(content, bytes):
        try:
            content = content.decode("utf-8", errors="ignore")
        except Exception:
            return None
    if isinstance(content, str):
        s = content.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            # Try to find an embedded JSON object/array.
            match = re.search(r"(\{[\s\S]+\}|\[[\s\S]+\])", s)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    return s
            return s
    return content


def _is_error_payload(parsed: Any) -> bool:
    return isinstance(parsed, dict) and bool(parsed.get("error"))


def _unwrap(parsed: Any) -> Any:
    """All MCP tools follow `{error: bool, data: ...}` envelope. Unwrap it."""
    if isinstance(parsed, dict) and "data" in parsed and "error" in parsed:
        if not parsed.get("error"):
            return parsed.get("data")
    return parsed


def _find_outputs(outputs: list[ToolOutput], name: str, agent: Optional[str] = None) -> list[Any]:
    """Return all unwrapped data payloads for the given tool name."""
    found: list[Any] = []
    for t in outputs:
        if t.name != name:
            continue
        if agent and t.agent and t.agent != agent:
            continue
        parsed = _coerce_json(t.content)
        if parsed is None or _is_error_payload(parsed):
            continue
        unwrapped = _unwrap(parsed)
        if unwrapped is not None:
            found.append(unwrapped)
    return found


def _first_for_symbol(outputs: list[Any], symbol: Optional[str]) -> Optional[Any]:
    """When multiple outputs of the same tool exist (e.g. two profile calls
    in a comparison), pick the one whose symbol best matches `symbol`."""
    if not outputs:
        return None
    if symbol is None:
        return outputs[0]
    sym_u = symbol.upper()
    for o in outputs:
        if not isinstance(o, dict):
            continue
        ticker = (o.get("symbol") or "").upper()
        if ticker.startswith(sym_u) or ticker.replace(".NS", "").replace(".BO", "") == sym_u:
            return o
    return outputs[0]


# ---------------------------------------------------------------------------
# Symbol extraction (from query text + observed tool args)
# ---------------------------------------------------------------------------

_INLINE_TICKER_RE = re.compile(r"\b([A-Z]{2,10}(?:\.(?:NS|BO|NSE|BSE))?)\b")

_COMPANY_TO_TICKER = {
    "tcs": "TCS",
    "tata consultancy services": "TCS",
    "infosys": "INFY",
    "infy": "INFY",
    "reliance": "RELIANCE",
    "reliance industries": "RELIANCE",
    "hdfc bank": "HDFCBANK",
    "hdfcbank": "HDFCBANK",
    "icici bank": "ICICIBANK",
    "icicibank": "ICICIBANK",
    "sbi": "SBIN",
    "sbin": "SBIN",
    "state bank of india": "SBIN",
    "wipro": "WIPRO",
    "hcl": "HCLTECH",
    "hcl tech": "HCLTECH",
    "hcl technologies": "HCLTECH",
    "ltimindtree": "LTIM",
    "axis bank": "AXISBANK",
    "kotak": "KOTAKBANK",
    "kotak bank": "KOTAKBANK",
    "kotak mahindra bank": "KOTAKBANK",
    "itc": "ITC",
    "bharti airtel": "BHARTIARTL",
    "bharti": "BHARTIARTL",
    "airtel": "BHARTIARTL",
    "hindustan unilever": "HINDUNILVR",
    "hul": "HINDUNILVR",
    "asian paints": "ASIANPAINT",
    "maruti": "MARUTI",
    "maruti suzuki": "MARUTI",
    "tata motors": "TATAMOTORS",
    "tata steel": "TATASTEEL",
    "adani": "ADANIENT",
    "adani enterprises": "ADANIENT",
    "zomato": "ZOMATO",
    "paytm": "PAYTM",
    "zodiac": "ZODIAC",
    "zodiac energy": "ZODIAC",
}

_BLACKLIST_TOKENS = {
    "NSE", "BSE", "SEBI", "RBI", "DCF", "WACC", "CAGR", "PE", "PB", "ROE", "ROA",
    "GDP", "FII", "DII", "EBITDA", "EPS", "TTM", "YOY", "QOQ", "FY", "USD", "INR",
    "GST", "IPO", "DRHP", "RHP", "AND", "OR", "VS", "THE", "WITH", "FROM",
}


def extract_symbols(message: str, outputs: list[ToolOutput]) -> list[str]:
    """Best-effort: prefer symbols actually passed to MCP tools; fall back to
    keyword extraction from the user query."""
    seen: list[str] = []

    # 1. From observed tool args
    for t in outputs:
        for key in ("symbol", "symbols", "companies"):
            v = t.args.get(key)
            if isinstance(v, str):
                u = v.strip().upper()
                if u and u not in seen and u not in _BLACKLIST_TOKENS:
                    seen.append(u)
            elif isinstance(v, list):
                for item in v:
                    if isinstance(item, str):
                        u = item.strip().upper()
                        if u and u not in seen and u not in _BLACKLIST_TOKENS:
                            seen.append(u)

    # 2. From observed tool outputs (handles "compare_stocks" returning multiple)
    for t in outputs:
        parsed = _coerce_json(t.content)
        unwrapped = _unwrap(parsed) if parsed else None
        if isinstance(unwrapped, dict):
            sym = unwrapped.get("symbol")
            if isinstance(sym, str):
                cleaned = sym.split(".")[0].upper()
                if cleaned and cleaned not in seen and cleaned not in _BLACKLIST_TOKENS:
                    seen.append(cleaned)
            comp = unwrapped.get("comparison")
            if isinstance(comp, list):
                for row in comp:
                    if isinstance(row, dict):
                        rsym = row.get("requested_symbol") or row.get("symbol")
                        if isinstance(rsym, str):
                            u = rsym.split(".")[0].upper()
                            if u and u not in seen and u not in _BLACKLIST_TOKENS:
                                seen.append(u)

    # 3. Fall back to text extraction — also run when a comparison query has
    #    fewer than 2 symbols, since the secondary entity may only appear in text.
    _is_comp = bool(re.search(
        r"\b(?:compare|comparison|compares|comparing|vs\.?|versus|against|head[\s-]to[\s-]head)\b",
        (message or ""), re.IGNORECASE,
    ))
    if not seen or (_is_comp and len(seen) < 2):
        lower = (message or "").lower()
        for name, tick in _COMPANY_TO_TICKER.items():
            pat = r"\b" + re.escape(name) + r"\b"
            if re.search(pat, lower):
                if tick not in seen:
                    seen.append(tick)
        for match in _INLINE_TICKER_RE.findall(message or ""):
            token = match.split(".")[0]
            if token in _BLACKLIST_TOKENS:
                continue
            if token not in seen:
                seen.append(token)

    return seen


# ---------------------------------------------------------------------------
# Entity assembly
# ---------------------------------------------------------------------------


def _build_entity_from_profile(profile: dict[str, Any], fallback_label: str) -> Entity:
    sym = profile.get("symbol") or fallback_label
    cur = profile.get("currency") or _currency_for(sym)
    prev_close = profile.get("previous_close")
    current = profile.get("current_price")
    change_pct: Optional[float] = None
    if prev_close and current:
        try:
            change_pct = ((float(current) - float(prev_close)) / float(prev_close)) * 100
        except (TypeError, ValueError, ZeroDivisionError):
            change_pct = None
    label = profile.get("long_name") or profile.get("short_name") or fallback_label
    return Entity(
        label=label,
        ticker=sym,
        exchange=profile.get("exchange"),
        sector=profile.get("sector"),
        industry=profile.get("industry"),
        currency=cur,
        market_cap=_to_float(profile.get("market_cap")),
        current_price=_to_float(profile.get("current_price")),
        change_pct=change_pct,
        fifty_two_week_high=_to_float(profile.get("52_week_high")),
        fifty_two_week_low=_to_float(profile.get("52_week_low")),
        pe=_to_float(profile.get("trailing_pe")),
        pb=_to_float(profile.get("price_to_book")),
        roe=_to_float(profile.get("return_on_equity")),
        profit_margin=_to_float(profile.get("profit_margins")),
        operating_margin=_to_float(profile.get("operating_margins")),
        revenue_growth=None,
        debt_to_equity=_to_float(profile.get("debt_to_equity")),
        dividend_yield=_to_float(profile.get("dividend_yield")),
        description=profile.get("description"),
    )


def _build_entity_from_nse_quote(quote: dict[str, Any], fallback_label: str) -> Entity:
    sym = quote.get("symbol") or fallback_label
    label = quote.get("company_name") or fallback_label
    return Entity(
        label=label,
        ticker=sym,
        exchange="NSE",
        sector=quote.get("sector") or quote.get("basic_industry"),
        industry=quote.get("industry"),
        currency="INR",
        current_price=_to_float(quote.get("last_price")),
        change_pct=_to_float(quote.get("pct_change")),
        fifty_two_week_high=_to_float(quote.get("week_high_52")),
        fifty_two_week_low=_to_float(quote.get("week_low_52")),
        pe=_to_float(quote.get("symbol_pe")),
    )


def _merge_entity_with_metrics(entity: Entity, metrics: Optional[dict[str, Any]]) -> Entity:
    if not metrics:
        return entity
    patch: dict[str, Any] = {}
    if entity.market_cap is None and metrics.get("market_cap") is not None:
        patch["market_cap"] = _to_float(metrics.get("market_cap"))
    if entity.pe is None and metrics.get("trailing_pe") is not None:
        patch["pe"] = _to_float(metrics.get("trailing_pe"))
    if entity.pb is None and metrics.get("price_to_book") is not None:
        patch["pb"] = _to_float(metrics.get("price_to_book"))
    if entity.roe is None and metrics.get("roe") is not None:
        patch["roe"] = _to_float(metrics.get("roe"))
    if entity.profit_margin is None and metrics.get("profit_margin") is not None:
        patch["profit_margin"] = _to_float(metrics.get("profit_margin"))
    if entity.operating_margin is None and metrics.get("operating_margin") is not None:
        patch["operating_margin"] = _to_float(metrics.get("operating_margin"))
    if entity.debt_to_equity is None and metrics.get("debt_to_equity") is not None:
        patch["debt_to_equity"] = _to_float(metrics.get("debt_to_equity"))
    if entity.dividend_yield is None and metrics.get("dividend_yield") is not None:
        patch["dividend_yield"] = _to_float(metrics.get("dividend_yield"))
    if entity.revenue_growth is None and metrics.get("revenue_growth") is not None:
        patch["revenue_growth"] = _to_float(metrics.get("revenue_growth"))
    if not patch:
        return entity
    data = entity.model_dump()
    data.update(patch)
    return Entity(**data)


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Statement helpers ΓÇö extract historical revenue / net income / margin
# ---------------------------------------------------------------------------


def _extract_annual_history(statements: Optional[list[dict[str, Any]]]) -> dict[str, list[Any]]:
    """Given the income_statement `statements` list, return a dict of
    {labels[], revenue[], net_income[], operating_income[], gross_profit[]}
    in chronological (oldest-first) order with up to 4 most recent annual entries."""
    if not isinstance(statements, list) or not statements:
        return {"labels": [], "revenue": [], "net_income": [], "operating_income": [], "gross_profit": []}
    # statements are typically newest-first from yfinance
    rows: list[dict[str, Any]] = []
    for s in statements[:4]:
        if not isinstance(s, dict):
            continue
        date = s.get("date") or s.get("Date") or s.get("period") or ""
        rows.append(
            {
                "label": _format_fy(date),
                "revenue": _to_float(s.get("Total Revenue") or s.get("Operating Revenue")),
                "net_income": _to_float(s.get("Net Income")),
                "operating_income": _to_float(s.get("Operating Income")),
                "gross_profit": _to_float(s.get("Gross Profit")),
            }
        )
    rows.reverse()  # oldest first
    return {
        "labels": [r["label"] for r in rows],
        "revenue": [r["revenue"] for r in rows],
        "net_income": [r["net_income"] for r in rows],
        "operating_income": [r["operating_income"] for r in rows],
        "gross_profit": [r["gross_profit"] for r in rows],
    }


def _format_fy(date_str: str) -> str:
    if not date_str:
        return ""
    # YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS
    m = re.match(r"(\d{4})", date_str)
    if not m:
        return date_str
    year = int(m.group(1))
    # Indian FY: 2024-03-31 -> FY24
    return f"FY{str(year)[-2:]}"


def _quarterly_history(quarterly: Optional[dict[str, Any]]) -> dict[str, list[Any]]:
    if not isinstance(quarterly, dict):
        return {"labels": [], "revenue": [], "net_income": []}
    rows = quarterly.get("quarters") or []
    if not isinstance(rows, list):
        return {"labels": [], "revenue": [], "net_income": []}
    out_labels: list[str] = []
    out_rev: list[Optional[float]] = []
    out_ni: list[Optional[float]] = []
    for q in rows[:4]:
        if not isinstance(q, dict):
            continue
        date = q.get("date") or ""
        out_labels.append(_format_quarter(date))
        out_rev.append(_to_float(q.get("Total Revenue")))
        out_ni.append(_to_float(q.get("Net Income")))
    return {
        "labels": list(reversed(out_labels)),
        "revenue": list(reversed(out_rev)),
        "net_income": list(reversed(out_ni)),
    }


def _format_quarter(date_str: str) -> str:
    if not date_str:
        return ""
    m = re.match(r"(\d{4})-(\d{2})", date_str)
    if not m:
        return date_str
    year, month = m.group(1), int(m.group(2))
    q_map = {3: "Q4", 6: "Q1", 9: "Q2", 12: "Q3"}
    q = q_map.get(month, f"M{month:02d}")
    return f"{q}{str(year)[-2:]}"


# ---------------------------------------------------------------------------
# Assemblers
# ---------------------------------------------------------------------------


def _wants_charts(message: str) -> bool:
    msg = (message or "").lower()
    
    # 1. Check if it is a regulatory, filing, or informational lookup.
    # If the user is looking up specific documents, filings, circulars, or regulatory details,
    # they don't want charts unless they explicitly ask for a visual/trend.
    regulatory_keywords = [
        "sebi", "lodr", "regulation", "announcement", "circular", "disclosure", 
        "board meeting", "filing", "promoter pledge", "pledged shares", 
        "insider trading", "document", "pdf", "prospectus", "drhp", "rhp", 
        "director", "governance", "committee", "audit", "compliance", "notice"
    ]
    is_regulatory = any(kw in msg for kw in regulatory_keywords)
    
    # Check if there is an explicit request for visuals/charts/historical trends/comparison
    explicit_visuals = [
        "chart", "graph", "plot", "visual", "trend", "historical", "history", "pattern",
        "compare", "comparison", "vs", "versus", "forecast", "predict", "projection",
        "growth", "analysis", "analyze", "valuation"
    ]
    has_explicit_visual = any(kw in msg for kw in explicit_visuals)
    
    if is_regulatory and not has_explicit_visual:
        logger.info("Query '%s' is regulatory/informational without explicit visual request. Omitting charts.", message)
        return False

    # 2. General logic for other queries
    keywords = [
        "chart", "graph", "plot", "visual", "trend", "historical", "history", "pattern",
        "compare", "comparison", "vs", "versus", "forecast", "predict", "projection",
        "analysis", "analyze", "overview", "snapshot", "growth", "revenue", "profit",
        "net income", "margin", "metrics", "financials", "performance", "valuation",
        "shareholding", "holdings", "annual", "quarterly"
    ]
    # Simple symbol or company name lookup should have charts (e.g. "TCS")
    words = msg.split()
    if len(words) <= 2 and not any(w in msg for w in ["what", "how", "why", "who", "where", "when"]):
        wants = True
    else:
        wants = any(kw in msg for kw in keywords)
    
    logger.info("Query '%s' wants charts? %s", message, wants)
    return wants


def _assemble_snapshot(message: str, outputs: list[ToolOutput], markdown_body: str) -> Optional[RichResponse]:
    symbols = extract_symbols(message, outputs)
    symbol = symbols[0] if symbols else None

    profiles = _find_outputs(outputs, "profile")
    key_metrics = _find_outputs(outputs, "key_metrics")
    nse_quotes = _find_outputs(outputs, "nse_get_quote")
    incomes = _find_outputs(outputs, "income_statement")
    quarterly = _find_outputs(outputs, "get_quarterly_results")
    shareholdings = _find_outputs(outputs, "get_shareholding") + _find_outputs(outputs, "nse_get_shareholding")
    news = _find_outputs(outputs, "get_latest_company_news") + _find_outputs(outputs, "search_news")

    profile = _first_for_symbol(profiles, symbol)
    nse_quote = _first_for_symbol(nse_quotes, symbol)
    metrics = _first_for_symbol(key_metrics, symbol)
    income = _first_for_symbol(incomes, symbol)
    qres = _first_for_symbol(quarterly, symbol)
    shares = _first_for_symbol(shareholdings, symbol)

    if not (profile or nse_quote or metrics or income or qres):
        return None

    if isinstance(profile, dict):
        entity = _build_entity_from_profile(profile, symbol or "")
    elif isinstance(nse_quote, dict):
        entity = _build_entity_from_nse_quote(nse_quote, symbol or "")
    else:
        # Build a thin entity from key_metrics alone
        m = metrics if isinstance(metrics, dict) else {}
        entity = Entity(
            label=symbol or "Company",
            ticker=m.get("symbol") or symbol,
            currency=m.get("currency") or _currency_for(symbol),
            market_cap=_to_float(m.get("market_cap")),
            pe=_to_float(m.get("trailing_pe")),
            pb=_to_float(m.get("price_to_book")),
            roe=_to_float(m.get("roe")),
            profit_margin=_to_float(m.get("profit_margin")),
            operating_margin=_to_float(m.get("operating_margin")),
            debt_to_equity=_to_float(m.get("debt_to_equity")),
            dividend_yield=_to_float(m.get("dividend_yield")),
        )

    entity = _merge_entity_with_metrics(entity, metrics if isinstance(metrics, dict) else None)
    if isinstance(nse_quote, dict) and entity.exchange is None:
        entity.exchange = "NSE"

    currency = entity.currency or "INR"

    # ----- Metric cards -----
    cards: list[MetricCard] = []
    cards.append(MetricCard(
        label="Market cap",
        value=_money(entity.market_cap, currency),
        tooltip="Total market value of outstanding shares",
        icon="briefcase",
        is_partial=entity.market_cap is None,
    ))
    cards.append(MetricCard(
        label="52-wk high",
        value=_price(entity.fifty_two_week_high, currency),
        tooltip="Highest traded price in the past 52 weeks",
        icon="trending-up",
        is_partial=entity.fifty_two_week_high is None,
    ))
    cards.append(MetricCard(
        label="52-wk low",
        value=_price(entity.fifty_two_week_low, currency),
        tooltip="Lowest traded price in the past 52 weeks",
        icon="trending-down",
        is_partial=entity.fifty_two_week_low is None,
    ))
    cards.append(MetricCard(
        label="Div. yield",
        value=_pct(entity.dividend_yield, assume_fraction=False) if (
            entity.dividend_yield is not None and entity.dividend_yield > 1
        ) else _pct(entity.dividend_yield),
        tooltip="Annual dividend per share / current price",
        icon="percent",
        is_partial=entity.dividend_yield is None,
    ))
    # yfinance returns debt_to_equity as percent for Indian tickers (e.g. 70 = 0.70x)
    de_val = entity.debt_to_equity
    de_str = "n/a"
    if de_val is not None:
        de_str = f"{de_val / 100:.2f}x" if de_val > 5 else f"{de_val:.2f}x"
    cards.append(MetricCard(
        label="Debt/Equity",
        value=de_str,
        tooltip="Total debt divided by shareholders' equity",
        icon="scale",
        change_type="negative" if de_val and de_val > 1.5 * 100 else "neutral",
        is_partial=de_val is None,
    ))
    cards.append(MetricCard(
        label="ROE",
        value=_pct(entity.roe),
        tooltip="Net income / shareholders' equity",
        icon="trending-up",
        change_type=_change_type(entity.roe),
        is_partial=entity.roe is None,
    ))

    # ----- Charts -----
    charts: list[Chart] = []
    if _wants_charts(message):
        history = _extract_annual_history(income.get("statements") if isinstance(income, dict) else None)

        if history["labels"] and any(v is not None for v in history["revenue"]):
            charts.append(Chart(
                id="annual-revenue",
                kind="bar",
                title="Annual revenue",
                subtitle=f"{currency} (Crore)" if currency == "INR" else f"({currency})",
                x_labels=history["labels"],
                series=[ChartSeries(
                    name="Revenue",
                    color="#10b981",
                    values=[_scale_for_chart(v, currency) for v in history["revenue"]],
                    unit="Cr" if currency == "INR" else currency,
                )],
                currency=currency,
                y_unit="Cr" if currency == "INR" else currency,
                is_partial=any(v is None for v in history["revenue"]),
            ))

        if history["labels"] and any(v is not None for v in history["net_income"]):
            charts.append(Chart(
                id="annual-net-profit",
                kind="bar",
                title="Net profit",
                subtitle=f"{currency} (Crore)" if currency == "INR" else f"({currency})",
                x_labels=history["labels"],
                series=[ChartSeries(
                    name="Net income",
                    color="#3b82f6",
                    values=[_scale_for_chart(v, currency) for v in history["net_income"]],
                    unit="Cr" if currency == "INR" else currency,
                )],
                currency=currency,
                y_unit="Cr" if currency == "INR" else currency,
                is_partial=any(v is None for v in history["net_income"]),
            ))

        # Quarterly trend (area)
        q_hist = _quarterly_history(qres if isinstance(qres, dict) else None)
        if q_hist["labels"] and any(v is not None for v in q_hist["revenue"]):
            charts.append(Chart(
                id="quarterly-revenue",
                kind="area",
                title="Quarterly revenue trend",
                x_labels=q_hist["labels"],
                series=[ChartSeries(
                    name="Revenue",
                    color="#8b5cf6",
                    values=[_scale_for_chart(v, currency) for v in q_hist["revenue"]],
                    unit="Cr" if currency == "INR" else currency,
                )],
                currency=currency,
                y_unit="Cr" if currency == "INR" else currency,
            ))

        # Shareholding donut (from yfinance major holders or NSE)
        donut = _build_shareholding_donut(shares)
        if donut:
            charts.append(donut)

    # ----- Strengths / risks (derive heuristically) -----
    sr = _derive_strengths_risks(entity)
    if sr:
        sr_block = StrengthsRisksBlock(entity_label=entity.label, **sr)
    else:
        sr_block = StrengthsRisksBlock(entity_label=entity.label)

    # ----- News headlines -----
    headlines = _news_to_headlines(news, primary=entity.label, secondary=None)[:6]

    title = entity.label
    subtitle_bits: list[str] = []
    if entity.exchange:
        subtitle_bits.append(entity.exchange)
    if entity.ticker:
        subtitle_bits.append(entity.ticker)
    if entity.sector:
        subtitle_bits.append(entity.sector)
    subtitle = " | ".join(subtitle_bits) if subtitle_bits else None

    is_partial = any(c.is_partial for c in cards) or any(c.is_partial for c in charts)

    return RichResponse(
        mode=RICH_MODE_SNAPSHOT,
        title=title,
        subtitle=subtitle,
        primary_entity=entity,
        metric_cards=cards,
        charts=charts,
        strengths_risks=[sr_block] if sr_block.strengths or sr_block.risks else [],
        headlines=headlines,
        markdown_body=markdown_body,
        data_sources=_default_sources(currency == "INR"),
        is_partial=is_partial,
    )


def _scale_for_chart(value: Optional[float], currency: str) -> Optional[float]:
    """Convert raw rupee/dollar value to chart-friendly Cr / B units."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if (currency or "INR").upper() == "INR":
        return round(v / 1e7, 2)  # to Crores
    return round(v / 1e9, 2)  # to Billions for USD/other


def _build_shareholding_donut(shares: Any) -> Optional[Chart]:
    if not isinstance(shares, dict):
        return None
    labels: list[str] = []
    values: list[float] = []
    # yfinance major_holders is [["xx%", "% of Shares Held by All Insider"], ...]
    for h in shares.get("major_holders") or []:
        try:
            val_str = (h.get("value") or "").strip()
            desc = (h.get("description") or "").strip()
            if not val_str or not desc:
                continue
            num_match = re.match(r"([0-9.]+)%?", val_str)
            if not num_match:
                continue
            num = float(num_match.group(1))
            short_desc = desc.replace("% of Shares Held by", "").strip() or desc
            short_desc = re.sub(r"^All ", "", short_desc, flags=re.IGNORECASE).strip()
            labels.append(short_desc.title())
            values.append(num)
        except Exception:
            continue
    if not labels:
        return None
    return Chart(
        id="shareholding",
        kind="donut",
        title="Shareholding pattern",
        x_labels=labels,
        series=[ChartSeries(name="Holders", values=values, unit="%")],
        y_unit="%",
    )


def _derive_strengths_risks(entity: Entity) -> dict[str, list[str]]:
    strengths: list[str] = []
    risks: list[str] = []
    if entity.roe is not None:
        roe_pct = entity.roe * 100 if entity.roe < 5 else entity.roe
        if roe_pct >= 18:
            strengths.append(f"High ROE of {roe_pct:.1f}% signals efficient capital deployment.")
        elif roe_pct < 8:
            risks.append(f"ROE of {roe_pct:.1f}% below 8% threshold.")
    if entity.profit_margin is not None:
        pm = entity.profit_margin * 100 if entity.profit_margin < 5 else entity.profit_margin
        if pm >= 15:
            strengths.append(f"Net margin of {pm:.1f}% indicates strong pricing power.")
        elif pm < 5:
            risks.append(f"Thin net margin of {pm:.1f}%.")
    if entity.operating_margin is not None:
        om = entity.operating_margin * 100 if entity.operating_margin < 5 else entity.operating_margin
        if om >= 20:
            strengths.append(f"Operating margin of {om:.1f}% is industry-leading.")
    if entity.debt_to_equity is not None:
        de = entity.debt_to_equity / 100 if entity.debt_to_equity > 5 else entity.debt_to_equity
        if de < 0.3:
            strengths.append(f"Lean balance sheet (D/E {de:.2f}x).")
        elif de > 1.5:
            risks.append(f"Elevated leverage (D/E {de:.2f}x) limits flexibility.")
    if entity.revenue_growth is not None:
        rg = entity.revenue_growth * 100 if entity.revenue_growth < 5 else entity.revenue_growth
        if rg >= 12:
            strengths.append(f"Revenue growth of {rg:.1f}% ahead of broader market.")
        elif rg < 0:
            risks.append(f"Revenue contracting at {rg:.1f}% YoY.")
    if entity.dividend_yield is not None:
        dy = entity.dividend_yield * 100 if entity.dividend_yield < 1 else entity.dividend_yield
        if dy >= 3:
            strengths.append(f"Dividend yield of {dy:.2f}% rewards income investors.")
    if entity.pe is not None and entity.pe > 50:
        risks.append(f"Premium valuation (P/E {entity.pe:.1f}x) leaves little room for error.")
    return {"strengths": strengths, "risks": risks}


def _news_to_headlines(news_outputs: list[Any], primary: Optional[str], secondary: Optional[str]) -> list[NewsHeadline]:
    out: list[NewsHeadline] = []
    seen_urls: set[str] = set()

    def _push(item: dict[str, Any]):
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        if not title:
            return
        if url and url in seen_urls:
            return
        if url:
            seen_urls.add(url)
        out.append(NewsHeadline(
            title=title,
            url=url or None,
            source=item.get("source") or (_domain_of(url) if url else None),
            published=item.get("published") or item.get("published_date"),
            snippet=((item.get("snippet") or item.get("content") or "")[:240]) or None,
        ))

    for payload in news_outputs:
        if isinstance(payload, dict):
            # get_latest_company_news: data.companies = {name: {results: [...]}}
            companies = payload.get("companies")
            if isinstance(companies, dict):
                for _, block in companies.items():
                    for r in block.get("results", []) or []:
                        if isinstance(r, dict):
                            _push(r)
            # search_news / search_web: data.results
            for key in ("results", "articles", "headlines"):
                arr = payload.get(key)
                if isinstance(arr, list):
                    for r in arr:
                        if isinstance(r, dict):
                            _push(r)
    return out[:8]


def _domain_of(url: str) -> Optional[str]:
    if not url:
        return None
    m = re.match(r"https?://([^/]+)/?", url)
    if not m:
        return None
    host = m.group(1).lower().removeprefix("www.")
    return host


def _default_sources(is_india: bool) -> list[DataSource]:
    return [
        DataSource(label="NSE India", url="https://www.nseindia.com"),
        DataSource(label="Yahoo Finance"),
        DataSource(label="Screener.in"),
    ]


# ---------------------------------------------------------------------------
# Comparison assembler
# ---------------------------------------------------------------------------


def _assemble_comparison(message: str, outputs: list[ToolOutput], markdown_body: str) -> Optional[RichResponse]:
    symbols = extract_symbols(message, outputs)
    if len(symbols) < 2:
        return None
    primary_sym, secondary_sym = symbols[0], symbols[1]

    profiles = _find_outputs(outputs, "profile")
    key_metrics_all = _find_outputs(outputs, "key_metrics")
    incomes = _find_outputs(outputs, "income_statement")
    compare = _find_outputs(outputs, "compare_stocks")
    news = _find_outputs(outputs, "get_latest_company_news") + _find_outputs(outputs, "search_news")

    primary_profile = _first_for_symbol(profiles, primary_sym)
    secondary_profile = _first_for_symbol(
        [p for p in profiles if isinstance(p, dict) and not _matches_symbol(p.get("symbol"), primary_sym)],
        secondary_sym,
    )
    primary_metrics = _first_for_symbol(key_metrics_all, primary_sym)
    secondary_metrics = _first_for_symbol(
        [m for m in key_metrics_all if isinstance(m, dict) and not _matches_symbol(m.get("symbol"), primary_sym)],
        secondary_sym,
    )
    primary_income = _first_for_symbol(incomes, primary_sym)
    secondary_income = _first_for_symbol(
        [i for i in incomes if isinstance(i, dict) and not _matches_symbol(i.get("symbol"), primary_sym)],
        secondary_sym,
    )

    # Fall back to compare_stocks payload for missing rows
    cmp_rows: dict[str, dict[str, Any]] = {}
    for c in compare:
        if isinstance(c, dict):
            for row in c.get("comparison") or []:
                if isinstance(row, dict):
                    req = (row.get("requested_symbol") or row.get("symbol") or "").upper().split(".")[0]
                    if req:
                        cmp_rows[req] = row

    def _entity_for(sym: str, profile: Any, metrics: Any) -> Optional[Entity]:
        if isinstance(profile, dict):
            ent = _build_entity_from_profile(profile, sym)
        else:
            row = cmp_rows.get(sym.upper())
            if isinstance(row, dict):
                ent = Entity(
                    label=row.get("name") or sym,
                    ticker=row.get("symbol") or sym,
                    currency=_currency_for(row.get("symbol")),
                    market_cap=_to_float(row.get("market_cap")),
                    current_price=_to_float(row.get("current_price")),
                    pe=_to_float(row.get("trailing_pe")),
                    pb=_to_float(row.get("price_to_book")),
                    roe=_to_float(row.get("roe")),
                    profit_margin=_to_float(row.get("profit_margin")),
                    revenue_growth=_to_float(row.get("revenue_growth")),
                    debt_to_equity=_to_float(row.get("debt_to_equity")),
                    dividend_yield=_to_float(row.get("dividend_yield")),
                )
            else:
                return None
        return _merge_entity_with_metrics(ent, metrics if isinstance(metrics, dict) else None)

    primary = _entity_for(primary_sym, primary_profile, primary_metrics)
    secondary = _entity_for(secondary_sym, secondary_profile, secondary_metrics)

    if not primary or not secondary:
        return None

    currency = primary.currency or "INR"

    # ----- Hero metric cards (4 per entity) -----
    cards: list[MetricCard] = []
    for ent_ref, ent in (("primary", primary), ("secondary", secondary)):
        cards.append(MetricCard(
            label="Market cap",
            value=_money(ent.market_cap, ent.currency or currency),
            entity_ref=ent_ref,
            tooltip="Total market value of outstanding shares",
            icon="briefcase",
            is_partial=ent.market_cap is None,
        ))
        cards.append(MetricCard(
            label="P/E",
            value=_ratio(ent.pe),
            entity_ref=ent_ref,
            tooltip="Price / TTM EPS",
            icon="scale",
            is_partial=ent.pe is None,
        ))
        cards.append(MetricCard(
            label="ROE",
            value=_pct(ent.roe),
            entity_ref=ent_ref,
            tooltip="Net income / shareholders' equity",
            icon="trending-up",
            change_type=_change_type(ent.roe),
            is_partial=ent.roe is None,
        ))
        cards.append(MetricCard(
            label="Op. margin",
            value=_pct(ent.operating_margin),
            entity_ref=ent_ref,
            tooltip="Operating income / revenue",
            icon="percent",
            change_type=_change_type(ent.operating_margin),
            is_partial=ent.operating_margin is None,
        ))

    # ----- Multi-series revenue chart (FYxx grouped bars) -----
    p_hist = _extract_annual_history(primary_income.get("statements") if isinstance(primary_income, dict) else None)
    s_hist = _extract_annual_history(secondary_income.get("statements") if isinstance(secondary_income, dict) else None)
    charts: list[Chart] = []
    labels = _align_labels(p_hist["labels"], s_hist["labels"])
    if labels:
        p_rev = _align_values(p_hist["labels"], p_hist["revenue"], labels, currency)
        s_rev = _align_values(s_hist["labels"], s_hist["revenue"], labels, currency)
        if any(v is not None for v in p_rev) or any(v is not None for v in s_rev):
            charts.append(Chart(
                id="revenue-comparison",
                kind="multi_bar",
                title="Revenue comparison",
                subtitle="\u20b9 Crore" if currency == "INR" else f"({currency} B)",
                x_labels=labels,
                series=[
                    ChartSeries(name=primary.label, color="#3b82f6", values=p_rev, unit="Cr" if currency == "INR" else "B"),
                    ChartSeries(name=secondary.label, color="#10b981", values=s_rev, unit="Cr" if currency == "INR" else "B"),
                ],
                currency=currency,
                y_unit="Cr" if currency == "INR" else "B",
                is_partial=any(v is None for v in p_rev) or any(v is None for v in s_rev),
            ))

        # Operating margin line chart (derive each year)
        def _margin_series(hist: dict[str, list[Any]]) -> list[Optional[float]]:
            out: list[Optional[float]] = []
            for rev, op in zip(hist["revenue"], hist["operating_income"]):
                if rev and op and rev > 0:
                    out.append(round((op / rev) * 100, 2))
                else:
                    out.append(None)
            return out

        p_margin_raw = _margin_series(p_hist)
        s_margin_raw = _margin_series(s_hist)
        p_margin = _align_pct(p_hist["labels"], p_margin_raw, labels)
        s_margin = _align_pct(s_hist["labels"], s_margin_raw, labels)
        if any(v is not None for v in p_margin) or any(v is not None for v in s_margin):
            charts.append(Chart(
                id="op-margin-comparison",
                kind="multi_line",
                title="Operating margin comparison",
                subtitle="%",
                x_labels=labels,
                series=[
                    ChartSeries(name=primary.label, color="#3b82f6", values=p_margin, unit="%"),
                    ChartSeries(name=secondary.label, color="#10b981", values=s_margin, unit="%"),
                ],
                y_unit="%",
                is_partial=any(v is None for v in p_margin) or any(v is None for v in s_margin),
            ))

    # ----- Head-to-head ratio table -----
    rows = _comparison_rows(primary, secondary, currency)

    # ----- Strengths / risks per entity -----
    sr_p_dict = _derive_strengths_risks(primary)
    sr_s_dict = _derive_strengths_risks(secondary)
    sr_blocks: list[StrengthsRisksBlock] = []
    sr_blocks.append(StrengthsRisksBlock(entity_label=primary.label, **sr_p_dict))
    sr_blocks.append(StrengthsRisksBlock(entity_label=secondary.label, **sr_s_dict))

    # ----- News -----
    headlines = _news_to_headlines(news, primary=primary.label, secondary=secondary.label)[:8]

    title = f"{primary.label} vs {secondary.label}"
    subtitle = "Head-to-head comparison"
    is_partial = any(c.is_partial for c in cards) or any(c.is_partial for c in charts)

    return RichResponse(
        mode=RICH_MODE_COMPARISON,
        title=title,
        subtitle=subtitle,
        primary_entity=primary,
        secondary_entity=secondary,
        metric_cards=cards,
        charts=charts,
        comparison_rows=rows,
        strengths_risks=sr_blocks,
        headlines=headlines,
        markdown_body=markdown_body,
        data_sources=_default_sources(currency == "INR"),
        is_partial=is_partial,
    )


def _matches_symbol(maybe: Optional[str], target: str) -> bool:
    if not maybe or not target:
        return False
    return maybe.upper().split(".")[0] == target.upper().split(".")[0]


def _align_labels(a: list[str], b: list[str]) -> list[str]:
    """Take the longer label set as canonical."""
    if len(a) >= len(b):
        return list(a)
    return list(b)


def _align_values(source_labels: list[str], values: list[Any], target_labels: list[str], currency: str) -> list[Optional[float]]:
    by_label = {lbl: val for lbl, val in zip(source_labels, values)}
    return [_scale_for_chart(by_label.get(lbl), currency) for lbl in target_labels]


def _align_pct(source_labels: list[str], values: list[Any], target_labels: list[str]) -> list[Optional[float]]:
    by_label = {lbl: val for lbl, val in zip(source_labels, values)}
    return [by_label.get(lbl) for lbl in target_labels]


def _comparison_rows(primary: Entity, secondary: Entity, currency: str) -> list[ComparisonRow]:
    rows: list[ComparisonRow] = []

    def _add(metric: str, p_val: Optional[float], s_val: Optional[float], formatter, lower_is_better: bool = False):
        p_str = formatter(p_val) if p_val is not None else "n/a"
        s_str = formatter(s_val) if s_val is not None else "n/a"
        winner: Optional[str] = None
        delta: Optional[str] = None
        if p_val is not None and s_val is not None:
            if abs(p_val - s_val) / max(abs(p_val), abs(s_val), 1e-9) < 0.001:
                winner = "tie"
            elif lower_is_better:
                winner = "primary" if p_val < s_val else "secondary"
            else:
                winner = "primary" if p_val > s_val else "secondary"
            try:
                pct = ((p_val - s_val) / s_val) * 100 if s_val else 0
                delta = f"{pct:+.1f}%"
            except (ZeroDivisionError, TypeError):
                delta = None
        rows.append(ComparisonRow(
            metric=metric,
            primary_value=p_str,
            secondary_value=s_str,
            winner=winner,
            delta=delta,
        ))

    _add("Market cap", primary.market_cap, secondary.market_cap, lambda v: _money(v, currency))
    _add("Current price", primary.current_price, secondary.current_price, lambda v: _price(v, currency))
    _add("P/E", primary.pe, secondary.pe, _ratio, lower_is_better=True)
    _add("P/B", primary.pb, secondary.pb, _ratio, lower_is_better=True)
    _add("ROE", primary.roe, secondary.roe, _pct)
    _add("Net margin", primary.profit_margin, secondary.profit_margin, _pct)
    _add("Op. margin", primary.operating_margin, secondary.operating_margin, _pct)
    _add("Revenue growth", primary.revenue_growth, secondary.revenue_growth, _pct)
    _add("Debt/Equity", primary.debt_to_equity, secondary.debt_to_equity, lambda v: f"{v / 100:.2f}x" if v and v > 5 else f"{v:.2f}x", lower_is_better=True)
    _add("Dividend yield", primary.dividend_yield, secondary.dividend_yield, _pct)
    return rows


# ---------------------------------------------------------------------------
# Valuation assembler
# ---------------------------------------------------------------------------


def _assemble_valuation(message: str, outputs: list[ToolOutput], markdown_body: str) -> Optional[RichResponse]:
    full = _find_outputs(outputs, "run_full_valuation")
    dcf = _find_outputs(outputs, "run_dcf_valuation")
    graham = _find_outputs(outputs, "run_graham_valuation")
    pe = _find_outputs(outputs, "run_pe_valuation")
    ev = _find_outputs(outputs, "run_ev_ebitda_valuation")
    ddm = _find_outputs(outputs, "run_ddm_valuation")
    wacc = _find_outputs(outputs, "run_wacc")
    profiles = _find_outputs(outputs, "profile")
    key_metrics_all = _find_outputs(outputs, "key_metrics")

    if not (full or dcf or graham or pe):
        return None

    symbols = extract_symbols(message, outputs)
    symbol = symbols[0] if symbols else None
    profile = _first_for_symbol(profiles, symbol)
    metrics = _first_for_symbol(key_metrics_all, symbol)

    if isinstance(profile, dict):
        entity = _build_entity_from_profile(profile, symbol or "")
    else:
        m = metrics if isinstance(metrics, dict) else {}
        entity = Entity(label=symbol or "Company", ticker=symbol, currency=_currency_for(symbol),
                        current_price=_to_float(m.get("current_price")))
    entity = _merge_entity_with_metrics(entity, metrics if isinstance(metrics, dict) else None)
    currency = entity.currency or "INR"

    full_payload = full[0] if full else None
    summary = (full_payload or {}).get("summary") if isinstance(full_payload, dict) else None
    avg_iv: Optional[float] = None
    verdict: Optional[str] = None
    upside_pct: Optional[float] = None
    current_price: Optional[float] = entity.current_price
    if isinstance(summary, dict):
        avg_iv = _to_float(summary.get("average_intrinsic_value"))
        verdict = summary.get("verdict")
        upside_pct = _to_float(summary.get("upside_pct"))
        current_price = _to_float(summary.get("current_price")) or current_price

    cards: list[MetricCard] = []
    cards.append(MetricCard(
        label="Current price",
        value=_price(current_price, currency),
        icon="trending-up",
        is_partial=current_price is None,
    ))
    cards.append(MetricCard(
        label="Avg intrinsic",
        value=_price(avg_iv, currency),
        change=f"{upside_pct:+.1f}%" if upside_pct is not None else None,
        change_type=_change_type(upside_pct),
        icon="scale",
        tooltip="Average of DCF, Graham, PE relative, EV/EBITDA, DDM intrinsic values",
        is_partial=avg_iv is None,
    ))
    cards.append(MetricCard(
        label="Verdict",
        value=verdict or "n/a",
        change_type="positive" if verdict == "UNDERVALUED" else "negative" if verdict == "OVERVALUED" else "neutral",
        icon="percent",
        is_partial=verdict is None,
    ))
    if isinstance(wacc, list) and wacc and isinstance(wacc[0], dict):
        w = wacc[0].get("wacc")
        cards.append(MetricCard(
            label="WACC",
            value=_pct(w) if w else "n/a",
            icon="briefcase",
            tooltip="Weighted average cost of capital",
            is_partial=w is None,
        ))

    # ----- Model breakdown chart -----
    charts: list[Chart] = []
    if isinstance(summary, dict):
        ivs = summary.get("intrinsic_values_by_model") or {}
        if isinstance(ivs, dict) and ivs:
            charts.append(Chart(
                id="iv-by-model",
                kind="bar",
                title="Intrinsic value by model",
                subtitle=f"vs current price {_price(current_price, currency)}",
                x_labels=list(ivs.keys()),
                series=[ChartSeries(
                    name="Fair value",
                    color="#8b5cf6",
                    values=[_to_float(v) for v in ivs.values()],
                    unit=currency,
                )],
                currency=currency,
                y_unit=currency,
            ))

    valuation_summary = summary if isinstance(summary, dict) else None

    title = f"Valuation: {entity.label}"
    return RichResponse(
        mode=RICH_MODE_VALUATION,
        title=title,
        subtitle=f"Multi-model intrinsic value vs current price ({currency})",
        primary_entity=entity,
        metric_cards=cards,
        charts=charts,
        valuation_summary=valuation_summary,
        markdown_body=markdown_body,
        data_sources=_default_sources(currency == "INR"),
        is_partial=any(c.is_partial for c in cards),
    )


# ---------------------------------------------------------------------------
# News assembler
# ---------------------------------------------------------------------------


def _assemble_news(message: str, outputs: list[ToolOutput], markdown_body: str) -> Optional[RichResponse]:
    news = _find_outputs(outputs, "get_latest_company_news") + _find_outputs(outputs, "search_news") + _find_outputs(outputs, "search_financial")
    if not news:
        return None
    headlines = _news_to_headlines(news, primary=None, secondary=None)
    if not headlines:
        return None
    symbols = extract_symbols(message, outputs)
    title = f"Latest news: {symbols[0]}" if symbols else "Latest news"
    return RichResponse(
        mode=RICH_MODE_NEWS,
        title=title,
        headlines=headlines,
        markdown_body=markdown_body,
        data_sources=[DataSource(label="Tavily"), DataSource(label="Google News")],
    )


# ---------------------------------------------------------------------------
# Filing assembler (DRHP / RHP / prospectus / annual report)
# ---------------------------------------------------------------------------


def _assemble_filing(message: str, outputs: list[ToolOutput], markdown_body: str) -> Optional[RichResponse]:
    fetched = _find_outputs(outputs, "doc_fetch_annual_report") + _find_outputs(outputs, "doc_ingest_url") + _find_outputs(outputs, "doc_ingest_pdf") + _find_outputs(outputs, "doc_search")
    if not fetched:
        return None
    sections: list[dict[str, Any]] = []
    for payload in fetched:
        if isinstance(payload, dict):
            named = payload.get("sections") or payload.get("named_sections")
            if isinstance(named, dict):
                for sec_name, sec in named.items():
                    if isinstance(sec, dict):
                        sections.append({"name": sec_name, "excerpt": (sec.get("text") or "")[:600]})
    if not sections:
        return None
    return RichResponse(
        mode=RICH_MODE_FILING,
        title="Filing analysis",
        filing_sections=sections,
        markdown_body=markdown_body,
    )


def _assemble_doc_compare(message: str, outputs: list[ToolOutput], markdown_body: str) -> Optional[RichResponse]:
    compared = _find_outputs(outputs, "doc_compare_offer_documents")
    if not compared:
        return None
    sections: list[dict[str, Any]] = []
    for payload in compared:
        if isinstance(payload, dict):
            for k, v in payload.items():
                if isinstance(v, dict) or isinstance(v, str):
                    sections.append({"name": k, "excerpt": str(v)[:600]})
    return RichResponse(
        mode=RICH_MODE_DOC_COMPARE,
        title="Document version comparison",
        filing_sections=sections,
        markdown_body=markdown_body,
    )


# ---------------------------------------------------------------------------
# Native bridge — build RichResponse from agent findings + enrichment bundle
# ---------------------------------------------------------------------------


def _native_entity_from_bundle(bundle: Any) -> Optional[Entity]:
    """Build an Entity from bundle.yahoo or bundle.india_snap."""
    y = getattr(bundle, "yahoo", None)
    india = getattr(bundle, "india_snap", None)

    if y and hasattr(y, "ticker"):
        currency = getattr(y, "currency", None) or "INR"
        return Entity(
            label=getattr(y, "name", getattr(y, "ticker", "Company")),
            ticker=getattr(y, "ticker", None),
            exchange=getattr(y, "exchange", None),
            currency=currency.upper(),
            market_cap=_to_float(getattr(y, "market_cap", None)),
            current_price=_to_float(getattr(y, "price", None)),
            change_pct=_to_float(getattr(y, "change_pct", None)),
            fifty_two_week_high=_to_float(getattr(y, "fifty_two_week_high", None)),
            fifty_two_week_low=_to_float(getattr(y, "fifty_two_week_low", None)),
            pe=_to_float(getattr(y, "financial_metrics", {}).get("trailing_pe")) if hasattr(y, "financial_metrics") else None,
            pb=_to_float(getattr(y, "financial_metrics", {}).get("price_to_book")) if hasattr(y, "financial_metrics") else None,
            roe=_to_float(getattr(y, "financial_metrics", {}).get("return_on_equity")) if hasattr(y, "financial_metrics") else None,
            profit_margin=_to_float(getattr(y, "financial_metrics", {}).get("profit_margins")) if hasattr(y, "financial_metrics") else None,
            operating_margin=_to_float(getattr(y, "financial_metrics", {}).get("operating_margins")) if hasattr(y, "financial_metrics") else None,
            revenue_growth=_to_float(getattr(y, "financial_metrics", {}).get("revenue_growth")) if hasattr(y, "financial_metrics") else None,
            debt_to_equity=_to_float(getattr(y, "financial_metrics", {}).get("debt_to_equity")) if hasattr(y, "financial_metrics") else None,
            dividend_yield=_to_float(getattr(y, "financial_metrics", {}).get("dividend_yield")) if hasattr(y, "financial_metrics") else None,
        )

    if india and hasattr(india, "symbol"):
        return Entity(
            label=getattr(india, "company_name", getattr(india, "symbol", "Company")),
            ticker=getattr(india, "symbol", None),
            exchange=getattr(india, "exchange", "NSE"),
            sector=getattr(india, "sector", None),
            industry=getattr(india, "industry", None),
            currency="INR",
            market_cap=_to_float(getattr(india, "market_cap_cr", None)),
            current_price=_to_float(getattr(india, "current_price", None)),
            change_pct=_to_float(getattr(india, "change_pct", None)),
            pe=_to_float(getattr(india, "pe_ratio", None)),
            pb=_to_float(getattr(india, "pb_ratio", None)),
            roe=_to_float(getattr(india, "roe", None)),
            debt_to_equity=_to_float(getattr(india, "debt_to_equity", None)),
            dividend_yield=_to_float(getattr(india, "dividend_yield", None)),
        )

    return None


def _native_valuation_assemble(
    bundle: Any,
    findings: list[Any] | None,
    memo: str,
) -> Optional[RichResponse]:
    """Assemble a valuation-mode RichResponse from native agent findings."""
    entity = _native_entity_from_bundle(bundle)
    if not entity:
        return None

    currency = entity.currency or "INR"
    val_findings = [f for f in (findings or []) if getattr(f, "agent", "").lower() == "valuation"]

    intrinsic: Optional[float] = None
    current_price: Optional[float] = entity.current_price
    upside_pct: Optional[float] = None
    growth_rate: Optional[float] = None
    model_used: Optional[str] = None
    fcf: Optional[float] = None
    wacc_val: Optional[float] = None
    iv_by_model: dict[str, Any] = {}

    for f in val_findings:
        metrics = getattr(f, "metrics", None)
        if not isinstance(metrics, dict):
            continue
        if "intrinsic_value" in metrics and metrics["intrinsic_value"] is not None:
            intrinsic = _to_float(metrics["intrinsic_value"])
        if "current_price" in metrics and metrics["current_price"] is not None:
            current_price = _to_float(metrics["current_price"])
        if "upside_pct" in metrics and metrics["upside_pct"] is not None:
            upside_pct = _to_float(metrics["upside_pct"])
        if "implied_growth_rate" in metrics and metrics["implied_growth_rate"] is not None:
            growth_rate = _to_float(metrics["implied_growth_rate"])
        if "model_used" in metrics:
            model_used = str(metrics["model_used"])
        if "fcf" in metrics and metrics["fcf"] is not None:
            fcf = _to_float(metrics["fcf"])

    # Infer verdict
    verdict: Optional[str] = None
    if intrinsic and current_price:
        if intrinsic > current_price * 1.15:
            verdict = "UNDERVALUED"
        elif intrinsic < current_price * 0.85:
            verdict = "OVERVALUED"
        else:
            verdict = "FAIRLY VALUED"
        iv_by_model["DCF"] = intrinsic

    cards: list[MetricCard] = []
    cards.append(MetricCard(
        label="Current price",
        value=_price(current_price, currency) if current_price else "n/a",
        icon="trending-up",
        is_partial=current_price is None,
    ))
    cards.append(MetricCard(
        label="DCF intrinsic",
        value=_price(intrinsic, currency) if intrinsic else "n/a",
        change=f"{upside_pct:+.1f}%" if upside_pct is not None else None,
        change_type=_change_type(upside_pct),
        icon="scale",
        tooltip="Discounted Cash Flow fair value per share",
        is_partial=intrinsic is None,
    ))
    cards.append(MetricCard(
        label="Verdict",
        value=verdict or "n/a",
        change_type="positive" if verdict == "UNDERVALUED" else "negative" if verdict == "OVERVALUED" else "neutral",
        icon="percent",
        is_partial=verdict is None,
    ))
    cards.append(MetricCard(
        label="Implied growth",
        value=f"{growth_rate*100:.1f}%" if growth_rate else "n/a",
        icon="percent",
        tooltip="Revenue growth rate implied by the forecast model",
        is_partial=growth_rate is None,
    ))
    cards.append(MetricCard(
        label="Forecast model",
        value=model_used or "n/a",
        icon="chip",
        tooltip="timesfm_2.5 = real model; fallback = statistical",
        is_partial=model_used in (None, "fallback_cagr", "fallback_statistical"),
    ))
    if fcf:
        cards.append(MetricCard(
            label="FCF (TTM)",
            value=_money(fcf, currency),
            icon="currency-dollar",
            tooltip="Trailing twelve-month Free Cash Flow",
        ))

    # Charts
    charts: list[Chart] = []
    if iv_by_model and current_price:
        charts.append(Chart(
            id="iv-by-model",
            kind="bar",
            title="Intrinsic value vs market price",
            subtitle=currency,
            x_labels=["Market Price", "DCF Intrinsic"],
            series=[ChartSeries(
                name="Value",
                color="#8b5cf6",
                values=[current_price, intrinsic] if intrinsic else [current_price, 0],
                unit=currency,
            )],
            currency=currency,
            y_unit=currency,
        ))

    # Projection line chart from findings
    proj_points: Optional[list[float]] = None
    p10_points: Optional[list[float]] = None
    p90_points: Optional[list[float]] = None
    for f in val_findings:
        metrics = getattr(f, "metrics", None)
        if isinstance(metrics, dict) and "projected_terminal_revenue" in metrics:
            # If we have a point_forecast list, use it; otherwise make a 2-point
            # placeholder from historical → terminal.
            pt = metrics.get("point_forecast")
            if isinstance(pt, list) and len(pt) >= 2:
                proj_points = [_to_float(v) for v in pt]
            else:
                # Build synthetic trajectory
                hist_cagr = metrics.get("historical_cagr")
                terminal = _to_float(metrics.get("projected_terminal_revenue"))
                if terminal:
                    proj_points = [terminal * 0.8, terminal]  # placeholder
            p10_points = metrics.get("p10_terminal")
            p90_points = metrics.get("p90_terminal")
            break

    if proj_points and len(proj_points) >= 2:
        labels = [f"Y{i+1}" for i in range(len(proj_points))]
        series = [ChartSeries(
            name="Projected Revenue",
            color="#10b981",
            values=proj_points,
            unit="Cr" if currency == "INR" else "B",
        )]
        if isinstance(p10_points, list) and len(p10_points) == len(proj_points):
            series.append(ChartSeries(
                name="P10 (Conservative)",
                color="#f59e0b",
                values=[_to_float(v) for v in p10_points],
                unit="Cr" if currency == "INR" else "B",
            ))
        if isinstance(p90_points, list) and len(p90_points) == len(proj_points):
            series.append(ChartSeries(
                name="P90 (Optimistic)",
                color="#8b5cf6",
                values=[_to_float(v) for v in p90_points],
                unit="Cr" if currency == "INR" else "B",
            ))
        charts.append(Chart(
            id="dcf-projection",
            kind="line",
            title="Revenue projection",
            subtitle=f"Model: {model_used or 'statistical fallback'}",
            x_labels=labels,
            series=series,
            currency=currency,
            y_unit="Cr" if currency == "INR" else "B",
            is_partial=model_used in (None, "fallback_cagr", "fallback_statistical"),
        ))

    valuation_summary: Optional[dict[str, Any]] = None
    if intrinsic or verdict:
        valuation_summary = {
            "intrinsic_values_by_model": iv_by_model,
            "average_intrinsic_value": intrinsic,
            "current_price": current_price,
            "upside_pct": upside_pct,
            "verdict": verdict,
        }

    title = f"Valuation: {entity.label}"
    return RichResponse(
        mode=RICH_MODE_VALUATION,
        title=title,
        subtitle=f"Multi-model intrinsic value vs current price ({currency})",
        primary_entity=entity,
        metric_cards=cards,
        charts=charts,
        valuation_summary=valuation_summary,
        markdown_body=memo,
        data_sources=_default_sources(currency == "INR"),
        is_partial=any(c.is_partial for c in cards),
    )


def _native_snapshot_assemble(
    bundle: Any,
    findings: list[Any] | None,
    memo: str,
) -> Optional[RichResponse]:
    """Assemble a snapshot-mode RichResponse from native agent findings."""
    entity = _native_entity_from_bundle(bundle)
    if not entity:
        return None

    currency = entity.currency or "INR"
    cards: list[MetricCard] = []
    cards.append(MetricCard(
        label="Market cap",
        value=_money(entity.market_cap, currency),
        tooltip="Total market value of outstanding shares",
        icon="briefcase",
        is_partial=entity.market_cap is None,
    ))
    cards.append(MetricCard(
        label="52-wk high",
        value=_price(entity.fifty_two_week_high, currency),
        tooltip="Highest traded price in the past 52 weeks",
        icon="trending-up",
        is_partial=entity.fifty_two_week_high is None,
    ))
    cards.append(MetricCard(
        label="52-wk low",
        value=_price(entity.fifty_two_week_low, currency),
        tooltip="Lowest traded price in the past 52 weeks",
        icon="trending-down",
        is_partial=entity.fifty_two_week_low is None,
    ))
    cards.append(MetricCard(
        label="Div. yield",
        value=_pct(entity.dividend_yield, assume_fraction=False) if (
            entity.dividend_yield is not None and entity.dividend_yield > 1
        ) else _pct(entity.dividend_yield),
        tooltip="Annual dividend per share / current price",
        icon="percent",
        is_partial=entity.dividend_yield is None,
    ))
    de_val = entity.debt_to_equity
    de_str = "n/a"
    if de_val is not None:
        de_str = f"{de_val / 100:.2f}x" if de_val > 5 else f"{de_val:.2f}x"
    cards.append(MetricCard(
        label="Debt/Equity",
        value=de_str,
        tooltip="Total debt divided by shareholders' equity",
        icon="scale",
        change_type="negative" if de_val and de_val > 1.5 * 100 else "neutral",
        is_partial=de_val is None,
    ))
    cards.append(MetricCard(
        label="ROE",
        value=_pct(entity.roe),
        tooltip="Net income / shareholders' equity",
        icon="trending-up",
        change_type=_change_type(entity.roe),
        is_partial=entity.roe is None,
    ))

    # Strengths / risks from findings
    sr = _derive_strengths_risks(entity)
    sr_blocks: list[StrengthsRisksBlock] = []
    if sr:
        sr_blocks.append(StrengthsRisksBlock(entity_label=entity.label, **sr))

    return RichResponse(
        mode=RICH_MODE_SNAPSHOT,
        title=entity.label,
        subtitle=" | ".join(filter(None, [entity.exchange, entity.ticker, entity.sector])),
        primary_entity=entity,
        metric_cards=cards,
        charts=[],
        strengths_risks=sr_blocks,
        markdown_body=memo,
        data_sources=_default_sources(currency == "INR"),
        is_partial=any(c.is_partial for c in cards),
    )


def build_from_native(
    objective: str,
    bundle: Any,
    docs: Any,
    specialist_findings: list[Any] | None,
    memo: str,
) -> Optional[RichResponse]:
    """Build a RichResponse directly from agent findings + enrichment bundle.

    This is the native-data equivalent of `build()` which expects LangGraph
    ToolOutput lists.  Use this when the pipeline has already run the
    multi-agent orchestrator and produced specialist_findings.
    """
    if not bundle:
        return None
    mode = classify_rich_mode(objective)
    try:
        if mode == RICH_MODE_VALUATION:
            return _native_valuation_assemble(bundle, specialist_findings, memo) \
                or _native_snapshot_assemble(bundle, specialist_findings, memo)
        if mode == RICH_MODE_SNAPSHOT:
            return _native_snapshot_assemble(bundle, specialist_findings, memo)
        # Comparison, news, filing modes not yet bridged — fallback to snapshot
        return _native_snapshot_assemble(bundle, specialist_findings, memo)
    except Exception:
        logger.exception("rich_builder native bridge failed; falling back to markdown-only")
        return None


# ---------------------------------------------------------------------------
# Public entrypoint (LangGraph ToolOutput style)
# ---------------------------------------------------------------------------


def build(message: str, outputs: list[ToolOutput], agents_used: list[str], final_markdown: str) -> Optional[RichResponse]:
    """Pick the right assembler based on the user query and the observed
    tool outputs. Returns None when there isn't enough structured data."""
    if detect_primary_intent(message) == PRIMARY_INTENT_EVENT_EXPLAINER:
        return None
    mode = classify_rich_mode(message)
    try:
        if mode == RICH_MODE_COMPARISON:
            return _assemble_comparison(message, outputs, final_markdown) \
                or _assemble_snapshot(message, outputs, final_markdown)
        if mode == RICH_MODE_VALUATION:
            return _assemble_valuation(message, outputs, final_markdown) \
                or _assemble_snapshot(message, outputs, final_markdown)
        if mode == RICH_MODE_NEWS:
            return _assemble_news(message, outputs, final_markdown)
        if mode == RICH_MODE_FILING:
            return _assemble_filing(message, outputs, final_markdown)
        if mode == RICH_MODE_DOC_COMPARE:
            return _assemble_doc_compare(message, outputs, final_markdown) \
                or _assemble_filing(message, outputs, final_markdown)
        if mode == RICH_MODE_SNAPSHOT:
            return _assemble_snapshot(message, outputs, final_markdown)
        # mode == RICH_MODE_CHAT
        return None
    except Exception:
        logger.exception("rich_builder failed; falling back to markdown-only")
        return None


__all__ = [
    "RichResponse",
    "ToolOutput",
    "build",
    "build_from_native",
    "Entity",
    "MetricCard",
    "Chart",
    "ChartSeries",
    "ComparisonRow",
    "StrengthsRisksBlock",
    "NewsHeadline",
    "DataSource",
]

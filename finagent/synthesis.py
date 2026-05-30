"""LLM synthesis pass — turn the full evidence pool into a readable memo.

When OPENAI_API_KEY is set we stream tokens from OpenAI. When it isn't
we still produce a polished prose memo from the same fact bundle.

All monetary figures are presented in INR (crore/lakh notation) first.
The memo never invents numbers — every figure is sourced from NSE/BSE,
Moneycontrol, Screener.in, SEBI filings, the live Yahoo quote (.NS/.BO),
or domestic financial-media signals.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from finagent.analysis.conflicts import ConflictReport
from finagent.output.artifact_builder import build_answer_artifact
from finagent.output.contracts import AnswerArtifact, OutputMode, ResponseDepth
from finagent.output.intent_classifier import classify_output_mode, extract_finance_entities, normalize_depth
from finagent.output.memo_formatter import MemoSection, format_memo
from finagent.output.renderer import render_markdown, render_rich_json
import finagent.rich_builder as teammate_rich_builder
from finagent.router.intent_router import is_portfolio_scope_query
from finagent.output.query_guards import is_portfolio_comparison_query

from finagent.prompt_builder import default_system_prompt
from finagent.runtime_provider import resolve_openai_config
from finagent.state.checkpoint import Checkpoint
from finagent.state.citation_log import Citation
from finagent.tools.data import (
    FxRate,
    IndiaCompanySnapshot,
    NewsItem,
    SEBIFiling,
    WikipediaSummary,
    YahooQuote,
    format_dual,
    format_inr,
    fetch_yahoo_quote,
)
from finagent.tools.web.scraper import ScrapedDoc

logger = logging.getLogger("finagent.synthesis")

_MEMO_BUDGET_CHARS = 12000

TokenSink = Callable[[str], Awaitable[None]] | Callable[[str], None] | None


@dataclass
class EnrichmentBundle:
    # India-specific data sources.
    india_snap: IndiaCompanySnapshot | None = None
    sebi_filing: SEBIFiling | None = None
    shareholding: dict | None = None
    # Universal sources
    yahoo: YahooQuote | None = None
    wikipedia: WikipediaSummary | None = None
    fx: FxRate | None = None
    news: list[NewsItem] = field(default_factory=list)

    def has_any(self) -> bool:
        return bool(
            self.india_snap
            or self.yahoo
            or self.wikipedia
            or self.sebi_filing
            or self.news
        )

    # Compatibility shim for older structured-data call sites
    @property
    def sec(self) -> IndiaCompanySnapshot | None:       # type: ignore[override]
        return self.india_snap

    @property
    def filing(self) -> SEBIFiling | None:              # type: ignore[override]
        return self.sebi_filing


@dataclass
class SynthesisResult:
    memo: str
    via: str  # "openai" | "structured"
    used_sources: int
    artifact: AnswerArtifact | None = None
    rich: dict | None = None  # result of render_rich_json(artifact)


# ──────────────────────────────────────────────────────────────────────────
#  Helpers — number formatting, prose tidying
# ──────────────────────────────────────────────────────────────────────────


_FX_FALLBACK = 83.4
_TRIPLE_ASTERISK = re.compile(r"\*{2,}")
_SINGLE_EMPH = re.compile(r"\*([^*\n]{1,80})\*")
_LEADING_BULLET = re.compile(r"^\s*[-*•]\s+", flags=re.MULTILINE)


def _scale_factor(unit: str | None) -> float:
    if not unit:
        return 1.0
    u = unit.lower().strip()
    if u in ("trillion", "tn", "t"):
        return 1e12
    if u in ("billion", "bn", "b"):
        return 1e9
    if u in ("million", "mn", "m"):
        return 1e6
    if u in ("thousand", "k"):
        return 1e3
    return 1.0


def _scrub_prose(text: str) -> str:
    """Strip leftover Markdown emphasis and bullet clutter so the memo reads
    as natural prose rather than a generation artifact."""
    if not text:
        return ""
    cleaned = _TRIPLE_ASTERISK.sub("", text)
    cleaned = cleaned.replace("**", "")
    cleaned = _SINGLE_EMPH.sub(r"\1", cleaned)
    cleaned = _LEADING_BULLET.sub("", cleaned)
    cleaned = cleaned.replace("\r\n", "\n").replace("\xa0", " ")
    # Compress noisy punctuation: ", , " -> ", "; "..." -> "."
    cleaned = re.sub(r",\s*,", ",", cleaned)
    cleaned = re.sub(r"\.{3,}", ".", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


_STRUCTURED_FENCE_RE = re.compile(r"```(?:chart|kpi|mermaid)\b[\s\S]*?```", re.IGNORECASE)


def _substantive_text_len(text: str) -> int:
    """Count prose characters after removing structured visual fences."""
    if not text:
        return 0
    prose = _STRUCTURED_FENCE_RE.sub("", text)
    prose = re.sub(r"[#*_`\|\-\s]+", " ", prose)
    return len(prose.strip())


def _ensure_balanced_memo(memo: str, artifact: AnswerArtifact) -> str:
    """Guarantee the answer has substantive prose whenever visuals exist."""
    visual_count = len(getattr(artifact, "metric_cards", []) or []) + len(getattr(artifact, "charts", []) or [])
    if visual_count == 0:
        return memo
    if _substantive_text_len(memo) >= 400:
        return memo
    structured_memo = render_markdown(artifact)
    if _substantive_text_len(structured_memo) > _substantive_text_len(memo):
        logger.warning(
            "[SYNTH-BALANCE] Replaced visual-heavy memo with structured prose fallback | visuals=%d | prose_chars=%d",
            visual_count,
            _substantive_text_len(memo),
        )
        return structured_memo
    return memo


def _attach_markdown_body(rich: dict | None, memo: str) -> dict | None:
    """Keep the final rich payload self-contained for frontend fallbacks."""
    if rich is None:
        return None
    try:
        rich["markdown_body"] = memo
    except Exception:
        pass
    return rich


def _amount_to_usd(value: float, unit: str) -> float:
    u = (unit or "").upper()
    if u == "USD":
        return value
    # Share-count units are left untouched.
    return value


def _get_attr_or_key(obj, key, default=None):
    """Safely get attribute or dict key."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _format_money(value: float | None, unit: str | None, fx: FxRate | None) -> str:
    if value is None:
        return "n/a"
    unit = (unit or "USD").upper()
    if unit not in ("USD", "USD/SHARES"):
        # Non-monetary metric (share count, ratio). Show raw.
        return f"{value:,.0f} {unit.lower()}"
    rate = fx.rate if fx else _FX_FALLBACK
    return format_dual(value, rate)


def _format_price(usd_price: float | None, currency: str | None, fx: FxRate | None) -> str:
    if usd_price is None:
        return "n/a"
    currency = (currency or "USD").upper()
    if currency == "INR":
        # India-first: lead with INR for NSE/BSE listed companies
        from finagent.tools.data.forex import format_inr as _fmt_inr
        return _fmt_inr(usd_price, 1.0)
    if currency != "USD":
        return f"{currency} {usd_price:,.2f}"
    rate = fx.rate if fx else _FX_FALLBACK
    # For USD prices, show INR first (India-focused)
    return f"₹{usd_price*rate:,.2f} (${usd_price:,.2f})"


def _format_local_money(value: float | None, currency: str | None, fx: FxRate | None) -> str:
    if value is None:
        return "n/a"
    currency = (currency or "USD").upper()
    sign = "-" if value < 0 else ""
    abs_value = abs(value)
    if currency == "USD":
        rate = fx.rate if fx else _FX_FALLBACK
        return f"{sign}{format_dual(abs_value, rate)}"
    if currency == "INR":
        return f"{sign}{format_inr(abs_value, 1.0)}"
    if abs_value >= 1e9:
        compact = f"{abs_value/1e9:,.2f}B"
    elif abs_value >= 1e6:
        compact = f"{abs_value/1e6:,.2f}M"
    elif abs_value >= 1e3:
        compact = f"{abs_value/1e3:,.2f}K"
    else:
        compact = f"{abs_value:,.2f}"
    return f"{sign}{currency} {compact}"


# ──────────────────────────────────────────────────────────────────────────
#  LLM-facing fact block (compact, no decoration)
# ──────────────────────────────────────────────────────────────────────────


def _build_source_digest(docs: list[ScrapedDoc], *, budget_chars: int = _MEMO_BUDGET_CHARS) -> tuple[str, int]:
    lines: list[str] = []
    used = 0
    char_total = 0
    for d in docs:
        if char_total >= budget_chars:
            break
        title = (d.title or "(no title)").strip()
        excerpt = (d.excerpt or "").strip().replace("\n", " ")
        block = (
            f"**Source {used + 1}**\n"
            f"- URL: {d.final_url}\n"
            f"- Domain: {d.domain} (tier {d.tier})\n"
            f"- Title: {title}\n"
            f"- Blocked: {d.blocked_reason or 'no'}\n"
            f"- Excerpt: {excerpt[:700]}\n"
        )
        lines.append(block)
        char_total += len(block)
        used += 1
    return "\n".join(lines), used


def _build_facts_block(bundle: EnrichmentBundle) -> str:
    lines: list[str] = []
    fx = bundle.fx
    if fx:
        lines.append(f"FX rate USD/INR = {fx.rate:.4f} (source: {fx.source})")
        lines.append("All USD figures should be expressed with an INR equivalent in parentheses.")
    if bundle.filing:
        f = bundle.filing
        lines.append(f"\nFiling narrative ({f.form} filed {f.filed_date}):")
        if f.business:
            lines.append(f"  Business overview (Item 1): {f.business[:1500]}")
        if f.risk_factors:
            lines.append(f"  Risk factors (Item 1A): {f.risk_factors[:1800]}")
        if f.mdna:
            lines.append(f"  MD&A (Item 7): {f.mdna[:1500]}")
    # India snapshot section (for Indian-listed companies)
    india_snap = getattr(bundle, "india_snap", None)
    _is_india_snap = india_snap is not None and hasattr(india_snap, "market_cap_cr")
    if _is_india_snap:
        s = india_snap
        lines.append(
            f"\nIndia Market Data: {s.symbol} | {s.company_name or s.symbol} "
            f"| Exchange: {s.exchange or 'NSE/BSE'}"
        )
        if s.sector:
            lines.append(f"  Sector: {s.sector}")
        if s.industry:
            lines.append(f"  Industry: {s.industry}")
        if s.current_price is not None:
            chg = f" ({s.change_pct:+.2f}%)" if s.change_pct is not None else ""
            lines.append(f"  Current price: ₹{s.current_price:,.2f}{chg}")
        if s.week_52_high is not None and s.week_52_low is not None:
            lines.append(f"  52-week range: ₹{s.week_52_low:,.2f} – ₹{s.week_52_high:,.2f}")
        if s.market_cap_cr is not None:
            lines.append(f"  Market cap: ₹{s.market_cap_cr:,.0f} Cr")
        # Key ratios
        ratio_parts: list[str] = []
        if s.pe_ratio  is not None: ratio_parts.append(f"P/E {s.pe_ratio:.2f}x")
        if s.pb_ratio  is not None: ratio_parts.append(f"P/B {s.pb_ratio:.2f}x")
        if s.roe       is not None: ratio_parts.append(f"ROE {s.roe:.1f}%")
        if s.roce      is not None: ratio_parts.append(f"ROCE {s.roce:.1f}%")
        if s.eps       is not None: ratio_parts.append(f"EPS ₹{s.eps:.2f}")
        if s.book_value is not None: ratio_parts.append(f"Book value ₹{s.book_value:.2f}")
        if s.dividend_yield is not None: ratio_parts.append(f"Div yield {s.dividend_yield:.2f}%")
        if s.debt_to_equity is not None: ratio_parts.append(f"D/E {s.debt_to_equity:.2f}")
        if ratio_parts:
            lines.append("  Ratios: " + ", ".join(ratio_parts))
        # Shareholding
        holding_parts: list[str] = []
        if s.promoter_holding  is not None: holding_parts.append(f"Promoter {s.promoter_holding:.1f}%")
        if s.fii_holding       is not None: holding_parts.append(f"FII {s.fii_holding:.1f}%")
        if s.dii_holding       is not None: holding_parts.append(f"DII {s.dii_holding:.1f}%")
        if s.promoter_pledge_pct is not None: holding_parts.append(f"Pledge {s.promoter_pledge_pct:.1f}%")
        if holding_parts:
            lines.append("  Shareholding: " + ", ".join(holding_parts))
        lines.append(f"  Data source: {s.source} ({s.source_url})")
    elif bundle.sec:
        # Structured data fallback path.
        s = bundle.sec
        lines.append(f"\nStructured market data: {s.ticker} | {s.name} | identifier {s.cik}")
        if s.sic_description:
            lines.append(f"  Industry (SIC): {s.sic_description}")
        if s.exchanges:
            lines.append(f"  Listed on: {', '.join(s.exchanges)}")
        for key, m in s.metrics.items():
            # m is a structured metric dataclass — use its methods
            try:
                inr_part = ""
                if fx and getattr(m, "unit", "").upper() == "USD":
                    inr_part = f" / INR ~ {format_inr(m.value, fx.rate)}"
                lines.append(
                    f"  {key} = {m.display_value()}{inr_part} "
                    f"({m.label}; {m.form} FY{m.fy} {m.fp or ''} ending {m.end})"
                )
            except Exception:
                lines.append(f"  {key} = {m}")
        if s.recent_filings:
            lines.append("  Recent filings:")
            for f in s.recent_filings[:6]:
                lines.append(f"    - {f.form} filed {f.filing_date} (report {f.report_date}): {f.url}")

    # Shareholding pattern (India — from NSE shareholding API)
    if getattr(bundle, "shareholding", None):
        sh = bundle.shareholding
        lines.append(
            f"\nShareholding pattern (latest): "
            f"Promoter {sh.get('promoter', 'n/a')}% | "
            f"FII {sh.get('fii', 'n/a')}% | "
            f"DII {sh.get('dii', 'n/a')}% | "
            f"Public {sh.get('public', 'n/a')}%"
            + (f" (as of {sh['as_of']})" if sh.get('as_of') else "")
        )

    # SEBI filing narrative
    sebi_fil = getattr(bundle, "sebi_filing", None)
    if sebi_fil and not isinstance(sebi_fil, type(None)):
        try:
            has_sebi_content = any([
                sebi_fil.business_overview, sebi_fil.risk_factors,
                sebi_fil.financial_summary, sebi_fil.management_discussion,
            ])
            if has_sebi_content:
                lines.append(f"\nSEBI/Trendlyne Analysis ({sebi_fil.company}):")
                if sebi_fil.business_overview:
                    lines.append(f"  Business overview: {sebi_fil.business_overview[:1200]}")
                if sebi_fil.management_discussion:
                    lines.append(f"  Management discussion: {sebi_fil.management_discussion[:1000]}")
                if sebi_fil.financial_summary:
                    lines.append(f"  Financial summary: {sebi_fil.financial_summary[:1000]}")
                if sebi_fil.risk_factors:
                    lines.append(f"  Risk factors: {sebi_fil.risk_factors[:1000]}")
        except Exception:
            pass
    if bundle.yahoo:
        y = bundle.yahoo
        chg = f"{y.change_pct:+.2f}%" if y.change_pct is not None else "n/a"
        usd_price_inr = ""
        if fx and (y.currency or "").upper() == "USD" and y.price:
            usd_price_inr = f" / INR ~₹{y.price*fx.rate:,.2f}"
        price_text = f"{y.price:,.2f}" if y.price is not None else "quote unavailable"
        prev_text = f"{y.previous_close:,.2f}" if y.previous_close is not None else "n/a"
        range_low = f"{y.fifty_two_week_low:,.2f}" if y.fifty_two_week_low is not None else "n/a"
        range_high = f"{y.fifty_two_week_high:,.2f}" if y.fifty_two_week_high is not None else "n/a"
        lines.append(
            f"\nYahoo Finance: {y.ticker} = {y.currency or ''} {price_text}{usd_price_inr} "
            f"(prev {prev_text}, {chg}); 52w {range_low}-{range_high}"
            f"; exchange {y.exchange or 'n/a'}"
        )
        if y.market_cap:
            lines.append(f"  Market cap: {_format_local_money(y.market_cap, y.currency, fx)}")
        if y.business_summary:
            lines.append(f"  Business summary: {y.business_summary[:900]}")
        if y.financial_metrics:
            for label, key in (
                ("Total revenue", "total_revenue"),
                ("EBITDA", "ebitda"),
                ("Free cash flow", "free_cashflow"),
                ("Total cash", "total_cash"),
                ("Total debt", "total_debt"),
            ):
                value = y.financial_metrics.get(key)
                if value is not None:
                    lines.append(f"  {label}: {_format_local_money(value, y.currency, fx)}")
            ratio_bits: list[str] = []
            for label, key in (
                ("Gross margin", "gross_margins"),
                ("Operating margin", "operating_margins"),
                ("Profit margin", "profit_margins"),
                ("ROE", "return_on_equity"),
                ("ROA", "return_on_assets"),
                ("Revenue growth", "revenue_growth"),
                ("Earnings growth", "earnings_growth"),
            ):
                value = y.financial_metrics.get(key)
                if value is not None:
                    ratio_bits.append(f"{label} {value * 100:.1f}%")
            for label, key in (
                ("Trailing P/E", "trailing_pe"),
                ("Forward P/E", "forward_pe"),
                ("P/B", "price_to_book"),
                ("Debt/equity", "debt_to_equity"),
                ("Current ratio", "current_ratio"),
            ):
                value = y.financial_metrics.get(key)
                if value is not None:
                    suffix = "%" if "yield" in key else "x"
                    ratio_bits.append(f"{label} {value:.2f}{suffix}")
            if ratio_bits:
                lines.append("  Ratios: " + ", ".join(ratio_bits))
        if y.annual_revenue:
            rev_pairs = [
                f"{date}: {_format_local_money(value, y.currency, fx)}"
                for date, value in zip(y.annual_revenue_dates, y.annual_revenue)
            ]
            lines.append("  Annual revenue history: " + "; ".join(rev_pairs[:6]))
        if y.annual_net_income:
            ni_pairs = [
                f"{date}: {_format_local_money(value, y.currency, fx)}"
                for date, value in zip(y.annual_net_income_dates, y.annual_net_income)
            ]
            lines.append("  Annual net income history: " + "; ".join(ni_pairs[:6]))
    if bundle.wikipedia:
        w = bundle.wikipedia
        excerpt = (w.extract or "").replace("\n", " ").strip()
        lines.append(f"\nWikipedia ({w.title}): {excerpt[:600]}")
    if not lines:
        return "(no API enrichment available)"
    return "\n".join(lines)


def _conflict_block(conflicts: list[ConflictReport]) -> str:
    if not conflicts:
        return ""
    lines = ["=== CONFLICTS DETECTED ==="]
    for c in conflicts:
        lines.append(f"- {c.note}")
        for o in c.observations:
            lines.append(f"    * {o.domain} (tier {o.tier}): {o.raw} -- '{o.context}'")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
#  OpenAI streaming path
# ──────────────────────────────────────────────────────────────────────────


async def _emit_token(sink: TokenSink, chunk: str) -> None:
    if sink is None or not chunk:
        return
    try:
        result = sink(chunk)
        if asyncio.iscoroutine(result):
            await result
    except Exception:
        logger.debug("token sink raised", exc_info=True)


_LLM_STYLE_GUIDE = """
ROLE & IDENTITY:
You are an elite institutional equity research director and conversational financial co-pilot for ProspektLab, specializing exclusively in the Indian capital markets. You operate with the conversational intelligence and adaptability of Claude and ChatGPT, combined with the extreme numerical precision of a chartered accountant.

CORE MANDATES & FINANCIAL COMPLIANCE:
1. GEOGRAPHY & ACCOUNTING: Base your reasoning entirely on Indian corporate parameters, SEBI LODR regulations, RBI monetary guidelines, and Ind-AS accounting standards. Never use US SEC/GAAP syntax (e.g., use "Shareholding Pattern" instead of "13F", "Concall Transcript" instead of "Earnings Call").
2. CURRENCY & UNIT FORMATTING: Present all monetary figures in Indian Rupee (INR) FIRST, enforcing strict Indian-style comma grouping and Crore/Lakh notation (e.g., ₹3.45 Cr or ₹45.6 L). Never lead with USD or apply Western million/billion formatting to domestic assets.
3. DATA GROUNDING: Do not invent or smooth numbers. If a financial metric is absent from the provided facts, omit it from KPI/chart/table blocks entirely. In prose, write it as 'N/A' — do not write multi-word 'data unavailable' explanations.
4. PORTFOLIO MIRROR GROUNDING: For portfolio questions, answer only from the synchronized `position_mirrors` holdings package and deterministic compute-core payloads supplied to you. If holdings are empty or ingestion is still active, tell the user to upload and synchronize holdings first instead of fabricating a sample portfolio.
5. NO LLM ARITHMETIC: Never calculate HHI, beta, CCB, VaR, ratios, or portfolio weights in prose. Quote exact values returned by the quantitative kernel or mark the metric as data unavailable.
6. CHAT EXPERIENCE: Write like a high-quality interactive assistant: direct first answer, clean sections when useful, concise bullets, and follow-up prompts only when they materially improve the user's next action. Avoid stiff research-report scaffolding unless the user explicitly asks for a full report.

### CONDITIONAL ROUTING PROTOCOLS

Evaluate the active session intent state to determine your exact structural response layout:

#### PROTOCOL A: INTENT IS 'comprehensive_profile'
- OBJECTIVE: Generate a publication-grade, uncompromised, and comprehensive equity research report.
- FORMATTING: Truncation or high-level summaries are strictly forbidden. Every single section below must be populated in full analytical depth (minimum 150 words per section) using clear Markdown headers (## for sections, **bold** for sub-emphasis — never ###), bold prose callouts, and clean markdown tables (`| HTML | Grids |`) for raw statements.
- REQUIRED RESTRUCTURING TEMPLATE:
  ## Business Overview
  [Detailed corporate ancestry, business segments, group ownership, and manufacturing scale]
  ## Financial Performance Evaluation
  [Consolidated revenues, EBITDA, PAT margins, YoY growth trends, and Ind-AS metrics]
  ## Strategic Initiatives & Capital Expenditure Catalysts
  [Capacity additions, order-book execution milestones, joint ventures, and quantified capex dates]
  ## Stock Valuation & Analyst Standings
  [Trailing/Forward P/E, EV/EBITDA, P/B multiples, Nifty 50 peer comparisons, and institutional price targets]
  ## Operational Strengths & Strategic Tail Risks
  [Order-book execution visibility, promoter pledge loops, input-cost exposures, and SEBI regulatory actions]
  ## Bottom Line Summary
  [Growth-quality synthesis and investment visibility verdict, concluded with a SEBI-compliant informational disclaimer]

#### PROTOCOL B: INTENT IS 'conversational_chat' OR ANY SPECIFIC CONVERSATIONAL FOLLOW-UP
- OBJECTIVE: Provide a direct, natural, and context-aware conversational response matching the exact scope of the latest user question.
- FORMATTING: Do NOT wrap your response in rigid template layouts, formal report sections, or fixed corporate headers.
- EXECUTION: Answer the user's question directly and comprehensively in the very first sentence. Use fluid, paragraph-driven prose. Integrate clean markdown bullet points or simple matrices natively ONLY if it directly clarifies the immediate answer. Maintain the context of prior turns smoothly without re-stating basic business overviews.

### STATISTICAL FORECASTING INTERPRETATION RULES
When the data package contains continuous forecasting arrays generated by the deterministic statistical projection path, interpret them using these explicit narrative rules:
- Refer to the 50th percentile baseline parameters natively as the "median projected trajectory" or "expected execution path".
- Translate the shaded upper and lower quantile boundaries (the 10th and 90th percentile risk confidence corridors) into plain English text, describing them as the "conservative bear-case floor" and "optimized bull-case ceiling" to provide the user with clear risk variance insight.

### DYNAMIC VISUAL CONTRACT (ChatGPT/Claude/Gemini-style structured output)
When the answer involves data that is easier to grasp visually — allocations, time-series, comparisons, or KPI dashboards — embed structured fenced blocks inline. The frontend will render these as live charts and stat cards.
Aim for mostly prose with selective visuals. Emit KPI/chart blocks only when every displayed number exists in the verified facts or deterministic compute payload. Do not emit placeholder, empty, zero-filled, or `N/A` KPI/chart/table blocks. Do not append all visuals at the bottom; place any visual immediately after the paragraph it supports.

Allowed fenced block types (emit ONLY when they genuinely aid comprehension; never force them for simple prose answers):

1. ` ```chart ` — for line, bar, donut, area charts.
   JSON schema inside the fence:
   ```chart
   {"type":"donut","title":"Sector Allocation","labels":["Financials","IT","Energy"],"datasets":[{"label":"Weight %","data":[35,25,15]}]}
   ```
   Supported types: line, bar, donut, area. Always include "title", "labels", and at least one dataset with "label" and "data".

2. ` ```kpi ` — for key metric cards.
   JSON schema inside the fence (can repeat multiple ` ```kpi ` blocks for a row):
   ```kpi
   {"label":"Portfolio Beta","value":"1.14","delta":"+0.08","trend":"up"}
   ```
   trend must be one of: up, down, flat.

3. ` ```mermaid ` — for flowcharts, decision trees, or process diagrams (existing capability, preserve).

Do not wrap chart/kpi blocks inside paragraphs — place them on their own lines with blank lines above and below so Markdown parsing is clean.

### INLINE VERIFICATION MARKERS & CITATIONS
You must continuously anchor your prose by injecting these explicit tracking markers immediately following every single statistic, metric, calculation, or claim:
- `[SOURCE: Domain/Filing]` — Cite the source document index or root domain (e.g., [SOURCE: NSE/Annual Report] or [SOURCE: Screener.in]).
- `[AS-OF: FYXX / QX]` — Pinpoint the precise accounting or reporting time horizon.
- `[ESTIMATE]` — Explicitly label any forward-looking calculation, valuation multiple projection, or statistical projection path.
- `[CONFLICT]` — Highlight instances where independent sources show contradictory or mismatched figures.

Conclude every major distinct text block or section with an explicit visibility confidence assessment tag: **[CONFIDENCE: HIGH | MEDIUM | LOW | DERIVED]**.
"""


_FOCUSED_OUTPUT_MODES = {
    "news_brief",
    "valuation_model",
    "direct_answer",
    "filing_analysis",
    "company_snapshot",
    "investment_view",
    "market_explainer",
    # New dynamic modes from intent-based agent selection
    "valuation_insights",      # Rich valuation output with statistical projections + model_used
    "forensic_insights",       # Forensic / anomaly detection output from AccountingAgent
    "conversational_chat"
}


def _synthesis_profile(mode: OutputMode, depth: ResponseDepth, objective: str) -> dict[str, int | float]:
    """Pick latency/quality budgets by response depth and output mode."""

    lower_objective = (objective or "").lower()
    is_deep = (
        depth == ResponseDepth.DEEP
        or mode == OutputMode.DEEP_RESEARCH_REPORT
        or any(kw in lower_objective for kw in ("deep_research_report", "synthesis", "investment-grade", "full-scale"))
    )
    if is_deep:
        return {
            "timeout_s": 180.0,
            "max_tokens": 8000,
            "digest_budget_chars": _MEMO_BUDGET_CHARS,
        }

    if depth == ResponseDepth.CHAT:
        return {
            "timeout_s": 20.0,
            "max_tokens": 1200,
            "digest_budget_chars": 3200,
        }

    if mode == OutputMode.COMPANY_COMPARISON:
        return {
            "timeout_s": 55.0,
            "max_tokens": 2600,
            "digest_budget_chars": 7600,
        }

    if mode in {
        OutputMode.COMPANY_SNAPSHOT,
        OutputMode.INVESTMENT_VIEW,
        OutputMode.MARKET_EXPLAINER,
        OutputMode.NEWS_BRIEF,
        OutputMode.DIRECT_ANSWER,
        OutputMode.CONVERSATIONAL_CHAT,
    }:
        return {
            "timeout_s": 35.0,
            "max_tokens": 1800,
            "digest_budget_chars": 5200,
        }

    return {
        "timeout_s": 45.0,
        "max_tokens": 2200,
        "digest_budget_chars": 6800,
    }


def _compact_chat_history(
    chat_history: list[dict[str, str]] | None,
    *,
    focused: bool,
    depth: ResponseDepth,
) -> list[dict[str, str]]:
    """Keep prior chat useful for entity continuity without drowning the next answer."""

    if not chat_history:
        return []
    compact: list[dict[str, str]] = []
    recent_messages = chat_history[-8:] if depth == ResponseDepth.DEEP else chat_history[-4:]
    for msg in recent_messages:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        if focused and role == "assistant":
            continue
        if depth == ResponseDepth.DEEP:
            limit = 600 if focused else (1800 if role == "assistant" else 900)
        elif depth == ResponseDepth.STANDARD:
            limit = 420 if focused else (700 if role == "assistant" else 500)
        else:
            limit = 300 if focused else (450 if role == "assistant" else 350)
        compact.append({"role": role, "content": content[:limit]})
    if focused or depth != ResponseDepth.DEEP:
        return compact[-4:]
    return compact


async def _openai_memo(
    target: str,
    objective: str,
    digest: str,
    facts: str,
    conflicts: list[ConflictReport],
    *,
    on_token: TokenSink = None,
    synth_model: str | None = None,
    chat_history: list[dict[str, str]] | None = None,
    output_mode: str | None = None,
    response_depth: str | None = None,
    force_non_stream: bool = False,
    user_email: str | None = None,
    session_id: str | None = None,
) -> str:
    cfg = resolve_openai_config()
    if cfg is None:
        raise RuntimeError("No LLM provider configured — set OPENAI_API_KEY or XAI_API_KEY")
    
    model_to_use = synth_model or cfg.model

    def _record_usage(usage_obj):
        if not user_email or not usage_obj:
            return
        try:
            from finagent.gateway.run import record_token_usage
            record_token_usage(
                user_email=user_email,
                session_id=session_id or "",
                prompt_tokens=getattr(usage_obj, "prompt_tokens", 0),
                completion_tokens=getattr(usage_obj, "completion_tokens", 0),
                model=model_to_use
            )
        except Exception as e:
            logger.debug("Failed to record token usage: %s", e)
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise RuntimeError("openai package not installed") from exc

    client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    system_prompt = default_system_prompt() + "\n" + _LLM_STYLE_GUIDE

    # Detect comparison queries to inject comparison-specific instructions
    # Portfolio-vs-benchmark queries must NOT receive company-comparison instructions.
    _lower_obj = (objective or "").lower()
    _is_comparison = any(t in _lower_obj for t in (" vs ", " versus ", "compare", "comparison", "against", "head to head")) and not is_portfolio_comparison_query(objective)

    if _is_comparison:
        comparison_instructions = (
            "This is a COMPARISON query. You MUST:\n"
            "1. Analyze BOTH companies equally with parallel depth.\n"
            "2. Structure the report with side-by-side analysis:\n"
            "   - ## Executive Summary (declare an overall winner with reasoning)\n"
            "   - ## Company Profiles (one subsection per company)\n"
            "   - ## Financial Comparison (use a markdown table: | Metric | Company A | Company B | Advantage |)\n"
            "   - ## Revenue & Growth Comparison\n"
            "   - ## Profitability & Margins\n"
            "   - ## Valuation Comparison (P/E, P/B, EV/EBITDA)\n"
            "   - ## Strengths & Weaknesses (parallel bullet points for each)\n"
            "   - ## Risk Comparison\n"
            "   - ## Investment Verdict (which is the better pick and why)\n"
            "3. Include a head-to-head metrics table with at least 8 metrics.\n"
            "4. For each metric, state which company wins and by how much.\n"
            "5. Use specific numbers from the facts — never generalize.\n\n"
        )
    else:
        comparison_instructions = ""

    depth_mode = normalize_depth(response_depth)
    try:
        resolved_mode = OutputMode(output_mode) if output_mode else OutputMode.CONVERSATIONAL_CHAT
    except ValueError:
        resolved_mode = OutputMode.CONVERSATIONAL_CHAT
    profile = _synthesis_profile(resolved_mode, depth_mode, objective)
    focused_output = resolved_mode.value in _FOCUSED_OUTPUT_MODES
    focus_instruction = ""
    if focused_output:
        base_instruction = (
            f"Latest operational focus: {output_mode}. Answer this focus directly first, "
            "using the existing conversation only to resolve the entity. Do not reissue a full company profile.\n"
            "Use a tight structure: ## Direct Answer, ## Key Evidence, ## Why It Matters, ## Limitations. "
        )

        if output_mode == "valuation_insights":
            base_instruction += (
                "This is a valuation-focused query. Prioritize and clearly present deterministic statistical revenue projections, "
                "+/-2 sigma corridors, implied growth rates, and model_used. "
                "Include DCF-related insights if available from specialist agents. "
                "Explicitly mention that no removed forecasting microservice was used.\n"
            )
        elif output_mode == "forensic_insights":
            base_instruction += (
                "This is a forensic accounting / anomaly detection query. "
                "Highlight anomalies flagged by statistical methods, along with confidence corridors and deviation magnitudes.\n"
            )
        elif output_mode == "news_brief":
            base_instruction += "For news briefs, list concrete dated headlines/developments first.\n"
        elif "price" in output_mode:
            base_instruction += "Lead with the price-window movement, high/low range, and data source before any business context.\n"

        focus_instruction = base_instruction + "\n"
    report_instruction = (
        "Produce a focused, direct answer to the objective above. Use 2-3 sections max. "
        "Include kpi/chart blocks only if real numeric data is in the source facts. "
        "Skip visuals entirely for conversational or opinion-type questions.\n\n"
        if focused_output
        else "Produce a balanced research response: 3-4 sections, dense prose, zero filler. "
        "Only emit kpi blocks if actual financial metrics are retrieved from source data (never invent them). "
        "Only emit 1 chart block if time-series data exists that meaningfully illustrates a trend. "
        "Skip charts and tables for conversational questions. "
        "For full research reports: use 6-8 sections with 1-2 charts only where time-series data exists.\n\n"
    )

    user_prompt = (
        f"**Research target:** {target}\n"
        f"**Objective:** {objective}\n\n"
        f"{focus_instruction}"
        f"{comparison_instructions}"
        f"{report_instruction}"
        "Requirements:\n"
        "- Use all available facts and source material provided below.\n"
        "- Never hallucinate numbers or invent figures — cite every claim with [SOURCE].\n"
        "- Use Markdown structure: ## section headings, tables for metrics, bullet points for lists.\n"
        "- For missing data: omit from kpi/chart/table blocks; write 'N/A' inline in prose only if the metric is directly asked about.\n"
        "- For follow-up answers, do not summarize the earlier memo; answer the user's new request directly.\n"
        "- Emit kpi blocks ONLY when actual financial metrics (price, PE, revenue, etc.) are present in the VERIFIED FACTS section.\n"
        "- Emit chart blocks ONLY when time-series numeric data (multiple data points across years/quarters) is present in VERIFIED FACTS.\n"
        "- For conversational questions or opinion queries: use prose only, no kpi/chart blocks.\n"
        "- For portfolio queries and comparison queries: ALWAYS include at least 1 chart + 1-3 kpi blocks whenever source data permits.\n\n"
        f"=== VERIFIED FACTS ===\n{facts}\n\n"
        f"=== SOURCE DOCUMENTS ===\n{digest}\n\n"
        f"{_conflict_block(conflicts)}"
    )

    chunks: list[str] = []
    model_to_use = synth_model or cfg.model
    messages = [{"role": "system", "content": system_prompt}]
    if chat_history:
        messages.extend(_compact_chat_history(chat_history, focused=focused_output, depth=depth_mode))
    messages.append({"role": "user", "content": user_prompt})

    _is_deep = depth_mode == ResponseDepth.DEEP or resolved_mode == OutputMode.DEEP_RESEARCH_REPORT
    _max_tokens = int(profile["max_tokens"])

    # ============================================================
    # DETAILED LLM CONTEXT LOGGING — what is actually sent to the model
    # ============================================================
    system_len = len(system_prompt)
    user_len = len(user_prompt)
    total_messages = len(messages)
    chat_hist_len = len(chat_history) if chat_history else 0

    logger.info("[LLM-CONTEXT] === FINAL SYNTHESIS PROMPT TO MODEL ===")
    logger.info("[LLM-CONTEXT] model=%s | max_tokens=%d | temperature=0.2 | is_deep=%s", model_to_use, _max_tokens, _is_deep)
    logger.info("[LLM-CONTEXT] system_prompt_len=%d | user_prompt_len=%d | total_messages=%d | chat_history_items=%d",
                system_len, user_len, total_messages, chat_hist_len)
    logger.info("[LLM-CONTEXT] target=%s | objective=%s | output_mode=%s", target, objective, output_mode)
    logger.info("[LLM-CONTEXT] facts_block_len=%d | digest_len=%d | conflicts=%d",
                len(facts), len(digest), len(conflicts))

    # Log a safe preview (first 1200 chars) of the actual user prompt being sent
    user_preview = user_prompt[:1200].replace("\n", " | ")
    logger.info("[LLM-CONTEXT] USER_PROMPT_PREVIEW: %s ... (truncated)", user_preview)

    # Log the beginning of the system prompt for verification
    sys_preview = system_prompt[:600].replace("\n", " | ")
    logger.info("[LLM-CONTEXT] SYSTEM_PROMPT_PREVIEW: %s ...", sys_preview)

    # Full raw prompts (can be very long — only at DEBUG level to avoid flooding)
    logger.debug("[LLM-CONTEXT] FULL_SYSTEM_PROMPT:\n%s", system_prompt)
    logger.debug("[LLM-CONTEXT] FULL_USER_PROMPT:\n%s", user_prompt)

    if force_non_stream:
        logger.info("[LLM-CALL] Forcing non-streaming OpenAI call (post-timeout retry) | model=%s | max_tokens=%d", model_to_use, _max_tokens)
        resp = await client.chat.completions.create(
            model=model_to_use,
            temperature=0.2,
            max_tokens=_max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        if getattr(resp, "usage", None):
            _record_usage(resp.usage)
        final = resp.choices[0].message.content or ""
        if isinstance(final, list):
            final = "".join(
                part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "")
                for part in final
            )
        final = str(final).strip()
        if final:
            logger.info("[LLM-RESPONSE] Synthesis completed via FORCED NON-STREAM (retry) | model=%s | output_len=%d chars", model_to_use, len(final))
            await _emit_token(on_token, final)
        return final

    # Normal path: try streaming first (with internal empty-response fallback to non-stream)
    logger.info("[LLM-CALL] Starting OpenAI streaming call | model=%s | session_id=%s", model_to_use, "n/a-in-this-scope")

    stream = await client.chat.completions.create(
        model=model_to_use,
        temperature=0.2,
        max_tokens=_max_tokens,
        stream=True,
        stream_options={"include_usage": True},
        messages=messages,
    )
    usage_data = None
    try:
        async for event in stream:
            if hasattr(event, "usage") and event.usage:
                usage_data = event.usage
            if not event.choices:
                continue
            delta = event.choices[0].delta
            text = getattr(delta, "content", None) or ""
            if isinstance(text, list):
                text = "".join(
                    part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "")
                    for part in text
                )
            if not text:
                continue
            chunks.append(text)
            await _emit_token(on_token, text)
        full = "".join(chunks).strip()
        if full:
            logger.info("[LLM-RESPONSE] Synthesis completed via streaming | model=%s | output_len=%d chars", model_to_use, len(full))
            if usage_data:
                _record_usage(usage_data)
            return full
        logger.warning("[LLM-FALLBACK] Streaming returned empty — falling back to non-streaming call | model=%s", model_to_use)
        logger.info("[LLM-CONTEXT] FALLBACK non-stream call | model=%s | user_prompt_len=%d", model_to_use, len(user_prompt))

        resp = await client.chat.completions.create(
            model=model_to_use,
            temperature=0.2,
            max_tokens=_max_tokens,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        if getattr(resp, "usage", None):
            _record_usage(resp.usage)
        final = resp.choices[0].message.content or ""
        if isinstance(final, list):
            final = "".join(
                part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "")
                for part in final
            )
        final = str(final).strip()
        if final:
            logger.info("[LLM-RESPONSE] Synthesis completed via NON-STREAM fallback | model=%s | output_len=%d chars", model_to_use, len(final))
            await _emit_token(on_token, final)
        return final
    finally:
        close = getattr(stream, "close", None)
        if close is not None:
            result = close()
            if asyncio.iscoroutine(result):
                await result


# ──────────────────────────────────────────────────────────────────────────
#  Structured fallback path — prose paragraphs, no asterisks
# ──────────────────────────────────────────────────────────────────────────


def _format_pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.2f}%"


def _cagr(points: list) -> float | None:
    """Compute CAGR across a list of series point-like objects (oldest first)."""
    if not points or len(points) < 2:
        return None
    first = points[0].value if hasattr(points[0], "value") else points[0].get("value")
    last = points[-1].value if hasattr(points[-1], "value") else points[-1].get("value")
    if not first or first <= 0 or not last or last <= 0:
        return None
    n = len(points) - 1
    try:
        return ((last / first) ** (1 / n) - 1) * 100.0
    except Exception:
        return None


def _history_paragraph(bundle: EnrichmentBundle) -> str | None:
    s = bundle.sec
    fx = bundle.fx
    y = bundle.yahoo
    if not s or not getattr(s, 'history', None):
        if not y:
            return None
        parts: list[str] = []
        if y.annual_revenue and len(y.annual_revenue) >= 2:
            first_val = _format_local_money(y.annual_revenue[0], y.currency, fx)
            last_val = _format_local_money(y.annual_revenue[-1], y.currency, fx)
            first_date = y.annual_revenue_dates[0] if y.annual_revenue_dates else "start"
            last_date = y.annual_revenue_dates[-1] if y.annual_revenue_dates else "latest"
            years = len(y.annual_revenue) - 1
            rev_cagr = _cagr([{"value": v} for v in y.annual_revenue])
            cagr_clause = f" — a {rev_cagr:+.1f}% compound annual growth rate" if rev_cagr is not None else ""
            parts.append(
                f"Annual revenue moved from {first_val} in {first_date} to {last_val} in {last_date} "
                f"over {years} years{cagr_clause}."
            )
        if y.annual_net_income and len(y.annual_net_income) >= 2:
            first_val = _format_local_money(y.annual_net_income[0], y.currency, fx)
            last_val = _format_local_money(y.annual_net_income[-1], y.currency, fx)
            first_date = y.annual_net_income_dates[0] if y.annual_net_income_dates else "start"
            last_date = y.annual_net_income_dates[-1] if y.annual_net_income_dates else "latest"
            ni_cagr = _cagr([{"value": v} for v in y.annual_net_income]) if y.annual_net_income[0] > 0 and y.annual_net_income[-1] > 0 else None
            cagr_clause = f", a {ni_cagr:+.1f}% CAGR" if ni_cagr is not None else ""
            parts.append(
                f"Net income moved from {first_val} in {first_date} to {last_val} in {last_date}{cagr_clause}."
            )
        if parts:
            return " ".join(parts)
        return None
    parts: list[str] = []
    rev = s.history.get("revenue")
    if rev and _get_attr_or_key(rev, "annual") and len(_get_attr_or_key(rev, "annual", [])) >= 2:
        annual = _get_attr_or_key(rev, "annual", [])
        first_p = annual[0]
        last_p = annual[-1]
        cagr = _cagr(annual)
        rev_unit = _get_attr_or_key(rev, "unit")
        first_val = _format_money(_get_attr_or_key(first_p, "value"), rev_unit, fx)
        last_val = _format_money(_get_attr_or_key(last_p, "value"), rev_unit, fx)
        years = len(rev.annual) - 1
        cagr_clause = f" — a {cagr:+.1f}% compound annual growth rate" if cagr is not None else ""
        parts.append(
            f"Annual revenue moved from {first_val} in FY{first_p.fy or first_p.end[:4]} "
            f"to {last_val} in FY{last_p.fy or last_p.end[:4]} over {years} years{cagr_clause}."
        )
    ni = s.history.get("net_income")
    if ni and ni.annual and len(ni.annual) >= 2:
        first_p = ni.annual[0]
        last_p = ni.annual[-1]
        cagr = _cagr(ni.annual)
        first_val = _format_money(first_p.value, ni.unit, fx)
        last_val = _format_money(last_p.value, ni.unit, fx)
        cagr_clause = f", a {cagr:+.1f}% CAGR" if cagr is not None else ""
        parts.append(
            f"Net income trended from {first_val} to {last_val} across the same window{cagr_clause}."
        )
    eps = s.history.get("eps_diluted")
    if eps and eps.annual and len(eps.annual) >= 2:
        first_p = eps.annual[0]
        last_p = eps.annual[-1]
        parts.append(
            f"Diluted EPS expanded from ${first_p.value:,.2f} to ${last_p.value:,.2f} on a fully-diluted basis."
        )
    if not parts:
        return None
    return " ".join(parts)


def _news_prose(bundle: EnrichmentBundle) -> str:
    if not bundle.news:
        return "No fresh news headlines were returned this session."
    top = bundle.news[:5]
    sources = {n.source for n in bundle.news if n.source}
    sentences = [
        f"Recent press coverage pulled {len(bundle.news)} headlines across "
        f"{len(sources)} outlets including {', '.join(sorted(list(sources))[:4])}."
    ]
    for i, n in enumerate(top, 1):
        when = n.published.split(",", 1)[-1].strip() if n.published else ""
        sentences.append(f"{n.source}: {n.title} ({when}).")
    return " ".join(sentences)


def _executive_summary_prose(target: str, bundle: EnrichmentBundle, conflicts: list[ConflictReport]) -> str:
    s = bundle.sec
    y = bundle.yahoo
    w = bundle.wikipedia
    fx = bundle.fx
    label = s.name if s else (y.name if y and y.name else target)

    sentences: list[str] = []
    if s and y and y.price is not None:
        listing = ", ".join(s.exchanges) if s.exchanges else "a US public listing"
        price_dual = _format_price(y.price, y.currency, fx)
        sentences.append(
            f"{label} (ticker {s.ticker}, {listing}) is trading at {price_dual}, "
            f"{_format_pct(y.change_pct)} versus prior close."
        )
    elif s:
        sentences.append(
            f"{label} is an exchange-listed issuer (identifier {s.cik}) with market data sourced from Indian market disclosures."
        )
    elif y and y.price is not None:
        sentences.append(f"{label} is trading at {_format_price(y.price, y.currency, fx)}.")
    else:
        sentences.append(f"This memo covers {label}.")

    if s and "revenue" in s.metrics:
        rev = s.metrics["revenue"]
        rev_money = _format_money(rev.value, rev.unit, fx)
        ni = s.metrics.get("net_income")
        ni_clause = ""
        if ni:
            ni_clause = f" and net income of {_format_money(ni.value, ni.unit, fx)}"
        sentences.append(
            f"The most recent {rev.form} (period ending {rev.end}) shows revenue of "
            f"{rev_money}{ni_clause}."
        )
    elif y and y.financial_metrics.get("total_revenue") is not None:
        revenue = _format_local_money(y.financial_metrics["total_revenue"], y.currency, fx)
        ni_clause = ""
        if y.financial_metrics.get("profit_margins") is not None:
            ni_clause = f" with a reported profit margin of {y.financial_metrics['profit_margins'] * 100:.1f}%"
        sentences.append(f"Yahoo Finance reports total revenue of {revenue}{ni_clause}.")

    if w and w.description:
        desc = w.description.strip().rstrip(".")
        article = "an" if desc[:1].lower() in "aeiou" else "a"
        sentences.append(f"It is described publicly as {article} {desc}.")

    if conflicts:
        sentences.append(
            f"Cross-source scanning flagged {len(conflicts)} numeric inconsistency"
            f"{'ies' if len(conflicts) != 1 else ''} that the reader should verify before relying on the figures."
        )

    return " ".join(sentences)


def _company_overview_prose(bundle: EnrichmentBundle, target: str) -> str:
    s = bundle.sec
    w = bundle.wikipedia
    f = bundle.filing
    y = bundle.yahoo
    paras: list[str] = []

    if f and f.business:
        cut = f.business[:1100]
        last = cut.rfind(". ")
        if last > 600:
            cut = cut[: last + 1]
        paras.append(
            f"From the company's own {f.form} filed {f.filed_date} (Item 1, Business): {cut}"
        )

    if w and w.extract:
        extract = w.extract.replace("\n", " ").strip()
        cut = extract[:900]
        last = cut.rfind(". ")
        if last > 400:
            cut = cut[: last + 1]
        paras.append(cut)
    elif y and y.business_summary:
        cut = y.business_summary.replace("\n", " ").strip()[:900]
        last = cut.rfind(". ")
        if last > 400:
            cut = cut[: last + 1]
        if cut:
            name = y.name or y.ticker
            exchange = f" and trades on {y.exchange}" if y.exchange else ""
            paras.append(f"{name} is covered by Yahoo Finance{exchange}. {cut}")
    elif s:
        sentences = [f"{s.name} ({s.ticker}) is listed in Indian market datasets under identifier {s.cik}."]
        if s.sic_description:
            sentences.append(f"It is classified under {s.sic_description}.")
        if s.exchanges:
            sentences.append(f"Shares trade on {', '.join(s.exchanges)}.")
        paras.append(" ".join(sentences))
    elif y:
        pieces = [f"{y.name or target} is tracked on Yahoo Finance under {y.ticker}."]
        if y.exchange:
            pieces.append(f"The shares trade on {y.exchange}.")
        paras.append(" ".join(pieces))

    if not paras:
        paras.append(f"No authoritative profile was resolved for {target}.")

    return "\n\n".join(paras)


def _financial_profile_prose(bundle: EnrichmentBundle) -> str:
    s = bundle.sec
    y = bundle.yahoo
    fx = bundle.fx
    if not (s or y):
        return "No API-backed financials were resolved for this target. Numeric inference would be premature."

    paras: list[str] = []
    if s:
        latest = None
        for key in ("revenue", "operating_income", "net_income"):
            m = s.metrics.get(key)
            if m:
                latest = (m.form, m.end)
                break
        if latest:
            paras.append(
                f"The most recent exchange-filed financials come from a {latest[0]} for the period ending {latest[1]}. "
                "The headline numbers are as follows."
            )

        narrative_lines: list[str] = []
        def _line(label: str, key: str) -> None:
            m = s.metrics.get(key)
            if m:
                narrative_lines.append(f"{label}: {_format_money(m.value, m.unit, fx)}.")

        _line("Revenue", "revenue")
        _line("Operating income", "operating_income")
        _line("Net income", "net_income")
        _line("Diluted EPS", "eps_diluted")
        _line("R&D expense", "rd_expense")
        _line("Total assets", "total_assets")
        _line("Total liabilities", "total_liabilities")
        _line("Stockholders' equity", "stockholders_equity")
        _line("Cash & equivalents", "cash_and_equivalents")
        _line("Long-term debt", "long_term_debt")
        # Shares outstanding is unitless
        m = s.metrics.get("shares_outstanding")
        if m:
            narrative_lines.append(f"Shares outstanding: {m.display_value()}.")
        if narrative_lines:
            paras.append(" ".join(narrative_lines))

    if y and y.price is not None:
        price_dual = _format_price(y.price, y.currency, fx)
        prev_dual = _format_price(y.previous_close, y.currency, fx) if y.previous_close else "n/a"
        range_low = f"{y.fifty_two_week_low:.2f}" if y.fifty_two_week_low is not None else "n/a"
        range_high = f"{y.fifty_two_week_high:.2f}" if y.fifty_two_week_high is not None else "n/a"
        currency_label = y.currency or "INR"
        line = (
            f"At session pull, the stock prints at {price_dual} versus a prior close of {prev_dual}, "
            f"a session move of {_format_pct(y.change_pct)}. "
            f"The 52-week range spans {range_low} to {range_high} ({currency_label})."
        )
        if y.market_cap:
            line += f" Market capitalisation sits near {_format_local_money(y.market_cap, y.currency, fx)}."
        paras.append(line)

    if y and y.financial_metrics:
        metric_sentences: list[str] = []
        for label, key in (
            ("Total revenue", "total_revenue"),
            ("EBITDA", "ebitda"),
            ("Free cash flow", "free_cashflow"),
            ("Cash", "total_cash"),
            ("Debt", "total_debt"),
        ):
            value = y.financial_metrics.get(key)
            if value is not None:
                metric_sentences.append(f"{label} is {_format_local_money(value, y.currency, fx)}.")
        ratio_bits: list[str] = []
        for label, key in (
            ("gross margin", "gross_margins"),
            ("operating margin", "operating_margins"),
            ("profit margin", "profit_margins"),
            ("ROE", "return_on_equity"),
            ("ROA", "return_on_assets"),
            ("revenue growth", "revenue_growth"),
            ("earnings growth", "earnings_growth"),
            ("dividend yield", "dividend_yield"),
        ):
            value = y.financial_metrics.get(key)
            if value is not None:
                ratio_bits.append(f"{label} {value * 100:.1f}%")
        for label, key in (
            ("trailing P/E", "trailing_pe"),
            ("forward P/E", "forward_pe"),
            ("price/book", "price_to_book"),
            ("debt/equity", "debt_to_equity"),
            ("current ratio", "current_ratio"),
            ("quick ratio", "quick_ratio"),
        ):
            value = y.financial_metrics.get(key)
            if value is not None:
                ratio_bits.append(f"{label} {value:.2f}x")
        if metric_sentences or ratio_bits:
            paragraph = "Yahoo Finance fundamentals complement the price snapshot. "
            paragraph += " ".join(metric_sentences)
            if ratio_bits:
                paragraph += " Key ratios include " + ", ".join(ratio_bits) + "."
            paras.append(paragraph)

    return "\n\n".join(paras)


def _market_position_prose(docs: list[ScrapedDoc]) -> str:
    snippets: list[str] = []
    for d in docs:
        ex = (d.excerpt or "").lower()
        if "competitor" in ex or "market share" in ex or "rival" in ex:
            snippets.append(d.excerpt[:340].strip())
            if len(snippets) >= 3:
                break
    if not snippets:
        return (
            "Competitive context did not surface explicitly in the gathered sources. "
            "A targeted follow-up on industry peers and segment share is recommended "
            "before sizing any thesis."
        )
    joined = " ".join(snippets)
    return f"Pulled from public commentary on the company: {joined}"


def _market_narrative_prose(bundle: EnrichmentBundle) -> str:
    news = bundle.news or []
    if not news:
        return (
            "Recent market narrative was not available from the domestic news feed in this session. "
            "Use the web-source citations above for direct NSE/BSE filings and financial-media context."
        )
    sources = ", ".join(sorted({n.source for n in news if n.source})[:4])
    headlines = "; ".join(n.title for n in news[:4] if n.title)
    return (
        f"Domestic financial media coverage came from {sources or 'the news feed'}. "
        f"The latest captured headlines were: {headlines}."
    )


def _risks_prose(bundle: EnrichmentBundle, docs: list[ScrapedDoc], conflicts: list[ConflictReport]) -> str:
    paras: list[str] = []
    if bundle.filing and bundle.filing.risk_factors:
        excerpt = bundle.filing.risk_factors.strip()
        cut = excerpt[:1500]
        last = cut.rfind(". ")
        if last > 800:
            cut = cut[: last + 1]
        paras.append(
            f"Taken directly from {bundle.filing.form} filed {bundle.filing.filed_date} (Item 1A): {cut}"
            + (" …" if len(excerpt) > len(cut) else "")
        )
    else:
        snippets: list[str] = []
        for d in docs:
            ex = (d.excerpt or "").lower()
            if "risk" in ex or "headwind" in ex or "regulatory" in ex:
                snippets.append(d.excerpt[:280].strip())
                if len(snippets) >= 3:
                    break
        if snippets:
            paras.append("Risk language pulled from public sources: " + " ".join(snippets))
        else:
            paras.append("Specific risk-factor language was not captured this run. Treat downside cases as under-described.")
    if conflicts:
        bullets = []
        for c in conflicts[:3]:
            bullets.append(c.note)
        paras.append("In addition, the cross-source scanner flagged the following numeric mismatches: " + "; ".join(bullets) + ".")
    return "\n\n".join(paras)


def _thesis_prose(bundle: EnrichmentBundle) -> str:
    s = bundle.sec
    y = bundle.yahoo
    fx = bundle.fx
    bull: list[str] = []
    bear: list[str] = []

    # Structured-data thesis points
    if s and "revenue" in s.metrics:
        rev = s.metrics["revenue"]
        bull.append(
            f"Top-line scale of {_format_money(rev.value, rev.unit, fx)} ({rev.form}) gives the company "
            "real operating leverage on its fixed cost base."
        )
    if s and "stockholders_equity" in s.metrics and "long_term_debt" in s.metrics:
        eq = s.metrics["stockholders_equity"].value
        debt = s.metrics["long_term_debt"].value
        if eq > 0:
            ratio = debt / eq
            if ratio < 1.0:
                bull.append(
                    f"Debt to equity sits at {ratio:.2f}x \u2014 a conservative capital structure that protects "
                    "the bull case across most macro paths."
                )
            else:
                bear.append(
                    f"Debt to equity is elevated at {ratio:.2f}x, which narrows financial flexibility if "
                    "earnings compress."
                )

    # Yahoo-based thesis points when local structured data is thin
    if y and y.financial_metrics and not s:
        ym = y.financial_metrics
        # Revenue scale
        if ym.get("total_revenue"):
            rev_str = _format_local_money(ym["total_revenue"], y.currency, fx)
            bull.append(f"TTM revenue of {rev_str} reflects operating scale that supports durable competitive positioning.")
        # Profit margins
        if ym.get("profit_margins"):
            pm = ym["profit_margins"] * 100
            if pm > 15:
                bull.append(f"Net profit margin of {pm:.1f}% signals pricing power and operational efficiency.")
            elif pm < 5:
                bear.append(f"Thin net profit margin of {pm:.1f}% leaves limited buffer against cost inflation or demand slowdowns.")
        # Revenue growth
        if ym.get("revenue_growth"):
            rg = ym["revenue_growth"] * 100
            if rg > 10:
                bull.append(f"Revenue growth of {rg:.1f}% YoY positions the company ahead of the broader market.")
            elif rg < 0:
                bear.append(f"Revenue is contracting at {rg:.1f}% YoY \u2014 a structural concern if the trend persists.")
        # ROE
        if ym.get("return_on_equity"):
            roe = ym["return_on_equity"] * 100
            if roe > 15:
                bull.append(f"Return on equity of {roe:.1f}% demonstrates efficient capital deployment.")
            elif roe < 8:
                bear.append(f"ROE of {roe:.1f}% is below the cost of equity for most Indian blue-chips.")
        # Debt to equity
        if ym.get("debt_to_equity"):
            de = ym["debt_to_equity"] / 100  # Yahoo returns as percentage
            if de < 0.5:
                bull.append(f"Debt/equity of {de:.2f}x indicates a clean balance sheet.")
            elif de > 1.5:
                bear.append(f"Debt/equity is stretched at {de:.2f}x \u2014 a concern if interest rates rise.")
        # Valuation
        if ym.get("trailing_pe"):
            pe = ym["trailing_pe"]
            if pe > 50:
                bear.append(f"Trailing P/E of {pe:.1f}x prices in aggressive growth expectations that may not materialise.")
            elif pe < 15:
                bull.append(f"Trailing P/E of {pe:.1f}x implies the market is underweighting the company\u2019s earnings power.")

    # Price-based thesis (works for all)
    if y and y.price and y.fifty_two_week_high:
        proximity = y.price / y.fifty_two_week_high
        if proximity > 0.9:
            bull.append(
                f"The stock is trading at {proximity*100:.0f}% of its 52-week high, a momentum signal "
                "that often persists in the short run."
            )
        elif proximity < 0.7:
            bear.append(
                f"The print sits at {proximity*100:.0f}% of the 52-week high, suggesting sentiment is "
                "still working through a derate."
            )

    if not bull:
        bull.append(
            "Insufficient data was available to construct a quantitative bull case this session. "
            "A deeper dive into quarterly earnings and management commentary is recommended."
        )
    if not bear:
        bear.append(
            "No clear bear signals emerged from the available data. Key risks may be hidden in "
            "sector-level headwinds, regulatory shifts, or promoter-related governance issues."
        )

    return (
        "**Bull case.** " + " ".join(bull) + "\n\n"
        "**Bear case.** " + " ".join(bear)
    )


def _conflicts_prose(conflicts: list[ConflictReport]) -> str:
    if not conflicts:
        return "No cross-source numeric conflicts were detected for this run."
    lines: list[str] = []
    for c in conflicts:
        sources = ", ".join(f"{o.domain} ({o.raw})" for o in c.observations)
        lines.append(f"{c.note}. Disagreeing sources: {sources}.")
    return "\n\n".join(lines)


def _build_specialist_findings_block(findings: list | None) -> str:
    """Format all specialist-agent findings into a compact prose block for the LLM.

    This ensures every agent's output (valuation, risk, forensic, etc.) reaches the
    synthesis prompt, regardless of which agent actually ran for the query.
    """
    if not findings:
        return ""
    lines: list[str] = []
    # Group by agent for readability
    by_agent: dict[str, list] = {}
    for f in findings:
        agent_name = getattr(f, "agent", "unknown")
        by_agent.setdefault(agent_name, []).append(f)

    for agent_name, agent_findings in by_agent.items():
        lines.append(f"--- Agent: {agent_name} ({len(agent_findings)} finding(s)) ---")
        for f in agent_findings:
            headline = getattr(f, "headline", "")
            detail = getattr(f, "detail", "")
            confidence = getattr(f, "confidence", "UNKNOWN")
            metrics = getattr(f, "metrics", None)
            evidence = getattr(f, "evidence", None)
            if headline:
                lines.append(f"  Headline: {headline}")
            if detail:
                # Indent detail for readability; keep under ~300 chars per line
                detail_snippet = detail.replace("\n", " ")
                lines.append(f"  Detail: {detail_snippet}")
            lines.append(f"  Confidence: {confidence}")
            if metrics and isinstance(metrics, dict):
                metric_items = [f"{k}={v}" for k, v in metrics.items() if v is not None]
                if metric_items:
                    lines.append(f"  Metrics: {' | '.join(metric_items)}")
            if evidence and isinstance(evidence, list) and evidence:
                lines.append(f"  Evidence: {', '.join(str(e) for e in evidence[:3])}")
            lines.append("")
    return "\n".join(lines)


def _financial_ratios_prose(bundle: EnrichmentBundle) -> str:
    """Build a clean financial ratios summary from Yahoo metrics."""
    y = bundle.yahoo
    fx = bundle.fx
    if not y or not y.financial_metrics:
        return (
            "Financial ratio data could not be retrieved for this company during this session. "
            "This is common for recently listed or thinly-covered Indian equities. "
            "Check screener.in or moneycontrol.com for up-to-date ratio snapshots."
        )
    ym = y.financial_metrics
    rows: list[str] = []

    # Valuation ratios
    val_bits: list[str] = []
    for label, key, fmt in [
        ("Trailing P/E", "trailing_pe", ".1f"),
        ("Forward P/E", "forward_pe", ".1f"),
        ("PEG ratio", "peg_ratio", ".2f"),
        ("Price/Book", "price_to_book", ".2f"),
        ("EV/EBITDA", "enterprise_to_ebitda", ".1f"),
        ("EV/Revenue", "enterprise_to_revenue", ".2f"),
    ]:
        v = ym.get(key)
        if v is not None:
            val_bits.append(f"{label}: {v:{fmt}}x")
    if val_bits:
        rows.append("**Valuation:** " + " · ".join(val_bits))

    # Profitability ratios
    prof_bits: list[str] = []
    for label, key in [
        ("Gross margin", "gross_margins"),
        ("Operating margin", "operating_margins"),
        ("Net margin", "profit_margins"),
        ("ROE", "return_on_equity"),
        ("ROA", "return_on_assets"),
    ]:
        v = ym.get(key)
        if v is not None:
            prof_bits.append(f"{label}: {v*100:.1f}%")
    if prof_bits:
        rows.append("**Profitability:** " + " · ".join(prof_bits))

    # Growth metrics
    growth_bits: list[str] = []
    for label, key in [
        ("Revenue growth", "revenue_growth"),
        ("Earnings growth", "earnings_growth"),
    ]:
        v = ym.get(key)
        if v is not None:
            growth_bits.append(f"{label}: {v*100:.1f}%")
    if growth_bits:
        rows.append("**Growth:** " + " · ".join(growth_bits))

    # Leverage & liquidity
    lev_bits: list[str] = []
    for label, key, fmt in [
        ("Debt/Equity", "debt_to_equity", ".0f"),
        ("Current ratio", "current_ratio", ".2f"),
        ("Quick ratio", "quick_ratio", ".2f"),
    ]:
        v = ym.get(key)
        if v is not None:
            suffix = "%" if key == "debt_to_equity" else "x"
            lev_bits.append(f"{label}: {v:{fmt}}{suffix}")
    if lev_bits:
        rows.append("**Leverage & liquidity:** " + " · ".join(lev_bits))

    # Per-share & yield
    ps_bits: list[str] = []
    if ym.get("trailing_eps"):
        ps_bits.append(f"EPS (TTM): {_format_local_money(ym['trailing_eps'], y.currency, fx)}")
    if ym.get("dividend_yield"):
        ps_bits.append(f"Div yield: {ym['dividend_yield']*100:.2f}%")
    if ym.get("book_value"):
        ps_bits.append(f"Book value: {_format_local_money(ym['book_value'], y.currency, fx)}")
    if ps_bits:
        rows.append("**Per-share:** " + " · ".join(ps_bits))

    if not rows:
        return (
            "Financial ratio data was not available through our data pipeline for this company. "
            "For Indian equities, try screener.in, trendlyne.com, or tickertape.in for detailed ratio analysis."
        )
    return "\n\n".join(rows)


def _structured_memo(
    target: str,
    citations: list[Citation],
    docs: list[ScrapedDoc],
    conflicts: list[ConflictReport],
    bundle: EnrichmentBundle,
) -> str:
    blocked_count = sum(1 for d in docs if d.blocked_reason)
    primary_count = sum(1 for d in docs if d.tier <= 2 and not d.blocked_reason)
    yahoo_financial_depth = bool(
        bundle.yahoo and (bundle.yahoo.financial_metrics or bundle.yahoo.annual_revenue or bundle.yahoo.annual_net_income)
    )

    overall_conf = "MEDIUM"
    if bundle.sec and primary_count >= 2:
        overall_conf = "HIGH"
    elif yahoo_financial_depth and primary_count >= 1:
        overall_conf = "MEDIUM"
    elif blocked_count >= len(docs) // 2 and not bundle.sec and not yahoo_financial_depth:
        overall_conf = "LOW"

    sections: list[MemoSection] = [
        MemoSection(title="Executive summary", body=_executive_summary_prose(target, bundle, conflicts), confidence=overall_conf),
        MemoSection(
            title="Company overview",
            body=_company_overview_prose(bundle, target),
            confidence="HIGH" if bundle.wikipedia or bundle.sec or bundle.filing else ("MEDIUM" if (bundle.yahoo and bundle.yahoo.business_summary) else "LOW"),
        ),
        MemoSection(
            title="Financial profile",
            body=_financial_profile_prose(bundle),
            confidence="HIGH" if bundle.sec else ("MEDIUM" if yahoo_financial_depth else "LOW"),
        ),
    ]

    if bundle.filing and bundle.filing.mdna:
        mdna_cut = bundle.filing.mdna[:1500]
        last = mdna_cut.rfind(". ")
        if last > 800:
            mdna_cut = mdna_cut[: last + 1]
        sections.append(
            MemoSection(
                title="Management discussion & outlook",
                body=(
                    f"From {bundle.filing.form} filed {bundle.filing.filed_date} (Item 7): "
                    + mdna_cut
                    + (" …" if len(bundle.filing.mdna) > len(mdna_cut) else "")
                ),
                confidence="HIGH",
            )
        )

    hist_para = _history_paragraph(bundle)
    if hist_para:
        sections.append(
            MemoSection(title="Multi-year financial trajectory", body=hist_para, confidence="HIGH")
        )

    # Financial ratios section (from Yahoo/yfinance metrics)
    sections.append(
        MemoSection(
            title="Financial ratios",
            body=_financial_ratios_prose(bundle),
            confidence="HIGH" if (bundle.yahoo and bundle.yahoo.financial_metrics) else "LOW",
        )
    )

    sections.extend(
        [
            MemoSection(title="Market and competitive position", body=_market_position_prose(docs), confidence="MEDIUM"),
            MemoSection(title="Recent news coverage", body=_news_prose(bundle), confidence="MEDIUM" if bundle.news else "LOW"),
            MemoSection(title="Domestic market narrative", body=_market_narrative_prose(bundle), confidence="MEDIUM" if bundle.news else "LOW"),
            MemoSection(
                title="Key risks",
                body=_risks_prose(bundle, docs, conflicts),
                confidence="HIGH" if (bundle.filing and bundle.filing.risk_factors) else "MEDIUM",
            ),
            MemoSection(title="Bull and bear thesis", body=_thesis_prose(bundle), confidence="DERIVED"),
            MemoSection(title="Cross-source conflicts", body=_conflicts_prose(conflicts), confidence="DERIVED"),
        ]
    )

    methodology_bits: list[str] = []
    methodology_bits.append(
        f"This memo synthesised {len(docs)} web sources via layered DuckDuckGo queries, "
        "iterative gap-driven follow-ups, and domestic financial-media enrichment."
    )
    if blocked_count:
        methodology_bits.append(
            f"{blocked_count} sources were blocked by robots.txt and recorded as click-through citations only."
        )
    if bundle.sec:
        methodology_bits.append(
            f"Structured market data supplied {len(bundle.sec.metrics)} authoritative metrics (identifier {bundle.sec.cik})."
        )
    if bundle.filing:
        methodology_bits.append(
            f"The actual {bundle.filing.form} was pulled and parsed for Item 1A risk factors and Item 7 MD&A."
        )
    if bundle.yahoo:
        methodology_bits.append(
            "Yahoo Finance supplied live quote data, valuation ratios, and the fallback fundamentals/history layer for non-US companies."
        )
    if bundle.fx:
        methodology_bits.append(
            f"USD figures are converted at USD/INR = {bundle.fx.rate:.4f} (source: {bundle.fx.source})."
        )
    sections.append(
        MemoSection(
            title="Data quality and methodology",
            body=" ".join(methodology_bits),
            confidence="HIGH",
        )
    )

    # Scrub each section body so the final memo reads cleanly.
    for sec in sections:
        sec.body = _scrub_prose(sec.body)
    citation_rows = [
        f"| [{i+1}] {c.title} | {c.url} | {c.date_accessed} | {c.kind} |" for i, c in enumerate(citations)
    ]
    return format_memo(
        target,
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        depth="standard",
        overall_confidence=overall_conf,
        duration="<1 min",
        source_count=len(citations),
        sections=sections,
        data_quality_rows=[],
        citation_rows=citation_rows,
    )


async def synthesize_memo(
    target: str,
    objective: str,
    docs: list[ScrapedDoc],
    checkpoint: Checkpoint,
    *,
    timeout_s: float | None = None,
    conflicts: list[ConflictReport] | None = None,
    on_token: TokenSink = None,
    enrichment: EnrichmentBundle | None = None,
    synth_model: str | None = None,
    output_mode: str | None = None,
    response_depth: str | None = None,
    entity=None,
    specialist_findings: list | None = None,
    quality_report=None,
    session_id: str | None = None,
    chat_history: list[dict[str, str]] | None = None,
    peer_targets: list[str] | None = None,
    user_email: str | None = None,
    portfolio_context: dict | None = None,
) -> SynthesisResult:
    conflicts = conflicts or []
    bundle = enrichment or EnrichmentBundle()
    depth = normalize_depth(response_depth)
    mode = classify_output_mode(
        query=objective,
        target=target,
        entity=entity,
        depth=depth,
        explicit_mode=output_mode,
    )

    # ── Force comparison mode if peer_targets provided ──
    if peer_targets and mode != OutputMode.COMPANY_COMPARISON:
        mode = OutputMode.COMPANY_COMPARISON

    # ── Dynamic synthesis timeout (deep research reports need more time) ──
    profile = _synthesis_profile(mode, depth, objective)
    digest, used = _build_source_digest(docs, budget_chars=int(profile["digest_budget_chars"]))
    if timeout_s is None:
        timeout_s = float(profile["timeout_s"])
    logger.info(
        "[SYNTH] effective timeout_s=%.0fs | depth=%s | mode=%s | max_tokens=%d | digest_budget=%d",
        timeout_s,
        depth.value,
        mode.value,
        int(profile["max_tokens"]),
        int(profile["digest_budget_chars"]),
    )

    # ── Fetch RICH peer enrichment in parallel (yahoo + india + wiki + news) ──
    peer_bundles = await _load_peer_bundles(peer_targets or [], objective, target, entity, mode)

    # Legacy: peer_quotes is now derived from peer_bundles for backward compat
    peer_quotes: dict[str, YahooQuote] = {
        name: pb["yahoo"] for name, pb in peer_bundles.items() if pb.get("yahoo")
    }
    # Fallback: if no peer_targets but comparison mode, use the old entity-extraction path
    if not peer_quotes and mode == OutputMode.COMPANY_COMPARISON:
        peer_quotes = await _load_peer_quotes(objective, target, entity, bundle, mode)
    artifact = build_answer_artifact(
        target=target,
        objective=objective,
        mode=mode,
        depth=depth,
        bundle=bundle,
        docs=docs,
        checkpoint=checkpoint,
        conflicts=conflicts,
        entity=entity,
        specialist_findings=specialist_findings or [],
        peer_quotes=peer_quotes,
        quality_report=quality_report,
    )
    
    # Build visual data payload but DEFER emit until after first memo token.
    # This ensures the text answer starts streaming BEFORE charts/cards appear,
    # which fixes the perception of "stats first, text minutes later".
    _visual_payload: dict | None = None
    if session_id:
        _visual_payload = dict(
            metric_cards=[
                {
                    "label": card.label,
                    "value": card.value,
                    "change": card.change,
                    "change_type": card.change_type,
                    "icon": card.icon,
                    "sparkline_svg": card.sparkline_svg,
                    "is_partial": card.is_partial,
                }
                for card in artifact.metric_cards
            ] if artifact.metric_cards else [],
            charts=[
                {
                    "id": chart.id,
                    "title": chart.title,
                    "subtitle": chart.subtitle,
                    "chart_type": chart.chart_type,
                    "labels": chart.labels or [],
                    "series": [
                        {
                            "name": s.name,
                            "color": s.color,
                            "data": [{"label": dp.label, "value": dp.value} for dp in s.data] if s.data else [],
                        }
                        for s in chart.series
                    ] if chart.series else [],
                    "is_partial": chart.is_partial,
                }
                for chart in artifact.charts
            ] if artifact.charts else [],
            comparison_results=[
                {
                    "metric": r.metric,
                    "primary_value": r.primary_value,
                    "secondary_value": r.secondary_value,
                    "winner": r.winner,
                    "delta": r.delta,
                    "primary_entity": r.primary_entity,
                    "secondary_entity": r.secondary_entity,
                }
                for r in artifact.comparison_results
            ] if artifact.comparison_results else None,
            visual_sections=[
                {
                    "type": vs.section_type,
                    "title": vs.title,
                    "columns": vs.columns,
                    "order": vs.order,
                    "is_partial": vs.is_partial,
                }
                for vs in artifact.visual_sections
            ] if artifact.visual_sections else [],
        )

    # Wrap on_token so visual_data_ready emits AFTER the first text chunk arrives.
    _visual_emitted = {"done": False}
    _orig_on_token = on_token

    async def _emit_visuals_once():
        if _visual_payload and not _visual_emitted["done"] and session_id:
            _visual_emitted["done"] = True
            try:
                from finagent.events import BUS
                BUS.emit(session_id, "visual_data_ready", **_visual_payload)
            except Exception:
                pass

    if _visual_payload and session_id:
        if _orig_on_token is None:
            # No streaming sink — emit visuals immediately after the call
            on_token = None
        else:
            if asyncio.iscoroutinefunction(_orig_on_token):
                async def _wrapped_async_sink(chunk: str):
                    await _orig_on_token(chunk)
                    if not _visual_emitted["done"]:
                        await _emit_visuals_once()
                on_token = _wrapped_async_sink
            else:
                def _wrapped_sync_sink(chunk: str):
                    _orig_on_token(chunk)
                    if not _visual_emitted["done"]:
                        # Sync sinks: fire-and-forget the emit
                        try:
                            from finagent.events import BUS
                            BUS.emit(session_id, "visual_data_ready", **_visual_payload)
                            _visual_emitted["done"] = True
                        except Exception:
                            pass
                on_token = _wrapped_sync_sink

    facts = _build_facts_block(bundle)
    if portfolio_context:
        facts += "\n\n=== LIVE PORTFOLIO MIRROR STATUS ===\n"
        facts += f"Total Portfolio Value: INR {portfolio_context.get('total_market_value', 0):,.2f}\n"
        facts += f"Total Unrealized P&L: INR {portfolio_context.get('unrealized_pnl', 0):,.2f} ({portfolio_context.get('unrealized_pnl_pct', 0) * 100:.2f}%)\n"
        facts += f"Day Change: INR {portfolio_context.get('day_change_total', 0):,.2f} ({portfolio_context.get('day_change_pct', 0) * 100:.2f}%)\n"
        risk = portfolio_context.get("risk") or {}
        facts += f"Concentration (HHI): {risk.get('hhi', 0):.4f}\n"
        facts += f"Beta vs NIFTY50: {risk.get('beta_vs_nifty', 0):.2f}\n"
        facts += f"Annualized Volatility: {risk.get('annualized_volatility_pct', 0):.2f}%\n"
        facts += f"Max Drawdown: {risk.get('max_drawdown_pct', 0):.2f}%\n"
        history = portfolio_context.get("history") or {}
        port_hist = (history.get("portfolio") or {}).get("prices") or []
        bench_hist = (history.get("benchmark") or {}).get("prices") or []
        if port_hist and bench_hist:
            facts += "\nPortfolio vs Benchmark NAV (indexed to 100):\n"
            # Sample 6 points: today, -1m, -3m, -6m, -9m, -1y
            n = len(port_hist)
            idxs = [n - 1, max(0, n - 22), max(0, n - 66), max(0, n - 132), max(0, n - 198), 0]
            for i in idxs:
                facts += f"  Day {i+1}: Portfolio {port_hist[i]:.2f} | Benchmark {bench_hist[i]:.2f}\n"
        positions = portfolio_context.get("positions") or []
        if positions:
            facts += "Holdings:\n"
            for p in positions:
                sym = p.get('symbol') or p.get('name') or '-'
                val = p.get('market_value') or 0
                weight = p.get('weight') or 0
                pnl = p.get('unrealized_pnl_pct') or 0
                facts += f"- {sym}: Market Value = INR {val:,.2f}, Weight = {weight * 100:.2f}%, Unrealized P&L = {pnl * 100:.2f}%\n"
    # ── Append specialist findings so the LLM sees agent outputs (valuation, risk, etc.) ──
    specialist_block = _build_specialist_findings_block(specialist_findings)
    if specialist_block:
        facts += "\n\n=== SPECIALIST AGENT FINDINGS ===\n" + specialist_block
    # ── Append RICH peer data to facts block for comparison queries ──
    # Prefer peer_bundles (full enrichment) over peer_quotes (yahoo-only)
    if peer_bundles:
        facts += "\n" + _build_peer_facts_block(peer_bundles)
    elif peer_quotes:
        facts += "\n" + _build_peer_quotes_only_block(peer_quotes)
    if resolve_openai_config() is not None:
        memo: str | None = None

        # Attempt 1: prefer streaming for best UX
        try:
            memo = await asyncio.wait_for(
                _openai_memo(
                    target,
                    objective,
                    digest,
                    facts,
                    conflicts,
                    on_token=on_token,
                    synth_model=synth_model,
                    chat_history=chat_history,
                    output_mode=mode.value,
                    response_depth=depth.value,
                    user_email=user_email,
                    session_id=session_id,
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "OpenAI synthesis timed out after %.0fs; retrying once with non-streaming call",
                timeout_s,
            )
            # Attempt 2: non-streaming retry (often completes faster without SSE overhead)
            try:
                memo = await asyncio.wait_for(
                    _openai_memo(
                        target,
                        objective,
                        digest,
                        facts,
                        conflicts,
                        on_token=on_token,
                        synth_model=synth_model,
                        chat_history=chat_history,
                        output_mode=mode.value,
                        response_depth=depth.value,
                        force_non_stream=True,
                        user_email=user_email,
                        session_id=session_id,
                    ),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "OpenAI synthesis timed out again after %.0fs (non-stream retry); falling back to structured prose builder",
                    timeout_s,
                )
            except Exception as exc:
                logger.warning("OpenAI synthesis retry failed (%s); using structured prose builder", exc)
        except Exception as exc:
            logger.warning("OpenAI synthesis failed (%s); using structured prose builder", exc)

        if memo:
            memo = _ensure_balanced_memo(memo, artifact)
            rich = render_rich_json(artifact)
            # Try teammate's new rich_builder for richer structured output
            # (NOW passing real bundle + specialist_findings so it can build
            # runtime visuals instead of empty placeholders)
            try:
                new_rich = teammate_rich_builder.build_from_native(
                    objective, bundle, docs, specialist_findings, memo
                )
                if new_rich:
                    rich = new_rich.model_dump(mode="json")
                    logger.info(
                        "[VISUALS-RICH] build_from_native succeeded | mode=%s | metric_cards=%d | charts=%d",
                        new_rich.mode,
                        len(new_rich.metric_cards),
                        len(new_rich.charts),
                    )
                else:
                    logger.info("[VISUALS-RICH] build_from_native returned None — falling back to render_rich_json artifact")
            except Exception:
                logger.exception("[VISUALS-RICH] build_from_native failed; keeping artifact-based rich payload")
            # Portfolio-scope: override rich with portfolio-specific payload when we have live context
            if portfolio_context and is_portfolio_scope_query(objective):
                try:
                    from finagent.run_agent import _build_portfolio_rich_payload
                    portfolio_rich = _build_portfolio_rich_payload(portfolio_context, benchmark="NIFTY50")
                    if portfolio_rich:
                        rich = portfolio_rich
                        logger.info("[VISUALS-RICH] portfolio rich payload wired | charts=%d | tables=%d",
                                    len(portfolio_rich.get("charts", [])), len(portfolio_rich.get("tables", [])))
                except Exception:
                    logger.exception("[VISUALS-RICH] portfolio rich payload failed; keeping existing rich")
            rich = _attach_markdown_body(rich, memo)
            # Safety net: ensure visuals are emitted even if no tokens streamed
            await _emit_visuals_once()
            return SynthesisResult(memo=memo, via="openai", used_sources=used, artifact=artifact, rich=rich)

    # Fallback to the python-generated structured text if LLM fails
    memo = render_markdown(artifact)
    await _emit_token(on_token, memo)
    rich = render_rich_json(artifact)
    try:
        new_rich = teammate_rich_builder.build_from_native(
            objective, bundle, docs, specialist_findings, memo
        )
        if new_rich:
            rich = new_rich.model_dump(mode="json")
            logger.info(
                "[VISUALS-RICH-FALLBACK] build_from_native succeeded | mode=%s | metric_cards=%d | charts=%d",
                new_rich.mode,
                len(new_rich.metric_cards),
                len(new_rich.charts),
            )
    except Exception:
        logger.exception("[VISUALS-RICH-FALLBACK] build_from_native failed; keeping artifact-based rich payload")
    # Portfolio-scope: override rich with portfolio-specific payload when we have live context
    if portfolio_context and is_portfolio_scope_query(objective):
        try:
            from finagent.run_agent import _build_portfolio_rich_payload
            portfolio_rich = _build_portfolio_rich_payload(portfolio_context, benchmark="NIFTY50")
            if portfolio_rich:
                rich = portfolio_rich
                logger.info("[VISUALS-RICH-FALLBACK] portfolio rich payload wired | charts=%d | tables=%d",
                            len(portfolio_rich.get("charts", [])), len(portfolio_rich.get("tables", [])))
        except Exception:
            logger.exception("[VISUALS-RICH-FALLBACK] portfolio rich payload failed; keeping existing rich")
    rich = _attach_markdown_body(rich, memo)
    # Safety net: emit visuals in fallback path too
    await _emit_visuals_once()
    return SynthesisResult(memo=memo, via=f"artifact:{mode.value}", used_sources=used, artifact=artifact, rich=rich)


async def _load_peer_quotes(
    objective: str,
    target: str,
    entity,
    bundle: EnrichmentBundle,
    mode: OutputMode,
) -> dict[str, YahooQuote]:
    if mode != OutputMode.COMPANY_COMPARISON:
        return {}
    peers: dict[str, YahooQuote] = {}
    primary_key = getattr(entity, "yahoo_ticker", None) or getattr(entity, "normalized_name", None)
    peer_entities = [
        peer for peer in extract_finance_entities(objective or target, limit=4)
        if (peer.yahoo_ticker or peer.normalized_name) != primary_key and peer.yahoo_ticker
    ]
    if not peer_entities:
        return {}

    async def _fetch_one(peer):
        try:
            return peer, await asyncio.wait_for(fetch_yahoo_quote(peer.yahoo_ticker), timeout=12.0)
        except Exception:
            return peer, None

    results = await asyncio.gather(*(_fetch_one(p) for p in peer_entities))
    for peer, quote in results:
        if quote is not None:
            key = peer.canonical_name or peer.ticker_label or peer.yahoo_ticker
            peers[key] = quote
    return peers


# ════════════════════════════════════════════════════════════════════════════
# RICH PEER ENRICHMENT — for comparison queries
# Fetches yahoo + india snapshot + wikipedia + news for each peer IN PARALLEL.
# This gives the LLM symmetric data on both companies so comparison output
# isn't lopsided toward the primary entity.
# ════════════════════════════════════════════════════════════════════════════
async def _load_peer_bundles(
    peer_targets: list[str],
    objective: str,
    target: str,
    entity,
    mode: OutputMode,
) -> dict[str, dict]:
    """Fetch comprehensive enrichment (yahoo + india + wiki + news) for each peer in parallel."""
    if not peer_targets and mode != OutputMode.COMPANY_COMPARISON:
        return {}

    # If no explicit peer_targets passed, derive from query (comparison fallback)
    candidate_names: list[str] = []
    if peer_targets:
        candidate_names = list(peer_targets)
    elif mode == OutputMode.COMPANY_COMPARISON:
        primary_key = getattr(entity, "yahoo_ticker", None) or getattr(entity, "normalized_name", None)
        for p in extract_finance_entities(objective or target, limit=4):
            pk = p.yahoo_ticker or p.normalized_name
            if pk and pk != primary_key:
                candidate_names.append(p.canonical_name or p.ticker_label or p.yahoo_ticker)

    if not candidate_names:
        return {}

    # Lazy import to avoid circular / startup costs
    try:
        from finagent.tools.data import (
            fetch_india_snapshot,
            fetch_news,
            fetch_wikipedia_summary,
        )
    except ImportError:
        fetch_india_snapshot = None
        fetch_news = None
        fetch_wikipedia_summary = None

    from finagent.geo.entity_resolver import resolve_entity

    async def _fetch_one_peer(name: str) -> tuple[str, dict]:
        try:
            peer_entity = resolve_entity(name)
        except Exception:
            return name, {}

        ticker = peer_entity.yahoo_ticker
        canonical = peer_entity.canonical_name or name
        # Decide which fetchers to run
        is_india_peer = bool(getattr(peer_entity, "country_code", "") == "IN" or (ticker or "").endswith(".NS") or (ticker or "").endswith(".BO"))
        nse_sym = None
        if is_india_peer and ticker:
            nse_sym = ticker.split(".")[0]

        async def _safe(coro, timeout):
            if coro is None:
                return None
            try:
                return await asyncio.wait_for(coro, timeout=timeout)
            except Exception:
                return None

        # Build coroutines (some may be None if fetcher unavailable)
        yahoo_coro = fetch_yahoo_quote(ticker) if ticker else None
        india_coro = fetch_india_snapshot(nse_sym) if (fetch_india_snapshot and nse_sym) else None
        wiki_coro = fetch_wikipedia_summary(canonical) if fetch_wikipedia_summary else None
        news_coro = None
        if fetch_news:
            try:
                news_coro = fetch_news(
                    canonical,
                    hl=getattr(peer_entity.profile, "news_hl", "en"),
                    gl=getattr(peer_entity.profile, "news_gl", "IN"),
                    ceid=getattr(peer_entity.profile, "news_ceid", "IN:en"),
                )
            except Exception:
                news_coro = None

        yahoo, india, wiki, news = await asyncio.gather(
            _safe(yahoo_coro, 12.0),
            _safe(india_coro, 15.0),
            _safe(wiki_coro, 8.0),
            _safe(news_coro, 12.0),
            return_exceptions=False,
        )

        return canonical, {
            "yahoo": yahoo,
            "india_snap": india,
            "wikipedia": wiki,
            "news": news or [],
            "entity": peer_entity,
        }

    results = await asyncio.gather(*(_fetch_one_peer(n) for n in candidate_names))
    out: dict[str, dict] = {}
    for name, data in results:
        # Skip empty results
        if data and (data.get("yahoo") or data.get("india_snap") or data.get("wikipedia")):
            out[name] = data
    return out


def _build_peer_facts_block(peer_bundles: dict[str, dict]) -> str:
    """Build a comprehensive facts block for peer companies — symmetric with primary bundle data."""
    lines: list[str] = ["=== PEER COMPANY DATA (use for side-by-side comparison) ==="]
    for peer_name, pb in peer_bundles.items():
        lines.append(f"\n──── {peer_name} ────")
        yahoo = pb.get("yahoo")
        india = pb.get("india_snap")
        wiki = pb.get("wikipedia")
        news = pb.get("news") or []

        # Yahoo data
        if yahoo:
            cur = getattr(yahoo, "currency", "") or ""
            if getattr(yahoo, "price", None) is not None:
                chg = getattr(yahoo, "change_pct", None)
                chg_str = f" ({chg:+.2f}%)" if chg is not None else ""
                lines.append(f"  Price: {cur} {yahoo.price:,.2f}{chg_str}")
            if getattr(yahoo, "market_cap", None):
                lines.append(f"  Market cap: {cur} {yahoo.market_cap:,.0f}")
            lo = getattr(yahoo, "fifty_two_week_low", None)
            hi = getattr(yahoo, "fifty_two_week_high", None)
            if lo is not None and hi is not None:
                lines.append(f"  52-week range: {lo:.2f} – {hi:.2f}")
            pm = getattr(yahoo, "financial_metrics", None) or {}
            if isinstance(pm, dict):
                if pm.get("total_revenue"):
                    lines.append(f"  Revenue (TTM): {pm['total_revenue']:,.0f}")
                if pm.get("ebitda"):
                    lines.append(f"  EBITDA: {pm['ebitda']:,.0f}")
                if pm.get("gross_margins") is not None:
                    lines.append(f"  Gross margin: {pm['gross_margins']*100:.1f}%")
                if pm.get("operating_margins") is not None:
                    lines.append(f"  Operating margin: {pm['operating_margins']*100:.1f}%")
                if pm.get("profit_margins") is not None:
                    lines.append(f"  Net margin: {pm['profit_margins']*100:.1f}%")
                if pm.get("return_on_equity") is not None:
                    lines.append(f"  ROE: {pm['return_on_equity']*100:.1f}%")
                if pm.get("return_on_assets") is not None:
                    lines.append(f"  ROA: {pm['return_on_assets']*100:.1f}%")
                if pm.get("trailing_pe") is not None:
                    lines.append(f"  P/E (trailing): {pm['trailing_pe']:.2f}x")
                if pm.get("forward_pe") is not None:
                    lines.append(f"  P/E (forward): {pm['forward_pe']:.2f}x")
                if pm.get("price_to_book") is not None:
                    lines.append(f"  P/B: {pm['price_to_book']:.2f}x")
                if pm.get("debt_to_equity") is not None:
                    lines.append(f"  D/E: {pm['debt_to_equity']:.2f}")
                if pm.get("dividend_yield") is not None:
                    lines.append(f"  Dividend yield: {pm['dividend_yield']*100:.2f}%")
                if pm.get("earnings_growth") is not None:
                    lines.append(f"  Earnings growth: {pm['earnings_growth']*100:.1f}%")
                if pm.get("revenue_growth") is not None:
                    lines.append(f"  Revenue growth: {pm['revenue_growth']*100:.1f}%")

        # India snapshot data (Indian peers)
        if india:
            if getattr(india, "sector", None):
                lines.append(f"  Sector: {india.sector}")
            if getattr(india, "industry", None):
                lines.append(f"  Industry: {india.industry}")
            if getattr(india, "market_cap_cr", None) is not None:
                lines.append(f"  Market cap (NSE): ₹{india.market_cap_cr:,.0f} Cr")
            if getattr(india, "pe_ratio", None) is not None:
                lines.append(f"  P/E (NSE): {india.pe_ratio:.2f}x")
            if getattr(india, "pb_ratio", None) is not None:
                lines.append(f"  P/B (NSE): {india.pb_ratio:.2f}x")
            if getattr(india, "roe", None) is not None:
                lines.append(f"  ROE (NSE): {india.roe:.1f}%")
            if getattr(india, "roce", None) is not None:
                lines.append(f"  ROCE: {india.roce:.1f}%")
            if getattr(india, "debt_to_equity", None) is not None:
                lines.append(f"  D/E (NSE): {india.debt_to_equity:.2f}")
            if getattr(india, "dividend_yield", None) is not None:
                lines.append(f"  Dividend yield (NSE): {india.dividend_yield:.2f}%")

        # Wikipedia overview
        if wiki and getattr(wiki, "extract", None):
            snippet = wiki.extract[:600].replace("\n", " ")
            lines.append(f"  Overview: {snippet}")

        # Recent news headlines
        if news:
            lines.append("  Recent news:")
            for n in news[:4]:
                title = getattr(n, "title", "") or ""
                source = getattr(n, "source", "") or ""
                if title:
                    lines.append(f"    • {title[:140]}{f' ({source})' if source else ''}")

    return "\n".join(lines) + "\n"


def _build_peer_quotes_only_block(peer_quotes: dict) -> str:
    """Fallback facts block when only yahoo quotes are available (no rich bundles)."""
    lines: list[str] = ["=== PEER COMPANY DATA (yahoo-only) ==="]
    for peer_name, pq in peer_quotes.items():
        lines.append(f"\n──── {peer_name} ────")
        if getattr(pq, "price", None) is not None:
            cur = getattr(pq, "currency", "") or ""
            lines.append(f"  Price: {cur} {pq.price:,.2f}")
        if getattr(pq, "market_cap", None):
            lines.append(f"  Market cap: {pq.market_cap:,.0f}")
        pm = getattr(pq, "financial_metrics", None) or {}
        if isinstance(pm, dict):
            if pm.get("total_revenue"):
                lines.append(f"  Revenue: {pm['total_revenue']:,.0f}")
            if pm.get("profit_margins") is not None:
                lines.append(f"  Net margin: {pm['profit_margins']*100:.1f}%")
            if pm.get("return_on_equity") is not None:
                lines.append(f"  ROE: {pm['return_on_equity']*100:.1f}%")
            if pm.get("trailing_pe") is not None:
                lines.append(f"  P/E: {pm['trailing_pe']:.2f}x")
    return "\n".join(lines) + "\n"

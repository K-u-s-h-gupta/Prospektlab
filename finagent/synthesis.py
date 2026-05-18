"""LLM synthesis pass — turn the full evidence pool into a readable memo.

When OPENAI_API_KEY is set we stream tokens from OpenAI. When it isn't
we still produce a polished prose memo from the same fact bundle.

All monetary figures are presented in INR (crore/lakh notation) first.
The memo never invents numbers — every figure is sourced from NSE/BSE,
Moneycontrol, Screener.in, SEBI filings, the live Yahoo quote (.NS/.BO),
or community signals.
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

from finagent.prompt_builder import default_system_prompt
from finagent.runtime_provider import resolve_openai_config
from finagent.state.checkpoint import Checkpoint
from finagent.state.citation_log import Citation
from finagent.tools.data import (
    FxRate,
    HNStory,
    IndiaCompanySnapshot,
    NewsItem,
    RedditPost,
    SEBIFiling,
    StockTwitsSnapshot,
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
    # India-specific data sources (replaces SEC EDGAR)
    india_snap: IndiaCompanySnapshot | None = None
    sebi_filing: SEBIFiling | None = None
    shareholding: dict | None = None
    # Universal sources
    yahoo: YahooQuote | None = None
    wikipedia: WikipediaSummary | None = None
    fx: FxRate | None = None
    reddit: list[RedditPost] = field(default_factory=list)
    hackernews: list[HNStory] = field(default_factory=list)
    stocktwits: StockTwitsSnapshot | None = None
    news: list[NewsItem] = field(default_factory=list)

    def has_any(self) -> bool:
        return bool(
            self.india_snap
            or self.yahoo
            or self.wikipedia
            or self.sebi_filing
            or self.reddit
            or self.hackernews
            or self.stocktwits
            or self.news
        )

    # Back-compat shims — code that read bundle.sec now gets india_snap
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


def _amount_to_usd(value: float, unit: str) -> float:
    u = (unit or "").upper()
    if u == "USD":
        return value
    # SEC EDGAR sometimes returns share counts in "shares" — leave untouched.
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


def _build_source_digest(docs: list[ScrapedDoc]) -> tuple[str, int]:
    lines: list[str] = []
    used = 0
    char_total = 0
    for d in docs:
        if char_total >= _MEMO_BUDGET_CHARS:
            break
        title = (d.title or "(no title)").strip()
        excerpt = (d.excerpt or "").strip().replace("\n", " ")
        block = (
            f"### Source {used + 1}\n"
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
        # US / SEC path — sec.metrics are SECMetric objects with .display_value()
        s = bundle.sec
        lines.append(f"\nSEC EDGAR: {s.ticker} | {s.name} | CIK {s.cik}")
        if s.sic_description:
            lines.append(f"  Industry (SIC): {s.sic_description}")
        if s.exchanges:
            lines.append(f"  Listed on: {', '.join(s.exchanges)}")
        for key, m in s.metrics.items():
            # m is a SECMetric dataclass — use its methods
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
    if bundle.reddit:
        sent = {"bullish": 0, "bearish": 0, "hype": 0, "neutral": 0}
        for p in bundle.reddit:
            sent[p.sentiment] = sent.get(p.sentiment, 0) + 1
        lines.append(
            f"\nReddit (community signal): {len(bundle.reddit)} high-upvote posts | "
            f"bullish {sent['bullish']}, bearish {sent['bearish']}, hype {sent['hype']}, neutral {sent['neutral']}"
        )
        for p in bundle.reddit[:5]:
            lines.append(f"  - r/{p.subreddit} ({p.score} upvotes, {p.sentiment}): {p.title}")
    if bundle.hackernews:
        lines.append(f"\nHacker News ({len(bundle.hackernews)} stories):")
        for h in bundle.hackernews[:5]:
            lines.append(f"  - {h.points} pts, {h.num_comments} comments: {h.title}")
    if bundle.stocktwits:
        st = bundle.stocktwits
        lines.append(
            f"\nStockTwits ${st.ticker}: bullish {st.bullish}, bearish {st.bearish}, "
            f"unrated {st.unrated} — net {st.net_sentiment}"
        )
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
Writing style and formatting rules — follow strictly:
1. Use Markdown headings (## for sections, ### for sub-sections), bold for
   key terms, and tables for comparative data. Bullet points are allowed for
   lists of items (risks, catalysts, metrics). The output will be rendered as
   Markdown, so structure aids readability.
2. This is an India-focused research system. Present all monetary figures
   in INR FIRST (crore / lakh notation), with USD equivalents in parentheses
   only where relevant. Use Indian-style grouping (e.g. ₹3.45 Cr or ₹45.6 L).
   Do NOT lead with USD for Indian-listed companies.
3. Authoritative Indian sources: NSE India, BSE India, SEBI filings,
   company investor relations, Screener.in, Trendlyne, Moneycontrol, Mint,
   Economic Times. Regulatory framework is SEBI, not SEC.
4. Do not invent numbers. If a figure is missing, say "data not available" —
   never fill gaps with estimates presented as facts.
5. Cite sources inline as [n] referring to the numbered SOURCES list.
6. End each major section with a confidence tag:
   **[CONFIDENCE: HIGH]** | **MEDIUM** | **LOW** based on source triangulation.
7. Tone: senior equity analyst memo — measured, specific, evidence-driven.
   For IPO analysis use DRHP/RHP terminology. For earnings, use "concall".
8. For deep research reports, produce ALL requested sections in full.
   Do not truncate or summarise. Each section must be substantive (≥150 words).
"""


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
) -> str:
    cfg = resolve_openai_config()
    if cfg is None:
        raise RuntimeError("No LLM provider configured — set OPENAI_API_KEY or XAI_API_KEY")
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise RuntimeError("openai package not installed") from exc

    client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    system_prompt = default_system_prompt() + "\n" + _LLM_STYLE_GUIDE

    # Detect comparison queries to inject comparison-specific instructions
    _lower_obj = (objective or "").lower()
    _is_comparison = any(t in _lower_obj for t in (" vs ", " versus ", "compare", "comparison", "against", "head to head"))

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

    user_prompt = (
        f"**Research target:** {target}\n"
        f"**Objective:** {objective}\n\n"
        f"{comparison_instructions}"
        "Produce a comprehensive, structured research report addressing the objective above.\n\n"
        "Requirements:\n"
        "- Use all available facts and source material provided below.\n"
        "- Never hallucinate numbers or invent figures — cite every claim with [n].\n"
        "- Use Markdown structure: ## section headings, tables for metrics, bullet points for lists.\n"
        "- If a data point is missing from the provided facts, explicitly state it is unavailable.\n"
        "- For deep/marathon reports: produce ALL sections in full — do NOT abbreviate.\n\n"
        f"=== VERIFIED FACTS ===\n{facts}\n\n"
        f"=== SOURCE DOCUMENTS ===\n{digest}\n\n"
        f"{_conflict_block(conflicts)}"
    )

    chunks: list[str] = []
    model_to_use = synth_model or cfg.model
    messages = [{"role": "system", "content": system_prompt}]
    if chat_history:
        messages.extend(chat_history)
    messages.append({"role": "user", "content": user_prompt})

    # Deep/marathon reports need more tokens; standard chat can stay short.
    _is_deep = any(kw in (objective or "").lower() for kw in (
        "deep_research_report", "synthesis", "investment-grade", "marathon", "full-scale"
    ))
    _max_tokens = 8000 if _is_deep else 4000

    stream = await client.chat.completions.create(
        model=model_to_use,
        temperature=0.2,
        max_tokens=_max_tokens,
        stream=True,
        messages=messages,
    )
    try:
        async for event in stream:
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
            return full
        resp = await client.chat.completions.create(
            model=cfg.model,
            temperature=0.2,
            max_tokens=4000,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        final = resp.choices[0].message.content or ""
        if isinstance(final, list):
            final = "".join(
                part.get("text", "") if isinstance(part, dict) else getattr(part, "text", "")
                for part in final
            )
        final = str(final).strip()
        if final:
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
    """Compute CAGR across a list of SECSeriesPoint-like objects (oldest first)."""
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
            f"{label} is a registered issuer (CIK {s.cik}) with market data sourced from SEC EDGAR for cross-listed reference."
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
        sentences = [f"{s.name} ({s.ticker}) is registered with the SEC under CIK {s.cik}."]
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
                f"The most recent SEC-filed financials come from a {latest[0]} for the period ending {latest[1]}. "
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


def _community_sentiment_prose(bundle: EnrichmentBundle) -> str:
    pieces: list[str] = []
    if bundle.reddit:
        sent = {"bullish": 0, "bearish": 0, "hype": 0, "neutral": 0}
        for p in bundle.reddit:
            sent[p.sentiment] = sent.get(p.sentiment, 0) + 1
        total = len(bundle.reddit)
        hype_flag = ""
        if sent["hype"] >= 3:
            hype_flag = " The hype-token density is high enough to warrant a pump-and-dump check before acting on retail flow."
        pieces.append(
            f"Across {total} high-upvote Reddit threads in r/IndianStreetBets, r/IndiaInvestments, "
            f"r/DalalStreetTalks, r/IndiaFinance and r/investing, the breakdown is {sent['bullish']} bullish, "
            f"{sent['bearish']} bearish, {sent['hype']} hype-leaning, {sent['neutral']} neutral.{hype_flag}"
        )
    if bundle.stocktwits:
        st = bundle.stocktwits
        pieces.append(
            f"StockTwits messages tagged ${st.ticker} skew {st.net_sentiment}: "
            f"{st.bullish} bullish, {st.bearish} bearish, {st.unrated} unrated across the latest stream."
        )
    if bundle.hackernews:
        hn = bundle.hackernews
        top = hn[0] if hn else None
        if top:
            pieces.append(
                f"Hacker News surfaced {len(hn)} story-level discussions, the strongest being "
                f"\"{top.title}\" at {top.points} points with {top.num_comments} comments."
            )
    if not pieces:
        return (
            "Community and retail sentiment data was not available for this session. "
            "For Indian stocks, discussions on r/IndianStreetBets, r/IndiaInvestments, "
            "and platforms like Moneycontrol forums or TradingView Ideas may provide "
            "additional retail sentiment signals. This section will auto-populate when "
            "community APIs return valid data."
        )
    return " ".join(pieces)


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

    # SEC-based thesis points (US companies)
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

    # Yahoo-based thesis points (Indian companies with no SEC data)
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

    if bundle.reddit:
        hype = sum(1 for p in bundle.reddit if p.sentiment == "hype")
        if hype >= 3:
            bear.append(
                "Retail hype intensity on Reddit is elevated, which historically precedes mean-reversion "
                "rather than sustainable outperformance."
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
            MemoSection(title="Community and retail sentiment", body=_community_sentiment_prose(bundle), confidence="MEDIUM" if (bundle.reddit or bundle.stocktwits or bundle.hackernews) else "LOW"),
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
        "iterative gap-driven follow-ups, and direct community-data APIs."
    )
    if blocked_count:
        methodology_bits.append(
            f"{blocked_count} sources were blocked by robots.txt and recorded as click-through citations only."
        )
    if bundle.sec:
        methodology_bits.append(
            f"SEC EDGAR companyfacts supplied {len(bundle.sec.metrics)} authoritative metrics (CIK {bundle.sec.cik})."
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
    if bundle.reddit or bundle.stocktwits or bundle.hackernews:
        community_parts = []
        if bundle.reddit:
            community_parts.append(f"{len(bundle.reddit)} Reddit posts")
        if bundle.stocktwits:
            community_parts.append(f"{bundle.stocktwits.bullish + bundle.stocktwits.bearish + bundle.stocktwits.unrated} StockTwits messages")
        if bundle.hackernews:
            community_parts.append(f"{len(bundle.hackernews)} Hacker News stories")
        methodology_bits.append("Community signal was sampled from " + ", ".join(community_parts) + ".")

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
    timeout_s: float = 75.0,
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
) -> SynthesisResult:
    digest, used = _build_source_digest(docs)
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
    # ── Append RICH peer data to facts block for comparison queries ──
    # Prefer peer_bundles (full enrichment) over peer_quotes (yahoo-only)
    if peer_bundles:
        facts += "\n" + _build_peer_facts_block(peer_bundles)
    elif peer_quotes:
        facts += "\n" + _build_peer_quotes_only_block(peer_quotes)
    if resolve_openai_config() is not None:
        try:
            memo = await asyncio.wait_for(
                _openai_memo(target, objective, digest, facts, conflicts, on_token=on_token, synth_model=synth_model, chat_history=chat_history),
                timeout=timeout_s,
            )
            rich = render_rich_json(artifact)
            # Try teammate's new rich_builder for richer structured output
            try:
                new_rich = teammate_rich_builder.build(objective, [], [], memo)
                if new_rich:
                    rich = new_rich.model_dump(mode="json")
            except Exception:
                pass
            # Safety net: ensure visuals are emitted even if no tokens streamed
            await _emit_visuals_once()
            return SynthesisResult(memo=memo, via="openai", used_sources=used, artifact=artifact, rich=rich)
        except Exception as exc:
            logger.warning("OpenAI synthesis failed (%s); using structured prose builder", exc)
            
    # Fallback to the python-generated structured text if LLM fails
    memo = render_markdown(artifact)
    await _emit_token(on_token, memo)
    rich = render_rich_json(artifact)
    try:
        new_rich = teammate_rich_builder.build(objective, [], [], memo)
        if new_rich:
            rich = new_rich.model_dump(mode="json")
    except Exception:
        pass
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

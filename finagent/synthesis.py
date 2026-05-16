"""LLM synthesis pass — turn the full evidence pool into a readable memo.

When OPENAI_API_KEY is set we stream tokens from OpenAI. When it isn't
we still produce a polished prose memo (proper paragraphs, no bullet
clutter, no boilerplate disclosures) from the same fact bundle.

All USD figures are duplicated in INR using the live USDINR Yahoo quote
fetched at session start. The memo never invents numbers — every figure
is sourced from the SEC EDGAR companyfacts API, the 10-K narrative we
pulled directly, the live Yahoo quote, or one of the community signals.
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
from finagent.output.contracts import OutputMode, ResponseDepth
from finagent.output.intent_classifier import classify_output_mode, extract_finance_entities, normalize_depth
from finagent.output.memo_formatter import MemoSection, format_memo
from finagent.output.renderer import render_markdown
from finagent.prompt_builder import default_system_prompt
from finagent.runtime_provider import resolve_openai_config
from finagent.state.checkpoint import Checkpoint
from finagent.state.citation_log import Citation
from finagent.tools.data import (
    FilingNarrative,
    FxRate,
    HNStory,
    NewsItem,
    RedditPost,
    SECCompanySnapshot,
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
    sec: SECCompanySnapshot | None = None
    yahoo: YahooQuote | None = None
    wikipedia: WikipediaSummary | None = None
    filing: FilingNarrative | None = None
    fx: FxRate | None = None
    reddit: list[RedditPost] = field(default_factory=list)
    hackernews: list[HNStory] = field(default_factory=list)
    stocktwits: StockTwitsSnapshot | None = None
    news: list[NewsItem] = field(default_factory=list)

    def has_any(self) -> bool:
        return bool(
            self.sec
            or self.yahoo
            or self.wikipedia
            or self.filing
            or self.reddit
            or self.hackernews
            or self.stocktwits
            or self.news
        )


@dataclass
class SynthesisResult:
    memo: str
    via: str  # "openai" | "structured"
    used_sources: int


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
    if bundle.sec:
        s = bundle.sec
        lines.append(f"\nSEC EDGAR: {s.ticker} | {s.name} | CIK {s.cik}")
        if s.sic_description:
            lines.append(f"  Industry (SIC): {s.sic_description}")
        if s.exchanges:
            lines.append(f"  Listed on: {', '.join(s.exchanges)}")
        for key, m in s.metrics.items():
            inr_part = ""
            if fx and m.unit.upper() == "USD":
                inr_part = f" / INR ~ {format_inr(m.value, fx.rate)}"
            lines.append(
                f"  {key} = {m.display_value()}{inr_part} ({m.label}; {m.form} FY{m.fy} {m.fp or ''} ending {m.end})"
            )
        if s.recent_filings:
            lines.append("  Recent filings:")
            for f in s.recent_filings[:6]:
                lines.append(f"    - {f.form} filed {f.filing_date} (report {f.report_date}): {f.url}")
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
Writing style rules — follow strictly:
1. Write in clear, natural paragraphs. NO bullet lists, NO bold-asterisks,
   NO Markdown headings inside paragraphs. The reader is reading a memo,
   not a slide.
2. This is an India-focused research system. Present all monetary figures
   in INR FIRST (crore / lakh notation), with USD equivalents in parentheses
   only where relevant. Use Indian-style grouping (e.g. ₹3.45 Cr or ₹45.6 L).
   Do NOT lead with USD for Indian-listed companies.
3. Authoritative Indian sources: NSE India, BSE India, SEBI filings,
   company investor relations, Screener.in, Trendlyne, Moneycontrol, Mint,
   Economic Times. Regulatory framework is SEBI, not SEC.
4. Do not invent numbers. If a figure is missing, say it is missing.
5. Cite sources inline as [n] referring to the numbered SOURCES list.
6. End each major section with a confidence tag on its own line:
   `[CONFIDENCE: HIGH]` | `MEDIUM` | `LOW` based on triangulation.
7. Tone: junior equity analyst note — measured, specific, no hype words.
   For IPO analysis use DRHP/RHP terminology. For earnings, use concall.
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
) -> str:
    cfg = resolve_openai_config()
    if cfg is None:
        raise RuntimeError("OPENAI_API_KEY not configured")
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise RuntimeError("openai package not installed") from exc

    client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    system_prompt = default_system_prompt() + "\n" + _LLM_STYLE_GUIDE
    user_prompt = (
        f"Target: {target}\n"
        f"Objective: {objective}\n\n"
        "You are an expert financial advisor. Provide a comprehensive, structured response "
        "addressing the user's objective directly.\n"
        "- Format your answer beautifully using Markdown (bold text, bullet points, headers).\n"
        "- Use tables to present comparative data or key financial metrics clearly.\n"
        "- If the user asks for a comparison, structure it as a comparison.\n"
        "- If they ask for an estimate or analysis, structure it accordingly.\n"
        "- Cite your sources using the numbered citations provided in the sources list.\n"
        "- Never hallucinate numbers. Use the provided facts and sources exclusively.\n\n"
        f"=== FACTS ===\n{facts}\n\n"
        f"=== SOURCES ===\n{digest}\n\n"
        f"{_conflict_block(conflicts)}"
    )

    chunks: list[str] = []
    model_to_use = synth_model or cfg.model
    stream = await client.chat.completions.create(
        model=model_to_use,
        temperature=0.2,
        max_tokens=4000,
        stream=True,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
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
    if not s or not s.history:
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
    if rev and rev.annual and len(rev.annual) >= 2:
        first_p = rev.annual[0]
        last_p = rev.annual[-1]
        cagr = _cagr(rev.annual)
        first_val = _format_money(first_p.value, rev.unit, fx)
        last_val = _format_money(last_p.value, rev.unit, fx)
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
    
    # Emit visual data event if session_id provided
    if session_id:
        from finagent.events import BUS
        BUS.emit(
            session_id,
            "visual_data_ready",
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
                    "svg_data": chart.svg_data,
                    "png_data": chart.png_data.decode('latin-1') if chart.png_data else "",
                    "width": chart.dimensions.get("width", 600) if hasattr(chart, 'dimensions') else 600,
                    "height": chart.dimensions.get("height", 300) if hasattr(chart, 'dimensions') else 300,
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

    facts = _build_facts_block(bundle)
    if resolve_openai_config() is not None:
        try:
            memo = await asyncio.wait_for(
                _openai_memo(target, objective, digest, facts, conflicts, on_token=on_token, synth_model=synth_model),
                timeout=timeout_s,
            )
            return SynthesisResult(memo=memo, via="openai", used_sources=used)
        except Exception as exc:
            logger.warning("OpenAI synthesis failed (%s); using structured prose builder", exc)
            
    # Fallback to the python-generated structured text if LLM fails
    memo = render_markdown(artifact)
    await _emit_token(on_token, memo)
    return SynthesisResult(memo=memo, via=f"artifact:{mode.value}", used_sources=used)


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
    for peer in extract_finance_entities(objective or target, limit=4):
        key = peer.yahoo_ticker or peer.normalized_name
        if not key or key == primary_key:
            continue
        if not peer.yahoo_ticker:
            continue
        try:
            quote = await asyncio.wait_for(fetch_yahoo_quote(peer.yahoo_ticker), timeout=12.0)
        except Exception:
            quote = None
        if quote is not None:
            peers[peer.canonical_name or peer.ticker_label or peer.yahoo_ticker] = quote
    return peers

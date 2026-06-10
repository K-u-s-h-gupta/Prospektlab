"""
ProspektLab Flash Content Engine — v2
Isolated content pipeline that orchestrates the existing 8-phase research
engine + IKG to generate highest-accuracy financial articles.

ISOLATION GUARANTEE: This module only CALLS run_research_session() and
IKGService methods as read-only consumers. It NEVER modifies
_DEEP_PASS_OBJECTIVES, run_research_session(), or any existing /research/*
routes. All changes are purely additive.

Content types:
  earnings — quarterly/annual results analysis
  sebi     — enforcement orders, regulatory updates
  trend    — sector / macro / thematic trends
  company  — company deep-dive profile
  manual   — operator-specified free topic

Modes:
  flash — 2 research passes + 1 synthesis  (~60–120 s)
  deep  — 7 research passes + 1 synthesis  (~5–8 min, optimised fork)
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

# ── v1 helpers (imported, never duplicated) ───────────────────────────────────
from finagent.content_automation import (
    ContentArticlePackage,
    ContentArticleSection,
    ContentArticleFaq,
    ContentAutomationRequest,
    ContentAutomationResult,
    _article_dir,
    _public_article_dir,
    _public_article_dirs,
    _safe_route_base,
    _write_bytes,
    _write_text,
    _upsert_sitemap,
    _generate_image,
    _event_fingerprint,
    _load_event_state,
    _save_event_state,
    refresh_public_research_hub,
    render_article_html,
    slugify,
    _SITE_URL,
)
from finagent.content.editorial import (
    contains_internal_language,
    event_is_low_value,
    run_editorial_revision_loop,
    sanitize_article_package,
    sanitize_public_text,
)
from finagent.seo.google_search_console import submit_sitemap
from finagent.events import BUS
from finagent.run_agent import AgentLoopConfig, run_research_session
from finagent.runtime_provider import resolve_openai_config

logger = logging.getLogger("finagent.content.flash_engine")

_FLASH_PASSES = int(os.getenv("FINAGENT_CONTENT_FLASH_PASSES", "3"))
_DEEP_PASSES = int(os.getenv("FINAGENT_CONTENT_DEEP_PASSES", "8"))
_DEEP_WALL_SECONDS = float(os.getenv("FINAGENT_CONTENT_DEEP_WALL_SECONDS", "420"))
_FLASH_WALL_SECONDS = 180.0
_PUBLISH_GATE_THRESHOLDS = {
    "confidence": 85,
    "editorial_score": 85,
    "source_score": 85,
    "depth_score": 85,
    "evidence_score": 95,
    "publish_gate_score": 90,
}
_OFFICIAL_DOMAIN_HINTS = (
    "nseindia.com",
    "bseindia.com",
    "bseindia",
    "sebi.gov.in",
    "rbi.org.in",
    "mca.gov.in",
)
_TRUSTED_SUPPORTING_DOMAIN_HINTS = (
    "reuters.com",
    "bloomberg.com",
    "moneycontrol.com",
    "livemint.com",
    "thehindu.com",
    "economictimes.indiatimes.com",
    "business-standard.com",
    "business-standard",
    "financialexpress.com",
    "ndtvprofit.com",
)
_LIMITED_DATA_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\blimited data\b", re.I),
    re.compile(r"\binsufficient data\b", re.I),
    re.compile(r"\bdata (?:was|were|is|are) not available\b", re.I),
    re.compile(r"\bunable to verify\b", re.I),
    re.compile(r"\bnot enough information\b", re.I),
)
_FILLER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bit is worth noting\b", re.I),
    re.compile(r"\bin conclusion\b", re.I),
    re.compile(r"\boverall[, ]", re.I),
    re.compile(r"\bneedless to say\b", re.I),
    re.compile(r"\bthis indicates that\b", re.I),
)
_SOURCE_SIGNAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\baccording to\b", re.I),
    re.compile(r"\bofficial disclosure\b", re.I),
    re.compile(r"\bverified filing\b", re.I),
    re.compile(r"\bcompany records\b", re.I),
    re.compile(r"\bexchange filing\b", re.I),
    re.compile(r"\bregulatory filing\b", re.I),
    re.compile(r"\bsebi\b", re.I),
    re.compile(r"\bnse\b", re.I),
    re.compile(r"\bbse\b", re.I),
)

_COMPANY_NAME_NOISE_TOKENS = {
    "limited",
    "ltd",
    "ltd.",
    "company",
    "co",
    "co.",
    "inc",
    "inc.",
    "plc",
    "private",
    "public",
    "india",
    "indian",
    "the",
    "and",
    "&",
}

_DIAGNOSTIC_PUBLIC_TOKENS: tuple[str, ...] = (
    "top metrics from the current evidence set",
    "quick visual read of the key data",
    "research coverage and limitations",
    "sources processed",
    "quality score",
    "specialist findings",
    "conflicts detected",
    "financial metrics resolved",
    "canonical entity resolution",
    "source count",
    "official source count",
    "supporting source count",
    "document evidence status",
    "context enrichment status",
    "evidence coverage by source type",
    "evidence coverage",
)
_BUSINESS_NUMERIC_HINTS: tuple[str, ...] = (
    "revenue",
    "profit",
    "loss",
    "margin",
    "ebit",
    "ebitda",
    "eps",
    "cash",
    "debt",
    "borrow",
    "order",
    "order book",
    "backlog",
    "guidance",
    "dividend",
    "buyback",
    "stake",
    "holding",
    "capex",
    "tcv",
    "turnover",
    "net worth",
    "assets",
    "liabilities",
    "default",
    "penalty",
    "settlement",
    "valuation",
    "growth",
    "yoy",
    "qoq",
    "fy",
    "quarter",
    "segment",
)


# Bound concurrent generation jobs so they don't saturate the pipeline
_FLASH_SEMAPHORE: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _FLASH_SEMAPHORE
    if _FLASH_SEMAPHORE is None:
        _FLASH_SEMAPHORE = asyncio.Semaphore(2)
    return _FLASH_SEMAPHORE


# ── Flash pass objectives (3 passes: 2 research + 1 synthesis) ───────────────

_CONTENT_FLASH_OBJECTIVES: list[str] = [
    # Pass 0 — Deterministic data extraction
    (
        "FACTS & DATA EXTRACTION: Extract every verifiable data point — revenue, profit, margins, "
        "YoY/QoQ growth, EPS, dividend, debt, cash, capex — directly from official exchange filings "
        "(BSE/NSE announcements), XBRL reports, company press releases, and regulatory orders. "
        "Do NOT infer or estimate figures; flag any missing or ambiguous data. "
        "Capture exact numbers with source citation for each. Note discrepancies across sources."
    ),
    # Pass 1 — Market context and interpretation
    (
        "CONTEXT & MARKET ANALYSIS: Interpret the extracted data through industry benchmarks, peer "
        "performance, analyst expectations, and macro environment (RBI, PLI schemes, USD-INR impact, "
        "sector dynamics, FII/DII flows). What changed versus the prior period and why? How does this "
        "compare to sector peers? What does this signal for the business trajectory? "
        "Every claim must be grounded in a named source."
    ),
    # Pass 2 — Full article synthesis (always last, emits memo)
    (
        "ARTICLE SYNTHESIS — FINAL: Write a complete publication-ready financial article that is more "
        "informative than any professional research analyst. Return ONLY valid JSON matching the "
        "ContentArticlePackage schema with these exact fields:\n"
        "  slug (URL-safe, 2-80 chars)\n"
        "  title (50-70 chars, SEO-optimised)\n"
        "  description (140-170 chars, meta description)\n"
        "  hero_eyebrow (short category label, max 40 chars)\n"
        "  hero_title (compelling headline, max 100 chars)\n"
        "  hero_summary (2-3 engaging sentences, 100-300 chars)\n"
        "  audience (target reader)\n"
        "  keywords (list of 8-12 precise terms)\n"
        "  key_takeaways (3-6 objects: {heading, detail})\n"
        "  metrics (4-8 objects: {label, value, change?, period?, source?})\n"
        "  tables (1-3 objects: {title, columns, rows, footnote?})\n"
        "  visuals (1-2 objects: {kind, title, points[{label,value}], note?})\n"
        "  timeline (0-8 objects: {date, event, detail?, source?})\n"
        "  evidence_notes (0-10 objects: {claim, source_title, source_url})\n"
        "  sections (list of 5-7 objects: {heading, paragraphs: [2-3 str], bullets: [0-5 str]})\n"
        "  faqs (list of 4-5 objects: {question, answer} retail investors actually ask)\n"
        "  cta_label (max 40 chars)\n"
        "  cta_href (link, usually '/#/contact')\n"
        "  image_prompt (detailed visual description for image generation)\n"
        "SEBI compliance mandatory: NO buy/sell/hold/accumulate/exit/target price/rebalancing. "
        "Every factual claim must cite its source inline. Zero filler sentences."
    ),
]

# ── Deep pass objectives (8 passes: 7 research + 1 synthesis) ────────────────

_CONTENT_DEEP_OBJECTIVES: list[str] = [
    # Pass 0
    (
        "BREAKING FACTS & FINANCIAL DATA: Extract every verifiable number from the latest filings — "
        "P&L (revenue, EBITDA, PAT, gross/net margins), balance sheet (total debt, cash, equity, "
        "working capital, inventory days), cash flow (OCF, FCF, capex, free-cash yield), XBRL-reported "
        "metrics, QoQ and YoY delta. Source only official filings: NSE/BSE exchange announcements, "
        "annual reports, concall transcripts, XBRL data. Flag any inferred figure explicitly."
    ),
    # Pass 1
    (
        "SECTOR & MACRO CONTEXT: Industry total addressable market size and growth rate, competitive "
        "structure (top 5 players, market share), regulatory environment (RBI, SEBI, sector-specific "
        "regulators), macro drivers (PLI schemes, inflation pass-through, USD-INR sensitivity, crude "
        "oil/commodity impact), government capex cycle effect, sector index outperformance/underperformance. "
        "Ground every assertion in a named data source."
    ),
    # Pass 2
    (
        "GOVERNANCE & OWNERSHIP INTELLIGENCE: Promoter holding structure (% owned, % pledged, trend "
        "over last 8 quarters), key director network and board independence score, related party "
        "transactions (nature, value, year), auditor name and tenure/qualifications, SEBI enforcement "
        "notices or adjudication orders on the company or promoters, corporate governance red flags "
        "from public records. Cite source for each finding — IKG graph data preferred."
    ),
    # Pass 3
    (
        "RISK ASSESSMENT & RED FLAGS: Regulatory risk (SEBI orders, show-cause notices, adjudications, "
        "ongoing investigations), litigation exposure (court filings, consumer complaints, arbitrations), "
        "key-person dependency (promoter concentration risk, single-customer/supplier risk), ESG "
        "controversies, forex and commodity sensitivity, credit rating changes (upgrade/downgrade). "
        "Quantify the estimated financial impact where data supports it."
    ),
    # Pass 4
    (
        "VALUATION FRAMING (SEBI-SAFE): Current trading multiples vs 3-year historical ranges — "
        "P/E, EV/EBITDA, P/B, EV/Sales, dividend yield. Implied scenario analysis from consensus — "
        "what revenue and earnings CAGR is the current price discounting? How has the stock re-rated "
        "vs sector peers over the last 1 and 3 years? Present ONLY as factual scenario ranges. "
        "ABSOLUTE PROHIBITION: NO buy/sell/hold/accumulate/exit/target price/rebalancing instruction. "
        "SEBI compliance is non-negotiable."
    ),
    # Pass 5
    (
        "GROWTH CATALYSTS & BUSINESS OUTLOOK: New product launches and their revenue addressable market, "
        "capacity expansion (capex committed, timeline, nameplate capacity post-expansion), government "
        "contracts and open tenders, M&A activity or rumours, international expansion milestones, R&D "
        "pipeline and IP filings, PLI scheme benefit realization schedule, verbatim management guidance "
        "from the latest concall. For each catalyst: probability, timeline, and revenue/margin impact."
    ),
    # Pass 6
    (
        "SMART-MONEY SIGNALS & SHAREHOLDING: Institutional flows — FII net buying/selling (3-quarter "
        "trend), DII activity (insurance + MF combined), top-5 mutual fund holders and QoQ position "
        "changes (entry/exit), promoter pledge delta, bulk and block deal activity with counterparty "
        "names. What are sophisticated institutions doing and what directional signal does it carry?"
    ),
    # Pass 7 — synthesis (always last, emits memo as JSON)
    (
        "DEEP ARTICLE SYNTHESIS — FINAL: Integrate ALL 7 prior research passes into a landmark "
        "investigative financial article — more informative than any professional research analyst. "
        "Return ONLY valid JSON matching ContentArticlePackage schema:\n"
        "  slug, title (50-70 chars), description (140-170 chars), hero_eyebrow, hero_title, "
        "  hero_summary, audience, keywords (10-12), "
        "  key_takeaways, metrics, tables, visuals, timeline, evidence_notes, "
        "  sections (7-9 rich objects: {heading, paragraphs: [2-4 str each], bullets: [0-6 str]})\n"
        "  — one section MUST examine verified ownership, governance, and filing signals covering "
        "    promoter pledges, RPTs, auditor tenure, and SEBI enforcement where records support it\n"
        "  faqs (5-6 objects: real investor questions with data-backed answers)\n"
        "  cta_label, cta_href, image_prompt\n"
        "SEBI compliance: NO buy/sell/hold/accumulate/exit/target price. "
        "Attribute every statistic to its source. Zero filler. Return raw JSON only."
    ),
]


# ── Request / result models ───────────────────────────────────────────────────

class FlashGenerationRequest(BaseModel):
    mode: Literal["flash", "deep", "research"] = "research"
    content_type: Literal["earnings", "sebi", "trend", "company", "manual"] = "manual"
    target: str = Field(..., min_length=2, max_length=300,
                        description="Company name, ticker, SEBI order subject, or topic")
    objective: str | None = Field(default=None, max_length=1000)
    source_url: str | None = Field(default=None, max_length=1000)
    source_markdown: str | None = Field(default=None, max_length=30000)
    source_evidence_meta: dict[str, Any] | None = None
    route_base: str = Field(default="insights", max_length=40)
    force_publish: bool = False
    include_image: bool = True
    overwrite: bool = True


class FlashIngestRequest(BaseModel):
    content_type: Literal["earnings", "sebi", "trend"] = "earnings"
    mode: Literal["flash", "deep", "research"] = "research"
    symbols: list[str] = Field(default_factory=list, max_length=20,
                               description="Ticker symbols for earnings/company types")
    isin_list: list[str] = Field(default_factory=list, max_length=20)
    bse_codes: list[str] = Field(default_factory=list, max_length=20)
    route_base: str = Field(default="insights", max_length=40)
    max_events_per_source: int = Field(default=5, ge=1, le=15)
    include_image: bool = True
    dry_run: bool = False


class FlashIngestResult(BaseModel):
    route_base: str
    generated_at: str
    discovered_events: int = 0
    generated_articles: int = 0
    auto_published: int = 0
    drafts: int = 0
    skipped_seen: int = 0
    failures: list[dict[str, str]] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)


# ── IKG context builder ───────────────────────────────────────────────────────

_MANUAL_EARNINGS_MARKERS = (
    "earnings", "results", "result", "quarter", "q1", "q2", "q3", "q4",
    "fy", "concall", "conference call", "fact sheet", "investor release",
)
_MANUAL_SEBI_MARKERS = (
    "sebi", "adjudication", "show cause", "settlement", "order", "penalty",
    "interim order", "enforcement",
)
_MANUAL_TREND_MARKERS = (
    "sector", "industry", "theme", "macro", "market", "outlook", "cycle",
    "policy", "trend",
)
_MANUAL_COMPANY_MARKERS = (
    "limited", "ltd", "bank", "services", "industries", "technology",
    "pharma", "finance", "motors", "power",
)
_IKG_TARGET_NOISE = re.compile(
    r"\b(q[1-4]|fy ?\d{2,4}|earnings?|results?|overview|analysis|update|preview|review|call|concall|fact ?sheet|transcript)\b",
    flags=re.IGNORECASE,
)


def _label_for_content_type(content_type: str) -> str:
    label_map = {
        "earnings": "Earnings Analysis",
        "sebi": "SEBI and Regulatory",
        "trend": "Market Trend Analysis",
        "company": "Company Intelligence",
        "manual": "Financial Insight",
    }
    return label_map.get((content_type or "manual").strip().lower(), "Financial Insight")


def _infer_manual_content_type(target: str, objective: str | None = None) -> str:
    text = f"{target} {objective or ''}".strip().lower()
    if any(marker in text for marker in _MANUAL_SEBI_MARKERS):
        return "sebi"
    if any(marker in text for marker in _MANUAL_EARNINGS_MARKERS):
        return "earnings"
    if any(marker in text for marker in _MANUAL_TREND_MARKERS):
        return "trend"
    if any(marker in text for marker in _MANUAL_COMPANY_MARKERS):
        return "company"
    tokens = [token for token in re.split(r"\s+", target.strip()) if token]
    if tokens and len(tokens) <= 6 and any(token.isupper() and len(token) <= 8 for token in tokens):
        return "company"
    return "manual"


def _effective_content_type(req: "FlashGenerationRequest") -> str:
    if req.content_type != "manual":
        return req.content_type
    return _infer_manual_content_type(req.target, req.objective)


def _normalise_ikg_target(target: str, content_type: str) -> str:
    cleaned = _IKG_TARGET_NOISE.sub(" ", target or "")
    cleaned = re.sub(r"[^A-Za-z0-9&().,\- ]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -,:")
    if cleaned and content_type in {"earnings", "company", "manual"}:
        words = cleaned.split()
        if len(words) > 6:
            cleaned = " ".join(words[:6])
    return cleaned or (target or "").strip()


def _article_structure_brief(content_type: str, target: str, has_ikg: bool) -> str:
    base = (
        "General requirements:\n"
        "- Lead with what changed and why it matters now.\n"
        "- Output structured presentation blocks: key_takeaways, metrics, tables, visuals, timeline, evidence_notes.\n"
        "- Keep metrics and tables source-backed. If a number is not in evidence, do not invent it.\n"
        "- Avoid generic company introductions unless they directly explain the quarter or event.\n"
        "- Do not mix live stock price, market cap, or valuation trivia into a historic earnings article unless clearly labeled with date and source.\n"
        "- Distinguish reported numbers, management commentary, and ProspektLab inference.\n"
    )
    if content_type == "earnings":
        base += (
            "For earnings-like topics, structure the article around:\n"
            "1. The quarter in one paragraph.\n"
            "2. The metrics that actually moved (revenue, margin, profit, cash, deal wins, dividend if declared).\n"
            "3. Demand by geography, vertical, product line, or client segment.\n"
            "4. Margin quality, hiring, productivity, attrition, and cash conversion.\n"
            "5. Management commentary, order book, discretionary-spend signals, and what to monitor next.\n"
            "6. Include at least one earnings table with YoY/QoQ deltas and one visual block based on those metrics.\n"
        )
    elif content_type == "company":
        base += (
            "For company intelligence topics, structure the article around business model, financial trajectory, governance, risks, catalysts, and peer context.\n"
            "Include one comparison table or metric strip plus one visual summary.\n"
        )
    elif content_type == "sebi":
        base += (
            "For SEBI topics, structure the article around the order timeline, allegations/findings, financial or governance implications, and what changes for public investors.\n"
            "Include a timeline block and a parties/action/status table when evidence supports it.\n"
        )
    elif content_type == "trend":
        base += (
            "For trend topics, structure the article around the thesis, data points, policy or macro triggers, segment winners and laggards, and the market consequences.\n"
            "Include one metrics table and one visual signal block.\n"
        )
    if has_ikg:
        base += (
            '- Include one dedicated section on verified ownership, governance, and filing signals.\n'
            "- If record coverage is partial, say so plainly instead of inventing missing governance data.\n"
        )
    return base


def _build_insights_hub_html_editorial(route_base: str = "insights") -> str:
    """
    Render the SEO landing page at /insights/research/
    listing all published articles in an editorial, filterable layout.
    """
    from finagent.content_automation import list_generated_articles

    route_base = _safe_route_base(route_base)
    articles = list_generated_articles(route_base=route_base, limit=120)
    published = [
        a for a in articles
        if str(a.get("publish_status") or "").lower() == "published"
        and str(a.get("publish_gate_status") or "").lower() == "publish"
    ]
    total = len(articles)
    published_count = len(published)
    research_count = sum(
        1
        for article in published
        if str(article.get("mode") or "").lower() in {"deep", "research"}
    )
    ikg_count = sum(1 for article in published if bool(article.get("ikg_covered")))
    now_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

    type_meta: dict[str, dict[str, str]] = {
        "earnings": {"label": "Earnings", "accent": "#0d766e"},
        "sebi": {"label": "SEBI", "accent": "#b4233c"},
        "trend": {"label": "Trend", "accent": "#0f3d91"},
        "company": {"label": "Company", "accent": "#6b46c1"},
        "manual": {"label": "Insight", "accent": "#845d1f"},
    }

    def _story_score(article: dict[str, Any]) -> int:
        raw = article.get("quality_score")
        if raw in (None, ""):
            raw = article.get("confidence_score")
        try:
            return int(round(float(raw or 0)))
        except Exception:
            return 0

    def _rgba(hex_colour: str, alpha: float) -> str:
        cleaned = (hex_colour or "#64748b").lstrip("#")
        if len(cleaned) != 6:
            return f"rgba(100, 116, 139, {alpha})"
        try:
            red = int(cleaned[0:2], 16)
            green = int(cleaned[2:4], 16)
            blue = int(cleaned[4:6], 16)
        except Exception:
            return f"rgba(100, 116, 139, {alpha})"
        return f"rgba({red}, {green}, {blue}, {alpha})"

    def _format_date(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return "Recently updated"
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt.strftime("%d %b %Y")
        except Exception:
            return html.escape(raw[:10])

    def _image_href(article: dict[str, Any]) -> str:
        slug = str(article.get("slug") or "").strip()
        if not slug:
            return "/prospektlab-logo.svg"
        suffix = Path(str(article.get("image_path") or "")).suffix.lower()
        ext = suffix if suffix in {".png", ".jpg", ".jpeg", ".webp", ".svg"} else ".svg"
        return f"/{route_base}/{slug}/cover{ext}"

    def _search_blob(article: dict[str, Any]) -> str:
        chunks = [
            str(article.get("title") or ""),
            str(article.get("description") or ""),
            str(article.get("hero_summary") or ""),
            str(article.get("audience") or ""),
        ]
        keywords = article.get("keywords") or []
        if isinstance(keywords, list):
            chunks.extend(str(item) for item in keywords[:8])
        return sanitize_public_text(" ".join(chunks).strip()).lower()

    def _story_card(article: dict[str, Any], *, featured: bool = False) -> str:
        slug = str(article.get("slug") or "").strip()
        title_text = sanitize_public_text(str(article.get("title") or slug or "Untitled insight"))
        summary_text = sanitize_public_text(str(article.get("hero_summary") or article.get("description") or "").strip())
        description_text = sanitize_public_text(str(article.get("description") or summary_text).strip())
        content_type = str(article.get("content_type") or "manual").strip().lower() or "manual"
        meta = type_meta.get(content_type, type_meta["manual"])
        accent = meta["accent"]
        local_url = f"/{route_base}/{slug}/" if slug else "#"
        summary_limit = 280 if featured else 180
        summary = summary_text[:summary_limit].rstrip()
        if summary and len(summary_text) > summary_limit:
            summary = summary.rstrip(" .,;:") + "..."
        ikg = bool(article.get("ikg_covered"))
        feature_note = '<div class="feature-note">Lead story</div>' if featured else ""
        date_label = _format_date(str(article.get("published_at") or article.get("generated_at") or ""))
        cover_href = html.escape(_image_href(article))
        title = html.escape(title_text)
        deck = html.escape(summary or description_text[:summary_limit] or "Publication-ready market research.")
        description = html.escape(description_text[:170])
        story_class = "story-card story-card-featured" if featured else "story-card"
        search_attr = html.escape(_search_blob(article), quote=True)
        return (
            f'<article class="{story_class}" style="--card-accent:{accent};--card-accent-soft:{_rgba(accent, 0.12)};" '
            f'data-story data-type="{html.escape(content_type)}" data-ikg="{"yes" if ikg else "no"}" '
            f'data-search="{search_attr}">'
            f'<a class="story-media" href="{html.escape(local_url)}" aria-label="{title}">'
            f'<img class="story-image" src="{cover_href}" alt="{title} cover image" loading="lazy" />'
            "</a>"
            '<div class="story-body">'
            f"{feature_note}"
            '<div class="story-overline">'
            f'<span class="meta-pill">{html.escape(date_label)} · {html.escape(meta["label"])}</span>'
            "</div>"
            f'<h2 class="story-title"><a href="{html.escape(local_url)}">{title}</a></h2>'
            f'<p class="story-summary">{deck}</p>'
            f'<p class="story-description">{description}</p>'
            '<div class="story-footer">'
            f'<span class="story-source">{html.escape("Source-backed" if ikg else "Editorial")}</span>'
            f'<a class="story-link" href="{html.escape(local_url)}">Open article</a>'
            "</div>"
            "</div>"
            "</article>"
        )

    type_counts = {
        key: sum(1 for article in published if str(article.get("content_type") or "manual").strip().lower() == key)
        for key in type_meta
    }
    avg_quality = round(sum(_story_score(article) for article in published) / published_count) if published_count else 0
    filter_specs: list[tuple[str, str, int]] = [("all", "All", published_count)]
    for key in ("earnings", "company", "sebi", "trend", "manual"):
        count = type_counts.get(key, 0)
        if count:
            filter_specs.append((key, type_meta[key]["label"], count))
    if ikg_count:
        filter_specs.append(("ikg", "Source-backed", ikg_count))
    filter_buttons = "".join(
        f'<button class="filter-button{" is-active" if key == "all" else ""}" type="button" '
        f'data-filter-button data-filter="{html.escape(key)}">{html.escape(label)}<span>{count}</span></button>'
        for key, label, count in filter_specs
    )

    if published:
        stories_html = "\n".join(
            _story_card(article, featured=(index == 0))
            for index, article in enumerate(published)
        )
    else:
        stories_html = (
            '<section class="empty-state" data-empty-state>'
            '<div class="empty-kicker">Editorial queue warming up</div>'
            '<h2>No public insights are live yet.</h2>'
            '<p>The archive will fill automatically as high-conviction stories clear review and publication checks.</p>'
            '<a class="story-link" href="/#/dashboard">Open Dashboard</a>'
            "</section>"
        )

    featured_image = f"{_SITE_URL}{_image_href(published[0])}" if published else f"{_SITE_URL}/prospektlab-logo.svg"
    schema = json.dumps(
        {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "Organization",
                    "@id": f"{_SITE_URL}/#organization",
                    "name": "ProspektLab",
                    "url": f"{_SITE_URL}/",
                    "logo": {"@type": "ImageObject", "url": f"{_SITE_URL}/prospektlab-logo.svg"},
                },
                {
                    "@type": "CollectionPage",
                    "@id": f"{_SITE_URL}/insights/research/#page",
                    "name": "ProspektLab Research Hub - Indian Market Intelligence",
                    "description": (
                        "Editorial-style financial research pages covering earnings, regulation, "
                        "company intelligence, and market trends for India."
                    ),
                    "url": f"{_SITE_URL}/insights/research/",
                    "image": featured_image,
                    "publisher": {"@id": f"{_SITE_URL}/#organization"},
                    "mainEntity": {"@id": f"{_SITE_URL}/insights/research/#itemlist"},
                },
                {
                    "@type": "ItemList",
                    "@id": f"{_SITE_URL}/insights/research/#itemlist",
                    "numberOfItems": published_count,
                    "itemListElement": [
                        {
                            "@type": "ListItem",
                            "position": index + 1,
                            "url": f"{_SITE_URL}/{route_base}/{article.get('slug')}/",
                            "name": article.get("title") or article.get("slug") or "Insight",
                        }
                        for index, article in enumerate(published[:24])
                    ],
                },
            ],
        },
        ensure_ascii=True,
    )

    return f"""<!doctype html>
<html lang="en-IN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>ProspektLab Research Hub | Indian Market Intelligence</title>
    <meta
      name="description"
      content="Editorial-style financial research for Indian markets, covering earnings, regulation, company intelligence, and market trends in direct, searchable URLs."
    />
    <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1" />
    <meta name="theme-color" content="#f4ecdf" />
    <link rel="canonical" href="{html.escape(_SITE_URL)}/insights/research/" />
    <link rel="icon" type="image/svg+xml" href="/prospektlab-favicon-v2.svg" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="ProspektLab" />
    <meta property="og:title" content="ProspektLab Research Hub | Indian Market Intelligence" />
    <meta
      property="og:description"
      content="A public archive of editorial-style research pages for Indian market participants."
    />
    <meta property="og:url" content="{html.escape(_SITE_URL)}/insights/research/" />
    <meta property="og:image" content="{html.escape(featured_image)}" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="ProspektLab Research Hub | Indian Market Intelligence" />
    <meta
      name="twitter:description"
      content="Editorial-style research pages for earnings, regulation, companies, and market trends."
    />
    <meta name="twitter:image" content="{html.escape(featured_image)}" />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Manrope:wght@400;500;600;700;800&family=Newsreader:opsz,wght@6..72,500;6..72,700&display=swap"
      rel="stylesheet"
    />
    <style>
      :root {{
        color-scheme: light;
        --paper: #f4ecdf;
        --paper-soft: #fffaf3;
        --ink: #142033;
        --muted: #5f6778;
        --line: rgba(20, 32, 51, 0.12);
        --line-strong: rgba(20, 32, 51, 0.18);
        --accent: #0d766e;
        --accent-blue: #0f3d91;
        --accent-gold: #ad6a1f;
        --shadow: 0 26px 80px rgba(15, 23, 42, 0.08);
      }}
      * {{
        box-sizing: border-box;
      }}
      html {{
        scroll-behavior: smooth;
      }}
      body {{
        margin: 0;
        font-family: "Manrope", Arial, sans-serif;
        background:
          radial-gradient(circle at top left, rgba(13, 118, 110, 0.1), transparent 24%),
          radial-gradient(circle at 100% 0%, rgba(15, 61, 145, 0.1), transparent 20%),
          linear-gradient(180deg, #f7f1e6 0%, #f4ecdf 45%, #f1e8d8 100%);
        color: var(--ink);
        line-height: 1.75;
      }}
      a {{
        color: inherit;
        text-decoration: none;
      }}
      img {{
        max-width: 100%;
        display: block;
      }}
      .shell {{
        width: min(calc(100% - 34px), 1240px);
        margin: 0 auto;
      }}
      .masthead {{
        position: sticky;
        top: 0;
        z-index: 40;
        backdrop-filter: blur(18px);
        background: rgba(244, 236, 223, 0.84);
        border-bottom: 1px solid rgba(20, 32, 51, 0.08);
      }}
      .masthead-inner {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 18px;
        padding: 14px 0;
      }}
      .brand {{
        display: inline-flex;
        align-items: center;
        gap: 10px;
      }}
      .brand-mark {{
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: linear-gradient(135deg, var(--accent), var(--accent-blue));
        box-shadow: 0 0 0 8px rgba(13, 118, 110, 0.08);
      }}
      .brand-text {{
        font-family: "IBM Plex Mono", monospace;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.18em;
        text-transform: uppercase;
      }}
      .masthead-links {{
        display: flex;
        align-items: center;
        gap: 16px;
        color: var(--muted);
        font-size: 13px;
      }}
      .masthead-links a:hover {{
        color: var(--ink);
      }}
      .hero {{
        padding: 34px 0 26px;
      }}
      .hero-panel {{
        border: 1px solid var(--line);
        border-radius: 34px;
        padding: 30px;
        background: linear-gradient(135deg, rgba(255, 250, 243, 0.95), rgba(249, 243, 232, 0.96));
        box-shadow: var(--shadow);
      }}
      .hero-grid {{
        display: grid;
        grid-template-columns: minmax(0, 1.12fr) minmax(300px, 0.88fr);
        gap: 26px;
        align-items: start;
      }}
      .eyebrow {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 7px 14px;
        border-radius: 999px;
        background: rgba(13, 118, 110, 0.1);
        color: var(--accent);
        border: 1px solid rgba(13, 118, 110, 0.16);
        font-family: "IBM Plex Mono", monospace;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }}
      .eyebrow::before {{
        content: "";
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--accent);
      }}
      h1,
      h2,
      h3 {{
        margin: 0;
        color: var(--ink);
      }}
      h1 {{
        margin-top: 18px;
        font-family: "Newsreader", Georgia, serif;
        font-size: clamp(3.05rem, 7vw, 5.7rem);
        line-height: 0.94;
        letter-spacing: -0.05em;
        max-width: 10.5ch;
      }}
      h2 {{
        font-family: "Newsreader", Georgia, serif;
        font-size: clamp(1.8rem, 3vw, 2.35rem);
        line-height: 1.02;
        letter-spacing: -0.04em;
      }}
      p {{
        margin: 0;
        color: var(--muted);
      }}
      .hero-copy {{
        margin-top: 18px;
        max-width: 62ch;
        font-size: 1.05rem;
      }}
      .stat-grid {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 14px;
        margin-top: 24px;
      }}
      .stat-card {{
        border: 1px solid var(--line);
        border-radius: 22px;
        padding: 16px 18px;
        background: rgba(255, 255, 255, 0.62);
      }}
      .stat-value {{
        font-family: "Newsreader", Georgia, serif;
        font-size: 2rem;
        line-height: 1;
        letter-spacing: -0.05em;
      }}
      .stat-label {{
        margin-top: 6px;
        font-family: "IBM Plex Mono", monospace;
        font-size: 11px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      .hero-aside {{
        display: grid;
        gap: 16px;
      }}
      .aside-card {{
        border: 1px solid var(--line);
        border-radius: 26px;
        padding: 22px;
        background: rgba(255, 250, 243, 0.84);
        box-shadow: 0 18px 40px rgba(15, 23, 42, 0.04);
      }}
      .aside-label,
      .section-label {{
        font-family: "IBM Plex Mono", monospace;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        color: var(--accent-gold);
      }}
      .capability-list {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 14px;
      }}
      .capability-chip,
      .meta-pill,
      .story-keyword {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 9px 13px;
        border-radius: 999px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.76);
        color: var(--ink);
        font-size: 12px;
      }}
      .capability-chip {{
        color: var(--muted);
      }}
      .controls {{
        padding: 10px 0 18px;
      }}
      .controls-top {{
        display: flex;
        align-items: end;
        justify-content: space-between;
        gap: 16px;
        flex-wrap: wrap;
      }}
      .controls-copy {{
        max-width: 56ch;
      }}
      .controls-copy p {{
        margin-top: 8px;
      }}
      .result-count {{
        margin-top: 8px;
        font-family: "IBM Plex Mono", monospace;
        font-size: 12px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      .search-shell {{
        min-width: min(100%, 340px);
      }}
      .search-label {{
        display: block;
        margin-bottom: 8px;
        font-family: "IBM Plex Mono", monospace;
        font-size: 11px;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      .search-input {{
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.76);
        padding: 14px 16px;
        color: var(--ink);
        font: inherit;
        box-shadow: 0 10px 24px rgba(15, 23, 42, 0.03);
      }}
      .search-input:focus {{
        outline: none;
        border-color: rgba(13, 118, 110, 0.35);
        box-shadow: 0 0 0 4px rgba(13, 118, 110, 0.08);
      }}
      .filter-strip {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 16px;
      }}
      .filter-button {{
        display: inline-flex;
        align-items: center;
        gap: 10px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.76);
        color: var(--muted);
        border-radius: 999px;
        padding: 10px 14px;
        font: inherit;
        font-size: 13px;
        cursor: pointer;
        transition: transform 0.18s ease, border-color 0.18s ease, color 0.18s ease, background 0.18s ease;
      }}
      .filter-button span {{
        padding: 2px 8px;
        border-radius: 999px;
        background: rgba(20, 32, 51, 0.06);
        color: var(--ink);
        font-size: 11px;
      }}
      .filter-button:hover,
      .filter-button.is-active {{
        transform: translateY(-1px);
        border-color: rgba(13, 118, 110, 0.24);
        background: rgba(13, 118, 110, 0.08);
        color: var(--ink);
      }}
      .stories-grid {{
        display: grid;
        grid-template-columns: repeat(12, minmax(0, 1fr));
        gap: 20px;
        padding-bottom: 26px;
      }}
      .story-card {{
        grid-column: span 4;
        display: flex;
        flex-direction: column;
        border: 1px solid var(--line);
        border-radius: 28px;
        overflow: hidden;
        background: rgba(255, 250, 243, 0.88);
        box-shadow: var(--shadow);
        transition: transform 0.22s ease, box-shadow 0.22s ease, border-color 0.22s ease;
      }}
      .story-card:hover {{
        transform: translateY(-4px);
        border-color: rgba(20, 32, 51, 0.18);
        box-shadow: 0 30px 90px rgba(15, 23, 42, 0.11);
      }}
      .story-card-featured {{
        grid-column: 1 / -1;
        display: grid;
        grid-template-columns: minmax(0, 1.08fr) minmax(320px, 0.92fr);
      }}
      .story-media {{
        position: relative;
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 240px;
        aspect-ratio: 3 / 2;
        overflow: hidden;
        background: linear-gradient(180deg, rgba(255, 250, 243, 0.96), rgba(241, 233, 222, 0.94));
      }}
      .story-card-featured .story-media {{
        min-height: 100%;
        aspect-ratio: auto;
        order: 2;
      }}
      .story-image {{
        width: 100%;
        height: 100%;
        object-fit: contain;
        object-position: center;
        transition: transform 0.25s ease;
      }}
      .story-card:hover .story-image {{
        transform: none;
      }}
      .story-body {{
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding: 22px 24px 24px;
      }}
      .feature-note {{
        font-family: "IBM Plex Mono", monospace;
        font-size: 11px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        color: var(--card-accent);
      }}
      .story-overline {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        align-items: center;
      }}
      .type-pill {{
        display: inline-flex;
        align-items: center;
        padding: 8px 13px;
        border-radius: 999px;
        background: var(--card-accent-soft);
        color: var(--card-accent);
        border: 1px solid rgba(20, 32, 51, 0.08);
        font-family: "IBM Plex Mono", monospace;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }}
      .meta-pill {{
        font-size: 11px;
        color: var(--muted);
      }}
      .meta-pill-accent {{
        color: var(--accent);
        border-color: rgba(13, 118, 110, 0.24);
        background: rgba(13, 118, 110, 0.08);
      }}
      .story-title {{
        font-family: "Newsreader", Georgia, serif;
        font-size: 2rem;
        line-height: 1.02;
        letter-spacing: -0.04em;
      }}
      .story-card-featured .story-title {{
        font-size: clamp(2.5rem, 5vw, 4rem);
      }}
      .story-title a:hover {{
        color: var(--card-accent);
      }}
      .story-summary {{
        font-size: 1rem;
        color: var(--ink);
      }}
      .story-description {{
        font-size: 0.96rem;
      }}
      .story-keywords {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }}
      .story-keyword {{
        font-size: 11px;
        color: var(--muted);
        padding: 8px 12px;
      }}
      .story-footer {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 14px;
        flex-wrap: wrap;
        margin-top: auto;
        padding-top: 8px;
      }}
      .story-source {{
        font-family: "IBM Plex Mono", monospace;
        font-size: 11px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      .story-score {{
        display: inline-flex;
        align-items: center;
        border-radius: 999px;
        padding: 8px 12px;
        font-family: "IBM Plex Mono", monospace;
        font-size: 11px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }}
      .score-strong {{
        color: #0d766e;
        background: rgba(13, 118, 110, 0.1);
      }}
      .score-mid {{
        color: #0f3d91;
        background: rgba(15, 61, 145, 0.09);
      }}
      .score-soft {{
        color: #845d1f;
        background: rgba(173, 106, 31, 0.1);
      }}
      .story-link {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 11px 18px;
        border-radius: 999px;
        border: 1px solid rgba(20, 32, 51, 0.12);
        background: var(--ink);
        color: #f8fafc;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
      }}
      .story-link:hover {{
        background: var(--card-accent);
      }}
      .empty-state {{
        grid-column: 1 / -1;
        width: 100%;
        min-width: 0;
        border: 1px dashed rgba(20, 32, 51, 0.18);
        border-radius: 30px;
        padding: 46px 28px;
        background: rgba(255, 250, 243, 0.74);
        text-align: center;
        overflow-wrap: anywhere;
      }}
      .empty-state h2 {{
        margin-top: 10px;
        font-size: clamp(2rem, 5vw, 3.2rem);
        max-width: 11ch;
        margin-left: auto;
        margin-right: auto;
      }}
      .empty-state p {{
        margin: 12px auto 22px;
        max-width: 54ch;
      }}
      .empty-kicker {{
        font-family: "IBM Plex Mono", monospace;
        font-size: 11px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        color: var(--accent);
      }}
      .method-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 16px;
        padding-bottom: 58px;
      }}
      .method-card {{
        border: 1px solid var(--line);
        border-radius: 24px;
        padding: 20px 22px;
        background: rgba(255, 250, 243, 0.86);
        box-shadow: 0 16px 38px rgba(15, 23, 42, 0.05);
      }}
      .method-card p {{
        margin-top: 10px;
        font-size: 0.95rem;
      }}
      .footer {{
        padding: 0 0 42px;
      }}
      .footer-card {{
        border-radius: 30px;
        padding: 28px 30px;
        background: linear-gradient(135deg, #15253d, #102036);
        color: #f6f8fc;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 18px;
        box-shadow: 0 30px 70px rgba(15, 23, 42, 0.18);
      }}
      .footer-card p {{
        margin-top: 8px;
        color: rgba(246, 248, 252, 0.76);
      }}
      .footer-link {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 11px 18px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.1);
        color: #f6f8fc;
        border: 1px solid rgba(255, 255, 255, 0.18);
      }}
      .is-hidden {{
        display: none !important;
      }}
      @media (max-width: 1180px) {{
        .hero-grid,
        .story-card-featured {{
          grid-template-columns: 1fr;
        }}
        .story-card {{
          grid-column: span 6;
        }}
        .story-card-featured .story-media {{
          order: 0;
        }}
        .stat-grid,
        .method-grid {{
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }}
      }}
      @media (max-width: 760px) {{
        .shell {{
          width: min(calc(100% - 22px), 1240px);
        }}
        .masthead-inner {{
          padding: 12px 0;
        }}
        .masthead-links {{
          gap: 10px;
          font-size: 12px;
        }}
        .hero-panel {{
          padding: 22px;
          border-radius: 26px;
        }}
        .stat-grid,
        .method-grid {{
          grid-template-columns: 1fr;
        }}
        .stories-grid {{
          gap: 16px;
        }}
        .story-card {{
          grid-column: 1 / -1;
        }}
        .story-body,
        .aside-card,
        .method-card {{
          padding: 18px;
        }}
        .footer-card {{
          padding: 22px;
          flex-direction: column;
          align-items: flex-start;
        }}
      }}
    </style>
    <script type="application/ld+json">{schema}</script>
  </head>
  <body>
    <div class="masthead">
      <div class="shell masthead-inner">
        <a class="brand" href="/{html.escape(route_base)}/research/">
          <span class="brand-mark"></span>
          <span class="brand-text">ProspektLab Research</span>
        </a>
        <div class="masthead-links">
          <a href="/#/dashboard">Dashboard</a>
          <a href="/#/contact">Contact</a>
        </div>
      </div>
    </div>

    <header class="hero">
      <div class="shell">
        <section class="hero-panel">
          <div class="hero-grid">
            <div>
              <div class="eyebrow">Public research</div>
              <h1>Indian market stories with the context serious readers actually need.</h1>
              <p class="hero-copy">
                Earnings, regulation, company moves, and sector shifts are published here as clean, searchable pages built for fast reading, deeper context, and repeat discovery.
              </p>
            </div>
            <div class="hero-aside">
              <section class="aside-card">
                <div class="aside-label">Publishing model</div>
                <h2 style="margin-top:10px;">Built for search, reading, and trust.</h2>
                <p style="margin-top:12px;">
                  Each article lives at a direct route, carries search metadata, and keeps the focus on the story rather than the workflow behind it.
                </p>
                <div class="capability-list">
                  <span class="capability-chip">Evidence-led reporting</span>
                  <span class="capability-chip">Continuous market watch</span>
                  <span class="capability-chip">Verified company context</span>
                  <span class="capability-chip">Compliance-safe language</span>
                </div>
              </section>
            </div>
          </div>
        </section>
      </div>
    </header>

    <main class="shell">
      <section class="controls">
        <div class="controls-top">
          <div class="controls-copy">
            <div class="section-label">Latest research</div>
            <h2 style="margin-top:10px;">Filter by topic, company, or coverage angle.</h2>
            <p>Search by company, theme, or keyword, then narrow the archive by story type or verified context.</p>
            <div class="result-count" data-result-count>{published_count} stories visible</div>
          </div>
          <label class="search-shell">
            <span class="search-label">Search archive</span>
            <input
              class="search-input"
              type="search"
              placeholder="Search company, theme, or keyword"
              data-search-input
            />
          </label>
        </div>
        <div class="filter-strip">{filter_buttons}</div>
      </section>

      <section class="stories-grid" data-story-grid>
        {stories_html}
      </section>

      <section class="method-grid">
        <article class="method-card">
            <div class="section-label">Evidence first</div>
            <h3 style="margin-top:10px;">Primary-source bias is deliberate.</h3>
            <p>Official filings, exchange disclosures, company material, and transcripts outrank generic summaries. The archive is designed to make that discipline easy to spot.</p>
          </article>
          <article class="method-card">
            <div class="section-label">Graph where useful</div>
            <h3 style="margin-top:10px;">Company context appears only when it adds real depth.</h3>
            <p>Ownership, governance, and filing context should sharpen the story, not decorate it. Thin coverage should stay clearly disclosed.</p>
          </article>
          <article class="method-card">
            <div class="section-label">Editorial finish</div>
            <h3 style="margin-top:10px;">The output should feel publishable on first open.</h3>
            <p>Sharper typography, calmer hierarchy, and cleaner routes make the archive feel closer to a financial publication than a content dump.</p>
          </article>
      </section>
    </main>

    <footer class="footer">
      <div class="shell">
        <div class="footer-card">
          <div>
            <div class="section-label" style="color: rgba(246, 248, 252, 0.64);">ProspektLab</div>
            <h3 style="color:#f6f8fc; margin-top:8px;">Research pages should feel deliberate and trustworthy.</h3>
            <p>Educational content only. No buy, sell, hold, or target-price language is published here.</p>
          </div>
          <a class="footer-link" href="/#/dashboard">ProspektLab Dashboard</a>
        </div>
      </div>
    </footer>

    <script>
      (function () {{
        const buttons = Array.from(document.querySelectorAll("[data-filter-button]"));
        const stories = Array.from(document.querySelectorAll("[data-story]"));
        const searchInput = document.querySelector("[data-search-input]");
        const resultCount = document.querySelector("[data-result-count]");
        const emptyState = document.querySelector("[data-empty-state]");
        let activeFilter = "all";

        const update = () => {{
          const query = String(searchInput && searchInput.value ? searchInput.value : "").trim().toLowerCase();
          let visible = 0;
          stories.forEach((story) => {{
            const type = String(story.getAttribute("data-type") || "");
            const ikg = String(story.getAttribute("data-ikg") || "no");
            const search = String(story.getAttribute("data-search") || "");
            const matchesFilter = activeFilter === "all"
              ? true
              : activeFilter === "ikg"
                ? ikg === "yes"
                : type === activeFilter;
            const matchesSearch = !query || search.indexOf(query) !== -1;
            const show = matchesFilter && matchesSearch;
            story.classList.toggle("is-hidden", !show);
            if (show) visible += 1;
          }});

          if (resultCount) {{
            resultCount.textContent = visible === 1 ? "1 story visible" : visible + " stories visible";
          }}
          if (emptyState && stories.length) {{
            emptyState.hidden = visible !== 0;
          }}
        }};

        buttons.forEach((button) => {{
          button.addEventListener("click", () => {{
            activeFilter = String(button.getAttribute("data-filter") || "all");
            buttons.forEach((item) => item.classList.toggle("is-active", item === button));
            update();
          }});
        }});

        if (searchInput) {{
          searchInput.addEventListener("input", update);
        }}
        update();
      }})();
    </script>
  </body>
</html>
"""
async def _build_ikg_context(target: str) -> dict[str, Any]:
    """
    Pull IKG structured data for the target entity. Degrades gracefully if
    the entity is not IKG-covered (e.g., trend/macro topics).
    """
    try:
        from finagent.ikg.service import get_ikg_service
    except Exception:
        return {}

    try:
        svc = get_ikg_service()
        bundle = await svc.build_company_bundle(identifier=target, depth="standard")
        entity = bundle.entity or {}
        cin = entity.get("cin")
        if not entity.get("resolved") or not cin:
            return {}

        ownership = bundle.ownership or {}
        governance = bundle.governance or {}
        risk = bundle.risk or {}
        documents = bundle.documents or {}
        coverage = bundle.coverage or {}
        company = bundle.company or {}

        ctx: dict[str, Any] = {
            "cin": cin,
            "covered": True,
            "company": company,
            "entity": entity,
            "coverage": coverage,
            "warnings": bundle.warnings or [],
            "ownership": ownership,
            "auditors": governance.get("auditors") or [],
            "related_party_transactions": risk.get("related_party_transactions") or [],
            "concall_transcripts": documents.get("concall_transcripts") or [],
            "enforcement_actions": risk.get("enforcement_actions") or [],
        }

        parts: list[str] = []
        entity_name = entity.get("name") or company.get("company_name") or target
        identity_bits = [f"IKG resolved {entity_name} to CIN {cin}"]
        if entity.get("isin"):
            identity_bits.append(f"ISIN {entity['isin']}")
        if entity.get("nse_symbol"):
            identity_bits.append(f"NSE symbol {entity['nse_symbol']}")
        parts.append(", ".join(identity_bits) + ".")

        promoters = ownership.get("promoters") or []
        promoter_chain = ownership.get("promoter_chain") or []
        pledge_summary = ownership.get("pledge_summary") or {}
        promoter_holding = float(pledge_summary.get("total_promoter_holding_pct") or 0.0)
        pledge_pct = float(pledge_summary.get("total_pledge_pct") or 0.0)
        owner_name = ""
        if promoter_chain:
            owner_name = str(promoter_chain[0].get("owner_name") or "").strip()
            promoter_holding = promoter_holding or float(promoter_chain[0].get("holding_pct") or 0.0)
        elif promoters:
            owner_name = str(promoters[0].get("owner_name") or "").strip()
            promoter_holding = promoter_holding or float(promoters[0].get("holding_pct") or 0.0)
        if promoter_holding > 0:
            owner_prefix = f"Promoter/major holder {owner_name}" if owner_name else "Promoter/major holder"
            parts.append(f"{owner_prefix} is visible in IKG at about {promoter_holding:.2f}% holding.")
            if pledge_pct > 0:
                parts.append(f"Promoter pledge visible in IKG at about {pledge_pct:.2f}% of holding.")

        auditors = governance.get("auditors") or []
        if auditors:
            latest = auditors[0]
            parts.append(
                f"Statutory auditor: {latest.get('auditor_name', 'N/A')} "
                f"(FY {latest.get('fiscal_year', 'N/A')})."
            )
            unique_auditors = {row.get("auditor_name") for row in auditors if row.get("auditor_name")}
            if len(unique_auditors) >= 2:
                parts.append(f"Auditor changed {len(unique_auditors) - 1} time(s) in {len(auditors)} years on record.")

        rpts = risk.get("related_party_transactions") or []
        if rpts:
            parts.append(f"Related-party coverage in IKG: {len(rpts)} fact(s).")

        enforcement = risk.get("enforcement_actions") or []
        if enforcement:
            parts.append(f"Regulatory or enforcement records in IKG: {len(enforcement)} item(s).")

        transcripts = documents.get("concall_transcripts") or []
        if transcripts:
            parts.append(f"Concall transcript coverage in IKG: {len(transcripts)} session(s).")

        sparse_layers = [
            name for name in ("ownership", "governance", "risk", "documents")
            if coverage.get(name) == "missing"
        ]
        if sparse_layers:
            parts.append(
                "IKG coverage is currently thin on "
                + ", ".join(sparse_layers)
                + " for this entity, so those angles should be cross-checked against primary filings."
            )

        ctx["narrative"] = " ".join(parts)
        return ctx

    except Exception:
        logger.exception("IKG context build failed for %r", target)
        return {}


# ── BUS helpers ───────────────────────────────────────────────────────────────

def _harvest_final_event(job_id: str) -> dict[str, Any]:
    """Scan BUS history for the 'final' event and return its payload."""
    for _idx, event in reversed(BUS.history(job_id, limit=5000)):
        if event.type == "final":
            return dict(event.payload)
    return {}


def _harvest_memo(job_id: str) -> str:
    """Try to harvest memo text from BUS final event or memo file."""
    final = _harvest_final_event(job_id)
    memo = (
        final.get("memo")
        or final.get("memo_preview")
        or final.get("answer")
        or final.get("text")
        or final.get("content")
        or ""
    )
    if not memo:
        try:
            from finagent.paths import finagent_data_path
            p = finagent_data_path("memos") / f"{job_id}.md"
            if p.is_file():
                memo = p.read_text(encoding="utf-8")
        except Exception:
            pass
    return memo


# ── Article assembly ──────────────────────────────────────────────────────────

def _split_memo_to_sections(memo: str) -> list[ContentArticleSection]:
    """Parse a markdown memo into ContentArticleSection list.

    Handles both ## (standard) and #### (news-brief) heading styles.
    """
    sections: list[ContentArticleSection] = []
    heading: str | None = None
    paragraphs: list[str] = []
    bullets: list[str] = []
    # Match ## and #### headings (news brief uses ####)
    _HEADING_RE = re.compile(r"^#{2,4}\s+(.+)")

    def _flush() -> None:
        if heading and (paragraphs or bullets):
            safe_paragraphs = list(paragraphs[:4])
            if not safe_paragraphs:
                if bullets:
                    safe_paragraphs = [bullets[0][:900]]
                else:
                    safe_paragraphs = [
                        "This section summarizes the filing-backed context captured in the research notes."
                    ]
            sections.append(ContentArticleSection(
                heading=heading[:140],
                paragraphs=safe_paragraphs,
                bullets=bullets[:6],
            ))

    for line in (memo or "").splitlines():
        s = line.strip()
        m = _HEADING_RE.match(s)
        if m:
            _flush()
            heading = m.group(1).strip()[:140]
            paragraphs = []
            bullets = []
        elif (s.startswith("- ") or s.startswith("* ")) and heading:
            text = s[2:].strip()
            if text and len(bullets) < 6:
                bullets.append(text[:300])
        elif s.startswith("|") and heading:
            # Table rows — treat each cell as a bullet for content
            pass
        elif s and heading and not s.startswith("#") and len(paragraphs) < 4:
            # Skip markdown table separators
            if not re.match(r"^\|[-| ]+\|$", s):
                paragraphs.append(s[:900])

    _flush()
    return sections[:10]


def _extract_faqs(memo: str) -> list[ContentArticleFaq]:
    """Extract FAQ Q&A pairs from memo text."""
    faqs: list[ContentArticleFaq] = []
    pattern = re.compile(
        r"(?:Q:|Question:|\*\*Q\*\*:?)?\s*([^\n]{8,180}\?)\s*\n+\s*(?:A:|Answer:|\*\*A\*\*:?)?\s*([^\n]{24,900})",
        re.IGNORECASE,
    )
    for m in pattern.finditer(memo or ""):
        q = m.group(1).strip()[:180]
        a = m.group(2).strip()[:900]
        if q and a:
            faqs.append(ContentArticleFaq(question=q, answer=a))
        if len(faqs) >= 6:
            break
    return faqs


_DEFAULT_FAQS = [
    ContentArticleFaq(
        question="Is this investment advice?",
        answer=(
            "No. This article is independent research for informational purposes only and does not "
            "constitute investment advice or a transaction recommendation for any security. "
            "Consult a SEBI-registered investment advisor before making investment decisions."
        ),
    ),
    ContentArticleFaq(
        question="Where does ProspektLab source its data?",
        answer=(
            "ProspektLab aggregates data from BSE, NSE, and SEBI official filings, XBRL financial "
            "reports, company press releases, and concall transcripts, then cross-checks material claims "
            "Knowledge Graph — a proprietary property graph covering listed Indian companies."
        ),
    ),
    ContentArticleFaq(
        question="How accurate is AI-generated financial analysis?",
        answer=(
            "ProspektLab's multi-pass pipeline cross-validates every claim across official filings, "
            "exchange announcements, and the IKG. Numbers are sourced from deterministic datasets "
            "(XBRL, BSE/NSE disclosures) — not generated by the model. Each article cites its "
            "sources and flags any estimate as such."
        ),
    ),
]

# Override default FAQ copy with clean public wording (no internal framework labels).
_DEFAULT_FAQS = [
    ContentArticleFaq(
        question="Is this investment advice?",
        answer=(
            "No. This article is independent research for informational purposes only and does not "
            "constitute investment advice or a transaction recommendation for any security. "
            "Consult a SEBI-registered investment advisor before making investment decisions."
        ),
    ),
    ContentArticleFaq(
        question="Where does ProspektLab source its data?",
        answer=(
            "ProspektLab aggregates data from BSE, NSE, and SEBI official filings, XBRL financial "
            "reports, company press releases, and concall transcripts, then cross-checks material claims "
            "against verified corporate records before publication."
        ),
    ),
    ContentArticleFaq(
        question="How accurate is AI-generated financial analysis?",
        answer=(
            "ProspektLab cross-validates every material claim across official filings and exchange "
            "announcements. Numbers are sourced from deterministic datasets (XBRL and BSE/NSE "
            "disclosures), and any estimate is explicitly labeled."
        ),
    ),
]


def _normalise_section_dicts(
    sections_raw: Any,
    *,
    target_display: str,
) -> list[dict[str, Any]]:
    """Coerce section payload to satisfy ContentArticleSection constraints."""
    sections: list[dict[str, Any]] = []
    for section in list(sections_raw or [])[:10]:
        if not isinstance(section, dict):
            continue
        heading = sanitize_public_text(str(section.get("heading") or "")).strip()[:140]
        if len(heading) < 3:
            continue
        paragraphs = [
            sanitize_public_text(str(paragraph)).strip()[:900]
            for paragraph in list(section.get("paragraphs") or [])[:4]
            if sanitize_public_text(str(paragraph)).strip()
        ]
        bullets = [
            sanitize_public_text(str(bullet)).strip()[:300]
            for bullet in list(section.get("bullets") or [])[:6]
            if sanitize_public_text(str(bullet)).strip()
        ]
        if not paragraphs:
            if bullets:
                paragraphs = [bullets[0]]
            else:
                paragraphs = [
                    f"This section consolidates source-backed context for {target_display} with a focus on material updates."
                ]
        if len(paragraphs) == 1:
            paragraphs.append(
                f"This analysis anchors each point to disclosed evidence and highlights what should be monitored next for {target_display}."
            )
        sections.append(
            {
                "heading": heading,
                "paragraphs": paragraphs,
                "bullets": bullets,
            }
        )
    return sections


def _coerce_article_payload(
    data: dict[str, Any],
    *,
    slug: str,
    target_display: str,
    label: str,
) -> dict[str, Any]:
    """Repair partial/malformed JSON-model output into schema-valid article payload."""
    payload = dict(data or {})
    payload["slug"] = slug
    payload["title"] = sanitize_public_text(str(payload.get("title") or f"{target_display} - {label}"))[:120]
    payload["description"] = sanitize_public_text(str(payload.get("description") or ""))[:220]
    if len(payload["description"]) < 80:
        payload["description"] = (
            f"In-depth {label.lower()} for {target_display}, with evidence-backed metrics, context, and watchpoints."
        )[:220]

    payload["hero_eyebrow"] = sanitize_public_text(str(payload.get("hero_eyebrow") or label))[:60]
    payload["hero_title"] = sanitize_public_text(str(payload.get("hero_title") or target_display))[:120]
    payload["hero_summary"] = sanitize_public_text(str(payload.get("hero_summary") or payload["description"]))[:360]
    if len(payload["hero_summary"]) < 80:
        payload["hero_summary"] = (
            f"This report synthesizes official disclosures, structured evidence, and market context for {target_display}."
        )[:360]

    sections = _normalise_section_dicts(payload.get("sections"), target_display=target_display)
    while len(sections) < 4:
        sections.append(
            {
                "heading": "Key research context",
                "paragraphs": [
                    f"This section captures material developments for {target_display} from official updates and supporting evidence."
                ],
                "bullets": [],
            }
        )
    payload["sections"] = sections[:10]

    faqs_raw = list(payload.get("faqs") or [])
    clean_faqs: list[dict[str, str]] = []
    for item in faqs_raw[:6]:
        if not isinstance(item, dict):
            continue
        question = sanitize_public_text(str(item.get("question") or "")).strip()[:180]
        answer = sanitize_public_text(str(item.get("answer") or "")).strip()[:900]
        if len(question) >= 8 and len(answer) >= 24:
            clean_faqs.append({"question": question, "answer": answer})
    for faq in _DEFAULT_FAQS:
        if len(clean_faqs) >= 4:
            break
        clean_faqs.append({"question": faq.question, "answer": faq.answer})
    payload["faqs"] = clean_faqs[:6]
    return payload


def _company_tokens(value: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", (value or "").lower())
    return [
        token
        for token in tokens
        if len(token) >= 3 and token not in _COMPANY_NAME_NOISE_TOKENS
    ]


def _extract_company_hint(req: "FlashGenerationRequest", meta: dict[str, Any]) -> str:
    candidates = [
        str(meta.get("company_name") or ""),
        str(meta.get("entity_name") or ""),
        str(req.target or ""),
    ]
    for candidate in candidates:
        text = sanitize_public_text(candidate).strip()
        if not text:
            continue
        # Common monitor target pattern: "... for <company>"
        for_match = re.search(r"\bfor\s+(.+)$", text, flags=re.IGNORECASE)
        cleaned = for_match.group(1).strip() if for_match else text
        cleaned = re.sub(r"[:\-|].*$", "", cleaned).strip()
        if len(cleaned) >= 4:
            return cleaned[:140]
    return ""


def _filter_sources_for_company(
    sources: list[dict[str, str]],
    *,
    company_hint: str,
) -> list[dict[str, str]]:
    tokens = _company_tokens(company_hint)
    if not tokens:
        return sources

    filtered: list[dict[str, str]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "")
        evidence_type = str(source.get("evidence_type") or "")
        source_kind = str(source.get("kind") or "")
        if source_kind == "primary_seed":
            filtered.append(source)
            continue
        haystack = " ".join(
            [
                str(source.get("title") or ""),
                str(source.get("snippet") or ""),
                url,
            ]
        ).lower()
        token_match = any(token in haystack for token in tokens)
        if evidence_type in {"official_document", "official_attachment"}:
            if token_match:
                filtered.append(source)
            continue
        if evidence_type == "company_context":
            filtered.append(source)
            continue
        if token_match:
            filtered.append(source)

    # Never return an empty list if upstream already found evidence.
    return filtered or sources[:6]


def _assemble_article_from_pipeline(
    memo: str | None,
    ikg_ctx: dict[str, Any],
    req: FlashGenerationRequest,
    slug: str,
    quality_score: float,
    content_type: str | None = None,
) -> ContentArticlePackage:
    """
    Build a ContentArticlePackage from the synthesis memo.
    - First attempts JSON parse (the synthesis objective requests JSON output).
    - Falls back to markdown splitting if JSON parse fails.
    - Injects IKG context block in both paths.
    """
    ikg_section_dict = None
    if ikg_ctx.get("narrative"):
        ikg_section_dict = {
            "heading": "What verified ownership and governance records show",
            "paragraphs": [
                ikg_ctx["narrative"],
                (
                    "These records track corporate governance structures, "
                    "promoter networks, auditor tenure, related-party transactions, and SEBI regulatory "
                    "actions for listed Indian companies — providing a verified layer of intelligence "
                    "not available from public data sources alone."
                ),
            ],
            "bullets": [],
        }

    if memo:
        # Strip markdown fences if present
        cleaned = memo.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned, flags=re.MULTILINE)
            cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        try:
            data = json.loads(cleaned)
            data = _coerce_article_payload(
                data,
                slug=slug,
                target_display=req.target[:80],
                label=_label_for_content_type((content_type or req.content_type or "manual").strip().lower()),
            )
            # Inject IKG section
            if ikg_section_dict:
                existing_sections: list[dict] = data.get("sections") or []
                # Check if IKG section already present
                has_ikg = any(
                    "knowledge graph" in str(s.get("heading", "")).lower()
                    for s in existing_sections
                )
                if not has_ikg and existing_sections:
                    existing_sections.insert(
                        max(0, len(existing_sections) - 1), ikg_section_dict
                    )
                    data["sections"] = existing_sections
            data = _coerce_article_payload(
                data,
                slug=slug,
                target_display=req.target[:80],
                label=_label_for_content_type((content_type or req.content_type or "manual").strip().lower()),
            )
            return ContentArticlePackage.model_validate(data)
        except Exception:
            logger.debug("Memo JSON parse failed for %r — using markdown fallback", slug)

    # ── Markdown fallback ─────────────────────────────────────────────────────
    effective_content_type = (content_type or req.content_type or "manual").strip().lower()
    label = _label_for_content_type(effective_content_type)
    target_display = req.target[:80]

    sections = _split_memo_to_sections(memo or "")
    if ikg_section_dict:
        sections.append(
            ContentArticleSection(
                heading=ikg_section_dict["heading"],
                paragraphs=ikg_section_dict["paragraphs"],
                bullets=[],
            )
        )
    # Ensure minimum depth
    while len(sections) < 4:
        sections.append(ContentArticleSection(
            heading="Key Takeaways",
            paragraphs=[
                f"The above analysis covers key developments for {target_display} based on "
                f"official exchange filings, regulatory disclosures, and verified governance records.",
            ],
            bullets=[],
        ))

    faqs = _extract_faqs(memo or "")
    faqs.extend(_DEFAULT_FAQS)
    faqs = faqs[:6]

    title = f"{target_display} — {label} | ProspektLab"[:120]
    description = (
        f"In-depth {label.lower()} of {target_display} from official filings, "
        f"verified governance records, and ProspektLab's editorial research workflow."
    )[:220]

    return ContentArticlePackage(
        slug=slug,
        title=title,
        description=description,
        hero_eyebrow=label,
        hero_title=target_display[:120],
        hero_summary=description[:360],
        audience="Indian investors and market researchers",
        keywords=[target_display, label, "India markets", "ProspektLab",
                  "financial analysis", effective_content_type, "BSE", "NSE", "SEBI"][:12],
        key_takeaways=[
            {
                "heading": "What changed",
                "detail": f"Latest update for {target_display} summarized from verified records and supporting context.",
            },
            {
                "heading": "Why it matters",
                "detail": "The article links event-level developments to business and investor-relevant implications.",
            },
        ],
        sections=sections[:10],
        faqs=faqs,
        cta_label="Explore ProspektLab",
        cta_href="/#/contact",
        image_prompt=(
            f"Premium editorial cover for '{target_display}'. Create a sharp 3:2 business-news composition "
            "with layered financial screens, documents, market cues, and one strong central subject tied to the story. "
            "Keep the full subject comfortably inside frame with generous margins so it reads well in a report card. "
            "Rich lighting, serious publication aesthetic, India market context, no headline text, no watermark."
        ),
    )


# ── Direct JSON article synthesis (post-research pass) ────────────────────────

def _synth_model_candidates(primary_model: str) -> list[str]:
    candidates = [
        str(primary_model or "").strip(),
        str(os.getenv("OPENAI_CHAT_MODEL") or "").strip(),
        "gpt-5.4-mini",
        "gpt-4.1-mini",
    ]
    ordered: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    return ordered or ["gpt-5.4-mini"]


def _required_section_headings(content_type: str) -> list[str]:
    common = [
        "What changed now",
        "Historical context and trendline",
        "Management and execution signals",
        "Risks, governance, and disclosures",
        "What to monitor next",
    ]
    if content_type == "earnings":
        return common + ["Quarter scorecard with YoY and QoQ deltas"]
    if content_type == "sebi":
        return common + ["Regulatory timeline and case status"]
    if content_type == "trend":
        return common + ["Sector map and transmission channels"]
    if content_type == "company":
        return common + ["Business model and competitive position"]
    return common


def _build_primary_evidence_context(req: "FlashGenerationRequest") -> str:
    meta = req.source_evidence_meta or {}
    lines: list[str] = []
    source_url = str(req.source_url or meta.get("source_url") or "").strip()
    if source_url:
        lines.append(f"Primary URL: {source_url}")

    doc_type = str(meta.get("attachment_document_type") or "").strip()
    extraction_status = str(meta.get("attachment_extraction_status") or "").strip()
    parser_name = str(meta.get("attachment_parser") or "").strip()
    if doc_type:
        lines.append(f"Attachment type: {doc_type}")
    if extraction_status:
        lines.append(f"Attachment extraction status: {extraction_status}")
    if parser_name:
        lines.append(f"Attachment parser: {parser_name}")

    structured_facts = meta.get("attachment_structured_facts")
    if isinstance(structured_facts, dict) and structured_facts:
        lines.append("Structured facts from attachment:")
        for key, value in list(structured_facts.items())[:30]:
            k = sanitize_public_text(str(key).replace("_", " ").strip())[:120]
            v = sanitize_public_text(str(value).strip())[:240]
            if k and v:
                lines.append(f"- {k}: {v}")

    table_count = len(list(meta.get("attachment_tables") or []))
    if table_count:
        lines.append(f"Attachment tables detected: {table_count}")

    markdown_excerpt = sanitize_public_text(str(req.source_markdown or "")).strip()
    attachment_text = sanitize_public_text(str(meta.get("attachment_text") or "")).strip()
    if markdown_excerpt:
        lines.append("\nPrimary source excerpt:")
        lines.append(markdown_excerpt[:6000])
    if attachment_text:
        lines.append("\nAttachment extraction excerpt:")
        lines.append(attachment_text[:7000])

    return "\n".join(lines).strip()


async def _direct_json_article_call(
    memo: str,
    ikg_ctx: dict[str, Any],
    req: "FlashGenerationRequest",
    slug: str,
    content_type: str | None = None,
    revision_note: str | None = None,
) -> ContentArticlePackage | None:
    """
    Use a direct OpenAI call (JSON mode) to convert the collected research memo
    into a structured ContentArticlePackage.  This is called AFTER the research
    pipeline completes — it's a lightweight format-conversion step that bypasses
    the synthesiser's fixed markdown templates.

    Returns None if the call fails so the caller can fall back to the existing
    markdown parser.
    """
    try:
        import openai  # type: ignore
    except ImportError:
        return None

    llm_cfg = resolve_openai_config(complexity="moderate")
    if not llm_cfg:
        return None

    primary_model = os.getenv("FINAGENT_SYNTH_MODEL") or llm_cfg.model or "gpt-5.4-mini"
    model_candidates = _synth_model_candidates(primary_model)

    effective_content_type = (content_type or req.content_type or "manual").strip().lower()
    label = _label_for_content_type(effective_content_type)
    target_display = req.target[:80]

    # Build IKG context injection
    ikg_block = ""
    if ikg_ctx.get("narrative"):
        ikg_block = (
            f"\n\n[IKG CONTEXT — must be included in article as a dedicated section]\n"
            f"{ikg_ctx['narrative']}\n"
            f"Supporting record identifier: CIN {ikg_ctx.get('cin')}"
        )
    primary_evidence_block = _build_primary_evidence_context(req)
    section_headings = _required_section_headings(effective_content_type)
    heading_line = ", ".join(section_headings)

    system_prompt = (
        "You are a senior financial editor at ProspektLab. Your task is to convert "
        "research notes into a structured JSON article that reads like a top-tier Indian "
        "financial publication and is more informative than a generic broker recap. "
        "SEBI compliance is MANDATORY: Do NOT use the words buy, sell, hold, accumulate, "
        "exit, or include target prices or rebalancing instructions anywhere. "
        "Use only the evidence present in the notes and cite the source of each important number inline. "
        "Do not pad the article with textbook company descriptions or stale market-cap trivia. "
        "Return ONLY valid JSON — no markdown, no code fences, no explanation."
    )

    schema_description = """Return JSON with EXACTLY these fields:
{
  "slug": "<URL-safe identifier, 2-80 chars — use the provided slug>",
  "title": "<SEO title 50-70 chars — include company/topic name>",
  "description": "<meta description 140-170 chars — what the article covers>",
  "hero_eyebrow": "<short category label max 40 chars e.g. Earnings Analysis>",
  "hero_title": "<compelling headline max 100 chars>",
  "hero_summary": "<2-3 engaging sentences 100-300 chars summarising key insight>",
  "audience": "<target reader e.g. Indian retail investors>",
  "keywords": ["<8-12 precise search terms>"],
  "key_takeaways": [
    {"heading": "<short takeaway title>", "detail": "<what changed and why it matters>"}
  ],
  "metrics": [
    {"label": "<metric name>", "value": "<metric value>", "change": "<optional delta>", "period": "<optional period>", "source": "<optional source cue>"}
  ],
  "tables": [
    {"title": "<table title>", "columns": ["<col1>", "<col2>"], "rows": [["<r1c1>", "<r1c2>"]], "footnote": "<optional caveat/source>"}
  ],
  "visuals": [
    {"kind": "bar", "title": "<visual title>", "points": [{"label": "<point>", "value": 123.4}], "note": "<optional visual note>"}
  ],
  "timeline": [
    {"date": "<date label>", "event": "<milestone>", "detail": "<optional detail>", "source": "<optional source>"}
  ],
  "evidence_notes": [
    {"claim": "<claim text>", "source_title": "<source title>", "source_url": "<source url>"}
  ],
  "sections": [
    {
      "heading": "<section title>",
      "paragraphs": ["<paragraph 1>", "<paragraph 2>"],
      "bullets": ["<bullet point 1>", "<bullet point 2>"]
    }
  ],
  "faqs": [
    {"question": "<question retail investors actually ask?>", "answer": "<data-backed answer>"}
  ],
  "cta_label": "<call-to-action text max 40 chars>",
  "cta_href": "/#/contact",
  "image_prompt": "<detailed visual description for cover image generation>"
}

Requirements:
- sections: 5-7 sections with 2-3 paragraphs each (not 1 paragraph). Use ALL research data.
- faqs: 4-5 questions real retail investors ask about this topic
- key_takeaways: 3-6 items
- metrics: 4-8 source-backed items
- tables: at least 1 semantic table when numbers exist
- visuals: at least 1 visual block with numeric points
- timeline: required for regulatory/order topics
- Every factual claim must include the source inline in the text (e.g. "according to NSE filing...")
- Zero filler sentences — every sentence must add information
- SEBI compliance: NO buy/sell/hold/accumulate/exit/target price/rebalancing
- Include ALL significant data points from the research notes"""

    ikg_section_instruction = ""
    if ikg_ctx.get("narrative"):
        ikg_section_instruction = (
            '\n- One section MUST be titled "What the ProspektLab Knowledge Graph shows" '
            "containing the IKG context block provided"
        )
    structure_instruction = _article_structure_brief(
        effective_content_type,
        target_display,
        bool(ikg_ctx.get("narrative")),
    )

    user_prompt = (
        f"Convert the following research notes into a publication-ready financial article.\n\n"
        f"Topic: {target_display}\n"
        f"Content type: {effective_content_type}\n"
        f"Slug to use: {slug}\n"
        f"Category label: {label}\n"
        f"Required section headings (use exact or near-exact wording): {heading_line}\n"
        f"Minimum total body depth target: 1200+ words with concrete evidence density.\n"
        f"{schema_description}{ikg_section_instruction}\n\n"
        f"{structure_instruction}\n\n"
        f"RESEARCH NOTES:\n{memo[:12000]}{ikg_block}\n\n"
        f"PRIMARY EVIDENCE:\n{primary_evidence_block[:12000]}\n\n"
        f"REVISION NOTE:\n{sanitize_public_text(str(revision_note or '')).strip()[:800]}\n\n"
        f"Return ONLY the JSON object. No markdown fences. No explanation."
    )

    client = openai.AsyncOpenAI(api_key=llm_cfg.api_key, base_url=llm_cfg.base_url)
    last_exc: Exception | None = None
    for model_name in model_candidates:
        try:
            response = await client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_completion_tokens=5000,
                response_format={"type": "json_object"},
                timeout=80,
            )
            raw = response.choices[0].message.content or ""
            cleaned = raw.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned, flags=re.MULTILINE)
                cleaned = re.sub(r"\n?```\s*$", "", cleaned)
            data = json.loads(cleaned)
            data = _coerce_article_payload(
                data,
                slug=slug,
                target_display=target_display,
                label=label,
            )
            return ContentArticlePackage.model_validate(data)
        except Exception as exc:
            last_exc = exc
            logger.warning("Direct JSON article call failed on %s: %s", model_name, exc)
            continue
    if last_exc:
        logger.warning("Direct JSON article call exhausted all model candidates: %s", last_exc)
    return None


# ── Scoring ───────────────────────────────────────────────────────────────────

_ADVISORY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(strong buy|buy|accumulate|sell|hold|exit|target price|price target)\b", re.I),
    re.compile(r"\b(undervalued|overvalued|fairly valued)\b", re.I),
)

_NON_ADVISORY_CONTEXT_HINTS: tuple[str, ...] = (
    "not investment advice",
    "does not constitute investment advice",
    "informational purposes only",
    "not a recommendation",
    "no recommendation",
)


def _domain(url: str) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except Exception:
        return ""


def _is_official_source_url(url: str) -> bool:
    host = _domain(url)
    return bool(host) and any(
        host == hint or host.endswith(f".{hint}")
        for hint in _OFFICIAL_DOMAIN_HINTS
    )


def _is_trusted_supporting_source_url(url: str) -> bool:
    host = _domain(url)
    if not host:
        return False
    return any(host == hint or host.endswith(f".{hint}") for hint in _TRUSTED_SUPPORTING_DOMAIN_HINTS)


def _normalise_source_entry(
    *,
    title: str,
    url: str,
    kind: str,
    evidence_type: str,
    snippet: str = "",
) -> dict[str, str]:
    return {
        "title": sanitize_public_text(str(title or "").strip())[:220],
        "url": str(url or "").strip()[:1200],
        "kind": str(kind or "secondary").strip()[:40],
        "evidence_type": str(evidence_type or "supporting").strip()[:80],
        "snippet": sanitize_public_text(str(snippet or "").strip())[:360],
    }


def _dedupe_sources(sources: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for source in sources:
        url = str(source.get("url") or "").strip()
        title = str(source.get("title") or "").strip().lower()
        key = url.lower() if url else f"title:{title}"
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _is_official_update_request(req: FlashGenerationRequest) -> bool:
    if req.source_evidence_meta:
        return True
    source_url = str(req.source_url or "").strip()
    if source_url and _is_official_source_url(source_url):
        return True
    return req.content_type in {"earnings", "sebi"}


def _build_evidence_pack(
    req: FlashGenerationRequest,
    ikg_ctx: dict[str, Any],
    final_event: dict[str, Any],
) -> dict[str, Any]:
    official_evidence: list[dict[str, str]] = []
    supporting_sources: list[dict[str, str]] = []
    research_sources: list[dict[str, str]] = []
    company_context: list[dict[str, str]] = []
    source_candidates: list[dict[str, str]] = []

    meta = req.source_evidence_meta or {}
    source_url = str(req.source_url or "").strip()
    attachment_url = str(meta.get("attachment_url") or "").strip()
    source_page_url = str(meta.get("source_url") or source_url).strip()
    attachment_text = str(meta.get("attachment_text") or "").strip()
    attachment_tables = list(meta.get("attachment_tables") or [])
    attachment_structured_facts = meta.get("attachment_structured_facts")
    source_markdown = str(req.source_markdown or "").strip()

    if source_page_url:
        official_evidence.append(
            _normalise_source_entry(
                title="Official disclosure page",
                url=source_page_url,
                kind="primary_seed",
                evidence_type="official_document",
                snippet=source_markdown[:320],
            )
        )
    if attachment_url:
        official_evidence.append(
            _normalise_source_entry(
                title=f"Official attachment ({str(meta.get('attachment_document_type') or 'document')})",
                url=attachment_url,
                kind="primary_seed",
                evidence_type="official_attachment",
                snippet=attachment_text[:320],
            )
        )

    citation_sources = list(final_event.get("citation_sources") or [])
    for source in citation_sources:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if not url:
            continue
        title = str(source.get("title") or "Research source")
        kind = str(source.get("kind") or "secondary")
        entry = _normalise_source_entry(
            title=title,
            url=url,
            kind=kind,
            evidence_type="trusted_supporting"
            if _is_trusted_supporting_source_url(url)
            else ("official_document" if _is_official_source_url(url) else "research_context"),
        )
        if entry["evidence_type"] == "official_document":
            official_evidence.append(entry)
        elif entry["evidence_type"] == "trusted_supporting":
            supporting_sources.append(entry)
        else:
            research_sources.append(entry)

    if ikg_ctx.get("covered") and (ikg_ctx.get("cin") or ikg_ctx.get("entity")):
        cin = str(ikg_ctx.get("cin") or "")
        company_context.append(
            _normalise_source_entry(
                title="Verified company records",
                url=f"ikg://company/{cin or slugify(req.target)}",
                kind="derived",
                evidence_type="company_context",
                snippet=str(ikg_ctx.get("narrative") or "")[:320],
            )
        )

    source_candidates.extend(official_evidence)
    source_candidates.extend(supporting_sources)
    source_candidates.extend(research_sources)
    source_candidates.extend(company_context)
    source_candidates = _dedupe_sources(source_candidates)
    company_hint = _extract_company_hint(req, meta)
    source_candidates = _filter_sources_for_company(source_candidates, company_hint=company_hint)

    document_status = "ready"
    if req.source_evidence_meta:
        extraction_status = str(meta.get("attachment_extraction_status") or "").strip().lower()
        text_sufficient = bool(meta.get("attachment_text_sufficient"))
        inferred_sufficient = bool(
            text_sufficient
            or attachment_text
            or source_markdown
            or (isinstance(attachment_structured_facts, dict) and len(attachment_structured_facts) > 0)
            or (isinstance(attachment_tables, list) and len(attachment_tables) > 0)
        )
        if extraction_status != "ok" or not inferred_sufficient:
            document_status = "failed"
        elif not attachment_text and not source_markdown and not inferred_sufficient:
            document_status = "insufficient"
    elif _is_official_update_request(req):
        document_status = "missing"

    context_status = "ready" if (ikg_ctx.get("covered") or len(research_sources) >= 2) else "missing"
    research_status = "ready" if citation_sources else "limited"

    return {
        "official_document_evidence": _dedupe_sources(official_evidence),
        "company_context": _dedupe_sources(company_context),
        "research_pipeline_context": _dedupe_sources(research_sources),
        "trusted_supporting_sources": _dedupe_sources(supporting_sources),
        "attachment_tables": attachment_tables[:6],
        "attachment_structured_facts": attachment_structured_facts,
        "sources_used": source_candidates,
        "summary": {
            "document_evidence_status": document_status,
            "context_enrichment_status": context_status,
            "research_context_status": research_status,
            "official_source_count": len(_dedupe_sources(official_evidence)),
            "trusted_supporting_source_count": len(_dedupe_sources(supporting_sources)),
            "research_source_count": len(_dedupe_sources(research_sources)),
            "company_context_count": len(_dedupe_sources(company_context)),
            "source_count": len(source_candidates),
            "attachment_table_count": len(attachment_tables),
            "attachment_structured_fact_count": len(attachment_structured_facts) if isinstance(attachment_structured_facts, dict) else 0,
        },
    }


def _evidence_pack_prompt_block(evidence_pack: dict[str, Any]) -> str:
    summary = evidence_pack.get("summary") or {}
    parts: list[str] = [
        "[EVIDENCE PACK - use this as priority input]",
        (
            f"Document evidence status: {summary.get('document_evidence_status', 'unknown')}; "
            f"Context enrichment status: {summary.get('context_enrichment_status', 'unknown')}; "
            f"Trusted supporting sources: {summary.get('trusted_supporting_source_count', 0)}."
        ),
        (
            "Write with this structure: what happened, why it matters, business context, "
            "financial/regulatory impact, what changed from prior context, watchpoints, and clear limitations. "
            "Also emit structured presentation blocks: key_takeaways, metrics, tables, visuals, timeline, evidence_notes."
        ),
    ]
    if evidence_pack.get("official_document_evidence"):
        source_urls = [str(item.get("url") or "") for item in evidence_pack["official_document_evidence"][:4]]
        parts.append("Official evidence URLs: " + ", ".join(url for url in source_urls if url))
    return "\n".join(part for part in parts if part).strip()


def _extract_numeric_metrics(article: ContentArticlePackage) -> list[dict[str, str]]:
    metrics: list[dict[str, str]] = []
    seen: set[str] = set()
    candidates: list[str] = []
    for section in article.sections:
        candidates.extend(section.bullets)
        candidates.extend(section.paragraphs)
    pattern = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 &/\-]{2,60}):\s*([^()]+?)(?:\s*\(([+\-][^)]+)\))?\s*$")
    for raw in candidates:
        line = sanitize_public_text(str(raw))
        match = pattern.match(line)
        if not match:
            continue
        label = match.group(1).strip()
        value = match.group(2).strip()
        change = (match.group(3) or "").strip()
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        metrics.append({"label": label[:80], "value": value[:80], "change": change[:40]})
        if len(metrics) >= 10:
            break
    return metrics


def _normalize_attachment_tables(meta: dict[str, Any]) -> list[dict[str, Any]]:
    tables = list(meta.get("attachment_tables") or [])
    normalized: list[dict[str, Any]] = []
    for index, table in enumerate(tables[:3], start=1):
        if isinstance(table, dict):
            columns = [sanitize_public_text(str(col))[:80] for col in list(table.get("columns") or [])[:10]]
            rows_raw = list(table.get("rows") or [])
            if not columns and rows_raw and isinstance(rows_raw[0], list):
                columns = [f"Column {i+1}" for i in range(min(10, len(rows_raw[0])))]
            rows: list[list[str]] = []
            for row in rows_raw[:20]:
                if not isinstance(row, list):
                    continue
                rows.append([sanitize_public_text(str(cell))[:140] for cell in row[:10]])
            if columns and rows:
                normalized.append(
                    {
                        "title": sanitize_public_text(str(table.get("title") or f"Attachment table {index}"))[:120],
                        "columns": columns,
                        "rows": rows,
                        "footnote": sanitize_public_text(str(table.get("note") or ""))[:300],
                    }
                )
        elif isinstance(table, list) and table:
            width = min(10, len(table[0]) if isinstance(table[0], list) else 0)
            if width <= 1:
                continue
            columns = [f"Column {i+1}" for i in range(width)]
            rows = []
            for row in table[:20]:
                if isinstance(row, list):
                    rows.append([sanitize_public_text(str(cell))[:140] for cell in row[:width]])
            if rows:
                normalized.append(
                    {
                        "title": f"Attachment table {index}",
                        "columns": columns,
                        "rows": rows,
                        "footnote": "",
                    }
                )
    return normalized


def _normalized_public_text(*values: Any) -> str:
    chunks: list[str] = []
    for value in values:
        if value is None:
            continue
        chunks.append(sanitize_public_text(str(value)))
    return re.sub(r"\s+", " ", " ".join(chunks)).strip().lower()


def _contains_diagnostic_public_text(*values: Any) -> bool:
    text = _normalized_public_text(*values)
    if not text:
        return False
    return any(token in text for token in _DIAGNOSTIC_PUBLIC_TOKENS)


def _is_business_numeric_signal(label: str, value: Any, *context: Any) -> bool:
    value_text = str(value or "")
    if _contains_diagnostic_public_text(label, value_text, *context):
        return False
    match = re.search(r"[-+]?\d*\.?\d+", value_text.replace(",", ""))
    if not match:
        return False
    combined = _normalized_public_text(label, value_text, *context)
    if any(hint in combined for hint in _BUSINESS_NUMERIC_HINTS):
        return True
    if re.search(r"(?:%|bps|crore|cr|lakh|million|billion|mn|bn|rs\.?|inr|usd|\$|₹|x)", value_text.lower()):
        return True
    return False


def _structured_visuals_from_metrics(metrics: list[dict[str, str]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        if not _is_business_numeric_signal(
            str(metric.get("label") or ""),
            metric.get("value"),
            metric.get("source"),
            metric.get("period"),
            metric.get("change"),
        ):
            continue
        value = str(metric.get("value") or "")
        value_clean = value.replace(",", "")
        match = re.search(r"[-+]?\d*\.?\d+", value_clean)
        if not match:
            continue
        try:
            numeric = float(match.group(0))
        except ValueError:
            continue
        points.append({"label": str(metric.get("label") or "")[:30], "value": numeric})
        if len(points) >= 8:
            break
    if len(points) < 2:
        return []
    return [
        {
            "kind": "bar",
            "title": "Quantitative signal map",
            "points": points,
            "note": "Derived from source-backed metrics in this article.",
        }
    ]


def _structured_visuals_from_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for table in tables:
        if not isinstance(table, dict):
            continue
        if _contains_diagnostic_public_text(table.get("title")):
            continue
        columns = list(table.get("columns") or [])
        rows = list(table.get("rows") or [])
        if len(columns) < 2 or len(rows) < 2:
            continue
        points: list[dict[str, Any]] = []
        for row in rows[:8]:
            if not isinstance(row, list) or len(row) < 2:
                continue
            label = sanitize_public_text(str(row[0]))[:30].strip()
            raw = str(row[1]).replace(",", "")
            if not _is_business_numeric_signal(label, raw, table.get("title"), columns):
                continue
            match = re.search(r"[-+]?\d*\.?\d+", raw)
            if not label or not match:
                continue
            try:
                value = float(match.group(0))
            except ValueError:
                continue
            points.append({"label": label, "value": value})
        if len(points) >= 2:
            return [
                {
                    "kind": "bar",
                    "title": sanitize_public_text(str(table.get("title") or "Data trend"))[:120],
                    "points": points,
                    "note": "Visual derived from table values captured in source evidence.",
                }
            ]
    return []


def _inject_structured_presentation(
    article: ContentArticlePackage,
    *,
    req: FlashGenerationRequest,
    evidence_pack: dict[str, Any],
    evidence_claims: list[dict[str, str]],
) -> ContentArticlePackage:
    data = article.model_dump()
    meta = req.source_evidence_meta or {}
    content_type = _effective_content_type(req)

    if not data.get("key_takeaways"):
        takeaways: list[dict[str, str]] = []
        for section in list(data.get("sections") or [])[:4]:
            if not isinstance(section, dict):
                continue
            heading = sanitize_public_text(str(section.get("heading") or "")).strip()
            para = ""
            paragraphs = list(section.get("paragraphs") or [])
            if paragraphs:
                para = sanitize_public_text(str(paragraphs[0]))[:260]
            if heading and para:
                takeaways.append({"heading": heading[:120], "detail": para})
        data["key_takeaways"] = takeaways[:6]

    metrics = list(data.get("metrics") or [])
    clean_metrics: list[dict[str, str]] = []
    seen_metric_keys: set[str] = set()

    def _push_metric(label: str, value: str, change: str = "", period: str = "", source: str = "") -> None:
        label_clean = sanitize_public_text(str(label)).strip()[:80]
        value_clean = sanitize_public_text(str(value)).strip()[:80]
        if not label_clean or not value_clean:
            return
        if _contains_diagnostic_public_text(label_clean, value_clean, change, period, source):
            return
        key = re.sub(r"\W+", " ", label_clean.lower()).strip()
        if not key or key in seen_metric_keys:
            return
        seen_metric_keys.add(key)
        clean_metrics.append(
            {
                "label": label_clean,
                "value": value_clean,
                "change": sanitize_public_text(str(change)).strip()[:40],
                "period": sanitize_public_text(str(period)).strip()[:60],
                "source": sanitize_public_text(str(source)).strip()[:180],
            }
        )

    for metric in metrics[:12]:
        if not isinstance(metric, dict):
            continue
        _push_metric(
            str(metric.get("label") or ""),
            str(metric.get("value") or ""),
            str(metric.get("change") or ""),
            str(metric.get("period") or ""),
            str(metric.get("source") or ""),
        )

    if len(clean_metrics) < 4:
        for metric in _extract_numeric_metrics(article):
            _push_metric(
                str(metric.get("label") or ""),
                str(metric.get("value") or ""),
                str(metric.get("change") or ""),
                str(metric.get("period") or ""),
                str(metric.get("source") or "Derived from article evidence"),
            )
            if len(clean_metrics) >= 10:
                break

    if len(clean_metrics) < 4:
        structured_facts = meta.get("attachment_structured_facts")
        if isinstance(structured_facts, dict):
            for key, value in list(structured_facts.items())[:24]:
                _push_metric(
                    str(key).replace("_", " ").title(),
                    str(value),
                    "",
                    "",
                    "Attachment facts",
                )
                if len(clean_metrics) >= 10:
                    break

    if len(clean_metrics) < 4:
        claim_pattern = re.compile(
            r"([A-Za-z][A-Za-z0-9 /&().%-]{3,70})\s*[:\-]\s*([\-+]?[\d,]+(?:\.\d+)?(?:\s*(?:%|bps|x|crore|cr|lakh|million|billion|bn|mn))?)",
            re.IGNORECASE,
        )
        for claim in evidence_claims:
            text = sanitize_public_text(str(claim.get("claim") or ""))
            match = claim_pattern.search(text)
            if not match:
                continue
            _push_metric(
                match.group(1),
                match.group(2),
                "",
                "",
                str(claim.get("source_title") or claim.get("source_url") or "Evidence note"),
            )
            if len(clean_metrics) >= 10:
                break

    metrics = clean_metrics[:10]
    data["metrics"] = metrics

    tables = list(data.get("tables") or [])
    filtered_existing_tables: list[dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        title = sanitize_public_text(str(table.get("title") or "")).strip()[:120]
        if _contains_diagnostic_public_text(title):
            continue
        columns = [sanitize_public_text(str(col)).strip()[:80] for col in list(table.get("columns") or [])[:10]]
        rows: list[list[str]] = []
        for row in list(table.get("rows") or [])[:20]:
            if not isinstance(row, list):
                continue
            cleaned = [sanitize_public_text(str(cell)).strip()[:140] for cell in row[:10]]
            if _contains_diagnostic_public_text(title, columns, cleaned):
                continue
            rows.append(cleaned)
        if len(columns) < 2 or len(rows) < 1:
            continue
        if not any(
            _is_business_numeric_signal(str(row[0] if row else ""), str(row[1] if len(row) > 1 else ""), title, columns)
            for row in rows
        ):
            continue
        filtered_existing_tables.append(
            {
                "title": title,
                "columns": columns,
                "rows": rows,
                "footnote": sanitize_public_text(str(table.get("footnote") or ""))[:300],
            }
        )
    tables = filtered_existing_tables
    existing_rows = sum(len(list(table.get("rows") or [])) for table in tables if isinstance(table, dict))
    if not tables or existing_rows < 2:
        attachment_tables = _normalize_attachment_tables(meta)
        if attachment_tables:
            tables = attachment_tables[:3]
        elif metrics:
            rows = [
                [str(metric.get("label") or ""), str(metric.get("value") or ""), str(metric.get("change") or "")]
                for metric in metrics[:10]
            ]
            tables = [{
                "title": "Key reported metrics",
                "columns": ["Metric", "Value", "Change"],
                "rows": rows,
                "footnote": "Compiled from source-backed metrics in this article.",
            }]
    data["tables"] = tables

    visuals = list(data.get("visuals") or [])
    filtered_existing_visuals: list[dict[str, Any]] = []
    for visual in visuals:
        if not isinstance(visual, dict):
            continue
        title = sanitize_public_text(str(visual.get("title") or ""))[:120]
        note = sanitize_public_text(str(visual.get("note") or ""))[:220]
        if _contains_diagnostic_public_text(title, note):
            continue
        points_raw = list(visual.get("points") or [])
        points: list[dict[str, Any]] = []
        for point in points_raw[:12]:
            if not isinstance(point, dict):
                continue
            label = sanitize_public_text(str(point.get("label") or ""))[:80]
            value = point.get("value")
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if not _is_business_numeric_signal(label, numeric, title, note):
                continue
            points.append({"label": label, "value": numeric})
        if len(points) < 2:
            continue
        filtered_existing_visuals.append(
            {
                "kind": sanitize_public_text(str(visual.get("kind") or "bar"))[:20] or "bar",
                "title": title or "Data trend",
                "points": points,
                "note": note,
            }
        )
    visuals = filtered_existing_visuals
    if not visuals:
        visuals = _structured_visuals_from_metrics(metrics)
    if not visuals:
        visuals = _structured_visuals_from_tables(tables)
    data["visuals"] = visuals

    timeline = list(data.get("timeline") or [])
    if not timeline and content_type in {"sebi", "earnings", "company"}:
        timeline = [{
            "date": datetime.now(timezone.utc).date().isoformat(),
            "event": "Latest filing/update processed",
            "detail": sanitize_public_text(req.target)[:180],
            "source": str(req.source_url or meta.get("source_url") or "")[:180],
        }]
        data["timeline"] = timeline

    if not data.get("evidence_notes"):
        notes = []
        for claim in evidence_claims[:10]:
            notes.append(
                {
                    "claim": sanitize_public_text(str(claim.get("claim") or ""))[:420],
                    "source_title": sanitize_public_text(str(claim.get("source_title") or ""))[:220],
                    "source_url": str(claim.get("source_url") or "")[:1200],
                }
            )
        data["evidence_notes"] = notes

    # Ensure missing research dimensions are explicitly covered in output structure.
    try:
        staged = ContentArticlePackage.model_validate(data)
        coverage = _research_dimension_coverage(staged)
        section_dicts = list(data.get("sections") or [])
        if not coverage.get("historical"):
            section_dicts.append(
                {
                    "heading": "Historical context and trendline",
                    "paragraphs": [
                        f"This update is interpreted against prior disclosed context for {sanitize_public_text(req.target)[:120]}, not as a standalone headline.",
                        "Readers should compare this filing with prior quarter disclosures, management commentary, and earlier governance signals to assess trajectory.",
                    ],
                    "bullets": [
                        "Track YoY and QoQ continuity where numeric disclosures are available.",
                        "Verify whether prior stated assumptions remain valid in this update.",
                    ],
                }
            )
        if not coverage.get("sentiment"):
            section_dicts.append(
                {
                    "heading": "Sentiment and narrative read-through",
                    "paragraphs": [
                        "Narrative risk is evaluated from disclosure tone, follow-on coverage patterns, and the balance between official facts and market interpretation.",
                        "This section avoids price calls and focuses on what sentiment signals may imply for risk perception and information efficiency.",
                    ],
                    "bullets": [
                        "Separate filing-confirmed facts from commentary-driven market narratives.",
                        "Watch for contradiction between management messaging and subsequent disclosures.",
                    ],
                }
            )
        if not coverage.get("watchpoints"):
            section_dicts.append(
                {
                    "heading": "What to monitor next quarter",
                    "paragraphs": [
                        "The next disclosure cycle should be monitored for execution confirmation, guidance consistency, and governance continuity.",
                        "If new filings alter assumptions used in this article, the thesis should be updated with fresh evidence.",
                    ],
                    "bullets": [
                        "Management follow-through vs announced intent.",
                        "Any new regulatory or compliance disclosures.",
                        "Change in key operating or funding indicators.",
                    ],
                }
            )
        data["sections"] = section_dicts[:10]
    except Exception:
        pass

    return ContentArticlePackage.model_validate(data)


def _article_word_count(article: ContentArticlePackage) -> int:
    chunks: list[str] = [article.title, article.description, article.hero_summary]
    for takeaway in article.key_takeaways:
        chunks.append(takeaway.heading)
        chunks.append(takeaway.detail)
    for metric in article.metrics:
        chunks.append(metric.label)
        chunks.append(metric.value)
        chunks.append(metric.change)
        chunks.append(metric.period)
        chunks.append(metric.source)
    for table in article.tables:
        chunks.append(table.title)
        chunks.extend(table.columns)
        for row in table.rows:
            chunks.extend(str(cell) for cell in row)
        chunks.append(table.footnote)
    for visual in article.visuals:
        chunks.append(visual.title)
        chunks.append(visual.note)
        for point in visual.points:
            chunks.append(point.label)
            chunks.append(str(point.value))
    for event in article.timeline:
        chunks.append(event.date)
        chunks.append(event.event)
        chunks.append(event.detail)
        chunks.append(event.source)
    for note in article.evidence_notes:
        chunks.append(note.claim)
        chunks.append(note.source_title)
        chunks.append(note.source_url)
    chunks.extend(section.heading for section in article.sections)
    for section in article.sections:
        chunks.extend(section.paragraphs)
        chunks.extend(section.bullets)
    for faq in article.faqs:
        chunks.append(faq.question)
        chunks.append(faq.answer)
    return len(re.findall(r"\b[\w%-]+\b", " ".join(chunks)))


def _substantive_section_count(article: ContentArticlePackage) -> int:
    count = 0
    for section in article.sections:
        para_words = sum(len(re.findall(r"\b[\w%-]+\b", paragraph)) for paragraph in section.paragraphs)
        bullet_words = sum(len(re.findall(r"\b[\w%-]+\b", bullet)) for bullet in section.bullets)
        if len(section.paragraphs) >= 2 and (para_words + bullet_words) >= 55:
            count += 1
    return count


def _article_plain_text(article: ContentArticlePackage) -> str:
    parts = [article.title, article.description, article.hero_summary]
    for takeaway in article.key_takeaways:
        parts.append(takeaway.heading)
        parts.append(takeaway.detail)
    for metric in article.metrics:
        parts.append(metric.label)
        parts.append(metric.value)
        parts.append(metric.change)
    for table in article.tables:
        parts.append(table.title)
        parts.extend(table.columns)
        for row in table.rows:
            parts.extend(str(cell) for cell in row)
    for visual in article.visuals:
        parts.append(visual.title)
        parts.extend(point.label for point in visual.points)
    for event in article.timeline:
        parts.append(event.date)
        parts.append(event.event)
        parts.append(event.detail)
    for note in article.evidence_notes:
        parts.append(note.claim)
        parts.append(note.source_title)
    for section in article.sections:
        parts.append(section.heading)
        parts.extend(section.paragraphs)
        parts.extend(section.bullets)
    for faq in article.faqs:
        parts.append(faq.question)
        parts.append(faq.answer)
    return "\n".join(part for part in parts if part).strip()


def _advisory_language_present(article: ContentArticlePackage) -> bool:
    # Ignore FAQ disclaimers; enforce advisory policy on analytical copy.
    parts: list[str] = [article.title, article.description, article.hero_summary]
    for takeaway in article.key_takeaways:
        parts.append(takeaway.heading)
        parts.append(takeaway.detail)
    for section in article.sections:
        parts.append(section.heading)
        parts.extend(section.paragraphs)
        parts.extend(section.bullets)
    for note in article.evidence_notes:
        parts.append(note.claim)

    text = "\n".join(part for part in parts if part)
    lowered = text.lower()
    for pattern in _ADVISORY_PATTERNS:
        for match in pattern.finditer(text):
            left = max(0, match.start() - 80)
            right = min(len(lowered), match.end() + 80)
            window = lowered[left:right]
            if any(hint in window for hint in _NON_ADVISORY_CONTEXT_HINTS):
                continue
            return True
    return False


def _split_sentences(text: str, *, max_count: int = 80) -> list[str]:
    if not text:
        return []
    cleaned = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    sentences = [part.strip() for part in parts if len(part.strip()) >= 24]
    return sentences[:max_count]


def _pick_claim_source(claim: str, evidence_pack: dict[str, Any]) -> dict[str, str] | None:
    lower = claim.lower()
    official = list(evidence_pack.get("official_document_evidence") or [])
    trusted = list(evidence_pack.get("trusted_supporting_sources") or [])
    research = list(evidence_pack.get("research_pipeline_context") or [])
    company = list(evidence_pack.get("company_context") or [])

    if any(token in lower for token in ("sebi", "nse", "bse", "disclosure", "filing", "order", "adjudication")) and official:
        return official[0]
    if any(token in lower for token in ("promoter", "governance", "ownership", "related party", "auditor")) and company:
        return company[0]
    if trusted:
        return trusted[0]
    if official:
        return official[0]
    if research:
        return research[0]
    if company:
        return company[0]
    return None


def _build_evidence_claims(article: ContentArticlePackage, evidence_pack: dict[str, Any]) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    seen_claims: set[str] = set()
    text = _article_plain_text(article)
    for sentence in _split_sentences(text, max_count=140):
        claim = sentence.strip()
        claim_key = re.sub(r"\W+", " ", claim.lower()).strip()
        if len(claim_key) < 30 or claim_key in seen_claims:
            continue
        if not re.search(r"\d", claim) and not any(pattern.search(claim) for pattern in _SOURCE_SIGNAL_PATTERNS):
            continue
        source = _pick_claim_source(claim, evidence_pack)
        if not source:
            continue
        seen_claims.add(claim_key)
        claims.append(
            {
                "claim": sanitize_public_text(claim)[:420],
                "source_url": str(source.get("url") or "")[:1200],
                "source_title": sanitize_public_text(str(source.get("title") or ""))[:220],
                "evidence_type": str(source.get("evidence_type") or "supporting"),
                "evidence_snippet": sanitize_public_text(str(source.get("snippet") or ""))[:380],
            }
        )
        if len(claims) >= 28:
            break
    return claims


def _compute_depth_score(article: ContentArticlePackage) -> int:
    section_count = len(article.sections)
    paragraph_count = sum(len(section.paragraphs) for section in article.sections)
    words = _article_word_count(article)
    substantive_sections = _substantive_section_count(article)
    score = 0.0
    score += min(section_count, 9) / 9 * 32
    score += min(paragraph_count, 24) / 24 * 28
    score += min(substantive_sections, 8) / 8 * 25
    score += min(words, 1600) / 1600 * 15
    return int(round(min(score, 100)))


def _compute_source_score(sources_used: list[dict[str, str]], editorial_source_score: int) -> int:
    if not sources_used:
        return 0
    source_count = len(sources_used)
    unique_domains = {domain for domain in (_domain(item.get("url") or "") for item in sources_used) if domain}
    official_sources = sum(1 for source in sources_used if _is_official_source_url(str(source.get("url") or "")))
    trusted_sources = sum(1 for source in sources_used if _is_trusted_supporting_source_url(str(source.get("url") or "")))

    base = 0.0
    base += min(source_count, 8) / 8 * 32
    base += min(len(unique_domains), 6) / 6 * 28
    base += min(official_sources, 2) / 2 * 24
    base += min(trusted_sources, 4) / 4 * 16
    weighted = int(round((base * 0.65) + (max(0, min(editorial_source_score, 100)) * 0.35)))
    return min(weighted, 100)


def _compute_evidence_score(
    evidence_pack: dict[str, Any],
    evidence_claims: list[dict[str, str]],
    *,
    is_official_update: bool,
) -> int:
    summary = evidence_pack.get("summary") or {}
    score = 0.0
    if summary.get("document_evidence_status") == "ready":
        score += 38
    elif summary.get("document_evidence_status") == "insufficient":
        score += 16
    elif not is_official_update:
        score += 20
    if summary.get("context_enrichment_status") == "ready":
        score += 20
    score += min(int(summary.get("trusted_supporting_source_count") or 0), 4) / 4 * 16
    score += min(int(summary.get("source_count") or 0), 8) / 8 * 14
    score += min(len(evidence_claims), 16) / 16 * 12
    return int(round(min(score, 100)))


def _unsupported_claims_present(
    article: ContentArticlePackage,
    evidence_claims: list[dict[str, str]],
    sources_used: list[dict[str, str]],
) -> bool:
    text = _article_plain_text(article)
    numeric_sentences = [
        sentence for sentence in _split_sentences(text, max_count=220)
        if re.search(r"\d", sentence)
    ]
    if numeric_sentences and not sources_used:
        return True
    if len(numeric_sentences) >= 6 and len(evidence_claims) < max(4, len(numeric_sentences) // 3):
        return True
    return False


def _structured_presentation_counts(article: ContentArticlePackage) -> dict[str, int]:
    table_count = len(article.tables or [])
    table_rows = sum(len(table.rows or []) for table in (article.tables or []))
    metric_count = len(article.metrics or [])
    visual_count = len(article.visuals or [])
    timeline_count = len(article.timeline or [])
    evidence_note_count = len(article.evidence_notes or [])
    return {
        "table_count": table_count,
        "table_rows": table_rows,
        "metric_count": metric_count,
        "visual_count": visual_count,
        "timeline_count": timeline_count,
        "evidence_note_count": evidence_note_count,
    }


def _research_dimension_coverage(article: ContentArticlePackage) -> dict[str, bool]:
    headings = " ".join(str(section.heading or "") for section in article.sections).lower()
    body = _article_plain_text(article).lower()
    return {
        "historical": any(token in body for token in ("historical", "previous quarter", "yoy", "qoq", "year-on-year")),
        "management": any(token in body for token in ("management", "concall", "guidance", "analyst meet", "investor meet")),
        "sentiment": any(token in body for token in ("sentiment", "market reaction", "investor reaction", "narrative")),
        "governance": any(token in body for token in ("governance", "regulatory", "sebi", "compliance", "promoter")),
        "watchpoints": any(token in headings or token in body for token in ("watch", "monitor", "what to track", "next quarter")),
    }


def _evidence_has_numeric_signals(evidence_pack: dict[str, Any], evidence_claims: list[dict[str, str]]) -> bool:
    summary = evidence_pack.get("summary") or {}
    if int(summary.get("attachment_table_count") or 0) > 0:
        return True
    if int(summary.get("attachment_structured_fact_count") or 0) > 0:
        return True
    for claim in evidence_claims:
        claim_text = str(claim.get("claim") or "")
        if _contains_diagnostic_public_text(claim_text):
            continue
        if re.search(r"\d", claim_text) and _is_business_numeric_signal(
            str(claim.get("source_title") or "Evidence"),
            claim_text,
            claim.get("source_url"),
        ):
            return True
    return False


def _evaluate_publish_gate(
    *,
    req: FlashGenerationRequest,
    article: ContentArticlePackage,
    editorial_review: Any,
    quality_score: float,
    evidence_pack: dict[str, Any],
    evidence_claims: list[dict[str, str]],
) -> dict[str, Any]:
    is_official_update = _is_official_update_request(req)
    effective_content_type = _effective_content_type(req)
    sources_used = _dedupe_sources(list(evidence_pack.get("sources_used") or []))
    word_count = _article_word_count(article)
    section_count = len(article.sections)
    substantive_sections = _substantive_section_count(article)
    editorial_score = int(getattr(editorial_review, "total_score", 0) or 0)
    editorial_source_score = int(getattr(editorial_review, "source_score", 0) or 0)
    depth_score = _compute_depth_score(article)
    source_score = _compute_source_score(sources_used, editorial_source_score)
    evidence_score = _compute_evidence_score(
        evidence_pack,
        evidence_claims,
        is_official_update=is_official_update,
    )
    structured_counts = _structured_presentation_counts(article)
    research_dimensions = _research_dimension_coverage(article)
    numeric_evidence_present = _evidence_has_numeric_signals(evidence_pack, evidence_claims)
    confidence = int(
        round(
            max(0.0, min(quality_score, 100.0)) * 0.15
            + editorial_score * 0.35
            + source_score * 0.20
            + depth_score * 0.15
            + evidence_score * 0.15
        )
    )
    confidence = max(0, min(confidence, 100))

    reasons: list[str] = []
    article_text = _article_plain_text(article)
    lower_text = article_text.lower()

    summary = evidence_pack.get("summary") or {}
    if not sources_used:
        reasons.append("missing_source_evidence")
    if not evidence_claims:
        reasons.append("missing_evidence_claims")
    if is_official_update and str(summary.get("document_evidence_status") or "") != "ready":
        reasons.append("missing_official_document_evidence")
    if is_official_update and word_count < 1200:
        reasons.append("official_article_too_short")
    if effective_content_type in {"earnings", "company", "trend"} and word_count < 1300:
        reasons.append("research_article_too_short")
    if substantive_sections < 6:
        reasons.append("insufficient_substantive_sections")
    if contains_internal_language(article_text):
        reasons.append("internal_language")
    if _advisory_language_present(article):
        reasons.append("advisory_language")
    limited_data_hits = sum(1 for pattern in _LIMITED_DATA_PATTERNS if pattern.search(article_text))
    if limited_data_hits >= 2:
        reasons.append("limited_data_copy")
    filler_hits = sum(1 for pattern in _FILLER_PATTERNS if pattern.search(lower_text))
    if filler_hits >= 2:
        reasons.append("filler_copy")
    if _unsupported_claims_present(article, evidence_claims, sources_used):
        reasons.append("unsupported_claims")
    if is_official_update and str(summary.get("context_enrichment_status") or "") != "ready":
        reasons.append("context_enrichment_missing")
    if is_official_update and word_count < 700:
        reasons.append("insufficient_structured_evidence")
    if effective_content_type in {"earnings", "sebi", "company"} and numeric_evidence_present:
        if structured_counts["table_count"] == 0 or structured_counts["table_rows"] == 0:
            reasons.append("missing_metrics_table")
        if structured_counts["visual_count"] == 0:
            reasons.append("visual_block_not_available")
    if effective_content_type == "sebi" and structured_counts["timeline_count"] == 0:
        reasons.append("timeline_missing")
    if numeric_evidence_present and structured_counts["metric_count"] < 3:
        reasons.append("insufficient_metric_coverage")
    if numeric_evidence_present and structured_counts["evidence_note_count"] == 0:
        reasons.append("missing_evidence_notes")
    if effective_content_type in {"earnings", "company", "sebi", "trend"}:
        missing_dimensions = [name for name, present in research_dimensions.items() if not present]
        if "historical" in missing_dimensions:
            reasons.append("missing_company_history")
        if "management" in missing_dimensions:
            reasons.append("missing_management_context")
        if len(missing_dimensions) >= 3:
            reasons.append("missing_research_dimensions")

    threshold_checks = {
        "publish_gate_score": confidence >= _PUBLISH_GATE_THRESHOLDS["publish_gate_score"],
        "confidence": confidence >= _PUBLISH_GATE_THRESHOLDS["confidence"],
        "editorial_score": editorial_score >= _PUBLISH_GATE_THRESHOLDS["editorial_score"],
        "source_score": source_score >= _PUBLISH_GATE_THRESHOLDS["source_score"],
        "depth_score": depth_score >= _PUBLISH_GATE_THRESHOLDS["depth_score"],
        "evidence_score": evidence_score >= _PUBLISH_GATE_THRESHOLDS["evidence_score"],
    }
    for metric, passed in threshold_checks.items():
        if not passed:
            reasons.append(f"{metric}_below_threshold")

    if not bool(getattr(editorial_review, "ready_to_publish", False)):
        reasons.append("editorial_revision_pending")

    unique_reasons: list[str] = []
    for reason in reasons:
        if reason not in unique_reasons:
            unique_reasons.append(reason)

    publish = not unique_reasons
    review_reason = "" if publish else unique_reasons[0]

    metrics = {
        "confidence": confidence,
        "editorial_score": editorial_score,
        "source_score": source_score,
        "depth_score": depth_score,
        "evidence_score": evidence_score,
        "word_count": word_count,
        "section_count": section_count,
        "substantive_sections": substantive_sections,
        "source_count": len(sources_used),
        "evidence_claim_count": len(evidence_claims),
        "official_source_count": int(summary.get("official_source_count") or 0),
        "trusted_supporting_source_count": int(summary.get("trusted_supporting_source_count") or 0),
        "document_evidence_status": str(summary.get("document_evidence_status") or ""),
        "context_enrichment_status": str(summary.get("context_enrichment_status") or ""),
        "research_context_status": str(summary.get("research_context_status") or ""),
        "table_count": structured_counts["table_count"],
        "table_rows": structured_counts["table_rows"],
        "metric_count": structured_counts["metric_count"],
        "visual_count": structured_counts["visual_count"],
        "timeline_count": structured_counts["timeline_count"],
        "evidence_note_count": structured_counts["evidence_note_count"],
        "numeric_evidence_present": numeric_evidence_present,
        "research_dimensions": research_dimensions,
        "content_type": effective_content_type,
        "is_official_update": is_official_update,
    }

    return {
        "status": "publish" if publish else "draft",
        "score": confidence,
        "reasons": unique_reasons,
        "metrics": metrics,
        "review_reason": review_reason,
        "sources_used": sources_used,
    }


# ── Core generation function ──────────────────────────────────────────────────

async def generate_flash_article(
    req: FlashGenerationRequest,
    *,
    job_id: str,
    requested_by: str,
) -> ContentAutomationResult:
    """
    Run the flash/deep content pipeline and produce a publishable article.
    Called from the async background task started by POST /api/content/flash/generate.
    """
    route_base = _safe_route_base(req.route_base)
    effective_content_type = _effective_content_type(req)
    ikg_target = _normalise_ikg_target(req.target, effective_content_type)
    editorial_mode = "research"

    # Build slug from target + content_type
    slug_src = req.objective[:80] if req.objective else req.target[:80]
    slug = slugify(f"{req.content_type}-{slug_src}")

    # Return existing if no overwrite
    if not req.overwrite:
        from finagent.content_automation import load_generated_article
        existing = load_generated_article(slug, route_base=route_base)
        if existing:
            return ContentAutomationResult.model_validate(existing)

    if req.mode == "flash":
        objectives = _CONTENT_FLASH_OBJECTIVES
        wall_limit = _FLASH_WALL_SECONDS
    else:
        objectives = _CONTENT_DEEP_OBJECTIVES
        wall_limit = _DEEP_WALL_SECONDS
    total_passes = len(objectives)

    BUS.emit(
        job_id, "phase",
        phase="content_generation",
        note=f"{req.mode.upper()} mode — {total_passes} passes for '{req.target[:60]}'",
    )

    # ── IKG context (parallel pre-fetch) ─────────────────────────────────────
    ikg_ctx: dict[str, Any] = {}
    if ikg_target:
        try:
            ikg_ctx = await _build_ikg_context(ikg_target)
            if ikg_ctx.get("covered"):
                BUS.emit(job_id, "log", source="flash_engine", level="info",
                         message=f"Verified record coverage found: CIN={ikg_ctx.get('cin')} target='{ikg_target}'")
            else:
                BUS.emit(job_id, "log", source="flash_engine", level="info",
                         message=f"IKG not covering '{req.target}' — proceeding without IKG block")
        except Exception as exc:
            logger.warning("Verified records context failed: %s", exc)

    # ── Assemble enriched base objective ─────────────────────────────────────
    type_prefix_map = {
        "earnings": (
            f"Earnings analysis: '{req.target}'. "
            "Focus: quarterly/annual results, what changed versus the previous quarter and year, "
            "segment and geography drivers, margins, cash conversion, hiring/attrition, order book, "
            "and management commentary from official materials."
        ),
        "sebi": (
            f"SEBI regulatory article: '{req.target}'. "
            "Focus: the order timeline, enforcement actions, compliance implications, market impact, investor relevance, "
            "and whether this changes the risk profile or disclosure burden."
        ),
        "trend": (
            f"Market trend analysis: '{req.target}'. "
            "Focus: sector dynamics, macro drivers, institutional flows, thematic catalysts, official policy signals, "
            "and the listed companies most affected."
        ),
        "company": (
            f"Company intelligence article: '{req.target}'. "
            "Focus: business model, financials, governance, risks, catalysts, market positioning."
        ),
        "manual": (
            f"Financial article: '{req.target}'. "
            "Infer whether this is best treated as an earnings, company, or market-structure story and write accordingly."
        ),
    }
    base_obj = req.objective or type_prefix_map.get(effective_content_type, f"Article: '{req.target}'")
    initial_evidence_pack = _build_evidence_pack(req, ikg_ctx, {})

    extra_ctx = ""
    if req.source_markdown:
        extra_ctx += f"\n\n[PRIMARY SOURCE MATERIAL]\n{req.source_markdown[:14000]}"
    if req.source_evidence_meta:
        evidence_meta = {
            "document_type": req.source_evidence_meta.get("attachment_document_type"),
            "parser": req.source_evidence_meta.get("attachment_parser"),
            "attachment_required": req.source_evidence_meta.get("attachment_required"),
            "extraction_status": req.source_evidence_meta.get("attachment_extraction_status"),
            "sufficiency_reason": req.source_evidence_meta.get("attachment_sufficiency_reason"),
            "source_uid": req.source_evidence_meta.get("source_uid"),
        }
        extra_ctx += f"\n\n[PRIMARY SOURCE PROVENANCE]\n{json.dumps(evidence_meta, ensure_ascii=True, default=str)}"
    if req.source_url:
        extra_ctx += f"\n\n[SOURCE URL]: {req.source_url}"
    if ikg_ctx.get("narrative"):
        extra_ctx += (
            f"\n\n[COMPANY CONTEXT - complementary background only]\n{ikg_ctx['narrative']}\n"
            f"Context source: verified company records (CIN: {ikg_ctx.get('cin')})"
        )
    evidence_prompt_block = _evidence_pack_prompt_block(initial_evidence_pack)
    if evidence_prompt_block:
        extra_ctx += f"\n\n{evidence_prompt_block}"

    enriched_objective = base_obj + extra_ctx

    synth_model = os.getenv("FINAGENT_SYNTH_MODEL") or "gpt-5.4-mini"
    fast_model = os.getenv("FINAGENT_SYNTH_MODEL_FAST") or "gpt-5.4-mini"

    # ── Pass runner ───────────────────────────────────────────────────────────
    async def _run_pass(i: int) -> None:
        is_last = (i == total_passes - 1)
        pass_label = "Final synthesis" if is_last else f"Research pass {i + 1}/{total_passes - 1}"
        pass_obj = objectives[i]

        BUS.emit(job_id, "flash_pass",
                 pass_number=i + 1,
                 total_passes=total_passes,
                 objective=pass_obj[:80],
                 label=pass_label,
                 status="running")

        cfg = AgentLoopConfig(
            max_steps=32 if is_last else 16,
            session_id=job_id,
            auto_depth=False,
            # Content generation is not a user chat session
            enable_memory=False,
            memory_recall_limit=0,
            enable_reflection=is_last,
            reflection_max_rounds=2 if is_last else 0,
            quality_threshold=70.0,
            reflection_per_query_limit=3 if is_last else 0,
            reflection_max_new_docs=24 if is_last else 0,
            reflection_max_queries_per_round=3 if is_last else 0,
            reflection_wall_clock_seconds=40.0 if is_last else 0.0,
            reflection_early_accept_margin=2.0,
            reflection_min_score_gain=0.75,
            enable_multi_agent=True,
            agent_deadline_ms=42_000 if is_last else 22_000,
            # Blindspot pass only on synthesis
            enable_blindspot=is_last,
            blindspot_max_queries=4 if is_last else 0,
            blindspot_per_query_timeout=15.0,
            # Models
            synth_model=synth_model if is_last else fast_model,
            response_depth="deep" if is_last else "standard",
            # For synthesis pass: output_mode=None so the objective text drives
            # format (the objective explicitly asks for JSON). Using "news_brief"
            # was causing the synthesiser's template to override the JSON instruction
            # and produce markdown instead of ContentArticlePackage JSON.
            output_mode=(
                None if is_last  # synthesis pass — objective drives JSON format
                else None  # research passes — no template override needed
            ),
            emit_memo=is_last,
            close_bus_on_finish=False,
            # Timeouts — tighter than full deep research
            breadth_search_timeout=70.0 if is_last else 22.0,
            followup_search_timeout=28.0 if is_last else 8.0,
            news_timeout=16.0 if is_last else 5.0,
            fast_mode=False,
            peer_targets=[],
            user_email=requested_by,
        )

        full_obj = f"{enriched_objective}\n\n{pass_label} — {pass_obj}"
        await run_research_session(
            req.target,
            full_obj,
            loop_config=cfg,
            is_followup=(i > 0),
        )

        BUS.emit(job_id, "flash_pass",
                 pass_number=i + 1,
                 total_passes=total_passes,
                 objective=pass_obj[:80],
                 label=pass_label,
                 status="done")

    # ── Execute passes ────────────────────────────────────────────────────────
    started_at = asyncio.get_running_loop().time()
    parallel_count = total_passes - 1

    if parallel_count > 0:
        BUS.emit(job_id, "phase", phase="content_generation",
                 note=f"Running {parallel_count} research passes in parallel")
        parallel_tasks = [asyncio.create_task(_run_pass(i)) for i in range(parallel_count)]
        parallel_results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
        for outcome in parallel_results:
            if isinstance(outcome, Exception):
                logger.warning("Research pass failed for job %s: %s", job_id, outcome)
                BUS.emit(job_id, "log", source="flash_engine", level="warning",
                         message=f"Research pass failed but synthesis will continue: {outcome}")

    elapsed = asyncio.get_running_loop().time() - started_at
    if elapsed > wall_limit:
        logger.warning(
            "Flash job %s hit wall limit %.0fs — synthesising with available context", job_id, wall_limit
        )

    await asyncio.sleep(0.3)
    BUS.emit(job_id, "phase", phase="content_generation", note="Running final article synthesis")
    await _run_pass(total_passes - 1)

    # ── Harvest memo + quality score ──────────────────────────────────────────
    memo = _harvest_memo(job_id)
    final_event = _harvest_final_event(job_id)
    quality_score = float(final_event.get("quality_score") or 0)
    evidence_pack = _build_evidence_pack(req, ikg_ctx, final_event)

    BUS.emit(job_id, "log", source="flash_engine", level="info",
             message=f"Synthesis complete — quality={quality_score:.1f}, memo_len={len(memo)}")

    # ── Assemble article ─────────────────────────────────────────────────────
    # Primary path: direct JSON call to OpenAI (structured article from research memo)
    # This bypasses the synthesiser's fixed markdown templates and produces proper
    # ContentArticlePackage JSON using the collected research as context.
    BUS.emit(job_id, "phase", phase="content_generation", note="Formatting article as structured JSON")
    article = await _direct_json_article_call(memo, ikg_ctx, req, slug, effective_content_type)

    if article is None:
        # Fallback: parse markdown memo into sections
        BUS.emit(job_id, "log", source="flash_engine", level="warning",
                 message="Direct JSON call failed — using markdown parser fallback")
        article = _assemble_article_from_pipeline(memo, ikg_ctx, req, slug, quality_score, effective_content_type)
    else:
        BUS.emit(job_id, "log", source="flash_engine", level="info",
                 message=f"Article JSON ready — {len(article.sections)} sections, {len(article.faqs)} FAQs")
    article = sanitize_article_package(article)
    baseline_words = _article_word_count(article)
    needs_revision = (
        baseline_words < 1100
        or len(article.sections) < 6
        or len(article.metrics) < 4
        or len(article.visuals) == 0
    )
    if needs_revision:
        BUS.emit(
            job_id,
            "log",
            source="flash_engine",
            level="info",
            message=(
                "Initial structured draft is thin; running one guided revision pass for depth, "
                "metrics coverage, and clearer watchpoints."
            ),
        )
        revision_note = (
            "Expand this into a full research article. Remove weak boilerplate and missing-data filler. "
            "Use concrete evidence and include historical framing, management commentary, market-sentiment read-through, "
            "governance or regulatory implications, and explicit watchpoints for next quarter. "
            "Ensure metrics >= 4, at least one meaningful table, and at least one numeric visual block."
        )
        revised_article = await _direct_json_article_call(
            memo,
            ikg_ctx,
            req,
            slug,
            effective_content_type,
            revision_note=revision_note,
        )
        if revised_article is not None:
            revised_article = sanitize_article_package(revised_article)
            revised_words = _article_word_count(revised_article)
            if (
                revised_words >= baseline_words
                or len(revised_article.metrics) > len(article.metrics)
                or len(revised_article.visuals) > len(article.visuals)
            ):
                article = revised_article
                BUS.emit(
                    job_id,
                    "log",
                    source="flash_engine",
                    level="info",
                    message=(
                        f"Guided revision accepted (words {baseline_words} -> {revised_words}; "
                        f"metrics {len(article.metrics)}; visuals {len(article.visuals)})."
                    ),
                )
    BUS.emit(job_id, "phase", phase="content_generation", note="Running editorial review and revision")
    article, editorial_review = await run_editorial_revision_loop(article, target=req.target, max_rounds=4)
    article = sanitize_article_package(article)
    editorial_score = editorial_review.total_score
    urgency_score = editorial_review.urgency_score
    combined_quality = int(round((max(quality_score, 0.0) * 0.30) + (editorial_score * 0.70)))
    evidence_claims = _build_evidence_claims(article, evidence_pack)
    article = _inject_structured_presentation(
        article,
        req=req,
        evidence_pack=evidence_pack,
        evidence_claims=evidence_claims,
    )
    article = sanitize_article_package(article)
    evidence_claims = _build_evidence_claims(article, evidence_pack)
    publish_gate = _evaluate_publish_gate(
        req=req,
        article=article,
        editorial_review=editorial_review,
        quality_score=combined_quality,
        evidence_pack=evidence_pack,
        evidence_claims=evidence_claims,
    )
    confidence = int(publish_gate.get("score") or 0)
    reasons = list(publish_gate.get("reasons") or [])
    publish_status = "published" if str(publish_gate.get("status") or "draft") == "publish" else "draft"
    review_reason = str(publish_gate.get("review_reason") or "")
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    # ── Render HTML + image ───────────────────────────────────────────────────
    fake_req = ContentAutomationRequest(
        topic=req.target,
        slug=slug,
        include_image=req.include_image,
        route_base=route_base,
        force_publish=req.force_publish,
    )
    image_bytes, image_ext, _mime = await _generate_image(fake_req, article, route_base)
    image_name = f"cover{image_ext}"
    public_url = f"{_SITE_URL}/{route_base}/{slug}/"
    img_href = f"/{route_base}/{slug}/{image_name}"
    html_text = render_article_html(
        article,
        public_url,
        img_href,
        generated_at,
        meta={
            "content_type": effective_content_type,
            "mode": editorial_mode,
            "quality_score": combined_quality,
            "ikg_covered": bool(ikg_ctx.get("covered")),
            "sources_used": list(evidence_pack.get("sources_used") or []),
            "hub_path": f"/{route_base}/research/" if route_base == "insights" else f"/{route_base}/",
        },
    )

    # ── Persist files ─────────────────────────────────────────────────────────
    adir = _article_dir(route_base, slug)
    html_path = adir / "index.html"
    json_path = adir / "article.json"
    img_path = adir / image_name
    _write_bytes(img_path, image_bytes)
    _write_text(html_path, html_text)

    # ── Score publishability ──────────────────────────────────────────────────
    if not reasons:
        reasons = [
            f"publish_gate_passed_{confidence}",
            f"editorial_{editorial_score}",
            f"urgency_{urgency_score}",
        ]

    # ── Mirror to public if publishing ────────────────────────────────────────
    public_mirror: str | None = None
    sitemap: str | None = None
    if publish_status == "published":
        try:
            pub_dirs = _public_article_dirs(route_base, slug)
            for pub_dir in pub_dirs:
                _write_text(pub_dir / "index.html", html_text)
                _write_bytes(pub_dir / image_name, image_bytes)
            public_mirror = str(pub_dirs[0])
            sitemap = _upsert_sitemap(route_base, slug)
            refresh_public_research_hub(route_base)
            submit_sitemap()
        except Exception:
            logger.exception("Public mirror failed for %s/%s", route_base, slug)

    result = ContentAutomationResult(
        slug=slug,
        title=article.title,
        description=article.description,
        route_base=route_base,
        public_url=public_url,
        html_path=str(html_path),
        json_path=str(json_path),
        image_path=str(img_path),
        generated_at=generated_at,
        sources_used=[
            {
                "title": str(source.get("title") or ""),
                "url": str(source.get("url") or ""),
            }
            for source in list(publish_gate.get("sources_used") or [])
        ],
        confidence_score=confidence,
        publish_status=publish_status,
        publish_reasons=reasons,
        mirrored_public_path=public_mirror,
        mirrored_sitemap=sitemap,
    )

    # Save JSON manifest
    manifest = {
        **result.model_dump(),
        "requested_by": requested_by,
        "job_id": job_id,
        "mode": editorial_mode,
        "content_type": effective_content_type,
        "requested_content_type": req.content_type,
        "quality_score": combined_quality,
        "ikg_covered": ikg_ctx.get("covered", False),
        "source_evidence_meta": req.source_evidence_meta or {},
        "publish_gate": publish_gate,
        "publish_gate_status": publish_gate.get("status") or "draft",
        "publish_gate_score": publish_gate.get("score") or 0,
        "evidence_pack_summary": evidence_pack.get("summary") or {},
        "evidence_claims": evidence_claims,
        "review_reason": review_reason,
        "sources_used": list(publish_gate.get("sources_used") or []),
        "editorial_review": editorial_review.to_dict(),
        "article": article.model_dump(),
    }
    _write_text(json_path, json.dumps(manifest, indent=2, ensure_ascii=True))

    BUS.emit(job_id, "content_done",
             slug=slug,
             title=article.title,
             public_url=public_url,
             publish_status=publish_status,
             publish_gate_status=publish_gate.get("status") or "draft",
             publish_gate_score=publish_gate.get("score") or 0,
             review_reason=review_reason,
             confidence_score=confidence,
             quality_score=combined_quality,
             editorial_score=editorial_score,
             urgency_score=urgency_score)

    return result


# ── Event ingestion (SEBI + earnings) via flash pipeline ─────────────────────

async def ingest_events_flash(
    req: FlashIngestRequest,
    *,
    requested_by: str,
    job_id: str,
) -> FlashIngestResult:
    """
    Discover SEBI / BSE / NSE events and route each one through the flash
    pipeline for high-quality article generation. Reuses v1 dedup state.
    """
    from finagent.news.sources.bse_announcements import fetch_bse_announcements
    from finagent.news.sources.nse_announcements import fetch_nse_announcements
    from finagent.news.sources.sebi_rss import fetch_sebi_news
    from finagent.content_automation import ContentEventWatch

    route_base = _safe_route_base(req.route_base)
    state = _load_event_state()
    seen_event_ids: dict[str, str] = state.setdefault("seen_event_ids", {})

    failures: list[dict[str, str]] = []
    results: list[dict[str, Any]] = []
    discovered = skipped = generated = published_count = draft_count = 0

    events_queue: list[tuple[str, dict[str, Any], str, str]] = []
    # (source, raw_event, target_label, content_type)

    # ── Gather SEBI events ────────────────────────────────────────────────────
    if req.content_type in ("sebi", "trend"):
        try:
            items = await asyncio.to_thread(fetch_sebi_news, req.max_events_per_source)
            for item in items:
                discovered += 1
                watch = ContentEventWatch(source="sebi")
                fid = _event_fingerprint("sebi", item, watch)
                if seen_event_ids.get(fid):
                    skipped += 1
                    continue
                seen_event_ids[fid] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                title = str(item.get("title") or "SEBI Update")[:160]
                events_queue.append(("sebi", item, f"SEBI: {title}", "sebi"))
        except Exception as exc:
            failures.append({"source": "sebi", "error": str(exc)[:400]})

    # ── Gather BSE events ─────────────────────────────────────────────────────
    for code in req.bse_codes:
        try:
            items = await asyncio.to_thread(
                fetch_bse_announcements, code, req.max_events_per_source
            )
            for item in items:
                discovered += 1
                watch = ContentEventWatch(source="bse", bse_scrip_code=code)
                fid = _event_fingerprint("bse", item, watch)
                if seen_event_ids.get(fid):
                    skipped += 1
                    continue
                seen_event_ids[fid] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                title = str(item.get("title") or "BSE Announcement")[:160]
                events_queue.append(("bse", item, f"{code}: {title}", "earnings"))
        except Exception as exc:
            failures.append({"source": "bse", "code": code, "error": str(exc)[:400]})

    # ── Gather NSE events ─────────────────────────────────────────────────────
    for isin in req.isin_list:
        try:
            items = await asyncio.to_thread(
                fetch_nse_announcements, isin, req.max_events_per_source
            )
            for item in items:
                discovered += 1
                watch = ContentEventWatch(source="nse", isin=isin)
                fid = _event_fingerprint("nse", item, watch)
                if seen_event_ids.get(fid):
                    skipped += 1
                    continue
                seen_event_ids[fid] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                title = str(item.get("title") or "NSE Announcement")[:160]
                events_queue.append(("nse", item, f"{isin}: {title}", "earnings"))
        except Exception as exc:
            failures.append({"source": "nse", "isin": isin, "error": str(exc)[:400]})

    _save_event_state(state)

    if req.dry_run:
        return FlashIngestResult(
            route_base=route_base,
            generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            discovered_events=discovered,
            skipped_seen=skipped,
            failures=failures,
        )

    # ── Process events via flash pipeline (bounded concurrency) ──────────────
    sem = asyncio.Semaphore(2)

    async def _process(src: str, event: dict, label: str, ctype: str) -> None:
        nonlocal generated, published_count, draft_count
        async with sem:
            sub_id = uuid.uuid4().hex[:12]
            BUS.open(sub_id, reset=True)
            try:
                gen_req = FlashGenerationRequest(
                    mode=req.mode,
                    content_type=ctype,  # type: ignore[arg-type]
                    target=label[:200],
                    source_url=str(event.get("url") or "") or None,
                    source_markdown=(event.get("snippet") or "")[:8000] or None,
                    route_base=route_base,
                    include_image=req.include_image,
                )
                r = await generate_flash_article(gen_req, job_id=sub_id, requested_by=requested_by)
                generated += 1
                if r.publish_status == "published":
                    published_count += 1
                else:
                    draft_count += 1
                results.append(r.model_dump())
                BUS.emit(job_id, "ingest_item_done",
                         slug=r.slug, title=r.title, publish_status=r.publish_status)
            except Exception as exc:
                logger.exception("Flash ingest failed for %r", label)
                failures.append({"target": label, "error": str(exc)[:400]})
            finally:
                BUS.close(sub_id)

    await asyncio.gather(
        *[_process(*e) for e in events_queue],
        return_exceptions=True,
    )

    return FlashIngestResult(
        route_base=route_base,
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        discovered_events=discovered,
        generated_articles=generated,
        auto_published=published_count,
        drafts=draft_count,
        skipped_seen=skipped,
        failures=failures,
        items=results,
    )


# ── Public hub HTML builder ───────────────────────────────────────────────────

def build_insights_hub_html(route_base: str = "insights") -> str:
    """
    Render the SEO landing page at /insights/research/
    listing all published articles, styled to match the app theme.
    """
    return _build_insights_hub_html_editorial(route_base=route_base)

    from finagent.content_automation import list_generated_articles

    articles = list_generated_articles(route_base=route_base, limit=120)
    published = [
        a for a in articles
        if str(a.get("publish_status") or "").lower() == "published"
        and str(a.get("publish_gate_status") or "").lower() == "publish"
    ]
    drafts = [a for a in articles if a.get("publish_status") != "published"]
    total = len(articles)
    now_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

    # ── helpers ──────────────────────────────────────────────────────────────
    _BADGE_COLORS = {
        "earnings": ("#34D399", "#0a2d1e"),
        "sebi":     ("#FB7185", "#2d0a12"),
        "trend":    ("#60A5FA", "#0a1a2d"),
        "company":  ("#A78BFA", "#1a0a2d"),
        "manual":   ("#94A3B8", "#141b24"),
    }

    def _type_badge(ct: str) -> str:
        fg, bg = _BADGE_COLORS.get(ct, ("#94A3B8", "#141b24"))
        label = html.escape(ct or "insight").upper()
        return (
            f'<span style="display:inline-block;font-size:10px;font-weight:700;'
            f'letter-spacing:.08em;color:{fg};padding:3px 9px;border-radius:5px;'
            f'background:{bg};border:1px solid {fg}33;">{label}</span>'
        )

    def _mode_icon(mode: str) -> str:
        return "⚡" if mode == "flash" else "🔬" if mode == "deep" else "📄"

    def _card(a: dict) -> str:
        title = html.escape(str(a.get("title") or "Untitled"))
        desc = html.escape(str(a.get("description") or a.get("meta_description") or "")[:160])
        url = html.escape(str(a.get("public_url") or "#"))
        date_str = str(a.get("generated_at") or "")[:10]
        score = int(a.get("confidence_score") or a.get("quality_score") or 0)
        ct = str(a.get("content_type") or "")
        mode = str(a.get("mode") or "")
        ikg = bool(a.get("ikg_covered"))
        badge = _type_badge(ct)
        mode_icon = _mode_icon(mode)
        score_color = "#34D399" if score >= 80 else "#60A5FA" if score >= 68 else "#94A3B8"
        ikg_badge = (
            '<span style="font-size:10px;color:#7dd3fc;background:rgba(125,211,252,.1);'
            'border:1px solid rgba(125,211,252,.25);padding:2px 7px;border-radius:4px;'
            'margin-left:4px;">IKG</span>'
            if ikg else ""
        )
        return (
            f'<a href="{url}" style="display:block;padding:24px;border-radius:16px;'
            f'border:1px solid rgba(145,180,230,.14);background:rgba(10,21,38,.85);'
            f'text-decoration:none;color:#f6f8fc;transition:border-color .18s,transform .15s;'
            f'backdrop-filter:blur(8px);" '
            f'onmouseover="this.style.borderColor=\'rgba(125,211,252,.35)\';this.style.transform=\'translateY(-2px)\'" '
            f'onmouseout="this.style.borderColor=\'rgba(145,180,230,.14)\';this.style.transform=\'none\'">'
            f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:10px;">'
            f'{badge}{ikg_badge}'
            f'<span style="margin-left:auto;font-size:10px;color:#5f7a9a;">{html.escape(date_str)}</span>'
            f'<span style="font-size:11px;">{mode_icon}</span>'
            f'</div>'
            f'<div style="font-size:1rem;font-weight:600;line-height:1.35;margin-bottom:8px;">{title}</div>'
            f'<div style="font-size:.85rem;color:#aab6cb;line-height:1.5;margin-bottom:14px;">{desc}</div>'
            f'<div style="font-size:11px;color:{score_color};">Quality score: {score}</div>'
            f'</a>'
        )

    if published:
        cards_html = (
            '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:18px;">'
            + "\n".join(_card(a) for a in published)
            + "</div>"
        )
    else:
        cards_html = (
            '<div style="text-align:center;padding:80px 0;">'
            '<div style="font-size:3rem;margin-bottom:16px;">🔬</div>'
            '<p style="color:#aab6cb;font-size:1.05rem;margin-bottom:8px;">No articles published yet.</p>'
            '<p style="color:#5f7a9a;font-size:.9rem;">The engine is running — check back soon or visit the '
            '<a href="/#/insights-studio" style="color:#7dd3fc;text-decoration:none;">Insights Studio</a> '
            'to generate and publish the first article.</p>'
            '</div>'
        )

    # Schema.org JSON-LD
    schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": "ProspektLab AI Research Hub — Indian Market Intelligence",
        "description": (
            "The most accurate AI-generated financial analysis on Indian markets — "
            "earnings results, SEBI orders, sector trends — powered by the "
            "ProspektLab Indian Knowledge Graph and 8-phase research pipeline."
        ),
        "url": f"{_SITE_URL}/insights/research/",
        "publisher": {
            "@type": "Organization",
            "name": "ProspektLab",
            "url": f"{_SITE_URL}/",
        },
    }, ensure_ascii=True)

    return (
        "<!doctype html>\n"
        '<html lang="en-IN">\n'
        "<head>\n"
        '  <meta charset="utf-8"/>\n'
        '  <meta name="viewport" content="width=device-width,initial-scale=1"/>\n'
        "  <title>ProspektLab AI Research Hub — Indian Market Intelligence</title>\n"
        f'  <meta name="description" content="The most accurate AI-generated financial analysis on Indian markets — earnings results, SEBI orders, sector trends — powered by the ProspektLab Indian Knowledge Graph and 8-phase research pipeline."/>\n'
        '  <meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1"/>\n'
        f'  <link rel="canonical" href="{html.escape(_SITE_URL)}/insights/research/"/>\n'
        '  <link rel="icon" type="image/svg+xml" href="/prospektlab-favicon-v2.svg"/>\n'
        '  <meta property="og:type" content="website"/>\n'
        '  <meta property="og:title" content="ProspektLab AI Research Hub — Indian Market Intelligence"/>\n'
        '  <meta property="og:description" content="Highest-accuracy AI financial analysis for Indian markets."/>\n'
        f'  <meta property="og:url" content="{html.escape(_SITE_URL)}/insights/research/"/>\n'
        '  <meta name="twitter:card" content="summary_large_image"/>\n'
        '  <link rel="preconnect" href="https://fonts.googleapis.com"/>\n'
        '  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&amp;display=swap" rel="stylesheet"/>\n'
        f'  <script type="application/ld+json">{schema}</script>\n'
        "  <style>\n"
        "    * { box-sizing: border-box; margin: 0; padding: 0; }\n"
        "    body {\n"
        "      font-family: Inter, -apple-system, BlinkMacSystemFont, Arial, sans-serif;\n"
        "      background: #03101f;\n"
        "      background-image: radial-gradient(ellipse at 20% 0%, rgba(96,165,250,.07) 0%, transparent 60%),\n"
        "                        radial-gradient(ellipse at 80% 20%, rgba(167,139,250,.05) 0%, transparent 50%);\n"
        "      color: #f6f8fc;\n"
        "      line-height: 1.7;\n"
        "      min-height: 100vh;\n"
        "    }\n"
        "    a { color: inherit; text-decoration: none; }\n"
        "    .shell { width: min(calc(100% - 32px), 1160px); margin: 0 auto; padding: 32px 0 80px; }\n"
        "    @media (max-width: 600px) { .stats-row { flex-wrap: wrap !important; gap: 16px !important; } }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="shell">\n'
        # ── NAV ──
        '  <nav style="display:flex;align-items:center;justify-content:space-between;'
        'padding:16px 0 36px;border-bottom:1px solid rgba(145,180,230,.1);margin-bottom:48px;">\n'
        '    <div style="display:flex;align-items:center;gap:10px;">\n'
        '      <div style="width:8px;height:8px;border-radius:50%;background:#7dd3fc;'
        'box-shadow:0 0 10px rgba(125,211,252,.5);"></div>\n'
        '      <span style="font-weight:800;font-size:14px;letter-spacing:.08em;'
        'text-transform:uppercase;color:#f6f8fc;">ProspektLab</span>\n'
        '    </div>\n'
        '    <div style="display:flex;gap:24px;align-items:center;">\n'
        f'      <a href="{html.escape(_SITE_URL)}/#/" style="font-size:13px;color:#aab6cb;'
        'transition:color .15s;" onmouseover="this.style.color=\'#7dd3fc\'" '
        'onmouseout="this.style.color=\'#aab6cb\'">App</a>\n'
        '    </div>\n'
        '  </nav>\n'
        # ── HERO ──
        '  <div style="text-align:center;padding:8px 0 56px;">\n'
        '    <div style="display:inline-flex;padding:5px 14px;border-radius:999px;'
        'background:rgba(96,165,250,.08);border:1px solid rgba(125,211,252,.2);'
        'color:#7dd3fc;font-size:11px;font-weight:700;text-transform:uppercase;'
        'letter-spacing:.12em;margin-bottom:24px;">ProspektLab AI Research</div>\n'
        '    <h1 style="font-size:clamp(2.2rem,5vw,3.8rem);font-weight:800;'
        'letter-spacing:-.04em;line-height:1.08;margin-bottom:18px;'
        'background:linear-gradient(135deg,#f6f8fc 30%,#7dd3fc);'
        '-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
        'background-clip:text;">'
        'Indian Market Intelligence Hub</h1>\n'
        '    <p style="color:#aab6cb;font-size:1.05rem;max-width:56ch;margin:0 auto 48px;line-height:1.65;">'
        'The most accurate AI-generated financial analysis — earnings results, SEBI orders, '
        'sector trends — powered by the ProspektLab Indian Knowledge Graph and 8-phase research pipeline.'
        '</p>\n'
        # ── STATS ──
        '    <div class="stats-row" style="display:flex;justify-content:center;gap:40px;margin-bottom:0;flex-wrap:wrap;">\n'
        f'      <div style="text-align:center;">'
        f'<div style="font-size:2.4rem;font-weight:800;color:#7dd3fc;letter-spacing:-.04em;">{len(published)}</div>'
        '<div style="font-size:.72rem;color:#5f7a9a;text-transform:uppercase;letter-spacing:.1em;margin-top:3px;">Articles Published</div>'
        '</div>\n'
        f'      <div style="text-align:center;">'
        '<div style="font-size:2.4rem;font-weight:800;color:#7dd3fc;letter-spacing:-.04em;">8</div>'
        '<div style="font-size:.72rem;color:#5f7a9a;text-transform:uppercase;letter-spacing:.1em;margin-top:3px;">Research Passes</div>'
        '</div>\n'
        f'      <div style="text-align:center;">'
        f'<div style="font-size:2.4rem;font-weight:800;color:#7dd3fc;letter-spacing:-.04em;">{total}</div>'
        '<div style="font-size:.72rem;color:#5f7a9a;text-transform:uppercase;letter-spacing:.1em;margin-top:3px;">Total Generated</div>'
        '</div>\n'
        '      <div style="text-align:center;">'
        '<div style="font-size:2.4rem;font-weight:800;color:#34D399;letter-spacing:-.04em;">IKG</div>'
        '<div style="font-size:.72rem;color:#5f7a9a;text-transform:uppercase;letter-spacing:.1em;margin-top:3px;">Knowledge Graph</div>'
        '</div>\n'
        '    </div>\n'
        '  </div>\n'
        # ── CAPABILITY PILLS ──
        '  <div style="display:flex;flex-wrap:wrap;gap:10px;justify-content:center;margin-bottom:48px;">\n'
        + "".join(
            f'  <span style="padding:6px 14px;border-radius:999px;font-size:12px;font-weight:500;'
            f'background:rgba(145,180,230,.06);border:1px solid rgba(145,180,230,.12);color:#aab6cb;">'
            f'{label}</span>\n'
            for label in [
                "⚡ Flash mode (2 min)", "🔬 Deep mode (8 min)", "📊 SEBI-safe analysis",
                "🏦 IKG ownership data", "💰 Earnings deep-dives", "🚨 Regulatory orders",
            ]
        )
        + "  </div>\n"
        # ── DIVIDER / SECTION HEADING ──
        + (
            '  <div style="display:flex;align-items:center;gap:16px;margin-bottom:24px;">\n'
            '    <div style="font-size:.75rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:#5f7a9a;">Latest Research</div>\n'
            '    <div style="flex:1;height:1px;background:rgba(145,180,230,.1);"></div>\n'
            f'    <div style="font-size:.72rem;color:#5f7a9a;">Updated {html.escape(now_str)}</div>\n'
            '  </div>\n'
        )
        # ── ARTICLE GRID ──
        + f"  {cards_html}\n"
        # ── FOOTER ──
        + '  <footer style="padding:48px 0 24px;text-align:center;border-top:1px solid rgba(145,180,230,.08);margin-top:64px;">\n'
        f'    <div style="display:flex;justify-content:center;gap:24px;margin-bottom:16px;">\n'
        f'      <a href="{html.escape(_SITE_URL)}/#/" style="font-size:13px;color:#7dd3fc;">ProspektLab App</a>\n'
        f'      <a href="/{html.escape(route_base)}/" style="font-size:13px;color:#7dd3fc;">All Insights</a>\n'
        '    </div>\n'
        '    <p style="font-size:.75rem;color:#3a4d62;max-width:60ch;margin:0 auto;">\n'
        '      ProspektLab AI Research. Educational content only — not investment advice.\n'
        '      No buy/sell/hold recommendation is made or implied.\n'
        '    </p>\n'
        '  </footer>\n'
        "</div>\n"
        "</body>\n"
        "</html>\n"
    )


build_insights_hub_html = _build_insights_hub_html_editorial

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
    event_is_low_value,
    run_editorial_revision_loop,
    sanitize_article_package,
    sanitize_public_text,
)
from finagent.seo.google_search_console import submit_sitemap
from finagent.events import BUS
from finagent.run_agent import AgentLoopConfig, run_research_session

logger = logging.getLogger("finagent.content.flash_engine")

_FLASH_PASSES = int(os.getenv("FINAGENT_CONTENT_FLASH_PASSES", "3"))
_DEEP_PASSES = int(os.getenv("FINAGENT_CONTENT_DEEP_PASSES", "8"))
_DEEP_WALL_SECONDS = float(os.getenv("FINAGENT_CONTENT_DEEP_WALL_SECONDS", "420"))
_FLASH_WALL_SECONDS = 180.0

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
        )
    elif content_type == "company":
        base += (
            "For company intelligence topics, structure the article around business model, financial trajectory, governance, risks, catalysts, and what differentiates the company from peers.\n"
        )
    elif content_type == "sebi":
        base += (
            "For SEBI topics, structure the article around the order timeline, allegations/findings, financial or governance implications, and what changes for public investors.\n"
        )
    elif content_type == "trend":
        base += (
            "For trend topics, structure the article around the thesis, data points, policy or macro triggers, segment winners and laggards, and the market consequences.\n"
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
    published = [a for a in articles if str(a.get("publish_status") or "").lower() == "published"]
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
            f'<span class="type-pill">{html.escape(meta["label"])}</span>'
            f'<span class="meta-pill">{html.escape(date_label)}</span>'
            "</div>"
            f'<h2 class="story-title"><a href="{html.escape(local_url)}">{title}</a></h2>'
            f'<p class="story-summary">{deck}</p>'
            f'<p class="story-description">{description}</p>'
            '<div class="story-footer">'
            f'<span class="story-source">{html.escape("Verified context" if ikg else "Editorial desk")}</span>'
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
            sections.append(ContentArticleSection(
                heading=heading[:140],
                paragraphs=paragraphs[:4],
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
            "constitute investment advice or a recommendation to buy, sell, or hold any security. "
            "Consult a SEBI-registered investment advisor before making investment decisions."
        ),
    ),
    ContentArticleFaq(
        question="Where does ProspektLab source its data?",
        answer=(
            "ProspektLab aggregates data from BSE, NSE, and SEBI official filings, XBRL financial "
            "reports, company press releases, concall transcripts, and verified ownership and "
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
            data["slug"] = slug
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

async def _direct_json_article_call(
    memo: str,
    ikg_ctx: dict[str, Any],
    req: "FlashGenerationRequest",
    slug: str,
    content_type: str | None = None,
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

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    model = os.getenv("FINAGENT_SYNTH_MODEL") or "gpt-4o"

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
        f"{schema_description}{ikg_section_instruction}\n\n"
        f"{structure_instruction}\n\n"
        f"RESEARCH NOTES:\n{memo[:12000]}{ikg_block}\n\n"
        f"Return ONLY the JSON object. No markdown fences. No explanation."
    )

    try:
        client = openai.AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=4000,
            response_format={"type": "json_object"},
            timeout=60,
        )
        raw = response.choices[0].message.content or ""
        # Strip any accidental markdown fences
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned, flags=re.MULTILINE)
            cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        data = json.loads(cleaned)
        data["slug"] = slug  # always use our slug
        return ContentArticlePackage.model_validate(data)
    except Exception as exc:
        logger.warning("Direct JSON article call failed: %s", exc)
        return None


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score_flash_publishability(
    article: ContentArticlePackage,
    has_ikg: bool,
    quality_score: float,
    mode: str,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    # Pipeline quality score (0-100)
    if quality_score >= 80:
        score += 30
        reasons.append(f"pipeline quality {quality_score:.0f}/100")
    elif quality_score >= 65:
        score += 20
        reasons.append(f"pipeline quality {quality_score:.0f}/100 (acceptable)")
    elif quality_score >= 50:
        score += 10

    # Section depth
    n_sections = len(article.sections)
    if n_sections >= 7:
        score += 22
        reasons.append(f"rich depth: {n_sections} sections")
    elif n_sections >= 5:
        score += 15
        reasons.append(f"good depth: {n_sections} sections")
    elif n_sections >= 4:
        score += 8

    # Paragraph depth
    n_paras = sum(len(s.paragraphs) for s in article.sections)
    if n_paras >= 14:
        score += 15
        reasons.append("substantial narrative depth")
    elif n_paras >= 10:
        score += 10
    elif n_paras >= 7:
        score += 5

    # Verified-record coverage
    if has_ikg:
        score += 10
        reasons.append("verified governance context included")

    # FAQ coverage
    n_faqs = len(article.faqs)
    if n_faqs >= 5:
        score += 8
        reasons.append("comprehensive FAQ")
    elif n_faqs >= 3:
        score += 5

    # Meta quality
    if len(article.description) >= 140:
        score += 4
    if len(article.hero_summary) >= 160:
        score += 4
    if len(article.keywords) >= 8:
        score += 3

    # Editorial-research bonus for greater depth
    if mode in {"deep", "research"}:
        score = min(score + 5, 100)

    return min(score, 100), reasons


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

    objectives = _CONTENT_DEEP_OBJECTIVES
    total_passes = len(objectives)
    wall_limit = _DEEP_WALL_SECONDS

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
            f"Context source: ProspektLab company knowledge graph (CIN: {ikg_ctx.get('cin')})"
        )

    enriched_objective = base_obj + extra_ctx

    synth_model = os.getenv("FINAGENT_SYNTH_MODEL") or "gpt-4o"
    fast_model = os.getenv("FINAGENT_SYNTH_MODEL_FAST") or "gpt-4o-mini"

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
    BUS.emit(job_id, "phase", phase="content_generation", note="Running editorial review and revision")
    article, editorial_review = await run_editorial_revision_loop(article, target=req.target, max_rounds=4)
    article = sanitize_article_package(article)
    editorial_score = editorial_review.total_score
    urgency_score = editorial_review.urgency_score
    combined_quality = int(round((max(quality_score, 0.0) * 0.30) + (editorial_score * 0.70)))
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
    confidence, reasons = _score_flash_publishability(
        article, bool(ikg_ctx.get("covered")), combined_quality, editorial_mode
    )
    confidence = int(round((confidence * 0.35) + (editorial_score * 0.65)))
    reasons.append(f"editorial review {editorial_score}/100")
    reasons.append(f"publish urgency {urgency_score}/100")
    if not editorial_review.ready_to_publish:
        reasons.extend(f"hold: {issue.message}" for issue in editorial_review.issues[:4])
    publish_status = "published" if (editorial_review.ready_to_publish and confidence >= 90) else "draft"

    # ── Mirror to public if publishing ────────────────────────────────────────
    public_mirror: str | None = None
    sitemap: str | None = None
    if publish_status == "published":
        try:
            pub_dir = _public_article_dir(route_base, slug)
            _write_text(pub_dir / "index.html", html_text)
            _write_bytes(pub_dir / image_name, image_bytes)
            public_mirror = str(pub_dir)
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
        sources_used=[],
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
        "editorial_review": editorial_review.to_dict(),
        "article": article.model_dump(),
    }
    _write_text(json_path, json.dumps(manifest, indent=2, ensure_ascii=True))

    BUS.emit(job_id, "content_done",
             slug=slug,
             title=article.title,
             public_url=public_url,
             publish_status=publish_status,
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
    published = [a for a in articles if a.get("publish_status") == "published"]
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

from __future__ import annotations

import asyncio
import base64
import html
import hashlib
import io
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from pydantic import BaseModel, Field

from finagent.paths import finagent_data_path, repo_root
from finagent.seo.google_search_console import submit_sitemap, submit_url_update
from finagent.news.sources.bse_announcements import fetch_bse_announcements
from finagent.news.sources.nse_announcements import fetch_nse_announcements
from finagent.news.sources.sebi_rss import fetch_sebi_news
from finagent.runtime_provider import resolve_openai_config
from finagent.tools.data import fetch_india_snapshot, fetch_news, fetch_nse_snapshot, fetch_yahoo_quote
from finagent.tools.web.scraper import search_web

logger = logging.getLogger("finagent.content_automation")

_SITE_URL = (os.getenv("PROSPEKTLAB_SITE_URL") or "https://prospektlab.com").rstrip("/")
_DEFAULT_ARTICLE_ROUTE = "insights"
_DATA_ROOT = finagent_data_path("content_automation")


@dataclass(frozen=True)
class _ImageClientConfig:
    api_key: str
    model: str
    provider: str
    base_url: str | None = None
    image_endpoint: str | None = None
    request_url: str | None = None
    api_version: str | None = None


class ContentArticleSection(BaseModel):
    heading: str = Field(..., min_length=3, max_length=140)
    paragraphs: list[str] = Field(default_factory=list, min_length=1, max_length=4)
    bullets: list[str] = Field(default_factory=list, max_length=6)


class ContentArticleFaq(BaseModel):
    question: str = Field(..., min_length=8, max_length=180)
    answer: str = Field(..., min_length=24, max_length=900)


class ContentArticlePackage(BaseModel):
    slug: str = Field(..., min_length=1, max_length=120)
    title: str = Field(..., min_length=12, max_length=120)
    description: str = Field(..., min_length=80, max_length=220)
    hero_eyebrow: str = Field(default="Research Brief", max_length=60)
    hero_title: str = Field(..., min_length=12, max_length=120)
    hero_summary: str = Field(..., min_length=80, max_length=360)
    audience: str = Field(default="Indian investors and market researchers", max_length=120)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    sections: list[ContentArticleSection] = Field(default_factory=list, min_length=4, max_length=12)
    faqs: list[ContentArticleFaq] = Field(default_factory=list, min_length=3, max_length=6)
    cta_label: str = Field(default="Talk to ProspektLab", max_length=40)
    cta_href: str = Field(default="/#/contact", max_length=200)
    image_prompt: str = Field(default="", max_length=1200)


class ContentAutomationRequest(BaseModel):
    topic: str = Field(..., min_length=8, max_length=240)
    slug: str | None = Field(default=None, max_length=120)
    company_symbol: str | None = Field(default=None, max_length=24)
    search_query: str | None = Field(default=None, max_length=240)
    source_url: str | None = Field(default=None, max_length=1000)
    source_markdown: str | None = Field(default=None, max_length=30000)
    audience: str = Field(default="Indian investors and market researchers", max_length=120)
    publish_to_frontend_public: bool = True
    include_image: bool = True
    overwrite: bool = True
    route_base: str = Field(default=_DEFAULT_ARTICLE_ROUTE, max_length=40)
    force_publish: bool = False


class ContentAutomationResult(BaseModel):
    slug: str
    title: str
    description: str
    route_base: str
    public_url: str
    html_path: str
    json_path: str
    image_path: str | None = None
    mirrored_public_path: str | None = None
    mirrored_sitemap: str | None = None
    generated_at: str
    sources_used: list[dict[str, str]] = Field(default_factory=list)
    confidence_score: int = 0
    publish_status: str = "draft"
    publish_reasons: list[str] = Field(default_factory=list)
    event_id: str | None = None


class ContentAutomationBatchTopic(BaseModel):
    topic: str = Field(..., min_length=8, max_length=240)
    slug: str | None = Field(default=None, max_length=120)
    company_symbol: str | None = Field(default=None, max_length=24)
    search_query: str | None = Field(default=None, max_length=240)
    source_url: str | None = Field(default=None, max_length=1000)
    source_markdown: str | None = Field(default=None, max_length=30000)
    audience: str | None = Field(default=None, max_length=120)


class ContentAutomationBatchRequest(BaseModel):
    topics: list[ContentAutomationBatchTopic] = Field(default_factory=list, min_length=1, max_length=50)
    publish_to_frontend_public: bool = True
    include_image: bool = True
    overwrite: bool = True
    route_base: str = Field(default=_DEFAULT_ARTICLE_ROUTE, max_length=40)
    max_concurrency: int = Field(default=3, ge=1, le=8)


class ContentAutomationBatchResult(BaseModel):
    route_base: str
    generated_at: str
    total_requested: int
    total_completed: int
    total_failed: int
    items: list[ContentAutomationResult] = Field(default_factory=list)
    failures: list[dict[str, str]] = Field(default_factory=list)


class ContentEventWatch(BaseModel):
    source: str = Field(..., min_length=3, max_length=12)
    symbol: str | None = Field(default=None, max_length=24)
    company_name: str | None = Field(default=None, max_length=120)
    isin: str | None = Field(default=None, max_length=24)
    bse_scrip_code: str | None = Field(default=None, max_length=24)
    audience: str | None = Field(default=None, max_length=120)


class ContentEventIngestionRequest(BaseModel):
    watches: list[ContentEventWatch] = Field(default_factory=list, min_length=1, max_length=100)
    route_base: str = Field(default=_DEFAULT_ARTICLE_ROUTE, max_length=40)
    max_events_per_watch: int = Field(default=3, ge=1, le=10)
    include_image: bool = True
    overwrite: bool = False
    dry_run: bool = False


class ContentEventIngestionResult(BaseModel):
    route_base: str
    generated_at: str
    discovered_events: int
    generated_articles: int
    auto_published: int
    drafts: int
    skipped_seen: int
    failures: list[dict[str, str]] = Field(default_factory=list)
    items: list[ContentAutomationResult] = Field(default_factory=list)


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    cleaned = cleaned.strip("-")
    return cleaned[:120] or "insight"


def _safe_route_base(value: str) -> str:
    base = slugify(value or _DEFAULT_ARTICLE_ROUTE)
    return base or _DEFAULT_ARTICLE_ROUTE


def _article_dir(route_base: str, slug: str) -> Path:
    return _DATA_ROOT / _safe_route_base(route_base) / slug


def _public_article_dir(route_base: str, slug: str) -> Path:
    return repo_root() / "Frontend" / "app" / "public" / _safe_route_base(route_base) / slug


def load_generated_article(slug: str, route_base: str = _DEFAULT_ARTICLE_ROUTE) -> dict[str, Any] | None:
    article_path = _article_dir(route_base, slug) / "article.json"
    if not article_path.is_file():
        return None
    try:
        return json.loads(article_path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load generated article %s", article_path)
        return None


def is_generated_article_published(slug: str, route_base: str = _DEFAULT_ARTICLE_ROUTE) -> bool:
    article = load_generated_article(slug, route_base=route_base)
    if not article:
        return False
    return str(article.get("publish_status") or "draft").lower() == "published"


def _find_cover_asset_name(route_base: str, slug: str) -> str | None:
    article_dir = _article_dir(route_base, slug)
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
        candidate = article_dir / f"cover{ext}"
        if candidate.is_file():
            return candidate.name
    return None


def _render_article_html_from_manifest(slug: str, route_base: str = _DEFAULT_ARTICLE_ROUTE) -> str | None:
    manifest = load_generated_article(slug, route_base=route_base)
    if not manifest:
        return None
    article_payload = manifest.get("article")
    if not isinstance(article_payload, dict):
        return None
    try:
        article = ContentArticlePackage.model_validate(article_payload)
    except Exception:
        logger.exception("Failed to validate article payload for %s/%s", route_base, slug)
        return None
    article_data = article.model_dump()
    field_limits = {
        "title": 120,
        "description": 220,
        "hero_eyebrow": 60,
        "hero_title": 120,
        "hero_summary": 360,
        "audience": 120,
        "cta_label": 40,
        "cta_href": 200,
        "image_prompt": 1200,
    }
    for key, limit in field_limits.items():
        if isinstance(article_data.get(key), str):
            article_data[key] = _repair_mojibake_text(str(article_data.get(key) or ""))[:limit].strip()
    article_data["keywords"] = [
        _repair_mojibake_text(str(keyword))[:120].strip()
        for keyword in (article_data.get("keywords") or [])
    ]
    for section in article_data.get("sections") or []:
        section["heading"] = _repair_mojibake_text(str(section.get("heading") or ""))[:140].strip()
        section["paragraphs"] = [
            _repair_mojibake_text(str(paragraph))
            for paragraph in (section.get("paragraphs") or [])
        ]
        section["bullets"] = [
            _repair_mojibake_text(str(item))
            for item in (section.get("bullets") or [])
        ]
    for faq in article_data.get("faqs") or []:
        faq["question"] = _repair_mojibake_text(str(faq.get("question") or ""))[:180].strip()
        faq["answer"] = _repair_mojibake_text(str(faq.get("answer") or ""))[:900].strip()
    try:
        article = ContentArticlePackage.model_validate(article_data)
    except Exception:
        logger.exception("Failed to sanitize article payload for %s/%s", route_base, slug)

    cover_name = _find_cover_asset_name(route_base, slug)
    image_href = f"/{_safe_route_base(route_base)}/{slug}/{cover_name}" if cover_name else None
    public_url = str(manifest.get("public_url") or f"{_SITE_URL}/{_safe_route_base(route_base)}/{slug}/")
    generated_at = str(manifest.get("generated_at") or datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    meta = {
        "content_type": manifest.get("content_type") or manifest.get("requested_content_type") or "manual",
        "mode": manifest.get("mode") or "research",
        "quality_score": manifest.get("quality_score") or manifest.get("confidence_score") or 0,
        "ikg_covered": bool(manifest.get("ikg_covered")),
        "hub_path": f"/{_safe_route_base(route_base)}/research/" if _safe_route_base(route_base) == "insights" else f"/{_safe_route_base(route_base)}/",
        "sources_used": manifest.get("sources_used") or [],
    }
    return render_article_html(article, public_url, image_href, generated_at, meta=meta)


def load_generated_article_html(slug: str, route_base: str = _DEFAULT_ARTICLE_ROUTE) -> str | None:
    rendered = _render_article_html_from_manifest(slug, route_base=route_base)
    if rendered:
        return rendered
    html_path = _article_dir(route_base, slug) / "index.html"
    if not html_path.is_file():
        return None
    try:
        return html_path.read_text(encoding="utf-8")
    except Exception:
        logger.exception("Failed to load generated article html %s", html_path)
        return None


def load_generated_article_asset(slug: str, asset_name: str, route_base: str = _DEFAULT_ARTICLE_ROUTE) -> Path | None:
    safe_name = Path(asset_name or "").name
    if not safe_name or safe_name != (asset_name or ""):
        return None
    asset_path = _article_dir(route_base, slug) / safe_name
    if not asset_path.is_file():
        return None
    return asset_path


def list_generated_articles(route_base: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    roots: list[Path]
    if route_base:
        roots = [_DATA_ROOT / _safe_route_base(route_base)]
    else:
        roots = [p for p in _DATA_ROOT.iterdir() if p.is_dir()] if _DATA_ROOT.is_dir() else []

    articles: list[dict[str, Any]] = []
    for root in roots:
        if not root.is_dir():
            continue
        current_route_base = root.name
        for article_json in root.glob("*/article.json"):
            try:
                data = json.loads(article_json.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("Failed reading article manifest %s", article_json)
                continue
            article_meta = data.get("article") if isinstance(data.get("article"), dict) else {}
            item = {
                "slug": data.get("slug") or article_json.parent.name,
                "title": _repair_mojibake_text(data.get("title") or ""),
                "description": _repair_mojibake_text(data.get("description") or ""),
                "route_base": data.get("route_base") or current_route_base,
                "public_url": data.get("public_url") or f"{_SITE_URL}/{current_route_base}/{article_json.parent.name}/",
                "generated_at": data.get("generated_at") or "",
                "html_path": data.get("html_path") or str(article_json.parent / "index.html"),
                "image_path": data.get("image_path") or None,
                "confidence_score": data.get("confidence_score") or 0,
                "publish_status": data.get("publish_status") or "draft",
                "content_type": data.get("content_type") or "manual",
                "requested_content_type": data.get("requested_content_type") or data.get("content_type") or "manual",
                "mode": data.get("mode") or "",
                "quality_score": data.get("quality_score") or 0,
                "ikg_covered": bool(data.get("ikg_covered")),
                "job_id": data.get("job_id") or "",
                "published_at": data.get("published_at") or "",
                "hero_summary": _repair_mojibake_text(article_meta.get("hero_summary") or ""),
                "audience": _repair_mojibake_text(article_meta.get("audience") or ""),
                "keywords": [_repair_mojibake_text(str(keyword)) for keyword in (article_meta.get("keywords") or [])],
                "editorial_review": data.get("editorial_review") or {},
                "editorial_quality_score": (
                    (data.get("editorial_review") or {}).get("total_score")
                    if isinstance(data.get("editorial_review"), dict)
                    else 0
                ),
                "publish_urgency_score": (
                    (data.get("editorial_review") or {}).get("urgency_score")
                    if isinstance(data.get("editorial_review"), dict)
                    else 0
                ),
            }
            articles.append(item)

    articles.sort(key=lambda item: item.get("generated_at") or "", reverse=True)
    return articles[: max(1, limit)]


def _source_domain(value: str) -> str:
    try:
        return (urlparse(value).hostname or "").lower()
    except Exception:
        return ""


async def _extract_source_url_markdown(source_url: str) -> tuple[str, list[dict[str, str]]]:
    try:
        from finagent.tools.mcp_servers.discovery_server import extract_url
    except Exception:
        return "", []

    try:
        result = await asyncio.to_thread(extract_url, [source_url], "basic")
    except Exception:
        logger.exception("URL extraction failed for %s", source_url)
        return "", []

    if not isinstance(result, dict) or result.get("error"):
        return "", []

    data = result.get("data") or {}
    extracted = data.get("results") or []
    snippets: list[str] = []
    sources: list[dict[str, str]] = []
    for item in extracted[:1]:
        url = str(item.get("url") or source_url)
        content = (item.get("content") or "").strip()
        if content:
            snippets.append(content[:8000])
            sources.append({"title": _source_domain(url) or "Source URL", "url": url})
    return "\n\n".join(snippets), sources


async def _collect_context(req: ContentAutomationRequest) -> tuple[str, list[dict[str, str]]]:
    blocks: list[str] = []
    sources: list[dict[str, str]] = []

    if req.source_markdown:
        blocks.append("User-provided source markdown:\n" + req.source_markdown.strip()[:18000])

    if req.source_url:
        extracted_text, extracted_sources = await _extract_source_url_markdown(req.source_url)
        if extracted_text:
            blocks.append("Extracted source URL content:\n" + extracted_text)
        sources.extend(extracted_sources)

    query = (req.search_query or req.topic).strip()
    try:
        search_docs = await search_web(query, max_results=6, bypass_crawl4ai=True)
    except Exception:
        logger.exception("Context search failed for %s", query)
        search_docs = []
    if search_docs:
        lines: list[str] = []
        for doc in search_docs[:6]:
            snippet = (doc.excerpt or "").strip()[:600]
            if not snippet:
                continue
            lines.append(f"- {doc.title.strip()}: {snippet}")
            sources.append({"title": doc.title.strip()[:160], "url": doc.final_url or doc.url})
        if lines:
            blocks.append("Search findings from existing platform web research:\n" + "\n".join(lines))

    try:
        news_items = await fetch_news(query, limit=4)
    except Exception:
        logger.exception("News fetch failed for %s", query)
        news_items = []
    if news_items:
        news_lines: list[str] = []
        for item in news_items[:4]:
            title = getattr(item, "title", "") or ""
            url = getattr(item, "url", "") or ""
            summary = getattr(item, "summary", "") or getattr(item, "snippet", "") or ""
            news_lines.append(f"- {title}: {summary[:400]}")
            if url:
                sources.append({"title": title[:160], "url": url})
        if news_lines:
            blocks.append("Recent news summaries from existing platform feeds:\n" + "\n".join(news_lines))

    if req.company_symbol:
        symbol = req.company_symbol.strip().upper()
        quote, india_snap, nse_snap = await asyncio.gather(
            fetch_yahoo_quote(symbol, timeout_s=18.0),
            fetch_india_snapshot(symbol),
            fetch_nse_snapshot(symbol),
            return_exceptions=True,
        )
        quote_lines: list[str] = []
        if not isinstance(quote, Exception) and quote is not None:
            quote_lines.append(
                f"Yahoo quote for {symbol}: price={getattr(quote, 'price', None)} currency={getattr(quote, 'currency', '')} market_cap={getattr(quote, 'market_cap', None)} trailing_pe={getattr(quote, 'trailing_pe', None)}"
            )
        snap = None
        if not isinstance(india_snap, Exception) and india_snap is not None:
            snap = india_snap
        elif not isinstance(nse_snap, Exception) and nse_snap is not None:
            snap = nse_snap
        if snap is not None:
            quote_lines.append(
                f"India market snapshot for {symbol}: name={getattr(snap, 'name', '')} sector={getattr(snap, 'sector', '')} industry={getattr(snap, 'industry', '')} market_cap={getattr(snap, 'market_cap', None)}"
            )
        if quote_lines:
            blocks.append("Company data from existing platform market APIs:\n" + "\n".join(quote_lines))

    deduped_sources: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for source in sources:
        url = (source.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped_sources.append({
            "title": (source.get("title") or _source_domain(url) or url)[:160],
            "url": url,
        })

    context = "\n\n".join(blocks).strip()
    return context[:24000], deduped_sources[:12]


def _fallback_article(req: ContentAutomationRequest, slug: str, context: str) -> ContentArticlePackage:
    compact = re.sub(r"\s+", " ", context or "").strip()
    summary = compact[:320] if compact else (
        "Indian investors need a practical reading of the latest market signal: what changed, why it matters, where the risk sits, and what to monitor before making an allocation decision."
    )
    topic = req.topic.strip()
    search_term = req.search_query or topic
    topic_label = topic.rstrip(". ")
    keywords = [
        topic,
        search_term,
        f"{topic} analysis",
        f"{topic} investor guide",
        "Indian market research",
    ]
    sections = [
        ContentArticleSection(
            heading="What changed and why it matters now",
            paragraphs=[
                f"{topic_label} matters because it sits where news flow, valuation comfort, liquidity, and investor behaviour meet. The useful reading starts with the current trigger, then asks whether it changes earnings visibility, portfolio risk, or only the short-term narrative.",
                "For a retail investor, the practical question is not whether the headline sounds exciting. It is whether the evidence changes expected cash flows, borrowing costs, fund flows, tax outcomes, or the risk of being forced into a decision at the wrong time.",
            ],
            bullets=[
                "Separate the event from the market reaction",
                "Check whether the data affects earnings, rates, liquidity, or governance",
                "Treat price moves as signals to investigate, not conclusions",
            ],
        ),
        ContentArticleSection(
            heading="The investor lens: stocks, gold, mutual funds, and SIPs",
            paragraphs=[
                "Equity investors should ask whether the development improves durable earnings, balance-sheet strength, capital allocation, or governance quality. A short-term rally without better cash generation can disappear quickly when liquidity tightens.",
                "Mutual fund and SIP investors should read the same event through exposure rather than headlines. Sector concentration, small-cap liquidity, duration risk in debt funds, cash needs, and gold allocation all matter more than one isolated news item.",
            ],
            bullets=[
                "Stocks: verify earnings impact and disclosure quality",
                "Mutual funds: check portfolio exposure and category risk",
                "Gold: use as a diversifier, not as a reaction to every scare",
                "SIPs: focus on time horizon, step-up discipline, and drawdown tolerance",
            ],
        ),
        ContentArticleSection(
            heading="Brief context before the headline fades",
            paragraphs=[
                f"The useful way to read {topic_label} is to place it beside recent market data, related official disclosures, and the broader macro setting. If the available evidence is thin, the right conclusion is caution, not a louder opinion.",
                "A serious investor should rank sources before ranking outcomes: regulator releases, exchange filings, fund factsheets, RBI or AMFI data, and company material should outweigh summaries, commentary, and social-market noise.",
            ],
            bullets=[
                "Prefer official filings and regulator releases over summaries",
                "Use recent price or NAV data only with a clear date",
                "Flag missing evidence plainly instead of filling the gap",
            ],
        ),
        ContentArticleSection(
            heading="History and pattern recognition",
            paragraphs=[
                "Most finance headlines repeat older patterns: rate-cycle turning points, margin pressure, liquidity squeezes, governance surprises, commodity shocks, or temporary fund-flow rotations. The historical comparison matters because markets often overpay for the first clean story and underprice the second-order risk.",
                "When history is relevant, compare the current event with at least one previous cycle. Did earnings follow the headline? Did flows persist? Did regulation change behaviour, or did it only create a short burst of volatility?",
            ],
            bullets=[
                "Look for repeated operating patterns",
                "Compare fund-flow reactions with later earnings data",
                "Watch whether management commentary matches filings over time",
            ],
        ),
        ContentArticleSection(
            heading="What to monitor next",
            paragraphs=[
                "The best next steps are concrete: identify the primary source, list the affected assets or funds, decide which metric would confirm the thesis, and set a review date. That protects investors from turning every market update into an impulsive portfolio change.",
                "For long-term investors, the monitor list should include earnings revisions, debt levels, promoter actions, fund portfolio changes, expense ratios, taxation, and liquidity. For gold and debt allocations, real yields, currency movement, product structure, and exit rules usually matter more than daily headlines.",
            ],
            bullets=[
                "Next official disclosure or factsheet",
                "Change in earnings, cash flow, or debt",
                "Fund exposure and concentration",
                "Tax and liquidity implications before switching",
            ],
        ),
    ]
    faqs = [
        ContentArticleFaq(
            question=f"How should investors approach {topic}?",
            answer="Start with the verified source, then ask whether the event changes earnings, interest rates, fund exposure, taxation, or liquidity. If it only changes sentiment, avoid making a portfolio decision until the data improves.",
        ),
        ContentArticleFaq(
            question="Does this article recommend buying or selling?",
            answer="No. It is educational research and does not recommend buying, selling, holding, switching, or rebalancing any security, mutual fund, SIP, gold product, or other investment.",
        ),
        ContentArticleFaq(
            question="Which sources should carry the most weight?",
            answer="Official exchange filings, regulator releases, RBI or AMFI data, company investor material, audited reports, and fund factsheets should carry more weight than social posts or generic market commentary.",
        ),
        ContentArticleFaq(
            question="What if the evidence is still incomplete?",
            answer="Treat the article as a watchlist brief. Wait for a primary disclosure, factsheet, or regulator update before acting, especially when the event affects concentrated stock positions or high-risk fund categories.",
        ),
    ]
    return ContentArticlePackage(
        slug=slug,
        title=f"{topic_label}: Investor Impact, Risks, And Watchpoints"[:120],
        description=summary[:200],
        hero_eyebrow="Investor Brief",
        hero_title=topic_label,
        hero_summary=summary,
        audience=req.audience,
        keywords=keywords[:8],
        sections=sections,
        faqs=faqs,
        image_prompt=(
            f"Premium ProspektLab editorial cover for {topic}. Build a sharp 3:2 dark business-news visual with layered "
            f"financial screens, documents, market cues, and one strong central subject tied to the story. "
            "Keep the full composition comfortably inside frame with generous padding so it works in a report card. "
            "High-end publication aesthetic, cinematic lighting, rich depth, India market context, no headline text, no watermark."
        ),
    )


async def _llm_generate_article(req: ContentAutomationRequest, slug: str, context: str) -> ContentArticlePackage:
    cfg = resolve_openai_config()
    if cfg is None:
        return _fallback_article(req, slug, context)

    try:
        from openai import AsyncOpenAI
    except Exception:
        return _fallback_article(req, slug, context)

    system = (
        "You are a senior Indian financial editor writing for serious retail investors and market researchers. "
        "Return JSON only, but the public article text must read like natural editorial writing, not an instruction, prompt, template, or model output. "
        "Never mention prompts, JSON, schema, automation, AI, language models, pipelines, internal tools, or quality scores. "
        "Write for humans first: concrete nouns, dated events, short paragraphs, and a calm investor lens. "
        "Do not narrate what the article will do; report what changed and why it matters. "
        "Do not fabricate facts not present in the context, and do not use buy, sell, hold, target-price, undervalued, or overvalued language."
    )
    user = (
        "Generate a publication-ready article package as JSON with these fields: "
        "title, description, hero_eyebrow, hero_title, hero_summary, audience, keywords, sections, faqs, cta_label, cta_href, image_prompt. "
        "Rules: title 50-70 chars when possible, description 140-170 chars when possible, 10-12 sections, each section with heading, 2-4 substantial paragraphs of 45-95 words each, optional bullets, 5-6 FAQs, keywords 8-12 items. "
        "Aim for a detailed 1,600-2,400 word investor-grade article; do not write thin summaries or generic explainers. "
        "Article arc: start with a sharp event hook and named source attribution, then brief context and a second hook that gives the reader a reason to continue, then market/policy/company context, numbers and quotes, history if it helps, investor implications across stocks, gold, mutual funds, SIPs, debt, tax, liquidity, risks, and watchpoints where relevant. "
        "Every factual claim should be tied to the provided context or written as a clearly labelled watchpoint. "
        "Do not publish diagnostic phrases such as 'this article covers', 'in this article', 'generated article', 'research workflow', 'quality score', 'sources processed', 'specialist findings', 'working research query', or 'next editorial pass'. "
        f"Slug: {slug}\n"
        f"Primary topic: {req.topic}\n"
        f"Audience: {req.audience}\n"
        f"Search query: {req.search_query or req.topic}\n"
        "CTA label should be concise and CTA href should usually be '/#/contact'.\n\n"
        "Use this context and source material:\n"
        f"{context[:22000]}"
    )

    client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
    model = cfg.model
    try:
        response = await client.chat.completions.create(
            model=model,
            temperature=0.4,
            max_tokens=9000,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content or "{}"
        data = _normalize_llm_article_payload(json.loads(content))
        data["slug"] = slug
        return ContentArticlePackage.model_validate(data)
    except Exception:
        logger.exception("LLM article generation failed; using fallback")
        return _fallback_article(req, slug, context)


def _split_llm_paragraphs(value: Any) -> list[str]:
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.extend(_split_llm_paragraphs(item))
            elif isinstance(item, dict):
                parts.extend(_split_llm_paragraphs(item.get("text") or item.get("content") or item.get("body")))
        return [part for part in parts if part]
    if not isinstance(value, str):
        return []
    raw = value.strip()
    if not raw:
        return []
    chunks = [chunk.strip(" -\t\r\n") for chunk in re.split(r"\n{2,}|\r\n{2,}", raw) if chunk.strip()]
    if len(chunks) > 1:
        return chunks[:4]
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", raw)
    if len(sentences) <= 3:
        return [raw]
    paragraphs: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        current.append(sentence)
        if len(" ".join(current).split()) >= 75 and len(paragraphs) < 3:
            paragraphs.append(" ".join(current).strip())
            current = []
    if current and len(paragraphs) < 4:
        paragraphs.append(" ".join(current).strip())
    return paragraphs or [raw]


def _normalize_llm_article_payload(data: Any) -> dict[str, Any]:
    """Accept common LLM variants and coerce them into ContentArticlePackage shape."""
    if not isinstance(data, dict):
        return {}
    sections = data.get("sections")
    if isinstance(sections, list):
        normalized_sections: list[dict[str, Any]] = []
        for raw_section in sections:
            if not isinstance(raw_section, dict):
                continue
            section = dict(raw_section)
            heading = section.get("heading") or section.get("title") or section.get("section_title") or "Investor context"
            paragraphs = _split_llm_paragraphs(section.get("paragraphs"))
            if not paragraphs:
                for key in ("content", "body", "text", "analysis", "summary", "details"):
                    paragraphs = _split_llm_paragraphs(section.get(key))
                    if paragraphs:
                        break
            bullets = section.get("bullets")
            if not isinstance(bullets, list):
                bullets = section.get("key_points") or section.get("watchpoints") or section.get("takeaways") or []
            if not paragraphs and isinstance(bullets, list) and bullets:
                paragraphs = [" ".join(str(item).strip() for item in bullets[:3] if str(item).strip())]
            normalized_sections.append({
                "heading": str(heading),
                "paragraphs": [str(item).strip() for item in paragraphs if str(item).strip()][:4],
                "bullets": [str(item).strip() for item in bullets if str(item).strip()][:6] if isinstance(bullets, list) else [],
            })
        data["sections"] = normalized_sections
    faqs = data.get("faqs")
    if isinstance(faqs, list):
        normalized_faqs: list[dict[str, str]] = []
        for raw_faq in faqs:
            if not isinstance(raw_faq, dict):
                continue
            question = raw_faq.get("question") or raw_faq.get("q") or raw_faq.get("title")
            answer = raw_faq.get("answer") or raw_faq.get("a") or raw_faq.get("response") or raw_faq.get("text")
            if question and answer:
                normalized_faqs.append({"question": str(question), "answer": str(answer)})
        data["faqs"] = normalized_faqs
    return data


def _render_json_ld(article: ContentArticlePackage, public_url: str, image_url: str | None, generated_at: str) -> str:
    faq_entities = [
        {
            "@type": "Question",
            "name": faq.question,
            "acceptedAnswer": {"@type": "Answer", "text": faq.answer},
        }
        for faq in article.faqs
    ]
    payload = {
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
                "@type": "Article",
                "@id": f"{public_url}#article",
                "headline": article.title,
                "description": article.description,
                "mainEntityOfPage": public_url,
                "inLanguage": "en-IN",
                "datePublished": generated_at,
                "dateModified": generated_at,
                "publisher": {"@id": f"{_SITE_URL}/#organization"},
                "author": {"@id": f"{_SITE_URL}/#organization"},
                "image": image_url or f"{_SITE_URL}/prospektlab-logo.svg",
                "keywords": article.keywords,
            },
            {
                "@type": "FAQPage",
                "@id": f"{public_url}#faq",
                "mainEntity": faq_entities,
            },
        ],
    }
    return json.dumps(payload, ensure_ascii=True)


def _repair_mojibake_text(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if any(token in text for token in ("Ã", "Â", "â")):
        try:
            repaired = text.encode("cp1252", errors="ignore").decode("utf-8", errors="ignore")
            if repaired and repaired.count("�") <= text.count("�"):
                text = repaired
        except Exception:
            pass
    replacements = {
        "â€”": "—",
        "â€“": "–",
        "â€˜": "'",
        "â€™": "'",
        "â€œ": '"',
        "â€": '"',
        "â€¦": "...",
        "â€¢": "•",
        "â†’": "→",
        "â‚¹": "₹",
        "Â·": "·",
        "Â±": "±",
        "Â ": " ",
        "Â": "",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text.replace("\ufeff", "").strip()


def _repair_mojibake_text(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if any(token in text for token in ("Ãƒ", "Ã‚", "Ã¢", "â", "Â")):
        try:
            repaired = text.encode("cp1252", errors="ignore").decode("utf-8", errors="ignore")
            if repaired and repaired.count("\ufffd") <= text.count("\ufffd"):
                text = repaired
        except Exception:
            pass
    replacements = {
        "Ã¢â‚¬â€": " - ",
        "Ã¢â‚¬â€œ": " - ",
        "Ã¢â‚¬Ëœ": "'",
        "Ã¢â‚¬â„¢": "'",
        "Ã¢â‚¬Å“": '"',
        "Ã¢â‚¬Â": '"',
        "Ã¢â‚¬Â¦": "...",
        "Ã¢â‚¬Â¢": " - ",
        "Ã¢â€ â€™": "->",
        "Ã¢â€šÂ¹": "Rs ",
        "Ã‚Â·": " - ",
        "Ã‚Â±": "+/-",
        "Ã‚ ": " ",
        "Ã‚": "",
        "â€”": " - ",
        "–": " - ",
        "•": " - ",
        "→": "->",
        "₹": "Rs ",
        "Â": "",
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    text = text.replace("\u00a0", " ").replace("\ufeff", "")
    text = re.sub(r"[^\S\r\n]+", " ", text)
    return text.strip()


def _hub_public_dir(route_base: str) -> Path:
    route_base = _safe_route_base(route_base)
    if route_base == "insights":
        return repo_root() / "Frontend" / "app" / "public" / route_base / "research"
    return repo_root() / "Frontend" / "app" / "public" / route_base


def refresh_public_research_hub(route_base: str = _DEFAULT_ARTICLE_ROUTE) -> str | None:
    route_base = _safe_route_base(route_base)
    try:
        from finagent.content.flash_engine import build_insights_hub_html
    except Exception:
        logger.exception("Failed to import public research hub builder")
        return None

    try:
        public_dir = _hub_public_dir(route_base)
        html_text = build_insights_hub_html(route_base=route_base)
        _write_text(public_dir / "index.html", html_text)
        return str(public_dir / "index.html")
    except Exception:
        logger.exception("Failed to refresh public research hub for %s", route_base)
        return None


_ARTICLE_PROSPEKTLAB_CSS = """
      :root {
        color-scheme: dark;
        --paper: #03060d;
        --paper-soft: rgba(8, 16, 32, 0.78);
        --ink: #f8fbff;
        --muted: #a8b4c8;
        --line: rgba(148, 163, 184, 0.14);
        --line-strong: rgba(147, 197, 253, 0.28);
        --accent: #60a5fa;
        --accent-soft: rgba(96, 165, 250, 0.12);
        --accent-2: #34d399;
        --accent-3: #2563eb;
        --shadow: 0 24px 80px rgba(0, 0, 0, 0.42);
        --panel: rgba(8, 16, 32, 0.78);
        --panel-strong: rgba(10, 22, 44, 0.92);
      }
      body {
        min-height: 100vh;
        background:
          linear-gradient(135deg, rgba(96, 165, 250, 0.10) 0 1px, transparent 1px 40px),
          linear-gradient(45deg, rgba(52, 211, 153, 0.055) 0 1px, transparent 1px 56px),
          linear-gradient(180deg, #03060d 0%, #07111f 44%, #03060d 100%);
        color: var(--ink);
      }
      body::before {
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        background:
          linear-gradient(115deg, rgba(96, 165, 250, 0.13), transparent 34%),
          linear-gradient(245deg, rgba(52, 211, 153, 0.08), transparent 38%);
        opacity: 0.86;
      }
      .progress-bar {
        background: linear-gradient(90deg, #eaf3ff, #60a5fa, #34d399);
      }
      .masthead {
        background: rgba(3, 6, 13, 0.74);
        border-bottom: 1px solid rgba(148, 163, 184, 0.12);
        box-shadow: 0 12px 40px rgba(0, 0, 0, 0.24);
      }
      .brand,
      .masthead-links a {
        color: var(--ink);
      }
      .masthead-links a {
        color: var(--muted);
      }
      .masthead-links a:hover {
        color: #ffffff;
      }
      .brand-mark {
        border-radius: 4px;
        background: linear-gradient(135deg, #eaf3ff, #60a5fa 45%, #1d4ed8);
        box-shadow: 0 0 0 7px rgba(96, 165, 250, 0.10), 0 0 28px rgba(96, 165, 250, 0.26);
      }
      .hero {
        padding: 42px 0 28px;
      }
      .hero-frame {
        position: relative;
        overflow: hidden;
        border-radius: 18px;
        border: 1px solid rgba(147, 197, 253, 0.22);
        background:
          linear-gradient(145deg, rgba(9, 18, 38, 0.96), rgba(8, 28, 62, 0.80) 58%, rgba(20, 41, 88, 0.62)),
          rgba(8, 16, 32, 0.92);
        box-shadow: var(--shadow), inset 0 1px 0 rgba(255, 255, 255, 0.05);
      }
      .hero-frame::after {
        content: "";
        position: absolute;
        inset: auto 0 0;
        height: 1px;
        background: linear-gradient(90deg, transparent, rgba(96, 165, 250, 0.8), rgba(52, 211, 153, 0.55), transparent);
      }
      h1,
      h2,
      h3,
      .mc-val,
      .faq-q-text,
      .signal-card p,
      .section-card li {
        color: var(--ink);
      }
      h1,
      h2,
      h3 {
        font-family: "Inter", "Manrope", sans-serif;
        letter-spacing: -0.035em;
      }
      h1 {
        max-width: 12ch;
      }
      p,
      li,
      .hero-summary,
      .hero-context,
      .rail-card li,
      .faq-answer p {
        color: var(--muted);
      }
      .hero-summary {
        color: #dbeafe;
      }
      .eyebrow,
      .section-kicker,
      .rail-label,
      .signal-index,
      .mc-lbl {
        color: var(--accent);
      }
      .eyebrow,
      .meta-pill,
      .keyword,
      .jump-chip,
      .section-card,
      .faq-shell,
      .faq-item,
      .rail-card,
      .signal-card,
      .footer-link {
        border-radius: 10px;
      }
      .eyebrow,
      .meta-pill-accent,
      .jump-chip:hover {
        border-color: rgba(96, 165, 250, 0.28);
        background: rgba(96, 165, 250, 0.10);
        color: #dbeafe;
      }
      .meta-pill,
      .keyword,
      .jump-chip {
        border-color: rgba(147, 197, 253, 0.22);
        background: rgba(15, 23, 42, 0.72);
        color: #dbeafe;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.035);
      }
      .jump-chip:hover,
      .jump-chip:focus-visible {
        background: linear-gradient(135deg, #eaf3ff, #60a5fa 52%, #1d4ed8);
        border-color: rgba(219, 234, 254, 0.68);
        color: #06111f;
        outline: none;
      }
      .hero-image {
        border-radius: 10px;
        border-color: rgba(147, 197, 253, 0.26);
        background:
          radial-gradient(circle at 18% 12%, rgba(96, 165, 250, 0.24), transparent 36%),
          radial-gradient(circle at 88% 82%, rgba(52, 211, 153, 0.16), transparent 34%),
          linear-gradient(135deg, rgba(3, 6, 13, 0.88), rgba(10, 22, 44, 0.94));
        box-shadow: 0 24px 72px rgba(0, 0, 0, 0.44), 0 0 42px rgba(96, 165, 250, 0.12);
        object-fit: cover;
        padding: 0;
        filter: saturate(1.08) contrast(1.04);
      }
      .signal-card,
      .rail-card,
      .section-card,
      .faq-shell,
      .faq-item {
        border-radius: 10px;
        border-color: rgba(147, 197, 253, 0.18);
        background: linear-gradient(180deg, rgba(12, 22, 44, 0.82), rgba(6, 13, 28, 0.80));
        box-shadow: 0 20px 66px rgba(0, 0, 0, 0.32), inset 0 1px 0 rgba(255, 255, 255, 0.04);
        backdrop-filter: blur(18px);
      }
      .signal-card:hover,
      .rail-card:hover,
      .section-card:hover,
      .faq-item:hover {
        border-color: rgba(96, 165, 250, 0.34);
      }
      .section-context {
        border-color: rgba(96, 165, 250, 0.30);
        background: linear-gradient(180deg, rgba(96, 165, 250, 0.12), rgba(8, 16, 32, 0.76));
      }
      li.data-row {
        border-left-color: var(--accent);
        background: rgba(96, 165, 250, 0.07);
        color: #dbeafe;
      }
      li.data-row::before {
        color: var(--accent-2);
      }
      .toc a {
        color: var(--muted);
      }
      .toc a:hover,
      .toc a.is-active {
        background: rgba(96, 165, 250, 0.12);
        color: #ffffff;
      }
      .faq-item summary:hover {
        background: rgba(96, 165, 250, 0.07);
      }
      .faq-chevron {
        color: var(--accent);
      }
      .footer-card {
        border-radius: 14px;
        border: 1px solid rgba(147, 197, 253, 0.20);
        background: linear-gradient(135deg, rgba(8, 16, 32, 0.96), rgba(8, 28, 62, 0.82));
      }
      .footer-link {
        min-height: 40px;
        border-color: rgba(96, 165, 250, 0.38);
        background: linear-gradient(135deg, #eaf3ff, #60a5fa 52%, #1d4ed8);
        color: #06111f;
        font-weight: 900;
        box-shadow: 0 14px 34px rgba(37, 99, 235, 0.24), inset 0 1px 0 rgba(255, 255, 255, 0.48);
      }
      .footer-link:hover {
        background: linear-gradient(135deg, #ffffff, #93c5fd 52%, #2563eb);
        color: #020817;
      }
      #btt {
        position: fixed;
        right: 28px;
        bottom: 28px;
        z-index: 200;
        width: 44px;
        height: 44px;
        border-radius: 50%;
        border: 1px solid rgba(147, 197, 253, 0.28);
        background: rgba(8, 16, 32, 0.86);
        color: #eaf3ff;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 18px;
        opacity: 0;
        pointer-events: none;
        transform: translateY(12px);
        transition: opacity 0.22s ease, transform 0.22s ease, border-color 0.22s ease, background 0.22s ease;
        box-shadow: 0 16px 48px rgba(0, 0, 0, 0.34), inset 0 1px 0 rgba(255, 255, 255, 0.04);
        backdrop-filter: blur(16px);
      }
      #btt.show {
        opacity: 1;
        pointer-events: auto;
        transform: translateY(0);
      }
      #btt:hover {
        border-color: rgba(96, 165, 250, 0.58);
        background: rgba(15, 23, 42, 0.96);
      }
      @media (max-width: 720px) {
        .hero-frame,
        .section-card,
        .faq-shell,
        .rail-card,
        .footer-card {
          border-radius: 12px;
        }
      }
"""


def render_article_html(
    article: ContentArticlePackage,
    public_url: str,
    image_href: str | None,
    generated_at: str,
    meta: dict[str, Any] | None = None,
) -> str:
    def esc(value: str) -> str:
        return html.escape(_repair_mojibake_text(value), quote=True)

    meta = dict(meta or {})
    route_base = _DEFAULT_ARTICLE_ROUTE
    try:
        parsed = urlparse(public_url)
        parts = [part for part in (parsed.path or "").split("/") if part]
        if len(parts) >= 2:
            route_base = _safe_route_base(parts[0])
    except Exception:
        route_base = _DEFAULT_ARTICLE_ROUTE
    hub_path = str(meta.get("hub_path") or (f"/{route_base}/research/" if route_base == "insights" else f"/{route_base}/"))
    raw_sources = meta.get("sources_used") if isinstance(meta.get("sources_used"), list) else []
    sources_used = [source for source in raw_sources if isinstance(source, dict)]

    section_html: list[str] = []
    toc_items: list[str] = []
    highlight_points: list[str] = []
    for idx, section in enumerate(article.sections, start=1):
        anchor = f"section-{idx}-{slugify(section.heading)}"
        toc_items.append(f'<li><a href="#{anchor}" data-toc-link>{esc(section.heading)}</a></li>')
        paragraphs = "".join(f"<p>{esc(paragraph)}</p>" for paragraph in section.paragraphs)
        bullets = ""
        if section.bullets:
            for item in section.bullets:
                if len(highlight_points) < 4:
                    highlight_points.append(item)
            items = "".join(f'<li class="data-row">{esc(item)}</li>' for item in section.bullets)
            bullets = f'<ul class="data-list">{items}</ul>'
        heading_key = section.heading.lower()
        section_class = (
            "section-card section-context"
            if ("knowledge graph" in heading_key or "verified ownership" in heading_key or "governance records" in heading_key)
            else "section-card"
        )
        section_html.append(
            f'<section class="{section_class}" id="{anchor}" data-section>'
            f'<div class="section-kicker">Section {idx:02d}</div>'
            f'<h2>{esc(section.heading)}</h2>{paragraphs}{bullets}'
            f'</section>'
        )

    if not highlight_points:
        highlight_points = article.keywords[:4]

    def _metric_card(idx: int, text: str) -> str:
        """Render a highlight bullet as a structured metric tile.

        Parses 'Label: Value (±Change)' format.  Falls back to plain card
        when the format doesn't match.
        """
        if ":" in text:
            label, rest = text.split(":", 1)
            rest = rest.strip()
            cm = re.search(r"\(([+\-][^)]+)\)", rest)
            if cm:
                chg = cm.group(1)
                val = rest[: cm.start()].rstrip(" —")
                css_dir = "mc-pos" if chg.startswith("+") else "mc-neg"
                return (
                    f'<article class="signal-card">'
                    f'<div class="signal-index">{idx:02d}</div>'
                    f'<div class="mc-lbl">{esc(label.strip())}</div>'
                    f'<div class="mc-val">{esc(val.strip())}</div>'
                    f'<span class="mc-chg {css_dir}">{esc(chg)}</span>'
                    f"</article>"
                )
            return (
                f'<article class="signal-card">'
                f'<div class="signal-index">{idx:02d}</div>'
                f'<div class="mc-lbl">{esc(label.strip())}</div>'
                f'<div class="mc-val">{esc(rest)}</div>'
                f"</article>"
            )
        return (
            f'<article class="signal-card">'
            f'<div class="signal-index">{idx:02d}</div>'
            f"<p>{esc(text)}</p>"
            f"</article>"
        )

    highlight_html = "".join(
        _metric_card(idx, point) for idx, point in enumerate(highlight_points[:4], start=1)
    )

    faq_items = "".join(
        f'<details class="faq-item"><summary><span class="faq-q-text">{esc(faq.question)}</span><span class="faq-chevron" aria-hidden="true">&#8250;</span></summary><div class="faq-answer"><p>{esc(faq.answer)}</p></div></details>'
        for faq in article.faqs
    )
    image_markup = f'<img class="hero-image" src="{esc(image_href)}" alt="{esc(article.title)} cover image" loading="eager" />' if image_href else '<div class="hero-image hero-image-fallback">ProspektLab Insight</div>'
    json_ld = _render_json_ld(article, public_url, f"{_SITE_URL}{image_href}" if image_href and image_href.startswith("/") else image_href, generated_at).replace("</", "<\\/")
    total_words = sum(len(paragraph.split()) for section in article.sections for paragraph in section.paragraphs)
    read_minutes = max(4, (total_words + 219) // 220)
    hero_context = f"{generated_at[:10]} • {read_minutes} min read"

    methodology_points = [
        "Primary source bias: official company filings, exchange disclosures, and transcripts should outrank generic summaries.",
        "This article avoids live market price commentary unless the source explicitly belongs to the reporting period.",
        "Ownership, governance, and filing signals appear only when verified records provide usable depth; thin coverage should be disclosed, not embellished.",
    ]
    methodology_html = "".join(f"<li>{esc(point)}</li>" for point in methodology_points)
    source_html = ""
    if sources_used:
        source_items = "".join(
            f'<li><a href="{esc(str(source.get("url") or "#"))}" rel="noopener noreferrer">{esc(str(source.get("title") or source.get("url") or "Source"))}</a></li>'
            for source in sources_used[:6]
        )
        source_html = (
            '<section class="rail-card">'
            '<div class="rail-label">Primary sources</div>'
            f"<ul>{source_items}</ul>"
            "</section>"
        )

    return f"""<!doctype html>
<html lang=\"en-IN\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>{esc(article.title)}</title>
    <meta name=\"description\" content=\"{esc(article.description)}\" />
    <meta name=\"robots\" content=\"index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1\" />
    <meta name=\"theme-color\" content=\"#03060d\" />
    <link rel=\"canonical\" href=\"{esc(public_url)}\" />
    <link rel=\"icon\" type=\"image/svg+xml\" href=\"/prospektlab-favicon-v2.svg\" />
    <meta property=\"og:type\" content=\"article\" />
    <meta property=\"og:site_name\" content=\"ProspektLab\" />
    <meta property=\"og:title\" content=\"{esc(article.title)}\" />
    <meta property=\"og:description\" content=\"{esc(article.description)}\" />
    <meta property=\"og:url\" content=\"{esc(public_url)}\" />
    <meta property=\"og:image\" content=\"{esc(f'{_SITE_URL}{image_href}' if image_href and image_href.startswith('/') else (image_href or f'{_SITE_URL}/prospektlab-logo.svg'))}\" />
    <meta name=\"twitter:card\" content=\"summary_large_image\" />
    <meta name=\"twitter:title\" content=\"{esc(article.title)}\" />
    <meta name=\"twitter:description\" content=\"{esc(article.description)}\" />
    <meta name=\"twitter:image\" content=\"{esc(f'{_SITE_URL}{image_href}' if image_href and image_href.startswith('/') else (image_href or f'{_SITE_URL}/prospektlab-logo.svg'))}\" />
    <link rel=\"preconnect\" href=\"https://fonts.googleapis.com\" />
    <link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin />
    <link href=\"https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Manrope:wght@400;500;600;700;800&family=Newsreader:opsz,wght@6..72,500;6..72,700&display=swap\" rel=\"stylesheet\" />
    <style>
      :root {{
        color-scheme: light;
        --paper: #f4ecdf;
        --paper-soft: #fffaf2;
        --ink: #142033;
        --muted: #5f6778;
        --line: rgba(20, 32, 51, 0.12);
        --line-strong: rgba(20, 32, 51, 0.22);
        --accent: #0d766e;
        --accent-soft: rgba(13, 118, 110, 0.12);
        --accent-2: #ad6a1f;
        --accent-3: #0f3d91;
        --shadow: 0 28px 90px rgba(17, 24, 39, 0.08);
      }}
      * {{ box-sizing: border-box; }}
      html {{ scroll-behavior: smooth; }}
      body {{
        margin: 0;
        font-family: "Manrope", Arial, sans-serif;
        background:
          radial-gradient(circle at top left, rgba(13, 118, 110, 0.10), transparent 26%),
          radial-gradient(circle at 100% 0%, rgba(15, 61, 145, 0.12), transparent 20%),
          linear-gradient(180deg, #f7f1e6 0%, #f4ecdf 46%, #f0e7d8 100%);
        color: var(--ink);
        line-height: 1.75;
      }}
      a {{ color: inherit; }}
      img {{ max-width: 100%; }}
      .progress-bar {{
        position: fixed;
        inset: 0 0 auto;
        height: 4px;
        background: linear-gradient(90deg, var(--accent), var(--accent-2));
        transform-origin: left center;
        transform: scaleX(0);
        z-index: 1000;
      }}
      .shell {{ width: min(calc(100% - 36px), 1240px); margin: 0 auto; }}
      .masthead {{
        position: sticky;
        top: 0;
        z-index: 80;
        backdrop-filter: blur(18px);
        background: rgba(244, 236, 223, 0.86);
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
        text-decoration: none;
        color: var(--ink);
      }}
      .brand-mark {{
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: linear-gradient(135deg, var(--accent), var(--accent-3));
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
      .masthead-links a {{
        text-decoration: none;
        transition: color 0.18s ease;
      }}
      .masthead-links a:hover {{ color: var(--ink); }}
      .hero {{
        padding: 34px 0 24px;
      }}
      .hero-frame {{
        border: 1px solid var(--line);
        border-radius: 34px;
        padding: 30px;
        background: linear-gradient(135deg, rgba(255, 250, 242, 0.92), rgba(249, 243, 233, 0.94));
        box-shadow: var(--shadow);
      }}
      .hero-grid {{
        display: grid;
        grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.86fr);
        gap: 28px;
        align-items: start;
      }}
      .eyebrow {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 7px 14px;
        border-radius: 999px;
        background: var(--accent-soft);
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
      h1, h2, h3 {{ margin: 0; color: var(--ink); }}
      h1 {{
        margin-top: 18px;
        font-family: "Newsreader", Georgia, serif;
        font-size: clamp(3rem, 7vw, 5.3rem);
        line-height: 0.96;
        letter-spacing: -0.05em;
        max-width: 10.8ch;
      }}
      h2 {{
        font-family: "Newsreader", Georgia, serif;
        font-size: clamp(2rem, 3vw, 2.7rem);
        line-height: 1.02;
        letter-spacing: -0.04em;
        margin-bottom: 14px;
      }}
      h3 {{
        font-family: "Newsreader", Georgia, serif;
        font-size: 1.5rem;
        letter-spacing: -0.03em;
      }}
      p, li {{
        margin: 0 0 14px;
        color: var(--muted);
        font-size: 1.02rem;
      }}
      .hero-summary {{
        margin-top: 18px;
        max-width: 60ch;
        font-size: 1.08rem;
      }}
      .hero-context {{
        margin-top: 14px;
        color: var(--muted);
        font-size: 0.92rem;
      }}
      .hero-meta {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 20px;
      }}
      .meta-pill, .keyword, .jump-chip {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 9px 13px;
        border-radius: 999px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.72);
        color: var(--ink);
        font-size: 12px;
        text-decoration: none;
      }}
      .meta-pill-accent {{
        border-color: rgba(13, 118, 110, 0.24);
        background: rgba(13, 118, 110, 0.08);
        color: var(--accent);
      }}
      .keyword-wrap, .jump-wrap {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 16px;
      }}
      .hero-image {{
        display: block;
        width: 100%;
        min-height: 320px;
        aspect-ratio: 3 / 2;
        padding: 14px;
        box-sizing: border-box;
        border-radius: 26px;
        border: 1px solid rgba(20, 32, 51, 0.10);
        background: linear-gradient(135deg, rgba(13, 118, 110, 0.10), rgba(15, 61, 145, 0.14));
        object-fit: contain;
        object-position: center;
        box-shadow: 0 20px 60px rgba(15, 23, 42, 0.08);
      }}
      .hero-image-fallback {{
        display: grid;
        place-items: center;
        color: var(--accent-3);
        font-family: "IBM Plex Mono", monospace;
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }}
      .signal-board {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 14px;
        margin-top: 22px;
      }}
      .signal-card {{
        border-radius: 20px;
        border: 1px solid var(--line-strong);
        padding: 18px 20px 20px;
        background: rgba(255, 255, 255, 0.88);
        box-shadow: 0 4px 16px rgba(20,32,51,0.05);
        display: flex;
        flex-direction: column;
        gap: 4px;
      }}
      .signal-index {{
        font-family: "IBM Plex Mono", monospace;
        font-size: 10px;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--accent);
        margin-bottom: 6px;
      }}
      .signal-card p {{
        margin: 0;
        color: var(--ink);
        font-size: 0.93rem;
        line-height: 1.5;
      }}
      .mc-lbl {{
        font-family: "IBM Plex Mono", monospace;
        font-size: 10px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--muted);
        margin-bottom: 2px;
      }}
      .mc-val {{
        font-family: "IBM Plex Mono", monospace;
        font-size: 1.05rem;
        font-weight: 600;
        color: var(--ink);
        letter-spacing: -0.02em;
        line-height: 1.2;
      }}
      .mc-chg {{
        display: inline-block;
        margin-top: 6px;
        padding: 3px 8px;
        border-radius: 6px;
        font-family: "IBM Plex Mono", monospace;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.02em;
      }}
      .mc-pos {{ background: rgba(16,185,129,0.12); color: #047857; }}
      .mc-neg {{ background: rgba(239,68,68,0.12); color: #b91c1c; }}
      /* ── Data list (section bullets) ─────────────── */
      ul.data-list {{
        list-style: none;
        padding: 0;
        margin: 18px 0 0;
        display: flex;
        flex-direction: column;
        gap: 8px;
      }}
      li.data-row {{
        display: flex;
        align-items: baseline;
        gap: 10px;
        padding: 10px 16px;
        background: rgba(20,32,51,0.035);
        border-left: 3px solid var(--accent);
        border-radius: 0 10px 10px 0;
        color: var(--ink);
        font-size: 0.965rem;
        line-height: 1.55;
      }}
      li.data-row::before {{
        content: "→";
        color: var(--accent);
        font-weight: 700;
        flex-shrink: 0;
        font-size: 12px;
      }}
      main {{
        padding: 8px 0 54px;
      }}
      .story-shell {{
        display: grid;
        grid-template-columns: minmax(0, 270px) minmax(0, 1fr);
        gap: 24px;
        align-items: start;
      }}
      .story-rail {{
        position: sticky;
        top: 86px;
        display: grid;
        gap: 16px;
      }}
      .rail-card {{
        border-radius: 24px;
        border: 1px solid var(--line);
        background: rgba(255, 250, 242, 0.84);
        padding: 18px 18px 20px;
        box-shadow: 0 14px 36px rgba(15, 23, 42, 0.04);
      }}
      .rail-label {{
        font-family: "IBM Plex Mono", monospace;
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        color: var(--muted);
        margin-bottom: 10px;
      }}
      .toc ol {{
        list-style: none;
        padding: 0;
        margin: 0;
        display: grid;
        gap: 8px;
      }}
      .toc a {{
        display: block;
        padding: 10px 12px;
        border-radius: 14px;
        text-decoration: none;
        color: var(--muted);
        transition: background 0.18s ease, color 0.18s ease, transform 0.18s ease;
      }}
      .toc a:hover, .toc a.is-active {{
        background: rgba(13, 118, 110, 0.08);
        color: var(--ink);
        transform: translateX(2px);
      }}
      .rail-card ul {{
        padding-left: 18px;
        margin: 0;
      }}
      .rail-card li {{
        margin-bottom: 10px;
        font-size: 0.93rem;
      }}
      .article-flow {{
        display: grid;
        gap: 18px;
      }}
      .section-card {{
        border-radius: 28px;
        border: 1px solid var(--line);
        background: rgba(255, 250, 242, 0.86);
        padding: 26px 28px;
        box-shadow: 0 18px 40px rgba(15, 23, 42, 0.05);
      }}
      .section-context {{
        border-color: rgba(13, 118, 110, 0.24);
        background: linear-gradient(180deg, rgba(13, 118, 110, 0.07), rgba(255, 250, 242, 0.94));
      }}
      .section-kicker {{
        margin-bottom: 10px;
        font-family: "IBM Plex Mono", monospace;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--accent-2);
      }}
      .section-card ul {{
        margin: 8px 0 0;
        padding-left: 18px;
      }}
      .section-card li {{
        color: var(--ink);
      }}
      .faq-shell {{
        border-radius: 28px;
        border: 1px solid var(--line);
        background: rgba(255, 250, 242, 0.9);
        padding: 24px 26px;
      }}
      .faq-grid {{
        display: grid;
        gap: 12px;
        margin-top: 16px;
      }}
      .faq-item {{
        border-radius: 16px;
        border: 1px solid var(--line);
        background: rgba(255, 255, 255, 0.80);
        overflow: hidden;
        transition: box-shadow 0.18s ease;
      }}
      .faq-item[open] {{
        box-shadow: 0 8px 24px rgba(20,32,51,0.07);
        border-color: var(--line-strong);
      }}
      .faq-item summary {{
        list-style: none;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 16px 20px;
        transition: background 0.15s ease;
      }}
      .faq-item summary:hover {{ background: rgba(13,118,110,0.04); }}
      .faq-item summary::-webkit-details-marker {{ display: none; }}
      .faq-q-text {{
        font-weight: 700;
        color: var(--ink);
        font-size: 1rem;
        line-height: 1.4;
      }}
      .faq-chevron {{
        font-size: 22px;
        color: var(--accent);
        flex-shrink: 0;
        transition: transform 0.22s cubic-bezier(0.4,0,0.2,1);
        display: inline-block;
      }}
      .faq-item[open] .faq-chevron {{ transform: rotate(90deg); }}
      .faq-answer {{
        padding: 0 20px 18px;
        border-top: 1px solid var(--line);
      }}
      .faq-answer p {{
        margin: 14px 0 0;
        color: var(--muted);
        font-size: 0.98rem;
        line-height: 1.75;
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
        color: rgba(246, 248, 252, 0.76);
        margin: 8px 0 0;
      }}
      .footer-link {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 11px 18px;
        border-radius: 999px;
        background: rgba(255, 255, 255, 0.10);
        color: #f6f8fc;
        border: 1px solid rgba(255, 255, 255, 0.18);
        text-decoration: none;
        white-space: nowrap;
      }}
      @media (max-width: 1080px) {{
        .hero-grid, .story-shell {{
          grid-template-columns: 1fr;
        }}
        .story-rail {{
          position: static;
          order: 2;
        }}
        .signal-board {{
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }}
        h1 {{
          max-width: 100%;
        }}
      }}
      @media (max-width: 720px) {{
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
        .hero-frame {{
          padding: 22px;
          border-radius: 26px;
        }}
        .section-card, .faq-shell, .rail-card {{
          padding: 20px;
          border-radius: 22px;
        }}
        .signal-board {{
          grid-template-columns: 1fr;
        }}
        .footer-card {{
          padding: 22px;
          flex-direction: column;
          align-items: flex-start;
        }}
      }}
    </style>
    <style>{_ARTICLE_PROSPEKTLAB_CSS}</style>
    <script type=\"application/ld+json\">{json_ld}</script>
  </head>
  <body>
    <div class=\"progress-bar\" data-progress></div>
    <div class=\"masthead\">
      <div class=\"shell masthead-inner\">
        <a class=\"brand\" href=\"{esc(hub_path)}\">
          <span class=\"brand-mark\"></span>
          <span class=\"brand-text\">ProspektLab Research</span>
        </a>
        <div class=\"masthead-links\">
          <a href=\"{esc(hub_path)}\">All insights</a>
          <a href=\"/#/dashboard\">Dashboard</a>
          <a href=\"/#/contact\">Contact</a>
        </div>
      </div>
    </div>
    <header class=\"hero\">
      <div class=\"shell\">
        <section class=\"hero-frame\">
          <div class=\"hero-grid\">
            <div>
              <div class=\"eyebrow\">{esc(article.hero_eyebrow)}</div>
              <h1>{esc(article.hero_title)}</h1>
              <p class=\"hero-summary\">{esc(article.hero_summary)}</p>
              <p class=\"hero-context\">{esc(hero_context)}</p>
            </div>
            <div>{image_markup}</div>
          </div>
          <div class=\"signal-board\">{highlight_html}</div>
        </section>
      </div>
    </header>
    <main>
      <div class=\"shell story-shell\">
        <aside class=\"story-rail\">
          <section class=\"rail-card toc\">
            <div class=\"rail-label\">On this page</div>
            <ol>{''.join(toc_items)}</ol>
          </section>
          <section class=\"rail-card\">
            <div class=\"rail-label\">How to read this</div>
            <ul>{methodology_html}</ul>
          </section>
          {source_html}
        </aside>
        <article class=\"article-flow\">
          {''.join(section_html)}
          <section class=\"faq-shell\" id=\"faq\">
            <div class=\"section-kicker\">Retail investor FAQ</div>
            <h2>Questions readers usually ask after the numbers</h2>
            <div class=\"faq-grid\">{faq_items}</div>
          </section>
        </article>
      </div>
    </main>
    <footer class=\"footer\">
      <div class=\"shell\">
        <div class=\"footer-card\">
          <div>
            <div class=\"rail-label\" style=\"color: rgba(246, 248, 252, 0.64);\">ProspektLab</div>
            <h3 style=\"color:#f6f8fc;\">Research pages should feel like finished editorial products.</h3>
            <p>This page is designed to read like a serious market note, not a raw model export.</p>
          </div>
          <a class=\"footer-link\" href=\"{esc(article.cta_href)}\">{esc(article.cta_label)}</a>
        </div>
      </div>
    </footer>
    <script src="/insights/research-runtime.js" defer></script>
  </body>
</html>
"""


def _compose_editorial_cover_prompt(article: ContentArticlePackage) -> str:
    profile = _topic_profile(article)
    visual_plan = _visual_story_plan(article)
    intent = _story_intent(article)
    base_prompt = (article.image_prompt or "").strip()
    if not base_prompt:
        base_prompt = (
            f"Premium editorial cover for {article.title}. High-end business publication look, layered market "
            "graphics, documents, devices, and one strong central subject tied to the story."
        )
    return (
        f"{base_prompt} Use ProspektLab's dark navy, glass-panel, blue/cyan/green accent system; avoid beige, tan, parchment, newspaper, or warm editorial palettes. "
        f"Story topic: {article.title}. "
        f"Story intent: {intent}. "
        f"Topic direction: {profile['prompt']}. "
        f"Central branded object: {visual_plan['hero_object']}. "
        f"Business cues: {', '.join(visual_plan['business_cues'])}. "
        f"Event clues: {', '.join(visual_plan['event_cues'])}. "
        "Create one coherent scene where the main object, business model, and event signal are visually obvious at first glance. "
        "Landscape 3:2 composition for a news-card thumbnail and report hero, with a centered safe area that survives responsive crops. "
        "Match a light, elegant financial publication UI with cream paper tones, balanced spacing, and attractive editorial depth. "
        "Keep all important elements fully inside frame with safe margins. "
        "No stretched or distorted objects. Do not crop the central branded object or key evidence props. "
        "Use clear subject separation, balanced contrast, and readable depth so the card feels interactive and professional on a light interface. "
        "No stretched perspective, no cropped main subject, no border text, no watermark, no UI chrome. "
        "Use rich lighting, dimensional materials, and a polished financial newsroom aesthetic."
    )


def _story_intent(article: ContentArticlePackage) -> str:
    text = _repair_mojibake_text(
        " ".join(
            [
                article.hero_eyebrow,
                article.title,
                article.description,
                article.hero_summary,
                *article.keywords[:10],
            ]
        )
    ).lower()
    if any(token in text for token in ("probe", "enforcement", "ed", "sebi", "order", "adjudication", "litigation", "investigation")):
        return "Explain the regulatory risk, timeline pressure, and compliance consequences around the event."
    if any(token in text for token in ("acquire", "acquisition", "stake", "deal", "merger", "investment", "majority")):
        return "Show strategic deal logic, ownership shift, and integration consequences for the business."
    if any(token in text for token in ("earnings", "results", "guidance", "margin", "revenue", "profit", "ebit")):
        return "Highlight what moved in the quarter, what management signaled, and what readers should monitor next."
    if any(token in text for token in ("trend", "sector", "macro", "policy", "market")):
        return "Frame the wider market narrative and expose the structural drivers behind the trend."
    return "Clarify the company event with strong business context and practical takeaways for informed readers."


def _cover_seed(article: ContentArticlePackage) -> int:
    payload = f"{article.slug}|{article.title}|{'|'.join(article.keywords[:4])}"
    return int(hashlib.sha256(payload.encode('utf-8')).hexdigest()[:8], 16)


def _normalize_image_base_url(raw: str | None) -> str | None:
    value = (raw or "").strip().rstrip("/")
    if not value:
        return None
    lowered = value.lower()
    if lowered.endswith("/v1"):
        return value
    if lowered.endswith("/openai/v1"):
        return value
    if "/openai/" in lowered:
        return value
    return f"{value}/openai/v1"


def _normalize_foundry_resource_endpoint(raw: str | None) -> str | None:
    value = (raw or "").strip().rstrip("/")
    if not value:
        return None
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _foundry_image_generation_url(resource_endpoint: str, deployment: str, api_version: str) -> str:
    safe_endpoint = resource_endpoint.rstrip("/")
    safe_deployment = deployment.strip().strip("/")
    safe_version = api_version.strip()
    return f"{safe_endpoint}/openai/deployments/{safe_deployment}/images/generations?api-version={safe_version}"


def _foundry_openai_base_url(resource_endpoint: str) -> str:
    return _normalize_image_base_url(resource_endpoint) or f"{resource_endpoint.rstrip('/')}/openai/v1"


def _normalize_url(raw: str | None) -> str | None:
    value = (raw or "").strip().rstrip("/")
    return value or None


def _resolve_image_client_config() -> _ImageClientConfig | None:
    provider = (os.getenv("FINAGENT_CONTENT_IMAGE_PROVIDER") or "").strip().lower()
    foundry_key = (
        os.getenv("AZURE_AI_FOUNDRY_API_KEY")
        or os.getenv("AZURE_AI_PROJECTS_API_KEY")
        or os.getenv("AZURE_OPENAI_API_KEY")
        or ""
    ).strip()
    foundry_image_endpoint = _normalize_url(
        os.getenv("AZURE_AI_FOUNDRY_IMAGE_ENDPOINT")
        or os.getenv("AZURE_AI_PROJECTS_IMAGE_ENDPOINT")
        or os.getenv("AZURE_OPENAI_IMAGE_ENDPOINT")
    )
    foundry_openai_base_url = _normalize_image_base_url(
        os.getenv("AZURE_AI_FOUNDRY_OPENAI_BASE_URL")
        or os.getenv("AZURE_AI_PROJECTS_OPENAI_BASE_URL")
        or os.getenv("AZURE_OPENAI_BASE_URL")
    )
    foundry_resource_endpoint = _normalize_foundry_resource_endpoint(
        os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
        or os.getenv("AZURE_AI_PROJECT_ENDPOINT")
        or os.getenv("AZURE_OPENAI_ENDPOINT")
    )
    allow_legacy_image_model = (os.getenv("FINAGENT_CONTENT_IMAGE_ALLOW_GPT_IMAGE_1") or "").strip().lower() in {"1", "true", "yes", "on"}

    def _normalize_image_model(value: str) -> str:
        cleaned = (value or "").strip()
        if cleaned.lower() == "gpt-image-1" and not allow_legacy_image_model:
            return "chatgpt-image-2"
        return cleaned

    foundry_deployment = (
        os.getenv("AZURE_AI_FOUNDRY_IMAGE_DEPLOYMENT")
        or os.getenv("AZURE_AI_PROJECTS_IMAGE_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_IMAGE_DEPLOYMENT")
        or "chatgpt-image-2"
    ).strip()
    foundry_deployment = _normalize_image_model(foundry_deployment)
    foundry_api_version = (os.getenv("AZURE_AI_FOUNDRY_IMAGE_API_VERSION") or "2025-04-01-preview").strip()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    openai_base_url = _normalize_image_base_url(os.getenv("FINAGENT_CONTENT_IMAGE_BASE_URL"))
    openai_model = _normalize_image_model((os.getenv("FINAGENT_CONTENT_IMAGE_MODEL") or "chatgpt-image-2").strip())
    foundry_request_url = None
    if foundry_resource_endpoint and foundry_deployment:
        foundry_request_url = _foundry_image_generation_url(foundry_resource_endpoint, foundry_deployment, foundry_api_version)
    elif foundry_openai_base_url and foundry_deployment:
        inferred_resource_endpoint = _normalize_foundry_resource_endpoint(foundry_openai_base_url)
        if inferred_resource_endpoint:
            foundry_request_url = _foundry_image_generation_url(inferred_resource_endpoint, foundry_deployment, foundry_api_version)

    if provider in {"foundry", "azure", "azure_foundry", "mai"}:
        if foundry_key and (foundry_image_endpoint or foundry_openai_base_url or foundry_resource_endpoint) and foundry_deployment:
            return _ImageClientConfig(
                api_key=foundry_key,
                model=foundry_deployment,
                provider="azure-foundry",
                base_url=foundry_openai_base_url or foundry_resource_endpoint,
                image_endpoint=foundry_image_endpoint,
                request_url=foundry_request_url,
                api_version=foundry_api_version,
            )
        logger.warning("Azure Foundry image provider selected but required config is missing; falling back")

    if provider == "openai":
        if openai_key and openai_model:
            return _ImageClientConfig(
                api_key=openai_key,
                model=openai_model,
                provider="openai",
                base_url=openai_base_url,
            )
        logger.warning("OpenAI image provider selected but OPENAI_API_KEY or model is missing")

    has_explicit_foundry_route = bool(foundry_image_endpoint or foundry_openai_base_url)
    if (
        provider not in {"openai"}
        and foundry_key
        and has_explicit_foundry_route
        and foundry_deployment
    ):
        return _ImageClientConfig(
            api_key=foundry_key,
            model=foundry_deployment,
            provider="azure-foundry",
            base_url=foundry_openai_base_url or foundry_resource_endpoint,
            image_endpoint=foundry_image_endpoint,
            request_url=foundry_request_url,
            api_version=foundry_api_version,
        )

    # Default routing: chatgpt-image-2 should use OPENAI_API_KEY unless caller
    # provides a concrete Foundry image route or explicitly forces Foundry.
    if provider not in {"foundry", "azure", "azure_foundry", "mai"}:
        if openai_key and openai_model.lower() == "chatgpt-image-2":
            return _ImageClientConfig(
                api_key=openai_key,
                model=openai_model,
                provider="openai",
                base_url=openai_base_url,
            )

    if foundry_key and (foundry_image_endpoint or foundry_openai_base_url or foundry_resource_endpoint) and foundry_deployment:
        return _ImageClientConfig(
            api_key=foundry_key,
            model=foundry_deployment,
            provider="azure-foundry",
            base_url=foundry_openai_base_url or foundry_resource_endpoint,
            image_endpoint=foundry_image_endpoint,
            request_url=foundry_request_url,
            api_version=foundry_api_version,
        )
    if openai_key and openai_model:
        return _ImageClientConfig(
            api_key=openai_key,
            model=openai_model,
            provider="openai",
            base_url=openai_base_url,
        )
    return None


def _visual_story_plan(article: ContentArticlePackage) -> dict[str, Any]:
    text = _repair_mojibake_text(" ".join([
        article.hero_eyebrow,
        article.title,
        article.description,
        article.hero_summary,
        *article.keywords[:8],
    ])).lower()
    plan = {
        "object_kind": "panel",
        "hero_object": "a branded publication panel with layered market documents",
        "business_cues": ["research notes", "charts", "statement pages"],
        "event_cues": ["story-specific highlight panel", "supporting documents", "light newsroom depth"],
        "coverage_label": "Coverage",
    }
    if any(token in text for token in ("quick commerce", "delivery", "grocery", "e-commerce", "retail app", "retail platform")):
        plan.update({
            "object_kind": "bag",
            "hero_object": "a branded delivery bag or parcel crate that clearly reflects the company's delivery business",
            "business_cues": ["shopping receipts", "route pins", "app screens", "parcel labels"],
            "coverage_label": "Delivery",
        })
    elif any(token in text for token in ("bank", "banking", "fintech", "payments", "nbfc", "insurance")):
        plan.update({
            "object_kind": "card",
            "hero_object": "a branded banking or payments card with ledger-style overlays",
            "business_cues": ["account ledger", "payment device", "balance sheet pages"],
            "coverage_label": "Finance",
        })
    elif any(token in text for token in ("software", "technology", "it services", "cloud", "saas", "consulting", "infosys", "tcs", "wipro", "hcl")):
        plan.update({
            "object_kind": "screen",
            "hero_object": "a branded technology screen or terminal surrounded by deal and execution material",
            "business_cues": ["code-like grids", "delivery dashboards", "contract pages"],
            "coverage_label": "Technology",
        })
    elif any(token in text for token in ("travel", "airline", "aviation", "hotel", "hospitality", "rail")):
        plan.update({
            "object_kind": "suitcase",
            "hero_object": "a branded suitcase or ticket wallet representing the travel business",
            "business_cues": ["route map", "boarding pass", "terminal signage"],
            "coverage_label": "Travel",
        })
    elif any(token in text for token in ("factory", "manufacturing", "industrial", "auto", "automotive", "chemicals")):
        plan.update({
            "object_kind": "crate",
            "hero_object": "a branded industrial crate or component case tied to the operating business",
            "business_cues": ["component sketches", "plant floor grid", "production sheets"],
            "coverage_label": "Industry",
        })
    if any(token in text for token in ("probe", "enforcement", "ed", "sebi", "regulat", "order", "litigation", "investigation")):
        plan["event_cues"] = ["official seal", "case files", "investigation board", "magnifier"]
    elif any(token in text for token in ("acquire", "stake", "deal", "merger", "investment", "majority")):
        plan["event_cues"] = ["transaction papers", "network map", "connected entities", "capital trail"]
    elif any(token in text for token in ("earnings", "results", "guidance", "margin", "revenue", "profit")):
        plan["event_cues"] = ["earnings memo", "guidance board", "results chart", "statement highlights"]
    return plan


def _topic_profile(article: ContentArticlePackage) -> dict[str, Any]:
    text = _repair_mojibake_text(" ".join([
        article.hero_eyebrow,
        article.title,
        article.description,
        article.hero_summary,
        *article.keywords[:8],
    ])).lower()

    if any(token in text for token in ("earnings", "results", "guidance", "margin", "revenue", "profit", "ebit")):
        if any(token in text for token in ("guidance upgrade", "raised fy", "raised full-year", "outlook improved", "first guidance upgrade")):
            return {
                "kind": "earnings",
                "variant": "guidance",
                "badge": "Outlook",
                "cues": ["Guidance", "Growth", "Outlook"],
                "prompt": "A dark ProspektLab earnings-and-guidance cover with glass forecast cards, upward momentum, management outlook cues, and a premium blue-cyan publication finish",
            }
        if any(token in text for token in ("deal", "order", "tcv", "pipeline", "wins")):
            return {
                "kind": "earnings",
                "variant": "dealwins",
                "badge": "Earnings",
                "cues": ["Deal wins", "Order book", "Margins"],
                "prompt": "A dark ProspektLab earnings cover focused on deal wins, order-book momentum, statement pages, and a strong company-linked visual center",
            }
        return {
            "kind": "earnings",
            "variant": "standard",
            "badge": "Earnings",
            "cues": ["Revenue", "Margins", "Guidance"],
            "prompt": "A dark ProspektLab earnings cover with statement pages, a guidance chart, polished market panels, and a strong focal subject tied to the company",
        }
    if "sebi" in text or "regulat" in text or "order" in text or "probe" in text:
        return {
            "kind": "regulation",
            "variant": "standard",
            "badge": "Regulation",
            "cues": ["Order", "Filings", "Timeline"],
            "prompt": "A dark ProspektLab compliance scene with official papers, a verification seal, timeline markers, and premium legal-finance details",
        }
    if any(token in text for token in ("acquire", "stake", "deal", "invest", "merger", "majority")):
        return {
            "kind": "deal",
            "variant": "standard",
            "badge": "Deal",
            "cues": ["Stake", "Capital", "Network"],
            "prompt": "A dark ProspektLab M&A editorial image with connected entities, transaction documents, sector props when relevant, and a confident publication finish",
        }
    if any(token in text for token in ("trend", "sector", "theme", "macro", "policy")):
        return {
            "kind": "trend",
            "variant": "standard",
            "badge": "Trend",
            "cues": ["Sector", "Momentum", "Shift"],
            "prompt": "A dark ProspektLab market-trend visual with layered charts, sector tiles, policy papers, and calm strategic composition",
        }
    if any(token in text for token in ("company", "ownership", "board", "governance", "shareholder")):
        return {
            "kind": "company",
            "variant": "standard",
            "badge": "Company",
            "cues": ["Ownership", "Board", "Capital"],
            "prompt": "A dark ProspektLab company-intelligence cover with governance papers, corporate architecture, connected nodes, and a premium research-desk feel",
        }
    return {
        "kind": "company",
        "variant": "standard",
        "badge": "Research",
        "cues": ["Coverage", "Signals", "Context"],
        "prompt": "A dark ProspektLab market-research cover with balanced editorial composition, company context, glass panels, and blue-cyan publication styling",
    }


def _cover_palette(article: ContentArticlePackage) -> dict[str, tuple[int, int, int]]:
    profile = _topic_profile(article)
    palettes: dict[str, list[dict[str, tuple[int, int, int]]]] = {
        "earnings": [
            {
                "bg_top": (3, 6, 13),
                "bg_bottom": (7, 17, 31),
                "frame": (8, 16, 32),
                "panel_top": (10, 22, 44),
                "panel_bottom": (5, 12, 26),
                "ink": (248, 251, 255),
                "muted": (168, 180, 200),
                "line": (91, 124, 173),
                "accent": (96, 165, 250),
                "accent_soft": (52, 211, 153),
                "accent_alt": (139, 92, 246),
                "glow_a": (37, 99, 235),
                "glow_b": (52, 211, 153),
                "chip": (96, 165, 250),
            },
            {
                "bg_top": (4, 8, 18),
                "bg_bottom": (9, 24, 48),
                "frame": (8, 18, 38),
                "panel_top": (12, 26, 52),
                "panel_bottom": (5, 12, 26),
                "ink": (248, 251, 255),
                "muted": (174, 187, 208),
                "line": (86, 119, 168),
                "accent": (56, 189, 248),
                "accent_soft": (96, 165, 250),
                "accent_alt": (52, 211, 153),
                "glow_a": (96, 165, 250),
                "glow_b": (139, 92, 246),
                "chip": (56, 189, 248),
            },
        ],
        "regulation": [
            {
                "bg_top": (3, 6, 13),
                "bg_bottom": (13, 18, 37),
                "frame": (9, 18, 38),
                "panel_top": (14, 24, 48),
                "panel_bottom": (6, 12, 25),
                "ink": (248, 251, 255),
                "muted": (174, 187, 208),
                "line": (98, 116, 154),
                "accent": (96, 165, 250),
                "accent_soft": (52, 211, 153),
                "accent_alt": (251, 113, 133),
                "glow_a": (37, 99, 235),
                "glow_b": (251, 113, 133),
                "chip": (96, 165, 250),
            }
        ],
        "deal": [
            {
                "bg_top": (3, 6, 13),
                "bg_bottom": (8, 22, 42),
                "frame": (9, 18, 38),
                "panel_top": (13, 29, 58),
                "panel_bottom": (5, 12, 26),
                "ink": (248, 251, 255),
                "muted": (168, 180, 200),
                "line": (91, 124, 173),
                "accent": (52, 211, 153),
                "accent_soft": (96, 165, 250),
                "accent_alt": (139, 92, 246),
                "glow_a": (52, 211, 153),
                "glow_b": (96, 165, 250),
                "chip": (52, 211, 153),
            }
        ],
        "company": [
            {
                "bg_top": (3, 6, 13),
                "bg_bottom": (7, 17, 31),
                "frame": (8, 16, 32),
                "panel_top": (10, 22, 44),
                "panel_bottom": (4, 10, 22),
                "ink": (248, 251, 255),
                "muted": (168, 180, 200),
                "line": (91, 124, 173),
                "accent": (96, 165, 250),
                "accent_soft": (52, 211, 153),
                "accent_alt": (199, 210, 254),
                "glow_a": (37, 99, 235),
                "glow_b": (52, 211, 153),
                "chip": (96, 165, 250),
            }
        ],
        "trend": [
            {
                "bg_top": (3, 6, 13),
                "bg_bottom": (8, 22, 42),
                "frame": (8, 16, 32),
                "panel_top": (11, 25, 52),
                "panel_bottom": (5, 12, 26),
                "ink": (248, 251, 255),
                "muted": (174, 187, 208),
                "line": (86, 119, 168),
                "accent": (96, 165, 250),
                "accent_soft": (52, 211, 153),
                "accent_alt": (139, 92, 246),
                "glow_a": (37, 99, 235),
                "glow_b": (52, 211, 153),
                "chip": (96, 165, 250),
            }
        ],
    }
    variants = palettes.get(profile["kind"], palettes["earnings"])
    return variants[_cover_seed(article) % len(variants)]


def _cover_label(article: ContentArticlePackage) -> str:
    tokens = re.findall(r"[A-Za-z0-9&]+", article.hero_title or article.title)
    stop = {"Q1", "Q2", "Q3", "Q4", "FY24", "FY25", "FY26", "THE", "AND", "WHAT", "WITH"}
    for token in tokens:
        if token.upper() in stop:
            continue
        if token.isupper() and 2 <= len(token) <= 8:
            return token
        if token[0].isalpha() and 3 <= len(token) <= 10:
            return token.title()
    return "Market"


def _content_badge(article: ContentArticlePackage) -> str:
    text = _repair_mojibake_text(" ".join([article.hero_eyebrow, article.title, article.description] + article.keywords[:4])).lower()
    if "sebi" in text or "regulat" in text:
        return "Regulation"
    if "earnings" in text or "results" in text or "margin" in text:
        return "Earnings"
    if "company" in text or "ownership" in text:
        return "Company"
    if "trend" in text or "sector" in text:
        return "Trend"
    return "Research"


def _fit_font(font_paths: list[str], size: int):
    from PIL import ImageFont

    for path in font_paths:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_cover_png(article: ContentArticlePackage) -> bytes | None:
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except Exception:
        return None

    width, height = 1600, 1000
    profile = _topic_profile(article)
    visual_plan = _visual_story_plan(article)
    palette = _cover_palette(article)
    label = _cover_label(article)
    badge = profile["badge"]
    cues = profile["cues"]

    font_paths_bold = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/trebucbd.ttf",
    ]
    font_paths_regular = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/calibri.ttf",
    ]
    mono_paths = [
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/cour.ttf",
        "C:/Windows/Fonts/lucon.ttf",
    ]

    eyebrow_font = _fit_font(mono_paths, 20)
    cue_font = _fit_font(font_paths_bold, 22)
    deck_font = _fit_font(font_paths_regular, 28)
    body_font = _fit_font(font_paths_regular, 20)
    metric_font = _fit_font(font_paths_bold, 26)
    label_font = _fit_font(font_paths_bold, 220 if len(label) <= 4 else 170 if len(label) <= 6 else 140)

    resample_ns = getattr(Image, "Resampling", Image)

    def metric_tokens() -> list[str]:
        blob = _repair_mojibake_text(" ".join([
            article.title,
            article.description,
            article.hero_summary,
            *article.keywords[:6],
        ]))
        blob = blob.replace("\u2013", "-").replace("\u2014", "-")
        found: list[str] = []
        patterns = [
            r"\$\d+(?:\.\d+)?\s?[BM]",
            r"(?:FY\d{2}\s)?\d+(?:\.\d+)?%\s?-\s?\d+(?:\.\d+)?%",
            r"(?:Rs\.?|INR)\s?\d[\d,]*(?:\.\d+)?\s?Cr",
            r"\d+(?:\.\d+)?%\s?[A-Za-z]{0,12}",
            r"\d+(?:\.\d+)?\s?bps",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, blob):
                token = re.sub(r"\s+", " ", match).strip(" -")
                if token and token not in found:
                    found.append(token)
                if len(found) == 4:
                    return found
        return found

    metrics = metric_tokens()
    story_blob = _repair_mojibake_text(" ".join([article.title, article.description, article.hero_summary])).replace("\u2013", "-").replace("\u2014", "-")
    guidance_match = re.search(r"(?:FY\d{2}\s)?\d+(?:\.\d+)?%\s?-\s?\d+(?:\.\d+)?%", story_blob)
    deal_match = re.search(r"\$\d+(?:\.\d+)?\s?[BM]", story_blob)
    margin_match = re.search(r"\d+(?:\.\d+)?%\s?(?:EBIT|margin)?", story_blob)
    revenue_match = re.search(r"(?:Rs\.?|INR)?\s?\d[\d,]*(?:\.\d+)?\s?Cr", story_blob)

    if profile["kind"] == "earnings" and profile.get("variant") == "guidance":
        primary_metric = guidance_match.group(0) if guidance_match else (margin_match.group(0) if margin_match else (metrics[0] if metrics else cues[0]))
        secondary_metric = margin_match.group(0) if margin_match else (deal_match.group(0) if deal_match else (metrics[1] if len(metrics) > 1 else cues[min(1, len(cues) - 1)]))
    elif profile["kind"] == "earnings" and profile.get("variant") == "dealwins":
        primary_metric = deal_match.group(0) if deal_match else (metrics[0] if metrics else cues[0])
        secondary_metric = margin_match.group(0) if margin_match else (metrics[1] if len(metrics) > 1 else cues[min(1, len(cues) - 1)])
    else:
        primary_metric = metrics[0] if metrics else cues[0]
        secondary_metric = revenue_match.group(0) if revenue_match else (metrics[1] if len(metrics) > 1 else cues[min(1, len(cues) - 1)])

    def blend(a: tuple[int, int, int], b: tuple[int, int, int], mix: float) -> tuple[int, int, int]:
        return tuple(int(a[idx] + (b[idx] - a[idx]) * mix) for idx in range(3))

    def text_width(font, text: str) -> int:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]

    def wrap_text(font, text: str, max_width: int, max_lines: int) -> list[str]:
        words = text.split()
        if not words:
            return []
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if not current or text_width(font, candidate) <= max_width:
                current = candidate
                continue
            lines.append(current)
            current = word
            if len(lines) == max_lines - 1:
                break
        if current and len(lines) < max_lines:
            lines.append(current)
        consumed = sum(len(line.split()) for line in lines)
        if consumed < len(words) and lines:
            leftover = " ".join(words[consumed:])
            candidate = f"{lines[-1]} {leftover}".strip()
            while text_width(font, candidate + "...") > max_width and " " in candidate:
                candidate = candidate.rsplit(" ", 1)[0]
            lines[-1] = candidate.rstrip() + "..."
        return lines[:max_lines]

    def rounded_gradient(
        size: tuple[int, int],
        radius: int,
        top: tuple[int, int, int],
        bottom: tuple[int, int, int],
        *,
        outline: tuple[int, int, int] | None = None,
    ) -> Image.Image:
        w, h = size
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ldraw = ImageDraw.Draw(layer)
        for y in range(h):
            ldraw.line((0, y, w, y), fill=blend(top, bottom, y / max(h - 1, 1)) + (255,))
        mask = Image.new("L", (w, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
        card = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        card.paste(layer, (0, 0), mask)
        if outline:
            ImageDraw.Draw(card).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, outline=outline + (165,), width=2)
        return card

    def paint_shadow(base: Image.Image, layer: Image.Image, position: tuple[int, int], *, blur: int = 36, alpha: int = 68, offset: tuple[int, int] = (0, 28)) -> None:
        shadow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        alpha_layer = layer.getchannel("A").point(lambda value: value * alpha // 255)
        shadow_layer = Image.new("RGBA", layer.size, (84, 60, 38, 255))
        shadow_layer.putalpha(alpha_layer)
        shadow.paste(shadow_layer, (position[0] + offset[0], position[1] + offset[1]), shadow_layer)
        base.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(blur)))

    def paste_rotated(base: Image.Image, layer: Image.Image, position: tuple[int, int], angle: float, *, shadow_offset: tuple[int, int] = (0, 28), shadow_alpha: int = 64) -> None:
        rotated = layer.rotate(angle, expand=True, resample=resample_ns.BICUBIC)
        x = int(position[0] - rotated.size[0] / 2)
        y = int(position[1] - rotated.size[1] / 2)
        paint_shadow(base, rotated, (x, y), offset=shadow_offset, alpha=shadow_alpha)
        base.alpha_composite(rotated, (x, y))

    def make_chip(text: str, *, fill: tuple[int, int, int], ink: tuple[int, int, int] = (255, 255, 255), padding_x: int = 26) -> Image.Image:
        tw = text_width(metric_font, text)
        chip = Image.new("RGBA", (tw + padding_x * 2, 58), (0, 0, 0, 0))
        cdraw = ImageDraw.Draw(chip)
        cdraw.rounded_rectangle((0, 0, chip.size[0] - 1, 57), radius=20, fill=fill + (238,), outline=(255, 255, 255, 90), width=1)
        cdraw.text((padding_x, 14), text, font=metric_font, fill=ink + (255,))
        return chip

    def draw_business_object(draw: Any, box: tuple[int, int, int, int], *, kind: str, fill: tuple[int, int, int], accent: tuple[int, int, int]) -> None:
        x0, y0, x1, y1 = box
        if kind == "bag":
            draw.rounded_rectangle((x0, y0 + 34, x1, y1), radius=28, fill=fill + (190,), outline=(255, 255, 255, 120), width=2)
            draw.arc((x0 + 54, y0 - 10, x1 - 54, y0 + 86), start=200, end=340, fill=(255, 255, 255, 190), width=8)
            draw.line((x0 + 64, y0 + 48, x1 - 64, y0 + 48), fill=accent + (180,), width=6)
            return
        if kind == "card":
            draw.rounded_rectangle((x0, y0 + 18, x1, y1), radius=26, fill=fill + (188,), outline=(255, 255, 255, 120), width=2)
            draw.rounded_rectangle((x0 + 26, y0 + 58, x0 + 108, y0 + 102), radius=10, fill=(255, 255, 255, 120))
            draw.line((x0 + 28, y0 + 132, x1 - 28, y0 + 132), fill=(255, 255, 255, 138), width=5)
            return
        if kind == "suitcase":
            draw.rounded_rectangle((x0, y0 + 38, x1, y1), radius=24, fill=fill + (188,), outline=(255, 255, 255, 120), width=2)
            draw.rounded_rectangle((x0 + 74, y0 + 6, x1 - 74, y0 + 54), radius=16, outline=(255, 255, 255, 180), width=6)
            return
        if kind == "crate":
            draw.rounded_rectangle((x0, y0 + 30, x1, y1), radius=20, fill=fill + (188,), outline=(255, 255, 255, 120), width=2)
            for step in range(1, 4):
                draw.line((x0 + step * ((x1 - x0) // 4), y0 + 40, x0 + step * ((x1 - x0) // 4), y1 - 12), fill=(255, 255, 255, 106), width=3)
            return
        if kind == "screen":
            draw.rounded_rectangle((x0, y0, x1, y1 - 28), radius=22, fill=fill + (188,), outline=(255, 255, 255, 120), width=2)
            draw.rounded_rectangle((x0 + 90, y1 - 26, x1 - 90, y1), radius=10, fill=(255, 255, 255, 170))
            return
        draw.rounded_rectangle((x0, y0, x1, y1), radius=28, fill=fill + (178,), outline=(255, 255, 255, 110), width=2)

    image = Image.new("RGBA", (width, height), palette["bg_top"] + (255,))
    bg = ImageDraw.Draw(image)
    for y in range(height):
        bg.line((0, y, width, y), fill=blend(palette["bg_top"], palette["bg_bottom"], y / max(height - 1, 1)) + (255,))

    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse((-120, -40, 760, 780), fill=palette["glow_a"] + (110,))
    gdraw.ellipse((900, -20, 1680, 780), fill=palette["glow_b"] + (105,))
    gdraw.ellipse((420, 500, 1180, 1120), fill=blend(palette["glow_a"], palette["glow_b"], 0.5) + (80,))
    gdraw.polygon([(640, -20), (920, -20), (1140, 760), (420, 760)], fill=(255, 255, 255, 52))
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(92)))

    grid = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    grid_draw = ImageDraw.Draw(grid)
    for x in range(72, width, 96):
        grid_draw.line((x, 64, x, height - 64), fill=palette["line"] + (24,), width=1)
    for y in range(72, height, 78):
        grid_draw.line((64, y, width - 64, y), fill=palette["line"] + (20,), width=1)
    image.alpha_composite(grid)

    trails = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(trails)
    tdraw.arc((120, 260, 1240, 1060), start=188, end=308, fill=palette["accent_soft"] + (62,), width=4)
    tdraw.arc((360, 110, 1540, 930), start=198, end=332, fill=palette["accent_alt"] + (56,), width=5)
    tdraw.arc((540, 180, 1660, 980), start=198, end=316, fill=palette["accent"] + (42,), width=4)
    image.alpha_composite(trails.filter(ImageFilter.GaussianBlur(8)))

    hero = rounded_gradient(
        (770, 500),
        46,
        blend(palette["accent_alt"], (255, 255, 255), 0.12),
        blend(palette["accent"], (255, 255, 255), 0.04),
        outline=palette["line"],
    )
    hdraw = ImageDraw.Draw(hero)
    for y in range(64, hero.size[1] - 26, 42):
        hdraw.line((36, y, hero.size[0] - 36, y), fill=(255, 255, 255, 18), width=1)
    hero_glow = Image.new("RGBA", hero.size, (0, 0, 0, 0))
    hgdraw = ImageDraw.Draw(hero_glow)
    hgdraw.ellipse((80, 90, 620, 520), fill=(255, 255, 255, 64))
    hgdraw.polygon([(540, 0), (770, 0), (770, 260), (470, 210)], fill=(255, 255, 255, 20))
    hero.alpha_composite(hero_glow.filter(ImageFilter.GaussianBlur(28)))
    hdraw.text((54, 48), article.hero_eyebrow[:28].upper(), font=eyebrow_font, fill=(255, 255, 255, 198))
    hero.alpha_composite(make_chip(primary_metric, fill=palette["chip"]), (48, 100))
    for idx, cue in enumerate(cues[:2]):
        cue_chip = make_chip(cue, fill=blend(palette["accent_soft"], (255, 255, 255), 0.22), ink=palette["ink"])
        hero.alpha_composite(cue_chip, (48, 178 + idx * 72))
    label_w = text_width(label_font, label)
    label_x = (hero.size[0] - label_w) // 2
    label_y = 210
    for offset, alpha in ((16, 34), (9, 58), (0, 236)):
        hdraw.text((label_x + offset, label_y + offset // 2), label, font=label_font, fill=(255, 255, 255, alpha))
    draw_business_object(
        hdraw,
        (520, 150, 712, 338),
        kind=str(visual_plan.get("object_kind") or "panel"),
        fill=blend(palette["accent_soft"], (255, 255, 255), 0.22),
        accent=palette["accent"],
    )
    hero.alpha_composite(make_chip(badge, fill=palette["chip"]), (46, hero.size[1] - 92))
    hdraw.line((530, 132, 660, 96, 730, 152), fill=(255, 255, 255, 148), width=8)

    analytics = rounded_gradient((560, 420), 42, palette["frame"], palette["panel_bottom"], outline=palette["line"])
    adraw = ImageDraw.Draw(analytics)
    adraw.rounded_rectangle((26, 26, 534, 88), radius=28, fill=(255, 255, 255, 150))
    analytics.alpha_composite(make_chip(secondary_metric, fill=blend(palette["accent_alt"], (255, 255, 255), 0.42), ink=palette["ink"], padding_x=22), (32, 30))
    graph = Image.new("RGBA", analytics.size, (0, 0, 0, 0))
    g = ImageDraw.Draw(graph)
    for x in range(44, 528, 66):
        g.line((x, 96, x, 380), fill=palette["line"] + (84,), width=1)
    for y in range(108, 380, 56):
        g.line((34, y, 526, y), fill=palette["line"] + (70,), width=1)
    watermark_font = _fit_font(font_paths_bold, 150 if len(label) <= 5 else 128)
    g.text((108, 120), label, font=watermark_font, fill=palette["ink"] + (34,))
    bars = [122, 92, 176, 144, 214, 188]
    if profile["kind"] == "earnings" and profile.get("variant") == "guidance":
        bars = [98, 116, 138, 160, 202, 230]
    elif profile["kind"] == "deal":
        bars = [86, 154, 126, 178, 212, 238]
    for idx, value in enumerate(bars):
        bx = 78 + idx * 70
        fill = palette["accent_soft"] if idx % 2 == 0 else palette["accent_alt"]
        g.rounded_rectangle((bx, 338 - value, bx + 46, 338), radius=16, fill=fill + (225,))
    points = [(56, 260), (138, 312), (214, 292), (302, 208), (388, 242), (472, 150)]
    if profile["kind"] == "earnings" and profile.get("variant") == "guidance":
        points = [(56, 292), (144, 252), (232, 240), (314, 204), (400, 166), (486, 126)]
    g.line(points, fill=palette["accent"] + (255,), width=12, joint="curve")
    for px, py in points:
        g.ellipse((px - 9, py - 9, px + 9, py + 9), fill=(255, 255, 255, 236))
    analytics.alpha_composite(graph)

    memo = rounded_gradient((376, 252), 34, (255, 252, 246), blend(palette["panel_bottom"], (255, 255, 255), 0.52), outline=palette["line"])
    mdraw = ImageDraw.Draw(memo)
    memo_title = "Research memo" if profile["kind"] != "regulation" else "Action memo"
    mdraw.text((28, 24), memo_title, font=cue_font, fill=palette["ink"] + (214,))
    snippet_lines = wrap_text(body_font, article.title, 300, 2)
    for idx, line in enumerate(snippet_lines):
        mdraw.text((28, 66 + idx * 24), line, font=body_font, fill=palette["muted"] + (218,))
    for idx in range(4):
        y = 126 + idx * 28
        length = 236 + ((idx + 1) % 2) * 52
        mdraw.rounded_rectangle((28, y, 28 + length, y + 10), radius=5, fill=palette["line"] + (148,))
    mdraw.ellipse((224, 112, 300, 188), outline=palette["accent_soft"] + (206,), width=6)
    mdraw.ellipse((286, 90, 352, 156), outline=palette["accent_alt"] + (206,), width=6)

    focus = rounded_gradient((396, 294), 34, blend(palette["accent_soft"], (255, 255, 255), 0.56), blend(palette["accent_alt"], (255, 255, 255), 0.38), outline=palette["line"])
    fdraw = ImageDraw.Draw(focus)
    focus_title = "Guidance reset" if profile["kind"] == "earnings" and profile.get("variant") == "guidance" else "Deal momentum" if profile["kind"] == "earnings" else "Story frame"
    if profile["kind"] == "regulation":
        focus_title = "Order trail"
    elif profile["kind"] == "deal":
        focus_title = "Transaction map"
    fdraw.text((34, 30), focus_title, font=cue_font, fill=palette["ink"] + (220,))
    if profile["kind"] == "earnings" and profile.get("variant") == "guidance":
        focus.alpha_composite(make_chip(primary_metric, fill=(255, 255, 255), ink=palette["ink"], padding_x=24), (30, 84))
        path = [(52, 214), (132, 186), (208, 194), (282, 152), (346, 116)]
        fdraw.line(path, fill=palette["accent"] + (244,), width=9)
        fdraw.polygon([(334, 106), (370, 92), (348, 134)], fill=palette["accent"] + (245,))
        for px, py in path[:-1]:
            fdraw.ellipse((px - 7, py - 7, px + 7, py + 7), fill=(255, 255, 255, 230))
    elif profile["kind"] == "earnings":
        for idx in range(3):
            px = 36 + idx * 104
            fdraw.rounded_rectangle((px, 90, px + 76, 154), radius=18, fill=(255, 255, 255, 178), outline=palette["line"] + (112,), width=1)
        fdraw.text((44, 188), primary_metric, font=metric_font, fill=palette["ink"] + (218,))
        path = [(44, 236), (118, 198), (196, 216), (282, 164), (348, 122)]
        fdraw.line(path, fill=palette["accent_alt"] + (240,), width=8)
        for px, py in path:
            fdraw.ellipse((px - 7, py - 7, px + 7, py + 7), fill=(255, 255, 255, 234))
    elif profile["kind"] == "regulation":
        for idx, doc in enumerate(((40, 96, 166, 214), (116, 74, 246, 196))):
            fdraw.rounded_rectangle(doc, radius=18, fill=(255, 255, 255, 206 - idx * 20), outline=palette["line"] + (116,), width=1)
        fdraw.ellipse((260, 110, 346, 196), outline=palette["accent"] + (236,), width=8)
        fdraw.line((308, 168, 356, 220), fill=palette["accent"] + (236,), width=8)
    elif profile["kind"] == "deal":
        for idx, box in enumerate(((40, 90, 164, 182), (188, 112, 318, 204))):
            fill = (255, 255, 255, 186) if idx == 0 else (255, 255, 255, 152)
            fdraw.rounded_rectangle(box, radius=22, fill=fill, outline=palette["line"] + (110,), width=1)
        fdraw.line((164, 136, 188, 156), fill=palette["accent"] + (238,), width=8)
        fdraw.polygon([(178, 146), (208, 156), (184, 174)], fill=palette["accent"] + (236,))
        fdraw.text((38, 220), secondary_metric, font=metric_font, fill=palette["ink"] + (214,))
    else:
        focus.alpha_composite(make_chip(cues[0], fill=(255, 255, 255), ink=palette["ink"], padding_x=22), (34, 86))
        focus.alpha_composite(make_chip(cues[min(1, len(cues) - 1)], fill=(255, 255, 255), ink=palette["ink"], padding_x=22), (34, 156))
        fdraw.line((52, 240, 338, 148), fill=palette["accent_alt"] + (228,), width=7)

    device = rounded_gradient((280, 380), 32, blend(palette["panel_top"], (255, 255, 255), 0.18), blend(palette["panel_bottom"], palette["frame"], 0.25), outline=palette["line"])
    ddraw = ImageDraw.Draw(device)
    ddraw.rounded_rectangle((26, 26, 254, 64), radius=18, fill=(255, 255, 255, 136))
    ddraw.text((42, 32), str(visual_plan.get("coverage_label") or "Coverage"), font=cue_font, fill=palette["ink"] + (212,))
    ddraw.rounded_rectangle((54, 94, 226, 224), radius=26, fill=blend(palette["accent"], (255, 255, 255), 0.58) + (214,), outline=(255, 255, 255, 110), width=1)
    device_label_font = _fit_font(font_paths_bold, 74 if len(label) <= 6 else 58)
    ddraw.text(((280 - text_width(device_label_font, label)) // 2, 120), label, font=device_label_font, fill=(255, 255, 255, 236))
    ddraw.rounded_rectangle((44, 256, 236, 314), radius=22, fill=(255, 255, 255, 168), outline=palette["line"] + (104,), width=1)
    ddraw.text((64, 270), badge, font=cue_font, fill=palette["ink"] + (214,))
    ddraw.line((62, 342, 112, 312, 154, 324, 214, 272), fill=palette["accent"] + (244,), width=8)
    ddraw.polygon([(204, 264), (232, 252), (216, 286)], fill=palette["accent"] + (242,))

    connectors = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(connectors)
    route_points = [(480, 442), (704, 372), (920, 522), (1164, 434)]
    cdraw.line(route_points, fill=palette["accent"] + (116,), width=6)
    for px, py in route_points:
        cdraw.ellipse((px - 12, py - 12, px + 12, py + 12), fill=(255, 255, 255, 188), outline=palette["accent"] + (160,), width=2)
    image.alpha_composite(connectors.filter(ImageFilter.GaussianBlur(2)))

    image.alpha_composite(make_chip("PROSPEKTLAB RESEARCH", fill=(255, 255, 255), ink=palette["ink"], padding_x=22), (84, 54))

    paste_rotated(image, hero, (442, 388), -5)
    paste_rotated(image, analytics, (1180, 336), 4)
    paste_rotated(image, memo, (314, 790), -6, shadow_offset=(0, 22), shadow_alpha=58)
    paste_rotated(image, focus, (850, 798), 7, shadow_offset=(0, 22), shadow_alpha=60)
    paste_rotated(image, device, (1268, 736), -8, shadow_offset=(0, 24), shadow_alpha=60)

    footer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(footer).text((84, 934), "Markets, policy, and company moves", font=deck_font, fill=palette["ink"] + (190,))
    image.alpha_composite(footer)

    final_image = image.convert("RGB")
    buffer = io.BytesIO()
    final_image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


async def _generate_image(req: ContentAutomationRequest, article: ContentArticlePackage, route_base: str) -> tuple[bytes, str, str]:
    prompt = _compose_editorial_cover_prompt(article)
    config = _resolve_image_client_config()
    if req.include_image and config:
        try:
            logger.info(
                "Generating cover image via %s using model/deployment %s",
                config.provider,
                config.model,
            )
            if config.provider == "azure-foundry":
                import httpx

                direct_error: str | None = None
                if config.image_endpoint:
                    headers = {
                        "api-key": config.api_key,
                        "Content-Type": "application/json",
                    }
                    payload = {
                        "model": config.model,
                        "prompt": prompt,
                        "size": "1536x1024",
                    }
                    async with httpx.AsyncClient(timeout=180.0, trust_env=False) as http_client:
                        response = await http_client.post(config.image_endpoint, headers=headers, json=payload)
                    if response.is_success:
                        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
                        if content_type.startswith("image/"):
                            return response.content, ".png", content_type
                        data = response.json()
                        items = data.get("data") if isinstance(data, dict) else None
                        if isinstance(items, list) and items:
                            first = items[0] or {}
                            b64 = first.get("b64_json")
                            if b64:
                                return base64.b64decode(b64), ".png", "image/png"
                            image_url = first.get("url")
                            if image_url:
                                async with httpx.AsyncClient(timeout=60.0, trust_env=False) as http_client:
                                    image_response = await http_client.get(image_url)
                                    image_response.raise_for_status()
                                    remote_type = (image_response.headers.get("content-type") or "image/png").split(";")[0].strip()
                                    return image_response.content, ".png", remote_type or "image/png"
                    else:
                        direct_error = response.text[:400]
                        logger.warning(
                            "Azure Foundry direct image endpoint failed for deployment %s: %s",
                            config.model,
                            direct_error,
                        )

                v1_error: str | None = None
                if config.base_url:
                    from openai import AsyncOpenAI

                    client = AsyncOpenAI(
                        api_key=config.api_key,
                        base_url=_foundry_openai_base_url(config.base_url or ""),
                        http_client=httpx.AsyncClient(timeout=120.0, trust_env=False),
                    )
                    try:
                        response = await client.images.generate(
                            model=config.model,
                            prompt=prompt,
                            size="1536x1024",
                            response_format="b64_json",
                        )
                        data = response.data[0]
                        b64 = getattr(data, "b64_json", None)
                        if b64:
                            return base64.b64decode(b64), ".png", "image/png"
                    except Exception as exc:
                        v1_error = str(exc)
                        logger.warning(
                            "Azure Foundry OpenAI v1 image generation failed for deployment %s: %s",
                            config.model,
                            v1_error[:300],
                        )
                    finally:
                        await client.close()

                if config.request_url:
                    headers = {
                        "api-key": config.api_key,
                        "Content-Type": "application/json",
                    }
                    payload = {
                        "prompt": prompt,
                        "size": "1536x1024",
                        "quality": "high",
                        "output_format": "png",
                    }
                    async with httpx.AsyncClient(timeout=180.0, trust_env=False) as http_client:
                        response = await http_client.post(config.request_url, headers=headers, json=payload)
                    if response.is_success:
                        content_type = (response.headers.get("content-type") or "image/png").split(";")[0].strip()
                        return response.content, ".png", content_type or "image/png"
                    logger.error(
                        "Azure Foundry preview image generation failed with status %s for deployment %s: %s",
                        response.status_code,
                        config.model,
                        response.text[:400],
                    )
                    if direct_error:
                        logger.error("Azure Foundry direct endpoint attempt also failed: %s", direct_error)
                    if v1_error:
                        logger.error("Azure Foundry OpenAI v1 attempt also failed: %s", v1_error[:400])
                    response.raise_for_status()
            else:
                from openai import AsyncOpenAI
                import httpx

                client = AsyncOpenAI(
                    api_key=config.api_key,
                    base_url=config.base_url,
                    http_client=httpx.AsyncClient(timeout=120.0, trust_env=False),
                )
                try:
                    response = await client.images.generate(
                        model=config.model,
                        prompt=prompt,
                        size="1536x1024",
                        response_format="b64_json",
                    )
                finally:
                    await client.close()
                data = response.data[0]
                b64 = getattr(data, "b64_json", None)
                if b64:
                    return base64.b64decode(b64), ".png", "image/png"
                image_url = getattr(data, "url", None)
                if image_url:
                    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as http_client:
                        image_response = await http_client.get(image_url)
                        image_response.raise_for_status()
                        content_type = (image_response.headers.get("content-type") or "image/png").split(";")[0].strip()
                        return image_response.content, ".png", content_type or "image/png"
        except Exception:
            logger.exception("Image generation failed; falling back to local cover renderer")
    png = render_cover_png(article)
    if png:
        return png, ".png", "image/png"
    svg = render_cover_svg(article)
    return svg.encode("utf-8"), ".svg", "image/svg+xml"


def render_cover_svg(article: ContentArticlePackage) -> str:
    def wrap_lines(text: str, *, max_chars: int, max_lines: int) -> list[str]:
        words = (text or "").split()
        if not words:
            return []
        lines: list[str] = []
        current = ""
        idx = 0
        while idx < len(words):
            word = words[idx]
            candidate = f"{current} {word}".strip()
            if not current or len(candidate) <= max_chars:
                current = candidate
                idx += 1
                continue
            lines.append(current)
            current = ""
            if len(lines) == max_lines - 1:
                break
        if current and len(lines) < max_lines:
            lines.append(current)
        if idx < len(words):
            remaining = " ".join(words[idx:])
            if lines:
                lines[-1] = (lines[-1] + " " + remaining).strip()
            else:
                lines.append(remaining)
        if lines and len(lines[-1]) > max_chars:
            lines[-1] = lines[-1][: max_chars - 1].rstrip() + "..."
        return lines[:max_lines]

    title_lines = wrap_lines(article.hero_title, max_chars=18, max_lines=3)
    subtitle_lines = wrap_lines(article.description[:170], max_chars=42, max_lines=3)
    title_svg = "".join(
        f'<tspan x="96" dy="{0 if idx == 0 else 92}">{html.escape(line)}</tspan>'
        for idx, line in enumerate(title_lines)
    )
    subtitle_svg = "".join(
        f'<tspan x="96" dy="{0 if idx == 0 else 36}">{html.escape(line)}</tspan>'
        for idx, line in enumerate(subtitle_lines)
    )

    chips = article.keywords[:4]
    chip_svg: list[str] = []
    x = 96
    y = 824
    for keyword in chips:
        safe = html.escape(keyword[:24])
        width = max(158, min(280, 48 + len(safe) * 10))
        chip_svg.append(
            f'<g><rect x="{x}" y="{y}" rx="24" ry="24" width="{width}" height="56" fill="#fff7ee" fill-opacity="0.88" stroke="#17314d" stroke-opacity="0.10" />'
            f'<text x="{x + 24}" y="{y + 36}" fill="#17314d" font-size="24" font-family="Manrope, Arial, sans-serif" font-weight="700">{safe}</text></g>'
        )
        x += width + 16
        if x > 1180:
            break

    return f"""<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1536\" height=\"1024\" viewBox=\"0 0 1536 1024\" role=\"img\" aria-label=\"{html.escape(article.hero_title)}\">
  <defs>
    <linearGradient id=\"bg\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\">
      <stop offset=\"0%\" stop-color=\"#f7f1e6\" />
      <stop offset=\"58%\" stop-color=\"#efe6d7\" />
      <stop offset=\"100%\" stop-color=\"#dce7f1\" />
    </linearGradient>
    <linearGradient id=\"ink\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\">
      <stop offset=\"0%\" stop-color=\"#17314d\" />
      <stop offset=\"100%\" stop-color=\"#245a8a\" />
    </linearGradient>
  </defs>
  <rect width=\"1536\" height=\"1024\" fill=\"url(#bg)\" />
  <circle cx=\"190\" cy=\"176\" r=\"220\" fill=\"#0d766e\" fill-opacity=\"0.10\" />
  <circle cx=\"1330\" cy=\"164\" r=\"260\" fill=\"#1d4f91\" fill-opacity=\"0.11\" />
  <rect x=\"54\" y=\"54\" width=\"1428\" height=\"916\" rx=\"44\" fill=\"#fffaf3\" fill-opacity=\"0.92\" stroke=\"#17314d\" stroke-opacity=\"0.10\" />
  <rect x=\"862\" y=\"164\" width=\"528\" height=\"548\" rx=\"32\" fill=\"#17314d\" fill-opacity=\"0.96\" />
  <path d=\"M910 618 C1018 468 1118 552 1212 430 C1274 350 1328 326 1364 318\" fill=\"none\" stroke=\"#66d2c4\" stroke-width=\"10\" stroke-linecap=\"round\" />
  <path d=\"M910 654 C1010 596 1108 616 1210 534 C1280 478 1334 458 1364 452\" fill=\"none\" stroke=\"#f9bf71\" stroke-width=\"7\" stroke-linecap=\"round\" stroke-opacity=\"0.92\" />
  <g fill=\"#fff2df\">
    <rect x=\"930\" y=\"720\" width=\"32\" height=\"122\" rx=\"12\" />
    <rect x=\"986\" y=\"664\" width=\"32\" height=\"178\" rx=\"12\" />
    <rect x=\"1042\" y=\"610\" width=\"32\" height=\"232\" rx=\"12\" />
    <rect x=\"1098\" y=\"674\" width=\"32\" height=\"168\" rx=\"12\" />
    <rect x=\"1154\" y=\"564\" width=\"32\" height=\"278\" rx=\"12\" />
    <rect x=\"1210\" y=\"706\" width=\"32\" height=\"136\" rx=\"12\" />
  </g>
  <text x=\"96\" y=\"132\" fill=\"#0d766e\" font-size=\"26\" font-family=\"IBM Plex Mono, monospace\" font-weight=\"600\" letter-spacing=\"4\">PROSPEKTLAB INSIGHT</text>
  <text x=\"96\" y=\"250\" fill=\"url(#ink)\" font-size=\"94\" font-family=\"Newsreader, Georgia, serif\" font-weight=\"700\">{title_svg}</text>
  <text x=\"96\" y=\"560\" fill=\"#5f6778\" font-size=\"30\" font-family=\"Manrope, Arial, sans-serif\" font-weight=\"600\">{subtitle_svg}</text>
  <text x=\"96\" y=\"714\" fill=\"#17314d\" font-size=\"26\" font-family=\"IBM Plex Mono, monospace\" font-weight=\"500\" letter-spacing=\"3\">EDITORIAL REPORT</text>
  {''.join(chip_svg)}
</svg>
"""


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _upsert_sitemap(route_base: str, slug: str) -> str | None:
    sitemap_path = repo_root() / "Frontend" / "app" / "public" / "sitemap.xml"
    route_base = _safe_route_base(route_base)
    url = f"{_SITE_URL}/{route_base}/{slug}/"
    try:
        if sitemap_path.is_file():
            tree = ET.parse(sitemap_path)
            root = tree.getroot()
        else:
            root = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
            tree = ET.ElementTree(root)
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        existing = False
        for url_el in root.findall(f"{ns}url"):
            loc_el = url_el.find(f"{ns}loc")
            if loc_el is not None and (loc_el.text or "").strip() == url:
                lastmod_el = url_el.find(f"{ns}lastmod")
                if lastmod_el is None:
                    lastmod_el = ET.SubElement(url_el, f"{ns}lastmod")
                lastmod_el.text = datetime.now(timezone.utc).date().isoformat()
                existing = True
                break
        if not existing:
            url_el = ET.SubElement(root, f"{ns}url")
            ET.SubElement(url_el, f"{ns}loc").text = url
            ET.SubElement(url_el, f"{ns}lastmod").text = datetime.now(timezone.utc).date().isoformat()
            ET.SubElement(url_el, f"{ns}changefreq").text = "monthly"
            ET.SubElement(url_el, f"{ns}priority").text = "0.8"
        tree.write(sitemap_path, encoding="utf-8", xml_declaration=True)
        return str(sitemap_path)
    except Exception:
        logger.exception("Failed to update sitemap at %s", sitemap_path)
        return None


def _event_state_path() -> Path:
    return _DATA_ROOT / "event_state.json"


def _load_event_state() -> dict[str, Any]:
    path = _event_state_path()
    if not path.is_file():
        return {"seen_event_ids": {}, "updated_at": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        logger.exception("Failed to load event state")
    return {"seen_event_ids": {}, "updated_at": ""}


def _save_event_state(state: dict[str, Any]) -> None:
    seen = state.get("seen_event_ids") or {}
    if isinstance(seen, dict) and len(seen) > 5000:
        ordered = sorted(seen.items(), key=lambda item: item[1], reverse=True)[:5000]
        state["seen_event_ids"] = dict(ordered)
    state["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    _write_text(_event_state_path(), json.dumps(state, indent=2, ensure_ascii=True))


def _event_fingerprint(source: str, event: dict[str, Any], watch: ContentEventWatch) -> str:
    parts = [
        source,
        watch.symbol or "",
        watch.isin or "",
        watch.bse_scrip_code or "",
        str(event.get("url") or ""),
        str(event.get("title") or ""),
        str(event.get("published") or ""),
    ]
    raw = "|".join(parts)
    return re.sub(r"[^a-zA-Z0-9]+", "-", raw.lower()).strip("-")[:220]


def _article_body_word_count(article: ContentArticlePackage) -> int:
    parts: list[str] = [article.title, article.description, article.hero_summary]
    for section in article.sections:
        parts.extend(section.paragraphs)
        parts.extend(section.bullets)
    for faq in article.faqs:
        parts.append(faq.question)
        parts.append(faq.answer)
    return sum(len(re.findall(r"\b[\w'-]+\b", part or "")) for part in parts)


def _article_paragraph_count(article: ContentArticlePackage) -> int:
    return sum(len(section.paragraphs) for section in article.sections)


def _score_publishability(req: ContentAutomationRequest, article: ContentArticlePackage, sources: list[dict[str, str]]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if len(sources) >= 3:
        score += 24
        reasons.append("multiple supporting sources found")
    elif len(sources) >= 1:
        score += 12
        reasons.append("at least one supporting source found")
    else:
        reasons.append("no external supporting sources found")

    section_count = len(article.sections)
    paragraph_count = _article_paragraph_count(article)
    article_words = _article_body_word_count(article)

    if section_count >= 10:
        score += 20
        reasons.append(f"article has newsroom section depth ({section_count} sections)")
    elif section_count >= 8:
        score += 10
        reasons.append(f"article is close to newsroom section depth ({section_count} sections)")
    else:
        reasons.append(f"article needs more section depth ({section_count} sections)")

    if paragraph_count >= 22:
        score += 14
        reasons.append(f"article has strong paragraph depth ({paragraph_count} paragraphs)")
    elif paragraph_count >= 18:
        score += 8
        reasons.append(f"article meets minimum paragraph depth ({paragraph_count} paragraphs)")
    else:
        reasons.append(f"article body needs more narrative depth ({paragraph_count} paragraphs)")

    if article_words >= 1600:
        score += 18
        reasons.append(f"article depth {article_words} words")
    elif article_words >= 1200:
        score += 12
        reasons.append(f"article meets minimum depth ({article_words} words)")
    else:
        reasons.append(f"article is too short ({article_words} words)")

    if len(article.faqs) >= 5:
        score += 8
        reasons.append("FAQ coverage included")
    if len(article.description) >= 120:
        score += 6
    if len(article.hero_summary) >= 140:
        score += 6
    if req.source_url or req.source_markdown:
        score += 8
        reasons.append("primary source material provided")
    if req.company_symbol:
        score += 6
        reasons.append("company market context available")

    score = min(score, 100)
    return score, reasons


async def generate_article_automation(req: ContentAutomationRequest, *, requested_by: str) -> ContentAutomationResult:
    slug = slugify(req.slug or req.topic)
    route_base = _safe_route_base(req.route_base)
    article_dir = _article_dir(route_base, slug)
    if article_dir.exists() and not req.overwrite:
        existing = load_generated_article(slug, route_base=route_base)
        if existing:
            return ContentAutomationResult.model_validate(existing)

    context, sources = await _collect_context(req)
    article = await _llm_generate_article(req, slug, context)
    article.slug = slug
    try:
        from finagent.content.editorial import run_editorial_revision_loop, sanitize_article_package

        article = sanitize_article_package(article)
        article, editorial_review = await run_editorial_revision_loop(article, target=req.topic, max_rounds=2)
        article = sanitize_article_package(article)
    except Exception:
        editorial_review = None
        logger.exception("Editorial cleanup failed; continuing with generated article")
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    image_bytes, image_ext, _mime = await _generate_image(req, article, route_base)
    image_name = f"cover{image_ext}"
    html_relative_image = f"/{route_base}/{slug}/{image_name}"
    html_text = render_article_html(article, f"{_SITE_URL}/{route_base}/{slug}/", html_relative_image, generated_at)

    image_path = article_dir / image_name
    html_path = article_dir / "index.html"
    json_path = article_dir / "article.json"
    _write_bytes(image_path, image_bytes)
    _write_text(html_path, html_text)

    confidence_score, publish_reasons = _score_publishability(req, article, sources)
    article_words = _article_body_word_count(article)
    section_count = len(article.sections)
    paragraph_count = _article_paragraph_count(article)
    if editorial_review is not None:
        confidence_score = int(round((confidence_score * 0.45) + (editorial_review.total_score * 0.55)))
        publish_reasons.append(f"editorial review {editorial_review.total_score}/100")
        if not editorial_review.ready_to_publish:
            publish_reasons.extend(f"hold: {issue.message}" for issue in editorial_review.issues[:4])
    editorial_ready = True if editorial_review is None else editorial_review.ready_to_publish
    if article_words < 1200:
        publish_reasons.append(f"hold: article depth {article_words} words below 1200-word newsroom minimum")
    if section_count < 10:
        publish_reasons.append(f"hold: article has {section_count} sections below 10-section newsroom minimum")
    if paragraph_count < 18:
        publish_reasons.append(f"hold: article has {paragraph_count} paragraphs below 18-paragraph newsroom minimum")
    meets_newsroom_depth = article_words >= 1200 and section_count >= 10 and paragraph_count >= 18
    publish_status = "published" if (req.force_publish or (editorial_ready and confidence_score >= 82 and meets_newsroom_depth)) else "draft"
    logger.info(
        "Content article evaluated: slug=%s status=%s score=%s words=%s sections=%s paragraphs=%s reasons=%s",
        slug,
        publish_status,
        confidence_score,
        article_words,
        section_count,
        paragraph_count,
        "; ".join(publish_reasons[:10]),
    )

    result = ContentAutomationResult(
        slug=slug,
        title=article.title,
        description=article.description,
        route_base=route_base,
        public_url=f"{_SITE_URL}/{route_base}/{slug}/",
        html_path=str(html_path),
        json_path=str(json_path),
        image_path=str(image_path),
        generated_at=generated_at,
        sources_used=sources,
        confidence_score=confidence_score,
        publish_status=publish_status,
        publish_reasons=publish_reasons,
    )

    public_mirror = None
    mirrored_sitemap = None
    if req.publish_to_frontend_public and publish_status == "published":
        try:
            public_dir = _public_article_dir(route_base, slug)
            _write_text(public_dir / "index.html", html_text)
            _write_bytes(public_dir / image_name, image_bytes)
            public_mirror = str(public_dir)
            mirrored_sitemap = _upsert_sitemap(route_base, slug)
            refresh_public_research_hub(route_base)
            submit_sitemap()
            submit_url_update(result.public_url, content_type="article")
        except Exception:
            logger.exception("Failed to mirror generated article into frontend public directory")

    payload = {
        **result.model_dump(),
        "mirrored_public_path": public_mirror,
        "mirrored_sitemap": mirrored_sitemap,
        "requested_by": requested_by,
        "word_count": article_words,
        "section_count": section_count,
        "paragraph_count": paragraph_count,
        "article": article.model_dump(),
    }
    if editorial_review is not None:
        payload["editorial_review"] = editorial_review.to_dict()
    _write_text(json_path, json.dumps(payload, indent=2, ensure_ascii=True))

    result.mirrored_public_path = public_mirror
    result.mirrored_sitemap = mirrored_sitemap
    return result


async def generate_article_batch(req: ContentAutomationBatchRequest, *, requested_by: str) -> ContentAutomationBatchResult:
    route_base = _safe_route_base(req.route_base)
    sem = asyncio.Semaphore(req.max_concurrency)
    failures: list[dict[str, str]] = []
    results: list[ContentAutomationResult] = []

    async def _one(topic: ContentAutomationBatchTopic) -> None:
        article_req = ContentAutomationRequest(
            topic=topic.topic,
            slug=topic.slug,
            company_symbol=topic.company_symbol,
            search_query=topic.search_query,
            source_url=topic.source_url,
            source_markdown=topic.source_markdown,
            audience=topic.audience or "Indian investors and market researchers",
            publish_to_frontend_public=req.publish_to_frontend_public,
            include_image=req.include_image,
            overwrite=req.overwrite,
            route_base=route_base,
        )
        async with sem:
            try:
                result = await generate_article_automation(article_req, requested_by=requested_by)
                results.append(result)
            except Exception as exc:
                logger.exception("Batch content generation failed for topic %s", topic.topic)
                failures.append({"topic": topic.topic, "error": str(exc)[:500]})

    await asyncio.gather(*[_one(topic) for topic in req.topics])
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return ContentAutomationBatchResult(
        route_base=route_base,
        generated_at=generated_at,
        total_requested=len(req.topics),
        total_completed=len(results),
        total_failed=len(failures),
        items=sorted(results, key=lambda item: item.generated_at, reverse=True),
        failures=failures,
    )


async def ingest_market_event_triggers(req: ContentEventIngestionRequest, *, requested_by: str) -> ContentEventIngestionResult:
    route_base = _safe_route_base(req.route_base)
    state = _load_event_state()
    seen_event_ids = state.setdefault("seen_event_ids", {})
    failures: list[dict[str, str]] = []
    results: list[ContentAutomationResult] = []
    discovered_events = 0
    skipped_seen = 0

    async def _poll_watch(watch: ContentEventWatch) -> list[tuple[str, dict[str, Any]]]:
        source = watch.source.strip().lower()
        items: list[dict[str, Any]] = []
        if source == "nse":
            if not watch.isin:
                raise ValueError("NSE watch requires 'isin'.")
            items = await asyncio.to_thread(fetch_nse_announcements, watch.isin, req.max_events_per_watch)
        elif source == "bse":
            if not watch.bse_scrip_code:
                raise ValueError("BSE watch requires 'bse_scrip_code'.")
            items = await asyncio.to_thread(fetch_bse_announcements, watch.bse_scrip_code, req.max_events_per_watch)
        elif source == "sebi":
            items = await asyncio.to_thread(fetch_sebi_news, req.max_events_per_watch)
        else:
            raise ValueError(f"Unsupported watch source: {watch.source}")
        return [(source, item) for item in items if isinstance(item, dict)]

    for watch in req.watches:
        try:
            raw_events = await _poll_watch(watch)
        except Exception as exc:
            failures.append({"watch": watch.model_dump_json(), "error": str(exc)[:500]})
            continue

        for source, event in raw_events:
            discovered_events += 1
            event_id = _event_fingerprint(source, event, watch)
            if seen_event_ids.get(event_id):
                skipped_seen += 1
                continue
            seen_event_ids[event_id] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

            company_display = (watch.company_name or watch.symbol or watch.isin or watch.bse_scrip_code or "").strip()
            title = str(event.get("title") or "Market event").strip()
            if source == "sebi":
                topic = f"SEBI Update: {title}"
            elif company_display:
                topic = f"{company_display}: {title}"
            else:
                topic = title

            article_req = ContentAutomationRequest(
                topic=topic,
                slug=slugify(f"{source}-{company_display or 'market'}-{title}")[:120],
                company_symbol=watch.symbol,
                search_query=f"{company_display} {title}".strip() or title,
                source_url=str(event.get("url") or "") or None,
                source_markdown=(event.get("snippet") or "")[:4000] or None,
                audience=watch.audience or "Indian investors and market researchers",
                publish_to_frontend_public=not req.dry_run,
                include_image=req.include_image,
                overwrite=req.overwrite,
                route_base=route_base,
            )
            try:
                result = await generate_article_automation(article_req, requested_by=requested_by)
                result.event_id = event_id
                results.append(result)
            except Exception as exc:
                failures.append({"topic": topic, "error": str(exc)[:500]})

    _save_event_state(state)
    auto_published = sum(1 for item in results if item.publish_status == "published")
    drafts = sum(1 for item in results if item.publish_status != "published")
    return ContentEventIngestionResult(
        route_base=route_base,
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        discovered_events=discovered_events,
        generated_articles=len(results),
        auto_published=auto_published,
        drafts=drafts,
        skipped_seen=skipped_seen,
        failures=failures,
        items=sorted(results, key=lambda item: item.generated_at, reverse=True),
    )


# ── Publish / unpublish helpers (used by flash engine and API routes) ─────────

def publish_article(slug: str, route_base: str = _DEFAULT_ARTICLE_ROUTE) -> dict[str, Any]:
    """
    Flip an article's publish_status to 'published', mirror HTML+image to the
    frontend public directory, and upsert the sitemap.
    Returns the updated manifest dict.
    """
    route_base = _safe_route_base(route_base)
    json_path = _article_dir(route_base, slug) / "article.json"
    if not json_path.is_file():
        raise FileNotFoundError(f"Article not found: {route_base}/{slug}")

    manifest: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
    manifest["publish_status"] = "published"
    manifest["published_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    # Mirror current HTML render
    html_text = load_generated_article_html(slug, route_base=route_base)
    if html_text:
        pub_dir = _public_article_dir(route_base, slug)
        _write_text(pub_dir / "index.html", html_text)

        # Mirror image(s)
        for img_file in _article_dir(route_base, slug).glob("cover.*"):
            _write_bytes(pub_dir / img_file.name, img_file.read_bytes())

        manifest["mirrored_public_path"] = str(pub_dir)

    sitemap_path = _upsert_sitemap(route_base, slug)
    manifest["mirrored_sitemap"] = sitemap_path
    refresh_public_research_hub(route_base)
    submit_sitemap()
    submit_url_update(str(manifest.get("public_url") or f"{_SITE_URL}/{route_base}/{slug}/"), content_type="article")

    _write_text(json_path, json.dumps(manifest, indent=2, ensure_ascii=True))
    return manifest


def unpublish_article(slug: str, route_base: str = _DEFAULT_ARTICLE_ROUTE) -> dict[str, Any]:
    """
    Flip an article's publish_status to 'draft' and remove the public mirror.
    Returns the updated manifest dict.
    """
    route_base = _safe_route_base(route_base)
    json_path = _article_dir(route_base, slug) / "article.json"
    if not json_path.is_file():
        raise FileNotFoundError(f"Article not found: {route_base}/{slug}")

    manifest: dict[str, Any] = json.loads(json_path.read_text(encoding="utf-8"))
    manifest["publish_status"] = "draft"
    manifest["unpublished_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    # Remove public mirror
    pub_dir = _public_article_dir(route_base, slug)
    if pub_dir.is_dir():
        import shutil
        try:
            shutil.rmtree(pub_dir)
        except Exception:
            logger.exception("Failed to remove public mirror %s", pub_dir)
    manifest["mirrored_public_path"] = None
    refresh_public_research_hub(route_base)
    submit_sitemap()

    _write_text(json_path, json.dumps(manifest, indent=2, ensure_ascii=True))
    return manifest

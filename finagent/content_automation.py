from __future__ import annotations

import asyncio
import base64
import html
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from pydantic import BaseModel, Field

from finagent.paths import finagent_data_path, repo_root
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
    hero_eyebrow: str = Field(default="Automated Insight", max_length=60)
    hero_title: str = Field(..., min_length=12, max_length=120)
    hero_summary: str = Field(..., min_length=80, max_length=360)
    audience: str = Field(default="Indian investors and market researchers", max_length=120)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    sections: list[ContentArticleSection] = Field(default_factory=list, min_length=4, max_length=10)
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


def load_generated_article_html(slug: str, route_base: str = _DEFAULT_ARTICLE_ROUTE) -> str | None:
    html_path = _article_dir(route_base, slug) / "index.html"
    if not html_path.is_file():
        return None
    try:
        return html_path.read_text(encoding="utf-8")
    except Exception:
        logger.exception("Failed to load generated article html %s", html_path)
        return None


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
            item = {
                "slug": data.get("slug") or article_json.parent.name,
                "title": data.get("title") or "",
                "description": data.get("description") or "",
                "route_base": data.get("route_base") or current_route_base,
                "public_url": data.get("public_url") or f"{_SITE_URL}/{current_route_base}/{article_json.parent.name}/",
                "generated_at": data.get("generated_at") or "",
                "html_path": data.get("html_path") or str(article_json.parent / "index.html"),
                "image_path": data.get("image_path") or None,
                "confidence_score": data.get("confidence_score") or 0,
                "publish_status": data.get("publish_status") or "draft",
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
        "This automated page turns platform research, market data, and topic analysis into a readable long-form article with SEO metadata, structured sections, and a publishable format."
    )
    topic = req.topic.strip()
    search_term = req.search_query or topic
    keywords = [
        topic,
        search_term,
        f"{topic} analysis",
        f"{topic} SEO",
        "ProspektLab insights",
    ]
    sections = [
        ContentArticleSection(
            heading="What this article covers",
            paragraphs=[
                f"This page was generated from an automated ProspektLab workflow for {topic}. It blends source material, market data, and platform research signals into a single article that can be published without manual layout work.",
                "The goal is not generic filler. The output is structured for search intent, readability, and faster publishing, while leaving room for editors or analysts to refine the final stance when needed.",
            ],
            bullets=[
                "Search-friendly title and meta description",
                "Sectioned article body with clear subheads",
                "FAQ blocks and structured metadata",
            ],
        ),
        ContentArticleSection(
            heading="Why the automation matters",
            paragraphs=[
                "A finance content pipeline only compounds if it can publish consistently. Automation reduces turnaround time from hours to minutes and lets the platform cover more long-tail topics without diluting quality.",
                "By pulling from existing platform APIs and search tools, the workflow can generate context-rich drafts instead of relying on a blank language-model prompt.",
            ],
            bullets=[
                "Faster publishing windows for time-sensitive topics",
                "Reusable templates for search and social metadata",
                "Lower dependence on manual formatting steps",
            ],
        ),
        ContentArticleSection(
            heading="How the platform data feeds the article",
            paragraphs=[
                "The generation path can ingest user-provided markdown, extract a source URL, pull market snapshots for a company symbol, and fetch recent related headlines. That means the draft begins with actual platform context instead of thin generic copy.",
                f"For this article, the working topic is {topic}. The pipeline can also use the search term '{search_term}' to gather supporting context before writing.",
            ],
            bullets=[
                "Existing web search utilities",
                "Existing news feed integrations",
                "Existing company snapshot and quote APIs",
            ],
        ),
        ContentArticleSection(
            heading="Publishing model",
            paragraphs=[
                "Each generated article can be saved as JSON, rendered to HTML, assigned a route slug, and mirrored into the frontend public directory. That allows the same automation job to support API delivery and static deployment.",
                "When image generation is available, the workflow can attach a cover asset. When it is not, the pipeline still generates a branded fallback graphic so the page remains publication-ready.",
            ],
            bullets=[
                "Stored manifest for reuse and editing",
                "Public HTML output for crawlability",
                "Image asset generation with fallback behavior",
            ],
        ),
    ]
    faqs = [
        ContentArticleFaq(
            question="Can ProspektLab generate publishable SEO articles automatically?",
            answer="Yes. The workflow produces a title, description, article sections, FAQs, image asset, HTML output, and a saved JSON manifest that can be served through an API or mirrored into the frontend public tree.",
        ),
        ContentArticleFaq(
            question="Does the workflow use existing platform APIs?",
            answer="Yes. It can reuse the platform's company snapshot, quote, news, and search utilities so article generation starts with structured context instead of relying only on a free-form model prompt.",
        ),
        ContentArticleFaq(
            question="Will the generated page remain crawlable?",
            answer="Yes. The automation writes normal HTML with canonical metadata and can mirror the output into a static public directory so crawlers receive a full document at a direct URL.",
        ),
    ]
    return ContentArticlePackage(
        slug=slug,
        title=f"{topic} | Automated Content Strategy by ProspektLab",
        description=summary[:200],
        hero_eyebrow="Automated Insight",
        hero_title=topic,
        hero_summary=summary,
        audience=req.audience,
        keywords=keywords[:8],
        sections=sections,
        faqs=faqs,
        image_prompt=f"Editorial finance hero illustration for {topic}, dark premium interface, Indian market intelligence, modern publication cover, no text.",
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
        "You write high-quality financial and strategic long-form articles for a search-first website. "
        "Return JSON only. Write for humans first, with strong clarity, no fluff, and SEO-safe structure. "
        "Every paragraph must add information. Avoid hype. Do not fabricate facts not present in the context."
    )
    user = (
        "Generate a publication-ready article package as JSON with these fields: "
        "title, description, hero_eyebrow, hero_title, hero_summary, audience, keywords, sections, faqs, cta_label, cta_href, image_prompt. "
        "Rules: title 50-70 chars when possible, description 140-170 chars when possible, 5-7 sections, each section with heading, 2-3 paragraphs, optional bullets, 3-5 FAQs, keywords 5-10 items. "
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
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        data["slug"] = slug
        return ContentArticlePackage.model_validate(data)
    except Exception:
        logger.exception("LLM article generation failed; using fallback")
        return _fallback_article(req, slug, context)


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


def render_article_html(article: ContentArticlePackage, public_url: str, image_href: str | None, generated_at: str) -> str:
    def esc(value: str) -> str:
        return html.escape(value or "", quote=True)

    section_html: list[str] = []
    toc_items: list[str] = []
    for idx, section in enumerate(article.sections, start=1):
        anchor = f"section-{idx}-{slugify(section.heading)}"
        toc_items.append(f'<li><a href="#{anchor}">{esc(section.heading)}</a></li>')
        paragraphs = "".join(f"<p>{esc(paragraph)}</p>" for paragraph in section.paragraphs)
        bullets = ""
        if section.bullets:
            items = "".join(f"<li>{esc(item)}</li>" for item in section.bullets)
            bullets = f"<ul>{items}</ul>"
        section_html.append(
            f'<section class="section" id="{anchor}"><h2>{esc(section.heading)}</h2>{paragraphs}{bullets}</section>'
        )

    faq_items = "".join(
        f'<div class="faq-item"><h3>{esc(faq.question)}</h3><p>{esc(faq.answer)}</p></div>' for faq in article.faqs
    )
    keywords = "<div class=\"keyword-wrap\">" + "".join(
        f'<span class="keyword">{esc(keyword)}</span>' for keyword in article.keywords[:10]
    ) + "</div>"
    image_markup = f'<img class="hero-image" src="{esc(image_href)}" alt="{esc(article.title)} cover image" loading="eager" />' if image_href else ""
    json_ld = _render_json_ld(article, public_url, f"{_SITE_URL}{image_href}" if image_href and image_href.startswith("/") else image_href, generated_at).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang=\"en-IN\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>{esc(article.title)}</title>
    <meta name=\"description\" content=\"{esc(article.description)}\" />
    <meta name=\"robots\" content=\"index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1\" />
    <meta name=\"theme-color\" content=\"#081221\" />
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
    <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap\" rel=\"stylesheet\" />
    <style>
      :root {{
        color-scheme: dark;
        --bg: #04101f;
        --panel: rgba(10, 21, 38, 0.9);
        --panel-soft: rgba(9, 18, 33, 0.82);
        --text: #f6f8fc;
        --muted: #aab6cb;
        --line: rgba(145, 180, 230, 0.16);
        --accent: #7dd3fc;
        --accent-2: #60a5fa;
      }}
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; font-family: Inter, Arial, sans-serif; background: linear-gradient(180deg, #03101f 0%, #081425 100%); color: var(--text); line-height: 1.7; }}
      a {{ color: var(--accent); }}
      .shell {{ width: min(calc(100% - 28px), 1120px); margin: 0 auto; }}
      .hero {{ padding: 28px 0 18px; }}
      .card {{ border: 1px solid var(--line); border-radius: 26px; background: var(--panel); box-shadow: 0 22px 64px rgba(0,0,0,.28); }}
      .hero-card {{ display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(260px, .85fr); gap: 24px; padding: 30px; align-items: center; }}
      .eyebrow {{ display: inline-flex; margin-bottom: 12px; padding: 7px 12px; border-radius: 999px; background: rgba(96,165,250,.12); border: 1px solid rgba(125,211,252,.18); color: var(--accent); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }}
      h1, h2, h3 {{ line-height: 1.16; margin: 0 0 10px; }}
      h1 {{ font-size: clamp(2.2rem, 5vw, 4rem); letter-spacing: -.04em; max-width: 12ch; }}
      h2 {{ font-size: clamp(1.45rem, 2.5vw, 2rem); letter-spacing: -.03em; }}
      p, li {{ color: var(--muted); font-size: 1rem; }}
      .hero-summary {{ font-size: 1.08rem; max-width: 62ch; }}
      .hero-meta {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
      .pill, .keyword {{ padding: 9px 12px; border-radius: 999px; border: 1px solid var(--line); background: rgba(6,14,27,.56); color: var(--text); }}
      .hero-image {{ display: block; width: 100%; border-radius: 22px; border: 1px solid var(--line); background: #071221; aspect-ratio: 4 / 3; object-fit: cover; }}
      main {{ padding: 4px 0 48px; }}
      .layout {{ display: grid; grid-template-columns: minmax(0, 240px) minmax(0, 1fr); gap: 24px; }}
      .toc {{ position: sticky; top: 20px; padding: 18px; }}
      .toc ol {{ margin: 0; padding-left: 18px; }}
      .toc li + li {{ margin-top: 8px; }}
      .toc a {{ text-decoration: none; color: var(--muted); }}
      .article {{ display: grid; gap: 18px; }}
      .section, .faq {{ padding: 24px; }}
      .section ul {{ padding-left: 18px; margin: 0; }}
      .section li + li {{ margin-top: 8px; }}
      .keyword-wrap {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }}
      .faq-grid {{ display: grid; gap: 14px; }}
      .faq-item {{ padding: 18px; border-radius: 18px; border: 1px solid var(--line); background: var(--panel-soft); }}
      .footer {{ padding-bottom: 36px; }}
      .footer-card {{ padding: 20px 24px; display: flex; flex-wrap: wrap; justify-content: space-between; gap: 16px; }}
      @media (max-width: 980px) {{ .hero-card, .layout {{ grid-template-columns: 1fr; }} .toc {{ position: static; }} }}
      @media (max-width: 720px) {{ .hero-card, .section, .faq, .toc {{ padding: 20px; }} h1 {{ max-width: 100%; }} }}
    </style>
    <script type=\"application/ld+json\">{json_ld}</script>
  </head>
  <body>
    <header class=\"hero\">
      <div class=\"shell\">
        <section class=\"card hero-card\">
          <div>
            <div class=\"eyebrow\">{esc(article.hero_eyebrow)}</div>
            <h1>{esc(article.hero_title)}</h1>
            <p class=\"hero-summary\">{esc(article.hero_summary)}</p>
            <div class=\"hero-meta\">
              <span class=\"pill\">Audience: {esc(article.audience)}</span>
              <span class=\"pill\">Published: {esc(generated_at[:10])}</span>
              <span class=\"pill\">Format: Automated long-form article</span>
            </div>
            {keywords}
          </div>
          <div>{image_markup}</div>
        </section>
      </div>
    </header>
    <main>
      <div class=\"shell layout\">
        <aside class=\"card toc\"><h2>On this page</h2><ol>{''.join(toc_items)}</ol></aside>
        <article class=\"article\">{''.join(section_html)}<section class=\"card faq\" id=\"faq\"><h2>Frequently Asked Questions</h2><div class=\"faq-grid\">{faq_items}</div></section></article>
      </div>
    </main>
    <footer class=\"footer\">
      <div class=\"shell\"><div class=\"card footer-card\"><div><strong>ProspektLab</strong><p>Automated content generated from platform APIs and research context.</p></div><div><a href=\"{esc(article.cta_href)}\">{esc(article.cta_label)}</a></div></div></div>
    </footer>
  </body>
</html>
"""


async def _generate_image(req: ContentAutomationRequest, article: ContentArticlePackage, route_base: str) -> tuple[bytes, str, str]:
    prompt = article.image_prompt or f"Editorial hero image for {article.title}, premium finance publication aesthetic, dark blue background, no text."
    model = os.getenv("FINAGENT_CONTENT_IMAGE_MODEL", "gpt-image-1").strip()
    openai_key = os.getenv("OPENAI_API_KEY")
    if req.include_image and openai_key and model:
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=openai_key)
            response = await client.images.generate(
                model=model,
                prompt=prompt,
                size="1536x1024",
            )
            data = response.data[0]
            b64 = getattr(data, "b64_json", None)
            if b64:
                return base64.b64decode(b64), ".png", "image/png"
        except Exception:
            logger.exception("Image generation failed; falling back to SVG")

    svg = render_cover_svg(article)
    return svg.encode("utf-8"), ".svg", "image/svg+xml"


def render_cover_svg(article: ContentArticlePackage) -> str:
    title = html.escape(article.hero_title)
    subtitle = html.escape(article.description[:160])
    chips = article.keywords[:4]
    chip_svg = []
    x = 60
    for keyword in chips:
        safe = html.escape(keyword[:24])
        width = max(120, min(260, 20 + len(safe) * 10))
        chip_svg.append(
            f'<g><rect x="{x}" y="760" rx="22" ry="22" width="{width}" height="52" fill="rgba(255,255,255,0.08)" stroke="rgba(125,211,252,0.22)"/><text x="{x + 20}" y="792" fill="#dbeafe" font-size="24" font-family="Inter, Arial, sans-serif">{safe}</text></g>'
        )
        x += width + 18
        if x > 1200:
            break
    return f"""<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1536\" height=\"1024\" viewBox=\"0 0 1536 1024\" role=\"img\" aria-label=\"{title}\">
  <defs>
    <linearGradient id=\"bg\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\">
      <stop offset=\"0%\" stop-color=\"#03101f\" />
      <stop offset=\"55%\" stop-color=\"#0b1b34\" />
      <stop offset=\"100%\" stop-color=\"#12264b\" />
    </linearGradient>
    <radialGradient id=\"glow\" cx=\"20%\" cy=\"15%\" r=\"80%\">
      <stop offset=\"0%\" stop-color=\"rgba(125,211,252,0.45)\" />
      <stop offset=\"100%\" stop-color=\"rgba(125,211,252,0)\" />
    </radialGradient>
  </defs>
  <rect width=\"1536\" height=\"1024\" fill=\"url(#bg)\" />
  <circle cx=\"320\" cy=\"170\" r=\"420\" fill=\"url(#glow)\" />
  <circle cx=\"1230\" cy=\"220\" r=\"320\" fill=\"rgba(96,165,250,0.11)\" />
  <rect x=\"48\" y=\"48\" width=\"1440\" height=\"928\" rx=\"42\" fill=\"rgba(8,18,36,0.78)\" stroke=\"rgba(145,180,230,0.16)\" />
  <text x=\"60\" y=\"114\" fill=\"#7dd3fc\" font-size=\"28\" font-family=\"Inter, Arial, sans-serif\" font-weight=\"700\" letter-spacing=\"3\">PROSPEKTLAB AUTOMATION</text>
  <text x=\"60\" y=\"270\" fill=\"#f8fbff\" font-size=\"88\" font-family=\"Inter, Arial, sans-serif\" font-weight=\"800\">{title}</text>
  <foreignObject x=\"60\" y=\"320\" width=\"1160\" height=\"240\"><div xmlns=\"http://www.w3.org/1999/xhtml\" style=\"color:#aab6cb;font:500 34px Inter,Arial,sans-serif;line-height:1.4;\">{subtitle}</div></foreignObject>
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


def _score_publishability(req: ContentAutomationRequest, article: ContentArticlePackage, sources: list[dict[str, str]]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if len(sources) >= 3:
        score += 28
        reasons.append("multiple supporting sources found")
    elif len(sources) >= 1:
        score += 14
        reasons.append("at least one supporting source found")
    else:
        reasons.append("no external supporting sources found")

    if len(article.sections) >= 5:
        score += 22
        reasons.append("article has enough section depth")
    elif len(article.sections) >= 4:
        score += 14
        reasons.append("article meets minimum section depth")
    else:
        reasons.append("article is too shallow")

    paragraph_count = sum(len(section.paragraphs) for section in article.sections)
    if paragraph_count >= 10:
        score += 16
        reasons.append("article body is substantial")
    elif paragraph_count >= 8:
        score += 10
        reasons.append("article body is moderately substantial")
    else:
        reasons.append("article body needs more narrative depth")

    if len(article.faqs) >= 3:
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
    publish_status = "published" if (req.force_publish or confidence_score >= 70) else "draft"

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
        except Exception:
            logger.exception("Failed to mirror generated article into frontend public directory")

    payload = {
        **result.model_dump(),
        "mirrored_public_path": public_mirror,
        "mirrored_sitemap": mirrored_sitemap,
        "requested_by": requested_by,
        "article": article.model_dump(),
    }
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

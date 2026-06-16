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
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from pydantic import BaseModel, Field

from finagent.paths import finagent_data_path, repo_root
from finagent.seo.google_search_console import submit_sitemap
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
_ARTICLE_DISCLAIMER = os.getenv(
    "FINAGENT_ARTICLE_DISCLAIMER",
    "This analysis is for informational purposes only. Markets carry risk; past performance does not guarantee future results.",
)


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


class ContentArticleTakeaway(BaseModel):
    heading: str = Field(..., min_length=3, max_length=120)
    detail: str = Field(..., min_length=12, max_length=360)


class ContentArticleMetric(BaseModel):
    label: str = Field(..., min_length=2, max_length=80)
    value: str = Field(..., min_length=1, max_length=80)
    change: str = Field(default="", max_length=40)
    period: str = Field(default="", max_length=60)
    source: str = Field(default="", max_length=180)


class ContentArticleTable(BaseModel):
    title: str = Field(..., min_length=3, max_length=120)
    columns: list[str] = Field(default_factory=list, min_length=2, max_length=10)
    rows: list[list[str]] = Field(default_factory=list, min_length=1, max_length=20)
    footnote: str = Field(default="", max_length=300)


class ContentArticleVisualPoint(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    value: float


class ContentArticleVisual(BaseModel):
    kind: str = Field(default="bar", max_length=20)
    title: str = Field(..., min_length=3, max_length=120)
    points: list[ContentArticleVisualPoint] = Field(default_factory=list, min_length=2, max_length=12)
    note: str = Field(default="", max_length=220)


class ContentArticleTimelineEvent(BaseModel):
    date: str = Field(..., min_length=4, max_length=40)
    event: str = Field(..., min_length=3, max_length=140)
    detail: str = Field(default="", max_length=260)
    source: str = Field(default="", max_length=180)


class ContentArticleEvidenceNote(BaseModel):
    claim: str = Field(..., min_length=10, max_length=420)
    source_title: str = Field(default="", max_length=220)
    source_url: str = Field(default="", max_length=1200)


class ContentArticlePackage(BaseModel):
    slug: str = Field(..., min_length=1, max_length=120)
    title: str = Field(..., min_length=12, max_length=120)
    description: str = Field(..., min_length=80, max_length=220)
    hero_eyebrow: str = Field(default="Research Brief", max_length=60)
    hero_title: str = Field(..., min_length=12, max_length=120)
    hero_summary: str = Field(..., min_length=80, max_length=360)
    audience: str = Field(default="Indian investors and market researchers", max_length=120)
    keywords: list[str] = Field(default_factory=list, max_length=12)
    # ── LiveMint-style narrative journalism fields (inverted pyramid) ──────
    # narrative_lede: opening paragraph carrying the key insight + hard numbers.
    # market_context: market/sector backdrop that situates the story.
    # analyst_commentary: woven analyst-grade interpretation (not bullet dumps).
    narrative_lede: str = Field(default="", max_length=900)
    market_context: str = Field(default="", max_length=1400)
    analyst_commentary: str = Field(default="", max_length=1800)
    key_takeaways: list[ContentArticleTakeaway] = Field(default_factory=list, max_length=8)
    metrics: list[ContentArticleMetric] = Field(default_factory=list, max_length=12)
    tables: list[ContentArticleTable] = Field(default_factory=list, max_length=4)
    visuals: list[ContentArticleVisual] = Field(default_factory=list, max_length=4)
    timeline: list[ContentArticleTimelineEvent] = Field(default_factory=list, max_length=10)
    evidence_notes: list[ContentArticleEvidenceNote] = Field(default_factory=list, max_length=16)
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
    image_mime: str | None = None
    cover_provider: str | None = None
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
    return _public_article_dirs(route_base, slug)[0]


def _public_article_dirs(route_base: str, slug: str) -> list[Path]:
    route_base = _safe_route_base(route_base)
    roots = [
        repo_root() / "frontend" / "public",
        repo_root() / "frontend" / "app" / "public",
    ]
    return [root / route_base / slug for root in roots]


def _public_hub_dirs(route_base: str) -> list[Path]:
    route_base = _safe_route_base(route_base)
    suffix = "research" if route_base == "insights" else ""
    roots = [
        repo_root() / "frontend" / "public",
        repo_root() / "frontend" / "app" / "public",
    ]
    if suffix:
        return [root / route_base / suffix for root in roots]
    return [root / route_base for root in roots]


def load_generated_article(slug: str, route_base: str = _DEFAULT_ARTICLE_ROUTE) -> dict[str, Any] | None:
    article_path = _article_dir(route_base, slug) / "article.json"
    if not article_path.is_file():
        return None
    try:
        return json.loads(article_path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load generated article %s", article_path)
        return None


def _manifest_publish_gate_status(article: dict[str, Any]) -> str:
    gate = article.get("publish_gate")
    if isinstance(gate, dict):
        status = str(gate.get("status") or "").strip().lower()
        if status in {"publish", "draft"}:
            return status
    explicit = str(article.get("publish_gate_status") or "").strip().lower()
    if explicit in {"publish", "draft"}:
        return explicit
    # Backward compatibility: older manifests may have published status without
    # an explicit publish_gate payload. Treat those as publish-approved.
    if str(article.get("publish_status") or "").strip().lower() == "published":
        return "publish"
    return "draft"


def is_publish_gate_passing_article(article: dict[str, Any]) -> bool:
    if not isinstance(article, dict):
        return False
    return _manifest_publish_gate_status(article) == "publish"


def is_generated_article_published(slug: str, route_base: str = _DEFAULT_ARTICLE_ROUTE) -> bool:
    article = load_generated_article(slug, route_base=route_base)
    if not article:
        return False
    if str(article.get("publish_status") or "draft").lower() != "published":
        return False
    return is_publish_gate_passing_article(article)


def _find_cover_asset_name(route_base: str, slug: str) -> str | None:
    article_dir = _article_dir(route_base, slug)
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".svg"):
        candidate = article_dir / f"cover{ext}"
        if candidate.is_file():
            return candidate.name
    return None


def _extract_structured_metrics_from_text(chunks: list[str]) -> list[dict[str, str]]:
    metrics: list[dict[str, str]] = []
    seen: set[str] = set()
    colon_pattern = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 &/\-]{2,60}):\s*([^()]+?)(?:\s*\(([+\-][^)]+)\))?\s*$")
    loose_pattern = re.compile(r"([+\-]?\d[\d,]*(?:\.\d+)?)\s*(%|cr|crore|lakh|bn|billion|mn|million|x|bps)?", re.IGNORECASE)

    for raw in chunks:
        text = _repair_mojibake_text(str(raw or "")).strip()
        if not text:
            continue
        match = colon_pattern.match(text)
        if match:
            label = match.group(1).strip()[:80]
            value = match.group(2).strip()[:80]
            change = (match.group(3) or "").strip()[:40]
            key = label.lower()
            if label and value and key not in seen:
                seen.add(key)
                metrics.append({"label": label, "value": value, "change": change, "period": "", "source": ""})
                if len(metrics) >= 10:
                    break
            continue
        loose = loose_pattern.search(text)
        if not loose:
            continue
        value = (loose.group(1) or "").strip()
        unit = (loose.group(2) or "").strip()
        if unit:
            value = f"{value} {unit}"
        label = text.split(":")[0][:72].strip() if ":" in text else text[:72].strip()
        if len(label) < 2:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        metrics.append({"label": label, "value": value[:80], "change": "", "period": "", "source": "Article text"})
        if len(metrics) >= 10:
            break
    return metrics


def _normalize_manifest_attachment_tables(meta: dict[str, Any]) -> list[dict[str, Any]]:
    tables = list(meta.get("attachment_tables") or [])
    normalized: list[dict[str, Any]] = []
    for index, table in enumerate(tables[:3], start=1):
        if isinstance(table, dict):
            columns = [_repair_mojibake_text(str(col))[:80].strip() for col in list(table.get("columns") or [])[:10]]
            rows_raw = list(table.get("rows") or [])
            if not columns and rows_raw and isinstance(rows_raw[0], list):
                columns = [f"Column {i + 1}" for i in range(min(10, len(rows_raw[0])))]
            rows: list[list[str]] = []
            for row in rows_raw[:20]:
                if not isinstance(row, list):
                    continue
                rows.append([_repair_mojibake_text(str(cell))[:140].strip() for cell in row[:10]])
            if columns and rows:
                normalized.append(
                    {
                        "title": _repair_mojibake_text(str(table.get("title") or f"Attachment table {index}"))[:120].strip(),
                        "columns": columns,
                        "rows": rows,
                        "footnote": _repair_mojibake_text(str(table.get("note") or ""))[:300].strip(),
                    }
                )
        elif isinstance(table, list) and table:
            width = min(10, len(table[0]) if isinstance(table[0], list) else 0)
            if width <= 1:
                continue
            columns = [f"Column {i + 1}" for i in range(width)]
            rows: list[list[str]] = []
            for row in table[:20]:
                if isinstance(row, list):
                    rows.append([_repair_mojibake_text(str(cell))[:140].strip() for cell in row[:width]])
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


def _normalized_public_text(*values: Any) -> str:
    chunks: list[str] = []
    for value in values:
        if value is None:
            continue
        chunks.append(_repair_mojibake_text(str(value)))
    return re.sub(r"\s+", " ", " ".join(chunks)).strip().lower()


def _contains_diagnostic_public_text(*values: Any) -> bool:
    text = _normalized_public_text(*values)
    if not text:
        return False
    return any(token in text for token in _DIAGNOSTIC_PUBLIC_TOKENS)


def _metric_has_business_numeric_signal(metric: dict[str, Any]) -> bool:
    label = str(metric.get("label") or "")
    value = str(metric.get("value") or "")
    change = str(metric.get("change") or "")
    period = str(metric.get("period") or "")
    source = str(metric.get("source") or "")
    if _contains_diagnostic_public_text(label, value, change, period, source):
        return False
    value_clean = value.replace(",", "")
    if not re.search(r"[-+]?\d*\.?\d+", value_clean):
        return False
    combined = _normalized_public_text(label, value, change, period, source)
    if any(hint in combined for hint in _BUSINESS_NUMERIC_HINTS):
        return True
    if re.search(r"(?:%|bps|crore|cr|lakh|million|billion|mn|bn|rs\.?|inr|usd|\$|₹|x)", value.lower()):
        return True
    return False


def _filter_public_metrics(metrics: list[dict[str, Any]]) -> list[dict[str, str]]:
    filtered: list[dict[str, str]] = []
    seen: set[str] = set()
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        label = _repair_mojibake_text(str(metric.get("label") or ""))[:80].strip()
        value = _repair_mojibake_text(str(metric.get("value") or ""))[:80].strip()
        change = _repair_mojibake_text(str(metric.get("change") or ""))[:40].strip()
        period = _repair_mojibake_text(str(metric.get("period") or ""))[:60].strip()
        source = _repair_mojibake_text(str(metric.get("source") or ""))[:180].strip()
        if not label or not value:
            continue
        if _contains_diagnostic_public_text(label, value, change, period, source):
            continue
        key = re.sub(r"\W+", " ", label.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        filtered.append(
            {
                "label": label,
                "value": value,
                "change": change,
                "period": period,
                "source": source,
            }
        )
    return filtered


def _table_has_business_numeric_rows(table: dict[str, Any]) -> bool:
    title = str(table.get("title") or "")
    columns = list(table.get("columns") or [])
    rows = list(table.get("rows") or [])
    column_text = " ".join(str(col) for col in columns)
    for row in rows:
        if not isinstance(row, list):
            continue
        row_text = " ".join(str(cell) for cell in row)
        if _contains_diagnostic_public_text(title, column_text, row_text):
            continue
        combined = _normalized_public_text(title, column_text, row_text)
        if re.search(r"[-+]?\d*\.?\d+", row_text.replace(",", "")) and any(
            hint in combined for hint in _BUSINESS_NUMERIC_HINTS
        ):
            return True
    return False


def _is_sentence_style_metric_label(label: str, *, max_chars: int, max_words: int) -> bool:
    cleaned = _repair_mojibake_text(str(label or "")).strip()
    if not cleaned:
        return True
    if len(cleaned) > max_chars or len(cleaned.split()) > max_words:
        return True
    if re.search(r"[.!?]", cleaned):
        return True
    return False


def _filter_public_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        title = _repair_mojibake_text(str(table.get("title") or ""))[:120].strip()
        columns = [_repair_mojibake_text(str(col))[:80].strip() for col in list(table.get("columns") or [])[:10]]
        if len(columns) < 2 or _contains_diagnostic_public_text(title):
            continue
        rows: list[list[str]] = []
        for row in list(table.get("rows") or [])[:20]:
            if not isinstance(row, list):
                continue
            cleaned = [_repair_mojibake_text(str(cell))[:140].strip() for cell in row[:10]]
            if _contains_diagnostic_public_text(title, columns, cleaned):
                continue
            if _is_sentence_style_metric_label(cleaned[0] if cleaned else "", max_chars=72, max_words=8):
                continue
            if not re.search(r"[-+]?\d", " ".join(cleaned[1:])):
                continue
            rows.append(cleaned)
        # A single-row "table" is just a stat line, not a table — require at
        # least two real data rows so we never render a near-empty table.
        if len(rows) < 2:
            continue
        candidate = {
            "title": title,
            "columns": columns,
            "rows": rows,
            "footnote": _repair_mojibake_text(str(table.get("footnote") or ""))[:300].strip(),
        }
        if not _table_has_business_numeric_rows(candidate):
            continue
        filtered.append(candidate)
    return filtered


def _filter_public_visuals(visuals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for visual in visuals:
        if not isinstance(visual, dict):
            continue
        title = str(visual.get("title") or "")
        note = str(visual.get("note") or "")
        if _contains_diagnostic_public_text(title, note):
            continue
        points_raw = list(visual.get("points") or [])
        points: list[dict[str, Any]] = []
        for point in points_raw:
            if not isinstance(point, dict):
                continue
            label = str(point.get("label") or "")
            value = point.get("value")
            if _contains_diagnostic_public_text(label):
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if not _metric_has_business_numeric_signal({"label": label, "value": numeric}):
                continue
            points.append({"label": label[:80], "value": numeric})
        if len(points) < 2:
            continue
        filtered.append(
            {
                "kind": _repair_mojibake_text(str(visual.get("kind") or "bar"))[:20].strip() or "bar",
                "title": _repair_mojibake_text(title)[:120].strip(),
                "points": points[:12],
                "note": _repair_mojibake_text(note)[:220].strip(),
            }
        )
    return filtered


def _structured_visuals_from_metrics(metrics: list[dict[str, str]]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for metric in metrics:
        if not _metric_has_business_numeric_signal(metric):
            continue
        label = _repair_mojibake_text(str(metric.get("label") or "")).strip()
        if _is_sentence_style_metric_label(label, max_chars=36, max_words=5):
            continue
        value = str(metric.get("value") or "").replace(",", "")
        match = re.search(r"[-+]?\d*\.?\d+", value)
        if not match:
            continue
        try:
            numeric = float(match.group(0))
        except ValueError:
            continue
        points.append({"label": label[:30], "value": numeric})
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


def _build_manifest_timeline(manifest: dict[str, Any]) -> list[dict[str, str]]:
    meta = manifest.get("source_evidence_meta") if isinstance(manifest.get("source_evidence_meta"), dict) else {}
    evidence_claims = manifest.get("evidence_claims") if isinstance(manifest.get("evidence_claims"), list) else []
    events: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def push(date_value: str, event_value: str, detail_value: str, source_value: str) -> None:
        date_clean = _repair_mojibake_text(str(date_value or "")).strip()[:40] or datetime.now(timezone.utc).date().isoformat()
        event_clean = _repair_mojibake_text(str(event_value or "")).strip()[:140]
        detail_clean = _repair_mojibake_text(str(detail_value or "")).strip()[:260]
        source_clean = _repair_mojibake_text(str(source_value or "")).strip()[:180]
        if len(event_clean) < 3:
            return
        key = (date_clean, event_clean.lower())
        if key in seen:
            return
        seen.add(key)
        events.append(
            {
                "date": date_clean,
                "event": event_clean,
                "detail": detail_clean,
                "source": source_clean,
            }
        )

    if isinstance(meta, dict):
        extraction = str(meta.get("attachment_extraction_status") or "").strip().lower()
        if extraction:
            push(
                str(meta.get("staged_at") or manifest.get("generated_at") or ""),
                "Attachment extraction completed" if extraction == "ok" else "Attachment extraction requires review",
                f"Extraction status: {extraction}. Parser: {str(meta.get('attachment_parser') or 'unknown')}.",
                str(meta.get("attachment_url") or meta.get("source_url") or ""),
            )
    for claim in evidence_claims[:10]:
        if not isinstance(claim, dict):
            continue
        snippet = _repair_mojibake_text(str(claim.get("evidence_snippet") or ""))
        announced = re.search(r"Announced at:\s*([0-9:\-+ ]{8,40})", snippet, flags=re.IGNORECASE)
        if announced:
            push(
                announced.group(1).strip(),
                "Official disclosure timestamp",
                str(claim.get("claim") or "")[:220],
                str(claim.get("source_url") or ""),
            )
            break
    push(
        str(manifest.get("generated_at") or ""),
        "Research article generated",
        str(manifest.get("title") or "Automated research update published.")[:220],
        str(manifest.get("public_url") or ""),
    )
    return events[:6]


def _hydrate_structured_article_from_manifest(
    article_data: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    payload = dict(article_data)
    sections = payload.get("sections") if isinstance(payload.get("sections"), list) else []
    evidence_claims = manifest.get("evidence_claims") if isinstance(manifest.get("evidence_claims"), list) else []
    meta = manifest.get("source_evidence_meta") if isinstance(manifest.get("source_evidence_meta"), dict) else {}

    if not payload.get("key_takeaways"):
        takeaways: list[dict[str, str]] = []
        for section in sections[:4]:
            if not isinstance(section, dict):
                continue
            heading = _repair_mojibake_text(str(section.get("heading") or "")).strip()[:120]
            paragraphs = section.get("paragraphs") if isinstance(section.get("paragraphs"), list) else []
            detail = _repair_mojibake_text(str(paragraphs[0] if paragraphs else "")).strip()[:360]
            if len(heading) >= 3 and len(detail) >= 12:
                takeaways.append({"heading": heading, "detail": detail})
        payload["key_takeaways"] = takeaways[:6]

    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), list) else []
    if not metrics:
        chunks: list[str] = []
        for section in sections:
            if not isinstance(section, dict):
                continue
            chunks.extend(str(x) for x in (section.get("bullets") or []) if str(x).strip())
            chunks.extend(str(x) for x in (section.get("paragraphs") or []) if str(x).strip())
        extracted_metrics = _extract_structured_metrics_from_text(chunks)
        facts_raw = meta.get("attachment_structured_facts")
        if isinstance(facts_raw, dict):
            for key, value in list(facts_raw.items())[:10]:
                label = _repair_mojibake_text(str(key).replace("_", " ").title())[:80].strip()
                val = _repair_mojibake_text(str(value))[:80].strip()
                if len(label) >= 2 and val:
                    extracted_metrics.append({"label": label, "value": val, "change": "", "period": "", "source": "Attachment facts"})
        elif isinstance(facts_raw, list):
            for item in facts_raw[:5]:
                if not isinstance(item, dict):
                    continue
                nested = item.get("facts")
                if isinstance(nested, dict):
                    for key, value in list(nested.items())[:8]:
                        label = _repair_mojibake_text(str(key).replace("_", " ").title())[:80].strip()
                        val = _repair_mojibake_text(str(value))[:80].strip()
                        if len(label) >= 2 and val:
                            extracted_metrics.append({"label": label, "value": val, "change": "", "period": "", "source": "Attachment facts"})
        deduped: list[dict[str, str]] = []
        seen_labels: set[str] = set()
        for metric in extracted_metrics:
            label_key = str(metric.get("label") or "").lower()
            if not label_key or label_key in seen_labels:
                continue
            seen_labels.add(label_key)
            deduped.append(metric)
        payload["metrics"] = deduped[:10]
    payload["metrics"] = _filter_public_metrics(
        [metric for metric in (payload.get("metrics") or []) if isinstance(metric, dict)]
    )[:10]

    tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
    if not tables:
        tables = _normalize_manifest_attachment_tables(meta)
        if not tables and payload.get("metrics"):
            metric_rows = [
                [
                    _repair_mojibake_text(str(metric.get("label") or ""))[:80].strip(),
                    _repair_mojibake_text(str(metric.get("value") or ""))[:80].strip(),
                    _repair_mojibake_text(str(metric.get("change") or ""))[:40].strip(),
                ]
                for metric in payload.get("metrics")[:10]
                if isinstance(metric, dict)
            ]
            if metric_rows:
                tables = [
                    {
                        "title": "Key reported metrics",
                        "columns": ["Metric", "Value", "Change"],
                        "rows": metric_rows,
                        "footnote": "Compiled from article evidence and extracted filing context.",
                    }
                ]
        if not tables and evidence_claims:
            claim_rows: list[list[str]] = []
            for claim in evidence_claims[:8]:
                if not isinstance(claim, dict):
                    continue
                claim_text = _repair_mojibake_text(str(claim.get("claim") or ""))[:140].strip()
                if len(claim_text) < 10:
                    continue
                source_text = _repair_mojibake_text(
                    str(claim.get("source_title") or claim.get("source_url") or "Source")
                )[:120].strip()
                claim_rows.append([claim_text, source_text])
            if claim_rows:
                tables = [
                    {
                        "title": "Evidence matrix",
                        "columns": ["Claim", "Source"],
                        "rows": claim_rows,
                        "footnote": "Each claim links back to the official or trusted source listed in this report.",
                    }
                ]
        payload["tables"] = tables
    payload["tables"] = _filter_public_tables(
        [table for table in (payload.get("tables") or []) if isinstance(table, dict)]
    )[:4]

    visuals = payload.get("visuals") if isinstance(payload.get("visuals"), list) else []
    if visuals:
        payload["visuals"] = _filter_public_visuals(
            [visual for visual in visuals if isinstance(visual, dict)]
        )[:3]
    else:
        metrics_payload = [metric for metric in payload.get("metrics") or [] if isinstance(metric, dict)]
        if any(_metric_has_business_numeric_signal(metric) for metric in metrics_payload):
            payload["visuals"] = _structured_visuals_from_metrics(metrics_payload)
        else:
            payload["visuals"] = []

    timeline = payload.get("timeline") if isinstance(payload.get("timeline"), list) else []
    if not timeline:
        payload["timeline"] = _build_manifest_timeline(manifest)

    evidence_notes = payload.get("evidence_notes") if isinstance(payload.get("evidence_notes"), list) else []
    if not evidence_notes:
        notes: list[dict[str, str]] = []
        for claim in evidence_claims[:10]:
            if not isinstance(claim, dict):
                continue
            claim_text = _repair_mojibake_text(str(claim.get("claim") or "")).strip()[:420]
            if len(claim_text) < 10:
                continue
            notes.append(
                {
                    "claim": claim_text,
                    "source_title": _repair_mojibake_text(str(claim.get("source_title") or ""))[:220].strip(),
                    "source_url": str(claim.get("source_url") or "")[:1200].strip(),
                }
            )
        if not notes:
            for source in (manifest.get("sources_used") or [])[:8]:
                if not isinstance(source, dict):
                    continue
                source_title = _repair_mojibake_text(str(source.get("title") or "Source reference"))[:220].strip()
                snippet = _repair_mojibake_text(str(source.get("snippet") or source.get("summary") or "")).strip()[:420]
                if len(snippet) < 10:
                    continue
                notes.append(
                    {
                        "claim": snippet,
                        "source_title": source_title,
                        "source_url": str(source.get("url") or "")[:1200].strip(),
                    }
                )
        if not notes and isinstance(meta, dict):
            source_url = str(meta.get("source_url") or meta.get("attachment_url") or "").strip()[:1200]
            source_name = _repair_mojibake_text(str(meta.get("source") or "Official source"))[:220].strip()
            if source_url:
                notes.append(
                    {
                        "claim": "Primary filing and disclosure evidence was ingested from the official source feed.",
                        "source_title": source_name or "Official source",
                        "source_url": source_url,
                    }
                )
        payload["evidence_notes"] = notes

    return payload


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
    for takeaway in article_data.get("key_takeaways") or []:
        takeaway["heading"] = _repair_mojibake_text(str(takeaway.get("heading") or ""))[:120].strip()
        takeaway["detail"] = _repair_mojibake_text(str(takeaway.get("detail") or ""))[:360].strip()
    for metric in article_data.get("metrics") or []:
        metric["label"] = _repair_mojibake_text(str(metric.get("label") or ""))[:80].strip()
        metric["value"] = _repair_mojibake_text(str(metric.get("value") or ""))[:80].strip()
        metric["change"] = _repair_mojibake_text(str(metric.get("change") or ""))[:40].strip()
        metric["period"] = _repair_mojibake_text(str(metric.get("period") or ""))[:60].strip()
        metric["source"] = _repair_mojibake_text(str(metric.get("source") or ""))[:180].strip()
    for table in article_data.get("tables") or []:
        table["title"] = _repair_mojibake_text(str(table.get("title") or ""))[:120].strip()
        table["columns"] = [
            _repair_mojibake_text(str(col))[:80].strip()
            for col in (table.get("columns") or [])
        ]
        cleaned_rows: list[list[str]] = []
        for row in table.get("rows") or []:
            if isinstance(row, list):
                cleaned_rows.append([
                    _repair_mojibake_text(str(cell))[:140].strip()
                    for cell in row
                ])
        table["rows"] = cleaned_rows
        table["footnote"] = _repair_mojibake_text(str(table.get("footnote") or ""))[:300].strip()
    for visual in article_data.get("visuals") or []:
        visual["kind"] = _repair_mojibake_text(str(visual.get("kind") or ""))[:20].strip()
        visual["title"] = _repair_mojibake_text(str(visual.get("title") or ""))[:120].strip()
        visual["note"] = _repair_mojibake_text(str(visual.get("note") or ""))[:220].strip()
        for point in visual.get("points") or []:
            point["label"] = _repair_mojibake_text(str(point.get("label") or ""))[:80].strip()
    for event in article_data.get("timeline") or []:
        event["date"] = _repair_mojibake_text(str(event.get("date") or ""))[:40].strip()
        event["event"] = _repair_mojibake_text(str(event.get("event") or ""))[:140].strip()
        event["detail"] = _repair_mojibake_text(str(event.get("detail") or ""))[:260].strip()
        event["source"] = _repair_mojibake_text(str(event.get("source") or ""))[:180].strip()
    for note in article_data.get("evidence_notes") or []:
        note["claim"] = _repair_mojibake_text(str(note.get("claim") or ""))[:420].strip()
        note["source_title"] = _repair_mojibake_text(str(note.get("source_title") or ""))[:220].strip()
        note["source_url"] = str(note.get("source_url") or "")[:1200].strip()
    article_data = _hydrate_structured_article_from_manifest(article_data, manifest)
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
            publish_gate = data.get("publish_gate") if isinstance(data.get("publish_gate"), dict) else {}
            publish_gate_metrics = publish_gate.get("metrics") if isinstance(publish_gate.get("metrics"), dict) else {}
            sources_used = data.get("sources_used") if isinstance(data.get("sources_used"), list) else []
            evidence_claims = data.get("evidence_claims") if isinstance(data.get("evidence_claims"), list) else []
            word_count = int(
                publish_gate_metrics.get("word_count")
                or data.get("word_count")
                or 0
            )
            if word_count <= 0 and isinstance(article_meta, dict):
                chunks: list[str] = [
                    str(article_meta.get("title") or data.get("title") or ""),
                    str(article_meta.get("description") or data.get("description") or ""),
                    str(article_meta.get("hero_summary") or ""),
                ]
                for section in article_meta.get("sections") or []:
                    if not isinstance(section, dict):
                        continue
                    chunks.append(str(section.get("heading") or ""))
                    chunks.extend(str(paragraph) for paragraph in (section.get("paragraphs") or []))
                    chunks.extend(str(bullet) for bullet in (section.get("bullets") or []))
                word_count = len(re.findall(r"\b[\w%-]+\b", " ".join(chunks)))
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
                "publish_gate": publish_gate,
                "publish_gate_status": _manifest_publish_gate_status(data),
                "publish_gate_score": int(publish_gate.get("score") or data.get("publish_gate_score") or 0),
                "review_reason": str(data.get("review_reason") or ""),
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
                "sources_used": sources_used,
                "source_count": int(publish_gate_metrics.get("source_count") or len(sources_used)),
                "word_count": word_count,
                "evidence_claim_count": int(publish_gate_metrics.get("evidence_claim_count") or len(evidence_claims)),
                "document_evidence_status": str(
                    publish_gate_metrics.get("document_evidence_status")
                    or ((data.get("evidence_pack_summary") or {}).get("document_evidence_status") if isinstance(data.get("evidence_pack_summary"), dict) else "")
                    or ""
                ),
                "context_enrichment_status": str(
                    publish_gate_metrics.get("context_enrichment_status")
                    or ((data.get("evidence_pack_summary") or {}).get("context_enrichment_status") if isinstance(data.get("evidence_pack_summary"), dict) else "")
                    or ""
                ),
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


_DOC_SOURCE_SUFFIXES = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".csv",
    ".txt",
    ".xml",
    ".xbrl",
}


def _prepare_docling_runtime_cache() -> None:
    configured_root = os.getenv("FINAGENT_DOCLING_CACHE_DIR")
    if configured_root:
        cache_root = Path(configured_root).expanduser()
    else:
        cache_root = Path(tempfile.gettempdir()) / "finagent_docling_cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    env_defaults = {
        "HF_HOME": str(cache_root),
        "HUGGINGFACE_HUB_CACHE": str(cache_root / "hub"),
        "TRANSFORMERS_CACHE": str(cache_root / "transformers"),
        "XDG_CACHE_HOME": str(cache_root / "xdg"),
    }
    for key, value in env_defaults.items():
        os.environ[key] = value


def _document_source_suffix(source_url: str) -> str:
    parsed = urlparse(source_url or "")
    path = (parsed.path or "").lower()
    for suffix in _DOC_SOURCE_SUFFIXES:
        if path.endswith(suffix):
            return suffix
    query = (parsed.query or "").lower()
    for suffix in _DOC_SOURCE_SUFFIXES:
        if suffix in query:
            return suffix
    return ""


def _is_document_source_url(source_url: str) -> bool:
    if _document_source_suffix(source_url):
        return True
    lowered = (source_url or "").lower()
    return any(token in lowered for token in (".pdf", "download", "attachment", "document"))


def _docling_extract_markdown(file_bytes: bytes, filename: str) -> tuple[str, str | None]:
    if not file_bytes:
        return "", "empty_file"
    temp_path: str | None = None
    try:
        _prepare_docling_runtime_cache()
        from docling.document_converter import DocumentConverter

        suffix = Path(filename or "source.bin").suffix or ".bin"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(file_bytes)
            temp_path = handle.name
        result = DocumentConverter().convert(temp_path, raises_on_error=False)
        document = getattr(result, "document", None)
        if document is None or not hasattr(document, "export_to_markdown"):
            status = getattr(result, "status", None)
            return "", f"docling_no_document:{status}"
        markdown = str(document.export_to_markdown() or "").strip()
        if not markdown:
            return "", "docling_empty_markdown"
        return markdown, None
    except Exception as exc:
        return "", f"docling_error:{exc}"
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _pymupdf_extract_text(file_bytes: bytes) -> tuple[str, str | None]:
    if not file_bytes:
        return "", "empty_file"
    try:
        import fitz  # type: ignore

        pages: list[str] = []
        with fitz.open(stream=file_bytes, filetype="pdf") as doc:
            for page in doc:
                text = str(page.get_text("text") or "").strip()
                if text:
                    pages.append(text)
        content = "\n\n".join(pages).strip()
        if not content:
            return "", "pymupdf_empty_text"
        return content, None
    except Exception as exc:
        return "", f"pymupdf_error:{exc}"


def _extract_document_bytes_docling_primary(
    file_bytes: bytes,
    filename: str,
    content_type: str = "",
) -> tuple[str, str | None, str | None]:
    docling_text, docling_error = _docling_extract_markdown(file_bytes, filename)
    if docling_text.strip():
        return docling_text, "docling_markdown", None

    suffix = Path(filename or "").suffix.lower()
    content_type_lower = str(content_type or "").lower()
    is_pdf = suffix == ".pdf" or file_bytes.startswith(b"%PDF") or "pdf" in content_type_lower
    if is_pdf:
        pymupdf_text, pymupdf_error = _pymupdf_extract_text(file_bytes)
        if pymupdf_text.strip():
            return pymupdf_text, "pymupdf", docling_error
        merged_error = "; ".join(part for part in (docling_error, pymupdf_error) if part)
        return "", None, merged_error or "document_extraction_failed"

    return "", None, docling_error or "docling_extraction_failed"


async def _extract_source_document_markdown(source_url: str) -> tuple[str, list[dict[str, str]]]:
    if not _is_document_source_url(source_url):
        return "", []
    try:
        import httpx
    except Exception:
        return "", []

    filename = Path(urlparse(source_url).path or "").name or "source_document"
    try:
        async with httpx.AsyncClient(timeout=45.0, trust_env=False, follow_redirects=True) as client:
            response = await client.get(
                source_url,
                headers={"User-Agent": "ProspektLabContentAutomation/1.0"},
            )
            response.raise_for_status()
            file_bytes = response.content
            content_type = str(response.headers.get("content-type") or "")
    except Exception:
        logger.exception("Document download failed for %s", source_url)
        return "", []

    if not file_bytes:
        return "", []

    extracted_text, parser_used, extraction_error = _extract_document_bytes_docling_primary(
        file_bytes=file_bytes,
        filename=filename,
        content_type=content_type,
    )
    if not extracted_text.strip():
        if extraction_error:
            logger.warning("Document extraction failed for %s: %s", source_url, extraction_error)
        return "", []

    parser_label = parser_used or "document_parser"
    text_block = f"[Extracted with {parser_label}]\n{extracted_text[:18000]}"
    source_title = _source_domain(source_url) or "Document source"
    return text_block, [{"title": source_title, "url": source_url}]


async def _extract_source_url_markdown(source_url: str) -> tuple[str, list[dict[str, str]]]:
    document_text, document_sources = await _extract_source_document_markdown(source_url)
    if document_text:
        return document_text, document_sources

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
        key_takeaways=[
            ContentArticleTakeaway(heading="What changed", detail=f"The latest update around {topic} is summarized with source-backed context."),
            ContentArticleTakeaway(heading="Why it matters", detail="The article prioritizes investor-relevant impact rather than generic narrative."),
        ],
        metrics=[
            ContentArticleMetric(label="Coverage mode", value="Automated editorial", period="current"),
            ContentArticleMetric(label="Source context", value="Platform + web evidence", period="current"),
        ],
        tables=[
            ContentArticleTable(
                title="At a glance",
                columns=["Area", "Current signal"],
                rows=[
                    ["Topic", topic[:80]],
                    ["Search intent", search_term[:80]],
                    ["Publishing format", "Long-form research page"],
                ],
            )
        ],
        visuals=[
            ContentArticleVisual(
                kind="bar",
                title="Signal balance",
                points=[
                    ContentArticleVisualPoint(label="Evidence", value=72.0),
                    ContentArticleVisualPoint(label="Context", value=68.0),
                    ContentArticleVisualPoint(label="Readability", value=78.0),
                ],
                note="Fallback visual when source-derived chart data is unavailable.",
            )
        ],
        timeline=[
            ContentArticleTimelineEvent(
                date=datetime.now(timezone.utc).date().isoformat(),
                event="Article generated",
                detail="Initial automation draft prepared for editorial review.",
            )
        ],
        sections=sections,
        faqs=faqs,
        image_prompt=(
            f"Premium editorial cover for {topic}, styled for the ProspektLab dark research terminal. "
            "Composition: 3:2 ratio, deep navy and near-black backdrop with subtle cyan and violet accent glow, "
            "layered floating financial UI panels (charts, ticker rows, document snippets), one strong central subject "
            "tied to the story, soft volumetric lighting from a single cyan accent source. "
            "Aesthetic: Bloomberg-meets-LiveMint, premium dark-mode financial journalism, India market context "
            "(Nifty, BSE, SEBI references where relevant). Generous padding so the subject reads cleanly inside a card. "
            "No headline text, no watermark, no logos."
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
        "You write high-quality financial and strategic long-form articles for a search-first website. "
        "Return JSON only. Write for humans first, with strong clarity, no fluff, and SEO-safe structure. "
        "Every paragraph must add information. Avoid hype. Do not fabricate facts not present in the context."
    )
    user = (
        "Generate a publication-ready article package as JSON with these fields: "
        "title, description, hero_eyebrow, hero_title, hero_summary, audience, keywords, "
        "narrative_lede, market_context, analyst_commentary, "
        "key_takeaways, metrics, tables, visuals, timeline, evidence_notes, sections, faqs, cta_label, cta_href, image_prompt. "
        "Write like a LiveMint finance journalist: data-led, narrative-driven, inverted-pyramid. "
        "Rules: title is a LiveMint-style headline 60-100 chars anchored on a specific number/named entity (not generic SEO); "
        "narrative_lede 40-70 words front-loading the key number in sentence one; "
        "market_context 50-90 words placing the story in index/sector/peer/macro terms with hard numbers; "
        "analyst_commentary 50-90 words of estimate revisions/valuation/drivers as flowing prose; "
        "description 140-170 chars when possible, 5-7 sections, each section heading + 2-3 prose paragraphs (numbers embedded in sentences) + optional bullets, 3-5 FAQs, keywords 5-10 items. "
        "Include 3-6 key_takeaways, 4-8 metrics, at least one semantic table, at least one visual block, and evidence_notes when numeric claims appear. "
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


_DELTA_RE = re.compile(r"^\s*[+\-−]?\s*\d[\d,]*\.?\d*\s*(%|pct|bps|bp|pp|x|cr|crore|bn|mn)?\b", re.I)


def _real_delta_direction(change: str) -> str:
    """Return 'up'/'down' only when `change` is a genuine signed numeric delta.

    Qualitative copy ("Broadly stable", "Disclosed", "Cautious outlook") returns
    "" so the renderer does not paint a misleading coloured arrow.
    """
    text = (change or "").strip()
    if not text or not _DELTA_RE.match(text):
        return ""
    if text.lstrip()[0] in "-−" or text.lower().lstrip("+").startswith(("down", "fell", "declin")):
        return "down"
    return "up"


def _real_chart_series(article: ContentArticlePackage) -> tuple[str, list[float]] | None:
    """Return (title, values) for the first visual that is a trustworthy data
    chart, or None. Never fabricates a placeholder series.
    """
    try:
        from finagent.content.content_accuracy import visual_issues
    except Exception:
        visual_issues = None  # type: ignore
    for visual in article.visuals or []:
        points = list(getattr(visual, "points", []) or [])
        values: list[float] = []
        for p in points:
            try:
                values.append(float(getattr(p, "value", None)))
            except (TypeError, ValueError):
                continue
        if len(values) < 2:
            continue
        if visual_issues is not None and visual_issues(visual):
            continue
        return (str(getattr(visual, "title", "") or ""), values)
    return None


# Content types that warrant a market-style hero (price/series chart + metric rail).
_MARKET_HERO_TYPES = {"earnings", "company"}


def _build_hero_html(
    article: ContentArticlePackage,
    content_type: str,
    stats_html: str,
    chart_series: tuple[str, list[float]] | None,
    esc,
) -> tuple[str, str]:
    """Build a content-type-aware hero panel.

    Returns (hero_html, chart_points_js). chart_points_js is empty when there is
    no real series to plot — the caller must not emit the canvas in that case.

    - Market hero (earnings/company WITH a real numeric series): chart + headline
      metric + metric rail.
    - Data hero (any type WITH metrics but no chart): metric rail only, no canvas,
      no "Indicative" badge, no fabricated change arrow.
    - Brief hero (no metrics, no chart): eyebrow + hero summary text only.
    """
    eyebrow = esc(article.hero_eyebrow)
    headline_metric = article.metrics[0] if article.metrics else None
    is_market = content_type in _MARKET_HERO_TYPES and chart_series is not None and headline_metric is not None

    if is_market:
        _title, values = chart_series  # type: ignore
        chart_points_js = ",".join(str(v) for v in values[:25])
        delta = _real_delta_direction(str(headline_metric.change or ""))
        chg_html = (
            f'<span class="chg {delta}">{esc(headline_metric.change)}</span>' if delta else ""
        )
        hero = (
            '<div class="art-hero-panel">'
            '<div class="art-chart">'
            '<div class="art-chart-head">'
            f'<span class="ach-name">{eyebrow}</span>'
            f'<span class="ach-range">{esc(_title or "Disclosed series")}</span>'
            "</div>"
            '<div class="art-chart-px">'
            f'<span class="px">{esc(headline_metric.value)}</span>{chg_html}'
            "</div>"
            '<canvas id="art-chart" aria-hidden="true"></canvas>'
            "</div>"
            f'<div class="art-stats">{stats_html}</div>'
            "</div>"
        )
        return hero, chart_points_js

    if stats_html:
        # Data hero: metric rail, no chart canvas, no Indicative badge.
        summary = esc(article.hero_summary or article.description or "")
        hero = (
            '<div class="art-hero-panel art-hero-data">'
            '<div class="art-chart art-chart-text">'
            '<div class="art-chart-head">'
            f'<span class="ach-name">{eyebrow}</span>'
            "</div>"
            f'<p class="art-hero-summary">{summary}</p>'
            "</div>"
            f'<div class="art-stats">{stats_html}</div>'
            "</div>"
        )
        return hero, ""

    # Brief hero: text only.
    summary = esc(article.hero_summary or article.description or "")
    hero = (
        '<div class="art-hero-panel art-hero-brief">'
        '<div class="art-chart art-chart-text">'
        '<div class="art-chart-head">'
        f'<span class="ach-name">{eyebrow}</span>'
        "</div>"
        f'<p class="art-hero-summary">{summary}</p>'
        "</div>"
        "</div>"
    )
    return hero, ""


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
    return _normalise_indian_financial_units(text.strip())


_USD_INR_ARTICLE_DISPLAY_RATE = 84.0


def _format_indian_number(value: float, decimals: int = 0) -> str:
    rounded = round(float(value), max(0, decimals))
    raw = f"{rounded:.{max(0, decimals)}f}"
    whole, _, frac = raw.partition(".")
    sign = ""
    if whole.startswith("-"):
        sign, whole = "-", whole[1:]
    if len(whole) > 3:
        tail = whole[-3:]
        head = whole[:-3]
        pairs: list[str] = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        if head:
            pairs.insert(0, head)
        whole = ",".join(pairs + [tail])
    if decimals > 0:
        frac = frac.rstrip("0")
        if frac:
            return f"{sign}{whole}.{frac}"
    return f"{sign}{whole}"


def _format_crore(value: float, *, approximate: bool = False) -> str:
    abs_value = abs(float(value))
    decimals = 1 if abs_value < 1000 and abs_value % 1 else 0
    prefix = "about " if approximate else ""
    return f"{prefix}Rs {_format_indian_number(value, decimals)} crore"


def _normalise_indian_financial_units(text: str) -> str:
    """Render public article money values in Indian crore/lakh notation."""
    if not text:
        return ""

    protected_segments: list[str] = []

    def _protect_existing(match: re.Match[str]) -> str:
        protected_segments.append(match.group(0))
        return f"__PL_INR_USD_SEGMENT_{len(protected_segments) - 1}__"

    text = re.sub(
        r"(?i)\b(?:about\s+)?Rs\.?\s+[0-9][\d,]*(?:\.\d+)?\s+crore\s+\(US\$[0-9][\d,]*(?:\.\d+)?[BM]\)",
        _protect_existing,
        text,
    )

    def _num(raw: str) -> float:
        return float(str(raw).replace(",", ""))

    def _inr_million(match: re.Match[str]) -> str:
        return _format_crore(_num(match.group(1)) / 10.0)

    def _inr_billion(match: re.Match[str]) -> str:
        return _format_crore(_num(match.group(1)) * 100.0)

    def _inr_cr(match: re.Match[str]) -> str:
        return f"Rs {_format_indian_number(_num(match.group(1)), 1 if '.' in match.group(1) else 0)} crore"

    def _bare_cr(match: re.Match[str]) -> str:
        return f"{match.group(1)}Rs {_format_indian_number(_num(match.group(2)), 1 if '.' in match.group(2) else 0)} crore"

    def _usd(match: re.Match[str]) -> str:
        amount = _num(match.group(1))
        unit = match.group(2).lower()
        if unit.startswith("b") or unit == "b":
            crore = amount * _USD_INR_ARTICLE_DISPLAY_RATE * 100.0
            source = f"US${_format_indian_number(amount, 2 if amount % 1 else 0)}B"
        else:
            crore = amount * _USD_INR_ARTICLE_DISPLAY_RATE / 10.0
            source = f"US${_format_indian_number(amount, 2 if amount % 1 else 0)}M"
        return f"{_format_crore(crore, approximate=True)} ({source})"

    text = re.sub(
        r"(?i)(?:Rs\.?|INR|₹)\s*([0-9][\d,]*(?:\.\d+)?)\s*(?:million|mn)\b",
        _inr_million,
        text,
    )
    text = re.sub(
        r"(?i)(?:Rs\.?|INR|₹)\s*([0-9][\d,]*(?:\.\d+)?)\s*(?:billion|bn)\b",
        _inr_billion,
        text,
    )
    text = re.sub(
        r"(?i)(?:Rs\.?|INR|₹)\s*([0-9][\d,]*(?:\.\d+)?)\s*(?:cr|crores?)\b",
        _inr_cr,
        text,
    )
    text = re.sub(
        r"(?i)(^|[\s(:;,\-])([0-9][\d,]*(?:\.\d+)?)\s*Cr\b",
        _bare_cr,
        text,
    )
    text = re.sub(
        r"(?i)(?:US\$|\$|USD\s*)\s*([0-9][\d,]*(?:\.\d+)?)\s*(billion|bn|b|million|mn|m)\b",
        _usd,
        text,
    )
    for idx, segment in enumerate(protected_segments):
        text = text.replace(f"__PL_INR_USD_SEGMENT_{idx}__", segment)
    return text


def _local_article_href(route_base: str, value: str, slug: str | None = None) -> str:
    cleaned = str(value or "").strip()
    if slug:
        return f"/{_safe_route_base(route_base)}/{slug}/"
    if not cleaned:
        return "#"
    try:
        parsed = urlparse(cleaned)
        parts = [part for part in (parsed.path or "").split("/") if part]
        if len(parts) >= 2 and parts[0] == _safe_route_base(route_base):
            return f"/{parts[0]}/{parts[1]}/"
    except Exception:
        pass
    return cleaned


def _compact_sentence(value: str, max_chars: int = 190) -> str:
    text = re.sub(r"\s+", " ", _repair_mojibake_text(value)).strip()
    if not text:
        return ""
    first_sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    candidate = first_sentence if len(first_sentence) <= max_chars else text
    if len(candidate) <= max_chars:
        return candidate
    trimmed = candidate[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{trimmed}..."


def _hub_public_dir(route_base: str) -> Path:
    return _public_hub_dirs(route_base)[0]


def _is_valid_public_hub_html(html_text: str) -> bool:
    if not html_text:
        return False
    style_match = re.search(r"<style>\s*(.*?)\s*</style>", html_text, re.IGNORECASE | re.DOTALL)
    if not style_match:
        return False
    css = (style_match.group(1) or "").strip()
    if len(css) < 1000:
        return False
    required_tokens = (".hero-grid", ".story-card", ".ticker-track", ".snap-grid")
    return all(tok in css for tok in required_tokens)


def refresh_public_research_hub(route_base: str = _DEFAULT_ARTICLE_ROUTE) -> str | None:
    route_base = _safe_route_base(route_base)
    try:
        from finagent.content.flash_engine import build_insights_hub_html
    except Exception:
        logger.exception("Failed to import public research hub builder")
        return None

    try:
        html_text = build_insights_hub_html(route_base=route_base)
        if route_base == "insights" and not _is_valid_public_hub_html(html_text):
            logger.error("Skipping public hub refresh for %s: generated hub HTML failed style validation", route_base)
            return None
        public_paths = _public_hub_dirs(route_base)
        for public_dir in public_paths:
            _write_text(public_dir / "index.html", html_text)
        return str(public_paths[0] / "index.html")
    except Exception:
        logger.exception("Failed to refresh public research hub for %s", route_base)
        return None


def _render_related_coverage_html(
    article: ContentArticlePackage,
    route_base: str,
    public_url: str,
    esc: Any,
) -> str:
    """Build a 'Related Coverage' HTML section with links to similar articles."""
    try:
        parsed = urlparse(public_url)
        parts = [p for p in (parsed.path or "").split("/") if p]
        current_slug = parts[-1] if len(parts) >= 2 else ""
    except Exception:
        current_slug = ""

    try:
        related = _find_related_articles(article, route_base, current_slug, max_results=3)
    except Exception:
        related = []

    if not related:
        return ""

    links: list[str] = []
    for item in related:
        title = str(item.get("title") or "")[:100]
        url = _local_article_href(route_base, str(item.get("public_url") or ""), str(item.get("slug") or ""))
        if not title or not url:
            continue
        links.append(
            f'<li style="margin-bottom:8px;">'
            f'<a href="{esc(url)}" style="color:#3B82F6;text-decoration:none;font-size:14px;">'
            f'{esc(title)}</a></li>'
        )

    if not links:
        return ""

    return (
        '<section style="max-width:720px;margin:32px auto 0;padding:24px 0;border-top:1px solid rgba(255,255,255,0.08);">'
        '<h4 style="font-size:14px;text-transform:uppercase;letter-spacing:0.05em;color:rgba(246,248,252,0.5);margin-bottom:12px;">Related Coverage</h4>'
        f'<ul style="list-style:none;padding:0;margin:0;">{"".join(links)}</ul>'
        '</section>'
    )


def _find_related_articles(
    article: ContentArticlePackage,
    route_base: str,
    current_slug: str = "",
    max_results: int = 3,
) -> list[dict[str, Any]]:
    """Find related articles by keyword overlap in title/description."""
    try:
        all_articles = list_generated_articles(route_base=route_base, limit=100)
    except Exception:
        return []

    target_words = set(re.findall(r"\b[a-z]{3,}\b", (article.title + " " + article.description).lower()))
    target_words -= {"the", "and", "for", "with", "that", "this", "from", "are", "was", "has", "have", "been", "will", "its"}

    scored: list[tuple[int, dict[str, Any]]] = []
    for item in all_articles:
        slug = item.get("slug", "")
        if slug == current_slug or not slug:
            continue
        if str(item.get("publish_status", "")).lower() != "published":
            continue
        if str(item.get("publish_gate_status") or "publish").lower() not in {"", "publish"}:
            continue
        item_words = set(re.findall(r"\b[a-z]{3,}\b", (str(item.get("title", "")) + " " + str(item.get("description", ""))).lower()))
        overlap = len(target_words & item_words)
        if overlap >= 2:
            scored.append((overlap, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:max_results]]


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
    current_article_href = _local_article_href(route_base, public_url, article.slug)
    raw_sources = meta.get("sources_used") if isinstance(meta.get("sources_used"), list) else []
    sources_used = [source for source in raw_sources if isinstance(source, dict)]

    section_html: list[str] = []
    section_toc_items: list[str] = []
    toc_items: list[str] = []
    highlight_points: list[str] = []
    public_sections = [section for section in article.sections if not _contains_diagnostic_public_text(section.heading)]
    for idx, section in enumerate(public_sections, start=1):
        anchor = f"section-{idx}-{slugify(section.heading)}"
        section_toc_items.append(f'<li><a href="#{anchor}" data-toc-link>{esc(section.heading)}</a></li>')
        paragraphs: list[str] = []
        for pidx, paragraph in enumerate(section.paragraphs):
            cls = "lead-p" if idx == 1 and pidx == 0 else ""
            paragraphs.append(f'<p class="{cls}">{esc(paragraph)}</p>' if cls else f"<p>{esc(paragraph)}</p>")
        bullets = ""
        if section.bullets:
            for item in section.bullets:
                if len(highlight_points) < 4:
                    highlight_points.append(item)
            keypoints: list[str] = []
            for item in section.bullets:
                if ":" in item:
                    label, value = item.split(":", 1)
                    keypoints.append(
                        f'<div class="keypoint"><span class="kp-k">{esc(label.strip())}</span>'
                        f'<span class="kp-v">{esc(value.strip())}</span></div>'
                    )
                else:
                    keypoints.append(f'<div class="keypoint"><span class="kp-v">{esc(item)}</span></div>')
            bullets = f'<div class="keypoints">{"".join(keypoints)}</div>'
        section_html.append(
            f'<section class="sec" id="{anchor}" data-section>'
            f'<span class="sec-label">Section {idx:02d}</span>'
            f'<h2>{esc(section.heading)}</h2>{"".join(paragraphs)}{bullets}'
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

    def _parse_numeric_value(raw: str | float | int) -> float | None:
        if isinstance(raw, (float, int)):
            return float(raw)
        text = str(raw or "").strip()
        if not text:
            return None
        text = text.replace(",", "")
        match = re.search(r"[-+]?\d*\.?\d+", text)
        if not match:
            return None
        try:
            value = float(match.group(0))
        except ValueError:
            return None
        lowered = text.lower()
        if "cr" in lowered or "crore" in lowered:
            value *= 10000000.0
        elif "lakh" in lowered:
            value *= 100000.0
        elif "bn" in lowered or "billion" in lowered:
            value *= 1000000000.0
        elif "mn" in lowered or "million" in lowered:
            value *= 1000000.0
        return value

    # Inline metrics strip from article.metrics.
    metric_strip_html = ""
    if article.metrics:
        metric_chips: list[str] = []
        for m in article.metrics[:4]:
            chg_html = ""
            # Only render a coloured up/down chip when the change is an actual
            # signed delta (e.g. "+120 bps", "-3%"). Prose like "Broadly stable"
            # or "Cautious outlook" must NOT be painted as a red down-arrow.
            delta = _real_delta_direction(str(m.change or ""))
            if delta:
                chg_html = f'<span class="im-chg {delta}">{esc(m.change)}</span>'
            metric_chips.append(
                f'<span class="inline-metric"><span class="im-k">{esc(m.label)}</span>'
                f'<span class="im-v">{esc(m.value)}</span>{chg_html}</span>'
            )
        metric_strip_html = f'<div class="inline-metrics">{"".join(metric_chips)}</div>'

    # ── LiveMint-style narrative blocks (inverted pyramid: lede → context → analysis) ──
    narrative_html = ""
    _lede = getattr(article, "narrative_lede", "") or ""
    _market = getattr(article, "market_context", "") or ""
    _analyst = getattr(article, "analyst_commentary", "") or ""
    if _lede or _market or _analyst:
        parts = []
        if _lede:
            parts.append(f'<p class="article-lede">{esc(_lede)}</p>')
        if _market:
            parts.append(f'<p class="article-context">{esc(_market)}</p>')
        if _analyst:
            parts.append(
                '<div class="analyst-note">'
                '<span class="analyst-note-label">Analyst view</span>'
                f"<p>{esc(_analyst)}</p>"
                "</div>"
            )
        narrative_html = f'<section class="narrative-lede-block">{"".join(parts)}</section>'

    takeaway_html = ""
    if article.key_takeaways:
        takeaway_items = "".join(
            (
                '<article class="takeaway-card">'
                f"<h3>{esc(item.heading)}</h3>"
                f"<p>{esc(item.detail)}</p>"
                "</article>"
            )
            for item in article.key_takeaways[:6]
        )
        takeaway_html = (
            '<section class="structured-card" id="key-takeaways">'
            '<div class="section-kicker">Key takeaways</div>'
            "<h2>What changed and why it matters</h2>"
            f'<div class="takeaway-grid">{takeaway_items}</div>'
            "</section>"
        )
        toc_items.append('<li><a href="#key-takeaways" data-toc-link>Key takeaways</a></li>')
    elif highlight_points:
        takeaway_items = "".join(
            (
                '<article class="takeaway-card">'
                f"<h3>Signal {idx:02d}</h3>"
                f"<p>{esc(_compact_sentence(point, 260))}</p>"
                "</article>"
            )
            for idx, point in enumerate(highlight_points[:4], start=1)
        )
        takeaway_html = (
            '<section class="structured-card" id="key-takeaways">'
            '<div class="section-kicker">Key takeaways</div>'
            "<h2>What changed and why it matters</h2>"
            f'<div class="takeaway-grid">{takeaway_items}</div>'
            "</section>"
        )
        toc_items.append('<li><a href="#key-takeaways" data-toc-link>Key takeaways</a></li>')

    table_html = ""
    public_tables = _filter_public_tables(
        [
            table.model_dump()
            for table in list(article.tables or [])
            if isinstance(table, ContentArticleTable)
        ]
    )
    if public_tables:
        rendered_tables = []
        for table in public_tables[:3]:
            columns = list(table.get("columns") or [])
            rows = list(table.get("rows") or [])
            head_cells = "".join(f"<th>{esc(str(cell))}</th>" for cell in columns[:10])
            row_html = "".join(
                "<tr>" + "".join(f"<td>{esc(str(cell))}</td>" for cell in row[:10]) + "</tr>"
                for row in rows[:20]
            )
            footnote_text = str(table.get("footnote") or "").strip()
            footnote = f'<div class="table-footnote">{esc(footnote_text)}</div>' if footnote_text else ""
            rendered_tables.append(
                '<article class="data-table-card">'
                f"<h3>{esc(str(table.get('title') or 'Data table'))}</h3>"
                '<div class="data-table-wrap"><table><thead><tr>'
                f"{head_cells}"
                "</tr></thead><tbody>"
                f"{row_html}"
                "</tbody></table></div>"
                f"{footnote}"
                "</article>"
            )
        table_html = (
            '<section class="structured-card" id="data-tables">'
            '<div class="section-kicker">Data tables</div>'
            "<h2>Structured numbers from filings and disclosures</h2>"
            + "".join(rendered_tables)
            + "</section>"
        )
        toc_items.append('<li><a href="#data-tables" data-toc-link>Data tables</a></li>')

    def _render_visual_svg(visual: ContentArticleVisual, idx: int) -> str:
        points = list(visual.points or [])[:8]
        if len(points) < 2:
            return ""
        max_value = max(abs(point.value) for point in points) or 1.0
        width = 640
        height = 240
        left = 52
        usable_w = width - left - 24
        usable_h = height - 58
        step = usable_w / max(1, len(points))
        bar_w = max(20.0, step * 0.56)
        bars: list[str] = []
        labels: list[str] = []

        def _svg_label_lines(raw: str, max_chars: int = 15) -> list[str]:
            cleaned = re.sub(r"\s+", " ", _repair_mojibake_text(raw)).strip()
            if not cleaned:
                return [""]
            words = cleaned.split()
            lines: list[str] = []
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if len(candidate) <= max_chars:
                    current = candidate
                    continue
                if current:
                    lines.append(current)
                current = word[:max_chars]
            if current:
                lines.append(current)
            if len(lines) > 2:
                lines = [lines[0], " ".join(lines[1:])]
            if lines and len(lines[-1]) > max_chars + 2:
                lines[-1] = lines[-1][: max_chars + 1].rstrip() + "..."
            return lines[:2]

        def _svg_value_label(value: float) -> str:
            abs_value = abs(float(value))
            decimals = 1 if abs_value < 100 and abs_value % 1 else 0
            return _format_indian_number(value, decimals)

        for point_index, point in enumerate(points):
            scaled = (abs(point.value) / max_value) * usable_h
            x = left + point_index * step + ((step - bar_w) / 2.0)
            y = 24 + (usable_h - scaled)
            center_x = x + (bar_w / 2.0)
            value_y = max(18.0, y - 8.0)
            bars.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{scaled:.1f}" rx="6" fill="rgba(96,165,250,0.76)" />'
            )
            bars.append(
                f'<text x="{center_x:.1f}" y="{value_y:.1f}" text-anchor="middle" fill="#EAE3D6" font-size="10" font-family="IBM Plex Mono, monospace">{esc(_svg_value_label(point.value))}</text>'
            )
            label_lines = _svg_label_lines(point.label)
            tspans = "".join(
                f'<tspan x="{center_x:.1f}" dy="{0 if line_idx == 0 else 12}">{esc(line)}</tspan>'
                for line_idx, line in enumerate(label_lines)
            )
            labels.append(
                f'<text x="{center_x:.1f}" y="{height - 23}" text-anchor="middle" fill="#A8B4C8" font-size="10.5">{tspans}</text>'
            )
        title = esc(visual.title)
        note = f'<div class="visual-note">{esc(visual.note)}</div>' if visual.note else ""
        return (
            '<article class="visual-card">'
            f"<h3>{title}</h3>"
            f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{title}">'
            f'<rect x="0" y="0" width="{width}" height="{height}" fill="rgba(13,31,60,0.85)" />'
            f'<line x1="{left}" y1="{height-32}" x2="{width-16}" y2="{height-32}" stroke="rgba(148,163,184,0.18)" />'
            + "".join(bars)
            + "".join(labels)
            + "</svg>"
            + note
            + "</article>"
        )

    visual_html = ""
    # Belt-and-braces: also scrub diagnostic labels at render time so a
    # diagnostic-tagged visual / table / metric can never leak into a public
    # page even if the payload-coming-in filter was bypassed.
    public_visuals = [
        v for v in list(article.visuals or [])
        if isinstance(v, ContentArticleVisual)
        and not _contains_diagnostic_public_text(v.title, v.note)
    ]
    if public_visuals:
        rendered_visuals = "".join(_render_visual_svg(v, idx) for idx, v in enumerate(public_visuals[:3], start=1))
        visual_html = (
            '<section class="structured-card" id="visuals">'
            '<div class="section-kicker">Visuals</div>'
            "<h2>Charts and indicators from the data</h2>"
            f'<div class="visual-grid">{rendered_visuals}</div>'
            "</section>"
        )
        toc_items.append('<li><a href="#visuals" data-toc-link>Visuals</a></li>')

    timeline_html = ""
    if article.timeline:
        timeline_items = "".join(
            (
                '<li class="timeline-item">'
                f'<div class="timeline-date">{esc(entry.date)}</div>'
                '<div class="timeline-body">'
                f"<h3>{esc(entry.event)}</h3>"
                f"<p>{esc(entry.detail)}</p>"
                f'<div class="timeline-source">{esc(entry.source)}</div>'
                "</div></li>"
            )
            for entry in article.timeline[:10]
        )
        timeline_html = (
            '<section class="structured-card" id="event-timeline">'
            '<div class="section-kicker">Timeline</div>'
            "<h2>How the event sequence developed</h2>"
            f'<ol class="timeline-list">{timeline_items}</ol>'
            "</section>"
        )
        toc_items.append('<li><a href="#event-timeline" data-toc-link>Timeline</a></li>')

    evidence_notes_html = ""
    public_evidence_notes = [
        note
        for note in list(article.evidence_notes or [])[:10]
        if not _contains_diagnostic_public_text(note.claim, note.source_title)
    ]
    if public_evidence_notes:
        note_items = "".join(
            (
                '<article class="evidence-card">'
                f"<p>{esc(note.claim)}</p>"
                f'<a href="{esc(note.source_url or "#")}" rel="noopener noreferrer">{esc(note.source_title or note.source_url or "Source")}</a>'
                "</article>"
            )
            for note in public_evidence_notes
        )
        evidence_notes_html = (
            '<section class="structured-card" id="evidence-notes">'
            '<div class="section-kicker">Evidence notes</div>'
            "<h2>Source-backed claims used in this article</h2>"
            f'<div class="evidence-grid">{note_items}</div>'
            "</section>"
        )
        toc_items.append('<li><a href="#evidence-notes" data-toc-link>Evidence notes</a></li>')

    faq_items = "".join(
        f'<details class="faq-item"><summary><span class="faq-q-text">{esc(faq.question)}</span><span class="faq-chevron" aria-hidden="true">&#8250;</span></summary><div class="faq-answer"><p>{esc(faq.answer)}</p></div></details>'
        for faq in article.faqs
    )
    json_ld = _render_json_ld(article, public_url, f"{_SITE_URL}{image_href}" if image_href and image_href.startswith("/") else image_href, generated_at).replace("</", "<\\/")
    total_words = sum(len(paragraph.split()) for section in public_sections for paragraph in section.paragraphs)
    read_minutes = max(4, (total_words + 219) // 220)
    hero_context = f"{generated_at[:10]} • {read_minutes} min read"

    methodology_points = [
        "Primary source bias: official company filings, exchange disclosures, and transcripts should outrank generic summaries.",
        "This article avoids live market price commentary unless the source explicitly belongs to the reporting period.",
        "Ownership, governance, and filing signals appear only when verified records provide usable depth; thin coverage should be disclosed, not embellished.",
    ]
    methodology_html = "".join(f"<li>{esc(point)}</li>" for point in methodology_points)
    source_section_html = ""
    if sources_used:
        source_items = "".join(
            (
                '<li class="data-row">'
                f'<a href="{esc(str(source.get("url") or "#"))}" rel="noopener noreferrer">'
                f'{esc(str(source.get("title") or source.get("url") or "Source"))}'
                "</a>"
                f'<span class="metric-meta">{esc(str(source.get("evidence_type") or source.get("kind") or "source"))}</span>'
                "</li>"
            )
            for source in sources_used[:8]
        )
        source_section_html = (
            '<section class="structured-card" id="evidence-sources">'
            '<div class="section-kicker">Evidence and methodology</div>'
            "<h2>Source pack used for this research note</h2>"
            "<details class=\"source-disclosure\" open>"
            "<summary>Show source list</summary>"
            f'<ul class="data-list">{source_items}</ul>'
            "</details>"
            "</section>"
        )
        toc_items.append('<li><a href="#evidence-sources" data-toc-link>Evidence and methodology</a></li>')

    if article.faqs:
        faq_item = '<li><a href="#faq" data-toc-link>FAQ</a></li>'
        source_idx = next((idx for idx, item in enumerate(toc_items) if "#evidence-sources" in item), len(toc_items))
        toc_items.insert(source_idx, faq_item)

    if section_toc_items:
        section_insert_at = 1 if toc_items and "#key-takeaways" in toc_items[0] else 0
        toc_items = toc_items[:section_insert_at] + section_toc_items + toc_items[section_insert_at:]

    # ── Handoff layout pieces: hero banner, data panel, tags, rail extras ──
    hero_img_style = f'style="background-image:url(\'{esc(image_href)}\');"' if image_href else ""
    tag_chips = "".join(f'<span class="chip">{esc(k)}</span>' for k in article.keywords[:5])

    # Real chart series only — no fabricated fallback. Content-type comes from
    # the manifest meta; default to a neutral type so non-earnings topics do not
    # get a market-style price hero.
    content_type = str((meta or {}).get("content_type") or "").strip().lower()
    chart_series = _real_chart_series(article)

    stats_html = ""
    if article.metrics:
        stats_html = "".join(
            f'<div class="art-stat"><div class="as-k">{esc(m.label)}</div><div class="as-v">{esc(m.value)}</div></div>'
            for m in article.metrics[:4]
        )
    elif highlight_points:
        stats_html = "".join(
            f'<div class="art-stat"><div class="as-k">Signal {i}</div><div class="as-v">{esc(point)}</div></div>'
            for i, point in enumerate(highlight_points[:4], start=1)
        )

    hero_panel_html, chart_points_js = _build_hero_html(article, content_type, stats_html, chart_series, esc)

    related_articles: list[dict[str, Any]] = []
    try:
        related_articles = _find_related_articles(article, route_base, article.slug, max_results=3)
    except Exception:
        related_articles = []

    def _cat_label(item: dict[str, Any]) -> str:
        ctype = str(item.get("content_type") or item.get("requested_content_type") or item.get("mode") or "").lower()
        label_map = {
            "sebi": "SEBI",
            "regulation": "Regulation",
            "earnings": "Earnings",
            "company": "Company",
            "trend": "Trends",
            "market": "Market",
            "manual": "Insight",
        }
        return label_map.get(ctype, "Research")

    related_links = [f'<a href="{esc(hub_path)}"><span class="rr-cat">Archive</span>Back to the research hub</a>']
    for item in related_articles:
        title = str(item.get("title") or "")[:90]
        url = _local_article_href(route_base, str(item.get("public_url") or ""), str(item.get("slug") or ""))
        if not title or not url:
            continue
        related_links.append(f'<a href="{esc(url)}"><span class="rr-cat">{esc(_cat_label(item))}</span>{esc(title)}</a>')
    related_html = '<div class="rail-related">' + "".join(related_links) + "</div>"
    next_story_href = hub_path
    next_story_title = "Explore more research notes"
    for item in related_articles:
        title = str(item.get("title") or "")[:120]
        url = _local_article_href(route_base, str(item.get("public_url") or ""), str(item.get("slug") or ""))
        if title and url:
            next_story_href = url
            next_story_title = title
            break
    takeaway_rail_items = ""
    if article.key_takeaways:
        takeaway_rail_items = "".join(
            f'<li><strong>{esc(item.heading)}</strong><span>{esc(_compact_sentence(item.detail, 100))}</span></li>'
            for item in article.key_takeaways[:4]
        )
    else:
        takeaway_rail_items = "".join(
            f'<li><span>{esc(_compact_sentence(p, 150))}</span></li>'
            for p in highlight_points[:4]
        )

    return f"""<!doctype html>
<html lang=\"en-IN\" data-page=\"article\">
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
    <link href=\"https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,400..600;1,6..72,400..560&display=swap\" rel=\"stylesheet\" />
    <style>
      :root {{
        color-scheme: dark;
        --paper: #03060d;
        --paper-2: #081424;
        --paper-3: #0d1f3c;
        --card: #0d1f3c;
        --ink: #EAE3D6;
        --ink-2: #A8B4C8;
        --ink-3: #8c9ab0;
        --line: rgba(148, 163, 184, 0.10);
        --line-2: rgba(148, 163, 184, 0.18);
        --line-strong: rgba(147, 197, 253, 0.24);
        --accent: #60A5FA;
        --accent-soft: rgba(96, 165, 250, 0.12);
        --accent-2: #8B5CF6;
        --accent-3: #2563EB;
        --up: #34D399;
        --down: #FB7185;
        --radius: 14px;
        --radius-lg: 22px;
        --serif: "Newsreader", Georgia, "Times New Roman", serif;
        --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        --ink-read: #D8DFEA;
        --mono: \"IBM Plex Mono\", ui-monospace, \"SF Mono\", Menlo, monospace;\r\n        --pad-x: clamp(20px, 5vw, 80px);\r\n        --maxw: 1440px;\r\n      }}
      *, *::before, *::after {{ box-sizing: border-box; }}
      * {{ margin: 0; }}
      html {{ -webkit-text-size-adjust: 100%; scroll-behavior: smooth; }}
      body {{
        font-family: var(--serif);
        background: var(--paper);
        color: var(--ink);
        line-height: 1.6;
        font-size: 18px;
        -webkit-font-smoothing: antialiased;
        text-rendering: optimizeLegibility;
        overflow-x: hidden;
      }}
      body::before {{
        content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 1;
        opacity: 0.35;
        background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.08'/%3E%3C/svg%3E");
        mix-blend-mode: overlay;
      }}
      .cursor-dot, .cursor-ring {{
        position: fixed; top: 0; left: 0; z-index: 9999; pointer-events: none; border-radius: 50%; mix-blend-mode: difference;
      }}
      .cursor-dot {{ width: 6px; height: 6px; background: #fff; transform: translate(-50%, -50%); }}
      .cursor-ring {{
        width: 34px; height: 34px; border: 1px solid #fff; transform: translate(-50%, -50%);
        transition: width .25s, height .25s, background .25s, opacity .25s;
      }}
      .cursor-ring.is-hover {{ width: 54px; height: 54px; background: rgba(255, 255, 255, 0.12); }}
      @media (hover: none), (pointer: coarse) {{
        .cursor-dot, .cursor-ring {{ display: none; }}
      }}
      img, svg, canvas {{ display: block; max-width: 100%; }}
      a {{ color: inherit; text-decoration: none; }}
      ::selection {{ background: var(--accent); color: #fff; }}
      .wrap {{ width: 100%; max-width: var(--maxw); margin-inline: auto; padding-inline: var(--pad-x); }}\r\n      .section {{ position: relative; z-index: 2; }}

      /* Read progress */
      .read-progress {{
        position: fixed; top: 0; left: 0; height: 3px; width: 100%;
        background: linear-gradient(90deg, var(--accent), var(--accent-2));
        transform: scaleX(0); transform-origin: left; z-index: 60;
      }}

      /* Ticker */
      .ticker {{
        position: relative; z-index: 40;
        background: #03060d; color: var(--ink);
        border-bottom: 1px solid var(--line);
        overflow: hidden;
      }}
      .ticker-track {{
        display: flex; gap: 0; width: max-content;
        animation: ticker 48s linear infinite;
      }}
      .ticker:hover .ticker-track {{ animation-play-state: paused; }}
      @keyframes ticker {{ to {{ transform: translateX(-50%); }} }}
      .tk {{
        font-family: var(--mono); font-size: 0.72rem; letter-spacing: 0.02em;
        display: inline-flex; align-items: center; gap: 0.55em;
        padding: 0.7em 1.3em; border-right: 1px solid var(--line); white-space: nowrap;
      }}
      .tk .sym {{ color: #fff; font-weight: 500; }}
      .tk .px {{ color: var(--ink-2); }}
      .tk .chg.up {{ color: var(--up); }}
      .tk .chg.down {{ color: var(--down); }}
      .tk .tri {{ font-size: 0.6rem; }}

      /* Dynamic hero variants (no chart) */
      .art-hero-panel.art-hero-data, .art-hero-panel.art-hero-brief {{ grid-template-columns: 1fr; }}
      .art-hero-panel.art-hero-data {{ grid-template-columns: 1.4fr 1fr; }}
      .art-chart-text {{ display: flex; flex-direction: column; justify-content: center; gap: 12px; }}
      .art-hero-summary {{ font-family: var(--serif, Newsreader, Georgia, serif); font-size: clamp(1.05rem, 1.6vw, 1.35rem); line-height: 1.5; color: var(--ink); margin: 0; }}
      @media (max-width: 720px) {{ .art-hero-panel.art-hero-data {{ grid-template-columns: 1fr; }} }}

      /* Header */
      .site-head {{
        position: sticky; top: 0; z-index: 50;
        background: color-mix(in srgb, var(--paper) 86%, transparent);
        backdrop-filter: blur(14px) saturate(1.2);
        -webkit-backdrop-filter: blur(14px) saturate(1.2);
        border-bottom: 1px solid var(--line);
      }}
      .head-inner {{ display: flex; align-items: center; justify-content: space-between; height: 64px; gap: 20px; }}
      .brand {{ display: inline-flex; align-items: baseline; gap: 0.6em; }}
      .brand .mk-dot {{ width: 9px; height: 9px; border-radius: 50%; background: var(--accent); align-self: center; box-shadow: 0 0 0 3px var(--accent-soft); }}
      .brand .mk-name {{ font-family: var(--mono); font-weight: 600; letter-spacing: 0.14em; font-size: 0.82rem; text-transform: uppercase; color: #fff; }}
      .brand .mk-sub {{ font-family: var(--mono); font-weight: 400; letter-spacing: 0.22em; font-size: 0.62rem; text-transform: uppercase; color: var(--ink-2); }}
      .nav {{ display: flex; align-items: center; gap: 6px; }}
      .nav a {{ font-family: var(--mono); font-size: 0.74rem; letter-spacing: 0.1em; text-transform: uppercase; padding: 0.6em 0.95em; border-radius: 999px; color: var(--ink-2); position: relative; transition: color .25s, background .25s; }}
      .nav a:hover {{ color: var(--ink); background: var(--paper-3); }}
      .nav .btn {{ font-family: var(--mono); font-size: 0.68rem; letter-spacing: 0.14em; text-transform: uppercase; font-weight: 500; display: inline-flex; align-items: center; gap: 0.7em; padding: 0.7em 1.15em; border-radius: 999px; background: var(--accent); color: #fff; }}
      .nav .btn:hover {{ background: var(--accent-3); }}
      .nav .btn .arrow {{ transition: transform .25s; }}
      .nav .btn:hover .arrow {{ transform: translateX(4px); }}
      .burger {{ display: none; width: 42px; height: 42px; border-radius: 10px; border: 1px solid var(--line-2); align-items: center; justify-content: center; flex-direction: column; gap: 4px; }}
      .burger span {{ width: 18px; height: 1.6px; background: var(--ink); transition: transform .3s, opacity .3s; }}
      .m-nav {{ display: none; }}

      /* Hero banner */
      .art-hero-banner {{
        position: relative; z-index: 2;
        border-radius: var(--radius-lg);
        overflow: hidden;
        margin: 0 var(--pad-x);
        max-width: var(--maxw);\r\n        margin-inline: auto;
        aspect-ratio: 24 / 10;
        background-color: var(--paper-3);
        background-position: center;
        background-size: cover;
        background-repeat: no-repeat;
      }}
      .art-hero-banner .hero-overlay {{
        position: absolute; inset: 0;
        background: linear-gradient(to right, rgba(3,6,13,.94) 0%, rgba(3,6,13,.72) 50%, rgba(3,6,13,.38) 100%);
        z-index: 1;
      }}
      .art-hero-content {{
        position: relative; z-index: 2;
        padding: clamp(32px, 5vw, 72px) clamp(28px, 4vw, 64px);
        display: flex; flex-direction: column; justify-content: flex-end;
        height: 100%; color: var(--ink);
      }}
      .art-hero-content .art-crumb {{ margin-bottom: 18px; }}
      .art-hero-content .art-crumb,
      .art-hero-content .art-crumb a {{ color: var(--ink-3); }}
      .art-hero-content .art-crumb a:hover {{ color: #fff; }}
      .art-hero-content .art-crumb .sep {{ opacity: .4; }}
      .art-hero-content .art-cat {{ color: var(--accent); font-weight: 500; }}
      .art-hero-content .art-title {{ color: #fff; font-family: var(--serif); font-weight: 500; font-size: clamp(1.85rem, 4.8vw, 4rem); line-height: 1.05; letter-spacing: -0.025em; max-width: 16ch; }}
      .art-hero-content .art-dek {{ font-family: var(--sans); font-size: clamp(1rem, 1.4vw, 1.25rem); line-height: 1.55; color: var(--ink-read); max-width: 50ch; margin-top: .85em; }}
      .art-hero-content .art-meta {{
        display: flex; align-items: center; gap: 1.2em; margin-top: 1.4em;
        font-family: var(--mono); font-size: 0.72rem; letter-spacing: 0.04em;
        color: var(--ink-3); flex-wrap: wrap;
      }}
      .art-hero-content .art-meta .byline {{ color: #fff; }}
      .art-hero-content .art-meta .av {{
        width: 28px; height: 28px; border-radius: 50%; background: var(--accent);
        color: #fff; display: inline-flex; align-items: center; justify-content: center;
        font-size: 0.66rem; font-weight: 600;
      }}
      .art-fig-caption {{
        max-width: var(--maxw); margin-inline: auto;
        padding: 12px clamp(20px, 5vw, 80px) 0;
        display: flex; align-items: center; gap: 0.7em;
        font-family: var(--mono); font-size: 0.64rem; letter-spacing: 0.06em;
        color: var(--ink-3); flex-wrap: wrap;
      }}
      .art-fig-caption .fc-tag {{ text-transform: uppercase; letter-spacing: 0.14em; color: var(--accent); }}
      .art-fig-caption .sep {{ opacity: 0.5; }}
      .art-tags-wrap {{ max-width: var(--maxw); margin-inline: auto; padding: 20px var(--pad-x) 0; }}\r\n      .art-tags {{ display: flex; flex-wrap: wrap; gap: 10px; }}
      .chip {{
        font-family: var(--mono); font-size: 0.7rem; letter-spacing: 0.04em;
        color: var(--ink-2); background: var(--paper-3); border: 1px solid var(--line);
        padding: 0.5em 0.9em; border-radius: 999px; display: inline-flex; align-items: center; gap: 0.5em;
      }}
      .chip:hover {{ border-color: var(--accent); color: var(--accent); }}

      /* Data panel */
      .art-hero-panel {{
        display: grid; grid-template-columns: 1.6fr 1fr; gap: 0;
        border: 1px solid var(--line); border-radius: var(--radius-lg); overflow: hidden;
        background: var(--card); margin-top: clamp(28px, 4vw, 48px);
      }}
      .art-chart {{ padding: clamp(20px, 2.5vw, 32px); }}
      .art-chart-head {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 10px; }}
      .art-chart-head .ach-name {{ font-family: var(--mono); font-weight: 600; letter-spacing: 0.04em; font-size: 0.92rem; color: #fff; }}
      .art-chart-head .ach-range {{ font-family: var(--mono); font-size: 0.64rem; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-3); }}
      .art-chart-px {{ display: flex; align-items: baseline; gap: 0.7em; margin-bottom: 14px; }}
      .art-chart-px .px {{ font-family: var(--mono); font-size: 1.5rem; font-weight: 500; color: var(--ink); }}
      .art-chart-px .chg {{ font-family: var(--mono); font-size: 0.82rem; }}
      .art-chart-px .chg.up {{ color: var(--up); }}
      .art-chart-px .chg.down {{ color: var(--down); }}
      .art-chart canvas {{ width: 100%; height: 150px; }}
      .art-stats {{
        background: var(--paper-2); border-left: 1px solid var(--line);
        padding: clamp(20px, 2.5vw, 30px);
        display: flex; flex-direction: column; justify-content: center; gap: 0;
      }}
      .art-stat {{ padding: 13px 0; border-top: 1px solid var(--line); }}
      .art-stat:first-child {{ border-top: 0; }}
      .art-stat .as-k {{ font-family: var(--mono); font-size: 0.62rem; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink-3); }}
      .art-stat .as-v {{ font-family: var(--mono); font-size: 1.05rem; font-weight: 500; margin-top: 3px; font-feature-settings: "tnum"; color: var(--ink); }}

      /* Body grid */
      .art-body {{
        display: grid; grid-template-columns: clamp(230px, 20vw, 280px) minmax(0, 1fr);
        gap: clamp(32px, 4vw, 64px);
        /* Keep the side gutter (--pad-x) here — the bare `0` horizontal padding
           let the prose run edge-to-edge below the 1440px max-width (all mobile). */
        padding: clamp(36px, 5vw, 70px) var(--pad-x) 0; align-items: start;
      }}
      .art-rail {{ position: sticky; top: 92px; }}
      .rail-block {{ margin-bottom: 36px; }}
      .rail-block h4 {{
        font-family: var(--mono); font-size: 0.66rem; letter-spacing: 0.16em; text-transform: uppercase;
        color: var(--ink-3); margin-bottom: 14px; font-weight: 500;
      }}
      .toc {{ list-style: none; padding: 0 6px 0 0; display: flex; flex-direction: column; gap: 2px; max-height: calc(100vh - 132px); overflow: auto; }}
      .toc a {{
        display: block; font-family: var(--mono); font-size: 0.78rem; color: var(--ink-3);
        padding: 7px 0 7px 14px; border-left: 2px solid var(--line);
        transition: color .25s, border-color .25s, padding .25s; line-height: 1.3;
      }}
      .toc a:hover {{ color: var(--ink); }}
      .toc a.is-active {{ color: var(--ink); border-color: var(--accent); padding-left: 18px; font-weight: 500; }}
      .rail-takeaways {{ list-style: none; padding: 0; display: flex; flex-direction: column; gap: 12px; }}
      .rail-takeaways li {{ font-family: var(--sans); font-size: 0.9rem; line-height: 1.5; color: var(--ink-read); padding-left: 16px; position: relative; }}
      .rail-takeaways li strong {{ display: block; margin-bottom: 4px; font-family: var(--mono); font-size: 0.62rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink); }}
      .rail-takeaways li span {{ display: block; }}
      .rail-takeaways li::before {{ content: ""; position: absolute; left: 0; top: 0.55em; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); }}
      .rail-related {{ list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0; }}
      .rail-related a {{ display: block; padding: 12px 0; border-top: 1px solid var(--line); font-size: 0.88rem; line-height: 1.35; color: var(--ink); transition: color .2s; }}
      .rail-related a:first-child {{ border-top: 0; }}
      .rail-related a:hover {{ color: var(--accent); }}
      .rail-related .rr-cat {{ font-family: var(--mono); font-size: 0.6rem; letter-spacing: 0.1em; text-transform: uppercase; color: var(--ink-3); display: block; margin-bottom: 3px; }}
      .rail-method li {{ font-family: var(--sans); font-size: 0.85rem; line-height: 1.55; color: var(--ink-read); margin-bottom: 10px; }}
      .rail-method ul {{ list-style: none; padding: 0; }}
      .rail-method li::before {{ content: "•"; color: var(--accent); margin-right: 8px; }}

      /* Prose */
      .prose {{ max-width: none; min-width: 0; }}
      .prose .sec {{ margin-bottom: clamp(36px, 4vw, 56px); scroll-margin-top: 90px; }}
      .prose .sec-label {{
        font-family: var(--mono); font-size: 0.66rem; letter-spacing: 0.18em; text-transform: uppercase;
        color: var(--accent); margin-bottom: 12px; display: block;
      }}
      .prose h2 {{ font-size: clamp(1.7rem, 2.6vw, 2.4rem); letter-spacing: -0.02em; line-height: 1.12; margin: 0 0 0.85em; color: #fff; }}
      .prose h2 + p, .prose h2 + .lead-p {{ margin-top: 0; }}
      .prose p {{ font-family: var(--sans); font-size: 1.0625rem; line-height: 1.75; color: var(--ink-read); margin: 0 0 1.15em; max-width: 74ch; }}
      .prose li {{ font-family: var(--sans); color: var(--ink-read); }}
      .prose .lead-p {{ font-family: var(--sans); font-size: 1.2rem; line-height: 1.65; color: var(--ink); margin-bottom: 1.2em; max-width: 72ch; }}
      .prose .sec-label {{ margin-bottom: 14px !important; }}
      /* Section breathing: stronger vertical rhythm between sections */
      .prose .sec {{ margin-bottom: clamp(48px, 5.5vw, 72px) !important; padding-bottom: clamp(4px, 0.6vw, 12px); }}
      .prose .sec + .sec {{ border-top: 1px solid var(--line); padding-top: clamp(40px, 4vw, 52px); }}
      .prose .keypoints, .prose .inline-metrics, .prose .pullquote {{ margin-block: clamp(20px, 2.4vw, 32px); }}
      .prose .lead-p:first-letter {{
        initial-letter: 2.4; font-weight: 500; margin-right: 0.08em; color: var(--accent);
      }}
      .prose strong {{ font-weight: 600; color: var(--ink); }}
      .article-lede {{ font-family: var(--sans); font-size: 1.24rem; line-height: 1.55; font-weight: 600; color: var(--ink); margin: 0 0 16px; }}
      .article-context {{ font-family: var(--sans); font-size: 1.04rem; line-height: 1.7; color: var(--ink-read); margin: 0 0 16px; }}
      .analyst-note {{
        margin-top: 8px; padding: 14px 18px; border-left: 3px solid var(--accent);
        background: var(--accent-soft); border-radius: 0 10px 10px 0;
      }}
      .analyst-note-label {{
        display: block; font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase;
        color: var(--accent); font-weight: 600; margin-bottom: 6px;
      }}
      .analyst-note p {{ font-family: var(--sans); margin: 0; font-size: 1.02rem; line-height: 1.7; color: var(--ink-read); }}
      .narrative-lede-block {{ margin: 0 0 clamp(32px, 4vw, 48px); padding: 0 0 clamp(28px, 3vw, 36px); border-bottom: 1px solid var(--line); }}
      .narrative-lede-block .article-lede {{ margin-bottom: 18px; }}
      .narrative-lede-block .article-context {{ margin-bottom: 18px; }}
      .narrative-lede-block .analyst-note {{ margin-top: 14px; padding: 16px 20px; }}

      /* Key point cards */
      .keypoints {{ display: grid; gap: 12px; margin: 24px 0 8px; }}
      .keypoint {{
        border: 1px solid var(--line); border-left: 3px solid var(--accent);
        border-radius: 0 10px 10px 0; padding: 14px 18px; background: var(--paper-3);
      }}
      .keypoint .kp-k {{
        font-family: var(--mono); font-size: 0.62rem; letter-spacing: 0.12em; text-transform: uppercase;
        color: var(--ink-3); display: block; margin-bottom: 4px;
      }}
      .keypoint .kp-v {{ font-family: var(--sans); font-size: 0.98rem; line-height: 1.5; color: var(--ink); }}

      /* Inline metric strip */
      .inline-metrics {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 20px 0; }}
      .inline-metric {{
        font-family: var(--mono); font-size: 0.8rem; border: 1px solid var(--line); border-radius: 8px;
        padding: 8px 14px; display: inline-flex; gap: 0.6em; align-items: center; background: var(--paper-3);
      }}
      .inline-metric .im-k {{ color: var(--ink-3); }}
      .inline-metric .im-v {{ font-weight: 500; color: var(--ink); }}
      .inline-metric .im-chg {{ font-weight: 600; }}
      .inline-metric .im-chg.up {{ color: var(--up); }}
      .inline-metric .im-chg.down {{ color: var(--down); }}

      /* Pull quote */
      .pullquote {{
        border-top: 2px solid var(--accent); border-bottom: 2px solid var(--accent);
        padding: 26px 0; margin: 36px 0;
      }}
      .pullquote p {{
        font-family: var(--serif); font-style: italic; font-size: clamp(1.4rem, 2.2vw, 2rem);
        line-height: 1.25; color: var(--ink); max-width: none; margin: 0;
      }}

      /* Structured cards (tables, timeline, evidence, FAQ, takeaways) */
      .structured-card {{
        border-radius: var(--radius-lg); border: 1px solid var(--line); background: var(--paper-3);
        padding: 24px 26px; margin-bottom: 28px;
        transition: border-color .2s ease, transform .2s ease, box-shadow .2s ease;
      }}
      .structured-card:hover {{ border-color: var(--line-strong); box-shadow: 0 18px 50px rgba(0,0,0,0.22); }}
      .section-kicker {{
        margin-bottom: 10px; font-family: var(--mono); font-size: 0.66rem; font-weight: 600;
        letter-spacing: 0.18em; text-transform: uppercase; color: var(--accent);
      }}
      .takeaway-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }}
      .takeaway-card {{ border: 1px solid var(--line); border-radius: 10px; padding: 14px; background: var(--paper-2); }}
      .takeaway-card h3 {{ font-size: 1.05rem; margin-bottom: 8px; color: var(--ink); }}
      .takeaway-card p {{ font-family: var(--sans); font-size: 0.95rem; line-height: 1.55; color: var(--ink-read); margin: 0; max-width: none; }}
      .data-table-card + .data-table-card {{ margin-top: 14px; }}
      .data-table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 12px; background: var(--paper-2); }}
      .data-table-wrap table {{ width: 100%; border-collapse: collapse; min-width: 560px; }}
      .data-table-wrap th, .data-table-wrap td {{ border-bottom: 1px solid var(--line); padding: 10px 12px; text-align: left; font-size: 0.92rem; color: var(--ink); }}
      .data-table-wrap th {{ font-family: var(--mono); font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--ink-3); }}
      .table-footnote {{ margin-top: 8px; font-size: 12px; color: var(--ink-3); }}
      .visual-grid {{ display: grid; gap: 14px; margin-top: 10px; }}
      .visual-card {{ border: 1px solid var(--line); border-radius: 12px; padding: 12px; background: var(--paper-2); }}
      .visual-card h3 {{ margin: 0 0 10px; font-size: 1.05rem; color: var(--ink); }}
      .visual-card svg {{ width: 100%; height: auto; display: block; border-radius: 10px; }}
      .visual-note {{ margin-top: 8px; color: var(--ink-3); font-size: 12px; }}
      .timeline-list {{ list-style: none; margin: 14px 0 0; padding: 0; display: grid; gap: 10px; }}
      .timeline-item {{
        display: grid; grid-template-columns: 130px minmax(0, 1fr); gap: 12px;
        padding: 10px 12px; border-radius: 12px; border: 1px solid var(--line); background: var(--paper-2);
      }}
      .timeline-date {{ font-family: var(--mono); font-size: 11px; letter-spacing: 0.08em; color: var(--accent); text-transform: uppercase; }}
      .timeline-body h3 {{ margin: 0 0 6px; font-size: 1.02rem; color: var(--ink); }}
      .timeline-body p {{ font-family: var(--sans); margin: 0; font-size: 0.95rem; line-height: 1.55; color: var(--ink-read); max-width: none; }}
      .timeline-source {{ margin-top: 6px; font-size: 12px; color: var(--ink-3); }}
      .evidence-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }}
      .evidence-card {{ border: 1px solid var(--line); background: var(--paper-2); border-radius: 12px; padding: 12px; }}
      .evidence-card p {{ font-family: var(--sans); margin-bottom: 8px; line-height: 1.55; color: var(--ink-read); font-size: 0.94rem; max-width: none; }}
      .evidence-card a {{ font-size: 12px; color: var(--accent); text-decoration: underline; overflow-wrap: anywhere; }}
      .source-disclosure summary {{ font-family: var(--mono); font-size: 0.8rem; color: var(--ink-3); cursor: pointer; margin-bottom: 8px; }}
      ul.data-list {{ list-style: none; padding: 0; margin: 18px 0 0; display: flex; flex-direction: column; gap: 8px; }}
      li.data-row {{
        display: flex; align-items: baseline; gap: 10px; padding: 10px 16px;
        background: rgba(96,165,250,0.04); border-left: 3px solid var(--accent);
        border-radius: 0 10px 10px 0; color: var(--ink); font-size: 0.965rem; line-height: 1.55;
      }}
      li.data-row::before {{ content: "→"; color: var(--accent); font-weight: 700; flex-shrink: 0; font-size: 12px; }}
      .metric-meta {{ font-size: 12px; color: var(--ink-3); margin-left: auto; }}
      .faq-shell {{ border-radius: var(--radius-lg); border: 1px solid var(--line); background: var(--paper-3); padding: 24px 26px; margin-bottom: 24px; }}
      .faq-grid {{ display: grid; gap: 12px; margin-top: 16px; }}
      .faq-item {{ border-radius: 12px; border: 1px solid var(--line); background: var(--paper-2); overflow: hidden; transition: box-shadow 0.18s ease; }}
      .faq-item[open] {{ box-shadow: 0 8px 24px rgba(0,0,0,0.25); border-color: var(--line-strong); }}
      .faq-item summary {{ list-style: none; cursor: pointer; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 16px 20px; transition: background 0.15s ease; }}
      .faq-item summary:hover {{ background: rgba(96,165,250,0.05); }}
      .faq-item summary::-webkit-details-marker {{ display: none; }}
      .faq-q-text {{ font-weight: 700; color: var(--ink); font-size: 1rem; line-height: 1.4; }}
      .faq-chevron {{ font-size: 22px; color: var(--accent); flex-shrink: 0; transition: transform 0.22s cubic-bezier(0.4,0,0.2,1); display: inline-block; }}
      .faq-item[open] .faq-chevron {{ transform: rotate(90deg); }}
      .faq-answer {{ padding: 0 20px 18px; border-top: 1px solid var(--line); }}
      .faq-answer p {{ margin: 14px 0 0; color: var(--ink-2); font-size: 0.98rem; line-height: 1.75; }}
      .signal-card {{
        border-radius: 16px; border: 1px solid var(--line-strong); padding: 18px 20px 20px;
        background: var(--paper-3); display: flex; flex-direction: column; gap: 4px;
      }}
      .signal-index {{ font-family: var(--mono); font-size: 10px; letter-spacing: 0.18em; text-transform: uppercase; color: var(--accent); margin-bottom: 6px; }}
      .signal-card p {{ margin: 0; color: var(--ink); font-size: 0.93rem; line-height: 1.5; }}
      .mc-lbl {{ font-family: var(--mono); font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--ink-3); margin-bottom: 2px; }}
      .mc-val {{ font-family: var(--mono); font-size: 1.05rem; font-weight: 600; color: var(--ink); letter-spacing: -0.02em; line-height: 1.2; }}
      .mc-chg {{ display: inline-block; margin-top: 6px; padding: 3px 8px; border-radius: 6px; font-family: var(--mono); font-size: 11px; font-weight: 600; letter-spacing: 0.02em; }}
      .mc-pos {{ background: rgba(52,211,153,0.12); color: var(--up); }}
      .mc-neg {{ background: rgba(251,113,133,0.12); color: var(--down); }}

      /* Disclaimer and next story */
      .art-disclaimer {{
        margin-top: 40px; padding: 22px 24px; border: 1px dashed var(--line-2); border-radius: 12px;
        font-family: var(--mono); font-size: 0.78rem; line-height: 1.6; color: var(--ink-3);
      }}
      .next-story {{ margin-top: clamp(50px, 7vw, 90px); border-top: 1px solid var(--line); padding-top: 30px; }}
      .next-story .ns-k {{ font-family: var(--mono); font-size: 0.66rem; letter-spacing: 0.16em; text-transform: uppercase; color: var(--ink-3); }}
      .next-story a {{ display: flex; justify-content: space-between; align-items: center; gap: 20px; margin-top: 14px; }}
      .next-story .ns-t {{ font-family: var(--serif); font-size: clamp(1.5rem, 2.6vw, 2.2rem); letter-spacing: -0.02em; max-width: 22ch; color: var(--ink); transition: color .3s; }}
      .next-story a:hover .ns-t {{ color: var(--accent); }}
      .next-story .ns-arrow {{ font-family: var(--mono); font-size: 1.4rem; color: var(--accent); }}

      /* Footer */
      .foot {{
        position: relative; z-index: 2; background: var(--paper-3); color: var(--ink);
        margin-top: clamp(60px, 9vw, 130px); border-top: 1px solid var(--line);
      }}
      .foot a {{ color: var(--ink); }}
      .foot .foot-grid {{ display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 40px; padding: clamp(50px, 7vw, 90px) 0 40px; }}
      .foot .mk-name {{ color: #fff; }}
      .foot-disc {{ font-family: var(--mono); font-size: 0.72rem; letter-spacing: 0.03em; color: var(--ink-3); line-height: 1.7; }}
      .foot-col h4 {{ font-family: var(--mono); font-size: 0.7rem; letter-spacing: 0.18em; text-transform: uppercase; color: var(--ink-3); margin-bottom: 14px; font-weight: 500; }}
      .foot-col ul {{ list-style: none; padding: 0; display: flex; flex-direction: column; gap: 10px; }}
      .foot-col a {{ font-family: var(--mono); font-size: 0.82rem; opacity: 0.85; transition: opacity .2s, color .2s; }}
      .foot-col a:hover {{ opacity: 1; color: #fff; }}
      .foot-base {{ display: flex; justify-content: space-between; align-items: center; padding: 22px 0 30px; border-top: 1px solid var(--line); font-family: var(--mono); font-size: 0.68rem; letter-spacing: 0.06em; color: var(--ink-3); flex-wrap: wrap; gap: 14px; }}

      @media (max-width: 980px) {{
        .art-hero-panel {{ grid-template-columns: 1fr; }}
        .art-stats {{ border-left: 0; border-top: 1px solid var(--line); flex-direction: row; flex-wrap: wrap; gap: 0 30px; }}
        .art-body {{ grid-template-columns: 1fr; gap: 30px; }}
        .art-rail {{ position: static; display: grid; grid-template-columns: 1fr 1fr; gap: 30px; }}
        .art-rail .rail-block.toc-block {{ grid-column: 1 / -1; }}
      }}
      @media (max-width: 880px) {{
        .nav {{ display: none; }}
        .burger {{ display: flex; }}
      }}
      @media (max-width: 700px) {{
        /* Drop the fixed aspect-ratio so the banner grows to fit the overlaid
           title/dek instead of clipping them (mobile hero overflow bug). */
        .art-hero-banner {{ aspect-ratio: auto; height: auto; min-height: 320px; margin: 0 12px; border-radius: 16px; }}
        .art-hero-content {{ height: auto; padding: 26px 22px; }}
        .art-hero-content .art-title {{ max-width: none; }}
      }}
      @media (max-width: 620px) {{
        body {{ font-size: 17px; }}
        .art-rail {{ grid-template-columns: 1fr; }}
        .prose p {{ font-size: 1.05rem; max-width: none; }}
        .prose .lead-p {{ font-size: 1.12rem; max-width: none; }}
        .prose .sec + .sec {{ padding-top: clamp(28px, 7vw, 40px); }}
        .foot .foot-grid {{ grid-template-columns: 1fr; }}
        .pullquote p {{ font-size: clamp(1.25rem, 6vw, 1.6rem); }}
        /* Even 2x2 stat grid instead of uneven flex-wrap. */
        .art-stats {{ display: grid; grid-template-columns: 1fr 1fr; column-gap: 24px; row-gap: 0; }}
        .art-stat {{ border-top: 1px solid var(--line); }}
        .art-stat:first-child, .art-stat:nth-child(2) {{ border-top: 0; }}
      }}
      @media (max-width: 560px) {{
        .takeaway-grid, .evidence-grid {{ grid-template-columns: 1fr; }}
        .timeline-item {{ grid-template-columns: 1fr; gap: 4px; }}
      }}
      @media (max-width: 440px) {{
        :root {{ --pad-x: 16px; }}
        .art-hero-content .art-title {{ font-size: clamp(1.6rem, 8vw, 2.1rem); }}
        .art-hero-content .art-meta {{ flex-direction: column; align-items: flex-start; gap: 0.5em; }}
        .data-table-wrap table {{ min-width: 460px; }}
      }}
    </style>
    <script type=\"application/ld+json\">{json_ld}</script>
  </head>
  <body>
    <div class=\"read-progress\" data-progress></div>

    <header class=\"site-head\">
      <div class=\"wrap head-inner\">
        <a class=\"brand\" href=\"{esc(hub_path)}\" aria-label=\"ProspektLab home\">
          <span class=\"mk-dot\"></span><span class=\"mk-name\">ProspektLab</span><span class=\"mk-sub\">Research</span>
        </a>
        <nav class=\"nav\" aria-label=\"Primary\">
          <a href=\"{esc(hub_path)}\">Hub</a>
          <a href=\"/#/dashboard\">Dashboard</a>
          <a href=\"/#/contact\">Contact</a>
          <a href=\"{esc(hub_path)}\" class=\"btn\">Open Archive <span class=\"arrow\">→</span></a>
        </nav>
        <button class=\"burger\" aria-label=\"Menu\"><span></span><span></span><span></span></button>
      </div>
    </header>

    <main>
      <article data-article>
        <div class=\"section\" style=\"padding-top:clamp(16px,2vw,28px)\">
          <div class=\"art-hero-banner\" {hero_img_style}>
            <div class=\"hero-overlay\"></div>
            <div class=\"art-hero-content\">
              <div class=\"art-crumb\">
                <a href=\"{esc(hub_path)}\">Insights</a><span class=\"sep\">/</span>
                <span class=\"art-cat\">{esc(article.hero_eyebrow)}</span>
              </div>
              <h1 class=\"art-title\">{esc(article.hero_title)}</h1>
              <p class=\"art-dek\">{esc(article.hero_summary)}</p>
              <div class=\"art-meta\">
                <span class=\"byline\"><span class=\"av\">PL</span> ProspektLab Desk</span>
                <span>{esc(hero_context)}</span>
                <span>Educational · No recommendation</span>
              </div>
            </div>
          </div>
        #   <div class=\"art-fig-caption\">
        #     <span class=\"fc-tag\">Generated illustration</span><span class=\"sep\">/</span>
        #     <span>ChatGPT-image-2</span><span class=\"sep\">/</span>
        #     <span>Editorial concept — {esc(article.title)}</span>
        #   </div>
          <div class=\"art-tags-wrap\">
            <div class=\"art-tags\">{tag_chips}</div>
          </div>
        </div>

        <header class=\"section\" style=\"padding: clamp(24px,3vw,40px) 0 clamp(16px,2vw,28px)\">
          <div class=\"wrap\">
            {hero_panel_html}
          </div>
        </header>

        <div class=\"section\">
          <div class=\"wrap art-body\">
            <aside class=\"art-rail\">
              <div class=\"rail-block toc-block\">
                <h4>On this page</h4>
                <ul class=\"toc\">{''.join(toc_items)}</ul>
              </div>
              <div class=\"rail-block\">
                <h4>Key takeaways</h4>
                <ul class=\"rail-takeaways\">{takeaway_rail_items}</ul>
              </div>
              <div class=\"rail-block\">
                <h4>Related coverage</h4>
                {related_html}
              </div>
              <div class=\"rail-block rail-method\">
                <h4>How to read this</h4>
                <ul>{methodology_html}</ul>
              </div>
            </aside>

            <div class=\"prose\">
              {narrative_html}
              {metric_strip_html}
              {takeaway_html}
              {''.join(section_html)}
              {table_html}
              {visual_html}
              {timeline_html}
              {evidence_notes_html}
              <section class=\"sec\" id=\"faq\">
                <span class=\"sec-label\">FAQ</span>
                <h2>Questions readers usually ask after the numbers</h2>
                <div class=\"faq-grid\">{faq_items}</div>
              </section>
              {source_section_html}
              <div class=\"art-disclaimer\">{esc(_ARTICLE_DISCLAIMER)}</div>
              <div class=\"next-story\">
                <span class=\"ns-k\">Next in the archive</span>
                <a href=\"{esc(next_story_href)}\">
                  <span class=\"ns-t\">{esc(next_story_title)}</span>
                  <span class=\"ns-arrow\">→</span>
                </a>
              </div>
            </div>
          </div>
        </div>
      </article>
    </main>

    <footer class=\"foot\">
      <div class=\"wrap\">
        <div class=\"foot-grid\">
          <div>
            <a class=\"brand\" href=\"{esc(hub_path)}\"><span class=\"mk-dot\"></span><span class=\"mk-name\">ProspektLab</span><span class=\"mk-sub\">Research</span></a>
            <p class=\"foot-disc\" style=\"margin-top:18px; max-width:42ch\">{esc(_ARTICLE_DISCLAIMER)}</p>
          </div>
          <div class=\"foot-col\">
            <h4>Platform</h4>
            <ul>
              <li><a href=\"/#/dashboard\">Dashboard</a></li>
              <li><a href=\"{esc(hub_path)}\">Research Archive</a></li>
              <li><a href=\"/#/contact\">Contact</a></li>
            </ul>
          </div>
          <div class=\"foot-col\">
            <h4>Article</h4>
            <ul>
              <li><a href=\"{esc(current_article_href)}\">This research note</a></li>
              <li><a href=\"{esc(hub_path)}\">More insights</a></li>
            </ul>
          </div>
        </div>
        <div class=\"foot-base\">
          <span>© 2026 ProspektLab Research</span>
          <span>Built for fast reading, deeper context, repeat discovery.</span>
        </div>
      </div>
    </footer>

    <script>
      (function(){{
        var pts = [{chart_points_js}];
        if(!pts.length) return;
        var color = "96,165,250";
        function draw(){{
          var c = document.getElementById("art-chart");
          if(!c || !c.getContext) return;
          var ctx = c.getContext("2d");
          var rect = c.getBoundingClientRect();
          var dpr = window.devicePixelRatio || 1;
          c.width = Math.round(rect.width * dpr);
          c.height = Math.round(rect.height * dpr);
          ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          var w = rect.width, h = rect.height;
          if (w === 0 || h === 0) return;
          ctx.clearRect(0, 0, w, h);
          var min = Math.min.apply(null, pts), max = Math.max.apply(null, pts);
          var range = max - min || 1;
          var pad = 10;
          function x(i){{ return pad + (i / (pts.length - 1)) * (w - pad * 2); }}
          function y(v){{ return h - pad - ((v - min) / range) * (h - pad * 2); }}
          var grad = ctx.createLinearGradient(0, 0, 0, h);
          grad.addColorStop(0, "rgba(" + color + ",0.22)");
          grad.addColorStop(1, "rgba(" + color + ",0)");
          ctx.beginPath();
          ctx.moveTo(x(0), y(pts[0]));
          pts.forEach(function(v, i){{ if(i > 0) ctx.lineTo(x(i), y(v)); }});
          ctx.lineTo(x(pts.length - 1), h);
          ctx.lineTo(x(0), h);
          ctx.closePath();
          ctx.fillStyle = grad; ctx.fill();
          ctx.beginPath();
          ctx.moveTo(x(0), y(pts[0]));
          pts.forEach(function(v, i){{ if(i > 0) ctx.lineTo(x(i), y(v)); }});
          ctx.strokeStyle = "rgba(" + color + ",0.85)";
          ctx.lineWidth = 2;
          ctx.lineJoin = "round"; ctx.lineCap = "round";
          ctx.stroke();
          ctx.beginPath();
          ctx.arc(x(pts.length - 1), y(pts[pts.length - 1]), 3.5, 0, Math.PI * 2);
          ctx.fillStyle = "rgba(" + color + ",1)";
          ctx.fill();
        }}
        setTimeout(draw, 200);
        window.addEventListener("resize", function(){{ setTimeout(draw, 50); }});
      }})();
    </script>
    <script>
      (function(){{
        'use strict';
        var progress = document.querySelector('[data-progress]');
        var raf = null;
        function updateProgress(){{
          raf = null;
          if(!progress) return;
          var max = document.documentElement.scrollHeight - window.innerHeight;
          var ratio = max > 0 ? window.scrollY / max : 0;
          progress.style.transform = 'scaleX(' + Math.max(0, Math.min(1, ratio)) + ')';
        }}
        updateProgress();
        window.addEventListener('scroll', function(){{ if(!raf) raf = requestAnimationFrame(updateProgress); }}, {{ passive: true }});

        var tocLinks = Array.from(document.querySelectorAll('[data-toc-link]'));
        var sections = tocLinks.map(function(lnk){{ return document.querySelector(lnk.getAttribute('href')); }}).filter(Boolean);
        if('IntersectionObserver' in window && tocLinks.length && sections.length){{
          var observer = new IntersectionObserver(function(entries){{
            entries.forEach(function(entry){{
              if(!entry.isIntersecting) return;
              var activeId = '#' + entry.target.id;
              tocLinks.forEach(function(lnk){{
                lnk.classList.toggle('is-active', lnk.getAttribute('href') === activeId);
              }});
            }});
          }}, {{ rootMargin: '-18% 0px -58% 0px', threshold: 0.1 }});
          sections.forEach(function(sec){{ observer.observe(sec); }});
        }}

        var btn = document.createElement('button');
        btn.id = 'btt';
        btn.setAttribute('aria-label', 'Back to top');
        btn.innerHTML = '&#8593;';
        document.body.appendChild(btn);
        var bttStyle = document.createElement('style');
        bttStyle.textContent = '#btt{{position:fixed;bottom:28px;right:28px;z-index:200;width:44px;height:44px;border-radius:50%;border:1px solid var(--line-strong);background:rgba(13,31,60,0.88);backdrop-filter:blur(10px);color:var(--ink);font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;opacity:0;transform:translateY(12px);transition:opacity .22s,transform .22s;pointer-events:none;box-shadow:0 6px 20px rgba(0,0,0,0.45)}}#btt.show{{opacity:1;transform:translateY(0);pointer-events:auto}}#btt:hover{{background:var(--accent-soft);border-color:var(--accent)}}';
        document.head.appendChild(bttStyle);
        window.addEventListener('scroll', function(){{ btn.classList.toggle('show', window.scrollY > 600); }}, {{ passive: true }});
        btn.addEventListener('click', function(){{ window.scrollTo({{ top: 0, behavior: 'smooth' }}); }});

        document.querySelectorAll('a[data-toc-link]').forEach(function(a){{
          a.addEventListener('click', function(e){{
            var href = a.getAttribute('href');
            if(!href || href[0] !== '#') return;
            var target = document.querySelector(href);
            if(!target) return;
            e.preventDefault();
            var y = target.getBoundingClientRect().top + window.scrollY - 96;
            window.scrollTo({{ top: y, behavior: 'smooth' }});
          }});
        }});
      }})();
    </script>
    <script>
      (function(){{
        var track = document.querySelector('.ticker-track');
        if(!track) return;
        function esc(s){{ return String(s == null ? '' : s).replace(/[&<>\"]/g, function(c){{ return {{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}}[c]; }}); }}
        function render(items){{
          var rows = items.map(function(it){{
            var up = Number(it.changePct) >= 0;
            var cls = up ? 'up' : 'down';
            var arrow = up ? '+' : '−';
            var pct = Math.abs(Number(it.changePct) || 0).toFixed(2);
            return '<span class=\"tk\"><span class=\"sym\">' + esc(it.symbol) + '</span>' +
              '<span class=\"px\">' + esc(it.value) + '</span>' +
              '<span class=\"chg ' + cls + '\">' + arrow + pct + '%</span></span>';
          }}).join('');
          track.innerHTML = rows + rows;
        }}
        function refresh(){{
          fetch('/public/market/ticker', {{ credentials: 'omit' }})
            .then(function(r){{ return r.ok ? r.json() : null; }})
            .then(function(data){{
              if(data && Array.isArray(data.items) && data.items.length) render(data.items);
            }})
            .catch(function(){{}});
        }}
        refresh();
        setInterval(function(){{ if(document.visibilityState === 'visible') refresh(); }}, 60000);
      }})();
    </script>
    <script>
      (function(){{
        var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        if(!reduce && !window.matchMedia("(pointer: coarse)").matches){{
          var dot = document.createElement("div"); dot.className = "cursor-dot";
          var ring = document.createElement("div"); ring.className = "cursor-ring";
          document.body.appendChild(dot); document.body.appendChild(ring);
          var mx = 0, my = 0, rx = 0, ry = 0;
          document.addEventListener("mousemove", function(e){{
            mx = e.clientX; my = e.clientY;
            dot.style.transform = "translate(" + mx + "px," + my + "px) translate(-50%,-50%)";
          }});
          (function loop(){{
            rx += (mx - rx) * 0.18; ry += (my - ry) * 0.18;
            ring.style.transform = "translate(" + rx + "px," + ry + "px) translate(-50%,-50%)";
            requestAnimationFrame(loop);
          }})();
          document.querySelectorAll("a,button,.chip,.story-card,[data-cursor]").forEach(function(el){{
            el.addEventListener("mouseenter", function(){{ ring.classList.add("is-hover"); }});
            el.addEventListener("mouseleave", function(){{ ring.classList.remove("is-hover"); }});
          }});
        }}
        if(!reduce && !window.matchMedia("(pointer: coarse)").matches){{
          document.querySelectorAll(".magnetic").forEach(function(el){{
            var str = parseFloat(el.getAttribute("data-mag")) || 0.3;
            el.addEventListener("mousemove", function(e){{
              var r = el.getBoundingClientRect();
              var mx2 = e.clientX - (r.left + r.width / 2), my2 = e.clientY - (r.top + r.height / 2);
              el.style.transform = "translate(" + mx2 * str + "px," + my2 * str + "px)";
              var inn = el.firstElementChild;
              if(inn) inn.style.transform = "translate(" + mx2 * str * 0.5 + "px," + my2 * str * 0.5 + "px)";
            }});
            el.addEventListener("mouseleave", function(){{
              el.style.transform = "";
              var inn = el.firstElementChild; if(inn) inn.style.transform = "";
            }});
          }});
        }}
      }})();
    </script>
  </body>
</html>"""



def _compose_editorial_cover_prompt(article: ContentArticlePackage) -> str:
    """Return a ChatGPT-image-2 prompt in the ProspektLab handoff editorial style.

    Style reference: dark navy (#14233B) background, cream (#EAE3D6) accents,
    emerald (#0F7A5C), cobalt (#1F56D6) or gold (#9A6B16) accent details,
    abstract/conceptual, no text, no people, Bloomberg/FT editorial mood.
    """
    directive = _story_visual_directive(article)
    intent_key = directive["intent_key"]
    topic = article.title or article.hero_title or intent_key.replace("_", " ")
    mood = directive.get("mood", "professional, authoritative, minimal")
    accent = directive.get("accent", "emerald green (#0F7A5C)")
    iconography = directive.get("iconography", "abstract geometric shapes, subtle data points")
    subject = directive.get("subject", "financial research concept")
    avoid = directive.get("avoid", "text overlays, human faces, bright saturated colors, stock-photo compositions")
    story_specific_prompt = _repair_mojibake_text(str(article.image_prompt or "")).strip()
    if story_specific_prompt:
        story_specific_prompt = re.sub(r"\s+", " ", story_specific_prompt)[:360]

    prompt = (
        f"Editorial illustration for a financial research article about {topic}. "
        "Dark navy blue background (#14233B). "
        f"Abstract composition featuring: {iconography}. "
        "Subtle grid pattern overlay. Muted cream (#EAE3D6) accents. "
        f"{accent} accent details. "
        f"Mood: {mood}. "
        f"Central subject: {subject}. "
        "Professional, authoritative, minimal. No text, no words, no letters, no numbers, "
        "no watermarks, no logos, no human faces. Bloomberg/Financial Times editorial style. "
        f"STRICTLY AVOID: {avoid}. "
        "Wide landscape 24:10 hero composition with generous margins so the subject reads cleanly inside a card."
    )
    if story_specific_prompt:
        prompt += (
            " Story-specific direction from the editor: "
            f"{story_specific_prompt}."
        )
    return prompt


_INTENT_VISUAL_LIBRARY: dict[str, dict[str, Any]] = {
    "scam_fraud": {
        "tokens": ("scam", "fraud", "ponzi", "fake", "forged", "siphon", "money laundering", "embezzle", "deceit",
                   "manipulation", "pump and dump", "front-running", "insider trading"),
        "mood": "ominous, investigative, forensic",
        "accent": "muted crimson (#C0402F) accent",
        "palette": "dark navy (#14233B), cream (#EAE3D6), muted crimson (#C0402F), cold steel-grey",
        "iconography": ("abstract shredded document shapes caught in dim light, a magnifying-glass silhouette hovering over faint ledger lines, "
                       "diagonal caution-geometry stripes, scattered fingerprint-dot patterns, subtle red warning accents"),
        "subject": "financial misconduct and forensic scrutiny",
        "avoid": "text overlays, human faces, bright saturated colors, stock-photo compositions, green/growth colors, celebration tones",
    },
    "regulatory_action": {
        "tokens": ("probe", "enforcement", "ed ", "raid", "sebi order", "adjudication", "litigation",
                   "investigation", "show cause", "penalty", "fine", "ban", "summons", "compliance"),
        "mood": "institutional, authoritative, tense",
        "accent": "emerald green (#0F7A5C) accent",
        "palette": "dark navy (#14233B), cream (#EAE3D6), emerald green (#0F7A5C), polished brass",
        "iconography": ("a translucent shield shape representing regulatory protection, stacked document pages with faint line patterns, "
                       "a balance-scale motif, subtle embossed seal geometry, official letterhead silhouettes"),
        "subject": "regulatory enforcement and compliance",
        "avoid": "text overlays, human faces, bright saturated colors, stock-photo compositions, cheerful color, casual office props",
    },
    "results_beat": {
        "tokens": ("beat", "exceeded", "outperform", "record profit", "all-time high", "growth", "expansion", "margin expansion"),
        "mood": "optimistic, momentum, confident",
        "accent": "emerald green (#0F7A5C) accent",
        "palette": "dark navy (#14233B), cream (#EAE3D6), emerald green (#0F7A5C), soft gold",
        "iconography": ("an upward-sloping bar chart in emerald green with gradient fill, a freshly printed earnings page silhouette, "
                       "subtle green LED ticker dots, polished glass tower reflection, ascending line chart"),
        "subject": "strong earnings and outperformance",
        "avoid": "text overlays, human faces, bright saturated colors, stock-photo compositions, dark shadows, warning red",
    },
    "results_miss": {
        "tokens": ("miss", "below estimate", "decline", "fall", "drop in", "shortfall", "margin pressure", "weak guidance"),
        "mood": "somber, reflective, scrutinizing",
        "accent": "muted crimson (#C0402F) accent",
        "palette": "dark navy (#14233B), cream (#EAE3D6), muted crimson (#C0402F), cool slate grey",
        "iconography": ("a downward-pointing arrow on a faint chart, a half-empty coffee cup silhouette beside a results sheet, "
                       "a broken line-graph fragment, soft red highlight strokes, rain-streaked window geometry"),
        "subject": "earnings shortfall and margin pressure",
        "avoid": "text overlays, human faces, bright saturated colors, stock-photo compositions, bright green, celebratory tones",
    },
    "deal_ma": {
        "tokens": ("acquire", "acquisition", "merger", "deal", "buyout", "stake sale", "investment", "majority stake",
                   "joint venture", "amalgamation"),
        "mood": "strategic, corporate, decisive",
        "accent": "gold (#9A6B16) accent",
        "palette": "dark navy (#14233B), cream (#EAE3D6), gold (#9A6B16), deep corporate blue",
        "iconography": ("two overlapping corporate seal rings on a folded contract, a gold pen silhouette on signed paper, "
                       "linked metal rings, subtle city skyline lines, handshake silhouette"),
        "subject": "mergers, acquisitions and strategic deals",
        "avoid": "text overlays, human faces, bright saturated colors, stock-photo compositions, chaotic elements, warning colors",
    },
    "layoffs_restructure": {
        "tokens": ("layoff", "retrench", "workforce reduction", "restructuring", "shutdown", "downsize", "exit", "wind down"),
        "mood": "muted, human, consequential",
        "accent": "cool slate grey accent",
        "palette": "dark navy (#14233B), cream (#EAE3D6), cool slate grey, dim warm wood",
        "iconography": ("an empty office chair silhouette pushed back from a desk, a cardboard box shape on a surface, "
                       "a closing door geometry, dimmed overhead light lines, faint hallway perspective"),
        "subject": "workforce restructuring and downsizing",
        "avoid": "text overlays, human faces, bright saturated colors, stock-photo compositions, bright tones, growth charts",
    },
    "war_geopolitical": {
        "tokens": ("war", "conflict", "sanction", "tariff", "trade war", "embargo", "border tension", "geopolitical"),
        "mood": "grave, global, destabilizing",
        "accent": "cobalt blue (#1F56D6) accent",
        "palette": "dark navy (#14233B), cream (#EAE3D6), cobalt blue (#1F56D6), deep oxidized red",
        "iconography": ("a world-map outline with strategic arcs, layered shipping-container geometry at a port, "
                       "a flag silhouette against smoke-toned sky, red highlighted regions on a globe, newspaper headline textures"),
        "subject": "geopolitical conflict and trade risk",
        "avoid": "text overlays, human faces, bright saturated colors, stock-photo compositions, specific national identifiers, celebration tones",
    },
    "capex_growth": {
        "tokens": ("capex", "capacity expansion", "new plant", "factory", "greenfield", "brownfield", "investment plan",
                   "expansion", "ramp-up", "order book"),
        "mood": "constructive, ambitious, industrial",
        "accent": "emerald green (#0F7A5C) accent",
        "palette": "dark navy (#14233B), cream (#EAE3D6), emerald green (#0F7A5C), industrial concrete grey",
        "iconography": ("a crane silhouette against a dusk skyline, a partially unrolled blueprint with grid lines, "
                       "stacked geometric building blocks, steel-girder assembly shapes, ascending volume bars"),
        "subject": "capex and capacity expansion",
        "avoid": "text overlays, human faces, bright saturated colors, stock-photo compositions, abstract finance icons, dark/threatening tones",
    },
    "downgrade_risk": {
        "tokens": ("downgrade", "rating cut", "default", "stress", "distressed", "credit risk", "npa", "asset quality"),
        "mood": "cautionary, analytical, alert",
        "accent": "gold (#9A6B16) accent",
        "palette": "dark navy (#14233B), cream (#EAE3D6), gold (#9A6B16), cool slate grey",
        "iconography": ("a credit-rating arrow pointing down, a stress-test gauge tilting into amber, "
                       "warning-triangle overlay on a balance sheet, a single document under harsh cone of light"),
        "subject": "credit downgrade and asset-quality risk",
        "avoid": "text overlays, human faces, bright saturated colors, stock-photo compositions, green, celebratory cues",
    },
    "ipo_listing": {
        "tokens": ("ipo", "listing", "drhp", "rhp", "anchor allotment", "prospectus", "subscription", "grey market premium"),
        "mood": "anticipatory, formal, milestone",
        "accent": "gold (#9A6B16) accent",
        "palette": "dark navy (#14233B), cream (#EAE3D6), gold (#9A6B16), polished navy",
        "iconography": ("a ceremonial bell on a polished podium silhouette, a hardbound prospectus with ribbon, "
                       "ticker-board geometry with NEW LISTING banner shape, soft spotlight cone"),
        "subject": "IPO listing and public-market debut",
        "avoid": "text overlays, human faces, bright saturated colors, stock-photo compositions, chaotic motion, warning colors",
    },
    "dividend_buyback": {
        "tokens": ("dividend", "buyback", "interim dividend", "special dividend", "payout", "tender offer"),
        "mood": "reassuring, shareholder-friendly, steady",
        "accent": "soft gold accent",
        "palette": "dark navy (#14233B), cream (#EAE3D6), soft gold, sage green",
        "iconography": ("gold coins arranged in steady stacks, a dividend-warrant silhouette, a corporate seal on a cheque-style document, "
                       "freshly printed share certificate beside a fountain-pen shape"),
        "subject": "dividends and buybacks",
        "avoid": "text overlays, human faces, bright saturated colors, stock-photo compositions, charts going down, cold tones",
    },
    "market_trend": {
        "tokens": ("trend", "sector rotation", "macro", "policy", "market", "rally", "correction", "volatility", "flows"),
        "mood": "observational, structural, data-dense",
        "accent": "cobalt blue (#1F56D6) accent",
        "palette": "dark navy (#14233B), cream (#EAE3D6), cobalt blue (#1F56D6), emerald green (#0F7A5C)",
        "iconography": ("a stacked sector-performance heatmap, a Bloomberg-style terminal screen glow, "
                       "trading-floor monitor wall geometry, layered ticker tape, subtle grid overlay"),
        "subject": "market trends and sector rotation",
        "avoid": "text overlays, human faces, bright saturated colors, stock-photo compositions, celebration cues, dark threatening tones",
    },
    "policy_macro": {
        "tokens": ("rbi", "monetary policy", "repo rate", "inflation", "gdp", "fiscal", "budget", "gst", "mpc"),
        "mood": "institutional, authoritative, macro-lens",
        "accent": "gold (#9A6B16) accent",
        "palette": "dark navy (#14233B), cream (#EAE3D6), gold (#9A6B16), marble white",
        "iconography": ("a neoclassical central-bank colonnade silhouette, a policy document with embossed seal, "
                       "an interest-rate dial/gauge, balance scales on a marble surface, radiating policy-wave circles"),
        "subject": "RBI monetary policy and macro-economics",
        "avoid": "text overlays, human faces, bright saturated colors, stock-photo compositions, individual political figures, flag-prominent imagery, chaotic tones",
    },
}


def _classify_story_intent(text: str) -> tuple[str, dict[str, Any]]:
    """Classify article into one of the visual intent buckets.
    Returns (intent_key, visual_directive_dict)."""
    for key, lib in _INTENT_VISUAL_LIBRARY.items():
        if any(token in text for token in lib["tokens"]):
            return key, lib
    # Default: generic results / company event
    return "results_beat", _INTENT_VISUAL_LIBRARY["results_beat"]


def _story_intent(article: ContentArticlePackage) -> str:
    """Legacy single-line intent for backward compat (used in cover prompt)."""
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
    intent_key, lib = _classify_story_intent(text)
    return (
        f"INTENT={intent_key.upper()}. Mood: {lib['mood']}. The reader must understand at a glance "
        f"that the story is about {intent_key.replace('_', ' ')}."
    )


def _story_visual_directive(article: ContentArticlePackage) -> dict[str, Any]:
    """Rich visual directive: mood, palette, iconography, subject, avoid."""
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
    intent_key, lib = _classify_story_intent(text)
    return {"intent_key": intent_key, **lib}


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
        os.getenv("AZURE_AI_FOUNDRY_IMAGE_OPENAI_BASE_URL")
        or os.getenv("AZURE_GPT_IMAGE2_BASE_URL")
        or os.getenv("AZURE_AI_FOUNDRY_OPENAI_BASE_URL")
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
        or "gpt-image-2"
    ).strip()
    foundry_deployment = _normalize_image_model(foundry_deployment)
    if foundry_deployment.lower() == "gpt-image-2":
        foundry_openai_base_url = _normalize_image_base_url(
            os.getenv("AZURE_AI_FOUNDRY_IMAGE_OPENAI_BASE_URL")
            or os.getenv("AZURE_GPT_IMAGE2_BASE_URL")
            or "https://prospektus-resource.services.ai.azure.com/openai/v1"
        )
    foundry_api_version = (os.getenv("AZURE_AI_FOUNDRY_IMAGE_API_VERSION") or "2025-04-01-preview").strip()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    openai_base_url = _normalize_image_base_url(os.getenv("FINAGENT_CONTENT_IMAGE_BASE_URL"))
    openai_model = _normalize_image_model((os.getenv("FINAGENT_CONTENT_IMAGE_MODEL") or "chatgpt-image-2").strip())
    force_foundry_chatgpt_image_2 = (
        os.getenv("FINAGENT_CONTENT_IMAGE_FORCE_FOUNDRY_CHATGPT_IMAGE_2", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )
    foundry_request_url = None
    if foundry_resource_endpoint and foundry_deployment:
        foundry_request_url = _foundry_image_generation_url(foundry_resource_endpoint, foundry_deployment, foundry_api_version)
    elif foundry_openai_base_url and foundry_deployment:
        inferred_resource_endpoint = _normalize_foundry_resource_endpoint(foundry_openai_base_url)
        if inferred_resource_endpoint:
            foundry_request_url = _foundry_image_generation_url(inferred_resource_endpoint, foundry_deployment, foundry_api_version)

    # Product default: when Azure Foundry credentials + image deployment are
    # configured (the customer-supplied path), prefer Foundry's gpt-image-2
    # over the direct OpenAI route. Override with FINAGENT_CONTENT_IMAGE_PROVIDER=openai.
    foundry_ready = bool(
        foundry_key
        and foundry_deployment
        and (foundry_image_endpoint or foundry_openai_base_url or foundry_resource_endpoint)
    )
    foundry_token_ready = bool(
        foundry_deployment
        and foundry_deployment.lower() == "gpt-image-2"
        and (foundry_openai_base_url or foundry_resource_endpoint)
    )
    if provider != "openai" and (foundry_ready or foundry_token_ready):
        return _ImageClientConfig(
            api_key=foundry_key,
            model=foundry_deployment,
            provider="azure-foundry",
            base_url=foundry_openai_base_url or foundry_resource_endpoint,
            image_endpoint=foundry_image_endpoint,
            request_url=foundry_request_url,
            api_version=foundry_api_version,
        )

    # Fallback: chatgpt-image-2 via direct OpenAI credentials if Foundry isn't set.
    if openai_key and openai_model.lower() == "chatgpt-image-2" and not force_foundry_chatgpt_image_2:
        return _ImageClientConfig(
            api_key=openai_key,
            model=openai_model,
            provider="openai",
            base_url=openai_base_url,
        )

    if provider in {"foundry", "azure", "azure_foundry", "mai"}:
        if (foundry_key and (foundry_image_endpoint or foundry_openai_base_url or foundry_resource_endpoint) and foundry_deployment) or foundry_token_ready:
            return _ImageClientConfig(
                api_key=foundry_key,
                model=foundry_deployment,
                provider="azure-foundry",
                base_url=foundry_openai_base_url or foundry_resource_endpoint,
                image_endpoint=foundry_image_endpoint,
                request_url=foundry_request_url,
                api_version=foundry_api_version,
            )
        logger.warning(
            "Azure Foundry image provider selected but required config is missing; "
            "set AZURE_GPT_IMAGE2_BASE_URL + AZURE_AI_FOUNDRY_IMAGE_DEPLOYMENT=gpt-image-2 "
            "for token auth, or provide API-key based settings."
        )

    if provider == "openai":
        if openai_key and openai_model:
            return _ImageClientConfig(
                api_key=openai_key,
                model=openai_model,
                provider="openai",
                base_url=openai_base_url,
            )
        logger.warning("OpenAI image provider selected but OPENAI_API_KEY or model is missing")

    # Default routing: if Foundry is unavailable, use OPENAI_API_KEY for direct
    # chatgpt-image-2 generation when configured.
    if provider not in {"foundry", "azure", "azure_foundry", "mai"}:
        if openai_key and openai_model.lower() == "chatgpt-image-2":
            return _ImageClientConfig(
                api_key=openai_key,
                model=openai_model,
                provider="openai",
                base_url=openai_base_url,
            )

    if (foundry_key and (foundry_image_endpoint or foundry_openai_base_url or foundry_resource_endpoint) and foundry_deployment) or foundry_token_ready:
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
                "prompt": "A light editorial earnings-and-guidance cover with forecast cards, upward momentum, management outlook cues, and a premium publication finish",
            }
        if any(token in text for token in ("deal", "order", "tcv", "pipeline", "wins")):
            return {
                "kind": "earnings",
                "variant": "dealwins",
                "badge": "Earnings",
                "cues": ["Deal wins", "Order book", "Margins"],
                "prompt": "A light editorial earnings cover focused on deal wins, order-book momentum, statement pages, and a strong company-linked visual center",
            }
        return {
            "kind": "earnings",
            "variant": "standard",
            "badge": "Earnings",
            "cues": ["Revenue", "Margins", "Guidance"],
            "prompt": "A light editorial earnings cover with statement pages, a guidance chart, polished market panels, and a strong focal subject tied to the company",
        }
    if "sebi" in text or "regulat" in text or "order" in text or "probe" in text:
        return {
            "kind": "regulation",
            "variant": "standard",
            "badge": "Regulation",
            "cues": ["Order", "Filings", "Timeline"],
            "prompt": "A bright editorial compliance scene with official papers, a verification seal, timeline markers, and premium legal-finance details",
        }
    if any(token in text for token in ("acquire", "stake", "deal", "invest", "merger", "majority")):
        return {
            "kind": "deal",
            "variant": "standard",
            "badge": "Deal",
            "cues": ["Stake", "Capital", "Network"],
            "prompt": "A polished M&A editorial image with connected entities, transaction documents, travel or sector props when relevant, and a confident publication finish",
        }
    if any(token in text for token in ("trend", "sector", "theme", "macro", "policy")):
        return {
            "kind": "trend",
            "variant": "standard",
            "badge": "Trend",
            "cues": ["Sector", "Momentum", "Shift"],
            "prompt": "A light editorial market-trend visual with layered charts, sector tiles, policy papers, and calm strategic composition",
        }
    if any(token in text for token in ("company", "ownership", "board", "governance", "shareholder")):
        return {
            "kind": "company",
            "variant": "standard",
            "badge": "Company",
            "cues": ["Ownership", "Board", "Capital"],
            "prompt": "A refined company-intelligence cover with governance papers, corporate architecture, connected nodes, and a premium research-desk feel",
        }
    return {
        "kind": "company",
        "variant": "standard",
        "badge": "Research",
        "cues": ["Coverage", "Signals", "Context"],
        "prompt": "A polished market-research cover with balanced editorial composition, company context, and warm publication styling",
    }


def _cover_palette(article: ContentArticlePackage) -> dict[str, tuple[int, int, int]]:
    profile = _topic_profile(article)
    palettes: dict[str, list[dict[str, tuple[int, int, int]]]] = {
        "earnings": [
            {
                "bg_top": (249, 243, 235),
                "bg_bottom": (238, 228, 214),
                "frame": (255, 250, 243),
                "panel_top": (251, 247, 240),
                "panel_bottom": (233, 224, 209),
                "ink": (24, 37, 52),
                "muted": (104, 115, 131),
                "line": (207, 191, 171),
                "accent": (13, 118, 110),
                "accent_soft": (233, 146, 85),
                "accent_alt": (69, 128, 201),
                "glow_a": (245, 205, 142),
                "glow_b": (170, 215, 205),
                "chip": (184, 30, 30),
            },
            {
                "bg_top": (250, 244, 238),
                "bg_bottom": (235, 229, 217),
                "frame": (255, 251, 246),
                "panel_top": (250, 246, 239),
                "panel_bottom": (229, 223, 212),
                "ink": (28, 39, 59),
                "muted": (108, 117, 130),
                "line": (208, 196, 181),
                "accent": (31, 127, 160),
                "accent_soft": (240, 165, 102),
                "accent_alt": (67, 108, 188),
                "glow_a": (252, 210, 151),
                "glow_b": (181, 206, 236),
                "chip": (192, 36, 24),
            },
        ],
        "regulation": [
            {
                "bg_top": (248, 242, 235),
                "bg_bottom": (235, 227, 220),
                "frame": (255, 250, 245),
                "panel_top": (250, 246, 240),
                "panel_bottom": (233, 226, 220),
                "ink": (39, 37, 47),
                "muted": (118, 108, 111),
                "line": (210, 196, 188),
                "accent": (134, 38, 53),
                "accent_soft": (199, 151, 88),
                "accent_alt": (75, 103, 140),
                "glow_a": (241, 213, 182),
                "glow_b": (224, 190, 201),
                "chip": (150, 30, 46),
            }
        ],
        "deal": [
            {
                "bg_top": (250, 244, 236),
                "bg_bottom": (238, 230, 219),
                "frame": (255, 250, 244),
                "panel_top": (252, 248, 241),
                "panel_bottom": (236, 227, 214),
                "ink": (32, 42, 57),
                "muted": (111, 118, 128),
                "line": (208, 193, 176),
                "accent": (207, 111, 60),
                "accent_soft": (86, 146, 208),
                "accent_alt": (18, 132, 122),
                "glow_a": (244, 210, 167),
                "glow_b": (185, 212, 232),
                "chip": (181, 54, 27),
            }
        ],
        "company": [
            {
                "bg_top": (248, 243, 234),
                "bg_bottom": (234, 228, 216),
                "frame": (255, 250, 244),
                "panel_top": (249, 246, 239),
                "panel_bottom": (229, 223, 212),
                "ink": (31, 41, 54),
                "muted": (106, 115, 124),
                "line": (206, 193, 179),
                "accent": (19, 121, 115),
                "accent_soft": (191, 149, 83),
                "accent_alt": (107, 129, 189),
                "glow_a": (236, 216, 175),
                "glow_b": (190, 219, 215),
                "chip": (177, 98, 39),
            }
        ],
        "trend": [
            {
                "bg_top": (246, 243, 237),
                "bg_bottom": (231, 232, 226),
                "frame": (252, 250, 245),
                "panel_top": (246, 248, 244),
                "panel_bottom": (226, 231, 225),
                "ink": (29, 42, 53),
                "muted": (102, 116, 124),
                "line": (193, 203, 199),
                "accent": (18, 121, 114),
                "accent_soft": (92, 144, 211),
                "accent_alt": (210, 149, 80),
                "glow_a": (206, 231, 214),
                "glow_b": (205, 220, 241),
                "chip": (163, 89, 30),
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


async def _generate_image(req: ContentAutomationRequest, article: ContentArticlePackage, route_base: str) -> tuple[bytes, str, str, str]:
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
                preferred_size = "1024x1024" if config.model.lower() == "gpt-image-2" else "1536x1024"

                token_flow_error: str | None = None
                if config.base_url and config.model.lower() == "gpt-image-2":
                    try:
                        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
                        from openai import OpenAI

                        def _generate_with_azure_token() -> tuple[bytes | None, str | None]:
                            proxy_keys = (
                                "HTTP_PROXY",
                                "HTTPS_PROXY",
                                "ALL_PROXY",
                                "http_proxy",
                                "https_proxy",
                                "all_proxy",
                            )
                            original_env = {key: os.environ.get(key) for key in proxy_keys}
                            try:
                                # Some local environments inject a dead localhost proxy (127.0.0.1:9).
                                # Clear proxy env for token + Foundry calls so auth can complete.
                                for key in proxy_keys:
                                    os.environ.pop(key, None)
                                azure_cfg = os.getenv("AZURE_CONFIG_DIR") or str(repo_root() / ".azurecli")
                                os.environ["AZURE_CONFIG_DIR"] = azure_cfg
                                Path(azure_cfg).mkdir(parents=True, exist_ok=True)

                                token_provider = get_bearer_token_provider(
                                    DefaultAzureCredential(),
                                    "https://ai.azure.com/.default",
                                )
                                client = OpenAI(
                                    base_url=_foundry_openai_base_url(config.base_url or ""),
                                    api_key=token_provider,
                                )
                                response = client.images.generate(
                                    model=config.model,
                                    prompt=prompt,
                                    n=1,
                                    size="1024x1024",
                                )
                                data = response.data[0] if getattr(response, "data", None) else None
                                if data is None:
                                    raise RuntimeError("Azure gpt-image-2 returned an empty image payload")
                                b64 = (
                                    getattr(data, "b64_json", None)
                                    or getattr(data, "image_base64", None)
                                    or getattr(data, "base64", None)
                                )
                                if b64:
                                    return base64.b64decode(b64), None
                                image_url = getattr(data, "url", None)
                                return None, image_url
                            finally:
                                for key, value in original_env.items():
                                    if value is None:
                                        os.environ.pop(key, None)
                                    else:
                                        os.environ[key] = value

                        token_image_bytes, token_image_url = await asyncio.to_thread(_generate_with_azure_token)
                        if token_image_bytes:
                            return token_image_bytes, ".png", "image/png", f"azure-foundry:{config.model}"
                        if token_image_url:
                            async with httpx.AsyncClient(timeout=60.0, trust_env=False) as http_client:
                                image_response = await http_client.get(token_image_url)
                                image_response.raise_for_status()
                                remote_type = (image_response.headers.get("content-type") or "image/png").split(";")[0].strip()
                                return image_response.content, ".png", remote_type or "image/png", f"azure-foundry:{config.model}"
                        token_flow_error = "Azure gpt-image-2 token flow returned no bytes or URL"
                    except Exception as exc:
                        token_flow_error = str(exc)
                        logger.warning(
                            "Azure gpt-image-2 token flow failed for deployment %s: %s",
                            config.model,
                            token_flow_error[:300],
                        )

                direct_error: str | None = None
                if config.image_endpoint:
                    headers = {
                        "api-key": config.api_key,
                        "Content-Type": "application/json",
                    }
                    payload = {
                        "model": config.model,
                        "prompt": prompt,
                        "size": preferred_size,
                    }
                    async with httpx.AsyncClient(timeout=180.0, trust_env=False) as http_client:
                        response = await http_client.post(config.image_endpoint, headers=headers, json=payload)
                    if response.is_success:
                        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
                        if content_type.startswith("image/"):
                            return response.content, ".png", content_type, f"azure-foundry:{config.model}"
                        data = response.json()
                        items = data.get("data") if isinstance(data, dict) else None
                        if isinstance(items, list) and items:
                            first = items[0] or {}
                            b64 = first.get("b64_json")
                            if b64:
                                return base64.b64decode(b64), ".png", "image/png", f"azure-foundry:{config.model}"
                            image_url = first.get("url")
                            if image_url:
                                async with httpx.AsyncClient(timeout=60.0, trust_env=False) as http_client:
                                    image_response = await http_client.get(image_url)
                                    image_response.raise_for_status()
                                    remote_type = (image_response.headers.get("content-type") or "image/png").split(";")[0].strip()
                                    return image_response.content, ".png", remote_type or "image/png", f"azure-foundry:{config.model}"
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
                        image_args: dict[str, Any] = {
                            "model": config.model,
                            "prompt": prompt,
                            "size": preferred_size,
                        }
                        response = await client.images.generate(**image_args)
                        data = response.data[0]
                        b64 = (
                            getattr(data, "b64_json", None)
                            or getattr(data, "image_base64", None)
                            or getattr(data, "base64", None)
                        )
                        if b64:
                            return base64.b64decode(b64), ".png", "image/png", f"azure-foundry:{config.model}"
                        image_url = getattr(data, "url", None)
                        if image_url:
                            async with httpx.AsyncClient(timeout=60.0, trust_env=False) as http_client:
                                image_response = await http_client.get(image_url)
                                image_response.raise_for_status()
                                remote_type = (image_response.headers.get("content-type") or "image/png").split(";")[0].strip()
                                return image_response.content, ".png", remote_type or "image/png", f"azure-foundry:{config.model}"
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
                        "size": preferred_size,
                        "quality": "high",
                        "output_format": "png",
                    }
                    async with httpx.AsyncClient(timeout=180.0, trust_env=False) as http_client:
                        response = await http_client.post(config.request_url, headers=headers, json=payload)
                    if response.is_success:
                        content_type = (response.headers.get("content-type") or "image/png").split(";")[0].strip()
                        if content_type.startswith("image/"):
                            return response.content, ".png", content_type or "image/png", f"azure-foundry:{config.model}"
                        try:
                            data = response.json()
                            items = data.get("data") if isinstance(data, dict) else None
                            if isinstance(items, list) and items:
                                first = items[0] or {}
                                b64 = first.get("b64_json")
                                if b64:
                                    return base64.b64decode(b64), ".png", "image/png", f"azure-foundry:{config.model}"
                                image_url = first.get("url")
                                if image_url:
                                    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as http_client:
                                        image_response = await http_client.get(image_url)
                                        image_response.raise_for_status()
                                        remote_type = (image_response.headers.get("content-type") or "image/png").split(";")[0].strip()
                                        return image_response.content, ".png", remote_type or "image/png", f"azure-foundry:{config.model}"
                        except Exception:
                            logger.exception("Azure Foundry preview image response parsing failed")
                        # If we could not extract an image, return raw bytes as a fallback
                        return response.content, ".png", content_type or "image/png", f"azure-foundry:{config.model}"
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
                    if token_flow_error:
                        logger.error("Azure gpt-image-2 token flow attempt also failed: %s", token_flow_error[:400])
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
                    model_candidates = [config.model]
                    if config.model.lower() == "chatgpt-image-2":
                        model_candidates.append("gpt-image-1")
                    response = None
                    selected_model = config.model
                    last_error: Exception | None = None
                    for model_name in model_candidates:
                        image_args: dict[str, Any] = {
                            "model": model_name,
                            "prompt": prompt,
                            "size": "1536x1024",
                        }
                        try:
                            response = await client.images.generate(**image_args)
                            selected_model = model_name
                            if model_name != config.model:
                                logger.warning(
                                    "Image model %s unavailable for current key; fallback model %s succeeded",
                                    config.model,
                                    model_name,
                                )
                            break
                        except Exception as exc:
                            last_error = exc
                            message = str(exc).lower()
                            fallback_allowed = (
                                model_name == config.model
                                and model_name.lower() == "chatgpt-image-2"
                                and "does not exist" in message
                            )
                            if fallback_allowed:
                                logger.warning(
                                    "Image model %s unavailable (%s). Retrying with gpt-image-1.",
                                    model_name,
                                    str(exc)[:220],
                                )
                                continue
                            raise
                    if response is None:
                        if last_error:
                            raise last_error
                        raise RuntimeError("Image generation failed with no response")
                finally:
                    await client.close()
                data = response.data[0]
                b64 = (
                    getattr(data, "b64_json", None)
                    or getattr(data, "image_base64", None)
                    or getattr(data, "base64", None)
                )
                if b64:
                    return base64.b64decode(b64), ".png", "image/png", f"openai:{selected_model}"
                image_url = getattr(data, "url", None)
                if image_url:
                    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as http_client:
                        image_response = await http_client.get(image_url)
                        image_response.raise_for_status()
                        content_type = (image_response.headers.get("content-type") or "image/png").split(";")[0].strip()
                        return image_response.content, ".png", content_type or "image/png", f"openai:{selected_model}"
        except Exception:
            logger.exception("Image generation failed; falling back to local cover renderer")
    png = render_cover_png(article)
    if png:
        return png, ".png", "image/png", "local-renderer:png"
    svg = render_cover_svg(article)
    return svg.encode("utf-8"), ".svg", "image/svg+xml", "local-renderer:svg"


async def _generate_cover_for_article(
    req: ContentAutomationRequest,
    article: ContentArticlePackage,
    route_base: str,
    *,
    publish_status: str,
    retries: int = 3,
    retry_delay_seconds: float = 1.5,
) -> tuple[bytes, str, str, str]:
    """
    Generate a cover asset and prefer Foundry gpt-image-2 for publish-ready stories.

    For published articles we always request an image (even if include_image=False on the
    incoming request) and retry when the provider falls back away from gpt-image-2.
    """
    must_have_cover = str(publish_status or "").lower() == "published"
    image_req = req.model_copy(update={"include_image": bool(req.include_image or must_have_cover)})

    attempts = max(1, int(retries)) if must_have_cover else 1
    last_result: tuple[bytes, str, str, str] | None = None
    for attempt in range(1, attempts + 1):
        result = await _generate_image(image_req, article, route_base)
        last_result = result
        provider = str(result[3] or "")
        if not must_have_cover:
            return result
        if provider.startswith("azure-foundry:gpt-image-2"):
            return result
        if attempt < attempts:
            logger.warning(
                "Cover generation for %s used provider %s (attempt %s/%s); retrying for gpt-image-2",
                article.slug,
                provider or "unknown",
                attempt,
                attempts,
            )
            await asyncio.sleep(max(0.0, float(retry_delay_seconds)))

    if last_result is None:
        raise RuntimeError("Cover generation did not produce a result")
    return last_result


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
            f'<g><rect x="{x}" y="{y}" rx="24" ry="24" width="{width}" height="56" fill="rgba(96,165,250,0.10)" stroke="#60A5FA" stroke-opacity="0.32" />'
            f'<text x="{x + 24}" y="{y + 36}" fill="#EAF3FF" font-size="24" font-family="Manrope, Arial, sans-serif" font-weight="700">{safe}</text></g>'
        )
        x += width + 16
        if x > 1180:
            break

    return f"""<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"1536\" height=\"1024\" viewBox=\"0 0 1536 1024\" role=\"img\" aria-label=\"{html.escape(article.hero_title)}\">
  <defs>
    <linearGradient id=\"bg\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\">
      <stop offset=\"0%\" stop-color=\"#03060d\" />
      <stop offset=\"58%\" stop-color=\"#061224\" />
      <stop offset=\"100%\" stop-color=\"#0a1838\" />
    </linearGradient>
    <linearGradient id=\"ink\" x1=\"0\" y1=\"0\" x2=\"1\" y2=\"1\">
      <stop offset=\"0%\" stop-color=\"#EAF3FF\" />
      <stop offset=\"100%\" stop-color=\"#60A5FA\" />
    </linearGradient>
    <radialGradient id=\"glowCyan\" cx=\"50%\" cy=\"50%\" r=\"50%\">
      <stop offset=\"0%\" stop-color=\"#60A5FA\" stop-opacity=\"0.32\" />
      <stop offset=\"100%\" stop-color=\"#60A5FA\" stop-opacity=\"0\" />
    </radialGradient>
    <radialGradient id=\"glowViolet\" cx=\"50%\" cy=\"50%\" r=\"50%\">
      <stop offset=\"0%\" stop-color=\"#8B5CF6\" stop-opacity=\"0.30\" />
      <stop offset=\"100%\" stop-color=\"#8B5CF6\" stop-opacity=\"0\" />
    </radialGradient>
  </defs>
  <rect width=\"1536\" height=\"1024\" fill=\"url(#bg)\" />
  <circle cx=\"190\" cy=\"176\" r=\"260\" fill=\"url(#glowCyan)\" />
  <circle cx=\"1330\" cy=\"164\" r=\"300\" fill=\"url(#glowViolet)\" />
  <rect x=\"54\" y=\"54\" width=\"1428\" height=\"916\" rx=\"44\" fill=\"rgba(8,16,32,0.78)\" stroke=\"#60A5FA\" stroke-opacity=\"0.22\" stroke-width=\"1\" />
  <rect x=\"862\" y=\"164\" width=\"528\" height=\"548\" rx=\"32\" fill=\"rgba(10,22,44,0.92)\" stroke=\"#60A5FA\" stroke-opacity=\"0.28\" />
  <path d=\"M910 618 C1018 468 1118 552 1212 430 C1274 350 1328 326 1364 318\" fill=\"none\" stroke=\"#34D399\" stroke-width=\"10\" stroke-linecap=\"round\" />
  <path d=\"M910 654 C1010 596 1108 616 1210 534 C1280 478 1334 458 1364 452\" fill=\"none\" stroke=\"#8B5CF6\" stroke-width=\"7\" stroke-linecap=\"round\" stroke-opacity=\"0.85\" />
  <g fill=\"#C7D2FE\" opacity=\"0.85\">
    <rect x=\"930\" y=\"720\" width=\"32\" height=\"122\" rx=\"12\" />
    <rect x=\"986\" y=\"664\" width=\"32\" height=\"178\" rx=\"12\" />
    <rect x=\"1042\" y=\"610\" width=\"32\" height=\"232\" rx=\"12\" />
    <rect x=\"1098\" y=\"674\" width=\"32\" height=\"168\" rx=\"12\" />
    <rect x=\"1154\" y=\"564\" width=\"32\" height=\"278\" rx=\"12\" />
    <rect x=\"1210\" y=\"706\" width=\"32\" height=\"136\" rx=\"12\" />
  </g>
  <text x=\"96\" y=\"132\" fill=\"#60A5FA\" font-size=\"26\" font-family=\"IBM Plex Mono, monospace\" font-weight=\"600\" letter-spacing=\"4\">PROSPEKTLAB INSIGHT</text>
  <text x=\"96\" y=\"250\" fill=\"url(#ink)\" font-size=\"94\" font-family=\"Newsreader, Georgia, serif\" font-weight=\"700\">{title_svg}</text>
  <text x=\"96\" y=\"560\" fill=\"#A8B4C8\" font-size=\"30\" font-family=\"Manrope, Arial, sans-serif\" font-weight=\"600\">{subtitle_svg}</text>
  <text x=\"96\" y=\"714\" fill=\"#C7D2FE\" font-size=\"26\" font-family=\"IBM Plex Mono, monospace\" font-weight=\"500\" letter-spacing=\"3\">EDITORIAL REPORT</text>
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

    filtered_metrics = _filter_public_metrics(
        [
            metric.model_dump() if hasattr(metric, "model_dump") else metric
            for metric in list(article.metrics or [])
        ]
    )
    filtered_tables = _filter_public_tables(
        [
            table.model_dump() if hasattr(table, "model_dump") else table
            for table in list(article.tables or [])
        ]
    )
    metric_count = len(filtered_metrics)
    table_count = len(filtered_tables)
    visual_count = len(
        _filter_public_visuals(
            [
                visual.model_dump() if hasattr(visual, "model_dump") else visual
                for visual in list(article.visuals or [])
            ]
        )
    )
    timeline_count = len(article.timeline or [])
    evidence_note_count = len(article.evidence_notes or [])
    business_numeric_present = bool(
        any(_metric_has_business_numeric_signal(metric) for metric in filtered_metrics)
        or any(_table_has_business_numeric_rows(table) for table in filtered_tables)
    )

    if metric_count >= 4:
        score += 8
        reasons.append("structured metrics included")
    elif metric_count > 0:
        score += 4
    else:
        reasons.append("insufficient_structured_evidence")

    if table_count >= 1:
        score += 8
        reasons.append("metrics table included")
    elif business_numeric_present:
        reasons.append("missing_metrics_table")

    if visual_count >= 1:
        score += 8
        reasons.append("visual block included")
    elif business_numeric_present:
        reasons.append("visual_block_not_available")

    if evidence_note_count >= 3:
        score += 6
        reasons.append("evidence notes included")

    if (req.topic or "").lower().find("sebi") >= 0 and timeline_count == 0:
        reasons.append("timeline_missing")

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
    confidence_score, publish_reasons = _score_publishability(req, article, sources)
    publish_status = "published" if (req.force_publish or confidence_score >= 70) else "draft"

    image_bytes, image_ext, image_mime, cover_provider = await _generate_cover_for_article(
        req,
        article,
        route_base,
        publish_status=publish_status,
    )
    image_name = f"cover{image_ext}"
    html_relative_image = f"/{route_base}/{slug}/{image_name}"
    html_text = render_article_html(
        article,
        f"{_SITE_URL}/{route_base}/{slug}/",
        html_relative_image,
        generated_at,
        meta={"sources_used": sources},
    )

    image_path = article_dir / image_name
    html_path = article_dir / "index.html"
    json_path = article_dir / "article.json"
    _write_bytes(image_path, image_bytes)
    _write_text(html_path, html_text)

    result = ContentAutomationResult(
        slug=slug,
        title=article.title,
        description=article.description,
        route_base=route_base,
        public_url=f"{_SITE_URL}/{route_base}/{slug}/",
        html_path=str(html_path),
        json_path=str(json_path),
        image_path=str(image_path),
        image_mime=image_mime,
        cover_provider=cover_provider,
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
            public_dirs = _public_article_dirs(route_base, slug)
            for public_dir in public_dirs:
                _write_text(public_dir / "index.html", html_text)
                _write_bytes(public_dir / image_name, image_bytes)
            public_mirror = str(public_dirs[0])
            mirrored_sitemap = _upsert_sitemap(route_base, slug)
            refresh_public_research_hub(route_base)
            submit_sitemap()
        except Exception:
            logger.exception("Failed to mirror generated article into frontend public directory")

    payload = {
        **result.model_dump(),
        "mirrored_public_path": public_mirror,
        "mirrored_sitemap": mirrored_sitemap,
        "requested_by": requested_by,
        "image_mime": image_mime,
        "cover_provider": cover_provider,
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


# ── Publish / unpublish helpers (used by flash engine and API routes) ─────────

def _fallback_cover_svg_for_publish(title: str) -> str:
    clean_title = " ".join(str(title or "").strip().split()) or "ProspektLab Research"
    words = clean_title.split(" ")
    wrapped: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if len(candidate) <= 34:
            current = candidate
            continue
        if current:
            wrapped.append(current)
        current = word
    if current:
        wrapped.append(current)
    wrapped = wrapped[:3] or ["ProspektLab Research"]

    text_lines: list[str] = []
    y = 300
    for line in wrapped:
        safe = html.escape(line)
        text_lines.append(
            f'<text x="96" y="{y}" fill="#EAF3FF" font-size="72" font-family="Newsreader, Georgia, serif" '
            f'font-weight="700">{safe}</text>'
        )
        y += 88

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1536" height="1024" viewBox="0 0 1536 1024" role="img" '
        f'aria-label="{html.escape(clean_title)} cover">\n'
        "  <defs>\n"
        '    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">\n'
        '      <stop offset="0%" stop-color="#03060d"/>\n'
        '      <stop offset="58%" stop-color="#061224"/>\n'
        '      <stop offset="100%" stop-color="#0a1838"/>\n'
        "    </linearGradient>\n"
        "  </defs>\n"
        '  <rect width="1536" height="1024" fill="url(#bg)"/>\n'
        '  <circle cx="190" cy="176" r="240" fill="#60A5FA" fill-opacity="0.18"/>\n'
        '  <circle cx="1320" cy="200" r="280" fill="#8B5CF6" fill-opacity="0.14"/>\n'
        '  <rect x="54" y="54" width="1428" height="916" rx="44" fill="rgba(8,16,32,0.72)" stroke="#60A5FA" stroke-opacity="0.24"/>\n'
        '  <text x="96" y="132" fill="#60A5FA" font-size="24" font-family="IBM Plex Mono, monospace" font-weight="600" letter-spacing="4">PROSPEKTLAB INSIGHT</text>\n'
        f"  {' '.join(text_lines)}\n"
        '  <text x="96" y="860" fill="#A8B4C8" font-size="30" font-family="Manrope, Arial, sans-serif">Image fallback rendered automatically</text>\n'
        "</svg>\n"
    )


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
    publish_gate = manifest.get("publish_gate")
    if not isinstance(publish_gate, dict):
        publish_gate = {}
    publish_gate["status"] = "publish"
    if not publish_gate.get("score"):
        publish_gate["score"] = int(manifest.get("publish_gate_score") or 100)
    metrics = publish_gate.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    metrics["manual_publish_override"] = True
    publish_gate["metrics"] = metrics
    manifest["publish_gate"] = publish_gate
    manifest["publish_gate_status"] = "publish"

    # Mirror current HTML render
    html_text = load_generated_article_html(slug, route_base=route_base)
    if html_text:
        pub_dirs = _public_article_dirs(route_base, slug)

        # Mirror image(s) and article HTML to every public tree we ship.
        article_dir = _article_dir(route_base, slug)
        cover_files = list(article_dir.glob("cover.*"))
        if not cover_files:
            fallback_cover = article_dir / "cover.svg"
            _write_text(
                fallback_cover,
                _fallback_cover_svg_for_publish(str(manifest.get("title") or slug)),
            )
            cover_files = [fallback_cover]
            manifest["image_path"] = str(fallback_cover)
            manifest["image_mime"] = "image/svg+xml"
            manifest["cover_provider"] = str(manifest.get("cover_provider") or "local-renderer:svg")
        else:
            if not manifest.get("image_path"):
                manifest["image_path"] = str(cover_files[0])
            if not manifest.get("image_mime"):
                ext = cover_files[0].suffix.lower()
                manifest["image_mime"] = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                    ".svg": "image/svg+xml",
                }.get(ext, "application/octet-stream")
        for pub_dir in pub_dirs:
            _write_text(pub_dir / "index.html", html_text)
            for img_file in cover_files:
                _write_bytes(pub_dir / img_file.name, img_file.read_bytes())

        manifest["mirrored_public_path"] = str(pub_dirs[0])

    sitemap_path = _upsert_sitemap(route_base, slug)
    manifest["mirrored_sitemap"] = sitemap_path
    refresh_public_research_hub(route_base)
    submit_sitemap()

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
    manifest["publish_gate_status"] = "draft"
    publish_gate = manifest.get("publish_gate")
    if isinstance(publish_gate, dict):
        publish_gate["status"] = "draft"
        manifest["publish_gate"] = publish_gate

    # Remove public mirror
    import shutil
    for pub_dir in _public_article_dirs(route_base, slug):
        if pub_dir.is_dir():
            try:
                shutil.rmtree(pub_dir)
            except Exception:
                logger.exception("Failed to remove public mirror %s", pub_dir)
    manifest["mirrored_public_path"] = None
    refresh_public_research_hub(route_base)
    submit_sitemap()

    _write_text(json_path, json.dumps(manifest, indent=2, ensure_ascii=True))
    return manifest

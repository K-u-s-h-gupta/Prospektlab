"""Portfolio-scoped news fetcher using multi-source pipeline.

Pipeline:
1. For each top-12 holding by market value: pull raw items from all source families in parallel
2. Add one portfolio-wide market context query
3. Filter to allow-list domains only
4. Drop items older than 7 days
5. Compute scores; drop items with score < 0.5
6. Deduplicate
7. Sort by score desc
8. Take top N (default 12); cache per tenant 10m
"""
from __future__ import annotations

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from typing import Any

from finagent.portfolio_mirrors import PositionMirror
from finagent.news.sources import fetch_all_sources, fetch_market_context
from finagent.news.scorer import score_item, tag_category, parse_published_at, VERIFIED_DOMAINS
from finagent.news.dedupe import deduplicate
from finagent.news.cache import cache_get, cache_set

logger = logging.getLogger("finagent.portfolio.news")


def _is_verified_domain(url: str) -> bool:
    """Check if URL domain is in the verified allow-list."""
    url_lower = url.lower()
    for domain in VERIFIED_DOMAINS:
        if domain in url_lower:
            return True
    return False


def _age_label(published_dt: datetime | None) -> str:
    """Return a human-readable age label."""
    if published_dt is None:
        return ""
    now = datetime.now(timezone.utc)
    if published_dt.tzinfo is None:
        published_dt = published_dt.replace(tzinfo=timezone.utc)
    delta = now - published_dt
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return "Just now"
    if hours < 24:
        return f"{int(hours)}h ago"
    days = int(hours / 24)
    if days < 7:
        return f"{days}d ago"
    return f"{days // 7}w ago"


def _freshness_label(published_dt: datetime | None) -> str:
    """Return freshness classification."""
    if published_dt is None:
        return "recent"
    now = datetime.now(timezone.utc)
    if published_dt.tzinfo is None:
        published_dt = published_dt.replace(tzinfo=timezone.utc)
    hours = (now - published_dt).total_seconds() / 3600
    if hours < 4:
        return "breaking"
    if hours < 24:
        return "fresh"
    return "recent"


def _compute_tenant_cache_key(tenant_id: str) -> str:
    return hashlib.sha256(f"portfolio_news:{tenant_id}".encode()).hexdigest()[:16]


def fetch_portfolio_news(
    positions: list[PositionMirror],
    *,
    limit: int = 12,
    per_holding_limit: int = 3,
) -> list[dict[str, Any]]:
    """Return deduplicated, scored, verified news for the top-N holdings."""
    if not positions:
        return []

    # Check cache per tenant (combined ranked result)
    # We use a simple tenant hash from first position
    tenant_id = getattr(positions[0], "tenant_id", "default") if positions else "default"
    cache_key = _compute_tenant_cache_key(tenant_id)
    cached = cache_get(cache_key, ttl_minutes=10, source="combined")
    if cached is not None:
        return cached

    # Top 12 holdings by market value
    top = sorted(positions, key=lambda p: p.market_value, reverse=True)[:12]

    all_items: list[dict[str, Any]] = []

    # Fetch per-holding news in parallel
    def _fetch_for_holding(pos: PositionMirror) -> list[dict[str, Any]]:
        try:
            items = fetch_all_sources(
                symbol=pos.normalized_symbol,
                name=pos.name,
                kind=pos.kind,
                isin=pos.isin,
                scrip_code=pos.symbol,
                amfi=pos.amfi,
                max_per_source=per_holding_limit,
            )
            total_value = sum(p.market_value for p in positions if p.market_value > 0)
            weight_pct = (pos.market_value / total_value * 100) if total_value else 0.0
            for item in items:
                item["related_holding"] = {
                    "symbol": pos.exchange_symbol,
                    "name": pos.name,
                    "kind": pos.kind,
                    "weight_pct": round(weight_pct, 2),
                }
            return items
        except Exception as e:
            logger.warning("News fetch failed for %s: %s", pos.symbol, e)
            return []

    with ThreadPoolExecutor(max_workers=min(len(top), 8)) as executor:
        futures = {executor.submit(_fetch_for_holding, pos): pos for pos in top}
        for future in as_completed(futures):
            try:
                items = future.result()
                all_items.extend(items)
            except Exception as e:
                logger.warning("News future failed: %s", e)

    # Add market context (already resilient)
    try:
        all_items.extend(fetch_market_context(max_results=6))
    except Exception as e:
        logger.warning("Market context news failed: %s", e)

    # ── Pipeline: filter, score, dedupe, sort ──────────────────────────────
    filtered: list[dict[str, Any]] = []
    for item in all_items:
        url = item.get("url", "")
        if not url:
            continue

        # Allow-list filter
        if not _is_verified_domain(url):
            continue

        # Age filter: drop items older than 7 days
        pub_dt = parse_published_at(item)
        if pub_dt:
            now = datetime.now(timezone.utc)
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            if (now - pub_dt).days > 7:
                continue

        filtered.append(item)

    # Score
    for item in filtered:
        weight_pct = item.get("related_holding", {}).get("weight_pct", 0.0)
        item["score"] = score_item(item, holding_weight_pct=weight_pct)
        item["category"] = tag_category(item)

    # Drop low score
    filtered = [item for item in filtered if item.get("score", 0) >= 0.5]

    # Deduplicate
    filtered = deduplicate(filtered)

    # Sort by score desc
    filtered.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Take top N
    results = filtered[:limit]

    # Enrich with frontend-friendly fields
    final_items = []
    for item in results:
        domain = item.get("source", "")
        tier = 3
        for d, t in VERIFIED_DOMAINS.items():
            if d in domain.lower() or domain.lower() in d:
                tier = t
                break
        pub_dt = parse_published_at(item)
        final_items.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "source_host": domain,
            "source_tier": tier,
            "verified": tier <= 1,
            "published_at": item.get("published", ""),
            "age_label": _age_label(pub_dt),
            "freshness": _freshness_label(pub_dt),
            "snippet": item.get("snippet", ""),
            "category": item.get("category", "general"),
            "score": item.get("score", 0.0),
            "related_holding": item.get("related_holding"),
            "tags": [item.get("category", "general"), _freshness_label(pub_dt)],
            "image": (
                item.get("image")
                or item.get("image_url")
                or item.get("thumbnail")
                or item.get("urlToImage")
                or item.get("banner")
                or item.get("og_image")
                or ""
            ),
            "image_url": (
                item.get("image")
                or item.get("image_url")
                or item.get("thumbnail")
                or item.get("urlToImage")
                or item.get("banner")
                or item.get("og_image")
                or ""
            ),
        })

    cache_set(cache_key, final_items, source="combined")
    return final_items

"""Google Search Console helpers for sitemap submission and performance reads."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("finagent.seo.google_search_console")

_STATUS_LOCK = threading.Lock()
_STATUS_CACHE: dict[str, Any] = {"expires_at": datetime.fromtimestamp(0, tz=timezone.utc), "payload": None}
_SCOPES = ("https://www.googleapis.com/auth/webmasters",)


def _bool_env(name: str, default: bool = False) -> bool:
    value = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _site_url() -> str:
    return str(os.getenv("GOOGLE_SEARCH_CONSOLE_SITE_URL") or "").strip()


def _sitemap_url() -> str:
    configured = str(os.getenv("GOOGLE_SEARCH_CONSOLE_SITEMAP_URL") or "").strip()
    if configured:
        return configured
    base = str(os.getenv("PROSPEKTLAB_SITE_URL") or "https://prospektlab.com").rstrip("/")
    return f"{base}/sitemap.xml"


def _service_account_file() -> str:
    return str(
        os.getenv("GOOGLE_SEARCH_CONSOLE_SERVICE_ACCOUNT_FILE")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        or ""
    ).strip()


def _service_account_info() -> dict[str, Any] | None:
    raw = str(os.getenv("GOOGLE_SEARCH_CONSOLE_SERVICE_ACCOUNT_JSON") or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("GOOGLE_SEARCH_CONSOLE_SERVICE_ACCOUNT_JSON is not valid JSON")
        return None


def _configured() -> bool:
    return bool(_site_url()) and bool(_service_account_file() or _service_account_info())


def _build_service() -> Any:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    info = _service_account_info()
    if info:
        credentials = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
    else:
        credentials = service_account.Credentials.from_service_account_file(_service_account_file(), scopes=_SCOPES)
    return build("searchconsole", "v1", credentials=credentials, cache_discovery=False)


def submit_sitemap() -> dict[str, Any]:
    status = {
        "enabled": _bool_env("GOOGLE_SEARCH_CONSOLE_ENABLED", default=False),
        "configured": _configured(),
        "site_url": _site_url(),
        "sitemap_url": _sitemap_url(),
        "submitted": False,
        "error": "",
    }
    if not status["enabled"] or not status["configured"]:
        return status
    try:
        service = _build_service()
        service.sitemaps().submit(siteUrl=_site_url(), feedpath=_sitemap_url()).execute()
        status["submitted"] = True
        return status
    except Exception as exc:
        logger.warning("Google Search Console sitemap submission failed: %s", exc)
        status["error"] = str(exc)[:240]
        return status


def _search_analytics_query(service: Any, *, dimensions: list[str], row_limit: int, start_date: str, end_date: str) -> list[dict[str, Any]]:
    response = (
        service.searchanalytics()
        .query(
            siteUrl=_site_url(),
            body={
                "startDate": start_date,
                "endDate": end_date,
                "dimensions": dimensions,
                "rowLimit": row_limit,
            },
        )
        .execute()
    )
    return list(response.get("rows") or [])


def get_search_console_status(days: int = 28) -> dict[str, Any]:
    enabled = _bool_env("GOOGLE_SEARCH_CONSOLE_ENABLED", default=False)
    configured = _configured()
    now = datetime.now(timezone.utc)

    with _STATUS_LOCK:
        cached = _STATUS_CACHE.get("payload")
        expires_at = _STATUS_CACHE.get("expires_at")
        if cached and isinstance(expires_at, datetime) and expires_at > now:
            return dict(cached)

    payload = {
        "enabled": enabled,
        "configured": configured,
        "site_url": _site_url(),
        "sitemap_url": _sitemap_url(),
        "error": "",
        "top_pages": [],
        "top_queries": [],
        "generated_at": now.replace(microsecond=0).isoformat(),
    }
    if not enabled or not configured:
        with _STATUS_LOCK:
            _STATUS_CACHE["payload"] = dict(payload)
            _STATUS_CACHE["expires_at"] = now + timedelta(minutes=10)
        return payload

    try:
        service = _build_service()
        end_date = date.today() - timedelta(days=2)
        start_date = end_date - timedelta(days=max(1, days - 1))
        page_rows = _search_analytics_query(
            service,
            dimensions=["page"],
            row_limit=5,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        query_rows = _search_analytics_query(
            service,
            dimensions=["query"],
            row_limit=5,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        payload["top_pages"] = [
            {
                "page": str((row.get("keys") or [""])[0]),
                "clicks": int(row.get("clicks") or 0),
                "impressions": int(row.get("impressions") or 0),
                "ctr": float(row.get("ctr") or 0.0),
                "position": float(row.get("position") or 0.0),
            }
            for row in page_rows
        ]
        payload["top_queries"] = [
            {
                "query": str((row.get("keys") or [""])[0]),
                "clicks": int(row.get("clicks") or 0),
                "impressions": int(row.get("impressions") or 0),
                "ctr": float(row.get("ctr") or 0.0),
                "position": float(row.get("position") or 0.0),
            }
            for row in query_rows
        ]
    except Exception as exc:
        logger.warning("Google Search Console status fetch failed: %s", exc)
        payload["error"] = str(exc)[:240]

    with _STATUS_LOCK:
        _STATUS_CACHE["payload"] = dict(payload)
        _STATUS_CACHE["expires_at"] = now + timedelta(minutes=10)
    return payload

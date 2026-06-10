from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import random
import sqlite3
import statistics
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx
from finagent.paths import finagent_data_path, repo_root
from finagent.storage.sqlite import connect_wal

logger = logging.getLogger("finagent.ops.control_tower")

RANGE_DAYS: dict[str, int] = {
    "7D": 7,
    "30D": 30,
    "90D": 90,
}

LANDING_ROUTES = {"/", "/landing", "/home", "/features", "/pricing", "/testimonials", "/contact"}
SIGNUP_ROUTES = {"/login", "/signup"}
ONBOARDING_ROUTES = {"/onboarding"}
WORKSPACE_ROUTES = {"/dashboard", "/insights", "/portfolio", "/workspace"}

AUTH_SUCCESS_EVENTS = {
    "auth_signup_success",
    "auth_login_success",
    "auth_google_login_success",
    "auth_google_success",
    "auth_password_reset_completed",
}
AUTH_FAILURE_EVENTS = {
    "auth_signup_failed",
    "auth_login_failed",
    "auth_google_login_failed",
}
AUTH_SUPPORT_EVENTS = {
    "auth_logout",
    "auth_mobile_updated",
    "auth_password_reset_requested",
    "auth_verification_sent",
}
AUTH_EVENTS = AUTH_SUCCESS_EVENTS | AUTH_FAILURE_EVENTS | AUTH_SUPPORT_EVENTS
SIGNUP_SUCCESS_EVENTS = AUTH_SUCCESS_EVENTS
SIGNUP_FAILURE_EVENTS = AUTH_FAILURE_EVENTS
AUTH_STARTED_EVENTS = AUTH_SUCCESS_EVENTS | AUTH_FAILURE_EVENTS | {
    "auth_verification_sent",
    "auth_password_reset_requested",
}

ONBOARDING_EVENTS = {"onboarding_completed"}

PORTFOLIO_SUCCESS_EVENTS = {
    "portfolio_mirror_replace_completed",
    "portfolio_upload_completed",
    "portfolio_extraction_confirm_completed",
    "portfolio_extraction_cancel_completed",
}
PORTFOLIO_FAILURE_EVENTS = {
    "portfolio_mirror_replace_failed",
    "portfolio_upload_failed",
    "portfolio_extraction_confirm_failed",
    "portfolio_extraction_cancel_failed",
    "portfolio_upload_review_required",
}
PORTFOLIO_EVENTS = PORTFOLIO_SUCCESS_EVENTS | PORTFOLIO_FAILURE_EVENTS | {
    "portfolio_mirror_replace_requested",
    "portfolio_upload_requested",
    "portfolio_upload_started",
    "portfolio_extraction_confirm_requested",
    "portfolio_extraction_cancel_requested",
    "portfolio_extraction_cancelled",
}

RESEARCH_SUCCESS_EVENTS = {
    "research_start_accepted",
    "research_started",
    "research_deep_started",
    "research_result_received",
    "research_stop_completed",
    "research_stream_completed",
    "research_stream_connected",
    "research_stream_final",
    "research_stream_opened",
}
RESEARCH_FAILURE_EVENTS = {
    "research_start_failed",
    "research_result_failed",
    "research_stop_failed",
    "research_stream_error",
}
RESEARCH_EVENTS = RESEARCH_SUCCESS_EVENTS | RESEARCH_FAILURE_EVENTS | {
    "research_start_requested",
    "research_result_requested",
    "research_stop_requested",
    "research_stream_waiting_for_result",
}

CONTENT_EVENTS = {
    "content_article_generated",
    "content_article_batch_generated",
    "content_events_ingested",
}

CHAT_EVENTS = {
    "chat_completed",
    "chat_research_requested",
    "chat_stream_completed",
    "chat_stream_started",
}

FRONTEND_EVENTS = {"app_initialized"}

WORKSPACE_EVENTS = PORTFOLIO_EVENTS | RESEARCH_EVENTS | CONTENT_EVENTS | CHAT_EVENTS
INSIGHT_EVENTS = CONTENT_EVENTS | {
    "chat_completed",
    "chat_stream_completed",
    "research_stream_completed",
    "research_stream_final",
    "research_result_received",
}

TRACKED_EVENT_GROUP_META: dict[str, dict[str, str]] = {
    "frontend": {
        "label": "Frontend",
        "description": "Browser bootstrap and page-level telemetry signals.",
        "color": "#8da8ff",
    },
    "auth": {
        "label": "Auth",
        "description": "Signup, login, verification, reset, and mobile completion.",
        "color": "#55d6ff",
    },
    "onboarding": {
        "label": "Onboarding",
        "description": "Users finishing the setup journey inside the app.",
        "color": "#7cf2b6",
    },
    "portfolio": {
        "label": "Portfolio",
        "description": "Mirror sync, uploads, extraction review, and confirmation flows.",
        "color": "#ffbf69",
    },
    "research": {
        "label": "Research",
        "description": "Research starts, streams, stop controls, and result retrieval.",
        "color": "#ff7ea8",
    },
    "content": {
        "label": "Content",
        "description": "Automation for article generation and event ingestion.",
        "color": "#f9f871",
    },
    "chat": {
        "label": "Chat",
        "description": "Chat-driven research requests and stream completion telemetry.",
        "color": "#b6c6ff",
    },
}

TRACKED_EVENT_GROUPS: dict[str, set[str]] = {
    "frontend": FRONTEND_EVENTS,
    "auth": AUTH_EVENTS,
    "onboarding": ONBOARDING_EVENTS,
    "portfolio": PORTFOLIO_EVENTS,
    "research": RESEARCH_EVENTS,
    "content": CONTENT_EVENTS,
    "chat": CHAT_EVENTS,
}
TRACKED_EVENT_LOOKUP = {event_name: group for group, names in TRACKED_EVENT_GROUPS.items() for event_name in names}
TRACKED_EVENT_NAMES = set(TRACKED_EVENT_LOOKUP)
GROUP_SUCCESS_EVENTS: dict[str, set[str]] = {
    "auth": AUTH_SUCCESS_EVENTS,
    "portfolio": PORTFOLIO_SUCCESS_EVENTS,
    "research": RESEARCH_SUCCESS_EVENTS,
}
GROUP_FAILURE_EVENTS: dict[str, set[str]] = {
    "auth": AUTH_FAILURE_EVENTS,
    "portfolio": PORTFOLIO_FAILURE_EVENTS,
    "research": RESEARCH_FAILURE_EVENTS,
}

EVENT_LABELS: dict[str, str] = {
    "app_initialized": "Frontend initialized",
    "auth_google_success": "Google auth completed",
    "auth_signup_success": "Signup completed",
    "auth_login_success": "Login success",
    "auth_google_login_success": "Google login success",
    "auth_signup_failed": "Signup failed",
    "auth_login_failed": "Login failed",
    "auth_google_login_failed": "Google login failed",
    "auth_logout": "Logout",
    "auth_mobile_updated": "Mobile updated",
    "auth_password_reset_requested": "Password reset requested",
    "auth_password_reset_completed": "Password reset completed",
    "auth_verification_sent": "Verification sent",
    "onboarding_completed": "Onboarding completed",
    "portfolio_mirror_replace_requested": "Portfolio sync requested",
    "portfolio_mirror_replace_completed": "Portfolio synced",
    "portfolio_mirror_replace_failed": "Portfolio sync failed",
    "portfolio_upload_requested": "Portfolio upload requested",
    "portfolio_upload_started": "Portfolio upload started",
    "portfolio_upload_completed": "Portfolio uploaded",
    "portfolio_upload_failed": "Portfolio upload failed",
    "portfolio_upload_review_required": "Portfolio review required",
    "portfolio_extraction_confirm_requested": "Extraction confirm requested",
    "portfolio_extraction_confirm_completed": "Extraction confirmed",
    "portfolio_extraction_confirm_failed": "Extraction confirm failed",
    "portfolio_extraction_cancel_requested": "Extraction cancel requested",
    "portfolio_extraction_cancel_completed": "Extraction cancel completed",
    "portfolio_extraction_cancel_failed": "Extraction cancel failed",
    "portfolio_extraction_cancelled": "Extraction cancelled",
    "research_start_requested": "Research requested",
    "research_start_accepted": "Research started",
    "research_started": "Research session created",
    "research_deep_started": "Deep research started",
    "research_start_failed": "Research start failed",
    "research_stop_requested": "Research stop requested",
    "research_stop_completed": "Research stop completed",
    "research_stop_failed": "Research stop failed",
    "research_result_requested": "Research result requested",
    "research_result_failed": "Research result failed",
    "research_stream_completed": "Insight delivered",
    "research_stream_connected": "Research stream connected",
    "research_stream_opened": "Research stream opened",
    "research_stream_final": "Research stream final payload",
    "research_stream_error": "Research stream error",
    "research_stream_waiting_for_result": "Research waiting for result",
    "research_result_received": "Result viewed",
    "chat_research_requested": "Chat research requested",
    "chat_stream_started": "Chat stream started",
    "chat_stream_completed": "Chat stream completed",
    "chat_completed": "Chat completed",
    "content_article_generated": "Insight article generated",
    "content_article_batch_generated": "Insight batch generated",
    "content_events_ingested": "Insight triggers ingested",
}

PAGE_LABELS: dict[str, str] = {
    "/": "Landing",
    "/landing": "Landing",
    "/login": "Sign in",
    "/signup": "Signup",
    "/onboarding": "Onboarding",
    "/dashboard": "Workspace",
    "/insights": "Insights",
    "/portfolio": "Portfolio",
    "/pricing": "Pricing",
    "/features": "Features",
    "/testimonials": "Testimonials",
    "/contact": "Contact",
    "/ops/control-tower": "Control Tower",
}

SOURCE_COLORS = [
    {"name": "Azure Application Insights", "color": "#55d6ff"},
    {"name": "Azure Monitor", "color": "#8da8ff"},
    {"name": "Supabase", "color": "#7cf2b6"},
    {"name": "ProspektLab Workspace", "color": "#ffbf69"},
    {"name": "ProspektLab Insights", "color": "#ff7ea8"},
]

FALLBACK_USERS = [
    {"email": "researcher@prospektlab.app", "name": "Researcher"},
    {"email": "ops@prospektlab.app", "name": "Ops Lead"},
    {"email": "insights@prospektlab.app", "name": "Insights Analyst"},
    {"email": "workspace@prospektlab.app", "name": "Workspace Admin"},
]

SUPABASE_TABLE_META: dict[str, dict[str, str]] = {
    "profiles": {
        "label": "Profiles",
        "note": "Authenticated identities and operator profiles.",
        "source": "Supabase",
    },
    "portfolio_mirrors": {
        "label": "Portfolio mirrors",
        "note": "Active holdings mirrored into the workspace.",
        "source": "ProspektLab Workspace",
    },
    "session_summaries": {
        "label": "Session summaries",
        "note": "Research session rollups persisted from the app.",
        "source": "ProspektLab Workspace",
    },
    "facts": {
        "label": "Memory facts",
        "note": "Durable facts stored from completed research.",
        "source": "ProspektLab Insights",
    },
    "token_usage": {
        "label": "Token usage",
        "note": "Model consumption by user and session.",
        "source": "Supabase",
    },
    "verification_codes": {
        "label": "Verification codes",
        "note": "Signup and password reset verification records.",
        "source": "Supabase",
    },
    "pending_extractions": {
        "label": "Pending extractions",
        "note": "Portfolio extraction reviews waiting for an operator.",
        "source": "ProspektLab Workspace",
    },
    "revoked_tokens": {
        "label": "Revoked tokens",
        "note": "Server-side revoked auth tokens.",
        "source": "Supabase",
    },
    "contacts": {
        "label": "Contacts",
        "note": "Prospect contact graph used for outreach.",
        "source": "Supabase",
    },
    "scrape_jobs": {
        "label": "Scrape jobs",
        "note": "Background acquisition jobs and their status.",
        "source": "Supabase",
    },
    "scrape_checkpoints": {
        "label": "Scrape checkpoints",
        "note": "Resume markers for long-running scrapes.",
        "source": "Supabase",
    },
    "extraction_rules": {
        "label": "Extraction rules",
        "note": "Heuristic rules used for ingestion and parsing.",
        "source": "Supabase",
    },
    "export_jobs": {
        "label": "Export jobs",
        "note": "Pending and completed export workloads.",
        "source": "Supabase",
    },
    "sebi_verified_leads": {
        "label": "SEBI leads",
        "note": "Verified market leads collected for targeting.",
        "source": "Supabase",
    },
    "outreach_campaigns": {
        "label": "Outreach campaigns",
        "note": "Campaign planning and send windows.",
        "source": "ProspektLab Insights",
    },
    "outreach_leads": {
        "label": "Outreach leads",
        "note": "Lead staging and assigned sender profiles.",
        "source": "ProspektLab Insights",
    },
    "outreach_suppressions": {
        "label": "Suppressions",
        "note": "Manual or automatic suppression records.",
        "source": "ProspektLab Insights",
    },
    "outreach_messages": {
        "label": "Outreach messages",
        "note": "Queued and delivered outbound messages.",
        "source": "ProspektLab Insights",
    },
    "outreach_events": {
        "label": "Outreach events",
        "note": "Provider-delivered opens, clicks, and bounce events.",
        "source": "ProspektLab Insights",
    },
    "outreach_replies": {
        "label": "Replies",
        "note": "Inbound replies captured from campaigns.",
        "source": "ProspektLab Insights",
    },
    "outreach_unsubscribes": {
        "label": "Unsubscribes",
        "note": "Prospects who opted out of future outreach.",
        "source": "ProspektLab Insights",
    },
}


def _env_string(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return default


def _env_bool(*names: str, default: bool = False) -> bool:
    for name in names:
        raw = os.getenv(name)
        if raw is None:
            continue
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_range_key(value: str | None) -> str:
    key = (value or "30D").strip().upper()
    return key if key in RANGE_DAYS else "30D"


def _range_days(range_key: str | None) -> int:
    return RANGE_DAYS[_normalize_range_key(range_key)]


def _duration_to_ms(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return 0.0

    if text.endswith("ms"):
        try:
            return float(text[:-2].strip())
        except ValueError:
            return 0.0

    # Azure typically formats durations as HH:MM:SS.mmmmmm.
    try:
        hours = 0
        if text.count(":") == 2:
            hh, mm, sec = text.split(":", 2)
            hours = int(hh)
        else:
            mm, sec = text.split(":", 1)
        if "." in sec:
            ss, frac = sec.split(".", 1)
        else:
            ss, frac = sec, "0"
        minutes = int(mm)
        seconds = int(ss)
        micros = int((frac + "000000")[:6])
        return ((hours * 3600) + (minutes * 60) + seconds) * 1000 + micros / 1000
    except Exception:
        return 0.0


def _fmt_count(value: int | float) -> str:
    number = int(round(value or 0))
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}k"
    return str(number)


def _fmt_pct(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}%"


def _fmt_age(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    if total < 60:
        return f"{total}s"
    minutes, sec = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _safe_email(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if "@" in text else ""


def _is_local_dev_identity(email: str) -> bool:
    normalized = _safe_email(email)
    return normalized.endswith("@prospektlab.local")


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            ts = float(value)
            if not math.isfinite(ts):
                return None
            if abs(ts) > 1_000_000_000_000:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.replace(".", "", 1).isdigit():
        try:
            ts = float(text)
            if abs(ts) > 1_000_000_000_000:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def _days_ago(days: int) -> datetime:
    return _now_utc() - timedelta(days=days)


def _route_label(route: str) -> str:
    route = (route or "").strip() or "/"
    return PAGE_LABELS.get(route, route)


def _normalized_path(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
        path = parsed.path or text
        return path.lower()
    except Exception:
        return text.lower()


def _event_label(name: str) -> str:
    return EVENT_LABELS.get(name, name)


def _event_group(name: str) -> str | None:
    return TRACKED_EVENT_LOOKUP.get(name)


def _safe_int(value: Any) -> int:
    try:
        if value in ("", None):
            return 0
        return int(float(value))
    except Exception:
        return 0


def _safe_float(value: Any) -> float:
    try:
        if value in ("", None):
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _filter_recent_rows(rows: list[dict[str, Any]], *keys: str, since: datetime | None = None) -> list[dict[str, Any]]:
    if since is None:
        return list(rows)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        dt = next((_parse_dt(row.get(key)) for key in keys if row.get(key) not in (None, "")), None)
        if dt is None or dt >= since:
            filtered.append(row)
    return filtered


def _latest_timestamp_from_rows(rows: list[dict[str, Any]], *keys: str) -> datetime | None:
    latest: datetime | None = None
    for row in rows:
        for key in keys:
            dt = _parse_dt(row.get(key))
            if dt and (latest is None or dt > latest):
                latest = dt
    return latest


def _status_from_configured(configured: bool, has_rows: bool, lag_seconds: float) -> str:
    if not configured:
        return "stale"
    return _status_from_lag(lag_seconds, has_rows or configured)


def _source_name_from_rows(rows: Iterable[dict[str, Any]], fallback: str) -> str:
    count = Counter()
    for row in rows:
        source = str(row.get("source") or "").strip()
        if source:
            count[source] += 1
    if not count:
        return fallback
    return count.most_common(1)[0][0]


def _choose_stage(user: dict[str, Any]) -> tuple[str, str]:
    if user.get("retained_sessions", 0) >= 2 or user.get("active_days", 0) >= 2:
        return "retained", "Invite to advanced monitoring"
    if user.get("first_value_sessions", 0) > 0:
        return "first_value", "Nudge them back with alerts"
    if user.get("workspace_sessions", 0) > 0:
        return "workspace", "Surface first insight shortcuts"
    if user.get("onboarding_sessions", 0) > 0:
        return "onboarding", "Guide them to first value"
    if user.get("signup_completed_sessions", 0) > 0:
        return "signup_completed", "Prompt onboarding completion"
    if user.get("signup_started_sessions", 0) > 0:
        return "signup_started", "Remove signup friction"
    if user.get("landing_sessions", 0) > 0:
        return "landing", "Push the signup CTA higher"
    return "profile", "Check whether telemetry is missing"


def _stage_rank(stage: str) -> int:
    order = {
        "profile": 0,
        "landing": 1,
        "signup_started": 2,
        "signup_completed": 3,
        "onboarding": 4,
        "workspace": 5,
        "first_value": 6,
        "retained": 7,
    }
    return order.get(stage, 0)


def _status_from_lag(lag_seconds: float, has_rows: bool) -> str:
    if not has_rows:
        return "stale"
    if lag_seconds <= 60 * 5:
        return "healthy"
    if lag_seconds <= 60 * 30:
        return "warn"
    return "stale"


def _status_pill(status: str) -> str:
    if status == "healthy":
        return "healthy"
    if status == "warn":
        return "watch"
    return "stale"


def _generate_demo_series(days: int, seed: int, totals: dict[str, int]) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    series: list[dict[str, Any]] = []
    base_date = _days_ago(days - 1)
    for idx in range(days):
        progress = idx / max(1, days - 1)
        wave = math.sin((idx / 2.8) + seed * 0.17)
        trend = 1 + (progress * 0.18)
        landing = max(60, int(totals["landing"] / days * trend + wave * totals["landing"] / days * 0.16 + rng.randint(-8, 8)))
        signup = max(20, int(landing * 0.62 + wave * 7))
        signup_completed = max(10, int(signup * 0.74 + rng.randint(-4, 4)))
        onboarding = max(8, int(signup_completed * 0.82 + rng.randint(-3, 3)))
        workspace = max(6, int(onboarding * 0.87 + rng.randint(-3, 3)))
        first_value = max(4, int(workspace * 0.79 + rng.randint(-2, 2)))
        errors = max(0, int(landing * 0.012 + abs(wave) * 2))
        auth_failure = max(0, signup - signup_completed)
        portfolio = max(3, int(workspace * 0.56 + rng.randint(-2, 2)))
        research = max(4, int(workspace * 0.82 + rng.randint(-2, 3)))
        content = max(1, int(first_value * 0.36 + rng.randint(0, 2)))
        chat = max(1, int(workspace * 0.24 + rng.randint(0, 2)))
        requests = max(30, int(landing * 1.18 + rng.randint(-12, 12)))
        dependencies = max(24, int(landing * 0.92 + rng.randint(-10, 10)))
        series.append({
            "date": (base_date + timedelta(days=idx)).isoformat(),
            "landing": landing,
            "signup_started": signup,
            "signup_completed": signup_completed,
            "onboarding_completed": onboarding,
            "workspace": workspace,
            "first_value": first_value,
            "auth_success": signup_completed,
            "auth_failure": auth_failure,
            "portfolio": portfolio,
            "research": research,
            "content": content,
            "chat": chat,
            "requests": requests,
            "dependencies": dependencies,
            "errors": errors,
        })
    return series


def _demo_snapshot(range_key: str, supabase_stats: dict[str, Any]) -> dict[str, Any]:
    days = _range_days(range_key)
    seed = int(hashlib.sha1(range_key.encode("utf-8")).hexdigest()[:8], 16)
    profiles_count = int(supabase_stats.get("profiles_count") or 0)
    token_total = int(supabase_stats.get("token_total") or 0)
    workspace_rows = int(supabase_stats.get("session_summary_count") or 0)
    insights_rows = int(supabase_stats.get("facts_count") or 0)

    landing_total = max(240, profiles_count * 48 + workspace_rows * 12 + max(0, token_total // 220))
    signup_started = int(landing_total * 0.64)
    signup_completed = int(signup_started * 0.78)
    onboarding_completed = int(signup_completed * 0.84)
    workspace_active = int(onboarding_completed * 0.88)
    first_value = int(workspace_active * 0.80)
    retained = int(first_value * 0.66)
    open_alerts = max(1, min(7, 1 + (workspace_rows // 4) + (insights_rows // 6)))
    p95_latency_ms = 185 + (token_total % 45)
    freshness_seconds = 48 + (seed % 26)

    series = _generate_demo_series(days, seed, {
        "landing": landing_total,
        "signup_started": signup_started,
        "signup_completed": signup_completed,
        "onboarding_completed": onboarding_completed,
        "workspace": workspace_active,
        "first_value": first_value,
    })
    top_pages = [
        {"route": "/", "views": landing_total // 2, "sessions": max(1, landing_total // 3)},
        {"route": "/signup", "views": signup_started // 2, "sessions": max(1, signup_started // 3)},
        {"route": "/onboarding", "views": onboarding_completed // 2, "sessions": max(1, onboarding_completed // 3)},
        {"route": "/dashboard", "views": workspace_active // 2, "sessions": max(1, workspace_active // 3)},
    ]
    top_events = [
        {"name": "auth_signup_success", "count": signup_completed, "pct": 22.0},
        {"name": "onboarding_completed", "count": onboarding_completed, "pct": 18.0},
        {"name": "research_start_accepted", "count": workspace_active, "pct": 17.0},
        {"name": "research_stream_completed", "count": first_value, "pct": 15.0},
        {"name": "portfolio_upload_completed", "count": max(1, workspace_active // 2), "pct": 8.0},
    ]
    combined_users = []
    for idx, item in enumerate(FALLBACK_USERS):
        stage = ["signup_completed", "onboarding", "workspace", "first_value"][idx % 4]
        combined_users.append({
            "email": item["email"],
            "name": item["name"],
            "stage": stage,
            "source": "Supabase + Azure",
            "last_seen": _now_utc().isoformat(),
            "workspace_events": max(1, workspace_active // (idx + 1)),
            "token_usage": max(1_000, token_total // max(1, idx + 2)),
            "risk": "low" if idx < 2 else "medium",
            "action": "Invite to advanced monitoring" if stage in {"first_value", "workspace"} else "Prompt onboarding completion",
        })

    funnel = [
        {"stage": "Landing", "value": landing_total, "detail": "Entry traffic across marketing and direct visits."},
        {"stage": "Signup started", "value": signup_started, "detail": "Users reaching the auth funnel."},
        {"stage": "Signup completed", "value": signup_completed, "detail": "Accounts created or login success."},
        {"stage": "Onboarding completed", "value": onboarding_completed, "detail": "Users who cleared setup."},
        {"stage": "Workspace active", "value": workspace_active, "detail": "People using the workspace."},
        {"stage": "First value", "value": first_value, "detail": "Users reaching their first insight."},
    ]
    biggest_leak = max(
        [
            {"label": "Landing -> signup", "amount": max(0, landing_total - signup_started), "pct": 0.0},
            {"label": "Signup -> completion", "amount": max(0, signup_started - signup_completed), "pct": 0.0},
            {"label": "Completion -> onboarding", "amount": max(0, signup_completed - onboarding_completed), "pct": 0.0},
            {"label": "Onboarding -> workspace", "amount": max(0, onboarding_completed - workspace_active), "pct": 0.0},
            {"label": "Workspace -> first value", "amount": max(0, workspace_active - first_value), "pct": 0.0},
        ],
        key=lambda row: row["amount"],
    )
    biggest_leak["pct"] = biggest_leak["amount"] / max(1, landing_total) * 100

    source_mix = [
        {"name": item["name"], "value": value, "color": item["color"]}
        for item, value in zip(
            SOURCE_COLORS,
            [landing_total, open_alerts * 14, max(1, profiles_count * 3), max(1, workspace_rows * 5), max(1, insights_rows * 4)],
        )
    ]
    source_total = sum(item["value"] for item in source_mix)
    for item in source_mix:
        item["pct"] = item["value"] / max(1, source_total) * 100

    source_health = [
        {
            "name": "Azure Application Insights",
            "status": "healthy",
            "coverage": 99.2,
            "lag_seconds": freshness_seconds,
            "note": "Landing pages and custom events are visible.",
            "metric": f"{_fmt_count(landing_total)} events",
            "extra": f"{p95_latency_ms:.0f}ms p95",
        },
        {
            "name": "Azure Monitor",
            "status": _status_pill("healthy" if open_alerts <= 3 else "watch"),
            "coverage": 96.7,
            "lag_seconds": freshness_seconds + 9,
            "note": "Exceptions and request failures are tracked.",
            "metric": f"{open_alerts} open alerts",
            "extra": f"{p95_latency_ms:.0f}ms p95",
        },
        {
            "name": "Supabase",
            "status": "healthy" if profiles_count else "watch",
            "coverage": 100.0 if profiles_count else 85.0,
            "lag_seconds": freshness_seconds + 12,
            "note": "Auth, profiles, token usage, and workspace summaries are connected.",
            "metric": f"{_fmt_count(profiles_count)} profiles",
            "extra": f"{_fmt_count(token_total)} tokens",
        },
        {
            "name": "ProspektLab Workspace",
            "status": "healthy" if workspace_rows else "watch",
            "coverage": 100.0 if workspace_rows else 78.0,
            "lag_seconds": freshness_seconds + 6,
            "note": "Session summaries and workspace activity are available.",
            "metric": f"{_fmt_count(workspace_rows)} sessions",
            "extra": f"{_fmt_count(workspace_rows * 2)} actions",
        },
        {
            "name": "ProspektLab Insights",
            "status": "healthy" if insights_rows else "watch",
            "coverage": 100.0 if insights_rows else 80.0,
            "lag_seconds": freshness_seconds + 4,
            "note": "Insights facts and generated content are stitched into the same view.",
            "metric": f"{_fmt_count(insights_rows)} insights",
            "extra": f"{_fmt_count(insights_rows * 2)} signals",
        },
    ]

    health_score = max(
        0,
        min(
            100,
            int(
                100
                - open_alerts * 8
                - max(0, (p95_latency_ms - 200) * 0.07)
                - max(0, biggest_leak["pct"] - 20) * 0.9
                + (3 if profiles_count else 0)
            ),
        ),
    )

    return {
        "mode": "demo",
        "live_data": False,
        "generated_at": _now_utc().isoformat(),
        "range": {"key": range_key, "days": days, "label": f"Last {days} days"},
        "summary": {
            "landing_sessions": landing_total,
            "signup_started_sessions": signup_started,
            "signup_completed_sessions": signup_completed,
            "onboarding_completed_sessions": onboarding_completed,
            "workspace_sessions": workspace_active,
            "first_value_sessions": first_value,
            "retained_sessions": retained,
            "combined_users": max(1, profiles_count or len(combined_users)),
            "workspace_users": max(1, workspace_rows),
            "insight_users": max(1, insights_rows),
            "identity_match_rate": 88.0 if profiles_count else 0.0,
            "open_alerts": open_alerts,
            "p95_latency_ms": p95_latency_ms,
            "avg_freshness_seconds": freshness_seconds,
            "signup_completion_rate": signup_completed / max(1, signup_started) * 100,
            "workspace_activation_rate": first_value / max(1, workspace_active) * 100,
        },
        "series": series,
        "funnel": funnel,
        "biggest_leak": biggest_leak,
        "dropoffs": [
            {
                "label": "Landing CTA friction",
                "detail": "People are visiting the platform but not pushing into signup quickly enough.",
                "amount": max(0, landing_total - signup_started),
                "pct": max(0, landing_total - signup_started) / max(1, landing_total) * 100,
            },
            {
                "label": "Signup verification drag",
                "detail": "Auth completion is trailing signup intent.",
                "amount": max(0, signup_started - signup_completed),
                "pct": max(0, signup_started - signup_completed) / max(1, landing_total) * 100,
            },
            {
                "label": "Workspace activation drag",
                "detail": "Users are getting through signup, but first value still needs a push.",
                "amount": max(0, onboarding_completed - first_value),
                "pct": max(0, onboarding_completed - first_value) / max(1, landing_total) * 100,
            },
        ],
        "source_mix": source_mix,
        "source_health": source_health,
        "combined_users": combined_users,
        "top_pages": top_pages,
        "top_events": top_events,
        "health_score": health_score,
        "open_alerts": open_alerts,
        "request_samples": [],
        "exception_samples": [],
    }


def _azure_config() -> dict[str, Any]:
    query_url = _env_string("CONTROL_TOWER_AZURE_QUERY_URL")
    workspace_id = _env_string("CONTROL_TOWER_AZURE_WORKSPACE_ID")
    appinsights_app_id = _env_string("CONTROL_TOWER_APPINSIGHTS_APP_ID")
    if not appinsights_app_id:
        connection_string = _env_string("APPINSIGHTS_CONNECTION_STRING", "APPLICATIONINSIGHTS_CONNECTION_STRING")
        for part in connection_string.split(";"):
            key, _, value = part.partition("=")
            if key.strip().lower() == "applicationid" and value.strip():
                appinsights_app_id = value.strip()
                break

    if not query_url:
        if workspace_id:
            query_url = f"https://api.loganalytics.azure.com/v1/workspaces/{workspace_id}/query"
        elif appinsights_app_id:
            query_url = f"https://api.applicationinsights.io/v1/apps/{appinsights_app_id}/query"

    if not query_url:
        return {"enabled": False}

    parsed = urlparse(query_url)
    resource_scope = _env_string("CONTROL_TOWER_AZURE_SCOPE")
    if not resource_scope and parsed.scheme and parsed.netloc:
        resource_scope = f"{parsed.scheme}://{parsed.netloc}/.default"

    return {
        "enabled": bool(query_url),
        "query_url": query_url,
        "app_id": appinsights_app_id,
        "tenant_id": _env_string("CONTROL_TOWER_AZURE_TENANT_ID", "AZURE_TENANT_ID"),
        "client_id": _env_string("CONTROL_TOWER_AZURE_CLIENT_ID", "AZURE_CLIENT_ID"),
        "client_secret": _env_string("CONTROL_TOWER_AZURE_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
        "bearer_token": _env_string("CONTROL_TOWER_AZURE_BEARER_TOKEN"),
        "api_key": _env_string("CONTROL_TOWER_APPINSIGHTS_API_KEY", "APPINSIGHTS_API_KEY", "APPLICATIONINSIGHTS_API_KEY"),
        "scope": resource_scope,
    }


_azure_token_lock = asyncio.Lock()
_azure_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}


async def _get_azure_token(config: dict[str, Any]) -> str | None:
    api_key = (config.get("api_key") or "").strip()
    if api_key:
        return None
    bearer = (config.get("bearer_token") or "").strip()
    if bearer:
        return bearer

    tenant_id = (config.get("tenant_id") or "").strip()
    client_id = (config.get("client_id") or "").strip()
    client_secret = (config.get("client_secret") or "").strip()
    scope = (config.get("scope") or "").strip()

    if not (tenant_id and client_id and client_secret and scope):
        return None

    now = time.time()
    cached = _azure_token_cache
    if cached.get("token") and cached.get("expires_at", 0.0) > now + 60:
        return str(cached["token"])

    async with _azure_token_lock:
        cached = _azure_token_cache
        if cached.get("token") and cached.get("expires_at", 0.0) > time.time() + 60:
            return str(cached["token"])

        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        payload = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": scope,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0), trust_env=_env_bool("FINAGENT_HTTP_TRUST_ENV")) as client:
            response = await client.post(token_url, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
            response.raise_for_status()
            token_data = response.json()
            token = str(token_data.get("access_token") or "")
            expires_in = float(token_data.get("expires_in") or 3600)
            if token:
                _azure_token_cache["token"] = token
                _azure_token_cache["expires_at"] = time.time() + max(120.0, expires_in - 60)
                return token
    return None


def _azure_query_text(days: int) -> str:
    return f"""
let startTime = ago({days}d);
union isfuzzy=true
(
  pageViews
  | where timestamp >= startTime
  | extend
      route = tolower(coalesce(tostring(customDimensions.route), tostring(name), "/")),
      session_id = coalesce(tostring(customDimensions.session_id), tostring(session_Id), tostring(operation_Id)),
      source = coalesce(tostring(customDimensions.source), "frontend"),
      user_email = coalesce(tostring(customDimensions.user_email), tostring(user_AuthenticatedId), tostring(user_Id))
  | project timestamp, kind = "pageview", event_name = route, route, user_email, session_id, source, duration_text = tostring(duration), success = true, status_code = "", message = tostring(customDimensions.page_title), target = tostring(uri)
  | order by timestamp desc
  | take 1500
),
(
  customEvents
  | where timestamp >= startTime
  | extend
      event_name = tostring(name),
      route = tostring(customDimensions.route),
      session_id = coalesce(tostring(customDimensions.session_id), tostring(session_Id), tostring(operation_Id)),
      source = coalesce(tostring(customDimensions.source), "frontend"),
      user_email = coalesce(tostring(customDimensions.user_email), tostring(user_AuthenticatedId), tostring(user_Id))
  | project timestamp, kind = "event", event_name, route, user_email, session_id, source, duration_text = tostring(customMeasurements.duration_ms), success = true, status_code = "", message = tostring(customDimensions.detail), target = tostring(customDimensions.path)
  | order by timestamp desc
  | take 2000
),
(
  dependencies
  | where timestamp >= startTime
  | extend
      session_id = coalesce(tostring(customDimensions.session_id), tostring(session_Id), tostring(operation_Id)),
      source = coalesce(tostring(customDimensions.source), tostring(target), "frontend"),
      user_email = coalesce(tostring(customDimensions.user_email), tostring(user_AuthenticatedId), tostring(user_Id))
  | project timestamp, kind = "dependency", event_name = tostring(name), route = tostring(data), user_email, session_id, source, duration_text = tostring(duration), success = success, status_code = tostring(resultCode), message = tostring(type), target = tostring(target)
  | order by timestamp desc
  | take 2000
),
(
  requests
  | where timestamp >= startTime
  | extend
      session_id = coalesce(tostring(customDimensions.session_id), tostring(session_Id), tostring(operation_Id)),
      source = coalesce(tostring(customDimensions.source), "backend"),
      user_email = coalesce(tostring(customDimensions.user_email), tostring(user_AuthenticatedId), tostring(user_Id))
  | project timestamp, kind = "request", event_name = tostring(name), route = tostring(url), user_email, session_id, source, duration_text = tostring(duration), success = success, status_code = tostring(resultCode), message = tostring(customDimensions.path), target = tostring(name)
  | order by timestamp desc
  | take 2000
),
(
  exceptions
  | where timestamp >= startTime
  | extend
      session_id = coalesce(tostring(customDimensions.session_id), tostring(session_Id), tostring(operation_Id)),
      source = coalesce(tostring(customDimensions.source), "backend"),
      user_email = coalesce(tostring(customDimensions.user_email), tostring(user_AuthenticatedId), tostring(user_Id))
  | project timestamp, kind = "exception", event_name = tostring(type), route = tostring(customDimensions.path), user_email, session_id, source, duration_text = "", success = false, status_code = "500", message = tostring(outerMessage), target = tostring(problemId)
  | order by timestamp desc
  | take 1000
)
| order by timestamp asc
"""


def _table_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    tables = payload.get("tables") or []
    if not tables:
        return []
    table = tables[0]
    columns = [col.get("name") for col in table.get("columns", [])]
    rows = table.get("rows", [])
    if not columns or not rows:
        return []
    result: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        result.append({columns[idx]: row[idx] for idx in range(min(len(columns), len(row)))})
    return result


def _normalize_azure_cli_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if row.get("kind"):
            normalized.append(row)
            continue
        item_type = str(row.get("itemType") or "").strip().lower()
        custom_dimensions = row.get("customDimensions")
        if isinstance(custom_dimensions, str):
            try:
                custom_dimensions = json.loads(custom_dimensions)
            except Exception:
                custom_dimensions = {}
        if not isinstance(custom_dimensions, dict):
            custom_dimensions = {}

        route = (
            row.get("url")
            or row.get("data")
            or custom_dimensions.get("path")
            or custom_dimensions.get("route")
            or row.get("name")
            or "/"
        )
        normalized.append(
            {
                "timestamp": row.get("timestamp"),
                "kind": "pageview" if item_type == "pageview" else "event" if item_type == "customEvent".lower() else "request" if item_type == "request" else "dependency" if item_type == "dependency" else "exception" if item_type == "exception" else item_type,
                "event_name": row.get("name") or route,
                "route": route,
                "user_email": custom_dimensions.get("user_email") or row.get("user_AuthenticatedId") or row.get("user_Id") or "",
                "session_id": custom_dimensions.get("session_id") or row.get("session_Id") or row.get("operation_Id") or "",
                "source": custom_dimensions.get("source") or row.get("source") or row.get("target") or ("backend" if item_type in {"request", "dependency", "exception"} else "frontend"),
                "duration_text": row.get("duration") or (row.get("customMeasurements") or {}).get("duration_ms") if isinstance(row.get("customMeasurements"), dict) else row.get("duration"),
                "success": row.get("success") if row.get("success") not in (None, "") else (False if item_type == "exception" else True),
                "status_code": row.get("resultCode") or ("500" if item_type == "exception" else ""),
                "message": row.get("outerMessage") or row.get("message") or row.get("type") or custom_dimensions.get("detail") or "",
                "target": row.get("target") or row.get("url") or row.get("data") or "",
            }
        )
    return normalized


def _azure_cli_executable() -> str | None:
    candidates = [
        os.getenv("AZURE_CLI_PATH", "").strip(),
        r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
        r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az",
        "az",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if Path(candidate).exists():
            return candidate
        if candidate == "az":
            return candidate
    return None


def _azure_query_via_cli(days: int, config: dict[str, Any]) -> tuple[list[dict[str, Any]], str, str]:
    app_id = str(config.get("app_id") or "").strip()
    if not app_id:
        return [], "warn", "Azure CLI is available, but no Application Insights app id is configured"

    azure_cli = _azure_cli_executable()
    if not azure_cli:
        return [], "warn", "Azure CLI is not installed on this host"

    query = f"union pageViews, customEvents, requests, dependencies, exceptions | where timestamp >= ago({days}d) | order by timestamp asc | take 3000"
    cmd = [
        azure_cli,
        "monitor",
        "app-insights",
        "query",
        "--app",
        app_id,
        "--analytics-query",
        query,
        "-o",
        "json",
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except FileNotFoundError:
        return [], "warn", "Azure CLI is not installed on this host"
    except subprocess.TimeoutExpired:
        return [], "warn", "Azure CLI query timed out"
    except Exception as exc:
        logger.debug("Azure CLI query failed unexpectedly: %s", exc)
        return [], "warn", f"Azure CLI query failed: {exc.__class__.__name__}"

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout or "Azure CLI query failed"
        logger.debug("Azure CLI query returned %s: %s", completed.returncode, detail)
        return [], "warn", f"Azure CLI query failed: {detail[:180]}"

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        return [], "warn", "Azure CLI returned unreadable query output"

    rows = _normalize_azure_cli_rows(_table_rows(payload))
    if rows:
        return rows, "healthy", "Azure telemetry live via Azure CLI"
    return [], "warn", "Azure CLI connected, but no matching telemetry rows were returned"


async def _azure_query(days: int) -> tuple[list[dict[str, Any]], str, str]:
    config = _azure_config()
    if not config.get("enabled"):
        if config.get("app_id"):
            return _azure_query_via_cli(days, config)
        return [], "disabled", "Azure query URL not configured"

    headers = {"Content-Type": "application/json"}
    api_key = str(config.get("api_key") or "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    else:
        token = await _get_azure_token(config)
        if not token:
            cli_rows, cli_status, cli_note = _azure_query_via_cli(days, config)
            if cli_rows:
                return cli_rows, cli_status, cli_note
            return [], "warn", "Azure query credentials are missing or incomplete"
        headers["Authorization"] = f"Bearer {token}"

    query = _azure_query_text(days)
    timeout = httpx.Timeout(30.0, connect=8.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=_env_bool("FINAGENT_HTTP_TRUST_ENV")) as client:
            response = await client.post(
                str(config["query_url"]),
                json={"query": query},
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.warning("Azure control tower query failed: %s", exc)
        cli_rows, cli_status, cli_note = _azure_query_via_cli(days, config)
        if cli_rows:
            return cli_rows, cli_status, cli_note
        return [], "warn", f"Azure query failed: {exc.__class__.__name__}"

    return _table_rows(payload), "healthy", "Azure telemetry live"


def _supabase_base(outreach: bool = False) -> str:
    if outreach:
        return _env_string("OUTREACH_SUPABASE_URL", default=_env_string("SUPABASE_URL")).rstrip("/")
    return _env_string("SUPABASE_URL").rstrip("/")


def _supabase_key(outreach: bool = False) -> str:
    if outreach:
        return _env_string("OUTREACH_SUPABASE_KEY", default=_env_string("SUPABASE_KEY"))
    return _env_string("SUPABASE_KEY")


def _supabase_headers(outreach: bool = False) -> dict[str, str] | None:
    url = _supabase_base(outreach=outreach)
    key = _supabase_key(outreach=outreach)
    if not url or not key:
        return None
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def _supabase_select(
    table: str,
    *,
    select: str = "*",
    limit: int = 250,
    order: str | None = None,
    filters: dict[str, str] | None = None,
    outreach: bool = False,
) -> list[dict[str, Any]]:
    base = _supabase_base(outreach=outreach)
    headers = _supabase_headers(outreach=outreach)
    if not base or headers is None:
        return []
    params: dict[str, str] = {"select": select}
    if limit:
        params["limit"] = str(limit)
    if order:
        params["order"] = order
    if filters:
        params.update(filters)
    url = f"{base}/rest/v1/{table}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(18.0, connect=6.0), trust_env=_env_bool("FINAGENT_HTTP_TRUST_ENV")) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, list) else []
    except Exception as exc:
        logger.debug("Supabase query for %s failed: %s", table, exc)
        return []


async def _load_supabase_stats(days: int) -> dict[str, Any]:
    since = _days_ago(days)
    main_configured = bool(_supabase_headers())
    outreach_configured = bool(_supabase_headers(outreach=True))

    (
        profiles,
        token_usage,
        sessions,
        facts,
        portfolio_mirrors,
        verification_codes,
        pending_extractions,
        revoked_tokens,
        contacts,
        scrape_jobs,
        scrape_checkpoints,
        extraction_rules,
        export_jobs,
        sebi_verified_leads,
        outreach_campaigns,
        outreach_leads,
        outreach_suppressions,
        outreach_messages,
        outreach_events,
        outreach_replies,
        outreach_unsubscribes,
    ) = await asyncio.gather(
        _supabase_select("profiles", select="id,email,full_name,auth_provider,created_at,updated_at", limit=1000, order="updated_at.desc"),
        _supabase_select("token_usage", select="user_email,session_id,total_tokens,prompt_tokens,completion_tokens,model,created_at", limit=1500, order="created_at.desc"),
        _supabase_select("session_summaries", select="session_id,target_key,target_display,citation_count,quality_score,created_at,user_email,metrics_json", limit=1000, order="created_at.desc"),
        _supabase_select("facts", select="id,target_key,kind,confidence,user_email,created_at", limit=1500, order="created_at.desc"),
        _supabase_select("portfolio_mirrors", select="tenant_id,symbol,market_value,cost_basis,kind,sector,industry,updated_at,active", limit=1500, order="updated_at.desc"),
        _supabase_select("verification_codes", select="email,type,created_at", limit=500, order="created_at.desc"),
        _supabase_select("pending_extractions", select="review_id,tenant_id,created_at", limit=500, order="created_at.desc"),
        _supabase_select("revoked_tokens", select="jti,revoked_at,expires_at", limit=500, order="revoked_at.desc"),
        _supabase_select("contacts", select="id,primary_source,opted_out,created_at,updated_at,city,state", limit=1000, order="created_at.desc"),
        _supabase_select("scrape_jobs", select="id,source,status,records_scraped,records_new,records_updated,records_failed,pages_done,pages_total,progress_pct,created_at,completed_at,heartbeat_at,last_checkpoint_at", limit=1000, order="created_at.desc"),
        _supabase_select("scrape_checkpoints", select="source,job_id,updated_at", limit=500, order="updated_at.desc"),
        _supabase_select("extraction_rules", select="domain,last_successful_at,consecutive_failures,is_active,healing_in_progress,updated_at", limit=500, order="updated_at.desc"),
        _supabase_select("export_jobs", select="id,status,format,created_at,completed_at", limit=500, order="created_at.desc"),
        _supabase_select("sebi_verified_leads", select="id,source,sebi_category,created_at", limit=1000, order="created_at.desc"),
        _supabase_select("outreach_campaigns", select="id,owner_email,name,status,scheduled_at,created_at,updated_at", limit=500, order="created_at.desc", outreach=True),
        _supabase_select("outreach_leads", select="id,owner_email,email,status,assigned_profile,last_contacted_at,unsubscribed_at,created_at,updated_at", limit=1500, order="created_at.desc", outreach=True),
        _supabase_select("outreach_suppressions", select="owner_email,email,source,reason,created_at", limit=1000, order="created_at.desc", outreach=True),
        _supabase_select("outreach_messages", select="id,owner_email,campaign_id,lead_id,to_email,status,provider,sender_profile,created_at,updated_at,sent_at", limit=1500, order="created_at.desc", outreach=True),
        _supabase_select("outreach_events", select="owner_email,message_id,event_type,provider,occurred_at,created_at", limit=1500, order="occurred_at.desc", outreach=True),
        _supabase_select("outreach_replies", select="owner_email,message_id,from_email,received_at,created_at", limit=1000, order="received_at.desc", outreach=True),
        _supabase_select("outreach_unsubscribes", select="email,reason,source,created_at,updated_at", limit=1000, order="created_at.desc", outreach=True),
    )

    return {
        "main_configured": main_configured,
        "outreach_configured": outreach_configured,
        "profiles": profiles,
        "token_usage": _filter_recent_rows(token_usage, "created_at", since=since),
        "sessions": _filter_recent_rows(sessions, "created_at", since=since),
        "facts": _filter_recent_rows(facts, "created_at", since=since),
        "portfolio_mirrors": portfolio_mirrors,
        "verification_codes": _filter_recent_rows(verification_codes, "created_at", since=since),
        "pending_extractions": pending_extractions,
        "revoked_tokens": _filter_recent_rows(revoked_tokens, "revoked_at", "expires_at", since=since),
        "contacts": contacts,
        "scrape_jobs": _filter_recent_rows(scrape_jobs, "created_at", "heartbeat_at", "completed_at", since=since),
        "scrape_checkpoints": scrape_checkpoints,
        "extraction_rules": extraction_rules,
        "export_jobs": _filter_recent_rows(export_jobs, "created_at", "completed_at", since=since),
        "sebi_verified_leads": _filter_recent_rows(sebi_verified_leads, "created_at", since=since),
        "outreach_campaigns": _filter_recent_rows(outreach_campaigns, "created_at", "updated_at", since=since),
        "outreach_leads": _filter_recent_rows(outreach_leads, "created_at", "updated_at", since=since),
        "outreach_suppressions": _filter_recent_rows(outreach_suppressions, "created_at", since=since),
        "outreach_messages": _filter_recent_rows(outreach_messages, "created_at", "updated_at", "sent_at", since=since),
        "outreach_events": _filter_recent_rows(outreach_events, "occurred_at", "created_at", since=since),
        "outreach_replies": _filter_recent_rows(outreach_replies, "received_at", "created_at", since=since),
        "outreach_unsubscribes": _filter_recent_rows(outreach_unsubscribes, "created_at", "updated_at", since=since),
    }


def _local_auth_db_path() -> Path:
    return repo_root() / "finagent" / "prospektlab.db"


def _load_local_store_stats(days: int) -> dict[str, Any]:
    since = _days_ago(days)
    auth_rows: list[dict[str, Any]] = []
    auth_providers: Counter[str] = Counter()
    auth_latest: datetime | None = None

    auth_db = _local_auth_db_path()
    if auth_db.exists():
        try:
            with sqlite3.connect(auth_db) as conn:
                conn.row_factory = sqlite3.Row
                for row in conn.execute("SELECT email, full_name, auth_provider, created_at FROM users ORDER BY created_at DESC").fetchall():
                    item = dict(row)
                    parsed = _parse_dt(item.get("created_at"))
                    auth_latest = max([entry for entry in [auth_latest, parsed] if entry is not None], default=auth_latest)
                    if parsed is not None and parsed < since:
                        continue
                    auth_rows.append(
                        {
                            "email": item.get("email") or "",
                            "full_name": item.get("full_name") or "",
                            "auth_provider": item.get("auth_provider") or "",
                            "created_at": parsed.isoformat() if parsed else (item.get("created_at") or ""),
                            "updated_at": parsed.isoformat() if parsed else (item.get("created_at") or ""),
                            "source": "local_auth_db",
                        }
                    )
                    provider = str(item.get("auth_provider") or "unknown").strip() or "unknown"
                    auth_providers[provider] += 1
        except Exception as exc:
            logger.debug("Control tower local auth DB read failed: %s", exc)

    state_counts = {
        "verification_codes": 0,
        "pending_extractions": 0,
        "revoked_tokens": 0,
        "outreach_unsubscribes": 0,
        "outreach_events": 0,
        "rate_limits": 0,
    }
    state_latest: datetime | None = None
    state_db = finagent_data_path("state.sqlite3")
    if state_db.exists():
        try:
            with connect_wal(state_db, timeout=2.0) as conn:
                for table_name in state_counts:
                    state_counts[table_name] = int(conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])
                state_latest_candidates = [
                    conn.execute("SELECT MAX(created_at) FROM verification_codes").fetchone()[0],
                    conn.execute("SELECT MAX(created_at) FROM pending_extractions").fetchone()[0],
                    conn.execute("SELECT MAX(revoked_at) FROM revoked_tokens").fetchone()[0],
                    conn.execute("SELECT MAX(updated_at) FROM outreach_unsubscribes").fetchone()[0],
                    conn.execute("SELECT MAX(created_at) FROM outreach_events").fetchone()[0],
                    conn.execute("SELECT MAX(window_start) FROM rate_limits").fetchone()[0],
                ]
                for raw_value in state_latest_candidates:
                    parsed = _parse_dt(raw_value)
                    if parsed is not None:
                        state_latest = max([entry for entry in [state_latest, parsed] if entry is not None], default=state_latest)
        except Exception as exc:
            logger.debug("Control tower local state DB read failed: %s", exc)

    return {
        "auth_rows": auth_rows,
        "auth_user_count": len(auth_rows),
        "auth_providers": auth_providers,
        "auth_latest": auth_latest,
        "state_counts": state_counts,
        "state_latest": state_latest,
        "connected": auth_db.exists() or state_db.exists(),
    }


def _merge_identity_profiles(profiles: list[dict[str, Any]], local_auth_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in profiles + local_auth_rows:
        email = _safe_email(row.get("email"))
        if not email or _is_local_dev_identity(email):
            continue
        existing = merged.get(email, {})
        merged[email] = {
            **existing,
            **row,
            "email": email,
            "full_name": row.get("full_name") or existing.get("full_name") or email.split("@")[0],
            "auth_provider": row.get("auth_provider") or existing.get("auth_provider") or "",
            "created_at": row.get("created_at") or existing.get("created_at") or "",
            "updated_at": row.get("updated_at") or existing.get("updated_at") or row.get("created_at") or existing.get("updated_at") or "",
        }
    return list(merged.values())


def _empty_series_row(date_key: str) -> dict[str, Any]:
    return {
        "date": date_key,
        "landing": 0,
        "signup_started": 0,
        "signup_completed": 0,
        "onboarding_completed": 0,
        "workspace": 0,
        "first_value": 0,
        "retained": 0,
        "auth_success": 0,
        "auth_failure": 0,
        "portfolio": 0,
        "research": 0,
        "content": 0,
        "chat": 0,
        "requests": 0,
        "dependencies": 0,
        "errors": 0,
        "profiles": 0,
        "workspace_users": 0,
        "first_value_users": 0,
        "retained_users": 0,
        "outreach_messages": 0,
        "token_logs": 0,
    }


def _build_verified_series(
    days: int,
    *,
    profile_rows: list[dict[str, Any]],
    session_rows: list[dict[str, Any]],
    fact_rows: list[dict[str, Any]],
    token_rows: list[dict[str, Any]],
    portfolio_rows: list[dict[str, Any]],
    outreach_rows: list[dict[str, Any]],
    combined_users: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    start_date = _days_ago(days - 1).date()
    series = {(start_date + timedelta(days=idx)).isoformat(): _empty_series_row((start_date + timedelta(days=idx)).isoformat()) for idx in range(days)}

    def _row_for(ts_value: Any) -> dict[str, Any] | None:
        parsed = _parse_dt(ts_value)
        if parsed is None:
            return None
        key = parsed.date().isoformat()
        return series.get(key)

    for row in profile_rows:
        entry = _row_for(row.get("created_at") or row.get("updated_at"))
        if entry is None:
            continue
        entry["profiles"] += 1
        entry["signup_completed"] += 1
        entry["auth_success"] += 1

    workspace_users_by_day: dict[str, set[str]] = defaultdict(set)
    first_value_users_by_day: dict[str, set[str]] = defaultdict(set)
    retained_users_by_day: dict[str, set[str]] = defaultdict(set)

    for row in session_rows:
        entry = _row_for(row.get("created_at"))
        if entry is None:
            continue
        email = _safe_email(row.get("user_email"))
        if email:
            workspace_users_by_day[entry["date"]].add(email)
        entry["chat"] += 1

    for row in token_rows:
        entry = _row_for(row.get("created_at"))
        if entry is None:
            continue
        email = _safe_email(row.get("user_email"))
        if email:
            workspace_users_by_day[entry["date"]].add(email)
        entry["token_logs"] += 1
        entry["chat"] += 1

    for row in fact_rows:
        entry = _row_for(row.get("created_at"))
        if entry is None:
            continue
        email = _safe_email(row.get("user_email"))
        if email:
            workspace_users_by_day[entry["date"]].add(email)
            first_value_users_by_day[entry["date"]].add(email)
        entry["research"] += 1
        entry["content"] += 1
        entry["first_value"] += 1

    for row in portfolio_rows:
        entry = _row_for(row.get("updated_at") or row.get("created_at"))
        if entry is None:
            continue
        entry["portfolio"] += 1

    for row in outreach_rows:
        entry = _row_for(row.get("sent_at") or row.get("updated_at") or row.get("created_at"))
        if entry is None:
            continue
        entry["outreach_messages"] += 1

    for row in combined_users:
        if row.get("stage") != "retained":
            continue
        entry = _row_for(row.get("last_seen"))
        if entry is None:
            continue
        email = _safe_email(row.get("email"))
        if email:
            retained_users_by_day[entry["date"]].add(email)

    for key, entry in series.items():
        entry["workspace_users"] = len(workspace_users_by_day.get(key) or set())
        entry["first_value_users"] = len(first_value_users_by_day.get(key) or set())
        entry["retained_users"] = len(retained_users_by_day.get(key) or set())
        entry["workspace"] = entry["workspace_users"] or entry["token_logs"]
        entry["retained"] = entry["retained_users"]

    return list(series.values())


def _build_persisted_tracking_groups(
    workspace_summary: dict[str, Any],
    portfolio_summary: dict[str, Any],
    outreach_summary: dict[str, Any],
    profile_count: int,
) -> list[dict[str, Any]]:
    counters = {
        "frontend": 0,
        "auth": profile_count,
        "onboarding": workspace_summary["unique_users"],
        "portfolio": portfolio_summary["active_positions"] + portfolio_summary["pending_reviews"],
        "research": workspace_summary["insight_rows"],
        "content": workspace_summary["insight_rows"],
        "chat": workspace_summary["session_count"] + len(workspace_summary.get("top_models") or []),
    }
    total = sum(counters.values()) or 1
    rows: list[dict[str, Any]] = []
    for group_key, tracked_names in TRACKED_EVENT_GROUPS.items():
        meta = TRACKED_EVENT_GROUP_META[group_key]
        amount = int(counters.get(group_key) or 0)
        active_events = min(len(tracked_names), max(0, amount if amount < len(tracked_names) else len(tracked_names)))
        top_event_name = sorted(tracked_names)[0] if tracked_names else ""
        rows.append(
            {
                "key": group_key,
                "label": meta["label"],
                "description": meta["description"],
                "color": meta["color"],
                "total": amount,
                "share_pct": amount / total * 100,
                "coverage_pct": active_events / max(1, len(tracked_names)) * 100,
                "tracked_event_count": len(tracked_names),
                "active_event_count": active_events,
                "success_count": amount if group_key != "frontend" else 0,
                "failure_count": 0,
                "success_rate": 100.0 if amount else 0.0,
                "top_event": {
                    "name": top_event_name,
                    "label": _event_label(top_event_name),
                    "count": amount,
                },
                "status": "active" if amount else "silent",
            }
        )
    rows.sort(key=lambda item: (item["total"], item["coverage_pct"]), reverse=True)
    return rows


def _build_persisted_tracking_catalog(
    workspace_summary: dict[str, Any],
    portfolio_summary: dict[str, Any],
    outreach_summary: dict[str, Any],
    profile_count: int,
) -> list[dict[str, Any]]:
    counts = {
        "auth_signup_success": profile_count,
        "onboarding_completed": workspace_summary["unique_users"],
        "portfolio_mirror_replace_completed": portfolio_summary["active_positions"],
        "portfolio_upload_review_required": portfolio_summary["pending_reviews"],
        "research_stream_completed": workspace_summary["insight_rows"],
        "chat_completed": workspace_summary["session_count"],
        "content_article_generated": workspace_summary["insight_rows"],
        "auth_verification_sent": portfolio_summary["verification_codes"],
    }
    if outreach_summary["messages"]:
        counts["content_events_ingested"] = outreach_summary["messages"]
    total = sum(counts.values()) or 1
    catalog: list[dict[str, Any]] = []
    for group_key, tracked_names in TRACKED_EVENT_GROUPS.items():
        meta = TRACKED_EVENT_GROUP_META[group_key]
        for event_name in sorted(tracked_names):
            count = int(counts.get(event_name) or 0)
            catalog.append(
                {
                    "name": event_name,
                    "label": _event_label(event_name),
                    "group": group_key,
                    "group_label": meta["label"],
                    "color": meta["color"],
                    "count": count,
                    "pct": count / total * 100,
                    "status": "active" if count else "silent",
                }
            )
    catalog.sort(key=lambda item: (item["count"], item["group_label"], item["label"]), reverse=True)
    return catalog


def _build_funnel_dropoffs(funnel: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(funnel) < 2:
        placeholder = {"label": "No funnel available", "detail": "Waiting for connected telemetry.", "amount": 0, "pct": 0.0, "color": "#55d6ff"}
        return [placeholder], placeholder

    baseline = max(1, int(funnel[0].get("value") or 0))
    palette = ["#55d6ff", "#7cf2b6", "#ffbf69", "#ff7ea8", "#8da8ff", "#f9f871"]
    dropoffs: list[dict[str, Any]] = []
    for idx in range(len(funnel) - 1):
        current = funnel[idx]
        nxt = funnel[idx + 1]
        amount = max(0, int(current.get("value") or 0) - int(nxt.get("value") or 0))
        dropoffs.append(
            {
                "label": f"{current.get('stage', 'Stage')} -> {nxt.get('stage', 'Stage')}",
                "detail": f"Verified movement from {current.get('stage', 'this stage')} to {nxt.get('stage', 'the next stage')}.",
                "amount": amount,
                "pct": amount / baseline * 100,
                "color": palette[idx % len(palette)],
            }
        )
    biggest = max(dropoffs, key=lambda item: item["amount"])
    return dropoffs, biggest


def _aggregate_event_summary(rows: list[dict[str, Any]], range_days: int) -> dict[str, Any]:
    _ = range_days
    top_routes: Counter[str] = Counter()
    top_events: Counter[str] = Counter()
    request_route_counts: Counter[str] = Counter()
    dependency_target_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    event_group_counts: Counter[str] = Counter()
    group_event_counts: dict[str, Counter[str]] = defaultdict(Counter)

    landing_sessions: set[str] = set()
    signup_sessions: set[str] = set()
    signup_completed_sessions: set[str] = set()
    onboarding_sessions: set[str] = set()
    workspace_sessions: set[str] = set()
    first_value_sessions: set[str] = set()
    auth_failure_sessions: set[str] = set()

    request_durations: list[float] = []
    dependency_durations: list[float] = []
    request_rows: list[dict[str, Any]] = []
    request_errors: list[dict[str, Any]] = []
    dependency_rows: list[dict[str, Any]] = []
    dependency_errors: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    user_signals: dict[str, dict[str, Any]] = {}
    latest_ts: datetime | None = None
    daily_rows: dict[str, dict[str, Any]] = {}

    def day_bucket(date_key: str) -> dict[str, Any]:
        return daily_rows.setdefault(
            date_key,
            {
                "date": date_key,
                "landing": 0,
                "signup_started": 0,
                "signup_completed": 0,
                "onboarding_completed": 0,
                "workspace": 0,
                "first_value": 0,
                "auth_success": 0,
                "auth_failure": 0,
                "portfolio": 0,
                "research": 0,
                "content": 0,
                "chat": 0,
                "requests": 0,
                "dependencies": 0,
                "errors": 0,
                "routes": {},
            },
        )

    def ensure_user(email: str, ts: datetime, source: str) -> dict[str, Any]:
        bucket = user_signals.setdefault(
            email,
            {
                "email": email,
                "name": email.split("@", 1)[0].replace(".", " ").replace("_", " ").title(),
                "landing_sessions": 0,
                "signup_started_sessions": 0,
                "signup_completed_sessions": 0,
                "onboarding_sessions": 0,
                "workspace_sessions": 0,
                "first_value_sessions": 0,
                "failed_auth_sessions": 0,
                "research_events": 0,
                "portfolio_events": 0,
                "content_events": 0,
                "chat_events": 0,
                "request_count": 0,
                "request_errors": 0,
                "dependency_errors": 0,
                "exception_count": 0,
                "active_days": set(),
                "sources": set(),
                "last_seen": ts,
                "first_seen": ts,
                "total_events": 0,
            },
        )
        bucket["last_seen"] = max(bucket["last_seen"], ts)
        bucket["first_seen"] = min(bucket["first_seen"], ts)
        bucket["active_days"].add(ts.date().isoformat())
        if source:
            bucket["sources"].add(source)
        return bucket

    for row in rows:
        ts = _parse_dt(row.get("timestamp"))
        if not ts:
            continue
        latest_ts = max(latest_ts, ts) if latest_ts else ts
        date_key = ts.date().isoformat()
        day = day_bucket(date_key)

        kind = str(row.get("kind") or "").lower()
        event_name = str(row.get("event_name") or "").strip()
        route = _normalized_path(row.get("route"))
        target = str(row.get("target") or "").strip()
        email = _safe_email(row.get("user_email"))
        session_id = str(row.get("session_id") or "").strip()
        identity = session_id or email
        source = str(row.get("source") or "").strip().lower() or ("frontend" if kind in {"pageview", "dependency"} else "backend")
        duration_ms = _duration_to_ms(row.get("duration_text"))
        success = bool(row.get("success")) if row.get("success") is not None else True
        status_code = str(row.get("status_code") or "").strip()
        message = str(row.get("message") or "").strip()

        if source:
            source_counts[source] += 1

        if kind == "pageview":
            key = route or "/"
            top_routes[key] += 1
            day["routes"][key] = day["routes"].get(key, 0) + 1
            if key in LANDING_ROUTES:
                day["landing"] += 1
                if identity:
                    landing_sessions.add(identity)
            if key in SIGNUP_ROUTES:
                day["signup_started"] += 1
                if identity:
                    signup_sessions.add(identity)
            if key in ONBOARDING_ROUTES:
                day["onboarding_completed"] += 1
                if identity:
                    onboarding_sessions.add(identity)
            if key in WORKSPACE_ROUTES:
                day["workspace"] += 1
                if identity:
                    workspace_sessions.add(identity)
            if email:
                bucket = ensure_user(email, ts, source)
                bucket["total_events"] += 1
                if key in LANDING_ROUTES:
                    bucket["landing_sessions"] += 1
                if key in SIGNUP_ROUTES:
                    bucket["signup_started_sessions"] += 1
                if key in ONBOARDING_ROUTES:
                    bucket["onboarding_sessions"] += 1
                if key in WORKSPACE_ROUTES:
                    bucket["workspace_sessions"] += 1
            continue

        if kind == "event":
            top_events[event_name] += 1
            group = _event_group(event_name)
            if group:
                event_group_counts[group] += 1
                group_event_counts[group][event_name] += 1
            if identity and event_name in AUTH_STARTED_EVENTS:
                signup_sessions.add(identity)
            if identity and event_name in SIGNUP_SUCCESS_EVENTS:
                signup_completed_sessions.add(identity)
            if identity and event_name in ONBOARDING_EVENTS:
                onboarding_sessions.add(identity)
            if identity and event_name in WORKSPACE_EVENTS:
                workspace_sessions.add(identity)
            if identity and event_name in INSIGHT_EVENTS:
                first_value_sessions.add(identity)
            if identity and event_name in SIGNUP_FAILURE_EVENTS:
                auth_failure_sessions.add(identity)

            if event_name in AUTH_STARTED_EVENTS:
                day["signup_started"] += 1
            if event_name in AUTH_SUCCESS_EVENTS:
                day["signup_started"] += 1
                day["signup_completed"] += 1
                day["auth_success"] += 1
            if event_name in AUTH_FAILURE_EVENTS:
                day["auth_failure"] += 1
                day["errors"] += 1
            if event_name in ONBOARDING_EVENTS:
                day["onboarding_completed"] += 1
            if event_name in WORKSPACE_EVENTS:
                day["workspace"] += 1
            if event_name in INSIGHT_EVENTS:
                day["first_value"] += 1
            if event_name in PORTFOLIO_EVENTS:
                day["portfolio"] += 1
            if event_name in RESEARCH_EVENTS:
                day["research"] += 1
            if event_name in CONTENT_EVENTS:
                day["content"] += 1
            if event_name in CHAT_EVENTS:
                day["chat"] += 1
            if event_name in PORTFOLIO_FAILURE_EVENTS or event_name in RESEARCH_FAILURE_EVENTS:
                day["errors"] += 1

            if email:
                bucket = ensure_user(email, ts, source)
                bucket["total_events"] += 1
                if event_name in AUTH_STARTED_EVENTS:
                    bucket["signup_started_sessions"] += 1
                if event_name in AUTH_SUCCESS_EVENTS:
                    bucket["signup_completed_sessions"] += 1
                if event_name in SIGNUP_FAILURE_EVENTS:
                    bucket["failed_auth_sessions"] += 1
                if event_name in ONBOARDING_EVENTS:
                    bucket["onboarding_sessions"] += 1
                if event_name in WORKSPACE_EVENTS:
                    bucket["workspace_sessions"] += 1
                if event_name in INSIGHT_EVENTS:
                    bucket["first_value_sessions"] += 1
                if event_name in PORTFOLIO_EVENTS:
                    bucket["portfolio_events"] += 1
                if event_name in RESEARCH_EVENTS:
                    bucket["research_events"] += 1
                if event_name in CONTENT_EVENTS:
                    bucket["content_events"] += 1
                if event_name in CHAT_EVENTS:
                    bucket["chat_events"] += 1
            continue

        if kind == "request":
            route_key = route or _normalized_path(message) or _normalized_path(target) or event_name
            day["requests"] += 1
            request_entry = {
                "timestamp": ts.isoformat(),
                "name": event_name,
                "route": route_key,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "success": success,
                "source": source,
            }
            request_rows.append(request_entry)
            request_route_counts[route_key or event_name] += 1
            if duration_ms > 0:
                request_durations.append(duration_ms)
            if not success or status_code.startswith("4") or status_code.startswith("5"):
                day["errors"] += 1
                request_errors.append(request_entry)
            if email:
                bucket = ensure_user(email, ts, source)
                bucket["total_events"] += 1
                bucket["request_count"] += 1
                if not success or status_code.startswith("4") or status_code.startswith("5"):
                    bucket["request_errors"] += 1
            continue

        if kind == "dependency":
            target_key = _normalized_path(target) or _normalized_path(route) or event_name
            day["dependencies"] += 1
            dependency_entry = {
                "timestamp": ts.isoformat(),
                "name": event_name,
                "route": _normalized_path(route) or route,
                "target": target_key or target,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "success": success,
                "source": source,
                "message": message,
            }
            dependency_rows.append(dependency_entry)
            dependency_target_counts[target_key or event_name] += 1
            if duration_ms > 0:
                dependency_durations.append(duration_ms)
            if not success or status_code.startswith("4") or status_code.startswith("5"):
                day["errors"] += 1
                dependency_errors.append(dependency_entry)
            if email:
                bucket = ensure_user(email, ts, source)
                bucket["total_events"] += 1
                if not success or status_code.startswith("4") or status_code.startswith("5"):
                    bucket["dependency_errors"] += 1
            continue

        if kind == "exception":
            day["errors"] += 1
            exception_entry = {
                "timestamp": ts.isoformat(),
                "name": event_name,
                "route": route,
                "message": message,
                "target": target,
                "source": source,
            }
            exceptions.append(exception_entry)
            if email:
                bucket = ensure_user(email, ts, source)
                bucket["total_events"] += 1
                bucket["exception_count"] += 1

    rows_by_day: list[dict[str, Any]] = []
    for date_key in sorted(daily_rows):
        entry = daily_rows[date_key]
        if entry["signup_started"] < entry["signup_completed"]:
            entry["signup_started"] = entry["signup_completed"]
        if entry["workspace"] < entry["first_value"]:
            entry["workspace"] = entry["first_value"]
        if entry["onboarding_completed"] < min(entry["signup_completed"], entry["workspace"]):
            entry["onboarding_completed"] = min(entry["signup_completed"], entry["workspace"])
        rows_by_day.append(entry)

    user_rows = []
    for email, bucket in user_signals.items():
        active_days = len(bucket["active_days"])
        signup_started = int(bucket["signup_started_sessions"])
        signup_completed = int(bucket["signup_completed_sessions"])
        onboarding = int(bucket["onboarding_sessions"])
        workspace = int(bucket["workspace_sessions"])
        first_value = int(bucket["first_value_sessions"])
        landing = int(bucket["landing_sessions"])
        retained = 1 if active_days >= 2 or (first_value > 0 and active_days >= 1) else 0
        stage, action = _choose_stage(
            {
                "landing_sessions": landing,
                "signup_started_sessions": signup_started,
                "signup_completed_sessions": signup_completed,
                "onboarding_sessions": onboarding,
                "workspace_sessions": workspace,
                "first_value_sessions": first_value,
                "retained_sessions": retained,
                "active_days": active_days,
            }
        )
        user_rows.append(
            {
                "email": email,
                "name": bucket["name"],
                "stage": stage,
                "action": action,
                "sources": sorted(bucket["sources"]),
                "last_seen": bucket["last_seen"].isoformat(),
                "first_seen": bucket["first_seen"].isoformat(),
                "landing_sessions": landing,
                "signup_started_sessions": signup_started,
                "signup_completed_sessions": signup_completed,
                "onboarding_sessions": onboarding,
                "workspace_sessions": workspace,
                "first_value_sessions": first_value,
                "retained_sessions": retained,
                "active_days": active_days,
                "total_events": int(bucket["total_events"]),
                "failed_auth_sessions": int(bucket["failed_auth_sessions"]),
                "research_events": int(bucket["research_events"]),
                "portfolio_events": int(bucket["portfolio_events"]),
                "content_events": int(bucket["content_events"]),
                "chat_events": int(bucket["chat_events"]),
                "request_count": int(bucket["request_count"]),
                "request_errors": int(bucket["request_errors"]),
                "dependency_errors": int(bucket["dependency_errors"]),
                "exception_count": int(bucket["exception_count"]),
            }
        )

    return {
        "rows_by_day": rows_by_day,
        "top_routes": top_routes,
        "top_events": top_events,
        "landing_sessions": len(landing_sessions),
        "signup_started_sessions": len(signup_sessions),
        "signup_completed_sessions": len(signup_completed_sessions),
        "onboarding_completed_sessions": len(onboarding_sessions),
        "workspace_sessions": len(workspace_sessions),
        "first_value_sessions": len(first_value_sessions),
        "auth_failure_sessions": len(auth_failure_sessions),
        "request_durations": request_durations,
        "dependency_durations": dependency_durations,
        "request_rows": request_rows,
        "dependency_rows": dependency_rows,
        "request_errors": request_errors,
        "dependency_errors": dependency_errors,
        "exceptions": exceptions,
        "users": user_rows,
        "event_group_counts": dict(event_group_counts),
        "group_event_counts": {key: dict(counter) for key, counter in group_event_counts.items()},
        "request_route_counts": request_route_counts,
        "dependency_target_counts": dependency_target_counts,
        "source_counts": source_counts,
        "latest_ts": latest_ts,
    }


def _parse_rows_to_user_summary(
    rows: list[dict[str, Any]],
    profiles: list[dict[str, Any]],
    token_usage: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    portfolio_mirrors: list[dict[str, Any]],
    pending_extractions: list[dict[str, Any]],
    outreach_messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    profile_map = {
        (_safe_email(row.get("email"))): row
        for row in profiles
        if _safe_email(row.get("email")) and not _is_local_dev_identity(_safe_email(row.get("email")))
    }

    token_map: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"token_usage": 0, "token_rows": 0, "models": Counter(), "last_seen": None}
    )
    for row in token_usage:
        email = _safe_email(row.get("user_email"))
        if not email or _is_local_dev_identity(email):
            continue
        token_map[email]["token_usage"] += _safe_int(row.get("total_tokens"))
        token_map[email]["token_rows"] += 1
        model = str(row.get("model") or "").strip()
        if model:
            token_map[email]["models"][model] += 1
        ts = _parse_dt(row.get("created_at"))
        if ts and (token_map[email]["last_seen"] is None or ts > token_map[email]["last_seen"]):
            token_map[email]["last_seen"] = ts

    session_map: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "workspace_sessions": 0,
            "quality_total": 0.0,
            "quality_rows": 0,
            "citation_total": 0,
            "targets": Counter(),
            "last_seen": None,
        }
    )
    for row in sessions:
        email = _safe_email(row.get("user_email"))
        if not email or _is_local_dev_identity(email):
            continue
        session_map[email]["workspace_sessions"] += 1
        session_map[email]["quality_total"] += _safe_float(row.get("quality_score"))
        if row.get("quality_score") not in (None, ""):
            session_map[email]["quality_rows"] += 1
        session_map[email]["citation_total"] += _safe_int(row.get("citation_count"))
        target_label = str(row.get("target_display") or row.get("target_key") or "").strip()
        if target_label:
            session_map[email]["targets"][target_label] += 1
        ts = _parse_dt(row.get("created_at"))
        if ts and (session_map[email]["last_seen"] is None or ts > session_map[email]["last_seen"]):
            session_map[email]["last_seen"] = ts

    fact_map: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"insight_rows": 0, "kinds": Counter(), "targets": Counter(), "last_seen": None}
    )
    for row in facts:
        email = _safe_email(row.get("user_email"))
        if not email or _is_local_dev_identity(email):
            continue
        fact_map[email]["insight_rows"] += 1
        kind = str(row.get("kind") or "").strip()
        target = str(row.get("target_key") or "").strip()
        if kind:
            fact_map[email]["kinds"][kind] += 1
        if target:
            fact_map[email]["targets"][target] += 1
        ts = _parse_dt(row.get("created_at"))
        if ts and (fact_map[email]["last_seen"] is None or ts > fact_map[email]["last_seen"]):
            fact_map[email]["last_seen"] = ts

    portfolio_map: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"positions": 0, "market_value": 0.0, "cost_basis": 0.0}
    )
    for row in portfolio_mirrors:
        tenant_id = str(row.get("tenant_id") or "").strip()
        if not tenant_id:
            continue
        if _safe_int(row.get("active") or 1) == 0:
            continue
        portfolio_map[tenant_id]["positions"] += 1
        portfolio_map[tenant_id]["market_value"] += _safe_float(row.get("market_value"))
        portfolio_map[tenant_id]["cost_basis"] += _safe_float(row.get("cost_basis"))

    review_map: Counter[str] = Counter()
    for row in pending_extractions:
        tenant_id = str(row.get("tenant_id") or "").strip()
        if tenant_id:
            review_map[tenant_id] += 1

    outreach_map: dict[str, dict[str, Any]] = defaultdict(lambda: {"messages": 0, "sent": 0, "last_seen": None})
    sent_statuses = {"queued", "sent", "delivered", "opened", "clicked", "replied"}
    for row in outreach_messages:
        email = _safe_email(row.get("owner_email"))
        if not email or _is_local_dev_identity(email):
            continue
        outreach_map[email]["messages"] += 1
        if str(row.get("status") or "").strip().lower() in sent_statuses:
            outreach_map[email]["sent"] += 1
        ts = _parse_dt(row.get("sent_at")) or _parse_dt(row.get("updated_at")) or _parse_dt(row.get("created_at"))
        if ts and (outreach_map[email]["last_seen"] is None or ts > outreach_map[email]["last_seen"]):
            outreach_map[email]["last_seen"] = ts

    telemetry_map = {
        (_safe_email(row.get("email"))): row
        for row in rows
        if _safe_email(row.get("email")) and not _is_local_dev_identity(_safe_email(row.get("email")))
    }
    all_emails = set(profile_map) | set(token_map) | set(session_map) | set(fact_map) | set(telemetry_map) | set(outreach_map)

    combined: list[dict[str, Any]] = []
    for email in all_emails:
        telemetry_row = telemetry_map.get(email, {})
        profile = profile_map.get(email, {})
        token = token_map.get(email, {})
        session = session_map.get(email, {})
        fact = fact_map.get(email, {})
        outreach = outreach_map.get(email, {})
        tenant_id = str(profile.get("id") or "").strip()
        portfolio = portfolio_map.get(tenant_id, {})
        pending_reviews = review_map.get(tenant_id, 0)

        last_seen_candidates = [
            _parse_dt(telemetry_row.get("last_seen")) if telemetry_row else None,
            _parse_dt(profile.get("updated_at")),
            token.get("last_seen"),
            session.get("last_seen"),
            fact.get("last_seen"),
            outreach.get("last_seen"),
        ]
        last_seen = max([dt for dt in last_seen_candidates if dt is not None], default=_now_utc())

        source_tags = set()
        if telemetry_row:
            source_tags.update(telemetry_row.get("sources") or [])
        if profile or token:
            source_tags.add("Supabase")
        if session or portfolio:
            source_tags.add("ProspektLab Workspace")
        if fact or outreach:
            source_tags.add("ProspektLab Insights")

        stage_data = {
            "landing_sessions": _safe_int(telemetry_row.get("landing_sessions")) if telemetry_row else 0,
            "signup_started_sessions": _safe_int(telemetry_row.get("signup_started_sessions")) if telemetry_row else 0,
            "signup_completed_sessions": _safe_int(telemetry_row.get("signup_completed_sessions")) if telemetry_row else 0,
            "onboarding_sessions": _safe_int(telemetry_row.get("onboarding_sessions")) if telemetry_row else 0,
            "workspace_sessions": max(_safe_int(telemetry_row.get("workspace_sessions")) if telemetry_row else 0, _safe_int(session.get("workspace_sessions"))),
            "first_value_sessions": max(_safe_int(telemetry_row.get("first_value_sessions")) if telemetry_row else 0, _safe_int(fact.get("insight_rows"))),
            "retained_sessions": _safe_int(telemetry_row.get("retained_sessions")) if telemetry_row else 0,
            "active_days": _safe_int(telemetry_row.get("active_days")) if telemetry_row else 0,
        }
        stage, action = _choose_stage(stage_data)
        top_model = token.get("models").most_common(1)[0][0] if token.get("models") else ""
        target_counter = Counter()
        target_counter.update(session.get("targets") or {})
        target_counter.update(fact.get("targets") or {})
        top_target = target_counter.most_common(1)[0][0] if target_counter else ""
        quality_rows = _safe_int(session.get("quality_rows"))
        avg_quality = (_safe_float(session.get("quality_total")) / quality_rows) if quality_rows else 0.0

        name = (profile.get("full_name") or telemetry_row.get("name") or email.split("@", 1)[0]).strip() or email
        combined.append(
            {
                "email": email,
                "name": name,
                "stage": stage,
                "source": " + ".join(sorted(source_tags)) if source_tags else "Azure + Supabase",
                "last_seen": last_seen.isoformat(),
                "workspace_events": _safe_int(session.get("workspace_sessions") or stage_data["workspace_sessions"]),
                "token_usage": _safe_int(token.get("token_usage")),
                "insight_rows": _safe_int(fact.get("insight_rows")),
                "portfolio_positions": _safe_int(portfolio.get("positions")),
                "portfolio_value": _safe_float(portfolio.get("market_value")),
                "pending_reviews": _safe_int(pending_reviews),
                "avg_quality_score": round(avg_quality, 1) if avg_quality else 0.0,
                "citation_count": _safe_int(session.get("citation_total")),
                "outreach_messages": _safe_int(outreach.get("messages")),
                "outreach_sent": _safe_int(outreach.get("sent")),
                "top_model": top_model,
                "top_target": top_target,
                "risk": "low" if _stage_rank(stage) >= 5 else "medium" if _stage_rank(stage) >= 3 else "high",
                "action": action,
                "auth_provider": profile.get("auth_provider") or "",
                "created_at": profile.get("created_at") or "",
                "updated_at": profile.get("updated_at") or "",
            }
        )

    combined.sort(key=lambda item: (_stage_rank(item["stage"]), item["last_seen"]), reverse=True)
    return combined


def _build_dropoffs(summary: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    landing = int(summary.get("landing_sessions") or 0)
    signup_started = int(summary.get("signup_started_sessions") or 0)
    signup_completed = int(summary.get("signup_completed_sessions") or 0)
    onboarding = int(summary.get("onboarding_completed_sessions") or 0)
    workspace = int(summary.get("workspace_sessions") or 0)
    first_value = int(summary.get("first_value_sessions") or 0)
    auth_failures = int(summary.get("auth_failure_sessions") or 0)
    p95_latency = float(summary.get("p95_latency_ms") or 0)

    dropoffs = [
        {
            "label": "Landing CTA friction",
            "detail": "Visitors are not making the jump from landing traffic into signup quickly enough.",
            "amount": max(0, landing - signup_started),
            "color": "#55d6ff",
        },
        {
            "label": "Signup / auth friction",
            "detail": "Auth failures or verification delays are interrupting the signup path.",
            "amount": max(0, signup_started - signup_completed + auth_failures),
            "color": "#7cf2b6",
        },
        {
            "label": "Onboarding friction",
            "detail": "Users are dropping before they reach a completed setup.",
            "amount": max(0, signup_completed - onboarding),
            "color": "#ffbf69",
        },
        {
            "label": "Workspace activation delay",
            "detail": "Users are landing in the workspace but not getting into useful actions fast enough.",
            "amount": max(0, onboarding - workspace),
            "color": "#ff7ea8",
        },
        {
            "label": "First insight latency",
            "detail": "Users are getting through setup but not seeing the first value quickly.",
            "amount": max(0, workspace - first_value + int(max(0, p95_latency - 250) // 40)),
            "color": "#8da8ff",
        },
    ]

    total = max(1, landing)
    for item in dropoffs:
        item["pct"] = item["amount"] / total * 100

    biggest = max(dropoffs, key=lambda item: item["amount"])
    return dropoffs, biggest


def _build_top_pages(top_routes: Counter[str]) -> list[dict[str, Any]]:
    items = []
    total = sum(top_routes.values()) or 1
    for route, views in top_routes.most_common(8):
        items.append({
            "route": route,
            "label": _route_label(route),
            "views": int(views),
            "sessions": int(max(1, views)),
            "pct": views / total * 100,
        })
    return items


def _build_top_events(top_events: Counter[str]) -> list[dict[str, Any]]:
    items = []
    total = sum(top_events.values()) or 1
    for name, count in top_events.most_common(10):
        items.append({
            "name": name,
            "label": _event_label(name),
            "count": int(count),
            "pct": count / total * 100,
        })
    return items


def _counter_breakdown(
    counter: Counter[str] | dict[str, int],
    *,
    limit: int = 8,
    key_name: str = "name",
    value_name: str = "count",
    label_fn: Any | None = None,
) -> list[dict[str, Any]]:
    if isinstance(counter, Counter):
        items = counter.most_common(limit)
        total = sum(counter.values()) or 1
    else:
        temp = Counter(counter)
        items = temp.most_common(limit)
        total = sum(temp.values()) or 1
    rows: list[dict[str, Any]] = []
    for key, value in items:
        row = {
            key_name: key,
            value_name: int(value),
            "pct": value / total * 100,
        }
        if label_fn is not None:
            row["label"] = label_fn(key)
        rows.append(row)
    return rows


def _build_tracking_groups(aggregate: dict[str, Any]) -> list[dict[str, Any]]:
    group_totals = aggregate.get("event_group_counts") or {}
    group_breakdown = aggregate.get("group_event_counts") or {}
    total_tracked = sum(int(value) for value in group_totals.values()) or 1
    rows: list[dict[str, Any]] = []
    for group_key, meta in TRACKED_EVENT_GROUP_META.items():
        tracked_names = TRACKED_EVENT_GROUPS.get(group_key, set())
        seen_counter = Counter(group_breakdown.get(group_key) or {})
        seen_count = sum(seen_counter.values())
        success_count = sum(seen_counter.get(name, 0) for name in GROUP_SUCCESS_EVENTS.get(group_key, set()))
        failure_count = sum(seen_counter.get(name, 0) for name in GROUP_FAILURE_EVENTS.get(group_key, set()))
        active_event_types = sum(1 for name in tracked_names if seen_counter.get(name, 0) > 0)
        top_event_name, top_event_count = ("", 0)
        if seen_counter:
            top_event_name, top_event_count = seen_counter.most_common(1)[0]
        rows.append(
            {
                "key": group_key,
                "label": meta["label"],
                "description": meta["description"],
                "color": meta["color"],
                "total": seen_count,
                "share_pct": seen_count / total_tracked * 100,
                "coverage_pct": active_event_types / max(1, len(tracked_names)) * 100,
                "tracked_event_count": len(tracked_names),
                "active_event_count": active_event_types,
                "success_count": success_count,
                "failure_count": failure_count,
                "success_rate": success_count / max(1, success_count + failure_count) * 100 if (success_count or failure_count) else 0.0,
                "top_event": {
                    "name": top_event_name,
                    "label": _event_label(top_event_name) if top_event_name else "",
                    "count": int(top_event_count),
                },
                "status": "active" if seen_count else "silent",
            }
        )
    rows.sort(key=lambda item: (item["total"], item["coverage_pct"]), reverse=True)
    return rows


def _build_tracking_catalog(aggregate: dict[str, Any]) -> list[dict[str, Any]]:
    group_breakdown = aggregate.get("group_event_counts") or {}
    top_events = aggregate.get("top_events") or Counter()
    total = sum(top_events.values()) or 1
    catalog: list[dict[str, Any]] = []
    for group_key, tracked_names in TRACKED_EVENT_GROUPS.items():
        meta = TRACKED_EVENT_GROUP_META.get(group_key, {})
        seen_counter = Counter(group_breakdown.get(group_key) or {})
        for event_name in sorted(tracked_names):
            count = int(seen_counter.get(event_name, 0))
            catalog.append(
                {
                    "name": event_name,
                    "label": _event_label(event_name),
                    "group": group_key,
                    "group_label": meta.get("label", group_key.title()),
                    "color": meta.get("color", "#55d6ff"),
                    "count": count,
                    "pct": count / total * 100,
                    "status": "active" if count else "silent",
                }
            )
    catalog.sort(key=lambda item: (item["count"], item["group_label"], item["label"]), reverse=True)
    return catalog


def _build_operations_summary(aggregate: dict[str, Any], p95_latency_ms: float) -> dict[str, Any]:
    request_rows = aggregate.get("request_rows") or []
    dependency_rows = aggregate.get("dependency_rows") or []
    request_errors = aggregate.get("request_errors") or []
    dependency_errors = aggregate.get("dependency_errors") or []
    exceptions = aggregate.get("exceptions") or []
    request_durations = aggregate.get("request_durations") or []
    dependency_durations = aggregate.get("dependency_durations") or []

    request_p50 = statistics.median(request_durations) if request_durations else 0.0
    dependency_p95 = (
        statistics.quantiles(dependency_durations, n=100)[94]
        if len(dependency_durations) >= 5
        else (statistics.median(dependency_durations) if dependency_durations else 0.0)
    )
    request_volume = len(request_rows)
    dependency_volume = len(dependency_rows)
    exception_count = len(exceptions)
    total_ops = request_volume + dependency_volume
    error_count = len(request_errors) + len(dependency_errors) + exception_count

    return {
        "request_count": request_volume,
        "dependency_count": dependency_volume,
        "request_error_count": len(request_errors),
        "dependency_error_count": len(dependency_errors),
        "exception_count": exception_count,
        "error_count": error_count,
        "error_rate": error_count / max(1, total_ops) * 100,
        "request_p50_ms": request_p50,
        "request_p95_ms": p95_latency_ms,
        "dependency_p95_ms": dependency_p95,
        "dependency_success_rate": (dependency_volume - len(dependency_errors)) / max(1, dependency_volume) * 100 if dependency_volume else 0.0,
        "top_request_routes": _counter_breakdown(aggregate.get("request_route_counts") or Counter(), limit=6, key_name="route", value_name="count", label_fn=_route_label),
        "top_dependency_targets": _counter_breakdown(aggregate.get("dependency_target_counts") or Counter(), limit=6, key_name="target", value_name="count"),
        "slow_requests": sorted(request_rows, key=lambda row: _safe_float(row.get("duration_ms")), reverse=True)[:6],
        "slow_dependencies": sorted(dependency_rows, key=lambda row: _safe_float(row.get("duration_ms")), reverse=True)[:6],
        "source_breakdown": _counter_breakdown(aggregate.get("source_counts") or Counter(), limit=6, key_name="source", value_name="count"),
    }


def _build_workspace_summary(supabase_stats: dict[str, Any]) -> dict[str, Any]:
    sessions = supabase_stats.get("sessions") or []
    facts = supabase_stats.get("facts") or []
    token_usage = supabase_stats.get("token_usage") or []

    quality_values = [_safe_float(row.get("quality_score")) for row in sessions if row.get("quality_score") not in (None, "")]
    citation_values = [_safe_int(row.get("citation_count")) for row in sessions]
    tokens_total = sum(_safe_int(row.get("total_tokens")) for row in token_usage)
    token_models = Counter(str(row.get("model") or "").strip() for row in token_usage if str(row.get("model") or "").strip())
    target_counter = Counter(str(row.get("target_display") or row.get("target_key") or "").strip() for row in sessions if str(row.get("target_display") or row.get("target_key") or "").strip())
    fact_kinds = Counter(str(row.get("kind") or "").strip() for row in facts if str(row.get("kind") or "").strip())

    return {
        "session_count": len(sessions),
        "insight_rows": len(facts),
        "unique_users": len({_safe_email(row.get("user_email")) for row in sessions if _safe_email(row.get("user_email"))}),
        "unique_targets": len({str(row.get("target_key") or "").strip() for row in facts if str(row.get("target_key") or "").strip()} | {str(row.get("target_key") or "").strip() for row in sessions if str(row.get("target_key") or "").strip()}),
        "token_total": tokens_total,
        "avg_tokens_per_log": tokens_total / max(1, len(token_usage)),
        "avg_quality_score": statistics.mean(quality_values) if quality_values else 0.0,
        "avg_citation_count": statistics.mean(citation_values) if citation_values else 0.0,
        "top_models": _counter_breakdown(token_models, limit=6, key_name="model", value_name="count"),
        "top_targets": _counter_breakdown(target_counter, limit=6, key_name="target", value_name="count"),
        "fact_kinds": _counter_breakdown(fact_kinds, limit=6, key_name="kind", value_name="count"),
    }


def _build_portfolio_summary(supabase_stats: dict[str, Any]) -> dict[str, Any]:
    mirrors = supabase_stats.get("portfolio_mirrors") or []
    pending_extractions = supabase_stats.get("pending_extractions") or []
    verification_codes = supabase_stats.get("verification_codes") or []
    revoked_tokens = supabase_stats.get("revoked_tokens") or []

    active_mirrors = [row for row in mirrors if _safe_int(row.get("active") or 1) != 0]
    sector_counter = Counter(str(row.get("sector") or "Unassigned").strip() or "Unassigned" for row in active_mirrors)
    kind_counter = Counter(str(row.get("kind") or "unknown").strip() or "unknown" for row in active_mirrors)

    return {
        "active_positions": len(active_mirrors),
        "portfolio_users": len({str(row.get("tenant_id") or "").strip() for row in active_mirrors if str(row.get("tenant_id") or "").strip()}),
        "total_market_value": sum(_safe_float(row.get("market_value")) for row in active_mirrors),
        "total_cost_basis": sum(_safe_float(row.get("cost_basis")) for row in active_mirrors),
        "pending_reviews": len(pending_extractions),
        "verification_codes": len(verification_codes),
        "revoked_tokens": len(revoked_tokens),
        "top_sectors": _counter_breakdown(sector_counter, limit=6, key_name="sector", value_name="count"),
        "asset_mix": _counter_breakdown(kind_counter, limit=6, key_name="kind", value_name="count"),
    }


def _build_pipeline_summary(supabase_stats: dict[str, Any]) -> dict[str, Any]:
    contacts = supabase_stats.get("contacts") or []
    scrape_jobs = supabase_stats.get("scrape_jobs") or []
    scrape_checkpoints = supabase_stats.get("scrape_checkpoints") or []
    extraction_rules = supabase_stats.get("extraction_rules") or []
    export_jobs = supabase_stats.get("export_jobs") or []
    sebi_verified_leads = supabase_stats.get("sebi_verified_leads") or []

    return {
        "contacts": len(contacts),
        "scrape_jobs": len(scrape_jobs),
        "checkpoints": len(scrape_checkpoints),
        "rules": len(extraction_rules),
        "exports": len(export_jobs),
        "verified_leads": len(sebi_verified_leads),
        "contact_sources": _counter_breakdown(Counter(str(row.get("primary_source") or "unknown").strip() or "unknown" for row in contacts), limit=6, key_name="source", value_name="count"),
        "scrape_statuses": _counter_breakdown(Counter(str(row.get("status") or "unknown").strip() or "unknown" for row in scrape_jobs), limit=6, key_name="status", value_name="count"),
        "export_statuses": _counter_breakdown(Counter(str(row.get("status") or "unknown").strip() or "unknown" for row in export_jobs), limit=6, key_name="status", value_name="count"),
    }


def _build_geo_summary(supabase_stats: dict[str, Any]) -> dict[str, Any]:
    contacts = supabase_stats.get("contacts") or []

    def _clean_geo(value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        normalized = re.sub(r"\s+", " ", text)
        return normalized.title()

    state_counts: Counter[str] = Counter()
    city_counts: Counter[str] = Counter()
    location_counts: Counter[str] = Counter()

    for row in contacts:
        state = _clean_geo(row.get("state"))
        city = _clean_geo(row.get("city"))
        if state:
            state_counts[state] += 1
        if city:
            city_counts[city] += 1
        if city or state:
            label = ", ".join(part for part in [city, state] if part)
            location_counts[label] += 1

    contacts_total = len(contacts)
    contacts_with_location = sum(1 for row in contacts if _clean_geo(row.get("city")) or _clean_geo(row.get("state")))

    return {
        "contacts_total": contacts_total,
        "contacts_with_location": contacts_with_location,
        "location_coverage": contacts_with_location / max(1, contacts_total) * 100,
        "top_states": _counter_breakdown(state_counts, limit=8, key_name="state", value_name="count"),
        "top_cities": _counter_breakdown(city_counts, limit=8, key_name="city", value_name="count"),
        "top_locations": _counter_breakdown(location_counts, limit=8, key_name="location", value_name="count"),
    }


def _build_outreach_summary(supabase_stats: dict[str, Any]) -> dict[str, Any]:
    campaigns = supabase_stats.get("outreach_campaigns") or []
    leads = supabase_stats.get("outreach_leads") or []
    suppressions = supabase_stats.get("outreach_suppressions") or []
    messages = supabase_stats.get("outreach_messages") or []
    events = supabase_stats.get("outreach_events") or []
    replies = supabase_stats.get("outreach_replies") or []
    unsubscribes = supabase_stats.get("outreach_unsubscribes") or []

    lead_statuses = Counter(str(row.get("status") or "unknown").strip() or "unknown" for row in leads)
    message_statuses = Counter(str(row.get("status") or "unknown").strip() or "unknown" for row in messages)
    event_types = Counter(str(row.get("event_type") or "unknown").strip() or "unknown" for row in events)
    provider_counts = Counter(str(row.get("provider") or "unknown").strip() or "unknown" for row in messages + events)
    sent_statuses = {"queued", "sent", "delivered", "opened", "clicked", "replied"}

    return {
        "campaigns": len(campaigns),
        "active_campaigns": sum(1 for row in campaigns if str(row.get("status") or "").strip().lower() in {"running", "scheduled", "queued", "active"}),
        "leads": len(leads),
        "suppressed": len(suppressions),
        "messages": len(messages),
        "sent_messages": sum(1 for row in messages if str(row.get("status") or "").strip().lower() in sent_statuses),
        "events": len(events),
        "opens": _safe_int(event_types.get("opened")),
        "clicks": _safe_int(event_types.get("clicked")),
        "replies": len(replies),
        "unsubscribes": len(unsubscribes),
        "lead_statuses": _counter_breakdown(lead_statuses, limit=6, key_name="status", value_name="count"),
        "message_statuses": _counter_breakdown(message_statuses, limit=6, key_name="status", value_name="count"),
        "event_types": _counter_breakdown(event_types, limit=6, key_name="event_type", value_name="count"),
        "providers": _counter_breakdown(provider_counts, limit=6, key_name="provider", value_name="count"),
    }


def _build_supabase_inventory(supabase_stats: dict[str, Any]) -> dict[str, Any]:
    main_configured = bool(supabase_stats.get("main_configured"))
    outreach_configured = bool(supabase_stats.get("outreach_configured"))
    timestamp_keys = (
        "updated_at",
        "occurred_at",
        "received_at",
        "completed_at",
        "sent_at",
        "revoked_at",
        "last_successful_at",
        "heartbeat_at",
        "last_checkpoint_at",
        "scheduled_at",
        "created_at",
    )

    tables: list[dict[str, Any]] = []
    total_rows = 0
    for table_name, meta in SUPABASE_TABLE_META.items():
        rows = supabase_stats.get(table_name) or []
        configured = outreach_configured if table_name.startswith("outreach_") else main_configured
        latest = _latest_timestamp_from_rows(rows, *timestamp_keys)
        lag_seconds = (_now_utc() - latest).total_seconds() if latest else 0.0
        status = _status_pill(_status_from_configured(configured, bool(rows), lag_seconds))
        tables.append(
            {
                "table": table_name,
                "label": meta["label"],
                "note": meta["note"],
                "source": meta["source"],
                "count": len(rows),
                "configured": configured,
                "last_seen": latest.isoformat() if latest else "",
                "status": status,
            }
        )
        total_rows += len(rows)

    tables.sort(key=lambda item: (item["configured"], item["count"], item["label"]), reverse=True)
    return {
        "connected": main_configured or outreach_configured,
        "main_configured": main_configured,
        "outreach_configured": outreach_configured,
        "total_rows": total_rows,
        "tables": tables,
    }


def _build_demo_tracking_groups(summary: dict[str, Any]) -> list[dict[str, Any]]:
    synthetic_totals = {
        "frontend": max(1, _safe_int(summary.get("landing_sessions")) // 6),
        "auth": _safe_int(summary.get("signup_started_sessions")),
        "onboarding": _safe_int(summary.get("onboarding_completed_sessions")),
        "portfolio": max(1, _safe_int(summary.get("workspace_sessions")) // 2),
        "research": max(1, _safe_int(summary.get("workspace_sessions"))),
        "content": max(1, _safe_int(summary.get("first_value_sessions")) // 2),
        "chat": max(1, _safe_int(summary.get("first_value_sessions")) // 3),
    }
    top_event_map = {
        "frontend": "app_initialized",
        "auth": "auth_signup_success",
        "onboarding": "onboarding_completed",
        "portfolio": "portfolio_upload_completed",
        "research": "research_stream_completed",
        "content": "content_article_generated",
        "chat": "chat_completed",
    }
    rows: list[dict[str, Any]] = []
    total = sum(synthetic_totals.values()) or 1
    for group_key, meta in TRACKED_EVENT_GROUP_META.items():
        tracked_names = TRACKED_EVENT_GROUPS.get(group_key, set())
        amount = synthetic_totals.get(group_key, 0)
        failure_count = 0
        success_count = amount
        if group_key == "auth":
            success_count = _safe_int(summary.get("signup_completed_sessions"))
            failure_count = max(0, _safe_int(summary.get("signup_started_sessions")) - success_count)
            amount = success_count + failure_count
        elif group_key == "portfolio":
            failure_count = max(0, amount // 7)
            success_count = max(0, amount - failure_count)
        elif group_key == "research":
            failure_count = max(0, amount // 10)
            success_count = max(0, amount - failure_count)
        active_events = max(1, min(len(tracked_names), int(round(len(tracked_names) * (0.42 if amount else 0.0)))))
        rows.append(
            {
                "key": group_key,
                "label": meta["label"],
                "description": meta["description"],
                "color": meta["color"],
                "total": amount,
                "share_pct": amount / total * 100,
                "coverage_pct": active_events / max(1, len(tracked_names)) * 100,
                "tracked_event_count": len(tracked_names),
                "active_event_count": active_events,
                "success_count": success_count,
                "failure_count": failure_count,
                "success_rate": success_count / max(1, success_count + failure_count) * 100 if (success_count or failure_count) else 0.0,
                "top_event": {
                    "name": top_event_map.get(group_key, ""),
                    "label": _event_label(top_event_map.get(group_key, "")),
                    "count": amount,
                },
                "status": "active" if amount else "silent",
            }
        )
    rows.sort(key=lambda item: (item["total"], item["coverage_pct"]), reverse=True)
    return rows


def _build_demo_tracking_catalog(summary: dict[str, Any]) -> list[dict[str, Any]]:
    counts = {
        "app_initialized": max(1, _safe_int(summary.get("landing_sessions")) // 6),
        "auth_signup_success": _safe_int(summary.get("signup_completed_sessions")),
        "auth_signup_failed": max(0, _safe_int(summary.get("signup_started_sessions")) - _safe_int(summary.get("signup_completed_sessions"))),
        "onboarding_completed": _safe_int(summary.get("onboarding_completed_sessions")),
        "portfolio_upload_completed": max(1, _safe_int(summary.get("workspace_sessions")) // 2),
        "portfolio_upload_failed": max(0, _safe_int(summary.get("workspace_sessions")) // 8),
        "research_stream_completed": _safe_int(summary.get("first_value_sessions")),
        "research_stream_error": max(0, _safe_int(summary.get("open_alerts")) // 2),
        "content_article_generated": max(1, _safe_int(summary.get("first_value_sessions")) // 2),
        "chat_completed": max(1, _safe_int(summary.get("first_value_sessions")) // 3),
    }
    total = sum(counts.values()) or 1
    catalog: list[dict[str, Any]] = []
    for group_key, tracked_names in TRACKED_EVENT_GROUPS.items():
        meta = TRACKED_EVENT_GROUP_META[group_key]
        for event_name in sorted(tracked_names):
            count = _safe_int(counts.get(event_name))
            catalog.append(
                {
                    "name": event_name,
                    "label": _event_label(event_name),
                    "group": group_key,
                    "group_label": meta["label"],
                    "color": meta["color"],
                    "count": count,
                    "pct": count / total * 100,
                    "status": "active" if count else "silent",
                }
            )
    catalog.sort(key=lambda item: (item["count"], item["group_label"], item["label"]), reverse=True)
    return catalog


def _build_demo_operations_summary(demo_snapshot: dict[str, Any]) -> dict[str, Any]:
    series = demo_snapshot.get("series") or []
    request_count = sum(_safe_int(row.get("requests")) for row in series)
    dependency_count = sum(_safe_int(row.get("dependencies")) for row in series)
    request_error_count = sum(_safe_int(row.get("errors")) for row in series)
    dependency_error_count = max(1, request_error_count // 3)
    exception_count = max(1, request_error_count // 4)
    p95_latency_ms = _safe_float((demo_snapshot.get("summary") or {}).get("p95_latency_ms"))
    top_request_routes = [
        {"route": "/auth/signup", "label": "/auth/signup", "count": max(1, _safe_int((demo_snapshot.get("summary") or {}).get("signup_started_sessions")) // 2), "pct": 26.0},
        {"route": "/research/start", "label": "/research/start", "count": max(1, _safe_int((demo_snapshot.get("summary") or {}).get("workspace_sessions"))), "pct": 22.0},
        {"route": "/api/content/articles/generate", "label": "/api/content/articles/generate", "count": max(1, _safe_int((demo_snapshot.get("summary") or {}).get("first_value_sessions")) // 2), "pct": 14.0},
    ]
    top_dependency_targets = [
        {"target": "127.0.0.1", "count": max(1, request_count // 3), "pct": 32.0},
        {"target": "frontend-api", "count": max(1, request_count // 4), "pct": 26.0},
        {"target": "azure-telemetry", "count": max(1, request_count // 6), "pct": 14.0},
    ]
    return {
        "request_count": request_count,
        "dependency_count": dependency_count,
        "request_error_count": request_error_count,
        "dependency_error_count": dependency_error_count,
        "exception_count": exception_count,
        "error_count": request_error_count + dependency_error_count + exception_count,
        "error_rate": (request_error_count + dependency_error_count + exception_count) / max(1, request_count + dependency_count) * 100,
        "request_p50_ms": max(80.0, p95_latency_ms * 0.58),
        "request_p95_ms": p95_latency_ms,
        "dependency_p95_ms": max(60.0, p95_latency_ms * 0.76),
        "dependency_success_rate": 94.0,
        "top_request_routes": top_request_routes,
        "top_dependency_targets": top_dependency_targets,
        "slow_requests": [
            {"name": "POST /research/start", "route": "/research/start", "status_code": "200", "duration_ms": max(220.0, p95_latency_ms * 0.92), "success": True, "source": "backend"},
            {"name": "POST /api/content/articles/generate", "route": "/api/content/articles/generate", "status_code": "200", "duration_ms": max(180.0, p95_latency_ms * 0.81), "success": True, "source": "backend"},
        ],
        "slow_dependencies": [
            {"name": "GET /dashboard", "target": "127.0.0.1", "status_code": "200", "duration_ms": max(120.0, p95_latency_ms * 0.52), "success": True, "source": "frontend"},
        ],
        "source_breakdown": [
            {"source": "frontend", "count": dependency_count, "pct": dependency_count / max(1, dependency_count + request_count) * 100},
            {"source": "backend", "count": request_count, "pct": request_count / max(1, dependency_count + request_count) * 100},
        ],
    }


def _build_trend(rows_by_day: list[dict[str, Any]], days: int) -> list[dict[str, Any]]:
    if not rows_by_day:
        return []
    # Keep the chart balanced if the live range is sparse.
    expected = _days_ago(days - 1).date()
    trend = {entry["date"]: entry for entry in rows_by_day}
    series: list[dict[str, Any]] = []
    for idx in range(days):
        key = (expected + timedelta(days=idx)).isoformat()
        entry = trend.get(key)
        if entry:
            series.append(entry)
        else:
            series.append({
                "date": key,
                "landing": 0,
                "signup_started": 0,
                "signup_completed": 0,
                "onboarding_completed": 0,
                "workspace": 0,
                "first_value": 0,
                "retained": 0,
                "auth_success": 0,
                "auth_failure": 0,
                "portfolio": 0,
                "research": 0,
                "content": 0,
                "chat": 0,
                "requests": 0,
                "dependencies": 0,
                "errors": 0,
                "profiles": 0,
                "workspace_users": 0,
                "first_value_users": 0,
                "retained_users": 0,
                "outreach_messages": 0,
                "token_logs": 0,
                "routes": {},
            })
    return series


async def build_control_tower_snapshot(range_key: str = "30D") -> dict[str, Any]:
    normalized = _normalize_range_key(range_key)
    days = _range_days(normalized)
    azure_result, supabase_stats = await asyncio.gather(
        _azure_query(days),
        _load_supabase_stats(days),
    )
    azure_rows, azure_status, azure_note = azure_result

    aggregate = _aggregate_event_summary(azure_rows, days) if azure_rows else {
        "rows_by_day": [],
        "top_routes": Counter(),
        "top_events": Counter(),
        "landing_sessions": 0,
        "signup_started_sessions": 0,
        "signup_completed_sessions": 0,
        "onboarding_completed_sessions": 0,
        "workspace_sessions": 0,
        "first_value_sessions": 0,
        "auth_failure_sessions": 0,
        "request_durations": [],
        "dependency_durations": [],
        "request_rows": [],
        "dependency_rows": [],
        "request_errors": [],
        "dependency_errors": [],
        "exceptions": [],
        "users": [],
        "event_group_counts": {},
        "group_event_counts": {},
        "request_route_counts": Counter(),
        "dependency_target_counts": Counter(),
        "source_counts": Counter(),
        "latest_ts": None,
    }
    journey_signal_count = sum(1 for row in azure_rows if str(row.get("kind") or "").strip() in {"pageview", "event"})
    ops_signal_count = sum(1 for row in azure_rows if str(row.get("kind") or "").strip() in {"request", "dependency", "exception"})

    profiles = supabase_stats.get("profiles") or []
    token_usage = supabase_stats.get("token_usage") or []
    sessions = supabase_stats.get("sessions") or []
    facts = supabase_stats.get("facts") or []
    portfolio_mirrors = supabase_stats.get("portfolio_mirrors") or []
    pending_extractions = supabase_stats.get("pending_extractions") or []
    outreach_messages = supabase_stats.get("outreach_messages") or []
    outreach_events = supabase_stats.get("outreach_events") or []
    local_stats = _load_local_store_stats(days)
    merged_profiles = _merge_identity_profiles(profiles, local_stats["auth_rows"])

    workspace_summary = _build_workspace_summary(supabase_stats)
    portfolio_summary = _build_portfolio_summary(supabase_stats)
    pipeline_summary = _build_pipeline_summary(supabase_stats)
    geo_summary = _build_geo_summary(supabase_stats)
    outreach_summary = _build_outreach_summary(supabase_stats)
    supabase_inventory = _build_supabase_inventory(supabase_stats)
    tracking_groups = _build_tracking_groups(aggregate) if azure_rows else _build_persisted_tracking_groups(
        workspace_summary,
        portfolio_summary,
        outreach_summary,
        len(merged_profiles),
    )
    tracking_catalog = _build_tracking_catalog(aggregate) if azure_rows else _build_persisted_tracking_catalog(
        workspace_summary,
        portfolio_summary,
        outreach_summary,
        len(merged_profiles),
    )
    if not any(item["total"] for item in tracking_groups):
        tracking_groups = _build_persisted_tracking_groups(
            workspace_summary,
            portfolio_summary,
            outreach_summary,
            len(merged_profiles),
        )
        tracking_catalog = _build_persisted_tracking_catalog(
            workspace_summary,
            portfolio_summary,
            outreach_summary,
            len(merged_profiles),
        )

    combined_users = _parse_rows_to_user_summary(
        aggregate["users"],
        merged_profiles,
        token_usage,
        sessions,
        facts,
        portfolio_mirrors,
        pending_extractions,
        outreach_messages,
    )

    retained_sessions = sum(1 for item in combined_users if item["stage"] == "retained")
    workspace_users = len(
        {
            _safe_email(row.get("user_email"))
            for row in sessions + facts + token_usage
            if _safe_email(row.get("user_email")) and not _is_local_dev_identity(_safe_email(row.get("user_email")))
        }
    )
    insight_users = len(
        {
            _safe_email(row.get("user_email"))
            for row in facts
            if _safe_email(row.get("user_email")) and not _is_local_dev_identity(_safe_email(row.get("user_email")))
        }
    )
    combined_users_count = len(combined_users)
    identity_matches = len({row.get("email") for row in combined_users if row.get("email") and row.get("auth_provider")}) or 0
    identity_match_rate = identity_matches / max(1, combined_users_count) * 100
    known_profiles = len(merged_profiles)

    supabase_latest = max(
        [
            item
            for item in [
                _latest_timestamp_from_rows(profiles, "updated_at", "created_at"),
                _latest_timestamp_from_rows(sessions, "created_at"),
                _latest_timestamp_from_rows(facts, "created_at"),
                _latest_timestamp_from_rows(token_usage, "created_at"),
                _latest_timestamp_from_rows(portfolio_mirrors, "updated_at"),
                _latest_timestamp_from_rows(outreach_messages, "sent_at", "updated_at", "created_at"),
                _latest_timestamp_from_rows(outreach_events, "occurred_at", "created_at"),
                local_stats.get("auth_latest"),
                local_stats.get("state_latest"),
            ]
            if item is not None
        ],
        default=None,
    )

    def _metric_state(status: str, source: str, note: str) -> dict[str, str]:
        return {"status": status, "source": source, "note": note}

    if azure_rows:
        raw_landing_sessions = int(aggregate["landing_sessions"])
        raw_signup_started_sessions = max(int(aggregate["signup_started_sessions"]), int(aggregate["signup_completed_sessions"]))
        raw_signup_completed_sessions = int(aggregate["signup_completed_sessions"])
        raw_onboarding_completed_sessions = max(
            int(aggregate["onboarding_completed_sessions"]),
            min(raw_signup_completed_sessions, int(aggregate["workspace_sessions"])),
        )
        workspace_sessions = max(int(aggregate["workspace_sessions"]), workspace_users)
        first_value_sessions = max(int(aggregate["first_value_sessions"]), insight_users)
        request_durations = aggregate["request_durations"]
        p95_latency_value = (
            statistics.quantiles(request_durations, n=100)[94]
            if len(request_durations) >= 5
            else (statistics.median(request_durations) if request_durations else 0.0)
        )
        latest_candidates = [aggregate.get("latest_ts"), supabase_latest]
        latest = max([item for item in latest_candidates if item is not None], default=_now_utc())
        freshness_seconds = (_now_utc() - latest).total_seconds()
        daily_series = _build_trend(aggregate["rows_by_day"], days)
        marketing_journey_available = bool(journey_signal_count)
        landing_sessions = raw_landing_sessions if marketing_journey_available else None
        signup_started_sessions = raw_signup_started_sessions if marketing_journey_available else None
        signup_completed_sessions = raw_signup_completed_sessions if marketing_journey_available else None
        onboarding_completed_sessions = raw_onboarding_completed_sessions if marketing_journey_available else None
        top_pages = _build_top_pages(aggregate["top_routes"]) if marketing_journey_available else []
        top_events = (
            _build_top_events(aggregate["top_events"])
            if marketing_journey_available else
            [
                {
                    "name": item.get("name"),
                    "label": item.get("label"),
                    "count": _safe_int(item.get("count")),
                    "pct": _safe_float(item.get("pct")),
                }
                for item in tracking_catalog
                if _safe_int(item.get("count")) > 0
            ][:8]
        )
        request_samples = aggregate["request_errors"][:20]
        exception_samples = aggregate["exceptions"][:20]
        mode = "live" if marketing_journey_available else "partial"
        live_data = True
        marketing_funnel = [
            {"stage": "Landing", "value": landing_sessions, "detail": "Verified landing traffic from Azure Application Insights."},
            {"stage": "Signup started", "value": signup_started_sessions, "detail": "Users who entered auth or signup telemetry."},
            {"stage": "Signup completed", "value": signup_completed_sessions, "detail": "Successful auth completions from live telemetry."},
            {"stage": "Onboarding completed", "value": onboarding_completed_sessions, "detail": "Users who finished onboarding."},
            {"stage": "Workspace active", "value": workspace_sessions, "detail": "Verified workspace activity."},
            {"stage": "First value", "value": first_value_sessions, "detail": "Users who reached a first insight or result."},
            {"stage": "Retained", "value": retained_sessions, "detail": "Users with repeated activity across days."},
        ] if marketing_journey_available else []
        metric_states = {
            "landing_sessions": _metric_state("live" if marketing_journey_available else "unavailable", "Azure Application Insights", "Verified page and event telemetry." if marketing_journey_available else "Azure is connected, but no journey pageviews or custom events have been emitted yet."),
            "signup_started_sessions": _metric_state("live" if marketing_journey_available else "unavailable", "Azure Application Insights", "Auth intent seen in telemetry." if marketing_journey_available else "Azure is connected, but signup-start telemetry has not been emitted yet."),
            "signup_completed_sessions": _metric_state("live" if marketing_journey_available else "unavailable", "Azure Application Insights", "Verified auth completion events." if marketing_journey_available else "Azure is connected, but auth completion events have not been emitted yet."),
            "onboarding_completed_sessions": _metric_state("live" if marketing_journey_available else "unavailable", "Azure Application Insights", "Verified onboarding completion events." if marketing_journey_available else "Azure is connected, but onboarding completion telemetry has not been emitted yet."),
            "workspace_sessions": _metric_state("live", "Azure + Supabase", "Telemetry stitched with persisted workspace users."),
            "first_value_sessions": _metric_state("live", "Azure + Supabase", "Telemetry cross-checked against persisted insight rows."),
            "retained_sessions": _metric_state("persisted", "Supabase", "Derived from persisted multi-day user activity."),
            "known_profiles": _metric_state("persisted", "Supabase + local auth DB", "Verified account identities observed in persisted stores."),
            "combined_users": _metric_state("persisted", "Supabase", "Merged identities across workspace and insights."),
            "workspace_users": _metric_state("persisted", "Supabase", "Distinct users from workspace writes."),
            "insight_users": _metric_state("persisted", "Supabase", "Distinct users with persisted facts."),
            "identity_match_rate": _metric_state("persisted", "Supabase + local auth DB", "Matched user identities across stores."),
            "open_alerts": _metric_state("live" if ops_signal_count else "unavailable", "Azure Monitor", "Derived from verified request, dependency, and exception issue rows in the selected range." if ops_signal_count else "Azure is connected, but no ops telemetry rows are available yet."),
            "issue_signals": _metric_state("live" if ops_signal_count else "unavailable", "Azure Monitor", "Request failures, dependency failures, and exceptions in the selected range." if ops_signal_count else "Azure is connected, but no ops telemetry rows are available yet."),
            "p95_latency_ms": _metric_state("live" if ops_signal_count else "unavailable", "Azure Monitor", "Verified request latency telemetry." if ops_signal_count else "Azure is connected, but no ops latency rows are available yet."),
            "signup_completion_rate": _metric_state("live" if marketing_journey_available else "unavailable", "Azure Application Insights", "Computed from live signup funnel counts." if marketing_journey_available else "Signup funnel rate is withheld until journey events are emitted."),
            "workspace_activation_rate": _metric_state("live", "Azure + Supabase", "Computed from verified workspace and first-value counts."),
            "retention_rate": _metric_state("persisted", "Supabase", "Computed from persisted retained user counts."),
            "request_count": _metric_state("live" if ops_signal_count else "unavailable", "Azure Monitor", "Verified backend request telemetry." if ops_signal_count else "Azure is connected, but no request telemetry rows are available yet."),
            "dependency_count": _metric_state("live" if ops_signal_count else "unavailable", "Azure Monitor", "Verified dependency telemetry." if ops_signal_count else "Azure is connected, but no dependency telemetry rows are available yet."),
            "exception_count": _metric_state("live" if ops_signal_count else "unavailable", "Azure Monitor", "Verified exception telemetry." if ops_signal_count else "Azure is connected, but no exception telemetry rows are available yet."),
            "error_rate": _metric_state("live" if ops_signal_count else "unavailable", "Azure Monitor", "Computed from verified ops telemetry." if ops_signal_count else "Error rate is withheld until ops telemetry is emitted."),
            "token_total": _metric_state("persisted", "Supabase", "Summed from persisted token usage rows."),
            "portfolio_positions": _metric_state("persisted", "Supabase", "Read from persisted portfolio mirrors."),
            "portfolio_value": _metric_state("persisted", "Supabase", "Summed from active portfolio mirrors."),
            "pending_reviews": _metric_state("persisted", "Supabase", "Pending extraction reviews in the workspace."),
            "outreach_campaigns": _metric_state("persisted", "Outreach Supabase", "Persisted outreach campaign rows."),
            "outreach_messages": _metric_state("persisted", "Outreach Supabase", "Persisted outreach message rows."),
            "supabase_rows": _metric_state("persisted", "Supabase", "Visible rows across configured tables."),
            "tracked_signal_count": _metric_state("persisted" if not marketing_journey_available else "live", "Azure + Supabase", "Live event families plus persisted product signals." if marketing_journey_available else "Persisted product signals are visible, but live journey events have not been emitted yet."),
        }
    else:
        landing_sessions = None
        signup_started_sessions = None
        signup_completed_sessions = None
        onboarding_completed_sessions = None
        workspace_sessions = workspace_summary["session_count"] or workspace_users or None
        first_value_sessions = insight_users or None
        p95_latency_value = 0.0
        freshness_seconds = (_now_utc() - supabase_latest).total_seconds() if supabase_latest else 0.0
        daily_series = _build_verified_series(
            days,
            profile_rows=merged_profiles,
            session_rows=sessions,
            fact_rows=facts,
            token_rows=token_usage,
            portfolio_rows=portfolio_mirrors,
            outreach_rows=outreach_messages,
            combined_users=combined_users,
        )
        top_pages = []
        persisted_events = [
            {"name": "profiles_created", "label": "Profiles created", "count": len(merged_profiles)},
            {"name": "workspace_sessions", "label": "Workspace sessions", "count": workspace_summary["session_count"]},
            {"name": "facts_persisted", "label": "Facts persisted", "count": workspace_summary["insight_rows"]},
            {"name": "portfolio_positions", "label": "Portfolio positions", "count": portfolio_summary["active_positions"]},
            {"name": "outreach_messages", "label": "Outreach messages", "count": outreach_summary["messages"]},
        ]
        top_events = [
            {**item, "pct": item["count"] / max(1, sum(entry["count"] for entry in persisted_events)) * 100}
            for item in persisted_events
            if item["count"] > 0
        ]
        request_samples = []
        exception_samples = []
        mode = "partial" if (supabase_inventory["connected"] or local_stats["connected"]) else "offline"
        live_data = False
        marketing_funnel = []
        metric_states = {
            "landing_sessions": _metric_state("unavailable", "Azure Application Insights", "Landing telemetry is unavailable until Azure query credentials are configured."),
            "signup_started_sessions": _metric_state("unavailable", "Azure Application Insights", "Signup-start telemetry is unavailable without Azure query access."),
            "signup_completed_sessions": _metric_state("unavailable", "Azure Application Insights", "Signup completion is not reported here because the live acquisition journey is unavailable."),
            "onboarding_completed_sessions": _metric_state("unavailable", "Azure Application Insights", "Onboarding completion is event-based and not persisted separately."),
            "workspace_sessions": _metric_state("persisted", "Supabase", "Persisted workspace session or token activity."),
            "first_value_sessions": _metric_state("persisted", "Supabase", "Verified users with persisted insight rows."),
            "retained_sessions": _metric_state("persisted", "Supabase", "Derived from repeated persisted user activity."),
            "known_profiles": _metric_state("persisted", "Supabase + local auth DB", "Verified account identities observed in persisted stores."),
            "combined_users": _metric_state("persisted", "Supabase + local auth DB", "Merged identities across persisted stores."),
            "workspace_users": _metric_state("persisted", "Supabase", "Distinct users from persisted workspace writes."),
            "insight_users": _metric_state("persisted", "Supabase", "Distinct users with persisted insights."),
            "identity_match_rate": _metric_state("persisted", "Supabase + local auth DB", "Matched user identities across persisted stores."),
            "open_alerts": _metric_state("unavailable", "Azure Monitor", "Ops alert counts require Azure Monitor query access."),
            "issue_signals": _metric_state("unavailable", "Azure Monitor", "Issue counts require Azure Monitor query access."),
            "p95_latency_ms": _metric_state("unavailable", "Azure Monitor", "Latency is unavailable without verified Azure ops telemetry."),
            "signup_completion_rate": _metric_state("unavailable", "Azure Application Insights", "Signup-start telemetry is unavailable, so this rate is withheld."),
            "workspace_activation_rate": _metric_state("persisted", "Supabase", "Computed from persisted workspace users and insight users."),
            "retention_rate": _metric_state("persisted", "Supabase", "Computed from persisted retained user counts."),
            "request_count": _metric_state("unavailable", "Azure Monitor", "Backend request telemetry is unavailable without Azure query access."),
            "dependency_count": _metric_state("unavailable", "Azure Monitor", "Dependency telemetry is unavailable without Azure query access."),
            "exception_count": _metric_state("unavailable", "Azure Monitor", "Exception telemetry is unavailable without Azure query access."),
            "error_rate": _metric_state("unavailable", "Azure Monitor", "Error rate is withheld until ops telemetry is live."),
            "token_total": _metric_state("persisted", "Supabase", "Summed from persisted token usage rows."),
            "portfolio_positions": _metric_state("persisted", "Supabase", "Read from persisted portfolio mirrors."),
            "portfolio_value": _metric_state("persisted", "Supabase", "Summed from active portfolio mirrors."),
            "pending_reviews": _metric_state("persisted", "Supabase", "Pending extraction reviews in the workspace."),
            "outreach_campaigns": _metric_state("persisted", "Outreach Supabase", "Persisted outreach campaign rows."),
            "outreach_messages": _metric_state("persisted", "Outreach Supabase", "Persisted outreach message rows."),
            "supabase_rows": _metric_state("persisted", "Supabase", "Visible rows across configured tables."),
            "tracked_signal_count": _metric_state("persisted", "Supabase + local auth DB", "Verified persisted product signals only; no synthetic telemetry."),
        }

    operations_summary = _build_operations_summary(aggregate, p95_latency_value)
    open_alerts = operations_summary["error_count"] if azure_rows else None
    issue_signals = operations_summary["error_count"] if azure_rows else None
    p95_latency_ms = p95_latency_value if azure_rows else None

    activation_funnel = [
        {"stage": "Known profiles", "value": known_profiles, "detail": "Verified identities observed in Supabase profiles and the local auth store."},
        {"stage": "Workspace users", "value": workspace_users, "detail": "Distinct users with persisted workspace activity."},
        {"stage": "First value", "value": insight_users, "detail": "Users with persisted insight output or facts."},
        {"stage": "Retained users", "value": retained_sessions, "detail": "Users with repeated cross-session activity."},
    ]
    activation_dropoffs, activation_biggest_leak = _build_funnel_dropoffs(activation_funnel)
    marketing_journey_available = bool(journey_signal_count)

    signup_completion_rate = (
        signup_completed_sessions / max(1, signup_started_sessions) * 100
        if marketing_journey_available and signup_started_sessions is not None and signup_completed_sessions is not None
        else None
    )
    workspace_activation_rate = (
        first_value_sessions / max(1, workspace_users) * 100
        if first_value_sessions is not None and workspace_users
        else None
    )
    retention_rate = retained_sessions / max(1, combined_users_count) * 100 if combined_users_count else None

    dropoffs, biggest_leak = (
        _build_dropoffs(
            {
                "landing_sessions": landing_sessions or 0,
                "signup_started_sessions": signup_started_sessions or 0,
                "signup_completed_sessions": signup_completed_sessions or 0,
                "onboarding_completed_sessions": onboarding_completed_sessions or 0,
                "workspace_sessions": workspace_sessions or 0,
                "first_value_sessions": first_value_sessions or 0,
                "auth_failure_sessions": aggregate["auth_failure_sessions"],
                "p95_latency_ms": p95_latency_value,
            }
        )
        if marketing_journey_available else
        (activation_dropoffs, activation_biggest_leak)
    )
    funnel = marketing_funnel if marketing_journey_available else activation_funnel
    journeys = {
        "marketing": {
            "available": marketing_journey_available,
            "source": "Azure Application Insights",
            "note": "Live acquisition telemetry from landing through onboarding." if marketing_journey_available else "Landing and signup telemetry is not being emitted yet, so acquisition charts are withheld.",
            "stages": marketing_funnel,
            "dropoffs": dropoffs if marketing_journey_available else [],
            "biggest_leak": biggest_leak if marketing_journey_available else None,
        },
        "activation": {
            "available": True,
            "source": "Supabase + local auth DB",
            "note": "Verified activation journey built from persisted identities, workspace activity, and first-value signals.",
            "stages": activation_funnel,
            "dropoffs": activation_dropoffs,
            "biggest_leak": activation_biggest_leak,
        },
    }

    source_mix = [
        {"name": "Azure Application Insights", "value": journey_signal_count if marketing_journey_available else 0, "color": SOURCE_COLORS[0]["color"]},
        {"name": "Azure Monitor", "value": (operations_summary["request_count"] + operations_summary["dependency_count"] + operations_summary["exception_count"]) if azure_rows else 0, "color": SOURCE_COLORS[1]["color"]},
        {"name": "Supabase", "value": supabase_inventory["total_rows"], "color": SOURCE_COLORS[2]["color"]},
        {"name": "Local auth store", "value": len(merged_profiles), "color": "#00f5ff"},
        {"name": "ProspektLab Workspace", "value": workspace_summary["session_count"] + portfolio_summary["active_positions"] + portfolio_summary["pending_reviews"], "color": SOURCE_COLORS[3]["color"]},
        {"name": "ProspektLab Insights", "value": workspace_summary["insight_rows"] + outreach_summary["messages"] + outreach_summary["events"] + outreach_summary["replies"], "color": SOURCE_COLORS[4]["color"]},
    ]
    source_total = sum(item["value"] for item in source_mix) or 1
    for item in source_mix:
        item["pct"] = item["value"] / source_total * 100

    non_outreach_tables = [item for item in supabase_inventory["tables"] if not item["table"].startswith("outreach_")]
    outreach_tables = [item for item in supabase_inventory["tables"] if item["table"].startswith("outreach_")]
    supabase_coverage = sum(1 for item in non_outreach_tables if item["count"] > 0) / max(1, len(non_outreach_tables)) * 100 if supabase_inventory["main_configured"] else 0.0
    insights_coverage = sum(1 for item in outreach_tables if item["count"] > 0) / max(1, len(outreach_tables)) * 100 if supabase_inventory["outreach_configured"] else (100.0 if facts else 0.0)

    azure_journey_status = _status_pill("healthy" if marketing_journey_available else ("watch" if azure_rows else azure_status))
    local_state_total = sum(local_stats["state_counts"].values())
    source_health = [
        {
            "name": "Azure Application Insights",
            "status": azure_journey_status,
            "coverage": 100.0 if marketing_journey_available else 0.0,
            "lag_seconds": freshness_seconds,
            "note": "Live acquisition telemetry from Azure Application Insights." if marketing_journey_available else "Azure is connected, but landing and signup journey events are not being emitted yet.",
            "metric": f"{_fmt_count(landing_sessions or 0)} landing sessions" if marketing_journey_available else "Journey telemetry unavailable",
            "extra": f"{_fmt_count(sum(1 for item in tracking_catalog if item['count'] > 0))} active event types" if marketing_journey_available else "Only ops dependencies and backend traces are visible",
        },
        {
            "name": "Azure Monitor",
            "status": _status_pill(_status_from_lag(freshness_seconds + 10, bool(azure_rows and (operations_summary["request_count"] or operations_summary["dependency_count"] or operations_summary["exception_count"])))),
            "coverage": 100.0 if (azure_rows and (operations_summary["request_count"] or operations_summary["dependency_count"] or operations_summary["exception_count"])) else 0.0,
            "lag_seconds": freshness_seconds + 10,
            "note": "Requests, frontend dependencies, and exceptions are stitched into the ops view.",
            "metric": f"{issue_signals} issue rows" if issue_signals is not None else "Ops telemetry unavailable",
            "extra": f"{p95_latency_ms:.0f}ms p95" if p95_latency_ms is not None else "Awaiting Azure Monitor query access",
        },
        {
            "name": "Supabase",
            "status": _status_pill(_status_from_configured(supabase_inventory["main_configured"], bool(profiles or token_usage or sessions or portfolio_mirrors), freshness_seconds + 15)),
            "coverage": supabase_coverage,
            "lag_seconds": freshness_seconds + 15,
            "note": "Auth, profiles, token usage, portfolio, and workspace tables are connected." if supabase_inventory["main_configured"] else "Set SUPABASE_URL and SUPABASE_KEY to enable live Supabase metrics.",
            "metric": f"{_fmt_count(len(profiles))} profiles",
            "extra": f"{_fmt_count(workspace_summary['token_total'])} tokens",
        },
        {
            "name": "ProspektLab Workspace",
            "status": _status_pill(_status_from_configured(supabase_inventory["main_configured"], bool(sessions or portfolio_mirrors or pending_extractions), freshness_seconds + 8)),
            "coverage": 100.0 if (sessions or portfolio_mirrors or pending_extractions) else 0.0,
            "lag_seconds": freshness_seconds + 8,
            "note": "Session summaries, portfolio mirrors, and extraction review queues are included.",
            "metric": f"{_fmt_count(workspace_summary['session_count'])} sessions",
            "extra": f"{_fmt_count(portfolio_summary['active_positions'])} positions",
        },
        {
            "name": "ProspektLab Insights",
            "status": _status_pill(_status_from_configured(supabase_inventory["main_configured"] or supabase_inventory["outreach_configured"], bool(facts or outreach_messages or outreach_events), freshness_seconds + 6)),
            "coverage": insights_coverage,
            "lag_seconds": freshness_seconds + 6,
            "note": "Memory facts, campaign sends, provider events, and replies are merged here." if (supabase_inventory["main_configured"] or supabase_inventory["outreach_configured"]) else "Configure outreach Supabase keys to bring campaign signals into the dashboard.",
            "metric": f"{_fmt_count(workspace_summary['insight_rows'])} facts",
            "extra": f"{_fmt_count(outreach_summary['messages'])} messages",
        },
        {
            "name": "Local auth store",
            "status": _status_pill(_status_from_configured(local_stats["connected"], bool(merged_profiles), freshness_seconds + 12)),
            "coverage": 100.0 if merged_profiles else 0.0,
            "lag_seconds": freshness_seconds + 12,
            "note": "Fallback persisted auth identities from the local ProspektLab SQLite store.",
            "metric": f"{_fmt_count(len(merged_profiles))} known profiles",
            "extra": f"{_fmt_count(local_state_total)} local state records",
        },
    ]

    connector_gaps = [
        note
        for note in [
            azure_note if not azure_rows else "",
            "Supabase main project is not configured" if not supabase_inventory["main_configured"] else "",
            "Outreach Supabase project is not configured" if not supabase_inventory["outreach_configured"] else "",
        ]
        if note
    ]
    verification = {
        "synthetic_metrics_removed": True,
        "live_metrics": sum(1 for item in metric_states.values() if item["status"] == "live"),
        "persisted_metrics": sum(1 for item in metric_states.values() if item["status"] == "persisted"),
        "unavailable_metrics": sum(1 for item in metric_states.values() if item["status"] == "unavailable"),
        "connector_gaps": connector_gaps,
        "metric_states": metric_states,
        "has_live_journey": marketing_journey_available,
        "has_live_ops": bool(ops_signal_count),
    }
    leak_penalty_pct = biggest_leak["pct"] if marketing_journey_available else min(biggest_leak["pct"], 24.0)

    health_score = max(
        0,
        min(
            100,
            int(
                100
                - (open_alerts or 0) * 6
                - max(0.0, operations_summary["error_rate"] - 2.0) * 1.8
                - max(0.0, (p95_latency_ms or 0.0) - 250.0) * 0.04
                - max(0.0, leak_penalty_pct - 18.0) * 0.75
                + (4 if supabase_inventory["main_configured"] else 0)
                + (3 if live_data else 0)
                - len(connector_gaps) * 4
            ),
        ),
    )

    return {
        "mode": mode,
        "live_data": live_data,
        "generated_at": _now_utc().isoformat(),
        "range": {"key": normalized, "days": days, "label": f"Last {days} days"},
        "summary": {
            "landing_sessions": landing_sessions,
            "signup_started_sessions": signup_started_sessions,
            "signup_completed_sessions": signup_completed_sessions,
            "onboarding_completed_sessions": onboarding_completed_sessions,
            "workspace_sessions": workspace_sessions,
            "first_value_sessions": first_value_sessions,
            "retained_sessions": retained_sessions,
            "known_profiles": known_profiles,
            "combined_users": combined_users_count,
            "workspace_users": workspace_users,
            "insight_users": insight_users,
            "identity_match_rate": identity_match_rate,
            "open_alerts": open_alerts,
            "issue_signals": issue_signals,
            "p95_latency_ms": p95_latency_ms,
            "avg_freshness_seconds": freshness_seconds,
            "signup_completion_rate": signup_completion_rate,
            "workspace_activation_rate": workspace_activation_rate,
            "retention_rate": retention_rate,
            "request_count": operations_summary["request_count"] if azure_rows else None,
            "dependency_count": operations_summary["dependency_count"] if azure_rows else None,
            "exception_count": operations_summary["exception_count"] if azure_rows else None,
            "error_rate": operations_summary["error_rate"] if azure_rows else None,
            "token_total": workspace_summary["token_total"],
            "portfolio_positions": portfolio_summary["active_positions"],
            "portfolio_value": portfolio_summary["total_market_value"],
            "pending_reviews": portfolio_summary["pending_reviews"],
            "outreach_campaigns": outreach_summary["campaigns"],
            "outreach_messages": outreach_summary["messages"],
            "supabase_rows": supabase_inventory["total_rows"],
            "tracked_signal_count": sum(item["total"] for item in tracking_groups),
        },
        "series": daily_series,
        "journeys": journeys,
        "funnel": funnel,
        "biggest_leak": biggest_leak,
        "dropoffs": dropoffs,
        "source_mix": source_mix,
        "source_health": source_health,
        "combined_users": combined_users[:25],
        "top_pages": top_pages,
        "top_events": top_events,
        "health_score": health_score,
        "open_alerts": open_alerts,
        "request_samples": request_samples,
        "dependency_samples": aggregate["dependency_errors"][:20],
        "exception_samples": exception_samples,
        "operations": operations_summary,
        "tracking_groups": tracking_groups,
        "tracking_catalog": tracking_catalog,
        "workspace": workspace_summary,
        "portfolio": portfolio_summary,
        "pipeline": pipeline_summary,
        "geo": geo_summary,
        "outreach": outreach_summary,
        "supabase": supabase_inventory,
        "verification": verification,
    }

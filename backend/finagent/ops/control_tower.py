from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import random
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

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
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
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
        series.append({
            "date": (base_date + timedelta(days=idx)).isoformat(),
            "landing": landing,
            "signup_started": signup,
            "signup_completed": signup_completed,
            "onboarding_completed": onboarding,
            "workspace": workspace,
            "first_value": first_value,
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
        "tenant_id": _env_string("CONTROL_TOWER_AZURE_TENANT_ID", "AZURE_TENANT_ID"),
        "client_id": _env_string("CONTROL_TOWER_AZURE_CLIENT_ID", "AZURE_CLIENT_ID"),
        "client_secret": _env_string("CONTROL_TOWER_AZURE_CLIENT_SECRET", "AZURE_CLIENT_SECRET"),
        "bearer_token": _env_string("CONTROL_TOWER_AZURE_BEARER_TOKEN"),
        "scope": resource_scope,
    }


_azure_token_lock = asyncio.Lock()
_azure_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}


async def _get_azure_token(config: dict[str, Any]) -> str | None:
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


async def _azure_query(days: int) -> tuple[list[dict[str, Any]], str, str]:
    config = _azure_config()
    if not config.get("enabled"):
        return [], "disabled", "Azure query URL not configured"

    token = await _get_azure_token(config)
    if not token:
        return [], "warn", "Azure credentials missing or incomplete"

    query = _azure_query_text(days)
    timeout = httpx.Timeout(30.0, connect=8.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=_env_bool("FINAGENT_HTTP_TRUST_ENV")) as client:
            response = await client.post(
                str(config["query_url"]),
                json={"query": query},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.warning("Azure control tower query failed: %s", exc)
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


def _aggregate_event_summary(rows: list[dict[str, Any]], range_days: int) -> dict[str, Any]:
    route_daily: dict[str, dict[str, int]] = defaultdict(lambda: {"views": 0, "sessions": 0})
    event_daily: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0})
    top_routes: Counter[str] = Counter()
    top_events: Counter[str] = Counter()
    landing_sessions: set[str] = set()
    signup_sessions: set[str] = set()
    signup_completed_sessions: set[str] = set()
    onboarding_sessions: set[str] = set()
    workspace_sessions: set[str] = set()
    first_value_sessions: set[str] = set()
    auth_failure_sessions: set[str] = set()
    user_signals: dict[str, dict[str, Any]] = {}
    request_durations: list[float] = []
    request_errors: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    latest_ts: datetime | None = None

    for row in rows:
        ts = _parse_dt(row.get("timestamp"))
        if not ts:
            continue
        latest_ts = max(latest_ts, ts) if latest_ts else ts
        kind = str(row.get("kind") or "").lower()
        event_name = str(row.get("event_name") or "").strip()
        route = str(row.get("route") or "").strip().lower()
        email = _safe_email(row.get("user_email"))
        session_id = str(row.get("session_id") or "").strip()
        source = str(row.get("source") or "").strip().lower() or ("frontend" if kind == "pageview" else "backend")
        duration_ms = _duration_to_ms(row.get("duration_text"))
        success = bool(row.get("success")) if row.get("success") is not None else True
        status_code = str(row.get("status_code") or "").strip()

        if kind == "pageview":
            key = route or "/"
            top_routes[key] += 1
            route_daily[f"{ts.date().isoformat()}::{key}"]["views"] += 1
            if session_id:
                route_daily[f"{ts.date().isoformat()}::{key}"]["sessions"] = route_daily[f"{ts.date().isoformat()}::{key}"].get("sessions", 0) + 1
            if key in LANDING_ROUTES:
                if session_id:
                    landing_sessions.add(session_id)
            if key in SIGNUP_ROUTES and session_id:
                signup_sessions.add(session_id)
            if key in ONBOARDING_ROUTES and session_id:
                onboarding_sessions.add(session_id)
            if key in WORKSPACE_ROUTES and session_id:
                workspace_sessions.add(session_id)

        elif kind == "event":
            top_events[event_name] += 1
            event_daily[f"{ts.date().isoformat()}::{event_name}"]["count"] += 1
            if session_id and event_name in SIGNUP_SUCCESS_EVENTS | SIGNUP_FAILURE_EVENTS:
                signup_sessions.add(session_id)
            if session_id and event_name in SIGNUP_SUCCESS_EVENTS:
                signup_completed_sessions.add(session_id)
            if session_id and event_name in ONBOARDING_EVENTS:
                onboarding_sessions.add(session_id)
            if session_id and event_name in WORKSPACE_EVENTS:
                workspace_sessions.add(session_id)
            if session_id and event_name in INSIGHT_EVENTS:
                first_value_sessions.add(session_id)
            if session_id and event_name in SIGNUP_FAILURE_EVENTS:
                auth_failure_sessions.add(session_id)

            if email:
                bucket = user_signals.setdefault(email, {
                    "email": email,
                    "name": email.split("@", 1)[0].replace(".", " ").replace("_", " ").title(),
                    "landing_sessions": 0,
                    "signup_started_sessions": 0,
                    "signup_completed_sessions": 0,
                    "onboarding_sessions": 0,
                    "workspace_sessions": 0,
                    "first_value_sessions": 0,
                    "failed_auth_sessions": 0,
                    "active_days": set(),
                    "sources": set(),
                    "last_seen": ts,
                    "first_seen": ts,
                    "total_events": 0,
                })
                bucket["total_events"] += 1
                bucket["sources"].add(source)
                bucket["last_seen"] = max(bucket["last_seen"], ts)
                bucket["first_seen"] = min(bucket["first_seen"], ts)
                bucket["active_days"].add(ts.date().isoformat())
                if event_name in SIGNUP_SUCCESS_EVENTS:
                    bucket["signup_completed_sessions"] += 1
                if event_name in SIGNUP_FAILURE_EVENTS:
                    bucket["failed_auth_sessions"] += 1
                if event_name in ONBOARDING_EVENTS:
                    bucket["onboarding_sessions"] += 1
                if event_name in WORKSPACE_EVENTS:
                    bucket["workspace_sessions"] += 1
                if event_name in INSIGHT_EVENTS:
                    bucket["first_value_sessions"] += 1
                if event_name in SIGNUP_SUCCESS_EVENTS | SIGNUP_FAILURE_EVENTS:
                    bucket["signup_started_sessions"] += 1

        elif kind == "request":
            if duration_ms > 0:
                request_durations.append(duration_ms)
            if not success or status_code.startswith("5"):
                request_errors.append({
                    "timestamp": ts.isoformat(),
                    "name": event_name,
                    "route": route,
                    "status_code": status_code,
                })
            if session_id:
                bucket = user_signals.setdefault(email or session_id, {
                    "email": email or session_id,
                    "name": (email.split("@", 1)[0].replace(".", " ").replace("_", " ").title() if email else session_id[:8]),
                    "landing_sessions": 0,
                    "signup_started_sessions": 0,
                    "signup_completed_sessions": 0,
                    "onboarding_sessions": 0,
                    "workspace_sessions": 0,
                    "first_value_sessions": 0,
                    "failed_auth_sessions": 0,
                    "active_days": set(),
                    "sources": set(),
                    "last_seen": ts,
                    "first_seen": ts,
                    "total_events": 0,
                })
                bucket["sources"].add(source)
                bucket["last_seen"] = max(bucket["last_seen"], ts)
                bucket["first_seen"] = min(bucket["first_seen"], ts)
                bucket["active_days"].add(ts.date().isoformat())

        elif kind == "exception":
            exceptions.append({
                "timestamp": ts.isoformat(),
                "name": event_name,
                "route": route,
                "message": str(row.get("message") or ""),
            })
            if session_id:
                auth_failure_sessions.add(session_id)

    daily_rows: dict[str, dict[str, Any]] = {}
    for key, counters in route_daily.items():
        date, route = key.split("::", 1)
        row = daily_rows.setdefault(date, {"date": date, "landing": 0, "signup_started": 0, "signup_completed": 0, "onboarding_completed": 0, "workspace": 0, "first_value": 0, "errors": 0, "routes": {}})
        row["routes"][route] = counters["views"]
        if route in LANDING_ROUTES:
            row["landing"] += counters["sessions"] or counters["views"]
        if route in SIGNUP_ROUTES:
            row["signup_started"] += counters["sessions"] or counters["views"]
        if route in ONBOARDING_ROUTES:
            row["onboarding_completed"] += counters["sessions"] or counters["views"]
        if route in WORKSPACE_ROUTES:
            row["workspace"] += counters["sessions"] or counters["views"]

    for key, counters in event_daily.items():
        date, event_name = key.split("::", 1)
        row = daily_rows.setdefault(date, {"date": date, "landing": 0, "signup_started": 0, "signup_completed": 0, "onboarding_completed": 0, "workspace": 0, "first_value": 0, "errors": 0, "routes": {}})
        if event_name in SIGNUP_SUCCESS_EVENTS:
            row["signup_completed"] += counters["count"]
            row["signup_started"] += counters["count"]
        if event_name in ONBOARDING_EVENTS:
            row["onboarding_completed"] += counters["count"]
        if event_name in WORKSPACE_EVENTS:
            row["workspace"] += counters["count"]
        if event_name in INSIGHT_EVENTS:
            row["first_value"] += counters["count"]
        if event_name in SIGNUP_FAILURE_EVENTS:
            row["signup_started"] += counters["count"]
            row["errors"] += counters["count"]

    rows_by_day = []
    for date in sorted(daily_rows):
        entry = daily_rows[date]
        if entry["signup_started"] < entry["signup_completed"]:
            entry["signup_started"] = entry["signup_completed"]
        if entry["onboarding_completed"] < min(entry["signup_completed"], entry["workspace"]):
            entry["onboarding_completed"] = min(entry["signup_completed"], entry["workspace"])
        rows_by_day.append(entry)

    user_rows = []
    for email, bucket in user_signals.items():
        active_days = len(bucket["active_days"])
        signup_started = bucket["signup_started_sessions"]
        signup_completed = bucket["signup_completed_sessions"]
        onboarding = bucket["onboarding_sessions"]
        workspace = bucket["workspace_sessions"]
        first_value = bucket["first_value_sessions"]
        landing = bucket["landing_sessions"]
        retained = 1 if active_days >= 2 or first_value > 0 and active_days >= 1 else 0
        stage, action = _choose_stage({
            "landing_sessions": landing,
            "signup_started_sessions": signup_started,
            "signup_completed_sessions": signup_completed,
            "onboarding_sessions": onboarding,
            "workspace_sessions": workspace,
            "first_value_sessions": first_value,
            "retained_sessions": retained,
            "active_days": active_days,
        })
        user_rows.append({
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
            "total_events": bucket["total_events"],
            "failed_auth_sessions": bucket["failed_auth_sessions"],
        })

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
        "request_errors": request_errors,
        "exceptions": exceptions,
        "users": user_rows,
        "latest_ts": latest_ts,
    }


def _parse_rows_to_user_summary(rows: list[dict[str, Any]], profiles: list[dict[str, Any]], token_usage: list[dict[str, Any]], sessions: list[dict[str, Any]], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profile_map = {(_safe_email(row.get("email"))): row for row in profiles if _safe_email(row.get("email"))}
    token_map: dict[str, dict[str, Any]] = defaultdict(lambda: {"token_usage": 0, "token_rows": 0, "last_seen": None})
    for row in token_usage:
        email = _safe_email(row.get("user_email"))
        if not email:
            continue
        token_map[email]["token_usage"] += int(row.get("total_tokens") or 0)
        token_map[email]["token_rows"] += 1
        ts = _parse_dt(row.get("created_at"))
        if ts and (token_map[email]["last_seen"] is None or ts > token_map[email]["last_seen"]):
            token_map[email]["last_seen"] = ts

    session_map: dict[str, dict[str, Any]] = defaultdict(lambda: {"workspace_sessions": 0, "last_seen": None})
    for row in sessions:
        email = _safe_email(row.get("user_email"))
        if not email:
            continue
        session_map[email]["workspace_sessions"] += 1
        ts = _parse_dt(row.get("created_at"))
        if ts and (session_map[email]["last_seen"] is None or ts > session_map[email]["last_seen"]):
            session_map[email]["last_seen"] = ts

    fact_map: dict[str, dict[str, Any]] = defaultdict(lambda: {"insight_rows": 0, "last_seen": None})
    for row in facts:
        email = _safe_email(row.get("user_email"))
        if not email:
            continue
        fact_map[email]["insight_rows"] += 1
        ts = _parse_dt(row.get("created_at"))
        if ts and (fact_map[email]["last_seen"] is None or ts > fact_map[email]["last_seen"]):
            fact_map[email]["last_seen"] = ts

    all_emails = set(profile_map) | set(token_map) | set(session_map) | set(fact_map)
    for row in rows:
        email = _safe_email(row.get("email"))
        if email:
            all_emails.add(email)

    combined: list[dict[str, Any]] = []
    for email in all_emails:
        telemetry_row = next((row for row in rows if _safe_email(row.get("email")) == email), None)
        profile = profile_map.get(email, {})
        token = token_map.get(email, {})
        session = session_map.get(email, {})
        fact = fact_map.get(email, {})
        last_seen_candidates = [
            _parse_dt(telemetry_row.get("last_seen")) if telemetry_row else None,
            _parse_dt(profile.get("updated_at")),
            token.get("last_seen"),
            session.get("last_seen"),
            fact.get("last_seen"),
        ]
        last_seen = max([dt for dt in last_seen_candidates if dt is not None], default=_now_utc())
        source_tags = set()
        if telemetry_row:
            source_tags.update(telemetry_row.get("sources") or [])
        if profile:
            source_tags.add("Supabase")
        if session:
            source_tags.add("ProspektLab Workspace")
        if fact:
            source_tags.add("ProspektLab Insights")
        if token:
            source_tags.add("Supabase")

        stage_data = {
            "landing_sessions": int(telemetry_row.get("landing_sessions") if telemetry_row else 0),
            "signup_started_sessions": int(telemetry_row.get("signup_started_sessions") if telemetry_row else 0),
            "signup_completed_sessions": int(telemetry_row.get("signup_completed_sessions") if telemetry_row else 0),
            "onboarding_sessions": int(telemetry_row.get("onboarding_sessions") if telemetry_row else 0),
            "workspace_sessions": int((telemetry_row.get("workspace_sessions") if telemetry_row else 0) or session.get("workspace_sessions", 0)),
            "first_value_sessions": int((telemetry_row.get("first_value_sessions") if telemetry_row else 0) or fact.get("insight_rows", 0)),
            "retained_sessions": int(telemetry_row.get("retained_sessions") if telemetry_row else 0),
            "active_days": int(telemetry_row.get("active_days") if telemetry_row else 0),
        }
        stage, action = _choose_stage(stage_data)
        name = (profile.get("full_name") or (telemetry_row.get("name") if telemetry_row else "") or email.split("@", 1)[0]).strip() or email
        combined.append({
            "email": email,
            "name": name,
            "stage": stage,
            "source": " + ".join(sorted(source_tags)) if source_tags else "Azure + Supabase",
            "last_seen": last_seen.isoformat(),
            "workspace_events": int(session.get("workspace_sessions", 0) or stage_data["workspace_sessions"]),
            "token_usage": int(token.get("token_usage", 0)),
            "insight_rows": int(fact.get("insight_rows", 0)),
            "risk": "low" if _stage_rank(stage) >= 5 else "medium" if _stage_rank(stage) >= 3 else "high",
            "action": action,
            "auth_provider": profile.get("auth_provider") or "",
            "created_at": profile.get("created_at") or "",
            "updated_at": profile.get("updated_at") or "",
        })

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
                "errors": 0,
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

    if not azure_rows:
        demo = _demo_snapshot(normalized, {
            "profiles_count": len(supabase_stats.get("profiles") or []),
            "token_total": sum(int(row.get("total_tokens") or 0) for row in supabase_stats.get("token_usage") or []),
            "session_summary_count": len(supabase_stats.get("sessions") or []),
            "facts_count": len(supabase_stats.get("facts") or []),
        })
        demo["source_health"][0]["status"] = _status_pill(azure_status)
        demo["source_health"][0]["note"] = azure_note
        demo["source_health"][0]["coverage"] = 0.0 if azure_status != "healthy" else demo["source_health"][0]["coverage"]
        return demo

    aggregate = _aggregate_event_summary(azure_rows, days)
    profiles = supabase_stats.get("profiles") or []
    token_usage = supabase_stats.get("token_usage") or []
    sessions = supabase_stats.get("sessions") or []
    facts = supabase_stats.get("facts") or []
    outreach_events = supabase_stats.get("outreach_events") or []

    combined_users = _parse_rows_to_user_summary(
        aggregate["users"],
        profiles,
        token_usage,
        sessions,
        facts,
    )

    landing_sessions = int(aggregate["landing_sessions"])
    signup_started_sessions = max(int(aggregate["signup_started_sessions"]), int(aggregate["signup_completed_sessions"]))
    signup_completed_sessions = int(aggregate["signup_completed_sessions"])
    onboarding_completed_sessions = max(int(aggregate["onboarding_completed_sessions"]), min(signup_completed_sessions, int(aggregate["workspace_sessions"])))
    workspace_sessions = max(int(aggregate["workspace_sessions"]), len(sessions))
    first_value_sessions = max(int(aggregate["first_value_sessions"]), len(facts))
    retained_sessions = sum(1 for item in combined_users if item["stage"] == "retained")
    combined_users_count = len(combined_users)
    workspace_users = len({row.get("user_email") for row in sessions if _safe_email(row.get("user_email"))})
    insight_users = len({row.get("user_email") for row in facts if _safe_email(row.get("user_email"))})
    identity_matches = len({row.get("email") for row in combined_users if row.get("email") and row.get("auth_provider")}) or 0
    identity_match_rate = identity_matches / max(1, combined_users_count) * 100

    request_durations = aggregate["request_durations"]
    p95_latency_ms = statistics.quantiles(request_durations, n=100)[94] if len(request_durations) >= 5 else (statistics.median(request_durations) if request_durations else 0.0)
    errors = len(aggregate["request_errors"]) + len(aggregate["exceptions"])
    open_alerts = max(1, min(9, errors + (1 if p95_latency_ms > 500 else 0)))
    freshness_seconds = 0.0
    latest_candidates = [aggregate.get("latest_ts")] + [_parse_dt(row.get("updated_at")) for row in profiles] + [_parse_dt(row.get("created_at")) for row in sessions] + [_parse_dt(row.get("created_at")) for row in facts]
    latest = max([item for item in latest_candidates if item is not None], default=_now_utc())
    freshness_seconds = (_now_utc() - latest).total_seconds()

    daily_series = _build_trend(aggregate["rows_by_day"], days)
    top_pages = _build_top_pages(aggregate["top_routes"])
    top_events = _build_top_events(aggregate["top_events"])
    dropoffs, biggest_leak = _build_dropoffs({
        "landing_sessions": landing_sessions,
        "signup_started_sessions": signup_started_sessions,
        "signup_completed_sessions": signup_completed_sessions,
        "onboarding_completed_sessions": onboarding_completed_sessions,
        "workspace_sessions": workspace_sessions,
        "first_value_sessions": first_value_sessions,
        "auth_failure_sessions": aggregate["auth_failure_sessions"],
        "p95_latency_ms": p95_latency_ms,
    })

    source_mix = [
        {"name": "Azure Application Insights", "value": len(azure_rows), "color": SOURCE_COLORS[0]["color"]},
        {"name": "Azure Monitor", "value": len(aggregate["request_errors"]) + len(aggregate["exceptions"]), "color": SOURCE_COLORS[1]["color"]},
        {"name": "Supabase", "value": len(profiles) + len(token_usage), "color": SOURCE_COLORS[2]["color"]},
        {"name": "ProspektLab Workspace", "value": len(sessions), "color": SOURCE_COLORS[3]["color"]},
        {"name": "ProspektLab Insights", "value": len(facts) + len(outreach_events), "color": SOURCE_COLORS[4]["color"]},
    ]
    source_total = sum(item["value"] for item in source_mix) or 1
    for item in source_mix:
        item["pct"] = item["value"] / source_total * 100

    source_health = [
        {
            "name": "Azure Application Insights",
            "status": _status_from_lag(freshness_seconds, bool(azure_rows)),
            "coverage": 100.0 if azure_rows else 0.0,
            "lag_seconds": freshness_seconds,
            "note": azure_note,
            "metric": f"{_fmt_count(landing_sessions)} landing sessions",
            "extra": f"{_fmt_count(len(top_events))} event types",
        },
        {
            "name": "Azure Monitor",
            "status": _status_from_lag(freshness_seconds + 10, bool(aggregate["request_errors"] or aggregate["exceptions"])),
            "coverage": 100.0 if (aggregate["request_errors"] or aggregate["exceptions"]) else 0.0,
            "lag_seconds": freshness_seconds + 10,
            "note": "Request failures and exceptions are the operational pulse.",
            "metric": f"{open_alerts} open alerts",
            "extra": f"{p95_latency_ms:.0f}ms p95",
        },
        {
            "name": "Supabase",
            "status": _status_from_lag(freshness_seconds + 15, bool(profiles or token_usage)),
            "coverage": 100.0 if (profiles or token_usage) else 0.0,
            "lag_seconds": freshness_seconds + 15,
            "note": "Auth, profiles, token usage, and workspace state are stitched in.",
            "metric": f"{_fmt_count(len(profiles))} profiles",
            "extra": f"{_fmt_count(sum(int(r.get('total_tokens') or 0) for r in token_usage))} tokens",
        },
        {
            "name": "ProspektLab Workspace",
            "status": _status_from_lag(freshness_seconds + 8, bool(sessions)),
            "coverage": 100.0 if sessions else 0.0,
            "lag_seconds": freshness_seconds + 8,
            "note": "Session summaries keep the workspace side of the funnel honest.",
            "metric": f"{_fmt_count(len(sessions))} sessions",
            "extra": f"{_fmt_count(workspace_users)} users",
        },
        {
            "name": "ProspektLab Insights",
            "status": _status_from_lag(freshness_seconds + 6, bool(facts or outreach_events)),
            "coverage": 100.0 if (facts or outreach_events) else 0.0,
            "lag_seconds": freshness_seconds + 6,
            "note": "Insights facts and generated content are merged into the same view.",
            "metric": f"{_fmt_count(len(facts))} insights",
            "extra": f"{_fmt_count(insight_users)} users",
        },
    ]

    signup_completion_rate = signup_completed_sessions / max(1, signup_started_sessions) * 100
    workspace_activation_rate = first_value_sessions / max(1, workspace_sessions) * 100
    retention_rate = retained_sessions / max(1, combined_users_count) * 100
    health_score = max(
        0,
        min(
            100,
            int(
                100
                - open_alerts * 7
                - max(0, p95_latency_ms - 250) * 0.06
                - max(0, biggest_leak["pct"] - 18) * 0.85
                + min(6, len(profiles) // 10)
            ),
        ),
    )

    return {
        "mode": "live" if azure_rows else "partial",
        "live_data": bool(azure_rows),
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
            "combined_users": combined_users_count,
            "workspace_users": workspace_users,
            "insight_users": insight_users,
            "identity_match_rate": identity_match_rate,
            "open_alerts": open_alerts,
            "p95_latency_ms": p95_latency_ms,
            "avg_freshness_seconds": freshness_seconds,
            "signup_completion_rate": signup_completion_rate,
            "workspace_activation_rate": workspace_activation_rate,
            "retention_rate": retention_rate,
        },
        "series": daily_series,
        "funnel": [
            {"stage": "Landing", "value": landing_sessions, "detail": "Landing traffic and first touchpoints."},
            {"stage": "Signup started", "value": signup_started_sessions, "detail": "Users who engaged with auth intent."},
            {"stage": "Signup completed", "value": signup_completed_sessions, "detail": "Successful auth completions."},
            {"stage": "Onboarding completed", "value": onboarding_completed_sessions, "detail": "Users who finished setup."},
            {"stage": "Workspace active", "value": workspace_sessions, "detail": "Users using the workspace."},
            {"stage": "First value", "value": first_value_sessions, "detail": "Users who reached an insight."},
            {"stage": "Retained", "value": retained_sessions, "detail": "Users with repeated activity."},
        ],
        "biggest_leak": biggest_leak,
        "dropoffs": dropoffs,
        "source_mix": source_mix,
        "source_health": source_health,
        "combined_users": combined_users[:25],
        "top_pages": top_pages,
        "top_events": top_events,
        "health_score": health_score,
        "open_alerts": open_alerts,
        "request_samples": aggregate["request_errors"][:20],
        "exception_samples": aggregate["exceptions"][:20],
    }

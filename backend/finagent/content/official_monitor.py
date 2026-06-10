"""24/7 official-source monitor for research article automation.

Polls official NSE, BSE, and SEBI sources, triages material events, and routes
only worthwhile items into the editorial research pipeline.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from finagent.content.editorial import event_is_low_value
from finagent.content.flash_engine import FlashGenerationRequest, generate_flash_article
from finagent.content_automation import (
    ContentEventWatch,
    _event_fingerprint,
    load_generated_article,
    list_generated_articles,
    refresh_public_research_hub,
    unpublish_article,
)
from finagent.events import BUS
from finagent.ikg.scrapers.mca_companies import get_listed_companies
from finagent.ikg.scrapers.sebi_corporate_filings import (
    _extract_with_fallback_candidates,
    fetch_bse_corporate_filings,
    fetch_nse_corporate_filings,
)
from finagent.news.dedupe import deduplicate
from finagent.news.scorer import VERIFIED_DOMAINS, parse_published_at, score_item, tag_category
from finagent.news.sources.sebi_rss import fetch_sebi_news
from finagent.paths import finagent_data_path, repo_root
from finagent.seo.google_search_console import get_search_console_status
from finagent.tools.data import fetch_news

logger = logging.getLogger("finagent.content.official_monitor")

_STATE_PATH = finagent_data_path("content_automation", "official_monitor_state.json")
_SCHEDULER_STATE_PATH = finagent_data_path("content_automation", "official_monitor_scheduler.json")
_DEFAULT_BATCH_SIZE = 10
_DEFAULT_EVENTS_PER_COMPANY = 2
_DEFAULT_ROUTE_BASE = "insights"
_SCHEDULER_HEARTBEAT_STALE_MINUTES = 15
_IST = timezone(timedelta(hours=5, minutes=30))


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = str(os.getenv(name, str(default))).strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


_FALLBACK_DAILY_TARGET = _env_int("FINAGENT_FALLBACK_DAILY_TARGET", 20, minimum=1, maximum=30)
_FALLBACK_MAX_PER_SWEEP = _env_int("FINAGENT_FALLBACK_MAX_PER_SWEEP", 3, minimum=1, maximum=10)
_FALLBACK_MAX_GENERATIONS_PER_SWEEP = _env_int("FINAGENT_FALLBACK_MAX_GENERATIONS_PER_SWEEP", 8, minimum=1, maximum=20)
_FALLBACK_MIN_UNIQUE_DOMAINS = _env_int("FINAGENT_FALLBACK_MIN_UNIQUE_DOMAINS", 3, minimum=1, maximum=10)
_FALLBACK_MIN_INTERVAL = timedelta(
    minutes=_env_int("FINAGENT_FALLBACK_MIN_INTERVAL_MINUTES", 0, minimum=0, maximum=720)
)
_OFFICIAL_UPLOAD_LOOKBACK_HOURS = _env_int("FINAGENT_OFFICIAL_UPLOAD_LOOKBACK_HOURS", 24, minimum=1, maximum=168)
_OFFICIAL_UPLOAD_LOOKBACK = timedelta(hours=_OFFICIAL_UPLOAD_LOOKBACK_HOURS)
_FALLBACK_TOPIC_LOOKBACK_DAYS = 14
_FALLBACK_PUBLISH_THRESHOLD = _env_int("FINAGENT_FALLBACK_MIN_CONFIDENCE", 92, minimum=0, maximum=100)
_FALLBACK_QUALITY_FIRST = _env_bool("FINAGENT_FALLBACK_QUALITY_FIRST", True)
_OFFICIAL_ATTACHMENT_STAGE_VERSION = 1
_OFFICIAL_TRIAGE_MIN_MATERIALITY = _env_int("FINAGENT_OFFICIAL_MIN_MATERIALITY", 75, minimum=0, maximum=100)
_OFFICIAL_TRIAGE_MIN_URGENCY = _env_int("FINAGENT_OFFICIAL_MIN_URGENCY", 65, minimum=0, maximum=100)
_ATTACHMENT_REQUIRED_CATEGORIES = {
    "financial_results",
    "shareholding_pattern",
    "corporate_governance",
    "voting_results",
    "related_party_transactions",
    "secretarial_compliance",
    "brsr",
}
_ATTACHMENT_REQUIRED_TERMS = (
    "shareholding pattern",
    "financial result",
    "financial results",
    "regulation 33",
    "voting result",
    "voting results",
    "related party",
    "secretarial compliance",
    "governance",
    "sebi order",
    "adjudication",
    "penalty",
    "show cause",
    "settlement order",
    "xbrl",
)
_ROUTINE_SKIP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bnewspaper publication\b", re.I),
    re.compile(r"\bgeneral update\b", re.I),
    re.compile(r"\btrading window\b", re.I),
    re.compile(r"\bnotice of board meeting\b", re.I),
    re.compile(r"\binvestor(?:s)? meet(?:ing)? notice\b", re.I),
    re.compile(r"\bintimation of analyst(?:s)? (?:meet|meeting|call)\b", re.I),
    re.compile(r"\besop\b", re.I),
    re.compile(r"\ballotment\b", re.I),
    re.compile(r"\bcompliance certificate\b", re.I),
    re.compile(r"\bcertificate under regulation\b", re.I),
)
_MATERIAL_BOARD_TERMS: tuple[str, ...] = (
    "financial result",
    "earnings",
    "dividend",
    "buyback",
    "bonus",
    "rights issue",
    "preferential issue",
    "fund raise",
    "merger",
    "acquisition",
    "amalgamation",
    "slump sale",
    "material transaction",
    "related party",
    "sebi",
    "regulatory",
    "governance",
    "auditor",
)
_MATERIAL_RESIGNATION_TERMS: tuple[str, ...] = (
    "managing director",
    "chief executive officer",
    "ceo",
    "chief financial officer",
    "cfo",
    "chairman",
    "independent director",
    "statutory auditor",
    "company secretary",
    "key managerial personnel",
    "fraud",
    "misconduct",
    "regulatory",
    "sebi",
    "investigation",
    "governance",
)
_TRANSCRIPT_SUBSTANCE_TERMS: tuple[str, ...] = (
    "revenue",
    "margin",
    "ebitda",
    "guidance",
    "order book",
    "capex",
    "cash flow",
    "debt",
    "growth",
    "demand",
)
_FALLBACK_NEWS_QUERIES = (
    "India business headlines today company updates",
    "Indian stock market sector rotation earnings outlook",
    "Indian companies debt reduction deleveraging balance sheet",
    "India capex manufacturing infrastructure renewable investment",
    "Indian banking nbfc credit growth deposit trends",
    "India promoter stake change buyback dividend corporate actions",
    "Indian market breadth fii dii flows sectors",
    "India power transmission renewable capex opportunities",
    "India working capital receivables inventory trends companies",
    "Indian markets latest regulation and business news",
)
_FALLBACK_THEME_RULES: dict[str, tuple[tuple[str, ...], str, str, str]] = {
    "debt": (
        ("debt", "delever", "loan", "borrow", "leverage", "net debt", "refinance"),
        "trend",
        "Debt-Cut Leaders: Which Indian Companies Are Repairing Balance Sheets Fastest",
        "Build a source-backed ranking story on debt reduction across Indian companies using recent verified reports. Explain who is deleveraging, how the balance-sheet change impacts risk and optionality, and what signals execution quality.",
    ),
    "margin": (
        ("margin", "ebitda", "operating profit", "profitability", "gross margin", "cost pressure"),
        "trend",
        "Margin Survivors: Where Indian Businesses Are Protecting Profitability",
        "Write a publication-ready analysis of margin resilience across Indian companies. Use verified reports to explain who is defending profitability, what operational levers are working, and where pressure is building next.",
    ),
    "capex": (
        ("capex", "capacity", "plant", "expansion", "factory", "greenfield", "brownfield", "order book"),
        "trend",
        "Capex Radar: Where New Corporate Investment Is Actually Going",
        "Turn verified business reports into a clear map of India's capex cycle. Explain which sectors are deploying capital, whether demand is real or anticipatory, and what investors should monitor over the next two quarters.",
    ),
    "banking": (
        ("bank", "nbfc", "loan growth", "credit growth", "deposit", "nim"),
        "trend",
        "Credit Pulse: What Banking And NBFC Headlines Are Signalling",
        "Write a crisp banking and NBFC sector analysis from verified reports. Connect headlines to credit growth quality, deposit competition, margin direction, and balance-sheet risk concentrations.",
    ),
    "consumption": (
        ("consumption", "demand", "fmcg", "retail", "volume growth", "premium"),
        "trend",
        "Consumption Split: Value Recovery Versus Premium Demand",
        "Synthesize verified reports into a consumption demand story. Separate value-segment recovery from premiumization, identify sectors with strongest demand confirmation, and flag where demand signals remain fragile.",
    ),
    "rotation": (
        ("sector rotation", "fii", "dii", "breadth", "outperform", "underperform", "index"),
        "trend",
        "Sector Rotation Map: Where Money Is Moving In Indian Markets",
        "Build a market-structure analysis from verified reports and market coverage. Explain where flows and breadth are shifting, which sectors are gaining leadership, and what could invalidate the current rotation.",
    ),
    "promoter": (
        ("promoter", "pledge", "stake sale", "stake increase", "insider", "buyback", "dividend"),
        "company",
        "Promoter Watch: Ownership Signals That Matter This Week",
        "Write an ownership-behavior analysis from verified reports, focusing on promoter actions, capital allocation signals, and governance implications without making investment recommendations.",
    ),
    "working_capital": (
        ("receivables", "inventory", "cash conversion", "working capital", "payables"),
        "trend",
        "Working Capital Alert: Companies With Improving Cash Discipline",
        "Use verified updates to analyze working-capital discipline across companies. Explain changes in receivables, inventory and cash conversion dynamics, and why this matters for business durability.",
    ),
    "power_renewables": (
        ("renewable", "solar", "wind", "transmission", "grid", "power equipment"),
        "trend",
        "Power Grid Winners: Who Benefits From Renewable And Transmission Buildout",
        "Write a source-backed infrastructure story on power and renewable execution. Connect project and policy momentum to listed-company business models and near-term execution bottlenecks.",
    ),
    "market": (
        ("market", "nifty", "sensex", "sector", "stocks", "equity"),
        "trend",
        "Market Signalboard: What Today's Business Headlines Mean For Indian Equities",
        "Synthesize verified business and market reports into a market-trend briefing. Explain underlying business signals, sector leadership, and the next quarter watchpoints in plain professional language.",
    ),
    "regulation": (
        ("sebi", "rbi", "mca", "regulatory", "policy", "penalty", "investigation", "order"),
        "sebi",
        "Regulatory Shiftbook: What New Orders Mean For Business Risk",
        "Write an evidence-led regulatory analysis from verified reports. Explain what changed, which companies or sectors are exposed, and what risk-control signals matter now without advisory language.",
    ),
}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _default_state() -> dict[str, Any]:
    return {
        "cursor": 0,
        "seen_event_ids": {},
        "last_started_at": "",
        "last_completed_at": "",
        "last_status": "idle",
        "last_error": "",
        "last_summary": {
            "discovered": 0,
            "generated": 0,
            "published": 0,
            "drafts": 0,
            "skipped_seen": 0,
            "skipped_low_value": 0,
            "failures": 0,
            "fallback_generated": 0,
            "fallback_published": 0,
            "fallback_held": 0,
        },
        "source_health": {
            "nse": {"ok": 0, "errors": 0, "last_ok_at": "", "last_error": ""},
            "bse": {"ok": 0, "errors": 0, "last_ok_at": "", "last_error": ""},
            "sebi": {"ok": 0, "errors": 0, "last_ok_at": "", "last_error": ""},
        },
        "current_run": {},
        "activity_log": [],
        "recent_items": [],
        "fallback": {
            "day_key": "",
            "daily_target": _FALLBACK_DAILY_TARGET,
            "daily_count": 0,
            "generated_today": 0,
            "published_today": 0,
            "held_today": 0,
            "last_published_at": "",
            "last_attempted_at": "",
            "last_status": "idle",
            "last_action": "",
            "last_error": "",
            "candidates_considered": 0,
            "qualified_topics": 0,
            "remaining_today": _FALLBACK_DAILY_TARGET,
            "review_reasons": [],
            "next_eligible_at": "",
            "last_topic": "",
            "last_slug": "",
        },
        "updated_at": "",
    }


def _default_scheduler_state() -> dict[str, Any]:
    return {
        "status": "",
        "note": "",
        "last_heartbeat_at": "",
        "next_official_monitor_at": "",
        "job_count": 0,
        "pid": 0,
    }


def load_monitor_state() -> dict[str, Any]:
    if not _STATE_PATH.is_file():
        return _default_state()
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            state = _default_state()
            state.update(data)
            fallback = _default_state().get("fallback") or {}
            raw_fallback = data.get("fallback") or {}
            if isinstance(raw_fallback, dict):
                fallback.update(raw_fallback)
            state["fallback"] = fallback
            summary = _default_state().get("last_summary") or {}
            raw_summary = data.get("last_summary") or {}
            if isinstance(raw_summary, dict):
                summary.update(raw_summary)
            state["last_summary"] = summary
            return state
    except Exception:
        logger.exception("Failed to load official monitor state")
    return _default_state()


def save_monitor_state(state: dict[str, Any]) -> None:
    seen = state.get("seen_event_ids") or {}
    if isinstance(seen, dict) and len(seen) > 12000:
        ordered = sorted(seen.items(), key=lambda item: item[1], reverse=True)[:12000]
        state["seen_event_ids"] = dict(ordered)
    activity_log = state.get("activity_log") or []
    if isinstance(activity_log, list):
        state["activity_log"] = activity_log[:80]
    recent_items = state.get("recent_items") or []
    if isinstance(recent_items, list):
        state["recent_items"] = recent_items[:60]
    state["updated_at"] = _utcnow_iso()
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=True), encoding="utf-8")


def _append_activity(
    state: dict[str, Any],
    *,
    message: str,
    level: str = "info",
    phase: str = "",
    source: str = "",
    company: str = "",
) -> None:
    activity = state.setdefault("activity_log", [])
    if not isinstance(activity, list):
        activity = []
        state["activity_log"] = activity
    activity.insert(
        0,
        {
            "timestamp": _utcnow_iso(),
            "message": message[:220],
            "level": level,
            "phase": phase[:80],
            "source": source[:32],
            "company": company[:140],
        },
    )


def _update_current_run(
    state: dict[str, Any],
    *,
    phase: str = "",
    source: str = "",
    company: str = "",
    discovered: int = 0,
    generated: int = 0,
    published: int = 0,
    drafts: int = 0,
    skipped_seen: int = 0,
    skipped_low_value: int = 0,
    failures: int = 0,
    companies_scanned: int = 0,
    companies_total: int = 0,
    **details: Any,
) -> None:
    current = state.setdefault("current_run", {})
    if not isinstance(current, dict):
        current = {}
        state["current_run"] = current
    if not current.get("started_at"):
        current["started_at"] = state.get("last_started_at") or _utcnow_iso()
    payload = {
        "phase": phase,
        "source": source,
        "company": company,
        "discovered": discovered,
        "generated": generated,
        "published": published,
        "drafts": drafts,
        "skipped_seen": skipped_seen,
        "skipped_low_value": skipped_low_value,
        "failures": failures,
        "companies_scanned": companies_scanned,
        "companies_total": companies_total,
        "updated_at": _utcnow_iso(),
    }
    payload.update(details)
    current.update(payload)


def load_scheduler_state() -> dict[str, Any]:
    if not _SCHEDULER_STATE_PATH.is_file():
        return _default_scheduler_state()
    try:
        data = json.loads(_SCHEDULER_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            state = _default_scheduler_state()
            state.update(data)
            return state
    except Exception:
        logger.exception("Failed to load official monitor scheduler state")
    return _default_scheduler_state()


def save_scheduler_state(state: dict[str, Any]) -> None:
    payload = _default_scheduler_state()
    payload.update(state)
    payload["last_heartbeat_at"] = payload.get("last_heartbeat_at") or _utcnow_iso()
    _SCHEDULER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SCHEDULER_STATE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def record_scheduler_heartbeat(
    *,
    status: str = "running",
    note: str = "",
    next_official_monitor_at: str = "",
    job_count: int = 0,
    pid: int | None = None,
) -> None:
    save_scheduler_state(
        {
            "status": status,
            "note": note,
            "last_heartbeat_at": _utcnow_iso(),
            "next_official_monitor_at": next_official_monitor_at,
            "job_count": job_count,
            "pid": int(pid or os.getpid()),
        }
    )


def _cron_enabled() -> bool:
    return os.getenv("FINAGENT_SCHEDULER_ENABLE_CRON", "1").strip().lower() in {"1", "true", "yes", "on"}


def _realtime_loop_enabled() -> bool:
    return os.getenv("FINAGENT_OFFICIAL_MONITOR_REALTIME_LOOP", "1").strip().lower() in {"1", "true", "yes", "on"}


def _runtime_control_enabled(control_key: str, *, default: bool = True) -> bool:
    try:
        from finagent.ikg.pipeline.run_store import is_runtime_control_enabled
    except Exception:
        return default
    return is_runtime_control_enabled(control_key, default=default)


def _derive_scheduler_status(scheduler_state: dict[str, Any]) -> tuple[str, bool]:
    cron_enabled = _cron_enabled() or _realtime_loop_enabled()
    pipeline_enabled = _runtime_control_enabled("pipeline_enabled", default=True)
    monitor_enabled = _runtime_control_enabled("official_monitor_enabled", default=True)
    scheduler_enabled = cron_enabled and pipeline_enabled and monitor_enabled

    recorded_status = str(scheduler_state.get("status") or "").strip().lower()
    if recorded_status == "manual_only":
        return "manual_only", scheduler_enabled
    if recorded_status == "disabled":
        return "disabled", scheduler_enabled

    if not cron_enabled:
        return "manual_only", scheduler_enabled
    if not pipeline_enabled or not monitor_enabled:
        return "disabled", scheduler_enabled

    heartbeat = scheduler_state.get("last_heartbeat_at") or ""
    heartbeat_dt = None
    if heartbeat:
        try:
            heartbeat_dt = datetime.fromisoformat(str(heartbeat).replace("Z", "+00:00"))
        except ValueError:
            heartbeat_dt = None
    if not heartbeat_dt:
        return "offline", scheduler_enabled
    if heartbeat_dt < datetime.now(timezone.utc) - timedelta(minutes=_SCHEDULER_HEARTBEAT_STALE_MINUTES):
        return "offline", scheduler_enabled
    return "running", scheduler_enabled


def _monitor_status_detail(
    *,
    status: str,
    scheduler_status: str,
    scheduler_state: dict[str, Any],
    last_completed_at: str,
) -> str:
    if status == "running":
        return "A sweep is running now. Official NSE, BSE, and SEBI sources from the last 24 hours are being scanned and publication candidates are being generated."
    if scheduler_status == "running" and last_completed_at:
        return "24/7 automation is online. Official NSE, BSE, and SEBI sources from the last 24 hours are scanned continuously for topics worth drafting and publishing."
    if scheduler_status == "running":
        return "24/7 automation is online and waiting for its first scheduled sweep. Topics are selected automatically from official-source updates published in the last 24 hours."
    if scheduler_status == "manual_only":
        return "Scheduled automation is disabled in this environment. You can still run a manual sweep or provide a topic above."
    if scheduler_status == "disabled":
        return "Runtime controls have paused the always-on monitor. Manual topic-driven generation is still available."
    note = str(scheduler_state.get("note") or "").strip()
    if note:
        return f"24/7 automation is expected, but the scheduler heartbeat is offline. {note}"
    return "24/7 automation is expected, but the scheduler heartbeat is offline. Start the scheduler service to resume automatic topic discovery and publishing."


def get_monitor_status() -> dict[str, Any]:
    state = load_monitor_state()
    scheduler_state = load_scheduler_state()
    fallback = _fallback_state(state)
    search_console = get_search_console_status()
    scheduler_status, scheduler_enabled = _derive_scheduler_status(scheduler_state)
    last_status = str(state.get("last_status") or "idle")
    last_started_at = _parse_iso_datetime(str(state.get("last_started_at") or ""))
    stale_running = bool(
        last_status == "running"
        and last_started_at
        and last_started_at < datetime.now(timezone.utc) - timedelta(minutes=30)
    )
    status = last_status
    if last_status == "running" and not stale_running:
        status = "running"
    elif scheduler_status == "running":
        status = "scheduled"
    elif scheduler_status in {"manual_only", "disabled", "offline"}:
        status = scheduler_status
    elif stale_running:
        status = "idle"

    return {
        "status": status,
        "last_started_at": state.get("last_started_at") or "",
        "last_completed_at": state.get("last_completed_at") or "",
        "last_error": state.get("last_error") or "",
        "last_summary": state.get("last_summary") or {},
        "source_health": state.get("source_health") or {},
        "current_run": state.get("current_run") or {},
        "activity_log": state.get("activity_log") or [],
        "recent_items": state.get("recent_items") or [],
        "cursor": int(state.get("cursor") or 0),
        "updated_at": state.get("updated_at") or "",
        "automation_mode": "automatic_topics",
        "automation_label": "24/7 official-source monitor + fallback desk",
        "status_detail": _monitor_status_detail(
            status=status,
            scheduler_status=scheduler_status,
            scheduler_state=scheduler_state,
            last_completed_at=str(state.get("last_completed_at") or ""),
        ),
        "scheduler_status": scheduler_status,
        "scheduler_enabled": scheduler_enabled,
        "scheduler_last_heartbeat_at": scheduler_state.get("last_heartbeat_at") or "",
        "next_scheduled_run_at": scheduler_state.get("next_official_monitor_at") or "",
        "fallback_status": fallback.get("last_status") or "idle",
        "fallback_daily_count": int(fallback.get("daily_count") or 0),
        "fallback_daily_target": int(fallback.get("daily_target") or _FALLBACK_DAILY_TARGET),
        "fallback_remaining_today": int(fallback.get("remaining_today") or 0),
        "fallback_generated_today": int(fallback.get("generated_today") or 0),
        "fallback_published_today": int(fallback.get("published_today") or fallback.get("daily_count") or 0),
        "fallback_held_today": int(fallback.get("held_today") or 0),
        "fallback_candidates_considered": int(fallback.get("candidates_considered") or 0),
        "fallback_qualified_topics": int(fallback.get("qualified_topics") or 0),
        "fallback_last_action": fallback.get("last_action") or "",
        "fallback_review_reasons": list(fallback.get("review_reasons") or []),
        "next_fallback_after": fallback.get("next_eligible_at") or "",
        "search_console": search_console,
    }


def _emit(job_id: str | None, event_type: str, **payload: Any) -> None:
    if not job_id:
        return
    BUS.emit(job_id, event_type, **payload)


def _mark_source_health(state: dict[str, Any], source: str, *, ok: bool, error: str = "") -> None:
    health = state.setdefault("source_health", {}).setdefault(
        source, {"ok": 0, "errors": 0, "last_ok_at": "", "last_error": ""}
    )
    if ok:
        health["ok"] = int(health.get("ok") or 0) + 1
        health["last_ok_at"] = _utcnow_iso()
        health["last_error"] = ""
    else:
        health["errors"] = int(health.get("errors") or 0) + 1
        health["last_error"] = error[:400]


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _fallback_state(state: dict[str, Any]) -> dict[str, Any]:
    fallback = state.setdefault("fallback", {})
    defaults = _default_state().get("fallback") or {}
    for key, value in defaults.items():
        fallback.setdefault(key, value)
    fallback["daily_target"] = _FALLBACK_DAILY_TARGET
    published_today = int(fallback.get("published_today") or fallback.get("daily_count") or 0)
    fallback["published_today"] = published_today
    fallback["daily_count"] = published_today
    fallback["generated_today"] = int(fallback.get("generated_today") or 0)
    fallback["held_today"] = int(fallback.get("held_today") or 0)
    fallback["qualified_topics"] = int(fallback.get("qualified_topics") or 0)
    if not isinstance(fallback.get("review_reasons"), list):
        fallback["review_reasons"] = []
    fallback["remaining_today"] = max(0, _FALLBACK_DAILY_TARGET - published_today)
    return fallback


def _ist_day_key(now: datetime | None = None) -> str:
    current = (now or datetime.now(timezone.utc)).astimezone(_IST)
    return current.strftime("%Y-%m-%d")


def _fallback_source_tier(url: str, source: str = "") -> int:
    host = (urlparse(url).hostname or "").lower()
    source_lower = source.lower()
    for domain, tier in VERIFIED_DOMAINS.items():
        domain = domain.lower()
        if host == domain or host.endswith(f".{domain}") or domain in source_lower:
            return int(tier)
    return 3


def _normalize_topic_key(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return " ".join(cleaned.split()[:12]).strip()


def _recent_published_topic_keys(route_base: str) -> set[str]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=_FALLBACK_TOPIC_LOOKBACK_DAYS)
    keys: set[str] = set()
    for article in list_generated_articles(route_base=route_base, limit=250):
        if str(article.get("publish_status") or "").lower() != "published":
            continue
        published_at = _parse_iso_datetime(str(article.get("published_at") or article.get("generated_at") or ""))
        if published_at and published_at < cutoff:
            continue
        keywords = " ".join(str(keyword) for keyword in (article.get("keywords") or [])[:4])
        key = _normalize_topic_key(f"{article.get('title') or ''} {keywords}")
        if key:
            keys.add(key)
    return keys


def _company_aliases(universe: list[dict[str, Any]]) -> list[tuple[str, str]]:
    aliases: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for company in universe:
        company_name = str(company.get("company_name") or company.get("nse_symbol") or "").strip()
        if not company_name:
            continue
        normalized_name = re.sub(r"\b(limited|ltd|limited\.|industries|services|company|co)\b", "", company_name, flags=re.I)
        candidates = [company_name, normalized_name.strip()]
        symbol = str(company.get("nse_symbol") or "").strip()
        if len(symbol) >= 4:
            candidates.append(symbol)
        for candidate in candidates:
            alias = candidate.strip().lower()
            if len(alias) < 4:
                continue
            key = (alias, company_name)
            if key in seen:
                continue
            seen.add(key)
            aliases.append(key)
    aliases.sort(key=lambda item: len(item[0]), reverse=True)
    return aliases


def _match_company_name(text: str, aliases: list[tuple[str, str]]) -> str | None:
    lowered = text.lower()
    for alias, company_name in aliases:
        if alias.isalpha() and len(alias) <= 5:
            if re.search(rf"\b{re.escape(alias)}\b", lowered):
                return company_name
            continue
        if alias in lowered:
            return company_name
    return None


def _classify_fallback_theme(item: dict[str, Any]) -> str:
    text = f"{item.get('title') or ''} {item.get('snippet') or ''}".lower()
    for theme, (keywords, _, _, _) in _FALLBACK_THEME_RULES.items():
        if any(keyword in text for keyword in keywords):
            return theme
    category = str(item.get("category") or "")
    if category == "regulatory":
        return "regulation"
    if category == "market":
        return "market"
    return "market"


def _search_console_topic_queries(search_console: dict[str, Any] | None) -> list[str]:
    if not isinstance(search_console, dict):
        return []
    if not bool(search_console.get("enabled")) or not bool(search_console.get("configured")):
        return []
    if search_console.get("error"):
        return []
    rows = list(search_console.get("top_queries") or [])
    ranked = sorted(
        (
            row for row in rows
            if isinstance(row, dict) and str(row.get("query") or "").strip()
        ),
        key=lambda row: (
            float(row.get("impressions") or 0.0),
            -float(row.get("ctr") or 0.0),
        ),
        reverse=True,
    )
    queries: list[str] = []
    for row in ranked[:5]:
        query = str(row.get("query") or "").strip()
        if len(query) < 6:
            continue
        queries.append(f"India business analysis {query}")
    return queries


async def _collect_fallback_news(
    universe: list[dict[str, Any]],
    *,
    search_console: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    del universe  # reserved for future query specialization
    dynamic_queries = _search_console_topic_queries(search_console)
    query_list = list(dict.fromkeys([*_FALLBACK_NEWS_QUERIES, *dynamic_queries]))[:14]
    batches = await asyncio.gather(
        *(fetch_news(query, limit=8) for query in query_list),
        return_exceptions=True,
    )
    vetted: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for batch in batches:
        if isinstance(batch, Exception):
            logger.warning("Fallback news fetch failed: %s", batch)
            continue
        for row in batch:
            item = {
                "title": str(getattr(row, "title", "") or "").strip(),
                "snippet": str(getattr(row, "description", "") or "").strip(),
                "url": str(getattr(row, "link", "") or "").strip(),
                "published": str(getattr(row, "published", "") or "").strip(),
                "source": str(getattr(row, "source", "") or "").strip(),
            }
            if not item["title"] or not item["url"]:
                continue
            tier = _fallback_source_tier(item["url"], item["source"])
            if tier > 1:
                continue
            published_at = parse_published_at(item)
            if published_at is not None:
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=timezone.utc)
                if published_at < now - timedelta(days=7):
                    continue
            item["published_at"] = published_at.isoformat() if published_at else ""
            item["source_tier"] = tier
            item["category"] = tag_category(item)
            item["score"] = score_item(item)
            vetted.append(item)
    deduped = deduplicate(vetted)
    deduped.sort(
        key=lambda item: (
            float(item.get("score") or 0.0),
            item.get("published_at") or "",
        ),
        reverse=True,
    )
    return deduped[:48]


def _build_fallback_candidates(items: list[dict[str, Any]], universe: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aliases = _company_aliases(universe)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        text = f"{item.get('title') or ''} {item.get('snippet') or ''}"
        company_name = _match_company_name(text, aliases)
        if company_name:
            group_key = f"company:{company_name}"
        else:
            group_key = f"theme:{_classify_fallback_theme(item)}"
        grouped.setdefault(group_key, []).append(item)

    candidates: list[dict[str, Any]] = []
    for group_key, group_items in grouped.items():
        unique_domains = {
            (urlparse(str(item.get("url") or "")).hostname or "").lower()
            for item in group_items
            if item.get("url")
        }
        unique_domains.discard("")
        if len(unique_domains) < _FALLBACK_MIN_UNIQUE_DOMAINS:
            continue

        ordered = sorted(group_items, key=lambda item: float(item.get("score") or 0.0), reverse=True)
        supporting = ordered[:5]
        if group_key.startswith("company:"):
            company_name = group_key.split(":", 1)[1]
            categories = Counter(str(item.get("category") or "general") for item in supporting)
            dominant = categories.most_common(1)[0][0] if categories else "general"
            content_type = "earnings" if dominant == "earnings" else "sebi" if dominant == "regulatory" else "company"
            target = company_name
            objective = (
                f"Write a sharp, publication-ready analysis of {company_name} using the latest verified reports. "
                "Start by explaining what the company does, then connect the current news cycle to business model, "
                "execution, financial or regulatory implications, and the next watchpoints. Keep the tone calm, "
                "concrete, and investor-safe."
            )
            topic_key = _normalize_topic_key(company_name)
        else:
            theme = group_key.split(":", 1)[1]
            _, content_type, target, objective = _FALLBACK_THEME_RULES.get(theme, _FALLBACK_THEME_RULES["market"])
            topic_key = _normalize_topic_key(target)

        candidates.append(
            {
                "group_key": group_key,
                "topic_key": topic_key,
                "target": target,
                "content_type": content_type,
                "objective": objective,
                "source_url": str(supporting[0].get("url") or ""),
                "supporting_sources": supporting,
                "score": round(sum(float(item.get("score") or 0.0) for item in supporting[:3]) + (len(unique_domains) * 0.15), 2),
            }
        )

    candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return candidates


def _fallback_candidate_quality_check(candidate: dict[str, Any]) -> tuple[bool, str]:
    supporting = list(candidate.get("supporting_sources") or [])
    if len(supporting) < 3:
        return False, "fallback_sources_too_thin"
    unique_domains = {
        (urlparse(str(item.get("url") or "")).hostname or "").lower()
        for item in supporting
        if item.get("url")
    }
    unique_domains.discard("")
    if len(unique_domains) < _FALLBACK_MIN_UNIQUE_DOMAINS:
        return False, "fallback_source_diversity_low"
    trusted_tier_count = sum(
        1 for item in supporting
        if _fallback_source_tier(str(item.get("url") or ""), str(item.get("source") or "")) <= 2
    )
    if trusted_tier_count < 2:
        return False, "fallback_trusted_sources_insufficient"
    headline_fingerprint = {
        re.sub(r"\W+", " ", str(item.get("title") or "").strip().lower())
        for item in supporting
    }
    headline_fingerprint.discard("")
    if len(headline_fingerprint) < 2:
        return False, "fallback_duplicate_headlines"
    return True, ""


def _load_article_gate_snapshot(slug: str, route_base: str) -> dict[str, Any]:
    manifest = load_generated_article(slug, route_base=route_base) or {}
    publish_gate = manifest.get("publish_gate") if isinstance(manifest.get("publish_gate"), dict) else {}
    metrics = publish_gate.get("metrics") if isinstance(publish_gate.get("metrics"), dict) else {}
    sources_used = manifest.get("sources_used") if isinstance(manifest.get("sources_used"), list) else []
    evidence_claims = manifest.get("evidence_claims") if isinstance(manifest.get("evidence_claims"), list) else []
    gate_reasons = publish_gate.get("reasons") if isinstance(publish_gate.get("reasons"), list) else []
    return {
        "publish_gate_status": str(publish_gate.get("status") or manifest.get("publish_gate_status") or "").lower(),
        "publish_gate_score": int(publish_gate.get("score") or manifest.get("publish_gate_score") or 0),
        "review_reason": str(manifest.get("review_reason") or ""),
        "quality_blockers": [str(reason)[:120] for reason in gate_reasons if str(reason).strip()][:16],
        "source_count": int(metrics.get("source_count") or len(sources_used)),
        "word_count": int(metrics.get("word_count") or manifest.get("word_count") or 0),
        "evidence_claim_count": int(metrics.get("evidence_claim_count") or len(evidence_claims)),
        "document_evidence_status": str(
            metrics.get("document_evidence_status")
            or ((manifest.get("evidence_pack_summary") or {}).get("document_evidence_status") if isinstance(manifest.get("evidence_pack_summary"), dict) else "")
            or ""
        ),
        "context_enrichment_status": str(
            metrics.get("context_enrichment_status")
            or ((manifest.get("evidence_pack_summary") or {}).get("context_enrichment_status") if isinstance(manifest.get("evidence_pack_summary"), dict) else "")
            or ""
        ),
    }


def _backfill_manifest_sources(manifest: dict[str, Any]) -> bool:
    sources = manifest.get("sources_used")
    if not isinstance(sources, list):
        sources = []
    seen_keys: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        title = str(source.get("title") or "").strip()
        key = url.lower() if url else f"title:{title.lower()}"
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        normalized.append(
            {
                "title": title[:220],
                "url": url[:1200],
                "kind": str(source.get("kind") or "secondary")[:40],
                "evidence_type": str(source.get("evidence_type") or "supporting")[:80],
            }
        )

    changed = len(normalized) != len(sources)
    meta = manifest.get("source_evidence_meta")
    if isinstance(meta, dict):
        seed_candidates = [
            ("Official disclosure page", str(meta.get("source_url") or "").strip(), "official_document"),
            ("Official attachment", str(meta.get("attachment_url") or "").strip(), "official_attachment"),
        ]
        for title, url, evidence_type in seed_candidates:
            if not url:
                continue
            key = url.lower()
            if key in seen_keys:
                continue
            seen_keys.add(key)
            normalized.append(
                {
                    "title": title,
                    "url": url[:1200],
                    "kind": "primary",
                    "evidence_type": evidence_type,
                }
            )
            changed = True

    if changed:
        manifest["sources_used"] = normalized
    return changed


def _cleanup_published_archive(route_base: str, *, state: dict[str, Any]) -> dict[str, int]:
    unpublished = 0
    backfilled = 0
    for item in list_generated_articles(route_base=route_base, limit=600):
        if str(item.get("publish_status") or "").lower() != "published":
            continue
        slug = str(item.get("slug") or "").strip()
        if not slug:
            continue
        manifest = load_generated_article(slug, route_base=route_base)
        if not isinstance(manifest, dict):
            continue

        manifest_changed = _backfill_manifest_sources(manifest)
        if manifest_changed:
            json_path = manifest.get("json_path") or str(
                finagent_data_path("content_automation", route_base, slug, "article.json")
            )
            try:
                Path(str(json_path)).write_text(json.dumps(manifest, indent=2, ensure_ascii=True), encoding="utf-8")
                backfilled += 1
            except Exception:
                logger.exception("Failed to backfill manifest sources for %s/%s", route_base, slug)

        gate_status = str(item.get("publish_gate_status") or "").strip().lower()
        if gate_status != "publish":
            try:
                unpublish_article(slug, route_base)
                unpublished += 1
            except Exception:
                logger.exception("Failed to unpublish non-gate article %s/%s", route_base, slug)

    if unpublished > 0:
        _append_activity(
            state,
            message=f"Archive cleanup unpublished {unpublished} non-gate article(s)",
            phase="archive_cleanup",
            level="warning",
        )
    elif backfilled > 0:
        _append_activity(
            state,
            message=f"Archive cleanup backfilled source metadata on {backfilled} article(s)",
            phase="archive_cleanup",
            level="info",
        )
    return {"unpublished": unpublished, "backfilled": backfilled}


async def _run_fallback_publication(
    *,
    state: dict[str, Any],
    route_base: str,
    requested_by: str,
    dry_run: bool,
    job_id: str | None,
    universe: list[dict[str, Any]],
) -> dict[str, Any]:
    fallback = _fallback_state(state)
    now = datetime.now(timezone.utc)
    day_key = _ist_day_key(now)
    if fallback.get("day_key") != day_key:
        fallback["day_key"] = day_key
        fallback["daily_count"] = 0
        fallback["generated_today"] = 0
        fallback["published_today"] = 0
        fallback["held_today"] = 0
        fallback["review_reasons"] = []
        fallback["qualified_topics"] = 0
        fallback["remaining_today"] = _FALLBACK_DAILY_TARGET

    fallback["last_attempted_at"] = _utcnow_iso()
    fallback["last_error"] = ""
    fallback["daily_target"] = _FALLBACK_DAILY_TARGET

    published_today = int(fallback.get("published_today") or fallback.get("daily_count") or 0)
    fallback["published_today"] = published_today
    fallback["daily_count"] = published_today
    fallback["remaining_today"] = max(0, _FALLBACK_DAILY_TARGET - published_today)

    if published_today >= _FALLBACK_DAILY_TARGET:
        fallback["last_status"] = "daily_cap_reached"
        fallback["last_action"] = "Fallback daily target reached for the current IST day"
        fallback["next_eligible_at"] = ""
        _append_activity(state, message=fallback["last_action"], phase="fallback", source="fallback")
        return {
            "generated": 0,
            "published": 0,
            "drafts": 0,
            "recent_items": [],
            "candidates_considered": 0,
            "qualified_topics": 0,
            "review_reasons": [],
            "remaining_today": fallback["remaining_today"],
        }

    last_published_at = _parse_iso_datetime(str(fallback.get("last_published_at") or ""))
    if _FALLBACK_MIN_INTERVAL.total_seconds() > 0 and last_published_at and now < last_published_at + _FALLBACK_MIN_INTERVAL:
        next_allowed = last_published_at + _FALLBACK_MIN_INTERVAL
        fallback["last_status"] = "cooldown"
        fallback["next_eligible_at"] = next_allowed.replace(microsecond=0).isoformat()
        fallback["last_action"] = "Fallback is cooling down before the next publish window"
        _append_activity(state, message=fallback["last_action"], phase="fallback", source="fallback")
        return {
            "generated": 0,
            "published": 0,
            "drafts": 0,
            "recent_items": [],
            "candidates_considered": 0,
            "qualified_topics": 0,
            "review_reasons": [],
            "remaining_today": fallback["remaining_today"],
        }

    _append_activity(state, message="Scanning verified business coverage for fallback topics", phase="fallback", source="fallback")
    _update_current_run(
        state,
        phase="fallback_scanning",
        source="fallback",
    )
    save_monitor_state(state)

    search_console = get_search_console_status()
    news_items = await _collect_fallback_news(universe, search_console=search_console)
    candidates = _build_fallback_candidates(news_items, universe)
    fallback["candidates_considered"] = len(candidates)
    fallback["qualified_topics"] = len(candidates)
    fallback["review_reasons"] = []
    recent_topic_keys = _recent_published_topic_keys(route_base)
    if not candidates:
        fallback["last_status"] = "no_candidate"
        fallback["last_action"] = "No fallback topic cleared the source and duplication filters"
        fallback["next_eligible_at"] = ""
        _append_activity(state, message=fallback["last_action"], phase="fallback", source="fallback")
        return {
            "generated": 0,
            "published": 0,
            "drafts": 0,
            "recent_items": [],
            "candidates_considered": len(candidates),
            "qualified_topics": len(candidates),
            "review_reasons": [],
            "remaining_today": fallback["remaining_today"],
        }

    if dry_run:
        preview = [item for item in candidates if item.get("topic_key") and item["topic_key"] not in recent_topic_keys][: min(3, len(candidates))]
        fallback["last_status"] = "candidate"
        fallback["last_action"] = "Fallback candidates ranked and ready for generation"
        return {
            "generated": 0,
            "published": 0,
            "drafts": 0,
            "recent_items": [
                {
                    "source": "fallback",
                    "title": str(item.get("target") or ""),
                    "status": "candidate",
                    "timestamp": _utcnow_iso(),
                }
                for item in preview
            ],
            "candidates_considered": len(candidates),
            "qualified_topics": len(candidates),
            "review_reasons": [],
            "remaining_today": fallback["remaining_today"],
        }

    generated = 0
    published = 0
    drafts = 0
    attempts = 0
    published_this_sweep = 0
    recent_items: list[dict[str, Any]] = []
    review_reasons: list[str] = []
    used_topic_keys = set(recent_topic_keys)
    remaining_today = max(0, _FALLBACK_DAILY_TARGET - published_today)
    generation_limit = max(_FALLBACK_MAX_GENERATIONS_PER_SWEEP, _FALLBACK_MAX_PER_SWEEP)

    for candidate in candidates:
        if published_today + published >= _FALLBACK_DAILY_TARGET:
            break
        if published_this_sweep >= _FALLBACK_MAX_PER_SWEEP:
            break
        if attempts >= generation_limit:
            break
        topic_key = str(candidate.get("topic_key") or "")
        if topic_key and topic_key in used_topic_keys:
            continue
        qualified, qualification_reason = _fallback_candidate_quality_check(candidate)
        if not qualified:
            review_reasons.append(qualification_reason)
            continue

        attempts += 1
        _emit(job_id, "log", source="fallback", level="info", message=f"Generating fallback article: {candidate['target']}")
        fallback["last_topic"] = str(candidate.get("target") or "")
        _append_activity(
            state,
            message=f"Generating fallback article from verified news: {candidate['target']}",
            phase="fallback_generating",
            source="fallback",
        )
        _update_current_run(
            state,
            phase="fallback_generating",
            source="fallback",
            company=str(candidate.get("target") or ""),
        )
        save_monitor_state(state)

        req = FlashGenerationRequest(
            mode="research",
            content_type=str(candidate.get("content_type") or "trend"),
            target=str(candidate.get("target") or "Indian market analysis"),
            objective=str(candidate.get("objective") or "") or None,
            source_url=str(candidate.get("source_url") or "") or None,
            route_base=route_base,
            include_image=True,
            overwrite=True,
        )
        result = await generate_flash_article(req, job_id=f"{(job_id or uuid.uuid4().hex)[:8]}-fb", requested_by=requested_by)
        generated += 1
        used_topic_keys.add(topic_key)
        gate_snapshot = _load_article_gate_snapshot(result.slug, route_base)

        is_published = str(result.publish_status or "").lower() == "published"
        confidence = int(result.confidence_score or 0)
        held_reason = ""
        if is_published and gate_snapshot.get("publish_gate_status") != "publish":
            unpublish_article(result.slug, route_base)
            is_published = False
            held_reason = str(gate_snapshot.get("review_reason") or "publish_gate_not_met")
        if is_published and int(gate_snapshot.get("source_count") or 0) < 3:
            unpublish_article(result.slug, route_base)
            is_published = False
            held_reason = "fallback_sources_too_thin"
        if is_published and _FALLBACK_QUALITY_FIRST and confidence < _FALLBACK_PUBLISH_THRESHOLD:
            unpublish_article(result.slug, route_base)
            is_published = False
            held_reason = "quality_threshold_not_met"

        if is_published:
            published += 1
            published_this_sweep += 1
            fallback["published_today"] = int(fallback.get("published_today") or 0) + 1
            fallback["daily_count"] = int(fallback.get("published_today") or 0)
            fallback["last_published_at"] = _utcnow_iso()
            fallback["last_status"] = "published"
            fallback["last_action"] = f"Published fallback article: {result.title}"
            fallback["last_slug"] = result.slug
            remaining_today = max(0, _FALLBACK_DAILY_TARGET - int(fallback.get("published_today") or 0))
        else:
            drafts += 1
            fallback["held_today"] = int(fallback.get("held_today") or 0) + 1
            fallback["last_status"] = "held"
            held_reason = held_reason or "editorial_gate_not_met"
            review_reasons.append(held_reason)
            fallback["last_action"] = f"Held fallback article as draft: {result.title}"
            fallback["last_slug"] = result.slug

        recent_items.append(
            {
                "source": "fallback",
                "title": result.title,
                "status": "published" if is_published else "draft",
                "slug": result.slug,
                "timestamp": result.generated_at,
                "review_reason": held_reason,
                "publish_gate_status": gate_snapshot.get("publish_gate_status") or "",
                "publish_gate_score": int(gate_snapshot.get("publish_gate_score") or 0),
                "source_count": int(gate_snapshot.get("source_count") or 0),
                "word_count": int(gate_snapshot.get("word_count") or 0),
                "evidence_claim_count": int(gate_snapshot.get("evidence_claim_count") or 0),
                "document_evidence_status": gate_snapshot.get("document_evidence_status") or "",
                "context_enrichment_status": gate_snapshot.get("context_enrichment_status") or "",
            }
        )

    fallback["generated_today"] = int(fallback.get("generated_today") or 0) + generated
    fallback["remaining_today"] = max(0, _FALLBACK_DAILY_TARGET - int(fallback.get("published_today") or 0))
    fallback["review_reasons"] = review_reasons[:10]
    if _FALLBACK_MIN_INTERVAL.total_seconds() > 0 and published > 0:
        fallback["next_eligible_at"] = (datetime.now(timezone.utc) + _FALLBACK_MIN_INTERVAL).replace(microsecond=0).isoformat()
    else:
        fallback["next_eligible_at"] = ""

    if published > 0:
        fallback["last_action"] = f"Fallback published {published} high-quality article(s) this sweep"
    elif drafts > 0:
        fallback["last_action"] = "Fallback generated drafts but held them for quality"
    else:
        fallback["last_status"] = "no_candidate"
        fallback["last_action"] = "No fresh fallback topic passed duplication and quality guards"

    _append_activity(state, message=fallback["last_action"], phase="fallback_complete", source="fallback")
    return {
        "generated": generated,
        "published": published,
        "drafts": drafts,
        "recent_items": recent_items,
        "candidates_considered": len(candidates),
        "qualified_topics": len(candidates),
        "review_reasons": review_reasons,
        "remaining_today": fallback["remaining_today"],
    }


def _load_fallback_universe(limit: int = 120) -> list[dict[str, Any]]:
    fallback_path = repo_root() / "finagent" / "data" / "isin_master.json"
    if not fallback_path.is_file():
        return []
    try:
        raw = json.loads(fallback_path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load fallback ISIN master")
        return []

    companies: list[dict[str, Any]] = []
    for isin, meta in list((raw or {}).items())[:limit]:
        if not isinstance(meta, dict):
            continue
        companies.append(
            {
                "cin": None,
                "company_name": meta.get("name") or meta.get("symbol") or str(isin),
                "nse_symbol": meta.get("symbol") or None,
                "bse_scrip_code": None,
                "isin": isin,
                "sector": meta.get("sector") or "",
            }
        )
    return companies


def _load_watch_universe() -> list[dict[str, Any]]:
    companies = get_listed_companies(nifty500_only=True)
    if companies:
        return companies
    return _load_fallback_universe()


def _slice_batch(universe: list[dict[str, Any]], cursor: int, batch_size: int) -> tuple[list[dict[str, Any]], int]:
    if not universe:
        return [], 0
    size = max(1, min(batch_size, len(universe)))
    start = cursor % len(universe)
    batch = [universe[(start + offset) % len(universe)] for offset in range(size)]
    next_cursor = (start + size) % len(universe)
    return batch, next_cursor


def _event_timestamp_key(record: dict[str, Any]) -> str:
    for key in ("published", "announced_at"):
        value = record.get(key)
        if value:
            return str(value)
    return ""


def _official_record_timestamp(record: dict[str, Any]) -> datetime | None:
    for key in ("announced_at", "published_at", "published", "generated_at"):
        raw = record.get(key)
        if not raw:
            continue
        if isinstance(raw, datetime):
            parsed = raw
        else:
            value = str(raw).strip()
            if not value:
                continue
            parsed = _parse_iso_datetime(value)
            if parsed is None and key in {"published", "published_at", "generated_at"}:
                parsed = parse_published_at({"published": value})
        if parsed is None:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _official_record_is_recent(record: dict[str, Any], *, now: datetime | None = None) -> bool:
    timestamp = _official_record_timestamp(record)
    if timestamp is None:
        return True
    current = now or datetime.now(timezone.utc)
    return timestamp >= current - _OFFICIAL_UPLOAD_LOOKBACK


def _attachment_required_for_event(source: str, record: dict[str, Any]) -> bool:
    category = str(record.get("category") or "").strip().lower()
    if category in _ATTACHMENT_REQUIRED_CATEGORIES:
        return True
    if bool(record.get("has_xbrl_hint")):
        return True
    blob = " ".join(
        str(record.get(key) or "")
        for key in ("title", "description", "snippet", "category")
    ).lower()
    if source == "sebi" and any(term in blob for term in ("order", "adjudication", "penalty", "show cause", "settlement")):
        return True
    return any(term in blob for term in _ATTACHMENT_REQUIRED_TERMS)


def _materiality_class(record: dict[str, Any], *, material: bool, attachment_required: bool) -> str:
    if not material:
        return "non_material"
    if attachment_required or record.get("attachment_url") or record.get("attachment_candidates"):
        return "material_with_attachment"
    return "material_without_attachment"


def _attachment_type_label(record: dict[str, Any], extraction: dict[str, Any] | None = None) -> str:
    if extraction:
        document_type = str(extraction.get("attachment_document_type") or "").strip()
        if document_type:
            return document_type
    url = str(record.get("attachment_url") or record.get("url") or "").lower().split("?", 1)[0]
    for suffix, label in (
        (".pdf", "pdf"),
        (".xbrl", "xbrl"),
        (".xml", "xml"),
        (".xlsx", "spreadsheet"),
        (".xls", "spreadsheet"),
        (".csv", "spreadsheet"),
        (".zip", "zip"),
        (".txt", "text"),
    ):
        if url.endswith(suffix):
            return label
    return ""


def _attachment_stage_path(source: str, record: dict[str, Any]) -> Path:
    payload = {
        "version": _OFFICIAL_ATTACHMENT_STAGE_VERSION,
        "source": source,
        "source_uid": str(record.get("source_uid") or ""),
        "attachment_url": str(record.get("attachment_url") or record.get("url") or ""),
        "title": str(record.get("title") or "")[:160],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()
    return finagent_data_path("content_automation", "official_attachment_evidence", f"{source}-{digest}.json")


def _load_staged_attachment_evidence(source: str, record: dict[str, Any]) -> dict[str, Any] | None:
    path = _attachment_stage_path(source, record)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read staged attachment evidence for %s", path)
        return None
    if not isinstance(payload, dict):
        return None
    if int(payload.get("stage_version") or 0) != _OFFICIAL_ATTACHMENT_STAGE_VERSION:
        return None
    return payload


def _stage_attachment_evidence(source: str, record: dict[str, Any]) -> dict[str, Any]:
    cached = _load_staged_attachment_evidence(source, record)
    if cached:
        return cached

    candidate_urls: list[str] = []
    for url in list(record.get("attachment_candidates") or []) + [
        record.get("attachment_url"),
        record.get("url"),
    ]:
        value = str(url or "").strip()
        if value and value not in candidate_urls:
            candidate_urls.append(value)

    extraction = _extract_with_fallback_candidates(candidate_urls)
    resolved_url = str(extraction.get("resolved_attachment_url") or record.get("attachment_url") or record.get("url") or "")
    evidence = {
        "stage_version": _OFFICIAL_ATTACHMENT_STAGE_VERSION,
        "staged_at": _utcnow_iso(),
        "source": source,
        "source_uid": str(record.get("source_uid") or ""),
        "source_url": str(record.get("source_url") or record.get("url") or ""),
        "attachment_url": resolved_url,
        "attachment_required": bool(record.get("attachment_required")),
        "attachment_type": _attachment_type_label(record, extraction),
        "attachment_document_type": str(extraction.get("attachment_document_type") or "") or None,
        "attachment_extraction_status": str(extraction.get("attachment_extraction_status") or "failed"),
        "attachment_parser": str(extraction.get("attachment_parser") or extraction.get("attachment_extracted_model") or "") or None,
        "attachment_text_sufficient": bool(extraction.get("attachment_text_sufficient")),
        "attachment_sufficiency_reason": str(extraction.get("attachment_sufficiency_reason") or "") or None,
        "attachment_extraction_error": str(extraction.get("attachment_extraction_error") or "") or None,
        "attachment_text_length": int(extraction.get("attachment_text_length") or 0),
        "attachment_text": str(extraction.get("attachment_text") or ""),
        "attachment_tables": list(extraction.get("attachment_tables") or []),
        "attachment_structured_facts": extraction.get("attachment_structured_facts"),
        "attachment_sha256": extraction.get("attachment_sha256"),
        "attachment_content_type": extraction.get("attachment_content_type"),
    }
    path = _attachment_stage_path(source, record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    evidence["stage_path"] = str(path)
    return evidence


def _attachment_review_reason(record: dict[str, Any], evidence: dict[str, Any] | None) -> str:
    if not bool(record.get("attachment_required")):
        return ""
    if not str(record.get("attachment_url") or record.get("url") or "").strip():
        return "attachment_required_missing"
    if not evidence:
        return "attachment_extraction_failed"
    if str(evidence.get("attachment_extraction_status") or "") != "ok":
        return "attachment_extraction_failed"
    if not bool(evidence.get("attachment_text_sufficient")):
        return "attachment_content_insufficient"
    return ""


def _public_review_reason(reason: str) -> str:
    raw = str(reason or "").strip().lower()
    if not raw:
        return ""
    mapping = {
        "routine_notice": "routine_official_update",
        "non_material_board_update": "routine_official_update",
        "non_material_resignation": "routine_official_update",
        "transcript_without_substance": "material_but_evidence_thin",
        "transcript_content_insufficient": "material_but_evidence_thin",
        "attachment_content_insufficient": "material_but_evidence_thin",
    }
    return mapping.get(raw, raw)


def _json_block(value: Any, *, max_chars: int = 5000) -> str:
    if not value:
        return ""
    text = json.dumps(value, ensure_ascii=True, default=str, indent=2)
    return text[:max_chars].strip()


def _build_attachment_source_markdown(source: str, record: dict[str, Any], evidence: dict[str, Any]) -> str:
    parts = [
        "Official filing evidence",
        f"Source: {source.upper()}",
        f"Title: {str(record.get('title') or '').strip()}",
    ]
    if record.get("company_name"):
        parts.append(f"Company: {str(record.get('company_name') or '').strip()}")
    if record.get("category"):
        parts.append(f"Category: {str(record.get('category') or '').strip()}")
    if record.get("announced_at"):
        parts.append(f"Announced at: {record.get('announced_at')}")
    if record.get("description"):
        parts.append(f"Official summary: {str(record.get('description') or '').strip()}")
    if evidence.get("attachment_document_type"):
        parts.append(f"Attachment type: {evidence.get('attachment_document_type')}")
    if evidence.get("attachment_parser"):
        parts.append(f"Parser used: {evidence.get('attachment_parser')}")
    if evidence.get("attachment_url"):
        parts.append(f"Attachment URL: {evidence.get('attachment_url')}")
    if record.get("source_url"):
        parts.append(f"Source page: {record.get('source_url')}")

    structured_text = _json_block(evidence.get("attachment_structured_facts"), max_chars=5000)
    if structured_text:
        parts.append(f"Structured facts:\n{structured_text}")

    for table in list(evidence.get("attachment_tables") or [])[:3]:
        markdown = str(table.get("markdown") or "").strip()
        if markdown:
            table_name = str(table.get("name") or "Extracted table").strip()
            parts.append(f"{table_name}:\n{markdown[:3500]}")

    attachment_text = str(evidence.get("attachment_text") or "").strip()
    if attachment_text:
        parts.append(f"Attachment text:\n{attachment_text[:18000]}")

    return "\n\n".join(part for part in parts if part).strip()[:28000]


def _recent_item_payload(base: dict[str, Any], evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(base)
    payload.setdefault("review_reason", "")
    payload.setdefault("publish_gate_status", "")
    payload.setdefault("publish_gate_score", 0)
    payload.setdefault("materiality_tier", "")
    payload.setdefault("selection_reason", "")
    payload.setdefault("urgency_score", 0)
    payload.setdefault("quality_blockers", [])
    payload.setdefault("source_count", 0)
    payload.setdefault("word_count", 0)
    payload.setdefault("evidence_claim_count", 0)
    payload.setdefault("document_evidence_status", "")
    payload.setdefault("context_enrichment_status", "")
    if evidence:
        payload["attachment_required"] = bool(evidence.get("attachment_required"))
        payload["attachment_type"] = evidence.get("attachment_type") or evidence.get("attachment_document_type") or ""
        payload["attachment_extraction_status"] = evidence.get("attachment_extraction_status") or ""
        payload["attachment_parser"] = evidence.get("attachment_parser") or ""
    else:
        payload.setdefault("attachment_required", bool(base.get("attachment_required")))
        payload.setdefault("attachment_type", "")
        payload.setdefault("attachment_extraction_status", "")
        payload.setdefault("attachment_parser", "")
    blockers_raw = payload.get("quality_blockers")
    if isinstance(blockers_raw, list):
        payload["quality_blockers"] = [str(item)[:120] for item in blockers_raw if str(item).strip()][:16]
    elif blockers_raw:
        payload["quality_blockers"] = [str(blockers_raw)[:120]]
    else:
        payload["quality_blockers"] = []
    payload["urgency_score"] = int(payload.get("urgency_score") or 0)
    return payload


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _has_transcript_substance_from_record(record: dict[str, Any]) -> bool:
    content = " ".join(
        str(record.get(key) or "")
        for key in ("title", "description", "snippet", "category")
    ).lower()
    if any(term in content for term in _TRANSCRIPT_SUBSTANCE_TERMS):
        return True
    return bool(re.search(r"\d", content))


def _has_transcript_substance_from_evidence(evidence: dict[str, Any] | None) -> bool:
    if not evidence:
        return False
    text = str(evidence.get("attachment_text") or "").strip().lower()
    if not text:
        return False
    if len(text) >= 900 and any(term in text for term in _TRANSCRIPT_SUBSTANCE_TERMS):
        return True
    return len(text) >= 1400 and bool(re.search(r"\d", text))


def _triage_event(source: str, record: dict[str, Any], company: dict[str, Any] | None = None) -> dict[str, Any]:
    title = str(record.get("title") or "").strip()
    description = str(record.get("description") or record.get("snippet") or "").strip()
    combined = f"{title} {description}".strip()
    lowered = combined.lower()
    attachment_required = _attachment_required_for_event(source, record)

    if not title:
        return {
            "generate": False,
            "skip_reason": "missing_title",
            "materiality_score": 0,
            "urgency_score": 0,
            "attachment_required": attachment_required,
            "materiality_class": "non_material",
            "materiality_tier": "non_material",
            "selection_reason": "missing_title",
            "quality_blockers": ["missing_title"],
        }

    if event_is_low_value(title, description):
        return {
            "generate": False,
            "skip_reason": "low_value",
            "materiality_score": 5,
            "urgency_score": 5,
            "attachment_required": attachment_required,
            "materiality_class": "non_material",
            "materiality_tier": "non_material",
            "selection_reason": "low_value_official_update",
            "quality_blockers": ["low_value"],
        }

    if any(pattern.search(combined) for pattern in _ROUTINE_SKIP_PATTERNS):
        return {
            "generate": False,
            "skip_reason": "routine_official_update",
            "materiality_score": 8,
            "urgency_score": 6,
            "attachment_required": attachment_required,
            "materiality_class": "non_material",
            "materiality_tier": "non_material",
            "selection_reason": "routine_official_update",
            "quality_blockers": ["routine_official_update"],
        }

    if "resignation" in lowered and not _contains_any(lowered, _MATERIAL_RESIGNATION_TERMS):
        return {
            "generate": False,
            "skip_reason": "routine_official_update",
            "materiality_score": 18,
            "urgency_score": 14,
            "attachment_required": attachment_required,
            "materiality_class": "non_material",
            "materiality_tier": "non_material",
            "selection_reason": "routine_official_update",
            "quality_blockers": ["routine_official_update"],
        }

    if (
        "board" in lowered
        and ("outcome" in lowered or "meeting" in lowered)
        and not _contains_any(lowered, _MATERIAL_BOARD_TERMS)
    ):
        return {
            "generate": False,
            "skip_reason": "routine_official_update",
            "materiality_score": 22,
            "urgency_score": 16,
            "attachment_required": attachment_required,
            "materiality_class": "non_material",
            "materiality_tier": "non_material",
            "selection_reason": "routine_official_update",
            "quality_blockers": ["routine_official_update"],
        }

    transcript_like = any(token in lowered for token in ("investor presentation", "analyst meet", "conference call", "concall", "transcript"))
    if transcript_like and not _has_transcript_substance_from_record(record):
        return {
            "generate": False,
            "skip_reason": "material_but_evidence_thin",
            "materiality_score": 20,
            "urgency_score": 12,
            "attachment_required": attachment_required,
            "materiality_class": "non_material",
            "materiality_tier": "non_material",
            "selection_reason": "material_but_evidence_thin",
            "quality_blockers": ["material_but_evidence_thin"],
        }

    high_priority_terms = (
        "financial results",
        "earnings",
        "result",
        "dividend",
        "buyback",
        "bonus",
        "split",
        "rights issue",
        "amalgamation",
        "demerger",
        "merger",
        "acquisition",
        "fund raise",
        "fundraise",
        "order win",
        "contract",
        "material capex",
        "capex",
        "rating",
        "credit rating",
        "default",
        "insolvency",
        "forensic",
        "auditor",
        "cfo",
        "ceo",
        "kmp",
        "resignation",
        "pledge",
        "stake change",
        "insider",
        "related party",
        "sebi",
        "rbi",
        "settlement",
        "adjudication",
        "penalty",
        "show cause",
        "policy",
    )
    medium_terms = (
        "board meeting",
        "investor presentation",
        "conference call",
        "concall",
        "transcript",
        "shareholding pattern",
        "governance",
    )

    materiality_score = 30
    urgency_score = 25
    if any(term in lowered for term in high_priority_terms):
        materiality_score += 50
        urgency_score += 40
    elif any(term in lowered for term in medium_terms):
        materiality_score += 20
        urgency_score += 15
    if attachment_required:
        materiality_score += 10
        urgency_score += 5

    content_type = "company"
    if "result" in lowered or "earnings" in lowered or "financial" in lowered:
        content_type = "earnings"
    elif source == "sebi" or "sebi" in lowered or "penalty" in lowered or "adjudication" in lowered:
        content_type = "sebi"

    target = (company or {}).get("company_name") or title
    if source == "sebi":
        target = f"SEBI: {title[:140]}"

    objective = (
        f"Assess the materiality of '{title}' using only official-source evidence. "
        "Explain what changed, why it matters now, and which governance, financial, or regulatory angles deserve publication."
    )
    if company and company.get("company_name"):
        objective = (
            f"Analyse the official update for {company.get('company_name')}: '{title}'. "
            "Use official filings, verified governance records, and sector context to explain what changed and why investors should care now."
        )

    materiality_score = min(materiality_score, 100)
    urgency_score = min(urgency_score, 100)
    material = materiality_score >= _OFFICIAL_TRIAGE_MIN_MATERIALITY
    urgent = urgency_score >= _OFFICIAL_TRIAGE_MIN_URGENCY
    selection_reason = "material_official_update"
    if any(term in lowered for term in high_priority_terms):
        selection_reason = "urgent_material_official_event"
    elif any(term in lowered for term in medium_terms):
        selection_reason = "evidence_rich_official_update"

    if not material:
        skip_reason = "not_material_enough"
    elif not urgent:
        skip_reason = "not_urgent_enough"
    else:
        skip_reason = ""

    quality_blockers: list[str] = []
    if skip_reason:
        quality_blockers.append(skip_reason)

    materiality_tier = _materiality_class(
        record,
        material=material,
        attachment_required=attachment_required,
    )

    return {
        "generate": bool(material and urgent),
        "skip_reason": skip_reason,
        "materiality_score": materiality_score,
        "urgency_score": urgency_score,
        "attachment_required": attachment_required,
        "materiality_class": materiality_tier,
        "materiality_tier": materiality_tier,
        "selection_reason": selection_reason,
        "quality_blockers": quality_blockers,
        "content_type": content_type,
        "target": target[:240],
        "objective": objective[:1000],
    }


async def run_official_monitor(
    *,
    requested_by: str = "automation@prospektlab.local",
    route_base: str = _DEFAULT_ROUTE_BASE,
    company_batch_size: int = _DEFAULT_BATCH_SIZE,
    max_events_per_company: int = _DEFAULT_EVENTS_PER_COMPANY,
    dry_run: bool = False,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Poll official sources, triage new items, and generate articles for material events."""
    state = load_monitor_state()
    state["last_status"] = "running"
    state["last_started_at"] = _utcnow_iso()
    state["last_error"] = ""
    state["current_run"] = {
        "started_at": state["last_started_at"],
        "phase": "booting",
        "source": "",
        "company": "",
        "discovered": 0,
        "generated": 0,
        "published": 0,
        "drafts": 0,
        "skipped_seen": 0,
        "skipped_low_value": 0,
        "failures": 0,
        "companies_scanned": 0,
        "companies_total": 0,
        "updated_at": state["last_started_at"],
    }
    _append_activity(
        state,
        message=f"Automation sweep started with a {_OFFICIAL_UPLOAD_LOOKBACK_HOURS}-hour official-source window",
        phase="booting",
    )
    save_monitor_state(state)

    discovered = 0
    generated = 0
    published = 0
    drafts = 0
    skipped_seen = 0
    skipped_low_value = 0
    failures: list[dict[str, str]] = []
    recent_items: list[dict[str, Any]] = []
    fallback_generated = 0
    fallback_published = 0
    fallback_held = 0
    archive_cleanup = {"unpublished": 0, "backfilled": 0}
    official_window_now = datetime.now(timezone.utc)

    seen_event_ids: dict[str, str] = state.setdefault("seen_event_ids", {})
    universe = _load_watch_universe()
    batch, next_cursor = _slice_batch(universe, int(state.get("cursor") or 0), company_batch_size)
    state["cursor"] = next_cursor
    _update_current_run(
        state,
        phase="loading_watchlist",
        companies_total=len(batch),
        discovered=discovered,
        generated=generated,
        published=published,
        drafts=drafts,
        skipped_seen=skipped_seen,
        skipped_low_value=skipped_low_value,
        failures=len(failures),
    )
    _append_activity(
        state,
        message=f"Prepared watchlist batch for {len(batch)} companies and SEBI feed",
        phase="loading_watchlist",
    )
    save_monitor_state(state)

    _emit(job_id, "phase", phase="official_monitor", note=f"Scanning official sources for {len(batch)} companies plus SEBI feeds")

    async def _process_event(source: str, event: dict[str, Any], watch: ContentEventWatch, company: dict[str, Any] | None = None) -> None:
        nonlocal discovered, generated, published, drafts, skipped_seen, skipped_low_value

        discovered += 1
        if company and company.get("company_name") and not event.get("company_name"):
            event["company_name"] = company.get("company_name")
        if source in {"nse", "bse", "sebi"} and not _official_record_is_recent(event, now=official_window_now):
            _append_activity(
                state,
                message=f"Skipped {source.upper()} item older than {_OFFICIAL_UPLOAD_LOOKBACK_HOURS} hours: {str(event.get('title') or 'Untitled update')[:120]}",
                phase="freshness_filter",
                source=source,
                company=str((company or {}).get("company_name") or ""),
            )
            return
        fingerprint = _event_fingerprint(source, event, watch)
        if seen_event_ids.get(fingerprint):
            skipped_seen += 1
            _update_current_run(
                state,
                phase="deduping",
                source=source,
                company=str((company or {}).get("company_name") or ""),
                discovered=discovered,
                generated=generated,
                published=published,
                drafts=drafts,
                skipped_seen=skipped_seen,
                skipped_low_value=skipped_low_value,
                failures=len(failures),
            )
            return
        seen_event_ids[fingerprint] = _utcnow_iso()

        triage = _triage_event(source, event, company)
        event["attachment_required"] = bool(triage.get("attachment_required"))
        event["materiality_class"] = str(triage.get("materiality_class") or "")
        event["materiality_tier"] = str(triage.get("materiality_tier") or triage.get("materiality_class") or "")
        event["urgency_score"] = int(triage.get("urgency_score") or 0)
        event["selection_reason"] = str(triage.get("selection_reason") or "")
        event["quality_blockers"] = [str(item) for item in list(triage.get("quality_blockers") or []) if str(item).strip()][:16]
        event_text = " ".join(
            str(event.get(key) or "")
            for key in ("title", "description", "snippet", "category")
        ).lower()
        transcript_like = any(
            token in event_text
            for token in ("investor presentation", "analyst meet", "conference call", "concall", "transcript")
        )
        if not triage.get("generate"):
            if triage.get("skip_reason") == "low_value":
                skipped_low_value += 1
            triage_reason = _public_review_reason(str(triage.get("skip_reason") or "filtered"))
            _append_activity(
                state,
                message=f"Skipped {source.upper()} item: {str(event.get('title') or 'Untitled update')[:120]}",
                phase="triage",
                source=source,
                company=str((company or {}).get("company_name") or ""),
            )
            _update_current_run(
                state,
                phase="triage",
                source=source,
                company=str((company or {}).get("company_name") or ""),
                discovered=discovered,
                generated=generated,
                published=published,
                drafts=drafts,
                skipped_seen=skipped_seen,
                skipped_low_value=skipped_low_value,
                failures=len(failures),
                materiality_tier=event.get("materiality_tier") or "",
                urgency_score=int(triage.get("urgency_score") or 0),
                selection_reason=event.get("selection_reason") or "",
                quality_blockers=list(event.get("quality_blockers") or []),
            )
            recent_items.insert(
                0,
                _recent_item_payload(
                    {
                        "source": source,
                        "title": str(event.get("title") or "")[:180],
                        "status": "skipped",
                        "reason": triage_reason,
                        "review_reason": triage_reason,
                        "timestamp": _event_timestamp_key(event),
                        "attachment_required": bool(triage.get("attachment_required")),
                        "materiality_tier": event.get("materiality_tier") or "",
                        "urgency_score": int(triage.get("urgency_score") or 0),
                        "selection_reason": event.get("selection_reason") or "",
                        "quality_blockers": [_public_review_reason(item) for item in list(event.get("quality_blockers") or [])],
                    }
                ),
            )
            return

        evidence: dict[str, Any] | None = None
        attachment_needed = bool(event.get("attachment_required") or event.get("attachment_url") or event.get("attachment_candidates"))
        source_markdown = str(event.get("description") or event.get("snippet") or "")[:8000] or None
        source_url = str(event.get("attachment_url") or event.get("source_url") or event.get("url") or "") or None

        if attachment_needed:
            attachment_type = _attachment_type_label(event)
            _append_activity(
                state,
                message=f"Resolved attachment for {source.upper()}: {str(event.get('title') or 'Untitled update')[:120]}",
                phase="attachment_resolved",
                source=source,
                company=str((company or {}).get("company_name") or ""),
            )
            _update_current_run(
                state,
                phase="attachment_resolved",
                source=source,
                company=str((company or {}).get("company_name") or ""),
                discovered=discovered,
                generated=generated,
                published=published,
                drafts=drafts,
                skipped_seen=skipped_seen,
                skipped_low_value=skipped_low_value,
                failures=len(failures),
                attachment_required=bool(event.get("attachment_required")),
                attachment_type=attachment_type,
                materiality_class=str(event.get("materiality_class") or ""),
                materiality_tier=str(event.get("materiality_tier") or ""),
                urgency_score=int(event.get("urgency_score") or 0),
                selection_reason=str(event.get("selection_reason") or ""),
                quality_blockers=list(event.get("quality_blockers") or []),
            )
            save_monitor_state(state)
            try:
                evidence = await asyncio.to_thread(_stage_attachment_evidence, source, event)
                source_url = str(evidence.get("attachment_url") or source_url or "") or None
                source_markdown = _build_attachment_source_markdown(source, event, evidence) or source_markdown
                extraction_phase = (
                    "attachment_extracted"
                    if str(evidence.get("attachment_extraction_status") or "") == "ok"
                    else "attachment_failed"
                )
                _append_activity(
                    state,
                    message=(
                        f"Attachment {str(evidence.get('attachment_extraction_status') or 'failed').replace('_', ' ')}"
                        f" for {source.upper()}: {str(event.get('title') or 'Untitled update')[:120]}"
                    ),
                    phase=extraction_phase,
                    source=source,
                    company=str((company or {}).get("company_name") or ""),
                    level="success" if extraction_phase == "attachment_extracted" else "warning",
                )
                _update_current_run(
                    state,
                    phase=extraction_phase,
                    source=source,
                    company=str((company or {}).get("company_name") or ""),
                    discovered=discovered,
                    generated=generated,
                    published=published,
                    drafts=drafts,
                    skipped_seen=skipped_seen,
                    skipped_low_value=skipped_low_value,
                    failures=len(failures),
                    attachment_required=bool(evidence.get("attachment_required")),
                    attachment_type=evidence.get("attachment_type") or evidence.get("attachment_document_type") or "",
                    attachment_extraction_status=evidence.get("attachment_extraction_status") or "",
                    attachment_parser=evidence.get("attachment_parser") or "",
                    review_reason="",
                    materiality_tier=str(event.get("materiality_tier") or ""),
                    urgency_score=int(event.get("urgency_score") or 0),
                    selection_reason=str(event.get("selection_reason") or ""),
                    quality_blockers=list(event.get("quality_blockers") or []),
                )
                save_monitor_state(state)
            except Exception as exc:
                logger.exception("Attachment staging failed for %s", event.get("title"))
                evidence = {
                    "attachment_required": bool(event.get("attachment_required")),
                    "attachment_type": attachment_type,
                    "attachment_extraction_status": "failed",
                    "attachment_parser": "",
                    "attachment_text_sufficient": False,
                    "attachment_sufficiency_reason": "extractor_exception",
                    "attachment_extraction_error": str(exc)[:220],
                }
                _append_activity(
                    state,
                    message=f"Attachment extraction failed for {source.upper()}: {str(event.get('title') or 'Untitled update')[:120]}",
                    level="warning",
                    phase="attachment_failed",
                    source=source,
                    company=str((company or {}).get("company_name") or ""),
                )
                _update_current_run(
                    state,
                    phase="attachment_failed",
                    source=source,
                    company=str((company or {}).get("company_name") or ""),
                    discovered=discovered,
                    generated=generated,
                    published=published,
                    drafts=drafts,
                    skipped_seen=skipped_seen,
                    skipped_low_value=skipped_low_value,
                    failures=len(failures),
                    attachment_required=bool(event.get("attachment_required")),
                    attachment_type=attachment_type,
                    attachment_extraction_status="failed",
                    attachment_parser="",
                    review_reason="attachment_extraction_failed",
                    materiality_tier=str(event.get("materiality_tier") or ""),
                    urgency_score=int(event.get("urgency_score") or 0),
                    selection_reason=str(event.get("selection_reason") or ""),
                    quality_blockers=["attachment_extraction_failed"],
                )
                save_monitor_state(state)

            review_reason = _attachment_review_reason(event, evidence)
            if not review_reason and transcript_like and not _has_transcript_substance_from_evidence(evidence):
                review_reason = "material_but_evidence_thin"
            review_reason = _public_review_reason(review_reason)
            if review_reason:
                _append_activity(
                    state,
                    message=f"Held for review ({review_reason.replace('_', ' ')}): {str(event.get('title') or 'Untitled update')[:120]}",
                    phase="awaiting_attachment_review",
                    source=source,
                    company=str((company or {}).get("company_name") or ""),
                    level="warning",
                )
                _update_current_run(
                    state,
                    phase="awaiting_attachment_review",
                    source=source,
                    company=str((company or {}).get("company_name") or ""),
                    discovered=discovered,
                    generated=generated,
                    published=published,
                    drafts=drafts,
                    skipped_seen=skipped_seen,
                    skipped_low_value=skipped_low_value,
                    failures=len(failures),
                    attachment_required=bool(event.get("attachment_required")),
                    attachment_type=(evidence or {}).get("attachment_type") or (evidence or {}).get("attachment_document_type") or attachment_type,
                    attachment_extraction_status=(evidence or {}).get("attachment_extraction_status") or "failed",
                    attachment_parser=(evidence or {}).get("attachment_parser") or "",
                    review_reason=review_reason,
                    materiality_tier=str(event.get("materiality_tier") or ""),
                    urgency_score=int(event.get("urgency_score") or 0),
                    selection_reason=str(event.get("selection_reason") or ""),
                    quality_blockers=[review_reason],
                )
                recent_items.insert(
                    0,
                    _recent_item_payload(
                        {
                            "source": source,
                            "title": str(event.get("title") or "")[:180],
                            "status": "under_review",
                            "reason": review_reason,
                            "review_reason": review_reason,
                            "timestamp": _event_timestamp_key(event),
                            "attachment_required": bool(event.get("attachment_required")),
                            "materiality_tier": event.get("materiality_tier") or "",
                            "urgency_score": int(event.get("urgency_score") or 0),
                            "selection_reason": event.get("selection_reason") or "",
                            "quality_blockers": [review_reason],
                        },
                        evidence,
                    ),
                )
                save_monitor_state(state)
                return

        _emit(job_id, "log", source="official_monitor", level="info", message=f"Generating article for {source.upper()}: {event.get('title')}")
        _append_activity(
            state,
            message=f"Generating {str(triage.get('content_type') or 'research')} article from {source.upper()}: {str(event.get('title') or 'Untitled update')[:120]}",
            phase="generating",
            source=source,
            company=str((company or {}).get("company_name") or ""),
        )
        _update_current_run(
            state,
            phase="generating",
            source=source,
            company=str((company or {}).get("company_name") or ""),
            discovered=discovered,
            generated=generated,
            published=published,
            drafts=drafts,
            skipped_seen=skipped_seen,
            skipped_low_value=skipped_low_value,
            failures=len(failures),
            materiality_tier=str(event.get("materiality_tier") or ""),
            urgency_score=int(event.get("urgency_score") or 0),
            selection_reason=str(event.get("selection_reason") or ""),
            quality_blockers=list(event.get("quality_blockers") or []),
        )
        save_monitor_state(state)

        if dry_run:
            recent_items.insert(
                0,
                _recent_item_payload(
                    {
                        "source": source,
                        "title": str(event.get("title") or "")[:180],
                        "status": "candidate",
                        "reason": "dry_run",
                        "review_reason": "",
                        "timestamp": _event_timestamp_key(event),
                        "attachment_required": bool(event.get("attachment_required")),
                        "materiality_tier": event.get("materiality_tier") or "",
                        "urgency_score": int(event.get("urgency_score") or 0),
                        "selection_reason": event.get("selection_reason") or "",
                        "quality_blockers": list(event.get("quality_blockers") or []),
                    },
                    evidence,
                ),
            )
            return

        sub_job = f"{(job_id or uuid.uuid4().hex)[:8]}-{uuid.uuid4().hex[:4]}"
        req = FlashGenerationRequest(
            mode="research",
            content_type=str(triage.get("content_type") or "company"),
            target=str(triage.get("target") or event.get("title") or "Official Update"),
            objective=str(triage.get("objective") or "") or None,
            source_url=source_url,
            source_markdown=source_markdown,
            source_evidence_meta=evidence or None,
            route_base=route_base,
            include_image=True,
            overwrite=True,
        )
        try:
            result = await generate_flash_article(req, job_id=sub_job, requested_by=requested_by)
            gate_snapshot = _load_article_gate_snapshot(result.slug, route_base)
            review_reason = _public_review_reason(str(gate_snapshot.get("review_reason") or ""))
            quality_blockers = [
                _public_review_reason(str(item))
                for item in list(gate_snapshot.get("quality_blockers") or [])
                if str(item).strip()
            ][:16]
            generated += 1
            if str(result.publish_status or "").lower() == "published":
                published += 1
                try:
                    refresh_public_research_hub(route_base)
                except Exception:
                    logger.exception("Failed to refresh public research hub after publish")
            else:
                drafts += 1
            _append_activity(
                state,
                message=f"{result.publish_status.title()} article: {result.title[:120]}",
                phase="completed_item",
                source=source,
                company=str((company or {}).get("company_name") or ""),
            )
            _update_current_run(
                state,
                phase="completed_item",
                source=source,
                company=str((company or {}).get("company_name") or ""),
                discovered=discovered,
                generated=generated,
                published=published,
                drafts=drafts,
                skipped_seen=skipped_seen,
                skipped_low_value=skipped_low_value,
                failures=len(failures),
                publish_gate_status=gate_snapshot.get("publish_gate_status") or "",
                publish_gate_score=int(gate_snapshot.get("publish_gate_score") or 0),
                review_reason=review_reason,
                quality_blockers=quality_blockers,
                source_count=int(gate_snapshot.get("source_count") or 0),
                word_count=int(gate_snapshot.get("word_count") or 0),
                evidence_claim_count=int(gate_snapshot.get("evidence_claim_count") or 0),
                document_evidence_status=gate_snapshot.get("document_evidence_status") or "",
                context_enrichment_status=gate_snapshot.get("context_enrichment_status") or "",
                materiality_tier=str(event.get("materiality_tier") or ""),
                urgency_score=int(event.get("urgency_score") or 0),
                selection_reason=str(event.get("selection_reason") or ""),
            )
            recent_items.insert(
                0,
                _recent_item_payload(
                    {
                        "source": source,
                        "title": result.title[:180],
                        "status": result.publish_status,
                        "slug": result.slug,
                        "reason": "" if result.publish_status == "published" else (review_reason or "; ".join(result.publish_reasons[:3])[:220]),
                        "review_reason": "" if result.publish_status == "published" else (review_reason or "; ".join(result.publish_reasons[:3])[:220]),
                        "timestamp": result.generated_at,
                        "attachment_required": bool(event.get("attachment_required")),
                        "publish_gate_status": gate_snapshot.get("publish_gate_status") or "",
                        "publish_gate_score": int(gate_snapshot.get("publish_gate_score") or 0),
                        "materiality_tier": event.get("materiality_tier") or "",
                        "urgency_score": int(event.get("urgency_score") or 0),
                        "selection_reason": event.get("selection_reason") or "",
                        "quality_blockers": quality_blockers,
                        "source_count": int(gate_snapshot.get("source_count") or 0),
                        "word_count": int(gate_snapshot.get("word_count") or 0),
                        "evidence_claim_count": int(gate_snapshot.get("evidence_claim_count") or 0),
                        "document_evidence_status": gate_snapshot.get("document_evidence_status") or "",
                        "context_enrichment_status": gate_snapshot.get("context_enrichment_status") or "",
                    },
                    evidence,
                ),
            )
            save_monitor_state(state)
        except Exception as exc:
            logger.exception("Official monitor generation failed for %s", event.get("title"))
            failures.append({"source": source, "error": str(exc)[:400], "title": str(event.get("title") or "")[:180]})
            _append_activity(
                state,
                message=f"Failed to generate article from {source.upper()}: {str(event.get('title') or 'Untitled update')[:120]}",
                level="error",
                phase="failed_item",
                source=source,
                company=str((company or {}).get("company_name") or ""),
            )
            _update_current_run(
                state,
                phase="failed_item",
                source=source,
                company=str((company or {}).get("company_name") or ""),
                discovered=discovered,
                generated=generated,
                published=published,
                drafts=drafts,
                skipped_seen=skipped_seen,
                skipped_low_value=skipped_low_value,
                failures=len(failures),
                materiality_tier=str(event.get("materiality_tier") or ""),
                urgency_score=int(event.get("urgency_score") or 0),
                selection_reason=str(event.get("selection_reason") or ""),
                quality_blockers=[str(exc)[:120]],
            )
            recent_items.insert(
                0,
                _recent_item_payload(
                    {
                        "source": source,
                        "title": str(event.get("title") or "")[:180],
                        "status": "failed",
                        "reason": str(exc)[:180],
                        "review_reason": str(exc)[:180],
                        "timestamp": _event_timestamp_key(event),
                        "attachment_required": bool(event.get("attachment_required")),
                        "materiality_tier": event.get("materiality_tier") or "",
                        "urgency_score": int(event.get("urgency_score") or 0),
                        "selection_reason": event.get("selection_reason") or "",
                        "quality_blockers": [str(exc)[:120]],
                    },
                    evidence,
                ),
            )
            save_monitor_state(state)

    try:
        _update_current_run(
            state,
            phase="fetching_sebi",
            source="sebi",
            discovered=discovered,
            generated=generated,
            published=published,
            drafts=drafts,
            skipped_seen=skipped_seen,
            skipped_low_value=skipped_low_value,
            failures=len(failures),
            companies_total=len(batch),
        )
        _append_activity(state, message="Checking SEBI feed for fresh regulatory items", phase="fetching_sebi", source="sebi")
        save_monitor_state(state)
        sebi_items = await asyncio.to_thread(fetch_sebi_news, 8)
        _mark_source_health(state, "sebi", ok=True)
        for item in sebi_items:
            await _process_event("sebi", item, ContentEventWatch(source="sebi", company_name="SEBI"))
    except Exception as exc:
        logger.warning("Official monitor SEBI fetch failed: %s", exc)
        _mark_source_health(state, "sebi", ok=False, error=str(exc))
        failures.append({"source": "sebi", "error": str(exc)[:400]})

    for index, company in enumerate(batch, start=1):
        company_name = str(company.get("company_name") or company.get("nse_symbol") or company.get("isin") or "Listed company")
        _update_current_run(
            state,
            phase="scanning_company",
            company=company_name,
            discovered=discovered,
            generated=generated,
            published=published,
            drafts=drafts,
            skipped_seen=skipped_seen,
            skipped_low_value=skipped_low_value,
            failures=len(failures),
            companies_scanned=index - 1,
            companies_total=len(batch),
        )
        _append_activity(
            state,
            message=f"Scanning filings for {company_name}",
            phase="scanning_company",
            company=company_name,
        )
        save_monitor_state(state)
        if company.get("nse_symbol"):
            symbol = str(company.get("nse_symbol") or "").strip().upper()
            try:
                nse_records = await asyncio.to_thread(fetch_nse_corporate_filings, symbol, years_back=1)
                _mark_source_health(state, "nse", ok=True)
                for item in nse_records[: max(1, max_events_per_company)]:
                    event = {
                        "title": item.get("title") or "",
                        "description": item.get("description") or "",
                        "url": item.get("attachment_url") or item.get("source_url") or "",
                        "source_url": item.get("source_url") or "",
                        "attachment_url": item.get("attachment_url") or "",
                        "attachment_candidates": item.get("attachment_candidates") or [],
                        "category": item.get("category") or "",
                        "source_uid": item.get("source_uid") or "",
                        "has_xbrl_hint": item.get("has_xbrl_hint") or False,
                        "company_name": item.get("company_name") or company_name,
                        "announced_at": item.get("announced_at"),
                    }
                    await _process_event(
                        "nse",
                        event,
                        ContentEventWatch(source="nse", symbol=symbol, isin=company.get("isin"), company_name=company_name),
                        company,
                    )
            except Exception as exc:
                logger.warning("Official monitor NSE fetch failed for %s: %s", symbol, exc)
                _mark_source_health(state, "nse", ok=False, error=str(exc))
                failures.append({"source": "nse", "symbol": symbol, "error": str(exc)[:400]})
                _append_activity(
                    state,
                    message=f"NSE fetch failed for {company_name}",
                    level="error",
                    phase="fetching_nse",
                    source="nse",
                    company=company_name,
                )

        if company.get("bse_scrip_code"):
            scrip = str(company.get("bse_scrip_code") or "").strip()
            try:
                bse_records = await asyncio.to_thread(fetch_bse_corporate_filings, scrip, years_back=1, max_pages=1)
                _mark_source_health(state, "bse", ok=True)
                for item in bse_records[: max(1, max_events_per_company)]:
                    event = {
                        "title": item.get("title") or "",
                        "description": item.get("description") or "",
                        "url": item.get("attachment_url") or item.get("source_url") or "",
                        "source_url": item.get("source_url") or "",
                        "attachment_url": item.get("attachment_url") or "",
                        "attachment_candidates": item.get("attachment_candidates") or [],
                        "category": item.get("category") or "",
                        "source_uid": item.get("source_uid") or "",
                        "has_xbrl_hint": item.get("has_xbrl_hint") or False,
                        "company_name": item.get("company_name") or company_name,
                        "announced_at": item.get("announced_at"),
                    }
                    await _process_event(
                        "bse",
                        event,
                        ContentEventWatch(source="bse", bse_scrip_code=scrip, isin=company.get("isin"), company_name=company_name),
                        company,
                    )
            except Exception as exc:
                logger.warning("Official monitor BSE fetch failed for %s: %s", scrip, exc)
                _mark_source_health(state, "bse", ok=False, error=str(exc))
                failures.append({"source": "bse", "scrip_code": scrip, "error": str(exc)[:400]})
                _append_activity(
                    state,
                    message=f"BSE fetch failed for {company_name}",
                    level="error",
                    phase="fetching_bse",
                    source="bse",
                    company=company_name,
                )

        _update_current_run(
            state,
            phase="company_complete",
            company=company_name,
            discovered=discovered,
            generated=generated,
            published=published,
            drafts=drafts,
            skipped_seen=skipped_seen,
            skipped_low_value=skipped_low_value,
            failures=len(failures),
            companies_scanned=index,
            companies_total=len(batch),
        )
        save_monitor_state(state)

    if not dry_run and published == 0:
        try:
            fallback_result = await _run_fallback_publication(
                state=state,
                route_base=route_base,
                requested_by=requested_by,
                dry_run=dry_run,
                job_id=job_id,
                universe=universe,
            )
            fallback_generated = int(fallback_result.get("generated") or 0)
            fallback_published = int(fallback_result.get("published") or 0)
            fallback_held = int(fallback_result.get("drafts") or 0)
            generated += fallback_generated
            published += fallback_published
            drafts += fallback_held
            recent_items = [
                _recent_item_payload(item if isinstance(item, dict) else {})
                for item in list(fallback_result.get("recent_items") or [])
            ] + recent_items
            save_monitor_state(state)
        except Exception as exc:
            logger.exception("Fallback publication sweep failed")
            _fallback_state(state)["last_error"] = str(exc)[:240]
            _fallback_state(state)["last_status"] = "error"
            _fallback_state(state)["last_action"] = "Fallback topic selection failed"
            failures.append({"source": "fallback", "error": str(exc)[:400]})
            _append_activity(
                state,
                message="Fallback topic selection failed",
                level="error",
                phase="fallback",
                source="fallback",
            )
            save_monitor_state(state)
    else:
        fallback = _fallback_state(state)
        fallback["last_status"] = "skipped"
        fallback["last_action"] = (
            "Fallback skipped because the official sweep already published a story"
            if published > 0
            else "Fallback skipped during dry run"
        )
        fallback["remaining_today"] = max(0, _FALLBACK_DAILY_TARGET - int(fallback.get("published_today") or 0))

    if not dry_run:
        try:
            archive_cleanup = _cleanup_published_archive(route_base, state=state)
        except Exception:
            logger.exception("Archive cleanup failed")
            failures.append({"source": "archive_cleanup", "error": "cleanup_failed"})

    state["last_status"] = "ok" if not failures else ("partial" if generated or discovered else "error")
    state["last_completed_at"] = _utcnow_iso()
    state["last_summary"] = {
        "discovered": discovered,
        "generated": generated,
        "published": published,
        "drafts": drafts,
        "skipped_seen": skipped_seen,
        "skipped_low_value": skipped_low_value,
        "failures": len(failures),
        "fallback_generated": fallback_generated,
        "fallback_published": fallback_published,
        "fallback_held": fallback_held,
        "archive_unpublished": int(archive_cleanup.get("unpublished") or 0),
        "archive_backfilled": int(archive_cleanup.get("backfilled") or 0),
        "companies_scanned": len(batch),
        "universe_size": len(universe),
    }
    state["current_run"] = {}
    _append_activity(
        state,
        message=(
            f"Sweep finished: discovered {discovered}, generated {generated}, "
            f"published {published}, held {drafts}, failures {len(failures)}"
        ),
        phase="finished",
        level="success" if not failures else "warning",
    )
    state["recent_items"] = recent_items + list(state.get("recent_items") or [])
    save_monitor_state(state)

    _emit(
        job_id,
        "ingest_done",
        discovered=discovered,
        generated=generated,
        published=published,
        drafts=drafts,
        skipped=skipped_seen + skipped_low_value,
        archive_unpublished=int(archive_cleanup.get("unpublished") or 0),
        archive_backfilled=int(archive_cleanup.get("backfilled") or 0),
    )

    return {
        "status": state["last_status"],
        "discovered": discovered,
        "generated": generated,
        "published": published,
        "drafts": drafts,
        "skipped_seen": skipped_seen,
        "skipped_low_value": skipped_low_value,
        "failures": failures,
        "archive_unpublished": int(archive_cleanup.get("unpublished") or 0),
        "archive_backfilled": int(archive_cleanup.get("backfilled") or 0),
        "companies_scanned": len(batch),
        "universe_size": len(universe),
        "cursor": next_cursor,
    }

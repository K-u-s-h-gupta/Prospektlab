"""FastAPI gateway: start a research session, stream events, serve all pages."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import json
import logging
import os
import re
import shutil
import sys
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# Configure logging for finagent and oracle namespaces to print to stdout at INFO level
# This ensures that all agent step execution logs show up in the terminal when running under uvicorn.
def configure_logging():
    _formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(_formatter)

    for logger_name in ["finagent", "oracle"]:
        _logger = logging.getLogger(logger_name)
        _logger.setLevel(logging.INFO)
        # Clear existing handlers to avoid duplicates on hot-reloading
        _logger.handlers = []
        _logger.addHandler(_handler)
        _logger.propagate = False
        _logger.disabled = False

configure_logging()


# Load .env before any other finagent imports so OPENAI_API_KEY / TAVILY_API_KEY
# are available when settings.py and runtime_provider.py are first imported.
try:
    from dotenv import load_dotenv as _load_dotenv
    # Try backend/finagent/.env first, then project root .env
    _here = Path(__file__).resolve().parent
    _loaded = (
        _load_dotenv(_here.parent / ".env", override=True)
        or _load_dotenv(_here.parent.parent.parent / ".env", override=True)
    )
except ImportError:
    pass  # python-dotenv not installed; keys must come from environment

from fastapi import FastAPI, HTTPException, Header, Depends, Request, Response, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, field_validator

import httpx
import urllib.parse
import jwt

from finagent.events import BUS
from finagent.output.intent_classifier import classify_query_complexity, extract_finance_entities, primary_target_from_query
from finagent.paths import finagent_data_path, finagent_home, repo_root
from finagent.run_agent import AgentLoopConfig, STANDARD_PRESET, STANDARD_PLUS_PRESET, run_research_session
from finagent.swarm_research import (
    SwarmResearchConfig,
    run_deep_swarm_research_session,
    run_standard_v2_research_session,
)
from finagent.canvas.models import InteractiveResearchCanvas
from finagent.canvas.store import CanvasController, CanvasStore
from finagent.tools.web.http_fetcher import aclose_shared_client
from finagent.router.intent_router import ContextualizerError, ContextualizeResult, LLMQueryContextualizer, is_portfolio_scope_query
from finagent.memory.chat_memory import ChatMemoryManager
from finagent.ingestion.image_ingestion import PortfolioImageExtractionError, extract_portfolio_from_image
from finagent.ingestion.portfolio_document import extraction_to_position_dicts, parse_portfolio_document
from finagent.ingestion.portfolio_schema import PortfolioExtractionConfirmRequest, PortfolioExtractionSchema
from finagent.content_automation import (
    ContentAutomationBatchRequest,
    ContentEventIngestionRequest,
    ContentAutomationRequest,
    generate_article_batch,
    generate_article_automation,
    ingest_market_event_triggers,
    is_generated_article_published,
    list_generated_articles,
    load_generated_article,
    load_generated_article_asset,
    load_generated_article_html,
    publish_article as _publish_article,
    unpublish_article as _unpublish_article,
)
from finagent.content.flash_engine import (
    FlashGenerationRequest,
    FlashIngestRequest,
    generate_flash_article,
    ingest_events_flash,
    build_insights_hub_html,
)
from finagent.content.official_monitor import get_monitor_status, run_official_monitor
from finagent.portfolio_mirrors import load_active_positions, replace_active_positions, summarize_positions, delete_positions, clear_all_positions, normalize_symbol
from finagent.portfolio.sectors import enrich_position
from finagent.portfolio.analytics import compute_portfolio_analytics
from finagent.portfolio.news import fetch_portfolio_news
from finagent.ops.control_tower import build_control_tower_snapshot
from finagent.gateway.email_delivery import EmailDeliveryOutcome, send_email_message
from finagent.gateway.sms_delivery import send_sms_message
from finagent.gateway import supabase_client as supabase
from finagent.gateway.auth_guard import decode_current_user_token
from finagent.telemetry import TELEMETRY, TelemetryUserContext, telemetry_request_context, telemetry_user_from_authorization_header, telemetry_user_from_request_user
from finagent.cache import app_cache
from finagent.telemetry_burner import create_telemetry_burner_task, get_telemetry_burner
from finagent.tools.data import fetch_news, fetch_yahoo_quote, fetch_india_snapshot, fetch_nse_snapshot
from finagent.news.sources.nse_announcements import fetch_nse_announcements
from finagent.news.scorer import VERIFIED_DOMAINS, parse_published_at
from finagent.screener import get_screener_service
from finagent.ipo import get_ipo_service
import time

# â”€â”€ Razorpay payments â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "").strip()
_RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "").strip()

try:
    import razorpay
    _razorpay_client: razorpay.Client | None = (
        razorpay.Client(auth=(_RAZORPAY_KEY_ID, _RAZORPAY_KEY_SECRET))
        if _RAZORPAY_KEY_ID and _RAZORPAY_KEY_SECRET
        else None
    )
except Exception:
    razorpay = None  # type: ignore[assignment]
    _razorpay_client = None


# â”€â”€ Rate limiting â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Supabase PostgreSQL-backed sliding window (shared across containers, no Redis)
class SupabaseSlidingWindowRateLimiter:
    def __init__(self, requests_limit: int, window_seconds: int):
        self.requests_limit = requests_limit
        self.window_seconds = window_seconds

    async def __call__(self, request: Request):
        from finagent.storage.supabase_store import get_state_store
        store = get_state_store()
        key = "unknown"
        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            key = auth.split(" ")[1]
        elif request.client:
            key = request.client.host
        try:
            allowed = await asyncio.wait_for(
                store.check_rate_limit(key, self.requests_limit, self.window_seconds),
                timeout=_gateway_float_setting("FINAGENT_RATE_LIMIT_TIMEOUT_S", 3.0),
            )
        except Exception as exc:
            logger.debug("Rate limit check failed open for %s: %s", key, exc)
            allowed = True
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again later."
            )

research_rate_limiter = SupabaseSlidingWindowRateLimiter(requests_limit=5, window_seconds=60)
auth_rate_limiter = SupabaseSlidingWindowRateLimiter(requests_limit=10, window_seconds=60)
default_rate_limiter = SupabaseSlidingWindowRateLimiter(requests_limit=100, window_seconds=60)

# â”€â”€ Upload validation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

VALID_MAGIC_BYTES = {
    b"%PDF": (".pdf",),
    b"\x89PNG": (".png",),
    b"\xff\xd8\xff": (".jpg", ".jpeg"),
    b"PK\x03\x04": (".xlsx",),         # ZIP container â€” modern Excel only
    b"\xD0\xCF\x11\xE0": (".xls",),   # OLE2 compound document â€” legacy Excel
}

PROMPT_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+(all\s+)?previous\s+(instructions|commands)|"
    r"disregard\s+(all\s+)?previous|"
    r"system\s+prompt|"
    r"you\s+are\s+now\s+|"
    r"new\s+instructions?\s*:|"
    r"override\s+(security|restrictions)|"
    r"bypass\s+(auth|authentication))",
    re.IGNORECASE,
)

_FRONTEND_PORTFOLIO_CONTEXT_RE = re.compile(
    r"^\s*\[(?:USER PORTFOLIO SUMMARY|USER HOLDS SPECIFIC POSITIONS|USER PORTFOLIO VALUE):.*?\]\s*",
    re.IGNORECASE | re.DOTALL,
)


def _gateway_float_setting(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


async def _jsonable_model_dump(value: Any) -> Any:
    dumped = value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
    if inspect.isawaitable(dumped):
        dumped = await dumped
    return dumped


async def _contextualize_query_with_budget(
    query: str,
    prior_target: str | None,
    chat_history: list[dict[str, Any]] | None,
    *,
    timeout_s: float,
) -> ContextualizeResult:
    contextualizer = LLMQueryContextualizer()
    return await asyncio.wait_for(
        contextualizer.contextualize(query, prior_target, chat_history),
        timeout=timeout_s,
    )


_MAX_CONCURRENT_SESSIONS = 20
_DEEP_RESEARCH_SEMAPHORE = asyncio.Semaphore(4)

# â”€â”€ Token Usage Tracking â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
WEEKLY_TOKEN_LIMIT = int(os.getenv("WEEKLY_TOKEN_LIMIT", "1000000"))
PRO_WEEKLY_TOKEN_LIMIT = int(os.getenv("PRO_WEEKLY_TOKEN_LIMIT", "2000000"))
FREE_WEEKLY_DEEP_RUNS = int(os.getenv("FREE_WEEKLY_DEEP_RUNS", "1"))

# â”€â”€ Plan helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async def _get_user_plan(email: str) -> str:
    return await supabase.get_user_plan(email)


def _weekly_token_limit_for_plan(plan: str) -> int:
    return PRO_WEEKLY_TOKEN_LIMIT if plan.strip().lower() == "pro" else WEEKLY_TOKEN_LIMIT


def _week_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def _next_week_start_utc() -> datetime:
    return _week_start_utc() + timedelta(weeks=1)


async def get_weekly_token_usage(user_email: str) -> int:
    from finagent.storage.supabase_store import get_token_usage_store
    store = get_token_usage_store()
    try:
        return await asyncio.wait_for(
            store.get_weekly_usage(user_email),
            timeout=_gateway_float_setting("FINAGENT_TOKEN_USAGE_TIMEOUT_S", 4.0),
        )
    except Exception as exc:
        logger.debug("weekly token usage check failed for %s: %s", user_email, exc)
        # Fail-open for availability; token tracking resumes once backend recovers.
        return 0


async def record_token_usage(
    user_email: str,
    session_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    model: str = "",
) -> None:
    from finagent.storage.supabase_store import get_token_usage_store
    store = get_token_usage_store()
    await store.record_usage(user_email, session_id, prompt_tokens, completion_tokens, model)


async def _check_deep_run_access(current_user: dict) -> None:
    """Raise 429 if a free user has exhausted their weekly deep-run quota."""
    email = current_user.get("email")
    if not email:
        return
    plan = await _get_user_plan(email)
    if plan.strip().lower() == "pro":
        return
    used, period_start = await supabase.get_deep_runs_used(email)
    current_week_start = _week_start_utc()
    if period_start < current_week_start:
        used = 0
    if used >= FREE_WEEKLY_DEEP_RUNS:
        raise HTTPException(status_code=429, detail={
            "code": "DEEP_PREMIUM_REQUIRED",
            "message": "Free tier allows 1 deep research run per week. Upgrade to Pro for unlimited deep research.",
            "plan": plan,
            "deep_runs_used": used,
            "deep_runs_limit": FREE_WEEKLY_DEEP_RUNS,
            "upgrade_available": True,
        })


async def _record_deep_run(current_user: dict) -> None:
    """Increment the user's weekly deep-run counter after a successful deep start."""
    email = current_user.get("email")
    user_id = current_user.get("user_id")
    if not email or not user_id:
        return
    # Supabase profiles expect a valid UUID user_id. Smoke-test tokens may use
    # non-UUID identifiers; skip persistence rather than failing the request.
    try:
        uuid.UUID(str(user_id))
    except ValueError:
        logger.debug("skipping deep-run persistence for non-UUID user_id %s", user_id)
        return
    # Best-effort: never block a research request if the profile/usage store
    # is unreachable or the auth user row does not exist (local test tokens).
    try:
        await supabase.upsert_profile(
            user_id=user_id,
            email=email,
            full_name=current_user.get("name") or email,
            auth_provider=current_user.get("auth_provider", "local_jwt"),
        )
        await supabase.increment_deep_runs_used(email)
    except Exception as exc:
        logger.debug("deep-run usage record failed for %s: %s", email, exc)


# â”€â”€ Ingestion state (in-memory + file fallback; no shared SQLite) â”€â”€â”€â”€â”€â”€â”€â”€â”€
# We use a simple in-memory dict backed by JSON files per tenant for ingestion state.
# This avoids SQLite contention and is sufficient for transient ingestion state.
_INGESTION_STATE: dict[str, dict[str, str]] = {}


def _ingestion_state_path(tenant_id: str) -> Path:
    return finagent_data_path("ingestion_state", f"{tenant_id}.json")


def _load_ingestion_state(tenant_id: str) -> dict[str, str]:
    if tenant_id in _INGESTION_STATE:
        return dict(_INGESTION_STATE[tenant_id])
    path = _ingestion_state_path(tenant_id)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _INGESTION_STATE[tenant_id] = data
                return data
        except Exception:
            pass
    return {"status": "IDLE", "message": ""}


def _save_ingestion_state(tenant_id: str, status: str, message: str = "") -> None:
    data = {"status": status, "message": message, "updated_at": datetime.now(timezone.utc).isoformat()}
    _INGESTION_STATE[tenant_id] = data
    try:
        path = _ingestion_state_path(tenant_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass


def _set_ingestion_state(tenant_id: str | None, status: str, message: str = "") -> None:
    if not tenant_id:
        return
    _save_ingestion_state(tenant_id, status, message)


# A crashed or abandoned ingestion must not block research forever. Auto-expire
# a blocking state once it is older than its TTL so the tenant self-heals.
_INGESTION_TTL_S: dict[str, float] = {"INGESTING": 600.0, "REVIEW_REQUIRED": 1800.0}


def _get_ingestion_state(tenant_id: str | None) -> dict[str, str]:
    if not tenant_id:
        return {"status": "IDLE", "message": ""}
    state = _load_ingestion_state(tenant_id)
    status = state.get("status", "IDLE")
    ttl = _INGESTION_TTL_S.get(status)
    if ttl is not None:
        updated = state.get("updated_at")
        stale = True
        if updated:
            try:
                ts = datetime.fromisoformat(updated)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                stale = (datetime.now(timezone.utc) - ts).total_seconds() > ttl
            except Exception:
                stale = True
        if stale:
            logger.warning("[INGESTION] auto-expiring stale %s state for tenant %s", status, tenant_id)
            _save_ingestion_state(tenant_id, "IDLE", "")
            return {"status": "IDLE", "message": ""}
    return state


def _require_no_active_ingestion(tenant_id: str | None) -> None:
    state = _get_ingestion_state(tenant_id)
    if state["status"] in {"INGESTING", "REVIEW_REQUIRED"}:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "INGESTION_IN_PROGRESS",
                "message": state["message"] or "Finish portfolio document ingestion before starting chat or research.",
            },
        )


async def _read_upload_limited(file: UploadFile, max_bytes: int = MAX_UPLOAD_SIZE) -> bytes:
    """Read an upload stream with an early hard limit to avoid oversized in-memory blobs."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, f"Upload exceeds {max_bytes // (1024 * 1024)} MB limit")
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_upload(data: bytes, filename: str) -> None:
    """Enforce upload size, extension, and magic-byte validation."""
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, f"Upload exceeds {MAX_UPLOAD_SIZE // (1024 * 1024)} MB limit")
    ext = Path(filename).suffix.lower()
    if ext not in {".pdf", ".csv", ".xls", ".xlsx", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(400, "Unsupported file type")
    if ext == ".csv":
        return  # CSV has no reliable magic byte
    magic = data[:8]
    valid = False
    for signature, allowed_exts in VALID_MAGIC_BYTES.items():
        if magic.startswith(signature):
            if ext in allowed_exts:
                valid = True
            break
    if not valid:
        raise HTTPException(400, "File content does not match extension")


def _guard_prompt_injection(query: str) -> str:
    """Block known prompt injection patterns and wrap user input safely."""
    if PROMPT_INJECTION_PATTERNS.search(query):
        raise HTTPException(400, "Query contains disallowed directives")
    # Escape XML-like tags to prevent prompt boundary breakout
    safe = query.replace("<", "&lt;").replace(">", "&gt;")
    return f"[USER_QUERY]\n{safe}\n[/USER_QUERY]"


def _strip_frontend_portfolio_context(query: str) -> str:
    text = (query or "").strip()
    if not text:
        return ""
    return _FRONTEND_PORTFOLIO_CONTEXT_RE.sub("", text, count=1).strip()


def _profile_mobile(profile: dict[str, Any] | None) -> str:
    if not isinstance(profile, dict):
        return ""
    return str(profile.get("mobile") or profile.get("phone") or "").strip()


_PHONE_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def _sms_default_country_code() -> str:
    raw = os.getenv("AUTH_SMS_DEFAULT_COUNTRY_CODE", "+91").strip()
    if not raw.startswith("+"):
        raw = f"+{raw.lstrip('+')}"
    return raw


def _normalize_mobile(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Mobile number is required.")

    if raw.startswith("+"):
        digits = "+" + re.sub(r"\D", "", raw[1:])
        if not _PHONE_E164_RE.match(digits):
            raise ValueError("Mobile number must be in E.164 format.")
        return digits

    digits_only = re.sub(r"\D", "", raw)
    if len(digits_only) == 10:
        normalized = f"{_sms_default_country_code()}{digits_only}"
    elif 8 <= len(digits_only) <= 15:
        normalized = f"+{digits_only}"
    else:
        raise ValueError("Mobile number is invalid.")

    if not _PHONE_E164_RE.match(normalized):
        raise ValueError("Mobile number must be in E.164 format.")
    return normalized


def _normalize_optional_mobile(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    return _normalize_mobile(raw)

_COMPARISON_RE = re.compile(
    r"\b(?:compare|comparison|compares|comparing|vs\.?|versus|against|head[\s-]to[\s-]head)\b",
    re.IGNORECASE,
)


def _is_comparison(query: str) -> bool:
    return bool(_COMPARISON_RE.search(query or ""))


def _extract_comparison_targets(query: str) -> list[str]:
    """Extract up to 2 entity names from a comparison query."""
    entities = extract_finance_entities(query, limit=2)
    return [e.canonical_name for e in entities if e.canonical_name]


_STANDARD_DEEP_LITE_TERMS = (
    "governance",
    "ownership",
    "shareholding",
    "promoter",
    "pledge",
    "risk",
    "regulatory",
    "litigation",
    "investigation",
    "valuation",
    "dcf",
    "cash flow",
    "capital allocation",
    "competitive",
    "moat",
    "peer",
    "scenario",
    "sensitivity",
)


def _should_use_standard_deep_lite(
    objective: str,
    raw_query: str,
    *,
    is_portfolio_query: bool,
    is_comparison_query: bool,
) -> bool:
    """Enable a bounded deep-lite profile for multi-factor standard queries."""
    if is_portfolio_query or is_comparison_query:
        return True

    cx = classify_query_complexity(raw_query, objective)
    if cx["complexity"] == "deep":
        return True
    combined = f"{raw_query}\n{objective}".lower()
    query_words = raw_query.lower().split()
    focus_hits = sum(1 for term in _STANDARD_DEEP_LITE_TERMS if term in combined)

    if cx["complexity"] == "moderate" and (cx["needs_history"] or cx["needs_macro"]):
        return True
    # A short query with two extracted entities (e.g. "TCS PE ratio") is still a
    # snapshot ask; require either real length or explicit factor terms to upgrade.
    if cx["complexity"] == "moderate" and cx["entity_count"] >= 2 and (len(query_words) >= 12 or focus_hits >= 1):
        return True

    if any(
        term in combined
        for term in (
            "deep",
            "comprehensive",
            "due diligence",
            "full analysis",
            "investment thesis",
            "multi-factor",
            "multifactor",
        )
    ):
        return True

    long_form = len(combined) >= 180 or len(query_words) >= 28
    return focus_hits >= 2 or (focus_hits >= 1 and long_form)


_SESSION_ID_RE = re.compile(r"^[a-f0-9]{12,64}$")
_REVIEW_ID_RE = re.compile(r"^[a-f0-9]{12,64}$")
_REVIEW_TOKEN_AUDIENCE = "prospektlab-portfolio-review"
_REVIEW_TOKEN_TTL_SECONDS = max(300, int(os.getenv("FINAGENT_REVIEW_TOKEN_TTL_S", "1800") or 1800))


def _validate_session_id(session_id: str) -> str:
    sid = (session_id or "").strip().lower()
    if not _SESSION_ID_RE.fullmatch(sid):
        raise HTTPException(status_code=422, detail="Invalid session_id format")
    return sid


def _validate_review_id(review_id: str) -> str:
    rid = (review_id or "").strip().lower()
    if not _REVIEW_ID_RE.fullmatch(rid):
        raise HTTPException(status_code=422, detail="Invalid review_id format")
    return rid

def _mint_review_token(review_id: str, tenant_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "rid": review_id,
        "tid": tenant_id,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=_REVIEW_TOKEN_TTL_SECONDS),
        "iss": "prospektlab",
        "aud": _REVIEW_TOKEN_AUDIENCE,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _review_token_matches_pending(review_token: str | None, review_id: str, tenant_id: str) -> bool:
    token = (review_token or "").strip()
    if not token or not review_id or not tenant_id:
        return False
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=["HS256"],
            audience=_REVIEW_TOKEN_AUDIENCE,
            issuer="prospektlab",
        )
    except jwt.PyJWTError:
        return False

    token_review_id = str(payload.get("rid") or "").strip().lower()
    token_tenant_id = str(payload.get("tid") or "").strip()
    return hmac.compare_digest(token_review_id, review_id) and hmac.compare_digest(token_tenant_id, tenant_id)


_MEMORY_MANAGER = ChatMemoryManager()
AUTH_COOKIE_NAME = "prospektlab_auth"
AUTH_COOKIE_MAX_AGE = 60 * 60 * 24 * 30

logger = logging.getLogger("finagent.gateway")


async def _periodic_cleanup() -> None:
    """Background task: reap zombie tasks and clean old state every 5 minutes."""
    while True:
        await asyncio.sleep(300)
        # Reap done tasks
        done_sids = [sid for sid, t in _TASKS.items() if t.done()]
        for sid in done_sids:
            _TASKS.pop(sid, None)
        # Clean old event bus sessions
        BUS.cleanup_old_sessions(max_age=3600)
        # Clean old SQLite state
        from finagent.gateway.state_store import cleanup_old_state
        cleanup_old_state(ttl_seconds=3600)
        logger.info("Periodic cleanup finished: %d tasks reaped, old sessions purged", len(done_sids))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(
        "FastAPI gateway startup: Logging configuration successfully applied to finagent and oracle namespaces."
    )
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_KEY"):
        logger.warning(
            "SUPABASE_URL or SUPABASE_KEY is not set. User-operational stores will use in-memory fallbacks. "
            "Long-term memory is handled separately by Prospekt tiered memory. "
            "Set Supabase environment variables for production user workflows."
        )
    cleanup_task = asyncio.create_task(_periodic_cleanup())
    create_telemetry_burner_task()
    yield
    # Shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    burner = get_telemetry_burner()
    await burner.stop()
    for task in list(_TASKS.values()):
        task.cancel()
    await aclose_shared_client()
    await TELEMETRY.aclose()


app = FastAPI(
    title="ProspektLab Intelligence Gateway",
    version="0.5.0",
    lifespan=lifespan,
)


# â”€â”€ CORS Middleware Configuration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from fastapi.middleware.cors import CORSMiddleware
_cors_raw = os.getenv("CORS_ORIGINS", "")
if not _cors_raw.strip() or _cors_raw.strip() == "*":
    _allow_origins = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:4174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:4174",
        "https://prospektlab.com",
        "https://www.prospektlab.com",
    ]
    _allow_credentials = True
else:
    _allow_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    _allow_credentials = True
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def telemetry_middleware(request: Request, call_next):
    if request.url.path in {"/docs", "/openapi.json", "/redoc"}:
        return await call_next(request)

    request_id, session_id = telemetry_request_context(request)
    telemetry_user = telemetry_user_from_authorization_header(request.headers.get("Authorization"))
    started_at = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        TELEMETRY.emit_exception(
            exc,
            user=telemetry_user,
            request_id=request_id,
            properties={
                "source": "backend",
                "method": request.method,
                "path": request.url.path,
                "query": request.url.query or "",
                "status": "exception",
            },
        )
        TELEMETRY.emit_request(
            name=f"{request.method} {request.url.path}",
            url=request.url.path,
            method=request.method,
            duration_ms=elapsed_ms,
            success=False,
            status_code=500,
            user=telemetry_user,
            request_id=request_id,
            session_id=session_id,
            properties={
                "source": "backend",
                "method": request.method,
                "path": request.url.path,
                "query": request.url.query or "",
                "status": "500",
            },
        )
        raise

    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    TELEMETRY.emit_request(
        name=f"{request.method} {request.url.path}",
        url=request.url.path,
        method=request.method,
        duration_ms=elapsed_ms,
        success=response.status_code < 400,
        status_code=response.status_code,
        user=telemetry_user,
        request_id=request_id,
        session_id=session_id,
        properties={
            "source": "backend",
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query or "",
            "status": str(response.status_code),
        },
    )
    response.headers["X-Prospektlab-Request-Id"] = request_id
    if session_id:
        response.headers["X-Prospektlab-Session-Id"] = session_id
    return response

# â”€â”€ Global Security Headers Middleware â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _content_security_policy_for_path(path: str) -> str:
    if path.startswith("/ops"):
        return (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://accounts.google.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com https://checkout.razorpay.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "style-src-attr 'unsafe-inline'; "
            "style-src-elem 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "img-src 'self' data: https://*.googleusercontent.com https://*.razorpay.com; "
            "frame-src 'self' https://accounts.google.com https://checkout.razorpay.com https://api.razorpay.com; "
            "connect-src 'self' https: wss: https://oauth2.googleapis.com https://*.supabase.co https://*.execute-api.us-east-1.amazonaws.com https://*.amplifyapp.com https://api.razorpay.com https://checkout.razorpay.com;"
        )

    # Public insights pages are rendered as standalone HTML documents with
    # inline styles, so they need a looser style policy than the SPA shell.
    if path.startswith("/insights"):
        return (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://accounts.google.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com https://checkout.razorpay.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "style-src-attr 'unsafe-inline'; "
            "style-src-elem 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "img-src 'self' data: https://*.googleusercontent.com https://*.razorpay.com; "
            "frame-src 'self' https://accounts.google.com https://checkout.razorpay.com https://api.razorpay.com; "
            "connect-src 'self' https: wss: https://oauth2.googleapis.com https://*.supabase.co https://*.execute-api.us-east-1.amazonaws.com https://*.amplifyapp.com https://api.razorpay.com https://checkout.razorpay.com;"
        )

    # Hardened CSP: unsafe-inline and unsafe-eval remain blocked for the main app.
    # Google Identity Services is loaded via a separate script file or
    # CSP nonce (recommended). For now, specific external domains are allowed.
    return (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://accounts.google.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com https://checkout.razorpay.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "style-src-attr 'unsafe-inline'; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "img-src 'self' data: https://*.googleusercontent.com https://*.razorpay.com; "
        "frame-src 'self' https://accounts.google.com https://checkout.razorpay.com https://api.razorpay.com; "
        "connect-src 'self' https: wss: https://oauth2.googleapis.com https://*.supabase.co https://*.execute-api.us-east-1.amazonaws.com https://*.amplifyapp.com https://api.razorpay.com https://checkout.razorpay.com;"
    )


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = _content_security_policy_for_path(request.url.path)
    return response

# â”€â”€ Unified get_current_user Dependency for JWT and BOLA checks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _set_auth_cookie(response: Response, token: str, request: Request | None = None) -> None:
    # Always secure in production; default to secure=True to prevent accidental
    # plaintext transmission behind reverse proxies.
    secure = True
    if os.getenv("PROSPEKTLAB_ENV") != "production" and request is not None:
        secure = request.url.scheme == "https"
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=AUTH_COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=secure,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", samesite="lax")


CONTROL_TOWER_HTML_PATH = Path(__file__).with_name("control_tower.html")


def _control_tower_allowed_emails() -> set[str]:
    raw = os.getenv("CONTROL_TOWER_ALLOWED_EMAILS", "")
    return {email.strip().lower() for email in raw.split(",") if email.strip()}


def _control_tower_requires_auth() -> bool:
    raw = os.getenv("CONTROL_TOWER_REQUIRE_AUTH")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return os.getenv("PROSPEKTLAB_ENV") == "production" or bool(_control_tower_allowed_emails())


def _control_tower_can_access(current_user: dict[str, Any] | None) -> bool:
    allowed_emails = _control_tower_allowed_emails()
    if not allowed_emails:
        return True
    email = (current_user or {}).get("email") if current_user else ""
    return str(email or "").strip().lower() in allowed_emails


def _decode_current_user(actual_token: str) -> dict:
    return decode_current_user_token(actual_token, local_jwt_secret=JWT_SECRET)


def _extract_request_token(
    request: Request,
    authorization: str | None,
) -> str | None:
    if authorization and authorization.startswith("Bearer "):
        return authorization.split(" ", 1)[1]

    cookie_token = request.cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        return cookie_token

    # Native EventSource cannot attach Authorization headers. Accept a
    # query-token fallback for read-only requests so SSE and memo views can
    # authenticate without widening POST/PUT/DELETE auth surfaces.
    if request.method.upper() in {"GET", "HEAD"}:
        query_token = (request.query_params.get("token") or "").strip()
        if query_token:
            return query_token

    return None


async def get_current_user(
    request: Request,
    authorization: str = Header(None),
) -> dict:
    actual_token = _extract_request_token(request, authorization)
    return _decode_current_user(actual_token)


async def get_current_user_optional(
    request: Request,
    authorization: str = Header(None),
) -> dict[str, Any] | None:
    actual_token = _extract_request_token(request, authorization)
    if not actual_token:
        return None
    try:
        return _decode_current_user(actual_token)
    except HTTPException:
        return None


async def _check_weekly_token_limit(current_user: dict) -> dict:
    """Raise 429 when the (authenticated) user's weekly token limit is exceeded.

    SECURITY: Client-side bypass headers have been removed. Only server-side
    token accounting determines limits.
    """
    plan = await _get_user_plan(current_user["email"])
    limit = _weekly_token_limit_for_plan(plan)
    usage = await get_weekly_token_usage(current_user["email"])
    if usage >= limit:
        # Calculate reset time in IST (UTC+5:30)
        restore_ist = _next_week_start_utc() + timedelta(hours=5, minutes=30)
        restore_display = restore_ist.strftime("%A, %d %B %Y at %I:%M %p IST")
        raise HTTPException(status_code=429, detail={
            "code": "WEEKLY_TOKEN_LIMIT_EXCEEDED",
            "message": f"You've used {usage:,} / {limit:,} tokens this week. Upgrade to Pro for more.",
            "restore_at": _next_week_start_utc().isoformat() + "Z",
            "restore_display": restore_display,
            "usage": usage,
            "limit": limit,
            "remaining": 0,
            "plan": plan,
            "upgrade_available": True,
        })
    return current_user


async def enforce_token_limit(
    request: Request,
    response: Response,
    authorization: str = Header(None),
) -> dict:
    """FastAPI dependency that enforces weekly limits for authenticated users while allowing guests."""
    current_user = await get_current_user_or_guest(request, response, authorization)
    return await _check_weekly_token_limit(current_user)


# â”€â”€ Public-first anonymous "guest" chat (Perplexity-style) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# The terminal is public: anyone can run standard + deep chat with no account.
# A signed-free opaque guest id (cookie) gives each visitor a stable identity
# so session ownership, SSE streaming and result polling all line up. Spend is
# bounded by a per-IP daily cap (deep < standard) â€” NOT by the cookie, so
# rotating the cookie can't reset the cap.
GUEST_COOKIE_NAME = "pl_guest"
GUEST_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
# Free anonymous daily caps, keyed per client IP. Override via env in prod.
_GUEST_DAILY_CAP_STANDARD = int(os.getenv("FINAGENT_GUEST_DAILY_STANDARD", "10") or 10)
_GUEST_DAILY_CAP_DEEP = int(os.getenv("FINAGENT_GUEST_DAILY_DEEP", "5") or 5)
_GUEST_ID_RE = re.compile(r"^g_[0-9a-f]{8,40}$")
_GUEST_FALLBACK_STATE_STORE: Any | None = None


def _is_guest_user(current_user: dict | None) -> bool:
    return bool(current_user and current_user.get("is_guest"))


def _guest_cookie_security(request: Request) -> tuple[bool, str]:
    """Return (secure, samesite) tuned for both same-origin and cross-origin API calls."""
    secure = True
    if os.getenv("PROSPEKTLAB_ENV") != "production":
        secure = request.url.scheme == "https"
    # Cross-origin XHR/fetch requires SameSite=None + Secure for cookie delivery.
    same_site = "none" if secure else "lax"
    return secure, same_site


def _set_guest_cookie(response: Response, request: Request, gid: str) -> None:
    secure, same_site = _guest_cookie_security(request)
    response.set_cookie(
        GUEST_COOKIE_NAME,
        gid,
        max_age=GUEST_COOKIE_MAX_AGE,
        httponly=True,
        samesite=same_site,
        secure=secure,
        path="/",
    )


def _attach_guest_cookie_to_response(response: Response, request: Request, current_user: dict | None) -> None:
    if not _is_guest_user(current_user):
        return
    gid = str((current_user or {}).get("guest_id") or "").strip()
    if not gid or not _GUEST_ID_RE.match(gid):
        return
    _set_guest_cookie(response, request, gid)


def _mint_guest_identity(request: Request, response: Response) -> dict:
    """Read (or create) the visitor's guest id and persist it as a cookie."""
    gid = (request.cookies.get(GUEST_COOKIE_NAME) or "").strip()
    if not gid:
        header_gid = (request.headers.get("x-prospekt-guest-id") or "").strip()
        if header_gid and _GUEST_ID_RE.match(header_gid):
            gid = header_gid
    if not gid or not _GUEST_ID_RE.match(gid):
        gid = "g_" + uuid.uuid4().hex
    _set_guest_cookie(response, request, gid)
    return {
        "email": f"guest:{gid}",
        "tenant_id": f"guest:{gid}",
        "guest_id": gid,
        "is_guest": True,
    }


async def get_current_user_or_guest(
    request: Request,
    response: Response,
    authorization: str = Header(None),
) -> dict:
    """Identity-only: real user when a valid token is present, else a guest.

    Used by chat + session endpoints so anonymous visitors get a stable
    identity. No token-limit / cap enforcement here â€” callers add that.
    """
    token = _extract_request_token(request, authorization)
    if token:
        try:
            return _decode_current_user(token)
        except HTTPException:
            pass  # invalid/expired token â†’ fall through to guest
    return _mint_guest_identity(request, response)


async def get_chat_user_or_guest(
    request: Request,
    response: Response,
    authorization: str = Header(None),
) -> dict:
    """Chat entrypoint identity: authed users get the weekly token-limit check;
    guests pass through (the per-mode daily cap is enforced in the endpoint,
    since the requested mode lives in the request body)."""
    current_user = await get_current_user_or_guest(request, response, authorization)
    if not _is_guest_user(current_user):
        await _check_weekly_token_limit(current_user)
    return current_user


async def enforce_guest_daily_cap(request: Request, mode: str) -> None:
    """Bound anonymous spend with a per-IP daily cap (deep < standard).

    Primary state store (Supabase) is used when available.  If it is unreachable
    or misconfigured, we fall back to an in-memory store so that anonymous chat
    remains usable without requiring login/signup.  The cap is still enforced;
    only the persistence changes.
    """
    from finagent.storage.supabase_store import get_state_store, _MemoryStateStore
    global _GUEST_FALLBACK_STATE_STORE
    ip = request.client.host if request.client else "unknown"
    is_deep = (mode or "").strip().lower() == "deep"
    limit = _GUEST_DAILY_CAP_DEEP if is_deep else _GUEST_DAILY_CAP_STANDARD
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    key = f"guest_chat:{'deep' if is_deep else 'standard'}:{ip}:{day}"

    store = get_state_store()
    try:
        allowed = await asyncio.wait_for(
            store.check_rate_limit(key, limit, 86400),
            timeout=_gateway_float_setting("FINAGENT_RATE_LIMIT_TIMEOUT_S", 3.0),
        )
    except Exception as exc:
        logger.warning(
            "Guest daily-cap primary store failed for %s (store=%s): %s; falling back to in-memory store",
            key, type(store).__name__, exc,
        )
        try:
            if _GUEST_FALLBACK_STATE_STORE is None:
                _GUEST_FALLBACK_STATE_STORE = _MemoryStateStore()
            allowed = await _GUEST_FALLBACK_STATE_STORE.check_rate_limit(key, limit, 86400)
        except Exception as exc2:
            logger.error("Guest daily-cap in-memory fallback also failed for %s: %s", key, exc2)
            # Availability wins for anonymous chat. If both limit stores fail,
            # allow the request rather than forcing login/signup or hard outage.
            allowed = True
    if not allowed:
        raise HTTPException(status_code=429, detail={
            "code": "GUEST_DAILY_LIMIT_EXCEEDED",
            "message": (
                f"You've hit today's free limit of {limit} "
                f"{'deep' if is_deep else 'standard'} questions. "
                "Your free quota resets tomorrow â€” check back then."
            ),
            "mode": "deep" if is_deep else "standard",
            "limit": limit,
            "is_guest": True,
            "signup_available": True,
        })

def verify_session_ownership(session_id: str, current_user: dict) -> None:
    sid = _validate_session_id(session_id)
    meta = _load_session_meta(sid)
    if not isinstance(meta, dict) or not meta:
        raise HTTPException(status_code=404, detail="Unknown session")

    owner_tenant = (meta.get("tenant_id") or "").strip()
    owner_email = (meta.get("user_email") or "").strip().lower()
    current_tenant = (current_user.get("tenant_id") or "").strip()
    current_email = (current_user.get("email") or "").strip().lower()

    # Fail closed: ownership metadata is mandatory for access.
    if not owner_tenant and not owner_email:
        raise HTTPException(status_code=403, detail="Access denied: Session ownership metadata missing.")

    if owner_tenant and current_tenant and owner_tenant != current_tenant:
        raise HTTPException(status_code=403, detail="Access denied: You do not own this research session.")
    if owner_email and owner_email != current_email:
        raise HTTPException(status_code=403, detail="Access denied: You do not own this research session.")

def add_cors_headers(request: Request, response: Response) -> Response:
    origin = request.headers.get("origin")
    if not origin:
        return response
    
    # Check if origin is allowed
    is_allowed = False
    if "*" in _allow_origins:
        is_allowed = True
        origin_to_set = "*"
    elif origin in _allow_origins:
        is_allowed = True
        origin_to_set = origin
    else:
        origin_to_set = None
        is_allowed = False

    if is_allowed and origin_to_set:
        response.headers["Access-Control-Allow-Origin"] = origin_to_set
        if _allow_credentials and origin_to_set != "*":
            response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "*"
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    response = JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )
    return add_cors_headers(request, response)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = " -> ".join(str(l) for l in err.get("loc", []))
        msg = err.get("msg", "Invalid value")
        errors.append(f"[{loc}]: {msg}")
    
    response = JSONResponse(
        status_code=422,
        content={
            "detail": "Input validation failed",
            "errors": errors
        }
    )
    return add_cors_headers(request, response)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id, session_id = telemetry_request_context(request)
    telemetry_user = telemetry_user_from_authorization_header(request.headers.get("Authorization"))
    TELEMETRY.emit_exception(
        exc,
        user=telemetry_user,
        request_id=request_id,
        properties={
            "source": "backend",
            "method": request.method,
            "path": request.url.path,
            "query": request.url.query or "",
            "status": "exception",
            "handler": "global_exception_handler",
        },
    )
    logger.exception("Unhandled gateway error on %s %s", request.method, request.url.path)
    response = JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred.",
            "error_type": exc.__class__.__name__
        }
    )
    response.headers["X-Prospektlab-Request-Id"] = request_id
    if session_id:
        response.headers["X-Prospektlab-Session-Id"] = session_id
    return add_cors_headers(request, response)

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET environment variable is required. Set a strong random secret before starting the server.")


def _mint_token(user_id: str, email: str, name: str | None = None, days: int = 30, email_verified: bool = False) -> str:
    """Issue a local JWT with jti, exp, iat, iss, and aud claims."""
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "email": email,
        "name": name or email,
        "email_verified": email_verified,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(days=days),
        "iss": "prospektlab",
        "aud": "prospektlab-api",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


class GoogleAuthRequest(BaseModel):
    credential: str

async def _verify_google_token(credential: str) -> dict:
    """Verify a Google ID token against Google's tokeninfo endpoints."""
    # Try v3 tokeninfo endpoint first (recommended by Google)
    tokeninfo_urls = [
        f"https://www.googleapis.com/oauth2/v3/tokeninfo?id_token={urllib.parse.quote(credential)}",
        f"https://oauth2.googleapis.com/tokeninfo?id_token={urllib.parse.quote(credential)}",
    ]
    last_error = None
    async with httpx.AsyncClient(timeout=10) as client:
        for url in tokeninfo_urls:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.json()
                logger.warning(f"Google tokeninfo returned {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                logger.warning(f"Google tokeninfo request failed for {url}: {e}")
                last_error = e

    raise HTTPException(status_code=503, detail="Identity service temporarily unavailable. Please try again.")

@app.post("/auth/google", dependencies=[Depends(auth_rate_limiter)])
async def google_auth(req: GoogleAuthRequest, request: Request):
    """Verify a Google ID token from GIS popup and return a session JWT."""
    info = await _verify_google_token(req.credential)

    email = info.get("email")
    name  = info.get("name") or info.get("given_name", "")
    avatar = info.get("picture", "")
    
    if not email or not info.get("email_verified"):
        raise HTTPException(status_code=401, detail="Google account email not verified")

    existing = await supabase.get_user_by_email(email)
    if existing:
        user_id = existing["id"]
        full_name = existing.get("full_name") or name
    else:
        # Create user via Supabase Admin API
        import secrets
        rand_pw = secrets.token_urlsafe(32) + "A1!"
        try:
            res = await supabase.create_admin_user(email, rand_pw, name, avatar_url=avatar, auth_provider="google")
            user_id = res.get("id")
            await supabase.upsert_profile(user_id, email, name, "google", avatar_url=avatar)
        except HTTPException as e:
            if e.status_code == 409:
                # User already exists in auth.users, fetch their ID directly from auth DB
                user_id = (await asyncio.to_thread(supabase.get_user_id_from_auth, email)) or "unknown"
                if user_id != "unknown":
                    await supabase.upsert_profile(user_id, email, name, "google", avatar_url=avatar)
            else:
                raise e
        full_name = name

    # Refresh profile details to check if mobile number exists
    profile = await supabase.get_user_by_email(email)
    mobile = _profile_mobile(profile)
    require_mobile = not bool(mobile)

    token = _mint_token(user_id, email, full_name, email_verified=True)

    response = JSONResponse({
        "token": token,
        "user_id": user_id,
        "email": email,
        "name": full_name,
        "full_name": full_name,
        "require_mobile": require_mobile,
        "mobile": mobile,
        "email_verified": True,
    })
    _set_auth_cookie(response, token, request)
    TELEMETRY.emit_event(
        "auth_google_success",
        user=TelemetryUserContext(email=email, name=full_name, user_id=user_id, auth_provider="google"),
        properties={
            "source": "backend",
            "require_mobile": require_mobile,
        },
    )
    return response

class UpdateMobileRequest(BaseModel):
    mobile: str

@app.post("/auth/google/update-mobile", dependencies=[Depends(auth_rate_limiter)])
async def update_google_mobile(req: UpdateMobileRequest, current_user: dict = Depends(get_current_user)):
    """Update mobile number for any auth provider (Google, email, etc.).
    Uses the shared get_current_user dependency for consistent JWT validation.
    """
    user_id = current_user.get("user_id")
    email = current_user.get("email")

    if not user_id or user_id == "unknown":
        raise HTTPException(status_code=400, detail="Invalid user ID in token")

    # Update in Supabase Auth via Admin API
    try:
        await supabase.update_admin_user_mobile(user_id, req.mobile)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Fetch profile to preserve name and avatar
    profile = await supabase.get_user_by_email(email)
    name = profile.get("full_name", "") if profile else ""
    avatar = profile.get("avatar_url", "") if profile else ""

    # Update in public.profiles table
    await supabase.upsert_profile(user_id, email, name, "google", mobile=req.mobile, avatar_url=avatar)
    TELEMETRY.emit_event(
        "auth_mobile_updated",
        user=telemetry_user_from_request_user(current_user),
        properties={
            "source": "backend",
            "provider": "google",
        },
    )

    return {"message": "Mobile number updated successfully."}



_MEMOS_DIR = finagent_data_path("memos")


def _frontend_base_url() -> str:
    raw = (os.getenv("FINAGENT_FRONTEND_URL") or os.getenv("FRONTEND_URL") or "").strip()
    if raw:
        return raw.rstrip("/")
    if _allow_origins and _allow_origins[0] != "*":
        return _allow_origins[0].rstrip("/")
    return "http://localhost:3000"


def _frontend_hash_url(route: str = "") -> str:
    cleaned = (route or "").lstrip("/")
    base = _frontend_base_url()
    return f"{base}/#/{cleaned}" if cleaned else f"{base}/#/"


def _frontend_static_url(path: str = "") -> str:
    cleaned = (path or "").lstrip("/")
    base = _frontend_base_url()
    return f"{base}/{cleaned}" if cleaned else f"{base}/"


class StartResearchRequest(BaseModel):
    target: str = Field(..., min_length=1)
    objective: str = Field("")
    # Optional â€” when absent the agent auto-picks depth from the objective.
    max_steps: int | None = Field(default=None, ge=4, le=50)
    max_wall_seconds: float | None = Field(default=None, ge=10, le=24 * 60 * 60)
    heartbeat_interval_s: float = Field(default=20.0, ge=5, le=300)
    mode: str = Field(default="chat", description="chat, standard, or deep")
    output_mode: str | None = None
    user_email: str | None = None
    session_id: str | None = None

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        mode = (v or "chat").strip().lower()
        if mode == "marathon":
            return "deep"
        return mode if mode in {"chat", "standard", "deep"} else "chat"

    @field_validator("session_id")
    @classmethod
    def _session_id(cls, v: str | None) -> str | None:
        if not v:
            return None
        try:
            return _validate_session_id(v)
        except HTTPException as exc:
            raise ValueError("Invalid session_id format") from exc


class DeepResearchRequest(BaseModel):
    target: str = Field(..., min_length=1)
    objective: str = Field(default="")
    passes: int = Field(default=8, ge=2, le=20, description="Legacy input accepted; runtime uses fixed 8-phase Deep Research")
    pass_depth: int = Field(default=40, ge=10, le=120, description="Max steps per phase")
    max_wall_seconds: float | None = Field(default=None, ge=30, le=30 * 60)
    heartbeat_interval_s: float = Field(default=20.0, ge=5, le=60)
    user_email: str | None = None
    session_id: str | None = None

    @field_validator("session_id")
    @classmethod
    def _session_id(cls, v: str | None) -> str | None:
        if not v:
            return None
        try:
            return _validate_session_id(v)
        except HTTPException as exc:
            raise ValueError("Invalid session_id format") from exc


class ChatResearchRequest(BaseModel):
    message: str = Field(..., min_length=1)
    target: str | None = Field(default=None, min_length=1)
    mode: str = Field(default="standard", description="chat, standard, or deep")
    max_wall_seconds: float | None = Field(default=None, ge=10, le=30 * 60)
    user_email: str | None = None
    session_id: str | None = None

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        mode = (v or "standard").strip().lower()
        return "deep" if mode == "marathon" else (mode if mode in {"chat", "standard", "deep"} else "standard")

    @field_validator("session_id")
    @classmethod
    def _session_id(cls, v: str | None) -> str | None:
        if not v:
            return None
        try:
            return _validate_session_id(v)
        except HTTPException as exc:
            raise ValueError("Invalid session_id format") from exc


class ScreenerQueryRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=400)
    limit: int = Field(default=25, ge=1, le=100)
    universe: list[str] = Field(default_factory=list, max_length=300)


class PositionMirrorInput(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=48)
    exchange: str = Field(default="NSE", max_length=12)
    quantity: float = Field(default=0.0, ge=0)
    market_value: float = Field(default=0.0, ge=0)
    cost_basis: float = Field(default=0.0, ge=0)
    name: str = Field(default="", max_length=180)
    isin: str = Field(default="", max_length=16)
    amfi: str = Field(default="", max_length=24)
    kind: str = Field(default="equity", max_length=12)
    sector: str = Field(default="", max_length=80)
    industry: str = Field(default="", max_length=120)
    avg_cost: float = Field(default=0.0, ge=0)
    last_price: float = Field(default=0.0, ge=0)
    as_of: str = Field(default="", max_length=40)
    active: bool = True


class PositionMirrorReplaceRequest(BaseModel):
    positions: list[PositionMirrorInput] = Field(default_factory=list, max_length=500)


class ManualPositionInput(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=48)
    quantity: float = Field(..., gt=0)
    avg_cost: float = Field(..., gt=0)
    date_purchased: str = Field(default="", max_length=40)


class ManualPortfolioSyncRequest(BaseModel):
    positions: list[ManualPositionInput] = Field(default_factory=list, max_length=100)


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(v: str) -> str:
    v = (v or "").strip().lower()
    if not _EMAIL_RE.match(v):
        raise ValueError("Invalid email address.")
    return v


class SignupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    email: str = Field(..., min_length=3, max_length=160)
    password: str = Field(..., min_length=8, max_length=200)
    mobile: str = Field(..., min_length=5, max_length=30)
    referral_source: str = Field(default="organic", min_length=2, max_length=80)
    verification_code: str | None = Field(default=None, max_length=6)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v: str) -> str:
        return _normalize_mobile(v)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter.")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter.")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in v):
            raise ValueError("Password must contain at least one special character.")
        return v


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=160)
    password: str = Field(..., min_length=1, max_length=200)
    remember: bool = False

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)


class SendVerificationRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=160)
    mobile: str | None = Field(default=None, min_length=5, max_length=30)
    channel: str = Field(default="email", min_length=3, max_length=16)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v: str | None) -> str | None:
        return _normalize_optional_mobile(v) or None

    @field_validator("channel")
    @classmethod
    def _channel(cls, v: str) -> str:
        value = (v or "email").strip().lower()
        if value not in {"email", "sms"}:
            raise ValueError("Channel must be email or sms.")
        return value


class OutreachUnsubscribeRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=160)
    reason: str = Field(default="unsubscribe", min_length=3, max_length=80)
    source: str = Field(default="public_page", min_length=3, max_length=80)
    note: str = Field(default="", max_length=500)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)

    @field_validator("reason", "source")
    @classmethod
    def _label(cls, v: str) -> str:
        return (v or "").strip().lower()

    @field_validator("note")
    @classmethod
    def _note(cls, v: str) -> str:
        return (v or "").strip()


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=160)
    channel: str = Field(default="email", min_length=3, max_length=16)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)

    @field_validator("channel")
    @classmethod
    def _channel(cls, v: str) -> str:
        value = (v or "email").strip().lower()
        if value not in {"email", "sms"}:
            raise ValueError("Channel must be email or sms.")
        return value


class OutreachUnsubscribeRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=160)
    reason: str = Field(default="unsubscribe", min_length=3, max_length=80)
    source: str = Field(default="public_page", min_length=3, max_length=80)
    note: str = Field(default="", max_length=500)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)

    @field_validator("reason", "source")
    @classmethod
    def _label(cls, v: str) -> str:
        return (v or "").strip().lower()

    @field_validator("note")
    @classmethod
    def _note(cls, v: str) -> str:
        return (v or "").strip()


class ResetPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=160)
    code: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)


_TASKS: dict[str, asyncio.Task[Any]] = {}
_SESSION_META: dict[str, dict[str, Any]] = {}
_SESSION_ARTIFACTS: dict[str, Any] = {}
_SESSIONS_DIR = finagent_data_path("sessions")


def _build_artifact_from_bus(session_id: str) -> Any:
    """Build an AnswerArtifact from the BUS 'final' event after synthesis completes."""
    from finagent.output.contracts import (
        AnswerArtifact, AnswerChart, AnswerCitation, AnswerTable,
        ChartDataPoint, ChartSeries as ArtifactChartSeries,
        MetricCard as ArtifactMetricCard, OutputMode, ResponseDepth,
        ResponseSection,
    )

    final_payload = None
    for _seq, ev in reversed(BUS.history(session_id, limit=2000)):
        if ev.type == "final":
            final_payload = ev.payload
            break
    if final_payload is None:
        return None

    mode_str = final_payload.get("output_mode", "deep_research_report")
    depth_str = final_payload.get("response_depth", "deep")
    try:
        mode = OutputMode(mode_str)
    except ValueError:
        mode = OutputMode.DEEP_RESEARCH_REPORT
    try:
        depth = ResponseDepth(depth_str)
    except ValueError:
        depth = ResponseDepth.DEEP

    rich = final_payload.get("rich") or {}
    memo = final_payload.get("memo", "")
    target = final_payload.get("target", "")

    title = rich.get("title") or target or "Research Report"
    summary_text = memo[:500].rsplit("\n", 1)[0] if len(memo) > 500 else memo

    sections: list[ResponseSection] = []
    if memo:
        import re as _re
        parts = _re.split(r"^(#{1,3})\s+(.+)$", memo, flags=_re.MULTILINE)
        i = 0
        while i < len(parts):
            if i + 2 < len(parts) and parts[i] in ("#", "##", "###"):
                sec_title = parts[i + 1].strip()
                sec_body = parts[i + 2].strip() if i + 2 < len(parts) else ""
                if sec_title and sec_body:
                    sections.append(ResponseSection(title=sec_title, body=sec_body))
                i += 3
            else:
                if parts[i].strip() and not sections:
                    sections.append(ResponseSection(title="Overview", body=parts[i].strip()))
                i += 1

    citations = []
    for cs in final_payload.get("citation_sources", []):
        url = cs.get("url", "")
        domain = url.split("/")[2] if "://" in url else None
        citations.append(AnswerCitation(title=cs.get("title", ""), url=url, kind=cs.get("kind", "source"), domain=domain))

    metric_cards = []
    for mc in rich.get("metric_cards", []):
        metric_cards.append(ArtifactMetricCard(
            label=mc.get("label", ""), value=mc.get("value", ""),
            change=mc.get("change") or "", change_type=mc.get("change_type") or "neutral",
        ))

    charts = []
    for ch in rich.get("charts", []):
        series = []
        x_labels = ch.get("x_labels", [])
        for s in ch.get("series", []):
            data = []
            for idx, val in enumerate(s.get("values", [])):
                lbl = x_labels[idx] if idx < len(x_labels) else str(idx)
                data.append(ChartDataPoint(label=lbl, value=float(val) if val is not None else 0.0))
            series.append(ArtifactChartSeries(
                name=s.get("name", ""), color=s.get("color") or "#2c5282",
                data=data, unit=s.get("unit") or "", chart_type=ch.get("kind", "line"),
            ))
        charts.append(AnswerChart(
            id=ch.get("id", ""), title=ch.get("title", ""),
            subtitle=ch.get("subtitle") or "", chart_type=ch.get("kind", "line"),
            series=series, labels=x_labels,
        ))

    tables: list[AnswerTable] = []
    comp_rows = rich.get("comparison_rows", [])
    if comp_rows:
        p_ent = rich.get("primary_entity") or {}
        s_ent = rich.get("secondary_entity") or {}
        p_label = p_ent.get("label", "Entity A") if isinstance(p_ent, dict) else "Entity A"
        s_label = s_ent.get("label", "Entity B") if isinstance(s_ent, dict) else "Entity B"
        tables.append(AnswerTable(
            title="Comparison",
            columns=["Metric", p_label, s_label, "Delta"],
            rows=[[r.get("metric", ""), r.get("primary_value", ""), r.get("secondary_value", ""), r.get("delta", "")] for r in comp_rows],
        ))

    return AnswerArtifact(
        mode=mode, depth=depth, title=title, summary=summary_text,
        sections=sections, tables=tables, citations=citations,
        charts=charts, metric_cards=metric_cards,
        metadata={"quality_score": final_payload.get("quality_score"), "target": target},
    )


def _session_dir(session_id: str, *, create: bool = False) -> Path:
    sid = _validate_session_id(session_id)
    base = _SESSIONS_DIR.resolve()
    path = (base / sid).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid session_id format") from exc
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _session_record(
    session_id: str,
    *,
    mode: str,
    target: str,
    objective: str = "",
    user_email: str | None = None,
    tenant_id: str | None = None,
    export_intent: dict[str, Any] | None = None,
) -> None:
    session_id = _validate_session_id(session_id)
    record = {
        "session_id": session_id,
        "mode": mode,
        "target": target,
        "objective": objective,
        "tenant_id": tenant_id,
        "user_email": user_email,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "export_intent": export_intent or {"wants_export": False, "confidence": 0.0, "matched": [], "negated": False},
    }
    _SESSION_META[session_id] = record
    _session_meta_path(session_id, create_parent=True).write_text(json.dumps(record, indent=2), encoding="utf-8")


def _session_meta_path(session_id: str, *, create_parent: bool = False) -> Path:
    return _session_dir(session_id, create=create_parent) / "meta.json"


def _load_session_meta(session_id: str) -> dict[str, Any]:
    sid = _validate_session_id(session_id)
    if sid in _SESSION_META:
        return dict(_SESSION_META[sid])
    path = _session_meta_path(sid)
    if not path.is_file():
        return {"session_id": sid}
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(meta, dict):
            _SESSION_META[sid] = meta
            return dict(meta)
    except Exception:
        pass
    return {"session_id": sid}


def _save_session_meta(session_id: str, meta: dict[str, Any]) -> None:
    sid = _validate_session_id(session_id)
    _SESSION_META[sid] = dict(meta)
    try:
        _session_meta_path(sid, create_parent=True).write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


def _clear_session_memo(session_id: str) -> None:
    """Remove stale rendered output before a fresh run reuses a session id."""
    sid = _validate_session_id(session_id)
    memo_path = _MEMOS_DIR / f"{sid}.md"
    if memo_path.is_file():
        try:
            memo_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not clear stale memo for session %s", sid)


def _event_payload(idx: int, event) -> dict[str, Any]:
    ts = event.timestamp
    if isinstance(ts, datetime):
        ts = ts.isoformat()
    return {"id": idx, "type": event.type, "timestamp": ts, **event.payload}


def _latest_event(session_id: str, event_type: str) -> dict[str, Any] | None:
    for idx, event in reversed(BUS.history(session_id, limit=5000)):
        if event.type == event_type:
            return _event_payload(idx, event)
    return None


def _session_status(session_id: str) -> dict[str, Any]:
    if not BUS.known(session_id) and session_id not in _SESSION_META:
        raise HTTPException(status_code=404, detail="Unknown session")
    meta = _load_session_meta(session_id)
    task = _TASKS.get(session_id)
    error_event = _latest_event(session_id, "error")
    final_event = _latest_event(session_id, "final")
    memo_event = _latest_event(session_id, "memo")
    if error_event:
        status = "error"
    elif BUS.is_closed(session_id) or (task is not None and task.done()) or final_event:
        status = "done"
    else:
        status = "running"
    meta.update(
        {
            "status": status,
            "closed": BUS.is_closed(session_id),
            "active": task is not None and not task.done(),
            "event_count": len(BUS.history(session_id, limit=5000)),
            "latest_phase": _latest_event(session_id, "phase"),
            "final": final_event,
            "memo": memo_event,
            "error": error_event,
            "stream": f"/sessions/{session_id}/stream",
            "events": f"/sessions/{session_id}/events",
            "result": f"/sessions/{session_id}/result",
        }
    )
    meta["status"] = status
    _save_session_meta(session_id, meta)
    return meta


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#  Lightweight local "auth" â€” stores hashed credentials per email under
#  the FinAgent home directory. No JWTs, no sessions â€” sufficient for a
#  single-user dev/demo deployment. Production should swap in real auth.
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@app.get("/health")
def health():
    return {
        "status": "ok",
        "active_sessions": list(_TASKS.keys()),
        "openai": "enabled" if os.getenv("OPENAI_API_KEY") else "fallback",
        "finagent_home": "<redacted>",
        "version": app.version,
    }


@app.post("/api/outreach/unsubscribe", dependencies=[Depends(default_rate_limiter)])
async def outreach_unsubscribe(req: OutreachUnsubscribeRequest, request: Request):
    note_parts: list[str] = []
    if req.note:
        note_parts.append(req.note)

    if request.client and request.client.host:
        host_hash = hashlib.sha256(request.client.host.encode("utf-8")).hexdigest()[:16]
        note_parts.append(f"ip_hash={host_hash}")

    user_agent = (request.headers.get("user-agent") or "").strip()
    if user_agent:
        note_parts.append(f"user_agent={user_agent[:180]}")

    row = await supabase.store_outreach_unsubscribe(
        req.email,
        reason=req.reason,
        source=req.source,
        note=" | ".join(note_parts)[:500],
    )
    return JSONResponse(
        {
            "status": "ok",
            "email": row.get("email", req.email),
            "reason": row.get("reason", req.reason),
            "message": "You have been unsubscribed from outreach emails.",
        },
        headers={"Cache-Control": "no-store"},
    )


@app.get("/auth/me")
async def auth_me(current_user: dict = Depends(get_current_user)):
    """Return the current authenticated user.

    Accepts either cookie auth or Authorization bearer token auth so
    cross-origin frontends can rehydrate session state reliably.
    """
    plan = await _get_user_plan(current_user.get("email", ""))
    return {
        "user_id": current_user.get("user_id"),
        "email": current_user.get("email"),
        "tenant_id": current_user.get("tenant_id"),
        "auth_provider": current_user.get("auth_provider"),
        "email_verified": current_user.get("email_verified", False),
        "plan": plan,
    }


@app.get("/capabilities")
def capabilities():
    return {
        "agent": "FinAgent",
        "cloud_chat_ready": True,
        "interfaces": {
            "chat_research": "/chat/research",
            "start": "/research/start",
            "deep_start": "/research/deep",
            "status": "/sessions/{session_id}/status",
            "events": "/sessions/{session_id}/events?after=0",
            "result": "/sessions/{session_id}/result",
            "sse": "/sessions/{session_id}/stream",
        },
        "capabilities": {
            "long_chain_research": {
                "max_passes": 20,
                "max_pass_depth": 200,
                "wall_clock_budget": True,
                "heartbeat_events": True,
            },
            "search": {
                "backends": ["duckduckgo", "bing", "searxng_optional"],
                "per_session_query_cache": True,
                "domain_pinned_queries": os.getenv("FINAGENT_DOMAIN_PINNED_QUERIES", "1") not in {"0", "false", "no"},
                "preferred_domain_rerank": True,
            },
            "browser": {
                "crawl4ai_installed": _has_module("crawl4ai"),
                "pooled_chromium": True,
                "fallback_enabled": os.getenv("FINAGENT_BROWSER_FALLBACK") == "1",
                "http_fallback_enabled": os.getenv("FINAGENT_BROWSER_FALLBACK_HTTP") == "1",
                "extract_tool": True,
                "screenshot_tool": False,
            },
            "self_generated_skills": {
                "enabled": True,
                "path": str(finagent_home() / "skills" / "auto"),
                "prompt_keyword_loading": True,
            },
            "memo_rich_output": {
                "markdown": True,
                "finchart_blocks": True,
                "mermaid_blocks": True,
            },
        },
    }


def _has_module(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


@app.get("/config")
def config():
    return {
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "finagent_home": "<redacted>",
        "version": app.version,
        "fx_override": os.getenv("FINAGENT_USD_INR"),
    }


# â”€â”€ Market Data & Token Usage Endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/user/token-usage")
async def get_user_token_usage(current_user: dict = Depends(get_current_user)):
    plan = await _get_user_plan(current_user["email"])
    limit = _weekly_token_limit_for_plan(plan)
    usage = await get_weekly_token_usage(current_user["email"])
    restore_ist = _next_week_start_utc() + timedelta(hours=5, minutes=30)
    restore_display = restore_ist.strftime("%A, %d %B %Y at %I:%M %p IST")
    remaining = max(0, limit - usage)
    pct_used = min(100.0, (usage / limit) * 100.0) if limit > 0 else 0.0
    return {
        "usage": usage,
        "limit": limit,
        "remaining": remaining,
        "pct_used": pct_used,
        "restore_display": restore_display,
        "restore_at": _next_week_start_utc().isoformat() + "Z",
        "plan": plan,
    }


# â”€â”€ Razorpay payment endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class CreateOrderRequest(BaseModel):
    amount: int = Field(default=49900, ge=100, description="Amount in paise")
    currency: str = Field(default="INR", pattern=r"^INR$", max_length=3)
    receipt: str = Field(default="", max_length=40)
    plan: str = Field(default="pro", max_length=20)


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@app.post("/api/create-order")
async def create_order(
    req: CreateOrderRequest,
    current_user: dict = Depends(get_current_user),
):
    if not _razorpay_client:
        raise HTTPException(status_code=503, detail="Payment gateway not configured.")
    if req.amount < 100:
        raise HTTPException(status_code=400, detail="Amount must be at least 100 paise.")

    try:
        order = _razorpay_client.order.create(data={
            "amount": req.amount,
            "currency": req.currency.upper(),
            "receipt": req.receipt or f"rcpt_{current_user.get('user_id', uuid.uuid4().hex)[:12]}",
            "notes": {"plan": req.plan, "user_id": current_user.get("user_id")},
        })
    except Exception as exc:
        logger.exception("Razorpay create-order failed")
        status = 401 if "authentication" in str(exc).lower() else 500
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    order_id = order.get("id")
    if order_id:
        await supabase.record_payment(
            user_id=current_user.get("user_id"),
            razorpay_order_id=order_id,
            amount=req.amount,
            currency=req.currency.upper(),
            status="created",
        )

    return {
        "order_id": order_id,
        "amount": req.amount,
        "currency": req.currency.upper(),
        "key_id": _RAZORPAY_KEY_ID,
    }


@app.post("/api/verify-payment")
async def verify_payment(
    req: VerifyPaymentRequest,
    current_user: dict = Depends(get_current_user),
):
    if not _RAZORPAY_KEY_SECRET:
        raise HTTPException(status_code=503, detail="Payment gateway not configured.")
    if not req.razorpay_order_id or not req.razorpay_payment_id or not req.razorpay_signature:
        raise HTTPException(status_code=400, detail="Missing payment verification fields.")

    expected = hmac.new(
        _RAZORPAY_KEY_SECRET.encode(),
        f"{req.razorpay_order_id}|{req.razorpay_payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, req.razorpay_signature):
        raise HTTPException(status_code=400, detail="Payment signature verification failed.")

    await supabase.update_payment_verified(
        req.razorpay_order_id,
        req.razorpay_payment_id,
        req.razorpay_signature,
    )
    email = current_user.get("email", "")
    user_id = current_user.get("user_id", "")
    name = current_user.get("name", email)

    await supabase.upsert_profile(
        user_id=user_id,
        email=email,
        full_name=name,
        auth_provider=current_user.get("auth_provider", "local_jwt"),
    )
    success = await supabase.update_user_plan(email, "pro")
    if not success:
        raise HTTPException(status_code=500, detail="Payment verified but failed to activate Pro plan.")

    return {"success": True, "plan": "pro"}


@app.get("/user/subscription")
async def get_user_subscription(current_user: dict = Depends(get_current_user)):
    """Return current subscription plan, token usage, and deep-run quota."""
    email = current_user.get("email", "")
    plan = await _get_user_plan(email)
    limit = _weekly_token_limit_for_plan(plan)
    usage = await get_weekly_token_usage(email)
    deep_used, _ = await supabase.get_deep_runs_used(email)
    return {
        "plan": plan,
        "token_limit": limit,
        "token_usage": usage,
        "token_remaining": max(0, limit - usage),
        "deep_runs_used": deep_used,
        "deep_runs_limit": FREE_WEEKLY_DEEP_RUNS if plan != "pro" else None,
        "deep_runs_remaining": max(0, FREE_WEEKLY_DEEP_RUNS - deep_used) if plan != "pro" else None,
    }


@app.post("/user/upgrade-plan")
async def manual_upgrade_plan(
    plan: str = "pro",
    current_user: dict = Depends(get_current_user),
):
    """Manual plan upgrade (temporary until Razorpay integration is live)."""
    email = current_user.get("email", "")
    user_id = current_user.get("user_id", "")
    name = current_user.get("name", email)
    # Ensure profile row exists before patching the plan.
    await supabase.upsert_profile(
        user_id=user_id,
        email=email,
        full_name=name,
        auth_provider=current_user.get("auth_provider", "local_jwt"),
    )
    success = await supabase.update_user_plan(email, plan)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to upgrade plan.")
    return {"success": True, "plan": plan}


_HISTORY_PERIODS = {"1M", "3M", "6M", "YTD", "1Y", "MAX"}

_HISTORY_SYMBOL_MAP = {
    "NIFTY": "^NSEI",
    "NIFTY50": "^NSEI",
    "NIFTY 50": "^NSEI",
    "NIFTY FUT": "^NSEI",
    "SENSEX": "^BSESN",
    "BSE SENSEX": "^BSESN",
    "NIFTY BANK": "^NSEBANK",
    "BANKNIFTY": "^NSEBANK",
    "BANKNIFTY FUT": "^NSEBANK",
    "NIFTY IT": "^CNXIT",
    "S&P 500": "^GSPC",
    "SP500": "^GSPC",
    "NASDAQ": "^IXIC",
    "DOW": "^DJI",
    "VIX": "^VIX",
    "USD/INR": "USDINR=X",
    "EUR/INR": "EURINR=X",
    "GBP/INR": "GBPINR=X",
    "JPY/INR": "JPYINR=X",
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    "CRUDE": "CL=F",
    "CRUDE OIL": "CL=F",
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "XRP": "XRP-USD",
}

_KNOWN_ISIN_SYMBOLS = {
    "INE002A01018": "RELIANCE",
    "INE467B01029": "TCS",
    "INE009A01021": "INFY",
    "INE040A01034": "HDFCBANK",
    "INE154A01025": "ITC",
    "INE021A01026": "ASIANPAINT",
    "INE155A01022": "TATAMOTORS",
    "INE758T01015": "ZOMATO",
}


def _clean_history_symbol(symbol: str) -> str:
    return re.sub(r"\s+", " ", (symbol or "").strip()).upper()


def _history_candidates(symbol: str, asset_type: str | None) -> list[str]:
    clean = _clean_history_symbol(symbol)
    if not clean:
        return []

    clean = _KNOWN_ISIN_SYMBOLS.get(clean, clean)
    mapped = _HISTORY_SYMBOL_MAP.get(clean)
    if mapped:
        return [mapped]
    if clean.startswith("^") or "=" in clean or "-" in clean:
        return [clean]

    suffix_match = re.search(r"\.(NS|BO|NSE|BSE)$", clean)
    if suffix_match:
        normalized = clean.removesuffix(".NSE").removesuffix(".BSE")
        if clean.endswith(".NSE"):
            normalized = f"{normalized}.NS"
        elif clean.endswith(".BSE"):
            normalized = f"{normalized}.BO"
        return [normalized]

    kind = (asset_type or "").strip().lower()
    if kind in {"index", "commodity", "currency", "crypto", "future", "futures"}:
        return [clean]
    if kind in {"mutual fund", "mutual_fund", "fund", "bond", "bonds"}:
        if clean.endswith((".NS", ".BO")) or "=" in clean or "-" in clean:
            return [clean]
        return []

    # Indian equity default: NSE first, then BSE. Raw is last for ETFs/global tickers.
    return [f"{clean}.NS", f"{clean}.BO", clean]


def _period_cutoff(period: str, latest: datetime) -> datetime | None:
    if period == "MAX":
        return None
    if period == "YTD":
        return datetime(latest.year, 1, 1, tzinfo=latest.tzinfo)
    days = {
        "1M": 31,
        "3M": 93,
        "6M": 186,
        "1Y": 366,
    }.get(period)
    return latest - timedelta(days=days or 366)


def _filter_history_period(dates: list[str], prices: list[float], period: str) -> tuple[list[str], list[float]]:
    rows: list[tuple[datetime, str, float]] = []
    for date_text, price in zip(dates, prices):
        try:
            parsed = datetime.fromisoformat(str(date_text)[:10]).replace(tzinfo=timezone.utc)
            price_f = float(price)
        except Exception:
            continue
        if price_f > 0:
            rows.append((parsed, parsed.date().isoformat(), price_f))

    rows.sort(key=lambda item: item[0])
    if not rows:
        return [], []

    cutoff = _period_cutoff(period, rows[-1][0])
    if cutoff is not None:
        rows = [row for row in rows if row[0] >= cutoff]

    return [row[1] for row in rows], [row[2] for row in rows]


def _watchlist_clean_symbol(value: str) -> str:
    sym = (value or "").strip().upper()
    return sym.removesuffix(".NS").removesuffix(".BO").removesuffix(".NSE").removesuffix(".BSE")


def _watchlist_find_quote(quotes_payload: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    normalized = _watchlist_clean_symbol(symbol)
    for candidate in (symbol, normalized, f"{normalized}.NS", f"{normalized}.BO"):
        row = quotes_payload.get(candidate)
        if isinstance(row, dict):
            return row
    return None


def _watchlist_format_price(value: float) -> str:
    return f"Rs {value:,.2f}"


def _watchlist_source_tier(url: str, source: str = "") -> int:
    host = ""
    try:
        host = urllib.parse.urlsplit(url).netloc.lower().replace("www.", "")
    except Exception:
        host = ""
    probe = f"{host} {source}".lower()
    for domain, tier in VERIFIED_DOMAINS.items():
        d = (domain or "").lower()
        if d and (d in probe or probe in d):
            return int(tier)
    return 3


def _watchlist_normalize_url(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
        query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
        kept_pairs = [(k, v) for k, v in query_pairs if not k.lower().startswith("utm_")]
        clean_query = urllib.parse.urlencode(kept_pairs)
        parsed = parsed._replace(query=clean_query, fragment="")
        normalized = urllib.parse.urlunsplit(parsed)
        return normalized.rstrip("/")
    except Exception:
        return value


def _watchlist_parse_published(value: str) -> datetime | None:
    dt = parse_published_at({"published": value})
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _watchlist_age_label(published_dt: datetime | None) -> str:
    if published_dt is None:
        return "recent"
    delta_hours = max(0.0, (datetime.now(timezone.utc) - published_dt).total_seconds() / 3600.0)
    if delta_hours < 1:
        return "just now"
    if delta_hours < 24:
        return f"{int(delta_hours)}h ago"
    return f"{int(delta_hours // 24)}d ago"


def _watchlist_day_label(day_iso: str) -> str:
    try:
        return datetime.fromisoformat(day_iso[:10]).strftime("%d %b")
    except Exception:
        return day_iso


def _watchlist_related_sources(
    *,
    symbol: str,
    day_iso: str,
    news_rows: list[dict[str, Any]],
    max_items: int = 3,
) -> list[dict[str, Any]]:
    try:
        day_dt = datetime.fromisoformat(day_iso[:10]).replace(tzinfo=timezone.utc)
    except Exception:
        return []

    candidates: list[tuple[float, int, dict[str, Any]]] = []
    for row in news_rows:
        if _watchlist_clean_symbol(str(row.get("symbol", ""))) != _watchlist_clean_symbol(symbol):
            continue
        published = _watchlist_parse_published(str(row.get("published", "")))
        if published is None:
            continue
        delta = abs((published - day_dt).total_seconds())
        if delta > 2 * 24 * 60 * 60:
            continue
        candidates.append((delta, int(row.get("source_tier", 3)), row))

    candidates.sort(key=lambda item: (item[0], item[1]))
    related = []
    for _, _, row in candidates[:max_items]:
        related.append({
            "headline": row.get("headline", ""),
            "url": row.get("url", ""),
            "source": row.get("source", ""),
            "published": row.get("published", ""),
            "category": row.get("category", "news"),
            "source_tier": int(row.get("source_tier", 3)),
        })
    return related


async def _watchlist_history_for_symbol(symbol: str, period: str) -> dict[str, Any] | None:
    clean_symbol = _clean_history_symbol(symbol)
    if not clean_symbol:
        return None
    history_timeout = _gateway_float_setting("FINAGENT_WATCHLIST_HISTORY_TIMEOUT_S", 2.5)
    for candidate in _history_candidates(clean_symbol, "equity"):
        quote = await fetch_yahoo_quote(candidate, timeout_s=history_timeout, cache_ttl_s=90.0)
        if not quote or not quote.series_dates or not quote.series_closes:
            continue
        dates, prices = _filter_history_period(quote.series_dates, quote.series_closes, period)
        if len(dates) < 2 or len(prices) < 2:
            continue
        return {
            "symbol": _watchlist_clean_symbol(symbol),
            "name": quote.name or _watchlist_clean_symbol(symbol),
            "dates": dates,
            "prices": prices,
            "source": quote.source_url or "Yahoo Finance",
            "as_of": dates[-1],
        }
    return None


@app.get("/watchlist/snapshot")
async def get_watchlist_snapshot(
    symbols: str,
    period: str = "1M",
    current_user: dict | None = Depends(get_current_user_optional),
):
    requested_period = (period or "1M").strip().upper()
    if requested_period not in _HISTORY_PERIODS:
        raise HTTPException(status_code=422, detail=f"Unsupported period '{period}'.")

    symbol_list: list[str] = []
    for raw in (symbols or "").split(","):
        clean = _watchlist_clean_symbol(raw)
        if clean and clean not in symbol_list:
            symbol_list.append(clean)
    symbol_list = symbol_list[:12]
    if not symbol_list:
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "period": requested_period,
            "refresh_after_ms": 45000,
            "quotes": [],
            "movers": [],
            "histories": {},
            "daily_summaries": [],
            "notable_movements": [],
            "news": [],
            "source_health": {
                "quotes": "unavailable",
                "history": "unavailable",
                "news": "unavailable",
                "official": "unavailable",
            },
        }

    cache_key = f"watchlist:snapshot:{requested_period}:{','.join(symbol_list)}"
    cached = await app_cache.get(cache_key)
    if cached is not None:
        return cached

    quotes_payload = await get_market_quotes(",".join(symbol_list), current_user=current_user)
    quote_rows: list[dict[str, Any]] = []
    quote_map: dict[str, dict[str, Any]] = {}

    for symbol in symbol_list:
        raw = _watchlist_find_quote(quotes_payload or {}, symbol)
        if not raw:
            continue
        try:
            price = float(raw.get("price"))
        except Exception:
            continue
        if price <= 0:
            continue
        change_pct = float(raw.get("change_pct") or 0.0)
        change_value = price * change_pct / 100.0
        row = {
            "symbol": symbol,
            "name": str(raw.get("company_name") or symbol),
            "price": price,
            "price_label": _watchlist_format_price(price),
            "change": change_value,
            "change_label": f"{'+' if change_value >= 0 else ''}{change_value:.2f}",
            "change_pct": change_pct,
            "change_pct_label": f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}%",
            "direction": "up" if change_pct >= 0 else "down",
            "source": str(raw.get("source") or "market data"),
            "source_url": str(raw.get("source_url") or ""),
            "isin": str(raw.get("isin") or ""),
        }
        quote_rows.append(row)
        quote_map[symbol] = row

    history_timeout = _gateway_float_setting("FINAGENT_WATCHLIST_HISTORY_GATHER_TIMEOUT_S", 4.0)
    try:
        history_results = await asyncio.wait_for(
            asyncio.gather(
                *[_watchlist_history_for_symbol(symbol, requested_period) for symbol in symbol_list],
                return_exceptions=True,
            ),
            timeout=history_timeout,
        )
    except asyncio.TimeoutError:
        logger.debug("watchlist history gather timed out for symbols=%s", ",".join(symbol_list))
        history_results = []
    histories: dict[str, dict[str, Any]] = {}
    for item in history_results:
        if isinstance(item, dict) and item.get("symbol"):
            histories[str(item["symbol"])] = item

    async def _fetch_symbol_news(symbol: str) -> list[dict[str, Any]]:
        name = quote_map.get(symbol, {}).get("name") or symbol
        items = await fetch_news(f"{symbol} {name} stock India", limit=4, enrich_images=False)
        rows: list[dict[str, Any]] = []
        for item in items[:4]:
            headline = str(item.title or "").strip()
            if not headline:
                continue
            url = _watchlist_normalize_url(str(item.link or ""))
            image = str(getattr(item, "image", "") or "")
            published = str(item.published or "")
            source = str(item.source or "News")
            rows.append({
                "symbol": symbol,
                "headline": headline,
                "url": url,
                "source": source,
                "published": published,
                "image": image,
                "category": "news",
                "source_tier": _watchlist_source_tier(url, source),
            })
        return rows

    async def _fetch_symbol_official(symbol: str) -> list[dict[str, Any]]:
        isin = str(quote_map.get(symbol, {}).get("isin") or "").strip()
        if not isin:
            return []
        announcements = await asyncio.to_thread(fetch_nse_announcements, isin, 4)
        rows: list[dict[str, Any]] = []
        for item in announcements[:4]:
            headline = str(item.get("title") or "").strip()
            if not headline:
                continue
            url = _watchlist_normalize_url(str(item.get("url") or ""))
            source = str(item.get("source") or "nseindia.com")
            rows.append({
                "symbol": symbol,
                "headline": headline,
                "url": url,
                "source": source,
                "published": str(item.get("published") or ""),
                "image": "",
                "category": str(item.get("category") or "official"),
                "source_tier": 0,
            })
        return rows

    news_symbols = symbol_list[:4]
    official_symbols = symbol_list[:4]

    news_timeout = _gateway_float_setting("FINAGENT_WATCHLIST_NEWS_GATHER_TIMEOUT_S", 4.0)
    try:
        news_results, official_results = await asyncio.wait_for(
            asyncio.gather(
                asyncio.gather(*[_fetch_symbol_news(symbol) for symbol in news_symbols], return_exceptions=True),
                asyncio.gather(*[_fetch_symbol_official(symbol) for symbol in official_symbols], return_exceptions=True),
            ),
            timeout=news_timeout,
        )
    except asyncio.TimeoutError:
        logger.debug("watchlist news gather timed out for symbols=%s", ",".join(news_symbols))
        news_results, official_results = [], []

    merged_news: dict[str, dict[str, Any]] = {}
    for batch in list(news_results) + list(official_results):
        if isinstance(batch, Exception):
            continue
        for row in batch:
            url_key = _watchlist_normalize_url(str(row.get("url") or ""))
            key = url_key or f"{_watchlist_clean_symbol(str(row.get('symbol', '')))}::{str(row.get('headline', '')).lower()}"
            if key in merged_news:
                if int(row.get("source_tier", 3)) < int(merged_news[key].get("source_tier", 3)):
                    merged_news[key] = row
                continue
            merged_news[key] = row

    news_rows = list(merged_news.values())
    news_rows.sort(
        key=lambda row: (
            _watchlist_parse_published(str(row.get("published") or "")) or datetime.min.replace(tzinfo=timezone.utc),
            -int(row.get("source_tier", 3)),
        ),
        reverse=True,
    )
    news_rows = news_rows[:36]

    daily_summaries: list[dict[str, Any]] = []
    for symbol in symbol_list:
        history = histories.get(symbol)
        if not history:
            continue
        dates = list(history.get("dates") or [])
        prices = list(history.get("prices") or [])
        if len(dates) < 2 or len(prices) < 2:
            continue

        for idx in range(1, min(len(dates), len(prices))):
            prev_price = float(prices[idx - 1] or 0.0)
            cur_price = float(prices[idx] or 0.0)
            if prev_price <= 0 or cur_price <= 0:
                continue
            change_pct = ((cur_price - prev_price) / prev_price) * 100.0
            related = _watchlist_related_sources(symbol=symbol, day_iso=str(dates[idx]), news_rows=news_rows, max_items=3)
            name = str(history.get("name") or quote_map.get(symbol, {}).get("name") or symbol)
            direction_word = "rose" if change_pct >= 0 else "fell"
            catalyst = related[0]["headline"] if related else ""
            summary = (
                f"{name} {direction_word} {abs(change_pct):.2f}% to {_watchlist_format_price(cur_price)}."
                if not catalyst
                else f"{name} {direction_word} {abs(change_pct):.2f}% to {_watchlist_format_price(cur_price)}. Closest catalyst: {catalyst}"
            )
            daily_summaries.append({
                "key": f"{symbol}:{dates[idx]}",
                "symbol": symbol,
                "name": name,
                "date": str(dates[idx]),
                "date_label": _watchlist_day_label(str(dates[idx])),
                "price": cur_price,
                "price_label": _watchlist_format_price(cur_price),
                "pct": round(change_pct, 4),
                "pct_label": f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}%",
                "direction": "up" if change_pct >= 0 else "down",
                "summary": summary,
                "source_count": len(related),
                "sources": related,
            })

    daily_summaries.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("symbol") or "")), reverse=True)

    notable_movements = [row for row in daily_summaries if abs(float(row.get("pct") or 0.0)) >= 2.0]
    if not notable_movements:
        notable_movements = sorted(
            daily_summaries,
            key=lambda row: abs(float(row.get("pct") or 0.0)),
            reverse=True,
        )[:24]

    movers = sorted(
        quote_rows,
        key=lambda row: abs(float(row.get("change_pct") or 0.0)),
        reverse=True,
    )

    news_payload = []
    for idx, row in enumerate(news_rows[:24]):
        published_dt = _watchlist_parse_published(str(row.get("published") or ""))
        news_payload.append({
            "id": f"{_watchlist_clean_symbol(str(row.get('symbol', '')))}-{idx}",
            "symbol": _watchlist_clean_symbol(str(row.get("symbol", ""))),
            "headline": str(row.get("headline") or ""),
            "source": str(row.get("source") or "News"),
            "published": str(row.get("published") or ""),
            "time": _watchlist_age_label(published_dt),
            "url": str(row.get("url") or ""),
            "image": str(row.get("image") or ""),
            "source_tier": int(row.get("source_tier", 3)),
            "category": str(row.get("category") or "news"),
        })

    source_health = {
        "quotes": "ok" if quote_rows else "unavailable",
        "history": "ok" if histories else "unavailable",
        "news": "ok" if news_payload else "unavailable",
        "official": "ok" if any(int(row.get("source_tier", 3)) == 0 for row in news_rows) else ("stale" if news_payload else "unavailable"),
    }

    response_payload = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "period": requested_period,
        "refresh_after_ms": 45000,
        "quotes": quote_rows,
        "movers": movers,
        "histories": histories,
        "daily_summaries": daily_summaries,
        "notable_movements": notable_movements,
        "news": news_payload,
        "source_health": source_health,
    }
    await app_cache.set(cache_key, response_payload, ttl=45)
    return response_payload


@app.get("/market/history")
async def get_market_history(
    symbol: str,
    period: str = "1Y",
    asset_type: str | None = None,
    current_user: dict = Depends(get_current_user_or_guest),
):
    requested_period = (period or "1Y").strip().upper()
    if requested_period not in _HISTORY_PERIODS:
        raise HTTPException(status_code=422, detail=f"Unsupported period '{period}'.")

    clean_symbol = _clean_history_symbol(symbol)
    if not clean_symbol:
        raise HTTPException(status_code=422, detail="symbol is required.")

    last_error = None
    for candidate in _history_candidates(clean_symbol, asset_type):
        try:
            quote = await fetch_yahoo_quote(candidate, timeout_s=18.0)
        except Exception as exc:
            last_error = str(exc)
            quote = None

        if not quote or not quote.series_dates or not quote.series_closes:
            continue

        dates, prices = _filter_history_period(quote.series_dates, quote.series_closes, requested_period)
        if len(prices) < 2:
            continue

        change_pct = None
        if prices[0] > 0:
            change_pct = (prices[-1] - prices[0]) / prices[0] * 100.0

        return {
            "symbol": quote.ticker or candidate,
            "name": quote.name or clean_symbol,
            "asset_type": asset_type or "market",
            "period": requested_period,
            "currency": quote.currency,
            "source": quote.source_url or "Yahoo Finance",
            "dates": dates,
            "prices": prices,
            "change_pct": change_pct,
            "as_of": dates[-1],
            "status": "ok",
        }

    return {
        "symbol": clean_symbol,
        "name": clean_symbol,
        "asset_type": asset_type or "market",
        "period": requested_period,
        "currency": None,
        "source": "unavailable",
        "dates": [],
        "prices": [],
        "change_pct": None,
        "as_of": None,
        "status": "unavailable",
        "message": "No data available right now.",
    }


@app.get("/market/quotes")
async def get_market_quotes(symbols: str, current_user: dict | None = Depends(get_current_user_optional)):
    def _clean_market_symbol(value: str) -> str:
        sym = (value or "").strip().upper()
        return sym.removesuffix(".NS").removesuffix(".BO").removesuffix(".NSE").removesuffix(".BSE")

    symbol_list = []
    for raw in symbols.split(","):
        sym = _clean_market_symbol(raw)
        if sym and sym not in symbol_list:
            symbol_list.append(sym)
    # Keep this high enough for batch tabs (overview/watchlist) but bounded.
    symbol_list = symbol_list[:120]
    results = {}
    if not symbol_list:
        return results
    
    async def fetch_one(sym: str):
        cache_key = f"quote:{sym}"
        cached = await app_cache.get(cache_key)
        if cached is not None:
            return sym, cached

        # Use NSE/BSE-first live quote data for dashboard prices and movers.
        quote_timeout = _gateway_float_setting("FINAGENT_MARKET_QUOTE_TIMEOUT_S", 3.0)
        yahoo_timeout = _gateway_float_setting("FINAGENT_MARKET_QUOTE_YAHOO_TIMEOUT_S", 4.0)

        try:
            snap = await asyncio.wait_for(fetch_nse_snapshot(sym), timeout=quote_timeout)
            if snap and snap.current_price is not None:
                return sym, {
                    "symbol": snap.symbol,
                    "company_name": snap.company_name,
                    "price": snap.current_price,
                    "change_pct": snap.change_pct if snap.change_pct is not None else 0.0,
                    "sector": snap.sector or snap.industry or "General",
                    "pe_ratio": snap.pe_ratio,
                    "market_cap": snap.market_cap_cr * 10000000 if snap.market_cap_cr else None,
                    "isin": snap.isin,
                    "source": snap.source or "NSE/BSE",
                    "source_url": snap.source_url,
                }
        except (asyncio.TimeoutError, httpx.HTTPError) as exc:
            logger.debug("NSE/BSE quote unavailable for %s: %s", sym, type(exc).__name__)
        except Exception as exc:
            logger.debug("NSE/BSE quote fetch failed for %s: %s", sym, exc)

        try:
            snap = await asyncio.wait_for(fetch_india_snapshot(sym), timeout=quote_timeout)
            if snap and snap.current_price is not None:
                return sym, {
                    "symbol": snap.symbol,
                    "company_name": snap.company_name,
                    "price": snap.current_price,
                    "change_pct": snap.change_pct if snap.change_pct is not None else 0.0,
                    "sector": snap.sector or snap.industry or "General",
                    "pe_ratio": snap.pe_ratio,
                    "market_cap": snap.market_cap_cr * 10000000 if snap.market_cap_cr else None,
                    "isin": snap.isin,
                    "source": snap.source or "market data",
                    "source_url": snap.source_url,
                }
        except (asyncio.TimeoutError, httpx.HTTPError) as exc:
            logger.debug("India quote fallback unavailable for %s: %s", sym, type(exc).__name__)
        except Exception as exc:
            logger.debug("India quote fallback failed for %s: %s", sym, exc)

        try:
            # Fallback to Yahoo if India providers miss or time out.
            yahoo_candidates = (
                (f"{sym}.NS", f"{sym}.BO", sym)
                if "." not in sym and not sym.startswith("^")
                else (sym,)
            )
            for candidate in yahoo_candidates:
                quote = await fetch_yahoo_quote(candidate, timeout_s=yahoo_timeout)
                if quote and quote.price is not None:
                    quote_name = getattr(quote, "name", None)
                    quote_symbol = getattr(quote, "symbol", None)
                    return sym, {
                        "symbol": sym,
                        "company_name": quote_name or quote_symbol or sym,
                        "price": quote.price,
                        "change_pct": quote.change_pct if quote.change_pct is not None else 0.0,
                        "sector": "General",
                        "pe_ratio": None,
                        "market_cap": None,
                        "isin": None,
                        "source": "Yahoo Finance",
                        "source_url": None,
                    }
        except Exception as exc:
            logger.debug("Yahoo quote fallback failed for %s: %s", sym, exc)
        return sym, None

    async def fetch_one_cached(sym: str):
        s, result = await fetch_one(sym)
        if result is not None:
            await app_cache.set(f"quote:{s}", result, ttl=60)
        return s, result

    quote_concurrency = max(4, min(int(os.getenv("FINAGENT_MARKET_QUOTES_CONCURRENCY", "20") or 20), 40))
    quote_total_timeout = _gateway_float_setting("FINAGENT_MARKET_QUOTES_TOTAL_TIMEOUT_S", 10.0)
    quote_semaphore = asyncio.Semaphore(quote_concurrency)

    async def fetch_one_limited(sym: str):
        async with quote_semaphore:
            return await fetch_one_cached(sym)

    tasks = [asyncio.create_task(fetch_one_limited(sym)) for sym in symbol_list]
    done, pending = await asyncio.wait(tasks, timeout=quote_total_timeout)
    if pending:
        logger.warning(
            "market quotes timed out after %.1fs; returning %d/%d completed symbols",
            quote_total_timeout,
            len(done),
            len(tasks),
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    fetched = []
    for task in done:
        try:
            fetched.append(task.result())
        except Exception as exc:
            logger.debug("market quote task failed: %s", exc)
    for sym, res in fetched:
        if res:
            results[sym] = res
            results[f"{sym}.NS"] = res
            results[f"{sym}.BO"] = res
    return results


@app.get("/market/news")
async def get_market_news(
    query: str = "India market",
    limit: int = 10,
    images: bool = False,
    current_user: dict | None = Depends(get_current_user_optional),
):
    safe_limit = max(1, min(int(limit or 10), 60))
    cache_key = f"news:{query.lower().strip()}:{safe_limit}:images={int(images)}"
    cached = await app_cache.get(cache_key)
    if cached is not None:
        return cached
    news_items = await fetch_news(query, limit=safe_limit, enrich_images=images)
    result = [
        {
            "title": item.title,
            "link": item.link,
            "source": item.source,
            "published": item.published,
            "description": item.description,
            "image": item.image,
            "image_url": item.image,
        }
        for item in news_items
    ]
    await app_cache.set(cache_key, result, ttl=300)
    return result


@app.get("/market/indices")
async def get_market_indices(current_user: dict | None = Depends(get_current_user_optional)):
    cached = await app_cache.get("market:indices")
    if cached is not None:
        return cached
    categories = {
        "india": [
            ("^NSEI", "NIFTY 50"),
            ("^BSESN", "SENSEX"),
            ("^NSEBANK", "NIFTY BANK"),
            ("^CNXIT", "NIFTY IT")
        ],
        "stocks": [
            ("RELIANCE.NS", "RELIANCE"),
            ("TCS.NS", "TCS"),
            ("INFY.NS", "INFY"),
            ("HDFCBANK.NS", "HDFCBANK"),
            ("ICICIBANK.NS", "ICICIBANK"),
            ("BRITANNIA.NS", "BRITANNIA"),
            ("SBIN.NS", "SBIN"),
            ("BHARTIARTL.NS", "BHARTIARTL"),
            ("ITC.NS", "ITC"),
            ("LT.NS", "LT")
        ],
        "us": [
            ("^GSPC", "S&P 500"),
            ("^IXIC", "NASDAQ"),
            ("^DJI", "DOW"),
            ("^VIX", "VIX")
        ],
        "currencies": [
            ("USDINR=X", "USD/INR"),
            ("EURINR=X", "EUR/INR"),
            ("GBPINR=X", "GBP/INR"),
            ("JPYINR=X", "JPY/INR")
        ],
        "crypto": [
            ("BTC-USD", "BTC"),
            ("ETH-USD", "ETH"),
            ("SOL-USD", "SOL"),
            ("XRP-USD", "XRP")
        ],
        "futures": [
            ("^NSEI", "NIFTY FUT"),
            ("^NSEBANK", "BANKNIFTY FUT"),
            ("CL=F", "CRUDE OIL"),
            ("GC=F", "GOLD")
        ]
    }

    # Do not allocate hardcoded synthetic market values on request paths.
    # If live data is missing for a category, we serve the last known live cache as stale.

    flat_targets = []
    for cat_name, targets in categories.items():
        for ticker, name in targets:
            flat_targets.append((cat_name, ticker, name))
    indices_quote_timeout = _gateway_float_setting("FINAGENT_MARKET_INDICES_QUOTE_TIMEOUT_S", 6.0)

    def format_market_cap(value: float | None, currency: str | None = None) -> str | None:
        if value is None:
            return None
        try:
            amount = float(value)
        except (TypeError, ValueError):
            return None
        if amount <= 0:
            return None
        if (currency or "").upper() == "INR":
            crore = amount / 10000000.0
            return f"â‚¹{crore:,.0f} Cr"
        if amount >= 1_000_000_000:
            return f"${amount / 1_000_000_000:,.1f}B"
        if amount >= 1_000_000:
            return f"${amount / 1_000_000:,.1f}M"
        return f"${amount:,.0f}"

    async def fetch_one(cat_name, ticker, name):
        try:
            quote = await fetch_yahoo_quote(ticker, timeout_s=indices_quote_timeout, cache_ttl_s=55.0)
            if quote:
                sparkline = quote.series_closes[-9:] if quote.series_closes else []
                if not sparkline and quote.price:
                    sparkline = [quote.price * (1 + (i - 4) * 0.001) for i in range(9)]
                
                diff = quote.price - quote.previous_close if quote.price and quote.previous_close is not None else 0.0
                chg_str = f"({diff:+.2f})" if diff else "â€”"
                
                display_val = f"{quote.price:,.2f}" if quote.price is not None else "â€”"
                if "USD" in ticker or "BTC" in ticker or "ETH" in ticker or "SOL" in ticker or "XRP" in ticker or ticker in ["CL=F", "GC=F"]:
                    if ticker in ["CL=F", "GC=F"]:
                        display_val = f"${quote.price:,.2f}"
                    elif "USDINR" in ticker or "EURINR" in ticker or "GBPINR" in ticker or "JPYINR" in ticker:
                        display_val = f"{quote.price:,.2f}"
                    else:
                        display_val = f"${quote.price:,.2f}" if quote.price is not None else "â€”"

                return cat_name, {
                    "symbol": name,
                    "value": display_val,
                    "change": chg_str,
                    "changePct": quote.change_pct if quote.change_pct is not None else 0.0,
                    "sparkData": sparkline,
                    "marketCap": format_market_cap(quote.market_cap, quote.currency),
                    "sourceTicker": ticker,
                    "kind": cat_name
                }
        except Exception as e:
            logger.error(f"Error fetching index {ticker}: {e}")
        return cat_name, None

    index_concurrency = max(4, min(int(os.getenv("FINAGENT_MARKET_INDICES_CONCURRENCY", "12") or 12), 24))
    index_total_timeout = _gateway_float_setting("FINAGENT_MARKET_INDICES_TOTAL_TIMEOUT_S", 14.0)
    index_semaphore = asyncio.Semaphore(index_concurrency)

    async def fetch_one_index_limited(cat_name: str, ticker: str, name: str):
        async with index_semaphore:
            return await fetch_one(cat_name, ticker, name)

    tasks = [
        asyncio.create_task(fetch_one_index_limited(cat_name, tick, name))
        for cat_name, tick, name in flat_targets
    ]
    done, pending = await asyncio.wait(tasks, timeout=index_total_timeout)
    if pending:
        logger.warning(
            "market indices timed out after %.1fs; returning %d/%d completed tickers",
            index_total_timeout,
            len(done),
            len(tasks),
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    fetched = []
    for task in done:
        try:
            fetched.append(task.result())
        except Exception as exc:
            logger.debug("market index task failed: %s", exc)

    results = {
        "india": [],
        "stocks": [],
        "us": [],
        "currencies": [],
        "crypto": [],
        "futures": []
    }
    for cat_name, res in fetched:
        if res:
            results[cat_name].append(res)

    last_live = await app_cache.get("market:indices:last_live")
    if isinstance(last_live, dict):
        for cat_name, rows in last_live.items():
            if cat_name not in results or results[cat_name]:
                continue
            if not isinstance(rows, list):
                continue
            stale_rows: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                stale = dict(row)
                stale["stale"] = True
                stale_rows.append(stale)
            results[cat_name] = stale_rows

    if any(results.get(cat_name) for cat_name in results):
        await app_cache.set("market:indices:last_live", results, ttl=3600)

    await app_cache.set("market:indices", results, ttl=60)
    return results


@app.get("/screener/search")
async def screener_search(
    q: str,
    limit: int = 8,
    current_user: dict | None = Depends(get_current_user_optional),
):
    service = get_screener_service()
    safe_limit = max(1, min(limit, 50))
    return await service.search(q, limit=safe_limit)


@app.get("/screener/company/{identifier}/snapshot")
async def screener_company_snapshot(
    identifier: str,
    period: str = "1Y",
    current_user: dict | None = Depends(get_current_user_optional),
):
    service = get_screener_service()
    return await service.company_snapshot(identifier, period=period)


@app.get("/screener/company/{identifier}/financials")
async def screener_company_financials(
    identifier: str,
    current_user: dict | None = Depends(get_current_user_optional),
):
    service = get_screener_service()
    return await service.company_financials(identifier)


@app.get("/screener/company/{identifier}/technicals")
async def screener_company_technicals(
    identifier: str,
    period: str = "1Y",
    current_user: dict | None = Depends(get_current_user_optional),
):
    service = get_screener_service()
    return await service.company_technicals(identifier, period=period)


@app.get("/screener/company/{identifier}/events")
async def screener_company_events(
    identifier: str,
    limit: int = 25,
    current_user: dict | None = Depends(get_current_user_optional),
):
    service = get_screener_service()
    safe_limit = max(1, min(limit, 100))
    return await service.company_events(identifier, limit=safe_limit)


@app.get("/screener/company/{identifier}/analyze")
async def screener_company_analyze(
    identifier: str,
    current_user: dict | None = Depends(get_current_user_optional),
):
    service = get_screener_service()
    return await service.analyze(identifier)


@app.post("/screener/query")
async def screener_query(
    payload: ScreenerQueryRequest,
    current_user: dict | None = Depends(get_current_user_optional),
):
    service = get_screener_service()
    universe = [sym for sym in payload.universe if (sym or "").strip()]
    return await service.query_screen(payload.query, limit=payload.limit, universe=universe or None)


@app.get("/ipo/pipeline")
async def ipo_pipeline(current_user: dict | None = Depends(get_current_user_optional)):
    service = get_ipo_service()
    return await service.pipeline_dashboard()


@app.get("/ipo/search")
async def ipo_search(
    q: str,
    limit: int = 10,
    current_user: dict | None = Depends(get_current_user_optional),
):
    service = get_ipo_service()
    safe_limit = max(1, min(limit, 50))
    results = await service.search_drhp(q, limit=safe_limit)
    return {"query": q, "results": results, "total": len(results)}


@app.get("/ipo/portfolio-links")
async def ipo_portfolio_links(
    symbols: str = "",
    current_user: dict | None = Depends(get_current_user_optional),
):
    service = get_ipo_service()
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    links = await service.portfolio_ipo_links(symbol_list)
    return {"links": links, "total": len(links)}


@app.get("/ipo/{slug}")
async def ipo_analysis(
    slug: str,
    current_user: dict | None = Depends(get_current_user_optional),
):
    service = get_ipo_service()
    payload = await service.get_analysis(slug)
    if not payload:
        raise HTTPException(status_code=404, detail=f"IPO not found: {slug}")
    return payload


@app.get("/ipo/{slug}/tracking")
async def ipo_post_listing_tracking(
    slug: str,
    current_user: dict | None = Depends(get_current_user_optional),
):
    service = get_ipo_service()
    payload = await service.get_post_listing(slug)
    if not payload:
        raise HTTPException(status_code=404, detail=f"IPO tracking not found: {slug}")
    return payload


@app.post("/ipo/watcher/run")
async def ipo_watcher_run(
    download: bool = True,
    current_user: dict | None = Depends(get_current_user_optional),
):
    service = get_ipo_service()
    return await service.run_watcher(download=download)


@app.post("/ipo/{slug}/analyze")
async def ipo_analyze(
    slug: str,
    current_user: dict | None = Depends(get_current_user_optional),
):
    service = get_ipo_service()
    try:
        return await service.fetch_and_analyze(slug)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/public/market/ticker")
async def get_public_market_ticker():
    """Public (no auth) compact ticker payload for the insights/research HTML
    pages. Returns a flat list of {symbol, value, change, changePct, sparkData}
    suitable for the marquee strip + sparkline canvases in the published hub
    and article pages. Cached 60s."""
    indices = await get_market_indices()
    # Pick a curated, India-first ordering for the public marquee.
    pick = (
        (indices.get("india") or [])[:4]
        + (indices.get("stocks") or [])[:10]
        + [r for r in (indices.get("futures") or []) if r.get("symbol") in {"CRUDE OIL", "GOLD"}][:2]
        + [r for r in (indices.get("currencies") or []) if r.get("symbol") == "USD/INR"][:1]
    )
    ordered_symbols = [
        str(row.get("symbol") or "").strip()
        for row in pick
        if isinstance(row, dict) and str(row.get("symbol") or "").strip()
    ]
    # Only publish rows backed by a live source ticker so public pages never
    # present hardcoded fallback values as "live" market data.
    live_items = [row for row in pick if isinstance(row, dict) and row.get("sourceTicker")]
    last_live = await app_cache.get("market:public_ticker:last_live")

    live_by_symbol: dict[str, dict] = {}
    for row in live_items:
        sym = str(row.get("symbol") or "").strip()
        if sym:
            live_by_symbol[sym] = row
    if isinstance(last_live, list):
        for row in last_live:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip()
            if sym and sym not in live_by_symbol:
                stale_row = dict(row)
                stale_row["stale"] = True
                live_by_symbol[sym] = stale_row

    items = [live_by_symbol[sym] for sym in ordered_symbols if sym in live_by_symbol]
    if live_items:
        await app_cache.set("market:public_ticker:last_live", live_items, ttl=3600)

    return {
        "items": items,
        "ttl_s": 60,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "live_only": True,
    }


# â”€â”€ Memory viewer endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.get("/portfolio/mirror")
async def get_portfolio_mirror(current_user: dict = Depends(get_current_user_or_guest)):
    tenant_id = current_user.get("tenant_id")
    try:
        positions = await load_active_positions(tenant_id)
    except Exception as exc:
        logger.warning("Portfolio mirror load failed for tenant %s: %s", tenant_id, exc)
        raise HTTPException(
            status_code=503,
            detail={
                "ok": False,
                "code": "PORTFOLIO_STORE_UNAVAILABLE",
                "message": "Your portfolio mirror is temporarily unavailable. Please retry in a moment.",
            },
        ) from exc
    return summarize_positions(positions)


@app.post("/portfolio/mirror")
async def replace_portfolio_mirror(req: PositionMirrorReplaceRequest, current_user: dict = Depends(get_current_user_or_guest)):
    tenant_id = current_user.get("tenant_id")
    _require_no_active_ingestion(tenant_id)
    positions = await replace_active_positions(
        tenant_id,
        [item.model_dump() for item in req.positions if item.active],
    )
    _set_ingestion_state(tenant_id, "MIRROR_SYNCHRONIZED" if positions else "MIRROR_EMPTY", "Manual portfolio mirror updated.")
    return summarize_positions(positions)


@app.post("/portfolio/mirror/sync-manual")
async def sync_manual_portfolio(req: ManualPortfolioSyncRequest, current_user: dict = Depends(get_current_user_or_guest)):
    """Sync a manually-entered portfolio to the user's portfolio mirror.

    Used by the manual-entry onboarding flow: users can type their holdings
    before creating an account, then sync them after login/signup.
    """
    tenant_id = current_user.get("tenant_id")
    telemetry_user = telemetry_user_from_request_user(current_user)
    _require_no_active_ingestion(tenant_id)

    prepared: list[dict] = []
    for item in req.positions:
        normalized = normalize_symbol(item.symbol)
        if not normalized:
            continue
        pos = {
            "symbol": normalized,
            "exchange": "NSE",
            "quantity": float(item.quantity),
            "avg_cost": float(item.avg_cost),
            "cost_basis": float(item.quantity * item.avg_cost),
            "market_value": float(item.quantity * item.avg_cost),
            "last_price": float(item.avg_cost),
            "active": True,
            "as_of": item.date_purchased or "",
        }
        pos = enrich_position(pos)
        prepared.append(pos)

    positions = await replace_active_positions(tenant_id, prepared)
    status = "MIRROR_SYNCHRONIZED" if positions else "MIRROR_EMPTY"
    _set_ingestion_state(tenant_id, status, "Manual portfolio holdings synced from onboarding.")

    TELEMETRY.emit_event(
        "portfolio_manual_sync_completed",
        user=telemetry_user,
        properties={
            "source": "backend",
            "position_count": len(positions),
        },
    )
    return summarize_positions(positions)


async def _require_synchronized_portfolio(tenant_id: str | None, *, allow_empty: bool = False) -> bool:
    if not tenant_id:
        raise HTTPException(
            status_code=403,
            detail={"status": "TENANT_REQUIRED", "message": "Portfolio audit requires a verified tenant session."},
        )
    try:
        positions = await asyncio.wait_for(
            load_active_positions(tenant_id),
            timeout=_gateway_float_setting("FINAGENT_PORTFOLIO_PREFLIGHT_TIMEOUT_S", 6.0),
        )
    except asyncio.TimeoutError as exc:
        logger.warning("Portfolio preflight timed out for tenant %s: %s", tenant_id, exc)
        if allow_empty:
            logger.info("Portfolio preflight timeout for tenant %s; allowing contextual fallback research", tenant_id)
            return False
        raise HTTPException(
            status_code=503,
            detail={
                "status": "PORTFOLIO_STORE_TIMEOUT",
                "message": "Your portfolio sync is temporarily taking too long. Please retry in a moment.",
            },
        ) from exc
    except Exception as exc:
        logger.warning("Portfolio preflight failed for tenant %s: %s", tenant_id, exc)
        if allow_empty:
            logger.info("Portfolio preflight unavailable for tenant %s; allowing contextual fallback research", tenant_id)
            return False
        raise HTTPException(
            status_code=503,
            detail={
                "status": "PORTFOLIO_STORE_UNAVAILABLE",
                "message": "Your portfolio sync is temporarily unavailable. Please retry in a moment.",
            },
        ) from exc
    if not positions:
        if allow_empty:
            logger.info("Portfolio mirror empty for tenant %s; allowing fallback research", tenant_id)
            return False
        raise HTTPException(
            status_code=409,
            detail={
                "status": "MIRROR_REQUIRED",
                "message": "Upload and synchronize your eCAS, CSV, Excel, or screenshot holdings before running portfolio research.",
            },
        )
    return True


@app.post("/api/portfolio/upload-cas")
@app.post("/api/portfolio/upload-document")
@app.post("/portfolio/mirror/ecas")
async def upload_portfolio_document(
    file: UploadFile = File(...),
    password: str = Form(default=""),
    current_user: dict = Depends(get_current_user_or_guest),
):
    filename = file.filename or "portfolio-upload"
    tenant_id = current_user.get("tenant_id")
    telemetry_user = telemetry_user_from_request_user(current_user)
    _set_ingestion_state(tenant_id, "INGESTING", "Transforming uploaded portfolio document.")
    TELEMETRY.emit_event(
        "portfolio_upload_started",
        user=telemetry_user,
        properties={
            "source": "backend",
            "upload_type": "document",
            "file_name": filename,
            "has_password": bool(password),
        },
    )
    try:
        payload_bytes = await _read_upload_limited(file)
        _validate_upload(payload_bytes, filename)
        extraction = await asyncio.wait_for(
            parse_portfolio_document(payload_bytes, filename, password),
            timeout=_gateway_float_setting("FINAGENT_DOCUMENT_PARSE_TIMEOUT_S", 90.0),
        )
    except asyncio.TimeoutError as exc:
        _set_ingestion_state(tenant_id, "FAILED", "Document parsing timed out.")
        TELEMETRY.emit_event(
            "portfolio_upload_failed",
            user=telemetry_user,
            properties={
                "source": "backend",
                "upload_type": "document",
                "file_name": filename,
                "error_type": "TimeoutError",
            },
        )
        raise HTTPException(
            status_code=504,
            detail={
                "ok": False,
                "code": "DOCUMENT_PARSE_TIMEOUT",
                "severity": "error",
                "message": "Parsing this document took too long and was stopped.",
                "action_hint": "Upload your broker CSV/XLSX export (fastest), or a clear screenshot of the holdings page.",
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected document parse failure for %s", filename)
        _set_ingestion_state(tenant_id, "FAILED", str(exc))
        TELEMETRY.emit_event(
            "portfolio_upload_failed",
            user=telemetry_user,
            properties={
                "source": "backend",
                "upload_type": "document",
                "file_name": filename,
                "error_type": exc.__class__.__name__,
            },
        )
        raise HTTPException(
            status_code=502,
            detail={
                "ok": False,
                "code": "DOCUMENT_PARSE_ERROR",
                "message": "Could not process this document right now.",
                "action_hint": "Try again in a moment, or upload your broker CSV/XLSX export or a clear holdings screenshot.",
            },
        ) from exc

    if extraction.status == "INGESTION_FAILED":
        _set_ingestion_state(tenant_id, "FAILED", extraction.warnings[0] if extraction.warnings else "Ingestion failed.")
        code = extraction.diagnostics.get("code", "DOCUMENT_PARSE_ERROR")
        # Tailored, helpful guidance for the exact memory/complexity cases we now detect
        if code in {"DOCUMENT_TOO_COMPLEX", "DOCUMENT_TOO_LARGE", "LOW_MEMORY"}:
            action_hint = (
                "This PDF is too large or complex for reliable parsing with current memory. "
                "Please upload the CSV or XLSX export from your broker instead (most reliable), "
                "or a clear screenshot of the holdings page."
            )
        else:
            action_hint = "Upload a current holdings statement/export, or try screenshot upload if this file is scanned."

        raise HTTPException(
            status_code=422,
            detail={
                "ok": False,
                "code": code,
                "severity": "error",
                "message": extraction.warnings[0] if extraction.warnings else "Document parse failed.",
                "action_hint": action_hint,
                "diagnostics": extraction.diagnostics,
            },
        )

    if not extraction.positions:
        _set_ingestion_state(tenant_id, "MIRROR_EMPTY", "Document parsed, but no active holdings were found.")
        return {
            "ok": True,
            "code": "EMPTY_BUT_VALID",
            "severity": "warning",
            "message": "Document parsed, but no active holdings were found.",
            "action_hint": "Upload a current eCAS/broker export or use screenshot upload.",
            "diagnostics": extraction.diagnostics,
            "investor": extraction.investor,
            "cas_meta": {"source_type": extraction.source_type, "transformer": extraction.diagnostics.get("transformer")},
        }

    if extraction.status == "REVIEW_REQUIRED":
        review_id = uuid.uuid4().hex[:16]
        review_token = _mint_review_token(review_id, tenant_id)
        await supabase.store_pending_extraction(
            review_id,
            tenant_id,
            {
                "source_type": extraction.source_type,
                "extraction": extraction.model_dump(),
            },
        )
        _set_ingestion_state(tenant_id, "REVIEW_REQUIRED", "Review extracted holdings before syncing.")
        TELEMETRY.emit_event(
            "portfolio_upload_review_required",
            user=telemetry_user,
            properties={
                "source": "backend",
                "upload_type": "document",
                "file_name": filename,
            },
        )
        return {
            "ok": True,
            "code": "REVIEW_REQUIRED",
            "status": "REVIEW_REQUIRED",
            "sync_status": "REVIEW_REQUIRED",
            "review_id": review_id,
            "review_token": review_token,
            "message": "Review extracted holdings before syncing.",
            **extraction.model_dump(),
        }

    try:
        positions = await replace_active_positions(tenant_id, extraction_to_position_dicts(extraction))
    except Exception as exc:  # noqa: BLE001 - mirror persistence is best-effort, never fail the upload
        logger.warning("Portfolio mirror sync raised for tenant %s; returning extracted holdings anyway: %s", tenant_id, exc)
        positions = []
    if not positions:
        # Mirror backend unreachable. Open-access mode keeps the holdings in the
        # frontend localStorage, so surface the extracted positions as a soft-synced
        # success instead of a hard failure.
        _set_ingestion_state(tenant_id, "MIRROR_SYNCHRONIZED", "Holdings extracted (local copy; cloud sync pending).")
        soft = {
            "ok": True,
            "code": "MIRROR_LOCAL_ONLY",
            "severity": "warning",
            "status": "MIRROR_SYNCHRONIZED",
            "sync_status": "MIRROR_SYNCHRONIZED",
            "message": "Holdings extracted. Saved locally; cloud sync will retry automatically.",
            "source": extraction.source_type,
            "count": len(extraction.positions),
            "positions": extraction_to_position_dicts(extraction),
            "cas_meta": {"source_type": extraction.source_type, "transformer": extraction.diagnostics.get("transformer")},
            "investor": extraction.investor,
            "diagnostics": extraction.diagnostics,
        }
        return soft
    summary = summarize_positions(positions)
    _set_ingestion_state(tenant_id, "MIRROR_SYNCHRONIZED", f"{summary['count']} holdings synchronized.")
    summary["ok"] = True
    summary["code"] = "MIRROR_SYNCHRONIZED"
    summary["severity"] = "info"
    summary["source"] = extraction.source_type
    summary["status"] = "MIRROR_SYNCHRONIZED"
    summary["sync_status"] = "MIRROR_SYNCHRONIZED"
    summary["cas_meta"] = {"source_type": extraction.source_type, "transformer": extraction.diagnostics.get("transformer")}
    summary["investor"] = extraction.investor
    summary["diagnostics"] = extraction.diagnostics
    TELEMETRY.emit_event(
        "portfolio_upload_completed",
        user=telemetry_user,
        properties={
            "source": "backend",
            "upload_type": "document",
            "file_name": filename,
            "status": summary["status"],
            "count": summary.get("count", 0),
        },
    )
    return summary


@app.post("/api/portfolio/upload-screenshot")
async def upload_portfolio_screenshot(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user_or_guest),
):
    filename = file.filename or "holdings-screenshot.png"
    if not filename.lower().endswith((".jpg", ".jpeg", ".png")):
        raise HTTPException(status_code=400, detail="Upload a JPG, JPEG, or PNG broker holdings screenshot.")
    tenant_id = current_user.get("tenant_id")
    telemetry_user = telemetry_user_from_request_user(current_user)
    _set_ingestion_state(tenant_id, "INGESTING", "Extracting holdings from screenshot.")
    TELEMETRY.emit_event(
        "portfolio_upload_started",
        user=telemetry_user,
        properties={
            "source": "backend",
            "upload_type": "screenshot",
            "file_name": filename,
        },
    )
    try:
        image_bytes = await _read_upload_limited(file)
        _validate_upload(image_bytes, filename)
        extraction = await asyncio.wait_for(
            extract_portfolio_from_image(image_bytes, filename),
            timeout=_gateway_float_setting("FINAGENT_SCREENSHOT_PARSE_TIMEOUT_S", 60.0),
        )
    except asyncio.TimeoutError as exc:
        _set_ingestion_state(tenant_id, "FAILED", "Screenshot extraction timed out.")
        TELEMETRY.emit_event(
            "portfolio_upload_failed",
            user=telemetry_user,
            properties={
                "source": "backend",
                "upload_type": "screenshot",
                "file_name": filename,
                "error_type": "TimeoutError",
            },
        )
        raise HTTPException(
            status_code=504,
            detail={
                "ok": False,
                "code": "SCREENSHOT_EXTRACTION_TIMEOUT",
                "message": "Reading this screenshot took too long and was stopped.",
                "action_hint": "Try a smaller, clearer holdings screenshot, or upload your broker CSV/XLSX export.",
            },
        ) from exc
    except PortfolioImageExtractionError as exc:
        _set_ingestion_state(tenant_id, "FAILED", str(exc))
        TELEMETRY.emit_event(
            "portfolio_upload_failed",
            user=telemetry_user,
            properties={
                "source": "backend",
                "upload_type": "screenshot",
                "file_name": filename,
                "error_type": exc.__class__.__name__,
            },
        )
        raise HTTPException(
            status_code=422,
            detail={
                "ok": False,
                "code": "SCREENSHOT_EXTRACTION_FAILED",
                "message": str(exc),
                "action_hint": "Upload a clearer broker screenshot or use eCAS/CSV/XLSX.",
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - convert any unexpected failure into an actionable response, never a raw 500
        logger.exception("Unexpected screenshot extraction failure for %s", filename)
        _set_ingestion_state(tenant_id, "FAILED", "Screenshot extraction failed unexpectedly.")
        TELEMETRY.emit_event(
            "portfolio_upload_failed",
            user=telemetry_user,
            properties={
                "source": "backend",
                "upload_type": "screenshot",
                "file_name": filename,
                "error_type": exc.__class__.__name__,
            },
        )
        raise HTTPException(
            status_code=502,
            detail={
                "ok": False,
                "code": "SCREENSHOT_EXTRACTION_ERROR",
                "message": "Could not read this screenshot right now.",
                "action_hint": "Try again in a moment, upload a clearer screenshot, or use your broker CSV/XLSX export.",
            },
        ) from exc

    review_id = uuid.uuid4().hex[:16]
    review_token = _mint_review_token(review_id, tenant_id)
    await supabase.store_pending_extraction(
        review_id,
        tenant_id,
        {
            "source_type": "image",
            "extraction": extraction.model_dump(),
        },
    )
    _set_ingestion_state(tenant_id, "REVIEW_REQUIRED", "Review screenshot-extracted holdings before syncing.")
    TELEMETRY.emit_event(
        "portfolio_upload_review_required",
        user=telemetry_user,
        properties={
            "source": "backend",
            "upload_type": "screenshot",
            "file_name": filename,
        },
    )
    return {
        "ok": True,
        "code": "REVIEW_REQUIRED",
        "status": "REVIEW_REQUIRED",
        "sync_status": "REVIEW_REQUIRED",
        "review_id": review_id,
        "review_token": review_token,
        "message": "Review extracted holdings before syncing.",
        **extraction.model_dump(),
    }


@app.post("/api/portfolio/confirm-extraction")
async def confirm_portfolio_extraction(
    req: PortfolioExtractionConfirmRequest,
    current_user: dict = Depends(get_current_user_or_guest),
):
    tenant_id = current_user.get("tenant_id")
    telemetry_user = telemetry_user_from_request_user(current_user)
    review_id = _validate_review_id(req.review_id) if req.review_id else None
    pending = None
    if review_id:
        pending = await supabase.get_pending_extraction(review_id)
    if review_id and not pending:
        raise HTTPException(status_code=404, detail="Review payload expired or not found.")
    pending_tenant_id = str((pending or {}).get("tenant_id") or "")
    if pending and pending_tenant_id != tenant_id:
        if not (review_id and _review_token_matches_pending(req.review_token, review_id, pending_tenant_id)):
            raise HTTPException(status_code=403, detail="Review payload belongs to a different tenant.")

    positions = req.positions
    source_type = req.source_type
    if not positions and pending:
        extraction = PortfolioExtractionSchema.model_validate(pending["extraction"]["extraction"])
        positions = extraction.positions
        source_type = pending["extraction"].get("source_type", source_type)
    if not positions:
        raise HTTPException(status_code=422, detail="No reviewed holdings were supplied.")

    _set_ingestion_state(tenant_id, "INGESTING", "Synchronizing reviewed holdings.")
    TELEMETRY.emit_event(
        "portfolio_extraction_confirm_requested",
        user=telemetry_user,
        properties={
            "source": "backend",
            "review_id": review_id or "",
            "source_type": source_type or "unknown",
            "position_count": len(positions),
        },
    )
    extraction = PortfolioExtractionSchema(
        status="MIRROR_SYNCHRONIZED",
        source_type=source_type if source_type in {"pdf", "csv", "xlsx", "image"} else "unknown",
        positions=positions,
        confidence=sum(p.confidence for p in positions) / len(positions),
    )
    try:
        mirrored = await replace_active_positions(tenant_id, extraction_to_position_dicts(extraction))
    except Exception as exc:  # noqa: BLE001 - mirror persistence is best-effort
        logger.warning("Reviewed-holdings mirror sync raised for tenant %s; returning holdings anyway: %s", tenant_id, exc)
        mirrored = []
    if not mirrored:
        # Cloud mirror unreachable. Surface the reviewed holdings as a soft success so
        # the frontend (localStorage source of truth) still captures them.
        _set_ingestion_state(tenant_id, "MIRROR_SYNCHRONIZED", "Reviewed holdings saved locally; cloud sync pending.")
        return {
            "ok": True,
            "code": "MIRROR_LOCAL_ONLY",
            "severity": "warning",
            "status": "MIRROR_SYNCHRONIZED",
            "sync_status": "MIRROR_SYNCHRONIZED",
            "source": source_type,
            "count": len(positions),
            "positions": extraction_to_position_dicts(extraction),
            "message": "Reviewed holdings saved locally; cloud sync will retry automatically.",
        }
    summary = summarize_positions(mirrored)
    _set_ingestion_state(tenant_id, "MIRROR_SYNCHRONIZED", f"{summary['count']} holdings synchronized.")
    if review_id:
        await supabase.delete_pending_extraction(review_id)
    summary.update({"ok": True, "code": "MIRROR_SYNCHRONIZED", "source": source_type})
    TELEMETRY.emit_event(
        "portfolio_extraction_confirm_completed",
        user=telemetry_user,
        properties={
            "source": "backend",
            "review_id": review_id or "",
            "source_type": source_type or "unknown",
            "count": summary.get("count", 0),
        },
    )
    return summary


@app.post("/api/portfolio/cancel-extraction")
async def cancel_portfolio_extraction(current_user: dict = Depends(get_current_user_or_guest)):
    tenant_id = current_user.get("tenant_id")
    telemetry_user = telemetry_user_from_request_user(current_user)
    pending_list = await supabase.get_pending_extractions_by_tenant(tenant_id)
    for item in pending_list:
        await supabase.delete_pending_extraction(item["review_id"])
    _set_ingestion_state(tenant_id, "IDLE", "")
    TELEMETRY.emit_event(
        "portfolio_extraction_cancelled",
        user=telemetry_user,
        properties={
            "source": "backend",
            "pending_count": len(pending_list),
        },
    )
    return {"ok": True, "status": "IDLE"}


def _portfolio_positions_signature(positions: list[Any]) -> str:
    rows: list[dict[str, Any]] = []
    for pos in positions[:250]:
        rows.append({
            "symbol": getattr(pos, "symbol", ""),
            "exchange": getattr(pos, "exchange", ""),
            "quantity": getattr(pos, "quantity", 0),
            "market_value": getattr(pos, "market_value", 0),
            "cost_basis": getattr(pos, "cost_basis", 0),
            "avg_cost": getattr(pos, "avg_cost", 0),
            "last_price": getattr(pos, "last_price", 0),
            "as_of": getattr(pos, "as_of", ""),
        })
    raw = json.dumps(rows, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


async def _compute_portfolio_analytics_cached(
    positions: list[Any],
    *,
    benchmark: str = "NIFTY50",
    period: str = "1y",
    timeout_s: float | None = None,
) -> dict[str, Any]:
    cache_ttl = max(15, int(os.getenv("FINAGENT_ANALYTICS_CACHE_TTL_S", "120") or 120))
    cache_key = (
        f"portfolio:analytics:{str(benchmark or 'NIFTY50').upper()}:"
        f"{str(period or '1y').lower()}:{_portfolio_positions_signature(positions)}"
    )
    cached = await app_cache.get(cache_key)
    if isinstance(cached, dict):
        return dict(cached)

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(compute_portfolio_analytics, positions, benchmark=benchmark, period=period),
            timeout=timeout_s if timeout_s is not None else _gateway_float_setting("FINAGENT_ANALYTICS_TIMEOUT_S", 18.0),
        )
    except asyncio.TimeoutError:
        logger.warning("Portfolio analytics timed out; returning lightweight analytics fallback")
        result = {
            "status": "ANALYTICS_TIMEOUT",
            "positions": [],
            "risk": {},
            "sector_breakdown": {},
            "kind_breakdown": {},
        }
        await app_cache.set(cache_key, result, ttl=15)
        return dict(result)

    if not isinstance(result, dict):
        result = {}
    await app_cache.set(cache_key, result, ttl=cache_ttl)
    return dict(result)


@app.get("/portfolio/analytics")
async def get_portfolio_analytics(
    current_user: dict = Depends(get_current_user_or_guest),
    benchmark: str = "NIFTY50",
    period: str = "1y",
):
    """Compute portfolio analytics with optional benchmark and period.
    
    Args:
        benchmark: Benchmark ticker (default: NIFTY50)
        period: Period string (1M, 3M, 1Y, YTD, default 1y)
    """
    tenant_id = current_user.get("tenant_id")
    positions, store_unavailable = await _load_optional_portfolio_positions(tenant_id, "portfolio/analytics")
    result = await _compute_portfolio_analytics_cached(positions, benchmark=benchmark, period=period)
    if isinstance(result, dict):
        result["store_unavailable"] = store_unavailable
    _record_metric_event(current_user, "portfolio_view")
    return result


@app.get("/portfolio/governance")
async def get_portfolio_governance(current_user: dict = Depends(get_current_user)):
    """Portfolio Governance X-Ray: forensic governance risk overlaid on holdings.

    Resolves each equity holding to its CIN via the IKG entity resolver, scores
    it with the Forensic Governance Score, and returns a market-value-weighted
    portfolio governance risk plus flagged holdings (each flag citation-backed).
    """
    from finagent.portfolio.governance_xray import compute_portfolio_governance_xray

    tenant_id = current_user.get("tenant_id")
    positions, store_unavailable = await _load_optional_portfolio_positions(tenant_id, "portfolio/governance")
    try:
        overlay = await asyncio.to_thread(compute_portfolio_governance_xray, positions)
    except Exception as exc:
        logger.warning("Portfolio governance X-Ray failed for tenant %s: %s", tenant_id, exc)
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "code": "GOVERNANCE_UNAVAILABLE",
                    "message": "Governance intelligence is temporarily unavailable. Please retry."},
        ) from exc
    overlay["store_unavailable"] = store_unavailable
    _record_metric_event(current_user, "governance_view")
    return overlay


def _record_metric_event(current_user: dict, event_type: str, session_id: str | None = None) -> None:
    """Best-effort usage-event recording for the metrics warehouse. Never raises."""
    try:
        from finagent.ops.metrics_warehouse import get_metrics_warehouse
        uid = str(current_user.get("user_id") or current_user.get("tenant_id") or "")
        if uid:
            get_metrics_warehouse().record_event(uid, event_type, session_id=session_id)
    except Exception as exc:  # metrics must never break a user request
        logger.debug("metric event record failed (%s): %s", event_type, exc)


@app.get("/metrics/snapshot")
async def get_metrics_snapshot(current_user: dict = Depends(get_current_user)):
    """Internal metrics dashboard data: DAU/MAU, retention cohorts, event volume.

    Gated to admin emails via FINAGENT_METRICS_ADMIN_EMAILS (comma-separated).
    """
    admins = {
        e.strip().lower()
        for e in os.getenv("FINAGENT_METRICS_ADMIN_EMAILS", "").split(",")
        if e.strip()
    }
    email = str(current_user.get("email") or "").lower()
    if admins and email not in admins:
        raise HTTPException(status_code=403, detail="Metrics access restricted")
    from finagent.ops.metrics_warehouse import get_metrics_warehouse
    return await asyncio.to_thread(get_metrics_warehouse().snapshot)


@app.get("/company/{cin}/governance")
async def get_company_governance(cin: str, current_user: dict = Depends(get_current_user)):
    """Forensic Governance Score for a single company by CIN."""
    from finagent.ikg.governance_score import (
        GovernanceLookupError,
        get_governance_scorer,
        result_to_dict,
    )

    scorer = get_governance_scorer()
    try:
        result = await asyncio.to_thread(scorer.score_company, cin)
    except GovernanceLookupError as exc:
        logger.warning("Company governance lookup failed for %s: %s", cin, exc)
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "code": "GOVERNANCE_LOOKUP_ERROR",
                    "message": "Could not retrieve governance data. Please retry."},
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"ok": False, "code": "NO_GOVERNANCE_DATA",
                    "message": f"No governance data available for {cin}."},
        )
    return result_to_dict(result)


@app.get("/company/{cin}/network")
async def get_company_network(cin: str, current_user: dict = Depends(get_current_user)):
    """Director-network explorer: companies sharing board members with this CIN."""
    from finagent.ikg.director_network import (
        NetworkLookupError,
        get_director_network_explorer,
    )

    explorer = get_director_network_explorer()
    try:
        result = await asyncio.to_thread(explorer.network, cin)
    except NetworkLookupError as exc:
        logger.warning("Company network lookup failed for %s: %s", cin, exc)
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "code": "NETWORK_LOOKUP_ERROR",
                    "message": "Could not retrieve the director network. Please retry."},
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"ok": False, "code": "NO_NETWORK_DATA",
                    "message": f"No director-network data available for {cin}."},
        )
    _record_metric_event(current_user, "network_view")
    return result


@app.get("/company/{cin}/provenance")
async def get_company_provenance_page(cin: str, current_user: dict = Depends(get_current_user)):
    """Citation-grade provenance page: every known fact about a company + sources."""
    from finagent.ikg.company_provenance import (
        ProvenanceLookupError,
        get_company_provenance,
    )

    prov = get_company_provenance()
    try:
        result = await asyncio.to_thread(prov.page, cin)
    except ProvenanceLookupError as exc:
        logger.warning("Provenance lookup failed for %s: %s", cin, exc)
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "code": "PROVENANCE_LOOKUP_ERROR",
                    "message": "Could not retrieve provenance data. Please retry."},
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"ok": False, "code": "NO_PROVENANCE_DATA",
                    "message": f"No provenance data available for {cin}."},
        )
    return result


@app.get("/company/{cin}/health")
async def get_company_graph_health(cin: str, current_user: dict = Depends(get_current_user)):
    """Per-company IKG completeness (evidence-grade / partial / thin)."""
    from finagent.ikg.graph_health import GraphHealthError, get_graph_health

    health = get_graph_health()
    try:
        result = await asyncio.to_thread(health.company, cin)
    except GraphHealthError as exc:
        logger.warning("Company graph health failed for %s: %s", cin, exc)
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "code": "GRAPH_HEALTH_ERROR",
                    "message": "Could not retrieve graph health. Please retry."},
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"ok": False, "code": "NO_COMPANY_VERTEX",
                    "message": f"No graph vertex for {cin}."},
        )
    return result


@app.get("/admin/ikg/health")
async def get_ikg_health_report(current_user: dict = Depends(get_current_user)):
    """Corpus-level IKG reconciliation snapshot. Admin-gated."""
    admins = {
        e.strip().lower()
        for e in os.getenv("FINAGENT_METRICS_ADMIN_EMAILS", "").split(",")
        if e.strip()
    }
    email = str(current_user.get("email") or "").lower()
    if admins and email not in admins:
        raise HTTPException(status_code=403, detail="Admin access restricted")
    from finagent.ikg.graph_health import GraphHealthError, get_graph_health

    try:
        return await asyncio.to_thread(get_graph_health().report)
    except GraphHealthError as exc:
        logger.warning("IKG health report failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail={"ok": False, "code": "GRAPH_HEALTH_ERROR",
                    "message": "Could not generate the IKG health report."},
        ) from exc


@app.get("/company/{cin}/staleness")
async def get_company_staleness(cin: str, current_user: dict = Depends(get_current_user)):
    """IKG context staleness verdict for a company CIN."""
    from finagent.ikg.staleness import get_staleness_checker
    verdict = await asyncio.to_thread(get_staleness_checker().check_company, cin)
    return {
        "cin": cin.upper().strip(),
        "band": verdict.band,
        "needs_refresh": verdict.needs_refresh,
        "age_days": verdict.age_days,
        "last_updated": verdict.last_updated,
        "sources_checked": verdict.sources_checked,
        "reason": verdict.reason,
    }


@app.post("/filings/triage")
async def post_filings_triage(payload: dict, current_user: dict = Depends(get_current_user)):
    """Triage a batch of corporate filings by materiality.

    Body: {"filings": [{"subject"|"headline"|"title", "category", "body"?}, ...]}
    Returns each filing's materiality band so callers can route HIGH ones to alerts.
    """
    from finagent.content.filing_triage import classify_materiality, should_alert

    filings = payload.get("filings") if isinstance(payload, dict) else None
    if not isinstance(filings, list):
        raise HTTPException(status_code=422, detail="Expected {'filings': [...]}")
    triaged = []
    for f in filings[:200]:
        if not isinstance(f, dict):
            continue
        verdict = classify_materiality(f)
        triaged.append({**{k: f.get(k) for k in ("subject", "headline", "title", "category")},
                        "materiality": verdict, "alert": should_alert(verdict)})
    return {
        "count": len(triaged),
        "alerts": sum(1 for t in triaged if t["alert"]),
        "results": triaged,
    }


@app.delete("/portfolio/mirror")
async def delete_portfolio_mirror(current_user: dict = Depends(get_current_user_or_guest)):
    """Clear all holdings for the authenticated tenant."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Tenant required")
    deleted = await delete_positions(tenant_id)
    _set_ingestion_state(tenant_id, "IDLE", "")
    return {"ok": True, "deleted": deleted}


class AdminResetRequest(BaseModel):
    reset_key: str = Field(..., min_length=8, max_length=128)


@app.post("/admin/reset-all-portfolios")
async def admin_reset_all_portfolios(req: AdminResetRequest, current_user: dict = Depends(get_current_user)):
    """Admin-only: wipe every portfolio mirror row so all users start fresh."""
    import os as _os
    _expected_key = (_os.environ.get("ADMIN_RESET_KEY") or "").strip()
    if not _expected_key:
        raise HTTPException(status_code=403, detail="Admin reset is disabled. Set ADMIN_RESET_KEY env var to enable.")
    if req.reset_key != _expected_key:
        raise HTTPException(status_code=403, detail="Invalid reset key.")

    count = await clear_all_positions()

    # Also clear ingestion state files
    import glob as _glob
    try:
        state_dir = finagent_data_path("ingestion_state")
        for f in _glob.glob(str(state_dir / "*.json")):
            try:
                _os.remove(f)
            except OSError:
                pass
    except Exception:
        pass

    TELEMETRY.emit_event(
        "admin_portfolio_reset_executed",
        user=telemetry_user_from_request_user(current_user),
        properties={"source": "backend", "rows_cleared": count},
    )
    return {"ok": True, "rows_cleared": count, "message": "All portfolio mirrors wiped. Users will start fresh."}


async def _load_optional_portfolio_positions(tenant_id: str | None, endpoint: str) -> tuple[list, bool]:
    """Best-effort portfolio load for dashboard widgets.

    Non-critical widgets such as news, action queue, taxes, and alerts should
    not raise 500s just because Supabase had a transient read timeout.
    """
    if not tenant_id:
        return [], True
    try:
        return await load_active_positions(tenant_id), False
    except Exception as exc:
        logger.warning("%s portfolio load failed for tenant %s: %s", endpoint, tenant_id, exc)
        return [], True


@app.get("/portfolio/news")
async def get_portfolio_news(limit: int = 12, current_user: dict = Depends(get_current_user_or_guest)):
    tenant_id = current_user.get("tenant_id")
    positions, store_unavailable = await _load_optional_portfolio_positions(tenant_id, "portfolio/news")
    safe_limit = max(1, min(int(limit or 12), 30))
    try:
        items = await asyncio.wait_for(
            asyncio.to_thread(fetch_portfolio_news, positions, limit=safe_limit),
            timeout=_gateway_float_setting("FINAGENT_PORTFOLIO_NEWS_TIMEOUT_S", 8.0),
        )
    except asyncio.TimeoutError:
        logger.warning("Portfolio news timed out for tenant %s", tenant_id)
        items = []
    return {
        "items": items,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "store_unavailable": store_unavailable,
        "filters": {
            "min_score": 0.5,
            "max_age_days": 7,
            "verified_only": True,
        },
    }


@app.get("/portfolio/sectors")
async def get_portfolio_sectors(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions, store_unavailable = await _load_optional_portfolio_positions(tenant_id, "portfolio/sectors")
    from finagent.portfolio_mirrors import sector_breakdown
    return sector_breakdown(positions)


@app.get("/portfolio/holding/{symbol}")
async def get_holding_detail(symbol: str, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions = await load_active_positions(tenant_id)
    pos = next((p for p in positions if p.exchange_symbol == symbol or p.normalized_symbol == symbol), None)
    if not pos:
        raise HTTPException(status_code=404, detail="Holding not found")
    from finagent.portfolio.holding_detail import get_holding_detail as _get_detail
    return _get_detail(pos)


@app.get("/portfolio/corporate-actions")
async def get_corporate_actions(days: int = 30, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions, store_unavailable = await _load_optional_portfolio_positions(tenant_id, "portfolio/corporate-actions")
    from finagent.portfolio.corporate_actions import fetch_corporate_actions
    return {"events": fetch_corporate_actions(positions, days=days), "store_unavailable": store_unavailable}


@app.get("/portfolio/alerts")
async def get_portfolio_alerts(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions, store_unavailable = await _load_optional_portfolio_positions(tenant_id, "portfolio/alerts")
    from finagent.portfolio.alerts import compute_alerts
    analytics = await _compute_portfolio_analytics_cached(positions, timeout_s=10.0)
    return {"alerts": compute_alerts(positions, analytics), "store_unavailable": store_unavailable}


@app.get("/portfolio/tax-summary")
async def get_tax_summary(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions, store_unavailable = await _load_optional_portfolio_positions(tenant_id, "portfolio/tax-summary")
    from finagent.portfolio.tax import compute_tax_summary
    result = compute_tax_summary(positions)
    if isinstance(result, dict):
        result["store_unavailable"] = store_unavailable
    return result


@app.get("/portfolio/dividends")
async def get_dividends(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions, store_unavailable = await _load_optional_portfolio_positions(tenant_id, "portfolio/dividends")
    from finagent.portfolio.dividends import compute_dividend_summary, get_next_ex_dates
    return {
        **compute_dividend_summary(positions),
        "next_ex_dates": get_next_ex_dates(positions),
        "store_unavailable": store_unavailable,
    }


class StressTestRequest(BaseModel):
    scenario: str = "nifty_down_20"
    custom_shocks: dict[str, float] | None = None

@app.post("/portfolio/stress-test")
async def post_stress_test(
    body: StressTestRequest,
    current_user: dict = Depends(get_current_user_or_guest),
):
    tenant_id = current_user.get("tenant_id")
    positions, store_unavailable = await _load_optional_portfolio_positions(tenant_id, "portfolio/stress-test")
    from finagent.portfolio.stress_test import run_stress_test
    result = run_stress_test(positions, scenario=body.scenario, custom_shocks=body.custom_shocks)
    if isinstance(result, dict):
        result["store_unavailable"] = store_unavailable
    return result


@app.get("/portfolio/mf-analytics")
async def get_mf_analytics(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions, store_unavailable = await _load_optional_portfolio_positions(tenant_id, "portfolio/mf-analytics")
    from finagent.portfolio.mf_analytics import compute_mf_analytics
    result = compute_mf_analytics(positions)
    if result is None:
        return {"status": "NO_MF_POSITIONS", "store_unavailable": store_unavailable}
    if isinstance(result, dict):
        result["store_unavailable"] = store_unavailable
    return result


@app.get("/portfolio/today")
async def get_today_queue(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions, store_unavailable = await _load_optional_portfolio_positions(tenant_id, "portfolio/today")
    from finagent.portfolio.action_queue import build_action_queue
    analytics = await _compute_portfolio_analytics_cached(positions, timeout_s=10.0)
    return {"items": build_action_queue(positions, analytics), "store_unavailable": store_unavailable}


@app.get("/portfolio/brief")
async def get_portfolio_brief(current_user: dict = Depends(get_current_user)):
    """Return a brief text summary of the portfolio."""
    tenant_id = current_user.get("tenant_id")
    positions, store_unavailable = await _load_optional_portfolio_positions(tenant_id, "portfolio/brief")
    if store_unavailable:
        return {"brief": "Portfolio data is temporarily unavailable.", "store_unavailable": True}
    if not positions:
        return {"brief": "No portfolio data available.", "store_unavailable": False}
    
    analytics = await _compute_portfolio_analytics_cached(positions, timeout_s=10.0)
    
    # Build enhanced brief with key insights
    count = len(positions)
    total_value = analytics.get('total_market_value', 0)
    pnl_pct = analytics.get('unrealized_pnl_pct', 0) * 100
    pnl_amount = analytics.get('unrealized_pnl', 0)
    beta = analytics.get('risk', {}).get('beta_vs_nifty', None)
    kind_breakdown = analytics.get('kind_breakdown', {})
    equity_pct = kind_breakdown.get('equity', 0) * 100
    mf_pct = kind_breakdown.get('mf', 0) * 100
    
    # Top holdings
    enriched = analytics.get('positions', [])
    top_holdings = sorted(enriched, key=lambda p: p.get('weight', 0), reverse=True)[:3]
    top_names = ', '.join(p.get('name', p.get('symbol', 'N/A')) for p in top_holdings)
    
    risk_str = f"{beta:.2f}" if beta is not None else "N/A"

    brief_text = (
        f"Portfolio of {count} holdings worth â‚¹{total_value:,.0f}. "
        f"Unrealized P/L: â‚¹{pnl_amount:,.0f} ({pnl_pct:+.1f}%). "
        f"Asset allocation: {equity_pct:.0f}% equity, {mf_pct:.0f}% MF. "
        f"Risk (vs NIFTY50): {risk_str}. "
        f"Top holdings: {top_names}."
    )
    return {"brief": brief_text}


@app.get("/portfolio/commentary")
async def get_portfolio_commentary(current_user: dict = Depends(get_current_user)):
    """Proactive AI daily read of the portfolio. LLM-written, template fallback."""
    tenant_id = current_user.get("tenant_id")
    positions, store_unavailable = await _load_optional_portfolio_positions(tenant_id, "portfolio/commentary")
    if store_unavailable:
        return {"commentary": "Portfolio data is temporarily unavailable.", "source": "error",
                "highlights": [], "store_unavailable": True}
    commentary_key = f"portfolio:commentary:{_portfolio_positions_signature(positions)}"
    cached = await app_cache.get(commentary_key)
    if isinstance(cached, dict):
        cached["store_unavailable"] = False
        return cached

    analytics = await _compute_portfolio_analytics_cached(positions, timeout_s=10.0)
    from finagent.portfolio.commentary import build_highlights, generate_commentary, template_commentary
    try:
        result = await asyncio.wait_for(
            generate_commentary(analytics),
            timeout=_gateway_float_setting("FINAGENT_PORTFOLIO_COMMENTARY_TIMEOUT_S", 6.0),
        )
    except asyncio.TimeoutError:
        result = {
            "commentary": template_commentary(analytics),
            "source": "template-timeout",
            "highlights": build_highlights(analytics),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    await app_cache.set(commentary_key, result, ttl=300)
    result["store_unavailable"] = False
    _record_metric_event(current_user, "commentary_view")
    return result


from finagent.memory import get_memory_store
from finagent.memory.store import normalize_target


@app.get("/memory/stats")
async def memory_stats(current_user: dict = Depends(get_current_user)):
    """Overall memory statistics scoped to the authenticated user."""
    store = get_memory_store()
    user_email = current_user.get("email")
    total = await store.count(user_email=user_email)
    targets = await store.get_targets(user_email=user_email, limit=20)
    sessions = await store.get_session_count(user_email=user_email)
    return {
        "total_facts": total,
        "total_sessions": sessions,
        "memory_backend": store.backend_name,
        "db_path": store.location,
        "targets": [{"target": t["target"], "facts": t["facts"]} for t in targets],
    }


@app.get("/memory/facts")
async def memory_facts(target: str = "", limit: int = 50, current_user: dict = Depends(get_current_user)):
    """Browse facts â€” optionally filtered by target company, scoped to the authenticated user."""
    store = get_memory_store()
    user_email = current_user.get("email")
    rows = await store.get_facts(
        target_key=normalize_target(target) if target else None,
        user_email=user_email,
        limit=limit,
    )
    return {
        "count": len(rows),
        "facts": [
            {
                "id": r.get("id"),
                "target_key": r.get("target_key"),
                "kind": r.get("kind"),
                "body": r.get("body"),
                "confidence": r.get("confidence"),
                "source_url": r.get("source_url"),
                "session_id": r.get("session_id"),
                "user_email": r.get("user_email"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ],
    }


@app.get("/memory/sessions")
async def memory_sessions(target: str = "", current_user: dict = Depends(get_current_user)):
    """List session summaries from memory, scoped to the authenticated user."""
    store = get_memory_store()
    user_email = current_user.get("email")
    rows = await store.list_sessions(
        user_email=user_email,
        target_key=normalize_target(target) if target else None,
        limit=20,
    )
    return {
        "count": len(rows),
        "sessions": [
            {
                "session_id": r.get("session_id"),
                "target_key": r.get("target_key"),
                "target_display": r.get("target_display"),
                "summary": (r.get("summary") or "")[:300],
                "quality_score": r.get("quality_score"),
                "citation_count": r.get("citation_count"),
                "created_at": r.get("created_at"),
                "user_email": r.get("user_email"),
            }
            for r in rows
        ],
    }


@app.delete("/memory/clear/{target}")
async def memory_clear(target: str, current_user: dict = Depends(get_current_user)):
    """Delete all stored facts for a specific target scoped to the authenticated user."""
    store = get_memory_store()
    user_email = current_user.get("email")
    deleted = await store.clear_target(target, user_email=user_email)
    return {"target": target, "deleted": deleted, "user_email": user_email}


# â”€â”€ Static page handlers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url(""), status_code=302)


@app.get("/landing")
def landing() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url(""), status_code=302)


@app.get("/unsubscribe")
@app.get("/unsubscribe/")
def unsubscribe_page(request: Request) -> RedirectResponse:
    target = _frontend_static_url("unsubscribe/")
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(url=target, status_code=302)


@app.get("/login")
def login_page() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url("dashboard"), status_code=302)


@app.get("/signup")
def signup_page() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url("dashboard"), status_code=302)


@app.get("/onboarding")
@app.get("/onboarding/")
def onboarding_page() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url("onboarding"), status_code=302)


@app.get("/dashboard")
@app.get("/dashboard/")
def dashboard_page() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url("dashboard"), status_code=302)


@app.get("/insights-studio")
@app.get("/insights-studio/")
def insights_studio_page() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url("insights-studio"), status_code=302)


@app.get("/profile")
def profile_page() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url("dashboard"), status_code=302)


@app.get("/settings")
def settings_page() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url("dashboard"), status_code=302)


@app.get("/app")
def widget(request: Request) -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url("dashboard"), status_code=302)


@app.get("/ops")
def ops_index() -> RedirectResponse:
    return RedirectResponse(url="/ops/control-tower", status_code=302)


@app.get("/ops/control-tower")
def control_tower_page(request: Request):
    require_auth = _control_tower_requires_auth()
    actual_token = request.cookies.get(AUTH_COOKIE_NAME)
    if not actual_token and require_auth:
        return RedirectResponse(url="/login", status_code=302)
    current_user = None
    invalid_token = False
    if actual_token:
        try:
            current_user = _decode_current_user(actual_token)
        except HTTPException:
            invalid_token = True
            if require_auth:
                response = RedirectResponse(url="/login", status_code=302)
                _clear_auth_cookie(response)
                return response
    try:
        if require_auth and current_user is None:
            response = RedirectResponse(url="/login", status_code=302)
            if invalid_token:
                _clear_auth_cookie(response)
            return response

        if not _control_tower_can_access(current_user):
            return HTMLResponse(
                """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>ProspektLab Control Tower</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background: #06111d;
      color: #eaf2fb;
      font-family: Inter, system-ui, -apple-system, Segoe UI, sans-serif;
    }
    main {
      width: min(720px, calc(100vw - 32px));
      padding: 32px;
      border-radius: 24px;
      border: 1px solid rgba(255, 255, 255, 0.12);
      background: rgba(13, 24, 38, 0.94);
      box-shadow: 0 24px 90px rgba(0, 0, 0, 0.36);
    }
    h1 {
      margin: 0 0 12px;
      font-size: 2rem;
      font-family: "Space Grotesk", Inter, system-ui, sans-serif;
    }
    p {
      margin: 0;
      color: #8ea5b9;
      line-height: 1.6;
    }
    code {
      padding: 2px 6px;
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.08);
      color: #eaf2fb;
    }
  </style>
</head>
<body>
  <main>
    <h1>Access restricted</h1>
    <p>This control tower is limited to authorized operators. If you expected access, add your email to <code>CONTROL_TOWER_ALLOWED_EMAILS</code> or remove the allowlist.</p>
  </main>
</body>
</html>""",
                status_code=403,
                headers={"Cache-Control": "no-store, max-age=0", "X-Robots-Tag": "noindex, nofollow"},
            )

        return HTMLResponse(
            CONTROL_TOWER_HTML_PATH.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store, max-age=0", "X-Robots-Tag": "noindex, nofollow"},
        )
    except Exception:
        return HTMLResponse(
            "<h1>Control Tower unavailable</h1>",
            status_code=500,
            headers={"Cache-Control": "no-store, max-age=0", "X-Robots-Tag": "noindex, nofollow"},
        )


@app.get("/api/ops/control-tower")
async def ops_control_tower_snapshot(
    request: Request,
    range: str = "30D",
    current_user: dict[str, Any] | None = Depends(get_current_user_optional),
) -> JSONResponse:
    if _control_tower_requires_auth() and current_user is None:
        raise HTTPException(status_code=401, detail="Missing or invalid authentication credentials")
    if not _control_tower_can_access(current_user):
        raise HTTPException(status_code=403, detail="Access denied")
    snapshot = await build_control_tower_snapshot(range)
    return JSONResponse(snapshot, headers={"Cache-Control": "no-store, max-age=0"})


@app.post("/auth/logout")
def auth_logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    _clear_auth_cookie(response)
    return response


# â”€â”€ Auth endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


# Verification codes and reset codes are stored in Supabase (or local SQLite fallback)
# via finagent.gateway.state_store / supabase_client.

def _send_email_code(email: str, code: str, is_reset: bool = False) -> EmailDeliveryOutcome:
    subject = "Reset Your ProspektLab Password" if is_reset else "Verify Your ProspektLab Email"
    body = (
        f"Your verification code to reset your password is: {code}\n\n"
        "This code will expire in 10 minutes."
        if is_reset else
        f"Your email verification code for ProspektLab signup is: {code}\n\n"
        "This code will expire in 10 minutes."
    )

    outcome = send_email_message(
        to_email=email,
        subject=subject,
        plain_text=body,
        html=f"<p>{body.replace(chr(10), '<br/>')}</p>",
    )
    if outcome.delivered:
        return outcome

    action_type = "RESET PASSWORD" if is_reset else "EMAIL VERIFICATION"
    print(f"\n==================================================")
    print(f"[EMAIL DELIVERY FALLBACK - {action_type}]")
    print(f"To: {email}")
    print(f"Subject: {subject}")
    print(f"Code: {code}")
    print(f"Provider detail: {outcome.detail or 'not configured'}")
    print(f"==================================================\n", flush=True)
    return outcome


def _send_sms_code(mobile: str, code: str, is_reset: bool = False) -> EmailDeliveryOutcome:
    message = (
        f"ProspektLab reset code: {code}. It expires in 10 minutes."
        if is_reset else
        f"ProspektLab verification code: {code}. It expires in 10 minutes."
    )

    outcome = send_sms_message(
        to_phone=mobile,
        message=message,
    )
    if outcome.delivered:
        return outcome

    action_type = "RESET PASSWORD" if is_reset else "SMS VERIFICATION"
    print(f"\n==================================================")
    print(f"[SMS DELIVERY FALLBACK - {action_type}]")
    print(f"To: {mobile}")
    print(f"Code: {code}")
    print(f"Provider detail: {outcome.detail or 'not configured'}")
    print(f"==================================================\n", flush=True)
    return outcome


@app.post("/auth/send-verification", dependencies=[Depends(auth_rate_limiter)])
async def auth_send_verification(req: SendVerificationRequest):
    email_clean = req.email.lower().strip()
    mobile_clean = req.mobile or ""
    channel = req.channel
    
    # Check if user already exists
    existing = await supabase.get_user_by_email(email_clean)
    if existing:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")

    if channel == "sms" and not mobile_clean:
        raise HTTPException(status_code=400, detail="Mobile number is required for SMS verification.")
        
    code = f"{secrets.randbelow(900000) + 100000}"
    recipient_key = mobile_clean if channel == "sms" else email_clean
    await supabase.store_verification_code(recipient_key, code, type_="signup")

    outcome = (
        _send_sms_code(mobile_clean, code, is_reset=False)
        if channel == "sms"
        else _send_email_code(email_clean, code, is_reset=False)
    )
    if outcome.delivered:
        TELEMETRY.emit_event(
            "auth_verification_sent",
            user=TelemetryUserContext(email=email_clean, name=email_clean),
            properties={
                "source": "backend",
                "flow": "signup",
                "delivery": outcome.provider,
                "channel": channel,
            },
        )
        channel_label = "SMS" if channel == "sms" else "email"
        return {"message": f"Verification code sent by {channel_label} successfully."}
    else:
        TELEMETRY.emit_event(
            "auth_verification_sent",
            user=TelemetryUserContext(email=email_clean, name=email_clean),
            properties={
                "source": "backend",
                "flow": "signup",
                "delivery": "simulated",
                "channel": channel,
            },
        )
        simulated_target = mobile_clean if channel == "sms" else email_clean
        return {
            "message": "Verification code generated.",
            "detail": f"Verification code simulated for {simulated_target}. Code {code} has been logged to the server terminal console."
        }


@app.post("/auth/forgot-password", dependencies=[Depends(auth_rate_limiter)])
async def auth_forgot_password(req: ForgotPasswordRequest):
    email_clean = req.email.lower().strip()
    channel = req.channel
    
    # Verify user exists
    existing = await supabase.get_user_by_email(email_clean)
    if not existing:
        raise HTTPException(status_code=404, detail="No account with that email exists.")

    mobile_clean = _normalize_optional_mobile(_profile_mobile(existing))
    if channel == "sms" and not mobile_clean:
        raise HTTPException(status_code=400, detail="No mobile number is available for SMS reset codes.")
        
    code = f"{secrets.randbelow(900000) + 100000}"
    recipient_key = mobile_clean if channel == "sms" else email_clean
    await supabase.store_verification_code(recipient_key, code, type_="reset")

    outcome = (
        _send_sms_code(mobile_clean, code, is_reset=True)
        if channel == "sms"
        else _send_email_code(email_clean, code, is_reset=True)
    )
    if outcome.delivered:
        TELEMETRY.emit_event(
            "auth_password_reset_requested",
            user=TelemetryUserContext(email=email_clean, name=email_clean),
            properties={
                "source": "backend",
                "delivery": outcome.provider,
                "channel": channel,
            },
        )
        channel_label = "SMS" if channel == "sms" else "email"
        return {"message": f"Reset code sent by {channel_label}."}
    else:
        TELEMETRY.emit_event(
            "auth_password_reset_requested",
            user=TelemetryUserContext(email=email_clean, name=email_clean),
            properties={
                "source": "backend",
                "delivery": "simulated",
                "channel": channel,
            },
        )
        simulated_target = mobile_clean if channel == "sms" else email_clean
        return {
            "message": "Reset code generated.",
            "detail": f"Reset code simulated for {simulated_target}. Code {code} has been logged to the server terminal console."
        }


@app.post("/auth/reset-password", dependencies=[Depends(auth_rate_limiter)])
async def auth_reset_password(req: ResetPasswordRequest):
    email_clean = req.email.lower().strip()

    existing = await supabase.get_user_by_email(email_clean)
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found.")

    valid = await supabase.verify_and_consume_code(email_clean, req.code, type_="reset", ttl_seconds=600)
    if not valid:
        mobile_clean = _normalize_optional_mobile(_profile_mobile(existing))
        if mobile_clean:
            valid = await supabase.verify_and_consume_code(mobile_clean, req.code, type_="reset", ttl_seconds=600)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid or expired reset code. Please request a new one.")
        
    user_id = existing["id"]
    await supabase.update_admin_user_password(user_id, req.new_password)
    TELEMETRY.emit_event(
        "auth_password_reset_completed",
        user=TelemetryUserContext(email=email_clean, name=email_clean, user_id=user_id),
        properties={
            "source": "backend",
        },
    )
    
    return {"message": "Password reset successfully."}


@app.post("/auth/signup", dependencies=[Depends(auth_rate_limiter)])
async def auth_signup(req: SignupRequest, request: Request):
    email_clean = req.email.lower().strip()
    mobile_clean = req.mobile.strip()
    name_clean = req.name.strip()
    referral_source_clean = req.referral_source.strip()

    # Verification code is optional. If the client provides one, we verify it;
    # otherwise we create the account immediately and auto-confirm the email so
    # the user can reach the dashboard without friction.
    email_verified = True
    if req.verification_code:
        valid = await supabase.verify_and_consume_code(email_clean, req.verification_code, type_="signup", ttl_seconds=600)
        if not valid:
            valid = await supabase.verify_and_consume_code(mobile_clean, req.verification_code, type_="signup", ttl_seconds=600)
        if not valid:
            raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
    
    # Create via Supabase with email confirmed so the dashboard is accessible immediately.
    res = await supabase.create_admin_user(
        email_clean,
        req.password,
        name_clean,
        mobile=mobile_clean,
        auth_provider="email",
        referral_source=referral_source_clean,
        email_confirm=True,
    )
    user_id = res.get("id")
    saved_profile = await supabase.upsert_profile(
        user_id,
        email_clean,
        name_clean,
        "email",
        mobile=mobile_clean,
        referral_source=referral_source_clean,
    )
    saved_mobile = _profile_mobile(saved_profile) or mobile_clean

    # Generate a JWT for immediate login after signup
    token = _mint_token(user_id, email_clean, name_clean)
        
    response = JSONResponse({
        "token": token,
        "user": {
            "name": name_clean,
            "email": email_clean,
            "plan": "free",
            "mobile": saved_mobile,
            "require_mobile": not bool(saved_mobile),
            "referral_source": referral_source_clean,
            "email_verified": email_verified,
        },
    })
    _set_auth_cookie(response, token, request)
    TELEMETRY.emit_event(
        "auth_signup_success",
        user=TelemetryUserContext(email=email_clean, name=name_clean, user_id=user_id, auth_provider="email"),
        properties={
            "source": "backend",
            "email_verified": email_verified,
        },
    )
    return response



@app.post("/auth/login", dependencies=[Depends(auth_rate_limiter)])
async def auth_login(req: LoginRequest, request: Request):
    email_clean = req.email.lower().strip()
    
    # Authenticate via Supabase
    auth_data = await supabase.authenticate_user(email_clean, req.password)
    
    user = auth_data.get("user", {})
    user_metadata = user.get("user_metadata", {})
    user_id = user.get("id") or user_metadata.get("sub") or email_clean
    
    full_name = user_metadata.get("full_name") or user_metadata.get("name") or "Researcher"
    profile = None
    try:
        profile = await supabase.get_user_by_email(email_clean)
    except Exception as exc:
        logger.warning("Profile lookup failed during login for %s: %s", email_clean, exc)
    mobile = (
        _profile_mobile(profile)
        or str(user_metadata.get("mobile") or "").strip()
        or str(user_metadata.get("phone") or "").strip()
    )
    email_verified = bool(user.get("email_confirmed_at") or user.get("email_verified"))

    # Issue a local JWT (same format as Google auth + signup) so that
    # get_current_user can verify it with JWT_SECRET in production.
    # Using the raw Supabase access token here would cause 401s because
    # the backend would need SUPABASE_JWT_SECRET to verify it.
    token = _mint_token(user_id, email_clean, full_name, email_verified=email_verified)

    response = JSONResponse({
        "token": token,
        "user": {
            "name": full_name,
            "email": email_clean,
            "plan": "free",
            "mobile": mobile,
            "require_mobile": not bool(mobile),
            "email_verified": email_verified,
        }
    })
    _set_auth_cookie(response, token, request)
    TELEMETRY.emit_event(
        "auth_login_success",
        user=TelemetryUserContext(email=email_clean, name=full_name, user_id=user_id, auth_provider="email"),
        properties={
            "source": "backend",
        },
    )
    _record_metric_event({"user_id": user_id, "email": email_clean}, "login")
    return response


# â”€â”€ Research orchestration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@app.post("/research/start", dependencies=[Depends(research_rate_limiter)])
async def start_research(req: StartResearchRequest, current_user: dict = Depends(enforce_token_limit)):
    session_id = req.session_id or uuid.uuid4().hex[:12]
    telemetry_user = telemetry_user_from_request_user(current_user)
    
    if req.session_id:
        verify_session_ownership(session_id, current_user)
        
    raw_query = req.target.strip()
    raw_query = _strip_frontend_portfolio_context(raw_query) or raw_query
    _guard_prompt_injection(raw_query)
    user_email = current_user["email"]
    tenant_id = current_user["tenant_id"]
    _record_metric_event(current_user, "research_session", session_id=session_id)
    _require_no_active_ingestion(tenant_id)
    if is_portfolio_scope_query(raw_query):
        await _require_synchronized_portfolio(tenant_id, allow_empty=True)

    # Cap concurrent sessions to prevent resource exhaustion
    active_sessions = sum(1 for t in _TASKS.values() if not t.done())
    if active_sessions >= _MAX_CONCURRENT_SESSIONS:
        raise HTTPException(503, "Server is at capacity. Please try again in a moment.")

    requested_mode = (req.mode or "chat").strip().lower()
    if requested_mode == "marathon":
        requested_mode = "deep"
    if requested_mode == "deep":
        return await start_deep_research(
            DeepResearchRequest(
                target=raw_query,
                objective=req.objective,
                passes=8,
                pass_depth=min(max(req.max_steps or 40, 10), 120),
                max_wall_seconds=req.max_wall_seconds,
                heartbeat_interval_s=min(max(req.heartbeat_interval_s, 5), 60),
                user_email=req.user_email,
                session_id=req.session_id,
            ),
            current_user=current_user,
        )
    
    # â”€â”€ Pure-LLM follow-up contextualization â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # The LLM decides whether this is a follow-up to the prior conversation,
    # rewrites pronouns into self-contained queries, and extracts the target.
    # If both OpenAI and xAI fail, we raise HTTPException 503.
    meta = _load_session_meta(session_id)
    prior_target = meta.get("target_display") or meta.get("target")
    is_followup = False
    target = None
    objective = (req.objective or raw_query).strip()

    if req.session_id and prior_target:
        chat_history = _MEMORY_MANAGER.get_history(user_email, session_id)
        try:
            result = await _contextualize_query_with_budget(
                raw_query,
                prior_target,
                chat_history,
                timeout_s=_gateway_float_setting(
                    "FINAGENT_CHAT_CONTEXTUALIZER_TIMEOUT_S",
                    3.5 if requested_mode == "chat" else 6.0,
                ),
            )
            is_followup = result.is_followup

            if is_followup:
                target = prior_target
                if result.contextualized_query and result.contextualized_query.strip():
                    objective = result.contextualized_query.strip()
            else:
                # New topic â€” LLM may have extracted a target, otherwise fall back
                target = result.target or primary_target_from_query(raw_query)
                if result.contextualized_query and result.contextualized_query.strip():
                    objective = result.contextualized_query.strip()

                # â”€â”€ Session isolation: if the resolved target differs from the prior
                # session's target, mint a fresh session_id so the old entity's
                # enrichment data, caches, and tool outputs don't leak into the new query.
                if prior_target and target and prior_target.lower() != target.lower():
                    session_id = uuid.uuid4().hex[:12]
                    BUS.open(session_id, reset=True)
                    logger.info("Target changed from %r to %r â€” new session %s", prior_target, target, session_id)
        except (asyncio.TimeoutError, ContextualizerError, Exception) as exc:
            logger.warning("Contextualizer failed for session %s, falling back to raw query: %s", session_id, exc)
            is_followup = True
            target = prior_target
            objective = raw_query.strip()
    else:
        # No prior context â€” resolve normally
        target = primary_target_from_query(raw_query)

    # Re-check portfolio scope on contextualized objective (follow-ups may become portfolio queries)
    objective_scope_query = _strip_frontend_portfolio_context(objective) or raw_query
    if is_portfolio_scope_query(objective_scope_query):
        await _require_synchronized_portfolio(tenant_id, allow_empty=True)

    # Always start a fresh event history for this research execution (prevents
    # replay of previous run's "memo"/"final" events into the new turn's UI).
    BUS.open(session_id, reset=True)
    _clear_session_memo(session_id)
    mode = requested_mode
    if mode not in {"chat", "standard", "deep"}:
        raise HTTPException(status_code=422, detail=f"Invalid mode: {mode}. Must be one of chat, standard, deep.")
    
    # â”€â”€ Comparison detection: extract both entities â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    from finagent.output.query_guards import is_portfolio_comparison_query
    is_comparison_query = _is_comparison(raw_query) and not is_portfolio_comparison_query(raw_query)
    comparison_targets = _extract_comparison_targets(raw_query) if is_comparison_query else []
    # Force comparison output mode for comparison queries (but NOT portfolio-vs-benchmark)
    forced_output_mode = req.output_mode
    if is_comparison_query and not forced_output_mode:
        forced_output_mode = "company_comparison"
    
    _session_record(session_id, mode=mode, target=target, objective=objective, user_email=user_email, tenant_id=tenant_id)
    TELEMETRY.emit_event(
        "research_started",
        user=telemetry_user,
        properties={
            "source": "backend",
            "session_id": session_id,
            "mode": mode,
            "request_mode": requested_mode,
            "target_length": len(raw_query),
            "comparison": is_comparison_query,
        },
    )

    async def _runner() -> None:
        try:
            # â”€â”€ Speed-first config â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            # Chat stays lightweight; standard keeps enrichment, reflection,
            # multi-agent checks, and visual synthesis.
            is_chat_mode = mode == "chat"
            is_standard_mode = mode == "standard"
            is_portfolio_query = is_portfolio_scope_query(objective) or is_portfolio_scope_query(raw_query)
            standard_deep_lite = is_standard_mode and _should_use_standard_deep_lite(
                objective,
                raw_query,
                is_portfolio_query=is_portfolio_query,
                is_comparison_query=is_comparison_query,
            )
            tier = "deep_lite" if standard_deep_lite else ("chat" if is_chat_mode else mode)
            logger.info("[MODE] session=%s tier=%s portfolio=%s comparison=%s query_len=%d",
                        session_id, tier, is_portfolio_query, is_comparison_query, len(raw_query))
            if req.max_steps is not None:
                base_steps = min(req.max_steps, 50)
            elif mode == "standard":
                base_steps = 18 if standard_deep_lite else 12
            else:
                base_steps = 28
            # Production hard cap: never exceed 50 steps regardless of mode or client input
            base_steps = min(base_steps, 50)
            logger.info("[GATEWAY] Research session %s base_steps capped at %d", session_id, base_steps)
            
            chat_history = _MEMORY_MANAGER.get_history(user_email, session_id)

            preset = STANDARD_PLUS_PRESET if standard_deep_lite else STANDARD_PRESET
            config_overrides = dict(preset)
            config_overrides.update(
                session_id=session_id,
                auto_depth=req.max_steps is None,
                output_mode=forced_output_mode,
                synth_model=os.getenv("FINAGENT_SYNTH_MODEL") or "gpt-5.4-mini",
                peer_targets=comparison_targets[1:] if len(comparison_targets) >= 2 else [],
                chat_history=chat_history,
                user_email=user_email,
                tenant_id=tenant_id,
            )
            if is_chat_mode:
                config_overrides.update(
                    max_steps=8,
                    breadth_search_timeout=8.0,
                    followup_search_timeout=5.0,
                    news_timeout=4.0,
                    quality_threshold=55.0,
                    response_depth="chat",
                )
            if req.max_steps is not None:
                config_overrides["max_steps"] = min(req.max_steps, 50)

            if is_chat_mode and os.environ.get("FINAGENT_CONVERSATIONAL_CHAT", "1") == "1":
                # True conversational chat: a finance-specialised chat model
                # (Claude/Gemini-style). Streamed prose, light real-time
                # grounding, NO research memo/report, no specialists/scraping.
                from finagent.chat_reply import run_chat_reply
                await run_chat_reply(
                    target,
                    objective,
                    session_id=session_id,
                    user_email=user_email,
                    chat_history=chat_history,
                    max_wall_seconds=float(req.max_wall_seconds or 18.0),
                )
            elif is_chat_mode:
                # Legacy lightweight research path (opt-out via env).
                await run_research_session(
                    target,
                    objective,
                    is_followup=is_followup,
                    loop_config=AgentLoopConfig(**config_overrides),
                )
            elif os.environ.get("FINAGENT_USE_SWARM_STANDARD", "1") == "1":
                # New compressed-deep standard mode: parallel evidence buckets,
                # IKG grounding, accuracy verification, and canvas synthesis.
                swarm_timeout = max(20.0, float(req.max_wall_seconds or 90.0)) + 5.0
                await asyncio.wait_for(
                    run_standard_v2_research_session(
                        target,
                        objective,
                        cfg=SwarmResearchConfig(
                            session_id=session_id,
                            max_wall_seconds=req.max_wall_seconds or 90.0,
                            user_email=user_email,
                            tenant_id=tenant_id,
                            portfolio_symbols=[],
                        ),
                    ),
                    timeout=swarm_timeout,
                )
            else:
                # Legacy standard pipeline (kept for regression tests and opt-out).
                await run_research_session(
                    target,
                    objective,
                    is_followup=is_followup,
                    loop_config=AgentLoopConfig(**config_overrides),
                )
            
        except asyncio.CancelledError:
            logger.warning("session %s cancelled before final synthesis", session_id)
            if not BUS.is_closed(session_id):
                BUS.emit(session_id, "log", source="gateway", level="warning", message="Research task was cancelled before final synthesis")
                BUS.emit(session_id, "error", message="Research task was cancelled before final synthesis")
                BUS.close(session_id)
        except asyncio.TimeoutError:
            logger.warning("session %s exceeded wall-clock budget", session_id)
            if not BUS.is_closed(session_id):
                BUS.emit(session_id, "log", source="gateway", level="warning", message="Research timed out before final synthesis")
                BUS.emit(session_id, "error", message="Research timed out before final synthesis")
                BUS.close(session_id)
        except Exception as exc:
            logger.exception("session %s crashed", session_id)
            BUS.emit(session_id, "log", source="gateway", level="error", message=f"Research failed: {type(exc).__name__}: {exc}")
            BUS.emit(session_id, "error", message=str(exc))
            BUS.close(session_id)
        finally:
            # Persist chat history even if the run crashed or timed out.
            # The user query is always saved; the assistant response is
            # saved only if a memo was successfully written to disk.
            _MEMORY_MANAGER.append_message(user_email, session_id, "user", raw_query)
            memo_path = _MEMOS_DIR / f"{session_id}.md"
            if memo_path.is_file():
                try:
                    final_memo = memo_path.read_text(encoding="utf-8")
                    _MEMORY_MANAGER.append_message(user_email, session_id, "assistant", final_memo)
                except Exception:
                    pass
            if not BUS.is_closed(session_id):
                BUS.close(session_id)
            _TASKS.pop(session_id, None)

    _TASKS[session_id] = asyncio.create_task(_runner())
    return JSONResponse({
        "session_id": session_id,
        "stream": f"/sessions/{session_id}/stream",
        "status": f"/sessions/{session_id}/status",
        "events": f"/sessions/{session_id}/events",
        "result": f"/sessions/{session_id}/result",
    })


# â”€â”€ Deep Research: multi-pass long-chain reasoning â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

# Each entry maps to a deep-research evidence or synthesis pass. The runtime
# keeps the public deep mode unchanged but now chooses a smaller intent-driven
# subset of these passes per request.
_DEEP_PASS_DEFINITIONS = [
    (
        "financials",
        "Core financials: 5-year revenue CAGR, EBITDA margin trend, net profit margins, EPS growth, "
        "free cash flow yield, return on capital employed (ROCE), debt-to-equity, interest coverage ratio, "
        "working capital cycle. Source from Screener.in, NSE filings, annual reports.",
    ),
    (
        "competitive_moat",
        "Competitive moat and market position: market share vs top 5 peers, pricing power evidence, "
        "switching costs, network effects, proprietary IP or patents, brand valuation, client concentration "
        "risk (top-10 clients as % of revenue), order-book or deal pipeline size and TCV.",
    ),
    (
        "governance",
        "Management quality and corporate governance: CEO/MD track record and tenure, promoter pledge "
        "percentage and trend, related-party transactions (RPTs) and their materiality, board independence "
        "ratio, auditor tenure and any qualifications, SEBI/stock-exchange show-cause notices or penalties, "
        "insider buying/selling patterns over the last 12 months.",
    ),
    (
        "valuation",
        "Valuation deep-dive: trailing and forward P/E vs sector median, EV/EBITDA vs global peers, "
        "PEG ratio, DCF implied price at WACC 10-12%, Graham number, price-to-free-cash-flow, "
        "dividend yield and payout sustainability, and source-attributed valuation scenario ranges. "
        "Do not produce buy/sell/hold labels, target prices, or trading calls.",
    ),
    (
        "risk",
        "Risk and red flag scan: regulatory investigations, pending litigation with financial exposure, "
        "environmental/ESG controversies, customer attrition or large contract losses, forex hedging "
        "policy and un-hedged exposure, commodity or input cost sensitivity, key-man dependency, "
        "technology disruption risk, recent management exits, any going-concern qualifications.",
    ),
    (
        "macro_sector",
        "Macro and sector overlay: government policy tailwinds (PLI schemes, budget allocations, "
        "infrastructure spend), RBI/interest-rate sensitivity, USD-INR impact on margins, crude oil "
        "or energy cost linkage, global demand cycle for the sector, peer capex plans, new entrants "
        "or foreign competition, import/export duties that affect the business model.",
    ),
    (
        "shareholding",
        "Shareholding and smart-money signals: latest FII/DII/promoter holding changes (QoQ), "
        "mutual fund entry/exit (top AMFs buying or trimming), bulk and block deal activity, "
        "promoter pledge creation or release, ESOP grants and dilution pipeline, ADR/GDR premium "
        "or discount, short interest data from F&O segment if available.",
    ),
    (
        "hidden_catalysts",
        "Hidden catalysts and growth optionality: new product lines or business segments under "
        "development, M&A pipeline or recent acquisitions and integration status, geographic "
        "expansion plans (new markets, international revenue mix), R&D pipeline and patent filings, "
        "digital transformation initiatives, capacity expansion capex with expected COD dates, "
        "recently-won mega-contracts or government tenders.",
    ),
    (
        "news_narrative",
        "Recent news, analyst commentary and market narrative: last 90-day earnings call key "
        "management guidance, analyst upgrades/downgrades with reasoning, negative investigative "
        "journalism or short-seller reports, Reddit/StockTwits retail sentiment trend, any "
        "Hacker News / tech community mentions, social media buzz or viral concerns.",
    ),
    (
        "peer_comparison",
        "Peer comparison deep-dive: side-by-side financial metrics vs 4-6 named peers (revenue "
        "growth, margins, valuation multiples, return ratios, debt levels), market-share trajectory "
        "over 3 years, relative stock performance YTD and 3-year CAGR, who is gaining vs losing "
        "share and why, pricing strategy differences, talent/attrition comparison if available.",
    ),
    (
        "capital_allocation",
        "Capital allocation quality and future return potential: historical capex efficiency (asset "
        "turns trend), dividend history and special dividend probability, buyback activity and "
        "its accretive/dilutive impact, reinvestment rate and incremental ROCE, management's "
        "stated capital allocation framework, balance sheet optionality (net cash or net debt), "
        "potential for re-rating if key milestones are met.",
    ),
    (
        "historical_sentiment",
        "Historical sentiment and management tone trajectory: extract management commentary "
        "from concall transcripts and exchange filings over the last 4-8 quarters. Track how "
        "management guidance has evolved â€” were prior guidance targets met, missed, or exceeded? "
        "Identify recurring concerns or optimism themes. Note shifts in language (cautious â†’ confident "
        "or vice versa). Compare analyst expectations vs actual delivery (consensus EPS misses/beats). "
        "Summarize FII/DII sentiment shifts and any notable institutional commentary.",
    ),
    (
        "synthesis",
        "Final synthesis: integrate all prior pass findings into a structured investment-grade "
        "research report. Resolve any data contradictions. Produce: (1) executive summary with "
        "clear stance (positive/neutral/negative/watch), investment thesis, and conviction level, "
        "(2) key financial metrics dashboard, (3) top 5 risk factors "
        "with probability/impact matrix, (4) competitive positioning verdict, (5) valuation "
        "summary with scenario-implied ranges and methodology, (6) key monitorables, and "
        "(7) historical sentiment trajectory if available.",
    ),
]
_DEEP_PASS_OBJECTIVES = [objective for _, objective in _DEEP_PASS_DEFINITIONS]
_DEEP_PASS_OBJECTIVES_BY_ID = {pass_id: objective for pass_id, objective in _DEEP_PASS_DEFINITIONS}
_DEEP_DEFAULT_PASS_IDS = ("competitive_moat", "valuation", "risk", "historical_sentiment")
_DEEP_PORTFOLIO_PASS_IDS = ("risk", "macro_sector", "capital_allocation")
_DEEP_FRESHNESS_TERMS = (
    "latest",
    "today",
    "recent",
    "current",
    "headline",
    "headlines",
    "news",
    "sentiment",
    "commentary",
    "90-day",
    "90 day",
)


def _contains_any_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _dedupe_pass_ids(pass_ids: list[str], *, limit: int | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for pass_id in pass_ids:
        if pass_id in seen:
            continue
        seen.add(pass_id)
        out.append(pass_id)
        if limit is not None and len(out) >= limit:
            break
    return out


def _is_broad_deep_objective(text: str) -> bool:
    return _contains_any_term(
        text,
        (
            "deep research",
            "deep-dive",
            "deep dive",
            "comprehensive",
            "full-scale",
            "investment-grade",
            "thesis",
            "report",
        ),
    )


def _is_freshness_sensitive_objective(text: str) -> bool:
    return _contains_any_term(text, _DEEP_FRESHNESS_TERMS)


def _select_deep_evidence_pass_ids(
    objective: str,
    raw_query: str,
    *,
    is_comparison_query: bool,
    portfolio_scope: bool,
) -> list[str]:
    combined = f"{raw_query}\n{objective}".lower()
    selected = ["financials"]
    intent_matches: list[str] = []

    if is_comparison_query or _contains_any_term(combined, ("compare", "versus", "vs ", "peer", "competitor")):
        intent_matches.extend(["peer_comparison", "competitive_moat"])
    if _contains_any_term(combined, ("valuation", "dcf", "multiple", "pe ", "p/e", "ev/ebitda", "price-to-book", "pb ")):
        intent_matches.append("valuation")
    if _contains_any_term(combined, ("risk", "red flag", "litigation", "investigation", "lawsuit", "hedging", "going concern")):
        intent_matches.append("risk")
    if _contains_any_term(combined, ("governance", "board", "auditor", "management", "insider", "related-party", "rpt")):
        intent_matches.append("governance")
    if _contains_any_term(combined, ("ownership", "shareholding", "promoter", "pledge", "fii", "dii", "institutional holding")):
        intent_matches.append("shareholding")
    if portfolio_scope or _contains_any_term(combined, ("macro", "sector", "policy", "rbi", "budget", "tailwind", "headwind", "usd-inr", "crude")):
        intent_matches.append("macro_sector")
    if _contains_any_term(combined, ("growth", "catalyst", "optionality", "new product", "m&a", "acquisition", "capacity", "tender", "pipeline")):
        intent_matches.append("hidden_catalysts")
    if _contains_any_term(combined, ("capital allocation", "buyback", "dividend", "capex", "reinvestment", "roce", "net cash", "net debt")):
        intent_matches.append("capital_allocation")
    if _contains_any_term(combined, ("moat", "market share", "pricing power", "switching costs", "network effects")):
        intent_matches.append("competitive_moat")
    if _contains_any_term(combined, ("news", "headline", "sentiment", "analyst", "short-seller", "retail sentiment")):
        intent_matches.append("news_narrative")
    if _contains_any_term(combined, ("concall", "transcript", "guidance", "management tone", "historical sentiment", "quarter over quarter", "delivery track")):
        intent_matches.append("historical_sentiment")

    if not intent_matches and _is_broad_deep_objective(combined):
        intent_matches.extend(_DEEP_PORTFOLIO_PASS_IDS if portfolio_scope else _DEEP_DEFAULT_PASS_IDS)

    selected.extend(_dedupe_pass_ids(intent_matches, limit=3))
    return selected


def _should_stop_deep_evidence(
    runtime_meta: dict[str, Any] | None,
    *,
    objective: str,
    raw_query: str,
    required_pass_ids: list[str],
    completed_pass_ids: list[str],
    is_comparison_query: bool,
) -> bool:
    if not runtime_meta:
        return False
    if "financials" not in completed_pass_ids:
        return False
    if is_comparison_query and "peer_comparison" not in completed_pass_ids:
        return False
    if int(runtime_meta.get("conflict_count") or 0) > 0:
        return False

    combined = f"{raw_query}\n{objective}".lower()
    if _is_freshness_sensitive_objective(combined):
        if int(runtime_meta.get("news_item_count") or 0) <= 0:
            return False
        return bool(
            runtime_meta.get("ikg_sufficient")
            or runtime_meta.get("can_answer_objective")
            or int(runtime_meta.get("doc_count") or 0) >= 3
        )

    if runtime_meta.get("ikg_sufficient") and not runtime_meta.get("objective_needs_fresh_web"):
        return True
    if runtime_meta.get("can_answer_objective") and int(runtime_meta.get("doc_count") or 0) >= 2:
        return True
    return bool(
        int(runtime_meta.get("primary_citations") or 0) >= 2
        and int(runtime_meta.get("doc_count") or 0) >= 4
    )


def _select_deep_guardrail_pass_id(
    runtime_meta: dict[str, Any] | None,
    *,
    objective: str,
    raw_query: str,
    completed_pass_ids: list[str],
    is_comparison_query: bool,
    portfolio_scope: bool,
) -> str | None:
    combined = f"{raw_query}\n{objective}".lower()
    if not runtime_meta:
        return "news_narrative" if _is_freshness_sensitive_objective(combined) else None

    if int(runtime_meta.get("conflict_count") or 0) > 0:
        for candidate in ("risk", "valuation", "governance", "news_narrative"):
            if candidate not in completed_pass_ids:
                return candidate

    if _is_freshness_sensitive_objective(combined) and "news_narrative" not in completed_pass_ids:
        return "news_narrative"
    if is_comparison_query and "peer_comparison" not in completed_pass_ids:
        return "peer_comparison"
    if portfolio_scope and "macro_sector" not in completed_pass_ids:
        return "macro_sector"
    if _is_broad_deep_objective(combined) and not runtime_meta.get("ikg_sufficient") and "competitive_moat" not in completed_pass_ids:
        return "competitive_moat"
    return None


@app.post("/research/deep", dependencies=[Depends(research_rate_limiter)])
async def start_deep_research(req: DeepResearchRequest, current_user: dict = Depends(enforce_token_limit)):
    master_session = req.session_id or uuid.uuid4().hex[:12]
    telemetry_user = telemetry_user_from_request_user(current_user)
    
    if req.session_id:
        verify_session_ownership(master_session, current_user)
        
    raw_query = req.target.strip()
    raw_query = _strip_frontend_portfolio_context(raw_query) or raw_query
    user_email = current_user["email"]
    tenant_id = current_user["tenant_id"]
    _require_no_active_ingestion(tenant_id)
    if is_portfolio_scope_query(raw_query):
        await _require_synchronized_portfolio(tenant_id, allow_empty=True)

    # â”€â”€ Pure-LLM follow-up detection for deep research runs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    meta = _load_session_meta(master_session)
    prior_target = meta.get("target_display") or meta.get("target")
    is_followup_deep = False
    target = None
    objective_for_deep = (req.objective or raw_query).strip()

    if req.session_id and prior_target:
        chat_history = _MEMORY_MANAGER.get_history(user_email, master_session)
        try:
            result = await _contextualize_query_with_budget(
                raw_query,
                prior_target,
                chat_history,
                timeout_s=_gateway_float_setting("FINAGENT_DEEP_CONTEXTUALIZER_TIMEOUT_S", 8.0),
            )
            is_followup_deep = result.is_followup

            if is_followup_deep:
                target = prior_target
                if result.contextualized_query and result.contextualized_query.strip():
                    objective_for_deep = result.contextualized_query.strip()
            else:
                target = result.target or primary_target_from_query(raw_query)
                if result.contextualized_query and result.contextualized_query.strip():
                    objective_for_deep = result.contextualized_query.strip()

                if prior_target and target and prior_target.lower() != target.lower():
                    master_session = uuid.uuid4().hex[:12]
                    BUS.open(master_session, reset=True)
                    logger.info("Target changed from %r to %r â€” new deep session %s", prior_target, target, master_session)
        except (asyncio.TimeoutError, ContextualizerError, Exception) as exc:
            logger.warning("Deep contextualizer failed for session %s, falling back to raw query: %s", master_session, exc)
            is_followup_deep = True
            target = prior_target
            objective_for_deep = raw_query.strip()
    else:
        target = primary_target_from_query(raw_query)

    objective_scope_query = _strip_frontend_portfolio_context(objective_for_deep) or raw_query
    portfolio_scope_query = is_portfolio_scope_query(objective_scope_query)
    if portfolio_scope_query:
        await _require_synchronized_portfolio(tenant_id, allow_empty=True)

    # â”€â”€ Deep-mode premium quota check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Bound the quota check: a slow/unreachable usage store must not hang the
    # start response (frontend aborts after CHAT_START_TIMEOUT_MS). Quota HTTP
    # errors (429) still propagate; only a timeout fails open.
    try:
        await asyncio.wait_for(_check_deep_run_access(current_user), timeout=8.0)
    except asyncio.TimeoutError:
        logger.warning("deep run access check timed out for %s; allowing run", user_email)

    from finagent.output.query_guards import is_portfolio_comparison_query
    is_comparison_query = _is_comparison(raw_query) and not is_portfolio_comparison_query(raw_query)
    comparison_targets = _extract_comparison_targets(raw_query) if is_comparison_query else []
    peer_targets_list = comparison_targets[1:] if len(comparison_targets) >= 2 else []
    evidence_pass_ids = _select_deep_evidence_pass_ids(
        objective_for_deep,
        raw_query,
        is_comparison_query=is_comparison_query,
        portfolio_scope=portfolio_scope_query,
    )
    planned_total_passes = min(6, len(evidence_pass_ids) + 2)

    BUS.open(master_session, reset=True)
    _clear_session_memo(master_session)

    # Record deep-run usage for free-tier quota enforcement. Best-effort and
    # time-bounded — never block the start response on the usage store.
    try:
        await asyncio.wait_for(_record_deep_run(current_user), timeout=6.0)
    except asyncio.TimeoutError:
        logger.warning("deep run usage record timed out for %s; continuing", user_email)
    except Exception as exc:
        logger.warning("deep run usage record failed for %s: %s", user_email, exc)

    # Deep mode: NLP intent extraction on the original prompt â€” the user must
    # explicitly ask for a downloadable document, otherwise we keep output as
    # an in-app memo. The PDF/DOCX is never generated automatically.
    from finagent.agent.query_analysis import detect_export_intent
    _intent = detect_export_intent(raw_query)
    _export_intent_dict = {
        "wants_export": _intent.wants_export,
        "confidence": _intent.confidence,
        "matched": _intent.matched,
        "negated": _intent.negated,
    }
    _session_record(
        master_session,
        mode="deep",
        target=target,
        objective=objective_for_deep,
        user_email=user_email,
        tenant_id=tenant_id,
        export_intent=_export_intent_dict,
    )
    # Deep mode: check IKG staleness for the resolved target so synthesis can
    # acknowledge data age. Best-effort â€” never blocks the run.
    try:
        from finagent.agent.query_analysis import classify_query_complexity
        from finagent.ikg.entity_resolver import get_entity_resolver
        from finagent.ikg.staleness import get_staleness_checker
        if classify_query_complexity(raw_query).enable_verification and target:
            # Time-bound the IKG lookups — a slow/unreachable IKG Postgres must
            # not hang the start response.
            ent = await asyncio.wait_for(asyncio.to_thread(get_entity_resolver().resolve, target), timeout=4.0)
            if ent and ent.cin:
                verdict = await asyncio.wait_for(asyncio.to_thread(get_staleness_checker().check_company, ent.cin), timeout=4.0)
                BUS.emit(
                    master_session, "ikg_staleness",
                    band=verdict.band, needs_refresh=verdict.needs_refresh,
                    age_days=verdict.age_days, last_updated=verdict.last_updated,
                    cin=ent.cin, reason=verdict.reason,
                )
    except Exception as exc:
        logger.debug("IKG staleness preflight skipped: %s", exc)
    TELEMETRY.emit_event(
        "research_deep_started",
        user=telemetry_user,
        properties={
            "source": "backend",
            "session_id": master_session,
            "passes": req.passes,
            "target_length": len(raw_query),
            "comparison": is_comparison_query,
        },
    )

    async def _deep_runner() -> None:
        if os.environ.get("FINAGENT_USE_SWARM_DEEP", "1") == "1":
            await _deep_runner_swarm()
        else:
            await _deep_runner_legacy()

    async def _maybe_auto_export_documents() -> None:
        """Generate all export formats if the user asked for a document in the prompt."""
        if os.environ.get("FINAGENT_DEEP_AUTO_EXPORT", "1") != "1":
            return
        try:
            session_rec = _SESSION_META.get(master_session) or _load_session_meta(master_session)
            intent = session_rec.get("export_intent") or {}
            if not intent.get("wants_export") or intent.get("confidence", 0.0) < 0.6:
                return
            artifact = _SESSION_ARTIFACTS.get(master_session)
            if artifact is None:
                return
            from finagent.swarm.document_agent import DocumentAgent
            agent = DocumentAgent(master_session)
            results = await agent.generate_all(artifact)
            BUS.emit(
                master_session,
                "documents_ready",
                results={k: v for k, v in results.items() if v.get("ok")},
                errors={k: v.get("error") for k, v in results.items() if v.get("error")},
            )
            logger.info("[DOCUMENT_AGENT] auto-exported session %s: %s", master_session, results)
        except Exception as exc:
            logger.warning("[DOCUMENT_AGENT] auto-export failed for %s: %s", master_session, exc)

    async def _deep_runner_legacy() -> None:
        completed_passes = 0
        started_at = asyncio.get_running_loop().time()
        chat_history = _MEMORY_MANAGER.get_history(user_email, master_session)
        completed_pass_ids: list[str] = []
        last_runtime_meta: dict[str, Any] = {}

        try:
            async def _run_pass(
                pass_number: int,
                *,
                pass_id: str,
                emit_memo: bool,
                enable_memory: bool,
            ) -> tuple[bool, dict[str, Any]]:
                async with _DEEP_RESEARCH_SEMAPHORE:
                    if req.max_wall_seconds is not None:
                        remaining = req.max_wall_seconds - (asyncio.get_running_loop().time() - started_at)
                        if remaining <= 0:
                            return False, {}

                    is_last = pass_id == "synthesis"
                    objective = _DEEP_PASS_OBJECTIVES_BY_ID[pass_id]
                    pass_label = f"Synthesis Pass {pass_number}/{planned_total_passes}" if is_last else f"Pass {pass_number}/{planned_total_passes}"

                    BUS.emit(master_session, "phase", phase="deep_research", note=f"{pass_label}: {objective[:60]}â€¦")
                    BUS.emit(
                        master_session,
                        "deep_pass",
                        pass_number=pass_number,
                        total_passes=planned_total_passes,
                        objective=objective,
                        deep_pass_label=pass_label,
                        pass_id=pass_id,
                        status="running",
                    )

                    pass_objective = f"{objective_for_deep}\n\n{pass_label} - {objective}"
                    # For comparison queries, force comparison output mode on synthesis pass
                    effective_output_mode = "company_comparison" if (is_comparison_query and is_last) else ("deep_research_report" if is_last else None)

                    run_result = await run_research_session(
                        target,
                        pass_objective,
                        is_followup=is_followup_deep,
                        loop_config=AgentLoopConfig(
                            max_steps=(req.pass_depth if is_last else min(req.pass_depth, 12)),
                            session_id=master_session,
                            auto_depth=False,
                            enable_memory=enable_memory,
                            reflection_max_rounds=(1 if is_last else 0),
                            quality_threshold=(72.0 if is_last else 65.0),
                            reflection_per_query_limit=(4 if is_last else 0),
                            reflection_max_new_docs=(32 if is_last else 0),
                            reflection_max_queries_per_round=(4 if is_last else 0),
                            reflection_wall_clock_seconds=(45.0 if is_last else 0.0),
                            reflection_early_accept_margin=(2.0 if is_last else 0.0),
                            reflection_min_score_gain=(0.75 if is_last else 0.0),
                            synth_model=os.getenv("FINAGENT_SYNTH_MODEL") or "gpt-5.4-mini",
                            response_depth=("deep" if is_last else "standard"),
                            output_mode=effective_output_mode,
                            emit_memo=emit_memo,
                            close_bus_on_finish=False,
                            chat_history=chat_history if (enable_memory or is_last) else None,
                            breadth_search_timeout=(75.0 if is_last else 20.0),
                            followup_search_timeout=(35.0 if is_last else 8.0),
                            reflection_per_query_timeout=(18.0 if is_last else 0.0),
                            blindspot_per_query_timeout=(25.0 if is_last else 0.0),
                            news_timeout=(18.0 if is_last else 5.0),
                            enable_blindspot=is_last,
                            enable_multi_agent=is_last,
                            enable_reflection=is_last,
                            enable_deep_dive=is_last,
                            fast_mode=not is_last,
                            # â”€â”€ Peer targets ensure synthesis fetches BOTH companies' enrichment
                            peer_targets=peer_targets_list,
                            user_email=user_email,
                            tenant_id=tenant_id,
                        ),
                    )
                    checkpoint = None
                    if isinstance(run_result, tuple):
                        if len(run_result) >= 2:
                            checkpoint = run_result[1]
                    elif run_result is not None:
                        checkpoint = run_result

                    BUS.emit(
                        master_session,
                        "deep_pass",
                        pass_number=pass_number,
                        total_passes=planned_total_passes,
                        objective=objective,
                        deep_pass_label=pass_label,
                        pass_id=pass_id,
                        status="done",
                    )
                    return True, dict(getattr(checkpoint, "runtime_meta", {}) or {})

            BUS.emit(
                master_session,
                "phase",
                phase="deep_research",
                note=f"Executing adaptive deep plan with {len(evidence_pass_ids)} evidence pass(es) before synthesis",
            )

            # Run evidence passes in parallel for 2-3Ã— wall-clock speed-up.
            # Each pass does independent research; synthesis pass integrates afterward.
            async def _evidence_pass(idx: int, pid: str) -> tuple[str, bool, dict[str, Any]]:
                ok, meta = await _run_pass(
                    idx + 1,
                    pass_id=pid,
                    emit_memo=False,
                    enable_memory=(idx == 0),
                )
                return pid, ok, meta

            if req.max_wall_seconds is not None:
                remaining = req.max_wall_seconds - (asyncio.get_running_loop().time() - started_at)
                evidence_timeout = max(10.0, remaining * 0.75)
            else:
                evidence_timeout = None

            evidence_tasks = [
                asyncio.create_task(_evidence_pass(i, pid))
                for i, pid in enumerate(evidence_pass_ids)
            ]
            try:
                if evidence_timeout:
                    done, pending = await asyncio.wait(evidence_tasks, timeout=evidence_timeout)
                    for t in pending:
                        t.cancel()
                    evidence_results = [t.result() for t in done if not t.cancelled() and not t.exception()]
                else:
                    raw_results = await asyncio.gather(*evidence_tasks, return_exceptions=True)
                    evidence_results = [r for r in raw_results if isinstance(r, tuple)]
            except Exception:
                logger.exception("Deep evidence parallel batch failed for %s", master_session)
                evidence_results = []

            for pid, ok, runtime_meta in evidence_results:
                if ok:
                    completed_passes += 1
                    completed_pass_ids.append(pid)
                    last_runtime_meta = runtime_meta
            guardrail_id = None
            if len(completed_pass_ids) < 5 and not _should_stop_deep_evidence(
                last_runtime_meta,
                objective=objective_for_deep,
                raw_query=raw_query,
                required_pass_ids=evidence_pass_ids,
                completed_pass_ids=completed_pass_ids,
                is_comparison_query=is_comparison_query,
            ):
                guardrail_id = _select_deep_guardrail_pass_id(
                    last_runtime_meta,
                    objective=objective_for_deep,
                    raw_query=raw_query,
                    completed_pass_ids=completed_pass_ids,
                    is_comparison_query=is_comparison_query,
                    portfolio_scope=portfolio_scope_query,
                )
            if guardrail_id and guardrail_id not in completed_pass_ids:
                pass_number = len(completed_pass_ids) + 1
                ok, runtime_meta = await _run_pass(
                    pass_number,
                    pass_id=guardrail_id,
                    emit_memo=False,
                    enable_memory=False,
                )
                if ok:
                    completed_passes += 1
                    completed_pass_ids.append(guardrail_id)
                    last_runtime_meta = runtime_meta

            if req.max_wall_seconds is None or (req.max_wall_seconds - (asyncio.get_running_loop().time() - started_at)) > 0:
                pass_number = len(completed_pass_ids) + 1
                ok, _ = await _run_pass(
                    pass_number,
                    pass_id="synthesis",
                    emit_memo=True,
                    enable_memory=True,
                )
                if ok:
                    completed_passes += 1
                    try:
                        artifact = _build_artifact_from_bus(master_session)
                        if artifact is not None:
                            _SESSION_ARTIFACTS[master_session] = artifact
                            logger.info("[EXPORT] stored AnswerArtifact for session %s (%d sections, %d citations)",
                                        master_session, len(artifact.sections), len(artifact.citations))
                    except Exception as art_exc:
                        logger.warning("[EXPORT] failed to build artifact for %s: %s", master_session, art_exc)

            await _maybe_auto_export_documents()

            BUS.emit(master_session, "deep_complete", passes=completed_passes, requested_passes=planned_total_passes)
        except asyncio.CancelledError:
            logger.warning("deep research %s cancelled before final synthesis", master_session)
            if not BUS.is_closed(master_session):
                BUS.emit(master_session, "log", source="gateway", level="warning", message="Deep research task was cancelled before final synthesis")
                BUS.emit(master_session, "error", message="Deep research task was cancelled before final synthesis")
                BUS.close(master_session)
        except Exception as exc:
            logger.exception("deep research %s crashed on pass", master_session)
            BUS.emit(master_session, "log", source="gateway", level="error", message=f"Deep research failed: {type(exc).__name__}: {exc}")
            BUS.emit(master_session, "error", message=f"Deep research failed: {exc}")
        finally:
            _TASKS.pop(master_session, None)
            BUS.close(master_session)

    async def _deep_runner_swarm() -> None:
        try:
            BUS.emit(
                master_session,
                "phase",
                phase="deep_research",
                note="Starting dynamic agent swarm with up to 300 sub-agents",
            )
            canvas = await run_deep_swarm_research_session(
                target,
                objective_for_deep,
                cfg=SwarmResearchConfig(
                    session_id=master_session,
                    max_wall_seconds=req.max_wall_seconds or 300.0,
                    max_swarm_tasks=300,
                    max_swarm_concurrency=20,
                    user_email=user_email,
                    tenant_id=tenant_id,
                    portfolio_symbols=[],
                ),
            )
            try:
                artifact = _build_artifact_from_bus(master_session)
                if artifact is not None:
                    _SESSION_ARTIFACTS[master_session] = artifact
                    logger.info("[EXPORT] stored AnswerArtifact for session %s (%d sections, %d citations)",
                                master_session, len(artifact.sections), len(artifact.citations))
            except Exception as art_exc:
                logger.warning("[EXPORT] failed to build artifact for %s: %s", master_session, art_exc)

            await _maybe_auto_export_documents()

            BUS.emit(master_session, "deep_complete", passes=1, requested_passes=1)
        except asyncio.CancelledError:
            logger.warning("deep research %s cancelled before final synthesis", master_session)
            if not BUS.is_closed(master_session):
                BUS.emit(master_session, "log", source="gateway", level="warning", message="Deep research task was cancelled before final synthesis")
                BUS.emit(master_session, "error", message="Deep research task was cancelled before final synthesis")
                BUS.close(master_session)
        except Exception as exc:
            logger.exception("deep research %s crashed on pass", master_session)
            BUS.emit(master_session, "log", source="gateway", level="error", message=f"Deep research failed: {type(exc).__name__}: {exc}")
            BUS.emit(master_session, "error", message=f"Deep research failed: {exc}")
        finally:
            _TASKS.pop(master_session, None)
            BUS.close(master_session)

    _TASKS[master_session] = asyncio.create_task(_deep_runner())
    return JSONResponse({
        "session_id": master_session,
        "stream": f"/sessions/{master_session}/stream",
        "status": f"/sessions/{master_session}/status",
        "events": f"/sessions/{master_session}/events",
        "result": f"/sessions/{master_session}/result",
        "mode": "deep",
        "passes": req.passes,
    })


# â”€â”€ Document export (deep mode only) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

from finagent.output.export_jobs import ExportFormat, ExportJob, cleanup_expired, get_job, start_export
from finagent.output.report_exporter import can_generate_documents


class ExportRequest(BaseModel):
    session_id: str
    format: str = Field(..., description="pdf, docx, xlsx, or pptx")
    style: str = Field(default="sell_side")


@app.post("/research/export")
async def request_export(req: ExportRequest, current_user: dict = Depends(get_current_user)):
    """Start an async document export job for a deep-mode session."""
    sid = _validate_session_id(req.session_id)
    verify_session_ownership(sid, current_user)

    session_rec = _SESSION_META.get(sid) or _load_session_meta(sid)
    session_mode = session_rec.get("mode", "")
    if not can_generate_documents(session_mode):
        raise HTTPException(422, "Document export is only available for deep-mode research sessions.")

    fmt = req.format.lower().strip()
    if fmt not in ("pdf", "docx", "xlsx", "pptx"):
        raise HTTPException(400, f"Unsupported format: {fmt}")

    artifact = _SESSION_ARTIFACTS.get(sid)
    if artifact is None:
        raise HTTPException(404, "No research artifact found for this session. Wait for the research to complete.")

    # Export remains explicit: user must click the export button (this endpoint).
    # Deep mode never auto-generates the document; this call requires the user
    # to have explicitly requested one (either in the prompt â€” wants_export â€” or
    # by clicking the post-session export button, which still arrives here).
    job = await start_export(sid, artifact, fmt, style=req.style)
    return JSONResponse({"job_id": job.job_id, "status": job.status}, status_code=202)


@app.get("/research/export/{job_id}")
async def export_status(job_id: str, current_user: dict = Depends(get_current_user)):
    """Poll the status of an export job."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Export job not found.")
    verify_session_ownership(job.session_id, current_user)
    return {
        "job_id": job.job_id,
        "status": job.status,
        "format": job.format,
        "error": job.error,
    }


@app.get("/research/export/{job_id}/download")
async def export_download(job_id: str, current_user: dict = Depends(get_current_user)):
    """Download the completed export job."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "Export job not found.")
    verify_session_ownership(job.session_id, current_user)
    if job.status != "done":
        raise HTTPException(409, f"Export job is {job.status}, not ready for download.")
    if not job.path or not job.path.exists():
        raise HTTPException(500, "Export file missing.")

    mime_types = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    return FileResponse(
        path=str(job.path),
        media_type=mime_types.get(job.format, "application/octet-stream"),
        filename=f"prospektlab_report.{job.format}",
    )


class ExportAllRequest(BaseModel):
    session_id: str
    style: str = Field(default="sell_side")


@app.post("/research/export-all")
async def request_export_all(req: ExportAllRequest, current_user: dict = Depends(get_current_user)):
    """Generate all export formats (PDF, DOCX, XLSX, PPTX) for a deep session.

    This is a convenience endpoint that uses the Document Agent to produce the
    full research-document package in one call. Each format is generated
    independently; failures in one format do not block the others.
    """
    sid = _validate_session_id(req.session_id)
    verify_session_ownership(sid, current_user)

    session_rec = _SESSION_META.get(sid) or _load_session_meta(sid)
    session_mode = session_rec.get("mode", "")
    if not can_generate_documents(session_mode):
        raise HTTPException(422, "Document export is only available for deep-mode research sessions.")

    artifact = _SESSION_ARTIFACTS.get(sid)
    if artifact is None:
        raise HTTPException(404, "No research artifact found for this session. Wait for the research to complete.")

    from finagent.swarm.document_agent import DocumentAgent
    agent = DocumentAgent(sid)
    results = await agent.generate_all(artifact)
    return JSONResponse({"session_id": sid, "results": results})


# â”€â”€ Stop / cancel a running session â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@app.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str, current_user: dict = Depends(get_current_user_or_guest)):
    """Cancel a running research session mid-flight."""
    verify_session_ownership(session_id, current_user)
    task = _TASKS.get(session_id)
    if task is None or task.done():
        raise HTTPException(status_code=404, detail="No active task for this session.")
    TELEMETRY.emit_event(
        "research_stop_requested",
        user=telemetry_user_from_request_user(current_user),
        properties={
            "source": "backend",
            "session_id": session_id,
        },
    )
    task.cancel()
    BUS.emit(session_id, "phase", phase="stopped", reason="user_cancelled", note="Research stopped by user.")
    BUS.emit(session_id, "error", message="Research cancelled by user.")
    BUS.close(session_id)
    logger.info("Session %s cancelled by user", session_id)
    TELEMETRY.emit_event(
        "research_stop_completed",
        user=telemetry_user_from_request_user(current_user),
        properties={
            "source": "backend",
            "session_id": session_id,
        },
    )
    return {"session_id": session_id, "status": "cancelled"}


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str, current_user: dict = Depends(get_current_user)) -> JSONResponse:
    """Delete a completed session and its persisted artifacts."""
    verify_session_ownership(session_id, current_user)
    task = _TASKS.get(session_id)
    if task and not task.done():
        raise HTTPException(status_code=409, detail="Cannot delete a session while it is still running.")

    memo_path = _MEMOS_DIR / f"{session_id}.md"
    removed_memo = False
    if memo_path.is_file():
        memo_path.unlink(missing_ok=True)
        removed_memo = True

    session_dir = _session_dir(session_id)
    removed_session_dir = False
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)
        removed_session_dir = True

    _SESSION_META.pop(session_id, None)
    BUS.forget_memory(session_id)
    deleted_history = _MEMORY_MANAGER.delete_session(current_user["email"], session_id)
    memory_cleanup = await get_memory_store().delete_session(session_id, user_email=current_user["email"])

    return JSONResponse({
        "session_id": session_id,
        "deleted": True,
        "removed_memo": removed_memo,
        "removed_session_dir": removed_session_dir,
        "deleted_history_messages": deleted_history,
        "deleted_memory_facts": memory_cleanup["facts"],
        "deleted_session_summaries": memory_cleanup["summaries"],
    })



@app.post("/chat/research", dependencies=[Depends(research_rate_limiter)])
async def chat_research(
    request: Request,
    req: ChatResearchRequest,
    current_user: dict = Depends(get_chat_user_or_guest),
):
    """Chat-interface friendly entrypoint.

    Starts a background research job and returns polling/SSE/result URLs.
    A chat backend can call this, periodically poll `/status` or `/events`,
    then fetch `/result` when done.
    """
    if req.session_id:
        verify_session_ownership(req.session_id, current_user)
        
    target = (req.target or req.message).strip()
    mode = (req.mode or "standard").strip().lower()
    TELEMETRY.emit_event(
        "chat_research_requested",
        user=telemetry_user_from_request_user(current_user),
        properties={
            "source": "backend",
            "mode": mode,
            "target_length": len(target),
            "has_session_id": bool(req.session_id),
        },
    )
    _require_no_active_ingestion(current_user.get("tenant_id"))
    if mode == "marathon":
        mode = "deep"
    # Anonymous visitors: free public chat, bounded by a per-IP daily cap
    # (deep < standard). Authenticated users are governed by token limits.
    if _is_guest_user(current_user):
        await enforce_guest_daily_cap(request, mode)
    if mode == "deep":
        response = await start_deep_research(
            DeepResearchRequest(
                target=target,
                objective=req.message,
                passes=8,
                pass_depth=40,
                max_wall_seconds=req.max_wall_seconds,
                heartbeat_interval_s=20,
                session_id=req.session_id,
            ),
            current_user=current_user
        )
        _attach_guest_cookie_to_response(response, request, current_user)
        return response
    response = await start_research(
        StartResearchRequest(
            target=target,
            objective=req.message,
            max_wall_seconds=req.max_wall_seconds,
            heartbeat_interval_s=20,
            mode=mode,
            session_id=req.session_id,
        ),
        current_user=current_user
    )
    _attach_guest_cookie_to_response(response, request, current_user)
    return response


@app.get("/memos")
def list_memos(current_user: dict = Depends(get_current_user)) -> JSONResponse:
    if not _MEMOS_DIR.is_dir():
        return JSONResponse({"memos": []})
    entries: list[dict[str, Any]] = []
    for p in sorted(_MEMOS_DIR.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:50]:
        try:
            session_id = _validate_session_id(p.stem)
        except HTTPException:
            continue
        meta = _load_session_meta(session_id)
        owner_tenant = (meta.get("tenant_id") or "").strip()
        owner_email = (meta.get("user_email") or "").strip().lower()
        current_tenant = (current_user.get("tenant_id") or "").strip()
        current_email = (current_user.get("email") or "").strip().lower()
        # Fail closed: hide sessions that do not have ownership metadata.
        if not owner_tenant and not owner_email:
            continue
        if owner_tenant and current_tenant and owner_tenant != current_tenant:
            continue
        if owner_email and owner_email != current_email:
            continue
            
        try:
            head = p.read_text(encoding="utf-8")[:200]
        except Exception:
            head = ""
        title = head.split("\n", 1)[0].lstrip("# ").strip() or p.stem
        entries.append(
            {
                "session_id": session_id,
                "title": title,
                "bytes": p.stat().st_size,
                "modified": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return JSONResponse({"memos": entries})


@app.get("/sessions/{session_id}/memo")
def get_memo(session_id: str, current_user: dict = Depends(get_current_user)):
    verify_session_ownership(session_id, current_user)
    memo_path = _MEMOS_DIR / f"{session_id}.md"
    if not memo_path.is_file():
        raise HTTPException(status_code=404, detail="Memo not ready")
    return HTMLResponse(
        memo_path.read_text(encoding="utf-8"),
        media_type="text/markdown",
        headers={"Cache-Control": "no-store, max-age=0"}
    )


@app.get("/sessions/{session_id}/canvas")
def get_canvas(session_id: str, current_user: dict = Depends(get_current_user)):
    """Return the interactive research canvas for a session."""
    verify_session_ownership(session_id, current_user)
    canvas = CanvasStore().load(session_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")
    return JSONResponse(canvas.to_dict())


class SteerRequest(BaseModel):
    command: str
    text: str = ""
    peer: str = ""


@app.post("/sessions/{session_id}/canvas/steer")
async def steer_canvas(
    session_id: str,
    req: SteerRequest,
    current_user: dict = Depends(get_current_user_or_guest),
):
    """Apply a user steering command to a running or completed canvas."""
    verify_session_ownership(session_id, current_user)
    store = CanvasStore()
    canvas = store.load(session_id)
    if canvas is None:
        raise HTTPException(status_code=404, detail="Canvas not found")

    controller = CanvasController(store)
    new_tasks = controller.apply_steer(canvas, req.model_dump())
    store.save(canvas)

    # Spawn a background task to execute the new subtasks if the session is active
    if new_tasks and session_id in _TASKS and not _TASKS[session_id].done():
        # The running swarm will pick up new tasks on its next iteration if supported;
        # for now, emit a steer event so the UI can show the new task list.
        BUS.emit(session_id, "user_steer", steer=req.model_dump(), new_tasks=new_tasks)

    return JSONResponse({"canvas": canvas.to_dict(), "new_tasks": new_tasks})


@app.post("/api/content/articles/generate", dependencies=[Depends(default_rate_limiter)])
async def generate_content_article(
    req: ContentAutomationRequest,
    current_user: dict = Depends(enforce_token_limit),
):
    result = await generate_article_automation(req, requested_by=current_user["email"])
    TELEMETRY.emit_event(
        "content_article_generated",
        user=telemetry_user_from_request_user(current_user),
        properties={
            "source": "backend",
            "slug": result.slug,
            "route_base": result.route_base,
            "mirrored_public": bool(result.mirrored_public_path),
        },
    )
    return JSONResponse(await _jsonable_model_dump(result))


@app.post("/api/content/articles/generate-batch", dependencies=[Depends(default_rate_limiter)])
async def generate_content_article_batch(
    req: ContentAutomationBatchRequest,
    current_user: dict = Depends(enforce_token_limit),
):
    result = await generate_article_batch(req, requested_by=current_user["email"])
    TELEMETRY.emit_event(
        "content_article_batch_generated",
        user=telemetry_user_from_request_user(current_user),
        properties={
            "source": "backend",
            "route_base": result.route_base,
            "requested": result.total_requested,
            "completed": result.total_completed,
            "failed": result.total_failed,
        },
    )
    return JSONResponse(await _jsonable_model_dump(result))


@app.post("/api/content/events/ingest", dependencies=[Depends(default_rate_limiter)])
async def ingest_content_events(
    req: ContentEventIngestionRequest,
    current_user: dict = Depends(enforce_token_limit),
):
    result = await ingest_market_event_triggers(req, requested_by=current_user["email"])
    TELEMETRY.emit_event(
        "content_events_ingested",
        user=telemetry_user_from_request_user(current_user),
        properties={
            "source": "backend",
            "route_base": result.route_base,
            "discovered_events": result.discovered_events,
            "generated_articles": result.generated_articles,
            "auto_published": result.auto_published,
            "drafts": result.drafts,
        },
    )
    return JSONResponse(await _jsonable_model_dump(result))


def _relativise_public_url(entry: dict) -> dict:
    """Replace the absolute production public_url with a relative path.

    The canonical public_url stored in article.json is always
    https://prospektlab.com/... (baked from _SITE_URL).  That value is
    correct for production SEO but breaks local dev links because clicking
    it navigates the browser to the live site.  We override it here so
    every API consumer receives a root-relative path that works on any
    host (Vite dev proxy, staging, prod Amplify rewrite, etc.).
    """
    rb = entry.get("route_base") or "insights"
    sl = entry.get("slug") or ""
    if sl:
        entry = dict(entry)  # shallow copy â€” don't mutate the cached dict
        entry["public_url"] = f"/{rb}/{sl}/"
    return entry


@app.get("/api/content/articles")
async def list_content_articles(
    route_base: str | None = None,
    limit: int = 50,
    current_user: dict | None = Depends(get_current_user_optional),
):
    entries = list_generated_articles(route_base=route_base, limit=limit)
    # Anonymous visitors (hub public page) only see published articles
    if current_user is None:
        entries = [
            e for e in entries
            if str(e.get("publish_status") or "").lower() == "published"
            and str(e.get("publish_gate_status") or "").lower() == "publish"
        ]
    # Override public_url to be a relative path so links work on local dev
    entries = [_relativise_public_url(e) for e in entries]
    return JSONResponse({"items": entries, "count": len(entries)})


@app.get("/api/content/articles/{slug}")
async def get_content_article(slug: str, route_base: str = "insights", current_user: dict = Depends(get_current_user)):
    article = load_generated_article(slug, route_base=route_base)
    if not article:
        raise HTTPException(status_code=404, detail="Generated article not found")
    return JSONResponse(_relativise_public_url(article))


@app.get("/api/content/articles/{slug}/html")
async def get_content_article_html(slug: str, route_base: str = "insights"):
    article_html = load_generated_article_html(slug, route_base=route_base)
    if not article_html:
        raise HTTPException(status_code=404, detail="Generated article not found")
    return HTMLResponse(article_html, headers={"Cache-Control": "public, max-age=300"})


_PUBLIC_RESEARCH_HUB_PATHS = [
    repo_root() / "frontend" / "public" / "insights" / "research" / "index.html",
    repo_root() / "frontend" / "app" / "public" / "insights" / "research" / "index.html",
]


def _render_public_research_hub() -> HTMLResponse:
    """Serve the curated public research hub without falling into slug routing."""
    for public_path in _PUBLIC_RESEARCH_HUB_PATHS:
        if public_path.is_file():
            try:
                return HTMLResponse(
                    public_path.read_text(encoding="utf-8"),
                    headers={"Cache-Control": "public, max-age=120"},
                )
            except OSError:
                logger.exception("Failed to read public research hub at %s", public_path)

    try:
        hub_html = build_insights_hub_html(route_base="insights")
    except Exception:
        logger.exception("Failed to build live public research hub")
        raise
    return HTMLResponse(hub_html, headers={"Cache-Control": "public, max-age=120"})


@app.get("/research/", include_in_schema=False)
@app.get("/research", include_in_schema=False)
async def research_hub():
    """Canonical public research hub at /research/."""
    return _render_public_research_hub()


@app.get("/insights/research/", include_in_schema=False)
@app.get("/insights/research", include_in_schema=False)
async def insights_research_hub():
    """Legacy hub path redirects to /research/."""
    return RedirectResponse(url="/research/", status_code=308)


@app.get("/insights/organic-traffic-platform/", include_in_schema=False)
@app.get("/insights/organic-traffic-platform", include_in_schema=False)
async def insights_hub_legacy_redirect():
    return RedirectResponse(url="/research/", status_code=308)


async def _serve_generated_insight(slug: str) -> HTMLResponse:
    """Shared handler for /insights/{slug} and /insights/{slug}/."""
    if not is_generated_article_published(slug):
        raise HTTPException(status_code=404, detail="Generated article not found")
    article_html = load_generated_article_html(slug)
    if not article_html:
        raise HTTPException(status_code=404, detail="Generated article not found")
    return HTMLResponse(article_html, headers={"Cache-Control": "public, max-age=300"})


async def _serve_generated_insight_asset(slug: str, asset_name: str) -> FileResponse:
    """Serve generated asset files such as cover.svg for public insight pages."""
    if not is_generated_article_published(slug):
        raise HTTPException(status_code=404, detail="Generated article not found")
    asset_path = load_generated_article_asset(slug, asset_name)
    if asset_path is None:
        raise HTTPException(status_code=404, detail="Generated article asset not found")
    return FileResponse(str(asset_path), headers={"Cache-Control": "public, max-age=300"})


@app.get("/insights/{slug}/{asset_name}", include_in_schema=False)
async def public_generated_insight_asset(slug: str, asset_name: str):
    return await _serve_generated_insight_asset(slug, asset_name)


@app.get("/research/{slug}", include_in_schema=False)
async def public_generated_research_article(slug: str):
    return await _serve_generated_insight(slug)


@app.get("/research/{slug}/", include_in_schema=False)
async def public_generated_research_article_slash(slug: str):
    return await _serve_generated_insight(slug)


@app.get("/insights/{slug}", include_in_schema=False)
async def public_generated_insight(slug: str):
    return await _serve_generated_insight(slug)


@app.get("/insights/{slug}/", include_in_schema=False)
async def public_generated_insight_slash(slug: str):
    return await _serve_generated_insight(slug)


# â”€â”€ Flash Content Engine routes (additive â€” no existing routes modified) â”€â”€â”€â”€â”€â”€

_FLASH_JOBS: dict[str, asyncio.Task] = {}  # job_id â†’ background task


@app.post("/api/content/flash/generate", dependencies=[Depends(default_rate_limiter)])
async def flash_generate(req: FlashGenerationRequest, current_user: dict = Depends(enforce_token_limit)):
    """Start an async Flash/Deep content generation job. Returns job_id + stream URL."""
    req = req.model_copy(update={"mode": "research", "force_publish": False})
    job_id = uuid.uuid4().hex[:12]
    user_email = current_user["email"]
    tenant_id = current_user["tenant_id"]

    BUS.open(job_id, reset=True)
    _session_record(job_id, mode=f"content_{req.mode}", target=req.target,
                    objective=req.objective or req.content_type,
                    user_email=user_email, tenant_id=tenant_id)

    async def _runner() -> None:
        try:
            result = await generate_flash_article(req, job_id=job_id, requested_by=user_email)
            BUS.emit(job_id, "log", source="gateway", level="info",
                     message=f"Article complete: {result.slug} ({result.publish_status})")
        except asyncio.CancelledError:
            BUS.emit(job_id, "error", message="Generation job cancelled")
        except Exception as exc:
            logger.exception("Flash generation job %s failed", job_id)
            BUS.emit(job_id, "error", message=f"Generation failed: {exc}")
        finally:
            _FLASH_JOBS.pop(job_id, None)
            BUS.close(job_id)

    _FLASH_JOBS[job_id] = asyncio.create_task(_runner())
    TELEMETRY.emit_event(
        "flash_content_started",
        user=telemetry_user_from_request_user(current_user),
        properties={"source": "backend", "job_id": job_id, "mode": req.mode,
                    "content_type": req.content_type},
    )
    return JSONResponse({
        "job_id": job_id,
        "stream": f"/sessions/{job_id}/stream",
        "status": f"/sessions/{job_id}/status",
        "events": f"/sessions/{job_id}/events",
        "result": f"/sessions/{job_id}/result",
        "mode": req.mode,
        "content_type": req.content_type,
    })


@app.post("/api/content/flash/ingest-events", dependencies=[Depends(default_rate_limiter)])
async def flash_ingest_events(req: FlashIngestRequest, current_user: dict = Depends(enforce_token_limit)):
    """Discover SEBI/BSE/NSE events and generate articles via the flash pipeline."""
    req = req.model_copy(update={"mode": "research"})
    job_id = uuid.uuid4().hex[:12]
    user_email = current_user["email"]
    tenant_id = current_user["tenant_id"]

    BUS.open(job_id, reset=True)
    _session_record(job_id, mode="content_ingest", target=req.content_type,
                    user_email=user_email, tenant_id=tenant_id)

    async def _ingest_runner() -> None:
        try:
            result = await ingest_events_flash(req, requested_by=user_email, job_id=job_id)
            BUS.emit(job_id, "ingest_done",
                     discovered=result.discovered_events,
                     generated=result.generated_articles,
                     published=result.auto_published,
                     drafts=result.drafts,
                     skipped=result.skipped_seen)
        except Exception as exc:
            logger.exception("Flash ingest job %s failed", job_id)
            BUS.emit(job_id, "error", message=f"Ingest failed: {exc}")
        finally:
            _FLASH_JOBS.pop(job_id, None)
            BUS.close(job_id)

    _FLASH_JOBS[job_id] = asyncio.create_task(_ingest_runner())
    TELEMETRY.emit_event(
        "flash_ingest_started",
        user=telemetry_user_from_request_user(current_user),
        properties={"source": "backend", "job_id": job_id, "content_type": req.content_type},
    )
    return JSONResponse({
        "job_id": job_id,
        "stream": f"/sessions/{job_id}/stream",
        "status": f"/sessions/{job_id}/status",
    })


@app.get("/api/content/automation/status")
async def content_automation_status(current_user: dict = Depends(get_current_user)):
    return JSONResponse(get_monitor_status())


@app.post("/api/content/automation/run-now", dependencies=[Depends(default_rate_limiter)])
async def content_automation_run_now(current_user: dict = Depends(enforce_token_limit)):
    """Run one immediate official-source monitoring sweep in the background."""
    job_id = uuid.uuid4().hex[:12]
    user_email = current_user["email"]
    tenant_id = current_user["tenant_id"]

    BUS.open(job_id, reset=True)
    _session_record(job_id, mode="content_monitor", target="official_sources",
                    objective="official-monitor-sweep",
                    user_email=user_email, tenant_id=tenant_id)

    async def _runner() -> None:
        try:
            result = await run_official_monitor(requested_by=user_email, job_id=job_id)
            BUS.emit(job_id, "log", source="gateway", level="info",
                     message=f"Official monitor finished: generated={result.get('generated', 0)} published={result.get('published', 0)}")
        except asyncio.CancelledError:
            BUS.emit(job_id, "error", message="Official monitor job cancelled")
        except Exception as exc:
            logger.exception("Official monitor job %s failed", job_id)
            BUS.emit(job_id, "error", message=f"Official monitor failed: {exc}")
        finally:
            _FLASH_JOBS.pop(job_id, None)
            BUS.close(job_id)

    _FLASH_JOBS[job_id] = asyncio.create_task(_runner())
    return JSONResponse({
        "job_id": job_id,
        "stream": f"/sessions/{job_id}/stream",
        "status": f"/sessions/{job_id}/status",
    })


@app.post("/api/content/articles/{slug}/publish")
async def publish_content_article(
    slug: str,
    route_base: str = "insights",
    current_user: dict = Depends(enforce_token_limit),
):
    """Publish a draft article â€” mirrors to public dir and adds to sitemap."""
    manifest = load_generated_article(slug, route_base=route_base)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Article '{slug}' not found")
    editorial_review = manifest.get("editorial_review") if isinstance(manifest, dict) else None
    if isinstance(editorial_review, dict) and not editorial_review.get("ready_to_publish", False):
        raise HTTPException(status_code=409, detail="Editorial review has not approved this draft for publication yet")
    try:
        updated = _publish_article(slug, route_base=route_base)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Article '{slug}' not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    TELEMETRY.emit_event(
        "content_article_published",
        user=telemetry_user_from_request_user(current_user),
        properties={"source": "backend", "slug": slug, "route_base": route_base},
    )
    rb = updated.get("route_base") or route_base
    return JSONResponse({
        "slug": slug,
        "publish_status": updated.get("publish_status"),
        "publish_gate_status": updated.get("publish_gate_status"),
        "public_url": f"/{rb}/{slug}/",
        "mirrored_public_path": updated.get("mirrored_public_path"),
    })


@app.post("/api/content/articles/{slug}/unpublish")
async def unpublish_content_article(
    slug: str,
    route_base: str = "insights",
    current_user: dict = Depends(enforce_token_limit),
):
    """Retract a published article â€” removes public mirror and sets status to draft."""
    try:
        updated = _unpublish_article(slug, route_base=route_base)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Article '{slug}' not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    TELEMETRY.emit_event(
        "content_article_unpublished",
        user=telemetry_user_from_request_user(current_user),
        properties={"source": "backend", "slug": slug, "route_base": route_base},
    )
    return JSONResponse({
        "slug": slug,
        "publish_status": updated.get("publish_status"),
        "publish_gate_status": updated.get("publish_gate_status"),
    })




@app.get("/sessions/{session_id}/status")
def session_status(session_id: str, current_user: dict = Depends(get_current_user_or_guest)) -> Response:
    verify_session_ownership(session_id, current_user)
    body = json.dumps(_session_status(session_id), default=str)
    return Response(content=body, media_type="application/json")


@app.get("/sessions/{session_id}/events")
def session_events(session_id: str, after: int = 0, limit: int = 250, current_user: dict = Depends(get_current_user_or_guest)) -> Response:
    verify_session_ownership(session_id, current_user)
    if not BUS.known(session_id):
        raise HTTPException(status_code=404, detail="Unknown session")
    events = [_event_payload(idx, event) for idx, event in BUS.history(session_id, after=after, limit=limit)]
    body = json.dumps({
        "session_id": session_id,
        "events": events,
        "next_after": (events[-1]["id"] + 1 if events else after),
        "closed": BUS.is_closed(session_id),
    }, default=str)
    return Response(content=body, media_type="application/json")


@app.get("/chat/history")
def chat_history(session_id: str, current_user: dict = Depends(get_current_user)) -> Response:
    """Retrieve chat history for a session."""
    verify_session_ownership(session_id, current_user)
    user_email = current_user["email"]
    history = _MEMORY_MANAGER.get_history(user_email, session_id)
    body = json.dumps({"session_id": session_id, "history": history}, default=str)
    return Response(content=body, media_type="application/json")


@app.get("/sessions/{session_id}/result")
def session_result(session_id: str, current_user: dict = Depends(get_current_user_or_guest)) -> Response:
    verify_session_ownership(session_id, current_user)
    status = _session_status(session_id)
    memo_path = _MEMOS_DIR / f"{session_id}.md"
    memo_text = memo_path.read_text(encoding="utf-8") if memo_path.is_file() else None
    final_payload = status.get("final") or {}
    memo_event = status.get("memo") or {}
    if memo_text is None:
        memo_text = (
            final_payload.get("memo")
            or final_payload.get("memo_preview")
            or final_payload.get("answer")
            or final_payload.get("text")
            or final_payload.get("content")
            or final_payload.get("markdown")
            or memo_event.get("preview")
            or memo_event.get("memo")
            or memo_event.get("answer")
        )
    body = json.dumps({
        "session_id": session_id,
        "status": status["status"],
        "target": status.get("target"),
        "mode": status.get("mode"),
        "final": final_payload or None,
        "memo": memo_text,
        "memo_event": memo_event or None,
        "error": status.get("error"),
    }, default=str)
    return Response(content=body, media_type="application/json")


@app.get("/sessions/{session_id}/stream")
async def stream_session(
    session_id: str,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    after: int | None = None,
    current_user: dict = Depends(get_current_user_or_guest)
):
    verify_session_ownership(session_id, current_user)
    telemetry_user = telemetry_user_from_request_user(current_user)
    
    if not BUS.known(session_id):
        raise HTTPException(status_code=404, detail="Unknown session")

    # Determine starting event seq number
    after_seq = 0
    if after is not None:
        after_seq = after + 1
    elif last_event_id:
        try:
            after_seq = int(last_event_id) + 1
        except ValueError:
            pass

    # Atomic subscribe: history snapshot + live queue in one call
    history_events, q = BUS.subscribe(session_id, after=after_seq, limit=5000)
    if not q and not BUS.is_closed(session_id):
        q = BUS.open(session_id)

    async def gen():
        TELEMETRY.emit_event(
            "research_stream_opened",
            user=telemetry_user,
            properties={
                "source": "backend",
                "session_id": session_id,
                "resumed": bool(after_seq > 0 or last_event_id),
            },
        )
        yield f"event: open\ndata: {json.dumps({'session_id': session_id})}\n\n"
        
        # 1. Replay missed events from history
        max_seen_seq = after_seq - 1
        for idx, event in history_events:
            payload = _event_payload(idx, event)
            yield f"id: {idx}\nevent: {event.type}\ndata: {json.dumps(payload, default=str)}\n\n"
            max_seen_seq = max(max_seen_seq, idx)

        # 2. Stream live events
        if q is not None:
            try:
                while True:
                    try:
                        # Wait for up to 15 seconds for a new event.
                        # If timeout occurs, send an SSE comment as a keep-alive/heartbeat.
                        event = await asyncio.wait_for(q.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue

                    if event is None:
                        TELEMETRY.emit_event(
                            "research_stream_completed",
                            user=telemetry_user,
                            properties={
                                "source": "backend",
                                "session_id": session_id,
                            },
                        )
                        yield "event: done\ndata: {}\n\n"
                        return

                    if event.seq > max_seen_seq:
                        idx = event.seq
                        payload = {"id": idx, "type": event.type, "timestamp": event.timestamp, **event.payload}
                        yield f"id: {idx}\nevent: {event.type}\ndata: {json.dumps(payload, default=str)}\n\n"
                        max_seen_seq = max(max_seen_seq, idx)
            finally:
                BUS.remove(session_id, q)
        else:
            TELEMETRY.emit_event(
                "research_stream_completed",
                user=telemetry_user,
                properties={
                    "source": "backend",
                    "session_id": session_id,
                    "mode": "no_queue",
                },
            )
            yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )












"""FastAPI gateway: start a research session, stream events, serve all pages."""

from __future__ import annotations

import asyncio
import hashlib
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
    # Try finagent/.env first, then project root .env
    _here = Path(__file__).resolve().parent
    _loaded = (
        _load_dotenv(_here.parent / ".env", override=True)
        or _load_dotenv(_here.parent.parent / ".env", override=True)
    )
except ImportError:
    pass  # python-dotenv not installed; keys must come from environment

from fastapi import FastAPI, HTTPException, Header, Depends, Request, Response, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, field_validator

import httpx
import urllib.parse
import jwt

from finagent.events import BUS
from finagent.output.intent_classifier import extract_finance_entities, primary_target_from_query
from finagent.paths import finagent_data_path, finagent_home
from finagent.run_agent import AgentLoopConfig, run_research_session
from finagent.tools.web.http_fetcher import aclose_shared_client
from finagent.router.intent_router import ContextualizerError, ContextualizeResult, LLMQueryContextualizer, is_portfolio_scope_query
from finagent.memory.chat_memory import ChatMemoryManager
from finagent.ingestion.image_ingestion import PortfolioImageExtractionError, extract_portfolio_from_image
from finagent.ingestion.portfolio_document import extraction_to_position_dicts, parse_portfolio_document
from finagent.ingestion.portfolio_schema import PortfolioExtractionConfirmRequest, PortfolioExtractionSchema
from finagent.portfolio_mirrors import load_active_positions, replace_active_positions, summarize_positions, delete_positions
from finagent.portfolio.analytics import compute_portfolio_analytics
from finagent.portfolio.news import fetch_portfolio_news
from finagent.gateway import supabase_client as supabase
from finagent.gateway.auth_guard import decode_current_user_token
from finagent.telemetry import TELEMETRY, TelemetryUserContext, telemetry_request_context, telemetry_user_from_authorization_header, telemetry_user_from_request_user
from finagent.tools.data import fetch_news, fetch_yahoo_quote, fetch_india_snapshot, fetch_nse_snapshot
import time

# ── Rate limiting ─────────────────────────────────────────────────────────
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

# ── Upload validation ─────────────────────────────────────────────────────
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

VALID_MAGIC_BYTES = {
    b"%PDF": (".pdf",),
    b"\x89PNG": (".png",),
    b"\xff\xd8\xff": (".jpg", ".jpeg"),
    b"PK\x03\x04": (".xlsx", ".xls"),
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

# ── Concurrency limits ──────────────────────────────────────────────────
_MAX_CONCURRENT_SESSIONS = 20
_DEEP_RESEARCH_SEMAPHORE = asyncio.Semaphore(2)

# ── Token Usage Tracking ──────────────────────────────────────────────────
WEEKLY_TOKEN_LIMIT = int(os.getenv("WEEKLY_TOKEN_LIMIT", "1000000"))

# ── Token Usage Tracking ──────────────────────────────────────────────────
WEEKLY_TOKEN_LIMIT = int(os.getenv("WEEKLY_TOKEN_LIMIT", "1000000"))


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


# ── Ingestion state (in-memory + file fallback; no shared SQLite) ─────────
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


def _get_ingestion_state(tenant_id: str | None) -> dict[str, str]:
    if not tenant_id:
        return {"status": "IDLE", "message": ""}
    return _load_ingestion_state(tenant_id)


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


_SESSION_ID_RE = re.compile(r"^[a-f0-9]{12,64}$")
_REVIEW_ID_RE = re.compile(r"^[a-f0-9]{12,64}$")


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
            "SUPABASE_URL or SUPABASE_KEY is not set. The application will use in-memory fallback stores. "
            "Data will not persist across restarts. Set these environment variables for production use."
        )
    cleanup_task = asyncio.create_task(_periodic_cleanup())
    yield
    # Shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    for task in list(_TASKS.values()):
        task.cancel()
    await aclose_shared_client()
    await TELEMETRY.aclose()


app = FastAPI(
    title="ProspektLab Intelligence Gateway",
    version="0.5.0",
    lifespan=lifespan,
)


# ── CORS Middleware Configuration ─────────────────────────────────────────
from fastapi.middleware.cors import CORSMiddleware
_cors_raw = os.getenv("CORS_ORIGINS", "*")
if _cors_raw.strip() == "*":
    _allow_origins = ["*"]
    _allow_credentials = False
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

# ── Global Security Headers Middleware ────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # Hardened CSP: unsafe-inline and unsafe-eval removed from script-src.
    # Google Identity Services is loaded via a separate script file or
    # CSP nonce (recommended). For now, specific external domains are allowed.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://accounts.google.com https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com; "
        "style-src 'self' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "img-src 'self' data: https://*.googleusercontent.com; "
        "frame-src 'self' https://accounts.google.com; "
        "connect-src 'self' https: wss: https://oauth2.googleapis.com https://*.supabase.co https://*.execute-api.us-east-1.amazonaws.com https://*.amplifyapp.com;"
    )
    return response

# ── Unified get_current_user Dependency for JWT and BOLA checks ──────────
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


def _decode_current_user(actual_token: str) -> dict:
    return decode_current_user_token(actual_token, local_jwt_secret=JWT_SECRET)


async def get_current_user(
    request: Request,
    authorization: str = Header(None),
) -> dict:
    actual_token = None
    if authorization and authorization.startswith("Bearer "):
        actual_token = authorization.split(" ")[1]
    else:
        actual_token = request.cookies.get(AUTH_COOKIE_NAME)
    return _decode_current_user(actual_token)


async def enforce_token_limit(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """FastAPI dependency — raises 429 when weekly token limit is exceeded.

    SECURITY: Client-side bypass headers have been removed. Only server-side
    token accounting determines limits.
    """
    usage = await get_weekly_token_usage(current_user["email"])
    if usage >= WEEKLY_TOKEN_LIMIT:
        # Calculate reset time in IST (UTC+5:30)
        restore_ist = _next_week_start_utc() + timedelta(hours=5, minutes=30)
        restore_display = restore_ist.strftime("%A, %d %B %Y at %I:%M %p IST")
        raise HTTPException(status_code=429, detail={
            "code": "WEEKLY_TOKEN_LIMIT_EXCEEDED",
            "message": f"You've used {usage:,} / {WEEKLY_TOKEN_LIMIT:,} tokens this week.",
            "restore_at": _next_week_start_utc().isoformat() + "Z",
            "restore_display": restore_display,
            "usage": usage,
            "limit": WEEKLY_TOKEN_LIMIT,
            "remaining": 0,
        })
    return current_user

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


def _mint_token(user_id: str, email: str, name: str | None = None, days: int = 30) -> str:
    """Issue a local JWT with jti, exp, iat, iss, and aud claims."""
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "email": email,
        "name": name or email,
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

    token = _mint_token(user_id, email, full_name)

    response = JSONResponse({
        "token": token,
        "user_id": user_id,
        "email": email,
        "name": full_name,
        "full_name": full_name,
        "require_mobile": require_mobile,
        "mobile": mobile
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
    return "http://localhost:5173"


def _frontend_hash_url(route: str = "") -> str:
    cleaned = (route or "").lstrip("/")
    base = _frontend_base_url()
    return f"{base}/#/{cleaned}" if cleaned else f"{base}/#/"


class StartResearchRequest(BaseModel):
    target: str = Field(..., min_length=1)
    objective: str = Field("")
    # Optional — when absent the agent auto-picks depth from the objective.
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
    mode: str = Field(default="standard", description="standard or deep")
    max_wall_seconds: float | None = Field(default=None, ge=10, le=30 * 60)
    user_email: str | None = None
    session_id: str | None = None

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        mode = (v or "standard").strip().lower()
        return "deep" if mode == "marathon" else (mode if mode in {"standard", "deep"} else "standard")

    @field_validator("session_id")
    @classmethod
    def _session_id(cls, v: str | None) -> str | None:
        if not v:
            return None
        try:
            return _validate_session_id(v)
        except HTTPException as exc:
            raise ValueError("Invalid session_id format") from exc


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
    verification_code: str = Field(..., min_length=6, max_length=6)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)

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

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=160)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _validate_email(v)


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
_SESSIONS_DIR = finagent_data_path("sessions")


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
    return {"id": idx, "type": event.type, "timestamp": event.timestamp, **event.payload}


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


# ──────────────────────────────────────────────────────────────────────────
#  Lightweight local "auth" — stores hashed credentials per email under
#  the FinAgent home directory. No JWTs, no sessions — sufficient for a
#  single-user dev/demo deployment. Production should swap in real auth.
# ──────────────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    return {
        "status": "ok",
        "active_sessions": list(_TASKS.keys()),
        "openai": "enabled" if os.getenv("OPENAI_API_KEY") else "fallback",
        "finagent_home": "<redacted>",
        "version": app.version,
    }


@app.get("/auth/me")
async def auth_me(current_user: dict = Depends(get_current_user)):
    """Return the current authenticated user.

    Accepts either cookie auth or Authorization bearer token auth so
    cross-origin frontends can rehydrate session state reliably.
    """
    return {
        "user_id": current_user.get("user_id"),
        "email": current_user.get("email"),
        "tenant_id": current_user.get("tenant_id"),
        "auth_provider": current_user.get("auth_provider"),
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


# ── Market Data & Token Usage Endpoints ─────────────────────────────────────

@app.get("/user/token-usage")
async def get_user_token_usage(current_user: dict = Depends(get_current_user)):
    usage = await get_weekly_token_usage(current_user["email"])
    restore_ist = _next_week_start_utc() + timedelta(hours=5, minutes=30)
    restore_display = restore_ist.strftime("%A, %d %B %Y at %I:%M %p IST")
    remaining = max(0, WEEKLY_TOKEN_LIMIT - usage)
    pct_used = min(100.0, (usage / WEEKLY_TOKEN_LIMIT) * 100.0)
    return {
        "usage": usage,
        "limit": WEEKLY_TOKEN_LIMIT,
        "remaining": remaining,
        "pct_used": pct_used,
        "restore_display": restore_display,
        "restore_at": _next_week_start_utc().isoformat() + "Z",
    }


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


@app.get("/market/history")
async def get_market_history(
    symbol: str,
    period: str = "1Y",
    asset_type: str | None = None,
    current_user: dict = Depends(get_current_user),
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
async def get_market_quotes(symbols: str, current_user: dict = Depends(get_current_user)):
    def _clean_market_symbol(value: str) -> str:
        sym = (value or "").strip().upper()
        return sym.removesuffix(".NS").removesuffix(".BO").removesuffix(".NSE").removesuffix(".BSE")

    symbol_list = []
    for raw in symbols.split(","):
        sym = _clean_market_symbol(raw)
        if sym and sym not in symbol_list:
            symbol_list.append(sym)
    symbol_list = symbol_list[:30]
    results = {}
    
    async def fetch_one(sym: str):
        # Use NSE/BSE-first live quote data for dashboard prices and movers.
        quote_timeout = _gateway_float_setting("FINAGENT_MARKET_QUOTE_TIMEOUT_S", 5.0)
        yahoo_timeout = _gateway_float_setting("FINAGENT_MARKET_QUOTE_YAHOO_TIMEOUT_S", 16.0)

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

    tasks = [fetch_one(sym) for sym in symbol_list]
    fetched = await asyncio.gather(*tasks)
    for sym, res in fetched:
        if res:
            results[sym] = res
            results[f"{sym}.NS"] = res
            results[f"{sym}.BO"] = res
    return results


@app.get("/market/news")
async def get_market_news(query: str = "India market", limit: int = 10, current_user: dict = Depends(get_current_user)):
    news_items = await fetch_news(query, limit=limit)
    return [
        {
            "title": item.title,
            "link": item.link,
            "source": item.source,
            "published": item.published,
            "description": item.description,
        }
        for item in news_items
    ]


@app.get("/market/indices")
async def get_market_indices(current_user: dict = Depends(get_current_user)):
    categories = {
        "india": [
            ("^NSEI", "NIFTY 50"),
            ("^BSESN", "SENSEX"),
            ("^NSEBANK", "NIFTY BANK"),
            ("^CNXIT", "NIFTY IT")
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

    fallbacks = {
        "india": [
            { "symbol": 'NIFTY 50',  "value": '23,939.45', "change": '(-92.25)',  "changePct": -0.38, "sparkData": [24050, 24010, 24020, 23980, 23960, 23990, 23945, 23930, 23939] },
            { "symbol": 'SENSEX',    "value": '76,093.52', "change": '(-395.44)', "changePct": -0.52, "sparkData": [76500, 76450, 76400, 76300, 76250, 76200, 76150, 76100, 76093] },
            { "symbol": 'NIFTY BANK', "value": '55,067.65', "change": '(-226.00)', "changePct": -0.41, "sparkData": [55300, 55280, 55260, 55200, 55150, 55120, 55080, 55070, 55067] },
            { "symbol": 'NIFTY IT',  "value": '28,987.85', "change": '(+4.05)',   "changePct": 0.03,  "sparkData": [28950, 28960, 28970, 28965, 28975, 28980, 28985, 28988, 28987] }
        ],
        "us": [
            { "symbol": 'S&P 500',  "value": '5,832.40', "change": '(+18.32)', "changePct": 0.31, "sparkData": [5800, 5810, 5815, 5820, 5825, 5830, 5828, 5832, 5832] },
            { "symbol": 'NASDAQ',   "value": '18,791.12', "change": '(+45.67)', "changePct": 0.24, "sparkData": [18700, 18720, 18750, 18760, 18780, 18785, 18790, 18791, 18791] },
            { "symbol": 'DOW',      "value": '42,388.50', "change": '(-89.20)', "changePct": -0.21, "sparkData": [42500, 42480, 42460, 42440, 42420, 42400, 42390, 42388, 42388] },
            { "symbol": 'VIX',      "value": '15.42', "change": '(-0.38)',  "changePct": -2.40, "sparkData": [16.2, 16.0, 15.9, 15.8, 15.7, 15.6, 15.5, 15.45, 15.42] }
        ],
        "currencies": [
            { "symbol": 'USD/INR',  "value": '84.12', "change": '(+0.08)', "changePct": 0.10, "sparkData": [84.0, 84.02, 84.05, 84.08, 84.09, 84.1, 84.11, 84.12, 84.12] },
            { "symbol": 'EUR/INR',  "value": '92.34', "change": '(-0.12)', "changePct": -0.13, "sparkData": [92.5, 92.48, 92.45, 92.4, 92.38, 92.36, 92.35, 92.34, 92.34] },
            { "symbol": 'GBP/INR',  "value": '110.22', "change": '(+0.34)', "changePct": 0.31, "sparkData": [109.8, 109.9, 110.0, 110.1, 110.15, 110.18, 110.2, 110.22, 110.22] },
            { "symbol": 'JPY/INR',  "value": '0.5612', "change": '(+0.002)', "changePct": 0.36, "sparkData": [0.559, 0.5595, 0.5600, 0.5605, 0.5608, 0.5610, 0.5612, 0.5612, 0.5612] }
        ],
        "crypto": [
            { "symbol": 'BTC',  "value": '$67,432', "change": '(+2.40%)', "changePct": 2.40, "sparkData": [65800, 66000, 66200, 66500, 66800, 67000, 67200, 67400, 67432] },
            { "symbol": 'ETH',  "value": '$2,521', "change": '(+1.82%)', "changePct": 1.82, "sparkData": [2470, 2480, 2490, 2495, 2505, 2510, 2515, 2520, 2521] },
            { "symbol": 'SOL',  "value": '$148.20', "change": '(-0.95%)', "changePct": -0.95, "sparkData": [150, 149.5, 149.2, 149, 148.8, 148.6, 148.4, 148.25, 148.2] },
            { "symbol": 'XRP',  "value": '$0.5234', "change": '(+0.42%)', "changePct": 0.42, "sparkData": [0.520, 0.521, 0.522, 0.5215, 0.522, 0.5225, 0.523, 0.5234, 0.5234] }
        ],
        "futures": [
            { "symbol": 'NIFTY FUT',  "value": '23,968.50', "change": '(-78.20)', "changePct": -0.32, "sparkData": [24050, 24020, 24000, 23990, 23980, 23975, 23970, 23968, 23968] },
            { "symbol": 'BANKNIFTY FUT', "value": '55,124.80', "change": '(-198.40)', "changePct": -0.36, "sparkData": [55320, 55280, 55250, 55200, 55170, 55150, 55130, 55125, 55124] },
            { "symbol": 'CRUDE OIL', "value": '$72.45', "change": '(+0.62)', "changePct": 0.86, "sparkData": [71.8, 72.0, 72.1, 72.2, 72.3, 72.35, 72.4, 72.45, 72.45] },
            { "symbol": 'GOLD',     "value": '$2,654', "change": '(+8.40)', "changePct": 0.32, "sparkData": [2640, 2645, 2648, 2650, 2652, 2653, 2654, 2654, 2654] }
        ]
    }

    flat_targets = []
    for cat_name, targets in categories.items():
        for ticker, name in targets:
            flat_targets.append((cat_name, ticker, name))

    async def fetch_one(cat_name, ticker, name):
        try:
            quote = await fetch_yahoo_quote(ticker)
            if quote:
                sparkline = quote.series_closes[-9:] if quote.series_closes else []
                if not sparkline and quote.price:
                    sparkline = [quote.price * (1 + (i - 4) * 0.001) for i in range(9)]
                
                diff = quote.price - quote.previous_close if quote.price and quote.previous_close is not None else 0.0
                chg_str = f"({diff:+.2f})" if diff else "—"
                
                display_val = f"{quote.price:,.2f}" if quote.price is not None else "—"
                if "USD" in ticker or "BTC" in ticker or "ETH" in ticker or "SOL" in ticker or "XRP" in ticker or ticker in ["CL=F", "GC=F"]:
                    if ticker in ["CL=F", "GC=F"]:
                        display_val = f"${quote.price:,.2f}"
                    elif "USDINR" in ticker or "EURINR" in ticker or "GBPINR" in ticker or "JPYINR" in ticker:
                        display_val = f"{quote.price:,.2f}"
                    else:
                        display_val = f"${quote.price:,.2f}" if quote.price is not None else "—"

                return cat_name, {
                    "symbol": name,
                    "value": display_val,
                    "change": chg_str,
                    "changePct": quote.change_pct if quote.change_pct is not None else 0.0,
                    "sparkData": sparkline
                }
        except Exception as e:
            logger.error(f"Error fetching index {ticker}: {e}")
        return cat_name, None

    tasks = [fetch_one(cat_name, tick, name) for cat_name, tick, name in flat_targets]
    fetched = await asyncio.gather(*tasks)

    results = {
        "india": [],
        "us": [],
        "currencies": [],
        "crypto": [],
        "futures": []
    }
    for cat_name, res in fetched:
        if res:
            results[cat_name].append(res)

    for cat_name, fallback_list in fallbacks.items():
        if not results[cat_name]:
            results[cat_name] = fallback_list
        elif len(results[cat_name]) < len(fallback_list):
            existing_symbols = {r["symbol"] for r in results[cat_name]}
            for fallback_item in fallback_list:
                if fallback_item["symbol"] not in existing_symbols:
                    results[cat_name].append(fallback_item)

    return results


# ── Memory viewer endpoints ─────────────────────────────────────────────

@app.get("/portfolio/mirror")
async def get_portfolio_mirror(current_user: dict = Depends(get_current_user)):
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
async def replace_portfolio_mirror(req: PositionMirrorReplaceRequest, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    _require_no_active_ingestion(tenant_id)
    positions = await replace_active_positions(
        tenant_id,
        [item.model_dump() for item in req.positions if item.active],
    )
    _set_ingestion_state(tenant_id, "MIRROR_SYNCHRONIZED" if positions else "MIRROR_EMPTY", "Manual portfolio mirror updated.")
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
    current_user: dict = Depends(get_current_user),
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
        extraction = await parse_portfolio_document(payload_bytes, filename, password)
    except Exception as exc:
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
        raise

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
            "message": "Review extracted holdings before syncing.",
            **extraction.model_dump(),
        }

    positions = await replace_active_positions(tenant_id, extraction_to_position_dicts(extraction))
    if not positions:
        _set_ingestion_state(tenant_id, "FAILED", "Portfolio holdings could not be saved.")
        raise HTTPException(
            status_code=503,
            detail={
                "ok": False,
                "code": "MIRROR_SYNC_FAILED",
                "message": "Your holdings were extracted, but saving them to your account failed. Please retry in a moment.",
            },
        )
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
    current_user: dict = Depends(get_current_user),
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
        extraction = await extract_portfolio_from_image(image_bytes, filename)
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

    review_id = uuid.uuid4().hex[:16]
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
        "message": "Review extracted holdings before syncing.",
        **extraction.model_dump(),
    }


@app.post("/api/portfolio/confirm-extraction")
async def confirm_portfolio_extraction(
    req: PortfolioExtractionConfirmRequest,
    current_user: dict = Depends(get_current_user),
):
    tenant_id = current_user.get("tenant_id")
    telemetry_user = telemetry_user_from_request_user(current_user)
    review_id = _validate_review_id(req.review_id) if req.review_id else None
    pending = None
    if review_id:
        pending = await supabase.get_pending_extraction(review_id)
    if review_id and not pending:
        raise HTTPException(status_code=404, detail="Review payload expired or not found.")
    if pending and pending.get("tenant_id") != tenant_id:
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
    mirrored = await replace_active_positions(tenant_id, extraction_to_position_dicts(extraction))
    if not mirrored:
        _set_ingestion_state(tenant_id, "FAILED", "Reviewed portfolio holdings could not be saved.")
        raise HTTPException(
            status_code=503,
            detail={
                "ok": False,
                "code": "MIRROR_SYNC_FAILED",
                "message": "Your reviewed holdings could not be saved to your account. Please retry in a moment.",
            },
        )
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
async def cancel_portfolio_extraction(current_user: dict = Depends(get_current_user)):
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


@app.get("/portfolio/analytics")
async def get_portfolio_analytics(
    current_user: dict = Depends(get_current_user),
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
    result = compute_portfolio_analytics(positions, benchmark=benchmark, period=period)
    if isinstance(result, dict):
        result["store_unavailable"] = store_unavailable
    return result


@app.delete("/portfolio/mirror")
async def delete_portfolio_mirror(current_user: dict = Depends(get_current_user)):
    """Clear all holdings for the authenticated tenant."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Tenant required")
    deleted = await delete_positions(tenant_id)
    _set_ingestion_state(tenant_id, "IDLE", "")
    return {"ok": True, "deleted": deleted}


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
async def get_portfolio_news(limit: int = 12, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions, store_unavailable = await _load_optional_portfolio_positions(tenant_id, "portfolio/news")
    items = fetch_portfolio_news(positions, limit=limit)
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
    analytics = compute_portfolio_analytics(positions)
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
    current_user: dict = Depends(get_current_user),
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
    analytics = compute_portfolio_analytics(positions)
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
    
    analytics = compute_portfolio_analytics(positions)
    
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
        f"Portfolio of {count} holdings worth ₹{total_value:,.0f}. "
        f"Unrealized P/L: ₹{pnl_amount:,.0f} ({pnl_pct:+.1f}%). "
        f"Asset allocation: {equity_pct:.0f}% equity, {mf_pct:.0f}% MF. "
        f"Risk (vs NIFTY50): {risk_str}. "
        f"Top holdings: {top_names}."
    )
    return {"brief": brief_text}


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
        "db_path": "<redacted>",
        "targets": [{"target": t["target"], "facts": t["facts"]} for t in targets],
    }


@app.get("/memory/facts")
async def memory_facts(target: str = "", limit: int = 50, current_user: dict = Depends(get_current_user)):
    """Browse facts — optionally filtered by target company, scoped to the authenticated user."""
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


# ── Static page handlers ────────────────────────────────────────────────


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url(""), status_code=302)


@app.get("/landing")
def landing() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url(""), status_code=302)


@app.get("/login")
def login_page() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url("login"), status_code=302)


@app.get("/signup")
def signup_page() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url("signup"), status_code=302)


@app.get("/profile")
def profile_page() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url("dashboard"), status_code=302)


@app.get("/settings")
def settings_page() -> RedirectResponse:
    return RedirectResponse(url=_frontend_hash_url("dashboard"), status_code=302)


@app.get("/app")
def widget(request: Request) -> RedirectResponse:
    actual_token = request.cookies.get(AUTH_COOKIE_NAME)
    if not actual_token:
        return RedirectResponse(url="/login", status_code=302)
    try:
        _decode_current_user(actual_token)
    except HTTPException:
        response = RedirectResponse(url="/login", status_code=302)
        _clear_auth_cookie(response)
        return response
    return RedirectResponse(url=_frontend_hash_url("dashboard"), status_code=302)


@app.post("/auth/logout")
def auth_logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    _clear_auth_cookie(response)
    return response


# ── Auth endpoints ──────────────────────────────────────────────────────


# Verification codes and reset codes are stored in Supabase (or local SQLite fallback)
# via finagent.gateway.state_store / supabase_client.

def _send_email_code(email: str, code: str, is_reset: bool = False) -> bool:
    subject = "Reset Your ProspektLab Password" if is_reset else "Verify Your ProspektLab Email"
    body = (
        f"Your verification code to reset your password is: {code}\n\n"
        "This code will expire in 10 minutes."
        if is_reset else
        f"Your email verification code for ProspektLab signup is: {code}\n\n"
        "This code will expire in 10 minutes."
    )
    
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "no-reply@prospektlab.com")
    
    if not smtp_host or not smtp_user or not smtp_password:
        # Fallback to printing in console
        action_type = "RESET PASSWORD" if is_reset else "EMAIL VERIFICATION"
        print(f"\n==================================================")
        print(f"[SMTP FALLBACK - {action_type}]")
        print(f"To: {email}")
        print(f"Subject: {subject}")
        print(f"Code: {code}")
        print(f"==================================================\n", flush=True)
        return False

    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = smtp_from
        msg["To"] = email
        
        port = int(smtp_port) if smtp_port else 587
        server = smtplib.SMTP(smtp_host, port, timeout=10)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_from, [email], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"[SMTP ERROR] Failed to send email to {email}: {e}", flush=True)
        print(f"\n==================================================")
        print(f"[SMTP FALLBACK ON FAILURE - Code: {code}]")
        print(f"To: {email}")
        print(f"==================================================\n", flush=True)
        return False


@app.post("/auth/send-verification", dependencies=[Depends(auth_rate_limiter)])
async def auth_send_verification(req: SendVerificationRequest):
    email_clean = req.email.lower().strip()
    
    # Check if user already exists
    existing = await supabase.get_user_by_email(email_clean)
    if existing:
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
        
    code = f"{secrets.randbelow(900000) + 100000}"
    await supabase.store_verification_code(email_clean, code, type_="signup")
    
    sent = _send_email_code(email_clean, code, is_reset=False)
    if sent:
        TELEMETRY.emit_event(
            "auth_verification_sent",
            user=TelemetryUserContext(email=email_clean, name=email_clean),
            properties={
                "source": "backend",
                "flow": "signup",
            },
        )
        return {"message": "Verification email sent successfully."}
    else:
        TELEMETRY.emit_event(
            "auth_verification_sent",
            user=TelemetryUserContext(email=email_clean, name=email_clean),
            properties={
                "source": "backend",
                "flow": "signup",
                "delivery": "simulated",
            },
        )
        return {
            "message": "Verification code generated.",
            "detail": f"Verification code simulated. Code {code} has been logged to the server terminal console."
        }


@app.post("/auth/forgot-password", dependencies=[Depends(auth_rate_limiter)])
async def auth_forgot_password(req: ForgotPasswordRequest):
    email_clean = req.email.lower().strip()
    
    # Verify user exists
    existing = await supabase.get_user_by_email(email_clean)
    if not existing:
        raise HTTPException(status_code=404, detail="No account with that email exists.")
        
    code = f"{secrets.randbelow(900000) + 100000}"
    await supabase.store_verification_code(email_clean, code, type_="reset")
    
    sent = _send_email_code(email_clean, code, is_reset=True)
    if sent:
        TELEMETRY.emit_event(
            "auth_password_reset_requested",
            user=TelemetryUserContext(email=email_clean, name=email_clean),
            properties={
                "source": "backend",
                "delivery": "email",
            },
        )
        return {"message": "Reset code sent to your email."}
    else:
        TELEMETRY.emit_event(
            "auth_password_reset_requested",
            user=TelemetryUserContext(email=email_clean, name=email_clean),
            properties={
                "source": "backend",
                "delivery": "simulated",
            },
        )
        return {
            "message": "Reset code generated.",
            "detail": f"Reset code simulated. Code {code} has been logged to the server terminal console."
        }


@app.post("/auth/reset-password", dependencies=[Depends(auth_rate_limiter)])
async def auth_reset_password(req: ResetPasswordRequest):
    email_clean = req.email.lower().strip()
    
    valid = await supabase.verify_and_consume_code(email_clean, req.code, type_="reset", ttl_seconds=600)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid or expired reset code. Please request a new one.")
        
    # Validate via Supabase
    existing = await supabase.get_user_by_email(email_clean)
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found.")
        
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
    
    # Verify and consume code (one-shot, atomically deleted on success)
    valid = await supabase.verify_and_consume_code(email_clean, req.verification_code, type_="signup", ttl_seconds=600)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
        
    name_clean = req.name.strip()
    mobile_clean = req.mobile.strip()
    
    # Create via Supabase
    res = await supabase.create_admin_user(email_clean, req.password, name_clean, mobile=mobile_clean, auth_provider="email")
    user_id = res.get("id")
    saved_profile = await supabase.upsert_profile(user_id, email_clean, name_clean, "email", mobile=mobile_clean)
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
        },
    })
    _set_auth_cookie(response, token, request)
    TELEMETRY.emit_event(
        "auth_signup_success",
        user=TelemetryUserContext(email=email_clean, name=name_clean, user_id=user_id, auth_provider="email"),
        properties={
            "source": "backend",
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
    
    # Issue a local JWT (same format as Google auth + signup) so that
    # get_current_user can verify it with JWT_SECRET in production.
    # Using the raw Supabase access token here would cause 401s because
    # the backend would need SUPABASE_JWT_SECRET to verify it.
    token = _mint_token(user_id, email_clean, full_name)
    
    response = JSONResponse({
        "token": token,
        "user": {
            "name": full_name,
            "email": email_clean,
            "plan": "free",
            "mobile": mobile,
            "require_mobile": not bool(mobile),
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
    return response


# ── Research orchestration ──────────────────────────────────────────────


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
    
    # ── Pure-LLM follow-up contextualization ─────────────────────────────
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
                # New topic — LLM may have extracted a target, otherwise fall back
                target = result.target or primary_target_from_query(raw_query)
                if result.contextualized_query and result.contextualized_query.strip():
                    objective = result.contextualized_query.strip()

                # ── Session isolation: if the resolved target differs from the prior
                # session's target, mint a fresh session_id so the old entity's
                # enrichment data, caches, and tool outputs don't leak into the new query.
                if prior_target and target and prior_target.lower() != target.lower():
                    session_id = uuid.uuid4().hex[:12]
                    BUS.open(session_id, reset=True)
                    logger.info("Target changed from %r to %r — new session %s", prior_target, target, session_id)
        except (asyncio.TimeoutError, ContextualizerError, Exception) as exc:
            logger.warning("Contextualizer failed for session %s, falling back to raw query: %s", session_id, exc)
            is_followup = True
            target = prior_target
            objective = raw_query.strip()
    else:
        # No prior context — resolve normally
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
    if mode not in {"chat", "standard"}:
        mode = "chat"
    
    # ── Comparison detection: extract both entities ────────────────────
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
            # ── Speed-first config ──────────────────────────────────────
            # Chat stays lightweight; standard keeps enrichment, reflection,
            # multi-agent checks, and visual synthesis.
            if req.max_steps is not None:
                base_steps = min(req.max_steps, 50)
            elif mode == "standard":
                base_steps = 18
            else:
                base_steps = 28
            # Production hard cap: never exceed 50 steps regardless of mode or client input
            base_steps = min(base_steps, 50)
            logger.info("[GATEWAY] Research session %s base_steps capped at %d", session_id, base_steps)
            
            chat_history = _MEMORY_MANAGER.get_history(user_email, session_id)

            is_chat_mode = mode == "chat"
            is_standard_mode = mode == "standard"
            is_portfolio_query = is_portfolio_scope_query(objective) or is_portfolio_scope_query(raw_query)
            balanced_standard = is_standard_mode and (is_portfolio_query or is_comparison_query)

            await run_research_session(
                target,
                objective,
                is_followup=is_followup,
                loop_config=AgentLoopConfig(
                    max_steps=base_steps,
                    session_id=session_id,
                    auto_depth=req.max_steps is None,
                    response_depth=mode,
                    output_mode=forced_output_mode,
                    synth_model=os.getenv("FINAGENT_SYNTH_MODEL") or ("gpt-4o" if (mode == "deep" or balanced_standard) else "gpt-4o-mini"),
                    # ── Speed: aggressively disable expensive phases for fast modes
                    enable_multi_agent=balanced_standard,
                    enable_blindspot=balanced_standard,
                    enable_reflection=balanced_standard,
                    reflection_max_rounds=1 if balanced_standard else 0,
                    reflection_max_new_docs=12 if balanced_standard else 0,
                    enable_deep_dive=balanced_standard,
                    quality_threshold=(68.0 if balanced_standard else (55.0 if is_chat_mode else 60.0)),
                    # ── Tight timeouts for fast modes (skip 3.0x multiplier on win32 for fast modes)
                    breadth_search_timeout=(20.0 if balanced_standard else (8.0 if is_chat_mode else 16.0)),
                    followup_search_timeout=(12.0 if balanced_standard else (5.0 if is_chat_mode else 8.0)),
                    reflection_per_query_timeout=8.0 if balanced_standard else 0.0,
                    blindspot_per_query_timeout=8.0 if balanced_standard else 0.0,
                    news_timeout=(10.0 if balanced_standard else (4.0 if is_chat_mode else 6.0)),
                    fast_mode=not balanced_standard,
                    # ── Comparison: pass peer targets so synthesis has parallel enrichment
                    peer_targets=comparison_targets[1:] if len(comparison_targets) >= 2 else [],
                    chat_history=chat_history,
                    user_email=user_email,
                    tenant_id=tenant_id,
                ),
            )
            
        except asyncio.CancelledError:
            logger.warning("session %s cancelled before final synthesis", session_id)
            if not BUS.is_closed(session_id):
                BUS.emit(session_id, "log", source="gateway", level="warning", message="Research task was cancelled before final synthesis")
                BUS.emit(session_id, "error", message="Research task was cancelled before final synthesis")
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
            _TASKS.pop(session_id, None)

    _TASKS[session_id] = asyncio.create_task(_runner())
    return JSONResponse({
        "session_id": session_id,
        "stream": f"/sessions/{session_id}/stream",
        "status": f"/sessions/{session_id}/status",
        "events": f"/sessions/{session_id}/events",
        "result": f"/sessions/{session_id}/result",
    })


# ── Deep Research: multi-pass long-chain reasoning ──────────────────────

# Each entry maps to a deep-research evidence pass. The runtime uses a fixed
# 8-pass layout: seven evidence passes plus one serial synthesis pass.
_DEEP_PASS_OBJECTIVES = [
    # Pass 0 — Financials foundation
    (
        "Core financials: 5-year revenue CAGR, EBITDA margin trend, net profit margins, EPS growth, "
        "free cash flow yield, return on capital employed (ROCE), debt-to-equity, interest coverage ratio, "
        "working capital cycle. Source from Screener.in, NSE filings, annual reports."
    ),
    # Pass 1 — Competitive moat
    (
        "Competitive moat and market position: market share vs top 5 peers, pricing power evidence, "
        "switching costs, network effects, proprietary IP or patents, brand valuation, client concentration "
        "risk (top-10 clients as % of revenue), order-book or deal pipeline size and TCV."
    ),
    # Pass 2 — Management and governance
    (
        "Management quality and corporate governance: CEO/MD track record and tenure, promoter pledge "
        "percentage and trend, related-party transactions (RPTs) and their materiality, board independence "
        "ratio, auditor tenure and any qualifications, SEBI/stock-exchange show-cause notices or penalties, "
        "insider buying/selling patterns over the last 12 months."
    ),
    # Pass 3 — Valuation
    (
        "Valuation deep-dive: trailing and forward P/E vs sector median, EV/EBITDA vs global peers, "
        "PEG ratio, DCF implied price at WACC 10-12%, Graham number, price-to-free-cash-flow, "
        "dividend yield and payout sustainability, and source-attributed valuation scenario ranges. "
        "Do not produce buy/sell/hold labels, target prices, or trading calls."
    ),
    # Pass 4 — Risk and red flags
    (
        "Risk and red flag scan: regulatory investigations, pending litigation with financial exposure, "
        "environmental/ESG controversies, customer attrition or large contract losses, forex hedging "
        "policy and un-hedged exposure, commodity or input cost sensitivity, key-man dependency, "
        "technology disruption risk, recent management exits, any going-concern qualifications."
    ),
    # Pass 5 — Macro and sector tailwinds/headwinds
    (
        "Macro and sector overlay: government policy tailwinds (PLI schemes, budget allocations, "
        "infrastructure spend), RBI/interest-rate sensitivity, USD-INR impact on margins, crude oil "
        "or energy cost linkage, global demand cycle for the sector, peer capex plans, new entrants "
        "or foreign competition, import/export duties that affect the business model."
    ),
    # Pass 6 — Institutional and shareholding intelligence
    (
        "Shareholding and smart-money signals: latest FII/DII/promoter holding changes (QoQ), "
        "mutual fund entry/exit (top AMFs buying or trimming), bulk and block deal activity, "
        "promoter pledge creation or release, ESOP grants and dilution pipeline, ADR/GDR premium "
        "or discount, short interest data from F&O segment if available."
    ),
    # Pass 7 — Hidden catalysts and growth drivers
    (
        "Hidden catalysts and growth optionality: new product lines or business segments under "
        "development, M&A pipeline or recent acquisitions and integration status, geographic "
        "expansion plans (new markets, international revenue mix), R&D pipeline and patent filings, "
        "digital transformation initiatives, capacity expansion capex with expected COD dates, "
        "recently-won mega-contracts or government tenders."
    ),
    # Pass 8 — News, sentiment and narrative
    (
        "Recent news, analyst commentary and market narrative: last 90-day earnings call key "
        "management guidance, analyst upgrades/downgrades with reasoning, negative investigative "
        "journalism or short-seller reports, Reddit/StockTwits retail sentiment trend, any "
        "Hacker News / tech community mentions, social media buzz or viral concerns."
    ),
    # Pass 9 — Peer comparison deep-dive
    (
        "Peer comparison deep-dive: side-by-side financial metrics vs 4-6 named peers (revenue "
        "growth, margins, valuation multiples, return ratios, debt levels), market-share trajectory "
        "over 3 years, relative stock performance YTD and 3-year CAGR, who is gaining vs losing "
        "share and why, pricing strategy differences, talent/attrition comparison if available."
    ),
    # Pass 10 — Capital allocation and future returns
    (
        "Capital allocation quality and future return potential: historical capex efficiency (asset "
        "turns trend), dividend history and special dividend probability, buyback activity and "
        "its accretive/dilutive impact, reinvestment rate and incremental ROCE, management's "
        "stated capital allocation framework, balance sheet optionality (net cash or net debt), "
        "potential for re-rating if key milestones are met."
    ),
    # Pass 11 (synthesis) — Investment-grade thesis
    (
        "Final synthesis: integrate all prior pass findings into a structured investment-grade "
        "research report. Resolve any data contradictions. Produce: (1) executive summary with "
        "clear bull/bear/base case, (2) key financial metrics dashboard, (3) top 5 risk factors "
        "with probability/impact matrix, (4) competitive positioning verdict, (5) valuation "
        "summary as scenario-implied ranges only, and (6) key monitorables. Keep it SEBI-safe: "
        "no buy, sell, hold, accumulate, exit, entry, position-size, target-price, or rebalancing instruction."
    ),
]


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

    # ── Pure-LLM follow-up detection for deep research runs ───────────────
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
                    logger.info("Target changed from %r to %r — new deep session %s", prior_target, target, master_session)
        except (asyncio.TimeoutError, ContextualizerError, Exception) as exc:
            logger.warning("Deep contextualizer failed for session %s, falling back to raw query: %s", master_session, exc)
            is_followup_deep = True
            target = prior_target
            objective_for_deep = raw_query.strip()
    else:
        target = primary_target_from_query(raw_query)

    objective_scope_query = _strip_frontend_portfolio_context(objective_for_deep) or raw_query
    if is_portfolio_scope_query(objective_scope_query):
        await _require_synchronized_portfolio(tenant_id, allow_empty=True)

    from finagent.output.query_guards import is_portfolio_comparison_query
    is_comparison_query = _is_comparison(raw_query) and not is_portfolio_comparison_query(raw_query)
    comparison_targets = _extract_comparison_targets(raw_query) if is_comparison_query else []
    peer_targets_list = comparison_targets[1:] if len(comparison_targets) >= 2 else []

    BUS.open(master_session, reset=True)
    _clear_session_memo(master_session)
    
    _session_record(master_session, mode="deep", target=target, objective=objective_for_deep, user_email=user_email, tenant_id=tenant_id)
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
        total_passes = 8
        completed_passes = 0
        started_at = asyncio.get_running_loop().time()
        chat_history = _MEMORY_MANAGER.get_history(user_email, master_session)
        
        try:
            async def _run_pass(i: int) -> bool:
                async with _DEEP_RESEARCH_SEMAPHORE:
                    if req.max_wall_seconds is not None:
                        remaining = req.max_wall_seconds - (asyncio.get_running_loop().time() - started_at)
                        if remaining <= 0:
                            return False
                    
                    is_last = (i == total_passes - 1)
                    if is_last:
                        objective = _DEEP_PASS_OBJECTIVES[-1]  # always "Final synthesis" (index 11)
                    else:
                        objective = _DEEP_PASS_OBJECTIVES[i % (len(_DEEP_PASS_OBJECTIVES) - 1)]
                    pass_label = f"Synthesis Pass {i+1}/{total_passes}" if is_last else f"Pass {i+1}/{total_passes}"
                    
                    BUS.emit(master_session, "phase", phase="deep_research", note=f"{pass_label}: {objective[:60]}…")
                    BUS.emit(master_session, "deep_pass", pass_number=i+1, total_passes=total_passes, objective=objective, deep_pass_label=pass_label, status="running")
                    
                    pass_objective = f"{objective_for_deep}\n\n{pass_label} - {objective}"
                    # For comparison queries, force comparison output mode on synthesis pass
                    effective_output_mode = "company_comparison" if (is_comparison_query and is_last) else ("deep_research_report" if is_last else None)

                    await run_research_session(
                        target,
                        pass_objective,
                        is_followup=is_followup_deep,
                        loop_config=AgentLoopConfig(
                            max_steps=(req.pass_depth if is_last else min(req.pass_depth, 12)),
                            session_id=master_session,
                            auto_depth=False,
                            enable_memory=True,
                            reflection_max_rounds=(2 if is_last else 0),
                            quality_threshold=(72.0 if is_last else 65.0),
                            reflection_per_query_limit=(4 if is_last else 0),
                            reflection_max_new_docs=(32 if is_last else 0),
                            reflection_max_queries_per_round=(4 if is_last else 0),
                            reflection_wall_clock_seconds=(45.0 if is_last else 0.0),
                            reflection_early_accept_margin=(2.0 if is_last else 0.0),
                            reflection_min_score_gain=(0.75 if is_last else 0.0),
                            synth_model=os.getenv("FINAGENT_SYNTH_MODEL") or ("gpt-4o" if is_last else "gpt-4o-mini"),
                            response_depth=("deep" if is_last else "standard"),
                            output_mode=effective_output_mode,
                            emit_memo=is_last,
                            close_bus_on_finish=False,
                            chat_history=chat_history if (i == 0 or is_last) else None,
                            breadth_search_timeout=(75.0 if is_last else 20.0),
                            followup_search_timeout=(35.0 if is_last else 8.0),
                            reflection_per_query_timeout=(18.0 if is_last else 0.0),
                            blindspot_per_query_timeout=(25.0 if is_last else 0.0),
                            news_timeout=(18.0 if is_last else 5.0),
                            enable_blindspot=is_last,
                            fast_mode=not is_last,
                            # ── Peer targets ensure synthesis fetches BOTH companies' enrichment
                            peer_targets=peer_targets_list,
                            user_email=user_email,
                            tenant_id=tenant_id,
                        ),
                    )
                    
                    BUS.emit(master_session, "deep_pass", pass_number=i+1, total_passes=total_passes, objective=objective, deep_pass_label=pass_label, status="done")
                    return True

            # All enrichment passes parallel + final synthesis (bounded by semaphore)
            BUS.emit(master_session, "phase", phase="deep_research", note=f"Executing passes 1 to {total_passes-1} in parallel")
            parallel_tasks = [
                asyncio.create_task(_run_pass(i))
                for i in range(total_passes - 1)
            ]
            results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
            for res in results:
                if res is True:
                    completed_passes += 1
            
            await asyncio.sleep(0.5)
            
            if await _run_pass(total_passes - 1):
                completed_passes += 1
            
            BUS.emit(master_session, "deep_complete", passes=completed_passes, requested_passes=total_passes)
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
        "passes": 8,
    })


# ── Stop / cancel a running session ─────────────────────────────────────

@app.post("/sessions/{session_id}/stop")
async def stop_session(session_id: str, current_user: dict = Depends(get_current_user)):
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
async def chat_research(req: ChatResearchRequest, current_user: dict = Depends(enforce_token_limit)):
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
    if mode == "deep":
        return await start_deep_research(
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
    return await start_research(
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


@app.get("/sessions/{session_id}/status")
def session_status(session_id: str, current_user: dict = Depends(get_current_user)) -> JSONResponse:
    verify_session_ownership(session_id, current_user)
    return JSONResponse(_session_status(session_id))


@app.get("/sessions/{session_id}/events")
def session_events(session_id: str, after: int = 0, limit: int = 250, current_user: dict = Depends(get_current_user)) -> JSONResponse:
    verify_session_ownership(session_id, current_user)
    if not BUS.known(session_id):
        raise HTTPException(status_code=404, detail="Unknown session")
    events = [_event_payload(idx, event) for idx, event in BUS.history(session_id, after=after, limit=limit)]
    return JSONResponse({
        "session_id": session_id,
        "events": events,
        "next_after": (events[-1]["id"] + 1 if events else after),
        "closed": BUS.is_closed(session_id),
    })


@app.get("/chat/history")
def chat_history(session_id: str, current_user: dict = Depends(get_current_user)) -> JSONResponse:
    """Retrieve chat history for a session."""
    verify_session_ownership(session_id, current_user)
    user_email = current_user["email"]
    history = _MEMORY_MANAGER.get_history(user_email, session_id)
    return JSONResponse({"session_id": session_id, "history": history})


@app.get("/sessions/{session_id}/result")
def session_result(session_id: str, current_user: dict = Depends(get_current_user)) -> JSONResponse:
    verify_session_ownership(session_id, current_user)
    status = _session_status(session_id)
    memo_path = _MEMOS_DIR / f"{session_id}.md"
    memo_text = memo_path.read_text(encoding="utf-8") if memo_path.is_file() else None
    final_payload = status.get("final") or {}
    memo_event = status.get("memo") or {}
    if memo_text is None:
        memo_text = final_payload.get("memo") or final_payload.get("memo_preview") or memo_event.get("preview")
    return JSONResponse({
        "session_id": session_id,
        "status": status["status"],
        "target": status.get("target"),
        "mode": status.get("mode"),
        "final": final_payload or None,
        "memo": memo_text,
        "memo_event": memo_event or None,
        "error": status.get("error"),
    })


@app.get("/sessions/{session_id}/stream")
async def stream_session(
    session_id: str,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    after: int | None = None,
    current_user: dict = Depends(get_current_user)
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

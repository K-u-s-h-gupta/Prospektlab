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
from datetime import datetime, timezone
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
from finagent.portfolio_mirrors import load_active_positions, replace_active_positions, summarize_positions
from finagent.portfolio.analytics import compute_portfolio_analytics
from finagent.portfolio.news import fetch_portfolio_news
from finagent.gateway import supabase_client as supabase
from finagent.gateway.auth_guard import decode_current_user_token
import time

class InMemSlidingWindowRateLimiter:
    def __init__(self, requests_limit: int, window_seconds: int):
        self.requests_limit = requests_limit
        self.window_seconds = window_seconds
        self.history = {}

    async def __call__(self, request: Request):
        ip = "unknown"
        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            ip = auth.split(" ")[1]
        elif request.client:
            ip = request.client.host
            
        now = time.time()
        if ip not in self.history:
            self.history[ip] = []
        
        self.history[ip] = [t for t in self.history[ip] if now - t < self.window_seconds]
        
        if len(self.history[ip]) >= self.requests_limit:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again later."
            )
        self.history[ip].append(now)

research_rate_limiter = InMemSlidingWindowRateLimiter(requests_limit=5, window_seconds=60)
auth_rate_limiter = InMemSlidingWindowRateLimiter(requests_limit=10, window_seconds=60)
default_rate_limiter = InMemSlidingWindowRateLimiter(requests_limit=100, window_seconds=60)
_PENDING_EXTRACTIONS: dict[str, dict[str, Any]] = {}


def _ingestion_db_path() -> Path:
    return finagent_data_path("memory.sqlite3")


def _ensure_ingestion_state_table() -> None:
    from finagent.storage.sqlite import connect_wal

    with connect_wal(_ingestion_db_path()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS portfolio_ingestion_state (
                tenant_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                message TEXT,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def _set_ingestion_state(tenant_id: str | None, status: str, message: str = "") -> None:
    if not tenant_id:
        return
    from finagent.storage.sqlite import connect_wal

    _ensure_ingestion_state_table()
    with connect_wal(_ingestion_db_path()) as conn:
        conn.execute(
            """
            INSERT INTO portfolio_ingestion_state (tenant_id, status, message, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(tenant_id) DO UPDATE SET
                status=excluded.status,
                message=excluded.message,
                updated_at=excluded.updated_at
            """,
            (tenant_id, status, message),
        )


def _get_ingestion_state(tenant_id: str | None) -> dict[str, str]:
    if not tenant_id:
        return {"status": "IDLE", "message": ""}
    from finagent.storage.sqlite import connect_wal

    _ensure_ingestion_state_table()
    with connect_wal(_ingestion_db_path()) as conn:
        row = conn.execute(
            "SELECT status, COALESCE(message, '') FROM portfolio_ingestion_state WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchone()
    if not row:
        return {"status": "IDLE", "message": ""}
    return {"status": str(row[0]), "message": str(row[1] or "")}


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

_MEMORY_MANAGER = ChatMemoryManager()
AUTH_COOKIE_NAME = "prospektlab_auth"
AUTH_COOKIE_MAX_AGE = 60 * 60 * 24 * 30

logger = logging.getLogger("finagent.gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(
        "FastAPI gateway startup: Logging configuration successfully applied to finagent and oracle namespaces."
    )
    yield
    # Shutdown
    for task in list(_TASKS.values()):
        task.cancel()
    await aclose_shared_client()


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

# ── Global Security Headers Middleware ────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://accounts.google.com https://cdn.jsdelivr.net https://cdn.tailwindcss.com https://cdnjs.cloudflare.com https://unpkg.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://cdn.tailwindcss.com; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "img-src 'self' data: https://*.googleusercontent.com; "
        "connect-src 'self' https: wss: https://oauth2.googleapis.com https://*.supabase.co https://*.execute-api.us-east-1.amazonaws.com https://*.amplifyapp.com;"
    )
    return response

# ── Unified get_current_user Dependency for JWT and BOLA checks ──────────
def _set_auth_cookie(response: Response, token: str, request: Request) -> None:
    secure = request.url.scheme == "https" or os.getenv("PROSPEKTLAB_ENV") == "production"
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=AUTH_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
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
    token: str | None = None,
) -> dict:
    actual_token = None
    if authorization and authorization.startswith("Bearer "):
        actual_token = authorization.split(" ")[1]
    elif token:
        actual_token = token
    else:
        actual_token = request.cookies.get(AUTH_COOKIE_NAME)
    return _decode_current_user(actual_token)

def verify_session_ownership(session_id: str, current_user: dict) -> None:
    meta = _load_session_meta(session_id)
    owner_tenant = meta.get("tenant_id")
    if owner_tenant and owner_tenant != current_user.get("tenant_id"):
        raise HTTPException(status_code=403, detail="Access denied: You do not own this research session.")
    owner_email = meta.get("user_email")
    if owner_email and owner_email.lower().strip() != current_user["email"].lower().strip():
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
    logger.exception("Unhandled gateway error on %s %s", request.method, request.url.path)
    response = JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred.",
            "error_type": exc.__class__.__name__
        }
    )
    return add_cors_headers(request, response)

JWT_SECRET = os.getenv("JWT_SECRET", "super_secret_ipo_key_123")
if JWT_SECRET == "super_secret_ipo_key_123" and os.getenv("PROSPEKTLAB_ENV") == "production":
    raise RuntimeError("Insecure default JWT_SECRET fallback is prohibited in production!")

class GoogleAuthRequest(BaseModel):
    credential: str

@app.post("/auth/google", dependencies=[Depends(auth_rate_limiter)])
async def google_auth(req: GoogleAuthRequest, request: Request):
    """Verify a Google ID token from GIS popup and return a session JWT."""
    try:
        url = f"https://oauth2.googleapis.com/tokeninfo?id_token={urllib.parse.quote(req.credential)}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10)
            if resp.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid Google token")
            info = resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google verification failed: {e}")

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
    mobile = profile.get("mobile") if profile else ""
    require_mobile = not bool(mobile)

    try:
        token = jwt.encode({"user_id": user_id, "email": email}, JWT_SECRET, algorithm="HS256")
    except Exception:
        # Fallback if PyJWT is not installed, though it should be
        token = f"mock_token_{user_id}"

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

    return {"message": "Mobile number updated successfully."}



_GATEWAY_DIR = Path(__file__).resolve().parent
_WIDGET_PATH = _GATEWAY_DIR / "widget.html"
_PAGE_PATHS = {
    "landing": _GATEWAY_DIR / "landing.html",
    "login": _GATEWAY_DIR / "login.html",
    "signup": _GATEWAY_DIR / "signup.html",
    "profile": _GATEWAY_DIR / "profile.html",
    "settings": _GATEWAY_DIR / "settings.html",
}
_MEMOS_DIR = finagent_data_path("memos")


class StartResearchRequest(BaseModel):
    target: str = Field(..., min_length=1)
    objective: str = Field("")
    # Optional — when absent the agent auto-picks depth from the objective.
    max_steps: int | None = Field(default=None, ge=4, le=10000)
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


class DeepResearchRequest(BaseModel):
    target: str = Field(..., min_length=1)
    passes: int = Field(default=8, ge=2, le=20, description="Legacy input accepted; runtime uses fixed 8-phase Deep Research")
    pass_depth: int = Field(default=40, ge=10, le=120, description="Max steps per phase")
    max_wall_seconds: float | None = Field(default=None, ge=30, le=30 * 60)
    heartbeat_interval_s: float = Field(default=20.0, ge=5, le=60)
    user_email: str | None = None
    session_id: str | None = None


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


def _session_record(
    session_id: str,
    *,
    mode: str,
    target: str,
    objective: str = "",
    user_email: str | None = None,
    tenant_id: str | None = None,
) -> None:
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
    _session_meta_path(session_id).write_text(json.dumps(record, indent=2), encoding="utf-8")


def _session_meta_path(session_id: str) -> Path:
    path = finagent_data_path("sessions", session_id, "meta.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_session_meta(session_id: str) -> dict[str, Any]:
    if session_id in _SESSION_META:
        return dict(_SESSION_META[session_id])
    path = _session_meta_path(session_id)
    if not path.is_file():
        return {"session_id": session_id}
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(meta, dict):
            _SESSION_META[session_id] = meta
            return dict(meta)
    except Exception:
        pass
    return {"session_id": session_id}


def _save_session_meta(session_id: str, meta: dict[str, Any]) -> None:
    _SESSION_META[session_id] = dict(meta)
    try:
        _session_meta_path(session_id).write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


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


# ── Memory viewer endpoints ─────────────────────────────────────────────

@app.get("/portfolio/mirror")
def get_portfolio_mirror(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions = load_active_positions(tenant_id)
    return summarize_positions(positions)


@app.post("/portfolio/mirror")
def replace_portfolio_mirror(req: PositionMirrorReplaceRequest, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    _require_no_active_ingestion(tenant_id)
    positions = replace_active_positions(
        tenant_id,
        [item.model_dump() for item in req.positions if item.active],
    )
    _set_ingestion_state(tenant_id, "MIRROR_SYNCHRONIZED" if positions else "MIRROR_EMPTY", "Manual portfolio mirror updated.")
    return summarize_positions(positions)


def _require_synchronized_portfolio(tenant_id: str | None) -> None:
    if not tenant_id:
        raise HTTPException(
            status_code=403,
            detail={"status": "TENANT_REQUIRED", "message": "Portfolio audit requires a verified tenant session."},
        )
    if not load_active_positions(tenant_id):
        raise HTTPException(
            status_code=409,
            detail={
                "status": "MIRROR_REQUIRED",
                "message": "Upload and synchronize your eCAS, CSV, Excel, or screenshot holdings before running portfolio research.",
            },
        )


@app.post("/api/portfolio/upload-cas")
@app.post("/api/portfolio/upload-document")
@app.post("/portfolio/mirror/ecas")
async def upload_portfolio_document(
    file: UploadFile = File(...),
    password: str = Form(default=""),
    current_user: dict = Depends(get_current_user),
):
    filename = file.filename or "portfolio-upload"
    if not filename.lower().endswith((".pdf", ".csv", ".xls", ".xlsx")):
        raise HTTPException(status_code=400, detail="Upload a PDF, CSV, XLS, or XLSX portfolio document.")
    tenant_id = current_user.get("tenant_id")
    _set_ingestion_state(tenant_id, "INGESTING", "Transforming uploaded portfolio document.")
    try:
        payload_bytes = await file.read()
        extraction = await parse_portfolio_document(payload_bytes, filename, password)
    except Exception as exc:
        _set_ingestion_state(tenant_id, "FAILED", str(exc))
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
        _PENDING_EXTRACTIONS[review_id] = {
            "tenant_id": tenant_id,
            "source_type": extraction.source_type,
            "extraction": extraction.model_dump(),
        }
        _set_ingestion_state(tenant_id, "REVIEW_REQUIRED", "Review extracted holdings before syncing.")
        return {
            "ok": True,
            "code": "REVIEW_REQUIRED",
            "status": "REVIEW_REQUIRED",
            "sync_status": "REVIEW_REQUIRED",
            "review_id": review_id,
            "message": "Review extracted holdings before syncing.",
            **extraction.model_dump(),
        }

    positions = replace_active_positions(tenant_id, extraction_to_position_dicts(extraction))
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
    _set_ingestion_state(tenant_id, "INGESTING", "Extracting holdings from screenshot.")
    try:
        extraction = await extract_portfolio_from_image(await file.read(), filename)
    except PortfolioImageExtractionError as exc:
        _set_ingestion_state(tenant_id, "FAILED", str(exc))
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
    _PENDING_EXTRACTIONS[review_id] = {
        "tenant_id": tenant_id,
        "source_type": "image",
        "extraction": extraction.model_dump(),
    }
    _set_ingestion_state(tenant_id, "REVIEW_REQUIRED", "Review screenshot-extracted holdings before syncing.")
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
    pending = _PENDING_EXTRACTIONS.get(req.review_id or "") if req.review_id else None
    if req.review_id and not pending:
        raise HTTPException(status_code=404, detail="Review payload expired or not found.")
    if pending and pending.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=403, detail="Review payload belongs to a different tenant.")

    positions = req.positions
    source_type = req.source_type
    if not positions and pending:
        extraction = PortfolioExtractionSchema.model_validate(pending["extraction"])
        positions = extraction.positions
        source_type = pending.get("source_type", source_type)
    if not positions:
        raise HTTPException(status_code=422, detail="No reviewed holdings were supplied.")

    _set_ingestion_state(tenant_id, "INGESTING", "Synchronizing reviewed holdings.")
    extraction = PortfolioExtractionSchema(
        status="MIRROR_SYNCHRONIZED",
        source_type=source_type if source_type in {"pdf", "csv", "xlsx", "image"} else "unknown",
        positions=positions,
        confidence=sum(p.confidence for p in positions) / len(positions),
    )
    mirrored = replace_active_positions(tenant_id, extraction_to_position_dicts(extraction))
    summary = summarize_positions(mirrored)
    _set_ingestion_state(tenant_id, "MIRROR_SYNCHRONIZED", f"{summary['count']} holdings synchronized.")
    if req.review_id:
        _PENDING_EXTRACTIONS.pop(req.review_id, None)
    summary.update({"ok": True, "code": "MIRROR_SYNCHRONIZED", "source": source_type})
    return summary


@app.post("/api/portfolio/cancel-extraction")
async def cancel_portfolio_extraction(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    for review_id, payload in list(_PENDING_EXTRACTIONS.items()):
        if payload.get("tenant_id") == tenant_id:
            _PENDING_EXTRACTIONS.pop(review_id, None)
    _set_ingestion_state(tenant_id, "IDLE", "")
    return {"ok": True, "status": "IDLE"}


@app.get("/portfolio/analytics")
def get_portfolio_analytics(
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
    positions = load_active_positions(tenant_id)
    return compute_portfolio_analytics(positions, benchmark=benchmark, period=period)


@app.delete("/portfolio/mirror")
def delete_portfolio_mirror(current_user: dict = Depends(get_current_user)):
    """Clear all holdings for the authenticated tenant."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Tenant required")
    from finagent.storage.sqlite import connect_wal
    from finagent.paths import finagent_data_path
    db_path = finagent_data_path("memory.sqlite3")
    with connect_wal(db_path) as conn:
        cur = conn.execute("DELETE FROM position_mirrors WHERE tenant_id = ?", (tenant_id,))
    _set_ingestion_state(tenant_id, "IDLE", "")
    return {"ok": True, "deleted": cur.rowcount}


@app.get("/portfolio/news")
def get_portfolio_news(limit: int = 12, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions = load_active_positions(tenant_id)
    items = fetch_portfolio_news(positions, limit=limit)
    return {
        "items": items,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "min_score": 0.5,
            "max_age_days": 7,
            "verified_only": True,
        },
    }


@app.get("/portfolio/sectors")
def get_portfolio_sectors(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions = load_active_positions(tenant_id)
    from finagent.portfolio_mirrors import sector_breakdown
    return sector_breakdown(positions)


@app.get("/portfolio/holding/{symbol}")
def get_holding_detail(symbol: str, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions = load_active_positions(tenant_id)
    pos = next((p for p in positions if p.exchange_symbol == symbol or p.normalized_symbol == symbol), None)
    if not pos:
        raise HTTPException(status_code=404, detail="Holding not found")
    from finagent.portfolio.holding_detail import get_holding_detail as _get_detail
    return _get_detail(pos)


@app.get("/portfolio/corporate-actions")
def get_corporate_actions(days: int = 30, current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions = load_active_positions(tenant_id)
    from finagent.portfolio.corporate_actions import fetch_corporate_actions
    return {"events": fetch_corporate_actions(positions, days=days)}


@app.get("/portfolio/alerts")
def get_portfolio_alerts(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions = load_active_positions(tenant_id)
    from finagent.portfolio.alerts import compute_alerts
    analytics = compute_portfolio_analytics(positions)
    return {"alerts": compute_alerts(positions, analytics)}


@app.get("/portfolio/tax-summary")
def get_tax_summary(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions = load_active_positions(tenant_id)
    from finagent.portfolio.tax import compute_tax_summary
    return compute_tax_summary(positions)


@app.get("/portfolio/dividends")
def get_dividends(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions = load_active_positions(tenant_id)
    from finagent.portfolio.dividends import compute_dividend_summary, get_next_ex_dates
    return {
        **compute_dividend_summary(positions),
        "next_ex_dates": get_next_ex_dates(positions),
    }


class StressTestRequest(BaseModel):
    scenario: str = "nifty_down_20"
    custom_shocks: dict[str, float] | None = None

@app.post("/portfolio/stress-test")
def post_stress_test(
    body: StressTestRequest,
    current_user: dict = Depends(get_current_user),
):
    tenant_id = current_user.get("tenant_id")
    positions = load_active_positions(tenant_id)
    from finagent.portfolio.stress_test import run_stress_test
    return run_stress_test(positions, scenario=body.scenario, custom_shocks=body.custom_shocks)


@app.get("/portfolio/mf-analytics")
def get_mf_analytics(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions = load_active_positions(tenant_id)
    from finagent.portfolio.mf_analytics import compute_mf_analytics
    result = compute_mf_analytics(positions)
    if result is None:
        return {"status": "NO_MF_POSITIONS"}
    return result


@app.get("/portfolio/today")
def get_today_queue(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    positions = load_active_positions(tenant_id)
    from finagent.portfolio.action_queue import build_action_queue
    analytics = compute_portfolio_analytics(positions)
    return {"items": build_action_queue(positions, analytics)}


@app.get("/portfolio/brief")
def get_portfolio_brief(current_user: dict = Depends(get_current_user)):
    """Return a brief text summary of the portfolio."""
    tenant_id = current_user.get("tenant_id")
    positions = load_active_positions(tenant_id)
    if not positions:
        return {"brief": "No portfolio data available."}
    
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
def memory_stats(current_user: dict = Depends(get_current_user)):
    """Overall memory statistics scoped to the authenticated user."""
    store = get_memory_store()
    user_email = current_user.get("email")
    import sqlite3 as _sq
    c = _sq.connect(str(store.db_path))
    c.row_factory = _sq.Row
    if user_email:
        total = c.execute("SELECT COUNT(*) AS n FROM facts WHERE user_email = ?", (user_email,)).fetchone()["n"]
        targets = c.execute(
            "SELECT target_key, COUNT(*) AS n FROM facts WHERE user_email = ? GROUP BY target_key ORDER BY n DESC LIMIT 20",
            (user_email,),
        ).fetchall()
        sessions = c.execute("SELECT COUNT(*) AS n FROM session_summaries WHERE user_email = ?", (user_email,)).fetchone()["n"]
    else:
        total = c.execute("SELECT COUNT(*) AS n FROM facts").fetchone()["n"]
        targets = c.execute(
            "SELECT target_key, COUNT(*) AS n FROM facts GROUP BY target_key ORDER BY n DESC LIMIT 20"
        ).fetchall()
        sessions = c.execute("SELECT COUNT(*) AS n FROM session_summaries").fetchone()["n"]
    c.close()
    return {
        "total_facts": total,
        "total_sessions": sessions,
        "db_path": "<redacted>",
        "targets": [{"target": r["target_key"], "facts": r["n"]} for r in targets],
    }


@app.get("/memory/facts")
def memory_facts(target: str = "", limit: int = 50, current_user: dict = Depends(get_current_user)):
    """Browse facts — optionally filtered by target company, scoped to the authenticated user."""
    store = get_memory_store()
    user_email = current_user.get("email")
    import sqlite3 as _sq
    c = _sq.connect(str(store.db_path))
    c.row_factory = _sq.Row
    if target and user_email:
        rows = c.execute(
            "SELECT * FROM facts WHERE target_key = ? AND user_email = ? ORDER BY created_at DESC LIMIT ?",
            (normalize_target(target), user_email, limit),
        ).fetchall()
    elif target:
        rows = c.execute(
            "SELECT * FROM facts WHERE target_key = ? ORDER BY created_at DESC LIMIT ?",
            (normalize_target(target), limit),
        ).fetchall()
    elif user_email:
        rows = c.execute(
            "SELECT * FROM facts WHERE user_email = ? ORDER BY created_at DESC LIMIT ?",
            (user_email, limit),
        ).fetchall()
    else:
        rows = c.execute(
            "SELECT * FROM facts ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    c.close()
    return {
        "count": len(rows),
        "facts": [
            {
                "id": r["id"], "target_key": r["target_key"], "kind": r["kind"],
                "body": r["body"], "confidence": r["confidence"],
                "source_url": r["source_url"], "session_id": r["session_id"],
                "user_email": r["user_email"] if "user_email" in r.keys() else None,
                "created_at": r["created_at"],
            }
            for r in rows
        ],
    }


@app.get("/memory/sessions")
def memory_sessions(target: str = "", current_user: dict = Depends(get_current_user)):
    """List session summaries from memory, scoped to the authenticated user."""
    store = get_memory_store()
    user_email = current_user.get("email")
    import sqlite3 as _sq
    c = _sq.connect(str(store.db_path))
    c.row_factory = _sq.Row
    if target and user_email:
        rows = c.execute(
            "SELECT * FROM session_summaries WHERE target_key = ? AND user_email = ? ORDER BY created_at DESC LIMIT 20",
            (normalize_target(target), user_email),
        ).fetchall()
    elif target:
        rows = c.execute(
            "SELECT * FROM session_summaries WHERE target_key = ? ORDER BY created_at DESC LIMIT 20",
            (normalize_target(target),),
        ).fetchall()
    elif user_email:
        rows = c.execute(
            "SELECT * FROM session_summaries WHERE user_email = ? ORDER BY created_at DESC LIMIT 20",
            (user_email,),
        ).fetchall()
    else:
        rows = c.execute("SELECT * FROM session_summaries ORDER BY created_at DESC LIMIT 20").fetchall()
    c.close()
    return {
        "count": len(rows),
        "sessions": [
            {
                "session_id": r["session_id"], "target_key": r["target_key"],
                "target_display": r["target_display"],
                "summary": r["summary"][:300], "quality_score": r["quality_score"],
                "citation_count": r["citation_count"], "created_at": r["created_at"],
                "user_email": r["user_email"] if "user_email" in r.keys() else None,
            }
            for r in rows
        ],
    }


@app.delete("/memory/clear/{target}")
def memory_clear(target: str, current_user: dict = Depends(get_current_user)):
    """Delete all stored facts for a specific target scoped to the authenticated user."""
    store = get_memory_store()
    user_email = current_user.get("email")
    deleted = store.clear_target(target, user_email=user_email)
    return {"target": target, "deleted": deleted, "user_email": user_email}


# ── Static page handlers ────────────────────────────────────────────────


def _serve_page(name: str) -> HTMLResponse:
    p = _PAGE_PATHS.get(name)
    if not p or not p.is_file():
        return HTMLResponse(f"<h1>{name}.html missing</h1>", status_code=500)
    return HTMLResponse(p.read_text(encoding="utf-8"))


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/landing", status_code=302)


@app.get("/landing")
def landing() -> HTMLResponse:
    return _serve_page("landing")


@app.get("/login")
def login_page() -> HTMLResponse:
    return _serve_page("login")


@app.get("/signup")
def signup_page() -> HTMLResponse:
    return _serve_page("signup")


@app.get("/profile")
def profile_page() -> HTMLResponse:
    return _serve_page("profile")


@app.get("/settings")
def settings_page() -> HTMLResponse:
    return _serve_page("settings")


@app.get("/app")
def widget(request: Request, token: str | None = None):
    actual_token = token or request.cookies.get(AUTH_COOKIE_NAME)
    if not actual_token:
        return RedirectResponse(url="/login", status_code=302)
    try:
        _decode_current_user(actual_token)
    except HTTPException:
        response = RedirectResponse(url="/login", status_code=302)
        _clear_auth_cookie(response)
        return response
    if token:
        response = RedirectResponse(url="/app", status_code=302)
        _set_auth_cookie(response, actual_token, request)
        return response
    if not _WIDGET_PATH.is_file():
        return HTMLResponse("<h1>FinAgent</h1><p>widget.html missing</p>", status_code=500)
    return HTMLResponse(
        _WIDGET_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )


@app.post("/auth/logout")
def auth_logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    _clear_auth_cookie(response)
    return response


# ── Auth endpoints ──────────────────────────────────────────────────────


_VERIFICATION_CODES: dict[str, tuple[str, float]] = {}
_RESET_CODES: dict[str, tuple[str, float]] = {}

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
    _VERIFICATION_CODES[email_clean] = (code, time.time())
    
    sent = _send_email_code(email_clean, code, is_reset=False)
    if sent:
        return {"message": "Verification email sent successfully."}
    else:
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
    _RESET_CODES[email_clean] = (code, time.time())
    
    sent = _send_email_code(email_clean, code, is_reset=True)
    if sent:
        return {"message": "Reset code sent to your email."}
    else:
        return {
            "message": "Reset code generated.",
            "detail": f"Reset code simulated. Code {code} has been logged to the server terminal console."
        }


@app.post("/auth/reset-password", dependencies=[Depends(auth_rate_limiter)])
async def auth_reset_password(req: ResetPasswordRequest):
    email_clean = req.email.lower().strip()
    
    if email_clean not in _RESET_CODES:
        raise HTTPException(status_code=400, detail="Please request a password reset first.")
        
    code, timestamp = _RESET_CODES[email_clean]
    if time.time() - timestamp > 600:
        raise HTTPException(status_code=400, detail="Reset code has expired. Please request a new one.")
        
    if code != req.code.strip():
        raise HTTPException(status_code=400, detail="Invalid reset code.")
        
    # Validate via Supabase
    existing = await supabase.get_user_by_email(email_clean)
    if not existing:
        raise HTTPException(status_code=404, detail="Account not found.")
        
    user_id = existing["id"]
    await supabase.update_admin_user_password(user_id, req.new_password)
    
    # Clean up code
    if email_clean in _RESET_CODES:
        del _RESET_CODES[email_clean]
    
    return {"message": "Password reset successfully."}


@app.post("/auth/signup", dependencies=[Depends(auth_rate_limiter)])
async def auth_signup(req: SignupRequest, request: Request):
    email_clean = req.email.lower().strip()
    
    # Check verification code
    if email_clean not in _VERIFICATION_CODES:
        raise HTTPException(status_code=400, detail="Please send a verification code first.")
        
    code, timestamp = _VERIFICATION_CODES[email_clean]
    if time.time() - timestamp > 600:
        raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new one.")
        
    if code != req.verification_code.strip():
        raise HTTPException(status_code=400, detail="Invalid verification code.")
        
    name_clean = req.name.strip()
    mobile_clean = req.mobile.strip()
    
    # Create via Supabase
    res = await supabase.create_admin_user(email_clean, req.password, name_clean, mobile=mobile_clean, auth_provider="email")
    user_id = res.get("id")
    await supabase.upsert_profile(user_id, email_clean, name_clean, "email", mobile=mobile_clean)
    
    # Clean up verification code
    if email_clean in _VERIFICATION_CODES:
        del _VERIFICATION_CODES[email_clean]
        
    # Generate a JWT for immediate login after signup
    try:
        token = jwt.encode({"user_id": user_id, "email": email_clean}, JWT_SECRET, algorithm="HS256")
    except Exception:
        token = f"mock_token_{user_id}"
        
    response = JSONResponse({"token": token, "user": {"name": name_clean, "email": email_clean, "plan": "free"}})
    _set_auth_cookie(response, token, request)
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
    
    # Issue a local JWT (same format as Google auth + signup) so that
    # get_current_user can verify it with JWT_SECRET in production.
    # Using the raw Supabase access token here would cause 401s because
    # the backend would need SUPABASE_JWT_SECRET to verify it.
    try:
        token = jwt.encode({"user_id": user_id, "email": email_clean}, JWT_SECRET, algorithm="HS256")
    except Exception:
        token = f"mock_token_{user_id}"
    
    response = JSONResponse({
        "token": token,
        "user": {
            "name": full_name,
            "email": email_clean,
            "plan": "free"
        }
    })
    _set_auth_cookie(response, token, request)
    return response


# ── Research orchestration ──────────────────────────────────────────────


@app.post("/research/start", dependencies=[Depends(research_rate_limiter)])
async def start_research(req: StartResearchRequest, current_user: dict = Depends(get_current_user)):
    session_id = req.session_id or uuid.uuid4().hex[:12]
    
    if req.session_id:
        verify_session_ownership(session_id, current_user)
        
    raw_query = req.target.strip()
    user_email = current_user["email"]
    tenant_id = current_user["tenant_id"]
    _require_no_active_ingestion(tenant_id)
    if is_portfolio_scope_query(raw_query):
        _require_synchronized_portfolio(tenant_id)
    
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
            contextualizer = LLMQueryContextualizer()
            result = await contextualizer.contextualize(raw_query, prior_target, chat_history)
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
        except ContextualizerError as exc:
            logger.error("Contextualizer failed for session %s: %s", session_id, exc)
            raise HTTPException(status_code=503, detail="Context service unavailable")
        except Exception as exc:
            logger.error("Unexpected contextualizer error for session %s: %s", session_id, exc)
            raise HTTPException(status_code=503, detail="Context service unavailable")
    else:
        # No prior context — resolve normally
        target = primary_target_from_query(raw_query)

    # Re-check portfolio scope on contextualized objective (follow-ups may become portfolio queries)
    if is_portfolio_scope_query(objective):
        _require_synchronized_portfolio(tenant_id)

    # Always start a fresh event history for this research execution (prevents
    # replay of previous run's "memo"/"final" events into the new turn's UI).
    BUS.open(session_id, reset=True)
    mode = (req.mode or "chat").strip().lower()
    if mode not in {"chat", "standard", "deep"}:
        mode = "chat"
    
    # ── Comparison detection: extract both entities ────────────────────
    is_comparison_query = _is_comparison(raw_query)
    comparison_targets = _extract_comparison_targets(raw_query) if is_comparison_query else []
    # Force comparison output mode for comparison queries
    forced_output_mode = req.output_mode
    if is_comparison_query and not forced_output_mode:
        forced_output_mode = "company_comparison"
    
    _session_record(session_id, mode=mode, target=target, objective=objective, user_email=user_email, tenant_id=tenant_id)

    async def _runner() -> None:
        try:
            # ── Speed-first config ──────────────────────────────────────
            # Standard "Research" mode = single fast pass.
            # Deep mode within /research/start = same path but with slightly higher budget
            if req.max_steps is not None:
                base_steps = req.max_steps
            elif mode == "deep":
                base_steps = 60
            elif mode == "standard":
                base_steps = 38
            else:
                base_steps = 28
            
            chat_history = _MEMORY_MANAGER.get_history(user_email, session_id)

            # Lightweight pipeline for standard/chat modes: skip expensive phases.
            # The synthesis still has access to peer enrichment (added below
            # in run_research_session via peer_targets).
            is_fast_mode = mode in {"standard", "chat"}
            is_deep_mode = mode == "deep"

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
                    synth_model=os.getenv("FINAGENT_SYNTH_MODEL"),
                    # ── Speed: aggressively disable expensive phases for fast modes
                    enable_multi_agent=not is_fast_mode,
                    enable_blindspot=not is_fast_mode,
                    enable_reflection=True,
                    reflection_max_rounds=(1 if is_fast_mode else (3 if is_deep_mode else 5)),
                    reflection_max_new_docs=(20 if is_fast_mode else (60 if is_deep_mode else 80)),
                    enable_deep_dive=True,
                    quality_threshold=(60.0 if is_fast_mode else (70.0 if is_deep_mode else 75.0)),
                    # ── Tight timeouts for fast modes
                    breadth_search_timeout=(45.0 if is_fast_mode else (90.0 if is_deep_mode else 150.0)) * (3.0 if sys.platform == "win32" else 1.0),
                    followup_search_timeout=(25.0 if is_fast_mode else (45.0 if is_deep_mode else 70.0)) * (3.0 if sys.platform == "win32" else 1.0),
                    reflection_per_query_timeout=(18.0 if is_fast_mode else (35.0 if is_deep_mode else 55.0)),
                    blindspot_per_query_timeout=(15.0 if is_fast_mode else (30.0 if is_deep_mode else 45.0)),
                    news_timeout=(15.0 if is_fast_mode else (25.0 if is_deep_mode else 40.0)),
                    # ── Comparison: pass peer targets so synthesis has parallel enrichment
                    peer_targets=comparison_targets[1:] if len(comparison_targets) >= 2 else [],
                    chat_history=chat_history,
                    user_email=user_email,
                    tenant_id=tenant_id,
                ),
            )
            
        except Exception as exc:
            logger.exception("session %s crashed", session_id)
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

# Each entry maps to one parallel enrichment pass. Passes 0-N-2 run in parallel;
# pass N-1 is the serial synthesis. For Marathon (12 passes) the first 11 entries
# are used; for Deep (5 passes) only the first 4 + synthesis are used.
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
        "dividend yield and payout sustainability, analyst consensus target price and upside/downside."
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
        "summary with price targets under each scenario, (6) recommended action with conviction "
        "level (High/Medium/Low) and key monitorables."
    ),
]


@app.post("/research/deep", dependencies=[Depends(research_rate_limiter)])
async def start_deep_research(req: DeepResearchRequest, current_user: dict = Depends(get_current_user)):
    master_session = req.session_id or uuid.uuid4().hex[:12]
    
    if req.session_id:
        verify_session_ownership(master_session, current_user)
        
    raw_query = req.target.strip()
    user_email = current_user["email"]
    tenant_id = current_user["tenant_id"]
    _require_no_active_ingestion(tenant_id)
    if is_portfolio_scope_query(raw_query):
        _require_synchronized_portfolio(tenant_id)

    # ── Pure-LLM follow-up detection for deep research runs ───────────────
    meta = _load_session_meta(master_session)
    prior_target = meta.get("target_display") or meta.get("target")
    is_followup_deep = False
    target = None
    objective_for_deep = (getattr(req, "objective", None) or raw_query).strip()

    if req.session_id and prior_target:
        chat_history = _MEMORY_MANAGER.get_history(user_email, master_session)
        try:
            contextualizer = LLMQueryContextualizer()
            result = await contextualizer.contextualize(raw_query, prior_target, chat_history)
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
        except ContextualizerError as exc:
            logger.error("Deep contextualizer failed for session %s: %s", master_session, exc)
            raise HTTPException(status_code=503, detail="Context service unavailable")
        except Exception as exc:
            logger.error("Unexpected deep contextualizer error for session %s: %s", master_session, exc)
            raise HTTPException(status_code=503, detail="Context service unavailable")
    else:
        target = primary_target_from_query(raw_query)

    BUS.open(master_session, reset=True)
    
    _session_record(master_session, mode="deep", target=target, objective=raw_query, user_email=user_email, tenant_id=tenant_id)

    # ── Comparison detection for deep research ─────────────────────────
    is_comparison_query = _is_comparison(raw_query)
    comparison_targets = _extract_comparison_targets(raw_query) if is_comparison_query else []
    peer_targets_list = comparison_targets[1:] if len(comparison_targets) >= 2 else []

    async def _deep_runner() -> None:
        total_passes = 8
        completed_passes = 0
        started_at = asyncio.get_running_loop().time()
        chat_history = _MEMORY_MANAGER.get_history(user_email, master_session)
        
        try:
            async def _run_pass(i: int) -> bool:
                if req.max_wall_seconds is not None:
                    remaining = req.max_wall_seconds - (asyncio.get_running_loop().time() - started_at)
                    if remaining <= 0:
                        return False
                
                is_last = (i == total_passes - 1)
                objective = _DEEP_PASS_OBJECTIVES[i % len(_DEEP_PASS_OBJECTIVES)]
                pass_label = f"Synthesis Pass {i+1}/{total_passes}" if is_last else f"Pass {i+1}/{total_passes}"
                
                BUS.emit(master_session, "phase", phase="deep_research", note=f"{pass_label}: {objective[:60]}…")
                BUS.emit(master_session, "deep_pass", pass_number=i+1, total_passes=total_passes, objective=objective, status="running")
                
                pass_objective = f"{raw_query}\n\n{pass_label} - {objective}"
                # For comparison queries, force comparison output mode on synthesis pass
                effective_output_mode = "company_comparison" if (is_comparison_query and is_last) else ("deep_research_report" if is_last else None)

                await run_research_session(
                    target,
                    pass_objective,
                    is_followup=is_followup_deep,
                    loop_config=AgentLoopConfig(
                        max_steps=req.pass_depth,
                        session_id=master_session,
                        auto_depth=False,
                        enable_memory=True,
                        reflection_max_rounds=(5 if is_last else 3),
                        quality_threshold=(72.0 if is_last else 65.0),
                        reflection_per_query_limit=(8 if is_last else 6),
                        reflection_max_new_docs=(120 if is_last else 80),
                        synth_model="gpt-4o",
                        response_depth=("deep" if is_last else "standard"),
                        output_mode=effective_output_mode,
                        emit_memo=is_last,
                        close_bus_on_finish=False,
                        chat_history=chat_history if (i == 0 or is_last) else None,
                        breadth_search_timeout=180.0 * (3.0 if sys.platform == "win32" else 1.0),
                        followup_search_timeout=75.0 * (3.0 if sys.platform == "win32" else 1.0),
                        reflection_per_query_timeout=60.0,
                        blindspot_per_query_timeout=50.0,
                        news_timeout=45.0,
                        enable_blindspot=True,
                        # ── Peer targets ensure synthesis fetches BOTH companies' enrichment
                        peer_targets=peer_targets_list,
                        user_email=user_email,
                        tenant_id=tenant_id,
                    ),
                )
                
                BUS.emit(master_session, "deep_pass", pass_number=i+1, total_passes=total_passes, objective=objective, status="done")
                return True

            # All enrichment passes parallel + final synthesis
            BUS.emit(master_session, "phase", phase="deep_research", note=f"Executing passes 1 to {total_passes-1} in parallel")
            parallel_tasks = [_run_pass(i) for i in range(total_passes - 1)]
            results = await asyncio.gather(*parallel_tasks, return_exceptions=True)
            for res in results:
                if res is True:
                    completed_passes += 1
            
            await asyncio.sleep(0.5)
            
            if await _run_pass(total_passes - 1):
                completed_passes += 1
            
            BUS.emit(master_session, "deep_complete", passes=completed_passes, requested_passes=total_passes)
        except Exception as exc:
            logger.exception("deep research %s crashed on pass", master_session)
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
    task.cancel()
    BUS.emit(session_id, "phase", phase="stopped", reason="user_cancelled", note="Research stopped by user.")
    BUS.emit(session_id, "error", message="Research cancelled by user.")
    BUS.close(session_id)
    logger.info("Session %s cancelled by user", session_id)
    return {"session_id": session_id, "status": "cancelled"}


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str, current_user: dict = Depends(get_current_user)) -> JSONResponse:
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

    session_dir = finagent_data_path("sessions", session_id)
    removed_session_dir = False
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)
        removed_session_dir = True

    _SESSION_META.pop(session_id, None)
    BUS.forget_memory(session_id)
    deleted_history = _MEMORY_MANAGER.delete_session(current_user["email"], session_id)
    memory_cleanup = get_memory_store().delete_session(session_id, user_email=current_user["email"])

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
async def chat_research(req: ChatResearchRequest, current_user: dict = Depends(get_current_user)):
    """Chat-interface friendly entrypoint.

    Starts a background research job and returns polling/SSE/result URLs.
    A chat backend can call this, periodically poll `/status` or `/events`,
    then fetch `/result` when done.
    """
    if req.session_id:
        verify_session_ownership(req.session_id, current_user)
        
    target = (req.target or req.message).strip()
    mode = (req.mode or "standard").strip().lower()
    _require_no_active_ingestion(current_user.get("tenant_id"))
    if is_portfolio_scope_query(target):
        _require_synchronized_portfolio(current_user.get("tenant_id"))
    if mode == "marathon":
        mode = "deep"
    if mode == "deep":
        return await start_deep_research(
            DeepResearchRequest(
                target=target,
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
            mode="standard",
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
        session_id = p.stem
        meta = _load_session_meta(session_id)
        owner_tenant = meta.get("tenant_id")
        if owner_tenant and owner_tenant != current_user.get("tenant_id"):
            continue
        owner_email = meta.get("user_email")
        if owner_email and owner_email.lower().strip() != current_user["email"].lower().strip():
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
    return JSONResponse({
        "session_id": session_id,
        "status": status["status"],
        "target": status.get("target"),
        "mode": status.get("mode"),
        "final": status.get("final"),
        "memo": memo_text,
        "memo_event": status.get("memo"),
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
    
    if not BUS.known(session_id):
        raise HTTPException(status_code=404, detail="Unknown session")

    # If the session is active but the queue was popped on previous disconnect,
    # re-create/re-open it to catch new events.
    q = BUS.get(session_id)
    if q is None and not BUS.is_closed(session_id):
        q = BUS.open(session_id)

    # Determine starting event seq number
    after_seq = 0
    if after is not None:
        after_seq = after + 1
    elif last_event_id:
        try:
            after_seq = int(last_event_id) + 1
        except ValueError:
            pass

    async def gen():
        yield f"event: open\ndata: {json.dumps({'session_id': session_id})}\n\n"
        
        # 1. Replay missed events from history
        max_seen_seq = after_seq - 1
        history_events = BUS.history(session_id, after=after_seq, limit=5000)
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
                        yield "event: done\ndata: {}\n\n"
                        return

                    if event.seq > max_seen_seq:
                        idx = event.seq
                        payload = {"id": idx, "type": event.type, "timestamp": event.timestamp, **event.payload}
                        yield f"id: {idx}\nevent: {event.type}\ndata: {json.dumps(payload, default=str)}\n\n"
                        max_seen_seq = max(max_seen_seq, idx)
            finally:
                BUS.remove(session_id)
        else:
            yield "event: done\ndata: {}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

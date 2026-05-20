"""FastAPI gateway: start a research session, stream events, serve all pages."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

from fastapi import FastAPI, HTTPException, Header, Depends, Request
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
from finagent.memory.chat_memory import ChatMemoryManager
from finagent.gateway import supabase_client as supabase
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

logger = logging.getLogger("finagent.gateway")

app = FastAPI(title="ProspektLab Intelligence Gateway", version="0.5.0")

# ── CORS Middleware Configuration ─────────────────────────────────────────
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow Amplify, localhost, and all production origins
    allow_credentials=False,  # Must be False when allow_origins=["*"]
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
async def get_current_user(
    authorization: str = Header(None),
    token: str | None = None
) -> dict:
    actual_token = None
    if authorization and authorization.startswith("Bearer "):
        actual_token = authorization.split(" ")[1]
    elif token:
        actual_token = token
        
    if not actual_token:
        raise HTTPException(status_code=401, detail="Missing or invalid authentication credentials")
        
    try:
        # Try local JWT_SECRET first (issued for Google login or local overrides)
        payload = jwt.decode(actual_token, JWT_SECRET, algorithms=["HS256"])
        return {
            "user_id": payload.get("user_id"),
            "email": payload.get("email"),
            "auth_provider": "local_jwt"
        }
    except Exception:
        # Fallback: decode as a Supabase authentication token
        try:
            supabase_jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
            if supabase_jwt_secret:
                payload = jwt.decode(actual_token, supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
            else:
                # If Supabase secret not set locally, decode without validation for local single-user context
                # PROHIBIT unverified signature decode in production to prevent spoofing
                if os.getenv("PROSPEKTLAB_ENV") == "production":
                    raise HTTPException(status_code=401, detail="Supabase JWT verification secret is required in production")
                payload = jwt.decode(actual_token, options={"verify_signature": False})
            
            user_id = payload.get("sub") or payload.get("user_id")
            email = payload.get("email")
            if not email:
                raise HTTPException(status_code=401, detail="Invalid token details")
            return {
                "user_id": user_id,
                "email": email,
                "auth_provider": "supabase_jwt"
            }
        except Exception as e:
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=401, detail="Could not validate authentication credentials")

def verify_session_ownership(session_id: str, current_user: dict) -> None:
    meta = _load_session_meta(session_id)
    owner_email = meta.get("user_email")
    if owner_email and owner_email.lower().strip() != current_user["email"].lower().strip():
        raise HTTPException(status_code=403, detail="Access denied: You do not own this research session.")

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        loc = " -> ".join(str(l) for l in err.get("loc", []))
        msg = err.get("msg", "Invalid value")
        errors.append(f"[{loc}]: {msg}")
    
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Input validation failed",
            "errors": errors
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled gateway error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal server error occurred.",
            "error_type": exc.__class__.__name__
        }
    )

JWT_SECRET = os.getenv("JWT_SECRET", "super_secret_ipo_key_123")
if JWT_SECRET == "super_secret_ipo_key_123" and os.getenv("PROSPEKTLAB_ENV") == "production":
    raise RuntimeError("Insecure default JWT_SECRET fallback is prohibited in production!")

class GoogleAuthRequest(BaseModel):
    credential: str

@app.post("/auth/google", dependencies=[Depends(auth_rate_limiter)])
async def google_auth(req: GoogleAuthRequest):
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

    return {
        "token": token,
        "user_id": user_id,
        "email": email,
        "name": full_name,
        "full_name": full_name,
        "require_mobile": require_mobile,
        "mobile": mobile
    }

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



def _is_ambiguous_followup(query: str) -> bool:
    text = (query or "").strip().lower()
    if not text:
        return False

    # 1. GUARD: Explicit new commands are NEVER ambiguous follow-ups.
    if re.search(r"\b(analyze|analyse|research|review)\b", text):
        return False
        
    # 2. GUARD: Explicit two-item comparisons ("compare X and Y" or "X vs Y")
    if re.search(r"\bcompare\b.*\band\b", text):
        return False
    if re.search(r"\w+\s+(vs\.?|versus)\s+\w+", text):
        return False

    # 3. Check for explicit follow-up pronouns
    pronoun_ref = re.search(r"\b(it|its|they|their|them|that company|this company|same company)\b", text)
    
    # 4. Check for explicit entities (This handles "compare with TCS" or "vs TCS")
    explicit_entities = extract_finance_entities(query, limit=2)
    if explicit_entities:
        if len(explicit_entities) == 1 and re.search(r"\b(compare|vs|versus)\s+(with|against|to)?\b", text):
            return True
        return False
        
    # 5. Only fall back to word count if it lacks both entities and intent verbs
    return bool(pronoun_ref) or len(text.split()) <= 5

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
_USERS_DIR = finagent_data_path("users")
_USERS_DIR.mkdir(parents=True, exist_ok=True)


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


class DeepResearchRequest(BaseModel):
    target: str = Field(..., min_length=1)
    passes: int = Field(default=5, ge=2, le=20, description="Number of chained research passes")
    pass_depth: int = Field(default=40, ge=10, le=200, description="Max steps per pass")
    max_wall_seconds: float | None = Field(default=None, ge=30, le=24 * 60 * 60)
    heartbeat_interval_s: float = Field(default=20.0, ge=5, le=300)
    user_email: str | None = None
    session_id: str | None = None


class ChatResearchRequest(BaseModel):
    message: str = Field(..., min_length=1)
    target: str | None = Field(default=None, min_length=1)
    mode: str = Field(default="standard", description="standard, deep, or marathon")
    max_wall_seconds: float | None = Field(default=None, ge=10, le=24 * 60 * 60)
    user_email: str | None = None
    session_id: str | None = None


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


def _session_record(session_id: str, *, mode: str, target: str, objective: str = "", user_email: str | None = None) -> None:
    record = {
        "session_id": session_id,
        "mode": mode,
        "target": target,
        "objective": objective,
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


def _user_path(email: str) -> Path:
    safe = hashlib.sha1(email.lower().strip().encode("utf-8")).hexdigest()
    return _USERS_DIR / f"{safe}.json"


def _hash_pw(password: str, *, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt.encode("utf-8"), n=2**14, r=8, p=1, dklen=64).hex()
    return h, salt


@app.on_event("shutdown")
async def _shutdown() -> None:
    for task in list(_TASKS.values()):
        task.cancel()
    await aclose_shared_client()


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
                "playwright_installed": _has_module("playwright"),
                "pooled_chromium": True,
                "fallback_enabled": os.getenv("FINAGENT_BROWSER_FALLBACK") == "1",
                "http_fallback_enabled": os.getenv("FINAGENT_BROWSER_FALLBACK_HTTP") == "1",
                "extract_tool": True,
                "screenshot_tool": True,
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

from finagent.memory import get_memory_store
from finagent.memory.store import normalize_target


@app.get("/memory/stats")
def memory_stats(current_user: dict = Depends(get_current_user)):
    """Overall memory statistics."""
    store = get_memory_store()
    import sqlite3 as _sq
    c = _sq.connect(str(store.db_path))
    c.row_factory = _sq.Row
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
    """Browse facts — optionally filtered by target company."""
    store = get_memory_store()
    import sqlite3 as _sq
    c = _sq.connect(str(store.db_path))
    c.row_factory = _sq.Row
    if target:
        rows = c.execute(
            "SELECT * FROM facts WHERE target_key = ? ORDER BY created_at DESC LIMIT ?",
            (normalize_target(target), limit),
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
                "created_at": r["created_at"],
            }
            for r in rows
        ],
    }


@app.get("/memory/sessions")
def memory_sessions(target: str = "", current_user: dict = Depends(get_current_user)):
    """List session summaries from memory."""
    store = get_memory_store()
    import sqlite3 as _sq
    c = _sq.connect(str(store.db_path))
    c.row_factory = _sq.Row
    if target:
        rows = c.execute(
            "SELECT * FROM session_summaries WHERE target_key = ? ORDER BY created_at DESC LIMIT 20",
            (normalize_target(target),),
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
            }
            for r in rows
        ],
    }


@app.delete("/memory/clear/{target}")
def memory_clear(target: str, current_user: dict = Depends(get_current_user)):
    """Delete all stored facts for a specific target."""
    store = get_memory_store()
    deleted = store.clear_target(target)
    return {"target": target, "deleted": deleted}


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
def widget() -> HTMLResponse:
    if not _WIDGET_PATH.is_file():
        return HTMLResponse("<h1>FinAgent</h1><p>widget.html missing</p>", status_code=500)
    return HTMLResponse(
        _WIDGET_PATH.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )


# ── Auth endpoints ──────────────────────────────────────────────────────


import time

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
async def auth_signup(req: SignupRequest):
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
        
    return {"token": token, "user": {"name": name_clean, "email": email_clean, "plan": "free"}}



@app.post("/auth/login", dependencies=[Depends(auth_rate_limiter)])
async def auth_login(req: LoginRequest):
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
    
    return {
        "token": token,
        "user": {
            "name": full_name,
            "email": email_clean,
            "plan": "free"
        }
    }


# ── Research orchestration ──────────────────────────────────────────────


@app.post("/research/start", dependencies=[Depends(research_rate_limiter)])
async def start_research(req: StartResearchRequest, current_user: dict = Depends(get_current_user)):
    session_id = req.session_id or uuid.uuid4().hex[:12]
    
    if req.session_id:
        verify_session_ownership(session_id, current_user)
        
    BUS.open(session_id)
    raw_query = req.target.strip()
    user_email = current_user["email"]
    
    # Preserve the prior target only for truly ambiguous follow-ups. If the
    # user names a new company/ticker, resolve the current query normally.
    meta = _load_session_meta(session_id)
    prior_target = meta.get("target_display") or meta.get("target")
    if req.session_id and prior_target and _is_ambiguous_followup(raw_query):
        target = prior_target
    else:
        target = primary_target_from_query(raw_query)
        # ── Session isolation: if the resolved target differs from the prior
        # session's target, mint a fresh session_id so the old entity's
        # enrichment data, caches, and tool outputs don't leak into the new query.
        if req.session_id and prior_target and target and prior_target.lower() != target.lower():
            session_id = uuid.uuid4().hex[:12]
            BUS.open(session_id)
            logger.info("Target changed from %r to %r — new session %s", prior_target, target, session_id)
        
    objective = (req.objective or raw_query).strip()
    mode = (req.mode or "chat").strip().lower()
    if mode not in {"chat", "standard", "deep", "marathon"}:
        mode = "chat"
    
    # ── Comparison detection: extract both entities ────────────────────
    is_comparison_query = _is_comparison(raw_query)
    comparison_targets = _extract_comparison_targets(raw_query) if is_comparison_query else []
    # Force comparison output mode for comparison queries
    forced_output_mode = req.output_mode
    if is_comparison_query and not forced_output_mode:
        forced_output_mode = "company_comparison"
    
    _session_record(session_id, mode=mode, target=target, objective=objective, user_email=user_email)

    async def _runner() -> None:
        try:
            # ── Speed-first config ──────────────────────────────────────
            # Standard "Research" mode = single fast pass (no marathon-level layers)
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

            # Lightweight pipeline for non-marathon: skip expensive phases.
            # The synthesis still has access to peer enrichment (added below
            # in run_research_session via peer_targets).
            is_fast_mode = mode in {"standard", "chat"}
            is_deep_mode = mode == "deep"

            await run_research_session(
                target,
                objective,
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
                    breadth_search_timeout=(45.0 if is_fast_mode else (90.0 if is_deep_mode else 150.0)),
                    followup_search_timeout=(25.0 if is_fast_mode else (45.0 if is_deep_mode else 70.0)),
                    reflection_per_query_timeout=(18.0 if is_fast_mode else (35.0 if is_deep_mode else 55.0)),
                    blindspot_per_query_timeout=(15.0 if is_fast_mode else (30.0 if is_deep_mode else 45.0)),
                    news_timeout=(15.0 if is_fast_mode else (25.0 if is_deep_mode else 40.0)),
                    # ── Comparison: pass peer targets so synthesis has parallel enrichment
                    peer_targets=comparison_targets[1:] if len(comparison_targets) >= 2 else [],
                    chat_history=chat_history,
                ),
            )
            
            # Save the final memo to the memory layer
            memo_path = _MEMOS_DIR / f"{session_id}.md"
            if memo_path.is_file():
                final_memo = memo_path.read_text(encoding="utf-8")
                _MEMORY_MANAGER.append_message(user_email, session_id, "user", raw_query)
                _MEMORY_MANAGER.append_message(user_email, session_id, "assistant", final_memo)
                
        except Exception as exc:
            logger.exception("session %s crashed", session_id)
            BUS.emit(session_id, "error", message=str(exc))
            BUS.close(session_id)
        finally:
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
        
    BUS.open(master_session)
    raw_query = req.target.strip()
    target = primary_target_from_query(raw_query)
    user_email = current_user["email"]
    
    _session_record(master_session, mode="deep", target=target, objective=raw_query, user_email=user_email)

    # ── Comparison detection for marathon ──────────────────────────────
    is_comparison_query = _is_comparison(raw_query)
    comparison_targets = _extract_comparison_targets(raw_query) if is_comparison_query else []
    peer_targets_list = comparison_targets[1:] if len(comparison_targets) >= 2 else []

    async def _deep_runner() -> None:
        total_passes = req.passes
        completed_passes = 0
        started_at = asyncio.get_running_loop().time()
        chat_history = _MEMORY_MANAGER.get_history(user_email, master_session)
        is_marathon = req.passes >= 8
        
        try:
            async def _run_pass(i: int) -> bool:
                remaining = None
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
                    loop_config=AgentLoopConfig(
                        max_steps=req.pass_depth,
                        session_id=master_session,
                        auto_depth=False,
                        enable_memory=True,
                        reflection_max_rounds=(5 if is_last else (4 if is_marathon else 3)),
                        quality_threshold=(72.0 if is_last else (68.0 if is_marathon else 65.0)),
                        reflection_per_query_limit=(8 if is_last else 6),
                        reflection_max_new_docs=(120 if is_last else 80),
                        synth_model="gpt-4o",
                        response_depth=("deep" if is_last else "standard"),
                        output_mode=effective_output_mode,
                        emit_memo=is_last,
                        close_bus_on_finish=False,
                        chat_history=chat_history if (i == 0 or is_last) else None,
                        breadth_search_timeout=(240.0 if is_marathon else 180.0),
                        followup_search_timeout=(100.0 if is_marathon else 75.0),
                        reflection_per_query_timeout=(75.0 if is_marathon else 60.0),
                        blindspot_per_query_timeout=(60.0 if is_marathon else 50.0),
                        news_timeout=(60.0 if is_marathon else 45.0),
                        enable_blindspot=True,
                        # ── Peer targets ensure synthesis fetches BOTH companies' enrichment
                        peer_targets=peer_targets_list,
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
        "passes": req.passes,
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


# ── Mode instruction helper (from teammate's Backend/api.py) ────────────

def _mode_instruction(mode: str) -> str:
    """Return system-level instruction text based on analysis depth mode."""
    if mode == "marathon":
        return (
            "User selected Marathon mode. Produce a full-scale, investment-grade research report structured as follows:\n"
            "1. EXECUTIVE SUMMARY — 3-sentence verdict with bull/bear/base case and conviction level.\n"
            "2. BUSINESS OVERVIEW — business model, revenue segments, geography mix, key customers.\n"
            "3. FINANCIAL DEEP-DIVE — 5-year trend tables for revenue, EBITDA, net profit, EPS, FCF, ROCE, D/E. "
            "Include CAGR figures and margin trajectory commentary.\n"
            "4. VALUATION — P/E, EV/EBITDA, P/FCF vs sector peers; DCF base-case implied price; analyst consensus.\n"
            "5. COMPETITIVE MOAT — market share, switching costs, pricing power, top peer comparison table.\n"
            "6. MANAGEMENT & GOVERNANCE — promoter track record, pledge %, RPTs, board quality, SEBI actions.\n"
            "7. SHAREHOLDING INTELLIGENCE — FII/DII/promoter trend, smart-money signals, bulk/block deals.\n"
            "8. GROWTH CATALYSTS — hidden optionality, new products, capex cycle, M&A, government tailwinds.\n"
            "9. RISK MATRIX — top 5 risks with probability (H/M/L) and financial impact quantified where possible.\n"
            "10. MACRO & SECTOR CONTEXT — policy tailwinds/headwinds, RBI rate sensitivity, commodity exposure.\n"
            "11. INVESTMENT VERDICT — recommended action (Buy/Hold/Sell), price target range, key monitorables.\n"
            "Rules: Use real numbers with source citations. Flag data gaps explicitly. "
            "Prefer ₹ for Indian stocks. No vague phrases — every claim needs a number or a named source. "
            "Completeness and factual accuracy over brevity."
        )
    return (
        "User selected Deep mode. Provide an in-depth but concise analysis covering ratios, sector context, "
        "risks, recent events/news, and forward-looking insights. Structured sections, comprehensive but focused."
    )


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
    if mode == "marathon":
        return await start_deep_research(
            DeepResearchRequest(
                target=target,
                passes=12,
                pass_depth=120,
                max_wall_seconds=req.max_wall_seconds or 4 * 60 * 60,
                heartbeat_interval_s=20,
                session_id=req.session_id,
            ),
            current_user=current_user
        )
    if mode == "deep":
        return await start_deep_research(
            DeepResearchRequest(
                target=target,
                passes=5,
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

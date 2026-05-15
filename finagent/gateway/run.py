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

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from finagent.events import BUS
from finagent.paths import finagent_data_path, finagent_home
from finagent.run_agent import AgentLoopConfig, run_research_session
from finagent.tools.web.http_fetcher import aclose_shared_client

logger = logging.getLogger("finagent.gateway")

app = FastAPI(title="ProspektLab Intelligence Gateway", version="0.5.0")

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
    objective: str = Field("Deep research memo")
    # Optional — when absent the agent auto-picks depth from the objective.
    max_steps: int | None = Field(default=None, ge=4, le=10000)
    mode: str = Field(default="standard", description="standard or deep")


class DeepResearchRequest(BaseModel):
    target: str = Field(..., min_length=1)
    passes: int = Field(default=5, ge=2, le=20, description="Number of chained research passes")
    pass_depth: int = Field(default=40, ge=10, le=200, description="Max steps per pass")


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


_TASKS: dict[str, asyncio.Task[Any]] = {}


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
        "finagent_home": str(finagent_home()),
        "version": app.version,
    }


@app.get("/config")
def config():
    return {
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "finagent_home": str(finagent_home()),
        "version": app.version,
        "fx_override": os.getenv("FINAGENT_USD_INR"),
    }


# ── Memory viewer endpoints ─────────────────────────────────────────────

from finagent.memory import get_memory_store
from finagent.memory.store import normalize_target


@app.get("/memory/stats")
def memory_stats():
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
        "db_path": str(store.db_path),
        "targets": [{"target": r["target_key"], "facts": r["n"]} for r in targets],
    }


@app.get("/memory/facts")
def memory_facts(target: str = "", limit: int = 50):
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
def memory_sessions(target: str = ""):
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
def memory_clear(target: str):
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
    return HTMLResponse(_WIDGET_PATH.read_text(encoding="utf-8"))


# ── Auth endpoints ──────────────────────────────────────────────────────


@app.post("/auth/signup")
def auth_signup(req: SignupRequest):
    user_path = _user_path(req.email)
    if user_path.is_file():
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    h, salt = _hash_pw(req.password)
    record = {
        "name": req.name.strip(),
        "email": req.email.lower().strip(),
        "password_hash": h,
        "salt": salt,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "plan": "free",
    }
    user_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {"user": {"name": record["name"], "email": record["email"], "plan": "free"}}


@app.post("/auth/login")
def auth_login(req: LoginRequest):
    user_path = _user_path(req.email)
    if not user_path.is_file():
        raise HTTPException(status_code=401, detail="No account with that email.")
    try:
        record = json.loads(user_path.read_text(encoding="utf-8"))
    except Exception:
        raise HTTPException(status_code=500, detail="Account file corrupted.")
    h, _ = _hash_pw(req.password, salt=record.get("salt"))
    if not secrets.compare_digest(h, record.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Incorrect password.")
    return {"user": {"name": record["name"], "email": record["email"], "plan": record.get("plan", "free")}}


# ── Research orchestration ──────────────────────────────────────────────


@app.post("/research/start")
async def start_research(req: StartResearchRequest):
    session_id = uuid.uuid4().hex[:12]
    BUS.open(session_id)

    async def _runner() -> None:
        try:
            base_steps = req.max_steps if req.max_steps is not None else 40
            await run_research_session(
                req.target,
                req.objective,
                loop_config=AgentLoopConfig(
                    max_steps=base_steps,
                    session_id=session_id,
                    auto_depth=req.max_steps is None,
                ),
            )
        except Exception as exc:
            logger.exception("session %s crashed", session_id)
            BUS.emit(session_id, "error", message=str(exc))
            BUS.close(session_id)

    _TASKS[session_id] = asyncio.create_task(_runner())
    return JSONResponse({"session_id": session_id, "stream": f"/sessions/{session_id}/stream"})


# ── Deep Research: multi-pass long-chain reasoning ──────────────────────

_DEEP_PASS_OBJECTIVES = [
    "Core fundamentals: revenue, profit, margins, EPS, balance sheet, growth trajectory.",
    "Competitive position: market share, peer comparison, moat analysis, sector dynamics.",
    "Risk assessment: regulatory risks, governance, key-man risk, sector headwinds, SEBI compliance.",
    "Macro overlay: interest rate sensitivity, FX exposure, crude/commodity linkage, government policy impact.",
    "Final synthesis: triangulate all prior findings, resolve contradictions, produce investment-grade thesis.",
]


@app.post("/research/deep")
async def start_deep_research(req: DeepResearchRequest):
    """Multi-pass long-chain research that chains sequential sessions,
    each building on memory from the previous pass. Each pass focuses
    on a different analytical dimension — fundamentals, competition,
    risk, macro, synthesis — so the final memo is deeply triangulated.
    """
    master_session = uuid.uuid4().hex[:12]
    BUS.open(master_session)

    async def _deep_runner() -> None:
        total_passes = min(req.passes, len(_DEEP_PASS_OBJECTIVES))
        try:
            for i in range(total_passes):
                objective = _DEEP_PASS_OBJECTIVES[i % len(_DEEP_PASS_OBJECTIVES)]
                pass_label = f"Pass {i+1}/{total_passes}"
                BUS.emit(
                    master_session, "phase",
                    phase="deep_research",
                    note=f"{pass_label}: {objective[:60]}…",
                )
                BUS.emit(
                    master_session, "deep_pass",
                    pass_number=i + 1,
                    total_passes=total_passes,
                    objective=objective,
                    status="running",
                )

                # Each pass is a full research session that reads+writes memory
                pass_objective = f"{pass_label} — {objective}"
                await run_research_session(
                    req.target,
                    pass_objective,
                    loop_config=AgentLoopConfig(
                        max_steps=req.pass_depth,
                        session_id=master_session,
                        auto_depth=False,
                        enable_memory=True,
                        reflection_max_rounds=3,
                        quality_threshold=65.0,
                        synth_model="gpt-4o",
                    ),
                )

                BUS.emit(
                    master_session, "deep_pass",
                    pass_number=i + 1,
                    total_passes=total_passes,
                    objective=objective,
                    status="done",
                )

                # Brief pause between passes to let memory persist
                if i < total_passes - 1:
                    await asyncio.sleep(2)

            BUS.emit(master_session, "deep_complete", passes=total_passes)
        except Exception as exc:
            logger.exception("deep research %s crashed on pass", master_session)
            BUS.emit(master_session, "error", message=f"Deep research failed: {exc}")
        finally:
            BUS.close(master_session)

    _TASKS[master_session] = asyncio.create_task(_deep_runner())
    return JSONResponse({
        "session_id": master_session,
        "stream": f"/sessions/{master_session}/stream",
        "mode": "deep",
        "passes": min(req.passes, len(_DEEP_PASS_OBJECTIVES)),
    })


@app.get("/memos")
def list_memos() -> JSONResponse:
    if not _MEMOS_DIR.is_dir():
        return JSONResponse({"memos": []})
    entries: list[dict[str, Any]] = []
    for p in sorted(_MEMOS_DIR.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:50]:
        try:
            head = p.read_text(encoding="utf-8")[:200]
        except Exception:
            head = ""
        title = head.split("\n", 1)[0].lstrip("# ").strip() or p.stem
        entries.append(
            {
                "session_id": p.stem,
                "title": title,
                "bytes": p.stat().st_size,
                "modified": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return JSONResponse({"memos": entries})


@app.get("/sessions/{session_id}/memo")
def get_memo(session_id: str):
    memo_path = _MEMOS_DIR / f"{session_id}.md"
    if not memo_path.is_file():
        raise HTTPException(status_code=404, detail="Memo not ready")
    return HTMLResponse(memo_path.read_text(encoding="utf-8"), media_type="text/markdown")


@app.get("/sessions/{session_id}/stream")
async def stream_session(session_id: str):
    q = BUS.get(session_id)
    if q is None:
        raise HTTPException(status_code=404, detail="Unknown session")

    async def gen():
        yield f"event: open\ndata: {json.dumps({'session_id': session_id})}\n\n"
        try:
            while True:
                event = await q.get()
                if event is None:
                    yield "event: done\ndata: {}\n\n"
                    return
                payload = {"type": event.type, "timestamp": event.timestamp, **event.payload}
                yield f"event: {event.type}\ndata: {json.dumps(payload, default=str)}\n\n"
        finally:
            BUS.remove(session_id)
            _TASKS.pop(session_id, None)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

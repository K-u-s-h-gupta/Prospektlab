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
from finagent.output.intent_classifier import primary_target_from_query
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
    objective: str = Field("")
    # Optional — when absent the agent auto-picks depth from the objective.
    max_steps: int | None = Field(default=None, ge=4, le=10000)
<<<<<<< HEAD
    mode: str = Field(default="chat", description="chat, standard, or deep")
    output_mode: str | None = None
=======
    max_wall_seconds: float | None = Field(default=None, ge=10, le=24 * 60 * 60)
    heartbeat_interval_s: float = Field(default=20.0, ge=5, le=300)
    mode: str = Field(default="standard", description="standard or deep")
>>>>>>> f2b7297 (Fix React hydration mismatch, apply scrapling & Yahoo Finance patches, and stabilize backend API)


class DeepResearchRequest(BaseModel):
    target: str = Field(..., min_length=1)
    passes: int = Field(default=5, ge=2, le=20, description="Number of chained research passes")
    pass_depth: int = Field(default=40, ge=10, le=200, description="Max steps per pass")
    max_wall_seconds: float | None = Field(default=None, ge=30, le=24 * 60 * 60)
    heartbeat_interval_s: float = Field(default=20.0, ge=5, le=300)


class ChatResearchRequest(BaseModel):
    message: str = Field(..., min_length=1)
    target: str | None = Field(default=None, min_length=1)
    mode: str = Field(default="standard", description="standard, deep, or marathon")
    max_wall_seconds: float | None = Field(default=None, ge=10, le=24 * 60 * 60)


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
_SESSION_META: dict[str, dict[str, Any]] = {}


def _session_record(session_id: str, *, mode: str, target: str, objective: str = "") -> None:
    record = {
        "session_id": session_id,
        "mode": mode,
        "target": target,
        "objective": objective,
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
        "finagent_home": str(finagent_home()),
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
<<<<<<< HEAD
    raw_query = req.target.strip()
    objective = (req.objective or raw_query).strip()
    target = primary_target_from_query(raw_query)
    mode = (req.mode or "chat").strip().lower()
    if mode not in {"chat", "standard", "deep"}:
        mode = "chat"
=======
    _session_record(session_id, mode=req.mode or "standard", target=req.target, objective=req.objective)
>>>>>>> f2b7297 (Fix React hydration mismatch, apply scrapling & Yahoo Finance patches, and stabilize backend API)

    async def _runner() -> None:
        try:
            if req.max_steps is not None:
                base_steps = req.max_steps
            elif mode == "deep":
                base_steps = 80
            elif mode == "standard":
                base_steps = 56
            else:
                base_steps = 40
            await run_research_session(
                target,
                objective,
                loop_config=AgentLoopConfig(
                    max_steps=base_steps,
                    session_id=session_id,
                    auto_depth=req.max_steps is None,
<<<<<<< HEAD
                    response_depth=mode,
                    output_mode=req.output_mode,
                    breadth_search_timeout=(150.0 if mode == "deep" else 110.0),
                    followup_search_timeout=(70.0 if mode == "deep" else 50.0),
                    reflection_per_query_timeout=(55.0 if mode == "deep" else 38.0),
                    blindspot_per_query_timeout=(45.0 if mode == "deep" else 32.0),
                    news_timeout=(40.0 if mode == "deep" else 30.0),
=======
                    max_wall_seconds=req.max_wall_seconds,
                    heartbeat_interval_s=req.heartbeat_interval_s,
                    synth_model=os.getenv("FINAGENT_SYNTH_MODEL"),
>>>>>>> f2b7297 (Fix React hydration mismatch, apply scrapling & Yahoo Finance patches, and stabilize backend API)
                ),
            )
        except Exception as exc:
            logger.exception("session %s crashed", session_id)
            BUS.emit(session_id, "error", message=str(exc))
            BUS.close(session_id)

    _TASKS[session_id] = asyncio.create_task(_runner())
    return JSONResponse({
        "session_id": session_id,
        "stream": f"/sessions/{session_id}/stream",
        "status": f"/sessions/{session_id}/status",
        "events": f"/sessions/{session_id}/events",
        "result": f"/sessions/{session_id}/result",
    })


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
<<<<<<< HEAD
    raw_query = req.target.strip()
    target = primary_target_from_query(raw_query)
=======
    _session_record(master_session, mode="deep", target=req.target, objective="Multi-pass deep research")
>>>>>>> f2b7297 (Fix React hydration mismatch, apply scrapling & Yahoo Finance patches, and stabilize backend API)

    async def _deep_runner() -> None:
        total_passes = req.passes
        completed_passes = 0
        started_at = asyncio.get_running_loop().time()
        try:
            for i in range(total_passes):
                remaining = None
                if req.max_wall_seconds is not None:
                    remaining = req.max_wall_seconds - (asyncio.get_running_loop().time() - started_at)
                    if remaining <= 0:
                        BUS.emit(
                            master_session,
                            "phase",
                            phase="stopped",
                            reason="time_budget",
                            note="Deep research wall-clock budget reached.",
                        )
                        break
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
                pass_objective = f"{raw_query}\n\n{pass_label} - {objective}"
                await run_research_session(
                    target,
                    pass_objective,
                    loop_config=AgentLoopConfig(
                        max_steps=req.pass_depth,
                        session_id=master_session,
                        auto_depth=False,
                        enable_memory=True,
                        reflection_max_rounds=3,
                        quality_threshold=65.0,
<<<<<<< HEAD
                        synth_model="gpt-4o",
                        response_depth=("deep" if i == total_passes - 1 else "standard"),
                        output_mode=("deep_research_report" if i == total_passes - 1 else None),
                        emit_memo=(i == total_passes - 1),
                        close_bus_on_finish=False,
                        breadth_search_timeout=180.0,
                        followup_search_timeout=75.0,
                        reflection_per_query_timeout=60.0,
                        blindspot_per_query_timeout=50.0,
                        news_timeout=45.0,
=======
                        synth_model=os.getenv("FINAGENT_SYNTH_MODEL"),
                        max_wall_seconds=remaining,
                        heartbeat_interval_s=req.heartbeat_interval_s,
                        close_bus_on_finish=False,
>>>>>>> f2b7297 (Fix React hydration mismatch, apply scrapling & Yahoo Finance patches, and stabilize backend API)
                    ),
                )

                BUS.emit(
                    master_session, "deep_pass",
                    pass_number=i + 1,
                    total_passes=total_passes,
                    objective=objective,
                    status="done",
                )
                completed_passes += 1

                # Brief pause between passes to let memory persist
                if i < total_passes - 1:
                    await asyncio.sleep(2)

            BUS.emit(master_session, "deep_complete", passes=completed_passes, requested_passes=total_passes)
        except Exception as exc:
            logger.exception("deep research %s crashed on pass", master_session)
            BUS.emit(master_session, "error", message=f"Deep research failed: {exc}")
        finally:
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


@app.post("/chat/research")
async def chat_research(req: ChatResearchRequest):
    """Chat-interface friendly entrypoint.

    Starts a background research job and returns polling/SSE/result URLs.
    A chat backend can call this, periodically poll `/status` or `/events`,
    then fetch `/result` when done.
    """
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
            )
        )
    if mode == "deep":
        return await start_deep_research(
            DeepResearchRequest(
                target=target,
                passes=5,
                pass_depth=40,
                max_wall_seconds=req.max_wall_seconds,
                heartbeat_interval_s=20,
            )
        )
    return await start_research(
        StartResearchRequest(
            target=target,
            objective=req.message,
            max_wall_seconds=req.max_wall_seconds,
            heartbeat_interval_s=20,
            mode="standard",
        )
    )


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


@app.get("/sessions/{session_id}/status")
def session_status(session_id: str) -> JSONResponse:
    return JSONResponse(_session_status(session_id))


@app.get("/sessions/{session_id}/events")
def session_events(session_id: str, after: int = 0, limit: int = 250) -> JSONResponse:
    if not BUS.known(session_id):
        raise HTTPException(status_code=404, detail="Unknown session")
    events = [_event_payload(idx, event) for idx, event in BUS.history(session_id, after=after, limit=limit)]
    return JSONResponse({
        "session_id": session_id,
        "events": events,
        "next_after": (events[-1]["id"] + 1 if events else after),
        "closed": BUS.is_closed(session_id),
    })


@app.get("/sessions/{session_id}/result")
def session_result(session_id: str) -> JSONResponse:
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
async def stream_session(session_id: str):
    q = BUS.get(session_id)
    if q is None and not BUS.is_closed(session_id):
        raise HTTPException(status_code=404, detail="Unknown session")

    async def gen():
        yield f"event: open\ndata: {json.dumps({'session_id': session_id})}\n\n"
        if q is None and BUS.is_closed(session_id):
            for idx, event in BUS.history(session_id, limit=5000):
                payload = _event_payload(idx, event)
                yield f"id: {idx}\nevent: {event.type}\ndata: {json.dumps(payload, default=str)}\n\n"
            yield "event: done\ndata: {}\n\n"
            return
        try:
            while True:
                event = await q.get()
                if event is None:
                    yield "event: done\ndata: {}\n\n"
                    return
                idx = event.seq
                payload = {"id": idx, "type": event.type, "timestamp": event.timestamp, **event.payload}
                yield f"id: {idx}\nevent: {event.type}\ndata: {json.dumps(payload, default=str)}\n\n"
        finally:
            BUS.remove(session_id)
            _TASKS.pop(session_id, None)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

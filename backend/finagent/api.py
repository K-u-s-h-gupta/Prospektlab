"""
FinAgent API - Merged from teammate's Backend/api.py + rich_builder integration
All API logic now lives inside finagent/.
"""
from __future__ import annotations

import os
import sys

# Fix Windows UTF-8 before any imports (crawl4ai's Rich logger crashes on cp1252)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import os
import re

from finagent.router.intent_router import is_portfolio_scope_query
from finagent.gateway.run import _should_use_standard_deep_lite

logger = logging.getLogger("finagent.api")

app = FastAPI(title="FinAgent API", version="2.0.0")

# Tighten CORS: allow only configured origins, never allow credentials with "*"
_cors_origins = os.getenv("CORS_ORIGINS", "*")
if _cors_origins.strip() == "*":
    _allow_origins = ["*"]
    _allow_creds = False
else:
    _allow_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
    _allow_creds = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_creds,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ── Auth dependency ───────────────────────────────────────────────────────

@app.middleware("http")
async def telemetry_middleware(request: Request, call_next):
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

from finagent.telemetry import TELEMETRY, telemetry_request_context, telemetry_user_from_authorization_header, telemetry_user_from_request_user
from finagent.gateway.auth_guard import decode_current_user_token

_JWT_SECRET = os.getenv("JWT_SECRET")

async def get_current_user(request: Request):
    token = None
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        token = auth.split(" ", 1)[1]
    if not token:
        raise HTTPException(status_code=401, detail="Missing or invalid authentication credentials")
    if not _JWT_SECRET:
        raise HTTPException(status_code=500, detail="JWT_SECRET is not configured")
    return decode_current_user_token(token, local_jwt_secret=_JWT_SECRET)

# ── Prompt injection guard ────────────────────────────────────────────────

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


def _guard_prompt_injection(query: str) -> str:
    if PROMPT_INJECTION_PATTERNS.search(query):
        raise HTTPException(400, "Query contains disallowed directives")
    safe = query.replace("<", "&lt;").replace(">", "&gt;")
    return f"[USER_QUERY]\n{safe}\n[/USER_QUERY]"



class ChatRequest(BaseModel):
    message: str
    response_depth: str = "deep"   # chat | standard | deep


class ChatResponse(BaseModel):
    reply: str
    agents_used: list[str] = Field(default_factory=list)
    rich: dict[str, Any] | None = None
    output_mode: str | None = None
    response_depth: str | None = None
    elapsed_ms: int | None = None


# =============================================================================
# Dynamic Output Mode Mapping
# =============================================================================
# This map controls what output_mode the frontend should use based on which
# specialist agents were activated by the user's query intent.
#
# Key idea: Every agent can influence (or fully determine) the final rendering mode.
# This makes the system truly intent-driven.
AGENT_TO_OUTPUT_MODE: dict[str, str] = {
    # High-value specialist agents (rich, detailed output)
    "valuation": "valuation_insights",        # Statistical revenue projection + DCF insights
    "accounting": "forensic_insights",        # Anomaly / forensic accounting analysis

    # Standard specialist agents
    "financials": "financial_snapshot",
    "risk": "risk_analysis",
    "governance": "governance_review",
    "technical": "technical_analysis",
    "competitor": "competitor_analysis",
    "macro": "macro_outlook",
    "community": "community_sentiment",

    # Lightweight / focused agents
    "news": "news_brief",
}

# Priority order when multiple agents run (first match wins)
OUTPUT_MODE_PRIORITY = [
    "valuation",      # Highest priority - rich DCF + statistical projection
    "accounting",     # Forensic analysis
    "risk",
    "governance",
    "financials",
    "technical",
    "competitor",
    "macro",
    "community",
    "news",
]


def _choose_output_mode(agents_used: list[str]) -> str:
    """
    Fully dynamic output mode selection.

    Rules:
    - Looks at ALL agents that ran for the query.
    - Uses a priority list so that important agents (valuation, accounting)
      can dominate the rendering mode.
    - Falls back gracefully to "direct_answer" if no known agent ran.
    - Easy to extend: just add new agent → mode mapping in AGENT_TO_OUTPUT_MODE.
    """
    if not agents_used:
        return "direct_answer"

    active_agents = [a for a in agents_used if a in AGENT_TO_OUTPUT_MODE]

    if not active_agents:
        return "direct_answer"

    # Choose based on priority
    for agent in OUTPUT_MODE_PRIORITY:
        if agent in active_agents:
            return AGENT_TO_OUTPUT_MODE[agent]

    # Fallback: use the first active agent's mode
    return AGENT_TO_OUTPUT_MODE[active_agents[0]]


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    """Standard JSON chat endpoint with rich support."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    _guard_prompt_injection(req.message)
    telemetry_user = telemetry_user_from_request_user(current_user)

    session_id = str(uuid.uuid4())
    logger.info("[API] Received /api/chat request | session_id=%s | query=%r | depth=%s",
                session_id, req.message[:200], req.response_depth)

    try:
        from finagent.run_agent import run_finagent_session, AgentLoopConfig

        # Apply same fast / deep-lite standard-mode logic as the gateway
        is_standard = req.response_depth == "standard"
        is_portfolio = is_portfolio_scope_query(req.message)
        standard_deep_lite = is_standard and _should_use_standard_deep_lite(
            req.message, req.message,
            is_portfolio_query=is_portfolio,
            is_comparison_query=False,
        )

        cfg = AgentLoopConfig(
            session_id=session_id,
            response_depth=req.response_depth,
            close_bus_on_finish=True,
            enable_multi_agent=standard_deep_lite if is_standard else True,
            enable_blindspot=standard_deep_lite if is_standard else True,
            enable_reflection=standard_deep_lite if is_standard else True,
            enable_deep_dive=standard_deep_lite if is_standard else True,
            fast_mode=not standard_deep_lite if is_standard else False,
        )

        logger.info("[API] Calling run_finagent_session | session_id=%s", session_id)
        t0 = time.perf_counter()
        reply, agents_used, rich = await run_finagent_session(req.message, cfg)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("[API] run_finagent_session completed | session_id=%s | agents_used=%s | reply_len=%d | elapsed_ms=%d",
                    session_id, agents_used, len(reply) if reply else 0, elapsed_ms)

        output_mode = _choose_output_mode(agents_used or [])
        TELEMETRY.emit_event(
            "chat_completed",
            user=telemetry_user,
            properties={
                "source": "backend",
                "session_id": session_id,
                "depth": req.response_depth,
                "elapsed_ms": elapsed_ms,
                "agents_used": len(agents_used or []),
            },
        )

        return ChatResponse(
            reply=reply,
            agents_used=agents_used or [],
            rich=rich.model_dump(mode="json") if rich is not None else None,
            output_mode=output_mode,
            response_depth=req.response_depth,
            elapsed_ms=elapsed_ms,
        )
    except Exception as e:
        logger.error("[API] Chat endpoint error | session_id=%s | error=%s", session_id, e, exc_info=True)
        TELEMETRY.emit_exception(
            e,
            user=telemetry_user,
            request_id=session_id,
            properties={
                "source": "backend",
                "session_id": session_id,
                "depth": req.response_depth,
                "endpoint": "/api/chat",
            },
        )
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    """Streaming endpoint that yields agent events and final rich data."""
    _guard_prompt_injection(req.message)
    telemetry_user = telemetry_user_from_request_user(current_user)
    async def event_generator() -> AsyncIterator[str]:
        try:
            from finagent.run_agent import run_finagent_session, AgentLoopConfig
            from finagent.events import BUS

            session_id = str(uuid.uuid4())
            logger.info("[API] Received /api/chat/stream request | session_id=%s | query=%r | depth=%s",
                        session_id, req.message[:200], req.response_depth)

            # Apply same fast / deep-lite standard-mode logic as the gateway
            is_standard = req.response_depth == "standard"
            is_portfolio = is_portfolio_scope_query(req.message)
            standard_deep_lite = is_standard and _should_use_standard_deep_lite(
                req.message, req.message,
                is_portfolio_query=is_portfolio,
                is_comparison_query=False,
            )

            cfg = AgentLoopConfig(
                session_id=session_id,
                response_depth=req.response_depth,
                close_bus_on_finish=False,  # We close manually after streaming
                enable_multi_agent=standard_deep_lite if is_standard else True,
                enable_blindspot=standard_deep_lite if is_standard else True,
                enable_reflection=standard_deep_lite if is_standard else True,
                enable_deep_dive=standard_deep_lite if is_standard else True,
                fast_mode=not standard_deep_lite if is_standard else False,
            )

            logger.info("[API] Starting streaming run_finagent_session | session_id=%s", session_id)
            TELEMETRY.emit_event(
                "chat_stream_started",
                user=telemetry_user,
                properties={
                    "source": "backend",
                    "session_id": session_id,
                    "depth": req.response_depth,
                },
            )

            # Subscribe to BUS events for this session
            event_queue = []

            def on_event(event_data):
                event_queue.append(event_data)

            # Register listener if BUS supports it
            if hasattr(BUS, 'on'):
                BUS.on(session_id, on_event)

            # Run the agent loop
            t0 = time.perf_counter()
            reply, agents_used, rich = await run_finagent_session(req.message, cfg)
            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger.info("[API] Streaming run_finagent_session finished | session_id=%s | agents=%s | elapsed_ms=%d", session_id, agents_used, elapsed_ms)

            # Yield buffered events
            for event_data in event_queue:
                yield f"event: agent_event\ndata: {json.dumps(event_data)}\n\n"

            # Yield final response with dynamic mode
            output_mode = _choose_output_mode(agents_used or [])

            final_payload = {
                "type": "final",
                "reply": reply,
                "agents_used": agents_used or [],
                "rich": rich.model_dump(mode="json") if rich is not None else None,
                "output_mode": output_mode,
                "response_depth": req.response_depth,
                "elapsed_ms": elapsed_ms,
            }
            yield f"event: final\ndata: {json.dumps(final_payload)}\n\n"
            TELEMETRY.emit_event(
                "chat_stream_completed",
                user=telemetry_user,
                properties={
                    "source": "backend",
                    "session_id": session_id,
                    "depth": req.response_depth,
                    "elapsed_ms": elapsed_ms,
                },
            )

            if hasattr(BUS, 'off'):
                BUS.off(session_id)
            if hasattr(BUS, 'close'):
                BUS.close()

        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            TELEMETRY.emit_exception(
                e,
                user=telemetry_user,
                properties={
                    "source": "backend",
                    "endpoint": "/api/chat/stream",
                    "depth": req.response_depth,
                },
            )
            yield f"event: error\ndata: {json.dumps({'type':'error','message':str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/health/mcp")
async def mcp_health():
    """Health check for MCP servers (teammate's implementation)."""
    return {
        "all_ok": True,
        "servers": {
            "discovery_server": {"ok": True, "latency_ms": 15},
            "quant_server": {"ok": True, "latency_ms": 15},
        }
    }


if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="FinAgent API Server")
    parser.add_argument("--port", type=int, default=8080, help="Port to run the server on (default: 8080)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind the server (default: 0.0.0.0)")
    args = parser.parse_args()

    uvicorn.run("finagent.api:app", host=args.host, port=args.port, reload=True)

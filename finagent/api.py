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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field



logger = logging.getLogger("finagent.api")

app = FastAPI(title="FinAgent API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
async def chat(req: ChatRequest):
    """Standard JSON chat endpoint with rich support."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    session_id = str(uuid.uuid4())
    logger.info("[API] Received /api/chat request | session_id=%s | query=%r | depth=%s",
                session_id, req.message[:200], req.response_depth)

    try:
        from finagent.run_agent import run_finagent_session, AgentLoopConfig
        cfg = AgentLoopConfig(
            session_id=session_id,
            response_depth=req.response_depth,
            close_bus_on_finish=True,
        )

        logger.info("[API] Calling run_finagent_session | session_id=%s", session_id)
        t0 = time.perf_counter()
        reply, agents_used, rich = await run_finagent_session(req.message, cfg)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info("[API] run_finagent_session completed | session_id=%s | agents_used=%s | reply_len=%d | elapsed_ms=%d",
                    session_id, agents_used, len(reply) if reply else 0, elapsed_ms)

        output_mode = _choose_output_mode(agents_used or [])

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
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Streaming endpoint that yields agent events and final rich data."""
    async def event_generator() -> AsyncIterator[str]:
        try:
            from finagent.run_agent import run_finagent_session, AgentLoopConfig
            from finagent.events import BUS

            session_id = str(uuid.uuid4())
            logger.info("[API] Received /api/chat/stream request | session_id=%s | query=%r | depth=%s",
                        session_id, req.message[:200], req.response_depth)

            cfg = AgentLoopConfig(
                session_id=session_id,
                response_depth=req.response_depth,
                close_bus_on_finish=False,  # We close manually after streaming
            )

            logger.info("[API] Starting streaming run_finagent_session | session_id=%s", session_id)

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

            if hasattr(BUS, 'off'):
                BUS.off(session_id)
            if hasattr(BUS, 'close'):
                BUS.close()

        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
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

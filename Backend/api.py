"""
ORACLE FIOS - FastAPI Backend
=============================
Exposes chat endpoints for the Next.js frontend to query the LangGraph brain.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import warnings
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from openai import APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError
from pydantic import BaseModel, Field

import rich_builder
from intent import (
    AGENT_SERVER_DEPENDENCIES as _INTENT_AGENT_DEPS,
    is_comparison_query as _intent_is_comparison_query,
    is_calculation_valuation_query as _intent_is_calculation_valuation_query,
    planned_agents_for_message as _intent_planned_agents,
)
from mcp_config import MCP_SERVERS

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")
logger = logging.getLogger("oracle.api")
warnings.filterwarnings(
    "ignore",
    message=r"The default value of `allowed_objects` will change in a future version\..*",
)

app = FastAPI(title="ORACLE FIOS API", version="0.1.0")
GRAPH_RUN_TIMEOUT_SECONDS = 240
GRAPH_IDLE_TIMEOUT_SECONDS = 90
GRAPH_REBUILD_COOLDOWN_SECONDS = 5

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_graph = None
_graph_lock = asyncio.Lock()
_graph_available_agents: list[str] | None = None
_graph_unavailable_servers: dict[str, str] = {}
_graph_last_build_attempt = 0.0
SYSTEM_NODE_NAMES = {"__start__", "__end__"}
IGNORED_NODE_NAMES = {"supervisor"}
IGNORED_MESSAGE_CONTENT = {"Transferring back to supervisor"}
URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")
# Keyword sets and agent dependencies are owned by intent.py so that
# rich_builder.py classifies the same way the supervisor planner does.
AGENT_SERVER_DEPENDENCIES = _INTENT_AGENT_DEPS


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    agents_used: list[str] = Field(default_factory=list)
    rich: dict[str, Any] | None = None


def _raise_provider_http_error(exc: Exception) -> None:
    if isinstance(exc, AuthenticationError):
        raise HTTPException(
            status_code=401,
            detail="OpenAI authentication failed. Check the OPENAI_API_KEY configured for the backend.",
        ) from exc
    if isinstance(exc, RateLimitError):
        raise HTTPException(
            status_code=429,
            detail="OpenAI rate limit reached. Please wait a moment and try again.",
        ) from exc
    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        raise HTTPException(
            status_code=503,
            detail="OpenAI connection failed. Please check internet access or try again shortly.",
        ) from exc
    if isinstance(exc, TimeoutError):
        raise HTTPException(
            status_code=504,
            detail="The analysis stalled for too long and timed out. Please retry the query.",
        ) from exc
    raise HTTPException(status_code=500, detail=f"Agent error: {str(exc)}") from exc


async def _get_graph():
    """Lazily build the graph on first use."""
    global _graph, _graph_available_agents, _graph_unavailable_servers, _graph_last_build_attempt
    needs_build = _graph is None
    if _graph is not None and getattr(_graph, "is_fallback", False):
        needs_build = (time.time() - _graph_last_build_attempt) >= GRAPH_REBUILD_COOLDOWN_SECONDS

    if needs_build:
        async with _graph_lock:
            needs_build = _graph is None
            if _graph is not None and getattr(_graph, "is_fallback", False):
                needs_build = (time.time() - _graph_last_build_attempt) >= GRAPH_REBUILD_COOLDOWN_SECONDS
            if needs_build:
                from graph import build_oracle_graph

                logger.info("Building ORACLE graph...")
                _graph_last_build_attempt = time.time()
                _graph = await build_oracle_graph()
                _graph_available_agents = list(getattr(_graph, "available_agents", []) or [])
                _graph_unavailable_servers = dict(getattr(_graph, "unavailable_servers", {}) or {})
                logger.info(
                    "ORACLE graph ready | fallback=%s | available_agents=%s",
                    getattr(_graph, "is_fallback", False),
                    _graph_available_agents,
                )
    return _graph


def _humanize_agent_name(name: str) -> str:
    return name.replace("_", " ").strip()


def _normalize_message_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def _extract_domains_from_text(text: str) -> list[str]:
    domains: list[str] = []
    for match in URL_PATTERN.findall(text):
        hostname = urlparse(match).hostname or ""
        hostname = hostname.lower().removeprefix("www.")
        if hostname:
            domains.append(hostname)
    return domains


def _collect_domains(value: object) -> list[str]:
    domains: list[str] = []
    if isinstance(value, dict):
        for nested in value.values():
            domains.extend(_collect_domains(nested))
    elif isinstance(value, list):
        for nested in value:
            domains.extend(_collect_domains(nested))
    elif isinstance(value, str):
        domains.extend(_extract_domains_from_text(value))
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                domains.extend(_collect_domains(json.loads(stripped)))
            except Exception:
                pass
    return domains


def _extract_source_domains_from_tool_payload(payload: object) -> list[str]:
    if not isinstance(payload, dict) or "messages" not in payload:
        return []

    domains: list[str] = []
    for msg in payload["messages"]:
        domains.extend(_collect_domains(getattr(msg, "content", None)))
        domains.extend(_collect_domains(getattr(msg, "artifact", None)))
        structured = getattr(msg, "structured_content", None)
        domains.extend(_collect_domains(structured))

    deduped: list[str] = []
    seen = set()
    for domain in domains:
        if domain not in seen:
            seen.add(domain)
            deduped.append(domain)
    return deduped


def _available_and_missing_agents(graph: object, message: str) -> tuple[list[str], list[str]]:
    planned_agents = _planned_agents_for_message(message)
    available_agents_raw = getattr(graph, "available_agents", None)
    if not available_agents_raw:
        available_agents_raw = _graph_available_agents or planned_agents
    available_agents = set(available_agents_raw)
    runnable_agents = [agent for agent in planned_agents if agent in available_agents]
    missing_agents = []
    if getattr(graph, "available_agents", None) or _graph_available_agents:
        missing_agents = [agent for agent in planned_agents if agent not in available_agents]
    return runnable_agents, missing_agents


def _missing_agent_details(graph: object, missing_agents: list[str]) -> list[str]:
    unavailable_servers = getattr(graph, "unavailable_servers", {}) or _graph_unavailable_servers
    details: list[str] = []
    for agent in missing_agents:
        deps = AGENT_SERVER_DEPENDENCIES.get(agent, [])
        missing_servers = [server for server in deps if server in unavailable_servers]
        if missing_servers:
            server_detail = ", ".join(
                f"{server} ({unavailable_servers[server]})" for server in missing_servers
            )
            details.append(f"{agent}: {server_detail}")
        else:
            details.append(agent)
    return details


def _augment_query_for_routing(graph: object, message: str) -> tuple[str, list[str], list[str]]:
    """Add deterministic routing hints using only agents that actually exist in this graph."""
    runnable_agents, missing_agents = _available_and_missing_agents(graph, message)

    if not runnable_agents and not missing_agents:
        return message, [], []

    hints: list[str] = []
    if runnable_agents:
        hints.append(
            "Runtime routing instruction for supervisor: "
            f"You must consult these available agents in this run before finalizing the answer: {', '.join(runnable_agents)}. "
            "Avoid unnecessary extra handoffs beyond these agents unless one of them clearly cannot complete the task."
        )
    if missing_agents:
        missing_details = _missing_agent_details(graph, missing_agents)
        hints.append(
            "Some planned specialists are not available in this backend run. "
            f"Do not refuse the query just because of that. Continue with the available agents and, if relevant, mention only this exact missing coverage: {', '.join(missing_details)}."
        )
    return message + "\n\n" + "\n".join(hints), runnable_agents, missing_agents


def _is_calculation_valuation_query(lower: str) -> bool:
    # Thin wrapper for backwards-compatibility callers in this module.
    return _intent_is_calculation_valuation_query(lower)


def _planned_agents_for_message(message: str) -> list[str]:
    return _intent_planned_agents(message)


def _iter_graph_entries(raw_event: object):
    """Normalize LangGraph events from both root and subgraph streams."""
    path: tuple[object, ...] = ()
    payload = raw_event

    if isinstance(raw_event, tuple) and len(raw_event) == 2:
        maybe_path, maybe_payload = raw_event
        if isinstance(maybe_path, tuple) and isinstance(maybe_payload, dict):
            path = maybe_path
            payload = maybe_payload

    if not isinstance(payload, dict):
        return

    path_node = None
    if path:
        last = path[-1]
        if isinstance(last, str):
            path_node = last.split(":", 1)[0]

    for payload_key, value in payload.items():
        if payload_key in SYSTEM_NODE_NAMES:
            continue
        if payload_key in {"agent", "tools"} and path_node:
            node_name = path_node
        elif isinstance(payload_key, str):
            node_name = payload_key.split(":", 1)[0]
        else:
            node_name = path_node
        yield path, node_name, payload_key, value


def _extract_message_content(payload: object) -> tuple[str, bool, bool]:
    """Return content, whether it is a final text reply, and whether messages exist."""
    if not isinstance(payload, dict) or "messages" not in payload or not payload["messages"]:
        return "", False, False

    last_msg = payload["messages"][-1]
    content = _normalize_message_content(getattr(last_msg, "content", ""))
    tool_calls = bool(getattr(last_msg, "tool_calls", None))
    response_metadata = getattr(last_msg, "response_metadata", {}) or {}
    is_handoff = bool(response_metadata.get("__is_handoff_back"))
    is_final_text = bool(content and not tool_calls and not is_handoff and content not in IGNORED_MESSAGE_CONTENT)
    return content, is_final_text, True


def _collect_tool_outputs(node_name: str | None, payload: object, sink: list[rich_builder.ToolOutput]) -> None:
    """Inspect a LangGraph node payload and persist any ToolMessage content.

    LangGraph emits a `tools` payload after a sub-agent's ReAct tool node fires.
    The payload's last `ToolMessage` carries `name`, the tool's JSON-text output,
    and (sometimes) the args. We capture all of them so rich_builder can later
    rebuild structured visuals without re-calling MCP tools.
    """
    if not isinstance(payload, dict):
        return
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return
    for msg in messages:
        # langchain ToolMessage exposes: name, content, tool_call_id, status
        name = getattr(msg, "name", None)
        if not name:
            # `tool_calls` on AIMessage carries name + args; capture as a stub so
            # rich_builder.extract_symbols can read the requested symbol.
            tool_calls = getattr(msg, "tool_calls", None) or []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    tc_name = tc.get("name")
                    tc_args = tc.get("args") or tc.get("arguments") or {}
                    if isinstance(tc_args, str):
                        try:
                            tc_args = json.loads(tc_args)
                        except Exception:
                            tc_args = {"raw": tc_args}
                    if tc_name:
                        sink.append(rich_builder.ToolOutput(
                            agent=node_name,
                            name=tc_name,
                            args=tc_args if isinstance(tc_args, dict) else {},
                            content=None,
                        ))
            continue
        content = getattr(msg, "content", None)
        # Tool args are usually not on the ToolMessage; look back through earlier
        # AIMessages in the same payload for the matching tool_call_id.
        args: dict[str, Any] = {}
        tool_call_id = getattr(msg, "tool_call_id", None)
        if tool_call_id:
            for prev in messages:
                tool_calls = getattr(prev, "tool_calls", None) or []
                for tc in tool_calls:
                    if isinstance(tc, dict) and tc.get("id") == tool_call_id:
                        raw_args = tc.get("args") or tc.get("arguments") or {}
                        if isinstance(raw_args, str):
                            try:
                                raw_args = json.loads(raw_args)
                            except Exception:
                                raw_args = {"raw": raw_args}
                        if isinstance(raw_args, dict):
                            args = raw_args
                        break
        sink.append(rich_builder.ToolOutput(
            agent=node_name,
            name=name,
            args=args,
            content=content,
        ))


async def _iter_graph_events_with_timeouts(graph: object, routed_message: str):
    """Iterate graph events with separate total-run and idle-event timeouts."""
    event_iter = graph.astream({"messages": [HumanMessage(content=routed_message)]}, subgraphs=True).__aiter__()
    async with asyncio.timeout(GRAPH_RUN_TIMEOUT_SECONDS):
        while True:
            try:
                async with asyncio.timeout(GRAPH_IDLE_TIMEOUT_SECONDS):
                    raw_event = await event_iter.__anext__()
            except StopAsyncIteration:
                break
            yield raw_event


async def _execute_graph(message: str) -> tuple[str, list[str], rich_builder.RichResponse | None]:
    """Run the graph and return the final reply, sub-agents used, and rich payload."""
    graph = await _get_graph()
    routed_message, planned_agents, missing_agents = _augment_query_for_routing(graph, message)
    started_at = time.perf_counter()
    agents_used: list[str] = []
    seen_agents: set[str] = set()
    tool_outputs: list[rich_builder.ToolOutput] = []
    final_content = ""
    last_nonempty_content = ""

    try:
        logger.info(
            "Graph execute start | planned_agents=%s | missing_agents=%s",
            planned_agents,
            missing_agents,
        )
        async for raw_event in _iter_graph_events_with_timeouts(graph, routed_message):
            for _, node_name, payload_key, payload in _iter_graph_entries(raw_event):
                if node_name and node_name not in IGNORED_NODE_NAMES and node_name not in seen_agents:
                    seen_agents.add(node_name)
                    agents_used.append(node_name)
                    logger.info("Graph execute agent_seen | agent=%s", node_name)

                if payload_key == "tools" and node_name not in IGNORED_NODE_NAMES:
                    _collect_tool_outputs(node_name, payload, tool_outputs)

                content, is_final_text, has_messages = _extract_message_content(payload)
                if has_messages and content:
                    last_nonempty_content = content
                if node_name == "supervisor" and is_final_text:
                    final_content = content
        logger.info(
            "Graph execute done | elapsed=%.2fs | agents_used=%s | tool_outputs=%d",
            time.perf_counter() - started_at,
            agents_used,
            len(tool_outputs),
        )
    except Exception as exc:
        logger.error(
            "Graph execution error | elapsed=%.2fs | error=%s",
            time.perf_counter() - started_at,
            exc,
            exc_info=True,
        )
        _raise_provider_http_error(exc)

    reply = final_content or last_nonempty_content or "I couldn't generate a response."
    rich = rich_builder.build(message, tool_outputs, agents_used, reply)
    return reply, agents_used, rich


async def _stream_graph_run(message: str) -> AsyncIterator[dict]:
    """Yield progress events followed by the final response payload."""
    graph = await _get_graph()
    routed_message, planned_agents, missing_agents = _augment_query_for_routing(graph, message)
    started_at = time.perf_counter()
    agents_used: list[str] = []
    seen_agents: set[str] = set()
    started_agents: set[str] = set()
    completed_agents: set[str] = set()
    seen_source_domains: set[str] = set()
    tool_outputs: list[rich_builder.ToolOutput] = []
    final_content = ""
    last_nonempty_content = ""

    yield {"type": "status", "label": "Routing query"}
    for agent in planned_agents:
        yield {
            "type": "agent_planned",
            "agent": agent,
            "label": f"{_humanize_agent_name(agent)} planned",
        }
    if missing_agents:
        yield {
            "type": "status",
            "label": "Some specialists are unavailable in this run. Continuing with the available agents.",
        }
        for detail in _missing_agent_details(graph, missing_agents):
            missing_agent_name = detail.split(":", 1)[0].strip()
            yield {
                "type": "agent_unavailable",
                "agent": missing_agent_name,
                "label": f"{_humanize_agent_name(missing_agent_name)} unavailable",
                "message": detail,
            }
    logger.info(
        "Graph stream start | planned_agents=%s | missing_agents=%s",
        planned_agents,
        missing_agents,
    )

    try:
        async for raw_event in _iter_graph_events_with_timeouts(graph, routed_message):
            for path, node_name, payload_key, payload in _iter_graph_entries(raw_event):
                if not node_name:
                    continue

                if node_name not in IGNORED_NODE_NAMES and node_name not in seen_agents:
                    seen_agents.add(node_name)
                    agents_used.append(node_name)

                if node_name not in IGNORED_NODE_NAMES and node_name not in started_agents:
                    started_agents.add(node_name)
                    logger.info("Graph stream agent_started | agent=%s", node_name)
                    yield {
                        "type": "agent_started",
                        "agent": node_name,
                        "label": f"{_humanize_agent_name(node_name)} started",
                    }

                if payload_key == "tools" and node_name not in IGNORED_NODE_NAMES:
                    logger.info("Graph stream tool_call | agent=%s", node_name)
                    yield {
                        "type": "agent_tool",
                        "agent": node_name,
                        "label": f"{_humanize_agent_name(node_name)} is calling tools",
                    }
                    _collect_tool_outputs(node_name, payload, tool_outputs)
                    for domain in _extract_source_domains_from_tool_payload(payload):
                        if domain not in seen_source_domains:
                            seen_source_domains.add(domain)
                            yield {
                                "type": "source",
                                "agent": node_name,
                                "domain": domain,
                                "label": f"Retrieving data from {domain}",
                            }

                content, is_final_text, has_messages = _extract_message_content(payload)
                if has_messages and content:
                    last_nonempty_content = content

                if node_name == "supervisor" and is_final_text:
                    final_content = content

                if (
                    node_name not in IGNORED_NODE_NAMES
                    and is_final_text
                    and node_name not in completed_agents
                    and payload_key == "agent"
                    and path
                ):
                    completed_agents.add(node_name)
                    logger.info("Graph stream agent_completed | agent=%s", node_name)
                    yield {
                        "type": "agent_completed",
                        "agent": node_name,
                        "label": f"{_humanize_agent_name(node_name)} completed",
                    }
    except Exception as exc:
        logger.error(
            "Graph streaming error | elapsed=%.2fs | error=%s",
            time.perf_counter() - started_at,
            exc,
            exc_info=True,
        )
        # Reset cached graph so the next request rebuilds cleanly when an MCP
        # server has gone down mid-run.
        global _graph
        _graph = None
        if isinstance(exc, AuthenticationError):
            error_message = "OpenAI authentication failed. Check the backend API key."
        elif isinstance(exc, RateLimitError):
            error_message = "OpenAI rate limit reached. Please wait a moment and try again."
        elif isinstance(exc, (APIConnectionError, APITimeoutError)):
            error_message = "OpenAI connection failed. Please check internet access or try again shortly."
        elif isinstance(exc, TimeoutError):
            error_message = "The analysis stalled for too long and timed out. Please retry the query."
        else:
            error_message = f"Agent error: {str(exc)}"
        yield {"type": "error", "message": error_message}
        return

    reply = final_content or last_nonempty_content or "I couldn't generate a response."
    
    # Visuals explicitly disabled per user request
    rich_payload = None

    logger.info(
        "Graph stream done | elapsed=%.2fs | agents_used=%s | tool_outputs=%d | rich_mode=disabled",
        time.perf_counter() - started_at,
        agents_used,
        len(tool_outputs),
    )
    yield {
        "type": "final",
        "reply": reply,
        "agents_used": agents_used,
        "rich": rich_payload,
    }


def _to_sse(event: dict) -> str:
    event_type = event.get("type", "message")
    return f"event: {event_type}\ndata: {json.dumps(event)}\n\n"


@app.get("/health")
async def health():
    return {"status": "ok", "service": "oracle-fios"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Send a message to ORACLE and get a normal JSON response."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    logger.info("User query: %s", req.message[:100])
    try:
        reply, agents_used, rich = await _execute_graph(req.message)
        return ChatResponse(
            reply=reply,
            agents_used=agents_used,
            rich=rich.model_dump(mode="json") if rich is not None else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Top level error in chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health/mcp")
async def mcp_health() -> dict[str, Any]:
    """Probe each configured MCP server and report up/down.

    The frontend uses this on page load to display a banner when one or more
    MCP servers are offline so the user knows why visuals may be missing.
    """
    results: dict[str, dict[str, Any]] = {}

    async def _check(name: str, cfg: dict[str, Any]) -> None:
        url = cfg.get("url", "")
        # FastMCP exposes /mcp; an OPTIONS or HEAD usually returns 200/405.
        check_url = url.rsplit("/mcp", 1)[0] if url.endswith("/mcp") else url
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                try:
                    r = await client.get(check_url + "/health")
                    ok = 200 <= r.status_code < 500
                except Exception:
                    # Fall back to bare connect on the /mcp endpoint
                    r = await client.get(url)
                    ok = 200 <= r.status_code < 500
            results[name] = {
                "ok": ok,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                "url": url,
            }
        except Exception as exc:
            results[name] = {
                "ok": False,
                "error": str(exc),
                "url": url,
            }

    await asyncio.gather(*(_check(name, cfg) for name, cfg in MCP_SERVERS.items()))
    all_ok = all(v.get("ok") for v in results.values())
    return {"all_ok": all_ok, "servers": results}


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """Send a message to ORACLE and stream agent progress to the frontend."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    logger.info("Streaming user query: %s", req.message[:100])

    async def event_stream():
        async for event in _stream_graph_run(req.message):
            yield _to_sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api:app", host="0.0.0.0", port=8080, reload=True)

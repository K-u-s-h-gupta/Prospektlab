"""Conversational chat responder — a finance-specialised chat model.

Chat mode is NOT research. It must behave like Claude/Gemini: a direct,
streamed, conversational answer, grounded with light real-time market data
when the question is about a specific company — and it must NOT produce a
formal research memo/report artifact, run specialists, scrape broadly, or
build charts/tables.

This path replaces routing chat through the heavy `run_research_session`
pipeline. It streams tokens over the SSE BUS and persists the answer to the
session memo file purely so chat history + the result endpoint keep working.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone

from finagent.events import BUS
from finagent.geo import resolve_entity
from finagent.prompt_builder import default_system_prompt
from finagent.runtime_provider import (
    is_content_filter_error,
    resolve_openai_config,
    resolve_openai_fallback_config,
)

logger = logging.getLogger("finagent.chat_reply")


_CHAT_STYLE = """
You are answering in CONVERSATIONAL CHAT mode — behave like a high-quality chat
assistant (Claude/Gemini class) specialised in Indian capital markets.

RULES:
- Answer the user's question directly in the first sentence. Natural, fluid prose.
- This is a conversation, NOT a report. Do NOT emit report scaffolding, fixed
  corporate section headers, executive summaries, or a formal memo layout.
- Do NOT emit chart/kpi/table fenced blocks. Plain prose; a short inline bullet
  list only if it genuinely clarifies the answer.
- Keep it concise and useful. Match the scope of the question — short question,
  short answer. Don't pad.
- Use INR (₹, crore/lakh) for Indian figures. Ground numbers in the FACTS block
  when present; if a figure isn't in the facts and you aren't sure, say so
  briefly rather than inventing it.
- No buy/sell/hold calls or price targets (SEBI-safe). You may discuss valuation
  context and trade-offs.
- Maintain prior conversation context smoothly; don't restate basics already covered.
"""


async def _fast_grounding(target: str, timeout_s: float = 5.0) -> tuple[str, list[str]]:
    """Best-effort light grounding for a single entity. Returns (facts, sources)."""
    try:
        entity = resolve_entity(target)
    except Exception:
        return "", []
    if not entity or not getattr(entity, "ticker_label", None):
        return "", []

    from finagent.tools.data import fetch_india_snapshot, fetch_news, fetch_yahoo_quote

    label = entity.ticker_label

    async def _quote():
        try:
            return await asyncio.wait_for(fetch_yahoo_quote(label), timeout=timeout_s)
        except Exception:
            return None

    async def _india():
        try:
            return await asyncio.wait_for(fetch_india_snapshot(label), timeout=timeout_s)
        except Exception:
            return None

    async def _news():
        try:
            return await asyncio.wait_for(fetch_news(label), timeout=timeout_s)
        except Exception:
            return []

    quote, india, news = await asyncio.gather(_quote(), _india(), _news())

    lines: list[str] = []
    sources: list[str] = []
    name = getattr(entity, "canonical_name", None) or target
    if quote is not None:
        if getattr(quote, "price", None) is not None:
            chg = f" ({quote.change_pct:+.2f}%)" if getattr(quote, "change_pct", None) is not None else ""
            lines.append(f"{name} last price: {quote.currency or ''} {quote.price:,.2f}{chg}.")
        if getattr(quote, "market_cap", None):
            lines.append(f"Market cap: {quote.market_cap:,.0f}.")
        metrics = getattr(quote, "financial_metrics", None) or {}
        for label_, key in (("trailing P/E", "trailing_pe"), ("P/B", "price_to_book"), ("ROE", "return_on_equity")):
            v = metrics.get(key)
            if v is not None:
                lines.append(f"{label_}: {v:.2f}" + ("%" if key == "return_on_equity" else "x"))
        if getattr(quote, "source_url", None):
            sources.append(quote.source_url)
    if india is not None:
        summary = getattr(india, "summary", None) or getattr(india, "about", None)
        if summary:
            lines.append(f"Profile: {str(summary)[:300]}")
    if news:
        for item in news[:4]:
            title = getattr(item, "title", None) or (item.get("title") if isinstance(item, dict) else None)
            if title:
                lines.append(f"News: {title}")
            url = getattr(item, "url", None) or (item.get("url") if isinstance(item, dict) else None)
            if url:
                sources.append(url)

    facts = "\n".join(f"- {ln}" for ln in lines)
    return facts, sources[:8]


def _build_messages(objective: str, facts: str, chat_history: list[dict] | None) -> list[dict]:
    system = default_system_prompt() + "\n" + _CHAT_STYLE
    messages = [{"role": "system", "content": system}]
    for turn in (chat_history or [])[-6:]:
        role = turn.get("role")
        content = turn.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content[:4000]})
    user = objective
    if facts:
        user = (
            f"FACTS (verified real-time market data — ground your answer in these):\n{facts}\n\n"
            f"User question: {objective}"
        )
    messages.append({"role": "user", "content": user})
    return messages


async def _stream_completion(messages: list[dict], emit, *, max_tokens: int = 1100) -> str:
    """Stream a chat completion, emitting memo_token chunks. Azure→public fallback."""
    from openai import AsyncOpenAI

    cfg = resolve_openai_config("moderate")
    if cfg is None:
        raise RuntimeError("No LLM provider configured — set OPENAI_API_KEY or XAI_API_KEY")

    async def _run(config) -> str:
        client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        chunks: list[str] = []
        stream = await client.chat.completions.create(
            model=config.model,
            temperature=0.3,
            max_completion_tokens=max_tokens,
            stream=True,
            messages=messages,
        )
        async for event in stream:
            if not event.choices:
                continue
            text = getattr(event.choices[0].delta, "content", None) or ""
            if text:
                chunks.append(text)
                emit("memo_token", chunk=text)
        return "".join(chunks).strip()

    try:
        return await _run(cfg)
    except Exception as exc:
        if is_content_filter_error(exc):
            fb = resolve_openai_fallback_config("moderate")
            if fb is not None:
                logger.warning("[CHAT_REPLY] content filter hit, retrying on fallback provider")
                return await _run(fb)
        raise


async def _run_tool_rounds(messages: list[dict], toolbox, emit, *, max_rounds: int = 3) -> None:
    """Let the model call finance tools to ground its answer. Mutates `messages`.

    Non-streaming rounds: the model picks tools, we execute them, append the
    results, and loop until it stops requesting tools or the round cap is hit.
    The final answer is streamed separately by the caller.
    """
    from openai import AsyncOpenAI

    from finagent.chat_tools import CHAT_TOOL_SPECS

    cfg = resolve_openai_config("simple")  # cheap tier for tool selection
    if cfg is None:
        return
    client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)

    for _ in range(max_rounds):
        try:
            resp = await client.chat.completions.create(
                model=cfg.model,
                messages=messages,
                tools=CHAT_TOOL_SPECS,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=600,
            )
        except Exception as exc:
            logger.warning("[CHAT_REPLY] tool round failed: %s", exc)
            return
        msg = resp.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None)
        if not tool_calls:
            return  # model has enough context; caller streams the answer

        messages.append({
            "role": "assistant",
            "content": msg.content or None,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            emit("tool_use", tool=name, args=args)
            result = await toolbox.execute(name, args)
            emit("tool_result", tool=name)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})


async def run_chat_reply(
    target: str,
    objective: str,
    *,
    session_id: str,
    user_email: str | None = None,
    chat_history: list[dict] | None = None,
    max_wall_seconds: float = 18.0,
) -> str:
    """Produce a streamed conversational finance answer (no memo/report)."""
    emit = lambda event_type, **kwargs: BUS.emit(session_id, event_type, **kwargs)
    t0 = time.perf_counter()

    emit("phase", phase="chat", note="Answering")

    sources: list[dict] = []
    agentic = os.environ.get("FINAGENT_CHAT_AGENTIC", "1") == "1"

    if agentic:
        # Agentic path: the model calls live finance tools (quote, shareholding,
        # IKG governance, filings, news, web search) to ground + cite, then we
        # stream the final answer. This is the Perplexity/Google-Finance beater.
        from finagent.chat_tools import ChatToolbox
        toolbox = ChatToolbox()
        messages = _build_messages(objective, "", chat_history)
        try:
            await asyncio.wait_for(
                _run_tool_rounds(messages, toolbox, emit),
                timeout=max(12.0, max_wall_seconds),
            )
        except Exception as exc:
            logger.warning("[CHAT_REPLY] tool grounding failed: %s", exc)
        sources = toolbox.citations
        if sources:
            messages.append({
                "role": "system",
                "content": "Write the final answer now using the tool results above. "
                           "Ground every specific number/fact in those results.",
            })
    else:
        # Lightweight fallback: single blind pre-fetch, no tool loop.
        facts = ""
        if target:
            try:
                facts, src = await _fast_grounding(target, timeout_s=min(6.0, max_wall_seconds * 0.4))
                sources = [{"title": u, "url": u} for u in src]
            except Exception as exc:
                logger.warning("[CHAT_REPLY] grounding failed: %s", exc)
        messages = _build_messages(objective, facts, chat_history)

    try:
        answer = await asyncio.wait_for(
            _stream_completion(messages, emit),
            timeout=max(12.0, max_wall_seconds),
        )
    except Exception as exc:
        logger.exception("[CHAT_REPLY] completion failed")
        emit("error", message=f"Chat reply failed: {exc}")
        emit("done", message="chat error")
        raise

    answer = (answer or "").strip()
    if not answer:
        answer = "I couldn't generate a response for that. Could you rephrase your question?"

    # Persist for chat history + result endpoint (NOT a research memo).
    try:
        from finagent.paths import finagent_data_path
        memos_dir = finagent_data_path("memos")
        memos_dir.mkdir(parents=True, exist_ok=True)
        (memos_dir / f"{session_id}.md").write_text(answer, encoding="utf-8")
    except Exception:
        logger.exception("[CHAT_REPLY] failed to persist chat answer")

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    preview = answer[:2400]
    emit(
        "memo",
        target=target,
        memo=answer,
        preview=preview,
        via="chat",
        elapsed_ms=elapsed_ms,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    emit(
        "final",
        target=target,
        canonical=target,
        output_mode="conversational_chat",
        response_depth="chat",
        is_chat_reply=True,
        memo=answer,
        memo_preview=preview,
        elapsed_ms=elapsed_ms,
        sources=sources,
        rich={"title": "", "markdown_body": answer},
    )
    emit("done", message="chat complete")
    return answer


__all__ = ["run_chat_reply"]

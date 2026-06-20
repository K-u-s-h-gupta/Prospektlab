"""Shared LLM call helper for the swarm (planner + per-agent reasoning).

`resolve_openai_config` returns an `OpenAIConfig` (api_key/model/base_url) — it
does NOT expose a `.client`. Building the AsyncOpenAI client is the caller's job;
centralising it here so the planner and the agent-reasoning layer share one
content-filter-aware path instead of each re-deriving (and mis-deriving) it.
"""

from __future__ import annotations

import logging

from finagent.runtime_provider import (
    is_content_filter_error,
    resolve_openai_config,
    resolve_openai_fallback_config,
)

logger = logging.getLogger("finagent.swarm.llm")


def _build_client(cfg):
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)


async def swarm_chat(
    system: str,
    user: str,
    *,
    complexity: str = "moderate",
    model: str | None = None,
    json_mode: bool = False,
    max_tokens: int = 1500,
    temperature: float = 0.2,
) -> str:
    """Single chat completion with Azure→public-OpenAI content-filter fallback.

    Returns the message content (possibly empty string). Raises only when no
    provider is configured at all; transient/filter errors are retried on the
    fallback provider before propagating.
    """
    cfg = resolve_openai_config(complexity)
    if cfg is None:
        raise RuntimeError("No LLM provider configured — set OPENAI_API_KEY or XAI_API_KEY")

    kwargs = {
        "model": model or cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        client = _build_client(cfg)
        resp = await client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""
    except Exception as exc:
        # Azure foundry aggressively flags benign finance prompts. Retry on the
        # public OpenAI endpoint when available before giving up.
        if is_content_filter_error(exc):
            fb = resolve_openai_fallback_config(complexity)
            if fb is not None:
                logger.warning("[SWARM_LLM] content filter hit, retrying on fallback provider")
                kwargs["model"] = model if (model and fb.model) else fb.model
                client = _build_client(fb)
                resp = await client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content or ""
        raise


__all__ = ["swarm_chat"]

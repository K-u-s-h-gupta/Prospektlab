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


def _needs_completion_tokens(model: str) -> bool:
    """OpenAI reasoning / GPT-5 family reject `max_tokens` (require
    `max_completion_tokens`) and only allow the default temperature."""
    m = (model or "").lower()
    return m.startswith(("gpt-5", "gpt5", "o1", "o3", "o4"))


def _token_kwargs(model: str, max_tokens: int, temperature: float) -> dict:
    """Pick the param names this model family accepts."""
    if _needs_completion_tokens(model):
        # Reasoning models: completion-token cap, default temperature only.
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens, "temperature": temperature}


def _adapt_unsupported_params(kwargs: dict, exc: Exception) -> dict | None:
    """Reactive safety net: if the API rejects a param as unsupported, swap to
    the accepted form and signal a retry. Returns adapted kwargs or None."""
    msg = str(getattr(exc, "message", "") or exc).lower()
    if "unsupported" not in msg and "not supported" not in msg and "invalid_request" not in msg:
        return None
    new = dict(kwargs)
    changed = False
    if "max_tokens" in msg and "max_tokens" in new:
        new["max_completion_tokens"] = new.pop("max_tokens")
        changed = True
    if "temperature" in msg and "temperature" in new:
        new.pop("temperature", None)
        changed = True
    return new if changed else None


async def _create(client, kwargs: dict):
    """chat.completions.create with up to 2 param-adaptation retries."""
    attempt = dict(kwargs)
    last_exc: Exception | None = None
    for _ in range(3):
        try:
            return await client.chat.completions.create(**attempt)
        except Exception as exc:  # noqa: BLE001
            adapted = _adapt_unsupported_params(attempt, exc)
            if adapted is None:
                raise
            logger.warning("[SWARM_LLM] adapting unsupported params and retrying")
            attempt = adapted
            last_exc = exc
    if last_exc:
        raise last_exc


def loads_lenient(content: str) -> dict:
    """Parse a JSON object from an LLM response, tolerating trailing prose or
    code fences. Some models emit reasoning/text after the JSON even in
    json_object mode, which makes a bare json.loads raise 'Extra data'."""
    import json

    text = (content or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    # Strip ```json fences if present.
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        text = text[4:] if text.lower().startswith("json") else text
    # Take the first balanced {...} block.
    start = text.find("{")
    if start == -1:
        return {}
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except Exception:
                    return {}
    return {}


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

    model_name = model or cfg.model
    kwargs = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        **_token_kwargs(model_name, max_tokens, temperature),
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        client = _build_client(cfg)
        resp = await _create(client, kwargs)
        return resp.choices[0].message.content or ""
    except Exception as exc:
        # Azure foundry aggressively flags benign finance prompts. Retry on the
        # public OpenAI endpoint when available before giving up.
        if is_content_filter_error(exc):
            fb = resolve_openai_fallback_config(complexity)
            if fb is not None:
                logger.warning("[SWARM_LLM] content filter hit, retrying on fallback provider")
                fb_model = model if (model and fb.model) else fb.model
                kwargs["model"] = fb_model
                # Re-pick token params for the fallback model's family.
                kwargs.pop("max_tokens", None)
                kwargs.pop("max_completion_tokens", None)
                kwargs.pop("temperature", None)
                kwargs.update(_token_kwargs(fb_model, max_tokens, temperature))
                client = _build_client(fb)
                resp = await _create(client, kwargs)
                return resp.choices[0].message.content or ""
        raise


__all__ = ["swarm_chat"]

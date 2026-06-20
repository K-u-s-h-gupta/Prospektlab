"""Resolve LLM provider configuration (Azure Foundry/OpenAI primary, xAI fallback).

Default model routing (cheap subagents, separate synthesis model):
- micro    -> gpt-4o-mini  (FINAGENT_OPENAI_MODEL_MICRO/_NANO — news triage, sentiment, tagging)
- simple   -> gpt-4o-mini  (FINAGENT_OPENAI_MODEL_SIMPLE)
- moderate -> gpt-4o-mini  (FINAGENT_OPENAI_MODEL)
- complex  -> gpt-4o-mini  (FINAGENT_OPENAI_MODEL)

Synthesis/final-report generation is controlled separately by FINAGENT_SYNTH_MODEL
and defaults to gpt-5.4-mini. The "micro" tier lets the high-volume, low-reasoning
agents point at a cheaper model via env without changing analysis-heavy agents.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

_XAI_BASE_URL = "https://api.x.ai/v1"


@dataclass
class OpenAIConfig:
    api_key: str
    model: str = "gpt-4o-mini"
    base_url: str | None = None


class ChatCompleter(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


def _normalize_openai_base_url(raw: str | None) -> str | None:
    value = (raw or "").strip().rstrip("/")
    if not value:
        return None
    lowered = value.lower()
    for suffix in ("/responses", "/chat/completions", "/embeddings"):
        if lowered.endswith(suffix):
            value = value[: -len(suffix)].rstrip("/")
            lowered = value.lower()
            break
    if lowered.endswith("/openai/v1") or lowered.endswith("/v1"):
        return value
    if "/openai/" in lowered:
        marker = lowered.find("/openai/")
        return f"{value[:marker]}/openai/v1"
    return f"{value}/openai/v1"


def _resource_to_openai_base_url(raw: str | None) -> str | None:
    value = (raw or "").strip().rstrip("/")
    if not value:
        return None
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/openai/v1"


def _resolve_azure_foundry_openai_config(complexity: str = "moderate") -> OpenAIConfig | None:
    key = (
        os.getenv("AZURE_AI_FOUNDRY_API_KEY")
        or os.getenv("AZURE_AI_PROJECTS_API_KEY")
        or os.getenv("AZURE_OPENAI_API_KEY")
        or ""
    ).strip()
    if not key:
        return None

    base_url = _normalize_openai_base_url(
        os.getenv("AZURE_AI_FOUNDRY_OPENAI_BASE_URL")
        or os.getenv("AZURE_AI_PROJECTS_OPENAI_BASE_URL")
        or os.getenv("AZURE_OPENAI_BASE_URL")
    )
    if not base_url:
        base_url = _resource_to_openai_base_url(
            os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
            or os.getenv("AZURE_AI_PROJECT_ENDPOINT")
            or os.getenv("AZURE_OPENAI_ENDPOINT")
        )
    if not base_url:
        return None

    deployment = (
        os.getenv("AZURE_AI_FOUNDRY_CHAT_DEPLOYMENT")
        or os.getenv("AZURE_AI_FOUNDRY_TEXT_DEPLOYMENT")
        or os.getenv("AZURE_AI_PROJECTS_CHAT_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_DEPLOYMENT")
        or "gpt-4o-mini"
    ).strip()

    if complexity == "micro":
        model = (
            os.getenv("FINAGENT_OPENAI_MODEL_MICRO")
            or os.getenv("FINAGENT_OPENAI_MODEL_NANO")
            or os.getenv("FINAGENT_OPENAI_MODEL_SIMPLE")
            or os.getenv("FINAGENT_OPENAI_MODEL_MINI")
            or deployment
            or "gpt-4o-mini"
        )
    elif complexity == "simple":
        model = (
            os.getenv("FINAGENT_OPENAI_MODEL_SIMPLE")
            or os.getenv("FINAGENT_OPENAI_MODEL_MINI")
            or deployment
            or "gpt-4o-mini"
        )
    else:
        model = (
            os.getenv("FINAGENT_OPENAI_MODEL")
            or deployment
            or "gpt-4o-mini"
        )

    return OpenAIConfig(api_key=key, model=model, base_url=base_url)


def resolve_openai_fallback_config(complexity: str = "moderate") -> OpenAIConfig | None:
    """Return the non-Azure OpenAI config (sk-proj key, public endpoint).

    Used to retry calls that Azure's content filter rejects with a
    ResponsibleAIPolicyViolation. The Azure foundry deployment in this repo
    aggressively flags benign finance prompts as "jailbreak" — public OpenAI
    has no equivalent filter on chat completions.
    """
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key.startswith("sk-"):
        return None
    if complexity == "micro":
        model = os.getenv("FINAGENT_OPENAI_FALLBACK_MODEL_MICRO") or os.getenv("FINAGENT_OPENAI_FALLBACK_MODEL") or "gpt-4o-mini"
    else:
        model = os.getenv("FINAGENT_OPENAI_FALLBACK_MODEL") or "gpt-4o-mini"
    return OpenAIConfig(api_key=key, model=model)


def is_content_filter_error(exc: BaseException) -> bool:
    """True when an Azure call fails with the ResponsibleAIPolicyViolation tag.

    We check the string form because the openai SDK wraps Azure's payload in
    BadRequestError without exposing the inner code as a structured field.
    """
    text = str(exc) if exc else ""
    return "content_filter" in text or "ResponsibleAIPolicy" in text or "jailbreak" in text.lower()


def is_rate_limit_error(exc: BaseException) -> bool:
    """True when a provider returns a 429-class rate-limit response."""
    text = str(exc) if exc else ""
    return (
        "rate_limit_exceeded" in text
        or "Rate limit reached" in text
        or "429" in text[:60]
        or "TPM" in text
        or "RPM" in text
        or "RPD" in text
    )


def resolve_openai_config(complexity: str = "moderate") -> OpenAIConfig | None:
    """Return config for the primary provider (Azure/OpenAI) or xAI as fallback."""
    if (os.getenv("FINAGENT_BYPASS_AZURE") or "").strip().lower() in {"1", "true", "yes"}:
        fb = resolve_openai_fallback_config(complexity=complexity)
        if fb:
            return fb
    azure_cfg = _resolve_azure_foundry_openai_config(complexity=complexity)
    if azure_cfg:
        return azure_cfg

    key = os.getenv("OPENAI_API_KEY")
    if key:
        base_url = _normalize_openai_base_url(os.getenv("OPENAI_BASE_URL"))
        if complexity == "micro":
            # High-volume, low-reasoning tier (news triage, sentiment, tagging,
            # dedup). Point this at the cheapest capable model to cut token spend
            # without touching analysis-heavy agents. Falls back to the mini tier.
            model = (
                os.getenv("FINAGENT_OPENAI_MODEL_MICRO")
                or os.getenv("FINAGENT_OPENAI_MODEL_NANO")
                or os.getenv("FINAGENT_OPENAI_MODEL_SIMPLE")
                or os.getenv("FINAGENT_OPENAI_MODEL_MINI")
                or "gpt-4o-mini"
            )
        elif complexity == "simple":
            model = (
                os.getenv("FINAGENT_OPENAI_MODEL_SIMPLE")
                or os.getenv("FINAGENT_OPENAI_MODEL_MINI")
                or "gpt-4o-mini"
            )
        else:
            model = (
                os.getenv("FINAGENT_OPENAI_MODEL")
                or "gpt-4o-mini"
            )
        return OpenAIConfig(api_key=key, model=model, base_url=base_url)

    xai_key = os.getenv("XAI_API_KEY")
    if xai_key:
        if complexity in ("micro", "simple"):
            model = os.getenv("FINAGENT_XAI_MODEL_SIMPLE", "grok-3-mini")
        else:
            model = os.getenv("FINAGENT_XAI_MODEL", "grok-3")
        return OpenAIConfig(api_key=xai_key, model=model, base_url=_XAI_BASE_URL)

    return None

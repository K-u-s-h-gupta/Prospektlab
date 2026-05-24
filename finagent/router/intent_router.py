"""Intent router for India-focused FinAgent.

Classifies query complexity and selects which pipeline phases to execute.

IMPORTANT: The Verifier is NEVER skipped regardless of query complexity.
There is intentionally no `skip_verifier` field — financial accuracy
requires verification on every response.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from finagent.geo.entity_resolver import PRONOUN_AND_COMMON_WORDS, ResolvedEntity, resolve_entities
from finagent.router.domain_taxonomy import AGENT_KEYWORDS
from finagent.router.policies import should_enable_deep_research
from finagent.runtime_provider import resolve_openai_config

logger = logging.getLogger("finagent.router.intent_router")

# ── Simple query patterns — skip heavy phases ─────────────────────────────────
_SIMPLE_PATTERNS = (
    "pe ratio", "p/e", "pb ratio", "p/b", "current price", "share price",
    "stock price", "live price", "market cap", "eps", "dividend yield",
    "book value", "52 week", "52-week", "nse price", "bse price",
    "what is the price", "historical price", "price history", "stock history",
    "share price history", "face value", "circuit limit",
)

# Moderate — run 1 deep-dive round, skip blindspot
_MODERATE_PATTERNS = (
    "quarterly results", "earnings", "revenue growth", "profit",
    "net income", "ebitda", "margin", "balance sheet", "cash flow",
    "latest news", "recent news", "sector outlook", "analyst target",
    "shareholding", "fii holding", "dii holding",
)

_FOLLOWUP_PRONOUNS = ("it", "its", "that company", "this company", "same company", "they", "their")
_FOCUS_PATTERNS = {
    "news": ("latest news", "recent news", "news", "headlines", "updates"),
    "valuation": ("valuation", "p/e", "pe ratio", "ev/ebitda", "market cap", "target price", "multiples"),
    "financials": ("financials", "results", "revenue", "profit", "margin", "balance sheet", "cash flow"),
    "price_history": ("historical price", "price history", "stock history", "share price history", "past price"),
    "shareholding": ("shareholding", "promoter", "fii", "dii", "pledge"),
    "risk": ("risk", "red flag", "governance", "lawsuit", "investigation", "penalty"),
}

# Complex / marathon — full pipeline
_COMPLEX_PATTERNS = (
    "deep", "comprehensive", "exhaustive", "due diligence", "full analysis",
    "marathon", "investigate", "compare", "vs ", "versus", "peer analysis",
    "risk factors", "sebi", "fraud", "investigation", "governance",
    "long term", "investment thesis", "initiation", "moat",
)


def _classify_complexity(objective: str) -> str:
    lower = (objective or "").lower()
    if any(p in lower for p in _COMPLEX_PATTERNS):
        return "complex"
    if any(p in lower for p in _SIMPLE_PATTERNS):
        return "simple"
    if any(p in lower for p in _MODERATE_PATTERNS):
        return "moderate"
    return "moderate"  # safe default


@dataclass
class RoutingDecision:
    selected_agents: list[str] = field(default_factory=list)
    confidence: str = "medium"
    selected_tools: list[str] = field(default_factory=list)
    retrieval_plan: list[str] = field(default_factory=list)
    fallback_policy: str = "continue-with-available-evidence"
    deep_research: bool = False
    # ── Complexity-driven phase flags ──────────────────────────────────────
    query_complexity: str = "moderate"   # "simple" | "moderate" | "complex"
    skip_reflection: bool = False        # skip Hermes reflection loop
    skip_blindspot: bool = False         # skip blindspot pass
    skip_deep_dive: bool = False         # skip all deep-dive rounds
    max_deep_dive_rounds: int = 4        # cap deep-dive iterations
    operational_intent: str = "snapshot"
    is_followup: bool = False
    # NOTE: There is intentionally NO skip_verifier field.
    # The verifier ALWAYS runs to protect financial data integrity.


def detect_operational_intent(objective: str, *, has_prior_entity: bool = False) -> tuple[str, bool]:
    """Separate the requested operation from the entity being discussed."""

    lower = (objective or "").lower().strip()
    focus = "snapshot"
    for label, terms in _FOCUS_PATTERNS.items():
        if any(term in lower for term in terms):
            focus = label
            break
    is_followup = has_prior_entity and (
        any(pronoun in lower for pronoun in _FOLLOWUP_PRONOUNS)
        or (focus != "snapshot" and len(lower.split()) <= 8)
    )
    return focus, is_followup


def route_objective(
    objective: str,
    entity: ResolvedEntity,
    *,
    playbook_agents: list[str] | None = None,
    has_prior_entity: bool = False,
) -> RoutingDecision:
    lower = (objective or "").lower()
    operational_intent, is_followup = detect_operational_intent(objective, has_prior_entity=has_prior_entity)

    # Agent selection from keyword taxonomy
    selected: list[str] = []
    for agent, keywords in AGENT_KEYWORDS.items():
        if any(term in lower for term in keywords):
            selected.append(agent)

    # Always include financials for India queries
    if not selected:
        selected = ["financials", "risk", "news"]
    if entity.country_code not in ("US",) and "financials" not in selected:
        selected.append("financials")
    if playbook_agents:
        for agent in playbook_agents:
            if agent not in selected:
                selected.append(agent)

    complexity = "simple" if is_followup and operational_intent in {"news", "valuation", "shareholding", "price_history"} else _classify_complexity(objective)
    deep = should_enable_deep_research(objective)

    # Phase flags based on complexity
    skip_reflection = complexity == "simple"
    skip_blindspot  = complexity in ("simple", "moderate")
    skip_deep_dive  = complexity == "simple"
    max_rounds = {"simple": 0, "moderate": 1, "complex": 4}.get(complexity, 4)

    # Agent roster pruning: simple queries don't need all specialists.
    # Relaxed for follow-ups so that "its risks + governance + 5y price + news"
    # and other complex pronoun follow-ups still get the agents their keywords requested.
    if complexity == "simple":
        selected = [a for a in selected if a in ("financials", "news", "risk", "governance", "valuation", "accounting", "competitor", "technical")]
        if not selected:
            selected = ["financials"]
    elif complexity == "moderate":
        # Keep financials, news, risk — drop heavy specialist agents
        selected = [a for a in selected if a in ("financials", "risk", "news", "competitor", "governance", "valuation", "accounting")]
        if not selected:
            selected = ["financials", "news"]
    # complex: keep all selected agents

    return RoutingDecision(
        selected_agents=selected,
        selected_tools=["search", "enrichment", "verification"],
        retrieval_plan=[entity.country_code, entity.search_label],
        deep_research=deep,
        query_complexity=complexity,
        skip_reflection=skip_reflection,
        skip_blindspot=skip_blindspot,
        skip_deep_dive=skip_deep_dive,
        max_deep_dive_rounds=max_rounds,
        operational_intent=operational_intent,
        is_followup=is_followup,
    )


class ContextualizerError(Exception):
    """Raised when the LLM contextualizer (OpenAI + xAI fallback) completely fails."""
    pass


@dataclass
class ContextualizeResult:
    is_followup: bool
    contextualized_query: str
    target: str | None = None


class LLMQueryContextualizer:
    def __init__(self) -> None:
        pass

    async def contextualize(
        self,
        query: str,
        prior_target: str | None,
        chat_history: list[dict[str, Any]] | None = None,
    ) -> ContextualizeResult:
        """Pure-LLM follow-up detection and rewriting with full chat history.

        Returns a structured decision with:
        - is_followup: whether this query continues the prior conversation topic
        - contextualized_query: pronoun-free, self-contained version (useful for retrieval)
        - target: the resolved company name (prior_target if follow-up, or newly extracted target)

        Raises ContextualizerError if both OpenAI and xAI are unavailable.
        """
        if not prior_target:
            return ContextualizeResult(
                is_followup=False,
                contextualized_query=query,
                target=None,
            )

        # Build a concise chat-history block for the prompt (last 6 turns max)
        history_block = ""
        if chat_history:
            turns = chat_history[-6:]
            lines: list[str] = []
            for turn in turns:
                role = turn.get("role", "user")
                content = (turn.get("content") or turn.get("message") or "")[:300]
                lines.append(f"{role}: {content}")
            history_block = "\n".join(lines)

        system_prompt = (
            "You are a financial-query contextualizer. Your ONLY job is to decide whether the user's "
            "latest query is a follow-up to the prior conversation, and if so rewrite it to be "
            "self-contained (replace pronouns with the actual company name).\n\n"
            "--- PRIOR TARGET COMPANY ---\n"
            f"{prior_target}\n\n"
            "--- RECENT CHAT HISTORY (most recent first) ---\n"
            f"{history_block or '(no history)'}\n\n"
            "--- CURRENT QUERY ---\n"
            f"{query}\n\n"
            "Instructions:\n"
            "1. If the current query refers to the prior target company (using pronouns like 'it', 'its', "
            "'they', 'their', 'this company', 'that company', 'same company', or by continuing the same "
            "topic without naming a new entity), set 'is_followup' to true.\n"
            "   - Rewrite 'contextualized_query' by replacing all ambiguous references with the full "
            "     company name (use possessives like \"Reliance's\" when appropriate).\n"
            "   - 'target' should be the prior target company name.\n\n"
            "2. If the current query introduces a COMPLETELY DIFFERENT company/ticker, or is a brand-new "
            "topic unrelated to the prior target, set 'is_followup' to false.\n"
            "   - 'contextualized_query' should be the original query unchanged.\n"
            "   - 'target' should be the newly mentioned company name, or null if none is clear.\n\n"
            "3. If the query is a comparison (e.g., 'compare it with TCS'), set 'is_followup' to true "
            "and rewrite both entities explicitly into the contextualized_query.\n\n"
            "Respond ONLY with a JSON object in this exact format:\n"
            "{\n"
            '  "is_followup": boolean,\n'
            '  "contextualized_query": "string",\n'
            '  "target": "string or null"\n'
            "}"
        )

        async def _invoke_llm(client: Any, model: str, system_prompt: str, user_query: str) -> ContextualizeResult:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            content = resp.choices[0].message.content or ""
            data = json.loads(content.strip())
            return ContextualizeResult(
                is_followup=bool(data.get("is_followup", False)),
                contextualized_query=data.get("contextualized_query", user_query),
                target=data.get("target") or None,
            )

        # --- Primary attempt (OpenAI or xAI via resolve_openai_config) --------
        primary_cfg = resolve_openai_config()
        if primary_cfg:
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=primary_cfg.api_key, base_url=primary_cfg.base_url)
                logger.info(
                    "[ROUTER-LLM] primary_attempt | model=%s | prior_target=%s | query=%s",
                    primary_cfg.model, prior_target, query[:120],
                )
                result = await _invoke_llm(client, primary_cfg.model, system_prompt, query)
                logger.info(
                    "[ROUTER-LLM] primary_success | is_followup=%s target=%r query=%r -> %r",
                    result.is_followup, result.target, query, result.contextualized_query,
                )
                return result
            except Exception as primary_exc:
                logger.warning("[ROUTER-LLM] primary_failed | error=%s | will_try_grok_fallback", primary_exc)
        else:
            logger.info("[ROUTER-LLM] no_primary_config | will_try_grok_fallback")

        # --- Grok small-model fallback (explicit second chance) ---------------
        xai_key = os.getenv("XAI_API_KEY")
        if xai_key:
            try:
                from openai import AsyncOpenAI
                grok_client = AsyncOpenAI(api_key=xai_key, base_url="https://api.x.ai/v1")
                grok_model = os.getenv("FINAGENT_XAI_MODEL", "grok-3-mini")
                logger.info(
                    "[ROUTER-LLM] grok_small_fallback | model=%s | prior_target=%s | query=%s",
                    grok_model, prior_target, query[:120],
                )
                result = await _invoke_llm(grok_client, grok_model, system_prompt, query)
                logger.info(
                    "[ROUTER-LLM] grok_fallback_success | is_followup=%s target=%r query=%r -> %r",
                    result.is_followup, result.target, query, result.contextualized_query,
                )
                return result
            except Exception as grok_exc:
                logger.warning("[ROUTER-LLM] grok_small_fallback_failed | error=%s", grok_exc)
        else:
            logger.warning("[ROUTER-LLM] no_xai_key | cannot_attempt_grok_fallback")

        # --- Both providers exhausted → hard failure -------------------------
        raise ContextualizerError(
            "All LLM contextualizer providers failed (OpenAI and xAI both unavailable). "
            "Cannot determine whether this is a follow-up query."
        )

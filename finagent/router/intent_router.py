"""Intent router for India-focused FinAgent.

Classifies query complexity and selects which pipeline phases to execute.

IMPORTANT: The Verifier is NEVER skipped regardless of query complexity.
There is intentionally no `skip_verifier` field — financial accuracy
requires verification on every response.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from finagent.geo.entity_resolver import ResolvedEntity, resolve_entities
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

    # Agent roster pruning: simple queries don't need all specialists
    if complexity == "simple":
        selected = [a for a in selected if a in ("financials", "news")]
        if not selected:
            selected = ["financials"]
    elif complexity == "moderate":
        # Keep financials, news, risk — drop heavy specialist agents
        selected = [a for a in selected if a in ("financials", "risk", "news", "competitor")]
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


class LLMQueryContextualizer:
    def __init__(self) -> None:
        pass

    async def contextualize(self, query: str, prior_target: str | None) -> tuple[str, bool]:
        """Rewrite follow-up queries using OpenAI to be self-contained by replacing pronouns with the prior target."""
        if not prior_target:
            return query, False

        heuristic_query, heuristic_followup = self._heuristic_fallback(query, prior_target)
        if heuristic_followup:
            logger.info(
                "Heuristic Query Contextualizer: %r -> %r (is_followup=True)",
                query,
                heuristic_query,
            )
            return heuristic_query, True
        if self._mentions_different_entity(query, prior_target):
            return query, False

        cfg = resolve_openai_config()
        if not cfg:
            logger.info("No OpenAI config found. Falling back to heuristics for query: %r", query)
            return heuristic_query, heuristic_followup

        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)

            system_prompt = (
                "You are a financial query analyzer.\n"
                "Your job is to rewrite a follow-up query to be fully self-contained by replacing any ambiguous pronouns or references with the target company's name.\n\n"
                "Prior Target Company: {prior_target}\n"
                "Current Query: {query}\n\n"
                "If the current query is referring to the prior target company (using pronouns like 'it', 'its', 'they', 'their', 'them', 'this company', 'that company', 'same company', 'the company', or by being a direct short follow-up like 'latest news'), then:\n"
                "1. Set 'is_followup' to true.\n"
                "2. Rewrite 'contextualized_query' to be self-contained, replacing the pronouns or references with the actual company name (use possessives like target's if applicable).\n\n"
                "If the current query is NOT a follow-up, or refers to a completely different company/ticker, or is a brand new command:\n"
                "1. Set 'is_followup' to false.\n"
                "2. Set 'contextualized_query' to the original query.\n\n"
                "Respond ONLY with a JSON object in this format:\n"
                "{\n"
                "  \"contextualized_query\": \"string\",\n"
                "  \"is_followup\": boolean\n"
                "}"
            ).replace("{prior_target}", prior_target).replace("{query}", query)

            resp = await client.chat.completions.create(
                model=cfg.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Contextualize this query: {query}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
            )

            content = resp.choices[0].message.content or ""
            data = json.loads(content.strip())

            contextualized_query = data.get("contextualized_query", query)
            is_followup = bool(data.get("is_followup", False))
            logger.info("LLM Query Contextualizer: %r -> %r (is_followup=%s)", query, contextualized_query, is_followup)
            return contextualized_query, is_followup

        except Exception as exc:
            logger.warning("LLM Query Contextualizer failed: %s. Falling back to heuristics.", exc)
            return self._heuristic_fallback(query, prior_target)

    def _heuristic_fallback(self, query: str, prior_target: str) -> tuple[str, bool]:
        text = (query or "").strip().lower()
        if not text:
            return query, False

        # Guard checks matching _is_ambiguous_followup
        if re.search(r"\b(analyze|analyse|research|review)\b", text):
            return query, False
        if re.search(r"\bcompare\b.*\band\b", text):
            return query, False
        if re.search(r"\w+\s+(vs\.?|versus)\s+\w+", text):
            return query, False
        if self._mentions_different_entity(query, prior_target):
            return query, False

        pronoun_ref = re.search(r"\b(it|its|they|their|them|that company|this company|same company|the company)\b", text)
        focus, _ = detect_operational_intent(query, has_prior_entity=False)
        short_focus = focus != "snapshot" and len(text.split()) <= 10
        is_followup = bool(pronoun_ref) or short_focus

        if is_followup:
            rewritten = query
            rewritten = re.sub(r"\b(its|their)\b", f"{prior_target}'s", rewritten, flags=re.IGNORECASE)
            rewritten = re.sub(r"\b(this company|that company|same company|the company)\b", prior_target, rewritten, flags=re.IGNORECASE)
            rewritten = re.sub(r"\b(it|they|them)\b", prior_target, rewritten, flags=re.IGNORECASE)
            rewritten = re.sub(r"\s+", " ", rewritten).strip()
            return rewritten, True
        return query, False

    def _mentions_different_entity(self, query: str, prior_target: str) -> bool:
        """Prevent short focused queries like 'Tata Motors latest news' from being
        incorrectly attached to the previous company.
        """

        try:
            entities = resolve_entities(query, limit=3)
        except Exception:
            return False
        if not entities:
            return False
        prior = (prior_target or "").lower()
        for entity in entities:
            labels = {
                (entity.canonical_name or "").lower(),
                (entity.normalized_name or "").lower(),
                (entity.ticker_label or "").lower(),
                (getattr(entity, "ticker", "") or "").lower(),
            }
            if any(label and label in prior for label in labels):
                continue
            return True
        return False

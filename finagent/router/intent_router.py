"""Intent router for India-focused FinAgent.

Classifies query complexity and selects which pipeline phases to execute.

IMPORTANT: The Verifier is NEVER skipped regardless of query complexity.
There is intentionally no `skip_verifier` field — financial accuracy
requires verification on every response.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from finagent.geo.entity_resolver import ResolvedEntity
from finagent.router.domain_taxonomy import AGENT_KEYWORDS
from finagent.router.policies import should_enable_deep_research

# ── Simple query patterns — skip heavy phases ─────────────────────────────────
_SIMPLE_PATTERNS = (
    "pe ratio", "p/e", "pb ratio", "p/b", "current price", "share price",
    "stock price", "live price", "market cap", "eps", "dividend yield",
    "book value", "52 week", "52-week", "nse price", "bse price",
    "what is the price", "face value", "circuit limit",
)

# Moderate — run 1 deep-dive round, skip blindspot
_MODERATE_PATTERNS = (
    "quarterly results", "earnings", "revenue growth", "profit",
    "net income", "ebitda", "margin", "balance sheet", "cash flow",
    "latest news", "recent news", "sector outlook", "analyst target",
    "shareholding", "fii holding", "dii holding",
)

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
    # NOTE: There is intentionally NO skip_verifier field.
    # The verifier ALWAYS runs to protect financial data integrity.


def route_objective(
    objective: str,
    entity: ResolvedEntity,
    *,
    playbook_agents: list[str] | None = None,
) -> RoutingDecision:
    lower = (objective or "").lower()

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

    complexity = _classify_complexity(objective)
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
    )

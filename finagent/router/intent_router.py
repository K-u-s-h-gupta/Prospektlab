from __future__ import annotations

from dataclasses import dataclass, field

from finagent.geo.entity_resolver import ResolvedEntity
from finagent.router.domain_taxonomy import AGENT_KEYWORDS
from finagent.router.policies import should_enable_deep_research


@dataclass
class RoutingDecision:
    selected_agents: list[str] = field(default_factory=list)
    confidence: str = "medium"
    selected_tools: list[str] = field(default_factory=list)
    retrieval_plan: list[str] = field(default_factory=list)
    fallback_policy: str = "continue-with-available-evidence"
    deep_research: bool = False


def route_objective(objective: str, entity: ResolvedEntity, *, playbook_agents: list[str] | None = None) -> RoutingDecision:
    lower = (objective or "").lower()
    selected: list[str] = []
    for agent, keywords in AGENT_KEYWORDS.items():
        if any(term in lower for term in keywords):
            selected.append(agent)

    if not selected:
        selected = ["financials", "risk", "news", "competitor"]

    if entity.country_code != "US" and "financials" not in selected:
        selected.append("financials")
    if playbook_agents:
        for agent in playbook_agents:
            if agent not in selected:
                selected.append(agent)

    return RoutingDecision(
        selected_agents=selected,
        selected_tools=["search", "enrichment", "verification"],
        retrieval_plan=[entity.country_code, entity.search_label],
        deep_research=should_enable_deep_research(objective),
    )

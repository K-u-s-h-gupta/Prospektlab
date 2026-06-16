"""Blueprint Specification Architecture.

Generates a structured research plan (BlueprintSpec) BEFORE agents launch.
The spec is presented to the user via SSE interrupt, and is injected into
every agent's context so all agents share the same goal framing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("finagent.agents.blueprint")


@dataclass
class BlueprintSpec:
    """Structured research plan generated before agents launch."""

    # Core plan
    goals: list[str] = field(default_factory=list)
    boundaries: list[str] = field(default_factory=list)
    non_goals: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)

    # Data sources to be used
    data_sources: list[str] = field(default_factory=list)

    # Agent assignment
    assigned_agents: list[str] = field(default_factory=list)

    # Metadata
    query: str = ""
    entity_name: str = ""
    entity_cin: str | None = None
    entity_isin: str | None = None
    complexity: str = "moderate"

    def to_context_block(self) -> str:
        """Format spec as a structured context block for agent injection."""
        lines = [
            "## Research Blueprint",
            f"**Entity**: {self.entity_name}",
            f"**Query**: {self.query}",
            "",
            "### Goals",
            *[f"- {g}" for g in self.goals],
            "",
            "### Scope Boundaries",
            *[f"- {b}" for b in self.boundaries],
            "",
            "### Non-Goals",
            *[f"- {ng}" for ng in self.non_goals],
            "",
            "### Success Criteria",
            *[f"- {sc}" for sc in self.success_criteria],
            "",
            "### Data Sources",
            *[f"- {ds}" for ds in self.data_sources],
            "",
            "> **Important**: All outputs must follow SEBI-safe research language.",
            "> Use scenario-conditional framing. Do NOT use buy/sell/hold language.",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goals": self.goals,
            "boundaries": self.boundaries,
            "non_goals": self.non_goals,
            "success_criteria": self.success_criteria,
            "data_sources": self.data_sources,
            "assigned_agents": self.assigned_agents,
            "query": self.query,
            "entity_name": self.entity_name,
            "entity_cin": self.entity_cin,
            "entity_isin": self.entity_isin,
            "complexity": self.complexity,
        }


def generate_blueprint(
    query: str,
    entity_name: str,
    routing_decision: Any | None = None,
    *,
    entity_cin: str | None = None,
    entity_isin: str | None = None,
) -> BlueprintSpec:
    """Generate a BlueprintSpec from query, entity, and routing context.

    This is synchronous and fast — no LLM calls needed for baseline spec.
    The routing_decision provides complexity and assigned_agents.

    Args:
        query: The user's research query.
        entity_name: Resolved company name.
        routing_decision: RoutingDecision from intent_router.
        entity_cin: Optional MCA CIN.
        entity_isin: Optional ISIN.

    Returns:
        BlueprintSpec with structured research plan.
    """
    complexity = "moderate"
    assigned_agents: list[str] = ["financials", "risk", "news"]

    if routing_decision:
        complexity = getattr(routing_decision, "query_complexity", "moderate")
        assigned_agents = getattr(routing_decision, "selected_agents", assigned_agents)

    query_lower = query.lower()

    # Derive goals from query intent
    goals: list[str] = []
    non_goals: list[str] = []
    data_sources: list[str] = []

    # Universal SEBI compliance goal
    goals.append(f"Produce evidence-based research summary on {entity_name}")
    goals.append("Present scenario-conditional analysis with explicit stated assumptions")
    goals.append("Source all financial claims from Tier 1-2 data sources with citations")
    non_goals.append("Issue investment recommendations, buy/sell/hold signals")
    non_goals.append("Provide price targets as definitive forecasts")

    # Agent-specific goals
    if "governance" in assigned_agents or "governance" in query_lower:
        goals.append("Map promoter ownership structure and pledge levels from IKG data")
        data_sources.extend(["BSE_SHP", "MCA_director_network", "IKG_graph"])

    if "valuation" in assigned_agents or any(kw in query_lower for kw in ("dcf", "valuation", "intrinsic")):
        goals.append("Run multi-model valuation (DCF, Graham, PE-relative, EV/EBITDA)")
        goals.append("State explicit WACC and growth rate assumptions for each model")
        data_sources.extend(["yfinance", "BSE_EOD_prices", "Screener.in"])

    if "risk" in assigned_agents:
        goals.append("Identify key risk factors with quantifiable exposure where available")
        data_sources.append("SEBI_enforcement_orders")

    if "financials" in assigned_agents:
        goals.append("Extract 5-year financial trend analysis from audited statements")
        data_sources.extend(["annual_reports", "BSE_corporate_filings"])

    if "news" in assigned_agents:
        goals.append("Verify recent material events from last 90 days")
        data_sources.append("news_search")

    if "accounting" in assigned_agents or "fraud" in query_lower:
        goals.append("Check for accounting quality signals: RPTs, auditor changes, qualified opinions")
        data_sources.append("IKG_graph")

    # Boundaries
    boundaries = [
        f"Research scope limited to {entity_name} and its disclosed subsidiaries",
        "Financial data sources: BSE/NSE filings, annual reports, MCA disclosures",
        "News coverage window: last 90 days for material events",
        "Historical financials: up to 5 years for trend analysis",
    ]

    if complexity == "simple":
        boundaries.append("Simple query mode: focus on key metrics only, skip deep-dive rounds")
    elif complexity == "complex":
        boundaries.append("Complex query mode: full multi-agent deep-dive with reflexion loop")

    # Success criteria
    success_criteria = [
        "All material claims sourced with URL or document citation",
        "Valuation outputs include explicit assumption list",
        "Governance section addresses promoter pledge if >15% (flag or note absence)",
        "Output passes SEBI-safe compliance check (no advisory language)",
        "Research Quality Score ≥ 65/100 from post-synthesis grader",
    ]

    # Deduplicate data sources
    data_sources = list(dict.fromkeys(data_sources))

    return BlueprintSpec(
        goals=goals,
        boundaries=boundaries,
        non_goals=non_goals,
        success_criteria=success_criteria,
        data_sources=data_sources,
        assigned_agents=assigned_agents,
        query=query,
        entity_name=entity_name,
        entity_cin=entity_cin,
        entity_isin=entity_isin,
        complexity=complexity,
    )


def blueprint_to_sse_event(spec: BlueprintSpec) -> dict[str, Any]:
    """Format a BlueprintSpec as an SSE event payload for the frontend."""
    return {
        "event": "blueprint",
        "data": {
            "type": "blueprint_ready",
            "entity": spec.entity_name,
            "query": spec.query,
            "complexity": spec.complexity,
            "agents": spec.assigned_agents,
            "goals": spec.goals,
            "data_sources": spec.data_sources,
            "success_criteria": spec.success_criteria,
        },
    }

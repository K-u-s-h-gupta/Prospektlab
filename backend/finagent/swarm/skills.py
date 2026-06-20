"""Skill registry for swarm agents.

A skill maps a reusable agent role to a system prompt, a set of allowed tools,
and an output schema. The SwarmCoordinator matches SubTasks to skills by
agent_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentSkill:
    """Definition of a reusable swarm agent skill."""

    skill_id: str
    display: str
    description: str
    system_prompt: str
    allowed_tools: list[str] = field(default_factory=list)
    output_schema: dict[str, Any] = field(default_factory=dict)
    priority: int = 50
    default_max_steps: int = 8
    default_budget_ms: int = 30_000

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "display": self.display,
            "description": self.description,
            "allowed_tools": self.allowed_tools,
            "priority": self.priority,
            "default_max_steps": self.default_max_steps,
            "default_budget_ms": self.default_budget_ms,
        }


class SkillRegistry:
    """Registry of available swarm skills."""

    def __init__(self) -> None:
        self._skills: dict[str, AgentSkill] = {}
        self._register_defaults()

    def register(self, skill: AgentSkill) -> None:
        self._skills[skill.skill_id] = skill

    def get(self, skill_id: str) -> AgentSkill | None:
        return self._skills.get(skill_id)

    def list_skills(self) -> list[str]:
        return list(self._skills.keys())

    def match(self, objective: str, available_tools: list[str] | None = None) -> list[AgentSkill]:
        """Return skills whose allowed_tools overlap with available_tools."""
        if available_tools is None:
            return list(self._skills.values())
        available = set(available_tools)
        return [s for s in self._skills.values() if available.intersection(set(s.allowed_tools))]

    def _register_defaults(self) -> None:
        # Financials
        self.register(AgentSkill(
            skill_id="financials_analyst",
            display="Financials Analyst",
            description="Analyses P&L, balance sheet, cash flow, margins, and growth trends.",
            system_prompt=(
                "You are a financial analyst. Use the provided enrichment bundle and IKG financials "
                "to extract 5-10 high-confidence claims about revenue, margins, ROCE, debt, cash flow, "
                "and working capital. Every claim must cite a source. Return structured JSON."
            ),
            allowed_tools=["ikg_get_financials", "ikg_get_xbrl_facts", "quant_full_valuation", "discovery_search"],
            default_max_steps=10,
            default_budget_ms=30_000,
            priority=10,
        ))

        # Valuation
        self.register(AgentSkill(
            skill_id="valuation_modeler",
            display="Valuation Modeler",
            description="Builds DCF, multiples, and scenario valuation ranges using real computation.",
            system_prompt=(
                "You are a valuation analyst. Use the sandbox Python tool to compute DCF and multiples. "
                "Do not hallucinate numbers. Return the model assumptions, intermediate steps, and a fair-value "
                "range. No buy/sell/hold labels."
            ),
            allowed_tools=["sandbox_python", "quant_full_valuation", "ikg_get_financials", "ikg_get_xbrl_facts"],
            default_max_steps=12,
            default_budget_ms=45_000,
            priority=20,
        ))

        # Governance
        self.register(AgentSkill(
            skill_id="governance_forensics",
            display="Governance Forensics",
            description="Forensic governance analysis using IKG director network, pledge, and enforcement data.",
            system_prompt=(
                "You are a forensic governance analyst. Use IKG tools to analyse director networks, "
                "promoter pledge, related-party transactions, auditor history, and SEBI enforcement. "
                "Flag red flags with source URLs. Score governance 0-100 with component breakdown."
            ),
            allowed_tools=[
                "ikg_company_bundle", "ikg_get_directors", "ikg_get_promoter_chain",
                "ikg_get_pledge_risk", "ikg_get_enforcement_history", "ikg_get_rpt_analysis",
                "ikg_get_auditor_history",
            ],
            default_max_steps=10,
            default_budget_ms=30_000,
            priority=15,
        ))

        # Risk
        self.register(AgentSkill(
            skill_id="risk_redflags",
            display="Risk Red-Flag Scanner",
            description="Scans for regulatory, operational, and market risks.",
            system_prompt=(
                "You are a risk analyst. Use IKG enforcement, news search, and web search to identify "
                "the top 5-7 risks. Rate each HIGH/MEDIUM/LOW for probability and impact. Cite sources."
            ),
            allowed_tools=["ikg_get_enforcement_history", "discovery_search_news", "discovery_search_web", "ikg_get_rpt_analysis"],
            default_max_steps=10,
            default_budget_ms=30_000,
            priority=25,
        ))

        # Competitor
        self.register(AgentSkill(
            skill_id="competitor_moat",
            display="Competitor & Moat Analyst",
            description="Peer comparison and competitive moat analysis.",
            system_prompt=(
                "You are a strategy analyst. Compare the target company with 4-6 named peers on "
                "revenue growth, margins, return ratios, valuation multiples, and market share. "
                "Identify the moat and threats."
            ),
            allowed_tools=["discovery_search", "quant_full_valuation", "ikg_search_entities", "ikg_company_bundle"],
            default_max_steps=10,
            default_budget_ms=30_000,
            priority=30,
        ))

        # News / Sentiment
        self.register(AgentSkill(
            skill_id="news_sentiment",
            display="News & Sentiment Analyst",
            description="Latest news, concall transcripts, and social sentiment.",
            system_prompt=(
                "You are a news and sentiment analyst. Focus on the last 90 days. Extract management "
                "guidance from concalls, analyst upgrades/downgrades, and retail sentiment. Cite exact "
                "sources and dates."
            ),
            allowed_tools=["discovery_search_news", "ikg_get_concall_transcripts", "ikg_search_document_sections", "discovery_search_reddit"],
            default_max_steps=10,
            default_budget_ms=25_000,
            priority=20,
        ))

        # Macro
        self.register(AgentSkill(
            skill_id="macro_sector",
            display="Macro & Sector Analyst",
            description="Macroeconomic and sector overlay for India and global drivers.",
            system_prompt=(
                "You are a macro analyst. Analyse RBI policy, USD-INR, crude, government schemes, "
                "and sector capex. Link to company margins and revenue exposure."
            ),
            allowed_tools=["discovery_search_news", "quant_forex", "ikg_search_document_sections"],
            default_max_steps=8,
            default_budget_ms=25_000,
            priority=35,
        ))

        # Causal / War-game
        self.register(AgentSkill(
            skill_id="causal_war_gamer",
            display="Causal War-Gamer",
            description="Runs counterfactual scenarios and adversary simulations.",
            system_prompt=(
                "You are a causal analyst. Given a scenario (e.g. crude +20%, INR -5%), estimate the "
                "impact on revenue, margins, and fair value. Use the sandbox tool for calculations. "
                "Consider adversary reactions: promoter, FII, short-seller, regulator."
            ),
            allowed_tools=["sandbox_python", "quant_full_valuation", "ikg_get_financials"],
            default_max_steps=12,
            default_budget_ms=45_000,
            priority=40,
        ))

        # Document producer
        self.register(AgentSkill(
            skill_id="document_producer",
            display="Document Producer",
            description="Generates PDF, DOCX, XLSX, and PPTX deliverables from the canvas.",
            system_prompt=(
                "You are a document production specialist. Take the final canvas and produce professional "
                "reports, decks, and models. No new research; only formatting and chart generation."
            ),
            allowed_tools=["export_pdf", "export_docx", "export_xlsx", "export_pptx"],
            default_max_steps=6,
            default_budget_ms=60_000,
            priority=90,
        ))


# Global singleton
_REGISTRY: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = SkillRegistry()
    return _REGISTRY


__all__ = ["AgentSkill", "SkillRegistry", "get_skill_registry"]

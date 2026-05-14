"""Bundled specialist subagents.

Importable as:
    from finagent.agents.specialists import default_roster
"""

from finagent.agents.specialists.community import CommunityAgent
from finagent.agents.specialists.competitor import CompetitorAgent
from finagent.agents.specialists.financials import FinancialsAgent
from finagent.agents.specialists.governance import GovernanceAgent
from finagent.agents.specialists.macro import MacroAgent
from finagent.agents.specialists.news import NewsAgent
from finagent.agents.specialists.risk import RiskAgent
from finagent.agents.specialists.technical import TechnicalAgent


def default_roster():
    """The standard 8-agent roster used by run_research_session."""
    return [
        FinancialsAgent(),
        RiskAgent(),
        TechnicalAgent(),
        NewsAgent(),
        CommunityAgent(),
        CompetitorAgent(),
        MacroAgent(),
        GovernanceAgent(),
    ]


__all__ = [
    "CommunityAgent",
    "CompetitorAgent",
    "FinancialsAgent",
    "GovernanceAgent",
    "MacroAgent",
    "NewsAgent",
    "RiskAgent",
    "TechnicalAgent",
    "default_roster",
]

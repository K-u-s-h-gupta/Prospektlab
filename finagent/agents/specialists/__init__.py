"""Specialist sub-agents (Hermes multi-agent system).

Each specialist answers one narrow question (financials, risk, news, etc.)
and returns structured AgentTaskResult + Findings.

Public API:
    default_roster() -> list[BaseSubAgent]
    Individual agent classes (for advanced use / testing)
"""

from .community import CommunityAgent
from .competitor import CompetitorAgent
from .financials import FinancialsAgent
from .governance import GovernanceAgent
from .macro import MacroAgent
from .news import NewsAgent
from .risk import RiskAgent
from .technical import TechnicalAgent
from .valuation import ValuationAgent
from .accounting import AccountingAgent

__all__ = [
    "AccountingAgent",
    "CommunityAgent",
    "CompetitorAgent",
    "FinancialsAgent",
    "GovernanceAgent",
    "MacroAgent",
    "NewsAgent",
    "RiskAgent",
    "TechnicalAgent",
    "ValuationAgent",
    "default_roster",
]


def default_roster():
    """Return the default roster of specialist agents (sorted by priority)."""
    agents = [
        FinancialsAgent(),   # priority 10
        RiskAgent(),         # 20
        NewsAgent(),         # 20
        TechnicalAgent(),    # 30
        CommunityAgent(),    # 30
        CompetitorAgent(),   # 40
        ValuationAgent(),    # 40  statistical revenue projection
        AccountingAgent(),   # 45  statistical anomaly / forensic
        MacroAgent(),        # 50
        GovernanceAgent(),   # 60
    ]
    # Stable sort by declared priority (lower = earlier in waves)
    agents.sort(key=lambda a: getattr(a, "priority", 50))
    return agents

"""Bundled specialist subagents.

Importable as:
    from finagent.agents.specialists import default_roster
"""

from finagent.agents.specialists.accounting import AccountingAgent
from finagent.agents.specialists.competitor import CompetitorAgent
from finagent.agents.specialists.financials import FinancialsAgent
from finagent.agents.specialists.governance import GovernanceAgent
from finagent.agents.specialists.macro import MacroAgent
from finagent.agents.specialists.news import NewsAgent
from finagent.agents.specialists.risk import RiskAgent
from finagent.agents.specialists.technical import TechnicalAgent
from finagent.agents.specialists.valuation import ValuationAgent


def default_roster():
    """The standard India-market specialist roster used by run_research_session."""
    return [
        FinancialsAgent(),
        RiskAgent(),
        TechnicalAgent(),
        NewsAgent(),
        CompetitorAgent(),
        MacroAgent(),
        GovernanceAgent(),
        ValuationAgent(),
        AccountingAgent(),
    ]


__all__ = [
    "AccountingAgent",
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

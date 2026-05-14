"""Multi-agent orchestration.

Hermes-style: an orchestrator runs many specialist subagents in parallel,
a verifier cross-checks their claims, and a blind-spot generator asks
"what haven't we covered?" to trigger a second dispatch round.

Public API:
    Orchestrator(...).run(context) -> OrchestrationResult
    BaseSubAgent — extend to add new specialists
    SubAgentContext — shared read-only inputs
    AgentTaskResult — what each subagent returns
"""

from finagent.agents.base import (
    AgentTaskResult,
    BaseSubAgent,
    Finding,
    SubAgentContext,
)
from finagent.agents.blindspot import BlindSpot, detect_blind_spots
from finagent.agents.orchestrator import Orchestrator, OrchestrationResult
from finagent.agents.verifier import Verifier, VerifierReport

__all__ = [
    "AgentTaskResult",
    "BaseSubAgent",
    "BlindSpot",
    "Finding",
    "Orchestrator",
    "OrchestrationResult",
    "SubAgentContext",
    "Verifier",
    "VerifierReport",
    "detect_blind_spots",
]

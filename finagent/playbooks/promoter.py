from __future__ import annotations

from finagent.playbooks.schema import FinancialPlaybook
from finagent.playbooks.store import PlaybookStore


def maybe_promote_playbook(
    *,
    quality_score: float,
    geography: str,
    objective: str,
    target: str,
    selected_agents: list[str],
    preferred_domains: list[str],
    query_templates: list[str],
) -> FinancialPlaybook | None:
    if quality_score < 78.0 or not selected_agents:
        return None
    lower = (objective or "").lower()
    if "compare" in lower:
        intent_key = "compare"
    elif "risk" in lower:
        intent_key = "risk"
    elif "valuation" in lower:
        intent_key = "valuation"
    else:
        intent_key = "analysis"

    playbook = FinancialPlaybook(
        name=f"{geography.lower()}_{intent_key}_playbook",
        geography=geography,
        intent_key=intent_key,
        selected_agents=selected_agents,
        preferred_domains=preferred_domains[:8],
        query_templates=query_templates[:8],
        example_target=target,
        example_objective=objective,
    )
    PlaybookStore().upsert(playbook)
    return playbook

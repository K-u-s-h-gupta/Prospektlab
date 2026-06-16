from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FinancialPlaybook:
    name: str
    geography: str
    intent_key: str
    selected_agents: list[str] = field(default_factory=list)
    preferred_domains: list[str] = field(default_factory=list)
    query_templates: list[str] = field(default_factory=list)
    success_count: int = 1
    example_target: str = ""
    example_objective: str = ""

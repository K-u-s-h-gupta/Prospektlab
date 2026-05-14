"""Decompose research into a dependency-aware plan."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Depth(str, Enum):
    SURFACE = "surface"
    STANDARD = "standard"
    DEEP = "deep"
    EXHAUSTIVE = "exhaustive"


@dataclass
class PlanStep:
    order: int
    action: str
    tool: str
    expected_output: str
    depends_on: tuple[int, ...] = ()


@dataclass
class ResearchPlan:
    target: str
    objective: str
    steps: list[PlanStep] = field(default_factory=list)
    depth: Depth = Depth.STANDARD
    estimated_duration: str = "60 minutes"
    human_gates: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        lines = [
            "RESEARCH PLAN",
            f"Target: {self.target}",
            f"Objective: {self.objective}",
            "Steps:",
        ]
        for s in sorted(self.steps, key=lambda x: x.order):
            deps = f" (after {s.depends_on})" if s.depends_on else ""
            lines.append(
                f"  Step {s.order} -- {s.action} -> {s.tool} -> {s.expected_output}{deps}"
            )
        lines.extend(
            [
                f"Estimated depth: {self.depth.value}",
                f"Estimated duration: {self.estimated_duration}",
                f"Human gates: {', '.join(self.human_gates) or 'none'}",
            ]
        )
        return "\n".join(lines)


def build_default_plan(target: str, objective: str) -> ResearchPlan:
    return ResearchPlan(
        target=target,
        objective=objective,
        steps=[
            PlanStep(1, "Breadth survey", "web_search", "Surface map of sources"),
            PlanStep(2, "Primary filings", "edgar", "10-K / 10-Q index", depends_on=(1,)),
            PlanStep(3, "Triangulate key metrics", "accuracy_validator", "Confidence tags", depends_on=(2,)),
            PlanStep(4, "Synthesis", "memo_formatter", "Research memo", depends_on=(3,)),
        ],
        human_gates=["export_data", "credit_spend_confirm"],
    )

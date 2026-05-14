"""Mandatory pre-flight clarification (Section 2.1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreflightAnswers:
    target_entity: str
    research_scope: str
    time_horizon: str
    output_format: str
    accuracy_bar: str  # exploratory | institutional


PREFLIGHT_QUESTIONS = [
    "(a) Target entity: exact company name, ticker, or fund? Public or private?",
    "(b) Research scope: what decisions will this research inform?",
    "(c) Time horizon: historical depth required? (1Y, 3Y, 5Y, 10Y?)",
    "(d) Output format: memo, model input, ProspektLab export, CRM record?",
    "(e) Accuracy bar: exploratory (80%) or institutional (>=95%)?",
]


def preflight_prompt_block() -> str:
    lines = ["Pre-flight - answer all five before research begins:", *PREFLIGHT_QUESTIONS]
    return "\n".join(lines)


def validate_preflight(p: PreflightAnswers | None) -> tuple[bool, list[str]]:
    missing: list[str] = []
    if p is None:
        return False, ["No preflight answers provided."]
    for field_name, val in p.__dict__.items():
        if not (val or "").strip():
            missing.append(field_name)
    return len(missing) == 0, missing

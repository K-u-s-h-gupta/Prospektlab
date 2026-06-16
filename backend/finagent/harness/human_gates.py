"""Declarative human gates before consequential actions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Gate:
    id: str
    template: str


GATES: list[Gate] = [
    Gate("export_data", "You are about to export {n} records to {destination}. Confirm?"),
    Gate("private_valuation", "About to report a private company valuation. Confirm sources?"),
    Gate("single_source_claim", "Material claim has only 1 source. Proceed or find more?"),
    Gate("conflict_detected", "Conflict detected between sources. How should I resolve this?"),
    Gate("pre_export_review", "Review ProspektLab dataset quality before export. Proceed?"),
    Gate("contact_export_confirm", "Export prospect contact data. Explicit confirmation required."),
    Gate("credit_spend_confirm", "Enrichment will consume credits. Show estimate and confirm?"),
    Gate("enrichment_quality_review", "Review enrichment sample before full run. Proceed?"),
]


def evaluate_gate(gate_id: str, **kwargs: str | int) -> str:
    for g in GATES:
        if g.id == gate_id:
            return g.template.format(**kwargs)
    raise KeyError(f"Unknown gate: {gate_id}")

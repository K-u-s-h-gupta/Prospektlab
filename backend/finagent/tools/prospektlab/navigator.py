"""ProspektLab workflow steps → tool sequence + gates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    name: str
    gated: bool
    gate: str | None = None


WORKFLOWS: dict[str, list[Step]] = {
    "company_search": [
        Step("fetch_entities", gated=False),
        Step("cross_reference", gated=False),
        Step("annotate_records", gated=False),
        Step("review_quality", gated=True, gate="pre_export_review"),
        Step("export", gated=True, gate="export_data"),
    ],
    "prospect_profiling": [
        Step("fetch_prospects", gated=False),
        Step("linkedin_verify", gated=False),
        Step("score_relevance", gated=False),
        Step("export_contacts", gated=True, gate="contact_export_confirm"),
    ],
    "deep_enrichment": [
        Step("cost_estimate", gated=True, gate="credit_spend_confirm"),
        Step("firmographics", gated=False),
        Step("technographics", gated=False),
        Step("funding_history", gated=False),
        Step("validate_sample", gated=True, gate="enrichment_quality_review"),
        Step("full_export", gated=True, gate="export_data"),
    ],
}

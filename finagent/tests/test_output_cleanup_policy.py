from __future__ import annotations

from finagent.output.contracts import (
    AnswerArtifact,
    AnswerCitation,
    OutputMode,
    ResponseDepth,
    ResponseSection,
)
from finagent.output.memo_formatter import MemoSection, format_memo
from finagent.output.output_scrubber import scrub_and_comply
from finagent.output.renderer import render_markdown, render_rich_json


def test_scrub_and_comply_removes_marker_noise_and_regulatory_tail():
    raw = (
        "Revenue grew 12% [SOURCE: Example Research] [AS-OF: FY25].\n"
        "Section confidence [CONFIDENCE: HIGH].\n"
        "Regulatory note: This is an educational, evidence-based research summary for Indian securities."
    )
    cleaned = scrub_and_comply(raw, session_id="test-cleanup")

    assert "[SOURCE:" not in cleaned
    assert "[AS-OF:" not in cleaned
    assert "[CONFIDENCE:" not in cleaned
    assert "Regulatory note:" not in cleaned


def test_render_markdown_omits_source_names_and_regulatory_note():
    artifact = AnswerArtifact(
        mode=OutputMode.DIRECT_ANSWER,
        depth=ResponseDepth.STANDARD,
        title="TCS snapshot",
        summary="Revenue and margin trends remain stable over recent quarters.",
        sections=[ResponseSection(title="Key Evidence", body="Margins held near prior-year range.")],
        citations=[AnswerCitation(title="Reuters", url="https://example.com/reuters-note", domain="reuters.com")],
    )

    memo = render_markdown(artifact)

    assert "#### Sources" not in memo
    assert "Reuters" not in memo
    assert "Regulatory note:" not in memo


def test_render_rich_json_uses_generic_reference_labels():
    artifact = AnswerArtifact(
        mode=OutputMode.DIRECT_ANSWER,
        depth=ResponseDepth.STANDARD,
        title="TCS snapshot",
        summary="Operational execution remains stable.",
        citations=[AnswerCitation(title="Moneycontrol", url="https://example.com/source-1")],
    )

    rich = render_rich_json(artifact)

    assert rich["data_sources"] == [{"label": "Reference 1", "url": "https://example.com/source-1"}]
    assert rich["disclaimer"] == ""


def test_format_memo_omits_source_inventory_sections():
    memo = format_memo(
        "TCS",
        date="2026-06-09",
        depth="standard",
        overall_confidence="HIGH",
        duration="30s",
        source_count=12,
        sections=[MemoSection(title="Executive summary", body="Detailed objective-focused summary.", confidence="HIGH")],
        data_quality_rows=["| Claim | Source | HIGH | 2026-06-09 | No |"],
        citation_rows=["| Title | https://example.com | 2026-06-09 | web |"],
    )

    assert "Sources consulted:" not in memo
    assert "Data quality log" not in memo
    assert "Citation log" not in memo

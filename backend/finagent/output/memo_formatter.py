"""Research memo template + inline markers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MemoSection:
    title: str
    body: str
    confidence: str


def format_memo(
    entity: str,
    *,
    date: str,
    depth: str,
    overall_confidence: str,
    duration: str,
    source_count: int,
    sections: list[MemoSection],
    data_quality_rows: list[str],
    citation_rows: list[str],
) -> str:
    _ = source_count, data_quality_rows, citation_rows
    lines = [
        f"# Research memo: {entity}",
        f"Date: {date}",
        "Prepared by: FinAgent",
        f"Research depth: {depth}",
        f"Overall confidence: {overall_confidence}",
        f"Research duration: {duration}",
        "",
    ]
    # Suppress the legacy placeholder when callers already supply an Executive summary section.
    has_exec = any((sec.title or "").strip().lower() == "executive summary" for sec in sections)
    if not has_exec:
        lines.extend(
            [
                "## Executive summary",
                "[CONFIDENCE: MEDIUM] Stub summary — replace after synthesis.",
                "",
            ]
        )
    for sec in sections:
        lines.extend([f"## {sec.title} [CONFIDENCE: {sec.confidence}]", sec.body, ""])
    return "\n".join(lines)

from __future__ import annotations

from finagent.output.contracts import AnswerArtifact, ResponseDepth
from finagent.output.compliance import enforce_sebi_compliance

_MISSING_VALUES = {"", "n/a", "na", "none", "null", "-", "\u2014"}


def _has_display_value(value) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() not in _MISSING_VALUES


def _table_rows_with_values(table) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows or []:
        if isinstance(row, dict):
            cells = [row.get(col, "") for col in table.columns]
        elif isinstance(row, (list, tuple)):
            cells = list(row)
        else:
            cells = [row]
        padded = cells[: len(table.columns)] + [""] * max(0, len(table.columns) - len(cells))
        if any(_has_display_value(cell) for cell in padded[1:]):
            rows.append([str(cell) for cell in padded])
    return rows


def render_markdown(artifact: AnswerArtifact) -> str:
    """Render a prose-first markdown answer.

    Visual widgets are delivered through `render_rich_json`; this markdown path
    intentionally omits visual placeholders so fallback answers do not end with
    duplicate or empty chart sections.
    """
    lines: list[str] = []

    safe_title = enforce_sebi_compliance(artifact.title, include_regulatory_note=False).splitlines()[0]
    safe_summary = enforce_sebi_compliance(artifact.summary, include_regulatory_note=False).strip()

    if artifact.depth == ResponseDepth.DEEP:
        lines.extend([f"# {safe_title}", "", safe_summary, ""])
    else:
        lines.extend([f"### {safe_title}", "", safe_summary, ""])

    for table in artifact.tables:
        if not table.columns:
            continue
        rows = _table_rows_with_values(table)
        if not rows:
            continue
        lines.append(f"#### {enforce_sebi_compliance(table.title, include_regulatory_note=False).splitlines()[0]}")
        lines.append("| " + " | ".join(table.columns) + " |")
        lines.append("|" + "|".join("---" for _ in table.columns) + "|")
        for row in rows:
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    for section in artifact.sections:
        if not section.body:
            continue
        lines.append(f"#### {enforce_sebi_compliance(section.title, include_regulatory_note=False).splitlines()[0]}")
        lines.append(enforce_sebi_compliance(section.body.strip(), include_regulatory_note=False))
        if section.confidence:
            lines.append(f"\nConfidence: {section.confidence}")
        lines.append("")

    if artifact.limitations:
        lines.append("#### Limitations")
        for item in artifact.limitations:
            lines.append(f"- {item}")
        lines.append("")

    if artifact.follow_up_suggestions:
        lines.append("#### Useful follow-ups")
        for item in artifact.follow_up_suggestions[:4]:
            lines.append(f"- {item}")
        lines.append("")

    return enforce_sebi_compliance("\n".join(lines).strip(), include_regulatory_note=False) + "\n"


def render_rich_json(artifact: AnswerArtifact) -> dict:
    """Return a backend/frontend-friendly structured payload."""
    return {
        "mode": getattr(artifact.mode, "value", str(artifact.mode)),
        "title": enforce_sebi_compliance(artifact.title, include_regulatory_note=False).splitlines()[0],
        "subtitle": enforce_sebi_compliance(artifact.summary, include_regulatory_note=False).strip(),
        "metric_cards": [
            {
                "label": enforce_sebi_compliance(c.label, include_regulatory_note=False).splitlines()[0],
                "value": c.value,
                "change": c.change,
                "change_type": c.change_type,
                "tooltip": enforce_sebi_compliance(c.tooltip, include_regulatory_note=False).strip(),
                "icon": c.icon,
                "is_partial": c.is_partial,
            }
            for c in artifact.metric_cards
            if _has_display_value(c.value)
        ],
        "charts": [
            {
                "id": ch.id,
                "title": enforce_sebi_compliance(ch.title, include_regulatory_note=False).splitlines()[0],
                "subtitle": enforce_sebi_compliance(ch.subtitle, include_regulatory_note=False).strip(),
                "kind": ch.chart_type,
                "x_labels": ch.labels,
                "series": [
                    {
                        "name": s.name,
                        "color": s.color,
                        "values": [p.value for p in s.data],
                        "unit": s.unit,
                    }
                    for s in ch.series
                    if s.data
                ],
                "is_partial": ch.is_partial,
            }
            for ch in artifact.charts
            if ch.series and any(s.data for s in ch.series)
        ],
        "comparison_rows": [
            {
                "metric": enforce_sebi_compliance(r.metric, include_regulatory_note=False).splitlines()[0],
                "primary_value": r.primary_value,
                "secondary_value": r.secondary_value,
                "winner": r.winner,
                "delta": r.delta,
            }
            for r in artifact.comparison_results
            if _has_display_value(r.primary_value) and _has_display_value(r.secondary_value)
        ],
        "data_sources": [{"label": f"Reference {i}", "url": c.url} for i, c in enumerate(artifact.citations, 1)],
        "disclaimer": "",
    }

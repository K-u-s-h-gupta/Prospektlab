"""
Server-side report exporter for FinAgent.

Generates professional analyst-style documents (PDF, DOCX, XLSX)
from an AnswerArtifact.

Document generation is only enabled for Marathon mode.
"""
from __future__ import annotations

import io
from typing import Literal

from finagent.output.contracts import AnswerArtifact, ResponseDepth

# Optional dependencies — imported lazily so the rest of the app works
# even if the user hasn't installed reportlab/python-docx/openpyxl yet.
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.lib import colors
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


Style = Literal["sell_side", "buy_side", "auto"]


def _ensure_reportlab():
    if not HAS_REPORTLAB:
        raise RuntimeError(
            "reportlab is required for PDF export. "
            "Install it with: pip install reportlab"
        )


def export_pdf(
    artifact: AnswerArtifact,
    style: Style = "sell_side",
    filename: str | None = None,
) -> bytes:
    """Generate a professional PDF report from the artifact."""
    _ensure_reportlab()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=18,
        spaceAfter=12,
        textColor=colors.HexColor("#1e3a5f"),
    )
    heading_style = ParagraphStyle(
        "CustomHeading",
        parent=styles["Heading2"],
        fontSize=13,
        spaceBefore=14,
        spaceAfter=6,
        textColor=colors.HexColor("#2c5282"),
    )
    body_style = ParagraphStyle(
        "CustomBody",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        spaceAfter=8,
    )

    story = []

    # Title
    story.append(Paragraph(artifact.title or "Research Report", title_style))
    story.append(Spacer(1, 6))

    # Subtitle / Summary
    if artifact.summary:
        story.append(Paragraph("<b>Executive Summary</b>", heading_style))
        story.append(Paragraph(artifact.summary, body_style))
        story.append(Spacer(1, 8))

    # Sections
    for section in artifact.sections:
        story.append(Paragraph(f"<b>{section.title}</b>", heading_style))
        story.append(Paragraph(section.body, body_style))

    # Tables
    for table in artifact.tables:
        story.append(Paragraph(f"<b>{table.title}</b>", heading_style))
        data = [table.columns] + table.rows
        t = Table(data, repeatRows=1)
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c5282")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f7fafc")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e0")),
                ]
            )
        )
        story.append(t)
        story.append(Spacer(1, 12))

    # Citations
    if artifact.citations:
        story.append(Paragraph("<b>Sources</b>", heading_style))
        for c in artifact.citations[:12]:
            story.append(Paragraph(f"• {c.title} — {c.url}", body_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


def export_docx(artifact: AnswerArtifact, style: Style = "sell_side") -> bytes:
    """Generate a DOCX report (stub for now)."""
    try:
        from docx import Document
        from docx.shared import Inches, Pt
    except ImportError:
        raise RuntimeError("python-docx is required for DOCX export.")

    doc = Document()
    doc.add_heading(artifact.title or "Research Report", 0)
    if artifact.summary:
        doc.add_heading("Executive Summary", level=1)
        doc.add_paragraph(artifact.summary)

    for section in artifact.sections:
        doc.add_heading(section.title, level=2)
        doc.add_paragraph(section.body)

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer.read()


def export_xlsx(artifact: AnswerArtifact) -> bytes:
    """Generate an Excel workbook with key data."""
    try:
        from openpyxl import Workbook
    except ImportError:
        raise RuntimeError("openpyxl is required for XLSX export.")

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"

    ws["A1"] = "Title"
    ws["B1"] = artifact.title or ""
    ws["A2"] = "Summary"
    ws["B2"] = artifact.summary or ""

    # Add metric cards if present
    row = 4
    for card in artifact.metric_cards:
        ws.cell(row=row, column=1, value=card.label)
        ws.cell(row=row, column=2, value=card.value)
        row += 1

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()


def can_generate_documents(depth: ResponseDepth | str) -> bool:
    """Return True only when the user selected Marathon mode."""
    if isinstance(depth, str):
        return depth.lower() == "marathon"
    return depth == ResponseDepth.MARATHON

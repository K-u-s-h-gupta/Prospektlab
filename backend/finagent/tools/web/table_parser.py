"""Layout-preserving HTML extraction for financial filings and result pages."""

from __future__ import annotations

import re
import logging


_WS_RE = re.compile(r"[ \t\r\f\v]+")
logger = logging.getLogger("finagent.table_parser")


def _cell_text(cell) -> str:
    text = cell.get_text(" ", strip=True)
    return _WS_RE.sub(" ", text).replace("|", "/")


def _table_to_markdown(table) -> str:
    try:
        rows: list[list[str]] = []
        caption = table.find("caption")
        for tr in table.find_all("tr"):
            cells = tr.find_all(["th", "td"])
            if not cells:
                continue
            row = [_cell_text(cell) for cell in cells]
            if any(row):
                rows.append(row)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines: list[str] = []
        if caption:
            caption_text = _cell_text(caption)
            if caption_text:
                lines.append(f"Table: {caption_text}")
        lines.append("| " + " | ".join(rows[0]) + " |")
        lines.append("| " + " | ".join(["---"] * width) + " |")
        for row in rows[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)
    except Exception as exc:
        logger.debug("dropping malformed table during matrix extraction: %s", exc)
        return ""


def extract_layout_preserving_text(html: str, *, prefer_narrative: bool = False) -> tuple[str, str, list[str]]:
    """Extract visible text while preserving HTML table matrices.

    Tables are converted to markdown tables before being removed from the
    narrative body. This keeps quarterly P&L/balance-sheet structures usable for
    downstream analysis instead of flattening rows and columns into one blob.
    """

    from bs4 import BeautifulSoup  # type: ignore

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    title = (soup.title.string or "").strip() if soup.title else ""

    table_blocks: list[str] = []
    for table in soup.find_all("table"):
        table_md = _table_to_markdown(table)
        if table_md:
            table_blocks.append(table_md)
        table.decompose()

    narrative = soup.get_text("\n", strip=True)
    narrative = re.sub(r"\n{3,}", "\n\n", narrative).strip()
    if prefer_narrative:
        narrative = _narrative_slice(narrative) or narrative
    if table_blocks:
        narrative = (narrative + "\n\nTABLES\n" + "\n\n".join(table_blocks)).strip()
    return title, narrative, table_blocks


def _narrative_slice(text: str, limit: int = 1200) -> str:
    if not text:
        return ""
    pieces: list[str] = []
    total = 0
    for line in text.splitlines():
        line = line.strip()
        if len(line) < 30:
            continue
        alpha = sum(1 for ch in line if ch.isalpha() or ch.isspace())
        if alpha / max(len(line), 1) < 0.55:
            continue
        pieces.append(line)
        total += len(line) + 1
        if total >= limit:
            break
    return " ".join(pieces)[:limit]

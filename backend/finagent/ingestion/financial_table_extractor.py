"""Financial table extraction from DRHP markdown sections."""

from __future__ import annotations

import re
from typing import Any


def _parse_markdown_table_rows(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in (section or "").splitlines():
        if "|" not in line:
            continue
        stripped = line.strip()
        if not stripped or set(stripped.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells:
            rows.append(cells)
    return rows


def _to_number(raw: str) -> float | None:
    text = (raw or "").strip().replace(",", "")
    if not text or text in {"-", "—", "NA", "N/A"}:
        return None
    text = text.replace("(", "-").replace(")", "")
    try:
        return float(text)
    except ValueError:
        return None


def _find_metric_row(rows: list[list[str]], metric_aliases: tuple[str, ...]) -> list[str] | None:
    for row in rows:
        if not row:
            continue
        label = row[0].lower()
        if any(alias in label for alias in metric_aliases):
            return row
    return None


def _year_columns(header: list[str]) -> list[tuple[int, str]]:
    cols: list[tuple[int, str]] = []
    for idx, cell in enumerate(header):
        if re.search(r"20\d{2}|fy\s*20\d{2}|year ended", cell, flags=re.IGNORECASE):
            cols.append((idx, cell))
    return cols


def _compute_cagr(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    start, end = values[0], values[-1]
    years = len(values) - 1
    if start <= 0 or end <= 0 or years <= 0:
        return None
    return round(((end / start) ** (1 / years) - 1) * 100, 1)


def extract_restated_financials(financial_section: str) -> dict[str, Any]:
    """Pull restated revenue, EBITDA, PAT, debt, and cash flow for last 3 fiscal years."""
    rows = _parse_markdown_table_rows(financial_section)
    if len(rows) < 2:
        return {"years": [], "metrics": {}, "trends": {}, "flags": []}

    header = rows[0]
    year_cols = _year_columns(header)
    if not year_cols:
        # Assume last 3 numeric columns are fiscal years
        numeric_cols = [(idx, cell) for idx, cell in enumerate(header[1:], start=1) if _to_number(cell) is None]
        year_cols = numeric_cols[-3:]

    years = [label for _, label in year_cols]

    metric_map = {
        "revenue": ("total income", "revenue from operations", "total revenue", "turnover"),
        "ebitda": ("ebitda", "profit before exceptional", "pbdit"),
        "pat": ("profit after tax", "pat", "net profit", "profit/(loss) for the period"),
        "total_debt": ("total borrowings", "total debt", "borrowings"),
        "cash_flow": ("net cash from operating", "cash flow from operating", "net cash generated from operating"),
    }

    metrics: dict[str, list[float | None]] = {}
    for metric_name, aliases in metric_map.items():
        row = _find_metric_row(rows, aliases)
        if not row:
            metrics[metric_name] = [None] * len(year_cols)
            continue
        values: list[float | None] = []
        for idx, _ in year_cols:
            values.append(_to_number(row[idx]) if idx < len(row) else None)
        metrics[metric_name] = values

    trends: dict[str, Any] = {}
    flags: list[str] = []

    revenue_vals = [v for v in metrics.get("revenue", []) if v is not None]
    pat_vals = [v for v in metrics.get("pat", []) if v is not None]
    ebitda_vals = [v for v in metrics.get("ebitda", []) if v is not None]
    debt_vals = [v for v in metrics.get("total_debt", []) if v is not None]

    if revenue_vals:
        trends["revenue_cagr_pct"] = _compute_cagr(revenue_vals)
        if len(revenue_vals) >= 2 and revenue_vals[-1] < revenue_vals[-2]:
            flags.append("revenue_decline")
    if pat_vals:
        trends["pat_cagr_pct"] = _compute_cagr(pat_vals)
        if len(pat_vals) >= 2 and pat_vals[-1] < pat_vals[-2]:
            flags.append("pat_decline")
    if ebitda_vals and revenue_vals and len(ebitda_vals) == len(revenue_vals):
        margins = []
        for e, r in zip(ebitda_vals, revenue_vals):
            if e is not None and r not in (None, 0):
                margins.append(round(100.0 * e / r, 1))
            else:
                margins.append(None)
        trends["ebitda_margin_pct"] = margins
        clean = [m for m in margins if m is not None]
        if len(clean) >= 2 and clean[-1] < clean[-2] - 1:
            flags.append("margin_compression")
    if debt_vals and len(debt_vals) >= 2 and debt_vals[-1] is not None and debt_vals[-2] is not None:
        if debt_vals[-1] > debt_vals[-2] * 1.15:
            flags.append("rising_debt")

    return {
        "years": years,
        "metrics": metrics,
        "trends": trends,
        "flags": flags,
    }

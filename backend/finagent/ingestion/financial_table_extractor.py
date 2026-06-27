"""Financial table extraction from DRHP markdown.

Strategies (in order):
1. Full-document scan for the KPI summary table (Basis for Issue Price section) — most reliable
2. Full-document scan for any financial pipe-table with year columns + metric rows
3. Space/tab plain-text table fallback
4. Inline keyword scan (last resort)
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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
    if not text or text in {"-", "—", "NA", "N/A", "nil", "Nil", "NIL", "z", ""}:
        return None
    # Handle bracketed negatives: (1234.56) → -1234.56
    text = re.sub(r"^\((.+)\)$", r"-\1", text)
    # Remove trailing/leading non-numeric noise
    text = re.sub(r"[^\d.\-]", "", text)
    if not text or text == ".":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _metric_label_allowed(label: str, metric_name: str | None) -> bool:
    label = re.sub(r"\s+", " ", (label or "").lower()).strip()
    if not label:
        return False
    if metric_name == "revenue" and re.search(r"\brevenue\s+(?:by|mix)", label):
        return False
    if metric_name in {"ebitda", "pat"} and "margin" in label:
        return False
    if metric_name == "pat" and "profit after tax" not in label and re.search(r"\bpat\s+margin\b", label):
        return False
    if metric_name == "total_debt" and (
        "debt to equity" in label
        or "debt-to-equity" in label
        or "debt / equity" in label
        or "debt/equity" in label
        or "equity ratio" in label
    ):
        return False
    return True


def _label_candidates(row: list[str]) -> list[tuple[int, str]]:
    for cell_idx in range(min(3, len(row))):
        label = str(row[cell_idx] or "").lower()
        label_clean = re.sub(r"\s*\([ivxlcdm0-9]+\)\s*$", "", label).strip()
        if label_clean:
            return [(cell_idx, label_clean)]
    return []


def _alias_matches_label(label: str, alias: str) -> bool:
    alias = alias.lower().strip()
    if re.fullmatch(r"[a-z]{2,4}", alias):
        return re.search(rf"\b{re.escape(alias)}\b", label) is not None
    return alias in label


def _find_metric_row(rows: list[list[str]], metric_aliases: tuple[str, ...], metric_name: str | None = None) -> list[str] | None:
    """Find a row whose first real label cell matches the metric."""
    for row in rows:
        if not row:
            continue
        for _, label_clean in _label_candidates(row):
            if not _metric_label_allowed(label_clean, metric_name):
                continue
            if any(_alias_matches_label(label_clean, alias) for alias in metric_aliases):
                return row
    return None


def _year_columns(header: list[str]) -> list[tuple[int, str]]:
    """Find column indices that correspond to fiscal years."""
    cols: list[tuple[int, str]] = []
    for idx, cell in enumerate(header):
        cell_s = str(cell or "")
        if re.search(r"20\d{2}|fy\s*20\d{2}|year ended|h[12]\s+20\d{2}|six months|nine months|dec[^a-z]|mar[^a-z]|sep[^a-z]", cell_s, flags=re.IGNORECASE):
            cols.append((idx, cell_s.strip()))
    return cols


def _compute_cagr(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    start, end = values[0], values[-1]
    years = len(values) - 1
    if start <= 0 or end <= 0 or years <= 0:
        return None
    return round(((end / start) ** (1 / years) - 1) * 100, 1)


def _extract_values_from_row(row: list[str], year_cols: list[tuple[int, str]]) -> list[float | None]:
    """Extract numeric values at year column indices, skipping empty padding cells."""
    values: list[float | None] = []
    for idx, _ in year_cols:
        if idx < len(row):
            values.append(_to_number(row[idx]))
        else:
            values.append(None)
    return values


def _value_scale_for_unit(unit: str, metric_name: str) -> float:
    lowered = (unit or "").lower()
    if metric_name not in {"revenue", "ebitda", "pat", "total_debt", "cash_flow"}:
        return 1.0
    if any(token in lowered for token in ("times", "ratio", "%")):
        return 1.0
    if "lakh" in lowered or "lac" in lowered:
        return 0.01
    if "million" in lowered or "mn" in lowered:
        return 0.1
    if "thousand" in lowered:
        return 0.00001
    return 1.0


def _metric_label_col(row: list[str], metric_name: str, aliases: tuple[str, ...]) -> int | None:
    for cell_idx, label_clean in _label_candidates(row):
        if _metric_label_allowed(label_clean, metric_name) and any(_alias_matches_label(label_clean, alias) for alias in aliases):
            return cell_idx
    return None


def _row_unit(row: list[str], label_col: int) -> str:
    for cell in row[label_col + 1: min(label_col + 4, len(row))]:
        lowered = str(cell or "").lower()
        if any(token in lowered for token in ("lakh", "lac", "crore", "million", "mn", "thousand", "rs", "inr", "%", "times")):
            return str(cell or "")
    return ""


def _scaled_metric_values(row: list[str], year_cols: list[tuple[int, str]], metric_name: str, aliases: tuple[str, ...]) -> list[float | None]:
    label_col = _metric_label_col(row, metric_name, aliases)
    unit = _row_unit(row, label_col if label_col is not None else 0)
    scale = _value_scale_for_unit(unit, metric_name)
    values: list[float | None] = []
    for idx, _ in year_cols:
        value = _to_number(row[idx]) if idx < len(row) else None
        values.append(round(value * scale, 4) if value is not None else None)
    return values


def _combined_header_rows(rows: list[list[str]], width: int) -> list[str]:
    combined: list[str] = []
    for col_idx in range(width):
        pieces: list[str] = []
        seen: set[str] = set()
        for row in rows:
            if col_idx >= len(row):
                continue
            cell = re.sub(r"\s+", " ", str(row[col_idx] or "")).strip()
            if not cell or cell in seen:
                continue
            pieces.append(cell)
            seen.add(cell)
        combined.append(" ".join(pieces))
    return combined


def _try_extract_from_multirow_pipe_rows(rows: list[list[str]]) -> dict[str, Any] | None:
    """Parse PyMuPDF tables whose year headers are split across several rows."""
    if not rows:
        return None
    candidate_indices = [
        idx for idx, row in enumerate(rows)
        if any(_FIN_TABLE_ANCHOR_RE.search(str(cell or "")) for cell in row[:3])
    ]
    best_result: dict[str, Any] | None = None
    best_score = -1

    for start_idx in candidate_indices:
        width = max((len(row) for row in rows[max(0, start_idx - 12): start_idx + 12]), default=0)
        if width < 3:
            continue
        header_rows = rows[max(0, start_idx - 12): start_idx]
        header = _combined_header_rows(header_rows, width)
        year_cols = _year_columns(header)
        if len(year_cols) < 2:
            continue
        data_rows = rows[start_idx: min(len(rows), start_idx + 80)]
        metrics: dict[str, list[float | None]] = {}
        unit_hits = 0
        for metric_name, aliases in _METRIC_MAP.items():
            row = _find_metric_row(data_rows, aliases, metric_name)
            if row:
                label_col = _metric_label_col(row, metric_name, aliases)
                if _row_unit(row, label_col if label_col is not None else 0):
                    unit_hits += 1
                metrics[metric_name] = _scaled_metric_values(row, year_cols, metric_name, aliases)
            else:
                metrics[metric_name] = [None] * len(year_cols)

        coverage = sum(
            1 for key in ("revenue", "ebitda", "pat")
            if any(value is not None for value in metrics.get(key, []))
        )
        if coverage < 2 and unit_hits == 0:
            continue
        if not any(any(v is not None for v in metrics.get(key, [])) for key in ("revenue", "pat")):
            continue

        result = _build_result([label for _, label in year_cols], metrics)
        score = coverage * 10 + unit_hits * 4 + len(year_cols)
        if score > best_score:
            best_score = score
            best_result = result

    return best_result


# ---------------------------------------------------------------------------
# Strategy 1: Full-document pipe-table scan
# Searches the entire markdown for the KPI/financial summary table that
# SEBI-mandated documents always include in the "Basis for Issue Price" chapter.
# ---------------------------------------------------------------------------

_FIN_TABLE_ANCHOR_RE = re.compile(
    r"(?:revenue\s*from\s*operations|total\s*income|total\s*revenue|turnover|"
    r"interest\s*income|profit\s*after\s*tax|pat|ebitda)",
    re.IGNORECASE,
)

_YEAR_DATE_RE = re.compile(
    r"(?:december|march|june|september|sept)\s+\d{1,2},?\s*20\d{2}|"
    r"march\s+31,?\s*20\d{2}|"
    r"31\s+march\s+20\d{2}|"
    r"fy\s*20\d{2}|"
    r"\b20\d{2}\s*-\s*\d{2,4}\b|"
    r"six\s+months|nine\s+months|half\s+year",
    re.IGNORECASE,
)


def _find_best_financial_table(full_text: str) -> tuple[list[str], list[list[str]]] | None:
    """Scan the full markdown for the best financial summary table.

    Returns (year_labels, data_rows) or None if nothing found.
    Prioritises the KPI summary table (Basis for Issue Price) which is
    consistently present in all SEBI prospectus documents.
    """
    lines = full_text.splitlines()
    n = len(lines)

    # Sliding window: find a header row with 2+ year-date cells, then look for
    # data rows with financial metric names.
    best_score = 0
    best_years: list[str] = []
    best_data: list[list[str]] = []

    for i, line in enumerate(lines):
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        year_hits = [c for c in cells if c and _YEAR_DATE_RE.search(c)]
        if len(year_hits) < 2:
            continue

        # Found a potential header row — collect data rows below it
        year_labels = year_hits
        year_col_indices = [ci for ci, c in enumerate(cells) if c and _YEAR_DATE_RE.search(c)]

        data_rows: list[list[str]] = []
        metric_count = 0
        for j in range(i + 1, min(i + 60, n)):
            dl = lines[j]
            if "|" not in dl:
                continue
            dcells = [c.strip() for c in dl.strip("|").split("|")]
            if not dcells:
                continue
            # Skip separator rows
            if all(set(c.replace("-", "").replace(":", "").replace(" ", "")) <= {"", "|"} for c in dcells):
                continue
            data_rows.append(dcells)
            # Check if this row has a financial metric label
            for ci in range(min(3, len(dcells))):
                label = re.sub(r"\s*\([ivxlcdm]+\)\s*$", "", str(dcells[ci] or "").lower()).strip()
                if label and _FIN_TABLE_ANCHOR_RE.search(label):
                    metric_count += 1
                    break

        score = metric_count * 10 + len(year_labels) * 2
        if score > best_score and metric_count >= 2:
            best_score = score
            best_years = year_labels
            # Rebuild data rows with consistent year-col alignment
            best_data = []
            header_cells = cells
            for row in data_rows:
                best_data.append(row)

    if best_years and best_data:
        return best_years, best_data
    return None


# ---------------------------------------------------------------------------
# Strategy 2: Space/tab plain-text table
# ---------------------------------------------------------------------------

_YEAR_CELL_RE = re.compile(r"fy\s*20\d{2}|20\d{2}-\d{2,4}|\b20\d{2}\b", re.IGNORECASE)
_NUM_CELL_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
_PAREN_NUM_RE = re.compile(r"^\(-?[\d,]+(?:\.\d+)?\)$")


def _split_plain_row(line: str) -> list[str]:
    parts = [p.strip() for p in line.split("\t") if p.strip()]
    if len(parts) >= 3:
        return parts
    parts = [p.strip() for p in re.split(r"\s{3,}", line) if p.strip()]
    if len(parts) >= 3:
        return parts
    return [p.strip() for p in re.split(r"\s{2,}", line) if p.strip()]


def _parse_plain_text_table(section: str) -> tuple[list[str], list[list[str]]]:
    lines = [l for l in (section or "").splitlines() if l.strip()]
    years: list[str] = []
    header_line_idx = -1
    for i, line in enumerate(lines):
        if _YEAR_CELL_RE.search(line):
            parts = _split_plain_row(line)
            year_parts = [p for p in parts if _YEAR_CELL_RE.search(p)]
            if len(year_parts) >= 2:
                years = year_parts
                header_line_idx = i
                break
    if not years:
        return [], []
    data_rows: list[list[str]] = []
    for line in lines[header_line_idx + 1:]:
        parts = _split_plain_row(line)
        if len(parts) < 2:
            continue
        numeric_count = sum(
            1 for p in parts[1:]
            if _NUM_CELL_RE.match(p.replace(",", "")) or _PAREN_NUM_RE.match(p.replace(",", ""))
        )
        if numeric_count >= 2:
            data_rows.append(parts)
    return years, data_rows


def _match_plain_metric(data_rows: list[list[str]], aliases: tuple[str, ...], n_years: int) -> list[float | None]:
    for row in data_rows:
        if not row:
            continue
        for cell_idx in range(min(2, len(row))):
            label = re.sub(r"\s*\([ivxlcdm]+\)\s*$", "", str(row[cell_idx] or "").lower()).strip()
            if label and any(alias in label for alias in aliases):
                nums: list[float | None] = []
                for cell in row[cell_idx + 1:]:
                    nums.append(_to_number(cell))
                while len(nums) < n_years:
                    nums.insert(0, None)
                return nums[-n_years:]
    return [None] * n_years


# ---------------------------------------------------------------------------
# Strategy 3: Inline scan (last resort)
# ---------------------------------------------------------------------------

def _scan_inline_metric(text: str, aliases: tuple[str, ...]) -> list[float] | None:
    lower = text.lower()
    for alias in aliases:
        start = lower.find(alias)
        if start == -1:
            continue
        snippet = text[start: start + 600]
        matches = re.findall(
            r"(?:₹|rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)\s*(?:crores?|cr\.?|lakhs?)?",
            snippet, re.IGNORECASE,
        )
        values: list[float] = []
        for raw in matches:
            try:
                v = float(raw.replace(",", ""))
                if 0 < v < 1_000_000:
                    values.append(v)
            except ValueError:
                pass
        if len(values) >= 2:
            return values[-3:]
    return None


# ---------------------------------------------------------------------------
# Metric alias map
# ---------------------------------------------------------------------------

_METRIC_MAP: dict[str, tuple[str, ...]] = {
    "revenue": (
        "revenue from operations",
        "total income",
        "total revenue",
        "turnover",
        "interest income",
        "net interest income",
        "total interest income",
        "income from operations",
        "revenue from operation",
    ),
    "ebitda": (
        "ebitda",
        "profit before exceptional",
        "pbdit",
        "operating profit",
        "profit before interest",
        "pre-provision operating profit",
        "ebit",
    ),
    "pat": (
        "profit after tax",
        "pat",
        "net profit",
        "profit/(loss) for the period",
        "profit/(loss) after tax",
        "profit for the year",
        "profit for the period",
        "net income",
    ),
    "total_debt": (
        "total borrowings",
        "total debt",
        "borrowings",
        "long-term borrowings",
        "total liabilities",
        "debt securities",
        "total outstanding borrowings",
    ),
    "cash_flow": (
        "net cash from operating",
        "cash flow from operating",
        "net cash generated from operating",
        "operating cash flow",
        "cash generated from operations",
    ),
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_restated_financials(financial_section: str, full_text: str = "") -> dict[str, Any]:
    """Pull restated financials for the last 3 fiscal years.

    Tries strategies in order:
    1. Full-document pipe-table scan (most reliable for Indian prospectuses)
    2. Section pipe-table scan
    3. Space/tab plain-text table
    4. Inline keyword scan (last resort)
    """
    # ------------------------------------------------------------------
    # Strategy 1: Full-document scan (highest priority for SEBI docs)
    # ------------------------------------------------------------------
    search_text = full_text if full_text else financial_section
    if search_text:
        pipe_rows = _parse_markdown_table_rows(search_text)
        multirow_result = _try_extract_from_multirow_pipe_rows(pipe_rows)
        if multirow_result:
            return multirow_result

        found = _find_best_financial_table(search_text)
        if found:
            years, data_rows = found
            metrics = _extract_metrics_from_data_rows(data_rows, years)
            has_data = any(any(v is not None for v in vals) for k, vals in metrics.items() if k in ("revenue", "pat"))
            if has_data:
                return _build_result(years, metrics)

    # ------------------------------------------------------------------
    # Strategy 2: Section-only pipe-table
    # ------------------------------------------------------------------
    if financial_section:
        rows = _parse_markdown_table_rows(financial_section)
        if len(rows) >= 2:
            result = _try_extract_from_pipe_rows(rows)
            if result:
                return result

    # ------------------------------------------------------------------
    # Strategy 3: Plain-text table (section then full)
    # ------------------------------------------------------------------
    for text in [financial_section, full_text]:
        if not text:
            continue
        pt_years, pt_rows = _parse_plain_text_table(text)
        if pt_years and pt_rows:
            n = len(pt_years)
            metrics = {}
            for metric_name, aliases in _METRIC_MAP.items():
                metrics[metric_name] = _match_plain_metric(pt_rows, aliases, n)
            has_data = any(any(v is not None for v in vals) for k, vals in metrics.items() if k in ("revenue", "pat"))
            if has_data:
                return _build_result(pt_years, metrics)

    # ------------------------------------------------------------------
    # Strategy 4: Inline keyword scan (last resort)
    # ------------------------------------------------------------------
    for text in [financial_section, full_text]:
        if not text:
            continue
        year_matches = re.findall(r"\bFY\s*20\d{2}\b|\bFiscal\s+20\d{2}\b|\b20\d{2}-\d{2,4}\b", text, re.IGNORECASE)
        unique_years = list(dict.fromkeys(year_matches))[-3:]
        inline_metrics: dict[str, list[float | None]] = {}
        for metric_name, aliases in _METRIC_MAP.items():
            found_vals = _scan_inline_metric(text, aliases)
            inline_metrics[metric_name] = found_vals if found_vals else []
        has_data = bool(inline_metrics.get("revenue") or inline_metrics.get("pat"))
        if has_data:
            n = max((len(v) for v in inline_metrics.values() if v), default=0)
            if n == 0:
                continue
            if not unique_years:
                import datetime
                cy = datetime.datetime.now().year
                unique_years = [f"FY{y}" for y in range(cy - n + 1, cy + 1)]
            for k in inline_metrics:
                while len(inline_metrics[k]) < n:
                    inline_metrics[k].insert(0, None)  # type: ignore
                inline_metrics[k] = inline_metrics[k][-n:]
            return _build_result(unique_years[:n], inline_metrics)

    return {"years": [], "metrics": {}, "trends": {}, "flags": []}


def _extract_metrics_from_data_rows(data_rows: list[list[str]], years: list[str]) -> dict[str, list[float | None]]:
    """Extract metric values from parsed data rows, using year header to find column indices."""
    # Rebuild a fake header that matches the year positions found
    # We need to find where year values actually land in the data rows
    # by looking at the header row that was already identified by _find_best_financial_table
    n = len(years)
    metrics: dict[str, list[float | None]] = {}
    for metric_name, aliases in _METRIC_MAP.items():
        row = _find_metric_row(data_rows, aliases, metric_name)
        if row is None:
            metrics[metric_name] = [None] * n
            continue
        label_col = _metric_label_col(row, metric_name, aliases)
        unit = _row_unit(row, label_col if label_col is not None else 0)
        scale = _value_scale_for_unit(unit, metric_name)
        nums: list[float | None] = []
        for cell in row[(label_col or 0) + 1:]:
            value = _to_number(cell)
            nums.append(round(value * scale, 4) if value is not None else None)
        nums_clean = [v for v in nums if v is not None]
        if len(nums_clean) >= n:
            metrics[metric_name] = nums_clean[:n]
        elif nums_clean:
            padded: list[float | None] = [None] * (n - len(nums_clean)) + nums_clean
            metrics[metric_name] = padded
        else:
            metrics[metric_name] = [None] * n
    return metrics


def _try_extract_from_pipe_rows(rows: list[list[str]]) -> dict[str, Any] | None:
    """Try standard pipe-table extraction from already-parsed rows."""
    header_idx = 0
    header = rows[0]
    year_cols = _year_columns(header)
    if not year_cols:
        for idx, candidate in enumerate(rows[:12]):
            candidate_years = _year_columns(candidate)
            if len(candidate_years) >= 2:
                header_idx = idx
                header = candidate
                year_cols = candidate_years
                break
    if not year_cols:
        fallback_cols = [(idx, cell) for idx, cell in enumerate(header[1:], start=1) if str(cell or "").strip()]
        year_cols = fallback_cols[-3:]
    if not year_cols:
        return None

    years = [label for _, label in year_cols]
    data_rows = rows[header_idx + 1:] if header_idx + 1 < len(rows) else rows[1:]
    n = len(year_cols)
    metrics: dict[str, list[float | None]] = {}
    for metric_name, aliases in _METRIC_MAP.items():
        row = _find_metric_row(data_rows, aliases, metric_name)
        if not row:
            metrics[metric_name] = [None] * n
            continue
        metrics[metric_name] = _scaled_metric_values(row, year_cols, metric_name, aliases)

    has_data = any(any(v is not None for v in vals) for k, vals in metrics.items() if k in ("revenue", "pat"))
    if not has_data:
        return None
    return _build_result(years, metrics)


# ---------------------------------------------------------------------------
# _build_result: normalise years + compute CAGR / flags
# ---------------------------------------------------------------------------

def _build_result(years: list[str], metrics: dict[str, list[float | None]]) -> dict[str, Any]:
    """Normalise years to oldest-first, compute CAGR and flags."""
    clean_years: list[str] = []
    year_ints: list[int] = []
    is_partial: list[bool] = []

    for y in years:
        y = str(y or "").strip()
        # Detect half-year / 9-month periods (Dec 31, Sep 30 endings = partial year)
        partial = bool(re.search(r"december|dec\b|september|sep\b|june|jun\b", y, re.IGNORECASE))
        m = re.search(r"(20\d{2})", y)
        if m:
            yr = int(m.group(1))
            if partial:
                # Dec 31, 2025 = 9M of FY2026 → label as "9M FY26"
                label = f"9M FY{str(yr + 1)[-2:]}" if re.search(r"dec", y, re.IGNORECASE) else f"H1 FY{str(yr + 1)[-2:]}"
            else:
                label = f"FY{yr}"
            clean_years.append(label)
            year_ints.append(yr if not partial else yr + 1)  # use next year for sorting
        else:
            clean_years.append(y)
            year_ints.append(0)
        is_partial.append(partial)

    # Deduplicate years (handles case where FY2025 and 9M-FY26 both map to similar ints)
    seen_labels: dict[str, int] = {}
    final_years: list[str] = []
    final_keep: list[int] = []
    for i, label in enumerate(clean_years):
        if label not in seen_labels:
            seen_labels[label] = i
            final_years.append(label)
            final_keep.append(i)
        # Skip duplicate labels

    if len(final_keep) < len(clean_years):
        metrics = {k: [v[i] for i in final_keep] for k, v in metrics.items()}
        clean_years = final_years
        year_ints = [year_ints[i] for i in final_keep]

    # Reverse to oldest-first if years are descending
    if len(year_ints) >= 2 and year_ints[0] > year_ints[-1]:
        clean_years = clean_years[::-1]
        metrics = {k: v[::-1] for k, v in metrics.items()}

    # Keep only FY years for CAGR calculation (exclude partial periods)
    # Partial periods (9M, H1) are kept in display but excluded from CAGR
    fy_only_indices = [i for i, y in enumerate(clean_years) if not re.match(r"^(?:9M|H1|H2)", y)]

    # Drop all-None leading columns (only for full-year data)
    n = len(clean_years)
    keep = list(range(n))
    for col in list(keep):
        if all(metrics.get(k, [None] * n)[col] is None for k in ("revenue", "pat")):
            keep.remove(col)
    if keep and len(keep) < n:
        clean_years = [clean_years[i] for i in keep]
        metrics = {k: [v[i] for i in keep] for k, v in metrics.items()}
        n = len(clean_years)
        fy_only_indices = [i for i, y in enumerate(clean_years) if not re.match(r"^(?:9M|H1|H2)", y)]

    # Remove all-None metric rows
    metrics = {k: v for k, v in metrics.items() if any(x is not None for x in v)}

    trends: dict[str, Any] = {}
    flags: list[str] = []

    # Use FY-only values for CAGR
    def _fy_vals(key: str) -> list[float]:
        full_list = metrics.get(key, [])
        return [full_list[i] for i in fy_only_indices if i < len(full_list) and full_list[i] is not None]

    revenue_vals = _fy_vals("revenue")
    pat_vals = _fy_vals("pat")
    all_revenue = [v for v in metrics.get("revenue", []) if v is not None]
    all_pat = [v for v in metrics.get("pat", []) if v is not None]
    ebitda_all = metrics.get("ebitda", [])
    rev_all = metrics.get("revenue", [])
    debt_vals = [v for v in metrics.get("total_debt", []) if v is not None]

    if revenue_vals:
        cagr = _compute_cagr(revenue_vals)
        trends["revenue_cagr_pct"] = cagr
        if len(revenue_vals) >= 2 and revenue_vals[-1] < revenue_vals[-2]:
            flags.append("revenue_decline")
    if pat_vals:
        trends["pat_cagr_pct"] = _compute_cagr(pat_vals)
        if len(pat_vals) >= 2 and pat_vals[-1] < pat_vals[-2]:
            flags.append("pat_decline")
    if ebitda_all and rev_all and len(ebitda_all) == len(rev_all):
        margins = []
        for e, r in zip(ebitda_all, rev_all):
            if e is not None and r not in (None, 0):
                margins.append(round(100.0 * e / r, 1))
            else:
                margins.append(None)
        trends["ebitda_margin_pct"] = margins
        clean = [m for m in margins if m is not None]
        if len(clean) >= 2 and clean[-1] < clean[-2] - 1:
            flags.append("margin_compression")
    if debt_vals and len(debt_vals) >= 2:
        if debt_vals[-1] > debt_vals[-2] * 1.15:
            flags.append("rising_debt")

    return {"years": clean_years, "metrics": metrics, "trends": trends, "flags": flags}

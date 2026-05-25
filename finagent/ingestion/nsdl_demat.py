"""Extract equity demat holdings from NSDL / CDSL eCAS PDFs.

Primary: pdfplumber table extraction.
Fallback: camelot-py (lattice then stream mode).
Diagnostics: per-mode extraction logs for debugging.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Any

logger = logging.getLogger("finagent.ingestion.nsdl_demat")

# Page-text signatures that indicate an equity-holdings table is present
_EQUITY_SECTION_SIGNATURES = [
    "equities & etfs held in demat account",
    "equity holdings",
    "demat account - equity",
    "securities held in demat",
    "equity / etf holdings",
    "listed equity securities",
]

# Table-column header variants → canonical field name
_HEADER_ALIASES: dict[str, list[str]] = {
    "isin": ["isin", "isin code", "isin no", "isin number", "security isin"],
    "name": ["company name", "security name", "name of security", "security", "scrip name", "description", "name"],
    "quantity": ["quantity", "qty", "units", "balance", "closing balance", "no. of shares", "shares"],
    "market_value": ["market value", "current value", "valuation", "amount", "value (inr)", "value", "closing value"],
    "cost_basis": ["cost", "cost basis", "invested value", "purchase value", "buy value", "acquisition cost", "average cost"],
    "exchange": ["exchange", "market", "segment"],
    "symbol": ["symbol", "ticker", "scrip code", "security code"],
}


def extract_nsdl_equity_demat(pdf_bytes: bytes, password: str = "") -> list[dict[str, Any]]:
    """Return equity demat positions from an NSDL/CDSL eCAS PDF.

    Tries pdfplumber first; falls back to camelot lattice then stream.
    Returns diagnostics in each mode for the caller to log.
    """
    diagnostics: dict[str, Any] = {"pdfplumber": None, "camelot_lattice": None, "camelot_stream": None}

    # ── Primary: pdfplumber ──────────────────────────────────────────────
    try:
        positions = _extract_with_pdfplumber(pdf_bytes, password)
        diagnostics["pdfplumber"] = {"positions": len(positions), "error": None}
        if positions:
            logger.info("pdfplumber extracted %d equity positions", len(positions))
            return positions
    except Exception as exc:
        diagnostics["pdfplumber"] = {"positions": 0, "error": str(exc)}
        logger.warning("pdfplumber equity extraction failed: %s", exc)

    # ── Fallback 1: camelot lattice ────────────────────────────────────────
    try:
        positions = _extract_with_camelot(pdf_bytes, password, mode="lattice")
        diagnostics["camelot_lattice"] = {"positions": len(positions), "error": None}
        if positions:
            logger.info("camelot lattice extracted %d equity positions", len(positions))
            return positions
    except Exception as exc:
        diagnostics["camelot_lattice"] = {"positions": 0, "error": str(exc)}
        logger.debug("camelot lattice failed: %s", exc)

    # ── Fallback 2: camelot stream ─────────────────────────────────────────
    try:
        positions = _extract_with_camelot(pdf_bytes, password, mode="stream")
        diagnostics["camelot_stream"] = {"positions": len(positions), "error": None}
        if positions:
            logger.info("camelot stream extracted %d equity positions", len(positions))
            return positions
    except Exception as exc:
        diagnostics["camelot_stream"] = {"positions": 0, "error": str(exc)}
        logger.debug("camelot stream failed: %s", exc)

    logger.info("All equity extractors returned 0 positions. Diagnostics: %s", diagnostics)
    return []


def _extract_with_pdfplumber(pdf_bytes: bytes, password: str) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    try:
        import pdfplumber as _pdfplumber
        pdf_file = io.BytesIO(pdf_bytes)
        with _pdfplumber.open(pdf_file, password=password or None) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                text = (page.extract_text() or "").lower()
                if not any(sig in text for sig in _EQUITY_SECTION_SIGNATURES):
                    continue

                tables = page.extract_tables()
                if not tables:
                    continue

                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    rows = _parse_table(table)
                    for row in rows:
                        pos = _row_to_position(row)
                        if pos:
                            positions.append(pos)
    except Exception:
        raise
    return positions


def _extract_with_camelot(pdf_bytes: bytes, password: str, mode: str) -> list[dict[str, Any]]:
    """Use camelot-py to extract tables from the PDF."""
    positions: list[dict[str, Any]] = []
    try:
        import camelot.io as camelot
        # camelot requires a file path, not bytes; write to temp
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        try:
            # If password protected, camelot may fail; skip in that case
            tables = camelot.read_pdf(tmp_path, pages="all", flavor=mode)
            for table in tables:
                # Convert camelot DataFrame to list of lists
                df = table.df
                if df.empty or len(df) < 2:
                    continue
                rows = _parse_table(df.values.tolist())
                for row in rows:
                    pos = _row_to_position(row)
                    if pos:
                        positions.append(pos)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception:
        raise
    return positions


def _parse_table(table: list[list[str | None]]) -> list[dict[str, Any]]:
    """Identify header row, map columns, and return data rows as dicts."""
    # Find the header row by looking for ISIN or Company Name keywords
    header_idx = -1
    header_cells: list[str] = []
    for idx, row in enumerate(table):
        cleaned = [str(cell or "").strip().lower() for cell in row]
        # Heuristic: if row contains both 'isin' and some name/quantity keywords, it's the header
        if any(h in cleaned for h in _HEADER_ALIASES["isin"]) and \
           any(h in cleaned for h in _HEADER_ALIASES["name"] + _HEADER_ALIASES["quantity"]):
            header_idx = idx
            header_cells = cleaned
            break

    if header_idx < 0:
        return []

    # Build column index → canonical field mapping
    col_map: dict[int, str] = {}
    for cidx, cell in enumerate(header_cells):
        for canon, aliases in _HEADER_ALIASES.items():
            if any(alias in cell for alias in aliases):
                col_map[cidx] = canon
                break

    # If we didn't map ISIN or name, this probably isn't the right table
    if "isin" not in col_map.values() and "name" not in col_map.values():
        return []

    rows: list[dict[str, Any]] = []
    for row in table[header_idx + 1 :]:
        if not any(str(cell or "").strip() for cell in row):
            continue
        mapped: dict[str, Any] = {}
        for cidx, canon in col_map.items():
            if cidx < len(row):
                mapped[canon] = str(row[cidx] or "").strip()
        if mapped.get("isin") or mapped.get("name"):
            rows.append(mapped)
    return rows


def _row_to_position(row: dict[str, Any]) -> dict[str, Any] | None:
    isin = _clean_isin(row.get("isin", ""))
    name = _clean_name(row.get("name", ""))
    if not isin and not name:
        return None

    quantity = _parse_number(row.get("quantity", ""))
    market_value = _parse_number(row.get("market_value", ""))
    cost_basis = _parse_number(row.get("cost_basis", ""))

    # Skip summary / total rows
    if quantity <= 0 and market_value <= 0:
        return None
    if any(name.lower().startswith(w) for w in ("total", "sub total", "grand total", "summary")):
        return None

    exchange = (row.get("exchange") or "NSE").strip().upper()
    if exchange in {"BSE", "BOMBAY", "BO"}:
        exchange = "BSE"
    else:
        exchange = "NSE"

    symbol = (row.get("symbol") or "").strip().upper()
    if not symbol and isin:
        # Symbol will be resolved later via ISIN→ticker map
        symbol = isin

    return {
        "symbol": symbol,
        "name": name,
        "isin": isin,
        "exchange": exchange,
        "quantity": quantity,
        "market_value": market_value,
        "cost_basis": cost_basis,
        "active": True,
        "kind": "equity",
        "avg_cost": (cost_basis / quantity) if quantity and cost_basis else 0.0,
    }


def _clean_isin(value: str) -> str:
    v = re.sub(r"[^A-Za-z0-9]", "", str(value or "").strip().upper())
    # INE pattern check
    if len(v) >= 12 and v.startswith("IN"):
        return v[:12]
    return v


def _clean_name(value: str) -> str:
    v = str(value or "").strip()
    # Remove trailing corporate suffixes for display
    v = re.sub(r"\s*-\s*EQ\s*$", "", v, flags=re.IGNORECASE)
    return v


def _parse_number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    txt = str(value)
    # Remove INR/₹, commas, spaces
    txt = re.sub(r"[₹,\s]", "", txt)
    # Handle negative in parentheses: (1,234.56)
    if txt.startswith("(") and txt.endswith(")"):
        txt = "-" + txt[1:-1]
    try:
        return float(txt)
    except ValueError:
        return 0.0

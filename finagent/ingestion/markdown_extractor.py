from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from finagent.ingestion.portfolio_schema import PortfolioExtractionSchema, PortfolioPositionSchema

logger = logging.getLogger("finagent.ingestion.markdown_extractor")

_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "symbol": ("symbol", "tradingsymbol", "trading symbol", "ticker", "scrip code", "security code", "instrument"),
    "name": ("company", "company name", "security", "security name", "name", "scheme", "scheme name", "description", "stock"),
    "isin": ("isin", "isin code", "isin no", "isin number"),
    "exchange": ("exchange", "segment", "market"),
    "quantity": ("quantity", "qty", "net qty", "units", "balance", "closing balance", "no. of shares", "shares", "holdings"),
    "market_value": ("market value", "current value", "valuation", "value", "value (inr)", "amount", "net value"),
    "cost_basis": ("cost basis", "invested value", "investment cost", "purchase value", "buy value", "total cost"),
    "avg_cost": ("avg cost", "average cost", "average price", "avg price", "buy average", "nav cost"),
    "last_price": ("ltp", "last price", "current price", "price", "nav", "close"),
    "as_of": ("as of", "date", "valuation date"),
    "amfi": ("amfi", "amfi code", "scheme code"),
}

_BAD_ROW_PREFIXES = ("total", "grand total", "sub total", "subtotal", "summary", "notes")
_ISIN_RE = re.compile(r"\b(IN[EFA-Z0-9][A-Z0-9]{9}\d)\b", re.IGNORECASE)


def _norm_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _canonical_header(value: str) -> str | None:
    norm = _norm_header(value)
    if not norm:
        return None
    for canonical, aliases in _HEADER_ALIASES.items():
        if any(alias == norm or alias in norm for alias in aliases):
            return canonical
    return None


def _split_markdown_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip().replace("<br>", " ") for cell in text.split("|")]


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell.strip()) for cell in cells if cell.strip())


def parse_markdown_tables(markdown: str) -> list[list[dict[str, str]]]:
    lines = (markdown or "").splitlines()
    tables: list[list[dict[str, str]]] = []
    idx = 0
    while idx < len(lines):
        if "|" not in lines[idx]:
            idx += 1
            continue
        block: list[str] = []
        while idx < len(lines) and "|" in lines[idx]:
            if lines[idx].strip():
                block.append(lines[idx])
            idx += 1
        if len(block) < 2:
            continue
        header = _split_markdown_row(block[0])
        start = 1
        if len(block) > 1 and _is_separator_row(_split_markdown_row(block[1])):
            start = 2
        canonical = [_canonical_header(cell) or f"col_{i}" for i, cell in enumerate(header)]
        if not any(c in {"symbol", "name", "isin", "quantity", "market_value"} for c in canonical):
            continue
        rows: list[dict[str, str]] = []
        for line in block[start:]:
            cells = _split_markdown_row(line)
            if len(cells) < 2:
                continue
            row = {canonical[i]: cells[i] for i in range(min(len(canonical), len(cells)))}
            rows.append(row)
        if rows:
            tables.append(rows)
    return tables


def parse_number(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return max(float(value), 0.0)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "-", "--", "n/a"}:
        return 0.0
    negative = text.startswith("(") and text.endswith(")")
    lower = text.lower()
    multiplier = 1.0
    if "crore" in lower or " cr" in lower or lower.endswith("cr"):
        multiplier = 10_000_000.0
    elif "lakh" in lower or " lac" in lower or lower.endswith("l"):
        multiplier = 100_000.0
    cleaned = re.sub(r"(?i)(inr|rs\.?|rupees?|crores?|cr|lakhs?|lacs?|lakh|lac)", "", text)
    cleaned = re.sub(r"[₹,\s]", "", cleaned)
    cleaned = cleaned.strip("()")
    cleaned = re.sub(r"[^0-9.\-]", "", cleaned)
    if not cleaned:
        return 0.0
    try:
        val = float(cleaned) * multiplier
    except ValueError:
        return 0.0
    if negative:
        val = -val
    return max(val, 0.0)


def _clean_symbol(value: str) -> str:
    text = str(value or "").strip().upper()
    if ":" in text:
        text = text.split(":")[-1]
    text = re.sub(r"[-_ ]?EQ$", "", text)
    text = text.removesuffix(".NS").removesuffix(".BO")
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text[:32]


def _clean_isin(*values: str) -> str:
    for value in values:
        match = _ISIN_RE.search(str(value or "").upper())
        if match:
            return match.group(1).upper()
    return ""


def _clean_name(value: str) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"\bIN[A-Z0-9]{10}\b", "", text, flags=re.IGNORECASE)
    return text.strip(" -:")[:160]


def _row_text(row: dict[str, str]) -> str:
    return " | ".join(str(v or "") for v in row.values())


def _row_to_position(row: dict[str, str]) -> tuple[PortfolioPositionSchema | None, str | None]:
    text = _row_text(row)
    lower = text.lower().strip()
    if not lower or any(lower.startswith(prefix) for prefix in _BAD_ROW_PREFIXES):
        return None, "summary_or_empty"

    isin = _clean_isin(row.get("isin", ""), text)
    amfi = _clean_symbol(row.get("amfi", ""))
    name = _clean_name(row.get("name", ""))
    raw_symbol = row.get("symbol", "") or row.get("isin", "")
    symbol = _clean_symbol(raw_symbol)
    exchange = (row.get("exchange") or "NSE").strip().upper()

    if isin.startswith("INF"):
        kind = "mf"
        exchange = "AMFI"
    elif "mutual fund" in lower or "scheme" in lower or exchange == "AMFI":
        kind = "mf"
        exchange = "AMFI"
    else:
        kind = "equity"
        exchange = "BSE" if exchange in {"BSE", "BO", ".BO"} else "NSE"

    quantity = parse_number(row.get("quantity"))
    market_value = parse_number(row.get("market_value"))
    cost_basis = parse_number(row.get("cost_basis"))
    avg_cost = parse_number(row.get("avg_cost"))
    last_price = parse_number(row.get("last_price"))

    if market_value <= 0 and quantity > 0 and last_price > 0:
        market_value = quantity * last_price
    if cost_basis <= 0 and quantity > 0 and avg_cost > 0:
        cost_basis = quantity * avg_cost

    if not symbol and isin:
        symbol = isin
    if not symbol and amfi:
        symbol = amfi
    if not name and symbol and not symbol.startswith("IN"):
        name = symbol

    if not (symbol or isin or amfi or name):
        return None, "missing_identity"
    if quantity <= 0 and market_value <= 0:
        return None, "missing_numeric_evidence"

    confidence = 0.45
    if isin:
        confidence += 0.25
    if symbol and not symbol.startswith("IN"):
        confidence += 0.15
    if market_value > 0:
        confidence += 0.1
    if quantity > 0:
        confidence += 0.05

    return PortfolioPositionSchema(
        symbol=symbol,
        name=name,
        isin=isin,
        amfi=amfi,
        exchange=exchange,
        kind=kind,
        quantity=quantity,
        market_value=market_value,
        cost_basis=cost_basis,
        avg_cost=avg_cost,
        last_price=last_price,
        as_of=str(row.get("as_of", "") or ""),
        confidence=min(confidence, 1.0),
        raw_evidence=text[:500],
    ), None


def extract_positions_from_markdown(
    markdown: str,
    *,
    source_type: str,
    broker_or_vendor: str = "",
    diagnostics: dict[str, Any] | None = None,
) -> PortfolioExtractionSchema:
    tables = parse_markdown_tables(markdown)
    rejected: dict[str, int] = defaultdict(int)
    positions: list[PortfolioPositionSchema] = []
    seen: dict[tuple[str, str, str], PortfolioPositionSchema] = {}
    for table in tables:
        for row in table:
            position, reason = _row_to_position(row)
            if position is None:
                rejected[reason or "unknown"] += 1
                continue
            key = (position.isin or position.symbol or position.name, position.exchange, position.kind)
            prior = seen.get(key)
            if prior is None:
                seen[key] = position
            else:
                seen[key] = prior.model_copy(
                    update={
                        "quantity": prior.quantity + position.quantity,
                        "market_value": prior.market_value + position.market_value,
                        "cost_basis": prior.cost_basis + position.cost_basis,
                        "confidence": max(prior.confidence, position.confidence),
                        "raw_evidence": f"{prior.raw_evidence} || {position.raw_evidence}"[:500],
                    }
                )
    positions = list(seen.values())
    confidence = sum(p.confidence for p in positions) / len(positions) if positions else 0.0
    warnings: list[str] = []
    if not positions:
        warnings.append("No holdings table rows with numeric evidence were found.")
    if rejected:
        warnings.append(f"Rejected rows: {dict(rejected)}")
    status = "MIRROR_SYNCHRONIZED" if positions and confidence >= 0.62 else ("REVIEW_REQUIRED" if positions else "MIRROR_EMPTY")
    merged_diag = dict(diagnostics or {})
    merged_diag.update(
        {
            "tables_found": len(tables),
            "positions_found": len(positions),
            "rows_rejected": dict(rejected),
            "markdown_preview": (markdown or "")[:4000],
        }
    )
    return PortfolioExtractionSchema(
        status=status,
        source_type=source_type if source_type in {"pdf", "csv", "xlsx", "image"} else "unknown",
        broker_or_vendor=broker_or_vendor,
        positions=positions,
        warnings=warnings,
        confidence=confidence,
        diagnostics=merged_diag,
    )

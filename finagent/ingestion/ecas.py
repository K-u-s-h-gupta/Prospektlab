"""eCAS / CAS PDF ingestion using local open-source parsers.

Replaces the previous CASParser SaaS integration with:
- codereverser/casparser for CAMS/KFintech MF statements
- pdfplumber-based extractor for NSDL/CDSL equity demat blocks
- camelot-py fallback for tabular equity extraction
- Document classification to reject non-CAS uploads

No external API keys required. No sandbox demo data.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Any

from finagent.ingestion.classifier import classify_pdf
from finagent.ingestion.nsdl_demat import extract_nsdl_equity_demat

logger = logging.getLogger("finagent.ingestion.ecas")


class EcasParseError(RuntimeError):
    pass


def _build_error_envelope(
    ok: bool = False,
    code: str = "UNKNOWN_ERROR",
    severity: str = "error",
    message: str = "",
    action_hint: str = "",
    diagnostics: dict[str, Any] | None = None,
    investor: dict[str, str | None] | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Standardized response envelope for all parse outcomes."""
    return {
        "ok": ok,
        "code": code,
        "severity": severity,  # "error" | "warning" | "info"
        "message": message,
        "action_hint": action_hint,
        "diagnostics": diagnostics or {},
        "investor": investor or {"name": None, "email": None, "pan": None},
        "summary": summary or {},
        "positions": [],
    }


async def parse_ecas_pdf(pdf_bytes: bytes, filename: str, password: str) -> dict[str, Any]:
    """Decision-tree parser for CAS/eCAS PDFs.

    Returns a unified envelope:
    - On success: ok=True, code=MIRROR_SYNCHRONIZED, positions=[...]
    - On empty-but-valid: ok=True, code=EMPTY_BUT_VALID, severity="warning"
    - On failure: ok=False, code=..., severity="error", action_hint=..., diagnostics=...
    """
    if not pdf_bytes:
        return _build_error_envelope(
            code="EMPTY_UPLOAD",
            message="Empty PDF upload.",
            action_hint="Please upload a valid eCAS PDF file.",
            diagnostics={"filename": filename},
        )
    if not password:
        return _build_error_envelope(
            code="PASSWORD_REQUIRED",
            message="eCAS password is required.",
            action_hint="Enter the PDF password (usually your PAN or date of birth).",
            diagnostics={"filename": filename},
        )

    # ── Step 1: Classify document ──────────────────────────────────────────
    classification = classify_pdf(pdf_bytes, password)
    logger.info("Classified %s: vendor=%s is_cas=%s isins=%d",
                filename, classification.get("vendor"), classification.get("is_cas"),
                classification.get("isin_count", 0))

    if not classification["is_cas"]:
        # If no vendor signature and < 3 ISINs, likely not a CAS
        if not classification["diagnostics"]["has_text"]:
            return _build_error_envelope(
                code="ENCRYPTED_OR_SCANNED",
                message="Could not extract text from this PDF. It may be password-protected or a scanned image.",
                action_hint="If this is a scanned CAS, re-download the text version from CAMS/KFintech/NSDL. Otherwise verify the password.",
                diagnostics=classification["diagnostics"],
            )
        return _build_error_envelope(
            code="WRONG_DOCUMENT_TYPE",
            message="This does not appear to be a CAS/eCAS statement.",
            action_hint="Upload a Consolidated Account Statement from CAMS, KFintech, NSDL, or CDSL.",
            diagnostics=classification["diagnostics"],
        )

    stype = classification.get("vendor") or "UNKNOWN"

    all_positions: list[dict[str, Any]] = []
    cas_meta: dict[str, Any] = {"statement_type": stype, "filename": filename}
    investor_info: dict[str, str | None] = {"name": None, "email": None, "pan": None}
    diagnostics: dict[str, Any] = {
        "classification": classification["diagnostics"],
        "mf_leg": {"attempted": False, "positions": 0, "error": None},
        "equity_leg": {"attempted": False, "positions": 0, "error": None},
    }

    # ── Mutual Fund leg (CAMS / KFINTECH / CDSL / UNKNOWN) ─────────────────
    if stype in {"CAMS", "KFINTECH", "CDSL_ECAS", "UNKNOWN"}:
        diagnostics["mf_leg"]["attempted"] = True
        try:
            import casparser
            payload = casparser.read_cas_pdf(
                io.BytesIO(pdf_bytes),
                password,
                output="dict",
            )
        except Exception as exc:
            msg = str(exc)
            if "password" in msg.lower() or "incorrect" in msg.lower():
                return _build_error_envelope(
                    code="INCORRECT_PASSWORD",
                    message="Incorrect eCAS password — please retry.",
                    action_hint="The password is usually your PAN (ABCDE1234F) or date of birth (DDMMYYYY).",
                    diagnostics={"classification": classification["diagnostics"], "casparser_error": msg},
                )
            diagnostics["mf_leg"]["error"] = msg
            payload = None

        if payload:
            cas_meta["file_type"] = payload.get("file_type")
            cas_meta["cas_type"] = payload.get("cas_type")
            inv = payload.get("investor_info") or {}
            investor_info["name"] = inv.get("name")
            investor_info["email"] = inv.get("email")
            investor_info["pan"] = inv.get("pan")

            mf_positions = _positions_from_casparser_payload(payload)
            diagnostics["mf_leg"]["positions"] = len(mf_positions)
            logger.info("casparser extracted %d MF positions", len(mf_positions))
            all_positions.extend(mf_positions)

    # ── Equity demat leg (NSDL / CDSL / UNKNOWN) ───────────────────────────
    if stype in {"NSDL_ECAS", "CDSL_ECAS", "UNKNOWN"}:
        diagnostics["equity_leg"]["attempted"] = True
        try:
            eq_positions = extract_nsdl_equity_demat(pdf_bytes, password)
            diagnostics["equity_leg"]["positions"] = len(eq_positions)
            logger.info("NSDL demat extractor found %d equity positions", len(eq_positions))
            all_positions.extend(eq_positions)
        except Exception as exc:
            diagnostics["equity_leg"]["error"] = str(exc)
            logger.warning("Equity demat extraction failed: %s", exc)
            # Do not hard-fail if MF positions were already found
            if not all_positions:
                return _build_error_envelope(
                    code="EXTRACTION_FAILED",
                    message=f"Could not extract holdings from this {stype} PDF.",
                    action_hint="Verify the file is a supported CAS/eCAS and the password is correct. If layout changed, report the issue.",
                    diagnostics=diagnostics,
                    investor=investor_info,
                )

    # ── Final assembly ─────────────────────────────────────────────────────
    if not all_positions:
        # Empty-but-valid: classified as CAS but zero holdings
        return _build_error_envelope(
            ok=True,
            code="EMPTY_BUT_VALID",
            severity="warning",
            message="CAS parsed successfully, but no active holdings were found in the statement.",
            action_hint="This may be a new account with no transactions yet, or a historical statement with closed positions. Upload a current statement if needed.",
            diagnostics=diagnostics,
            investor=investor_info,
            summary=cas_meta,
        )

    return {
        "ok": True,
        "code": "MIRROR_SYNCHRONIZED",
        "severity": "info",
        "message": f"Parsed {len(all_positions)} positions from {stype} statement.",
        "action_hint": "",
        "diagnostics": diagnostics,
        "investor": investor_info,
        "summary": cas_meta,
        "positions": all_positions,
        "statement_type": stype,
    }


def positions_from_ecas_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize the unified payload into flat position dicts."""
    raw_positions: list[dict[str, Any]] = payload.get("positions", [])

    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for pos in raw_positions:
        key = (pos.get("symbol", ""), pos.get("exchange", "NSE"), pos.get("kind", "equity"))
        if key not in merged:
            merged[key] = pos.copy()
        else:
            merged[key]["quantity"] = (merged[key].get("quantity") or 0) + (pos.get("quantity") or 0)
            merged[key]["market_value"] = (merged[key].get("market_value") or 0) + (pos.get("market_value") or 0)
            merged[key]["cost_basis"] = (merged[key].get("cost_basis") or 0) + (pos.get("cost_basis") or 0)
    return list(merged.values())


def _positions_from_casparser_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Walk casparser dict output and emit MF positions."""
    positions: list[dict[str, Any]] = []
    folios = payload.get("folios") or []
    for folio in folios:
        if not isinstance(folio, dict):
            continue
        schemes = folio.get("schemes") or []
        for scheme in schemes:
            if not isinstance(scheme, dict):
                continue
            valuation = scheme.get("valuation") or {}
            close_val = scheme.get("close") or 0.0
            units = scheme.get("close") or 0.0  # casparser v0.9 uses 'close' for units balance
            # Some versions use 'close_calculated' or 'balance'
            units = _first_number(scheme, "close", "close_calculated", "balance", "units")
            if units <= 0:
                continue

            name = _first_text(scheme, "scheme", "rta_code", "advisor")
            isin = _first_text(scheme, "isin", "amfi")
            amfi = _first_text(scheme, "amfi", "isin")
            nav = _first_number(valuation, "nav")
            market_value = _first_number(valuation, "value", "market_value", "current_value")
            cost = _first_number(valuation, "cost", "cost_basis", "invested_value")

            # Symbol for MF = AMFI code (unique scheme identifier)
            symbol = amfi or isin or _clean_symbol(name)
            if not symbol:
                continue

            positions.append({
                "symbol": symbol,
                "name": name,
                "isin": isin,
                "amfi": amfi,
                "exchange": "AMFI",  # Mutual funds don't trade on NSE/BSE directly
                "quantity": units,
                "market_value": market_value,
                "cost_basis": cost,
                "active": True,
                "kind": "mf",
                "avg_cost": (cost / units) if units and cost else 0.0,
                "last_price": nav,
                "as_of": valuation.get("date") or "",
            })
    return positions


def _first_text(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _first_number(row: dict[str, Any] | None, *keys: str) -> float:
    if row is None:
        return 0.0
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = re.sub(r"[^\d.\-]", "", str(value))
        if cleaned:
            try:
                return float(cleaned)
            except ValueError:
                continue
    return 0.0


def _clean_symbol(value: str) -> str:
    text = (value or "").strip().upper()
    # Remove exchange suffixes
    text = re.sub(r"\s+EQ$", "", text)
    text = re.sub(r"\s+NSE$", "", text)
    text = re.sub(r"\s+BSE$", "", text)
    # Strip common corporate suffixes that break tickers
    for suffix in (" LIMITED", " LTD.", " LTD", ",LIMITED", ", LIMITED", ", LTD.", ", LTD"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    # Remove all remaining spaces
    text = text.replace(" ", "")
    return text

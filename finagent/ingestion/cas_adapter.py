"""Adapter for casparser v0.9.0 CAS/eCAS PDFs.

Converts casparser's CASData (CAMS/KFintech) or NSDLCASData (CDSL/NSDL) output
to a unified flat PortfolioExtractionSchema with merged equity + MF positions.
"""

from __future__ import annotations

import io
import logging
from decimal import Decimal
from typing import Any

from finagent.ingestion.portfolio_schema import PortfolioExtractionSchema, PortfolioPositionSchema, PortfolioTransactionSchema

logger = logging.getLogger("finagent.ingestion.cas_adapter")


def cas_adapter(
    pdf_bytes: bytes,
    password: str = "",
) -> PortfolioExtractionSchema:
    """Parse a CAS/eCAS PDF using casparser v0.9.0 and return unified PortfolioExtractionSchema.

    Handles both CAMS/KFintech (CASData) and CDSL/NSDL (NSDLCASData).
    Merges all positions (equity + MF) into a single flat positions[] array.

    Args:
        pdf_bytes: PDF file bytes
        password: PDF password (if encrypted)

    Returns:
        PortfolioExtractionSchema with status, positions, confidence, and diagnostics
    """
    try:
        from casparser import read_cas_pdf
        from casparser.types import CASData, NSDLCASData
    except ImportError as exc:
        logger.error("casparser not installed: %s", exc)
        return PortfolioExtractionSchema(
            status="INGESTION_FAILED",
            source_type="pdf",
            positions=[],
            warnings=["casparser library not installed."],
            confidence=0.0,
            diagnostics={"code": "CASPARSER_NOT_INSTALLED", "error": str(exc)},
        )

    try:
        cas_data = read_cas_pdf(
            io.BytesIO(pdf_bytes),
            password=password or None,
            output="dict",
            sort_transactions=True,
        )
    except Exception as exc:
        logger.error("casparser read_cas_pdf failed: %s", exc)
        error_str = str(exc).lower()
        if "password" in error_str:
            return PortfolioExtractionSchema(
                status="INGESTION_FAILED",
                source_type="pdf",
                positions=[],
                warnings=["This PDF is encrypted. Enter the eCAS password and retry."],
                confidence=0.0,
                diagnostics={"code": "PASSWORD_REQUIRED", "error": str(exc)},
            )
        if "pymupdf" in error_str or "fitz" in error_str or "pdfminer does not support" in error_str:
            return PortfolioExtractionSchema(
                status="INGESTION_FAILED",
                source_type="pdf",
                positions=[],
                warnings=[
                    "CAS PDF parsing requires the 'pymupdf' package. "
                    "Install it with: pip install pymupdf>=1.24.0"
                ],
                confidence=0.0,
                diagnostics={"code": "PYMUPDF_REQUIRED", "error": str(exc)},
            )
        return PortfolioExtractionSchema(
            status="INGESTION_FAILED",
            source_type="pdf",
            positions=[],
            warnings=["Failed to parse CAS PDF with casparser."],
            confidence=0.0,
            diagnostics={"code": "CASPARSER_PARSE_ERROR", "error": str(exc)},
        )

    positions: list[PortfolioPositionSchema] = []
    transactions: list[PortfolioTransactionSchema] = []
    investor_info: dict[str, str | None] = {}
    warnings: list[str] = []
    diagnostics: dict[str, Any] = {
        "casparser_version": "0.9.0",
        "cas_type": None,
    }

    if isinstance(cas_data, CASData):
        # CAMS/KFintech CASData: has folios with schemes (MF) and equities
        logger.info("Parsed CAMS/KFintech CAS (CASData)")
        diagnostics["cas_type"] = "CAMS_KFINTECH"

        # Extract investor info (use getattr for safety across casparser versions)
        if cas_data.investor_info:
            inv = cas_data.investor_info
            investor_info = {
                "name": getattr(inv, "name", None) or None,
                "email": getattr(inv, "email", None) or None,
                "phone": getattr(inv, "phone", None) or getattr(inv, "mobile", None) or None,
                "pan": getattr(inv, "pan", None) or None,
            }

        # Process folios
        for folio_idx, folio in enumerate(cas_data.folios or []):
            folio_num = folio.folio_num or f"Folio_{folio_idx}"

            # Process MF schemes in this folio
            for scheme in folio.schemes or []:
                pos, txns = _scheme_to_position(
                    scheme=scheme,
                    folio_num=folio_num,
                    diagnostics=diagnostics,
                )
                if pos:
                    positions.append(pos)
                transactions.extend(txns)

            # Process equities in this folio (if any)
            for equity in folio.equities or []:
                pos = _equity_to_position(
                    equity=equity,
                    folio_num=folio_num,
                    diagnostics=diagnostics,
                )
                if pos:
                    positions.append(pos)

        diagnostics["folio_count"] = len(cas_data.folios or [])

    elif isinstance(cas_data, NSDLCASData):
        # CDSL/NSDL NSDLCASData: has demat accounts with equities and MF
        logger.info("Parsed CDSL/NSDL eCAS (NSDLCASData)")
        diagnostics["cas_type"] = "CDSL_NSDL"

        # Extract investor info (use getattr for safety across casparser versions)
        if cas_data.investor_info:
            inv = cas_data.investor_info
            investor_info = {
                "name": getattr(inv, "name", None) or None,
                "email": getattr(inv, "email", None) or None,
                "phone": getattr(inv, "phone", None) or getattr(inv, "mobile", None) or None,
                "pan": getattr(inv, "pan", None) or None,
            }

        # Process demat accounts
        for account in cas_data.accounts or []:
            account_id = f"{account.dp_id}_{account.client_id}" if account.dp_id and account.client_id else account.name

            # Process equities
            for equity in account.equities or []:
                pos = _nsdl_equity_to_position(
                    equity=equity,
                    account_id=account_id,
                    diagnostics=diagnostics,
                )
                if pos:
                    positions.append(pos)

            # Process MF
            for mf in account.mutual_funds or []:
                pos, txns = _nsdl_mf_to_position(
                    mf=mf,
                    account_id=account_id,
                    diagnostics=diagnostics,
                )
                if pos:
                    positions.append(pos)
                transactions.extend(txns)

        diagnostics["account_count"] = len(cas_data.accounts or [])

    else:
        logger.warning("casparser returned unexpected type: %s", type(cas_data))
        return PortfolioExtractionSchema(
            status="INGESTION_FAILED",
            source_type="pdf",
            positions=[],
            transactions=[],
            warnings=["casparser returned unexpected data structure."],
            confidence=0.0,
            diagnostics={"code": "UNEXPECTED_CASPARSER_TYPE", "type": str(type(cas_data))},
        )

    # Determine extraction status
    if not positions:
        status = "MIRROR_EMPTY"
        confidence = 0.5
    elif any(p.confidence < 0.7 for p in positions):
        status = "REVIEW_REQUIRED"
        confidence = sum(p.confidence for p in positions) / len(positions)
    else:
        status = "MIRROR_SYNCHRONIZED"
        confidence = sum(p.confidence for p in positions) / len(positions)

    logger.info(
        "casparser adapter complete: %d positions, %d transactions, status=%s, confidence=%.2f",
        len(positions),
        len(transactions),
        status,
        confidence,
    )

    return PortfolioExtractionSchema(
        status=status,
        source_type="pdf",
        broker_or_vendor="CAS",
        investor=investor_info,
        positions=positions,
        transactions=transactions,
        warnings=warnings,
        confidence=confidence,
        diagnostics=diagnostics,
    )


_BUY_TYPES = {"PURCHASE", "PURCHASE_SIP", "SWITCH_IN", "DIVIDEND_REINVESTMENT"}


def _scheme_to_position(
    scheme: Any,
    folio_num: str,
    diagnostics: dict[str, Any],
) -> tuple[PortfolioPositionSchema | None, list[PortfolioTransactionSchema]]:
    """Convert a casparser MF Scheme to PortfolioPositionSchema + transaction list."""
    if not scheme:
        return None, []

    # Determine name and symbol
    name = (scheme.scheme or "").strip()
    symbol = ""
    isin = (scheme.isin or "").strip().upper()
    amfi = (scheme.amfi or "").strip().upper()

    if not name and not isin and not amfi:
        return None, []

    quantity = float(scheme.close or scheme.open or 0)
    if quantity == 0:
        # Closed position; may still be worth tracking if there's market value
        pass

    # valuation is SchemeValuation with fields like nav, value, absolute_gains, etc.
    nav = float(scheme.valuation.nav or 0) if scheme.valuation else 0.0
    market_value = float(scheme.valuation.value or 0) if scheme.valuation else 0.0

    # Cost basis: sum of all buy transactions
    cost_basis = 0.0
    total_buy_units = 0.0
    transactions: list[PortfolioTransactionSchema] = []
    if scheme.transactions:
        for txn in scheme.transactions:
            txn_type_str = str(txn.type).strip().upper()
            if txn_type_str in _BUY_TYPES:
                cost_basis += float(txn.amount or 0)
                total_buy_units += float(txn.units or 0)
            # Capture every transaction for SIP detection / XIRR
            transactions.append(
                PortfolioTransactionSchema(
                    date=str(txn.date or ""),
                    txn_type=txn_type_str,
                    amount=float(txn.amount or 0),
                    units=float(txn.units or 0),
                    nav=float(txn.nav or 0),
                    isin=isin,
                    amfi=amfi,
                    symbol=symbol,
                    name=name,
                    scheme_type=str(scheme.type or "").strip().upper(),
                    kind="mf",
                    raw_evidence=f"folio={folio_num}",
                )
            )

    avg_cost = cost_basis / quantity if quantity > 0 else 0.0
    # Also derive from total_buy_units if CAS statement cost is inconsistent
    if avg_cost == 0.0 and total_buy_units > 0 and cost_basis > 0:
        avg_cost = cost_basis / total_buy_units

    confidence = 0.95 if isin and name else 0.85 if isin or name else 0.5

    pos = PortfolioPositionSchema(
        symbol=symbol,
        name=name,
        isin=isin,
        amfi=amfi,
        exchange="AMFI",
        kind="mf",
        quantity=quantity,
        market_value=market_value,
        cost_basis=cost_basis,
        avg_cost=avg_cost,
        last_price=nav,
        as_of=str(scheme.valuation.date) if scheme.valuation and hasattr(scheme.valuation, "date") else "",
        confidence=confidence,
        raw_evidence=f"folio={folio_num}",
    )
    return pos, transactions


def _equity_to_position(
    equity: Any,
    folio_num: str,
    diagnostics: dict[str, Any],
) -> PortfolioPositionSchema | None:
    """Convert a casparser Equity (from CAMS CASData) to PortfolioPositionSchema."""
    if not equity:
        return None

    name = (equity.name or "").strip()
    isin = (equity.isin or "").strip().upper()

    if not name and not isin:
        return None

    # CAMS doesn't typically have equity holdings (that's from CDSL/NSDL),
    # but handle it if present
    confidence = 0.9 if isin and name else 0.7

    return PortfolioPositionSchema(
        symbol="",  # Will be resolved by ISIN resolver
        name=name,
        isin=isin,
        amfi="",
        exchange="NSE",
        kind="equity",
        quantity=0.0,
        market_value=0.0,
        cost_basis=0.0,
        avg_cost=0.0,
        last_price=0.0,
        as_of="",
        confidence=confidence,
        raw_evidence=f"folio={folio_num}",
    )


def _nsdl_equity_to_position(
    equity: Any,
    account_id: str,
    diagnostics: dict[str, Any],
) -> PortfolioPositionSchema | None:
    """Convert an NSDL equity (from NSDLCASData) to PortfolioPositionSchema."""
    if not equity:
        return None

    name = (equity.name or "").strip()
    isin = (equity.isin or "").strip().upper()

    if not name and not isin:
        return None

    quantity = float(equity.num_shares or 0)
    price = float(equity.price or 0)
    market_value = float(equity.value or 0)

    # Cost basis is not typically provided in NSDL extract
    cost_basis = 0.0
    avg_cost = 0.0

    confidence = 0.95 if isin and name else 0.85 if isin or name else 0.6

    return PortfolioPositionSchema(
        symbol="",  # Will be resolved by ISIN resolver
        name=name,
        isin=isin,
        amfi="",
        exchange="NSE",
        kind="equity",
        quantity=quantity,
        market_value=market_value,
        cost_basis=cost_basis,
        avg_cost=avg_cost,
        last_price=price,
        as_of="",
        confidence=confidence,
        raw_evidence=f"account={account_id}",
    )


def _nsdl_mf_to_position(
    mf: Any,
    account_id: str,
    diagnostics: dict[str, Any],
) -> tuple[PortfolioPositionSchema | None, list[PortfolioTransactionSchema]]:
    """Convert an NSDL MF (from NSDLCASData) to PortfolioPositionSchema + transactions."""
    if not mf:
        return None, []

    name = (mf.name or "").strip()
    isin = (mf.isin or "").strip().upper()
    amfi = (mf.amfi or "").strip().upper() if hasattr(mf, "amfi") else ""

    if not name and not isin and not amfi:
        return None, []

    quantity = float(mf.balance or 0)
    nav = float(mf.nav or 0)
    market_value = float(mf.value or 0)
    cost_basis = float(mf.total_cost or 0)
    avg_cost = float(mf.avg_cost or 0) if mf.avg_cost else (cost_basis / quantity if quantity > 0 else 0)

    confidence = 0.95 if isin and name else 0.85 if isin or name else 0.6

    transactions: list[PortfolioTransactionSchema] = []
    if hasattr(mf, "transactions") and mf.transactions:
        for txn in mf.transactions:
            txn_type_str = str(txn.type).strip().upper()
            transactions.append(
                PortfolioTransactionSchema(
                    date=str(txn.date or ""),
                    txn_type=txn_type_str,
                    amount=float(txn.amount or 0),
                    units=float(txn.units or 0),
                    nav=float(txn.nav or 0),
                    isin=isin,
                    amfi=amfi,
                    symbol="",
                    name=name,
                    scheme_type="",
                    kind="mf",
                    raw_evidence=f"account={account_id}",
                )
            )

    pos = PortfolioPositionSchema(
        symbol="",  # Will be resolved by ISIN resolver
        name=name,
        isin=isin,
        amfi=amfi,
        exchange="AMFI",
        kind="mf",
        quantity=quantity,
        market_value=market_value,
        cost_basis=cost_basis,
        avg_cost=avg_cost,
        last_price=nav,
        as_of="",
        confidence=confidence,
        raw_evidence=f"account={account_id}",
    )
    return pos, transactions

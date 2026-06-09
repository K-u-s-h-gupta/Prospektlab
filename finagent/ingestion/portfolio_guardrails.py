from __future__ import annotations

import re

from finagent.ingestion.portfolio_schema import PortfolioExtractionSchema

_DOC_CONTEXT_PATTERNS = [
    r"\bholdings?\b",
    r"\bportfolio\b",
    r"\bsecurity name\b",
    r"\btrading symbol\b",
    r"\bmarket value\b",
    r"\bcurrent value\b",
    r"\binvested value\b",
    r"\bvaluation date\b",
    r"\bdemat\b",
    r"\bmutual fund\b",
    r"\bequity shares?\b",
    r"\bfolio\b",
    r"\becas\b",
    r"\bcas\b",
    r"\bnsdl\b",
    r"\bcdsl\b",
]

_DOC_HEADER_PATTERNS = [
    r"\bsymbol\b",
    r"\bisin\b",
    r"\bamfi\b",
    r"\bltp\b",
    r"\bnav\b",
    r"\bmarket value\b",
    r"\bcurrent value\b",
    r"\binvested value\b",
    r"\bsecurity\b",
    r"\bscheme\b",
]

_BROKER_PATTERNS = [
    r"\bzerodha\b",
    r"\bkite\b",
    r"\bgroww\b",
    r"\bupstox\b",
    r"\bdhan\b",
    r"\bangel(?:\s+one)?\b",
    r"\bmotilal\b",
    r"\baxis direct\b",
    r"\bicici direct\b",
    r"\b5paisa\b",
    r"\bsharekhan\b",
    r"\bgeojit\b",
    r"\bshoonya\b",
    r"\bcams\b",
    r"\bkfintech\b",
]

_NON_PORTFOLIO_PATTERNS = [
    r"\binvoice\b",
    r"\bbill to\b",
    r"\btotal amount due\b",
    r"\bgst\b",
    r"\btax invoice\b",
    r"\bpurchase order\b",
    r"\bshipping address\b",
    r"\bdelivery note\b",
    r"\battendance\b",
    r"\bmarksheet\b",
    r"\bresume\b",
    r"\bcurriculum vitae\b",
]


def _count_pattern_hits(text: str, patterns: list[str]) -> int:
    hits = 0
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            hits += 1
    return hits


def _strong_position_count(extraction: PortfolioExtractionSchema) -> int:
    return sum(
        1
        for position in extraction.positions
        if (position.symbol or position.name or position.isin or position.amfi)
        and (position.quantity > 0 or position.market_value > 0)
    )


def _identifier_position_count(extraction: PortfolioExtractionSchema) -> int:
    return sum(
        1
        for position in extraction.positions
        if position.isin
        or position.amfi
        or (position.symbol and position.symbol.isupper() and 2 <= len(position.symbol) <= 20)
    )


def enforce_document_guardrails(
    extraction: PortfolioExtractionSchema,
    markdown: str,
    *,
    filename: str,
) -> PortfolioExtractionSchema:
    if extraction.status == "INGESTION_FAILED":
        return extraction

    broker = (extraction.broker_or_vendor or "").strip().upper()
    if broker == "CAS" and extraction.positions:
        return extraction

    text = (markdown or "")[:20000]
    lower_text = text.lower()
    context_hits = _count_pattern_hits(lower_text, _DOC_CONTEXT_PATTERNS)
    header_hits = _count_pattern_hits(lower_text, _DOC_HEADER_PATTERNS)
    broker_hits = _count_pattern_hits(lower_text, _BROKER_PATTERNS)
    non_portfolio_hits = _count_pattern_hits(lower_text, _NON_PORTFOLIO_PATTERNS)
    strong_positions = _strong_position_count(extraction)
    identifier_positions = _identifier_position_count(extraction)
    portfolio_signal = context_hits + header_hits + broker_hits

    extraction.diagnostics.update(
        {
            "portfolio_guardrails": {
                "context_hits": context_hits,
                "header_hits": header_hits,
                "broker_hits": broker_hits,
                "non_portfolio_hits": non_portfolio_hits,
                "strong_positions": strong_positions,
                "identifier_positions": identifier_positions,
                "portfolio_signal": portfolio_signal,
            }
        }
    )

    looks_like_portfolio_document = portfolio_signal >= 2 and non_portfolio_hits < 2
    has_verified_holdings_rows = strong_positions > 0 and (identifier_positions > 0 or header_hits >= 2)

    if extraction.positions:
        if looks_like_portfolio_document and has_verified_holdings_rows:
            return extraction
        return PortfolioExtractionSchema(
            status="INGESTION_FAILED",
            source_type=extraction.source_type,
            broker_or_vendor=extraction.broker_or_vendor,
            investor=extraction.investor,
            positions=[],
            warnings=[
                "This file does not look like a verified holdings statement or broker export. Upload an actual eCAS, broker CSV/XLSX, or holdings screenshot."
            ],
            confidence=0.0,
            diagnostics={
                **extraction.diagnostics,
                "code": "NOT_PORTFOLIO_DOCUMENT",
                "filename": filename,
            },
        )

    if looks_like_portfolio_document:
        return extraction

    return PortfolioExtractionSchema(
        status="INGESTION_FAILED",
        source_type=extraction.source_type,
        broker_or_vendor=extraction.broker_or_vendor,
        investor=extraction.investor,
        positions=[],
        warnings=[
            "This file does not look like a holdings statement. Upload a real eCAS, broker export, or holdings screenshot."
        ],
        confidence=0.0,
        diagnostics={
            **extraction.diagnostics,
            "code": "NOT_PORTFOLIO_DOCUMENT",
            "filename": filename,
        },
    )

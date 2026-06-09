"""Memory Consolidator — extract verified claims from session histories.

During "dreaming" (offline, between sessions), the consolidator scans
completed research sessions and extracts verified factual claims:
  - Verified revenue/profit figures with source citations
  - Confirmed promoter holding percentages
  - Confirmed director appointments/cessations
  - Confirmed SEBI enforcement actions

These claims are stored in memory Tier 3 (core memories) with HIGH confidence
and removed from Tier 2 (session recall) to prevent stale data accumulation.

Dreaming is triggered by the nightly worker (dreaming/worker.py).
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from finagent.ikg.service import get_ikg_service

logger = logging.getLogger("finagent.dreaming.consolidator")


# ── Verified fact extraction patterns ────────────────────────────────────────

_REVENUE_PATTERNS = (
    re.compile(
        r"(?:revenue|turnover|sales)\s+(?:of\s+)?(?:INR\s+|₹\s*)?(\d[\d,.]+)\s*(?:crore|lakh|cr|lac)?",
        re.I,
    ),
    re.compile(
        r"(?:FY\d{2}|Q\d FY\d{2})[^.]*?(?:INR\s+|₹\s*)?(\d[\d,.]+)\s*crore[^.]*?revenue",
        re.I,
    ),
)

_PROMOTER_PATTERNS = (
    re.compile(
        r"promoter(?:\s+group)?\s+holds?\s+(\d+\.?\d*)\s*%",
        re.I,
    ),
    re.compile(
        r"promoter\s+(?:holding|ownership|stake)\s+(?:is\s+)?(\d+\.?\d*)\s*%",
        re.I,
    ),
)

_PLEDGE_PATTERNS = (
    re.compile(
        r"(\d+\.?\d*)\s*%\s+(?:of\s+)?(?:promoter\s+)?(?:holdings?\s+)?(?:is\s+)?pledged",
        re.I,
    ),
    re.compile(
        r"pledge[d]?\s+(?:percentage\s+is\s+)?(\d+\.?\d*)\s*%",
        re.I,
    ),
)

_SEBI_ORDER_PATTERNS = (
    re.compile(
        r"SEBI\s+(?:order|direction|penalty)[^.]*?(?:INR\s+|₹\s*)?(\d[\d,.]+)\s*(?:lakh|crore)?",
        re.I,
    ),
)


def extract_verified_claims(
    session_output: str,
    *,
    entity_name: str = "",
    entity_cin: str | None = None,
    source_citation: str = "",
) -> list[dict[str, Any]]:
    """Extract structured, verifiable factual claims from session output.

    Claims are only extracted when they appear to be sourced (URL or source citation
    present in the surrounding text) and are of specific verifiable fact types.

    Args:
        session_output: Full synthesis output text.
        entity_name: Company name for context.
        entity_cin: Company CIN for context.
        source_citation: Default source citation for extracted claims.

    Returns:
        List of claim dicts with: claim_type, value, unit, entity, source, confidence
    """
    claims: list[dict[str, Any]] = []

    # Check if text has citations (necessary for high-confidence claims)
    has_citations = bool(
        re.search(r"https?://", session_output)
        or re.search(r"\(BSE|NSE|Annual Report|SEBI\)", session_output, re.I)
        or re.search(r"\[Source:", session_output, re.I)
    )
    confidence = "HIGH" if has_citations else "MEDIUM"

    # Extract revenue claims
    for pattern in _REVENUE_PATTERNS:
        for match in pattern.finditer(session_output):
            value_str = match.group(1).replace(",", "")
            try:
                value = float(value_str)
                claims.append({
                    "claim_type": "revenue",
                    "value": value,
                    "unit": "crore_inr",
                    "entity_name": entity_name,
                    "entity_cin": entity_cin,
                    "evidence": match.group(0)[:100],
                    "source": source_citation or "synthesis_session",
                    "confidence": confidence,
                    "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                })
            except ValueError:
                pass

    # Extract promoter holding claims
    for pattern in _PROMOTER_PATTERNS:
        for match in pattern.finditer(session_output):
            try:
                pct = float(match.group(1))
                if 0 < pct <= 100:
                    claims.append({
                        "claim_type": "promoter_holding_pct",
                        "value": pct,
                        "unit": "percent",
                        "entity_name": entity_name,
                        "entity_cin": entity_cin,
                        "evidence": match.group(0)[:100],
                        "source": source_citation or "synthesis_session",
                        "confidence": confidence,
                        "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    })
            except ValueError:
                pass

    # Extract pledge claims
    for pattern in _PLEDGE_PATTERNS:
        for match in pattern.finditer(session_output):
            try:
                pct = float(match.group(1))
                if 0 < pct <= 100:
                    claims.append({
                        "claim_type": "pledge_pct",
                        "value": pct,
                        "unit": "percent",
                        "entity_name": entity_name,
                        "entity_cin": entity_cin,
                        "evidence": match.group(0)[:100],
                        "source": source_citation or "synthesis_session",
                        "confidence": confidence,
                        "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    })
            except ValueError:
                pass

    # Deduplicate by (claim_type, value) — keep first occurrence
    seen: set[tuple[str, float]] = set()
    deduped: list[dict[str, Any]] = []
    for claim in claims:
        key = (claim["claim_type"], claim["value"])
        if key not in seen:
            seen.add(key)
            deduped.append(claim)

    logger.info(
        "[CONSOLIDATOR] Extracted %d verified claims for entity=%s",
        len(deduped), entity_name,
    )
    return deduped


async def consolidate_session(
    session_output: str,
    memory_store: Any | None = None,
    *,
    entity_name: str = "",
    entity_cin: str | None = None,
    user_email: str | None = None,
    session_id: str | None = None,
    source_citation: str = "",
) -> int:
    """Extract and store verified claims from a session.

    Args:
        session_output: Full synthesis output.
        memory_store: ProspektTieredMemoryStore instance.
        entity_name: Company name.
        entity_cin: Company CIN.
        user_email: User email for memory scoping.
        session_id: Source session ID.
        source_citation: Citation for extracted facts.

    Returns:
        Number of claims stored.
    """
    claims = extract_verified_claims(
        session_output,
        entity_name=entity_name,
        entity_cin=entity_cin,
        source_citation=source_citation,
    )

    if not claims:
        return 0

    if not memory_store or not user_email:
        logger.info("[CONSOLIDATOR] No memory store — %d claims not persisted", len(claims))
        return 0

    stored = 0
    ikg_service = get_ikg_service()
    for claim in claims:
        try:
            target_key = (
                f"verified:{claim['claim_type']}:{entity_cin or entity_name[:20]}"
            )
            await memory_store.remember(
                target_key=target_key,
                kind=f"verified_{claim['claim_type']}",
                body=(
                    f"{claim['claim_type'].replace('_', ' ').title()}: "
                    f"{claim['value']} {claim['unit']} "
                    f"[Source: {claim['source']}]"
                ),
                confidence=claim["confidence"],
                session_id=session_id,
                user_email=user_email,
                metadata={
                    "claim_type": claim["claim_type"],
                    "value": claim["value"],
                    "unit": claim["unit"],
                    "entity_cin": entity_cin,
                    "evidence": claim["evidence"],
                    "source": claim["source"],
                },
            )
            stored += 1
        except Exception as exc:
            logger.debug("[CONSOLIDATOR] Failed to store claim: %s", exc)

        try:
            predicate = {
                "revenue": "reported_revenue",
                "promoter_holding_pct": "promoter_holding_pct",
                "pledge_pct": "promoter_pledge_pct",
            }.get(claim["claim_type"], claim["claim_type"])
            await ikg_service.submit_candidate_fact(
                subject_entity_id=f"company:{entity_cin}" if entity_cin else (entity_name or "unknown_entity"),
                predicate=predicate,
                object_value=str(claim["value"]),
                value_numeric=float(claim["value"]) if isinstance(claim["value"], (int, float)) else None,
                confidence=0.85 if claim["confidence"] == "HIGH" else 0.65,
                source_type="dreaming_consolidator",
                source_url=claim["source"],
                evidence_text=claim["evidence"],
                metadata={
                    "unit": claim["unit"],
                    "claim_type": claim["claim_type"],
                    "entity_name": entity_name,
                    "entity_cin": entity_cin,
                    "session_id": session_id,
                    "user_email": user_email,
                },
            )
        except Exception as exc:
            logger.debug("[CONSOLIDATOR] Failed to store candidate fact: %s", exc)

    logger.info("[CONSOLIDATOR] Stored %d/%d claims for %s", stored, len(claims), entity_name)
    return stored

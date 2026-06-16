"""Block Livemint as an evidence source.

Public articles may match LiveMint's editorial cadence but must never source
from livemint.com — the pipeline is grounded in official Indian financial
portals and other trusted press. This module strips Livemint URLs from any
source-shaped collection and reports a critical compliance flag when any
slipped through.

Pure functions only — no IO, no LLM.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

_LIVEMINT_HOST_RE = re.compile(r"(?:^|\.)livemint\.com$", re.I)
_LIVEMINT_BARE_RE = re.compile(r"livemint\.com", re.I)


def is_livemint_url(url: str | None) -> bool:
    if not url:
        return False
    raw = str(url).strip()
    if not raw:
        return False
    try:
        host = urlparse(raw).hostname or ""
    except Exception:
        host = ""
    if host and _LIVEMINT_HOST_RE.search(host):
        return True
    # Fallback for malformed entries that still leak the domain.
    return bool(_LIVEMINT_BARE_RE.search(raw))


def strip_livemint_sources(items: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], int]:
    """Remove every entry whose `url` resolves to livemint.com.

    Returns the cleaned list and the number of entries dropped — callers wire
    that count into the publish-gate critical reasons.
    """
    if not items:
        return [], 0
    cleaned: list[dict[str, Any]] = []
    dropped = 0
    for item in items:
        if not isinstance(item, dict):
            cleaned.append(item)
            continue
        if is_livemint_url(item.get("url") or item.get("source_url")):
            dropped += 1
            continue
        cleaned.append(item)
    return cleaned, dropped


def evidence_pack_livemint_count(evidence_pack: dict[str, Any] | None) -> int:
    """Count Livemint URLs anywhere in the evidence pack."""
    if not evidence_pack:
        return 0
    count = 0
    for bucket_name in (
        "official_document_evidence",
        "company_context",
        "research_pipeline_context",
        "trusted_supporting_sources",
        "sources_used",
    ):
        bucket = evidence_pack.get(bucket_name) or []
        if not isinstance(bucket, list):
            continue
        for item in bucket:
            if isinstance(item, dict) and is_livemint_url(item.get("url") or item.get("source_url")):
                count += 1
    return count


def sanitise_evidence_pack(evidence_pack: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Return a copy of the evidence pack with every Livemint entry removed."""
    cleaned = dict(evidence_pack or {})
    total_dropped = 0
    for bucket_name in (
        "official_document_evidence",
        "company_context",
        "research_pipeline_context",
        "trusted_supporting_sources",
        "sources_used",
    ):
        bucket = cleaned.get(bucket_name)
        if isinstance(bucket, list):
            new_bucket, dropped = strip_livemint_sources(bucket)
            cleaned[bucket_name] = new_bucket
            total_dropped += dropped
    return cleaned, total_dropped

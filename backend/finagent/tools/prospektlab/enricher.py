"""Enrichment MCP wrappers (gated upstream)."""

from __future__ import annotations

from typing import Any, Protocol


class EnrichClient(Protocol):
    async def enrich_business(self, company_ids: list[str], **kwargs: Any) -> dict: ...

    async def enrich_prospects(self, prospect_ids: list[str], **kwargs: Any) -> dict: ...

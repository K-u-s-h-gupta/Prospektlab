"""Wrap ProspektLab fetch-entities MCP (inject client at runtime)."""

from __future__ import annotations

from typing import Any, Protocol


class EntityClient(Protocol):
    async def fetch_entities(self, query: str, **kwargs: Any) -> list[dict]: ...


async def fetch_entities_stub(client: EntityClient | None, query: str) -> list[dict]:
    if client is None:
        return []
    return await client.fetch_entities(query)

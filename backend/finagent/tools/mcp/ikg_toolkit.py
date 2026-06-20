"""Typed toolkit for the IKG MCP server.

Provides every research agent with easy async access to governance, director,
pledge, enforcement, RPT, XBRL, and provenance data from the IKG graph.
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Any

from finagent.tools.mcp_config import MCP_SERVERS

logger = logging.getLogger("finagent.tools.mcp.ikg_toolkit")


class IKGToolKit:
    """Client for the IKG MCP server (port 8007)."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or MCP_SERVERS.get("ikg", {}).get("url", "http://127.0.0.1:8007/mcp")
        self._session = None

    async def _post(self, method: str, arguments: dict[str, Any]) -> dict:
        """Call an MCP tool via HTTP POST (fastmcp streamable-http transport)."""
        import httpx

        if self._session is None:
            self._session = httpx.AsyncClient(timeout=30.0)

        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": method, "arguments": arguments},
            "id": 1,
        }
        try:
            resp = await self._session.post(self.base_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                logger.warning("[IKG MCP] %s error: %s", method, data["error"])
                return {"status": "error", "error": str(data["error"])}
            result = data.get("result", {})
            # fastmcp returns content list; extract text/json
            content = result.get("content", [])
            if content and content[0].get("type") == "text":
                import json
                try:
                    return json.loads(content[0]["text"])
                except Exception:
                    return {"text": content[0]["text"], "status": "ok"}
            return result
        except Exception as exc:
            logger.warning("[IKG MCP] %s failed: %s", method, exc)
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    async def company_bundle(self, identifier: str = "", cin: str = "", ticker: str = "", depth: str = "standard") -> dict:
        return await self._post("ikg_company_bundle", {
            "identifier": identifier, "cin": cin, "ticker": ticker, "depth": depth
        })

    async def coverage(self, identifier: str = "", cin: str = "", ticker: str = "", depth: str = "standard") -> dict:
        return await self._post("ikg_coverage", {
            "identifier": identifier, "cin": cin, "ticker": ticker, "depth": depth
        })

    async def directors(self, cin: str) -> dict:
        return await self._post("ikg_get_directors", {"cin": cin})

    async def promoter_chain(self, cin: str) -> dict:
        return await self._post("ikg_get_promoter_chain", {"cin": cin})

    async def pledge_risk(self, cin: str) -> dict:
        return await self._post("ikg_get_pledge_risk", {"cin": cin})

    async def enforcement_history(self, cin: str) -> dict:
        return await self._post("ikg_get_enforcement_history", {"cin": cin})

    async def auditor_history(self, cin: str, limit: int = 8) -> dict:
        return await self._post("ikg_get_auditor_history", {"cin": cin, "limit": limit})

    async def rpt_analysis(self, cin: str, limit: int = 12) -> dict:
        return await self._post("ikg_get_rpt_analysis", {"cin": cin, "limit": limit})

    async def financials(self, identifier: str = "", cin: str = "", ticker: str = "", depth: str = "standard") -> dict:
        return await self._post("ikg_get_financials", {
            "identifier": identifier, "cin": cin, "ticker": ticker, "depth": depth
        })

    async def xbrl_facts(self, cin: str, category: str = "", limit: int = 20) -> dict:
        return await self._post("ikg_get_xbrl_facts", {"cin": cin, "category": category, "limit": limit})

    async def corporate_filings(self, cin: str, limit: int = 12) -> dict:
        return await self._post("ikg_get_corporate_filings", {"cin": cin, "limit": limit})

    async def corporate_actions(self, cin: str, limit: int = 12) -> dict:
        return await self._post("ikg_get_corporate_actions", {"cin": cin, "limit": limit})

    async def concall_transcripts(self, cin: str, limit: int = 8) -> dict:
        return await self._post("ikg_get_concall_transcripts", {"cin": cin, "limit": limit})

    async def search_document_sections(self, cin: str, query: str = "", document_type: str = "", limit: int = 10) -> dict:
        return await self._post("ikg_search_document_sections", {
            "cin": cin, "query": query, "document_type": document_type, "limit": limit
        })

    async def fact_provenance(self, subject_entity_id: str, predicate: str = "", limit: int = 20) -> dict:
        return await self._post("ikg_get_fact_provenance", {
            "subject_entity_id": subject_entity_id, "predicate": predicate, "limit": limit
        })

    async def health(self) -> dict:
        return await self._post("ikg_health", {})

    async def close(self) -> None:
        if self._session:
            await self._session.aclose()
            self._session = None


@lru_cache(maxsize=1)
def get_ikg_toolkit() -> IKGToolKit:
    return IKGToolKit()


__all__ = ["IKGToolKit", "get_ikg_toolkit"]

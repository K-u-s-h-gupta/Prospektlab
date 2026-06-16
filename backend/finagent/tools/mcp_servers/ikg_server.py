"""FastMCP server for the Indian Knowledge Graph."""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv
from fastmcp import FastMCP

from finagent.ikg.entity_resolver import get_entity_resolver
from finagent.ikg.service import get_ikg_service

load_dotenv()

logger = logging.getLogger("finagent.ikg.mcp_server")

mcp = FastMCP(
    "ProspektLab IKG",
    instructions=(
        "Indian Knowledge Graph tools for canonical entity resolution, governance, "
        "ownership, enforcement, documents, dreaming candidates, and provenance-aware grounding."
    ),
)


def _service():
    return get_ikg_service()


@mcp.tool()
async def ikg_health() -> dict[str, Any]:
    """Return IKG backend health, graph stats, and runtime health signals."""
    service = _service()
    stats = await service.graph_client.stats()
    out = {
        "status": "ok",
        "backend": os.getenv("IKG_BACKEND", "memory"),
        "graph_stats": stats,
        "database_configured": bool(service.database_url),
    }
    try:
        from finagent.ikg.pipeline.orchestrator import get_pipeline_health

        out["pipeline_health"] = get_pipeline_health(service.database_url or "")
    except Exception as exc:
        out["pipeline_health"] = {"status": "unknown", "warning": str(exc)}
    return out


@mcp.tool()
async def ikg_pipeline_status() -> dict[str, Any]:
    """Return pipeline status and scheduler health when available."""
    service = _service()
    try:
        from finagent.ikg.pipeline.orchestrator import get_pipeline_health

        return get_pipeline_health(service.database_url or "")
    except Exception as exc:
        return {"status": "unknown", "warning": str(exc)}


@mcp.tool()
async def ikg_resolve_entity(identifier: str) -> dict[str, Any]:
    """Resolve company name, ticker, ISIN, or CIN to canonical IKG identity."""
    resolver = get_entity_resolver()
    entity = resolver.resolve(identifier)
    if not entity:
        return {"status": "not_found", "identifier": identifier}
    return {
        "status": "ok",
        "identifier": identifier,
        "cin": entity.cin,
        "name": entity.name,
        "nse_symbol": entity.nse_symbol,
        "bse_scrip_code": entity.bse_scrip_code,
        "isin": entity.isin,
        "sector": entity.sector,
        "confidence": entity.confidence,
        "source": entity.source,
    }


@mcp.tool()
async def ikg_search_entities(query: str, limit: int = 5) -> dict[str, Any]:
    """Search canonical entities by approximate company name."""
    resolver = get_entity_resolver()
    matches = resolver.resolve_by_name(query, limit=limit)
    return {
        "status": "ok",
        "query": query,
        "results": [
            {
                "cin": row.cin,
                "name": row.name,
                "nse_symbol": row.nse_symbol,
                "bse_scrip_code": row.bse_scrip_code,
                "isin": row.isin,
                "sector": row.sector,
                "confidence": row.confidence,
            }
            for row in matches
        ],
    }


@mcp.tool()
async def ikg_company_bundle(
    identifier: str = "",
    cin: str = "",
    ticker: str = "",
    isin: str = "",
    depth: str = "standard",
) -> dict[str, Any]:
    """Return a provenance-aware IKG bundle for chat or analytics usage."""
    bundle = await _service().build_company_bundle(
        identifier=identifier or None,
        cin=cin or None,
        ticker=ticker or None,
        isin=isin or None,
        depth=depth,
    )
    return bundle.to_public_payload()


@mcp.tool()
async def ikg_coverage(
    identifier: str = "",
    cin: str = "",
    ticker: str = "",
    depth: str = "standard",
) -> dict[str, Any]:
    """Return only the coverage/freshness summary for an entity."""
    bundle = await _service().build_company_bundle(
        identifier=identifier or None,
        cin=cin or None,
        ticker=ticker or None,
        depth=depth,
    )
    return {
        "status": bundle.status,
        "coverage": bundle.coverage,
        "confidence": bundle.confidence,
        "as_of_date": bundle.as_of_date,
        "warnings": bundle.warnings,
        "entity": bundle.entity,
    }


@mcp.tool()
async def ikg_get_company_master(cin: str) -> dict[str, Any]:
    """Return canonical company-master information by CIN."""
    row = await _service().get_company_master(cin)
    return {"status": "ok" if row else "not_found", "data": row}


@mcp.tool()
async def ikg_get_directors(cin: str) -> dict[str, Any]:
    """Return director relationships and current governance graph edges."""
    bundle = await _service().build_company_bundle(cin=cin, depth="standard")
    return {
        "status": bundle.status,
        "entity": bundle.entity,
        "directors": bundle.governance.get("directors") or [],
        "director_history": bundle.governance.get("director_history") or [],
        "as_of_date": bundle.as_of_date,
        "source_refs": bundle.source_refs,
    }


@mcp.tool()
async def ikg_get_promoter_chain(cin: str) -> dict[str, Any]:
    """Return promoter ownership chain and pledge links."""
    service = _service()
    chain = await service.graph_client.get_promoter_chain(cin)
    return {"status": "ok", **chain}


@mcp.tool()
async def ikg_get_pledge_risk(cin: str) -> dict[str, Any]:
    """Return promoter pledge exposure summary."""
    risk = await _service().graph_client.get_pledge_risk(cin)
    return {"status": "ok", **risk}


@mcp.tool()
async def ikg_get_enforcement_history(cin: str) -> dict[str, Any]:
    """Return enforcement history linked to the company."""
    actions = await _service().graph_client.get_enforcement_actions(cin)
    return {"status": "ok", "cin": cin, "count": len(actions), "actions": actions}


@mcp.tool()
async def ikg_get_auditor_history(cin: str, limit: int = 8) -> dict[str, Any]:
    """Return auditor-history rows for a company."""
    rows = await _service().get_auditor_history(cin, limit=limit)
    return {"status": "ok", "cin": cin, "count": len(rows), "auditors": rows}


@mcp.tool()
async def ikg_get_rpt_analysis(cin: str, limit: int = 12) -> dict[str, Any]:
    """Return related-party transaction XBRL rows."""
    rows = await _service().get_related_party_transactions(cin, limit=limit)
    return {"status": "ok", "cin": cin, "count": len(rows), "related_party_transactions": rows}


@mcp.tool()
async def ikg_get_financials(
    identifier: str = "",
    cin: str = "",
    ticker: str = "",
    depth: str = "standard",
) -> dict[str, Any]:
    """Return financial coverage from IKG bundle plus raw company financials."""
    bundle = await _service().build_company_bundle(
        identifier=identifier or None,
        cin=cin or None,
        ticker=ticker or None,
        depth=depth,
    )
    return {
        "status": bundle.status,
        "entity": bundle.entity,
        "financials": bundle.financials,
        "coverage": bundle.coverage.get("financials"),
        "warnings": bundle.warnings,
        "source_refs": bundle.source_refs,
    }


@mcp.tool()
async def ikg_get_xbrl_facts(cin: str, category: str = "", limit: int = 20) -> dict[str, Any]:
    """Return normalized XBRL facts by CIN and optional category."""
    rows = await _service().get_xbrl_facts(cin, category=category or None, limit=limit)
    return {"status": "ok", "cin": cin, "category": category or None, "count": len(rows), "facts": rows}


@mcp.tool()
async def ikg_get_corporate_filings(cin: str, limit: int = 12) -> dict[str, Any]:
    """Return filing metadata stored in IKG staging/runtime tables."""
    rows = await _service().get_corporate_filings(cin, limit=limit)
    return {"status": "ok", "cin": cin, "count": len(rows), "filings": rows}


@mcp.tool()
async def ikg_get_corporate_actions(cin: str, limit: int = 12) -> dict[str, Any]:
    """Return corporate action rows stored in IKG."""
    rows = await _service().get_corporate_actions(cin, limit=limit)
    return {"status": "ok", "cin": cin, "count": len(rows), "actions": rows}


@mcp.tool()
async def ikg_get_concall_transcripts(cin: str, limit: int = 8) -> dict[str, Any]:
    """Return concall transcript metadata for a company."""
    rows = await _service().get_concall_transcripts(cin, limit=limit)
    return {"status": "ok", "cin": cin, "count": len(rows), "transcripts": rows}


@mcp.tool()
async def ikg_search_document_sections(
    cin: str,
    query: str = "",
    document_type: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Search IKG document sections for targeted evidence."""
    rows = await _service().search_document_sections(
        cin,
        query=query or None,
        document_type=document_type or None,
        limit=limit,
    )
    return {
        "status": "ok",
        "cin": cin,
        "query": query or None,
        "document_type": document_type or None,
        "count": len(rows),
        "sections": rows,
    }


@mcp.tool()
async def ikg_get_fact_provenance(
    subject_entity_id: str,
    predicate: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Return fact rows and provenance for a canonical entity."""
    rows = await _service().get_fact_provenance(
        subject_entity_id=subject_entity_id,
        predicate=predicate or None,
        limit=limit,
    )
    return {
        "status": "ok",
        "subject_entity_id": subject_entity_id,
        "predicate": predicate or None,
        "count": len(rows),
        "facts": rows,
    }


@mcp.tool()
async def ikg_list_candidate_facts(status: str = "candidate", limit: int = 25) -> dict[str, Any]:
    """List dreaming-layer candidate facts that have not been promoted."""
    rows = await _service().list_candidate_facts(status=status or None, limit=limit)
    return {"status": "ok", "candidate_status": status or None, "count": len(rows), "facts": rows}


@mcp.tool()
async def ikg_submit_candidate_fact(
    subject_entity_id: str,
    predicate: str,
    object_value: str = "",
    value_numeric: float | None = None,
    source_type: str = "manual",
    source_url: str = "",
    evidence_text: str = "",
    confidence: float = 0.5,
) -> dict[str, Any]:
    """Submit a candidate fact without promoting it to canonical IKG truth."""
    return await _service().submit_candidate_fact(
        subject_entity_id=subject_entity_id,
        predicate=predicate,
        object_value=object_value or None,
        value_numeric=value_numeric,
        confidence=confidence,
        source_type=source_type,
        source_url=source_url or None,
        evidence_text=evidence_text or None,
    )


@mcp.tool()
async def ikg_create_refresh_hint(
    entity_id: str = "",
    reason: str = "",
    priority: str = "normal",
    source_type: str = "manual",
) -> dict[str, Any]:
    """Create a refresh hint for dreaming/scheduler follow-up."""
    return await _service().create_refresh_hint(
        entity_id=entity_id or None,
        reason=reason,
        priority=priority,
        source_type=source_type,
    )


@mcp.tool()
async def ikg_list_refresh_hints(status: str = "open", limit: int = 25) -> dict[str, Any]:
    """List graph-refresh hints generated by dreaming or operators."""
    rows = await _service().list_refresh_hints(status=status or None, limit=limit)
    return {"status": "ok", "refresh_status": status or None, "count": len(rows), "hints": rows}


def start_ikg_server(host: str = "0.0.0.0", port: int = 8007) -> None:
    logger.info("Starting IKG FastMCP server on %s:%d", host, port)
    mcp.run(transport="streamable-http", host=host, port=port)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")
    start_ikg_server()

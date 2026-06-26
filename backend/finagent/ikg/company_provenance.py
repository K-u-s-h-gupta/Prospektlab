"""Company Provenance Page — every known fact about a company with its source.

This is the public, SEO-facing expression of the provenance moat: a per-company
page where each fact links to the primary source document/paragraph and carries
a confidence score. No competitor surfaces citation-grade company data.

Design:
  - `assemble_provenance(rows)` is PURE (no DB) → unit-testable.
  - `CompanyProvenance.page(cin)` fetches facts from ikg_facts + the company
    vertex, then assembles them grouped by predicate.

Raises `ProvenanceLookupError` on DB failure (vs None for "no data").
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from finagent.ikg.db import connect_postgres, get_database_url

logger = logging.getLogger("finagent.ikg.company_provenance")


class ProvenanceLookupError(Exception):
    """Raised when provenance lookup fails due to a DB/infrastructure error."""


# Human-friendly labels for predicates surfaced on the page.
_PREDICATE_LABELS = {
    "has_promoter_holding": "Promoter Holding",
    "has_pledge": "Promoter Pledge",
    "audited_by": "Auditor",
    "director_of": "Board Member",
    "has_financials": "Financials",
    "enforcement_action_against": "Regulatory Action",
    "subsidiary_of": "Subsidiary Of",
    "related_party_transaction": "Related Party Transaction",
    "has_corporate_action": "Corporate Action",
}


def _label(predicate: str) -> str:
    return _PREDICATE_LABELS.get(predicate, predicate.replace("_", " ").title())


def assemble_provenance(
    cin: str,
    company_name: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Group fact rows by predicate; each fact carries its citation.

    rows item shape (from ikg_facts):
      {predicate, object_value, value_numeric, as_of_date, event_date,
       confidence, source_table, source_url, evidence_text}
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cited = 0
    for r in rows:
        predicate = str(r.get("predicate") or "")
        if not predicate:
            continue
        value = r.get("object_value")
        if value is None and r.get("value_numeric") is not None:
            value = r.get("value_numeric")
        source_url = r.get("source_url")
        if source_url:
            cited += 1
        groups[predicate].append({
            "value": value,
            "as_of": str(r.get("as_of_date") or r.get("event_date") or "") or None,
            "confidence": float(r.get("confidence") or 1.0),
            "evidence": {
                "source_table": r.get("source_table"),
                "source_url": source_url,
                "detail": (r.get("evidence_text") or "")[:280] or None,
            },
        })

    sections = [
        {
            "predicate": predicate,
            "label": _label(predicate),
            "facts": sorted(items, key=lambda f: f.get("as_of") or "", reverse=True),
        }
        for predicate, items in sorted(groups.items())
    ]
    total = len(rows)
    return {
        "cin": cin,
        "company_name": company_name,
        "sections": sections,
        "summary": {
            "total_facts": total,
            "cited_facts": cited,
            "citation_ratio": round(cited / total, 2) if total else 0.0,
            "predicates": len(sections),
        },
    }


class CompanyProvenance:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = get_database_url(database_url)

    def _connect(self) -> Any:
        from psycopg.rows import dict_row
        return connect_postgres(self.database_url, row_factory=dict_row, connect_timeout=5)

    def page(self, cin: str, *, limit: int = 500) -> dict[str, Any] | None:
        """Build the provenance page for a company CIN.
        None if no facts exist. Raises ProvenanceLookupError on DB failure."""
        cin = (cin or "").upper().strip()
        if not cin or not self.database_url:
            return None
        entity_id = f"company:{cin}"
        try:
            with self._connect() as conn:
                # Use READ COMMITTED transaction
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(
                            "select properties->>'name' as name from ikg_vertices where vertex_id = %s",
                            (entity_id,),
                        )
                        vrow = cur.fetchone()
                        company_name = (vrow or {}).get("name") or cin

                        cur.execute(
                            """
                            select predicate, object_value, value_numeric, as_of_date, event_date,
                                   confidence, source_table, source_url, evidence_text
                            from ikg_facts
                            where subject_entity_id = %s
                            order by coalesce(as_of_date, event_date) desc nulls last
                            limit %s
                            """,
                            (entity_id, limit),
                        )
                        rows = [dict(r) for r in cur.fetchall()]
        except Exception as exc:
            raise ProvenanceLookupError(f"Provenance lookup failed for {cin}: {exc}") from exc

        if not rows:
            return None
        return assemble_provenance(cin, company_name, rows)


_provenance: CompanyProvenance | None = None


def get_company_provenance() -> CompanyProvenance:
    global _provenance
    if _provenance is None:
        _provenance = CompanyProvenance()
    return _provenance

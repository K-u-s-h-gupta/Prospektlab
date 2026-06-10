"""IKG — Indian Corporate Knowledge Graph package.

This package provides the complete data infrastructure for the Knowledge Graph:
  - graph_client.py  — PostgreSQL adjacency-list + Memgraph projection client
  - schema.py        — Node and Edge type definitions
  - entity_resolver.py — CIN/DIN/ISIN entity resolution
  - scrapers/        — Data ingestion modules for each source
  - pipeline/        — Orchestration and scheduling
"""

from finagent.ikg.schema import (
    CompanyNode,
    PersonNode,
    PromoterGroupNode,
    RegulatorActionNode,
    BankNode,
    AuditFirmNode,
    DirectorOfEdge,
    OwnsStakeInEdge,
    SubsidiaryOfEdge,
    PledgedToEdge,
    EnforcementActionEdge,
    RelatedPartyEdge,
    AuditedByEdge,
)

__all__ = [
    "CompanyNode", "PersonNode", "PromoterGroupNode",
    "RegulatorActionNode", "BankNode", "AuditFirmNode",
    "DirectorOfEdge", "OwnsStakeInEdge", "SubsidiaryOfEdge",
    "PledgedToEdge", "EnforcementActionEdge", "RelatedPartyEdge",
    "AuditedByEdge",
]

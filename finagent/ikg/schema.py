"""IKG Schema — Node and Edge type definitions for the Indian Corporate Knowledge Graph.

Node types mirror the corporate registry structure:
  Company → Person → PromoterGroup → Bank → AuditFirm → RegulatorAction

Edge types capture all significant corporate relationships with provenance:
  DIRECTOR_OF, OWNS_STAKE_IN, SUBSIDIARY_OF, PLEDGED_TO,
  ENFORCEMENT_ACTION_AGAINST, RELATED_PARTY_TRANSACTION, AUDITED_BY

All edges carry confidence_score, source_citation, source_url, updated_at
to enable fact-provenance tracking and freshness-based eviction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


# ── Base metadata for all nodes ──────────────────────────────────────────────

@dataclass
class NodeMetadata:
    source_citation: str = ""     # e.g. "MCA21 bulk download 2026-06-01"
    source_url: str = ""          # direct URL to source document
    confidence_score: float = 1.0  # 0.0 – 1.0
    created_at: str = ""
    updated_at: str = ""


# ── Node Types ────────────────────────────────────────────────────────────────

@dataclass
class CompanyNode:
    """MCA-registered company with stock market identifiers."""
    cin: str                      # Corporate Identity Number (primary key)
    name: str
    bse_scrip_code: str | None = None
    nse_symbol: str | None = None
    isin: str | None = None
    sector: str | None = None
    industry: str | None = None
    company_category: str | None = None  # "Company limited by shares" etc.
    company_class: str | None = None     # "Public" | "Private"
    company_sub_category: str | None = None
    listing_status: str | None = None    # "Listed" | "Unlisted"
    incorporation_date: date | None = None
    roc: str | None = None               # Registrar of Companies
    registered_state: str | None = None
    status: str | None = None            # "Active" | "Struck Off" etc.
    authorized_capital: float | None = None   # INR lakhs
    paidup_capital: float | None = None        # INR lakhs
    metadata: NodeMetadata = field(default_factory=NodeMetadata)

    @property
    def label(self) -> str:
        return "Company"

    @property
    def vertex_id(self) -> str:
        return f"company:{self.cin}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.vertex_id,
            "label": self.label,
            "cin": self.cin,
            "name": self.name,
            "bse_scrip_code": self.bse_scrip_code,
            "nse_symbol": self.nse_symbol,
            "isin": self.isin,
            "sector": self.sector,
            "industry": self.industry,
            "listing_status": self.listing_status,
            "status": self.status,
            "incorporation_date": str(self.incorporation_date) if self.incorporation_date else None,
        }


@dataclass
class PersonNode:
    """MCA-registered director/signatory with DIN."""
    din: str          # Director Identification Number (primary key)
    name: str
    designation: str | None = None
    nationality: str | None = None
    metadata: NodeMetadata = field(default_factory=NodeMetadata)

    @property
    def label(self) -> str:
        return "Person"

    @property
    def vertex_id(self) -> str:
        return f"person:{self.din}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.vertex_id,
            "label": self.label,
            "din": self.din,
            "name": self.name,
            "designation": self.designation,
        }


@dataclass
class PromoterGroupNode:
    """Promoter entity (individual or corporate) holding stake in a company."""
    id: str           # Composite: "{cin}:{promoter_name_slug}"
    name: str
    promoter_type: str = "individual"  # "individual" | "corporate" | "foreign"
    pan: str | None = None
    metadata: NodeMetadata = field(default_factory=NodeMetadata)

    @property
    def label(self) -> str:
        return "PromoterGroup"

    @property
    def vertex_id(self) -> str:
        return f"promoter:{self.id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.vertex_id,
            "label": self.label,
            "promoter_id": self.id,
            "name": self.name,
            "promoter_type": self.promoter_type,
        }


@dataclass
class RegulatorActionNode:
    """SEBI / IRDAI / RBI enforcement order."""
    id: str           # e.g. SEBI order number
    order_number: str
    regulator: str = "SEBI"           # "SEBI" | "RBI" | "IRDAI" | "MCA"
    violation_type: str = ""
    penalty_amount_inr: float | None = None
    order_date: date | None = None
    status: str = "active"            # "active" | "appealed" | "reversed"
    pdf_url: str | None = None
    metadata: NodeMetadata = field(default_factory=NodeMetadata)

    @property
    def label(self) -> str:
        return "RegulatorAction"

    @property
    def vertex_id(self) -> str:
        return f"regulator_action:{self.id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.vertex_id,
            "label": self.label,
            "action_id": self.id,
            "order_number": self.order_number,
            "regulator": self.regulator,
            "violation_type": self.violation_type,
            "penalty_amount_inr": self.penalty_amount_inr,
            "order_date": str(self.order_date) if self.order_date else None,
            "status": self.status,
        }


@dataclass
class BankNode:
    """Financial institution holding pledged shares."""
    id: str
    name: str
    bfi_code: str | None = None   # RBI BFI code
    metadata: NodeMetadata = field(default_factory=NodeMetadata)

    @property
    def label(self) -> str:
        return "Bank"

    @property
    def vertex_id(self) -> str:
        return f"bank:{self.id}"

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.vertex_id, "label": self.label, "name": self.name}


@dataclass
class AuditFirmNode:
    """ICAI-registered audit firm."""
    id: str
    name: str
    registration_number: str = ""  # ICAI firm registration
    metadata: NodeMetadata = field(default_factory=NodeMetadata)

    @property
    def label(self) -> str:
        return "AuditFirm"

    @property
    def vertex_id(self) -> str:
        return f"audit_firm:{self.id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.vertex_id,
            "label": self.label,
            "name": self.name,
            "registration_number": self.registration_number,
        }


# ── Edge Types ────────────────────────────────────────────────────────────────

@dataclass
class EdgeMetadata:
    confidence_score: float = 1.0
    source_citation: str = ""
    source_url: str = ""
    updated_at: str = ""


@dataclass
class DirectorOfEdge:
    """Person → Company: board membership."""
    from_din: str      # PersonNode.din
    to_cin: str        # CompanyNode.cin
    designation: str = ""
    from_date: date | None = None
    to_date: date | None = None   # None = currently serving
    metadata: EdgeMetadata = field(default_factory=EdgeMetadata)

    @property
    def label(self) -> str:
        return "DIRECTOR_OF"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "from": f"person:{self.from_din}",
            "to": f"company:{self.to_cin}",
            "designation": self.designation,
            "from_date": str(self.from_date) if self.from_date else None,
            "to_date": str(self.to_date) if self.to_date else None,
            "confidence_score": self.metadata.confidence_score,
        }


@dataclass
class OwnsStakeInEdge:
    """PromoterGroup → Company: shareholding pattern."""
    from_promoter_id: str   # PromoterGroupNode.id
    to_cin: str             # CompanyNode.cin
    percentage: float = 0.0
    pledge_pct: float = 0.0
    quarter: str = ""       # e.g. "Q4FY25"
    metadata: EdgeMetadata = field(default_factory=EdgeMetadata)

    @property
    def label(self) -> str:
        return "OWNS_STAKE_IN"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "from": f"promoter:{self.from_promoter_id}",
            "to": f"company:{self.to_cin}",
            "percentage": self.percentage,
            "pledge_pct": self.pledge_pct,
            "quarter": self.quarter,
            "confidence_score": self.metadata.confidence_score,
        }


@dataclass
class SubsidiaryOfEdge:
    """Company → Company: subsidiary relationship."""
    from_cin: str   # subsidiary CIN
    to_cin: str     # parent CIN
    stake_pct: float = 0.0
    metadata: EdgeMetadata = field(default_factory=EdgeMetadata)

    @property
    def label(self) -> str:
        return "SUBSIDIARY_OF"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "from": f"company:{self.from_cin}",
            "to": f"company:{self.to_cin}",
            "stake_pct": self.stake_pct,
        }


@dataclass
class PledgedToEdge:
    """PromoterGroup → Bank: pledge detail."""
    from_promoter_id: str
    to_bank_id: str
    amount_inr: float | None = None
    percentage_of_holding: float | None = None
    quarter: str = ""
    metadata: EdgeMetadata = field(default_factory=EdgeMetadata)

    @property
    def label(self) -> str:
        return "PLEDGED_TO"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "from": f"promoter:{self.from_promoter_id}",
            "to": f"bank:{self.to_bank_id}",
            "amount_inr": self.amount_inr,
            "percentage_of_holding": self.percentage_of_holding,
            "quarter": self.quarter,
        }


@dataclass
class EnforcementActionEdge:
    """RegulatorAction → Company/Person: enforcement target."""
    from_action_id: str
    to_vertex_id: str     # company:{cin} or person:{din}
    role_in_violation: str = ""
    metadata: EdgeMetadata = field(default_factory=EdgeMetadata)

    @property
    def label(self) -> str:
        return "ENFORCEMENT_ACTION_AGAINST"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "from": f"regulator_action:{self.from_action_id}",
            "to": self.to_vertex_id,
            "role_in_violation": self.role_in_violation,
        }


@dataclass
class RelatedPartyEdge:
    """Company → Company: related party transaction."""
    from_cin: str
    to_cin: str
    amount_inr: float | None = None
    nature: str = ""     # "loan" | "purchase" | "service" | "other"
    fy: str = ""         # e.g. "FY2025"
    metadata: EdgeMetadata = field(default_factory=EdgeMetadata)

    @property
    def label(self) -> str:
        return "RELATED_PARTY_TRANSACTION"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "from": f"company:{self.from_cin}",
            "to": f"company:{self.to_cin}",
            "amount_inr": self.amount_inr,
            "nature": self.nature,
            "fy": self.fy,
        }


@dataclass
class AuditedByEdge:
    """Company → AuditFirm: audit engagement."""
    from_cin: str
    to_audit_firm_id: str
    from_fy: str = ""
    to_fy: str = ""       # Empty = current auditor
    metadata: EdgeMetadata = field(default_factory=EdgeMetadata)

    @property
    def label(self) -> str:
        return "AUDITED_BY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "from": f"company:{self.from_cin}",
            "to": f"audit_firm:{self.to_audit_firm_id}",
            "from_fy": self.from_fy,
            "to_fy": self.to_fy,
        }

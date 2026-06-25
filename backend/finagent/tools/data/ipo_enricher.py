"""IPO filing enrichment: infer sector, status, and dates from available metadata.

This module does NOT make network requests; it works purely from data already
present in the filing record (company_name, doc_type, filing_date, etc.) to
produce reasonable values for fields that the SEBI scraper cannot populate
directly (sector, listing_date, subscription_open/close).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Sector keyword mapping  (first match wins; order matters)
# ---------------------------------------------------------------------------
_SECTOR_MAP: list[tuple[tuple[str, ...], str]] = [
    (("jio",), "Telecom"),
    (("telecom", "communication"), "Telecom"),
    (("bank", "banking"), "Banking"),
    (("finance", "financial", "fintech", "loan", "credit", "microfinance", "nbfc", "mfi"), "Financial Services"),
    (("insurance",), "Insurance"),
    (("pharma", "pharmaceutical", "drug", "medicine", "life science"), "Pharmaceuticals"),
    (("parenteral", "biotech", "biosimilar", "clinical"), "Pharmaceuticals"),
    (("healthcare", "hospital", "health service", "diagnostic", "nephro"), "Healthcare"),
    (("medical", "medico"), "Healthcare"),
    (("software", "saas", "platform", "digital", "ai ", " ai", "analytics", "data"), "Technology"),
    (("tech ", " tech", "solutions", "systems", "infosys", "infotech"), "Technology"),
    (("media", "entertainment", "broadcast", "amagi"), "Media & Entertainment"),
    (("power", "energy", "solar", "electric", "transmission", "wind"), "Energy"),
    (("coal", "coking", "mine", "mineral"), "Mining"),
    (("infra", "infrastructure", "construction", "cement", "road"), "Infrastructure"),
    (("real estate", "realty", "housing", "property"), "Real Estate"),
    (("textile", "fabric", "yarn", "twistex", "spintex"), "Textiles"),
    (("jewel", "diamond", "gold", "silver", "ornament"), "Jewellery"),
    (("food", "nutrition", "beverage", "dairy", "agro", "punjabi",), "Food & Beverages"),
    (("agri", "crop", "fertiliser", "pesticide", "seed"), "Agriculture"),
    (("packaging", "pack"), "Packaging"),
    (("logistics", "courier", "transport", "freight", "shadowfax", "wakefit"), "Logistics & Consumer"),
    (("tourism", "leisure", "hotel", "hospitality", "waterway"), "Travel & Tourism"),
    (("chemical", "chem"), "Chemicals"),
    (("steel", "stainless", "metal", "iron", "alloy", "casting"), "Metals"),
    (("mechatronic", "engineering", "component", "electronic", "semiconductor"), "Manufacturing"),
    (("exchange", "nse", "bse", "stock market"), "Capital Markets"),
    (("brand", "consumer", "retail", "e-commerce", "meesho"), "Consumer & E-Commerce"),
    (("export",), "Exports & Trade"),
]

# How many days after an RHP filing before we assume the IPO has listed
# (3 days subscription + 2 days allotment + 7 days listing window = 12 days minimum)
_RHP_LIVE_CUTOFF_DAYS = 12

# How many days back to show in "recently listed" bucket
RECENTLY_LISTED_DAYS = 60


def _infer_sector(company_name: str) -> str | None:
    lower = (company_name or "").lower()
    for keywords, sector in _SECTOR_MAP:
        if any(kw in lower for kw in keywords):
            return sector
    return "Other"


def _infer_status(
    doc_type: str,
    filing_date_str: str | None,
    prospectus_date_str: str | None,
    current_status: str | None,
) -> str:
    """Determine the correct bucket status from document type and filing age."""
    # Respect manually-set live/listed statuses unless the data clearly contradicts them
    if doc_type == "prospectus":
        return "listed"
    if doc_type == "drhp":
        return "upcoming"
    if doc_type == "rhp":
        # If there's a prospectus date, the IPO has listed
        if prospectus_date_str:
            return "listed"
        if filing_date_str:
            try:
                filing = date.fromisoformat(filing_date_str)
                days_old = (date.today() - filing).days
                if days_old <= _RHP_LIVE_CUTOFF_DAYS:
                    return "live"
                else:
                    # IPO has definitely listed by now
                    return "listed"
            except ValueError:
                pass
        return "live"
    return current_status or "upcoming"


def _estimate_listing_date(
    doc_type: str,
    filing_date_str: str | None,
    prospectus_date_str: str | None,
) -> str | None:
    """Estimate listing date from prospectus filing date or RHP + buffer."""
    # Prospectus is filed around listing date — use it directly
    if prospectus_date_str:
        return prospectus_date_str
    # RHP → estimate listing as filing + 15 days (3 sub + 5 allotment + 7 listing window)
    if doc_type == "rhp" and filing_date_str:
        try:
            f = date.fromisoformat(filing_date_str)
            return (f + timedelta(days=15)).isoformat()
        except ValueError:
            pass
    return None


def _estimate_subscription_dates(
    doc_type: str,
    rhp_filing_date: str | None,
) -> tuple[str | None, str | None]:
    """Estimate subscription open/close from RHP filing date."""
    if doc_type == "rhp" and rhp_filing_date:
        try:
            f = date.fromisoformat(rhp_filing_date)
            # IPO typically opens 2-4 days after RHP filing
            open_date = f + timedelta(days=2)
            close_date = open_date + timedelta(days=3)  # 3-day subscription window
            return open_date.isoformat(), close_date.isoformat()
        except ValueError:
            pass
    return None, None


def enrich_filing(payload: dict[str, Any]) -> dict[str, Any]:
    """Return an enriched copy of a filing payload with inferred fields filled in."""
    enriched = dict(payload)

    company_name = payload.get("company_name", "")
    doc_type = str(payload.get("doc_type") or "drhp").lower()
    filing_date = payload.get("filing_date")
    prospectus_date = payload.get("prospectus_filing_date")
    current_status = payload.get("status")

    # RHP filing date
    rhp_date = payload.get("rhp_filing_date") or (filing_date if doc_type == "rhp" else None)
    if doc_type == "rhp" and not enriched.get("rhp_filing_date"):
        enriched["rhp_filing_date"] = filing_date

    # Sector
    if not enriched.get("sector"):
        enriched["sector"] = _infer_sector(company_name)

    # Status
    if doc_type in ("rhp", "drhp", "prospectus"):
        enriched["status"] = _infer_status(doc_type, filing_date, prospectus_date, current_status)
    elif not current_status:
        enriched["status"] = "upcoming"

    inferred_status = enriched.get("status", "upcoming")

    # Listing date
    if inferred_status == "listed" and not enriched.get("listing_date"):
        enriched["listing_date"] = _estimate_listing_date(doc_type, filing_date, prospectus_date)

    # Subscription dates
    if inferred_status == "live" and not enriched.get("subscription_open"):
        sub_open, sub_close = _estimate_subscription_dates(doc_type, rhp_date)
        if sub_open:
            enriched["subscription_open"] = sub_open
        if sub_close:
            enriched["subscription_close"] = sub_close

    # Recompute issue_size_cr from fresh + OFS when both are known
    fresh = enriched.get("fresh_issue_cr")
    ofs = enriched.get("ofs_cr")
    if fresh and ofs:
        computed_total = round(fresh + ofs, 2)
        current_total = enriched.get("issue_size_cr") or 0
        # Use the larger / more complete value
        if computed_total > current_total:
            enriched["issue_size_cr"] = computed_total
    elif fresh and not enriched.get("issue_size_cr"):
        enriched["issue_size_cr"] = fresh
    elif ofs and not enriched.get("issue_size_cr"):
        enriched["issue_size_cr"] = ofs

    return enriched


def is_recently_listed(filing: dict[str, Any], *, days: int = RECENTLY_LISTED_DAYS) -> bool:
    """Return True if the filing's listing date falls within the recency window."""
    listing_date_str = filing.get("listing_date") or filing.get("prospectus_filing_date")
    if not listing_date_str:
        return True  # Include if we can't determine the date (safer default)
    try:
        listing = date.fromisoformat(listing_date_str[:10])
        return (date.today() - listing).days <= days
    except ValueError:
        return True

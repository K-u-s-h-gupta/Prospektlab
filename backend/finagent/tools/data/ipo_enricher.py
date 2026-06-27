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
    subscription_open_str: str | None = None,
    subscription_close_str: str | None = None,
    listing_date_str: str | None = None,
) -> str:
    """Determine the correct bucket status from dates and document type.

    Live means currently open for subscription. Closed-but-not-listed issues
    are marked as ``closed`` so the live tab cannot show stale subscriptions.
    """
    today = date.today()
    current = (current_status or "").strip().lower()

    listing: date | None = None
    if listing_date_str:
        try:
            listing = date.fromisoformat(listing_date_str[:10])
            if listing <= today:
                return "listed"
        except ValueError:
            pass

    if subscription_open_str and subscription_close_str:
        try:
            sub_open = date.fromisoformat(subscription_open_str[:10])
            sub_close = date.fromisoformat(subscription_close_str[:10])
            if sub_open <= today <= sub_close:
                return "live"
            if today > sub_close:
                return "closed"
            if today < sub_open:
                return "upcoming"
        except ValueError:
            pass
    elif subscription_open_str:
        try:
            sub_open = date.fromisoformat(subscription_open_str[:10])
            if sub_open <= today and current == "live":
                return "live"
            return "upcoming"
        except ValueError:
            pass

    if doc_type == "prospectus" or prospectus_date_str:
        return "listed"

    if current in {"live", "listed", "closed", "upcoming"}:
        return "upcoming" if current == "live" else current

    if doc_type in {"drhp", "rhp"}:
        return "upcoming"
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
    subscription_open = payload.get("subscription_open")
    subscription_close = payload.get("subscription_close")
    listing_date = payload.get("listing_date")

    # RHP filing date
    rhp_date = payload.get("rhp_filing_date") or (filing_date if doc_type == "rhp" else None)
    if doc_type == "rhp" and not enriched.get("rhp_filing_date"):
        enriched["rhp_filing_date"] = filing_date

    # Sector
    if not enriched.get("sector"):
        enriched["sector"] = _infer_sector(company_name)

    # Status - use subscription dates for accurate live detection
    enriched["status"] = _infer_status(
        doc_type, filing_date, prospectus_date, current_status,
        subscription_open, subscription_close, listing_date
    )

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

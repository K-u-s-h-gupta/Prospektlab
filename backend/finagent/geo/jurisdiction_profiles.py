from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JurisdictionProfile:
    country_code: str
    country_name: str
    primary_currency: str
    exchanges: tuple[str, ...] = ()
    regulator: str | None = None
    preferred_domains: tuple[str, ...] = ()
    filing_terms: tuple[str, ...] = ()
    news_hl: str = "en-IN"
    news_gl: str = "IN"
    news_ceid: str = "IN:en"
    search_suffix_terms: tuple[str, ...] = ()
    yahoo_suffixes: tuple[str, ...] = ()
    governance_terms: tuple[str, ...] = ()


_INDIA_PROFILE = JurisdictionProfile(
    country_code="IN",
    country_name="India",
    primary_currency="INR",
    exchanges=("NSE", "BSE"),
    regulator="SEBI",
    preferred_domains=(
        "nseindia.com",
        "bseindia.com",
        "sebi.gov.in",
        "moneycontrol.com",
        "screener.in",
        "trendlyne.com",
        "tickertape.in",
        "economictimes.indiatimes.com",
        "livemint.com",
        "business-standard.com",
    ),
    filing_terms=(
        "SEBI LODR Regulation 30 corporate announcement",
        "SEBI LODR Regulation 33 financial results",
        "Regulation 31 shareholding pattern",
        "annual report",
        "concall transcript",
    ),
    search_suffix_terms=("India", "NSE", "BSE", "SEBI LODR"),
    yahoo_suffixes=(".NS", ".BO"),
    governance_terms=("insider trading disclosure", "board meeting outcome", "corporate governance"),
)

_PROFILES: dict[str, JurisdictionProfile] = {
    "IN": _INDIA_PROFILE,
    "GLOBAL": _INDIA_PROFILE,
}


def get_jurisdiction_profile(country_code: str | None) -> JurisdictionProfile:
    return _PROFILES.get((country_code or "IN").upper(), _INDIA_PROFILE)

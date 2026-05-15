from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class JurisdictionProfile:
    country_code: str
    country_name: str
    primary_currency: str
    exchanges: tuple[str, ...] = ()
    regulator: str | None = None
    preferred_domains: tuple[str, ...] = ()
    filing_terms: tuple[str, ...] = ()
    news_hl: str = "en-US"
    news_gl: str = "US"
    news_ceid: str = "US:en"
    search_suffix_terms: tuple[str, ...] = ()
    yahoo_suffixes: tuple[str, ...] = ()
    governance_terms: tuple[str, ...] = ()


_PROFILES: dict[str, JurisdictionProfile] = {
    "US": JurisdictionProfile(
        country_code="US",
        country_name="United States",
        primary_currency="USD",
        exchanges=("NASDAQ", "NYSE"),
        regulator="SEC",
        preferred_domains=("sec.gov", "investor.gov", "reuters.com", "finance.yahoo.com"),
        filing_terms=("10-K", "10-Q", "8-K", "DEF 14A"),
        news_hl="en-US",
        news_gl="US",
        news_ceid="US:en",
        search_suffix_terms=("United States", "NASDAQ", "NYSE"),
        governance_terms=("Form 4", "DEF 14A", "proxy"),
    ),
    "IN": JurisdictionProfile(
        country_code="IN",
        country_name="India",
        primary_currency="INR",
        exchanges=("NSE", "BSE"),
        regulator="SEBI",
        preferred_domains=("nseindia.com", "bseindia.com", "sebi.gov.in", "moneycontrol.com"),
        filing_terms=("annual report", "quarterly results", "concall transcript", "shareholding pattern"),
        news_hl="en-IN",
        news_gl="IN",
        news_ceid="IN:en",
        search_suffix_terms=("India", "NSE", "BSE", "SEBI"),
        yahoo_suffixes=(".NS", ".BO"),
        governance_terms=("insider trading disclosure", "board meeting outcome", "corporate governance"),
    ),
    "JP": JurisdictionProfile(
        country_code="JP",
        country_name="Japan",
        primary_currency="JPY",
        exchanges=("TSE",),
        regulator="FSA Japan",
        preferred_domains=("jpx.co.jp", "fsa.go.jp", "nikkei.com"),
        filing_terms=("annual report", "earnings presentation", "investor relations"),
        news_hl="en-US",
        news_gl="JP",
        news_ceid="JP:en",
        search_suffix_terms=("Japan", "Tokyo Stock Exchange"),
        governance_terms=("board changes", "annual report", "governance report"),
    ),
    "EU": JurisdictionProfile(
        country_code="EU",
        country_name="Europe",
        primary_currency="EUR",
        exchanges=("XETRA", "EURONEXT", "LSE"),
        regulator="European regulators",
        preferred_domains=("euronext.com", "londonstockexchange.com", "reuters.com"),
        filing_terms=("annual report", "results presentation", "investor relations"),
        news_hl="en-GB",
        news_gl="GB",
        news_ceid="GB:en",
        search_suffix_terms=("Europe", "investor relations"),
        governance_terms=("annual report", "governance report", "board changes"),
    ),
    "GLOBAL": JurisdictionProfile(
        country_code="GLOBAL",
        country_name="Global",
        primary_currency="USD",
        exchanges=(),
        regulator=None,
        preferred_domains=("reuters.com", "finance.yahoo.com"),
        filing_terms=("annual report", "investor relations", "earnings transcript"),
        news_hl="en-US",
        news_gl="US",
        news_ceid="US:en",
        search_suffix_terms=("investor relations", "annual report"),
        governance_terms=("board changes", "executive compensation", "insider activity"),
    ),
}


def get_jurisdiction_profile(country_code: str | None) -> JurisdictionProfile:
    if not country_code:
        return _PROFILES["GLOBAL"]
    return _PROFILES.get(country_code.upper(), _PROFILES["GLOBAL"])

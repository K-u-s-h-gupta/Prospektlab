"""SEC EDGAR integration stub."""

EDGAR_BROWSE = "https://www.sec.gov/cgi-bin/browse-edgar"


def company_filings_url(cik: str) -> str:
    return f"{EDGAR_BROWSE}?action=getcompany&CIK={cik}&type=&dateb=&owner=include&count=40"

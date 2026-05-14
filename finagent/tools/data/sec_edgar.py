"""SEC EDGAR JSON API client.

The SEC publishes a documented Fair-Access policy
(https://www.sec.gov/os/accessing-edgar-data) which permits programmatic access
to data.sec.gov endpoints as long as requests carry an identification
User-Agent. Our `http_fetcher` already attaches that UA for sec.gov, so we just
hit the endpoints directly and parse JSON.

Endpoints used:
- https://www.sec.gov/files/company_tickers.json
    Mapping {seq: {cik_str, ticker, title}} for every SEC-registered company.
- https://data.sec.gov/submissions/CIK{padded}.json
    Filing history (form types, accession numbers, filing dates).
- https://data.sec.gov/api/xbrl/companyfacts/CIK{padded}.json
    Every XBRL fact the company has ever reported, keyed by us-gaap / dei
    concept name.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from finagent.tools.web.http_fetcher import fetch

logger = logging.getLogger("finagent.sec_edgar")

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# In-process ticker map cache. Built lazily on first lookup.
_ticker_index: dict[str, dict[str, Any]] = {}
_ticker_lock = asyncio.Lock()


@dataclass
class SECMetric:
    concept: str  # us-gaap concept name
    label: str  # human label
    unit: str  # e.g. USD, USD/shares, shares, pure
    value: float
    end: str  # period-end date
    fy: int | None
    fp: str | None  # FY / Q1 / Q2 ...
    form: str  # 10-K / 10-Q / ...
    accn: str  # accession number
    filed: str | None = None

    def display_value(self) -> str:
        if self.unit == "USD":
            return _format_usd(self.value)
        if self.unit == "USD/shares":
            return f"${self.value:,.2f}"
        if self.unit == "shares":
            return f"{int(self.value):,} shares"
        return f"{self.value:,.2f} {self.unit}"


@dataclass
class SECFiling:
    form: str
    accession: str
    filing_date: str
    report_date: str
    primary_doc: str
    url: str


@dataclass
class SECSeriesPoint:
    end: str
    value: float
    fy: int | None
    fp: str | None
    form: str


@dataclass
class SECTimeSeries:
    concept: str
    label: str
    unit: str
    annual: list[SECSeriesPoint] = field(default_factory=list)
    quarterly: list[SECSeriesPoint] = field(default_factory=list)


@dataclass
class SECCompanySnapshot:
    cik: str  # zero-padded 10-digit string
    ticker: str
    name: str
    metrics: dict[str, SECMetric] = field(default_factory=dict)
    history: dict[str, SECTimeSeries] = field(default_factory=dict)
    recent_filings: list[SECFiling] = field(default_factory=list)
    sic_description: str | None = None
    exchanges: list[str] = field(default_factory=list)


def _format_usd(value: float) -> str:
    av = abs(value)
    if av >= 1e12:
        return f"${value/1e12:,.2f}T"
    if av >= 1e9:
        return f"${value/1e9:,.2f}B"
    if av >= 1e6:
        return f"${value/1e6:,.1f}M"
    if av >= 1e3:
        return f"${value/1e3:,.1f}K"
    return f"${value:,.0f}"


async def _load_ticker_index() -> dict[str, dict[str, Any]]:
    if _ticker_index:
        return _ticker_index
    async with _ticker_lock:
        if _ticker_index:
            return _ticker_index
        res = await fetch(_TICKERS_URL, respect_robots=False, timeout_s=20)
        if res.status != 200 or not res.text:
            logger.warning("ticker index fetch failed (status=%s)", res.status)
            return {}
        try:
            data = json.loads(res.text)
        except Exception as exc:
            logger.warning("ticker index parse failed: %s", exc)
            return {}
        for entry in data.values():
            if not isinstance(entry, dict):
                continue
            ticker = str(entry.get("ticker") or "").upper().strip()
            title = str(entry.get("title") or "").strip()
            cik = entry.get("cik_str")
            if not (ticker and title and cik):
                continue
            normalized = {
                "cik": f"{int(cik):010d}",
                "ticker": ticker,
                "name": title,
            }
            _ticker_index[ticker] = normalized
            _ticker_index[title.lower()] = normalized
            # Also index a "core" form (drop common suffixes) for fuzzy matches.
            core = (
                title.lower()
                .removesuffix(" inc.")
                .removesuffix(" inc")
                .removesuffix(" corp.")
                .removesuffix(" corp")
                .removesuffix(" corporation")
                .removesuffix(" company")
                .removesuffix(" plc")
                .removesuffix(" ltd")
                .removesuffix(" ltd.")
                .strip()
            )
            if core and core not in _ticker_index:
                _ticker_index[core] = normalized
    return _ticker_index


async def resolve_ticker_or_name(query: str) -> dict[str, str] | None:
    """Resolve `query` to {cik, ticker, name}, or None if not found."""
    index = await _load_ticker_index()
    if not index:
        return None
    q = query.strip()
    q_upper = q.upper()
    q_lower = q.lower()
    hit = index.get(q_upper) or index.get(q_lower)
    if hit:
        return hit
    # Try a starts-with fuzzy match on names (longest match wins).
    candidates = [v for k, v in index.items() if k.startswith(q_lower) and len(k) > 2]
    if candidates:
        candidates.sort(key=lambda v: len(v["name"]))
        return candidates[0]
    return None


_METRIC_ALIASES: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
    ],
    "operating_income": [
        "OperatingIncomeLoss",
    ],
    "total_assets": [
        "Assets",
    ],
    "total_liabilities": [
        "Liabilities",
    ],
    "stockholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "eps_diluted": [
        "EarningsPerShareDiluted",
    ],
    "eps_basic": [
        "EarningsPerShareBasic",
    ],
    "shares_outstanding": [
        "CommonStockSharesOutstanding",
        "EntityCommonStockSharesOutstanding",
    ],
    "rd_expense": [
        "ResearchAndDevelopmentExpense",
    ],
    "long_term_debt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
    ],
}


def _history_series(
    facts_root: dict[str, Any],
    concept_aliases: list[str],
    preferred_units: tuple[str, ...] = ("USD", "USD/shares", "shares", "pure"),
    *,
    max_annual: int = 8,
    max_quarterly: int = 12,
) -> SECTimeSeries | None:
    """Pull a multi-year annual + quarterly time series for the concept.

    Same alias resolution as _latest_fact, but instead of returning the
    single latest point, returns the most recent N annual (10-K) and
    quarterly (10-Q) points, deduplicated by end-date.
    """
    us_gaap = facts_root.get("facts", {}).get("us-gaap", {})
    dei = facts_root.get("facts", {}).get("dei", {})
    for alias in concept_aliases:
        node = us_gaap.get(alias) or dei.get(alias)
        if not node:
            continue
        label = node.get("label") or alias
        units = node.get("units", {})
        for unit in preferred_units:
            entries = units.get(unit)
            if not entries:
                continue
            # Annual = 10-K rows, Quarterly = 10-Q rows
            annual_raw = [e for e in entries if e.get("form") == "10-K"]
            quarterly_raw = [e for e in entries if e.get("form") == "10-Q"]
            annual_raw.sort(key=lambda e: e.get("end") or "", reverse=True)
            quarterly_raw.sort(key=lambda e: e.get("end") or "", reverse=True)

            def _dedup(rows: list[dict[str, Any]], n: int) -> list[SECSeriesPoint]:
                seen: set[str] = set()
                out: list[SECSeriesPoint] = []
                for e in rows:
                    end = e.get("end") or ""
                    if end in seen:
                        continue
                    seen.add(end)
                    out.append(
                        SECSeriesPoint(
                            end=end,
                            value=float(e.get("val") or 0),
                            fy=e.get("fy"),
                            fp=e.get("fp"),
                            form=e.get("form", ""),
                        )
                    )
                    if len(out) >= n:
                        break
                return out

            annual = _dedup(annual_raw, max_annual)
            quarterly = _dedup(quarterly_raw, max_quarterly)
            if not annual and not quarterly:
                continue
            # SEC reports annual revenue cumulatively in 10-K — series is
            # already annualised because we pull only form=10-K rows.
            annual.reverse()  # oldest first for plotting
            quarterly.reverse()
            return SECTimeSeries(
                concept=alias,
                label=label,
                unit=unit,
                annual=annual,
                quarterly=quarterly,
            )
    return None


_HISTORY_KEYS = ("revenue", "net_income", "operating_income", "eps_diluted", "rd_expense")


def _latest_fact(
    facts_root: dict[str, Any],
    concept_aliases: list[str],
    preferred_units: tuple[str, ...] = ("USD", "USD/shares", "shares", "pure"),
) -> SECMetric | None:
    """Find the latest annual / quarterly value across `concept_aliases`.

    We prefer 10-K (FY) values; if none exist, fall back to the most-recent
    10-Q. Returns None if the concept is missing entirely.
    """
    us_gaap = facts_root.get("facts", {}).get("us-gaap", {})
    dei = facts_root.get("facts", {}).get("dei", {})
    best: SECMetric | None = None
    for alias in concept_aliases:
        node = us_gaap.get(alias) or dei.get(alias)
        if not node:
            continue
        label = node.get("label") or alias
        units = node.get("units", {})
        for unit in preferred_units:
            entries = units.get(unit)
            if not entries:
                continue
            # Sort descending by end-date; prefer 10-K (form=10-K) at the same date.
            entries_sorted = sorted(
                entries,
                key=lambda e: (e.get("end") or "", 1 if e.get("form") == "10-K" else 0),
                reverse=True,
            )
            top = entries_sorted[0]
            metric = SECMetric(
                concept=alias,
                label=label,
                unit=unit,
                value=float(top.get("val")),
                end=top.get("end", ""),
                fy=top.get("fy"),
                fp=top.get("fp"),
                form=top.get("form", ""),
                accn=top.get("accn", ""),
                filed=top.get("filed"),
            )
            if best is None or (metric.end or "") > (best.end or ""):
                best = metric
            break  # only first matching unit per alias
    return best


def _parse_submissions(payload: dict[str, Any]) -> tuple[list[SECFiling], str | None, list[str]]:
    filings: list[SECFiling] = []
    sic_description = payload.get("sicDescription")
    exchanges = list(payload.get("exchanges") or [])
    recent = payload.get("filings", {}).get("recent", {}) or {}
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accns = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    report_dates = recent.get("reportDate", [])
    cik = str(int(payload.get("cik", "0"))) if payload.get("cik") is not None else ""
    keep_forms = {"10-K", "10-Q", "8-K", "20-F", "S-1", "DEF 14A", "10-K/A", "10-Q/A"}
    # Two-pass: always reserve a slot for the most-recent 10-K and 10-Q so the
    # narrative extractor has filings with Item 1A / Item 7. Then fill the rest
    # chronologically up to 12 total.
    reserved_targets = ["10-K", "10-Q", "20-F"]
    reserved_taken: set[str] = set()
    candidates: list[SECFiling] = []

    def _row_url(i: int, form: str) -> tuple[str, str, str]:
        accn = accns[i] if i < len(accns) else ""
        accn_clean = accn.replace("-", "")
        primary = primary_docs[i] if i < len(primary_docs) else ""
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn_clean}/{primary}"
            if cik and accn_clean and primary
            else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=10"
        )
        return accn, primary, url

    # Pass 1: pin most recent 10-K / 10-Q / 20-F
    for i in range(len(forms)):
        form = forms[i]
        if form in reserved_targets and form not in reserved_taken:
            accn, primary, url = _row_url(i, form)
            candidates.append(
                SECFiling(
                    form=form,
                    accession=accn,
                    filing_date=dates[i] if i < len(dates) else "",
                    report_date=report_dates[i] if i < len(report_dates) else "",
                    primary_doc=primary,
                    url=url,
                )
            )
            reserved_taken.add(form)

    # Pass 2: fill chronologically with anything in keep_forms (no dupes by accession)
    seen_accn = {c.accession for c in candidates}
    for i in range(min(len(forms), 40)):
        form = forms[i]
        if form not in keep_forms:
            continue
        accn, primary, url = _row_url(i, form)
        if accn in seen_accn:
            continue
        candidates.append(
            SECFiling(
                form=form,
                accession=accn,
                filing_date=dates[i] if i < len(dates) else "",
                report_date=report_dates[i] if i < len(report_dates) else "",
                primary_doc=primary,
                url=url,
            )
        )
        seen_accn.add(accn)
        if len(candidates) >= 12:
            break

    # Sort by filing_date descending so the UI shows most recent on top,
    # but the reserved 10-K stays available via .recent_filings list.
    candidates.sort(key=lambda f: f.filing_date or "", reverse=True)
    return candidates, sic_description, exchanges


async def fetch_company_snapshot(query: str, *, timeout_s: float = 20.0) -> SECCompanySnapshot | None:
    """Resolve `query` then fetch submissions + companyfacts JSON in parallel."""
    resolved = await resolve_ticker_or_name(query)
    if not resolved:
        return None
    cik = resolved["cik"]
    sub_task = asyncio.create_task(
        fetch(_SUBMISSIONS_URL.format(cik=cik), respect_robots=False, timeout_s=timeout_s)
    )
    facts_task = asyncio.create_task(
        fetch(_COMPANY_FACTS_URL.format(cik=cik), respect_robots=False, timeout_s=timeout_s)
    )
    sub_res, facts_res = await asyncio.gather(sub_task, facts_task)

    filings: list[SECFiling] = []
    sic_description: str | None = None
    exchanges: list[str] = []
    if sub_res.status == 200 and sub_res.text:
        try:
            sub_payload = json.loads(sub_res.text)
            filings, sic_description, exchanges = _parse_submissions(sub_payload)
        except Exception as exc:
            logger.warning("submissions parse failed: %s", exc)

    metrics: dict[str, SECMetric] = {}
    history: dict[str, SECTimeSeries] = {}
    if facts_res.status == 200 and facts_res.text:
        try:
            facts_payload = json.loads(facts_res.text)
            for key, aliases in _METRIC_ALIASES.items():
                m = _latest_fact(facts_payload, aliases)
                if m is not None:
                    metrics[key] = m
            for key in _HISTORY_KEYS:
                aliases = _METRIC_ALIASES.get(key) or []
                if not aliases:
                    continue
                series = _history_series(facts_payload, aliases)
                if series is not None:
                    history[key] = series
        except Exception as exc:
            logger.warning("companyfacts parse failed: %s", exc)

    return SECCompanySnapshot(
        cik=cik,
        ticker=resolved["ticker"],
        name=resolved["name"],
        metrics=metrics,
        history=history,
        recent_filings=filings,
        sic_description=sic_description,
        exchanges=exchanges,
    )

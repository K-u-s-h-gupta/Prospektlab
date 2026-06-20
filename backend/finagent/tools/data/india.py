"""India-specific financial data fetching.

Priority order:
  1. Moneycontrol / Screener.in  — pre-parsed structured data, rarely rate-limited
  2. NSE India API               — live quotes and corporate actions
  3. BSE India API               — fallback for NSE failures / BSE-only listings

All results are cached via finagent.tools.data.cache with IST-aware TTLs.
"""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Any

import httpx

from finagent.tools.data.cache import cached_call, cache_set, cache_get

logger = logging.getLogger("finagent.tools.data.india")

# ── HTTP session helper ────────────────────────────────────────────────────────

_HEADERS_NSE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/",
    "Accept-Language": "en-US,en;q=0.9",
}

_HEADERS_MC = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
}

def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


_MC_HISTORY_COUNTBACK = max(90, _int_env("FINAGENT_MC_HISTORY_COUNTBACK", 320))


_SYMBOL_ALIASES = {
    "ZOMATO": "ETERNAL",
}


def _canonical_symbol(symbol: str) -> str:
    value = (symbol or "").strip().upper()
    return _SYMBOL_ALIASES.get(value, value)


# Known Moneycontrol identifiers used by their chart endpoint.
# Unknown symbols fall back to the raw NSE ticker.
_MC_SYMBOL_MAP: dict[str, str] = {
    "RELIANCE": "RI",
    "TCS": "TCS",
    "INFY": "IT",
    "HDFCBANK": "HDF01",
    "ICICIBANK": "ICICIBANK",
    "SBIN": "SBI",
    "ITC": "ITC",
    "LT": "LT",
    "AXISBANK": "AXSB",
    "KOTAKBANK": "KTKM",
    "BHARTIARTL": "BHA",
    "HINDUNILVR": "HLL",
    "WIPRO": "WIP",
    "HCLTECH": "HCL04",
    "TECHM": "TECHM",
    "TATAMOTORS": "TATAMOTORS",
    "TATASTEEL": "TIS",
    "POWERGRID": "PGRI",
    "NTPC": "NTPC",
    "ONGC": "ONGC",
    "SUNPHARMA": "SUNPHARMA",
    "ASIANPAINT": "ASP",
    "NESTLEIND": "NEST",
    "ULTRACEMCO": "UTI",
    "BAJFINANCE": "BAF",
    "BAJAJFINSV": "BAF01",
    "INDUSINDBK": "INDBK",
    "M&M": "MAH",
    "MARUTI": "MAR02",
    "ADANIENT": "ADE",
    "JSWSTEEL": "JSW",
    "GRASIM": "GRI",
    "ZOMATO": "ZOMATO",
    "ETERNAL": "ETERNAL",
}


_TIMEOUT = httpx.Timeout(
    _float_env("FINAGENT_MARKET_DATA_TIMEOUT_S", 4.0),
    connect=_float_env("FINAGENT_MARKET_DATA_CONNECT_TIMEOUT_S", 1.5),
)


def _httpx_trust_env() -> bool:
    raw = os.getenv("FINAGENT_HTTP_TRUST_ENV", "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


_HTTPX_TRUST_ENV = _httpx_trust_env()
_PROVIDER_BACKOFF_SECONDS = _float_env("FINAGENT_MARKET_DATA_BACKOFF_S", 60.0)
_PROVIDER_BACKOFF: dict[str, float] = {}
_TRANSIENT_NETWORK_ERRORS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.TransportError,
)


def _provider_available(provider: str, symbol: str) -> bool:
    key = f"{provider}:{(symbol or '').upper()}"
    return time.monotonic() >= _PROVIDER_BACKOFF.get(key, 0.0)


def _mark_provider_miss(provider: str, symbol: str, exc: Exception) -> None:
    key = f"{provider}:{(symbol or '').upper()}"
    _PROVIDER_BACKOFF[key] = time.monotonic() + _PROVIDER_BACKOFF_SECONDS
    logger.debug(
        "%s temporarily unavailable for %s; suppressing retries for %.0fs: %s",
        provider,
        symbol,
        _PROVIDER_BACKOFF_SECONDS,
        type(exc).__name__,
    )


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class IndiaCompanySnapshot:
    """Unified India company data from Moneycontrol / NSE / BSE."""
    symbol: str                          # NSE symbol e.g. "RELIANCE"
    isin: str = ""                       # e.g. "INE002A01018"
    cin: str = ""                        # e.g. "L17110MH1973PLC019786"
    company_name: str = ""
    exchange: str = "NSE"                # "NSE" or "BSE"
    sector: str = ""
    industry: str = ""
    face_value: float | None = None
    market_cap_cr: float | None = None   # in Crores INR
    current_price: float | None = None
    change_pct: float | None = None
    week_52_high: float | None = None
    week_52_low: float | None = None
    # Fundamentals
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    eps: float | None = None
    book_value: float | None = None
    dividend_yield: float | None = None
    roe: float | None = None             # Return on Equity %
    roce: float | None = None            # Return on Capital Employed %
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    # Shareholding
    promoter_holding: float | None = None   # %
    fii_holding: float | None = None        # %
    dii_holding: float | None = None        # %
    public_holding: float | None = None     # %
    promoter_pledge_pct: float | None = None  # % of promoter shares pledged
    # Profile
    business_summary: str = ""
    screener_company_id: str = ""
    segment_data: dict[str, Any] = field(default_factory=dict)
    related_party_data: dict[str, Any] = field(default_factory=dict)
    annual_reports: list[dict[str, Any]] = field(default_factory=list)
    # Quarterly
    quarterly_revenue: list[dict] = field(default_factory=list)
    quarterly_profit: list[dict] = field(default_factory=list)
    # Price history
    series_dates: list[str] = field(default_factory=list)
    series_closes: list[float] = field(default_factory=list)
    # Source
    source: str = ""
    source_url: str = ""

    @property
    def metrics(self) -> dict[str, Any]:
        """Flat dict of all numeric metrics — mirrors old SECCompanySnapshot.metrics API."""
        m: dict[str, Any] = {}
        if self.pe_ratio is not None:       m["pe_ratio"]         = {"label": "P/E Ratio",              "display": f"{self.pe_ratio:.2f}x",    "value": self.pe_ratio}
        if self.pb_ratio is not None:       m["pb_ratio"]         = {"label": "P/B Ratio",              "display": f"{self.pb_ratio:.2f}x",    "value": self.pb_ratio}
        if self.eps is not None:            m["eps"]              = {"label": "EPS (TTM)",               "display": f"Rs {self.eps:.2f}",         "value": self.eps}
        if self.book_value is not None:     m["book_value"]       = {"label": "Book Value",              "display": f"Rs {self.book_value:.2f}",  "value": self.book_value}
        if self.dividend_yield is not None: m["dividend_yield"]   = {"label": "Dividend Yield",          "display": f"{self.dividend_yield:.2f}%","value": self.dividend_yield}
        if self.roe is not None:            m["roe"]              = {"label": "ROE",                     "display": f"{self.roe:.1f}%",         "value": self.roe}
        if self.roce is not None:           m["roce"]             = {"label": "ROCE",                    "display": f"{self.roce:.1f}%",        "value": self.roce}
        if self.debt_to_equity is not None: m["debt_to_equity"]   = {"label": "Debt / Equity",           "display": f"{self.debt_to_equity:.2f}","value": self.debt_to_equity}
        if self.market_cap_cr is not None:  m["market_cap"]       = {"label": "Market Cap",              "display": f"Rs {self.market_cap_cr:,.0f} Cr","value": self.market_cap_cr}
        if self.promoter_holding is not None: m["promoter_pct"]   = {"label": "Promoter Holding",        "display": f"{self.promoter_holding:.1f}%","value": self.promoter_holding}
        if self.fii_holding is not None:    m["fii_pct"]          = {"label": "FII Holding",             "display": f"{self.fii_holding:.1f}%", "value": self.fii_holding}
        if self.dii_holding is not None:    m["dii_pct"]          = {"label": "DII Holding",             "display": f"{self.dii_holding:.1f}%", "value": self.dii_holding}
        if self.promoter_pledge_pct is not None: m["pledge_pct"]  = {"label": "Promoter Pledge",         "display": f"{self.promoter_pledge_pct:.1f}%","value": self.promoter_pledge_pct}
        return m

    # Back-compat properties for SECCompanySnapshot
    @property
    def name(self) -> str: return self.company_name
    @property
    def ticker(self) -> str: return self.symbol
    @property
    def cik(self) -> str: return self.isin
    @property
    def sic_description(self) -> str: return self.industry
    @property
    def history(self) -> dict: return {}
    @property
    def exchanges(self) -> list[str]: return [self.exchange] if self.exchange else []
    @property
    def recent_filings(self) -> list: return []


@dataclass
class SEBIFiling:
    """Pre-parsed India regulatory filing from Moneycontrol / Trendlyne / BSE."""
    filing_type: str          # "Annual Report" | "Quarterly Result" | "DRHP" | "RHP"
    company: str
    period: str               # e.g. "FY2025", "Q4FY25"
    filed_date: str
    source_url: str
    business_overview: str | None = None
    risk_factors: str | None = None
    financial_summary: str | None = None
    management_discussion: str | None = None  # MD&A
    key_highlights: list[str] = field(default_factory=list)

    def has_any(self) -> bool:
        return any([self.business_overview, self.risk_factors,
                    self.financial_summary, self.management_discussion])

    @property
    def form(self) -> str:
        return self.filing_type

    @property
    def business(self) -> str | None:
        return self.business_overview

    @property
    def mdna(self) -> str | None:
        return self.management_discussion


# ── Screener.in ───────────────────────────────────────────────────────────────

async def _fetch_screener(symbol: str) -> IndiaCompanySnapshot | None:
    """Fetch company data from Screener.in — best source for 10-year financials."""
    provider = "screener"
    sym = _canonical_symbol(symbol)
    if not _provider_available(provider, sym):
        return None
    urls = [
        f"https://www.screener.in/company/{sym}/consolidated/",
        f"https://www.screener.in/company/{sym}/",
    ]
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS_MC, trust_env=_HTTPX_TRUST_ENV) as session:
            for url in urls:
                resp = await session.get(url)
                if resp.status_code != 200:
                    continue
                snap = _parse_screener_html(resp.text, sym)
                if snap is None:
                    continue
                snap.source_url = url
                if url.endswith("/consolidated/"):
                    snap.source = "screener.in consolidated"
                if snap.screener_company_id:
                    snap.segment_data = await _fetch_screener_segment_metadata(
                        session,
                        snap.screener_company_id,
                        consolidated=url.endswith("/consolidated/"),
                        referer=url,
                    )
                return snap
        return None
    except _TRANSIENT_NETWORK_ERRORS as exc:
        _mark_provider_miss(provider, sym, exc)
        return None
    except Exception as exc:
        logger.debug("screener fetch failed for %s: %s", symbol, exc)
        return None



def _clean_html_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = html_lib.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _parse_segment_names(segment_html: str) -> dict[str, Any]:
    names: list[str] = []
    restricted = "upgrade to premium" in (segment_html or "").lower()
    sales_m = re.search(r'<tbody[^>]*data-segment-line=["\']Sales["\'][^>]*>(.*?)</tbody>', segment_html or "", re.IGNORECASE | re.DOTALL)
    block = sales_m.group(1) if sales_m else (segment_html or "")
    for row_m in re.finditer(r"<tr[^>]*>(.*?)</tr>", block, re.IGNORECASE | re.DOTALL):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_m.group(1) or "", re.IGNORECASE | re.DOTALL)
        if not cells:
            continue
        label = _clean_html_text(cells[0])
        label_l = label.lower()
        if not label or label_l in {"sales", "profit %", "roce %"}:
            continue
        if "please upgrade" in label_l or "less:" in label_l:
            continue
        if label not in names:
            names.append(label)
    return {
        "status": "restricted" if restricted else ("available" if names else "unavailable"),
        "segments": names[:20],
        "reason": "segment_values_require_screener_premium" if restricted else ("parsed_public_segment_table" if names else "segment_table_unavailable"),
    }


async def _fetch_screener_segment_metadata(
    session: httpx.AsyncClient,
    company_id: str,
    *,
    consolidated: bool,
    referer: str,
) -> dict[str, Any]:
    params = "?consolidated=true" if consolidated else ""
    url = f"https://www.screener.in/api/segments/{company_id}/profit-loss/1/{params}"
    try:
        resp = await session.get(url, headers={**_HEADERS_MC, "Referer": referer})
        if resp.status_code != 200:
            return {"status": "unavailable", "source_url": url, "reason": f"http_{resp.status_code}"}
        parsed = _parse_segment_names(resp.text)
        parsed["source_url"] = url
        return parsed
    except Exception as exc:
        logger.debug("Screener segment fetch failed for %s: %s", company_id, exc)
        return {"status": "unavailable", "source_url": url, "reason": "fetch_failed"}


def _parse_annual_reports(page_html: str) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in re.finditer(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', page_html or "", re.IGNORECASE | re.DOTALL):
        url = html_lib.unescape(match.group(1) or "").strip()
        body = match.group(2) or ""
        text = _clean_html_text(body)
        if "financial year" not in text.lower() and "annual report" not in text.lower():
            continue
        year_m = re.search(r"(?:Financial\s+Year|FY)\s*(\d{4})", text, re.IGNORECASE)
        if not year_m:
            continue
        if url.startswith("/"):
            url = f"https://www.screener.in{url}"
        if url in seen:
            continue
        seen.add(url)
        reports.append({
            "year": int(year_m.group(1)),
            "label": f"Financial Year {year_m.group(1)}",
            "url": url,
            "source": "bse" if "bseindia.com" in url.lower() or "from bse" in text.lower() else "public_web",
        })
    reports.sort(key=lambda item: int(item.get("year") or 0), reverse=True)
    return reports[:8]


async def fetch_nse_delivery_snapshot(symbol: str) -> dict[str, Any]:
    """Fetch latest delivery percentage from NSE public archives when reachable."""
    sym = _canonical_symbol(symbol)
    cached = cache_get("delivery", sym)
    if cached is not None:
        return cached
    end_dt = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    start_dt = end_dt - timedelta(days=10)
    params = {
        "from": start_dt.strftime("%d-%m-%Y"),
        "to": end_dt.strftime("%d-%m-%Y"),
        "symbol": sym,
        "dataType": "priceVolumeDeliverable",
        "series": "EQ",
    }
    url = "https://www.nseindia.com/api/historical/securityArchives"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6.0), trust_env=_HTTPX_TRUST_ENV) as session:
            await session.get("https://www.nseindia.com", headers=_HEADERS_NSE)
            resp = await session.get(url, params=params, headers={**_HEADERS_NSE, "Referer": f"https://www.nseindia.com/get-quotes/equity?symbol={sym}"})
        if resp.status_code != 200:
            out = {"status": "unavailable", "reason": f"nse_http_{resp.status_code}", "source_url": url}
            cache_set("delivery", sym, out, "delivery")
            return out
        data = resp.json()
        rows = data.get("data") if isinstance(data, dict) else data
        if not isinstance(rows, list) or not rows:
            out = {"status": "unavailable", "reason": "nse_archive_empty", "source_url": url}
            cache_set("delivery", sym, out, "delivery")
            return out
        latest = rows[0]
        for row in rows:
            if isinstance(row, dict) and (row.get("COP_DELIV_PERC") or row.get("deliverableQty")):
                latest = row
                break
        delivery_pct = _safe_float(latest.get("COP_DELIV_PERC") or latest.get("DELIV_PER") or latest.get("deliverablePercent"))
        traded_qty = _safe_float(latest.get("CH_TOT_TRADED_QTY") or latest.get("totTradedQty"))
        deliverable_qty = _safe_float(latest.get("COP_DELIV_QTY") or latest.get("deliverableQty"))
        out = {
            "status": "ok" if delivery_pct is not None else "unavailable",
            "delivery_pct": delivery_pct,
            "traded_qty": traded_qty,
            "deliverable_qty": deliverable_qty,
            "as_of": str(latest.get("CH_TIMESTAMP") or latest.get("mTIMESTAMP") or latest.get("date") or ""),
            "source": "NSE public security archives",
            "source_url": url,
        }
        cache_set("delivery", sym, out, "delivery")
        return out
    except Exception as exc:
        logger.debug("NSE delivery fetch failed for %s: %s", sym, exc)
        return {"status": "unavailable", "reason": "nse_archive_fetch_failed", "source_url": url}

def _parse_screener_html(html: str, symbol: str) -> IndiaCompanySnapshot | None:
    """Parse key metrics from Screener.in HTML (no JS required for basic data)."""
    snap = IndiaCompanySnapshot(
        symbol=symbol.upper(),
        source="screener.in",
        source_url=f"https://www.screener.in/company/{symbol.upper()}/",
    )

    def _find(pattern: str) -> str | None:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else None

    def _num(raw: str | None) -> float | None:
        if not raw:
            return None
        text_val = str(raw).strip()
        if not text_val:
            return None
        neg = text_val.startswith("(") and text_val.endswith(")")
        text_val = text_val.strip("()")
        text_val = text_val.replace("₹", "").replace("Rs ", "")
        text_val = re.sub(r"(?i)\b(?:rs\.?|inr)\b", "", text_val)
        text_val = text_val.replace(",", "").replace("%", "")
        text_val = re.sub(r"(?i)\b(?:cr|crore|lakh|lakhs|mn|bn)\b", "", text_val)
        text_val = re.sub(r"[^0-9eE+\-.]", "", text_val)
        if not text_val or text_val in {"+", "-", ".", "+.", "-."}:
            return None
        try:
            value = float(text_val)
        except ValueError:
            return None
        return -value if neg else value

    # Company name
    name_m = re.search(r'<h1[^>]*class="[^"]*company-name[^"]*"[^>]*>([^<]+)', html)
    if name_m:
        snap.company_name = name_m.group(1).strip()
    if not snap.company_name:
        title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if title_m:
            title_text = re.sub(r"<[^>]+>", " ", title_m.group(1) or "")
            title_text = re.sub(r"\s+", " ", title_text).strip()
            if title_text:
                cleaned_title = title_text.split("|")[0].strip()
                cleaned_title = re.sub(r"\bshare\s+price\b.*$", "", cleaned_title, flags=re.IGNORECASE).strip()
                cleaned_title = re.sub(r"\s{2,}", " ", cleaned_title).strip(" -|")
                if cleaned_title:
                    snap.company_name = cleaned_title

    company_info_m = re.search(r'<div[^>]*id=["\']company-info["\'][^>]*>|<div[^>]*data-company-id=["\']\d+["\'][^>]*id=["\']company-info["\'][^>]*>', html, re.IGNORECASE | re.DOTALL)
    if company_info_m:
        id_m = re.search(r'data-company-id=["\'](\d+)["\']', company_info_m.group(0), re.IGNORECASE)
        if id_m:
            snap.screener_company_id = id_m.group(1)

    rpt_m = re.search(r'data-url=["\']([^"\']*/results/rpt/[^"\']+)["\']', html, re.IGNORECASE)
    if rpt_m:
        rpt_url = rpt_m.group(1)
        if rpt_url.startswith('/'):
            rpt_url = f"https://www.screener.in{rpt_url}"
        snap.related_party_data = {
            "status": "requires_free_login",
            "source_url": rpt_url,
            "reason": "screener_rpt_modal_requires_login_without_paid_api",
        }

    snap.annual_reports = _parse_annual_reports(html)

    cin_match = re.search(r"\b[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b", html, re.IGNORECASE)
    if cin_match:
        snap.cin = cin_match.group(0).upper()

    if not snap.isin:
        isin_match = re.search(r"\bINE[A-Z0-9]{9}\b", html, re.IGNORECASE)
        if isin_match:
            snap.isin = isin_match.group(0).upper()

    def _clean_classification(value: str | None) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        cleaned = re.sub(r"\s+", " ", raw).strip(" :|,-")
        low = cleaned.lower()
        # Avoid index labels and generic boilerplate being captured as sector.
        banned_tokens = ("nifty", "index", "indices", "incorporated", "india ratings", "www.", "http")
        if any(token in low for token in banned_tokens):
            return ""
        if len(cleaned) < 2 or len(cleaned) > 80:
            return ""
        if re.search(r"[a-z]{3}", low) is None:
            return ""
        if cleaned in {"i", "/i", "-", "--"}:
            return ""
        return cleaned

    sector_patterns = (
        r'"sector"\s*:\s*"([^"]{2,120})"',
        r'Sector\s*</[^>]+>\s*<[^>]*>\s*([^<]{2,120})\s*<',
        r'\bSector\b[^A-Za-z0-9]{1,16}([A-Za-z &/\-]{2,120})',
    )
    for pattern in sector_patterns:
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            cleaned = _clean_classification(m.group(1))
            if cleaned:
                snap.sector = cleaned
                break

    industry_patterns = (
        r'"industry"\s*:\s*"([^"]{2,120})"',
        r'Industry\s*</[^>]+>\s*<[^>]*>\s*([^<]{2,120})\s*<',
        r'\bIndustry\b[^A-Za-z0-9]{1,16}([A-Za-z &/\-]{2,120})',
    )
    for pattern in industry_patterns:
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            cleaned = _clean_classification(m.group(1))
            if cleaned:
                snap.industry = cleaned
                break

    ratio_section = re.search(r"id=[\"']top-ratios[\"'].*?</ul>", html, re.DOTALL | re.IGNORECASE)
    if ratio_section:
        block = ratio_section.group(0)

        kv_pairs: dict[str, str] = {}
        _tag_strip = re.compile(r"<[^>]+>")
        _pair_pat = re.compile(
            r'<li[^>]*>\s*<span[^>]*class=["\'][^"\']*name[^"\']*["\'][^>]*>(.*?)</span>\s*<span[^>]*class=["\'][^"\']*(?:number|value)[^"\']*["\'][^>]*>(.*?)</span>',
            re.IGNORECASE | re.DOTALL,
        )
        for pair in _pair_pat.finditer(block):
            raw_label = _tag_strip.sub(" ", pair.group(1) or "")
            raw_value = _tag_strip.sub(" ", pair.group(2) or "")
            label = re.sub(r"\s+", " ", raw_label).strip().lower()
            value = re.sub(r"\s+", " ", raw_value).strip()
            if label and value:
                kv_pairs[label] = value

        def _kv(*tokens: str) -> float | None:
            for label, raw_value in kv_pairs.items():
                if all(token in label for token in tokens):
                    return _num(raw_value)
            return None

        def _latest_table_value(section_id: str, *label_tokens: str) -> float | None:
            section_m = re.search(
                rf'<section[^>]*id=["\']{re.escape(section_id)}["\'][^>]*>(.*?)</section>',
                html,
                re.IGNORECASE | re.DOTALL,
            )
            if not section_m:
                return None
            for row_m in re.finditer(r"<tr[^>]*>(.*?)</tr>", section_m.group(1) or "", re.IGNORECASE | re.DOTALL):
                cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_m.group(1) or "", re.IGNORECASE | re.DOTALL)
                if len(cells) < 2:
                    continue
                label = re.sub(r"\s+", " ", _tag_strip.sub(" ", cells[0] or "")).strip().lower()
                if not all(token in label for token in label_tokens):
                    continue
                values = [_num(re.sub(r"\s+", " ", _tag_strip.sub(" ", cell or "")).strip()) for cell in cells[1:]]
                values = [value for value in values if value is not None]
                return values[-1] if values else None
            return None

        def _find_block(pattern: str) -> str | None:
            m = re.search(pattern, block, re.IGNORECASE | re.DOTALL)
            return m.group(1).strip() if m else None

        currency_pat = r"(?:Rs\.?|INR)?"
        snap.market_cap_cr = _kv("market", "cap") or _num(_find_block(rf'Market\s+Cap.*?{currency_pat}\s*([\d,.]+)'))
        snap.current_price = _kv("current", "price") or _num(_find_block(rf'Current\s+Price.*?{currency_pat}\s*([\d,.]+)'))
        snap.pe_ratio = _kv("stock", "p/e") or _num(_find_block(r'Stock\s+P/E.*?<span[^>]*>([\d.]+)'))
        snap.pb_ratio = _kv("stock", "p/b") or _num(_find_block(r'Stock\s+P/B.*?<span[^>]*>([\d.]+)'))
        snap.eps = _kv("eps") or _num(_find_block(r'(?:TTM\s+)?EPS.*?<span[^>]*>([\d.]+)'))
        snap.book_value = _kv("book", "value") or _num(_find_block(rf'Book\s+Value.*?{currency_pat}\s*([\d.]+)'))
        snap.dividend_yield = _kv("dividend", "yield") or _num(_find_block(r'Dividend\s+Yield.*?([\d.]+)\s*%'))
        snap.roce = _kv("roce") or _num(_find_block(r'ROCE.*?([\d.]+)\s*%'))
        snap.roe = _kv("roe") or _num(_find_block(r'ROE.*?([\d.]+)\s*%'))
        snap.debt_to_equity = _kv("debt", "eq") or _num(_find_block(r'Debt\s*(?:/|to)?\s*Eq(?:uity)?.*?<span[^>]*>([\d.]+)'))
        snap.current_ratio = _kv("current", "ratio") or _num(_find_block(r'Current\s+Ratio.*?<span[^>]*>([\d.]+)'))

        if snap.debt_to_equity is None:
            borrowings = _latest_table_value("balance-sheet", "borrowings")
            share_capital = _latest_table_value("balance-sheet", "share", "capital")
            reserves = _latest_table_value("balance-sheet", "reserves")
            equity = (share_capital or 0.0) + (reserves or 0.0)
            if borrowings is not None and equity > 0:
                snap.debt_to_equity = round(float(borrowings) / float(equity), 4)

        high_low_value = ""
        for label, value in kv_pairs.items():
            if "high" in label and "low" in label:
                high_low_value = value
                break
        hl_match = re.search(r'([\d,.]+)\s*/\s*([\d,.]+)', high_low_value) if high_low_value else None
        if hl_match is None:
            block_text = re.sub(r"\s+", " ", _tag_strip.sub(" ", block)).strip()
            hl_match = re.search(r'High\s*/\s*Low\s*[^0-9]*([\d,.]+)\s*/\s*[^0-9]*([\d,.]+)', block_text, re.IGNORECASE)
        if hl_match:
            snap.week_52_high = _num(hl_match.group(1))
            snap.week_52_low = _num(hl_match.group(2))

        if snap.pb_ratio is None and snap.current_price is not None and snap.book_value not in (None, 0):
            try:
                snap.pb_ratio = round(float(snap.current_price) / float(snap.book_value), 4)
            except Exception:
                pass

        if snap.pe_ratio is None and snap.current_price is not None and snap.eps not in (None, 0):
            try:
                snap.pe_ratio = round(float(snap.current_price) / float(snap.eps), 4)
            except Exception:
                pass

    tag_strip = re.compile(r"<[^>]+>")

    about_m = re.search(
        r'<div[^>]*class=["\'][^"\']*about[^"\']*["\'][^>]*>(.*?)</div>',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    if about_m:
        about_text = tag_strip.sub(" ", about_m.group(1) or "")
        about_text = about_text.replace("&nbsp;", " ").replace("&amp;", "&")
        about_text = re.sub(r"\s+", " ", about_text).strip()
        if about_text:
            snap.business_summary = about_text[:1200]

    def _latest_shareholding_value(*aliases: str) -> float | None:
        marker = re.search(r'<section[^>]*id=["\']shareholding["\'][^>]*>(.*?)</section>', html, re.IGNORECASE | re.DOTALL)
        block = marker.group(1) if marker else html
        alias_l = tuple(alias.lower() for alias in aliases)
        for row_m in re.finditer(r"<tr[^>]*>(.*?)</tr>", block, re.IGNORECASE | re.DOTALL):
            row_html = row_m.group(1) or ""
            row_text = tag_strip.sub(" ", row_html).replace("&nbsp;", " ")
            row_text = re.sub(r"\s+", " ", row_text).strip().lower()
            if not any(alias in row_text for alias in alias_l):
                continue
            values = re.findall(r"<td[^>]*>\s*([0-9][\d,.]*)\s*%", row_html, re.IGNORECASE)
            if values:
                return _num(values[-1])
        return None

    # Shareholding from Screener. Prefer the latest quarterly shareholding row.
    snap.promoter_holding = _latest_shareholding_value("promoters", "promoter") or _num(_find(r'Promoter\s+Holding.*?([\d.]+)\s*%'))
    snap.fii_holding = _latest_shareholding_value("fiis", "foreign institutions", "fii") or _num(_find(r'FII\s+Holding.*?([\d.]+)\s*%'))
    snap.dii_holding = _latest_shareholding_value("diis", "domestic institutions", "dii") or _num(_find(r'DII\s+Holding.*?([\d.]+)\s*%'))
    snap.public_holding = _latest_shareholding_value("public") or _num(_find(r'Public\s+Holding.*?([\d.]+)\s*%'))
    snap.promoter_pledge_pct = _num(
        _find(r'Promoter\s+Pledge.*?([\d.]+)\s*%')
        or _find(r'Pledged\s+Percentage.*?([\d.]+)\s*%')
    )

    if any(
        value is not None
        for value in (
            snap.current_price,
            snap.market_cap_cr,
            snap.pe_ratio,
            snap.pb_ratio,
            snap.roe,
            snap.roce,
        )
    ) or snap.company_name:
        return snap
    return None


async def _fetch_moneycontrol(symbol: str) -> IndiaCompanySnapshot | None:
    """Fetch from Moneycontrol API (JSON endpoints used by their site)."""
    provider = "moneycontrol"
    sym = _canonical_symbol(symbol)
    if not _provider_available(provider, sym):
        return None
    mc_sym = _MC_SYMBOL_MAP.get(sym, sym)
    url = f"https://priceapi.moneycontrol.com/techCharts/indianMarket/stock/history?symbol={mc_sym}&resolution=1D&countback={_MC_HISTORY_COUNTBACK}&currencyCode=INR"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS_MC, trust_env=_HTTPX_TRUST_ENV) as session:
            resp = await session.get(url)
            if resp.status_code != 200:
                return None
            data = resp.json()
        return _parse_moneycontrol_json(data, sym)
    except _TRANSIENT_NETWORK_ERRORS as exc:
        _mark_provider_miss(provider, sym, exc)
        return None
    except Exception as exc:
        logger.debug("moneycontrol fetch failed for %s: %s", sym, exc)
        return None


def _parse_moneycontrol_json(data: dict, symbol: str) -> IndiaCompanySnapshot | None:
    if not data or data.get("s") != "ok":
        return None

    closes_raw = data.get("c", []) or []
    times_raw = data.get("t", []) or []

    series_dates: list[str] = []
    series_closes: list[float] = []

    for idx, raw_close in enumerate(closes_raw):
        close = _safe_float(raw_close)
        if close is None:
            continue
        ts = times_raw[idx] if idx < len(times_raw) else None
        dt = None
        if isinstance(ts, str) and ts.strip().isdigit():
            ts = int(ts.strip())
        if isinstance(ts, (int, float)):
            ts_num = int(ts)
            if ts_num > 10**12:
                ts_num //= 1000
            try:
                dt = datetime.fromtimestamp(ts_num, tz=timezone.utc)
            except Exception:
                dt = None
        series_dates.append(dt.date().isoformat() if dt else "")
        series_closes.append(float(close))

    if not series_closes:
        return None

    snap = IndiaCompanySnapshot(
        symbol=symbol.upper(),
        current_price=series_closes[-1],
        series_dates=series_dates,
        series_closes=series_closes,
        source="moneycontrol",
        source_url=f"https://www.moneycontrol.com/india/stockpricequote/{symbol.lower()}",
    )
    if len(series_closes) >= 2:
        prev = series_closes[-2]
        curr = series_closes[-1]
        snap.change_pct = round((curr - prev) / prev * 100, 2) if prev else None
    return snap

# ── NSE India API ─────────────────────────────────────────────────────────────

async def _fetch_nse(symbol: str) -> IndiaCompanySnapshot | None:
    """Fetch from NSE India's JSON API (needs Referer cookie dance)."""
    provider = "nse"
    sym = _canonical_symbol(symbol)
    if not _provider_available(provider, sym):
        return None
    quote_url = f"https://www.nseindia.com/api/quote-equity?symbol={sym}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=_HTTPX_TRUST_ENV) as session:
            # Seed cookies with a homepage visit
            await session.get("https://www.nseindia.com", headers=_HEADERS_NSE)
            resp = await session.get(quote_url, headers=_HEADERS_NSE)
            if resp.status_code != 200:
                return None
            data = resp.json()
        return _parse_nse_json(data, sym)
    except _TRANSIENT_NETWORK_ERRORS as exc:
        _mark_provider_miss(provider, sym, exc)
        return None
    except Exception as exc:
        logger.debug("NSE fetch failed for %s: %s", sym, exc)
        return None


def _parse_nse_json(data: dict, symbol: str) -> IndiaCompanySnapshot | None:
    if not data:
        return None
    info = data.get("info", {})
    price_info = data.get("priceInfo", {})
    metadata = data.get("metadata", {})

    snap = IndiaCompanySnapshot(
        symbol=symbol.upper(),
        isin=info.get("isin", ""),
        company_name=info.get("companyName", ""),
        exchange="NSE",
        sector=metadata.get("sector", ""),
        industry=metadata.get("industry", ""),
        current_price=price_info.get("lastPrice"),
        change_pct=price_info.get("pChange"),
        week_52_high=price_info.get("weekHighLow", {}).get("max"),
        week_52_low=price_info.get("weekHighLow", {}).get("min"),
        face_value=metadata.get("pdFaceValue"),
        source="NSE",
        source_url=f"https://www.nseindia.com/get-quotes/equity?symbol={symbol.upper()}",
    )
    return snap if snap.company_name else None


# ── BSE India API (fallback) ──────────────────────────────────────────────────

# BSE uses numeric scrip codes; map NSE symbols to BSE codes for major stocks
_BSE_SCRIP_MAP: dict[str, str] = {
    "RELIANCE": "500325", "TCS": "532540",     "HDFCBANK": "500180",
    "INFY": "500209",     "ICICIBANK": "532174","HINDUNILVR": "500696",
    "SBIN": "500112",     "BHARTIARTL": "532454","ITC": "500875",
    "KOTAKBANK": "500247","LT": "500510",       "AXISBANK": "532215",
    "BAJFINANCE": "500034","WIPRO": "507685",   "HCLTECH": "532281",
    "MARUTI": "532500",   "TATAMOTORS": "500570","TATASTEEL": "500470",
    "NTPC": "532555",     "POWERGRID": "532898", "SUNPHARMA": "524715",
    "TITAN": "500114",    "ONGC": "500312",     "M&M": "500520",
}


async def _fetch_bse(symbol: str) -> IndiaCompanySnapshot | None:
    """Fetch from BSE India API as fallback."""
    provider = "bse"
    sym = _canonical_symbol(symbol)
    if not _provider_available(provider, sym):
        return None
    scrip = _BSE_SCRIP_MAP.get(sym)
    if not scrip:
        logger.debug("no BSE scrip code for %s", sym)
        return None
    url = f"https://api.bseindia.com/BseIndiaAPI/api/getScripHeaderData/w?Debtflag=&scripcode={scrip}&seriesid="
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS_MC, trust_env=_HTTPX_TRUST_ENV) as session:
            resp = await session.get(url)
            if resp.status_code != 200:
                return None
            data = resp.json()
        return _parse_bse_json(data, sym, scrip)
    except _TRANSIENT_NETWORK_ERRORS as exc:
        _mark_provider_miss(provider, sym, exc)
        return None
    except Exception as exc:
        logger.debug("BSE fetch failed for %s: %s", sym, exc)
        return None


def _parse_bse_json(data: dict, symbol: str, scrip: str) -> IndiaCompanySnapshot | None:
    if not data:
        return None
    snap = IndiaCompanySnapshot(
        symbol=symbol.upper(),
        isin=data.get("ISIN_Code", ""),
        cin=data.get("CIN", ""),
        company_name=data.get("LongName", ""),
        exchange="BSE",
        face_value=_safe_float(data.get("FaceValue")),
        current_price=_safe_float(data.get("CurrRate")),
        change_pct=_safe_float(data.get("Prcntchng")),
        week_52_high=_safe_float(data.get("High52")),
        week_52_low=_safe_float(data.get("Low52")),
        market_cap_cr=_safe_float(data.get("Mktcap")),
        source="BSE",
        source_url=f"https://www.bseindia.com/stock-share-price/{symbol.lower()}/{scrip}/",
    )
    return snap if snap.company_name else None


def _safe_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, str):
        raw = v.strip()
        if not raw:
            return None
        raw = raw.replace("₹", "").replace("Rs ", "")
        raw = raw.replace(",", "").replace("%", "")
        raw = re.sub(r"(?i)\b(?:rs\.?|inr|crore|cr)\b", "", raw)
        raw = re.sub(r"[^0-9eE+\-.]", "", raw)
        if raw in {"", "+", "-", ".", "+.", "-."}:
            return None
        v = raw
    try:
        return float(v) if v != "" else None
    except (ValueError, TypeError):
        return None


# ── Shareholding (NSE first, then BSE) ───────────────────────────────────────

async def fetch_shareholding_pattern(symbol: str) -> dict | None:
    """Fetch latest shareholding pattern: Promoter / FII / DII / Public."""
    logger.info("[MCP-USE] nse_india | tool=nse_get_shareholding | args={'symbol': '%s'}", symbol)
    try:
        from finagent.state.session_context import record_mcp
        record_mcp("nse_india")
    except ImportError:
        pass
    cached = cache_get("shareholding", symbol)
    if cached is not None:
        return cached

    # Try NSE shareholding API
    url = f"https://www.nseindia.com/api/corporate-share-holdings-master?index=shareHolding&symbol={symbol.upper()}&csvVal=1"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, trust_env=_HTTPX_TRUST_ENV) as session:
            await session.get("https://www.nseindia.com", headers=_HEADERS_NSE)
            resp = await session.get(url, headers=_HEADERS_NSE)
            if resp.status_code == 200:
                data = resp.json()
                holding = _parse_nse_shareholding(data)
                if holding:
                    cache_set("shareholding", symbol, holding, "shareholding")
                    return holding
    except Exception as exc:
        logger.debug("NSE shareholding failed for %s: %s", symbol, exc)

    return None


def _parse_nse_shareholding(data: list | dict) -> dict | None:
    if not data:
        return None
    if isinstance(data, dict):
        data = data.get("data", []) or []
    if not data:
        return None
    latest = data[0] if data else {}
    return {
        "promoter":   _safe_float(latest.get("promoterAndPromoterGroupTotal")),
        "fii":        _safe_float(latest.get("totalForeignInstitutional")),
        "dii":        _safe_float(latest.get("totalDomesticInstitutions")),
        "public":     _safe_float(latest.get("publicTotal")),
        "as_of":      latest.get("shareholdingDate", ""),
    }


# ── SEBI filing (Moneycontrol / Trendlyne pre-parsed) ───────────────────────

async def fetch_sebi_filing(symbol: str, filing_type: str = "annual") -> SEBIFiling | None:
    """Return pre-parsed filing data from Moneycontrol / Trendlyne.

    For now we pull from Trendlyne's structured JSON endpoints which give
    us the key financial highlights without needing to parse SEBI PDFs.
    """
    logger.info("[MCP-USE] nse_india | tool=nse_get_announcements | args={'symbol': '%s'}", symbol)
    try:
        from finagent.state.session_context import record_mcp
        record_mcp("nse_india")
    except ImportError:
        pass
    cached = cache_get("sebi_filing", f"{symbol}:{filing_type}")
    if cached is not None:
        return cached

    url = f"https://trendlyne.com/equity/{symbol.upper()}/analysis/"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), headers=_HEADERS_MC, trust_env=_HTTPX_TRUST_ENV) as session:
            resp = await session.get(url)
            if resp.status_code != 200:
                return None
            html = resp.text
        filing = _parse_trendlyne_analysis(html, symbol)
        if filing:
            cache_set("sebi_filing", f"{symbol}:{filing_type}", filing, "sebi_filing")
        return filing
    except Exception as exc:
        logger.debug("Trendlyne analysis fetch failed for %s: %s", symbol, exc)
        return None


def _parse_trendlyne_analysis(html: str, symbol: str) -> SEBIFiling | None:
    """Extract structured text blocks from Trendlyne analysis page."""
    filing = SEBIFiling(
        filing_type="Annual Analysis",
        company=symbol.upper(),
        period="Latest",
        filed_date="",
        source_url=f"https://trendlyne.com/equity/{symbol.upper()}/analysis/",
    )

    def _section(heading_re: str) -> str | None:
        m = re.search(
            rf'{heading_re}.*?<div[^>]*class="[^"]*analysis[^"]*"[^>]*>(.*?)</div>',
            html, re.DOTALL | re.IGNORECASE,
        )
        if not m:
            return None
        return re.sub(r"<[^>]+>", " ", m.group(1)).strip()[:2000]

    filing.business_overview    = _section(r"Business Overview|About the Company")
    filing.management_discussion = _section(r"Management Analysis|Management Discussion")
    filing.risk_factors          = _section(r"Risk Factors|Key Risks")
    filing.financial_summary     = _section(r"Financial Summary|Financial Performance")

    return filing if filing.has_any() else None


# ── Primary public API ────────────────────────────────────────────────────────

async def fetch_india_snapshot(symbol: str) -> IndiaCompanySnapshot | None:
    """Fetch company snapshot.

    Strategy:
      1. Screener.in (most complete pre-parsed fundamentals)
      2. Moneycontrol  (price + chart data)
      3. NSE India API (live quote)
      4. BSE India API (final fallback for BSE-only listings)

    Results merged: first successful source wins, subsequent sources
    backfill any missing numeric fields.
    """
    logger.info("[MCP-USE] fundamentals | tool=profile | args={'symbol': '%s'}", symbol)
    try:
        from finagent.state.session_context import record_mcp
        record_mcp("fundamentals")
    except ImportError:
        pass
    sym = _canonical_symbol(symbol)

    async def _do_fetch() -> IndiaCompanySnapshot | None:
        screener_snap, mc_snap, nse_snap = await asyncio.gather(
            _fetch_screener(sym),
            _fetch_moneycontrol(sym),
            _fetch_nse(sym),
            return_exceptions=True,
        )

        if isinstance(screener_snap, Exception):
            logger.debug("Screener fetch failed for %s: %s", sym, screener_snap)
            screener_snap = None
        if isinstance(mc_snap, Exception):
            logger.debug("Moneycontrol fetch failed for %s: %s", sym, mc_snap)
            mc_snap = None
        if isinstance(nse_snap, Exception):
            logger.debug("NSE fetch failed for %s: %s", sym, nse_snap)
            nse_snap = None

        # Prefer Screener fundamentals, but prefer NSE quote freshness.
        snap = screener_snap or nse_snap or mc_snap
        if snap is None:
            logger.debug("Screener/MC/NSE miss for %s; trying BSE", sym)
            snap = await _fetch_bse(sym)

        if snap is None:
            return None

        def _fill_missing(target: IndiaCompanySnapshot, source: IndiaCompanySnapshot, fields: list[str]) -> None:
            for field in fields:
                if getattr(target, field) in (None, "") and getattr(source, field) not in (None, ""):
                    setattr(target, field, getattr(source, field))

        if nse_snap is not None:
            # NSE quote is the freshest available public source for listed equities.
            if nse_snap.current_price is not None:
                snap.current_price = nse_snap.current_price
            if nse_snap.change_pct is not None:
                snap.change_pct = nse_snap.change_pct
            if nse_snap.week_52_high is not None:
                snap.week_52_high = nse_snap.week_52_high
            if nse_snap.week_52_low is not None:
                snap.week_52_low = nse_snap.week_52_low
            _fill_missing(
                snap,
                nse_snap,
                ["isin", "cin", "company_name", "sector", "industry", "face_value", "exchange"],
            )
            if snap.source and "nse" not in snap.source.lower():
                snap.source = f"{snap.source}+NSE"

        if mc_snap is not None:
            if snap.current_price is None and mc_snap.current_price is not None:
                snap.current_price = mc_snap.current_price
            if snap.change_pct is None and mc_snap.change_pct is not None:
                snap.change_pct = mc_snap.change_pct
            if not getattr(snap, "series_dates", None) and getattr(mc_snap, "series_dates", None):
                snap.series_dates = list(mc_snap.series_dates)
            if not getattr(snap, "series_closes", None) and getattr(mc_snap, "series_closes", None):
                snap.series_closes = list(mc_snap.series_closes)

        if (snap.current_price is None or not snap.company_name) and snap.exchange != "BSE":
            bse_snap = await _fetch_bse(sym)
            if bse_snap is not None:
                _fill_missing(
                    snap,
                    bse_snap,
                    [
                        "isin",
                        "cin",
                        "company_name",
                        "exchange",
                        "face_value",
                        "week_52_high",
                        "week_52_low",
                        "market_cap_cr",
                    ],
                )
                if snap.current_price is None and bse_snap.current_price is not None:
                    snap.current_price = bse_snap.current_price
                if snap.change_pct is None and bse_snap.change_pct is not None:
                    snap.change_pct = bse_snap.change_pct

        return snap

    return await cached_call("india_snap", sym, "price", _do_fetch)


async def fetch_nse_snapshot(symbol: str) -> IndiaCompanySnapshot | None:
    """NSE-first fetch (used as an explicit NSE-direct call, bypasses Screener)."""
    logger.info("[MCP-USE] nse_india | tool=nse_get_quote | args={'symbol': '%s'}", symbol)
    try:
        from finagent.state.session_context import record_mcp
        record_mcp("nse_india")
    except ImportError:
        pass
    sym = _canonical_symbol(symbol)

    async def _do() -> IndiaCompanySnapshot | None:
        snap = await _fetch_nse(sym)
        if snap is None:
            snap = await _fetch_bse(sym)
        return snap

    return await cached_call("nse_snap", sym, "price", _do)

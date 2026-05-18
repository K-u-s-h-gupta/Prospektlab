"""India-specific financial data fetching.

Priority order:
  1. Moneycontrol / Screener.in  — pre-parsed structured data, rarely rate-limited
  2. NSE India API               — live quotes and corporate actions
  3. BSE India API               — fallback for NSE failures / BSE-only listings

All results are cached via finagent.tools.data.cache with IST-aware TTLs.
"""

from __future__ import annotations

import asyncio
import logging
import re
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

_TIMEOUT = httpx.Timeout(15.0)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class IndiaCompanySnapshot:
    """Unified India company data from Moneycontrol / NSE / BSE."""
    symbol: str                          # NSE symbol e.g. "RELIANCE"
    isin: str = ""                       # e.g. "INE002A01018"
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
    # Quarterly
    quarterly_revenue: list[dict] = field(default_factory=list)
    quarterly_profit: list[dict] = field(default_factory=list)
    # Source
    source: str = ""
    source_url: str = ""

    @property
    def metrics(self) -> dict[str, Any]:
        """Flat dict of all numeric metrics — mirrors old SECCompanySnapshot.metrics API."""
        m: dict[str, Any] = {}
        if self.pe_ratio is not None:       m["pe_ratio"]         = {"label": "P/E Ratio",              "display": f"{self.pe_ratio:.2f}x",    "value": self.pe_ratio}
        if self.pb_ratio is not None:       m["pb_ratio"]         = {"label": "P/B Ratio",              "display": f"{self.pb_ratio:.2f}x",    "value": self.pb_ratio}
        if self.eps is not None:            m["eps"]              = {"label": "EPS (TTM)",               "display": f"₹{self.eps:.2f}",         "value": self.eps}
        if self.book_value is not None:     m["book_value"]       = {"label": "Book Value",              "display": f"₹{self.book_value:.2f}",  "value": self.book_value}
        if self.dividend_yield is not None: m["dividend_yield"]   = {"label": "Dividend Yield",          "display": f"{self.dividend_yield:.2f}%","value": self.dividend_yield}
        if self.roe is not None:            m["roe"]              = {"label": "ROE",                     "display": f"{self.roe:.1f}%",         "value": self.roe}
        if self.roce is not None:           m["roce"]             = {"label": "ROCE",                    "display": f"{self.roce:.1f}%",        "value": self.roce}
        if self.debt_to_equity is not None: m["debt_to_equity"]   = {"label": "Debt / Equity",           "display": f"{self.debt_to_equity:.2f}","value": self.debt_to_equity}
        if self.market_cap_cr is not None:  m["market_cap"]       = {"label": "Market Cap",              "display": f"₹{self.market_cap_cr:,.0f} Cr","value": self.market_cap_cr}
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


# ── Screener.in ───────────────────────────────────────────────────────────────

async def _fetch_screener(symbol: str) -> IndiaCompanySnapshot | None:
    """Fetch company data from Screener.in — best source for 10-year financials."""
    url = f"https://www.screener.in/company/{symbol.upper()}/"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS_MC) as session:
            resp = await session.get(url)
            if resp.status_code != 200:
                return None
            html = resp.text
        return _parse_screener_html(html, symbol)
    except Exception as exc:
        logger.debug("screener fetch failed for %s: %s", symbol, exc)
        return None


def _parse_screener_html(html: str, symbol: str) -> IndiaCompanySnapshot | None:
    """Parse key metrics from Screener.in HTML (no JS required for basic data)."""
    snap = IndiaCompanySnapshot(symbol=symbol.upper(), source="screener.in",
                                source_url=f"https://www.screener.in/company/{symbol.upper()}/")

    def _find(pattern: str) -> str | None:
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        return m.group(1).strip() if m else None

    def _num(s: str | None) -> float | None:
        if not s:
            return None
        s = re.sub(r"[₹,%\s,Cr]", "", s)
        try:
            return float(s)
        except ValueError:
            return None

    # Company name
    name_m = re.search(r'<h1[^>]*class="[^"]*company-name[^"]*"[^>]*>([^<]+)', html)
    if name_m:
        snap.company_name = name_m.group(1).strip()

    # Key ratios table — Screener renders these in a specific #top-ratios div
    ratio_section = re.search(r'id=["\']top-ratios["\'].*?</ul>', html, re.DOTALL)
    if ratio_section:
        block = ratio_section.group(0)

        def _find_block(pattern: str) -> str | None:
            m = re.search(pattern, block, re.IGNORECASE | re.DOTALL)
            return m.group(1).strip() if m else None

        snap.market_cap_cr  = _num(_find_block(r'Market\s+Cap.*?₹\s*([\d,]+)'))
        snap.current_price  = _num(_find_block(r'Current\s+Price.*?₹\s*([\d,.]+)'))
        snap.pe_ratio       = _num(_find_block(r'Stock\s+P/E.*?<span[^>]*>([\d.]+)'))
        snap.book_value     = _num(_find_block(r'Book\s+Value.*?₹\s*([\d.]+)'))
        snap.dividend_yield = _num(_find_block(r'Dividend\s+Yield.*?([\d.]+)\s*%'))
        snap.roce           = _num(_find_block(r'ROCE.*?([\d.]+)\s*%'))
        snap.roe            = _num(_find_block(r'ROE.*?([\d.]+)\s*%'))

    # Shareholding from Screener
    snap.promoter_holding = _num(_find(r'Promoter Holding.*?([\d.]+)\s*%'))
    snap.fii_holding      = _num(_find(r'FII\s+Holding.*?([\d.]+)\s*%'))
    snap.dii_holding      = _num(_find(r'DII\s+Holding.*?([\d.]+)\s*%'))

    if snap.company_name or snap.pe_ratio or snap.market_cap_cr:
        return snap
    return None


# ── Moneycontrol ──────────────────────────────────────────────────────────────

# Known Moneycontrol symbol map for top Indian companies (extend as needed)
_MC_SYMBOL_MAP: dict[str, str] = {
    "RELIANCE": "RI",  "TCS": "TCS", "HDFCBANK": "HDF01",
    "INFY": "IT",      "ICICIBANK": "ICICIBANK", "HINDUNILVR": "HLL",
    "SBIN": "SBI",     "BHARTIARTL": "BHA",      "ITC": "ITC",
    "KOTAKBANK": "KTKM", "LT": "LT",             "AXISBANK": "AXSB",
    "BAJFINANCE": "BAF",  "WIPRO": "WIP",         "HCLTECH": "HCL04",
    "MARUTI": "MAR02",    "TATAMOTORS": "TATAMOTORS", "ADANIENT": "ADE",
    "TATASTEEL": "TIS",   "NTPC": "NTPC",         "POWERGRID": "PGRI",
    "ULTRACEMCO": "UTI",  "ASIANPAINT": "ASP",    "NESTLEIND": "NEST",
    "SUNPHARMA": "SUNPHARMA", "TITAN": "TITA",    "ONGC": "ONGC",
    "BAJAJFINSV": "BAF01",    "INDUSINDBK": "INDBK", "GRASIM": "GRI",
    "M&M": "MAH",             "JSWSTEEL": "JSW",   "TECHM": "TECHM",
}


async def _fetch_moneycontrol(symbol: str) -> IndiaCompanySnapshot | None:
    """Fetch from Moneycontrol API (JSON endpoints used by their site)."""
    mc_sym = _MC_SYMBOL_MAP.get(symbol.upper(), symbol.upper())
    url = f"https://priceapi.moneycontrol.com/techCharts/indianMarket/stock/history?symbol={mc_sym}&resolution=1D&countback=5&currencyCode=INR"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS_MC) as session:
            resp = await session.get(url)
            if resp.status_code != 200:
                return None
            data = resp.json()
        return _parse_moneycontrol_json(data, symbol)
    except Exception as exc:
        logger.debug("moneycontrol fetch failed for %s: %s", symbol, exc)
        return None


def _parse_moneycontrol_json(data: dict, symbol: str) -> IndiaCompanySnapshot | None:
    if not data or data.get("s") != "ok":
        return None
    closes = data.get("c", [])
    if not closes:
        return None
    snap = IndiaCompanySnapshot(
        symbol=symbol.upper(),
        current_price=float(closes[-1]) if closes else None,
        source="moneycontrol",
        source_url=f"https://www.moneycontrol.com/india/stockpricequote/{symbol.lower()}",
    )
    if len(closes) >= 2:
        prev = float(closes[-2])
        curr = float(closes[-1])
        snap.change_pct = round((curr - prev) / prev * 100, 2) if prev else None
    return snap


# ── NSE India API ─────────────────────────────────────────────────────────────

async def _fetch_nse(symbol: str) -> IndiaCompanySnapshot | None:
    """Fetch from NSE India's JSON API (needs Referer cookie dance)."""
    quote_url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol.upper()}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as session:
            # Seed cookies with a homepage visit
            await session.get("https://www.nseindia.com", headers=_HEADERS_NSE)
            resp = await session.get(quote_url, headers=_HEADERS_NSE)
            if resp.status_code != 200:
                return None
            data = resp.json()
        return _parse_nse_json(data, symbol)
    except Exception as exc:
        logger.debug("NSE fetch failed for %s: %s", symbol, exc)
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
    scrip = _BSE_SCRIP_MAP.get(symbol.upper())
    if not scrip:
        logger.debug("no BSE scrip code for %s", symbol)
        return None
    url = f"https://api.bseindia.com/BseIndiaAPI/api/getScripHeaderData/w?Debtflag=&scripcode={scrip}&seriesid="
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS_MC) as session:
            resp = await session.get(url)
            if resp.status_code != 200:
                return None
            data = resp.json()
        return _parse_bse_json(data, symbol, scrip)
    except Exception as exc:
        logger.debug("BSE fetch failed for %s: %s", symbol, exc)
        return None


def _parse_bse_json(data: dict, symbol: str, scrip: str) -> IndiaCompanySnapshot | None:
    if not data:
        return None
    snap = IndiaCompanySnapshot(
        symbol=symbol.upper(),
        isin=data.get("ISIN_Code", ""),
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
    try:
        return float(v) if v is not None and v != "" else None
    except (ValueError, TypeError):
        return None


# ── Shareholding (NSE first, then BSE) ───────────────────────────────────────

async def fetch_shareholding_pattern(symbol: str) -> dict | None:
    """Fetch latest shareholding pattern: Promoter / FII / DII / Public."""
    cached = cache_get("shareholding", symbol)
    if cached is not None:
        return cached

    # Try NSE shareholding API
    url = f"https://www.nseindia.com/api/corporate-share-holdings-master?index=shareHolding&symbol={symbol.upper()}&csvVal=1"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as session:
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
    cached = cache_get("sebi_filing", f"{symbol}:{filing_type}")
    if cached is not None:
        return cached

    url = f"https://trendlyne.com/equity/{symbol.upper()}/analysis/"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), headers=_HEADERS_MC) as session:
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
    sym = symbol.upper().strip()

    async def _do_fetch() -> IndiaCompanySnapshot | None:
        # Run Screener + Moneycontrol in parallel (both non-rate-limited)
        screener_snap, mc_snap = await asyncio.gather(
            _fetch_screener(sym),
            _fetch_moneycontrol(sym),
            return_exceptions=True,
        )

        # Resolve exceptions to None
        if isinstance(screener_snap, Exception):
            screener_snap = None
        if isinstance(mc_snap, Exception):
            mc_snap = None

        # Merge: start from Screener (richest), backfill from Moneycontrol
        snap = screener_snap or mc_snap
        if snap is None:
            logger.info("Screener/MC miss for %s — trying NSE", sym)
            snap = await _fetch_nse(sym)

        if snap is None:
            logger.info("NSE miss for %s — trying BSE", sym)
            snap = await _fetch_bse(sym)

        if snap is None:
            return None

        # Backfill price from MC if Screener didn't return it
        if snap is screener_snap and mc_snap and mc_snap.current_price:
            if snap.current_price is None:
                snap.current_price = mc_snap.current_price
            if snap.change_pct is None:
                snap.change_pct = mc_snap.change_pct

        return snap

    return await cached_call("india_snap", sym, "price", _do_fetch)


async def fetch_nse_snapshot(symbol: str) -> IndiaCompanySnapshot | None:
    """NSE-first fetch (used as an explicit NSE-direct call, bypasses Screener)."""
    sym = symbol.upper().strip()

    async def _do() -> IndiaCompanySnapshot | None:
        snap = await _fetch_nse(sym)
        if snap is None:
            snap = await _fetch_bse(sym)
        return snap

    return await cached_call("nse_snap", sym, "price", _do)

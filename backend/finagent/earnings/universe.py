"""Universe guardrails for the Earnings tab."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

_DEFAULT_LIMIT = 1000

_SENSEX_SYMBOLS = {
    "ASIANPAINT",
    "AXISBANK",
    "BAJAJFINSV",
    "BAJFINANCE",
    "BHARTIARTL",
    "HCLTECH",
    "HDFCBANK",
    "HINDUNILVR",
    "ICICIBANK",
    "INDUSINDBK",
    "INFY",
    "ITC",
    "JSWSTEEL",
    "KOTAKBANK",
    "LT",
    "M&M",
    "MARUTI",
    "NESTLEIND",
    "NTPC",
    "POWERGRID",
    "RELIANCE",
    "SBIN",
    "SUNPHARMA",
    "TATAMOTORS",
    "TATASTEEL",
    "TCS",
    "TECHM",
    "TITAN",
    "ULTRACEMCO",
    "ZOMATO",
}


@dataclass(frozen=True)
class EarningsUniverse:
    symbols: frozenset[str]
    isins: frozenset[str]
    bse_codes: frozenset[str]
    source: str

    @property
    def size(self) -> int:
        return len(self.symbols)


def _norm_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def _norm_text(value: Any) -> str:
    return str(value or "").strip()


def _load_indexed_companies() -> list[dict[str, Any]]:
    from finagent.ikg.scrapers.mca_companies import get_listed_companies

    return get_listed_companies(indexed_only=True)


@lru_cache(maxsize=1)
def get_earnings_universe() -> EarningsUniverse:
    limit = int(os.getenv("FINAGENT_EARNINGS_UNIVERSE_LIMIT", str(_DEFAULT_LIMIT)) or _DEFAULT_LIMIT)
    limit = max(1, min(limit, _DEFAULT_LIMIT))
    try:
        rows = _load_indexed_companies()[:limit]
    except Exception:
        rows = []

    symbols = {_norm_symbol(row.get("nse_symbol") or row.get("symbol")) for row in rows}
    isins = {_norm_symbol(row.get("isin")) for row in rows}
    bse_codes = {_norm_text(row.get("bse_scrip_code")) for row in rows}
    symbols = {symbol for symbol in symbols if symbol}
    isins = {isin for isin in isins if isin}
    bse_codes = {code for code in bse_codes if code}
    symbols.update(_SENSEX_SYMBOLS)

    return EarningsUniverse(
        symbols=frozenset(symbols),
        isins=frozenset(isins),
        bse_codes=frozenset(bse_codes),
        source="ikg_company_master_indexed",
    )


def record_in_earnings_universe(record: dict[str, Any]) -> bool:
    # When FINAGENT_EARNINGS_FILTER_UNIVERSE is false, allow all NSE/BSE
    # earnings announcements through so the calendar shows every company.
    if os.getenv("FINAGENT_EARNINGS_FILTER_UNIVERSE", "").lower() in {"0", "false", "off", "no"}:
        return True
    universe = get_earnings_universe()
    if not universe.symbols and not universe.isins and not universe.bse_codes:
        return True
    # If the universe only contains the fallback SENSEX symbols (no company master data),
    # allow all records through so we don't filter out companies when master is empty.
    if universe.symbols == _SENSEX_SYMBOLS and not universe.isins and not universe.bse_codes:
        return True
    symbol = _norm_symbol(record.get("symbol") or record.get("nse_symbol"))
    isin = _norm_symbol(record.get("isin"))
    bse_code = _norm_text(record.get("bse_scrip_code") or record.get("scrip_code"))
    return bool(
        (symbol and symbol in universe.symbols)
        or (isin and isin in universe.isins)
        or (bse_code and bse_code in universe.bse_codes)
    )


def filter_earnings_universe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record_in_earnings_universe(record)]


def earnings_universe_sql_filter(alias: str = "a") -> tuple[str, list[Any]]:
    # Respect the same kill-switch as record_in_earnings_universe so the calendar
    # and companies list show all NSE/BSE announcing companies when requested.
    if os.getenv("FINAGENT_EARNINGS_FILTER_UNIVERSE", "").lower() in {"0", "false", "off", "no"}:
        return "", []
    universe = get_earnings_universe()
    # If the universe only contains the fallback SENSEX symbols (no company master data),
    # disable filtering so all earnings announcements are shown. This prevents empty
    # results when the ikg_company_master table is not populated.
    if universe.symbols == _SENSEX_SYMBOLS and not universe.isins and not universe.bse_codes:
        return "", []
    clauses: list[str] = []
    params: list[Any] = []
    prefix = f"{alias}." if alias else ""
    if universe.symbols:
        clauses.append(f"upper(coalesce({prefix}symbol, '')) = any(%s)")
        params.append(sorted(universe.symbols))
    if universe.isins:
        clauses.append(f"upper(coalesce({prefix}isin, '')) = any(%s)")
        params.append(sorted(universe.isins))
    if universe.bse_codes:
        clauses.append(f"coalesce({prefix}bse_scrip_code, '') = any(%s)")
        params.append(sorted(universe.bse_codes))
    if not clauses:
        return "", []
    return "(" + " or ".join(clauses) + ")", params
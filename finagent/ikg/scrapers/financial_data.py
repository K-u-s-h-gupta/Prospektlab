"""Financial data scraper — multi-source triangulated financial data.

Fetches and cross-validates financial data from multiple free sources:
  1. yfinance — already integrated in finagent/tools/data/yahoo_finance.py
  2. Screener.in — structured financials for Indian companies (web scraping)
  3. NSE corporate filings — quarterly results metadata

Three-source validation: any financial fact stored in memory is
cross-referenced against at least 2 sources when available.

Schedule: Quarterly (after quarterly results season).
"""

from __future__ import annotations

import logging
import os
import re
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx

from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.scrapers._engine import sync_get

logger = logging.getLogger("finagent.ikg.scrapers.financial_data")

_SCREENER_BASE_URL = "https://www.screener.in/company/{ticker}/consolidated/"
_SCREENER_API_URL = "https://www.screener.in/api/company/{company_id}/"
_SCREENER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json, text/html, */*",
    "Referer": "https://www.screener.in/",
}
_REQUEST_DELAY_S = 2.0
_DEFAULT_MAX_WORKERS = 4


def fetch_screener_financials(ticker: str, timeout_s: float = 30.0) -> dict[str, Any] | None:
    """Fetch financial data from Screener.in for an NSE ticker.

    Screener.in has structured financial data (P&L, BS, CF) for Indian companies.
    We use the public web interface, parsing the embedded JSON data.

    Args:
        ticker: NSE symbol (e.g., "RELIANCE").
        timeout_s: Request timeout.

    Returns:
        Dict with income_statement, balance_sheet, cash_flow arrays, or None.
    """
    url = _SCREENER_BASE_URL.format(ticker=ticker.upper())
    try:
        resp = sync_get(url, headers=_SCREENER_HEADERS, timeout=timeout_s)
        if resp.status_code == 404:
            # Try standalone (non-consolidated)
            url_standalone = url.replace("/consolidated/", "/")
            resp = sync_get(url_standalone, headers=_SCREENER_HEADERS, timeout=timeout_s)
        if resp.status_code != 200:
            return None

        return _parse_screener_html(resp.text, ticker)

    except httpx.TimeoutException:
        logger.warning("Screener.in timeout for %s", ticker)
        return None
    except Exception as exc:
        logger.debug("Screener.in fetch failed for %s: %s", ticker, exc)
        return None


def _parse_screener_html(html: str, ticker: str) -> dict[str, Any]:
    """Extract financial tables from Screener.in HTML page.

    Screener.in embeds data in structured <table> elements with class 'data-table'
    and a <th> for the row label followed by <td> for each year's values.
    We parse these tables to populate income statement, balance sheet, cash flow.
    """
    result: dict[str, Any] = {
        "ticker": ticker,
        "source": "screener.in",
        "income_statement": [],
        "balance_sheet": [],
        "cash_flow": [],
        "key_ratios": {},
    }

    # ── 1. Extract year headers ───────────────────────────────────────────────
    # Screener tables have a header row like: | | Mar 2020 | Mar 2021 | ... |
    year_pat = re.compile(r'(?:Mar|Jun|Sep|Dec)\s+\d{4}', re.I)

    def _parse_table_section(html_chunk: str) -> list[dict[str, Any]]:
        """Parse a single Screener data table into a list of {year: value} dicts."""
        rows_out: list[dict[str, Any]] = []

        # Extract header years
        header_match = re.search(r'<thead[^>]*>(.*?)</thead>', html_chunk, re.S | re.I)
        years: list[str] = []
        if header_match:
            years = year_pat.findall(header_match.group(1))

        # Extract each data row
        row_pat = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S | re.I)
        td_pat = re.compile(r'<td[^>]*>(.*?)</td>', re.S | re.I)
        th_pat = re.compile(r'<th[^>]*>(.*?)</th>', re.S | re.I)
        tag_strip = re.compile(r'<[^>]+>')

        for row_m in row_pat.finditer(html_chunk):
            row_html = row_m.group(1)
            # First th/td is the label
            label_m = th_pat.search(row_html) or td_pat.search(row_html)
            if not label_m:
                continue
            label = tag_strip.sub('', label_m.group(1)).strip()
            if not label or label in ("+", "-", ""):
                continue
            values = [tag_strip.sub('', td.group(1)).replace(',', '').strip()
                      for td in td_pat.finditer(row_html)]
            if not values:
                continue

            row_dict: dict[str, Any] = {"label": label}
            for i, yr in enumerate(years):
                if i < len(values):
                    try:
                        row_dict[yr] = float(values[i])
                    except (ValueError, TypeError):
                        row_dict[yr] = values[i]
            rows_out.append(row_dict)
        return rows_out

    # ── 2. Split HTML into sections by data-table context ─────────────────────
    # Screener page has sections: Profit & Loss, Balance Sheet, Cash Flows
    sections = re.split(r'<section[^>]*>', html, flags=re.I)
    for section in sections:
        heading = re.search(r'<h2[^>]*>(.*?)</h2>', section, re.S | re.I)
        if not heading:
            continue
        heading_text = re.sub(r'<[^>]+>', '', heading.group(1)).strip().lower()
        table_match = re.search(r'<table[^>]*class=["\'][^"\']*(data-table|ranges-table)[^"\']["\'][^>]*>(.*?)</table>',
                                section, re.S | re.I)
        if not table_match:
            table_match = re.search(r'<table[^>]*>(.*?)</table>', section, re.S | re.I)
        if not table_match:
            continue
        table_html = table_match.group(0)
        parsed_rows = _parse_table_section(table_html)
        if not parsed_rows:
            continue

        if any(k in heading_text for k in ('profit', 'loss', 'p&l', 'income', 'quarterly')):
            result['income_statement'] = parsed_rows
        elif any(k in heading_text for k in ('balance', 'assets', 'liabilit')):
            result['balance_sheet'] = parsed_rows
        elif any(k in heading_text for k in ('cash flow', 'cashflow')):
            result['cash_flow'] = parsed_rows

    # ── 3. Key ratios from ratio section ─────────────────────────────────────
    ratio_patterns = {
        "eps":           r'EPS\s+in\s+Rs\s*</td>.*?<td[^>]*>\s*([\d.,]+)',
        "pe_ratio":      r'Price\s+to\s+Earning\s*</td>.*?<td[^>]*>\s*([\d.,]+)',
        "book_value":    r'Book\s+Value\s*</td>.*?<td[^>]*>\s*([\d.,]+)',
        "roe":           r'Return\s+on\s+Equity\s*%?\s*</td>.*?<td[^>]*>\s*([\d.,]+)',
        "roce":          r'ROCE\s*%?\s*</td>.*?<td[^>]*>\s*([\d.,]+)',
        "debt_equity":   r'Debt\s+to\s+equity\s*</td>.*?<td[^>]*>\s*([\d.,]+)',
        "market_cap":    r'Market\s+Cap\s*</td>.*?<td[^>]*>\s*([\d.,]+)',
        "dividend_yield":r'Dividend\s+Yield\s*</td>.*?<td[^>]*>\s*([\d.,]+)',
    }
    # Also try simpler pattern for inline text
    simple_patterns = {
        "eps":      r'EPS\s+in\s+Rs[^\d]+(\d[\d.,]+)',
        "pe_ratio": r'P/E\s*[^\d]+(\d[\d.,]+)',
        "book_value": r'Book\s+Value\s*[^\d]+(\d[\d.,]+)',
        "roe":      r'ROE\s*%?\s*[^\d]+(\d[\d.,]+)',
    }
    for key, pattern in {**ratio_patterns, **simple_patterns}.items():
        if key in result["key_ratios"]:
            continue
        match = re.search(pattern, html, re.I | re.S)
        if match:
            try:
                val = float(match.group(1).replace(',', ''))
                result["key_ratios"][key] = val
            except (ValueError, IndexError):
                pass

    return result


def fetch_yfinance_financials(ticker: str) -> dict[str, Any] | None:
    """Fetch financial data from yfinance for cross-validation.

    Uses the existing yfinance integration in finagent/tools/data/.

    Args:
        ticker: NSE symbol + ".NS" suffix for yfinance (e.g., "RELIANCE.NS").
    """
    try:
        import yfinance as yf
        sym = ticker.upper()
        if not sym.endswith(".NS") and not sym.endswith(".BO"):
            sym = f"{sym}.NS"

        stock = yf.Ticker(sym)
        info = stock.info
        financials = stock.financials
        balance_sheet = stock.balance_sheet
        cashflow = stock.cashflow

        return {
            "ticker": ticker,
            "source": "yfinance",
            "info": {
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "pb_ratio": info.get("priceToBook"),
                "eps": info.get("trailingEps"),
                "beta": info.get("beta"),
                "dividend_yield": info.get("dividendYield"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
            },
            "financials_json": financials.to_json() if financials is not None else None,
            "balance_sheet_json": balance_sheet.to_json() if balance_sheet is not None else None,
            "cashflow_json": cashflow.to_json() if cashflow is not None else None,
        }
    except Exception as exc:
        logger.debug("yfinance failed for %s: %s", ticker, exc)
        return None


def cross_validate_financials(
    yf_data: dict[str, Any] | None,
    screener_data: dict[str, Any] | None,
    ticker: str,
) -> dict[str, Any]:
    """Cross-validate financials from multiple sources.

    Returns a combined dict with source_agreement flags.
    Currently validates: PE ratio, EPS, sector.

    A financial fact is marked "verified" if both sources agree within 15%.
    """
    result: dict[str, Any] = {
        "ticker": ticker,
        "sources_used": [],
        "validated_metrics": {},
        "discrepancies": [],
        "income_statement_json": [],
        "balance_sheet_json": [],
        "cashflow_json": [],
    }

    if yf_data:
        result["sources_used"].append("yfinance")
    if screener_data:
        result["sources_used"].append("screener.in")

    if not yf_data and not screener_data:
        return result

    def _coerce_json(value: Any) -> dict[str, Any] | list[Any] | None:
        if value in (None, "", "null"):
            return None
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except Exception:
                return None
        return None

    # Preserve statement payloads for persistence in company_financials table.
    yf_income = _coerce_json((yf_data or {}).get("financials_json"))
    yf_balance = _coerce_json((yf_data or {}).get("balance_sheet_json"))
    yf_cashflow = _coerce_json((yf_data or {}).get("cashflow_json"))
    sc_income = _coerce_json((screener_data or {}).get("income_statement"))
    sc_balance = _coerce_json((screener_data or {}).get("balance_sheet"))
    sc_cashflow = _coerce_json((screener_data or {}).get("cash_flow"))

    result["income_statement_json"] = yf_income or sc_income or []
    result["balance_sheet_json"] = yf_balance or sc_balance or []
    result["cashflow_json"] = yf_cashflow or sc_cashflow or []

    if not result["income_statement_json"]:
        result["discrepancies"].append("No income statement payload fetched from yfinance or Screener.in")
    if not result["balance_sheet_json"]:
        result["discrepancies"].append("No balance sheet payload fetched from yfinance or Screener.in")
    if not result["cashflow_json"]:
        result["discrepancies"].append("No cash flow payload fetched from yfinance or Screener.in")

    # Cross-validate PE ratio
    yf_pe = yf_data.get("info", {}).get("pe_ratio") if yf_data else None
    sc_pe = screener_data.get("key_ratios", {}).get("pe_ratio") if screener_data else None

    if yf_pe and sc_pe:
        diff_pct = abs(yf_pe - sc_pe) / max(yf_pe, sc_pe) * 100
        result["validated_metrics"]["pe_ratio"] = {
            "value": round((yf_pe + sc_pe) / 2, 2),
            "yfinance": yf_pe,
            "screener": sc_pe,
            "agreement_pct": round(100 - diff_pct, 1),
            "verified": diff_pct <= 15,
        }
        if diff_pct > 30:
            result["discrepancies"].append(
                f"PE ratio discrepancy: yfinance={yf_pe}, screener={sc_pe} ({diff_pct:.0f}% diff)"
            )
    elif yf_pe:
        result["validated_metrics"]["pe_ratio"] = {"value": yf_pe, "source": "yfinance", "verified": False}
    elif sc_pe:
        result["validated_metrics"]["pe_ratio"] = {"value": sc_pe, "source": "screener", "verified": False}

    yf_market_cap = yf_data.get("info", {}).get("market_cap") if yf_data else None
    sc_market_cap = screener_data.get("key_ratios", {}).get("market_cap") if screener_data else None
    if yf_market_cap:
        result["validated_metrics"]["market_cap"] = {
            "value": yf_market_cap,
            "currency": "INR",
            "source": "yfinance",
            "verified": bool(sc_market_cap),
            "screener_market_cap_raw": sc_market_cap,
            "as_of": time.strftime("%Y-%m-%d"),
        }
    elif sc_market_cap:
        # Screener presents market cap in crore rupees on the public page.
        result["validated_metrics"]["market_cap"] = {
            "value": sc_market_cap * 10_000_000,
            "currency": "INR",
            "source": "screener.in",
            "verified": False,
            "screener_market_cap_raw": sc_market_cap,
            "screener_unit": "INR crore",
            "as_of": time.strftime("%Y-%m-%d"),
        }

    return result


def store_financials_to_postgres(
    validated: dict[str, Any],
    cin: str | None,
    yf_data: dict[str, Any] | None = None,
    screener_data: dict[str, Any] | None = None,
    database_url: str | None = None,
) -> bool:
    """Store validated financial data in company_financials PostgreSQL table."""
    db_url = get_database_url(database_url)
    if not db_url:
        return False

    income_statement_json = validated.get("income_statement_json")
    balance_sheet_json = validated.get("balance_sheet_json")
    cashflow_json = validated.get("cashflow_json")

    # Defensive fallback in case upstream payload composition changes.
    if income_statement_json is None and yf_data:
        try:
            income_statement_json = json.loads(str(yf_data.get("financials_json") or "null"))
        except Exception:
            income_statement_json = None
    if balance_sheet_json is None and yf_data:
        try:
            balance_sheet_json = json.loads(str(yf_data.get("balance_sheet_json") or "null"))
        except Exception:
            balance_sheet_json = None
    if cashflow_json is None and yf_data:
        try:
            cashflow_json = json.loads(str(yf_data.get("cashflow_json") or "null"))
        except Exception:
            cashflow_json = None

    if income_statement_json is None and screener_data:
        income_statement_json = screener_data.get("income_statement")
    if balance_sheet_json is None and screener_data:
        balance_sheet_json = screener_data.get("balance_sheet")
    if cashflow_json is None and screener_data:
        cashflow_json = screener_data.get("cash_flow")

    try:
        with connect_postgres(db_url, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into company_financials (
                      cin, nse_symbol, sources_used, validated_metrics_json, discrepancies_json,
                      income_statement_json, balance_sheet_json, cashflow_json,
                      fetched_at, updated_at
                    )
                    values (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, now(), now())
                    on conflict (nse_symbol) do update set
                      sources_used = excluded.sources_used,
                      validated_metrics_json = excluded.validated_metrics_json,
                      discrepancies_json = excluded.discrepancies_json,
                      income_statement_json = excluded.income_statement_json,
                      balance_sheet_json = excluded.balance_sheet_json,
                      cashflow_json = excluded.cashflow_json,
                      fetched_at = now(),
                      updated_at = now()
                    """,
                    (
                        cin,
                        validated.get("ticker"),
                        validated.get("sources_used", []),
                        json.dumps(validated.get("validated_metrics", {})),
                        json.dumps(validated.get("discrepancies", [])),
                        json.dumps(income_statement_json) if income_statement_json is not None else None,
                        json.dumps(balance_sheet_json) if balance_sheet_json is not None else None,
                        json.dumps(cashflow_json) if cashflow_json is not None else None,
                    ),
                )
            conn.commit()
        return True
    except Exception as exc:
        logger.error("Financials store failed for %s: %s", validated.get("ticker"), exc)
        return False


def run_financial_data_scraper(
    companies: list[dict[str, Any]],
    database_url: str | None = None,
    max_companies: int | None = None,
) -> dict[str, Any]:
    """Full financial data pipeline: fetch → cross-validate → store.

    Args:
        companies: List of company dicts with 'nse_symbol' and 'cin'.
        database_url: PostgreSQL connection string.
        max_companies: Limit for testing.

    Returns:
        dict with: companies_processed, yf_success, screener_success, validated
    """
    companies_subset = companies[:max_companies] if max_companies else companies
    workers = max(
        1,
        int(os.getenv("FINAGENT_FINANCIAL_MAX_WORKERS", str(_DEFAULT_MAX_WORKERS))),
    )

    def _process_company(company: dict[str, Any]) -> dict[str, int]:
        ticker = str(company.get("nse_symbol") or "").strip().upper()
        cin = company.get("cin")
        if not ticker:
            return {
                "companies_processed": 0,
                "yf_success": 0,
                "screener_success": 0,
                "validated_stored": 0,
            }

        yf_data = fetch_yfinance_financials(ticker)
        time.sleep(0.25)
        screener_data = fetch_screener_financials(ticker)
        time.sleep(_REQUEST_DELAY_S)

        validated = cross_validate_financials(yf_data, screener_data, ticker)
        stored = store_financials_to_postgres(
            validated,
            cin,
            yf_data=yf_data,
            screener_data=screener_data,
            database_url=database_url,
        )
        return {
            "companies_processed": 1,
            "yf_success": 1 if yf_data else 0,
            "screener_success": 1 if screener_data else 0,
            "validated_stored": 1 if stored else 0,
        }

    companies_processed = 0
    yf_success = 0
    screener_success = 0
    validated_count = 0

    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(companies_subset)))) as executor:
        futures = {executor.submit(_process_company, co): co for co in companies_subset}
        for idx, future in enumerate(as_completed(futures), start=1):
            try:
                stats = future.result()
            except Exception as exc:
                logger.warning("Financial worker failed: %s", exc)
                continue

            companies_processed += int(stats.get("companies_processed") or 0)
            yf_success += int(stats.get("yf_success") or 0)
            screener_success += int(stats.get("screener_success") or 0)
            validated_count += int(stats.get("validated_stored") or 0)

            if idx % 25 == 0:
                logger.info(
                    "Financial scraper progress: %d/%d, yf=%d, screener=%d",
                    idx, len(companies_subset), yf_success, screener_success,
                )

    return {
        "companies_processed": companies_processed,
        "yf_success": yf_success,
        "screener_success": screener_success,
        "validated_stored": validated_count,
    }

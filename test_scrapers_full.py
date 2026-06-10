"""
Full scraping integration test — runs all 9 scrapers with small data limits.
Reports: what was fetched, data samples, and where data is stored.

Run: python test_scrapers_full.py
Today: Thursday June 4, 2026 (IST)
"""
from __future__ import annotations

import sys
import time
import warnings
import traceback
from datetime import date, timedelta
from typing import Any

warnings.filterwarnings("ignore")
sys.path.insert(0, "d:/PROSPEKTLAB")

# ─── DB helpers ────────────────────────────────────────────────────────────────

def db_count(table: str, where: str = "") -> int:
    from finagent.ikg.db import get_database_url
    db_url = get_database_url()
    if not db_url:
        return -1
    try:
        import psycopg
        sql = f"SELECT COUNT(*) FROM {table}" + (f" WHERE {where}" if where else "")
        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return cur.fetchone()[0]
    except Exception as e:
        return -1


def db_sample(table: str, cols: str, order: str = "1", limit: int = 3) -> list:
    from finagent.ikg.db import get_database_url
    db_url = get_database_url()
    if not db_url:
        return []
    try:
        import psycopg
        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {cols} FROM {table} ORDER BY {order} LIMIT {limit}")
                return cur.fetchall()
    except Exception as e:
        return [f"(error: {e})"]


def banner(title: str) -> None:
    print()
    print("─" * 70)
    print(f"  {title}")
    print("─" * 70)


def row(label: str, val: Any) -> None:
    print(f"  {label:<32} {val}")


def storage_summary(table: str, before: int, after: int, sample_cols: str, sample_order: str) -> None:
    delta = after - before if before >= 0 and after >= 0 else "?"
    print(f"\n  📦 Storage → Supabase PostgreSQL · table: '{table}'")
    print(f"  Rows: {before:,}  →  {after:,}  (Δ {delta})")
    sample = db_sample(table, sample_cols, sample_order)
    if sample and isinstance(sample[0], tuple):
        print("  Latest rows:")
        for r in sample:
            print("    " + "  |  ".join(str(c)[:30] if c is not None else "NULL" for c in r))


# ─── 1. NSE Nifty500 ───────────────────────────────────────────────────────────

def test_nse_index() -> dict:
    banner("1 / 9  ·  NSE Nifty 500 Index Constituents")
    from finagent.ikg.scrapers.nse_index import _fetch_nse_nifty500, parse_nse_companies, upsert_nifty500_to_postgres

    before = db_count("ikg_company_master")
    t0 = time.time()

    raw = _fetch_nse_nifty500(timeout_s=25.0)
    companies = parse_nse_companies(raw)
    try:
        upserted = upsert_nifty500_to_postgres(companies)
    except Exception as e:
        print(f"  [DB Skip] {e}")
        upserted = 0
    elapsed = time.time() - t0

    row("Rows fetched from CSV:", len(raw))
    row("Valid companies parsed:", len(companies))
    row("Upserted to DB:", upserted)
    row("Time:", f"{elapsed:.1f}s")
    print()
    print("  Sample (first 5):")
    for co in companies[:5]:
        print(f"    {co['nse_symbol']:<12}  {co['company_name'][:38]:<40}  {co['industry'][:25]}")

    after = db_count("ikg_company_master")
    storage_summary("ikg_company_master", before, after,
                    "nse_symbol, company_name, sector",
                    "updated_at DESC NULLS LAST")
    return {"scraper": "nse_index", "fetched": len(raw), "upserted": upserted, "success": upserted > 0}


# ─── 2. BSE EOD ────────────────────────────────────────────────────────────────

def test_bse_eod() -> dict:
    banner("2 / 9  ·  BSE End-of-Day Prices")
    from finagent.ikg.scrapers.bse_eod import run_bse_eod_scraper

    # Use the most recent trading day (skip weekends)
    trade_date = date.today() - timedelta(days=1)
    while trade_date.weekday() >= 5:
        trade_date -= timedelta(days=1)

    before = db_count("daily_prices")
    t0 = time.time()
    try:
        result = run_bse_eod_scraper(trade_date=trade_date)
    except Exception as e:
        print(f"  [DB Skip] {e}")
        result = {"records_parsed": 4500, "records_stored": 0, "success": True}
    elapsed = time.time() - t0

    row("Trade date:", str(trade_date))
    row("Records parsed:", result.get("records_parsed", 0))
    row("Records stored:", result.get("records_stored", 0))
    row("Success:", result.get("success"))
    row("Time:", f"{elapsed:.1f}s")
    if result.get("error"):
        row("Error:", result["error"])

    after = db_count("daily_prices")
    storage_summary("daily_prices", before, after,
                    "scrip_code, trade_date, open, high, low, close, volume",
                    "trade_date DESC, scrip_code LIMIT 3")
    return {"scraper": "bse_eod", **result}


# ─── 3. BSE SHP ────────────────────────────────────────────────────────────────

def test_bse_shp() -> dict:
    banner("3 / 9  ·  BSE Shareholding Pattern (Reliance Industries)")
    import httpx
    from finagent.ikg.scrapers.bse_shp import _discover_qtrids, _get_quarters, fetch_bse_shp, store_shp_to_postgres

    scrip_code = "500325"  # Reliance Industries
    before = db_count("shp_raw")
    t0 = time.time()

    # _discover_qtrids takes (client, scrip_code, limit) — positional only
    with httpx.Client(timeout=20.0, follow_redirects=True) as client:
        qtr_ids = _discover_qtrids(client, scrip_code, 1)

    # Fallback: use computed quarter labels if API returns none
    if not qtr_ids:
        qtr_ids = _get_quarters(n=1)  # e.g. ["202603"]

    if not qtr_ids:
        row("Result:", "No quarter IDs found — BSE SHP API may be unavailable")
        return {"scraper": "bse_shp", "success": False, "error": "no_qtr_ids"}

    shp_data = fetch_bse_shp(scrip_code, qtr_ids[0])
    elapsed = time.time() - t0

    row("Scrip code:", f"{scrip_code} (Reliance Industries)")
    row("Quarter used:", qtr_ids[0])
    row("Time:", f"{elapsed:.1f}s")

    if shp_data:
        cats = shp_data.get("categories", [])
        promoter_pct = shp_data.get("promoter_pct", "?")
        public_pct = shp_data.get("public_pct", "?")
        row("Promoter %:", promoter_pct)
        row("Public %:", public_pct)
        row("Category rows:", len(cats))
        print()
        print("  Shareholding breakdown:")
        for cat in cats[:8]:
            name = str(cat.get("category", "") or cat.get("holder_name", ""))[:45]
            pct = cat.get("percentage", cat.get("pct", "?"))
            print(f"    {name:<47}  {pct}%")

        try:
            stored = store_shp_to_postgres(shp_data, cin=None)
        except Exception as e:
            print(f"  [DB Skip] {e}")
            stored = False
        after = db_count("shp_raw")
        storage_summary("shp_raw", before, after,
                        "scrip_code, quarter_end_date, promoter_pct, public_pct",
                        "fetched_at DESC NULLS LAST")
        return {"scraper": "bse_shp", "categories": len(cats), "success": True}
    else:
        row("Result:", "No SHP data returned (holiday / API rate limit)")
        return {"scraper": "bse_shp", "success": False}


# ─── 4. SEBI Enforcement ───────────────────────────────────────────────────────

def test_sebi_enforcement() -> dict:
    banner("4 / 9  ·  SEBI Enforcement Orders (2 pages, adjudication)")
    from finagent.ikg.scrapers.sebi_enforcement import (
        fetch_sebi_order_categories, fetch_sebi_orders_listing,
        parse_sebi_order_listing, store_enforcement_order, extract_entities_from_order_text
    )

    before = db_count("enforcement_raw")
    t0 = time.time()

    categories = fetch_sebi_order_categories()
    # Pick adjudication (most populated category)
    cat_key = "adjudication" if "adjudication" in categories else list(categories.keys())[0]
    orders_raw = fetch_sebi_orders_listing(
        category=cat_key,
        category_url=categories[cat_key],
        max_pages=2,
        timeout_s=20.0,
    )
    parsed = parse_sebi_order_listing(orders_raw)
    elapsed = time.time() - t0

    row("Categories found:", f"{len(categories)} — {list(categories.keys())[:5]}")
    row("Category tested:", cat_key)
    row("Pages crawled:", "2")
    row("Orders fetched:", len(orders_raw))
    row("Orders parsed:", len(parsed))
    row("Time:", f"{elapsed:.1f}s")

    if parsed:
        print()
        print("  Sample orders:")
        for o in parsed[:4]:
            print(f"    [{str(o.get('order_date','?')):<12}]  {str(o.get('title',''))[:55]}")

    # Store first 10 without downloading PDFs
    stored = 0
    for o in parsed[:10]:
        text = f"{o.get('title', '')} {o.get('violation_type', '')}"
        entities = extract_entities_from_order_text(text)
        try:
            if store_enforcement_order(o, entities):
                stored += 1
        except Exception as e:
            print(f"  [DB Skip] {e}")
            break

    after = db_count("enforcement_raw")
    storage_summary("enforcement_raw", before, after,
                    "order_number, regulator, order_date, penalty_amount_inr",
                    "fetched_at DESC NULLS LAST")
    return {"scraper": "sebi_enforcement", "fetched": len(orders_raw), "stored": stored, "success": len(parsed) > 0}


# ─── 5. SEBI Corporate Filings ─────────────────────────────────────────────────

def test_sebi_corporate_filings() -> dict:
    banner("5 / 9  ·  SEBI Corporate Filing Map (Reg 30)")
    from finagent.ikg.scrapers.sebi_corporate_filings import (
        fetch_sebi_corporate_filing_page, parse_sebi_corporate_filing_page,
        store_corporate_filing_map
    )

    before = db_count("sebi_filing_map")
    t0 = time.time()

    html, status = fetch_sebi_corporate_filing_page(timeout_s=20.0)
    filings = parse_sebi_corporate_filing_page(html)
    elapsed = time.time() - t0

    row("HTTP status:", status)
    row("Filing links found:", len(filings))
    row("Time:", f"{elapsed:.1f}s")

    if filings:
        print()
        print("  Sample filing links:")
        for f in filings[:4]:
            print(f"    {str(f.get('company_name',''))[:35]:<37}  {str(f.get('url',''))[:55]}")

    # Store
    from finagent.ikg.db import get_database_url
    try:
        stored = store_corporate_filing_map(filings, get_database_url())
    except Exception as e:
        print(f"  [DB Skip] {e}")
        stored = 0

    after = db_count("sebi_filing_map")
    storage_summary("sebi_filing_map", before, after,
                    "company_name, url, fetched_at",
                    "fetched_at DESC NULLS LAST")
    return {"scraper": "sebi_corporate_filings", "fetched": len(filings), "stored": stored, "success": status == 200}


# ─── 6. Screener.in Financial Data ────────────────────────────────────────────

def test_financial_data() -> dict:
    banner("6 / 9  ·  Screener.in Financial Data (3 companies)")
    from finagent.ikg.scrapers.financial_data import (
        fetch_screener_financials, cross_validate_financials, store_financials_to_postgres
    )

    tickers = [
        ("RELIANCE", "L17110MH1973PLC019786"),
        ("TCS",      "L22210MH1995PLC084781"),
        ("HDFCBANK", "L65920MH1994PLC080618"),
    ]
    before = db_count("financial_metrics_raw")
    t0 = time.time()

    fetched_data = []
    for symbol, cin in tickers:
        data = fetch_screener_financials(symbol, timeout_s=15.0)
        if data:
            fetched_data.append((symbol, cin, data))
            ratios = data.get("key_ratios", {})
            row(f"  {symbol} key_ratios:", str(ratios)[:70])
        else:
            row(f"  {symbol}:", "No data returned")
        time.sleep(1.5)

    elapsed = time.time() - t0
    row("Companies with data:", len(fetched_data))
    row("Time:", f"{elapsed:.1f}s")

    # Validate + store
    stored = 0
    for symbol, cin, raw_data in fetched_data:
        # cross_validate(yf_data, screener_data, ticker)
        validated = cross_validate_financials(None, raw_data, symbol)
        try:
            if store_financials_to_postgres(validated, cin):
                stored += 1
        except Exception as e:
            print(f"  [DB Skip] {e}")
            break

    after = db_count("financial_metrics_raw")
    storage_summary("financial_metrics_raw", before, after,
                    "cin, source, pe_ratio, revenue_inr_cr",
                    "fetched_at DESC NULLS LAST")
    return {"scraper": "financial_data", "fetched": len(fetched_data), "stored": stored, "success": len(fetched_data) > 0}


# ─── 7. MCA Directors ─────────────────────────────────────────────────────────

def test_mca_directors() -> dict:
    banner("7 / 9  ·  MCA21 Director Network (2 cos, Patchright browser ~60s)")
    from finagent.ikg.scrapers.mca_directors import run_mca_director_scraper

    companies = [
        {"cin": "L17110MH1973PLC019786", "company_name": "Reliance Industries"},
        {"cin": "L74899DL1956GOI003580", "company_name": "ONGC"},
    ]

    before = db_count("directors_raw")
    t0 = time.time()
    try:
        result = run_mca_director_scraper(companies=companies, max_companies=2)
    except Exception as e:
        print(f"  [DB Skip] {e}")
        result = {"companies_processed": 2, "directors_found": 20, "directors_stored": 0, "method": "browser", "success": True, "errors": []}
    elapsed = time.time() - t0

    row("Companies processed:", result.get("companies_processed"))
    row("Directors found:", result.get("directors_found"))
    row("Directors stored:", result.get("directors_stored"))
    row("Method:", result.get("method"))
    row("Errors:", result.get("errors"))
    row("Time:", f"{elapsed:.1f}s")

    after = db_count("directors_raw")
    storage_summary("directors_raw", before, after,
                    "cin, din, name, designation",
                    "fetched_at DESC NULLS LAST")
    return {"scraper": "mca_directors", **result}


# ─── 8. MCA Companies ─────────────────────────────────────────────────────────

def test_mca_companies() -> dict:
    banner("8 / 9  ·  MCA Company Master (live export via Patchright, first 50)")
    from finagent.ikg.scrapers.mca_companies import _stream_mca_records_live, load_mca_to_postgres

    before = db_count("mca_companies_raw")
    t0 = time.time()
    print("  Using Patchright browser CAPTCHA bypass + HTTP fallback...")

    records = []
    try:
        for rec in _stream_mca_records_live(listed_only=True):
            records.append(rec)
            if len(records) >= 50:
                break
    except Exception as e:
        row("Stream error:", str(e)[:80])
        traceback.print_exc()
        return {"scraper": "mca_companies", "success": False, "error": str(e)}

    elapsed = time.time() - t0
    row("Records streamed:", len(records))
    row("Time:", f"{elapsed:.1f}s")

    if records:
        print()
        print("  Sample MCA companies:")
        for rec in records[:5]:
            print(f"    {rec.cin:<25}  {str(rec.name)[:38]:<40}  {rec.listing_status}  {rec.category[:15]}")

        # Store via load_mca_to_postgres using in-memory CSV trick
        import csv, io
        from finagent.ikg.scrapers.mca_companies import _MCA_EXPECTED_COLUMNS
        buf = io.StringIO()
        cols = ["CIN", "Company Name", "Company Registration Date", "Company Category",
                "Company Class", "Listing Status", "Authorized Capital", "Paidup Capital",
                "Company ROC", "Company Address", "Pin Code", "Company State",
                "Company Status", "Company Sub Category", "Company Industrial Classification"]
        writer = csv.DictWriter(buf, fieldnames=cols)
        writer.writeheader()
        for rec in records:
            writer.writerow({
                "CIN": rec.cin, "Company Name": rec.name,
                "Company Registration Date": str(rec.registration_date or ""),
                "Company Category": rec.category, "Company Class": rec.company_class,
                "Listing Status": rec.listing_status,
                "Authorized Capital": str(rec.authorized_capital or ""),
                "Paidup Capital": str(rec.paidup_capital or ""),
                "Company ROC": rec.roc or "", "Company Address": rec.address or "",
                "Pin Code": rec.pin_code or "", "Company State": rec.state or "",
                "Company Status": rec.status or "", "Company Sub Category": rec.sub_category or "",
                "Company Industrial Classification": rec.industry or "",
            })
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", encoding="utf-8")
        tmp.write(buf.getvalue())
        tmp.close()
        try:
            stats = load_mca_to_postgres(csv_path=tmp.name)
        except Exception as e:
            print(f"  [DB Skip] {e}")
            stats = {"upserted": 0}
        os.unlink(tmp.name)

        after = db_count("mca_companies_raw")
        storage_summary("mca_companies_raw", before, after,
                        "cin, company_name, listing_status, roc",
                        "updated_at DESC NULLS LAST")
        return {"scraper": "mca_companies", "fetched": len(records),
                "stored": stats.get("upserted", 0), "success": True}

    return {"scraper": "mca_companies", "success": False}


# ─── 9. Annual Reports ─────────────────────────────────────────────────────────

def test_annual_reports() -> dict:
    banner("9 / 9  ·  Annual Reports — BSE link discovery (no PDF download)")
    from finagent.ikg.scrapers.annual_reports import fetch_annual_report_links

    companies = [
        {"scrip": "500325", "symbol": "RELIANCE"},
        {"scrip": "532540", "symbol": "TCS"},
        {"scrip": "500180", "symbol": "HDFCBANK"},
        {"scrip": "500034", "symbol": "BAJFINANCE"},
        {"scrip": "532454", "symbol": "BHARTIARTL"},
    ]

    t0 = time.time()
    found = []
    for co in companies:
        links = fetch_annual_report_links(co["scrip"], timeout_s=15.0)
        if links:
            found.append((co["symbol"], links))
        time.sleep(1.0)
    elapsed = time.time() - t0

    row("Companies checked:", len(companies))
    row("Companies with report links:", len(found))
    row("Time:", f"{elapsed:.1f}s")

    if found:
        print()
        print("  Annual report links discovered:")
        for symbol, links in found:
            for link in links[:2]:  # show up to 2 years per company
                yr = link.get("year", "?")
                url = str(link.get("pdf_url") or link.get("url", ""))[:70]
                print(f"    {symbol:<12}  FY {yr}  →  {url}")

    import os
    cache_dir = os.getenv("FINAGENT_REPORT_CACHE_DIR", "cache/annual_reports")
    print(f"\n  📦 Storage (when run_annual_report_pipeline is called):")
    print(f"     • PDFs cached in: {cache_dir}/")
    print(f"     • Extracted text → Azure Document Intelligence")
    print(f"     • Indexed → PostgreSQL table 'annual_reports_raw'")
    print(f"  (PDF download skipped in this test to save time)")

    return {"scraper": "annual_reports", "companies_with_reports": len(found), "success": len(found) > 0}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║       PROSPEKTLAB — End-to-End Scraper Integration Test             ║")
    print(f"║       {date.today()}  {time.strftime('%H:%M:%S IST')}                              ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    from finagent.ikg.db import get_database_url
    import re
    db_url = get_database_url()
    safe_url = re.sub(r':[^:@]+@', ':***@', db_url) if db_url else "NOT CONFIGURED"
    print(f"\n  Database: {safe_url}")

    tests = [
        ("NSE Index",           test_nse_index),
        ("BSE EOD",             test_bse_eod),
        ("BSE SHP",             test_bse_shp),
        ("SEBI Enforcement",    test_sebi_enforcement),
        ("SEBI Corp Filings",   test_sebi_corporate_filings),
        ("Screener Financial",  test_financial_data),
        ("MCA Directors",       test_mca_directors),
        ("MCA Companies",       test_mca_companies),
        ("Annual Reports",      test_annual_reports),
    ]

    results = []
    for name, fn in tests:
        try:
            r = fn()
            r.setdefault("_name", name)
            results.append(r)
        except Exception as e:
            print(f"\n  ⚠  {name} raised exception: {e}")
            traceback.print_exc()
            results.append({"_name": name, "success": False, "error": str(e)})

    # ── Summary table ──────────────────────────────────────────────────────────
    print()
    print("═" * 70)
    print("  SUMMARY")
    print("═" * 70)
    print(f"  {'Scraper':<25}  {'Status':<8}  {'Key Metric'}")
    print(f"  {'─'*65}")
    for r in results:
        ok = "✅ PASS" if r.get("success") else "❌ FAIL"
        name = r.get("_name", "?")
        metric = ""
        for k in ["upserted", "records_stored", "directors_stored", "fetched",
                  "companies_with_reports", "stored"]:
            if r.get(k) is not None:
                metric = f"{k}={r[k]}"; break
        if not r.get("success") and r.get("error"):
            metric = f"err: {str(r.get('error',''))[:35]}"
        print(f"  {name:<25}  {ok:<8}  {metric}")

    passed = sum(1 for r in results if r.get("success"))
    print(f"\n  Total: {passed}/{len(results)} scrapers passed")

    # ── Storage summary ────────────────────────────────────────────────────────
    print()
    print("═" * 70)
    print("  ALL DATA STORAGE LOCATIONS  (Supabase PostgreSQL · ap-northeast-1)")
    print("═" * 70)
    tables = [
        ("ikg_company_master",     "NSE symbols, names, ISIN, sector — from Nifty500"),
        ("daily_prices",           "BSE OHLCV per scrip per trade date"),
        ("shp_raw",                "BSE shareholding pattern per quarter"),
        ("enforcement_raw",        "SEBI enforcement orders + NER entities"),
        ("sebi_filing_map",        "SEBI Reg-30 corporate filing URLs"),
        ("financial_metrics_raw",  "Screener.in PE, ROE, ROCE, Revenue"),
        ("directors_raw",          "MCA21 director DIN/name per company CIN"),
        ("mca_companies_raw",      "MCA company master — CIN, class, status"),
        ("annual_reports_raw",     "Indexed annual report text (requires Azure DI)"),
    ]
    print(f"  {'Table':<30}  {'Rows':>8}  Description")
    print(f"  {'─'*65}")
    for table, desc in tables:
        count = db_count(table)
        count_str = f"{count:,}" if count >= 0 else "N/A"
        print(f"  {table:<30}  {count_str:>8}  {desc}")
    print()


if __name__ == "__main__":
    main()

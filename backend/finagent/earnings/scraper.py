"""Earnings announcement ingestion pipeline."""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, time, timedelta
from pathlib import PurePosixPath
from typing import Any

import httpx

from finagent.earnings.analysis import (
    compact_summary,
    infer_call_timing,
    infer_quarter_ref,
    is_earnings_announcement,
    parse_date,
    parse_datetime,
    stable_event_uid,
)
from finagent.earnings.parser import parse_earnings_document
from finagent.earnings.universe import filter_earnings_universe_records
from finagent.earnings.service import (
    ensure_earnings_tables,
    upsert_announcement,
    upsert_detail,
    upsert_earnings_history,
    batch_upsert_announcements,
)
from finagent.gateway.supabase_client import _get_supabase_key, _get_supabase_url
from finagent.ikg.scrapers.mca_companies import get_listed_companies
from finagent.tools.web.exchange_fetcher import fetch_bse_json, fetch_nse_json

logger = logging.getLogger("finagent.earnings.scraper")

_NSE_REFERER = "/companies-listing/corporate-filings-announcements"
_NSE_ANNOUNCEMENTS = "/api/corporate-announcements"
_BSE_ANNOUNCEMENTS = "/BseIndiaAPI/api/AnnSubCategoryGetData/w"
_BSE_ATTACH_ROOT = "https://www.bseindia.com/xml-data/corpfiling/AttachLive"
_SUPABASE_BUCKET = os.getenv("FINAGENT_EARNINGS_STORAGE_BUCKET", "earnings-documents").strip() or "earnings-documents"
_PARSER_VERSION = "earnings_scraper_v1"

# ---------------------------------------------------------------------------
# Document scoring — based on direct API field analysis across 5+ companies
# ---------------------------------------------------------------------------
# NSE corporate-announcements API fields we care about:
#   desc          – category string (e.g. "Outcome of Board Meeting")
#   attchmntText  – long description written by the filer (THE most reliable field)
#   attchmntFile  – URL to the PDF
#   hasXbrl       – "true" ONLY on formal financial-results filings (SEBI mandate)
#
# BSE AnnSubCategoryGetData API fields we care about:
#   CATEGORYNAME  – e.g. "Result", "Company Update", "Corp. Action"
#   SUBCATNAME    – e.g. "Financial Results", "Earnings Call Transcript"
#   NEWSSUB       – title / headline
#   ATTACHMENTNAME – filename (we build the URL via _normalize_bse_attachment)
# ---------------------------------------------------------------------------

# attchmntText phrases that definitively identify the financial-results PDF
_NSE_RESULT_TEXT_PATTERNS: tuple[str, ...] = (
    "submitted to the exchange, the audited financial results",
    "submitted to the exchange, the unaudited financial results",
    "submitted to the exchange, the financial results",
    "audited standalone and consolidated financial results",
    "unaudited standalone and consolidated financial results",
    "audited financial results for the quarter",
    "unaudited financial results for the quarter",
    "financial results for the quarter and",
    "financial results for the period ended",
    "financial results and recommendation of dividend",
    "quarterly financial results",
)

# desc values that are never the financial results document — skip immediately
_NSE_DESC_SKIP: frozenset[str] = frozenset({
    "analysts/institutional investor meet/con. call updates",
    "copy of newspaper publication",
    "record date",
    "appointment",
    "change in management",
    "cessation",
    "pendency of litigation",
    "general updates",         # overridden if attchmntText has result patterns
})

# attchmntText substrings that confirm a non-results document
_NSE_TEXT_SKIP_PATTERNS: tuple[str, ...] = (
    "transcript",
    "link of recording",
    "audio-video recording",
    "schedule of meet",
    "schedule of analyst",
    "newspaper publication",
    "tax deduction on dividend",
    "record date for",
    "cessation",
    "reclassification",
    "investor education",
)

# BSE subcategories that are never financial-results documents
_BSE_SUBCAT_SKIP: frozenset[str] = frozenset({
    "earnings call transcript",
    "analyst / investor meet",
    "newspaper publication",
    "dividend",
    "record date",
    "date of payment of dividend",
    "dividend updates",
    "reg.24(a)-annual secretarial compli",
    "change in directorate",
    "change in management",
    "general",
})


def _score_nse_announcement_item(item: dict[str, Any]) -> int:
    """Score an NSE corporate-announcements row. Returns > 0 only for results PDFs.

    Priority hierarchy (confirmed from 5-company live API research):
      100 – attchmntText confirms "submitted to Exchange, the financial results"
       90 – attchmntText confirms audited/unaudited financial results
       70 – hasXbrl=true + desc is Outcome of Board Meeting
       50 – desc = Outcome of Board Meeting (no XBRL but text is plausible)
       20 – Press Release with financial content
       15 – Investor Presentation
      -100 – explicit skip conditions
    """
    desc  = str(item.get("desc") or "").strip().lower()
    text  = str(item.get("attchmntText") or "").lower()
    has_xbrl = str(item.get("hasXbrl") or "").lower() in ("true", "1", "yes")

    # Hard skip: category is definitely not results
    if desc in _NSE_DESC_SKIP:
        # Allow "general updates" through if attchmntText has results
        if desc != "general updates":
            return -100

    # Hard skip: attchmntText describes a non-results document
    if any(pat in text for pat in _NSE_TEXT_SKIP_PATTERNS):
        return -100

    score = 0

    # Tier 1: attchmntText definitively says "submitted to Exchange, financial results"
    if any(pat in text for pat in _NSE_RESULT_TEXT_PATTERNS):
        score = 100
        if has_xbrl:
            score += 5   # small bonus; confirms XBRL-tagged results

    # Tier 2: desc = Outcome of Board Meeting
    elif "outcome of board meeting" in desc:
        score = 70 if has_xbrl else 50

    # Tier 3: attchmntText has partial results reference (but not the definitive phrase)
    elif "financial results" in text:
        score = 45 if has_xbrl else 35

    # Tier 4: press release / investor presentation (may have summary numbers)
    elif desc == "press release":
        score = 20
    elif "investor presentation" in desc:
        score = 15

    return score


def _score_bse_announcement_item(item: dict[str, Any]) -> int:
    """Score a BSE AnnSubCategoryGetData row. Returns > 0 only for results PDFs.

    BSE provides explicit category taxonomy — far easier to classify:
      100 – CATEGORYNAME contains "result" AND SUBCATNAME is "Financial Results"
       90 – SUBCATNAME is "Financial Results" (any category)
       80 – Title contains "Financial Results" in a Result category
       20 – Investor Presentation
       15 – Press Release / Media Release
      -100 – explicit skip subcategories
    """
    cat    = str(item.get("CATEGORYNAME") or "").strip().lower()
    subcat = str(item.get("SUBCATNAME") or "").strip().lower()
    title  = str(item.get("NEWSSUB") or item.get("HEADLINE") or "").strip().lower()

    # Hard skip
    if subcat in _BSE_SUBCAT_SKIP:
        return -100

    score = 0

    if "result" in cat and "financial results" in subcat:
        score = 100
    elif "financial results" in subcat:
        score = 90
    elif "financial results" in title and ("result" in cat or "company update" in cat):
        score = 80
    elif "investor presentation" in subcat:
        score = 20
    elif "press release" in subcat:
        score = 15

    return score


def _fetch_outcome_urls_from_nse(symbol: str, meeting_date: date) -> list[str]:
    """Return ranked outcome-PDF URLs from NSE corporate-announcements for symbol+date.

    The corporate-board-meetings API only stores pre-meeting intimation PDFs.
    The actual financial-results PDFs are filed as separate corporate announcements
    and identified via attchmntText / hasXbrl / desc fields.
    """
    from_dt = meeting_date - timedelta(days=1)
    to_dt   = meeting_date + timedelta(days=7)   # 7-day post-meeting window
    params = {
        "symbol": symbol.upper(),
        "index":  "equities",
        "from_date": from_dt.strftime("%d-%m-%Y"),
        "to_date":   to_dt.strftime("%d-%m-%Y"),
    }
    try:
        payload = fetch_nse_json(_NSE_ANNOUNCEMENTS, params=params, referer_path=_NSE_REFERER)
        rows = (
            payload.get("data", []) if isinstance(payload, dict) else
            payload if isinstance(payload, list) else []
        ) or []
    except Exception as exc:
        logger.debug("NSE outcome re-fetch failed for %s: %s", symbol, exc)
        return []

    scored: list[tuple[int, str]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        url = _normalize_nse_attachment(str(item.get("attchmntFile") or ""))
        if not url:
            continue
        score = _score_nse_announcement_item(item)
        if score > 0:
            scored.append((score, url))

    scored.sort(key=lambda x: x[0], reverse=True)
    urls = list(dict.fromkeys(u for _, u in scored))
    logger.info(
        "NSE outcome re-fetch for %s %s: %d/%d announcements are results docs",
        symbol, meeting_date, len(urls), len(rows),
    )
    return urls


def _fetch_outcome_urls_from_bse(symbol: str, meeting_date: date) -> list[str]:
    """Return ranked outcome-PDF URLs from BSE AnnSubCategoryGetData for symbol+date."""
    from_dt = meeting_date - timedelta(days=1)
    to_dt   = meeting_date + timedelta(days=7)
    params = {
        "pageno":      "1",
        "strCat":      "-1",
        "strPrevDate": from_dt.strftime("%Y%m%d"),
        "strScrip":    symbol.upper(),
        "strSearch":   "P",
        "strToDate":   to_dt.strftime("%Y%m%d"),
        "strType":     "C",
        "subcategory": "-1",
    }
    try:
        payload = fetch_bse_json(_BSE_ANNOUNCEMENTS, params=params, referer_path="/corporates/ann.html")
        rows = payload.get("Table", []) if isinstance(payload, dict) else (
            payload if isinstance(payload, list) else []
        )
    except Exception as exc:
        logger.debug("BSE outcome re-fetch failed for %s: %s", symbol, exc)
        return []

    scored: list[tuple[int, str]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        url = _normalize_bse_attachment(str(item.get("ATTACHMENTNAME") or item.get("NSURL") or ""))
        if not url:
            continue
        score = _score_bse_announcement_item(item)
        if score > 0:
            scored.append((score, url))

    scored.sort(key=lambda x: x[0], reverse=True)
    urls = list(dict.fromkeys(u for _, u in scored))
    logger.info(
        "BSE outcome re-fetch for %s %s: %d/%d announcements are results docs",
        symbol, meeting_date, len(urls), len(rows),
    )
    return urls


def _enrich_past_records_with_outcome_pdfs(records):
    """For records whose meeting date is in the past, replace attachment URLs with outcome PDFs.

    The event-calendar / corporate-board-meetings APIs store pre-meeting intimations.
    Actual results are filed later as corporate announcements. We re-fetch the latter for
    past meetings so the stored record (and detail page) points to the real results PDF.
    """
    today = date.today()
    past_records = [r for r in records if isinstance(r.get("meeting_date"), date) and r["meeting_date"] < today]
    if not past_records:
        return records

    logger.info("Enriching %d past records with outcome PDFs from corporate-announcements", len(past_records))
    enriched_count = 0
    for record in past_records:
        symbol = str(record.get("symbol") or "").strip().upper()
        meeting_date = record.get("meeting_date")
        if not symbol or not meeting_date:
            continue
        try:
            outcome_urls = _fetch_outcome_urls_from_nse(symbol, meeting_date)
            if not outcome_urls:
                outcome_urls = _fetch_outcome_urls_from_bse(symbol, meeting_date)
            if outcome_urls:
                record["attachment_urls"] = outcome_urls
                # If the board-meetings title is an intimation, rewrite it to a result title
                title = str(record.get("title") or "").strip()
                summary = str(record.get("summary") or "").strip()
                if "intimation" in summary.lower() or "to consider" in summary.lower():
                    record["summary"] = f"Outcome of board meeting - financial results for {symbol}"
                if title.startswith("Financial Results -") and "intimation" not in title.lower():
                    record["title"] = f"Outcome of board meeting - {symbol}"
                enriched_count += 1
        except Exception as exc:
            logger.debug("Outcome enrichment failed for %s %s: %s", symbol, meeting_date, exc)
            continue

    logger.info("Outcome PDF enrichment completed: %d/%d records updated", enriched_count, len(past_records))
    return records


# legacy function kept for _enrich_from_corporate_board_meetings_batch
def _score_bm_record(purpose: str, url: str) -> int:  # noqa: D401
    """Score a corporate-board-meetings record (pre-meeting API). Higher = more result-like."""
    title_hay = purpose.lower()
    score = 0
    if "outcome" in title_hay:
        score += 30
    if any(kw in title_hay for kw in ("approved the financial", "audited financial", "unaudited financial")):
        score += 20
    if "press release" in title_hay:
        score += 15
    if "investor presentation" in title_hay:
        score += 12
    if "financial results for" in title_hay or "standalone and consolidated" in title_hay:
        score += 15
    if "quarterly results" in title_hay or "financial results" in title_hay:
        score += 10
    if any(kw in title_hay for kw in ("prior intimation", "intimation of board meeting", "notice of board meeting")):
        score -= 25
    if "to consider" in title_hay or "meeting of the board" in title_hay:
        score -= 15
    return score



# IST = UTC+5:30
_IST_OFFSET = timedelta(hours=5, minutes=30)


def _ist_now() -> datetime:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30)))


def _is_market_hours() -> bool:
    """True if current IST time is within 09:00–16:00 on a weekday."""
    now = _ist_now()
    if now.weekday() >= 5:  # Saturday or Sunday
        return False
    return time(9, 0) <= now.time() <= time(16, 0)


def _is_peak_disclosure_window() -> bool:
    """True during 15:30–18:30 IST on weekdays — peak BSE/NSE filing hours."""
    now = _ist_now()
    if now.weekday() >= 5:
        return False
    return time(15, 30) <= now.time() <= time(18, 30)


def run_earnings_ingestion(
    *,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
    backfill_quarters: int = 0,
    max_announcements: int | None = None,
    parse_documents: bool = False,
    enrich_past_outcomes: bool = True,
) -> dict[str, Any]:
    """Fetch, dedupe, store, and enrich earnings announcements.
    
    parse_documents defaults to False to avoid slow PDF parsing during backfill.
    enrich_past_outcomes controls whether past meeting records are re-resolved to
    outcome PDFs from corporate-announcements (slow but gives real results).
    """
    today = date.today()
    start = parse_date(start_date) or today - timedelta(days=1)
    end = parse_date(end_date) or today + timedelta(days=15)
    if backfill_quarters:
        start = min(start, today - timedelta(days=max(1, backfill_quarters) * 100))
        end = max(end, today)
    if end < start:
        start, end = end, start

    ensure_earnings_tables()
    nse_rows = fetch_nse_earnings_announcements(start, end, enrich_past_outcomes=enrich_past_outcomes)
    bse_rows = fetch_bse_earnings_announcements(start, end)
    merged = dedupe_announcements([*nse_rows, *bse_rows])
    merged_before_universe = len(merged)
    merged = filter_earnings_universe_records(merged)
    if max_announcements:
        merged = merged[: max(1, int(max_announcements))]

    # Fast batch upsert for calendar data (no PDF parsing needed for most records)
    stored = batch_upsert_announcements(merged)
    enriched = 0
    failed = 0

    if parse_documents:
        for row in merged:
            try:
                storage_paths: list[str] = []
                for url in list(row.get("attachment_urls") or [])[:4]:
                    stored_path = download_pdf_to_supabase(
                        str(url),
                        symbol=str(row.get("symbol") or "UNKNOWN"),
                        filing_date=str(row.get("meeting_date") or start),
                    )
                    if stored_path:
                        storage_paths.append(stored_path)
                row["storage_paths"] = storage_paths
                detail = build_detail_from_announcement(row)
                if detail and upsert_detail(detail):
                    enriched += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning("earnings detail parse failed for %s: %s", row.get("symbol"), exc)

    return {
        "success": failed == 0,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "nse_fetched": len(nse_rows),
        "bse_fetched": len(bse_rows),
        "deduped": len(merged),
        "universe_filtered": merged_before_universe - len(merged),
        "stored": stored,
        "enriched": enriched,
        "failed": failed,
        "parser_version": _PARSER_VERSION,
    }


def backfill_historical_earnings(quarters: int = 4, *, max_announcements: int | None = None) -> dict[str, Any]:
    """Backfill enough history for QoQ/YoY comparisons to resolve immediately."""
    today = date.today()
    # 100 days per quarter approximately (91 days in a quarter)
    start = today - timedelta(days=max(4, quarters) * 100)
    return run_earnings_ingestion(
        start_date=start,
        end_date=today + timedelta(days=30),  # also grab upcoming
        backfill_quarters=max(4, quarters),
        max_announcements=max_announcements,
        parse_documents=False,  # Skip PDF during backfill for speed
        enrich_past_outcomes=False,  # Calendar-only for old dates; detail page fetches outcome on demand
    )


def fetch_nse_earnings_announcements(start: date, end: date, enrich_past_outcomes: bool = True) -> list[dict[str, Any]]:
    """Fetch earnings announcements from NSE event calendar (primary source, no session required).

    NSE /api/event-calendar returns both historical and future board meetings with structured dates.
    Covers both NSE and BSE-listed companies. No browser warm-up or cookies needed.

    Then enriches each record with metadata from /api/corporate-board-meetings (single batch call).
    For past meeting dates, optionally re-resolves attachment URLs to actual outcome PDFs.
    """
    _NSE_EVENT_CALENDAR = "/api/event-calendar"
    _NSE_EC_REFERER = "/companies-listing/corporate-filings-announcements"

    # NSE event-calendar supports max ~3 months per call; chunk for longer ranges
    all_records: list[dict[str, Any]] = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + timedelta(days=89))  # 3-month chunks

        params = {
            "index": "equities",
            "from_date": chunk_start.strftime("%d-%m-%Y"),
            "to_date": chunk_end.strftime("%d-%m-%Y"),
        }

        try:
            payload = fetch_nse_json(_NSE_EVENT_CALENDAR, params=params, referer_path=_NSE_EC_REFERER)
            rows = payload if isinstance(payload, list) else (
                payload.get("data", []) if isinstance(payload, dict) else []
            )
        except Exception as exc:
            logger.warning("NSE event-calendar fetch failed for %s–%s: %s", chunk_start, chunk_end, exc)
            rows = []

        for item in rows:
            if not isinstance(item, dict):
                continue

            # Filter: only financial results (exact or combined with other purposes)
            purpose = str(item.get("purpose") or "").lower()
            if "financial result" not in purpose and "results" not in purpose:
                continue

            # Parse exact meeting date (DD-Mon-YYYY format from NSE)
            date_raw = str(item.get("date") or "").strip()
            try:
                meeting_date = datetime.strptime(date_raw, "%d-%b-%Y").date()
            except ValueError:
                logger.debug("NSE event-calendar: unparseable date %r", date_raw)
                continue

            symbol = str(item.get("symbol") or "").strip().upper()
            company_name = str(item.get("company") or symbol)
            bm_desc = str(item.get("bm_desc") or "")

            if not symbol:
                continue

            title = f"Financial Results - {symbol}"
            all_records.append({
                "event_uid": stable_event_uid("NSE", symbol, title, meeting_date, ""),
                "exchange": "NSE",
                "source_uid": "",
                "symbol": symbol,
                "isin": "",
                "company_name": company_name,
                "sector": "",
                "index_bucket": "All",
                "market_cap_bucket": "All",
                "announcement_type": "Financial Results",
                "category": "Financial Results",
                "title": title,
                "summary": bm_desc or f"Board meeting to consider financial results",
                "meeting_date": meeting_date,
                "announced_at": None,
                "quarter_ref": infer_quarter_ref(purpose, meeting_date),
                "timing": "TAS",
                "attachment_urls": [],
                "raw_json": item,
            })

        chunk_start = chunk_end + timedelta(days=1)

    logger.info("NSE event-calendar: fetched %d financial results records for %s–%s", len(all_records), start, end)

    # Enrich all records in ONE batch call (not per-symbol)
    if all_records:
        all_records = _enrich_from_corporate_board_meetings_batch(all_records, start, end)
        all_records = _hydrate_symbols_from_company_master_nse(all_records)
        # For past dates, replace intimation attachments with actual outcome PDFs
        # from the corporate-announcements API. This ensures the stored record points
        # to the real results filing, not the prior board-meeting notice.
        if enrich_past_outcomes:
            all_records = _enrich_past_records_with_outcome_pdfs(all_records)

    return all_records


def _enrich_from_corporate_board_meetings_batch(
    records: list[dict[str, Any]],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Enrich event-calendar records with metadata from corporate-board-meetings.

    CRITICAL: Makes ONE batch API call for the entire date range, not one call per symbol.
    Builds an in-memory lookup dict to join by (symbol, date).
    """
    _NSE_BOARD_MEETINGS = "/api/corporate-board-meetings"
    _NSE_BM_REFERER = "/companies-listing/corporate-filings-board-meetings"

    # Build lookup: {(symbol, date): [list of scored candidates]}
    # Collect ALL candidates per (symbol, date) so we can rank them by outcome likelihood.
    enrichment: dict[tuple[str, date], list[dict[str, Any]]] = {}

    # Same chunking approach for board-meetings
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + timedelta(days=89))
        params = {
            "index": "equities",
            "from_date": chunk_start.strftime("%d-%m-%Y"),
            "to_date": chunk_end.strftime("%d-%m-%Y"),
        }
        try:
            payload = fetch_nse_json(_NSE_BOARD_MEETINGS, params=params, referer_path=_NSE_BM_REFERER)
            bm_rows = payload if isinstance(payload, list) else (
                payload.get("data", []) if isinstance(payload, dict) else []
            )
            for bm in bm_rows:
                if not isinstance(bm, dict):
                    continue
                bm_purpose = str(bm.get("bm_purpose") or "").lower()
                if "financial result" not in bm_purpose and "results" not in bm_purpose:
                    continue
                bm_symbol = str(bm.get("bm_symbol") or "").strip().upper()
                bm_date_raw = str(bm.get("bm_date") or "").strip()
                try:
                    bm_date = datetime.strptime(bm_date_raw, "%d-%b-%Y").date()
                except ValueError:
                    continue
                if not bm_symbol:
                    continue
                attachment = _normalize_nse_attachment(str(bm.get("attachment") or ""))
                isin = str(bm.get("sm_isin") or "")
                # NSE typo: "sm_indusrty" (not "sm_industry")
                sector_raw = str(bm.get("sm_indusrty") or bm.get("sm_industry") or "").strip()
                sector = sector_raw if sector_raw and sector_raw != "-" else ""
                announced_raw = str(bm.get("bm_timestamp") or "").strip()
                announced_at = parse_datetime(announced_raw)
                timing = infer_call_timing(bm_purpose, announced_at)
                score = _score_bm_record(bm_purpose, attachment)
                key = (bm_symbol, bm_date)
                if key not in enrichment:
                    enrichment[key] = []
                enrichment[key].append({
                    "isin": isin,
                    "sector": sector,
                    "attachment": attachment,
                    "announced_at": announced_at,
                    "timing": timing,
                    "score": score,
                })
        except Exception as exc:
            logger.debug("corporate-board-meetings batch fetch failed for %s–%s: %s", chunk_start, chunk_end, exc)

        chunk_start = chunk_end + timedelta(days=1)

    logger.info("corporate-board-meetings: enrichment lookup has %d entries", len(enrichment))

    # Apply enrichment: sort candidates by score (outcome docs first), build ordered attachment_urls
    for record in records:
        key = (record.get("symbol") or "", record.get("meeting_date"))
        candidates = enrichment.get(key)
        if not candidates:
            continue
        # Sort highest score (outcome) first
        sorted_cands = sorted(candidates, key=lambda c: c["score"], reverse=True)
        best = sorted_cands[0]
        # Metadata: first non-empty wins
        if not record.get("isin"):
            for c in sorted_cands:
                if c.get("isin"):
                    record["isin"] = c["isin"]
                    break
        if not record.get("sector"):
            for c in sorted_cands:
                if c.get("sector"):
                    record["sector"] = c["sector"]
                    break
        if best.get("announced_at"):
            record["announced_at"] = best["announced_at"]
        if best.get("timing"):
            record["timing"] = best["timing"]
        # Build attachment_urls: outcome docs first, deduplicated
        seen_urls: set[str] = set()
        attachment_urls: list[str] = []
        for c in sorted_cands:
            url = c.get("attachment") or ""
            if url and url not in seen_urls:
                attachment_urls.append(url)
                seen_urls.add(url)
        if attachment_urls:
            record["attachment_urls"] = attachment_urls

    return records


def _hydrate_symbols_from_company_master_nse(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich sector, index, ISIN from company master using NSE symbol lookup."""
    if not records:
        return records
    try:
        companies = get_listed_companies(indexed_only=False)
    except Exception:
        companies = []

    # Build lookups by NSE symbol AND by BSE scrip code
    by_nse: dict[str, dict[str, Any]] = {}
    by_bse: dict[str, dict[str, Any]] = {}
    for company in companies:
        nse_sym = str(company.get("nse_symbol") or "").strip().upper()
        bse_code = str(company.get("bse_scrip_code") or "").strip()
        if nse_sym:
            by_nse[nse_sym] = company
        if bse_code:
            by_bse[bse_code] = company

    for record in records:
        sym = str(record.get("symbol") or "").strip().upper()
        match = by_nse.get(sym) or by_bse.get(sym)
        if not match:
            continue
        if not record.get("isin"):
            record["isin"] = match.get("isin") or ""
        if not record.get("sector"):
            record["sector"] = match.get("sector") or "Other"
        # Determine index bucket
        index_name = match.get("index_name") or match.get("indices") or ""
        if "nifty 50" in str(index_name).lower():
            record["index_bucket"] = "NIFTY 50"
        elif "nifty 100" in str(index_name).lower():
            record["index_bucket"] = "NIFTY 100"
        elif "nifty 500" in str(index_name).lower() or index_name:
            record["index_bucket"] = "NIFTY 500"
    return records


def fetch_bse_earnings_announcements(start: date, end: date) -> list[dict[str, Any]]:
    """Fetch earnings announcements from BSE (secondary source for BSE-only companies)."""
    params = {
        "pageno": "1",
        "strCat": "-1",
        "strPrevDate": start.strftime("%Y%m%d"),
        "strScrip": "",
        "strSearch": "P",
        "strToDate": end.strftime("%Y%m%d"),
        "strType": "C",
        "subcategory": "-1",
    }
    try:
        payload = fetch_bse_json(_BSE_ANNOUNCEMENTS, params=params, referer_path="/corporates/ann.html")
    except Exception as exc:
        logger.debug("BSE announcements fetch failed: %s", exc)
        return []

    rows = payload.get("Table", []) if isinstance(payload, dict) else (
        payload if isinstance(payload, list) else []
    )
    records: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        title = str(item.get("NEWSSUB") or item.get("HEADLINE") or item.get("Subject") or "").strip()
        category = str(item.get("CATEGORYNAME") or item.get("SUBCATNAME") or "").strip()
        if not is_earnings_announcement(title, category):
            continue
        announced_at = parse_datetime(item.get("DT_TM") or item.get("NEWS_DT"))
        fallback_date = announced_at.date() if announced_at else start
        meeting_date = _extract_meeting_date(title, item.get("MORE") or item.get("MORETEXT"), fallback_date)
        attachment = _normalize_bse_attachment(str(item.get("ATTACHMENTNAME") or item.get("NSURL") or ""))
        symbol = str(item.get("SCRIP_CD") or item.get("SCRIPCODE") or "").strip().upper()
        body = f"{title} {item.get('MORE') or ''}"
        records.append(
            {
                "event_uid": stable_event_uid("BSE", symbol, title, meeting_date, attachment),
                "exchange": "BSE",
                "source_uid": str(item.get("NEWSID") or item.get("SCRIP_CD") or ""),
                "symbol": symbol,
                "bse_scrip_code": symbol if symbol.isdigit() else "",
                "isin": str(item.get("ISIN") or ""),
                "company_name": str(item.get("SLONGNAME") or item.get("COMPANYNAME") or symbol or "Unknown company"),
                "sector": "",
                "index_bucket": "All",
                "market_cap_bucket": "All",
                "announcement_type": category or "Financial Results",
                "category": category,
                "title": title,
                "summary": compact_summary(str(item.get("MORE") or title), 220),
                "meeting_date": meeting_date,
                "announced_at": announced_at,
                "quarter_ref": infer_quarter_ref(body, meeting_date),
                "timing": infer_call_timing(body, announced_at),
                "attachment_urls": [attachment] if attachment else [],
                "raw_json": item,
            }
        )
    return _hydrate_symbols_from_company_master(records)


def dedupe_announcements(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by (symbol, meeting_date). NSE takes priority over BSE."""
    seen: dict[str, dict[str, Any]] = {}
    for record in records:
        symbol = str(record.get("symbol") or record.get("isin") or record.get("company_name") or "").upper()
        # Use only symbol + date as key (not title, which varies between sources)
        date_key = str(record.get("meeting_date") or "")[:10]
        key = f"{symbol}|{date_key}"
        existing = seen.get(key)
        if existing is None:
            seen[key] = record
            continue
        # NSE record takes priority
        if existing.get("exchange") != "NSE" and record.get("exchange") == "NSE":
            record["bse_corroborated"] = True
            record["attachment_urls"] = sorted(
                set([*(record.get("attachment_urls") or []), *(existing.get("attachment_urls") or [])])
            )
            seen[key] = record
            continue
        # Merge attachment URLs
        existing["attachment_urls"] = sorted(
            set([*(existing.get("attachment_urls") or []), *(record.get("attachment_urls") or [])])
        )
        existing["nse_corroborated"] = bool(
            existing.get("nse_corroborated") or record.get("exchange") == "NSE"
        )
        existing["bse_corroborated"] = bool(
            existing.get("bse_corroborated") or record.get("exchange") == "BSE"
        )
    return sorted(seen.values(), key=lambda r: str(r.get("meeting_date") or ""), reverse=True)


def build_detail_from_announcement(record: dict[str, Any]) -> dict[str, Any] | None:
    """Build a structured detail record from an announcement, trying attachment URLs in order.

    Priority order:
    1. Stored attachment_urls (already scored: outcome docs first by the scraper).
    2. If all scored PDFs come back as intimation-only, re-fetch outcome URLs from
       NSE corporate-announcements (then BSE) for the same symbol+date.
    3. Fall back to text-only parse from the announcement summary if no PDF works.
    """
    attachment_urls = list(record.get("attachment_urls") or [])
    storage_paths = list(record.get("storage_paths") or [])
    symbol = str(record.get("symbol") or "")
    meeting_date_raw = record.get("meeting_date")
    from finagent.earnings.analysis import parse_date as _pd
    meeting_date = _pd(str(meeting_date_raw or ""))

    shared_metadata = {
        "title": record.get("title"),
        "company_name": record.get("company_name"),
        "symbol": symbol,
        "meeting_date": meeting_date_raw,
        "announced_at": record.get("announced_at"),
        "quarter_ref": record.get("quarter_ref"),
        "timing": record.get("timing"),
    }

    def _try_urls(urls: list[str]) -> dict[str, Any] | None:
        """Try each URL; return parsed result if non-intimation, else None."""
        for url_idx, url in enumerate(urls[:4]):
            pdf_bytes = _download_pdf_bytes(str(url))
            if not pdf_bytes:
                continue
            candidate = parse_earnings_document(
                pdf_bytes=pdf_bytes,
                text=str(record.get("summary") or ""),
                metadata={"source_url": url, **shared_metadata},
            )
            if candidate.get("is_intimation") and url_idx < len(urls) - 1:
                logger.debug(
                    "Attachment %d for %s is intimation, trying next URL", url_idx, symbol
                )
                continue
            return candidate
        return None

    parsed = _try_urls(attachment_urls)

    # All stored URLs were intimation docs — re-fetch outcome PDFs from exchange APIs
    if parsed is None or parsed.get("is_intimation"):
        if symbol and meeting_date:
            logger.info(
                "Stored URLs for %s %s are intimation-only; re-fetching outcome docs from NSE/BSE",
                symbol,
                meeting_date,
            )
            outcome_urls = _fetch_outcome_urls_from_nse(symbol, meeting_date)
            if not outcome_urls:
                outcome_urls = _fetch_outcome_urls_from_bse(symbol, meeting_date)
            if outcome_urls:
                parsed = _try_urls(outcome_urls) or parsed

    # Last resort: text-only parse from announcement summary
    if parsed is None:
        if not record.get("summary"):
            return None
        parsed = parse_earnings_document(
            text=str(record.get("summary") or ""),
            metadata={"source_url": attachment_urls[0] if attachment_urls else "", **shared_metadata},
        )

    if not parsed:
        return None

    documents = [
        {
            "type": _document_type_for_url(url, idx),
            "title": _document_title_for_url(url, idx),
            "url": url,
            "storage_path": storage_paths[idx] if idx < len(storage_paths) else "",
        }
        for idx, url in enumerate(attachment_urls)
    ]
    return {
        "event_uid": record.get("event_uid"),
        "symbol": symbol,
        "company_name": record.get("company_name"),
        "meeting_date": meeting_date_raw,
        "fiscal_quarter": parsed.get("quarter") or record.get("quarter_ref"),
        "timing": parsed.get("timing") or record.get("timing"),
        "highlights": parsed.get("highlights") or [],
        "management_commentary": parsed.get("management_commentary") or [],
        "transcript": parsed.get("transcript") or {"prepared_remarks": [], "qa": []},
        "documents": documents,
        "financials": parsed.get("financials") or {"rows": []},
        "text_excerpt": parsed.get("text_excerpt") or "",
        "parser_version": parsed.get("parser_version") or _PARSER_VERSION,
    }


def download_pdf_to_supabase(url: str, *, symbol: str, filing_date: str) -> str:
    pdf_bytes = _download_pdf_bytes(url)
    if not pdf_bytes:
        return ""
    supabase_url = _get_supabase_url()
    supabase_key = _get_supabase_key()
    if not supabase_url or not supabase_key:
        return ""
    filename = _safe_filename(PurePosixPath(url.split("?", 1)[0]).name or "filing.pdf")
    object_path = f"{_safe_filename(symbol.upper())}/{_safe_filename(str(filing_date)[:10])}/{filename}"
    endpoint = f"{supabase_url.rstrip('/')}/storage/v1/object/{_SUPABASE_BUCKET}/{object_path}"
    try:
        with httpx.Client(timeout=40.0, follow_redirects=True) as client:
            response = client.post(
                endpoint,
                content=pdf_bytes,
                headers={
                    "apikey": supabase_key,
                    "Authorization": f"Bearer {supabase_key}",
                    "Content-Type": "application/pdf",
                    "x-upsert": "true",
                },
            )
            if response.status_code in {200, 201}:
                return f"{_SUPABASE_BUCKET}/{object_path}"
            logger.debug("Supabase PDF upload returned %s: %s", response.status_code, response.text[:200])
    except Exception as exc:  # noqa: BLE001
        logger.debug("Supabase PDF upload failed: %s", exc)
    return ""


def _download_pdf_bytes(url: str) -> bytes:
    if not url:
        return b""
    try:
        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            response = client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
                    "Accept": "application/pdf,*/*",
                    "Referer": "https://www.nseindia.com/",
                },
            )
            response.raise_for_status()
            content = response.content
            if len(content) > 1024 and content[:4] == b"%PDF":
                return content
    except Exception as exc:  # noqa: BLE001
        logger.debug("PDF download failed for %s: %s", url, exc)
    return b""


def _extract_meeting_date(title: str, body: Any, fallback: date) -> date:
    text = f"{title or ''} {body or ''}"
    match = re.search(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})\b", text)
    parsed = parse_date(match.group(1)) if match else None
    return parsed or fallback


def _normalize_nse_attachment(raw: str) -> str:
    url = raw.strip()
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://www.nseindia.com{url}"
    return url


def _normalize_bse_attachment(raw: str) -> str:
    url = raw.strip().replace("\\", "/")
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://www.bseindia.com{url}"
    return f"{_BSE_ATTACH_ROOT}/{url}"


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._=-]+", "-", value.strip())
    cleaned = cleaned.strip("-")[:120] or "filing.pdf"
    if "." not in cleaned:
        cleaned += ".pdf"
    return cleaned


def _document_type_for_url(url: str, index: int) -> str:
    lower = url.lower()
    if "transcript" in lower or "concall" in lower:
        return "Concall transcript PDF"
    if "presentation" in lower or "ppt" in lower:
        return "Investor presentation"
    if index == 0:
        return "Press release"
    return "Official document"


def _document_title_for_url(url: str, index: int) -> str:
    doc_type = _document_type_for_url(url, index)
    return "Exchange filing attachment" if doc_type == "Official document" else doc_type


def _hydrate_symbols_from_company_master(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Legacy: enrich BSE records using BSE scrip code lookup."""
    if not records:
        return records
    try:
        companies = get_listed_companies(indexed_only=False)
    except Exception:
        companies = []
    by_bse = {
        str(company.get("bse_scrip_code") or "").strip(): company
        for company in companies
        if company.get("bse_scrip_code")
    }
    by_nse = {
        str(company.get("nse_symbol") or "").strip().upper(): company
        for company in companies
        if company.get("nse_symbol")
    }
    for record in records:
        code = str(record.get("bse_scrip_code") or "").strip()
        sym = str(record.get("symbol") or "").strip().upper()
        match = by_bse.get(code) or by_nse.get(sym)
        if not match:
            continue
        record["symbol"] = str(match.get("nse_symbol") or record.get("symbol") or "").upper()
        record["isin"] = record.get("isin") or match.get("isin") or ""
        record["company_name"] = match.get("company_name") or record.get("company_name")
        record["sector"] = match.get("sector") or record.get("sector") or "Other"
    return records


def check_and_backfill_if_needed() -> dict[str, Any] | None:
    """Check if earnings table is empty; if so run a fast backfill.

    Called on startup. Non-blocking intent: this is a best-effort seed.
    """
    try:
        from finagent.ikg.db import connect_postgres

        with connect_postgres(connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM earnings_announcements WHERE meeting_date IS NOT NULL"
                )
                result = cur.fetchone()
                count = result[0] if result else 0

        if count > 50:
            logger.info("earnings_announcements has %d records, skipping backfill", count)
            return None

        logger.info(
            "earnings_announcements is sparse (%d records) — running backfill", count
        )
        result = backfill_historical_earnings(quarters=8)
        logger.info("Backfill completed: %s", result)
        return result

    except Exception as exc:
        logger.debug("Backfill check failed (non-fatal): %s", exc)
        return None


try:
    from finagent.ikg.pipeline.celery_app import celery_app
except Exception:  # pragma: no cover - Celery is optional in local tests
    celery_app = None

if celery_app is not None:
    celery_app.conf.task_routes = {
        **(celery_app.conf.task_routes or {}),
        "finagent.earnings.scrape": {"queue": "documents"},
        "finagent.earnings.backfill": {"queue": "documents"},
        "finagent.earnings.sync_yahoo": {"queue": "documents"},
    }
    celery_app.conf.beat_schedule = {
        **(celery_app.conf.beat_schedule or {}),
        # Adaptive: 5-min during market hours, 15-min off-hours
        "earnings-announcements-every-5-minutes": {
            "task": "finagent.earnings.scrape",
            "schedule": 5 * 60,
        },
        # Yahoo consensus sync — every 6 hours
        "earnings-yahoo-sync-every-6-hours": {
            "task": "finagent.earnings.sync_yahoo",
            "schedule": 6 * 60 * 60,
        },
    }

    @celery_app.task(name="finagent.earnings.scrape")
    def scrape_earnings_task() -> dict[str, Any]:
        # During off-hours, reduce scope to avoid hammering NSE/BSE
        if _is_peak_disclosure_window() or _is_market_hours():
            return run_earnings_ingestion()
        return run_earnings_ingestion(
            start_date=date.today() - timedelta(days=2),
            end_date=date.today() + timedelta(days=15),
        )

    @celery_app.task(name="finagent.earnings.backfill")
    def backfill_earnings_task(quarters: int = 8, max_announcements: int | None = None) -> dict[str, Any]:
        return backfill_historical_earnings(quarters=quarters, max_announcements=max_announcements)

    @celery_app.task(name="finagent.earnings.sync_yahoo")
    def sync_yahoo_task(symbols: list[str] | None = None) -> dict[str, Any]:
        """Pull Yahoo Finance earnings history + estimates for tracked symbols."""
        return sync_yahoo_earnings(symbols=symbols)


def _get_active_symbols(limit: int = 200) -> list[str]:
    """Return symbols with recent (90-day) earnings announcements from DB."""
    try:
        from finagent.ikg.db import connect_postgres, get_database_url
        from psycopg.rows import dict_row
        db_url = get_database_url()
        if not db_url:
            return []
        cutoff = date.today() - timedelta(days=90)
        with connect_postgres(row_factory=dict_row, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT symbol FROM earnings_announcements
                    WHERE meeting_date >= %s AND symbol IS NOT NULL AND symbol != ''
                    ORDER BY symbol LIMIT %s
                    """,
                    (cutoff, limit),
                )
                return [r["symbol"] for r in cur.fetchall()]
    except Exception as exc:
        logger.debug("_get_active_symbols failed: %s", exc)
        return []


def sync_yahoo_earnings(symbols: list[str] | None = None) -> dict[str, Any]:
    """Sync Yahoo Finance earnings history for given symbols (or all active ones)."""
    from finagent.earnings.yahoo_scraper import (
        fetch_earnings_history,
        fetch_price_history_around_date,
    )

    targets = symbols or _get_active_symbols(limit=100)
    synced = 0
    failed = 0

    for symbol in targets:
        try:
            rows = fetch_earnings_history(symbol)
            for row in rows:
                if not row.get("fiscal_year") or not row.get("fiscal_period"):
                    continue
                if row.get("earnings_date") and row.get("post_earnings_move_1d") is None:
                    try:
                        price_data = fetch_price_history_around_date(symbol, row["earnings_date"])
                        row.update(price_data)
                    except Exception:
                        pass
                if upsert_earnings_history(row):
                    synced += 1
        except Exception as exc:
            failed += 1
            logger.warning("sync_yahoo_earnings failed for %s: %s", symbol, exc)

    return {"synced": synced, "failed": failed, "symbols": len(targets)}

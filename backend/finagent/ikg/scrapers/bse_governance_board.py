"""Full-board scraper from BSE quarterly Corporate Governance reports (Reg 27(2)).

The real-time board-change feed captures *changes*; this captures the *full current
board* with DIN for every listed company — the density that makes director-network and
enforcement-proximity features meaningful (was stuck at 451 cos because the NSE
governance API 403s Azure). Reg 27(2) corporate-governance reports are filed quarterly
to BSE and list the entire board (name, DIN, category, designation) in the attachment.

Pipeline per scrip: BSE announcements → newest governance-report PDF → local-first
extraction (PyMuPDF, no Azure DI cost) → reuse parse_director_kmp_from_text →
_store_directors. Incremental via ``since``.
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx

from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.scrapers._doc_extract import extract_pdf_text_local, text_is_sufficient
from finagent.ikg.scrapers.director_kmp_enricher import (
    _ensure_director_tables,
    _store_directors,
    parse_director_kmp_from_text,
)

logger = logging.getLogger("finagent.ikg.scrapers.bse_governance_board")

_BSE_ANNOUNCEMENTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
_BSE_ATTACH_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"
_BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/",
}
_PARSER_VERSION = "bse_governance_board_v1"
_REQUEST_DELAY_S = float(os.getenv("FINAGENT_GOV_BOARD_REQUEST_DELAY_S", "0.3"))
_DEFAULT_MAX_WORKERS = int(os.getenv("FINAGENT_GOV_BOARD_MAX_WORKERS", "4") or "4")
_LOCAL_MIN_CHARS = int(os.getenv("FINAGENT_GOV_BOARD_LOCAL_MIN_CHARS", "600") or "600")

_GOV_REPORT_HINTS = (
    "corporate governance", "reg. 27", "regulation 27", "27(2)",
    "corp. governance", "governance report", "board composition",
    "integrated filing", "governance",
)
# Exclude governance-keyword noise that is not a board-listing report.
_GOV_REPORT_EXCLUDE = ("analyst", "investor meet", "press release", "media")
_GOV_REPORT_MAX_PAGES = int(os.getenv("FINAGENT_GOV_BOARD_MAX_PAGES", "12") or "12")
_GOV_REPORT_WINDOW_DAYS = int(os.getenv("FINAGENT_GOV_BOARD_WINDOW_DAYS", "365") or "365")


def _full_attachment_url(raw: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    return raw if raw.lower().startswith("http") else _BSE_ATTACH_BASE + raw.lstrip("/")


def _is_governance_report(title: str, desc: str, category: str) -> bool:
    blob = f"{title} {desc} {category}".lower()
    if any(x in blob for x in _GOV_REPORT_EXCLUDE):
        return False
    return any(h in blob for h in _GOV_REPORT_HINTS)


def fetch_governance_pdf_candidates(scrip_code: str, *, since: str | None = None,
                                    max_pages: int | None = None, max_candidates: int = 6,
                                    timeout_s: float = 45.0) -> list[str]:
    """Return candidate governance-report PDF URLs (newest first) for a BSE scrip."""
    max_pages = max_pages or _GOV_REPORT_MAX_PAGES
    today = time.strftime("%Y%m%d", time.gmtime())
    prev = since or time.strftime("%Y%m%d", time.gmtime(time.time() - _GOV_REPORT_WINDOW_DAYS * 86400))
    out: list[str] = []
    seen: set[str] = set()
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
            for page_no in range(1, max(1, max_pages) + 1):
                params = {
                    "pageno": str(page_no), "strCat": "-1", "strPrevDate": prev,
                    "strScrip": str(scrip_code), "strSearch": "P", "strToDate": today,
                    "strType": "C", "subcategory": "-1",
                }
                resp = client.get(_BSE_ANNOUNCEMENTS_URL, headers=_BSE_HEADERS, params=params)
                if resp.status_code != 200 or not resp.content:
                    break
                rows = (resp.json() or {}).get("Table")
                if not isinstance(rows, list) or not rows:
                    break
                for row in rows:  # newest first
                    if not isinstance(row, dict):
                        continue
                    title = str(row.get("NEWSSUB") or row.get("HEADLINE") or "")
                    desc = str(row.get("MORE") or row.get("MORETEXT") or "")
                    cat = str(row.get("CATEGORYNAME") or row.get("SUBCATNAME") or "")
                    if not _is_governance_report(title, desc, cat):
                        continue
                    url = _full_attachment_url(str(row.get("ATTACHMENTNAME") or row.get("NSURL") or ""))
                    if url and url.lower().endswith(".pdf") and url not in seen:
                        seen.add(url)
                        out.append(url)
                        if len(out) >= max_candidates:
                            return out
                if len(rows) < 50:
                    break
                time.sleep(_REQUEST_DELAY_S)
    except Exception as exc:
        logger.debug("BSE governance-report lookup failed for %s: %s", scrip_code, exc)
    return out


def _extract_board_text(url: str, *, timeout_s: float = 40.0) -> str:
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
            resp = client.get(url, headers=_BSE_HEADERS)
            if resp.status_code != 200 or not resp.content:
                return ""
        return (extract_pdf_text_local(resp.content) or {}).get("full_text") or ""
    except Exception as exc:
        logger.debug("governance PDF extract failed %s: %s", url, exc)
        return ""


def run_governance_board_scraper(
    companies: list[dict[str, Any]],
    *,
    database_url: str | None = None,
    since: str | None = None,
    max_companies: int | None = None,
) -> dict[str, Any]:
    """Scrape full current boards from BSE governance reports for the given companies."""
    db_url = get_database_url(database_url)
    if not db_url:
        return {"success": False, "error": "no database_url", "directors_stored": 0}

    targets = [c for c in companies if str(c.get("bse_scrip_code") or "").strip() and c.get("cin")]
    if max_companies:
        targets = targets[:max_companies]
    stats = {"success": True, "companies_processed": 0, "reports_found": 0,
             "director_candidates": 0, "directors_stored": 0, "errors": 0}
    if not targets:
        return {**stats, "success": False, "error": "no companies with bse_scrip_code+cin"}

    def _work(co: dict[str, Any]) -> dict[str, Any]:
        scrip = str(co.get("bse_scrip_code")).strip()
        candidates = fetch_governance_pdf_candidates(scrip, since=since)
        if not candidates:
            return {"co": co, "rows": [], "found": False}
        best: list[dict[str, Any]] = []
        for pdf in candidates:
            text = _extract_board_text(pdf)
            if not text_is_sufficient(text, min_chars=_LOCAL_MIN_CHARS):
                continue
            rows = parse_director_kmp_from_text(
                text, cin=str(co.get("cin")), source="BSE_governance_report",
                source_url=pdf, bse_scrip_code=scrip,
                nse_symbol=(str(co.get("nse_symbol") or "").strip().upper() or None),
            )
            if len(rows) > len(best):
                best = rows
            if len(best) >= 4:  # a real board listing — stop scanning candidates
                break
        return {"co": co, "rows": best, "found": True}

    from psycopg.rows import dict_row

    with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
        _ensure_director_tables(conn)
        with conn.cursor() as cur:
            with ThreadPoolExecutor(max_workers=min(_DEFAULT_MAX_WORKERS, max(1, len(targets)))) as ex:
                futures = {ex.submit(_work, co): co for co in targets}
                for fut in as_completed(futures):
                    try:
                        res = fut.result()
                    except Exception as exc:
                        stats["errors"] += 1
                        logger.debug("governance-board worker failed: %s", exc)
                        continue
                    stats["companies_processed"] += 1
                    if res["found"]:
                        stats["reports_found"] += 1
                    rows = res["rows"]
                    stats["director_candidates"] += len(rows)
                    if rows:
                        try:
                            stats["directors_stored"] += _store_directors(cur, rows)
                            conn.commit()
                        except Exception as exc:
                            conn.rollback()
                            stats["errors"] += 1
                            logger.debug("governance-board store failed: %s", exc)
    stats["success"] = stats["directors_stored"] > 0 or stats["errors"] == 0
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import json

    from finagent.ikg.scrapers.mca_companies import get_listed_companies

    print(json.dumps(run_governance_board_scraper(get_listed_companies(), max_companies=15), default=str, indent=2))

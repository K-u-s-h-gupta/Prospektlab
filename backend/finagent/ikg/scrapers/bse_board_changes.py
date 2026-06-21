"""Real-time director / KMP board-change scraper (BSE corporate announcements).

SEBI LODR Reg 30 requires board appointments, resignations, cessations and KMP
changes to be disclosed to the exchange within 24 hours. Those disclosures land in
the BSE corporate-announcements feed (``AnnSubCategoryGetData``) — reachable from the
ikg-vm (Azure), unlike the NSE governance API which 403s datacenter IPs.

This is the **real-time** director source (cadence = daily/intraday), complementing
the quarterly Reg 27(2) governance filings and yearly annual-report board sections.
It is incremental: pass ``since`` (YYYYMMDD) to fetch only new disclosures.

Each director event is upserted into ``directors_raw`` with an appointment_date or
cessation_date and ``announced_at`` so board-churn features stay current within a day.
"""

from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import httpx

from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.scrapers._doc_extract import extract_pdf_text_local

logger = logging.getLogger("finagent.ikg.scrapers.bse_board_changes")

_BSE_ATTACH_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"

_BSE_ANNOUNCEMENTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
_BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/",
}
_PARSER_VERSION = "bse_board_changes_v1"
_REQUEST_DELAY_S = float(os.getenv("FINAGENT_BOARD_CHANGE_REQUEST_DELAY_S", "0.3"))
_DEFAULT_MAX_WORKERS = int(os.getenv("FINAGENT_BOARD_CHANGE_MAX_WORKERS", "4") or "4")

# BSE files board changes under these category / subcategory names.
_DIRECTOR_CATEGORY_HINTS = (
    "board of directors", "change in directors", "change in director",
    "appointment", "resignation", "cessation", "key managerial",
    "company secretary", "chief financial officer", "managing director",
    "director", "kmp",
)
_APPOINT_RE = re.compile(r"\b(appoint|induct|re-?appoint|join|nominat)", re.I)
_CESSATION_RE = re.compile(r"\b(resign|cessation|cease|retire|demise|removal|step\s*down|vacat)", re.I)
_DIN_RE = re.compile(r"\bDIN\s*[:\-]?\s*(\d{8})\b", re.I)
_TAG_RE = re.compile(r"<[^>]+>")

# Person name following common role/verb cues in the announcement text.
_NAME_RE = re.compile(
    r"(?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Shri|Smt\.?|CA\.?)\s+"
    r"([A-Z][a-zA-Z.]+(?:\s+[A-Z][a-zA-Z.]+){1,3})"
)


def _strip(text: Any) -> str:
    return _TAG_RE.sub("", str(text or "")).replace("&amp;", "&").strip()


def _full_attachment_url(raw: str) -> str | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("http"):
        return raw
    return _BSE_ATTACH_BASE + raw.lstrip("/")


def _extract_names_dins_from_pdf(url: str, *, timeout_s: float = 30.0) -> list[tuple[str | None, str]]:
    """Download a board-change attachment and pull (name, din) pairs via local extraction.

    Local-first (PyMuPDF/pypdf) — no Azure DI cost for these short disclosures.
    """
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
            resp = client.get(url, headers=_BSE_HEADERS)
            if resp.status_code != 200 or not resp.content:
                return []
        text = (extract_pdf_text_local(resp.content) or {}).get("full_text") or ""
    except Exception as exc:
        logger.debug("board-change PDF extract failed %s: %s", url, exc)
        return []
    if not text:
        return []
    pairs: list[tuple[str | None, str]] = []
    seen: set[str] = set()
    for m in re.finditer(r"\bDIN\s*[:\-]?\s*(\d{8})\b", text, re.I):
        din = m.group(1)
        if din in seen:
            continue
        seen.add(din)
        # Look for a name within the 120 chars preceding the DIN.
        window = text[max(0, m.start() - 120): m.start()]
        nm = None
        nmatch = list(_NAME_RE.finditer(window))
        if nmatch:
            nm = nmatch[-1].group(1).strip()
        pairs.append((nm, din))
    return pairs


def _parse_dt(raw: str) -> str | None:
    raw = str(raw or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%d %b %Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw[:26], fmt).replace(tzinfo=timezone.utc).isoformat()
        except Exception:
            continue
    m = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
    return m.group(1) if m else None


def _classify(text: str) -> str | None:
    """Return 'appointment' | 'cessation' | None for a board announcement."""
    if _CESSATION_RE.search(text):
        return "cessation"
    if _APPOINT_RE.search(text):
        return "appointment"
    return None


def _is_board_change(title: str, desc: str, category: str) -> bool:
    blob = f"{title} {desc} {category}".lower()
    if not any(h in blob for h in _DIRECTOR_CATEGORY_HINTS):
        return False
    # Must look like a personnel change, not a routine board meeting notice.
    return bool(_APPOINT_RE.search(blob) or _CESSATION_RE.search(blob) or "din" in blob)


def fetch_board_changes_for_scrip(
    scrip_code: str,
    *,
    since: str | None = None,
    max_pages: int = 3,
    timeout_s: float = 30.0,
) -> list[dict[str, Any]]:
    """Fetch recent board-change announcements for one BSE scrip."""
    today = time.strftime("%Y%m%d", time.gmtime())
    prev = since or time.strftime("%Y%m%d", time.gmtime(time.time() - 120 * 86400))
    events: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True, trust_env=False) as client:
            for page_no in range(1, max(1, max_pages) + 1):
                params = {
                    "pageno": str(page_no),
                    "strCat": "-1",
                    "strPrevDate": prev,
                    "strScrip": str(scrip_code),
                    "strSearch": "P",
                    "strToDate": today,
                    "strType": "C",
                    "subcategory": "-1",
                }
                resp = client.get(_BSE_ANNOUNCEMENTS_URL, headers=_BSE_HEADERS, params=params)
                if resp.status_code != 200:
                    break
                rows = (resp.json() or {}).get("Table") if resp.content else None
                if not isinstance(rows, list) or not rows:
                    break
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    title = _strip(row.get("NEWSSUB") or row.get("HEADLINE"))
                    desc = _strip(row.get("MORE") or row.get("MORETEXT"))
                    category = _strip(row.get("CATEGORYNAME") or row.get("SUBCATNAME"))
                    if not _is_board_change(title, desc, category):
                        continue
                    blob = f"{title}. {desc}"
                    action = _classify(blob)
                    if not action:
                        continue
                    announced = _parse_dt(row.get("DT_TM") or row.get("NEWS_DT") or "")
                    attach = _full_attachment_url(_strip(row.get("ATTACHMENTNAME") or row.get("NSURL")))
                    din_m = _DIN_RE.search(blob)
                    name_m = _NAME_RE.search(blob)
                    base = {
                        "scrip_code": str(scrip_code), "action": action,
                        "announced_at": announced, "title": title[:400],
                        "category": category, "attachment_url": attach,
                    }
                    if din_m:
                        events.append({**base, "din": din_m.group(1),
                                       "name": name_m.group(1).strip() if name_m else None})
                    elif attach and attach.lower().endswith((".pdf", "")):
                        # Name/DIN are in the filing PDF — extract locally (no DI cost).
                        pairs = _extract_names_dins_from_pdf(attach)
                        for nm, din in pairs:
                            events.append({**base, "din": din, "name": nm})
                        if not pairs and name_m:
                            events.append({**base, "din": None, "name": name_m.group(1).strip()})
                    elif name_m:
                        events.append({**base, "din": None, "name": name_m.group(1).strip()})
                if len(rows) < 50:
                    break
                time.sleep(_REQUEST_DELAY_S)
    except Exception as exc:
        logger.debug("BSE board-change fetch failed for %s: %s", scrip_code, exc)
    return events


def _upsert_board_events(cur: Any, cin: str, scrip_code: str, events: list[dict[str, Any]]) -> int:
    stored = 0
    for ev in events:
        din = ev.get("din")
        name = (ev.get("name") or "")[:200] or None
        if not din and not name:
            continue  # nothing identifiable
        ann = (ev.get("announced_at") or "")[:10] or None  # DATE column → trim to YYYY-MM-DD
        appt = ann if ev["action"] == "appointment" else None
        cess = ann if ev["action"] == "cessation" else None
        # Per-event savepoint so one malformed event never loses the rest.
        cur.execute("SAVEPOINT _bc")
        try:
            stored += _insert_board_event(cur, cin, scrip_code, din, name, ev, appt, cess)
            cur.execute("RELEASE SAVEPOINT _bc")
        except Exception as exc:
            cur.execute("ROLLBACK TO SAVEPOINT _bc")
            logger.debug("board event insert skipped (%s): %s", cin, exc)
    return stored


def _insert_board_event(cur, cin, scrip_code, din, name, ev, appt, cess) -> int:
        # Idempotent: skip if the same cin+din+dates event is already recorded
        # (daily real-time runs re-see the same disclosure window).
        cur.execute(
            """
            insert into directors_raw
                (cin, din, name, designation, appointment_date, cessation_date,
                 source, source_url, bse_scrip_code, fetched_at)
            select %s, %s, %s, %s, %s, %s, %s, %s, %s, now()
            where not exists (
                select 1 from directors_raw d
                where d.cin = %s
                  and coalesce(d.din, '') = coalesce(%s, '')
                  and coalesce(d.appointment_date::text, '') = coalesce(%s::text, '')
                  and coalesce(d.cessation_date::text, '') = coalesce(%s::text, '')
            )
            """,
            (
                cin, din, name, ev.get("category"), appt, cess,
                "BSE_announcement_realtime", ev.get("attachment_url"), scrip_code,
                cin, din, appt, cess,
            ),
        )
        return cur.rowcount or 0


def run_board_change_scraper(
    companies: list[dict[str, Any]],
    *,
    database_url: str | None = None,
    since: str | None = None,
    max_companies: int | None = None,
) -> dict[str, Any]:
    """Scrape real-time board changes for the given companies (must carry bse_scrip_code)."""
    db_url = get_database_url(database_url)
    if not db_url:
        return {"success": False, "error": "no database_url", "events_stored": 0}

    targets = [c for c in companies if str(c.get("bse_scrip_code") or "").strip()]
    if max_companies:
        targets = targets[:max_companies]
    stats = {"success": True, "companies_processed": 0, "events_found": 0, "events_stored": 0, "errors": 0}
    if not targets:
        return {**stats, "success": False, "error": "no companies with bse_scrip_code"}

    def _work(co: dict[str, Any]) -> dict[str, Any]:
        scrip = str(co.get("bse_scrip_code")).strip()
        evs = fetch_board_changes_for_scrip(scrip, since=since)
        return {"co": co, "events": evs}

    from psycopg.rows import dict_row

    with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            with ThreadPoolExecutor(max_workers=min(_DEFAULT_MAX_WORKERS, max(1, len(targets)))) as ex:
                futures = {ex.submit(_work, co): co for co in targets}
                for fut in as_completed(futures):
                    try:
                        res = fut.result()
                    except Exception as exc:
                        stats["errors"] += 1
                        logger.debug("board-change worker failed: %s", exc)
                        continue
                    co = res["co"]
                    evs = res["events"]
                    stats["companies_processed"] += 1
                    stats["events_found"] += len(evs)
                    cin = str(co.get("cin") or "").strip()
                    if cin and evs:
                        try:
                            stats["events_stored"] += _upsert_board_events(cur, cin, str(co.get("bse_scrip_code")), evs)
                            conn.commit()
                        except Exception as exc:
                            conn.rollback()
                            stats["errors"] += 1
                            logger.debug("board-change upsert failed for %s: %s", cin, exc)
    stats["success"] = stats["errors"] == 0 or stats["events_stored"] > 0
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import json

    from finagent.ikg.scrapers.mca_companies import get_listed_companies

    cos = get_listed_companies()
    print(json.dumps(run_board_change_scraper(cos, max_companies=20), default=str, indent=2))

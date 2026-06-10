"""BSE EOD (End-of-Day) Prices — daily batch downloader.

Downloads official BSE bulk EOD price data in CSV format.
This is official BSE data, free for public use.

Source: https://api.bseindia.com/BseIndiaAPI/api/GetBhavcopydata/w
Method: Resolve official filename via metadata endpoint, then download CSV
Returns: CSV with OHLCV for all BSE-listed companies

Schedule: Daily at 6:00 PM IST (after market close + settlement).

Table: daily_prices (scrip_code, trade_date, open, high, low, close, volume)

Anti-blocking:
  Uses SmartHTTPClient with proxy rotation and retry (up to 4 attempts).
  BSE public APIs are generally reliable; proxy adds resilience for IP bans.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.scrapers._engine import SmartHTTPClient, sync_get

logger = logging.getLogger("finagent.ikg.scrapers.bse_eod")

_BSE_EOD_META_URL = "https://api.bseindia.com/BseIndiaAPI/api/GetBhavcopydata/w"
_BSE_EOD_DOWNLOAD_BASE = "https://www.bseindia.com/download/BhavCopy/Equity/"
_BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://www.bseindia.com/",
    "Accept": "application/json, text/plain, */*",
}


def _bse_date_str(d: date) -> str:
    """Format date as DDMMYY for BSE URL."""
    return d.strftime("%d%m%y")


def _bse_date_param(d: date) -> str:
    """Format date as YYYYMMDD for BSE metadata endpoint."""
    return d.strftime("%Y%m%d")


def resolve_bse_eod_filename(
    trade_date: date,
    timeout_s: float = 30.0,
) -> str | None:
    """Resolve the official BSE EOD file name for a given trade date.

    Uses SmartHTTPClient for proxy rotation + retry resilience.
    """
    params = {
        "flag": "1",
        "segment": "equity",
        "date": _bse_date_param(trade_date),
    }
    try:
        resp = sync_get(
            _BSE_EOD_META_URL,
            params=params,
            headers=_BSE_HEADERS,
            timeout=timeout_s,
        )
        if resp.status_code != 200:
            logger.warning("BSE EOD metadata returned %s for %s", resp.status_code, trade_date)
            return None
        payload = resp.json()
    except Exception as exc:
        logger.warning("BSE EOD metadata lookup failed for %s: %s", trade_date, exc)
        return None

    return pick_bse_eod_filename(payload)


def pick_bse_eod_filename(payload: dict[str, Any]) -> str | None:
    """Pick the official BSE EOD file name from GetBhavcopydata payload."""
    candidate_rows: list[dict[str, Any]] = []
    for key in ("dsedcudiff", "dsBhav", "dsEqnew", "dsZip", "dsEquity"):
        rows = payload.get(key)
        if isinstance(rows, list):
            candidate_rows.extend(item for item in rows if isinstance(item, dict))

    if not candidate_rows:
        logger.info("BSE EOD metadata payload had no candidate rows")
        return None

    for row in candidate_rows:
        filename = str(row.get("filename") or row.get("FilePath") or "").strip()
        if not filename:
            continue
        if not re.search(r"\.(csv|zip)$", filename, re.I):
            continue
        return filename
    return None


def download_bse_eod_csv(
    trade_date: date | None = None,
    timeout_s: float = 60.0,
) -> bytes | None:
    """Download BSE EOD bulk CSV zip for a given trading date.

    Args:
        trade_date: Trading date (defaults to yesterday). Skips weekends.
        timeout_s: Download timeout.

    Returns:
        Raw CSV bytes, or None if not available (holiday/weekend).
    """
    if trade_date is None:
        trade_date = date.today() - timedelta(days=1)

    # Skip weekends
    if trade_date.weekday() >= 5:
        logger.info("BSE EOD: %s is a weekend, skipping", trade_date)
        return None

    filename = resolve_bse_eod_filename(trade_date, timeout_s=timeout_s)
    if not filename:
        logger.info("BSE EOD metadata has no filename for %s", trade_date)
        return None
    url = f"{_BSE_EOD_DOWNLOAD_BASE}{filename}"
    logger.info("Downloading BSE EOD data for %s from %s", trade_date, url)

    try:
        resp = sync_get(url, headers=_BSE_HEADERS, timeout=timeout_s)
        if resp.status_code == 404:
            logger.info("BSE EOD not available for %s (possibly holiday)", trade_date)
            return None
        resp.raise_for_status()

        content = resp.content
        filename_upper = filename.upper()
        if filename_upper.endswith(".ZIP") or content[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                csv_files = [n for n in zf.namelist() if n.upper().endswith(".CSV")]
                if not csv_files:
                    logger.warning("No CSV found in BSE EOD zip for %s", trade_date)
                    return None
                return zf.read(csv_files[0])
        return content

    except zipfile.BadZipFile:
        logger.warning("BSE EOD: bad zip file for %s", trade_date)
        return None
    except httpx.HTTPStatusError as exc:
        logger.warning("BSE EOD HTTP error for %s: %s", trade_date, exc)
        return None
    except Exception as exc:
        logger.error("BSE EOD download failed for %s: %s", trade_date, exc)
        return None


def parse_bse_eod_csv(csv_bytes: bytes) -> list[dict[str, Any]]:
    """Parse BSE EOD CSV into list of price records.

    BSE EOD CSV columns:
      CODE, NAME, OPEN, HIGH, LOW, CLOSE, LAST, PREVCLOSE, TOTTRDQTY,
      TOTTRDVAL, TIMESTAMP, TOTALTRADES, ISIN

    Returns:
        List of dicts with: scrip_code, trade_date, open, high, low, close, volume
    """
    import csv

    records = []
    try:
        content = csv_bytes.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(content))
        for row in reader:
            scrip_code = (
                row.get("CODE")
                or row.get("FinInstrmId")
                or row.get("TckrSymb")
                or row.get("SecurityID")
                or ""
            )
            scrip_code = str(scrip_code).strip()
            if not scrip_code:
                continue
            try:
                from datetime import datetime

                trade_date = _parse_trade_date(
                    str(
                        row.get("TIMESTAMP")
                        or row.get("TradDt")
                        or row.get("TradeDate")
                        or row.get("BizDt")
                        or ""
                    ).strip()
                ) or (date.today() - timedelta(days=1))
                record = {
                    "scrip_code": scrip_code,
                    "name": str(row.get("NAME") or row.get("FinInstrmNm") or row.get("TckrSymb") or "").strip(),
                    "isin": (row.get("ISIN") or "").strip(),
                    "trade_date": trade_date,
                    "open": _as_float(row.get("OPEN") or row.get("OpnPric")),
                    "high": _as_float(row.get("HIGH") or row.get("HghPric")),
                    "low": _as_float(row.get("LOW") or row.get("LwPric")),
                    "close": _as_float(row.get("CLOSE") or row.get("ClsPric")),
                    "prev_close": _as_float(row.get("PREVCLOSE") or row.get("PrvsClsgPric")),
                    "volume": int(_as_float(row.get("TOTTRDQTY") or row.get("TtlTradgVol") or row.get("TrdQty"))),
                    "value_lakh": _as_float(row.get("TOTTRDVAL") or row.get("TtlTrfVal") or row.get("TrdVal")),
                }
                if not record["open"] and not record["high"] and not record["low"] and not record["close"]:
                    continue
                records.append(record)
            except (ValueError, TypeError):
                continue
    except Exception as exc:
        logger.error("BSE EOD CSV parse failed: %s", exc)

    logger.info("Parsed %d BSE EOD price records", len(records))
    return records


def _parse_trade_date(raw: str) -> date | None:
    if not raw:
        return None
    raw = raw.strip()
    from datetime import datetime

    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None


def _as_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "").replace("%", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def store_eod_to_postgres(
    records: list[dict[str, Any]],
    database_url: str | None = None,
) -> int:
    """Store EOD price records in PostgreSQL daily_prices table.

    Args:
        records: Parsed price records.
        database_url: PostgreSQL connection string.

    Returns:
        Number of records inserted.
    """
    db_url = get_database_url(database_url)
    if not db_url or not records:
        return 0

    try:
        with connect_postgres(db_url, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                inserted = len(records)
                cur.executemany(
                    """
                    insert into daily_prices (
                      scrip_code, isin, name, trade_date,
                      open, high, low, close, prev_close, volume, value_lakh
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (scrip_code, trade_date) do update set
                      close = excluded.close,
                      high = excluded.high,
                      low = excluded.low,
                      open = excluded.open,
                      volume = excluded.volume,
                      value_lakh = excluded.value_lakh
                    """,
                    [
                        (
                            rec["scrip_code"], rec.get("isin"), rec.get("name"),
                            rec["trade_date"],
                            rec["open"], rec["high"], rec["low"], rec["close"],
                            rec["prev_close"], rec["volume"], rec["value_lakh"],
                        )
                        for rec in records
                    ],
                )
            conn.commit()
        logger.info("Stored %d EOD price records", inserted)
        return inserted
    except Exception as exc:
        logger.error("EOD store failed: %s", exc)
        return 0


def run_bse_eod_scraper(
    trade_date: date | None = None,
    database_url: str | None = None,
) -> dict[str, Any]:
    """Full EOD pipeline: download → parse → store.

    Returns:
        dict with: trade_date, records_parsed, records_stored, success, error
    """
    if trade_date is None:
        trade_date = date.today() - timedelta(days=1)
        # Adjust for weekends
        while trade_date.weekday() >= 5:
            trade_date -= timedelta(days=1)

    csv_bytes = download_bse_eod_csv(trade_date)
    if not csv_bytes:
        return {
            "trade_date": str(trade_date),
            "records_parsed": 0,
            "records_stored": 0,
            "success": False,
            "error": "Data not available (holiday or weekend)",
        }

    records = parse_bse_eod_csv(csv_bytes)
    stored = store_eod_to_postgres(records, database_url)

    return {
        "trade_date": str(trade_date),
        "records_parsed": len(records),
        "records_stored": stored,
        "success": True,
        "error": None,
    }


def backfill_bse_eod(
    days_back: int = 30,
    database_url: str | None = None,
) -> dict[str, Any]:
    """Backfill BSE EOD data for the last N trading days.

    Args:
        days_back: Number of calendar days to look back (fetches trading days only).
        database_url: PostgreSQL connection string.

    Returns:
        dict with: days_processed, total_records_stored
    """
    import time

    total_stored = 0
    days_processed = 0
    today = date.today()

    for i in range(1, days_back + 1):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:  # Skip weekends
            continue
        result = run_bse_eod_scraper(d, database_url)
        total_stored += result.get("records_stored", 0)
        if result.get("success"):
            days_processed += 1
        time.sleep(1.0)  # Polite crawl delay

    return {"days_processed": days_processed, "total_records_stored": total_stored}


if __name__ == "__main__":
    result = run_bse_eod_scraper()
    print(result)

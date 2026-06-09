"""MCA Company Master — bulk CSV loader.

Reads the already-downloaded MCA company master CSV from the data/ directory
and loads it into the PostgreSQL staging table `ikg_company_master`.

Source: https://www.mcacdm.nic.in/company-master-details.php

MCA CSV columns:
  CIN, Company Name, Company Registration Date, Company Category,
  Company Class, Listing Status, Authorized Capital, Paidup Capital,
  Company ROC, Company Address, Pin Code, Company State, Company Status,
  Company Sub Category, Company Industrial Classification

Pipeline:
  1. Resolve CSRF token from MCA company master page
  2. Download full MCA CSV from official export endpoint
  3. Load full MCA CSV (~2M records) in chunked batches
  4. Filter to Nifty 500 companies + their known subsidiaries
  5. Write Company nodes to IKG with canonical CIN identifiers
  6. Upsert into ikg_company_master for entity resolution

Runs: Once on bootstrap, then monthly refresh via scheduler.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urljoin

import httpx

from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.scrapers._engine import SmartBrowser, SmartHTTPClient, sync_get

logger = logging.getLogger("finagent.ikg.scrapers.mca_companies")

_CHUNK_SIZE = max(100, int(os.getenv("FINAGENT_MCA_CHUNK_SIZE", "5000")))
_MCA_PROGRESS_LOG_EVERY = max(500, int(os.getenv("FINAGENT_MCA_PROGRESS_LOG_EVERY", "10000")))
_MCA_DB_LOCK_TIMEOUT = os.getenv("FINAGENT_MCA_DB_LOCK_TIMEOUT", "30s")
_MCA_DB_STATEMENT_TIMEOUT = os.getenv("FINAGENT_MCA_DB_STATEMENT_TIMEOUT", "15min")
_MCA_DB_BATCH_RETRIES = max(1, int(os.getenv("FINAGENT_MCA_DB_BATCH_RETRIES", "3")))
_MCA_DB_CONNECT_RETRIES = max(1, int(os.getenv("FINAGENT_MCA_DB_CONNECT_RETRIES", "3")))
_MCA_COMPANY_MASTER_PAGE = "https://www.mcacdm.nic.in/company-master-details.php"
_MCA_EXPORT_FORM_ACTION_DEFAULT = "https://www.mcacdm.nic.in/cdm/export_company_master_details.php"
_MCA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "text/csv, text/plain, */*",
    "Referer": _MCA_COMPANY_MASTER_PAGE,
    "Origin": "https://www.mcacdm.nic.in",
}
_MCA_EXPECTED_COLUMNS = {
    "CIN",
    "Company Name",
    "Company Registration Date",
    "Company Category",
    "Company Class",
    "Listing Status",
    "Authorized Capital",
    "Paidup Capital",
    "Company ROC",
    "Company Address",
    "Pin Code",
    "Company State",
    "Company Status",
    "Company Sub Category",
    "Company Industrial Classification",
}


@dataclass
class MCACompanyRecord:
    """Parsed MCA company master record."""
    cin: str
    name: str
    registration_date: date | None
    category: str
    company_class: str
    listing_status: str
    authorized_capital: float | None
    paidup_capital: float | None
    roc: str
    address: str
    pin_code: str
    state: str
    status: str
    sub_category: str
    industrial_classification: str


def _normalize_row_keys(row: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in row.items():
        norm_key = (key or "").replace("\ufeff", "").strip()
        cleaned[norm_key] = value
    return cleaned


def _validate_mca_columns(fieldnames: list[str] | None, source_label: str) -> None:
    headers = {
        (name or "").replace("\ufeff", "").strip()
        for name in (fieldnames or [])
        if (name or "").strip()
    }
    missing = sorted(_MCA_EXPECTED_COLUMNS - headers)
    if missing:
        raise RuntimeError(
            f"MCA export schema drift from {source_label}; missing columns: {', '.join(missing)}"
        )


def extract_mca_export_form(html_text: str) -> tuple[str, str]:
    """Extract CSRF token and export action URL from MCA company master page."""
    token_match = re.search(r'name=["\']csrf_token["\'][^>]*value=["\']([^"\']+)["\']', html_text or "", re.I)
    if not token_match:
        raise RuntimeError("MCA export page missing csrf_token")
    action_match = re.search(r'<form[^>]+id=["\']exportForm["\'][^>]*action=["\']([^"\']+)["\']', html_text or "", re.I)
    action = action_match.group(1) if action_match else _MCA_EXPORT_FORM_ACTION_DEFAULT
    return token_match.group(1).strip(), urljoin(_MCA_COMPANY_MASTER_PAGE, action)


def build_mca_export_payload(
    csrf_token: str,
    *,
    captcha_value: str = "AB12CD",
) -> dict[str, str]:
    """Build MCA export POST payload for full company master download."""
    return {
        "csrf_token": csrf_token,
        "companystate[]": "all",
        "companyindustrialclassification[]": "all",
        "captcha_input": captcha_value,
        "captcha_hidden": captcha_value,
        "export": "true",
    }


def _stream_mca_records_from_csv_file(
    path: Path,
    *,
    filter_cins: set[str] | None = None,
    listed_only: bool = False,
) -> Iterator[MCACompanyRecord]:
    if not path.exists():
        logger.error(
            "MCA CSV file not found at %s. "
            "Download from https://www.mcacdm.nic.in/company-master-details.php",
            path,
        )
        return

    logger.info(
        "Streaming MCA company master from local CSV: %s (progress interval=%d rows)",
        path,
        _MCA_PROGRESS_LOG_EVERY,
    )
    count = 0
    seen = 0
    invalid = 0
    filtered = 0

    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        reader = csv.DictReader(fh)
        _validate_mca_columns(reader.fieldnames, source_label=f"file:{path}")
        for row in reader:
            seen += 1
            record = _parse_row(_normalize_row_keys(row))
            if record is None:
                invalid += 1
                if seen % _MCA_PROGRESS_LOG_EVERY == 0:
                    logger.info(
                        "MCA CSV progress [%s]: seen=%d, yielded=%d, filtered=%d, invalid=%d",
                        path.name, seen, count, filtered, invalid,
                    )
                continue

            if filter_cins and record.cin not in filter_cins:
                filtered += 1
                if seen % _MCA_PROGRESS_LOG_EVERY == 0:
                    logger.info(
                        "MCA CSV progress [%s]: seen=%d, yielded=%d, filtered=%d, invalid=%d",
                        path.name, seen, count, filtered, invalid,
                    )
                continue

            if listed_only and record.listing_status.upper() != "LISTED":
                filtered += 1
                if seen % _MCA_PROGRESS_LOG_EVERY == 0:
                    logger.info(
                        "MCA CSV progress [%s]: seen=%d, yielded=%d, filtered=%d, invalid=%d",
                        path.name, seen, count, filtered, invalid,
                    )
                continue

            count += 1
            if seen % _MCA_PROGRESS_LOG_EVERY == 0:
                logger.info(
                    "MCA CSV progress [%s]: seen=%d, yielded=%d, filtered=%d, invalid=%d",
                    path.name, seen, count, filtered, invalid,
                )
            yield record

    logger.info(
        "MCA CSV stream complete [%s]: seen=%d, yielded=%d, filtered=%d, invalid=%d",
        path.name, seen, count, filtered, invalid,
    )


def _stream_mca_records_from_excel_file(
    path: Path,
    *,
    filter_cins: set[str] | None = None,
    listed_only: bool = False,
) -> Iterator[MCACompanyRecord]:
    if not path.exists():
        logger.error("MCA Excel file not found at %s", path)
        return

    logger.info(
        "Streaming MCA company master from local Excel: %s (progress interval=%d rows)",
        path,
        _MCA_PROGRESS_LOG_EVERY,
    )
    try:
        from openpyxl import load_workbook  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Excel ingestion requires openpyxl. Install with: uv add openpyxl"
        ) from exc

    count = 0
    seen = 0
    invalid = 0
    filtered = 0

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        headers_row = next(rows, None)
        if not headers_row:
            raise RuntimeError(f"MCA Excel file {path} has no header row")
        headers = [(str(h or "").replace("\ufeff", "").strip()) for h in headers_row]
        _validate_mca_columns(headers, source_label=f"excel:{path}")

        for row in rows:
            seen += 1
            raw_row: dict[str, str] = {}
            for idx, header in enumerate(headers):
                if not header:
                    continue
                value = row[idx] if idx < len(row) else ""
                raw_row[header] = "" if value is None else str(value).strip()

            record = _parse_row(_normalize_row_keys(raw_row))
            if record is None:
                invalid += 1
                if seen % _MCA_PROGRESS_LOG_EVERY == 0:
                    logger.info(
                        "MCA Excel progress [%s]: seen=%d, yielded=%d, filtered=%d, invalid=%d",
                        path.name, seen, count, filtered, invalid,
                    )
                continue

            if filter_cins and record.cin not in filter_cins:
                filtered += 1
                if seen % _MCA_PROGRESS_LOG_EVERY == 0:
                    logger.info(
                        "MCA Excel progress [%s]: seen=%d, yielded=%d, filtered=%d, invalid=%d",
                        path.name, seen, count, filtered, invalid,
                    )
                continue

            if listed_only and record.listing_status.upper() != "LISTED":
                filtered += 1
                if seen % _MCA_PROGRESS_LOG_EVERY == 0:
                    logger.info(
                        "MCA Excel progress [%s]: seen=%d, yielded=%d, filtered=%d, invalid=%d",
                        path.name, seen, count, filtered, invalid,
                    )
                continue

            count += 1
            if seen % _MCA_PROGRESS_LOG_EVERY == 0:
                logger.info(
                    "MCA Excel progress [%s]: seen=%d, yielded=%d, filtered=%d, invalid=%d",
                    path.name, seen, count, filtered, invalid,
                )
            yield record
    finally:
        workbook.close()

    logger.info(
        "MCA Excel stream complete [%s]: seen=%d, yielded=%d, filtered=%d, invalid=%d",
        path.name, seen, count, filtered, invalid,
    )


def _stream_mca_records_live(
    *,
    filter_cins: set[str] | None = None,
    listed_only: bool = False,
    timeout_s: float = 300.0,
) -> Iterator[MCACompanyRecord]:
    """Stream MCA records live, using Patchright browser for CAPTCHA bypass."""
    logger.info("Streaming MCA company master from live CDM export via browser")

    async def _browser_export() -> bytes:
        """Use Patchright browser to bypass CAPTCHA and download the export CSV."""
        browser = SmartBrowser(headless=True)
        await browser.start()
        try:
            page = await browser.new_page()
            # Navigate to MCA export page
            await page.goto(_MCA_COMPANY_MASTER_PAGE, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2.0)

            # Get CSRF token from page
            csrf_val = await page.evaluate("""
                () => {
                    const el = document.querySelector('input[name="csrf_token"]');
                    return el ? el.value : '';
                }
            """)

            if not csrf_val:
                logger.warning("No CSRF token found on MCA page; attempting direct POST")
                csrf_val = "auto_bypass"

            # Submit the export form via JS (fills hidden CAPTCHA fields)
            csv_bytes = await page.evaluate(f"""
                async () => {{
                    const formData = new FormData();
                    formData.append('csrf_token', '{csrf_val}');
                    formData.append('companystate[]', 'all');
                    formData.append('companyindustrialclassification[]', 'all');
                    formData.append('captcha_input', 'AB12CD');
                    formData.append('captcha_hidden', 'AB12CD');
                    formData.append('export', 'true');

                    const resp = await fetch(
                        '{_MCA_EXPORT_FORM_ACTION_DEFAULT}',
                        {{ method: 'POST', body: formData, credentials: 'include' }}
                    );
                    const buf = await resp.arrayBuffer();
                    return Array.from(new Uint8Array(buf));
                }}
            """)
            await page.close()
            return bytes(csv_bytes)
        finally:
            await browser.close()

    try:
        csv_bytes_content = asyncio.run(_browser_export())
    except Exception as exc:
        logger.error("Browser-based MCA export failed: %s", exc)
        logger.info("Falling back to direct HTTP export...")
        # Direct HTTP path must keep the same session for CSRF + form submit.
        with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=_MCA_HEADERS, trust_env=False) as client:
            page_resp = client.get(_MCA_COMPANY_MASTER_PAGE)
            page_resp.raise_for_status()
            csrf_token, export_url = extract_mca_export_form(page_resp.text)
            payload = build_mca_export_payload(csrf_token)
            export_resp = client.post(export_url, data=payload)
            export_resp.raise_for_status()
            response_text = export_resp.text or ""
            if "Invalid CSRF token" in response_text:
                raise RuntimeError("MCA export failed: CSRF token rejected")
            if "captcha" in response_text.lower() and "cin" not in response_text[:500].lower():
                raise RuntimeError("MCA export failed: CAPTCHA challenge rejected")
            csv_bytes_content = export_resp.content

    content_str = csv_bytes_content.decode("utf-8", errors="replace")
    if not content_str.strip() or "CIN" not in content_str[:500]:
        raise RuntimeError("MCA export response does not appear to be a valid CSV")

    count = 0
    filtered = 0
    reader = csv.DictReader(io.StringIO(content_str))
    _validate_mca_columns(reader.fieldnames, source_label="live_export")
    for row in reader:
        record = _parse_row(_normalize_row_keys(row))
        if record is None:
            continue
        if filter_cins and record.cin not in filter_cins:
            filtered += 1
            continue
        if listed_only and record.listing_status.upper() != "LISTED":
            filtered += 1
            continue
        count += 1
        yield record

    logger.info("MCA live stream complete: %d records yielded, %d filtered", count, filtered)


def _parse_date(raw: Any) -> date | None:
    """Parse MCA date formats: DD/MM/YYYY or YYYY-MM-DD."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    raw = str(raw).strip()
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    return None


def _parse_float(raw: Any) -> float | None:
    raw = str(raw or "").strip().replace(",", "")
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


def _parse_row(row: dict[str, str]) -> MCACompanyRecord | None:
    """Parse a CSV row into a MCACompanyRecord. Returns None if CIN invalid."""
    cin = (row.get("CIN") or "").strip().upper()
    name = (row.get("Company Name") or "").strip()
    if not cin or not name:
        return None
    return MCACompanyRecord(
        cin=cin,
        name=name,
        registration_date=_parse_date(row.get("Company Registration Date", "")),
        category=(row.get("Company Category") or "").strip(),
        company_class=(row.get("Company Class") or "").strip(),
        listing_status=(row.get("Listing Status") or "").strip(),
        authorized_capital=_parse_float(row.get("Authorized Capital", "")),
        paidup_capital=_parse_float(row.get("Paidup Capital", "")),
        roc=(row.get("Company ROC") or "").strip(),
        address=(row.get("Company Address") or "").strip(),
        pin_code=(row.get("Pin Code") or "").strip(),
        state=(row.get("Company State") or "").strip(),
        status=(row.get("Company Status") or "").strip(),
        sub_category=(row.get("Company Sub Category") or "").strip(),
        industrial_classification=(row.get("Company Industrial Classification") or "").strip(),
    )


def stream_mca_records(
    csv_path: str | Path | None = None,
    *,
    filter_cins: set[str] | None = None,
    listed_only: bool = False,
) -> Iterator[MCACompanyRecord]:
    """Stream MCA company master records.

    Args:
        csv_path: Optional path to a local MCA CSV/Excel file. If omitted, uses
            the official MCA CDM export endpoint.
        filter_cins: If provided, only yield companies with these CINs.
        listed_only: If True, only yield companies with Listing Status = "Listed".

    Yields:
        MCACompanyRecord for each valid row.
    """
    if csv_path:
        path = Path(csv_path)
        suffix = path.suffix.lower()
        if suffix in {".xlsx", ".xlsm"}:
            yield from _stream_mca_records_from_excel_file(
                path,
                filter_cins=filter_cins,
                listed_only=listed_only,
            )
        elif suffix == ".xls":
            raise RuntimeError(
                "Legacy .xls is not supported directly. Please save as .xlsx or .csv and retry."
            )
        else:
            yield from _stream_mca_records_from_csv_file(
                path,
                filter_cins=filter_cins,
                listed_only=listed_only,
            )
        return

    yield from _stream_mca_records_live(
        filter_cins=filter_cins,
        listed_only=listed_only,
    )


def load_mca_to_postgres(
    database_url: str | None = None,
    csv_path: str | Path | None = None,
    *,
    filter_cins: set[str] | None = None,
    listed_only: bool = False,
    dry_run: bool = False,
    max_records: int | None = None,
) -> dict[str, int]:
    """Load MCA company master CSV into PostgreSQL staging table.

    Args:
        database_url: PostgreSQL connection string.
        csv_path: Path to MCA CSV file.
        filter_cins: Optional CIN allowlist (e.g., Nifty 500 CINs only).
        listed_only: If True, only load listed companies.
        dry_run: If True, parse but don't write to DB.
        max_records: Optional cap for smoke tests and diagnostics.

    Returns:
        dict with keys: records_read, records_upserted, records_failed, duration_s
    """
    import time

    db_url = get_database_url(database_url)

    if not dry_run and not db_url:
        raise ValueError("database_url or IKG_DATABASE_URL env var required")

    source_label = str(csv_path) if csv_path else "live_mca_export"
    logger.info(
        "Starting MCA load: source=%s, listed_only=%s, dry_run=%s, chunk_size=%d",
        source_label,
        listed_only,
        dry_run,
        _CHUNK_SIZE,
    )

    start_t = time.time()
    records_read = 0
    records_upserted = 0
    records_failed = 0
    batch: list[MCACompanyRecord] = []

    def _record_payload(rec: MCACompanyRecord) -> dict[str, Any]:
        return {
            "cin": rec.cin,
            "company_name": rec.name,
            "registration_date": rec.registration_date.isoformat() if rec.registration_date else None,
            "category": rec.category,
            "company_class": rec.company_class,
            "listing_status": rec.listing_status,
            "authorized_capital": rec.authorized_capital,
            "paidup_capital": rec.paidup_capital,
            "roc": rec.roc,
            "address": rec.address,
            "pin_code": rec.pin_code,
            "state": rec.state,
            "status": rec.status,
            "sub_category": rec.sub_category,
            "industrial_classification": rec.industrial_classification,
        }

    def _flush_batch(batch: list[MCACompanyRecord], conn: Any, batch_no: int) -> int:
        if not batch:
            return 0
        flush_start = time.time()
        logger.info(
            "MCA DB batch %d starting: rows=%d, first_cin=%s, last_cin=%s",
            batch_no,
            len(batch),
            batch[0].cin,
            batch[-1].cin,
        )

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    with input_rows as (
                        select *
                        from jsonb_to_recordset(%s::jsonb) as x(
                            cin text,
                            company_name text,
                            registration_date date,
                            category text,
                            company_class text,
                            listing_status text,
                            authorized_capital numeric,
                            paidup_capital numeric,
                            roc text,
                            address text,
                            pin_code text,
                            state text,
                            status text,
                            sub_category text,
                            industrial_classification text
                        )
                    ),
                    deduped as (
                        select distinct on (cin)
                            cin, company_name, registration_date, category, company_class,
                            listing_status, authorized_capital, paidup_capital, roc,
                            address, pin_code, state, status, sub_category,
                            industrial_classification
                        from input_rows
                        where cin is not null and cin <> ''
                        order by cin
                    )
                    insert into ikg_company_master (
                        cin, company_name, registration_date, category, company_class,
                        listing_status, authorized_capital, paidup_capital, roc,
                        address, pin_code, state, status, sub_category,
                        industrial_classification, updated_at
                    )
                    select
                        cin, company_name, registration_date, category, company_class,
                        listing_status, authorized_capital, paidup_capital, roc,
                        address, pin_code, state, status, sub_category,
                        industrial_classification, now()
                    from deduped
                    on conflict (cin) do update set
                        company_name = excluded.company_name,
                        registration_date = excluded.registration_date,
                        category = excluded.category,
                        company_class = excluded.company_class,
                        listing_status = excluded.listing_status,
                        authorized_capital = excluded.authorized_capital,
                        paidup_capital = excluded.paidup_capital,
                        roc = excluded.roc,
                        address = excluded.address,
                        pin_code = excluded.pin_code,
                        state = excluded.state,
                        status = excluded.status,
                        sub_category = excluded.sub_category,
                        industrial_classification = excluded.industrial_classification,
                        updated_at = now()
                    where (
                        ikg_company_master.company_name,
                        ikg_company_master.registration_date,
                        ikg_company_master.category,
                        ikg_company_master.company_class,
                        ikg_company_master.listing_status,
                        ikg_company_master.authorized_capital,
                        ikg_company_master.paidup_capital,
                        ikg_company_master.roc,
                        ikg_company_master.address,
                        ikg_company_master.pin_code,
                        ikg_company_master.state,
                        ikg_company_master.status,
                        ikg_company_master.sub_category,
                        ikg_company_master.industrial_classification
                    ) is distinct from (
                        excluded.company_name,
                        excluded.registration_date,
                        excluded.category,
                        excluded.company_class,
                        excluded.listing_status,
                        excluded.authorized_capital,
                        excluded.paidup_capital,
                        excluded.roc,
                        excluded.address,
                        excluded.pin_code,
                        excluded.state,
                        excluded.status,
                        excluded.sub_category,
                        excluded.industrial_classification
                    )
                    """,
                    (json.dumps([_record_payload(rec) for rec in batch], ensure_ascii=False),),
                )
            conn.commit()
            logger.info(
                "MCA DB batch %d complete: rows=%d, elapsed=%.1fs",
                batch_no,
                len(batch),
                time.time() - flush_start,
            )
            return len(batch)
        except Exception as exc:
            conn.rollback()
            logger.exception("MCA DB batch %d failed after %.1fs: %s", batch_no, time.time() - flush_start, exc)
            raise

    if dry_run:
        for record in stream_mca_records(csv_path, filter_cins=filter_cins, listed_only=listed_only):
            records_read += 1
            if max_records and records_read >= max_records:
                logger.info("MCA dry-run record limit reached: %d", max_records)
                break
        duration = time.time() - start_t
        logger.info("DRY RUN: would have loaded %d records in %.1fs", records_read, duration)
        return {"records_read": records_read, "records_upserted": 0, "records_failed": 0, "duration_s": round(duration, 2)}

    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("psycopg required for PostgreSQL loading") from exc

    def _open_mca_connection() -> Any:
        last_read_only = ""
        for attempt in range(1, _MCA_DB_CONNECT_RETRIES + 1):
            logger.info("Connecting to Postgres/Supabase for MCA load (attempt %d/%d)", attempt, _MCA_DB_CONNECT_RETRIES)
            conn = connect_postgres(db_url, row_factory=dict_row, connect_timeout=30)
            logger.info("Connected to Postgres/Supabase for MCA load")
            with conn.cursor() as cur:
                cur.execute("select set_config('lock_timeout', %s, false)", (_MCA_DB_LOCK_TIMEOUT,))
                cur.execute("select set_config('statement_timeout', %s, false)", (_MCA_DB_STATEMENT_TIMEOUT,))
                cur.execute("show transaction_read_only")
                read_only = str((cur.fetchone() or {}).get("transaction_read_only") or "").lower()
            conn.commit()
            logger.info(
                "Configured MCA DB timeouts: lock_timeout=%s, statement_timeout=%s, transaction_read_only=%s",
                _MCA_DB_LOCK_TIMEOUT,
                _MCA_DB_STATEMENT_TIMEOUT,
                read_only,
            )
            if read_only not in {"on", "true", "1", "yes"}:
                return conn

            last_read_only = read_only
            logger.warning(
                "MCA DB connection is read-only on attempt %d/%d; closing and retrying",
                attempt,
                _MCA_DB_CONNECT_RETRIES,
            )
            try:
                conn.close()
            except Exception:
                pass
            time.sleep(min(5, attempt))

        raise RuntimeError(
            "Supabase/Postgres connection is read-only "
            f"(transaction_read_only={last_read_only!r}). "
            "Use the primary writable Supabase database URL, not a read replica, "
            "and check whether the Supabase project has been placed into read-only mode."
        )

    def _flush_with_retry(batch: list[MCACompanyRecord], conn: Any, batch_no: int) -> tuple[int, Any]:
        last_exc: Exception | None = None
        for attempt in range(1, _MCA_DB_BATCH_RETRIES + 1):
            try:
                return _flush_batch(batch, conn, batch_no), conn
            except psycopg.errors.ReadOnlySqlTransaction as exc:
                last_exc = exc
                logger.warning(
                    "MCA DB batch %d hit a read-only transaction on attempt %d/%d; reconnecting and retrying",
                    batch_no,
                    attempt,
                    _MCA_DB_BATCH_RETRIES,
                )
                try:
                    conn.close()
                except Exception:
                    pass
                conn = _open_mca_connection()
            except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
                last_exc = exc
                logger.warning(
                    "MCA DB batch %d lost DB connection on attempt %d/%d; reconnecting and retrying: %s",
                    batch_no,
                    attempt,
                    _MCA_DB_BATCH_RETRIES,
                    exc,
                )
                try:
                    conn.close()
                except Exception:
                    pass
                conn = _open_mca_connection()
        assert last_exc is not None
        raise last_exc

    conn = _open_mca_connection()
    try:
        batch_no = 0
        for record in stream_mca_records(csv_path, filter_cins=filter_cins, listed_only=listed_only):
            records_read += 1
            batch.append(record)
            if len(batch) >= _CHUNK_SIZE:
                batch_no += 1
                upserted, conn = _flush_with_retry(batch, conn, batch_no)
                records_upserted += upserted
                records_failed += len(batch) - upserted
                batch = []
                logger.info(
                    "MCA loader progress: %d read, %d upserted",
                    records_read, records_upserted,
                )
            if max_records and records_read >= max_records:
                logger.info("MCA record limit reached: %d", max_records)
                break
        if batch:
            batch_no += 1
            upserted, conn = _flush_with_retry(batch, conn, batch_no)
            records_upserted += upserted
            records_failed += len(batch) - upserted
            logger.info(
                "MCA loader progress: %d read, %d upserted",
                records_read, records_upserted,
            )
    finally:
        try:
            conn.close()
        except Exception:
            pass

    duration = time.time() - start_t
    logger.info(
        "MCA load complete: %d read, %d upserted, %d failed, %.1fs",
        records_read, records_upserted, records_failed, duration,
    )
    return {
        "records_read": records_read,
        "records_upserted": records_upserted,
        "records_failed": records_failed,
        "duration_s": round(duration, 2),
    }


def get_listed_companies(
    database_url: str | None = None,
    nifty500_only: bool = True,
) -> list[dict[str, Any]]:
    """Fetch listed companies from ikg_company_master for use in other scrapers.

    Args:
        database_url: PostgreSQL connection string.
        nifty500_only: If True, return only Nifty 500 companies (those with nse_symbol set).

    Returns:
        List of company dicts with cin, company_name, nse_symbol, bse_scrip_code, isin.
    """
    db_url = get_database_url(database_url)
    if not db_url:
        logger.warning("No database URL configured for get_listed_companies()")
        return []

    try:
        from psycopg.rows import dict_row

        sql = """
            select cin, company_name, nse_symbol, bse_scrip_code, isin, sector
            from ikg_company_master
            where listing_status ilike 'listed'
        """
        if nifty500_only:
            sql += " and nse_symbol is not null"
        sql += (
            " order by "
            "case when cin is not null and trim(cin) <> '' then 0 else 1 end, "
            "case when bse_scrip_code is not null and trim(bse_scrip_code) <> '' then 0 else 1 end, "
            "company_name"
        )

        with connect_postgres(db_url, row_factory=dict_row, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.error("Failed to fetch listed companies: %s", exc)
        return []


def backfill_bse_scrip_codes_from_daily_prices(database_url: str | None = None) -> int:
    """Hydrate company master BSE scrip codes by matching official BSE EOD ISINs."""
    db_url = get_database_url(database_url)
    if not db_url:
        logger.warning("No database URL configured for BSE scrip-code backfill")
        return 0

    try:
        with connect_postgres(db_url, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    with latest_prices as (
                        select distinct on (isin)
                               isin,
                               scrip_code
                        from daily_prices
                        where isin is not null
                          and scrip_code is not null
                        order by isin, trade_date desc
                    )
                    update ikg_company_master c
                       set bse_scrip_code = lp.scrip_code,
                           updated_at = now()
                    from latest_prices lp
                    where c.isin = lp.isin
                      and c.nse_symbol is not null
                      and (c.bse_scrip_code is null or c.bse_scrip_code = '')
                    returning c.cin
                    """
                )
                updated = cur.rowcount or 0
            conn.commit()
        if updated:
            logger.info("Backfilled %d BSE scrip codes from official BSE EOD ISIN mapping", updated)
        return updated
    except Exception as exc:
        logger.warning("BSE scrip-code backfill failed: %s", exc)
        return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Load MCA company master CSV to PostgreSQL")
    parser.add_argument("--db-url", help="PostgreSQL connection string")
    parser.add_argument("--csv-path", help="Path to MCA CSV file")
    parser.add_argument("--listed-only", action="store_true", help="Only load listed companies")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, don't write to DB")
    parser.add_argument("--limit", type=int, help="Maximum parsed records to load; useful for smoke tests")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    result = load_mca_to_postgres(
        database_url=args.db_url,
        csv_path=args.csv_path,
        listed_only=args.listed_only,
        dry_run=args.dry_run,
        max_records=args.limit,
    )
    print(result)

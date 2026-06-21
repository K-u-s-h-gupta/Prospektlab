"""IKG Pipeline Orchestrator — runs all data pipeline tasks in order.

This module coordinates the complete data ingestion pipeline:
  Phase 1: Load MCA company master (already downloaded CSV)
  Phase 2: Fetch Nifty 500 list from NSE API
  Phase 3: Scrape BSE shareholding patterns (quarterly)
  Phase 4: Scrape BSE EOD prices (daily)
  Phase 5: Refresh directors/KMP from governance filings (NSE/BSE/SEBI maps)
  Phase 6: Scrape financial data (quarterly)
  Phase 7: Scrape SEBI enforcement orders (weekly)
  Phase 8: Enrich directors/KMP from annual-report board sections + SEBI filing docs

Each phase has health monitoring:
  - Records fetched, records failed, duration, last_run_timestamp
  - Alerting on: scraper failure, data freshness > threshold, IKG node count anomaly
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from finagent.ikg.db import connect_postgres, ensure_ikg_runtime_tables, get_database_url, is_supabase_database_url

logger = logging.getLogger("finagent.ikg.pipeline.orchestrator")

_DATABASE_URL = get_database_url()
_PIPELINE_LOG_DIR = Path(os.getenv("FINAGENT_PIPELINE_LOG_DIR", "pipeline_logs"))
_PARALLEL_MAX_WORKERS = max(1, int(os.getenv("FINAGENT_PIPELINE_PARALLEL_WORKERS", "6")))


@dataclass
class PipelineRunResult:
    """Result of a single pipeline task run."""
    task_name: str
    started_at: str = ""
    completed_at: str = ""
    duration_s: float = 0.0
    records_fetched: int = 0
    records_stored: int = 0
    records_failed: int = 0
    success: bool = False
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _log_run_result(result: PipelineRunResult) -> None:
    """Write pipeline run result to JSONL and Supabase/Postgres if configured."""
    try:
        _PIPELINE_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = _PIPELINE_LOG_DIR / f"pipeline_{time.strftime('%Y%m%d')}.jsonl"
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(result.to_dict(), default=str) + "\n")
    except Exception as exc:
        logger.warning("Failed to write pipeline log: %s", exc)

    try:
        from finagent.ikg.pipeline.run_store import persist_pipeline_run

        persist_pipeline_run(result)
    except Exception as exc:
        logger.warning("Failed to persist pipeline run: %s", exc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_mca_bootstrap(
    csv_path: str | None = None,
    listed_only: bool = False,
) -> PipelineRunResult:
    """Phase 1: Load MCA company master from the downloaded CSV."""
    result = PipelineRunResult(task_name="mca_bootstrap", started_at=_now_iso())
    start_t = time.time()
    csv_path = csv_path or os.getenv("MCA_COMPANY_MASTER_CSV")
    result.metadata = {
        "source_name": "MCA company master",
        "official_source_url": "https://www.mcacdm.nic.in/company-master-details.php",
        "parser_version": "mca_company_master_csv_v2",
        "csv_path": csv_path,
        "listed_only": listed_only,
    }

    try:
        from finagent.ikg.scrapers.mca_companies import load_mca_to_postgres

        stats = load_mca_to_postgres(
            database_url=_DATABASE_URL,
            csv_path=csv_path,
            listed_only=listed_only,
        )
        result.records_fetched = stats.get("records_read", 0)
        result.records_stored = stats.get("records_upserted", 0)
        result.records_failed = stats.get("records_failed", 0)
        result.success = True

    except Exception as exc:
        logger.error("MCA bootstrap failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_nse_nifty500_refresh() -> PipelineRunResult:
    """Phase 2: Fetch the latest configured NSE constituent universe."""
    result = PipelineRunResult(task_name="nse_nifty500_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": f"NSE {_configured_universe_label()}",
        "official_source_url": "https://niftyindices.com/IndexConstituent/",
        "parser_version": "nse_index_v3",
    }
    start_t = time.time()

    try:
        from finagent.ikg.scrapers.nse_index import run_nse_index_scraper

        stats = run_nse_index_scraper(database_url=_DATABASE_URL)
        result.records_fetched = stats.get("companies_fetched", 0)
        result.records_stored = stats.get("companies_upserted", 0)
        result.success = stats.get("success", False)
        result.error = stats.get("error")
        result.metadata.update(
            {
                "universe": stats.get("universe"),
                "universe_label": stats.get("universe_label"),
            }
        )

    except Exception as exc:
        logger.error("NSE universe refresh failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def _configured_shp_quarters(default: int = 40) -> int:
    try:
        return max(1, int(os.getenv("FINAGENT_SHP_QUARTERS", str(default)) or str(default)))
    except ValueError:
        return default


def _configured_years_back(default: int = 3) -> int:
    raw = (os.getenv("FINAGENT_PIPELINE_YEARS_BACK") or "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("Invalid FINAGENT_PIPELINE_YEARS_BACK=%r; using default=%d", raw, default)
        return default


def _configured_universe_label() -> str:
    return (os.getenv("FINAGENT_NSE_UNIVERSE_LABEL") or os.getenv("FINAGENT_NSE_UNIVERSE") or "All Listed").strip()


def _listed_company_scope() -> str:
    raw = (os.getenv("FINAGENT_LISTED_COMPANY_SCOPE") or "").strip().lower()
    if raw in {"all", "all_listed", "listed"}:
        return "all_listed"
    if raw in {"indexed", "index_only", "nifty", "nifty500", "nifty1000"}:
        return "indexed"
    return "all_listed"


def _use_indexed_listed_companies() -> bool:
    return _listed_company_scope() == "indexed"


def _last_successful_completed_at(task_name: str, *, lookback_minutes: int = 15) -> str | None:
    db_url = get_database_url(_DATABASE_URL)
    if not db_url:
        return None
    try:
        from psycopg.rows import dict_row

        with connect_postgres(db_url, row_factory=dict_row, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select completed_at
                    from ikg_pipeline_runs
                    where task_name = %s
                      and success = true
                    order by completed_at desc
                    limit 1
                    """,
                    (task_name,),
                )
                row = cur.fetchone() or {}
        completed_at = row.get("completed_at")
        if not completed_at:
            return None
        if isinstance(completed_at, datetime):
            completed_dt = completed_at
        else:
            completed_dt = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
        completed_dt = completed_dt - timedelta(minutes=max(0, lookback_minutes))
        return completed_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception as exc:
        logger.debug("Unable to determine last successful %s run: %s", task_name, exc)
        return None


def _make_skipped_result(
    task_name: str,
    *,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> PipelineRunResult:
    result = PipelineRunResult(
        task_name=task_name,
        started_at=_now_iso(),
        completed_at=_now_iso(),
        duration_s=0.0,
        success=True,
        metadata={
            "skipped": True,
            "reason": reason,
            **(metadata or {}),
        },
    )
    _log_run_result(result)
    return result


def _is_bounded_run(max_companies: int | None) -> bool:
    return max_companies is not None and int(max_companies) > 0


def _bounded_attachment_limit(max_companies: int | None) -> int | None:
    if not _is_bounded_run(max_companies):
        return None
    return max(25, min(250, int(max_companies) * 40))


def _bounded_qdrant_limit(max_companies: int | None) -> int | None:
    if not _is_bounded_run(max_companies):
        return None
    return max(100, min(2000, int(max_companies) * 150))


def run_bse_shp_refresh(quarters: int | None = None, max_companies: int | None = None) -> PipelineRunResult:
    """Phase 3: Scrape BSE shareholding patterns for Nifty 500."""
    result = PipelineRunResult(task_name="bse_shp_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": "BSE shareholding pattern",
        "official_source_url": "https://www.bseindia.com/corporates/Sharehold_Searchnew",
        "parser_version": "bse_shp_v2",
    }
    start_t = time.time()

    try:
        from finagent.ikg.scrapers.mca_companies import (
            backfill_bse_scrip_codes_from_daily_prices,
            get_listed_companies,
        )
        from finagent.ikg.scrapers.bse_shp import run_bse_shp_scraper

        backfill_bse_scrip_codes_from_daily_prices(database_url=_DATABASE_URL)
        companies = get_listed_companies(
            database_url=_DATABASE_URL,
            indexed_only=_use_indexed_listed_companies(),
        )
        if companies and not any(co.get("bse_scrip_code") for co in companies):
            from finagent.ikg.scrapers.bse_eod import run_bse_eod_scraper

            logger.info("No BSE scrip codes found; running BSE EOD once to hydrate ISIN mapping")
            run_bse_eod_scraper(database_url=_DATABASE_URL)
            backfill_bse_scrip_codes_from_daily_prices(database_url=_DATABASE_URL)
            companies = get_listed_companies(
                database_url=_DATABASE_URL,
                indexed_only=_use_indexed_listed_companies(),
            )
        if not companies:
            result.error = "No companies found in ikg_company_master"
            result.success = False
        else:
            stats = run_bse_shp_scraper(
                companies=companies,
                database_url=_DATABASE_URL,
                quarters=quarters or _configured_shp_quarters(),
                max_companies=max_companies,
            )
            result.records_fetched = stats.get("records_fetched", 0)
            result.records_stored = stats.get("records_stored", 0)
            result.records_failed = stats.get("errors", 0)
            result.metadata.update({
                "quarters": stats.get("quarters_fetched", []),
                "http_status": stats.get("http_status"),
            })
            result.success = True

    except Exception as exc:
        logger.error("BSE SHP refresh failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_bse_eod_daily() -> PipelineRunResult:
    """Phase 4: Download today's BSE EOD prices."""
    result = PipelineRunResult(task_name="bse_eod_daily", started_at=_now_iso())
    result.metadata = {
        "source_name": "BSE bhavcopy",
        "official_source_url": "https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx",
        "parser_version": "bse_eod_v2",
    }
    start_t = time.time()

    try:
        from finagent.ikg.scrapers.bse_eod import run_bse_eod_scraper

        stats = run_bse_eod_scraper(database_url=_DATABASE_URL)
        result.records_fetched = stats.get("records_parsed", 0)
        result.records_stored = stats.get("records_stored", 0)
        result.success = stats.get("success", False)
        result.error = stats.get("error")
        result.metadata.update({"trade_date": stats.get("trade_date")})

    except Exception as exc:
        logger.error("BSE EOD daily run failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_mca_director_refresh(max_companies: int | None = None) -> PipelineRunResult:
    """Deprecated: MCA CAPTCHA-based director scraping is disabled."""
    result = PipelineRunResult(task_name="mca_director_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": "MCA director master (deprecated)",
        "official_source_url": "https://www.mca.gov.in/",
        "parser_version": "mca_directors_disabled_v2",
        "deprecated": True,
        "reason": (
            "MCA CAPTCHA flow is intentionally disabled. "
            "Use corporate_governance_director_refresh + annual report board sections + SEBI filings."
        ),
    }
    result.duration_s = 0.0
    result.completed_at = _now_iso()
    result.success = True
    logger.info("MCA director refresh skipped: deprecated CAPTCHA scraper is disabled.")
    _log_run_result(result)
    return result


def run_corporate_governance_director_refresh(
    max_companies: int | None = None,
    years_back: int = 2,
) -> PipelineRunResult:
    """Refresh directors from official NSE/BSE corporate governance filings."""
    result = PipelineRunResult(task_name="corporate_governance_director_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": "NSE/BSE corporate governance filings",
        "official_source_url": "https://www.sebi.gov.in/curation/corporate_filings.html",
        "parser_version": "corporate_governance_directors_v1",
        "years_back": years_back,
    }
    start_t = time.time()

    try:
        from finagent.ikg.scrapers.corporate_governance_directors import (
            run_corporate_governance_director_scraper,
        )
        from finagent.ikg.scrapers.mca_companies import get_listed_companies

        companies = get_listed_companies(
            database_url=_DATABASE_URL,
            indexed_only=_use_indexed_listed_companies(),
            require_cin=True,
        )
        if not companies:
            result.error = "No listed companies available for corporate governance director refresh"
            result.success = False
        else:
            stats = run_corporate_governance_director_scraper(
                companies=companies,
                database_url=_DATABASE_URL,
                max_companies=max_companies,
                years_back=years_back,
            )
            result.records_fetched = stats.get("directors_found", 0)
            result.records_stored = stats.get("directors_stored", 0)
            result.records_failed = stats.get("errors", 0)
            result.success = bool(stats.get("success", result.records_stored > 0))
            if not result.success and not result.records_stored:
                if int(stats.get("companies_processed") or 0) == 0:
                    result.error = "No listed companies with CIN mappings were available for governance director refresh"
                else:
                    result.error = "Governance director refresh stored no directors"
            result.metadata.update(
                {
                    "companies_processed": stats.get("companies_processed", 0),
                    "filings_found": stats.get("filings_found", 0),
                    "filings_processed": stats.get("filings_processed", 0),
                }
            )

    except Exception as exc:
        logger.error("Corporate governance director refresh failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_financial_data_refresh(max_companies: int | None = None) -> PipelineRunResult:
    """Phase 6: Refresh financial data (yfinance + Screener.in cross-validate)."""
    result = PipelineRunResult(task_name="financial_data_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": "financial data",
        "official_source_url": "https://finance.yahoo.com/,https://www.screener.in/",
        "parser_version": "financial_data_v1",
    }
    start_t = time.time()

    try:
        from finagent.ikg.scrapers.mca_companies import get_listed_companies
        from finagent.ikg.scrapers.financial_data import run_financial_data_scraper

        companies = get_listed_companies(
            database_url=_DATABASE_URL,
            indexed_only=_use_indexed_listed_companies(),
        )
        if not companies:
            result.error = "No listed companies available for financial refresh"
            result.success = False
        else:
            stats = run_financial_data_scraper(
                companies=companies,
                database_url=_DATABASE_URL,
                max_companies=max_companies,
            )
            result.records_fetched = stats.get("companies_processed", 0)
            result.records_stored = stats.get("validated_stored", 0)
            source_hits = int(stats.get("yf_success", 0) or 0) + int(stats.get("screener_success", 0) or 0)
            result.records_failed = max(0, int(result.records_fetched or 0) - int(result.records_stored or 0))
            result.success = bool(result.records_stored) and source_hits > 0
            if not result.success:
                result.error = "No financial source payloads were stored for the selected companies"
            result.metadata.update({
                "yfinance_success": stats.get("yf_success", 0),
                "screener_success": stats.get("screener_success", 0),
            })

    except Exception as exc:
        logger.error("Financial data refresh failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_sebi_enforcement_refresh(pages: int = 2) -> PipelineRunResult:
    """Phase 7: Scrape SEBI enforcement orders."""
    result = PipelineRunResult(task_name="sebi_enforcement_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": "SEBI enforcement orders",
        "official_source_url": "https://www.sebi.gov.in/enforcement/orders.html",
        "parser_version": "sebi_enforcement_v3",
    }
    start_t = time.time()

    try:
        from finagent.ikg.scrapers.sebi_enforcement import run_sebi_enforcement_scraper

        stats = run_sebi_enforcement_scraper(pages=pages, database_url=_DATABASE_URL)
        result.records_fetched = stats.get("orders_fetched", 0)
        result.records_stored = stats.get("orders_stored", 0)
        result.records_failed = stats.get("errors", 0)
        result.success = stats.get("success", result.records_stored > 0 or result.records_fetched == 0)
        result.metadata.update({
            "orders_processed": stats.get("orders_processed", 0),
            "categories": stats.get("categories", []),
            "http_status": stats.get("http_status"),
        })
        result.error = stats.get("error")

    except Exception as exc:
        logger.error("SEBI enforcement refresh failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_sebi_corporate_filing_map_refresh() -> PipelineRunResult:
    """Refresh SEBI corporate filing navigation map."""
    result = PipelineRunResult(task_name="sebi_corporate_filing_map_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": "SEBI corporate filing curation",
        "official_source_url": "https://www.sebi.gov.in/curation/corporate_filings.html",
        "parser_version": "sebi_corporate_filings_v2",
    }
    start_t = time.time()

    try:
        from finagent.ikg.scrapers.sebi_corporate_filings import run_sebi_corporate_filing_map_scraper

        stats = run_sebi_corporate_filing_map_scraper(database_url=_DATABASE_URL)
        result.records_fetched = stats.get("records_fetched", 0)
        result.records_stored = stats.get("records_stored", 0)
        result.records_failed = stats.get("errors", 0)
        result.success = bool(stats.get("success", result.records_stored > 0))
        result.metadata.update({
            "categories": stats.get("categories", []),
            "http_status": stats.get("http_status"),
        })
        result.error = stats.get("error")

    except Exception as exc:
        logger.error("SEBI corporate filing map refresh failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_corporate_filing_documents_refresh(
    max_companies: int | None = None,
    years_back: int = 1,
) -> PipelineRunResult:
    """Fetch filings behind the SEBI curation map from NSE/BSE official sources."""
    result = PipelineRunResult(task_name="corporate_filing_documents_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": "NSE/BSE corporate filings",
        "official_source_url": "https://www.sebi.gov.in/curation/corporate_filings.html",
        "parser_version": "corporate_filings_documents_v1",
        "years_back": years_back,
    }
    start_t = time.time()

    try:
        from finagent.ikg.scrapers.bse_eod import run_bse_eod_scraper
        from finagent.ikg.scrapers.mca_companies import (
            backfill_bse_scrip_codes_from_daily_prices,
            get_listed_companies,
        )
        from finagent.ikg.scrapers.sebi_corporate_filings import (
            run_corporate_filing_documents_scraper,
            run_sebi_corporate_filing_map_scraper,
        )

        run_sebi_corporate_filing_map_scraper(database_url=_DATABASE_URL)
        backfill_bse_scrip_codes_from_daily_prices(database_url=_DATABASE_URL)
        companies = get_listed_companies(
            database_url=_DATABASE_URL,
            indexed_only=_use_indexed_listed_companies(),
        )
        if companies and not any(co.get("bse_scrip_code") for co in companies):
            run_bse_eod_scraper(database_url=_DATABASE_URL)
            backfill_bse_scrip_codes_from_daily_prices(database_url=_DATABASE_URL)
            companies = get_listed_companies(
                database_url=_DATABASE_URL,
                indexed_only=_use_indexed_listed_companies(),
            )
        if not companies:
            result.error = "No listed companies available for corporate filing document refresh"
            result.success = False
        else:
            stats = run_corporate_filing_documents_scraper(
                companies,
                database_url=_DATABASE_URL,
                max_companies=max_companies,
                years_back=years_back,
            )
            result.records_fetched = stats.get("records_fetched", 0)
            result.records_stored = stats.get("records_stored", 0)
            result.records_failed = stats.get("errors", 0)
            result.success = bool(stats.get("success", result.records_stored > 0))
            result.metadata.update(
                {
                    "companies_processed": stats.get("companies_processed", 0),
                    "companies_with_records": stats.get("companies_with_records", 0),
                    "categories": stats.get("categories", []),
                    "attachments_extracted": stats.get("attachments_extracted", 0),
                    "attachments_failed": stats.get("attachments_failed", 0),
                    "xbrl_filings": stats.get("xbrl_filings", 0),
                    "xbrl_facts": stats.get("xbrl_facts", 0),
                    "corporate_actions_stored": stats.get("corporate_actions_stored", 0),
                }
            )
            result.error = stats.get("error")

    except Exception as exc:
        logger.error("Corporate filing document refresh failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_corporate_filing_attachment_hydration(limit: int | None = None) -> PipelineRunResult:
    """Resume extraction for already-stored corporate filing attachments."""
    result = PipelineRunResult(task_name="corporate_filing_attachment_hydration", started_at=_now_iso())
    result.metadata = {
        "source_name": "NSE/BSE corporate filing attachments",
        "official_source_url": "staging://corporate_filings_raw",
        "parser_version": "corporate_filings_attachment_hydration_v1",
        "limit": limit,
    }
    start_t = time.time()
    try:
        from finagent.ikg.scrapers.sebi_corporate_filings import hydrate_stored_corporate_filing_attachments

        stats = hydrate_stored_corporate_filing_attachments(database_url=_DATABASE_URL, limit=limit)
        result.records_fetched = int(stats.get("records_seen") or 0)
        result.records_stored = int(stats.get("attachments_extracted") or 0)
        result.records_failed = int(stats.get("attachments_failed") or 0)
        result.success = result.records_failed == 0
        result.metadata.update(stats)
    except Exception as exc:
        logger.error("Corporate filing attachment hydration failed: %s", exc)
        result.error = str(exc)
        result.success = False
    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_annual_reports_refresh(max_companies: int | None = None) -> PipelineRunResult:
    """Fetch and store official BSE annual report metadata by default."""
    result = PipelineRunResult(task_name="annual_reports_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": "BSE annual reports",
        "official_source_url": "https://www.bseindia.com/corporates/annualdisplay.aspx",
        "parser_version": "bse_annual_reports_v2",
        "extract_mode": os.getenv("FINAGENT_ANNUAL_REPORT_EXTRACT_MODE", "metadata_only"),
    }
    start_t = time.time()

    try:
        from finagent.ikg.scrapers.mca_companies import get_listed_companies
        from finagent.ikg.scrapers.annual_reports import run_annual_report_pipeline

        companies = get_listed_companies(
            database_url=_DATABASE_URL,
            indexed_only=_use_indexed_listed_companies(),
        )
        if not companies:
            result.error = "No listed companies available for annual report refresh"
            result.success = False
        else:
            stats = run_annual_report_pipeline(
                companies=companies,
                database_url=_DATABASE_URL,
                max_companies=max_companies,
            )
            result.records_fetched = stats.get("reports_found", 0)
            result.records_stored = stats.get("reports_persisted", 0)
            result.records_failed = stats.get("errors", 0)
            result.success = stats.get("errors", 0) == 0
            if not result.success and not result.error:
                result.error = "Annual report metadata fetch failed for one or more selected companies"
            result.metadata.update({
                "companies_processed": stats.get("companies_processed", 0),
                "reports_downloaded": stats.get("reports_downloaded", 0),
                "reports_persisted": stats.get("reports_persisted", 0),
                "chunks_indexed": stats.get("chunks_indexed", 0),
            })

    except Exception as exc:
        logger.error("Annual reports refresh failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_concall_transcripts_refresh(
    max_companies: int | None = None,
    years_back: int = 3,
) -> PipelineRunResult:
    """Fetch and index verified NSE concall transcripts for Nifty 500 companies."""
    result = PipelineRunResult(task_name="concall_transcripts_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": "NSE corporate announcements (concall transcripts)",
        "official_source_url": "https://www.nseindia.com/api/corporate-announcements",
        "parser_version": "nse_concall_transcripts_v1",
        "years_back": years_back,
    }
    start_t = time.time()

    try:
        from finagent.ikg.scrapers.mca_companies import get_listed_companies
        from finagent.ikg.scrapers.concall_transcripts import run_concall_transcript_scraper

        companies = get_listed_companies(
            database_url=_DATABASE_URL,
            indexed_only=_use_indexed_listed_companies(),
        )
        if not companies:
            result.error = "No listed companies available for concall transcript refresh"
            result.success = False
        else:
            stats = run_concall_transcript_scraper(
                companies=companies,
                database_url=_DATABASE_URL,
                max_companies=max_companies,
                years_back=years_back,
            )
            result.records_fetched = stats.get("announcements_fetched", 0)
            result.records_stored = stats.get("transcripts_stored", 0)
            result.records_failed = stats.get("transcripts_failed", 0) + stats.get("errors", 0)
            result.success = bool(stats.get("success", True))
            result.metadata.update(
                {
                    "chunks_indexed": stats.get("chunks_indexed", 0),
                    "edges_written": stats.get("edges_written", 0),
                    "companies_processed": stats.get("companies_processed", 0),
                }
            )
    except Exception as exc:
        logger.error("Concall transcript refresh failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_director_kmp_enrichment_refresh(
    max_companies: int | None = None,
    years_back: int = 3,
) -> PipelineRunResult:
    """Enrich directors/KMP from governance docs + annual report board sections + SEBI filing docs."""
    result = PipelineRunResult(task_name="director_kmp_enrichment_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": "Director/KMP document enrichment",
        "official_source_url": "staging://director_source_records,document_sections,corporate_filings_raw",
        "parser_version": "director_kmp_enricher_v1",
        "years_back": years_back,
    }
    start_t = time.time()
    try:
        from finagent.ikg.scrapers.mca_companies import get_listed_companies
        from finagent.ikg.scrapers.director_kmp_enricher import run_director_kmp_enrichment

        companies = get_listed_companies(
            database_url=_DATABASE_URL,
            indexed_only=_use_indexed_listed_companies(),
            require_cin=True,
        )
        if not companies:
            result.error = "No listed companies available for director/KMP enrichment"
            result.success = False
        else:
            stats = run_director_kmp_enrichment(
                companies=companies,
                database_url=_DATABASE_URL,
                max_companies=max_companies,
                years_back=years_back,
            )
            result.records_fetched = int(stats.get("director_candidates") or 0)
            result.records_stored = int(stats.get("directors_stored") or 0)
            result.records_failed = int(stats.get("errors") or 0)
            result.success = bool(stats.get("success", result.records_stored > 0))
            result.error = stats.get("error")
            if not result.success and not result.records_stored:
                if int(stats.get("companies_considered") or 0) == 0:
                    result.error = "No listed companies with CIN mappings were available for director/KMP enrichment"
                else:
                    result.error = result.error or "Director/KMP enrichment stored no directors"
            result.metadata.update(
                {
                    "documents_scanned": int(stats.get("documents_scanned") or 0),
                    "companies_considered": int(stats.get("companies_considered") or 0),
                }
            )
    except Exception as exc:
        logger.error("Director/KMP enrichment refresh failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_failure_events_refresh() -> PipelineRunResult:
    """IGS Phase A: mine failure-event labels (MCA status + SEBI debarment)."""
    result = PipelineRunResult(task_name="failure_events_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": "MCA master status + SEBI enforcement",
        "official_source_url": "staging://ikg_company_master.status,enforcement_raw",
        "parser_version": "failure_labels_v1",
    }
    start_t = time.time()
    try:
        from finagent.ikg.scrapers.failure_labels import run_failure_label_refresh

        stats = run_failure_label_refresh(database_url=_DATABASE_URL)
        mca = stats.get("mca", {})
        sebi = stats.get("sebi", {})
        result.records_stored = int(mca.get("rows_upserted", 0) or 0) + int(sebi.get("rows_upserted", 0) or 0)
        result.records_fetched = int(mca.get("total_failures", 0) or 0)
        result.success = bool(stats.get("success"))
        if not result.success:
            result.error = mca.get("error") or sebi.get("error") or "failure label mining incomplete"
        result.metadata.update({
            "mca_rows_upserted": mca.get("rows_upserted"),
            "mca_total_failures": mca.get("total_failures"),
            "sebi_rows_upserted": sebi.get("rows_upserted"),
            "sebi_orders_scanned": sebi.get("orders_scanned"),
        })
    except Exception as exc:
        logger.error("Failure events refresh failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_company_features_refresh(as_of: str | None = None, max_companies: int | None = None) -> PipelineRunResult:
    """IGS Phase B: materialise company_features (temporal + graph) for listed companies."""
    result = PipelineRunResult(task_name="company_features_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": "IKG graph + staging",
        "official_source_url": "staging://shp_raw,directors_raw,auditor_history_raw,ikg_edges",
        "parser_version": "igs_features_v1",
    }
    start_t = time.time()
    try:
        from finagent.ikg.igs.feature_builder import build_company_features
        from finagent.ikg.scrapers.mca_companies import get_listed_companies

        cins: set[str] | None = None
        if max_companies:
            companies = get_listed_companies(database_url=_DATABASE_URL, indexed_only=_use_indexed_listed_companies())
            cins = {str(c.get("cin")).strip() for c in companies[:max_companies] if c.get("cin")}
        stats = build_company_features(database_url=_DATABASE_URL, cins=cins, as_of=as_of)
        result.records_stored = int(stats.get("rows_upserted", 0) or 0)
        result.records_fetched = int(stats.get("companies", 0) or 0)
        result.success = bool(stats.get("success"))
        result.error = stats.get("error")
        result.metadata.update({k: stats.get(k) for k in ("companies", "note")})
    except Exception as exc:
        logger.error("Company features refresh failed: %s", exc)
        result.error = str(exc)
        result.success = False
    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_igs_model_train(as_of: str | None = None) -> PipelineRunResult:
    """IGS Phase C: train the LightGBM failure model on company_features vs failure_events."""
    result = PipelineRunResult(task_name="igs_model_train", started_at=_now_iso())
    result.metadata = {
        "source_name": "company_features + failure_events",
        "official_source_url": "staging://company_features,failure_events",
        "parser_version": "igs_model_v1",
    }
    start_t = time.time()
    try:
        from finagent.ikg.igs.model import train_failure_model

        stats = train_failure_model(database_url=_DATABASE_URL, as_of=as_of)
        result.records_fetched = int(stats.get("n_train", 0) or 0)
        result.records_stored = int(stats.get("n_pos", 0) or 0)
        result.success = bool(stats.get("success"))
        result.error = stats.get("error")
        result.metadata.update({k: stats.get(k) for k in ("auc_cv", "n_train", "n_pos", "n_neg", "backend", "model_path", "model_version")})
    except Exception as exc:
        logger.error("IGS model train failed: %s", exc)
        result.error = str(exc)
        result.success = False
    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_igs_scoring_refresh(as_of: str | None = None, max_companies: int | None = None) -> PipelineRunResult:
    """IGS Phase D: score all listed companies (rules + model) into company_governance_scores history."""
    result = PipelineRunResult(task_name="igs_scoring_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": "governance rules + IGS model",
        "official_source_url": "staging://company_features,governance_score",
        "parser_version": "igs_scoring_v1",
    }
    start_t = time.time()
    try:
        from finagent.ikg.igs.scoring import score_all_listed

        stats = score_all_listed(database_url=_DATABASE_URL, as_of=as_of, limit=max_companies)
        result.records_stored = int(stats.get("scored", 0) or 0)
        result.records_failed = int(stats.get("errors", 0) or 0)
        result.success = bool(stats.get("success"))
        result.metadata.update({k: stats.get(k) for k in ("scored", "with_model", "errors", "as_of")})
    except Exception as exc:
        logger.error("IGS scoring refresh failed: %s", exc)
        result.error = str(exc)
        result.success = False
    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_ikg_graph_build(max_companies: int | None = None) -> PipelineRunResult:
    """Build Supabase/Postgres graph rows from populated Nifty 500 staging tables."""
    result = PipelineRunResult(task_name="ikg_graph_build", started_at=_now_iso())
    result.metadata = {
        "source_name": "IKG staging tables",
        "official_source_url": "staging://ikg_company_master,directors_raw,shp_raw,company_financials,annual_reports_raw,annual_report_chunks,document_sections,corporate_filings_raw,enforcement_raw,ikg_facts",
        "parser_version": "ikg_graph_build_v1",
        "max_companies": max_companies,
    }
    start_t = time.time()

    try:
        from finagent.ikg.pipeline.run_store import build_ikg_from_staging
        from finagent.ikg.scrapers.mca_companies import get_listed_companies

        companies = get_listed_companies(
            database_url=_DATABASE_URL,
            indexed_only=_use_indexed_listed_companies(),
        )
        if not companies and _use_indexed_listed_companies():
            logger.warning("No indexed listed-company rows found; falling back to broader listed company selection")
            companies = get_listed_companies(database_url=_DATABASE_URL, indexed_only=False)
        if max_companies:
            companies = companies[:max_companies]
        cins = {str(co.get("cin") or "").strip() for co in companies if co.get("cin")}
        if not cins:
            refs = {
                str(
                    co.get("nse_symbol")
                    or co.get("bse_scrip_code")
                    or co.get("isin")
                    or co.get("company_name")
                    or ""
                ).strip()
                for co in companies
                if (
                    co.get("nse_symbol")
                    or co.get("bse_scrip_code")
                    or co.get("isin")
                    or co.get("company_name")
                )
            }
            allow_broad_fallback = os.getenv(
                "FINAGENT_IKG_BUILD_BROAD_FALLBACK_ON_MISSING_CINS",
                "1",
            ).strip().lower() in {"1", "true", "yes", "on"}
            if refs and allow_broad_fallback:
                logger.warning(
                    "No company CINs found for scoped graph build; falling back to broad staging build for %d scoped refs",
                    len(refs),
                )
                stats = build_ikg_from_staging(database_url=_DATABASE_URL, nifty10_cins=None)
                result.records_fetched = len(refs)
                result.records_stored = int(stats.get("vertices_created", 0)) + int(stats.get("edges_created", 0))
                result.records_failed = 1 if stats.get("error") else 0
                result.success = not bool(stats.get("error"))
                result.error = stats.get("error")
                result.metadata.update(
                    {
                        "scope_fallback": "broad_no_cin_filter",
                        "scoped_refs": sorted(refs)[:10],
                    }
                )
                result.metadata.update(stats)
            else:
                result.error = "No company CINs found for graph build"
                result.success = False
                result.metadata["scope_fallback"] = "disabled" if refs else "no_scope_refs"
        else:
            stats = build_ikg_from_staging(database_url=_DATABASE_URL, nifty10_cins=cins)
            result.records_fetched = len(cins)
            result.records_stored = int(stats.get("vertices_created", 0)) + int(stats.get("edges_created", 0))
            result.records_failed = 1 if stats.get("error") else 0
            result.success = not bool(stats.get("error"))
            result.error = stats.get("error")
            result.metadata.update(stats)

    except Exception as exc:
        logger.error("IKG graph build failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def run_qdrant_document_index_refresh(
    *,
    max_sections: int | None = None,
    recreate: bool = False,
) -> PipelineRunResult:
    """Materialize extracted documents and index document sections into Qdrant."""
    result = PipelineRunResult(task_name="qdrant_document_index_refresh", started_at=_now_iso())
    result.metadata = {
        "source_name": "IKG document_sections",
        "official_source_url": "staging://document_sections,corporate_filings_raw,enforcement_raw,concall_transcripts_raw,annual_reports_raw",
        "parser_version": "qdrant_document_sections_v1",
        "max_sections": max_sections,
        "recreate": recreate,
    }
    start_t = time.time()
    if max_sections is None:
        configured_limit = os.getenv("FINAGENT_QDRANT_INDEX_LIMIT", "").strip()
        if configured_limit:
            max_sections = int(configured_limit)
            result.metadata["max_sections"] = max_sections
    incremental_since: str | None = None
    if not recreate and os.getenv("FINAGENT_QDRANT_INCREMENTAL", "1").strip().lower() in {"1", "true", "yes", "on"}:
        incremental_since = _last_successful_completed_at("qdrant_document_index_refresh")
        if incremental_since:
            result.metadata["since"] = incremental_since

    try:
        from finagent.graphrag.qdrant_indexer import index_document_sections_to_qdrant
        from finagent.ikg.scrapers._engine import run_async

        stats = run_async(
            index_document_sections_to_qdrant(
                database_url=_DATABASE_URL,
                limit=max_sections,
                recreate=recreate,
                since=incremental_since,
                materialize=True,
            )
        )
        result.records_fetched = int(stats.get("rows_seen") or 0)
        result.records_stored = int(stats.get("indexed") or 0)
        result.records_failed = int(stats.get("skipped") or 0)
        result.success = bool(stats.get("success"))
        result.error = stats.get("error")
        result.metadata.update(stats)
    except Exception as exc:
        logger.error("Qdrant document index refresh failed: %s", exc)
        result.error = str(exc)
        result.success = False

    result.duration_s = round(time.time() - start_t, 2)
    result.completed_at = _now_iso()
    _log_run_result(result)
    return result


def _annual_mode_requires_financials() -> bool:
    mode = os.getenv("FINAGENT_ANNUAL_REPORT_EXTRACT_MODE", "metadata_only").strip().lower()
    return mode in {"targeted_top100_mcap", "top100_mcap", "market_cap_top100", "targeted_mcap"}


def run_nifty500_parallel_refresh(
    *,
    max_companies: int | None = None,
    years_back: int | None = None,
    include_graph_build: bool = True,
    include_qdrant_index: bool = True,
) -> dict[str, PipelineRunResult]:
    """Run the configured NSE-universe refresh tasks in parallel after constituent sync."""
    years_back = max(1, int(years_back or _configured_years_back()))
    logger.info("=== %s parallel refresh starting ===", _configured_universe_label())
    results: dict[str, PipelineRunResult] = {}
    bounded_run = _is_bounded_run(max_companies)

    # Keep this dependency first so downstream company lookups are up to date.
    results["nse_nifty500_refresh"] = run_nse_nifty500_refresh()
    financials_first = _annual_mode_requires_financials()
    if financials_first:
        logger.info(
            "Annual-report mode requires market-cap ranking; running financial_data_refresh before parallel document jobs"
        )
        results["financial_data_refresh"] = run_financial_data_refresh(max_companies=max_companies)

    jobs: list[tuple[str, Any, dict[str, Any]]] = [
        ("bse_shp_refresh", run_bse_shp_refresh, {"quarters": _configured_shp_quarters(), "max_companies": max_companies}),
        (
            "corporate_governance_director_refresh",
            run_corporate_governance_director_refresh,
            {"max_companies": max_companies, "years_back": years_back},
        ),
        ("sebi_enforcement_refresh", run_sebi_enforcement_refresh, {}),
        ("sebi_corporate_filing_map_refresh", run_sebi_corporate_filing_map_refresh, {}),
        (
            "corporate_filing_documents_refresh",
            run_corporate_filing_documents_refresh,
            {"max_companies": max_companies, "years_back": years_back},
        ),
        ("annual_reports_refresh", run_annual_reports_refresh, {"max_companies": max_companies}),
        (
            "concall_transcripts_refresh",
            run_concall_transcripts_refresh,
            {"max_companies": max_companies, "years_back": years_back},
        ),
    ]
    if bounded_run and _last_successful_completed_at("bse_eod_daily", lookback_minutes=24 * 60):
        results["bse_eod_daily"] = _make_skipped_result(
            "bse_eod_daily",
            reason="bounded run reused a recent successful daily price refresh",
            metadata={"max_companies": max_companies},
        )
    else:
        jobs.insert(1, ("bse_eod_daily", run_bse_eod_daily, {}))
    if not financials_first:
        jobs.insert(3, ("financial_data_refresh", run_financial_data_refresh, {"max_companies": max_companies}))

    max_workers = max(1, min(_PARALLEL_MAX_WORKERS, len(jobs)))
    expected_results = len(results) + len(jobs)
    logger.info(
        "%s parallel jobs queued: %s | workers=%d | max_companies=%s | years_back=%s",
        _configured_universe_label(),
        ", ".join(name for name, _, _ in jobs),
        max_workers,
        max_companies or "all",
        years_back,
    )

    def _run_logged_job(name: str, fn: Any, kwargs: dict[str, Any]) -> PipelineRunResult:
        started = time.time()
        logger.info("[NIFTY-PARALLEL] START %s args=%s", name, kwargs)
        result = fn(**kwargs)
        logger.info(
            "[NIFTY-PARALLEL] DONE %s success=%s fetched=%d stored=%d failed=%d duration=%.1fs",
            name,
            result.success,
            result.records_fetched,
            result.records_stored,
            result.records_failed,
            time.time() - started,
        )
        return result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_run_logged_job, name, fn, kwargs): name for name, fn, kwargs in jobs}
        for future in as_completed(future_map):
            job_name = future_map[future]
            try:
                results[job_name] = future.result()
                logger.info(
                    "[NIFTY-PARALLEL] PROGRESS completed=%d/%d latest=%s",
                    len(results),
                    expected_results,
                    job_name,
                )
            except Exception as exc:
                logger.error("Parallel task %s failed: %s", job_name, exc)
                failed = PipelineRunResult(
                    task_name=job_name,
                    started_at=_now_iso(),
                    completed_at=_now_iso(),
                    duration_s=0.0,
                    success=False,
                    error=str(exc),
                )
                _log_run_result(failed)
                results[job_name] = failed

    logger.info("[NIFTY-PARALLEL] START director_kmp_enrichment_refresh")
    results["director_kmp_enrichment_refresh"] = run_director_kmp_enrichment_refresh(
        max_companies=max_companies,
        years_back=years_back,
    )
    logger.info(
        "[NIFTY-PARALLEL] DONE director_kmp_enrichment_refresh success=%s fetched=%d stored=%d failed=%d duration=%.1fs",
        results["director_kmp_enrichment_refresh"].success,
        results["director_kmp_enrichment_refresh"].records_fetched,
        results["director_kmp_enrichment_refresh"].records_stored,
        results["director_kmp_enrichment_refresh"].records_failed,
        results["director_kmp_enrichment_refresh"].duration_s,
    )

    if include_graph_build:
        logger.info("[NIFTY-PARALLEL] START ikg_graph_build max_companies=%s", max_companies or "all")
        results["ikg_graph_build"] = run_ikg_graph_build(max_companies=max_companies)
        logger.info(
            "[NIFTY-PARALLEL] DONE ikg_graph_build success=%s fetched=%d stored=%d failed=%d duration=%.1fs",
            results["ikg_graph_build"].success,
            results["ikg_graph_build"].records_fetched,
            results["ikg_graph_build"].records_stored,
            results["ikg_graph_build"].records_failed,
            results["ikg_graph_build"].duration_s,
        )
    if include_qdrant_index:
        qdrant_limit = _bounded_qdrant_limit(max_companies)
        logger.info(
            "[NIFTY-PARALLEL] START qdrant_document_index_refresh max_sections=%s",
            qdrant_limit or "all",
        )
        results["qdrant_document_index_refresh"] = run_qdrant_document_index_refresh(max_sections=qdrant_limit)
        logger.info(
            "[NIFTY-PARALLEL] DONE qdrant_document_index_refresh success=%s fetched=%d stored=%d failed=%d duration=%.1fs",
            results["qdrant_document_index_refresh"].success,
            results["qdrant_document_index_refresh"].records_fetched,
            results["qdrant_document_index_refresh"].records_stored,
            results["qdrant_document_index_refresh"].records_failed,
            results["qdrant_document_index_refresh"].duration_s,
        )

    logger.info(
        "=== %s parallel refresh complete: %d tasks, %d stored records ===",
        _configured_universe_label(),
        len(results),
        sum(r.records_stored for r in results.values()),
    )
    return results


def run_historical_backfill(
    *,
    max_companies: int | None = None,
    years_back: int | None = None,
    hydration_passes: int | None = None,
    attachment_limit: int | None = None,
) -> dict[str, PipelineRunResult]:
    """Run a deeper historical rebuild with follow-up attachment hydration passes."""
    effective_years_back = max(1, int(years_back or _configured_years_back(7)))
    bounded_run = _is_bounded_run(max_companies)
    configured_passes = os.getenv("FINAGENT_CORP_FILINGS_HYDRATION_PASSES", "").strip()
    if hydration_passes is None:
        hydration_passes = 1 if bounded_run else max(1, int(configured_passes or "2"))
    effective_attachment_limit = attachment_limit if attachment_limit is not None else _bounded_attachment_limit(max_companies)
    qdrant_limit = _bounded_qdrant_limit(max_companies)
    logger.info(
        "=== Historical backfill starting: universe=%s max_companies=%s years_back=%s hydration_passes=%s ===",
        _configured_universe_label(),
        max_companies or "all",
        effective_years_back,
        hydration_passes,
    )
    results = run_nifty500_parallel_refresh(
        max_companies=max_companies,
        years_back=effective_years_back,
        include_graph_build=False,
        include_qdrant_index=False,
    )
    for pass_index in range(max(0, int(hydration_passes))):
        task_key = f"corporate_filing_attachment_hydration_pass_{pass_index + 1}"
        results[task_key] = run_corporate_filing_attachment_hydration(limit=effective_attachment_limit)
        if results[task_key].records_fetched == 0:
            logger.info("Historical backfill hydration pass %d found no remaining attachment backlog", pass_index + 1)
            break
    results["ikg_graph_build_final"] = run_ikg_graph_build(max_companies=max_companies)
    results["qdrant_document_index_refresh_final"] = run_qdrant_document_index_refresh(max_sections=qdrant_limit)
    logger.info(
        "=== Historical backfill complete: tasks=%d stored=%d ===",
        len(results),
        sum(result.records_stored for result in results.values()),
    )
    return results


def run_full_bootstrap(
    csv_path: str | None = None,
    skip_phases: list[str] | None = None,
) -> dict[str, PipelineRunResult]:
    """Run the complete IKG bootstrap pipeline.

    This is a one-time operation to build the initial IKG.
    After bootstrap, individual phases run on their own schedules.

    Phase order:
      1. mca_bootstrap (loads the downloaded MCA CSV)
      2. nse_nifty500_refresh (gets Nifty 500 list)
      3. financial_data_refresh (gets financial data)
      4. bse_shp_refresh (gets shareholding patterns)

    Args:
        csv_path: Path to downloaded MCA CSV file.
        skip_phases: List of phase names to skip.

    Returns:
        dict of task_name → PipelineRunResult
    """
    skip = set(skip_phases or [])
    results: dict[str, PipelineRunResult] = {}

    logger.info("=== IKG Full Bootstrap Starting ===")

    # Phase 1: MCA company master
    if "mca_bootstrap" not in skip:
        logger.info("Phase 1: MCA Bootstrap...")
        results["mca_bootstrap"] = run_mca_bootstrap(csv_path=csv_path)
        logger.info("Phase 1 result: %s", results["mca_bootstrap"].to_dict())

    # Phase 2: NSE Nifty 500 list
    if "nse_nifty500_refresh" not in skip:
        logger.info("Phase 2: NSE Nifty 500 refresh...")
        results["nse_nifty500_refresh"] = run_nse_nifty500_refresh()
        logger.info("Phase 2 result: %s", results["nse_nifty500_refresh"].to_dict())

    # Phase 3/4: Run heavy company-level jobs in parallel.
    parallel_jobs: list[tuple[str, Any, dict[str, Any]]] = []
    if "financial_data_refresh" not in skip:
        parallel_jobs.append(("financial_data_refresh", run_financial_data_refresh, {}))
    if "bse_shp_refresh" not in skip:
        parallel_jobs.append(("bse_shp_refresh", run_bse_shp_refresh, {"quarters": _configured_shp_quarters()}))

    if parallel_jobs:
        logger.info("Phase 3/4: Running %d bootstrap jobs in parallel...", len(parallel_jobs))
        with ThreadPoolExecutor(max_workers=min(2, len(parallel_jobs))) as executor:
            future_map = {executor.submit(fn, **kwargs): name for name, fn, kwargs in parallel_jobs}
            for future in as_completed(future_map):
                name = future_map[future]
                results[name] = future.result()
                logger.info("%s result: %s", name, results[name].to_dict())

    logger.info("=== IKG Full Bootstrap Complete ===")
    total_records = sum(r.records_stored for r in results.values())
    logger.info("Total records stored: %d", total_records)

    return results


def get_pipeline_health(database_url: str | None = None) -> dict[str, Any]:
    """Check data freshness and IKG node counts for health monitoring."""
    db_url = get_database_url(database_url) or _DATABASE_URL
    health: dict[str, Any] = {
        "status": "unknown",
        "backend": {
            "ikg_backend": os.getenv("IKG_BACKEND", "memory"),
            "database_configured": bool(db_url),
            "supabase_database": is_supabase_database_url(db_url),
            "supabase_api_configured": bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_KEY")),
            "azure_document_intelligence_configured": bool(
                os.getenv("AZURE_DI_ENDPOINT") and os.getenv("AZURE_DI_KEY")
            ),
            "retrieval_backend": os.getenv("FINAGENT_RETRIEVAL_BACKEND", "qdrant_postgres"),
            "qdrant_configured": bool(os.getenv("QDRANT_URL", "http://localhost:6333")),
        },
        "checks": {},
        "alerts": [],
    }

    if not db_url:
        health["status"] = "unconfigured"
        return health
    ensure_ikg_runtime_tables(db_url)

    try:
        from psycopg.rows import dict_row
        from datetime import date

        with connect_postgres(db_url, row_factory=dict_row, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                # Check company master freshness
                cur.execute("select count(*) as n, max(updated_at) as latest from ikg_company_master")
                row = cur.fetchone() or {}
                health["checks"]["company_master"] = {
                    "count": int(row.get("n") or 0),
                    "last_updated": str(row.get("latest") or ""),
                }
                if int(row.get("n") or 0) < 100:
                    health["alerts"].append("company_master has < 100 records — needs bootstrap")

                # Check EOD prices freshness
                cur.execute("select count(*) as n, max(trade_date) as latest from daily_prices")
                row = cur.fetchone() or {}
                latest_trade = row.get("latest")
                health["checks"]["daily_prices"] = {
                    "count": int(row.get("n") or 0),
                    "latest_trade_date": str(latest_trade or ""),
                }
                if latest_trade and (date.today() - latest_trade).days > 3:
                    health["alerts"].append(f"daily_prices stale: last date={latest_trade}")

                try:
                    cur.execute(
                        """
                        select
                          (select count(*) from ikg_vertices) as vertices,
                          (select count(*) from ikg_edges) as edges
                        """
                    )
                    row = cur.fetchone() or {}
                    health["checks"]["ikg_graph"] = {
                        "vertices": int(row.get("vertices") or 0),
                        "edges": int(row.get("edges") or 0),
                    }
                    if int(row.get("vertices") or 0) == 0:
                        health["alerts"].append("IKG graph has no vertices")
                except Exception as exc:
                    conn.rollback()
                    health["alerts"].append(f"ikg_graph check failed: {exc}")

                try:
                    cur.execute(
                        """
                        select
                          count(*) as total_runs,
                          max(created_at) as latest_run,
                          count(*) filter (
                            where success = false and created_at > now() - interval '24 hours'
                          ) as failed_24h
                        from ikg_pipeline_runs
                        """
                    )
                    row = cur.fetchone() or {}
                    failed_24h = int(row.get("failed_24h") or 0)
                    health["checks"]["pipeline_runs"] = {
                        "total_runs": int(row.get("total_runs") or 0),
                        "latest_run": str(row.get("latest_run") or ""),
                        "failed_24h": failed_24h,
                    }
                    if failed_24h:
                        health["alerts"].append(f"{failed_24h} pipeline runs failed in the last 24h")
                except Exception as exc:
                    conn.rollback()
                    health["alerts"].append(f"pipeline_runs check failed: {exc}")

                try:
                    cur.execute(
                        "select count(*) as n, max(announced_at) as latest from concall_transcripts_raw"
                    )
                    row = cur.fetchone() or {}
                    health["checks"]["concall_transcripts"] = {
                        "count": int(row.get("n") or 0),
                        "latest_announcement": str(row.get("latest") or ""),
                    }
                    if int(row.get("n") or 0) == 0:
                        health["alerts"].append("concall_transcripts_raw is empty")
                except Exception as exc:
                    conn.rollback()
                    health["alerts"].append(f"concall_transcripts check failed: {exc}")

                try:
                    cur.execute(
                        """
                        select
                          (select count(*) from corporate_filings_raw) as filings,
                          (select count(*) from corporate_filings_raw where attachment_text_length > 0) as filings_with_text,
                          (select count(*) from xbrl_filings_raw) as xbrl_filings,
                          (select count(*) from corporate_xbrl_facts) as xbrl_facts,
                          (select count(*) from financial_results_xbrl) as financial_xbrl,
                          (select count(*) from corporate_event_xbrl) as event_xbrl,
                          (select count(*) from corporate_actions_raw) as corporate_actions
                        """
                    )
                    row = cur.fetchone() or {}
                    health["checks"]["corporate_filings_structured"] = {
                        "filings": int(row.get("filings") or 0),
                        "filings_with_text": int(row.get("filings_with_text") or 0),
                        "xbrl_filings": int(row.get("xbrl_filings") or 0),
                        "xbrl_facts": int(row.get("xbrl_facts") or 0),
                        "financial_xbrl": int(row.get("financial_xbrl") or 0),
                        "event_xbrl": int(row.get("event_xbrl") or 0),
                        "corporate_actions": int(row.get("corporate_actions") or 0),
                    }
                    if int(row.get("filings") or 0) > 0 and int(row.get("filings_with_text") or 0) == 0:
                        health["alerts"].append("corporate_filings_raw has metadata but no extracted attachment text")
                    if int(row.get("filings") or 0) > 0 and int(row.get("corporate_actions") or 0) == 0:
                        health["alerts"].append("corporate_actions_raw is empty despite corporate filing metadata")
                except Exception as exc:
                    conn.rollback()
                    health["alerts"].append(f"corporate filing structured-data check failed: {exc}")

                try:
                    cur.execute(
                        """
                        select
                          count(*) as sections,
                          count(*) filter (where document_type = 'annual_report') as annual_sections,
                          count(*) filter (where document_type = 'corporate_filing') as filing_sections,
                          count(*) filter (where document_type = 'concall_transcript') as concall_sections,
                          count(*) filter (where document_type = 'sebi_enforcement_order') as enforcement_sections,
                          count(*) filter (where document_type = 'director_governance_document') as director_sections
                        from document_sections
                        """
                    )
                    row = cur.fetchone() or {}
                    health["checks"]["document_sections"] = {
                        "sections": int(row.get("sections") or 0),
                        "annual_sections": int(row.get("annual_sections") or 0),
                        "filing_sections": int(row.get("filing_sections") or 0),
                        "concall_sections": int(row.get("concall_sections") or 0),
                        "enforcement_sections": int(row.get("enforcement_sections") or 0),
                        "director_sections": int(row.get("director_sections") or 0),
                    }
                    if int(row.get("sections") or 0) == 0:
                        health["alerts"].append("document_sections is empty; run qdrant_index/materialization after scraping")
                except Exception as exc:
                    conn.rollback()
                    health["alerts"].append(f"document_sections check failed: {exc}")

                try:
                    from finagent.graphrag.qdrant_store import check_qdrant

                    qdrant = check_qdrant()
                    health["checks"]["qdrant"] = qdrant
                    if not qdrant.get("ok"):
                        health["alerts"].append(f"qdrant unavailable: {qdrant.get('error')}")
                except Exception as exc:
                    health["alerts"].append(f"qdrant check failed: {exc}")

                try:
                    cur.execute(
                        """
                        select control_key, enabled, control_group, updated_at
                        from ikg_runtime_controls
                        order by control_key
                        """
                    )
                    rows = cur.fetchall() or []
                    controls: dict[str, dict[str, Any]] = {}
                    for row in rows:
                        key = row.get("control_key")
                        if not key:
                            continue
                        controls[str(key)] = {
                            "enabled": bool(row.get("enabled")),
                            "control_group": row.get("control_group"),
                            "updated_at": str(row.get("updated_at") or ""),
                        }
                    health["checks"]["runtime_controls"] = controls
                    if not controls.get("pipeline_enabled", {}).get("enabled", True):
                        health["alerts"].append("pipeline_enabled is disabled")
                    if not controls.get("graph_enabled", {}).get("enabled", True):
                        health["alerts"].append("graph_enabled is disabled")
                except Exception as exc:
                    conn.rollback()
                    health["alerts"].append(f"runtime_controls check failed: {exc}")

        health["status"] = "healthy" if not health["alerts"] else "degraded"
    except Exception as exc:
        health["status"] = "error"
        health["error"] = str(exc)

    return health


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run IKG data pipeline")
    parser.add_argument("--phase", choices=[
        "bootstrap", "nse", "shp", "eod", "directors", "governance_directors", "director_kmp", "financials",
        "sebi", "sebi_filings", "corp_filings", "corp_filing_hydrate", "annual_reports", "concall", "build_graph", "nifty500_parallel", "historical_backfill", "health",
        "qdrant_index", "failure_events", "igs_features", "igs_train", "igs_score",
    ], default="health")
    parser.add_argument("--csv-path", help="Path to MCA CSV file")
    parser.add_argument("--max-companies", type=int, help="Limit companies (for testing)")
    parser.add_argument("--years-back", type=int, default=3, help="Years back for transcript scraping")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.phase == "health":
        print(json.dumps(get_pipeline_health(), default=str, indent=2))
    elif args.phase == "bootstrap":
        results = run_full_bootstrap(csv_path=args.csv_path)
        for name, r in results.items():
            print(f"{name}: {r.to_dict()}")
    elif args.phase == "nse":
        print(run_nse_nifty500_refresh().to_dict())
    elif args.phase == "shp":
        print(run_bse_shp_refresh(max_companies=args.max_companies).to_dict())
    elif args.phase == "eod":
        print(run_bse_eod_daily().to_dict())
    elif args.phase == "directors":
        print(run_mca_director_refresh(max_companies=args.max_companies).to_dict())
    elif args.phase == "governance_directors":
        print(
            run_corporate_governance_director_refresh(
                max_companies=args.max_companies,
                years_back=args.years_back,
            ).to_dict()
        )
    elif args.phase == "director_kmp":
        print(
            run_director_kmp_enrichment_refresh(
                max_companies=args.max_companies,
                years_back=args.years_back,
            ).to_dict()
        )
    elif args.phase == "financials":
        print(run_financial_data_refresh(max_companies=args.max_companies).to_dict())
    elif args.phase == "sebi":
        print(run_sebi_enforcement_refresh().to_dict())
    elif args.phase == "sebi_filings":
        print(run_sebi_corporate_filing_map_refresh().to_dict())
    elif args.phase == "corp_filings":
        print(
            run_corporate_filing_documents_refresh(
                max_companies=args.max_companies,
                years_back=args.years_back,
            ).to_dict()
        )
    elif args.phase == "corp_filing_hydrate":
        print(run_corporate_filing_attachment_hydration(limit=args.max_companies).to_dict())
    elif args.phase == "annual_reports":
        print(run_annual_reports_refresh(max_companies=args.max_companies).to_dict())
    elif args.phase == "concall":
        print(
            run_concall_transcripts_refresh(
                max_companies=args.max_companies,
                years_back=args.years_back,
            ).to_dict()
        )
    elif args.phase == "build_graph":
        print(run_ikg_graph_build(max_companies=args.max_companies).to_dict())
    elif args.phase == "failure_events":
        print(run_failure_events_refresh().to_dict())
    elif args.phase == "igs_features":
        print(run_company_features_refresh(max_companies=args.max_companies).to_dict())
    elif args.phase == "igs_train":
        print(run_igs_model_train().to_dict())
    elif args.phase == "igs_score":
        print(run_igs_scoring_refresh(max_companies=args.max_companies).to_dict())
    elif args.phase == "qdrant_index":
        print(run_qdrant_document_index_refresh().to_dict())
    elif args.phase == "nifty500_parallel":
        results = run_nifty500_parallel_refresh(
            max_companies=args.max_companies,
            years_back=args.years_back,
        )
        for name, r in results.items():
            print(f"{name}: {r.to_dict()}")
    elif args.phase == "historical_backfill":
        results = run_historical_backfill(
            max_companies=args.max_companies,
            years_back=args.years_back,
        )
        for name, r in results.items():
            print(f"{name}: {r.to_dict()}")

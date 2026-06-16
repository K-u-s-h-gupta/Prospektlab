from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from finagent.env import load_finagent_env
from finagent.graphrag.qdrant_indexer import index_document_sections_to_qdrant
from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.pipeline.run_store import build_ikg_from_staging
from finagent.ikg.scrapers.annual_reports import run_annual_report_pipeline
from finagent.ikg.scrapers.bse_shp import run_bse_shp_scraper
from finagent.ikg.scrapers.concall_transcripts import run_concall_transcript_scraper
from finagent.ikg.scrapers.corporate_governance_directors import run_corporate_governance_director_scraper
from finagent.ikg.scrapers.director_kmp_enricher import run_director_kmp_enrichment
from finagent.ikg.scrapers.financial_data import run_financial_data_scraper
from finagent.ikg.scrapers.sebi_corporate_filings import run_corporate_filing_documents_scraper


def _company(symbol: str, cin: str, bse_scrip_code: str, company_name: str) -> list[dict[str, Any]]:
    return [{
        "cin": cin,
        "nse_symbol": symbol.upper(),
        "bse_scrip_code": bse_scrip_code,
        "company_name": company_name,
    }]


def _upsert_company_identity(
    *,
    database_url: str | None,
    symbol: str,
    cin: str,
    bse_scrip_code: str,
    company_name: str,
) -> None:
    db_url = get_database_url(database_url)
    if not db_url:
        raise RuntimeError("Database URL is not configured")
    with connect_postgres(db_url, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into ikg_company_master (
                  cin, nse_symbol, bse_scrip_code, company_name,
                  listing_status, status, updated_at
                )
                values (%s, %s, %s, %s, 'Listed', 'Active', now())
                on conflict (nse_symbol) do update set
                  cin = excluded.cin,
                  bse_scrip_code = coalesce(excluded.bse_scrip_code, ikg_company_master.bse_scrip_code),
                  company_name = coalesce(excluded.company_name, ikg_company_master.company_name),
                  listing_status = 'Listed',
                  status = coalesce(ikg_company_master.status, 'Active'),
                  updated_at = now()
                """,
                (cin, symbol.upper(), bse_scrip_code, company_name),
            )
        conn.commit()


def _scoped_counts(
    *,
    database_url: str | None,
    symbol: str,
    cin: str,
    bse_scrip_code: str,
) -> dict[str, int]:
    db_url = get_database_url(database_url)
    if not db_url:
        raise RuntimeError("Database URL is not configured")
    sql = """
    select
      (select count(*) from ikg_company_master
         where upper(coalesce(nse_symbol, '')) = upper(%(symbol)s)
            or cin = %(cin)s
            or coalesce(bse_scrip_code, '') = %(scrip)s) as company_master,
      (select count(*) from company_financials
         where upper(coalesce(nse_symbol, '')) = upper(%(symbol)s)
            or cin = %(cin)s) as financials,
      (select count(*) from shp_raw
         where cin = %(cin)s
            or coalesce(scrip_code, '') = %(scrip)s) as shp,
      (select count(*) from corporate_filings_raw
         where upper(coalesce(symbol, '')) = upper(%(symbol)s)
            or cin = %(cin)s
            or coalesce(scrip_code, '') = %(scrip)s) as corp_filings,
      (select count(*) from corporate_filings_raw
         where (upper(coalesce(symbol, '')) = upper(%(symbol)s)
            or cin = %(cin)s
            or coalesce(scrip_code, '') = %(scrip)s)
           and coalesce(attachment_text_length, 0) > 0) as corp_filings_with_text,
      (select count(*) from xbrl_filings_raw
         where upper(coalesce(symbol, '')) = upper(%(symbol)s)
            or cin = %(cin)s
            or coalesce(scrip_code, '') = %(scrip)s) as xbrl_filings,
      (select count(*) from corporate_xbrl_facts
         where upper(coalesce(symbol, '')) = upper(%(symbol)s)
            or cin = %(cin)s
            or coalesce(scrip_code, '') = %(scrip)s) as xbrl_facts,
      (select count(*) from financial_results_xbrl
         where upper(coalesce(symbol, '')) = upper(%(symbol)s)
            or cin = %(cin)s
            or coalesce(scrip_code, '') = %(scrip)s) as financial_xbrl,
      (select count(*) from corporate_event_xbrl
         where upper(coalesce(symbol, '')) = upper(%(symbol)s)
            or cin = %(cin)s
            or coalesce(scrip_code, '') = %(scrip)s) as event_xbrl,
      (select count(*) from corporate_actions_raw
         where upper(coalesce(symbol, '')) = upper(%(symbol)s)
            or cin = %(cin)s
            or coalesce(scrip_code, '') = %(scrip)s) as corporate_actions,
      (select count(*) from annual_reports_raw
         where upper(coalesce(nse_symbol, '')) = upper(%(symbol)s)
            or cin = %(cin)s
            or coalesce(scrip_code, '') = %(scrip)s) as annual_reports,
      (select count(*) from concall_transcripts_raw
         where upper(coalesce(symbol, '')) = upper(%(symbol)s)
            or cin = %(cin)s) as concalls,
      (select count(*) from directors_raw
         where cin = %(cin)s
            or upper(coalesce(nse_symbol, '')) = upper(%(symbol)s)) as directors,
      (select count(*) from document_sections
         where upper(coalesce(metadata->>'nse_symbol', '')) = upper(%(symbol)s)
            or coalesce(metadata->>'cin', '') = %(cin)s
            or coalesce(metadata->>'company_cin', '') = %(cin)s
            or coalesce(metadata->>'company_identifier', '') in (%(cin)s, %(symbol)s, %(scrip)s)) as sections,
      (select count(*) from ikg_vertices
         where vertex_id in ('company:' || %(cin)s, 'company:' || %(symbol)s, 'company:' || %(scrip)s)) as vertices,
      (select count(*) from ikg_edges
         where from_vertex_id in ('company:' || %(cin)s, 'company:' || %(symbol)s, 'company:' || %(scrip)s)
            or to_vertex_id in ('company:' || %(cin)s, 'company:' || %(symbol)s, 'company:' || %(scrip)s)) as edges,
      (select count(*) from ikg_facts
         where subject_entity_id in ('company:' || %(cin)s, 'company:' || %(symbol)s, 'company:' || %(scrip)s)
            or coalesce(object_entity_id, '') in ('company:' || %(cin)s, 'company:' || %(symbol)s, 'company:' || %(scrip)s)) as facts
    """
    keys = [
        "company_master",
        "financials",
        "shp",
        "corp_filings",
        "corp_filings_with_text",
        "xbrl_filings",
        "xbrl_facts",
        "financial_xbrl",
        "event_xbrl",
        "corporate_actions",
        "annual_reports",
        "concalls",
        "directors",
        "sections",
        "vertices",
        "edges",
        "facts",
    ]
    with connect_postgres(db_url, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {"symbol": symbol.upper(), "cin": cin, "scrip": bse_scrip_code})
            row = cur.fetchone()
    if isinstance(row, dict):
        return {k: int(v or 0) for k, v in row.items()}
    if row is not None:
        return {key: int(value or 0) for key, value in zip(keys, row)}
    raise RuntimeError("Unable to read scoped counts")


def run_target_company_smoke(
    *,
    symbol: str,
    cin: str,
    bse_scrip_code: str,
    company_name: str,
    years_back: int | None = None,
    reports_per_company: int | None = None,
    annual_extract_mode: str | None = None,
    corp_filings_extract_limit: int | None = None,
    qdrant_limit: int = 40,
    skip_qdrant: bool = False,
    database_url: str | None = None,
) -> dict[str, Any]:
    load_finagent_env()
    if reports_per_company is not None:
        os.environ["FINAGENT_ANNUAL_REPORTS_PER_COMPANY"] = str(max(1, reports_per_company))
    if annual_extract_mode is not None:
        os.environ["FINAGENT_ANNUAL_REPORT_EXTRACT_MODE"] = annual_extract_mode.strip().lower() or "targeted"
    os.environ["FINAGENT_CORP_FILINGS_EXTRACT_ATTACHMENTS"] = "1"
    if corp_filings_extract_limit is not None:
        os.environ["FINAGENT_CORP_FILINGS_EXTRACT_LIMIT"] = str(max(1, corp_filings_extract_limit))
    os.environ["FINAGENT_QDRANT_INDEX_BATCH_SIZE"] = "2"
    os.environ["FINAGENT_EMBEDDING_BATCH_SIZE"] = "2"
    os.environ["FINAGENT_EMBEDDING_BATCH_DELAY_S"] = "10"

    _upsert_company_identity(
        database_url=database_url,
        symbol=symbol,
        cin=cin,
        bse_scrip_code=bse_scrip_code,
        company_name=company_name,
    )
    company = _company(symbol, cin, bse_scrip_code, company_name)
    before = _scoped_counts(
        database_url=database_url,
        symbol=symbol,
        cin=cin,
        bse_scrip_code=bse_scrip_code,
    )

    corp_kwargs: dict[str, Any] = {"database_url": database_url, "max_companies": 1}
    annual_kwargs: dict[str, Any] = {"database_url": database_url, "max_companies": 1}
    concall_kwargs: dict[str, Any] = {"database_url": database_url, "max_companies": 1}
    governance_kwargs: dict[str, Any] = {"database_url": database_url, "max_companies": 1}
    director_kmp_kwargs: dict[str, Any] = {"database_url": database_url, "max_companies": 1}
    if years_back is not None:
        effective_years_back = max(1, years_back)
        corp_kwargs["years_back"] = effective_years_back
        concall_kwargs["years_back"] = effective_years_back
        governance_kwargs["years_back"] = effective_years_back
        director_kmp_kwargs["years_back"] = effective_years_back
    if reports_per_company is not None:
        annual_kwargs["reports_per_company"] = max(1, reports_per_company)

    results: dict[str, Any] = {
        "financials": run_financial_data_scraper(company, database_url=database_url, max_companies=1),
        "shp": run_bse_shp_scraper(company, database_url=database_url, max_companies=1, quarters=4),
        "corp_filings": run_corporate_filing_documents_scraper(company, **corp_kwargs),
        "annual_reports": run_annual_report_pipeline(company, **annual_kwargs),
        "concall": run_concall_transcript_scraper(company, **concall_kwargs),
        "governance_directors": run_corporate_governance_director_scraper(company, **governance_kwargs),
        "director_kmp": run_director_kmp_enrichment(companies=company, **director_kmp_kwargs),
    }
    results["graph"] = build_ikg_from_staging(
        database_url=database_url,
        nifty10_cins={cin},
    )
    if skip_qdrant:
        results["qdrant"] = {"success": True, "skipped": True}
    else:
        try:
            results["qdrant"] = asyncio.run(
                index_document_sections_to_qdrant(
                    database_url=database_url,
                    company_symbol=symbol.upper(),
                    limit=max(1, qdrant_limit),
                    batch_size=2,
                    recreate=False,
                    materialize=True,
                )
            )
        except Exception as exc:
            results["qdrant"] = {"success": False, "error": str(exc)}

    after = _scoped_counts(
        database_url=database_url,
        symbol=symbol,
        cin=cin,
        bse_scrip_code=bse_scrip_code,
    )
    return {
        "company": company[0],
        "years_back": years_back,
        "reports_per_company": reports_per_company,
        "annual_extract_mode": annual_extract_mode,
        "corp_filings_extract_limit": corp_filings_extract_limit,
        "before": before,
        "results": results,
        "after": after,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a targeted one-company IKG smoke")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--cin", required=True)
    parser.add_argument("--bse-scrip", required=True)
    parser.add_argument("--company-name", required=True)
    parser.add_argument("--years-back", type=int, default=None)
    parser.add_argument("--reports-per-company", type=int, default=None)
    parser.add_argument("--annual-extract-mode", default=None)
    parser.add_argument("--corp-filings-extract-limit", type=int, default=None)
    parser.add_argument("--qdrant-limit", type=int, default=40)
    parser.add_argument("--skip-qdrant", action="store_true")
    args = parser.parse_args()

    result = run_target_company_smoke(
        symbol=args.symbol,
        cin=args.cin,
        bse_scrip_code=args.bse_scrip,
        company_name=args.company_name,
        years_back=args.years_back,
        reports_per_company=args.reports_per_company,
        annual_extract_mode=args.annual_extract_mode,
        corp_filings_extract_limit=args.corp_filings_extract_limit,
        qdrant_limit=args.qdrant_limit,
        skip_qdrant=args.skip_qdrant,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

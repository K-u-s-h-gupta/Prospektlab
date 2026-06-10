"""Celery + Redis runtime for high-throughput IKG scraping.

APScheduler should enqueue these tasks; workers execute scraper phases in
parallel and the graph build remains a final controlled DB-write phase.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from typing import Any

from finagent.env import load_finagent_env

load_finagent_env()

logger = logging.getLogger("finagent.ikg.pipeline.celery_app")


def _broker_url() -> str:
    return (
        os.getenv("CELERY_BROKER_URL", "").strip()
        or os.getenv("REDIS_URL", "").strip()
        or "redis://localhost:6379/0"
    )


def _result_backend_url() -> str:
    return (
        os.getenv("CELERY_RESULT_BACKEND", "").strip()
        or os.getenv("REDIS_URL", "").strip()
        or "redis://localhost:6379/1"
    )


try:
    from celery import Celery, chain, group
except ImportError as exc:  # pragma: no cover - exercised when deps are not synced
    Celery = None  # type: ignore[assignment]
    chain = None  # type: ignore[assignment]
    group = None  # type: ignore[assignment]
    _CELERY_IMPORT_ERROR: Exception | None = exc
else:
    _CELERY_IMPORT_ERROR = None


if Celery is not None:
    celery_app = Celery(
        "finagent_ikg",
        broker=_broker_url(),
        backend=_result_backend_url(),
    )
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="Asia/Kolkata",
        enable_utc=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=int(os.getenv("FINAGENT_CELERY_PREFETCH", "1")),
        task_time_limit=int(os.getenv("FINAGENT_CELERY_TASK_TIME_LIMIT", "7200")),
        task_soft_time_limit=int(os.getenv("FINAGENT_CELERY_TASK_SOFT_TIME_LIMIT", "6900")),
        task_routes={
            "finagent.ikg.nse": {"queue": "nse"},
            "finagent.ikg.bse_shp": {"queue": "bse"},
            "finagent.ikg.bse_eod": {"queue": "bse"},
            "finagent.ikg.governance_directors": {"queue": "documents"},
            "finagent.ikg.financials": {"queue": "financials"},
            "finagent.ikg.sebi_enforcement": {"queue": "sebi"},
            "finagent.ikg.sebi_filing_map": {"queue": "sebi"},
            "finagent.ikg.corporate_filings": {"queue": "documents"},
            "finagent.ikg.annual_reports": {"queue": "documents"},
            "finagent.ikg.concalls": {"queue": "documents"},
            "finagent.ikg.director_kmp": {"queue": "documents"},
            "finagent.ikg.build_graph": {"queue": "graph"},
            "finagent.ikg.memgraph_project": {"queue": "graph"},
            "finagent.ikg.qdrant_index": {"queue": "graph"},
        },
    )
else:
    celery_app = None


def _require_celery() -> Any:
    if celery_app is None:
        raise RuntimeError(
            "Celery is not installed. Run `uv sync` after the pyproject dependency update."
        ) from _CELERY_IMPORT_ERROR
    return celery_app


def _result_dict(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if isinstance(result, dict):
        return result
    return {"result": result}


if celery_app is not None:

    @celery_app.task(name="finagent.ikg.nse")
    def nse_nifty500_refresh_task() -> dict[str, Any]:
        from finagent.ikg.pipeline.orchestrator import run_nse_nifty500_refresh

        return _result_dict(run_nse_nifty500_refresh())

    @celery_app.task(name="finagent.ikg.bse_shp")
    def bse_shp_refresh_task(max_companies: int | None = None, quarters: int | None = None) -> dict[str, Any]:
        from finagent.ikg.pipeline.orchestrator import run_bse_shp_refresh

        return _result_dict(run_bse_shp_refresh(max_companies=max_companies, quarters=quarters))

    @celery_app.task(name="finagent.ikg.bse_eod")
    def bse_eod_daily_task() -> dict[str, Any]:
        from finagent.ikg.pipeline.orchestrator import run_bse_eod_daily

        return _result_dict(run_bse_eod_daily())

    @celery_app.task(name="finagent.ikg.governance_directors")
    def governance_directors_task(max_companies: int | None = None, years_back: int = 3) -> dict[str, Any]:
        from finagent.ikg.pipeline.orchestrator import run_corporate_governance_director_refresh

        return _result_dict(run_corporate_governance_director_refresh(max_companies=max_companies, years_back=years_back))

    @celery_app.task(name="finagent.ikg.financials")
    def financial_data_task(max_companies: int | None = None) -> dict[str, Any]:
        from finagent.ikg.pipeline.orchestrator import run_financial_data_refresh

        return _result_dict(run_financial_data_refresh(max_companies=max_companies))

    @celery_app.task(name="finagent.ikg.sebi_enforcement")
    def sebi_enforcement_task() -> dict[str, Any]:
        from finagent.ikg.pipeline.orchestrator import run_sebi_enforcement_refresh

        return _result_dict(run_sebi_enforcement_refresh())

    @celery_app.task(name="finagent.ikg.sebi_filing_map")
    def sebi_filing_map_task() -> dict[str, Any]:
        from finagent.ikg.pipeline.orchestrator import run_sebi_corporate_filing_map_refresh

        return _result_dict(run_sebi_corporate_filing_map_refresh())

    @celery_app.task(name="finagent.ikg.corporate_filings")
    def corporate_filings_task(max_companies: int | None = None, years_back: int = 3) -> dict[str, Any]:
        from finagent.ikg.pipeline.orchestrator import run_corporate_filing_documents_refresh

        return _result_dict(run_corporate_filing_documents_refresh(max_companies=max_companies, years_back=years_back))

    @celery_app.task(name="finagent.ikg.annual_reports")
    def annual_reports_task(max_companies: int | None = None) -> dict[str, Any]:
        from finagent.ikg.pipeline.orchestrator import run_annual_reports_refresh

        return _result_dict(run_annual_reports_refresh(max_companies=max_companies))

    @celery_app.task(name="finagent.ikg.concalls")
    def concalls_task(max_companies: int | None = None, years_back: int = 3) -> dict[str, Any]:
        from finagent.ikg.pipeline.orchestrator import run_concall_transcripts_refresh

        return _result_dict(run_concall_transcripts_refresh(max_companies=max_companies, years_back=years_back))

    @celery_app.task(name="finagent.ikg.director_kmp")
    def director_kmp_task(max_companies: int | None = None, years_back: int = 3) -> dict[str, Any]:
        from finagent.ikg.pipeline.orchestrator import run_director_kmp_enrichment_refresh

        return _result_dict(run_director_kmp_enrichment_refresh(max_companies=max_companies, years_back=years_back))

    @celery_app.task(name="finagent.ikg.build_graph")
    def build_graph_task(max_companies: int | None = None) -> dict[str, Any]:
        from finagent.ikg.pipeline.orchestrator import run_ikg_graph_build

        return _result_dict(run_ikg_graph_build(max_companies=max_companies))

    @celery_app.task(name="finagent.ikg.memgraph_project")
    def memgraph_project_task(max_companies: int | None = None, rebuild: bool = False) -> dict[str, Any]:
        from finagent.ikg.pipeline.orchestrator import run_memgraph_projection_refresh

        return _result_dict(run_memgraph_projection_refresh(max_companies=max_companies, rebuild=rebuild))

    @celery_app.task(name="finagent.ikg.qdrant_index")
    def qdrant_index_task(max_sections: int | None = None, recreate: bool = False) -> dict[str, Any]:
        from finagent.ikg.pipeline.orchestrator import run_qdrant_document_index_refresh

        return _result_dict(run_qdrant_document_index_refresh(max_sections=max_sections, recreate=recreate))


def enqueue_nifty500_parallel(
    *,
    max_companies: int | None = None,
    years_back: int = 3,
) -> str:
    """Submit the Nifty 500 scraper group and final graph build to Celery."""
    _require_celery()
    assert chain is not None and group is not None

    annual_mode = os.getenv("FINAGENT_ANNUAL_REPORT_EXTRACT_MODE", "metadata_only").strip().lower()
    financials_first = annual_mode in {
        "targeted_top100_mcap",
        "top100_mcap",
        "market_cap_top100",
        "targeted_mcap",
    }
    parallel_tasks = [
        bse_shp_refresh_task.si(max_companies=max_companies, quarters=None),
        bse_eod_daily_task.si(),
        governance_directors_task.si(max_companies=max_companies, years_back=years_back),
        sebi_enforcement_task.si(),
        sebi_filing_map_task.si(),
        corporate_filings_task.si(max_companies=max_companies, years_back=years_back),
        annual_reports_task.si(max_companies=max_companies),
        concalls_task.si(max_companies=max_companies, years_back=years_back),
    ]
    if not financials_first:
        parallel_tasks.insert(3, financial_data_task.si(max_companies=max_companies))
    if financials_first:
        workflow = chain(
            nse_nifty500_refresh_task.s(),
            financial_data_task.si(max_companies=max_companies),
            group(parallel_tasks),
            director_kmp_task.si(max_companies=max_companies, years_back=years_back),
            build_graph_task.si(max_companies=max_companies),
            memgraph_project_task.si(max_companies=max_companies),
            qdrant_index_task.si(),
        )
    else:
        workflow = chain(
            nse_nifty500_refresh_task.s(),
            group(parallel_tasks),
            director_kmp_task.si(max_companies=max_companies, years_back=years_back),
            build_graph_task.si(max_companies=max_companies),
            memgraph_project_task.si(max_companies=max_companies),
            qdrant_index_task.si(),
        )
    async_result = workflow.apply_async()
    return str(async_result.id)


def celery_health() -> dict[str, Any]:
    """Check whether the broker/workers are reachable."""
    app = _require_celery()
    try:
        responses = app.control.ping(timeout=float(os.getenv("FINAGENT_CELERY_PING_TIMEOUT", "2")))
        return {
            "configured": True,
            "broker_url": _broker_url().split("@")[-1],
            "workers": responses,
            "ok": bool(responses),
        }
    except Exception as exc:
        return {
            "configured": True,
            "broker_url": _broker_url().split("@")[-1],
            "workers": [],
            "ok": False,
            "error": str(exc),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="FinAgent IKG Celery runtime helpers")
    parser.add_argument("--health", action="store_true", help="Ping Celery workers")
    parser.add_argument("--submit-nifty500", action="store_true", help="Enqueue Nifty 500 scraper workflow")
    parser.add_argument("--max-companies", type=int, default=None)
    parser.add_argument("--years-back", type=int, default=3)
    args = parser.parse_args()

    if args.health:
        print(json.dumps(celery_health(), indent=2, default=str))
        return
    if args.submit_nifty500:
        task_id = enqueue_nifty500_parallel(
            max_companies=args.max_companies,
            years_back=args.years_back,
        )
        print(json.dumps({"submitted": True, "task_id": task_id}, indent=2))
        return
    parser.print_help()


if __name__ == "__main__":
    main()

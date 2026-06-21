"""IKG Pipeline Scheduler - cron scheduling with optional APScheduler support.

Runs the official-source ingestion pipeline as a dedicated long-running
process. Do not import or start this from the FastAPI gateway process; run it
as its own service/container:

  python -m finagent.ikg.pipeline.scheduler
  python -m finagent.ikg.pipeline.scheduler --once
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
import threading
from typing import Any, Callable
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("finagent.ikg.pipeline.scheduler")

_IST_TIMEZONE = "Asia/Kolkata"
_SCHEDULER_REF: Any | None = None

_JOB_CONTROL_KEYS: dict[str, str] = {
    "bse_eod_daily": "bse_enabled",
    "nse_nifty500_monthly": "nse_enabled",
    "mca_company_master_monthly": "mca_enabled",
    "bse_shp_quarterly": "bse_enabled",
    "financial_data_quarterly": "financials_enabled",
    "sebi_enforcement_weekly": "sebi_enabled",
    "sebi_corporate_filings_weekly": "sebi_enabled",
    "annual_reports_weekly": "bse_enabled",
    "annual_reports_seasonal_midweek": "bse_enabled",
    "annual_reports": "bse_enabled",
    "concall_transcripts_weekly": "nse_enabled",
    "director_kmp_enrichment_weekly": "documents_enabled",
    "pipeline_health_6h": "healthcheck_enabled",
    "dreaming_layer_nightly": "dreaming_enabled",
    "official_content_monitor_10m": "official_monitor_enabled",
}


class _FallbackJob:
    def __init__(self, job_id: str, name: str | None = None) -> None:
        self.id = job_id
        self.name = name or job_id
        self.next_run_time = None


class _FallbackScheduler:
    """Minimal scheduler stand-in when APScheduler is unavailable.

    The backend should still boot cleanly even if the scheduler dependency has
    not been installed in the active virtualenv. We keep the process alive so the
    dedicated scheduler launcher can be used in manual-only mode, while exposing
    the same basic methods the rest of the module expects.
    """

    is_fallback = True

    def __init__(self, timezone: str) -> None:
        self.timezone = timezone
        self._jobs: dict[str, _FallbackJob] = {}
        self._shutdown_requested = False

    def add_job(self, _func: Callable[[], None], _trigger: Any = None, **kwargs: Any) -> _FallbackJob:
        job_id = str(kwargs.get("id") or "")
        job_name = str(kwargs.get("name") or job_id)
        job = _FallbackJob(job_id, job_name)
        self._jobs[job_id] = job
        return job

    def get_jobs(self) -> list[_FallbackJob]:
        return list(self._jobs.values())

    def get_job(self, job_id: str) -> _FallbackJob | None:
        return self._jobs.get(job_id)

    def start(self) -> None:
        logger.warning(
            "APScheduler is not installed; the IKG scheduler is running in manual-only fallback mode."
        )
        while not self._shutdown_requested:
            time.sleep(1)

    def shutdown(self, wait: bool = False) -> None:
        self._shutdown_requested = True


def _cron_enabled() -> bool:
    return os.getenv("FINAGENT_SCHEDULER_ENABLE_CRON", "1").strip().lower() in {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s=%r; using default %d", name, raw, default)
        return default
    return max(minimum, min(value, maximum))


def _official_monitor_interval_minutes() -> int:
    realtime_default = 1 if _env_bool("FINAGENT_OFFICIAL_MONITOR_REALTIME", False) else 10
    return _env_int(
        "FINAGENT_OFFICIAL_MONITOR_INTERVAL_MINUTES",
        realtime_default,
        minimum=1,
        maximum=60,
    )


def _heartbeat_interval_minutes() -> int:
    default = 1 if _env_bool("FINAGENT_OFFICIAL_MONITOR_REALTIME", False) else 2
    return _env_int(
        "FINAGENT_SCHEDULER_HEARTBEAT_MINUTES",
        default,
        minimum=1,
        maximum=10,
    )


def _official_monitor_realtime_loop_enabled() -> bool:
    return _env_bool("FINAGENT_OFFICIAL_MONITOR_REALTIME_LOOP", True)


def _official_monitor_interval_seconds() -> int:
    default = 30 if _official_monitor_realtime_loop_enabled() else _official_monitor_interval_minutes() * 60
    return _env_int(
        "FINAGENT_OFFICIAL_MONITOR_INTERVAL_SECONDS",
        default,
        minimum=15,
        maximum=3600,
    )


def _heartbeat_interval_seconds() -> int:
    default = 20 if _official_monitor_realtime_loop_enabled() else _heartbeat_interval_minutes() * 60
    return _env_int(
        "FINAGENT_SCHEDULER_HEARTBEAT_SECONDS",
        default,
        minimum=10,
        maximum=300,
    )


def _monitor_batch_size() -> int:
    default = 40 if _env_bool("FINAGENT_OFFICIAL_MONITOR_REALTIME", False) else 10
    return _env_int("FINAGENT_OFFICIAL_MONITOR_BATCH_SIZE", default, minimum=1, maximum=500)


def _monitor_events_per_company() -> int:
    default = 4 if _env_bool("FINAGENT_OFFICIAL_MONITOR_REALTIME", False) else 2
    return _env_int(
        "FINAGENT_OFFICIAL_MONITOR_MAX_EVENTS_PER_COMPANY",
        default,
        minimum=1,
        maximum=20,
    )


def _pipeline_years_back(default: int = 3) -> int:
    return _env_int("FINAGENT_PIPELINE_YEARS_BACK", default, minimum=1, maximum=25)


def _controls_enabled(job_id: str) -> bool:
    from finagent.ikg.pipeline.run_store import is_runtime_control_enabled

    if not is_runtime_control_enabled("pipeline_enabled", default=True):
        return False
    control_key = _JOB_CONTROL_KEYS.get(job_id)
    if not control_key:
        return True
    return is_runtime_control_enabled(control_key, default=True)


def _build_scheduler() -> Any:
    """Build and configure the APScheduler instance."""
    apscheduler_available = True
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as exc:
        apscheduler_available = False
        BlockingScheduler = _FallbackScheduler  # type: ignore[assignment]
        CronTrigger = None  # type: ignore[assignment]
        logger.warning(
            "APScheduler is not available in the active environment; using a manual-only scheduler fallback. "
            "Install apscheduler>=3.10.0 to enable cron jobs."
        )

    global _SCHEDULER_REF

    def _cron_trigger(**kwargs: Any) -> Any:
        if apscheduler_available and CronTrigger is not None:
            return CronTrigger(**kwargs)
        return kwargs

    scheduler = BlockingScheduler(timezone=_IST_TIMEZONE)
    _SCHEDULER_REF = scheduler

    if not _cron_enabled():
        logger.info("Cron scheduling disabled by FINAGENT_SCHEDULER_ENABLE_CRON; scheduler will stay idle for manual use")
        return scheduler

    scheduler.add_job(
        _run_bse_eod,
        _cron_trigger(day_of_week="mon-fri", hour=18, minute=15, timezone=_IST_TIMEZONE),
        id="bse_eod_daily",
        name="BSE EOD Prices",
        misfire_grace_time=3600,
        replace_existing=True,
    )
    # Real-time director/KMP board changes (SEBI LODR Reg 30, <=24h) — twice daily so
    # appointments/cessations land within hours of the BSE filing, not next quarter.
    scheduler.add_job(
        _run_board_changes,
        _cron_trigger(hour="10,20", minute=0, timezone=_IST_TIMEZONE),
        id="board_changes_daily",
        name="Real-time Board Changes (BSE announcements)",
        misfire_grace_time=3600,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_nse_nifty500,
        _cron_trigger(day=1, hour=6, minute=0, timezone=_IST_TIMEZONE),
        id="nse_nifty500_monthly",
        name="NSE Nifty 500 Refresh",
        misfire_grace_time=7200,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_mca_company_master,
        _cron_trigger(day=2, hour=4, minute=0, timezone=_IST_TIMEZONE),
        id="mca_company_master_monthly",
        name="MCA Company Master Refresh",
        misfire_grace_time=14400,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_bse_shp,
        _cron_trigger(month="1,4,7,10", day=15, hour=2, minute=0, timezone=_IST_TIMEZONE),
        id="bse_shp_quarterly",
        name="BSE Shareholding Pattern",
        misfire_grace_time=14400,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_financial_data,
        _cron_trigger(month="1,4,7,10", day=16, hour=3, minute=0, timezone=_IST_TIMEZONE),
        id="financial_data_quarterly",
        name="Financial Data Cross-Validation",
        misfire_grace_time=14400,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_sebi_enforcement,
        _cron_trigger(day_of_week="sun", hour=2, minute=0, timezone=_IST_TIMEZONE),
        id="sebi_enforcement_weekly",
        name="SEBI Enforcement Orders",
        misfire_grace_time=7200,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_sebi_corporate_filings,
        _cron_trigger(day_of_week="sun", hour=3, minute=15, timezone=_IST_TIMEZONE),
        id="sebi_corporate_filings_weekly",
        name="SEBI Corporate Filing Map",
        misfire_grace_time=7200,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_annual_reports,
        _cron_trigger(day_of_week="sun", hour=4, minute=30, timezone=_IST_TIMEZONE),
        id="annual_reports_weekly",
        name="BSE Annual Reports",
        misfire_grace_time=14400,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_annual_reports,
        _cron_trigger(month="8,9,10,11", day_of_week="wed", hour=4, minute=30, timezone=_IST_TIMEZONE),
        id="annual_reports_seasonal_midweek",
        name="BSE Annual Reports Seasonal Midweek",
        misfire_grace_time=14400,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_concall_transcripts,
        _cron_trigger(day_of_week="sun", hour=5, minute=45, timezone=_IST_TIMEZONE),
        id="concall_transcripts_weekly",
        name="NSE Concall Transcripts",
        misfire_grace_time=14400,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_director_kmp_enrichment,
        _cron_trigger(day_of_week="sun", hour=6, minute=20, timezone=_IST_TIMEZONE),
        id="director_kmp_enrichment_weekly",
        name="Director/KMP Document Enrichment",
        misfire_grace_time=14400,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_health_check,
        _cron_trigger(hour="0,6,12,18", minute=30, timezone=_IST_TIMEZONE),
        id="pipeline_health_6h",
        name="Pipeline Health Check",
        misfire_grace_time=600,
        replace_existing=True,
    )
    if not _official_monitor_realtime_loop_enabled():
        monitor_every_minutes = _official_monitor_interval_minutes()
        monitor_cron = "*" if monitor_every_minutes == 1 else f"*/{monitor_every_minutes}"
        scheduler.add_job(
            _run_official_content_monitor,
            _cron_trigger(minute=monitor_cron, timezone=_IST_TIMEZONE),
            id="official_content_monitor_10m",
            name="Official Content Monitor",
            misfire_grace_time=max(120, monitor_every_minutes * 120),
            replace_existing=True,
        )
        heartbeat_every_minutes = _heartbeat_interval_minutes()
        heartbeat_cron = "*" if heartbeat_every_minutes == 1 else f"*/{heartbeat_every_minutes}"
        scheduler.add_job(
            _emit_scheduler_heartbeat,
            _cron_trigger(minute=heartbeat_cron, timezone=_IST_TIMEZONE),
            id="scheduler_heartbeat_2m",
            name="Scheduler Heartbeat",
            misfire_grace_time=max(60, heartbeat_every_minutes * 90),
            replace_existing=True,
        )
    else:
        logger.info(
            "Realtime official monitor loop enabled; skipping cron registration for official monitor and heartbeat jobs."
        )
    if os.getenv("FINAGENT_SCHEDULER_ENABLE_DREAMING", "1").strip().lower() in {"1", "true", "yes", "on"}:
        scheduler.add_job(
            _run_dreaming_layer,
            _cron_trigger(hour=2, minute=30, timezone=_IST_TIMEZONE),
            id="dreaming_layer_nightly",
            name="Dreaming Layer Nightly Graph Update",
            misfire_grace_time=7200,
            replace_existing=True,
        )

    return scheduler


def _official_monitor_next_run_iso() -> str:
    if _SCHEDULER_REF is None:
        return ""
    try:
        job = _SCHEDULER_REF.get_job("official_content_monitor_10m")
    except Exception:
        return ""
    next_run_time = getattr(job, "next_run_time", None)
    return next_run_time.isoformat() if next_run_time else ""


def _emit_scheduler_heartbeat(
    note: str = "",
    status: str = "running",
    next_official_monitor_at: str | None = None,
) -> None:
    try:
        from finagent.content.official_monitor import record_scheduler_heartbeat

        job_count = len(_SCHEDULER_REF.get_jobs()) if _SCHEDULER_REF is not None else 0
        record_scheduler_heartbeat(
            status=status,
            note=note,
            next_official_monitor_at=next_official_monitor_at if next_official_monitor_at is not None else _official_monitor_next_run_iso(),
            job_count=job_count,
        )
    except Exception as exc:
        logger.warning("Failed to record scheduler heartbeat: %s", exc)


def _with_lock(job_id: str, run: Callable[[], None]) -> None:
    from finagent.ikg.pipeline.run_store import scheduler_job_lock

    with scheduler_job_lock(job_id) as acquired:
        if not acquired:
            logger.info("[SCHEDULER] %s skipped; another scheduler owns the lock", job_id)
            return
        run()


def _with_control_and_lock(job_id: str, run: Callable[[], None]) -> None:
    if not _controls_enabled(job_id):
        logger.info("[SCHEDULER] %s skipped; runtime controls disabled it", job_id)
        return
    _with_lock(job_id, run)


def _run_mca_company_master() -> None:
    def _run() -> None:
        from finagent.ikg.pipeline.orchestrator import run_mca_bootstrap

        result = run_mca_bootstrap()
        logger.info("[SCHEDULER] mca_company_master: %s", result.to_dict())

    _with_control_and_lock("mca_company_master_monthly", _run)


def _run_bse_eod() -> None:
    def _run() -> None:
        from finagent.ikg.pipeline.orchestrator import run_bse_eod_daily

        result = run_bse_eod_daily()
        logger.info("[SCHEDULER] bse_eod: %s", result.to_dict())

    _with_control_and_lock("bse_eod_daily", _run)


def _run_board_changes() -> None:
    def _run() -> None:
        from finagent.ikg.pipeline.orchestrator import run_board_change_refresh

        result = run_board_change_refresh()
        logger.info("[SCHEDULER] board_changes: %s", result.to_dict())

    _with_control_and_lock("board_changes_daily", _run)


def _run_nse_nifty500() -> None:
    def _run() -> None:
        from finagent.ikg.pipeline.orchestrator import run_nse_nifty500_refresh

        result = run_nse_nifty500_refresh()
        logger.info("[SCHEDULER] nse_nifty500: %s", result.to_dict())

    _with_control_and_lock("nse_nifty500_monthly", _run)


def _run_bse_shp() -> None:
    def _run() -> None:
        from finagent.ikg.pipeline.orchestrator import run_bse_shp_refresh

        result = run_bse_shp_refresh()
        logger.info("[SCHEDULER] bse_shp: %s", result.to_dict())

    _with_control_and_lock("bse_shp_quarterly", _run)


def _run_financial_data() -> None:
    def _run() -> None:
        from finagent.ikg.pipeline.orchestrator import run_financial_data_refresh

        result = run_financial_data_refresh()
        logger.info("[SCHEDULER] financial_data: %s", result.to_dict())

    _with_control_and_lock("financial_data_quarterly", _run)


def _run_sebi_enforcement() -> None:
    def _run() -> None:
        from finagent.ikg.pipeline.orchestrator import run_sebi_enforcement_refresh

        result = run_sebi_enforcement_refresh()
        logger.info("[SCHEDULER] sebi_enforcement: %s", result.to_dict())

    _with_control_and_lock("sebi_enforcement_weekly", _run)


def _run_sebi_corporate_filings() -> None:
    def _run() -> None:
        from finagent.ikg.pipeline.orchestrator import run_sebi_corporate_filing_map_refresh

        result = run_sebi_corporate_filing_map_refresh()
        logger.info("[SCHEDULER] sebi_corporate_filings: %s", result.to_dict())

    _with_control_and_lock("sebi_corporate_filings_weekly", _run)


def _run_annual_reports() -> None:
    def _run() -> None:
        from finagent.ikg.pipeline.orchestrator import run_annual_reports_refresh

        result = run_annual_reports_refresh()
        logger.info("[SCHEDULER] annual_reports: %s", result.to_dict())

    _with_control_and_lock("annual_reports", _run)


def _run_concall_transcripts() -> None:
    def _run() -> None:
        from finagent.ikg.pipeline.orchestrator import run_concall_transcripts_refresh

        result = run_concall_transcripts_refresh(years_back=_pipeline_years_back())
        logger.info("[SCHEDULER] concall_transcripts: %s", result.to_dict())

    _with_control_and_lock("concall_transcripts_weekly", _run)


def _run_director_kmp_enrichment() -> None:
    def _run() -> None:
        from finagent.ikg.pipeline.orchestrator import run_director_kmp_enrichment_refresh

        result = run_director_kmp_enrichment_refresh(years_back=_pipeline_years_back())
        logger.info("[SCHEDULER] director_kmp_enrichment: %s", result.to_dict())

    _with_control_and_lock("director_kmp_enrichment_weekly", _run)


def _run_corporate_filing_attachment_hydration() -> None:
    def _run() -> None:
        from finagent.ikg.pipeline.orchestrator import run_corporate_filing_attachment_hydration

        result = run_corporate_filing_attachment_hydration()
        logger.info("[SCHEDULER] corporate_filing_attachment_hydration: %s", result.to_dict())

    _with_control_and_lock("corporate_filing_attachment_hydration_6h", _run)


def _run_health_check() -> None:
    def _run() -> None:
        import time
        from datetime import datetime, timezone

        from finagent.ikg.pipeline.orchestrator import get_pipeline_health
        from finagent.ikg.pipeline.run_store import persist_pipeline_run

        started_at = datetime.now(timezone.utc)
        start_t = time.time()
        health = get_pipeline_health()
        if health.get("alerts"):
            logger.warning("[SCHEDULER] Pipeline health alerts: %s", health["alerts"])
        else:
            logger.info("[SCHEDULER] Pipeline health: %s", health.get("status", "ok"))
        persist_pipeline_run({
            "task_name": "pipeline_health_check",
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_s": round(time.time() - start_t, 2),
            "records_fetched": 1,
            "records_stored": 1,
            "records_failed": len(health.get("alerts") or []),
            "success": health.get("status") in {"healthy", "degraded", "unconfigured"},
            "error": health.get("error"),
            "metadata": {
                "source_name": "IKG pipeline health",
                "parser_version": "pipeline_health_v1",
                "health": health,
            },
        })

    _with_control_and_lock("pipeline_health_6h", _run)


def _run_official_content_monitor() -> None:
    def _run() -> None:
        from finagent.content.official_monitor import run_official_monitor

        route_base = (os.getenv("FINAGENT_OFFICIAL_MONITOR_ROUTE_BASE") or "insights").strip() or "insights"
        requested_by = (os.getenv("FINAGENT_OFFICIAL_MONITOR_REQUESTED_BY") or "automation@prospektlab.local").strip()
        batch_size = _monitor_batch_size()
        events_per_company = _monitor_events_per_company()
        dry_run = _env_bool("FINAGENT_OFFICIAL_MONITOR_DRY_RUN", False)

        _emit_scheduler_heartbeat(note="Running official-source sweep now", status="running")
        result = asyncio.run(
            run_official_monitor(
                requested_by=requested_by,
                route_base=route_base,
                company_batch_size=batch_size,
                max_events_per_company=events_per_company,
                dry_run=dry_run,
            )
        )
        _emit_scheduler_heartbeat(note="Scheduler online and waiting for the next official-source sweep", status="running")
        logger.info("[SCHEDULER] official_content_monitor: %s", result)

    _with_control_and_lock("official_content_monitor_10m", _run)


def _run_realtime_official_monitor_loop(stop_event: threading.Event) -> None:
    interval_s = _official_monitor_interval_seconds()
    heartbeat_s = _heartbeat_interval_seconds()
    logger.info(
        "[SCHEDULER] Realtime official monitor loop started: interval=%ss heartbeat=%ss",
        interval_s,
        heartbeat_s,
    )
    while not stop_event.is_set():
        cycle_started = time.time()
        _emit_scheduler_heartbeat(note="Realtime official-source cycle running", status="running")
        try:
            _run_official_content_monitor()
        except Exception as exc:
            logger.exception("[SCHEDULER] Realtime official monitor loop failed: %s", exc)

        elapsed = time.time() - cycle_started
        sleep_for = max(1.0, float(interval_s) - elapsed)
        next_run_at = (datetime.now(timezone.utc) + timedelta(seconds=sleep_for)).replace(microsecond=0).isoformat()
        waited = 0.0
        while waited < sleep_for and not stop_event.is_set():
            step = min(float(heartbeat_s), sleep_for - waited)
            stop_event.wait(step)
            waited += step
            if not stop_event.is_set():
                _emit_scheduler_heartbeat(
                    note="Realtime official monitor waiting for next cycle",
                    status="running",
                    next_official_monitor_at=next_run_at,
                )
    logger.info("[SCHEDULER] Realtime official monitor loop stopped")


def _run_graph_build() -> None:
    def _run() -> None:
        from finagent.ikg.pipeline.orchestrator import run_ikg_graph_build

        result = run_ikg_graph_build()
        logger.info("[SCHEDULER] ikg_graph_build: %s", result.to_dict())

    _with_control_and_lock("ikg_graph_build_4h", _run)


def _run_qdrant_index() -> None:
    def _run() -> None:
        from finagent.ikg.pipeline.orchestrator import run_qdrant_document_index_refresh

        result = run_qdrant_document_index_refresh()
        logger.info("[SCHEDULER] qdrant_document_index: %s", result.to_dict())

    _with_control_and_lock("qdrant_document_index_4h", _run)


def _run_dreaming_layer() -> None:
    def _run() -> None:
        import time
        from datetime import datetime, timezone

        from finagent.dreaming.worker import run_dreaming_in_thread
        from finagent.ikg.pipeline.run_store import persist_pipeline_run

        started_at = datetime.now(timezone.utc)
        start_t = time.time()
        result = run_dreaming_in_thread()
        logger.info("[SCHEDULER] dreaming_layer: %s", result)
        persist_pipeline_run(
            {
                "task_name": "dreaming_layer_nightly",
                "started_at": started_at.isoformat(),
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "duration_s": round(time.time() - start_t, 2),
                "records_fetched": int(sum((result.get("patterns_detected") or {}).values())),
                "records_stored": int(sum((result.get("patterns_detected") or {}).values())),
                "records_failed": len(result.get("errors") or []),
                "success": not bool(result.get("errors")),
                "error": "; ".join(result.get("errors") or []),
                "metadata": {
                    "source_name": "Dreaming layer",
                    "official_source_url": "",
                    "parser_version": "dreaming_layer_v1",
                    "dreaming_result": result,
                },
            }
        )

    _with_control_and_lock("dreaming_layer_nightly", _run)


def run_all_once(
    *,
    include_slow: bool = False,
    years_back: int | None = None,
) -> None:
    """Run scheduler jobs immediately for testing/manual refresh.

    By default this runs the lightweight jobs only. Pass include_slow=True for
    a full manual refresh that may take many hours because official sources are
    rate limited.
    """
    logger.info("Running scheduler tasks immediately...")
    effective_years_back = max(1, int(years_back or _pipeline_years_back()))
    if include_slow:
        import os

        if os.getenv("FINAGENT_SCHEDULER_USE_CELERY", "0").strip().lower() in {"1", "true", "yes", "on"}:
            from finagent.ikg.pipeline.celery_app import enqueue_nifty500_parallel

            task_id = enqueue_nifty500_parallel(
                years_back=effective_years_back,
            )
            logger.info("[SCHEDULER] Enqueued Celery Nifty500 workflow: %s", task_id)
        else:
            from finagent.ikg.pipeline.orchestrator import run_nifty500_parallel_refresh

            results = run_nifty500_parallel_refresh(
                years_back=effective_years_back,
            )
            for task_name, task_result in results.items():
                logger.info("[SCHEDULER] %s: %s", task_name, task_result.to_dict())
    _run_sebi_corporate_filings()
    _run_corporate_filing_attachment_hydration()
    _run_concall_transcripts()
    _run_director_kmp_enrichment()
    _run_graph_build()
    _run_qdrant_index()
    _run_health_check()
    logger.info("Scheduler immediate run completed")


def start_scheduler() -> None:
    """Start the blocking scheduler. Runs until interrupted."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Starting IKG data pipeline scheduler (IST timezone)...")
    logger.info(
        "Official monitor cadence: every %d minute(s) | batch_size=%d | events_per_company=%d | realtime=%s",
        _official_monitor_interval_minutes(),
        _monitor_batch_size(),
        _monitor_events_per_company(),
        _env_bool("FINAGENT_OFFICIAL_MONITOR_REALTIME", False),
    )
    logger.info(
        "Official monitor realtime loop: enabled=%s | interval=%ss",
        _official_monitor_realtime_loop_enabled(),
        _official_monitor_interval_seconds(),
    )

    scheduler = _build_scheduler()
    realtime_stop_event = threading.Event()
    realtime_thread: threading.Thread | None = None
    if _official_monitor_realtime_loop_enabled():
        realtime_thread = threading.Thread(
            target=_run_realtime_official_monitor_loop,
            args=(realtime_stop_event,),
            name="official-monitor-realtime-loop",
            daemon=True,
        )
        realtime_thread.start()
    if getattr(scheduler, "is_fallback", False):
        _emit_scheduler_heartbeat(
            note="APScheduler is not installed in this environment; scheduler is running in manual-only mode",
            status="manual_only",
        )

    def _shutdown(signum: int, frame: Any) -> None:
        logger.info("Received signal %d, shutting down scheduler...", signum)
        realtime_stop_event.set()
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    jobs = scheduler.get_jobs()
    if jobs:
        logger.info("Scheduled jobs:")
        for job in jobs:
            # APScheduler builds can differ on exposed job attributes; avoid startup crash.
            next_run_time = getattr(job, "next_run_time", None)
            logger.info("  %-40s -> next run: %s", job.name, next_run_time)
    else:
        logger.info("No scheduled cron jobs registered")

    try:
        _emit_scheduler_heartbeat(note="Scheduler online and watching official sources", status="running")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        _emit_scheduler_heartbeat(note="Scheduler stopped", status="stopped")
        logger.info("Scheduler stopped")
    finally:
        realtime_stop_event.set()
        if realtime_thread and realtime_thread.is_alive():
            realtime_thread.join(timeout=2.0)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="IKG Pipeline Scheduler")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run lightweight scheduled tasks once immediately (testing mode)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="With --once, run the full scraper refresh. This may take many hours.",
    )
    parser.add_argument(
        "--years-back",
        type=int,
        default=3,
        help="With transcript scraping, look back this many years.",
    )
    args = parser.parse_args()

    if args.once:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        run_all_once(
            include_slow=args.all,
            years_back=args.years_back,
        )
    else:
        start_scheduler()

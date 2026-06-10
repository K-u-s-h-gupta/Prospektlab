"""Dreaming Scheduler — nightly APScheduler job for the dreaming pipeline.

Schedule: 2:00 AM IST nightly (runs after EOD pipeline completes at 6 PM IST).

The dreaming cycle runs:
  1. Pattern detection (pledge spikes, director exodus, price anomalies)
  2. Memory consolidation
  3. Stale memory eviction
  4. Ticker context card pre-computation
"""

from __future__ import annotations

import logging
import os
import signal
import sys
from typing import Any

logger = logging.getLogger("finagent.dreaming.scheduler")

_IST_TIMEZONE = "Asia/Kolkata"


def _build_dreaming_scheduler() -> Any:
    """Build APScheduler instance for the nightly dreaming job."""
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as exc:
        raise RuntimeError(
            "APScheduler is required. Install: pip install apscheduler>=3.10.0"
        ) from exc

    scheduler = BlockingScheduler(timezone=_IST_TIMEZONE)

    # Nightly dreaming cycle at 2:00 AM IST
    scheduler.add_job(
        _run_dreaming_cycle,
        CronTrigger(hour=2, minute=0, timezone=_IST_TIMEZONE),
        id="dreaming_nightly",
        name="Nightly Dreaming Cycle",
        misfire_grace_time=7200,  # 2 hour grace if server was down at 2 AM
        replace_existing=True,
    )

    # Ticker card pre-computation at 3:00 AM IST (after dreaming patterns)
    scheduler.add_job(
        _run_preloader,
        CronTrigger(hour=3, minute=0, timezone=_IST_TIMEZONE),
        id="preloader_nightly",
        name="Ticker Card Preloader",
        misfire_grace_time=7200,
        replace_existing=True,
    )

    return scheduler


def _run_dreaming_cycle() -> None:
    """Execute the nightly dreaming cycle."""
    from finagent.dreaming.worker import run_dreaming_in_thread

    logger.info("[DREAMING-SCHEDULER] Starting nightly dreaming cycle...")
    result = run_dreaming_in_thread()
    logger.info("[DREAMING-SCHEDULER] Dreaming result: %s", result)


def _run_preloader() -> None:
    """Execute the ticker card preloader."""
    import asyncio

    from finagent.dreaming.preloader import preload_nifty500_cards

    logger.info("[DREAMING-SCHEDULER] Starting ticker card preloader...")
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        cards = loop.run_until_complete(preload_nifty500_cards())
        logger.info("[DREAMING-SCHEDULER] Pre-computed %d ticker cards", cards)
    except Exception as exc:
        logger.error("[DREAMING-SCHEDULER] Preloader failed: %s", exc)


def start_dreaming_scheduler() -> None:
    """Start the blocking dreaming scheduler."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("Starting dreaming scheduler (IST timezone)...")

    scheduler = _build_dreaming_scheduler()

    def _shutdown(signum: int, frame: Any) -> None:
        logger.info("Shutting down dreaming scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Scheduled dreaming jobs:")
    for job in scheduler.get_jobs():
        logger.info("  %-40s → next: %s", job.name, job.next_run_time)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Dreaming scheduler stopped")


if __name__ == "__main__":
    start_dreaming_scheduler()

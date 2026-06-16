"""Pattern Detector — detect market and governance trends across companies.

Runs nightly during dreaming to detect emerging patterns across the IKG:
  - Promoter pledge spikes (>10% increase quarter-over-quarter)
  - Director exodus (multiple resignations in 30 days)
  - Sector-wide margin compression
  - Revenue growth acceleration/deceleration

Detected patterns are written to memory as TREND facts with ticker tags.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger("finagent.dreaming.pattern_detector")


async def detect_pledge_spikes(
    database_url: str | None = None,
    threshold_change_pct: float = 10.0,
) -> list[dict[str, Any]]:
    """Detect companies with >10% quarter-on-quarter promoter pledge increase.

    Args:
        database_url: PostgreSQL connection string.
        threshold_change_pct: Minimum change to flag as a spike.

    Returns:
        List of spike alerts with: scrip_code, cin, current_pledge, previous_pledge, change
    """
    db_url = database_url or os.getenv("IKG_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    if not db_url:
        return []

    try:
        import psycopg
        from psycopg.rows import dict_row

        sql = """
        with ranked_quarters as (
          select
            scrip_code, cin, quarter,
            total_pledge_pct,
            lag(total_pledge_pct) over (partition by scrip_code order by quarter) as prev_pledge_pct,
            rank() over (partition by scrip_code order by quarter desc) as rn
          from shp_raw
          where total_pledge_pct is not null
        )
        select scrip_code, cin, quarter,
               total_pledge_pct as current_pledge_pct,
               prev_pledge_pct,
               (total_pledge_pct - prev_pledge_pct) as change_pct
        from ranked_quarters
        where rn = 1
          and prev_pledge_pct is not null
          and (total_pledge_pct - prev_pledge_pct) >= %s
        order by change_pct desc
        """

        with psycopg.connect(db_url, row_factory=dict_row, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (threshold_change_pct,))
                results = [dict(r) for r in cur.fetchall()]

        logger.info("[PATTERN] Detected %d pledge spikes (threshold: %.1f%%)", len(results), threshold_change_pct)
        return results

    except Exception as exc:
        logger.error("[PATTERN] Pledge spike detection failed: %s", exc)
        return []


async def detect_director_exodus(
    database_url: str | None = None,
    lookback_days: int = 30,
    min_resignations: int = 2,
) -> list[dict[str, Any]]:
    """Detect companies with multiple director resignations in the lookback window.

    Args:
        database_url: PostgreSQL connection string.
        lookback_days: Window to look back for resignations.
        min_resignations: Minimum resignations to flag.

    Returns:
        List of exodus alerts with: cin, resignation_count, directors
    """
    db_url = database_url or os.getenv("IKG_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    if not db_url:
        return []

    try:
        import psycopg
        from psycopg.rows import dict_row

        cutoff = date.today() - timedelta(days=lookback_days)

        sql = """
        select cin,
               count(*) as resignation_count,
               array_agg(name) as directors,
               max(cessation_date) as latest_cessation
        from directors_raw
        where cessation_date >= %s
          and cessation_date is not null
        group by cin
        having count(*) >= %s
        order by resignation_count desc
        """

        with psycopg.connect(db_url, row_factory=dict_row, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (cutoff, min_resignations))
                results = [dict(r) for r in cur.fetchall()]

        logger.info("[PATTERN] Detected %d director exodus events", len(results))
        return results

    except Exception as exc:
        logger.error("[PATTERN] Director exodus detection failed: %s", exc)
        return []


async def detect_price_volume_anomalies(
    database_url: str | None = None,
    lookback_days: int = 5,
    volume_spike_threshold: float = 3.0,
) -> list[dict[str, Any]]:
    """Detect price/volume anomalies in EOD data.

    Flags: volume spike > Nx 20-day average, price drop > 10% in 3 days.

    Args:
        database_url: PostgreSQL connection string.
        lookback_days: Days to scan for anomalies.
        volume_spike_threshold: Multiple of average volume to flag.

    Returns:
        List of anomaly alerts.
    """
    db_url = database_url or os.getenv("IKG_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    if not db_url:
        return []

    try:
        import psycopg
        from psycopg.rows import dict_row

        cutoff = date.today() - timedelta(days=lookback_days)
        avg_window = date.today() - timedelta(days=30)

        sql = """
        with avg_volumes as (
          select scrip_code, avg(volume) as avg_vol_20d
          from daily_prices
          where trade_date >= %s and trade_date < %s
          group by scrip_code
        ),
        recent_prices as (
          select p.scrip_code, p.trade_date, p.close, p.volume,
                 first_value(p.close) over (
                   partition by p.scrip_code
                   order by p.trade_date desc
                   rows between unbounded preceding and unbounded following
                 ) as latest_close,
                 last_value(p.close) over (
                   partition by p.scrip_code
                   order by p.trade_date desc
                   rows between unbounded preceding and unbounded following
                 ) as oldest_close_in_window
          from daily_prices p
          where p.trade_date >= %s
        )
        select rp.scrip_code,
               rp.trade_date,
               rp.close,
               rp.volume,
               av.avg_vol_20d,
               (rp.volume::numeric / greatest(av.avg_vol_20d, 1)) as volume_spike_ratio
        from recent_prices rp
        join avg_volumes av on rp.scrip_code = av.scrip_code
        where (rp.volume::numeric / greatest(av.avg_vol_20d, 1)) >= %s
           or rp.close < 0.9 * rp.oldest_close_in_window
        order by volume_spike_ratio desc
        limit 50
        """

        with psycopg.connect(db_url, row_factory=dict_row, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (avg_window, cutoff, cutoff, volume_spike_threshold))
                results = [dict(r) for r in cur.fetchall()]

        logger.info("[PATTERN] Detected %d price/volume anomalies", len(results))
        return results

    except Exception as exc:
        logger.error("[PATTERN] Price/volume anomaly detection failed: %s", exc)
        return []


async def run_all_pattern_detectors(
    database_url: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Run all pattern detectors and return combined results.

    Returns:
        dict with keys: pledge_spikes, director_exodus, price_volume_anomalies
    """
    pledge_spikes = await detect_pledge_spikes(database_url)
    director_exodus = await detect_director_exodus(database_url)
    price_anomalies = await detect_price_volume_anomalies(database_url)

    summary = {
        "pledge_spikes": pledge_spikes,
        "director_exodus": director_exodus,
        "price_volume_anomalies": price_anomalies,
    }

    total = sum(len(v) for v in summary.values())
    logger.info("[PATTERN] Total patterns detected: %d", total)
    return summary

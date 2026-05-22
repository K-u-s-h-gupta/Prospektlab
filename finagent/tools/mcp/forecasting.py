"""TimesFM 2.5 local inference wrapper for zero-shot financial forecasting.

Provides two async entry points consumed by specialist agents:

  * ``generate_zero_shot_forecast`` — project numerical trends N periods
    out with multi-quantile risk confidence bands.
  * ``detect_anomalies`` — evaluate whether newly reported values deviate
    from the model's learned temporal patterns.

All synchronous PyTorch / NumPy matrix math is dispatched through a
``ThreadPoolExecutor`` so the FastAPI / AsyncIO event loop is never
blocked.  If the ``timesfm`` package is missing or the model fails to
load, both functions transparently fall back to lightweight statistical
baselines (CAGR extrapolation, z-score bands) and log a warning.
"""

from __future__ import annotations

import asyncio
import logging
import math
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Sequence

logger = logging.getLogger("finagent.tools.mcp.forecasting")

# ---------------------------------------------------------------------------
#  Lazy model singleton — loaded once, reused for all subsequent calls.
# ---------------------------------------------------------------------------

_model = None
_model_load_attempted = False
_TIMESFM_AVAILABLE = False

# Dedicated thread pool so heavy matrix math never contends with
# the event loop's default executor.
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="timesfm")

# Default quantile levels for probabilistic forecasts.
DEFAULT_QUANTILES: list[float] = [0.1, 0.25, 0.5, 0.75, 0.9]


def _ensure_model():
    """Attempt to load TimesFM once; cache the result (or None on failure)."""
    global _model, _model_load_attempted, _TIMESFM_AVAILABLE

    if _model_load_attempted:
        return _model

    _model_load_attempted = True

    try:
        import timesfm  # type: ignore[import-untyped]

        _TIMESFM_AVAILABLE = True
        logger.info("timesfm package found — loading TimesFM 2.5 model …")

        tfm = timesfm.TimesFm(
            hparams=timesfm.TimesFmHparams(
                backend="cpu",
                per_core_batch_size=32,
                horizon_len=128,
            ),
            checkpoint=timesfm.TimesFmCheckpoint(
                huggingface_repo_id="google/timesfm-2.0-200m-pytorch",
            ),
        )
        _model = tfm
        logger.info("TimesFM 2.5 model loaded successfully (CPU backend)")
    except ImportError:
        logger.warning(
            "timesfm package not installed — forecasting will use "
            "statistical fallback. Install with: pip install timesfm"
        )
        _model = None
    except Exception as exc:
        logger.warning("TimesFM model load failed (%s) — using fallback", exc)
        _model = None

    return _model


# ---------------------------------------------------------------------------
#  Output dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ForecastResult:
    """Result of a zero-shot forecast."""

    point_forecast: list[float]
    quantile_forecasts: dict[float, list[float]] = field(default_factory=dict)
    horizon: int = 0
    freq: int = 1
    model_used: str = "timesfm_2.5"
    metadata: dict = field(default_factory=dict)


@dataclass
class AnomalyResult:
    """Result of anomaly detection on new values."""

    is_anomaly: list[bool]
    lower_bound: list[float]   # P10 corridor
    upper_bound: list[float]   # P90 corridor
    deviations: list[float]    # signed deviation magnitude
    model_used: str = "timesfm_2.5"
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
#  Statistical fallbacks (used when timesfm is unavailable)
# ---------------------------------------------------------------------------


def _cagr(values: list[float]) -> float | None:
    """Compound annual growth rate from first to last."""
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        return None
    n = len(values) - 1
    try:
        return (values[-1] / values[0]) ** (1.0 / n) - 1
    except (ZeroDivisionError, ValueError):
        return None


def _fallback_forecast(
    values: list[float],
    horizon: int,
    quantiles: list[float],
) -> ForecastResult:
    """CAGR-based extrapolation with synthetic confidence bands."""
    growth = _cagr(values)
    if growth is None:
        # Linear fallback if CAGR fails (e.g. negative values)
        if len(values) >= 2:
            delta = (values[-1] - values[-2])
        else:
            delta = 0.0
        point = [values[-1] + delta * (i + 1) for i in range(horizon)]
    else:
        last = values[-1]
        point = [last * (1 + growth) ** (i + 1) for i in range(horizon)]

    # Synthetic bands: widen linearly with horizon step.
    if len(values) >= 3:
        hist_std = statistics.stdev(values)
    else:
        hist_std = abs(values[-1]) * 0.05  # 5% of last value

    q_forecasts: dict[float, list[float]] = {}
    for q in quantiles:
        z = statistics.NormalDist().inv_cdf(q) if 0 < q < 1 else 0.0
        q_forecasts[q] = [
            pt + z * hist_std * math.sqrt(i + 1) for i, pt in enumerate(point)
        ]

    return ForecastResult(
        point_forecast=point,
        quantile_forecasts=q_forecasts,
        horizon=horizon,
        freq=1,
        model_used="fallback_statistical",
        metadata={"method": "cagr_extrapolation", "growth_rate": growth},
    )


def _fallback_anomalies(
    historical: list[float],
    new_values: list[float],
) -> AnomalyResult:
    """Z-score-based anomaly detection (±2σ bands)."""
    if len(historical) < 3:
        # Not enough data — report no anomalies.
        return AnomalyResult(
            is_anomaly=[False] * len(new_values),
            lower_bound=[min(historical or [0])] * len(new_values),
            upper_bound=[max(historical or [0])] * len(new_values),
            deviations=[0.0] * len(new_values),
            model_used="fallback_statistical",
            metadata={"method": "insufficient_data"},
        )

    mu = statistics.mean(historical)
    sigma = statistics.stdev(historical)
    if sigma == 0:
        sigma = abs(mu) * 0.01 or 1.0

    lower = mu - 2.0 * sigma
    upper = mu + 2.0 * sigma

    flags = []
    devs = []
    for v in new_values:
        outside = v < lower or v > upper
        flags.append(outside)
        if sigma > 0:
            devs.append((v - mu) / sigma)
        else:
            devs.append(0.0)

    return AnomalyResult(
        is_anomaly=flags,
        lower_bound=[lower] * len(new_values),
        upper_bound=[upper] * len(new_values),
        deviations=devs,
        model_used="fallback_statistical",
        metadata={"method": "zscore_2sigma", "mean": mu, "stdev": sigma},
    )


# ---------------------------------------------------------------------------
#  TimesFM-powered implementations (synchronous — called in executor)
# ---------------------------------------------------------------------------


def _timesfm_forecast_sync(
    model,
    values: list[float],
    horizon: int,
    freq: int,
    quantiles: list[float],
) -> ForecastResult:
    """Run TimesFM forecast synchronously (intended for thread pool)."""
    import numpy as np

    input_array = np.array(values, dtype=np.float32)

    # TimesFM .forecast() returns (point_forecast, quantile_forecast)
    # Input shape: list of 1-D arrays; output: list of 1-D arrays.
    point_out, quantile_out = model.forecast(
        [input_array],
        freq=[freq],
    )

    point_list = point_out[0][:horizon].tolist()

    # Build quantile dict from the model's calibrated quantile head.
    q_dict: dict[float, list[float]] = {}
    if quantile_out is not None and len(quantile_out) > 0:
        q_array = quantile_out[0]  # shape: (horizon, num_quantiles)
        # TimesFM default quantiles: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        default_q = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        for i, dq in enumerate(default_q):
            if i < q_array.shape[1]:
                q_dict[dq] = q_array[:horizon, i].tolist()

    # Map to requested quantiles (nearest available).
    mapped: dict[float, list[float]] = {}
    for rq in quantiles:
        best_key = min(q_dict.keys(), key=lambda k: abs(k - rq)) if q_dict else None
        if best_key is not None:
            mapped[rq] = q_dict[best_key]
        else:
            # Synthesize from point forecast + historical stdev
            if len(values) >= 3:
                hist_std = float(np.std(values))
            else:
                hist_std = abs(values[-1]) * 0.05
            z = statistics.NormalDist().inv_cdf(rq) if 0 < rq < 1 else 0.0
            mapped[rq] = [
                pt + z * hist_std * math.sqrt(j + 1)
                for j, pt in enumerate(point_list)
            ]

    return ForecastResult(
        point_forecast=point_list,
        quantile_forecasts=mapped,
        horizon=horizon,
        freq=freq,
        model_used="timesfm_2.5",
        metadata={"input_length": len(values)},
    )


def _timesfm_anomalies_sync(
    model,
    historical: list[float],
    new_values: list[float],
    freq: int,
) -> AnomalyResult:
    """Run TimesFM-based anomaly detection synchronously."""
    import numpy as np

    # Forecast len(new_values) steps from historical context.
    input_array = np.array(historical, dtype=np.float32)
    horizon = len(new_values)

    point_out, quantile_out = model.forecast(
        [input_array],
        freq=[freq],
    )

    # Extract P10 and P90 as confidence corridor.
    lower_bounds = []
    upper_bounds = []

    if quantile_out is not None and len(quantile_out) > 0:
        q_array = quantile_out[0]
        # Default quantile indices: 0=P10, ..., 8=P90
        p10_idx = 0   # 0.1
        p90_idx = min(8, q_array.shape[1] - 1)  # 0.9

        for step in range(min(horizon, q_array.shape[0])):
            lower_bounds.append(float(q_array[step, p10_idx]))
            upper_bounds.append(float(q_array[step, p90_idx]))
    else:
        # Fall back to point ± 2σ.
        point = point_out[0][:horizon].tolist()
        hist_std = float(np.std(historical)) if len(historical) >= 3 else abs(historical[-1]) * 0.05
        lower_bounds = [p - 2 * hist_std for p in point]
        upper_bounds = [p + 2 * hist_std for p in point]

    # Pad if model returned fewer steps than requested.
    while len(lower_bounds) < horizon:
        lower_bounds.append(lower_bounds[-1] if lower_bounds else 0.0)
        upper_bounds.append(upper_bounds[-1] if upper_bounds else 0.0)

    flags = []
    devs = []
    for i, v in enumerate(new_values):
        lo = lower_bounds[i]
        hi = upper_bounds[i]
        corridor_width = hi - lo if hi != lo else 1.0
        is_outside = v < lo or v > hi
        flags.append(is_outside)
        midpoint = (lo + hi) / 2
        devs.append((v - midpoint) / (corridor_width / 2) if corridor_width else 0.0)

    return AnomalyResult(
        is_anomaly=flags,
        lower_bound=lower_bounds,
        upper_bound=upper_bounds,
        deviations=devs,
        model_used="timesfm_2.5",
        metadata={
            "historical_length": len(historical),
            "new_values_count": len(new_values),
        },
    )


# ---------------------------------------------------------------------------
#  Public async API
# ---------------------------------------------------------------------------


async def generate_zero_shot_forecast(
    values: Sequence[float],
    *,
    horizon: int = 8,
    freq: int = 1,
    quantiles: list[float] | None = None,
) -> ForecastResult:
    """Project numerical trends ``horizon`` periods out with quantile bands.

    Parameters
    ----------
    values : sequence of float
        Historical time-series values (oldest first).
    horizon : int
        Number of future periods to forecast (default 8).
    freq : int
        Frequency indicator for TimesFM (0 = high-freq, 1 = medium, 2 = low).
    quantiles : list of float, optional
        Quantile levels for confidence bands (default [0.1, 0.25, 0.5, 0.75, 0.9]).

    Returns
    -------
    ForecastResult
        Contains point_forecast, quantile_forecasts, and metadata.
    """
    vals = list(values)
    if len(vals) < 2:
        return ForecastResult(
            point_forecast=[],
            horizon=horizon,
            model_used="none",
            metadata={"error": "insufficient_data", "min_required": 2},
        )

    qs = quantiles or DEFAULT_QUANTILES
    loop = asyncio.get_running_loop()
    model = await loop.run_in_executor(_executor, _ensure_model)

    if model is not None:
        try:
            result = await loop.run_in_executor(
                _executor,
                _timesfm_forecast_sync,
                model,
                vals,
                horizon,
                freq,
                qs,
            )
            return result
        except Exception as exc:
            logger.warning(
                "TimesFM forecast failed (%s) — falling back to statistical",
                exc,
            )

    # Fallback path.
    return _fallback_forecast(vals, horizon, qs)


async def detect_anomalies(
    historical: Sequence[float],
    new_values: Sequence[float],
    *,
    freq: int = 1,
) -> AnomalyResult:
    """Check if ``new_values`` deviate from the model's learned patterns.

    Uses TimesFM's probabilistic forecast to build P10–P90 confidence
    corridors.  Values outside the corridor are flagged as anomalies.

    Parameters
    ----------
    historical : sequence of float
        Past time-series values forming the context window.
    new_values : sequence of float
        Newly observed values to evaluate.
    freq : int
        Frequency indicator for TimesFM.

    Returns
    -------
    AnomalyResult
        Per-value anomaly flags, confidence corridors, and deviation magnitudes.
    """
    hist = list(historical)
    nv = list(new_values)

    if len(hist) < 3 or not nv:
        return AnomalyResult(
            is_anomaly=[False] * len(nv),
            lower_bound=[0.0] * len(nv),
            upper_bound=[0.0] * len(nv),
            deviations=[0.0] * len(nv),
            model_used="none",
            metadata={"error": "insufficient_data"},
        )

    loop = asyncio.get_running_loop()
    model = await loop.run_in_executor(_executor, _ensure_model)

    if model is not None:
        try:
            result = await loop.run_in_executor(
                _executor,
                _timesfm_anomalies_sync,
                model,
                hist,
                nv,
                freq,
            )
            return result
        except Exception as exc:
            logger.warning(
                "TimesFM anomaly detection failed (%s) — falling back", exc
            )

    return _fallback_anomalies(hist, nv)

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
import os
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Sequence

logger = logging.getLogger("finagent.tools.mcp.forecasting")

# Remote TimesFM service endpoint (Azure Container Apps or other)
# Set TIMESFM_REMOTE_URL in your environment to offload inference.
# Example: TIMESFM_REMOTE_URL=https://timesfm-inference.xxx.eastus.azurecontainerapps.io
_TIMESFM_REMOTE_URL: str | None = os.environ.get("TIMESFM_REMOTE_URL", None)
_TIMESFM_REMOTE_TIMEOUT: float = float(os.environ.get("TIMESFM_REMOTE_TIMEOUT", "30.0"))

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
    """Load the modern TimesFM 2.5 200M PyTorch model using the recommended pattern.

    Uses direct submodule import + from_pretrained + compile(ForecastConfig).
    Falls back gracefully to statistical methods if anything fails.
    """
    global _model, _model_load_attempted, _TIMESFM_AVAILABLE

    if _model_load_attempted:
        return _model

    _model_load_attempted = True

    try:
        import torch  # type: ignore[import-untyped]
        import timesfm  # type: ignore[import-untyped]
        # Direct import bypasses __init__.py export issues (common in venvs/Colab)
        import timesfm.timesfm_2p5.timesfm_2p5_torch as timesfm_2p5_torch  # type: ignore[import-untyped]

        _TIMESFM_AVAILABLE = True
        logger.info("Loading TimesFM 2.5 200M (PyTorch) via from_pretrained('google/timesfm-2.5-200m-pytorch') ...")

        torch.set_float32_matmul_precision("high")

        model = timesfm_2p5_torch.TimesFM_2p5_200M_torch.from_pretrained(
            "google/timesfm-2.5-200m-pytorch"
        )

        model.compile(
            timesfm.ForecastConfig(
                max_context=512,
                max_horizon=32,
                normalize_inputs=True,
                use_continuous_quantile_head=True,
            )
        )

        _model = model
        logger.info("[TIMESFM] SUCCESS - REAL TimesFM 2.5 200M PyTorch model loaded and compiled successfully - zero-shot forecasting is ACTIVE")
        return _model

    except Exception as exc:
        logger.warning(
            "[TIMESFM] WARNING - TimesFM 2.5 200M load failed (%s). "
            "Forecasting will use statistical fallback (CAGR + z-score). "
            "To enable real model: huggingface-cli login + accept terms on HF + ensure torch + timesfm 2.5 installed.",
            exc,
        )
        _model = None
        _TIMESFM_AVAILABLE = False

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


def cagr(values: list[float]) -> float | None:
    """Compound annual growth rate from first to last (public helper)."""
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        return None
    n = len(values) - 1
    try:
        return (values[-1] / values[0]) ** (1.0 / n) - 1
    except (ZeroDivisionError, ValueError):
        return None


# Backwards-compat alias (some older code may still reference _cagr)
_cagr = cagr


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
    """Run TimesFM forecast synchronously.

    Supports both the new 2.5 compiled model (after from_pretrained + compile)
    and any legacy objects that may still be present.
    """
    import numpy as np

    input_array = np.array(values, dtype=np.float32)

    point_list: list[float] = []
    q_dict: dict[float, list[float]] = {}

    # Try the modern v2.5 API first (after from_pretrained + compile)
    tried_new_api = False
    try:
        # Preferred: high-level forecast if it exists
        if hasattr(model, "forecast"):
            out = model.forecast(horizon=horizon, inputs=[input_array])
            tried_new_api = True
            if isinstance(out, (list, tuple)) and len(out) >= 1:
                point_out = np.asarray(out[0]).reshape(-1)
                point_list = point_out[:horizon].tolist()
                if len(out) > 1 and out[1] is not None:
                    fq = np.asarray(out[1])
                    if fq.ndim >= 2:
                        med_idx = min(5, fq.shape[-1] - 1)
                        q_dict[0.5] = fq.reshape(-1, fq.shape[-1])[:horizon, med_idx].tolist()
    except Exception:
        pass

    # Fallback for new 2.5 model: use forecast_naive (known to exist on the torch implementation)
    if not point_list and hasattr(model, "forecast_naive"):
        try:
            out = model.forecast_naive(horizon=horizon, inputs=[input_array])
            tried_new_api = True
            arr = np.asarray(out[0] if isinstance(out, (list, tuple)) else out)
            point_list = arr.reshape(-1)[:horizon].tolist()
        except Exception:
            pass

    # If the modern calls didn't work, try the old legacy signature (for older timesfm installs)
    if not point_list and not tried_new_api:
        try:
            point_out, quantile_out = model.forecast([input_array], freq=[freq])
            point_list = np.asarray(point_out).reshape(-1)[:horizon].tolist()
            if quantile_out is not None and len(quantile_out) > 0:
                q_array = np.asarray(quantile_out[0])
                default_q = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
                for i, dq in enumerate(default_q):
                    if i < q_array.shape[1]:
                        q_dict[dq] = q_array[:horizon, i].tolist()
        except Exception:
            pass

    # Final safety: if we still have nothing, return empty (will trigger fallback higher up)
    if not point_list:
        point_list = [values[-1]] * horizon if values else [0.0] * horizon

    # Map requested quantiles
    mapped: dict[float, list[float]] = {}
    for rq in quantiles:
        best_key = min(q_dict.keys(), key=lambda k: abs(k - rq)) if q_dict else None
        if best_key is not None:
            mapped[rq] = q_dict[best_key]
        else:
            if len(values) >= 3:
                hist_std = float(np.std(values))
            else:
                hist_std = abs(values[-1]) * 0.05 if values else 1.0
            z = statistics.NormalDist().inv_cdf(rq) if 0 < rq < 1 else 0.0
            mapped[rq] = [pt + z * hist_std * math.sqrt(j + 1) for j, pt in enumerate(point_list)]

    return ForecastResult(
        point_forecast=point_list,
        quantile_forecasts=mapped,
        horizon=horizon,
        freq=freq,
        model_used="timesfm_2.5",
        metadata={"input_length": len(values), "api": "v2.5"},
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

    point_out = None
    quantile_out = None
    tried_new_api = False

    try:
        if hasattr(model, "forecast"):
            out = model.forecast(horizon=horizon, inputs=[input_array])
            tried_new_api = True
            if isinstance(out, (list, tuple)) and len(out) >= 1:
                point_out = np.asarray(out[0])
                if len(out) > 1 and out[1] is not None:
                    quantile_out = np.asarray(out[1])
    except Exception as exc:
        logger.warning("Modern forecast call in anomalies failed: %s", exc)

    if point_out is None and not tried_new_api:
        try:
            point_out, quantile_out = model.forecast(
                [input_array],
                freq=[freq],
            )
            if point_out is not None:
                point_out = np.asarray(point_out)
            if quantile_out is not None:
                quantile_out = np.asarray(quantile_out)
        except Exception:
            pass

    if point_out is None:
        raise ValueError("TimesFM forecast failed to return point predictions")

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
#  Remote client helpers (Azure Container Apps / standalone service)
# ---------------------------------------------------------------------------

async def _remote_forecast(
    values: list[float],
    horizon: int,
    freq: int,
    quantiles: list[float],
) -> ForecastResult | None:
    """Call remote TimesFM REST service for zero-shot forecast."""
    if not _TIMESFM_REMOTE_URL:
        return None
    url = _TIMESFM_REMOTE_URL.rstrip("/") + "/forecast"
    payload = {
        "values": values,
        "horizon": horizon,
        "freq": freq,
        "quantiles": quantiles,
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=_TIMESFM_REMOTE_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        # Convert string-keyed quantiles back to float keys
        q_raw = data.get("quantile_forecasts", {})
        q_mapped = {float(k): v for k, v in q_raw.items()}
        return ForecastResult(
            point_forecast=data.get("point_forecast", []),
            quantile_forecasts=q_mapped,
            horizon=data.get("horizon", horizon),
            freq=data.get("freq", freq),
            model_used=data.get("model_used", "timesfm_2.5_remote"),
            metadata=data.get("metadata", {}),
        )
    except Exception as exc:
        logger.warning(
            "[TIMESFM-REMOTE] Forecast call to %s failed (%s). Falling back to local.",
            url,
            exc,
        )
        return None


async def _remote_anomaly(
    historical: list[float],
    new_values: list[float],
    freq: int,
) -> AnomalyResult | None:
    """Call remote TimesFM REST service for anomaly detection."""
    if not _TIMESFM_REMOTE_URL:
        return None
    url = _TIMESFM_REMOTE_URL.rstrip("/") + "/anomaly"
    payload = {
        "historical": historical,
        "new_values": new_values,
        "freq": freq,
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=_TIMESFM_REMOTE_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        return AnomalyResult(
            is_anomaly=data.get("is_anomaly", []),
            lower_bound=data.get("lower_bound", []),
            upper_bound=data.get("upper_bound", []),
            deviations=data.get("deviations", []),
            model_used=data.get("model_used", "timesfm_2.5_remote"),
            metadata=data.get("metadata", {}),
        )
    except Exception as exc:
        logger.warning(
            "[TIMESFM-REMOTE] Anomaly call to %s failed (%s). Falling back to local.",
            url,
            exc,
        )
        return None


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
    logger.info("[MCP-USE] forecasting | tool=generate_forecast | args={'input_len': %d, 'horizon': %d}", len(vals), horizon)
    try:
        from finagent.state.session_context import record_mcp
        record_mcp("forecasting")
    except ImportError:
        pass
    logger.info("[MCP-FORECAST] generate_zero_shot_forecast called | input_len=%d | horizon=%d | freq=%d", len(vals), horizon, freq)

    if len(vals) < 2:
        logger.warning("[MCP-FORECAST] Insufficient history, returning empty forecast")
        return ForecastResult(
            point_forecast=[],
            horizon=horizon,
            model_used="none",
            metadata={"error": "insufficient_data", "min_required": 2},
        )

    qs = quantiles or DEFAULT_QUANTILES

    # -----------------------------------------------------------------
    #  Remote-first path (Azure Container Apps or standalone service)
    # -----------------------------------------------------------------
    if _TIMESFM_REMOTE_URL:
        logger.info("[TIMESFM-REMOTE] Attempting remote forecast via %s", _TIMESFM_REMOTE_URL)
        remote_result = await _remote_forecast(vals, horizon, freq, qs)
        if remote_result is not None:
            logger.info(
                "[TIMESFM-REMOTE] SUCCESS | model=%s | point_forecast_len=%d",
                remote_result.model_used,
                len(remote_result.point_forecast),
            )
            return remote_result
        logger.info("[TIMESFM-REMOTE] Remote failed — falling through to local inference")

    loop = asyncio.get_running_loop()
    model = await loop.run_in_executor(_executor, _ensure_model)

    if model is not None:
        logger.info("[TIMESFM] generate_zero_shot_forecast -> using REAL TimesFM 2.5 model (horizon=%s)", horizon)
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
            logger.info("[TIMESFM] Real forecast completed, model_used=%s", result.model_used)
            logger.info("[MCP-FORECAST] SUCCESS | model=%s | point_forecast_len=%d", result.model_used, len(result.point_forecast))
            return result
        except Exception as exc:
            logger.warning(
                "TimesFM forecast failed (%s) — falling back to statistical",
                exc,
            )

    # Fallback path.
    logger.info("[TIMESFM] generate_zero_shot_forecast -> using statistical fallback (CAGR + z-score)")
    res = _fallback_forecast(vals, horizon, qs)
    logger.info("[MCP-FORECAST] FALLBACK used | point_forecast_len=%d", len(res.point_forecast))
    return res


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
    logger.info("[MCP-USE] forecasting | tool=detect_anomalies | args={'historical_len': %d, 'new_values_len': %d}", len(hist), len(nv))
    try:
        from finagent.state.session_context import record_mcp
        record_mcp("forecasting")
    except ImportError:
        pass
    logger.info("[MCP-ANOMALY] detect_anomalies called | historical_len=%d | new_values_len=%d", len(hist), len(nv))

    if len(hist) < 3 or not nv:
        return AnomalyResult(
            is_anomaly=[False] * len(nv),
            lower_bound=[0.0] * len(nv),
            upper_bound=[0.0] * len(nv),
            deviations=[0.0] * len(nv),
            model_used="none",
            metadata={"error": "insufficient_data"},
        )

    # -----------------------------------------------------------------
    #  Remote-first path
    # -----------------------------------------------------------------
    if _TIMESFM_REMOTE_URL:
        logger.info("[TIMESFM-REMOTE] Attempting remote anomaly detection via %s", _TIMESFM_REMOTE_URL)
        remote_result = await _remote_anomaly(hist, nv, freq)
        if remote_result is not None:
            logger.info(
                "[TIMESFM-REMOTE] SUCCESS | model=%s | anomalies_detected=%d",
                remote_result.model_used,
                sum(remote_result.is_anomaly),
            )
            return remote_result
        logger.info("[TIMESFM-REMOTE] Remote failed — falling through to local inference")

    loop = asyncio.get_running_loop()
    model = await loop.run_in_executor(_executor, _ensure_model)

    if model is not None:
        logger.info("[TIMESFM] detect_anomalies -> using REAL TimesFM 2.5 model for anomaly screening")
        try:
            result = await loop.run_in_executor(
                _executor,
                _timesfm_anomalies_sync,
                model,
                hist,
                nv,
                freq,
            )
            logger.info("[TIMESFM] Anomaly detection completed with real model, model_used=%s", result.model_used)
            logger.info("[MCP-ANOMALY] SUCCESS | anomalies_detected=%d", sum(result.is_anomaly))
            return result
        except Exception as exc:
            logger.warning(
                "TimesFM anomaly detection failed (%s) — falling back", exc
            )

    logger.info("[TIMESFM] detect_anomalies -> using statistical fallback (z-score)")
    res = _fallback_anomalies(hist, nv)
    logger.info("[MCP-ANOMALY] FALLBACK used | anomalies_detected=%d", sum(res.is_anomaly))
    return res

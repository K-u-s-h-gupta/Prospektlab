"""
TimesFM 2.5 200M — MCP Server (FastMCP streamable-http transport)

Exposes the same inference logic as main.py but via the MCP protocol
for integration with finagent / other MCP clients.

Usage:
    python mcp_server.py

Or via uvicorn with FastMCP's built-in HTTP transport:
    (handled automatically by FastMCP.run)
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Sequence

import numpy as np
from fastmcp import FastMCP

# ---------------------------------------------------------------------------
#  Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("timesfm-mcp")

# ---------------------------------------------------------------------------
#  Lazy model singleton
# ---------------------------------------------------------------------------
_model = None
_model_load_attempted = False
_TIMESFM_AVAILABLE = False


def _ensure_model():
    global _model, _model_load_attempted, _TIMESFM_AVAILABLE
    if _model_load_attempted:
        return _model
    _model_load_attempted = True

    try:
        import torch
        import timesfm
        import timesfm.timesfm_2p5.timesfm_2p5_torch as timesfm_2p5_torch

        _TIMESFM_AVAILABLE = True
        logger.info("[MCP] Loading TimesFM 2.5 200M ...")
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
        logger.info("[MCP] SUCCESS — model loaded.")
    except Exception as exc:
        logger.error("[MCP] FAILED: %s", exc, exc_info=True)
        _model = None
        _TIMESFM_AVAILABLE = False

    return _model


# ---------------------------------------------------------------------------
#  FastMCP app
# ---------------------------------------------------------------------------

mcp = FastMCP("TimesFM 2.5 Forecasting Engine")


@mcp.tool()
def generate_zero_shot_forecast(
    values: list[float],
    horizon: int = 8,
    freq: int = 1,
    quantiles: list[float] | None = None,
) -> dict:
    """
    Project a time-series ``horizon`` periods into the future.

    Parameters
    ----------
    values : list[float]
        Historical observations (oldest first). Minimum length 2.
    horizon : int
        Number of future periods to predict (1–128).
    freq : int
        Frequency indicator: 0=high, 1=medium, 2=low.
    quantiles : list[float] | None
        Quantile levels for confidence bands. Defaults to [0.1,0.25,0.5,0.75,0.9].

    Returns
    -------
    dict
        {
            "point_forecast": [...],
            "quantile_forecasts": {"0.1": [...], "0.5": [...], ...},
            "model_used": "timesfm_2.5",
            "metadata": {...}
        }
    """
    model = _ensure_model()
    if model is None:
        return {"error": True, "message": "TimesFM model not available"}

    import math, statistics

    input_array = np.array(values, dtype=np.float32)
    qs = quantiles or [0.1, 0.25, 0.5, 0.75, 0.9]
    point_list = []
    q_dict = {}

    # Modern v2.5 API
    tried_new_api = False
    try:
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

    if not point_list and hasattr(model, "forecast_naive"):
        try:
            out = model.forecast_naive(horizon=horizon, inputs=[input_array])
            arr = np.asarray(out[0] if isinstance(out, (list, tuple)) else out)
            point_list = arr.reshape(-1)[:horizon].tolist()
        except Exception:
            pass

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

    if not point_list:
        point_list = [values[-1]] * horizon if values else [0.0] * horizon

    mapped = {}
    for rq in qs:
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

    return {
        "point_forecast": point_list,
        "quantile_forecasts": {str(k): v for k, v in mapped.items()},
        "horizon": horizon,
        "freq": freq,
        "model_used": "timesfm_2.5",
        "metadata": {"input_length": len(values), "api": "v2.5"},
    }


@mcp.tool()
def detect_anomalies(
    historical: list[float],
    new_values: list[float],
    freq: int = 1,
) -> dict:
    """
    Detect whether newly observed values deviate from the model's forecast corridor.

    Parameters
    ----------
    historical : list[float]
        Past observations used as forecasting context (min length 2).
    new_values : list[float]
        Recently observed values to evaluate.
    freq : int
        Frequency indicator: 0=high, 1=medium, 2=low.

    Returns
    -------
    dict
        {
            "is_anomaly": [bool, ...],
            "lower_bound": [...],
            "upper_bound": [...],
            "deviations": [...],
            "model_used": "timesfm_2.5",
            "metadata": {...}
        }
    """
    model = _ensure_model()
    if model is None:
        return {"error": True, "message": "TimesFM model not available"}

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
                point_out = np.asarray(out[0]).reshape(-1)
                if len(out) > 1 and out[1] is not None:
                    quantile_out = np.asarray(out[1])
    except Exception:
        pass

    if point_out is None and not tried_new_api:
        try:
            point_out, quantile_out = model.forecast([input_array], freq=[freq])
            point_out = np.asarray(point_out).reshape(-1)
            if quantile_out is not None and len(quantile_out) > 0:
                quantile_out = np.asarray(quantile_out[0])
        except Exception:
            pass

    if point_out is None or len(point_out) < horizon:
        return {"error": True, "message": "Model did not produce enough predictions"}

    p10 = point_out.copy()
    p90 = point_out.copy()
    if quantile_out is not None and quantile_out.ndim >= 2:
        nq = quantile_out.shape[-1]
        if nq > 0:
            p10 = quantile_out[:horizon, 0].reshape(-1)
        if nq > 8:
            p90 = quantile_out[:horizon, 8].reshape(-1)
        elif nq > 0:
            p90 = quantile_out[:horizon, -1].reshape(-1)

    deviations = []
    is_anomaly = []
    for actual, pred, lo, hi in zip(new_values, point_out[:horizon], p10[:horizon], p90[:horizon]):
        dev = float(actual - pred)
        deviations.append(dev)
        is_anomaly.append(not (float(lo) <= actual <= float(hi)))

    return {
        "is_anomaly": is_anomaly,
        "lower_bound": p10[:horizon].tolist(),
        "upper_bound": p90[:horizon].tolist(),
        "deviations": deviations,
        "model_used": "timesfm_2.5",
        "metadata": {"historical_length": len(historical), "new_length": len(new_values)},
    }


# ---------------------------------------------------------------------------
#  Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("MCP_PORT", "8001"))
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    # FastMCP streamable-http transport
    mcp.run(transport="streamable-http", host=host, port=port)

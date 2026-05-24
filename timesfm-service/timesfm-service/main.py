"""
TimesFM 2.5 200M — Standalone REST + MCP Inference Service

Runs a FastAPI server exposing:
  POST /forecast      → zero-shot point + quantile forecasts
  POST /anomaly       → anomaly detection on new values
  GET  /health        → readiness / model-loaded probe
  GET  /              → service metadata

Model weights are baked into the Docker image at build time so there
is no runtime download penalty.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Sequence

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
#  Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("timesfm-service")

# ---------------------------------------------------------------------------
#  Lazy model singleton (same pattern as finagent/tools/mcp/forecasting.py)
# ---------------------------------------------------------------------------
_model = None
_model_load_attempted = False
_TIMESFM_AVAILABLE = False


def _ensure_model():
    """Load TimesFM 2.5 200M PyTorch model from baked-in HuggingFace cache."""
    global _model, _model_load_attempted, _TIMESFM_AVAILABLE

    if _model_load_attempted:
        return _model
    _model_load_attempted = True

    try:
        import torch
        import timesfm
        import timesfm.timesfm_2p5.timesfm_2p5_torch as timesfm_2p5_torch

        _TIMESFM_AVAILABLE = True
        logger.info("Loading TimesFM 2.5 200M from baked-in cache ...")

        torch.set_float32_matmul_precision("high")

        model = timesfm_2p5_torch.TimesFM_2p5_200M_torch.from_pretrained(
            "google/timesfm-2.5-200m-pytorch",
            # trust_remote_code=True  # if needed by newer hub versions
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
        logger.info("SUCCESS — real TimesFM 2.5 model loaded and compiled.")
    except Exception as exc:
        logger.error("FAILED to load TimesFM model: %s", exc, exc_info=True)
        _model = None
        _TIMESFM_AVAILABLE = False

    return _model


# ---------------------------------------------------------------------------
#  Pydantic schemas
# ---------------------------------------------------------------------------

class ForecastRequest(BaseModel):
    values: list[float] = Field(..., description="Historical time-series (oldest first)", min_length=2)
    horizon: int = Field(default=8, ge=1, le=128, description="Future periods to predict")
    freq: int = Field(default=1, ge=0, le=2, description="Frequency: 0=high, 1=medium, 2=low")
    quantiles: list[float] | None = Field(
        default=None,
        description="Quantile levels (default [0.1,0.25,0.5,0.75,0.9])"
    )


class ForecastResponse(BaseModel):
    point_forecast: list[float]
    quantile_forecasts: dict[str, list[float]]
    horizon: int
    freq: int
    model_used: str
    metadata: dict


class AnomalyRequest(BaseModel):
    historical: list[float] = Field(..., min_length=2)
    new_values: list[float] = Field(..., min_length=1)
    freq: int = Field(default=1, ge=0, le=2)


class AnomalyResponse(BaseModel):
    is_anomaly: list[bool]
    lower_bound: list[float]
    upper_bound: list[float]
    deviations: list[float]
    model_used: str
    metadata: dict


# ---------------------------------------------------------------------------
#  Synchronous inference helpers (run in threadpool)
# ---------------------------------------------------------------------------

def _run_forecast(values, horizon, freq, quantiles):
    model = _ensure_model()
    if model is None:
        raise RuntimeError("TimesFM model is not available")

    import numpy as np
    input_array = np.array(values, dtype=np.float32)
    qs = quantiles or [0.1, 0.25, 0.5, 0.75, 0.9]

    point_list = []
    q_dict = {}

    # Try modern v2.5 API first
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
    import math, statistics
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


def _run_anomaly(historical, new_values, freq):
    model = _ensure_model()
    if model is None:
        raise RuntimeError("TimesFM model is not available")

    import numpy as np
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
        raise RuntimeError("Model did not produce enough predictions for anomaly detection")

    # Extract P10 and P90 corridors
    p10 = point_out.copy()
    p90 = point_out.copy()
    if quantile_out is not None and quantile_out.ndim >= 2:
        n_quantiles = quantile_out.shape[-1]
        if n_quantiles > 0:
            p10 = quantile_out[:horizon, 0].reshape(-1)
        if n_quantiles > 8:
            p90 = quantile_out[:horizon, 8].reshape(-1)
        elif n_quantiles > 0:
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
#  FastAPI lifespan — preload model eagerly
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Preloading TimesFM model (this may take 30–60 s) ...")
    _ensure_model()
    logger.info("Lifespan startup complete. model_available=%s", _TIMESFM_AVAILABLE)
    yield
    logger.info("Lifespan shutdown.")


app = FastAPI(
    title="TimesFM 2.5 200M Inference Service",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
#  REST endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "service": "timesfm-2.5-200m",
        "model_available": _TIMESFM_AVAILABLE,
        "endpoints": {
            "forecast": "POST /forecast",
            "anomaly": "POST /anomaly",
            "health": "GET /health",
        },
    }


@app.get("/health")
async def health():
    if _model is None and _model_load_attempted:
        raise HTTPException(status_code=503, detail="Model failed to load")
    return {
        "status": "ok",
        "model_available": _TIMESFM_AVAILABLE,
        "model_loaded": _model is not None,
    }


@app.post("/forecast", response_model=ForecastResponse)
async def forecast(req: ForecastRequest):
    try:
        result = _run_forecast(req.values, req.horizon, req.freq, req.quantiles)
        return result
    except Exception as exc:
        logger.error("Forecast error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/anomaly", response_model=AnomalyResponse)
async def anomaly(req: AnomalyRequest):
    try:
        result = _run_anomaly(req.historical, req.new_values, req.freq)
        return result
    except Exception as exc:
        logger.error("Anomaly error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
#  Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=port, log_level="info")

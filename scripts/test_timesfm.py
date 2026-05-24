"""Safe test script for TimesFM 2.5 (200M) integration.

Run this from the project root AFTER you have activated the isolated venv:

    cd C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB
    .\\.venv-finagent\\Scripts\\Activate.ps1

Then:

    python scripts/test_timesfm.py

It will:
1. Try to import timesfm
2. Attempt to load the 200M PyTorch model (CPU)
3. Run a tiny zero-shot forecast
4. Show whether the real model or the statistical fallback was used

This will never touch your global Python installation.
"""

from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path

# Make sure we can import from the finagent package
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

async def main():
    print("=" * 70)
    print("TimesFM 2.5 (200M) Integration Smoke Test")
    print("Python:", sys.version)
    print("Working dir:", os.getcwd())
    print("=" * 70)

    try:
        from finagent.tools.mcp.forecasting import (
            generate_zero_shot_forecast,
            _TIMESFM_AVAILABLE,
            _ensure_model,
        )
        print("\n[1] Forecasting module imported successfully.")
    except Exception as e:
        print("\n[ERROR] Could not import forecasting module:", e)
        return

    print(f"\n[2] _TIMESFM_AVAILABLE flag at import time: {_TIMESFM_AVAILABLE}")

    print("\n[3] Attempting to load TimesFM model (this may take 30-120s first time)...")
    model = _ensure_model()
    print(f"    Model object: {model}")
    print(f"    _TIMESFM_AVAILABLE after load attempt: {_TIMESFM_AVAILABLE}")

    # Tiny synthetic series (quarterly revenue-like numbers)
    test_series = [120.0, 128.5, 135.2, 142.0, 150.8, 158.3, 167.1]

    print("\n[4] Running generate_zero_shot_forecast on 7 data points (horizon=4)...")
    try:
        result = await generate_zero_shot_forecast(
            test_series,
            horizon=4,
            freq=1,  # medium frequency
            quantiles=[0.1, 0.5, 0.9],
        )
        print("    Success!")
        print(f"    model_used           : {result.model_used}")
        print(f"    point_forecast       : {[round(x,2) for x in result.point_forecast]}")
        print(f"    P50 (median)         : {[round(x,2) for x in result.quantile_forecasts.get(0.5, [])]}")
        print(f"    metadata             : {result.metadata}")
    except Exception as exc:
        print("    [ERROR] Forecast call raised:", exc)

    print("\n" + "=" * 70)
    if result and result.model_used == "timesfm_2.5":
        print("✅ REAL TimesFM 2.5 model is active and working!")
    else:
        print("ℹ️  Using statistical fallback (timesfm not available or failed to load).")
        print("   This is expected on Python 3.14 or when the package is not installed.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

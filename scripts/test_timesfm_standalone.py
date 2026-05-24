"""
Modern TimesFM 2.5 200M PyTorch Smoke Test (Standalone)

Run inside the isolated venv after following the safe install steps:

    cd C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB
    .\.venv-finagent\Scripts\Activate.ps1
    python scripts/test_timesfm_standalone.py

This uses the exact recommended loading pattern:
- Direct submodule import
- from_pretrained("google/timesfm-2.5-200m-pytorch")
- compile(ForecastConfig(...))
"""

from __future__ import annotations
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("timesfm-modern-test")

async def main():
    print("=" * 75)
    print("TimesFM 2.5 200M PyTorch — Modern Loading Test")
    print("Python:", sys.version)
    print("=" * 75)

    try:
        import torch
        import timesfm
        import timesfm.timesfm_2p5.timesfm_2p5_torch as timesfm_2p5_torch
    except ImportError as e:
        print("❌ Missing dependency:", e)
        print("   Make sure you ran the safe install recipe (torch + timesfm from GitHub).")
        return

    torch.set_float32_matmul_precision("high")

    print("\nLoading model via from_pretrained('google/timesfm-2.5-200m-pytorch') ...")
    try:
        model = timesfm_2p5_torch.TimesFM_2p5_200M_torch.from_pretrained(
            "google/timesfm-2.5-200m-pytorch"
        )
        model.compile(
            timesfm.ForecastConfig(
                max_context=512,
                max_horizon=8,
                normalize_inputs=True,
                use_continuous_quantile_head=True,
            )
        )
        print("✅ Model loaded and compiled successfully!")
    except Exception as e:
        print("❌ from_pretrained / compile failed:")
        print(type(e).__name__, ":", str(e)[:400])
        print("\nTip: If you see 'Repository Not Found' or 401, go to the HF model page,")
        print("     accept the terms, then run:  huggingface-cli login")
        return

    # Tiny forecast test
    import numpy as np
    series = np.array([120.0, 128.0, 135.0, 142.0, 151.0, 158.0, 167.0], dtype=np.float32)

    print("\nRunning forecast(horizon=4, inputs=[series]) ...")
    try:
        point, quantiles = model.forecast(horizon=4, inputs=[series])
        print("Point forecast :", np.asarray(point).reshape(-1)[:4].round(2).tolist())
        print("Success! The integration is ready for ValuationAgent / AccountingAgent.")
    except Exception as e:
        print("Forecast call failed (the model may expect a different call shape):", e)

    print("=" * 75)


if __name__ == "__main__":
    asyncio.run(main())

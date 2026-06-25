"""Upstox daily token refresh scheduler.

Standalone invocation wrapper. Core logic lives in finagent.upstox_token_scheduler
so it can be imported directly by the FastAPI lifespan.

Usage (standalone / one-shot refresh):
  python scripts/upstox_token_scheduler.py
"""

from __future__ import annotations

import logging
import os
from pathlib import Path


# ── Load .env before importing finagent ─────────────────────────────────────
try:
    from dotenv import load_dotenv
    _root = Path(__file__).resolve().parents[1]
    for _candidate in [_root / "backend" / "finagent" / ".env", _root / ".env"]:
        if _candidate.exists():
            load_dotenv(_candidate)
            break
except ImportError:
    pass

# ── Delegate to the finagent package module ──────────────────────────────────
try:
    import sys as _sys
    _backend = str(Path(__file__).resolve().parents[1] / "backend")
    if _backend not in _sys.path:
        _sys.path.insert(0, _backend)
    from finagent.upstox_token_scheduler import (  # noqa: F401 — re-export
        _write_token,
        refresh_token_sync,
        refresh_token_async,
        schedule_daily_refresh,
    )
except ImportError as _e:
    raise ImportError(
        "Could not import finagent.upstox_token_scheduler. "
        "Ensure backend/ is in PYTHONPATH or run from repo root."
    ) from _e


# ── Standalone invocation ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    success = refresh_token_sync()
    sys.exit(0 if success else 1)

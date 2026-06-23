"""Upstox daily token refresh scheduler.

Runs inside the production Docker container (Python 3.11+) as an APScheduler
async job. Fires every day at 03:45 IST (22:15 UTC) — after the 03:30 IST
token expiry and before market open (09:15 IST).

How it works:
  1. Uses the `upstox_totp` library (headless, no browser) to log in with
     UPSTOX_USERNAME / UPSTOX_PASSWORD / UPSTOX_TOTP_SECRET + UPSTOX_CLIENT_ID
     / UPSTOX_CLIENT_SECRET / UPSTOX_REDIRECT_URI from environment variables.
  2. Writes the fresh token to:
       • os.environ["UPSTOX_ACCESS_TOKEN"]   (picked up by the WS feed on reconnect)
       • /app/.upstox/access_token.txt       (fallback read by the feed manager)
  3. The UpstoxFeedManager re-reads the token on every WebSocket reconnect, so
     no gateway restart is required.

Environment variables required (set in ECS task definition / Elastic Beanstalk):
  UPSTOX_USERNAME       10-digit mobile number
  UPSTOX_PASSWORD       Upstox account password
  UPSTOX_TOTP_SECRET    TOTP seed (from Upstox 2FA setup)
  UPSTOX_CLIENT_ID      API key from Upstox developer portal
  UPSTOX_CLIENT_SECRET  API secret from Upstox developer portal
  UPSTOX_REDIRECT_URI   Registered redirect URI (e.g. https://127.0.0.1)

Usage (standalone):
  python scripts/upstox_token_scheduler.py   # runs one refresh immediately
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger("finagent.upstox_token_scheduler")


def _token_dir() -> Path:
    """Resolve the .upstox directory.

    In Docker the working dir is /app, so the token lands at /app/.upstox/.
    On Windows dev machines it falls back to the repo root's .upstox/.
    A custom path can be set via UPSTOX_CACHE_DIR.
    """
    base = os.getenv("UPSTOX_CACHE_DIR")
    if base:
        root = Path(base)
    else:
        # Try /app (Docker), fall back to repo root
        docker_dir = Path("/app/.upstox")
        repo_dir = Path(__file__).resolve().parents[1] / ".upstox"
        root = docker_dir if Path("/app").exists() else repo_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def _token_file() -> Path:
    return _token_dir() / "access_token.txt"


def _write_token(token: str) -> None:
    """Persist token to disk + os.environ so the feed picks it up without restart."""
    # 1. Update environment variable (read by _read_access_token on reconnect)
    os.environ["UPSTOX_ACCESS_TOKEN"] = token

    # 2. Write to file (backup, also read by _read_access_token)
    path = _token_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(token, encoding="utf-8")
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600 — POSIX only, no-op on Windows
    except Exception:
        pass
    tmp.replace(path)
    logger.info("Upstox token written to %s (%d chars)", path, len(token))


def refresh_token_sync() -> bool:
    """Synchronous token refresh. Returns True on success, False on failure."""
    required = ["UPSTOX_USERNAME", "UPSTOX_PASSWORD", "UPSTOX_TOTP_SECRET",
                "UPSTOX_CLIENT_ID", "UPSTOX_CLIENT_SECRET", "UPSTOX_REDIRECT_URI"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        logger.warning(
            "Upstox token refresh skipped — missing env vars: %s. "
            "Set these in your ECS task definition / Elastic Beanstalk env.",
            ", ".join(missing),
        )
        return False

    try:
        from upstox_totp import UpstoxTOTP  # type: ignore[import]
    except ImportError:
        logger.error(
            "upstox-totp not installed. Add 'upstox-totp>=1.0.7' to requirements-finagent.txt "
            "and rebuild the Docker image."
        )
        return False

    try:
        logger.info("Starting Upstox TOTP headless login for token refresh...")
        upx = UpstoxTOTP()
        resp = upx.app_token.get_access_token()
    except Exception as exc:
        logger.error("Upstox TOTP login failed: %s", exc, exc_info=True)
        return False

    if not getattr(resp, "success", False) or not getattr(resp, "data", None):
        logger.error(
            "Upstox token generation unsuccessful. "
            "Check credentials / TOTP secret / Upstox app settings."
        )
        return False

    token: str = getattr(resp.data, "access_token", "") or ""
    if not token:
        logger.error("Upstox returned an empty access token.")
        return False

    _write_token(token)
    logger.info("✅ Upstox token refreshed successfully (%d chars)", len(token))
    return True


async def refresh_token_async() -> None:
    """Async wrapper for use with APScheduler AsyncIOScheduler."""
    import asyncio
    loop = asyncio.get_event_loop()
    success = await loop.run_in_executor(None, refresh_token_sync)
    if not success:
        logger.warning(
            "Upstox token refresh failed. Live feed will continue with the previous token "
            "until it expires, then fall back to NSE/Yahoo polling."
        )


def schedule_daily_refresh(scheduler) -> None:
    """Register the daily 03:45 IST (22:15 UTC) token refresh job on `scheduler`.

    Call this from the FastAPI lifespan with an APScheduler AsyncIOScheduler
    instance that has already been started.

    Example:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.start()
        schedule_daily_refresh(scheduler)
    """
    # 03:45 IST = 22:15 UTC (IST is UTC+5:30)
    scheduler.add_job(
        refresh_token_async,
        trigger="cron",
        hour=22,
        minute=15,
        id="upstox_daily_token_refresh",
        name="Upstox daily token refresh (03:45 IST)",
        replace_existing=True,
        misfire_grace_time=600,  # allow up to 10 min late if server was down
        max_instances=1,
    )
    logger.info(
        "Upstox token refresh scheduled: daily at 22:15 UTC (03:45 IST). "
        "Token will be refreshed before market open."
    )


# ── Standalone invocation ───────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from pathlib import Path

    # Load .env if running standalone
    try:
        from dotenv import load_dotenv
        for candidate in [
            Path(__file__).parents[1] / "backend" / "finagent" / ".env",
            Path(__file__).parents[1] / ".env",
        ]:
            if candidate.exists():
                load_dotenv(candidate)
                break
    except ImportError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    success = refresh_token_sync()
    sys.exit(0 if success else 1)

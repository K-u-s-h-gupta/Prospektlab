"""Upstox daily token refresh — finagent-importable module.

Core logic used by the FastAPI lifespan scheduler.
The standalone scripts/upstox_token_scheduler.py delegates here.

Fires daily at 03:45 IST (22:15 UTC) — after the 03:30 IST token expiry
and before market open (09:15 IST).

How it works:
  1. Playwright headless Chromium performs the full Upstox OAuth2 login:
       mobile number (#mobileNum)
       → "Get OTP" → TOTP code (#otpNum, from UPSTOX_TOTP_SECRET)
       → Continue → PIN (#pinCode, from UPSTOX_PIN_CODE)
       → Continue → redirect_uri?code=<auth_code>
     Then exchanges the auth_code for an access_token via Upstox token API.
  2. Falls back to upstox_totp package if available (requires Python 3.12+).
  3. Writes the fresh token to:
       • os.environ["UPSTOX_ACCESS_TOKEN"]   (picked up by WS feed on reconnect)
       • .upstox/access_token.txt            (fallback read by feed manager)
  4. UpstoxFeedManager re-reads token on every WebSocket reconnect —
     no gateway restart required.

Required env vars:
  UPSTOX_USERNAME       10-digit mobile number
  UPSTOX_PIN_CODE       6-digit login PIN
  UPSTOX_TOTP_SECRET    TOTP seed (from Upstox 2FA setup)
  UPSTOX_CLIENT_ID      API key from Upstox developer portal
  UPSTOX_CLIENT_SECRET  API secret from Upstox developer portal
  UPSTOX_REDIRECT_URI   Registered redirect URI (e.g. https://127.0.0.1)
"""
from __future__ import annotations

import logging
import os
import stat
import time
import urllib.parse
from pathlib import Path

logger = logging.getLogger("finagent.upstox_token_scheduler")

_REQUIRED_ENV = [
    "UPSTOX_USERNAME",
    "UPSTOX_TOTP_SECRET",
    "UPSTOX_CLIENT_ID",
    "UPSTOX_CLIENT_SECRET",
    "UPSTOX_REDIRECT_URI",
]


def _token_dir() -> Path:
    """Resolve the .upstox directory.

    In Docker: /app/.upstox/
    On dev Windows: <repo_root>/.upstox/
    Override via UPSTOX_CACHE_DIR env var.
    """
    base = os.getenv("UPSTOX_CACHE_DIR")
    if base:
        root = Path(base)
    else:
        docker_dir = Path("/app/.upstox")
        # backend/finagent/upstox_token_scheduler.py -> parents[2] = repo root
        repo_dir = Path(__file__).resolve().parents[2] / ".upstox"
        root = docker_dir if Path("/app").exists() else repo_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def _token_file() -> Path:
    return _token_dir() / "access_token.txt"


def _write_token(token: str) -> None:
    """Persist token to disk + os.environ so the feed picks it up without restart."""
    os.environ["UPSTOX_ACCESS_TOKEN"] = token
    path = _token_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(token, encoding="utf-8")
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600 — no-op on Windows
    except Exception:
        pass
    tmp.replace(path)
    logger.info("Upstox token written to %s (%d chars)", path, len(token))


# ---------------------------------------------------------------------------
# Playwright headless login (primary method — works on Python 3.11+)
# ---------------------------------------------------------------------------

def _playwright_refresh() -> str | None:
    """Headless Chromium OAuth2 login to Upstox.

    Returns the access_token string on success, None on any failure.

    Upstox login flow (verified against live login.upstox.com UI):
      1. Navigate to authorization dialog → redirects to login.upstox.com.
      2. Fill mobile number (#mobileNum) via React-native event → click "Get OTP".
      3. OTP/TOTP page (#otpNum): fill TOTP from UPSTOX_TOTP_SECRET → "Continue".
      4. PIN page (#pinCode): fill 6-digit PIN from UPSTOX_PIN_CODE → "Continue".
      5. Browser redirects to redirect_uri?code=<auth_code> (captured via request intercept).
      6. POST auth_code to Upstox token endpoint → receive access_token.
    """
    client_id = os.getenv("UPSTOX_CLIENT_ID", "").strip()
    client_secret = os.getenv("UPSTOX_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("UPSTOX_REDIRECT_URI", "").strip()
    mobile = os.getenv("UPSTOX_USERNAME", "").strip()
    mpin = (os.getenv("UPSTOX_PIN_CODE") or "").strip()
    totp_secret = os.getenv("UPSTOX_TOTP_SECRET", "").strip()

    if not all([client_id, client_secret, redirect_uri, mobile, totp_secret]):
        logger.error(
            "Playwright Upstox login: missing credentials. "
            "Need UPSTOX_CLIENT_ID, UPSTOX_CLIENT_SECRET, UPSTOX_REDIRECT_URI, "
            "UPSTOX_USERNAME, UPSTOX_TOTP_SECRET."
        )
        return None

    if not mpin:
        logger.error(
            "UPSTOX_PIN_CODE not set. Upstox login requires the 6-digit PIN. "
            "Set UPSTOX_PIN_CODE=<your-6-digit-pin> in backend/finagent/.env."
        )
        return None

    try:
        import pyotp
    except ImportError:
        logger.error("pyotp not installed. Run: uv pip install pyotp")
        return None

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        logger.error("playwright not installed. Run: playwright install chromium")
        return None

    auth_url = (
        "https://api.upstox.com/v2/login/authorization/dialog"
        f"?response_type=code&client_id={urllib.parse.quote(client_id)}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}&state=prospektlab"
    )
    totp_gen = pyotp.TOTP(totp_secret)

    # auth_code is set by the request interceptor and read after the browser closes.
    captured: dict = {"auth_code": None}

    def _on_request(request):
        if captured["auth_code"]:
            return
        url = request.url
        redirect_host = redirect_uri.rstrip("/").split("://")[-1]
        if redirect_host in url and "code=" in url:
            try:
                params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                codes = params.get("code", [])
                if codes:
                    captured["auth_code"] = codes[0]
                    logger.info("Upstox auth code captured from request (len=%d)", len(codes[0]))
            except Exception:
                pass

    logger.info("Playwright Upstox login: opening headless Chromium...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            page.on("request", _on_request)

            try:
                # Step 1: Load the Upstox authorization dialog.
                page.goto(auth_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)
                logger.info("Playwright: loaded login page at %s", page.url)

                # Step 2: Fill mobile number using React-native InputEvent.
                page.locator("#mobileNum").wait_for(state="visible", timeout=10000)
                page.evaluate(
                    """(mobile) => {
                        const input = document.getElementById('mobileNum');
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value').set;
                        setter.call(input, mobile);
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                        input.dispatchEvent(new Event('blur',  { bubbles: true }));
                    }""",
                    mobile,
                )
                logger.info("Playwright: filled mobile number")
                page.get_by_role("button", name="Get OTP").click()
                logger.info("Playwright: clicked Get OTP")

                # Step 3: Wait for OTP/TOTP input and fill TOTP.
                page.locator("#otpNum").wait_for(state="visible", timeout=20000)
                logger.info("Playwright: OTP/TOTP page loaded")

                totp_ok = False
                for attempt in range(3):
                    current_totp = totp_gen.now()
                    remaining = 30 - (int(time.time()) % 30)
                    logger.info(
                        "Playwright: filling TOTP '%s' (attempt %d, %ds remaining in window)",
                        current_totp, attempt + 1, remaining,
                    )
                    page.locator("#otpNum").clear()
                    page.locator("#otpNum").fill(current_totp)
                    page.get_by_role("button", name="Continue").click()

                    # After TOTP → PIN page should appear.
                    try:
                        page.locator("#pinCode").wait_for(state="visible", timeout=10000)
                        totp_ok = True
                        logger.info("Playwright: TOTP accepted, PIN page appeared")
                        break
                    except PWTimeout:
                        if captured["auth_code"]:
                            break  # Redirect already captured
                        if page.locator("#otpNum").is_visible():
                            logger.warning("Playwright: TOTP '%s' rejected, retrying...", current_totp)
                            time.sleep(2)
                            continue
                        break  # Some other transition

                if not totp_ok and not captured["auth_code"]:
                    logger.error("Playwright: TOTP step failed after 3 attempts")
                    return None

                # Step 4: Fill 6-digit PIN.
                if not captured["auth_code"]:
                    page.locator("#pinCode").wait_for(state="visible", timeout=5000)
                    page.locator("#pinCode").fill(mpin)
                    logger.info("Playwright: filled PIN")
                    page.get_by_role("button", name="Continue").click()
                    logger.info("Playwright: clicked Continue after PIN")
                    # Wait up to 8 s for the request interceptor to fire.
                    for _ in range(16):
                        if captured["auth_code"]:
                            break
                        time.sleep(0.5)

            except Exception as exc:
                logger.error("Playwright Upstox login error: %s", exc, exc_info=True)
                return None
            finally:
                browser.close()

    except Exception as exc:
        logger.error("Playwright sync_playwright context error: %s", exc)
        return None

    auth_code = captured["auth_code"]
    if not auth_code:
        logger.error("Playwright Upstox login: failed to capture auth code")
        return None

    logger.info("Playwright: auth code obtained (%d chars), exchanging for access token...", len(auth_code))

    # Step 5: Exchange auth code for access token (plain HTTP — no browser needed).
    try:
        import httpx
        token_resp = httpx.post(
            "https://api.upstox.com/v2/login/authorization/token",
            headers={
                "accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "code": auth_code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15.0,
        )
        if token_resp.status_code == 200:
            resp_data = token_resp.json()
            token = (
                resp_data.get("access_token")
                or (resp_data.get("data") or {}).get("access_token", "")
            )
            if token:
                logger.info("Playwright Upstox login: access_token obtained (%d chars)", len(token))
                return token
            logger.error("Upstox token response missing access_token: %s", resp_data)
            return None
        else:
            logger.error(
                "Upstox token exchange failed: HTTP %d — %s",
                token_resp.status_code, token_resp.text[:300],
            )
            return None
    except Exception as exc:
        logger.error("Upstox token exchange HTTP error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# upstox-totp fallback (requires Python 3.12+, optional)
# ---------------------------------------------------------------------------

def _upstox_totp_refresh() -> str | None:
    """Fallback using the upstox-totp package (Python 3.12+ only)."""
    try:
        from upstox_totp import UpstoxTOTP  # type: ignore[import]
    except ImportError:
        return None  # not installed or wrong Python version

    try:
        upx = UpstoxTOTP()
        resp = upx.app_token.get_access_token()
    except Exception as exc:
        logger.error("upstox-totp login failed: %s", exc, exc_info=True)
        return None

    if not getattr(resp, "success", False) or not getattr(resp, "data", None):
        logger.error("upstox-totp: token generation unsuccessful.")
        return None

    token: str = getattr(resp.data, "access_token", "") or ""
    return token or None


# ---------------------------------------------------------------------------
# Public refresh API
# ---------------------------------------------------------------------------

def refresh_token_sync() -> bool:
    """Synchronous token refresh. Returns True on success, False on failure.

    Tries methods in order:
      1. Playwright headless login (Python 3.11+, uses UPSTOX_PIN_CODE + TOTP)
      2. upstox-totp package (Python 3.12+ only)
    """
    missing = [k for k in _REQUIRED_ENV if not os.getenv(k)]
    if missing:
        logger.warning(
            "Upstox token refresh skipped — missing env vars: %s. "
            "Set these in backend/finagent/.env.",
            ", ".join(missing),
        )
        return False

    # Method 1: Playwright headless browser (works on Python 3.11)
    logger.info("Attempting Upstox token refresh via Playwright headless login...")
    token = _playwright_refresh()

    # Method 2: upstox-totp package (Python 3.12+ only)
    if not token:
        logger.info("Playwright method failed, trying upstox-totp package...")
        token = _upstox_totp_refresh()

    if not token:
        logger.error(
            "All Upstox token refresh methods failed.\n"
            "  To fix: paste a fresh token in backend/finagent/.env as:\n"
            "    UPSTOX_ACCESS_TOKEN=eyJ...\n"
            "  Get a new token from: https://account.upstox.com/developer/apps"
        )
        return False

    _write_token(token)
    logger.info("Upstox token refreshed successfully (%d chars)", len(token))
    return True


async def refresh_token_async() -> None:
    """Async wrapper for use with APScheduler AsyncIOScheduler."""
    import asyncio
    loop = asyncio.get_event_loop()
    success = await loop.run_in_executor(None, refresh_token_sync)
    if not success:
        logger.warning(
            "Upstox token refresh failed. Live feed continues with previous token "
            "until it expires, then falls back to NSE/Yahoo polling."
        )


def schedule_daily_refresh(scheduler) -> None:
    """Register the daily 03:45 IST (22:15 UTC) token refresh job.

    Call from the FastAPI lifespan with an APScheduler AsyncIOScheduler
    that has already been started:

        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from finagent.upstox_token_scheduler import schedule_daily_refresh
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.start()
        schedule_daily_refresh(scheduler)
    """
    scheduler.add_job(
        refresh_token_async,
        trigger="cron",
        hour=22,
        minute=15,
        id="upstox_daily_token_refresh",
        name="Upstox daily token refresh (03:45 IST)",
        replace_existing=True,
        misfire_grace_time=600,   # up to 10 min late if server was briefly down
        max_instances=1,
    )
    logger.info(
        "Upstox token refresh scheduled: daily at 22:15 UTC (03:45 IST). "
        "Token refreshed before market open."
    )

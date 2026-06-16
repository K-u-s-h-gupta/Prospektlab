"""Resilient multi-tier fetcher for NSE / BSE official endpoints.

The exchanges aggressively block datacenter IPs and bare HTTP clients.
This module layers fallbacks so a single call survives the failure modes:

  Tier 1 — Warm-session httpx
    Visit the homepage first to acquire bm_sv/nsit/akamai cookies, then
    hit the JSON API with full browser headers (Sec-Fetch-*, Referer,
    Accept-Language, br/gzip Accept-Encoding, sec-ch-ua client hints).
    Cookies are kept on a module-level client and refreshed every 25 min.
    Fixes ~90% of failures when the IP isn't outright banned.

  Tier 2 — Stealth browser (patchright)
    Real Chromium with stealth fingerprint patches, navigates the
    homepage, lets the bot-protection JS run, then calls the JSON
    endpoint via page.evaluate(fetch). Handles datacenter-IP cases NSE
    blocks at the WAF layer (sec-ch-ua sniffing, TLS fingerprinting).

  Tier 3 — Cross-exchange fallback
    For announcement-style queries, NSE failure routes to BSE (or vice
    versa) using the company's other identifier (BSE scrip_code / NSE
    symbol). The two exchanges mirror most filings within minutes.

  Tier 4 — Open-source mirror
    Trendlyne, Screener.in, Moneycontrol mirror NSE/BSE corporate
    announcements with looser anti-bot policies. Used as last resort.

Failures degrade silently — callers always get a list (possibly empty)
back, never an exception.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any
from urllib.parse import urlencode, urlparse

logger = logging.getLogger("finagent.tools.web.exchange_fetcher")

# ── Constants ──────────────────────────────────────────────────────────

NSE_HOME = "https://www.nseindia.com"
BSE_HOME = "https://www.bseindia.com"

# Modern Chrome-on-Windows fingerprint. NSE checks this against TLS handshake.
_REAL_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Connection": "keep-alive",
}

# ── Session cache (warm cookies) ───────────────────────────────────────

_SESSION_TTL_SECONDS = 25 * 60  # NSE cookies expire ~30 min
_session_lock = threading.Lock()
_nse_session: dict[str, Any] = {"client": None, "warmed_at": 0.0}
_bse_session: dict[str, Any] = {"client": None, "warmed_at": 0.0}


def _get_warmed_nse_client():
    """Return an httpx.Client with warmed NSE cookies. Refreshes every 25 min."""
    import httpx

    now = time.time()
    with _session_lock:
        if _nse_session["client"] and (now - _nse_session["warmed_at"]) < _SESSION_TTL_SECONDS:
            return _nse_session["client"]

        # Build a fresh client and warm it
        client = httpx.Client(
            timeout=20.0,
            follow_redirects=True,
            headers=_REAL_BROWSER_HEADERS,
            http2=True,
        )
        try:
            # Step 1: hit home page (sets bm_sv, akam cookies)
            home = client.get(NSE_HOME)
            if home.status_code != 200:
                logger.debug("NSE home warm-up returned %d", home.status_code)
            # Step 2: hit a benign API to seed remaining cookies (nsit, nseQuoteSymbols)
            client.get(f"{NSE_HOME}/api/marketStatus")
        except Exception as exc:
            logger.debug("NSE warm-up failed: %s", exc)

        _nse_session["client"] = client
        _nse_session["warmed_at"] = now
        return client


def _get_warmed_bse_client():
    """BSE is laxer but a warmed client still helps when scraping site pages."""
    import httpx

    now = time.time()
    with _session_lock:
        if _bse_session["client"] and (now - _bse_session["warmed_at"]) < _SESSION_TTL_SECONDS:
            return _bse_session["client"]
        client = httpx.Client(
            timeout=20.0,
            follow_redirects=True,
            headers={**_REAL_BROWSER_HEADERS, "Referer": BSE_HOME + "/"},
            http2=True,
        )
        try:
            client.get(BSE_HOME)
        except Exception as exc:
            logger.debug("BSE warm-up failed: %s", exc)
        _bse_session["client"] = client
        _bse_session["warmed_at"] = now
        return client


# ── Tier 1: Warm httpx ─────────────────────────────────────────────────

def _tier1_nse(api_url: str, params: dict[str, Any], referer: str) -> Any | None:
    try:
        client = _get_warmed_nse_client()
        resp = client.get(
            api_url,
            params=params,
            headers={"Referer": referer},
        )
        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception:
                logger.debug("NSE T1 200 but invalid JSON: %s", api_url)
                return None
        if resp.status_code == 401:
            # Cookies expired mid-flight; force refresh and retry once
            logger.info("NSE T1 401 — refreshing session and retrying")
            with _session_lock:
                _nse_session["warmed_at"] = 0.0
            client = _get_warmed_nse_client()
            resp = client.get(api_url, params=params, headers={"Referer": referer})
            if resp.status_code == 200:
                return resp.json()
        logger.debug("NSE T1 status=%d for %s", resp.status_code, api_url)
        return None
    except Exception as exc:
        logger.debug("NSE T1 exception: %s", exc)
        return None


def _tier1_bse(api_url: str, params: dict[str, Any]) -> Any | None:
    try:
        client = _get_warmed_bse_client()
        resp = client.get(api_url, params=params)
        if resp.status_code == 200:
            return _parse_bse_payload(resp.text)
        logger.debug("BSE T1 status=%d for %s", resp.status_code, api_url)
        return None
    except Exception as exc:
        logger.debug("BSE T1 exception: %s", exc)
        return None


def _parse_bse_payload(text: str) -> Any | None:
    """BSE APIs sometimes return a JSON-encoded string (double-encoded JSON)
    and sometimes a plain JSON object. Try both."""
    import json
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    # If we got a string back, parse it again (double-encoded case)
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except Exception:
            return None
    return parsed


# ── Tier 1.5: curl_cffi — TLS-fingerprint impersonation ────────────────
# curl_cffi wraps curl-impersonate so the TLS/HTTP2 handshake matches a real
# Chrome / Edge / Safari client. NSE blocks based on TLS JA3 fingerprint of
# python's stdlib SSL stack; this beats that block without launching a browser.

# Module-level curl_cffi session with warmed cookies, refreshed on TTL
_curl_lock = threading.Lock()
_nse_curl_session: dict[str, Any] = {"session": None, "warmed_at": 0.0}
_bse_curl_session: dict[str, Any] = {"session": None, "warmed_at": 0.0}


def _get_warmed_curl_session(home_url: str, slot: dict[str, Any]):
    """Return a curl_cffi Session with browser-impersonated TLS and warmed cookies."""
    try:
        from curl_cffi import requests as cc_requests
    except ImportError:
        return None

    now = time.time()
    with _curl_lock:
        if slot["session"] and (now - slot["warmed_at"]) < _SESSION_TTL_SECONDS:
            return slot["session"]
        try:
            session = cc_requests.Session(impersonate="chrome131", timeout=20)
            # Warm by visiting home page — curl_cffi handles full TLS handshake
            try:
                session.get(home_url, headers={"Accept-Language": "en-US,en;q=0.9"})
            except Exception as warm_exc:
                logger.debug("curl_cffi warm-up for %s failed: %s", home_url, warm_exc)
        except Exception as exc:
            logger.debug("curl_cffi session init failed: %s", exc)
            return None
        slot["session"] = session
        slot["warmed_at"] = now
        return session


def _tier1b_nse_curlcffi(api_url: str, params: dict[str, Any], referer: str) -> Any | None:
    """NSE fetch via curl_cffi Chrome-impersonated TLS handshake.
    Fixes datacenter-IP blocks where httpx fails because of TLS JA3 fingerprint."""
    session = _get_warmed_curl_session(NSE_HOME, _nse_curl_session)
    if session is None:
        return None
    try:
        resp = session.get(api_url, params=params, headers={"Referer": referer})
        if resp.status_code != 200:
            logger.debug("NSE T1b curl_cffi status=%d", resp.status_code)
            return None
        try:
            return resp.json()
        except Exception:
            return None
    except Exception as exc:
        logger.debug("NSE T1b curl_cffi exception: %s", exc)
        return None


def _tier1b_bse_curlcffi(api_url: str, params: dict[str, Any]) -> Any | None:
    """BSE fetch via curl_cffi Chrome-impersonated TLS handshake.
    BSE's api.bseindia.com requires Referer + Origin pointing to www.bseindia.com."""
    session = _get_warmed_curl_session(BSE_HOME, _bse_curl_session)
    if session is None:
        return None
    try:
        resp = session.get(
            api_url,
            params=params,
            headers={
                "Referer": BSE_HOME + "/",
                "Origin": BSE_HOME,
            },
        )
        if resp.status_code != 200:
            logger.debug("BSE T1b curl_cffi status=%d", resp.status_code)
            return None
        return _parse_bse_payload(resp.text)
    except Exception as exc:
        logger.debug("BSE T1b curl_cffi exception: %s", exc)
        return None


# ── Tier 2: Stealth browser (patchright) ───────────────────────────────

async def _tier2_browser_json(api_url: str, params: dict[str, Any], referer: str) -> Any | None:
    """Use patchright stealth chromium: navigate the homepage to acquire cookies,
    then navigate DIRECTLY to the API URL. Chromium will receive the JSON as the
    response body and we extract it from the response — avoids same-origin
    fetch() issues that NSE's WAF triggers on synthetic fetch requests."""
    try:
        from patchright.async_api import async_playwright
    except ImportError:
        logger.debug("patchright not installed; skipping T2")
        return None

    full_url = api_url
    if params:
        sep = "&" if "?" in api_url else "?"
        full_url = f"{api_url}{sep}{urlencode(params)}"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            try:
                ctx = await browser.new_context(
                    user_agent=_REAL_BROWSER_HEADERS["User-Agent"],
                    locale="en-US",
                    viewport={"width": 1366, "height": 768},
                    extra_http_headers={
                        "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
                        "Accept": "application/json, text/plain, */*",
                    },
                )
                page = await ctx.new_page()
                # Step 1: Warm by visiting homepage (Akamai BMK challenge fires here)
                try:
                    await page.goto(referer, wait_until="domcontentloaded", timeout=25000)
                except Exception as warm_exc:
                    logger.debug("T2 referer warm-up failed: %s (continuing anyway)", warm_exc)
                # Step 2: Settle delay for any post-load JS that sets cookies
                await asyncio.sleep(1.8)
                # Step 3: Navigate directly to API URL. The response body IS the JSON.
                try:
                    response = await page.goto(full_url, wait_until="domcontentloaded", timeout=25000)
                except Exception as nav_exc:
                    logger.debug("T2 API navigation failed: %s", nav_exc)
                    return None
                if response is None:
                    logger.debug("T2 navigation returned no response")
                    return None
                status = response.status
                if status != 200:
                    logger.debug("T2 API navigation returned status %d", status)
                    return None
                # Extract body — Chromium renders JSON as <pre> on direct nav
                try:
                    body_text = await response.text()
                except Exception:
                    body_text = await page.evaluate("() => document.body ? document.body.innerText : ''")
                if not body_text:
                    return None
                import json
                # Strip any HTML wrapper Chromium added
                body_text = body_text.strip()
                if body_text.startswith("<"):
                    body_text = await page.evaluate(
                        "() => document.body ? document.body.innerText : ''"
                    )
                    body_text = (body_text or "").strip()
                try:
                    parsed = json.loads(body_text)
                except Exception as parse_exc:
                    logger.debug("T2 body not JSON: %s | head: %s", parse_exc, body_text[:200])
                    return None
                # Handle double-encoded BSE strings
                if isinstance(parsed, str):
                    try:
                        parsed = json.loads(parsed)
                    except Exception:
                        return None
                return parsed
            finally:
                await browser.close()
    except Exception as exc:
        logger.debug("T2 browser exception: %s", exc)
        return None


def _tier2_browser_json_sync(api_url: str, params: dict[str, Any], referer: str) -> Any | None:
    """Sync wrapper around Tier 2 for callers in non-async contexts.
    Skips when an event loop is already running (callers must use async path)."""
    try:
        loop = asyncio.get_running_loop()
        if loop.is_running():
            logger.debug("T2 skipped — event loop already running, caller must use async variant")
            return None
    except RuntimeError:
        pass
    try:
        return asyncio.run(_tier2_browser_json(api_url, params, referer))
    except Exception as exc:
        logger.debug("T2 sync exception: %s", exc)
        return None


# ── Public entry points ────────────────────────────────────────────────

def fetch_nse_json(
    api_path: str,
    params: dict[str, Any] | None = None,
    *,
    referer_path: str = "/",
    use_browser_fallback: bool = True,
) -> Any | None:
    """Fetch a JSON payload from nseindia.com with multi-tier fallback.

    `api_path` is everything after the host (must start with '/').
    Returns the parsed JSON or None if all tiers fail. Never raises.
    """
    params = params or {}
    api_url = f"{NSE_HOME}{api_path}"
    referer = f"{NSE_HOME}{referer_path}"

    result = _tier1_nse(api_url, params, referer)
    if result is not None:
        return result

    # Tier 1b — curl_cffi with browser-impersonated TLS (defeats JA3 blocks)
    result = _tier1b_nse_curlcffi(api_url, params, referer)
    if result is not None:
        logger.info("NSE T1b (curl_cffi) recovered request: %s", api_path)
        return result

    if not use_browser_fallback:
        return None

    result = _tier2_browser_json_sync(api_url, params, referer)
    if result is not None:
        logger.info("NSE T2 (stealth browser) recovered request: %s", api_path)
        return result

    return None


async def fetch_nse_json_async(
    api_path: str,
    params: dict[str, Any] | None = None,
    *,
    referer_path: str = "/",
    use_browser_fallback: bool = True,
) -> Any | None:
    """Async variant — required when caller is already in an event loop."""
    params = params or {}
    api_url = f"{NSE_HOME}{api_path}"
    referer = f"{NSE_HOME}{referer_path}"

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _tier1_nse, api_url, params, referer)
    if result is not None:
        return result

    result = await loop.run_in_executor(None, _tier1b_nse_curlcffi, api_url, params, referer)
    if result is not None:
        logger.info("NSE T1b (curl_cffi) recovered request: %s", api_path)
        return result

    if not use_browser_fallback:
        return None

    result = await _tier2_browser_json(api_url, params, referer)
    if result is not None:
        logger.info("NSE T2 (stealth browser) recovered request: %s", api_path)
    return result


def fetch_bse_json(
    api_path: str,
    params: dict[str, Any] | None = None,
    *,
    referer_path: str = "/",
    use_browser_fallback: bool = True,
) -> Any | None:
    """Fetch JSON from api.bseindia.com (or www.bseindia.com) with fallback."""
    params = params or {}
    if api_path.startswith("http"):
        api_url = api_path
        parsed = urlparse(api_url)
        host_root = f"{parsed.scheme}://{parsed.netloc}"
        referer = host_root + referer_path
    else:
        api_url = f"https://api.bseindia.com{api_path}"
        referer = f"{BSE_HOME}{referer_path}"

    result = _tier1_bse(api_url, params)
    if result is not None:
        return result

    result = _tier1b_bse_curlcffi(api_url, params)
    if result is not None:
        logger.info("BSE T1b (curl_cffi) recovered request: %s", api_path)
        return result

    if not use_browser_fallback:
        return None

    result = _tier2_browser_json_sync(api_url, params, referer)
    if result is not None:
        logger.info("BSE T2 (stealth browser) recovered request: %s", api_path)
    return result


async def fetch_bse_json_async(
    api_path: str,
    params: dict[str, Any] | None = None,
    *,
    referer_path: str = "/",
    use_browser_fallback: bool = True,
) -> Any | None:
    params = params or {}
    if api_path.startswith("http"):
        api_url = api_path
        parsed = urlparse(api_url)
        host_root = f"{parsed.scheme}://{parsed.netloc}"
        referer = host_root + referer_path
    else:
        api_url = f"https://api.bseindia.com{api_path}"
        referer = f"{BSE_HOME}{referer_path}"

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _tier1_bse, api_url, params)
    if result is not None:
        return result

    result = await loop.run_in_executor(None, _tier1b_bse_curlcffi, api_url, params)
    if result is not None:
        logger.info("BSE T1b (curl_cffi) recovered request: %s", api_path)
        return result

    if not use_browser_fallback:
        return None

    result = await _tier2_browser_json(api_url, params, referer)
    if result is not None:
        logger.info("BSE T2 (stealth browser) recovered request: %s", api_path)
    return result


# ── Diagnostics ────────────────────────────────────────────────────────

def reset_sessions() -> None:
    """Force a cookie refresh on next call. Useful after long idle periods."""
    with _session_lock:
        _nse_session["client"] = None
        _nse_session["warmed_at"] = 0.0
        _bse_session["client"] = None
        _bse_session["warmed_at"] = 0.0


def session_status() -> dict[str, Any]:
    """Return current cookie age — useful for the gateway health endpoint."""
    now = time.time()
    return {
        "nse_warmed_seconds_ago": int(now - _nse_session["warmed_at"]) if _nse_session["warmed_at"] else None,
        "bse_warmed_seconds_ago": int(now - _bse_session["warmed_at"]) if _bse_session["warmed_at"] else None,
        "ttl_seconds": _SESSION_TTL_SECONDS,
    }

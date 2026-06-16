"""MCA21 Director Network — Patchright-powered browser scraper.

Uses Patchright (CDP-patched Playwright) to authenticate a browser session
with the MCA21 V3 portal, then extracts director data for each company CIN.

Why Patchright:
  The MCA21 V3 portal (mca.gov.in) returns an "Error page" HTML for plain
  HTTP POST requests — it requires a real, authenticated browser session
  with valid cookies from a prior navigation. Patchright provides an
  undetectable Chromium instance that navigates and extracts data while
  passing all bot-detection checks.

Session strategy:
  - One browser instance reused across ALL company lookups (amortizes browser
    startup cost across potentially 2000+ companies)
  - Navigates MCA company master page to warm the session
  - Re-navigates every 30 minutes to refresh session cookies
  - 36s delay between companies (100 req/hour limit)

Proxy strategy:
  - Each N companies, rotate to a new proxy to avoid IP-based rate limiting
  - Falls back to direct connection if proxies fail

Pagination:
  - Director listing is per-CIN and typically returns all directors in one
    response; no pagination needed at the company level
  - The outer loop paginated by processing companies in batches

Rate limit: 100 req/hour = 36 sec/req
Schedule: Monthly refresh (weekend)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from datetime import datetime, date
from typing import Any

import httpx

from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.scrapers._engine import SmartBrowser, SmartHTTPClient, get_browser, run_async

logger = logging.getLogger("finagent.ikg.scrapers.mca_directors")

# MCA21 V3 endpoints
_MCA_BASE_URL = "https://www.mca.gov.in"
_MCA_COMPANY_SEARCH_URL = "https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html"
_MCA_DIRECTOR_URL = "https://www.mca.gov.in/mcafoportal/companyLLPMasterData.do"
_MCA_API_URL = "https://efiling.mca.gov.in/eFiling/getDirectorDetailsForCIN"

_REQUEST_DELAY_S = 36.0   # 100 req/hour
_SESSION_REFRESH_INTERVAL = 1800  # 30 min
_PROXY_ROTATE_EVERY = 20  # rotate proxy every N companies
_SOLVECAPTCHA_TIMEOUT_S = float(os.getenv("MCA_CAPTCHA_SOLVER_TIMEOUT_S", "120"))
_SOLVECAPTCHA_MAX_ATTEMPTS = max(1, int(os.getenv("MCA_CAPTCHA_MAX_ATTEMPTS", "3")))
_MCA_CAPTCHA_SCRAPER_ENABLED = os.getenv("FINAGENT_ENABLE_MCA_DIRECTOR_CAPTCHA", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Referer": "https://www.mca.gov.in/",
    "Origin": "https://www.mca.gov.in",
}
_MCA_CIN_INPUT_SELECTOR = "#masterdata-search-box"
_MCA_SEARCH_RADIO_COMPANY = "#company"
_MCA_SEARCH_BUTTON_SELECTORS = ("#searchicon", "button.searchicon", "button[type='submit']")
_MCA_RESULT_ROW_SELECTORS = (
    ".masterdatasearch table.two-masterdata tbody tr",
    ".masterdatasearch table.one tbody tr",
)
_MCA_CAPTCHA_MODAL = "#captchaModal"
_MCA_CAPTCHA_INPUT = "#customCaptchaInput"
_MCA_CAPTCHA_CANVAS = "#captchaCanvas"
_MCA_CAPTCHA_REFRESH = "#refresh-img"
_MCA_CAPTCHA_SUBMIT_BUTTONS = ("#check", "#checkOne")
_MCA_CAPTCHA_STATUS = "#showResult"


def _get_solvecaptcha_api_key() -> str | None:
    for key_name in (
        "SOLVECAPTCHA_API_KEY",
        "SOLVECAPTCHA_KEY",
        "CAPTCHA_SOLVER_API_KEY",
        "MCA_CAPTCHA_SOLVER_API_KEY",
        "TWOCAPTCHA_API_KEY",
    ):
        value = (os.getenv(key_name) or "").strip()
        if value:
            return value
    return None


def _solve_mca_captcha(image_bytes: bytes) -> str:
    api_key = _get_solvecaptcha_api_key()
    if not api_key:
        raise RuntimeError(
            "Captcha solver key missing. Set SOLVECAPTCHA_API_KEY (or MCA_CAPTCHA_SOLVER_API_KEY)."
        )
    if not image_bytes:
        raise RuntimeError("Empty captcha image bytes")

    try:
        from solvecaptcha import Solvecaptcha  # type: ignore
    except Exception as exc:  # pragma: no cover - depends on runtime install
        raise RuntimeError(
            "solvecaptcha-python is not installed. Install dependencies to enable MCA captcha solving."
        ) from exc

    solver = Solvecaptcha(api_key)
    encoded = base64.b64encode(image_bytes).decode("ascii")
    # The client accepts image URLs, files, and image payloads.
    result = solver.normal(f"data:image/png;base64,{encoded}")

    if isinstance(result, str):
        solved = result.strip()
    elif isinstance(result, dict):
        solved = str(
            result.get("code")
            or result.get("text")
            or result.get("captcha")
            or result.get("answer")
            or ""
        ).strip()
    else:
        solved = str(result or "").strip()

    solved = re.sub(r"[^A-Za-z0-9]", "", solved)
    if len(solved) < 4:
        raise RuntimeError(f"Captcha solver returned invalid text: {result!r}")
    return solved[:6]


class MCABrowserSession:
    """Manages a long-lived Patchright browser session for MCA21 scraping."""

    def __init__(self) -> None:
        self._browser: SmartBrowser | None = None
        self._page: Any = None
        self._session_started: float = 0.0
        self._cookies: list[dict[str, Any]] = []
        self._captcha_solver_enabled = bool(_get_solvecaptcha_api_key())

    async def start(self) -> None:
        """Launch browser and warm MCA session."""
        self._browser = SmartBrowser(headless=True, persistent=True)
        await self._browser.start()
        self._page = await self._browser.new_page()
        await self._warm_session()

    async def _warm_session(self) -> None:
        """Navigate to MCA to establish session cookies."""
        logger.info("Warming MCA21 browser session...")
        try:
            await self._page.goto(
                _MCA_COMPANY_SEARCH_URL,
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await asyncio.sleep(2 + (0.5 * (hash(str(time.time())) % 3)))
            # Navigate to main MCA page as well
            await self._page.goto(_MCA_BASE_URL, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(1.5)
            self._session_started = time.monotonic()
            logger.info("MCA21 session warmed successfully")
        except Exception as exc:
            logger.warning("MCA session warm failed: %s", exc)

    async def _refresh_if_needed(self) -> None:
        """Refresh session if older than threshold."""
        if time.monotonic() - self._session_started > _SESSION_REFRESH_INTERVAL:
            logger.info("Refreshing MCA21 browser session (age > %ds)", _SESSION_REFRESH_INTERVAL)
            await self._warm_session()

    async def get_cookies_for_httpx(self) -> dict[str, str]:
        """Extract browser cookies for use with httpx requests."""
        if not self._page:
            return {}
        try:
            cookies = await self._browser._context.cookies()  # type: ignore[union-attr]
            return {c["name"]: c["value"] for c in cookies if "mca.gov.in" in c.get("domain", "")}
        except Exception:
            return {}

    async def fetch_directors_via_page(self, cin: str) -> list[dict[str, Any]]:
        """Use browser page to fetch and extract director data for a CIN."""
        if not self._page:
            return []

        await self._refresh_if_needed()

        try:
            # Try the API endpoint via page fetch (uses browser session cookies)
            result = await self._page.evaluate(
                f"""async () => {{
                    const resp = await fetch(
                        '{_MCA_DIRECTOR_URL}',
                        {{
                            method: 'POST',
                            headers: {{
                                'Content-Type': 'application/x-www-form-urlencoded',
                                'Accept': 'application/json, text/html, */*',
                            }},
                            body: 'companyID={cin}&requestType=CINbased',
                            credentials: 'include',
                        }}
                    );
                    const text = await resp.text();
                    return {{ status: resp.status, body: text }};
                }}"""
            )

            status = result.get("status", 0)
            body = result.get("body", "")

            if status == 200 and body and not body.strip().startswith("<!"):
                try:
                    data = json.loads(body)
                    directors = parse_mca_director_response(data, cin=cin)
                    if directors:
                        logger.info("MCA browser fetch: %d directors for CIN=%s", len(directors), cin)
                        return directors
                except (json.JSONDecodeError, ValueError):
                    pass
            elif status == 200 and body:
                parsed_from_html = _parse_directors_from_html(body, cin)
                if parsed_from_html:
                    logger.info("MCA browser HTML parse: %d directors for CIN=%s", len(parsed_from_html), cin)
                    return parsed_from_html

            # Fallback: navigate to company page and scrape visible data
            return await self._scrape_director_page(cin)

        except Exception as exc:
            logger.warning("MCA browser fetch failed for CIN=%s: %s", cin, exc)
            return await self._scrape_director_page(cin)

    async def _goto_mds_page(self) -> bool:
        if not self._page:
            return False
        await self._page.goto(_MCA_COMPANY_SEARCH_URL, wait_until="domcontentloaded", timeout=45000)
        await asyncio.sleep(1.8)
        title = (await self._page.title() or "").strip().lower()
        if "access denied" in title or "fo login" in title:
            logger.warning("MCA MDS page blocked: title=%s", title)
            return False
        return True

    async def _click_first_result_row(self) -> bool:
        if not self._page:
            return False
        for selector in _MCA_RESULT_ROW_SELECTORS:
            locator = self._page.locator(selector)
            count = await locator.count()
            if count > 0:
                await locator.first.click()
                await asyncio.sleep(1.0)
                return True
        return False

    async def _solve_captcha_modal_if_visible(self, cin: str) -> bool:
        if not self._page:
            return False
        modal = self._page.locator(_MCA_CAPTCHA_MODAL)
        if await modal.count() == 0 or not await modal.is_visible():
            return True
        if not self._captcha_solver_enabled:
            logger.warning("MCA captcha required for CIN=%s but solver API key is missing", cin)
            return False

        for attempt in range(1, _SOLVECAPTCHA_MAX_ATTEMPTS + 1):
            canvas = self._page.locator(_MCA_CAPTCHA_CANVAS)
            if await canvas.count() == 0:
                logger.warning("MCA captcha canvas not found for CIN=%s", cin)
                return False

            await asyncio.sleep(1.2)
            image_bytes = await canvas.screenshot(type="png")
            try:
                solved = await asyncio.to_thread(_solve_mca_captcha, image_bytes)
            except Exception as exc:
                logger.warning("MCA captcha solve failed (attempt %d/%d): %s", attempt, _SOLVECAPTCHA_MAX_ATTEMPTS, exc)
                solved = ""

            if not solved:
                refresh = self._page.locator(_MCA_CAPTCHA_REFRESH)
                if await refresh.count():
                    await refresh.first.click()
                await asyncio.sleep(1.2)
                continue

            input_box = self._page.locator(_MCA_CAPTCHA_INPUT)
            if await input_box.count() == 0:
                logger.warning("MCA captcha input not found for CIN=%s", cin)
                return False
            await input_box.fill(solved)

            clicked = False
            for submit_selector in _MCA_CAPTCHA_SUBMIT_BUTTONS:
                button = self._page.locator(submit_selector)
                if await button.count() and await button.first.is_visible():
                    await button.first.click()
                    clicked = True
                    break
            if not clicked:
                logger.warning("MCA captcha submit button not visible for CIN=%s", cin)
                return False

            await asyncio.sleep(2.5)
            if not await modal.is_visible():
                return True

            status_text = ""
            status = self._page.locator(_MCA_CAPTCHA_STATUS)
            if await status.count():
                status_text = (await status.first.text_content() or "").strip().lower()
            if any(token in status_text for token in ("incorrect", "expired", "retry", "missing")):
                refresh = self._page.locator(_MCA_CAPTCHA_REFRESH)
                if await refresh.count():
                    await refresh.first.click()
                await asyncio.sleep(1.0)
                continue

        logger.warning("MCA captcha attempts exhausted for CIN=%s", cin)
        return False

    async def _extract_session_directors(self, cin: str) -> list[dict[str, Any]]:
        if not self._page:
            return []
        try:
            payload = await self._page.evaluate(
                """() => ({
                    filteredDirData: sessionStorage.getItem('filteredDirData') || '',
                    companyDetails: sessionStorage.getItem('companyDetails') || ''
                })"""
            )
        except Exception:
            return []

        filtered_raw = str((payload or {}).get("filteredDirData") or "")
        if not filtered_raw:
            return []
        try:
            filtered = json.loads(filtered_raw)
        except Exception:
            return []
        if not isinstance(filtered, list):
            return []
        return parse_mca_filtered_directors(filtered, cin)

    async def _scrape_director_page(self, cin: str) -> list[dict[str, Any]]:
        """Navigate the MCA MDS flow, solve captcha, and extract directors."""
        if not self._page:
            return []
        try:
            if not await self._goto_mds_page():
                return []

            company_radio = self._page.locator(_MCA_SEARCH_RADIO_COMPANY)
            if await company_radio.count():
                await company_radio.first.check()

            cin_input = self._page.locator(_MCA_CIN_INPUT_SELECTOR)
            if await cin_input.count() == 0:
                logger.warning("MCA CIN search input missing for CIN=%s", cin)
                return []
            await cin_input.fill(cin)

            clicked = False
            for selector in _MCA_SEARCH_BUTTON_SELECTORS:
                button = self._page.locator(selector)
                if await button.count() and await button.first.is_visible():
                    await button.first.click()
                    clicked = True
                    break
            if not clicked:
                await self._page.keyboard.press("Enter")

            await asyncio.sleep(2.0)
            if not await self._solve_captcha_modal_if_visible(cin):
                return []

            # Search result tables are populated after captcha validation.
            await asyncio.sleep(2.0)
            if not await self._click_first_result_row():
                # If no row was rendered, there is no match for this CIN.
                return []

            if not await self._solve_captcha_modal_if_visible(cin):
                return []

            # Session data is populated by fnStoreDirCompDataInSession on success.
            for _ in range(8):
                directors = await self._extract_session_directors(cin)
                if directors:
                    return directors
                await asyncio.sleep(1.0)

            content = await self._page.content()
            return _parse_directors_from_html(content, cin)
        except Exception as exc:
            logger.debug("MCA director MDS scrape failed for CIN=%s: %s", cin, exc)
            return []

    async def close(self) -> None:
        """Close browser session."""
        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
        if self._browser:
            await self._browser.close()
        self._page = None
        self._browser = None


def _parse_directors_from_html(html: str, cin: str) -> list[dict[str, Any]]:
    """Extract director information from MCA company HTML page."""
    directors = []
    # Look for director table rows — MCA renders them in <tr> tags
    din_pattern = re.compile(r"\b(\d{8})\b")
    name_pattern = re.compile(r"([A-Z][A-Z\s]+(?:KUMAR|SINGH|SHARMA|RAO|PATEL|GUPTA|MEHTA|VERMA|JAIN|SHAH|AGARWAL|BAJAJ|[A-Z]{2,}))", re.I)

    # Try to find structured data in script tags (MCA sometimes embeds JSON)
    json_pattern = re.compile(r"var\s+directorData\s*=\s*(\[.*?\]);", re.S)
    json_match = json_pattern.search(html)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            return parse_mca_director_response(data, cin=cin)
        except Exception:
            pass

    # Fall back to table scraping
    table_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
    for row_match in table_pattern.finditer(html):
        row_html = row_match.group(1)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S | re.I)
        cells_text = [re.sub(r"<[^>]+>", "", cell).strip() for cell in cells]

        # Look for DIN in cells
        din = None
        name = None
        designation = None
        for i, cell in enumerate(cells_text):
            if din_pattern.match(cell.strip()) and len(cell.strip()) == 8:
                din = cell.strip()
                if i + 1 < len(cells_text):
                    name = cells_text[i + 1]
                if i + 2 < len(cells_text):
                    designation = cells_text[i + 2]
                break

        if din and name and len(name) > 3:
            directors.append({
                "cin": cin,
                "din": din,
                "name": name,
                "designation": designation or "Director",
                "appointment_date": None,
                "cessation_date": None,
            })

    return directors


# ─── Original parse/store functions (kept for compatibility) ──────────────────

def parse_mca_filtered_directors(filtered_directors: list[dict[str, Any]], cin: str) -> list[dict[str, Any]]:
    """Parse MCA sessionStorage `filteredDirData` payload into normalized rows."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    cin_upper = (cin or "").strip().upper()

    for item in filtered_directors:
        if not isinstance(item, dict):
            continue

        raw_din = str(item.get("DIN") or item.get("din") or "").strip()
        din = raw_din if re.fullmatch(r"\d{8}", raw_din or "") else ""

        first = str(item.get("firstName") or "").strip()
        middle = str(item.get("middleName") or "").strip()
        last = str(item.get("lastName") or "").strip()
        name = " ".join(part for part in (first, middle, last) if part).strip()
        if not name:
            name = str(item.get("name") or item.get("fullName") or "").strip()
        if not name:
            continue

        roles = item.get("MCAUserRole")
        if not isinstance(roles, list):
            roles = []

        matched_roles: list[dict[str, Any]] = []
        for role in roles:
            if not isinstance(role, dict):
                continue
            role_cin = str(role.get("cin") or role.get("CIN") or "").strip().upper()
            if cin_upper and role_cin != cin_upper:
                continue
            matched_roles.append(role)

        if not matched_roles and cin_upper:
            matched_roles = [{}]
        if not matched_roles:
            continue

        for role in matched_roles:
            designation = str(role.get("designation") or role.get("Designation") or "Director").strip()
            appointment_date = _parse_mca_date(
                str(role.get("appointmentDate") or role.get("dateOfAppointment") or "")
            )
            cessation_date = _parse_mca_date(
                str(role.get("cessationDate") or role.get("dateOfCessation") or "")
            )
            status = str(role.get("signatoryAssociationStatus") or "").strip().lower()
            if status not in {"", "active", "resigned", "deactivated", "null"}:
                continue

            dedupe_key = (din or name.upper(), designation.upper())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            rows.append(
                {
                    "cin": cin_upper,
                    "din": din,
                    "name": name,
                    "designation": designation or "Director",
                    "appointment_date": appointment_date,
                    "cessation_date": cessation_date,
                }
            )

    return rows


def fetch_mca_directors(cin: str, timeout_s: float = 30.0) -> list[dict[str, Any]]:
    """Fetch director records using SmartHTTPClient with proxy + retry.

    Falls back gracefully if MCA session not warmed.
    For full browser session support, use MCABrowserSession.
    """
    from finagent.ikg.scrapers._engine import sync_post

    try:
        resp = sync_post(
            _MCA_DIRECTOR_URL,
            data={"companyID": cin, "requestType": "CINbased"},
            headers=_BROWSER_HEADERS,
            timeout=timeout_s,
        )

        if resp.status_code == 200:
            body = resp.text.strip()
            if body and not body.startswith("<!"):
                try:
                    data = resp.json()
                    directors = parse_mca_director_response(data, cin=cin)
                    if directors:
                        return directors
                except Exception:
                    pass
            if body:
                html_directors = _parse_directors_from_html(body, cin)
                if html_directors:
                    return html_directors

        logger.debug("MCA HTTP fetch returned no JSON for CIN=%s (status=%d)", cin, resp.status_code)
        return []

    except Exception as exc:
        logger.debug("MCA director HTTP fetch failed for CIN=%s: %s", cin, exc)
        return []


def parse_mca_director_response(
    data: dict[str, Any] | list[Any],
    cin: str,
) -> list[dict[str, Any]]:
    """Parse MCA21 director API response."""
    directors = []
    items = data if isinstance(data, list) else (
        data.get("directors") or data.get("signatories") or
        data.get("data") or data.get("Table") or []
    )

    for item in items:
        if not isinstance(item, dict):
            continue

        din = str(item.get("DIN") or item.get("din") or item.get("director_din") or "").strip()
        name = str(
            item.get("DirectorName") or item.get("name") or item.get("director_name") or
            item.get("NAME") or item.get("DIRECTOR_NAME") or ""
        ).strip()

        if not din or not name:
            continue

        designation = str(
            item.get("Designation") or item.get("designation") or
            item.get("director_designation") or item.get("DESIGNATION") or ""
        ).strip()

        appointment_date_raw = str(
            item.get("AppointmentDate") or item.get("appointment_date") or
            item.get("DATE_OF_APPOINTMENT") or ""
        ).strip()

        cessation_date_raw = str(
            item.get("CessationDate") or item.get("cessation_date") or
            item.get("DATE_OF_CESSATION") or ""
        ).strip()

        directors.append({
            "cin": cin,
            "din": din,
            "name": name,
            "designation": designation,
            "appointment_date": _parse_mca_date(appointment_date_raw),
            "cessation_date": _parse_mca_date(cessation_date_raw) if cessation_date_raw else None,
        })

    return directors


def _parse_mca_date(raw: str) -> str | None:
    """Parse MCA date string → ISO YYYY-MM-DD or None."""
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%d %b %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


async def write_directors_to_ikg(directors: list[dict[str, Any]]) -> int:
    """Write director records to IKG as Person nodes + DIRECTOR_OF edges."""
    from finagent.ikg.graph_client import get_graph_client

    client = get_graph_client()
    edges_written = 0

    for d in directors:
        din = d.get("din", "")
        cin = d.get("cin", "")
        name = d.get("name", "")
        if not din or not cin or not name:
            continue

        await client.upsert_vertex(
            f"person:{din}", "Person",
            {"din": din, "name": name, "designation": d.get("designation", "")},
        )
        await client.upsert_edge(
            f"person:{din}", f"company:{cin}", "DIRECTOR_OF",
            {
                "designation": d.get("designation", ""),
                "from_date": d.get("appointment_date"),
                "to_date": d.get("cessation_date"),
                "source_citation": "MCA21_director_data",
                "confidence_score": 1.0,
            },
        )
        edges_written += 1

    return edges_written


def store_directors_to_postgres(
    directors: list[dict[str, Any]],
    database_url: str | None = None,
) -> int:
    """Store director records in PostgreSQL directors_raw staging table."""
    db_url = get_database_url(database_url)
    if not db_url or not directors:
        return 0

    try:
        upserted = 0
        with connect_postgres(db_url, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                for d in directors:
                    cur.execute(
                        """
                        insert into directors_raw (
                          cin, din, name, designation, appointment_date, cessation_date, fetched_at
                        )
                        values (%s, %s, %s, %s, %s, %s, now())
                        on conflict (cin, din) do update set
                          name = excluded.name,
                          designation = excluded.designation,
                          appointment_date = excluded.appointment_date,
                          cessation_date = excluded.cessation_date,
                          fetched_at = now()
                        """,
                        (
                            d["cin"], d["din"], d["name"], d.get("designation"),
                            d.get("appointment_date"), d.get("cessation_date"),
                        ),
                    )
                    upserted += 1
            conn.commit()
        return upserted
    except Exception as exc:
        logger.error("Director store failed: %s", exc)
        return 0


async def run_mca_director_scraper_async(
    companies: list[dict[str, Any]],
    database_url: str | None = None,
    max_companies: int | None = None,
) -> dict[str, Any]:
    """Full director pipeline using Patchright browser session.

    One browser instance is kept alive across all companies.
    Rate-limited to 100 req/hour (36s/company).
    """
    if not _MCA_CAPTCHA_SCRAPER_ENABLED:
        return {
            "companies_processed": 0,
            "directors_found": 0,
            "directors_stored": 0,
            "errors": 0,
            "disabled": True,
            "method": "disabled_by_default",
            "reason": (
                "MCA director CAPTCHA scraping is disabled by default. "
                "Use NSE/BSE governance + annual report board sections + SEBI filings."
            ),
        }

    companies_subset = companies[:max_companies] if max_companies else companies
    companies_processed = 0
    directors_found = 0
    directors_stored = 0
    errors = 0

    session = MCABrowserSession()
    try:
        await session.start()

        for i, co in enumerate(companies_subset):
            cin = co.get("cin", "")
            if not cin:
                continue

            # Rotate proxy every N companies
            if i > 0 and i % _PROXY_ROTATE_EVERY == 0 and session._browser:
                logger.info("Rotating browser proxy at company %d", i)
                # Close and restart with a new proxy
                await session.close()
                session = MCABrowserSession()
                await session.start()

            try:
                directors = await session.fetch_directors_via_page(cin)
            except Exception as exc:
                logger.warning("Director fetch exception for CIN=%s: %s", cin, exc)
                directors = []
                errors += 1

            if directors:
                directors_found += len(directors)
                stored = store_directors_to_postgres(directors, database_url)
                directors_stored += stored
                try:
                    await write_directors_to_ikg(directors)
                except Exception as exc:
                    logger.warning("IKG director write failed for CIN=%s: %s", cin, exc)
                    errors += 1

            companies_processed += 1
            if companies_processed % 10 == 0:
                logger.info(
                    "Director scraper: %d/%d companies, %d directors found",
                    companies_processed, len(companies_subset), directors_found,
                )

            # Rate limit: 100 req/hour
            jitter = (0.5 - (companies_processed % 10) / 20) * 3
            await asyncio.sleep(_REQUEST_DELAY_S + jitter)

    finally:
        await session.close()

    return {
        "companies_processed": companies_processed,
        "directors_found": directors_found,
        "directors_stored": directors_stored,
        "errors": errors,
        "method": "patchright_browser",
    }


def run_mca_director_scraper(
    companies: list[dict[str, Any]],
    database_url: str | None = None,
    max_companies: int | None = None,
) -> dict[str, Any]:
    """Sync wrapper for the async Patchright-based director scraper."""
    return run_async(
        run_mca_director_scraper_async(
            companies=companies,
            database_url=database_url,
            max_companies=max_companies,
        )
    )


if __name__ == "__main__":
    if not _MCA_CAPTCHA_SCRAPER_ENABLED:
        print(
            "MCA CAPTCHA scraper is disabled. "
            "Set FINAGENT_ENABLE_MCA_DIRECTOR_CAPTCHA=1 only for explicit diagnostic runs."
        )
    else:
        # Quick test with Reliance Industries
        test_companies = [{"cin": "L17110MH1973PLC019786", "company_name": "Reliance Industries"}]
        result = run_mca_director_scraper(test_companies, max_companies=1)
        print(result)

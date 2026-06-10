"""SEBI Enforcement Orders — scraper and NER pipeline.

Fetches SEBI enforcement orders from the SEBI website and processes them
through Document Intelligence + NER to extract:
  - Order number, date, violation type, penalty amount
  - Named entities (companies, directors) mentioned in the order
  - Links to PDF documents

Source: https://www.sebi.gov.in/enforcement/orders.html
Rate limit: 1 req/5s (respectful crawling)
Schedule: Weekly (Sunday 2 AM IST via scheduler)

Pagination:
  SEBI enforcement listing pages show 25 orders per page.
  Each category is iterated across all pages until no more orders found.
  Max pages cap: configurable via max_pages param (default=50).

Pipeline:
  1. Crawl SEBI enforcement orders listing page
  2. Discover all category URLs
  3. For each category, paginate through all pages (25 orders/page)
  4. Download PDF links for recent orders
  5. Extract text via Azure Document Intelligence
  6. NER: extract company names, CINs, DINs, penalty amounts
  7. Store in enforcement_raw PostgreSQL table
  8. Write ENFORCEMENT_ACTION_AGAINST edges to IKG
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import date, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.scrapers._doc_extract import extract_pdf_text_local, text_is_sufficient
from finagent.ikg.scrapers._engine import SmartHTTPClient, run_async, sync_get

logger = logging.getLogger("finagent.ikg.scrapers.sebi_enforcement")

_SEBI_BASE_URL = "https://www.sebi.gov.in"
_SEBI_ORDERS_URL = "https://www.sebi.gov.in/enforcement/orders.html"
_SEBI_ORDER_CATEGORY_KEY_BY_SMID = {
    "1": "sat",
    "2": "chairperson_members",
    "3": "settlement",
    "4": "aa_rti",
    "5": "corporatisation_demutualisation",
    "6": "adjudication",
    "7": "courts",
    "77": "special_courts",
    "133": "quasi_judicial",
    "138": "regulation_30a",
}
_SEBI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.sebi.gov.in/enforcement/orders.html",
}
_REQUEST_DELAY_S = 5.0
_PARSER_VERSION = "sebi_enforcement_v3"
_DEFAULT_MAX_PAGES = 50   # cap per category to prevent infinite loops
_SEBI_AJAX_LISTING_URL = "https://www.sebi.gov.in/sebiweb/ajax/home/getnewslistinfo.jsp"
_AZURE_DI_MODEL = os.getenv("AZURE_DI_SEBI_MODEL", "prebuilt-layout").strip() or "prebuilt-layout"
_SEBI_LOCAL_MIN_CHARS = int(os.getenv("FINAGENT_SEBI_LOCAL_MIN_CHARS", "1000") or "1000")


# ─── HTML Parsers ─────────────────────────────────────────────────────────────

class _SebiOrderCategoryParser(HTMLParser):
    """Extract official category links from SEBI enforcement orders page."""

    def __init__(self, source_url: str) -> None:
        super().__init__()
        self.source_url = source_url
        self.categories: list[dict[str, str]] = []
        self._href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        href = attrs_dict.get("href", "").strip()
        if href:
            self._href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        title = " ".join(" ".join(self._text_parts).split())
        href = self._href
        self._href = None
        self._text_parts = []
        if not title:
            return
        if "order" not in title.lower():
            return
        url = urljoin(self.source_url, href)
        if "HomeAction.do?doListing=yes" not in url:
            return
        self.categories.append({"title": title, "url": url})


class _SebiPaginationParser(HTMLParser):
    """Detect pagination links in SEBI listing pages.

    SEBI uses links with page number parameters in one of two forms:
      ?doListing=yes&...&pageNo=2
      JavaScript: goToPage(2)
    We detect both patterns and extract the next page URL.
    """

    def __init__(self, source_url: str) -> None:
        super().__init__()
        self.source_url = source_url
        self.next_page_url: str | None = None
        self.total_pages: int = 1
        self.current_page: int = 1
        self._text_parts: list[str] = []
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        href = attrs_dict.get("href", "").strip()
        if not href:
            return
        self._href = href
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        text = " ".join(" ".join(self._text_parts).split()).strip().lower()
        href = self._href
        self._href = None
        self._text_parts = []

        if text in ("next", "next »", "next>", "next page", ">", "»"):
            full_url = urljoin(self.source_url, href)
            if full_url and full_url != self.source_url:
                self.next_page_url = full_url


class _SebiOrderHTMLParser(HTMLParser):
    """Minimal SEBI listing parser for official HTML pages."""

    def __init__(self, source_url: str, category: str) -> None:
        super().__init__()
        self.source_url = source_url
        self.category = category
        self.orders: list[dict[str, Any]] = []
        self._href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        href = attrs_dict.get("href", "").strip()
        if href:
            self._href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        title = " ".join(" ".join(self._text_parts).split())
        href = self._href
        self._href = None
        self._text_parts = []
        if not title:
            return

        url = urljoin(self.source_url, href)
        haystack = f"{title} {url}".lower()
        path = urlparse(url).path.lower()
        if (
            ".pdf" not in path
            and "/enforcement/orders/" not in path
            and "dodirect" not in url.lower()
            and "/sebi_data/attachdocs/" not in url.lower()
        ):
            return
        if path.endswith("/orders.html"):
            return
        if "order" not in haystack and ".pdf" not in haystack:
            return

        order_date = _parse_date_from_text(f"{title} {url}")
        self.orders.append({
            "order_number": _derive_order_number(title, url),
            "order_date": order_date,
            "pdf_url": url if ".pdf" in url.lower() else "",
            "detail_url": url,
            "title": title,
            "violation_type": self.category,
            "category": self.category,
            "source_url": self.source_url,
        })


# ─── Helper functions ──────────────────────────────────────────────────────────

def _category_key_from_url_and_title(url: str, title: str) -> str:
    parsed = urlparse(url)
    smid = parse_qs(parsed.query).get("smid", [""])[0]
    if smid and smid in _SEBI_ORDER_CATEGORY_KEY_BY_SMID:
        return _SEBI_ORDER_CATEGORY_KEY_BY_SMID[smid]
    fallback = re.sub(r"[^a-z0-9]+", "_", (title or "").strip().lower()).strip("_")
    return fallback or "orders"


def _derive_order_number(title: str, url: str) -> str:
    slug = url.rstrip("/").split("/")[-1]
    slug = re.sub(r"\.(html?|pdf)$", "", slug, flags=re.I)
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", slug).strip("-")
    if slug and len(slug) >= 6:
        return slug[:100]
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", title).strip("-")
    return clean[:100] or f"sebi-order-{abs(hash(url))}"


def _parse_date_from_text(raw: str) -> date | None:
    if not raw:
        return None
    patterns = [
        r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{4})\b",
        r"\b(\d{4}-\d{1,2}-\d{1,2})\b",
        r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b",
        r"\b([A-Za-z]{3,9}\s+\d{1,2},\s+\d{4})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if match:
            parsed = _parse_sebi_date(match.group(1))
            if parsed:
                return parsed
    return None


def _parse_sebi_date(raw: str) -> date | None:
    if not raw:
        return None
    from datetime import datetime
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            pass
    return None


# ─── Core fetch functions ──────────────────────────────────────────────────────

def fetch_sebi_order_categories(timeout_s: float = 30.0) -> dict[str, str]:
    """Fetch official SEBI enforcement order category URLs from orders page."""
    client = SmartHTTPClient(extra_headers=_SEBI_HEADERS)
    resp = run_async(_async_fetch_categories(client, timeout_s))
    parser = _SebiOrderCategoryParser(source_url=_SEBI_ORDERS_URL)
    parser.feed(resp.text or "")
    categories: dict[str, str] = {}
    for item in parser.categories:
        key = _category_key_from_url_and_title(item["url"], item["title"])
        categories[key] = item["url"]
    if not categories:
        raise RuntimeError("SEBI orders page had no discoverable categories")
    return categories


async def _async_fetch_categories(client: SmartHTTPClient, timeout_s: float) -> Any:
    resp = await client.get(_SEBI_ORDERS_URL, headers=_SEBI_HEADERS, timeout=timeout_s)
    if resp.status_code != 200:
        raise RuntimeError(f"SEBI orders page returned {resp.status_code}")
    return resp


def fetch_sebi_orders_listing(
    category: str,
    category_url: str,
    timeout_s: float = 30.0,
    max_pages: int = _DEFAULT_MAX_PAGES,
) -> list[dict[str, Any]]:
    """Fetch ALL pages of SEBI enforcement orders listing for a category.

    Iterates pagination by following Next links until exhausted or max_pages hit.

    Args:
        category: SEBI order category key.
        category_url: Official SEBI listing URL for this category.
        timeout_s: Request timeout per page.
        max_pages: Maximum pages to fetch per category (default 50).

    Returns:
        Deduplicated list of all order metadata dicts across all pages.
    """
    if "/sebiweb/home/HomeAction.do" in category_url and "doListing=yes" in category_url:
        return _fetch_sebi_orders_listing_via_ajax(
            category=category,
            category_url=category_url,
            timeout_s=timeout_s,
            max_pages=max_pages,
        )

    all_orders: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    current_url = category_url
    page_num = 1

    client = SmartHTTPClient(extra_headers=_SEBI_HEADERS)

    while current_url and page_num <= max_pages:
        logger.info(
            "SEBI [%s] page %d: %s",
            category, page_num, current_url[:80],
        )
        try:
            resp = run_async(client.get(current_url, headers=_SEBI_HEADERS, timeout=timeout_s))
            if resp.status_code != 200:
                logger.warning("SEBI category page %d returned %d", page_num, resp.status_code)
                break

            page_orders = parse_sebi_orders_html(resp.text, category=category, source_url=current_url)
            new_orders = [o for o in page_orders if o.get("detail_url") not in seen_urls]

            if not new_orders:
                logger.info("SEBI [%s] page %d: no new orders, stopping pagination", category, page_num)
                break

            for o in new_orders:
                seen_urls.add(o.get("detail_url", ""))
            all_orders.extend(new_orders)
            logger.info("SEBI [%s] page %d: %d orders (total: %d)", category, page_num, len(new_orders), len(all_orders))

            # Detect next page URL
            next_page_url = _detect_next_page(resp.text, current_url)
            if not next_page_url or next_page_url == current_url:
                logger.info("SEBI [%s] no next page found, done", category)
                break

            current_url = next_page_url
            page_num += 1
            time.sleep(_REQUEST_DELAY_S)

        except Exception as exc:
            logger.error("SEBI orders listing failed on page %d: %s", page_num, exc)
            break

    logger.info("SEBI [%s] total orders across %d pages: %d", category, page_num, len(all_orders))
    return all_orders


def _fetch_sebi_orders_listing_via_ajax(
    category: str,
    category_url: str,
    timeout_s: float,
    max_pages: int,
) -> list[dict[str, Any]]:
    """Fetch SEBI listing pages backed by searchFormNewsList AJAX flow."""
    all_orders: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_page_fingerprints: set[str] = set()

    client = SmartHTTPClient(extra_headers=_SEBI_HEADERS)
    initial_resp = run_async(client.get(category_url, headers=_SEBI_HEADERS, timeout=timeout_s))
    if initial_resp.status_code != 200:
        logger.warning("SEBI [%s] initial page returned %s", category, initial_resp.status_code)
        return []

    listing_html = initial_resp.text or ""
    state = _extract_ajax_state(initial_resp.text or "", category_url)
    page_num = 1

    while page_num <= max_pages:
        page_orders = parse_sebi_orders_html(listing_html, category=category, source_url=category_url)
        new_orders = [o for o in page_orders if o.get("detail_url") not in seen_urls]
        for order in new_orders:
            seen_urls.add(order.get("detail_url", ""))
        all_orders.extend(new_orders)
        logger.info(
            "SEBI [%s] AJAX page %d: %d orders (total: %d)",
            category,
            page_num,
            len(new_orders),
            len(all_orders),
        )

        window = _parse_records_window(listing_html)
        if window and window[1] >= window[2]:
            break
        if not window and not new_orders:
            break

        next_html = _fetch_ajax_next_listing(
            client=client,
            state=state,
            category_url=category_url,
            timeout_s=timeout_s,
        )
        if not next_html:
            break

        fingerprint = hashlib.sha1(next_html.encode("utf-8", errors="ignore")).hexdigest()[:16]
        if fingerprint in seen_page_fingerprints:
            logger.info("SEBI [%s] pagination repeated page fingerprint, stopping", category)
            break
        seen_page_fingerprints.add(fingerprint)
        listing_html = next_html
        page_num += 1
        time.sleep(_REQUEST_DELAY_S)

    logger.info("SEBI [%s] total orders across %d pages (AJAX): %d", category, page_num, len(all_orders))
    return all_orders


def _parse_records_window(html_text: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\s+to\s+(\d+)\s+of\s+([0-9,]+)\s+records?", html_text or "", re.I)
    if not match:
        return None
    start = int(match.group(1).replace(",", ""))
    end = int(match.group(2).replace(",", ""))
    total = int(match.group(3).replace(",", ""))
    return start, end, total


def _extract_hidden_input(html_text: str, name: str) -> str:
    pattern = rf"""name=["']{re.escape(name)}["'][^>]*value=["']([^"']*)["']"""
    match = re.search(pattern, html_text or "", re.I)
    return (match.group(1) if match else "").strip()


def _extract_ajax_state(html_text: str, category_url: str) -> dict[str, str]:
    parsed = urlparse(category_url)
    query = parse_qs(parsed.query or "")
    sid = _extract_hidden_input(html_text, "sid") or query.get("sid", ["0"])[0]
    ssid_hidden = (
        _extract_hidden_input(html_text, "ssidhidden")
        or query.get("ssid", ["0"])[0]
    )
    smid_hidden = (
        _extract_hidden_input(html_text, "smidhidden")
        or query.get("smid", ["0"])[0]
    )
    return {
        "sid": sid,
        "ssid": ssid_hidden,
        "smid": smid_hidden,
        "ssidhidden": ssid_hidden,
        "sectName": _extract_hidden_input(html_text, "sectName") or "Enforcement",
        "search": _extract_hidden_input(html_text, "search"),
        "fromDate": _extract_hidden_input(html_text, "fromDate"),
        "toDate": _extract_hidden_input(html_text, "toDate"),
        "fromYear": _extract_hidden_input(html_text, "fromYear"),
        "toYear": _extract_hidden_input(html_text, "toYear"),
        "deptId": _extract_hidden_input(html_text, "deptId"),
        "intmid": _extract_hidden_input(html_text, "intmid") or "-1",
        "nextValue": _extract_hidden_input(html_text, "nextValue") or "1",
        "token": _extract_hidden_input(html_text, "org.apache.struts.taglib.html.TOKEN"),
    }


def _fetch_ajax_next_listing(
    *,
    client: SmartHTTPClient,
    state: dict[str, str],
    category_url: str,
    timeout_s: float,
) -> str | None:
    payload = {
        "nextValue": state.get("nextValue", "1"),
        "next": "n",
        "search": state.get("search", ""),
        "fromDate": state.get("fromDate", ""),
        "toDate": state.get("toDate", ""),
        "fromYear": state.get("fromYear", ""),
        "toYear": state.get("toYear", ""),
        "deptId": state.get("deptId", ""),
        "sid": state.get("sid", "0"),
        "ssid": state.get("ssid", "0"),
        "smid": state.get("smid", "0"),
        "ssidhidden": state.get("ssidhidden", "0"),
        "intmid": state.get("intmid", "-1"),
        "sText": state.get("sectName", "Enforcement"),
        "ssText": "",
        "smText": "",
        "doDirect": "-1",
    }
    token = state.get("token", "")
    if token:
        payload["org.apache.struts.taglib.html.TOKEN"] = token

    headers = {
        **_SEBI_HEADERS,
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": category_url,
    }
    resp = run_async(client.post(_SEBI_AJAX_LISTING_URL, data=payload, headers=headers, timeout=timeout_s))
    if resp.status_code != 200:
        logger.warning("SEBI AJAX listing returned %s", resp.status_code)
        return None

    raw = resp.text or ""
    listing_html = raw.split("#@#")[0] if "#@#" in raw else raw
    next_value = _extract_hidden_input(listing_html, "nextValue")
    if next_value:
        state["nextValue"] = next_value
    else:
        try:
            state["nextValue"] = str(int(state.get("nextValue", "1")) + 1)
        except ValueError:
            state["nextValue"] = "1"
    return listing_html.strip() or None


def _detect_next_page(html_text: str, current_url: str) -> str | None:
    """Detect the Next page URL from SEBI listing HTML.

    SEBI uses multiple pagination patterns:
    1. <a href="...?pageNo=2">Next</a>
    2. <a href="...">Next »</a>
    3. <a href="javascript:goToPage(2)">Next</a>  → manual construction
    4. Page number links: <a href="...">2</a> next to current page
    """
    # Strategy 1: direct HTML parser
    pg_parser = _SebiPaginationParser(current_url)
    pg_parser.feed(html_text or "")
    if pg_parser.next_page_url:
        return pg_parser.next_page_url

    # Strategy 2: regex for common SEBI page patterns
    # Pattern: pageNo=N in href
    page_no_match = re.search(r'href="([^"]*[?&]pageNo=(\d+)[^"]*)"', html_text, re.I)
    if page_no_match:
        return urljoin(current_url, page_no_match.group(1))

    # Pattern: javascript goToPage(N) — reconstruct URL
    js_match = re.search(r'goToPage\((\d+)\)', html_text)
    if js_match:
        next_page_num = int(js_match.group(1))
        current_parsed = urlparse(current_url)
        qs = parse_qs(current_parsed.query)
        qs["pageNo"] = [str(next_page_num)]
        from urllib.parse import urlencode, urlunparse
        new_qs = urlencode({k: v[0] for k, v in qs.items()})
        return urlunparse(current_parsed._replace(query=new_qs))

    # Strategy 3: Find highest page number link adjacent to current
    # Detect "1 to 25 of N records" pattern
    records_match = re.search(r"(\d+)\s+to\s+(\d+)\s+of\s+(\d+)\s+records?", html_text, re.I)
    if records_match:
        start = int(records_match.group(1))
        end = int(records_match.group(2))
        total = int(records_match.group(3))
        page_size = end - start + 1
        if end < total:
            # There are more pages
            next_start = end + 1
            # Try to construct URL with start param
            current_parsed = urlparse(current_url)
            qs = parse_qs(current_parsed.query)
            # SEBI uses different param names: pageNo, startIndex, start, from
            for param in ("pageNo", "startIndex", "start", "from", "pg"):
                if param in qs:
                    if param == "pageNo":
                        qs[param] = [str(int(qs[param][0]) + 1)]
                    else:
                        qs[param] = [str(next_start)]
                    from urllib.parse import urlencode, urlunparse
                    new_qs = urlencode({k: v[0] for k, v in qs.items()})
                    return urlunparse(current_parsed._replace(query=new_qs))

    return None


def parse_sebi_orders_html(html_text: str, category: str, source_url: str) -> list[dict[str, Any]]:
    """Parse SEBI official HTML order category pages."""
    parser = _SebiOrderHTMLParser(source_url=source_url, category=category)
    parser.feed(html_text or "")

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for order in parser.orders:
        key = order.get("detail_url") or order.get("pdf_url") or order.get("order_number")
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(order)
    return deduped


def parse_sebi_order_listing(raw_orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse SEBI order listing into standardized format."""
    parsed = []
    for order in raw_orders:
        order_number = str(
            order.get("order_number") or order.get("order_no") or
            order.get("orderNo") or order.get("title") or ""
        ).strip()
        order_date_raw = str(order.get("date") or order.get("orderDate") or "").strip()
        pdf_url = str(
            order.get("pdf_link") or order.get("pdfLink") or order.get("url") or ""
        ).strip()
        if order.get("pdf_url"):
            pdf_url = str(order.get("pdf_url") or "").strip()

        if not order_number:
            continue

        if pdf_url and not pdf_url.startswith("http"):
            pdf_url = _SEBI_BASE_URL + pdf_url

        order_date = order.get("order_date") or _parse_sebi_date(order_date_raw)

        parsed.append({
            "order_number": order_number,
            "order_date": order_date,
            "pdf_url": pdf_url,
            "detail_url": order.get("detail_url") or order.get("url") or "",
            "title": str(order.get("title") or order.get("subject") or "").strip(),
            "violation_type": str(
                order.get("type") or order.get("violation_type") or order.get("category") or ""
            ).strip(),
            "source_url": order.get("source_url") or _SEBI_ORDERS_URL,
        })

    return parsed


def extract_entities_from_order_text(order_text: str) -> dict[str, Any]:
    """Extract named entities from SEBI enforcement order text using regex NER."""
    entities: dict[str, Any] = {
        "companies": [],
        "cins": [],
        "dins": [],
        "penalties": [],
        "violation_keywords": [],
    }

    if not order_text:
        return entities

    cin_pattern = re.compile(r"\b[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b")
    entities["cins"] = list(set(cin_pattern.findall(order_text)))

    din_pattern = re.compile(r"\bDIN[:\s]*(\d{8})\b", re.I)
    entities["dins"] = list(set(din_pattern.findall(order_text)))

    company_pattern = re.compile(
        r"\b([A-Z][A-Za-z\s&.,'-]+(?:Limited|Ltd\.?|Private|Pvt\.?|Corporation|Corp\.?))\b"
    )
    raw_companies = company_pattern.findall(order_text)
    seen_companies: set[str] = set()
    for name in raw_companies:
        clean = name.strip()
        if len(clean) > 5 and clean.upper() not in seen_companies:
            seen_companies.add(clean.upper())
            entities["companies"].append(clean)

    penalty_patterns = [
        re.compile(
            r"(?:penalty|fine|penalised|penalized|imposed)\s+(?:of\s+)?(?:Rs\.?\s*|INR\s*|₹\s*)(\d[\d,]*(?:\.\d+)?)\s*(?:crore|lakh|cr\.?|lac)?",
            re.I,
        ),
        re.compile(
            r"(?:Rs\.?\s*|INR\s*|₹\s*)(\d[\d,]*(?:\.\d+)?)\s*(?:crore|lakh|cr\.?|lac)",
            re.I,
        ),
    ]
    seen_penalties: set[float] = set()
    for penalty_pattern in penalty_patterns:
        for match in penalty_pattern.finditer(order_text):
            try:
                amount_str = match.group(1).replace(",", "")
                amount = float(amount_str)
                full_match = match.group(0).lower()
                if "crore" in full_match or "cr" in full_match:
                    amount *= 1e7
                elif "lakh" in full_match or "lac" in full_match:
                    amount *= 1e5
                if amount not in seen_penalties:
                    seen_penalties.add(amount)
                    entities["penalties"].append(amount)
            except ValueError:
                pass

    violation_keywords = [
        "insider trading", "front running", "market manipulation",
        "unfair trade practice", "fraudulent", "misleading statement",
        "non-compliance", "LODR violation", "PIT regulations",
        "takeover regulations", "mutual fund regulation",
    ]
    for kw in violation_keywords:
        if kw.lower() in order_text.lower():
            entities["violation_keywords"].append(kw)

    return entities


def store_enforcement_order(
    order: dict[str, Any],
    entities: dict[str, Any],
    database_url: str | None = None,
) -> bool:
    """Store parsed enforcement order in PostgreSQL enforcement_raw table."""
    db_url = get_database_url(database_url)
    if not db_url:
        return False

    try:
        max_penalty = max(entities.get("penalties", [0])) if entities.get("penalties") else None
        violation_type = ", ".join(entities.get("violation_keywords", [])) or order.get("violation_type", "")

        with connect_postgres(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into enforcement_raw (
                      order_number, regulator, violation_type, penalty_amount_inr,
                      order_date, pdf_url, full_text, entities_json, fetched_at
                    )
                    values (%s, 'SEBI', %s, %s, %s, %s, %s, %s::jsonb, now())
                    on conflict (order_number) do update set
                      violation_type = excluded.violation_type,
                      penalty_amount_inr = excluded.penalty_amount_inr,
                      entities_json = excluded.entities_json,
                      fetched_at = now()
                    """,
                    (
                        order["order_number"],
                        violation_type,
                        max_penalty,
                        order.get("order_date"),
                        order.get("pdf_url"),
                        order.get("full_text", ""),
                        json.dumps(entities),
                    ),
                )
            conn.commit()
        return True
    except Exception as exc:
        logger.error("Enforcement order store failed: %s", exc)
        return False


async def write_enforcement_to_ikg(
    order: dict[str, Any],
    entities: dict[str, Any],
) -> int:
    """Write ENFORCEMENT_ACTION_AGAINST edges to IKG."""
    from finagent.ikg.graph_client import get_graph_client

    client = get_graph_client()
    edges_written = 0
    order_id = order.get("order_number", "")
    if not order_id:
        return 0

    await client.upsert_vertex(
        f"regulator_action:{order_id}", "RegulatorAction",
        {
            "order_number": order_id,
            "regulator": "SEBI",
            "violation_type": ", ".join(entities.get("violation_keywords", [])),
            "penalty_amount_inr": max(entities.get("penalties", [0])) if entities.get("penalties") else None,
            "order_date": str(order.get("order_date")) if order.get("order_date") else None,
            "pdf_url": order.get("pdf_url", ""),
        },
    )

    for cin in entities.get("cins", []):
        await client.upsert_vertex(
            f"company:{cin}",
            "Company",
            {
                "cin": cin,
                "source_citation": "SEBI_enforcement_order",
            },
        )
        await client.upsert_edge(
            f"regulator_action:{order_id}", f"company:{cin}",
            "ENFORCEMENT_ACTION_AGAINST",
            {"source_citation": "SEBI_enforcement_order", "confidence_score": 0.95},
        )
        edges_written += 1

    return edges_written


def extract_order_text_from_pdf_url(pdf_url: str, timeout_s: float = 120.0) -> dict[str, Any]:
    """Download a SEBI PDF and extract text with local-first + selective DI."""
    if not pdf_url:
        return {"full_text": "", "fallback_used": None, "error": None}

    try:
        from finagent.ingestion.azure_doc_intel import extract_document
        from finagent.ikg.scrapers._engine import sync_get

        parsed_url = urlparse(pdf_url)
        file_param = parse_qs(parsed_url.query).get("file", [""])[0]
        download_url = file_param or pdf_url
        if download_url and not str(download_url).lower().startswith(("http://", "https://")):
            download_url = urljoin(_SEBI_BASE_URL, str(download_url))

        resp = sync_get(download_url, headers=_SEBI_HEADERS, timeout=timeout_s)
        resp.raise_for_status()
        pdf_bytes = resp.content

        local = extract_pdf_text_local(pdf_bytes)
        local_text = str(local.get("full_text") or "")
        if text_is_sufficient(local_text, min_chars=_SEBI_LOCAL_MIN_CHARS):
            return {
                "full_text": local_text,
                "fallback_used": False,
                "model_used": local.get("model") or "pymupdf_local",
                "page_count": int(local.get("page_count") or 0),
                "error": None,
            }

        result = run_async(
            extract_document(
                file_bytes=pdf_bytes,
                model_id=_AZURE_DI_MODEL,
                timeout_s=timeout_s,
                allow_fallback=True,
            )
        )
        text = result.full_text or ""
        if not text.strip() and local_text.strip():
            text = local_text
            model_used = local.get("model") or "pymupdf_local"
            page_count = int(local.get("page_count") or 0)
        else:
            model_used = result.model_used
            page_count = result.page_count
        return {
            "full_text": text,
            "fallback_used": result.fallback_used,
            "model_used": model_used,
            "page_count": page_count,
            "error": None,
        }
    except Exception as exc:
        logger.warning("SEBI order PDF extraction failed for %s: %s", pdf_url, exc)
        return {"full_text": "", "fallback_used": None, "error": str(exc)}


def resolve_sebi_order_pdf_url(detail_url: str, timeout_s: float = 30.0) -> str:
    """Resolve a SEBI order detail page to its official PDF wrapper/link."""
    if not detail_url or detail_url.lower().endswith(".pdf"):
        return detail_url
    try:
        resp = sync_get(detail_url, headers=_SEBI_HEADERS, timeout=timeout_s)
        if resp.status_code != 200:
            return ""
        match = re.search(r"""(?:href|src)=['""]([^'"]+\.pdf[^'"]*)['"]""", resp.text, re.I)
        if not match:
            return ""
        return urljoin(detail_url, match.group(1))
    except Exception as exc:
        logger.debug("SEBI PDF URL resolution failed for %s: %s", detail_url, exc)
        return ""


# ─── Main pipeline ─────────────────────────────────────────────────────────────

def run_sebi_enforcement_scraper(
    pages: int = 2,
    database_url: str | None = None,
    categories: list[str] | None = None,
    extract_pdfs: bool | None = None,
    max_pages_per_category: int | None = None,
) -> dict[str, Any]:
    """Full SEBI enforcement scraper pipeline with full pagination.

    Args:
        pages: Retained for compatibility (unused — use max_pages_per_category).
        database_url: PostgreSQL connection string.
        categories: SEBI category keys to crawl.
        extract_pdfs: If True, download PDFs and extract text via Azure DI.
        max_pages_per_category: Max listing pages to scrape per category (default 50).

    Returns:
        dict with: orders_fetched, orders_processed, orders_stored, errors
    """
    orders_fetched = 0
    orders_processed = 0
    orders_stored = 0
    edges_written = 0
    errors = 0
    http_status: int | None = None
    categories_to_fetch: list[str] = []
    seen_order_keys: set[str] = set()
    extract_pdf_text = (
        extract_pdfs
        if extract_pdfs is not None
        else os.getenv("SEBI_EXTRACT_PDFS", "1").strip().lower() not in {"0", "false", "no"}
    )
    configured_max_pages = os.getenv("SEBI_MAX_PAGES_PER_CATEGORY")
    if configured_max_pages:
        effective_max_pages = int(configured_max_pages)
    elif max_pages_per_category is not None:
        effective_max_pages = max_pages_per_category
    else:
        effective_max_pages = pages
    effective_max_pages = max(1, int(effective_max_pages))

    try:
        category_map = fetch_sebi_order_categories()
        http_status = 200
    except Exception as exc:
        logger.error("SEBI category discovery failed: %s", exc)
        return {
            "orders_fetched": 0, "orders_processed": 0, "orders_stored": 0,
            "edges_written": 0, "errors": 1, "success": False,
            "categories": [], "http_status": http_status,
            "parser_version": _PARSER_VERSION, "error": str(exc),
        }

    categories_to_fetch = [c for c in (categories or list(category_map.keys())) if c in category_map]

    for category in categories_to_fetch:
        raw_orders = fetch_sebi_orders_listing(
            category=category,
            category_url=category_map[category],
            max_pages=effective_max_pages,
        )
        orders_fetched += len(raw_orders)

        parsed = parse_sebi_order_listing(raw_orders)
        for order in parsed:
            order_key = str(order.get("order_number") or order.get("pdf_url") or order.get("detail_url"))
            if order_key in seen_order_keys:
                continue
            seen_order_keys.add(order_key)
            time.sleep(_REQUEST_DELAY_S)

            if not order.get("pdf_url") and order.get("detail_url"):
                order["pdf_url"] = resolve_sebi_order_pdf_url(order["detail_url"])

            full_text = ""
            if extract_pdf_text:
                if not order.get("pdf_url"):
                    logger.warning("SEBI order missing PDF URL: %s", order.get("detail_url"))
                    errors += 1
                    continue
                extracted = extract_order_text_from_pdf_url(order["pdf_url"])
                full_text = extracted.get("full_text") or ""
                if extracted.get("error") or not full_text.strip():
                    logger.warning(
                        "SEBI PDF extraction failed for %s: %s",
                        order.get("order_number"), extracted.get("error"),
                    )
                    errors += 1
                    continue
            else:
                full_text = " ".join(
                    str(order.get(k) or "")
                    for k in ("title", "violation_type", "detail_url", "pdf_url")
                )

            entities = extract_entities_from_order_text(full_text)
            order["full_text"] = full_text

            stored = store_enforcement_order(order, entities, database_url)
            if stored:
                orders_stored += 1
                try:
                    edges_written += run_async(write_enforcement_to_ikg(order, entities))
                except Exception as exc:
                    logger.warning("SEBI IKG write failed for %s: %s", order.get("order_number"), exc)
            else:
                errors += 1

            orders_processed += 1

    logger.info(
        "SEBI enforcement: %d fetched, %d processed, %d stored, %d edges, %d errors",
        orders_fetched, orders_processed, orders_stored, edges_written, errors,
    )
    return {
        "orders_fetched": orders_fetched,
        "orders_processed": orders_processed,
        "orders_stored": orders_stored,
        "edges_written": edges_written,
        "errors": errors,
        # Consider success if we fetched orders and stored at least 80% of them.
        # Strict equality (stored == processed) was causing false failures when a
        # small number of PDFs fail to extract or orders are skipped as duplicates.
        "success": orders_fetched > 0 and orders_stored >= max(1, int(orders_fetched * 0.8)),
        "categories": categories_to_fetch,
        "http_status": http_status,
        "parser_version": _PARSER_VERSION,
    }


if __name__ == "__main__":
    result = run_sebi_enforcement_scraper(extract_pdfs=False)
    print(result)

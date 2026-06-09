"""BSE Shareholding Pattern (SHP) — quarterly scraper.

Downloads promoter holding % and pledge % for Nifty 500 companies
from the BSE corporate filings API.

Source: https://api.bseindia.com/BseIndiaAPI/api/ShareHoldingPattern/...
        BSE shareholding XML/JSON endpoint
Rate limit: 2 req/s (BSE is more lenient than NSE)
Data: BSE's live endpoints expose the available quarter ids per company. The
backfill depth is configurable so governance runs can collect 10-year history
where the source still exposes it.

Schedule: Quarterly, after quarterly results season (Jan, Apr, Jul, Oct).

Pipeline:
  1. For each Nifty 500 company (by BSE scrip code):
     - Download SHP data for all available quarters
     - Parse: promoter names, holding %, pledge %
     - Store in PostgreSQL staging table shp_raw
     - Write OWNS_STAKE_IN and PLEDGED_TO edges to IKG
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx

from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.scrapers._engine import SmartHTTPClient, run_async, sync_get

logger = logging.getLogger("finagent.ikg.scrapers.bse_shp")

_BSE_SHP_DECLARATION_URL = "https://api.bseindia.com/BseIndiaAPI/api/shpDecleraction/w?scripcode={scrip_code}"
_BSE_SHP_QTRINFO_URL = "https://api.bseindia.com/BseIndiaAPI/api/Corp_shpSec_shpqtrinfo_ng/w"
_BSE_SHP_SUMMARY_URL = "https://api.bseindia.com/BseIndiaAPI/api/Corp_shpSec_SHPSUMMARY_ng/w"
_BSE_SHP_PROMOTER_URL = "https://api.bseindia.com/BseIndiaAPI/api/Corp_shpPromoterNGroup_ng/w"
_BSE_SHP_PUBLIC_URL = "https://api.bseindia.com/BseIndiaAPI/api/Corp_shpSec_SHPPubShold_ng/w"
_BSE_SHP_FOREIGN_URL = "https://api.bseindia.com/BseIndiaAPI/api/Corp_shpforeignownership_ng/w"
_BSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}
_REQUEST_DELAY_S = 0.6  # BSE rate limit: ~2 req/s
_PARSER_VERSION = "bse_shp_v2"
_DEFAULT_MAX_WORKERS = 4
_DEFAULT_DISCOVERY_TIMEOUT_S = float(os.getenv("FINAGENT_BSE_SHP_DISCOVERY_TIMEOUT_S", "45") or "45")
_DEFAULT_REQUEST_TIMEOUT_S = float(os.getenv("FINAGENT_BSE_SHP_REQUEST_TIMEOUT_S", "20") or "20")


class _BseFilingLinkParser(HTMLParser):
    def __init__(self, source_url: str) -> None:
        super().__init__()
        self.source_url = source_url
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_dict = {k.lower(): v or "" for k, v in attrs}
        href = attrs_dict.get("href", "").strip()
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        title = " ".join(" ".join(self._text).split()) or self._href.rsplit("/", 1)[-1]
        url = urljoin(self.source_url, self._href)
        haystack = f"{title} {url}".lower()
        if any(token in haystack for token in ("sharehold", "xbrl", ".xml", ".zip", ".pdf")):
            self.links.append({"title": title, "url": url})
        self._href = None
        self._text = []


def _get_quarters(n: int = 8) -> list[str]:
    """Generate last N quarter labels in BSE format: YYYYMM.

    BSE uses YYYYMM where MM is the last month of the quarter:
      Q1 (Apr-Jun) → 06, Q2 (Jul-Sep) → 09,
      Q3 (Oct-Dec) → 12, Q4 (Jan-Mar) → 03
    """
    from datetime import date

    today = date.today()
    quarters = []
    month = today.month
    year = today.year

    # Find current quarter end month
    quarter_ends = [3, 6, 9, 12]
    for q_end in quarter_ends:
        if month <= q_end:
            current_q_end = q_end
            current_q_year = year
            break
    else:
        current_q_end = 3
        current_q_year = year + 1

    for _ in range(n):
        quarters.append(f"{current_q_year}{current_q_end:02d}")
        current_q_end -= 3
        if current_q_end <= 0:
            current_q_end = 12
            current_q_year -= 1

    return quarters


def _as_int_qtrid(value: Any) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _fetch_json(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, str] | None = None,
    retries: int = 2,
    allow_list: bool = False,
) -> dict[str, Any] | list[Any]:
    last_error: Exception | None = None
    for attempt in range(max(1, retries + 1)):
        try:
            resp = client.get(url, params=params, headers=_BSE_HEADERS)
            resp.raise_for_status()
            payload = resp.json()
            if allow_list and isinstance(payload, list):
                return payload
            if not isinstance(payload, dict):
                raise RuntimeError(f"Unexpected BSE SHP payload type: {type(payload).__name__}")
            return payload
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError, ValueError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(_REQUEST_DELAY_S * (attempt + 1))
    raise last_error or RuntimeError(f"BSE SHP request failed for {url}")


def _discover_qtrids(
    client: httpx.Client,
    scrip_code: str,
    limit: int,
) -> list[int]:
    declaration_resp = _fetch_json(
        client,
        _BSE_SHP_DECLARATION_URL.format(scrip_code=scrip_code),
        retries=3,
        allow_list=True,
    )
    declaration = declaration_resp if isinstance(declaration_resp, list) else declaration_resp.get("Table") or declaration_resp.get("data") or []
    if not isinstance(declaration, list) or not declaration:
        raise RuntimeError(f"BSE SHP declaration returned no data for scrip={scrip_code}")
    latest_qtrid = _as_int_qtrid((declaration[0] or {}).get("qtr_id"))
    if latest_qtrid is None:
        raise RuntimeError(f"BSE SHP declaration missing qtr_id for scrip={scrip_code}")

    discovered: list[int] = []
    misses = 0
    probe = latest_qtrid
    while len(discovered) < max(1, limit) and probe > 0 and misses < max(5, limit * 2):
        try:
            info = _fetch_json(
                client,
                _BSE_SHP_QTRINFO_URL,
                params={"SCRIPCODE": scrip_code, "QtrCode": str(probe)},
            )
            table = info.get("table1")
            if isinstance(table, list) and table:
                discovered.append(probe)
                misses = 0
            else:
                misses += 1
        except Exception:
            misses += 1
        probe -= 1
    return discovered


def _extract_summary_metrics(summary_payload: dict[str, Any]) -> dict[str, float]:
    promoter = 0.0
    public = 0.0
    pledge = 0.0
    for row in summary_payload.get("Table1") or []:
        if not isinstance(row, dict):
            continue
        category = str(row.get("Fld_ShortCatg") or row.get("FLD_CATEGORY") or "").lower()
        pct = _as_float(row.get("Fld_TotalPercentageOf_A_B_C2") or row.get("Fld_TotalVotingRightsPercent"))
        encumbered = _as_float(row.get("Fld_TotalencumberedPercentage") or row.get("Fld_PledgeEncumberedPercentage"))
        if "promoter and promoter group" in category:
            promoter = max(promoter, pct)
            pledge = max(pledge, encumbered)
        elif category.strip() == "public shareholder":
            public = max(public, pct)
    return {
        "promoter_pct": round(promoter, 2),
        "public_pct": round(public, 2),
        "pledge_pct": round(pledge, 2),
    }


def _extract_fii_dii(public_payload: dict[str, Any]) -> tuple[float, float]:
    fii = 0.0
    dii = 0.0
    for row in public_payload.get("Table1") or []:
        if not isinstance(row, dict):
            continue
        if row.get("Fld_ShareHolderName"):
            continue
        subcat = str(row.get("Fld_SubCategory") or "").lower()
        pct = _as_float(row.get("Fld_TotalPercentageOf_A_B_C2"))
        if pct <= 0:
            continue
        if "foreign" in subcat or "fii" in subcat or "fpi" in subcat:
            fii = max(fii, pct)
        if "domestic" in subcat or "mutual" in subcat or "insurance" in subcat or "dii" in subcat:
            dii = max(dii, pct)
    return round(fii, 2), round(dii, 2)


def _extract_promoter_groups(promoter_payload: dict[str, Any]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in promoter_payload.get("Table1") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Fld_ShareHolderName") or "").strip()
        pct = _as_float(row.get("Fld_TotalPercentageOf_A_B_C2"))
        if not name or pct <= 0:
            continue
        key = name.upper()
        if key in seen:
            continue
        seen.add(key)
        groups.append({
            "name": name,
            "category": str(row.get("Fld_SubCategory") or row.get("Fld_ShortCatg") or "Promoter"),
            "holding_pct": round(pct, 2),
            "pledge_pct_of_holding": round(_as_float(row.get("Fld_TotalencumberedPercentage")), 2),
        })
    return groups


def fetch_bse_shp(scrip_code: str, quarter: str | int, timeout_s: float = 15.0) -> dict[str, Any] | None:
    """Fetch BSE shareholding pattern for one scrip and quarter ID.

    Args:
        scrip_code: BSE scrip code (e.g., "500325" for Reliance).
        quarter: BSE quarter ID (`qtrid`), not YYYYMM.
        timeout_s: Request timeout.

    Returns:
        Parsed SHP data dict, or None if not available.
    """
    qtrid = _as_int_qtrid(quarter)
    if qtrid is None:
        return None
    try:
        timeout = httpx.Timeout(timeout_s, connect=min(10.0, timeout_s))
        with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
            qtr_params = {"SCRIPCODE": scrip_code, "QtrCode": str(qtrid)}
            qtrinfo = _fetch_json(client, _BSE_SHP_QTRINFO_URL, params=qtr_params)
            summary = _fetch_json(client, _BSE_SHP_SUMMARY_URL, params=qtr_params)
            promoter = _fetch_json(client, _BSE_SHP_PROMOTER_URL, params=qtr_params)
            public = _fetch_json(client, _BSE_SHP_PUBLIC_URL, params=qtr_params)
            foreign = _fetch_json(
                client,
                _BSE_SHP_FOREIGN_URL,
                params={"scripcode": scrip_code, "qtrid": str(qtrid)},
            )

        qtr_info_row = (
            (qtrinfo.get("table1") or [None])[0]
            if isinstance(qtrinfo.get("table1"), list)
            else None
        ) or {}

        summary_metrics = _extract_summary_metrics(summary)
        fii_pct, dii_pct = _extract_fii_dii(public)
        promoter_groups = _extract_promoter_groups(promoter)
        if not fii_pct and isinstance(foreign.get("Table1"), list):
            for row in foreign.get("Table1") or []:
                if not isinstance(row, dict):
                    continue
                label = str(row.get("Fld_AnnBLabelName") or "").lower()
                if "limit utilized" in label:
                    fii_pct = max(fii_pct, _as_float(row.get("Fld_Limitsutilized")))

        return {
            "scrip_code": scrip_code,
            "quarter": str(qtrid),
            "quarter_name": str(qtr_info_row.get("fld_quartername") or ""),
            "as_of_date": str(qtr_info_row.get("fld_enddate") or ""),
            "promoter_groups": promoter_groups,
            "total_promoter_holding_pct": summary_metrics["promoter_pct"],
            "total_pledge_pct": summary_metrics["pledge_pct"],
            "fii_holding_pct": round(fii_pct, 2),
            "dii_holding_pct": round(dii_pct, 2),
            "public_holding_pct": summary_metrics["public_pct"],
            "raw_data": {
                "qtrid": qtrid,
                "source_url": _BSE_SHP_SUMMARY_URL,
                "qtrinfo_url": _BSE_SHP_QTRINFO_URL,
                "promoter_url": _BSE_SHP_PROMOTER_URL,
                "public_url": _BSE_SHP_PUBLIC_URL,
                "foreign_url": _BSE_SHP_FOREIGN_URL,
                "parser_version": _PARSER_VERSION,
            },
        }

    except httpx.TimeoutException:
        logger.warning("BSE SHP timeout for scrip=%s qtrid=%s", scrip_code, qtrid)
        return None
    except Exception as exc:
        logger.debug("BSE SHP fetch failed for scrip=%s qtrid=%s: %s", scrip_code, qtrid, exc)
        return None


def parse_bse_shp_html(
    html_text: str,
    scrip_code: str,
    quarter: str,
    source_url: str,
) -> dict[str, Any] | None:
    """Parse BSE SHP listing HTML and capture XBRL/PDF filing links."""
    parser = _BseFilingLinkParser(source_url)
    parser.feed(html_text or "")
    if not parser.links:
        return None

    quarter_links = []
    for link in parser.links:
        haystack = f"{link['title']} {link['url']}"
        if quarter in haystack or quarter[0:4] in haystack or not re.search(r"20\d{2}", haystack):
            quarter_links.append(link)

    links = quarter_links or parser.links
    return {
        "scrip_code": scrip_code,
        "quarter": quarter,
        "promoter_groups": [],
        "total_promoter_holding_pct": 0.0,
        "total_pledge_pct": 0.0,
        "fii_holding_pct": 0.0,
        "dii_holding_pct": 0.0,
        "public_holding_pct": 0.0,
        "raw_data": {
            "source_url": source_url,
            "filing_links": links,
            "parser_version": _PARSER_VERSION,
        },
    }


def _try_parse_first_xbrl_link(client: httpx.Client, parsed_html: dict[str, Any]) -> dict[str, Any] | None:
    for link in parsed_html.get("raw_data", {}).get("filing_links", []):
        url = str(link.get("url") or "")
        if not any(url.lower().endswith(ext) for ext in (".xml", ".xbrl")):
            continue
        try:
            resp = client.get(url, headers=_BSE_HEADERS)
            if resp.status_code != 200:
                continue
            parsed = parse_bse_shp_xbrl(
                resp.text,
                scrip_code=parsed_html["scrip_code"],
                quarter=parsed_html["quarter"],
                source_url=url,
            )
            if any(
                parsed.get(key, 0) > 0
                for key in (
                    "total_promoter_holding_pct",
                    "public_holding_pct",
                    "fii_holding_pct",
                    "dii_holding_pct",
                )
            ):
                return parsed
        except Exception as exc:
            logger.debug("BSE SHP XBRL parse failed for %s: %s", url, exc)
    return None


def parse_bse_shp_xbrl(
    xml_text: str,
    scrip_code: str,
    quarter: str,
    source_url: str,
) -> dict[str, Any]:
    """Parse common BSE SHP XBRL facts into aggregate holding fields."""
    import xml.etree.ElementTree as ET

    result: dict[str, Any] = {
        "scrip_code": scrip_code,
        "quarter": quarter,
        "promoter_groups": [],
        "total_promoter_holding_pct": 0.0,
        "total_pledge_pct": 0.0,
        "fii_holding_pct": 0.0,
        "dii_holding_pct": 0.0,
        "public_holding_pct": 0.0,
        "raw_data": {
            "source_url": source_url,
            "parser_version": _PARSER_VERSION,
            "format": "xbrl",
        },
    }

    root = ET.fromstring(xml_text)
    for elem in root.iter():
        local_name = elem.tag.rsplit("}", 1)[-1].lower()
        text = (elem.text or "").strip()
        value = _as_float(text)
        if value <= 0 or value > 100:
            continue

        if "pledge" in local_name or "encumber" in local_name:
            result["total_pledge_pct"] = max(result["total_pledge_pct"], value)
        elif "promoter" in local_name and ("percent" in local_name or "shareholding" in local_name):
            result["total_promoter_holding_pct"] = max(result["total_promoter_holding_pct"], value)
        elif "foreign" in local_name or "fii" in local_name:
            result["fii_holding_pct"] = max(result["fii_holding_pct"], value)
        elif "domesticinstitution" in local_name or "dii" in local_name:
            result["dii_holding_pct"] = max(result["dii_holding_pct"], value)
        elif "public" in local_name and ("percent" in local_name or "shareholding" in local_name):
            result["public_holding_pct"] = max(result["public_holding_pct"], value)

    if result["total_promoter_holding_pct"] > 0:
        result["promoter_groups"].append({
            "name": "Promoter and Promoter Group",
            "category": "Promoter",
            "holding_pct": round(result["total_promoter_holding_pct"], 2),
            "pledge_pct_of_holding": round(result["total_pledge_pct"], 2),
        })

    for key in (
        "total_promoter_holding_pct",
        "total_pledge_pct",
        "fii_holding_pct",
        "dii_holding_pct",
        "public_holding_pct",
    ):
        result[key] = round(result[key], 2)
    return result


def parse_bse_shp_response(
    data: dict[str, Any],
    scrip_code: str,
    quarter: str,
) -> dict[str, Any]:
    """Parse BSE SHP JSON response into standardized format.

    BSE SHP response structure varies slightly; we handle common patterns.
    """
    result: dict[str, Any] = {
        "scrip_code": scrip_code,
        "quarter": quarter,
        "promoter_groups": [],
        "total_promoter_holding_pct": 0.0,
        "total_pledge_pct": 0.0,
        "fii_holding_pct": 0.0,
        "dii_holding_pct": 0.0,
        "public_holding_pct": 0.0,
        "raw_data": {**data, "parser_version": _PARSER_VERSION},
    }

    shp_data = _extract_shp_rows(data)

    for item in shp_data:
        category = str(
            item.get("category")
            or item.get("ShareHolderCategory")
            or item.get("Fld_ShortCatg")
            or item.get("Fld_ShortName")
            or item.get("FLD_CATEGORY")
            or item.get("CATEGORY")
            or item.get("Cat")
            or ""
        )
        pct = _as_float(
            item.get("percentage")
            or item.get("ShareholPercentage")
            or item.get("ShareholdingPercentage")
            or item.get("NoOfSharesPercent")
            or item.get("TotalShareholdingPercentage")
            or item.get("PercToTotalShares")
            or item.get("Fld_TotalPercentageOf_A_B_C2")
            or item.get("Fld_TotalVotingRightsPercent")
            or item.get("Fld_PercentAfterFullConversion")
        )
        pledge_pct = _as_float(
            item.get("pledgePct")
            or item.get("PledgeShares")
            or item.get("PledgePercentage")
            or item.get("EncumberedSharesPercentage")
            or item.get("Fld_TotalencumberedPercentage")
            or item.get("Fld_PledgeEncumberedPercentage")
        )
        name = str(item.get("name") or item.get("ShareHolderName") or item.get("Name") or "")

        cat_lower = category.lower()
        if "promoter" in cat_lower and "non promoter" not in cat_lower and "non-promoter" not in cat_lower:
            result["total_promoter_holding_pct"] += pct
            if pledge_pct > 0:
                result["total_pledge_pct"] += pledge_pct
            result["promoter_groups"].append({
                "name": name,
                "category": category,
                "holding_pct": round(pct, 2),
                "pledge_pct_of_holding": round(pledge_pct, 2),
            })
        elif "fii" in cat_lower or "foreign" in cat_lower:
            result["fii_holding_pct"] += pct
        elif "dii" in cat_lower or "institution" in cat_lower:
            result["dii_holding_pct"] += pct
        elif ("public" in cat_lower or "retail" in cat_lower) and "non promoter" not in cat_lower and "non-promoter" not in cat_lower:
            result["public_holding_pct"] += pct

    result["total_promoter_holding_pct"] = round(result["total_promoter_holding_pct"], 2)
    result["total_pledge_pct"] = round(result["total_pledge_pct"], 2)
    result["fii_holding_pct"] = round(result["fii_holding_pct"], 2)
    result["dii_holding_pct"] = round(result["dii_holding_pct"], 2)
    result["public_holding_pct"] = round(result["public_holding_pct"], 2)

    return result


def _as_float(value: Any) -> float:
    try:
        return float(str(value or "0").replace(",", "").replace("%", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _extract_shp_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("Table1", "Table5", "data", "shareholding", "ShareholdingPattern", "Table"):
        value = data.get(key)
        if isinstance(value, list):
            rows = [item for item in value if isinstance(item, dict)]
            if rows:
                return rows
        elif isinstance(value, dict):
            rows = _extract_shp_rows(value)
            if rows:
                return rows
    for value in data.values():
        if isinstance(value, list):
            rows = [item for item in value if isinstance(item, dict)]
            if rows:
                return rows
    return []


def store_shp_to_postgres(
    shp_data: dict[str, Any],
    cin: str | None,
    database_url: str | None = None,
) -> bool:
    """Store parsed SHP data in PostgreSQL shp_raw staging table."""
    import json

    db_url = get_database_url(database_url)
    if not db_url:
        return False

    try:
        with connect_postgres(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into shp_raw (
                      scrip_code, cin, quarter,
                      total_promoter_holding_pct, total_pledge_pct,
                      fii_holding_pct, dii_holding_pct, public_holding_pct,
                      promoter_groups_json, raw_json, fetched_at
                    )
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, now())
                    on conflict (scrip_code, quarter) do update set
                      total_promoter_holding_pct = excluded.total_promoter_holding_pct,
                      total_pledge_pct = excluded.total_pledge_pct,
                      fii_holding_pct = excluded.fii_holding_pct,
                      dii_holding_pct = excluded.dii_holding_pct,
                      public_holding_pct = excluded.public_holding_pct,
                      promoter_groups_json = excluded.promoter_groups_json,
                      raw_json = excluded.raw_json,
                      fetched_at = now()
                    """,
                    (
                        shp_data["scrip_code"],
                        cin,
                        shp_data["quarter"],
                        shp_data["total_promoter_holding_pct"],
                        shp_data["total_pledge_pct"],
                        shp_data["fii_holding_pct"],
                        shp_data["dii_holding_pct"],
                        shp_data["public_holding_pct"],
                        json.dumps(shp_data["promoter_groups"]),
                        json.dumps(shp_data.get("raw_data", {})),
                    ),
                )
            conn.commit()
        return True
    except Exception as exc:
        logger.error("SHP store failed for scrip=%s: %s", shp_data.get("scrip_code"), exc)
        return False


async def write_shp_to_ikg(shp_data: dict[str, Any], cin: str) -> None:
    """Write OWNS_STAKE_IN edges to IKG from parsed SHP data."""
    from finagent.ikg.graph_client import get_graph_client

    client = get_graph_client()
    quarter = shp_data.get("quarter", "")
    await client.upsert_vertex(
        f"company:{cin}",
        "Company",
        {
            "cin": cin,
            "bse_scrip_code": shp_data.get("scrip_code"),
            "source_citation": "BSE_SHP",
        },
    )

    for promoter in shp_data.get("promoter_groups", []):
        promoter_name = promoter.get("name", "")
        if not promoter_name:
            continue

        # Create a stable promoter ID
        promoter_id = f"{cin}:{promoter_name[:50].replace(' ', '_').upper()}"

        # Upsert PromoterGroup vertex
        await client.upsert_vertex(
            f"promoter:{promoter_id}",
            "PromoterGroup",
            {
                "promoter_id": promoter_id,
                "name": promoter_name,
                "promoter_type": "individual" if "individual" in promoter.get("category", "").lower() else "corporate",
            },
        )

        # OWNS_STAKE_IN edge
        await client.upsert_edge(
            f"promoter:{promoter_id}",
            f"company:{cin}",
            "OWNS_STAKE_IN",
            {
                "percentage": promoter.get("holding_pct", 0),
                "pledge_pct": promoter.get("pledge_pct_of_holding", 0),
                "quarter": quarter,
                "source_citation": "BSE_SHP",
            },
        )


def run_bse_shp_scraper(
    companies: list[dict[str, Any]],
    database_url: str | None = None,
    quarters: int = 4,
    max_companies: int | None = None,
) -> dict[str, Any]:
    """Full SHP pipeline for all provided companies.

    Args:
        companies: List of company dicts with scrip_code, cin keys.
        database_url: PostgreSQL connection string.
        quarters: Number of quarters to fetch. Capped by
            FINAGENT_BSE_SHP_MAX_QUARTERS (default 40 for 10 years).
        max_companies: Limit for testing.

    Returns:
        dict with: companies_processed, records_fetched, records_stored, errors
    """
    import asyncio

    max_quarters = max(1, int(os.getenv("FINAGENT_BSE_SHP_MAX_QUARTERS", "40") or "40"))
    quarters = max(1, min(int(quarters or 1), max_quarters))
    companies_subset = companies[:max_companies] if max_companies else companies

    workers = max(
        1,
        int(os.getenv("FINAGENT_BSE_SHP_MAX_WORKERS", str(_DEFAULT_MAX_WORKERS))),
    )

    def _process_company(co: dict[str, Any]) -> dict[str, Any]:
        scrip_code = str(co.get("bse_scrip_code") or co.get("scrip_code") or "")
        cin = co.get("cin")
        if not scrip_code:
            return {
                "companies_processed": 0,
                "records_fetched": 0,
                "records_stored": 0,
                "errors": 0,
                "quarters_fetched": [],
            }

        local_fetched = 0
        local_stored = 0
        local_errors = 0
        local_qtrids: set[str] = set()

        try:
            timeout = httpx.Timeout(_DEFAULT_DISCOVERY_TIMEOUT_S, connect=min(15.0, _DEFAULT_DISCOVERY_TIMEOUT_S))
            with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
                qtr_ids = _discover_qtrids(client, scrip_code, quarters)
        except Exception as exc:
            logger.warning("Failed to discover BSE SHP qtrids for %s: %s", scrip_code, exc)
            return {
                "companies_processed": 1,
                "records_fetched": 0,
                "records_stored": 0,
                "errors": 1,
                "quarters_fetched": [],
            }

        for qtr_id in qtr_ids:
            time.sleep(_REQUEST_DELAY_S)
            shp_data = fetch_bse_shp(scrip_code, qtr_id, timeout_s=_DEFAULT_REQUEST_TIMEOUT_S)
            if not shp_data:
                continue

            local_fetched += 1
            local_qtrids.add(str(qtr_id))
            stored = store_shp_to_postgres(shp_data, cin, database_url)
            if stored:
                local_stored += 1
                if cin:
                    try:
                        run_async(write_shp_to_ikg(shp_data, cin))
                    except Exception as exc:
                        logger.warning("IKG write failed for CIN %s: %s", cin, exc)
                        local_errors += 1
            else:
                local_errors += 1

        return {
            "companies_processed": 1,
            "records_fetched": local_fetched,
            "records_stored": local_stored,
            "errors": local_errors,
            "quarters_fetched": sorted(local_qtrids, reverse=True),
        }

    companies_processed = 0
    records_fetched = 0
    records_stored = 0
    errors = 0
    processed_qtrids: set[str] = set()

    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(companies_subset)))) as executor:
        futures = {executor.submit(_process_company, co): co for co in companies_subset}
        for idx, future in enumerate(as_completed(futures), start=1):
            try:
                stats = future.result()
            except Exception as exc:
                logger.warning("BSE SHP worker failed: %s", exc)
                errors += 1
                continue

            companies_processed += int(stats.get("companies_processed") or 0)
            records_fetched += int(stats.get("records_fetched") or 0)
            records_stored += int(stats.get("records_stored") or 0)
            errors += int(stats.get("errors") or 0)
            for qtr in stats.get("quarters_fetched") or []:
                processed_qtrids.add(str(qtr))

            if idx % 50 == 0:
                logger.info(
                    "SHP progress: %d/%d companies, %d records fetched",
                    idx, len(companies_subset), records_fetched,
                )

    return {
        "companies_processed": companies_processed,
        "records_fetched": records_fetched,
        "records_stored": records_stored,
        "errors": errors,
        "quarters_fetched": sorted(processed_qtrids, reverse=True),
    }

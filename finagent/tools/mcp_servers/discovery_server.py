# discovery_server.py
# ==============================================================================
# ORACLE FIOS - Consolidated OSINT & Data Discovery Engine (MCP Server)
# Port: 8003
# Merged: NSE Market Data + Web & News Search + Document Pipeline (RAG/Qdrant)
# ==============================================================================

from __future__ import annotations

import os
import re
import time
import asyncio
import hashlib
import logging
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastmcp import FastMCP

# ------------------------------------------------------------------------------
# Config
# ------------------------------------------------------------------------------
load_dotenv()

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION", "oracle_documents")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 dimension

# ------------------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("oracle.discovery_server")

# ------------------------------------------------------------------------------
# FastMCP Server Instance
# ------------------------------------------------------------------------------
mcp = FastMCP(
    "ORACLE OSINT & Data Discovery Engine",
    instructions=(
        "Consolidated OSINT & Data Discovery Engine containing NSE Market Data, "
        "Web & News Search, and the Document Pipeline (RAG/Qdrant). "
        "Part of the ORACLE Financial Intelligence OS."
    ),
)

# ------------------------------------------------------------------------------
# In-Memory Cache and Throttling for NSE Tools
# ------------------------------------------------------------------------------
class TTLCache:
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = {}          # key -> (value, expire_at)
        self.fetching = {}       # key -> threading.Lock()
        self.async_lock = asyncio.Lock()
        self.async_fetching = {} # key -> asyncio.Future

    def get(self, key: str) -> tuple[bool, Any]:
        """Returns (found, value) if key exists and is not expired."""
        with self.lock:
            if key in self.cache:
                val, expire_at = self.cache[key]
                if time.time() < expire_at:
                    return True, val
                else:
                    del self.cache[key]
            return False, None

    def set(self, key: str, value: Any, ttl: float):
        with self.lock:
            self.cache[key] = (value, time.time() + ttl)

    def get_or_fetch(self, key: str, fetch_fn, ttl: float) -> Any:
        found, val = self.get(key)
        if found:
            logger.info("Cache HIT for key: %s", key)
            return val

        key_lock = None
        is_first_fetcher = False

        with self.lock:
            if key in self.cache:
                val, expire_at = self.cache[key]
                if time.time() < expire_at:
                    return val
                else:
                    del self.cache[key]

            if key in self.fetching:
                key_lock = self.fetching[key]
            else:
                key_lock = threading.Lock()
                key_lock.acquire()
                self.fetching[key] = key_lock
                is_first_fetcher = True

        if not is_first_fetcher:
            logger.info("Cache WAIT/COALESCE for key: %s", key)
            with key_lock:
                found, val = self.get(key)
                if found:
                    return val
                return self.get_or_fetch(key, fetch_fn, ttl)

        logger.info("Cache MISS/FETCH for key: %s", key)
        try:
            val = fetch_fn()
            if isinstance(val, dict) and not val.get("error"):
                self.set(key, val, ttl)
            return val
        finally:
            with self.lock:
                if key in self.fetching:
                    del self.fetching[key]
            key_lock.release()

    async def async_get_or_fetch(self, key: str, fetch_fn, ttl: float) -> Any:
        found, val = self.get(key)
        if found:
            logger.info("Cache HIT for key: %s", key)
            return val

        loop = asyncio.get_running_loop()
        first_fetcher = False
        async with self.async_lock:
            found, val = self.get(key)
            if found:
                return val
            fut = self.async_fetching.get(key)
            if fut is None:
                fut = loop.create_future()
                self.async_fetching[key] = fut
                first_fetcher = True

        if not first_fetcher:
            logger.info("Cache WAIT/COALESCE for key: %s", key)
            return await fut

        try:
            logger.info("Cache MISS/FETCH for key: %s", key)
            val = await fetch_fn()
            if isinstance(val, dict) and not val.get("error"):
                self.set(key, val, ttl)
            if not fut.done():
                fut.set_result(val)
            return val
        except Exception as exc:
            if not fut.done():
                fut.set_exception(exc)
            raise
        finally:
            async with self.async_lock:
                self.async_fetching.pop(key, None)

_mcp_cache = TTLCache()
_nse_throttle_lock = asyncio.Lock()
_last_nse_request_time = 0.0

async def _async_throttled_nse_call(func, *args, **kwargs):
    global _last_nse_request_time
    async with _nse_throttle_lock:
        now = time.time()
        elapsed = now - _last_nse_request_time
        delay = 0.5 - elapsed
        if delay > 0:
            logger.info("Throttling: Sleeping for %.3f seconds before calling %s", delay, getattr(func, "__name__", str(func)))
            await asyncio.sleep(delay)
        _last_nse_request_time = time.time()
        return await asyncio.to_thread(func, *args, **kwargs)

def _throttled_nse_call(func, *args, **kwargs):
    """Compatibility wrapper for non-async callers; new NSE tools use the async gate."""
    return asyncio.run(_async_throttled_nse_call(func, *args, **kwargs))

# ------------------------------------------------------------------------------
# Lazy-loaded Clients & State
# ------------------------------------------------------------------------------
_nse_instance = None
_nse_download_folder = os.path.join(tempfile.gettempdir(), "oracle_nse_data")

_tavily = None
TRANSIENT_ERROR_MARKERS = (
    "connection", "timeout", "temporarily", "temporarily unavailable",
    "rate limit", "429", "503", "504", "reset by peer", "name resolution",
)

_qdrant_client = None
_embedder = None
_docs_download_dir = os.path.join(tempfile.gettempdir(), "oracle_docs")

# ------------------------------------------------------------------------------
# Document Processing Configurations
# ------------------------------------------------------------------------------
SECTION_ALIASES = {
    "risk_factors": ["risk factors", "risk factor"],
    "business_overview": ["our business", "business overview", "company overview", "industry overview"],
    "objects_of_issue": ["objects of the issue", "objects of this issue", "use of proceeds", "issue proceeds"],
    "financial_information": [
        "financial information", "restated financial information",
        "summary financial information", "selected financial information",
    ],
    "capital_structure": ["capital structure"],
    "management": ["our management", "management", "board of directors"],
}
DOC_SEARCH_CONFIG = {
    "drhp": {"query": "draft red herring prospectus pdf", "keywords": ["drhp", "draft red herring prospectus"]},
    "rhp": {"query": "red herring prospectus pdf", "keywords": ["rhp", "red herring prospectus"]},
    "prospectus": {"query": "prospectus pdf", "keywords": ["prospectus"]},
}

# ------------------------------------------------------------------------------
# Lazily Initialised Clients Helpers
# ------------------------------------------------------------------------------
def _get_nse():
    global _nse_instance
    if _nse_instance is None:
        from nse import NSE
        os.makedirs(_nse_download_folder, exist_ok=True)
        _nse_instance = NSE(_nse_download_folder)
    return _nse_instance

def _get_tavily():
    global _tavily
    if _tavily is None:
        if not TAVILY_API_KEY:
            raise ValueError("TAVILY_API_KEY is not configured.")
        from tavily import TavilyClient
        _tavily = TavilyClient(api_key=TAVILY_API_KEY)
    return _tavily

def _get_tavily_client():
    if not TAVILY_API_KEY:
        raise ValueError("TAVILY_API_KEY not configured.")
    from tavily import TavilyClient
    return TavilyClient(api_key=TAVILY_API_KEY)

def _get_qdrant():
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        if QDRANT_API_KEY:
            _qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
        else:
            _qdrant_client = QdrantClient(url=QDRANT_URL)

        collections = [c.name for c in _qdrant_client.get_collections().collections]
        if COLLECTION_NAME not in collections:
            _qdrant_client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
            )
            logger.info("Created Qdrant collection: %s", COLLECTION_NAME)
    return _qdrant_client

def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
        logger.info("Loaded embedding model: %s", EMBEDDING_MODEL)
    return _embedder

# ------------------------------------------------------------------------------
# General Helper Functions
# ------------------------------------------------------------------------------
def _safe_get(data: dict, *keys: str, default: Any = None) -> Any:
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current

def _parse_date(date_str: str | None, fallback: date | None = None) -> date:
    if date_str is None:
        if fallback is not None:
            return fallback
        raise ValueError("Date string is required")
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Could not parse date '{date_str}'. Use DD-MM-YYYY or YYYY-MM-DD.")

def _is_transient_search_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in TRANSIENT_ERROR_MARKERS)

def _search_with_retries(client: Any, *, retries: int = 2, **kwargs) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return client.search(**kwargs)
        except Exception as exc:
            last_exc = exc
            logger.warning("Tavily search attempt %d/%d failed: %s", attempt, retries, exc)
            if attempt >= retries or not _is_transient_search_error(exc):
                raise
            time.sleep(0.5 * attempt)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Tavily search failed.")

def _embed_texts(texts: list[str]) -> list[list[float]]:
    model = _get_embedder()
    embeddings = model.encode(texts, show_progress_bar=False)
    return embeddings.tolist()

def _chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    if not text or not text.strip():
        return []
    paragraphs = text.split("\n\n")
    chunks = []
    current_chunk = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current_chunk) + len(para) + 2 <= chunk_size:
            current_chunk += ("\n\n" + para) if current_chunk else para
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            if len(para) > chunk_size:
                sentences = para.replace(". ", ".\n").split("\n")
                current_chunk = ""
                for sent in sentences:
                    if len(current_chunk) + len(sent) + 1 <= chunk_size:
                        current_chunk += (" " + sent) if current_chunk else sent
                    else:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        current_chunk = sent
            else:
                current_chunk = para
    if current_chunk:
        chunks.append(current_chunk.strip())
    if overlap > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            prev_tail = chunks[i - 1][-overlap:]
            overlapped.append(prev_tail + " ... " + chunks[i])
        chunks = overlapped
    return chunks

def _extract_pdf_text(pdf_path: str) -> str:
    import fitz  # PyMuPDF
    doc = fitz.open(pdf_path)
    text_parts = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text_parts.append(f"--- Page {page_num + 1} ---\n{page.get_text()}")
    doc.close()
    return "\n\n".join(text_parts)

def _doc_id(source: str, symbol: str | None = None) -> str:
    return hashlib.md5(f"{source}:{symbol or 'UNKNOWN'}".encode()).hexdigest()

def _hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")

def _score_document_candidate(company_name: str, doc_type: str, title: str, url: str, snippet: str, score: float | None) -> float:
    config = DOC_SEARCH_CONFIG[doc_type]
    haystack = f"{title} {url} {snippet}".lower()
    company_tokens = [token for token in re.split(r"[^a-z0-9]+", company_name.lower()) if len(token) > 2]
    boosted_score = float(score or 0.0)
    if any(keyword in haystack for keyword in config["keywords"]):
        boosted_score += 3.0
    boosted_score += min(2.0, 0.25 * sum(1 for token in company_tokens if token in haystack))
    host = _hostname(url)
    if any(domain in host for domain in ("sebi.gov.in", "nseindia.com", "bseindia.com")):
        boosted_score += 2.0
    return boosted_score

def _find_section_positions(text: str) -> list[tuple[int, str]]:
    lower_text = text.lower()
    positions: list[tuple[int, str]] = []
    for section_name, aliases in SECTION_ALIASES.items():
        best_pos = None
        for alias in aliases:
            pos = lower_text.find(alias)
            if pos != -1 and (best_pos is None or pos < best_pos):
                best_pos = pos
        if best_pos is not None:
            positions.append((best_pos, section_name))
    positions.sort(key=lambda item: item[0])
    return positions

def _extract_named_sections(text: str) -> dict[str, dict[str, Any]]:
    normalized_text = " ".join(text.split())
    if not normalized_text:
        return {}
    positions = _find_section_positions(normalized_text)
    sections: dict[str, dict[str, Any]] = {}
    for idx, (start, section_name) in enumerate(positions):
        end = positions[idx + 1][0] if idx + 1 < len(positions) else min(len(normalized_text), start + 6000)
        section_text = normalized_text[start:end].strip()
        sections[section_name] = {
            "present": True,
            "section_length": len(section_text),
            "excerpt": section_text[:1200],
        }
    for section_name in SECTION_ALIASES:
        sections.setdefault(section_name, {"present": False, "section_length": 0, "excerpt": ""})
    return sections

def _build_transition_notes(documents: list[dict[str, Any]]) -> list[str]:
    notes: list[str] = []
    for left, right in zip(documents, documents[1:]):
        left_type = left["doc_type"].upper()
        right_type = right["doc_type"].upper()
        for section_name in SECTION_ALIASES:
            left_section = left["sections"][section_name]
            right_section = right["sections"][section_name]
            if left_section["present"] and not right_section["present"]:
                notes.append(f"{section_name} appears in {left_type} but not in {right_type}.")
            elif not left_section["present"] and right_section["present"]:
                notes.append(f"{section_name} appears in {right_type} but not in {left_type}.")
            elif left_section["present"] and right_section["present"] and left_section["section_length"] > 0:
                left_len = left_section["section_length"]
                right_len = right_section["section_length"]
                change_ratio = abs(right_len - left_len) / left_len
                if change_ratio >= 0.2:
                    direction = "expanded" if right_len > left_len else "condensed"
                    notes.append(f"{section_name} was {direction} from {left_type} to {right_type}.")
    deduped: list[str] = []
    seen = set()
    for note in notes:
        if note not in seen:
            seen.add(note)
            deduped.append(note)
    return deduped

# ==============================================================================
# SUB-LAYER 1: NSE Market Feeds Tools
# ==============================================================================

@mcp.tool()
async def nse_get_quote(symbol: str) -> dict:
    """Fetch the real-time stock quote from NSE India (PE, face value, ISIN, volume, price info)."""
    symbol = symbol.strip().upper()
    logger.info("nse_get_quote: %s", symbol)

    async def fetch_fn():
        try:
            nse = _get_nse()
            raw = await _async_throttled_nse_call(nse.quote, symbol)
        except Exception as exc:
            logger.error("nse_get_quote failed for %s: %s", symbol, exc)
            return {"error": True, "message": f"Failed to fetch quote for '{symbol}': {str(exc)}"}

        price_info = raw.get("priceInfo", {})
        if price_info.get("lastPrice") is None:
            return {"error": True, "message": f"No data found for symbol '{symbol}'."}

        info = raw.get("info", {})
        metadata = raw.get("metadata", {})
        security_info = raw.get("securityInfo", {})
        industry_info = raw.get("industryInfo", {})

        quote = {
            "symbol": info.get("symbol", symbol),
            "company_name": info.get("companyName", metadata.get("companyName", "N/A")),
            "isin": info.get("isin", metadata.get("isin")),
            "series": metadata.get("series"),
            "listing_date": metadata.get("listingDate"),
            "sector": industry_info.get("sector", metadata.get("pdSectorInd", "").strip()),
            "industry": industry_info.get("industry", metadata.get("industry")),
            "basic_industry": industry_info.get("basicIndustry"),
            "last_price": price_info.get("lastPrice"),
            "change": price_info.get("change"),
            "pct_change": price_info.get("pChange"),
            "open": price_info.get("open"),
            "high": _safe_get(price_info, "intraDayHighLow", "max"),
            "low": _safe_get(price_info, "intraDayHighLow", "min"),
            "close": price_info.get("close"),
            "prev_close": price_info.get("previousClose"),
            "vwap": price_info.get("vwap"),
            "week_high_52": _safe_get(price_info, "weekHighLow", "max"),
            "week_low_52": _safe_get(price_info, "weekHighLow", "min"),
            "week_high_52_date": _safe_get(price_info, "weekHighLow", "maxDate"),
            "week_low_52_date": _safe_get(price_info, "weekHighLow", "minDate"),
            "sector_pe": metadata.get("pdSectorPe"),
            "symbol_pe": metadata.get("pdSymbolPe"),
            "face_value": security_info.get("faceValue"),
            "issued_size": security_info.get("issuedSize"),
            "is_fno": info.get("isFNOSec", False),
        }
        return {"error": False, "data": quote}

    return await _mcp_cache.async_get_or_fetch(f"quote:{symbol}", fetch_fn, 300)

@mcp.tool()
async def nse_get_trade_info(symbol: str) -> dict:
    """Fetch trade volume, traded value, market cap, free-float market cap, and delivery quantity percentage."""
    symbol = symbol.strip().upper()
    logger.info("nse_get_trade_info: %s", symbol)

    async def fetch_fn():
        try:
            nse = _get_nse()
            raw = await _async_throttled_nse_call(nse.quote, symbol, section="trade_info")
        except Exception as exc:
            return {"error": True, "message": f"Failed: {str(exc)}"}

        trade = _safe_get(raw, "marketDeptOrderBook", "tradeInfo", default={})
        dp = raw.get("securityWiseDP", {})
        return {
            "error": False,
            "data": {
                "symbol": symbol,
                "total_traded_volume": trade.get("totalTradedVolume"),
                "total_traded_value": trade.get("totalTradedValue"),
                "total_market_cap": trade.get("totalMarketCap"),
                "free_float_market_cap": trade.get("ffmc"),
                "impact_cost": trade.get("impactCost"),
                "daily_volatility": trade.get("cmDailyVolatility"),
                "annual_volatility": trade.get("cmAnnualVolatility"),
                "delivery_quantity": dp.get("deliveryQuantity"),
                "quantity_traded": dp.get("quantityTraded"),
                "delivery_to_traded_pct": dp.get("deliveryToTradedQuantity"),
            },
        }

    return await _mcp_cache.async_get_or_fetch(f"trade_info:{symbol}", fetch_fn, 300)

@mcp.tool()
async def nse_get_historical(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    days: int = 365,
) -> dict:
    """Fetch historical OHLCV data directly from NSE India."""
    symbol = symbol.strip().upper()
    logger.info("nse_get_historical: %s", symbol)
    try:
        ed = _parse_date(end_date, fallback=date.today())
        sd = _parse_date(start_date) if start_date else ed - timedelta(days=days)
    except Exception as exc:
        return {"error": True, "message": f"Date parsing failed: {str(exc)}"}

    async def fetch_fn():
        try:
            nse = _get_nse()
            raw_records = await _async_throttled_nse_call(
                nse.fetch_equity_historical_data,
                symbol=symbol,
                from_date=sd,
                to_date=ed,
                series="EQ"
            )
            if not raw_records:
                return {"error": True, "message": f"No historical data for '{symbol}' in the given range."}

            records = []
            for r in raw_records:
                records.append({
                    "date": r.get("mtimestamp", ""),
                    "open": r.get("chOpeningPrice"),
                    "high": r.get("chTradeHighPrice"),
                    "low": r.get("chTradeLowPrice"),
                    "close": r.get("chClosingPrice"),
                    "ltp": r.get("chLastTradedPrice"),
                    "prev_close": r.get("chPreviousClsPrice"),
                    "volume": r.get("chTotTradedQty"),
                    "value": r.get("chTotTradedVal"),
                    "vwap": r.get("vwap"),
                    "total_trades": r.get("chTotalTrades"),
                })
            return {
                "error": False,
                "data": {
                    "symbol": symbol,
                    "total_records": len(records),
                    "date_range": {"start": records[0]["date"], "end": records[-1]["date"]},
                    "records": records,
                },
            }
        except Exception as exc:
            return {"error": True, "message": f"Failed: {str(exc)}"}

    cache_key = f"historical:{symbol}:{sd.strftime('%Y-%m-%d')}:{ed.strftime('%Y-%m-%d')}"
    return await _mcp_cache.async_get_or_fetch(cache_key, fetch_fn, 86400)

@mcp.tool()
async def nse_get_option_chain(symbol: str) -> dict:
    """Fetch option chain data (total CE/PE OI, PCR, underlying value, strikes) for a stock or index."""
    symbol_upper = symbol.strip().upper()
    sym = symbol.strip().lower() if symbol_upper in ("NIFTY", "BANKNIFTY", "FINNIFTY", "NIFTYIT") else symbol_upper

    async def fetch_fn():
        try:
            nse = _get_nse()
            raw = await _async_throttled_nse_call(nse.optionChain, sym)
            records = raw.get("records", {})
            filtered = raw.get("filtered", {})
            ce_oi = _safe_get(filtered, "CE", "totOI", default=0)
            pe_oi = _safe_get(filtered, "PE", "totOI", default=0)
            pcr = round(pe_oi / ce_oi, 2) if ce_oi > 0 else None
            return {
                "error": False,
                "data": {
                    "symbol": symbol_upper,
                    "underlying_value": records.get("underlyingValue"),
                    "expiry_dates": records.get("expiryDates", [])[:5],
                    "total_ce_oi": ce_oi,
                    "total_pe_oi": pe_oi,
                    "pcr": pcr,
                    "strikePrices": records.get("strikePrices", []),
                },
            }
        except Exception as exc:
            return {"error": True, "message": str(exc)}

    return await _mcp_cache.async_get_or_fetch(f"option_chain:{symbol_upper}", fetch_fn, 300)

@mcp.tool()
async def nse_get_index(index_name: str = "NIFTY 50") -> dict:
    """Fetch live index details with constituent stocks."""
    async def fetch_fn():
        try:
            nse = _get_nse()
            raw = await _async_throttled_nse_call(nse.listEquityStocksByIndex, index=index_name)
            return {"error": False, "data": raw}
        except Exception as exc:
            return {"error": True, "message": str(exc)}

    return await _mcp_cache.async_get_or_fetch(f"index:{index_name}", fetch_fn, 300)

@mcp.tool()
async def nse_get_shareholding(symbol: str) -> dict:
    """Fetch promoter, public, mutual fund, and foreign holding pattern from NSE."""
    symbol = symbol.strip().upper()

    async def fetch_fn():
        try:
            nse = _get_nse()
            raw = await _async_throttled_nse_call(nse.shareholding, symbol)
            return {"error": False, "data": raw}
        except Exception as exc:
            return {"error": True, "message": str(exc)}

    return await _mcp_cache.async_get_or_fetch(f"shareholding:{symbol}", fetch_fn, 86400)

@mcp.tool()
async def nse_get_actions(symbol: str | None = None) -> dict:
    """Fetch corporate actions like dividend, splits, bonus, rights."""
    sym = symbol.strip().upper() if symbol else None

    async def fetch_fn():
        try:
            nse = _get_nse()
            if sym:
                raw = await _async_throttled_nse_call(nse.actions, symbol=sym)
            else:
                raw = await _async_throttled_nse_call(nse.actions)
            return {"error": False, "data": raw}
        except Exception as exc:
            return {"error": True, "message": str(exc)}

    return await _mcp_cache.async_get_or_fetch(f"actions:{sym or 'ALL'}", fetch_fn, 86400)

@mcp.tool()
async def nse_get_announcements(symbol: str | None = None) -> dict:
    """Fetch corporate announcements from NSE."""
    sym = symbol.strip().upper() if symbol else None

    async def fetch_fn():
        try:
            nse = _get_nse()
            if sym:
                raw = await _async_throttled_nse_call(nse.announcements, symbol=sym)
            else:
                raw = await _async_throttled_nse_call(nse.announcements)
            return {"error": False, "data": raw}
        except Exception as exc:
            return {"error": True, "message": str(exc)}

    return await _mcp_cache.async_get_or_fetch(f"announcements:{sym or 'ALL'}", fetch_fn, 86400)

@mcp.tool()
async def nse_get_board_meetings(symbol: str | None = None) -> dict:
    """Fetch upcoming board meetings (results dates, dividend discussions)."""
    sym = symbol.strip().upper() if symbol else None

    async def fetch_fn():
        try:
            nse = _get_nse()
            if sym:
                raw = await _async_throttled_nse_call(nse.boardMeetings, symbol=sym)
            else:
                raw = await _async_throttled_nse_call(nse.boardMeetings)
            return {"error": False, "data": raw}
        except Exception as exc:
            return {"error": True, "message": str(exc)}

    return await _mcp_cache.async_get_or_fetch(f"board_meetings:{sym or 'ALL'}", fetch_fn, 86400)


# ==============================================================================
# SUB-LAYER 2: Web & News Search Tools
# ==============================================================================

@mcp.tool()
def search_web(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
    include_answer: bool = True,
    time_range: str | None = None,
) -> dict:
    """Perform a general web search using Tavily."""
    logger.info("search_web: query='%s'", query)
    try:
        client = _get_tavily()
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_answer="basic" if include_answer else False,
            topic="general",
            time_range=time_range,
        )
        results = [{"title": r.get("title"), "url": r.get("url"), "content": r.get("content"), "score": r.get("score")} for r in response.get("results", [])]
        return {
            "error": False,
            "data": {
                "query": query,
                "answer": response.get("answer"),
                "total_results": len(results),
                "results": results,
                "response_time": response.get("response_time"),
            }
        }
    except Exception as exc:
        return {"error": True, "message": str(exc)}

@mcp.tool()
def search_news(query: str, max_results: int = 10, time_range: str = "week") -> dict:
    """Search for real-time news articles about finance, stocks, and markets."""
    try:
        client = _get_tavily()
        attempts = [
            {"strategy": "news", "kwargs": {"query": query, "max_results": max_results, "search_depth": "basic", "include_answer": "basic", "topic": "news", "time_range": time_range}},
            {"strategy": "finance", "kwargs": {"query": query, "max_results": max_results, "search_depth": "basic", "include_answer": "basic", "topic": "finance"}},
            {"strategy": "general", "kwargs": {"query": query, "max_results": max_results, "search_depth": "basic", "include_answer": "basic", "topic": "general"}},
        ]
        last_error = None
        last_output = None
        for attempt in attempts:
            try:
                response = _search_with_retries(client, **attempt["kwargs"])
                articles = [{"title": r.get("title"), "url": r.get("url"), "content": r.get("content"), "score": r.get("score"), "published_date": r.get("published_date")} for r in response.get("results", [])]
                output = {"query": query, "answer": response.get("answer"), "total_articles": len(articles), "articles": articles, "time_range": time_range, "strategy_used": attempt["strategy"]}
                last_output = output
                if articles:
                    return {"error": False, "data": output}
            except Exception as exc:
                last_error = str(exc)

        if last_output is not None:
            return {"error": False, "data": last_output}
        return {"error": True, "message": last_error or "Tavily news search failed."}
    except Exception as exc:
        return {"error": True, "message": str(exc)}

@mcp.tool()
def get_latest_company_news(companies: list[str], max_results_per_company: int = 3, time_range: str = "week") -> dict:
    """Retrieve the latest news articles for one or more companies with fallback searching."""
    try:
        client = _get_tavily()
        output = {}
        for company in companies[:5]:
            name = company.strip()
            if not name:
                continue
            company_result = {"company": name, "strategy_used": None, "results": [], "answer": None}
            attempts = [
                {"strategy": "news", "kwargs": {"query": f"{name} latest news", "max_results": max_results_per_company, "search_depth": "basic", "include_answer": "basic", "topic": "news", "time_range": time_range}},
                {"strategy": "finance", "kwargs": {"query": f"{name} latest news", "max_results": max_results_per_company, "search_depth": "basic", "include_answer": "basic", "topic": "finance"}},
                {"strategy": "general", "kwargs": {"query": f"{name} latest news", "max_results": max_results_per_company, "search_depth": "basic", "include_answer": "basic", "topic": "general"}},
            ]
            last_error = None
            for attempt in attempts:
                try:
                    response = _search_with_retries(client, **attempt["kwargs"])
                    results = [{"title": r.get("title"), "url": r.get("url"), "content": r.get("content"), "score": r.get("score"), "published_date": r.get("published_date")} for r in response.get("results", [])]
                    if results:
                        company_result["strategy_used"] = attempt["strategy"]
                        company_result["answer"] = response.get("answer")
                        company_result["results"] = results
                        break
                except Exception as exc:
                    last_error = str(exc)
            if not company_result["results"] and last_error:
                company_result["error"] = last_error
            output[name] = company_result
        return {"error": False, "data": {"companies": output, "time_range": time_range}}
    except Exception as exc:
        return {"error": True, "message": str(exc)}

@mcp.tool()
def search_financial(query: str, max_results: int = 4, search_depth: str = "basic", include_domains: list[str] | None = None) -> dict:
    """Finance-focused search prioritising Indian financial publications (MoneyControl, ET, Screener, BSE, NSE, SEBI)."""
    if include_domains is None:
        include_domains = [
            "moneycontrol.com", "economictimes.indiatimes.com", "screener.in", "trendlyne.com",
            "bseindia.com", "nseindia.com", "livemint.com", "businesstoday.in",
            "ndtvprofit.com", "sebi.gov.in"
        ]
    try:
        client = _get_tavily()
        response = client.search(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            include_answer="basic",
            topic="finance",
            include_domains=include_domains,
        )
        results = [{"title": r.get("title"), "url": r.get("url"), "content": r.get("content"), "score": r.get("score")} for r in response.get("results", [])]
        return {
            "error": False,
            "data": {
                "query": query,
                "answer": response.get("answer"),
                "total_results": len(results),
                "results": results,
                "sources_prioritised": include_domains,
            }
        }
    except Exception as exc:
        return {"error": True, "message": str(exc)}

@mcp.tool()
def extract_url(urls: list[str], extract_depth: str = "basic") -> dict:
    """Extract clean, structured markdown content from web pages / URLs."""
    try:
        client = _get_tavily()
        response = client.extract(urls=urls, extract_depth=extract_depth)
        results = [{"url": r.get("url"), "content": r.get("raw_content", "")} for r in response.get("results", [])]
        failed = [{"url": f.get("url"), "error": f.get("error")} for f in response.get("failed_results", [])]
        return {
            "error": False,
            "data": {
                "total_extracted": len(results),
                "total_failed": len(failed),
                "results": results,
                "failed": failed,
                "response_time": response.get("response_time"),
            }
        }
    except Exception as exc:
        return {"error": True, "message": str(exc)}

@mcp.tool()
def research_company(symbol: str, company_name: str | None = None) -> dict:
    """Perform multi-dimensional company research (recent news, earnings results, analyst views, board updates, sector outlook)."""
    symbol = symbol.strip().upper()
    name = company_name or symbol
    try:
        client = _get_tavily()
        queries = {
            "recent_news": f"{name} {symbol} latest news India stock market",
            "quarterly_results": f"{name} {symbol} quarterly results earnings 2026",
            "analyst_views": f"{name} {symbol} analyst target price buy sell recommendation",
            "management": f"{name} {symbol} management commentary guidance outlook",
            "sector_outlook": f"{name} sector industry outlook India 2026",
        }
        research = {}
        for category, query in queries.items():
            try:
                response = client.search(
                    query=query,
                    max_results=3,
                    search_depth="basic",
                    include_answer="basic",
                    topic="news" if category == "recent_news" else "finance",
                    time_range="month",
                )
                research[category] = {
                    "query": query,
                    "answer": response.get("answer"),
                    "sources": [{"title": r.get("title"), "url": r.get("url"), "snippet": (r.get("content") or "")[:300]} for r in response.get("results", [])]
                }
            except Exception as e:
                research[category] = {"query": query, "error": str(e)}
        return {
            "error": False,
            "data": {
                "symbol": symbol,
                "company_name": name,
                "research_date": datetime.now().isoformat(),
                "categories": research,
            }
        }
    except Exception as exc:
        return {"error": True, "message": str(exc)}

# ==============================================================================
# SUB-LAYER 3: Document Ingestion & RAG Tools
# ==============================================================================

@mcp.tool()
def doc_search(query: str, symbol: str | None = None, doc_type: str | None = None, top_k: int = 5) -> dict:
    """Search indexed documents in Qdrant (annual reports, con-calls, filings, transcript chunks)."""
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        client = _get_qdrant()
        query_vector = _embed_texts([query])[0]

        must_conditions = []
        if symbol:
            must_conditions.append(FieldCondition(key="symbol", match=MatchValue(value=symbol.strip().upper())))
        if doc_type:
            must_conditions.append(FieldCondition(key="doc_type", match=MatchValue(value=doc_type)))

        search_filter = Filter(must=must_conditions) if must_conditions else None
        results = client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            limit=top_k,
            query_filter=search_filter,
        )

        if not results:
            return {
                "error": False,
                "data": {
                    "query": query,
                    "total_results": 0,
                    "results": [],
                    "note": "No indexed documents found.",
                }
            }

        chunks = [{
            "content": r.payload.get("text", ""),
            "symbol": r.payload.get("symbol"),
            "doc_type": r.payload.get("doc_type"),
            "source": r.payload.get("source"),
            "chunk_index": r.payload.get("chunk_index"),
            "date": r.payload.get("date"),
            "score": round(r.score, 4),
        } for r in results]
        return {"error": False, "data": {"query": query, "total_results": len(chunks), "results": chunks}}
    except Exception as exc:
        return {"error": True, "message": str(exc)}

@mcp.tool()
def doc_ingest_pdf(pdf_path: str, symbol: str | None = None, doc_type: str = "annual_report", date_str: str | None = None) -> dict:
    """Extract text from a PDF, chunk it, embed and index in Qdrant."""
    normalized_symbol = symbol.strip().upper() if symbol else None
    try:
        from qdrant_client.models import PointStruct
        import uuid

        text = _extract_pdf_text(pdf_path)
        if not text.strip():
            return {"error": True, "message": "PDF text is empty."}

        chunks = _chunk_text(text)
        if not chunks:
            return {"error": True, "message": "No content chunks generated."}

        embeddings = _embed_texts(chunks)
        client = _get_qdrant()
        points = []
        doc_id = _doc_id(pdf_path, normalized_symbol)

        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embedding,
                    payload={
                        "text": chunk,
                        "symbol": normalized_symbol,
                        "doc_type": doc_type,
                        "source": pdf_path,
                        "doc_id": doc_id,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "date": date_str or datetime.now().strftime("%Y-%m-%d"),
                        "indexed_at": datetime.now().isoformat(),
                    },
                )
            )

        for i in range(0, len(points), 100):
            client.upsert(collection_name=COLLECTION_NAME, points=points[i : i + 100])

        return {
            "error": False,
            "data": {
                "symbol": normalized_symbol,
                "doc_type": doc_type,
                "source": pdf_path,
                "doc_id": doc_id,
                "total_chunks": len(chunks),
                "total_characters": len(text),
            }
        }
    except Exception as exc:
        return {"error": True, "message": str(exc)}

@mcp.tool()
def doc_ingest_url(url: str, symbol: str | None = None, doc_type: str = "webpage", date_str: str | None = None) -> dict:
    """Scrape web page content via Tavily, chunk it, embed and index in Qdrant."""
    normalized_symbol = symbol.strip().upper() if symbol else None
    try:
        from qdrant_client.models import PointStruct
        import uuid

        tavily = _get_tavily_client()
        response = tavily.extract(urls=[url], extract_depth="advanced")
        results = response.get("results", [])
        if not results:
            return {"error": True, "message": "Could not extract content."}

        text = results[0].get("raw_content", "")
        if not text.strip():
            return {"error": True, "message": "Content is empty."}

        chunks = _chunk_text(text)
        embeddings = _embed_texts(chunks)
        client = _get_qdrant()
        points = []
        doc_id = _doc_id(url, normalized_symbol)

        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embedding,
                    payload={
                        "text": chunk,
                        "symbol": normalized_symbol,
                        "doc_type": doc_type,
                        "source": url,
                        "doc_id": doc_id,
                        "chunk_index": i,
                        "total_chunks": len(chunks),
                        "date": date_str or datetime.now().strftime("%Y-%m-%d"),
                        "indexed_at": datetime.now().isoformat(),
                    },
                )
            )

        for i in range(0, len(points), 100):
            client.upsert(collection_name=COLLECTION_NAME, points=points[i : i + 100])

        return {
            "error": False,
            "data": {
                "symbol": normalized_symbol,
                "doc_type": doc_type,
                "source": url,
                "doc_id": doc_id,
                "total_chunks": len(chunks),
            }
        }
    except Exception as exc:
        return {"error": True, "message": str(exc)}

@mcp.tool()
def doc_fetch_annual_report(symbol: str) -> dict:
    """Auto-fetch latest annual report PDF from NSE, download it, extract and index in Qdrant."""
    symbol = symbol.strip().upper()
    try:
        from nse import NSE
        os.makedirs(_docs_download_dir, exist_ok=True)
        nse = NSE(_docs_download_dir)

        reports = _throttled_nse_call(nse.annual_reports, symbol=symbol)
        report_data = reports.get("data", [])
        if not report_data:
            return {"error": True, "message": f"No annual reports found on NSE for '{symbol}'."}

        latest = report_data[0]
        report_url = latest.get("fileName", "")
        if not report_url:
            return {"error": True, "message": "Report URL not found."}

        try:
            saved_path = _throttled_nse_call(nse.download_document, report_url, folder=_docs_download_dir)
            saved_path = str(saved_path)
        except Exception as dl_err:
            return {
                "error": False,
                "data": {
                    "symbol": symbol,
                    "status": "url_found_but_download_failed",
                    "report_url": report_url,
                    "download_error": str(dl_err),
                    "suggestion": f"Use doc_ingest_url to extract content via Tavily.",
                    "all_reports": [{"year": r.get("year"), "url": r.get("fileName")} for r in report_data[:5]],
                }
            }

        result = doc_ingest_pdf(pdf_path=saved_path, symbol=symbol, doc_type="annual_report")
        if not result.get("error"):
            result["data"]["report_url"] = report_url
            result["data"]["all_reports_count"] = len(report_data)
        return result
    except Exception as exc:
        return {"error": True, "message": str(exc)}

@mcp.tool()
def doc_compare_offer_documents(company_name: str, include_doc_types: list[str] | None = None) -> dict:
    """Download and compare DRHP, RHP, and prospectus offer documents for an IPO candidate."""
    try:
        requested_doc_types = include_doc_types or ["drhp", "rhp", "prospectus"]
        requested_doc_types = [doc_type.lower() for doc_type in requested_doc_types if doc_type.lower() in DOC_SEARCH_CONFIG]
        if not requested_doc_types:
            return {"error": True, "message": "Provide at least one valid document type."}

        tavily = _get_tavily_client()
        documents = []
        not_found = []

        for doc_type in requested_doc_types:
            search_config = DOC_SEARCH_CONFIG[doc_type]
            query = f"\"{company_name}\" {search_config['query']}"
            search_response = tavily.search(
                query=query, max_results=5, search_depth="advanced",
                topic="finance",
                include_domains=["sebi.gov.in", "nseindia.com", "bseindia.com", "chittorgarh.com", "investorgain.com", "topsharebrokers.com"],
            )

            candidates = []
            for result in search_response.get("results", []):
                title = result.get("title") or ""
                url = result.get("url") or ""
                snippet = result.get("content") or ""
                if not url:
                    continue
                candidates.append({
                    "title": title, "url": url, "snippet": snippet[:400],
                    "score": _score_document_candidate(company_name, doc_type, title, url, snippet, result.get("score")),
                })

            candidates.sort(key=lambda item: item["score"], reverse=True)
            if not candidates:
                not_found.append(doc_type)
                continue

            best = candidates[0]
            extract_response = tavily.extract(urls=[best["url"]], extract_depth="advanced")
            extracted_results = extract_response.get("results", [])
            if not extracted_results:
                not_found.append(doc_type)
                continue

            raw_text = extracted_results[0].get("raw_content", "") or ""
            sections = _extract_named_sections(raw_text)
            documents.append({
                "doc_type": doc_type, "title": best["title"], "url": best["url"],
                "domain": _hostname(best["url"]), "text_length": len(raw_text),
                "sections": sections, "preview": " ".join(raw_text.split())[:1600],
            })

        section_matrix = {}
        for section_name in SECTION_ALIASES:
            section_matrix[section_name] = {}
            for doc in documents:
                section_matrix[section_name][doc["doc_type"]] = {
                    "present": doc["sections"].get(section_name, {}).get("present", False),
                    "section_length": doc["sections"].get(section_name, {}).get("section_length", 0),
                    "excerpt": doc["sections"].get(section_name, {}).get("excerpt", ""),
                }

        return {
            "error": False,
            "data": {
                "company_name": company_name,
                "documents_found": [doc["doc_type"] for doc in documents],
                "documents_not_found": not_found,
                "documents": documents,
                "section_matrix": section_matrix,
                "transition_notes": _build_transition_notes(documents),
            }
        }
    except Exception as exc:
        return {"error": True, "message": str(exc)}

@mcp.tool()
def doc_list_collections() -> dict:
    """List available document vector collections and their statistics in Qdrant."""
    try:
        client = _get_qdrant()
        collections = client.get_collections().collections
        info = []
        for c in collections:
            detail = client.get_collection(c.name)
            info.append({
                "name": c.name,
                "points_count": detail.points_count,
                "vectors_count": detail.vectors_count,
                "status": str(detail.status),
            })
        return {"error": False, "data": {"collections": info}}
    except Exception as exc:
        return {"error": True, "message": str(exc)}

# ------------------------------------------------------------------------------
# Entry Point
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting ORACLE OSINT & Data Discovery Engine MCP Server on Port 8003 ...")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8003)

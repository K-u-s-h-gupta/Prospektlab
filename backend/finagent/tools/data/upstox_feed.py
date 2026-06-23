"""Upstox WebSocket real-time market feed.

Connects to the Upstox Market Data Feed V3 (wss://api.upstox.com/v3/feed/market-data-feed)
and streams live ticks into an in-memory price cache.

During market hours (09:15 - 15:30 IST) this provides < 1 second latency.
Outside market hours it falls back to NSE/Yahoo polling.

Environment variables:
    UPSTOX_ACCESS_TOKEN   -  OAuth2 access token from Upstox developer portal
    UPSTOX_FEED_MODE      -  "ltpc" (default, price+change) or "full_d30_excluding_0_20"
    FINAGENT_REALTIME_FALLBACK_INTERVAL_S  -  polling interval when WS is down (default 5s)

Usage (singleton pattern):
    from finagent.tools.data.upstox_feed import market_feed
    await market_feed.start()                     # called in FastAPI lifespan
    snapshot = market_feed.get("NSE_EQ|INE002A01018")  # instant, O(1)
    snapshot = market_feed.get_by_symbol("RELIANCE")    # convenient alias
"""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import os
import struct
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger("finagent.upstox_feed")

# Upstox publishes a daily instrument master per exchange. The NSE file covers
# the whole equity universe (~2.4k EQ scrips) + every NSE index (~140), which
# together fit one LTPC websocket connection (5000-key cap). Subscribing the
# full universe means every tab (overview/portfolio/screener/watchlist) gets
# < 1s ticks for any Indian symbol with zero per-tab wiring.
_UNIVERSE_URL = os.getenv(
    "UPSTOX_UNIVERSE_URL",
    "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz",
)
# Hard ceiling on instruments subscribed in a single LTPC connection.
_MAX_SUBSCRIBE = int(os.getenv("UPSTOX_MAX_SUBSCRIBE", "4900") or 4900)
# Per-sub-message chunk size (keep each frame small).
_SUBSCRIBE_CHUNK = int(os.getenv("UPSTOX_SUBSCRIBE_CHUNK", "1500") or 1500)

# â”€â”€ Upstox instrument key registry â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Maps clean NSE/BSE symbol -> Upstox instrument_key
# Pattern: NSE_EQ|<ISIN>  or  NSE_INDEX|Nifty 50
# This covers the dashboard's default universe; symbols are added dynamically.
_INSTRUMENT_REGISTRY: dict[str, str] = {
    # â”€â”€ Indian Indices â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "^NSEI":       "NSE_INDEX|Nifty 50",
    "NIFTY50":     "NSE_INDEX|Nifty 50",
    "NIFTY 50":    "NSE_INDEX|Nifty 50",
    "^BSESN":      "BSE_INDEX|SENSEX",
    "SENSEX":      "BSE_INDEX|SENSEX",
    "^NSEBANK":    "NSE_INDEX|Nifty Bank",
    "NIFTYBANK":   "NSE_INDEX|Nifty Bank",
    "NIFTY BANK":  "NSE_INDEX|Nifty Bank",
    "^CNXIT":      "NSE_INDEX|Nifty IT",
    "NIFTYIT":     "NSE_INDEX|Nifty IT",
    "NIFTY IT":    "NSE_INDEX|Nifty IT",
    "MIDCAP50":    "NSE_INDEX|Nifty Midcap 50",
    "NIFTY100":    "NSE_INDEX|Nifty 100",
    "NIFTY500":    "NSE_INDEX|Nifty 500",
    "NIFTY MIDCAP 50": "NSE_INDEX|Nifty Midcap 50",
    # â”€â”€ Nifty 50 Large Caps â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    "RELIANCE":    "NSE_EQ|INE002A01018",
    "TCS":         "NSE_EQ|INE467B01029",
    "HDFCBANK":    "NSE_EQ|INE040A01034",
    "INFY":        "NSE_EQ|INE009A01021",
    "ICICIBANK":   "NSE_EQ|INE090A01021",
    "HINDUNILVR":  "NSE_EQ|INE030A01027",
    "ITC":         "NSE_EQ|INE154A01025",
    "KOTAKBANK":   "NSE_EQ|INE237A01028",
    "LT":          "NSE_EQ|INE018A01030",
    "SBIN":        "NSE_EQ|INE062A01020",
    "BHARTIARTL":  "NSE_EQ|INE397D01024",
    "AXISBANK":    "NSE_EQ|INE238A01034",
    "ASIANPAINT":  "NSE_EQ|INE021A01026",
    "MARUTI":      "NSE_EQ|INE585B01010",
    "SUNPHARMA":   "NSE_EQ|INE044A01036",
    "TATAMOTORS":  "NSE_EQ|INE155A01022",
    "WIPRO":       "NSE_EQ|INE075A01022",
    "NTPC":        "NSE_EQ|INE733E01010",
    "POWERGRID":   "NSE_EQ|INE752E01010",
    "ULTRACEMCO":  "NSE_EQ|INE481G01011",
    "BAJFINANCE":  "NSE_EQ|INE296A01024",
    "BAJAJFINSV":  "NSE_EQ|INE918I01026",
    "HCLTECH":     "NSE_EQ|INE860A01027",
    "TECHM":       "NSE_EQ|INE669C01036",
    "ADANIENT":    "NSE_EQ|INE423A01024",
    "JSWSTEEL":    "NSE_EQ|INE019A01038",
    "TATASTEEL":   "NSE_EQ|INE081A01020",
    "ONGC":        "NSE_EQ|INE213A01029",
    "M&M":         "NSE_EQ|INE101A01026",
    "NESTLEIND":   "NSE_EQ|INE239A01016",
    "GRASIM":      "NSE_EQ|INE047A01021",
    "INDUSINDBK":  "NSE_EQ|INE095A01012",
    "ZOMATO":      "NSE_EQ|INE758T01015",
    "ETERNAL":     "NSE_EQ|INE758T01015",
    "BRITANNIA":   "NSE_EQ|INE216A01030",
    "CIPLA":       "NSE_EQ|INE059A01026",
    "DIVISLAB":    "NSE_EQ|INE361B01024",
    "DRREDDY":     "NSE_EQ|INE089A01023",
    "EICHERMOT":   "NSE_EQ|INE066A01021",
    "BPCL":        "NSE_EQ|INE029A01011",
    "COALINDIA":   "NSE_EQ|INE522F01014",
    "APOLLOHOSP":  "NSE_EQ|INE437A01024",
    "TRENT":       "NSE_EQ|INE849A01020",
    "BAJAJ-AUTO":  "NSE_EQ|INE917I01010",
    "TITAN":       "NSE_EQ|INE280A01028",
    "HEROMOTOCO":  "NSE_EQ|INE158A01026",
    "SHREECEM":    "NSE_EQ|INE070A01015",
    "ADANIGREEN":  "NSE_EQ|INE364U01010",
    "ADANIPORTS":  "NSE_EQ|INE742F01042",
    "HINDALCO":    "NSE_EQ|INE038A01020",
    "VEDL":        "NSE_EQ|INE205A01025",
}

# â”€â”€ Price snapshot dataclass â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class PriceTick:
    symbol: str           # e.g. "RELIANCE"
    instrument_key: str   # e.g. "NSE_EQ|INE002A01018"
    price: float
    change: float         # absolute change
    change_pct: float     # percent change
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None       # previous close
    volume: int | None = None
    timestamp: float = field(default_factory=time.time)
    source: str = "upstox_ws"

    def age_seconds(self) -> float:
        return time.time() - self.timestamp

    def to_quote_dict(self) -> dict[str, Any]:
        """Returns the shape expected by /market/quotes consumers."""
        return {
            "symbol": self.symbol,
            "company_name": self.symbol,
            "price": self.price,
            "change": self.change,
            "change_pct": self.change_pct,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "prev_close": self.close,
            "volume": self.volume,
            "sector": "General",
            "source": self.source,
            "timestamp": self.timestamp,
        }

    def to_index_dict(self, display_name: str | None = None) -> dict[str, Any]:
        """Returns the shape expected by /market/indices consumers."""
        positive = self.change_pct >= 0
        return {
            "symbol": display_name or self.symbol,
            "value": f"{self.price:,.2f}",
            "change": f"({self.change:+.2f})",
            "changePct": self.change_pct,
            "sparkData": [],   # updated by feed manager
            "sourceTicker": self.instrument_key,
        }


# â”€â”€ IST market hours helper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _is_market_open() -> bool:
    """True if current IST time is within NSE/BSE regular trading hours."""
    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    if now_ist.weekday() >= 5:  # Sat/Sun
        return False
    t = now_ist.time()
    from datetime import time as dtime
    return dtime(9, 14) <= t <= dtime(15, 31)


# â”€â”€ Upstox WebSocket Feed Manager â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class UpstoxFeedManager:
    """Singleton that manages an Upstox WebSocket connection and an in-memory
    price cache. Exposes synchronous O(1) reads so REST endpoints return instantly.
    """

    _WS_URL = "wss://api.upstox.com/v3/feed/market-data-feed"
    _AUTH_URL = "https://api.upstox.com/v3/feed/market-data-feed/authorize"

    def __init__(self) -> None:
        self._prices: dict[str, PriceTick] = {}          # symbol -> tick
        self._ikey_to_symbol: dict[str, str] = {}         # instrument_key -> symbol
        self._symbol_to_ikey: dict[str, str] = {}         # symbol -> instrument_key
        self._sparklines: dict[str, list[float]] = {}     # symbol -> last 9 prices
        # queue -> interest set of UPPER symbols, or None = receive every tick.
        self._subscribers: dict[asyncio.Queue, set[str] | None] = {}
        self._running = False
        self._ws_connected = False
        self._task: asyncio.Task | None = None
        self._fallback_task: asyncio.Task | None = None
        self._fallback_interval = float(os.getenv("FINAGENT_REALTIME_FALLBACK_INTERVAL_S", "5"))
        self._mode = os.getenv("UPSTOX_FEED_MODE", "ltpc")
        # Full instrument-key universe to subscribe (filled by _load_universe).
        self._all_ikeys: list[str] = sorted(set(_INSTRUMENT_REGISTRY.values()))
        self._universe_loaded = False
        # Pre-populate both lookup dicts from the registry
        for sym, ikey in _INSTRUMENT_REGISTRY.items():
            self._symbol_to_ikey[sym.upper()] = ikey
            self._ikey_to_symbol[ikey] = sym.upper()

    # â”€â”€ Public read API (sync, O(1)) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def get(self, key: str) -> PriceTick | None:
        """Get tick by symbol, alias (e.g. ^NSEI) or instrument_key. None if uncached."""
        upper = key.upper()
        tick = self._prices.get(upper)
        if tick is not None:
            return tick
        # instrument_key -> symbol (direct)
        sym = self._ikey_to_symbol.get(key) or self._ikey_to_symbol.get(upper)
        if sym and sym in self._prices:
            return self._prices[sym]
        # alias symbol (^NSEI / NIFTY50) -> instrument_key -> canonical symbol
        ikey = self._symbol_to_ikey.get(upper)
        if ikey:
            sym2 = self._ikey_to_symbol.get(ikey)
            if sym2 and sym2 in self._prices:
                return self._prices[sym2]
        return None

    def get_by_symbol(self, symbol: str) -> PriceTick | None:
        return self.get(symbol)

    def get_all(self) -> dict[str, PriceTick]:
        return dict(self._prices)

    def get_sparkline(self, symbol: str) -> list[float]:
        return list(self._sparklines.get(symbol.upper(), []))

    @property
    def connected(self) -> bool:
        return self._ws_connected

    # â”€â”€ Lifecycle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        logger.info("UpstoxFeedManager starting")
        # Load the full NSE universe before connecting (non-fatal on failure).
        try:
            await self._load_universe()
        except Exception as exc:
            logger.warning("Instrument universe load failed (using registry only): %s", exc)
        self._task = asyncio.create_task(self._run_ws_loop(), name="upstox_ws")
        self._fallback_task = asyncio.create_task(self._run_fallback_loop(), name="upstox_fallback")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._fallback_task:
            self._fallback_task.cancel()
            try:
                await self._fallback_task
            except asyncio.CancelledError:
                pass
        logger.info("UpstoxFeedManager stopped")

    # â”€â”€ WebSocket push subscriber (for /ws/market endpoint) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def subscribe_queue(self, symbols: list[str] | None = None) -> asyncio.Queue:
        """Register a broadcast queue. `symbols` is the client's interest set  - 
        only matching ticks are pushed. None/empty = receive every tick."""
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subscribers[q] = self._norm_interest(symbols)
        return q

    def set_interest(self, q: asyncio.Queue, symbols: list[str] | None) -> None:
        """Update a queue's interest set (client sent a new subscribe frame)."""
        if q in self._subscribers:
            self._subscribers[q] = self._norm_interest(symbols)

    def _norm_interest(self, symbols: list[str] | None) -> set[str] | None:
        # None arg -> None = receive every tick (internal/admin use).
        # A list (even empty) -> a concrete set = receive only those symbols
        # (empty set = receive nothing until the client subscribes).
        if symbols is None:
            return None
        out: set[str] = set()
        for s in symbols:
            sym = str(s or "").strip().upper()
            sym = sym.removesuffix(".NS").removesuffix(".BO").removesuffix(".NSE").removesuffix(".BSE")
            if sym:
                out.add(sym)
                ikey = self._symbol_to_ikey.get(sym)
                canonical = self._ikey_to_symbol.get(ikey or "")
                if canonical:
                    out.add(canonical)
        return out

    def unsubscribe_queue(self, q: asyncio.Queue) -> None:
        self._subscribers.pop(q, None)

    def _broadcast(self, tick: PriceTick) -> None:
        if not self._subscribers:
            return
        msg = {"type": "tick", "data": tick.to_quote_dict()}
        sym = tick.symbol
        dead = []
        for q, interest in self._subscribers.items():
            if interest is not None and sym not in interest:
                continue
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.pop(q, None)

    # â”€â”€ Cache update â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _update_price(self, symbol: str, ikey: str, price: float,
                      change: float, change_pct: float,
                      open_: float | None = None,
                      high: float | None = None,
                      low: float | None = None,
                      close: float | None = None,
                      volume: int | None = None,
                      source: str = "upstox_ws") -> None:
        sym = symbol.upper()
        tick = PriceTick(
            symbol=sym,
            instrument_key=ikey,
            price=price,
            change=change,
            change_pct=change_pct,
            open=open_,
            high=high,
            low=low,
            close=close,
            volume=volume,
            source=source,
        )
        self._prices[sym] = tick
        # Update sparkline (keep last 9 points)
        sl = self._sparklines.setdefault(sym, [])
        sl.append(price)
        if len(sl) > 9:
            sl.pop(0)
        self._broadcast(tick)

    # â”€â”€ Upstox authorization â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _get_ws_url(self) -> str | None:
        """Call Upstox auth endpoint to get the authorized WebSocket URL."""
        token = _read_access_token()
        if not token:
            logger.warning("Upstox token not set (env or .upstox/access_token.txt)  -  WS feed disabled")
            return None
        try:
            import httpx
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(self._AUTH_URL, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    url = (data.get("data") or {}).get("authorizedRedirectUri") or self._WS_URL
                    logger.info("Upstox WS authorized: %s", url[:60])
                    return url
                else:
                    logger.warning("Upstox auth failed: %s %s", resp.status_code, resp.text[:200])
                    return None
        except Exception as exc:
            logger.error("Upstox auth error: %s", exc)
            return None

    # â”€â”€ WebSocket loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _run_ws_loop(self) -> None:
        """Persistent loop: connect -> subscribe -> stream ticks -> reconnect on error."""
        backoff = 2.0
        while self._running:
            ws_url = await self._get_ws_url()
            if not ws_url:
                # No token configured  -  sleep and retry (token may be added later)
                await asyncio.sleep(60)
                continue
            try:
                await self._connect_and_stream(ws_url)
                backoff = 2.0  # reset on clean exit
            except Exception as exc:
                logger.warning("Upstox WS error: %s  -  reconnecting in %.0fs", exc, backoff)
            finally:
                self._ws_connected = False
            if self._running:
                await asyncio.sleep(min(backoff, 60))
                backoff = min(backoff * 1.5, 60)

    async def _connect_and_stream(self, ws_url: str) -> None:
        try:
            import websockets
        except ImportError:
            logger.error("websockets not installed  -  pip install websockets")
            await asyncio.sleep(30)
            return

        token = _read_access_token()
        headers = [("Authorization", f"Bearer {token}")]

        logger.info("Connecting to Upstox WS: %s", ws_url[:60])
        async with websockets.connect(
            ws_url,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            self._ws_connected = True
            logger.info("Upstox WS connected âœ“")
            # Subscribe to all known instruments
            await self._send_subscription(ws)
            # Stream incoming messages
            async for message in ws:
                if not self._running:
                    break
                await self._handle_message(message)

    # â”€â”€ Instrument universe â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _universe_cache_path(self) -> Path:
        return _upstox_dir() / "nse_universe.json"

    async def _load_universe(self) -> None:
        """Download (or read cached) Upstox NSE instrument master and build the
        full symbolâ†”instrument_key maps + the subscription list. Cached per day
        on disk so we hit the network at most once daily."""
        rows = await asyncio.get_event_loop().run_in_executor(None, self._load_universe_sync)
        if not rows:
            return
        eq = idx = 0
        for r in rows:
            ikey = r.get("instrument_key")
            seg = r.get("segment")
            if not ikey or not seg:
                continue
            sym = (r.get("trading_symbol") or "").strip().upper()
            if seg == "NSE_EQ" and r.get("instrument_type") == "EQ" and sym:
                self._symbol_to_ikey.setdefault(sym, ikey)
                self._ikey_to_symbol.setdefault(ikey, sym)
                eq += 1
            elif seg == "NSE_INDEX" and sym:
                self._symbol_to_ikey.setdefault(sym, ikey)
                self._ikey_to_symbol.setdefault(ikey, sym)
                idx += 1
        # Build subscription list: registry first (indices w/ ^-aliases), then
        # the full equity universe, capped to the LTPC ceiling.
        ordered: list[str] = []
        seen: set[str] = set()
        for ikey in list(_INSTRUMENT_REGISTRY.values()) + list(self._ikey_to_symbol.keys()):
            if ikey not in seen:
                seen.add(ikey)
                ordered.append(ikey)
        self._all_ikeys = ordered[:_MAX_SUBSCRIBE]
        self._universe_loaded = True
        logger.info(
            "Upstox universe loaded: %d EQ + %d INDEX -> subscribing %d instruments",
            eq, idx, len(self._all_ikeys),
        )

    def _load_universe_sync(self) -> list[dict] | None:
        cache = self._universe_cache_path()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Reuse cache if written today.
        try:
            if cache.exists():
                blob = json.loads(cache.read_text(encoding="utf-8"))
                if blob.get("date") == today and isinstance(blob.get("rows"), list):
                    return blob["rows"]
        except Exception:
            pass
        try:
            import httpx
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                resp = client.get(_UNIVERSE_URL)
                resp.raise_for_status()
                raw = gzip.decompress(resp.content)
                rows = json.loads(raw)
            if isinstance(rows, list) and rows:
                try:
                    cache.write_text(json.dumps({"date": today, "rows": rows}), encoding="utf-8")
                except Exception:
                    pass
                return rows
        except Exception as exc:
            logger.warning("Upstox universe download failed: %s", exc)
            # Fall back to any stale cache.
            try:
                if cache.exists():
                    blob = json.loads(cache.read_text(encoding="utf-8"))
                    if isinstance(blob.get("rows"), list):
                        return blob["rows"]
            except Exception:
                pass
        return None

    async def _send_subscription(self, ws) -> None:
        """Subscribe to the full instrument universe in LTPC, chunked."""
        ikeys = self._all_ikeys or sorted(set(_INSTRUMENT_REGISTRY.values()))
        total = 0
        for i in range(0, len(ikeys), _SUBSCRIBE_CHUNK):
            chunk = ikeys[i:i + _SUBSCRIBE_CHUNK]
            payload = {
                "guid": "prospektlab-feed",
                "method": "sub",
                "data": {"mode": self._mode, "instrumentKeys": chunk},
            }
            await ws.send(json.dumps(payload).encode("utf-8"))
            total += len(chunk)
        logger.info("Subscribed to %d Upstox instruments (mode=%s, %d frames)",
                    total, self._mode, (len(ikeys) + _SUBSCRIBE_CHUNK - 1) // _SUBSCRIBE_CHUNK)

    async def _handle_message(self, message: bytes | str) -> None:
        """Parse incoming Upstox feed message (JSON or Protobuf binary)."""
        try:
            if isinstance(message, bytes):
                # Try JSON first (some modes send JSON)
                try:
                    data = json.loads(message.decode("utf-8"))
                    self._parse_json_feed(data)
                    return
                except (UnicodeDecodeError, json.JSONDecodeError):
                    pass
                # Protobuf binary  -  try to decode
                self._parse_binary_feed(message)
            else:
                data = json.loads(message)
                self._parse_json_feed(data)
        except Exception as exc:
            logger.debug("Feed message parse error: %s", exc)

    def _parse_json_feed(self, data: dict) -> None:
        """Parse Upstox JSON market data feed."""
        feeds = data.get("feeds") or {}
        for ikey, feed_data in feeds.items():
            try:
                ltpc = (feed_data.get("ltpc") or
                        feed_data.get("ff", {}).get("marketFF", {}).get("ltpc") or
                        {})
                ltp = _safe_float(ltpc.get("ltp") or ltpc.get("cp"))
                if ltp is None:
                    continue
                cp = _safe_float(ltpc.get("cp") or ltpc.get("close"))
                change = ltp - cp if (cp and cp != 0) else 0.0
                change_pct = (change / cp * 100.0) if cp and cp != 0 else 0.0

                # Optional OHLCV from full feed
                ohlcv = (feed_data.get("ohlcv") or
                         feed_data.get("ff", {}).get("marketFF", {}).get("marketOHLC", {}).get("ohlc", [{}]))
                ohlc = ohlcv[0] if isinstance(ohlcv, list) and ohlcv else (ohlcv if isinstance(ohlcv, dict) else {})

                sym = self._ikey_to_symbol.get(ikey, ikey.split("|")[-1].upper())
                self._symbol_to_ikey[sym] = ikey
                self._ikey_to_symbol[ikey] = sym

                self._update_price(
                    symbol=sym,
                    ikey=ikey,
                    price=ltp,
                    change=change,
                    change_pct=round(change_pct, 4),
                    open_=_safe_float(ohlc.get("open") or ohlc.get("o")),
                    high=_safe_float(ohlc.get("high") or ohlc.get("h")),
                    low=_safe_float(ohlc.get("low") or ohlc.get("l")),
                    close=cp,
                    volume=_safe_int(feed_data.get("volume") or ohlc.get("vol")),
                    source="upstox_ws",
                )
            except Exception as exc:
                logger.debug("Feed parse error for %s: %s", ikey, exc)

    def _parse_binary_feed(self, data: bytes) -> None:
        """Decode an Upstox V3 protobuf FeedResponse (LTPC mode) into the cache.

        Upstox V3 streams protobuf binary only  -  the vendored MarketDataFeedV3_pb2
        (compiled from the official .proto) is required. Without it, ticks are
        silently dropped, so the import failure is logged once."""
        proto = _load_proto()
        if proto is None:
            return
        try:
            msg = proto.FeedResponse()
            msg.ParseFromString(data)
        except Exception as exc:
            logger.debug("protobuf parse error: %s", exc)
            return
        for ikey, feed in msg.feeds.items():
            try:
                # LTPC may live directly on the Feed (ltpc mode) or nested inside
                # fullFeed (marketFF / indexFF) when a fuller mode is requested.
                ltpc = None
                ohlc_list = []
                which = feed.WhichOneof("FeedUnion")
                if which == "ltpc":
                    ltpc = feed.ltpc
                elif which == "fullFeed":
                    ff = feed.fullFeed
                    if ff.WhichOneof("FullFeedUnion") == "marketFF":
                        ltpc = ff.marketFF.ltpc
                        ohlc_list = list(ff.marketFF.marketOHLC.ohlc)
                    elif ff.WhichOneof("FullFeedUnion") == "indexFF":
                        ltpc = ff.indexFF.ltpc
                        ohlc_list = list(ff.indexFF.marketOHLC.ohlc)
                elif which == "firstLevelWithGreeks":
                    ltpc = feed.firstLevelWithGreeks.ltpc
                if ltpc is None:
                    continue
                ltp = ltpc.ltp
                cp = ltpc.cp
                if ltp <= 0:
                    continue
                change = ltp - cp if cp else 0.0
                change_pct = (change / cp * 100.0) if cp else 0.0
                # Prefer the day ("1d") OHLC bar when present.
                o = h = l = None
                vol = None
                for bar in ohlc_list:
                    if bar.interval in ("1d", "I1", "day", ""):
                        o, h, l = bar.open or None, bar.high or None, bar.low or None
                        vol = bar.vol or None
                        break
                sym = self._ikey_to_symbol.get(ikey, ikey.split("|")[-1].upper())
                self._symbol_to_ikey.setdefault(sym, ikey)
                self._update_price(
                    symbol=sym, ikey=ikey, price=ltp,
                    change=change, change_pct=round(change_pct, 4),
                    open_=o, high=h, low=l, close=cp, volume=vol,
                    source="upstox_ws",
                )
            except Exception as exc:
                logger.debug("feed decode error for %s: %s", ikey, exc)

    # â”€â”€ Fallback HTTP polling (when WS is down or off-hours) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _interested_symbols(self) -> set[str]:
        """Union of all connected clients' interest sets  -  the only symbols
        worth gap-filling (bounds work against the ~2.5k universe)."""
        interested: set[str] = set()
        for interest in self._subscribers.values():
            if interest:
                interested |= interest
        return interested

    def _indices_need_fallback(self) -> bool:
        """True when the core india indices aren't being kept fresh by the WS."""
        t = self.get_by_symbol("NIFTY 50")
        return t is None or t.age_seconds() > 8

    async def _run_fallback_loop(self) -> None:
        """Fill gaps when the WS isn't supplying data.

        Two layers:
          1. NSE `allIndices` bulk poll  -  keeps india indices live with NO token.
          2. Per-symbol NSE/Yahoo poll, bounded to symbols clients subscribed to.
        """
        while self._running:
            try:
                await asyncio.sleep(self._fallback_interval)
                if not self._running:
                    break
                market_open = _is_market_open()

                # 1) Bulk NSE indices (token-free) when WS isn't feeding them.
                if market_open and self._indices_need_fallback():
                    await self._poll_nse_indices()

                # 2) Per-symbol gap fill  -  only symbols clients actually want.
                interested = self._interested_symbols()
                stale = [
                    s for s in interested
                    if s not in self._prices or self._prices[s].age_seconds() > 15
                ]
                targets = stale[:30]
                if not targets:
                    continue
                if not market_open:
                    await self._poll_yahoo(targets[:10])
                elif not self._ws_connected:
                    await self._poll_nse(targets[:20])
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Fallback poll error: %s", exc)

    async def _poll_nse_indices(self) -> None:
        """Refresh india indices from NSE `allIndices` (no broker token needed)."""
        try:
            from finagent.tools.data.nse_bulk import fetch_nse_indices
            rows = await fetch_nse_indices()
        except Exception as exc:
            logger.debug("NSE indices fallback error: %s", exc)
            return
        for r in rows:
            sym = r["symbol"]
            existing = self._prices.get(sym)
            # Never clobber a fresh Upstox tick.
            if existing is not None and existing.source == "upstox_ws" and existing.age_seconds() < 10:
                continue
            ikey = self._symbol_to_ikey.get(sym, f"NSE_INDEX|{sym}")
            self._update_price(
                symbol=sym, ikey=ikey, price=r["price"],
                change=r.get("change") or 0.0, change_pct=r.get("change_pct") or 0.0,
                open_=r.get("open"), close=r.get("previousClose"),
                source="nse_bulk",
            )

    async def _poll_nse(self, symbols: list[str]) -> None:
        """Poll NSE API for missing/stale symbols."""
        try:
            from finagent.tools.data.india import fetch_nse_snapshot
            for sym in symbols[:10]:
                try:
                    snap = await asyncio.wait_for(fetch_nse_snapshot(sym), timeout=3.0)
                    if snap and snap.current_price is not None:
                        ikey = self._symbol_to_ikey.get(sym, f"NSE_EQ|{sym}")
                        self._update_price(
                            symbol=sym,
                            ikey=ikey,
                            price=snap.current_price,
                            change=0.0,
                            change_pct=snap.change_pct or 0.0,
                            source="nse_poll",
                        )
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("NSE poll error: %s", exc)

    async def _poll_yahoo(self, symbols: list[str]) -> None:
        """Poll Yahoo Finance for off-hours/crypto prices."""
        try:
            from finagent.tools.data.yahoo_finance import fetch_yahoo_quote
            for sym in symbols[:5]:
                try:
                    ikey = self._symbol_to_ikey.get(sym, "")
                    # Pick correct Yahoo ticker
                    if "INDEX" in ikey:
                        candidates = [_YAHOO_INDEX_MAP.get(sym, sym)]
                    else:
                        candidates = [f"{sym}.NS", f"{sym}.BO", sym]
                    for candidate in candidates:
                        q = await asyncio.wait_for(
                            fetch_yahoo_quote(candidate, timeout_s=6.0, cache_ttl_s=30.0),
                            timeout=7.0,
                        )
                        if q and q.price is not None:
                            self._update_price(
                                symbol=sym,
                                ikey=ikey or f"NSE_EQ|{sym}",
                                price=q.price,
                                change=q.price - (q.previous_close or q.price),
                                change_pct=q.change_pct or 0.0,
                                close=q.previous_close,
                                source="yahoo_poll",
                            )
                            break
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("Yahoo poll error: %s", exc)

    # â”€â”€ Dynamic subscription â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def register_symbol(self, symbol: str, isin: str | None = None, exchange: str = "NSE_EQ") -> str | None:
        """Register a new symbol so it gets subscribed next time WS connects."""
        sym = symbol.upper()
        if sym in self._symbol_to_ikey:
            return self._symbol_to_ikey[sym]
        if isin:
            ikey = f"{exchange}|{isin}"
            self._symbol_to_ikey[sym] = ikey
            self._ikey_to_symbol[ikey] = sym
            return ikey
        return None


# â”€â”€ Yahoo index ticker map (for off-hours fallback) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_YAHOO_INDEX_MAP = {
    "^NSEI": "^NSEI", "NIFTY50": "^NSEI", "NIFTY 50": "^NSEI",
    "^BSESN": "^BSESN", "SENSEX": "^BSESN",
    "^NSEBANK": "^NSEBANK", "NIFTYBANK": "^NSEBANK",
    "^CNXIT": "^CNXIT", "NIFTYIT": "^CNXIT",
    "^GSPC": "^GSPC", "S&P 500": "^GSPC",
    "^IXIC": "^IXIC", "NASDAQ": "^IXIC",
    "^DJI": "^DJI", "DOW": "^DJI",
    "^VIX": "^VIX", "VIX": "^VIX",
    "BTC-USD": "BTC-USD", "BTC": "BTC-USD",
    "ETH-USD": "ETH-USD", "ETH": "ETH-USD",
    "SOL-USD": "SOL-USD", "SOL": "SOL-USD",
    "XRP-USD": "XRP-USD", "XRP": "XRP-USD",
    "USDINR=X": "USDINR=X", "USD/INR": "USDINR=X",
    "CL=F": "CL=F", "CRUDE OIL": "CL=F",
    "GC=F": "GC=F", "GOLD": "GC=F",
}


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _upstox_dir() -> Path:
    """Local state dir for the universe cache + auto-generated access token."""
    base = os.getenv("UPSTOX_CACHE_DIR")
    root = Path(base) if base else (Path(__file__).resolve().parents[4] / ".upstox")
    root.mkdir(parents=True, exist_ok=True)
    return root


def token_file_path() -> Path:
    """Where scripts/upstox_token.py writes the daily TOTP-generated token."""
    return _upstox_dir() / "access_token.txt"


def _read_access_token() -> str:
    """Resolve the Upstox access token: env var first, then the token file
    written by the daily TOTP job. Read fresh each reconnect so a refreshed
    token is picked up without a gateway restart."""
    tok = os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()
    if tok:
        return tok
    try:
        p = token_file_path()
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


_PROTO_MODULE: Any = None
_PROTO_TRIED = False


def _load_proto() -> Any:
    """Lazy-import the vendored Upstox V3 protobuf module (compiled from the
    official .proto). Cached; warns exactly once if unavailable."""
    global _PROTO_MODULE, _PROTO_TRIED
    if _PROTO_MODULE is not None or _PROTO_TRIED:
        return _PROTO_MODULE
    _PROTO_TRIED = True
    try:
        from finagent.tools.data import MarketDataFeedV3_pb2 as proto  # type: ignore
        _PROTO_MODULE = proto
    except Exception:
        try:
            import MarketDataFeedV3_pb2 as proto  # type: ignore
            _PROTO_MODULE = proto
        except Exception as exc:
            logger.error(
                "MarketDataFeedV3_pb2 not importable  -  Upstox V3 ticks cannot be "
                "decoded. Compile the proto: %s", exc,
            )
    return _PROTO_MODULE


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if f != f else f  # NaN guard
    except (TypeError, ValueError):
        return None


def _safe_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


# â”€â”€ Singleton â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
market_feed = UpstoxFeedManager()


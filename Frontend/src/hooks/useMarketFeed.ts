/**
 * useMarketFeed  -  Real-time market price hook via WebSocket
 *
 * Connects to /ws/market (Upstox WebSocket relay on the backend).
 * On connection, receives a full snapshot of all known prices, then
 * individual ticks as prices change.
 *
 * Falls back to HTTP polling (getMarketQuotes / getMarketIndices) if:
 *   - WebSocket connection fails
 *   - Browser tab is hidden
 *   - WS disconnects and can't reconnect within 5s
 *
 * Usage:
 *   const { prices, indexData, connected, feedSource } = useMarketFeed(symbols);
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { getMarketQuotes, getMarketIndices } from '../api/client';
import { getRuntimeMarketDataWebSocketUrl } from '../utils/runtimeConfig';

export interface PriceSnapshot {
  symbol: string;
  price: number;
  change: number;
  change_pct: number;
  company_name?: string;
  sector?: string;
  source?: string;
  timestamp?: number;
}

export interface IndexSnapshot {
  symbol: string;
  value: string;
  change: string;
  changePct: number;
  sparkData: number[];
  sourceTicker?: string;
  kind?: string;
  liveSource?: string;
}

export interface MarketFeedState {
  /** Map of SYMBOL -> live price data */
  prices: Record<string, PriceSnapshot>;
  /** Map of category -> index rows (same shape as /market/indices) */
  indexData: Record<string, IndexSnapshot[]>;
  /** True when WebSocket is connected to backend */
  connected: boolean;
  /** "websocket" when feed is live, "polling" when falling back to HTTP */
  feedSource: 'websocket' | 'polling';
  /** Seconds since last price update (useful for freshness badge) */
  lastUpdateAge: number;
}

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 15000];
const POLL_INTERVAL_MS = 5000;   // fallback HTTP polling when WS is down
const INDEX_POLL_MS   = 10000;  // fallback index polling; WS ticks update immediately

const UPSTOX_INDEX_SUBSCRIPTIONS = [
  '^NSEI', 'NIFTY50', 'NIFTY 50',
  '^BSESN', 'SENSEX',
  '^NSEBANK', 'NIFTYBANK', 'NIFTY BANK',
  '^CNXIT', 'NIFTYIT', 'NIFTY IT',
  'MIDCAP50', 'NIFTY MIDCAP 50',
  'NIFTY100', 'NIFTY 100',
  'NIFTY500', 'NIFTY 500',
];

const INDEX_TICK_META: Record<string, { kind: string; display: string; sourceTicker: string; order: number }> = {
  '^NSEI': { kind: 'india', display: 'NIFTY 50', sourceTicker: '^NSEI', order: 0 },
  NIFTY50: { kind: 'india', display: 'NIFTY 50', sourceTicker: '^NSEI', order: 0 },
  'NIFTY 50': { kind: 'india', display: 'NIFTY 50', sourceTicker: '^NSEI', order: 0 },
  '^BSESN': { kind: 'india', display: 'SENSEX', sourceTicker: '^BSESN', order: 1 },
  SENSEX: { kind: 'india', display: 'SENSEX', sourceTicker: '^BSESN', order: 1 },
  '^NSEBANK': { kind: 'india', display: 'NIFTY BANK', sourceTicker: '^NSEBANK', order: 2 },
  NIFTYBANK: { kind: 'india', display: 'NIFTY BANK', sourceTicker: '^NSEBANK', order: 2 },
  'NIFTY BANK': { kind: 'india', display: 'NIFTY BANK', sourceTicker: '^NSEBANK', order: 2 },
  '^CNXIT': { kind: 'india', display: 'NIFTY IT', sourceTicker: '^CNXIT', order: 3 },
  NIFTYIT: { kind: 'india', display: 'NIFTY IT', sourceTicker: '^CNXIT', order: 3 },
  'NIFTY IT': { kind: 'india', display: 'NIFTY IT', sourceTicker: '^CNXIT', order: 3 },
  MIDCAP50: { kind: 'india', display: 'NIFTY MIDCAP 50', sourceTicker: 'MIDCAP50', order: 4 },
  'NIFTY MIDCAP 50': { kind: 'india', display: 'NIFTY MIDCAP 50', sourceTicker: 'MIDCAP50', order: 4 },
  NIFTY100: { kind: 'india', display: 'NIFTY 100', sourceTicker: 'NIFTY100', order: 5 },
  'NIFTY 100': { kind: 'india', display: 'NIFTY 100', sourceTicker: 'NIFTY100', order: 5 },
  NIFTY500: { kind: 'india', display: 'NIFTY 500', sourceTicker: 'NIFTY500', order: 6 },
  'NIFTY 500': { kind: 'india', display: 'NIFTY 500', sourceTicker: 'NIFTY500', order: 6 },
};

interface MarketFeedOptions {
  includeIndices?: boolean;
  pollIndices?: boolean;
}

function normalizeFeedSymbol(value: string): string {
  return String(value || '').trim().toUpperCase()
    .replace(/\.(NS|BO|NSE|BSE)$/i, '');
}

function buildSubscriptionSymbols(symbols: string[], includeIndices: boolean): string[] {
  const out = new Set<string>();
  if (includeIndices) {
    UPSTOX_INDEX_SUBSCRIPTIONS.forEach((symbol) => out.add(symbol));
  }
  symbols.forEach((symbol) => {
    const clean = normalizeFeedSymbol(symbol);
    if (clean) out.add(clean);
  });
  return Array.from(out);
}

function indexMetaFor(symbol: string) {
  return INDEX_TICK_META[normalizeFeedSymbol(symbol)];
}

function formatIndexValue(price: number): string {
  return price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatIndexChange(change: number): string {
  if (!Number.isFinite(change)) return '--';
  return `(${change >= 0 ? '+' : ''}${change.toFixed(2)})`;
}

export function useMarketFeed(symbols: string[] = [], options: MarketFeedOptions = {}): MarketFeedState {
  const includeIndices = options.includeIndices !== false;
  const pollIndices = options.pollIndices ?? includeIndices;
  const subscriptionSymbols = buildSubscriptionSymbols(symbols, includeIndices);
  const subscriptionKey = subscriptionSymbols.join(',');
  const [prices, setPrices] = useState<Record<string, PriceSnapshot>>({});
  const [indexData, setIndexData] = useState<Record<string, IndexSnapshot[]>>({});
  const [connected, setConnected] = useState(false);
  const [feedSource, setFeedSource] = useState<'websocket' | 'polling'>('polling');
  const [lastUpdateAge, setLastUpdateAge] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempt = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectTimeoutTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const indexPollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastUpdateRef = useRef<number>(Date.now());
  const symbolsRef = useRef(symbols);
  const subscriptionSymbolsRef = useRef(subscriptionSymbols);
  const pollIndicesRef = useRef(pollIndices);
  symbolsRef.current = symbols;
  subscriptionSymbolsRef.current = subscriptionSymbols;
  pollIndicesRef.current = pollIndices;

  // -- Freshness ticker (30s granularity  -  avoids per-second re-renders) ----
  useEffect(() => {
    const ticker = setInterval(() => {
      setLastUpdateAge(Math.round((Date.now() - lastUpdateRef.current) / 1000));
    }, 30000);
    return () => clearInterval(ticker);
  }, []);

  // -- Apply an Upstox index tick directly to index rows ----------
  const applyIndexTick = useCallback((data: PriceSnapshot): boolean => {
    const meta = indexMetaFor(data?.symbol || '');
    const price = Number(data?.price);
    if (!meta || !Number.isFinite(price) || price <= 0) return false;

    const rawChangePct = Number(data.change_pct);
    const changePct = Number.isFinite(rawChangePct) ? rawChangePct : 0;
    const rawChange = Number(data.change);
    const change = Number.isFinite(rawChange) ? rawChange : price * (changePct / 100);

    setIndexData((prev) => {
      const currentRows = Array.isArray(prev[meta.kind]) ? prev[meta.kind] : [];
      const existing = currentRows.find((row) => normalizeFeedSymbol(row.symbol) === normalizeFeedSymbol(meta.display));
      const sparkData = [...(existing?.sparkData || []), price].slice(-9);
      const nextRow: IndexSnapshot = {
        symbol: meta.display,
        value: formatIndexValue(price),
        change: formatIndexChange(change),
        changePct,
        sparkData,
        sourceTicker: meta.sourceTicker,
        kind: meta.kind,
        liveSource: data.source || 'upstox_ws',
      };
      const nextRows = existing
        ? currentRows.map((row) => normalizeFeedSymbol(row.symbol) === normalizeFeedSymbol(meta.display) ? nextRow : row)
        : [...currentRows, nextRow];
      nextRows.sort((a, b) => (INDEX_TICK_META[normalizeFeedSymbol(a.symbol)]?.order ?? 99) - (INDEX_TICK_META[normalizeFeedSymbol(b.symbol)]?.order ?? 99));
      return { ...prev, [meta.kind]: nextRows };
    });
    return true;
  }, []);

  // -- Apply a price tick to state ---------------------------------------------
  const applyTick = useCallback((data: PriceSnapshot) => {
    if (!data?.symbol || data.price == null) return;
    applyIndexTick(data);
    lastUpdateRef.current = Date.now();
    setPrices(prev => {
      const sym = normalizeFeedSymbol(data.symbol);
      const existing = prev[sym];
      // Skip redundant updates (same price, same timestamp)
      if (existing?.price === data.price && existing?.timestamp === data.timestamp) {
        return prev;
      }
      return { ...prev, [sym]: { ...data, symbol: sym } };
    });
  }, [applyIndexTick]);

  // -- Apply a full snapshot (initial connection burst) ----------------------
  const applySnapshot = useCallback((snapshot: Record<string, PriceSnapshot>) => {
    if (!snapshot || typeof snapshot !== 'object') return;
    lastUpdateRef.current = Date.now();
    Object.values(snapshot).forEach((data) => applyIndexTick(data));
    setPrices(prev => {
      const next = { ...prev };
      for (const [sym, data] of Object.entries(snapshot)) {
        if (data?.price != null) {
          const clean = normalizeFeedSymbol(data.symbol || sym);
          next[clean] = { ...data, symbol: clean };
        }
      }
      return next;
    });
  }, [applyIndexTick]);

  // -- Send this tab's symbol interest to the backend --------------------------
  const sendSubscribe = useCallback((syms: string[]) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    try {
      ws.send(JSON.stringify({ action: 'subscribe', symbols: syms }));
    } catch { /* socket closing */ }
  }, []);

  // -- HTTP fallback polling -------------------------------------------------
  const pollQuotesOnce = useCallback(async () => {
    const syms = symbolsRef.current;
    if (!syms.length) return;
    try {
      const data = await getMarketQuotes(syms);
      if (data) {
        lastUpdateRef.current = Date.now();
        setPrices(prev => {
          const next = { ...prev };
          for (const [sym, q] of Object.entries(data as Record<string, any>)) {
            const price = Number(q.price);
            if (!Number.isFinite(price) || price <= 0) continue;
            const changePct = Number.isFinite(Number(q.change_pct)) ? Number(q.change_pct) : 0;
            next[sym.toUpperCase()] = {
              symbol: sym.toUpperCase(),
              price,
              change: q.change ?? price * (changePct / 100),
              change_pct: changePct,
              company_name: q.company_name,
              sector: q.sector,
              source: q.source || 'http_poll',
              timestamp: q.timestamp,
            };
          }
          return next;
        });
      }
    } catch { /* silent */ }
  }, []);

  const startFallbackPolling = useCallback(() => {
    setFeedSource('polling');
    pollQuotesOnce();
    if (pollTimer.current) return; // already running
    pollTimer.current = setInterval(() => {
      pollQuotesOnce();
    }, POLL_INTERVAL_MS);
  }, [pollQuotesOnce]);
  // -- WebSocket connection ----------------------------------------------------
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN ||
        wsRef.current?.readyState === WebSocket.CONNECTING) return;

    try {
      const wsUrl = getRuntimeMarketDataWebSocketUrl('/ws/market', 'http://localhost:8000');
      if (!wsUrl) {
        setConnected(false);
        startFallbackPolling();
        return;
      }
      // Production WebSocket routes can fail slowly through proxies/API gateways;
      // keep the HTTP quote stream hot until the socket actually opens.
      startFallbackPolling();
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      if (connectTimeoutTimer.current) clearTimeout(connectTimeoutTimer.current);
      connectTimeoutTimer.current = setTimeout(() => {
        if (ws.readyState === WebSocket.CONNECTING) {
          ws.close();
        }
      }, 5000);

      ws.onopen = () => {
        if (connectTimeoutTimer.current) {
          clearTimeout(connectTimeoutTimer.current);
          connectTimeoutTimer.current = null;
        }
        setConnected(true);
        setFeedSource('websocket');
        reconnectAttempt.current = 0;
        // Tell the backend which symbols this tab needs (interest filter).
        sendSubscribe(subscriptionSymbolsRef.current);
        // Stop fallback polling  -  WS is live
        if (pollTimer.current) { clearInterval(pollTimer.current); pollTimer.current = null; }
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'tick' && msg.data) {
            applyTick(msg.data);
          } else if (msg.type === 'snapshot' && msg.data) {
            applySnapshot(msg.data);
          }
          // heartbeat / connected messages  -  no action needed
        } catch {
          // ignore malformed frames
        }
      };

      ws.onclose = () => {
        if (connectTimeoutTimer.current) {
          clearTimeout(connectTimeoutTimer.current);
          connectTimeoutTimer.current = null;
        }
        setConnected(false);
        wsRef.current = null;
        scheduleReconnect();
        // Start HTTP fallback while reconnecting
        startFallbackPolling();
      };

      ws.onerror = () => {
        if (connectTimeoutTimer.current) {
          clearTimeout(connectTimeoutTimer.current);
          connectTimeoutTimer.current = null;
        }
        ws.close();
      };
    } catch {
      scheduleReconnect();
      startFallbackPolling();
    }
  }, [applyTick, applySnapshot]); // eslint-disable-line react-hooks/exhaustive-deps

  const scheduleReconnect = useCallback(() => {
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    const delay = RECONNECT_DELAYS[Math.min(reconnectAttempt.current, RECONNECT_DELAYS.length - 1)];
    reconnectAttempt.current += 1;
    reconnectTimer.current = setTimeout(connect, delay);
  }, [connect]);

  // -- Index data polling -----------------------------------------------------
  const fetchIndices = useCallback(async () => {
    if (!pollIndicesRef.current) return;
    try {
      const data = await getMarketIndices();
      if (data && typeof data === 'object') {
        setIndexData(data);
        lastUpdateRef.current = Date.now();
      }
    } catch { /* silent */ }
  }, []);

  // -- Startup + visibility handling -----------------------------------------
  useEffect(() => {
    connect();
    fetchIndices();

    // Poll indices as a fallback; Upstox websocket ticks update them immediately.
    if (pollIndicesRef.current) {
      indexPollTimer.current = setInterval(fetchIndices, INDEX_POLL_MS);
    }

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        // Re-connect WS and refresh data when tab becomes visible
        connect();
        fetchIndices();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);

    return () => {
      // Cleanup on unmount
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (connectTimeoutTimer.current) clearTimeout(connectTimeoutTimer.current);
      if (pollTimer.current) clearInterval(pollTimer.current);
      if (indexPollTimer.current) clearInterval(indexPollTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent reconnect loop on intentional unmount
        wsRef.current.close();
      }
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!pollIndices) {
      if (indexPollTimer.current) {
        clearInterval(indexPollTimer.current);
        indexPollTimer.current = null;
      }
      return;
    }
    fetchIndices();
    if (!indexPollTimer.current) {
      indexPollTimer.current = setInterval(fetchIndices, INDEX_POLL_MS);
    }
  }, [pollIndices, fetchIndices]);

  // -- Re-subscribe when symbol list changes ---------------------------------
  // (WS auto-sends all prices; this ensures HTTP fallback covers new symbols)
  useEffect(() => {
    if (connected) {
      // WS is live  -  update the backend interest filter for the new symbols.
      sendSubscribe(subscriptionSymbolsRef.current);
    } else if (symbols.length > 0) {
      // Fallback mode  -  trigger an immediate HTTP fetch for new symbols
      getMarketQuotes(symbols).then(data => {
        if (data) applySnapshot(data as Record<string, PriceSnapshot>);
      }).catch(() => {});
    }
  }, [subscriptionKey, connected]); // eslint-disable-line react-hooks/exhaustive-deps

  return { prices, indexData, connected, feedSource, lastUpdateAge };
}

/**
 * Converts raw prices map into the quote shape that existing dashboard
 * components expect (same as what getMarketQuotes returned previously).
 */
export function pricesToQuotesData(prices: Record<string, PriceSnapshot>): Record<string, any> {
  const out: Record<string, any> = {};
  for (const [sym, p] of Object.entries(prices)) {
    const row = {
      symbol: p.symbol,
      company_name: p.company_name || p.symbol,
      price: p.price,
      change_pct: p.change_pct,
      sector: p.sector || 'General',
      source: p.source,
    };
    out[sym] = row;
    // Also expose with suffixes so existing consumers find them
    out[`${sym}.NS`] = row;
    out[`${sym}.BO`] = row;
  }
  return out;
}



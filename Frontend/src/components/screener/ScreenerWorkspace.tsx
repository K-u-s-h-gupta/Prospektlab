import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowUpRight,
  Building2,
  CandlestickChart,
  CircleDot,
  Gauge,
  RefreshCw,
  Search,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { AppShell } from '../layout/AppShell';
import {
  ScreenerSearchItem,
  getScreenerAnalysis,
  getScreenerFinancials,
  screenerSearch,
} from '../../api/client';
import { useMarketFeed } from '../../hooks/useMarketFeed';
import '../../styles/screener.css';

type ScreenerViewTab = 'overview' | 'fundamentals' | 'technicals' | 'events';
type FundamentalSegment = 'ratios' | 'income_statement' | 'balance_sheet' | 'cash_flow';

interface ScreenerWorkspaceProps {
  embedded?: boolean;
}

const SEARCH_DEBOUNCE_MS = 250;
const DEFAULT_SCREENER_SYMBOL = 'RELIANCE';

const CRORE = 10_000_000;
const LAKH = 100_000;

/* ─── Formatters ─────────────────────────────────────────────────────────── */

const fmtNum = (value: any, digits = 2): string => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return n.toFixed(digits);
};

const fmtPct = (value: any, digits = 2): string => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `${n.toFixed(digits)}%`;
};

const fmtInr = (value: any, digits = 2): string => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: digits })}`;
};

// Expects value already expressed in INR crores
const fmtCrore = (value: any, digits = 2): string => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: digits })} cr`;
};

const fmtVolume = (value: any): string => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= CRORE) return `${(abs / CRORE).toFixed(2)} cr`;
  if (abs >= LAKH) return `${(abs / LAKH).toFixed(2)} L`;
  if (abs >= 1000) return `${(abs / 1000).toFixed(1)}k`;
  return n.toLocaleString('en-IN');
};

// value is in INR crores (isInCrores=true) or raw INR (default)
const fmtMarketCap = (value: any, isInCrores = false): string => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  const crores = isInCrores ? n : n / CRORE;
  if (crores >= 100_000) return `₹${(crores / 100_000).toFixed(2)} L cr`;
  return `₹${crores.toLocaleString('en-IN', { maximumFractionDigits: 2 })} cr`;
};

const trendTone = (value: any): 'up' | 'down' | 'neutral' => {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'neutral';
  return n >= 0 ? 'up' : 'down';
};

const getArray = (value: any): any[] => (Array.isArray(value) ? value : []);

const displayText = (value: any, fallback = '—'): string =>
  String(value ?? '').trim() || fallback;

// Handles both object {label: string} and plain string sentiment shapes
const sentimentLabel = (value: any): string => {
  if (!value) return 'neutral';
  if (typeof value === 'string') return value.toLowerCase() || 'neutral';
  return String(value?.label || '').toLowerCase() || 'neutral';
};

const sentimentTone = (value: any): 'positive' | 'negative' | 'neutral' => {
  const lbl = sentimentLabel(value);
  if (lbl === 'positive') return 'positive';
  if (lbl === 'negative') return 'negative';
  return 'neutral';
};

const formatEventPublished = (value: any): string =>
  String(value ?? '').trim() || '—';

const formatRatioValue = (item: any): string => {
  if (item?.display) return String(item.display);
  const unit = String(item?.unit || '').toLowerCase();
  if (unit.includes('%')) return fmtPct(item?.value, 2);
  if (unit.includes('crore') || unit.includes('cr')) return fmtCrore(item?.value, 2);
  if (unit.includes('inr') || unit.includes('rs') || unit.includes('₹')) return fmtInr(item?.value, 2);
  if (unit.includes('times') || unit.includes('x')) return `${fmtNum(item?.value, 2)}x`;
  return fmtNum(item?.value, 2);
};

const formatSuggestionConfidence = (value: any): string => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '';
  return `${Math.round(n * 100)}%`;
};

// Contradiction severity helpers — backend emits "watch" | "high"
const contradictionTone = (severity: any): 'negative' | 'neutral' | 'positive' => {
  const s = String(severity || '').toLowerCase();
  if (s === 'high' || s === 'critical') return 'negative';
  if (s === 'medium' || s === 'moderate' || s === 'watch') return 'neutral';
  return 'positive';
};

const contradictionSeverityLabel = (item: any): string => {
  const s = String(item?.severity || item?.level || '').toLowerCase();
  if (s === 'high' || s === 'critical') return 'High';
  if (s === 'watch' || s === 'medium' || s === 'moderate') return 'Watch';
  if (s === 'low') return 'Low';
  return 'Note';
};

// Normalise event type/category string for keyword matching (strip delimiters + lowercase)
const normaliseEventType = (row: any): string =>
  String(row?.event_type || row?.category || row?.type || row?.title || '')
    .toLowerCase()
    .replace(/[-_ ]/g, '');

/* ─── Sparkline ───────────────────────────────────────────────────────────── */

const Sparkline: React.FC<{ prices: number[] }> = ({ prices }) => {
  const usable = prices.filter((p) => Number.isFinite(p));
  if (usable.length < 2) return <div className="screener-empty-inline">No price history available</div>;
  const W = 360, H = 84;
  const min = Math.min(...usable), max = Math.max(...usable);
  const span = max - min || 1;
  const pts = usable.map((p, i) => {
    const x = (i / (usable.length - 1)) * W;
    const y = H - ((p - min) / span) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const linePath = pts.map((pt, i) => `${i === 0 ? 'M' : 'L'} ${pt}`).join(' ');
  const areaPath = `${linePath} L ${W},${H} L 0,${H} Z`;
  const up = usable[usable.length - 1] >= usable[0];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="screener-sparkline" preserveAspectRatio="none">
      <path d={areaPath} fill={up ? 'rgba(52,211,153,0.14)' : 'rgba(251,113,133,0.14)'} />
      <path d={linePath} fill="none" stroke={up ? 'var(--profit)' : 'var(--loss)'} strokeWidth={2} />
    </svg>
  );
};

/* ─── Error boundary ─────────────────────────────────────────────────────── */

class ScreenerRenderBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError() { return { hasError: true }; }
  componentDidCatch(err: unknown) { console.error('Screener render failed', err); }
  render() {
    if (this.state.hasError)
      return <div className="screener-error">Screener view encountered a rendering error. Please refresh.</div>;
    return this.props.children;
  }
}

/* ─── Main component ─────────────────────────────────────────────────────── */

export const ScreenerWorkspace: React.FC<ScreenerWorkspaceProps> = ({ embedded = false }) => {
  // ── Search state ──────────────────────────────────────────────────────────
  const [searchText, setSearchText] = useState('');
  const [suggestions, setSuggestions] = useState<ScreenerSearchItem[]>([]);
  const [searchBusy, setSearchBusy] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [focusedIndex, setFocusedIndex] = useState(-1); // keyboard nav

  // ── Analysis state ───────────────────────────────────────────────────────
  const [activeSymbol, setActiveSymbol] = useState('');
  const [analysisPayload, setAnalysisPayload] = useState<any>(null);
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [analysisError, setAnalysisError] = useState('');

  // ── Financials state ─────────────────────────────────────────────────────
  const [financialsPayload, setFinancialsPayload] = useState<any>(null);
  const [financialsSymbol, setFinancialsSymbol] = useState('');
  const [financialsBusy, setFinancialsBusy] = useState(false);
  const [financialsError, setFinancialsError] = useState('');

  // ── Tab / segment state ───────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<ScreenerViewTab>('overview');
  const [fundamentalSegment, setFundamentalSegment] = useState<FundamentalSegment>('ratios');

  // ── Refs ──────────────────────────────────────────────────────────────────
  const loadGenRef = useRef(0);          // race-condition guard for loadCompany
  const financialsLoadingRef = useRef<string | null>(null); // guard for loadFinancials
  const searchAreaRef = useRef<HTMLDivElement>(null); // click-outside detection

  /* ─── Derived data ───────────────────────────────────────────────────────── */

  const snapshot = analysisPayload?.snapshot ?? null;
  const resolved = snapshot?.resolved ?? {};
  const score = snapshot?.score ?? {};
  // quote only carries: price, change_pct, currency, source, source_url
  const quote = snapshot?.quote ?? {};
  // All financial metrics live in fundamentals.metrics
  const fundamentals = snapshot?.fundamentals ?? {};
  const m = fundamentals?.metrics ?? {};
  const financialAnalytics = financialsPayload?.analytics ?? {};
  const technicals = snapshot?.technicals ?? {};
  const events = snapshot?.events ?? {};
  const summary = snapshot?.summary ?? {};
  const contradictions = getArray(snapshot?.contradictions);
  const peers = snapshot?.peers ?? {};

  // Real-time price feed (Upstox WebSocket → HTTP fallback)
  const { prices: livePrices } = useMarketFeed(activeSymbol ? [activeSymbol] : [], { includeIndices: false });
  const liveTick = activeSymbol ? livePrices[activeSymbol.toUpperCase()] : undefined;
  const livePrice = liveTick?.price ?? quote?.price;
  const liveChangePct = liveTick?.change_pct ?? quote?.change_pct;

  /* ─── Click-outside: close dropdown when user clicks away ────────────────── */
  useEffect(() => {
    const handle = (e: MouseEvent) => {
      if (searchAreaRef.current && !searchAreaRef.current.contains(e.target as Node)) {
        setSearchOpen(false);
        setFocusedIndex(-1);
      }
    };
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, []);

  /* ─── Reset focused index whenever suggestions list changes ─────────────── */
  useEffect(() => {
    setFocusedIndex(-1);
  }, [suggestions]);

  /* ─── Typeahead search ───────────────────────────────────────────────────── */
  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const q = searchText.trim();
      if (!q || q.length < 2) {
        if (!cancelled) { setSuggestions([]); setSearchOpen(false); }
        return;
      }
      setSearchBusy(true);
      try {
        const data = await screenerSearch(q, 10);
        if (!cancelled) {
          const rows = getArray(data?.items) as ScreenerSearchItem[];
          setSuggestions(rows);
          setSearchOpen(rows.length > 0);
        }
      } catch {
        if (!cancelled) { setSuggestions([]); setSearchOpen(false); }
      } finally {
        if (!cancelled) setSearchBusy(false);
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [searchText]);

  /* ─── Load company analysis ──────────────────────────────────────────────── */
  const loadCompany = useCallback(async (symbol: string) => {
    const clean = (symbol || '').trim().toUpperCase();
    if (!clean) return;

    // Increment generation counter — any in-flight request with a prior gen is stale
    loadGenRef.current += 1;
    const myGen = loadGenRef.current;

    setActiveSymbol(clean);
    setActiveTab('overview');
    setFundamentalSegment('ratios');
    setAnalysisBusy(true);
    setFinancialsPayload(null);
    setFinancialsSymbol('');
    setAnalysisError('');
    setFinancialsError('');
    financialsLoadingRef.current = null;

    try {
      const analysis = await getScreenerAnalysis(clean);
      if (loadGenRef.current !== myGen) return; // stale — a newer request won
      setAnalysisPayload(analysis);
      setAnalysisError('');
    } catch (err: unknown) {
      if (loadGenRef.current !== myGen) return; // stale error — ignore silently
      const msg = (err as any)?.message || 'Failed to load screener analysis.';
      setAnalysisPayload(null);
      setAnalysisError(msg);
    } finally {
      // Only reset busy state if this is still the current request
      if (loadGenRef.current === myGen) setAnalysisBusy(false);
    }
  }, []);

  /* ─── Load financial statements ──────────────────────────────────────────── */
  const loadFinancials = useCallback(async (symbol: string) => {
    const clean = (symbol || '').trim().toUpperCase();
    if (!clean) return;
    if (financialsLoadingRef.current === clean) return; // already loading this symbol
    if (financialsPayload && financialsSymbol === clean) return; // already loaded
    financialsLoadingRef.current = clean;
    setFinancialsBusy(true);
    try {
      const payload = await getScreenerFinancials(clean);
      setFinancialsPayload(payload);
      setFinancialsSymbol(clean);
      setFinancialsError('');
    } catch (err: unknown) {
      const msg = (err as any)?.message || 'Failed to load financial statements.';
      setFinancialsPayload(null);
      setFinancialsSymbol(clean);
      setFinancialsError(msg);
    } finally {
      financialsLoadingRef.current = null;
      setFinancialsBusy(false);
    }
  }, [financialsPayload, financialsSymbol]);

  /* ─── Search interaction handlers ───────────────────────────────────────── */
  const selectSuggestion = useCallback((item: ScreenerSearchItem) => {
    const sym = String(item?.symbol || '').trim().toUpperCase();
    if (!sym) return;
    setSearchText(`${item.name || sym} (${sym})`);
    setSuggestions([]);
    setSearchOpen(false);
    setFocusedIndex(-1);
    void loadCompany(sym);
  }, [loadCompany]);

  const onSearchKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!searchOpen || suggestions.length === 0) {
      if (e.key === 'Escape') { setSearchOpen(false); setFocusedIndex(-1); }
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setFocusedIndex((idx) => Math.min(idx + 1, suggestions.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setFocusedIndex((idx) => (idx <= 0 ? -1 : idx - 1));
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setSearchOpen(false);
      setFocusedIndex(-1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const target = focusedIndex >= 0 ? suggestions[focusedIndex] : suggestions[0];
      if (target) selectSuggestion(target);
    }
  }, [searchOpen, suggestions, focusedIndex, selectSuggestion]);

  const onSearchSubmit = useCallback((event: React.FormEvent) => {
    event.preventDefault();
    const target = focusedIndex >= 0 && focusedIndex < suggestions.length
      ? suggestions[focusedIndex]
      : suggestions.length > 0 ? suggestions[0] : null;
    if (target) { selectSuggestion(target); return; }
    const clean = searchText.trim().toUpperCase();
    if (!clean) return;
    setSearchOpen(false);
    void loadCompany(clean);
  }, [focusedIndex, suggestions, searchText, selectSuggestion, loadCompany]);

  /* ─── Auto-load default on mount ─────────────────────────────────────────── */
  useEffect(() => {
    if (activeSymbol || analysisBusy) return;
    void loadCompany(DEFAULT_SCREENER_SYMBOL);
  }, [activeSymbol, analysisBusy, loadCompany]);

  /* ─── Load financials when Fundamentals tab is opened ────────────────────── */
  useEffect(() => {
    if (activeTab !== 'fundamentals' || !activeSymbol) return;
    void loadFinancials(activeSymbol);
  }, [activeTab, activeSymbol, loadFinancials]);

  /* ─── Memos ──────────────────────────────────────────────────────────────── */
  const positives = useMemo(() => getArray(summary?.positives), [summary]);
  const negatives = useMemo(() => getArray(summary?.negatives), [summary]);
  const newsRows = useMemo(() => getArray(events?.news), [events]);
  const corpRows = useMemo(() => getArray(events?.corporate), [events]);
  const profileFacts = useMemo(() => getArray(fundamentals?.profile?.facts), [fundamentals]);
  const enforcementRows = useMemo(() => getArray(events?.enforcement), [events]);
  const peerRows = useMemo(() => getArray(peers?.items), [peers]);

  // Corporate actions: prefer events.corporate_actions (backend-filtered); fallback to keyword scan
  const corporateActionRows = useMemo(() => {
    const direct = getArray(events?.corporate_actions);
    if (direct.length > 0) return direct;
    return getArray(events?.corporate).filter((row: any) => {
      const t = normaliseEventType(row);
      return (
        t.includes('dividend') || t.includes('bonus') || t.includes('split') ||
        t.includes('buyback') || t.includes('rights') || t.includes('agm') ||
        t.includes('egm') || t.includes('corporateaction') || t.includes('recorddate') ||
        t.includes('exdate') || t.includes('boardmeeting') || t.includes('financialresults')
      );
    });
  }, [events]);

  // Insider trades: prefer events.insider_trades; fallback to keyword scan
  const insiderTradeRows = useMemo(() => {
    const direct = getArray(events?.insider_trades);
    if (direct.length > 0) return direct;
    return getArray(events?.corporate).filter((row: any) => {
      const t = normaliseEventType(row);
      return (
        t.includes('insider') || t.includes('sast') || t.includes('bulkdeal') ||
        t.includes('blockdeal') || t.includes('pledge') || t.includes('encumbrance') ||
        t.includes('promoter') || t.includes('shareholdingchange') ||
        t.includes('acquisition') || t.includes('disposal') || t.includes('pit')
      );
    });
  }, [events]);

  const periodColumns = useMemo(() => {
    return getArray(financialsPayload?.periods)
      .map((period: any) => {
        if (typeof period === 'string') return { id: period, label: period };
        const id = String(period?.id || period?.period || period?.label || '').trim();
        const label = String(period?.label || period?.period || period?.id || '').trim();
        return id ? { id, label: label || id } : null;
      })
      .filter(Boolean) as Array<{ id: string; label: string }>;
  }, [financialsPayload]);

  const ratioGroups = useMemo(() => {
    const raw = financialsPayload?.ratios;
    if (!raw || typeof raw !== 'object') return [];
    return Object.entries(raw)
      .map(([group, rows]) => ({ group, rows: getArray(rows) }))
      .filter((g) => g.rows.length > 0);
  }, [financialsPayload]);

  const activeStatement = useMemo(() => {
    if (fundamentalSegment === 'income_statement') return financialsPayload?.income_statement ?? null;
    if (fundamentalSegment === 'balance_sheet') return financialsPayload?.balance_sheet ?? null;
    if (fundamentalSegment === 'cash_flow') return financialsPayload?.cash_flow ?? null;
    return null;
  }, [financialsPayload, fundamentalSegment]);

  const statementRows = useMemo(() => getArray(activeStatement?.rows), [activeStatement]);

  /* ─── Statement table renderer ───────────────────────────────────────────── */
  const renderStatementTable = () => {
    if (!activeStatement) return null;
    const src = activeStatement?.source ?? {};
    const srcLine = [src?.name, src?.as_of ? `as of ${src.as_of}` : '', src?.basis ?? '']
      .map((s) => String(s ?? '').trim()).filter(Boolean).join(' | ');

    return (
      <div className="screener-table-card">
        <div className="screener-table-meta">
          <span>{srcLine || '—'}</span>
          <span>Values in ₹ cr (crores)</span>
        </div>
        <div className="screener-table-wrap">
          <table className="screener-table">
            <thead>
              <tr>
                <th>Metric</th>
                {periodColumns.map((col) => <th key={col.id}>{col.label}</th>)}
                <th>YoY %</th>
              </tr>
            </thead>
            <tbody>
              {statementRows.map((row: any, idx: number) => {
                const vals = row?.values ?? {};
                const last = periodColumns[periodColumns.length - 1]?.id;
                const prev = periodColumns[periodColumns.length - 2]?.id;
                const latest = Number(vals?.[last]);
                const prior = Number(vals?.[prev]);
                const yoy = Number.isFinite(latest) && Number.isFinite(prior) && prior !== 0
                  ? ((latest - prior) / Math.abs(prior)) * 100 : null;
                const unit = String(row?.unit || activeStatement?.unit || '').toLowerCase();
                const isPerShare = unit.includes('share') || unit.includes('eps') ||
                  String(row?.key || '').toLowerCase().includes('eps');

                return (
                  <tr key={String(row?.key || row?.label || idx)}>
                    <td>{row?.label || row?.key || 'Metric'}</td>
                    {periodColumns.map((col) => (
                      <td key={`${String(row?.key ?? idx)}-${col.id}`}>
                        {isPerShare ? fmtInr(vals?.[col.id], 2) : fmtCrore(vals?.[col.id], 2)}
                      </td>
                    ))}
                    <td className={Number.isFinite(yoy) ? (Number(yoy) >= 0 ? 'up' : 'down') : ''}>
                      {Number.isFinite(yoy) ? `${Number(yoy) >= 0 ? '+' : ''}${Number(yoy).toFixed(2)}%` : '—'}
                    </td>
                  </tr>
                );
              })}
              {statementRows.length === 0 && (
                <tr>
                  <td colSpan={periodColumns.length + 2} className="screener-table-empty">
                    Financial statement data unavailable.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    );
  };

  /* ─── JSX ────────────────────────────────────────────────────────────────── */
  const content = (
    <div className={`screener-shell ${embedded ? 'embedded' : ''}`}>

      {/* ── Search bar ───────────────────────────────────────────────────── */}
      <div className="screener-search-area" ref={searchAreaRef}>
        <form className="screener-search-form" onSubmit={onSearchSubmit}>
          <Search size={18} />
          <input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            onFocus={() => { if (suggestions.length > 0) setSearchOpen(true); }}
            onKeyDown={onSearchKeyDown}
            className="screener-search-input"
            placeholder="Search company name, symbol, ISIN, or CIN…"
            autoComplete="off"
            aria-autocomplete="list"
            aria-expanded={searchOpen}
            aria-haspopup="listbox"
            role="combobox"
          />
          {searchBusy && <span className="screener-search-status">Searching…</span>}
        </form>

        {searchOpen && suggestions.length > 0 && (
          <div className="screener-search-dropdown" role="listbox">
            {suggestions.map((item, idx) => {
              const conf = formatSuggestionConfidence(item.confidence);
              return (
                <button
                  key={`${item.symbol}-${item.cin || idx}`}
                  type="button"
                  className={`screener-search-option${focusedIndex === idx ? ' focused' : ''}`}
                  role="option"
                  aria-selected={focusedIndex === idx}
                  onMouseDown={(e) => e.preventDefault()}
                  onMouseEnter={() => setFocusedIndex(idx)}
                  onClick={() => selectSuggestion(item)}
                >
                  <div className="screener-search-option-head">
                    <span className="screener-search-option-symbol">{item.symbol}</span>
                    <span className="screener-search-option-sector">{item.sector || '—'}</span>
                  </div>
                  <div className="screener-search-option-name">{item.name}</div>
                  <div className="screener-search-option-meta">
                    <span>{item.source || 'resolver'}</span>
                    {conf && <span>{conf}</span>}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Empty / loading states ───────────────────────────────────────── */}
      {!activeSymbol && !analysisBusy && (
        <div className="screener-empty-state">
          Search a company above to open full screener analysis.
        </div>
      )}

      {analysisBusy && (
        <div className="screener-loading-stack">
          <div className="screener-loading">Fetching analysis for {activeSymbol}…</div>
          <div className="screener-skeleton-card" />
          <div className="screener-skeleton-grid">
            <div className="screener-skeleton-card" />
            <div className="screener-skeleton-card" />
            <div className="screener-skeleton-card" />
          </div>
        </div>
      )}

      {!analysisBusy && analysisError && (
        <div className="screener-error">
          {analysisError}
          <button
            type="button"
            className="screener-retry-btn"
            onClick={() => void loadCompany(activeSymbol)}
          >
            <RefreshCw size={12} /> Retry
          </button>
        </div>
      )}

      {/* ── Main analysis view ───────────────────────────────────────────── */}
      {!analysisBusy && snapshot && (
        <>
          {/* Head card */}
          <div className="screener-head-card">
            <div className="screener-company-meta">
              <div className="screener-company-symbol">
                <Building2 size={16} />
                <span>{resolved?.symbol || activeSymbol}</span>
                {resolved?.isin && <span className="screener-isin-badge">{resolved.isin}</span>}
              </div>
              <h2>{resolved?.company_name || activeSymbol}</h2>
              <div className="screener-company-sub">
                {resolved?.sector && <span className="screener-sector-badge">{resolved.sector}</span>}
                {resolved?.cin && <span>CIN: {resolved.cin}</span>}
              </div>
            </div>
            <div className="screener-head-metrics">
              <div className="screener-head-price">{fmtInr(livePrice, 2)}</div>
              <div className={`screener-head-change ${trendTone(liveChangePct)}`}>
                {Number.isFinite(Number(liveChangePct))
                  ? (Number(liveChangePct) >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />)
                  : null}
                {fmtPct(liveChangePct, 2)}
              </div>
              <div className="screener-score-pill">
                <Gauge size={14} />
                Score {Number.isFinite(Number(score?.prospekt_score)) ? fmtNum(score.prospekt_score, 1) : '—'}
                {score?.grade ? ` (${score.grade})` : ''}
              </div>
              <button
                type="button"
                className="screener-refresh-btn"
                onClick={() => void loadCompany(activeSymbol)}
                title="Reload analysis"
              >
                <RefreshCw size={13} />
              </button>
            </div>
          </div>

          {/* Score pillars strip */}
          {score?.pillars && (
            <div className="screener-pillars-row">
              {Object.entries(score.pillars).map(([pillar, val]) => (
                <div key={pillar} className="screener-pillar">
                  <span className="screener-pillar-label">{pillar.replace(/_/g, ' ')}</span>
                  <span className="screener-pillar-value">{fmtNum(val, 1)}</span>
                </div>
              ))}
            </div>
          )}

          {/* Tab bar */}
          <div className="screener-tabbar">
            {(['overview', 'fundamentals', 'technicals', 'events'] as ScreenerViewTab[]).map((tab) => (
              <button
                key={tab}
                type="button"
                className={activeTab === tab ? 'active' : ''}
                onClick={() => setActiveTab(tab)}
              >
                {tab === 'events' ? 'News & Corporate' : tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="screener-content">

            {/* ── Overview tab ──────────────────────────────────────────── */}
            {activeTab === 'overview' && (
              <div className="screener-section-grid">

                {/* Key Metrics — sourced exclusively from fundamentals.metrics */}
                <div className="screener-section screener-section-wide">
                  <div className="screener-section-head"><Gauge size={14} /> Key Metrics</div>
                  <div className="screener-key-metrics-grid">
                    {[
                      { label: 'Market Cap',       val: fmtMarketCap(m?.market_cap, true) },
                      { label: 'P/E Ratio',        val: fmtNum(m?.pe_ratio, 2) },
                      { label: 'P/B Ratio',        val: fmtNum(m?.pb_ratio, 2) },
                      { label: 'EPS (TTM)',         val: fmtInr(m?.eps, 2) },
                      { label: 'Book Value',       val: fmtInr(m?.book_value, 2) },
                      { label: 'Dividend Yield',   val: fmtPct(m?.dividend_yield, 2) },
                      { label: 'ROE',              val: fmtPct(m?.roe, 2),             tone: trendTone(m?.roe) },
                      { label: 'ROCE',             val: fmtPct(m?.roce, 2),            tone: trendTone(m?.roce) },
                      { label: 'Debt / Equity',    val: fmtNum(m?.debt_to_equity, 2) },
                      { label: 'Current Ratio',    val: fmtNum(m?.current_ratio, 2) },
                      { label: 'Net Margin',       val: fmtPct(m?.net_margin_pct, 2),  tone: trendTone(m?.net_margin_pct) },
                      { label: 'Operating Margin', val: fmtPct(m?.operating_margin_pct, 2), tone: trendTone(m?.operating_margin_pct) },
                      { label: 'Gross Margin',     val: fmtPct(m?.gross_margin_pct, 2), tone: trendTone(m?.gross_margin_pct) },
                      { label: 'ROA',              val: fmtPct(m?.return_on_assets_pct, 2), tone: trendTone(m?.return_on_assets_pct) },
                      { label: 'Revenue Growth',   val: fmtPct(m?.revenue_growth_pct, 2), tone: trendTone(m?.revenue_growth_pct) },
                      { label: 'PAT Growth',       val: fmtPct(m?.net_income_growth_pct, 2), tone: trendTone(m?.net_income_growth_pct) },
                      { label: 'EV / EBITDA',      val: fmtNum(m?.ev_to_ebitda, 2) },
                      { label: 'Price / Sales',    val: fmtNum(m?.price_to_sales, 2) },
                      { label: 'FCF Yield',        val: fmtPct(m?.fcf_yield_pct, 2) },
                      { label: 'Earnings Yield',   val: fmtPct(m?.earnings_yield_pct, 2) },
                      { label: 'PEG Ratio',        val: fmtNum(m?.peg_ratio_proxy, 2) },
                      { label: 'Beta',             val: fmtNum(m?.beta, 2) },
                      { label: 'Promoter Holding', val: fmtPct(m?.promoter_holding_pct, 2) },
                      { label: 'Promoter Pledge',  val: fmtPct(m?.promoter_pledge_pct, 2), tone: Number(m?.promoter_pledge_pct) > 0 ? 'down' as const : 'neutral' as const },
                      { label: 'FII Holding',      val: fmtPct(m?.fii_holding_pct, 2) },
                      { label: 'DII Holding',      val: fmtPct(m?.dii_holding_pct, 2) },
                      { label: '52W High',         val: fmtInr(technicals?.high_52w, 2) },
                      { label: '52W Low',          val: fmtInr(technicals?.low_52w, 2) },
                      { label: 'Piotroski Score',  val: fmtNum(m?.piotroski_f_score_proxy, 0) },
                    ].map(({ label, val, tone }) => (
                      <div key={label} className="screener-metric-item">
                        <span className="screener-metric-label">{label}</span>
                        <span className={`screener-metric-value${tone ? ` ${tone}` : ''}`}>{val}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Company Profile */}
                <div className="screener-section screener-section-wide">
                  <div className="screener-section-head"><Building2 size={14} /> Company Profile</div>
                  <p className="screener-longtext">
                    {fundamentals?.profile?.business_summary ||
                     fundamentals?.profile?.overview ||
                     'Business overview not available from public sources.'}
                  </p>
                  {profileFacts.length > 0 && (
                    <div className="screener-facts-grid">
                      {profileFacts.map((fact: any, idx: number) => (
                        <div key={`fact-${idx}`} className="screener-fact">
                          <span className="screener-fact-label">{fact?.label}</span>
                          <span className="screener-fact-value">{displayText(fact?.value)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {(fundamentals?.profile?.mission || fundamentals?.profile?.vision) && (
                    <div className="screener-overview-points">
                      {fundamentals?.profile?.mission && <div><strong>Mission:</strong> {fundamentals.profile.mission}</div>}
                      {fundamentals?.profile?.vision && <div><strong>Vision:</strong> {fundamentals.profile.vision}</div>}
                    </div>
                  )}
                  {getArray(fundamentals?.profile?.products_services).length > 0 && (
                    <div className="screener-section-note">
                      Products / Services: {getArray(fundamentals.profile.products_services).slice(0, 6).join(' | ')}
                    </div>
                  )}
                </div>

                {/* Positive / Negative Indicators — all, no cap */}
                <div className="screener-section">
                  <div className="screener-section-head"><ArrowUpRight size={14} /> Positive / Negative Indicators</div>
                  {positives.length === 0 && negatives.length === 0 ? (
                    <div className="screener-empty-inline">Signal analysis not yet available for this snapshot.</div>
                  ) : (
                    <div className="screener-bullets">
                      <div>
                        <h4>Positives ({positives.length})</h4>
                        {positives.map((item: string, idx: number) => (
                          <p key={`p-${idx}`} className="screener-bullet-positive">+ {item}</p>
                        ))}
                        {positives.length === 0 && <p className="screener-empty-inline">No positive signals.</p>}
                      </div>
                      <div>
                        <h4>Negatives ({negatives.length})</h4>
                        {negatives.map((item: string, idx: number) => (
                          <p key={`n-${idx}`} className="screener-bullet-negative">- {item}</p>
                        ))}
                        {negatives.length === 0 && <p className="screener-empty-inline">No negative signals.</p>}
                      </div>
                    </div>
                  )}
                </div>

                {/* Peer Comparison — columns match actual peer data shape */}
                <div className="screener-section screener-section-wide">
                  <div className="screener-section-head"><Building2 size={14} /> Peer Comparison</div>
                  {peers?.status === 'deferred' ? (
                    <div className="screener-empty-inline">Peer data is being fetched in the background. Reload to refresh.</div>
                  ) : peerRows.length > 0 ? (
                    <div className="screener-mini-table-wrap">
                      <table className="screener-mini-table">
                        <thead>
                          <tr>
                            <th>Company</th>
                            <th>Mkt Cap (cr)</th>
                            <th>Price</th>
                            <th>P/E</th>
                            <th>P/B</th>
                            <th>ROE %</th>
                            <th>ROCE %</th>
                            <th>D/E</th>
                            <th>Promoter %</th>
                          </tr>
                        </thead>
                        <tbody>
                          {/* Current company — highlighted */}
                          <tr className="screener-peer-self">
                            <td><strong>{resolved?.symbol || activeSymbol}</strong> <span className="screener-peer-self-label">▶ this</span></td>
                            <td>{fmtMarketCap(m?.market_cap, true)}</td>
                            <td>{fmtInr(livePrice, 2)}</td>
                            <td>{fmtNum(m?.pe_ratio, 2)}</td>
                            <td>{fmtNum(m?.pb_ratio, 2)}</td>
                            <td>{fmtPct(m?.roe, 2)}</td>
                            <td>{fmtPct(m?.roce, 2)}</td>
                            <td>{fmtNum(m?.debt_to_equity, 2)}</td>
                            <td>{fmtPct(m?.promoter_holding_pct, 2)}</td>
                          </tr>
                          {peerRows.map((row: any, idx: number) => (
                            <tr key={row.symbol || row.company_name || String(idx)}>
                              <td>{row.symbol || '—'}{row.company_name ? <span className="screener-peer-name"> {row.company_name}</span> : null}</td>
                              {/* backend field is market_cap_cr */}
                              <td>{fmtMarketCap(row.market_cap_cr ?? row.market_cap, true)}</td>
                              <td>{fmtInr(row.price, 2)}</td>
                              <td>{fmtNum(row.pe_ratio, 2)}</td>
                              <td>{fmtNum(row.pb_ratio, 2)}</td>
                              <td>{fmtPct(row.roe, 2)}</td>
                              <td>{fmtPct(row.roce, 2)}</td>
                              <td>{fmtNum(row.debt_to_equity, 2)}</td>
                              <td>{fmtPct(row.promoter_holding_pct, 2)}</td>
                            </tr>
                          ))}
                          {/* Sector median */}
                          {peers?.median && (
                            <tr className="screener-peer-median">
                              <td><em>Sector Median</em></td>
                              <td>—</td>
                              <td>—</td>
                              <td>{fmtNum(peers.median.pe_ratio, 2)}</td>
                              <td>{fmtNum(peers.median.pb_ratio, 2)}</td>
                              <td>{fmtPct(peers.median.roe, 2)}</td>
                              <td>{fmtPct(peers.median.roce, 2)}</td>
                              <td>{fmtNum(peers.median.debt_to_equity, 2)}</td>
                              <td>—</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="screener-empty-inline">Peer comparison data not available for this company.</div>
                  )}
                  {peers?.source && <div className="screener-section-note">Source: {peers.source}</div>}
                </div>

                {/* Contradictions / Blind Spots */}
                <div className="screener-section">
                  <div className="screener-section-head"><AlertTriangle size={14} /> Contradictions / Blind Spots</div>
                  {contradictions.length === 0 ? (
                    <>
                      <div className="screener-empty-inline">No material contradictions detected.</div>
                      <div className="screener-section-note">
                        Checks run: Valuation vs Growth · Profit vs Cash Flow · Technicals vs Governance · Promoter Pledge Stress
                      </div>
                    </>
                  ) : (
                    contradictions.map((item: any, idx: number) => (
                      <div key={`c-${idx}`} className="screener-contradiction">
                        <div className="screener-contradiction-header">
                          <span className="screener-contradiction-title">{item.title || item.code || `Flag ${idx + 1}`}</span>
                          <span className={`screener-contradiction-severity ${contradictionTone(item.severity ?? item.level)}`}>
                            {contradictionSeverityLabel(item)}
                          </span>
                        </div>
                        <div className="screener-contradiction-detail">{item.detail || item.description || '—'}</div>
                        {item.data_points && typeof item.data_points === 'object' && (
                          <div className="screener-contradiction-datapoints">
                            {Object.entries(item.data_points).map(([k, v]) => (
                              <span key={k} className="screener-contradiction-dp">
                                <strong>{k}:</strong>{' '}
                                {v !== null && typeof v === 'object' ? JSON.stringify(v) : String(v ?? '—')}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>

              </div>
            )}

            {/* ── Fundamentals tab ──────────────────────────────────────── */}
            {activeTab === 'fundamentals' && (
              <div className="screener-section-grid">
                <div className="screener-segmented">
                  {(['ratios', 'income_statement', 'balance_sheet', 'cash_flow'] as FundamentalSegment[]).map((seg) => (
                    <button
                      key={seg}
                      type="button"
                      className={fundamentalSegment === seg ? 'active' : ''}
                      onClick={() => setFundamentalSegment(seg)}
                    >
                      {seg === 'ratios' ? 'Ratios' : seg === 'income_statement' ? 'Income Statement' : seg === 'balance_sheet' ? 'Balance Sheet' : 'Cash Flow'}
                    </button>
                  ))}
                </div>

                {financialsBusy ? (
                  <div className="screener-loading-stack">
                    <div className="screener-loading">Loading financial data for {activeSymbol}…</div>
                    <div className="screener-skeleton-card" />
                  </div>
                ) : financialsError ? (
                  <div className="screener-error">
                    {financialsError}
                    <button type="button" className="screener-retry-btn" onClick={() => {
                      setFinancialsPayload(null); setFinancialsSymbol(''); void loadFinancials(activeSymbol);
                    }}><RefreshCw size={12} /> Retry</button>
                  </div>
                ) : fundamentalSegment === 'ratios' ? (
                  <div className="screener-ratio-groups">
                    {ratioGroups.map((grp) => (
                      <div key={grp.group} className="screener-ratio-group">
                        <div className="screener-ratio-group-title">{String(grp.group).replace(/_/g, ' ')}</div>
                        <div className="screener-metric-grid">
                          {grp.rows.map((item: any) => (
                            <div key={`${grp.group}-${item.key ?? item.label}`} className="screener-metric-card">
                              <div className="screener-metric-label">{item.label || item.key || 'Metric'}</div>
                              <div className="screener-metric-value">{formatRatioValue(item)}</div>
                              <div className="screener-metric-source">{item.source || '—'}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                    {financialAnalytics?.status && (
                      <div className="screener-section">
                        <div className="screener-section-head"><Gauge size={14} /> Derived Analytics</div>
                        <div className="screener-tech-grid">
                          <div>DCF Fair Value: <strong>{fmtInr(financialAnalytics?.dcf?.fair_value_per_share, 2)}</strong></div>
                          <div>DCF Upside: <strong>{fmtPct(financialAnalytics?.dcf?.upside_pct, 2)}</strong></div>
                          <div>Piotroski F-Score: <strong>{fmtNum(financialAnalytics?.piotroski?.score, 0)}/9</strong></div>
                          <div>DuPont ROE: <strong>{fmtPct(financialAnalytics?.dupont?.roe_pct, 2)}</strong></div>
                          <div>Asset Turnover: <strong>{fmtNum(financialAnalytics?.dupont?.asset_turnover, 3)}x</strong></div>
                          <div>Equity Multiplier: <strong>{fmtNum(financialAnalytics?.dupont?.equity_multiplier, 2)}x</strong></div>
                          <div>Net Margin (DuPont): <strong>{fmtPct(financialAnalytics?.dupont?.net_margin_pct, 2)}</strong></div>
                        </div>
                        <div className="screener-section-note">
                          {financialAnalytics?.dcf?.source || financialAnalytics?.source || 'Derived from public financial statements.'}
                        </div>
                      </div>
                    )}
                    {ratioGroups.length === 0 && !financialsBusy && (
                      <div className="screener-empty-inline">Ratio data not yet available. Try switching to Income Statement.</div>
                    )}
                  </div>
                ) : (
                  renderStatementTable()
                )}
              </div>
            )}

            {/* ── Technicals tab ────────────────────────────────────────── */}
            {activeTab === 'technicals' && (
              <div className="screener-section-grid">
                <div className="screener-section">
                  <div className="screener-section-head"><CandlestickChart size={14} /> Technical Structure</div>
                  {technicals?.status === 'unavailable' ? (
                    <div className="screener-empty-inline">Technical data unavailable — insufficient price history.</div>
                  ) : (
                    <div className="screener-tech-grid">
                      <div>Trend Bias: <strong>{displayText(technicals?.trend_bias)}</strong></div>
                      <div>RSI (14):
                        <strong className={
                          Number(technicals?.rsi14) >= 70 ? 'screener-val-overbought' :
                          Number(technicals?.rsi14) <= 30 ? 'screener-val-oversold' : ''
                        }>
                          {' '}{fmtNum(technicals?.rsi14, 1)}
                          {Number.isFinite(Number(technicals?.rsi14))
                            ? Number(technicals.rsi14) >= 70 ? ' — Overbought'
                            : Number(technicals.rsi14) <= 30 ? ' — Oversold' : ''
                            : ''}
                        </strong>
                      </div>
                      <div>MACD: <strong>{fmtNum(technicals?.macd, 4)}</strong></div>
                      <div>MACD Signal: <strong>{fmtNum(technicals?.macd_signal, 4)}</strong></div>
                      <div>MACD Histogram: <strong className={trendTone(technicals?.macd_histogram)}>{fmtNum(technicals?.macd_histogram, 4)}</strong></div>
                      <div>SMA 20/50: <strong>{displayText(technicals?.sma20_50_signal)}</strong></div>
                      <div>SMA 50/200: <strong>{displayText(technicals?.sma50_200_signal)}</strong></div>
                      <div>Above 200 DMA: <strong>{technicals?.above_200dma === true ? 'Yes' : technicals?.above_200dma === false ? 'No' : '—'}</strong></div>
                      <div>Breakout State: <strong>{displayText(technicals?.breakout_state)}</strong></div>
                      <div>1M Return: <strong className={trendTone(technicals?.return_1m_pct)}>{fmtPct(technicals?.return_1m_pct, 2)}</strong></div>
                      <div>3M Return: <strong className={trendTone(technicals?.return_3m_pct)}>{fmtPct(technicals?.return_3m_pct, 2)}</strong></div>
                      <div>Volatility (1M ann.): <strong>{fmtPct(technicals?.volatility_1m_annualized_pct, 2)}</strong></div>
                      <div>52W Drawdown: <strong className="down">{fmtPct(technicals?.drawdown_from_52w_high_pct, 2)}</strong></div>
                      <div>52W Upside: <strong className="up">{fmtPct(technicals?.upside_to_52w_high_pct, 2)}</strong></div>
                      <div>Bollinger Position: <strong>{fmtPct(technicals?.bollinger_position_pct, 1)}</strong></div>
                    </div>
                  )}
                </div>

                <div className="screener-section">
                  <div className="screener-section-head"><CircleDot size={14} /> Price Structure</div>
                  <Sparkline prices={getArray(technicals?.history?.prices) as number[]} />
                  <div className="screener-tech-grid screener-tech-grid-spaced">
                    <div>20 DMA: <strong>{fmtInr(technicals?.sma20, 2)}</strong></div>
                    <div>50 DMA: <strong>{fmtInr(technicals?.sma50, 2)}</strong></div>
                    <div>200 DMA: <strong>{fmtInr(technicals?.sma200, 2)}</strong></div>
                    <div>Bollinger Upper: <strong>{fmtInr(technicals?.bollinger_upper, 2)}</strong></div>
                    <div>Bollinger Mid: <strong>{fmtInr(technicals?.bollinger_mid ?? technicals?.sma20, 2)}</strong></div>
                    <div>Bollinger Lower: <strong>{fmtInr(technicals?.bollinger_lower, 2)}</strong></div>
                    <div>Bollinger State: <strong>{displayText(technicals?.bollinger_state)}</strong></div>
                    <div>20D Support: <strong>{fmtInr(technicals?.support_20d, 2)}</strong></div>
                    <div>20D Resistance: <strong>{fmtInr(technicals?.resistance_20d, 2)}</strong></div>
                    <div>52W High: <strong>{fmtInr(technicals?.high_52w, 2)}</strong></div>
                    <div>52W Low: <strong>{fmtInr(technicals?.low_52w, 2)}</strong></div>
                  </div>
                </div>
              </div>
            )}

            {/* ── News & Corporate tab ──────────────────────────────────── */}
            {activeTab === 'events' && (
              <div className="screener-section-grid">

                <div className="screener-section">
                  <div className="screener-section-head"><ArrowUpRight size={14} /> Latest News</div>
                  <div className="screener-event-list">
                    {newsRows.slice(0, 14).map((row: any, idx: number) => (
                      <a
                        key={`news-${idx}`}
                        href={row.url || '#'}
                        target="_blank"
                        rel="noreferrer"
                        className="screener-event-row"
                      >
                        <div>{displayText(row.headline ?? row.title, 'Market update')}</div>
                        <div className="screener-event-meta">
                          <span>{displayText(row.source, 'News')}</span>
                          <span>{displayText(row.age ?? formatEventPublished(row.published))}</span>
                          <span className={`screener-sentiment ${sentimentTone(row.sentiment)}`}>
                            {sentimentLabel(row.sentiment)}
                          </span>
                        </div>
                      </a>
                    ))}
                    {newsRows.length === 0 && (
                      <div className="screener-empty-inline">No news items returned for this symbol.</div>
                    )}
                  </div>
                </div>

                <div className="screener-section">
                  <div className="screener-section-head"><Building2 size={14} /> Corporate Disclosures</div>
                  <div className="screener-event-list">
                    {corpRows.slice(0, 12).map((row: any, idx: number) => (
                      <a
                        key={`corp-${idx}`}
                        href={row.url || '#'}
                        target="_blank"
                        rel="noreferrer"
                        className="screener-event-row"
                      >
                        <div>{displayText(row.title, 'Corporate disclosure')}</div>
                        <div className="screener-event-meta">
                          <span>{displayText(row.event_type || row.category, 'disclosure')}</span>
                          <span>{displayText(row.source, 'Exchange')}</span>
                          <span>{formatEventPublished(row.published)}</span>
                          <span className={`screener-sentiment ${sentimentTone(row.sentiment)}`}>
                            {sentimentLabel(row.sentiment)}
                          </span>
                        </div>
                      </a>
                    ))}
                    {corpRows.length === 0 && (
                      <div className="screener-empty-inline">No corporate disclosures available.</div>
                    )}
                  </div>
                  {enforcementRows.length > 0 && (
                    <div className="screener-enforcement">
                      <h4>Enforcement / Regulatory Signals ({enforcementRows.length})</h4>
                      {enforcementRows.slice(0, 8).map((row: any, idx: number) => (
                        <div key={`enf-${idx}`} className="screener-flag-row">
                          <span>{displayText(row.violation_type ?? row.label, 'Regulatory item')}</span>
                          <span>{displayText(row.order_date ?? row.updated_at)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="screener-section">
                  <div className="screener-section-head"><CandlestickChart size={14} /> Corporate Actions</div>
                  <div className="screener-event-list">
                    {corporateActionRows.length > 0 ? (
                      corporateActionRows.slice(0, 10).map((row: any, idx: number) => (
                        <a
                          key={`ca-${idx}`}
                          href={row.url || '#'}
                          target="_blank"
                          rel="noreferrer"
                          className="screener-event-row"
                        >
                          <div>{displayText(row.title, 'Corporate action')}</div>
                          <div className="screener-event-meta">
                            <span className="screener-event-type-badge">{displayText(row.event_type || row.category, 'corporate_action')}</span>
                            <span>{formatEventPublished(row.published ?? row.ex_date ?? row.record_date)}</span>
                            <span>{displayText(row.source, 'Exchange')}</span>
                            {row.amount && <span>Amount: {displayText(row.amount)}</span>}
                          </div>
                        </a>
                      ))
                    ) : (
                      <div className="screener-empty-inline">
                        No corporate actions (dividends, bonus, splits, buybacks) detected in recent exchange filings.
                      </div>
                    )}
                  </div>
                </div>

                <div className="screener-section">
                  <div className="screener-section-head"><ShieldCheck size={14} /> Insider Trades & SAST</div>
                  <div className="screener-event-list">
                    {insiderTradeRows.length > 0 ? (
                      insiderTradeRows.slice(0, 10).map((row: any, idx: number) => (
                        <a
                          key={`it-${idx}`}
                          href={row.url || '#'}
                          target="_blank"
                          rel="noreferrer"
                          className="screener-event-row"
                        >
                          <div>{displayText(row.title ?? row.headline, 'Insider disclosure')}</div>
                          <div className="screener-event-meta">
                            <span className="screener-event-type-badge">{displayText(row.event_type || row.category, 'insider_trade')}</span>
                            <span>{formatEventPublished(row.published ?? row.trade_date)}</span>
                            <span>{displayText(row.source, 'Exchange')}</span>
                            {row.person && <span>{displayText(row.person)}</span>}
                            {row.transaction_type && <span>{displayText(row.transaction_type)}</span>}
                            {row.shares && <span>Qty: {fmtVolume(row.shares)}</span>}
                          </div>
                        </a>
                      ))
                    ) : (
                      <div className="screener-empty-inline">
                        No SAST / insider-trade disclosures detected in recent exchange filings.
                      </div>
                    )}
                  </div>
                </div>

              </div>
            )}

            <footer className="screener-footer">
              <span>Symbol: {resolved?.symbol || activeSymbol}</span>
              {resolved?.sector && <span>Sector: {resolved.sector}</span>}
              {score?.grade && <span>Grade: {score.grade}</span>}
              {score?.method && <span>Model: {score.method}</span>}
            </footer>
          </div>
        </>
      )}
    </div>
  );

  const wrapped = <ScreenerRenderBoundary>{content}</ScreenerRenderBoundary>;
  return embedded ? wrapped : <AppShell title="Screener">{wrapped}</AppShell>;
};

export default ScreenerWorkspace;

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  ArrowUpRight,
  Building2,
  CandlestickChart,
  CircleDot,
  Database,
  Download,
  Gauge,
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
  runScreenerQuery,
  screenerSearch,
} from '../../api/client';
import { useMarketFeed } from '../../hooks/useMarketFeed';
import '../../styles/screener.css';

type ScreenerViewTab = 'overview' | 'fundamentals' | 'technicals' | 'governance' | 'events';
type FundamentalSegment = 'ratios' | 'income_statement' | 'balance_sheet' | 'cash_flow';

interface ScreenerWorkspaceProps {
  embedded?: boolean;
}

const SEARCH_DEBOUNCE_MS = 250;
const DEFAULT_SCREENER_SYMBOL = 'RELIANCE';
const QUICK_SCREENER_QUERIES = [
  { id: 'quality', label: 'Quality Leaders', query: 'quality companies with high roe and low debt' },
  { id: 'growth', label: 'Growth Leaders', query: 'high growth companies with improving profit and revenue momentum' },
  { id: 'value', label: 'Value Picks', query: 'profitable undervalued companies with reasonable pe' },
] as const;

const CRORE = 10_000_000;
const LAKH = 100_000;

const fmtNum = (value: any, digits = 2) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return n.toFixed(digits);
};

const fmtPct = (value: any, digits = 2) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `${n.toFixed(digits)}%`;
};

const fmtInr = (value: any, digits = 2) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: digits })}`;
};

// Format value already in crores
const fmtCrore = (value: any, digits = 2) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `₹${n.toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: digits })} cr`;
};

// Format large volumes/quantities
const fmtVolume = (value: any) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  const absN = Math.abs(n);
  if (absN >= CRORE) return `${(absN / CRORE).toFixed(2)} cr`;
  if (absN >= LAKH) return `${(absN / LAKH).toFixed(2)} L`;
  if (absN >= 1000) return `${(absN / 1000).toFixed(1)}k`;
  return n.toLocaleString('en-IN');
};

// Format market cap (expects value in crores or raw INR)
const fmtMarketCap = (value: any, isInCrores = false) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  const crores = isInCrores ? n : n / CRORE;
  if (crores >= 100000) {
    return `₹${(crores / 100000).toFixed(2)} L cr`;
  }
  return `₹${crores.toLocaleString('en-IN', { maximumFractionDigits: 2 })} cr`;
};

const trendTone = (value: any) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'neutral';
  return n >= 0 ? 'up' : 'down';
};

const getArray = (value: any): any[] => (Array.isArray(value) ? value : []);

const Sparkline: React.FC<{ prices: number[] }> = ({ prices }) => {
  const usable = prices.filter((p) => Number.isFinite(p));
  if (usable.length < 2) return <div className="screener-empty-inline">No chart history</div>;
  const width = 360;
  const height = 84;
  const min = Math.min(...usable);
  const max = Math.max(...usable);
  const span = max - min || 1;
  const points = usable.map((price, idx) => {
    const x = (idx / (usable.length - 1)) * width;
    const y = height - ((price - min) / span) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const path = points.map((pt, idx) => `${idx === 0 ? 'M' : 'L'} ${pt}`).join(' ');
  const area = `${path} L ${width},${height} L 0,${height} Z`;
  const tone = usable[usable.length - 1] >= usable[0] ? 'var(--profit)' : 'var(--loss)';

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="screener-sparkline" preserveAspectRatio="none">
      <path d={area} fill={tone === 'var(--profit)' ? 'rgba(52, 211, 153, 0.14)' : 'rgba(251, 113, 133, 0.14)'} />
      <path d={path} fill="none" stroke={tone} strokeWidth={2} />
    </svg>
  );
};

const formatSuggestionConfidence = (value: any) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '';
  return `${Math.round(n * 100)}%`;
};

const formatRatioValue = (item: any) => {
  if (item?.display) return String(item.display);
  const unit = String(item?.unit || '').toLowerCase();
  if (unit.includes('%')) return fmtPct(item?.value, 2);
  if (unit.includes('crore') || unit.includes('cr')) return fmtCrore(item?.value, 2);
  if (unit.includes('inr') || unit.includes('rs') || unit.includes('₹')) return fmtInr(item?.value, 2);
  if (unit.includes('times') || unit.includes('x')) return `${fmtNum(item?.value, 2)}x`;
  return fmtNum(item?.value, 2);
};

const formatFreshnessStatus = (value: any) => {
  const status = String(value || '').toLowerCase();
  if (!status) return '—';
  if (status === 'live' || status === 'available') return 'Live';
  if (status === 'fresh') return 'Fresh';
  if (status === 'stale') return 'Stale';
  if (status === 'aging') return 'Aging';
  if (status === 'ok') return 'OK';
  if (status === 'unavailable') return '—';
  return status.replace(/_/g, ' ').replace(/\b\w/g, (match) => match.toUpperCase());
};

const displayText = (value: any, fallback = '—') => {
  const text = String(value ?? '').trim();
  return text || fallback;
};

const sentimentTone = (value: any) => {
  const label = String(value?.label || value || '').toLowerCase();
  if (label === 'positive') return 'positive';
  if (label === 'negative') return 'negative';
  return 'neutral';
};

const formatEventPublished = (value: any) => {
  const text = String(value ?? '').trim();
  return text || '—';
};

const formatAge = (value: any, unit: 's' | 'h') => {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  return `${n.toFixed(unit === 's' ? 0 : 1)}${unit}`;
};

const downloadTextFile = (filename: string, content: string, mimeType: string) => {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
};

const toCsv = (rows: Array<Array<string | number | null | undefined>>) => rows
  .map((row) => row.map((cell) => {
    if (cell === null || cell === undefined) return '';
    const textCell = String(cell);
    if (/["\n,]/.test(textCell)) {
      return `"${textCell.replace(/"/g, '""')}"`;
    }
    return textCell;
  }).join(','))
  .join('\n');

class ScreenerRenderBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    // Keep rendering safe while still logging for diagnostics.
    console.error('Screener render failed', error);
  }

  render() {
    if (this.state.hasError) {
      return <div className="screener-error">Screener view encountered a rendering error. Please refresh.</div>;
    }
    return this.props.children;
  }
}

export const ScreenerWorkspace: React.FC<ScreenerWorkspaceProps> = ({ embedded = false }) => {
  const [searchText, setSearchText] = useState('');
  const [suggestions, setSuggestions] = useState<ScreenerSearchItem[]>([]);
  const [searchBusy, setSearchBusy] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  const [activeSymbol, setActiveSymbol] = useState('');
  const [analysisPayload, setAnalysisPayload] = useState<any>(null);
  const [financialsPayload, setFinancialsPayload] = useState<any>(null);
  const [financialsSymbol, setFinancialsSymbol] = useState('');
  const [analysisBusy, setAnalysisBusy] = useState(false);
  const [financialsBusy, setFinancialsBusy] = useState(false);
  const [analysisError, setAnalysisError] = useState('');
  const [financialsError, setFinancialsError] = useState('');
  const [queryRows, setQueryRows] = useState<any[]>([]);
  const [queryBusy, setQueryBusy] = useState(false);
  const [queryError, setQueryError] = useState('');

  const [activeTab, setActiveTab] = useState<ScreenerViewTab>('overview');
  const [fundamentalSegment, setFundamentalSegment] = useState<FundamentalSegment>('ratios');

  const snapshot = analysisPayload?.snapshot || null;
  const resolved = snapshot?.resolved || {};
  const score = snapshot?.score || {};
  const quote = snapshot?.quote || {};

  // Real-time price for the open company (Upstox feed -> HTTP fallback).
  const { prices: livePrices } = useMarketFeed(activeSymbol ? [activeSymbol] : [], { includeIndices: false });
  const liveTick = activeSymbol ? livePrices[activeSymbol.toUpperCase()] : undefined;
  const livePrice = liveTick?.price ?? quote?.price;
  const liveChangePct = liveTick?.change_pct ?? quote?.change_pct;
  const liveSource = liveTick?.source || quote?.source;
  const fundamentals = snapshot?.fundamentals || {};
  const publicDepth = fundamentals?.public_data_depth || {};
  const financialAnalytics = financialsPayload?.analytics || {};
  const technicals = snapshot?.technicals || {};
  const governance = snapshot?.governance || {};
  const events = snapshot?.events || {};
  const summary = snapshot?.summary || {};
  const contradictions = getArray(snapshot?.contradictions);
  const peers = snapshot?.peers || {};
  const sourceHealth = snapshot?.source_health || {};
  const freshness = snapshot?.freshness || {};
  const freshnessSections = freshness?.sections || {};

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const q = searchText.trim();
      if (!q || q.length < 2) {
        if (!cancelled) {
          setSuggestions([]);
          setSearchOpen(false);
        }
        return;
      }
      setSearchBusy(true);
      try {
        const data = await screenerSearch(q, 8);
        if (!cancelled) {
          const rows = getArray(data?.items) as ScreenerSearchItem[];
          setSuggestions(rows);
          setSearchOpen(rows.length > 0);
        }
      } catch {
        if (!cancelled) {
          setSuggestions([]);
          setSearchOpen(false);
        }
      } finally {
        if (!cancelled) {
          setSearchBusy(false);
        }
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [searchText]);

  const loadCompany = useCallback(async (symbol: string) => {
    const clean = (symbol || '').trim().toUpperCase();
    if (!clean) return;
    setActiveSymbol(clean);
    setActiveTab('overview');
    setFundamentalSegment('ratios');
    setAnalysisBusy(true);
    setFinancialsBusy(false);
    setFinancialsPayload(null);
    setFinancialsSymbol('');
    setAnalysisError('');
    setFinancialsError('');

    try {
      const analysis = await getScreenerAnalysis(clean);
      setAnalysisPayload(analysis);
      setAnalysisError('');
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'name' in err && err.name === 'AbortError') return;
      setAnalysisPayload(null);
      setAnalysisError((err as any)?.message || 'Failed to load screener analysis.');
    }
    setAnalysisBusy(false);
  }, []);

  const loadFinancials = useCallback(async (symbol: string) => {
    const clean = (symbol || '').trim().toUpperCase();
    if (!clean) return;
    if (financialsBusy) return;
    if (financialsPayload && financialsSymbol === clean) return;
    setFinancialsBusy(true);
    try {
      const payload = await getScreenerFinancials(clean);
      setFinancialsPayload(payload);
      setFinancialsSymbol(clean);
      setFinancialsError('');
    } catch (err: unknown) {
      if (err && typeof err === 'object' && 'name' in err && err.name === 'AbortError') return;
      setFinancialsPayload(null);
      setFinancialsSymbol(clean);
      setFinancialsError((err as any)?.message || 'Failed to load financial statements.');
    } finally {
      setFinancialsBusy(false);
    }
  }, [financialsBusy, financialsPayload, financialsSymbol]);

  const runQuickQuery = useCallback(async (query: string) => {
    if (!query.trim()) return;
    setQueryBusy(true);
    setQueryError('');
    try {
      const data = await runScreenerQuery(query, 20);
      const rows = getArray(data?.matches);
      setQueryRows(rows);
      setQueryError(rows.length > 0 ? '' : 'No stocks matched this query yet.');
    } catch (err: unknown) {
      setQueryRows([]);
      setQueryError((err as any)?.message || 'Failed to run screener query.');
    } finally {
      setQueryBusy(false);
    }
  }, []);

  const selectSuggestion = useCallback((item: ScreenerSearchItem) => {
    const symbol = String(item?.symbol || '').trim().toUpperCase();
    if (!symbol) return;
    setSearchText(`${item.name} (${symbol})`);
    setSuggestions([]);
    setSearchOpen(false);
    void loadCompany(symbol);
  }, [loadCompany]);

  const onSearchSubmit = useCallback((event: React.FormEvent) => {
    event.preventDefault();
    if (suggestions.length > 0) {
      selectSuggestion(suggestions[0]);
      return;
    }
    const clean = searchText.trim().toUpperCase();
    if (!clean) return;
    setSearchOpen(false);
    void loadCompany(clean);
  }, [suggestions, searchText, selectSuggestion, loadCompany]);

  useEffect(() => {
    if (activeSymbol || analysisBusy) return;
    void loadCompany(DEFAULT_SCREENER_SYMBOL);
  }, [activeSymbol, analysisBusy, loadCompany]);

  useEffect(() => {
    if (activeTab !== 'fundamentals') return;
    if (!activeSymbol) return;
    void loadFinancials(activeSymbol);
  }, [activeTab, activeSymbol, loadFinancials]);

  const positives = useMemo(() => getArray(summary?.positives), [summary]);
  const negatives = useMemo(() => getArray(summary?.negatives), [summary]);
  const newsRows = useMemo(() => getArray(events?.news), [events]);
  const corpRows = useMemo(() => getArray(events?.corporate), [events]);
  const corporateActionRows = useMemo(() => getArray(events?.corporate_actions), [events]);
  const insiderTradeRows = useMemo(() => getArray(events?.insider_trades), [events]);
  const annualReportRows = useMemo(() => getArray(publicDepth?.annual_reports?.items), [publicDepth]);
  const profileFacts = useMemo(() => getArray(fundamentals?.profile?.facts), [fundamentals]);
  const enforcementRows = useMemo(() => getArray(events?.enforcement), [events]);
  const peerRows = useMemo(() => getArray(peers?.items), [peers]);

  const periodColumns = useMemo(() => {
    const raw = getArray(financialsPayload?.periods);
    return raw
      .map((period: any) => {
        if (typeof period === 'string') {
          return { id: period, label: period };
        }
        const id = String(period?.id || period?.period || period?.label || '').trim();
        const label = String(period?.label || period?.period || period?.id || '').trim();
        if (!id) return null;
        return { id, label: label || id };
      })
      .filter(Boolean) as Array<{ id: string; label: string }>;
  }, [financialsPayload]);

  const ratioGroups = useMemo(() => {
    const raw = financialsPayload?.ratios || {};
    if (!raw || typeof raw !== 'object') return [];
    return Object.entries(raw)
      .map(([group, rows]) => ({
        group,
        rows: getArray(rows),
      }))
      .filter((entry) => entry.rows.length > 0);
  }, [financialsPayload]);

  const activeStatement = useMemo(() => {
    if (fundamentalSegment === 'income_statement') return financialsPayload?.income_statement || null;
    if (fundamentalSegment === 'balance_sheet') return financialsPayload?.balance_sheet || null;
    if (fundamentalSegment === 'cash_flow') return financialsPayload?.cash_flow || null;
    return null;
  }, [financialsPayload, fundamentalSegment]);

  const statementRows = useMemo(() => getArray(activeStatement?.rows), [activeStatement]);

  const freshnessItems = useMemo(() => {
    const sectionPairs: Array<[string, string]> = [
      ['quote', 'Quote'],
      ['fundamentals', 'Fundamentals'],
      ['technicals', 'Technicals'],
      ['governance', 'Governance'],
      ['news', 'News'],
      ['corporate', 'Corporate'],
    ];
    return sectionPairs.map(([key, label]) => {
      const section = freshnessSections?.[key] || {};
      return {
        key,
        label,
        status: formatFreshnessStatus(section?.status),
      };
    });
  }, [freshnessSections]);

  const renderFreshnessBadge = useCallback((key: string, label: string) => {
    const section = freshnessSections?.[key] || {};
    const statusRaw = String(section?.status || '').toLowerCase() || 'unavailable';
    const tone = ['live', 'fresh', 'available'].includes(statusRaw)
      ? 'live'
      : ['stale'].includes(statusRaw)
        ? 'stale'
        : 'unavailable';
    return (
      <span key={`${key}-${label}`} className={`screener-freshness-badge ${tone}`}>
        {label}: {formatFreshnessStatus(statusRaw)}
      </span>
    );
  }, [freshnessSections]);

  const exportSnapshotJson = useCallback(() => {
    if (!snapshot) return;
    const symbol = String(resolved?.symbol || activeSymbol || 'company').toUpperCase();
    downloadTextFile(`${symbol}-screener-snapshot.json`, JSON.stringify(snapshot, null, 2), 'application/json');
  }, [snapshot, resolved?.symbol, activeSymbol]);

  const exportRatiosCsv = useCallback(() => {
    const groups = getArray(financialsPayload?.ratios ? Object.entries(financialsPayload.ratios) : []);
    if (groups.length === 0) return;
    const rows: Array<Array<string | number | null | undefined>> = [['Group', 'Metric', 'Value', 'Unit', 'Source']];
    groups.forEach((entry: any) => {
      const group = String(entry?.[0] || 'group');
      const metrics = getArray(entry?.[1]);
      metrics.forEach((item: any) => {
        rows.push([
          group,
          String(item?.label || item?.key || ''),
          item?.value ?? item?.display ?? '',
          String(item?.unit || ''),
          String(item?.source || ''),
        ]);
      });
    });
    const symbol = String(resolved?.symbol || activeSymbol || 'company').toUpperCase();
    downloadTextFile(`${symbol}-ratios.csv`, toCsv(rows), 'text/csv;charset=utf-8');
  }, [financialsPayload, resolved?.symbol, activeSymbol]);

  const exportStatementCsv = useCallback(() => {
    if (!activeStatement) return;
    const rows = getArray(activeStatement?.rows);
    if (rows.length === 0) return;

    const headers: Array<string> = ['Metric', ...periodColumns.map((p) => p.label || p.id), 'Source'];
    const csvRows: Array<Array<string | number | null | undefined>> = [headers];

    rows.forEach((row: any) => {
      const values = row?.values || {};
      csvRows.push([
        String(row?.label || row?.key || ''),
        ...periodColumns.map((period) => values?.[period.id]),
        String(row?.source || activeStatement?.source?.name || ''),
      ]);
    });

    const symbol = String(resolved?.symbol || activeSymbol || 'company').toUpperCase();
    const segment = String(fundamentalSegment || 'statement');
    downloadTextFile(`${symbol}-${segment}.csv`, toCsv(csvRows), 'text/csv;charset=utf-8');
  }, [activeStatement, periodColumns, resolved?.symbol, activeSymbol, fundamentalSegment]);
  const renderStatementTable = () => {
    if (!activeStatement) return null;

    const source = activeStatement?.source || {};
    const sourceLine = [source?.name, source?.as_of ? `as of ${source.as_of}` : '', source?.basis || '']
      .map((item) => String(item || '').trim())
      .filter(Boolean)
      .join(' | ');

    return (
      <div className="screener-table-card">
        <div className="screener-table-meta">
          <span>{sourceLine || '—'}</span>
          <span>Values in ₹ cr (crores)</span>
        </div>
        <div className="screener-table-wrap">
          <table className="screener-table">
            <thead>
              <tr>
                <th>Metric</th>
                {periodColumns.map((period) => (
                  <th key={period.id}>{period.label}</th>
                ))}
                <th>YoY %</th>
              </tr>
            </thead>
            <tbody>
              {statementRows.map((row: any) => {
                const values = row?.values || {};
                const lastPeriod = periodColumns[periodColumns.length - 1]?.id;
                const prevPeriod = periodColumns[periodColumns.length - 2]?.id;
                const latest = Number(values?.[lastPeriod]);
                const previous = Number(values?.[prevPeriod]);
                const yoy = Number.isFinite(latest) && Number.isFinite(previous) && previous !== 0
                  ? ((latest - previous) / Math.abs(previous)) * 100
                  : null;

                return (
                  <tr key={String(row?.key || row?.label)}>
                    <td>{row?.label || row?.key || 'Metric'}</td>
                    {periodColumns.map((period) => {
                      const raw = values?.[period.id];
                      const unit = String(row?.unit || activeStatement?.unit || '').toLowerCase();
                      // EPS and per-share values show as INR, rest show as crores
                      const isPerShare = unit.includes('share') || unit.includes('eps') || 
                        String(row?.key || '').toLowerCase().includes('eps');
                      const display = isPerShare
                        ? fmtInr(raw, 2)
                        : fmtCrore(raw, 2);
                      return <td key={`${row?.key}-${period.id}`}>{display}</td>;
                    })}
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

  const content = (
    <div className={`screener-shell ${embedded ? 'embedded' : ''}`}>
      <div className="screener-search-area">
        <form className="screener-search-form" onSubmit={onSearchSubmit}>
          <Search size={18} />
          <input
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            onFocus={() => setSearchOpen(suggestions.length > 0)}
            className="screener-search-input"
            placeholder="Search company name, symbol, ISIN, or CIN"
          />
          {searchBusy && <span className="screener-search-status">Searching...</span>}
        </form>

        {searchOpen && suggestions.length > 0 && (
          <div className="screener-search-dropdown">
            {suggestions.map((item) => (
              <button
                key={`${item.symbol}-${item.cin || ''}`}
                type="button"
                className="screener-search-option"
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => selectSuggestion(item)}
              >
                <div className="screener-search-option-head">
                  <span className="screener-search-option-symbol">{item.symbol}</span>
                  <span className="screener-search-option-sector">{item.sector || '—'}</span>
                </div>
                <div className="screener-search-option-name">{item.name}</div>
                <div className="screener-search-option-meta">
                  <span>{item.source || 'resolver'}</span>
                  {formatSuggestionConfidence(item.confidence) && <span>{formatSuggestionConfidence(item.confidence)}</span>}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="screener-quick-row">
        {QUICK_SCREENER_QUERIES.map((item) => (
          <button
            key={item.id}
            type="button"
            className="screener-quick-btn"
            onClick={() => void runQuickQuery(item.query)}
            disabled={queryBusy}
          >
            {item.label}
          </button>
        ))}
      </div>
      {queryBusy && <div className="screener-loading">Running screener query...</div>}
      {!queryBusy && queryError && <div className="screener-error">{queryError}</div>}
      {!queryBusy && queryRows.length > 0 && (
        <div className="screener-quick-grid">
          {queryRows.slice(0, 12).map((row: any, idx: number) => {
            const symbol = String(row?.symbol || '').trim().toUpperCase();
            const title = String(row?.name || row?.company_name || symbol || `Result ${idx + 1}`);
            return (
              <button
                key={`${symbol || title}-${idx}`}
                type="button"
                className="screener-quick-card"
                onClick={() => {
                  if (!symbol) return;
                  setSearchText(`${title} (${symbol})`);
                  void loadCompany(symbol);
                }}
              >
                <div>{symbol || '—'}</div>
                <div>{title}</div>
              </button>
            );
          })}
        </div>
      )}

      {!activeSymbol && !analysisBusy && (
        <div className="screener-empty-state">
          Select a company from search suggestions to open full screener analysis.
        </div>
      )}

      {analysisBusy && (
        <div className="screener-loading-stack">
          <div className="screener-loading">Loading full analysis...</div>
          <div className="screener-skeleton-card" />
          <div className="screener-skeleton-grid">
            <div className="screener-skeleton-card" />
            <div className="screener-skeleton-card" />
            <div className="screener-skeleton-card" />
          </div>
        </div>
      )}
      {!analysisBusy && analysisError && <div className="screener-error">{analysisError}</div>}

      {!analysisBusy && snapshot && (
        <>
          <div className="screener-head-card">
            <div className="screener-company-meta">
              <div className="screener-company-symbol">
                <Building2 size={16} />
                <span>{resolved?.symbol || activeSymbol}</span>
              </div>
              <h2>{resolved?.company_name || activeSymbol}</h2>
              <div className="screener-company-sub">
                <span>{resolved?.sector || '—'}</span>
                {resolved?.cin && <span>CIN: {resolved.cin}</span>}
                {resolved?.isin && <span>ISIN: {resolved.isin}</span>}
              </div>
            </div>
            <div className="screener-head-metrics">
              <div className="screener-head-price">{fmtInr(livePrice, 2)}</div>
              <div className={`screener-head-change ${trendTone(liveChangePct)}`}>
                {Number(liveChangePct) >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                {fmtPct(liveChangePct, 2)}
              </div>
              <div className="screener-score-pill">
                <Gauge size={14} />
                Score {fmtNum(score?.prospekt_score, 1)} ({score?.grade || '—'})
              </div>
              <div className="screener-quote-source">Quote: {liveSource || '—'}</div>
              <div className="screener-actions-row">
                <button type="button" className="screener-action-btn" onClick={exportSnapshotJson} disabled={!snapshot}>
                  <Download size={13} /> Export Snapshot
                </button>
                <button
                  type="button"
                  className="screener-action-btn"
                  onClick={() => {
                    if (activeTab !== 'fundamentals') return;
                    if (fundamentalSegment === 'ratios') {
                      exportRatiosCsv();
                    } else {
                      exportStatementCsv();
                    }
                  }}
                  disabled={activeTab !== 'fundamentals' || (fundamentalSegment === 'ratios' ? ratioGroups.length === 0 : statementRows.length === 0)}
                >
                  <Download size={13} /> Export {fundamentalSegment === 'ratios' ? 'Ratios' : 'Statement'}
                </button>
              </div>
            </div>
          </div>

          <div className="screener-tabbar">
            <button type="button" className={activeTab === 'overview' ? 'active' : ''} onClick={() => setActiveTab('overview')}>Overview</button>
            <button type="button" className={activeTab === 'fundamentals' ? 'active' : ''} onClick={() => setActiveTab('fundamentals')}>Fundamentals</button>
            <button type="button" className={activeTab === 'technicals' ? 'active' : ''} onClick={() => setActiveTab('technicals')}>Technicals</button>
            <button type="button" className={activeTab === 'governance' ? 'active' : ''} onClick={() => setActiveTab('governance')}>Governance</button>
            <button type="button" className={activeTab === 'events' ? 'active' : ''} onClick={() => setActiveTab('events')}>News & Corporate</button>
          </div>

          <div className="screener-freshness-row">
            {freshnessItems.map((item) => renderFreshnessBadge(item.key, item.label))}
          </div>

          <div className="screener-content">
            {activeTab === 'overview' && (
              <div className="screener-section-grid">
                {/* Key Metrics Summary */}
                <div className="screener-section screener-section-wide">
                  <div className="screener-section-head"><Gauge size={14} /> Key Metrics</div>
                  <div className="screener-key-metrics-grid">
                    <div className="screener-metric-item">
                      <span className="screener-metric-label">Market Cap</span>
                      <span className="screener-metric-value">{fmtMarketCap(fundamentals?.metrics?.market_cap || quote?.market_cap, true)}</span>
                    </div>
                    <div className="screener-metric-item">
                      <span className="screener-metric-label">P/E Ratio</span>
                      <span className="screener-metric-value">{fmtNum(fundamentals?.metrics?.pe_ratio || quote?.pe_ratio, 2)}</span>
                    </div>
                    <div className="screener-metric-item">
                      <span className="screener-metric-label">P/B Ratio</span>
                      <span className="screener-metric-value">{fmtNum(fundamentals?.metrics?.pb_ratio || quote?.pb_ratio, 2)}</span>
                    </div>
                    <div className="screener-metric-item">
                      <span className="screener-metric-label">EPS (TTM)</span>
                      <span className="screener-metric-value">{fmtInr(fundamentals?.metrics?.eps || quote?.eps, 2)}</span>
                    </div>
                    <div className="screener-metric-item">
                      <span className="screener-metric-label">Book Value</span>
                      <span className="screener-metric-value">{fmtInr(fundamentals?.metrics?.book_value || quote?.book_value, 2)}</span>
                    </div>
                    <div className="screener-metric-item">
                      <span className="screener-metric-label">Dividend Yield</span>
                      <span className="screener-metric-value">{fmtPct(fundamentals?.metrics?.dividend_yield, 2)}</span>
                    </div>
                    <div className="screener-metric-item">
                      <span className="screener-metric-label">ROE</span>
                      <span className="screener-metric-value">{fmtPct(fundamentals?.metrics?.roe, 2)}</span>
                    </div>
                    <div className="screener-metric-item">
                      <span className="screener-metric-label">ROCE</span>
                      <span className="screener-metric-value">{fmtPct(fundamentals?.metrics?.roce, 2)}</span>
                    </div>
                    <div className="screener-metric-item">
                      <span className="screener-metric-label">Debt/Equity</span>
                      <span className="screener-metric-value">{fmtNum(fundamentals?.metrics?.debt_to_equity, 2)}</span>
                    </div>
                    <div className="screener-metric-item">
                      <span className="screener-metric-label">52W High</span>
                      <span className="screener-metric-value">{fmtInr(technicals?.high_52w || quote?.high_52w, 2)}</span>
                    </div>
                    <div className="screener-metric-item">
                      <span className="screener-metric-label">52W Low</span>
                      <span className="screener-metric-value">{fmtInr(technicals?.low_52w || quote?.low_52w, 2)}</span>
                    </div>
                    <div className="screener-metric-item">
                      <span className="screener-metric-label">Avg Volume</span>
                      <span className="screener-metric-value">{fmtVolume(quote?.avg_volume || technicals?.avg_volume)}</span>
                    </div>
                  </div>
                </div>

                <div className="screener-section screener-section-wide">
                  <div className="screener-section-head"><Building2 size={14} /> Company Profile</div>
                  <p className="screener-longtext">{fundamentals?.profile?.business_summary || fundamentals?.profile?.overview || 'Business overview is not available from public sources yet.'}</p>
                  {profileFacts.length > 0 ? (
                    <div className="screener-facts-grid">
                      {profileFacts.map((fact: any, idx: number) => (
                        <div key={`fact-${idx}`} className="screener-fact">
                          <span className="screener-fact-label">{fact?.label}</span>
                          <span className="screener-fact-value">{displayText(fact?.value)}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="screener-empty-inline">Company facts not available.</div>
                  )}
                  {(fundamentals?.profile?.mission || fundamentals?.profile?.vision) && (
                    <div className="screener-overview-points">
                      {fundamentals?.profile?.mission && <div><strong>Mission:</strong> {fundamentals.profile.mission}</div>}
                      {fundamentals?.profile?.vision && <div><strong>Vision:</strong> {fundamentals.profile.vision}</div>}
                    </div>
                  )}
                  {getArray(fundamentals?.profile?.products_services).length > 0 && (
                    <div className="screener-section-note">Products/Services: {getArray(fundamentals?.profile?.products_services).slice(0, 6).join(' | ')}</div>
                  )}
                </div>

                <div className="screener-section">
                  <div className="screener-section-head"><ArrowUpRight size={14} /> Positive / Negative</div>
                  <div className="screener-bullets">
                    <div>
                      <h4>Positives</h4>
                      {positives.slice(0, 6).map((item: string, idx: number) => (
                        <p key={`p-${idx}`}>+ {item}</p>
                      ))}
                    </div>
                    <div>
                      <h4>Negatives</h4>
                      {negatives.slice(0, 6).map((item: string, idx: number) => (
                        <p key={`n-${idx}`}>- {item}</p>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="screener-section">
                  <div className="screener-section-head"><Building2 size={14} /> Peer Comparison</div>
                  {peerRows.length > 0 ? (
                    <div className="screener-mini-table-wrap">
                      <table className="screener-mini-table">
                        <thead>
                          <tr>
                            <th>Peer</th>
                            <th>P/E</th>
                            <th>ROE</th>
                            <th>ROCE</th>
                            <th>Debt/Eq</th>
                          </tr>
                        </thead>
                        <tbody>
                          {peerRows.map((row: any) => (
                            <tr key={row.symbol}>
                              <td>{row.symbol}</td>
                              <td>{fmtNum(row.pe_ratio, 2)}</td>
                              <td>{fmtPct(row.roe, 2)}</td>
                              <td>{fmtPct(row.roce, 2)}</td>
                              <td>{fmtNum(row.debt_to_equity, 2)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="screener-empty-inline">Peer data not available.</div>
                  )}
                  <div className="screener-section-note">{peers?.source || '—'}</div>
                </div>

                <div className="screener-section">
                  <div className="screener-section-head"><Database size={14} /> Public-Source Depth</div>
                  <div className="screener-tech-grid">
                    <div>Segments: <strong>{formatFreshnessStatus(publicDepth?.segments?.status)}</strong></div>
                    <div>Related Parties: <strong>{formatFreshnessStatus(publicDepth?.related_party_transactions?.status)}</strong></div>
                    <div>Annual Reports: <strong>{formatFreshnessStatus(publicDepth?.annual_reports?.status)}</strong></div>
                    <div>Auditor Remarks: <strong>{formatFreshnessStatus(publicDepth?.auditor_remarks?.status)}</strong></div>
                    <div>Delivery %: <strong>{Number.isFinite(Number(publicDepth?.delivery_pct?.delivery_pct)) ? fmtPct(publicDepth?.delivery_pct?.delivery_pct, 2) : formatFreshnessStatus(publicDepth?.delivery_pct?.status)}</strong></div>
                    <div>Corporate Actions: <strong>{formatFreshnessStatus(publicDepth?.corporate_actions?.status)}</strong></div>
                    <div>Insider Trades: <strong>{formatFreshnessStatus(publicDepth?.insider_trades?.status)}</strong></div>
                  </div>
                  {getArray(publicDepth?.segments?.segments).length > 0 && (
                    <div className="screener-section-note">Segments found: {getArray(publicDepth?.segments?.segments).slice(0, 8).join(' | ')}</div>
                  )}
                  {annualReportRows.length > 0 && (
                    <div className="screener-section-note">
                      Latest annual report: <a href={annualReportRows[0]?.url || publicDepth?.annual_reports?.latest_url || '#'} target="_blank" rel="noreferrer">FY {annualReportRows[0]?.year || publicDepth?.annual_reports?.latest_year || 'latest'}</a>
                    </div>
                  )}
                  {publicDepth?.delivery_pct?.as_of && (
                    <div className="screener-section-note">Delivery data as of {displayText(publicDepth?.delivery_pct?.as_of, 'latest exchange archive')} via {displayText(publicDepth?.delivery_pct?.source, 'NSE public archives')}</div>
                  )}
                  <div className="screener-section-note">No paid APIs used. Restricted values stay labelled instead of inferred.</div>
                </div>

                <div className="screener-section">
                  <div className="screener-section-head"><AlertTriangle size={14} /> Contradictions / Blind Spots</div>
                  {contradictions.length === 0 ? (
                    <div className="screener-empty-inline">No material contradiction detected in this snapshot.</div>
                  ) : (
                    contradictions.map((item: any, idx: number) => (
                      <div key={`c-${idx}`} className="screener-contradiction">
                        <div className="screener-contradiction-title">{item.title}</div>
                        <div className="screener-contradiction-detail">{item.detail}</div>
                      </div>
                    ))
                  )}
                </div>

              </div>
            )}

            {activeTab === 'fundamentals' && (
              <div className="screener-section-grid">
                <div className="screener-segmented">
                  <button type="button" className={fundamentalSegment === 'ratios' ? 'active' : ''} onClick={() => setFundamentalSegment('ratios')}>Ratios</button>
                  <button type="button" className={fundamentalSegment === 'income_statement' ? 'active' : ''} onClick={() => setFundamentalSegment('income_statement')}>Income Statement</button>
                  <button type="button" className={fundamentalSegment === 'balance_sheet' ? 'active' : ''} onClick={() => setFundamentalSegment('balance_sheet')}>Balance Sheet</button>
                  <button type="button" className={fundamentalSegment === 'cash_flow' ? 'active' : ''} onClick={() => setFundamentalSegment('cash_flow')}>Cash Flow</button>
                </div>

                {financialsBusy ? (
                  <div className="screener-loading-stack">
                    <div className="screener-empty-inline">Loading financial statements...</div>
                    <div className="screener-skeleton-card" />
                  </div>
                ) : financialsError ? (
                  <div className="screener-error">{financialsError}</div>
                ) : fundamentalSegment === 'ratios' ? (
                  <div className="screener-ratio-groups">
                    {ratioGroups.map((group) => (
                      <div key={group.group} className="screener-ratio-group">
                        <div className="screener-ratio-group-title">{String(group.group).replace(/_/g, ' ')}</div>
                        <div className="screener-metric-grid">
                          {group.rows.map((item: any) => (
                            <div key={`${group.group}-${item.key || item.label}`} className="screener-metric-card">
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
                        <div className="screener-section-head"><Gauge size={14} /> Derived Public Analytics</div>
                        <div className="screener-tech-grid">
                          <div>DCF Fair Value: <strong>{fmtInr(financialAnalytics?.dcf?.fair_value_per_share, 2)}</strong></div>
                          <div>DCF Upside: <strong>{fmtPct(financialAnalytics?.dcf?.upside_pct, 2)}</strong></div>
                          <div>Piotroski F-Score: <strong>{fmtNum(financialAnalytics?.piotroski?.score, 0)}</strong></div>
                          <div>DuPont ROE: <strong>{fmtPct(financialAnalytics?.dupont?.roe_pct, 2)}</strong></div>
                          <div>Asset Turnover: <strong>{fmtNum(financialAnalytics?.dupont?.asset_turnover, 3)}</strong></div>
                          <div>Equity Multiplier: <strong>{fmtNum(financialAnalytics?.dupont?.equity_multiplier, 2)}</strong></div>
                        </div>
                        <div className="screener-section-note">{financialAnalytics?.dcf?.source || financialAnalytics?.source || 'Derived from public statements where available.'}</div>
                      </div>
                    )}
                    {ratioGroups.length === 0 && (
                      <div className="screener-empty-inline">Ratio data not available.</div>
                    )}
                  </div>
                ) : (
                  renderStatementTable()
                )}
              </div>
            )}

            {activeTab === 'technicals' && (
              <div className="screener-section-grid">
                <div className="screener-section">
                  <div className="screener-section-head"><CandlestickChart size={14} /> Technical Structure</div>
                  <div className="screener-tech-grid">
                    <div>Trend Bias: <strong>{technicals?.trend_bias || '—'}</strong></div>
                    <div>RSI (14): <strong>{fmtNum(technicals?.rsi14, 2)}</strong></div>
                    <div>MACD: <strong>{fmtNum(technicals?.macd, 4)}</strong></div>
                    <div>MACD Signal: <strong>{fmtNum(technicals?.macd_signal, 4)}</strong></div>
                    <div>SMA 20/50: <strong>{displayText(technicals?.sma20_50_signal)}</strong></div>
                    <div>SMA 50/200: <strong>{displayText(technicals?.sma50_200_signal)}</strong></div>
                    <div>Above 200 DMA: <strong>{technicals?.above_200dma ? 'Yes' : 'No'}</strong></div>
                    <div>Breakout State: <strong>{technicals?.breakout_state || '—'}</strong></div>
                    <div>1M Return: <strong>{fmtPct(technicals?.return_1m_pct, 2)}</strong></div>
                    <div>3M Return: <strong>{fmtPct(technicals?.return_3m_pct, 2)}</strong></div>
                    <div>Volatility (1M ann.): <strong>{fmtPct(technicals?.volatility_1m_annualized_pct, 2)}</strong></div>
                    <div>52W Drawdown: <strong>{fmtPct(technicals?.drawdown_from_52w_high_pct, 2)}</strong></div>
                  </div>
                </div>
                <div className="screener-section">
                  <div className="screener-section-head"><CircleDot size={14} /> Price Structure</div>
                  <Sparkline prices={getArray(technicals?.history?.prices) as number[]} />
                  <div className="screener-tech-grid screener-tech-grid-spaced">
                    <div>20 DMA: <strong>{fmtInr(technicals?.sma20, 2)}</strong></div>
                    <div>50 DMA: <strong>{fmtInr(technicals?.sma50, 2)}</strong></div>
                    <div>200 DMA: <strong>{fmtInr(technicals?.sma200, 2)}</strong></div>
                    <div>Bollinger: <strong>{displayText(technicals?.bollinger_state)}</strong></div>
                    <div>Upper Band: <strong>{fmtInr(technicals?.bollinger_upper, 2)}</strong></div>
                    <div>Lower Band: <strong>{fmtInr(technicals?.bollinger_lower, 2)}</strong></div>
                    <div>20D Support: <strong>{fmtInr(technicals?.support_20d, 2)}</strong></div>
                    <div>20D Resistance: <strong>{fmtInr(technicals?.resistance_20d, 2)}</strong></div>
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'governance' && (
              <div className="screener-section-grid">
                <div className="screener-section">
                  <div className="screener-section-head"><ShieldCheck size={14} /> Governance, Promoters, Insiders</div>
                  <div className="screener-tech-grid">
                    <div>Governance Band: <strong>{displayText(governance?.band, formatFreshnessStatus(governance?.status))}</strong></div>
                    <div>Governance Score: <strong>{fmtNum(governance?.score, 1)}</strong></div>
                    <div>Promoter Holding: <strong>{fmtPct(fundamentals?.metrics?.promoter_holding_pct, 2)}</strong></div>
                    <div>Promoter Pledge: <strong>{fmtPct(fundamentals?.metrics?.promoter_pledge_pct, 2)}</strong></div>
                    <div>FII Holding: <strong>{fmtPct(fundamentals?.metrics?.fii_holding_pct, 2)}</strong></div>
                    <div>DII Holding: <strong>{fmtPct(fundamentals?.metrics?.dii_holding_pct, 2)}</strong></div>
                    <div>Public Holding: <strong>{fmtPct(fundamentals?.metrics?.public_holding_pct, 2)}</strong></div>
                    <div>Institutional Holding: <strong>{fmtPct(fundamentals?.metrics?.institutional_holding_pct, 2)}</strong></div>
                    <div>Directors Tracked: <strong>{snapshot?.insiders?.counts?.directors ?? 0}</strong></div>
                    <div>Insider Facts: <strong>{snapshot?.insiders?.counts?.insider_facts ?? 0}</strong></div>
                  </div>
                  <div className="screener-section-note">
                    Shareholding source: {displayText(fundamentals?.sources?.shareholding || fundamentals?.sources?.snapshot || sourceHealth?.shareholding?.status)}
                  </div>
                  <div className="screener-flag-list">
                    {getArray(governance?.flags).length > 0 ? getArray(governance?.flags).slice(0, 8).map((flag: any, idx: number) => (
                      <div key={`f-${idx}`} className="screener-flag-row">
                        <span>{flag.code || 'FLAG'}</span>
                        <span>{displayText(flag.detail)}</span>
                      </div>
                    )) : (
                      <div className="screener-empty-inline">No governance flags returned by the current public-source pass.</div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'events' && (
              <div className="screener-section-grid">
                <div className="screener-section">
                  <div className="screener-section-head"><ArrowUpRight size={14} /> Latest News</div>
                  <div className="screener-event-list">
                    {newsRows.slice(0, 14).map((row: any, idx: number) => (
                      <a key={`n-${idx}`} href={row.url || '#'} target="_blank" rel="noreferrer" className="screener-event-row">
                        <div>{displayText(row.headline, 'Market update')}</div>
                        <div className="screener-event-meta">
                          <span>{displayText(row.source, 'News')}</span>
                          <span>{displayText(row.age, formatEventPublished(row.published))}</span>
                          <span className={`screener-sentiment ${sentimentTone(row.sentiment)}`}>{displayText(row.sentiment?.label, 'neutral')}</span>
                        </div>
                      </a>
                    ))}
                    {newsRows.length === 0 && <div className="screener-empty-inline">No news items available.</div>}
                  </div>
                </div>
                <div className="screener-section">
                  <div className="screener-section-head"><Building2 size={14} /> Corporate & Enforcement</div>
                  <div className="screener-event-list">
                    {corpRows.slice(0, 12).map((row: any, idx: number) => (
                      <a key={`c-${idx}`} href={row.url || '#'} target="_blank" rel="noreferrer" className="screener-event-row">
                        <div>{displayText(row.title, 'Corporate disclosure')}</div>
                        <div className="screener-event-meta">
                          <span>{displayText(row.event_type || row.category, 'corporate_disclosure')}</span>
                          <span>{displayText(row.source, 'Exchange')}</span>
                          <span>{formatEventPublished(row.published)}</span>
                          <span className={`screener-sentiment ${sentimentTone(row.sentiment)}`}>{displayText(row.sentiment?.label, 'neutral')}</span>
                        </div>
                      </a>
                    ))}
                    {corpRows.length === 0 && <div className="screener-empty-inline">No corporate disclosures available.</div>}
                  </div>
                  {enforcementRows.length > 0 && (
                    <div className="screener-enforcement">
                      <h4>Enforcement Signals</h4>
                      {enforcementRows.slice(0, 8).map((row: any, idx: number) => (
                        <div key={`e-${idx}`} className="screener-flag-row">
                          <span>{row.violation_type || row.label || 'Regulatory item'}</span>
                          <span>{row.order_date || row.updated_at || ''}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="screener-section">
                  <div className="screener-section-head"><CandlestickChart size={14} /> Corporate Actions Calendar</div>
                  <div className="screener-event-list">
                    {corporateActionRows.slice(0, 10).map((row: any, idx: number) => (
                      <a key={`ca-${idx}`} href={row.url || '#'} target="_blank" rel="noreferrer" className="screener-event-row">
                        <div>{displayText(row.title, 'Corporate action')}</div>
                        <div className="screener-event-meta">
                          <span>{displayText(row.event_type, 'corporate_action')}</span>
                          <span>{formatEventPublished(row.published)}</span>
                          <span>{displayText(row.source, 'Exchange')}</span>
                        </div>
                      </a>
                    ))}
                    {corporateActionRows.length === 0 && <div className="screener-empty-inline">No corporate-action rows detected in the latest exchange disclosures.</div>}
                  </div>
                </div>
                <div className="screener-section">
                  <div className="screener-section-head"><ShieldCheck size={14} /> Insider Trades</div>
                  <div className="screener-event-list">
                    {insiderTradeRows.slice(0, 8).map((row: any, idx: number) => (
                      <a key={`it-${idx}`} href={row.url || '#'} target="_blank" rel="noreferrer" className="screener-event-row">
                        <div>{displayText(row.title, 'Insider disclosure')}</div>
                        <div className="screener-event-meta">
                          <span>{displayText(row.event_type, 'insider_trade_disclosure')}</span>
                          <span>{formatEventPublished(row.published)}</span>
                          <span>{displayText(row.source, 'Exchange')}</span>
                        </div>
                      </a>
                    ))}
                    {insiderTradeRows.length === 0 && <div className="screener-empty-inline">No insider-trade disclosures detected in the latest exchange feed.</div>}
                  </div>
                </div>
              </div>
            )}

            <footer className="screener-footer">
              <span>Active symbol: {resolved?.symbol || activeSymbol}</span>
              <span>Freshness: quote {formatAge(freshness?.quote_age_seconds, 's')}, history {formatAge(freshness?.age_hours?.history, 'h')}, news {formatAge(freshness?.age_hours?.news, 'h')}</span>
            </footer>
          </div>
        </>
      )}
    </div>
  );

  const wrappedContent = <ScreenerRenderBoundary>{content}</ScreenerRenderBoundary>;
  if (embedded) return wrappedContent;
  return <AppShell title="Screener">{wrappedContent}</AppShell>;
};

export default ScreenerWorkspace;


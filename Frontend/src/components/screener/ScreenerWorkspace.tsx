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

const fmtNum = (value: any, digits = 2) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'Unavailable';
  return n.toFixed(digits);
};

const fmtPct = (value: any, digits = 2) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'Unavailable';
  return `${n.toFixed(digits)}%`;
};

const fmtInr = (value: any, digits = 2) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'Unavailable';
  return `Rs ${n.toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: digits })}`;
};

const fmtCrore = (value: any, digits = 2) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'Unavailable';
  return `Rs ${n.toLocaleString('en-IN', { maximumFractionDigits: digits, minimumFractionDigits: digits })} Cr`;
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
  if (unit.includes('crore')) return fmtCrore(item?.value, 2);
  if (unit.includes('inr')) return fmtInr(item?.value, 2);
  return fmtNum(item?.value, 2);
};

const formatFreshnessStatus = (value: any) => {
  const status = String(value || '').toLowerCase();
  if (!status) return 'Unavailable';
  if (status === 'live' || status === 'available') return 'Live';
  if (status === 'fresh') return 'Fresh';
  if (status === 'stale') return 'Stale';
  if (status === 'aging') return 'Aging';
  if (status === 'ok') return 'OK';
  if (status === 'unavailable') return 'Unavailable';
  return status.replace(/_/g, ' ').replace(/\b\w/g, (match) => match.toUpperCase());
};

const displayText = (value: any, fallback = 'Not disclosed') => {
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
  return text || 'time unavailable';
};

const formatAge = (value: any, unit: 's' | 'h') => {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'unavailable';
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
    if (/[\",\n]/.test(textCell)) {
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
    // eslint-disable-next-line no-console
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

  const loadCompany = async (symbol: string) => {
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
    } catch (err: any) {
      setAnalysisPayload(null);
      setAnalysisError(err?.message || 'Failed to load screener analysis.');
    }
    setAnalysisBusy(false);
  };

  const loadFinancials = async (symbol: string) => {
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
    } catch (err: any) {
      setFinancialsPayload(null);
      setFinancialsSymbol(clean);
      setFinancialsError(err?.message || 'Failed to load financial statements.');
    } finally {
      setFinancialsBusy(false);
    }
  };

  const runQuickQuery = async (query: string) => {
    if (!query.trim()) return;
    setQueryBusy(true);
    setQueryError('');
    try {
      const data = await runScreenerQuery(query, 20);
      const rows = getArray(data?.matches);
      setQueryRows(rows);
      setQueryError(rows.length > 0 ? '' : 'No stocks matched this query yet.');
    } catch (err: any) {
      setQueryRows([]);
      setQueryError(err?.message || 'Failed to run screener query.');
    } finally {
      setQueryBusy(false);
    }
  };

  const selectSuggestion = (item: ScreenerSearchItem) => {
    const symbol = String(item?.symbol || '').trim().toUpperCase();
    if (!symbol) return;
    setSearchText(`${item.name} (${symbol})`);
    setSuggestions([]);
    setSearchOpen(false);
    void loadCompany(symbol);
  };

  const onSearchSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (suggestions.length > 0) {
      selectSuggestion(suggestions[0]);
      return;
    }
    const clean = searchText.trim().toUpperCase();
    if (!clean) return;
    setSearchOpen(false);
    void loadCompany(clean);
  };

  useEffect(() => {
    if (activeSymbol || analysisBusy) return;
    void loadCompany(DEFAULT_SCREENER_SYMBOL);
  }, [activeSymbol, analysisBusy]);

  useEffect(() => {
    if (activeTab !== 'fundamentals') return;
    if (!activeSymbol) return;
    void loadFinancials(activeSymbol);
  }, [activeTab, activeSymbol]);

  const positives = useMemo(() => getArray(summary?.positives), [summary]);
  const negatives = useMemo(() => getArray(summary?.negatives), [summary]);
  const newsRows = useMemo(() => getArray(events?.news), [events]);
  const corpRows = useMemo(() => getArray(events?.corporate), [events]);
  const corporateActionRows = useMemo(() => getArray(events?.corporate_actions), [events]);
  const insiderTradeRows = useMemo(() => getArray(events?.insider_trades), [events]);
  const annualReportRows = useMemo(() => getArray(publicDepth?.annual_reports?.items), [publicDepth]);
  const enforcementRows = useMemo(() => getArray(events?.enforcement), [events]);
  const peerRows = useMemo(() => getArray(peers?.items), [peers]);
  const sourceHealthRows = useMemo(() => Object.entries(sourceHealth || {}).map(([key, value]: [string, any]) => ({
    key,
    label: key.replace(/_/g, ' '),
    status: formatFreshnessStatus(value?.status),
    count: value?.count,
  })), [sourceHealth]);

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
          <span>{sourceLine || 'Source unavailable'}</span>
          <span>{activeStatement?.unit || 'INR crore'}</span>
        </div>
        <div className="screener-table-wrap">
          <table className="screener-table">
            <thead>
              <tr>
                <th>Metric</th>
                {periodColumns.map((period) => (
                  <th key={period.id}>{period.label}</th>
                ))}
                <th>YoY</th>
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
                      const display = unit.includes('share')
                        ? fmtInr(raw, 2)
                        : unit.includes('inr')
                          ? fmtCrore(raw, 2)
                          : fmtNum(raw, 2);
                      return <td key={`${row?.key}-${period.id}`}>{display}</td>;
                    })}
                    <td className={Number.isFinite(yoy) ? (Number(yoy) >= 0 ? 'up' : 'down') : ''}>
                      {Number.isFinite(yoy) ? `${Number(yoy).toFixed(2)}%` : 'Unavailable'}
                    </td>
                  </tr>
                );
              })}
              {statementRows.length === 0 && (
                <tr>
                  <td colSpan={periodColumns.length + 2} className="screener-table-empty">
                    Financial statement data is unavailable for this company right now.
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
                  <span className="screener-search-option-sector">{item.sector || 'Sector unavailable'}</span>
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
                <div>{symbol || 'Unavailable'}</div>
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
                <span>{resolved?.sector || 'Sector unavailable'}</span>
                {resolved?.cin && <span>CIN: {resolved.cin}</span>}
                {resolved?.isin && <span>ISIN: {resolved.isin}</span>}
              </div>
            </div>
            <div className="screener-head-metrics">
              <div className="screener-head-price">{fmtInr(quote?.price, 2)}</div>
              <div className={`screener-head-change ${trendTone(quote?.change_pct)}`}>
                {Number(quote?.change_pct) >= 0 ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                {fmtPct(quote?.change_pct, 2)}
              </div>
              <div className="screener-score-pill">
                <Gauge size={14} />
                Score {fmtNum(score?.prospekt_score, 1)} ({score?.grade || 'Unavailable'})
              </div>
              <div className="screener-quote-source">Quote source: {quote?.source || 'Unavailable'}</div>
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
                <div className="screener-section">
                  <div className="screener-section-head"><Database size={14} /> Company Fundamentals</div>
                  <p className="screener-longtext">{fundamentals?.profile?.overview || fundamentals?.profile?.business_summary || 'Overview is not available from public sources yet.'}</p>
                  <div className="screener-overview-points">
                    <div><strong>Mission:</strong> {displayText(fundamentals?.profile?.mission)}</div>
                    <div><strong>Vision:</strong> {displayText(fundamentals?.profile?.vision)}</div>
                    <div><strong>Products/Services:</strong> {displayText(getArray(fundamentals?.profile?.products_services).slice(0, 4).join(' | '))}</div>
                    <div><strong>Clients:</strong> {displayText(getArray(fundamentals?.profile?.clients).slice(0, 4).join(' | '), 'Not separately disclosed')}</div>
                  </div>
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
                    <div className="screener-empty-inline">Peer set is unavailable from current public-source lookup.</div>
                  )}
                  <div className="screener-section-note">{peers?.source || 'Peer source unavailable'}</div>
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

                <div className="screener-section">
                  <div className="screener-section-head"><ShieldCheck size={14} /> Source Health</div>
                  <div className="screener-health-grid">
                    {sourceHealthRows.map((item) => (
                      <div key={item.key} className="screener-health-pill">
                        <span>{item.label}</span>
                        <strong>{item.status}{item.count !== undefined ? ` (${item.count})` : ''}</strong>
                      </div>
                    ))}
                    {sourceHealthRows.length === 0 && <div className="screener-empty-inline">Source diagnostics are unavailable.</div>}
                  </div>
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
                              <div className="screener-metric-source">{item.source || 'Source unavailable'}</div>
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
                      <div className="screener-empty-inline">Ratio data is currently unavailable.</div>
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
                    <div>Trend Bias: <strong>{technicals?.trend_bias || 'Unavailable'}</strong></div>
                    <div>RSI (14): <strong>{fmtNum(technicals?.rsi14, 2)}</strong></div>
                    <div>MACD: <strong>{fmtNum(technicals?.macd, 4)}</strong></div>
                    <div>MACD Signal: <strong>{fmtNum(technicals?.macd_signal, 4)}</strong></div>
                    <div>SMA 20/50: <strong>{displayText(technicals?.sma20_50_signal, 'Unavailable')}</strong></div>
                    <div>SMA 50/200: <strong>{displayText(technicals?.sma50_200_signal, 'Unavailable')}</strong></div>
                    <div>Above 200 DMA: <strong>{technicals?.above_200dma ? 'Yes' : 'No'}</strong></div>
                    <div>Breakout State: <strong>{technicals?.breakout_state || 'Unavailable'}</strong></div>
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
                    <div>Bollinger: <strong>{displayText(technicals?.bollinger_state, 'Unavailable')}</strong></div>
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
                    Shareholding source: {displayText(fundamentals?.sources?.shareholding || fundamentals?.sources?.snapshot || sourceHealth?.shareholding?.status, 'Source unavailable')}
                  </div>
                  <div className="screener-flag-list">
                    {getArray(governance?.flags).length > 0 ? getArray(governance?.flags).slice(0, 8).map((flag: any, idx: number) => (
                      <div key={`f-${idx}`} className="screener-flag-row">
                        <span>{flag.code || 'FLAG'}</span>
                        <span>{displayText(flag.detail, 'Governance signal present')}</span>
                      </div>
                    )) : (
                      <div className="screener-empty-inline">No governance flags returned by the current public-source pass.</div>
                    )}
                  </div>
                </div>
                <div className="screener-section">
                  <div className="screener-section-head"><Database size={14} /> Governance Source Health</div>
                  <div className="screener-health-grid">
                    {['governance', 'shareholding', 'corporate', 'enforcement'].map((key) => {
                      const item = sourceHealth?.[key] || {};
                      return (
                        <div key={key} className="screener-health-pill">
                          <span>{key.replace(/_/g, ' ')}</span>
                          <strong>{formatFreshnessStatus(item?.status)}</strong>
                          {item?.count !== undefined && <em>{item.count} rows</em>}
                        </div>
                      );
                    })}
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

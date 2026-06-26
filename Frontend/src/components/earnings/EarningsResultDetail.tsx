import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  ExternalLink,
  FileText,
  Loader2,
  AlertCircle,
} from 'lucide-react';
import {
  EarningsResultResponse,
  EarningsAISummary,
  EarningsFinancialRow,
  EarningsDocumentLink,
  getEarningsResult,
} from '../../api/client';
import EarningsQuarterTabs from './EarningsQuarterTabs';

interface EarningsResultDetailProps {
  symbol: string;
  date: string;
  companyName?: string;
  onBack: () => void;
}

// Transcript tab removed - 'highlights' | 'documents' only
type DetailTab = 'highlights' | 'documents';

// -- formatting helpers --------------------------------------------------

const fmtINR = (v?: number | null, unit?: string): string => {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  if (unit === '%') return `${v.toFixed(1)}%`;
  if (unit === 'Rs') return `₹${v.toFixed(2)}`;
  // Rs Cr
  if (Math.abs(v) >= 1000) {
    return `₹${(v / 1000).toFixed(2)}K Cr`;
  }
  return `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })} Cr`;
};

const fmtPct = (v?: number | null): string => {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const prefix = v > 0 ? '+' : '';
  return `${prefix}${v.toFixed(2)}%`;
};

const fmtPrice = (v?: number | null): string => {
  if (v === null || v === undefined) return '—';
  return `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
};

const changeClass = (v?: number | null, higherIsGood = true): string => {
  if (v == null || Number.isNaN(v) || v === 0) return 'neutral';
  return (higherIsGood ? v > 0 : v < 0) ? 'positive' : 'negative';
};

// -- sub-components ------------------------------------------------------

const KeyMetricsSummary: React.FC<{ rows: EarningsFinancialRow[] }> = ({ rows }) => {
  const rowsMap = Object.fromEntries(rows.map((r) => [r.key, r]));
  const metrics = [
    { key: 'revenue', label: 'Revenue', unit: 'Rs Cr' },
    { key: 'eps', label: 'EPS', unit: 'Rs' },
    { key: 'pat', label: 'PAT', unit: 'Rs Cr' },
  ];
  const visible = metrics.filter((m) => rowsMap[m.key]?.current != null);
  if (!visible.length) return null;

  return (
    <div className="erd-key-metrics">
      <h4 className="erd-section-title">Key Metrics</h4>
      <div className="erd-key-metrics-table">
        <div className="erd-key-metrics-head">
          <span>Metric</span>
          <span>Current</span>
          <span>vs Last Quarter</span>
          <span>vs Last Year Same Quarter</span>
        </div>
        {visible.map((m) => {
          const row = rowsMap[m.key];
          return (
            <div key={m.key} className="erd-key-metrics-row">
              <span className="erd-key-metrics-label">
                {m.label}
                <span className="erd-key-metrics-unit">{m.unit}</span>
              </span>
              <span className="erd-key-metrics-value">{fmtINR(row.current, m.unit)}</span>
              <span className="erd-key-metrics-comparison">
                <span className="erd-key-metrics-base">
                  {fmtINR(row.previous_quarter, m.unit)}
                </span>
                <span className={`erd-key-metrics-delta ${changeClass(row.qoq_pct, row.higher_is_good)}`}>
                  {fmtPct(row.qoq_pct)}
                </span>
              </span>
              <span className="erd-key-metrics-comparison">
                <span className="erd-key-metrics-base">
                  {fmtINR(row.same_quarter_last_year, m.unit)}
                </span>
                <span className={`erd-key-metrics-delta ${changeClass(row.yoy_pct, row.higher_is_good)}`}>
                  {fmtPct(row.yoy_pct)}
                </span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

/** AISummaryCard - renders the LLM-generated structured earnings intelligence. */
const AISummaryCard: React.FC<{ summary: EarningsAISummary }> = ({ summary }) => {
  const rating = (summary.rating || '').toLowerCase();
  const ratingClass =
    rating === 'positive' ? 'positive' : rating === 'negative' ? 'negative' : 'neutral';

  const kh = summary.key_highlights || {};
  const khItems = [
    { label: 'Revenue Drivers', body: kh.revenue_drivers },
    { label: 'Margin Quality', body: kh.margin_quality },
    { label: 'Demand & Geography', body: kh.demand_geography },
    { label: 'Management Guidance', body: kh.management_guidance },
    { label: 'Order Book', body: kh.order_book },
  ].filter((item): item is { label: string; body: string } => Boolean(item.body));

  return (
    <div className="erd-ai-summary">
      <p className="erd-ai-summary-title">AI Intelligence</p>

      {summary.performance_narrative && (
        <p className="erd-ai-narrative">{summary.performance_narrative}</p>
      )}

      {summary.pov_analysis && (
        <div className="erd-ai-pov">{summary.pov_analysis}</div>
      )}

      {khItems.length > 0 && (
        <div className="erd-ai-kh">
          <p className="erd-ai-kh-heading">Key Highlights</p>
          <div className="erd-ai-kh-grid">
            {khItems.map((item) => (
              <div key={item.label} className="erd-ai-kh-item">
                <div className="erd-ai-kh-label">{item.label}</div>
                <div className="erd-ai-kh-body">{item.body}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {summary.risks_outlook && (
        <div className="erd-ai-risks">{summary.risks_outlook}</div>
      )}

      {(summary.verdict || summary.rating) && (
        <div className="erd-ai-verdict-row">
          {summary.verdict && (
            <span className="erd-ai-verdict-text">{summary.verdict}</span>
          )}
          {summary.rating && (
            <span className={`erd-ai-rating ${ratingClass}`}>{summary.rating}</span>
          )}
        </div>
      )}
    </div>
  );
};

const DocumentsList: React.FC<{ documents: EarningsDocumentLink[] }> = ({ documents }) => {
  if (!documents.length) {
    return <p className="erd-muted">No official documents linked for this filing.</p>;
  }
  return (
    <div className="erd-docs-list">
      {documents.map((doc, i) => (
        <a
          key={i}
          href={doc.url}
          target="_blank"
          rel="noreferrer"
          className="erd-doc-card"
        >
          <FileText size={16} className="erd-doc-icon" />
          <div className="erd-doc-meta">
            <div className="erd-doc-title">{doc.title}</div>
            <div className="erd-doc-type">{doc.type}</div>
          </div>
          <ExternalLink size={12} className="erd-doc-arrow" />
        </a>
      ))}
    </div>
  );
};

// -- main component ------------------------------------------------------

const EarningsResultDetail: React.FC<EarningsResultDetailProps> = ({
  symbol,
  date,
  companyName,
  onBack,
}) => {
  const [result, setResult] = useState<EarningsResultResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<DetailTab>('highlights');
  const [activeQuarterIndex, setActiveQuarterIndex] = useState(0);
  // Track the currently viewed date so quarter-tab navigation works within the detail view.
  const [currentDate, setCurrentDate] = useState(date);
  const reqSeq = useRef(0);

  // Re-sync currentDate when the parent prop changes (e.g. coming back from a different company).
  useEffect(() => {
    setCurrentDate(date);
  }, [date]);

  const load = useCallback(async () => {
    const seq = ++reqSeq.current;
    setLoading(true);
    setError('');
    try {
      const data = await getEarningsResult(symbol, currentDate);
      if (reqSeq.current !== seq) return;
      setResult(data);
      // set active quarter to the one matching the requested date
      const matchIdx = data.quarter_tabs.findIndex((t) => t.is_current);
      setActiveQuarterIndex(matchIdx >= 0 ? matchIdx : 0);
    } catch (err: any) {
      if (reqSeq.current !== seq) return;
      const raw = err?.message || '';
      const msg =
        raw === 'Failed to fetch' || raw === 'NetworkError when attempting to fetch resource.'
          ? 'Could not reach the earnings service. Check your connection and try again.'
          : raw === 'Not Found' || raw.includes('404')
            ? `No earnings result found for ${symbol} on ${currentDate}.`
            : raw || `Could not load result for ${symbol}.`;
      setError(msg);
    } finally {
      if (reqSeq.current === seq) setLoading(false);
    }
  }, [symbol, currentDate]);

  useEffect(() => {
    load();
  }, [load]);

  // Handle quarter tab selection: if the tab has an earnings_date, navigate to it.
  const handleQuarterSelect = useCallback((index: number) => {
    setActiveQuarterIndex(index);
    if (!result) return;
    const tab = result.quarter_tabs[index];
    if (!tab) return;
    const tabDate = tab.earnings_date;
    // Only navigate if: date is set, not a future quarter, and different from current date
    if (tabDate && !tab.is_future && tabDate !== currentDate) {
      setCurrentDate(tabDate);
      setResult(null);
      setError('');
    }
  }, [result, currentDate]);

  // If the result is only a calendar announcement (not yet parsed), poll every 20s
  // for up to 3 minutes so the complete financial data appears automatically.
  // Skip polling for future scheduled earnings (no PDF available yet).
  useEffect(() => {
    if (!result || result.financials?.source !== 'announcement_fallback') return;
    // Check if the meeting date is in the future
    const isFuture = new Date(result.meeting_date) > new Date();
    if (isFuture) return; // Skip polling for future earnings
    let attempts = 0;
    const maxAttempts = 9;
    const interval = setInterval(() => {
      attempts += 1;
      if (attempts > maxAttempts) {
        clearInterval(interval);
        return;
      }
      load();
    }, 20000);
    return () => clearInterval(interval);
  }, [result, load]);

  // -- render states ------------------------------------------------------

  if (loading) {
    return (
      <div className="erd-root">
        <button type="button" className="erd-back-btn" onClick={onBack}>
          <ArrowLeft size={14} /> Earnings calendar
        </button>
        <div className="erd-loading">
          <Loader2 size={22} className="erd-spinner" />
          <span>Loading {companyName || symbol} results...</span>
        </div>
      </div>
    );
  }

  if (error || !result) {
    return (
      <div className="erd-root">
        <button type="button" className="erd-back-btn" onClick={onBack}>
          <ArrowLeft size={14} /> Earnings calendar
        </button>
        <div className="erd-error">
          <AlertCircle size={18} />
          <span>{error || 'Result data not found.'}</span>
          <button type="button" className="erd-retry-btn" onClick={load}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  const tabs = result.quarter_tabs || [];
  const financialRows = result.financials?.rows || [];
  const documents = result.documents || [];
  const hasAiSummary = Boolean(
    result.ai_summary && Object.keys(result.ai_summary).length > 0
  );
  const isProcessing = result.financials?.source === 'announcement_fallback';

  return (
    <div className="erd-root">
      {/* Back navigation */}
      <button type="button" className="erd-back-btn" onClick={onBack}>
        <ArrowLeft size={14} /> Earnings calendar
      </button>

      {/* Quarter tab strip */}
      {tabs.length > 0 && (
        <EarningsQuarterTabs
          tabs={tabs}
          activeIndex={activeQuarterIndex}
          onSelect={handleQuarterSelect}
        />
      )}

      {/* Company header */}
      <div className="erd-company-header">
        <div className="erd-company-name-row">
          <h2 className="erd-company-name">{result.name}</h2>
          {result.current_price != null && (
            <span className="erd-current-price">{fmtPrice(result.current_price)}</span>
          )}
        </div>
        <div className="erd-company-meta">
          <span className="erd-meta-chip">{result.symbol}</span>
          {result.sector && <span className="erd-meta-chip">{result.sector}</span>}
          {result.fiscal_quarter && <span className="erd-meta-chip">{result.fiscal_quarter}</span>}
          <span className="erd-meta-chip">{result.timing}</span>
          <span className="erd-meta-chip muted">{result.meeting_date}</span>
        </div>
      </div>

      {/* Tab bar - Highlights and Documents only (transcript removed) */}
      <div className="erd-tab-bar" role="tablist">
        {(['highlights', 'documents'] as DetailTab[]).map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={activeTab === t}
            className={`erd-tab-btn ${activeTab === t ? 'is-active' : ''}`}
            onClick={() => setActiveTab(t)}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="erd-tab-content">
        {isProcessing && (
          <div className="erd-processing-banner">
            <Loader2 size={16} className="erd-spinner" />
            <span>Processing the official results PDF. This can take up to 60 seconds on the first open.</span>
          </div>
        )}
        {activeTab === 'highlights' && (
          <div className="erd-highlights-panel">
            {(financialRows.length > 0) && (
              <KeyMetricsSummary rows={financialRows} />
            )}

            {/* AI Intelligence summary - shown when LLM has processed the filing */}
            {hasAiSummary && result.ai_summary && (
              <AISummaryCard summary={result.ai_summary} />
            )}

            {result.financials?.unit_note && (
              <p className="erd-footnote">{result.financials.unit_note}</p>
            )}
          </div>
        )}
        {activeTab === 'documents' && (
          <DocumentsList documents={documents} />
        )}
      </div>
    </div>
  );
};

export default EarningsResultDetail;

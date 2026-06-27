import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  ExternalLink,
  FileText,
  Loader2,
  AlertCircle,
  TrendingUp,
  TrendingDown,
  Minus,
  Zap,
} from 'lucide-react';
import {
  EarningsResultResponse,
  EarningsAISummary,
  EarningsFinancialRow,
  EarningsDocumentLink,
  EarningsHighlight,
  getEarningsResult,
} from '../../api/client';
import SubsidiaryMatrix from './SubsidiaryMatrix';
import FootnoteDiff from './FootnoteDiff';

interface EarningsResultDetailProps {
  symbol: string;
  date: string;
  companyName?: string;
  onBack: () => void;
}

// Transcript tab removed - 'highlights' | 'analysis' | 'documents'
type DetailTab = 'highlights' | 'analysis' | 'documents';

// -- formatting helpers --------------------------------------------------

const fmtINR = (v?: number | null, unit?: string): string => {
  if (v === null || v === undefined || Number.isNaN(v)) return '-';
  if (unit === '%') return `${v.toFixed(1)}%`;
  if (unit === 'Rs') return `Rs ${v.toFixed(2)}`;
  if (Math.abs(v) >= 1000) {
    return `Rs ${(v / 1000).toFixed(2)}K Cr`;
  }
  return `Rs ${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })} Cr`;
};

const fmtPct = (v?: number | null): string => {
  if (v === null || v === undefined || Number.isNaN(v)) return '-';
  const prefix = v > 0 ? '+' : '';
  return `${prefix}${v.toFixed(2)}%`;
};

const fmtPrice = (v?: number | null): string => {
  if (v === null || v === undefined) return '-';
  return `Rs ${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
};

const changeClass = (v?: number | null, higherIsGood = true): string => {
  if (v == null || Number.isNaN(v) || v === 0) return 'neutral';
  return (higherIsGood ? v > 0 : v < 0) ? 'positive' : 'negative';
};

// -- sub-components ------------------------------------------------------

/** QuickTake - One-line verdict with visual rating indicator */
const QuickTake: React.FC<{
  summary?: EarningsAISummary | null;
  rows: EarningsFinancialRow[];
}> = ({ summary, rows }) => {
  const rating = (summary?.rating || '').toLowerCase();
  const verdict = summary?.verdict || summary?.performance_narrative;

  // Generate quick take from metrics if no AI summary
  const rowsMap = Object.fromEntries(rows.map((r) => [r.key, r]));
  const revenueQoQ = rowsMap['revenue']?.qoq_pct;
  const patQoQ = rowsMap['pat']?.qoq_pct;
  const epsQoQ = rowsMap['eps']?.qoq_pct;

  let quickVerdict = verdict;
  let quickRating = rating;

  if (!quickVerdict && rows.length > 0) {
    const changes: string[] = [];
    if (revenueQoQ != null) {
      changes.push(`Revenue ${revenueQoQ >= 0 ? 'up' : 'down'} ${Math.abs(revenueQoQ).toFixed(1)}% QoQ`);
    }
    if (patQoQ != null) {
      changes.push(`PAT ${patQoQ >= 0 ? 'up' : 'down'} ${Math.abs(patQoQ).toFixed(1)}%`);
    }
    if (epsQoQ != null) {
      changes.push(`EPS ${epsQoQ >= 0 ? 'up' : 'down'} ${Math.abs(epsQoQ).toFixed(1)}%`);
    }
    quickVerdict = changes.length > 0 ? changes.join('. ') + '.' : undefined;

    // Infer rating from metrics
    const avgChange = [revenueQoQ, patQoQ, epsQoQ].filter(v => v != null).reduce((a, b) => a! + b!, 0)! /
                      [revenueQoQ, patQoQ, epsQoQ].filter(v => v != null).length;
    if (avgChange > 5) quickRating = 'positive';
    else if (avgChange < -5) quickRating = 'negative';
    else quickRating = 'neutral';
  }

  if (!quickVerdict) return null;

  const ratingIcon = quickRating === 'positive' ? <TrendingUp size={16} /> :
                     quickRating === 'negative' ? <TrendingDown size={16} /> : <Minus size={16} />;
  const ratingClass = quickRating === 'positive' ? 'positive' :
                      quickRating === 'negative' ? 'negative' : 'neutral';

  return (
    <div className={`erd-quick-take ${ratingClass}`}>
      <div className="erd-quick-take-icon">{ratingIcon}</div>
      <div className="erd-quick-take-content">
        <span className="erd-quick-take-label">Quick Take</span>
        <p className="erd-quick-take-text">{quickVerdict}</p>
      </div>
      {quickRating && (
        <span className={`erd-quick-take-rating ${ratingClass}`}>
          {quickRating.charAt(0).toUpperCase() + quickRating.slice(1)}
        </span>
      )}
    </div>
  );
};

const KeyMetricsSummary: React.FC<{ rows: EarningsFinancialRow[] }> = ({ rows }) => {
  const rowsMap = Object.fromEntries(rows.map((r) => [r.key, r]));

  // Define all possible metrics we want to show
  const allMetrics = [
    { key: 'revenue', label: 'Revenue', unit: 'Rs Cr', higherIsGood: true, maxReasonable: 10000000 },
    { key: 'pat', label: 'Profit After Tax', unit: 'Rs Cr', higherIsGood: true, maxReasonable: 1000000 },
    { key: 'ebitda', label: 'EBITDA', unit: 'Rs Cr', higherIsGood: true, maxReasonable: 1000000 },
    { key: 'eps', label: 'EPS', unit: 'Rs', higherIsGood: true, maxReasonable: 10000 },
    { key: 'ebitda_margin', label: 'EBITDA Margin', unit: '%', higherIsGood: true, maxReasonable: 100 },
    { key: 'pat_margin', label: 'PAT Margin', unit: '%', higherIsGood: true, maxReasonable: 100 },
  ];

  // Filter to only show metrics that have reasonable current values
  const visible = allMetrics.filter((m) => {
    const row = rowsMap[m.key];
    if (!row?.current || Number.isNaN(row.current)) return false;
    // Filter out obviously wrong data (e.g., margin > 100%, revenue < 1)
    if (Math.abs(row.current) > m.maxReasonable) return false;
    if (m.key === 'revenue' && row.current < 1) return false;
    return true;
  });

  if (!visible.length) return null;

  return (
    <div className="erd-key-metrics">
      <h4 className="erd-section-title">Financial Performance</h4>
      <div className="erd-key-metrics-table">
        <div className="erd-key-metrics-head">
          <span>Metric</span>
          <span>Current</span>
          <span>QoQ Change</span>
          <span>YoY Change</span>
        </div>
        {visible.map((m) => {
          const row = rowsMap[m.key];
          const isPercent = m.unit === '%';
          // Also filter QoQ/YoY if they're unreasonable (> 10000%)
          const qoq = row.qoq_pct != null && Math.abs(row.qoq_pct) < 10000 ? row.qoq_pct : null;
          const yoy = row.yoy_pct != null && Math.abs(row.yoy_pct) < 10000 ? row.yoy_pct : null;
          return (
            <div key={m.key} className="erd-key-metrics-row">
              <span className="erd-key-metrics-label">
                {m.label}
              </span>
              <span className="erd-key-metrics-value">
                {isPercent ? `${row.current?.toFixed(1)}%` : fmtINR(row.current, m.unit)}
              </span>
              <span className="erd-key-metrics-comparison">
                {qoq != null ? (
                  <span className={`erd-key-metrics-delta ${changeClass(qoq, m.higherIsGood)}`}>
                    {fmtPct(qoq)}
                  </span>
                ) : (
                  <span className="erd-key-metrics-delta neutral">-</span>
                )}
              </span>
              <span className="erd-key-metrics-comparison">
                {yoy != null ? (
                  <span className={`erd-key-metrics-delta ${changeClass(yoy, m.higherIsGood)}`}>
                    {fmtPct(yoy)}
                  </span>
                ) : (
                  <span className="erd-key-metrics-delta neutral">-</span>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};
const OfficialHighlights: React.FC<{ highlights: EarningsHighlight[] }> = ({ highlights }) => {
  const items = (highlights || []).filter((item) => item?.text?.trim());
  if (!items.length) return null;

  return (
    <section className="erd-official-highlights" aria-label="Official filing highlights">
      <div className="erd-section-heading-row">
        <h4 className="erd-section-title">Official Highlights</h4>
        <span className="erd-section-kicker">Parsed from filing</span>
      </div>
      <div className="erd-highlights-list">
        {items.map((item, index) => (
          <div key={`${item.text}-${index}`} className="erd-highlight-item">
            <span className="erd-highlight-dot" />
            <span className="erd-highlight-text">{item.text}</span>
            {item.url && (
              <a
                href={item.url}
                target="_blank"
                rel="noreferrer"
                className="erd-highlight-source"
                title={item.source_label || 'Official filing'}
              >
                <ExternalLink size={12} />
              </a>
            )}
          </div>
        ))}
      </div>
    </section>
  );
};

const AnalysisBrief: React.FC<{
  summary?: EarningsAISummary | null;
  rows: EarningsFinancialRow[];
  documents: EarningsDocumentLink[];
}> = ({ summary, rows, documents }) => {
  const rowsMap = Object.fromEntries(rows.map((row) => [row.key, row]));
  const metricOrder = [
    { key: 'revenue', label: 'Revenue' },
    { key: 'pat', label: 'PAT' },
    { key: 'ebitda', label: 'EBITDA' },
    { key: 'eps', label: 'EPS' },
    { key: 'ebitda_margin', label: 'EBITDA margin' },
    { key: 'pat_margin', label: 'PAT margin' },
  ];
  const metricRows = metricOrder
    .map((item) => ({ ...item, row: rowsMap[item.key] }))
    .filter((item) => item.row?.current != null);

  if (!summary && metricRows.length === 0) return null;

  const sourceCopy = documents.length > 0 ? 'Official filing linked' : 'Parsed official filing';

  return (
    <section className="erd-analysis-brief">
      <div className="erd-section-heading-row">
        <h4 className="erd-section-title">Analyst Read</h4>
        <span className="erd-section-kicker">{sourceCopy}</span>
      </div>

      {summary?.pov_analysis && <p className="erd-analysis-lead">{summary.pov_analysis}</p>}
      {!summary?.pov_analysis && summary?.performance_narrative && (
        <p className="erd-analysis-lead">{summary.performance_narrative}</p>
      )}

      {metricRows.length > 0 && (
        <div className="erd-analysis-metric-grid">
          {metricRows.map(({ key, label, row }) => {
            const isPercent = row.unit === '%';
            return (
              <div key={key} className="erd-analysis-metric">
                <span className="erd-analysis-metric-label">{label}</span>
                <strong>{isPercent ? `${row.current?.toFixed(1)}%` : fmtINR(row.current, row.unit)}</strong>
                <div className="erd-analysis-deltas">
                  <span className={changeClass(row.qoq_pct, row.higher_is_good !== false)}>
                    QoQ {fmtPct(row.qoq_pct)}
                  </span>
                  <span className={changeClass(row.yoy_pct, row.higher_is_good !== false)}>
                    YoY {fmtPct(row.yoy_pct)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {(summary?.key_highlights?.margin_quality || summary?.risks_outlook) && (
        <div className="erd-analysis-copy-grid">
          {summary?.key_highlights?.margin_quality && (
            <div>
              <span>Margin Quality</span>
              <p>{summary.key_highlights.margin_quality}</p>
            </div>
          )}
          {summary?.risks_outlook && (
            <div>
              <span>Risks & Outlook</span>
              <p>{summary.risks_outlook}</p>
            </div>
          )}
        </div>
      )}
    </section>
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

      {(summary.operational_kpis || summary.confidence_factors) && (
        <div className="erd-ai-note-grid">
          {summary.operational_kpis && (
            <div className="erd-ai-note">
              <span>Operational KPIs</span>
              <p>{summary.operational_kpis}</p>
            </div>
          )}
          {summary.confidence_factors && (
            <div className="erd-ai-note">
              <span>Confidence</span>
              <p>{summary.confidence_factors}</p>
            </div>
          )}
        </div>
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
  // Track the currently viewed date so reloads stay aligned with the selected result.
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

  const financialRows = result.financials?.rows || [];
  const documents = result.documents || [];
  const hasAiSummary = Boolean(
    result.ai_summary && Object.keys(result.ai_summary).length > 0
  );
  const hasOfficialHighlights = Boolean((result.highlights || []).some((item) => item?.text));
  const hasAnalysisBrief = hasAiSummary || financialRows.some((row) => row.current != null);
  const hasSubsidiaryAnalysis = Boolean(
    result.subsidiary_analysis && result.subsidiary_analysis.alert_level !== 'none'
  );
  const hasFootnotesDiff = Boolean(
    result.footnotes_diff && !result.footnotes_diff.error
  );
  const isProcessing = result.financials?.source === 'announcement_fallback';

  return (
    <div className="erd-root">
      {/* Back navigation */}
      <button type="button" className="erd-back-btn" onClick={onBack}>
        <ArrowLeft size={14} /> Earnings calendar
      </button>

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

      {/* Tab bar - Highlights, Analysis, and Documents */}
      <div className="erd-tab-bar" role="tablist">
        {(['highlights', 'analysis', 'documents'] as DetailTab[]).map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={activeTab === t}
            className={`erd-tab-btn ${activeTab === t ? 'is-active' : ''}`}
            onClick={() => setActiveTab(t)}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
            {t === 'analysis' && (hasSubsidiaryAnalysis || hasFootnotesDiff) && (
              <span className="erd-tab-badge">!</span>
            )}
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
            {/* Quick Take - prominent verdict at top */}
            <QuickTake summary={result.ai_summary} rows={financialRows} />

            {hasOfficialHighlights && (
              <OfficialHighlights highlights={result.highlights || []} />
            )}

            {/* Key Metrics table */}
            {(financialRows.length > 0) && (
              <KeyMetricsSummary rows={financialRows} />
            )}

            {/* AI Intelligence summary - detailed analysis */}
            {hasAiSummary && result.ai_summary && (
              <AISummaryCard summary={result.ai_summary} />
            )}

            {/* Show placeholder when no data */}
            {!hasAiSummary && !hasOfficialHighlights && financialRows.length === 0 && (
              <div className="erd-no-highlights">
                <Zap size={24} />
                <p>Earnings analysis will appear here once the filing is processed.</p>
              </div>
            )}

            {result.financials?.unit_note && (
              <p className="erd-footnote">{result.financials.unit_note}</p>
            )}
          </div>
        )}
        {activeTab === 'analysis' && (
          <div className="erd-analysis-panel">
            {hasAnalysisBrief && (
              <AnalysisBrief
                summary={result.ai_summary}
                rows={financialRows}
                documents={documents}
              />
            )}

            {/* Subsidiary Cash-Drain Matrix */}
            {result.subsidiary_analysis && result.subsidiary_analysis.alert_level && result.subsidiary_analysis.alert_level !== 'none' && (
              <SubsidiaryMatrix analysis={result.subsidiary_analysis} />
            )}

            {/* Footnote QoQ Diff Engine */}
            {result.footnotes_diff && !result.footnotes_diff.error && (
              <FootnoteDiff diff={result.footnotes_diff} />
            )}

            {/* Show empty state when no analysis is available */}
            {!hasAnalysisBrief && (!result.subsidiary_analysis || !result.subsidiary_analysis.alert_level || result.subsidiary_analysis.alert_level === 'none') &&
             (!result.footnotes_diff || result.footnotes_diff.error) && (
              <div className="erd-analysis-empty">
                <AlertCircle size={32} />
                <h4>Advanced Analysis Unavailable</h4>
                <p>
                  Advanced analysis features require specific data from the company's filing:
                </p>
                <ul>
                  <li><strong>Subsidiary Analysis</strong>: Requires both standalone and consolidated financial statements. This company may only report consolidated results.</li>
                  <li><strong>Footnote Comparison</strong>: Requires footnotes from both current and previous quarter filings. {result.footnotes_diff?.error || 'Previous quarter data may not be available.'}</li>
                </ul>
                <p className="erd-analysis-tip">
                  Most companies report only consolidated financials. Subsidiary analysis is primarily useful for conglomerates with significant subsidiary operations.
                </p>
              </div>
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

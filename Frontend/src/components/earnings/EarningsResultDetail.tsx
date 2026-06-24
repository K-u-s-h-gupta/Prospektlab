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
} from 'lucide-react';
import {
  EarningsResultResponse,
  EarningsAISummary,
  EarningsFinancialRow,
  EarningsExtractedTable,
  EarningsTranscriptBlock,
  EarningsDocumentLink,
  EarningsHighlight,
  getEarningsResult,
} from '../../api/client';
import EarningsQuarterTabs from './EarningsQuarterTabs';

interface EarningsResultDetailProps {
  symbol: string;
  date: string;
  companyName?: string;
  onBack: () => void;
}

// Transcript tab removed â€” 'highlights' | 'documents' only
type DetailTab = 'highlights' | 'documents';

// â”€â”€ formatting helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

const fmtINR = (v?: number | null, unit?: string): string => {
  if (v === null || v === undefined || Number.isNaN(v)) return 'â€”';
  if (unit === '%') return `${v.toFixed(1)}%`;
  if (unit === 'Rs') return `â‚¹${v.toFixed(2)}`;
  // Rs Cr
  if (Math.abs(v) >= 1000) {
    return `â‚¹${(v / 1000).toFixed(2)}K Cr`;
  }
  return `â‚¹${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })} Cr`;
};

const fmtPct = (v?: number | null): string => {
  if (v === null || v === undefined || Number.isNaN(v)) return 'â€”';
  const prefix = v > 0 ? '+' : '';
  return `${prefix}${v.toFixed(2)}%`;
};

const fmtPrice = (v?: number | null): string => {
  if (v === null || v === undefined) return 'â€”';
  return `â‚¹${v.toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
};

const beatMissClass = (pct?: number | null): string => {
  if (pct == null || Number.isNaN(pct)) return '';
  return pct > 0 ? 'beat' : pct < 0 ? 'miss' : '';
};

const beatMissLabel = (pct?: number | null): string => {
  if (pct == null || Number.isNaN(pct)) return '';
  return pct > 0 ? 'Beat' : pct < 0 ? 'Miss' : 'In-line';
};

const changeClass = (v?: number | null, higherIsGood = true): string => {
  if (v == null || Number.isNaN(v) || v === 0) return 'neutral';
  return (higherIsGood ? v > 0 : v < 0) ? 'positive' : 'negative';
};

// â”€â”€ sub-components â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

/**
 * MetricsGrid â€” shows all six core metrics (Revenue, PAT, EBITDA, EPS, EBITDA Margin, PAT Margin).
 * Pulls current values from financials.rows; estimated / beat-miss from top-level revenue & eps fields.
 * 1D move is shown only on the EPS row.
 */
const MetricsGrid: React.FC<{ result: EarningsResultResponse }> = ({ result }) => {
  // Build a lookup from financials.rows for current (actual) values
  const rowsMap = Object.fromEntries(
    (result.financials?.rows || []).map((r: EarningsFinancialRow) => [r.key, r])
  );

  const metrics = [
    {
      key: 'revenue',
      label: 'Revenue',
      actual: rowsMap['revenue']?.current ?? result.revenue?.actual,
      estimated: result.revenue?.estimated,
      beatMiss: result.revenue?.beat_miss_pct,
      unit: 'Rs Cr',
    },
    {
      key: 'pat',
      label: 'PAT',
      actual: rowsMap['pat']?.current,
      estimated: null as number | null | undefined,
      beatMiss: null as number | null | undefined,
      unit: 'Rs Cr',
    },
    {
      key: 'ebitda',
      label: 'EBITDA',
      actual: rowsMap['ebitda']?.current,
      estimated: null as number | null | undefined,
      beatMiss: null as number | null | undefined,
      unit: 'Rs Cr',
    },
    {
      key: 'eps',
      label: 'EPS',
      actual: rowsMap['eps']?.current ?? result.eps?.actual,
      estimated: result.eps?.estimated,
      beatMiss: result.eps?.beat_miss_pct,
      unit: 'Rs',
    },
    {
      key: 'ebitda_margin',
      label: 'EBITDA Margin',
      actual: rowsMap['ebitda_margin']?.current,
      estimated: null as number | null | undefined,
      beatMiss: null as number | null | undefined,
      unit: '%',
    },
    {
      key: 'pat_margin',
      label: 'PAT Margin',
      actual: rowsMap['pat_margin']?.current,
      estimated: null as number | null | undefined,
      beatMiss: null as number | null | undefined,
      unit: '%',
    },
  ];

  // Only render rows that have at least one value
  const visibleMetrics = metrics.filter((m) => m.actual != null || m.estimated != null);
  if (!visibleMetrics.length) return null;

  return (
    <div className="erd-metrics-grid">
      <div className="erd-metrics-head">
        <span />
        <span>Estimated</span>
        <span>Actual</span>
        <span>Beat / Miss</span>
        <span>1D Move</span>
      </div>
      {visibleMetrics.map((row) => (
        <div key={row.key} className="erd-metrics-row">
          <span className="erd-metrics-label">{row.label}</span>
          <span className="erd-metrics-value muted">
            {row.estimated != null ? fmtINR(row.estimated, row.unit) : 'â€”'}
          </span>
          <span className="erd-metrics-value">
            {row.actual != null ? fmtINR(row.actual, row.unit) : 'â€”'}
          </span>
          <span className={`erd-metrics-badge ${beatMissClass(row.beatMiss)}`}>
            {row.beatMiss != null ? (
              <>
                {beatMissLabel(row.beatMiss)}
                {' '}
                <span className="erd-badge-pct">{fmtPct(row.beatMiss)}</span>
              </>
            ) : 'â€”'}
          </span>
          <span className="erd-metrics-value">
            {row.key === 'eps' && result.move_1d?.pct != null ? (
              <span className={`erd-move-chip ${changeClass(result.move_1d.pct)}`}>
                {result.move_1d.pct > 0 ? <TrendingUp size={11} /> : result.move_1d.pct < 0 ? <TrendingDown size={11} /> : <Minus size={11} />}
                {fmtPct(result.move_1d.pct)}
              </span>
            ) : row.key === 'revenue' && result.current_price != null ? (
              <span className="erd-price-chip">{fmtPrice(result.current_price)}</span>
            ) : 'â€”'}
          </span>
        </div>
      ))}
    </div>
  );
};

const FinancialTable: React.FC<{ rows: EarningsFinancialRow[] }> = ({ rows }) => {
  if (!rows.length) {
    return <p className="erd-muted">Financial data will appear here once available.</p>;
  }
  return (
    <div className="erd-table-wrap">
      <table className="erd-fin-table">
        <thead>
          <tr>
            <th>Metric</th>
            <th>Current</th>
            <th>QoQ</th>
            <th>YoY</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td>
                <div className="erd-fin-label">{row.label}</div>
                <div className="erd-fin-unit">{row.unit}</div>
              </td>
              <td>{fmtINR(row.current, row.unit)}</td>
              <td>
                <span className={`erd-delta ${changeClass(row.qoq_pct, row.higher_is_good)}`}>
                  {fmtPct(row.qoq_pct)}
                </span>
              </td>
              <td>
                <span className={`erd-delta ${changeClass(row.yoy_pct, row.higher_is_good)}`}>
                  {fmtPct(row.yoy_pct)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const ConsolidatedTables: React.FC<{ tables: EarningsExtractedTable[] }> = ({ tables }) => {
  const visibleTables = tables.filter((table) => table.rows?.length).slice(0, 2);
  if (!visibleTables.length) return null;
  return (
    <div className="erd-extracted-tables">
      {visibleTables.map((table, tableIndex) => {
        const rows = table.rows.slice(0, 14);
        const maxCols = Math.min(6, Math.max(...rows.map((row) => row.length)));
        return (
          <div key={`${table.page_number || 0}-${tableIndex}`} className="erd-extracted-table-block">
            <div className="erd-table-caption">
              Consolidated table{table.page_number ? `, page ${table.page_number}` : ''}
            </div>
            <div className="erd-table-wrap">
              <table className="erd-fin-table erd-raw-table">
                <tbody>
                  {rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {Array.from({ length: maxCols }).map((_, colIndex) => (
                        <td key={colIndex}>{row[colIndex] || ''}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
};

const HighlightsList: React.FC<{ items: EarningsHighlight[] }> = ({ items }) => {
  if (!items.length) {
    return <p className="erd-muted">AI highlights will appear once the PDF is processed.</p>;
  }
  return (
    <ul className="erd-highlights-list">
      {items.map((item, i) => (
        <li key={i}>
          <span className="erd-highlight-bullet" />
          <span className="erd-highlight-text">{item.text}</span>
          {item.url ? (
            <a href={item.url} target="_blank" rel="noreferrer" className="erd-highlight-source">
              <ExternalLink size={10} />
            </a>
          ) : null}
        </li>
      ))}
    </ul>
  );
};

/** AISummaryCard â€” renders the LLM-generated structured earnings intelligence. */
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

// TranscriptSection exported so it remains available for future use without triggering
// noUnusedLocals — the transcript tab was removed from the UI but the component is kept.
export const TranscriptSection: React.FC<{
  preparedRemarks: EarningsTranscriptBlock[];
  qa: EarningsTranscriptBlock[];
}> = ({ preparedRemarks, qa }) => {
  const hasAny = preparedRemarks.length > 0 || qa.length > 0;
  if (!hasAny) {
    return <p className="erd-muted">Transcript not yet available for this filing.</p>;
  }
  return (
    <div className="erd-transcript">
      {preparedRemarks.length > 0 && (
        <div className="erd-transcript-section">
          <h4 className="erd-transcript-heading">Prepared remarks</h4>
          {preparedRemarks.map((block, i) => (
            <div key={i} className="erd-transcript-block">
              {block.speaker && <span className="erd-transcript-speaker">{block.speaker}</span>}
              <p>{block.text}</p>
            </div>
          ))}
        </div>
      )}
      {qa.length > 0 && (
        <div className="erd-transcript-section">
          <h4 className="erd-transcript-heading">Q &amp; A</h4>
          {qa.map((block, i) => (
            <div key={i} className={`erd-transcript-block ${(block.speaker || '').toLowerCase().includes('analyst') || (block.speaker || '').toLowerCase().includes('question') ? 'is-question' : ''}`}>
              {block.speaker && <span className="erd-transcript-speaker">{block.speaker}</span>}
              <p>{block.text}</p>
            </div>
          ))}
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

// â”€â”€ main component â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
  const reqSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++reqSeq.current;
    setLoading(true);
    setError('');
    try {
      const data = await getEarningsResult(symbol, date);
      if (reqSeq.current !== seq) return;
      setResult(data);
      // set active quarter to the one matching the requested date
      const matchIdx = data.quarter_tabs.findIndex((t) => t.is_current);
      setActiveQuarterIndex(matchIdx >= 0 ? matchIdx : 0);
    } catch (err: any) {
      if (reqSeq.current !== seq) return;
      setError(err?.message || `Could not load result for ${symbol}.`);
    } finally {
      if (reqSeq.current === seq) setLoading(false);
    }
  }, [symbol, date]);

  useEffect(() => {
    load();
  }, [load]);

  // â”€â”€ render states â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

  if (loading) {
    return (
      <div className="erd-root">
        <button type="button" className="erd-back-btn" onClick={onBack}>
          <ArrowLeft size={14} /> Earnings calendar
        </button>
        <div className="erd-loading">
          <Loader2 size={22} className="erd-spinner" />
          <span>Loading {companyName || symbol} resultsâ€¦</span>
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
  const highlights = result.highlights || [];
  const financialRows = result.financials?.rows || [];
  const consolidatedTables = result.financials?.consolidated_tables || [];
  const documents = result.documents || [];
  const hasAiSummary = Boolean(
    result.ai_summary && Object.keys(result.ai_summary).length > 0
  );

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
          onSelect={setActiveQuarterIndex}
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

      {/* Metrics grid â€” all six core metrics */}
      <MetricsGrid result={result} />

      {/* Tab bar â€” Highlights and Documents only (transcript removed) */}
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
        {activeTab === 'highlights' && (
          <div className="erd-highlights-panel">
            <HighlightsList items={highlights} />

            {/* AI Intelligence summary â€” shown when LLM has processed the filing */}
            {hasAiSummary && result.ai_summary && (
              <AISummaryCard summary={result.ai_summary} />
            )}

            {(financialRows.length > 0 || consolidatedTables.length > 0) && (
              <div className="erd-fin-section">
                <h4 className="erd-section-title">Financial comparison</h4>
                <FinancialTable rows={financialRows} />
                <ConsolidatedTables tables={consolidatedTables} />
                {result.financials?.unit_note && (
                  <p className="erd-footnote">{result.financials.unit_note}</p>
                )}
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

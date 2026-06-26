import React from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  AlertTriangle,
  BarChart3,
  Briefcase,
  CheckCircle2,
  Circle,
  Clock,
  DollarSign,
  FileText,
  Landmark,
  PieChart,
  Shield,
  TrendingUp,
  Users,
} from 'lucide-react';
import { AppShell } from '../components/layout/AppShell';
import { IpoScoreBars } from '../components/ipo/IpoCard';
import { IpoAnalysisResponse } from '../api/client';

type DetailTab = 'business' | 'financials' | 'growth' | 'valuation' | 'promoters' | 'proceeds' | 'risks' | 'institutional';

const TAB_CONFIG: { key: DetailTab; label: string; icon: React.ReactNode }[] = [
  { key: 'business', label: 'Business', icon: <Briefcase size={14} /> },
  { key: 'financials', label: 'Financials', icon: <BarChart3 size={14} /> },
  { key: 'growth', label: 'Growth', icon: <TrendingUp size={14} /> },
  { key: 'valuation', label: 'Valuation', icon: <DollarSign size={14} /> },
  { key: 'promoters', label: 'Promoters', icon: <Users size={14} /> },
  { key: 'proceeds', label: 'Proceeds', icon: <PieChart size={14} /> },
  { key: 'risks', label: 'Risks', icon: <Shield size={14} /> },
  { key: 'institutional', label: 'Institutional', icon: <Landmark size={14} /> },
];

const fmtCr = (v?: number | null) => (v != null ? `₹${v} cr` : '—');

// Cached date formatter to avoid repeated Date parsing
const dateCache = new Map<string, string>();
const fmtDate = (value?: string | null) => {
  if (!value) return null;
  if (dateCache.has(value)) return dateCache.get(value);
  try {
    const formatted = new Date(value).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
    dateCache.set(value, formatted);
    return formatted;
  } catch {
    return value;
  }
};

const fmtDocType = (value?: string | null) => {
  const upper = String(value || 'drhp').toUpperCase();
  if (upper === 'DRHP') return 'DRHP';
  if (upper === 'RHP') return 'RHP';
  if (upper === 'PROSPECTUS') return 'Prospectus';
  return upper;
};

type IpoLifecycleStage = {
  key: string;
  label: string;
  description?: string;
  state: string;
  date?: string | null;
  end_date?: string | null;
  pdf_url?: string | null;
  countdown?: { days: number; target_date: string } | null;
};

// ── Module Pending Empty State ────────────────────────────────────────────────
export const ModulePending: React.FC<{ icon?: string; title: string; sub: string }> = ({ icon = '📊', title, sub }) => (
  <div className="ipo-module-pending">
    <div className="ipo-module-pending-icon">{icon}</div>
    <div className="ipo-module-pending-title">{title}</div>
    <div className="ipo-module-pending-sub">{sub}</div>
  </div>
);

// ── Data validation helpers ───────────────────────────────────────────────────
const isLikelyCagr = (v: number | null | undefined): boolean =>
  v != null && v > -95 && v < 500;  // reject absurd CAGRs like 1818%

const isLikelyIssueCr = (v: number | null | undefined): boolean =>
  v != null && v >= 1 && v <= 50000;  // reasonable IPO size in crores

const fmtCrValidated = (v?: number | null) =>
  isLikelyIssueCr(v) ? fmtCr(v) : '—';

// ── Signal Assessment Engine ──────────────────────────────────────────────────
type Signal = 'positive' | 'neutral' | 'negative' | 'pending';

const getSignalColor = (signal: Signal) => {
  switch (signal) {
    case 'positive': return '#4ade80';
    case 'neutral': return '#fbbf24';
    case 'negative': return '#f87171';
    default: return 'var(--text-muted)';
  }
};

const getSignalLabel = (signal: Signal) => {
  switch (signal) {
    case 'positive': return 'Positive';
    case 'neutral': return 'Neutral';
    case 'negative': return 'Negative';
    default: return 'Pending';
  }
};

const getSignalIcon = (signal: Signal) => {
  switch (signal) {
    case 'positive': return '+';
    case 'neutral': return '0';
    case 'negative': return '–';
    default: return '?';
  }
};

// Signal computation functions based on drhp.md interpretation rules
const computeBusinessSignal = (analysis: any, scores: any): Signal => {
  const hasStrengths = (analysis.strengths || []).length >= 3;
  const hasOverview = (analysis.business_overview_paragraphs || []).length > 0 || analysis.business_synthesis;
  const businessScore = scores.business_quality;
  if (businessScore >= 70 && hasStrengths) return 'positive';
  if (businessScore >= 45 || hasOverview) return 'neutral';
  if (businessScore != null && businessScore < 45) return 'negative';
  return 'pending';
};

const computeFinancialSignal = (financials: any): Signal => {
  const trends = financials.trends || {};
  const revCagr = trends.revenue_cagr_pct;
  const flags = financials.flags || [];
  if (revCagr == null) return 'pending';
  if (revCagr > 15 && !flags.includes('margin_compression') && !flags.includes('pat_decline')) return 'positive';
  if (revCagr >= 8 && revCagr <= 15) return 'neutral';
  return 'negative';
};

const computeGrowthSignal = (financials: any): Signal => {
  const metrics = financials.metrics || {};
  const revenue = (metrics.revenue || metrics.revenue_cr || []).filter((v: any) => v != null);
  const pat = (metrics.pat || metrics.pat_cr || []).filter((v: any) => v != null);
  if (revenue.length < 2 || pat.length < 2) return 'pending';
  
  // Check if profitability grows with revenue
  let divergenceYears = 0;
  for (let i = 1; i < Math.min(revenue.length, pat.length); i++) {
    const revGrowth = revenue[i - 1] > 0 ? (revenue[i] - revenue[i - 1]) / revenue[i - 1] : 0;
    const patGrowth = pat[i - 1] > 0 ? (pat[i] - pat[i - 1]) / pat[i - 1] : 0;
    if (revGrowth > 0.05 && patGrowth < revGrowth * 0.5) divergenceYears++;
  }
  if (divergenceYears === 0) return 'positive';
  if (divergenceYears === 1) return 'neutral';
  return 'negative';
};

const computeValuationSignal = (peerVal: any): Signal => {
  const premium = peerVal.premium_pct;
  if (premium == null) return 'pending';
  if (premium <= 0) return 'positive';
  if (premium <= 30) return 'neutral';  // drhp.md: up to 20% acceptable, >30% negative
  return 'negative';
};

const computePromoterSignal = (objects: any, promoters: any): Signal => {
  const ofsPct = objects.ofs_pct;
  const promoList = promoters.promoters || [];
  const totalStake = promoList.reduce((sum: number, p: any) => sum + (p.shareholding_pct || 0), 0);
  if (ofsPct == null && promoList.length === 0) return 'pending';
  if (ofsPct != null && ofsPct > 50) return 'negative';
  if (ofsPct != null && ofsPct < 20 && (totalStake > 50 || promoList.length === 0)) return 'positive';
  return 'neutral';
};

const computeProceedsSignal = (objects: any): Signal => {
  const util = objects.utilization || [];
  const flags = objects.flags || [];
  if (util.length === 0 && flags.length === 0) return 'pending';
  if (flags.includes('high_gcp_allocation')) return 'negative';
  const hasCapex = util.some((u: any) => u.category === 'capex' || u.category === 'expansion');
  const hasDebt = util.some((u: any) => u.category === 'debt_repayment');
  if (hasCapex && !flags.includes('high_debt_repayment_allocation')) return 'positive';
  if (hasDebt && !flags.includes('high_debt_repayment_allocation')) return 'neutral';
  return 'neutral';
};

const computeRiskSignal = (risks: any, scores: any): Signal => {
  const riskScore = scores.risk_profile;
  const totalCount = risks.total_count;
  if (riskScore == null && totalCount == null) return 'pending';
  if (riskScore >= 70 || (totalCount != null && totalCount <= 10)) return 'positive';
  if (riskScore >= 45 || (totalCount != null && totalCount <= 25)) return 'neutral';
  return 'negative';
};

const computeInstitutionalSignal = (filing: any): Signal => {
  const subTimes = filing.subscription_times;
  const subStatus = filing.subscription_status;
  if (subTimes == null && !subStatus) return 'pending';
  if (subTimes != null && subTimes >= 3) return 'positive';
  if (subTimes != null && subTimes >= 1) return 'neutral';
  if (subTimes != null && subTimes < 1) return 'negative';
  return 'pending';
};

// ── Signal Badge Component ────────────────────────────────────────────────────
const SignalBadge: React.FC<{ signal: Signal; compact?: boolean }> = ({ signal, compact }) => (
  <span
    className={`ipo-signal-badge ipo-signal-badge--${signal}`}
    style={{ '--signal-color': getSignalColor(signal) } as React.CSSProperties}
  >
    <span className="ipo-signal-icon">{getSignalIcon(signal)}</span>
    {!compact && <span className="ipo-signal-text">{getSignalLabel(signal)}</span>}
  </span>
);

// ── Interpretation Card Component ─────────────────────────────────────────────
const InterpretationCard: React.FC<{ signal: Signal; rules: { positive: string; neutral?: string; negative: string } }> = ({ signal, rules }) => (
  <div className={`ipo-interpretation ipo-interpretation--${signal}`}>
    <div className="ipo-interpretation-header">
      <SignalBadge signal={signal} />
      <span className="ipo-interpretation-label">Signal assessment</span>
    </div>
    <div className="ipo-interpretation-body">
      {signal === 'positive' && <p>{rules.positive}</p>}
      {signal === 'neutral' && <p>{rules.neutral || 'Mixed signals — requires deeper analysis.'}</p>}
      {signal === 'negative' && <p>{rules.negative}</p>}
      {signal === 'pending' && <p>Insufficient data to assess signal. Analysis pending.</p>}
    </div>
  </div>
);

const buildFallbackLifecycle = (filing: any): IpoLifecycleStage[] => {
  const docType = String(filing.doc_type || 'drhp').toLowerCase();
  const status = String(filing.status || 'upcoming').toLowerCase();
  const hasRhp = docType === 'rhp' || docType === 'prospectus' || Boolean(filing.rhp_filing_date);
  const isOpen = status === 'live' || Boolean(filing.subscription_open);
  const isListed = status === 'listed' || Boolean(filing.listing_date);
  return [
    { key: 'drhp', label: 'DRHP Filed', description: 'Draft Red Herring Prospectus filed with SEBI', state: docType === 'drhp' && !isOpen && !isListed ? 'current' : 'done', date: filing.filing_date, pdf_url: docType === 'drhp' ? filing.pdf_url : null },
    { key: 'rhp', label: 'RHP Approved', description: 'Red Herring Prospectus approved by SEBI', state: hasRhp ? (docType === 'rhp' && !isOpen && !isListed ? 'current' : 'done') : 'pending', date: filing.rhp_filing_date || (hasRhp ? filing.filing_date : null), pdf_url: docType === 'rhp' ? filing.pdf_url : null },
    { key: 'ipo_open', label: 'Bidding Open', description: 'IPO subscription window', state: status === 'live' ? 'current' : (isOpen || isListed ? 'done' : 'pending'), date: filing.subscription_open, end_date: filing.subscription_close },
    { key: 'allotment', label: 'Allotment', description: 'Share allotment finalized', state: filing.allotment_date || isListed ? 'done' : 'pending', date: filing.allotment_date },
    { key: 'listed', label: 'Listed', description: 'Trading commenced on exchange', state: status === 'listed' ? 'current' : (isListed ? 'done' : 'pending'), date: filing.listing_date },
  ];
};

const IpoLifecyclePanel = React.memo<{ lifecycle?: any; filing: any }>(({ lifecycle, filing }) => {
  const stages: IpoLifecycleStage[] = lifecycle?.stages?.length ? lifecycle.stages : buildFallbackLifecycle(filing);
  const currentDocType = lifecycle?.current_doc_type || filing.doc_type || 'drhp';
  const latestDocumentUrl = lifecycle?.latest_document_url || filing.pdf_url;

  return (
    <section className="ipo-lifecycle-panel" aria-label="IPO lifecycle">
      <div className="ipo-lifecycle-head">
        <div>
          <div className="ipo-lifecycle-title">IPO lifecycle</div>
          <div className="ipo-lifecycle-subtitle">
            Latest official document: {fmtDocType(currentDocType)}{lifecycle?.latest_document_date ? ` - ${fmtDate(lifecycle.latest_document_date) || '—'}` : ''}
          </div>
        </div>
        {latestDocumentUrl && (
          <a href={latestDocumentUrl} target="_blank" rel="noopener noreferrer" className="ipo-lifecycle-doc-link">
            <FileText size={13} />
            View latest PDF
          </a>
        )}
      </div>

      <div className="ipo-lifecycle-track">
        {stages.map((stage, index) => {
          const state = stage.state === 'done' || stage.state === 'current' ? stage.state : 'pending';
          const connectorActive = state === 'done' || state === 'current';
          const Icon = state === 'done' ? CheckCircle2 : state === 'current' ? Clock : Circle;
          const stateLabel = state === 'done' ? 'Done' : state === 'current' ? 'Current' : 'Pending';
          const countdown = stage.countdown;
          return (
            <div key={stage.key} className={`ipo-lifecycle-step ${state}`}>
              <div className="ipo-lifecycle-step-top">
                <span className="ipo-lifecycle-dot"><Icon size={15} /></span>
                {index < stages.length - 1 && <span className={`ipo-lifecycle-connector${connectorActive ? ' active' : ''}`} />}
              </div>
              <div className="ipo-lifecycle-label">{stage.label}</div>
              <div className="ipo-lifecycle-date">
                {stage.key === 'ipo_open' && stage.end_date
                  ? `${fmtDate(stage.date) || '—'} – ${fmtDate(stage.end_date) || '—'}`
                  : (fmtDate(stage.date) || (state === 'pending' ? 'Pending' : '—'))}
              </div>
              {countdown && countdown.days >= 0 && (
                <div className="ipo-lifecycle-countdown">
                  {countdown.days === 0 ? 'Today' : countdown.days === 1 ? '1 day left' : `${countdown.days} days left`}
                </div>
              )}
              <div className="ipo-lifecycle-state">{stateLabel}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
});

IpoLifecyclePanel.displayName = 'IpoLifecyclePanel';

// ── Final IPO Signal Framework (Summary) ──────────────────────────────────────
const IpoSignalSummary = React.memo<{ signals: Record<string, Signal> }>(({ signals }) => {
  const entries: { label: string; key: string }[] = [
    { label: 'Business Quality', key: 'business' },
    { label: 'Financial Strength', key: 'financials' },
    { label: 'Growth Quality', key: 'growth' },
    { label: 'Valuation', key: 'valuation' },
    { label: 'Promoter Alignment', key: 'promoters' },
    { label: 'Proceeds Quality', key: 'proceeds' },
    { label: 'Risk Profile', key: 'risks' },
    { label: 'Institutional', key: 'institutional' },
  ];

  const positiveCount = Object.values(signals).filter(s => s === 'positive').length;
  const negativeCount = Object.values(signals).filter(s => s === 'negative').length;
  const pendingCount = Object.values(signals).filter(s => s === 'pending').length;

  let overallVerdict = 'Wait & Watch';
  let verdictClass = 'neutral';
  if (pendingCount >= 4) {
    overallVerdict = 'Analysis Incomplete';
    verdictClass = 'pending';
  } else if (positiveCount >= 5) {
    overallVerdict = 'Strong IPO';
    verdictClass = 'positive';
  } else if (negativeCount >= 4) {
    overallVerdict = 'Avoid / Post-Listing Review';
    verdictClass = 'negative';
  }

  return (
    <section className="ipo-signal-summary">
      <div className="ipo-signal-summary-head">
        <h3 className="ipo-signal-summary-title">IPO Signal Framework</h3>
        <span className={`ipo-verdict ipo-verdict--${verdictClass}`}>{overallVerdict}</span>
      </div>
      <div className="ipo-signal-grid">
        {entries.map(({ label, key }) => (
          <div key={key} className="ipo-signal-cell">
            <span className="ipo-signal-cell-label">{label}</span>
            <SignalBadge signal={signals[key] || 'pending'} />
          </div>
        ))}
      </div>
      <div className="ipo-signal-legend">
        <span className="ipo-signal-legend-item"><span style={{ color: '#4ade80' }}>+</span> Positive</span>
        <span className="ipo-signal-legend-item"><span style={{ color: '#fbbf24' }}>0</span> Neutral</span>
        <span className="ipo-signal-legend-item"><span style={{ color: '#f87171' }}>–</span> Negative</span>
        <span className="ipo-signal-legend-item"><span style={{ color: 'var(--text-muted)' }}>?</span> Pending</span>
      </div>
    </section>
  );
});

IpoSignalSummary.displayName = 'IpoSignalSummary';

// ── Module 1: Business Quality Tab ───────────────────────────────────────────
const BusinessTab = React.memo<{ analysis: any; scores: any; filing: any }>(({
  analysis, scores, filing
}) => {
  const signal = computeBusinessSignal(analysis, scores);
  const hasStrengths = (analysis.strengths || []).length > 0;
  const hasStrategies = (analysis.strategies || []).length > 0;
  const businessParagraphs = (analysis.business_overview_paragraphs || []).filter(Boolean);

  return (
    <div className="ipo-tab-content">
      <InterpretationCard
        signal={signal}
        rules={{
          positive: 'Simple, focused business model with clear revenue drivers and defensible market position.',
          neutral: 'Business model identified but may have diversification concerns or limited moat visibility.',
          negative: 'Over-diversified or unclear revenue streams; heavy single-customer dependence or unproven industry.',
        }}
      />

      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">Business overview</h3>
        {businessParagraphs.length > 0 ? (
          businessParagraphs.map((paragraph: string, index: number) => (
            <p key={index} className="ipo-prose">{paragraph}</p>
          ))
        ) : analysis.business_synthesis || analysis.business_overview_excerpt ? (
          <p className="ipo-prose">{analysis.business_synthesis || analysis.business_overview_excerpt}</p>
        ) : (
          <p className="ipo-prose muted">
            Business overview will be available once the {fmtDocType(filing.doc_type)} document is analyzed.
          </p>
        )}
      </section>

      {hasStrengths && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Key competitive strengths</h3>
          <ul className="ipo-bullet-list">
            {(analysis.strengths || []).slice(0, 8).map((s: string, i: number) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </section>
      )}

      {hasStrategies && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Growth strategies</h3>
          <ul className="ipo-bullet-list">
            {(analysis.strategies || []).slice(0, 8).map((s: string, i: number) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </section>
      )}

      {/* Industry positioning context */}
      {(filing.sector || filing.is_sme != null) && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Industry positioning</h3>
          <div className="ipo-position-grid">
            {filing.sector && (
              <div className="ipo-position-item">
                <span className="ipo-position-label">Sector</span>
                <span className="ipo-position-value">{filing.sector}</span>
              </div>
            )}
            {filing.exchange && (
              <div className="ipo-position-item">
                <span className="ipo-position-label">Exchange</span>
                <span className="ipo-position-value">{filing.exchange}</span>
              </div>
            )}
            {filing.is_sme != null && (
              <div className="ipo-position-item">
                <span className="ipo-position-label">Category</span>
                <span className="ipo-position-value">{filing.is_sme ? 'SME IPO' : 'Mainboard IPO'}</span>
              </div>
            )}
            {scores.business_quality != null && (
              <div className="ipo-position-item">
                <span className="ipo-position-label">Business Quality Score</span>
                <span className="ipo-position-value" style={{ color: scores.business_quality >= 70 ? '#4ade80' : scores.business_quality >= 45 ? '#fbbf24' : '#f87171' }}>
                  {scores.business_quality}/100
                </span>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
});

BusinessTab.displayName = 'BusinessTab';

// ── Module 2: Revenue & Profitability Tab ────────────────────────────────────
const FinancialsTab = React.memo<{ financials: any; kpis?: any; kpiRows?: any[]; summary?: string }>(({ financials, kpis, kpiRows, summary }) => {
  const signal = computeFinancialSignal(financials);
  const years = financials.years;
  const metrics = financials.metrics;
  const metricLabels: Record<string, string> = {
    revenue: 'Revenue (₹ cr)', pat: 'PAT / Net Profit (₹ cr)', ebitda: 'EBITDA (₹ cr)',
    revenue_cr: 'Revenue (₹ cr)', pat_cr: 'PAT (₹ cr)', ebitda_cr: 'EBITDA (₹ cr)',
    total_debt: 'Total Debt (₹ cr)', cash_flow: 'Operating Cash Flow (₹ cr)',
    assets: 'Total Assets (₹ cr)',
  };

  const hasData = years && metrics && Object.keys(metrics).length > 0;

  const kpiConfig = [
    { key: 'roe_pct', label: 'ROE' },
    { key: 'roce_pct', label: 'ROCE' },
    { key: 'ebitda_margin_pct', label: 'EBITDA Margin' },
    { key: 'pat_margin_pct', label: 'PAT Margin' },
    { key: 'ronw_pct', label: 'RoNW' },
    { key: 'debt_equity_ratio', label: 'Debt / Equity' },
    { key: 'eps', label: 'EPS (₹)' },
    { key: 'pe_ratio', label: 'P/E Ratio' },
    { key: 'nav', label: 'NAV (₹)' },
  ];
  const hasKpis = kpis && Object.keys(kpis).length > 0;
  const hasKpiRows = (kpiRows || []).length > 0;

  return (
    <div className="ipo-tab-content">
      <InterpretationCard
        signal={signal}
        rules={{
          positive: 'Revenue CAGR > 15% with stable or improving EBITDA margins. PAT growth in line with revenue.',
          neutral: 'Revenue growth 8–15% with volatile but improving margins.',
          negative: 'Revenue growth < 8% or margins consistently declining. PAT growth significantly below revenue.',
        }}
      />

      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">Restated financials (₹ cr)</h3>
        {summary && <p className="ipo-prose">{summary}</p>}
        {!hasData ? (
          <div className="ipo-empty" style={{ padding: '24px 0' }}>
            <div className="ipo-empty-icon">📄</div>
            <div className="ipo-empty-text">Restated financials are not available yet</div>
            <div className="ipo-empty-sub">Revenue, margins, PAT, debt, and operating-cash-flow trends will appear once filing tables are parsed.</div>
          </div>
        ) : (
          <>
            <div className="ipo-fin-table-wrap">
              <table className="ipo-fin-table">
                <thead>
                  <tr>
                    <th>Metric</th>
                    {years.map((y: string) => <th key={y}>{y}</th>)}
                    <th>CAGR</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(metrics).map(([key, values]) => {
                    const vals = (values as any[]).filter((v) => v != null) as number[];
                    const allVals = values as (number | null)[];
                    const first = vals[0] || 0;
                    const last = vals[vals.length - 1] || 0;
                    const cagr = first > 0 && vals.length > 1
                      ? ((Math.pow(last / first, 1 / (vals.length - 1)) - 1) * 100).toFixed(1)
                      : null;
                    const cagrNum = cagr ? parseFloat(cagr) : 0;
                    return (
                      <tr key={key}>
                        <td className="ipo-metric-name">{metricLabels[key] || key.replace(/_/g, ' ').toUpperCase()}</td>
                        {allVals.map((v: number | null, i: number) => {
                          const prev = i > 0 ? allVals[i - 1] : null;
                          const growth = prev && prev > 0 && v != null ? ((v - prev) / prev * 100).toFixed(0) : null;
                          return (
                            <td key={i} className="ipo-fin-cell">
                              <span className="ipo-fin-val">{v != null ? v.toLocaleString('en-IN') : '—'}</span>
                              {growth && (
                                <span className={`ipo-fin-growth ${parseFloat(growth) >= 0 ? 'up' : 'down'}`}>
                                  {parseFloat(growth) >= 0 ? '+' : ''}{growth}%
                                </span>
                              )}
                            </td>
                          );
                        })}
                        <td>
                          {cagr && (
                            <span className={`ipo-cagr-badge ${cagrNum >= 20 ? 'good' : cagrNum >= 10 ? 'ok' : 'weak'}`}>
                              {cagrNum >= 0 ? '+' : ''}{cagr}%
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {(financials.trends || financials.flags) && (
              <div className="ipo-trend-row">
                {isLikelyCagr(financials.trends?.revenue_cagr_pct) && (
                  <span className={`ipo-trend-chip${financials.trends.revenue_cagr_pct < 0 ? ' warning' : ''}`}>
                    Revenue CAGR: {financials.trends.revenue_cagr_pct > 0 ? '+' : ''}{financials.trends.revenue_cagr_pct}%
                  </span>
                )}
                {isLikelyCagr(financials.trends?.pat_cagr_pct) && (
                  <span className={`ipo-trend-chip${financials.trends.pat_cagr_pct < 0 ? ' warning' : ''}`}>
                    PAT CAGR: {financials.trends.pat_cagr_pct > 0 ? '+' : ''}{financials.trends.pat_cagr_pct}%
                  </span>
                )}
                {(financials.flags || []).map((flag: string) => (
                  <span key={flag} className="ipo-flag amber">{flag.replace(/_/g, ' ')}</span>
                ))}
              </div>
            )}
          </>
        )}
      </section>

      {(hasKpis || hasKpiRows) && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Key performance indicators</h3>
          {hasKpis && (
            <div className="ipo-kpi-grid">
              {kpiConfig.filter(k => kpis[k.key] != null).map(k => {
                const val = kpis[k.key];
                const isPercent = k.key.endsWith('_pct');
                const display = typeof val === 'number'
                  ? `${val.toFixed(2)}${isPercent ? '%' : ''}`
                  : String(val);
                return (
                  <div key={k.key} className="ipo-kpi-card">
                    <div className="ipo-kpi-label">{k.label}</div>
                    <div className="ipo-kpi-value">{display}</div>
                  </div>
                );
              })}
            </div>
          )}
          {hasKpiRows && (
            <div className="ipo-fin-table-wrap" style={{ marginTop: hasKpis ? 18 : 0 }}>
              <table className="ipo-fin-table">
                <thead>
                  <tr>
                    <th>KPI</th>
                    <th>Current</th>
                    <th>Prior</th>
                    <th>Trend</th>
                  </tr>
                </thead>
                <tbody>
                  {(kpiRows || []).map((row: any) => (
                    <tr key={row.label}>
                      <td>{row.label}</td>
                      <td>{row.current}</td>
                      <td>{row.prior}</td>
                      <td>
                        <span className={`ipo-peer-diff ${row.trend === 'improving' ? 'discount' : row.trend === 'deteriorating' ? 'premium' : ''}`}>
                          {row.trend === 'improving' ? 'Improving' : row.trend === 'deteriorating' ? 'Deteriorating' : 'Stable'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </div>
  );
});

FinancialsTab.displayName = 'FinancialsTab';

// ── Module 3: Growth vs Profitability Quality Tab ────────────────────────────
const GrowthTab = React.memo<{ financials: any; kpis?: any }>(({ financials, kpis: _kpis }) => {
  const signal = computeGrowthSignal(financials);
  const years = financials.years || [];
  const metrics = financials.metrics || {};
  const revenue = metrics.revenue || metrics.revenue_cr || [];
  const ebitda = metrics.ebitda || metrics.ebitda_cr || [];
  const pat = metrics.pat || metrics.pat_cr || [];

  // Build comparison table
  const comparisonRows: { year: string; revGrowth: string | null; ebitdaGrowth: string | null; patGrowth: string | null; divergence: boolean }[] = [];
  for (let i = 1; i < years.length; i++) {
    const revG = revenue[i - 1] > 0 && revenue[i] != null ? ((revenue[i] - revenue[i - 1]) / revenue[i - 1] * 100) : null;
    const ebitdaG = ebitda[i - 1] > 0 && ebitda[i] != null ? ((ebitda[i] - ebitda[i - 1]) / ebitda[i - 1] * 100) : null;
    const patG = pat[i - 1] > 0 && pat[i] != null ? ((pat[i] - pat[i - 1]) / pat[i - 1] * 100) : null;
    const divergence = revG != null && revG > 5 && ((ebitdaG != null && ebitdaG < revG * 0.5) || (patG != null && patG < revG * 0.5));
    comparisonRows.push({
      year: `${years[i - 1]} → ${years[i]}`,
      revGrowth: revG != null ? revG.toFixed(1) : null,
      ebitdaGrowth: ebitdaG != null ? ebitdaG.toFixed(1) : null,
      patGrowth: patG != null ? patG.toFixed(1) : null,
      divergence,
    });
  }

  // Compute margin series
  const marginSeries: { year: string; ebitdaMargin: string | null; patMargin: string | null }[] = [];
  for (let i = 0; i < years.length; i++) {
    const eM = revenue[i] > 0 && ebitda[i] != null ? (ebitda[i] / revenue[i] * 100) : null;
    const pM = revenue[i] > 0 && pat[i] != null ? (pat[i] / revenue[i] * 100) : null;
    marginSeries.push({
      year: years[i],
      ebitdaMargin: eM != null ? eM.toFixed(1) : null,
      patMargin: pM != null ? pM.toFixed(1) : null,
    });
  }

  const hasData = comparisonRows.length > 0;
  const divergenceCount = comparisonRows.filter(r => r.divergence).length;

  return (
    <div className="ipo-tab-content">
      <InterpretationCard
        signal={signal}
        rules={{
          positive: 'Profitability grows equal to or faster than revenue — operating leverage intact.',
          neutral: 'Revenue up but margins declined for 1 year — possible one-time cost or investment phase.',
          negative: 'Revenue up but margins declined for 2+ consecutive years — growth at cost of profitability.',
        }}
      />

      {!hasData ? (
        <section className="ipo-detail-block">
          <div className="ipo-empty" style={{ padding: '24px 0' }}>
            <div className="ipo-empty-icon">📊</div>
            <div className="ipo-empty-text">Growth quality analysis requires multi-year financials</div>
            <div className="ipo-empty-sub">This comparison will appear once 3-year restated financial data is available.</div>
          </div>
        </section>
      ) : (
        <>
          <section className="ipo-detail-block">
            <h3 className="ipo-detail-block-title">
              Revenue vs profitability growth
              {divergenceCount > 0 && (
                <span className="ipo-section-count" style={{ background: 'rgba(239,68,68,0.12)', color: '#fca5a5' }}>
                  {divergenceCount} divergence{divergenceCount !== 1 ? 's' : ''}
                </span>
              )}
            </h3>
            <div className="ipo-fin-table-wrap">
              <table className="ipo-fin-table">
                <thead>
                  <tr>
                    <th>Period</th>
                    <th>Revenue Growth</th>
                    <th>EBITDA Growth</th>
                    <th>PAT Growth</th>
                    <th>Signal</th>
                  </tr>
                </thead>
                <tbody>
                  {comparisonRows.map((row) => (
                    <tr key={row.year} className={row.divergence ? 'ipo-row-flagged' : ''}>
                      <td className="ipo-metric-name">{row.year}</td>
                      <td>
                        {row.revGrowth != null && (
                          <span className={`ipo-fin-growth-inline ${parseFloat(row.revGrowth) >= 0 ? 'up' : 'down'}`}>
                            {parseFloat(row.revGrowth) >= 0 ? '+' : ''}{row.revGrowth}%
                          </span>
                        )}
                      </td>
                      <td>
                        {row.ebitdaGrowth != null && (
                          <span className={`ipo-fin-growth-inline ${parseFloat(row.ebitdaGrowth) >= 0 ? 'up' : 'down'}`}>
                            {parseFloat(row.ebitdaGrowth) >= 0 ? '+' : ''}{row.ebitdaGrowth}%
                          </span>
                        )}
                      </td>
                      <td>
                        {row.patGrowth != null && (
                          <span className={`ipo-fin-growth-inline ${parseFloat(row.patGrowth) >= 0 ? 'up' : 'down'}`}>
                            {parseFloat(row.patGrowth) >= 0 ? '+' : ''}{row.patGrowth}%
                          </span>
                        )}
                      </td>
                      <td>
                        {row.divergence ? (
                          <span className="ipo-flag amber" style={{ fontSize: '10px' }}>
                            <AlertTriangle size={10} /> Diverging
                          </span>
                        ) : (
                          <span style={{ color: '#4ade80', fontSize: '11px', fontWeight: 600 }}>Aligned</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {marginSeries.length > 0 && (
            <section className="ipo-detail-block">
              <h3 className="ipo-detail-block-title">Margin trajectory</h3>
              <div className="ipo-fin-table-wrap">
                <table className="ipo-fin-table">
                  <thead>
                    <tr>
                      <th>Year</th>
                      <th>EBITDA Margin</th>
                      <th>PAT Margin</th>
                    </tr>
                  </thead>
                  <tbody>
                    {marginSeries.map((row) => (
                      <tr key={row.year}>
                        <td className="ipo-metric-name">{row.year}</td>
                        <td>{row.ebitdaMargin != null ? `${row.ebitdaMargin}%` : '—'}</td>
                        <td>{row.patMargin != null ? `${row.patMargin}%` : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Margin trend assessment */}
              {marginSeries.length >= 2 && (() => {
                const first = marginSeries[0].ebitdaMargin ? parseFloat(marginSeries[0].ebitdaMargin!) : null;
                const last = marginSeries[marginSeries.length - 1].ebitdaMargin ? parseFloat(marginSeries[marginSeries.length - 1].ebitdaMargin!) : null;
                if (first != null && last != null) {
                  const diff = last - first;
                  return (
                    <div className="ipo-trend-row" style={{ marginTop: 12 }}>
                      <span className={`ipo-trend-chip ${diff >= 0 ? '' : 'warning'}`}>
                        EBITDA Margin: {diff >= 0 ? '+' : ''}{diff.toFixed(1)}pp over period
                      </span>
                    </div>
                  );
                }
                return null;
              })()}
            </section>
          )}
        </>
      )}
    </div>
  );
});

GrowthTab.displayName = 'GrowthTab';

// ── Module 4: Valuation vs Peers Tab ─────────────────────────────────────────
const ValuationTab = React.memo<{ peerVal: any; summary?: string; filing: any }>(({ peerVal, summary, filing }) => {
  const signal = computeValuationSignal(peerVal);
  const premium = peerVal.premium_pct;
  const premiumColor = premium != null ? (premium > 30 ? '#fca5a5' : premium > 15 ? '#fcd34d' : '#4ade80') : 'var(--text-muted)';

  return (
    <div className="ipo-tab-content">
      <InterpretationCard
        signal={signal}
        rules={{
          positive: 'IPO valuation at or below peer median, or premium justified by superior growth/margins.',
          neutral: 'IPO priced up to 20% premium vs peers — not unreasonable if growth justifies it.',
          negative: 'IPO priced >30% premium without superior fundamentals — aggressive pricing.',
        }}
      />

      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">Valuation summary</h3>
        {summary && <p className="ipo-prose">{summary}</p>}
        <div className="ipo-val-summary-grid">
          <div className="ipo-val-summary-card">
            <div className="ipo-val-summary-label">IPO P/E</div>
            <div className="ipo-val-summary-val">{peerVal.ipo_pe ?? '—'}x</div>
          </div>
          <div className="ipo-val-summary-card">
            <div className="ipo-val-summary-label">Peer avg P/E</div>
            <div className="ipo-val-summary-val">{peerVal.peer_avg_pe ?? '—'}x</div>
          </div>
          <div className="ipo-val-summary-card">
            <div className="ipo-val-summary-label">Premium to peers</div>
            <div className="ipo-val-summary-val" style={{ color: premiumColor }}>
              {premium != null ? `${premium > 0 ? '+' : ''}${premium}%` : '—'}
            </div>
          </div>
          {peerVal.ipo_ev_ebitda != null && (
            <div className="ipo-val-summary-card">
              <div className="ipo-val-summary-label">EV/EBITDA</div>
              <div className="ipo-val-summary-val">{peerVal.ipo_ev_ebitda}x</div>
            </div>
          )}
          {filing.price_band && (filing.price_band.low || filing.price_band.high) && (
            <div className="ipo-val-summary-card">
              <div className="ipo-val-summary-label">Price Band</div>
              <div className="ipo-val-summary-val" style={{ fontSize: '18px' }}>
                ₹{filing.price_band.low}–₹{filing.price_band.high}
              </div>
            </div>
          )}
          {filing.issue_size_cr != null && (
            <div className="ipo-val-summary-card">
              <div className="ipo-val-summary-label">Implied Market Cap</div>
              <div className="ipo-val-summary-val" style={{ fontSize: '18px' }}>{fmtCr(filing.issue_size_cr)}</div>
            </div>
          )}
        </div>
        {peerVal.historical_note && (
          <p className="ipo-prose muted" style={{ marginTop: 12 }}>{peerVal.historical_note}</p>
        )}
      </section>

      {(peerVal.peers || []).length > 0 && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Peer comparison (listed peers from DRHP)</h3>
          <div className="ipo-fin-table-wrap">
            <table className="ipo-fin-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>P/E (x)</th>
                  <th>EV/EBITDA (x)</th>
                  <th>vs IPO P/E</th>
                </tr>
              </thead>
              <tbody>
                {peerVal.peers.map((p: any) => {
                  const diffPe = peerVal.ipo_pe && p.pe ? ((peerVal.ipo_pe - p.pe) / p.pe * 100).toFixed(0) : null;
                  return (
                    <tr key={p.company}>
                      <td>{p.company}</td>
                      <td>{p.pe ?? '—'}</td>
                      <td>{p.ev_ebitda ?? '—'}</td>
                      <td>
                        {diffPe && (
                          <span className={`ipo-peer-diff ${parseFloat(diffPe) > 0 ? 'premium' : 'discount'}`}>
                            {parseFloat(diffPe) > 0 ? '+' : ''}{diffPe}%
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
});

ValuationTab.displayName = 'ValuationTab';

// ── Module 5: Promoter & OFS Tab ─────────────────────────────────────────────
const PromotersTab = React.memo<{ promoters: any; objects: any; management: any[]; fraudSignals: any[]; filing: any; summary?: string }>(({
  promoters, objects, management, fraudSignals, filing, summary
}) => {
  const signal = computePromoterSignal(objects, promoters);
  const hasPromoters = (promoters.promoters || []).length > 0;
  const hasManagement = (management || []).length > 0;
  const ofsPct = objects.ofs_pct;
  const freshIssue = objects.fresh_issue_cr ?? filing.fresh_issue_cr;
  const ofsAmount = objects.ofs_cr ?? filing.ofs_cr;
  const totalIssue = objects.total_issue_cr ?? filing.issue_size_cr ?? ((freshIssue || 0) + (ofsAmount || 0));

  return (
    <div className="ipo-tab-content">
      <InterpretationCard
        signal={signal}
        rules={{
          positive: 'OFS < 20% of total issue. Promoters retain > 50% post-IPO — strong alignment.',
          neutral: 'Partial exit by financial investors with reasonable promoter retention.',
          negative: 'Large promoter exit or OFS > 50% of issue size — significant dilution/exit signal.',
        }}
      />

      {/* OFS Analysis */}
      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">Offer structure analysis</h3>
        {summary && <p className="ipo-prose">{summary}</p>}
        <div className="ipo-val-summary-grid">
          <div className="ipo-val-summary-card">
            <div className="ipo-val-summary-label">Total Issue</div>
            <div className="ipo-val-summary-val" style={{ fontSize: '18px' }}>{fmtCr(totalIssue)}</div>
          </div>
          {freshIssue != null && (
            <div className="ipo-val-summary-card">
              <div className="ipo-val-summary-label">Fresh Issue</div>
              <div className="ipo-val-summary-val" style={{ fontSize: '18px' }}>{fmtCr(freshIssue)}</div>
            </div>
          )}
          {ofsAmount != null && (
            <div className="ipo-val-summary-card">
              <div className="ipo-val-summary-label">Offer for Sale (OFS)</div>
              <div className="ipo-val-summary-val" style={{ fontSize: '18px', color: ofsPct != null && ofsPct > 50 ? '#f87171' : undefined }}>
                {fmtCr(ofsAmount)}
              </div>
            </div>
          )}
          {ofsPct != null && (
            <div className="ipo-val-summary-card">
              <div className="ipo-val-summary-label">OFS % of Total Issue</div>
              <div className="ipo-val-summary-val" style={{ color: ofsPct > 50 ? '#f87171' : ofsPct > 20 ? '#fbbf24' : '#4ade80' }}>
                {ofsPct}%
              </div>
            </div>
          )}
        </div>

        {/* OFS threshold indicator bar */}
        {ofsPct != null && (
          <div className="ipo-ofs-indicator" style={{ marginTop: 14 }}>
            <div className="ipo-ofs-bar-wrap">
              <div className="ipo-ofs-bar-fill" style={{ width: `${Math.min(100, ofsPct)}%` }} />
              <div className="ipo-ofs-marker" style={{ left: '20%' }} title="20% — positive threshold" />
              <div className="ipo-ofs-marker warning" style={{ left: '50%' }} title="50% — negative threshold" />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: '10px', color: 'var(--text-muted)' }}>
              <span>0%</span>
              <span style={{ flex: 1, textAlign: 'center', paddingLeft: '12%' }}>20% <span style={{ color: '#4ade80' }}>✓</span></span>
              <span style={{ flex: 1, textAlign: 'center' }}>50% <span style={{ color: '#fbbf24' }}>⚠</span></span>
              <span>100%</span>
            </div>
          </div>
        )}

        {(objects.flags || []).includes('high_ofs_exit_signal') && (
          <div className="ipo-flag-block amber" style={{ marginTop: 12 }}>
            <AlertTriangle size={13} />
            High OFS component ({ofsPct}%) — promoters significantly reducing stake
          </div>
        )}
      </section>

      {/* Promoters */}
      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">Promoter shareholding</h3>
        {hasPromoters ? (
          <div className="ipo-promoter-grid">
            {(promoters.promoters || []).map((p: any) => (
              <div key={p.name} className="ipo-promoter-card">
                <div className="ipo-promoter-name">{p.name}</div>
                {p.shareholding_pct != null && (
                  <div className="ipo-promoter-stake">{Number(p.shareholding_pct).toFixed(2)}% stake</div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <span className="ipo-prose muted">Promoter details will be available after document analysis.</span>
        )}
      </section>

      {/* Management */}
      {hasManagement && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Key management personnel</h3>
          <div className="ipo-management-grid">
            {(management || []).map((m: any, i: number) => (
              <div key={i} className="ipo-management-card">
                <div className="ipo-management-name">{m.name}</div>
                <div className="ipo-management-role">{m.designation}</div>
                {m.experience && <div className="ipo-management-exp">{m.experience}</div>}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Fraud signals relevant to promoters */}
      {fraudSignals.length > 0 && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Governance signals</h3>
          <div className="ipo-governance-alert">
            <AlertTriangle size={18} />
            <div>
              <strong>{fraudSignals.length} governance heuristic signal{fraudSignals.length !== 1 ? 's' : ''} triggered</strong>
              <ul className="ipo-fraud-signals-list">
                {fraudSignals.map((s: any, i: number) => (
                  <li key={i}>{s.label}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      )}

      {/* Litigation */}
      {promoters.litigation_count != null && promoters.litigation_count > 0 && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">
            Litigation & legal matters
            <span
              className="ipo-section-count"
              style={{ marginLeft: 8, background: promoters.litigation_count > 2 ? 'rgba(239,68,68,0.12)' : undefined }}
            >
              {promoters.litigation_count} case{promoters.litigation_count !== 1 ? 's' : ''}
            </span>
          </h3>
          {(promoters.litigation_snippets || []).length > 0 ? (
            <div className="ipo-litigation-list">
              {(promoters.litigation_snippets || []).map((s: string, i: number) => (
                <p key={i} className="ipo-litigation-item">{s}</p>
              ))}
            </div>
          ) : (
            <p className="ipo-prose muted">
              {promoters.litigation_count} litigation case{promoters.litigation_count !== 1 ? 's' : ''} mentioned in the filing.
            </p>
          )}
        </section>
      )}
    </div>
  );
});

PromotersTab.displayName = 'PromotersTab';

// ── Module 6: Use of Proceeds Tab ────────────────────────────────────────────
const ProceedsTab = React.memo<{ objects: any; filing: any }>(({ objects, filing }) => {
  const signal = computeProceedsSignal(objects);
  const hasObjectsData = (objects.utilization || []).length > 0;
  // Validate amounts — don't show obviously wrong values
  const rawFresh = objects.fresh_issue_cr ?? filing.fresh_issue_cr;
  const rawOfs = objects.ofs_cr ?? filing.ofs_cr;
  const freshIssue = isLikelyIssueCr(rawFresh) ? rawFresh : null;
  const ofsAmount = isLikelyIssueCr(rawOfs) ? rawOfs : null;
  const totalIssue = objects.total_issue_cr ?? filing.issue_size_cr ?? ((freshIssue || 0) + (ofsAmount || 0));
  const validTotal = isLikelyIssueCr(totalIssue) ? totalIssue : null;

  // Category quality classification
  const categoryQuality: Record<string, 'good' | 'neutral' | 'concern'> = {
    capex: 'good', expansion: 'good', acquisition: 'good',
    debt_repayment: 'neutral', working_capital: 'neutral',
    general_corporate: 'concern', marketing: 'neutral',
  };

  return (
    <div className="ipo-tab-content">
      <InterpretationCard
        signal={signal}
        rules={{
          positive: 'Proceeds directed to capex, expansion, or debt reduction — growth-oriented use.',
          neutral: 'Working capital + general corporate purposes — acceptable but limited visibility.',
          negative: 'Vague or unexplained fund usage; majority for shareholder exit.',
        }}
      />

      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">Objects of the issue</h3>

        {/* Issue size summary */}
        {(freshIssue || ofsAmount || validTotal) && (
          <div className="ipo-issue-summary">
            {validTotal != null && (
              <div className="ipo-issue-summary-item">
                <span className="ipo-issue-summary-label">Total Issue Size</span>
                <span className="ipo-issue-summary-value">{fmtCr(validTotal)}</span>
              </div>
            )}
            {freshIssue != null && (
              <div className="ipo-issue-summary-item">
                <span className="ipo-issue-summary-label">Fresh Issue</span>
                <span className="ipo-issue-summary-value">{fmtCr(freshIssue)}</span>
              </div>
            )}
            {ofsAmount != null && (
              <div className="ipo-issue-summary-item">
                <span className="ipo-issue-summary-label">Offer for Sale</span>
                <span className="ipo-issue-summary-value">{fmtCr(ofsAmount)}</span>
              </div>
            )}
          </div>
        )}

        {/* Utilization breakdown with quality indicators */}
        {hasObjectsData ? (
          <div className="ipo-util-grid">
            {(objects.utilization || []).map((u: any) => {
              const total = freshIssue || 1;
              const pct = total > 0 ? Math.round((u.amount_cr / total) * 100) : 0;
              const quality = categoryQuality[u.category] || 'neutral';
              return (
                <div key={u.category} className={`ipo-util-item ipo-util-item--${quality}`}>
                  <div className="ipo-util-item-header">
                    <span className="ipo-util-label">{u.label}</span>
                    <strong className="ipo-util-amount">{fmtCr(u.amount_cr)}</strong>
                  </div>
                  <div className="ipo-util-bar-wrap">
                    <div className="ipo-util-bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                  <div className="ipo-util-footer">
                    <span className="ipo-util-pct">{pct}% of fresh issue</span>
                    <span className={`ipo-util-quality ipo-util-quality--${quality}`}>
                      {quality === 'good' ? 'Growth' : quality === 'concern' ? 'Low visibility' : 'Neutral'}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="ipo-empty" style={{ padding: '24px 0' }}>
            <div className="ipo-empty-icon">💰</div>
            <div className="ipo-empty-text">Utilization breakdown not available</div>
            <div className="ipo-empty-sub">Issue utilization details will appear after document analysis.</div>
          </div>
        )}
      </section>

      {/* Flag alerts */}
      {(objects.flags || []).length > 0 && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Proceed quality alerts</h3>
          {(objects.flags || []).includes('high_debt_repayment_allocation') && (
            <div className="ipo-flag-block amber">
              <AlertTriangle size={13} />
              More than 40% of proceeds allocated to debt repayment — evaluate leverage position carefully
            </div>
          )}
          {(objects.flags || []).includes('high_gcp_allocation') && (
            <div className="ipo-flag-block amber">
              <AlertTriangle size={13} />
              More than 60% allocated to general corporate purposes — limited visibility on fund usage
            </div>
          )}
          {(objects.flags || []).includes('high_ofs_exit_signal') && (
            <div className="ipo-flag-block amber">
              <AlertTriangle size={13} />
              Majority of issue is OFS — proceeds primarily exit capital for existing shareholders
            </div>
          )}
        </section>
      )}
    </div>
  );
});

ProceedsTab.displayName = 'ProceedsTab';

// ── Module 7: Risk Factor Severity Tab ───────────────────────────────────────
const RisksTab = React.memo<{ risks: any; scores: any; summary?: string }>(({ risks, scores, summary }) => {
  const signal = computeRiskSignal(risks, scores);
  const catColors: Record<string, string> = {
    business: '#60a5fa', regulatory: '#a78bfa', financial: '#34d399',
    management: '#f59e0b', market: '#f87171',
  };

  return (
    <div className="ipo-tab-content">
      <InterpretationCard
        signal={signal}
        rules={{
          positive: 'Mostly generic industry risks. Low concentration of high-severity factors.',
          neutral: 'Customer concentration or regulatory exposure present — manageable but worth monitoring.',
          negative: 'Ongoing litigation, regulatory dependency, high leverage, or cash burn — material downside risks.',
        }}
      />

      {summary && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Risk summary</h3>
          <p className="ipo-prose">{summary}</p>
        </section>
      )}

      {risks.total_count != null && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">
            Risk landscape
            <span className="ipo-section-count" style={{ marginLeft: 8 }}>{risks.total_count} factors</span>
          </h3>
          <div className="ipo-risk-cats">
            {Object.entries(risks.by_category || {}).map(([cat, info]: [string, any]) => (
              <div key={cat} className="ipo-risk-cat-card" style={{ '--cat-color': catColors[cat] || '#60a5fa' } as React.CSSProperties}>
                <div className="ipo-risk-cat-name">{cat}</div>
                <div className="ipo-risk-cat-count">{info.count}</div>
                <div className="ipo-risk-cat-bar-wrap">
                  <div
                    className="ipo-risk-cat-bar-fill"
                    style={{ width: `${Math.min(100, info.severity_score)}%`, background: catColors[cat] || '#60a5fa' }}
                  />
                </div>
                <div className="ipo-risk-cat-score">Severity: {info.severity_score}/100</div>
              </div>
            ))}
          </div>
          {risks.dominant_category && (
            <div className="ipo-trend-row">
              <span className="ipo-trend-chip">Dominant risk: {risks.dominant_category}</span>
              {risks.regulatory_or_management_alert && (
                <span className="ipo-flag amber">
                  <AlertTriangle size={11} />
                  High regulatory/management risk concentration
                </span>
              )}
            </div>
          )}
        </section>
      )}

      {(risks.top_risks || []).length > 0 && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Top risks by severity</h3>
          <div className="ipo-risk-list">
            {(risks.top_risks || []).map((r: any) => (
              <div key={r.number} className={`ipo-risk-item ipo-risk-item--${r.severity}`}>
                <div className="ipo-risk-item-head">
                  <span className={`ipo-severity ${r.severity}`}>{r.severity}</span>
                  <span className="ipo-risk-cat-tag">{r.category}</span>
                  <span style={{ fontSize: '10px', color: 'var(--text-muted)', marginLeft: 'auto' }}>#{r.number}</span>
                </div>
                <p className="ipo-risk-text">{r.text}</p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
});

RisksTab.displayName = 'RisksTab';

// ── Module 8: Institutional & Anchor Participation Tab ───────────────────────
const InstitutionalTab = React.memo<{ filing: any; scores: any }>(({ filing, scores }) => {
  const signal = computeInstitutionalSignal(filing);
  const subTimes = filing.subscription_times;
  const subStatus = filing.subscription_status;
  const gmp = filing.gmp;
  const lotSize = filing.lot_size;

  return (
    <div className="ipo-tab-content">
      <InterpretationCard
        signal={signal}
        rules={{
          positive: 'Strong institutional participation with diversified anchor investors. Subscription > 3x.',
          neutral: 'Limited but credible institutional participation. Subscription 1–3x.',
          negative: 'Concentrated or minimal institutional interest. Undersubscribed.',
        }}
      />

      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">Subscription & market signals</h3>
        <div className="ipo-val-summary-grid">
          {subTimes != null && (
            <div className="ipo-val-summary-card">
              <div className="ipo-val-summary-label">Subscription</div>
              <div className="ipo-val-summary-val" style={{ color: subTimes >= 3 ? '#4ade80' : subTimes >= 1 ? '#fbbf24' : '#f87171' }}>
                {subTimes}x
              </div>
            </div>
          )}
          {subStatus && (
            <div className="ipo-val-summary-card">
              <div className="ipo-val-summary-label">Status</div>
              <div className="ipo-val-summary-val" style={{ fontSize: '16px' }}>{subStatus}</div>
            </div>
          )}
          {gmp != null && (
            <div className="ipo-val-summary-card">
              <div className="ipo-val-summary-label">Grey Market Premium</div>
              <div className="ipo-val-summary-val" style={{ color: gmp >= 0 ? '#4ade80' : '#f87171' }}>
                ₹{gmp}
                {filing.price_band?.high && (
                  <span style={{ fontSize: '12px', color: 'var(--text-muted)', marginLeft: 6 }}>
                    ({((gmp / filing.price_band.high) * 100).toFixed(0)}%)
                  </span>
                )}
              </div>
            </div>
          )}
          {lotSize != null && (
            <div className="ipo-val-summary-card">
              <div className="ipo-val-summary-label">Lot Size</div>
              <div className="ipo-val-summary-val" style={{ fontSize: '18px' }}>
                {lotSize} shares
                {filing.price_band?.high && (
                  <span style={{ fontSize: '12px', display: 'block', color: 'var(--text-muted)', marginTop: 2 }}>
                    Min ₹{(lotSize * filing.price_band.high).toLocaleString('en-IN')}
                  </span>
                )}
              </div>
            </div>
          )}
          {filing.price_band && (filing.price_band.low || filing.price_band.high) && (
            <div className="ipo-val-summary-card">
              <div className="ipo-val-summary-label">Price Band</div>
              <div className="ipo-val-summary-val" style={{ fontSize: '18px' }}>
                ₹{filing.price_band.low}–₹{filing.price_band.high}
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Institutional confidence indicators */}
      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">Institutional confidence assessment</h3>
        <div className="ipo-institutional-grid">
          <div className="ipo-institutional-item">
            <div className="ipo-institutional-indicator">
              <span className="ipo-institutional-dot" style={{ background: subTimes != null && subTimes >= 3 ? '#4ade80' : subTimes != null && subTimes >= 1 ? '#fbbf24' : 'var(--text-muted)' }} />
              <span>Overall subscription demand</span>
            </div>
            <p className="ipo-prose muted">
              {subTimes != null
                ? subTimes >= 10 ? 'Exceptional demand — strong institutional confidence'
                  : subTimes >= 3 ? 'Healthy oversubscription — diversified investor interest'
                  : subTimes >= 1 ? 'Moderate demand — adequate but not exceptional'
                  : 'Undersubscribed — weak institutional appetite'
                : 'Subscription data not yet available'}
            </p>
          </div>
          <div className="ipo-institutional-item">
            <div className="ipo-institutional-indicator">
              <span className="ipo-institutional-dot" style={{ background: gmp != null && gmp > 0 ? '#4ade80' : gmp != null && gmp < 0 ? '#f87171' : 'var(--text-muted)' }} />
              <span>Grey market sentiment</span>
            </div>
            <p className="ipo-prose muted">
              {gmp != null
                ? gmp > 50 ? 'Strong positive GMP — market expecting significant listing gains'
                  : gmp > 0 ? 'Positive GMP — market expects modest listing gains'
                  : gmp === 0 ? 'Flat GMP — no listing premium expected'
                  : 'Negative GMP — market expects listing below issue price'
                : 'GMP data not available'}
            </p>
          </div>
          {scores.composite_score != null && (
            <div className="ipo-institutional-item">
              <div className="ipo-institutional-indicator">
                <span className="ipo-institutional-dot" style={{ background: scores.composite_score >= 65 ? '#4ade80' : scores.composite_score >= 45 ? '#fbbf24' : '#f87171' }} />
                <span>Composite quality score</span>
              </div>
              <p className="ipo-prose muted">
                ProspektLab composite score: {scores.composite_score}/100. {
                  scores.composite_score >= 70 ? 'Strong fundamentals across all dimensions.'
                  : scores.composite_score >= 50 ? 'Mixed fundamentals — selective strengths.'
                  : 'Below-average fundamentals — multiple concerns.'
                }
              </p>
            </div>
          )}
        </div>
      </section>

      {/* Disclaimer */}
      <div className="ipo-flag-block amber" style={{ marginTop: 0 }}>
        <AlertTriangle size={13} />
        <span style={{ fontSize: '11.5px' }}>
          GMP is unofficial and crowd-sourced. Subscription data may be delayed. Neither predicts listing performance.
          Institutional participation signal is directional, not a recommendation.
        </span>
      </div>
    </div>
  );
});

InstitutionalTab.displayName = 'InstitutionalTab';

// ── Main Detail Page ──────────────────────────────────────────────────────────
export const IpoDetailPage: React.FC = () => {
  const { slug = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [data, setData] = React.useState<IpoAnalysisResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');
  const [activeTab, setActiveTab] = React.useState<DetailTab>('business');
  const [analysisStatus, setAnalysisStatus] = React.useState<string>('loading');
  const [statusMessage, setStatusMessage] = React.useState<string>('');

  // Get card data from router state (passed from dashboard)
  const cardFromState = (location.state as { card?: any } | null)?.card;
  
  const backPath = typeof (location.state as { from?: unknown } | null)?.from === 'string'
    ? (location.state as { from: string }).from
    : '/dashboard/ipo';

  React.useEffect(() => {
    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    
    const checkStatusAndLoad = async () => {
      try {
        const { getIpoAnalysisStatus, queueIpoAnalysis, getIpoAnalysis } = await import('../api/client');
        
        const status = await getIpoAnalysisStatus(slug);
        
        if (!status.exists) {
          if (!cancelled) {
            setError('IPO not found');
            setAnalysisStatus('error');
            setLoading(false);
          }
          return;
        }
        
        if (status.has_analysis && status.has_scores) {
          if (!cancelled) {
            setStatusMessage('Loading analysis...');
            const payload = await getIpoAnalysis(slug);
            setData(payload);
            setAnalysisStatus('ready');
            setLoading(false);
          }
          return;
        }

        // Completed status but actual data may have been cleared — only trust it if has_analysis is true
        if (status.analysis_status === 'completed' && status.has_analysis) {
          if (!cancelled) {
            setStatusMessage('Loading analysis...');
            const payload = await getIpoAnalysis(slug);
            setData(payload);
            setAnalysisStatus('ready');
            setLoading(false);
          }
          return;
        }
        
        if (status.analysis_status === 'in_progress') {
          if (!cancelled) {
            setStatusMessage('Analysis in progress... This may take up to 60 seconds.');
            setAnalysisStatus('processing');
          }
          pollTimer = setTimeout(checkStatusAndLoad, 3000);
          return;
        }
        
        if (status.analysis_status === 'failed') {
          if (!cancelled) {
            setError(status.error || 'Analysis failed');
            setAnalysisStatus('error');
            setLoading(false);
          }
          return;
        }
        
        if (status.analysis_status === 'pending' || !status.has_analysis) {
          if (!cancelled) {
            setStatusMessage('Preparing analysis... Waiting for a background worker to parse the DRHP.');
            setAnalysisStatus('processing');
          }
          
          const queueResult = await queueIpoAnalysis(slug, true);
          
          if (queueResult.status === 'completed') {
            if (!cancelled) {
              const payload = await getIpoAnalysis(slug);
              setData(payload);
              setAnalysisStatus('ready');
              setLoading(false);
            }
          } else if (queueResult.status === 'failed') {
            if (!cancelled) {
              setError(queueResult.error || 'Analysis failed');
              setAnalysisStatus('error');
              setLoading(false);
            }
          } else {
            pollTimer = setTimeout(checkStatusAndLoad, 3000);
          }
        }
        
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message || 'Failed to load IPO analysis');
          setAnalysisStatus('error');
          setLoading(false);
        }
      }
    };
    
    void checkStatusAndLoad();
    
    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
    };
  }, [slug]);
  
  // Background refresh for live data (only when analysis is ready)
  React.useEffect(() => {
    if (analysisStatus !== 'ready') return;
    
    let cancelled = false;
    
    const refreshData = async () => {
      try {
        const { getIpoAnalysis } = await import('../api/client');
        const payload = await getIpoAnalysis(slug);
        if (!cancelled) setData(payload);
      } catch {
        // Silently fail background refresh
      }
    };
    
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible' && !cancelled) {
        void refreshData();
      }
    }, 60000);
    
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [slug, analysisStatus]);

  const filing = data?.filing || {};
  const analysis = data?.analysis || {};
  const scores = data?.scores || {};
  const lifecycle = data?.lifecycle;
  const objects = analysis.objects_of_issue || {};
  const financials = analysis.financials || {};
  const risks = analysis.risk_factors || {};
  const promoters = analysis.promoters || {};
  const management = analysis.management || [];
  const peerVal = analysis.peer_valuation || data?.peer_valuation || {};
  const fraudSignals = analysis.fraud_signals || [];
  const ofsPct = objects.ofs_pct;
  const hasAlert = fraudSignals.length >= 2;

  // Compute all signals
  const signals: Record<string, Signal> = React.useMemo(() => ({
    business: computeBusinessSignal(analysis, scores),
    financials: computeFinancialSignal(financials),
    growth: computeGrowthSignal(financials),
    valuation: computeValuationSignal(peerVal),
    promoters: computePromoterSignal(objects, promoters),
    proceeds: computeProceedsSignal(objects),
    risks: computeRiskSignal(risks, scores),
    institutional: computeInstitutionalSignal(filing),
  }), [analysis, scores, financials, peerVal, objects, promoters, risks, filing]);

  // Memoized handlers to prevent child re-renders
  const handleBack = React.useCallback(() => navigate(backPath), [navigate, backPath]);
  const handleTabChange = React.useCallback((key: DetailTab) => setActiveTab(key), []);

  // Show error state
  if (error) {
    return (
      <AppShell title="IPO Analysis">
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-deep)' }}>
          <div style={{ flex: 1, overflowY: 'auto', padding: 'clamp(16px, 3vw, 24px) clamp(14px, 4vw, 32px) 60px' }}>
            <button type="button" className="ipo-back-btn" onClick={handleBack}>
              <ArrowLeft size={14} />
              IPO Pipeline
            </button>
            <div className="ipo-error">{error}</div>
          </div>
        </div>
      </AppShell>
    );
  }

  // Show loading/processing state
  if (loading || analysisStatus === 'processing') {
    return (
      <AppShell title={cardFromState?.company_name || 'IPO Analysis'}>
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-deep)' }}>
          <div style={{ flex: 1, overflowY: 'auto', padding: 'clamp(16px, 3vw, 24px) clamp(14px, 4vw, 32px) 60px' }}>
            <button type="button" className="ipo-back-btn" onClick={handleBack}>
              <ArrowLeft size={14} />
              IPO Pipeline
            </button>
            
            <div className="ipo-loading-full">
              <div className="ipo-loading-card">
                <div className="ipo-loading-spinner large" />
                <h2 className="ipo-loading-title">
                  {cardFromState?.company_name || 'Loading IPO Analysis'}
                </h2>
                <p className="ipo-loading-message">{statusMessage || 'Loading...'}</p>
                {analysisStatus === 'processing' && (
                  <div className="ipo-loading-progress">
                    <div className="ipo-loading-progress-bar" />
                  </div>
                )}
                {cardFromState && (
                  <div className="ipo-loading-preview">
                    <div className="ipo-loading-preview-item">
                      <span>Issue Size</span>
                      <strong>{cardFromState.issue_size_cr ? `₹${cardFromState.issue_size_cr} cr` : '—'}</strong>
                    </div>
                    <div className="ipo-loading-preview-item">
                      <span>Price Band</span>
                      <strong>
                        {cardFromState.price_band?.low && cardFromState.price_band?.high
                          ? `₹${cardFromState.price_band.low}–₹${cardFromState.price_band.high}`
                          : '—'}
                      </strong>
                    </div>
                    {cardFromState.gmp != null && (
                      <div className="ipo-loading-preview-item">
                        <span>GMP</span>
                        <strong className={cardFromState.gmp >= 0 ? 'text-up' : 'text-down'}>
                          ₹{cardFromState.gmp}
                        </strong>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell title={filing.company_name || 'IPO Analysis'}>
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-deep)' }}>
        <div style={{ flex: 1, overflowY: 'auto', padding: 'clamp(16px, 3vw, 24px) clamp(14px, 4vw, 32px) 60px' }}>

          <button type="button" className="ipo-back-btn" onClick={handleBack}>
            <ArrowLeft size={14} />
            IPO Pipeline
          </button>

          {/* Hero header */}
          <div className="ipo-detail-hero">
            <div className="ipo-detail-hero-main">
              <div className="ipo-detail-eyebrow">
                {filing.exchange && <span className="ipo-exchange-tag">{filing.exchange}</span>}
                {filing.is_sme && <span className="ipo-sme-tag">SME</span>}
                {filing.sector && <span>{filing.sector}</span>}
              </div>
              <h1 className="ipo-detail-title">{filing.company_name}</h1>
              <div className="ipo-detail-meta-row">
                {isLikelyIssueCr(filing.issue_size_cr) && <span>Issue {fmtCr(filing.issue_size_cr)}</span>}
                {isLikelyIssueCr(objects.fresh_issue_cr ?? filing.fresh_issue_cr) && <span>Fresh {fmtCrValidated(objects.fresh_issue_cr ?? filing.fresh_issue_cr)}</span>}
                {isLikelyIssueCr(objects.ofs_cr ?? filing.ofs_cr) && <span>OFS {fmtCrValidated(objects.ofs_cr ?? filing.ofs_cr)}</span>}
                {filing.subscription_open && (
                  <span>Sub {fmtDate(filing.subscription_open)}{filing.subscription_close ? ` – ${fmtDate(filing.subscription_close)}` : ''}</span>
                )}
                {filing.allotment_date && (
                  <span>Allotment {fmtDate(filing.allotment_date)}</span>
                )}
                {filing.lot_size && (
                  <span>Lot {filing.lot_size} shares</span>
                )}
                {ofsPct != null && ofsPct >= 50 && (
                  <span className="ipo-flag amber">
                    <AlertTriangle size={11} />
                    High OFS ({ofsPct}%)
                  </span>
                )}
              </div>
              {hasAlert && (
                <div className="ipo-governance-alert-inline">
                  <AlertTriangle size={14} />
                  {fraudSignals.length} governance signals flagged from DRHP
                </div>
              )}
            </div>
            <div className="ipo-detail-hero-score">
              <IpoScoreBars
                scores={scores}
                composite={scores.composite_score ?? filing.composite_score}
              />
            </div>
          </div>

          <IpoLifecyclePanel lifecycle={lifecycle} filing={filing} />

          {/* Signal Framework Summary */}
          <IpoSignalSummary signals={signals} />

          {/* Tab nav */}
          <div className="ipo-tab-nav" role="tablist">
            {TAB_CONFIG.map((tab) => (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.key}
                className={`ipo-tab-btn${activeTab === tab.key ? ' active' : ''}`}
                onClick={() => handleTabChange(tab.key)}
              >
                {tab.icon}
                {tab.label}
                <SignalBadge signal={signals[tab.key] || 'pending'} compact />
                {tab.key === 'risks' && risks.total_count > 0 && (
                  <span className="ipo-tab-count">{risks.total_count}</span>
                )}
                {tab.key === 'promoters' && hasAlert && (
                  <span className="ipo-tab-alert">!</span>
                )}
              </button>
            ))}
          </div>

          {/* Tab content */}
          {activeTab === 'business' && (
            <BusinessTab analysis={analysis} scores={scores} filing={filing} />
          )}
          {activeTab === 'financials' && (
            <FinancialsTab financials={financials} kpis={analysis.kpis} kpiRows={analysis.kpi_rows} summary={analysis.financial_summary} />
          )}
          {activeTab === 'growth' && (
            <GrowthTab financials={financials} kpis={analysis.kpis} />
          )}
          {activeTab === 'valuation' && (
            <ValuationTab peerVal={peerVal} summary={analysis.valuation_summary} filing={filing} />
          )}
          {activeTab === 'promoters' && (
            <PromotersTab
              promoters={promoters}
              objects={objects}
              management={management}
              fraudSignals={fraudSignals}
              filing={filing}
              summary={analysis.governance_summary}
            />
          )}
          {activeTab === 'proceeds' && (
            <ProceedsTab objects={objects} filing={filing} />
          )}
          {activeTab === 'risks' && (
            <RisksTab risks={risks} scores={scores} summary={analysis.risk_summary} />
          )}
          {activeTab === 'institutional' && (
            <InstitutionalTab filing={filing} scores={scores} />
          )}
        </div>
      </div>
    </AppShell>
  );
};

export default IpoDetailPage;

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
  Shield,
  Users,
} from 'lucide-react';
import { AppShell } from '../components/layout/AppShell';
import { IpoScoreBars } from '../components/ipo/IpoCard';
import { getIpoAnalysis, IpoAnalysisResponse } from '../api/client';

type DetailTab = 'overview' | 'financials' | 'valuation' | 'risks' | 'governance';

const TAB_CONFIG: { key: DetailTab; label: string; icon: React.ReactNode }[] = [
  { key: 'overview', label: 'Overview', icon: <Briefcase size={14} /> },
  { key: 'financials', label: 'Financials', icon: <BarChart3 size={14} /> },
  { key: 'valuation', label: 'Valuation', icon: <DollarSign size={14} /> },
  { key: 'risks', label: 'Risks', icon: <Shield size={14} /> },
  { key: 'governance', label: 'Governance', icon: <Users size={14} /> },
];

const fmtCr = (v?: number | null) => (v != null ? `₹${v} cr` : '—');
const fmtDate = (value?: string | null) => {
  if (!value) return null;
  try {
    return new Date(value).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
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
};

const buildFallbackLifecycle = (filing: any): IpoLifecycleStage[] => {
  const docType = String(filing.doc_type || 'drhp').toLowerCase();
  const status = String(filing.status || 'upcoming').toLowerCase();
  const hasRhp = docType === 'rhp' || docType === 'prospectus' || Boolean(filing.rhp_filing_date);
  const isOpen = status === 'live' || Boolean(filing.subscription_open);
  const isListed = status === 'listed' || Boolean(filing.listing_date);
  return [
    { key: 'drhp', label: 'DRHP', description: 'Draft Red Herring Prospectus', state: docType === 'drhp' && !isOpen && !isListed ? 'current' : 'done', date: filing.filing_date, pdf_url: docType === 'drhp' ? filing.pdf_url : null },
    { key: 'rhp', label: 'RHP Approved', description: 'Red Herring Prospectus', state: hasRhp ? (docType === 'rhp' && !isOpen && !isListed ? 'current' : 'done') : 'pending', date: filing.rhp_filing_date || (hasRhp ? filing.filing_date : null), pdf_url: docType === 'rhp' ? filing.pdf_url : null },
    { key: 'ipo_open', label: 'IPO Open', description: 'Subscription window', state: status === 'live' ? 'current' : (isOpen || isListed ? 'done' : 'pending'), date: filing.subscription_open, end_date: filing.subscription_close },
    { key: 'listed', label: 'Listed', description: 'Exchange listing', state: status === 'listed' ? 'current' : (isListed ? 'done' : 'pending'), date: filing.listing_date },
  ];
};

const IpoLifecyclePanel: React.FC<{ lifecycle?: any; filing: any }> = ({ lifecycle, filing }) => {
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
          // Connector is active for any reached stage (done or current), so the progress bar
          // extends up to the current stage and stops before pending checkpoints.
          const connectorActive = state === 'done' || state === 'current';
          const Icon = state === 'done' ? CheckCircle2 : state === 'current' ? Clock : Circle;
          // Show the state label explicitly. Only future stages (after the current one) are "Pending".
          const stateLabel = state === 'done' ? 'Done' : state === 'current' ? 'Current' : 'Pending';
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
              <div className="ipo-lifecycle-state">{stateLabel}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
};

// ── Overview Tab ──────────────────────────────────────────────────────────────
const OverviewTab: React.FC<{ analysis: any; filing: any; objects: any }> = ({
  analysis, filing, objects
}) => {
  const hasObjectsData = (objects.utilization || []).length > 0;
  const hasStrengths = (analysis.strengths || []).length > 0;
  const hasStrategies = (analysis.strategies || []).length > 0;
  
  // Show issue size breakdown even without utilization details
  const showIssueSummary = objects.fresh_issue_cr || objects.ofs_cr || filing.fresh_issue_cr || filing.ofs_cr;
  const freshIssue = objects.fresh_issue_cr ?? filing.fresh_issue_cr;
  const ofsAmount = objects.ofs_cr ?? filing.ofs_cr;
  const totalIssue = objects.total_issue_cr ?? filing.issue_size_cr ?? ((freshIssue || 0) + (ofsAmount || 0));
  const ofsPct = totalIssue > 0 && ofsAmount ? Math.round((ofsAmount / totalIssue) * 100) : null;
  
  return (
    <div className="ipo-tab-content">
      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">Business overview</h3>
        <p className="ipo-prose">
          {analysis.business_synthesis || analysis.business_overview_excerpt || (
            <span className="ipo-prose muted">
              Business overview will be available once the {fmtDocType(filing.doc_type)} document is analyzed.
            </span>
          )}
        </p>
      </section>

      {/* Strengths */}
      {hasStrengths && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Key strengths</h3>
          <ul className="ipo-bullet-list">
            {(analysis.strengths || []).slice(0, 5).map((s: string, i: number) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </section>
      )}

      {/* Strategies */}
      {hasStrategies && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Business strategies</h3>
          <ul className="ipo-bullet-list">
            {(analysis.strategies || []).slice(0, 5).map((s: string, i: number) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">Objects of the issue</h3>
        
        {/* Issue size summary */}
        {showIssueSummary && (
          <div className="ipo-issue-summary">
            <div className="ipo-issue-summary-item">
              <span className="ipo-issue-summary-label">Total Issue Size</span>
              <span className="ipo-issue-summary-value">{fmtCr(totalIssue)}</span>
            </div>
            {freshIssue != null && (
              <div className="ipo-issue-summary-item">
                <span className="ipo-issue-summary-label">Fresh Issue</span>
                <span className="ipo-issue-summary-value">{fmtCr(freshIssue)}</span>
              </div>
            )}
            {ofsAmount != null && (
              <div className="ipo-issue-summary-item">
                <span className="ipo-issue-summary-label">Offer for Sale</span>
                <span className="ipo-issue-summary-value">
                  {fmtCr(ofsAmount)}
                  {ofsPct != null && <span className="ipo-ofs-pct">({ofsPct}%)</span>}
                </span>
              </div>
            )}
          </div>
        )}
        
        {/* Utilization breakdown */}
        {hasObjectsData ? (
          <div className="ipo-util-grid">
            {(objects.utilization || []).map((u: any) => {
              const total = (freshIssue || 1);
              const pct = total > 0 ? Math.round((u.amount_cr / total) * 100) : 0;
              return (
                <div key={u.category} className="ipo-util-item">
                  <div className="ipo-util-item-header">
                    <span className="ipo-util-label">{u.label}</span>
                    <strong className="ipo-util-amount">{fmtCr(u.amount_cr)}</strong>
                  </div>
                  <div className="ipo-util-bar-wrap">
                    <div className="ipo-util-bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="ipo-util-pct">{pct}% of fresh issue</span>
                </div>
              );
            })}
          </div>
        ) : !showIssueSummary && (
          <p className="ipo-prose muted">Issue utilisation breakdown will be available after document analysis.</p>
        )}
        
        {/* Flags */}
        {(objects.flags || []).includes('high_debt_repayment_allocation') && (
          <div className="ipo-flag-block amber">
            <AlertTriangle size={13} />
            More than 40% of proceeds allocated to debt repayment — evaluate carefully
          </div>
        )}
        {(objects.flags || []).includes('high_ofs_exit_signal') && (
          <div className="ipo-flag-block amber">
            <AlertTriangle size={13} />
            High OFS component ({ofsPct}%) — promoters significantly reducing stake
          </div>
        )}
        {(objects.flags || []).includes('high_gcp_allocation') && (
          <div className="ipo-flag-block amber">
            <AlertTriangle size={13} />
            More than 60% allocated to general corporate purposes — limited visibility on fund usage
          </div>
        )}
      </section>
    </div>
  );
};

// ── Financials Tab ────────────────────────────────────────────────────────────
const FinancialsTab: React.FC<{ financials: any; kpis?: any }> = ({ financials, kpis }) => {
  const years = financials.years;
  const metrics = financials.metrics;
  const metricLabels: Record<string, string> = {
    revenue: 'Revenue (₹ cr)', pat: 'PAT / Net Profit (₹ cr)', ebitda: 'EBITDA (₹ cr)',
    revenue_cr: 'Revenue (₹ cr)', pat_cr: 'PAT (₹ cr)', ebitda_cr: 'EBITDA (₹ cr)',
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

  return (
    <div className="ipo-tab-content">
      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">Restated financials (₹ cr)</h3>
        {!hasData ? (
          <div className="ipo-empty" style={{ padding: '24px 0' }}>
            <div className="ipo-empty-icon">📄</div>
            <div className="ipo-empty-text">Financials pending DRHP analysis</div>
            <div className="ipo-empty-sub">Trigger analysis via the Analyse button to extract financials from the DRHP PDF</div>
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
                              <span className="ipo-fin-val">{v != null ? v : '—'}</span>
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
                {financials.trends?.revenue_cagr_pct != null && (
                  <span className="ipo-trend-chip">Revenue CAGR: {financials.trends.revenue_cagr_pct}%</span>
                )}
                {financials.trends?.pat_cagr_pct != null && (
                  <span className="ipo-trend-chip">PAT CAGR: {financials.trends.pat_cagr_pct}%</span>
                )}
                {(financials.flags || []).map((flag: string) => (
                  <span key={flag} className="ipo-flag amber">{flag.replace(/_/g, ' ')}</span>
                ))}
              </div>
            )}
          </>
        )}
      </section>

      {hasKpis && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Key performance indicators</h3>
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
        </section>
      )}
    </div>
  );
};

// ── Valuation Tab ─────────────────────────────────────────────────────────────
const ValuationTab: React.FC<{ peerVal: any }> = ({ peerVal }) => {
  const premium = peerVal.premium_pct;
  const premiumColor = premium != null ? (premium > 30 ? '#fca5a5' : premium > 15 ? '#fcd34d' : '#4ade80') : 'var(--text-muted)';

  return (
    <div className="ipo-tab-content">
      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">Valuation summary</h3>
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
        </div>
        {peerVal.historical_note && (
          <p className="ipo-prose muted" style={{ marginTop: 12 }}>{peerVal.historical_note}</p>
        )}
      </section>

      {(peerVal.peers || []).length > 0 && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Peer comparison</h3>
          <div className="ipo-fin-table-wrap">
            <table className="ipo-fin-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>P/E (x)</th>
                  <th>EV/EBITDA (x)</th>
                  <th>vs IPO</th>
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
};

// ── Risks Tab ─────────────────────────────────────────────────────────────────
const RisksTab: React.FC<{ risks: any }> = ({ risks }) => {
  const catColors: Record<string, string> = {
    business: '#60a5fa', regulatory: '#a78bfa', financial: '#34d399',
    management: '#f59e0b', market: '#f87171',
  };

  return (
    <div className="ipo-tab-content">
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
                <div className="ipo-risk-cat-score">Severity: {info.severity_score}</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {(risks.top_risks || []).length > 0 && (
        <section className="ipo-detail-block">
          <h3 className="ipo-detail-block-title">Key risks</h3>
          <div className="ipo-risk-list">
            {(risks.top_risks || []).map((r: any) => (
              <div key={r.number} className={`ipo-risk-item ipo-risk-item--${r.severity}`}>
                <div className="ipo-risk-item-head">
                  <span className={`ipo-severity ${r.severity}`}>{r.severity}</span>
                  <span className="ipo-risk-cat-tag">{r.category}</span>
                </div>
                <p className="ipo-risk-text">{r.text}</p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
};

// ── Governance Tab ────────────────────────────────────────────────────────────
const GovernanceTab: React.FC<{ promoters: any; management: any[]; fraudSignals: any[] }> = ({
  promoters, management, fraudSignals
}) => {
  const hasPromoters = (promoters.promoters || []).length > 0;
  const hasManagement = (management || []).length > 0;
  
  return (
    <div className="ipo-tab-content">
      {fraudSignals.length >= 2 && (
        <div className="ipo-governance-alert">
          <AlertTriangle size={18} />
          <div>
            <strong>Governance risk alert</strong>
            <p>{fraudSignals.length} SME fraud heuristic signals triggered from DRHP disclosures.</p>
            <ul className="ipo-fraud-signals-list">
              {fraudSignals.map((s: any, i: number) => (
                <li key={i}>{s.label}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">Promoters</h3>
        {hasPromoters ? (
          <div className="ipo-promoter-grid">
            {(promoters.promoters || []).map((p: any) => (
              <div key={p.name} className="ipo-promoter-card">
                <div className="ipo-promoter-name">{p.name}</div>
                {p.shareholding_pct != null && (
                  <div className="ipo-promoter-stake">{p.shareholding_pct.toFixed(2)}% stake</div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <span className="ipo-prose muted">Promoter details will be available after document analysis.</span>
        )}
      </section>

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

      {!hasPromoters && !hasManagement && promoters.litigation_count === 0 && fraudSignals.length === 0 && (
        <div className="ipo-empty" style={{ padding: '24px 0' }}>
          <div className="ipo-empty-icon">👥</div>
          <div className="ipo-empty-text">Governance details pending</div>
          <div className="ipo-empty-sub">Promoter, management, and litigation details will be extracted from the DRHP</div>
        </div>
      )}
    </div>
  );
};

// ── Main Detail Page ──────────────────────────────────────────────────────────
export const IpoDetailPage: React.FC = () => {
  const { slug = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [data, setData] = React.useState<IpoAnalysisResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');
  const [activeTab, setActiveTab] = React.useState<DetailTab>('overview');

  const backPath = typeof (location.state as { from?: unknown } | null)?.from === 'string'
    ? (location.state as { from: string }).from
    : '/dashboard/ipo';

  React.useEffect(() => {
    let cancelled = false;
    const loadAnalysis = async (showSpinner = true) => {
      if (showSpinner) setLoading(true);
      setError('');
      try {
        const payload = await getIpoAnalysis(slug);
        if (!cancelled) setData(payload);
      } catch (err: any) {
        if (!cancelled) setError(err?.message || 'Failed to load IPO analysis');
      } finally {
        if (!cancelled && showSpinner) setLoading(false);
      }
    };
    void loadAnalysis(true);
    const timer = window.setInterval(() => { void loadAnalysis(false); }, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [slug]);

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

  return (
    <AppShell title={filing.company_name || 'IPO Analysis'}>
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-deep)' }}>
        <div style={{ flex: 1, overflowY: 'auto', padding: 'clamp(16px, 3vw, 24px) clamp(14px, 4vw, 32px) 60px' }}>

          <button type="button" className="ipo-back-btn" onClick={() => navigate(backPath)}>
            <ArrowLeft size={14} />
            IPO Pipeline
          </button>

          {loading && (
            <div className="ipo-loading">
              <div className="ipo-loading-inner">
                <div className="ipo-loading-spinner" />
                Loading DRHP analysis&hellip;
              </div>
            </div>
          )}
          {error && <div className="ipo-error">{error}</div>}

          {data && (
            <>
              {/* Hero header */}
              <div className="ipo-detail-hero">
                <div className="ipo-detail-hero-main">
                  <div className="ipo-detail-eyebrow">
                    {filing.exchange && <span className="ipo-exchange-tag">{filing.exchange}</span>}
                    {filing.sector && <span>{filing.sector}</span>}
                  </div>
                  <h1 className="ipo-detail-title">{filing.company_name}</h1>
                  <div className="ipo-detail-meta-row">
                    <span>Issue {fmtCr(filing.issue_size_cr)}</span>
                    <span>Fresh {fmtCr(objects.fresh_issue_cr ?? filing.fresh_issue_cr)}</span>
                    <span>OFS {fmtCr(objects.ofs_cr ?? filing.ofs_cr)}</span>
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

              {/* Tab nav */}
              <div className="ipo-tab-nav" role="tablist">
                {TAB_CONFIG.map((tab) => (
                  <button
                    key={tab.key}
                    type="button"
                    role="tab"
                    aria-selected={activeTab === tab.key}
                    className={`ipo-tab-btn${activeTab === tab.key ? ' active' : ''}`}
                    onClick={() => setActiveTab(tab.key)}
                  >
                    {tab.icon}
                    {tab.label}
                    {tab.key === 'risks' && risks.total_count > 0 && (
                      <span className="ipo-tab-count">{risks.total_count}</span>
                    )}
                    {tab.key === 'governance' && hasAlert && (
                      <span className="ipo-tab-alert">!</span>
                    )}
                  </button>
                ))}
              </div>

              {/* Tab content */}
              {activeTab === 'overview' && (
                <OverviewTab analysis={analysis} filing={filing} objects={objects} />
              )}
              {activeTab === 'financials' && <FinancialsTab financials={financials} kpis={analysis.kpis} />}
              {activeTab === 'valuation' && <ValuationTab peerVal={peerVal} />}
              {activeTab === 'risks' && <RisksTab risks={risks} />}
              {activeTab === 'governance' && (
                <GovernanceTab promoters={promoters} management={management} fraudSignals={fraudSignals} />
              )}
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
};

export default IpoDetailPage;

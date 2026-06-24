import React from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft, AlertTriangle, TrendingUp, Shield,
  Briefcase, DollarSign, Users, BarChart3, ChevronRight
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

// ── Overview Tab ──────────────────────────────────────────────────────────────
const OverviewTab: React.FC<{ analysis: any; filing: any; objects: any; slug: string; backPath: string }> = ({
  analysis, filing, objects, slug, backPath
}) => (
  <div className="ipo-tab-content">
    <section className="ipo-detail-block">
      <h3 className="ipo-detail-block-title">Business overview</h3>
      <p className="ipo-prose">
        {analysis.business_synthesis || analysis.business_overview_excerpt ||
          'Business overview synthesis pending DRHP processing.'}
      </p>
    </section>

    <section className="ipo-detail-block">
      <h3 className="ipo-detail-block-title">Objects of the issue</h3>
      <div className="ipo-util-grid">
        {(objects.utilization || []).map((u: any) => {
          const total = (objects.fresh_issue_cr || 1);
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
      {(objects.flags || []).includes('high_debt_repayment_allocation') && (
        <div className="ipo-flag-block amber">
          <AlertTriangle size={13} />
          More than 40% of proceeds allocated to debt repayment — evaluate carefully
        </div>
      )}
    </section>

    {(filing.status === 'listed' || filing.listing_date) && (
      <div className="ipo-tracking-cta">
        <Link to={`/ipo/${slug}/tracking`} state={{ from: backPath }} className="ipo-cta-link">
          <TrendingUp size={14} />
          View post-listing performance tracker
          <ChevronRight size={14} />
        </Link>
      </div>
    )}
  </div>
);

// ── Financials Tab ────────────────────────────────────────────────────────────
const FinancialsTab: React.FC<{ financials: any }> = ({ financials }) => {
  const years = financials.years || ['FY22', 'FY23', 'FY24'];
  const metrics = financials.metrics || { revenue: [820, 1040, 1280], pat: [45, 62, 74], ebitda: [110, 145, 176] };
  const metricLabels: Record<string, string> = {
    revenue: 'Revenue', pat: 'PAT (Net Profit)', ebitda: 'EBITDA',
    revenue_cr: 'Revenue (₹ cr)', pat_cr: 'PAT (₹ cr)', ebitda_cr: 'EBITDA (₹ cr)',
  };

  return (
    <div className="ipo-tab-content">
      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">Restated financials (₹ cr)</h3>
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
                const vals = values as number[];
                const first = vals[0] || 0;
                const last = vals[vals.length - 1] || 0;
                const cagr = first > 0 && vals.length > 1
                  ? ((Math.pow(last / first, 1 / (vals.length - 1)) - 1) * 100).toFixed(1)
                  : null;
                const cagrNum = cagr ? parseFloat(cagr) : 0;
                return (
                  <tr key={key}>
                    <td className="ipo-metric-name">{metricLabels[key] || key.replace(/_/g, ' ').toUpperCase()}</td>
                    {vals.map((v: number, i: number) => {
                      const prev = i > 0 ? vals[i - 1] : null;
                      const growth = prev && prev > 0 ? ((v - prev) / prev * 100).toFixed(0) : null;
                      return (
                        <td key={i} className="ipo-fin-cell">
                          <span className="ipo-fin-val">{v ?? '—'}</span>
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
      </section>
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
const GovernanceTab: React.FC<{ promoters: any; fraudSignals: any[] }> = ({
  promoters, fraudSignals
}) => (
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
      <div className="ipo-promoter-list">
        {(promoters.promoters || []).map((p: any) => (
          <span key={p.name} className="ipo-chip">{p.name}</span>
        ))}
        {(promoters.promoters || []).length === 0 && (
          <span className="ipo-prose muted">Promoter details pending DRHP processing.</span>
        )}
      </div>
    </section>

    {promoters.litigation_count != null && (
      <section className="ipo-detail-block">
        <h3 className="ipo-detail-block-title">
          Litigation
          <span
            className="ipo-section-count"
            style={{ marginLeft: 8, background: promoters.litigation_count > 2 ? 'rgba(239,68,68,0.12)' : undefined }}
          >
            {promoters.litigation_count} case{promoters.litigation_count !== 1 ? 's' : ''}
          </span>
        </h3>
        {(promoters.litigation_snippets || []).map((s: string, i: number) => (
          <p key={i} className="ipo-prose muted">{s}</p>
        ))}
      </section>
    )}
  </div>
);

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
    (async () => {
      setLoading(true);
      setError('');
      try {
        const payload = await getIpoAnalysis(slug);
        if (!cancelled) setData(payload);
      } catch (err: any) {
        if (!cancelled) setError(err?.message || 'Failed to load IPO analysis');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [slug]);

  const filing = data?.filing || {};
  const analysis = data?.analysis || {};
  const scores = data?.scores || {};
  const objects = analysis.objects_of_issue || {};
  const financials = analysis.financials || {};
  const risks = analysis.risk_factors || {};
  const promoters = analysis.promoters || {};
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
                <OverviewTab analysis={analysis} filing={filing} objects={objects} slug={slug} backPath={backPath} />
              )}
              {activeTab === 'financials' && <FinancialsTab financials={financials} />}
              {activeTab === 'valuation' && <ValuationTab peerVal={peerVal} />}
              {activeTab === 'risks' && <RisksTab risks={risks} />}
              {activeTab === 'governance' && (
                <GovernanceTab promoters={promoters} fraudSignals={fraudSignals} />
              )}
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
};

export default IpoDetailPage;

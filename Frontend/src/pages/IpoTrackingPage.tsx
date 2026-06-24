import React from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, AlertCircle, MinusCircle, TrendingUp, TrendingDown, Activity } from 'lucide-react';
import { AppShell } from '../components/layout/AppShell';
import { getIpoTracking, IpoTrackingResponse } from '../api/client';

const statusIcon = (status: string) => {
  if (status === 'on_track') return <CheckCircle2 size={16} className="text-up" />;
  if (status === 'mixed') return <MinusCircle size={16} style={{ color: 'var(--accent-amber, #f59e0b)' }} />;
  return <AlertCircle size={16} className="text-down" />;
};

const statusLabel = (status: string) => {
  if (status === 'on_track') return 'On track';
  if (status === 'mixed') return 'Mixed progress';
  return 'Off track';
};

const ReturnCard: React.FC<{ label: string; value: string | null; isReturn?: boolean }> = ({ label, value, isReturn }) => {
  const num = isReturn && value ? parseFloat(value) : null;
  const color = num != null ? (num >= 0 ? '#4ade80' : '#f87171') : 'var(--text-primary)';
  const Icon = num != null ? (num >= 0 ? TrendingUp : TrendingDown) : Activity;

  return (
    <div className="ipo-return-card">
      <div className="ipo-return-label">{label}</div>
      <div className="ipo-return-value" style={isReturn ? { color } : {}}>
        {isReturn && num != null && <Icon size={16} />}
        {value ?? '—'}
      </div>
    </div>
  );
};

export const IpoTrackingPage: React.FC = () => {
  const { slug = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const [data, setData] = React.useState<IpoTrackingResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');

  const backPath = typeof (location.state as { from?: unknown } | null)?.from === 'string'
    ? (location.state as { from: string }).from
    : '/dashboard/ipo';

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const payload = await getIpoTracking(slug);
        if (!cancelled) setData(payload);
      } catch (err: any) {
        if (!cancelled) setError(err?.message || 'Failed to load tracking');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [slug]);

  const filing = data?.filing || {};
  const tracking = data?.tracking || {};

  const onTrackCount = (tracking.drhp_promises || []).filter((p: any) => p.status === 'on_track').length;
  const totalPromises = (tracking.drhp_promises || []).length;
  const progressPct = totalPromises > 0 ? Math.round((onTrackCount / totalPromises) * 100) : 0;

  return (
    <AppShell title={`${filing.company_name || slug} — Post-listing`}>
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-deep)' }}>
        <div style={{ flex: 1, overflowY: 'auto', padding: 'clamp(16px, 3vw, 24px) clamp(14px, 4vw, 32px) 60px' }}>

          <button
            type="button"
            className="ipo-back-btn"
            onClick={() => navigate(`/ipo/${slug}`, { state: { from: backPath } })}
          >
            <ArrowLeft size={14} />
            Back to analysis
          </button>

          {loading && (
            <div className="ipo-loading">
              <div className="ipo-loading-inner">
                <div className="ipo-loading-spinner" />
                Loading post-listing tracker&hellip;
              </div>
            </div>
          )}
          {error && <div className="ipo-error">{error}</div>}

          {data && (
            <>
              {/* Hero */}
              <div className="ipo-tracking-hero">
                <div className="ipo-detail-eyebrow">
                  {filing.exchange && <span className="ipo-exchange-tag">{filing.exchange}</span>}
                  Post-listing tracker
                </div>
                <h1 className="ipo-detail-title">{filing.company_name}</h1>
                <p className="ipo-prose muted" style={{ maxWidth: 600, marginTop: 4 }}>
                  Compares DRHP-stated objectives against post-listing performance using our quarterly results pipeline.
                </p>
              </div>

              {/* Performance metrics */}
              <div className="ipo-detail-block">
                <h3 className="ipo-detail-block-title">Listing performance</h3>
                <div className="ipo-return-grid">
                  <ReturnCard label="Issue price" value={tracking.issue_price != null ? `₹${tracking.issue_price}` : null} />
                  <ReturnCard label="Listing price" value={tracking.listing_price != null ? `₹${tracking.listing_price}` : null} />
                  <ReturnCard
                    label="Listing gain"
                    value={tracking.listing_gain_pct != null ? `${tracking.listing_gain_pct > 0 ? '+' : ''}${tracking.listing_gain_pct}%` : null}
                    isReturn
                  />
                  <ReturnCard
                    label="Current return"
                    value={tracking.current_return_pct != null ? `${tracking.current_return_pct > 0 ? '+' : ''}${tracking.current_return_pct}%` : null}
                    isReturn
                  />
                </div>
              </div>

              {/* DRHP promises tracker */}
              {totalPromises > 0 && (
                <div className="ipo-detail-block">
                  <div className="ipo-promises-header">
                    <h3 className="ipo-detail-block-title">DRHP objectives tracker</h3>
                    <div className="ipo-promises-summary">
                      <div className="ipo-promises-progress-wrap">
                        <div
                          className="ipo-promises-progress-fill"
                          style={{
                            width: `${progressPct}%`,
                            background: progressPct >= 70 ? '#4ade80' : progressPct >= 40 ? '#fbbf24' : '#f87171'
                          }}
                        />
                      </div>
                      <span className="ipo-promises-count">{onTrackCount}/{totalPromises} on track</span>
                    </div>
                  </div>

                  <div className="ipo-promise-list">
                    {(tracking.drhp_promises || []).map((item: any, idx: number) => (
                      <div key={idx} className={`ipo-promise-item ipo-promise-item--${item.status}`}>
                        <div className="ipo-promise-icon">{statusIcon(item.status)}</div>
                        <div className="ipo-promise-body">
                          <div className="ipo-promise-objective">{item.objective}</div>
                          <div className={`ipo-promise-status-label status--${item.status}`}>
                            {statusLabel(item.status)}
                          </div>
                        </div>
                        {item.detail && (
                          <div className="ipo-promise-detail">{item.detail}</div>
                        )}
                      </div>
                    ))}
                  </div>

                  {tracking.on_track != null && (
                    <div className={`ipo-overall-verdict ${tracking.on_track ? 'positive' : 'mixed'}`}>
                      {tracking.on_track
                        ? <><CheckCircle2 size={14} /> Broadly on track with DRHP plans</>
                        : <><MinusCircle size={14} /> Mixed progress vs DRHP plans</>
                      }
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
};

export default IpoTrackingPage;

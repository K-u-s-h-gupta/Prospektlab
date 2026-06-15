import React from 'react';
import { ShieldAlert, ShieldCheck, AlertTriangle, Loader2 } from 'lucide-react';
import { getPortfolioGovernance, PortfolioGovernance } from '../../api/client';
import { ProvenanceCard } from '../common/ProvenanceCard';
import { CompanyIntelModal } from './CompanyIntelModal';

/**
 * Portfolio Governance X-Ray panel — forensic governance risk overlaid on
 * the user's holdings. Consumes /portfolio/governance. Theme-native glass.
 */

const BAND_COLOR: Record<string, string> = {
  LOW: 'var(--profit)',
  MODERATE: 'var(--accent-cyan)',
  ELEVATED: '#F59E0B',
  HIGH: 'var(--loss)',
};

const SEV_COLOR: Record<string, string> = {
  high: 'var(--loss)',
  watch: '#F59E0B',
  info: 'var(--text-muted)',
};

export const GovernancePanel: React.FC = () => {
  const [data, setData] = React.useState<PortfolioGovernance | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [intel, setIntel] = React.useState<{ cin: string; name: string } | null>(null);

  React.useEffect(() => {
    let alive = true;
    setLoading(true);
    getPortfolioGovernance()
      .then((d) => { if (alive) { setData(d); setError(null); } })
      .catch((e) => { if (alive) setError(e.message || 'Failed to load governance'); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  if (loading) {
    return (
      <div className="gov-panel gov-panel-center">
        <Loader2 size={18} className="gov-spin" color="var(--accent-cyan)" />
        <span className="gov-muted">Scanning portfolio governance…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="gov-panel gov-panel-center">
        <AlertTriangle size={18} color="var(--loss)" />
        <span className="gov-muted">{error}</span>
      </div>
    );
  }

  if (!data) return null;

  const band = data.portfolio_governance_band;
  const bandColor = BAND_COLOR[band] || 'var(--text-muted)';
  const cov = data.coverage;

  return (
    <div className="gov-panel">
      <div className="gov-header">
        <div className="gov-header-title">
          {band === 'LOW'
            ? <ShieldCheck size={18} color={bandColor} />
            : <ShieldAlert size={18} color={bandColor} />}
          <span>Governance X-Ray</span>
        </div>
        <div className="gov-score-pill" style={{ borderColor: bandColor, color: bandColor }}>
          {data.portfolio_governance_score.toFixed(0)} · {band}
        </div>
      </div>

      <div className="gov-coverage">
        Scored {cov.holdings_scored}/{cov.holdings_total} holdings
        {' '}({Math.round(cov.coverage_ratio * 100)}% coverage)
      </div>

      {data.flagged_holdings.length === 0 ? (
        <div className="gov-clean">
          <ShieldCheck size={16} color="var(--profit)" />
          <span>No elevated governance risk detected across scored holdings.</span>
        </div>
      ) : (
        <div className="gov-flagged">
          {data.flagged_holdings.map((h) => (
            <div
              className="gov-flag-row"
              key={h.symbol + h.cin}
              onClick={() => h.cin && setIntel({ cin: h.cin, name: h.name || h.symbol })}
              style={{ cursor: h.cin ? 'pointer' : 'default' }}
            >
              <div className="gov-flag-head">
                <span className="gov-flag-name">{h.name || h.symbol}</span>
                <span
                  className="gov-flag-band"
                  style={{ color: BAND_COLOR[h.band] || 'var(--text-muted)' }}
                >
                  {h.score.toFixed(0)} · {h.band}
                </span>
                <span className="gov-flag-weight">{h.weight_pct.toFixed(1)}%</span>
              </div>
              <div className="gov-flag-tags">
                {h.top_flags.map((f, i) => (
                  <ProvenanceCard
                    key={i}
                    label={f.code}
                    evidence={{ detail: f.detail, source_table: 'IKG' }}
                  >
                    <span className="gov-tag" style={{ color: SEV_COLOR[f.severity] || 'var(--text-muted)' }}>
                      {f.code.replace(/_/g, ' ')}
                    </span>
                  </ProvenanceCard>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {data.unresolved && data.unresolved.length > 0 && (
        <div className="gov-unresolved">
          {data.unresolved.length} holding(s) not yet mapped to the corporate graph.
        </div>
      )}

      {intel && (
        <CompanyIntelModal cin={intel.cin} name={intel.name} onClose={() => setIntel(null)} />
      )}
    </div>
  );
};

export default GovernancePanel;

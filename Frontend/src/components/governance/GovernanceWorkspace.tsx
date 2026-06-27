import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ShieldCheck,
  ShieldAlert,
  ChevronLeft,
  AlertTriangle,
  Info,
  RefreshCw,
  Search,
  Building2,
} from 'lucide-react';
import {
  getGovernanceLeaderboard,
  getCompanyGovernance,
  GovernanceRiskRow,
  GovernanceResult,
} from '../../api/client';
import './governance.css';

type Band = 'LOW' | 'MODERATE' | 'ELEVATED' | 'HIGH';

const BAND_META: Record<Band, { label: string; color: string; bg: string }> = {
  HIGH: { label: 'High', color: '#F87171', bg: 'rgba(248,113,113,0.14)' },
  ELEVATED: { label: 'Elevated', color: '#FB923C', bg: 'rgba(251,146,60,0.14)' },
  MODERATE: { label: 'Moderate', color: '#FBBF24', bg: 'rgba(251,191,36,0.14)' },
  LOW: { label: 'Low', color: '#34D399', bg: 'rgba(52,211,153,0.12)' },
};

const FILTERS: Array<{ id: string; label: string; bands?: string }> = [
  { id: 'all', label: 'All flagged', bands: 'HIGH,ELEVATED,MODERATE' },
  { id: 'high', label: 'High', bands: 'HIGH' },
  { id: 'elevated', label: 'Elevated+', bands: 'HIGH,ELEVATED' },
];

const BandChip: React.FC<{ band: Band | null | undefined; small?: boolean }> = ({ band, small }) => {
  if (!band) {
    return (
      <span className="gov-band-chip" style={{ color: 'var(--text-muted)', background: 'rgba(148,163,184,0.10)' }}>
        Not rated
      </span>
    );
  }
  const m = BAND_META[band];
  return (
    <span className="gov-band-chip" style={{ color: m.color, background: m.bg, fontSize: small ? 10 : 11 }}>
      {m.label}
    </span>
  );
};

const ScoreBar: React.FC<{ value: number; band: Band }> = ({ value, band }) => {
  const pct = Math.max(2, Math.min(100, value));
  return (
    <div className="gov-scorebar">
      <div className="gov-scorebar-fill" style={{ width: `${pct}%`, background: BAND_META[band].color }} />
      <span className="gov-scorebar-val">{value.toFixed(0)}</span>
    </div>
  );
};

const displayName = (row: GovernanceRiskRow) =>
  (row.company_name || row.cin || '').replace(/\s+LIMITED\.?$/i, ' Ltd');

// ── Company scorecard ─────────────────────────────────────────────────────────

const Scorecard: React.FC<{ cin: string; fallbackName?: string; onBack: () => void }> = ({
  cin,
  fallbackName,
  onBack,
}) => {
  const [data, setData] = useState<GovernanceResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    getCompanyGovernance(cin)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e?.message || 'Failed to load governance detail'))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [cin]);

  const igs = data?.igs || null;
  const insufficient = !!igs?.insufficient_data;
  const band = (igs?.band || data?.band || null) as Band | null;
  const composite = igs?.composite_score ?? data?.score ?? null;

  const subscores = useMemo(() => {
    const s = data?.subscores || {};
    return Object.entries(s)
      .filter(([, v]) => typeof v === 'number')
      .sort((a, b) => (b[1] as number) - (a[1] as number));
  }, [data]);

  return (
    <div className="gov-scorecard">
      <button className="gov-back" onClick={onBack}>
        <ChevronLeft size={16} /> Back to radar
      </button>

      <div className="gov-card-head">
        <div className="gov-card-title">
          <Building2 size={18} />
          <div>
            <div className="gov-co-name">{data?.cin ? fallbackName || cin : fallbackName || cin}</div>
            <div className="gov-co-cin">{cin}</div>
          </div>
        </div>
        <BandChip band={band} />
      </div>

      {loading && <div className="gov-empty">Loading governance profile…</div>}
      {error && (
        <div className="gov-notice gov-notice-warn">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {!loading && !error && data && (
        <>
          {insufficient && (
            <div className="gov-notice">
              <Info size={15} />
              <span>
                <strong>Not rated by the model</strong> — insufficient governance data (no pledge, board, or
                enforcement history). Showing rules-based signals only.
              </span>
            </div>
          )}

          <div className="gov-metric-row">
            <div className="gov-metric">
              <span className="gov-metric-label">Composite risk</span>
              <span className="gov-metric-value">{composite != null ? composite.toFixed(0) : '—'}<small>/100</small></span>
            </div>
            <div className="gov-metric">
              <span className="gov-metric-label">Rules score</span>
              <span className="gov-metric-value">{data.score != null ? data.score.toFixed(0) : '—'}</span>
            </div>
            <div className="gov-metric">
              <span className="gov-metric-label">Model risk</span>
              <span className="gov-metric-value">
                {igs?.model_risk != null ? igs.model_risk.toFixed(0) : insufficient ? 'N/R' : '—'}
              </span>
            </div>
            <div className="gov-metric">
              <span className="gov-metric-label">Failure prob.</span>
              <span className="gov-metric-value">
                {igs?.model_probability != null ? `${(igs.model_probability * 100).toFixed(1)}%` : '—'}
              </span>
            </div>
          </div>

          {subscores.length > 0 && (
            <div className="gov-section">
              <div className="gov-section-title">Risk dimensions</div>
              {subscores.map(([key, val]) => {
                const v = val as number;
                const b: Band = v >= 75 ? 'HIGH' : v >= 50 ? 'ELEVATED' : v >= 25 ? 'MODERATE' : 'LOW';
                return (
                  <div key={key} className="gov-dim-row">
                    <span className="gov-dim-label">{key.replace(/_/g, ' ')}</span>
                    <ScoreBar value={v} band={b} />
                  </div>
                );
              })}
            </div>
          )}

          {data.flags && data.flags.length > 0 && (
            <div className="gov-section">
              <div className="gov-section-title">Flagged signals — citation-backed</div>
              {data.flags.slice(0, 12).map((f, i) => (
                <div key={i} className="gov-flag">
                  <span
                    className="gov-flag-sev"
                    style={{
                      color: f.severity === 'high' ? '#F87171' : f.severity === 'watch' ? '#FBBF24' : '#94A3B8',
                    }}
                  >
                    ●
                  </span>
                  <div className="gov-flag-body">
                    <div className="gov-flag-detail">{f.detail}</div>
                    {f.evidence && Object.keys(f.evidence).length > 0 && (
                      <div className="gov-flag-evidence">
                        {Object.entries(f.evidence)
                          .slice(0, 4)
                          .map(([k, v]) => `${k}: ${String(v)}`)
                          .join('  ·  ')}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="gov-foot">
            {igs?.model_version ? `Model ${igs.model_version}` : 'Rules engine'}
            {igs?.as_of_date ? ` · as of ${igs.as_of_date}` : ''}
            {data.computed_at ? ` · computed ${new Date(data.computed_at).toLocaleDateString('en-IN')}` : ''}
          </div>
        </>
      )}
    </div>
  );
};

// ── Workspace (leaderboard) ───────────────────────────────────────────────────

const GovernanceWorkspace: React.FC = () => {
  const [filter, setFilter] = useState('all');
  const [rows, setRows] = useState<GovernanceRiskRow[]>([]);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<{ cin: string; name?: string } | null>(null);

  const load = useCallback((bands?: string) => {
    setLoading(true);
    setError(null);
    getGovernanceLeaderboard(bands, 100)
      .then((d) => {
        setRows(d.companies || []);
        setAsOf(d.as_of);
      })
      .catch((e) => setError(e?.message || 'Failed to load governance radar'))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const f = FILTERS.find((x) => x.id === filter);
    load(f?.bands);
  }, [filter, load]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) =>
        (r.company_name || '').toLowerCase().includes(q) ||
        (r.nse_symbol || '').toLowerCase().includes(q) ||
        (r.cin || '').toLowerCase().includes(q),
    );
  }, [rows, query]);

  if (selected) {
    return <Scorecard cin={selected.cin} fallbackName={selected.name} onBack={() => setSelected(null)} />;
  }

  return (
    <div className="gov-workspace">
      <div className="gov-hero">
        <div className="gov-hero-icon">
          <ShieldAlert size={20} />
        </div>
        <div>
          <div className="gov-hero-title">Governance Risk Radar</div>
          <div className="gov-hero-sub">
            Promoter-pledge &amp; governance distress across listed India · data-backed model{' '}
            {asOf ? `· as of ${asOf}` : ''}
          </div>
        </div>
        <button className="gov-refresh" onClick={() => load(FILTERS.find((x) => x.id === filter)?.bands)} title="Refresh">
          <RefreshCw size={15} />
        </button>
      </div>

      <div className="gov-toolbar">
        <div className="gov-filters">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              className={`gov-filter-chip ${filter === f.id ? 'active' : ''}`}
              onClick={() => setFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="gov-search">
          <Search size={13} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search company or symbol…"
          />
        </div>
      </div>

      {loading && <div className="gov-empty">Scanning the universe…</div>}
      {error && (
        <div className="gov-notice gov-notice-warn">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {!loading && !error && (
        <div className="gov-board">
          <div className="gov-board-head">
            <span>#</span>
            <span>Company</span>
            <span>Band</span>
            <span>Risk</span>
            <span className="gov-col-flag">Top signal</span>
          </div>
          {visible.length === 0 && <div className="gov-empty">No companies match.</div>}
          {visible.map((r, i) => (
            <button key={r.cin} className="gov-board-row" onClick={() => setSelected({ cin: r.cin, name: displayName(r) })}>
              <span className="gov-rank">{i + 1}</span>
              <span className="gov-row-co">
                <span className="gov-row-name">{displayName(r)}</span>
                <span className="gov-row-sym">{r.nse_symbol || r.bse_scrip_code || r.cin}</span>
              </span>
              <span>
                <BandChip band={r.band} small />
              </span>
              <span className="gov-row-score">
                <ScoreBar value={r.composite_score} band={r.band} />
              </span>
              <span className="gov-col-flag gov-row-flag">
                {r.flags && r.flags.length > 0 ? r.flags[0].detail : '—'}
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="gov-coverage-note">
        <ShieldCheck size={13} /> Rated on real pledge / holding / board data. Companies without data are shown as
        “Not rated”, never as a false signal.
      </div>
    </div>
  );
};

export default GovernanceWorkspace;

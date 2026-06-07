import React from 'react';
import { Bar, Line } from 'react-chartjs-2';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Database,
  Gauge,
  MapPin,
  RefreshCcw,
  ShieldCheck,
  Sparkles,
  Target,
  Users,
} from 'lucide-react';
import { getControlTowerSnapshot, type ControlTowerSnapshot } from '../api/client';
import { MetricCard } from '../components/charts/MetricCard';
import { DonutChart } from '../components/charts/DonutChart';
import { ChartColors } from '../components/charts/ThemeProvider';
import { AppShell } from '../components/layout/AppShell';
import { useAuth } from '../context/AuthContext';

type RangeKey = '7D' | '30D' | '90D';
type TrendView = 'activation' | 'acquisition' | 'ops';

const RANGE_OPTIONS: RangeKey[] = ['7D', '30D', '90D'];
const VIEW_OPTIONS: Array<{ id: TrendView; label: string }> = [
  { id: 'activation', label: 'Activation' },
  { id: 'acquisition', label: 'Acquisition' },
  { id: 'ops', label: 'Ops' },
];

const numberFormatter = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
const compactNumberFormatter = new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 1 });
const moneyFormatter = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 });
const pctFormatter = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 1 });
const dateTimeFormatter = new Intl.DateTimeFormat('en-IN', {
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
});

const shellCardStyle: React.CSSProperties = {
  background: 'linear-gradient(180deg, rgba(11, 18, 32, 0.98), rgba(7, 12, 24, 0.94))',
  border: '1px solid rgba(96, 165, 250, 0.12)',
  borderRadius: 20,
  boxShadow: '0 20px 58px rgba(0, 0, 0, 0.32), inset 0 1px 0 rgba(255, 255, 255, 0.02)',
  backdropFilter: 'blur(16px)',
};

type FunnelStage = {
  stage: string;
  value: number | null;
  detail?: string;
};

type GeoMode = 'states' | 'cities';

function formatCount(value: unknown, empty = 'Withheld') {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numberFormatter.format(numeric) : empty;
}

function formatCompactCount(value: unknown, empty = 'Withheld') {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? compactNumberFormatter.format(numeric) : empty;
}

function formatMoney(value: unknown, empty = 'INR 0') {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? moneyFormatter.format(numeric) : empty;
}

function formatPct(value: unknown, empty = 'Withheld') {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${pctFormatter.format(numeric)}%` : empty;
}

function formatDateLabel(raw: unknown) {
  if (!raw) return '';
  const parsed = new Date(String(raw));
  if (Number.isNaN(parsed.getTime())) return String(raw);
  return parsed.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
}

function buildTrendChart(snapshot: ControlTowerSnapshot | null, view: TrendView) {
  const rows = snapshot?.series || [];
  const labels = rows.map((row) => formatDateLabel(row.date));
  const byView: Record<TrendView, Array<{ label: string; color: string; bg: string; values: number[] }>> = {
    activation: [
      {
        label: 'Known profiles',
        color: '#38BDF8',
        bg: 'rgba(56, 189, 248, 0.08)',
        values: rows.map((row) => Number(row.profiles || 0)),
      },
      {
        label: 'Workspace users',
        color: '#34D399',
        bg: 'rgba(52, 211, 153, 0.08)',
        values: rows.map((row) => Number(row.workspace_users || row.workspace || 0)),
      },
      {
        label: 'First value',
        color: '#F59E0B',
        bg: 'rgba(245, 158, 11, 0.08)',
        values: rows.map((row) => Number(row.first_value_users || row.first_value || 0)),
      },
      {
        label: 'Retained',
        color: '#818CF8',
        bg: 'rgba(129, 140, 248, 0.08)',
        values: rows.map((row) => Number(row.retained_users || row.retained || 0)),
      },
    ],
    acquisition: [
      {
        label: 'Landing',
        color: '#22D3EE',
        bg: 'rgba(34, 211, 238, 0.08)',
        values: rows.map((row) => Number(row.landing || row.landing_sessions || 0)),
      },
      {
        label: 'Signup started',
        color: '#38BDF8',
        bg: 'rgba(56, 189, 248, 0.08)',
        values: rows.map((row) => Number(row.signup_started || row.signup_started_sessions || 0)),
      },
      {
        label: 'Signup completed',
        color: '#34D399',
        bg: 'rgba(52, 211, 153, 0.08)',
        values: rows.map((row) => Number(row.signup_completed || row.signup_completed_sessions || 0)),
      },
      {
        label: 'Onboarding',
        color: '#F59E0B',
        bg: 'rgba(245, 158, 11, 0.08)',
        values: rows.map((row) => Number(row.onboarding_completed || row.onboarding_completed_sessions || 0)),
      },
    ],
    ops: [
      {
        label: 'Requests',
        color: '#38BDF8',
        bg: 'rgba(56, 189, 248, 0.08)',
        values: rows.map((row) => Number(row.requests || 0)),
      },
      {
        label: 'Dependencies',
        color: '#818CF8',
        bg: 'rgba(129, 140, 248, 0.08)',
        values: rows.map((row) => Number(row.dependencies || 0)),
      },
      {
        label: 'Errors',
        color: '#FB7185',
        bg: 'rgba(251, 113, 133, 0.08)',
        values: rows.map((row) => Number(row.errors || 0)),
      },
    ],
  };

  const datasets = byView[view];
  const hasData = datasets.some((dataset) => dataset.values.some((value) => value > 0));

  return {
    labels,
    hasData,
    data: {
      labels,
      datasets: datasets.map((dataset, idx) => ({
        label: dataset.label,
        data: dataset.values,
        borderColor: dataset.color,
        backgroundColor: dataset.bg,
        pointRadius: 0,
        pointHoverRadius: 4,
        borderWidth: 2,
        fill: idx === 0,
        tension: 0.28,
        borderJoinStyle: 'round' as const,
      })),
    },
  };
}

function buildBarChart(labels: string[], values: number[], color: string) {
  return {
    labels,
    datasets: [
      {
        label: 'Count',
        data: values,
        backgroundColor: color,
        borderRadius: 8,
        borderSkipped: false,
        maxBarThickness: 38,
      },
    ],
  };
}

function buildGeoChart(snapshot: ControlTowerSnapshot | null, mode: GeoMode) {
  const rows = mode === 'states' ? (snapshot?.geo?.top_states || []) : (snapshot?.geo?.top_cities || []);
  const labels = rows.map((row: Record<string, any>) => String(row.label || row.state || row.city || row.location || 'Unknown'));
  const values = rows.map((row: Record<string, any>) => Number(row.count || row.value || 0));
  const hasData = values.some((value: number) => value > 0);

  return {
    labels,
    hasData,
    data: {
      labels,
      datasets: [
        {
          label: mode === 'states' ? 'State contacts' : 'City contacts',
          data: values,
          backgroundColor: 'rgba(52, 211, 153, 0.84)',
          borderColor: 'rgba(52, 211, 153, 0.72)',
          borderWidth: 1,
          borderRadius: 10,
          borderSkipped: false,
          maxBarThickness: 28,
        },
      ],
    },
  };
}

const chartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: 'index' as const, intersect: false },
  plugins: {
    legend: {
      position: 'top' as const,
      labels: {
        color: ChartColors.textPrimary,
        usePointStyle: true,
        padding: 16,
      },
    },
  },
  scales: {
    x: {
      grid: { color: 'rgba(255, 255, 255, 0.03)' },
      ticks: { color: ChartColors.textSecondary },
    },
    y: {
      beginAtZero: true,
      grid: { color: 'rgba(255, 255, 255, 0.05)' },
      ticks: {
        color: ChartColors.textSecondary,
        callback: (value: unknown) => formatCompactCount(value, '0'),
      },
    },
  },
};

const horizontalGeoChartOptions = {
  ...chartOptions,
  indexAxis: 'y' as const,
  plugins: {
    legend: { display: false },
  },
  scales: {
    x: {
      beginAtZero: true,
      grid: { color: 'rgba(255, 255, 255, 0.05)' },
      ticks: { color: ChartColors.textSecondary },
    },
    y: {
      grid: { display: false },
      ticks: { color: ChartColors.textPrimary, font: { size: 11 } },
    },
  },
};

export const ControlTowerPage: React.FC = () => {
  const { showToast } = useAuth();
  const [range, setRange] = React.useState<RangeKey>('30D');
  const [view, setView] = React.useState<TrendView>('activation');
  const [geoMode, setGeoMode] = React.useState<GeoMode>('states');
  const [snapshot, setSnapshot] = React.useState<ControlTowerSnapshot | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [isRefreshing, setIsRefreshing] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const loadSnapshot = React.useCallback(async (nextRange: RangeKey, silent = false) => {
    if (silent) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setError(null);
    try {
      const result = await getControlTowerSnapshot(nextRange);
      setSnapshot(result);
      if (view === 'acquisition' && !result?.journeys?.marketing?.available) {
        setView('activation');
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load control tower';
      setError(message);
      if (!silent) {
        showToast(message, 'error');
      }
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [showToast, view]);

  React.useEffect(() => {
    void loadSnapshot(range);
  }, [loadSnapshot, range]);

  React.useEffect(() => {
    const timer = window.setInterval(() => {
      void loadSnapshot(range, true);
    }, 60000);
    return () => window.clearInterval(timer);
  }, [loadSnapshot, range]);

  const trend = React.useMemo(() => buildTrendChart(snapshot, view), [snapshot, view]);
  const displayedFunnel = React.useMemo<FunnelStage[]>(() => {
    if (!snapshot) return [];
    return view === 'acquisition' && snapshot.journeys?.marketing?.available
      ? ((snapshot.journeys.marketing?.stages || []) as FunnelStage[])
      : ((snapshot.journeys?.activation?.stages || snapshot.funnel || []) as FunnelStage[]);
  }, [snapshot, view]);
  const trackingGroups = React.useMemo(
    () => (snapshot?.tracking_groups || []).filter((item) => Number(item.total || 0) > 0).slice(0, 6),
    [snapshot]
  );
  const geoTrend = React.useMemo(() => buildGeoChart(snapshot, geoMode), [snapshot, geoMode]);
  const geoHighlights = React.useMemo(
    () => (snapshot?.geo?.top_locations || []).slice(0, 6),
    [snapshot]
  );

  const acquisitionUnavailable = snapshot && !snapshot?.journeys?.marketing?.available;
  const sourceMixLabels = (snapshot?.source_mix || [])
    .filter((item: Record<string, any>) => Number(item.value || 0) > 0)
    .map((item: Record<string, any>) => item.name);
  const sourceMixValues = (snapshot?.source_mix || [])
    .filter((item: Record<string, any>) => Number(item.value || 0) > 0)
    .map((item: Record<string, any>) => Number(item.value || 0));

  return (
    <AppShell title="Control Tower">
      <div style={{ height: '100%', overflowY: 'auto', padding: '24px 24px 48px', background: 'radial-gradient(circle at top center, rgba(56, 189, 248, 0.08), transparent 26%), radial-gradient(circle at 85% 8%, rgba(129, 140, 248, 0.08), transparent 24%), linear-gradient(180deg, rgba(2, 6, 23, 0.72), rgba(2, 6, 23, 0.94))' }}>
        <div style={{ maxWidth: 1480, margin: '0 auto', display: 'grid', gap: 18 }}>
          <section style={{ ...shellCardStyle, padding: 28, position: 'relative', overflow: 'hidden' }}>
            <div style={{
              position: 'absolute',
              inset: 0,
              background: 'radial-gradient(circle at top left, rgba(56, 189, 248, 0.14), transparent 30%), radial-gradient(circle at 90% 20%, rgba(129, 140, 248, 0.12), transparent 24%)',
              pointerEvents: 'none',
            }} />
            <div style={{ position: 'relative', zIndex: 1, display: 'grid', gridTemplateColumns: 'minmax(0, 1.5fr) minmax(320px, 430px)', gap: 20 }}>
              <div>
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '7px 12px', borderRadius: 999, border: '1px solid rgba(56, 189, 248, 0.18)', background: 'rgba(56, 189, 248, 0.08)', color: 'var(--accent-cyan)', fontSize: 11, fontWeight: 800, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                  <ShieldCheck size={14} />
                  ProspektLab Control Tower
                </div>
                <h1 style={{ margin: '16px 0 10px', fontSize: 'clamp(34px, 4vw, 52px)', lineHeight: 0.96, letterSpacing: '-0.05em' }}>
                  Operator view for growth, activation, and platform health.
                </h1>
                <p style={{ margin: 0, maxWidth: 760, color: 'var(--text-secondary)', fontSize: 15, lineHeight: 1.7 }}>
                  This is now the real product-facing dashboard surface. When acquisition telemetry is missing, the page says so directly and falls back to the verified activation journey instead of pretending the answer is zero.
                </p>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 18 }}>
                  <div style={{ padding: '9px 12px', borderRadius: 999, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', color: 'var(--text-primary)', fontSize: 13 }}>
                    <strong style={{ color: 'white' }}>Mode:</strong> {snapshot?.mode || 'loading'}
                  </div>
                  <div style={{ padding: '9px 12px', borderRadius: 999, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', color: 'var(--text-primary)', fontSize: 13 }}>
                    <strong style={{ color: 'white' }}>Snapshot:</strong> {snapshot?.generated_at ? dateTimeFormatter.format(new Date(snapshot.generated_at)) : 'Loading'}
                  </div>
                  <div style={{ padding: '9px 12px', borderRadius: 999, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', color: 'var(--text-primary)', fontSize: 13 }}>
                    <strong style={{ color: 'white' }}>Data integrity:</strong> {snapshot?.verification?.synthetic_metrics_removed ? 'Synthetic metrics removed' : 'Pending'}
                  </div>
                </div>
              </div>

              <div style={{ ...shellCardStyle, padding: 20, background: 'linear-gradient(180deg, rgba(7, 12, 24, 0.96), rgba(15, 23, 42, 0.78))' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 14 }}>
                  <div>
                    <div style={{ color: 'var(--text-secondary)', fontSize: 11, fontWeight: 700, letterSpacing: '0.09em', textTransform: 'uppercase' }}>Health Score</div>
                    <div style={{ marginTop: 10, fontSize: 40, fontWeight: 800, lineHeight: 1, color: 'var(--text-primary)' }}>{formatCount(snapshot?.health_score, '--')}</div>
                    <p style={{ margin: '10px 0 0', color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.55 }}>
                      Weighted by verified issue volume, error rate, latency, connector coverage, and the strongest measured funnel leak.
                    </p>
                  </div>
                  <div style={{ width: 56, height: 56, borderRadius: 16, background: 'rgba(56, 189, 248, 0.08)', border: '1px solid rgba(56, 189, 248, 0.16)', display: 'grid', placeItems: 'center', color: 'var(--accent-cyan)' }}>
                    <Gauge size={26} />
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12, marginTop: 18 }}>
                  <div style={{ padding: 14, borderRadius: 14, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
                    <div style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Live metrics</div>
                    <strong style={{ display: 'block', fontSize: 22, color: 'white' }}>{formatCount(snapshot?.verification?.live_metrics, '--')}</strong>
                    <small style={{ color: 'var(--text-secondary)' }}>Backed by Azure ops or live app telemetry</small>
                  </div>
                  <div style={{ padding: 14, borderRadius: 14, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
                    <div style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Persisted metrics</div>
                    <strong style={{ display: 'block', fontSize: 22, color: 'white' }}>{formatCount(snapshot?.verification?.persisted_metrics, '--')}</strong>
                    <small style={{ color: 'var(--text-secondary)' }}>Backed by Supabase and local state</small>
                  </div>
                </div>
              </div>
            </div>
          </section>

          {acquisitionUnavailable && (
            <section style={{ ...shellCardStyle, padding: 18, borderColor: 'rgba(251, 191, 36, 0.22)', background: 'linear-gradient(180deg, rgba(51, 28, 0, 0.38), rgba(15, 23, 42, 0.9))' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                <div style={{ width: 42, height: 42, borderRadius: 14, background: 'rgba(251, 191, 36, 0.1)', color: '#FBBF24', display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                  <AlertTriangle size={20} />
                </div>
                <div>
                  <div style={{ color: '#FCD34D', fontSize: 12, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Acquisition telemetry withheld</div>
                  <p style={{ margin: '6px 0 0', color: 'var(--text-primary)', fontSize: 14, lineHeight: 1.7 }}>
                    Azure is live for ops, but landing, signup, and onboarding page or custom-event telemetry is still not being emitted. This page is showing the verified activation journey from persisted product data instead of reporting fake zero traffic.
                  </p>
                </div>
              </div>
            </section>
          )}

          <section style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 14 }}>
            <MetricCard label="Known Profiles" value={formatCount(snapshot?.summary?.known_profiles)} subValue="Verified identities" icon="users" />
            <MetricCard label="Workspace Users" value={formatCount(snapshot?.summary?.workspace_users)} subValue="Persisted active users" />
            <MetricCard label="First Value Users" value={formatCount(snapshot?.summary?.first_value_sessions)} subValue="Reached insight output" />
            <MetricCard label="Retention Rate" value={formatPct(snapshot?.summary?.retention_rate)} subValue="Cross-session return rate" />
            <MetricCard label="Issue Signals" value={formatCount(snapshot?.summary?.issue_signals)} subValue="Errors in selected range" change={formatPct(snapshot?.summary?.error_rate, '--')} changeType="negative" />
            <MetricCard label="Request P95" value={snapshot?.summary?.p95_latency_ms != null ? `${Math.round(Number(snapshot.summary.p95_latency_ms))}ms` : 'Withheld'} subValue="Backend latency" />
            <MetricCard label="Token Usage" value={formatCompactCount(snapshot?.summary?.token_total)} subValue="Total token logs" />
            <MetricCard label="Outreach Messages" value={formatCount(snapshot?.summary?.outreach_messages)} subValue="Persisted campaign messages" />
          </section>

          <section style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.55fr) minmax(340px, 0.85fr)', gap: 18 }}>
            <div style={{ ...shellCardStyle, padding: 20 }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 14 }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-primary)', fontSize: 18, fontWeight: 700 }}>
                    <BarChart3 size={18} />
                    Trendlines
                  </div>
                  <p style={{ margin: '6px 0 0', color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6 }}>
                    Switch between acquisition, activation, and ops to see what is truly being measured.
                  </p>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {RANGE_OPTIONS.map((option) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => setRange(option)}
                      style={{
                        padding: '8px 12px',
                        borderRadius: 999,
                        border: `1px solid ${range === option ? 'rgba(56, 189, 248, 0.3)' : 'rgba(255,255,255,0.08)'}`,
                        background: range === option ? 'rgba(56, 189, 248, 0.12)' : 'rgba(255,255,255,0.03)',
                        color: range === option ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                        fontSize: 12,
                        fontWeight: 700,
                      }}
                    >
                      {option}
                    </button>
                  ))}
                </div>
              </div>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
                {VIEW_OPTIONS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => setView(option.id)}
                    disabled={option.id === 'acquisition' && !snapshot?.journeys?.marketing?.available}
                    style={{
                      padding: '9px 14px',
                      borderRadius: 12,
                      border: `1px solid ${view === option.id ? 'rgba(56, 189, 248, 0.26)' : 'rgba(255,255,255,0.08)'}`,
                      background: view === option.id ? 'rgba(56, 189, 248, 0.12)' : 'rgba(255,255,255,0.03)',
                      color: option.id === 'acquisition' && !snapshot?.journeys?.marketing?.available ? 'var(--text-muted)' : view === option.id ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                      fontSize: 12,
                      fontWeight: 700,
                      opacity: option.id === 'acquisition' && !snapshot?.journeys?.marketing?.available ? 0.55 : 1,
                    }}
                  >
                    {option.label}
                  </button>
                ))}
              </div>

              <div style={{ height: 340 }}>
                {!trend.hasData ? (
                  <div style={{ height: '100%', display: 'grid', placeItems: 'center', color: 'var(--text-secondary)', border: '1px dashed rgba(255,255,255,0.12)', borderRadius: 16 }}>
                    No trustworthy data is available for this chart view yet.
                  </div>
                ) : (
                  <Line data={trend.data} options={chartOptions} />
                )}
              </div>
            </div>

            <div style={{ display: 'grid', gap: 18 }}>
              <div style={{ ...shellCardStyle, padding: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-primary)', fontSize: 18, fontWeight: 700, marginBottom: 6 }}>
                  <Target size={18} />
                  Journey Funnel
                </div>
                <p style={{ margin: '0 0 12px', color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6 }}>
                  {view === 'acquisition' && snapshot?.journeys?.marketing?.available
                    ? snapshot?.journeys?.marketing?.note
                    : snapshot?.journeys?.activation?.note}
                </p>
                <div style={{ height: 280 }}>
                  {displayedFunnel.length === 0 ? (
                    <div style={{ height: '100%', display: 'grid', placeItems: 'center', color: 'var(--text-secondary)', border: '1px dashed rgba(255,255,255,0.12)', borderRadius: 16 }}>
                      No funnel data available.
                    </div>
                  ) : (
                    <Bar
                      data={buildBarChart(
                        displayedFunnel.map((item) => item.stage),
                        displayedFunnel.map((item) => Number(item.value || 0)),
                        'rgba(56, 189, 248, 0.82)'
                      )}
                      options={{
                        ...chartOptions,
                        plugins: {
                          legend: { display: false },
                        },
                      }}
                    />
                  )}
                </div>
              </div>

              <div style={{ ...shellCardStyle, padding: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-primary)', fontSize: 18, fontWeight: 700, marginBottom: 6 }}>
                  <Database size={18} />
                  Source Mix
                </div>
                <p style={{ margin: '0 0 12px', color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6 }}>
                  Weighted by measured rows, signals, and persisted activity rather than placeholder estimates.
                </p>
                <DonutChart labels={sourceMixLabels} data={sourceMixValues} title="" valueKind="percent" unit="%" />
              </div>
            </div>
          </section>

          <section style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.05fr) minmax(0, 0.95fr)', gap: 18 }}>
            <div style={{ ...shellCardStyle, padding: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-primary)', fontSize: 18, fontWeight: 700, marginBottom: 6 }}>
                <Sparkles size={18} />
                Tracking Groups
              </div>
              <p style={{ margin: '0 0 12px', color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6 }}>
                The top measured product domains across auth, onboarding, research, content, portfolio, and chat.
              </p>
              <div style={{ height: 280 }}>
                {trackingGroups.length === 0 ? (
                  <div style={{ height: '100%', display: 'grid', placeItems: 'center', color: 'var(--text-secondary)', border: '1px dashed rgba(255,255,255,0.12)', borderRadius: 16 }}>
                    No tracking groups available.
                  </div>
                ) : (
                  <Bar
                    data={buildBarChart(
                      trackingGroups.map((item) => item.label),
                      trackingGroups.map((item) => Number(item.total || 0)),
                      'rgba(129, 140, 248, 0.82)'
                    )}
                    options={{
                      ...chartOptions,
                      plugins: {
                        legend: { display: false },
                      },
                    }}
                  />
                )}
              </div>
            </div>

            <div style={{ ...shellCardStyle, padding: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-primary)', fontSize: 18, fontWeight: 700, marginBottom: 6 }}>
                <Activity size={18} />
                Source Health
              </div>
              <p style={{ margin: '0 0 14px', color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6 }}>
                Each connector shows measured coverage and what that connector is actually contributing to this snapshot.
              </p>
              <div style={{ display: 'grid', gap: 12 }}>
                {(snapshot?.source_health || []).map((item) => (
                  <div key={item.name} style={{ padding: 14, borderRadius: 14, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
                    <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
                      <div>
                        <div style={{ color: 'var(--text-primary)', fontWeight: 700 }}>{item.name}</div>
                        <div style={{ marginTop: 4, color: 'var(--text-secondary)', fontSize: 12, lineHeight: 1.55 }}>{item.note}</div>
                      </div>
                      <span style={{
                        padding: '6px 9px',
                        borderRadius: 999,
                        fontSize: 11,
                        fontWeight: 800,
                        textTransform: 'uppercase',
                        letterSpacing: '0.06em',
                        color: item.status === 'healthy' ? '#86EFAC' : item.status === 'watch' ? '#FCD34D' : '#FDA4AF',
                        background: item.status === 'healthy' ? 'rgba(52, 211, 153, 0.12)' : item.status === 'watch' ? 'rgba(245, 158, 11, 0.12)' : 'rgba(251, 113, 133, 0.12)',
                      }}>
                        {item.status}
                      </span>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12, marginTop: 12 }}>
                      <div>
                        <div style={{ color: 'var(--text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Primary metric</div>
                        <div style={{ color: 'white', fontSize: 14, fontWeight: 600, marginTop: 4 }}>{item.metric}</div>
                      </div>
                      <div>
                        <div style={{ color: 'var(--text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Coverage</div>
                        <div style={{ color: 'white', fontSize: 14, fontWeight: 600, marginTop: 4 }}>{formatPct(item.coverage, '0%')}</div>
                      </div>
                    </div>
                    <div style={{ marginTop: 10, color: 'var(--text-secondary)', fontSize: 12 }}>{item.extra}</div>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.2fr) minmax(0, 0.8fr)', gap: 18 }}>
            <div style={{ ...shellCardStyle, padding: 20 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-primary)', fontSize: 18, fontWeight: 700, marginBottom: 6 }}>
                <Users size={18} />
                Combined Users
              </div>
              <p style={{ margin: '0 0 12px', color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6 }}>
                Cross-source operator view of who reached workspace value, who stalled, and where follow-up is needed.
              </p>
              <div style={{ overflowX: 'auto', borderRadius: 16, border: '1px solid rgba(255,255,255,0.06)' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 860 }}>
                  <thead>
                    <tr style={{ background: 'rgba(255,255,255,0.03)' }}>
                      {['User', 'Stage', 'Last Seen', 'Workspace', 'Tokens', 'Portfolio', 'Action'].map((label) => (
                        <th key={label} style={{ padding: '12px 14px', textAlign: 'left', fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(snapshot?.combined_users || []).slice(0, 10).map((user) => (
                      <tr key={`${user.email}-${user.stage}`} style={{ borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                        <td style={{ padding: '14px' }}>
                          <div style={{ color: 'var(--text-primary)', fontWeight: 700 }}>{user.name || user.email || 'Unknown'}</div>
                          <div style={{ marginTop: 4, color: 'var(--text-secondary)', fontSize: 12 }}>{user.email || 'No email'}</div>
                        </td>
                        <td style={{ padding: '14px', color: 'var(--text-primary)', textTransform: 'capitalize' }}>{String(user.stage || 'unknown').replace(/_/g, ' ')}</td>
                        <td style={{ padding: '14px', color: 'var(--text-secondary)' }}>{user.last_seen ? dateTimeFormatter.format(new Date(user.last_seen)) : 'Unknown'}</td>
                        <td style={{ padding: '14px', color: 'var(--text-primary)' }}>{formatCount(user.workspace_events, '0')}</td>
                        <td style={{ padding: '14px', color: 'var(--text-primary)' }}>{formatCompactCount(user.token_usage, '0')}</td>
                        <td style={{ padding: '14px', color: 'var(--text-primary)' }}>{formatMoney(user.portfolio_value, 'INR 0')}</td>
                        <td style={{ padding: '14px' }}>
                          <span style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            padding: '6px 10px',
                            borderRadius: 999,
                            background: user.risk === 'high' ? 'rgba(251, 113, 133, 0.12)' : user.risk === 'medium' ? 'rgba(245, 158, 11, 0.12)' : 'rgba(52, 211, 153, 0.12)',
                            color: user.risk === 'high' ? '#FDA4AF' : user.risk === 'medium' ? '#FCD34D' : '#86EFAC',
                            fontSize: 11,
                            fontWeight: 700,
                          }}>
                            {user.action || 'Review'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div style={{ display: 'grid', gap: 18 }}>
              <div style={{ ...shellCardStyle, padding: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-primary)', fontSize: 18, fontWeight: 700, marginBottom: 6 }}>
                  <ShieldCheck size={18} />
                  Data Integrity
                </div>
                <p style={{ margin: '0 0 12px', color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6 }}>
                  The page distinguishes live, persisted, and withheld metrics explicitly.
                </p>
                <div style={{ display: 'grid', gap: 10 }}>
                  {[
                    { label: 'Live metrics', value: snapshot?.verification?.live_metrics, icon: <Activity size={16} /> },
                    { label: 'Persisted metrics', value: snapshot?.verification?.persisted_metrics, icon: <Database size={16} /> },
                    { label: 'Withheld metrics', value: snapshot?.verification?.unavailable_metrics, icon: <AlertTriangle size={16} /> },
                  ].map((item) => (
                    <div key={item.label} style={{ padding: 14, borderRadius: 14, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-primary)', fontWeight: 600 }}>
                        <span style={{ width: 34, height: 34, borderRadius: 12, display: 'grid', placeItems: 'center', background: 'rgba(56, 189, 248, 0.08)', color: 'var(--accent-cyan)' }}>{item.icon}</span>
                        {item.label}
                      </div>
                      <strong style={{ color: 'white', fontSize: 22 }}>{formatCount(item.value, '--')}</strong>
                    </div>
                  ))}
                </div>
                {(snapshot?.verification?.connector_gaps || []).length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
                    {snapshot?.verification?.connector_gaps?.map((gap) => (
                      <span key={gap} style={{ padding: '8px 10px', borderRadius: 999, background: 'rgba(245, 158, 11, 0.12)', color: '#FCD34D', fontSize: 11, fontWeight: 700 }}>
                        {gap}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <div style={{ ...shellCardStyle, padding: 20 }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 6 }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-primary)', fontSize: 18, fontWeight: 700 }}>
                      <MapPin size={18} />
                      Geo Footprint
                    </div>
                    <p style={{ margin: '6px 0 0', color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6 }}>
                      Derived only from contact city and state fields. No coordinates are invented, so the location view stays truthful.
                    </p>
                  </div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {[
                      { id: 'states', label: 'States' },
                      { id: 'cities', label: 'Cities' },
                    ].map((option) => (
                      <button
                        key={option.id}
                        type="button"
                        onClick={() => setGeoMode(option.id as GeoMode)}
                        style={{
                          padding: '8px 12px',
                          borderRadius: 999,
                          border: `1px solid ${geoMode === option.id ? 'rgba(56, 189, 248, 0.26)' : 'rgba(255,255,255,0.08)'}`,
                          background: geoMode === option.id ? 'rgba(56, 189, 248, 0.12)' : 'rgba(255,255,255,0.03)',
                          color: geoMode === option.id ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                          fontSize: 12,
                          fontWeight: 700,
                        }}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12, marginTop: 12 }}>
                  <div style={{ padding: 14, borderRadius: 14, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
                    <div style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Location coverage</div>
                    <strong style={{ display: 'block', fontSize: 22, color: 'white' }}>{formatPct(snapshot?.geo?.location_coverage, '--')}</strong>
                    <small style={{ color: 'var(--text-secondary)' }}>Contacts with city or state data</small>
                  </div>
                  <div style={{ padding: 14, borderRadius: 14, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
                    <div style={{ fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>Located contacts</div>
                    <strong style={{ display: 'block', fontSize: 22, color: 'white' }}>{formatCount(snapshot?.geo?.contacts_with_location, '--')}</strong>
                    <small style={{ color: 'var(--text-secondary)' }}>Out of {formatCount(snapshot?.geo?.contacts_total, '--')} total contacts</small>
                  </div>
                </div>

                <div style={{ height: 240, marginTop: 16 }}>
                  {!geoTrend.hasData ? (
                    <div style={{ height: '100%', display: 'grid', placeItems: 'center', color: 'var(--text-secondary)', border: '1px dashed rgba(255,255,255,0.12)', borderRadius: 16 }}>
                      No verified location data available.
                    </div>
                  ) : (
                    <Bar data={geoTrend.data} options={horizontalGeoChartOptions} />
                  )}
                </div>

                <div style={{ display: 'grid', gap: 8, marginTop: 14 }}>
                  {geoHighlights.length === 0 ? (
                    <div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>No geo hotspots to display yet.</div>
                  ) : (
                    geoHighlights.map((item: Record<string, any>) => {
                      const label = String(item.label || item.location || item.state || item.city || 'Unknown');
                      const count = Number(item.count || 0);
                      const pct = Number(item.pct || 0);
                      return (
                        <div key={label} style={{ padding: '10px 12px', borderRadius: 12, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.05)' }}>
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                            <div style={{ minWidth: 0 }}>
                              <div style={{ color: 'var(--text-primary)', fontWeight: 700, fontSize: 13, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{label}</div>
                              <div style={{ marginTop: 4, color: 'var(--text-secondary)', fontSize: 11 }}>{formatCount(count, '0')} contacts</div>
                            </div>
                            <strong style={{ color: 'white', fontSize: 12 }}>{formatPct(pct, '0%')}</strong>
                          </div>
                          <div style={{ height: 6, borderRadius: 999, background: 'rgba(255,255,255,0.06)', marginTop: 8, overflow: 'hidden' }}>
                            <div style={{ width: `${Math.min(100, Math.max(4, pct))}%`, height: '100%', borderRadius: 999, background: 'linear-gradient(90deg, rgba(52, 211, 153, 0.9), rgba(56, 189, 248, 0.9))' }} />
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              <div style={{ ...shellCardStyle, padding: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-primary)', fontSize: 18, fontWeight: 700, marginBottom: 6 }}>
                  <BarChart3 size={18} />
                  Top Events
                </div>
                <p style={{ margin: '0 0 12px', color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6 }}>
                  The loudest measured event families across the selected range.
                </p>
                <div style={{ display: 'grid', gap: 10 }}>
                  {(snapshot?.top_events || []).slice(0, 8).map((item) => (
                    <div key={`${item.name}-${item.label}`} style={{ padding: 14, borderRadius: 14, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                        <div>
                          <div style={{ color: 'var(--text-primary)', fontWeight: 700 }}>{item.label || item.name}</div>
                          <div style={{ marginTop: 4, color: 'var(--text-secondary)', fontSize: 12 }}>{item.name}</div>
                        </div>
                        <div style={{ color: 'white', fontWeight: 700 }}>{formatCount(item.count, '0')}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </section>

          <section style={{ ...shellCardStyle, padding: 20 }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-primary)', fontSize: 18, fontWeight: 700 }}>
                  <Database size={18} />
                  Supabase Inventory
                </div>
                <p style={{ margin: '6px 0 0', color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6 }}>
                  Every connected table that is contributing to the control tower right now.
                </p>
              </div>
              <button
                type="button"
                onClick={() => void loadSnapshot(range, true)}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  padding: '10px 14px',
                  borderRadius: 12,
                  border: '1px solid rgba(255,255,255,0.08)',
                  background: 'rgba(255,255,255,0.03)',
                  color: 'var(--text-primary)',
                  fontWeight: 700,
                }}
              >
                <RefreshCcw size={15} className={isRefreshing ? 'animate-spin-custom' : ''} />
                {isRefreshing ? 'Refreshing' : 'Refresh'}
              </button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12 }}>
              {(snapshot?.supabase?.tables || []).slice(0, 12).map((item: Record<string, any>) => (
                <div key={String(item.table)} style={{ padding: 16, borderRadius: 16, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10 }}>
                    <div>
                      <div style={{ color: 'var(--text-primary)', fontWeight: 700 }}>{item.label}</div>
                      <div style={{ marginTop: 4, color: 'var(--text-secondary)', fontSize: 12, lineHeight: 1.55 }}>{item.note}</div>
                    </div>
                    <span style={{
                      padding: '6px 9px',
                      borderRadius: 999,
                      fontSize: 11,
                      fontWeight: 800,
                      textTransform: 'uppercase',
                      color: item.status === 'healthy' ? '#86EFAC' : item.status === 'watch' ? '#FCD34D' : '#FDA4AF',
                      background: item.status === 'healthy' ? 'rgba(52, 211, 153, 0.12)' : item.status === 'watch' ? 'rgba(245, 158, 11, 0.12)' : 'rgba(251, 113, 133, 0.12)',
                    }}>
                      {item.status}
                    </span>
                  </div>
                  <div style={{ marginTop: 14, color: 'white', fontSize: 24, fontWeight: 800 }}>{formatCount(item.count, '0')}</div>
                  <div style={{ marginTop: 8, color: 'var(--text-secondary)', fontSize: 12 }}>
                    {item.last_seen ? `Last row: ${dateTimeFormatter.format(new Date(item.last_seen))}` : 'No recent row'}
                  </div>
                </div>
              ))}
            </div>
          </section>

          {(isLoading || error) && (
            <section style={{ ...shellCardStyle, padding: 18 }}>
              <div style={{ color: error ? '#FDA4AF' : 'var(--text-secondary)', fontSize: 14 }}>
                {error || 'Loading control tower...'}
              </div>
            </section>
          )}
        </div>
      </div>
    </AppShell>
  );
};

export default ControlTowerPage;

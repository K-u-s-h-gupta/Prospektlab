import React from 'react';

export function MetricCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  sub?: string;
  tone?: 'up' | 'down' | 'neutral' | 'accent';
}) {
  const color = tone === 'up'
    ? 'var(--profit)'
    : tone === 'down'
      ? 'var(--loss)'
      : tone === 'accent'
        ? 'var(--accent-cyan)'
        : 'var(--text-primary)';

  return (
    <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
      <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: 11, marginBottom: 6, letterSpacing: 0.2 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color, fontFamily: 'var(--font-mono)' }}>{value}</div>
      {sub && <div style={{ color: 'var(--text-muted)', marginTop: 4, fontSize: 10.5 }}>{sub}</div>}
    </div>
  );
}

export function HealthGauge({ health }: { health: any }) {
  const score = Number(health?.score);
  if (!Number.isFinite(score)) return null;

  const band = health?.band || '';
  const color = score >= 75 ? 'var(--profit)' : score >= 50 ? 'var(--accent-cyan)' : score >= 25 ? '#fbbf24' : 'var(--loss)';
  const comps = health?.components || {};
  const maxes = health?.max_components || {};
  const order: Array<[string, string]> = [
    ['diversification', 'Diversification'],
    ['risk_adjusted_return', 'Risk-adj. return'],
    ['drawdown_resilience', 'Drawdown resilience'],
    ['volatility', 'Volatility'],
    ['concentration', 'Concentration'],
  ];
  const r = 52;
  const circ = 2 * Math.PI * r;
  const frac = Math.max(0, Math.min(1, score / 100));

  return (
    <div style={{ display: 'flex', gap: 22, alignItems: 'center', flexWrap: 'wrap' }}>
      <div style={{ position: 'relative', width: 132, height: 132, flexShrink: 0 }}>
        <svg width={132} height={132}>
          <circle cx={66} cy={66} r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={10} />
          <circle cx={66} cy={66} r={r} fill="none" stroke={color} strokeWidth={10} strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={circ * (1 - frac)} transform="rotate(-90 66 66)" />
        </svg>
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ fontSize: 32, fontWeight: 800, color, lineHeight: 1 }}>{score}</div>
          <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>/ 100</div>
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 220 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color, marginBottom: 10 }}>{band}</div>
        {order.map(([key, label]) => {
          const value = Number(comps[key] ?? 0);
          const max = Number(maxes[key] ?? 1);
          const pct = max > 0 ? (value / max) * 100 : 0;
          return (
            <div key={key} style={{ marginBottom: 7 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: 'var(--text-secondary)', marginBottom: 3 }}>
                <span>{label}</span>
                <span style={{ fontFamily: 'var(--font-mono)' }}>{value.toFixed(0)}/{max}</span>
              </div>
              <div style={{ height: 5, background: 'rgba(255,255,255,0.06)', borderRadius: 3 }}>
                <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 3, transition: 'width .4s' }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function CorrelationHeatmap({ matrix, labels }: { matrix: Array<Array<number | null>>; labels: string[] }) {
  if (!labels?.length || !matrix?.length) return null;
  const short = labels.map((label) => label.replace('.NS', '').replace('.BO', '').slice(0, 7));
  const cellColor = (value: number | null) => {
    if (value === null || value === undefined) return 'rgba(255,255,255,0.03)';
    if (value >= 0.7) return 'rgba(251,113,133,0.55)';
    if (value >= 0.4) return 'rgba(251,113,133,0.30)';
    if (value >= 0.1) return 'rgba(251,191,36,0.22)';
    if (value >= -0.1) return 'rgba(255,255,255,0.06)';
    return 'rgba(52,211,153,0.28)';
  };

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: 10 }}>
        <thead>
          <tr><th></th>{short.map((symbol, index) => <th key={index} style={{ padding: '2px 4px', color: 'var(--text-muted)', fontWeight: 600 }}>{symbol}</th>)}</tr>
        </thead>
        <tbody>
          {matrix.map((row, rowIndex) => (
            <tr key={rowIndex}>
              <td style={{ padding: '2px 6px', color: 'var(--text-secondary)', fontWeight: 600, whiteSpace: 'nowrap' }}>{short[rowIndex]}</td>
              {row.map((value, columnIndex) => (
                <td key={columnIndex} title={`${short[rowIndex]} ↔ ${short[columnIndex]}: ${value ?? 'n/a'}`} style={{ background: cellColor(value), color: 'var(--text-primary)', textAlign: 'center', padding: '6px 8px', border: '1px solid rgba(0,0,0,0.25)', fontFamily: 'var(--font-mono)', minWidth: 36 }}>
                  {value === null || value === undefined ? '·' : value.toFixed(2)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DrawdownSparkline({ series }: { series: Array<{ date: string; drawdown_pct: number }> }) {
  if (!series || series.length < 2) return null;
  const width = 100;
  const height = 32;
  const values = series.map((point) => point.drawdown_pct);
  const min = Math.min(...values, 0);
  const points = series.map((point, index) => {
    const x = (index / (series.length - 1)) * width;
    const frac = min < 0 ? point.drawdown_pct / min : 0;
    const y = frac * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const line = points.map((point, index) => (index === 0 ? `M ${point}` : `L ${point}`)).join(' ');
  const area = `${line} L ${width},${height} L 0,${height} Z`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ width: '100%', height: 40, display: 'block' }}>
      <path d={area} fill="rgba(251,113,133,0.15)" />
      <path d={line} fill="none" stroke="var(--loss)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

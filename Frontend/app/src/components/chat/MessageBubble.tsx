import React from 'react';
import { User, Brain } from 'lucide-react';
import { AreaChart } from '../charts/AreaChart';
import { BarChart } from '../charts/BarChart';
import { DonutChart } from '../charts/DonutChart';
import { MetricCard } from '../charts/MetricCard';
import { CalloutBlock } from './CalloutBlock';
import { SectionBlock } from './SectionBlock';
import { HtmlArtifact } from './HtmlArtifact';
import { TableBlock } from '../charts/TableBlock';
import { RadarChart } from '../charts/RadarChart';
import { TreemapChart } from '../charts/TreemapChart';

// ─── Inline markdown renderer ────────────────────────────────────────────────
// Handles: **bold**, *italic*, `code`, [SOURCE:...], [AS-OF:...],
//          [CONFIDENCE:...], [ESTIMATE], [CONFLICT]
const renderInlineMarkdown = (text: string): React.ReactNode[] => {
  const nodes: React.ReactNode[] = [];
  const regex =
    /\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`|\[SOURCE:\s*([^\]]+)\]|\[AS-OF:\s*([^\]]+)\]|\[CONFIDENCE:\s*([^\]]+)\]|\[ESTIMATE\]|\[CONFLICT\]/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let ki = 0;

  while ((m = regex.exec(text)) !== null) {
    if (m.index > last) {
      nodes.push(<span key={ki++}>{text.slice(last, m.index)}</span>);
    }
    if (m[1] !== undefined) {
      nodes.push(
        <strong key={ki++} style={{ fontWeight: 700, color: 'var(--text-primary)' }}>
          {m[1]}
        </strong>
      );
    } else if (m[2] !== undefined) {
      nodes.push(
        <em key={ki++} style={{ color: 'var(--text-secondary)', fontStyle: 'italic' }}>
          {m[2]}
        </em>
      );
    } else if (m[3] !== undefined) {
      nodes.push(
        <code
          key={ki++}
          style={{
            background: 'rgba(56,189,248,0.1)',
            color: 'var(--accent-cyan)',
            padding: '1px 5px',
            borderRadius: '4px',
            fontSize: '11px',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {m[3]}
        </code>
      );
    } else if (m[4] !== undefined) {
      nodes.push(
        <span
          key={ki++}
          style={{
            fontSize: '9px',
            background: 'rgba(129,140,248,0.12)',
            color: 'var(--accent-indigo)',
            border: '1px solid rgba(129,140,248,0.2)',
            borderRadius: '4px',
            padding: '1px 5px',
            marginLeft: '3px',
            fontWeight: 600,
          }}
        >
          ⬡ {m[4]}
        </span>
      );
    } else if (m[5] !== undefined) {
      nodes.push(
        <span
          key={ki++}
          style={{
            fontSize: '9px',
            background: 'rgba(56,189,248,0.08)',
            color: 'var(--accent-cyan)',
            border: '1px solid rgba(56,189,248,0.15)',
            borderRadius: '4px',
            padding: '1px 5px',
            marginLeft: '3px',
          }}
        >
          📅 {m[5]}
        </span>
      );
    } else if (m[6] !== undefined) {
      const level = m[6].trim().toUpperCase();
      const color =
        level === 'HIGH'
          ? 'var(--profit)'
          : level === 'LOW'
          ? 'var(--loss)'
          : 'var(--accent-indigo)';
      nodes.push(
        <span
          key={ki++}
          style={{
            fontSize: '9px',
            color,
            border: `1px solid ${color}`,
            borderRadius: '4px',
            padding: '1px 5px',
            marginLeft: '4px',
            opacity: 0.85,
            fontWeight: 600,
          }}
        >
          ◈ {level}
        </span>
      );
    } else if (m[0] === '[ESTIMATE]') {
      nodes.push(
        <span
          key={ki++}
          style={{
            fontSize: '9px',
            background: 'rgba(251,191,36,0.1)',
            color: '#fbbf24',
            border: '1px solid rgba(251,191,36,0.2)',
            borderRadius: '4px',
            padding: '1px 5px',
            marginLeft: '3px',
          }}
        >
          ~ est.
        </span>
      );
    } else if (m[0] === '[CONFLICT]') {
      nodes.push(
        <span
          key={ki++}
          style={{
            fontSize: '9px',
            background: 'rgba(239,68,68,0.1)',
            color: 'var(--loss)',
            border: '1px solid rgba(239,68,68,0.2)',
            borderRadius: '4px',
            padding: '1px 5px',
            marginLeft: '3px',
          }}
        >
          ⚠ conflict
        </span>
      );
    }
    last = regex.lastIndex;
  }

  if (last < text.length) {
    nodes.push(<span key={ki++}>{text.slice(last)}</span>);
  }
  return nodes;
};

// ─── Block-level markdown renderer ──────────────────────────────────────────
// Handles: #/##/###/####/#####, unordered/ordered lists, HR, tables, paragraphs
const renderMarkdownContent = (text: string): React.ReactNode[] => {
  if (!text) return [];
  const lines = text.split('\n');
  const output: React.ReactNode[] = [];
  let listBuffer: { ordered: boolean; items: string[] } | null = null;
  let tableBuffer: { headers: string[]; rows: string[][] } | null = null;
  let ki = 0;

  const flushList = () => {
    if (!listBuffer) return;
    const Tag = listBuffer.ordered ? 'ol' : 'ul';
    output.push(
      <Tag
        key={ki++}
        style={{
          margin: '6px 0',
          paddingLeft: '20px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
        }}
      >
        {listBuffer.items.map((item, i) => (
          <li key={i} style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.55 }}>
            {renderInlineMarkdown(item)}
          </li>
        ))}
      </Tag>
    );
    listBuffer = null;
  };

  const flushTable = () => {
    if (!tableBuffer) return;
    output.push(
      <div
        key={ki++}
        style={{
          overflowX: 'auto',
          margin: '10px 0',
          width: '100%',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          borderRadius: '6px',
        }}
      >
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontSize: '12.5px',
            textAlign: 'left',
            minWidth: '450px',
          }}
        >
          <thead>
            <tr
              style={{
                background: 'rgba(255, 255, 255, 0.03)',
                borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
              }}
            >
              {tableBuffer.headers.map((h, i) => (
                <th
                  key={i}
                  style={{
                    padding: '8px 12px',
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                  }}
                >
                  {renderInlineMarkdown(h)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tableBuffer.rows.map((row, rIdx) => (
              <tr
                key={rIdx}
                style={{
                  borderBottom:
                    rIdx < tableBuffer!.rows.length - 1
                      ? '1px solid rgba(255, 255, 255, 0.04)'
                      : 'none',
                }}
              >
                {row.map((cell, cIdx) => (
                  <td
                    key={cIdx}
                    style={{
                      padding: '8px 12px',
                      color: 'var(--text-secondary)',
                    }}
                  >
                    {renderInlineMarkdown(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
    tableBuffer = null;
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    // --- Table ---
    if (line.trim().startsWith('|')) {
      flushList();
      const cells = line
        .split('|')
        .map((c) => c.trim())
        .filter((_, idx, arr) => idx > 0 && idx < arr.length - 1);
      const isSeparator = cells.every((c) => /^[:-\s]+$/.test(c));
      if (!isSeparator) {
        if (!tableBuffer) {
          tableBuffer = { headers: cells, rows: [] };
        } else {
          tableBuffer.rows.push(cells);
        }
      }
      continue;
    }

    // --- H5 (##### heading) → small bold accent label ---
    const h5 = line.match(/^#####\s+(.+)/);
    if (h5) {
      flushTable(); flushList();
      output.push(
        <div
          key={ki++}
          style={{
            fontSize: '10.5px',
            fontWeight: 700,
            color: 'var(--text-muted)',
            letterSpacing: '0.07em',
            textTransform: 'uppercase',
            marginTop: '10px',
            marginBottom: '2px',
          }}
        >
          {renderInlineMarkdown(h5[1])}
        </div>
      );
      continue;
    }

    // --- H4 (#### heading) → bold label with left bar ---
    const h4 = line.match(/^####\s+(.+)/);
    if (h4) {
      flushTable(); flushList();
      output.push(
        <div
          key={ki++}
          style={{
            fontSize: '12px',
            fontWeight: 700,
            color: 'var(--text-primary)',
            marginTop: '12px',
            marginBottom: '3px',
            paddingLeft: '8px',
            borderLeft: '2px solid rgba(56,189,248,0.4)',
          }}
        >
          {renderInlineMarkdown(h4[1])}
        </div>
      );
      continue;
    }

    // --- H3 ---
    const h3 = line.match(/^###\s+(.+)/);
    if (h3) {
      flushTable(); flushList();
      output.push(
        <div
          key={ki++}
          style={{
            fontSize: '13px',
            fontWeight: 700,
            color: 'var(--text-primary)',
            marginTop: '14px',
            marginBottom: '4px',
            borderBottom: '1px solid rgba(255,255,255,0.07)',
            paddingBottom: '4px',
          }}
        >
          {renderInlineMarkdown(h3[1])}
        </div>
      );
      continue;
    }

    // --- H2 ---
    const h2 = line.match(/^##\s+(.+)/);
    if (h2) {
      flushTable(); flushList();
      output.push(
        <div
          key={ki++}
          style={{
            fontSize: '14px',
            fontWeight: 700,
            color: 'var(--accent-indigo)',
            marginTop: '16px',
            marginBottom: '4px',
            borderBottom: '1px solid rgba(129,140,248,0.2)',
            paddingBottom: '5px',
          }}
        >
          {renderInlineMarkdown(h2[1])}
        </div>
      );
      continue;
    }

    // --- H1 ---
    const h1 = line.match(/^#\s+(.+)/);
    if (h1) {
      flushTable(); flushList();
      output.push(
        <div
          key={ki++}
          style={{
            fontSize: '15px',
            fontWeight: 800,
            color: 'var(--accent-cyan)',
            marginTop: '18px',
            marginBottom: '6px',
            letterSpacing: '0.02em',
          }}
        >
          {renderInlineMarkdown(h1[1])}
        </div>
      );
      continue;
    }

    // --- Horizontal rule ---
    if (/^---+$/.test(line.trim())) {
      flushTable(); flushList();
      output.push(
        <hr
          key={ki++}
          style={{ border: 'none', borderTop: '1px solid rgba(255,255,255,0.08)', margin: '10px 0' }}
        />
      );
      continue;
    }

    // --- Unordered list item ---
    const ul = line.match(/^[-*]\s+(.+)/);
    if (ul) {
      flushTable();
      if (listBuffer && !listBuffer.ordered) {
        listBuffer.items.push(ul[1]);
      } else {
        flushList();
        listBuffer = { ordered: false, items: [ul[1]] };
      }
      continue;
    }

    // --- Ordered list item ---
    const ol = line.match(/^\d+\.\s+(.+)/);
    if (ol) {
      flushTable();
      if (listBuffer && listBuffer.ordered) {
        listBuffer.items.push(ol[1]);
      } else {
        flushList();
        listBuffer = { ordered: true, items: [ol[1]] };
      }
      continue;
    }

    // --- Empty line ---
    if (line.trim() === '') {
      flushTable(); flushList();
      output.push(<div key={ki++} style={{ height: '6px' }} />);
      continue;
    }

    // --- Normal paragraph line ---
    flushTable(); flushList();
    output.push(
      <div
        key={ki++}
        style={{ fontSize: '13.5px', color: 'var(--text-secondary)', lineHeight: 1.6 }}
      >
        {renderInlineMarkdown(line)}
      </div>
    );
  }

  flushTable();
  flushList();
  return output;
};

// ─── Message content parser ──────────────────────────────────────────────────
const parseMessageContent = (text: string) => {
  if (!text) return [];
  const cleanText = text.replace(/^\[NEW_PROMPT_V2_ACTIVE\]\s*/, '');
  const regex = /```(chart|kpi|table|callout|section|html)\s*([\s\S]*?)\s*```/g;
  const segments: Array<{ type: string; content: any }> = [];
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(cleanText)) !== null) {
    const type = match[1];
    const jsonStr = match[2];
    const index = match.index;
    if (index > lastIndex) {
      segments.push({ type: 'text', content: cleanText.substring(lastIndex, index) });
    }
    if (type === 'html') {
      let parsed;
      try { parsed = JSON.parse(jsonStr); } catch { parsed = jsonStr; }
      segments.push({ type, content: parsed });
    } else {
      try {
        segments.push({ type, content: JSON.parse(jsonStr) });
      } catch {
        segments.push({ type: 'text', content: match[0] });
      }
    }
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < cleanText.length) {
    segments.push({ type: 'text', content: cleanText.substring(lastIndex) });
  }
  return segments;
};

// ─── Group consecutive KPI blocks ────────────────────────────────────────────
const groupSegments = (segments: Array<{ type: string; content: any }>) => {
  const grouped: Array<{ type: string; content: any }> = [];
  let currentKpis: any[] = [];
  for (const seg of segments) {
    if (seg.type === 'kpi') {
      currentKpis.push(seg.content);
    } else {
      if (currentKpis.length > 0) {
        grouped.push({ type: 'kpi_group', content: currentKpis });
        currentKpis = [];
      }
      grouped.push(seg);
    }
  }
  if (currentKpis.length > 0) grouped.push({ type: 'kpi_group', content: currentKpis });
  return grouped;
};

// ─── Segment renderer ─────────────────────────────────────────────────────────
const renderSegment = (seg: { type: string; content: any }, idx: number): React.ReactNode => {
  if (seg.type === 'text') {
    return (
      <div key={idx} style={{ wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
        {renderMarkdownContent(seg.content)}
      </div>
    );
  }
  if (seg.type === 'kpi_group') {
    return (
      <div
        key={idx}
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: '8px',
          margin: '10px 0',
          width: '100%',
        }}
      >
        {seg.content.map((kpi: any, kIdx: number) => (
          <MetricCard
            key={kIdx}
            label={kpi.label}
            value={kpi.value}
            change={kpi.delta}
            changeType={kpi.trend === 'up' ? 'positive' : kpi.trend === 'down' ? 'negative' : 'neutral'}
          />
        ))}
      </div>
    );
  }
  if (seg.type === 'chart') {
    const chart = seg.content;
    const hasLabels = chart.labels && chart.labels.length > 0;
    const hasData =
      chart.datasets && chart.datasets.length > 0 &&
      chart.datasets[0].data && chart.datasets[0].data.length > 0;
    if (!hasLabels || !hasData) return null;
    const labels = chart.labels;
    const primaryDataset = chart.datasets[0];
    const comparisonDataset = chart.datasets[1];
    return (
      <div
        key={idx}
        className="glass animate-scale-pop"
        style={{
          padding: '16px', margin: '12px 0',
          background: 'rgba(15, 23, 42, 0.45)',
          border: '1px solid rgba(255, 255, 255, 0.05)',
          borderRadius: '8px', width: '100%',
        }}
      >
        {chart.type === 'area' || chart.type === 'line' ? (
          <AreaChart labels={labels} data={primaryDataset.data} title={chart.title} unit={chart.unit || ''} />
        ) : chart.type === 'bar' ? (
          <BarChart labels={labels} data={primaryDataset.data} title={chart.title} unit={chart.unit || ''}
            comparisonData={comparisonDataset?.data} comparisonTitle={comparisonDataset?.label} />
        ) : chart.type === 'donut' ? (
          <DonutChart labels={labels} data={primaryDataset.data} title={chart.title}
            valueKind={chart.valueKind} unit={chart.unit} />
        ) : chart.type === 'radar' ? (
          <RadarChart labels={labels} data={primaryDataset.data} title={chart.title}
            comparisonData={comparisonDataset?.data} comparisonTitle={comparisonDataset?.label} />
        ) : chart.type === 'treemap' ? (
          <TreemapChart labels={labels} data={primaryDataset.data} title={chart.title} unit="%" />
        ) : null}
      </div>
    );
  }
  if (seg.type === 'table') {
    return (
      <TableBlock key={idx} headers={seg.content.headers || []} rows={seg.content.rows || []} title={seg.content.title} />
    );
  }
  if (seg.type === 'callout') {
    const c = seg.content;
    return <CalloutBlock key={idx} type={c.type || 'neutral'} items={c.items || []} title={c.title} />;
  }
  if (seg.type === 'section') {
    const s = seg.content;
    return <SectionBlock key={idx} title={s.title || ''} bullets={s.bullets || []} />;
  }
  if (seg.type === 'html') {
    return <HtmlArtifact key={idx} html={seg.content} />;
  }
  return null;
};

// ─── Rich chart renderer (rich_builder format: series[].values) ───────────────
const renderRichChart = (chart: any, keyVal: number): React.ReactNode => {
  if (!chart) return null;
  const series = chart.series || [];
  const xLabels = chart.x_labels || [];
  // Allow donut/treemap with no x_labels (use labels from series or skip)
  const kind = (chart.kind || 'bar').toLowerCase();
  const hasData = series.length > 0 && (series[0].values || []).length > 0;
  if (!hasData) return null;

  const primaryVals: number[] = (series[0]?.values || []).map((v: any) => v ?? 0);
  const secondaryVals: number[] | undefined = series[1]?.values?.map((v: any) => v ?? 0);
  const secondaryName: string | undefined = series[1]?.name;
  const unit = chart.y_unit || series[0]?.unit || '';
  const labels = xLabels.length > 0 ? xLabels : primaryVals.map((_: any, i: number) => String(i + 1));

  return (
    <div
      key={keyVal}
      className="glass animate-scale-pop"
      style={{
        padding: '14px 16px',
        margin: '10px 0',
        background: 'rgba(15, 23, 42, 0.45)',
        border: '1px solid rgba(255, 255, 255, 0.05)',
        borderRadius: '8px',
        width: '100%',
      }}
    >
      {kind === 'area' || kind === 'line' || kind === 'multi_line' ? (
        <AreaChart labels={labels} data={primaryVals} title={chart.title} unit={unit} />
      ) : kind === 'bar' || kind === 'multi_bar' ? (
        <BarChart
          labels={labels} data={primaryVals} title={chart.title} unit={unit}
          comparisonData={secondaryVals} comparisonTitle={secondaryName}
        />
      ) : kind === 'donut' ? (
        <DonutChart labels={labels} data={primaryVals} title={chart.title}
          valueKind={chart.valueKind} unit={unit} />
      ) : kind === 'radar' ? (
        <RadarChart
          labels={labels} data={primaryVals} title={chart.title}
          comparisonData={secondaryVals} comparisonTitle={secondaryName}
        />
      ) : kind === 'treemap' ? (
        <TreemapChart labels={labels} data={primaryVals} title={chart.title} unit="%" />
      ) : null}
      {chart.subtitle && (
        <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '6px', textAlign: 'center' }}>
          {chart.subtitle}
        </div>
      )}
    </div>
  );
};

const isMissingDisplayValue = (value: any): boolean => {
  if (value === null || value === undefined) return true;
  if (typeof value === 'number' && !Number.isFinite(value)) return true;
  const text = String(value).trim().toLowerCase();
  return text === '' || text === 'n/a' || text === 'na' || text === 'nan' || text === 'infinity' || text === '-infinity' || text === 'none' || text === 'null' || text === '-' || text === '—';
};

const chartHasData = (chart: any): boolean => {
  return (chart?.series || []).some((series: any) =>
    (series?.values || []).some((value: any) => typeof value === 'number' && Number.isFinite(value))
  );
};

const cleanTable = (table: any): any | null => {
  if (!table || !Array.isArray(table.headers) || !Array.isArray(table.rows)) return null;
  const rows = table.rows.filter((row: any) => {
    const cells = Array.isArray(row) ? row : Object.values(row || {});
    return cells.slice(1).some((cell: any) => !isMissingDisplayValue(cell));
  });
  return rows.length > 0 ? { ...table, rows } : null;
};

// ─── Entity profile card ──────────────────────────────────────────────────────
const renderEntityCard = (entity: any, isSecondary: boolean): React.ReactNode => {
  if (!entity) return null;
  const accent = isSecondary ? 'var(--accent-indigo)' : 'var(--accent-cyan)';
  const borderColor = isSecondary ? 'rgba(129,140,248,0.18)' : 'rgba(56,189,248,0.18)';
  return (
    <div
      className="glass"
      style={{
        flex: 1, minWidth: '160px', maxWidth: '260px',
        padding: '12px 14px',
        background: 'rgba(15, 23, 42, 0.55)',
        border: `1px solid ${borderColor}`,
        borderRadius: '8px',
        display: 'flex', flexDirection: 'column', gap: '3px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px' }}>
        <span style={{ fontSize: '11px', fontWeight: 800, color: accent, letterSpacing: '0.06em' }}>
          {entity.ticker || entity.label}
        </span>
        {entity.exchange && (
          <span style={{
            fontSize: '8.5px', color: 'var(--text-muted)',
            background: 'rgba(255,255,255,0.05)', padding: '1px 5px', borderRadius: '3px',
          }}>
            {entity.exchange}
          </span>
        )}
      </div>
      <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)', lineHeight: 1.25 }}>
        {entity.label}
      </div>
      {entity.current_price != null && (
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '5px', marginTop: '3px' }}>
          <span style={{ fontSize: '16px', fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
            ₹{Number(entity.current_price).toLocaleString('en-IN')}
          </span>
          {entity.change_pct != null && (
            <span style={{
              fontSize: '11px', fontWeight: 600,
              color: entity.change_pct >= 0 ? 'var(--profit)' : 'var(--loss)',
            }}>
              {entity.change_pct >= 0 ? '+' : ''}{Number(entity.change_pct).toFixed(2)}%
            </span>
          )}
        </div>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '4px' }}>
        {entity.sector && (
          <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{entity.sector}</span>
        )}
        {entity.market_cap != null && (
          <span style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
            ₹{(entity.currency === 'INR' && Number(entity.market_cap) < 10000000
              ? Number(entity.market_cap)
              : Number(entity.market_cap) / 1e7
            ).toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr
          </span>
        )}
        {entity.pe != null && (
          <span style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
            P/E {Number(entity.pe).toFixed(1)}x
          </span>
        )}
      </div>
    </div>
  );
};

// ─── Inline comparison table ──────────────────────────────────────────────────
const renderComparisonTable = (rows: any[]): React.ReactNode => {
  if (!rows || rows.length === 0) return null;
  return (
    <div
      className="glass"
      style={{ margin: '10px 0', overflow: 'hidden', background: 'rgba(15, 23, 42, 0.45)' }}
    >
      <div style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' as any }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', textAlign: 'left', minWidth: '360px' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', backgroundColor: 'rgba(3,7,18,0.3)' }}>
              <th style={{ padding: '9px 12px', color: 'var(--text-secondary)', fontWeight: 600 }}>Metric</th>
              <th style={{ padding: '9px 12px', fontWeight: 700, color: 'var(--accent-cyan)' }}>Primary</th>
              <th style={{ padding: '9px 12px', fontWeight: 700, color: 'var(--accent-indigo)' }}>Secondary</th>
              <th style={{ padding: '9px 12px', color: 'var(--text-secondary)', fontWeight: 600 }}>Edge</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row: any, i: number) => (
              <tr
                key={i}
                style={{ borderBottom: i < rows.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none' }}
              >
                <td style={{ padding: '9px 12px', color: 'var(--text-primary)', fontWeight: 600 }}>{row.metric}</td>
                <td style={{ padding: '9px 12px', fontFamily: 'var(--font-mono)', fontSize: '11.5px' }}>{row.primary_value}</td>
                <td style={{ padding: '9px 12px', fontFamily: 'var(--font-mono)', fontSize: '11.5px' }}>{row.secondary_value}</td>
                <td style={{ padding: '9px 12px' }}>
                  {row.winner === 'primary' ? (
                    <span className="badge badge-success" style={{ fontSize: '9px', padding: '2px 5px' }}>Primary</span>
                  ) : row.winner === 'secondary' ? (
                    <span className="badge badge-info" style={{ fontSize: '9px', padding: '2px 5px' }}>Secondary</span>
                  ) : (
                    <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ─── Inline strengths & risks block ──────────────────────────────────────────
const renderStrengthsRisksBlock = (blocks: any[]): React.ReactNode => {
  if (!blocks || blocks.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', margin: '10px 0' }}>
      {blocks.map((block: any, i: number) => (
        <div key={i} className="glass" style={{ padding: '12px 16px', background: 'rgba(15, 23, 42, 0.45)' }}>
          {block.entity_label && (
            <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '8px', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
              {block.entity_label}
            </div>
          )}
          <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
            {(block.strengths || []).length > 0 && (
              <div style={{ flex: 1, minWidth: '130px' }}>
                <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--profit)', marginBottom: '5px' }}>✓ Strengths</div>
                {block.strengths.slice(0, 4).map((s: string, si: number) => (
                  <div key={si} style={{ fontSize: '11.5px', color: 'var(--text-secondary)', lineHeight: 1.45, padding: '2px 0' }}>· {s}</div>
                ))}
              </div>
            )}
            {(block.risks || []).length > 0 && (
              <div style={{ flex: 1, minWidth: '130px' }}>
                <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--loss)', marginBottom: '5px' }}>⚠ Risks</div>
                {block.risks.slice(0, 4).map((r: string, ri: number) => (
                  <div key={ri} style={{ fontSize: '11.5px', color: 'var(--text-secondary)', lineHeight: 1.45, padding: '2px 0' }}>· {r}</div>
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
};

// ─── Rich table renderer (tables[] from portfolio/tabular data) ───────────────
const renderRichTable = (table: any, keyVal: number): React.ReactNode => {
  const cleaned = cleanTable(table);
  if (!cleaned) return null;
  return <TableBlock key={keyVal} headers={cleaned.headers} rows={cleaned.rows} title={cleaned.title} />;
};

// ─── Detect if richData has meaningful visual content ────────────────────────
const hasRichContent = (richData: any): boolean => {
  if (!richData) return false;
  return (
    (richData.metric_cards || []).some((card: any) => !isMissingDisplayValue(card?.value)) ||
    (richData.charts || []).some(chartHasData) ||
    (richData.comparison_rows || []).some((row: any) => !isMissingDisplayValue(row?.primary_value) && !isMissingDisplayValue(row?.secondary_value)) ||
    (richData.strengths_risks || []).length > 0 ||
    (richData.tables || []).some((table: any) => cleanTable(table))
  );
};

// ─── Unified inline content renderer ─────────────────────────────────────────
// Interleaves richData visuals with text sections (Claude-like inline layout).
// Layout: entity cards → metric cards → [section → visual → section → visual…] → conclusion text
const renderUnifiedContent = (text: string, richData: any): React.ReactNode => {
  const cleanText = text.replace(/^\[NEW_PROMPT_V2_ACTIVE\]\s*/, '');
  const result: React.ReactNode[] = [];
  let rk = 0;

  // ── 1. Entity Profile Cards (always at the very top) ──
  const primaryEnt = richData?.primary_entity;
  const secondaryEnt = richData?.secondary_entity;
  if (primaryEnt || secondaryEnt) {
    result.push(
      <div
        key={rk++}
        style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginBottom: '12px' }}
      >
        {primaryEnt && renderEntityCard(primaryEnt, false)}
        {secondaryEnt && renderEntityCard(secondaryEnt, true)}
      </div>
    );
  }

  // ── 2. Metric Cards Grid (right below entity) ──
  const metricCards = (richData?.metric_cards || [])
    .filter((card: any) => !isMissingDisplayValue(card?.value))
    .slice(0, 6);
  if (metricCards.length > 0) {
    result.push(
      <div
        key={rk++}
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
          gap: '8px',
          marginBottom: '14px',
        }}
      >
        {metricCards.map((mc: any, i: number) => (
          <MetricCard
            key={i}
            label={mc.label}
            value={mc.value}
            subValue={mc.sub_value}
            change={mc.change}
            changeType={mc.change_type as any}
            tooltip={mc.tooltip}
          />
        ))}
      </div>
    );
  }

  // ── 3. Split text into sections at ## heading boundaries ──
  const lines = cleanText.split('\n');
  const sections: string[] = [];
  let currentLines: string[] = [];
  for (const line of lines) {
    if (line.match(/^##\s+/) && currentLines.length > 0) {
      const trimmed = currentLines.join('\n').trimEnd();
      if (trimmed) sections.push(trimmed);
      currentLines = [line];
    } else {
      currentLines.push(line);
    }
  }
  const lastSection = currentLines.join('\n').trimEnd();
  if (lastSection) sections.push(lastSection);

  // If no heading breaks, treat the whole text as one section
  if (sections.length === 0) sections.push(cleanText);

  // ── 4. Build visual queue: charts → tables → comparison → strengths/risks ──
  const visualQueue: Array<() => React.ReactNode> = [];

  (richData?.charts || []).filter(chartHasData).slice(0, 3).forEach((chart: any, i: number) => {
    visualQueue.push(() => renderRichChart(chart, i));
  });
  (richData?.tables || []).map(cleanTable).filter(Boolean).slice(0, 2).forEach((table: any, i: number) => {
    visualQueue.push(() => renderRichTable(table, i));
  });
  const comparisonRows = (richData?.comparison_rows || [])
    .filter((row: any) => !isMissingDisplayValue(row?.primary_value) && !isMissingDisplayValue(row?.secondary_value));
  if (comparisonRows.length > 0) {
    visualQueue.push(() => renderComparisonTable(comparisonRows));
  }
  if ((richData?.strengths_risks || []).length > 0) {
    visualQueue.push(() => renderStrengthsRisksBlock(richData.strengths_risks));
  }

  // ── 5. Interleave: section text → visual → section text → visual… → conclusion ──
  // Strategy:
  // - If multiple sections: insert visuals between sections (except after the last one).
  // - If only 1 section: render text first, then ALL visuals after it.
  // - Always drain remaining visuals after all sections are rendered.
  const lastSectionIdx = sections.length - 1;

  sections.forEach((section, i) => {
    // Render the text section
    const segs = parseMessageContent(section);
    const grouped = groupSegments(segs);
    result.push(
      <div key={rk++} style={{ wordBreak: 'break-word', overflowWrap: 'anywhere' }}>
        {grouped.map((seg, si) => renderSegment(seg, si))}
      </div>
    );

    // Between sections (not after the very last one), insert visuals
    if (sections.length > 1 && i < lastSectionIdx) {
      if (visualQueue.length > 0) {
        const fn = visualQueue.shift()!;
        const node = fn();
        if (node) result.push(<React.Fragment key={rk++}>{node}</React.Fragment>);
      }
    }
  });

  // ── 6. News headlines (compact footer, no visuals) ──
  const headlines = (richData?.headlines || []).slice(0, 3);
  if (headlines.length > 0) {
    result.push(
      <div
        key={rk++}
        style={{
          borderTop: '1px solid rgba(255,255,255,0.05)',
          paddingTop: '8px',
          marginTop: '10px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
        }}
      >
        <div style={{ fontSize: '9.5px', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '3px' }}>
          Sources
        </div>
        {headlines.map((h: any, i: number) => (
          <div key={i} style={{ fontSize: '10.5px', color: 'var(--text-secondary)', display: 'flex', gap: '6px', alignItems: 'flex-start' }}>
            <span style={{ color: 'var(--text-muted)', flexShrink: 0 }}>·</span>
            <span>
              {h.url ? (
                <a href={h.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent-cyan)', textDecoration: 'none' }}>
                  {h.title}
                </a>
              ) : h.title}
              {h.source && <span style={{ color: 'var(--text-muted)', marginLeft: '4px' }}>— {h.source}</span>}
            </span>
          </div>
        ))}
      </div>
    );
  }

  return <>{result}</>;
};

// ─── Component ───────────────────────────────────────────────────────────────
interface MessageBubbleProps {
  sender: 'user' | 'ai';
  text: string;
  richData?: any;
  depth?: 'chat' | 'standard' | 'deep';
  elapsedMs?: number;
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({
  sender,
  text,
  richData,
  depth,
  elapsedMs,
}) => {
  const isUser = sender === 'user';

  return (
    <div
      className="animate-slide-in-up"
      style={{
        display: 'flex',
        gap: '12px',
        width: '100%',
        maxWidth: '100%',
        alignSelf: 'center',
        flexDirection: isUser ? 'row-reverse' : 'row',
        marginBottom: '8px',
      }}
    >
      {/* Avatar */}
      <div
        style={{
          width: '32px',
          height: '32px',
          borderRadius: '50%',
          backgroundColor: isUser ? 'var(--neutral-dim)' : 'rgba(129, 140, 248, 0.1)',
          border: '1px solid',
          borderColor: isUser ? 'var(--accent-cyan)' : 'var(--accent-indigo)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: isUser ? 'var(--accent-cyan)' : 'var(--accent-indigo)',
          flexShrink: 0,
          boxShadow: isUser
            ? '0 0 10px rgba(56, 189, 248, 0.1)'
            : '0 0 10px rgba(129, 140, 248, 0.1)',
        }}
      >
        {isUser ? <User size={14} /> : <Brain size={14} />}
      </div>

      {/* Content area */}
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
          flex: 1,
          minWidth: 0,
          maxWidth: '100%',
        }}
      >
        {/* Name + metadata row */}
        {!isUser && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              fontSize: '11px',
              color: 'var(--text-secondary)',
            }}
          >
            <span
              style={{
                fontWeight: 700,
                color: 'var(--text-primary)',
                letterSpacing: '0.05em',
                whiteSpace: 'nowrap',
                flexShrink: 0,
              }}
            >
              Arthik
            </span>
            {depth && (
              <span
                className="badge badge-info"
                style={{
                  fontSize: '9px',
                  padding: '1px 5px',
                  color: 'var(--accent-indigo)',
                  borderColor: 'rgba(129, 140, 248, 0.2)',
                  background: 'rgba(129, 140, 248, 0.1)',
                  whiteSpace: 'nowrap',
                  flexShrink: 0,
                }}
              >
                {depth.toUpperCase()}
              </span>
            )}
            {elapsedMs && (
              <span style={{ whiteSpace: 'nowrap', flexShrink: 0 }}>
                • done in {(elapsedMs / 1000).toFixed(2)}s
              </span>
            )}
          </div>
        )}

        {/* Message body — single unified bubble */}
        <div
          style={{
            background: isUser ? 'rgba(56, 189, 248, 0.06)' : 'rgba(15, 23, 42, 0.75)',
            border: '1px solid',
            borderColor: isUser ? 'rgba(56, 189, 248, 0.25)' : 'rgba(255, 255, 255, 0.10)',
            borderRadius: '12px',
            padding: '14px 18px',
            fontSize: '13.5px',
            color: 'var(--text-primary)',
            lineHeight: 1.55,
            boxShadow: isUser
              ? '0 4px 20px rgba(0, 0, 0, 0.15)'
              : '0 4px 24px rgba(0, 0, 0, 0.25)',
            wordBreak: 'break-word',
            overflowWrap: 'anywhere',
            minWidth: 0,
          }}
        >
          {!isUser && richData && hasRichContent(richData)
            ? renderUnifiedContent(text, richData)
            : (() => {
                const segments = parseMessageContent(text);
                const grouped = groupSegments(segments);
                return grouped.map((seg, idx) => renderSegment(seg, idx));
              })()}
        </div>
      </div>
    </div>
  );
};

export default MessageBubble;

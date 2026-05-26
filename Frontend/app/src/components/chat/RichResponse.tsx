import React from 'react';
import { AreaChart } from '../charts/AreaChart';
import { BarChart } from '../charts/BarChart';
import { DonutChart } from '../charts/DonutChart';
import { MetricCard } from '../charts/MetricCard';
import { AlertCircle, CheckCircle, ExternalLink, Newspaper, Scale, BarChart2 } from 'lucide-react';

interface RichResponseProps {
  data: {
    mode: string;
    title?: string;
    subtitle?: string;
    primary_entity?: any;
    secondary_entity?: any;
    metric_cards?: any[];
    charts?: any[];
    comparison_rows?: any[];
    strengths_risks?: any[];
    headlines?: any[];
    data_sources?: any[];
    disclaimer?: string;
  };
}

export const RichResponse: React.FC<RichResponseProps> = ({ data }) => {
  if (!data) return null;

  const {
    title,
    subtitle,
    primary_entity,
    metric_cards = [],
    charts = [],
    comparison_rows = [],
    strengths_risks = [],
    headlines = [],
    data_sources = [],
    disclaimer
  } = data;

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: '16px',
      width: '100%',
      backgroundColor: 'transparent'
    }}>
      {/* Header Context */}
      {(title || subtitle) && (
        <div style={{
          borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
          paddingBottom: '8px',
          marginBottom: '4px'
        }}>
          {title && <h3 style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>{title}</h3>}
          {subtitle && <p style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>{subtitle}</p>}
        </div>
      )}

      {/* Entity Profile Panel */}
      {primary_entity && (
        <div className="glass" style={{
          padding: '12px 16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
          background: 'rgba(15, 23, 42, 0.45)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '13.5px', fontWeight: 700, color: 'var(--text-primary)' }}>
              {primary_entity.label} ({primary_entity.ticker})
            </span>
            {primary_entity.current_price && (
              <span style={{ fontSize: '14px', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                ₹{primary_entity.current_price.toLocaleString('en-IN')}
                {primary_entity.change_pct !== undefined && (
                  <span style={{ 
                    fontSize: '11px', 
                    marginLeft: '8px',
                    color: primary_entity.change_pct >= 0 ? 'var(--profit)' : 'var(--loss)'
                  }}>
                    {primary_entity.change_pct >= 0 ? '+' : ''}{primary_entity.change_pct.toFixed(2)}%
                  </span>
                )}
              </span>
            )}
          </div>
          {primary_entity.description && (
            <p style={{ fontSize: '11.5px', color: 'var(--text-secondary)', lineHeight: 1.45 }}>
              {primary_entity.description}
            </p>
          )}
        </div>
      )}

      {/* Metric Cards Grid */}
      {metric_cards.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
          gap: '10px'
        }}>
          {metric_cards.map((card, i) => (
            <MetricCard
              key={i}
              label={card.label}
              value={card.value}
              subValue={card.sub_value}
              change={card.change}
              changeType={card.change_type}
              tooltip={card.tooltip}
            />
          ))}
        </div>
      )}

      {/* Custom Visual Charts */}
      {charts.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr',
          gap: '12px'
        }}>
          {charts.map((chart, i) => {
            const hasLabels = chart.x_labels && chart.x_labels.length > 0;
            const hasSeries = chart.series && chart.series.length > 0;
            if (!hasLabels || !hasSeries) return null;

            const labels = chart.x_labels;
            const primarySeries = chart.series[0];
            const comparisonSeries = chart.series[1];

            return (
              <div key={i} className="glass" style={{
                padding: '16px',
                display: 'flex',
                flexDirection: 'column',
                gap: '10px',
                background: 'rgba(15, 23, 42, 0.45)'
              }}>
                {chart.kind === 'area' || chart.kind === 'line' ? (
                  <AreaChart
                    labels={labels}
                    data={primarySeries.values}
                    title={chart.title}
                    unit={chart.y_unit || 'Cr'}
                  />
                ) : chart.kind === 'bar' || chart.kind === 'multi_bar' ? (
                  <BarChart
                    labels={labels}
                    data={primarySeries.values}
                    title={chart.title}
                    unit={chart.y_unit || 'Cr'}
                    comparisonData={comparisonSeries?.values}
                    comparisonTitle={comparisonSeries?.name}
                  />
                ) : chart.kind === 'donut' ? (
                  <DonutChart
                    labels={labels}
                    data={primarySeries.values}
                    title={chart.title}
                  />
                ) : (
                  <div style={{ color: 'var(--text-secondary)', fontSize: '11px', textAlign: 'center', padding: '16px' }}>
                    <BarChart2 size={20} style={{ marginBottom: '6px' }} />
                    Unsupported chart layout ({chart.kind})
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Peer Comparison Table */}
      {comparison_rows.length > 0 && (
        <div className="glass" style={{ overflow: 'hidden', background: 'rgba(15, 23, 42, 0.45)' }}>
          <table style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontSize: '12px',
            textAlign: 'left'
          }}>
            <thead>
              <tr style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.06)', backgroundColor: 'rgba(3, 7, 18, 0.3)' }}>
                <th style={{ padding: '10px 14px', color: 'var(--text-secondary)', fontWeight: 600 }}>Metric Analysis</th>
                <th style={{ padding: '10px 14px', fontWeight: 700 }}>Primary</th>
                <th style={{ padding: '10px 14px', fontWeight: 700 }}>Secondary</th>
                <th style={{ padding: '10px 14px', color: 'var(--text-secondary)', fontWeight: 600 }}>Winner</th>
              </tr>
            </thead>
            <tbody>
              {comparison_rows.map((row, i) => (
                <tr key={i} style={{
                  borderBottom: i < comparison_rows.length - 1 ? '1px solid rgba(255, 255, 255, 0.04)' : 'none',
                  transition: 'background-color 0.2s ease'
                }}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.02)'}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                >
                  <td style={{ padding: '10px 14px', color: 'var(--text-primary)', fontWeight: 600 }}>{row.metric}</td>
                  <td style={{ padding: '10px 14px', fontFamily: 'var(--font-mono)' }}>{row.primary_value}</td>
                  <td style={{ padding: '10px 14px', fontFamily: 'var(--font-mono)' }}>{row.secondary_value}</td>
                  <td style={{ padding: '10px 14px' }}>
                    {row.winner === 'primary' ? (
                      <span className="badge badge-success" style={{ fontSize: '9px', padding: '2px 6px' }}>Primary</span>
                    ) : row.winner === 'secondary' ? (
                      <span className="badge badge-info" style={{ fontSize: '9px', padding: '2px 6px' }}>Secondary</span>
                    ) : (
                      <span className="badge badge-info" style={{ fontSize: '9px', padding: '2px 6px', opacity: 0.6 }}>Tie</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Strengths & Risks Blocks */}
      {strengths_risks.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {strengths_risks.map((block, i) => (
            <div key={i} className="glass" style={{
              padding: '16px',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
              background: 'rgba(15, 23, 42, 0.45)'
            }}>
              {/* Strengths */}
              {block.strengths && block.strengths.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--profit)', fontSize: '12.5px', fontWeight: 700 }}>
                    <CheckCircle size={14} />
                    Key Growth Drivers & Strengths
                  </div>
                  <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '5px' }}>
                    {block.strengths.map((str: string, j: number) => (
                      <li key={j} style={{ fontSize: '11.5px', color: 'var(--text-secondary)', display: 'flex', gap: '6px', alignItems: 'flex-start' }}>
                        <span style={{ color: 'var(--profit)', fontWeight: 'bold' }}>•</span>
                        <span>{str}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Risks */}
              {block.risks && block.risks.length > 0 && (
                <div style={{ 
                  display: 'flex', 
                  flexDirection: 'column', 
                  gap: '8px', 
                  borderTop: '1px solid rgba(255, 255, 255, 0.05)', 
                  paddingTop: '12px',
                  marginTop: block.strengths?.length ? '4px' : '0'
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--loss)', fontSize: '12.5px', fontWeight: 700 }}>
                    <AlertCircle size={14} />
                    Key Risk Factors & Red Flags
                  </div>
                  <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '5px' }}>
                    {block.risks.map((risk: string, j: number) => (
                      <li key={j} style={{ fontSize: '11.5px', color: 'var(--text-secondary)', display: 'flex', gap: '6px', alignItems: 'flex-start' }}>
                        <span style={{ color: 'var(--loss)', fontWeight: 'bold' }}>•</span>
                        <span>{risk}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Headlines News Section */}
      {headlines.length > 0 && (
        <div className="glass" style={{
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '10px',
          background: 'rgba(15, 23, 42, 0.45)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-primary)', fontSize: '13px', fontWeight: 700 }}>
            <Newspaper size={14} color="var(--accent-indigo)" />
            Recent Market Sentiment & News
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {headlines.map((news, i) => (
              <a
                key={i}
                href={news.url || '#'}
                target="_blank"
                rel="noreferrer"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '4px',
                  padding: '8px 12px',
                  background: 'rgba(3, 7, 18, 0.3)',
                  border: '1px solid rgba(255, 255, 255, 0.04)',
                  borderRadius: '8px',
                  textDecoration: 'none',
                  color: 'inherit',
                  transition: 'all 0.2s ease'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--accent-cyan)';
                  e.currentTarget.style.background = 'rgba(56, 189, 248, 0.02)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.04)';
                  e.currentTarget.style.background = 'rgba(3, 7, 18, 0.3)';
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {news.title}
                  <ExternalLink size={10} style={{ opacity: 0.5 }} />
                </div>
                <div style={{ display: 'flex', gap: '8px', fontSize: '10px', color: 'var(--text-secondary)' }}>
                  {news.source && <span>Source: {news.source}</span>}
                  {news.published && <span>• {news.published}</span>}
                </div>
              </a>
            ))}
          </div>
        </div>
      )}

      {/* Sources Citations Footer */}
      {data_sources.length > 0 && (
        <div style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '6px',
          alignItems: 'center',
          fontSize: '11px',
          color: 'var(--text-secondary)',
          paddingLeft: '2px'
        }}>
          <Scale size={11} />
          <span>Verified:</span>
          {data_sources.map((src, i) => (
            <span key={i} className="badge badge-info" style={{ display: 'inline-flex', gap: '4px', alignItems: 'center', fontSize: '9px', padding: '2px 6px' }}>
              {src.label}
            </span>
          ))}
        </div>
      )}

      {/* Disclaimer */}
      {disclaimer && (
        <div style={{
          fontSize: '10px',
          color: 'var(--text-muted)',
          lineHeight: 1.4,
          borderTop: '1px dashed rgba(255, 255, 255, 0.08)',
          paddingTop: '8px',
          marginTop: '4px'
        }}>
          {disclaimer}
        </div>
      )}
    </div>
  );
};

export default RichResponse;

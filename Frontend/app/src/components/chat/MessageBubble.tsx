import React from 'react';
import { User, Brain } from 'lucide-react';
import { RichResponse } from './RichResponse';
import { AreaChart } from '../charts/AreaChart';
import { BarChart } from '../charts/BarChart';
import { DonutChart } from '../charts/DonutChart';
import { MetricCard } from '../charts/MetricCard';

const renderFormattedText = (text: string) => {
  if (!text) return '';
  const parts = text.split(/\*\*([^*]+)\*\*/g);
  return parts.map((part, index) => {
    if (index % 2 === 1) {
      return <strong key={index} style={{ fontWeight: 700, color: 'var(--accent-cyan)' }}>{part}</strong>;
    }
    return part;
  });
};

const parseMessageContent = (text: string) => {
  if (!text) return [];

  const regex = /```(chart|kpi)\s*([\s\S]*?)\s*```/g;
  const segments: Array<{ type: 'text' | 'chart' | 'kpi'; content: any }> = [];
  
  let lastIndex = 0;
  let match;
  
  while ((match = regex.exec(text)) !== null) {
    const type = match[1] as 'chart' | 'kpi';
    const jsonStr = match[2];
    const index = match.index;
    
    if (index > lastIndex) {
      segments.push({ type: 'text', content: text.substring(lastIndex, index) });
    }
    
    try {
      const parsed = JSON.parse(jsonStr);
      segments.push({ type, content: parsed });
    } catch (e) {
      segments.push({ type: 'text', content: match[0] });
    }
    
    lastIndex = regex.lastIndex;
  }
  
  if (lastIndex < text.length) {
    segments.push({ type: 'text', content: text.substring(lastIndex) });
  }
  
  return segments;
};

const groupSegments = (segments: Array<{ type: 'text' | 'chart' | 'kpi'; content: any }>) => {
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
  if (currentKpis.length > 0) {
    grouped.push({ type: 'kpi_group', content: currentKpis });
  }
  return grouped;
};

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
  elapsedMs
}) => {
  const isUser = sender === 'user';

  return (
    <div className="animate-slide-in-up" style={{
      display: 'flex',
      gap: '12px',
      width: '100%',
      maxWidth: '100%',
      alignSelf: 'center',
      flexDirection: isUser ? 'row-reverse' : 'row',
      marginBottom: '8px'
    }}>
      {/* Avatar Wrapper */}
      <div style={{
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
        boxShadow: isUser ? '0 0 10px rgba(56, 189, 248, 0.1)' : '0 0 10px rgba(129, 140, 248, 0.1)'
      }}>
        {isUser ? <User size={14} /> : <Brain size={14} />}
      </div>

      {/* Bubble Content Area */}
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
        maxWidth: '85%'
      }}>
        {/* Name and Metadata Row */}
        {!isUser && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontSize: '11px',
            color: 'var(--text-secondary)'
          }}>
            <span style={{ fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '0.05em', whiteSpace: 'nowrap', flexShrink: 0 }}>Mark-IT</span>
            {depth && (
              <span className="badge badge-info" style={{ fontSize: '9px', padding: '1px 5px', color: 'var(--accent-indigo)', borderColor: 'rgba(129, 140, 248, 0.2)', background: 'rgba(129, 140, 248, 0.1)', whiteSpace: 'nowrap', flexShrink: 0 }}>
                {depth.toUpperCase()}
              </span>
            )}
            {elapsedMs && (
              <span style={{ whiteSpace: 'nowrap', flexShrink: 0 }}>• done in {(elapsedMs / 1000).toFixed(2)}s</span>
            )}
          </div>
        )}

        {/* Message body */}
        <div style={{
          background: isUser ? 'rgba(56, 189, 248, 0.06)' : 'rgba(15, 23, 42, 0.75)',
          border: '1px solid',
          borderColor: isUser ? 'rgba(56, 189, 248, 0.25)' : 'rgba(255, 255, 255, 0.10)',
          borderRadius: '12px',
          padding: '14px 18px',
          fontSize: '13.5px',
          color: 'var(--text-primary)',
          lineHeight: 1.55,
          boxShadow: isUser ? '0 4px 20px rgba(0, 0, 0, 0.15)' : '0 4px 24px rgba(0, 0, 0, 0.25)'
        }}>
          {(() => {
            const segments = parseMessageContent(text);
            const grouped = groupSegments(segments);
            return grouped.map((seg, idx) => {
              if (seg.type === 'text') {
                return (
                  <div key={idx} style={{ whiteSpace: 'pre-line' }}>
                    {renderFormattedText(seg.content)}
                  </div>
                );
              }
              if (seg.type === 'kpi_group') {
                return (
                  <div key={idx} style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                    gap: '10px',
                    margin: '12px 0',
                    width: '100%'
                  }}>
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
                const hasData = chart.datasets && chart.datasets.length > 0 && chart.datasets[0].data && chart.datasets[0].data.length > 0;
                if (!hasLabels || !hasData) return null;

                const labels = chart.labels;
                const primaryDataset = chart.datasets[0];
                const comparisonDataset = chart.datasets[1];

                return (
                  <div key={idx} className="glass animate-scale-pop" style={{
                    padding: '16px',
                    margin: '12px 0',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '10px',
                    background: 'rgba(15, 23, 42, 0.45)',
                    border: '1px solid rgba(255, 255, 255, 0.05)',
                    borderRadius: '8px',
                    width: '100%'
                  }}>
                    {chart.type === 'area' || chart.type === 'line' ? (
                      <AreaChart
                        labels={labels}
                        data={primaryDataset.data}
                        title={chart.title}
                        unit={chart.unit || ''}
                      />
                    ) : chart.type === 'bar' ? (
                      <BarChart
                        labels={labels}
                        data={primaryDataset.data}
                        title={chart.title}
                        unit={chart.unit || ''}
                        comparisonData={comparisonDataset?.data}
                        comparisonTitle={comparisonDataset?.label}
                      />
                    ) : chart.type === 'donut' ? (
                      <DonutChart
                        labels={labels}
                        data={primaryDataset.data}
                        title={chart.title}
                      />
                    ) : (
                      <div style={{ color: 'var(--text-secondary)', fontSize: '11px', textAlign: 'center', padding: '16px' }}>
                        Unsupported chart layout ({chart.type})
                      </div>
                    )}
                  </div>
                );
              }
              return null;
            });
          })()}
        </div>

        {/* Structured Visual Cards (Rich Renders) */}
        {!isUser && richData && (
          <div className="animate-scale-pop" style={{ marginTop: '4px', width: '100%' }}>
            <RichResponse data={richData} />
          </div>
        )}
      </div>
    </div>
  );
};

export default MessageBubble;

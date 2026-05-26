import React from 'react';
import { ArrowRight, AlertTriangle, Scale, Target } from 'lucide-react';

export interface InsightItem {
  id: string;
  ticker: string;
  type: 'valuation' | 'risk' | 'earnings';
  title: string;
  summary: string;
  timestamp: string;
}

interface RecentInsightsProps {
  insights: InsightItem[];
  onSelectInsight: (insight: InsightItem) => void;
}

export const RecentInsights: React.FC<RecentInsightsProps> = ({ insights = [], onSelectInsight }) => {
  return (
    <div className="glass animate-fade-in-up" style={{
      padding: '20px',
      display: 'flex',
      flexDirection: 'column',
      gap: '16px'
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
        paddingBottom: '10px'
      }}>
        <h3 style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)' }}>Alerts</h3>
        <span className="badge badge-success" style={{ fontSize: '10px' }}>
          Live
        </span>
      </div>

      {/* Insights list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {insights.map((item) => {
          let Icon = Target;
          let badgeClass = 'badge badge-info';
          let iconColor = 'var(--accent-indigo)';
          
          if (item.type === 'risk') {
            Icon = AlertTriangle;
            badgeClass = 'badge badge-danger';
            iconColor = 'var(--loss)';
          }
          if (item.type === 'valuation') {
            Icon = Scale;
            badgeClass = 'badge badge-success';
            iconColor = 'var(--profit)';
          }

          return (
            <div
              className="glass-interactive"
              key={item.id}
              style={{
                background: 'rgba(15, 23, 42, 0.35)',
                border: '1px solid rgba(255, 255, 255, 0.04)',
                borderRadius: '12px',
                padding: '14px 16px',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
                cursor: 'pointer',
                transition: 'all 0.25s cubic-bezier(0.4, 0, 0.2, 1)'
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.3)';
                e.currentTarget.style.background = 'rgba(56, 189, 248, 0.02)';
                e.currentTarget.style.transform = 'translateY(-1px)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.04)';
                e.currentTarget.style.background = 'rgba(15, 23, 42, 0.35)';
                e.currentTarget.style.transform = 'translateY(0)';
              }}
              onClick={() => onSelectInsight(item)}
            >
              {/* Top Row Meta */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Icon size={13} color={iconColor} />
                <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-primary)' }}>
                  {item.ticker}
                </span>
                <span className={badgeClass} style={{ fontSize: '9px', padding: '2px 6px' }}>
                  {item.type.toUpperCase()}
                </span>
                <span style={{ fontSize: '11px', color: 'var(--text-secondary)', marginLeft: 'auto' }}>
                  {item.timestamp}
                </span>
              </div>

              {/* Title & Body */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <h4 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {item.title}
                </h4>
                <p style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                  {item.summary}
                </p>
              </div>

              {/* Bottom Row action */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                fontSize: '11px',
                color: 'var(--accent-cyan)',
                fontWeight: 600,
                marginTop: '4px'
              }}>
                <span>View details</span>
                <ArrowRight size={10} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default RecentInsights;

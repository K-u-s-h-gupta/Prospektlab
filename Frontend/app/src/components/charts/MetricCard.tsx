import React from 'react';

interface MetricCardProps {
  label: string;
  value: string;
  subValue?: string;
  change?: string;
  changeType?: 'positive' | 'negative' | 'neutral';
  tooltip?: string;
  icon?: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  subValue,
  change,
  changeType = 'neutral',
  tooltip
}) => {
  let changeColor = 'var(--text-secondary)';
  if (changeType === 'positive') changeColor = 'var(--profit)';
  if (changeType === 'negative') changeColor = 'var(--loss)';

  return (
    <div 
      className="glass" 
      style={{
        padding: '12px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: '4px',
        position: 'relative',
        overflow: 'hidden',
        transition: 'all 0.25s ease',
        background: 'rgba(15, 23, 42, 0.45)',
        border: '1px solid rgba(255, 255, 255, 0.05)'
      }}
      title={tooltip}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.25)';
        e.currentTarget.style.transform = 'translateY(-1px)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.05)';
        e.currentTarget.style.transform = 'translateY(0)';
      }}
    >
      <div style={{
        fontSize: '10px',
        color: 'var(--text-secondary)',
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        fontWeight: 700
      }}>
        {label}
      </div>
      
      <div style={{
        fontSize: '20px',
        fontWeight: 700,
        fontFamily: "var(--font-mono)",
        color: 'var(--text-primary)',
        lineHeight: 1.1,
        letterSpacing: '-0.3px'
      }}>
        {value}
      </div>

      {(subValue || change) && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          fontSize: '11px',
          marginTop: '2px'
        }}>
          {change && (
            <span style={{ fontWeight: 600, color: changeColor }}>
              {change}
            </span>
          )}
          {subValue && (
            <span style={{
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              color: 'var(--text-secondary)'
            }}>
              {subValue}
            </span>
          )}
        </div>
      )}
    </div>
  );
};

export default MetricCard;

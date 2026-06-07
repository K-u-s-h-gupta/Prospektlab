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
        padding: '14px 16px 15px',
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
        position: 'relative',
        overflow: 'hidden',
        transition: 'all 0.25s ease',
        background: 'linear-gradient(180deg, rgba(11, 18, 32, 0.94), rgba(7, 12, 24, 0.9))',
        border: '1px solid rgba(96, 165, 250, 0.1)',
        boxShadow: '0 18px 42px rgba(0, 0, 0, 0.22)',
      }}
      title={tooltip}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.26)';
        e.currentTarget.style.transform = 'translateY(-2px)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'rgba(96, 165, 250, 0.1)';
        e.currentTarget.style.transform = 'translateY(0)';
      }}
    >
      <div style={{
        position: 'absolute',
        inset: '0 auto auto 0',
        width: '100%',
        height: 2,
        background: 'linear-gradient(90deg, rgba(56, 189, 248, 0.85), rgba(129, 140, 248, 0.55), transparent)',
        opacity: 0.9,
      }} />
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
        fontSize: '22px',
        fontWeight: 800,
        fontFamily: "var(--font-mono)",
        color: 'var(--text-primary)',
        lineHeight: 1.1,
        letterSpacing: '-0.4px'
      }}>
        {value}
      </div>

      {(subValue || change) && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          fontSize: '11px',
          marginTop: '1px'
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

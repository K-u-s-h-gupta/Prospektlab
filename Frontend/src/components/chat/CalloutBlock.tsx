import React from 'react';
import { TrendingUp, AlertCircle, Info } from 'lucide-react';

type CalloutType = 'bull' | 'bear' | 'neutral';

interface CalloutBlockProps {
  type: CalloutType;
  items: string[];
  title?: string;
}

const CONFIG: Record<CalloutType, { borderColor: string; bg: string; icon: React.ReactNode; label: string }> = {
  bull: {
    borderColor: 'var(--profit)',
    bg: 'rgba(10, 180, 100, 0.06)',
    icon: <TrendingUp size={14} color="var(--profit)" />,
    label: 'Strengths & Catalysts'
  },
  bear: {
    borderColor: 'var(--loss)',
    bg: 'rgba(220, 50, 50, 0.06)',
    icon: <AlertCircle size={14} color="var(--loss)" />,
    label: 'Risks & Red Flags'
  },
  neutral: {
    borderColor: 'var(--accent-indigo)',
    bg: 'rgba(129, 140, 248, 0.06)',
    icon: <Info size={14} color="var(--accent-indigo)" />,
    label: 'Key Takeaways'
  }
};

export const CalloutBlock: React.FC<CalloutBlockProps> = ({ type, items, title }) => {
  if (!items.length) return null;
  const cfg = CONFIG[type] || CONFIG.neutral;

  return (
    <div className="animate-scale-pop" style={{
      borderLeft: `4px solid ${cfg.borderColor}`,
      background: cfg.bg,
      borderRadius: '6px',
      padding: '12px 16px',
      margin: '12px 0',
      width: '100%'
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        marginBottom: '8px'
      }}>
        {cfg.icon}
        <span style={{
          fontSize: '12.5px',
          fontWeight: 700,
          color: cfg.borderColor,
          letterSpacing: '0.02em'
        }}>
          {title || cfg.label}
        </span>
      </div>
      <ul style={{
        listStyle: 'none',
        display: 'flex',
        flexDirection: 'column',
        gap: '5px',
        margin: 0,
        padding: 0
      }}>
        {items.map((item, i) => (
          <li key={i} style={{
            fontSize: '12px',
            color: 'var(--text-secondary)',
            display: 'flex',
            gap: '8px',
            alignItems: 'flex-start',
            lineHeight: 1.45
          }}>
            <span style={{
              color: cfg.borderColor,
              fontWeight: 700,
              flexShrink: 0,
              marginTop: '1px'
            }}>•</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
};

export default CalloutBlock;

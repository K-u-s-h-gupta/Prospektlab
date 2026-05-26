import React from 'react';
import { Search, Scale, ShieldAlert, Sparkles } from 'lucide-react';

interface QuickActionsProps {
  onTrigger: (prompt: string, depth?: 'chat' | 'standard' | 'deep') => void;
}

export const QuickActions: React.FC<QuickActionsProps> = ({ onTrigger }) => {
  const actions = [
    {
      label: 'Scan',
      icon: Search,
      prompt: 'Analyze TCS fundamentals and PE valuation.',
      color: 'var(--accent-cyan)',
      depth: 'chat' as const
    },
    {
      label: 'Compare',
      icon: Scale,
      prompt: 'Compare Reliance vs Tata Motors on margins and growth.',
      color: 'var(--accent-indigo)',
      depth: 'standard' as const
    },
    {
      label: 'Deep Scan',
      icon: Sparkles,
      prompt: 'Run full 8-phase deep research loop on Asian Paints.',
      color: 'var(--profit)',
      depth: 'deep' as const
    },
    {
      label: 'Valuation',
      icon: ShieldAlert,
      prompt: 'Calculate intrinsic value for Infosys using a DCF model.',
      color: 'var(--accent-cyan)',
      depth: 'standard' as const
    }
  ];

  return (
    <div className="action-chips-container">
      {actions.map((act, i) => {
        const Icon = act.icon;
        return (
          <button
            key={i}
            className="action-chip"
            onClick={() => onTrigger(act.prompt, act.depth)}
            style={{
              padding: '6px 12px',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              background: 'rgba(15, 23, 42, 0.25)',
              border: '1px solid rgba(255, 255, 255, 0.05)',
              borderRadius: '8px',
              fontSize: '11px',
              color: 'var(--text-secondary)',
              cursor: 'pointer'
            }}
          >
            <Icon size={12} color={act.color} />
            <span>{act.label}</span>
          </button>
        );
      })}
    </div>
  );
};

export default QuickActions;

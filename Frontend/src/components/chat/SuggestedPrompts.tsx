import React from 'react';
import { ArrowUpRight } from 'lucide-react';

interface SuggestedPromptsProps {
  prompts: string[];
  onClick: (prompt: string) => void;
  disabled?: boolean;
}

export const SuggestedPrompts: React.FC<SuggestedPromptsProps> = ({ prompts, onClick, disabled }) => {
  if (prompts.length === 0) return null;

  return (
    <div className="stagger-children" style={{
      display: 'flex',
      flexDirection: 'column',
      gap: '8px',
      width: '100%',
      maxWidth: '100%',
      alignSelf: 'center'
    }}>
      <span style={{
        fontSize: '10px',
        color: 'var(--text-secondary)',
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        fontWeight: 700
      }}>
        Try asking
      </span>

      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '6px'
      }}>
        {prompts.map((prompt, i) => (
          <button
            className="glass-interactive"
            key={i}
            onClick={() => onClick(prompt)}
            disabled={disabled}
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.4)',
              border: '1px solid rgba(255, 255, 255, 0.05)',
              color: 'var(--text-primary)',
              borderRadius: '20px',
              padding: '6px 12px',
              fontSize: '11.5px',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              cursor: disabled ? 'default' : 'pointer',
              transition: 'all 0.2s ease',
              opacity: disabled ? 0.6 : 1,
              transform: 'none'
            }}
            onMouseEnter={(e) => {
              if (!disabled) {
                e.currentTarget.style.borderColor = 'var(--accent-cyan)';
                e.currentTarget.style.backgroundColor = 'rgba(56, 189, 248, 0.02)';
              }
            }}
            onMouseLeave={(e) => {
              if (!disabled) {
                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.05)';
                e.currentTarget.style.backgroundColor = 'rgba(15, 23, 42, 0.4)';
              }
            }}
          >
            <span>{prompt}</span>
            <ArrowUpRight size={11} color="var(--accent-cyan)" />
          </button>
        ))}
      </div>
    </div>
  );
};

export default SuggestedPrompts;

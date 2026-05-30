import React, { useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';

interface SectionBlockProps {
  title: string;
  bullets: string[];
}

export const SectionBlock: React.FC<SectionBlockProps> = ({ title, bullets }) => {
  const [open, setOpen] = useState(true);

  if (!bullets.length && !title) return null;

  return (
    <div className="glass" style={{
      background: 'rgba(15, 23, 42, 0.35)',
      border: '1px solid rgba(255, 255, 255, 0.06)',
      borderRadius: '8px',
      margin: '10px 0',
      overflow: 'hidden',
      width: '100%'
    }}>
      <div
        onClick={() => setOpen(!open)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '10px 14px',
          cursor: 'pointer',
          userSelect: 'none',
          background: 'rgba(3, 7, 18, 0.3)',
          borderBottom: open ? '1px solid rgba(255, 255, 255, 0.05)' : 'none'
        }}
      >
        {open ? <ChevronDown size={14} color="var(--text-secondary)" /> : <ChevronRight size={14} color="var(--text-secondary)" />}
        <span style={{
          fontSize: '12.5px',
          fontWeight: 700,
          color: 'var(--text-primary)'
        }}>
          {title}
        </span>
      </div>
      {open && bullets.length > 0 && (
        <div style={{ padding: '10px 14px 14px 14px' }}>
          <ul style={{
            listStyle: 'none',
            display: 'flex',
            flexDirection: 'column',
            gap: '6px',
            margin: 0,
            padding: 0
          }}>
            {bullets.map((item, i) => (
              <li key={i} style={{
                fontSize: '12px',
                color: 'var(--text-secondary)',
                display: 'flex',
                gap: '8px',
                alignItems: 'flex-start',
                lineHeight: 1.5
              }}>
                <span style={{
                  color: 'var(--accent-cyan)',
                  fontWeight: 700,
                  flexShrink: 0
                }}>•</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default SectionBlock;

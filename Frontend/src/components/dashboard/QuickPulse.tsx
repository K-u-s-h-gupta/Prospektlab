import React from 'react';
import { ArrowUpRight, ArrowDownRight } from 'lucide-react';

interface MarketIndex {
  name: string;
  value: string;
  change: string;
  changePct: number;
  sparkline: number[];
}

export const QuickPulse: React.FC = () => {
  const indices: MarketIndex[] = [
    { name: 'NIFTY 50', value: '22,957.10', change: '+184.20', changePct: 0.81, sparkline: [0.3, 0.45, 0.6, 0.55, 0.9] },
    { name: 'SENSEX', value: '75,418.00', change: '+652.15', changePct: 0.87, sparkline: [0.4, 0.35, 0.65, 0.8, 0.95] },
    { name: 'NIFTY BANK', value: '49,115.50', change: '-128.40', changePct: -0.26, sparkline: [0.7, 0.65, 0.4, 0.5, 0.3] }
  ];

  return (
    <div className="ticker-ribbon animate-fade-in-up">
      {indices.map((idx, i) => {
        const isUp = idx.changePct >= 0;
        return (
          <div 
            key={i} 
            style={{
              padding: '10px 14px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              background: 'rgba(15, 23, 42, 0.25)',
              border: '1px solid rgba(255, 255, 255, 0.04)',
              borderRadius: '8px',
              gap: '12px'
            }}
          >
            {/* Index Label */}
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span style={{ fontSize: '10px', color: 'var(--text-secondary)', fontWeight: 700 }}>
                {idx.name}
              </span>
            </div>

            {/* Value & Change */}
            <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
              <span style={{ fontSize: '13px', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                {idx.value}
              </span>
              <span style={{ 
                fontSize: '10px', 
                fontWeight: 600, 
                color: isUp ? 'var(--profit)' : 'var(--loss)',
                display: 'flex',
                alignItems: 'center',
                gap: '2px'
              }}>
                {isUp ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                {isUp ? '+' : ''}{idx.changePct}%
              </span>
            </div>

            {/* Sparkline (5 columns) */}
            <div style={{
              display: 'flex',
              alignItems: 'flex-end',
              gap: '2px',
              height: '14px'
            }}>
              {idx.sparkline.map((val, idxBar) => (
                <div 
                  key={idxBar}
                  style={{
                    width: '3px',
                    height: `${val * 100}%`,
                    backgroundColor: isUp ? 'var(--profit)' : 'var(--loss)',
                    opacity: 0.3 + (idxBar * 0.15)
                  }}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default QuickPulse;

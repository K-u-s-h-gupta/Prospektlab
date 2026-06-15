import React from 'react';
import { Sparkline } from './Sparkline';

export interface IndexTickerData {
  symbol: string;
  value: string;
  change: string;
  changePct: number;
  sparkData: number[];
}

interface IndexTickerCardProps {
  data: IndexTickerData;
  active?: boolean;
  onClick?: () => void;
}

export const IndexTickerCard: React.FC<IndexTickerCardProps> = ({ data, active, onClick }) => {
  const positive = data.changePct >= 0;

  return (
    <button
      onClick={onClick}
      className="index-ticker-card"
      data-active={active || undefined}
      style={{
        background: active ? 'rgba(56, 189, 248, 0.04)' : 'rgba(15, 23, 42, 0.35)',
        border: '1px solid',
        borderColor: active ? 'rgba(56, 189, 248, 0.25)' : 'var(--border-subtle)',
        borderRadius: 14,
        padding: '14px 16px',
        cursor: onClick ? 'pointer' : 'default',
        textAlign: 'left',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        transition: 'var(--transition)',
        minWidth: 0,
        width: '100%',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <span className="index-ticker-symbol" style={{ fontSize: 12, fontWeight: 700, letterSpacing: '0.02em', color: 'var(--text-primary)' }}>
          {data.symbol}
        </span>
        <span
          className="index-ticker-change-pct"
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: positive ? 'var(--profit)' : 'var(--loss)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {positive ? '+' : ''}
          {data.changePct.toFixed(2)}%
        </span>
      </div>

      <div className="index-ticker-value" style={{ fontSize: 18, fontWeight: 600, fontFamily: 'var(--font-mono)', letterSpacing: '-0.3px', color: 'var(--text-primary)' }}>
        {data.value}
      </div>

      <div className="index-ticker-change" style={{ fontSize: 10.5, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
        {data.change}
      </div>

      <div style={{ marginTop: 4 }}>
        <Sparkline data={data.sparkData} positive={positive} width={220} height={36} />
      </div>
    </button>
  );
};

export default IndexTickerCard;

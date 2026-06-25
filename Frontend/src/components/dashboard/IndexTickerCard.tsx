import React from 'react';
import { Sparkline } from './Sparkline';

export interface IndexTickerData {
  symbol: string;
  value: string;
  change: string;
  changePct: number;
  sparkData: number[];
  liveSource?: string;  // "upstox_ws" | "nse_poll" | "yahoo_poll" | undefined
}

interface IndexTickerCardProps {
  data: IndexTickerData;
  active?: boolean;
  onClick?: () => void;
  /** When true, shows a pulsing LIVE badge */
  isLive?: boolean;
}

export const IndexTickerCard: React.FC<IndexTickerCardProps> = ({ data, active, onClick, isLive }) => {
  const positive = data.changePct >= 0;
  const liveFromWS = isLive || data.liveSource === 'upstox_ws' || data.liveSource === 'nse_poll';

  return (
    <button
      onClick={onClick}
      className={`index-ticker-card glass-interactive ${active ? 'active' : ''}`}
      data-active={active || undefined}
      style={{
        padding: '16px 16px 0',
        cursor: onClick ? 'pointer' : 'default',
        textAlign: 'left',
        display: 'flex',
        flexDirection: 'column',
        minWidth: 0,
        width: '100%',
        position: 'relative',
        borderColor: active ? 'var(--border-active)' : undefined,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', width: '100%', zIndex: 1, position: 'relative' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span className="index-ticker-symbol" style={{ fontSize: 13, fontWeight: 800, letterSpacing: '0.04em', color: 'var(--text-secondary)' }}>
            {data.symbol}
          </span>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span className="index-ticker-value" style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-mono)', letterSpacing: '-0.5px', color: 'var(--text-primary)' }}>
              {data.value}
            </span>
          </div>
          <div className="index-ticker-change" style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginTop: -2 }}>
            {data.change}
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {liveFromWS && (
              <span
                title="Real-time data via Upstox WebSocket"
                style={{
                  fontSize: 9,
                  fontWeight: 800,
                  letterSpacing: '0.08em',
                  color: 'var(--profit)',
                  background: 'var(--profit-dim)',
                  border: '1px solid rgba(52, 211, 153, 0.3)',
                  borderRadius: 4,
                  padding: '2px 6px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                }}
              >
                <span
                  style={{
                    width: 5,
                    height: 5,
                    borderRadius: '50%',
                    background: 'var(--profit)',
                    display: 'inline-block',
                    animation: 'pulse-dot 1.5s ease-in-out infinite',
                  }}
                />
                LIVE
              </span>
            )}
            <span
              className="index-ticker-change-pct"
              style={{
                fontSize: 13,
                fontWeight: 700,
                color: positive ? 'var(--profit)' : 'var(--loss)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              {positive ? '+' : ''}
              {data.changePct.toFixed(2)}%
            </span>
          </div>
        </div>
      </div>

      <div style={{ marginTop: 8, width: '100%', position: 'relative', zIndex: 0, marginLeft: '-16px', marginRight: '-16px' }}>
        <Sparkline data={data.sparkData} positive={positive} width={400} height={45} />
      </div>
    </button>
  );
};

export default IndexTickerCard;

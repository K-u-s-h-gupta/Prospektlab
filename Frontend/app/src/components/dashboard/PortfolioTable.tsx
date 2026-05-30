import React from 'react';
import { ArrowUpRight, Activity } from 'lucide-react';

interface PortfolioItem {
  symbol: string;
  name: string;
  qty: number;
  avgCost: number;
  current: number;
  sector: string;
  assetClass?: string;
}

interface PortfolioTableProps {
  portfolio: PortfolioItem[];
  onSelectStock: (symbol: string, item?: PortfolioItem) => void;
  onAnalyzeStock?: (symbol: string) => void;
}

export const PortfolioTable: React.FC<PortfolioTableProps> = ({ portfolio, onSelectStock, onAnalyzeStock }) => {
  // Calculations
  const computedPortfolio = portfolio.map(item => {
    const costBasis = item.qty * item.avgCost;
    const currentValue = item.qty * item.current;
    const pnl = currentValue - costBasis;
    const pnlPct = (pnl / costBasis) * 100;
    return { ...item, currentValue, pnl, pnlPct };
  });

  const totals = computedPortfolio.reduce((acc, curr) => {
    acc.costBasis += curr.qty * curr.avgCost;
    acc.currentValue += curr.currentValue;
    acc.pnl += curr.pnl;
    return acc;
  }, { costBasis: 0, currentValue: 0, pnl: 0 });

  const totalReturnPct = totals.costBasis > 0 ? (totals.pnl / totals.costBasis) * 100 : 0;

  return (
    <div className="animate-fade-in-up" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Portfolio holdings table container */}
      <div 
        className="glass"
        style={{
          border: '1px solid rgba(255, 255, 255, 0.06)',
          overflow: 'hidden',
          boxShadow: '0 8px 32px rgba(0,0,0,0.2)'
        }}
      >
        <div className="portfolio-table-scroll" style={{ overflowX: 'auto' }}>
          <table className="portfolio-table" style={{ width: '100%', minWidth: 640, borderCollapse: 'collapse', fontSize: '13px', textAlign: 'left' }}>
            <thead>
              <tr className="shimmer-overlay" style={{ 
                background: 'rgba(255, 255, 255, 0.02)', 
                borderBottom: '1px solid rgba(255, 255, 255, 0.08)',
                color: 'var(--text-secondary)',
                fontWeight: 600,
                position: 'relative',
                overflow: 'hidden'
              }}>
                <th style={{ padding: '14px 16px', whiteSpace: 'nowrap' }}>TICKER</th>
                <th style={{ padding: '14px 16px', whiteSpace: 'nowrap' }}>QTY</th>
                <th style={{ padding: '14px 16px', whiteSpace: 'nowrap' }}>AVG PRICE</th>
                <th style={{ padding: '14px 16px', whiteSpace: 'nowrap' }}>CURRENT</th>
                <th style={{ padding: '14px 16px', whiteSpace: 'nowrap' }}>NET VALUE</th>
                <th style={{ padding: '14px 16px', textAlign: 'right', whiteSpace: 'nowrap' }}>P&L</th>
                <th style={{ padding: '14px 16px', textAlign: 'center', whiteSpace: 'nowrap' }}>ACTION</th>
              </tr>
            </thead>
            <tbody>
              {computedPortfolio.map((item) => {
                const isProfit = item.pnl >= 0;
                return (
                  <tr 
                    key={item.symbol} 
                    style={{ 
                      borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
                      color: 'var(--text-primary)',
                      cursor: 'pointer',
                      transition: 'background 0.2s ease'
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.02)'}
                    onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                    onClick={() => onSelectStock(item.symbol, item)}
                  >
                    <td style={{ padding: '14px 16px', maxWidth: 200 }}>
                      <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                        <span className="stock-name-ellipsis" style={{ fontWeight: 700, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', display: 'block' }} title={item.name}>{item.name}</span>
                        <span style={{ fontSize: '10px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>{item.symbol}</span>
                      </div>
                    </td>
                    <td style={{ padding: '14px 16px', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>{item.qty}</td>
                    <td style={{ padding: '14px 16px', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>₹{item.avgCost.toLocaleString('en-IN')}</td>
                    <td style={{ padding: '14px 16px', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>₹{item.current.toLocaleString('en-IN')}</td>
                    <td style={{ padding: '14px 16px', fontFamily: 'var(--font-mono)', fontWeight: 600, whiteSpace: 'nowrap' }}>
                      ₹{item.currentValue.toLocaleString('en-IN')}
                    </td>
                    <td style={{ 
                      padding: '14px 16px', 
                      fontFamily: 'var(--font-mono)', 
                      textAlign: 'right',
                      fontWeight: 600,
                      color: isProfit ? 'var(--profit)' : 'var(--loss)',
                      whiteSpace: 'nowrap'
                    }}>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                        <span>{isProfit ? '+' : ''}₹{item.pnl.toLocaleString('en-IN')}</span>
                        <span style={{ fontSize: '10px', display: 'flex', alignItems: 'center', gap: '2px' }}>
                          <ArrowUpRight size={10} style={{ transform: isProfit ? 'none' : 'rotate(90deg)' }} />
                          {isProfit ? '+' : ''}{item.pnlPct.toFixed(1)}%
                        </span>
                      </div>
                    </td>
                    <td style={{ padding: '14px 16px', textAlign: 'center', whiteSpace: 'nowrap' }} onClick={(e) => { e.stopPropagation(); onAnalyzeStock ? onAnalyzeStock(item.symbol) : onSelectStock(item.symbol, item); }}>
                      <button 
                        style={{ 
                          fontSize: '11px', 
                          padding: '6px 12px', 
                          borderRadius: '6px',
                          background: 'rgba(56, 189, 248, 0.05)',
                          borderColor: 'rgba(56, 189, 248, 0.15)',
                          color: 'var(--accent-cyan)',
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          whiteSpace: 'nowrap'
                        }}
                      >
                        <Activity size={10} />
                        Audit
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Totals Summary Footer */}
        <div 
          style={{ 
            background: 'rgba(255, 255, 255, 0.02)', 
            borderTop: '1px solid rgba(255, 255, 255, 0.08)', 
            padding: '16px 20px', 
            display: 'flex', 
            justifyContent: 'space-between',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: '12px'
          }}
        >
          <div style={{ display: 'flex', gap: '24px' }}>
            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-secondary)', fontWeight: 600 }}>PORTFOLIO NAV</div>
              <div style={{ fontSize: '16px', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                ₹{totals.currentValue.toLocaleString('en-IN')}
              </div>
            </div>
            <div>
              <div style={{ fontSize: '10px', color: 'var(--text-secondary)', fontWeight: 600 }}>TOTAL RETURN</div>
              <div style={{ 
                fontSize: '16px', 
                fontWeight: 700, 
                fontFamily: 'var(--font-mono)',
                color: totals.pnl >= 0 ? 'var(--profit)' : 'var(--loss)'
              }}>
                {totals.pnl >= 0 ? '+' : ''}₹{totals.pnl.toLocaleString('en-IN')} ({totalReturnPct.toFixed(1)}%)
              </div>
            </div>
          </div>
          
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
            Calibrated on {portfolio.length} holding positions
          </div>
        </div>
      </div>
    </div>
  );
};
export default PortfolioTable;

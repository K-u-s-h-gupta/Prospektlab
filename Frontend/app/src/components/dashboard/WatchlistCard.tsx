import React from 'react';
import { ArrowUpRight, ArrowDownRight, MessageSquare, Plus, X } from 'lucide-react';

export interface WatchlistStock {
  symbol: string;
  name: string;
  price: string;
  change: string;
  changePct: number;
}

interface WatchlistCardProps {
  stocks: WatchlistStock[];
  onSelectStock: (symbol: string) => void;
  onAddStock?: (symbol: string) => void;
  onRemoveStock?: (symbol: string) => void;
}

export const WatchlistCard: React.FC<WatchlistCardProps> = ({
  stocks = [],
  onSelectStock,
  onAddStock,
  onRemoveStock
}) => {
  const [newSymbol, setNewSymbol] = React.useState('');

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSymbol.trim() || !onAddStock) return;
    onAddStock(newSymbol.trim().toUpperCase());
    setNewSymbol('');
  };

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: '16px'
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
        paddingBottom: '10px'
      }}>
        <h3 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>My Smart Watchlist</h3>
        <span className="badge badge-info" style={{ fontSize: '10px' }}>
          {stocks.length} tracked
        </span>
      </div>

      {/* Add new stock form */}
      {onAddStock && (
        <form onSubmit={handleAdd} style={{ display: 'flex', gap: '8px' }}>
          <input
            type="text"
            placeholder="Add ticker (e.g. RELIANCE, TCS)"
            value={newSymbol}
            onChange={(e) => setNewSymbol(e.target.value)}
            style={{
              flex: 1,
              fontSize: '12px',
              padding: '8px 12px',
              background: 'rgba(15, 23, 42, 0.4)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '8px',
              color: 'var(--text-primary)'
            }}
          />
          <button type="submit" style={{
            padding: '8px 12px',
            background: 'rgba(56, 189, 248, 0.08)',
            border: '1px solid rgba(56, 189, 248, 0.2)',
            borderRadius: '8px',
            color: 'var(--accent-cyan)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer'
          }}>
            <Plus size={14} />
          </button>
        </form>
      )}

      {/* Stocks rows list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {stocks.length === 0 ? (
          <div style={{
            fontSize: '12px',
            color: 'var(--text-secondary)',
            textAlign: 'center',
            padding: '24px',
            background: 'rgba(255, 255, 255, 0.01)',
            border: '1px dashed rgba(255, 255, 255, 0.06)',
            borderRadius: '8px'
          }}>
            Watchlist empty. Add some tickers above to start tracking.
          </div>
        ) : (
          stocks.map((stock) => {
            const isUp = stock.changePct >= 0;
            return (
              <div
                key={stock.symbol}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  padding: '10px 12px',
                  background: 'rgba(15, 23, 42, 0.35)',
                  border: '1px solid rgba(255, 255, 255, 0.04)',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  transition: 'all 0.2s ease'
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.25)';
                  e.currentTarget.style.background = 'rgba(56, 189, 248, 0.03)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.04)';
                  e.currentTarget.style.background = 'rgba(15, 23, 42, 0.35)';
                }}
                onClick={() => onSelectStock(stock.symbol)}
              >
                {/* Meta details */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                  <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)' }}>
                    {stock.symbol}
                  </span>
                  <span style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
                    {stock.name}
                  </span>
                </div>

                {/* Price indicators */}
                <div style={{
                  marginLeft: 'auto',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'flex-end',
                  gap: '2px',
                  marginRight: '16px'
                }}>
                  <span style={{ fontSize: '13px', fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
                    ₹{stock.price}
                  </span>
                  <span style={{
                    fontSize: '10px',
                    fontWeight: 600,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '2px',
                    color: isUp ? 'var(--profit)' : 'var(--loss)'
                  }}>
                    {isUp ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                    {stock.change} ({isUp ? '+' : ''}{stock.changePct}%)
                  </span>
                </div>

                {/* Quick actions row */}
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelectStock(stock.symbol);
                    }}
                    style={{
                      background: 'transparent',
                      border: 'none',
                      padding: '4px',
                      color: 'var(--accent-cyan)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      cursor: 'pointer'
                    }}
                    title="Ask Mark"
                  >
                    <MessageSquare size={12} />
                  </button>

                  {onRemoveStock && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemoveStock(stock.symbol);
                      }}
                      style={{
                        background: 'transparent',
                        border: 'none',
                        padding: '4px',
                        color: 'var(--loss)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        opacity: 0.6,
                        cursor: 'pointer'
                      }}
                      title="Remove from watchlist"
                    >
                      <X size={12} />
                    </button>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

export default WatchlistCard;

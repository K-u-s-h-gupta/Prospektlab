import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Logo } from '../components/layout/Logo';
import { ArrowLeft, ArrowRight, CheckCircle2 } from 'lucide-react';
import { INDIAN_STOCKS, POPULAR_MUTUAL_FUNDS } from '../data/indianStocks';
import { trackEvent } from '../telemetry';
import { useAuth } from '../context/AuthContext';

const LEGACY_DEFAULT_WATCHLIST = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'TATAMOTORS', 'ASIANPAINT', 'ZOMATO', 'ITC'];

const isLegacyDefaultWatchlist = (symbols: string[]) => {
  if (symbols.length !== LEGACY_DEFAULT_WATCHLIST.length) return false;
  return LEGACY_DEFAULT_WATCHLIST.every((symbol) => symbols.includes(symbol));
};

export const WatchlistStep: React.FC = () => {
  const navigate = useNavigate();
  const { setOnboarded, user } = useAuth();
  const watchlistStorageKey = user?.email
    ? `prospektlab_watchlist:${user.email.toLowerCase()}`
    : 'prospektlab_watchlist';

  useEffect(() => {
    const root = document.getElementById('root');
    const prevBodyOverflow = document.body.style.overflowY;
    const prevRootOverflow = root ? root.style.overflowY : '';
    document.body.style.overflowY = 'auto';
    if (root) root.style.overflowY = 'auto';
    return () => {
      document.body.style.overflowY = prevBodyOverflow;
      if (root) root.style.overflowY = prevRootOverflow;
    };
  }, []);

  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [inputVal, setInputVal] = useState('');
  const [suggestions, setSuggestions] = useState<Array<{ symbol: string; name: string; type: 'Stock' | 'Mutual Fund' }>>([]);
  const [isCompleting, setIsCompleting] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const saved = localStorage.getItem(watchlistStorageKey);
    try {
      const parsed = saved ? JSON.parse(saved) : [];
      const normalized = Array.isArray(parsed)
        ? Array.from(
            new Set(
              parsed
                .map((item) => String(item || '').split('.')[0].toUpperCase().trim())
                .filter((item) => item.length > 0)
            )
          )
        : [];
      if (isLegacyDefaultWatchlist(normalized)) {
        localStorage.removeItem(watchlistStorageKey);
        setWatchlist([]);
      } else {
        setWatchlist(normalized);
      }
    } catch {
      setWatchlist([]);
    }
  }, [watchlistStorageKey]);

  useEffect(() => {
    if (!inputVal.trim()) {
      setSuggestions([]);
      return;
    }
    const query = inputVal.toLowerCase().trim();
    const matchedStocks = INDIAN_STOCKS.filter(
      s => s.symbol.toLowerCase().includes(query) || s.name.toLowerCase().includes(query)
    ).slice(0, 5).map(s => ({ symbol: s.symbol, name: s.name, type: 'Stock' as const }));
    const matchedMFs = POPULAR_MUTUAL_FUNDS.filter(
      f => f.symbol.toLowerCase().includes(query) || f.name.toLowerCase().includes(query)
    ).slice(0, 5).map(f => ({ symbol: f.symbol, name: f.name, type: 'Mutual Fund' as const }));
    setSuggestions([...matchedStocks, ...matchedMFs]);
  }, [inputVal]);

  const handleAddCustom = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputVal.trim()) return;
    const ticker = inputVal.trim().toUpperCase();
    if (!watchlist.includes(ticker)) {
      setWatchlist([...watchlist, ticker]);
    }
    setInputVal('');
    setSuggestions([]);
  };

  const toggleWatchlistSymbol = (symbol: string) => {
    if (watchlist.includes(symbol)) {
      setWatchlist(watchlist.filter((c) => c !== symbol));
    } else {
      setWatchlist([...watchlist, symbol]);
    }
  };

  const handleComplete = () => {
    setIsCompleting(true);
    const name = localStorage.getItem('prospektlab_username') || '';
    const style = localStorage.getItem('prospektlab_style') || 'Balanced';
    localStorage.setItem(watchlistStorageKey, JSON.stringify(watchlist));
    setOnboarded(true);
    trackEvent('onboarding_completed', {
      name: name.trim() || 'anonymous',
      style,
      watchlist_count: watchlist.length,
      portfolio_count: 0,
      source: 'uploaded',
    });
    setIsCompleting(false);
    navigate('/dashboard');
  };

  return (
    <div className="onboarding-screen animate-fade-in-up">
      <div className="glass onboarding-card" style={{ maxWidth: '640px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', justifyContent: 'center' }}>
          <div style={{ background: 'var(--gradient-brand)', borderRadius: '10px', padding: '6px', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 15px rgba(56, 189, 248, 0.3)' }}>
            <Logo size={20} />
          </div>
          <span style={{ fontSize: '22px', fontWeight: 700, letterSpacing: '-0.5px' }} className="text-gradient">ProspektLab</span>
        </div>

        <div style={{ textAlign: 'center' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-primary)' }}>Build Your Opportunity Radar</h2>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>
            Add the stocks you are watching. You can always change this later in the dashboard.
          </p>
        </div>

        {/* Custom Input Form */}
        <div style={{ position: 'relative' }}>
          <form onSubmit={handleAddCustom} style={{ display: 'flex', gap: '8px' }}>
            <input
              type="text"
              placeholder="Search or add ticker (e.g. TATAMOTORS, HDFCBANK)"
              value={inputVal}
              onChange={(e) => setInputVal(e.target.value)}
              style={{ flex: 1, fontSize: '13px' }}
            />
            <button type="submit" style={{ fontSize: '13px', padding: '0 16px' }}>Add</button>
          </form>

          {suggestions.length > 0 && (
            <div style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              right: 0,
              zIndex: 100,
              marginTop: '6px',
              maxHeight: '220px',
              overflowY: 'auto',
              background: 'rgba(15, 23, 42, 0.95)',
              backdropFilter: 'blur(12px)',
              border: '1px solid rgba(255, 255, 255, 0.08)',
              borderRadius: '10px',
              boxShadow: '0 12px 36px rgba(0, 0, 0, 0.65)'
            }}>
              {suggestions.map((item) => {
                const isAlreadyAdded = watchlist.includes(item.symbol);
                return (
                  <div
                    key={item.symbol}
                    onClick={() => {
                      if (isAlreadyAdded) {
                        setWatchlist(watchlist.filter(w => w !== item.symbol));
                      } else {
                        setWatchlist([...watchlist, item.symbol]);
                      }
                      setInputVal('');
                      setSuggestions([]);
                    }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '10px 14px',
                      cursor: 'pointer',
                      borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
                      transition: 'all 0.15s ease'
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(56, 189, 248, 0.06)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                  >
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', textAlign: 'left', overflow: 'hidden' }}>
                      <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)' }}>{item.symbol}</span>
                      <span style={{ fontSize: '10px', color: 'var(--text-secondary)', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap', maxWidth: '300px' }}>{item.name}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{
                        fontSize: '9px',
                        fontWeight: 600,
                        padding: '1px 6px',
                        borderRadius: '4px',
                        background: item.type === 'Stock' ? 'rgba(56, 189, 248, 0.08)' : 'rgba(129, 140, 248, 0.08)',
                        color: item.type === 'Stock' ? 'var(--accent-cyan)' : 'var(--accent-indigo)',
                        border: `1px solid ${item.type === 'Stock' ? 'rgba(56, 189, 248, 0.15)' : 'rgba(129, 140, 248, 0.15)'}`
                      }}>{item.type}</span>
                      {isAlreadyAdded ? (
                        <span style={{ fontSize: '10px', color: 'var(--loss)', fontWeight: 500 }}>✕ Remove</span>
                      ) : (
                        <span style={{ fontSize: '10px', color: 'var(--profit)', fontWeight: 500 }}>+ Add</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Selected Summary */}
        <div style={{
          fontSize: '12px',
          color: 'var(--text-secondary)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'rgba(3, 7, 18, 0.3)',
          padding: '12px 16px',
          borderRadius: '10px',
          border: '1px solid rgba(255, 255, 255, 0.04)'
        }}>
          <span>Watchlist targets active:</span>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)', fontWeight: 600 }}>{watchlist.length} Assets</span>
        </div>

        {/* Selected chips */}
        {watchlist.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {watchlist.map((ticker) => (
              <span
                key={ticker}
                onClick={() => toggleWatchlistSymbol(ticker)}
                style={{
                  fontSize: '11px',
                  background: 'rgba(56, 189, 248, 0.08)',
                  color: 'var(--accent-cyan)',
                  padding: '4px 10px',
                  borderRadius: '16px',
                  border: '1px solid rgba(56, 189, 248, 0.15)',
                  cursor: 'pointer'
                }}
              >
                {ticker} ✕
              </span>
            ))}
          </div>
        )}

        <div style={{ display: 'flex', gap: '14px', marginTop: '6px' }}>
          <button type="button" onClick={() => navigate('/onboarding/upload')} style={{ flex: 1, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
            <ArrowLeft size={14} /> Back
          </button>
          <button type="button" onClick={handleComplete} disabled={isCompleting} className="primary" style={{ flex: 1, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
            {isCompleting ? <><CheckCircle2 size={14} /> Saving...</> : <>Open Dashboard <ArrowRight size={14} /></>}
          </button>
        </div>
      </div>
    </div>
  );
};

export default WatchlistStep;

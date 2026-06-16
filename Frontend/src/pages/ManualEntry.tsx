import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Logo } from '../components/layout/Logo';
import { ArrowLeft, Plus, Trash2, ArrowRight, Search, X } from 'lucide-react';
import { INDIAN_STOCKS } from '../data/indianStocks';
import { trackEvent } from '../telemetry';
import { MANUAL_PORTFOLIO_KEY } from '../context/AuthContext';

interface ManualRow {
  id: string;
  symbol: string;
  quantity: string;
  avgCost: string;
  datePurchased: string;
}

const POPULAR_TICKERS = ['RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ITC', 'TATAMOTORS', 'BHARTIARTL', 'ZOMATO', 'TITAN', 'TRENT'];

const createEmptyRow = (): ManualRow => ({
  id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
  symbol: '',
  quantity: '',
  avgCost: '',
  datePurchased: '',
});

const resolveHoldingSymbol = (value: string): string | null => {
  const normalized = value.trim().replace(/\s+/g, ' ');
  if (!normalized) return null;

  const normalizedUpper = normalized.toUpperCase().split('.')[0];
  const symbolMatch = INDIAN_STOCKS.find((stock) => stock.symbol.toUpperCase() === normalizedUpper);
  if (symbolMatch) return symbolMatch.symbol;

  const normalizedLower = normalized.toLowerCase();
  const nameMatch = INDIAN_STOCKS.find((stock) => stock.name.trim().toLowerCase() === normalizedLower);
  if (nameMatch) return nameMatch.symbol;

  return null;
};

export const ManualEntry: React.FC = () => {
  const navigate = useNavigate();
  const [rows, setRows] = useState<ManualRow[]>(() => {
    if (typeof window === 'undefined') return [];
    const saved = localStorage.getItem(MANUAL_PORTFOLIO_KEY);
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          return parsed.map((p: any, idx: number) => ({
            id: p.id || `${Date.now()}-${idx}`,
            symbol: p.symbol || '',
            quantity: p.quantity ? String(p.quantity) : '',
            avgCost: p.avg_cost ? String(p.avg_cost) : (p.avgCost ? String(p.avgCost) : ''),
            datePurchased: p.date_purchased || p.datePurchased || '',
          }));
        }
      } catch {
        // ignore
      }
    }
    return [createEmptyRow()];
  });
  const [suggestions, setSuggestions] = useState<Array<{ symbol: string; name: string; type: string }>>([]);
  const [activeRow, setActiveRow] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRefs = useRef<Record<string, HTMLInputElement | null>>({});

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

  const addRow = () => {
    setRows((prev) => [...prev, createEmptyRow()]);
  };

  const removeRow = (id: string) => {
    setRows((prev) => {
      const next = prev.filter((r) => r.id !== id);
      return next.length > 0 ? next : [createEmptyRow()];
    });
    if (activeRow === id) {
      setActiveRow(null);
      setSuggestions([]);
    }
  };

  const updateRow = (id: string, field: keyof ManualRow, value: string) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, [field]: value } : r)));
    setError(null);
    if (field === 'symbol') {
      setActiveRow(id);
      const term = value.trim().toUpperCase();
      if (term.length === 0) {
        setSuggestions([]);
      } else {
        const matches = INDIAN_STOCKS.filter(
          (s) =>
            s.symbol.toUpperCase().includes(term) ||
            s.name.toUpperCase().includes(term)
        ).slice(0, 6);
        setSuggestions(matches.map((s) => ({ symbol: s.symbol, name: s.name, type: 'Stock' })));
      }
    }
  };

  const selectSuggestion = (id: string, symbol: string) => {
    updateRow(id, 'symbol', symbol);
    setSuggestions([]);
    setActiveRow(null);
  };

  const addPopular = (symbol: string) => {
    const existing = rows.find((r) => r.symbol.toUpperCase() === symbol.toUpperCase());
    if (existing) {
      inputRefs.current[existing.id]?.focus();
      return;
    }
    setRows((prev) => [
      ...prev,
      { ...createEmptyRow(), symbol },
    ]);
  };

  const validate = (): boolean => {
    const completeRows = rows.filter((r) => r.symbol.trim() && parseFloat(r.quantity) > 0 && parseFloat(r.avgCost) > 0);
    if (completeRows.length === 0) {
      setError('Add at least one holding with ticker, quantity, and average price.');
      return false;
    }
    const hasUnknownSymbol = completeRows.some((r) => !resolveHoldingSymbol(r.symbol));
    if (hasUnknownSymbol) {
      setError('company name not found try again with proper name/symbol');
      return false;
    }
    setError(null);
    return true;
  };

  const saveToLocalStorage = () => {
    const payload = rows
      .filter((r) => r.symbol.trim() && parseFloat(r.quantity) > 0 && parseFloat(r.avgCost) > 0)
      .map((r) => {
        const symbol = resolveHoldingSymbol(r.symbol);
        if (!symbol) return null;
        const stock = INDIAN_STOCKS.find((item) => item.symbol.toUpperCase() === symbol.toUpperCase());
        return {
          symbol,
          name: stock?.name || symbol,
          quantity: parseFloat(r.quantity),
          avg_cost: parseFloat(r.avgCost),
          date_purchased: r.datePurchased || '',
        };
      })
      .filter((row): row is { symbol: string; name: string; quantity: number; avg_cost: number; date_purchased: string } => Boolean(row));
    localStorage.setItem(MANUAL_PORTFOLIO_KEY, JSON.stringify(payload));
    return payload;
  };

  const handleGoToDashboard = () => {
    if (!validate()) return;
    const payload = saveToLocalStorage();
    trackEvent('manual_entry_completed', {
      position_count: payload.length,
      style: localStorage.getItem('prospektlab_style') || 'Balanced',
    });
    navigate('/dashboard');
  };

  const totalRows = rows.length;
  const validRows = rows.filter((r) => r.symbol.trim() && parseFloat(r.quantity) > 0 && parseFloat(r.avgCost) > 0).length;

  return (
    <div className="onboarding-screen animate-fade-in-up">
      <div className="glass onboarding-card" style={{ maxWidth: '720px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', justifyContent: 'center' }}>
          <div style={{ background: 'var(--gradient-brand)', borderRadius: '10px', padding: '6px', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 15px rgba(56, 189, 248, 0.3)' }}>
            <Logo size={20} />
          </div>
          <span style={{ fontSize: '22px', fontWeight: 700, letterSpacing: '-0.5px' }} className="text-gradient">ProspektLab</span>
        </div>

        <div style={{ textAlign: 'center' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-primary)' }}>Enter your holdings</h2>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>
            Type the stocks or mutual funds you own. Date of purchase is optional. No login required yet.
          </p>
        </div>

        {error && (
          <div style={{
            background: 'rgba(251, 113, 133, 0.08)',
            border: '1px solid rgba(251, 113, 133, 0.2)',
            color: 'var(--loss)',
            padding: '12px 14px',
            borderRadius: '10px',
            fontSize: '13px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <X size={16} /> {error}
          </div>
        )}

        {/* Popular chips */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>Quick add</span>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {POPULAR_TICKERS.map((ticker) => (
              <button
                key={ticker}
                type="button"
                onClick={() => addPopular(ticker)}
                style={{
                  fontSize: '12px',
                  padding: '6px 12px',
                  borderRadius: '20px',
                  border: '1px solid rgba(255,255,255,0.08)',
                  background: 'rgba(255,255,255,0.02)',
                  color: 'var(--text-secondary)',
                  cursor: 'pointer'
                }}
              >
                + {ticker}
              </button>
            ))}
          </div>
        </div>

        {/* Header row — hidden on mobile (fields stack with their own placeholders) */}
        <div className="manual-entry-head" style={{
          fontSize: '10px',
          color: 'var(--text-secondary)',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          fontWeight: 600,
          padding: '0 8px'
        }}>
          <span>Ticker</span>
          <span>Qty</span>
          <span>Avg Price</span>
          <span>Date (opt)</span>
          <span></span>
        </div>

        {/* Input rows — elevated z-index so the ticker suggestion dropdown
            paints above the footer/buttons (sibling sections share z-index:1,
            so without this the later footer would overlap the open menu). */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', position: 'relative', zIndex: 30 }}>
          {rows.map((row) => (
            <div key={row.id} style={{ position: 'relative' }}>
              <div className="manual-entry-grid">
                <div className="me-c-ticker" style={{ position: 'relative' }}>
                  <input
                    ref={(el) => { inputRefs.current[row.id] = el; }}
                    type="text"
                    placeholder="Search ticker or company..."
                    value={row.symbol}
                    onChange={(e) => updateRow(row.id, 'symbol', e.target.value)}
                    onFocus={() => { setActiveRow(row.id); if (row.symbol.trim()) updateRow(row.id, 'symbol', row.symbol); }}
                    onBlur={() => setTimeout(() => setSuggestions([]), 150)}
                    style={{ fontSize: '13px', padding: '10px 12px', width: '100%' }}
                  />
                  <Search size={14} style={{ position: 'absolute', right: '10px', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', pointerEvents: 'none' }} />
                  {activeRow === row.id && suggestions.length > 0 && (
                    <div className="manual-entry-suggestion-menu">
                      {suggestions.map((s) => (
                        <div
                          key={s.symbol}
                          onMouseDown={() => selectSuggestion(row.id, s.symbol)}
                          className="manual-entry-suggestion-option"
                          onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(56, 189, 248, 0.06)'; }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                        >
                          <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{s.symbol}</div>
                          <div style={{ color: 'var(--text-secondary)', fontSize: '11px', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>{s.name}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                <input
                  type="number"
                  min="0"
                  step="1"
                  placeholder="Qty"
                  value={row.quantity}
                  onChange={(e) => updateRow(row.id, 'quantity', e.target.value)}
                  className="me-c-qty"
                  style={{ fontSize: '13px', padding: '10px 12px', width: '100%' }}
                />
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  placeholder="Avg ₹"
                  value={row.avgCost}
                  onChange={(e) => updateRow(row.id, 'avgCost', e.target.value)}
                  className="me-c-avg"
                  style={{ fontSize: '13px', padding: '10px 12px', width: '100%' }}
                />
                <input
                  type="date"
                  value={row.datePurchased}
                  onChange={(e) => updateRow(row.id, 'datePurchased', e.target.value)}
                  className="me-c-date"
                  style={{ fontSize: '13px', padding: '10px 12px', width: '100%', colorScheme: 'dark' }}
                />
                <button
                  type="button"
                  onClick={() => removeRow(row.id)}
                  className="me-c-del"
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: 'var(--text-muted)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center'
                  }}
                  title="Remove row"
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
          ))}
        </div>

        <button
          type="button"
          onClick={addRow}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '6px',
            fontSize: '12px',
            padding: '10px',
            borderRadius: '8px',
            border: '1px dashed rgba(255,255,255,0.12)',
            background: 'transparent',
            color: 'var(--text-secondary)',
            cursor: 'pointer'
          }}
        >
          <Plus size={14} /> Add another holding
        </button>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '12px', color: 'var(--text-secondary)' }}>
          <span>{validRows} of {totalRows} rows ready</span>
          <span style={{ color: 'var(--text-muted)' }}>Login required later for AI chat</span>
        </div>

        <div style={{ display: 'flex', gap: '14px' }}>
          <button
            type="button"
            onClick={() => navigate('/get-started')}
            style={{ flex: 1, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
          >
            <ArrowLeft size={14} /> Back
          </button>
          <button
            type="button"
            onClick={handleGoToDashboard}
            className="primary"
            style={{ flex: 2, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
          >
            Go to Dashboard <ArrowRight size={14} />
          </button>
        </div>
      </div>
    </div>
  );
};

export default ManualEntry;

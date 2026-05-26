import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Brain, 
  TrendingUp, 
  ShieldAlert, 
  BadgeInfo, 
  UploadCloud, 
  CheckCircle2, 
  Loader2, 
  Sparkles, 
  ChevronRight, 
  ArrowLeft 
} from 'lucide-react';
import { Logo } from '../components/layout/Logo';

interface PortfolioItem {
  symbol: string;
  name: string;
  qty: number;
  avgCost: number;
  current: number;
  sector: string;
}

const DEMO_PORTFOLIO: PortfolioItem[] = [
  { symbol: "TCS", name: "Tata Consultancy", qty: 15, avgCost: 3450, current: 3842, sector: "IT" },
  { symbol: "RELIANCE", name: "Reliance Industries", qty: 10, avgCost: 2780, current: 2931, sector: "Energy" },
  { symbol: "HDFCBANK", name: "HDFC Bank", qty: 20, avgCost: 1480, current: 1562, sector: "Banking" },
  { symbol: "INFY", name: "Infosys", qty: 25, avgCost: 1380, current: 1452, sector: "IT" },
  { symbol: "ITC", name: "ITC Limited", qty: 50, avgCost: 410, current: 431, sector: "FMCG" },
  { symbol: "ASIANPAINT", name: "Asian Paints", qty: 8, avgCost: 2650, current: 2810, sector: "Consumer" }
];

export const Onboarding: React.FC = () => {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);

  // New: Name capture + improved state
  const [name, setName] = useState('');
  
  // Style and watchlist state
  const [style, setStyle] = useState<'Conservative' | 'Balanced' | 'Growth'>('Balanced');
  const [watchlist, setWatchlist] = useState<string[]>(['RELIANCE', 'TCS', 'INFY']);
  const [inputVal, setInputVal] = useState('');

  // Portfolio statement upload states
  const [portfolio, setPortfolio] = useState<PortfolioItem[]>([]);
  const [isParsing, setIsParsing] = useState(false);
  const [parseStep, setParseStep] = useState(0);
  const [dragActive, setDragActive] = useState(false);
  const [uploadedFileName, setUploadedFileName] = useState('');

  const styles = [
    {
      id: 'Conservative' as const,
      title: 'Conservative / Defensive',
      desc: 'Focus on index heavyweights, strong dividends, and clean debt structures (e.g. TCS, HDFCBANK).',
      icon: BadgeInfo,
      color: 'var(--neutral)'
    },
    {
      id: 'Balanced' as const,
      title: 'Balanced Analyst',
      desc: 'Look at value opportunities, PEG ratios, capital allocation, and medium-term sector expansions.',
      icon: Brain,
      color: 'var(--accent-indigo)'
    },
    {
      id: 'Growth' as const,
      title: 'Aggressive / Growth',
      desc: 'Track tech startups, high-beta momentum, potential earnings surprises, and small-cap breakouts.',
      icon: TrendingUp,
      color: 'var(--profit)'
    }
  ];

  const popularChips = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'TATAMOTORS', 'ASIANPAINT', 'ZOMATO', 'ITC'];
  const brokers = ['Zerodha', 'Groww', 'Upstox', 'ICICI Direct'];

  const toggleChip = (chip: string) => {
    if (watchlist.includes(chip)) {
      setWatchlist(watchlist.filter(c => c !== chip));
    } else {
      setWatchlist([...watchlist, chip]);
    }
  };

  const handleAddCustom = (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputVal.trim()) return;
    const ticker = inputVal.trim().toUpperCase();
    if (!watchlist.includes(ticker)) {
      setWatchlist([...watchlist, ticker]);
    }
    setInputVal('');
  };

  // Simulate file parsing steps
  const startParsingSimulation = (fileName: string) => {
    setUploadedFileName(fileName);
    setIsParsing(true);
    setParseStep(0);
  };

  useEffect(() => {
    if (!isParsing) return;
    
    const interval = setInterval(() => {
      setParseStep((prev) => {
        if (prev >= 3) {
          clearInterval(interval);
          setTimeout(() => {
            setIsParsing(false);
            setPortfolio(DEMO_PORTFOLIO);
          }, 600);
          return 4;
        }
        return prev + 1;
      });
    }, 600);

    return () => clearInterval(interval);
  }, [isParsing]);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      startParsingSimulation(file.name);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      startParsingSimulation(file.name);
    }
  };

  const handleUseDemo = () => {
    startParsingSimulation('demostatement_2026.csv');
  };

  const handleComplete = () => {
    // Persist everything including name
    if (name.trim()) {
      localStorage.setItem('prospektlab_username', name.trim());
    }
    localStorage.setItem('prospektlab_style', style);
    localStorage.setItem('prospektlab_watchlist', JSON.stringify(watchlist));
    
    const finalPortfolio = portfolio.length > 0 ? portfolio : DEMO_PORTFOLIO;
    localStorage.setItem('prospektlab_portfolio', JSON.stringify(finalPortfolio));
    localStorage.setItem('prospektlab_onboarded', 'true');
    
    // Clear old onboarding progress
    localStorage.removeItem('prospektlab_onboarding_step');

    const mockConversations = [
      { id: '1', title: `Portfolio Analysis for ${name || 'You'}`, date: 'Just now' }
    ];
    localStorage.setItem('prospektlab_conversations', JSON.stringify(mockConversations));

    navigate('/dashboard');
  };

  return (
    <div style={{
      width: '100vw',
      height: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      position: 'relative',
      overflow: 'hidden',
      padding: '20px'
    }} className="animate-fade-in-up">
      
      {/* Absolute Glass Card Container */}
      <div 
        className="glass"
        style={{
          width: '100%',
          maxWidth: '600px',
          padding: '40px',
          display: 'flex',
          flexDirection: 'column',
          gap: '28px',
          position: 'relative',
          zIndex: 10,
          border: '1px solid rgba(255, 255, 255, 0.08)',
          boxShadow: '0 24px 64px rgba(0, 0, 0, 0.7)'
        }}
      >
        {/* Logo and Brand */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', justifyContent: 'center' }}>
          <div style={{
            background: 'var(--gradient-brand)',
            borderRadius: '10px',
            padding: '6px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 15px rgba(56, 189, 248, 0.3)'
          }}>
            <Brain size={20} color="#0f172a" />
          </div>
          <span style={{ 
            fontSize: '22px', 
            fontWeight: 700, 
            letterSpacing: '-0.5px' 
          }} className="text-gradient">
            ProspektLab
          </span>
        </div>

        {/* Progress Bar steps indicator */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', color: 'var(--text-secondary)', fontWeight: 600 }}>
              <span>STEP {step} OF 3</span>
              <span style={{ color: 'var(--accent-cyan)' }}>
                {step === 1 && 'YOUR NAME + STYLE'}
                {step === 2 && 'YOUR PORTFOLIO'}
                {step === 3 && 'FINAL SETUP'}
              </span>
            </div>
          <div style={{ display: 'flex', gap: '8px', width: '100%' }}>
            {[1, 2, 3, 4].map((s) => (
              <div 
                key={s} 
                style={{ 
                  flex: 1, 
                  height: '4px', 
                  backgroundColor: step >= s ? 'var(--accent-cyan)' : 'rgba(255, 255, 255, 0.08)', 
                  borderRadius: '2px', 
                  boxShadow: step >= s ? '0 0 8px rgba(56, 189, 248, 0.4)' : 'none',
                  transition: 'all 0.3s ease' 
                }} 
              />
            ))}
          </div>
        </div>

        {/* STEP 1: NAME + INVESTING STYLE (restructured to 3 steps) */}
        {step === 1 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div style={{ textAlign: 'center' }}>
              <h2 style={{ fontSize: '22px', fontWeight: 600, color: 'var(--text-primary)' }}>Welcome. What's your name?</h2>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '6px' }}>Mark — your AI market analyst — will address you personally from here on.</p>
            </div>

            {/* Name capture - new and critical */}
            <input
              type="text"
              placeholder="Your first name (e.g. Aryan)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={{ fontSize: '15px', padding: '14px 16px', textAlign: 'center' }}
            />

            <div style={{ textAlign: 'center', marginTop: '8px' }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)' }}>How aggressively do you want to play?</h3>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>This decides which signals Mark surfaces first for you.</p>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {styles.map((item) => {
                const Icon = item.icon;
                const isSelected = style === item.id;
                return (
                  <div
                    key={item.id}
                    onClick={() => setStyle(item.id)}
                    style={{
                      border: '1px solid',
                      borderColor: isSelected ? 'var(--accent-cyan)' : 'rgba(255, 255, 255, 0.06)',
                      background: isSelected ? 'rgba(56, 189, 248, 0.04)' : 'rgba(255, 255, 255, 0.01)',
                      borderRadius: '14px',
                      padding: '18px 20px',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '18px',
                      boxShadow: isSelected ? '0 0 15px rgba(56, 189, 248, 0.05)' : 'none',
                      transition: 'var(--transition)'
                    }}
                    onMouseEnter={(e) => {
                      if (!isSelected) e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.15)';
                    }}
                    onMouseLeave={(e) => {
                      if (!isSelected) e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.06)';
                    }}
                  >
                    <div style={{
                      background: isSelected ? 'var(--gradient-brand)' : 'rgba(255, 255, 255, 0.04)',
                      padding: '10px',
                      borderRadius: '10px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: isSelected ? '#0f172a' : 'var(--text-secondary)',
                      transition: 'var(--transition)'
                    }}>
                      <Icon size={18} />
                    </div>
                    
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 1 }}>
                      <span style={{ fontSize: '14px', fontWeight: 600, color: isSelected ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
                        {item.title}
                      </span>
                      <span style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                        {item.desc}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>

            <button
              onClick={() => setStep(2)}
              className="primary shimmer-overlay"
              style={{ 
                padding: '14px 20px', 
                borderRadius: '12px', 
                marginTop: '8px', 
                display: 'flex', 
                alignItems: 'center', 
                justifyContent: 'center', 
                gap: '8px' 
              }}
            >
              Continue Configuration <ChevronRight size={16} />
            </button>
          </div>
        )}

        {/* STEP 2: PORTFOLIO STATEMENT IMPORT */}
        {step === 2 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
            <div style={{ textAlign: 'center' }}>
              <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-primary)' }}>Import your real positions</h2>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>Mark gives you 8-second institutional analysis on everything you actually own.</p>
            </div>

            {/* Drag & Drop Area */}
            {!isParsing && portfolio.length === 0 && (
              <div 
                onDragEnter={handleDrag}
                onDragOver={handleDrag}
                onDragLeave={handleDrag}
                onDrop={handleDrop}
                style={{
                  border: '2px dashed rgba(255, 255, 255, 0.1)',
                  borderColor: dragActive ? 'var(--accent-cyan)' : 'rgba(255, 255, 255, 0.1)',
                  borderRadius: '16px',
                  background: dragActive ? 'rgba(56, 189, 248, 0.02)' : 'rgba(255, 255, 255, 0.01)',
                  padding: '30px 20px',
                  textAlign: 'center',
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: '14px',
                  transition: 'var(--transition)'
                }}
              >
                <div style={{
                  background: 'rgba(56, 189, 248, 0.05)',
                  color: 'var(--accent-cyan)',
                  padding: '12px',
                  borderRadius: '50%',
                  display: 'inline-flex'
                }}>
                  <UploadCloud size={28} />
                </div>
                
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  <span style={{ fontSize: '14px', fontWeight: 500 }}>
                    Drag & drop your trade statement here
                  </span>
                  <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                    Supports PDF, Excel or CSV outputs from any major broker
                  </span>
                </div>

                <div style={{ display: 'flex', gap: '6px', justifyContent: 'center', flexWrap: 'wrap', margin: '4px 0' }}>
                  {brokers.map((b) => (
                    <span key={b} style={{ fontSize: '10px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)', padding: '2px 8px', borderRadius: '4px', color: 'var(--text-secondary)' }}>
                      {b}
                    </span>
                  ))}
                </div>

                <div style={{ position: 'relative' }}>
                  <input 
                    type="file" 
                    id="onboarding-file-upload" 
                    accept=".csv,.pdf,.xlsx,.xls"
                    onChange={handleFileChange}
                    style={{ display: 'none' }}
                  />
                  <button 
                    type="button"
                    onClick={() => document.getElementById('onboarding-file-upload')?.click()}
                    style={{ fontSize: '12px', padding: '8px 16px', borderRadius: '8px' }}
                  >
                    Select File
                  </button>
                </div>

                <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  OR
                </div>

                <button 
                  type="button" 
                  onClick={handleUseDemo}
                  style={{ 
                    border: '1px dashed var(--accent-indigo)', 
                    background: 'rgba(129, 140, 248, 0.05)', 
                    color: 'var(--accent-indigo)',
                    fontSize: '12px',
                    padding: '8px 16px',
                    borderRadius: '8px',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}
                >
                  <Sparkles size={12} /> Use Demo Portfolio (6 Stocks)
                </button>
              </div>
            )}

            {/* Parsing Simulated Screen */}
            {isParsing && (
              <div style={{
                background: 'rgba(3, 7, 18, 0.4)',
                border: '1px solid rgba(255, 255, 255, 0.06)',
                borderRadius: '16px',
                padding: '24px',
                display: 'flex',
                flexDirection: 'column',
                gap: '14px',
                fontFamily: 'var(--font-mono)'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--accent-cyan)' }}>
                  <Loader2 size={14} className="animate-spin-custom" />
                  <span>PARSING STATEMENT DATA: {uploadedFileName}</span>
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '12px', marginTop: '6px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', color: parseStep >= 1 ? 'var(--profit)' : 'var(--text-secondary)' }}>
                    <span>▸ Validating statement header schema...</span>
                    <span>{parseStep >= 1 ? '✓ COMPLETE' : '● PROCESSING'}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', color: parseStep >= 2 ? 'var(--profit)' : 'var(--text-secondary)' }}>
                    <span>▸ Matching ISINs to market tickers...</span>
                    <span>{parseStep >= 2 ? '✓ 6 ASSETS FOUND' : parseStep >= 1 ? '● RUNNING' : '○ QUEUED'}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', color: parseStep >= 3 ? 'var(--profit)' : 'var(--text-secondary)' }}>
                    <span>▸ Synthesizing historical buy averages...</span>
                    <span>{parseStep >= 3 ? '✓ COMPLETE' : parseStep >= 2 ? '● RUNNING' : '○ QUEUED'}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', color: parseStep >= 4 ? 'var(--profit)' : 'var(--text-secondary)' }}>
                    <span>▸ Calibrating index weights & risk ratios...</span>
                    <span>{parseStep >= 4 ? '✓ STABLE' : parseStep >= 3 ? '● RUNNING' : '○ QUEUED'}</span>
                  </div>
                </div>
              </div>
            )}

            {/* Parsing Complete / Holdings Preview */}
            {!isParsing && portfolio.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{
                  background: 'rgba(52, 211, 153, 0.05)',
                  border: '1px solid rgba(52, 211, 153, 0.15)',
                  color: 'var(--profit)',
                  padding: '12px 16px',
                  borderRadius: '10px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  fontSize: '13px'
                }}>
                  <CheckCircle2 size={16} />
                  <span>Import successful! {portfolio.length} stock positions compiled.</span>
                </div>

                {/* Holdings Preview Table */}
                <div style={{
                  background: 'rgba(3,7,18,0.3)',
                  border: '1px solid rgba(255,255,255,0.06)',
                  borderRadius: '10px',
                  overflow: 'hidden'
                }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ background: 'rgba(255,255,255,0.02)', borderBottom: '1px solid rgba(255,255,255,0.06)', color: 'var(--text-secondary)' }}>
                        <th style={{ padding: '8px 12px' }}>TICKER</th>
                        <th style={{ padding: '8px 12px' }}>QTY</th>
                        <th style={{ padding: '8px 12px' }}>AVG PRICE</th>
                        <th style={{ padding: '8px 12px' }}>SECTOR</th>
                      </tr>
                    </thead>
                    <tbody>
                      {portfolio.map((item) => (
                        <tr key={item.symbol} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', color: 'var(--text-primary)' }}>
                          <td style={{ padding: '8px 12px', fontWeight: 600 }}>{item.symbol}</td>
                          <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)' }}>{item.qty}</td>
                          <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)' }}>₹{item.avgCost.toLocaleString('en-IN')}</td>
                          <td style={{ padding: '8px 12px' }}>
                            <span style={{ fontSize: '10px', background: 'rgba(56, 189, 248, 0.08)', color: 'var(--accent-cyan)', padding: '1px 6px', borderRadius: '4px' }}>
                              {item.sector}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <button 
                  type="button" 
                  onClick={() => { setPortfolio([]); setUploadedFileName(''); }}
                  style={{ color: 'var(--loss)', alignSelf: 'flex-start', fontSize: '11px', padding: '0', background: 'none', border: 'none' }}
                >
                  Reset & Upload Another Statement
                </button>
              </div>
            )}

            {/* Navigation buttons */}
            <div style={{ display: 'flex', gap: '14px', marginTop: '6px' }}>
              <button
                type="button"
                onClick={() => setStep(1)}
                style={{ flex: 1, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
              >
                <ArrowLeft size={14} /> Back
              </button>
              <button
                type="button"
                onClick={() => setStep(3)}
                disabled={isParsing || portfolio.length === 0}
                className="primary"
                style={{ flex: 1, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
              >
                Continue Setup <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}

        {/* STEP 3: WATCHLIST SELECTION */}
        {step === 3 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
            <div style={{ textAlign: 'center' }}>
              <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-primary)' }}>Select Watchlist Targets</h2>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>Which additional assets are you tracking for future acquisitions?</p>
            </div>

            {/* Custom Input Form */}
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

            {/* Popular Selectable Chips */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <span style={{ fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>
                Popular Companies
              </span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                {popularChips.map((chip) => {
                  const isChecked = watchlist.includes(chip);
                  return (
                    <button
                      key={chip}
                      type="button"
                      onClick={() => toggleChip(chip)}
                      style={{
                        background: isChecked ? 'rgba(56, 189, 248, 0.08)' : 'rgba(255, 255, 255, 0.01)',
                        borderColor: isChecked ? 'var(--accent-cyan)' : 'rgba(255, 255, 255, 0.06)',
                        color: isChecked ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                        borderRadius: '20px',
                        padding: '6px 14px',
                        fontSize: '12px',
                        border: '1px solid',
                        boxShadow: isChecked ? '0 0 10px rgba(56, 189, 248, 0.05)' : 'none'
                      }}
                    >
                      {chip}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Selected Summary Card */}
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
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)', fontWeight: 600 }}>
                {watchlist.length} Assets
              </span>
            </div>

            {/* Action buttons */}
            <div style={{ display: 'flex', gap: '14px', marginTop: '6px' }}>
              <button
                type="button"
                onClick={() => setStep(2)}
                style={{ flex: 1, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
              >
                <ArrowLeft size={14} /> Back
              </button>
              <button
                type="button"
                onClick={() => setStep(4)}
                className="primary"
                style={{ flex: 1, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
              >
                Continue Setup <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}

        {/* STEP 4: MEET MARK */}
        {step === 4 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
            <div style={{ textAlign: 'center' }}>
              <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-primary)' }}>You're set. Meet Mark.</h2>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>Your quant engine is ready to run tests.</p>
            </div>

            {/* Glass Avatar Card */}
            <div style={{
              background: 'rgba(15, 23, 42, 0.4)',
              border: '1px solid rgba(255, 255, 255, 0.06)',
              borderRadius: '14px',
              padding: '24px',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '16px',
              textAlign: 'center',
              position: 'relative'
            }}>
              <div 
                className="animate-pulse-glow"
                style={{
                  width: '60px',
                  height: '60px',
                  borderRadius: '50%',
                  background: 'rgba(56, 189, 248, 0.08)',
                  border: '2px solid var(--accent-cyan)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'var(--accent-cyan)'
                }}
              >
                <Logo size={32} />
              </div>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <span style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>Mark · Online</span>
                <span className="badge badge-success" style={{ fontSize: '10px', alignSelf: 'center' }}>Status: Live</span>
              </div>

              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                "I am initialized on historical balance sheets, solvency margins, and quantitative cash flows. I synthesize pure equity data and strip away market noise. Let's deploy your cockpit."
              </p>
            </div>

            {/* Trial suggested query */}
            <div style={{
              background: 'rgba(129, 140, 248, 0.03)',
              border: '1px dashed var(--accent-indigo)',
              borderRadius: '10px',
              padding: '12px 16px',
              display: 'flex',
              alignItems: 'center',
              gap: '10px'
            }}>
              <ShieldAlert size={14} color="var(--accent-indigo)" style={{ flexShrink: 0 }} />
              <span style={{ fontSize: '12px', color: 'var(--text-primary)' }}>
                Suggested Query: <strong>"Analyze {portfolio[0]?.symbol || watchlist[0] || 'RELIANCE'} PE ratio."</strong>
              </span>
            </div>

            {/* Actions */}
            <div style={{ display: 'flex', gap: '14px', marginTop: '6px' }}>
              <button
                type="button"
                onClick={() => setStep(3)}
                style={{ flex: 1, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
              >
                <ArrowLeft size={14} /> Back
              </button>
              <button
                type="button"
                onClick={handleComplete}
                className="primary shimmer-overlay"
                style={{ flex: 1, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
              >
                Launch Command Center <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
export default Onboarding;

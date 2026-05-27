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
  ArrowLeft,
  Lock,
  Eye,
  EyeOff,
  AlertTriangle,
  Search
} from 'lucide-react';
import { Logo } from '../components/layout/Logo';
import { useAuth } from '../context/AuthContext';
import { 
  uploadPortfolioDocument, 
  uploadPortfolioScreenshot, 
  confirmExtraction, 
  cancelExtraction, 
  replacePortfolioMirror 
} from '../api/client';
import { 
  searchCompanies, 
  searchMutualFunds, 
  POPULAR_MUTUAL_FUNDS,
  INDIAN_STOCKS
} from '../data/indianStocks';

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
  { symbol: "INFY", name: "Infosys Limited", qty: 25, avgCost: 1380, current: 1452, sector: "IT" },
  { symbol: "ITC", name: "ITC Limited", qty: 50, avgCost: 410, current: 431, sector: "FMCG" },
  { symbol: "ASIANPAINT", name: "Asian Paints", qty: 8, avgCost: 2650, current: 2810, sector: "Consumer" }
];

const resolvePositionDetails = (symbol: string, currentName: string, currentSector: string) => {
  const cleanSym = (symbol || '').split('.')[0].toUpperCase().trim();
  
  const ISIN_TO_SYMBOL: Record<string, string> = {
    'INE002A01018': 'RELIANCE',
    'INE467B01029': 'TCS',
    'INE009A01021': 'INFY',
    'INE040A01034': 'HDFCBANK',
    'INE154A01025': 'ITC',
    'INE021A01026': 'ASIANPAINT',
    'INE155A01022': 'TATAMOTORS',
    'INE758T01015': 'ZOMATO',
    'INE0LP301011': 'Physicswallah',
    'INF247L01DA9': 'MOMF'
  };
  
  const targetSym = ISIN_TO_SYMBOL[cleanSym] || cleanSym;
  
  if (targetSym === 'MOMF') {
    return {
      symbol: 'MOMF',
      name: 'Motilal Oswal Manufacturing Fund - Direct Growth',
      sector: 'Thematic - Manufacturing'
    };
  }
  
  if (targetSym === 'Physicswallah') {
    return {
      symbol: 'Physicswallah',
      name: 'Physicswallah Limited',
      sector: 'Education Services'
    };
  }

  // Check if mutual fund in POPULAR_MUTUAL_FUNDS
  const mf = POPULAR_MUTUAL_FUNDS.find(f => f.symbol.toUpperCase() === targetSym);
  if (mf) {
    return {
      symbol: targetSym,
      name: mf.name,
      sector: mf.category
    };
  }

  // Check if stock in INDIAN_STOCKS
  const stock = INDIAN_STOCKS.find(s => s.symbol.toUpperCase() === targetSym);
  if (stock) {
    return {
      symbol: targetSym,
      name: stock.name,
      sector: stock.sector === 'Other' || !stock.sector ? 'General' : stock.sector
    };
  }

  return {
    symbol: targetSym,
    name: currentName || symbol,
    sector: currentSector && currentSector !== 'General' && currentSector !== 'Other' ? currentSector : 'General'
  };
};

export const Onboarding: React.FC = () => {
  const navigate = useNavigate();
  const { user, showToast } = useAuth();

  const [step, setStep] = useState(1);
  const [name, setName] = useState('');
  const [style, setStyle] = useState<'Conservative' | 'Balanced' | 'Growth'>('Balanced');
  const [watchlist, setWatchlist] = useState<string[]>(['RELIANCE', 'TCS', 'INFY']);
  const [inputVal, setInputVal] = useState('');

  // Watchlist search dropdown states
  const [searchResults, setSearchResults] = useState<Array<{ symbol: string; name: string; type: 'stock' | 'mf' }>>([]);
  const [showDropdown, setShowDropdown] = useState(false);

  // Portfolio statement upload states
  const [portfolio, setPortfolio] = useState<PortfolioItem[]>([]);
  const [isParsing, setIsParsing] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  
  // Real file states
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isPdf, setIsPdf] = useState(false);
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  // Review states
  const [reviewId, setReviewId] = useState<string>('');
  const [pendingPositions, setPendingPositions] = useState<any[]>([]);
  const [reviewSource, setReviewSource] = useState<string>('');

  // Prefill name from authenticated user
  useEffect(() => {
    if (user && user.name && !name) {
      setName(user.name);
    }
  }, [user]);

  // Handle Search Input in Watchlist
  useEffect(() => {
    if (inputVal.trim().length >= 3) {
      const stocks = searchCompanies(inputVal, 4).map(s => ({ symbol: s.symbol, name: s.name, type: 'stock' as const }));
      const mfs = searchMutualFunds(inputVal, 4).map(m => ({ symbol: m.symbol, name: m.name, type: 'mf' as const }));
      setSearchResults([...stocks, ...mfs]);
      setShowDropdown(true);
    } else {
      setSearchResults([]);
      setShowDropdown(false);
    }
  }, [inputVal]);

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
  const popularMutualFunds = POPULAR_MUTUAL_FUNDS.slice(0, 8);
  const brokers = ['Zerodha', 'Groww', 'Upstox', 'ICICI Direct'];

  const toggleChip = (chip: string) => {
    if (watchlist.includes(chip)) {
      setWatchlist(watchlist.filter(c => c !== chip));
    } else {
      setWatchlist([...watchlist, chip]);
    }
  };

  const handleSelectSearchItem = (item: { symbol: string; name: string }) => {
    if (!watchlist.includes(item.symbol)) {
      setWatchlist([...watchlist, item.symbol]);
      showToast(`Added ${item.symbol} to watchlist`, 'success');
    }
    setInputVal('');
    setShowDropdown(false);
  };

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
      handleFileSelected(file);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      handleFileSelected(file);
    }
  };

  const handleFileSelected = (file: File) => {
    setSelectedFile(file);
    setIsPdf(file.name.toLowerCase().endsWith('.pdf'));
    setPassword('');
  };

  const handleUploadAndProcess = async () => {
    if (!selectedFile) return;
    setIsParsing(true);
    showToast(`Parsing ${selectedFile.name}...`, 'info');
    
    try {
      const fileExtension = selectedFile.name.toLowerCase();
      let res;
      
      if (fileExtension.endsWith('.png') || fileExtension.endsWith('.jpg') || fileExtension.endsWith('.jpeg')) {
        res = await uploadPortfolioScreenshot(selectedFile);
      } else if (fileExtension.endsWith('.pdf') || fileExtension.endsWith('.csv') || fileExtension.endsWith('.xlsx') || fileExtension.endsWith('.xls')) {
        res = await uploadPortfolioDocument(selectedFile, password);
      } else {
        throw new Error('Unsupported file format. Please upload PDF, CSV, Excel or Image.');
      }

      if (res.status === 'REVIEW_REQUIRED' || res.sync_status === 'REVIEW_REQUIRED' || res.code === 'REVIEW_REQUIRED') {
        setReviewId(res.review_id);
        setPendingPositions(res.positions || []);
        setReviewSource(res.source_type || 'document');
        showToast('Holdings extracted. Review required.', 'info');
      } else if (res.status === 'MIRROR_SYNCHRONIZED' || res.sync_status === 'MIRROR_SYNCHRONIZED' || res.code === 'MIRROR_SYNCHRONIZED') {
        const mapped = (res.positions || []).map((p: any) => {
          const qty = p.quantity || 0;
          const marketVal = p.market_value || 0;
          let currentPrice = p.last_price || p.current_price || 0;
          if (currentPrice === 0 && qty > 0 && marketVal > 0) {
            currentPrice = marketVal / qty;
          }
          if (currentPrice === 0) {
            currentPrice = p.avg_cost || p.cost_basis || 100.00;
          }
          const sym = p.symbol || p.exchange_symbol;
          const resolved = resolvePositionDetails(sym, p.name, p.sector);
          
          let avgCost = p.avg_cost || p.cost_basis || 0;
          if (avgCost === 0) {
            avgCost = parseFloat((currentPrice * 0.85).toFixed(4));
          }
          
          return {
            symbol: resolved.symbol,
            name: resolved.name,
            qty: qty,
            avgCost: avgCost,
            current: currentPrice,
            sector: resolved.sector
          };
        });
        setPortfolio(mapped);
        showToast(`Successfully synchronized ${mapped.length} positions.`, 'success');
      }
    } catch (err: any) {
      console.error(err);
      const msg = err.message || 'Parsing failed.';
      showToast(msg, 'error');
    } finally {
      setIsParsing(false);
    }
  };

  const handleConfirmReview = async () => {
    setIsParsing(true);
    try {
      const res = await confirmExtraction(reviewId, pendingPositions, reviewSource);
      const mapped = (res.positions || []).map((p: any) => {
        const qty = p.quantity || 0;
        const marketVal = p.market_value || 0;
        let currentPrice = p.last_price || p.current_price || 0;
        if (currentPrice === 0 && qty > 0 && marketVal > 0) {
          currentPrice = marketVal / qty;
        }
        if (currentPrice === 0) {
          currentPrice = p.avg_cost || p.cost_basis || 100.00;
        }
        const sym = p.symbol || p.exchange_symbol;
        const resolved = resolvePositionDetails(sym, p.name, p.sector);
        
        let avgCost = p.avg_cost || p.cost_basis || 0;
        if (avgCost === 0) {
          avgCost = parseFloat((currentPrice * 0.85).toFixed(4));
        }
        
        return {
          symbol: resolved.symbol,
          name: resolved.name,
          qty: qty,
          avgCost: avgCost,
          current: currentPrice,
          sector: resolved.sector
        };
      });
      setPortfolio(mapped);
      setReviewId('');
      setPendingPositions([]);
      showToast('Portfolio sync complete!', 'success');
    } catch (err: any) {
      showToast(err.message || 'Confirmation failed.', 'error');
    } finally {
      setIsParsing(false);
    }
  };

  const handleCancelReview = async () => {
    try {
      await cancelExtraction();
      setReviewId('');
      setPendingPositions([]);
      setSelectedFile(null);
      setIsPdf(false);
      setPassword('');
      showToast('Extraction cancelled.', 'info');
    } catch (err: any) {
      showToast(err.message || 'Cancel failed.', 'error');
    }
  };

  const handleUseDemo = async () => {
    setIsParsing(true);
    showToast('Injecting demo portfolio...', 'info');
    try {
      const mappedInputs = DEMO_PORTFOLIO.map(item => ({
        symbol: item.symbol,
        exchange: 'NSE',
        quantity: item.qty,
        market_value: item.qty * item.current,
        cost_basis: item.qty * item.avgCost,
        name: item.name,
        avg_cost: item.avgCost,
        last_price: item.current,
        sector: item.sector,
        active: true
      }));
      await replacePortfolioMirror(mappedInputs);
      setPortfolio(DEMO_PORTFOLIO);
      showToast('Demo portfolio synchronized!', 'success');
    } catch (err: any) {
      showToast(err.message || 'Demo portfolio creation failed.', 'error');
    } finally {
      setIsParsing(false);
    }
  };

  const handleComplete = () => {
    if (!name.trim()) return;

    localStorage.setItem('prospektlab_username', name.trim());
    localStorage.setItem('prospektlab_style', style);
    localStorage.setItem('prospektlab_watchlist', JSON.stringify(watchlist));
    localStorage.setItem('prospektlab_portfolio', JSON.stringify(portfolio));
    localStorage.setItem('prospektlab_onboarded', 'true');
    
    // Clear old onboarding progress
    localStorage.removeItem('prospektlab_onboarding_step');

    const mockConversations = [
      { id: '1', title: `Portfolio Analysis for ${name.trim()}`, date: 'Just now' }
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
          <Logo size={32} />
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
              <span>STEP {step} OF 4</span>
              <span style={{ color: 'var(--accent-cyan)' }}>
                {step === 1 && 'NAME & STYLE'}
                {step === 2 && 'PORTFOLIO IMPORT'}
                {step === 3 && 'WATCHLIST SELECTION'}
                {step === 4 && 'MARK-IT QUANT ENGINE'}
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

        {/* STEP 1: NAME + INVESTING STYLE */}
        {step === 1 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div style={{ textAlign: 'center' }}>
              <h2 style={{ fontSize: '22px', fontWeight: 600, color: 'var(--text-primary)' }}>Welcome. What's your name? <span style={{ color: 'var(--loss)' }}>*</span></h2>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '6px' }}>Mark-IT — your AI market analyst — will address you personally from here on.</p>
            </div>

            {/* Name capture */}
            <input
              type="text"
              placeholder="Your first name (required)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={{ fontSize: '15px', padding: '14px 16px', textAlign: 'center' }}
              required
            />

            <div style={{ textAlign: 'center', marginTop: '8px' }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)' }}>How aggressively do you want to play?</h3>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>This decides which signals Mark-IT surfaces first for you.</p>
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
              onClick={() => name.trim() && setStep(2)}
              className="primary shimmer-overlay"
              disabled={!name.trim()}
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
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>Mark-IT gives you 8-second institutional analysis on everything you actually own.</p>
            </div>

            {/* Drag & Drop Area */}
            {!isParsing && portfolio.length === 0 && !reviewId && (
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
                    Supports PDF, Excel, CSV or Screenshot (PNG, JPG)
                  </span>
                </div>

                <div style={{ display: 'flex', gap: '6px', justifyContent: 'center', flexWrap: 'wrap', margin: '4px 0' }}>
                  {brokers.map((b) => (
                    <span key={b} style={{ fontSize: '10px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)', padding: '2px 8px', borderRadius: '4px', color: 'var(--text-secondary)' }}>
                      {b}
                    </span>
                  ))}
                </div>

                <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
                  <input 
                    type="file" 
                    id="onboarding-file-upload" 
                    accept=".csv,.pdf,.xlsx,.xls,.png,.jpg,.jpeg"
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

                  {selectedFile && (
                    <div style={{ fontSize: '12px', color: 'var(--accent-cyan)', marginTop: '4px', fontWeight: 500 }}>
                      Selected: {selectedFile.name}
                    </div>
                  )}
                </div>

                {/* PDF Password Input Field (Conditional Render) */}
                {selectedFile && isPdf && (
                  <div className="animate-fade-in-up" style={{ 
                    width: '100%', 
                    maxWidth: '300px', 
                    display: 'flex', 
                    flexDirection: 'column', 
                    gap: '6px', 
                    textAlign: 'left',
                    marginTop: '10px'
                  }}>
                    <label style={{ fontSize: '11px', color: 'var(--text-secondary)', fontWeight: 600 }}>PDF PASSWORD (IF SECURED)</label>
                    <div className="auth-input-wrapper">
                      <Lock className="auth-input-icon" size={14} />
                      <input 
                        type={showPassword ? "text" : "password"}
                        className="auth-input"
                        placeholder="Enter password..."
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        style={{ fontSize: '12px', padding: '8px 12px 8px 36px', height: '36px' }}
                      />
                      <button
                        type="button"
                        className="auth-input-right"
                        onClick={() => setShowPassword(!showPassword)}
                        style={{ height: '36px' }}
                      >
                        {showPassword ? <EyeOff size={12} /> : <Eye size={12} />}
                      </button>
                    </div>
                  </div>
                )}

                {selectedFile && (
                  <button
                    type="button"
                    onClick={handleUploadAndProcess}
                    className="primary"
                    style={{ fontSize: '13px', padding: '10px 24px', borderRadius: '8px', marginTop: '10px' }}
                  >
                    Upload & Process Statement
                  </button>
                )}

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

            {/* Parsing Screen */}
            {isParsing && (
              <div style={{
                background: 'rgba(3, 7, 18, 0.4)',
                border: '1px solid rgba(255, 255, 255, 0.06)',
                borderRadius: '16px',
                padding: '24px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '14px',
                fontFamily: 'var(--font-mono)'
              }}>
                <Loader2 size={28} className="animate-spin-custom" color="var(--accent-cyan)" />
                <span style={{ fontSize: '12px', color: 'var(--accent-cyan)' }}>PARSING PORTFOLIO STATEMENT ON SERVER...</span>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>Running OCR extraction & database alignment...</span>
              </div>
            )}

            {/* REVIEW REQUIRED SCREEN */}
            {!isParsing && reviewId && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }} className="animate-fade-in-up">
                <div style={{
                  background: 'rgba(251, 191, 36, 0.05)',
                  border: '1px solid rgba(251, 191, 36, 0.2)',
                  color: '#fbbf24',
                  padding: '12px 16px',
                  borderRadius: '10px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  fontSize: '13px'
                }}>
                  <AlertTriangle size={16} />
                  <span>Review Extracted Holdings before Synchronizing:</span>
                </div>

                <div style={{
                  background: 'rgba(3,7,18,0.3)',
                  border: '1px solid rgba(255,255,255,0.06)',
                  borderRadius: '10px',
                  maxHeight: '200px',
                  overflowY: 'auto'
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
                      {pendingPositions.map((item, idx) => (
                        <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', color: 'var(--text-primary)' }}>
                          <td style={{ padding: '8px 12px', fontWeight: 600 }}>{item.symbol || item.exchange_symbol}</td>
                          <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)' }}>{item.quantity || 0}</td>
                          <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)' }}>₹{(item.avg_cost || item.cost_basis || 0).toLocaleString('en-IN')}</td>
                          <td style={{ padding: '8px 12px' }}>{item.sector || 'General'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div style={{ display: 'flex', gap: '12px' }}>
                  <button
                    type="button"
                    onClick={handleCancelReview}
                    style={{ flex: 1, padding: '10px', background: 'transparent', border: '1px solid var(--border-subtle)' }}
                  >
                    Cancel Sync
                  </button>
                  <button
                    type="button"
                    onClick={handleConfirmReview}
                    className="primary"
                    style={{ flex: 1, padding: '10px' }}
                  >
                    Confirm & Sync
                  </button>
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
                  onClick={() => { setPortfolio([]); setSelectedFile(null); setPassword(''); }}
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
              <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-primary)' }}>Select Wishlist Targets</h2>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>Which additional assets or funds are you tracking for future buys?</p>
            </div>

            {/* Custom Input Form with search as you type */}
            <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div className="auth-input-wrapper">
                <Search className="auth-input-icon" size={16} />
                <input
                  type="text"
                  placeholder="Type company or fund name (min 3 chars)..."
                  value={inputVal}
                  onChange={(e) => setInputVal(e.target.value)}
                  style={{ flex: 1, fontSize: '13px', paddingLeft: '38px' }}
                />
              </div>

              {showDropdown && searchResults.length > 0 && (
                <div style={{
                  position: 'absolute',
                  top: '46px',
                  left: 0,
                  right: 0,
                  background: 'var(--bg-elevated)',
                  backdropFilter: 'blur(20px)',
                  border: '1px solid var(--border-hover)',
                  borderRadius: '8px',
                  boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
                  maxHeight: '200px',
                  overflowY: 'auto',
                  zIndex: 100
                }}>
                  {searchResults.map((res) => (
                    <div
                      key={res.symbol}
                      onClick={() => handleSelectSearchItem(res)}
                      style={{
                        padding: '10px 14px',
                        cursor: 'pointer',
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        borderBottom: '1px solid rgba(255,255,255,0.04)',
                        fontSize: '12px'
                      }}
                      onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'}
                      onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                    >
                      <div>
                        <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{res.symbol}</span>
                        <span style={{ marginLeft: '10px', color: 'var(--text-secondary)' }}>{res.name}</span>
                      </div>
                      <span className={`badge ${res.type === 'mf' ? 'badge-info' : 'badge-premium'}`} style={{ fontSize: '9px' }}>
                        {res.type === 'mf' ? 'MF' : 'Stock'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Popular Selectable Chips */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <span style={{ fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700, display: 'block', marginBottom: '8px' }}>
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

              <div>
                <span style={{ fontSize: '11px', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700, display: 'block', marginBottom: '8px' }}>
                  Popular Mutual Funds
                </span>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                  {popularMutualFunds.map((fund) => {
                    const isChecked = watchlist.includes(fund.symbol);
                    return (
                      <button
                        key={fund.symbol}
                        type="button"
                        onClick={() => toggleChip(fund.symbol)}
                        style={{
                          background: isChecked ? 'rgba(96, 165, 250, 0.08)' : 'rgba(255, 255, 255, 0.01)',
                          borderColor: isChecked ? 'var(--neutral)' : 'rgba(255, 255, 255, 0.06)',
                          color: isChecked ? 'var(--neutral)' : 'var(--text-secondary)',
                          borderRadius: '20px',
                          padding: '6px 14px',
                          fontSize: '12px',
                          border: '1px solid',
                          boxShadow: isChecked ? '0 0 10px rgba(96, 165, 250, 0.05)' : 'none'
                        }}
                      >
                        {fund.name.replace(' Opportunities Fund', '').replace(' Long Term Equity Fund', '').replace(' Balanced Fund', '')}
                      </button>
                    );
                  })}
                </div>
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

        {/* STEP 4: MEET MARK-IT */}
        {step === 4 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
            <div style={{ textAlign: 'center' }}>
              <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-primary)' }}>You're set. Meet Mark-IT.</h2>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>Your quant engine is ready to run audits.</p>
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
                <span style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>Mark-IT · Online</span>
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

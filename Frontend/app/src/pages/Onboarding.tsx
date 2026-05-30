import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
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
import { 
  uploadPortfolioDocument, 
  uploadPortfolioScreenshot, 
  confirmExtraction, 
  cancelExtraction 
} from '../api/client';
import { INDIAN_STOCKS, POPULAR_MUTUAL_FUNDS } from '../data/indianStocks';


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
  const { setOnboarded } = useAuth();
  const [step, setStep] = useState(1);

  // Allow the page to scroll while on the onboarding screen.
  // The main app uses overflow:hidden on body/#root for the dashboard cockpit,
  // so we temporarily unlock it here and restore on unmount.
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

  // Pre-fill name from localStorage (set by landing page personalisation)
  const [name, setName] = useState(() => localStorage.getItem('prospektlab_username') || '');
  
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

  // Real backend parsing state hooks
  const [pdfPassword, setPdfPassword] = useState('');
  const [showPasswordInput, setShowPasswordInput] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const [reviewPositions, setReviewPositions] = useState<any[]>([]);
  const [sourceType, setSourceType] = useState<string>('unknown');
  const [isReviewing, setIsReviewing] = useState(false);
  const [isSubmittingReview, setIsSubmittingReview] = useState(false);

  // Autocomplete suggestions for watchlist search
  const [suggestions, setSuggestions] = useState<Array<{ symbol: string; name: string; type: 'Stock' | 'Mutual Fund'; detail: string }>>([]);


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
    setSuggestions([]);
  };

  // Autocomplete filtering for stocks & mutual funds as user types
  useEffect(() => {
    if (!inputVal.trim()) {
      setSuggestions([]);
      return;
    }
    const query = inputVal.toLowerCase().trim();

    // Filter stocks (up to 5 matches)
    const matchedStocks = INDIAN_STOCKS.filter(
      s => s.symbol.toLowerCase().includes(query) || s.name.toLowerCase().includes(query)
    ).slice(0, 5).map(s => ({
      symbol: s.symbol,
      name: s.name,
      type: 'Stock' as const,
      detail: s.sector && s.sector !== 'Other' ? s.sector : 'Equity'
    }));

    // Filter mutual funds (up to 5 matches)
    const matchedMFs = POPULAR_MUTUAL_FUNDS.filter(
      f => f.symbol.toLowerCase().includes(query) || f.name.toLowerCase().includes(query)
    ).slice(0, 5).map(f => ({
      symbol: f.symbol,
      name: f.name,
      type: 'Mutual Fund' as const,
      detail: f.category || 'Mutual Fund'
    }));

    setSuggestions([...matchedStocks, ...matchedMFs]);
  }, [inputVal]);


  // Helper to map backend positions into the UI PortfolioItem format
  const mapPositionsToPortfolioItems = (positions: any[]): PortfolioItem[] => {
    return positions.map((p: any) => {
      const qty = p.quantity || 0;
      const marketVal = p.market_value || 0;
      let currentPrice = p.last_price || 0;
      if (currentPrice === 0 && qty > 0 && marketVal > 0) {
        currentPrice = marketVal / qty;
      }
      if (currentPrice === 0) {
        currentPrice = p.avg_cost || p.cost_basis || 100.00;
      }
      
      let avgCost = p.avg_cost || 0;
      if (avgCost === 0) {
        avgCost = parseFloat((currentPrice * 0.85).toFixed(4));
      }
      
      const cleanSym = (p.symbol || '').split('.')[0].toUpperCase().trim();
      const ISIN_TO_SYMBOL: Record<string, string> = {
        'INE002A01018': 'RELIANCE',
        'INE467B01029': 'TCS',
        'INE009A01021': 'INFY',
        'INE040A01034': 'HDFCBANK',
        'INE154A01025': 'ITC',
        'INE021A01026': 'ASIANPAINT',
        'INE155A01022': 'TATAMOTORS',
        'INE758T01015': 'ZOMATO',
        'INE0LP301011': 'PWL',
        'INF247L01DA9': 'MOMF'
      };
      const targetSym = ISIN_TO_SYMBOL[cleanSym] || cleanSym;
      let resolvedName = p.name || '';
      let resolvedSector = p.sector || 'General';
      
      const mf = POPULAR_MUTUAL_FUNDS.find(f => f.symbol.toUpperCase() === targetSym);
      if (mf) {
        resolvedName = mf.name;
        resolvedSector = mf.category;
      } else {
        const stock = INDIAN_STOCKS.find(s => s.symbol.toUpperCase() === targetSym);
        if (stock) {
          resolvedName = stock.name;
          resolvedSector = stock.sector === 'Other' || !stock.sector ? 'General' : stock.sector;
        }
      }

      return {
        symbol: targetSym,
        name: resolvedName,
        qty: qty,
        avgCost: avgCost,
        current: currentPrice,
        sector: resolvedSector
      };
    });
  };

  const handleFileSelect = (file: File) => {
    setErrorMsg(null);
    setShowPasswordInput(false);
    setPdfPassword('');
    setPendingFile(null);

    const fileName = file.name.toLowerCase();
    const isPDF = fileName.endsWith('.pdf');
    const isExcelOrCsv = fileName.endsWith('.xls') || fileName.endsWith('.xlsx') || fileName.endsWith('.csv');
    const isImage = fileName.endsWith('.jpg') || fileName.endsWith('.jpeg') || fileName.endsWith('.png');

    if (!isPDF && !isExcelOrCsv && !isImage) {
      setErrorMsg('Unsupported file type. Please upload a PDF, CSV, Excel, or Image file.');
      return;
    }

    if (isPDF) {
      setPendingFile(file);
      setShowPasswordInput(true);
    } else {
      startRealUpload(file);
    }
  };

  const startRealUpload = async (file: File, password?: string) => {
    setIsParsing(true);
    setParseStep(0);
    setErrorMsg(null);
    setUploadedFileName(file.name);
    setShowPasswordInput(false);
    setPendingFile(null);

    // Visual steps timer progress in parallel
    let currentStep = 0;
    const progressTimer = setInterval(() => {
      currentStep = Math.min(currentStep + 1, 3);
      setParseStep(currentStep);
    }, 1200);

    try {
      const fileName = file.name.toLowerCase();
      const isImage = fileName.endsWith('.jpg') || fileName.endsWith('.jpeg') || fileName.endsWith('.png');
      
      let res;
      if (isImage) {
        res = await uploadPortfolioScreenshot(file);
      } else {
        res = await uploadPortfolioDocument(file, password);
      }

      clearInterval(progressTimer);
      setParseStep(4);
      // Wait a moment for UX transition
      await new Promise(resolve => setTimeout(resolve, 800));

      if (res.code === "REVIEW_REQUIRED" || res.status === "REVIEW_REQUIRED" || res.sync_status === "REVIEW_REQUIRED") {
        setReviewId(res.review_id);
        setReviewPositions(res.positions || []);
        setSourceType(res.source_type || (isImage ? 'image' : 'pdf'));
        setIsReviewing(true);
        setIsParsing(false);
      } else if (res.code === "MIRROR_SYNCHRONIZED" || res.status === "MIRROR_SYNCHRONIZED" || res.sync_status === "MIRROR_SYNCHRONIZED") {
        const mapped = mapPositionsToPortfolioItems(res.positions || []);
        setPortfolio(mapped);
        setIsParsing(false);
      } else if (res.code === "EMPTY_BUT_VALID") {
        setErrorMsg('Document is valid but no active holdings were found.');
        setIsParsing(false);
      } else {
        const mapped = mapPositionsToPortfolioItems(res.positions || []);
        setPortfolio(mapped);
        setIsParsing(false);
      }
    } catch (err: any) {
      clearInterval(progressTimer);
      console.error(err);
      setErrorMsg(err.message || 'An error occurred during file parsing.');
      setIsParsing(false);
    }
  };

  const handleConfirmReview = async () => {
    if (!reviewId) return;
    setIsSubmittingReview(true);
    setErrorMsg(null);
    try {
      const res = await confirmExtraction(reviewId, reviewPositions, sourceType);
      if (res && res.positions) {
        const mapped = mapPositionsToPortfolioItems(res.positions);
        setPortfolio(mapped);
        setIsReviewing(false);
        setReviewId(null);
        setReviewPositions([]);
      } else {
        throw new Error('Failed to synchronize reviewed positions.');
      }
    } catch (err: any) {
      console.error(err);
      setErrorMsg(err.message || 'Failed to confirm review.');
    } finally {
      setIsSubmittingReview(false);
    }
  };

  const handleCancelReview = async () => {
    try {
      await cancelExtraction();
    } catch (err) {
      console.error('Cancel extraction failed', err);
    } finally {
      setIsReviewing(false);
      setReviewId(null);
      setReviewPositions([]);
      setPendingFile(null);
    }
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
      handleFileSelect(file);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      handleFileSelect(file);
    }
  };

  const handleUseDemo = () => {
    setUploadedFileName('demostatement_2026.csv');
    setIsParsing(true);
    setParseStep(0);
    // Start simulation timer
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
    setOnboarded(true);
    
    // Clear old onboarding progress
    localStorage.removeItem('prospektlab_onboarding_step');

    const newSessionId = 'conv-' + Date.now();
    const mockConversations = [
      { id: newSessionId, title: `Portfolio Analysis for ${name || 'You'}`, date: 'Just now' }
    ];
    localStorage.setItem('prospektlab_conversations', JSON.stringify(mockConversations));

    navigate('/dashboard');
  };

  return (
    <div className="onboarding-screen animate-fade-in-up">
      
      {/* Absolute Glass Card Container */}
      <div className="glass onboarding-card">
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
              <span>{step === 4 ? 'COMPLETE' : `STEP ${step} OF 3`}</span>
              <span style={{ color: 'var(--accent-cyan)' }}>
                {step === 1 && 'YOUR NAME + STYLE'}
                {step === 2 && 'YOUR PORTFOLIO'}
                {step === 3 && 'FINAL SETUP'}
                {step === 4 && 'DEPLOY COMMAND CENTER'}
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
              <h2 style={{ fontSize: '22px', fontWeight: 600, color: 'var(--text-primary)' }}>Your Institutional Edge Starts Here</h2>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '6px' }}>Arthik — your personal AI analyst — will address you by name and tailor every insight to your risk profile. Let's build your command center.</p>
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
              <h3 style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)' }}>How do you want Arthik to think for you?</h3>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>This determines which red flags and opportunities Arthik prioritizes in your daily briefings.</p>
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
              <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-primary)' }}>Upload Your Portfolio. See the Hidden Risks.</h2>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>In 8 seconds, Arthik will audit your real holdings for concentration risk, overlap, and leverage — the things your broker won't tell you.</p>
            </div>

            {/* Error Message Box */}
            {errorMsg && (
              <div style={{
                background: 'rgba(239, 68, 68, 0.08)',
                border: '1px solid rgba(239, 68, 68, 0.2)',
                color: 'var(--loss)',
                padding: '12px 16px',
                borderRadius: '10px',
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                fontSize: '13px'
              }}>
                <ShieldAlert size={16} />
                <span style={{ flex: 1 }}>{errorMsg}</span>
                <button
                  type="button"
                  onClick={() => setErrorMsg(null)}
                  style={{ background: 'none', border: 'none', color: 'var(--loss)', cursor: 'pointer', fontSize: '12px', padding: '0 4px' }}
                >
                  ✕
                </button>
              </div>
            )}

            {/* HOLDINGS REVIEW SCREEN */}
            {isReviewing && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
                <div style={{
                  background: 'rgba(255, 255, 255, 0.01)',
                  border: '1px solid rgba(255, 255, 255, 0.06)',
                  borderRadius: '12px',
                  padding: '16px',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '12px'
                }}>
                  <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Sparkles size={16} color="var(--accent-cyan)" />
                    <span>Review Extracted Holdings</span>
                  </div>
                  <p style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: '1.4' }}>
                    Confirm the positions parsed from your document before synchronizing them with your dashboard.
                  </p>
                  
                  <div style={{
                    maxHeight: '260px',
                    overflowY: 'auto',
                    overflowX: 'auto',
                    border: '1px solid rgba(255, 255, 255, 0.06)',
                    borderRadius: '8px',
                    background: 'rgba(3, 7, 18, 0.2)'
                  }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '11px', textAlign: 'left' }}>
                      <thead>
                        <tr style={{ background: 'rgba(255,255,255,0.02)', borderBottom: '1px solid rgba(255,255,255,0.06)', color: 'var(--text-secondary)' }}>
                          <th style={{ padding: '8px 12px' }}>TICKER/ISIN</th>
                          <th style={{ padding: '8px 12px' }}>NAME</th>
                          <th style={{ padding: '8px 12px', textAlign: 'right' }}>QTY</th>
                          <th style={{ padding: '8px 12px', textAlign: 'right' }}>VALUE</th>
                          <th style={{ padding: '8px 12px', textAlign: 'right' }}>CONF.</th>
                        </tr>
                      </thead>
                      <tbody>
                        {reviewPositions.map((pos, idx) => (
                          <tr key={idx} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', color: 'var(--text-primary)' }}>
                            <td style={{ padding: '8px 12px', fontWeight: 600 }}>{pos.symbol || pos.isin || 'UNKNOWN'}</td>
                            <td style={{ padding: '8px 12px', color: 'var(--text-secondary)' }}>{pos.name || ''}</td>
                            <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>{Number(pos.quantity || 0).toLocaleString('en-IN')}</td>
                            <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>
                              ₹{Number(pos.market_value || 0).toLocaleString('en-IN')}
                            </td>
                            <td style={{ padding: '8px 12px', textAlign: 'right', color: pos.confidence > 0.8 ? 'var(--profit)' : 'var(--accent-orange)' }}>
                              {Math.round(Number(pos.confidence || 0) * 100)}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '12px' }}>
                  <button
                    type="button"
                    onClick={handleCancelReview}
                    style={{ flex: 1, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleConfirmReview}
                    disabled={isSubmittingReview || reviewPositions.length === 0}
                    className="primary"
                    style={{ flex: 1, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                  >
                    {isSubmittingReview ? (
                      <>
                        <Loader2 size={14} className="animate-spin-custom" />
                        Syncing...
                      </>
                    ) : (
                      <>
                        Sync Portfolio Mirror
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}

            {/* PASSWORD INPUT SCREEN */}
            {showPasswordInput && pendingFile && !isReviewing && (
              <div style={{
                background: 'rgba(3, 7, 18, 0.4)',
                border: '1px solid rgba(255, 255, 255, 0.06)',
                borderRadius: '16px',
                padding: '24px',
                display: 'flex',
                flexDirection: 'column',
                gap: '16px',
                textAlign: 'center'
              }}>
                <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  Password Required
                </h3>
                <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  The file "{pendingFile.name}" is password protected (e.g. eCAS PDF). Please enter the password to parse:
                </p>
                <input
                  type="password"
                  placeholder="eCAS / File Password"
                  value={pdfPassword}
                  onChange={(e) => setPdfPassword(e.target.value)}
                  style={{
                    fontSize: '14px',
                    padding: '10px 12px',
                    textAlign: 'center',
                    background: 'rgba(255, 255, 255, 0.02)',
                    border: '1px solid rgba(255, 255, 255, 0.1)',
                    borderRadius: '8px',
                    color: 'var(--text-primary)',
                    outline: 'none',
                    width: '100%'
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      startRealUpload(pendingFile, pdfPassword);
                    }
                  }}
                />
                <div style={{ display: 'flex', gap: '10px', marginTop: '4px' }}>
                  <button
                    type="button"
                    onClick={() => {
                      setShowPasswordInput(false);
                      setPendingFile(null);
                      setPdfPassword('');
                    }}
                    style={{ flex: 1, padding: '10px', fontSize: '12px' }}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={() => startRealUpload(pendingFile, pdfPassword)}
                    className="primary"
                    style={{ flex: 1, padding: '10px', fontSize: '12px' }}
                  >
                    Parse Document
                  </button>
                </div>
              </div>
            )}

            {/* DRAG AND DROP FILE ZONE */}
            {!isReviewing && !showPasswordInput && !isParsing && portfolio.length === 0 && (
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
                    Drag & drop your statement or screenshot here
                  </span>
                  <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                    Supports PDF, Excel, CSV or broker screenshot image
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

            {/* PARSING STEP LOGS */}
            {isParsing && !isReviewing && !showPasswordInput && (
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
                    <span>{parseStep >= 2 ? '✓ COMPLETE' : parseStep >= 1 ? '● RUNNING' : '○ QUEUED'}</span>
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

            {/* PREVIEW COMPLETED HOLDINGS */}
            {!isParsing && !isReviewing && !showPasswordInput && portfolio.length > 0 && (
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
                  onClick={() => { setPortfolio([]); setUploadedFileName(''); setErrorMsg(null); }}
                  style={{ color: 'var(--loss)', alignSelf: 'flex-start', fontSize: '11px', padding: '0', background: 'none', border: 'none' }}
                >
                  Reset & Upload Another Statement
                </button>
              </div>
            )}

            {/* Navigation buttons - only show when not in review/password mode */}
            {!isReviewing && !showPasswordInput && (
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
            )}
          </div>
        )}

        {/* STEP 3: WATCHLIST SELECTION */}
        {step === 3 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
            <div style={{ textAlign: 'center' }}>
              <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-primary)' }}>Build Your Opportunity Radar</h2>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>Add the stocks you are watching. Arthik will track earnings dates, run valuation screens, and alert you before the crowd moves.</p>
            </div>

            {/* Custom Input Form with Autocomplete Suggestions */}
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

              {/* Suggestions Dropdown */}
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
                  {suggestions.map((item, idx) => {
                    const isAlreadyAdded = watchlist.includes(item.symbol);
                    return (
                      <div
                        key={`${item.symbol}-${idx}`}
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
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = 'rgba(56, 189, 248, 0.06)';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = 'transparent';
                        }}
                      >
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', textAlign: 'left', overflow: 'hidden' }}>
                          <span style={{ fontSize: '12px', fontWeight: 700, color: 'var(--text-primary)' }}>
                            {item.symbol}
                          </span>
                          <span style={{ fontSize: '10px', color: 'var(--text-secondary)', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap', maxWidth: '300px' }}>
                            {item.name}
                          </span>
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
                          }}>
                            {item.type}
                          </span>
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

        {/* STEP 4: MEET ARTHIK */}
        {step === 4 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
            <div style={{ textAlign: 'center' }}>
              <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-primary)' }}>Your Edge Is Live. Deploy It.</h2>
              <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>Arthik is calibrated on your risk profile, portfolio, and watchlist. Ask your first question. Get institutional-grade analysis in 8 seconds.</p>
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
                <span style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>Arthik · Online</span>
                <span className="badge badge-success" style={{ fontSize: '10px', alignSelf: 'center' }}>Status: Live</span>
              </div>

              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                "I do not do hope. I do numbers. I have indexed your portfolio against 850+ Indian corporates, real-time NSE feeds, and every quarterly filing available. Ask me anything about your book, a ticker, or the tape. Let's find where the market got it wrong today."
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
                Launch Your Edge <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
export default Onboarding;

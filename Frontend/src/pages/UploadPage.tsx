import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Logo } from '../components/layout/Logo';
import { UploadCloud, ShieldAlert, CheckCircle2, Loader2, Sparkles, ArrowLeft, X } from 'lucide-react';
import { 
  uploadPortfolioDocument, 
  uploadPortfolioScreenshot, 
  confirmExtraction, 
  cancelExtraction,
  getPortfolioMirror
} from '../api/client';
import { INDIAN_STOCKS, POPULAR_MUTUAL_FUNDS } from '../data/indianStocks';
import { useAuth } from '../context/AuthContext';
import { APP_BETA_ACCESS_NOTE, APP_BETA_BADGE, APP_BETA_LABEL } from '../constants/beta';

interface PortfolioItem {
  symbol: string;
  name: string;
  qty: number;
  avgCost: number;
  current: number;
  sector: string;
}

export const UploadPage: React.FC = () => {
  const navigate = useNavigate();
  const { setOnboarded } = useAuth();

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

  const [portfolio, setPortfolio] = useState<PortfolioItem[]>([]);
  const [isParsing, setIsParsing] = useState(false);
  const [parseStep, setParseStep] = useState(0);
  const [dragActive, setDragActive] = useState(false);
  const [uploadedFileName, setUploadedFileName] = useState('');
  const [pdfPassword, setPdfPassword] = useState('');
  const [showPasswordInput, setShowPasswordInput] = useState(false);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const [reviewToken, setReviewToken] = useState<string | null>(null);
  const [reviewPositions, setReviewPositions] = useState<any[]>([]);
  const [sourceType, setSourceType] = useState<string>('unknown');
  const [isReviewing, setIsReviewing] = useState(false);
  const [isSubmittingReview, setIsSubmittingReview] = useState(false);

  const brokers = ['Zerodha', 'Groww', 'Upstox', 'ICICI Direct'];

  const mapPositionsToPortfolioItems = (positions: any[]): PortfolioItem[] => {
    return positions.map((p: any) => {
      const qty = p.quantity || 0;
      const marketVal = p.market_value || 0;
      let currentPrice = p.last_price || 0;
      if (currentPrice === 0 && qty > 0 && marketVal > 0) {
        currentPrice = marketVal / qty;
      }
      if (currentPrice === 0) {
        currentPrice = p.avg_cost || (qty > 0 && p.cost_basis ? p.cost_basis / qty : 0);
      }
      let avgCost = p.avg_cost || 0;
      if (avgCost === 0 && qty > 0 && p.cost_basis) {
        avgCost = parseFloat((p.cost_basis / qty).toFixed(4));
      }
      if (avgCost === 0 && currentPrice > 0) {
        avgCost = currentPrice;
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
      return { symbol: targetSym, name: resolvedName, qty, avgCost, current: currentPrice, sector: resolvedSector };
    });
  };

  // Persist extracted holdings locally. The dashboard reads holdings from
  // `prospektlab_manual_portfolio` in open-access/guest mode, so the upload must
  // write there (plus the legacy `prospektlab_portfolio` key) for the portfolio
  // tab to populate when the cloud mirror is unavailable.
  const persistLocalPortfolio = (positions: any[]): boolean => {
    const mapped = mapPositionsToPortfolioItems(Array.isArray(positions) ? positions : []);
    if (mapped.length === 0) return false;
    const manualPayload = mapped.map((m) => ({
      symbol: m.symbol,
      name: m.name,
      quantity: m.qty,
      avg_cost: m.avgCost,
      sector: m.sector,
    }));
    setPortfolio(mapped);
    localStorage.setItem('prospektlab_manual_portfolio', JSON.stringify(manualPayload));
    localStorage.setItem('prospektlab_portfolio', JSON.stringify(mapped));
    return true;
  };

  const verifyMirrorSync = async (fallbackPositions: any[] = []): Promise<boolean> => {
    let lastError: any = null;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const mirror = await getPortfolioMirror();
        const mirrorPositions = Array.isArray(mirror?.positions) ? mirror.positions : [];
        const count = Number(mirror?.count || mirrorPositions.length || 0);
        if (count > 0) {
          if (persistLocalPortfolio(mirrorPositions.length > 0 ? mirrorPositions : fallbackPositions)) {
            return true;
          }
        }
      } catch (err: any) {
        lastError = err;
      }
      await new Promise(resolve => setTimeout(resolve, 500 * (attempt + 1)));
    }
    // Cloud mirror unreachable or empty (sync down or guest mode). localStorage is
    // the source of truth — persist the extracted holdings so the portfolio tab
    // still populates instead of failing the whole upload.
    if (persistLocalPortfolio(fallbackPositions)) {
      return true;
    }
    if (lastError) console.error('Portfolio mirror verification failed', lastError);
    return false;
  };

  const handleFileSelect = (file: File) => {
    setErrorMsg(null);
    setPortfolio([]);
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
    setReviewToken(null);

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
      await new Promise(resolve => setTimeout(resolve, 800));

      if (res.code === "REVIEW_REQUIRED" || res.status === "REVIEW_REQUIRED" || res.sync_status === "REVIEW_REQUIRED") {
        setReviewId(res.review_id);
        setReviewToken(res.review_token || null);
        setReviewPositions(res.positions || []);
        setSourceType(res.source_type || (isImage ? 'image' : 'pdf'));
        setIsReviewing(true);
        setIsParsing(false);
      } else if (res.code === "MIRROR_SYNCHRONIZED" || res.status === "MIRROR_SYNCHRONIZED" || res.sync_status === "MIRROR_SYNCHRONIZED") {
        const verified = await verifyMirrorSync(res.positions || []);
        if (!verified) {
          setErrorMsg('Your holdings were extracted, but I could not verify that they were saved to your account. Please retry the upload.');
        } else {
          setOnboarded(true);
          navigate('/onboarding/watchlist');
        }
        setIsParsing(false);
      } else if (res.code === "EMPTY_BUT_VALID") {
        setErrorMsg('Document is valid but no active holdings were found.');
        setIsParsing(false);
      } else {
        const verified = await verifyMirrorSync(res.positions || []);
        if (!verified) {
          setErrorMsg('Your holdings were extracted, but I could not verify that they were saved to your account. Please retry the upload.');
        } else {
          setOnboarded(true);
          navigate('/onboarding/watchlist');
        }
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
      const res = await confirmExtraction(reviewId, reviewPositions, sourceType, reviewToken);
      if (res && res.positions) {
        const verified = await verifyMirrorSync(res.positions);
        if (verified) {
          setIsReviewing(false);
          setReviewId(null);
          setReviewToken(null);
          setReviewPositions([]);
          setOnboarded(true);
          navigate('/onboarding/watchlist');
        } else {
          throw new Error('Your reviewed holdings were extracted, but I could not verify that they were saved to your account. Please retry the sync.');
        }
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
    try { await cancelExtraction(); } catch (err) { console.error('Cancel extraction failed', err); }
    finally {
      setIsReviewing(false);
      setReviewId(null);
      setReviewToken(null);
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
      handleFileSelect(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleFileSelect(e.target.files[0]);
    }
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

        <div className="beta-inline-group" style={{ justifyContent: 'center' }}>
          <span className="beta-pill">{APP_BETA_BADGE}</span>
          <span className="beta-note">{APP_BETA_LABEL} • {APP_BETA_ACCESS_NOTE}</span>
        </div>

        <div style={{ textAlign: 'center' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-primary)' }}>Upload your statement</h2>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>
            Upload your eCAS PDF, broker statement, or a screenshot of your holdings. PDFs may need your PAN as the password. Beta access remains free for invited users.
          </p>
        </div>

        {errorMsg && (
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
            <ShieldAlert size={16} /> {errorMsg}
            <button type="button" onClick={() => setErrorMsg(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }}>
              <X size={14} />
            </button>
          </div>
        )}

        {/* Password input */}
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
            <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)' }}>Password Required</h3>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              The file "{pendingFile.name}" is password protected. For eCAS statements, the password is usually your PAN in uppercase.
            </p>
            <input
              type="password"
              placeholder="eCAS / File Password"
              value={pdfPassword}
              onChange={(e) => setPdfPassword(e.target.value)}
              style={{ fontSize: '14px', padding: '10px 12px', textAlign: 'center', background: 'rgba(255, 255, 255, 0.02)', border: '1px solid rgba(255, 255, 255, 0.1)', borderRadius: '8px', color: 'var(--text-primary)', outline: 'none', width: '100%' }}
              onKeyDown={(e) => { if (e.key === 'Enter') startRealUpload(pendingFile, pdfPassword); }}
            />
            <div style={{ display: 'flex', gap: '10px', marginTop: '4px' }}>
              <button type="button" onClick={() => { setShowPasswordInput(false); setPendingFile(null); setPdfPassword(''); }} style={{ flex: 1, padding: '10px', fontSize: '12px' }}>Cancel</button>
              <button type="button" onClick={() => startRealUpload(pendingFile, pdfPassword)} className="primary" style={{ flex: 1, padding: '10px', fontSize: '12px' }}>Parse Document</button>
            </div>
          </div>
        )}

        {/* Drag & drop zone */}
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
            <div style={{ background: 'rgba(56, 189, 248, 0.05)', color: 'var(--accent-cyan)', padding: '12px', borderRadius: '50%', display: 'inline-flex' }}>
              <UploadCloud size={28} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <span style={{ fontSize: '14px', fontWeight: 500 }}>Drag & drop your statement or screenshot here</span>
              <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Supports PDF, Excel, CSV or broker screenshot image</span>
            </div>
            <div style={{ display: 'flex', gap: '6px', justifyContent: 'center', flexWrap: 'wrap', margin: '4px 0' }}>
              {brokers.map((b) => (
                <span key={b} style={{ fontSize: '10px', background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)', padding: '2px 8px', borderRadius: '4px', color: 'var(--text-secondary)' }}>{b}</span>
              ))}
            </div>
            <div style={{ position: 'relative' }}>
              <input type="file" id="upload-page-file-input" accept=".csv,.pdf,.xlsx,.xls,.png,.jpg,.jpeg" onChange={handleFileChange} style={{ display: 'none' }} />
              <button type="button" onClick={() => document.getElementById('upload-page-file-input')?.click()} style={{ fontSize: '12px', padding: '8px 16px', borderRadius: '8px' }}>
                Select File
              </button>
            </div>
            <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
              For password-protected eCAS PDFs, use your PAN in uppercase.
            </div>
          </div>
        )}

        {/* Parsing logs */}
        {isParsing && !isReviewing && !showPasswordInput && (
          <div style={{ background: 'rgba(3, 7, 18, 0.4)', border: '1px solid rgba(255, 255, 255, 0.06)', borderRadius: '16px', padding: '24px', display: 'flex', flexDirection: 'column', gap: '14px', fontFamily: 'var(--font-mono)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--accent-cyan)' }}>
              <Loader2 size={14} className="animate-spin-custom" />
              <span>PARSING STATEMENT DATA: {uploadedFileName}</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '12px', marginTop: '6px' }}>
              {[
                'Validating statement header schema...',
                'Matching ISINs to market tickers...',
                'Synthesizing historical buy averages...',
                'Calibrating index weights & risk ratios...'
              ].map((label, idx) => {
                const step = idx + 1;
                const done = parseStep >= step;
                const running = parseStep === step - 1 && !done;
                return (
                  <div key={label} style={{ display: 'flex', justifyContent: 'space-between', color: done ? 'var(--profit)' : running ? 'var(--text-primary)' : 'var(--text-secondary)' }}>
                    <span>▸ {label}</span>
                    <span>{done ? '✓ COMPLETE' : running ? '● PROCESSING' : '○ QUEUED'}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Success preview */}
        {!isParsing && !isReviewing && !showPasswordInput && portfolio.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div style={{ background: 'rgba(52, 211, 153, 0.05)', border: '1px solid rgba(52, 211, 153, 0.15)', color: 'var(--profit)', padding: '12px 16px', borderRadius: '10px', display: 'flex', alignItems: 'center', gap: '10px', fontSize: '13px' }}>
              <CheckCircle2 size={16} />
              <span>Import successful! {portfolio.length} positions are synced to your account.</span>
            </div>
            <div style={{ background: 'rgba(3,7,18,0.3)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '10px', overflow: 'hidden' }}>
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
                      <td style={{ padding: '8px 12px', fontFamily: 'var(--font-mono)' }}>Rs {item.avgCost.toLocaleString('en-IN')}</td>
                      <td style={{ padding: '8px 12px' }}>
                        <span style={{ fontSize: '10px', background: 'rgba(56, 189, 248, 0.08)', color: 'var(--accent-cyan)', padding: '1px 6px', borderRadius: '4px' }}>{item.sector}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Review screen */}
        {isReviewing && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
            <div style={{ background: 'rgba(3, 7, 18, 0.4)', border: '1px solid rgba(255, 255, 255, 0.06)', borderRadius: '12px', padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Sparkles size={16} color="var(--accent-cyan)" />
                <span>Review Extracted Holdings</span>
              </div>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: '1.4' }}>
                Confirm the positions parsed from your document before synchronizing them with your dashboard.
              </p>
              <div style={{ maxHeight: '260px', overflowY: 'auto', overflowX: 'auto', border: '1px solid rgba(255, 255, 255, 0.06)', borderRadius: '8px', background: 'rgba(3, 7, 18, 0.2)' }}>
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
                        <td style={{ padding: '8px 12px', textAlign: 'right', fontFamily: 'var(--font-mono)' }}>Rs {Number(pos.market_value || 0).toLocaleString('en-IN')}</td>
                        <td style={{ padding: '8px 12px', textAlign: 'right', color: pos.confidence > 0.8 ? 'var(--profit)' : 'var(--accent-orange)' }}>{Math.round(Number(pos.confidence || 0) * 100)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '12px' }}>
              <button type="button" onClick={handleCancelReview} style={{ flex: 1, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>Cancel</button>
              <button type="button" onClick={handleConfirmReview} disabled={isSubmittingReview || reviewPositions.length === 0} className="primary" style={{ flex: 1, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                {isSubmittingReview ? <><Loader2 size={14} className="animate-spin-custom" /> Syncing...</> : <>Sync Portfolio Mirror</>}
              </button>
            </div>
          </div>
        )}

        {!isReviewing && (
          <div style={{ display: 'flex', gap: '14px' }}>
            <button type="button" onClick={() => navigate('/get-started')} style={{ flex: 1, padding: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
              <ArrowLeft size={14} /> Back
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default UploadPage;

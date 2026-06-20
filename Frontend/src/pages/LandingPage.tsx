import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Brain, Star, ArrowRight, Zap, Shield, TrendingUp,
  AlertTriangle, BarChart3, CheckCircle, MessageSquare,
  FileText, ChevronDown, Lock, Trophy, X, ChevronRight,
  Activity, Users, Quote
} from 'lucide-react';
import { Logo } from '../components/layout/Logo';
import { useAuth } from '../context/AuthContext';

/* ─────────────────────────────────────────────
   DATA
───────────────────────────────────────────── */
const ACTIVITY_FEED = [
  { avatar: 'RK', name: 'Rahul K.', city: 'Mumbai', action: 'flagged a promoter pledge risk on ASIANPAINT', time: '2 min ago', color: '#38BDF8' },
  { avatar: 'PV', name: 'Priya V.', city: 'Bengaluru', action: 'ran DCF on RELIANCE. Found 12.3% upside.', time: '4 min ago', color: '#818CF8' },
  { avatar: 'AS', name: 'Ankit S.', city: 'Hyderabad', action: 'compared TCS vs INFY. Rebalanced ₹8L.', time: '7 min ago', color: '#34D399' },
  { avatar: 'DM', name: 'Deepa M.', city: 'Chennai', action: "avoided a likely default. Altman Z flagged it.", time: '11 min ago', color: '#A78BFA' },
  { avatar: 'VR', name: 'Vikram R.', city: 'Pune', action: 'generated a deep research memo on HDFCBANK', time: '15 min ago', color: '#F59E0B' },
  { avatar: 'SN', name: 'Sneha N.', city: 'Delhi', action: 'spotted a ₹2.3L saving before Asian Paints dropped', time: '18 min ago', color: '#38BDF8' },
];

const REVIEWS = [
  { name: 'CA, Mumbai', location: 'Mumbai', role: 'CA & Part-time Investor', avatar: 'AM', stars: 5, title: 'Caught the Asian Paints drop before it happened', body: "Was about to add Asian Paints at ₹2,850. Arthik flagged the promoter pledge increase. I held off. Stock dropped 14% in three weeks. That call saved me ₹2.3 Lakhs on a ₹16L position.", result: 'Saved ₹2.3L in 3 weeks' },
  { name: 'Tech professional, Bengaluru', location: 'Bengaluru', role: 'Tech Lead, Flipkart', avatar: 'PK', stars: 5, title: 'Replaced my broker research entirely', body: "Broker's PDF said BUY on everything. Arthik gave me a DCF on TCS in eight seconds. I changed the growth rate. Fair value updated in real time. Cancelled my ₹18K/yr subscription.", result: 'Cancelled ₹18K/yr broker research' },
  { name: 'Business owner, Delhi', location: 'New Delhi', role: 'Business Owner', avatar: 'VG', stars: 4, title: 'Stopped losing money on Telegram tips', body: "Lost ₹4.8L over 18 months chasing tips. Arthik shows me actual numbers. Piotroski. Debt ratios. Cash flows. Portfolio up 22% in eight months. I understand every position I hold.", result: 'Portfolio up 22% in 8 months' },
  { name: 'Dentist, Chennai', location: 'Chennai', role: 'Dentist & HNI Investor', avatar: 'SI', stars: 5, title: 'Altman Z saved my capital', body: "Arthik's Altman Z-Score flagged concentrated wholesale borrowing plus declining interest coverage. I passed. The company defaulted eleven weeks later. Paid for itself 100x in one decision.", result: 'Avoided a likely default' },
  { name: 'Engineer, Jaipur', location: 'Jaipur', role: 'Civil Engineer', avatar: 'MT', stars: 5, title: 'Found a 34% margin-of-safety stock', body: "My advisor had me in 12 overlapping mutual funds. Arthik surfaced a small-cap. 0.6x book. Zero debt. 18% ROE. Bought at ₹142. It's at ₹208 now.", result: '₹142 → ₹208 in 5 months' },
  { name: 'Small business owner, Kochi', location: 'Kochi', role: 'Small Business Owner', avatar: 'KN', stars: 4, title: 'It took 20 minutes to trust it. Now I can\'t stop.', body: "First time I asked 'Should I average down on Zomato?' Arthik gave me burn-rate analysis, competitive moat, and Graham valuation in one response. Goldman Sachs in my pocket.", result: 'First good Zomato call in 2 years' },
];

const FAQS = [
  { q: "Is this SEBI-registered investment advice?", a: "No. ProspektLab is an analytical tool, not a SEBI-registered advisor. Arthik pulls public data and runs standard models. You make the call. We recommend a SEBI-registered advisor for final decisions." },
  { q: "How is this different from ChatGPT?", a: "ChatGPT trains on 2023 data. Arthik pulls live NSE feeds. ChatGPT gives opinions. Arthik shows you the math, with editable assumptions. Also: ChatGPT costs ₹1,650/month. Arthik's free tier is actually useful." },
  { q: "What's the catch with the free tier?", a: "No catch. 20 queries per day. Live data. Basic valuations. Portfolio tracking. The free tier saves most users from one bad trade in week one. After that, ₹499/month feels cheap." },
  { q: "How accurate are the models?", a: "Same models as sell-side research. Two-stage DCF. Altman Z. Piotroski F-Score. Graham formula. The difference: every assumption is visible. Every number is editable. Broker research hides the math. We show it." },
  { q: "Where is my portfolio data stored?", a: "In your browser. Not on our servers. We never see your holdings. Clear your cache, you re-import. That's the trade-off for real privacy." },
  { q: "Which brokers work for import?", a: "Zerodha, Groww, Upstox, ICICI Direct, and anything that exports a standard trade book CSV or PDF. If your broker gives you a statement, Arthik can read it." },
];

/* ─────────────────────────────────────────────
   ANIMATED COUNTER
───────────────────────────────────────────── */
const AnimatedCounter: React.FC<{ target: number; suffix?: string; prefix?: string }> = ({ target, suffix = '', prefix = '' }) => {
  const [count, setCount] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);
  const animated = useRef(false);
  useEffect(() => {
    const obs = new IntersectionObserver(entries => {
      if (!entries[0].isIntersecting || animated.current) return;
      animated.current = true;
      const t0 = performance.now();
      const tick = (now: number) => {
        const p = Math.min((now - t0) / 1600, 1);
        const ease = 1 - Math.pow(1 - p, 3);
        setCount(Math.floor(ease * target));
        if (p < 1) requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }, { threshold: 0.5 });
    if (ref.current) obs.observe(ref.current);
    return () => obs.disconnect();
  }, [target]);
  return <span ref={ref}>{prefix}{count.toLocaleString('en-IN')}{suffix}</span>;
};

/* ─────────────────────────────────────────────
   AUTO PERSONALIZATION (no user input)
───────────────────────────────────────────── */
type Context = {
  greeting: string;
  marketStatus: 'open' | 'pre' | 'post' | 'weekend';
  marketLine: string;
  visitCount: number;
  visitorLine: string;
  refSource: string;
  timeOfDay: 'dawn' | 'morning' | 'afternoon' | 'evening' | 'night';
};

const getContext = (): Context => {
  const now = new Date();
  const hour = now.getHours();
  const minutes = now.getMinutes();
  const day = now.getDay();
  const isWeekend = day === 0 || day === 6;
  const minutesNow = hour * 60 + minutes;
  const marketOpen = 9 * 60 + 15;
  const marketClose = 15 * 60 + 30;

  let marketStatus: Context['marketStatus'] = 'post';
  let marketLine = '';
  if (isWeekend) {
    marketStatus = 'weekend';
    marketLine = day === 0
      ? "Markets closed. Sunday is when the smart money plans the week."
      : "Markets closed. Saturday is for thinking, not reacting.";
  } else if (minutesNow < marketOpen) {
    marketStatus = 'pre';
    const mins = marketOpen - minutesNow;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    marketLine = `Markets open in ${h > 0 ? h + 'h ' : ''}${m}m. Prepare with edge, not hope.`;
  } else if (minutesNow >= marketOpen && minutesNow <= marketClose) {
    marketStatus = 'open';
    const mins = marketClose - minutesNow;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    marketLine = `Markets are live. ${h > 0 ? h + 'h ' : ''}${m}m to close. Every minute decides something.`;
  } else {
    marketStatus = 'post';
    marketLine = "Markets closed. Tomorrow's moves are being decided right now.";
  }

  let timeOfDay: Context['timeOfDay'] = 'afternoon';
  let greeting = '';
  if (hour < 5) { timeOfDay = 'night'; greeting = "Up at 3 AM researching. We see you. The system isn't built for you."; }
  else if (hour < 12) { timeOfDay = 'morning'; greeting = 'Good morning.'; }
  else if (hour < 17) { timeOfDay = 'afternoon'; greeting = 'Good afternoon.'; }
  else if (hour < 21) { timeOfDay = 'evening'; greeting = 'Good evening.'; }
  else { timeOfDay = 'night'; greeting = "Still up. Still researching. Still alone in this."; }

  let visitCount = 1;
  if (typeof window !== 'undefined') {
    visitCount = parseInt(localStorage.getItem('pl_visits') || '0', 10) + 1;
  }
  let visitorLine = '';
  if (visitCount === 2) visitorLine = "Back again. We thought you would be.";
  else if (visitCount === 3) visitorLine = "Three visits. Something's keeping you here.";
  else if (visitCount >= 4 && visitCount < 8) visitorLine = `Visit #${visitCount}. Stop looking. Start using.`;
  else if (visitCount >= 8) visitorLine = `${visitCount} visits. The free tier is one click away. You know this.`;

  let refSource = '';
  if (typeof document !== 'undefined') {
    const ref = (document.referrer || '').toLowerCase();
    if (ref.includes('twitter') || ref.includes('x.com')) refSource = 'X';
    else if (ref.includes('linkedin')) refSource = 'LinkedIn';
    else if (ref.includes('reddit')) refSource = 'Reddit';
    else if (ref.includes('youtube') || ref.includes('youtu.be')) refSource = 'YouTube';
    else if (ref.includes('whatsapp')) refSource = 'WhatsApp';
    else if (ref.includes('google') || ref.includes('bing') || ref.includes('duckduckgo')) refSource = 'Search';
  }

  return { greeting, marketStatus, marketLine, visitCount, visitorLine, refSource, timeOfDay };
};

/* ─────────────────────────────────────────────
   MAIN COMPONENT
───────────────────────────────────────────── */
export const LandingPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { isAuthenticated, onboarded } = useAuth();

  /* URL/localStorage personalization (existing) */
  const urlName = searchParams.get('name') || searchParams.get('investor') || searchParams.get('ref') || '';
  const savedName = typeof window !== 'undefined' ? (localStorage.getItem('prospektlab_username') || '') : '';
  const personalName = urlName || savedName;
  const PN = personalName ? personalName.charAt(0).toUpperCase() + personalName.slice(1) : '';
  useEffect(() => { if (urlName) localStorage.setItem('prospektlab_username', urlName); }, [urlName]);

  /* AUTOMATIC personalization (no input required) */
  const ctx = useMemo(() => getContext(), []);
  useEffect(() => {
    if (typeof window !== 'undefined') localStorage.setItem('pl_visits', String(ctx.visitCount));
  }, [ctx.visitCount]);

  /* UI state */
  const [showStickyBar, setShowStickyBar] = useState(false);
  const [activeReview, setActiveReview] = useState(0);
  const [toastIdx, setToastIdx] = useState(0);
  const [showToast, setShowToast] = useState(true);
  const [openFaq, setOpenFaq] = useState<number | null>(0);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const handle = () => setShowStickyBar(window.scrollY > 420);
    window.addEventListener('scroll', handle, { passive: true });
    return () => window.removeEventListener('scroll', handle);
  }, []);

  useEffect(() => {
    const id = setInterval(() => {
      setShowToast(false);
      setTimeout(() => {
        setToastIdx(i => (i + 1) % ACTIVITY_FEED.length);
        setShowToast(true);
      }, 400);
    }, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const id = setInterval(() => setActiveReview(i => (i + 1) % REVIEWS.length), 6000);
    return () => clearInterval(id);
  }, []);

  const scrollTo = useCallback((id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setMobileMenuOpen(false);
  }, []);

  const ctaTarget = isAuthenticated && onboarded ? '/dashboard' : '/get-started';
  const handleCTA = () => navigate(ctaTarget);
  const handleAuthAction = () => navigate('/dashboard');

  const toast = ACTIVITY_FEED[toastIdx];

  /* Choose the contextual hero line (priority: name > visitor > referrer > market > time) */
  const heroContextLine =
    ctx.visitorLine ||
    (ctx.refSource ? `Coming in from ${ctx.refSource}. The smart money found us the same way.` : '') ||
    ctx.marketLine;

  /* Status dot color based on market state */
  const marketDot = ctx.marketStatus === 'open' ? 'var(--profit)' : ctx.marketStatus === 'weekend' ? 'var(--text-muted)' : '#fbbf24';

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-deep)', overflowX: 'hidden', position: 'relative' }}>

      {/* ─── Global CSS ─── */}
      <style>{`
        @keyframes orbFloat { 0%,100% { transform: translate(0,0) scale(1); } 33% { transform: translate(30px,-20px) scale(1.05); } 66% { transform: translate(-20px,15px) scale(0.97); } }
        @keyframes shimmer { 0% { background-position: -200% center; } 100% { background-position: 200% center; } }
        @keyframes toastSlide { from { opacity:0; transform: translateX(40px) scale(0.95); } to { opacity:1; transform: translateX(0) scale(1); } }
        @keyframes barUp { from { transform: translateY(100%); opacity:0; } to { transform: translateY(0); opacity:1; } }
        @keyframes reviewFade { from { opacity:0; transform:translateY(8px); } to { opacity:1; transform:translateY(0); } }
        @keyframes pulse2 { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
        @keyframes glowPulse { 0%,100% { box-shadow: 0 16px 44px rgba(37,99,235,0.26), inset 0 1px 0 rgba(255,255,255,0.55); } 50% { box-shadow: 0 22px 60px rgba(37,99,235,0.34), inset 0 1px 0 rgba(255,255,255,0.68); } }
        .cta-shimmer { background: linear-gradient(135deg, #F8FBFF 0%, #93C5FD 42%, #2563EB 100%); background-size: auto; animation: none; }
        .cta-shimmer:hover { background: linear-gradient(135deg, #FFFFFF 0%, #BFDBFE 42%, #2563EB 100%); filter: brightness(1.04); transform: translateY(-1px); }
        .cta-shimmer:active { transform: scale(0.98); }
        .card-hover { transition: border-color 0.2s, transform 0.2s, box-shadow 0.2s; }
        .card-hover:hover { border-color: rgba(147,197,253,0.3) !important; transform: translateY(-2px); box-shadow: var(--edge-glow), var(--blue-aura); }
        #hero::before { content:''; position:absolute; left:50%; top:44px; width:min(760px,90vw); height:min(760px,90vw); transform:translateX(-50%); border-radius:999px; background:radial-gradient(circle, rgba(37,99,235,0.12), transparent 62%); pointer-events:none; }
        .mobile-menu-btn { display: none; }
        @media (max-width: 768px) {
          .d-none-m { display: none !important; }
          .hero-split { flex-direction: column !important; }
          .stats-4col { grid-template-columns: repeat(2,1fr) !important; }
          .pain-3col, .feat-3col, .ba-2col, .rev-grid { grid-template-columns: 1fr !important; }
          .mobile-menu-btn { display: flex !important; align-items: center; justify-content: center; }
          .quote-block h3 { font-size: 22px !important; }
          .landing-toast { max-width: 260px !important; right: 8px !important; top: 64px !important; }
          .sticky-cta-bar { flex-direction: column !important; padding: 12px 16px !important; gap: 10px !important; align-items: flex-start !important; }
          .active-review-card { flex-direction: column !important; align-items: center !important; text-align: center !important; }
        }
        @media (max-width: 480px) {
          .stats-4col { grid-template-columns: 1fr !important; }
          .stats-4col > div > div:first-child { font-size: 24px !important; }
          .hero-split { gap: 28px !important; }
          .sticky-cta-bar { padding: 10px 12px !important; }
          .sticky-cta-bar button { width: 100% !important; text-align: center !important; }
          .guarantee-items { flex-direction: column !important; align-items: center !important; gap: 12px !important; }
        }
      `}</style>

      {/* ─── AMBIENT ORBS ─── */}
      <div style={{ position:'fixed', inset:0, pointerEvents:'none', zIndex:0, overflow:'hidden' }}>
        <div style={{ position:'absolute', width:760, height:760, borderRadius:'50%', background:'radial-gradient(circle, rgba(37,99,235,0.14) 0%, transparent 70%)', top:'-18%', left:'-12%', animation:'orbFloat 22s ease-in-out infinite' }} />
        <div style={{ position:'absolute', width:640, height:640, borderRadius:'50%', background:'radial-gradient(circle, rgba(96,165,250,0.10) 0%, transparent 72%)', bottom:'4%', right:'-9%', animation:'orbFloat 26s ease-in-out infinite reverse' }} />
        <div style={{ position:'absolute', width:440, height:440, borderRadius:'50%', background:'radial-gradient(circle, rgba(139,92,246,0.06) 0%, transparent 72%)', top:'38%', left:'46%', animation:'orbFloat 18s ease-in-out infinite 3s' }} />
      </div>

      {/* ─── ACTIVITY TOAST ─── */}
      {showToast && (
        <div className="landing-toast" style={{ position:'fixed', top:80, right:20, zIndex:999, maxWidth:320, background:'rgba(15,23,42,0.95)', backdropFilter:'blur(20px)', border:`1px solid ${toast.color}33`, borderRadius:14, padding:'12px 14px', display:'flex', alignItems:'flex-start', gap:10, animation:'toastSlide 0.4s ease forwards', boxShadow:`0 8px 32px rgba(0,0,0,0.4), 0 0 0 1px ${toast.color}22` }}>
          <div style={{ width:32, height:32, borderRadius:'50%', background:`${toast.color}22`, border:`1px solid ${toast.color}44`, display:'flex', alignItems:'center', justifyContent:'center', fontSize:11, fontWeight:700, color:toast.color, flexShrink:0 }}>{toast.avatar}</div>
          <div style={{ flex:1, minWidth:0 }}>
            <div style={{ fontSize:12, fontWeight:600, color:'var(--text-primary)', marginBottom:2 }}><span style={{ color:toast.color }}>{toast.name}</span> from {toast.city}</div>
            <div style={{ fontSize:11, color:'var(--text-secondary)', lineHeight:1.4 }}>{toast.action}</div>
            <div style={{ fontSize:10, color:'var(--text-muted)', marginTop:4, display:'flex', alignItems:'center', gap:4 }}>
              <span style={{ width:5, height:5, borderRadius:'50%', background:'var(--profit)', animation:'pulse2 2s infinite', display:'inline-block' }} />
              {toast.time}
            </div>
          </div>
          <button onClick={() => setShowToast(false)} style={{ background:'none', border:'none', color:'var(--text-muted)', cursor:'pointer', padding:0, flexShrink:0 }}><X size={12} /></button>
        </div>
      )}

      {/* ─── STICKY CTA BAR ─── */}
      {showStickyBar && (
        <div className="sticky-cta-bar" style={{ position:'fixed', bottom:0, left:0, right:0, zIndex:100, background:'rgba(3,7,18,0.95)', backdropFilter:'blur(20px)', borderTop:'1px solid var(--border-subtle)', padding:'14px 24px', display:'flex', alignItems:'center', justifyContent:'space-between', gap:16, animation:'barUp 0.35s ease forwards', flexWrap:'wrap' }}>
          <div style={{ display:'flex', alignItems:'center', gap:12 }}>
            <div style={{ background:'var(--gradient-brand)', borderRadius:8, padding:6, display:'flex' }}><Brain size={16} color="#0f172a" /></div>
            <div>
              <div style={{ fontSize:14, fontWeight:700, color:'var(--text-primary)' }}>{PN ? `${PN}, your unfair advantage is one click away.` : 'Your unfair advantage is one click away.'}</div>
              <div style={{ fontSize:11, color:'var(--text-muted)' }}>Free forever tier. No card. 30 second setup.</div>
            </div>
          </div>
          <button onClick={handleCTA} className="cta-shimmer" style={{ color:'#0f172a', border:'none', padding:'10px 24px', borderRadius:10, fontSize:14, fontWeight:700, cursor:'pointer', flexShrink:0 }}>
            Claim it →
          </button>
        </div>
      )}

      {/* ─── NAVBAR ─── */}
      <nav style={{ position:'sticky', top:0, zIndex:50, background:'rgba(3,7,18,0.88)', backdropFilter:'blur(20px)', borderBottom:'1px solid var(--border-subtle)' }}>
        <div style={{ maxWidth:1200, margin:'0 auto', padding:'13px 24px', display:'flex', alignItems:'center', justifyContent:'space-between', gap:16 }}>
          <div onClick={() => scrollTo('hero')} style={{ display:'flex', alignItems:'center', gap:10, cursor:'pointer', flexShrink:0 }}>
            <Logo size={30} />
            <span style={{ fontWeight:800, fontSize:17, letterSpacing:'0.08em', textTransform:'uppercase' }} className="text-gradient">Prospekt Lab</span>
          </div>

          <div className="d-none-m" style={{ display:'flex', gap:6, alignItems:'center' }}>
            {[['hero','Home'],['pain','The Setup'],['mechanism','The Edge'],['reviews','Receipts'],['faq','FAQ']].map(([id,label]) => (
              <button key={id} onClick={() => scrollTo(id)} style={{ background:'none', border:'none', color:'var(--text-secondary)', fontSize:13, fontWeight:500, cursor:'pointer', padding:'6px 12px', borderRadius:8, transition:'all 0.15s' }}
                onMouseEnter={e => { e.currentTarget.style.color = 'var(--text-primary)'; e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; }}
                onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-secondary)'; e.currentTarget.style.background = 'none'; }}>
                {label}
              </button>
            ))}
            <button onClick={() => navigate('/contact')} style={{ background:'none', border:'none', color:'var(--text-secondary)', fontSize:13, fontWeight:500, cursor:'pointer', padding:'6px 12px', borderRadius:8, transition:'all 0.15s' }}
              onMouseEnter={e => { e.currentTarget.style.color = 'var(--text-primary)'; e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; }}
              onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-secondary)'; e.currentTarget.style.background = 'none'; }}>
              Contact
            </button>
          </div>

          <div style={{ display:'flex', gap:10, alignItems:'center', flexShrink:0 }}>
            {/* Live market status pill (auto-personalized) */}
            <div className="d-none-m" style={{ display:'flex', alignItems:'center', gap:8, background:'rgba(15,23,42,0.6)', border:'1px solid var(--border-subtle)', borderRadius:999, padding:'5px 12px' }}>
              <span style={{ width:6, height:6, borderRadius:'50%', background:marketDot, animation:'pulse2 2s infinite', display:'inline-block' }} />
              <span style={{ fontSize:11, color:'var(--text-secondary)', fontWeight:600, letterSpacing:'0.03em' }}>
                {ctx.marketStatus === 'open' ? 'NSE LIVE' : ctx.marketStatus === 'weekend' ? 'NSE CLOSED' : ctx.marketStatus === 'pre' ? 'OPENING SOON' : 'AFTER HOURS'}
              </span>
            </div>
            <button onClick={() => navigate('/pricing')} className="d-none-m" style={{ background:'none', border:'1px solid var(--border-subtle)', color:'var(--text-primary)', padding:'7px 16px', borderRadius:8, fontSize:13, cursor:'pointer', transition:'all 0.15s' }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent-cyan)'; e.currentTarget.style.color = 'var(--accent-cyan)'; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border-subtle)'; e.currentTarget.style.color = 'var(--text-primary)'; }}>
              Pricing
            </button>
            <button onClick={handleAuthAction} className="d-none-m" style={{ background:'none', border:'1px solid var(--border-subtle)', color:'var(--text-primary)', padding:'7px 16px', borderRadius:8, fontSize:13, cursor:'pointer', transition:'all 0.15s' }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent-cyan)'; e.currentTarget.style.color = 'var(--accent-cyan)'; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border-subtle)'; e.currentTarget.style.color = 'var(--text-primary)'; }}>
              Dashboard
            </button>
            <button onClick={handleCTA} className="cta-shimmer" style={{ color:'#0f172a', border:'none', padding:'8px 18px', borderRadius:8, fontSize:13, fontWeight:700, cursor:'pointer' }}>
              Start Free →
            </button>
            <button className="mobile-menu-btn" onClick={() => setMobileMenuOpen(v => !v)} style={{ background:'none', border:'1px solid var(--border-subtle)', color:'var(--text-primary)', padding:'7px', borderRadius:8, cursor:'pointer' }}>
              <ChevronDown size={16} style={{ transform: mobileMenuOpen ? 'rotate(180deg)' : 'rotate(0)', transition:'transform 0.2s' }} />
            </button>
          </div>
        </div>
        {mobileMenuOpen && (
          <div style={{ padding:'12px 24px 20px', borderTop:'1px solid var(--border-subtle)', display:'flex', flexDirection:'column', gap:4 }}>
            {[['hero','Home'],['pain','The Setup'],['mechanism','The Edge'],['reviews','Receipts'],['faq','FAQ']].map(([id,label]) => (
              <button key={id} onClick={() => scrollTo(id)} style={{ background:'none', border:'none', color:'var(--text-secondary)', fontSize:14, textAlign:'left', padding:'10px 0', cursor:'pointer', borderBottom:'1px solid var(--border-subtle)' }}>{label}</button>
            ))}
            <button onClick={() => navigate('/contact')} style={{ background:'none', border:'none', color:'var(--text-secondary)', fontSize:14, textAlign:'left', padding:'10px 0', cursor:'pointer', borderBottom:'1px solid var(--border-subtle)' }}>Contact</button>
          </div>
        )}
      </nav>

      {/* ─── HERO ─── */}
      <section id="hero" style={{ position:'relative', zIndex:1, padding:'clamp(60px,8vw,100px) 24px clamp(60px,6vw,80px)' }}>
        <div style={{ maxWidth:1200, margin:'0 auto', display:'flex', gap:'clamp(32px,5vw,64px)', alignItems:'center' }} className="hero-split">

          {/* LEFT */}
          <div style={{ flex:'1 1 520px', maxWidth:600 }}>

            {/* Auto-personalized context line */}
            {heroContextLine && (
              <div style={{ display:'inline-flex', alignItems:'center', gap:8, background:'rgba(56,189,248,0.07)', border:'1px solid rgba(56,189,248,0.18)', color:'var(--accent-cyan)', padding:'6px 14px', borderRadius:999, fontSize:12, fontWeight:600, marginBottom:20, letterSpacing:'0.01em' }}>
                <span style={{ width:6, height:6, borderRadius:'50%', background:marketDot, animation:'pulse2 2s infinite', display:'inline-block' }} />
                {heroContextLine}
              </div>
            )}

            {PN && (
              <div style={{ display:'inline-flex', alignItems:'center', gap:8, background:'rgba(52,211,153,0.06)', border:'1px solid rgba(52,211,153,0.2)', borderRadius:999, padding:'5px 12px', marginBottom:20, marginLeft: heroContextLine ? 8 : 0 }}>
                <div style={{ width:20, height:20, borderRadius:'50%', background:'var(--gradient-brand)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:9, fontWeight:800, color:'#0f172a' }}>{PN[0]}</div>
                <span style={{ fontSize:12, color:'var(--profit)', fontWeight:700 }}>{ctx.greeting.replace('.', '')}, {PN}</span>
              </div>
            )}

            {/* Main headline. Unfair advantage positioning. */}
            <h1 style={{ fontSize:'clamp(30px,4.5vw,54px)', fontWeight:900, lineHeight:1.06, letterSpacing:'-1.5px', marginBottom:22 }}>
              You vs. the institutions.
              <br />
              <span style={{ background:'var(--gradient-brand)', WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>Until today, this was an unfair fight.</span>
            </h1>

            <p style={{ fontSize:'clamp(15px,1.6vw,18px)', color:'var(--text-secondary)', lineHeight:1.7, marginBottom:14, maxWidth:560 }}>
              Wall Street has Bloomberg terminals. Hedge funds have analyst teams. Mutual funds have DCF models built overnight.
            </p>
            <p style={{ fontSize:'clamp(15px,1.6vw,18px)', color:'var(--text-primary)', lineHeight:1.7, marginBottom:32, maxWidth:560, fontWeight:600 }}>
              You had Telegram tips and a 40-page broker PDF that says BUY on everything. <span style={{ color:'var(--accent-cyan)' }}>That ends now.</span>
            </p>

            {/* Primary CTA */}
            <div style={{ display:'flex', flexDirection:'column', gap:12, marginBottom:32 }}>
              <button onClick={handleCTA} className="cta-shimmer" style={{ color:'#0f172a', border:'none', padding:'18px 34px', borderRadius:14, fontSize:'clamp(15px,1.4vw,17px)', fontWeight:800, cursor:'pointer', display:'inline-flex', alignItems:'center', gap:10, width:'fit-content', letterSpacing:'-0.2px', animation:'glowPulse 3s infinite' }}>
                Claim Your Unfair Advantage <ArrowRight size={20} />
              </button>
              <div style={{ display:'flex', gap:20, flexWrap:'wrap', fontSize:12, color:'var(--text-muted)' }}>
                <span style={{ display:'flex', alignItems:'center', gap:5 }}><CheckCircle size={12} color="var(--profit)" /> No credit card</span>
                <span style={{ display:'flex', alignItems:'center', gap:5 }}><CheckCircle size={12} color="var(--profit)" /> 30 second setup</span>
                <span style={{ display:'flex', alignItems:'center', gap:5 }}><CheckCircle size={12} color="var(--profit)" /> Free forever tier</span>
              </div>
            </div>

            {/* Social proof strip */}
            <div style={{ display:'flex', alignItems:'center', gap:14, flexWrap:'wrap' }}>
              <div style={{ display:'flex', gap:-4 }}>
                {['AM','PK','VG','SI','MT'].map((av,i) => (
                  <div key={i} style={{ width:28, height:28, borderRadius:'50%', background:'var(--gradient-brand)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:9, fontWeight:800, color:'#0f172a', border:'2px solid var(--bg-deep)', marginLeft: i ? -8 : 0 }}>{av}</div>
                ))}
              </div>
              <div style={{ display:'flex', gap:3 }}>{[1,2,3,4,5].map(i => <Star key={i} size={13} fill="#fbbf24" color="#fbbf24" />)}</div>
              <span style={{ fontSize:13, color:'var(--text-secondary)' }}>
                <strong style={{ color:'var(--text-primary)' }}>2,847</strong> investors evened the score
              </span>
            </div>
          </div>

          {/* RIGHT. Chat mockup. */}
          <div style={{ flex:'1 1 420px', maxWidth:520 }}>
            <div style={{ borderRadius:18, overflow:'hidden', border:'1px solid rgba(56,189,248,0.15)', boxShadow:'0 32px 80px rgba(0,0,0,0.5), 0 0 0 1px rgba(56,189,248,0.05)', background:'rgba(3,7,18,0.8)', backdropFilter:'blur(20px)' }}>
              <div style={{ background:'rgba(15,23,42,0.95)', padding:'12px 16px', display:'flex', alignItems:'center', gap:12, borderBottom:'1px solid var(--border-subtle)' }}>
                <div style={{ display:'flex', gap:6 }}>
                  {['#fb7185','#fbbf24','#34d399'].map(c => <span key={c} style={{ width:10, height:10, borderRadius:'50%', background:c, display:'block' }} />)}
                </div>
                <div style={{ flex:1, background:'rgba(255,255,255,0.04)', borderRadius:6, padding:'4px 10px', fontSize:11, color:'var(--text-muted)', fontFamily:'var(--font-mono)', display:'flex', alignItems:'center', gap:6 }}>
                  <span style={{ width:6, height:6, borderRadius:'50%', background:marketDot, animation:'pulse2 2s infinite', display:'inline-block' }} />
                  Arthik · {ctx.marketStatus === 'open' ? 'Live · NSE Connected' : 'Standby · NSE Cached'}
                </div>
                <Activity size={13} color="var(--profit)" />
              </div>
              <div style={{ padding:'20px 18px', display:'flex', flexDirection:'column', gap:16 }}>
                <div style={{ display:'flex', gap:10, justifyContent:'flex-end' }}>
                  <div style={{ background:'rgba(56,189,248,0.1)', border:'1px solid rgba(56,189,248,0.2)', borderRadius:'14px 14px 4px 14px', padding:'10px 14px', fontSize:13, color:'var(--text-primary)', maxWidth:280, lineHeight:1.5 }}>
                    Should I buy RELIANCE at ₹2,931? What's the real intrinsic value?
                  </div>
                  <div style={{ width:28, height:28, borderRadius:'50%', background:'rgba(255,255,255,0.06)', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 }}>
                    <Users size={12} color="var(--text-muted)" />
                  </div>
                </div>
                <div style={{ display:'flex', gap:10 }}>
                  <div style={{ width:28, height:28, borderRadius:'50%', background:'var(--gradient-brand)', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0, boxShadow:'0 0 10px rgba(56,189,248,0.3)' }}><Brain size={14} color="#0f172a" /></div>
                  <div style={{ flex:1, background:'rgba(15,23,42,0.6)', border:'1px solid rgba(56,189,248,0.12)', borderRadius:'4px 14px 14px 14px', padding:'14px', fontSize:13, color:'var(--text-primary)', lineHeight:1.6 }}>
                    <div style={{ display:'flex', alignItems:'center', gap:6, marginBottom:12 }}>
                      <span style={{ fontSize:11, fontWeight:700, color:'var(--accent-cyan)', letterSpacing:'0.06em' }}>ARTHIK · RELIANCE</span>
                      <span style={{ fontSize:10, background:'rgba(52,211,153,0.1)', color:'var(--profit)', padding:'2px 6px', borderRadius:4, fontWeight:700 }}>LIVE</span>
                    </div>
                    <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:8, marginBottom:14 }}>
                      {[['DCF Value','₹3,240','+10.5%','var(--profit)'],['P/E Ratio','22.5x','5yr avg 24x','var(--text-muted)'],['Piotroski','7/9','Strong','var(--accent-cyan)']].map(([l,v,s,c]) => (
                        <div key={l} style={{ background:'rgba(3,7,18,0.6)', borderRadius:10, padding:'10px 8px', textAlign:'center', border:'1px solid var(--border-subtle)' }}>
                          <div style={{ fontSize:9, color:'var(--text-muted)', marginBottom:5, letterSpacing:'0.06em', textTransform:'uppercase', fontWeight:600 }}>{l}</div>
                          <div style={{ fontSize:15, fontWeight:800, color:c, fontFamily:'var(--font-mono)' }}>{v}</div>
                          <div style={{ fontSize:9, color:c, marginTop:3, fontWeight:600 }}>{s}</div>
                        </div>
                      ))}
                    </div>
                    <p style={{ fontSize:12, lineHeight:1.65, color:'var(--text-secondary)', marginBottom:10 }}>
                      <strong style={{ color:'var(--text-primary)' }}>Verdict:</strong> Reasonable entry. Debt/equity <strong style={{ color:'var(--accent-cyan)' }}>0.42x</strong>. ROE <strong style={{ color:'var(--profit)' }}>11.8%</strong>. For a 15% margin of safety, wait for ₹2,700. Otherwise fair value for a quality compounder.
                    </p>
                    <div style={{ display:'flex', gap:6, fontSize:10, color:'var(--text-muted)' }}>
                      <span style={{ background:'rgba(56,189,248,0.06)', padding:'2px 8px', borderRadius:4 }}>NSE India</span>
                      <span style={{ background:'rgba(56,189,248,0.06)', padding:'2px 8px', borderRadius:4 }}>yfinance</span>
                      <span style={{ background:'rgba(56,189,248,0.06)', padding:'2px 8px', borderRadius:4 }}>Valuation</span>
                      <span style={{ marginLeft:'auto', color:'var(--text-muted)' }}>8.1s</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─── STATS BANNER ─── */}
      <div style={{ borderTop:'1px solid var(--border-subtle)', borderBottom:'1px solid var(--border-subtle)', background:'rgba(15,23,42,0.4)', position:'relative', zIndex:1 }}>
        <div style={{ maxWidth:1100, margin:'0 auto', padding:'32px 24px', display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:24, textAlign:'center' }} className="stats-4col">
          {[
            { label:'Active Investors', target:2847, suffix:'+', color:'var(--accent-cyan)' },
            { label:'Queries Answered', target:52000, suffix:'+', color:'var(--accent-indigo)' },
            { label:'Corporates Indexed', target:850, suffix:'+', color:'var(--profit)' },
            { label:'Specialist Agents', target:8, suffix:'', color:'var(--accent-violet)' },
          ].map(({ label, target, suffix, color }) => (
            <div key={label}>
              <div style={{ fontSize:'clamp(22px,3vw,32px)', fontWeight:900, fontFamily:'var(--font-mono)', color, letterSpacing:'-0.5px' }}>
                <AnimatedCounter target={target} suffix={suffix} />
              </div>
              <div style={{ fontSize:12, color:'var(--text-secondary)', marginTop:6, fontWeight:500 }}>{label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* ─── QUOTE: MUNGER (Incentives) ─── */}
      <section style={{ padding:'clamp(60px,8vw,100px) 24px', position:'relative', zIndex:1 }}>
        <div className="quote-block" style={{ maxWidth:820, margin:'0 auto', textAlign:'center', position:'relative' }}>
          <Quote size={40} color="var(--accent-cyan)" style={{ opacity:0.3, marginBottom:20 }} />
          <h3 style={{ fontSize:'clamp(26px,3.5vw,40px)', fontWeight:700, lineHeight:1.25, marginBottom:20, letterSpacing:'-0.5px', fontStyle:'italic', color:'var(--text-primary)' }}>
            "Show me the incentive, and I'll show you the outcome."
          </h3>
          <div style={{ display:'inline-flex', alignItems:'center', gap:10, marginBottom:32 }}>
            <div style={{ width:30, height:1, background:'var(--border-hover)' }} />
            <span style={{ fontSize:13, color:'var(--text-secondary)', fontWeight:600, letterSpacing:'0.04em' }}>CHARLIE MUNGER</span>
            <div style={{ width:30, height:1, background:'var(--border-hover)' }} />
          </div>
          <p style={{ fontSize:15, color:'var(--text-secondary)', lineHeight:1.75, maxWidth:620, margin:'0 auto' }}>
            Your broker earns when you trade. Not when you win. So their research recommends trading. Forty times a year. That isn't a flaw in the system. It is the system.
          </p>
        </div>
      </section>

      {/* ─── PAIN ─── */}
      <section id="pain" style={{ padding:'clamp(20px,4vw,40px) 24px clamp(60px,7vw,90px)', position:'relative', zIndex:1 }}>
        <div style={{ maxWidth:1100, margin:'0 auto' }}>
          <div style={{ textAlign:'center', marginBottom:52 }}>
            <div style={{ display:'inline-flex', alignItems:'center', gap:8, background:'rgba(251,113,133,0.07)', border:'1px solid rgba(251,113,133,0.18)', color:'var(--loss)', padding:'6px 16px', borderRadius:999, fontSize:12, fontWeight:700, marginBottom:16 }}>
              <AlertTriangle size={13} /> The Setup
            </div>
            <h2 style={{ fontSize:'clamp(26px,3.5vw,40px)', fontWeight:800, marginBottom:12, letterSpacing:'-0.5px' }}>
              You're not investing. <span style={{ color:'var(--loss)' }}>You're the product.</span>
            </h2>
            <p style={{ fontSize:16, color:'var(--text-secondary)', maxWidth:580, margin:'0 auto', lineHeight:1.65 }}>
              Three ways the Indian retail investor was designed to lose. None of them are accidents.
            </p>
          </div>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(280px,1fr))', gap:20 }} className="pain-3col">
            {[
              { icon:MessageSquare, title:"Research is a sales brochure.", body:"Every broker report ends with BUY. Every page. Every quarter. Hold doesn't pay brokerage.", stat:"0 SELL ratings in your inbox last year" },
              { icon:AlertTriangle, title:"Tips are someone else's exit.", body:"The Telegram tip you bought at the top? That's their distribution. You're not the audience. You're the buyer.", stat:"₹4.8L average annual tip loss" },
              { icon:BarChart3, title:"Data isn't insight.", body:"Screener gives you 47 ratios. You stare at them and buy Reliance because it 'feels safe'. That's branding. Not investing.", stat:"23 stocks owned. 0 understood." },
            ].map((c, i) => (
              <div key={i} className="card-hover" style={{ background:'rgba(15,23,42,0.45)', border:'1px solid rgba(251,113,133,0.12)', borderRadius:18, padding:28, display:'flex', flexDirection:'column', gap:14 }}>
                <div style={{ width:46, height:46, borderRadius:13, background:'rgba(251,113,133,0.08)', display:'flex', alignItems:'center', justifyContent:'center' }}>
                  <c.icon size={22} color="var(--loss)" />
                </div>
                <h3 style={{ fontSize:18, fontWeight:700, lineHeight:1.3 }}>{c.title}</h3>
                <p style={{ fontSize:14, color:'var(--text-secondary)', lineHeight:1.65, flex:1 }}>{c.body}</p>
                <div style={{ fontSize:12, fontWeight:800, color:'var(--loss)', fontFamily:'var(--font-mono)', background:'rgba(251,113,133,0.06)', padding:'6px 12px', borderRadius:8, display:'inline-flex' }}>{c.stat}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ─── QUOTE: BUFFETT (Knowledge gap) ─── */}
      <section style={{ padding:'clamp(50px,7vw,80px) 24px', position:'relative', zIndex:1, background:'linear-gradient(180deg, transparent, rgba(56,189,248,0.02), transparent)' }}>
        <div className="quote-block" style={{ maxWidth:820, margin:'0 auto', textAlign:'center' }}>
          <Quote size={40} color="var(--accent-indigo)" style={{ opacity:0.3, marginBottom:20 }} />
          <h3 style={{ fontSize:'clamp(26px,3.5vw,40px)', fontWeight:700, lineHeight:1.25, marginBottom:20, letterSpacing:'-0.5px', fontStyle:'italic', color:'var(--text-primary)' }}>
            "Risk comes from not knowing what you're doing."
          </h3>
          <div style={{ display:'inline-flex', alignItems:'center', gap:10, marginBottom:24 }}>
            <div style={{ width:30, height:1, background:'var(--border-hover)' }} />
            <span style={{ fontSize:13, color:'var(--text-secondary)', fontWeight:600, letterSpacing:'0.04em' }}>WARREN BUFFETT</span>
            <div style={{ width:30, height:1, background:'var(--border-hover)' }} />
          </div>
          <p style={{ fontSize:15, color:'var(--text-secondary)', lineHeight:1.75, maxWidth:620, margin:'0 auto' }}>
            You don't have a luck problem. You have a knowledge gap. The kind that costs ₹2L on Asian Paints because nobody told you the promoter pledged more shares. That gap is the only thing we close.
          </p>
        </div>
      </section>

      {/* ─── SOLUTION ─── */}
      <section id="mechanism" style={{ padding:'clamp(40px,5vw,60px) 24px clamp(60px,7vw,90px)', position:'relative', zIndex:1 }}>
        <div style={{ maxWidth:1100, margin:'0 auto' }}>
          <div style={{ textAlign:'center', marginBottom:52 }}>
            <div style={{ display:'inline-flex', alignItems:'center', gap:8, background:'rgba(52,211,153,0.07)', border:'1px solid rgba(52,211,153,0.18)', color:'var(--profit)', padding:'6px 16px', borderRadius:999, fontSize:12, fontWeight:700, marginBottom:16 }}>
              <Zap size={13} /> The Edge
            </div>
            <h2 style={{ fontSize:'clamp(26px,3.5vw,40px)', fontWeight:800, marginBottom:12, letterSpacing:'-0.5px' }}>
              Arthik is the <span style={{ background:'var(--gradient-brand)', WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>analyst team</span> you couldn't afford.
            </h2>
            <p style={{ fontSize:16, color:'var(--text-secondary)', maxWidth:640, margin:'0 auto', lineHeight:1.65 }}>
              Eight specialist AI agents. Working in parallel. Reading what brokers won't tell you. Running the math sell-side hides. Answering in eight seconds. With zero incentive to make you trade.
            </p>
          </div>

          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(240px,1fr))', gap:16 }} className="feat-3col">
            {[
              { icon:TrendingUp, title:"Live NSE feeds", desc:"Real-time price action, volume anomalies, institutional flow. No delayed data.", metric:'265ms' },
              { icon:Shield, title:"Transparent valuation", desc:"DCF, Graham, Altman Z, Piotroski. Every assumption visible. Every number editable.", metric:'4 models' },
              { icon:FileText, title:"Deep research memos", desc:"Eight-phase loops read filings, compare peers, check sentiment, write analyst-grade memos.", metric:'90s' },
              { icon:CheckCircle, title:"Zero conflict", desc:"Arthik earns no brokerage. Has no incentive to push you to trade. Just the math.", metric:'0 bias' },
              { icon:Lock, title:"Portfolio risk audit", desc:"Upload your statement. Arthik flags concentration, overlap, hidden leverage, beta drift.", metric:'6 axes' },
              { icon:Trophy, title:"Earnings edge", desc:"Pre-result positioning. Whisper expectations. Beat/miss rates. Implied volatility.", metric:'5-day lead' },
            ].map((f, i) => (
              <div key={i} className="card-hover" style={{ background:'rgba(15,23,42,0.4)', border:'1px solid var(--border-subtle)', borderRadius:16, padding:24, display:'flex', flexDirection:'column', gap:12 }}>
                <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between' }}>
                  <div style={{ width:42, height:42, borderRadius:12, background:'rgba(56,189,248,0.08)', display:'flex', alignItems:'center', justifyContent:'center' }}>
                    <f.icon size={20} color="var(--accent-cyan)" />
                  </div>
                  <div style={{ fontSize:11, fontWeight:800, color:'var(--accent-cyan)', fontFamily:'var(--font-mono)', background:'rgba(56,189,248,0.06)', padding:'3px 8px', borderRadius:6 }}>{f.metric}</div>
                </div>
                <h3 style={{ fontSize:15, fontWeight:700 }}>{f.title}</h3>
                <p style={{ fontSize:13, color:'var(--text-secondary)', lineHeight:1.6 }}>{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ─── BEFORE / AFTER ─── */}
      <section style={{ padding:'clamp(40px,5vw,60px) 24px', position:'relative', zIndex:1 }}>
        <div style={{ maxWidth:1100, margin:'0 auto' }}>
          <div style={{ background:'linear-gradient(135deg, rgba(15,23,42,0.7) 0%, rgba(3,7,18,0.5) 100%)', border:'1px solid var(--border-subtle)', borderRadius:24, padding:'clamp(28px,4vw,48px)', overflow:'hidden', position:'relative' }}>
            <div style={{ position:'absolute', top:0, right:0, width:300, height:300, background:'radial-gradient(circle, rgba(129,140,248,0.06) 0%, transparent 70%)', pointerEvents:'none' }} />
            <h2 style={{ fontSize:'clamp(22px,3vw,32px)', fontWeight:800, textAlign:'center', marginBottom:14, letterSpacing:'-0.3px' }}>
              The <span style={{ color:'var(--loss)' }}>old you</span> vs. the <span style={{ color:'var(--profit)' }}>edge you</span>
            </h2>
            <p style={{ fontSize:14, color:'var(--text-secondary)', textAlign:'center', marginBottom:36, maxWidth:520, margin:'0 auto 36px' }}>
              Same market. Same money. Different intelligence layer.
            </p>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'clamp(20px,4vw,48px)' }} className="ba-2col">
              <div style={{ display:'flex', flexDirection:'column', gap:14 }}>
                <div style={{ fontSize:11, fontWeight:800, color:'var(--loss)', letterSpacing:'0.1em', textTransform:'uppercase', paddingBottom:10, borderBottom:'1px solid rgba(251,113,133,0.15)' }}>The Old You</div>
                {[
                  "Broker sends a 40-page PDF. Page 40 says BUY. You buy. They earn.",
                  "Tip arrives. You panic-buy at the top. Predictable.",
                  "Twenty-three stocks. Zero conviction. Red days mean panic.",
                ].map((item,i) => (
                  <div key={i} style={{ display:'flex', gap:10, alignItems:'flex-start' }}>
                    <div style={{ width:18, height:18, borderRadius:'50%', background:'rgba(251,113,133,0.1)', border:'1px solid rgba(251,113,133,0.2)', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0, marginTop:1 }}>
                      <span style={{ color:'var(--loss)', fontSize:10, fontWeight:900, lineHeight:1 }}>✕</span>
                    </div>
                    <span style={{ fontSize:14, color:'var(--text-secondary)', lineHeight:1.55 }}>{item}</span>
                  </div>
                ))}
              </div>
              <div style={{ display:'flex', flexDirection:'column', gap:14 }}>
                <div style={{ fontSize:11, fontWeight:800, color:'var(--profit)', letterSpacing:'0.1em', textTransform:'uppercase', paddingBottom:10, borderBottom:'1px solid rgba(52,211,153,0.15)' }}>The Edge You</div>
                {[
                  "Ask Arthik. Real DCF. Real risk score. Eight seconds. You decide.",
                  "Tip arrives. Run it through Arthik. Verified or rejected. Move on.",
                  "Every position justified. Red days are buying opportunities.",
                ].map((item,i) => (
                  <div key={i} style={{ display:'flex', gap:10, alignItems:'flex-start' }}>
                    <div style={{ width:18, height:18, borderRadius:'50%', background:'rgba(52,211,153,0.1)', border:'1px solid rgba(52,211,153,0.2)', display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0, marginTop:1 }}>
                      <CheckCircle size={11} color="var(--profit)" />
                    </div>
                    <span style={{ fontSize:14, color:'var(--text-primary)', lineHeight:1.55, fontWeight:500 }}>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─── QUOTE: LYNCH (Conviction) ─── */}
      <section style={{ padding:'clamp(50px,7vw,80px) 24px', position:'relative', zIndex:1 }}>
        <div className="quote-block" style={{ maxWidth:820, margin:'0 auto', textAlign:'center' }}>
          <Quote size={40} color="var(--profit)" style={{ opacity:0.3, marginBottom:20 }} />
          <h3 style={{ fontSize:'clamp(26px,3.5vw,40px)', fontWeight:700, lineHeight:1.25, marginBottom:20, letterSpacing:'-0.5px', fontStyle:'italic', color:'var(--text-primary)' }}>
            "Know what you own, and know why you own it."
          </h3>
          <div style={{ display:'inline-flex', alignItems:'center', gap:10, marginBottom:24 }}>
            <div style={{ width:30, height:1, background:'var(--border-hover)' }} />
            <span style={{ fontSize:13, color:'var(--text-secondary)', fontWeight:600, letterSpacing:'0.04em' }}>PETER LYNCH</span>
            <div style={{ width:30, height:1, background:'var(--border-hover)' }} />
          </div>
          <p style={{ fontSize:15, color:'var(--text-secondary)', lineHeight:1.75, maxWidth:620, margin:'0 auto' }}>
            Arthik answers both questions. About every stock. In every portfolio. In real time. That's the only kind of conviction worth having.
          </p>
        </div>
      </section>

      {/* ─── REVIEWS ─── */}
      <section id="reviews" style={{ padding:'clamp(20px,4vw,40px) 24px clamp(60px,7vw,90px)', position:'relative', zIndex:1 }}>
        <div style={{ maxWidth:1100, margin:'0 auto' }}>
          <div style={{ textAlign:'center', marginBottom:48 }}>
            <div style={{ display:'inline-flex', alignItems:'center', gap:8, background:'rgba(251,191,36,0.07)', border:'1px solid rgba(251,191,36,0.18)', color:'#fbbf24', padding:'6px 16px', borderRadius:999, fontSize:12, fontWeight:700, marginBottom:16 }}>
              <Star size={13} fill="#fbbf24" /> 4.8/5 from 2,847 investors
            </div>
            <h2 style={{ fontSize:'clamp(26px,3.5vw,40px)', fontWeight:800, marginBottom:12, letterSpacing:'-0.5px' }}>
              Real names. <span style={{ background:'var(--gradient-brand)', WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>Real numbers.</span>
            </h2>
            <p style={{ fontSize:16, color:'var(--text-secondary)', maxWidth:560, margin:'0 auto' }}>
              No anonymous quotes. No vague "great tool!" reviews. Specific decisions. Specific outcomes.
            </p>
          </div>

          <div className="active-review-card" key={activeReview} style={{ background:'linear-gradient(135deg, rgba(56,189,248,0.06), rgba(129,140,248,0.04))', border:'1px solid rgba(56,189,248,0.18)', borderRadius:22, padding:'clamp(24px,4vw,40px)', marginBottom:28, display:'flex', gap:24, alignItems:'flex-start', animation:'reviewFade 0.5s ease forwards' }}>
            <div style={{ width:60, height:60, borderRadius:'50%', background:'var(--gradient-brand)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:20, fontWeight:800, color:'#0f172a', flexShrink:0, boxShadow:'0 0 20px rgba(56,189,248,0.2)' }}>{REVIEWS[activeReview].avatar}</div>
            <div style={{ flex:1 }}>
              <div style={{ display:'flex', gap:3, marginBottom:10 }}>
                {[...Array(5)].map((_,i) => <Star key={i} size={15} fill={i < REVIEWS[activeReview].stars ? '#fbbf24' : 'transparent'} color={i < REVIEWS[activeReview].stars ? '#fbbf24' : 'var(--text-muted)'} />)}
              </div>
              <h3 style={{ fontSize:20, fontWeight:700, marginBottom:12, letterSpacing:'-0.3px' }}>{REVIEWS[activeReview].title}</h3>
              <p style={{ fontSize:15, color:'var(--text-secondary)', lineHeight:1.75, marginBottom:18 }}>{REVIEWS[activeReview].body}</p>
              <div style={{ display:'flex', alignItems:'center', gap:12, flexWrap:'wrap' }}>
                <span style={{ fontSize:14, fontWeight:700, color:'var(--text-primary)' }}>{REVIEWS[activeReview].name}</span>
                <span style={{ width:3, height:3, borderRadius:'50%', background:'var(--text-muted)', display:'inline-block' }} />
                <span style={{ fontSize:13, color:'var(--text-muted)' }}>{REVIEWS[activeReview].role}</span>
                <span style={{ width:3, height:3, borderRadius:'50%', background:'var(--text-muted)', display:'inline-block' }} />
                <span style={{ fontSize:13, color:'var(--text-muted)' }}>{REVIEWS[activeReview].location}</span>
                <div style={{ marginLeft:'auto', background:'rgba(52,211,153,0.1)', border:'1px solid rgba(52,211,153,0.2)', color:'var(--profit)', padding:'5px 12px', borderRadius:8, fontSize:13, fontWeight:700 }}>{REVIEWS[activeReview].result}</div>
              </div>
            </div>
          </div>

          <div style={{ display:'flex', justifyContent:'center', gap:8, marginBottom:36 }}>
            {REVIEWS.map((_,i) => (
              <button key={i} onClick={() => setActiveReview(i)} style={{ width: i === activeReview ? 24 : 8, height:8, borderRadius:4, border:'none', cursor:'pointer', background: i === activeReview ? 'var(--accent-cyan)' : 'rgba(255,255,255,0.15)', transition:'all 0.3s', padding:0 }} />
            ))}
          </div>

          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(260px,1fr))', gap:16 }} className="rev-grid">
            {REVIEWS.map((r,i) => (
              <div key={i} onClick={() => setActiveReview(i)} className="card-hover" style={{ background:'rgba(15,23,42,0.4)', border: i === activeReview ? '1px solid var(--accent-cyan)' : '1px solid var(--border-subtle)', borderRadius:16, padding:22, cursor:'pointer', transition:'all 0.2s', boxShadow: i === activeReview ? '0 0 20px rgba(56,189,248,0.08)' : 'none' }}>
                <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:12 }}>
                  <div style={{ width:38, height:38, borderRadius:'50%', background:'var(--gradient-brand)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:12, fontWeight:800, color:'#0f172a' }}>{r.avatar}</div>
                  <div>
                    <div style={{ fontSize:13, fontWeight:700 }}>{r.name}</div>
                    <div style={{ fontSize:11, color:'var(--text-muted)' }}>{r.location}</div>
                  </div>
                  <div style={{ marginLeft:'auto', display:'flex', gap:2 }}>{[...Array(r.stars)].map((_,si) => <Star key={si} size={11} fill="#fbbf24" color="#fbbf24" />)}</div>
                </div>
                <p style={{ fontSize:13, color:'var(--text-secondary)', lineHeight:1.55, display:'-webkit-box', WebkitLineClamp:3, WebkitBoxOrient:'vertical', overflow:'hidden' }}>{r.body}</p>
                <div style={{ marginTop:12, fontSize:12, color:'var(--profit)', fontWeight:700, display:'flex', alignItems:'center', gap:6 }}>
                  <TrendingUp size={12} /> {r.result}
                </div>
              </div>
            ))}
          </div>

          <div style={{ textAlign:'center', marginTop:28 }}>
            <button onClick={() => navigate('/testimonials')} style={{ background:'none', border:'1px solid var(--border-subtle)', color:'var(--text-secondary)', padding:'10px 24px', borderRadius:10, fontSize:13, cursor:'pointer', transition:'all 0.2s' }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--accent-cyan)'; e.currentTarget.style.color = 'var(--accent-cyan)'; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = 'var(--border-subtle)'; e.currentTarget.style.color = 'var(--text-secondary)'; }}>
              Read all reviews <ChevronRight size={14} style={{ display:'inline', verticalAlign:'middle' }} />
            </button>
          </div>
        </div>
      </section>

      {/* ─── GUARANTEE ─── */}
      <section style={{ padding:'clamp(40px,5vw,60px) 24px', position:'relative', zIndex:1 }}>
        <div style={{ maxWidth:1100, margin:'0 auto' }}>
          <div style={{ background:'rgba(15,23,42,0.5)', border:'1px solid rgba(52,211,153,0.15)', borderRadius:24, padding:'clamp(28px,4vw,48px)', textAlign:'center', position:'relative', overflow:'hidden' }}>
            <div style={{ position:'absolute', inset:0, background:'radial-gradient(ellipse 600px 300px at 50% 0%, rgba(52,211,153,0.04), transparent 70%)', pointerEvents:'none' }} />
            <div style={{ width:60, height:60, borderRadius:'50%', background:'rgba(52,211,153,0.08)', border:'1px solid rgba(52,211,153,0.2)', display:'flex', alignItems:'center', justifyContent:'center', margin:'0 auto 20px', boxShadow:'0 0 24px rgba(52,211,153,0.1)' }}>
              <Shield size={26} color="var(--profit)" />
            </div>
            <h2 style={{ fontSize:'clamp(22px,3vw,34px)', fontWeight:800, marginBottom:14, letterSpacing:'-0.3px' }}>
              Free forever. No card. No tricks.
            </h2>
            <p style={{ fontSize:16, color:'var(--text-secondary)', maxWidth:600, margin:'0 auto 28px', lineHeight:1.7 }}>
              Twenty queries per day. Live NSE data. Basic valuations. If Arthik doesn't save you from one bad decision in your first week, you delete the tab. That's it. That's the deal.
            </p>
            <div className="guarantee-items" style={{ display:'flex', justifyContent:'center', gap:'clamp(16px,3vw,32px)', flexWrap:'wrap', marginBottom:32 }}>
              {['Free forever tier','Cancel anytime','No hidden fees','Your data never sold'].map((item,i) => (
                <div key={i} style={{ display:'flex', alignItems:'center', gap:8, fontSize:14, color:'var(--text-secondary)' }}>
                  <CheckCircle size={16} color="var(--profit)" /> {item}
                </div>
              ))}
            </div>
            <button onClick={handleCTA} className="cta-shimmer" style={{ color:'#0f172a', border:'none', padding:'18px 40px', borderRadius:14, fontSize:17, fontWeight:800, cursor:'pointer', letterSpacing:'-0.2px' }}>
              Claim it. It's free. →
            </button>
          </div>
        </div>
      </section>

      {/* ─── FAQ ─── */}
      <section id="faq" style={{ padding:'clamp(40px,5vw,60px) 24px clamp(60px,8vw,100px)', position:'relative', zIndex:1 }}>
        <div style={{ maxWidth:720, margin:'0 auto' }}>
          <h2 style={{ fontSize:'clamp(24px,3vw,34px)', fontWeight:800, textAlign:'center', marginBottom:40, letterSpacing:'-0.3px' }}>
            Questions? <span style={{ background:'var(--gradient-brand)', WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>Answered.</span>
          </h2>
          {FAQS.map((faq,i) => (
            <div key={i} style={{ borderBottom:'1px solid var(--border-subtle)' }}>
              <button onClick={() => setOpenFaq(openFaq === i ? null : i)} style={{ width:'100%', display:'flex', alignItems:'center', justifyContent:'space-between', padding:'20px 0', background:'none', border:'none', color:'var(--text-primary)', fontSize:15, fontWeight:600, textAlign:'left', cursor:'pointer', gap:12 }}>
                <span>{faq.q}</span>
                <ChevronDown size={17} color="var(--text-muted)" style={{ transform: openFaq === i ? 'rotate(180deg)' : 'rotate(0)', transition:'transform 0.25s', flexShrink:0 }} />
              </button>
              {openFaq === i && (
                <div style={{ paddingBottom:20, fontSize:14, color:'var(--text-secondary)', lineHeight:1.75, animation:'reviewFade 0.2s ease' }}>
                  {faq.a}
                </div>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* ─── FINAL CTA with closing quote ─── */}
      <section style={{ padding:'clamp(60px,7vw,80px) 24px', position:'relative', zIndex:1, overflow:'hidden' }}>
        <div style={{ position:'absolute', inset:0, background:'radial-gradient(ellipse 900px 400px at 50% 0%, rgba(56,189,248,0.07), transparent 70%)', pointerEvents:'none' }} />
        <div style={{ maxWidth:780, margin:'0 auto', textAlign:'center', position:'relative' }}>

          {/* Closing Buffett quote */}
          <div style={{ marginBottom:48, padding:'24px 0', borderTop:'1px solid var(--border-subtle)', borderBottom:'1px solid var(--border-subtle)' }}>
            <Quote size={28} color="var(--accent-cyan)" style={{ opacity:0.3, marginBottom:14 }} />
            <p style={{ fontSize:'clamp(20px,2.6vw,28px)', fontWeight:600, lineHeight:1.35, letterSpacing:'-0.3px', fontStyle:'italic', color:'var(--text-primary)', marginBottom:14 }}>
              "Be fearful when others are greedy. Greedy when others are fearful."
            </p>
            <span style={{ fontSize:12, color:'var(--text-secondary)', fontWeight:600, letterSpacing:'0.06em' }}>WARREN BUFFETT</span>
          </div>

          <div style={{ display:'inline-flex', alignItems:'center', gap:8, background:'rgba(56,189,248,0.06)', border:'1px solid rgba(56,189,248,0.15)', color:'var(--accent-cyan)', padding:'6px 16px', borderRadius:999, fontSize:12, fontWeight:700, marginBottom:24 }}>
            <span style={{ width:6, height:6, borderRadius:'50%', background:'var(--profit)', animation:'pulse2 2s infinite', display:'inline-block' }} />
            2,847 investors already even the score
          </div>
          <h2 style={{ fontSize:'clamp(28px,4vw,46px)', fontWeight:900, marginBottom:18, letterSpacing:'-1px', lineHeight:1.08 }}>
            The hardest part of investing isn't picking stocks.
            <br />
            <span style={{ background:'var(--gradient-brand)', WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>It's telling signal from noise.</span>
          </h2>
          <p style={{ fontSize:17, color:'var(--text-secondary)', marginBottom:32, lineHeight:1.65 }}>
            Arthik does that part. You take the credit.
          </p>
          <button onClick={handleCTA} className="cta-shimmer" style={{ color:'#0f172a', border:'none', padding:'20px 44px', borderRadius:16, fontSize:18, fontWeight:900, cursor:'pointer', marginBottom:20, letterSpacing:'-0.3px' }}>
            Claim Your Unfair Advantage →
          </button>
          <div style={{ display:'flex', justifyContent:'center', gap:24, flexWrap:'wrap', fontSize:12, color:'var(--text-muted)' }}>
            {['Live NSE data','8 specialist agents','Free forever tier'].map(t => (
              <span key={t} style={{ display:'flex', alignItems:'center', gap:6 }}><CheckCircle size={12} color="var(--profit)" /> {t}</span>
            ))}
          </div>
        </div>
      </section>

      {/* ─── FOOTER ─── */}
      <footer style={{ borderTop:'1px solid var(--border-subtle)', padding:'clamp(32px,4vw,48px) 24px', background:'rgba(3,7,18,0.7)', position:'relative', zIndex:1, paddingBottom: showStickyBar ? 100 : undefined }}>
        <div style={{ maxWidth:1100, margin:'0 auto', display:'flex', flexDirection:'column', gap:20 }}>
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', flexWrap:'wrap', gap:16 }}>
            <div style={{ display:'flex', alignItems:'center', gap:10 }}>
              <Logo size={28} />
              <span style={{ fontWeight:800, fontSize:15, letterSpacing:'0.08em', textTransform:'uppercase' }} className="text-gradient">Prospekt Lab</span>
            </div>
            <div style={{ display:'flex', gap:8, flexWrap:'wrap' }}>
              {[['Home', () => scrollTo('hero')],['Pricing', () => navigate('/pricing')],['Features', () => navigate('/features')],['Reviews', () => navigate('/testimonials')]].map(([label, fn]) => (
                <button key={label as string} onClick={fn as () => void} style={{ background:'none', border:'1px solid var(--border-subtle)', color:'var(--text-muted)', padding:'5px 12px', borderRadius:7, fontSize:12, cursor:'pointer', transition:'all 0.15s' }}
                  onMouseEnter={e => { e.currentTarget.style.color = 'var(--text-primary)'; e.currentTarget.style.borderColor = 'var(--border-hover)'; }}
                  onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.borderColor = 'var(--border-subtle)'; }}>
                  {label as string}
                </button>
              ))}
            </div>
          </div>
          <p style={{ fontSize:11.5, color:'var(--text-muted)', maxWidth:760, lineHeight:1.65 }}>
            Disclaimer: ProspektLab is an informational AI intelligence platform. Content is for analytical and educational purposes only. We are not SEBI-registered advisors. Past performance of any model does not guarantee future results. Consult a SEBI-registered advisor before making investment decisions.
          </p>
          <p style={{ fontSize:11, color:'var(--text-muted)' }}>© 2026 ProspektLab. All rights reserved. Made in India. · <a href="#" style={{ color:'inherit', textDecoration:'underline' }}>Privacy</a> · <a href="#" style={{ color:'inherit', textDecoration:'underline' }}>Terms</a></p>
        </div>
      </footer>
    </div>
  );
};

export default LandingPage;


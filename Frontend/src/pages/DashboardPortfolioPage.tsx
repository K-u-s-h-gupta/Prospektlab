import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { AppShell } from '../components/layout/AppShell';
import { WatchlistCard, WatchlistStock } from '../components/dashboard/WatchlistCard';
import { PortfolioTable } from '../components/dashboard/PortfolioTable';
import { AssetHistoryModal, AssetHistoryTarget } from '../components/dashboard/AssetHistoryModal';
import { DonutChart } from '../components/charts/DonutChart';
import { IndexTickerCard, IndexTickerData } from '../components/dashboard/IndexTickerCard';
import { InteractiveChart } from '../components/charts/InteractiveChart';
import { ChatInput } from '../components/chat/ChatInput';
import { MessageBubble } from '../components/chat/MessageBubble';
import { AgentThinking } from '../components/chat/AgentThinking';
import ExportPanel from '../components/chat/ExportPanel';
import { useAuth } from '../context/AuthContext';
import { 
  startResearch, 
  streamSession, 
  stopSession, 
  getSessionResult, 
  getMfAnalytics,
  getTodayQueue,
  getPortfolioAnalytics,
  getPortfolioMirror,
  replacePortfolioMirror,
  AgentEventData,
  getMarketIndices,
  getMarketQuotes,
  getMarketNews,
  getPortfolioNews,
  getPortfolioBrief,
  getPortfolioCommentary,
  getTaxSummary,
  postStressTest,
  getUserTokenUsage,
} from '../api/client';
import { Lock, Search, Sparkles, MessageSquare, ChevronRight, ChevronDown, Activity, TrendingDown, Keyboard, UploadCloud } from 'lucide-react';
import { INDIAN_STOCKS, POPULAR_MUTUAL_FUNDS } from '../data/indianStocks';

interface Message {
  sender: 'user' | 'ai';
  text: string;
  richData?: any;
  depth?: 'standard' | 'deep';
  elapsedMs?: number;
  tokenLimitDetail?: any;
  sessionId?: string;
  wantsDocument?: boolean;
}

interface PortfolioItem {
  symbol: string;
  name: string;
  qty: number;
  avgCost: number;
  current: number;
  sector: string;
  assetClass?: string;
  dayChangePct?: number;
}

const TAPE_NEWS_CACHE_KEY = 'prospektlab_tape_news_cache_v1';

// ── Explicit document/report intent detection (gates the export panel) ──────
const DOC_INTENT_RE = /\b(report|document|doc|pdf|docx|memo|write[- ]?up|deck|dossier|whitepaper|white paper|one[- ]?pager|file)\b/i;
const DOC_VERB_RE = /\b(export|download|save|generate|create|make|produce|prepare|draft|build|give me|send me|put together)\b/i;
const DOC_NEG_RE = /\b(do not|don'?t|no need|without|skip|not a (report|document|pdf))\b/i;
function queryWantsDocument(text: string): boolean {
  const t = (text || '').toLowerCase();
  if (!t) return false;
  if (DOC_NEG_RE.test(t)) return false;
  if (/\b(as|to|in)\s+(a\s+)?(pdf|docx?|document|report|file)\b/.test(t)) return true;
  if (/\b(generate|create|make|give me|send me|build|prepare|draft|export|download)\s+(me\s+)?(a\s+|an\s+|the\s+)?(report|document|doc|pdf|docx|memo|deck|dossier|write[- ]?up|one[- ]?pager)\b/.test(t)) return true;
  return DOC_VERB_RE.test(t) && DOC_INTENT_RE.test(t);
}

// ── Analytics presentational helpers ───────────────────────────────────────
function fmtNum(v: any, digits = 2, suffix = ''): string {
  const n = Number(v);
  if (v === null || v === undefined || !Number.isFinite(n)) return '—';
  return `${n.toFixed(digits)}${suffix}`;
}

function fmtINR(v: any): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  const sign = n < 0 ? '-' : '';
  const a = Math.abs(n);
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(2)} L`;
  if (a >= 1e3) return `${sign}₹${(a / 1e3).toFixed(1)}k`;
  return `${sign}₹${a.toFixed(0)}`;
}

function MetricCard({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: string; tone?: 'up' | 'down' | 'neutral' | 'accent' }) {
  const color = tone === 'up' ? 'var(--profit)' : tone === 'down' ? 'var(--loss)' : tone === 'accent' ? 'var(--accent-cyan)' : 'var(--text-primary)';
  return (
    <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
      <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: 11, marginBottom: 6, letterSpacing: 0.2 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color, fontFamily: 'var(--font-mono)' }}>{value}</div>
      {sub && <div style={{ color: 'var(--text-muted)', marginTop: 4, fontSize: 10.5 }}>{sub}</div>}
    </div>
  );
}

function HealthGauge({ health }: { health: any }) {
  const score = Number(health?.score);
  if (!Number.isFinite(score)) return null;
  const band = health?.band || '';
  const color = score >= 75 ? 'var(--profit)' : score >= 50 ? 'var(--accent-cyan)' : score >= 25 ? '#fbbf24' : 'var(--loss)';
  const comps = health?.components || {};
  const maxes = health?.max_components || {};
  const order: Array<[string, string]> = [['diversification', 'Diversification'], ['risk_adjusted_return', 'Risk-adj. return'], ['drawdown_resilience', 'Drawdown resilience'], ['volatility', 'Volatility'], ['concentration', 'Concentration']];
  const r = 52, circ = 2 * Math.PI * r, frac = Math.max(0, Math.min(1, score / 100));
  return (
    <div style={{ display: 'flex', gap: 22, alignItems: 'center', flexWrap: 'wrap' }}>
      <div style={{ position: 'relative', width: 132, height: 132, flexShrink: 0 }}>
        <svg width={132} height={132}>
          <circle cx={66} cy={66} r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth={10} />
          <circle cx={66} cy={66} r={r} fill="none" stroke={color} strokeWidth={10} strokeLinecap="round" strokeDasharray={circ} strokeDashoffset={circ * (1 - frac)} transform="rotate(-90 66 66)" />
        </svg>
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ fontSize: 32, fontWeight: 800, color, lineHeight: 1 }}>{score}</div>
          <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>/ 100</div>
        </div>
      </div>
      <div style={{ flex: 1, minWidth: 220 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color, marginBottom: 10 }}>{band}</div>
        {order.map(([k, label]) => {
          const val = Number(comps[k] ?? 0), mx = Number(maxes[k] ?? 1);
          const pct = mx > 0 ? (val / mx) * 100 : 0;
          return (
            <div key={k} style={{ marginBottom: 7 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: 'var(--text-secondary)', marginBottom: 3 }}>
                <span>{label}</span><span style={{ fontFamily: 'var(--font-mono)' }}>{val.toFixed(0)}/{mx}</span>
              </div>
              <div style={{ height: 5, background: 'rgba(255,255,255,0.06)', borderRadius: 3 }}>
                <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 3, transition: 'width .4s' }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function CorrelationHeatmap({ matrix, labels }: { matrix: Array<Array<number | null>>; labels: string[] }) {
  if (!labels?.length || !matrix?.length) return null;
  const short = labels.map(l => l.replace('.NS', '').replace('.BO', '').slice(0, 7));
  const cellColor = (v: number | null) => {
    if (v === null || v === undefined) return 'rgba(255,255,255,0.03)';
    if (v >= 0.7) return 'rgba(251,113,133,0.55)';
    if (v >= 0.4) return 'rgba(251,113,133,0.30)';
    if (v >= 0.1) return 'rgba(251,191,36,0.22)';
    if (v >= -0.1) return 'rgba(255,255,255,0.06)';
    return 'rgba(52,211,153,0.28)';
  };
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', fontSize: 10 }}>
        <thead>
          <tr><th></th>{short.map((s, i) => <th key={i} style={{ padding: '2px 4px', color: 'var(--text-muted)', fontWeight: 600 }}>{s}</th>)}</tr>
        </thead>
        <tbody>
          {matrix.map((row, i) => (
            <tr key={i}>
              <td style={{ padding: '2px 6px', color: 'var(--text-secondary)', fontWeight: 600, whiteSpace: 'nowrap' }}>{short[i]}</td>
              {row.map((v, j) => (
                <td key={j} title={`${short[i]} ↔ ${short[j]}: ${v ?? 'n/a'}`} style={{ background: cellColor(v), color: 'var(--text-primary)', textAlign: 'center', padding: '6px 8px', border: '1px solid rgba(0,0,0,0.25)', fontFamily: 'var(--font-mono)', minWidth: 36 }}>
                  {v === null || v === undefined ? '·' : v.toFixed(2)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DrawdownSparkline({ series }: { series: Array<{ date: string; drawdown_pct: number }> }) {
  if (!series || series.length < 2) return null;
  const w = 100, h = 32;
  const vals = series.map(s => s.drawdown_pct);
  const min = Math.min(...vals, 0);
  const pts = series.map((s, i) => {
    const x = (i / (series.length - 1)) * w;
    const frac = min < 0 ? s.drawdown_pct / min : 0; // 0 at top, deepest=1 at bottom
    const y = frac * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const line = pts.map((p, i) => (i === 0 ? `M ${p}` : `L ${p}`)).join(' ');
  const area = `${line} L ${w},${h} L 0,${h} Z`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ width: '100%', height: 40, display: 'block' }}>
      <path d={area} fill="rgba(251,113,133,0.15)" />
      <path d={line} fill="none" stroke="var(--loss)" strokeWidth={1} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

const FAST_TAPE_NEWS_FALLBACKS: Array<{id: string; source: string; time: string; headline: string; sentiment: 'neutral'; tickers: string[]}> = [];

const readCachedTapeNews = () => {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(TAPE_NEWS_CACHE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch (_) {
    return [];
  }
};

// Every benchmark here has a verified Yahoo Finance history feed. Nifty Smallcap
// 250 and Nifty Next 50 were removed — Yahoo returns no usable history for them —
// and the midcap entry is now labelled correctly (^NSEMDCP50 = Nifty Midcap 50).
const BENCHMARKS = [
  { id: 'NIFTY50', name: 'Nifty 50' },
  { id: 'SENSEX', name: 'SENSEX' },
  { id: 'NIFTYBANK', name: 'Nifty Bank' },
  { id: 'NIFTYIT', name: 'Nifty IT' },
  { id: 'MIDCAP50', name: 'Nifty Midcap 50' },
  { id: 'NIFTY100', name: 'Nifty 100' },
  { id: 'NIFTY500', name: 'Nifty 500' }
];

// Canonical aliases for common ISIN-led symbols seen in eCAS / broker exports.
const SYMBOL_ALIASES: Record<string, string> = {
  INE002A01018: 'RELIANCE',
  INE467B01029: 'TCS',
  INE009A01021: 'INFY',
  INE040A01034: 'HDFCBANK',
  INE154A01025: 'ITC',
  INE021A01026: 'ASIANPAINT',
  INE155A01022: 'TATAMOTORS',
  INE758T01015: 'ZOMATO',
  INE0LP301011: 'PWL',
  INF247L01DA9: 'MOMF'
};

const LEGACY_DEFAULT_WATCHLIST = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'TATAMOTORS', 'ASIANPAINT', 'ZOMATO', 'ITC'];

const isLegacyDefaultWatchlist = (symbols: string[]) => {
  if (symbols.length !== LEGACY_DEFAULT_WATCHLIST.length) return false;
  return LEGACY_DEFAULT_WATCHLIST.every((symbol) => symbols.includes(symbol));
};

const normalizeSeedSymbol = (value: any) =>
  String(value || '').split('.')[0].toUpperCase().trim();

// Legacy browser migrations could resurrect a one-row RELIANCE placeholder into
// manual cache. Treat only that specific shape as seed data and start fresh.
const isLegacyRelianceSeedPortfolio = (positions: any[]) => {
  if (!Array.isArray(positions) || positions.length !== 1) return false;
  const row = positions[0] || {};
  if (normalizeSeedSymbol(row.symbol || row.isin || row.amfi) !== 'RELIANCE') return false;
  const hasLegacyDerivedFields =
    Object.prototype.hasOwnProperty.call(row, 'market_value') &&
    Object.prototype.hasOwnProperty.call(row, 'cost_basis') &&
    Object.prototype.hasOwnProperty.call(row, 'last_price');
  if (!hasLegacyDerivedFields) return false;
  const qty = Number(row.quantity ?? row.qty ?? 0);
  const avgCost = Number(row.avg_cost ?? row.avgCost ?? 0);
  return qty > 0 && avgCost > 0;
};

const toCanonicalSymbol = (rawSymbol: string) => {
  const clean = String(rawSymbol || '').split('.')[0].toUpperCase().trim();
  return SYMBOL_ALIASES[clean] || clean;
};

export const DashboardPortfolioPage: React.FC = () => {
  const navigate = useNavigate();
  const { setOnboarded, user, showToast, isAuthenticated, isReadOnly, syncLocalPortfolio, clearLocalPortfolio, isPro } = useAuth();
  const watchlistStorageKey = useMemo(() => {
    if (isAuthenticated && user?.email) {
      return `prospektlab_watchlist:${user.email.toLowerCase()}`;
    }
    return 'prospektlab_watchlist';
  }, [isAuthenticated, user?.email]);
  const chatStorageScope = useMemo(() => {
    if (isAuthenticated && user?.email) {
      return user.email.toLowerCase();
    }
    return 'guest';
  }, [isAuthenticated, user?.email]);
  const conversationsStorageKey = useMemo(
    () => `prospektlab_conversations:${chatStorageScope}`,
    [chatStorageScope],
  );
  const [portfolio, setPortfolio] = useState<PortfolioItem[]>([]);
  const [portfolioSyncNonce, setPortfolioSyncNonce] = useState(0);
  const [manualOverridePrompt, setManualOverridePrompt] = useState<{
    localCount: number;
    savedCount: number;
  } | null>(null);
  const [isApplyingManualOverride, setIsApplyingManualOverride] = useState(false);
  const [showLoginBanner, setShowLoginBanner] = useState(() => {
    if (typeof window === 'undefined') return true;
    const dismissed = localStorage.getItem('prospektlab_login_banner_dismissed');
    if (!dismissed) return true;
    return Date.now() > parseInt(dismissed, 10);
  });
  const dismissLoginBanner = () => {
    setShowLoginBanner(false);
    localStorage.setItem('prospektlab_login_banner_dismissed', String(Date.now() + 24 * 60 * 60 * 1000));
  };
  const goToLogin = () => {
    navigate('/login?redirect=/dashboard/portfolio');
  };
  const [portfolioOnboardName, setPortfolioOnboardName] = useState(() => {
    if (typeof window === 'undefined') return '';
    return (localStorage.getItem('prospektlab_username') || '').trim();
  });
  const [quotesData, setQuotesData] = useState<Record<string, any>>({});

  // Enriched portfolio resolving ISINs, symbols, sectors and asset classes
  const enrichedPortfolio = useMemo(() => {
    return portfolio.map(item => {
      const cleanSym = item.symbol.split('.')[0].toUpperCase().trim();
      const targetSym = toCanonicalSymbol(cleanSym);
      let displaySymbol = targetSym;
      if (item.symbol.includes('.') && !targetSym.includes('.')) {
        displaySymbol = targetSym + '.' + item.symbol.split('.')[1];
      }

      let resolvedName = item.name;
      let resolvedSector = item.sector;
      let resolvedAssetClass = 'Equity';

      const sectorLower = (item.sector || '').toLowerCase();
      const nameLower = (item.name || '').toLowerCase();

      const isMF =
        // MF folio/ISIN codes start with "INF" and are full 12-char ISINs.
        // Guard against equity tickers like INFY / INFA being caught by the prefix.
        (cleanSym.startsWith('INF') && cleanSym.length >= 10) ||
        targetSym === 'MOMF' ||
        sectorLower === 'mutual fund' || 
        sectorLower === 'mf' ||
        nameLower.includes('fund') || 
        nameLower.includes('mutual') ||
        POPULAR_MUTUAL_FUNDS.some(f => f.symbol.toUpperCase() === targetSym);

      if (isMF) {
        resolvedAssetClass = 'Mutual Fund';
        {
          const mf = POPULAR_MUTUAL_FUNDS.find(
            f => f.symbol.toUpperCase() === targetSym || 
                 f.name.toLowerCase() === nameLower
          );

          if (mf) {
            resolvedName = mf.name;
            resolvedSector = mf.category;
          } else {
            if (cleanSym.startsWith('INF')) {
              resolvedName = item.name !== item.symbol ? item.name : `Mutual Fund (${targetSym})`;
            }
            resolvedSector = item.sector === 'General' || !item.sector ? 'Mutual Fund' : item.sector;
          }
        }
      } else {
        const stock = INDIAN_STOCKS.find(
          s => s.symbol.toUpperCase() === targetSym || 
               s.name.toLowerCase() === nameLower
        );

        if (stock) {
          resolvedName = stock.name;
          resolvedSector = stock.sector === 'Other' || !stock.sector ? 'General' : stock.sector;
        } else {
          resolvedName = item.name !== item.symbol ? item.name : targetSym;
        }
        
        if (item.sector && item.sector !== 'General' && item.sector !== 'Other') {
          resolvedSector = item.sector;
        } else if (resolvedSector === 'Other') {
          resolvedSector = 'General';
        }
      }

      // Override default/General sector with real sector from backend quotes if available
      const realQuote = quotesData[targetSym];
      if (realQuote && realQuote.sector && realQuote.sector !== 'General' && realQuote.sector !== 'Other') {
        resolvedSector = realQuote.sector;
      }

      let currentPrice = item.current || 0;
      if (currentPrice === 0) {
        currentPrice = item.avgCost || 0;
      }

      let avgCost = item.avgCost || 0;
      if (avgCost === 0 && currentPrice > 0) {
        avgCost = currentPrice;
      }

      return {
        ...item,
        symbol: displaySymbol,
        name: resolvedName,
        sector: resolvedSector,
        assetClass: resolvedAssetClass,
        avgCost: avgCost,
        current: currentPrice
      };
    });
  }, [portfolio, quotesData]);
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [watchlistStocks, setWatchlistStocks] = useState<WatchlistStock[]>([]);
  const [conversations, setConversations] = useState<any[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string>('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [thinkingEvents, setThinkingEvents] = useState<AgentEventData[]>([]);
  // Pre-filled chat query state (set by external dashboard buttons instead of auto-executing)
  const [pendingChatQuery, setPendingChatQuery] = useState<{ id: string; text: string; depth: 'standard' | 'deep' } | null>(null);
  const [isChatHighlighted, setIsChatHighlighted] = useState(false);
  const [assetHistoryTarget, setAssetHistoryTarget] = useState<AssetHistoryTarget | null>(null);
  const [activeTab, setActiveTab] = useState<'portfolio' | 'watchlist'>('portfolio');
  // Chart benchmark states
  const [selectedBenchmark, setSelectedBenchmark] = useState<string>('NIFTY50');
  const [isBenchmarkMenuOpen, setIsBenchmarkMenuOpen] = useState(false);
  const benchmarkSelectorRef = useRef<HTMLDivElement>(null);

  // Resizable chat rail state
  const [chatWidth, setChatWidth] = useState<number>(() => {
    const saved = localStorage.getItem('prospektlab_chat_width');
    return saved ? parseInt(saved, 10) : 380;
  });
  const [isDraggingChat, setIsDraggingChat] = useState(false);
  const [isChatHidden, setIsChatHidden] = useState(() => {
    const savedWidth = localStorage.getItem('prospektlab_chat_width');
    return savedWidth ? parseInt(savedWidth, 10) <= 0 : false;
  });

  // Analytics tab state
  const [analyticsTab, setAnalyticsTab] = useState<'mf' | 'risk' | 'stress' | 'corr' | 'tax'>('risk');
  // mfData removed as diagnostics now uses enriched portfolio metrics
  const [actionQueue, setActionQueue] = useState<any[]>([]);

  const getMessageStorageKey = (conversationId: string) =>
    `prospektlab_messages:${chatStorageScope}:${conversationId}`;

  const readStoredMessages = (conversationId: string): string | null => {
    const scopedKey = getMessageStorageKey(conversationId);
    const scopedRaw = localStorage.getItem(scopedKey);
    if (scopedRaw) return scopedRaw;
    if (isAuthenticated) return null;
    const legacyKey = `prospektlab_messages_${conversationId}`;
    const legacyRaw = localStorage.getItem(legacyKey);
    if (legacyRaw) {
      localStorage.setItem(scopedKey, legacyRaw);
      localStorage.removeItem(legacyKey);
    }
    return legacyRaw;
  };

  useEffect(() => {
    if (!isPro || typeof window === 'undefined') return;

    const storageKeys: string[] = [];
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (!key) continue;
      if (key.startsWith('prospektlab_messages:') || key.startsWith('prospektlab_messages_')) {
        storageKeys.push(key);
      }
    }

    for (const key of storageKeys) {
      try {
        const raw = localStorage.getItem(key);
        if (!raw) continue;
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) continue;
        const cleaned = parsed.filter((msg: any) => msg?.tokenLimitDetail?.code !== 'DEEP_PREMIUM_REQUIRED');
        if (cleaned.length !== parsed.length) {
          localStorage.setItem(key, JSON.stringify(cleaned));
        }
      } catch (e) {
        // Ignore malformed historical payloads and continue.
      }
    }

    setMessages((prev) => prev.filter((msg) => msg.tokenLimitDetail?.code !== 'DEEP_PREMIUM_REQUIRED'));
  }, [isPro]);

  // SSE tracking
  const abortStreamRef = useRef<(() => void) | null>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  // Live index data (simulated real-time like Google Finance)
  const [liveIndexData, setLiveIndexData] = useState<Record<string, IndexTickerData[]>>({
    india: [],
    us: [],
    currencies: [],
    crypto: [],
    futures: [],
  });
  const [indicesLoading, setIndicesLoading] = useState(true);
  const [indicesError, setIndicesError] = useState<string | null>(null);

  const [tokenUsage, setTokenUsage] = useState<any>(null);
  const [newsFeed, setNewsFeed] = useState<any[]>(() => readCachedTapeNews());
  const [newsLoading, setNewsLoading] = useState(() => readCachedTapeNews().length === 0);
  const [newsError, setNewsError] = useState<string | null>(null);

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      if (!benchmarkSelectorRef.current?.contains(event.target as Node)) {
        setIsBenchmarkMenuOpen(false);
      }
    };
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, []);
  const [portfolioAnalytics, setPortfolioAnalytics] = useState<any>(null);
  const [portfolioAnalyticsError, setPortfolioAnalyticsError] = useState<string | null>(null);
  const [mfAnalytics, setMfAnalytics] = useState<any>(null);
  const [taxSummary, setTaxSummary] = useState<any>(null);
  const [commentary, setCommentary] = useState<any>(null);
  const [stressResult, setStressResult] = useState<any>(null);
  const [stressScenario, setStressScenario] = useState<string>('nifty_down_20');
  const [stressShock, setStressShock] = useState<number>(-20);
  const [stressLoading, setStressLoading] = useState<boolean>(false);
  const [portfolioMirrorVersion, setPortfolioMirrorVersion] = useState(0);

  // Fetch token usage helper
  const fetchTokenUsage = async () => {
    try {
      const data = await getUserTokenUsage();
      if (data) {
        setTokenUsage(data);
      }
    } catch (e) {
      console.error('Failed to fetch token usage', e);
    }
  };

  // Compute allStockData dynamically from real-time backend quotes
  const allStockData = useMemo(() => {
    const data: Record<string, { name: string; price: string; change: string; changePct: number; sector: string }> = {};
    Object.keys(quotesData).forEach(sym => {
      const q = quotesData[sym];
      const price = Number(q.price);
      const changePct = Number(q.change_pct);
      const hasPrice = Number.isFinite(price) && price > 0;
      const normalized = String(sym || '').split('.')[0].toUpperCase().trim();
      const changeVal = hasPrice ? price * ((Number.isFinite(changePct) ? changePct : 0) / 100) : 0;
      const row = {
        name: q.company_name || `${sym} Limited`,
        price: hasPrice ? price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—',
        change: hasPrice ? `${changeVal >= 0 ? '+' : ''}${changeVal.toFixed(2)}` : '—',
        changePct: Number.isFinite(changePct) ? changePct : 0,
        sector: q.sector || 'General'
      };
      data[sym] = row;
      if (normalized) {
        data[normalized] = row;
      }
    });
    return data;
  }, [quotesData]);

  // Portfolio-only symbol set (normalized base tickers). Used to scope news and
  // movers strictly to holdings so Watchlist data never bleeds into the Portfolio.
  const portfolioSymbols = useMemo(
    () => Array.from(new Set(enrichedPortfolio.map(p => normalizeMarketSymbol(p.symbol)))),
    [enrichedPortfolio]
  );

  // Combined set is used ONLY for fetching live quotes (the Watchlist tab still
  // needs prices for its own symbols). It is never used to scope portfolio data.
  const userUniverseSymbols = useMemo(() => {
    const watchlistSymbols = watchlist.map(w => normalizeMarketSymbol(w));
    return Array.from(new Set([...portfolioSymbols, ...watchlistSymbols]));
  }, [portfolioSymbols, watchlist]);

  const mapTapeNewsItems = (items: any[], sourcePrefix = 'n') => {
    return (items || []).map((item: any, idx: number) => {
      const title = item.title || item.headline || '';
      const description = item.description || item.snippet || '';
      const txt = `${title} ${description}`.toLowerCase();
      let sentiment: 'bullish' | 'bearish' | 'neutral' = 'neutral';
      if (txt.includes('surge') || txt.includes('gain') || txt.includes('rise') || txt.includes('bull') || txt.includes('growth') || txt.includes('higher') || txt.includes('up')) {
        sentiment = 'bullish';
      } else if (txt.includes('fall') || txt.includes('drop') || txt.includes('slip') || txt.includes('decline') || txt.includes('bear') || txt.includes('lower') || txt.includes('down')) {
        sentiment = 'bearish';
      }

      // Tag tickers using ONLY portfolio holdings — watchlist symbols must never
      // surface in the Portfolio news feed.
      const tickers = new Set<string>();
      portfolioSymbols.forEach(sym => {
        const base = sym.toLowerCase();
        const name = (INDIAN_STOCKS.find(s => s.symbol.toUpperCase() === sym)?.name || '').toLowerCase();
        if (base && (txt.includes(base) || (name && txt.includes(name)))) {
          tickers.add(sym);
        }
      });
      const holdingSymbol = item.related_holding?.symbol;
      if (holdingSymbol) {
        const normalizedHolding = normalizeMarketSymbol(holdingSymbol);
        if (portfolioSymbols.includes(normalizedHolding)) tickers.add(normalizedHolding);
      }

      return {
        id: item.id || `${sourcePrefix}-${idx}-${title.slice(0, 16)}`,
        source: item.source || item.source_host || 'News',
        time: item.age_label || item.published || item.published_at || 'Just now',
        headline: title,
        sentiment,
        tickers: Array.from(tickers),
        // From the dedicated portfolio-news endpoint OR a market item that names
        // a holding. Used to keep the feed strictly holding-relevant.
        holdingRelevant: Boolean(item.related_holding) || tickers.size > 0,
      };
    }).filter((item: any) => item.headline);
  };

  useEffect(() => {
    const mapped: WatchlistStock[] = watchlist.map((rawSymbol) => {
      const symbol = normalizeMarketSymbol(rawSymbol);
      const info = allStockData[symbol] || allStockData[rawSymbol];
      const stock = INDIAN_STOCKS.find((s) => s.symbol.toUpperCase() === symbol);
      return {
        symbol,
        name: info?.name || stock?.name || `${symbol} Limited`,
        price: info?.price ?? '—',
        change: info?.change ?? '—',
        changePct: Number.isFinite(Number(info?.changePct)) ? Number(info?.changePct) : 0,
      };
    });
    setWatchlistStocks(mapped);
  }, [watchlist, allStockData]);

  // Fetch quotes whenever user universe changes or periodically
  useEffect(() => {
    if (userUniverseSymbols.length === 0) return;
    const fetchQuotes = async () => {
      try {
        const data = await getMarketQuotes(userUniverseSymbols);
        if (data) {
          setQuotesData(data);
        }
      } catch (e) {
        console.error('Failed to fetch market quotes', e);
      }
    };
    fetchQuotes();
    const interval = setInterval(fetchQuotes, 20000);
    return () => clearInterval(interval);
  }, [userUniverseSymbols]);

  useEffect(() => {
    let cancelled = false;
    const fetchRealtimePortfolioAnalytics = async () => {
      try {
        const data = await getPortfolioAnalytics(selectedBenchmark, '1Y');
        if (!data || cancelled) return;
        setPortfolioAnalytics(data);
        setPortfolioAnalyticsError(null);

        if (Array.isArray(data.positions) && data.positions.length > 0) {
          const mapped: PortfolioItem[] = data.positions.map((p: any) => {
            const cleanSym = String(p.symbol || '').split('.')[0].toUpperCase().trim();
            const stock = INDIAN_STOCKS.find(s => s.symbol.toUpperCase() === cleanSym);
            const mf = POPULAR_MUTUAL_FUNDS.find(f => f.symbol.toUpperCase() === cleanSym);
            const quantity = Number(p.quantity) || 0;
            const marketValue = positiveNumber(p.market_value);
            const livePrice = positiveNumber(p.last_price, quantity > 0 ? marketValue / quantity : 0);
            const costBasis = Number(p.cost_basis) || 0;
            const avgCost = Number(p.avg_cost) || (quantity > 0 ? costBasis / quantity : 0);
            const assetClass = p.kind === 'mf' || mf ? 'Mutual Fund' : 'Equity';
            return {
              symbol: cleanSym || String(p.symbol || ''),
              name: p.name || stock?.name || mf?.name || cleanSym || 'Holding',
              qty: quantity,
              avgCost,
              current: livePrice,
              sector: p.sector || stock?.sector || mf?.category || 'General',
              assetClass,
              dayChangePct: finiteNumber(p.day_change_pct) * 100,
            };
          });
          setPortfolio(mapped);
        }
      } catch (e: any) {
        if (!cancelled) {
          setPortfolioAnalyticsError(e?.message || 'Failed to load live portfolio analytics');
          console.error('Failed to fetch live portfolio analytics', e);
        }
      }
    };

    fetchRealtimePortfolioAnalytics();
    const interval = setInterval(fetchRealtimePortfolioAnalytics, 60000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [selectedBenchmark, portfolioMirrorVersion]);

  // Fetch indices on mount and periodically
  useEffect(() => {
    let cancelled = false;
    const fetchIndices = async () => {
      try {
        setIndicesError(null);
        const data = await getMarketIndices();
        if (data && !cancelled) {
          setLiveIndexData(data);
          setIndicesLoading(false);
        }
      } catch (e: any) {
        if (!cancelled) {
          console.error('Failed to fetch market indices', e);
          setIndicesError(e.message || 'Failed to load market indices');
          setIndicesLoading(false);
        }
      }
    };
    fetchIndices();
    const interval = setInterval(fetchIndices, 60000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  // Fetch news on mount and periodically
  useEffect(() => {
    let cancelled = false;
    const fetchNews = async () => {
      const cached = readCachedTapeNews();
      if (cached.length > 0 && !cancelled) {
        setNewsFeed(cached);
        setNewsLoading(false);
      } else if (!cancelled) {
        setNewsFeed(FAST_TAPE_NEWS_FALLBACKS);
        setNewsLoading(false);
      }

      try {
        setNewsError(null);
        const hasHoldings = portfolioSymbols.length > 0;
        const marketPromise = getMarketNews("India market");
        const portfolioPromise = getPortfolioNews(8).catch((err) => {
          console.warn('Portfolio news refresh failed', err);
          return null;
        });
        const marketData = await marketPromise;
        if (cancelled) return;

        const marketItems = mapTapeNewsItems(marketData, 'm');

        if (!hasHoldings) {
          // No holdings to scope to — fall back to general India-market news.
          if (marketItems.length > 0) {
            setNewsFeed(marketItems);
            localStorage.setItem(TAPE_NEWS_CACHE_KEY, JSON.stringify(marketItems));
          }
          const portfolioDataNoHold = await portfolioPromise;
          if (cancelled || !portfolioDataNoHold) return;
          return;
        }

        const portfolioData = await portfolioPromise;
        if (cancelled) return;

        // Holding-relevant only: dedicated portfolio-news items + market items
        // that explicitly name one of the user's holdings. Generic market noise
        // is dropped so the feed stays scoped to the portfolio.
        const portfolioItems = mapTapeNewsItems(portfolioData?.items || [], 'p');
        const relevantMarketItems = marketItems.filter((item: any) => item.holdingRelevant);
        const deduped = [...portfolioItems, ...relevantMarketItems].filter((item, idx, arr) =>
          idx === arr.findIndex((candidate) => candidate.headline === item.headline)
        ).slice(0, 10);

        if (deduped.length > 0) {
          setNewsFeed(deduped);
          localStorage.setItem(TAPE_NEWS_CACHE_KEY, JSON.stringify(deduped));
          setNewsError(null);
        } else {
          // Holdings exist but no holding-relevant news right now — show an empty
          // feed rather than leaking unrelated market headlines.
          setNewsFeed([]);
          localStorage.removeItem(TAPE_NEWS_CACHE_KEY);
        }
      } catch (e: any) {
        if (!cancelled) {
          console.error('Failed to fetch market news', e);
          if (newsFeed.length === 0) {
            setNewsError(e.message || 'Failed to load market news');
          }
        }
      }
    };
    fetchNews();
    const interval = setInterval(fetchNews, 300000); // 5 minutes
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
    // Scope to portfolio holdings only — watchlist changes must not refetch/retarget
    // the portfolio news feed. Joined key keeps the dep stable across renders.
  }, [portfolioSymbols.join(',')]);

  // Fetch token usage on mount
  useEffect(() => {
    fetchTokenUsage();
  }, []);

  // Drag listeners for Chat Resizing
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDraggingChat) return;
      let newWidth = window.innerWidth - e.clientX;

      if (newWidth < 60) {
        newWidth = 0;
        setIsChatHidden(true);
      } else {
        setIsChatHidden(false);
        if (newWidth > 480) {
          newWidth = 480;
        }
      }
      setChatWidth(newWidth);
      localStorage.setItem('prospektlab_chat_width', newWidth.toString());
    };

    const handleMouseUp = () => {
      setIsDraggingChat(false);
    };

    if (isDraggingChat) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
    }

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDraggingChat]);

  // Load state and portfolio details
  useEffect(() => {
    const syncPortfolio = async () => {
      const mapMirrorPosition = (p: any): PortfolioItem | null => {
        const rawSymbol = String(p?.symbol || p?.isin || p?.amfi || '').trim();
        if (!rawSymbol) return null;
        const qty = Number(p?.quantity) || 0;
        const marketVal = Number(p?.market_value) || 0;
        const costBasis = Number(p?.cost_basis) || 0;
        let currentPrice = Number(p?.last_price) || 0;
        if (currentPrice <= 0 && qty > 0 && marketVal > 0) {
          currentPrice = marketVal / qty;
        }
        if (currentPrice <= 0 && qty > 0 && costBasis > 0) {
          currentPrice = costBasis / qty;
        }
        let avgCost = Number(p?.avg_cost) || 0;
        if (avgCost <= 0 && qty > 0 && costBasis > 0) {
          avgCost = costBasis / qty;
        }
        if (avgCost <= 0 && currentPrice > 0) {
          avgCost = currentPrice;
        }

        const cleanSym = rawSymbol.split('.')[0].toUpperCase().trim();
        const targetSym = toCanonicalSymbol(cleanSym);
        let resolvedName = String(p?.name || targetSym);
        let resolvedSector = String(p?.sector || '').trim();
        const mf = POPULAR_MUTUAL_FUNDS.find((f) => f.symbol.toUpperCase() === targetSym);
        if (mf) {
          resolvedName = mf.name;
          resolvedSector = mf.category;
        } else {
          const stock = INDIAN_STOCKS.find((s) => s.symbol.toUpperCase() === targetSym);
          if (stock) {
            resolvedName = stock.name;
            resolvedSector = stock.sector === 'Other' || !stock.sector ? 'General' : stock.sector;
          }
        }

        return {
          symbol: targetSym,
          name: resolvedName,
          qty,
          avgCost,
          current: currentPrice,
          sector: resolvedSector || 'General',
        };
      };

      const mapManualLocalPosition = (p: any): PortfolioItem | null => {
        const rawSymbol = String(p?.symbol || '').trim();
        if (!rawSymbol) return null;
        const qty = Number(p?.quantity ?? p?.qty) || 0;
        const avgCost = Number(p?.avg_cost ?? p?.avgCost) || 0;
        if (qty <= 0 || avgCost <= 0) return null;
        const cleanSym = rawSymbol.split('.')[0].toUpperCase().trim();
        const targetSym = toCanonicalSymbol(cleanSym);
        const stock = INDIAN_STOCKS.find((s) => s.symbol.toUpperCase() === targetSym);
        return {
          symbol: targetSym,
          name: String(p?.name || stock?.name || targetSym),
          qty,
          avgCost,
          current: avgCost,
          sector: String(p?.sector || stock?.sector || 'General'),
        };
      };

      // Authenticated users: load from backend mirror, and only sync local
      // manual holdings when the mirror is still empty.
      if (isAuthenticated) {
        try {
          let res = await getPortfolioMirror();
          let mirrorPositions = Array.isArray(res?.positions) ? res.positions : [];
          const manualRaw = localStorage.getItem('prospektlab_manual_portfolio');
          let manualPositions: any[] = [];
          if (manualRaw) {
            try {
              const parsed = JSON.parse(manualRaw);
              if (Array.isArray(parsed)) {
                manualPositions = parsed;
                if (isLegacyRelianceSeedPortfolio(manualPositions)) {
                  manualPositions = [];
                  localStorage.removeItem('prospektlab_manual_portfolio');
                  localStorage.removeItem('prospektlab_portfolio');
                }
              }
            } catch (err) {
              console.error('Failed to parse manual local portfolio cache', err);
            }
          }
          const legacyRaw = localStorage.getItem('prospektlab_portfolio');
          let legacyPositions: any[] = [];
          if (legacyRaw) {
            try {
              const parsedLegacy = JSON.parse(legacyRaw);
              if (Array.isArray(parsedLegacy)) {
                legacyPositions = parsedLegacy;
                if (isLegacyRelianceSeedPortfolio(legacyPositions)) {
                  legacyPositions = [];
                  localStorage.removeItem('prospektlab_portfolio');
                }
              }
            } catch (legacyErr) {
              console.error('Failed to parse legacy local portfolio cache', legacyErr);
            }
          }

          if (mirrorPositions.length === 0 && (manualPositions.length > 0 || legacyPositions.length > 0)) {
            let synced = false;
            if (manualPositions.length > 0) {
              synced = await syncLocalPortfolio();
            } else {
              const legacyMapped = legacyPositions
                .map(mapManualLocalPosition)
                .filter((item: PortfolioItem | null): item is PortfolioItem => Boolean(item));
              const backfillPayload = buildMirrorBackfillPayload(legacyMapped);
              if (backfillPayload.length > 0) {
                try {
                  await replacePortfolioMirror(backfillPayload);
                  synced = true;
                  showToast('Recovered your local holdings and synchronized them to cloud.', 'success');
                } catch (legacySyncErr) {
                  console.error('Failed to backfill legacy local portfolio cache', legacySyncErr);
                }
              }
              if (!synced && legacyMapped.length > 0) {
                setPortfolio(legacyMapped);
                localStorage.setItem('prospektlab_portfolio', JSON.stringify(legacyMapped));
                setPortfolioMirrorVersion((version) => version + 1);
                setOnboarded(true);
                showToast('Loaded your locally cached holdings. Cloud sync is pending.', 'info');
                return;
              }
            }
            if (synced) {
              res = await getPortfolioMirror();
              mirrorPositions = Array.isArray(res?.positions) ? res.positions : [];
              const refreshedManualRaw = localStorage.getItem('prospektlab_manual_portfolio');
              if (!refreshedManualRaw) {
                manualPositions = [];
              }
              if (mirrorPositions.length > 0) {
                legacyPositions = [];
              }
            } else {
              const localMapped = manualPositions
                .map(mapManualLocalPosition)
                .filter((item: PortfolioItem | null): item is PortfolioItem => Boolean(item));
              if (localMapped.length > 0) {
                setPortfolio(localMapped);
                localStorage.setItem('prospektlab_portfolio', JSON.stringify(localMapped));
                setPortfolioMirrorVersion((version) => version + 1);
                setOnboarded(true);
                showToast('Loaded your locally entered holdings. Cloud sync is pending.', 'info');
                return;
              }
            }
          }

          if (mirrorPositions.length > 0) {
            const mapped = mirrorPositions
              .map(mapMirrorPosition)
              .filter((item: PortfolioItem | null): item is PortfolioItem => Boolean(item));
            if (mapped.length > 0) {
              setPortfolio(mapped);
              localStorage.setItem('prospektlab_portfolio', JSON.stringify(mapped));
              if (manualPositions.length > 0) {
                setManualOverridePrompt({
                  localCount: manualPositions.length,
                  savedCount: mirrorPositions.length,
                });
              } else {
                setManualOverridePrompt(null);
              }
              setPortfolioMirrorVersion((version) => version + 1);
              setOnboarded(true);
              return;
            }
          }

          // Mirror is empty for this authenticated user.
          if (manualPositions.length === 0 && legacyPositions.length === 0) {
            localStorage.removeItem('prospektlab_portfolio');
          }
          setManualOverridePrompt(null);
          setPortfolio([]);
          setOnboarded(false);
        } catch (e) {
          console.error('Failed to sync portfolio from mirror', e);
          const savedPortfolioRaw = localStorage.getItem('prospektlab_portfolio');
          try {
            const savedPortfolio = savedPortfolioRaw ? JSON.parse(savedPortfolioRaw) : [];
            if (Array.isArray(savedPortfolio) && savedPortfolio.length > 0) {
              if (isLegacyRelianceSeedPortfolio(savedPortfolio)) {
                localStorage.removeItem('prospektlab_portfolio');
              } else {
                setPortfolio(savedPortfolio);
                setPortfolioMirrorVersion((version) => version + 1);
                setOnboarded(true);
                return;
              }
            }
          } catch (storageErr) {
            console.error('Failed to recover local portfolio snapshot', storageErr);
          }
          try {
            const manualRaw = localStorage.getItem('prospektlab_manual_portfolio');
            const manual = manualRaw ? JSON.parse(manualRaw) : [];
            if (Array.isArray(manual) && manual.length > 0) {
              if (isLegacyRelianceSeedPortfolio(manual)) {
                localStorage.removeItem('prospektlab_manual_portfolio');
                localStorage.removeItem('prospektlab_portfolio');
              } else {
                const localMapped = manual
                .map(mapManualLocalPosition)
                .filter((item: PortfolioItem | null): item is PortfolioItem => Boolean(item));
                if (localMapped.length > 0) {
                  setPortfolio(localMapped);
                  localStorage.setItem('prospektlab_portfolio', JSON.stringify(localMapped));
                  setPortfolioMirrorVersion((version) => version + 1);
                  setOnboarded(true);
                  showToast('Showing local holdings because portfolio sync is temporarily unavailable.', 'info');
                  return;
                }
              }
            }
          } catch (manualErr) {
            console.error('Failed to recover manual local portfolio snapshot', manualErr);
          }
          setManualOverridePrompt(null);
          setPortfolio([]);
          setOnboarded(false);
        }
        return;
      }

      // Read-only / unauthenticated users: load from manual portfolio localStorage.
      setManualOverridePrompt(null);
      const manualRaw = localStorage.getItem('prospektlab_manual_portfolio');
      try {
        const manual = manualRaw ? JSON.parse(manualRaw) : [];
        if (Array.isArray(manual) && manual.length > 0) {
          if (isLegacyRelianceSeedPortfolio(manual)) {
            localStorage.removeItem('prospektlab_manual_portfolio');
            localStorage.removeItem('prospektlab_portfolio');
            setPortfolio([]);
            return;
          }
          const mapped: PortfolioItem[] = manual.map((p: any) => ({
            symbol: p.symbol || '',
            name: p.name || p.symbol || '',
            qty: Number(p.quantity || p.qty || 0),
            avgCost: Number(p.avg_cost || p.avgCost || 0),
            current: Number(p.avg_cost || p.avgCost || 0),
            sector: p.sector || 'General',
          }));
          setPortfolio(mapped);
          setPortfolioMirrorVersion((version) => version + 1);
          return;
        }
      } catch (err) {
        console.error('Failed to parse manual portfolio', err);
      }
      setPortfolio([]);
    };
    syncPortfolio();

    // Load watchlist symbols from scoped storage.
    const savedWatchlistRaw = localStorage.getItem(watchlistStorageKey);
    const savedWatchlist: string[] = savedWatchlistRaw ? JSON.parse(savedWatchlistRaw) : [];
    const normalizedWatchlist = savedWatchlist
      .map((s) => String(s || '').split('.')[0].toUpperCase().trim())
      .filter((s) => s.length > 0);
    const dedupedWatchlist = Array.from(new Set(normalizedWatchlist));
    if (isLegacyDefaultWatchlist(dedupedWatchlist)) {
      localStorage.removeItem(watchlistStorageKey);
      setWatchlist([]);
    } else {
      setWatchlist(dedupedWatchlist);
    }

    // Load past conversations from user-scoped storage.
    let savedConversations: any[] = [];
    try {
      const scopedRaw = localStorage.getItem(conversationsStorageKey);
      if (scopedRaw) {
        savedConversations = JSON.parse(scopedRaw);
      } else if (!isAuthenticated) {
        const legacyRaw = localStorage.getItem('prospektlab_conversations');
        savedConversations = legacyRaw ? JSON.parse(legacyRaw) : [];
        if (savedConversations.length > 0) {
          localStorage.setItem(conversationsStorageKey, JSON.stringify(savedConversations));
          localStorage.removeItem('prospektlab_conversations');
        }
      }
    } catch (e) {
      console.error(e);
    }
    setConversations(savedConversations);

    // Pick active conversation
    if (savedConversations.length > 0) {
      const firstConv = savedConversations[0];
      if (firstConv.id === '1') {
        const migratedId = `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        firstConv.id = migratedId;
        const savedMessagesRaw = readStoredMessages('1');
        if (savedMessagesRaw) {
          localStorage.setItem(getMessageStorageKey(migratedId), savedMessagesRaw);
          localStorage.removeItem(getMessageStorageKey('1'));
          localStorage.removeItem('prospektlab_messages_1');
        }
        localStorage.setItem(conversationsStorageKey, JSON.stringify(savedConversations));
        setConversations([...savedConversations]);
      }
      setActiveConversationId(firstConv.id);
      const savedMessagesRaw = readStoredMessages(firstConv.id);
      if (savedMessagesRaw) {
        try {
          setMessages(JSON.parse(savedMessagesRaw));
        } catch (e) {
          bootstrapWelcomeMessage(firstConv.id);
        }
      } else {
        bootstrapWelcomeMessage(firstConv.id);
      }
    } else {
      const newId = `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const newConv = { id: newId, title: 'Equity Analysis Session', date: 'Today' };
      const updatedConvs = [newConv];
      setConversations(updatedConvs);
      localStorage.setItem(conversationsStorageKey, JSON.stringify(updatedConvs));
      setActiveConversationId(newId);
      bootstrapWelcomeMessage(newId);
    }

    // Backend analytics only for authenticated users
    if (isAuthenticated) {
      fetchBackendAnalytics();
    }
  }, [isAuthenticated, setOnboarded, syncLocalPortfolio, watchlistStorageKey, conversationsStorageKey, portfolioSyncNonce]);

  const fetchBackendAnalytics = async () => {
    // Each widget fetch is independent — one failure must not blank the others.
    getMfAnalytics().then(setMfAnalytics).catch(() => {});
    getTodayQueue().then(q => setActionQueue(q.items || [])).catch(() => {});
    getTaxSummary().then(setTaxSummary).catch(() => {});
    getPortfolioCommentary().then(setCommentary).catch(() => {});
  };

  const runStressTest = async (scenario: string, customShockPct?: number) => {
    setStressLoading(true);
    try {
      const isCustom = customShockPct !== undefined;
      const custom = isCustom ? { nifty: (customShockPct as number) / 100 } : undefined;
      const res = await postStressTest(isCustom ? 'custom' : scenario, custom);
      if (res && isCustom) res.scenario_label = `Custom · Nifty ${customShockPct}%`;
      setStressResult(res);
      setStressScenario(isCustom ? 'custom' : scenario);
    } catch (e) {
      console.log('Stress test failed', e);
    } finally {
      setStressLoading(false);
    }
  };

  const bootstrapWelcomeMessage = (convId: string) => {
    const welcomeMsgs: Message[] = [
      {
        sender: 'ai',
        text: `Arthik here. I don't do hope — I do numbers. Ask me anything about your book, a ticker, or the tape.`
      }
    ];
    setMessages(welcomeMsgs);
    localStorage.setItem(getMessageStorageKey(convId), JSON.stringify(welcomeMsgs));
  };

  const createConversationId = () =>
    `conv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  const createConversationDraft = (existingConversations: any[] = conversations) => {
    const newId = createConversationId();
    const newConv = { id: newId, title: 'Equity Analysis Session', date: 'Today' };
    const updatedConversations = [newConv, ...existingConversations];
    setConversations(updatedConversations);
    localStorage.setItem(conversationsStorageKey, JSON.stringify(updatedConversations));
    setActiveConversationId(newId);
    bootstrapWelcomeMessage(newId);
    return newId;
  };

  // Keep the newest chat turn visible as messages and live pipeline events arrive.
  useEffect(() => {
    const node = chatContainerRef.current;
    if (!node) return;

    const scrollToBottom = () => {
      node.scrollTop = node.scrollHeight;
    };

    const frame = window.requestAnimationFrame(scrollToBottom);
    const timer = window.setTimeout(scrollToBottom, 120);

    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [messages.length, isThinking, thinkingEvents.length]);

  // Live index simulation removed - data is now loaded live from the backend API

  const finiteNumber = (value: any, fallback = 0) => {
    if (value === null || value === undefined || value === '') return fallback;
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  };

  const positiveNumber = (value: any, fallback = 0) => {
    const n = finiteNumber(value, Number.NaN);
    return Number.isFinite(n) && n > 0 ? n : fallback;
  };

  const normalizeMarketSymbol = (symbol: string) =>
    String(symbol || '').split('.')[0].toUpperCase().trim();

  const lookupLiveQuote = (symbol: string) => {
    const base = normalizeMarketSymbol(symbol);
    return (
      quotesData[symbol] ||
      quotesData[base] ||
      quotesData[`${base}.NS`] ||
      quotesData[`${base}.BO`] ||
      null
    );
  };

  const analyticsPositions = Array.isArray(portfolioAnalytics?.positions) ? portfolioAnalytics.positions : [];

  const isGenericSector = (sector: any) => {
    const normalized = String(sector || '').trim().toLowerCase();
    return !normalized || ['general', 'other', 'unknown', 'n/a', 'na'].includes(normalized);
  };

  const resolvePortfolioSector = (symbol: string, name?: string, currentSector?: string, kind?: string) => {
    if (!isGenericSector(currentSector)) return String(currentSector).trim();
    const cleanSym = normalizeMarketSymbol(symbol);
    const nameLower = String(name || '').toLowerCase();
    const localHolding = enrichedPortfolio.find((p) => normalizeMarketSymbol(p.symbol) === cleanSym);
    if (localHolding && !isGenericSector(localHolding.sector)) return localHolding.sector;
    const stock = INDIAN_STOCKS.find(
      (s) => s.symbol.toUpperCase() === cleanSym || s.name.toLowerCase() === nameLower
    );
    if (stock && !isGenericSector(stock.sector)) return stock.sector;
    const mf = POPULAR_MUTUAL_FUNDS.find(
      (f) => f.symbol.toUpperCase() === cleanSym || f.name.toLowerCase() === nameLower
    );
    if (mf) return mf.category || 'Mutual Fund';
    if (String(kind || '').toLowerCase() === 'mf') return 'Mutual Fund';
    return 'General';
  };

  // Calculations for total portfolio NAV summary from backend live analytics first,
  // with quote-normalized local holdings as fallback while analytics loads.
  const computedPortfolioDetails: Array<PortfolioItem & { currentValue: number; pnl: number; pnlPct: number; dayChangePct?: number }> = (analyticsPositions.length > 0
    ? analyticsPositions.map((p: any) => {
        const symbol = normalizeMarketSymbol(p.symbol || '');
        const liveQuote = lookupLiveQuote(symbol);
        const qty = finiteNumber(p.quantity);
        const backendMarketValue = positiveNumber(p.market_value);
        const backendUnitPrice = positiveNumber(p.last_price, qty > 0 ? backendMarketValue / qty : 0);
        const current = positiveNumber(liveQuote?.price, backendUnitPrice);
        const currentValue = qty > 0 && current > 0 ? qty * current : backendMarketValue;
        const costBasis = finiteNumber(p.cost_basis);
        const pnl = costBasis > 0 ? currentValue - costBasis : finiteNumber(p.unrealized_pnl, currentValue - costBasis);
        const pnlPct = finiteNumber(p.unrealized_pnl_pct) * 100;
        return {
          symbol,
          name: p.name || symbol,
          qty,
          avgCost: finiteNumber(p.avg_cost, qty > 0 ? costBasis / qty : 0),
          current,
          sector: resolvePortfolioSector(symbol, p.name, p.sector, p.kind),
          assetClass: p.kind === 'mf' ? 'Mutual Fund' : 'Equity',
          currentValue,
          pnl,
          pnlPct: costBasis > 0 ? (pnl / costBasis) * 100 : pnlPct,
          dayChangePct: finiteNumber(liveQuote?.change_pct, finiteNumber(p.day_change_pct) * 100),
        };
      })
    : enrichedPortfolio.map(item => {
        const liveQuote = lookupLiveQuote(item.symbol);
        const livePrice = positiveNumber(liveQuote?.price, positiveNumber(item.current, item.avgCost));
        const costBasis = item.qty * item.avgCost;
        const currentValue = item.qty * livePrice;
        const pnl = currentValue - costBasis;
        const pnlPct = costBasis > 0 ? (pnl / costBasis) * 100 : 0;
        return { ...item, current: livePrice, currentValue, pnl, pnlPct };
      })
  ).filter((item: any) => Number.isFinite(item.currentValue) && item.currentValue >= 0);

  const liveComputedTotalValue = computedPortfolioDetails.reduce((acc: number, curr: any) => acc + curr.currentValue, 0);
  const liveComputedTotalCost = computedPortfolioDetails.reduce((acc: number, curr: any) => acc + curr.qty * curr.avgCost, 0);
  const liveComputedTotalPnL = computedPortfolioDetails.reduce((acc: number, curr: any) => acc + curr.pnl, 0);

  const portfolioSummary = {
    totalCost: liveComputedTotalCost > 0 ? liveComputedTotalCost : finiteNumber(portfolioAnalytics?.total_cost_basis),
    totalValue: liveComputedTotalValue > 0 ? liveComputedTotalValue : finiteNumber(portfolioAnalytics?.total_market_value),
    totalPnL: liveComputedTotalCost > 0 && liveComputedTotalValue > 0
      ? liveComputedTotalPnL
      : finiteNumber(portfolioAnalytics?.unrealized_pnl, liveComputedTotalPnL),
  };
  const hasPortfolioHoldings = computedPortfolioDetails.length > 0;

  const portfolioTotalReturnPct = portfolioSummary.totalCost > 0 
    ? (portfolioSummary.totalPnL / portfolioSummary.totalCost) * 100 
    : 0;

  // Donut chart calculations for sector allocation
  const sectorBreakdownFromBackend = portfolioAnalytics?.sector_breakdown || {};
  const hasBackendSectorBreakdown = Object.keys(sectorBreakdownFromBackend).length > 0;
  const sectorUsesPercent = !hasPortfolioHoldings && hasBackendSectorBreakdown && portfolioSummary.totalValue <= 0;
  const localSectorAllocations = computedPortfolioDetails.reduce((acc: Record<string, number>, curr: any) => {
    const sector = resolvePortfolioSector(curr.symbol, curr.name, curr.sector, curr.assetClass === 'Mutual Fund' ? 'mf' : curr.kind);
    acc[sector] = (acc[sector] || 0) + curr.currentValue;
    return acc;
  }, {} as Record<string, number>);

  const backendSectorAllocations: Record<string, number> = Object.keys(portfolioAnalytics?.sector_breakdown || {}).length > 0
    ? Object.fromEntries(
        Object.entries(sectorBreakdownFromBackend)
          .map(([sec, weight]) => {
            const w = finiteNumber(weight);
            const value = sectorUsesPercent ? w * 100 : w * portfolioSummary.totalValue;
            return [sec, value] as [string, number];
          })
          .filter(([, value]) => value > 0)
      ) as Record<string, number>
    : {};

  const backendSectorsAreGeneric =
    Object.keys(backendSectorAllocations).length > 0 &&
    Object.keys(backendSectorAllocations).every((sector) => isGenericSector(sector));

  const sectorAllocations: Record<string, number> =
    Object.keys(localSectorAllocations).length > 0 || backendSectorsAreGeneric
      ? localSectorAllocations
      : Object.keys(backendSectorAllocations).length > 0
      ? backendSectorAllocations
      : {};

  const sectorEntries = Object.entries(sectorAllocations)
    .map(([label, value]) => [label, finiteNumber(value)] as [string, number])
    .filter(([, value]) => value > 0);

  const sectorChartData = {
    labels: sectorEntries.map(([label]) => label),
    data: sectorEntries.map(([, value]) => value)
  };

  // Donut chart calculations for Asset Allocation (Equity vs MF vs Cash/Bonds)
  const kindBreakdownFromBackend = portfolioAnalytics?.kind_breakdown || {};
  const hasBackendKindBreakdown = Object.keys(kindBreakdownFromBackend).length > 0;
  const assetUsesPercent = !hasPortfolioHoldings && hasBackendKindBreakdown && portfolioSummary.totalValue <= 0;
  const localAssetAllocations = computedPortfolioDetails.reduce((acc: Record<string, number>, curr: any) => {
    const value = curr.currentValue;
    const assetClass = curr.assetClass || 'Equity';
    acc[assetClass] = (acc[assetClass] || 0) + value;
    return acc;
  }, {} as Record<string, number>);
  const backendAssetAllocations: Record<string, number> = hasBackendKindBreakdown
    ? Object.fromEntries(
        Object.entries(kindBreakdownFromBackend)
          .map(([kind, weight]) => {
            const w = finiteNumber(weight);
            const value = assetUsesPercent ? w * 100 : w * portfolioSummary.totalValue;
            return [kind === 'mf' ? 'Mutual Fund' : 'Equity', value] as [string, number];
          })
          .filter(([, value]) => value > 0)
      ) as Record<string, number>
    : {};
  const assetAllocations: Record<string, number> =
    Object.keys(localAssetAllocations).length > 0 ? localAssetAllocations : backendAssetAllocations;

  const assetEntries = Object.entries(assetAllocations)
    .map(([label, value]) => [label, finiteNumber(value)] as [string, number])
    .filter(([, value]) => value > 0);

  const assetChartData = {
    labels: assetEntries.length > 0 ? assetEntries.map(([label]) => label) : ['Equity'],
    data: assetEntries.length > 0 ? assetEntries.map(([, value]) => value) : [1]
  };
  const allocationTotalValue = assetEntries
    .reduce((acc, [, value]) => acc + finiteNumber(value), 0);
  const sectorAllocationTotalValue = sectorEntries
    .reduce((acc, [, value]) => acc + finiteNumber(value), 0);
  const sidebarTotalValue =
    allocationTotalValue > 0
      ? allocationTotalValue
      : sectorAllocationTotalValue > 0
      ? sectorAllocationTotalValue
      : portfolioSummary.totalValue;
  const sidebarTotalPnL =
    hasPortfolioHoldings && liveComputedTotalCost > 0 && allocationTotalValue > 0
      ? allocationTotalValue - liveComputedTotalCost
      : portfolioSummary.totalPnL;
  const sidebarTotalReturnPct =
    liveComputedTotalCost > 0
      ? (sidebarTotalPnL / liveComputedTotalCost) * 100
      : portfolioTotalReturnPct;

  // --- Portfolio vs Benchmark Comparative Data from backend live analytics ---
  const compareChartData = useMemo(() => {
    const portHist = portfolioAnalytics?.history?.portfolio || {};
    const benchHist = portfolioAnalytics?.history?.benchmark || {};
    const portDates: string[] = Array.isArray(portHist.dates) ? portHist.dates : [];
    const benchDates: string[] = Array.isArray(benchHist.dates) ? benchHist.dates : [];

    const portMap = new Map<string, number>(
      portDates
        .map((date, idx) => [date, finiteNumber(portHist.prices?.[idx])] as [string, number])
        .filter(([date, value]) => Boolean(date) && value > 0)
    );
    const benchMap = new Map<string, number>(
      benchDates
        .map((date, idx) => [date, finiteNumber(benchHist.prices?.[idx])] as [string, number])
        .filter(([date, value]) => Boolean(date) && value > 0)
    );

    const normalizeTo100 = (values: number[]) => {
      if (!values.length) return values;
      const base = values.find((value) => value > 0) || values[0];
      if (!base) return values;
      return values.map((value) => (value / base) * 100);
    };

    const buildSeries = (dates: string[], portMapRef: Map<string, number>, benchMapRef: Map<string, number>) => ({
      labels: dates,
      portValues: normalizeTo100(dates.map((date) => portMapRef.get(date) || 0)),
      benchValues: normalizeTo100(dates.map((date) => benchMapRef.get(date) || 0)),
    });

    const commonDates = Array.from(portMap.keys()).filter((date) => benchMap.has(date)).sort();
    const latestCommonDate = commonDates.length > 0 ? new Date(commonDates[commonDates.length - 1]) : null;
    const oneYearCutoff = latestCommonDate && !Number.isNaN(latestCommonDate.getTime())
      ? new Date(latestCommonDate.getFullYear() - 1, latestCommonDate.getMonth(), latestCommonDate.getDate())
      : null;
    const oneYearCommonDates = oneYearCutoff
      ? commonDates.filter((date) => {
          const parsed = new Date(date);
          return !Number.isNaN(parsed.getTime()) && parsed >= oneYearCutoff;
        })
      : commonDates;

    if (oneYearCommonDates.length > 1) {
      return buildSeries(oneYearCommonDates, portMap, benchMap);
    }

    // Fallback: align on union of dates with last-known forward fill
    const unionDates = Array.from(new Set([...portMap.keys(), ...benchMap.keys()])).sort();
    if (unionDates.length > 1) {
      let lastPort = 0;
      let lastBench = 0;
      const alignedDates: string[] = [];
      const alignedPort: number[] = [];
      const alignedBench: number[] = [];
      for (const date of unionDates) {
        const portValue = portMap.get(date);
        const benchValue = benchMap.get(date);
        if (portValue && portValue > 0) lastPort = portValue;
        if (benchValue && benchValue > 0) lastBench = benchValue;
        if (lastPort > 0 && lastBench > 0) {
          alignedDates.push(date);
          alignedPort.push(lastPort);
          alignedBench.push(lastBench);
        }
      }
      if (alignedDates.length > 1) {
        return buildSeries(alignedDates, new Map(alignedDates.map((date, idx) => [date, alignedPort[idx]])), new Map(alignedDates.map((date, idx) => [date, alignedBench[idx]])));
      }
    }

    // Benchmark-only fallback when portfolio history is unavailable (e.g. MF-heavy books)
    if (benchDates.length > 1) {
      const benchOnlyDates = benchDates.slice(-252);
      const benchOnlyValues = (benchHist.prices || []).slice(-252).map((value: any) => finiteNumber(value)).filter((value: number) => value > 0);
      if (benchOnlyValues.length > 1) {
        return {
          labels: benchOnlyDates.slice(-benchOnlyValues.length),
          portValues: [],
          benchValues: normalizeTo100(benchOnlyValues),
        };
      }
    }

    const portPrices = Array.isArray(portHist.prices) ? portHist.prices.map((v: any) => finiteNumber(v)).filter((v: number) => v > 0) : [];
    const benchPrices = Array.isArray(benchHist.prices) ? benchHist.prices.map((v: any) => finiteNumber(v)).filter((v: number) => v > 0) : [];
    const minLen = Math.min(portPrices.length, benchPrices.length);
    if (minLen > 1) {
      const alignedPort = portPrices.slice(portPrices.length - minLen);
      const alignedBench = benchPrices.slice(benchPrices.length - minLen);
      const candidateLabels = (portDates.length >= minLen ? portDates : benchDates).slice(-minLen);
      const labels = candidateLabels.length === minLen
        ? candidateLabels
        : alignedPort.map((_value: number, idx: number) => `T-${minLen - idx - 1}`);
      return {
        labels,
        portValues: alignedPort,
        benchValues: alignedBench,
      };
    }

    return {
      labels: [],
      portValues: [],
      benchValues: [],
    };
  }, [portfolioAnalytics]);

  // Portfolio derived risk metrics from backend live analytics.
  const portfolioStats = (() => {
    if (computedPortfolioDetails.length === 0) return null;
    const sorted = [...computedPortfolioDetails].sort((a, b) => b.pnlPct - a.pnlPct);
    const best = sorted[0];
    const worst = sorted[sorted.length - 1];
    const winners = computedPortfolioDetails.filter(p => p.pnl > 0).length;
    const losers = computedPortfolioDetails.filter(p => p.pnl < 0).length;
    
    // Top sector
    const totalVal = computedPortfolioDetails.reduce((s, p) => s + p.currentValue, 0);
    const sectors = Object.entries(sectorAllocations).sort((a, b) => b[1] - a[1]);
    const topSector = sectors[0];
    const topSectorPct = topSector && totalVal > 0 ? (topSector[1] / totalVal) * 100 : 0;
    
    // Herfindahl-Hirschman Index (HHI) for concentration risk
    const backendHhi = finiteNumber(portfolioAnalytics?.risk?.hhi);
    const hhi = backendHhi > 0
      ? backendHhi * 10000
      : computedPortfolioDetails.reduce((sum: number, p: any) => {
          const weight = totalVal > 0 ? (p.currentValue / totalVal) * 100 : 0;
          return sum + (weight * weight);
        }, 0);
    const beta = finiteNumber(portfolioAnalytics?.risk?.beta_vs_nifty, 0);
    const annualVolPct = finiteNumber(portfolioAnalytics?.risk?.annualized_volatility_pct, 0);
    // Prefer the backend's 1-day historical VaR (same number the Risk tab shows);
    // fall back to a parametric estimate only when history isn't available yet.
    const histVarPct = finiteNumber(portfolioAnalytics?.risk?.historical_var_pct, 0);
    const oneDayVol = annualVolPct > 0 ? annualVolPct / 100 / Math.sqrt(252) : 0.0165;
    const var95 = histVarPct > 0
      ? totalVal * histVarPct / 100
      : totalVal * oneDayVol * 1.65 * (beta > 0 ? beta : 1);

    return { best, worst, winners, losers, topSector, topSectorPct, beta, hhi, var95 };
  })();

  // Tracked universe movers — resolve live change_pct by normalizing symbol format
  // quotesData may be keyed as "RELIANCE.NS" but portfolio symbols may be "RELIANCE"
  const lookupQuote = (sym: string) => {
    return lookupLiveQuote(sym);
  };

  // Movers are scoped strictly to portfolio holdings. Watchlist names belong to
  // the Watchlist tab only and must not appear inside the Portfolio view.
  const allTrackedStocks = [...computedPortfolioDetails];

  const stocksWithChange = allTrackedStocks.map(s => {
    const q = lookupQuote(s.symbol);
    const changePct = q && Number.isFinite(Number(q.change_pct)) ? Number(q.change_pct) : null;
    const livePrice = q?.price;
    const displayPrice = livePrice != null
      ? livePrice.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : s.current > 0 ? s.current.toFixed(2) : '—';
    const baseSymbol = normalizeMarketSymbol(s.symbol);
    return {
      symbol: baseSymbol,
      name: q?.company_name || s.name,
      price: displayPrice,
      changePct,
      hasLiveQuote: q != null && changePct != null,
      isOwned: computedPortfolioDetails.some(
        p => normalizeMarketSymbol(p.symbol) === baseSymbol
      ),
    };
  }).filter(s => s.hasLiveQuote && s.changePct !== null);

  const gainers = [...stocksWithChange]
    .filter(s => (s.changePct ?? 0) > 0)
    .sort((a, b) => (b.changePct ?? 0) - (a.changePct ?? 0))
    .slice(0, 4);
  const losersList = [...stocksWithChange]
    .filter(s => (s.changePct ?? 0) < 0)
    .sort((a, b) => (a.changePct ?? 0) - (b.changePct ?? 0))
    .slice(0, 4);
  const mostActive = [...stocksWithChange]
    .filter(s => Math.abs(s.changePct ?? 0) > 0.005)
    .sort((a, b) => Math.abs(b.changePct ?? 0) - Math.abs(a.changePct ?? 0))
    .slice(0, 4);

  // News feed is now fetched dynamically from the API and stored in state

  const sentimentColor = (s: string) =>
    s === 'bullish' ? 'var(--profit)' : s === 'bearish' ? 'var(--loss)' : 'var(--text-secondary)';
  const sentimentLabel = (s: string) =>
    s === 'bullish' ? 'BULLISH' : s === 'bearish' ? 'BEARISH' : 'NEUTRAL';

  // --- Portfolio Query Enrichment (Portfolio-Aware Chat) ---
  const detectPortfolioScope = (query: string): 'portfolio_scope' | 'specific_holding' | 'general' => {
    const qLower = query.toLowerCase();
    const scopeKeywords = [
      'my portfolio', 'my holdings', 'my equities', 'my stocks', 'my investments', 
      'my book', 'my positions', 'pros cons of my', 'audit my', 'risk in my', 'analyse my'
    ];
    
    if (scopeKeywords.some(keyword => qLower.includes(keyword))) {
      return 'portfolio_scope';
    }

    // Check if user specifically mentions a ticker they own
    const ownedMatches = portfolio.some(p => 
      qLower.includes(p.symbol.toLowerCase()) || 
      qLower.includes(p.name.toLowerCase())
    );

    if (ownedMatches) {
      return 'specific_holding';
    }

    return 'general';
  };

  const buildMirrorBackfillPayload = (items: PortfolioItem[]) => {
    const nowIso = new Date().toISOString();
    return items
      .filter((p) => Number(p.qty) > 0 && (p.symbol || '').trim().length > 0)
      .map((p) => {
        const symbol = String(p.symbol || '').split('.')[0].toUpperCase().trim();
        const quantity = Number(p.qty) || 0;
        const lastPrice = Number(p.current) || 0;
        const avgCost = Number(p.avgCost) || 0;
        return {
          symbol,
          exchange: 'NSE',
          quantity,
          market_value: quantity * lastPrice,
          cost_basis: quantity * avgCost,
          name: p.name || symbol,
          kind: 'equity',
          sector: p.sector || 'General',
          avg_cost: avgCost,
          last_price: lastPrice,
          as_of: nowIso,
          active: true,
        };
      });
  };

  const enrichQueryWithPortfolio = (query: string): string => {
    if (enrichedPortfolio.length === 0) return '';

    const scope = detectPortfolioScope(query);
    if (scope === 'portfolio_scope') {
      const breakdownSectors = Object.entries(sectorAllocations)
        .map(([sec, val]) => {
          const pct = portfolioSummary.totalValue > 0 ? ((finiteNumber(val) / portfolioSummary.totalValue) * 100).toFixed(0) : '0';
          return `${sec} ${pct}%`;
        })
        .join(', ');
      
      const holdingsStr = enrichedPortfolio
        .map(p => `${p.name} (${p.symbol}, ${p.qty} shares @ ₹${p.avgCost} cost, current ₹${p.current}, sector: ${p.sector})`)
        .join('; ');

      return `[USER PORTFOLIO SUMMARY: ${enrichedPortfolio.length} holdings worth ₹${portfolioSummary.totalValue.toLocaleString('en-IN')}, total P&L: ₹${portfolioSummary.totalPnL.toLocaleString('en-IN')} (${portfolioTotalReturnPct.toFixed(1)}%). Top sectors: ${breakdownSectors}. Holdings: ${holdingsStr}]`;
    }

    if (scope === 'specific_holding') {
      const matched = enrichedPortfolio.filter(p => {
        const qLower = query.toLowerCase();
        return qLower.includes(p.symbol.toLowerCase()) || qLower.includes(p.name.toLowerCase());
      });
      if (matched.length > 0) {
        const holdingsStr = matched
          .map(p => {
            const costBasis = p.qty * p.avgCost;
            const pnl = p.qty * p.current - costBasis;
            const pnlPct = costBasis > 0 ? (pnl / costBasis) * 100 : 0;
            return `${p.name} (${p.symbol}) - ${p.qty} shares @ ₹${p.avgCost} avg cost, current ₹${p.current}, unrealized P&L ₹${pnl.toLocaleString('en-IN')} (${pnlPct.toFixed(1)}%), representing ${((p.qty * p.current / portfolioSummary.totalValue) * 100).toFixed(1)}% of total portfolio, sector: ${p.sector}`;
          })
          .join('; ');

        return `[USER HOLDS SPECIFIC POSITIONS: ${holdingsStr}]`;
      }
    }

    // Default general query - inject light summary context anyway
    return `[USER PORTFOLIO VALUE: ₹${portfolioSummary.totalValue.toLocaleString('en-IN')} across ${enrichedPortfolio.length} positions]`;
  };

  const buildPortfolioFallbackAnswer = (_query: string, reason?: string) => {
    if (computedPortfolioDetails.length === 0) {
      return [
        'I could not find synchronized portfolio holdings for this account yet.',
        '',
        'For SEBI-safe analysis, upload or sync your holdings first. I will then respond as an objective risk-audit tool and will avoid buy, sell, hold, target-price, or suitability recommendations.',
      ].join('\n');
    }

    const totalValue = portfolioSummary.totalValue || computedPortfolioDetails.reduce((sum, item) => sum + item.currentValue, 0);
    const formatMoney = (value: number) => `Rs. ${Math.round(value || 0).toLocaleString('en-IN')}`;
    const topHoldings = [...computedPortfolioDetails]
      .sort((a, b) => b.currentValue - a.currentValue)
      .slice(0, 5)
      .map((item) => {
        const weight = totalValue > 0 ? (item.currentValue / totalValue) * 100 : 0;
        return `${item.symbol}: ${weight.toFixed(1)}% (${item.sector || 'General'})`;
      })
      .join(', ');
    const sectorRows = Object.entries(sectorAllocations)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
      .map(([sector, value]) => {
        const weight = totalValue > 0 ? (finiteNumber(value) / totalValue) * 100 : 0;
        return `${sector}: ${weight.toFixed(1)}%`;
      })
      .join(', ');
    const betaText = portfolioStats ? portfolioStats.beta.toFixed(2) : 'N/A';
    const hhiText = portfolioStats ? portfolioStats.hhi.toFixed(0) : 'N/A';
    const varText = portfolioStats ? formatMoney(portfolioStats.var95) : 'N/A';
    const topSectorText = portfolioStats?.topSector
      ? `${portfolioStats.topSector[0]} at ${portfolioStats.topSectorPct.toFixed(1)}%`
      : sectorRows || 'not available';

    return [
      reason ? `Live research did not finish cleanly (${reason}), so I completed this with the synchronized portfolio analytics already available in your dashboard.` : 'Here is the objective portfolio-risk audit from your synchronized dashboard analytics.',
      '',
      '**Compliance note:** This is not investment advice, not a buy/sell/hold call, and not a target-price view. It is a risk and exposure audit based on your uploaded holdings and live/available market data.',
      '',
      `**Main hidden-risk area:** concentration risk. Your largest sector exposure is ${topSectorText}. If that sector faces a drawdown or earnings disappointment, the portfolio can move more than the headline index suggests.`,
      '',
      `**Position concentration:** ${topHoldings || 'not available'}. Check whether any single holding or closely related group is carrying more risk than you intended.`,
      '',
      `**Risk snapshot:** portfolio value ${formatMoney(totalValue)}, beta vs Nifty ${betaText}, concentration score ${hhiText}, estimated one-day 95% VaR ${varText}. These are model outputs, not guarantees.`,
      '',
      `**What to review next:** compare sector weights with your intended benchmark, check if top holdings share the same macro drivers, and verify whether recent price moves came from earnings, corporate announcements, leverage, or broad index moves.`,
    ].join('\n');
  };

  // --- Real API Chat Integration ---
  const handleSendMessage = async (message: string, depth: 'standard' | 'deep' = 'standard') => {
    if (!message.trim() || isThinking || isReadOnly) return;
    const conversationId = activeConversationId || createConversationDraft(conversations);

    // 1. Append User Bubble
    const userMsg: Message = { sender: 'user', text: message, depth };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    localStorage.setItem(getMessageStorageKey(conversationId), JSON.stringify(updatedMessages));

    // Update conversation title if needed
    const activeConv = conversations.find(c => c.id === conversationId);
    if (activeConv && (activeConv.title === 'Equity Analysis Session' || activeConv.title.startsWith('Analyze ') || activeConv.title.startsWith('Portfolio '))) {
      const cleanTitle = message.length > 28 ? message.substring(0, 28) + '...' : message;
      const updatedConvs = conversations.map(c => c.id === conversationId ? { ...c, title: cleanTitle } : c);
      setConversations(updatedConvs);
      localStorage.setItem(conversationsStorageKey, JSON.stringify(updatedConvs));
    }

    // 2. Start Thinking & SSE Stream
    setIsThinking(true);
    setThinkingEvents([{
      seq: 0,
      type: 'phase',
      timestamp: new Date().toISOString(),
      payload: { phase: 'queued', note: 'Preparing the live research run' },
    }]);

    const enrichedObjective = enrichQueryWithPortfolio(message);
    const startMs = performance.now();
    const portfolioScope = detectPortfolioScope(message);

    try {
      if (portfolioScope !== 'general' && enrichedPortfolio.length > 0) {
        try {
          const payload = buildMirrorBackfillPayload(enrichedPortfolio);
          if (payload.length > 0) {
            await replacePortfolioMirror(payload);
          }
        } catch (syncErr) {
          console.warn('Portfolio mirror preflight sync failed', syncErr);
        }
      }

      // API call to start background job
      const startRes = await startResearch(message, depth, enrichedObjective);
      const backendSessionId = startRes.session_id;
      let streamedMemoText = '';
      let runCompleted = false;
      const completeWithResponse = (aiResponse: Message) => {
        if (runCompleted) return;
        runCompleted = true;
        setMessages((prev) => {
          const next = [...prev, aiResponse];
          try {
            localStorage.setItem(getMessageStorageKey(conversationId), JSON.stringify(next));
          } catch (storageErr) {
            console.warn('[DASHBOARD] localStorage persist failed', storageErr);
          }
          return next;
        });
        setIsThinking(false);
        setThinkingEvents([]);
      };
      const completeWithPortfolioFallback = async (reason: string) => {
        if (runCompleted) return;
        if (abortStreamRef.current) {
          abortStreamRef.current();
          abortStreamRef.current = null;
        }
        let fallbackText = buildPortfolioFallbackAnswer(message, reason);
        try {
          const brief = await getPortfolioBrief();
          if (brief?.brief) {
            fallbackText = `${fallbackText}\n\n**Backend portfolio brief:** ${brief.brief}`;
          }
        } catch (briefErr) {
          console.warn('Portfolio brief fallback failed', briefErr);
        }
        completeWithResponse({
          sender: 'ai',
          text: fallbackText,
          depth,
          elapsedMs: Math.round(performance.now() - startMs),
        });
      };
      if (backendSessionId && backendSessionId !== activeConv?.backendSessionId) {
        const updatedConvs = conversations.map(c =>
          c.id === conversationId ? { ...c, backendSessionId } : c
        );
        setConversations(updatedConvs);
        localStorage.setItem(conversationsStorageKey, JSON.stringify(updatedConvs));
      }

      // Subscribe to SSE updates
      const unsubscribe = streamSession(
        backendSessionId,
        (event) => {
          if (event.type === 'memo_token' && typeof event.payload?.chunk === 'string') {
            streamedMemoText += event.payload.chunk;
          }
          // Push event to thinking stack
          setThinkingEvents((prev) => [...prev, event]);
        },
        async (parsedEvent: any) => {
          if (runCompleted) return;
          // Finished research Turn
          const elapsed = Math.round(performance.now() - startMs);

          // Get full synthesized result
          let aiResponse: Message;
          try {
            const finalResult = await getSessionResult(backendSessionId);
            console.log('[DASHBOARD] getSessionResult success:', finalResult);
            const richPayload =
              finalResult.final?.rich ||
              parsedEvent?.rich ||
              null;
            const memoText =
              finalResult.memo ||
              finalResult.final?.memo ||
              finalResult.final?.memo_preview ||
              richPayload?.markdown_body ||
              finalResult.memo_event?.preview ||
              streamedMemoText.trim() ||
              parsedEvent?.memo ||
              parsedEvent?.memo_preview ||
              parsedEvent?.preview ||
              'Analysis complete.';
            const usefulMemo = memoText.trim().length > 40 && memoText.trim() !== 'Analysis complete.';
            if (!usefulMemo && portfolioScope !== 'general' && enrichedPortfolio.length > 0) {
              await completeWithPortfolioFallback('empty final answer');
              return;
            }
            aiResponse = {
              sender: 'ai',
              text: memoText,
              richData: richPayload,
              depth: depth,
              elapsedMs: elapsed,
              sessionId: backendSessionId,
              wantsDocument: depth === 'deep' && queryWantsDocument(message),
            };
          } catch (resErr) {
            console.error('[DASHBOARD] Failed to retrieve final memo details', resErr);
            // Fallback: try to show preview from the event data if available
            const fallbackRich = parsedEvent?.rich || null;
            const fallbackText =
              parsedEvent?.memo ||
              parsedEvent?.memo_preview ||
              parsedEvent?.preview ||
              fallbackRich?.markdown_body ||
              streamedMemoText.trim() ||
              'Analysis complete.';
            aiResponse = {
              sender: 'ai',
              text: fallbackText,
              richData: fallbackRich,
              depth: depth,
              elapsedMs: elapsed,
              sessionId: backendSessionId,
              wantsDocument: depth === 'deep' && queryWantsDocument(message),
            };
            // Also show a toast so the user knows something went wrong
            showToast('Failed to load full answer. Showing cached preview.', 'error');
          }

          completeWithResponse(aiResponse);
        },
        (error) => {
          if (runCompleted) return;
          const errMsg = error.message || 'Stream processing failed.';
          showToast(errMsg, 'error');
          if (portfolioScope !== 'general' && enrichedPortfolio.length > 0) {
            void completeWithPortfolioFallback(errMsg);
            return;
          }
          const errResponse: Message = {
            sender: 'ai',
            text: `**Research failed**: ${errMsg}\n\nPlease try again. If this keeps happening, switch to Standard mode or retry with a shorter query.`,
          };
          completeWithResponse(errResponse);
        }
      );

      abortStreamRef.current = unsubscribe;
    } catch (err: any) {
      setIsThinking(false);
      setThinkingEvents([]);
      const errMsg = err.message || 'Failed to connect to Quant engine.';
      showToast(errMsg, 'error');
      const conflictStatus = err?.detail?.status || err?.detail?.code || err?.detail?.error_code;
      if (
        err?.message?.includes('409') ||
        conflictStatus === 'MIRROR_REQUIRED' ||
        conflictStatus === 'INGESTION_IN_PROGRESS' ||
        conflictStatus === 'INGESTION_REQUIRED'
      ) {
        let fallbackText = buildPortfolioFallbackAnswer(message, conflictStatus || errMsg);
        try {
          const brief = await getPortfolioBrief();
          if (brief?.brief) {
            fallbackText = `${fallbackText}\n\n**Backend portfolio brief:** ${brief.brief}`;
          }
        } catch (briefErr) {
          console.warn('Portfolio brief fallback failed', briefErr);
        }
        const fallbackResponse: Message = {
          sender: 'ai',
          text: fallbackText,
          depth,
          elapsedMs: Math.round(performance.now() - startMs),
        };
        setMessages((prev) => {
          const next = [...prev, fallbackResponse];
          try {
            localStorage.setItem(getMessageStorageKey(conversationId), JSON.stringify(next));
          } catch (storageErr) {
            console.warn('[DASHBOARD] localStorage persist failed', storageErr);
          }
          return next;
        });
        return;
      }
      
      if (err.detail?.code === 'WEEKLY_TOKEN_LIMIT_EXCEEDED' || err.detail?.code === 'DEEP_PREMIUM_REQUIRED') {
        const limitResponse: Message = {
          sender: 'ai',
          text: err.detail?.code === 'DEEP_PREMIUM_REQUIRED' ? 'Deep Mode Limit Reached' : 'Weekly Token Limit Exceeded',
          tokenLimitDetail: err.detail
        };
        setMessages((prev) => {
          const next = [...prev, limitResponse];
          try {
            localStorage.setItem(getMessageStorageKey(conversationId), JSON.stringify(next));
          } catch (e) { /* ignore storage errors */ }
          return next;
        });
      } else {
        if (portfolioScope !== 'general' && enrichedPortfolio.length > 0) {
          let fallbackText = buildPortfolioFallbackAnswer(message, errMsg);
          try {
            const brief = await getPortfolioBrief();
            if (brief?.brief) {
              fallbackText = `${fallbackText}\n\n**Backend portfolio brief:** ${brief.brief}`;
            }
          } catch (briefErr) {
            console.warn('Portfolio brief fallback failed', briefErr);
          }
          const fallbackResponse: Message = {
            sender: 'ai',
            text: fallbackText,
            depth,
            elapsedMs: Math.round(performance.now() - startMs),
          };
          setMessages((prev) => {
            const next = [...prev, fallbackResponse];
            try {
              localStorage.setItem(getMessageStorageKey(conversationId), JSON.stringify(next));
            } catch (storageErr) {
              console.warn('[DASHBOARD] localStorage persist failed', storageErr);
            }
            return next;
          });
          return;
        }
        const errResponse: Message = {
          sender: 'ai',
          text: `**Connection Error**: ${errMsg}`
        };
        setMessages((prev) => [...prev, errResponse]);
        try {
          const merged = [...updatedMessages, errResponse];
          localStorage.setItem(getMessageStorageKey(conversationId), JSON.stringify(merged));
        } catch (e) { /* ignore storage errors */ }
      }
    }
  };

  const handleStopGeneration = async () => {
    if (abortStreamRef.current) {
      abortStreamRef.current();
      abortStreamRef.current = null;
    }

    const activeConv = conversations.find(c => c.id === activeConversationId);
    
    if (activeConv?.backendSessionId) {
      try {
        await stopSession(activeConv.backendSessionId);
      } catch (e) {
        // Already terminated on server
      }
    }

    setIsThinking(false);
    setThinkingEvents([]);

    const stopMsg: Message = { sender: 'ai', text: '_Analysis stopped by user._' };
    setMessages(prev => {
      const updated = [...prev, stopMsg];
      localStorage.setItem(getMessageStorageKey(activeConversationId), JSON.stringify(updated));
      return updated;
    });
  };

  const handleSelectConversation = (id: string) => {
    if (isThinking) return;
    setActiveConversationId(id);
    const savedMessagesRaw = readStoredMessages(id);
    if (savedMessagesRaw) {
      try {
        setMessages(JSON.parse(savedMessagesRaw));
      } catch (e) {
        bootstrapWelcomeMessage(id);
      }
    } else {
      bootstrapWelcomeMessage(id);
    }
  };

  const handleNewConversation = () => {
    if (isThinking) {
      if (abortStreamRef.current) {
        abortStreamRef.current();
        abortStreamRef.current = null;
      }
      const activeConv = conversations.find((c) => c.id === activeConversationId);
      if (activeConv?.backendSessionId) {
        void stopSession(activeConv.backendSessionId).catch(() => {});
      }
      setIsThinking(false);
      setThinkingEvents([]);
    }
    createConversationDraft(conversations);
  };

  const handleDeleteConversation = (id: string) => {
    if (conversations.length <= 1) return;
    if (isThinking && activeConversationId === id) return;
    const updated = conversations.filter(c => c.id !== id);
    setConversations(updated);
    if (updated.length > 0) {
      localStorage.setItem(conversationsStorageKey, JSON.stringify(updated));
    } else {
      localStorage.removeItem(conversationsStorageKey);
    }
    localStorage.removeItem(getMessageStorageKey(id));

    if (activeConversationId === id) {
      if (updated.length > 0) {
        handleSelectConversation(updated[0].id);
      } else {
        setActiveConversationId('');
        setMessages([]);
      }
    }
  };

  const handleClearHistory = () => {
    if (isThinking) return;
    conversations.forEach(c => {
      localStorage.removeItem(getMessageStorageKey(c.id));
    });
    
    const newId = createConversationId();
    const newConv = { id: newId, title: 'Equity Analysis Session', date: 'Today' };
    setConversations([newConv]);
    localStorage.setItem(conversationsStorageKey, JSON.stringify([newConv]));
    
    setActiveConversationId(newId);
    bootstrapWelcomeMessage(newId);
  };

  const handleConfirmOverrideWithLocalHoldings = async () => {
    if (isApplyingManualOverride) return;
    setIsApplyingManualOverride(true);
    try {
      const synced = await syncLocalPortfolio({ force: true });
      if (synced) {
        setManualOverridePrompt(null);
        setPortfolioSyncNonce((value) => value + 1);
        showToast('Saved holdings replaced with your current local holdings.', 'success');
      } else {
        showToast('Could not replace saved holdings. Please try again.', 'error');
      }
    } finally {
      setIsApplyingManualOverride(false);
    }
  };

  const handleKeepSavedHoldings = () => {
    clearLocalPortfolio();
    setManualOverridePrompt(null);
    setPortfolioSyncNonce((value) => value + 1);
    showToast('Kept your saved holdings. Local manual draft was discarded.', 'info');
  };

  /** Pre-fills the chat input with a query (shows query for user review instead of auto-executing) */
  const handleSuggestQuery = (query: string, depth: 'standard' | 'deep' = 'standard') => {
    if (isReadOnly) {
      navigate('/login?redirect=/dashboard/portfolio');
      return;
    }
    // Auto-open chat if it's hidden
    if (isChatHidden) {
      setIsChatHidden(false);
      const w = 380;
      setChatWidth(w);
      localStorage.setItem('prospektlab_chat_width', w.toString());
    }
    // Set pending query — ChatInput will pick this up and auto-populate
    setPendingChatQuery({ id: `draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, text: query, depth });
    // Pulse the chat rail border
    setIsChatHighlighted(true);
    setTimeout(() => setIsChatHighlighted(false), 1600);
    // Scroll chat body to bottom so user sees the populated input
    setTimeout(() => {
      if (chatContainerRef.current) {
        chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
      }
    }, 120);
  };

  const openAssetHistory = (symbol: string, name?: string, assetType?: string) => {
    setAssetHistoryTarget({ symbol, name, assetType });
  };

  const handleSelectStock = (symbol: string, item?: { name?: string; assetClass?: string }) => {
    openAssetHistory(symbol, item?.name, item?.assetClass || 'equity');
  };

  const handleAnalyzeStock = (symbol: string) => {
    handleSuggestQuery(`Analyse ${symbol} and check its core ratios.`, 'standard');
  };

  const handleAddStock = (symbol: string) => {
    const normalized = normalizeMarketSymbol(symbol);
    if (!normalized || watchlist.includes(normalized)) return;
    const updated = [...watchlist, normalized];
    setWatchlist(updated);
    localStorage.setItem(watchlistStorageKey, JSON.stringify(updated));
  };

  const handleRemoveStock = (symbol: string) => {
    const normalized = normalizeMarketSymbol(symbol);
    const updated = watchlist.filter(s => normalizeMarketSymbol(s) !== normalized);
    setWatchlist(updated);
    localStorage.setItem(watchlistStorageKey, JSON.stringify(updated));
  };

  // showToast is now provided by AuthContext — visible toast notifications
  const retryIndices = async () => {
    setIndicesLoading(true);
    setIndicesError(null);
    try {
      const data = await getMarketIndices();
      if (data) {
        setLiveIndexData(data);
      }
    } catch (e: any) {
      console.error('Failed to fetch market indices', e);
      setIndicesError(e.message || 'Failed to load market indices');
    } finally {
      setIndicesLoading(false);
    }
  };

  const retryNews = async () => {
    setNewsLoading(true);
    setNewsError(null);
    try {
      const hasHoldings = portfolioSymbols.length > 0;
      const [marketData, portfolioData] = await Promise.allSettled([
        getMarketNews('India market'),
        getPortfolioNews(8),
      ]);
      const portfolioItems = portfolioData.status === 'fulfilled'
        ? mapTapeNewsItems(portfolioData.value?.items || [], 'retry-p')
        : [];
      const marketItems = marketData.status === 'fulfilled'
        ? mapTapeNewsItems(marketData.value, 'retry-m')
        : [];
      // With holdings: keep only holding-relevant items. Without: general market.
      const source = hasHoldings
        ? [...portfolioItems, ...marketItems.filter((i: any) => i.holdingRelevant)]
        : marketItems;
      const mapped = source
        .filter((item, idx, arr) => idx === arr.findIndex((candidate) => candidate.headline === item.headline))
        .slice(0, 10);
      if (mapped.length > 0) {
        setNewsFeed(mapped);
        localStorage.setItem(TAPE_NEWS_CACHE_KEY, JSON.stringify(mapped));
      } else {
        setNewsFeed([]);
        localStorage.removeItem(TAPE_NEWS_CACHE_KEY);
      }
    } catch (e: any) {
      console.error('Failed to fetch market news', e);
      setNewsError(e.message || 'Failed to load market news');
    } finally {
      setNewsLoading(false);
    }
  };

  useEffect(() => {
    if (!user?.name) return;
    const cleanUserName = user.name.trim();
    if (!cleanUserName) return;
    setPortfolioOnboardName((prev) => prev || cleanUserName);
  }, [user?.name]);

  const persistPortfolioOnboardName = () => {
    if (typeof window === 'undefined') return;
    const cleanName = portfolioOnboardName.trim();
    if (!cleanName) {
      localStorage.removeItem('prospektlab_username');
      return;
    }
    localStorage.setItem('prospektlab_username', cleanName);
  };

  const canStartPortfolioSetup = portfolioOnboardName.trim().length > 0;

  const handlePortfolioManualSetup = () => {
    persistPortfolioOnboardName();
    navigate('/onboarding/manual');
  };

  const handlePortfolioUploadSetup = () => {
    persistPortfolioOnboardName();
    navigate('/onboarding/upload');
  };

  const hasEngaged = messages.some((msg, index) => msg.sender === 'user' || index > 0);

  /* ─────────────────────────────────────────────
     ARTHIK PERSONALIZED GREETING
  ───────────────────────────────────────────── */
  const getArthikGreeting = (): string => {
    const hour = new Date().getHours();
    const name = (user?.name || localStorage.getItem('prospektlab_username') || 'there').split(/\s+/)[0];
    const portfolioSize = portfolio.length;
    const marketOpen = hour >= 9 && hour < 16;
    const isWeekend = [0, 6].includes(new Date().getDay());

    const timeOfDay =
      hour < 5 ? 'night' :
      hour < 12 ? 'morning' :
      hour < 17 ? 'afternoon' :
      hour < 21 ? 'evening' : 'night';

    const greetings: string[] = [];

    if (timeOfDay === 'night') {
      greetings.push(
        `Still up, ${name}? Markets are closed, but the best moves are planned in silence. What's on your mind?`,
        `Late night research session, ${name}? I like that. What are you digging into?`,
        `The markets sleep, but the sharp money never does. What's keeping you up, ${name}?`
      );
    } else if (timeOfDay === 'morning') {
      if (marketOpen && !isWeekend) {
        greetings.push(
          `Markets are live, ${name}. Nifty opened a few minutes ago. What's the first thing you want to check?`,
          `Good morning, ${name}. The opening bell just rang. Want a quick scan of your watchlist?`,
          `Morning, ${name}. Fresh tape, fresh numbers. What should we look at first?`
        );
      } else {
        greetings.push(
          `Good morning, ${name}. Markets are closed today, but there's always something to read. What's on your mind?`,
          `Morning, ${name}. No market action today, but we can still prep for tomorrow. What are you thinking about?`,
          `Hey ${name}. Quiet morning with no market noise — perfect time to dig deep into something. What do you want to explore?`
        );
      }
    } else if (timeOfDay === 'afternoon') {
      if (marketOpen && !isWeekend) {
        greetings.push(
          `Afternoon, ${name}. Mid-session often reveals the real trend. What do you want to analyze?`,
          `Hey ${name}. The market's been running for a few hours now. Want to check how your positions are holding up?`,
          `Good afternoon, ${name}. Want me to run a quick risk check on your book while the tape is active?`
        );
      } else {
        greetings.push(
          `Afternoon, ${name}. No live tape right now, but we can still build conviction. What are you researching?`,
          `Hey ${name}. Quiet afternoon — perfect for deep research. What company do you want to understand better?`
        );
      }
    } else { // evening
      if (marketOpen && !isWeekend) {
        greetings.push(
          `Evening, ${name}. Markets are closing soon. Want a summary of what moved today?`,
          `Hey ${name}. The closing bell is coming up. Should we review how your positions performed today?`,
          `Good evening, ${name}. Last hour of trading — want me to flag anything unusual in your watchlist?`
        );
      } else {
        greetings.push(
          `Evening, ${name}. Markets are closed. Want me to run a DCF on something you've been watching?`,
          `Hey ${name}. The market's done for the day. Perfect time to research without the noise. What do you want to explore?`,
          `Good evening, ${name}. Want me to audit a stock you've been thinking about buying?`
        );
      }
    }

    // Portfolio-aware additions
    if (portfolioSize > 0) {
      greetings.push(
        `Hey ${name}. You've got ${portfolioSize} positions in your book. Want me to check what's changed since yesterday?`,
        `Hi ${name}. Your portfolio has ${portfolioSize} holdings. Should I run a quick risk scan?`,
        `Welcome back, ${name}. I see ${portfolioSize} positions in your portfolio. Anything specific you want me to dig into?`
      );
    } else {
      greetings.push(
        `Hey ${name}. Your portfolio is empty right now — want me to help you build a watchlist?`,
        `Hi ${name}. No holdings synced yet. Want me to find a few solid names to start tracking?`,
        `Welcome, ${name}. Let's start building your research dashboard. What sector interests you?`
      );
    }

    // Pick one based on a rotating hash of the current hour
    const index = (hour + new Date().getDate()) % greetings.length;
    return greetings[index];
  };

  const arthikGreeting = getArthikGreeting();

  const activeIndices = useMemo(() =>
    [...liveIndexData.india].sort((a, b) => b.changePct - a.changePct),
    [liveIndexData.india]
  );

  const marketSummary = useMemo(() => {
    if (activeIndices.length === 0) {
      return { headline: 'Loading market data...', body: 'Fetching latest index data from NSE and BSE.', sourcesCount: 0 };
    }
    const gainers = activeIndices.filter((i: any) => i.changePct > 0);
    const losers = activeIndices.filter((i: any) => i.changePct < 0);
    const best = activeIndices[0];
    const worst = activeIndices[activeIndices.length - 1];
    const gainerParts = gainers.length > 0
      ? `${gainers.length} ind${gainers.length === 1 ? 'ex' : 'ices'} in the green led by ${best?.symbol || ''}`
      : 'All indices trading lower';
    const loserParts = losers.length > 0
      ? `while ${losers.length} declin${losers.length === 1 ? 'es' : 'e'}${worst?.symbol ? ' led by ' + worst.symbol : ''}`
      : '';
    return {
      headline: `${gainerParts}${loserParts ? ' ' + loserParts : ''}`,
      body: `Markets ${gainers.length > losers.length ? 'continue to show strength' : 'are under pressure'} with the ${best?.symbol || 'NIFTY'} ${(best?.changePct || 0) >= 0 ? 'up' : 'down'} ${Math.abs(best?.changePct || 0).toFixed(1)}%. Sector rotation and global cues remain key drivers today.`,
      sourcesCount: activeIndices.length,
    };
  }, [activeIndices]);

  const suggestions = portfolio.length > 0
    ? [
        `What is the pros and cons of my equities?`,
        `Why is ${portfolio[0]?.symbol || 'my top holding'} moving against me?`,
        `Where's the hidden risk in my portfolio?`,
      ]
    : [
        `What's moving the Nifty right now?`,
        `Is this a dip or a trap?`,
        `Give me the bull case on Tata Motors.`,
      ];

  return (
    <AppShell
      title="Portfolio"
      portfolioSummary={undefined}
      conversations={conversations}
      onDeleteConversation={handleDeleteConversation}
      onClearHistory={handleClearHistory}
      onNewConversation={handleNewConversation}
      onSelectConversation={handleSelectConversation}
      activeConversationId={activeConversationId}
      tokenUsage={tokenUsage}
    >
      {manualOverridePrompt && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 1200,
            background: 'rgba(2, 6, 23, 0.7)',
            backdropFilter: 'blur(5px)',
            WebkitBackdropFilter: 'blur(5px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
        >
          <div
            style={{
              width: 'min(560px, 100%)',
              borderRadius: '16px',
              border: '1px solid rgba(56, 189, 248, 0.22)',
              background: 'rgba(15, 23, 42, 0.98)',
              boxShadow: '0 20px 70px rgba(0, 0, 0, 0.5)',
              padding: '22px 22px 18px',
              display: 'flex',
              flexDirection: 'column',
              gap: '10px',
            }}
          >
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)' }}>
              Override previous saved holdings?
            </div>
            <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
              We found <strong>{manualOverridePrompt.localCount}</strong> local holdings from your current manual session,
              and <strong> {manualOverridePrompt.savedCount}</strong> holdings already saved in your account.
              Do you want to replace your saved holdings with the current local holdings?
            </div>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
              <button
                type="button"
                onClick={handleKeepSavedHoldings}
                disabled={isApplyingManualOverride}
                style={{
                  borderRadius: 10,
                  padding: '10px 16px',
                  border: '1px solid rgba(148, 163, 184, 0.22)',
                  background: 'rgba(15, 23, 42, 0.5)',
                  color: 'var(--text-secondary)',
                  fontSize: 13,
                  fontWeight: 600,
                }}
              >
                No, keep saved
              </button>
              <button
                type="button"
                onClick={handleConfirmOverrideWithLocalHoldings}
                disabled={isApplyingManualOverride}
                style={{
                  borderRadius: 10,
                  padding: '10px 16px',
                  border: '1px solid rgba(56, 189, 248, 0.3)',
                  background: 'linear-gradient(135deg, rgba(56, 189, 248, 0.24), rgba(14, 116, 144, 0.28))',
                  color: 'var(--text-primary)',
                  fontSize: 13,
                  fontWeight: 700,
                }}
              >
                {isApplyingManualOverride ? 'Overriding...' : 'Yes, override'}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className={`workbench ${isChatHidden ? 'chat-closed' : 'chat-open'}`} style={
        (typeof window !== 'undefined' && window.innerWidth > 768) ? {
          gridTemplateColumns: `minmax(0, 1fr) ${isChatHidden ? '0px' : `${chatWidth}px`}`,
          transition: isDraggingChat ? 'none' : undefined
        } : undefined
      }>
        {/* ════════════════════════ LEFT: DATA DASHBOARD ════════════════════════ */}
        <div className="workbench-data">
          {/* Read-only login banner */}
          {isReadOnly && showLoginBanner && (
            <div style={{
              background: 'rgba(245, 158, 11, 0.08)',
              border: '1px solid rgba(245, 158, 11, 0.2)',
              borderRadius: '10px',
              padding: '12px 16px',
              marginBottom: '16px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '12px',
              flexWrap: 'wrap'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '13px', color: 'var(--text-primary)' }}>
                <span style={{ fontSize: '16px' }}>🔒</span>
                <span>
                  You're previewing the dashboard. <strong>Sign up</strong> to unlock AI chat, save your portfolio, and get personalized insights.
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <button type="button" onClick={goToLogin} style={{ fontSize: '12px', padding: '8px 14px', borderRadius: '8px' }}>
                  Sign Up / Log In
                </button>
                <button type="button" onClick={dismissLoginBanner} style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: '4px' }}>
                  ✕
                </button>
              </div>
            </div>
          )}

          {/* Email verification banner for authenticated users */}
          {false && (
            <div style={{
              background: 'rgba(56, 189, 248, 0.06)',
              border: '1px solid rgba(56, 189, 248, 0.2)',
              borderRadius: '10px',
              padding: '12px 16px',
              marginBottom: '16px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '12px',
              flexWrap: 'wrap'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '13px', color: 'var(--text-primary)' }}>
                <span style={{ fontSize: '16px' }}>✉️</span>
                <span>
                  Please verify your email to secure your account. A verification code was sent to <strong>{user?.email}</strong>.
                </span>
              </div>
              <button type="button" onClick={() => navigate('/login')} style={{ fontSize: '12px', padding: '8px 14px', borderRadius: '8px' }}>
                Verify
              </button>
            </div>
          )}

          {/* Portfolio tab: indices strip removed by product decision. */}
          {false && (
            <>
              {/* Market Header */}
              <div className="market-header" style={{ display: 'flex', alignItems: 'center', marginBottom: 18, borderBottom: '1px solid var(--border-subtle)', paddingBottom: 10, fontSize: 0 }}>
                <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.1px' }}>Indian Market Indices</span>
                <span className="live-dot" style={{ marginRight: 6 }} /> LIVE • NSE/BSE
              </div>

              {/* Index ticker cards */}
              <div className="index-grid">
            {indicesLoading && activeIndices.length === 0 && (
              <>
                {[1, 2, 3, 4].map(i => (
                  <div key={i} className="index-ticker-card index-skeleton" style={{
                    background: 'rgba(15, 23, 42, 0.35)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 14,
                    padding: '14px 16px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                    minWidth: 0,
                    width: '100%',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                      <div className="skeleton-block" style={{ width: 72, height: 14 }} />
                      <div className="skeleton-block" style={{ width: 48, height: 12 }} />
                    </div>
                    <div className="skeleton-block" style={{ width: 100, height: 20 }} />
                    <div className="skeleton-block" style={{ width: 80, height: 12 }} />
                    <div className="skeleton-block" style={{ width: '100%', height: 36, marginTop: 4 }} />
                  </div>
                ))}
              </>
            )}
            {indicesError && (
              <div className="index-error-banner" style={{
                gridColumn: '1 / -1',
                padding: '12px 16px',
                background: 'rgba(239, 68, 68, 0.08)',
                border: '1px solid rgba(239, 68, 68, 0.2)',
                borderRadius: 10,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: 12,
                color: 'var(--text-muted)',
              }}>
                <span>Failed to load market indices</span>
                <button onClick={retryIndices} style={{
                  background: 'transparent',
                  border: '1px solid rgba(255, 255, 255, 0.15)',
                  borderRadius: 6,
                  padding: '4px 12px',
                  fontSize: 11,
                  color: 'var(--text-primary)',
                  cursor: 'pointer',
                }}>
                  Retry
                </button>
              </div>
            )}
            {!indicesLoading && !indicesError && activeIndices.map(idx => (
              <IndexTickerCard
                key={idx.symbol}
                data={idx}
                onClick={() => openAssetHistory(idx.symbol, idx.symbol, 'index')}
              />
            ))}
              </div>
            </>
          )}

          {/* Portfolio vs Benchmark Indexed Comparison Chart */}
          <div className="data-panel" style={{ marginBottom: 36 }}>
            <div className="chart-panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%' }}>Comparative Returns (Indexed)</span>
              
              {/* Benchmark dropdown selector */}
              <div className="chart-benchmark-selector" style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }} ref={benchmarkSelectorRef}>
                <span className="benchmark-selector-label" style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>VS BENCHMARK:</span>
                <div className="benchmark-select">
                  <button
                    type="button"
                    className="benchmark-select-trigger"
                    aria-haspopup="listbox"
                    aria-expanded={isBenchmarkMenuOpen}
                    onClick={() => setIsBenchmarkMenuOpen(open => !open)}
                  >
                    <span>{BENCHMARKS.find(bench => bench.id === selectedBenchmark)?.name || 'Nifty 50'}</span>
                    <ChevronDown size={13} className={isBenchmarkMenuOpen ? 'benchmark-select-chevron open' : 'benchmark-select-chevron'} />
                  </button>
                  {isBenchmarkMenuOpen && (
                    <div className="benchmark-select-menu" role="listbox" aria-label="Benchmark selector">
                      {BENCHMARKS.map(bench => (
                        <button
                          key={bench.id}
                          type="button"
                          role="option"
                          aria-selected={selectedBenchmark === bench.id}
                          className={selectedBenchmark === bench.id ? 'benchmark-select-option active' : 'benchmark-select-option'}
                          onClick={() => {
                            setSelectedBenchmark(bench.id);
                            setIsBenchmarkMenuOpen(false);
                          }}
                        >
                          {bench.name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {compareChartData.labels.length > 0 ? (
              <InteractiveChart
                labels={compareChartData.labels}
                data={compareChartData.portValues.length > 1 ? compareChartData.portValues : compareChartData.benchValues}
                title={compareChartData.portValues.length > 1 ? "Your Portfolio (base = 100)" : "Benchmark (base = 100)"}
                unit=""
                comparisonData={compareChartData.portValues.length > 1 && compareChartData.benchValues.length > 1 ? compareChartData.benchValues : undefined}
                comparisonTitle={BENCHMARKS.find(b => b.id === selectedBenchmark)?.name || 'Benchmark'}
                height={300}
              />
            ) : (
              <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                {portfolioAnalyticsError || 'Syncing portfolio history from backend...'}
              </div>
            )}

            <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span>{portfolioAnalyticsError || (compareChartData.portValues.length > 1 ? 'Comparison is indexed to 100 using live backend portfolio analytics' : compareChartData.labels.length > 0 ? 'Benchmark history shown as portfolio history builds' : 'Portfolio history is not available yet')}</span>
              {compareChartData.labels.length > 0 && (
                <span style={{ marginLeft: 'auto', color: 'var(--accent-cyan)', cursor: 'pointer' }}
                  onClick={() => handleSuggestQuery(`Explain how my portfolio is performing compared to ${selectedBenchmark}.`, 'standard')}
                >
                  Analyse return spread →
                </span>
              )}
            </div>
          </div>

          {/* North-star: Portfolio Health + Arthik's proactive daily read */}
          {hasPortfolioHoldings && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16, marginBottom: 28 }}>
              <div className="data-panel">
                <div className="data-panel-head">
                  <div className="data-panel-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Activity size={15} color="var(--accent-cyan)" /> Portfolio Health</div>
                  <span className="section-sublabel">LIVE SCORE</span>
                </div>
                {portfolioAnalytics?.health?.score != null ? (
                  <HealthGauge health={portfolioAnalytics.health} />
                ) : (
                  <div style={{ padding: '24px 8px', color: 'var(--text-muted)', fontSize: 12 }}>Building your health score from live price history…</div>
                )}
              </div>
              <div className="data-panel">
                <div className="data-panel-head">
                  <div className="data-panel-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Sparkles size={15} color="var(--accent-cyan)" /> Arthik's daily read</div>
                  <span className="section-sublabel">{commentary?.source === 'llm' ? 'AI' : 'AUTO'} • {new Date().toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}</span>
                </div>
                {commentary?.commentary ? (
                  <>
                    <div style={{ fontSize: 13.5, lineHeight: 1.6, color: 'var(--text-primary)' }}>{commentary.commentary}</div>
                    {Array.isArray(commentary.highlights) && commentary.highlights.length > 0 && (
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
                        {commentary.highlights.map((h: any, i: number) => (
                          <div key={i} style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: '6px 10px' }}>
                            <div style={{ fontSize: 9.5, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: 0.3 }}>{h.label}</div>
                            <div style={{ fontSize: 12.5, fontWeight: 700, fontFamily: 'var(--font-mono)', color: h.tone === 'up' ? 'var(--profit)' : h.tone === 'down' ? 'var(--loss)' : 'var(--text-primary)' }}>{h.value}</div>
                          </div>
                        ))}
                      </div>
                    )}
                    <button className="summary-cta" style={{ marginTop: 14 }} onClick={() => handleSuggestQuery("Give me a deeper read on my portfolio today — what should I actually do about it?", 'deep')}>
                      <Sparkles size={13} /> Go deeper with Arthik
                    </button>
                  </>
                ) : (
                  <div style={{ padding: '20px 8px', color: 'var(--text-muted)', fontSize: 12 }}>Arthik is reading your book…</div>
                )}
              </div>
            </div>
          )}

          {/* Arthik's read on your book stats */}
          {portfolioStats && (
            <>
              <div className="section-head">
                <div className="section-title">Arthik's read on your book</div>
                <span className="section-sublabel">PERSONAL • {portfolio.length} POSITIONS</span>
              </div>
               <div className="stats-grid">
                {computedPortfolioDetails.length > 1 ? (
                  <>
                    <div className="stat-tile">
                      <div className="stat-tile-label">TODAY'S BEST</div>
                      <div className="stat-tile-value" style={{
                        color: 'var(--profit)',
                        fontSize: '13px',
                        fontFamily: 'var(--font-sans)',
                        fontWeight: 700,
                        wordBreak: 'break-word',
                        minHeight: '34px',
                        display: 'flex',
                        alignItems: 'center'
                      }}>
                        {portfolioStats.best.name}
                      </div>
                      <div className="stat-tile-sub">
                        +{Math.abs(portfolioStats.best.pnlPct).toFixed(2)}% · ₹{Math.abs(portfolioStats.best.pnl).toLocaleString('en-IN')}
                      </div>
                    </div>
                    <div className="stat-tile">
                      <div className="stat-tile-label">TODAY'S WORST</div>
                      <div className="stat-tile-value" style={{
                        color: 'var(--loss)',
                        fontSize: '13px',
                        fontFamily: 'var(--font-sans)',
                        fontWeight: 700,
                        wordBreak: 'break-word',
                        minHeight: '34px',
                        display: 'flex',
                        alignItems: 'center'
                      }}>
                        {portfolioStats.worst.name}
                      </div>
                      <div className="stat-tile-sub">
                        {portfolioStats.worst.pnlPct.toFixed(2)}% · ₹{portfolioStats.worst.pnl.toLocaleString('en-IN')}
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="stat-tile">
                    <div className="stat-tile-label">YOUR HOLDING</div>
                    <div className="stat-tile-value" style={{
                      color: 'var(--accent-cyan)',
                      fontSize: '13px',
                      fontFamily: 'var(--font-sans)',
                      fontWeight: 700,
                      wordBreak: 'break-word',
                      minHeight: '34px',
                      display: 'flex',
                      alignItems: 'center'
                    }}>
                      {portfolioStats.best.name}
                    </div>
                    <div className="stat-tile-sub">
                      {portfolioStats.best.pnlPct >= 0 ? '+' : ''}{portfolioStats.best.pnlPct.toFixed(2)}% · ₹{Math.abs(portfolioStats.best.pnl).toLocaleString('en-IN')}
                    </div>
                  </div>
                )}
                <div className="stat-tile">
                  <div className="stat-tile-label">WIN / LOSS RATIO</div>
                  <div className="stat-tile-value">
                    {portfolioStats.winners}<span style={{ color: 'var(--text-muted)' }}> / </span>{portfolioStats.losers}
                  </div>
                  <div className="stat-tile-sub" style={{ color: portfolioStats.winners >= portfolioStats.losers ? 'var(--profit)' : 'var(--loss)' }}>
                    {portfolioStats.winners >= portfolioStats.losers ? 'More green than red' : 'More red than green'}
                  </div>
                </div>
                <div className="stat-tile">
                  <div className="stat-tile-label">PORTFOLIO BETA</div>
                  <div className="stat-tile-value">{portfolioStats.beta.toFixed(2)}</div>
                  <div className="stat-tile-sub">
                    {portfolioStats.beta > 1.1 ? 'High systematic risk' : portfolioStats.beta < 0.9 ? 'Calmer than benchmark' : 'In line with Nifty'}
                  </div>
                </div>
                <div className="stat-tile">
                  <div className="stat-tile-label">Value at Risk (95%)</div>
                  <div className="stat-tile-value" style={{ color: 'var(--loss)' }}>₹{portfolioStats.var95.toFixed(0)}</div>
                  <div className="stat-tile-sub">Estimated 1-day max loss</div>
                </div>
                <div className="stat-tile stat-tile-cta" onClick={() => handleSuggestQuery('Audit my portfolio — what is the single biggest risk hiding in my book right now?', 'deep')}>
                  <div className="stat-tile-label" style={{ color: 'var(--accent-cyan)' }}>ASK ARTHIK</div>
                  <div style={{ fontSize: 13, lineHeight: 1.4, marginTop: 6, color: 'var(--text-primary)' }}>
                    "What's the one thing I'm missing about my book today?"
                  </div>
                </div>
              </div>
            </>
          )}

          {/* Double Donut Chart Flex Container (Sector & Asset Allocation) */}
          {hasPortfolioHoldings && sectorChartData.labels.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px', marginBottom: '28px' }}>
              <div className="data-panel">
                <div className="data-panel-head">
                  <div className="data-panel-title" style={{ fontSize: '13px', fontWeight: 600 }}>Sector Allocation</div>
                  <button
                    className="data-panel-link"
                    onClick={() => handleSuggestQuery('Audit my sector allocation — where am I over- or under-exposed?', 'standard')}
                  >
                    Audit →
                  </button>
                </div>
                <DonutChart
                  labels={sectorChartData.labels}
                  data={sectorChartData.data}
                  title=""
                  valueKind={sectorUsesPercent ? 'percent' : 'currency'}
                  unit={sectorUsesPercent ? '%' : undefined}
                />
              </div>
              <div className="data-panel">
                <div className="data-panel-head">
                  <div className="data-panel-title" style={{ fontSize: '13px', fontWeight: 600 }}>Asset Allocation</div>
                  <button
                    className="data-panel-link"
                    onClick={() => handleSuggestQuery('Audit my asset allocation classes.', 'standard')}
                  >
                    Audit →
                  </button>
                </div>
                <DonutChart
                  labels={assetChartData.labels}
                  data={assetChartData.data}
                  title=""
                  valueKind={assetUsesPercent ? 'percent' : 'currency'}
                  unit={assetUsesPercent ? '%' : undefined}
                />
              </div>
            </div>
          )}

          {/* ADVANCED PORTFOLIO RISK & ANALYTICS PANELS (Mutual Fund, Risk, Stress Test) */}
          {hasPortfolioHoldings && (
            <div className="data-panel" style={{ marginBottom: '28px' }}>
                <div className="data-panel-head" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '10px' }}>
                  <div className="analytics-tabs-row" style={{ gap: 16, display: 'flex', flexWrap: 'wrap' }}>
                    <button
                      onClick={() => setAnalyticsTab('risk')}
                      style={{
                        background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                        color: analyticsTab === 'risk' ? 'var(--text-primary)' : 'var(--text-secondary)',
                        fontWeight: 600, fontSize: 13,
                      }}
                    >
                      Moat & Risk Matrix
                    </button>
                    <button
                      onClick={() => setAnalyticsTab('mf')}
                      style={{
                        background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                        color: analyticsTab === 'mf' ? 'var(--text-primary)' : 'var(--text-secondary)',
                        fontWeight: 600, fontSize: 13,
                      }}
                    >
                      Mutual Fund Diagnostics
                    </button>
                    <button
                      onClick={() => setAnalyticsTab('corr')}
                      style={{
                        background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                        color: analyticsTab === 'corr' ? 'var(--text-primary)' : 'var(--text-secondary)',
                        fontWeight: 600, fontSize: 13,
                      }}
                    >
                      Correlation
                    </button>
                    <button
                      onClick={() => setAnalyticsTab('stress')}
                      style={{
                        background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                        color: analyticsTab === 'stress' ? 'var(--text-primary)' : 'var(--text-secondary)',
                        fontWeight: 600, fontSize: 13,
                      }}
                    >
                      Shock & Stress Simulator
                    </button>
                    <button
                      onClick={() => setAnalyticsTab('tax')}
                      style={{
                        background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                        color: analyticsTab === 'tax' ? 'var(--text-primary)' : 'var(--text-secondary)',
                        fontWeight: 600, fontSize: 13,
                      }}
                    >
                      Tax & Harvesting
                    </button>
                  </div>
                </div>

              <div style={{ marginTop: '14px' }}>
                {analyticsTab === 'risk' && (() => {
                  const risk = portfolioAnalytics?.risk || {};
                  const rolling = portfolioAnalytics?.rolling_returns || {};
                  const dd = portfolioAnalytics?.drawdown_series || [];
                  const attr = portfolioAnalytics?.attribution || {};
                  const contributors = attr.top_contributors || [];
                  const detractors = attr.top_detractors || [];
                  const totalVal = Number(portfolioAnalytics?.total_market_value) || 0;
                  const varPct = risk.historical_var_pct;
                  const cvarPct = risk.cvar_pct;
                  const hhiPct = Number(risk.hhi || 0) * 10000;
                  return (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 12 }}>
                        <MetricCard label="XIRR (money-weighted)" value={risk.xirr_pct != null ? fmtNum(risk.xirr_pct, 1, '%') : '—'} sub="Annualized, by cashflow" tone={Number(risk.xirr_pct) >= 0 ? 'up' : 'down'} />
                        <MetricCard label="Annualized return" value={fmtNum(risk.annualized_return_pct, 1, '%')} sub="From NAV history" tone={Number(risk.annualized_return_pct) >= 0 ? 'up' : 'down'} />
                        <MetricCard label="Sharpe ratio" value={fmtNum(risk.sharpe, 2)} sub={`vs ${fmtNum(risk.risk_free_rate_pct, 1, '%')} risk-free`} tone={Number(risk.sharpe) >= 1 ? 'up' : Number(risk.sharpe) < 0 ? 'down' : 'neutral'} />
                        <MetricCard label="Sortino ratio" value={fmtNum(risk.sortino, 2)} sub="Downside-adjusted" tone={Number(risk.sortino) >= 1 ? 'up' : 'neutral'} />
                        <MetricCard label="Calmar ratio" value={fmtNum(risk.calmar, 2)} sub="Return ÷ max drawdown" tone={Number(risk.calmar) >= 1 ? 'up' : 'neutral'} />
                        <MetricCard label="Volatility (ann.)" value={fmtNum(risk.annualized_volatility_pct, 1, '%')} sub="Std-dev of returns" />
                        <MetricCard label="Beta vs Nifty" value={fmtNum(risk.beta_vs_nifty, 2)} sub={Number(risk.beta_vs_nifty) > 1.1 ? 'More volatile than index' : Number(risk.beta_vs_nifty) < 0.9 ? 'Calmer than index' : 'In line with index'} />
                        <MetricCard label="Max drawdown" value={fmtNum(risk.max_drawdown_pct, 1, '%')} sub="Worst peak-to-trough" tone="down" />
                        <MetricCard label="1-day VaR (95%)" value={varPct != null ? fmtINR(totalVal * varPct / 100) : '—'} sub={varPct != null ? `Historical · ${fmtNum(varPct, 2, '%')}` : 'Building distribution'} tone="down" />
                        <MetricCard label="CVaR (expected shortfall)" value={cvarPct != null ? fmtINR(totalVal * cvarPct / 100) : '—'} sub={cvarPct != null ? `Avg loss beyond VaR · ${fmtNum(cvarPct, 2, '%')}` : '—'} tone="down" />
                        <MetricCard label="Diversification (HHI)" value={fmtNum(hhiPct, 0)} sub={hhiPct > 2500 ? 'Highly concentrated' : 'Well diversified'} tone={hhiPct > 2500 ? 'down' : 'up'} />
                        <MetricCard label="Top-5 concentration" value={fmtNum(risk.top5_weight_pct, 1, '%')} sub="Share in 5 biggest names" tone={Number(risk.top5_weight_pct) > 60 ? 'down' : 'neutral'} />
                      </div>

                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
                        <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
                          <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: 11, marginBottom: 10 }}>ROLLING RETURNS</div>
                          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                            {['1M', '3M', '6M', '1Y'].map(k => {
                              const v = rolling?.[k];
                              return (
                                <div key={k} style={{ textAlign: 'center' }}>
                                  <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{k}</div>
                                  <div style={{ fontSize: 14, fontWeight: 700, fontFamily: 'var(--font-mono)', color: v == null ? 'var(--text-muted)' : Number(v) >= 0 ? 'var(--profit)' : 'var(--loss)' }}>{v == null ? '—' : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(1)}%`}</div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                        <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', fontWeight: 600, fontSize: 11, marginBottom: 8 }}><span>UNDERWATER (DRAWDOWN)</span><span style={{ color: 'var(--loss)', fontFamily: 'var(--font-mono)' }}>{fmtNum(risk.max_drawdown_pct, 1, '%')}</span></div>
                          {dd.length > 1 ? <DrawdownSparkline series={dd} /> : <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '10px 0' }}>Building drawdown curve…</div>}
                        </div>
                      </div>

                      {(contributors.length > 0 || detractors.length > 0) && (
                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12 }}>
                          <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
                            <div style={{ color: 'var(--profit)', fontWeight: 600, fontSize: 11, marginBottom: 8 }}>TOP CONTRIBUTORS</div>
                            {contributors.length === 0 ? <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>None positive yet.</div> : contributors.map((c: any) => (
                              <div key={c.symbol} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginTop: 6 }}>
                                <span style={{ color: 'var(--text-primary)' }}>{String(c.symbol || '').replace('.NS', '').replace('.BO', '')} <span style={{ color: 'var(--text-muted)' }}>· {fmtNum(c.weight_pct, 1, '%')}</span></span>
                                <span style={{ color: 'var(--profit)', fontFamily: 'var(--font-mono)' }}>+{fmtNum(c.contribution_pct, 2, '%')}</span>
                              </div>
                            ))}
                          </div>
                          <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
                            <div style={{ color: 'var(--loss)', fontWeight: 600, fontSize: 11, marginBottom: 8 }}>TOP DETRACTORS</div>
                            {detractors.length === 0 ? <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>No drags. Enjoy it.</div> : detractors.map((c: any) => (
                              <div key={c.symbol} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginTop: 6 }}>
                                <span style={{ color: 'var(--text-primary)' }}>{String(c.symbol || '').replace('.NS', '').replace('.BO', '')} <span style={{ color: 'var(--text-muted)' }}>· {fmtNum(c.weight_pct, 1, '%')}</span></span>
                                <span style={{ color: 'var(--loss)', fontFamily: 'var(--font-mono)' }}>{fmtNum(c.contribution_pct, 2, '%')}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      <div style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
                        Risk-adjusted ratios use a {fmtNum(risk.risk_free_rate_pct, 1, '%')} risk-free rate. VaR / CVaR are 1-day historical at 95% confidence from live price history.
                        {actionQueue.length > 0 && <span style={{ color: 'var(--accent-cyan)', cursor: 'pointer', marginLeft: 6 }} onClick={() => handleSuggestQuery('Check my portfolio action items.', 'standard')}>· {actionQueue.length} action item{actionQueue.length > 1 ? 's' : ''} →</span>}
                      </div>
                    </div>
                  );
                })()}

                {analyticsTab === 'mf' && (() => {
                  const mfHoldings = enrichedPortfolio.filter(p => p.assetClass === 'Mutual Fund');
                  const totalMfValue = mfHoldings.reduce((sum, p) => sum + (p.qty * p.current), 0);
                  const backendMfValue = finiteNumber(mfAnalytics?.total_mf_value);
                  const displayedMfValue = backendMfValue > 0 ? backendMfValue : totalMfValue;
                  const weightedTer = finiteNumber(mfAnalytics?.aum_weighted_ter_pct);
                  const hasWeightedTer = weightedTer > 0;
                  const schemeCount = Number.isFinite(Number(mfAnalytics?.scheme_count))
                    ? Number(mfAnalytics.scheme_count)
                    : mfHoldings.length;
                  const categoryBreakdown = mfAnalytics?.category_breakdown || {};
                  const amcConcentration = mfAnalytics?.amc_concentration || {};

                  return (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                      {mfHoldings.length > 0 ? (
                        <>
                          {/* Summary Metrics Row */}
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
                            <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px' }}>
                              <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: '11px', marginBottom: '4px' }}>MUTUAL FUND ASSETS</div>
                              <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                                ₹{displayedMfValue.toLocaleString('en-IN')}
                              </div>
                              <div style={{ color: 'var(--text-muted)', marginTop: '4px', fontSize: '10px' }}>
                                {schemeCount} Active Scheme{schemeCount > 1 ? 's' : ''}
                              </div>
                            </div>

                            <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px' }}>
                              <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: '11px', marginBottom: '4px' }}>AUM-WEIGHTED TER</div>
                              <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                                {hasWeightedTer ? `${weightedTer.toFixed(2)}%` : 'Not synced'}
                              </div>
                              <div style={{ 
                                color: hasWeightedTer ? 'var(--text-muted)' : 'var(--text-secondary)', 
                                marginTop: '4px', 
                                fontSize: '10px',
                                fontWeight: 600
                              }}>
                                {hasWeightedTer ? 'From backend MF metadata' : 'Needs AMFI TER metadata for schemes'}
                              </div>
                            </div>

                            <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px' }}>
                              <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: '11px', marginBottom: '4px' }}>PORTFOLIO EXPOSURE</div>
                              <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                                {((displayedMfValue / (portfolioSummary.totalValue || 1)) * 100).toFixed(1)}%
                              </div>
                              <div style={{ color: 'var(--text-muted)', marginTop: '4px', fontSize: '10px' }}>
                                Allocation in Mutual Funds
                              </div>
                            </div>
                          </div>

                          {(Object.keys(categoryBreakdown).length > 0 || Object.keys(amcConcentration).length > 0) && (
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px' }}>
                              {Object.keys(categoryBreakdown).length > 0 && (
                                <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px' }}>
                                  <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: '11px', marginBottom: '8px' }}>CATEGORY BREAKDOWN</div>
                                  {Object.entries(categoryBreakdown).map(([category, pct]) => (
                                    <div key={category} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginTop: 6 }}>
                                      <span style={{ color: 'var(--text-primary)', textTransform: 'capitalize' }}>{category.replace(/_/g, ' ')}</span>
                                      <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>{finiteNumber(pct).toFixed(1)}%</span>
                                    </div>
                                  ))}
                                </div>
                              )}
                              {Object.keys(amcConcentration).length > 0 && (
                                <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px' }}>
                                  <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: '11px', marginBottom: '8px' }}>AMC CONCENTRATION</div>
                                  {Object.entries(amcConcentration).slice(0, 5).map(([amc, pct]) => (
                                    <div key={amc} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginTop: 6 }}>
                                      <span style={{ color: 'var(--text-primary)' }}>{amc}</span>
                                      <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>{finiteNumber(pct).toFixed(1)}%</span>
                                    </div>
                                  ))}
                                </div>
                              )}
                            </div>
                          )}

                          {/* Individual Scheme Detail Cards */}
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px', marginTop: '4px' }}>
                            {mfHoldings.map(item => {
                              const weightInPortfolio = ((item.qty * item.current) / (portfolioSummary.totalValue || 1)) * 100;
                              
                              return (
                                <div 
                                  key={item.symbol} 
                                  style={{ 
                                    background: 'rgba(255, 255, 255, 0.02)', 
                                    border: '1px solid rgba(255, 255, 255, 0.06)', 
                                    borderRadius: '10px', 
                                    padding: '16px',
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '12px',
                                    boxShadow: '0 4px 20px rgba(0, 0, 0, 0.15)'
                                  }}
                                >
                                  {/* Card Header */}
                                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                    <div>
                                      <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>{item.name}</div>
                                      <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px', display: 'flex', gap: '8px', alignItems: 'center' }}>
                                        <span style={{ fontFamily: 'var(--font-mono)' }}>{item.symbol}</span>
                                        <span>•</span>
                                        <span style={{ color: 'var(--accent-cyan)' }}>{item.sector}</span>
                                      </div>
                                    </div>
                                    <div style={{ textAlign: 'right' }}>
                                      <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                                        ₹{(item.qty * item.current).toLocaleString('en-IN')}
                                      </div>
                                      <div style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                                        Weight: <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{weightInPortfolio.toFixed(1)}%</span>
                                      </div>
                                    </div>
                                  </div>

                                </div>
                              );
                            })}
                          </div>
                        </>
                      ) : (
                        <div style={{ textAlign: 'center', padding: '24px 14px', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px' }}>
                          <div style={{ fontStyle: 'italic', color: 'var(--text-muted)', fontSize: '12.5px', marginBottom: '6px' }}>
                            No Mutual Fund schemes found in your portfolio holdings statement.
                          </div>
                          <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                            Mutual Fund Diagnostics will display only verified synced metrics for schemes present in your portfolio.
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })()}

                {analyticsTab === 'stress' && (() => {
                  const scenarios = [
                    { key: 'nifty_down_10', label: 'Nifty −10%' },
                    { key: 'nifty_down_20', label: 'Nifty −20%' },
                    { key: 'nifty_down_30', label: 'Nifty −30%' },
                    { key: 'covid_2020', label: '2020 COVID' },
                    { key: 'gfc_2008', label: '2008 GFC' },
                  ];
                  const res = stressResult;
                  const loss = Number(res?.portfolio_loss_pct);
                  return (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Deterministic shock engine — each holding's hit = weight × beta × shock, repriced on live betas.</div>
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        {scenarios.map(s => (
                          <button key={s.key} onClick={() => runStressTest(s.key)} disabled={stressLoading}
                            style={{ padding: '8px 12px', fontSize: 11, borderRadius: 8, cursor: 'pointer',
                              background: stressScenario === s.key && res ? 'rgba(251,113,133,0.16)' : 'rgba(251,113,133,0.05)',
                              border: `1px solid ${stressScenario === s.key && res ? 'var(--loss)' : 'var(--border-subtle)'}`,
                              color: 'var(--text-primary)' }}>{s.label}</button>
                        ))}
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
                        <div style={{ fontSize: 11, color: 'var(--text-secondary)', fontWeight: 600 }}>CUSTOM NIFTY SHOCK</div>
                        <input type="range" min={-50} max={0} step={1} value={stressShock} onChange={e => setStressShock(Number(e.target.value))} style={{ flex: 1, minWidth: 160, accentColor: 'var(--loss)' }} />
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: 'var(--loss)', minWidth: 52, textAlign: 'right' }}>{stressShock}%</div>
                        <button onClick={() => runStressTest('custom', stressShock)} disabled={stressLoading}
                          style={{ padding: '8px 14px', fontSize: 11, borderRadius: 8, cursor: 'pointer', background: 'var(--loss)', border: 'none', color: '#fff', fontWeight: 700 }}>
                          {stressLoading ? 'Running…' : 'Run shock'}
                        </button>
                      </div>
                      {res && res.status === 'OK' && (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
                            <MetricCard label="Projected impact" value={`${loss >= 0 ? '+' : ''}${loss.toFixed(2)}%`} tone="down" sub={res.scenario_label || res.scenario} />
                            <MetricCard label="Rupee loss in shock" value={fmtINR(res.projected_value_loss)} tone="down" sub="Estimated" />
                            <MetricCard label="Portfolio after shock" value={fmtINR(res.projected_value)} sub={`From ${fmtINR(res.total_value)}`} />
                          </div>
                          <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
                            <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: 11, marginBottom: 10 }}>BIGGEST CASUALTIES</div>
                            {(res.positions || []).slice(0, 6).map((p: any) => {
                              const impact = Number(p.impact_pct) || 0;
                              const w = Math.min(100, Math.abs(impact) / (Math.abs(loss) || 1) * 100);
                              return (
                                <div key={p.symbol} style={{ marginBottom: 8 }}>
                                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 3 }}>
                                    <span style={{ color: 'var(--text-primary)' }}>{String(p.symbol || '').replace('.NS', '').replace('.BO', '')} <span style={{ color: 'var(--text-muted)' }}>· β {fmtNum(p.beta, 2)} · {fmtNum(p.weight_pct, 1, '%')}</span></span>
                                    <span style={{ color: 'var(--loss)', fontFamily: 'var(--font-mono)' }}>{impact.toFixed(2)}%</span>
                                  </div>
                                  <div style={{ height: 5, background: 'rgba(255,255,255,0.06)', borderRadius: 3 }}>
                                    <div style={{ height: '100%', width: `${w}%`, background: 'var(--loss)', borderRadius: 3 }} />
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                      {!res && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Pick a scenario or drag the slider to simulate your book.</div>}
                    </div>
                  );
                })()}

                {analyticsTab === 'corr' && (() => {
                  const cm = portfolioAnalytics?.correlation_matrix;
                  const hasMatrix = cm && cm.labels && cm.labels.length >= 2;
                  return (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Pairwise 1-year return correlation across your top holdings. Red = names that move together (hidden concentration); green = diversifiers.</div>
                      {hasMatrix ? <CorrelationHeatmap matrix={cm.matrix} labels={cm.labels} /> : (
                        <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '12px 0' }}>Need at least 2 equity holdings with price history to map correlations.</div>
                      )}
                    </div>
                  );
                })()}

                {analyticsTab === 'tax' && (() => {
                  const t = taxSummary;
                  const harvest = t?.harvest;
                  return (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                      {t && t.status === 'OK' ? (
                        <>
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
                            <MetricCard label="Unrealized gains" value={fmtINR(t.unrealized_total)} tone={Number(t.unrealized_total) >= 0 ? 'up' : 'down'} sub="If sold today" />
                            <MetricCard label="Short-term (STCG)" value={fmtINR(t.unrealized_stcg)} sub="Held < 1 year" />
                            <MetricCard label="Long-term (LTCG)" value={fmtINR(t.unrealized_ltcg)} sub="Held > 1 year" />
                            <MetricCard label="Est. tax if sold today" value={fmtINR(t.estimated_tax_if_sold_today)} tone="down" sub="FY25-26 rates" />
                          </div>
                          <div style={{ background: 'rgba(52,211,153,0.04)', border: '1px solid rgba(52,211,153,0.2)', borderRadius: 10, padding: 14 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                              <TrendingDown size={15} color="var(--profit)" />
                              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>Tax-loss harvesting</div>
                            </div>
                            {harvest && harvest.count > 0 ? (
                              <>
                                <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 12 }}>
                                  Booking these {harvest.count} loss{harvest.count > 1 ? 'es' : ''} realizes <b style={{ color: 'var(--loss)' }}>{fmtINR(harvest.total_harvestable_loss)}</b> in losses and can shield up to <b style={{ color: 'var(--profit)' }}>{fmtINR(harvest.total_potential_shield)}</b> of tax on offsetting gains.
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                  {harvest.opportunities.slice(0, 6).map((o: any) => (
                                    <div key={o.symbol} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: '8px 12px' }}>
                                      <div>
                                        <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-primary)' }}>{String(o.symbol || '').replace('.NS', '').replace('.BO', '')} <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>· {o.gain_type}</span></div>
                                        <div style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>{o.name || ''}</div>
                                      </div>
                                      <div style={{ textAlign: 'right' }}>
                                        <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--loss)', fontFamily: 'var(--font-mono)' }}>−{fmtINR(o.unrealized_loss).replace('-', '')}{o.loss_pct != null ? ` (${Number(o.loss_pct).toFixed(1)}%)` : ''}</div>
                                        <div style={{ fontSize: 10, color: 'var(--profit)' }}>shield ≈ {fmtINR(o.potential_tax_shield)}</div>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </>
                            ) : (
                              <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>No harvestable losses right now — none of your holdings sit on an unrealized loss.</div>
                            )}
                          </div>
                          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>Estimates only — actual liability depends on your slab, other income and realized trades. Holding period uses your recorded purchase date where available.</div>
                        </>
                      ) : (
                        <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '12px 0' }}>Tax view loads once your holdings sync.</div>
                      )}
                    </div>
                  );
                })()}
              </div>
            </div>
          )}

          {/* Top Movers */}
          <div className="section-head">
            <div className="section-title">Top movers in your holdings</div>
            <span className="section-sublabel">YOUR PORTFOLIO</span>
          </div>
          <div className="movers-grid">
            <div className="movers-col">
              <div className="movers-col-head" style={{ color: 'var(--profit)' }}>↗ Gainers</div>
              {gainers.length === 0 ? (
                <div className="movers-empty">No green names today.</div>
              ) : gainers.map(s => (
                <div key={s.symbol} className="mover-row" onClick={() => openAssetHistory(s.symbol, s.name, 'equity')}>
                  <div>
                    <div className="mover-sym">{s.symbol} {s.isOwned && <span className="owned-dot" title="You own this" />}</div>
                    <div className="mover-name">{s.name}</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="mover-price">₹{s.price}</div>
                    <div className="mover-pct" style={{ color: 'var(--profit)' }}>+{(s.changePct ?? 0).toFixed(2)}%</div>
                  </div>
                </div>
              ))}
            </div>
            <div className="movers-col">
              <div className="movers-col-head" style={{ color: 'var(--loss)' }}>↘ Losers</div>
              {losersList.length === 0 ? (
                <div className="movers-empty">All green. Enjoy it while it lasts.</div>
              ) : losersList.map(s => (
                <div key={s.symbol} className="mover-row" onClick={() => openAssetHistory(s.symbol, s.name, 'equity')}>
                  <div>
                    <div className="mover-sym">{s.symbol} {s.isOwned && <span className="owned-dot" title="You own this" />}</div>
                    <div className="mover-name">{s.name}</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="mover-price">₹{s.price}</div>
                    <div className="mover-pct" style={{ color: 'var(--loss)' }}>{(s.changePct ?? 0).toFixed(2)}%</div>
                  </div>
                </div>
              ))}
            </div>
            <div className="movers-col">
              <div className="movers-col-head">⚡ Most active</div>
              {mostActive.length === 0 ? (
                <div className="movers-empty">Waiting for live NSE/BSE movement.</div>
              ) : mostActive.map(s => (
                <div key={s.symbol} className="mover-row" onClick={() => openAssetHistory(s.symbol, s.name, 'equity')}>
                  <div>
                    <div className="mover-sym">{s.symbol} {s.isOwned && <span className="owned-dot" title="You own this" />}</div>
                    <div className="mover-name">{s.name}</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="mover-price">₹{s.price}</div>
                    <div className="mover-pct" style={{ color: (s.changePct ?? 0) >= 0 ? 'var(--profit)' : 'var(--loss)' }}>
                      {(s.changePct ?? 0) >= 0 ? '+' : ''}{(s.changePct ?? 0).toFixed(2)}%
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* AI Market summary */}
          <div className="section-head">
            <div className="section-title">India market summary</div>
            <span className="section-sublabel">ARTHIK'S BRIEF • {marketSummary.sourcesCount} sources</span>
          </div>

          <div className="summary-card">
            <div className="summary-card-headline">{marketSummary.headline}</div>
            <div className="summary-card-body">{marketSummary.body}</div>
            <button
              className="summary-cta"
              onClick={() => handleSuggestQuery('Dive deeper on today\'s market moves — what should I actually do about my portfolio?', 'deep')}
            >
              <Sparkles size={13} /> Have Arthik dig into it
            </button>
          </div>

          {/* Holdings vs Watchlist table */}
          <div className="data-grid" style={{ gridTemplateColumns: 'minmax(0, 1fr)' }}>
            <div className="data-panel">
              <div className="data-panel-head">
                <div className="panel-tabs" style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                  <button
                    onClick={() => setActiveTab('portfolio')}
                    style={{
                      background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                      color: activeTab === 'portfolio' ? 'var(--text-primary)' : 'var(--text-secondary)',
                      fontWeight: 600, fontSize: 13, whiteSpace: 'nowrap'
                    }}
                  >
                    Holdings
                  </button>
                  <button
                    onClick={() => setActiveTab('watchlist')}
                    style={{
                      background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                      color: activeTab === 'watchlist' ? 'var(--text-primary)' : 'var(--text-secondary)',
                      fontWeight: 600, fontSize: 13, whiteSpace: 'nowrap'
                    }}
                  >
                    Watchlist
                  </button>
                </div>
              </div>

              {activeTab === 'portfolio' && hasPortfolioHoldings && (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(4, minmax(130px, 1fr)) auto',
                    gap: 10,
                    marginBottom: 16,
                  }}
                >
                  <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 10, background: 'rgba(15, 23, 42, 0.34)', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <span style={{ color: 'var(--text-secondary)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 700 }}>Holdings</span>
                    <span style={{ color: 'var(--text-primary)', fontSize: 15, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{computedPortfolioDetails.length}</span>
                  </div>
                  <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 10, background: 'rgba(15, 23, 42, 0.34)', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <span style={{ color: 'var(--text-secondary)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 700 }}>Invested</span>
                    <span style={{ color: 'var(--text-primary)', fontSize: 15, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmtINR(liveComputedTotalCost)}</span>
                  </div>
                  <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 10, background: 'rgba(15, 23, 42, 0.34)', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <span style={{ color: 'var(--text-secondary)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 700 }}>Current Value</span>
                    <span style={{ color: 'var(--text-primary)', fontSize: 15, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmtINR(sidebarTotalValue)}</span>
                  </div>
                  <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 10, background: 'rgba(15, 23, 42, 0.34)', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <span style={{ color: 'var(--text-secondary)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 700 }}>Unrealized P&L</span>
                    <span style={{ color: sidebarTotalPnL >= 0 ? 'var(--profit)' : 'var(--loss)', fontSize: 15, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
                      {`${sidebarTotalPnL >= 0 ? '+' : ''}${fmtINR(sidebarTotalPnL)} (${sidebarTotalReturnPct.toFixed(2)}%)`}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => navigate('/get-started')}
                    style={{
                      border: '1px solid rgba(56, 189, 248, 0.28)',
                      borderRadius: 10,
                      background: 'rgba(56, 189, 248, 0.08)',
                      color: 'var(--accent-cyan)',
                      fontSize: 12,
                      fontWeight: 700,
                      padding: '0 14px',
                      cursor: 'pointer',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    Update holdings
                  </button>
                </div>
              )}

              {activeTab === 'portfolio' ? (
                computedPortfolioDetails.length > 0 ? (
                  <PortfolioTable portfolio={computedPortfolioDetails} onSelectStock={handleSelectStock} onAnalyzeStock={handleAnalyzeStock} />
                ) : (
                  <div style={{ padding: '8px 0 2px' }}>
                    <div
                      style={{
                        maxWidth: 760,
                        margin: '0 auto',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: 14,
                        background: 'rgba(15, 23, 42, 0.25)',
                        padding: '20px 16px',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 14,
                      }}
                    >
                      <div style={{ textAlign: 'center' }}>
                        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)' }}>Set up your portfolio</div>
                        <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>
                          Add your name first, then choose how you want to add holdings.
                        </div>
                      </div>

                      <div style={{ maxWidth: 420, margin: '0 auto 6px', textAlign: 'left', width: '100%' }}>
                        <label style={{ display: 'block', fontSize: 11, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600, marginBottom: 6 }}>
                          Your Name
                        </label>
                        <input
                          type="text"
                          placeholder="Enter your name"
                          value={portfolioOnboardName}
                          onChange={(event) => setPortfolioOnboardName(event.target.value)}
                          onBlur={persistPortfolioOnboardName}
                          style={{
                            width: '100%',
                            fontSize: 14,
                            padding: '12px 14px',
                            borderRadius: 10,
                            border: '1px solid var(--border-subtle)',
                            background: 'rgba(15, 23, 42, 0.35)',
                            color: 'var(--text-primary)',
                            outline: 'none',
                          }}
                        />
                      </div>

                      {!canStartPortfolioSetup && (
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', textAlign: 'center' }}>
                          Please enter your name to continue.
                        </div>
                      )}

                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 10 }}>
                        <button
                          type="button"
                          onClick={handlePortfolioManualSetup}
                          disabled={!canStartPortfolioSetup}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: 8,
                            borderRadius: 10,
                            border: '1px solid rgba(56, 189, 248, 0.28)',
                            background: 'rgba(56, 189, 248, 0.08)',
                            color: 'var(--accent-cyan)',
                            fontWeight: 700,
                            fontSize: 12,
                            height: 42,
                            cursor: canStartPortfolioSetup ? 'pointer' : 'not-allowed',
                            opacity: canStartPortfolioSetup ? 1 : 0.6,
                          }}
                        >
                          <Keyboard size={15} />
                          Enter holdings manually
                        </button>
                        <button
                          type="button"
                          onClick={handlePortfolioUploadSetup}
                          disabled={!canStartPortfolioSetup}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: 8,
                            borderRadius: 10,
                            border: '1px solid rgba(129, 140, 248, 0.32)',
                            background: 'rgba(129, 140, 248, 0.1)',
                            color: 'var(--accent-indigo)',
                            fontWeight: 700,
                            fontSize: 12,
                            height: 42,
                            cursor: canStartPortfolioSetup ? 'pointer' : 'not-allowed',
                            opacity: canStartPortfolioSetup ? 1 : 0.6,
                          }}
                        >
                          <UploadCloud size={15} />
                          Upload holding statement
                        </button>
                      </div>
                    </div>
                  </div>
                )
              ) : (
                <WatchlistCard
                  stocks={watchlistStocks}
                  onSelectStock={handleSelectStock}
                  onAskStock={handleAnalyzeStock}
                  onAddStock={handleAddStock}
                  onRemoveStock={handleRemoveStock}
                />
              )}
            </div>

            {/* Portfolio tab: ProspektLab Research panel removed by product decision. */}
          </div>

          {/* News Feed */}
          <div className="section-head" style={{ marginTop: 24 }}>
            <div className="section-title">News on your holdings</div>
            <span className="section-sublabel">{portfolioSymbols.length > 0 ? 'HOLDING-RELEVANT · ARTHIK\'S SENTIMENT' : 'LIVE NEWS · ARTHIK\'S SENTIMENT'}</span>
          </div>
          <div className="news-grid">
            {newsLoading && (
              <>
                {[1, 2, 3, 4].map(i => (
                  <div key={i} className="news-card news-skeleton" style={{
                    padding: '14px 16px',
                    background: 'rgba(15, 23, 42, 0.35)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 12,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                  }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <div className="skeleton-block" style={{ width: 56, height: 10 }} />
                      <div className="skeleton-block" style={{ width: 64, height: 10 }} />
                      <div className="skeleton-block" style={{ width: 40, height: 10 }} />
                    </div>
                    <div className="skeleton-block" style={{ width: '100%', height: 14 }} />
                    <div className="skeleton-block" style={{ width: '70%', height: 14 }} />
                  </div>
                ))}
              </>
            )}
            {newsError && (
              <div className="news-error-banner" style={{
                gridColumn: '1 / -1',
                padding: '12px 16px',
                background: 'rgba(239, 68, 68, 0.08)',
                border: '1px solid rgba(239, 68, 68, 0.2)',
                borderRadius: 10,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: 12,
                color: 'var(--text-muted)',
              }}>
                <span>Failed to load market news</span>
                <button onClick={retryNews} style={{
                  background: 'transparent',
                  border: '1px solid rgba(255, 255, 255, 0.15)',
                  borderRadius: 6,
                  padding: '4px 12px',
                  fontSize: 11,
                  color: 'var(--text-primary)',
                  cursor: 'pointer',
                }}>
                  Retry
                </button>
              </div>
            )}
            {!newsLoading && !newsError && newsFeed.map(n => (
              <div key={n.id} className="news-card" onClick={() => handleSuggestQuery(`Tell me more about: ${n.headline}`, 'standard')}>
                <div className="news-card-meta">
                  <div className="news-card-meta-copy">
                  <span className="news-source">{n.source}</span>
                  <span className="news-time">· {n.time}</span>
                  </div>
                  <span className="news-sentiment" style={{ color: sentimentColor(n.sentiment), borderColor: sentimentColor(n.sentiment) + '40' }}>
                    {sentimentLabel(n.sentiment)}
                  </span>
                </div>
                <div className="news-headline">{n.headline}</div>
                {n.tickers.length > 0 && (
                  <div className="news-tickers">
                    {n.tickers.map((t: string) => <span key={t} className="news-ticker-pill">{t}</span>)}
                  </div>
                )}
              </div>
            ))}
            {!newsLoading && !newsError && newsFeed.length === 0 && (
              <div style={{
                gridColumn: '1 / -1',
                padding: '18px 16px',
                background: 'rgba(15, 23, 42, 0.35)',
                border: '1px solid var(--border-subtle)',
                borderRadius: 12,
                fontSize: 12.5,
                color: 'var(--text-muted)',
                textAlign: 'center',
              }}>
                {portfolioSymbols.length > 0
                  ? 'No fresh news on your holdings right now. We only show stories tied to the stocks you own.'
                  : 'Add holdings to see news scoped to your portfolio.'}
              </div>
            )}
          </div>

        </div>

        {/* ════════════════════════ RIGHT: CHAT RAIL ════════════════════════ */}
        <div className="workbench-chat" style={{
          position: 'relative',
          width: isChatHidden ? '0px' : `${chatWidth}px`,
          display: 'flex',
          flexDirection: 'column',
          borderLeft: isChatHidden ? 'none' : undefined,
          overflow: 'visible',
          transition: isDraggingChat ? 'none' : 'box-shadow 0.4s ease',
          boxShadow: isChatHighlighted ? '0 0 0 2px rgba(56, 189, 248, 0.45), -4px 0 24px rgba(56, 189, 248, 0.08)' : undefined
        }}>
          {/* Login overlay — blurs entire chat rail when user is not authenticated */}
          {isReadOnly && (
            <div
              onClick={() => navigate('/login?redirect=/dashboard/portfolio')}
              style={{
                position: 'absolute',
                inset: 0,
                zIndex: 20,
                backdropFilter: 'blur(6px)',
                WebkitBackdropFilter: 'blur(6px)',
                background: 'rgba(15, 23, 42, 0.35)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '12px',
                borderRadius: '12px',
                cursor: 'pointer'
              }}
            >
              <Lock size={32} color="var(--text-muted)" />
              <span style={{ color: 'var(--text-secondary)', fontSize: 14, fontWeight: 600 }}>
                Login to unlock
              </span>
            </div>
          )}

          {/* Boundary toggle removed — use header close button + floating restore ball */}

          {/* Inner Content that hides when collapsed */}
          <div style={{
            display: isChatHidden ? 'none' : 'flex',
            flexDirection: 'column',
            width: '100%',
            height: '100%',
            overflow: 'hidden'
          }}>
          {/* Mobile drag handle */}
          <button
            className="chat-mobile-handle"
            onClick={() => {
              setIsChatHidden(true);
              setChatWidth(0);
              localStorage.setItem('prospektlab_chat_width', '0');
            }}
            aria-label="Close chat"
          >
            <div className="chat-mobile-handle-bar" />
          </button>

          {/* Desktop drag handle left edge */}
          <div
            className="drag-handle-vertical drag-handle-left"
            onMouseDown={() => setIsDraggingChat(true)}
            style={{ width: '6px' }}
          />

          <div className="chat-rail-head">
            <div className="chat-rail-title">Arthik</div>
            <div className="chat-rail-actions">
               <button className="chat-rail-iconbtn" title="Collapse Chat" onClick={() => {
                 setIsChatHidden(true);
                 setChatWidth(0);
                 localStorage.setItem('prospektlab_chat_width', '0');
               }}>
                 <ChevronRight size={16} color="#38BDF8" style={{ minWidth: 16, minHeight: 16, display: 'block' }} />
               </button>
            </div>
          </div>

          <div className="chat-rail-body" ref={chatContainerRef}>
            {!hasEngaged ? (
              <>
                <div className="chat-rail-greeting">
                  {arthikGreeting}
                </div>

                {suggestions.map((s, i) => (
                  <button key={i} className="suggestion-card" onClick={() => handleSuggestQuery(s, 'standard')}>
                    <span>{s}</span>
                    <span className="suggestion-card-icon"><Search size={11} /></span>
                  </button>
                ))}

                <div className="explore-label">Or try one of these</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  <button
                    className="mode-chip"
                    onClick={() => handleSuggestQuery('Deep research: build a complete investment thesis on RELIANCE.', 'deep')}
                    style={{ position: 'relative' }}
                  >
                    <Sparkles size={12} /> Full thesis
                    {!isPro && (
                      <span style={{ position: 'absolute', top: -6, right: -6, background: 'var(--gradient-brand)', color: '#0f172a', fontSize: 8, fontWeight: 800, padding: '1px 5px', borderRadius: 999 }}>
                        PRO
                      </span>
                    )}
                  </button>
                  <button
                    className="mode-chip"
                    onClick={() => handleSuggestQuery('Run a DCF valuation on my largest holding.', 'standard')}
                  >
                    DCF valuation
                  </button>
                  <button
                    className="mode-chip"
                    onClick={() => handleSuggestQuery('Compare TCS vs Infosys on margins, growth, and quality.', 'standard')}
                  >
                    Head-to-head
                  </button>
                </div>
              </>
            ) : (
              <>
                {messages.map((msg, i) => {
                  if (i === 0 && msg.sender === 'ai') return null;

                  if (msg.tokenLimitDetail) {
                    const detail = msg.tokenLimitDetail;
                    const isDeepPremium = detail.code === 'DEEP_PREMIUM_REQUIRED';
                    if (isDeepPremium && isPro) {
                      return null;
                    }
                    return (
                      <div key={i} className="glass-card token-limit-card animate-slide-in-up" style={{
                        padding: '20px',
                        margin: '12px 0',
                        borderRadius: '12px',
                        border: isDeepPremium ? '1px solid rgba(56, 189, 248, 0.25)' : '1px solid rgba(239, 68, 68, 0.25)',
                        background: isDeepPremium ? 'rgba(56, 189, 248, 0.05)' : 'rgba(239, 68, 68, 0.05)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '12px'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <div style={{
                            background: isDeepPremium ? 'rgba(56, 189, 248, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                            color: isDeepPremium ? '#38BDF8' : '#F87171',
                            width: '36px',
                            height: '36px',
                            borderRadius: '50%',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: '18px',
                            fontWeight: 'bold'
                          }}>{isDeepPremium ? '🔒' : '⚠️'}</div>
                          <div>
                            <h4 style={{ margin: 0, fontSize: '14px', fontWeight: 600, color: isDeepPremium ? '#38BDF8' : '#F87171' }}>
                              {isDeepPremium ? 'Deep Mode is Pro' : 'Research Limit Reached'}
                            </h4>
                            <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                              {isDeepPremium ? 'Free tier includes 1 deep run per week' : 'Weekly allocation exhausted'}
                            </span>
                          </div>
                        </div>

                        <p style={{ margin: 0, fontSize: '12px', lineHeight: '1.5', color: 'var(--text-secondary)' }}>
                          {detail.message || `You've consumed all allocated tokens for this period.`}
                        </p>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-muted)' }}>
                            <span>Weekly Progress</span>
                            <span>100% ({detail.usage?.toLocaleString() || detail.deep_runs_used?.toLocaleString() || '0'} / {detail.limit?.toLocaleString() || detail.deep_runs_limit?.toLocaleString() || '1'})</span>
                          </div>
                          <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.06)', borderRadius: '3px', overflow: 'hidden' }}>
                            <div style={{ width: '100%', height: '100%', background: isDeepPremium ? '#38BDF8' : '#EF4444', borderRadius: '3px' }}></div>
                          </div>
                        </div>

                        {detail.upgrade_available && !isPro && (
                          <button
                            onClick={() => navigate('/pricing')}
                            style={{
                              width: '100%',
                              padding: '10px',
                              borderRadius: 8,
                              border: 'none',
                              background: 'var(--gradient-brand)',
                              color: '#0f172a',
                              fontSize: 13,
                              fontWeight: 700,
                              cursor: 'pointer',
                            }}
                          >
                            Subscribe to Pro — Unlock Deep Mode
                          </button>
                        )}

                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '10px', marginTop: '4px' }}>
                          Restores on: <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{detail.restore_display || 'Next week'}</span>
                        </div>
                      </div>
                    );
                  }

                  return (
                    <div key={i} className="animate-slide-in-up">
                      <MessageBubble
                        sender={msg.sender}
                        text={msg.text}
                        richData={msg.richData}
                        depth={msg.depth}
                        elapsedMs={msg.elapsedMs}
                      />
                      {msg.sender === 'ai' && msg.depth === 'deep' && msg.wantsDocument && msg.sessionId && (
                        <ExportPanel sessionId={msg.sessionId} />
                      )}
                    </div>
                  );
                })}
              </>
            )}
          </div>

          {isThinking && (
            <div className="chat-live-pipeline-panel" aria-live="polite" aria-label="Arthik live pipeline">
              <AgentThinking events={thinkingEvents} isActive={isThinking} />
            </div>
          )}

          <div className="chat-rail-dock">
            <ChatInput
              onSend={handleSendMessage}
              onStop={handleStopGeneration}
              disabled={isThinking || isReadOnly}
              pendingDraft={isReadOnly ? null : pendingChatQuery}
              onPendingConsumed={() => setPendingChatQuery(null)}
            />
            <div className="chat-rail-footer">
              {isReadOnly
                ? 'Login to access Arthik AI — ask about any stock, sector, or portfolio'
                : isPro
                  ? 'Arthik • Pro • Unlimited Deep • Esc to stop'
                  : 'Arthik • Free • 1 Deep run/week • Esc to stop'}
            </div>
          </div>
          </div>
        </div>
      </div>

      {/* Mobile chat backdrop — tap to close */}
      {!isChatHidden && (
        <div
          className="chat-mobile-backdrop"
          onClick={() => {
            setIsChatHidden(true);
            setChatWidth(0);
            localStorage.setItem('prospektlab_chat_width', '0');
          }}
        />
      )}

      {/* Floating Chat Restore Button (when chat is snapped/hidden) */}
      {isChatHidden && (
        <button
          className="chat-restore-btn"
          onClick={() => {
            setIsChatHidden(false);
            const w = 380;
            setChatWidth(w);
            localStorage.setItem('prospektlab_chat_width', w.toString());
          }}
          title="Restore chat workspace"
        >
          <MessageSquare size={20} />
        </button>
      )}

      <AssetHistoryModal
        asset={assetHistoryTarget}
        onClose={() => setAssetHistoryTarget(null)}
      />
    </AppShell>
  );
};

export default DashboardPortfolioPage;

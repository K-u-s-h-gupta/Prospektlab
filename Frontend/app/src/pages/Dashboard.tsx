import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { AppShell } from '../components/layout/AppShell';
import { WatchlistCard, WatchlistStock } from '../components/dashboard/WatchlistCard';
import { InsightItem } from '../components/dashboard/RecentInsights';
import { PortfolioTable } from '../components/dashboard/PortfolioTable';
import { AssetHistoryModal, AssetHistoryTarget } from '../components/dashboard/AssetHistoryModal';
import { DonutChart } from '../components/charts/DonutChart';
import { IndexTickerCard, IndexTickerData } from '../components/dashboard/IndexTickerCard';
import { InteractiveChart } from '../components/charts/InteractiveChart';
import { ChatInput } from '../components/chat/ChatInput';
import { MessageBubble } from '../components/chat/MessageBubble';
import { AgentThinking } from '../components/chat/AgentThinking';
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
  getUserTokenUsage
} from '../api/client';
import { Search, Edit3, Sparkles, MessageSquare, ChevronRight, ChevronDown } from 'lucide-react';
import { INDIAN_STOCKS, POPULAR_MUTUAL_FUNDS } from '../data/indianStocks';

interface Message {
  sender: 'user' | 'ai';
  text: string;
  richData?: any;
  depth?: 'standard' | 'deep';
  elapsedMs?: number;
  tokenLimitDetail?: any;
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

const FAST_TAPE_NEWS_FALLBACKS = [
  {
    id: 'fallback-market-1',
    source: 'Market tape',
    time: 'Live fallback',
    headline: 'Nifty, Bank Nifty, IT and large-cap portfolio names are being checked against the latest available feed.',
    sentiment: 'neutral' as const,
    tickers: [] as string[],
  },
  {
    id: 'fallback-market-2',
    source: 'Market tape',
    time: 'Live fallback',
    headline: 'Corporate announcements and index breadth can materially change portfolio risk even when headline indices are flat.',
    sentiment: 'neutral' as const,
    tickers: [] as string[],
  },
  {
    id: 'fallback-market-3',
    source: 'Market tape',
    time: 'Live fallback',
    headline: 'Sector concentration, single-stock weight and liquidity are the first checks before interpreting intraday moves.',
    sentiment: 'neutral' as const,
    tickers: [] as string[],
  },
];

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

const readStoredPortfolioSnapshot = (): PortfolioItem[] => {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem('prospektlab_portfolio');
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch (_) {
    return [];
  }
};

const BENCHMARKS = [
  { id: 'NIFTY50', name: 'Nifty 50' },
  { id: 'SENSEX', name: 'SENSEX' },
  { id: 'NIFTYBANK', name: 'Nifty Bank' },
  { id: 'NIFTYIT', name: 'Nifty IT' },
  { id: 'MIDCAP150', name: 'Nifty Midcap 150' },
  { id: 'SMALLCAP250', name: 'Nifty Smallcap 250' },
  { id: 'NEXT50', name: 'Nifty Next 50' }
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

const toCanonicalSymbol = (rawSymbol: string) => {
  const clean = String(rawSymbol || '').split('.')[0].toUpperCase().trim();
  return SYMBOL_ALIASES[clean] || clean;
};

const CalendarSheet: React.FC<{ dateStr: string; dateLabel: string }> = ({ dateStr, dateLabel }) => {
  let month = "TBA";
  let day = "?";
  
  if (dateStr) {
    const d = new Date(dateStr);
    if (!isNaN(d.getTime())) {
      month = d.toLocaleString('en-US', { month: 'short' }).toUpperCase();
      day = d.getDate().toString();
    }
  } else if (dateLabel && dateLabel !== 'Awaiting Date') {
    const parts = dateLabel.split(' ');
    if (parts.length >= 2) {
      month = parts[0].substring(0, 3).toUpperCase();
      day = parts[1].replace(',', '');
    }
  }

  return (
    <div style={{
      width: '52px',
      height: '56px',
      background: 'rgba(15, 23, 42, 0.6)',
      border: '1px solid var(--border-subtle)',
      borderRadius: '8px',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
      flexShrink: 0
    }}>
      <div style={{
        width: '100%',
        background: dateStr ? 'linear-gradient(90deg, #ef4444, #dc2626)' : 'linear-gradient(90deg, #4b5563, #374151)',
        fontSize: '9px',
        fontWeight: 800,
        color: '#ffffff',
        textAlign: 'center',
        padding: '2px 0',
        letterSpacing: '0.05em'
      }}>
        {month}
      </div>
      <div style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: dateStr ? '18px' : '14px',
        fontWeight: 700,
        color: 'var(--text-primary)',
        lineHeight: 1
      }}>
        {day}
      </div>
    </div>
  );
};

export const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const { setOnboarded, user, showToast } = useAuth();
  const [portfolio, setPortfolio] = useState<PortfolioItem[]>(() => readStoredPortfolioSnapshot());
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
        cleanSym.startsWith('INF') || 
        targetSym === 'MOMF' ||
        sectorLower === 'mutual fund' || 
        sectorLower === 'mf' ||
        nameLower.includes('fund') || 
        nameLower.includes('mutual') ||
        POPULAR_MUTUAL_FUNDS.some(f => f.symbol.toUpperCase() === targetSym);

      if (isMF) {
        resolvedAssetClass = 'Mutual Fund';
        if (targetSym === 'MOMF') {
          resolvedName = 'Motilal Oswal Manufacturing Fund - Direct Growth';
          resolvedSector = 'Thematic - Manufacturing';
        } else {
          let mf = POPULAR_MUTUAL_FUNDS.find(
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
  const [isBypassEnabled, setIsBypassEnabled] = useState(
    () => typeof window !== 'undefined' && localStorage.getItem('prospektlab_bypass_token_limit') === 'true'
  );
  // Pre-filled chat query state (set by external dashboard buttons instead of auto-executing)
  const [pendingChatQuery, setPendingChatQuery] = useState<{ id: string; text: string; depth: 'standard' | 'deep' } | null>(null);
  const [isChatHighlighted, setIsChatHighlighted] = useState(false);
  const [assetHistoryTarget, setAssetHistoryTarget] = useState<AssetHistoryTarget | null>(null);

  const toggleBypassLimit = (val: boolean) => {
    localStorage.setItem('prospektlab_bypass_token_limit', val ? 'true' : 'false');
    setIsBypassEnabled(val);
    showToast(val ? 'Developer Sandbox Bypass Enabled' : 'Sandbox Bypass Disabled', 'info');
  };
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
  const [analyticsTab, setAnalyticsTab] = useState<'mf' | 'risk' | 'stress'>('risk');
  // mfData removed as diagnostics now uses enriched portfolio metrics
  const [actionQueue, setActionQueue] = useState<any[]>([]);

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

  const userUniverseSymbols = useMemo(() => {
    const portfolioSymbols = enrichedPortfolio.map(p => p.symbol.toUpperCase());
    const watchlistSymbols = watchlist.map(w => w.toUpperCase());
    return Array.from(new Set([...portfolioSymbols, ...watchlistSymbols]));
  }, [enrichedPortfolio, watchlist]);

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

      const tickers = new Set<string>();
      userUniverseSymbols.forEach(sym => {
        if (txt.includes(sym.toLowerCase())) {
          tickers.add(sym);
        }
      });
      const holdingSymbol = item.related_holding?.symbol;
      if (holdingSymbol) tickers.add(normalizeMarketSymbol(holdingSymbol));

      return {
        id: item.id || `${sourcePrefix}-${idx}-${title.slice(0, 16)}`,
        source: item.source || item.source_host || 'News',
        time: item.age_label || item.published || item.published_at || 'Just now',
        headline: title,
        sentiment,
        tickers: Array.from(tickers),
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
        const marketPromise = getMarketNews("India market");
        const portfolioPromise = getPortfolioNews(8).catch((err) => {
          console.warn('Portfolio news refresh failed', err);
          return null;
        });
        const marketData = await marketPromise;
        if (cancelled) return;

        const marketItems = mapTapeNewsItems(marketData, 'm');
        if (marketItems.length > 0) {
          setNewsFeed(marketItems);
          localStorage.setItem(TAPE_NEWS_CACHE_KEY, JSON.stringify(marketItems));
        }

        const portfolioData = await portfolioPromise;
        if (cancelled) return;

        const portfolioItems = mapTapeNewsItems(portfolioData?.items || [], 'p');
        const deduped = [...portfolioItems, ...marketItems].filter((item, idx, arr) =>
          idx === arr.findIndex((candidate) => candidate.headline === item.headline)
        ).slice(0, 10);

        if (deduped.length > 0) {
          setNewsFeed(deduped);
          localStorage.setItem(TAPE_NEWS_CACHE_KEY, JSON.stringify(deduped));
          setNewsError(null);
        } else if (!cached.length) {
          setNewsFeed(FAST_TAPE_NEWS_FALLBACKS);
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
  }, [userUniverseSymbols]);

  // Fetch token usage on mount
  useEffect(() => {
    fetchTokenUsage();
  }, []);

  const recentInsights = useMemo<InsightItem[]>(() => {
    const list: InsightItem[] = [];
    userUniverseSymbols.forEach((sym, idx) => {
      const upperSym = sym.toUpperCase();
      const clean = upperSym.split('.')[0];
      const targetSym = toCanonicalSymbol(clean);
      const pItem = enrichedPortfolio.find(p => p.symbol.toUpperCase() === upperSym);
      const stockItem = INDIAN_STOCKS.find(s => s.symbol.toUpperCase() === targetSym);
      const resolvedName = pItem ? pItem.name : (stockItem ? stockItem.name : allStockData[upperSym]?.name || `${targetSym} Limited`);

      const types: Array<'valuation' | 'risk' | 'earnings'> = ['valuation', 'risk', 'earnings'];
      const chosenType = types[idx % types.length];
      let title = '';
      let summary = '';
      const meta = allStockData[upperSym];
      
      if (chosenType === 'valuation') {
        title = `Valuation Assessment — ${resolvedName}`;
        summary = ` metrics for ${resolvedName} (currently at ${meta?.price || '—'}) indicate sector-specific dynamics in ${meta?.sector || 'General'}. Long-term multipliers suggest stabilization.`;
      } else if (chosenType === 'risk') {
        title = `Beta & Volatility — ${resolvedName}`;
        summary = `Historical correlation data for ${resolvedName} (${meta?.sector || 'General'} sector) indicates a stable tracking coefficient relative to Nifty 50 benchmarks.`;
      } else {
        title = `Earnings Outlook — ${resolvedName}`;
        summary = `Consensus estimates for ${resolvedName} point to stable capital efficiency metrics. Margin structure remains in line with ${meta?.sector || 'General'} industry peers.`;
      }

      list.push({
        id: `ins-${idx}`,
        ticker: upperSym,
        name: resolvedName,
        type: chosenType,
        title,
        summary,
        timestamp: `${idx * 3 + 2} hours ago`
      });
    });

    if (list.length === 0) {
      return [
        {
          id: 'ins-1',
          ticker: 'RELIANCE',
          name: 'Reliance Industries Ltd',
          type: 'valuation',
          title: 'DCF Intrinsic Mismatch',
          summary: 'Arthik\'s WACC valuation models calculate an intrinsic value of ₹3,240. Represents a 10.5% margin of safety relative to market pricing.',
          timestamp: '1 hour ago'
        },
        {
          id: 'ins-2',
          ticker: 'ASIANPAINT',
          name: 'Asian Paints Limited',
          type: 'risk',
          title: 'Pledge Indicator Alert',
          summary: 'Promoter pledge ratio ticked up by 2.1% in the recent filings. Financial health rating remains at 8/9, but leverage warrants monitoring.',
          timestamp: '3 hours ago'
        }
      ];
    }

    return list;
  }, [userUniverseSymbols, enrichedPortfolio, allStockData]);

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
      try {
        const res = await getPortfolioMirror();
        const mirrorPositions = Array.isArray(res?.positions) ? res.positions : [];
        if (mirrorPositions.length > 0) {
          const mapped = mirrorPositions.map((p: any) => {
            const qty = p.quantity || 0;
            const marketVal = p.market_value || 0;
            let currentPrice = p.last_price || 0;
            if (currentPrice === 0 && qty > 0 && marketVal > 0) {
              currentPrice = marketVal / qty;
            }
            if (currentPrice === 0) {
              currentPrice = p.avg_cost || (qty > 0 ? (p.cost_basis || 0) / qty : 0);
            }
            
            let avgCost = p.avg_cost || 0;
            if (avgCost === 0 && currentPrice > 0) {
              avgCost = currentPrice;
            }
            
            const cleanSym = p.symbol.split('.')[0].toUpperCase().trim();
            const targetSym = toCanonicalSymbol(cleanSym);
            let resolvedName = p.name;
            let resolvedSector = p.sector;
            
            if (targetSym === 'MOMF') {
              resolvedName = 'Motilal Oswal Manufacturing Fund - Direct Growth';
              resolvedSector = 'Thematic - Manufacturing';
            } else {
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
            }

            return {
              symbol: targetSym,
              name: resolvedName,
              qty: qty,
              avgCost: avgCost,
              current: currentPrice,
              sector: resolvedSector || p.sector || 'General'
            };
          });
          setPortfolio(mapped);
          localStorage.setItem('prospektlab_portfolio', JSON.stringify(mapped));
          setPortfolioMirrorVersion((version) => version + 1);
          return;
        }

        localStorage.removeItem('prospektlab_portfolio');
        setPortfolio([]);
        setOnboarded(false);
        navigate('/onboarding', { replace: true });
      } catch (e) {
        console.error('Failed to sync portfolio from mirror', e);
        const savedPortfolioRaw = localStorage.getItem('prospektlab_portfolio');
        try {
          const savedPortfolio = savedPortfolioRaw ? JSON.parse(savedPortfolioRaw) : [];
          if (Array.isArray(savedPortfolio) && savedPortfolio.length > 0) {
            setPortfolio(savedPortfolio);
            setPortfolioMirrorVersion((version) => version + 1);
            return;
          }
        } catch (storageErr) {
          console.error('Failed to recover local portfolio snapshot', storageErr);
        }
        setOnboarded(false);
        navigate('/onboarding', { replace: true });
      }
    };
    syncPortfolio();

    // Load watchlist symbols
    const savedWatchlistRaw = localStorage.getItem('prospektlab_watchlist');
    const savedWatchlist: string[] = savedWatchlistRaw ? JSON.parse(savedWatchlistRaw) : ['RELIANCE', 'TCS', 'INFY'];
    const normalizedWatchlist = savedWatchlist
      .map((s) => String(s || '').split('.')[0].toUpperCase().trim())
      .filter((s) => s.length > 0);
    const dedupedWatchlist = Array.from(new Set(normalizedWatchlist));
    setWatchlist(dedupedWatchlist);

    // Load past conversations
    let savedConversations = [];
    try {
      const savedConversationsRaw = localStorage.getItem('prospektlab_conversations');
      savedConversations = savedConversationsRaw ? JSON.parse(savedConversationsRaw) : [];
    } catch (e) {
      console.error(e);
    }
    setConversations(savedConversations);

    // Pick active conversation
    if (savedConversations.length > 0) {
      let firstConv = savedConversations[0];
      if (firstConv.id === '1') {
        const migratedId = 'conv-' + Date.now();
        firstConv.id = migratedId;
        const savedMessagesRaw = localStorage.getItem('prospektlab_messages_1');
        if (savedMessagesRaw) {
          localStorage.setItem(`prospektlab_messages_${migratedId}`, savedMessagesRaw);
          localStorage.removeItem('prospektlab_messages_1');
        }
        localStorage.setItem('prospektlab_conversations', JSON.stringify(savedConversations));
        setConversations([...savedConversations]);
      }
      setActiveConversationId(firstConv.id);
      const savedMessagesRaw = localStorage.getItem(`prospektlab_messages_${firstConv.id}`);
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
      const newId = 'conv-' + Date.now();
      const newConv = { id: newId, title: 'Equity Analysis Session', date: 'Today' };
      const updatedConvs = [newConv];
      setConversations(updatedConvs);
      localStorage.setItem('prospektlab_conversations', JSON.stringify(updatedConvs));
      setActiveConversationId(newId);
      bootstrapWelcomeMessage(newId);
    }

    // Fetch extra analytics
    fetchBackendAnalytics();
  }, [navigate, setOnboarded]);

  const fetchBackendAnalytics = async () => {
    try {
      const mf = await getMfAnalytics();
      setMfAnalytics(mf);
      const queue = await getTodayQueue();
      setActionQueue(queue.items || []);
    } catch (e) {
      console.log('Backend analytics not fully synchronized yet', e);
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
    localStorage.setItem(`prospektlab_messages_${convId}`, JSON.stringify(welcomeMsgs));
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
    const oneDayVol = annualVolPct > 0 ? annualVolPct / 100 / Math.sqrt(252) : 0.0165;
    const var95 = totalVal * oneDayVol * 1.65 * (beta > 0 ? beta : 1);

    return { best, worst, winners, losers, topSector, topSectorPct, beta, hhi, var95 };
  })();

  // Tracked universe movers — resolve live change_pct by normalizing symbol format
  // quotesData may be keyed as "RELIANCE.NS" but portfolio symbols may be "RELIANCE"
  const lookupQuote = (sym: string) => {
    return lookupLiveQuote(sym);
  };

  const allTrackedStocks = [
    ...computedPortfolioDetails,
    ...watchlist
      .filter(sym => {
        const wBase = normalizeMarketSymbol(sym);
        return !computedPortfolioDetails.find(p => normalizeMarketSymbol(p.symbol) === wBase);
      })
      .map(sym => {
        const base = normalizeMarketSymbol(sym);
        const info = allStockData[sym] || allStockData[base] || allStockData[base + '.NS'];
        return ({
        symbol: sym,
        name: info?.name || `${base} Limited`,
        qty: 0,
        avgCost: 0,
        current: info?.price ? parseFloat(info.price.replace(/,/g, '')) || 0 : 0,
        sector: 'Watchlist',
        dayChangePct: info?.changePct || 0,
      } as PortfolioItem);
      })
  ];

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

  const upcomingEarnings = useMemo(() => {
    const VERIFIED_BSE_NSE_EARNINGS: Record<string, { date: string; dateLabel: string; period: string; catalyst: string; impact: 'high' | 'medium' | 'watch'; when: string }> = {
      'INFY': { date: '2026-07-16', dateLabel: 'July 16, 2026', period: 'Q1 FY27', catalyst: 'IT bellwether — sets sector tone', impact: 'high', when: 'After Market Hours' },
      'RELIANCE': { date: '2026-07-24', dateLabel: 'July 24, 2026', period: 'Q1 FY27', catalyst: 'Jio + Retail demerger update', impact: 'high', when: 'After Market Hours' },
      'HDFCBANK': { date: '2026-07-18', dateLabel: 'July 18, 2026', period: 'Q1 FY27', catalyst: 'NIM trajectory post-merger', impact: 'high', when: 'Post Board Meeting' },
      'TATAMOTORS': { date: '2026-07-31', dateLabel: 'July 31, 2026', period: 'Q1 FY27', catalyst: 'JLR margins + EV order book', impact: 'medium', when: 'After Market Hours' },
      'TCS': { date: '2026-07-09', dateLabel: 'July 9, 2026', period: 'Q1 FY27', catalyst: 'First IT major to report — deal wins key', impact: 'high', when: 'After Market Hours' },
      'ASIANPAINT': { date: '2026-07-23', dateLabel: 'July 23, 2026', period: 'Q1 FY27', catalyst: 'Volume recovery + crude impact', impact: 'medium', when: 'After Market Hours' },
      'ZOMATO': { date: '2026-07-28', dateLabel: 'July 28, 2026', period: 'Q1 FY27', catalyst: 'Blinkit profitability path', impact: 'high', when: 'After Market Hours' },
      'ITC': { date: '2026-07-30', dateLabel: 'July 30, 2026', period: 'Q1 FY27', catalyst: 'FMCG margin expansion', impact: 'medium', when: 'After Market Hours' },
      'LTIM': { date: '2026-07-15', dateLabel: 'July 15, 2026', period: 'Q1 FY27', catalyst: 'Mid-tier IT demand signal', impact: 'medium', when: 'After Market Hours' },
      'PWL': { date: '', dateLabel: 'Awaiting Date', period: 'Q1 FY27', catalyst: 'First full-year audited results post-IPO', impact: 'high', when: '' },
      'PHYSICSWALLAH': { date: '', dateLabel: 'Awaiting Date', period: 'Q1 FY27', catalyst: 'First full-year audited results post-IPO', impact: 'high', when: '' }
    };
 
    const mfSymbols = new Set(
      enrichedPortfolio
        .filter(p => p.assetClass === 'Mutual Fund')
        .map(p => p.symbol.toUpperCase())
    );
 
    const equityUniverseSymbols = userUniverseSymbols.filter(sym => {
      const clean = sym.split('.')[0].toUpperCase().trim();
      const isMF = 
        clean.startsWith('INF') || 
        mfSymbols.has(sym) || 
        POPULAR_MUTUAL_FUNDS.some(f => f.symbol.toUpperCase() === clean);
      return !isMF;
    });
 
    const list: Array<{ date: string; dateLabel: string; ticker: string; name: string; period: string; catalyst: string; impact: 'high' | 'medium' | 'watch'; when: string }> = [];
 
    equityUniverseSymbols.forEach((sym) => {
      const upperSym = sym.toUpperCase();
      const clean = upperSym.split('.')[0];
      const targetSym = toCanonicalSymbol(clean);
      const verified = VERIFIED_BSE_NSE_EARNINGS[targetSym] || VERIFIED_BSE_NSE_EARNINGS[clean];
 
      if (verified) {
        let isPast = false;
        if (verified.date) {
          const verifiedDate = new Date(verified.date);
          const todayDate = new Date('2026-05-27');
          isPast = verifiedDate < todayDate;
        }
 
        if (!isPast) {
          const pItem = enrichedPortfolio.find(p => p.symbol.toUpperCase() === upperSym);
          const stockItem = INDIAN_STOCKS.find(s => s.symbol.toUpperCase() === targetSym);
          const resolvedName = pItem ? pItem.name : (stockItem ? stockItem.name : allStockData[upperSym]?.name || `${targetSym} Limited`);
          
          list.push({
            date: verified.date,
            dateLabel: verified.dateLabel,
            ticker: upperSym,
            name: resolvedName,
            period: verified.period,
            catalyst: verified.catalyst,
            impact: verified.impact,
            when: verified.when
          });
        }
      }
    });

    return list;
  }, [userUniverseSymbols, enrichedPortfolio]);

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
    if (!message.trim() || isThinking || !activeConversationId) return;

    // 1. Append User Bubble
    const userMsg: Message = { sender: 'user', text: message, depth };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    localStorage.setItem(`prospektlab_messages_${activeConversationId}`, JSON.stringify(updatedMessages));

    // Update conversation title if needed
    const activeConv = conversations.find(c => c.id === activeConversationId);
    if (activeConv && (activeConv.title === 'Equity Analysis Session' || activeConv.title.startsWith('Analyze ') || activeConv.title.startsWith('Portfolio '))) {
      const cleanTitle = message.length > 28 ? message.substring(0, 28) + '...' : message;
      const updatedConvs = conversations.map(c => c.id === activeConversationId ? { ...c, title: cleanTitle } : c);
      setConversations(updatedConvs);
      localStorage.setItem('prospektlab_conversations', JSON.stringify(updatedConvs));
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
            localStorage.setItem(`prospektlab_messages_${activeConversationId}`, JSON.stringify(next));
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
          c.id === activeConversationId ? { ...c, backendSessionId } : c
        );
        setConversations(updatedConvs);
        localStorage.setItem('prospektlab_conversations', JSON.stringify(updatedConvs));
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
              elapsedMs: elapsed
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
              elapsedMs: elapsed
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
            localStorage.setItem(`prospektlab_messages_${activeConversationId}`, JSON.stringify(next));
          } catch (storageErr) {
            console.warn('[DASHBOARD] localStorage persist failed', storageErr);
          }
          return next;
        });
        return;
      }
      
      if (err.detail?.code === 'WEEKLY_TOKEN_LIMIT_EXCEEDED') {
        const limitResponse: Message = {
          sender: 'ai',
          text: `Weekly Token Limit Exceeded`,
          tokenLimitDetail: err.detail
        };
        setMessages((prev) => {
          const next = [...prev, limitResponse];
          try {
            localStorage.setItem(`prospektlab_messages_${activeConversationId}`, JSON.stringify(next));
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
              localStorage.setItem(`prospektlab_messages_${activeConversationId}`, JSON.stringify(next));
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
          localStorage.setItem(`prospektlab_messages_${activeConversationId}`, JSON.stringify(merged));
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
      localStorage.setItem(`prospektlab_messages_${activeConversationId}`, JSON.stringify(updated));
      return updated;
    });
  };

  const handleSelectConversation = (id: string) => {
    if (isThinking) return;
    setActiveConversationId(id);
    const savedMessagesRaw = localStorage.getItem(`prospektlab_messages_${id}`);
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
    if (isThinking) return;
    const newId = 'conv-' + Date.now();
    const newConv = { id: newId, title: 'Equity Analysis Session', date: 'Today' };
    const updatedConvs = [newConv, ...conversations];
    setConversations(updatedConvs);
    localStorage.setItem('prospektlab_conversations', JSON.stringify(updatedConvs));
    
    setActiveConversationId(newId);
    bootstrapWelcomeMessage(newId);
  };

  const handleDeleteConversation = (id: string) => {
    if (isThinking && activeConversationId === id) return;
    const updated = conversations.filter(c => c.id !== id);
    setConversations(updated);
    localStorage.setItem('prospektlab_conversations', JSON.stringify(updated));
    localStorage.removeItem(`prospektlab_messages_${id}`);

    if (activeConversationId === id) {
      if (updated.length > 0) {
        handleSelectConversation(updated[0].id);
      } else {
        handleNewConversation();
      }
    }
  };

  const handleClearHistory = () => {
    if (isThinking) return;
    conversations.forEach(c => {
      localStorage.removeItem(`prospektlab_messages_${c.id}`);
    });
    
    const newId = 'conv-' + Date.now();
    const newConv = { id: newId, title: 'Equity Analysis Session', date: 'Today' };
    setConversations([newConv]);
    localStorage.setItem('prospektlab_conversations', JSON.stringify([newConv]));
    
    setActiveConversationId(newId);
    bootstrapWelcomeMessage(newId);
  };

  /** Pre-fills the chat input with a query (shows query for user review instead of auto-executing) */
  const handleSuggestQuery = (query: string, depth: 'standard' | 'deep' = 'standard') => {
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
    localStorage.setItem('prospektlab_watchlist', JSON.stringify(updated));
  };

  const handleRemoveStock = (symbol: string) => {
    const normalized = normalizeMarketSymbol(symbol);
    const updated = watchlist.filter(s => normalizeMarketSymbol(s) !== normalized);
    setWatchlist(updated);
    localStorage.setItem('prospektlab_watchlist', JSON.stringify(updated));
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
      const [marketData, portfolioData] = await Promise.allSettled([
        getMarketNews('India market'),
        getPortfolioNews(8),
      ]);
      const mapped = [
        ...(portfolioData.status === 'fulfilled' ? mapTapeNewsItems(portfolioData.value?.items || [], 'retry-p') : []),
        ...(marketData.status === 'fulfilled' ? mapTapeNewsItems(marketData.value, 'retry-m') : []),
      ].filter((item, idx, arr) => idx === arr.findIndex((candidate) => candidate.headline === item.headline)).slice(0, 10);
      if (mapped.length > 0) {
        setNewsFeed(mapped);
        localStorage.setItem(TAPE_NEWS_CACHE_KEY, JSON.stringify(mapped));
      } else {
        setNewsFeed(FAST_TAPE_NEWS_FALLBACKS);
      }
    } catch (e: any) {
      console.error('Failed to fetch market news', e);
      setNewsError(e.message || 'Failed to load market news');
    } finally {
      setNewsLoading(false);
    }
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

  const activeIndices = liveIndexData.india;

  const marketSummary = {
    headline: 'Indian markets open red as global cues weigh on sentiment',
    body: 'The Nifty 50 and SENSEX opened in the red before staging a marginal recovery to trade flat in early hours. Market sentiment is dampened by overnight weakness in US tech and a stronger dollar. Energy and Banking are the worst performers; IT held flat on a strong TCS print.',
    sourcesCount: 4,
  };

  const insightTypeBadgeClass = (type: string) =>
    type === 'valuation' ? 'insight-row-type-valuation' :
    type === 'risk' ? 'insight-row-type-risk' :
    'insight-row-type-earnings';

  const getCountdownLabel = (dateStr: string) => {
    if (!dateStr) return 'Awaiting Date';
    const target = new Date(dateStr);
    const today = new Date('2026-05-27');
    
    target.setHours(0, 0, 0, 0);
    today.setHours(0, 0, 0, 0);
    
    const diffTime = target.getTime() - today.getTime();
    const diffDays = Math.round(diffTime / (1000 * 60 * 60 * 24));
    
    if (diffDays === 0) return '● Today';
    if (diffDays === 1) return 'tomorrow';
    if (diffDays > 1) return `in ${diffDays} days`;
    return '';
  };

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
      title="Dashboard"
      portfolioSummary={hasPortfolioHoldings ? {
        totalValue: sidebarTotalValue,
        totalPnL: sidebarTotalPnL,
        totalReturnPct: sidebarTotalReturnPct
      } : undefined}
      conversations={conversations}
      onDeleteConversation={handleDeleteConversation}
      onClearHistory={handleClearHistory}
      onNewConversation={handleNewConversation}
      onSelectConversation={handleSelectConversation}
      activeConversationId={activeConversationId}
      tokenUsage={tokenUsage}
    >
      <div className={`workbench ${isChatHidden ? 'chat-closed' : 'chat-open'}`} style={
        (typeof window !== 'undefined' && window.innerWidth > 768) ? {
          gridTemplateColumns: `minmax(0, 1fr) ${isChatHidden ? '0px' : `${chatWidth}px`}`,
          transition: isDraggingChat ? 'none' : undefined
        } : undefined
      }>
        {/* ════════════════════════ LEFT: DATA DASHBOARD ════════════════════════ */}
        <div className="workbench-data">
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

          {/* Arthik's read on your book stats */}
          {portfolioStats && (
            <>
              <div className="section-head">
                <div className="section-title">Arthik's read on your book</div>
                <span className="section-sublabel">PERSONAL • {portfolio.length} POSITIONS</span>
              </div>
              <div className="stats-grid">
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
                  <div className="analytics-tabs-row" style={{ gap: 16 }}>
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
                      onClick={() => setAnalyticsTab('stress')}
                      style={{
                        background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                        color: analyticsTab === 'stress' ? 'var(--text-primary)' : 'var(--text-secondary)',
                        fontWeight: 600, fontSize: 13,
                      }}
                    >
                      Shock & Stress Simulator
                    </button>
                  </div>
                </div>

              <div style={{ marginTop: '14px' }}>
                {analyticsTab === 'risk' && portfolioStats && (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '14px', fontSize: '12px' }}>
                    <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px' }}>
                      <div style={{ color: 'var(--text-secondary)', fontWeight: 600, marginBottom: '6px' }}>Herfindahl-Hirschman Index (HHI)</div>
                      <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>{portfolioStats.hhi.toFixed(0)}</div>
                      <div style={{ color: portfolioStats.hhi > 2500 ? 'var(--loss)' : 'var(--profit)', marginTop: '4px', fontSize: '11px' }}>
                        {portfolioStats.hhi > 2500 ? 'Highly Concentrated' : 'Well Diversified'}
                      </div>
                    </div>
                    
                    <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px' }}>
                      <div style={{ color: 'var(--text-secondary)', fontWeight: 600, marginBottom: '6px' }}>Active Risk Score</div>
                      <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>{(portfolioStats.beta * 45).toFixed(0)} / 100</div>
                      <div style={{ color: 'var(--text-muted)', marginTop: '4px', fontSize: '11px' }}>Systematic volatile beta rating</div>
                    </div>

                    <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px' }}>
                      <div style={{ color: 'var(--text-secondary)', fontWeight: 600, marginBottom: '6px' }}>Action Queue Items</div>
                      <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>{actionQueue.length} Alerts</div>
                      <div style={{ color: 'var(--accent-cyan)', marginTop: '4px', fontSize: '11px', cursor: 'pointer' }}
                        onClick={() => handleSuggestQuery('Check my portfolio action items.', 'standard')}
                      >
                        Inspect Queue →
                      </div>
                    </div>
                  </div>
                )}

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

                                  <hr style={{ border: 'none', borderBottom: '1px solid rgba(255, 255, 255, 0.05)', margin: 0 }} />

                                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '10px' }}>
                                    <div style={{ background: 'rgba(255, 255, 255, 0.02)', border: '1px solid rgba(255, 255, 255, 0.05)', borderRadius: '6px', padding: '8px' }}>
                                      <div style={{ fontSize: '10px', color: 'var(--text-secondary)', fontWeight: 600 }}>SCHEME TER</div>
                                      <div style={{ fontSize: '12px', color: 'var(--text-primary)', marginTop: 4 }}>Not synced</div>
                                    </div>
                                    <div style={{ background: 'rgba(255, 255, 255, 0.02)', border: '1px solid rgba(255, 255, 255, 0.05)', borderRadius: '6px', padding: '8px' }}>
                                      <div style={{ fontSize: '10px', color: 'var(--text-secondary)', fontWeight: 600 }}>EXIT LOAD</div>
                                      <div style={{ fontSize: '12px', color: 'var(--text-primary)', marginTop: 4 }}>Not synced</div>
                                    </div>
                                  </div>

                                  <div style={{ 
                                    background: 'rgba(56, 189, 248, 0.05)', 
                                    border: '1px solid rgba(56, 189, 248, 0.14)', 
                                    borderRadius: '6px', 
                                    padding: '8px 10px',
                                    fontSize: '11px',
                                    color: 'var(--text-secondary)'
                                  }}>
                                    Scheme-level TER, exit load, and look-through holdings need verified AMFI/AMC data before display.
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

                {analyticsTab === 'stress' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                    <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Simulate shocks on your portfolio holdings NAV:</div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '10px' }}>
                      <button
                        onClick={() => handleSuggestQuery('Simulate Nifty down 10% on my portfolio.', 'standard')}
                        style={{ padding: '8px', fontSize: '11px', background: 'rgba(251, 113, 133, 0.05)', borderColor: 'var(--loss)' }}
                      >
                        Nifty -10% Crash
                      </button>
                      <button
                        onClick={() => handleSuggestQuery('Simulate Nifty down 20% on my portfolio.', 'standard')}
                        style={{ padding: '8px', fontSize: '11px', background: 'rgba(251, 113, 133, 0.08)', borderColor: 'var(--loss)' }}
                      >
                        Nifty -20% Crash
                      </button>
                      <button
                        onClick={() => handleSuggestQuery('Simulate the 2020 COVID crash scenarios on my book.', 'standard')}
                        style={{ padding: '8px', fontSize: '11px', background: 'rgba(129, 140, 248, 0.05)', borderColor: 'var(--accent-indigo)' }}
                      >
                        2020 COVID Crash
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Top Movers */}
          <div className="section-head">
            <div className="section-title">Top movers in your universe</div>
            <span className="section-sublabel">PORTFOLIO + WATCHLIST</span>
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
          <div className="data-grid">
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

              {activeTab === 'portfolio' ? (
                enrichedPortfolio.length > 0 ? (
                  <PortfolioTable portfolio={enrichedPortfolio} onSelectStock={handleSelectStock} onAnalyzeStock={handleAnalyzeStock} />
                ) : (
                  <div style={{ padding: 32, textAlign: 'center', fontSize: 13, color: 'var(--text-secondary)' }}>
                    No holdings yet.{' '}
                    <button
                      onClick={() => navigate('/onboarding')}
                      style={{ color: 'var(--accent-cyan)', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 600 }}
                    >
                      Import portfolio →
                    </button>
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

            <div className="data-panel">
              <div className="data-panel-head">
                <div className="data-panel-title">Live insights</div>
                <span className="section-sublabel" style={{ fontSize: 9.5 }}>{recentInsights.length} new</span>
              </div>
              <div>
                {recentInsights.map(ins => (
                  <div
                    key={ins.id}
                    className="insight-row"
                    onClick={() => handleSuggestQuery(`Walk me through the ${ins.title} for ${ins.ticker}.`, 'standard')}
                  >
                    <div className="insight-row-meta" style={{ flexWrap: 'wrap', rowGap: '4px' }}>
                      <span>{ins.ticker}</span>
                      <span className={`insight-row-type ${insightTypeBadgeClass(ins.type)}`}>{ins.type}</span>
                      <span style={{ marginLeft: 'auto', fontWeight: 500, textTransform: 'none', letterSpacing: 0, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{ins.timestamp}</span>
                    </div>
                    <div className="insight-row-title">{ins.title}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* News Feed */}
          <div className="section-head" style={{ marginTop: 24 }}>
            <div className="section-title">What's moving the tape</div>
            <span className="section-sublabel">LIVE NEWS · ARTHIK'S SENTIMENT</span>
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
          </div>

          {/* Upcoming Earnings */}
          <div className="section-head" style={{ marginTop: 24 }}>
            <div className="section-title">Upcoming earnings</div>
            <span className="section-sublabel">YOUR UNIVERSE · EARNINGS CALENDAR</span>
          </div>
          <div className="earnings-list">
            {upcomingEarnings.map(e => {
              const isOwned = enrichedPortfolio.some(p => p.symbol === e.ticker);
              const impactColor = e.impact === 'high' ? 'var(--accent-cyan)' : e.impact === 'medium' ? 'var(--text-secondary)' : 'var(--text-muted)';
              const impactBg = e.impact === 'high' ? 'rgba(56, 189, 248, 0.12)' : e.impact === 'medium' ? 'rgba(148, 163, 184, 0.1)' : 'rgba(100, 116, 139, 0.08)';
              const impactLabel = e.impact === 'high' ? '🔥 High Impact' : e.impact === 'medium' ? '📊 Notable' : '👀 Watch';
              
              const countdown = getCountdownLabel(e.date);
              
              return (
                <div key={e.ticker} className="earnings-row" style={{ gap: '16px', padding: '12px 16px' }} onClick={() => handleSuggestQuery(`What should I expect from ${e.name}'s upcoming ${e.period} earnings?`, 'standard')}>
                  {/* Calendar Sheet Card on Left */}
                  <CalendarSheet dateStr={e.date} dateLabel={e.dateLabel} />
                  
                  {/* Info in Middle */}
                  <div className="earnings-info" style={{ flex: 1, minWidth: 0 }}>
                    <div className="earnings-name" style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13.5px', fontWeight: 600, overflowWrap: 'break-word', wordBreak: 'break-word' }}>
                      {e.name}
                      {isOwned && <span className="owned-badge">OWNED</span>}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: 4 }}>
                      {e.period} {e.when ? `· ${e.when}` : ''}
                    </div>
                    {/* Countdown and Date text */}
                    <div className="earnings-meta" style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: 4, fontSize: '11px' }}>
                      <span style={{ 
                        color: e.date ? 'var(--accent-cyan)' : 'var(--text-muted)', 
                        fontWeight: 600,
                        textTransform: 'uppercase',
                        fontSize: '10px'
                      }}>
                        {countdown}
                      </span>
                      {e.date && (
                        <>
                          <span style={{ color: 'var(--text-muted)' }}>•</span>
                          <span style={{ color: 'var(--text-muted)' }}>{e.dateLabel}</span>
                        </>
                      )}
                    </div>
                    {/* Consensus estimates disclaimer */}
                    <div style={{ fontSize: '10.5px', color: 'var(--loss)', marginTop: 4, fontStyle: 'italic' }}>
                      Consensus Estimate: <span style={{ fontWeight: 600 }}>not disclosed by those</span>
                    </div>
                  </div>
                  
                  {/* Catalyst and Impact on Right */}
                  <div className="earnings-catalyst" style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
                    <span className="earnings-impact-pill" style={{ 
                      fontSize: '9.5px', fontWeight: 700, color: impactColor, 
                      background: impactBg, padding: '3px 8px', borderRadius: '6px',
                      letterSpacing: '0.02em', whiteSpace: 'nowrap'
                    }}>{impactLabel}</span>
                    <span className="earnings-catalyst-text">
                      {e.catalyst}
                    </span>
                  </div>
                </div>
              );
            })}
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
               <button className="chat-rail-iconbtn" title="New session" onClick={handleNewConversation}>
                 <Edit3 size={16} color="#38BDF8" style={{ minWidth: 16, minHeight: 16, display: 'block' }} />
               </button>
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
                  >
                    <Sparkles size={12} /> Full thesis
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
                    return (
                      <div key={i} className="glass-card token-limit-card animate-slide-in-up" style={{
                        padding: '20px',
                        margin: '12px 0',
                        borderRadius: '12px',
                        border: '1px solid rgba(239, 68, 68, 0.25)',
                        background: 'rgba(239, 68, 68, 0.05)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '12px'
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <div style={{
                            background: 'rgba(239, 68, 68, 0.15)',
                            color: '#F87171',
                            width: '36px',
                            height: '36px',
                            borderRadius: '50%',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: '18px',
                            fontWeight: 'bold'
                          }}>⚠️</div>
                          <div>
                            <h4 style={{ margin: 0, fontSize: '14px', fontWeight: 600, color: '#F87171' }}>Research Limit Reached</h4>
                            <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>Weekly allocation exhausted</span>
                          </div>
                        </div>
                        
                        <p style={{ margin: 0, fontSize: '12px', lineHeight: '1.5', color: 'var(--text-secondary)' }}>
                          {detail.message || `You've consumed all 5,000,000 allocated tokens for this period.`}
                        </p>
                        
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-muted)' }}>
                            <span>Weekly Progress</span>
                            <span>100% ({detail.usage?.toLocaleString() || '5,000,000'} / {detail.limit?.toLocaleString() || '5,000,000'})</span>
                          </div>
                          <div style={{ width: '100%', height: '6px', background: 'rgba(255,255,255,0.06)', borderRadius: '3px', overflow: 'hidden' }}>
                            <div style={{ width: '100%', height: '100%', background: '#EF4444', borderRadius: '3px' }}></div>
                          </div>
                        </div>

                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '10px', marginTop: '4px' }}>
                          Restores on: <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{detail.restore_display || 'Next week'}</span>
                        </div>

                        <label style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          marginTop: '6px',
                          fontSize: '12px',
                          cursor: 'pointer',
                          padding: '8px 12px',
                          borderRadius: '8px',
                          background: 'rgba(255, 255, 255, 0.03)',
                          border: '1px solid rgba(255, 255, 255, 0.05)'
                        }}>
                          <input
                            type="checkbox"
                            checked={isBypassEnabled}
                            onChange={(e) => toggleBypassLimit(e.target.checked)}
                            style={{ cursor: 'pointer' }}
                          />
                          <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>Bypass Limit (Developer Sandbox)</span>
                        </label>
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
              disabled={isThinking}
              pendingDraft={pendingChatQuery}
              onPendingConsumed={() => setPendingChatQuery(null)}
            />
            <div className="chat-rail-footer">
              Arthik • every NSE name • Standard / Deep • Esc to stop
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

export default Dashboard;

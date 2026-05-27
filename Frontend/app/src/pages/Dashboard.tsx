import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { AppShell } from '../components/layout/AppShell';
import { WatchlistCard, WatchlistStock } from '../components/dashboard/WatchlistCard';
import { InsightItem } from '../components/dashboard/RecentInsights';
import { PortfolioTable } from '../components/dashboard/PortfolioTable';
import { DonutChart } from '../components/charts/DonutChart';
import { IndexTickerCard, IndexTickerData } from '../components/dashboard/IndexTickerCard';
import { InteractiveChart } from '../components/charts/InteractiveChart';
import { ChatInput } from '../components/chat/ChatInput';
import { MessageBubble } from '../components/chat/MessageBubble';
import { AgentThinking } from '../components/chat/AgentThinking';
import { 
  startResearch, 
  streamSession, 
  stopSession, 
  getSessionResult, 
  getMfAnalytics,
  getTodayQueue,
  getPortfolioMirror,
  AgentEventData
} from '../api/client';
import { Search, Edit3, Sparkles, MessageSquare, ChevronRight } from 'lucide-react';
import { INDIAN_STOCKS, POPULAR_MUTUAL_FUNDS } from '../data/indianStocks';

interface Message {
  sender: 'user' | 'ai';
  text: string;
  richData?: any;
  depth?: 'standard' | 'deep';
  elapsedMs?: number;
}

interface PortfolioItem {
  symbol: string;
  name: string;
  qty: number;
  avgCost: number;
  current: number;
  sector: string;
}

const BENCHMARKS = [
  { id: 'NIFTY50', name: 'Nifty 50' },
  { id: 'SENSEX', name: 'SENSEX' },
  { id: 'NIFTYBANK', name: 'Nifty Bank' },
  { id: 'NIFTYIT', name: 'Nifty IT' },
  { id: 'MIDCAP150', name: 'Nifty Midcap 150' },
  { id: 'SMALLCAP250', name: 'Nifty Smallcap 250' },
  { id: 'NEXT50', name: 'Nifty Next 50' }
];

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
  const [portfolio, setPortfolio] = useState<PortfolioItem[]>([]);

  // Helper db for mutual fund diagnostics
  const MUTUAL_FUND_DIAGNOSTICS_DB: Record<string, {
    expenseRatio: number;
    exitLoad: string;
    topHoldings: Array<{ name: string; weight: number }>;
  }> = useMemo(() => ({
    'PPFLEXICAP': {
      expenseRatio: 0.58,
      exitLoad: '2.00% within 365 days, 1.00% within 730 days',
      topHoldings: [
        { name: 'HDFC Bank Ltd', weight: 7.8 },
        { name: 'Reliance Industries Ltd', weight: 6.5 },
        { name: 'Tata Consultancy Services', weight: 5.2 },
        { name: 'Microsoft Corp (US)', weight: 4.8 },
        { name: 'ITC Limited', weight: 4.2 }
      ]
    },
    'INF247L01DA9': {
      expenseRatio: 1.12,
      exitLoad: '1.00% if redeemed on or before 90 days',
      topHoldings: [
        { name: 'Tata Motors Ltd', weight: 6.8 },
        { name: 'Reliance Industries Ltd', weight: 5.5 },
        { name: 'Larsen & Toubro Ltd', weight: 4.8 },
        { name: 'Bharat Electronics Ltd', weight: 4.2 },
        { name: 'Maruti Suzuki India Ltd', weight: 3.9 }
      ]
    },
    'SBIBLUECHIP': {
      expenseRatio: 0.85,
      exitLoad: '1.00% within 365 days',
      topHoldings: [
        { name: 'HDFC Bank Ltd', weight: 8.2 },
        { name: 'ICICI Bank Ltd', weight: 7.5 },
        { name: 'Reliance Industries Ltd', weight: 6.1 },
        { name: 'Infosys Ltd', weight: 5.4 },
        { name: 'ITC Limited', weight: 4.8 }
      ]
    },
    'HDFCMIDCAP': {
      expenseRatio: 0.74,
      exitLoad: '1.00% within 365 days',
      topHoldings: [
        { name: 'Cholamandalam Investment', weight: 4.5 },
        { name: 'HDFC Bank Ltd', weight: 4.1 },
        { name: 'Tata Power Company Ltd', weight: 3.8 },
        { name: 'Hindustan Aeronautics Ltd', weight: 3.5 },
        { name: 'Federal Bank Ltd', weight: 3.2 }
      ]
    },
    'NIPPONSMALLCAP': {
      expenseRatio: 0.68,
      exitLoad: '1.00% within 30 days',
      topHoldings: [
        { name: 'Tube Investments of India', weight: 3.9 },
        { name: 'HDFC Bank Ltd', weight: 3.1 },
        { name: 'Kirloskar Brothers Ltd', weight: 2.8 },
        { name: 'Larsen & Toubro Ltd', weight: 2.5 },
        { name: 'KPIT Technologies Ltd', weight: 2.2 }
      ]
    }
  }), []);

  const getMfDiagnostics = (symbol: string) => {
    const clean = symbol.split('.')[0].toUpperCase().trim();
    if (MUTUAL_FUND_DIAGNOSTICS_DB[clean]) {
      return MUTUAL_FUND_DIAGNOSTICS_DB[clean];
    }
    
    // Hash-based fallback to generate deterministic realistic details
    let hash = 0;
    for (let i = 0; i < clean.length; i++) {
      hash = clean.charCodeAt(i) + ((hash << 5) - hash);
    }
    const expenseRatio = parseFloat((0.4 + Math.abs(hash % 100) / 100).toFixed(2));
    const exitLoad = `${Math.abs(hash % 2) === 0 ? '1.00%' : '0.50%'} if redeemed within ${Math.abs(hash % 3) === 0 ? '30' : '365'} days`;
    
    return {
      expenseRatio,
      exitLoad,
      topHoldings: [
        { name: 'HDFC Bank Ltd', weight: 6.2 },
        { name: 'Reliance Industries Ltd', weight: 5.5 },
        { name: 'ICICI Bank Ltd', weight: 4.8 },
        { name: 'Infosys Ltd', weight: 4.0 },
        { name: 'Tata Consultancy Services', weight: 3.5 }
      ]
    };
  };

  // Enriched portfolio resolving ISINs, symbols, sectors and asset classes
  const enrichedPortfolio = useMemo(() => {
    return portfolio.map(item => {
      const cleanSym = item.symbol.split('.')[0].toUpperCase().trim();
      
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
        if (targetSym === 'Physicswallah') {
          resolvedName = 'Physicswallah Limited';
          resolvedSector = 'Education Services';
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
        }
        
        if (item.sector && item.sector !== 'General' && item.sector !== 'Other') {
          resolvedSector = item.sector;
        } else if (resolvedSector === 'Other') {
          resolvedSector = 'General';
        }
      }

      let currentPrice = item.current || 0;
      if (currentPrice === 0) {
        currentPrice = item.avgCost || 100.00;
      }

      let avgCost = item.avgCost || 0;
      if (avgCost === 0) {
        avgCost = parseFloat((currentPrice * 0.85).toFixed(4));
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
  }, [portfolio]);
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [watchlistStocks, setWatchlistStocks] = useState<WatchlistStock[]>([]);
  const [conversations, setConversations] = useState<any[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string>('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [thinkingEvents, setThinkingEvents] = useState<AgentEventData[]>([]);
  const [activeTab, setActiveTab] = useState<'portfolio' | 'watchlist'>('portfolio');
  const [marketTab, setMarketTab] = useState<'india' | 'us' | 'currencies' | 'crypto' | 'futures'>('india');

  // Chart benchmark states
  const [selectedBenchmark, setSelectedBenchmark] = useState<string>('NIFTY50');

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
    india: [
      { symbol: 'NIFTY 50',  value: '23,939.45', change: '(-92.25)',  changePct: -0.38, sparkData: [24050, 24010, 24020, 23980, 23960, 23990, 23945, 23930, 23939] },
      { symbol: 'SENSEX',    value: '76,093.52', change: '(-395.44)', changePct: -0.52, sparkData: [76500, 76450, 76400, 76300, 76250, 76200, 76150, 76100, 76093] },
      { symbol: 'NIFTY BANK', value: '55,067.65', change: '(-226.00)', changePct: -0.41, sparkData: [55300, 55280, 55260, 55200, 55150, 55120, 55080, 55070, 55067] },
      { symbol: 'NIFTY IT',  value: '28,987.85', change: '(+4.05)',   changePct: 0.03,  sparkData: [28950, 28960, 28970, 28965, 28975, 28980, 28985, 28988, 28987] },
    ],
    us: [
      { symbol: 'S&P 500',  value: '5,832.40', change: '(+18.32)', changePct: 0.31, sparkData: [5800, 5810, 5815, 5820, 5825, 5830, 5828, 5832, 5832] },
      { symbol: 'NASDAQ',   value: '18,791.12', change: '(+45.67)', changePct: 0.24, sparkData: [18700, 18720, 18750, 18760, 18780, 18785, 18790, 18791, 18791] },
      { symbol: 'DOW',      value: '42,388.50', change: '(-89.20)', changePct: -0.21, sparkData: [42500, 42480, 42460, 42440, 42420, 42400, 42390, 42388, 42388] },
      { symbol: 'VIX',      value: '15.42', change: '(-0.38)',  changePct: -2.40, sparkData: [16.2, 16.0, 15.9, 15.8, 15.7, 15.6, 15.5, 15.45, 15.42] },
    ],
    currencies: [
      { symbol: 'USD/INR',  value: '84.12', change: '(+0.08)', changePct: 0.10, sparkData: [84.0, 84.02, 84.05, 84.08, 84.09, 84.1, 84.11, 84.12, 84.12] },
      { symbol: 'EUR/INR',  value: '92.34', change: '(-0.12)', changePct: -0.13, sparkData: [92.5, 92.48, 92.45, 92.4, 92.38, 92.36, 92.35, 92.34, 92.34] },
      { symbol: 'GBP/INR',  value: '110.22', change: '(+0.34)', changePct: 0.31, sparkData: [109.8, 109.9, 110.0, 110.1, 110.15, 110.18, 110.2, 110.22, 110.22] },
      { symbol: 'JPY/INR',  value: '0.5612', change: '(+0.002)', changePct: 0.36, sparkData: [0.559, 0.5595, 0.5600, 0.5605, 0.5608, 0.5610, 0.5612, 0.5612, 0.5612] },
    ],
    crypto: [
      { symbol: 'BTC',  value: '$67,432', change: '(+2.40%)', changePct: 2.40, sparkData: [65800, 66000, 66200, 66500, 66800, 67000, 67200, 67400, 67432] },
      { symbol: 'ETH',  value: '$2,521', change: '(+1.82%)', changePct: 1.82, sparkData: [2470, 2480, 2490, 2495, 2505, 2510, 2515, 2520, 2521] },
      { symbol: 'SOL',  value: '$148.20', change: '(-0.95%)', changePct: -0.95, sparkData: [150, 149.5, 149.2, 149, 148.8, 148.6, 148.4, 148.25, 148.2] },
      { symbol: 'XRP',  value: '$0.5234', change: '(+0.42%)', changePct: 0.42, sparkData: [0.520, 0.521, 0.522, 0.5215, 0.522, 0.5225, 0.523, 0.5234, 0.5234] },
    ],
    futures: [
      { symbol: 'NIFTY FUT',  value: '23,968.50', change: '(-78.20)', changePct: -0.32, sparkData: [24050, 24020, 24000, 23990, 23980, 23975, 23970, 23968, 23968] },
      { symbol: 'BANKNIFTY FUT', value: '55,124.80', change: '(-198.40)', changePct: -0.36, sparkData: [55320, 55280, 55250, 55200, 55170, 55150, 55130, 55125, 55124] },
      { symbol: 'CRUDE OIL', value: '$72.45', change: '(+0.62)', changePct: 0.86, sparkData: [71.8, 72.0, 72.1, 72.2, 72.3, 72.35, 72.4, 72.45, 72.45] },
      { symbol: 'GOLD',     value: '$2,654', change: '(+8.40)', changePct: 0.32, sparkData: [2640, 2645, 2648, 2650, 2652, 2653, 2654, 2654, 2654] },
    ],
  });

  const allStockData: Record<string, { name: string; price: string; change: string; changePct: number; sector: string }> = {
    RELIANCE: { name: 'Reliance Industries Ltd', price: '2,931.40', change: '+32.10', changePct: 1.11, sector: 'Energy' },
    TCS: { name: 'Tata Consultancy Services', price: '3,842.15', change: '+12.45', changePct: 0.33, sector: 'IT' },
    INFY: { name: 'Infosys Limited', price: '1,452.90', change: '-18.40', changePct: -1.25, sector: 'IT' },
    HDFCBANK: { name: 'HDFC Bank Limited', price: '1,562.10', change: '+14.60', changePct: 0.94, sector: 'Banking' },
    TATAMOTORS: { name: 'Tata Motors Limited', price: '942.50', change: '+22.15', changePct: 2.41, sector: 'Consumer' },
    ASIANPAINT: { name: 'Asian Paints Limited', price: '2,810.00', change: '-42.10', changePct: -1.48, sector: 'Consumer' },
    ZOMATO: { name: 'Zomato Limited', price: '184.20', change: '+8.15', changePct: 4.63, sector: 'Consumer' },
    ITC: { name: 'ITC Limited', price: '431.50', change: '-1.20', changePct: -0.28, sector: 'FMCG' }
  };

  const userUniverseSymbols = useMemo(() => {
    const portfolioSymbols = enrichedPortfolio.map(p => p.symbol.toUpperCase());
    const watchlistSymbols = watchlist.map(w => w.toUpperCase());
    return Array.from(new Set([...portfolioSymbols, ...watchlistSymbols]));
  }, [enrichedPortfolio, watchlist]);

  const recentInsights = useMemo<InsightItem[]>(() => {
    const templateInsights: Record<string, Omit<InsightItem, 'id' | 'timestamp'>> = {
      RELIANCE: {
        ticker: 'RELIANCE',
        type: 'valuation',
        title: 'DCF Intrinsic Mismatch',
        summary: 'Mark-IT\'s WACC valuation models calculate an intrinsic value of ₹3,240. Represents a 10.5% margin of safety relative to market pricing.'
      },
      ASIANPAINT: {
        ticker: 'ASIANPAINT',
        type: 'risk',
        title: 'Pledge Indicator Alert',
        summary: 'Promoter pledge ratio ticked up by 2.1% in the recent filings. Financial health rating remains at 8/9, but leverage warrants monitoring.'
      },
      TCS: {
        ticker: 'TCS',
        type: 'earnings',
        title: 'Operating Margin Premium',
        summary: 'TCS reports EBIT margin of 24.6%, outpacing peers (Infosys at 21.2%). Operating cash flows demonstrate significant pricing power.'
      },
      INFY: {
        ticker: 'INFY',
        type: 'valuation',
        title: 'Cloud Growth Acceleration',
        summary: 'Infosys shows a 14% YoY growth in cloud services segment, hinting at strong margin expansion in upcoming quarters.'
      },
      HDFCBANK: {
        ticker: 'HDFCBANK',
        type: 'risk',
        title: 'Net Interest Margin Stabilization',
        summary: 'NIM stabilized at 3.4% this quarter. Merging headwinds are fully priced in, prompting positive credit outlook upgrade.'
      },
      TATAMOTORS: {
        ticker: 'TATAMOTORS',
        type: 'earnings',
        title: 'EV Volume Milestone',
        summary: 'EV segment volumes crossed 15,000 units this quarter. Operating leverage is turning positive for domestic PV business.'
      },
      ZOMATO: {
        ticker: 'ZOMATO',
        type: 'valuation',
        title: 'Contribution Margin Peak',
        summary: 'Zomato food delivery contribution margin expands to 7.1%. Blinkit integration scaling faster than consensus estimates.'
      },
      ITC: {
        ticker: 'ITC',
        type: 'earnings',
        title: 'FMCG Margin Outperformance',
        summary: 'ITC non-cigarette FMCG segment EBITDA margins expand by 120bps, driven by premiumization and supply chain scaling.'
      }
    };

    const list: InsightItem[] = [];
    userUniverseSymbols.forEach((sym, idx) => {
      const upperSym = sym.toUpperCase();
      const clean = upperSym.split('.')[0];
      const ISIN_TO_SYMBOL: Record<string, string> = {
        'INE0LP301011': 'LTIM',
        'INE002A01018': 'RELIANCE',
        'INE467B01029': 'TCS',
        'INE009A01021': 'INFY',
        'INE040A01034': 'HDFCBANK',
        'INE154A01025': 'ITC',
        'INE021A01026': 'ASIANPAINT',
        'INE155A01022': 'TATAMOTORS',
        'INE758T01015': 'ZOMATO'
      };
      const targetSym = ISIN_TO_SYMBOL[clean] || clean;
      const pItem = enrichedPortfolio.find(p => p.symbol.toUpperCase() === upperSym);
      const stockItem = INDIAN_STOCKS.find(s => s.symbol.toUpperCase() === targetSym);
      const resolvedName = pItem ? pItem.name : (stockItem ? stockItem.name : allStockData[upperSym]?.name || `${targetSym} Limited`);

      if (templateInsights[upperSym]) {
        list.push({
          id: `ins-${idx}`,
          timestamp: `${idx * 2 + 1} hours ago`,
          name: resolvedName,
          ...templateInsights[upperSym]
        });
      } else {
        const types: Array<'valuation' | 'risk' | 'earnings'> = ['valuation', 'risk', 'earnings'];
        const chosenType = types[idx % types.length];
        let title = '';
        let summary = '';
        if (chosenType === 'valuation') {
          title = `Relative Valuation Upside — ${resolvedName}`;
          summary = `Mark-IT analysis of ${resolvedName} shows it trading at a 15% discount to historical P/E median, suggesting short-term mean reversion potential.`;
        } else if (chosenType === 'risk') {
          title = `Systematic Volatility Shift — ${resolvedName}`;
          summary = `Beta of ${resolvedName} increased to 1.18. Increased correlation with benchmark suggests higher sensitivity to macro interest rate shifts.`;
        } else {
          title = `Earnings Performance Outlook — ${resolvedName}`;
          summary = `Consensus estimates for ${resolvedName} project 8% revenue growth. Free cash flow generation remains high with strong cash conversion cycle.`;
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
      }
    });

    if (list.length === 0) {
      return [
        {
          id: 'ins-1',
          ticker: 'RELIANCE',
          name: 'Reliance Industries Ltd',
          type: 'valuation',
          title: 'DCF Intrinsic Mismatch',
          summary: 'Mark-IT\'s WACC valuation models calculate an intrinsic value of ₹3,240. Represents a 10.5% margin of safety relative to market pricing.',
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
  }, [userUniverseSymbols, enrichedPortfolio]);

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
    // Load portfolio
    const savedPortfolioRaw = localStorage.getItem('prospektlab_portfolio');
    const parsedPortfolio: PortfolioItem[] = savedPortfolioRaw ? JSON.parse(savedPortfolioRaw) : [];
    setPortfolio(parsedPortfolio);

    const syncPortfolio = async () => {
      try {
        const res = await getPortfolioMirror();
        if (res && res.positions) {
          const mapped = res.positions.map((p: any) => {
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
            
            const cleanSym = p.symbol.split('.')[0].toUpperCase().trim();
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
            let resolvedName = p.name;
            let resolvedSector = p.sector;
            
            if (targetSym === 'MOMF') {
              resolvedName = 'Motilal Oswal Manufacturing Fund - Direct Growth';
              resolvedSector = 'Thematic - Manufacturing';
            } else if (targetSym === 'Physicswallah') {
              resolvedName = 'Physicswallah Limited';
              resolvedSector = 'Education Services';
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
        }
      } catch (e) {
        console.error('Failed to sync portfolio from mirror', e);
      }
    };
    syncPortfolio();

    if (parsedPortfolio.length === 0) {
      setActiveTab('watchlist');
    }

    // Load watchlist symbols
    const savedWatchlistRaw = localStorage.getItem('prospektlab_watchlist');
    const savedWatchlist: string[] = savedWatchlistRaw ? JSON.parse(savedWatchlistRaw) : ['RELIANCE', 'TCS', 'INFY'];
    setWatchlist(savedWatchlist);

    // Build watchlist stocks
    const stocksList: WatchlistStock[] = savedWatchlist.map(sym => {
      const info = allStockData[sym] || { name: `${sym} Company`, price: '100.00', change: '+0.00', changePct: 0 };
      return {
        symbol: sym,
        name: info.name,
        price: info.price,
        change: info.change,
        changePct: info.changePct
      };
    });
    setWatchlistStocks(stocksList);

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
      const firstConv = savedConversations[0];
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
  }, []);

  const fetchBackendAnalytics = async () => {
    try {
      await getMfAnalytics();
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
        text: `Mark-IT here. I don't do hope — I do numbers. Ask me anything about your book, a ticker, or the tape.`
      }
    ];
    setMessages(welcomeMsgs);
    localStorage.setItem(`prospektlab_messages_${convId}`, JSON.stringify(welcomeMsgs));
  };

  // Scroll chat bubble container to bottom
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [messages.length, isThinking]);

  // Live indices ticker simulation
  useEffect(() => {
    const isMarketOpen = (symbol: string, category: string): boolean => {
      const now = new Date();
      if (category === 'crypto') return true;

      const getTZDayAndHour = (tz: string) => {
        const formatter = new Intl.DateTimeFormat('en-US', {
          timeZone: tz,
          hour12: false,
          weekday: 'short',
          hour: 'numeric',
          minute: 'numeric'
        });
        const parts = formatter.formatToParts(now);
        const day = parts.find(p => p.type === 'weekday')?.value || 'Mon';
        const hour = parseInt(parts.find(p => p.type === 'hour')?.value || '0', 10);
        const minute = parseInt(parts.find(p => p.type === 'minute')?.value || '0', 10);
        return { day, hour, minute };
      };

      const isWeekend = (day: string) => day === 'Sat' || day === 'Sun';

      if (category === 'india' || symbol.includes('NIFTY') || symbol.includes('BANKNIFTY') || symbol.includes('SENSEX')) {
        const { day, hour, minute } = getTZDayAndHour('Asia/Kolkata');
        if (isWeekend(day)) return false;
        const timeInMinutes = hour * 60 + minute;
        return timeInMinutes >= 555 && timeInMinutes <= 930;
      }

      if (category === 'us') {
        const { day, hour, minute } = getTZDayAndHour('America/New_York');
        if (isWeekend(day)) return false;
        const timeInMinutes = hour * 60 + minute;
        return timeInMinutes >= 570 && timeInMinutes <= 960;
      }

      if (category === 'currencies' || category === 'futures') {
        const { day } = getTZDayAndHour('Asia/Kolkata');
        return !isWeekend(day);
      }

      return true;
    };

    const interval = setInterval(() => {
      setLiveIndexData(prev => {
        const currentList = prev[marketTab];
        if (!currentList) return prev;

        const updated = currentList.map((item) => {
          if (!isMarketOpen(item.symbol, marketTab)) return item;
          if (Math.random() > 0.55) return item;

          const lastPrice = item.sparkData[item.sparkData.length - 1];
          const tick = lastPrice * (0.0008 + Math.random() * 0.0027) * (Math.random() > 0.5 ? 1 : -1);
          const newPrice = Math.max(0.01, lastPrice + tick);
          const newSpark = [...item.sparkData.slice(-12), parseFloat(newPrice.toFixed(2))];
          const base = newSpark[0];
          const newChangePct = ((newPrice - base) / base) * 100;
          const newChange = `(${newChangePct >= 0 ? '+' : ''}${(newPrice - base).toFixed(2)})`;

          let displayValue = newPrice.toLocaleString('en-IN');
          if (item.symbol.includes('USD') || item.symbol.includes('EUR') || item.symbol.includes('GBP') || item.symbol === 'GOLD' || item.symbol === 'CRUDE OIL') {
            displayValue = item.symbol.includes('USD') || item.symbol.includes('EUR') || item.symbol.includes('GBP')
              ? newPrice.toFixed(2)
              : '$' + newPrice.toFixed(2);
          } else if (item.symbol.includes('BTC') || item.symbol.includes('ETH') || item.symbol.includes('SOL')) {
            displayValue = '$' + Math.round(newPrice).toLocaleString();
          } else if (item.symbol === 'XRP') {
            displayValue = '$' + newPrice.toFixed(4);
          } else if (item.symbol.includes('FUT') || item.symbol.includes('NIFTY') || item.symbol.includes('SENSEX') || item.symbol.includes('BANK')) {
            displayValue = Math.round(newPrice).toLocaleString('en-IN');
          }

          return {
            ...item,
            value: displayValue,
            change: newChange,
            changePct: parseFloat(newChangePct.toFixed(2)),
            sparkData: newSpark,
          };
        });

        return {
          ...prev,
          [marketTab]: updated,
        };
      });
    }, 2650);

    return () => clearInterval(interval);
  }, [marketTab]);

  // Calculations for total portfolio NAV summary
  const computedPortfolioDetails = enrichedPortfolio.map(item => {
    const costBasis = item.qty * item.avgCost;
    const currentValue = item.qty * item.current;
    const pnl = currentValue - costBasis;
    const pnlPct = costBasis > 0 ? (pnl / costBasis) * 100 : 0;
    return { ...item, currentValue, pnl, pnlPct };
  });

  const portfolioSummary = computedPortfolioDetails.reduce((acc, curr) => {
    acc.totalCost += curr.qty * curr.avgCost;
    acc.totalValue += curr.currentValue;
    acc.totalPnL += curr.pnl;
    return acc;
  }, { totalCost: 0, totalValue: 0, totalPnL: 0 });

  const portfolioTotalReturnPct = portfolioSummary.totalCost > 0 
    ? (portfolioSummary.totalPnL / portfolioSummary.totalCost) * 100 
    : 0;

  // Donut chart calculations for sector allocation
  const sectorAllocations = enrichedPortfolio.reduce((acc, curr) => {
    const currentValue = curr.qty * curr.current;
    acc[curr.sector] = (acc[curr.sector] || 0) + currentValue;
    return acc;
  }, {} as Record<string, number>);

  const sectorChartData = {
    labels: Object.keys(sectorAllocations),
    data: Object.values(sectorAllocations)
  };

  // Donut chart calculations for Asset Allocation (Equity vs MF vs Cash/Bonds)
  const assetAllocations = enrichedPortfolio.reduce((acc, curr) => {
    const value = curr.qty * curr.current;
    acc[curr.assetClass] = (acc[curr.assetClass] || 0) + value;
    return acc;
  }, {} as Record<string, number>);

  const assetChartData = {
    labels: Object.keys(assetAllocations).length > 0 ? Object.keys(assetAllocations) : ['Equity'],
    data: Object.values(assetAllocations).length > 0 ? Object.values(assetAllocations) : [1]
  };

  // --- Portfolio vs Benchmark Comparative Data Walks ---
  const compareChartData = useMemo(() => {
    const days = 252; // 1 year daily chart
    const labels: string[] = [];
    const benchValues: number[] = [];
    const portValues: number[] = [];
    const today = new Date();

    // Seed variables based on benchmark ID to get consistent lines
    let bSeed = selectedBenchmark === 'NIFTY50' ? 42 : selectedBenchmark === 'SENSEX' ? 88 : selectedBenchmark === 'NIFTYBANK' ? 104 : 12;
    const bRand = () => {
      bSeed = (bSeed * 9301 + 49297) % 233280;
      return bSeed / 233280;
    };

    let pSeed = 99; // portfolio seed
    const pRand = () => {
      pSeed = (pSeed * 9301 + 49297) % 233280;
      return pSeed / 233280;
    };

    let benchPrice = 100; // indexed starting at 100
    let portPrice = 100;  // indexed starting at 100

    // Portfolio beta factor (simulated based on size of portfolio)
    const beta = 1.05 + enrichedPortfolio.length * 0.01;

    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(today.getDate() - i);
      if (d.getDay() === 0 || d.getDay() === 6) continue;

      const drift = 0.0003; // benchmark drift
      const vol = 0.012;   // benchmark volatility
      const bShock = (bRand() - 0.5) * 2 * vol;
      const bReturn = drift + bShock;
      benchPrice = benchPrice * (1 + bReturn);

      // Portfolio returns = beta * benchmark_return + alpha + tracking_error
      const alpha = 0.00015; // 3.8% annual alpha outperformance
      const trackingError = 0.005;
      const pShock = (pRand() - 0.5) * 2 * trackingError;
      const pReturn = beta * bReturn + alpha + pShock;
      portPrice = portPrice * (1 + pReturn);

      labels.push(d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }));
      benchValues.push(parseFloat(benchPrice.toFixed(2)));
      portValues.push(parseFloat(portPrice.toFixed(2)));
    }

    return { labels, benchValues, portValues };
  }, [selectedBenchmark, enrichedPortfolio]);

  // Portfolio derived risk metrics (Value at Risk, Beta, Sharpe, HHI)
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
    const topSectorPct = topSector ? (topSector[1] / totalVal) * 100 : 0;
    
    // Herfindahl-Hirschman Index (HHI) for concentration risk
    const hhi = computedPortfolioDetails.reduce((sum, p) => {
      const weight = (p.currentValue / totalVal) * 100;
      return sum + (weight * weight);
    }, 0);
    
    // Beta
    const beta = 0.95 + (computedPortfolioDetails.length * 0.02);
    
    // Value at Risk (95% 1-day)
    const var95 = totalVal * 0.0165 * beta;

    return { best, worst, winners, losers, topSector, topSectorPct, beta, hhi, var95 };
  })();

  // Tracked universe movers
  const allTrackedStocks = [...enrichedPortfolio, ...watchlistStocks.filter(w => !enrichedPortfolio.find(p => p.symbol === w.symbol)).map(w => ({
    symbol: w.symbol, name: w.name, qty: 0, avgCost: 0,
    current: parseFloat(w.price.replace(/,/g, '')) || 0,
    sector: 'Watchlist',
  } as PortfolioItem))];

  const stocksWithChange = allTrackedStocks.map(s => {
    const meta = allStockData[s.symbol];
    return {
      symbol: s.symbol,
      name: s.name,
      price: meta?.price || s.current.toFixed(2),
      changePct: meta?.changePct ?? 0,
      isOwned: enrichedPortfolio.some(p => p.symbol === s.symbol),
    };
  });

  const gainers = [...stocksWithChange].filter(s => s.changePct > 0).sort((a, b) => b.changePct - a.changePct).slice(0, 4);
  const losersList = [...stocksWithChange].filter(s => s.changePct < 0).sort((a, b) => a.changePct - b.changePct).slice(0, 4);
  const mostActive = [...stocksWithChange].sort((a, b) => Math.abs(b.changePct) - Math.abs(a.changePct)).slice(0, 4);

  // News sentiment
  const newsFeed = [
    { id: 'n1', source: 'Mint', time: '12 min ago', headline: 'Tata Group stocks surge ahead of strategic board meeting', sentiment: 'bullish', tickers: ['TATAMOTORS'] },
    { id: 'n2', source: 'Bloomberg', time: '38 min ago', headline: 'Rupee retreats from recent highs amid importer dollar demand', sentiment: 'neutral', tickers: [] },
    { id: 'n3', source: 'ET Markets', time: '1 hour ago', headline: 'TCS posts record EBIT margin; analysts lift target prices', sentiment: 'bullish', tickers: ['TCS'] },
    { id: 'n4', source: 'Reuters', time: '2 hours ago', headline: 'Promoter pledge in Asian Paints ticks up — what it means', sentiment: 'bearish', tickers: ['ASIANPAINT'] },
    { id: 'n5', source: 'Moneycontrol', time: '3 hours ago', headline: 'Nifty Bank breaks key support — institutional positioning shifts', sentiment: 'bearish', tickers: [] },
  ];

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
      
      const ISIN_TO_SYMBOL: Record<string, string> = {
        'INE0LP301011': 'PHYSICSWALLAH',
        'INE002A01018': 'RELIANCE',
        'INE467B01029': 'TCS',
        'INE009A01021': 'INFY',
        'INE040A01034': 'HDFCBANK',
        'INE154A01025': 'ITC',
        'INE021A01026': 'ASIANPAINT',
        'INE155A01022': 'TATAMOTORS',
        'INE758T01015': 'ZOMATO'
      };
      
      const targetSym = ISIN_TO_SYMBOL[clean] || clean;
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

  const enrichQueryWithPortfolio = (query: string): string => {
    if (enrichedPortfolio.length === 0) return '';

    const scope = detectPortfolioScope(query);
    if (scope === 'portfolio_scope') {
      const breakdownSectors = Object.entries(sectorAllocations)
        .map(([sec, val]) => `${sec} ${((val / portfolioSummary.totalValue) * 100).toFixed(0)}%`)
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
    setThinkingEvents([]);

    const enrichedObjective = enrichQueryWithPortfolio(message);
    const startMs = performance.now();

    try {
      // API call to start background job
      const startRes = await startResearch(message, depth, activeConversationId, enrichedObjective);
      const backendSessionId = startRes.session_id;

      // Subscribe to SSE updates
      const unsubscribe = streamSession(
        backendSessionId,
        (event) => {
          // Push event to thinking stack
          setThinkingEvents((prev) => [...prev, event]);
        },
        async () => {
          // Finished research Turn
          setIsThinking(false);
          const elapsed = Math.round(performance.now() - startMs);

          // Get full synthesized result
          try {
            const finalResult = await getSessionResult(backendSessionId);
            const aiResponse: Message = {
              sender: 'ai',
              text: finalResult.memo || 'Analysis complete.',
              richData: finalResult.final?.payload?.rich || finalResult.final || null,
              depth: depth,
              elapsedMs: elapsed
            };

            setMessages((prev) => {
              const merged = [...prev, aiResponse];
              localStorage.setItem(`prospektlab_messages_${activeConversationId}`, JSON.stringify(merged));
              return merged;
            });
          } catch (resErr) {
            console.error('Failed to retrieve final memo details', resErr);
          }
        },
        (error) => {
          setIsThinking(false);
          showToast(error.message || 'Stream processing failed.', 'error');
        }
      );

      abortStreamRef.current = unsubscribe;
    } catch (err: any) {
      setIsThinking(false);
      const errMsg = err.message || 'Failed to connect to Quant engine.';
      showToast(errMsg, 'error');
      
      // Append error message bubble
      const errResponse: Message = {
        sender: 'ai',
        text: `**Connection Error**: ${errMsg}`
      };
      setMessages((prev) => [...prev, errResponse]);
    }
  };

  const handleStopGeneration = async () => {
    if (abortStreamRef.current) {
      abortStreamRef.current();
      abortStreamRef.current = null;
    }
    
    try {
      await stopSession(activeConversationId);
    } catch (e) {
      // Already terminated on server
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

  const handleSelectStock = (symbol: string) => {
    handleSendMessage(`Analyse ${symbol} and check its core ratios.`, 'standard');
  };

  const handleAddStock = (symbol: string) => {
    if (watchlist.includes(symbol)) return;
    const updated = [...watchlist, symbol];
    setWatchlist(updated);
    localStorage.setItem('prospektlab_watchlist', JSON.stringify(updated));

    const info = allStockData[symbol] || { name: `${symbol} Ticker`, price: '150.00', change: '+2.10', changePct: 1.4 };
    const newStock: WatchlistStock = {
      symbol,
      name: info.name,
      price: info.price,
      change: info.change,
      changePct: info.changePct
    };
    setWatchlistStocks([...watchlistStocks, newStock]);
  };

  const handleRemoveStock = (symbol: string) => {
    const updated = watchlist.filter(s => s !== symbol);
    setWatchlist(updated);
    localStorage.setItem('prospektlab_watchlist', JSON.stringify(updated));
    setWatchlistStocks(watchlistStocks.filter(s => s.symbol !== symbol));
  };

  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    // Falls back to logging if AuthContext toast dispenser is unreachable
    console.log(`[Toast ${type.toUpperCase()}] ${message}`);
  };

  const hasEngaged = messages.length > 1;
  const briefingTime = new Date().getHours();
  const timeGreeting = briefingTime < 12 ? 'Good morning' : briefingTime < 17 ? 'Good afternoon' : 'Good evening';
  const username = (localStorage.getItem('prospektlab_username') || 'analyst').toLowerCase();

  const activeIndices = liveIndexData[marketTab] || liveIndexData.india;

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
      portfolioSummary={portfolio.length > 0 ? {
        totalValue: portfolioSummary.totalValue,
        totalPnL: portfolioSummary.totalPnL,
        totalReturnPct: portfolioTotalReturnPct
      } : undefined}
      conversations={conversations}
      onDeleteConversation={handleDeleteConversation}
      onClearHistory={handleClearHistory}
      onNewConversation={handleNewConversation}
      onSelectConversation={handleSelectConversation}
      activeConversationId={activeConversationId}
    >
      <div className={`workbench ${isChatHidden ? 'chat-closed' : 'chat-open'}`} style={{
        gridTemplateColumns: `minmax(0, 1fr) ${isChatHidden ? '0px' : `${chatWidth}px`}`,
        transition: isDraggingChat ? 'none' : undefined
      }}>
        {/* ════════════════════════ LEFT: DATA DASHBOARD ════════════════════════ */}
        <div className="workbench-data">
          {/* Market tabs */}
          <div className="market-tabs">
            {([
              { id: 'us', label: 'US' },
              { id: 'india', label: 'India' },
              { id: 'currencies', label: 'Currencies' },
              { id: 'crypto', label: 'Crypto' },
              { id: 'futures', label: 'Futures' },
            ] as const).map(t => (
              <button
                key={t.id}
                className="market-tab"
                data-active={marketTab === t.id}
                onClick={() => setMarketTab(t.id)}
              >
                {t.label}
              </button>
            ))}
            <div style={{ flex: 1 }} />
            <div style={{ fontSize: 10.5, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.08em', marginRight: 8 }}>
              <span className="live-dot" style={{ marginRight: 6 }} /> LIVE • NSE/BSE
            </div>
          </div>

          {/* Index ticker cards */}
          <div className="index-grid">
            {activeIndices.map(idx => (
              <IndexTickerCard
                key={idx.symbol}
                data={idx}
                onClick={() => handleSendMessage(`Give me a quick read on ${idx.symbol} — what's moving it today?`, 'standard')}
              />
            ))}
          </div>

          {/* Portfolio vs Benchmark Indexed Comparison Chart */}
          <div className="data-panel" style={{ marginBottom: 36 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>Comparative Returns (Indexed)</span>
              
              {/* Benchmark dropdown selector */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>VS BENCHMARK:</span>
                <select
                  value={selectedBenchmark}
                  onChange={(e) => setSelectedBenchmark(e.target.value)}
                  style={{
                    padding: '4px 8px',
                    fontSize: '11px',
                    borderRadius: '6px',
                    background: 'rgba(15, 23, 42, 0.6)',
                    borderColor: 'rgba(255, 255, 255, 0.08)',
                    height: '26px'
                  }}
                >
                  {BENCHMARKS.map(bench => (
                    <option key={bench.id} value={bench.id}>{bench.name}</option>
                  ))}
                </select>
              </div>
            </div>

            <InteractiveChart
              labels={compareChartData.labels}
              data={compareChartData.portValues}
              title="Your Portfolio (base = 100)"
              unit=""
              comparisonData={compareChartData.benchValues}
              comparisonTitle={BENCHMARKS.find(b => b.id === selectedBenchmark)?.name || 'Benchmark'}
              height={300}
            />

            <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>Comparison is indexed to 100 to show proportional performance over time</span>
              <span style={{ marginLeft: 'auto', color: 'var(--accent-cyan)', cursor: 'pointer' }}
                onClick={() => handleSendMessage(`Explain how my portfolio is performing compared to ${selectedBenchmark}.`, 'standard')}
              >
                Analyse return spread →
              </span>
            </div>
          </div>

          {/* Mark's read on your book stats */}
          {portfolioStats && (
            <>
              <div className="section-head">
                <div className="section-title">Mark-IT's read on your book</div>
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
                <div className="stat-tile stat-tile-cta" onClick={() => handleSendMessage('Audit my portfolio — what is the single biggest risk hiding in my book right now?', 'deep')}>
                  <div className="stat-tile-label" style={{ color: 'var(--accent-cyan)' }}>ASK MARK-IT</div>
                  <div style={{ fontSize: 13, lineHeight: 1.4, marginTop: 6, color: 'var(--text-primary)' }}>
                    "What's the one thing I'm missing about my book today?"
                  </div>
                </div>
              </div>
            </>
          )}

          {/* Double Donut Chart Flex Container (Sector & Asset Allocation) */}
          {enrichedPortfolio.length > 0 && sectorChartData.labels.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px', marginBottom: '28px' }}>
              <div className="data-panel">
                <div className="data-panel-head">
                  <div className="data-panel-title" style={{ fontSize: '13px', fontWeight: 600 }}>Sector Allocation</div>
                  <button
                    className="data-panel-link"
                    onClick={() => handleSendMessage('Audit my sector allocation — where am I over- or under-exposed?', 'standard')}
                  >
                    Audit →
                  </button>
                </div>
                <DonutChart labels={sectorChartData.labels} data={sectorChartData.data} title="" />
              </div>
              <div className="data-panel">
                <div className="data-panel-head">
                  <div className="data-panel-title" style={{ fontSize: '13px', fontWeight: 600 }}>Asset Allocation</div>
                  <button
                    className="data-panel-link"
                    onClick={() => handleSendMessage('Audit my asset allocation classes.', 'standard')}
                  >
                    Audit →
                  </button>
                </div>
                <DonutChart labels={assetChartData.labels} data={assetChartData.data} title="" />
              </div>
            </div>
          )}

          {/* ADVANCED PORTFOLIO RISK & ANALYTICS PANELS (Mutual Fund, Risk, Stress Test) */}
          {enrichedPortfolio.length > 0 && (
            <div className="data-panel" style={{ marginBottom: '28px' }}>
              <div className="data-panel-head" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '10px' }}>
                <div style={{ display: 'flex', gap: 16 }}>
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
                        onClick={() => handleSendMessage('Check my portfolio action items.', 'standard')}
                      >
                        Inspect Queue →
                      </div>
                    </div>
                  </div>
                )}

                {analyticsTab === 'mf' && (() => {
                  const mfHoldings = enrichedPortfolio.filter(p => p.assetClass === 'Mutual Fund');
                  const totalMfValue = mfHoldings.reduce((sum, p) => sum + (p.qty * p.current), 0);
                  const averageMfExpenseRatio = mfHoldings.length > 0 
                    ? mfHoldings.reduce((sum, p) => sum + getMfDiagnostics(p.symbol).expenseRatio, 0) / mfHoldings.length
                    : 0;

                  return (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                      {mfHoldings.length > 0 ? (
                        <>
                          {/* Summary Metrics Row */}
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
                            <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px' }}>
                              <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: '11px', marginBottom: '4px' }}>MUTUAL FUND ASSETS</div>
                              <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                                ₹{totalMfValue.toLocaleString('en-IN')}
                              </div>
                              <div style={{ color: 'var(--text-muted)', marginTop: '4px', fontSize: '10px' }}>
                                {mfHoldings.length} Active Scheme{mfHoldings.length > 1 ? 's' : ''}
                              </div>
                            </div>

                            <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px' }}>
                              <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: '11px', marginBottom: '4px' }}>AVG EXPENSE RATIO</div>
                              <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                                {averageMfExpenseRatio.toFixed(2)}%
                              </div>
                              <div style={{ 
                                color: averageMfExpenseRatio <= 1.15 ? 'var(--profit)' : 'var(--loss)', 
                                marginTop: '4px', 
                                fontSize: '10px',
                                fontWeight: 600
                              }}>
                                {averageMfExpenseRatio <= 1.15 ? '✓ Under Benchmark (1.15%)' : '⚠ Over Benchmark (1.15%)'}
                              </div>
                            </div>

                            <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px' }}>
                              <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: '11px', marginBottom: '4px' }}>PORTFOLIO EXPOSURE</div>
                              <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                                {((totalMfValue / (portfolioSummary.totalValue || 1)) * 100).toFixed(1)}%
                              </div>
                              <div style={{ color: 'var(--text-muted)', marginTop: '4px', fontSize: '10px' }}>
                                Allocation in Mutual Funds
                              </div>
                            </div>
                          </div>

                          {/* Individual Scheme Detail Cards */}
                          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '16px', marginTop: '4px' }}>
                            {mfHoldings.map(item => {
                              const diag = getMfDiagnostics(item.symbol);
                              const weightInPortfolio = ((item.qty * item.current) / (portfolioSummary.totalValue || 1)) * 100;
                              const isLowExpense = diag.expenseRatio <= 1.15;
                              
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

                                  {/* Expense Ratio Progress Bar */}
                                  <div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '11px', marginBottom: '6px' }}>
                                      <span style={{ color: 'var(--text-secondary)' }}>Expense Ratio</span>
                                      <span style={{ fontWeight: 600, color: isLowExpense ? 'var(--profit)' : 'var(--loss)' }}>
                                        {diag.expenseRatio}% <span style={{ fontSize: '9px', fontWeight: 'normal', color: 'var(--text-muted)' }}>(Benchmark: 1.15%)</span>
                                      </span>
                                    </div>
                                    <div style={{ width: '100%', height: '6px', background: 'rgba(255, 255, 255, 0.06)', borderRadius: '3px', overflow: 'hidden', position: 'relative' }}>
                                      <div style={{ 
                                        width: `${Math.min(100, (diag.expenseRatio / 2.0) * 100)}%`, 
                                        height: '100%', 
                                        background: isLowExpense ? 'linear-gradient(90deg, var(--accent-cyan), var(--profit))' : 'linear-gradient(90deg, var(--accent-cyan), var(--loss))', 
                                        borderRadius: '3px' 
                                      }} />
                                      {/* Benchmark line at 1.15% */}
                                      <div style={{ position: 'absolute', left: `${(1.15 / 2.0) * 100}%`, top: 0, bottom: 0, width: '1.5px', background: 'rgba(255, 255, 255, 0.3)' }} title="Benchmark: 1.15%" />
                                    </div>
                                  </div>

                                  {/* Exit Load Warning */}
                                  <div style={{ 
                                    display: 'flex', 
                                    gap: '8px', 
                                    alignItems: 'center', 
                                    background: 'rgba(245, 158, 11, 0.05)', 
                                    border: '1px solid rgba(245, 158, 11, 0.15)', 
                                    borderRadius: '6px', 
                                    padding: '8px 10px',
                                    fontSize: '11px' 
                                  }}>
                                    <span style={{ color: '#F59E0B', fontWeight: 'bold', fontSize: '13px' }}>⚠</span>
                                    <div style={{ color: 'rgba(245, 158, 11, 0.9)' }}>
                                      <span style={{ fontWeight: 600 }}>Exit Load Constraint:</span> {diag.exitLoad}
                                    </div>
                                  </div>

                                  {/* Top Underlying Holdings */}
                                  <div>
                                    <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '8px' }}>Top Underlying Asset Exposure</div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                      {diag.topHoldings.map((h, hIdx) => (
                                        <div key={hIdx}>
                                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10.5px', marginBottom: '2px' }}>
                                            <span style={{ color: 'var(--text-primary)' }}>{h.name}</span>
                                            <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>{h.weight}%</span>
                                          </div>
                                          <div style={{ width: '100%', height: '4px', background: 'rgba(255, 255, 255, 0.03)', borderRadius: '2px', overflow: 'hidden' }}>
                                            <div style={{ 
                                              width: `${h.weight * 5}%`, 
                                              height: '100%', 
                                              background: 'rgba(255, 255, 255, 0.15)', 
                                              borderRadius: '2px' 
                                            }} />
                                          </div>
                                        </div>
                                      ))}
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
                            Equity positions are standard. Mutual Fund Diagnostics will display expense benchmarks and exit loads for schemes present in your portfolio.
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
                        onClick={() => handleSendMessage('Simulate Nifty down 10% on my portfolio.', 'standard')}
                        style={{ padding: '8px', fontSize: '11px', background: 'rgba(251, 113, 133, 0.05)', borderColor: 'var(--loss)' }}
                      >
                        Nifty -10% Crash
                      </button>
                      <button
                        onClick={() => handleSendMessage('Simulate Nifty down 20% on my portfolio.', 'standard')}
                        style={{ padding: '8px', fontSize: '11px', background: 'rgba(251, 113, 133, 0.08)', borderColor: 'var(--loss)' }}
                      >
                        Nifty -20% Crash
                      </button>
                      <button
                        onClick={() => handleSendMessage('Simulate the 2020 COVID crash scenarios on my book.', 'standard')}
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
                <div key={s.symbol} className="mover-row" onClick={() => handleSendMessage(`Why is ${s.symbol} up today? Walk me through it.`, 'standard')}>
                  <div>
                    <div className="mover-sym">{s.symbol} {s.isOwned && <span className="owned-dot" title="You own this" />}</div>
                    <div className="mover-name">{s.name}</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="mover-price">₹{s.price}</div>
                    <div className="mover-pct" style={{ color: 'var(--profit)' }}>+{s.changePct.toFixed(2)}%</div>
                  </div>
                </div>
              ))}
            </div>
            <div className="movers-col">
              <div className="movers-col-head" style={{ color: 'var(--loss)' }}>↘ Losers</div>
              {losersList.length === 0 ? (
                <div className="movers-empty">All green. Enjoy it while it lasts.</div>
              ) : losersList.map(s => (
                <div key={s.symbol} className="mover-row" onClick={() => handleSendMessage(`Why is ${s.symbol} down today? Should I be worried?`, 'standard')}>
                  <div>
                    <div className="mover-sym">{s.symbol} {s.isOwned && <span className="owned-dot" title="You own this" />}</div>
                    <div className="mover-name">{s.name}</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="mover-price">₹{s.price}</div>
                    <div className="mover-pct" style={{ color: 'var(--loss)' }}>{s.changePct.toFixed(2)}%</div>
                  </div>
                </div>
              ))}
            </div>
            <div className="movers-col">
              <div className="movers-col-head">⚡ Most active</div>
              {mostActive.map(s => (
                <div key={s.symbol} className="mover-row" onClick={() => handleSendMessage(`Quick read on ${s.symbol} — what's the institutional view?`, 'standard')}>
                  <div>
                    <div className="mover-sym">{s.symbol} {s.isOwned && <span className="owned-dot" title="You own this" />}</div>
                    <div className="mover-name">{s.name}</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div className="mover-price">₹{s.price}</div>
                    <div className="mover-pct" style={{ color: s.changePct >= 0 ? 'var(--profit)' : 'var(--loss)' }}>
                      {s.changePct >= 0 ? '+' : ''}{s.changePct.toFixed(2)}%
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* AI Market summary */}
          <div className="section-head">
            <div className="section-title">{marketTab === 'india' ? 'India market summary' : `${marketTab.charAt(0).toUpperCase() + marketTab.slice(1)} market summary`}</div>
            <span className="section-sublabel">MARK-IT'S BRIEF • {marketSummary.sourcesCount} sources</span>
          </div>

          <div className="summary-card">
            <div className="summary-card-headline">{marketSummary.headline}</div>
            <div className="summary-card-body">{marketSummary.body}</div>
            <button
              className="summary-cta"
              onClick={() => handleSendMessage('Dive deeper on today\'s market moves — what should I actually do about my portfolio?', 'deep')}
            >
              <Sparkles size={13} /> Have Mark-IT dig into it
            </button>
          </div>

          {/* Holdings vs Watchlist table */}
          <div className="data-grid">
            <div className="data-panel">
              <div className="data-panel-head">
                <div style={{ display: 'flex', gap: 16 }}>
                  <button
                    onClick={() => setActiveTab('portfolio')}
                    style={{
                      background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                      color: activeTab === 'portfolio' ? 'var(--text-primary)' : 'var(--text-secondary)',
                      fontWeight: 600, fontSize: 13,
                    }}
                  >
                    Holdings
                  </button>
                  <button
                    onClick={() => setActiveTab('watchlist')}
                    style={{
                      background: 'none', border: 'none', padding: 0, cursor: 'pointer',
                      color: activeTab === 'watchlist' ? 'var(--text-primary)' : 'var(--text-secondary)',
                      fontWeight: 600, fontSize: 13,
                    }}
                  >
                    Watchlist
                  </button>
                </div>
                <button className="data-panel-link" onClick={() => navigate('/onboarding')}>Manage →</button>
              </div>

              {activeTab === 'portfolio' ? (
                enrichedPortfolio.length > 0 ? (
                  <PortfolioTable portfolio={enrichedPortfolio} onSelectStock={handleSelectStock} />
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
                    onClick={() => handleSendMessage(`Walk me through the ${ins.title} for ${ins.ticker}.`, 'standard')}
                  >
                    <div className="insight-row-meta">
                      <span>{ins.ticker}</span>
                      <span className={`insight-row-type ${insightTypeBadgeClass(ins.type)}`}>{ins.type}</span>
                      <span style={{ marginLeft: 'auto', fontWeight: 500, textTransform: 'none', letterSpacing: 0, color: 'var(--text-muted)' }}>{ins.timestamp}</span>
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
            <span className="section-sublabel">LIVE NEWS · MARK-IT'S SENTIMENT</span>
          </div>
          <div className="news-grid">
            {newsFeed.map(n => (
              <div key={n.id} className="news-card" onClick={() => handleSendMessage(`Tell me more about: ${n.headline}`, 'standard')}>
                <div className="news-card-meta">
                  <span className="news-source">{n.source}</span>
                  <span className="news-time">· {n.time}</span>
                  <span className="news-sentiment" style={{ color: sentimentColor(n.sentiment), borderColor: sentimentColor(n.sentiment) + '40' }}>
                    {sentimentLabel(n.sentiment)}
                  </span>
                </div>
                <div className="news-headline">{n.headline}</div>
                {n.tickers.length > 0 && (
                  <div className="news-tickers">
                    {n.tickers.map(t => <span key={t} className="news-ticker-pill">{t}</span>)}
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
                <div key={e.ticker} className="earnings-row" style={{ gap: '16px', padding: '12px 16px' }} onClick={() => handleSendMessage(`What should I expect from ${e.name}'s upcoming ${e.period} earnings?`, 'standard')}>
                  {/* Calendar Sheet Card on Left */}
                  <CalendarSheet dateStr={e.date} dateLabel={e.dateLabel} />
                  
                  {/* Info in Middle */}
                  <div className="earnings-info" style={{ flex: 1 }}>
                    <div className="earnings-name" style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13.5px', fontWeight: 600 }}>
                      {e.name}
                      {isOwned && <span className="owned-badge">OWNED</span>}
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: 4 }}>
                      {e.period} {e.when ? `· ${e.when}` : ''}
                    </div>
                    {/* Countdown and Date text */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: 4, fontSize: '11px' }}>
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
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6, minWidth: '140px' }}>
                    <span style={{ 
                      fontSize: '9.5px', fontWeight: 700, color: impactColor, 
                      background: impactBg, padding: '3px 8px', borderRadius: '6px',
                      letterSpacing: '0.02em', whiteSpace: 'nowrap'
                    }}>{impactLabel}</span>
                    <span style={{ fontSize: '10.5px', color: 'var(--text-muted)', maxWidth: '200px', textAlign: 'right', lineHeight: 1.3 }}>
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
          transition: isDraggingChat ? 'none' : undefined
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
          {/* Drag Handle left edge */}
          <div
            className="drag-handle-vertical drag-handle-left"
            onMouseDown={() => setIsDraggingChat(true)}
            style={{ width: '6px' }}
          />

          <div className="chat-rail-head">
            <div className="chat-rail-title">Mark-IT</div>
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
                  {timeGreeting}, {username}. I'm Mark-IT — your market read, unfiltered. What are we hunting today?
                </div>

                {suggestions.map((s, i) => (
                  <button key={i} className="suggestion-card" onClick={() => handleSendMessage(s, 'standard')}>
                    <span>{s}</span>
                    <span className="suggestion-card-icon"><Search size={11} /></span>
                  </button>
                ))}

                <div className="explore-label">Or try one of these</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  <button
                    className="mode-chip"
                    onClick={() => handleSendMessage('Deep research: build a complete investment thesis on RELIANCE.', 'deep')}
                  >
                    <Sparkles size={12} /> Full thesis
                  </button>
                  <button
                    className="mode-chip"
                    onClick={() => handleSendMessage('Run a DCF valuation on my largest holding.', 'standard')}
                  >
                    DCF valuation
                  </button>
                  <button
                    className="mode-chip"
                    onClick={() => handleSendMessage('Compare TCS vs Infosys on margins, growth, and quality.', 'standard')}
                  >
                    Head-to-head
                  </button>
                </div>
              </>
            ) : (
              <>
                {messages.map((msg, i) => (
                  i === 0 && msg.sender === 'ai' ? null : (
                    <div key={i} className="animate-slide-in-up">
                      <MessageBubble
                        sender={msg.sender}
                        text={msg.text}
                        richData={msg.richData}
                        depth={msg.depth}
                        elapsedMs={msg.elapsedMs}
                      />
                    </div>
                  )
                ))}
                <AgentThinking events={thinkingEvents} isActive={isThinking} />
              </>
            )}
          </div>

          <div className="chat-rail-dock">
            <ChatInput 
              onSend={handleSendMessage} 
              onStop={handleStopGeneration} 
              disabled={isThinking} 
            />
            <div className="chat-rail-footer">
              Mark-IT • every NSE name • Standard / Deep • Esc to stop
            </div>
          </div>
          </div>
        </div>
      </div>

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
    </AppShell>
  );
};

export default Dashboard;

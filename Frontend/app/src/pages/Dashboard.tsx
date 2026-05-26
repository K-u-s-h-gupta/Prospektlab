import React, { useState, useEffect, useRef } from 'react';
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
import { AgentEventData } from '../api/client';
import { Search, History, Maximize2, Edit3, Sparkles } from 'lucide-react';

interface Message {
  sender: 'user' | 'ai';
  text: string;
  richData?: any;
  depth?: 'chat' | 'standard' | 'deep';
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



export const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const [portfolio, setPortfolio] = useState<PortfolioItem[]>([]);
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [watchlistStocks, setWatchlistStocks] = useState<WatchlistStock[]>([]);
  const [conversations, setConversations] = useState<any[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string>('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [thinkingEvents, setThinkingEvents] = useState<AgentEventData[]>([]);
  const [activeTab, setActiveTab] = useState<'portfolio' | 'watchlist'>('portfolio');
  const [marketTab, setMarketTab] = useState<'india' | 'us' | 'currencies' | 'crypto' | 'futures'>('india');

  const chatContainerRef = useRef<HTMLDivElement>(null);
  const streamIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

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

  // Raw static stocks details for mock listings matching user input
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

  // Static high value intelligence insights
  const recentInsights: InsightItem[] = [
    {
      id: 'ins-1',
      ticker: 'RELIANCE',
      type: 'valuation',
      title: 'DCF Intrinsic Mismatch',
      summary: 'Mark\'s WACC valuation models calculate an intrinsic value of ₹3,240. Represents a 10.5% margin of safety relative to market pricing.',
      timestamp: '1 hour ago'
    },
    {
      id: 'ins-2',
      ticker: 'ASIANPAINT',
      type: 'risk',
      title: 'Pledge Indicator Alert',
      summary: 'Promoter pledge ratio ticked up by 2.1% in the recent filings. Financial health rating remains at 8/9, but leverage warrants monitoring.',
      timestamp: '3 hours ago'
    },
    {
      id: 'ins-3',
      ticker: 'TCS',
      type: 'earnings',
      title: 'Operating Margin Premium',
      summary: 'TCS reports EBIT margin of 24.6%, outpacing peers (Infosys at 21.2%). Operating cash flows demonstrate significant pricing power.',
      timestamp: '5 hours ago'
    }
  ];

  // Initialize and load states from localStorage
  useEffect(() => {
    // Clean old AI names from saved messages
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && key.startsWith('prospektlab_messages_')) {
        try {
          const raw = localStorage.getItem(key);
          if (raw) {
            let parsed;
            try {
              parsed = JSON.parse(raw);
            } catch (jsonErr) {
              console.warn(`Corrupted localStorage key "${key}" found. Resetting...`);
              localStorage.removeItem(key);
              continue;
            }
            if (Array.isArray(parsed)) {
              let changed = false;
              const cleaned = parsed.map((msg: any) => {
                if (msg && typeof msg.text === 'string') {
                  let text = msg.text
                    .replace(/ORACLE/g, 'Mark')
                    .replace(/SOLVENT/g, 'Mark')
                    .replace(/AXIS/g, 'Mark')
                    .replace(/QUASAR/g, 'Mark')
                    .replace(/oracle/g, 'Mark')
                    .replace(/solvent/g, 'Mark')
                    .replace(/axis/g, 'Mark')
                    .replace(/quasar/g, 'Mark');
                  
                  if (text.startsWith('Hello! I am') || text.startsWith('AXIS Core ON') || text.startsWith('QUASAR Core ON') || text.startsWith('Mark Core ON')) {
                    text = 'Mark here. Let\'s find where the market got it wrong today.';
                  }
                  if (text !== msg.text) {
                    changed = true;
                  }
                  return { ...msg, text };
                }
                return msg;
              });
              if (changed) {
                localStorage.setItem(key, JSON.stringify(cleaned));
              }
            }
          }
        } catch (e) {
          console.error(e);
        }
      }
    }



    // Load portfolio
    const savedPortfolioRaw = localStorage.getItem('prospektlab_portfolio');
    const parsedPortfolio: PortfolioItem[] = savedPortfolioRaw ? JSON.parse(savedPortfolioRaw) : [];
    setPortfolio(parsedPortfolio);

    // If portfolio is empty, default tab to watchlist
    if (parsedPortfolio.length === 0) {
      setActiveTab('watchlist');
    }

    // Load watchlist symbols
    const savedWatchlistRaw = localStorage.getItem('prospektlab_watchlist');
    const savedWatchlist: string[] = savedWatchlistRaw ? JSON.parse(savedWatchlistRaw) : ['RELIANCE', 'TCS', 'INFY'];
    setWatchlist(savedWatchlist);

    // Build watchlist stocks list from data dictionary
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

    // Load past conversations for AppShell sidebar
    let savedConversations = [];
    try {
      const savedConversationsRaw = localStorage.getItem('prospektlab_conversations');
      savedConversations = savedConversationsRaw ? JSON.parse(savedConversationsRaw) : [];
    } catch (e) {
      console.error(e);
    }
    setConversations(savedConversations);

    // Initialize or bootstrap a default session
    if (savedConversations.length > 0) {
      // Select the first conversation
      const firstConv = savedConversations[0];
      setActiveConversationId(firstConv.id);
      const savedMessagesRaw = localStorage.getItem(`prospektlab_messages_${firstConv.id}`);
      if (savedMessagesRaw) {
        try {
          setMessages(JSON.parse(savedMessagesRaw));
        } catch (e) {
          console.error("Failed to parse saved messages, bootstrapping welcome message", e);
          bootstrapWelcomeMessage(firstConv.id);
        }
      } else {
        bootstrapWelcomeMessage(firstConv.id);
      }
    } else {
      // Create a brand new session
      const newId = 'conv-' + Date.now();
      const newConv = { id: newId, title: 'Equity Analysis Session', date: 'Today' };
      const updatedConvs = [newConv];
      setConversations(updatedConvs);
      localStorage.setItem('prospektlab_conversations', JSON.stringify(updatedConvs));
      setActiveConversationId(newId);
      bootstrapWelcomeMessage(newId);
    }
  }, []);

  // Helper to bootstrap welcome message
  const bootstrapWelcomeMessage = (convId: string) => {
    const welcomeMsgs: Message[] = [
      {
        sender: 'ai',
        text: `Mark here. I don't do hope — I do numbers. Ask me anything about your book, a ticker, or the tape.`
      }
    ];
    setMessages(welcomeMsgs);
    localStorage.setItem(`prospektlab_messages_${convId}`, JSON.stringify(welcomeMsgs));
  };

  // Scroll to bottom of chat container when messages or thinking state change
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [messages.length, isThinking]);

  // === LIVE TICKER SIMULATION (Google Finance style) ===
  // Slightly moves prices + extends sparklines every few seconds for the active tab
  useEffect(() => {
    const interval = setInterval(() => {
      setLiveIndexData(prev => {
        const currentList = prev[marketTab];
        if (!currentList) return prev;

        const updated = currentList.map((item) => {
          // Only tick 1-2 random cards per cycle for natural feel
          if (Math.random() > 0.55) return item;

          const lastPrice = item.sparkData[item.sparkData.length - 1];
          // Small realistic tick (0.08% - 0.35%)
          const tick = lastPrice * (0.0008 + Math.random() * 0.0027) * (Math.random() > 0.5 ? 1 : -1);
          const newPrice = Math.max(0.01, lastPrice + tick);

          // Keep last 13 points
          const newSpark = [...item.sparkData.slice(-12), parseFloat(newPrice.toFixed(2))];

          // Recompute change from first point in window
          const base = newSpark[0];
          const newChangePct = ((newPrice - base) / base) * 100;
          const newChange = `(${newChangePct >= 0 ? '+' : ''}${(newPrice - base).toFixed(2)})`;

          // Format display value
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

  // Calculations for total portfolio summary NAV
  const computedPortfolioDetails = portfolio.map(item => {
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

  // Donut chart calculations for sector breakdown
  const sectorAllocations = portfolio.reduce((acc, curr) => {
    const currentValue = curr.qty * curr.current;
    acc[curr.sector] = (acc[curr.sector] || 0) + currentValue;
    return acc;
  }, {} as Record<string, number>);

  const sectorChartData = {
    labels: Object.keys(sectorAllocations),
    data: Object.values(sectorAllocations)
  };

  // Simulation loop for agent streaming steps (mimics real SSE events)
  const runAgentStreamMock = (message: string, depth: 'chat' | 'standard' | 'deep', onComplete: (rich: any, replyText: string) => void) => {
    setThinkingEvents([]);
    setIsThinking(true);

    const isCompare = message.toLowerCase().includes('compare') || message.toLowerCase().includes('vs');
    const isValuation = message.toLowerCase().includes('valuation') || message.toLowerCase().includes('dcf') || message.toLowerCase().includes('graham');
    
    // Ticker extraction
    let ticker = 'RELIANCE';
    if (message.toUpperCase().includes('TCS')) ticker = 'TCS';
    if (message.toUpperCase().includes('INFY')) ticker = 'INFY';
    if (message.toUpperCase().includes('ASIANPAINT')) ticker = 'ASIANPAINT';
    if (message.toUpperCase().includes('TATAMOTORS')) ticker = 'TATAMOTORS';
    if (message.toUpperCase().includes('HDFCBANK')) ticker = 'HDFCBANK';
    if (message.toUpperCase().includes('ZOMATO')) ticker = 'ZOMATO';
    if (message.toUpperCase().includes('ITC')) ticker = 'ITC';

    const stepsList: Array<{ agent: string; status: 'planned' | 'active' | 'completed'; step: string; details: string }> = [
      { agent: 'intent_router', status: 'planned', step: 'Classifying user query', details: 'Scanning semantics for finance intents' },
      { agent: 'intent_router', status: 'active', step: 'Routing to active nodes', details: `Found entities: ${ticker}. Primary intent: ${isValuation ? 'VALUATION' : isCompare ? 'COMPARISON' : 'SNAPSHOT'}` },
      { agent: 'intent_router', status: 'completed', step: 'Routing hints established', details: 'Forwarding query to cognitive agents' },
      
      { agent: 'market_data_agent', status: 'planned', step: 'Establishing Live feed connect', details: 'Pending network connection' },
      { agent: 'market_data_agent', status: 'active', step: 'Fetching live quote direct from NSE', details: `Connecting to NSE microservice. Retrieving quote for ticker: ${ticker}` },
      { agent: 'market_data_agent', status: 'completed', step: 'NSE quote fetched', details: `Retrieved price for ${ticker}. Trading volume stable.` },
      
      { agent: 'fundamentals_agent', status: 'planned', step: 'Accessing quarterly statement files', details: 'Pending yfinance/filings ingest' },
      { agent: 'fundamentals_agent', status: 'active', step: 'Analyzing quarterly ratios and operating margins', details: `Retrieving yfinance profile metrics. Calculating ROE, PE, and Debt/Equity for ${ticker}` },
      { agent: 'fundamentals_agent', status: 'completed', step: 'Statements parsed successfully', details: `Finished calculation. ROE parsed and margins mapped.` }
    ];

    if (isValuation) {
      stepsList.push(
        { agent: 'valuation_agent', status: 'planned', step: 'Opening DCF formula cells', details: 'Calibrating discount rate' },
        { agent: 'valuation_agent', status: 'active', step: 'Running DCF and Graham mathematical calculations', details: `Running valuation engine. WACC configured at 10.5%. Cash flow growth at 8%.` },
        { agent: 'valuation_agent', status: 'completed', step: 'Valuation bounds complete', details: `Intrinsic value successfully calculated relative to historical metrics.` }
      );
    }

    if (depth === 'deep') {
      stepsList.push(
        { agent: 'news_research_agent', status: 'planned', step: 'Scanning Tavily finance news', details: 'Initializing web search queries' },
        { agent: 'news_research_agent', status: 'active', step: 'Evaluating corporate news and SEBI filing sentiment', details: 'Searching recent press releases, shareholder circulars, and board meetings.' },
        { agent: 'news_research_agent', status: 'completed', step: 'News audit complete', details: 'Sentiment remains largely positive. Minimal volatility flagged.' }
      );
    }

    let currentStepIdx = 0;

    // Store interval in ref so we can stop it from anywhere
    if (streamIntervalRef.current) clearInterval(streamIntervalRef.current);

    streamIntervalRef.current = setInterval(() => {
      if (currentStepIdx < stepsList.length) {
        const item = stepsList[currentStepIdx];
        setThinkingEvents(prev => [
          ...prev,
          {
            seq: currentStepIdx,
            type: 'agent_event',
            timestamp: new Date().toISOString(),
            payload: {
              agent: item.agent,
              status: item.status,
              step: item.step,
              details: item.details
            }
          }
        ]);
        currentStepIdx++;
      } else {
        if (streamIntervalRef.current) {
          clearInterval(streamIntervalRef.current);
          streamIntervalRef.current = null;
        }
        
        let richPayload: any = null;
        let responseText = '';

        if (isValuation) {
          const stockMeta = allStockData[ticker] || { name: ticker, price: '100.00', change: '+0', changePct: 0 };
          const current = parseFloat(stockMeta.price.replace(/,/g, ''));
          const intrinsic = Math.round(current * 1.15); // 15% upside
          const diffPct = ((intrinsic - current) / current) * 100;

          richPayload = {
            mode: 'valuation_insights',
            title: `Intrinsic Valuation Memo: ${ticker}`,
            subtitle: 'Institutional DCF & Graham analysis models.',
            primary_entity: {
              label: stockMeta.name,
              ticker: ticker,
              current_price: current,
              change_pct: stockMeta.changePct,
              description: 'DCF Intrinsic calculation model.'
            },
            metric_cards: [
              { label: 'Intrinsic Value (DCF)', value: `₹${intrinsic.toLocaleString('en-IN')}`, sub_value: `${diffPct >= 0 ? '+' : ''}${diffPct.toFixed(1)}% vs market`, change_type: diffPct >= 0 ? 'positive' : 'negative' },
              { label: 'Discount Rate (WACC)', value: '10.5%', sub_value: 'Conservative standard' },
              { label: 'Graham Value', value: `₹${(intrinsic * 0.9).toFixed(0)}`, sub_value: 'Based on EPS growth' }
            ],
            charts: [
              {
                id: 'chart-1',
                kind: 'area',
                title: 'Projected Free Cash Flow',
                x_labels: ['FY25 (E)', 'FY26 (E)', 'FY27 (E)', 'FY28 (E)', 'FY29 (E)'],
                series: [{ name: 'FCF', values: [12000, 13100, 14200, 15500, 16900] }],
                y_unit: 'Cr'
              }
            ],
            data_sources: [{ label: 'NSE India' }, { label: 'yfinance' }, { label: 'Valuation Engine' }],
            disclaimer: 'Calculated using static projection methods. Verify cash flows prior to entering capital.'
          };

          responseText = `Mark's math: fair value on **${ticker}** is **₹${intrinsic.toLocaleString('en-IN')}**. Tape is **${diffPct.toFixed(1)}%** off. That's not opinion — that's arithmetic. Conservative band sits at **₹${(intrinsic * 0.9).toFixed(0)}**.`;
        } else if (isCompare) {
          richPayload = {
            mode: 'comparison_insights',
            title: 'Side-by-Side Comparative Audit',
            subtitle: 'Financial statements comparison.',
            comparison_rows: [
              { metric: 'Operating Margin (EBIT)', primary_value: '24.6%', secondary_value: '21.2%', winner: 'primary' },
              { metric: 'Return on Equity (ROE)', primary_value: '28.4%', secondary_value: '22.1%', winner: 'primary' },
              { metric: 'Debt to Equity', primary_value: '0.08x', secondary_value: '0.12x', winner: 'primary' },
              { metric: 'Revenue Growth (YoY)', primary_value: '8.4%', secondary_value: '9.2%', winner: 'secondary' }
            ],
            data_sources: [{ label: 'yfinance' }, { label: 'Fundamentals Server' }]
          };

          responseText = `TCS prints **24.6%** operating margin, Infosys sits at **21.2%**. That gap is structural pricing power, not noise. Mark owns the wider moat nine times out of ten — and so should you.`;
        } else {
          const stockMeta = allStockData[ticker] || { name: ticker, price: '100.00', change: '+0', changePct: 0 };
          const current = parseFloat(stockMeta.price.replace(/,/g, ''));
          
          richPayload = {
            mode: 'financial_snapshot',
            title: `Corporate Pulse: ${ticker}`,
            subtitle: 'Standard financial snapshot profile.',
            primary_entity: {
              label: stockMeta.name,
              ticker: ticker,
              current_price: current,
              change_pct: stockMeta.changePct,
              description: `${ticker} financial overview.`
            },
            metric_cards: [
              { label: 'Market Cap', value: ticker === 'TCS' ? '₹14.2L Cr' : ticker === 'RELIANCE' ? '₹19.8L Cr' : '₹2.7L Cr', sub_value: 'Index Heavyweight' },
              { label: 'P/E Ratio', value: ticker === 'TCS' ? '28.2x' : ticker === 'ASIANPAINT' ? '68.2x' : '22.5x', sub_value: 'Trailing 12 Months' },
              { label: 'ROE', value: ticker === 'TCS' ? '28.4%' : '18.2%', sub_value: 'Sustained capital efficiency', change_type: 'positive' }
            ],
            strengths_risks: [
              {
                entity_label: ticker,
                strengths: ['Sustained high capital returns (ROE > 18%)', 'Zero long-term debt liabilities'],
                risks: ['Higher comparative entry PE valuation', 'Sector discretionary spending delays']
              }
            ],
            headlines: [
              { title: `${ticker} announces quarterly dividend distribution`, source: 'BSE India', published: '2 days ago' },
              { title: `Analysts upgrade ${ticker} to Outperform rating`, source: 'Economic Times', published: '5 days ago' }
            ]
          };

          responseText = `Quick read on **${ticker}**: ROE at **${ticker === 'TCS' ? '28.4%' : '18.2%'}**. Balance sheet is clean. PE is rich — pay for quality, but know what you're paying.`;
        }

        setIsThinking(false);
        onComplete(richPayload, responseText);
      }
    }, 350);
  };

  const handleSendMessage = (message: string, depth: 'chat' | 'standard' | 'deep' = 'standard') => {
    if (!message.trim() || isThinking || !activeConversationId) return;

    // Append User message to bubble thread
    const userMsg: Message = { sender: 'user', text: message, depth };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    localStorage.setItem(`prospektlab_messages_${activeConversationId}`, JSON.stringify(updatedMessages));

    // Update conversation title based on user message if it was a default title
    const activeConv = conversations.find(c => c.id === activeConversationId);
    if (activeConv && (activeConv.title === 'Equity Analysis Session' || activeConv.title.startsWith('Analyze '))) {
      const cleanTitle = message.length > 28 ? message.substring(0, 28) + '...' : message;
      const updatedConvs = conversations.map(c => c.id === activeConversationId ? { ...c, title: cleanTitle } : c);
      setConversations(updatedConvs);
      localStorage.setItem('prospektlab_conversations', JSON.stringify(updatedConvs));
    }

    // Run real-time agent scan mock loop
    const t0 = performance.now();
    runAgentStreamMock(message, depth, (richPayload, replyText) => {
      const elapsed = Math.round(performance.now() - t0);
      
      const aiResponse: Message = {
        sender: 'ai',
        text: replyText,
        richData: richPayload,
        depth: depth,
        elapsedMs: elapsed
      };
      
      setMessages(prev => {
        const finalMessages = [...prev, aiResponse];
        localStorage.setItem(`prospektlab_messages_${activeConversationId}`, JSON.stringify(finalMessages));
        return finalMessages;
      });
    });
  };

    // Switch Conversation session
    const handleSelectConversation = (id: string) => {
      if (isThinking) return;
      setActiveConversationId(id);
      const savedMessagesRaw = localStorage.getItem(`prospektlab_messages_${id}`);
      if (savedMessagesRaw) {
        try {
          setMessages(JSON.parse(savedMessagesRaw));
        } catch (e) {
          console.error("Failed to parse saved messages", e);
          bootstrapWelcomeMessage(id);
        }
      } else {
        bootstrapWelcomeMessage(id);
      }
    };

  // Start new Conversation session
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

  // Delete Conversation session
  const handleDeleteConversation = (id: string) => {
    if (isThinking && activeConversationId === id) return;
    const updated = conversations.filter(c => c.id !== id);
    setConversations(updated);
    localStorage.setItem('prospektlab_conversations', JSON.stringify(updated));
    localStorage.removeItem(`prospektlab_messages_${id}`);

    // If deleted the active one, pick next or create one
    if (activeConversationId === id) {
      if (updated.length > 0) {
        const firstConv = updated[0];
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
        // Create a brand new session
        const newId = 'conv-' + Date.now();
        const newConv = { id: newId, title: 'Equity Analysis Session', date: 'Today' };
        const updatedConvs = [newConv];
        setConversations(updatedConvs);
        localStorage.setItem('prospektlab_conversations', JSON.stringify(updatedConvs));
        setActiveConversationId(newId);
        bootstrapWelcomeMessage(newId);
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
    handleSendMessage(`Analyze ${symbol} fundamentals and metrics.`, 'standard');
  };

  const handleAddStock = (symbol: string) => {
    if (watchlist.includes(symbol)) return;
    const updated = [...watchlist, symbol];
    setWatchlist(updated);
    localStorage.setItem('prospektlab_watchlist', JSON.stringify(updated));

    // Update stocks list
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

  // Stop button handler
  const handleStopGeneration = () => {
    if (streamIntervalRef.current) {
      clearInterval(streamIntervalRef.current);
      streamIntervalRef.current = null;
    }
    setIsThinking(false);
    setThinkingEvents([]);

    const stopMsg: Message = { sender: 'ai', text: '_You stopped the analysis._' };
    setMessages(prev => {
      const updated = [...prev, stopMsg];
      if (activeConversationId) {
        localStorage.setItem(`prospektlab_messages_${activeConversationId}`, JSON.stringify(updated));
      }
      return updated;
    });
  };

  const handleRemoveStock = (symbol: string) => {
    const updated = watchlist.filter(s => s !== symbol);
    setWatchlist(updated);
    localStorage.setItem('prospektlab_watchlist', JSON.stringify(updated));
    setWatchlistStocks(watchlistStocks.filter(s => s.symbol !== symbol));
  };

  // Personalized chat suggestions — Mark's voice
  const suggestions = portfolio.length > 0
    ? [
        `What's the tape telling us today?`,
        `Why is ${portfolio[0]?.symbol || 'my top holding'} moving against me?`,
        `Where's the hidden risk in my portfolio?`,
      ]
    : [
        `What's moving the Nifty right now?`,
        `Is this a dip or a trap?`,
        `Give me the bull case on Tata Motors.`,
      ];

  const hasEngaged = messages.length > 1;
  const briefingTime = new Date().getHours();
  const timeGreeting = briefingTime < 12 ? 'Good morning' : briefingTime < 17 ? 'Good afternoon' : 'Good evening';
  const username = (localStorage.getItem('prospektlab_username') || 'analyst').toLowerCase();

  const activeIndices = liveIndexData[marketTab] || liveIndexData.india;

  // AI-generated market summary (mock — would be live in prod)
  const marketSummary = {
    headline: 'Indian markets open red as global cues weigh on sentiment',
    body: 'The Nifty 50 and SENSEX opened in the red before staging a marginal recovery to trade flat in early hours. Market sentiment is dampened by overnight weakness in US tech and a stronger dollar. Energy and Banking are the worst performers; IT held flat on a strong TCS print.',
    sourcesCount: 4,
  };

  const insightTypeBadgeClass = (type: string) =>
    type === 'valuation' ? 'insight-row-type-valuation' :
    type === 'risk' ? 'insight-row-type-risk' :
    'insight-row-type-earnings';

  // ─── Realistic 5-year daily price series for the primary chart ─────
  // Deterministic seeded walk so the chart looks the same on every render
  const primaryChartData = (() => {
    const days = 1260; // ~5 years of trading days
    const labels: string[] = [];
    const values: number[] = [];
    const today = new Date();
    let price = 17500;
    // Simple seeded PRNG so output is stable
    let seed = 42;
    const rand = () => {
      seed = (seed * 9301 + 49297) % 233280;
      return seed / 233280;
    };
    for (let i = days - 1; i >= 0; i--) {
      const d = new Date(today);
      d.setDate(today.getDate() - i);
      // Skip weekends
      if (d.getDay() === 0 || d.getDay() === 6) continue;
      const drift = 0.00038;          // ~10% annual drift
      const vol = 0.011;              // ~1.1% daily vol
      const shock = (rand() - 0.5) * 2 * vol;
      price = price * (1 + drift + shock);
      labels.push(d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' }));
      values.push(Math.round(price * 100) / 100);
    }
    // Anchor the last point to current Nifty
    if (values.length > 0) values[values.length - 1] = 23939.45;
    return { labels, values };
  })();

  // ─── Portfolio-context derived stats (the unique value) ────────────
  const portfolioStats = (() => {
    if (computedPortfolioDetails.length === 0) return null;
    const sorted = [...computedPortfolioDetails].sort((a, b) => b.pnlPct - a.pnlPct);
    const best = sorted[0];
    const worst = sorted[sorted.length - 1];
    const winners = computedPortfolioDetails.filter(p => p.pnl > 0).length;
    const losers = computedPortfolioDetails.filter(p => p.pnl < 0).length;
    const sectorMap = new Map<string, number>();
    computedPortfolioDetails.forEach(p => sectorMap.set(p.sector, (sectorMap.get(p.sector) || 0) + p.currentValue));
    const totalVal = computedPortfolioDetails.reduce((s, p) => s + p.currentValue, 0);
    const sectors = Array.from(sectorMap.entries()).sort((a, b) => b[1] - a[1]);
    const topSector = sectors[0];
    const topSectorPct = topSector ? (topSector[1] / totalVal) * 100 : 0;
    // Beta (mock): roughly 1.0–1.2 based on portfolio composition
    const beta = 0.95 + (computedPortfolioDetails.length * 0.02);
    return { best, worst, winners, losers, topSector, topSectorPct, beta };
  })();

  // ─── Top Movers (portfolio + watchlist combined) ───────────────────
  const allTrackedStocks = [...portfolio, ...watchlistStocks.filter(w => !portfolio.find(p => p.symbol === w.symbol)).map(w => ({
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
      isOwned: portfolio.some(p => p.symbol === s.symbol),
    };
  });

  const gainers = [...stocksWithChange].filter(s => s.changePct > 0).sort((a, b) => b.changePct - a.changePct).slice(0, 4);
  const losers = [...stocksWithChange].filter(s => s.changePct < 0).sort((a, b) => a.changePct - b.changePct).slice(0, 4);
  const mostActive = [...stocksWithChange].sort((a, b) => Math.abs(b.changePct) - Math.abs(a.changePct)).slice(0, 4);

  // ─── News feed (mock, with Mark's voice on sentiment) ──────────────
  const newsFeed = [
    { id: 'n1', source: 'Mint', time: '12 min ago', headline: 'Tata Group stocks surge ahead of strategic board meeting', sentiment: 'bullish', tickers: ['TATAMOTORS'] },
    { id: 'n2', source: 'Bloomberg', time: '38 min ago', headline: 'Rupee retreats from recent highs amid importer dollar demand', sentiment: 'neutral', tickers: [] },
    { id: 'n3', source: 'ET Markets', time: '1 hour ago', headline: 'TCS posts record EBIT margin; analysts lift target prices', sentiment: 'bullish', tickers: ['TCS'] },
    { id: 'n4', source: 'Reuters', time: '2 hours ago', headline: 'Promoter pledge in Asian Paints ticks up — what it means', sentiment: 'bearish', tickers: ['ASIANPAINT'] },
    { id: 'n5', source: 'Moneycontrol', time: '3 hours ago', headline: 'Nifty Bank breaks key support — institutional positioning shifts', sentiment: 'bearish', tickers: [] },
  ];

  // ─── Upcoming earnings (focused on user's tracked tickers) ─────────
  const upcomingEarnings = [
    { date: 'TUE 28', ticker: 'INFY', name: 'Infosys', period: 'Fiscal Q3 2026', epsEst: '17.20', revEst: '38.2K Cr', when: '1:30 PM IST' },
    { date: 'WED 29', ticker: 'RELIANCE', name: 'Reliance Industries', period: 'Fiscal Q3 2026', epsEst: '22.10', revEst: '2.31L Cr', when: '5:00 PM IST' },
    { date: 'THU 30', ticker: 'HDFCBANK', name: 'HDFC Bank', period: 'Fiscal Q3 2026', epsEst: '21.80', revEst: '64.8K Cr', when: '10:00 AM IST' },
    { date: 'FRI 31', ticker: 'TATAMOTORS', name: 'Tata Motors', period: 'Fiscal Q3 2026', epsEst: '13.40', revEst: '1.18L Cr', when: '4:30 PM IST' },
  ];

  const sentimentColor = (s: string) =>
    s === 'bullish' ? 'var(--profit)' : s === 'bearish' ? 'var(--loss)' : 'var(--text-secondary)';
  const sentimentLabel = (s: string) =>
    s === 'bullish' ? 'BULLISH' : s === 'bearish' ? 'BEARISH' : 'NEUTRAL';

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
      <div className="workbench">
        {/* â•â•â•â•â•â•â•â• LEFT: DATA DASHBOARD â•â•â•â•â•â•â•â• */}
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

          {/* Primary Interactive Chart — full-fidelity daily data so every range works */}
          <div className="data-panel" style={{ marginBottom: 36 }}>
            <InteractiveChart
              labels={primaryChartData.labels}
              data={primaryChartData.values}
              title="NIFTY 50 — Interactive"
              unit=""
              height={300}
            />
            <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>Hover for exact values · click any range above</span>
              <span style={{ marginLeft: 'auto', color: 'var(--accent-cyan)', cursor: 'pointer' }}
                onClick={() => handleSendMessage('Walk me through the current NIFTY 50 move — what is the story today?', 'standard')}
              >
                Ask Mark about this move →
              </span>
            </div>
          </div>

          {/* ═══ MARK'S READ ON YOUR PORTFOLIO — unique stats nobody else shows ═══ */}
          {portfolioStats && (
            <>
              <div className="section-head">
                <div className="section-title">Mark's read on your book</div>
                <span className="section-sublabel">PERSONAL • {portfolio.length} POSITIONS</span>
              </div>
              <div className="stats-grid">
                <div className="stat-tile">
                  <div className="stat-tile-label">TODAY'S BEST</div>
                  <div className="stat-tile-value" style={{ color: 'var(--profit)' }}>
                    {portfolioStats.best.symbol}
                  </div>
                  <div className="stat-tile-sub">
                    +{Math.abs(portfolioStats.best.pnlPct).toFixed(2)}% · ₹{Math.abs(portfolioStats.best.pnl).toLocaleString('en-IN')}
                  </div>
                </div>
                <div className="stat-tile">
                  <div className="stat-tile-label">TODAY'S WORST</div>
                  <div className="stat-tile-value" style={{ color: 'var(--loss)' }}>
                    {portfolioStats.worst.symbol}
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
                  <div className="stat-tile-label">CONCENTRATION</div>
                  <div className="stat-tile-value">
                    {portfolioStats.topSectorPct.toFixed(0)}<span style={{ fontSize: 16, color: 'var(--text-muted)' }}>%</span>
                  </div>
                  <div className="stat-tile-sub">
                    in {portfolioStats.topSector?.[0] || '—'}{portfolioStats.topSectorPct > 40 ? ' · overweight' : ''}
                  </div>
                </div>
                <div className="stat-tile">
                  <div className="stat-tile-label">PORTFOLIO BETA</div>
                  <div className="stat-tile-value">{portfolioStats.beta.toFixed(2)}</div>
                  <div className="stat-tile-sub">
                    {portfolioStats.beta > 1.1 ? 'Moves more than Nifty' : portfolioStats.beta < 0.9 ? 'Calmer than Nifty' : 'In line with Nifty'}
                  </div>
                </div>
                <div className="stat-tile stat-tile-cta" onClick={() => handleSendMessage('Audit my portfolio — what is the single biggest risk hiding in my book right now?', 'deep')}>
                  <div className="stat-tile-label" style={{ color: 'var(--accent-cyan)' }}>ASK MARK</div>
                  <div style={{ fontSize: 13, lineHeight: 1.4, marginTop: 6, color: 'var(--text-primary)' }}>
                    "What's the one thing I'm missing about my book today?"
                  </div>
                </div>
              </div>
            </>
          )}

          {/* ═══ TOP MOVERS (your tracked universe) ═══ */}
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
              {losers.length === 0 ? (
                <div className="movers-empty">All green. Enjoy it while it lasts.</div>
              ) : losers.map(s => (
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
            <span className="section-sublabel">MARK'S BRIEF • {marketSummary.sourcesCount} sources</span>
          </div>

          <div className="summary-card">
            <div className="summary-card-headline">{marketSummary.headline}</div>
            <div className="summary-card-body">{marketSummary.body}</div>
            <button
              className="summary-cta"
              onClick={() => handleSendMessage('Dive deeper on today\'s market moves — what should I actually do about my portfolio?', 'deep')}
            >
              <Sparkles size={13} /> Have Mark dig into it
            </button>
          </div>

          {/* Portfolio + Watchlist + Allocation */}
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
                <button className="data-panel-link" onClick={() => navigate('/onboarding')}>Manage â†’</button>
              </div>

              {activeTab === 'portfolio' ? (
                portfolio.length > 0 ? (
                  <PortfolioTable portfolio={portfolio} onSelectStock={handleSelectStock} />
                ) : (
                  <div style={{ padding: 32, textAlign: 'center', fontSize: 13, color: 'var(--text-secondary)' }}>
                    No holdings yet.{' '}
                    <button
                      onClick={() => navigate('/onboarding')}
                      style={{ color: 'var(--accent-cyan)', background: 'none', border: 'none', cursor: 'pointer', fontWeight: 600 }}
                    >
                      Import portfolio â†’
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

          {portfolio.length > 0 && sectorChartData.labels.length > 0 && (
            <div className="data-panel" style={{ maxWidth: 480 }}>
              <div className="data-panel-head">
                <div className="data-panel-title">Sector allocation</div>
                <button
                  className="data-panel-link"
                  onClick={() => handleSendMessage('Audit my sector allocation — where am I over- or under-exposed?', 'standard')}
                >
                  Audit →
                </button>
              </div>
              <DonutChart labels={sectorChartData.labels} data={sectorChartData.data} title="" />
            </div>
          )}

          {/* ═══ NEWS FEED — finance news with Mark's sentiment read ═══ */}
          <div className="section-head" style={{ marginTop: 24 }}>
            <div className="section-title">What's moving the tape</div>
            <span className="section-sublabel">LIVE NEWS · MARK'S SENTIMENT</span>
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

          {/* ═══ UPCOMING EARNINGS — focused on your tracked tickers ═══ */}
          <div className="section-head" style={{ marginTop: 24 }}>
            <div className="section-title">Upcoming earnings</div>
            <span className="section-sublabel">YOUR UNIVERSE · NEXT 7 DAYS</span>
          </div>
          <div className="earnings-list">
            {upcomingEarnings.map(e => {
              const isOwned = portfolio.some(p => p.symbol === e.ticker);
              return (
                <div key={e.ticker} className="earnings-row" onClick={() => handleSendMessage(`What should I expect from ${e.ticker}'s upcoming earnings?`, 'standard')}>
                  <div className="earnings-date">
                    <div className="earnings-day">{e.date.split(' ')[0]}</div>
                    <div className="earnings-num">{e.date.split(' ')[1]}</div>
                  </div>
                  <div className="earnings-info">
                    <div className="earnings-name">
                      {e.name}
                      {isOwned && <span className="owned-badge">OWNED</span>}
                    </div>
                    <div className="earnings-when">{e.when}</div>
                  </div>
                  <div className="earnings-period">{e.period}</div>
                  <div className="earnings-metric">
                    <div className="earnings-metric-label">EPS est.</div>
                    <div className="earnings-metric-val">₹{e.epsEst}</div>
                  </div>
                  <div className="earnings-metric">
                    <div className="earnings-metric-label">Rev est.</div>
                    <div className="earnings-metric-val">{e.revEst}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* â•â•â•â•â•â•â•â• RIGHT: CHAT RAIL â•â•â•â•â•â•â•â• */}
        <div className="workbench-chat">
          <div className="chat-rail-head">
            <div className="chat-rail-title">Mark</div>
            <div className="chat-rail-actions">
               <button className="chat-rail-iconbtn" title="New session" onClick={handleNewConversation}>
                 <Edit3 size={16} color="#94a3b8" strokeWidth={2} />
               </button>
               <button className="chat-rail-iconbtn" title="History">
                 <History size={16} color="#94a3b8" strokeWidth={2} />
               </button>
               <button className="chat-rail-iconbtn" title="Expand">
                 <Maximize2 size={16} color="#94a3b8" strokeWidth={2} />
               </button>
            </div>
          </div>

          <div className="chat-rail-body" ref={chatContainerRef}>
            {!hasEngaged ? (
              <>
                <div className="chat-rail-greeting">
                  {timeGreeting}, {username}. I'm Mark — your market read, unfiltered. What are we hunting today?
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
                  // Hide auto-bootstrap welcome message — greeting card handles intro
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
              Mark • every NSE name • Quick / Standard / Deep • Esc to stop
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
};

export default Dashboard;

export interface PortfolioItem {
  symbol: string;
  name: string;
  qty: number;
  avgCost: number;
  current: number;
  sector: string;
  assetClass?: string;
  dayChangePct?: number;
}

export interface ComputedPortfolioItem extends PortfolioItem {
  currentValue: number;
  pnl: number;
  pnlPct: number;
}

export interface NewsFeedItem {
  id: string;
  source: string;
  time: string;
  headline: string;
  description: string;
  sentiment: 'bullish' | 'bearish' | 'neutral';
  tickers: string[];
  url: string;
  image: string;
  sourceCount: number;
}

export interface ResearchTitleItem {
  slug: string;
  title: string;
  content_type: string;
  ago: string;
  public_url: string;
  image_path?: string;
  generated_at?: string;
}

export interface MarketMoverItem {
  symbol: string;
  name: string;
  price: number;
  changePct: number;
}

export interface PortfolioSummary {
  totalCost: number;
  totalValue: number;
  totalPnL: number;
}

export interface PortfolioPulseItem extends ComputedPortfolioItem {
  movePct: number;
  moveValue: number;
}

export interface PortfolioPulse {
  label: string;
  aggregateValue: number;
  aggregatePct: number;
  best: PortfolioPulseItem;
  worst: PortfolioPulseItem;
}

export interface PortfolioStats {
  best: ComputedPortfolioItem;
  worst: ComputedPortfolioItem;
  winners: number;
  losers: number;
  topSector?: [string, number];
  topSectorPct: number;
  beta: number;
  hhi: number;
  var95: number;
}

export interface PortfolioExposure {
  equityValue: number;
  mutualFundValue: number;
  sectorCount: number;
  equityPct: number;
}

export interface CommentaryHighlight {
  label: string;
  value: string;
  tone: 'up' | 'down' | 'neutral';
}

export interface VisibleCommentary {
  commentary: string;
  source: string;
  highlights?: CommentaryHighlight[];
}

export interface OverviewEarningsHero {
  tone: 'reported' | 'upcoming' | 'calendar';
  title: string;
  subtitle: string;
  body: string;
  cta: string;
  href: string;
  metricA: string;
  metricB: string;
  symbol: string;
}

export interface CompareChartData {
  labels: string[];
  portValues: number[];
  benchValues: number[];
}

export interface ChartBreakdown {
  labels: string[];
  data: number[];
}

export interface PortfolioMoverRow {
  symbol: string;
  name: string;
  price: string;
  changePct: number | null;
  isOwned: boolean;
}

export type PortfolioAnalyticsTab = 'mf' | 'risk' | 'stress' | 'corr' | 'tax';
export type HoldingsWorkspaceTab = 'portfolio' | 'watchlist';

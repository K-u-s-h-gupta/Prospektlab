import React from 'react';
import { Activity, ChevronDown, Sparkles, TrendingDown } from 'lucide-react';
import { DonutChart } from '../../components/charts/DonutChart';
import { InteractiveChart } from '../../components/charts/InteractiveChart';
import { PortfolioTable } from '../../components/dashboard/PortfolioTable';
import { WatchlistWorkspace } from '../../components/dashboard/WatchlistWorkspace';
import type { WatchlistStock } from '../../components/dashboard/watchlistTypes';
import type { NewsFeedItem } from './types';
import type {
  ChartBreakdown,
  CompareChartData,
  ComputedPortfolioItem,
  HoldingsWorkspaceTab,
  PortfolioAnalyticsTab,
  PortfolioExposure,
  PortfolioItem,
  PortfolioMoverRow,
  PortfolioStats,
  PortfolioSummary,
  VisibleCommentary,
} from './types';
import { CorrelationHeatmap, DrawdownSparkline, HealthGauge, MetricCard } from './PortfolioWidgets';

interface PortfolioTabContentProps {
  hasPortfolioHoldings: boolean;
  portfolioSummary: PortfolioSummary;
  portfolioTotalReturnPct: number;
  computedPortfolioDetails: ComputedPortfolioItem[];
  portfolioExposure: PortfolioExposure;
  topHolding: ComputedPortfolioItem | null;
  topHoldingWeight: number;
  onResetPortfolio: () => void;
  isResettingPortfolio: boolean;
  benchmarkSelectorRef: React.RefObject<HTMLDivElement>;
  isBenchmarkMenuOpen: boolean;
  onToggleBenchmarkMenu: () => void;
  selectedBenchmark: string;
  onSelectBenchmark: (benchmarkId: string) => void;
  benchmarks: Array<{ id: string; name: string }>;
  compareChartData: CompareChartData;
  benchmarkHistoryLoading: boolean;
  portfolioAnalyticsError: string | null;
  onSuggestQuery: (query: string, depth?: 'standard' | 'deep') => void;
  visiblePortfolioHealth: any;
  visibleCommentary: VisibleCommentary | null;
  portfolioStats: PortfolioStats | null;
  sectorChartData: ChartBreakdown;
  sectorUsesPercent: boolean;
  assetChartData: ChartBreakdown;
  assetUsesPercent: boolean;
  analyticsTab: PortfolioAnalyticsTab;
  onSelectAnalyticsTab: (tab: PortfolioAnalyticsTab) => void;
  portfolioAnalytics: any;
  actionQueue: any[];
  mfAnalytics: any;
  enrichedPortfolio: PortfolioItem[];
  onRunStressTest: (scenario: string, customShockPct?: number) => void;
  stressResult: any;
  stressScenario: string;
  stressShock: number;
  onSetStressShock: (value: number) => void;
  stressLoading: boolean;
  taxSummary: any;
  gainers: PortfolioMoverRow[];
  losersList: PortfolioMoverRow[];
  mostActive: PortfolioMoverRow[];
  onOpenAssetHistory: (symbol: string, name?: string, assetType?: string) => void;
  marketSummary: { headline: string; body: string; sourcesCount: number };
  activeTab: HoldingsWorkspaceTab;
  onSelectWorkspaceTab: (tab: HoldingsWorkspaceTab) => void;
  watchlist: string[];
  watchlistStocks: WatchlistStock[];
  onChangeWatchlistSymbols: (symbols: string[]) => void;
  onSelectStock: (symbol: string, item?: { name?: string; assetClass?: string }) => void;
  onAnalyzeStock: (symbol: string) => void;
  onOpenPortfolioSetup: () => void;
  onNavigate: (href: string) => void;
  portfolioSymbols: string[];
  newsFeed: NewsFeedItem[];
  newsLoading: boolean;
  newsError: string | null;
  onRetryNews: () => void;
  sentimentColor: (sentiment: string) => string;
  sentimentLabel: (sentiment: string) => string;
  fmtINR: (value: any) => string;
  fmtINRWhole: (value: any) => string;
  fmtNum: (value: any, digits?: number, suffix?: string) => string;
}

export const PortfolioTabContent: React.FC<PortfolioTabContentProps> = ({
  hasPortfolioHoldings,
  portfolioSummary,
  portfolioTotalReturnPct,
  computedPortfolioDetails,
  portfolioExposure,
  topHolding,
  topHoldingWeight,
  onResetPortfolio,
  isResettingPortfolio,
  benchmarkSelectorRef,
  isBenchmarkMenuOpen,
  onToggleBenchmarkMenu,
  selectedBenchmark,
  onSelectBenchmark,
  benchmarks,
  compareChartData,
  benchmarkHistoryLoading,
  portfolioAnalyticsError,
  onSuggestQuery,
  visiblePortfolioHealth,
  visibleCommentary,
  portfolioStats,
  sectorChartData,
  sectorUsesPercent,
  assetChartData,
  assetUsesPercent,
  analyticsTab,
  onSelectAnalyticsTab,
  portfolioAnalytics,
  actionQueue,
  mfAnalytics,
  enrichedPortfolio,
  onRunStressTest,
  stressResult,
  stressScenario,
  stressShock,
  onSetStressShock,
  stressLoading,
  taxSummary,
  gainers,
  losersList,
  mostActive,
  onOpenAssetHistory,
  marketSummary,
  activeTab,
  onSelectWorkspaceTab,
  watchlist,
  watchlistStocks,
  onChangeWatchlistSymbols,
  onSelectStock,
  onAnalyzeStock,
  onOpenPortfolioSetup,
  onNavigate,
  portfolioSymbols,
  newsFeed,
  newsLoading,
  newsError,
  onRetryNews,
  sentimentColor,
  sentimentLabel,
  fmtINR,
  fmtINRWhole,
  fmtNum,
}) => {
  if (!hasPortfolioHoldings) {
    return (
      <div className="data-panel" style={{ padding: '28px', display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div className="section-head" style={{ marginBottom: 0 }}>
          <div className="section-title">Set up your portfolio</div>
          <span className="section-sublabel">UPLOAD OR MANUAL ENTRY REQUIRED</span>
        </div>
        <div style={{ color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6 }}>
          No synchronized holdings found for this account. Add holdings to unlock live NAV, allocation, risk analytics, and personalized portfolio insights.
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button type="button" className="portfolio-top-action-btn primary" onClick={onOpenPortfolioSetup}>
            Open onboarding form
          </button>
          <button type="button" className="portfolio-top-action-btn" onClick={() => onNavigate('/onboarding/manual')}>
            Enter manually
          </button>
          <button type="button" className="portfolio-top-action-btn" onClick={() => onNavigate('/onboarding/upload')}>
            Upload statement
          </button>
        </div>
      </div>
    );
  }

  const risk = portfolioAnalytics?.risk || {};
  const rolling = portfolioAnalytics?.rolling_returns || {};
  const drawdowns = portfolioAnalytics?.drawdown_series || [];
  const attribution = portfolioAnalytics?.attribution || {};
  const contributors = attribution.top_contributors || [];
  const detractors = attribution.top_detractors || [];
  const totalMarketValue = Number(portfolioAnalytics?.total_market_value) || 0;
  const varPct = risk.historical_var_pct;
  const cvarPct = risk.cvar_pct;
  const hhiPct = Number(risk.hhi || 0) * 10000;
  const mfHoldings = enrichedPortfolio.filter((item) => item.assetClass === 'Mutual Fund');
  const totalMfValue = mfHoldings.reduce((sum, item) => sum + (item.qty * item.current), 0);
  const backendMfValue = Number(mfAnalytics?.total_mf_value || 0);
  const displayedMfValue = backendMfValue > 0 ? backendMfValue : totalMfValue;
  const weightedTer = Number(mfAnalytics?.aum_weighted_ter_pct || 0);
  const hasWeightedTer = weightedTer > 0;
  const schemeCount = Number.isFinite(Number(mfAnalytics?.scheme_count)) ? Number(mfAnalytics.scheme_count) : mfHoldings.length;
  const categoryBreakdown = mfAnalytics?.category_breakdown || {};
  const amcConcentration = mfAnalytics?.amc_concentration || {};
  const stressScenarios = [
    { key: 'nifty_down_10', label: 'Nifty −10%' },
    { key: 'nifty_down_20', label: 'Nifty −20%' },
    { key: 'nifty_down_30', label: 'Nifty −30%' },
    { key: 'covid_2020', label: '2020 COVID' },
    { key: 'gfc_2008', label: '2008 GFC' },
  ];
  const stressLoss = Number(stressResult?.portfolio_loss_pct);
  const correlationMatrix = portfolioAnalytics?.correlation_matrix;
  const hasCorrelationMatrix = correlationMatrix && correlationMatrix.labels && correlationMatrix.labels.length >= 2;
  const harvest = taxSummary?.harvest;

  return (
    <>
      <div className="portfolio-top-hero">
        <div className="portfolio-top-hero-head">
          <div>
            <div className="portfolio-top-label">Portfolio Value</div>
            <div className="portfolio-top-value">{fmtINRWhole(portfolioSummary.totalValue)}</div>
            <div className={`portfolio-top-change ${portfolioSummary.totalPnL >= 0 ? 'up' : 'down'}`}>
              {portfolioSummary.totalPnL >= 0 ? '+' : ''}{fmtINRWhole(portfolioSummary.totalPnL)} ({portfolioTotalReturnPct.toFixed(2)}%)
            </div>
          </div>
          <div className="portfolio-top-actions">
            <button type="button" className="portfolio-top-action-btn" onClick={onResetPortfolio} disabled={isResettingPortfolio} style={{ padding: '8px 12px', fontSize: 11, borderRadius: 8 }}>
              {isResettingPortfolio ? 'Resetting...' : 'Reset portfolio'}
            </button>
          </div>
        </div>
        <div className="portfolio-top-metrics">
          <div className="portfolio-top-metric"><span>Total Invested</span><strong>{fmtINRWhole(portfolioSummary.totalCost)}</strong></div>
          <div className="portfolio-top-metric"><span>Holdings</span><strong>{computedPortfolioDetails.length}</strong></div>
          <div className="portfolio-top-metric"><span>Sector Spread</span><strong>{portfolioExposure.sectorCount}</strong></div>
          <div className="portfolio-top-metric"><span>Equity Exposure</span><strong>{portfolioExposure.equityPct.toFixed(1)}%</strong></div>
          <div className="portfolio-top-metric"><span>Mutual Fund Value</span><strong>{fmtINRWhole(portfolioExposure.mutualFundValue)}</strong></div>
          <div className="portfolio-top-metric"><span>Top Holding</span><strong>{topHolding ? `${topHolding.symbol} (${topHoldingWeight.toFixed(1)}%)` : 'Not available'}</strong></div>
        </div>
      </div>

      <div className="data-panel" style={{ marginBottom: 36 }}>
        <div className="chart-panel-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%' }}>Comparative Returns (Indexed)</span>
          <div className="chart-benchmark-selector" style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }} ref={benchmarkSelectorRef}>
            <span className="benchmark-selector-label" style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>VS BENCHMARK:</span>
            <div className="benchmark-select">
              <button type="button" className="benchmark-select-trigger" aria-haspopup="listbox" aria-expanded={isBenchmarkMenuOpen} onClick={onToggleBenchmarkMenu}>
                <span>{benchmarks.find((bench) => bench.id === selectedBenchmark)?.name || 'Nifty 50'}</span>
                <ChevronDown size={13} className={isBenchmarkMenuOpen ? 'benchmark-select-chevron open' : 'benchmark-select-chevron'} />
              </button>
              {isBenchmarkMenuOpen && (
                <div className="benchmark-select-menu" role="listbox" aria-label="Benchmark selector">
                  {benchmarks.map((bench) => (
                    <button key={bench.id} type="button" role="option" aria-selected={selectedBenchmark === bench.id} className={selectedBenchmark === bench.id ? 'benchmark-select-option active' : 'benchmark-select-option'} onClick={() => onSelectBenchmark(bench.id)}>
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
            title={compareChartData.portValues.length > 1 ? 'Your Portfolio (base = 100)' : `${benchmarks.find((bench) => bench.id === selectedBenchmark)?.name || 'Benchmark'} (base = 100)`}
            unit=""
            comparisonData={compareChartData.portValues.length > 1 && compareChartData.benchValues.length > 1 ? compareChartData.benchValues : undefined}
            comparisonTitle={benchmarks.find((bench) => bench.id === selectedBenchmark)?.name || 'Benchmark'}
            height={300}
          />
        ) : (
          <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
            {benchmarkHistoryLoading ? 'Loading benchmark history...' : portfolioAnalyticsError || 'Syncing portfolio history from backend...'}
          </div>
        )}

        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span>{compareChartData.portValues.length > 1 ? 'Comparison is indexed to 100 using live backend portfolio analytics' : compareChartData.labels.length > 0 ? 'Benchmark history shown while portfolio return history builds' : portfolioAnalyticsError || 'Portfolio history is syncing; local risk panels are available below'}</span>
          {compareChartData.labels.length > 0 && (
            <span style={{ marginLeft: 'auto', color: 'var(--accent-cyan)', cursor: 'pointer' }} onClick={() => onSuggestQuery(`Explain how my portfolio is performing compared to ${selectedBenchmark}.`, 'standard')}>
              Analyse return spread →
            </span>
          )}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16, marginBottom: 28 }}>
        <div className="data-panel">
          <div className="data-panel-head">
            <div className="data-panel-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Activity size={15} color="var(--accent-cyan)" /> Portfolio Health</div>
            <span className="section-sublabel">LIVE SCORE</span>
          </div>
          {visiblePortfolioHealth?.score != null ? (
            <>
              <HealthGauge health={visiblePortfolioHealth} />
              {visiblePortfolioHealth.source === 'local-fallback' && <div style={{ marginTop: 10, fontSize: 11, color: 'var(--text-muted)' }}>Local score shown while backend price history finishes syncing.</div>}
            </>
          ) : (
            <div style={{ padding: '24px 8px', color: 'var(--text-muted)', fontSize: 12 }}>Building your health score from live price history…</div>
          )}
        </div>
        <div className="data-panel">
          <div className="data-panel-head">
            <div className="data-panel-title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}><Sparkles size={15} color="var(--accent-cyan)" /> Arthik's daily read</div>
            <span className="section-sublabel">{visibleCommentary?.source === 'llm' ? 'AI' : visibleCommentary?.source === 'local' ? 'LOCAL' : 'AUTO'} • {new Date().toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}</span>
          </div>
          {visibleCommentary?.commentary ? (
            <>
              <div style={{ fontSize: 13.5, lineHeight: 1.6, color: 'var(--text-primary)' }}>{visibleCommentary.commentary}</div>
              {Array.isArray(visibleCommentary.highlights) && visibleCommentary.highlights.length > 0 && (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
                  {visibleCommentary.highlights.map((highlight, index) => (
                    <div key={index} style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: '6px 10px' }}>
                      <div style={{ fontSize: 9.5, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: 0.3 }}>{highlight.label}</div>
                      <div style={{ fontSize: 12.5, fontWeight: 700, fontFamily: 'var(--font-mono)', color: highlight.tone === 'up' ? 'var(--profit)' : highlight.tone === 'down' ? 'var(--loss)' : 'var(--text-primary)' }}>{highlight.value}</div>
                    </div>
                  ))}
                </div>
              )}
              <button className="summary-cta" style={{ marginTop: 14 }} onClick={() => onSuggestQuery("Give me deeper read on my portfolio today — what should I actually do about it?", 'deep')}>
                <Sparkles size={13} /> Go deeper with Arthik
              </button>
            </>
          ) : (
            <div style={{ padding: '20px 8px', color: 'var(--text-muted)', fontSize: 12 }}>Arthik is reading your book…</div>
          )}
        </div>
      </div>

      {portfolioStats && (
        <>
          <div className="section-head">
            <div className="section-title">Arthik's read on your book</div>
            <span className="section-sublabel">PERSONAL • {computedPortfolioDetails.length} POSITIONS</span>
          </div>
          <div className="stats-grid">
            {computedPortfolioDetails.length > 1 ? (
              <>
                <div className="stat-tile">
                  <div className="stat-tile-label">TODAY'S BEST</div>
                  <div className="stat-tile-value" style={{ color: 'var(--profit)', fontSize: '13px', fontFamily: 'var(--font-sans)', fontWeight: 700, wordBreak: 'break-word', minHeight: '34px', display: 'flex', alignItems: 'center' }}>{portfolioStats.best.name}</div>
                  <div className="stat-tile-sub">+{Math.abs(portfolioStats.best.pnlPct).toFixed(2)}% · ₹{Math.abs(portfolioStats.best.pnl).toLocaleString('en-IN')}</div>
                </div>
                <div className="stat-tile">
                  <div className="stat-tile-label">TODAY'S WORST</div>
                  <div className="stat-tile-value" style={{ color: 'var(--loss)', fontSize: '13px', fontFamily: 'var(--font-sans)', fontWeight: 700, wordBreak: 'break-word', minHeight: '34px', display: 'flex', alignItems: 'center' }}>{portfolioStats.worst.name}</div>
                  <div className="stat-tile-sub">{portfolioStats.worst.pnlPct.toFixed(2)}% · ₹{portfolioStats.worst.pnl.toLocaleString('en-IN')}</div>
                </div>
              </>
            ) : (
              <div className="stat-tile">
                <div className="stat-tile-label">YOUR HOLDING</div>
                <div className="stat-tile-value" style={{ color: 'var(--accent-cyan)', fontSize: '13px', fontFamily: 'var(--font-sans)', fontWeight: 700, wordBreak: 'break-word', minHeight: '34px', display: 'flex', alignItems: 'center' }}>{portfolioStats.best.name}</div>
                <div className="stat-tile-sub">{portfolioStats.best.pnlPct >= 0 ? '+' : ''}{portfolioStats.best.pnlPct.toFixed(2)}% · ₹{Math.abs(portfolioStats.best.pnl).toLocaleString('en-IN')}</div>
              </div>
            )}
            <div className="stat-tile">
              <div className="stat-tile-label">WIN / LOSS RATIO</div>
              <div className="stat-tile-value">{portfolioStats.winners}<span style={{ color: 'var(--text-muted)' }}> / </span>{portfolioStats.losers}</div>
              <div className="stat-tile-sub" style={{ color: portfolioStats.winners >= portfolioStats.losers ? 'var(--profit)' : 'var(--loss)' }}>{portfolioStats.winners >= portfolioStats.losers ? 'More green than red' : 'More red than green'}</div>
            </div>
            <div className="stat-tile">
              <div className="stat-tile-label">PORTFOLIO BETA</div>
              <div className="stat-tile-value">{portfolioStats.beta.toFixed(2)}</div>
              <div className="stat-tile-sub">{portfolioStats.beta > 1.1 ? 'High systematic risk' : portfolioStats.beta < 0.9 ? 'Calmer than benchmark' : 'In line with Nifty'}</div>
            </div>
            <div className="stat-tile">
              <div className="stat-tile-label">Value at Risk (95%)</div>
              <div className="stat-tile-value" style={{ color: 'var(--loss)' }}>₹{portfolioStats.var95.toFixed(0)}</div>
              <div className="stat-tile-sub">Estimated 1-day max loss</div>
            </div>
            <div className="stat-tile stat-tile-cta" onClick={() => onSuggestQuery('Audit my portfolio — what is single biggest risk hiding in my book right now?', 'deep')}>
              <div className="stat-tile-label" style={{ color: 'var(--accent-cyan)' }}>ASK ARTHIK</div>
              <div style={{ fontSize: 13, lineHeight: 1.4, marginTop: 6, color: 'var(--text-primary)' }}>
                "What's one thing I'm missing about my book today?"
              </div>
            </div>
          </div>
        </>
      )}

      {sectorChartData.labels.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px', marginBottom: '28px' }}>
          <div className="data-panel">
            <div className="data-panel-head">
              <div className="data-panel-title" style={{ fontSize: '13px', fontWeight: 600 }}>Sector Allocation</div>
              <button className="data-panel-link" onClick={() => onSuggestQuery('Audit my sector allocation — where am I over- or under-exposed?', 'standard')}>Audit →</button>
            </div>
            <DonutChart labels={sectorChartData.labels} data={sectorChartData.data} title="" valueKind={sectorUsesPercent ? 'percent' : 'currency'} unit={sectorUsesPercent ? '%' : undefined} />
          </div>
          <div className="data-panel">
            <div className="data-panel-head">
              <div className="data-panel-title" style={{ fontSize: '13px', fontWeight: 600 }}>Asset Allocation</div>
              <button className="data-panel-link" onClick={() => onSuggestQuery('Audit my asset allocation classes.', 'standard')}>Audit →</button>
            </div>
            <DonutChart labels={assetChartData.labels} data={assetChartData.data} title="" valueKind={assetUsesPercent ? 'percent' : 'currency'} unit={assetUsesPercent ? '%' : undefined} />
          </div>
        </div>
      )}

      <div className="data-panel" style={{ marginBottom: '28px' }}>
        <div className="data-panel-head" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '10px' }}>
          <div className="analytics-tabs-row" style={{ gap: 16, display: 'flex', flexWrap: 'wrap' }}>
            {([
              ['risk', 'Moat & Risk Matrix'],
              ['mf', 'Mutual Fund Diagnostics'],
              ['corr', 'Correlation'],
              ['stress', 'Shock & Stress Simulator'],
              ['tax', 'Tax & Harvesting'],
            ] as Array<[PortfolioAnalyticsTab, string]>).map(([tab, label]) => (
              <button key={tab} onClick={() => onSelectAnalyticsTab(tab)} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: analyticsTab === tab ? 'var(--text-primary)' : 'var(--text-secondary)', fontWeight: 600, fontSize: 13 }}>
                {label}
              </button>
            ))}
          </div>
        </div>

        <div style={{ marginTop: '14px' }}>
          {analyticsTab === 'risk' && (
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
                <MetricCard label="1-day VaR (95%)" value={varPct != null ? fmtINR(totalMarketValue * varPct / 100) : '—'} sub={varPct != null ? `Historical · ${fmtNum(varPct, 2, '%')}` : 'Building distribution'} tone="down" />
                <MetricCard label="CVaR (expected shortfall)" value={cvarPct != null ? fmtINR(totalMarketValue * cvarPct / 100) : '—'} sub={cvarPct != null ? `Avg loss beyond VaR · ${fmtNum(cvarPct, 2, '%')}` : '—'} tone="down" />
                <MetricCard label="Diversification (HHI)" value={fmtNum(hhiPct, 0)} sub={hhiPct > 2500 ? 'Highly concentrated' : 'Well diversified'} tone={hhiPct > 2500 ? 'down' : 'up'} />
                <MetricCard label="Top-5 concentration" value={fmtNum(risk.top5_weight_pct, 1, '%')} sub="Share in 5 biggest names" tone={Number(risk.top5_weight_pct) > 60 ? 'down' : 'neutral'} />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
                <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
                  <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: 11, marginBottom: 10 }}>ROLLING RETURNS</div>
                  <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                    {['1M', '3M', '6M', '1Y'].map((key) => {
                      const value = rolling?.[key];
                      return (
                        <div key={key} style={{ textAlign: 'center' }}>
                          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{key}</div>
                          <div style={{ fontSize: 14, fontWeight: 700, fontFamily: 'var(--font-mono)', color: value == null ? 'var(--text-muted)' : Number(value) >= 0 ? 'var(--profit)' : 'var(--loss)' }}>{value == null ? '—' : `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(1)}%`}</div>
                        </div>
                      );
                    })}
                  </div>
                </div>
                <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', fontWeight: 600, fontSize: 11, marginBottom: 8 }}><span>UNDERWATER (DRAWDOWN)</span><span style={{ color: 'var(--loss)', fontFamily: 'var(--font-mono)' }}>{fmtNum(risk.max_drawdown_pct, 1, '%')}</span></div>
                  {drawdowns.length > 1 ? <DrawdownSparkline series={drawdowns} /> : <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '10px 0' }}>Building drawdown curve…</div>}
                </div>
              </div>

              {(contributors.length > 0 || detractors.length > 0) && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12 }}>
                  <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
                    <div style={{ color: 'var(--profit)', fontWeight: 600, fontSize: 11, marginBottom: 8 }}>TOP CONTRIBUTORS</div>
                    {contributors.length === 0 ? <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>None positive yet.</div> : contributors.map((contributor: any) => (
                      <div key={contributor.symbol} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginTop: 6 }}>
                        <span style={{ color: 'var(--text-primary)' }}>{String(contributor.symbol || '').replace('.NS', '').replace('.BO', '')} <span style={{ color: 'var(--text-muted)' }}>· {fmtNum(contributor.weight_pct, 1, '%')}</span></span>
                        <span style={{ color: 'var(--profit)', fontFamily: 'var(--font-mono)' }}>+{fmtNum(contributor.contribution_pct, 2, '%')}</span>
                      </div>
                    ))}
                  </div>
                  <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
                    <div style={{ color: 'var(--loss)', fontWeight: 600, fontSize: 11, marginBottom: 8 }}>TOP DETRACTORS</div>
                    {detractors.length === 0 ? <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>No drags. Enjoy it.</div> : detractors.map((detractor: any) => (
                      <div key={detractor.symbol} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginTop: 6 }}>
                        <span style={{ color: 'var(--text-primary)' }}>{String(detractor.symbol || '').replace('.NS', '').replace('.BO', '')} <span style={{ color: 'var(--text-muted)' }}>· {fmtNum(detractor.weight_pct, 1, '%')}</span></span>
                        <span style={{ color: 'var(--loss)', fontFamily: 'var(--font-mono)' }}>{fmtNum(detractor.contribution_pct, 2, '%')}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
                Risk-adjusted ratios use a {fmtNum(risk.risk_free_rate_pct, 1, '%')} risk-free rate. VaR / CVaR are 1-day historical at 95% confidence from live price history.
                {actionQueue.length > 0 && <span style={{ color: 'var(--accent-cyan)', cursor: 'pointer', marginLeft: 6 }} onClick={() => onSuggestQuery('Check my portfolio action items.', 'standard')}>· {actionQueue.length} action item{actionQueue.length > 1 ? 's' : ''} →</span>}
              </div>
            </div>
          )}

          {analyticsTab === 'mf' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {mfHoldings.length > 0 ? (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '12px' }}>
                    <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px' }}>
                      <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: '11px', marginBottom: '4px' }}>MUTUAL FUND ASSETS</div>
                      <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>₹{displayedMfValue.toLocaleString('en-IN')}</div>
                      <div style={{ color: 'var(--text-muted)', marginTop: '4px', fontSize: '10px' }}>{schemeCount} Active Scheme{schemeCount > 1 ? 's' : ''}</div>
                    </div>
                    <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px' }}>
                      <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: '11px', marginBottom: '4px' }}>AUM-WEIGHTED TER</div>
                      <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{hasWeightedTer ? `${weightedTer.toFixed(2)}%` : 'Not synced'}</div>
                      <div style={{ color: hasWeightedTer ? 'var(--text-muted)' : 'var(--text-secondary)', marginTop: '4px', fontSize: '10px', fontWeight: 600 }}>{hasWeightedTer ? 'From backend MF metadata' : 'Needs AMFI TER metadata for schemes'}</div>
                    </div>
                    <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px', padding: '12px' }}>
                      <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: '11px', marginBottom: '4px' }}>PORTFOLIO EXPOSURE</div>
                      <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{((displayedMfValue / (portfolioSummary.totalValue || 1)) * 100).toFixed(1)}%</div>
                      <div style={{ color: 'var(--text-muted)', marginTop: '4px', fontSize: '10px' }}>Allocation in Mutual Funds</div>
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
                              <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>{Number(pct || 0).toFixed(1)}%</span>
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
                              <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>{Number(pct || 0).toFixed(1)}%</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '16px', marginTop: '4px' }}>
                    {mfHoldings.map((item) => {
                      const weightInPortfolio = ((item.qty * item.current) / (portfolioSummary.totalValue || 1)) * 100;
                      return (
                        <div key={item.symbol} style={{ background: 'rgba(255, 255, 255, 0.02)', border: '1px solid rgba(255, 255, 255, 0.06)', borderRadius: '10px', padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px', boxShadow: '0 4px 20px rgba(0, 0, 0, 0.15)' }}>
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
                              <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>₹{(item.qty * item.current).toLocaleString('en-IN')}</div>
                              <div style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '2px' }}>Weight: <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{weightInPortfolio.toFixed(1)}%</span></div>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </>
              ) : (
                <div style={{ textAlign: 'center', padding: '24px 14px', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: '8px' }}>
                  <div style={{ fontStyle: 'italic', color: 'var(--text-muted)', fontSize: '12.5px', marginBottom: '6px' }}>No Mutual Fund schemes found in your portfolio holdings statement.</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>Mutual Fund Diagnostics display only verified synced metrics for schemes present in your portfolio.</div>
                </div>
              )}
            </div>
          )}

          {analyticsTab === 'stress' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Deterministic shock engine — each holding's hit = weight × beta × shock, repriced on live betas.</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {stressScenarios.map((scenario) => (
                  <button key={scenario.key} onClick={() => onRunStressTest(scenario.key)} disabled={stressLoading} style={{ padding: '8px 12px', fontSize: 11, borderRadius: 8, cursor: 'pointer', background: stressScenario === scenario.key && stressResult ? 'rgba(251,113,133,0.16)' : 'rgba(251,113,133,0.05)', border: `1px solid ${stressScenario === scenario.key && stressResult ? 'var(--loss)' : 'var(--border-subtle)'}`, color: 'var(--text-primary)' }}>
                    {scenario.label}
                  </button>
                ))}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
                <div style={{ fontSize: 11, color: 'var(--text-secondary)', fontWeight: 600 }}>CUSTOM NIFTY SHOCK</div>
                <input type="range" min={-50} max={0} step={1} value={stressShock} onChange={(event) => onSetStressShock(Number(event.target.value))} style={{ flex: 1, minWidth: 160, accentColor: 'var(--loss)' }} />
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: 'var(--loss)', minWidth: 52, textAlign: 'right' }}>{stressShock}%</div>
                <button onClick={() => onRunStressTest('custom', stressShock)} disabled={stressLoading} style={{ padding: '8px 14px', fontSize: 11, borderRadius: 8, cursor: 'pointer', background: 'var(--loss)', border: 'none', color: '#fff', fontWeight: 700 }}>
                  {stressLoading ? 'Running…' : 'Run shock'}
                </button>
              </div>
              {stressResult && stressResult.status === 'OK' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
                    <MetricCard label="Projected impact" value={`${stressLoss >= 0 ? '+' : ''}${stressLoss.toFixed(2)}%`} tone="down" sub={stressResult.scenario_label || stressResult.scenario} />
                    <MetricCard label="Rupee loss in shock" value={fmtINR(stressResult.projected_value_loss)} tone="down" sub="Estimated" />
                    <MetricCard label="Portfolio after shock" value={fmtINR(stressResult.projected_value)} sub={`From ${fmtINR(stressResult.total_value)}`} />
                  </div>
                  <div style={{ background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: 12 }}>
                    <div style={{ color: 'var(--text-secondary)', fontWeight: 600, fontSize: 11, marginBottom: 10 }}>BIGGEST CASUALTIES</div>
                    {(stressResult.positions || []).slice(0, 6).map((position: any) => {
                      const impact = Number(position.impact_pct) || 0;
                      const width = Math.min(100, Math.abs(impact) / (Math.abs(stressLoss) || 1) * 100);
                      return (
                        <div key={position.symbol} style={{ marginBottom: 8 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 3 }}>
                            <span style={{ color: 'var(--text-primary)' }}>{String(position.symbol || '').replace('.NS', '').replace('.BO', '')} <span style={{ color: 'var(--text-muted)' }}>· β {fmtNum(position.beta, 2)} · {fmtNum(position.weight_pct, 1, '%')}</span></span>
                            <span style={{ color: 'var(--loss)', fontFamily: 'var(--font-mono)' }}>{impact.toFixed(2)}%</span>
                          </div>
                          <div style={{ height: 5, background: 'rgba(255,255,255,0.06)', borderRadius: 3 }}>
                            <div style={{ height: '100%', width: `${width}%`, background: 'var(--loss)', borderRadius: 3 }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              {!stressResult && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Pick scenario or drag slider to simulate your book.</div>}
            </div>
          )}

          {analyticsTab === 'corr' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Pairwise 1-year return correlation across your top holdings. Red = names that move together; green = diversifiers.</div>
              {hasCorrelationMatrix ? <CorrelationHeatmap matrix={correlationMatrix.matrix} labels={correlationMatrix.labels} /> : <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '12px 0' }}>Need at least 2 equity holdings with price history to map correlations.</div>}
            </div>
          )}

          {analyticsTab === 'tax' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {taxSummary && taxSummary.status === 'OK' ? (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
                    <MetricCard label="Unrealized gains" value={fmtINR(taxSummary.unrealized_total)} tone={Number(taxSummary.unrealized_total) >= 0 ? 'up' : 'down'} sub="If sold today" />
                    <MetricCard label="Short-term (STCG)" value={fmtINR(taxSummary.unrealized_stcg)} sub="Held < 1 year" />
                    <MetricCard label="Long-term (LTCG)" value={fmtINR(taxSummary.unrealized_ltcg)} sub="Held > 1 year" />
                    <MetricCard label="Est. tax if sold today" value={fmtINR(taxSummary.estimated_tax_if_sold_today)} tone="down" sub="FY25-26 rates" />
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
                          {harvest.opportunities.slice(0, 6).map((opportunity: any) => (
                            <div key={opportunity.symbol} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-subtle)', borderRadius: 8, padding: '8px 12px' }}>
                              <div>
                                <div style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-primary)' }}>{String(opportunity.symbol || '').replace('.NS', '').replace('.BO', '')} <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>· {opportunity.gain_type}</span></div>
                                <div style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>{opportunity.name || ''}</div>
                              </div>
                              <div style={{ textAlign: 'right' }}>
                                <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--loss)', fontFamily: 'var(--font-mono)' }}>−{fmtINR(opportunity.unrealized_loss).replace('-', '')}{opportunity.loss_pct != null ? ` (${Number(opportunity.loss_pct).toFixed(1)}%)` : ''}</div>
                                <div style={{ fontSize: 10, color: 'var(--profit)' }}>shield ≈ {fmtINR(opportunity.potential_tax_shield)}</div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </>
                    ) : (
                      <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>No harvestable losses right now — none of your holdings sit on unrealized loss.</div>
                    )}
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>Estimates only — actual liability depends on slab, other income and realized trades. Holding period uses recorded purchase date where available.</div>
                </>
              ) : (
                <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '12px 0' }}>Tax view loads once your holdings sync.</div>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="section-head">
        <div className="section-title">Portfolio Movers</div>
        <span className="section-sublabel">TOP MOVERS · YOUR PORTFOLIO</span>
      </div>
      <div className="movers-grid">
        <div className="movers-col">
          <div className="movers-col-head" style={{ color: 'var(--profit)' }}>↗ Gainers</div>
          {gainers.length === 0 ? <div className="movers-empty">No green names today.</div> : gainers.map((item) => (
            <div key={item.symbol} className="mover-row" onClick={() => onOpenAssetHistory(item.symbol, item.name, 'equity')}>
              <div>
                <div className="mover-sym">{item.symbol} {item.isOwned && <span className="owned-dot" title="You own this" />}</div>
                <div className="mover-name">{item.name}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div className="mover-price">₹{item.price}</div>
                <div className="mover-pct" style={{ color: 'var(--profit)' }}>+{(item.changePct ?? 0).toFixed(2)}%</div>
              </div>
            </div>
          ))}
        </div>
        <div className="movers-col">
          <div className="movers-col-head" style={{ color: 'var(--loss)' }}>↘ Losers</div>
          {losersList.length === 0 ? <div className="movers-empty">All green. Enjoy it while it lasts.</div> : losersList.map((item) => (
            <div key={item.symbol} className="mover-row" onClick={() => onOpenAssetHistory(item.symbol, item.name, 'equity')}>
              <div>
                <div className="mover-sym">{item.symbol} {item.isOwned && <span className="owned-dot" title="You own this" />}</div>
                <div className="mover-name">{item.name}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div className="mover-price">₹{item.price}</div>
                <div className="mover-pct" style={{ color: 'var(--loss)' }}>{(item.changePct ?? 0).toFixed(2)}%</div>
              </div>
            </div>
          ))}
        </div>
        <div className="movers-col">
          <div className="movers-col-head">⚡ Most active</div>
          {mostActive.length === 0 ? <div className="movers-empty">Waiting for live NSE/BSE movement.</div> : mostActive.map((item) => (
            <div key={item.symbol} className="mover-row" onClick={() => onOpenAssetHistory(item.symbol, item.name, 'equity')}>
              <div>
                <div className="mover-sym">{item.symbol} {item.isOwned && <span className="owned-dot" title="You own this" />}</div>
                <div className="mover-name">{item.name}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div className="mover-price">₹{item.price}</div>
                <div className="mover-pct" style={{ color: (item.changePct ?? 0) >= 0 ? 'var(--profit)' : 'var(--loss)' }}>{(item.changePct ?? 0) >= 0 ? '+' : ''}{(item.changePct ?? 0).toFixed(2)}%</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="section-head">
        <div className="section-title">India market summary</div>
        <span className="section-sublabel">ARTHIK'S BRIEF • {marketSummary.sourcesCount} sources</span>
      </div>
      <div className="summary-card">
        <div className="summary-card-headline">{marketSummary.headline}</div>
        <div className="summary-card-body">{marketSummary.body}</div>
        <button className="summary-cta" onClick={() => onSuggestQuery("Dive deeper on today's market moves — what should I actually do about my portfolio?", 'deep')}>
          <Sparkles size={13} /> Have Arthik dig into it
        </button>
      </div>

      <div className="data-panel">
        <div className="data-panel-head">
          <div className="data-panel-title">Holdings Workspace</div>
          <div className="panel-tabs" style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <button onClick={() => onSelectWorkspaceTab('portfolio')} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: activeTab === 'portfolio' ? 'var(--text-primary)' : 'var(--text-secondary)', fontWeight: 600, fontSize: 13, whiteSpace: 'nowrap' }}>Holdings</button>
            <button onClick={() => onSelectWorkspaceTab('watchlist')} style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: activeTab === 'watchlist' ? 'var(--text-primary)' : 'var(--text-secondary)', fontWeight: 600, fontSize: 13, whiteSpace: 'nowrap' }}>Watchlist</button>
          </div>
        </div>
        <div className="portfolio-panel-meta">
          <span>{computedPortfolioDetails.length} holding{computedPortfolioDetails.length === 1 ? '' : 's'}</span>
          <span>{portfolioExposure.sectorCount} sector{portfolioExposure.sectorCount === 1 ? '' : 's'}</span>
        </div>

        {activeTab === 'portfolio' ? (
          computedPortfolioDetails.length > 0 ? (
            <PortfolioTable portfolio={computedPortfolioDetails} onSelectStock={onSelectStock} onAnalyzeStock={onAnalyzeStock} />
          ) : (
            <div className="portfolio-empty-state">
              <div className="portfolio-empty-title">No holdings synced yet</div>
              <div className="portfolio-empty-copy">Start with manual entry or upload latest holdings document.</div>
              <div className="portfolio-empty-actions">
                <button type="button" className="portfolio-empty-btn primary" onClick={onOpenPortfolioSetup}>Set up portfolio</button>
                <button type="button" className="portfolio-empty-btn" onClick={() => onNavigate('/onboarding/upload')}>Upload now</button>
              </div>
            </div>
          )
        ) : (
          <WatchlistWorkspace symbols={watchlist} stocks={watchlistStocks} onChangeSymbols={onChangeWatchlistSymbols} onSelectStock={onSelectStock} onAskStock={onAnalyzeStock} />
        )}
      </div>

      <div className="section-head" style={{ marginTop: 24 }}>
        <div className="section-title">{portfolioSymbols.length > 0 ? 'News on your holdings' : "What's moving tape"}</div>
        <span className="section-sublabel">{portfolioSymbols.length > 0 ? `HOLDING NEWS · ${portfolioSymbols.length} TRACKED` : `LIVE NEWS · ARTHIK'S SENTIMENT`}</span>
      </div>
      <div className="news-grid">
        {newsLoading && (
          <>
            {[1, 2, 3, 4].map((index) => (
              <div key={index} className="news-card news-skeleton" style={{ padding: '14px 16px', background: 'rgba(15, 23, 42, 0.35)', border: '1px solid var(--border-subtle)', borderRadius: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
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
          <div className="news-error-banner" style={{ gridColumn: '1 / -1', padding: '12px 16px', background: 'rgba(239, 68, 68, 0.08)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: 10, display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12, color: 'var(--text-muted)' }}>
            <span>Failed to load market news</span>
            <button onClick={onRetryNews} style={{ background: 'transparent', border: '1px solid rgba(255, 255, 255, 0.15)', borderRadius: 6, padding: '4px 12px', fontSize: 11, color: 'var(--text-primary)', cursor: 'pointer' }}>Retry</button>
          </div>
        )}
        {!newsLoading && !newsError && (() => {
          const holdingNews = newsFeed.filter((item) => {
            if (portfolioSymbols.length === 0) return true;
            if (item.id.startsWith('p-')) return true;
            const itemTickers = (item.tickers || []).map((ticker) => String(ticker).split('.')[0].toUpperCase().trim());
            if (itemTickers.some((ticker) => portfolioSymbols.includes(ticker))) return true;
            const headline = item.headline.toLowerCase();
            return portfolioSymbols.some((symbol) => headline.includes(symbol.toLowerCase()));
          });

          if (holdingNews.length === 0) {
            return <div style={{ gridColumn: '1 / -1', padding: '18px 16px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13, border: '1px dashed var(--border-subtle)', borderRadius: 12 }}>No holding-specific news right now. Check Overview tab for broader market headlines.</div>;
          }

          return holdingNews.map((item) => (
            <div key={item.id} className="news-card" onClick={() => onSuggestQuery(`Tell me more about: ${item.headline}`, 'standard')}>
              <div className="news-card-meta">
                <div className="news-card-meta-copy">
                  <span className="news-source">{item.source}</span>
                  <span className="news-time">· {item.time}</span>
                </div>
                <span className="news-sentiment" style={{ color: sentimentColor(item.sentiment), borderColor: sentimentColor(item.sentiment) + '40' }}>{sentimentLabel(item.sentiment)}</span>
              </div>
              <div className="news-headline">{item.headline}</div>
              {item.tickers.length > 0 && (
                <div className="news-tickers">
                  {item.tickers.map((ticker) => <span key={ticker} className="news-ticker-pill">{ticker}</span>)}
                </div>
              )}
            </div>
          ));
        })()}
      </div>
    </>
  );
};

export default PortfolioTabContent;

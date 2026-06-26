import React from 'react';
import { ChevronLeft, ChevronRight, ExternalLink, ArrowUpRight, ArrowDownRight, Eye } from 'lucide-react';
import type { EarningsCalendarDay, EarningsCompanyItem } from '../../api/client';
import { IndexTickerCard, type IndexTickerData } from '../../components/dashboard/IndexTickerCard';
import type { WatchlistStock } from '../../components/dashboard/watchlistTypes';
import type {
  MarketMoverItem,
  NewsFeedItem,
  OverviewEarningsHero,
  PortfolioPulse,
  PortfolioSummary,
  ResearchTitleItem,
} from './types';

interface OverviewTabContentProps {
  indicesStale: boolean;
  indicesLoading: boolean;
  overviewIndices: IndexTickerData[];
  onRetryIndices: () => void;
  onOpenAssetHistory: (symbol: string, name?: string, assetType?: string) => void;
  hasPortfolioHoldings: boolean;
  overviewPortfolioPulse: PortfolioPulse | null;
  portfolioSummary: PortfolioSummary;
  portfolioTotalReturnPct: number;
  overviewPortfolioFocus: string;
  onOpenPortfolio: () => void;
  onOpenPortfolioSetup: () => void;
  overviewEarningsLoading: boolean;
  overviewEarningsError: string | null;
  overviewEarningsHero: OverviewEarningsHero | null;
  overviewTodayEarningsDay: EarningsCalendarDay | null;
  overviewEarningsDays: EarningsCalendarDay[];
  overviewEarningsUpcoming: EarningsCompanyItem[];
  ownedUniverseSet: Set<string>;
  normalizeSymbol: (value: string) => string;
  formatOverviewDate: (value?: string | null, withYear?: boolean) => string;
  formatRelativeDateLabel: (value?: string | null) => string;
  formatEarningsTiming: (timing?: string) => string;
  parseDateKey: (value?: string | null) => Date | null;
  todayOverviewDateKey: string;
  onNavigate: (href: string) => void;
  buildEarningsDetailHref: (item: Pick<EarningsCompanyItem, 'symbol' | 'name' | 'date'>) => string;
  buildEarningsDateHref: (date: string) => string;
  showMarketMoversLoading: boolean;
  marketMoversError: string | null;
  overviewGainers: MarketMoverItem[];
  overviewLosers: MarketMoverItem[];
  watchlistStocks: WatchlistStock[];
  onOpenWatchlist: () => void;
  researchTitlesLoading: boolean;
  researchTitles: ResearchTitleItem[];
  buildNewsFallbackCover: (seed: string, title?: string, source?: string, kind?: 'market' | 'research' | 'watchlist') => string;
  buildResearchArticleUrl: (slug: string, publicUrl?: string) => string;
  discoverSlides: NewsFeedItem[][];
  discoverIndex: number;
  onDiscoverPrev: () => void;
  onDiscoverNext: () => void;
  onSelectDiscoverSlide: (index: number) => void;
  discoverDragOffset: number;
  discoverBodyRef: React.RefObject<HTMLDivElement>;
  handleDiscoverPointerDown: React.PointerEventHandler<HTMLDivElement>;
  handleDiscoverPointerMove: React.PointerEventHandler<HTMLDivElement>;
  handleDiscoverPointerUp: React.PointerEventHandler<HTMLDivElement>;
  newsLoading: boolean;
  buildDiscoverItemUrl: (item: NewsFeedItem) => string;
  fmtINRWhole: (value: any) => string;
}

export const OverviewTabContent: React.FC<OverviewTabContentProps> = ({
  indicesStale,
  indicesLoading,
  overviewIndices,
  onRetryIndices,
  onOpenAssetHistory,
  hasPortfolioHoldings,
  overviewPortfolioPulse,
  portfolioSummary,
  portfolioTotalReturnPct,
  overviewPortfolioFocus,
  onOpenPortfolio,
  onOpenPortfolioSetup,
  overviewEarningsLoading,
  overviewEarningsError,
  overviewEarningsHero,
  overviewTodayEarningsDay,
  overviewEarningsDays,
  overviewEarningsUpcoming,
  ownedUniverseSet,
  normalizeSymbol,
  formatOverviewDate,
  formatRelativeDateLabel,
  formatEarningsTiming,
  parseDateKey,
  todayOverviewDateKey,
  onNavigate,
  buildEarningsDetailHref,
  buildEarningsDateHref,
  showMarketMoversLoading,
  marketMoversError,
  overviewGainers,
  overviewLosers,
  watchlistStocks,
  onOpenWatchlist,
  researchTitlesLoading,
  researchTitles,
  buildNewsFallbackCover,
  buildResearchArticleUrl,
  discoverSlides,
  discoverIndex,
  onDiscoverPrev,
  onDiscoverNext,
  onSelectDiscoverSlide,
  discoverDragOffset,
  discoverBodyRef,
  handleDiscoverPointerDown,
  handleDiscoverPointerMove,
  handleDiscoverPointerUp,
  newsLoading,
  buildDiscoverItemUrl,
  fmtINRWhole,
}) => {
  return (
    <>
      <div className="market-header" style={{ display: 'flex', alignItems: 'center', marginBottom: 18, borderBottom: '1px solid var(--border-subtle)', paddingBottom: 10, fontSize: 0 }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.1px' }}>Top India Indices</span>
        <span className="live-dot" style={{ marginRight: 6 }} /> LIVE - NSE/BSE
        {indicesStale && (
          <button
            type="button"
            onClick={onRetryIndices}
            style={{
              marginLeft: 'auto',
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted)',
              fontSize: 10,
              cursor: 'pointer',
              textDecoration: 'underline',
              padding: 0,
            }}
          >
            Refresh delayed · tap to retry
          </button>
        )}
      </div>

      <div className="index-grid">
        {indicesLoading && overviewIndices.length === 0 && (
          <>
            {[1, 2, 3, 4].map((index) => (
              <div key={index} className="index-ticker-card index-skeleton" style={{ background: 'rgba(15, 23, 42, 0.35)', border: '1px solid var(--border-subtle)', borderRadius: 14, padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0, width: '100%' }}>
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
        {overviewIndices.map((index) => (
          <IndexTickerCard
            key={index.symbol}
            data={index}
            onClick={() => onOpenAssetHistory(index.symbol, index.symbol, 'index')}
          />
        ))}
      </div>

      <div className="section-head" style={{ marginTop: 20 }}>
        <div className="section-title">Portfolio Snapshot</div>
        <span className="section-sublabel">VALUE · BEST MOVER · WORST MOVER</span>
      </div>
      {hasPortfolioHoldings && overviewPortfolioPulse ? (
        <div className="overview-portfolio-grid">
          <button type="button" className="overview-portfolio-hero" onClick={onOpenPortfolio}>
            <div className="overview-spotlight-kicker">Live portfolio</div>
            <div className="overview-portfolio-value">{fmtINRWhole(portfolioSummary.totalValue)}</div>
            <div className={'overview-portfolio-change ' + (portfolioSummary.totalPnL >= 0 ? 'up' : 'down')}>
              {(portfolioSummary.totalPnL >= 0 ? '+' : '') + fmtINRWhole(portfolioSummary.totalPnL) + ' (' + portfolioTotalReturnPct.toFixed(2) + '%)'}
            </div>
            <div className="overview-portfolio-copy">{overviewPortfolioFocus || 'Open portfolio workspace for full allocation, risk, and holdings detail.'}</div>
            <div className="overview-portfolio-strip">
              <span>{overviewPortfolioPulse.label}</span>
              <strong className={overviewPortfolioPulse.aggregateValue >= 0 ? 'up' : 'down'}>
                {(overviewPortfolioPulse.aggregateValue >= 0 ? '+' : '') + fmtINRWhole(overviewPortfolioPulse.aggregateValue) + ' (' + overviewPortfolioPulse.aggregatePct.toFixed(2) + '%)'}
              </strong>
            </div>
          </button>

          <button type="button" className="overview-portfolio-mover-card" onClick={() => onOpenAssetHistory(overviewPortfolioPulse.best.symbol, overviewPortfolioPulse.best.name, overviewPortfolioPulse.best.assetClass || 'equity')}>
            <div className="overview-mover-kicker">Best mover</div>
            <div className="overview-mover-asset">{overviewPortfolioPulse.best.name}</div>
            <div className="overview-mover-symbol-line">{overviewPortfolioPulse.best.symbol}</div>
            <div className="overview-mover-stat up">{(overviewPortfolioPulse.best.movePct >= 0 ? '+' : '') + overviewPortfolioPulse.best.movePct.toFixed(2) + '%'}</div>
            <div className="overview-mover-copy">Weight {(portfolioSummary.totalValue > 0 ? (overviewPortfolioPulse.best.currentValue / portfolioSummary.totalValue) * 100 : 0).toFixed(1)}% · Open detail</div>
          </button>

          <button type="button" className="overview-portfolio-mover-card" onClick={() => onOpenAssetHistory(overviewPortfolioPulse.worst.symbol, overviewPortfolioPulse.worst.name, overviewPortfolioPulse.worst.assetClass || 'equity')}>
            <div className="overview-mover-kicker">Worst mover</div>
            <div className="overview-mover-asset">{overviewPortfolioPulse.worst.name}</div>
            <div className="overview-mover-symbol-line">{overviewPortfolioPulse.worst.symbol}</div>
            <div className="overview-mover-stat down">{(overviewPortfolioPulse.worst.movePct >= 0 ? '+' : '') + overviewPortfolioPulse.worst.movePct.toFixed(2) + '%'}</div>
            <div className="overview-mover-copy">Weight {(portfolioSummary.totalValue > 0 ? (overviewPortfolioPulse.worst.currentValue / portfolioSummary.totalValue) * 100 : 0).toFixed(1)}% · Open detail</div>
          </button>
        </div>
      ) : (
        <div className="overview-signal-empty overview-signal-empty--portfolio">
          <div>No holdings synced yet. Add your book to unlock value, best mover, worst mover, and portfolio-specific alerts.</div>
          <button type="button" className="overview-inline-btn" onClick={onOpenPortfolioSetup}>
            Set up portfolio
          </button>
        </div>
      )}

      <div className="section-head" style={{ marginTop: 20 }}>
        <div className="section-title">Earnings Pulse</div>
        <span className="section-sublabel">RECENTLY REPORTED · UPCOMING RESULTS</span>
      </div>
      <div className="overview-earnings-grid">
        <div className="overview-earnings-hero-shell">
          {overviewEarningsLoading && !overviewEarningsHero ? (
            <div className="overview-signal-empty">Loading earnings pulse...</div>
          ) : overviewEarningsError ? (
            <div className="overview-signal-empty">{overviewEarningsError}</div>
          ) : overviewEarningsHero ? (
            <button type="button" className={'overview-spotlight-card overview-spotlight-card--earnings overview-spotlight-card--' + overviewEarningsHero.tone} onClick={() => onNavigate(overviewEarningsHero.href)}>
              <div className="overview-spotlight-kicker">
                {overviewEarningsHero.tone === 'reported' ? 'Result alert' : overviewEarningsHero.tone === 'upcoming' ? 'Next on deck' : 'Calendar pulse'}
              </div>
              <div className="overview-spotlight-title">{overviewEarningsHero.title}</div>
              <div className="overview-spotlight-subtitle">{overviewEarningsHero.subtitle}</div>
              <div className="overview-spotlight-copy">{overviewEarningsHero.body}</div>
              <div className="overview-hero-metrics">
                <span>{overviewEarningsHero.metricA}</span>
                <span>{overviewEarningsHero.metricB}</span>
                {overviewEarningsHero.symbol && ownedUniverseSet.has(normalizeSymbol(overviewEarningsHero.symbol)) ? <span className="owned-badge">TRACKED</span> : null}
              </div>
              <div className="overview-spotlight-footer">
                <div className="overview-count-pills">
                  {overviewTodayEarningsDay ? <span>Today {overviewTodayEarningsDay.company_count}</span> : null}
                  {overviewEarningsDays[1] ? <span>{formatOverviewDate(overviewEarningsDays[1].date)} {overviewEarningsDays[1].company_count}</span> : null}
                </div>
                <span className="overview-spotlight-link">{overviewEarningsHero.cta} <ExternalLink size={12} /></span>
              </div>
            </button>
          ) : (
            <div className="overview-signal-empty">No scheduled earnings on near-term calendar.</div>
          )}
        </div>

        <div className="earnings-list overview-earnings-list">
          {overviewEarningsLoading && overviewEarningsUpcoming.length === 0 ? (
            <div className="overview-movers-empty">Loading upcoming companies...</div>
          ) : overviewEarningsError ? (
            <div className="overview-movers-empty">{overviewEarningsError}</div>
          ) : overviewEarningsUpcoming.length === 0 ? (
            <div className="overview-movers-empty">No upcoming companies in next few sessions.</div>
          ) : overviewEarningsUpcoming.map((company) => {
            const parsedDate = parseDateKey(company.date);
            const dayNumber = parsedDate ? String(parsedDate.getDate()).padStart(2, '0') : '--';
            const monthLabel = parsedDate ? parsedDate.toLocaleDateString('en-IN', { month: 'short' }).toUpperCase() : 'TBD';
            const tracked = ownedUniverseSet.has(normalizeSymbol(company.symbol));
            const isPastRow = Boolean(company.is_past || company.eps_actual != null || company.post_earnings_move_1d != null);
            const route = isPastRow ? buildEarningsDetailHref(company) : buildEarningsDateHref(company.date);
            const hasRevPat = company.revenue_yoy_pct != null || company.pat_yoy_pct != null;

            return (
              <button key={company.event_uid} type="button" className="earnings-row overview-earnings-row" onClick={() => onNavigate(route)}>
                <div className="earnings-date">
                  <div className="earnings-day">{monthLabel}</div>
                  <div className="earnings-num">{dayNumber}</div>
                </div>
                <div className="earnings-info">
                  <div className="earnings-name">
                    <span>{company.name}</span>
                    {tracked ? <span className="owned-badge">TRACKED</span> : null}
                  </div>
                  <div className="earnings-period">{company.symbol} · {company.fiscal_quarter || 'Quarter TBD'}</div>
                  <div className="earnings-when">{formatEarningsTiming(company.timing)} · {formatOverviewDate(company.date, true)}</div>
                </div>
                <div className="earnings-catalyst">
                  {isPastRow && hasRevPat ? (
                    <div className="earnings-rev-pat-pills">
                      {company.revenue_yoy_pct != null && (
                        <span className={'overview-status-pill ' + (Number(company.revenue_yoy_pct) >= 0 ? 'positive' : 'negative')}>
                          Rev {Number(company.revenue_yoy_pct) >= 0 ? '+' : ''}{Number(company.revenue_yoy_pct).toFixed(1)}%
                        </span>
                      )}
                      {company.pat_yoy_pct != null && (
                        <span className={'overview-status-pill ' + (Number(company.pat_yoy_pct) >= 0 ? 'positive' : 'negative')}>
                          PAT {Number(company.pat_yoy_pct) >= 0 ? '+' : ''}{Number(company.pat_yoy_pct).toFixed(1)}%
                        </span>
                      )}
                    </div>
                  ) : (
                    <span className={'overview-status-pill ' + (company.date === todayOverviewDateKey ? 'warning' : 'muted')}>{formatRelativeDateLabel(company.date)}</span>
                  )}
                  <div className="earnings-catalyst-text">{company.highlights?.[0]?.text || (company.sector ? company.sector + (isPastRow ? ' result announced.' : ' result on radar.') : (isPastRow ? 'Open result snapshot for details.' : 'Open earnings slate for details.'))}</div>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="section-head" style={{ marginTop: 20 }}>
        <div className="section-title">Today's Gainers & Losers</div>
        <span className="section-sublabel">TOP 5 EACH</span>
      </div>
      <div className="overview-movers-grid">
        <div className="overview-movers-panel">
          <div className="overview-movers-head">
            <span>Gainers</span>
            <span>{overviewGainers.length}</span>
          </div>
          <div className="overview-movers-list">
            {showMarketMoversLoading ? (
              <div className="overview-movers-empty">Loading gainers...</div>
            ) : marketMoversError ? (
              <div className="overview-movers-empty">{marketMoversError}</div>
            ) : overviewGainers.length === 0 ? (
              <div className="overview-movers-empty">No gainers found right now.</div>
            ) : overviewGainers.map((item) => (
              <div key={`g-${item.symbol}`} className="overview-mover-row">
                <div className="overview-mover-symbol">{item.symbol}</div>
                <div className="overview-mover-name">{item.name}</div>
                <div className="overview-mover-price">₹{item.price.toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}</div>
                <div className="overview-mover-change up">+{item.changePct.toFixed(2)}%</div>
              </div>
            ))}
          </div>
        </div>

        <div className="overview-movers-panel">
          <div className="overview-movers-head">
            <span>Losers</span>
            <span>{overviewLosers.length}</span>
          </div>
          <div className="overview-movers-list">
            {showMarketMoversLoading ? (
              <div className="overview-movers-empty">Loading losers...</div>
            ) : marketMoversError ? (
              <div className="overview-movers-empty">{marketMoversError}</div>
            ) : overviewLosers.length === 0 ? (
              <div className="overview-movers-empty">No losers found right now.</div>
            ) : overviewLosers.map((item) => (
              <div key={`l-${item.symbol}`} className="overview-mover-row">
                <div className="overview-mover-symbol">{item.symbol}</div>
                <div className="overview-mover-name">{item.name}</div>
                <div className="overview-mover-price">₹{item.price.toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}</div>
                <div className="overview-mover-change down">{item.changePct.toFixed(2)}%</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="section-head" style={{ marginTop: 20 }}>
        <div className="section-title">My Watchlist</div>
        <span className="section-sublabel">{watchlistStocks.length} TRACKED</span>
      </div>
      {watchlistStocks.length > 0 ? (
        <div className="overview-watchlist-grid">
          {watchlistStocks.slice(0, 8).map((stock) => {
            const isUp = stock.changePct >= 0;
            return (
              <button key={stock.symbol} type="button" className={`overview-watchlist-card ${isUp ? 'up' : 'down'}`} onClick={() => onOpenAssetHistory(stock.symbol, stock.name, 'equity')}>
                <div className="overview-watchlist-card-header">
                  <span className="overview-watchlist-symbol">{stock.symbol}</span>
                  <span className={`overview-watchlist-badge ${isUp ? 'up' : 'down'}`}>
                    {isUp ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                    {isUp ? '+' : ''}{stock.changePct.toFixed(2)}%
                  </span>
                </div>
                <div className="overview-watchlist-name" title={stock.name}>{stock.name}</div>
                <div className="overview-watchlist-price">₹{stock.price}</div>
                <div className={`overview-watchlist-change ${isUp ? 'up' : 'down'}`}>{stock.change}</div>
              </button>
            );
          })}
          {watchlistStocks.length > 8 && (
            <button type="button" className="overview-watchlist-card overview-watchlist-more" onClick={onOpenWatchlist}>
              <Eye size={18} />
              <span>+{watchlistStocks.length - 8} more</span>
              <span className="overview-watchlist-more-cta">View all</span>
            </button>
          )}
        </div>
      ) : (
        <div className="overview-signal-empty overview-signal-empty--watchlist">
          <div>No stocks in your watchlist yet. Add companies to track prices and get quick insights.</div>
          <button type="button" className="overview-inline-btn" onClick={onOpenWatchlist}>
            <Eye size={14} /> Set up watchlist
          </button>
        </div>
      )}

      <div className="section-head" style={{ marginTop: 20 }}>
        <div className="section-title">ProspektLab Research</div>
        <span className="section-sublabel">LATEST GENERATED ARTICLES</span>
      </div>
      <div className="overview-article-grid">
        {researchTitlesLoading && researchTitles.length === 0 ? (
          <div className="overview-article-empty">Latest generated articles loading...</div>
        ) : researchTitles.map((article) => {
          const primaryCover = buildNewsFallbackCover(`research:${article.slug}:${article.title}`, article.title, article.content_type || 'Research', 'research');
          return (
            <a key={article.slug} href={buildResearchArticleUrl(article.slug, article.public_url)} className="overview-article-card" target="_blank" rel="noopener noreferrer">
              <img
                src={article.image_path || primaryCover}
                alt={`${article.title} cover`}
                className="overview-article-image"
                loading="lazy"
                draggable={false}
                onError={(event) => {
                  event.currentTarget.src = buildNewsFallbackCover(`research:${article.slug}`, article.title, article.content_type || 'Research', 'research');
                }}
              />
              <div className="overview-article-body">
                <div className="overview-article-meta">
                  <span>{article.content_type || 'Research'}</span>
                  <span>{article.ago}</span>
                </div>
                <div className="overview-article-title">{article.title}</div>
              </div>
            </a>
          );
        })}
      </div>

      <div className="section-head" style={{ marginTop: 22 }}>
        <div className="section-title">Discover</div>
        <span className="section-sublabel">MULTI-SOURCE LIVE FEED</span>
      </div>
      <div className="discover-carousel-shell">
        <button type="button" className="discover-nav-btn" onClick={onDiscoverPrev} disabled={discoverSlides.length <= 1} aria-label="Previous discover slide">
          <ChevronLeft size={18} />
        </button>
        <div
          className={`discover-carousel-body${discoverDragOffset !== 0 ? ' is-dragging' : ''}`}
          ref={discoverBodyRef}
          onPointerDown={handleDiscoverPointerDown}
          onPointerMove={handleDiscoverPointerMove}
          onPointerUp={handleDiscoverPointerUp}
          onPointerCancel={handleDiscoverPointerUp}
          onPointerLeave={handleDiscoverPointerUp}
        >
          {discoverSlides.length > 0 ? (
            <div className="discover-carousel-track" style={{ transform: `translateX(calc(${-discoverIndex * 100}% + ${discoverDragOffset}px))` }}>
              {discoverSlides.map((slide, slideIndex) => (
                <div key={slideIndex} className="discover-slide">
                  {slide.map((item) => {
                    const discoverHref = buildDiscoverItemUrl(item);
                    return (
                      <a key={item.id} href={discoverHref} className="discover-card" target="_blank" rel="noopener noreferrer" onPointerDown={(event) => event.stopPropagation()}>
                        <img
                          src={item.image || buildNewsFallbackCover(item.headline, item.headline, item.source)}
                          alt={`${item.headline} cover`}
                          className="discover-card-image"
                          loading="lazy"
                          draggable={false}
                          onError={(event) => {
                            event.currentTarget.src = buildNewsFallbackCover(item.headline, item.headline, item.source);
                          }}
                        />
                        <div className="discover-card-content">
                          <div className="discover-card-headline">{item.headline}</div>
                          <div className="discover-card-meta">
                            <span>{item.sourceCount > 0 ? `${item.sourceCount} sources` : item.source}</span>
                            <ExternalLink size={12} />
                          </div>
                        </div>
                      </a>
                    );
                  })}
                </div>
              ))}
            </div>
          ) : (
            <div className="discover-empty">{newsLoading ? 'Loading discover feed...' : 'No discover cards available right now.'}</div>
          )}
        </div>
        <button type="button" className="discover-nav-btn" onClick={onDiscoverNext} disabled={discoverSlides.length <= 1} aria-label="Next discover slide">
          <ChevronRight size={18} />
        </button>
      </div>
      {discoverSlides.length > 1 && (
        <div className="discover-dots">
          {discoverSlides.map((_, index) => (
            <button key={`discover-dot-${index}`} type="button" className={discoverIndex === index ? 'active' : ''} onClick={() => onSelectDiscoverSlide(index)} aria-label={`Discover slide ${index + 1}`} />
          ))}
        </div>
      )}
    </>
  );
};

export default OverviewTabContent;

import React from 'react';
import { Rocket, RefreshCw, Search, X, TrendingUp, Clock, CheckCircle, Activity } from 'lucide-react';
import { AppShell } from '../components/layout/AppShell';
import { IpoCardView } from '../components/ipo/IpoCard';
import { getIpoPipeline, searchIpos, IpoPipelineResponse, IpoCard } from '../api/client';

type FilterTab = 'all' | 'live' | 'upcoming' | 'listed';

// Memoized icons to prevent recreation on each render
const FILTER_ICONS: Record<FilterTab, React.ReactNode> = {
  all: <Activity size={13} />,
  live: <span className="ipo-pulse-dot" />,
  upcoming: <Clock size={13} />,
  listed: <CheckCircle size={13} />,
};

const FILTER_TABS: { key: FilterTab; label: string }[] = [
  { key: 'all', label: 'All IPOs' },
  { key: 'live', label: 'Live' },
  { key: 'upcoming', label: 'Upcoming' },
  { key: 'listed', label: 'Recently Listed' },
];

interface StatsPillProps {
  live: number;
  upcoming: number;
  listed: number;
}

const StatsPills = React.memo<StatsPillProps>(({ live, upcoming, listed }) => (
  <div className="ipo-stats-row">
    <div className="ipo-stat-pill live">
      <span className="ipo-pulse-dot" />
      <span className="ipo-stat-pill-count">{live}</span>
      <span className="ipo-stat-pill-label">Live</span>
    </div>
    <div className="ipo-stat-pill upcoming">
      <Clock size={12} />
      <span className="ipo-stat-pill-count">{upcoming}</span>
      <span className="ipo-stat-pill-label">Upcoming</span>
    </div>
    <div className="ipo-stat-pill listed">
      <TrendingUp size={12} />
      <span className="ipo-stat-pill-count">{listed}</span>
      <span className="ipo-stat-pill-label">Listed</span>
    </div>
  </div>
));

StatsPills.displayName = 'StatsPills';

interface IpoSectionProps {
  title: string;
  subtitle: string;
  cards: IpoPipelineResponse['buckets']['upcoming'];
  originPath?: string;
  variant: 'live' | 'upcoming' | 'listed';
}

const IpoSection = React.memo<IpoSectionProps>(({ title, subtitle, cards, originPath, variant }) => (
  <section className={`ipo-section ipo-section--${variant}`}>
    <div className="ipo-section-head">
      <div className="ipo-section-head-left">
        <div className="ipo-section-badge-wrap">
          {variant === 'live' && <span className="ipo-live-badge"><span className="ipo-pulse-dot" />Live</span>}
          {variant === 'upcoming' && <span className="ipo-upcoming-badge"><Clock size={11} />Upcoming</span>}
          {variant === 'listed' && <span className="ipo-listed-badge"><TrendingUp size={11} />Listed</span>}
        </div>
        <div className="ipo-section-title">{title}</div>
        <div className="ipo-section-subtitle">{subtitle}</div>
      </div>
      <span className="ipo-section-count">{cards.length} IPO{cards.length !== 1 ? 's' : ''}</span>
    </div>
    {cards.length === 0 ? (
      <div className="ipo-empty">
        <div className="ipo-empty-icon">
          {variant === 'live' ? '📡' : variant === 'upcoming' ? '📋' : '📊'}
        </div>
        <div className="ipo-empty-text">No {variant} IPOs right now</div>
        <div className="ipo-empty-sub">Check back soon — the pipeline updates daily</div>
      </div>
    ) : (
      <div className="ipo-card-grid-wrap">
        {cards.map((card) => (
          <IpoCardView key={card.slug} card={card} originPath={originPath} />
        ))}
      </div>
    )}
  </section>
));

IpoSection.displayName = 'IpoSection';

interface IpoDashboardContentProps {
  embedded?: boolean;
  originPath?: string;
}

export const IpoDashboardContent: React.FC<IpoDashboardContentProps> = ({
  embedded = false,
  originPath = '/ipo',
}) => {
  const [data, setData] = React.useState<IpoPipelineResponse | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');
  const [activeFilter, setActiveFilter] = React.useState<FilterTab>('all');
  const [searchQuery, setSearchQuery] = React.useState('');
  const [searchResults, setSearchResults] = React.useState<IpoCard[] | null>(null);
  const [searchLoading, setSearchLoading] = React.useState(false);
  const searchTimeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = React.useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const payload = await getIpoPipeline();
      setData(payload);
    } catch (err: any) {
      setError(err?.message || 'Failed to load IPO pipeline');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => { load(); }, [load]);

  // Debounced search
  React.useEffect(() => {
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    searchTimeoutRef.current = setTimeout(async () => {
      setSearchLoading(true);
      try {
        const res = await searchIpos(searchQuery.trim(), 20);
        setSearchResults(res.results);
      } catch {
        setSearchResults([]);
      } finally {
        setSearchLoading(false);
      }
    }, 350);
    return () => {
      if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    };
  }, [searchQuery]);

  const liveCount = data?.buckets.live.length ?? 0;
  const upcomingCount = data?.buckets.upcoming.length ?? 0;
  const listedCount = data?.buckets.listed.length ?? 0;

  // Memoized filter computation to avoid recalculating on every render
  const filtered = React.useMemo(() => {
    if (!data) return { live: [], upcoming: [], listed: [] };
    if (activeFilter === 'all') return data.buckets;
    if (activeFilter === 'live') return { live: data.buckets.live, upcoming: [], listed: [] };
    if (activeFilter === 'upcoming') return { live: [], upcoming: data.buckets.upcoming, listed: [] };
    return { live: [], upcoming: [], listed: data.buckets.listed };
  }, [data, activeFilter]);

  const isSearchActive = searchQuery.trim().length > 0;

  // Memoized handlers to prevent child re-renders
  const handleFilterChange = React.useCallback((key: FilterTab) => {
    setActiveFilter(key);
    setSearchQuery('');
  }, []);

  const handleSearchChange = React.useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchQuery(e.target.value);
  }, []);

  const handleClearSearch = React.useCallback(() => {
    setSearchQuery('');
  }, []);

  const contentStyle: React.CSSProperties = embedded
    ? { minWidth: 0 }
    : { flex: 1, overflowY: 'auto' as const, minWidth: 0, padding: 'clamp(16px, 3vw, 28px) clamp(14px, 4vw, 36px) 60px' };

  return (
    <div style={contentStyle}>
      {/* Hero */}
      <div className="ipo-hero">
        <div className="ipo-hero-left">
          <div className="ipo-hero-eyebrow">
            <Rocket size={14} />
            Primary market intelligence
          </div>
          <h1 className="ipo-hero-title">IPO Pipeline</h1>
          <p className="ipo-hero-body">
            Live DRHP analysis across upcoming, open, and recently listed IPOs &mdash; including SME issues that most platforms skip.
          </p>
          {data && <StatsPills live={liveCount} upcoming={upcomingCount} listed={listedCount} />}
        </div>
        <button type="button" className="ipo-refresh-btn" onClick={load} disabled={loading}>
          <RefreshCw size={13} className={loading ? 'ipo-spin' : ''} />
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {/* Controls bar: filter tabs + search */}
      <div className="ipo-controls-bar">
        <div className="ipo-filter-tabs" role="tablist">
          {FILTER_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={activeFilter === tab.key}
              className={`ipo-filter-tab${activeFilter === tab.key ? ' active' : ''}`}
              onClick={() => handleFilterChange(tab.key)}
            >
              {FILTER_ICONS[tab.key]}
              {tab.label}
              {tab.key === 'live' && liveCount > 0 && <span className="ipo-filter-badge">{liveCount}</span>}
            </button>
          ))}
        </div>
        <div className="ipo-search-wrap">
          <Search size={13} className="ipo-search-icon" />
          <input
            type="text"
            className="ipo-search-input"
            placeholder="Search IPOs…"
            value={searchQuery}
            onChange={handleSearchChange}
            aria-label="Search IPOs"
          />
          {searchQuery && (
            <button type="button" className="ipo-search-clear" onClick={handleClearSearch} aria-label="Clear">
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      {loading && (
        <div className="ipo-loading">
          <div className="ipo-loading-inner">
            <div className="ipo-loading-spinner" />
            Loading IPO pipeline&hellip;
          </div>
        </div>
      )}
      {error && <div className="ipo-error">{error}</div>}

      {/* Search results */}
      {isSearchActive && !loading && (
        <div className="ipo-search-results-wrap">
          <div className="ipo-section-head">
            <div className="ipo-section-head-left">
              <div className="ipo-section-title">Search results</div>
              <div className="ipo-section-subtitle">
                {searchLoading ? 'Searching…' : searchResults ? `${searchResults.length} result${searchResults.length !== 1 ? 's' : ''} for "${searchQuery}"` : ''}
              </div>
            </div>
          </div>
          {searchLoading && <div className="ipo-loading"><div className="ipo-loading-inner"><div className="ipo-loading-spinner" />Searching&hellip;</div></div>}
          {!searchLoading && searchResults?.length === 0 && (
            <div className="ipo-empty">
              <div className="ipo-empty-icon">🔍</div>
              <div className="ipo-empty-text">No results for &ldquo;{searchQuery}&rdquo;</div>
              <div className="ipo-empty-sub">Try a different company name or sector</div>
            </div>
          )}
          {!searchLoading && searchResults && searchResults.length > 0 && (
            <div className="ipo-card-grid-wrap">
              {searchResults.map((card) => (
                <IpoCardView key={card.slug} card={card} originPath={originPath} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Main pipeline sections */}
      {data && !isSearchActive && (
        <>
          {(activeFilter === 'all' || activeFilter === 'live') && (
            <IpoSection
              title="Live for subscription"
              subtitle="Currently open IPOs with DRHP/RHP analysis and live subscription context"
              cards={filtered.live}
              originPath={originPath}
              variant="live"
            />
          )}
          {(activeFilter === 'all' || activeFilter === 'upcoming') && (
            <IpoSection
              title="Upcoming pipeline"
              subtitle="DRHP filed &mdash; subscription not yet open"
              cards={filtered.upcoming}
              originPath={originPath}
              variant="upcoming"
            />
          )}
          {(activeFilter === 'all' || activeFilter === 'listed') && (
            <IpoSection
              title="Recently listed"
              subtitle="Listed in the last 30 days with post-listing performance"
              cards={filtered.listed}
              originPath={originPath}
              variant="listed"
            />
          )}
          <div className="ipo-gmp-disclaimer">
            <span className="ipo-disclaimer-icon">⚠</span>
            {data.gmp_disclaimer}
          </div>
        </>
      )}
    </div>
  );
};

export const IpoDashboard: React.FC = () => {
  return (
    <AppShell title="IPO Intelligence">
      <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-deep)' }}>
        <IpoDashboardContent />
      </div>
    </AppShell>
  );
};

export default IpoDashboard;

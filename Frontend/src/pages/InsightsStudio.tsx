import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  BarChart2,
  FileSearch,
  Globe,
  Grid,
  Info,
  LayoutList,
  Newspaper,
  RefreshCcw,
  Send,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import AppShell from '../components/layout/AppShell';
import { FlashJobMonitor } from '../components/insights/FlashJobMonitor';
import { ArticleQueueTable } from '../components/insights/ArticleQueueTable';
import { DraftReviewDrawer } from '../components/insights/DraftReviewDrawer';
import { ArticleReader } from '../components/insights/ArticleReader';
import { getContentArticle, ArticleDetail, getMarketIndices, getMarketQuotes } from '../api/client';
import '../components/insights/insightsStudio.css';
import {
  ArticleListItem,
  FlashGenerationRequest,
  generateFlashArticle,
  getContentAutomationStatus,
  listContentArticles,
  publishContentArticle,
  runContentAutomationNow,
  unpublishContentArticle,
  AutomationStatus,
} from '../api/client';

// ─────────────────────────────────────────────────────────────
//  Types
// ─────────────────────────────────────────────────────────────

type ContentType = 'earnings' | 'sebi' | 'trend' | 'company' | 'manual';
type ViewMode = 'cards' | 'table';

interface ActiveJob {
  jobId: string;
  mode: 'research' | 'automation';
  label: string;
}

interface MarketIndex {
  name: string;
  sub: string;
  symbol: string;
  price: number | null;
  change: number | null;
  changePct: number | null;
  dir: 'up' | 'down';
  history: number[];
}

interface MarketCard {
  name: string;
  symbol: string;
  price: number | null;
  changePct: number | null;
  dir: 'up' | 'down';
  prefix?: string;
  suffix?: string;
  history: number[];
}

// ─────────────────────────────────────────────────────────────
//  Constants
// ─────────────────────────────────────────────────────────────

const isLivePublished = (item: ArticleListItem): boolean =>
  item.publish_status === 'published' && item.publish_gate_status === 'publish';

const CONTENT_TYPE_META: Record<ContentType, { label: string; colour: string; desc: string }> = {
  earnings: { label: 'Earnings', colour: '#34D399', desc: 'Quarterly and annual result analysis' },
  sebi: { label: 'Regulatory', colour: '#FB7185', desc: 'SEBI orders, settlements, and compliance shifts' },
  trend: { label: 'Trend', colour: '#60A5FA', desc: 'Sector, macro, and policy-led market stories' },
  company: { label: 'Company', colour: '#A78BFA', desc: 'Company intelligence with governance and risk context' },
  manual: { label: 'Manual', colour: '#94A3B8', desc: 'Operator-led research topic or angle' },
};

const AUTOMATION_STATUS_LABELS: Record<string, string> = {
  running: 'sweep running',
  scheduled: 'watching 24/7',
  offline: 'scheduler offline',
  disabled: 'automation paused',
  manual_only: 'manual mode',
  idle: 'checking status',
};

const CATEGORY_FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'earnings', label: 'Earnings' },
  { key: 'sebi', label: 'SEBI' },
  { key: 'trend', label: 'Trend' },
  { key: 'company', label: 'Company' },
  { key: 'manual', label: 'Manual' },
];

// ─────────────────────────────────────────────────────────────
//  Sparkline canvas helper
// ─────────────────────────────────────────────────────────────

function drawSparkline(
  canvas: HTMLCanvasElement,
  pts: number[],
  dir: 'up' | 'down',
  lineWidth = 1.6
) {
  if (!pts || pts.length < 2) return;
  const upColor = '#34D399';
  const downColor = '#FB7185';
  const color = dir === 'up' ? upColor : downColor;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = rect.width || 80;
  const h = rect.height || 30;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.scale(dpr, dpr);
  const min = Math.min(...pts);
  const max = Math.max(...pts);
  const range = max - min || 1;
  const pad = 2;
  const xOf = (i: number) => pad + (i / (pts.length - 1)) * (w - pad * 2);
  const yOf = (v: number) => h - pad - ((v - min) / range) * (h - pad * 2);
  // fill
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, color + '30');
  grad.addColorStop(1, color + '00');
  ctx.beginPath();
  ctx.moveTo(xOf(0), yOf(pts[0]));
  for (let i = 1; i < pts.length; i++) ctx.lineTo(xOf(i), yOf(pts[i]));
  ctx.lineTo(xOf(pts.length - 1), h);
  ctx.lineTo(xOf(0), h);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();
  // line
  ctx.beginPath();
  ctx.moveTo(xOf(0), yOf(pts[0]));
  for (let i = 1; i < pts.length; i++) ctx.lineTo(xOf(i), yOf(pts[i]));
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth;
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.stroke();
  // dot
  const last = pts.length - 1;
  ctx.beginPath();
  ctx.arc(xOf(last), yOf(pts[last]), 2.2, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
}

// ─────────────────────────────────────────────────────────────
//  Sparkline component
// ─────────────────────────────────────────────────────────────

const Sparkline: React.FC<{
  pts: number[];
  dir: 'up' | 'down';
  width?: number;
  height?: number;
  lineWidth?: number;
  className?: string;
}> = ({ pts, dir, width, height, lineWidth, className }) => {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (ref.current && pts.length >= 2) drawSparkline(ref.current, pts, dir, lineWidth);
  }, [pts, dir, lineWidth]);
  return (
    <canvas
      ref={ref}
      className={`pl-spark-canvas ${className || ''}`}
      style={{ width: width || 80, height: height || 30, display: 'block' }}
    />
  );
};

// ─────────────────────────────────────────────────────────────
//  Ticker strip
// ─────────────────────────────────────────────────────────────

const STATIC_TICKER_DATA = [
  ['RELIANCE', '0', '+0.00%', 'up'],
  ['TCS', '0', '+0.00%', 'up'],
  ['HDFCBANK', '0', '+0.00%', 'down'],
  ['INFY', '0', '+0.00%', 'up'],
  ['ICICIBANK', '0', '+0.00%', 'up'],
  ['SBIN', '0', '+0.00%', 'down'],
  ['BHARTIARTL', '0', '+0.00%', 'up'],
  ['ITC', '0', '+0.00%', 'down'],
  ['LT', '0', '+0.00%', 'up'],
  ['AXISBANK', '0', '+0.00%', 'up'],
  ['KOTAKBANK', '0', '+0.00%', 'down'],
  ['HINDUNILVR', '0', '+0.00%', 'up'],
  ['ADANIENT', '0', '+0.00%', 'up'],
  ['MARUTI', '0', '+0.00%', 'up'],
  ['SUNPHARMA', '0', '+0.00%', 'down'],
];

const TICKER_SYMBOLS = STATIC_TICKER_DATA.map((d) => d[0]);

interface TickerItem { sym: string; px: string; chg: string; dir: 'up' | 'down'; }

const TickerStrip: React.FC = () => {
  const [items, setItems] = useState<TickerItem[]>(
    STATIC_TICKER_DATA.map((d) => ({ sym: d[0], px: d[1], chg: d[2], dir: d[3] as 'up' | 'down' }))
  );

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await getMarketQuotes(TICKER_SYMBOLS);
        if (cancelled) return;
        const quotes: Record<string, any> = {};
        if (Array.isArray(data)) {
          data.forEach((q: any) => { if (q.symbol) quotes[q.symbol] = q; });
        } else if (data && typeof data === 'object') {
          Object.assign(quotes, data);
        }
        const updated = TICKER_SYMBOLS.map((sym) => {
          const q = quotes[sym] || quotes[sym.replace('.NS', '')] || quotes[sym + '.NS'];
          if (!q) return { sym, px: '—', chg: '—', dir: 'up' as const };
          const price = q.price ?? q.last_price ?? q.close ?? 0;
          const chgPct = q.change_pct ?? q.changePct ?? q.pct_change ?? 0;
          const dir: 'up' | 'down' = chgPct >= 0 ? 'up' : 'down';
          const sign = chgPct >= 0 ? '+' : '';
          return {
            sym,
            px: price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
            chg: `${sign}${chgPct.toFixed(2)}%`,
            dir,
          };
        });
        setItems(updated);
      } catch (_) {
        /* silent - show static dashes */
      }
    };
    load();
    const id = window.setInterval(load, 60000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, []);

  const doubled = [...items, ...items];

  return (
    <div className="pl-ticker" aria-hidden="true">
      <div className="pl-ticker-track">
        {doubled.map((item, i) => (
          <span key={i} className="pl-tk">
            <span className="pl-sym">{item.sym}</span>
            <span className="pl-px">{item.px}</span>
            <span className={`pl-chg-${item.dir}`}>
              {item.dir === 'up' ? '▲' : '▼'} {item.chg}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────
//  Market snapshot (NIFTY / SENSEX / BANKNIFTY / INR-USD)
// ─────────────────────────────────────────────────────────────

const DEFAULT_INDICES: MarketIndex[] = [
  { name: 'NIFTY 50', sub: 'NSE · INDEX', symbol: 'NIFTY50', price: null, change: null, changePct: null, dir: 'up', history: [100, 101, 99, 102, 103, 101, 104, 106, 105, 108] },
  { name: 'SENSEX', sub: 'BSE · INDEX', symbol: 'SENSEX', price: null, change: null, changePct: null, dir: 'up', history: [100, 100.5, 101, 100.2, 101.5, 102, 101.8, 103, 102.6, 103.4] },
  { name: 'BANK NIFTY', sub: 'NSE · INDEX', symbol: 'BANKNIFTY', price: null, change: null, changePct: null, dir: 'down', history: [100, 99, 98.5, 99.2, 98, 97.4, 98.1, 97, 96.4, 96.8] },
  { name: 'INR / USD', sub: 'FX · SPOT', symbol: 'USDINR', price: null, change: null, changePct: null, dir: 'up', history: [100, 100.1, 100.05, 100.2, 100.3, 100.25, 100.4, 100.5, 100.45, 100.6] },
];

const DEFAULT_MB_CARDS: MarketCard[] = [
  { name: 'Nifty IT', symbol: 'NIFTYIT', price: null, changePct: null, dir: 'up', history: [100, 101, 102, 101.5, 103, 104, 103.6, 105, 106, 107] },
  { name: 'Nifty Auto', symbol: 'NIFTYAUTO', price: null, changePct: null, dir: 'up', history: [100, 100.4, 101, 100.8, 101.6, 102, 101.4, 102.2, 102.8, 103] },
  { name: 'Nifty FMCG', symbol: 'NIFTYFMCG', price: null, changePct: null, dir: 'down', history: [100, 99.8, 100, 99.4, 99, 99.2, 98.6, 98.9, 98.4, 98.7] },
  { name: 'Gold (10g)', symbol: 'GOLD', price: null, changePct: null, dir: 'up', prefix: '₹', history: [100, 100.6, 101, 101.4, 101, 101.8, 102.2, 102, 102.6, 103] },
  { name: 'Crude (WTI)', symbol: 'CRUDEOIL', price: null, changePct: null, dir: 'down', prefix: '$', history: [100, 99.4, 99, 98.6, 99, 98.2, 97.8, 98, 97.4, 97.6] },
  { name: 'India 10Y', symbol: 'IN10Y', price: null, changePct: null, dir: 'up', suffix: '%', history: [100, 100.1, 100, 100.2, 100.3, 100.2, 100.4, 100.5, 100.4, 100.6] },
];

function fmtPrice(v: number | null, dec = 2, prefix = '', suffix = ''): string {
  if (v === null) return '—';
  return prefix + v.toLocaleString('en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec }) + suffix;
}

function fmtChg(pct: number | null): string {
  if (pct === null) return '—';
  return (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
}

const MarketSnap: React.FC<{ indices: MarketIndex[]; loading: boolean }> = ({ indices, loading }) => (
  <div className="pl-market-snap">
    <div className="pl-snap-head">
      <span className="pl-snap-eyebrow">Market Snapshot</span>
      <span className="pl-snap-live">
        <span className="pl-pulse" />
        Live
      </span>
    </div>
    {indices.map((idx, i) => (
      <div key={i} className="pl-idx-row">
        <div className="pl-idx-meta">
          <div className="pl-idx-name">{idx.name}</div>
          <div className="pl-idx-sub">{idx.sub}</div>
        </div>
        <Sparkline pts={idx.history} dir={idx.dir} width={80} height={28} className="pl-idx-spark" />
        <div className="pl-idx-val">
          {loading && idx.price === null ? (
            <div className="pl-shimmer" style={{ width: 80, height: 14, marginBottom: 4 }} />
          ) : (
            <div className="pl-idx-px">{fmtPrice(idx.price, 2)}</div>
          )}
          {loading && idx.changePct === null ? (
            <div className="pl-shimmer" style={{ width: 56, height: 11, marginTop: 3 }} />
          ) : (
            <div className={`pl-idx-chg ${idx.dir}`}>{fmtChg(idx.changePct)}</div>
          )}
        </div>
      </div>
    ))}
  </div>
);

const MarketBand: React.FC<{ cards: MarketCard[]; loading: boolean }> = ({ cards, loading }) => (
  <div>
    <div className="pl-section-label" style={{ marginBottom: 10 }}>Market Watch — Indices · Commodities · Rates</div>
    <div className="pl-market-band">
      {cards.map((card, i) => (
        <div key={i} className="pl-mb-card">
          <div className="pl-mb-name">{card.name}</div>
          {loading && card.price === null ? (
            <div className="pl-shimmer" style={{ height: 16, marginTop: 6, marginBottom: 4, borderRadius: 4 }} />
          ) : (
            <div className="pl-mb-px">{fmtPrice(card.price, card.prefix === '$' ? 2 : card.suffix === '%' ? 2 : 0, card.prefix || '', card.suffix || '')}</div>
          )}
          <div className={`pl-mb-chg ${card.dir}`}>
            {card.dir === 'up' ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
            {fmtChg(card.changePct)}
          </div>
          <Sparkline pts={card.history} dir={card.dir} width={undefined} height={28} lineWidth={1.4} />
        </div>
      ))}
    </div>
  </div>
);

// ─────────────────────────────────────────────────────────────
//  Article Card
// ─────────────────────────────────────────────────────────────

const ArticleCard: React.FC<{
  item: ArticleListItem;
  onPreview: (item: ArticleListItem) => void;
  onPublish: (item: ArticleListItem) => void;
  onUnpublish: (item: ArticleListItem) => void;
}> = ({ item, onPreview, onPublish, onUnpublish }) => {
  const live = isLivePublished(item);
  const catMeta = CONTENT_TYPE_META[item.content_type as ContentType] || CONTENT_TYPE_META.manual;
  const dateStr = item.generated_at
    ? new Date(item.generated_at).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' })
    : '—';

  return (
    <div className="pl-story-card" onClick={() => onPreview(item)}>
      <div className="pl-story-top">
        <span className="pl-story-cat" style={{ color: catMeta.colour }}>{catMeta.label}</span>
        <span className={`pl-story-status ${live ? 'published' : 'draft'}`}>
          {live ? '● Published' : '○ Draft'}
        </span>
      </div>

      <h3 className="pl-story-title">{item.title || item.slug}</h3>

      {item.description && (
        <p className="pl-story-dek">{item.description.slice(0, 120)}{item.description.length > 120 ? '…' : ''}</p>
      )}

      {(item.confidence_score !== undefined || item.editorial_quality_score !== undefined) && (
        <div className="pl-metric-row">
          {item.confidence_score !== undefined && (
            <span className="pl-metric-chip">
              <span className="label">Conf</span>
              <span className="value" style={{ color: item.confidence_score >= 0.7 ? '#34D399' : item.confidence_score >= 0.4 ? '#FBBF24' : '#FB7185' }}>
                {Math.round(item.confidence_score * 100)}%
              </span>
            </span>
          )}
          {item.editorial_quality_score !== undefined && (
            <span className="pl-metric-chip">
              <span className="label">Quality</span>
              <span className="value">{item.editorial_quality_score}/10</span>
            </span>
          )}
          {item.ikg_covered && (
            <span className="pl-metric-chip">
              <span className="value" style={{ color: '#60A5FA' }}>IKG ✓</span>
            </span>
          )}
        </div>
      )}

      <div className="pl-story-foot" onClick={(e) => e.stopPropagation()}>
        <span className="pl-story-date">{dateStr}</span>
        <div className="pl-story-actions">
          <button className="pl-story-btn" onClick={(e) => { e.stopPropagation(); onPreview(item); }}>
            <BarChart2 size={11} /> Review
          </button>
          {live ? (
            <button className="pl-story-btn" onClick={(e) => { e.stopPropagation(); onUnpublish(item); }}>
              Unpublish
            </button>
          ) : (
            <button className="pl-story-btn publish" onClick={(e) => { e.stopPropagation(); onPublish(item); }}>
              Publish →
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────
//  Shared button styles
// ─────────────────────────────────────────────────────────────

const labelStyle: React.CSSProperties = {
  display: 'block',
  marginBottom: 6,
  fontSize: 11,
  fontWeight: 700,
  color: 'var(--text-muted)',
  letterSpacing: '0.06em',
  textTransform: 'uppercase',
  fontFamily: 'var(--font-mono)',
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '11px 12px',
  borderRadius: 10,
  border: '1px solid rgba(255,255,255,0.08)',
  background: 'rgba(255,255,255,0.03)',
  color: 'var(--text-primary)',
  fontSize: 13,
  outline: 'none',
};

const actionButtonStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 8,
  padding: '10px 14px',
  borderRadius: 10,
  border: '1px solid rgba(96,165,250,0.25)',
  background: 'rgba(96,165,250,0.12)',
  color: 'var(--accent-cyan)',
  cursor: 'pointer',
  fontSize: 12,
  fontWeight: 600,
};

const secondaryButtonStyle: React.CSSProperties = {
  ...actionButtonStyle,
  border: '1px solid rgba(255,255,255,0.08)',
  background: 'rgba(255,255,255,0.03)',
  color: 'var(--text-secondary)',
};

// ─────────────────────────────────────────────────────────────
//  Main component
// ─────────────────────────────────────────────────────────────

const InsightsStudio: React.FC = () => {
  // ── Generate form state ──
  const [contentType, setContentType] = useState<ContentType>('earnings');
  const [target, setTarget] = useState('');
  const [objective, setObjective] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);

  // ── Jobs & articles ──
  const [activeJobs, setActiveJobs] = useState<ActiveJob[]>([]);
  const [articles, setArticles] = useState<ArticleListItem[]>([]);
  const [loadingArticles, setLoadingArticles] = useState(false);
  const [reviewArticle, setReviewArticle] = useState<ArticleListItem | null>(null);
  const [readerDetail, setReaderDetail] = useState<ArticleDetail | null>(null);

  // ── View / filter ──
  const [viewMode, setViewMode] = useState<ViewMode>('cards');
  const [filterCat, setFilterCat] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');

  // ── Market data ──
  const [indices, setIndices] = useState<MarketIndex[]>(DEFAULT_INDICES);
  const [mbCards, setMbCards] = useState<MarketCard[]>(DEFAULT_MB_CARDS);
  const [marketLoading, setMarketLoading] = useState(true);

  // ── Automation ──
  const [automationStatus, setAutomationStatus] = useState<AutomationStatus | null>(null);
  const [automationLoading, setAutomationLoading] = useState(false);
  const [automationLoadError, setAutomationLoadError] = useState<string | null>(null);

  // ── Generate ──
  const [generateLoading, setGenerateLoading] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null);

  const showToast = useCallback((msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type });
    window.setTimeout(() => setToast(null), 3500);
  }, []);

  // ─────────────────────────────────────────────
  //  Market data loader
  // ─────────────────────────────────────────────

  const loadMarketData = useCallback(async () => {
    try {
      const data = await getMarketIndices();
      if (!data) return;

      // Parse indices
      const idxMap: Record<string, any> = {};
      const raw = Array.isArray(data) ? data : (data.indices || data.data || []);
      raw.forEach((item: any) => {
        const sym = (item.symbol || item.index || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
        idxMap[sym] = item;
      });

      const parseIdx = (sym: string, fallback: MarketIndex): MarketIndex => {
        const candidates = [sym, sym.replace('50', ''), sym + '50'];
        let q: any = null;
        for (const c of candidates) {
          if (idxMap[c]) { q = idxMap[c]; break; }
        }
        if (!q) return fallback;
        const price = q.price ?? q.value ?? q.last ?? fallback.price;
        const chgPct = q.change_pct ?? q.pct_change ?? q.changePct ?? fallback.changePct;
        const change = q.change ?? fallback.change;
        const dir: 'up' | 'down' = (chgPct ?? 0) >= 0 ? 'up' : 'down';
        const history: number[] = q.history || q.spark || fallback.history;
        return { ...fallback, price, changePct: chgPct, change, dir, history };
      };

      setIndices((prev) => prev.map((idx) => parseIdx(idx.symbol, idx)));

      // Market band cards — try to match from same data
      const parseMB = (card: MarketCard): MarketCard => {
        const sym = card.symbol.toUpperCase().replace(/[^A-Z0-9]/g, '');
        const q = idxMap[sym];
        if (!q) return card;
        const price = q.price ?? q.value ?? q.last ?? card.price;
        const chgPct = q.change_pct ?? q.pct_change ?? q.changePct ?? card.changePct;
        const dir: 'up' | 'down' = (chgPct ?? 0) >= 0 ? 'up' : 'down';
        const history: number[] = q.history || q.spark || card.history;
        return { ...card, price, changePct: chgPct, dir, history };
      };
      setMbCards((prev) => prev.map(parseMB));
    } catch (_) {
      // silent — defaults remain
    } finally {
      setMarketLoading(false);
    }
  }, []);

  useEffect(() => {
    loadMarketData();
    const id = window.setInterval(loadMarketData, 90000);
    return () => window.clearInterval(id);
  }, [loadMarketData]);

  // ─────────────────────────────────────────────
  //  Articles loader
  // ─────────────────────────────────────────────

  const loadArticles = useCallback(async () => {
    setLoadingArticles(true);
    try {
      const { items } = await listContentArticles('insights', 100);
      setArticles(items.sort((a, b) => (b.generated_at ?? '').localeCompare(a.generated_at ?? '')));
    } catch (error) {
      console.error('Failed to load articles', error);
    } finally {
      setLoadingArticles(false);
    }
  }, []);

  // ─────────────────────────────────────────────
  //  Automation loader
  // ─────────────────────────────────────────────

  const loadAutomation = useCallback(async () => {
    try {
      setAutomationLoadError(null);
      const next = await getContentAutomationStatus();
      setAutomationStatus(next);
    } catch (error) {
      console.error('Failed to load automation status', error);
      setAutomationLoadError('Automation status is unavailable. Check the active backend connection.');
    }
  }, []);

  useEffect(() => {
    loadArticles();
    loadAutomation();
  }, [loadArticles, loadAutomation]);

  useEffect(() => {
    const id = window.setInterval(loadAutomation, 30000);
    return () => window.clearInterval(id);
  }, [loadAutomation]);

  const openReader = useCallback(async (item: ArticleListItem) => {
    try {
      const detail = await getContentArticle(item.slug, item.route_base || 'insights');
      setReaderDetail(detail);
    } catch (e) {
      console.warn('article reader load failed', e);
    }
  }, []);

  // ─────────────────────────────────────────────
  //  Actions
  // ─────────────────────────────────────────────

  const handleGenerate = async () => {
    if (!target.trim()) { setGenerateError('A company, event, or topic is required.'); return; }
    setGenerateError(null);
    setGenerateLoading(true);
    try {
      const req: FlashGenerationRequest = {
        mode: 'research',
        content_type: contentType,
        target: target.trim(),
        objective: objective.trim() || undefined,
        source_url: sourceUrl.trim() || undefined,
        route_base: 'insights',
        include_image: true,
        overwrite: true,
      };
      const { job_id } = await generateFlashArticle(req);
      setActiveJobs((prev) => [{ jobId: job_id, mode: 'research', label: target.trim() }, ...prev]);
      showToast(`Research workflow started: ${job_id.slice(0, 8)}`);
    } catch (error: any) {
      setGenerateError(error.message || 'Failed to start research workflow');
      showToast(error.message || 'Failed to start research workflow', 'error');
    } finally {
      setGenerateLoading(false);
    }
  };

  const handleAutomationRun = async () => {
    setAutomationLoading(true);
    try {
      const { job_id } = await runContentAutomationNow();
      setActiveJobs((prev) => [{ jobId: job_id, mode: 'automation', label: 'Official-source sweep' }, ...prev]);
      showToast(`Official-source sweep started: ${job_id.slice(0, 8)}`);
    } catch (error: any) {
      showToast(error.message || 'Failed to start official-source sweep', 'error');
    } finally {
      setAutomationLoading(false);
    }
  };

  const handlePublish = async (article: ArticleListItem) => {
    try {
      const updated = await publishContentArticle(article.slug, article.route_base);
      setArticles((prev) => prev.map((e) => e.slug === article.slug ? {
        ...e,
        publish_status: (updated.publish_status as 'draft' | 'published') || 'published',
        publish_gate_status: (updated.publish_gate_status as 'draft' | 'publish') || 'publish',
      } : e));
      await loadArticles();
      showToast(`Published: ${article.slug}`);
    } catch (error: any) {
      showToast(error.message || 'Publish failed', 'error');
    }
  };

  const handleUnpublish = async (article: ArticleListItem) => {
    try {
      const updated = await unpublishContentArticle(article.slug, article.route_base);
      setArticles((prev) => prev.map((e) => e.slug === article.slug ? {
        ...e,
        publish_status: (updated.publish_status as 'draft' | 'published') || 'draft',
        publish_gate_status: (updated.publish_gate_status as 'draft' | 'publish') || 'draft',
      } : e));
      await loadArticles();
      showToast(`Moved back to draft: ${article.slug}`);
    } catch (error: any) {
      showToast(error.message || 'Unpublish failed', 'error');
    }
  };

  const handleJobComplete = async (jobId?: string) => {
    if (jobId) setActiveJobs((prev) => prev.filter((j) => j.jobId !== jobId));
    await Promise.all([loadArticles(), loadAutomation()]);
  };

  const handleStatusChanged = (slug: string, newStatus: 'draft' | 'published') => {
    setArticles((prev) => prev.map((e) => e.slug === slug ? {
      ...e,
      publish_status: newStatus,
      publish_gate_status: newStatus === 'published' ? 'publish' : 'draft',
    } : e));
    setReviewArticle(null);
  };

  // ─────────────────────────────────────────────
  //  Derived state
  // ─────────────────────────────────────────────

  const stats = useMemo(() => ({
    total: articles.length,
    published: articles.filter(isLivePublished).length,
    drafts: articles.filter((i) => !isLivePublished(i)).length,
    sourceBacked: articles.filter((i) => i.ikg_covered).length,
  }), [articles]);

  const filteredArticles = useMemo(() => {
    let result = articles;
    if (filterCat !== 'all') {
      result = result.filter((a) => a.content_type === filterCat);
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      result = result.filter((a) =>
        (a.title || '').toLowerCase().includes(q) ||
        (a.description || '').toLowerCase().includes(q) ||
        (a.slug || '').toLowerCase().includes(q)
      );
    }
    return result;
  }, [articles, filterCat, searchQuery]);

  // ─── Automation labels ───
  const lastSummary = automationStatus?.last_summary || {};
  const currentRun = automationStatus?.current_run || {};
  const activityLog = (automationStatus?.activity_log || []).slice(0, 6);
  const recentItems = (automationStatus?.recent_items || []).slice(0, 4);
  const automationStatusLabel = automationStatus
    ? (AUTOMATION_STATUS_LABELS[automationStatus.status || 'idle'] || automationStatus.status || 'checking status')
    : (automationLoadError ? 'status unavailable' : 'checking status');
  const automationStatusColour = automationStatus?.status === 'running'
    ? 'var(--accent-cyan)'
    : automationStatus?.status === 'scheduled' ? 'var(--profit)'
    : automationStatus?.status === 'offline' ? 'var(--loss)'
    : automationStatus?.status === 'disabled' || automationStatus?.status === 'manual_only' ? '#FBBF24'
    : automationLoadError ? 'var(--loss)' : '#FBBF24';
  const lastRunLabel = automationStatus?.last_completed_at
    ? new Date(automationStatus.last_completed_at).toLocaleString()
    : automationLoadError ? 'backend status unavailable' : 'not available';
  const heartbeatLabel = automationStatus?.scheduler_last_heartbeat_at
    ? new Date(automationStatus.scheduler_last_heartbeat_at).toLocaleString()
    : 'not available';
  const nextRunLabel = automationStatus?.next_scheduled_run_at
    ? new Date(automationStatus.next_scheduled_run_at).toLocaleString()
    : 'not available';
  const currentPhaseLabel = currentRun.phase
    ? String(currentRun.phase).replace(/_/g, ' ')
    : automationStatus?.status === 'running' ? 'starting' : 'standing by';
  const currentFocusParts = [currentRun.company, currentRun.source ? String(currentRun.source).toUpperCase() : ''].filter(Boolean);
  const currentFocusLabel = currentFocusParts.length > 0 ? currentFocusParts.join(' - ') : 'Queue-level monitoring';
  const fallbackDailyTarget = automationStatus?.fallback_daily_target ?? 10;
  const fallbackPublishedToday = automationStatus?.fallback_published_today ?? automationStatus?.fallback_daily_count ?? 0;
  const fallbackRemainingToday = automationStatus?.fallback_remaining_today ?? Math.max(0, fallbackDailyTarget - fallbackPublishedToday);
  const searchConsole = automationStatus?.search_console;
  const searchConsoleLabel = !searchConsole?.enabled ? 'disabled'
    : !searchConsole?.configured ? 'needs setup'
    : searchConsole?.error ? 'connected with warnings' : 'connected';

  // ─────────────────────────────────────────────
  //  Render
  // ─────────────────────────────────────────────

  return (
    <AppShell title="Insights Studio">
      <div className="insights-studio">

        {/* ── Ticker strip ── */}
        <TickerStrip />

        {/* ── Page header ── */}
        <div className="insights-studio__header">
          <div className="insights-studio__header-row">
            <div className="insights-studio__title-group">
              <div className="insights-studio__title-line">
                <Newspaper size={20} color="var(--accent-cyan)" />
                <span className="insights-studio__title">Insights Studio</span>
                <span className="insights-studio__badge">
                  <Sparkles size={11} />
                  Editorial Research
                </span>
              </div>
              <p className="insights-studio__subtitle">
                Each story is drafted for clean public reading, checked for evidence and compliance,
                and then routed through publication gates. Official filings stay first in line.
              </p>
            </div>

            {/* Article stats */}
            <div className="insights-studio__stats">
              {[
                { label: 'Total', value: stats.total, colour: 'var(--text-primary)' },
                { label: 'Published', value: stats.published, colour: 'var(--profit)' },
                { label: 'Drafts', value: stats.drafts, colour: '#FBBF24' },
                { label: 'Source-backed', value: stats.sourceBacked, colour: 'var(--accent-cyan)' },
              ].map((item) => (
                <div key={item.label} className="insights-studio__stat">
                  <div className="insights-studio__stat-value" style={{ color: item.colour }}>{item.value}</div>
                  <div className="insights-studio__stat-label">{item.label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── Main 2-column layout ── */}
        <div className="insights-studio__main">

          {/* ── LEFT SIDEBAR ── */}
          <aside className="insights-studio__sidebar">

            {/* Generate form */}
            <section className="data-panel">
              <div className="data-panel-head">
                <span className="data-panel-title">Generate Research Article</span>
              </div>
              <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div className="insights-panel-copy">
                  All articles use the same deep editorial workflow: official-source retrieval,
                  verified context enrichment, structured drafting, paragraph-level review, and
                  auto-publish only when the draft clears the quality gate.
                </div>

                {/* Content type */}
                <div>
                  <label style={labelStyle}>Content Type</label>
                  <div className="insights-type-grid">
                    {(Object.keys(CONTENT_TYPE_META) as ContentType[]).map((entry) => {
                      const meta = CONTENT_TYPE_META[entry];
                      const active = contentType === entry;
                      return (
                        <button
                          key={entry}
                          type="button"
                          className="insights-type-button"
                          onClick={() => setContentType(entry)}
                          style={{
                            borderColor: active ? `${meta.colour}44` : 'rgba(255,255,255,0.08)',
                            background: active ? `${meta.colour}14` : 'transparent',
                          }}
                        >
                          <div style={{ fontSize: 12, fontWeight: 700, color: active ? meta.colour : 'var(--text-primary)' }}>
                            {meta.label}
                          </div>
                          <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                            {meta.desc}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Target input */}
                <div>
                  <label style={labelStyle}>
                    {contentType === 'trend' || contentType === 'manual' ? 'Topic' : 'Company / Subject'}
                  </label>
                  <input
                    value={target}
                    onChange={(e) => setTarget(e.target.value)}
                    placeholder={
                      contentType === 'earnings' ? 'e.g. Infosys Q3 FY26 results' :
                      contentType === 'sebi' ? 'e.g. SEBI order against a listed company' :
                      contentType === 'trend' ? 'e.g. Domestic defence capex cycle' :
                      contentType === 'company' ? 'e.g. Reliance Industries' :
                      'e.g. Midcap chemicals pricing reset'
                    }
                    style={inputStyle}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleGenerate(); }}
                  />
                </div>

                {/* Advanced toggle */}
                <button
                  type="button"
                  onClick={() => setShowAdvanced((p) => !p)}
                  style={{ ...secondaryButtonStyle, justifyContent: 'space-between' }}
                >
                  <span>Advanced context</span>
                  <span>{showAdvanced ? 'Hide' : 'Show'}</span>
                </button>

                {showAdvanced && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <div>
                      <label style={labelStyle}>Custom Objective</label>
                      <textarea
                        value={objective}
                        onChange={(e) => setObjective(e.target.value)}
                        placeholder="Add a sharper editorial angle, publication goal, or scenario to validate."
                        rows={3}
                        style={{ ...inputStyle, resize: 'vertical', minHeight: 86, fontFamily: 'inherit' }}
                      />
                    </div>
                    <div>
                      <label style={labelStyle}>Primary Source URL</label>
                      <input
                        value={sourceUrl}
                        onChange={(e) => setSourceUrl(e.target.value)}
                        placeholder="https://www.bseindia.com/..."
                        style={inputStyle}
                      />
                    </div>
                  </div>
                )}

                {generateError && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--loss)', fontSize: 12 }}>
                    <AlertTriangle size={14} />
                    <span>{generateError}</span>
                  </div>
                )}

                <button
                  type="button"
                  onClick={handleGenerate}
                  disabled={generateLoading || !target.trim()}
                  style={{
                    ...actionButtonStyle,
                    width: '100%',
                    opacity: generateLoading || !target.trim() ? 0.6 : 1,
                    cursor: generateLoading || !target.trim() ? 'not-allowed' : 'pointer',
                  }}
                >
                  {generateLoading ? <RefreshCcw size={14} className="animate-spin-custom" /> : <Send size={14} />}
                  <span>{generateLoading ? 'Starting workflow...' : 'Start research article'}</span>
                </button>

                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: 12, borderRadius: 10, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                  <Info size={14} color="var(--text-muted)" style={{ marginTop: 2, flexShrink: 0 }} />
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6 }}>
                    The editorial gate checks headings, paragraphs, sourcing, compliance language, and
                    publish urgency before a draft goes live. Weak drafts stay in review.
                  </div>
                </div>
              </div>
            </section>

            {/* Active workflows */}
            {activeJobs.length > 0 && (
              <section>
                <div style={{ marginBottom: 8, fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontFamily: 'var(--font-mono)' }}>
                  Active Workflows
                </div>
                <div className="insights-job-stack">
                  {activeJobs.map((job) => (
                    <FlashJobMonitor
                      key={job.jobId}
                      jobId={job.jobId}
                      mode={job.mode}
                      label={job.label}
                      onComplete={() => handleJobComplete(job.jobId)}
                    />
                  ))}
                </div>
              </section>
            )}

            {/* Automation health */}
            <section className="data-panel">
              <div className="data-panel-head">
                <span className="data-panel-title">Automation Health</span>
              </div>
              <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
                {/* Status grid */}
                <div className="insights-form-grid">
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Status</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: automationStatusColour, textTransform: 'capitalize' }}>
                      {automationStatusLabel}
                    </div>
                    <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>
                      Last run {lastRunLabel}
                    </div>
                  </div>
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>24/7 Mode</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
                      {automationStatus?.automation_label || 'Official-source monitor'}
                    </div>
                    <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>
                      {automationStatus?.status_detail || automationLoadError || 'Monitor chooses publishable topics from official-source updates.'}
                    </div>
                  </div>
                </div>

                {/* Source health badges */}
                <div className="insights-health-badges">
                  {(['nse', 'bse', 'sebi'] as const).map((source) => {
                    const health = automationStatus?.source_health?.[source] || {};
                    const ok = !health.last_error;
                    return (
                      <span key={source} className="insights-health-badge" style={{ color: ok ? 'var(--profit)' : '#FBBF24' }}>
                        <Activity size={11} />
                        {source.toUpperCase()}
                      </span>
                    );
                  })}
                </div>

                {/* Run stats grid */}
                <div className="insights-automation-grid">
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Current Phase</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', textTransform: 'capitalize' }}>{currentPhaseLabel}</div>
                    <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>{currentFocusLabel}</div>
                  </div>
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Next Sweep</div>
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>{nextRunLabel}</div>
                  </div>
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Discovered</div>
                    <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{lastSummary.discovered ?? 0}</div>
                  </div>
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Published / Held</div>
                    <div style={{ fontSize: 18, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                      {lastSummary.published ?? 0} / {lastSummary.drafts ?? 0}
                    </div>
                  </div>
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Fallback Today</div>
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', textTransform: 'capitalize' }}>
                      {fallbackPublishedToday}/{fallbackDailyTarget} published
                    </div>
                    <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                      {fallbackRemainingToday} remaining today
                    </div>
                  </div>
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Search Console</div>
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)', textTransform: 'capitalize' }}>
                      {searchConsoleLabel}
                    </div>
                    <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                      {searchConsole?.site_url || 'Configure Search Console credentials.'}
                    </div>
                  </div>
                </div>

                {/* Heartbeat */}
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  Scheduler heartbeat: {heartbeatLabel}
                </div>

                {/* Action buttons */}
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button type="button" onClick={loadAutomation} style={secondaryButtonStyle}>
                    <RefreshCcw size={13} /> Refresh
                  </button>
                  <button type="button" onClick={handleAutomationRun} disabled={automationLoading} style={actionButtonStyle}>
                    {automationLoading ? <RefreshCcw size={13} className="animate-spin-custom" /> : <FileSearch size={13} />}
                    Run sweep now
                  </button>
                  <a href="/insights/research/" target="_blank" rel="noopener noreferrer" style={{ ...secondaryButtonStyle, textDecoration: 'none' }}>
                    <Globe size={13} /> Public site
                  </a>
                </div>

                {/* Activity log */}
                <div className="insights-automation-list">
                  {activityLog.length === 0 ? (
                    <div className="insights-panel-copy">Live automation steps will appear here while the monitor is scanning.</div>
                  ) : activityLog.map((item, i) => (
                    <div key={`${item.timestamp || i}`} className="insights-automation-item">
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', overflowWrap: 'anywhere' }}>
                          {item.message || 'Automation update'}
                        </div>
                        <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                          {item.phase ? String(item.phase).replace(/_/g, ' ') : 'status'} · {item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : ''}
                        </div>
                      </div>
                      <div style={{ fontSize: 10, fontWeight: 700, color: item.level === 'error' ? 'var(--loss)' : item.level === 'warning' ? '#FBBF24' : item.level === 'success' ? 'var(--profit)' : 'var(--accent-cyan)', textTransform: 'uppercase', fontFamily: 'var(--font-mono)', flexShrink: 0 }}>
                        {item.level || 'info'}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Recent items */}
                {recentItems.length > 0 && (
                  <div className="insights-automation-list">
                    {recentItems.map((item, i) => (
                      <div key={`${item.slug || i}`} className="insights-automation-item">
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', overflowWrap: 'anywhere' }}>
                            {item.title || item.slug || 'Untitled item'}
                          </div>
                          <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                            {item.source?.toUpperCase()} · {item.timestamp ? new Date(item.timestamp).toLocaleString() : ''}
                          </div>
                        </div>
                        <div style={{ fontSize: 10, fontWeight: 700, color: item.status === 'published' ? 'var(--profit)' : item.status === 'failed' ? 'var(--loss)' : '#FBBF24', textTransform: 'uppercase', fontFamily: 'var(--font-mono)', flexShrink: 0 }}>
                          {item.status || 'queued'}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>
          </aside>

          {/* ── RIGHT CONTENT AREA ── */}
          <div className="insights-studio__content">
            <div className="insights-main-content">

              {/* Market data zone */}
              <div className="insights-market-zone">
                {/* Market snapshot + band side by side — responsive via pl-market-zone-grid */}
                <div className="pl-market-zone-grid">
                  <MarketSnap indices={indices} loading={marketLoading} />
                  <MarketBand cards={mbCards} loading={marketLoading} />
                </div>
              </div>

              {/* Article queue zone */}
              <div className="insights-queue-zone">
                {/* Queue header with search + filters + view toggle */}
                <div className="pl-queue-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flex: 1, flexWrap: 'wrap' }}>
                    <div className="pl-section-label">Research Queue</div>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                      {filteredArticles.length} {filteredArticles.length === 1 ? 'story' : 'stories'}
                    </span>
                  </div>

                  <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                    {/* Search */}
                    <div className="pl-search-box">
                      <svg className="pl-search-icon" width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                        <circle cx={11} cy={11} r={7} /><line x1={16.5} y1={16.5} x2={21} y2={21} />
                      </svg>
                      <input
                        type="search"
                        className="pl-search-input"
                        placeholder="Search articles…"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                      />
                    </div>

                    {/* View toggle */}
                    <div className="pl-view-toggle">
                      <button className={`pl-view-btn ${viewMode === 'cards' ? 'active' : ''}`} onClick={() => setViewMode('cards')}>
                        <Grid size={13} /> Cards
                      </button>
                      <button className={`pl-view-btn ${viewMode === 'table' ? 'active' : ''}`} onClick={() => setViewMode('table')}>
                        <LayoutList size={13} /> Table
                      </button>
                    </div>

                    {/* Refresh */}
                    <button onClick={loadArticles} style={secondaryButtonStyle}>
                      <RefreshCcw size={13} className={loadingArticles ? 'animate-spin-custom' : ''} />
                    </button>
                  </div>
                </div>

                {/* Filter chips */}
                <div className="pl-filter-chips" style={{ marginBottom: 16 }}>
                  {CATEGORY_FILTERS.map((f) => (
                    <button
                      key={f.key}
                      className={`pl-filter-chip ${filterCat === f.key ? 'active' : ''}`}
                      onClick={() => setFilterCat(f.key)}
                    >
                      {f.label}
                    </button>
                  ))}
                </div>

                {/* Article queue view */}
                {loadingArticles ? (
                  <div className="pl-article-grid">
                    {Array.from({ length: 6 }).map((_, i) => (
                      <div key={i} style={{ borderRadius: 14, border: '1px solid rgba(255,255,255,0.05)', overflow: 'hidden' }}>
                        <div className="pl-shimmer" style={{ height: 140 }} />
                      </div>
                    ))}
                  </div>
                ) : filteredArticles.length === 0 ? (
                  <div className="pl-empty-state">
                    <Newspaper size={32} color="var(--text-muted)" />
                    <h3>No stories match that filter</h3>
                    <p>Try a different keyword or category filter. New research articles appear here after generation completes.</p>
                  </div>
                ) : viewMode === 'cards' ? (
                  <div className="pl-article-grid">
                    {filteredArticles.map((item) => (
                      <ArticleCard
                        key={item.slug}
                        item={item}
                        onPreview={(a) => { openReader(a); setReviewArticle(a); }}
                        onPublish={handlePublish}
                        onUnpublish={handleUnpublish}
                      />
                    ))}
                  </div>
                ) : (
                  <ArticleQueueTable
                    articles={filteredArticles}
                    loading={loadingArticles}
                    onRefresh={loadArticles}
                    onPreview={(item) => { openReader(item); setReviewArticle(item); }}
                    onPublish={handlePublish}
                    onUnpublish={handleUnpublish}
                  />
                )}
              </div>
            </div>
          </div>
        </div>

        {/* ── Toast ── */}
        {toast && (
          <div style={{
            position: 'fixed', bottom: 18, right: 18, left: 'auto',
            maxWidth: 'min(420px, calc(100vw - 32px))',
            zIndex: 1200, padding: '12px 14px', borderRadius: 10,
            border: `1px solid ${toast.type === 'success' ? 'rgba(52,211,153,0.3)' : 'rgba(251,113,133,0.3)'}`,
            background: toast.type === 'success' ? 'rgba(52,211,153,0.12)' : 'rgba(251,113,133,0.12)',
            color: toast.type === 'success' ? 'var(--profit)' : 'var(--loss)',
            fontSize: 12, fontWeight: 600, overflowWrap: 'anywhere',
          }}>
            {toast.msg}
          </div>
        )}

        {/* ── Drawers ── */}
        <DraftReviewDrawer
          article={reviewArticle}
          onClose={() => setReviewArticle(null)}
          onStatusChanged={handleStatusChanged}
        />

        {readerDetail && (
          <ArticleReader detail={readerDetail} onClose={() => setReaderDetail(null)} />
        )}
      </div>
    </AppShell>
  );
};

export default InsightsStudio;

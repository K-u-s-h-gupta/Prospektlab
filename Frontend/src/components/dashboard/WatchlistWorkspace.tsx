import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
} from 'chart.js';
import { Line } from 'react-chartjs-2';
import {
  ExternalLink,
  Search,
  Settings2,
  TrendingDown,
  TrendingUp,
  X,
} from 'lucide-react';
import { getMarketQuotes, getWatchlistSnapshot, MarketHistoryPeriod } from '../../api/client';
import { INDIAN_STOCKS, POPULAR_MUTUAL_FUNDS } from '../../data/indianStocks';
import type { WatchlistStock } from './WatchlistCard';
import { buildProspektCover } from '../../utils/coverArt';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);

type MoversRange = '1D' | '1M' | '6M' | 'YTD' | '1Y' | '5Y' | 'MAX';

interface WatchlistWorkspaceProps {
  symbols: string[];
  stocks: WatchlistStock[];
  onChangeSymbols: (next: string[]) => void;
  onSelectStock: (symbol: string) => void;
  onAskStock?: (symbol: string) => void;
}

interface WatchlistNewsItem {
  id: string;
  symbol: string;
  headline: string;
  source: string;
  time: string;
  url: string;
  image: string;
  fallbackImage: string;
}

interface SymbolHistory {
  symbol: string;
  dates: string[];
  prices: number[];
}

interface MovementEvent {
  key: string;
  symbol?: string;
  dateIso?: string;
  dateLabel: string;
  priceLabel: string;
  pctLabel: string;
  direction: 'up' | 'down';
  summary: string;
  sourceCount: number;
}

interface LiveQuoteSnapshot {
  symbol: string;
  name: string;
  price: number;
  changePct: number;
}

interface IntradayPoint {
  ts: number;
  price: number;
}

const RANGE_OPTIONS: MoversRange[] = ['1D', '1M', '6M', 'YTD', '1Y', '5Y', 'MAX'];
const LINE_COLORS = ['#38bdf8', '#f97316', '#facc15', '#c084fc', '#22c55e', '#ef4444', '#2dd4bf', '#fb7185'];
const WATCHLIST_ONBOARDING_SYMBOLS = ['RELIANCE', 'TCS', 'INFY', 'HDFCBANK', 'ICICIBANK', 'SBIN'];

const normalizeSymbol = (value: string) =>
  String(value || '').split('.')[0].toUpperCase().trim();

const normalizeNewsUrl = (raw: string) => {
  const value = String(raw || '').trim();
  if (!value) return '';
  try {
    const parsed = new URL(value.startsWith('//') ? `https:${value}` : value);
    parsed.hash = '';
    return parsed.toString();
  } catch {
    return value;
  }
};

const historyPeriodForRange = (range: MoversRange): MarketHistoryPeriod => {
  if (range === '1D') return '1M';
  if (range === '5Y') return 'MAX';
  return range;
};

const parseIsoDate = (value: string): number => {
  const ts = Date.parse(value);
  return Number.isFinite(ts) ? ts : 0;
};

const filterSeriesForRange = (dates: string[], prices: number[], range: MoversRange) => {
  if (dates.length < 2 || prices.length < 2) return { dates: [], prices: [] };
  if (range === '1D') {
    const start = Math.max(0, dates.length - 24);
    return { dates: dates.slice(start), prices: prices.slice(start) };
  }
  if (range === '5Y') {
    const latest = parseIsoDate(dates[dates.length - 1]);
    if (!latest) return { dates, prices };
    const cutoff = new Date(latest);
    cutoff.setFullYear(cutoff.getFullYear() - 5);
    const cutoffTs = cutoff.getTime();
    const kept: Array<{ date: string; price: number }> = [];
    for (let idx = 0; idx < dates.length; idx += 1) {
      const ts = parseIsoDate(dates[idx]);
      if (ts >= cutoffTs) {
        kept.push({ date: dates[idx], price: prices[idx] });
      }
    }
    if (kept.length < 2) return { dates, prices };
    return { dates: kept.map((row) => row.date), prices: kept.map((row) => row.price) };
  }
  return { dates, prices };
};

const formatDateShort = (isoDate: string) => {
  const parsed = new Date(isoDate);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return parsed.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
};

const formatDateLong = (isoDate: string) => {
  const parsed = new Date(isoDate);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return parsed.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
};

const parseDisplayPrice = (value: string | number): number => {
  if (typeof value === 'number') return Number.isFinite(value) ? value : 0;
  const cleaned = String(value || '').replace(/[^0-9.-]/g, '');
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : 0;
};

const formatSignedNumber = (value: number, digits = 2): string =>
  `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`;

const formatIntradayLabel = (ts: number): string =>
  new Date(ts).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' });

const formatMovementLabel = (ts: number): string =>
  new Date(ts).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: 'numeric', minute: '2-digit' });

const toINR = (value: number) =>
  Number.isFinite(value) ? `\u20B9${value.toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '\u20B9--';

const fallbackCover = (seed: string, title = '', symbol = '', source = '') =>
  buildProspektCover({
    seed,
    title: title || seed,
    source,
    symbol,
    kind: 'watchlist',
    label: 'Watchlist Brief',
  });

const findDisplayName = (symbol: string, fallbackName = '') => {
  const clean = normalizeSymbol(symbol);
  const stock = INDIAN_STOCKS.find((row) => row.symbol.toUpperCase() === clean);
  if (stock) return stock.name;
  const mf = POPULAR_MUTUAL_FUNDS.find((row) => row.symbol.toUpperCase() === clean);
  if (mf) return mf.name;
  return fallbackName || clean;
};

export const WatchlistWorkspace: React.FC<WatchlistWorkspaceProps> = ({
  symbols,
  stocks,
  onChangeSymbols,
  onSelectStock,
  onAskStock,
}) => {
  const [range, setRange] = useState<MoversRange>('1D');
  const [isManageOpen, setIsManageOpen] = useState(false);
  const [manageQuery, setManageQuery] = useState('');
  const [draftSymbols, setDraftSymbols] = useState<string[]>(symbols);
  const [histories, setHistories] = useState<Record<string, SymbolHistory>>({});
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [watchlistNews, setWatchlistNews] = useState<WatchlistNewsItem[]>([]);
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsError, setNewsError] = useState<string | null>(null);
  const [selectedMovementSymbol, setSelectedMovementSymbol] = useState<string>(symbols[0] || '');
  const [liveQuotes, setLiveQuotes] = useState<Record<string, LiveQuoteSnapshot>>({});
  const [intradaySeries, setIntradaySeries] = useState<Record<string, IntradayPoint[]>>({});
  const [dailyMovementSummaries, setDailyMovementSummaries] = useState<MovementEvent[]>([]);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const autoPromptRef = useRef(false);

  useEffect(() => {
    setDraftSymbols(symbols);
    if (!selectedMovementSymbol && symbols.length > 0) {
      setSelectedMovementSymbol(symbols[0]);
    }
    if (selectedMovementSymbol && !symbols.includes(selectedMovementSymbol) && symbols.length > 0) {
      setSelectedMovementSymbol(symbols[0]);
    }
    if (symbols.length === 0) {
      setSelectedMovementSymbol('');
    }
  }, [symbols, selectedMovementSymbol]);

  useEffect(() => {
    if (symbols.length > 0) {
      autoPromptRef.current = false;
      return;
    }
    if (autoPromptRef.current) return;
    autoPromptRef.current = true;
    setDraftSymbols([]);
    setManageQuery('');
    setIsManageOpen(true);
  }, [symbols]);

  useEffect(() => {
    if (symbols.length === 0) return;
    const intervalMs = range === '1D' ? 45000 : 90000;
    const interval = window.setInterval(() => {
      setRefreshNonce((prev) => prev + 1);
    }, intervalMs);
    return () => window.clearInterval(interval);
  }, [symbols, range]);

  const symbolOptions = useMemo(() => {
    const items = [...INDIAN_STOCKS.slice(0, 2400), ...POPULAR_MUTUAL_FUNDS];
    const query = manageQuery.trim().toLowerCase();
    if (!query) return items.slice(0, 40).map((row) => ({ symbol: row.symbol, name: row.name }));
    return items
      .filter((row) => row.symbol.toLowerCase().includes(query) || row.name.toLowerCase().includes(query))
      .slice(0, 80)
      .map((row) => ({ symbol: row.symbol, name: row.name }));
  }, [manageQuery]);

  useEffect(() => {
    let cancelled = false;
    const fetchSnapshot = async () => {
      if (symbols.length === 0) {
        setLiveQuotes({});
        setHistories({});
        setHistoryError(null);
        setWatchlistNews([]);
        setNewsError(null);
        setDailyMovementSummaries([]);
        return;
      }

      setHistoryLoading(true);
      setNewsLoading(true);
      setHistoryError(null);
      setNewsError(null);

      try {
        const period = historyPeriodForRange(range);
        const snapshot = await getWatchlistSnapshot(symbols.slice(0, 12), period);
        if (cancelled) return;

        const nextLive: Record<string, LiveQuoteSnapshot> = {};
        (snapshot.quotes || []).forEach((row: any) => {
          const symbol = normalizeSymbol(String(row.symbol || ''));
          const price = Number(row.price);
          const changePct = Number(row.change_pct);
          if (!symbol || !Number.isFinite(price) || price <= 0) return;
          nextLive[symbol] = {
            symbol,
            name: String(row.name || findDisplayName(symbol, symbol)),
            price,
            changePct: Number.isFinite(changePct) ? changePct : 0,
          };
        });
        if (Object.keys(nextLive).length > 0) {
          setLiveQuotes((prev) => ({ ...prev, ...nextLive }));
        } else {
          try {
            const fallbackQuotes = await getMarketQuotes(symbols.slice(0, 20));
            if (!cancelled && fallbackQuotes && typeof fallbackQuotes === 'object') {
              const fallbackLive: Record<string, LiveQuoteSnapshot> = {};
              Object.entries(fallbackQuotes).forEach(([rawSymbol, row]: [string, any]) => {
                const symbol = normalizeSymbol(rawSymbol);
                const price = Number(row?.price);
                const changePct = Number(row?.change_pct);
                if (!symbol || !Number.isFinite(price) || price <= 0) return;
                fallbackLive[symbol] = {
                  symbol,
                  name: String(row?.company_name || findDisplayName(symbol, symbol)),
                  price,
                  changePct: Number.isFinite(changePct) ? changePct : 0,
                };
              });
              if (Object.keys(fallbackLive).length > 0) {
                setLiveQuotes((prev) => ({ ...prev, ...fallbackLive }));
              }
            }
          } catch {
            // ignore fallback quote failures
          }
        }

        const nextHistories: Record<string, SymbolHistory> = {};
        Object.values(snapshot.histories || {}).forEach((row: any) => {
          const symbol = normalizeSymbol(String(row.symbol || ''));
          if (!symbol || !Array.isArray(row.dates) || !Array.isArray(row.prices)) return;
          const filtered = filterSeriesForRange(row.dates, row.prices, range);
          if (filtered.dates.length < 2) return;
          nextHistories[symbol] = {
            symbol,
            dates: filtered.dates,
            prices: filtered.prices,
          };
        });
        setHistories(nextHistories);
        if (range !== '1D' && Object.keys(nextHistories).length === 0) {
          setHistoryError('No chart history available right now.');
        }

        const newsItems = (snapshot.news || []).map((item: any, idx: number) => {
          const symbol = normalizeSymbol(String(item.symbol || ''));
          const headline = String(item.headline || item.title || '').trim();
          const url = normalizeNewsUrl(String(item.url || item.link || ''));
          const source = String(item.source || 'News');
          const image = fallbackCover(`${symbol}:${source}:${headline || idx}`, headline, symbol, source);
          return {
            id: String(item.id || `${symbol}-${idx}-${headline.slice(0, 18)}`),
            symbol,
            headline,
            source,
            time: String(item.time || item.published || 'Just now'),
            url,
            image,
            fallbackImage: fallbackCover(`${symbol}:${headline || idx}`, headline, symbol, source),
          } as WatchlistNewsItem;
        }).filter((item: WatchlistNewsItem) => item.headline);
        setWatchlistNews(newsItems.slice(0, 18));
        if (newsItems.length === 0) {
          setNewsError('No watchlist news found right now.');
        }

        const dailySummaries = (snapshot.daily_summaries || []).map((item: any, idx: number) => ({
          key: String(item.key || `${item.symbol || 'SYM'}-${item.date || idx}`),
          symbol: normalizeSymbol(String(item.symbol || '')),
          dateIso: String(item.date || ''),
          dateLabel: String(item.date_label || formatDateLong(String(item.date || ''))),
          priceLabel: String(item.price_label || toINR(Number(item.price || 0))),
          pctLabel: String(item.pct_label || `${Number(item.pct || 0).toFixed(2)}%`),
          direction: Number(item.pct || 0) >= 0 ? 'up' : 'down',
          summary: String(item.summary || ''),
          sourceCount: Number(item.source_count || 0),
        } as MovementEvent))
          .filter((item: MovementEvent) => Boolean(item.symbol))
          .sort((a: MovementEvent, b: MovementEvent) => parseIsoDate(b.dateIso || '') - parseIsoDate(a.dateIso || ''));
        setDailyMovementSummaries(dailySummaries);
      } catch (err: any) {
        if (!cancelled) {
          const message = err?.message || 'Unable to load watchlist intelligence snapshot.';
          try {
            const fallbackQuotes = await getMarketQuotes(symbols.slice(0, 20));
            if (!cancelled && fallbackQuotes && typeof fallbackQuotes === 'object') {
              const nextLive: Record<string, LiveQuoteSnapshot> = {};
              Object.entries(fallbackQuotes).forEach(([rawSymbol, row]: [string, any]) => {
                const symbol = normalizeSymbol(rawSymbol);
                const price = Number(row?.price);
                const changePct = Number(row?.change_pct);
                if (!symbol || !Number.isFinite(price) || price <= 0) return;
                nextLive[symbol] = {
                  symbol,
                  name: String(row?.company_name || findDisplayName(symbol, symbol)),
                  price,
                  changePct: Number.isFinite(changePct) ? changePct : 0,
                };
              });
              if (Object.keys(nextLive).length > 0) {
                setLiveQuotes((prev) => ({ ...prev, ...nextLive }));
              }
            }
          } catch {
            // ignore fallback quote failures
          }
          setHistoryError('Detailed watchlist history is temporarily unavailable. Showing live quotes.');
          setNewsError(message);
        }
      } finally {
        if (!cancelled) {
          setHistoryLoading(false);
          setNewsLoading(false);
        }
      }
    };

    fetchSnapshot();
    return () => {
      cancelled = true;
    };
  }, [symbols, range, refreshNonce]);

  const normalizedStocks = useMemo(() => {
    const bySymbol = new Map<string, WatchlistStock>();
    stocks.forEach((row) => bySymbol.set(normalizeSymbol(row.symbol), row));
    return symbols.map((symbol) => {
      const normalized = normalizeSymbol(symbol);
      const linked = bySymbol.get(normalized);
      const live = liveQuotes[normalized];
      if (live) {
        const moveValue = live.price * (live.changePct / 100);
        return {
          symbol: normalized,
          name: live.name || linked?.name || findDisplayName(normalized, normalized),
          price: live.price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
          change: formatSignedNumber(moveValue, 2),
          changePct: live.changePct,
        };
      }
      return linked || {
        symbol: normalized,
        name: findDisplayName(normalized, normalized),
        price: '--',
        change: '--',
        changePct: 0,
      };
    });
  }, [symbols, stocks, liveQuotes]);

  useEffect(() => {
    if (symbols.length === 0) {
      setIntradaySeries({});
      return;
    }
    const active = new Set(symbols.map((row) => normalizeSymbol(row)));
    const now = Date.now();
    const cutoff = now - 24 * 60 * 60 * 1000;
    setIntradaySeries((prev) => {
      let changed = false;
      const next: Record<string, IntradayPoint[]> = {};
      active.forEach((symbol) => {
        const base = (prev[symbol] || []).filter((row) => row.ts >= cutoff);
        const stock = normalizedStocks.find((row) => normalizeSymbol(row.symbol) === symbol);
        const price = parseDisplayPrice(stock?.price ?? 0);
        if (!Number.isFinite(price) || price <= 0) {
          if (base.length > 0) next[symbol] = base;
          return;
        }
        const last = base[base.length - 1];
        const shouldAppend = !last || Math.abs(last.price - price) > 0.0001 || now - last.ts >= 60_000;
        const updated = shouldAppend ? [...base, { ts: now, price }] : base;
        if (shouldAppend || updated.length !== (prev[symbol] || []).length) changed = true;
        next[symbol] = updated.slice(-360);
      });
      if (!changed && Object.keys(prev).length === Object.keys(next).length) return prev;
      return next;
    });
  }, [symbols, normalizedStocks]);

  const normalizedSeries = useMemo(() => {
    const buildHistorySeries = () => {
      const seriesList = symbols
        .map((symbol) => histories[normalizeSymbol(symbol)])
        .filter((row): row is SymbolHistory => Boolean(row));
      if (seriesList.length === 0) return { labels: [] as string[], datasets: [] as any[] };

      const labelSet = new Set<string>();
      seriesList.forEach((row) => row.dates.forEach((date) => labelSet.add(date)));
      const labels = Array.from(labelSet).sort((a, b) => parseIsoDate(a) - parseIsoDate(b));
      const datasets = seriesList
        .map((row, idx) => {
          const color = LINE_COLORS[idx % LINE_COLORS.length];
          const byDate = new Map<string, number>();
          row.dates.forEach((date, rowIdx) => byDate.set(date, row.prices[rowIdx]));
          const firstPrice = row.prices.find((value) => Number.isFinite(value) && value > 0) || 0;
          if (firstPrice <= 0) return null;
          let lastPrice: number | null = null;
          const data = labels.map((date) => {
            const price = byDate.get(date);
            if (typeof price === 'number' && Number.isFinite(price) && price > 0) {
              lastPrice = price;
            }
            if (lastPrice === null) return null;
            return Number((((lastPrice - firstPrice) / firstPrice) * 100).toFixed(2));
          });
          const pointCount = data.filter((value): value is number => typeof value === 'number').length;
          if (pointCount === 0) return null;
          return {
            label: normalizeSymbol(row.symbol),
            data,
            borderColor: color,
            pointRadius: pointCount === 1 ? 2.5 : 0,
            pointHoverRadius: 3,
            borderWidth: 2,
            tension: 0.25,
            spanGaps: true,
          };
        })
        .filter((dataset): dataset is any => Boolean(dataset));
      return {
        labels: labels.map((date) => formatDateShort(date)),
        datasets,
      };
    };

    const historySeries = buildHistorySeries();

    if (range === '1D') {
      const labelKeys = new Set<number>();
      const seriesRows = symbols
        .map((symbol) => {
          const normalized = normalizeSymbol(symbol);
          const points = (intradaySeries[normalized] || []).slice(-240);
          if (points.length < 2) return null;
          const bucketed = new Map<number, number>();
          points.forEach((row) => {
            const bucket = Math.floor(row.ts / 60000) * 60000;
            bucketed.set(bucket, row.price);
            labelKeys.add(bucket);
          });
          return { symbol: normalized, bucketed };
        })
        .filter((row): row is { symbol: string; bucketed: Map<number, number> } => Boolean(row));
      const labelsRaw = Array.from(labelKeys).sort((a, b) => a - b);
      const datasets = seriesRows
        .map((row, idx) => {
          const color = LINE_COLORS[idx % LINE_COLORS.length];
          const firstAtSharedStart = labelsRaw.length > 0 ? row.bucketed.get(labelsRaw[0]) : undefined;
          const firstPrice = (
            (typeof firstAtSharedStart === 'number' && firstAtSharedStart > 0 ? firstAtSharedStart : undefined)
            || Array.from(row.bucketed.values()).find((value) => Number.isFinite(value) && value > 0)
            || 0
          );
          if (firstPrice <= 0) return null;
          let lastPrice: number | null = null;
          const data = labelsRaw.map((labelKey) => {
            const price = row.bucketed.get(labelKey);
            if (typeof price === 'number' && Number.isFinite(price) && price > 0) {
              lastPrice = price;
            }
            if (lastPrice === null) return null;
            return Number((((lastPrice - firstPrice) / firstPrice) * 100).toFixed(2));
          });
          const pointCount = data.filter((value): value is number => typeof value === 'number').length;
          if (pointCount === 0) return null;
          return {
            label: row.symbol,
            data,
            borderColor: color,
            pointRadius: pointCount === 1 ? 2.5 : 0,
            pointHoverRadius: 3,
            borderWidth: 2,
            tension: 0.25,
            spanGaps: true,
          };
        })
        .filter((dataset): dataset is any => Boolean(dataset));

      const hasRenderableIntraday =
        labelsRaw.length >= 2
        && datasets.some((dataset) => dataset.data.filter((value: number | null) => typeof value === 'number').length >= 2);

      if (!hasRenderableIntraday && historySeries.datasets.length > 0) {
        return historySeries;
      }
      return {
        labels: labelsRaw.map((ts) => formatIntradayLabel(ts)),
        datasets,
      };
    }

    return historySeries;
  }, [range, symbols, histories, intradaySeries]);

  const topMoverSymbol = useMemo(() => {
    if (normalizedStocks.length === 0) return '';
    const sorted = [...normalizedStocks].sort((a, b) => Math.abs(b.changePct) - Math.abs(a.changePct));
    return sorted[0]?.symbol || '';
  }, [normalizedStocks]);

  useEffect(() => {
    if (!selectedMovementSymbol && topMoverSymbol) {
      setSelectedMovementSymbol(topMoverSymbol);
    }
  }, [selectedMovementSymbol, topMoverSymbol]);

  const movementEvents = useMemo(() => {
    const focus = normalizeSymbol(selectedMovementSymbol || topMoverSymbol);
    if (!focus) return [] as MovementEvent[];
    const monthlyRows = dailyMovementSummaries.filter((item) => normalizeSymbol(item.symbol || '') === focus);
    if (monthlyRows.length > 0) {
      return monthlyRows.slice(0, 35);
    }
    const focusIntraday = (intradaySeries[focus] || []).slice(-180);
    if (focusIntraday.length >= 2) {
      const rows: Array<{ ts: number; pct: number; price: number }> = [];
      for (let idx = 1; idx < focusIntraday.length; idx += 1) {
        const prev = focusIntraday[idx - 1].price;
        const cur = focusIntraday[idx].price;
        if (!prev || prev <= 0 || !cur) continue;
        rows.push({
          ts: focusIntraday[idx].ts,
          pct: ((cur - prev) / prev) * 100,
          price: cur,
        });
      }
      const biggest = [...rows]
        .sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct))
        .slice(0, 3);
      return biggest.map((row, idx) => {
        const related = watchlistNews
          .filter((item) => normalizeSymbol(item.symbol) === focus)
          .slice(idx * 2, idx * 2 + 2);
        const newsLead = related[0]?.headline
          ? `News flow: ${related[0].headline}`
          : `${findDisplayName(focus)} moved ${row.pct >= 0 ? 'higher' : 'lower'} during live trading.`;
        return {
          key: `${focus}-${row.ts}-${idx}`,
          dateLabel: formatMovementLabel(row.ts),
          priceLabel: toINR(row.price),
          pctLabel: `${row.pct >= 0 ? '+' : ''}${row.pct.toFixed(2)}%`,
          direction: row.pct >= 0 ? 'up' : 'down',
          summary: newsLead,
          sourceCount: related.length,
        };
      });
    }

    const series = histories[focus];
    if (!series || series.dates.length < 2) {
      const stock = normalizedStocks.find((row) => normalizeSymbol(row.symbol) === focus);
      if (!stock) return [];
      return [
        {
          key: `${focus}-fallback`,
          dateLabel: 'Latest',
          priceLabel: `\u20B9${stock.price}`,
          pctLabel: `${stock.changePct >= 0 ? '+' : ''}${stock.changePct.toFixed(2)}%`,
          direction: stock.changePct >= 0 ? 'up' : 'down',
          summary: `${stock.name} is moving today. Load more history to unlock detailed movement explanations.`,
          sourceCount: 0,
        },
      ];
    }
    const rows: Array<{ date: string; pct: number; price: number }> = [];
    for (let idx = 1; idx < series.dates.length; idx += 1) {
      const prev = series.prices[idx - 1];
      const cur = series.prices[idx];
      if (!prev || prev <= 0 || !cur) continue;
      rows.push({
        date: series.dates[idx],
        pct: ((cur - prev) / prev) * 100,
        price: cur,
      });
    }
    const biggest = [...rows]
      .sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct))
      .slice(0, 3);
    return biggest.map((row, idx) => {
      const related = watchlistNews.filter((item) => normalizeSymbol(item.symbol) === focus).slice(idx * 2, idx * 2 + 2);
      const newsLead = related[0]?.headline
        ? `News flow: ${related[0].headline}`
        : `${findDisplayName(focus)} moved ${row.pct >= 0 ? 'higher' : 'lower'} on heightened market activity.`;
      return {
        key: `${focus}-${row.date}-${idx}`,
        dateLabel: formatDateLong(row.date),
        priceLabel: toINR(row.price),
        pctLabel: `${row.pct >= 0 ? '+' : ''}${row.pct.toFixed(2)}%`,
        direction: row.pct >= 0 ? 'up' : 'down',
        summary: newsLead,
        sourceCount: related.length,
      };
    });
  }, [selectedMovementSymbol, topMoverSymbol, dailyMovementSummaries, histories, intradaySeries, watchlistNews, normalizedStocks]);

  const toggleDraftSymbol = (symbol: string) => {
    const target = normalizeSymbol(symbol);
    setDraftSymbols((prev) => {
      if (prev.includes(target)) return prev.filter((row) => row !== target);
      return [...prev, target];
    });
  };

  const saveDraft = () => {
    const next = Array.from(new Set(draftSymbols.map((row) => normalizeSymbol(row)).filter(Boolean)));
    onChangeSymbols(next);
    setIsManageOpen(false);
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index' as const, intersect: false },
    plugins: {
      legend: {
        display: true,
        labels: {
          color: '#9ca3af',
          boxWidth: 12,
          usePointStyle: true,
          pointStyle: 'line',
        },
      },
      tooltip: {
        backgroundColor: 'rgba(15,23,42,0.98)',
        borderColor: 'rgba(148,163,184,0.35)',
        borderWidth: 1,
        titleColor: '#e2e8f0',
        bodyColor: '#cbd5e1',
        callbacks: {
          label: (context: any) => `${context.dataset.label}: ${Number(context.parsed.y || 0).toFixed(2)}%`,
        },
      },
    },
    scales: {
      x: {
        grid: { color: 'rgba(148,163,184,0.12)' },
        ticks: { color: '#94a3b8', maxTicksLimit: 6 },
      },
      y: {
        grid: { color: 'rgba(148,163,184,0.12)' },
        ticks: {
          color: '#94a3b8',
          callback: (value: any) => `${Number(value).toFixed(0)}%`,
        },
      },
    },
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button
          type="button"
          className="data-panel-link"
          onClick={() => {
            setDraftSymbols(symbols);
            setManageQuery('');
            setIsManageOpen(true);
          }}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
        >
          <Settings2 size={12} /> Manage watchlist
        </button>
      </div>

      {symbols.length > 0 ? (
        <>
          <div className="data-panel" style={{ padding: 14 }}>
            <div className="data-panel-head" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 10 }}>
              <div className="data-panel-title">Watchlist movers</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {RANGE_OPTIONS.map((option) => (
                  <button
                    key={option}
                    type="button"
                    onClick={() => setRange(option)}
                    style={{
                      borderRadius: 7,
                      border: `1px solid ${range === option ? 'rgba(56,189,248,0.45)' : 'rgba(148,163,184,0.22)'}`,
                      background: range === option ? 'rgba(56,189,248,0.14)' : 'transparent',
                      color: range === option ? 'var(--text-primary)' : 'var(--text-muted)',
                      padding: '3px 8px',
                      fontSize: 10.5,
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    {option}
                  </button>
                ))}
              </div>
            </div>
            <div style={{ height: 280, marginTop: 12 }}>
              {range !== '1D' && historyLoading ? (
                <div className="research-empty">Loading movers chart...</div>
              ) : normalizedSeries.datasets.length === 0 ? (
                <div className="research-empty">
                  {range === '1D' ? 'Waiting for live price updates...' : (historyError || 'History is unavailable for selected symbols.')}
                </div>
              ) : (
                <Line data={normalizedSeries} options={chartOptions} />
              )}
            </div>
            <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {normalizedStocks.map((stock) => {
                const isUp = stock.changePct >= 0;
                return (
                  <div
                    key={stock.symbol}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'minmax(120px,1.8fr) 1fr auto auto auto',
                      gap: 10,
                      alignItems: 'center',
                      border: '1px solid rgba(148,163,184,0.15)',
                      background: 'rgba(15,23,42,0.33)',
                      borderRadius: 10,
                      padding: '10px 12px',
                    }}
                  >
                    <button
                      type="button"
                      onClick={() => onSelectStock(stock.symbol)}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 10,
                        border: 'none',
                        background: 'transparent',
                        color: 'inherit',
                        cursor: 'pointer',
                        minWidth: 0,
                        textAlign: 'left',
                        padding: 0,
                      }}
                    >
                      <span
                        style={{
                          width: 28,
                          height: 28,
                          borderRadius: 7,
                          background: 'rgba(56,189,248,0.16)',
                          display: 'inline-flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontSize: 11,
                          fontWeight: 700,
                          color: 'var(--accent-cyan)',
                          flexShrink: 0,
                        }}
                      >
                        {stock.symbol.slice(0, 1)}
                      </span>
                      <span style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{stock.name}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{stock.symbol}</div>
                      </span>
                    </button>
                    <div style={{ justifySelf: 'end', fontSize: 13, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                      {'\u20B9'}{stock.price}
                    </div>
                    <div style={{ justifySelf: 'end', fontSize: 12, color: isUp ? 'var(--profit)' : 'var(--loss)' }}>
                      {stock.change}
                    </div>
                    <div
                      style={{
                        justifySelf: 'end',
                        fontSize: 11,
                        fontWeight: 700,
                        color: isUp ? 'var(--profit)' : 'var(--loss)',
                        border: `1px solid ${isUp ? 'rgba(34,197,94,0.35)' : 'rgba(239,68,68,0.35)'}`,
                        background: isUp ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
                        borderRadius: 7,
                        padding: '4px 8px',
                        minWidth: 84,
                        textAlign: 'center',
                      }}
                    >
                      {isUp ? <TrendingUp size={11} style={{ verticalAlign: 'text-bottom' }} /> : <TrendingDown size={11} style={{ verticalAlign: 'text-bottom' }} />}
                      {' '}
                      {Math.abs(stock.changePct).toFixed(2)}%
                    </div>
                    <div style={{ justifySelf: 'end', display: 'flex', gap: 6 }}>
                      {onAskStock && (
                        <button
                          type="button"
                          onClick={() => onAskStock(stock.symbol)}
                          style={{
                            border: '1px solid rgba(56,189,248,0.26)',
                            background: 'rgba(56,189,248,0.09)',
                            color: 'var(--accent-cyan)',
                            borderRadius: 7,
                            padding: '4px 8px',
                            fontSize: 10.5,
                            cursor: 'pointer',
                          }}
                        >
                          Ask
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => onChangeSymbols(symbols.filter((row) => normalizeSymbol(row) !== normalizeSymbol(stock.symbol)))}
                        title="Remove from watchlist"
                        style={{
                          border: '1px solid rgba(239,68,68,0.32)',
                          background: 'rgba(239,68,68,0.08)',
                          color: 'var(--loss)',
                          borderRadius: 7,
                          width: 28,
                          height: 28,
                          cursor: 'pointer',
                        }}
                      >
                        <X size={13} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="data-panel" style={{ padding: 14 }}>
            <div className="data-panel-head" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 10 }}>
              <div className="data-panel-title">Notable price movement</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <select
                  value={selectedMovementSymbol}
                  onChange={(event) => setSelectedMovementSymbol(event.target.value)}
                  style={{
                    borderRadius: 7,
                    border: '1px solid rgba(148,163,184,0.24)',
                    background: 'rgba(15,23,42,0.6)',
                    color: 'var(--text-primary)',
                    fontSize: 12,
                    padding: '5px 8px',
                  }}
                >
                  {symbols.map((symbol) => (
                    <option key={symbol} value={symbol}>{normalizeSymbol(symbol)}</option>
                  ))}
                </select>
              </div>
            </div>
            <div style={{ marginTop: 12, maxHeight: 420, overflowY: 'auto', paddingRight: 6, display: 'flex', flexDirection: 'column', gap: 12 }}>
              {movementEvents.length === 0 ? (
                <div className="research-empty">Not enough movement data yet.</div>
              ) : movementEvents.map((item) => (
                <div key={item.key} style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: 14 }}>
                  <div style={{ color: 'var(--text-muted)', fontSize: 12, fontWeight: 600 }}>{item.dateLabel}</div>
                  <div style={{ borderLeft: '2px solid rgba(148,163,184,0.25)', paddingLeft: 14 }}>
                    <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap', marginBottom: 6 }}>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 17, color: 'var(--text-primary)', fontWeight: 700 }}>{item.priceLabel}</span>
                      <span style={{ color: item.direction === 'up' ? 'var(--profit)' : 'var(--loss)', fontSize: 17, fontWeight: 700 }}>
                        {item.pctLabel}
                      </span>
                    </div>
                    <div style={{ color: 'var(--text-secondary)', fontSize: 15, lineHeight: 1.45 }}>{item.summary}</div>
                    <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text-muted)' }}>
                      {item.sourceCount > 0 ? `${item.sourceCount} source${item.sourceCount > 1 ? 's' : ''}` : 'No linked sources yet'}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="data-panel" style={{ padding: 14 }}>
            <div className="data-panel-head" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 10 }}>
              <div className="data-panel-title">Watchlist news</div>
              <span className="section-sublabel">SYMBOL-FOCUSED</span>
            </div>
            <div style={{ marginTop: 12 }}>
              {newsLoading ? (
                <div className="research-empty">Loading watchlist news...</div>
              ) : newsError ? (
                <div className="research-empty">{newsError}</div>
              ) : (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px, 1fr))', gap: 12 }}>
                  {watchlistNews.map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => {
                        if (item.url) window.open(item.url, '_blank', 'noopener,noreferrer');
                      }}
                      style={{
                        border: '1px solid rgba(148,163,184,0.18)',
                        background: 'rgba(15,23,42,0.33)',
                        borderRadius: 10,
                        overflow: 'hidden',
                        textAlign: 'left',
                        padding: 0,
                        cursor: item.url ? 'pointer' : 'default',
                        display: 'flex',
                        flexDirection: 'column',
                      }}
                    >
                      <img
                        src={item.image || item.fallbackImage}
                        alt={`${item.headline} cover`}
                        loading="lazy"
                        onError={(event) => {
                          const target = event.currentTarget;
                          target.onerror = null;
                          target.src = item.fallbackImage;
                        }}
                        style={{ width: '100%', height: 118, objectFit: 'cover' }}
                      />
                      <div style={{ padding: 10, display: 'flex', flexDirection: 'column', gap: 6 }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                          <span style={{ fontSize: 10.5, color: 'var(--accent-cyan)', fontWeight: 700 }}>{normalizeSymbol(item.symbol)}</span>
                          <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>{item.source}</span>
                        </div>
                        <div style={{ fontSize: 12.5, color: 'var(--text-primary)', lineHeight: 1.35, display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                          {item.headline}
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>{item.time}</span>
                          {item.url && <ExternalLink size={12} color="var(--text-muted)" />}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      ) : (
        <div className="data-panel" style={{ padding: 18 }}>
          <div className="data-panel-head" style={{ marginBottom: 10 }}>
            <div className="data-panel-title">Build your watchlist</div>
            <span className="section-sublabel">ADD SYMBOLS TO START LIVE TRACKING</span>
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.6, marginBottom: 12 }}>
            Your watchlist is currently empty. Add symbols to unlock live movers, notable price movement, and watchlist-specific news.
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {WATCHLIST_ONBOARDING_SYMBOLS.map((symbol) => (
              <button
                key={symbol}
                type="button"
                onClick={() => onChangeSymbols(Array.from(new Set([...symbols, symbol])))}
                style={{
                  border: '1px solid rgba(56,189,248,0.3)',
                  background: 'rgba(56,189,248,0.1)',
                  color: 'var(--text-primary)',
                  borderRadius: 999,
                  padding: '6px 12px',
                  fontSize: 11,
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                + {symbol}
              </button>
            ))}
          </div>
          <div style={{ marginTop: 14 }}>
            <button
              type="button"
              className="data-panel-link"
              onClick={() => {
                setDraftSymbols(symbols.length > 0 ? symbols : WATCHLIST_ONBOARDING_SYMBOLS.slice(0, 3));
                setManageQuery('');
                setIsManageOpen(true);
              }}
            >
              Open full watchlist manager
            </button>
          </div>
        </div>
      )}

      {isManageOpen && createPortal((
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(3,7,18,0.72)',
            backdropFilter: 'blur(4px)',
            zIndex: 1300,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 14,
          }}
          onClick={() => setIsManageOpen(false)}
        >
          <div
            className="data-panel"
            style={{ width: 'min(920px, 100%)', maxHeight: '84vh', overflow: 'auto', padding: 16 }}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="data-panel-head" style={{ borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: 10 }}>
              <div className="data-panel-title">Manage watchlist</div>
              <button
                type="button"
                onClick={() => setIsManageOpen(false)}
                style={{
                  border: '1px solid rgba(148,163,184,0.24)',
                  background: 'transparent',
                  color: 'var(--text-secondary)',
                  borderRadius: 7,
                  width: 28,
                  height: 28,
                  cursor: 'pointer',
                }}
              >
                <X size={14} />
              </button>
            </div>

            <div style={{ marginTop: 12 }}>
              <label style={{ display: 'block', marginBottom: 8, fontSize: 11, color: 'var(--text-muted)', fontWeight: 600 }}>Search symbols</label>
              <div style={{ position: 'relative' }}>
                <Search size={13} color="var(--text-muted)" style={{ position: 'absolute', left: 10, top: 10 }} />
                <input
                  value={manageQuery}
                  onChange={(event) => setManageQuery(event.target.value)}
                  placeholder="Type ticker or company name"
                  style={{
                    width: '100%',
                    padding: '8px 10px 8px 30px',
                    borderRadius: 8,
                    border: '1px solid rgba(148,163,184,0.25)',
                    background: 'rgba(2,6,23,0.45)',
                    color: 'var(--text-primary)',
                    fontSize: 12,
                  }}
                />
              </div>
            </div>

            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>Selected ({draftSymbols.length})</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {draftSymbols.length === 0 ? (
                  <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>No symbols selected.</span>
                ) : draftSymbols.map((symbol) => (
                  <button
                    key={symbol}
                    type="button"
                    onClick={() => toggleDraftSymbol(symbol)}
                    style={{
                      border: '1px solid rgba(56,189,248,0.24)',
                      background: 'rgba(56,189,248,0.08)',
                      color: 'var(--accent-cyan)',
                      borderRadius: 999,
                      padding: '4px 10px',
                      fontSize: 11,
                      fontWeight: 600,
                      cursor: 'pointer',
                    }}
                  >
                    {symbol} x
                  </button>
                ))}
              </div>
            </div>

            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>Suggestions</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(230px,1fr))', gap: 8 }}>
                {symbolOptions.map((item) => {
                  const selected = draftSymbols.includes(normalizeSymbol(item.symbol));
                  return (
                    <button
                      key={item.symbol}
                      type="button"
                      onClick={() => toggleDraftSymbol(item.symbol)}
                      style={{
                        border: `1px solid ${selected ? 'rgba(56,189,248,0.35)' : 'rgba(148,163,184,0.22)'}`,
                        background: selected ? 'rgba(56,189,248,0.1)' : 'rgba(15,23,42,0.35)',
                        color: selected ? 'var(--text-primary)' : 'var(--text-secondary)',
                        borderRadius: 8,
                        padding: '8px 9px',
                        textAlign: 'left',
                        cursor: 'pointer',
                      }}
                    >
                      <div style={{ fontSize: 11.5, fontWeight: 700 }}>{item.symbol}</div>
                      <div style={{ fontSize: 10.5, color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {item.name}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
              <button
                type="button"
                onClick={() => setIsManageOpen(false)}
                style={{
                  border: '1px solid rgba(148,163,184,0.28)',
                  background: 'transparent',
                  color: 'var(--text-secondary)',
                  borderRadius: 8,
                  padding: '7px 12px',
                  fontSize: 12,
                  cursor: 'pointer',
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={saveDraft}
                style={{
                  border: '1px solid rgba(56,189,248,0.35)',
                  background: 'rgba(56,189,248,0.16)',
                  color: 'var(--text-primary)',
                  borderRadius: 8,
                  padding: '7px 12px',
                  fontSize: 12,
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                Save watchlist
              </button>
            </div>
          </div>
        </div>
      ), document.body)}
    </div>
  );
};

export default WatchlistWorkspace;


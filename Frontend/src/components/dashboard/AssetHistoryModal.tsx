import React, { useEffect, useMemo, useState } from 'react';
import { X, Loader2, AlertCircle } from 'lucide-react';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';
import { ChartColors } from '../charts/ThemeProvider';
import { getMarketHistory, MarketHistoryPeriod, MarketHistoryResponse } from '../../api/client';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend, Filler);

export interface AssetHistoryTarget {
  symbol: string;
  name?: string;
  assetType?: string;
}

interface AssetHistoryModalProps {
  asset: AssetHistoryTarget | null;
  onClose: () => void;
}

const PERIODS: MarketHistoryPeriod[] = ['1M', '3M', '6M', 'YTD', '1Y', 'MAX'];

const formatDate = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' });
};

const formatPrice = (value: number, currency?: string) => {
  if (!Number.isFinite(value)) return '-';
  if (currency && /^[A-Z]{3}$/.test(currency)) {
    try {
      return new Intl.NumberFormat('en-IN', {
        style: 'currency',
        currency,
        maximumFractionDigits: value >= 100 ? 2 : 4,
      }).format(value);
    } catch {
      // Fall through to compact numeric formatting.
    }
  }
  return value.toLocaleString('en-IN', {
    maximumFractionDigits: value >= 100 ? 2 : 4,
  });
};

export const AssetHistoryModal: React.FC<AssetHistoryModalProps> = ({ asset, onClose }) => {
  const [period, setPeriod] = useState<MarketHistoryPeriod>('1Y');
  const [data, setData] = useState<MarketHistoryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!asset) return;
    setPeriod('1Y');
  }, [asset?.symbol]);

  useEffect(() => {
    if (!asset) return;
    let cancelled = false;

    const fetchHistory = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await getMarketHistory(asset.symbol, period, asset.assetType);
        if (!cancelled) {
          setData(response);
        }
      } catch (err: any) {
        if (!cancelled) {
          setError(err?.message || 'Market history is unavailable.');
          setData(null);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    fetchHistory();
    return () => {
      cancelled = true;
    };
  }, [asset, period]);

  useEffect(() => {
    if (!asset) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [asset, onClose]);

  const validPoints = useMemo(() => {
    if (!data) return [];
    return data.dates
      .map((date, idx) => ({ date, price: Number(data.prices[idx]) }))
      .filter(point => point.date && Number.isFinite(point.price) && point.price > 0);
  }, [data]);

  const latest = validPoints[validPoints.length - 1];
  const first = validPoints[0];
  const changePct = data?.change_pct ?? (first && latest && first.price > 0
    ? ((latest.price - first.price) / first.price) * 100
    : undefined);
  const isPositive = (changePct ?? 0) >= 0;

  const chartData = {
    labels: validPoints.map(point => formatDate(point.date)),
    datasets: [
      {
        label: data?.name || asset?.name || asset?.symbol || 'Asset',
        data: validPoints.map(point => point.price),
        borderColor: isPositive ? ChartColors.primary : '#fb7185',
        backgroundColor: (ctx: any) => {
          const chart = ctx.chart;
          const { ctx: c, chartArea } = chart;
          if (!chartArea) return 'rgba(56, 189, 248, 0.12)';
          const gradient = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
          gradient.addColorStop(0, isPositive ? 'rgba(56, 189, 248, 0.22)' : 'rgba(251, 113, 133, 0.18)');
          gradient.addColorStop(1, 'rgba(2, 6, 23, 0)');
          return gradient;
        },
        borderWidth: 2,
        fill: true,
        tension: 0.22,
        pointRadius: 0,
        pointHoverRadius: 4,
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index' as const, intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: ChartColors.surface,
        titleColor: ChartColors.textPrimary,
        bodyColor: ChartColors.textSecondary,
        borderColor: ChartColors.grid,
        borderWidth: 1,
        callbacks: {
          label: (context: any) => {
            const value = Number(context.parsed.y);
            return `Price: ${formatPrice(value, data?.currency)}`;
          },
        },
      },
    },
    scales: {
      x: {
        grid: { color: 'rgba(148, 163, 184, 0.08)' },
        ticks: {
          color: ChartColors.textSecondary,
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 7,
        },
      },
      y: {
        grid: { color: 'rgba(148, 163, 184, 0.08)' },
        ticks: {
          color: ChartColors.textSecondary,
          callback: (value: any) => formatPrice(Number(value), data?.currency),
        },
      },
    },
  };

  if (!asset) return null;

  const title = asset.name || data?.name || asset.symbol;
  const sourceText = data?.source || 'market data';
  const showEmpty = !loading && !error && validPoints.length < 2;

  return (
    <div className="asset-history-backdrop" onClick={onClose}>
      <div
        className="asset-history-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`${title} historical performance`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="asset-history-head">
          <div className="asset-history-title-wrap">
            <div className="asset-history-eyebrow">{data?.asset_type || asset.assetType || 'Tracked asset'}</div>
            <h2 className="asset-history-title">{title}</h2>
            <div className="asset-history-meta">
              <span>{data?.symbol || asset.symbol}</span>
              <span>{sourceText}</span>
              {data?.as_of && <span>as of {formatDate(data.as_of)}</span>}
            </div>
          </div>
          <button className="asset-history-close" type="button" aria-label="Close history" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <div className="asset-history-stats">
          <div>
            <span className="asset-history-stat-label">Last price</span>
            <strong>{latest ? formatPrice(latest.price, data?.currency) : '-'}</strong>
          </div>
          <div>
            <span className="asset-history-stat-label">{period} change</span>
            <strong style={{ color: isPositive ? 'var(--profit)' : 'var(--loss)' }}>
              {changePct === undefined ? '-' : `${isPositive ? '+' : ''}${changePct.toFixed(2)}%`}
            </strong>
          </div>
        </div>

        <div className="asset-history-controls" aria-label="History period">
          {PERIODS.map(item => (
            <button
              key={item}
              type="button"
              className={period === item ? 'active' : ''}
              onClick={() => setPeriod(item)}
            >
              {item}
            </button>
          ))}
        </div>

        <div className="asset-history-chart">
          {loading && (
            <div className="asset-history-state">
              <Loader2 size={18} className="asset-history-spin" />
              <span>Loading real market history...</span>
            </div>
          )}

          {!loading && error && (
            <div className="asset-history-state">
              <AlertCircle size={18} />
              <span>{error}</span>
            </div>
          )}

          {showEmpty && (
            <div className="asset-history-state">
              <AlertCircle size={18} />
              <span>{data?.message || 'No data available right now.'}</span>
            </div>
          )}

          {!loading && !error && validPoints.length >= 2 && (
            <Line data={chartData} options={chartOptions} />
          )}
        </div>
      </div>
    </div>
  );
};

export default AssetHistoryModal;

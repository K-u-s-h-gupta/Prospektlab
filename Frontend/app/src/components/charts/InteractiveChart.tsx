import React, { useState, useMemo } from 'react';
import { Line } from 'react-chartjs-2';
import { 
  Chart as ChartJS, 
  CategoryScale, 
  LinearScale, 
  PointElement, 
  LineElement, 
  Title, 
  Tooltip, 
  Legend, 
  Filler 
} from 'chart.js';
import { ChartColors } from './ThemeProvider';

ChartJS.register(
  CategoryScale, 
  LinearScale, 
  PointElement, 
  LineElement, 
  Title, 
  Tooltip, 
  Legend, 
  Filler
);

export interface InteractiveChartProps {
  labels: string[];
  data: number[];
  title?: string;
  unit?: string;
  comparisonData?: number[];
  comparisonTitle?: string;
  height?: number;
}

const RANGES = ['1M', '6M', 'YTD', '1Y'] as const;
type Range = typeof RANGES[number];

const parseChartDate = (label: string): Date | null => {
  if (!label) return null;
  const direct = new Date(label);
  if (!Number.isNaN(direct.getTime())) return direct;

  const match = label.match(/^(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{2}|\d{4})$/);
  if (!match) return null;
  const [, dayText, monthText, yearText] = match;
  const month = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
    .indexOf(monthText.slice(0, 3).toLowerCase());
  if (month < 0) return null;
  const year = yearText.length === 2 ? 2000 + Number(yearText) : Number(yearText);
  const parsed = new Date(year, month, Number(dayText));
  return Number.isNaN(parsed.getTime()) ? null : parsed;
};

const shiftMonths = (date: Date, months: number) => {
  const shifted = new Date(date);
  shifted.setMonth(shifted.getMonth() + months);
  return shifted;
};

const shiftYears = (date: Date, years: number) => {
  const shifted = new Date(date);
  shifted.setFullYear(shifted.getFullYear() + years);
  return shifted;
};

const formatChartLabel = (label: string) => {
  const date = parseChartDate(label);
  return date
    ? date.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' })
    : label;
};

export const InteractiveChart: React.FC<InteractiveChartProps> = ({
  labels,
  data,
  title = 'Price',
  unit = '',
  comparisonData,
  comparisonTitle,
  height = 320,
}) => {
  const [selectedRange, setSelectedRange] = useState<Range>('1Y');

  // Calendar-date filtering and base-100 normalization using caller-provided real data.
  const filtered = useMemo(() => {
    const rows = labels.map((label, idx) => {
      const primary = Number(data[idx]);
      const comparison = comparisonData ? Number(comparisonData[idx]) : undefined;
      const hasComparison = comparisonData
        ? Number.isFinite(comparison) && Number(comparison) > 0
        : true;
      if (!Number.isFinite(primary) || primary <= 0 || !hasComparison) {
        return null;
      }
      return {
        label,
        date: parseChartDate(label),
        primary,
        comparison,
      };
    }).filter(Boolean) as Array<{ label: string; date: Date | null; primary: number; comparison?: number }>;

    if (rows.length === 0) {
      return { labels: [], data: [], comparison: undefined as number[] | undefined };
    }

    const datedRows = rows.filter(row => row.date);
    const latestDate = datedRows.length > 0 ? datedRows[datedRows.length - 1].date : null;
    let cutoffDate: Date | null = null;
    let fallbackStart = 0;

    if (latestDate) {
      switch (selectedRange) {
        case '1M': cutoffDate = shiftMonths(latestDate, -1); break;
        case '6M': cutoffDate = shiftMonths(latestDate, -6); break;
        case 'YTD': cutoffDate = new Date(latestDate.getFullYear(), 0, 1); break;
        case '1Y': cutoffDate = shiftYears(latestDate, -1); break;
      }
    } else {
      switch (selectedRange) {
        case '1M': fallbackStart = Math.max(0, rows.length - 22); break;
        case '6M': fallbackStart = Math.max(0, rows.length - 126); break;
        case 'YTD': fallbackStart = Math.max(0, Math.floor(rows.length * 0.4)); break;
        case '1Y': fallbackStart = Math.max(0, rows.length - 252); break;
      }
    }

    const slicedRows = cutoffDate
      ? rows.filter(row => row.date && row.date >= cutoffDate)
      : rows.slice(fallbackStart);
    
    const usableRows = slicedRows;
    const firstVal = usableRows[0]?.primary || 100;
    const firstComp = comparisonData ? (usableRows[0]?.comparison || 100) : 100;
    
    const normalizedData = usableRows.map(row => parseFloat(((row.primary / firstVal) * 100).toFixed(2)));
    const normalizedComp = comparisonData
      ? usableRows.map(row => parseFloat((((row.comparison || firstComp) / firstComp) * 100).toFixed(2)))
      : undefined;

    return {
      labels: usableRows.map(row => formatChartLabel(row.label)),
      data: normalizedData,
      comparison: normalizedComp,
    };
  }, [labels, data, comparisonData, selectedRange]);

  const chartData = {
    labels: filtered.labels,
    datasets: [
      {
        label: title,
        data: filtered.data,
        borderColor: ChartColors.primary,
        backgroundColor: (ctx: any) => {
          const chart = ctx.chart;
          const { ctx: c, chartArea } = chart;
          if (!chartArea) return 'rgba(56, 189, 248, 0.1)';
          const gradient = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
          gradient.addColorStop(0, ChartColors.primaryGradStart);
          gradient.addColorStop(1, ChartColors.primaryGradStop);
          return gradient;
        },
        borderWidth: 2,
        fill: true,
        tension: 0.25,
        pointRadius: 0,
        pointHoverRadius: 4,
      },
      ...(filtered.comparison ? [{
        label: comparisonTitle || 'Comparison',
        data: filtered.comparison,
        borderColor: ChartColors.secondary,
        borderWidth: 2,
        fill: false,
        tension: 0.25,
        pointRadius: 0,
      }] : []),
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index' as const, intersect: false },
    plugins: {
      legend: { display: !!comparisonData, position: 'top' as const },
      tooltip: {
        backgroundColor: ChartColors.surface,
        titleColor: ChartColors.textPrimary,
        bodyColor: ChartColors.textSecondary,
        borderColor: ChartColors.grid,
        borderWidth: 1,
        callbacks: {
          label: (context: any) => {
            const label = context.dataset.label || '';
            const val = context.parsed.y;
            const formatted = Math.abs(val) < 5 ? val.toFixed(4) : val.toFixed(2);
            return `${label}: ${formatted}${unit}`;
          }
        }
      },
    },
    scales: {
      x: { grid: { color: ChartColors.grid }, ticks: { color: ChartColors.textSecondary } },
      y: {
        grid: { color: ChartColors.grid },
        ticks: {
          color: ChartColors.textSecondary,
          callback: (val: any) => {
            const num = Number(val);
            const formatted = Math.abs(num) < 5 ? num.toFixed(4) : num.toFixed(2);
            return unit ? `${formatted} ${unit}` : formatted;
          },
        },
      },
    },
  };

  return (
    <div>
      <div className="interactive-chart-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: ChartColors.textPrimary, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '100%', flexShrink: 0 }}>{title}</div>
        <div className="chart-range-buttons" style={{ display: 'flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {RANGES.map(r => (
            <button
              key={r}
              onClick={() => setSelectedRange(r)}
              className="chart-range-btn"
              style={{
                background: selectedRange === r ? 'rgba(56, 189, 248, 0.1)' : 'transparent',
                border: '1px solid',
                borderColor: selectedRange === r ? ChartColors.primary : ChartColors.grid,
                color: selectedRange === r ? ChartColors.primary : ChartColors.textSecondary,
                padding: '2px 8px',
                borderRadius: 6,
                fontSize: 11,
                fontWeight: 600,
                cursor: 'pointer',
                whiteSpace: 'nowrap',
              }}
            >
              {r}
            </button>
          ))}
        </div>
      </div>
      <div style={{ height }}>
        {filtered.data.length > 1 ? (
          <Line data={chartData} options={options} />
        ) : (
          <div style={{
            height: '100%',
            minHeight: 180,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: ChartColors.textSecondary,
            fontSize: 12,
            textAlign: 'center',
            border: `1px dashed ${ChartColors.grid}`,
            borderRadius: 8,
            padding: 16,
          }}>
            Live historical data is not available for this range yet.
          </div>
        )}
      </div>
    </div>
  );
};

export default InteractiveChart;

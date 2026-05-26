import React, { useState, useMemo } from 'react';
import { Line } from 'react-chartjs-2';
import { ChartColors } from './ThemeProvider';

export interface InteractiveChartProps {
  labels: string[];
  data: number[];
  title?: string;
  unit?: string;
  comparisonData?: number[];
  comparisonTitle?: string;
  height?: number;
}

const RANGES = ['1D', '5D', '1M', '6M', 'YTD', '1Y', '5Y', 'MAX'] as const;
type Range = typeof RANGES[number];

export const InteractiveChart: React.FC<InteractiveChartProps> = ({
  labels,
  data,
  title = 'Price',
  unit = '',
  comparisonData,
  comparisonTitle,
  height = 320,
}) => {
  const [selectedRange, setSelectedRange] = useState<Range>('1M');

  // Simple range filtering (mock slicing for demo - in real would use date logic)
  const filtered = useMemo(() => {
    const len = data.length;
    let start = 0;
    switch (selectedRange) {
      case '1D': start = Math.max(0, len - 1); break;
      case '5D': start = Math.max(0, len - 5); break;
      case '1M': start = Math.max(0, len - 22); break;
      case '6M': start = Math.max(0, len - 126); break;
      case 'YTD': start = Math.max(0, Math.floor(len * 0.4)); break;
      case '1Y': start = Math.max(0, len - 252); break;
      case '5Y': start = Math.max(0, len - 1260); break;
      case 'MAX': start = 0; break;
    }
    return {
      labels: labels.slice(start),
      data: data.slice(start),
      comparison: comparisonData ? comparisonData.slice(start) : undefined,
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
      },
    },
    scales: {
      x: { grid: { color: ChartColors.grid }, ticks: { color: ChartColors.textSecondary } },
      y: {
        grid: { color: ChartColors.grid },
        ticks: {
          color: ChartColors.textSecondary,
          callback: (val: any) => (unit ? `${val} ${unit}` : val),
        },
      },
    },
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: ChartColors.textPrimary }}>{title}</div>
        <div style={{ display: 'flex', gap: 4 }}>
          {RANGES.map(r => (
            <button
              key={r}
              onClick={() => setSelectedRange(r)}
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
              }}
            >
              {r}
            </button>
          ))}
        </div>
      </div>
      <div style={{ height }}>
        <Line data={chartData} options={options} />
      </div>
    </div>
  );
};

export default InteractiveChart;
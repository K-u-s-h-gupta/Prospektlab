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

  // Simple range filtering and base-100 normalization
  const filtered = useMemo(() => {
    if (selectedRange === '1D') {
      // Generate simulated intraday hourly points (9:15 to 15:30 IST)
      const intradayLabels = ['09:15', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00', '15:30'];
      
      let pVal = 100;
      let bVal = 100;
      const portIntraday: number[] = [pVal];
      const benchIntraday: number[] = [bVal];
      
      // Deterministic pseudo-random number generator to prevent flickering on renders
      let seed = title.length + (comparisonTitle?.length || 0);
      const rand = () => {
        seed = (seed * 9301 + 49297) % 233280;
        return seed / 233280;
      };

      for (let i = 1; i < intradayLabels.length; i++) {
        const bShock = (rand() - 0.5) * 0.4; // max 0.2% change per hour
        const pShock = (rand() - 0.5) * 0.5; // portfolio slightly different volatility
        bVal = bVal * (1 + bShock / 100);
        pVal = pVal * (1 + pShock / 100);
        benchIntraday.push(parseFloat(bVal.toFixed(2)));
        portIntraday.push(parseFloat(pVal.toFixed(2)));
      }

      const normPort = portIntraday.map(v => parseFloat(((v / portIntraday[0]) * 100).toFixed(2)));
      const normBench = benchIntraday.map(v => parseFloat(((v / benchIntraday[0]) * 100).toFixed(2)));

      return {
        labels: intradayLabels,
        data: normPort,
        comparison: comparisonData ? normBench : undefined,
      };
    }

    const len = data.length;
    let start = 0;
    switch (selectedRange) {
      case '5D': start = Math.max(0, len - 5); break;
      case '1M': start = Math.max(0, len - 22); break;
      case '6M': start = Math.max(0, len - 126); break;
      case 'YTD': start = Math.max(0, Math.floor(len * 0.4)); break;
      case '1Y': start = Math.max(0, len - 252); break;
      case '5Y': start = Math.max(0, len - 1260); break;
      case 'MAX': start = 0; break;
    }

    const slicedData = data.slice(start);
    const slicedComp = comparisonData ? comparisonData.slice(start) : undefined;
    
    // Normalize to base 100 starting at the first item of the sliced range
    const firstVal = slicedData[0] || 100;
    const firstComp = (slicedComp && slicedComp[0]) || 100;
    
    const normalizedData = slicedData.map(v => parseFloat(((v / firstVal) * 100).toFixed(2)));
    const normalizedComp = slicedComp ? slicedComp.map(v => parseFloat(((v / firstComp) * 100).toFixed(2))) : undefined;

    return {
      labels: labels.slice(start),
      data: normalizedData,
      comparison: normalizedComp,
    };
  }, [labels, data, comparisonData, selectedRange, title, comparisonTitle]);

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
            const formatted = Math.abs(val) < 100 ? val.toFixed(4) : val.toFixed(2);
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
            const formatted = Math.abs(num) < 100 ? num.toFixed(4) : num.toFixed(2);
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
        <Line data={chartData} options={options} />
      </div>
    </div>
  );
};

export default InteractiveChart;
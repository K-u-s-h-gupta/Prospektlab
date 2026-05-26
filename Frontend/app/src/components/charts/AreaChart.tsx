import React from 'react';
import { Line } from 'react-chartjs-2';
import { ChartColors } from './ThemeProvider';

interface AreaChartProps {
  labels: string[];
  data: number[];
  title: string;
  unit?: string;
}

export const AreaChart: React.FC<AreaChartProps> = ({ labels, data, title, unit = 'Cr' }) => {
  const chartData = {
    labels,
    datasets: [
      {
        fill: true,
        label: title,
        data: data,
        borderColor: ChartColors.primary,
        backgroundColor: (context: any) => {
          const chart = context.chart;
          const { ctx, chartArea } = chart;
          if (!chartArea) return null;
          const gradient = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
          gradient.addColorStop(0, ChartColors.primaryGradStart);
          gradient.addColorStop(1, ChartColors.primaryGradStop);
          return gradient;
        },
        borderWidth: 2,
        tension: 0.3,
        pointBackgroundColor: ChartColors.primary,
        pointBorderColor: '#0D0D0D',
        pointHoverRadius: 6,
        pointHoverBackgroundColor: ChartColors.primary,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false,
      },
      title: {
        display: true,
        text: `${title} (${unit})`,
        color: ChartColors.textPrimary,
        font: {
          size: 13,
          weight: 'normal' as const
        },
        padding: { bottom: 12 }
      },
    },
    scales: {
      x: {
        grid: {
          display: false,
        },
        ticks: {
          color: ChartColors.textSecondary,
        }
      },
      y: {
        grid: {
          color: ChartColors.grid,
        },
        ticks: {
          color: ChartColors.textSecondary,
          callback: (value: any) => {
            if (value >= 1e7) return (value / 1e7).toFixed(1) + ' Cr';
            if (value >= 1e5) return (value / 1e5).toFixed(1) + ' L';
            return value;
          }
        }
      }
    }
  };

  return (
    <div style={{ height: '220px', width: '100%', position: 'relative' }}>
      <Line data={chartData} options={options} />
    </div>
  );
};

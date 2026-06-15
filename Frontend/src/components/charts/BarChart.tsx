import React from 'react';
import { Bar } from 'react-chartjs-2';
import { ChartColors } from './ThemeProvider';

interface BarChartProps {
  labels: string[];
  data: number[];
  title: string;
  unit?: string;
  comparisonData?: number[];
  comparisonTitle?: string;
}

export const BarChart: React.FC<BarChartProps> = ({
  labels,
  data,
  title,
  unit = 'Cr',
  comparisonData,
  comparisonTitle
}) => {
  const datasets: any[] = [
    {
      label: title,
      data: data,
      backgroundColor: ChartColors.primary,
      borderRadius: 4,
      borderWidth: 0,
      maxBarThickness: 32,
    }
  ];

  if (comparisonData && comparisonTitle) {
    datasets.push({
      label: comparisonTitle,
      data: comparisonData,
      backgroundColor: ChartColors.secondary,
      borderRadius: 4,
      borderWidth: 0,
      maxBarThickness: 32,
    });
  }

  const chartData = {
    labels,
    datasets,
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: !!comparisonData,
        position: 'top' as const,
        labels: {
          boxWidth: 10,
          boxHeight: 10
        }
      },
      title: {
        display: true,
        text: `${title} ${comparisonTitle ? `vs ${comparisonTitle}` : ''} (${unit})`,
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
      <Bar data={chartData} options={options} />
    </div>
  );
};

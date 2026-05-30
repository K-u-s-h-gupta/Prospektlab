import React from 'react';
import { Radar } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  RadialLinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend
} from 'chart.js';
import { ChartColors } from './ThemeProvider';

ChartJS.register(RadialLinearScale, PointElement, LineElement, Filler, Tooltip, Legend);

interface RadarChartProps {
  labels: string[];
  data: number[];
  comparisonData?: number[];
  comparisonTitle?: string;
  title?: string;
  unit?: string;
}

export const RadarChart: React.FC<RadarChartProps> = ({
  labels,
  data,
  comparisonData,
  comparisonTitle,
  title
}) => {
  if (!labels.length || !data.length) return null;

  const chartData = {
    labels,
    datasets: [
      {
        label: title || 'Primary',
        data,
        backgroundColor: 'rgba(56, 189, 248, 0.15)',
        borderColor: ChartColors.primary,
        borderWidth: 2,
        pointBackgroundColor: ChartColors.primary,
        pointBorderColor: '#fff',
        pointHoverRadius: 5,
        pointRadius: 3
      },
      ...(comparisonData ? [{
        label: comparisonTitle || 'Comparison',
        data: comparisonData,
        backgroundColor: 'rgba(16, 185, 129, 0.15)',
        borderColor: ChartColors.secondary,
        borderWidth: 2,
        pointBackgroundColor: ChartColors.secondary,
        pointBorderColor: '#fff',
        pointHoverRadius: 5,
        pointRadius: 3
      }] : [])
    ]
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      r: {
        beginAtZero: true,
        grid: { color: ChartColors.grid },
        angleLines: { color: ChartColors.grid },
        pointLabels: {
          color: ChartColors.textSecondary,
          font: { size: 11 }
        },
        ticks: {
          display: false
        }
      }
    },
    plugins: {
      legend: {
        position: 'bottom' as const,
        labels: {
          color: ChartColors.textSecondary,
          padding: 16,
          usePointStyle: true,
          font: { size: 11 }
        }
      },
      tooltip: {
        backgroundColor: ChartColors.surface,
        titleColor: ChartColors.textPrimary,
        bodyColor: ChartColors.textSecondary,
        borderColor: ChartColors.grid,
        borderWidth: 1
      }
    }
  };

  return (
    <div className="glass" style={{
      padding: '16px',
      margin: '12px 0',
      display: 'flex',
      flexDirection: 'column',
      gap: '10px',
      background: 'rgba(15, 23, 42, 0.45)',
      border: '1px solid rgba(255, 255, 255, 0.05)',
      borderRadius: '8px',
      width: '100%'
    }}>
      {title && (
        <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)' }}>
          {title}
        </div>
      )}
      <div style={{ height: 300 }}>
        <Radar data={chartData} options={options} />
      </div>
    </div>
  );
};

export default RadarChart;

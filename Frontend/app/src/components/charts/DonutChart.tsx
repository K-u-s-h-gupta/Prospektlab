import React from 'react';
import { Doughnut } from 'react-chartjs-2';
import { ChartColors } from './ThemeProvider';


interface DonutChartProps {
  labels: string[];
  data: number[];
  title: string;
}

export const DonutChart: React.FC<DonutChartProps> = ({ labels, data, title }) => {
  const getSectorColor = (label: string) => {
    switch (label.toUpperCase()) {
      case 'IT': return '#38BDF8'; // Cyan
      case 'ENERGY': return '#818CF8'; // Indigo
      case 'BANKING': return '#34D399'; // Emerald
      case 'FMCG': return '#F59E0B'; // Amber
      case 'CONSUMER': return '#FB7185'; // Soft Rose
      default: return '#94A3B8'; // Slate
    }
  };

  const colors = labels.map(getSectorColor);

  const chartData = {
    labels,
    datasets: [
      {
        data: data,
        backgroundColor: colors,
        borderWidth: 1,
        borderColor: 'rgba(3, 7, 18, 0.8)',
        hoverOffset: 6
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'right' as const,
        labels: {
          color: ChartColors.textPrimary,
          font: {
            size: 11
          },
          padding: 10,
          boxWidth: 8,
          boxHeight: 8
        }
      },
      title: {
        display: !!title,
        text: title,
        color: ChartColors.textSecondary,
        font: {
          size: 12,
          weight: 'normal' as const
        },
        padding: { bottom: 12 }
      },
    },
    cutout: '65%'
  };

  return (
    <div style={{ height: '220px', width: '100%', position: 'relative' }}>
      <Doughnut data={chartData} options={options} />
    </div>
  );
};

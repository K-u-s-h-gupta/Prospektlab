import React from 'react';
import { Doughnut } from 'react-chartjs-2';
import { Chart as ChartJS, ArcElement, Tooltip, Legend, Title } from 'chart.js';
import { ChartColors } from './ThemeProvider';

ChartJS.register(ArcElement, Tooltip, Legend, Title);


interface DonutChartProps {
  labels: string[];
  data: number[];
  title: string;
}

export const DonutChart: React.FC<DonutChartProps> = ({ labels, data, title }) => {
  const PREDEFINED_COLORS = [
    '#38BDF8', // Cyan
    '#818CF8', // Indigo
    '#34D399', // Emerald
    '#F59E0B', // Amber
    '#FB7185', // Soft Rose
    '#A78BFA', // Violet
    '#F472B6', // Pink
    '#F87171', // Red
    '#FB923C', // Orange
    '#4ADE80', // Light Green
    '#2DD4BF', // Teal
  ];

  const colors = labels.map((_, idx) => PREDEFINED_COLORS[idx % PREDEFINED_COLORS.length]);

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

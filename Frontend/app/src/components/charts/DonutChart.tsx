import React from 'react';
import { Doughnut } from 'react-chartjs-2';
import { Chart as ChartJS, ArcElement, Tooltip, Legend, Title } from 'chart.js';
import { ChartColors } from './ThemeProvider';

ChartJS.register(ArcElement, Tooltip, Legend, Title);

interface DonutChartProps {
  labels: string[];
  data: number[];
  title: string;
  valueKind?: 'currency' | 'percent';
  unit?: string;
}

export const DonutChart: React.FC<DonutChartProps> = ({ labels, data, title, valueKind = 'currency', unit }) => {
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

  const totalVal = data.reduce((a, b) => a + b, 0);

  // Format labels to include percentage in the legend: e.g. "IT (28%)"
  const formattedLabels = labels.map((label, idx) => {
    const val = data[idx];
    const pct = totalVal > 0 ? (val / totalVal) * 100 : 0;
    return `${label} (${pct.toFixed(0)}%)`;
  });

  const colors = labels.map((_, idx) => PREDEFINED_COLORS[idx % PREDEFINED_COLORS.length]);

  const chartData = {
    labels: formattedLabels,
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
        position: 'bottom' as const,
        align: 'center' as const,
        labels: {
          color: ChartColors.textPrimary,
          font: {
            size: 10
          },
          padding: 8,
          boxWidth: 8,
          boxHeight: 8,
          usePointStyle: true,
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
        padding: { bottom: 8 }
      },
      tooltip: {
        callbacks: {
          label: (context: any) => {
            const val = context.raw;
            const pct = totalVal > 0 ? (val / totalVal) * 100 : 0;
            const isPercent = valueKind === 'percent' || unit === '%';
            if (isPercent) {
              return ` ${val.toFixed(1)}%`;
            }
            const formattedVal = '₹' + val.toLocaleString('en-IN', { maximumFractionDigits: 0 });
            return ` ${formattedVal} · ${pct.toFixed(1)}% of portfolio`;
          }
        }
      }
    },
    cutout: '65%'
  };

  // Plugin to draw total value in the center of the donut chart
  const centerTextPlugin = {
    id: 'centerText',
    beforeDraw: (chart: any) => {
      const { ctx, width, height } = chart;
      ctx.save();
      
      const isPercent = valueKind === 'percent' || unit === '%';
      const centerLabel = isPercent ? '100%' : '₹' + Math.round(totalVal).toLocaleString('en-IN');
      const subLabel = isPercent ? 'Allocation' : 'Total Value';
      
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      
      // Get donut center coordinates
      const textX = chart.getDatasetMeta(0).data[0]?.x || width / 2;
      const textY = chart.getDatasetMeta(0).data[0]?.y || height / 2;
      
      // Draw sub label
      ctx.font = 'normal 10px sans-serif';
      ctx.fillStyle = 'rgba(255, 255, 255, 0.45)';
      ctx.fillText(subLabel, textX, textY - 9);
      
      // Draw the main center value (never fake currency for percent donuts)
      ctx.font = 'bold 12px sans-serif';
      ctx.fillStyle = '#FFFFFF';
      ctx.fillText(centerLabel, textX, textY + 7);
      
      ctx.restore();
    }
  };

  return (
    <div style={{ height: '220px', width: '100%', position: 'relative' }}>
      <Doughnut data={chartData} options={options} plugins={[centerTextPlugin]} />
    </div>
  );
};

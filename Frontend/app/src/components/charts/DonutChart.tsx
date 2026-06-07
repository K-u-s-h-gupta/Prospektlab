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
    '#38BDF8',
    '#818CF8',
    '#34D399',
    '#F59E0B',
    '#FB7185',
    '#A78BFA',
    '#F472B6',
    '#F87171',
    '#FB923C',
    '#4ADE80',
    '#2DD4BF',
  ];

  const normalizedData = data.map((value) => {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : 0;
  });

  const totalVal = normalizedData.reduce((a, b) => a + b, 0);

  if (!labels.length || !normalizedData.length || totalVal <= 0) {
    return (
      <div style={{ height: '220px', width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: ChartColors.textMuted, fontSize: 12 }}>
        No verified allocation data available
      </div>
    );
  }

  const formattedLabels = labels.map((label, idx) => {
    const val = normalizedData[idx];
    const pct = totalVal > 0 ? (val / totalVal) * 100 : 0;
    return `${label} (${pct.toFixed(0)}%)`;
  });

  const colors = labels.map((_, idx) => PREDEFINED_COLORS[idx % PREDEFINED_COLORS.length]);

  const chartData = {
    labels: formattedLabels,
    datasets: [
      {
        data: normalizedData,
        backgroundColor: colors,
        borderWidth: 1,
        borderColor: 'rgba(3, 7, 18, 0.8)',
        hoverOffset: 6,
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
          font: { size: 10 },
          padding: 8,
          boxWidth: 8,
          boxHeight: 8,
          usePointStyle: true,
        },
      },
      title: {
        display: !!title,
        text: title,
        color: ChartColors.textSecondary,
        font: {
          size: 12,
          weight: 'normal' as const,
        },
        padding: { bottom: 8 },
      },
      tooltip: {
        callbacks: {
          label: (context: any) => {
            const val = Number(context.raw);
            const pct = totalVal > 0 ? (val / totalVal) * 100 : 0;
            const isPercent = valueKind === 'percent' || unit === '%';
            if (isPercent) {
              return ` ${val.toFixed(1)}%`;
            }
            const formattedVal = `INR ${val.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
            return ` ${formattedVal} - ${pct.toFixed(1)}% of total`;
          },
        },
      },
    },
    cutout: '65%',
  };

  const centerTextPlugin = {
    id: 'centerText',
    beforeDraw: (chart: any) => {
      const { ctx, width, height } = chart;
      ctx.save();

      const chartValues = ((chart?.data?.datasets?.[0]?.data || []) as Array<number | string>)
        .map((value) => {
          const numeric = Number(value);
          return Number.isFinite(numeric) ? numeric : 0;
        });
      const liveTotalVal = chartValues.reduce((acc, value) => acc + value, 0);

      const isPercent = valueKind === 'percent' || unit === '%';
      const centerLabel = isPercent ? '100%' : `INR ${Math.round(liveTotalVal).toLocaleString('en-IN')}`;
      const subLabel = isPercent ? 'Allocation' : 'Total Value';

      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      const arcMeta = chart.getDatasetMeta(0)?.data?.[0];
      const textX = arcMeta?.x ?? width / 2;
      const textY = arcMeta?.y ?? height / 2;

      ctx.font = 'normal 10px sans-serif';
      ctx.fillStyle = 'rgba(255, 255, 255, 0.45)';
      ctx.fillText(subLabel, textX, textY - 9);

      ctx.font = 'bold 12px sans-serif';
      ctx.fillStyle = '#FFFFFF';
      ctx.fillText(centerLabel, textX, textY + 7);

      ctx.restore();
    },
  };

  return (
    <div style={{ height: '220px', width: '100%', position: 'relative' }}>
      <Doughnut data={chartData} options={options} plugins={[centerTextPlugin]} />
    </div>
  );
};

export default DonutChart;

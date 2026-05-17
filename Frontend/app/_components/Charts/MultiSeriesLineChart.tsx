"use client";

import { Chart as ChartType } from "../lib/types";

interface MultiSeriesLineChartProps {
  chart: ChartType;
}

const fallbackColors = ["#7df9ff", "#bef264", "#c4b5fd", "#fda4af"];

function points(values: Array<number | null>, width: number, height: number, max: number, min: number) {
  const range = Math.max(1, max - min);
  return values
    .map((value, idx) => {
      if (typeof value !== "number") return null;
      const x = values.length <= 1 ? width / 2 : (idx / (values.length - 1)) * width;
      const y = height - ((value - min) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .filter(Boolean)
    .join(" ");
}

export function MultiSeriesLineChart({ chart }: MultiSeriesLineChartProps) {
  if (!chart.series || chart.series.length === 0) {
    return <div className="flex h-32 items-center justify-center text-sm text-slate-500">No data available</div>;
  }

  const seriesList = chart.series;
  const allValues = seriesList.flatMap((series) => series.values || []).filter((value): value is number => typeof value === "number");
  const min = Math.min(...allValues, 0);
  const max = Math.max(...allValues, 1);
  const width = 640;
  const height = 220;

  return (
    <div className="w-full rounded-2xl border border-white/10 bg-white/[0.035] p-4">
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-white">{chart.title}</h3>
        {chart.subtitle && <p className="text-xs text-slate-500">{chart.subtitle}</p>}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} className="h-64 w-full overflow-visible" role="img" aria-label={chart.title}>
        {[0.25, 0.5, 0.75].map((line) => (
          <line key={line} x1="0" x2={width} y1={height * line} y2={height * line} stroke="rgba(255,255,255,0.08)" />
        ))}
        {seriesList.map((series, idx) => {
          const color = series.color || fallbackColors[idx % fallbackColors.length];
          const linePoints = points(series.values || [], width, height, max, min);
          return (
            <polyline key={series.name} points={linePoints} fill="none" stroke={color} strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          );
        })}
      </svg>
      <div className="mt-3 flex flex-wrap gap-3">
        {seriesList.map((series, idx) => (
          <span key={series.name} className="flex items-center gap-2 text-xs text-slate-400">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: series.color || fallbackColors[idx % fallbackColors.length] }} />
            {series.name}
          </span>
        ))}
      </div>
    </div>
  );
}

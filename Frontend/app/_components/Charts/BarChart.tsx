"use client";

import { Chart as ChartType } from "../lib/types";

interface BarChartProps {
  chart: ChartType;
}

const fallbackColors = ["#7df9ff", "#bef264", "#c4b5fd", "#fda4af"];

function valueMax(chart: ChartType) {
  const values = (chart.series || []).flatMap((series) => series.values || []).filter((value): value is number => typeof value === "number");
  return Math.max(1, ...values.map((value) => Math.abs(value)));
}

export function BarChart({ chart }: BarChartProps) {
  if (!chart.series || chart.series.length === 0) {
    return <div className="flex h-32 items-center justify-center text-sm text-slate-500">No data available</div>;
  }

  const seriesList = chart.series;
  const max = valueMax(chart);

  return (
    <div className="w-full rounded-2xl border border-white/10 bg-white/[0.035] p-4">
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-white">{chart.title}</h3>
        {chart.subtitle && <p className="text-xs text-slate-500">{chart.subtitle}</p>}
      </div>
      <div className="space-y-3">
        {(chart.x_labels || []).map((label, idx) => (
          <div key={`${label}-${idx}`} className="grid grid-cols-[84px_minmax(0,1fr)] items-center gap-3 text-xs">
            <span className="truncate text-slate-500">{label}</span>
            <div className="space-y-1.5">
              {seriesList.map((series, sidx) => {
                const value = series.values?.[idx];
                const width = typeof value === "number" ? Math.max(4, (Math.abs(value) / max) * 100) : 0;
                const color = series.color || fallbackColors[sidx % fallbackColors.length];
                return (
                  <div key={series.name} className="flex items-center gap-2">
                    <div className="h-3 flex-1 rounded-full bg-white/[0.06]">
                      <div className="h-3 rounded-full" style={{ width: `${width}%`, backgroundColor: color }} />
                    </div>
                    <span className="w-20 truncate text-right text-slate-300">{typeof value === "number" ? value.toLocaleString("en-IN") : "n/a"}</span>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap gap-3">
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

"use client";

import { Chart as ChartType } from "../lib/types";

interface MultiSeriesBarChartProps {
  chart: ChartType;
}

const fallbackColors = ["#7df9ff", "#bef264", "#c4b5fd", "#fda4af"];

function valueMax(chart: ChartType) {
  const values = (chart.series || []).flatMap((series) => series.values || []).filter((value): value is number => typeof value === "number");
  return Math.max(1, ...values.map((value) => Math.abs(value)));
}

export function MultiSeriesBarChart({ chart }: MultiSeriesBarChartProps) {
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
      <div className="space-y-4">
        {(chart.x_labels || []).map((label, idx) => (
          <div key={`${label}-${idx}`} className="grid grid-cols-[84px_minmax(0,1fr)] items-center gap-3 text-xs">
            <span className="truncate text-slate-500">{label}</span>
            <div className="flex h-28 items-end gap-2 rounded-2xl bg-black/20 px-3 py-3">
              {seriesList.map((series, sidx) => {
                const value = series.values?.[idx];
                const height = typeof value === "number" ? Math.max(6, (Math.abs(value) / max) * 100) : 0;
                return (
                  <div key={series.name} className="flex min-w-0 flex-1 flex-col items-center gap-2">
                    <div className="flex h-20 w-full items-end">
                      <div
                        className="w-full rounded-t-md"
                        style={{ height: `${height}%`, backgroundColor: series.color || fallbackColors[sidx % fallbackColors.length] }}
                        title={`${series.name}: ${typeof value === "number" ? value.toLocaleString("en-IN") : "n/a"}`}
                      />
                    </div>
                    <span className="w-full truncate text-center text-[10px] text-slate-500">{series.name}</span>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

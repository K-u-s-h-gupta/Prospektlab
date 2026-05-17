"use client";

import { Chart as ChartType } from "../lib/types";

interface DonutChartProps {
  chart: ChartType;
}

const fallbackColors = ["#7df9ff", "#bef264", "#c4b5fd", "#fda4af", "#fdba74"];

export function DonutChart({ chart }: DonutChartProps) {
  if (!chart.series || chart.series.length === 0) {
    return <div className="flex h-32 items-center justify-center text-sm text-slate-500">No data available</div>;
  }

  const seriesList = chart.series;
  const values = (chart.x_labels || []).map((label, idx) => ({
    name: label,
    value: Number(seriesList[0]?.values?.[idx] ?? 0),
  }));
  const total = Math.max(1, values.reduce((sum, item) => sum + Math.max(0, item.value), 0));
  const gradient = values
    .map((item, idx, arr) => {
      const start = arr.slice(0, idx).reduce((sum, prev) => sum + (Math.max(0, prev.value) / total) * 100, 0);
      const end = start + (Math.max(0, item.value) / total) * 100;
      const color = fallbackColors[idx % fallbackColors.length];
      return `${color} ${start.toFixed(2)}% ${end.toFixed(2)}%`;
    })
    .join(", ");

  return (
    <div className="w-full rounded-2xl border border-white/10 bg-white/[0.035] p-4">
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-white">{chart.title}</h3>
        {chart.subtitle && <p className="text-xs text-slate-500">{chart.subtitle}</p>}
      </div>
      <div className="grid items-center gap-4 sm:grid-cols-[180px_minmax(0,1fr)]">
        <div
          className="mx-auto h-40 w-40 rounded-full"
          style={{
            background: `conic-gradient(${gradient || "#334155 0% 100%"})`,
            boxShadow: "inset 0 0 0 34px #08090c, 0 0 40px rgba(125,249,255,0.08)",
          }}
          role="img"
          aria-label={chart.title}
        />
        <div className="space-y-2">
          {values.slice(0, 6).map((item, idx) => (
            <div key={item.name} className="flex items-center justify-between gap-3 rounded-xl bg-black/20 px-3 py-2 text-xs">
              <span className="flex min-w-0 items-center gap-2 text-slate-400">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: fallbackColors[idx % fallbackColors.length] }} />
                <span className="truncate">{item.name}</span>
              </span>
              <span className="font-medium text-slate-200">{item.value.toLocaleString("en-IN")}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

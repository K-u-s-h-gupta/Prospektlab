"use client";

import { Chart as ChartType } from "../lib/types";


interface DonutChartProps {
  chart: ChartType;
}

export function DonutChart({ chart }: DonutChartProps) {
  if (!chart.series || chart.series.length === 0) return <div className="h-32 flex items-center justify-center text-gray-400">No data available</div>;

  return (
    <div className="w-full h-64 rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-2">
        <h3 className="text-sm font-semibold text-gray-900">{chart.title}</h3>
        {chart.subtitle && <p className="text-xs text-gray-500">{chart.subtitle}</p>}
      </div>
      <div className="space-y-2">
        {(chart.x_labels || []).map((label, idx) => (
          <div key={label} className="flex items-center justify-between text-sm border-b border-slate-100 py-1">
            <span className="text-gray-600">{label}</span>
            <span className="font-medium text-gray-900">{String(chart.series?.[0]?.values?.[idx] ?? "n/a")}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

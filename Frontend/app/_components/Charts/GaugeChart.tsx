"use client";

import { Chart as ChartType } from "../lib/types";

interface GaugeChartProps {
  chart: ChartType;
}

export function GaugeChart({ chart }: GaugeChartProps) {
  if (!chart.series || chart.series.length === 0) {
    return <div className="flex h-64 items-center justify-center text-sm text-slate-500">No data available</div>;
  }

  const fairValueSeries = chart.series.find((s) => s.name.toLowerCase().includes("fair"));
  const cmpSeries = chart.series.find((s) => s.name.toLowerCase().includes("cmp"));
  const fairValue = fairValueSeries?.values?.[0];
  const cmp = cmpSeries?.values?.[0];

  if (typeof fairValue !== "number" || typeof cmp !== "number") {
    return <div className="flex h-64 items-center justify-center text-sm text-slate-500">No valid data</div>;
  }

  const maxValue = Math.max(fairValue, cmp) * 1.1;
  const gaugeValue = Math.max(0, Math.min(135, (cmp / maxValue) * 100));
  const gaugeColor = gaugeValue < 80 ? "#bef264" : gaugeValue < 110 ? "#7df9ff" : "#fda4af";
  const currency = chart.currency || "INR";

  return (
    <div className="flex h-80 w-full flex-col items-center justify-center rounded-2xl border border-white/10 bg-white/[0.035] p-6">
      <div className="mb-4 text-center">
        <h3 className="text-sm font-semibold text-white">{chart.title}</h3>
        {chart.subtitle && <p className="text-xs text-slate-500">{chart.subtitle}</p>}
      </div>

      <svg viewBox="0 0 200 120" className="w-full max-w-xs" height={150} aria-label={chart.title}>
        <path d="M 30 100 A 70 70 0 0 1 170 100" fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="10" strokeLinecap="round" />
        <path
          d="M 30 100 A 70 70 0 0 1 170 100"
          fill="none"
          stroke={gaugeColor}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${(gaugeValue / 100) * 220} 220`}
          opacity="0.9"
        />
        <g transform={`translate(100, 100) rotate(${(gaugeValue / 100) * 180 - 90})`}>
          <circle cx="0" cy="0" r="4" fill="#f8fafc" />
          <line x1="0" y1="0" x2="58" y2="0" stroke="#f8fafc" strokeWidth="2" strokeLinecap="round" />
        </g>
        <text x="30" y="115" fontSize="10" fill="#94a3b8" textAnchor="middle">
          Low
        </text>
        <text x="100" y="115" fontSize="10" fill="#94a3b8" textAnchor="middle">
          Fair
        </text>
        <text x="170" y="115" fontSize="10" fill="#94a3b8" textAnchor="middle">
          High
        </text>
      </svg>

      <div className="mt-6 grid w-full max-w-sm grid-cols-2 gap-3 text-center">
        <div className="rounded-2xl border border-white/10 bg-black/20 p-3">
          <p className="text-xs text-slate-500">Fair Value</p>
          <p className="mt-1 text-lg font-semibold text-white">
            {currency} {fairValue.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
          </p>
        </div>
        <div className="rounded-2xl border border-white/10 bg-black/20 p-3">
          <p className="text-xs text-slate-500">Current Price</p>
          <p className="mt-1 text-lg font-semibold text-white">
            {currency} {cmp.toLocaleString("en-IN", { maximumFractionDigits: 2 })}
          </p>
        </div>
      </div>
    </div>
  );
}

"use client";

import { Chart as ChartType } from "../lib/types";

interface GaugeChartProps {
  chart: ChartType;
}

/**
 * Simple gauge visualization for DCF fair value vs CMP comparison.
 * Uses SVG for lightweight rendering without heavy chart library dependency.
 */
export function GaugeChart({ chart }: GaugeChartProps) {
  if (!chart.series || chart.series.length === 0) {
    return <div className="h-64 flex items-center justify-center text-gray-400">No data available</div>;
  }

  // Extract fair value and CMP from series
  const fairValueSeries = chart.series.find((s) => s.name.toLowerCase().includes("fair"));
  const cmpSeries = chart.series.find((s) => s.name.toLowerCase().includes("cmp"));

  const fairValue = fairValueSeries?.values?.[0];
  const cmp = cmpSeries?.values?.[0];

  if (typeof fairValue !== "number" || typeof cmp !== "number") {
    return <div className="h-64 flex items-center justify-center text-gray-400">No valid data</div>;
  }

  // Calculate gauge position (0-100)
  const maxValue = Math.max(fairValue, cmp) * 1.1;
  const gaugeValue = (cmp / maxValue) * 100;
  const gaugeColor =
    gaugeValue < 80
      ? "#ef4444" // red (undervalued)
      : gaugeValue < 100
        ? "#f59e0b" // amber (fairly valued)
        : gaugeValue < 120
          ? "#10b981" // green (fairly valued high)
          : "#ef4444"; // red (overvalued)

  return (
    <div className="w-full h-64 rounded-lg border border-gray-200 bg-white p-6 flex flex-col items-center justify-center">
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-gray-900 text-center">{chart.title}</h3>
        {chart.subtitle && <p className="text-xs text-gray-500 text-center">{chart.subtitle}</p>}
      </div>

      {/* Gauge SVG */}
      <svg viewBox="0 0 200 120" className="w-full max-w-xs" height={150}>
        {/* Gauge background arc */}
        <path
          d="M 30 100 A 70 70 0 0 1 170 100"
          fill="none"
          stroke="#e5e7eb"
          strokeWidth="8"
          strokeLinecap="round"
        />

        {/* Gauge colored arc */}
        <path
          d="M 30 100 A 70 70 0 0 1 170 100"
          fill="none"
          stroke={gaugeColor}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={`${(gaugeValue / 100) * 220} 220`}
          opacity="0.7"
        />

        {/* Needle */}
        <g transform={`translate(100, 100) rotate(${(gaugeValue / 100) * 180 - 90})`}>
          <circle cx="0" cy="0" r="3" fill="#1f2937" />
          <line x1="0" y1="0" x2="60" y2="0" stroke="#1f2937" strokeWidth="2" strokeLinecap="round" />
        </g>

        {/* Labels */}
        <text x="30" y="115" fontSize="10" fill="#6b7280" textAnchor="middle">
          Undervalued
        </text>
        <text x="100" y="115" fontSize="10" fill="#6b7280" textAnchor="middle">
          Fair
        </text>
        <text x="170" y="115" fontSize="10" fill="#6b7280" textAnchor="middle">
          Overvalued
        </text>
      </svg>

      {/* Values */}
      <div className="mt-6 grid grid-cols-2 gap-6 text-center">
        <div>
          <p className="text-xs text-gray-500">Fair Value</p>
          <p className="text-lg font-bold text-gray-900">₹{fairValue.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Current Price</p>
          <p className="text-lg font-bold text-gray-900">₹{cmp.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</p>
        </div>
      </div>

      {/* Assessment */}
      <div className="mt-4 text-center">
        <p className={`text-sm font-semibold ${gaugeColor.includes("10b981") ? "text-green-600" : gaugeColor.includes("f59e0b") ? "text-amber-600" : "text-red-600"}`}>
          {gaugeValue < 80
            ? "Potentially Undervalued"
            : gaugeValue < 100
              ? "Fairly Valued"
              : gaugeValue < 120
                ? "Slightly Overvalued"
                : "Potentially Overvalued"}
        </p>
      </div>
    </div>
  );
}

"use client";

import { ComparisonRow } from "./lib/types";

interface ComparisonTableProps {
  rows: ComparisonRow[];
  primaryLabel?: string;
  secondaryLabel?: string;
}

export function ComparisonTable({ rows, primaryLabel = "Primary", secondaryLabel = "Secondary" }: ComparisonTableProps) {
  if (!rows || rows.length === 0) return null;

  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.035]">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[620px] text-sm">
          <thead className="border-b border-white/10 bg-white/[0.04]">
            <tr>
              <th className="px-5 py-3 text-left font-medium text-slate-300">Metric</th>
              <th className="px-5 py-3 text-right font-medium text-slate-300">{primaryLabel}</th>
              <th className="px-5 py-3 text-right font-medium text-slate-300">{secondaryLabel}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/10">
            {rows.map((row, idx) => (
              <tr key={`${row.metric}-${idx}`} className="bg-black/10">
                <td className="px-5 py-4 font-medium text-white">{row.metric}</td>
                <td className={`px-5 py-4 text-right font-medium ${row.winner === "primary" ? "text-lime-200" : "text-slate-400"}`}>
                  {row.primary_value}
                </td>
                <td className={`px-5 py-4 text-right font-medium ${row.winner === "secondary" ? "text-lime-200" : "text-slate-400"}`}>
                  {row.secondary_value}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

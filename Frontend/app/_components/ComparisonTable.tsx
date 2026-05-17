"use client";

import { ComparisonRow } from "./lib/types";

interface ComparisonTableProps {
  rows: ComparisonRow[];
  primaryLabel?: string;
  secondaryLabel?: string;
}

export function ComparisonTable({ rows, primaryLabel = "Primary", secondaryLabel = "Secondary" }: ComparisonTableProps) {
  if (!rows || rows.length === 0) {
    return null;
  }

  return (
    <div className="rounded-lg border border-gray-200 overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-50 border-b border-gray-200">
          <tr>
            <th className="px-6 py-3 text-left font-semibold text-gray-900">Metric</th>
            <th className="px-6 py-3 text-right font-semibold text-gray-900">{primaryLabel}</th>
            <th className="px-6 py-3 text-right font-semibold text-gray-900">{secondaryLabel}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200">
          {rows.map((row, idx) => (
            <tr key={idx} className={idx % 2 === 0 ? "bg-white" : "bg-gray-50"}>
              <td className="px-6 py-4 font-medium text-gray-900">{row.metric}</td>
              <td
                className={`px-6 py-4 text-right font-medium ${
                  row.winner === "primary"
                    ? "text-green-600 bg-green-50"
                    : row.winner === "secondary"
                      ? "text-gray-600"
                      : "text-gray-600"
                }`}
              >
                {row.primary_value}
              </td>
              <td
                className={`px-6 py-4 text-right font-medium ${
                  row.winner === "secondary"
                    ? "text-green-600 bg-green-50"
                    : row.winner === "primary"
                      ? "text-gray-600"
                      : "text-gray-600"
                }`}
              >
                {row.secondary_value}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

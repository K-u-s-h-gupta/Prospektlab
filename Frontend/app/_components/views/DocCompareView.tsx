"use client";

import { RichResponse } from "../lib/types";

interface DocCompareViewProps {
  data: RichResponse;
}

export function DocCompareView({ data }: DocCompareViewProps) {
  return (
    <div className="space-y-6 pb-4">
      {/* Title */}
      {data.title && (
        <div>
          <h2 className="text-2xl font-bold text-gray-900">{data.title}</h2>
          {data.subtitle && <p className="text-gray-600 mt-1">{data.subtitle}</p>}
        </div>
      )}

      {/* Document Comparison Table */}
      {data.filing_sections && data.filing_sections.length > 0 && (
        <div className="rounded-lg border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-6 py-3 text-left font-semibold text-gray-900">Section / Field</th>
                <th className="px-6 py-3 text-left font-semibold text-gray-900">Document A</th>
                <th className="px-6 py-3 text-left font-semibold text-gray-900">Document B</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {data.filing_sections.map((row, idx) => (
                <tr key={idx} className={idx % 2 === 0 ? "bg-white" : "bg-gray-50"}>
                  <td className="px-6 py-4 font-medium text-gray-900">{String((row as Record<string, unknown>).name || "")}</td>
                  <td className="px-6 py-4 text-gray-700 max-w-xs truncate" title={String((row as Record<string, unknown>).excerpt || "")}>
                    {String((row as Record<string, unknown>).excerpt || "")}
                  </td>
                  <td className="px-6 py-4 text-gray-700 max-w-xs truncate" title={String((row as Record<string, unknown>).description || "")}>
                    {String((row as Record<string, unknown>).description || "—")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Disclaimer */}
      {data.disclaimer && <div className="text-xs text-gray-500 mt-4 italic">{data.disclaimer}</div>}
    </div>
  );
}

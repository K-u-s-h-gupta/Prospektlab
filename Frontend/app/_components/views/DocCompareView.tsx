"use client";

import { RichResponse } from "../lib/types";

interface DocCompareViewProps {
  data: RichResponse;
}

export function DocCompareView({ data }: DocCompareViewProps) {
  return (
    <div className="space-y-6 pb-4">
      {data.title && (
        <div>
          <h2 className="text-2xl font-semibold text-white">{data.title}</h2>
          {data.subtitle && <p className="mt-1 text-slate-500">{data.subtitle}</p>}
        </div>
      )}

      {data.filing_sections && data.filing_sections.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.035]">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="border-b border-white/10 bg-white/[0.04]">
                <tr>
                  <th className="px-6 py-3 text-left font-semibold text-slate-300">Section / Field</th>
                  <th className="px-6 py-3 text-left font-semibold text-slate-300">Document A</th>
                  <th className="px-6 py-3 text-left font-semibold text-slate-300">Document B</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10">
                {data.filing_sections.map((row, idx) => (
                  <tr key={idx} className="bg-black/10">
                    <td className="px-6 py-4 font-medium text-white">{String((row as Record<string, unknown>).name || "")}</td>
                    <td className="max-w-xs truncate px-6 py-4 text-slate-400" title={String((row as Record<string, unknown>).excerpt || "")}>
                      {String((row as Record<string, unknown>).excerpt || "")}
                    </td>
                    <td className="max-w-xs truncate px-6 py-4 text-slate-400" title={String((row as Record<string, unknown>).description || "")}>
                      {String((row as Record<string, unknown>).description || "-")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {data.disclaimer && <div className="mt-4 text-xs italic text-slate-500">{data.disclaimer}</div>}
    </div>
  );
}

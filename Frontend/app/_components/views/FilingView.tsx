"use client";

import { RichResponse } from "../lib/types";

interface FilingViewProps {
  data: RichResponse;
}

export function FilingView({ data }: FilingViewProps) {
  return (
    <div className="space-y-6 pb-4">
      {/* Title */}
      {data.title && (
        <div>
          <h2 className="text-2xl font-semibold text-white">{data.title}</h2>
          {data.subtitle && <p className="mt-1 text-slate-500">{data.subtitle}</p>}
        </div>
      )}

      {/* Filing Sections */}
      {data.filing_sections && data.filing_sections.length > 0 && (
        <div className="space-y-4">
          {data.filing_sections.map((section, idx) => (
            <div key={idx} className="rounded-2xl border border-white/10 bg-white/[0.035] p-6">
              {String((section as Record<string, unknown>).name || "") && (
                <h3 className="mb-3 font-semibold text-white">{String((section as Record<string, unknown>).name || "")}</h3>
              )}
              <div className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-400">
                {String((section as Record<string, unknown>).excerpt || (section as Record<string, unknown>).text || JSON.stringify(section, null, 2))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Disclaimer */}
      {data.disclaimer && <div className="mt-4 text-xs italic text-slate-500">{data.disclaimer}</div>}
    </div>
  );
}

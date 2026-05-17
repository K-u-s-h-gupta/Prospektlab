"use client";

import { RichResponse } from "../lib/types";
import { ExternalLink } from "lucide-react";

interface NewsViewProps {
  data: RichResponse;
}

export function NewsView({ data }: NewsViewProps) {
  return (
    <div className="space-y-4 pb-4">
      {/* Title */}
      {data.title && (
        <div>
          <h2 className="text-2xl font-semibold text-white">{data.title}</h2>
          {data.subtitle && <p className="mt-1 text-slate-500">{data.subtitle}</p>}
        </div>
      )}

      {/* Headlines List */}
      {data.headlines && data.headlines.length > 0 && (
        <div className="space-y-3">
          {data.headlines.map((headline, idx) => (
            <a
              key={idx}
              href={headline.url || "#"}
              target="_blank"
              rel="noopener noreferrer"
              className="group block rounded-2xl border border-white/10 bg-white/[0.035] p-4 transition-colors hover:bg-white/[0.06]"
            >
              <div className="flex items-start gap-3">
                <div className="flex-1">
                  <h3 className="font-semibold text-white group-hover:text-cyan-100">{headline.title}</h3>
                  {headline.snippet && <p className="mt-2 line-clamp-2 text-sm text-slate-400">{headline.snippet}</p>}
                  <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
                    {headline.source && <span className="font-medium">{headline.source}</span>}
                    {headline.published && <span>•</span>}
                    {headline.published && <span>{headline.published}</span>}
                  </div>
                </div>
                {headline.url && <ExternalLink className="mt-1 h-4 w-4 flex-shrink-0 text-slate-500 group-hover:text-cyan-100" />}
              </div>
            </a>
          ))}
        </div>
      )}

      {/* Disclaimer */}
      {data.disclaimer && <div className="mt-4 text-xs italic text-slate-500">{data.disclaimer}</div>}
    </div>
  );
}

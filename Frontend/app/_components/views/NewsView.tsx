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
          <h2 className="text-2xl font-bold text-gray-900">{data.title}</h2>
          {data.subtitle && <p className="text-gray-600 mt-1">{data.subtitle}</p>}
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
              className="block p-4 rounded-lg border border-gray-200 bg-white hover:bg-gray-50 transition-colors group"
            >
              <div className="flex items-start gap-3">
                <div className="flex-1">
                  <h3 className="font-semibold text-gray-900 group-hover:text-blue-600">{headline.title}</h3>
                  {headline.snippet && <p className="text-sm text-gray-600 mt-2 line-clamp-2">{headline.snippet}</p>}
                  <div className="flex items-center gap-2 mt-3 text-xs text-gray-500">
                    {headline.source && <span className="font-medium">{headline.source}</span>}
                    {headline.published && <span>•</span>}
                    {headline.published && <span>{headline.published}</span>}
                  </div>
                </div>
                {headline.url && <ExternalLink className="w-4 h-4 text-gray-400 group-hover:text-blue-600 flex-shrink-0 mt-1" />}
              </div>
            </a>
          ))}
        </div>
      )}

      {/* Disclaimer */}
      {data.disclaimer && <div className="text-xs text-gray-500 mt-4 italic">{data.disclaimer}</div>}
    </div>
  );
}

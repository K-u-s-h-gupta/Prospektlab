"use client";

import { Entity, DataSource } from "./lib/types";
import { ExternalLink } from "lucide-react";

interface GuidanceFooterProps {
  entities: Entity[];
  dataSources?: DataSource[];
}

export function GuidanceFooter({ entities, dataSources }: GuidanceFooterProps) {
  return (
    <div className="mt-6 border-t border-white/10 pt-4">
      {/* FY Guidance / Forward Statements */}
      {entities.length > 0 && (
        <div className="mb-4">
          <p className="text-xs leading-5 text-slate-500">
            <strong>Forward-Looking Statements:</strong> Projections and guidance are based on historical data and
            assumptions. Actual results may differ materially. Please refer to company disclosures and regulatory
            filings for official guidance.
          </p>
        </div>
      )}

      {/* Data Sources Citation */}
      {dataSources && dataSources.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold text-slate-400">Data Sources:</p>
          <div className="flex flex-wrap gap-3">
            {dataSources.map((source, idx) => (
              <a
                key={idx}
                href={source.url || "#"}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs text-slate-300 transition-colors hover:bg-white/[0.07]"
              >
                {source.label}
                {source.url && <ExternalLink className="w-3 h-3" />}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

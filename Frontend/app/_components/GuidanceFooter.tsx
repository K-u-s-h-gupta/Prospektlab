"use client";

import { Entity, DataSource } from "./lib/types";
import { ExternalLink } from "lucide-react";

interface GuidanceFooterProps {
  entities: Entity[];
  dataSources?: DataSource[];
}

export function GuidanceFooter({ entities, dataSources }: GuidanceFooterProps) {
  return (
    <div className="border-t border-gray-200 pt-4 mt-6">
      {/* FY Guidance / Forward Statements */}
      {entities.length > 0 && (
        <div className="mb-4">
          <p className="text-xs text-gray-600">
            <strong>Forward-Looking Statements:</strong> Projections and guidance are based on historical data and
            assumptions. Actual results may differ materially. Please refer to company disclosures and regulatory
            filings for official guidance.
          </p>
        </div>
      )}

      {/* Data Sources Citation */}
      {dataSources && dataSources.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-700 mb-2">Data Sources:</p>
          <div className="flex flex-wrap gap-3">
            {dataSources.map((source, idx) => (
              <a
                key={idx}
                href={source.url || "#"}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-gray-100 hover:bg-gray-200 transition-colors text-xs text-gray-700"
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

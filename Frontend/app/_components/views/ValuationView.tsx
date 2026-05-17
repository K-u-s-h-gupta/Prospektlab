"use client";

import { RichResponse } from "../lib/types";
import { EntityHeader } from "../EntityHeader";
import { MetricCardGrid } from "../MetricCardGrid";
import { GuidanceFooter } from "../GuidanceFooter";
import dynamic from "next/dynamic";

const GaugeChart = dynamic(() => import("../Charts/GaugeChart").then((m) => m.GaugeChart), {
  ssr: false,
  loading: () => <div className="h-64 bg-gray-100 rounded animate-pulse" />,
});

interface ValuationViewProps {
  data: RichResponse;
}

export function ValuationView({ data }: ValuationViewProps) {
  return (
    <div className="space-y-6 pb-4">
      {/* Title */}
      {data.title && (
        <div>
          <h2 className="text-2xl font-bold text-gray-900">{data.title}</h2>
          {data.subtitle && <p className="text-gray-600 mt-1">{data.subtitle}</p>}
        </div>
      )}

      {/* Entity Header */}
      {data.primary_entity && <EntityHeader entity={data.primary_entity} showPrice={true} compact={false} />}

      {/* Valuation Metric Cards */}
      {data.metric_cards && data.metric_cards.length > 0 && <MetricCardGrid cards={data.metric_cards} columns={3} />}

      {/* DCF Gauge Chart */}
      {data.charts &&
        data.charts.length > 0 &&
        data.charts.map((chart) => {
          if (chart.kind === "gauge") {
            return (
              <div key={chart.id}>
                <h3 className="text-lg font-semibold text-gray-900 mb-4">{chart.title}</h3>
                <GaugeChart chart={chart} />
              </div>
            );
          }
          return null;
        })}

      {/* Valuation Summary */}
      {data.valuation_summary && (
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Valuation Summary</h3>
          <div className="space-y-3">
            {Object.entries(data.valuation_summary).map(([key, value]) => (
              <div key={key} className="flex justify-between text-sm">
                <span className="text-gray-600 capitalize">{key.replace(/_/g, " ")}</span>
                <span className="font-medium text-gray-900">{String(value)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Guidance Footer */}
      {data.primary_entity && <GuidanceFooter entities={[data.primary_entity]} dataSources={data.data_sources} />}

      {/* Disclaimer */}
      {data.disclaimer && <div className="text-xs text-gray-500 mt-4 italic">{data.disclaimer}</div>}
    </div>
  );
}

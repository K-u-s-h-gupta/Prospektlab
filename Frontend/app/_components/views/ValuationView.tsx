"use client";

import { RichResponse } from "../lib/types";
import { EntityHeader } from "../EntityHeader";
import { MetricCardGrid } from "../MetricCardGrid";
import { GuidanceFooter } from "../GuidanceFooter";
import dynamic from "next/dynamic";

const GaugeChart = dynamic(() => import("../Charts/GaugeChart").then((m) => m.GaugeChart), {
  ssr: false,
  loading: () => <div className="h-64 rounded-2xl border border-white/10 bg-white/[0.035] animate-pulse" />,
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
          <h2 className="text-2xl font-semibold text-white">{data.title}</h2>
          {data.subtitle && <p className="mt-1 text-slate-500">{data.subtitle}</p>}
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
                <h3 className="mb-4 text-lg font-semibold text-white">{chart.title}</h3>
                <GaugeChart chart={chart} />
              </div>
            );
          }
          return null;
        })}

      {/* Valuation Summary */}
      {data.valuation_summary && (
        <div className="rounded-2xl border border-white/10 bg-white/[0.035] p-6">
          <h3 className="mb-4 text-lg font-semibold text-white">Valuation Summary</h3>
          <div className="space-y-3">
            {Object.entries(data.valuation_summary).map(([key, value]) => (
              <div key={key} className="flex justify-between text-sm">
                <span className="capitalize text-slate-500">{key.replace(/_/g, " ")}</span>
                <span className="font-medium text-white">{String(value)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Guidance Footer */}
      {data.primary_entity && <GuidanceFooter entities={[data.primary_entity]} dataSources={data.data_sources} />}

      {/* Disclaimer */}
      {data.disclaimer && <div className="mt-4 text-xs italic text-slate-500">{data.disclaimer}</div>}
    </div>
  );
}

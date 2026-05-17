"use client";

import { RichResponse } from "../lib/types";
import { EntityHeader } from "../EntityHeader";
import { MetricCardGrid } from "../MetricCardGrid";
import { StrengthsRisksDual } from "../StrengthsRisksDual";
import { GuidanceFooter } from "../GuidanceFooter";
import dynamic from "next/dynamic";

const BarChart = dynamic(() => import("../Charts/BarChart").then((m) => m.BarChart), {
  ssr: false,
  loading: () => <div className="h-64 rounded-2xl border border-white/10 bg-white/[0.035] animate-pulse" />,
});

const DonutChart = dynamic(() => import("../Charts/DonutChart").then((m) => m.DonutChart), {
  ssr: false,
  loading: () => <div className="h-64 rounded-2xl border border-white/10 bg-white/[0.035] animate-pulse" />,
});

const AreaChart = dynamic(() => import("../Charts/AreaChart").then((m) => m.AreaChart), {
  ssr: false,
  loading: () => <div className="h-64 rounded-2xl border border-white/10 bg-white/[0.035] animate-pulse" />,
});

interface SnapshotViewProps {
  data: RichResponse;
}

export function SnapshotView({ data }: SnapshotViewProps) {
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

      {/* Hero Metric Cards (6 key metrics) */}
      {data.metric_cards && data.metric_cards.length > 0 && <MetricCardGrid cards={data.metric_cards} columns={3} />}

      {/* Charts: Revenue, Profit, Shareholding, Quarterly Trend */}
      {data.charts && data.charts.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {data.charts.map((chart) => {
            if (chart.kind === "bar") {
              return (
                <div key={chart.id}>
                  <h3 className="mb-4 text-lg font-semibold text-white">{chart.title}</h3>
                  <BarChart chart={chart} />
                </div>
              );
            }
            if (chart.kind === "donut") {
              return (
                <div key={chart.id}>
                  <h3 className="mb-4 text-lg font-semibold text-white">{chart.title}</h3>
                  <DonutChart chart={chart} />
                </div>
              );
            }
            if (chart.kind === "area") {
              return (
                <div key={chart.id} className="md:col-span-2">
                  <h3 className="mb-4 text-lg font-semibold text-white">{chart.title}</h3>
                  <AreaChart chart={chart} />
                </div>
              );
            }
            return null;
          })}
        </div>
      )}

      {/* Strengths & Risks */}
      {data.strengths_risks && data.strengths_risks.length > 0 && <StrengthsRisksDual blocks={data.strengths_risks} />}

      {/* Guidance Footer */}
      {data.primary_entity && <GuidanceFooter entities={[data.primary_entity]} dataSources={data.data_sources} />}

      {/* Disclaimer */}
      {data.disclaimer && <div className="mt-4 text-xs italic text-slate-500">{data.disclaimer}</div>}
    </div>
  );
}

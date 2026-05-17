"use client";

import { MetricCard as MetricCardType } from "./lib/types";
import { PartialDataBadge } from "./PartialDataBadge";
import { TrendingUp, TrendingDown } from "lucide-react";

interface MetricCardGridProps {
  cards: MetricCardType[];
  columns?: number;
}

function MetricCard({ card }: { card: MetricCardType }) {
  const changeIsPositive = card.change_type === "positive";
  const changeIsNegative = card.change_type === "negative";

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-2">
        <div className="text-sm font-medium text-gray-600">{card.label}</div>
        {card.is_partial && <PartialDataBadge message="Partial" />}
      </div>

      <div className="space-y-2">
        <div className="text-2xl font-bold text-gray-900">{card.value}</div>

        {card.sub_value && <div className="text-xs text-gray-500">{card.sub_value}</div>}

        {card.change && (
          <div
            className={`flex items-center gap-1 text-xs font-medium ${
              changeIsPositive ? "text-green-600" : changeIsNegative ? "text-red-600" : "text-gray-500"
            }`}
          >
            {changeIsPositive ? <TrendingUp className="w-3 h-3" /> : changeIsNegative ? <TrendingDown className="w-3 h-3" /> : null}
            {card.change}
          </div>
        )}
      </div>

      {card.tooltip && <div className="text-xs text-gray-500 mt-2 italic">{card.tooltip}</div>}
    </div>
  );
}

export function MetricCardGrid({ cards, columns = 4 }: MetricCardGridProps) {
  if (!cards || cards.length === 0) {
    return null;
  }

  const gridCols = {
    1: "grid-cols-1",
    2: "grid-cols-2",
    3: "grid-cols-3",
    4: "grid-cols-4",
  }[Math.min(columns, 4)] || "grid-cols-3";

  return (
    <div className={`grid ${gridCols} gap-4 md:grid-cols-2 lg:${gridCols}`}>
      {cards.map((card, idx) => (
        <MetricCard key={idx} card={card} />
      ))}
    </div>
  );
}

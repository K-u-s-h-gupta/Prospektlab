"use client";

import { TrendingDown, TrendingUp } from "lucide-react";
import { MetricCard as MetricCardType } from "./lib/types";
import { PartialDataBadge } from "./PartialDataBadge";

interface MetricCardGridProps {
  cards: MetricCardType[];
  columns?: number;
}

function MetricCard({ card }: { card: MetricCardType }) {
  const changeIsPositive = card.change_type === "positive";
  const changeIsNegative = card.change_type === "negative";

  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.035] p-4 shadow-sm transition hover:border-cyan-200/20 hover:bg-white/[0.055]">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="text-sm font-medium text-slate-400">{card.label}</div>
        {card.is_partial && <PartialDataBadge message="Partial" />}
      </div>

      <div className="space-y-2">
        <div className="break-words text-2xl font-semibold text-white">{card.value}</div>
        {card.sub_value && <div className="text-xs text-slate-500">{card.sub_value}</div>}
        {card.change && (
          <div
            className={`flex items-center gap-1 text-xs font-medium ${
              changeIsPositive ? "text-lime-200" : changeIsNegative ? "text-rose-200" : "text-slate-500"
            }`}
          >
            {changeIsPositive ? <TrendingUp className="h-3 w-3" /> : changeIsNegative ? <TrendingDown className="h-3 w-3" /> : null}
            {card.change}
          </div>
        )}
      </div>

      {card.tooltip && <div className="mt-3 text-xs text-slate-500">{card.tooltip}</div>}
    </div>
  );
}

export function MetricCardGrid({ cards, columns = 4 }: MetricCardGridProps) {
  if (!cards || cards.length === 0) return null;

  const gridClass =
    columns <= 2
      ? "grid-cols-1 sm:grid-cols-2"
      : columns === 3
        ? "grid-cols-1 sm:grid-cols-2 xl:grid-cols-3"
        : "grid-cols-1 sm:grid-cols-2 xl:grid-cols-4";

  return (
    <div className={`grid ${gridClass} gap-3`}>
      {cards.map((card, idx) => (
        <MetricCard key={`${card.label}-${idx}`} card={card} />
      ))}
    </div>
  );
}

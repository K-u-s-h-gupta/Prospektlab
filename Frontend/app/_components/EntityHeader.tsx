"use client";

import { TrendingDown, TrendingUp } from "lucide-react";
import { Entity } from "./lib/types";

interface EntityHeaderProps {
  entity: Entity;
  showPrice?: boolean;
  compact?: boolean;
}

function formatPrice(value?: number, currency = "INR") {
  if (typeof value !== "number") return "";
  return `${currency} ${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export function EntityHeader({ entity, showPrice = true, compact = false }: EntityHeaderProps) {
  const changeIsPositive = typeof entity.change_pct === "number" && entity.change_pct > 0;
  const changeIsNegative = typeof entity.change_pct === "number" && entity.change_pct < 0;

  if (compact) {
    return (
      <div className="flex items-center justify-between gap-4 py-2">
        <div className="min-w-0">
          <div className="truncate font-semibold text-white">{entity.label}</div>
          {entity.ticker && (
            <div className="text-xs text-slate-500">
              {entity.ticker}
              {entity.exchange && ` / ${entity.exchange}`}
            </div>
          )}
        </div>
        {showPrice && entity.current_price && (
          <div className="text-right">
            <div className="font-semibold text-white">{formatPrice(entity.current_price, entity.currency)}</div>
            {changeIsPositive || changeIsNegative ? (
              <div className={`flex items-center justify-end gap-1 text-xs font-medium ${changeIsPositive ? "text-lime-200" : "text-rose-200"}`}>
                {changeIsPositive ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                {Math.abs(entity.change_pct ?? 0).toFixed(2)}%
              </div>
            ) : null}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-2xl font-semibold text-white">{entity.label}</h2>
          {entity.exchange && (
            <span className="rounded-full border border-cyan-200/20 bg-cyan-200/10 px-2.5 py-1 text-xs font-medium text-cyan-100">
              {entity.exchange}
            </span>
          )}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-500">
          {entity.ticker && <span>{entity.ticker}</span>}
          {entity.sector && <span>/ {entity.sector}</span>}
          {entity.industry && <span>/ {entity.industry}</span>}
        </div>
      </div>

      {showPrice && entity.current_price && (
        <div className="flex flex-wrap items-baseline gap-3">
          <div className="text-3xl font-semibold text-white">{formatPrice(entity.current_price, entity.currency)}</div>
          {changeIsPositive || changeIsNegative ? (
            <div
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 ${
                changeIsPositive ? "border-lime-200/20 bg-lime-200/10 text-lime-100" : "border-rose-200/20 bg-rose-200/10 text-rose-100"
              }`}
            >
              {changeIsPositive ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
              <span className="text-sm font-semibold">
                {changeIsPositive ? "+" : ""}
                {entity.change_pct?.toFixed(2)}%
              </span>
            </div>
          ) : null}
        </div>
      )}

      {entity.description && <p className="text-sm leading-6 text-slate-400">{entity.description}</p>}
    </div>
  );
}

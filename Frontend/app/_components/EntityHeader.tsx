"use client";

import { Entity } from "./lib/types";
import { TrendingUp, TrendingDown } from "lucide-react";

interface EntityHeaderProps {
  entity: Entity;
  showPrice?: boolean;
  compact?: boolean;
}

export function EntityHeader({ entity, showPrice = true, compact = false }: EntityHeaderProps) {
  const changeIsPositive = entity.change_pct && entity.change_pct > 0;
  const changeIsNegative = entity.change_pct && entity.change_pct < 0;

  if (compact) {
    return (
      <div className="flex items-center justify-between py-2">
        <div>
          <div className="font-semibold text-gray-900">{entity.label}</div>
          {entity.ticker && (
            <div className="text-xs text-gray-500">
              {entity.ticker}
              {entity.exchange && ` · ${entity.exchange}`}
            </div>
          )}
        </div>
        {showPrice && entity.current_price && (
          <div className="text-right">
            <div className="font-semibold text-gray-900">₹{entity.current_price.toLocaleString()}</div>
            {changeIsPositive || changeIsNegative ? (
              <div
                className={`flex items-center justify-end gap-1 text-xs font-medium ${
                  changeIsPositive ? "text-green-600" : "text-red-600"
                }`}
              >
                {changeIsPositive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                {Math.abs(entity.change_pct ?? 0).toFixed(2)}%
              </div>
            ) : null}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div>
        <div className="flex items-center gap-3">
          <h2 className="text-2xl font-bold text-gray-900">{entity.label}</h2>
          {entity.exchange && (
            <span className="px-2.5 py-1 rounded-full bg-blue-50 text-xs font-medium text-blue-700">
              {entity.exchange}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-sm text-gray-600 mt-1">
          {entity.ticker && <span>{entity.ticker}</span>}
          {entity.sector && (
            <>
              <span>·</span>
              <span>{entity.sector}</span>
            </>
          )}
          {entity.industry && (
            <>
              <span>·</span>
              <span>{entity.industry}</span>
            </>
          )}
        </div>
      </div>

      {showPrice && entity.current_price && (
        <div className="flex items-baseline gap-2">
          <div className="text-3xl font-bold text-gray-900">₹{entity.current_price.toLocaleString()}</div>
          {changeIsPositive || changeIsNegative ? (
            <div
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full ${
                changeIsPositive ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
              }`}
            >
              {changeIsPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
              <span className="text-sm font-semibold">
                {changeIsPositive ? "+" : ""}
                {entity.change_pct?.toFixed(2)}%
              </span>
            </div>
          ) : null}
        </div>
      )}

      {entity.description && <p className="text-sm text-gray-600 leading-relaxed">{entity.description}</p>}
    </div>
  );
}

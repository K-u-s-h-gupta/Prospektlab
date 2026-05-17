"use client";

import { Entity } from "./lib/types";
import { EntityHeader } from "./EntityHeader";

interface ComparisonHeroProps {
  primary?: Entity;
  secondary?: Entity;
}

export function ComparisonHero({ primary, secondary }: ComparisonHeroProps) {
  if (!primary || !secondary) {
    return null;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pb-6">
      <div className="space-y-2">
        <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Primary</div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <EntityHeader entity={primary} showPrice={true} compact={false} />
        </div>
      </div>

      <div className="space-y-2">
        <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide">Secondary</div>
        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <EntityHeader entity={secondary} showPrice={true} compact={false} />
        </div>
      </div>
    </div>
  );
}

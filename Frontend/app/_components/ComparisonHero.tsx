"use client";

import { EntityHeader } from "./EntityHeader";
import { Entity } from "./lib/types";

interface ComparisonHeroProps {
  primary?: Entity;
  secondary?: Entity;
}

export function ComparisonHero({ primary, secondary }: ComparisonHeroProps) {
  if (!primary || !secondary) return null;

  return (
    <div className="grid grid-cols-1 gap-3 pb-2 md:grid-cols-2">
      <div className="space-y-2">
        <div className="text-xs font-medium uppercase tracking-[0.2em] text-slate-500">Primary</div>
        <div className="rounded-2xl border border-white/10 bg-white/[0.035] p-4">
          <EntityHeader entity={primary} showPrice compact={false} />
        </div>
      </div>

      <div className="space-y-2">
        <div className="text-xs font-medium uppercase tracking-[0.2em] text-slate-500">Secondary</div>
        <div className="rounded-2xl border border-white/10 bg-white/[0.035] p-4">
          <EntityHeader entity={secondary} showPrice compact={false} />
        </div>
      </div>
    </div>
  );
}

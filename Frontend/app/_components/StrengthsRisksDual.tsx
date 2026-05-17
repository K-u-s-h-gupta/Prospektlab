"use client";

import { AlertCircle, CheckCircle2 } from "lucide-react";
import { StrengthsRisksBlock } from "./lib/types";

interface StrengthsRisksDualProps {
  blocks: StrengthsRisksBlock[];
}

function PointList({ items, tone }: { items: string[]; tone: "good" | "risk" }) {
  return (
    <ul className="space-y-2">
      {items.map((item, idx) => (
        <li key={`${item}-${idx}`} className={`flex items-start gap-2 text-sm ${tone === "good" ? "text-lime-50" : "text-rose-50"}`}>
          <span className={`mt-2 h-1.5 w-1.5 shrink-0 rounded-full ${tone === "good" ? "bg-lime-200" : "bg-rose-200"}`} />
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

export function StrengthsRisksDual({ blocks }: StrengthsRisksDualProps) {
  if (!blocks || blocks.length === 0) return null;

  return (
    <div>
      <h3 className="mb-3 text-lg font-semibold text-white">Strengths & Risks</h3>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {blocks.map((block, idx) => (
          <div key={`${block.entity_label}-${idx}`} className="space-y-3">
            {blocks.length > 1 && <h4 className="font-semibold text-slate-200">{block.entity_label}</h4>}
            <div className="rounded-2xl border border-lime-200/15 bg-lime-200/8 p-4">
              <div className="mb-3 flex items-center gap-2">
                <CheckCircle2 className="h-4 w-4 text-lime-200" />
                <h5 className="text-sm font-semibold text-lime-100">Strengths</h5>
              </div>
              <PointList items={block.strengths || []} tone="good" />
            </div>
            <div className="rounded-2xl border border-rose-200/15 bg-rose-200/8 p-4">
              <div className="mb-3 flex items-center gap-2">
                <AlertCircle className="h-4 w-4 text-rose-200" />
                <h5 className="text-sm font-semibold text-rose-100">Risks</h5>
              </div>
              <PointList items={block.risks || []} tone="risk" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

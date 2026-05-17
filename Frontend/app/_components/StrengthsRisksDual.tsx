"use client";

import { StrengthsRisksBlock } from "./lib/types";
import { CheckCircle2, AlertCircle } from "lucide-react";

interface StrengthsRisksDualProps {
  blocks: StrengthsRisksBlock[];
}

export function StrengthsRisksDual({ blocks }: StrengthsRisksDualProps) {
  if (!blocks || blocks.length === 0) {
    return null;
  }

  if (blocks.length === 1) {
    // Single entity: side-by-side strengths and risks
    const block = blocks[0];
    return (
      <div>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Strengths & Risks</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Strengths */}
          <div className="rounded-lg border border-green-200 bg-green-50 p-4">
            <div className="flex items-center gap-2 mb-3">
              <CheckCircle2 className="w-5 h-5 text-green-600" />
              <h4 className="font-semibold text-green-900">Strengths</h4>
            </div>
            <ul className="space-y-2">
              {(block.strengths || []).map((strength, idx) => (
                <li key={idx} className="text-sm text-green-800 flex items-start gap-2">
                  <span className="text-green-600 mt-0.5">•</span>
                  <span>{strength}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Risks */}
          <div className="rounded-lg border border-red-200 bg-red-50 p-4">
            <div className="flex items-center gap-2 mb-3">
              <AlertCircle className="w-5 h-5 text-red-600" />
              <h4 className="font-semibold text-red-900">Risks</h4>
            </div>
            <ul className="space-y-2">
              {(block.risks || []).map((risk, idx) => (
                <li key={idx} className="text-sm text-red-800 flex items-start gap-2">
                  <span className="text-red-600 mt-0.5">•</span>
                  <span>{risk}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    );
  }

  // Multiple entities: side-by-side comparison panels
  return (
    <div>
      <h3 className="text-lg font-semibold text-gray-900 mb-4">Strengths & Risks</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {blocks.map((block, idx) => (
          <div key={idx} className="space-y-4">
            <h4 className="font-semibold text-gray-900">{block.entity_label}</h4>

            {/* Strengths */}
            <div className="rounded-lg border border-green-200 bg-green-50 p-4">
              <div className="flex items-center gap-2 mb-3">
                <CheckCircle2 className="w-4 h-4 text-green-600" />
                <h5 className="font-medium text-green-900 text-sm">Strengths</h5>
              </div>
              <ul className="space-y-1.5">
                {(block.strengths || []).map((strength, sidx) => (
                  <li key={sidx} className="text-xs text-green-800 flex items-start gap-2">
                    <span className="text-green-600 mt-0.5">•</span>
                    <span>{strength}</span>
                  </li>
                ))}
              </ul>
            </div>

            {/* Risks */}
            <div className="rounded-lg border border-red-200 bg-red-50 p-4">
              <div className="flex items-center gap-2 mb-3">
                <AlertCircle className="w-4 h-4 text-red-600" />
                <h5 className="font-medium text-red-900 text-sm">Risks</h5>
              </div>
              <ul className="space-y-1.5">
                {(block.risks || []).map((risk, ridx) => (
                  <li key={ridx} className="text-xs text-red-800 flex items-start gap-2">
                    <span className="text-red-600 mt-0.5">•</span>
                    <span>{risk}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

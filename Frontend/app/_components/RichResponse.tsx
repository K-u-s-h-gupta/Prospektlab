"use client";

import { RichResponse } from "./lib/types";
import { ComparisonView } from "./views/ComparisonView";
import { SnapshotView } from "./views/SnapshotView";
import { ValuationView } from "./views/ValuationView";
import { NewsView } from "./views/NewsView";
import { FilingView } from "./views/FilingView";
import { DocCompareView } from "./views/DocCompareView";

interface RichResponseProps {
  data: RichResponse;
}

/**
 * Root dispatcher for RichResponse rendering.
 * Routes to the appropriate view based on rich.mode.
 */
export function RichResponseComponent({ data }: RichResponseProps) {
  if (!data) {
    return null;
  }

  const { mode } = data;

  switch (mode) {
    case "comparison":
      return <ComparisonView data={data} />;
    case "snapshot":
      return <SnapshotView data={data} />;
    case "valuation":
      return <ValuationView data={data} />;
    case "news":
      return <NewsView data={data} />;
    case "filing":
      return <FilingView data={data} />;
    case "doc_compare":
      return <DocCompareView data={data} />;
    case "chat":
    default:
      return null;
  }
}

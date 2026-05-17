"use client";

interface PartialDataBadgeProps {
  message?: string;
}

export function PartialDataBadge({ message = "Partial Data" }: PartialDataBadgeProps) {
  return (
    <div className="inline-flex items-center gap-1.5 rounded-full border border-amber-200/20 bg-amber-200/10 px-2.5 py-1 text-xs font-medium text-amber-100">
      <div className="h-1.5 w-1.5 rounded-full bg-amber-200" />
      {message}
    </div>
  );
}

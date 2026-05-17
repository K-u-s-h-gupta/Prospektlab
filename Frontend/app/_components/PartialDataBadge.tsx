"use client";

interface PartialDataBadgeProps {
  message?: string;
}

export function PartialDataBadge({ message = "Partial Data" }: PartialDataBadgeProps) {
  return (
    <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-50 border border-amber-200 text-xs font-medium text-amber-700">
      <div className="w-1.5 h-1.5 rounded-full bg-amber-500" />
      {message}
    </div>
  );
}

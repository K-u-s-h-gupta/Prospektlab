"use client";

interface SparklineProps {
  data: number[];
  color?: string;
}

export function Sparkline({ data, color = "#3b82f6" }: SparklineProps) {
  if (!data || data.length === 0) return <div className="w-12 h-6 bg-gray-100 rounded" />;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const points = data.map((v, i) => {
    const x = (i / Math.max(1, data.length - 1)) * 48;
    const y = max === min ? 12 : 24 - ((v - min) / (max - min)) * 20;
    return `${x},${y}`;
  }).join(" ");

  return (
    <svg width="48" height="24" viewBox="0 0 48 24" className="overflow-visible">
      <polyline fill="none" stroke={color} strokeWidth="1.5" points={points} />
    </svg>
  );
}

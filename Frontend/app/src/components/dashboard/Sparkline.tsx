import React from 'react';

interface SparklineProps {
  data: number[];
  positive?: boolean;
  width?: number;
  height?: number;
  strokeWidth?: number;
  fill?: boolean;
}

/** Google Finance-style smooth sparkline with end dot and nice gradient */
export const Sparkline: React.FC<SparklineProps> = ({
  data,
  positive = true,
  width = 220,
  height = 42,
  strokeWidth = 1.75,
  fill = true,
}) => {
  if (!data || data.length < 2) return null;

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const stepX = width / (data.length - 1);

  const points = data.map((v, i) => ({
    x: i * stepX,
    y: height - ((v - min) / range) * (height - 6) - 3,
  }));

  // Build smooth path using quadratic curves for Google-Finance polish
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1];
    const curr = points[i];
    const midX = (prev.x + curr.x) / 2;
    path += ` Q ${midX} ${prev.y} ${curr.x} ${curr.y}`;
  }

  const areaPath = `${path} L ${width} ${height} L 0 ${height} Z`;

  const stroke = positive ? '#34D399' : '#FB7185';
  const gradId = `spark-grad-${positive ? 'p' : 'n'}`;

  const lastPoint = points[points.length - 1];

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      <defs>
        <linearGradient id={gradId} x1="0%" y1="0%" x2="0%" y2="100%">
          <stop offset="0%" stopColor={stroke} stopOpacity={0.35} />
          <stop offset="100%" stopColor={stroke} stopOpacity={0.02} />
        </linearGradient>
      </defs>

      {fill && <path d={areaPath} fill={`url(#${gradId})`} />}
      <path
        d={path}
        stroke={stroke}
        strokeWidth={strokeWidth}
        fill="none"
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {/* Current price dot */}
      <circle
        cx={lastPoint.x}
        cy={lastPoint.y}
        r="2.5"
        fill={stroke}
        stroke="#0F172A"
        strokeWidth="1"
      />
    </svg>
  );
};

export default Sparkline;

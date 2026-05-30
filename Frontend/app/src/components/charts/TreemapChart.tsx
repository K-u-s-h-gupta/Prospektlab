import React, { useRef, useEffect } from 'react';
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement } from 'chart.js';

ChartJS.register(CategoryScale, LinearScale, BarElement);

interface TreemapChartProps {
  labels: string[];
  data: number[];
  title?: string;
  unit?: string;
}

export const TreemapChart: React.FC<TreemapChartProps> = ({
  labels,
  data,
  title,
  unit = '%'
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!canvasRef.current || !labels.length) return;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const container = canvas.parentElement;
    const width = container?.clientWidth || 600;
    const height = 300;
    canvas.width = width;
    canvas.height = height;

    const total = data.reduce((a, b) => a + b, 0);
    if (total <= 0) return;

    const colors = [
      '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
      '#06b6d4', '#ec4899', '#84cc16', '#f97316', '#6366f1'
    ];

    // Simple treemap layout using squarified algorithm
    interface Rect { x: number; y: number; w: number; h: number; label: string; value: number; color: string; }
    const rects: Rect[] = [];
    const sorted = labels
      .map((l, i) => ({ label: l, value: data[i], color: colors[i % colors.length] }))
      .sort((a, b) => b.value - a.value);

    const layoutRects = (items: typeof sorted, x: number, y: number, w: number, h: number) => {
      if (!items.length) return;
      if (items.length === 1) {
        const r = items[0];
        rects.push({ x, y, w, h, label: r.label, value: r.value, color: r.color });
        return;
      }

      const area = w * h;
      const totalVal = items.reduce((s, i) => s + i.value, 0);
      const scale = area / totalVal;

      // split into two roughly equal groups
      let splitIdx = 0;
      let runningSum = 0;
      for (let i = 0; i < items.length; i++) {
        runningSum += items[i].value;
        if (runningSum >= totalVal / 2) {
          splitIdx = i + 1;
          break;
        }
      }
      if (splitIdx >= items.length) splitIdx = Math.max(1, items.length - 1);

      const groupA = items.slice(0, splitIdx);
      const groupB = items.slice(splitIdx);

      if (w >= h) {
        const areaA = groupA.reduce((s, i) => s + i.value, 0) * scale;
        const wA = areaA / h;
        layoutRects(groupA, x, y, wA, h);
        layoutRects(groupB, x + wA, y, w - wA, h);
      } else {
        const areaA = groupA.reduce((s, i) => s + i.value, 0) * scale;
        const hA = areaA / w;
        layoutRects(groupA, x, y, w, hA);
        layoutRects(groupB, x, y + hA, w, h - hA);
      }
    };

    layoutRects(sorted, 0, 0, width, height);

    // Draw
    ctx.clearRect(0, 0, width, height);

    rects.forEach(r => {
      const pct = ((r.value / total) * 100).toFixed(1);

      // Background
      ctx.fillStyle = r.color;
      ctx.fillRect(r.x + 1, r.y + 1, r.w - 2, r.h - 2);

      // Text
      ctx.fillStyle = '#ffffff';
      ctx.font = `${Math.max(10, Math.min(13, r.w / 10))}px monospace`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';

      const cx = r.x + r.w / 2;
      const cy = r.y + r.h / 2;

      if (r.w > 50 && r.h > 30) {
        ctx.font = '11px monospace';
        ctx.fillStyle = 'rgba(255,255,255,0.95)';
        ctx.fillText(r.label, cx, cy - 8);
        ctx.font = 'bold 12px monospace';
        ctx.fillText(`${pct}${unit}`, cx, cy + 10);
      }
    });
  }, [labels, data, unit]);

  return (
    <div className="glass" style={{
      padding: '16px',
      margin: '12px 0',
      display: 'flex',
      flexDirection: 'column',
      gap: '10px',
      background: 'rgba(15, 23, 42, 0.45)',
      border: '1px solid rgba(255, 255, 255, 0.05)',
      borderRadius: '8px',
      width: '100%'
    }}>
      {title && (
        <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)' }}>
          {title}
        </div>
      )}
      <canvas ref={canvasRef} style={{ width: '100%', height: '300px' }} />
    </div>
  );
};

export default TreemapChart;

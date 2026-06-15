export function toFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Normalize backend chart payloads (x_labels/kind/series.values vs labels/chart_type/series.data). */
export function normalizeChartForRender(chart: any) {
  if (!chart) return null;
  const rawType = String(chart.chart_type || chart.kind || 'bar').toLowerCase();
  const kind =
    rawType === 'area' || rawType === 'multi_line'
      ? 'line'
      : rawType === 'multi_bar'
        ? 'bar'
        : rawType;
  const xLabels: string[] = chart.x_labels || chart.labels || [];
  const series = (chart.series || []).map((s: any) => {
    const rawValues = Array.isArray(s?.values)
      ? s.values
      : Array.isArray(s?.data)
        ? s.data.map((d: any) => (d && typeof d === 'object' ? d.value : d))
        : [];
    const values = rawValues
      .map((v: any) => toFiniteNumber(v))
      .filter((v: number | null): v is number => v !== null);
    return { ...s, values };
  });
  return { ...chart, kind, x_labels: xLabels, series };
}

export function chartHasRenderableData(chart: any): boolean {
  const normalized = normalizeChartForRender(chart);
  if (!normalized) return false;
  const labels = normalized.x_labels || [];
  const series = normalized.series || [];
  if (!series.length) return false;
  const hasValues = series.some((s: any) => (s.values || []).length > 0);
  if (normalized.kind === 'donut' || normalized.kind === 'treemap') {
    return labels.length > 0 && hasValues;
  }
  return labels.length > 0 && hasValues;
}

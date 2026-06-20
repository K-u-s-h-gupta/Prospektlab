export type ProspektCoverKind = 'market' | 'research' | 'watchlist';

export interface ProspektCoverOptions {
  seed: string;
  title?: string;
  source?: string;
  label?: string;
  symbol?: string;
  kind?: ProspektCoverKind;
}

const PALETTES = [
  { bgA: '#06111f', bgB: '#10233b', panel: '#17314a', accent: '#38bdf8', accent2: '#22c55e', warm: '#f97316' },
  { bgA: '#07131f', bgB: '#122b2d', panel: '#173b3d', accent: '#2dd4bf', accent2: '#60a5fa', warm: '#f59e0b' },
  { bgA: '#080f1d', bgB: '#1b2440', panel: '#252f4c', accent: '#a78bfa', accent2: '#38bdf8', warm: '#fb7185' },
  { bgA: '#07130f', bgB: '#183426', panel: '#21422f', accent: '#34d399', accent2: '#38bdf8', warm: '#fbbf24' },
  { bgA: '#0b111c', bgB: '#2a2234', panel: '#342943', accent: '#fb7185', accent2: '#f59e0b', warm: '#38bdf8' },
];

const KIND_LABELS: Record<ProspektCoverKind, string> = {
  market: 'Market Intelligence',
  research: 'ProspektLab Research',
  watchlist: 'Watchlist Brief',
};

const escapeXml = (value: string) =>
  String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');

const hashText = (value: string) => {
  let hash = 2166136261;
  for (let idx = 0; idx < value.length; idx += 1) {
    hash ^= value.charCodeAt(idx);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
};

const makeRandom = (seed: number) => {
  let state = seed >>> 0;
  return () => {
    state += 0x6D2B79F5;
    let value = Math.imul(state ^ (state >>> 15), 1 | state);
    value ^= value + Math.imul(value ^ (value >>> 7), 61 | value);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
};

const cleanDisplayText = (value: string, fallback: string) => {
  const cleaned = String(value || '')
    .replace(/\s+/g, ' ')
    .trim();
  return cleaned || fallback;
};

const compactUpper = (value: string, fallback: string, maxLength: number) => {
  const text = cleanDisplayText(value, fallback).toUpperCase();
  return text.length > maxLength ? `${text.slice(0, Math.max(0, maxLength - 1))}.` : text;
};

const wrapTitle = (value: string) => {
  const words = cleanDisplayText(value, 'Market signal').split(/\s+/);
  const lines: string[] = [];
  let current = '';

  for (const word of words) {
    const next = current ? `${current} ${word}` : word;
    if (next.length > 31 && current) {
      lines.push(current);
      current = word;
    } else {
      current = next;
    }
    if (lines.length === 2) break;
  }
  if (lines.length < 2 && current) lines.push(current);

  return lines.slice(0, 2).map((line) => (line.length > 34 ? `${line.slice(0, 33)}.` : line));
};

const buildSparkline = (rand: () => number, baseY: number, amplitude: number) => {
  const points: string[] = [];
  let trend = rand() > 0.45 ? -1 : 1;
  for (let idx = 0; idx < 11; idx += 1) {
    if (rand() > 0.74) trend *= -1;
    const x = 610 + idx * 48;
    const wave = Math.sin(idx * 0.9 + rand() * 0.8) * amplitude * 0.55;
    const drift = trend * idx * 4.2;
    const noise = (rand() - 0.5) * amplitude;
    const y = Math.max(92, Math.min(410, baseY + wave + drift + noise));
    points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
  }
  return points.join(' ');
};

const buildBars = (rand: () => number, palette: typeof PALETTES[number]) => {
  const bars: string[] = [];
  for (let idx = 0; idx < 12; idx += 1) {
    const x = 650 + idx * 38;
    const height = 42 + rand() * 130;
    const y = 470 - height;
    const fill = idx % 3 === 0 ? palette.warm : idx % 2 === 0 ? palette.accent : palette.accent2;
    bars.push(`<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="16" height="${height.toFixed(1)}" rx="7" fill="${fill}" opacity="${(0.28 + rand() * 0.42).toFixed(2)}"/>`);
  }
  return bars.join('');
};

const buildCandles = (rand: () => number, palette: typeof PALETTES[number]) => {
  const candles: string[] = [];
  for (let idx = 0; idx < 9; idx += 1) {
    const x = 320 + idx * 44;
    const y = 126 + rand() * 100;
    const wick = 54 + rand() * 86;
    const body = 22 + rand() * 54;
    const fill = idx % 2 === 0 ? palette.accent : palette.warm;
    candles.push(`<line x1="${x}" y1="${(y - 16).toFixed(1)}" x2="${x}" y2="${(y + wick).toFixed(1)}" stroke="${fill}" stroke-width="4" opacity="0.46"/>`);
    candles.push(`<rect x="${x - 10}" y="${y.toFixed(1)}" width="20" height="${body.toFixed(1)}" rx="4" fill="${fill}" opacity="0.72"/>`);
  }
  return candles.join('');
};

export const buildProspektCover = ({
  seed,
  title = '',
  source = '',
  label = '',
  symbol = '',
  kind = 'market',
}: ProspektCoverOptions) => {
  const hash = hashText(`${kind}:${seed}:${title}:${source}:${symbol}`);
  const rand = makeRandom(hash);
  const palette = PALETTES[hash % PALETTES.length];
  const gradientId = `g${hash.toString(16)}`;
  const gridId = `grid${hash.toString(16)}`;
  const clipId = `clip${hash.toString(16)}`;
  const eyebrow = compactUpper(label || KIND_LABELS[kind], KIND_LABELS[kind], 28);
  const sourceLabel = compactUpper(symbol || source, kind === 'watchlist' ? 'WATCHLIST' : 'PROSPEKTLAB', 24);
  const titleLines = wrapTitle(title || source || label || KIND_LABELS[kind]);
  const sparkline = buildSparkline(rand, 255 + rand() * 40, 78 + rand() * 28);
  const accentOrbX = 870 + rand() * 130;
  const accentOrbY = 96 + rand() * 76;
  const variant = hash % 3;

  const svg = `
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675" role="img" aria-label="${escapeXml(title || eyebrow)}">
  <defs>
    <linearGradient id="${gradientId}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="${palette.bgA}"/>
      <stop offset="52%" stop-color="${palette.bgB}"/>
      <stop offset="100%" stop-color="#030712"/>
    </linearGradient>
    <pattern id="${gridId}" width="64" height="64" patternUnits="userSpaceOnUse">
      <path d="M 64 0 L 0 0 0 64" fill="none" stroke="#94a3b8" stroke-width="1" opacity="0.12"/>
    </pattern>
    <clipPath id="${clipId}">
      <rect x="0" y="0" width="1200" height="675" rx="36"/>
    </clipPath>
  </defs>
  <g clip-path="url(#${clipId})">
    <rect width="1200" height="675" fill="url(#${gradientId})"/>
    <rect width="1200" height="675" fill="url(#${gridId})"/>
    <path d="M0 512 C160 438 286 552 452 470 C618 388 722 454 880 366 C1028 284 1122 314 1200 260 L1200 675 L0 675 Z" fill="${palette.panel}" opacity="0.34"/>
    <circle cx="${accentOrbX.toFixed(1)}" cy="${accentOrbY.toFixed(1)}" r="210" fill="${palette.accent}" opacity="0.08"/>
    <circle cx="100" cy="604" r="240" fill="${palette.warm}" opacity="0.055"/>
    <rect x="470" y="52" width="260" height="48" rx="18" fill="rgba(15, 23, 42, 0.54)" stroke="${palette.accent}" stroke-width="1.5" opacity="0.94"/>
    <text x="508" y="84" fill="#e2f6ff" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="24" font-weight="800">PL</text>
    <text x="562" y="83" fill="${palette.accent}" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="15" font-weight="800" letter-spacing="2.4">INTEL</text>
    <text x="600" y="150" text-anchor="middle" fill="${palette.accent}" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="22" font-weight="800" letter-spacing="3.6">${escapeXml(eyebrow)}</text>
    <text x="600" y="194" text-anchor="middle" fill="#94a3b8" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="20" font-weight="700" letter-spacing="2">${escapeXml(sourceLabel)}</text>
    ${variant === 0 ? buildCandles(rand, palette) : ''}
    ${variant === 1 ? buildBars(rand, palette) : ''}
    <polyline points="${sparkline}" fill="none" stroke="${palette.accent}" stroke-width="9" stroke-linecap="round" stroke-linejoin="round" opacity="0.86"/>
    <polyline points="${sparkline}" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.52"/>
    <path d="M596 502 L1110 502" stroke="#94a3b8" stroke-width="1.4" opacity="0.22"/>
    <path d="M596 408 L1110 408" stroke="#94a3b8" stroke-width="1.4" opacity="0.16"/>
    <path d="M596 314 L1110 314" stroke="#94a3b8" stroke-width="1.4" opacity="0.16"/>
    <rect x="276" y="470" width="648" height="124" rx="28" fill="rgba(2, 6, 23, 0.58)" stroke="rgba(148, 163, 184, 0.18)"/>
    <text x="600" y="524" text-anchor="middle" fill="#f8fafc" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="39" font-weight="800">${escapeXml(titleLines[0] || sourceLabel)}</text>
    <text x="600" y="570" text-anchor="middle" fill="#cbd5e1" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="34" font-weight="720">${escapeXml(titleLines[1] || '')}</text>
    <rect x="494" y="606" width="212" height="42" rx="16" fill="rgba(15, 23, 42, 0.58)" stroke="${palette.accent2}" stroke-width="1.5" opacity="0.9"/>
    <text x="600" y="633" text-anchor="middle" fill="${palette.accent2}" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="15" font-weight="800" letter-spacing="2.8">${kind === 'research' ? 'SOURCE BACKED' : 'LIVE SIGNAL'}</text>
  </g>
</svg>`.trim();

  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
};

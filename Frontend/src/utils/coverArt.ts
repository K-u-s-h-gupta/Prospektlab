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

const RESEARCH_PALETTES = [
  { bgA: '#0b1528', bgB: '#14233b', panel: '#1a3048', accent: '#0f7a5c', accent2: '#eae3d6', warm: '#9a6b16' },
  { bgA: '#0a1424', bgB: '#16263d', panel: '#1f3550', accent: '#1f56d6', accent2: '#eae3d6', warm: '#0f7a5c' },
  { bgA: '#0c121f', bgB: '#1b2438', panel: '#24314a', accent: '#9a6b16', accent2: '#eae3d6', warm: '#c0402f' },
  { bgA: '#08131d', bgB: '#132a2d', panel: '#183b3d', accent: '#2dd4bf', accent2: '#eae3d6', warm: '#1f56d6' },
];

type ResearchVisualTheme = {
  label: string;
  badge: string;
  accent: string;
  motif: (palette: typeof RESEARCH_PALETTES[number], rand: () => number) => string;
};

const RESEARCH_THEME_RULES: Array<{ tokens: string[]; theme: ResearchVisualTheme }> = [
  {
    tokens: ['scam', 'fraud', 'ponzi', 'forged', 'siphon', 'embezzle', 'manipulation'],
    theme: {
      label: 'Forensic Brief',
      badge: 'RISK WATCH',
      accent: '#c0402f',
      motif: (palette, rand) => `
        <rect x="760" y="118" width="220" height="280" rx="18" fill="rgba(2, 6, 23, 0.42)" stroke="${palette.warm}" stroke-width="2" opacity="0.72"/>
        <circle cx="870" cy="210" r="58" fill="none" stroke="${palette.warm}" stroke-width="5" opacity="0.55"/>
        <line x1="910" y1="250" x2="980" y2="320" stroke="${palette.warm}" stroke-width="6" opacity="0.62"/>
        <path d="M790 360 L860 300 L930 360 L1000 290" fill="none" stroke="${palette.accent2}" stroke-width="3" opacity="0.34"/>
        ${Array.from({ length: 7 }, (_, idx) => {
          const x = 790 + idx * 24;
          const y = 390 + rand() * 18;
          return `<circle cx="${x}" cy="${y}" r="3" fill="${palette.warm}" opacity="${(0.25 + rand() * 0.35).toFixed(2)}"/>`;
        }).join('')}
      `,
    },
  },
  {
    tokens: ['sebi', 'probe', 'enforcement', 'adjudication', 'penalty', 'compliance', 'show cause'],
    theme: {
      label: 'Regulatory Brief',
      badge: 'SEBI LENS',
      accent: '#0f7a5c',
      motif: (palette) => `
        <path d="M820 150 L980 150 L900 250 Z" fill="none" stroke="${palette.accent}" stroke-width="4" opacity="0.58"/>
        <rect x="790" y="280" width="180" height="130" rx="14" fill="rgba(15, 23, 42, 0.55)" stroke="${palette.accent2}" stroke-width="1.5" opacity="0.8"/>
        <rect x="810" y="300" width="140" height="10" rx="4" fill="${palette.accent2}" opacity="0.28"/>
        <rect x="810" y="322" width="110" height="8" rx="4" fill="${palette.accent2}" opacity="0.22"/>
        <rect x="810" y="342" width="125" height="8" rx="4" fill="${palette.accent2}" opacity="0.18"/>
        <circle cx="930" cy="380" r="22" fill="none" stroke="${palette.accent}" stroke-width="3" opacity="0.5"/>
      `,
    },
  },
  {
    tokens: ['bank', 'hdfc', 'icici', 'sbi', 'nim', 'deposit', 'credit', 'loan'],
    theme: {
      label: 'Banking Brief',
      badge: 'BANKING',
      accent: '#9a6b16',
      motif: (palette) => `
        <rect x="790" y="130" width="34" height="250" rx="8" fill="${palette.accent2}" opacity="0.18"/>
        <rect x="836" y="170" width="34" height="210" rx="8" fill="${palette.accent}" opacity="0.34"/>
        <rect x="882" y="150" width="34" height="230" rx="8" fill="${palette.accent2}" opacity="0.22"/>
        <rect x="928" y="190" width="34" height="190" rx="8" fill="${palette.warm}" opacity="0.42"/>
        <path d="M770 390 H1010" stroke="${palette.accent2}" stroke-width="2" opacity="0.28"/>
        <path d="M770 120 Q900 88 1010 120" fill="none" stroke="${palette.warm}" stroke-width="3" opacity="0.45"/>
      `,
    },
  },
  {
    tokens: ['it ', 'tcs', 'infosys', 'wipro', 'tech', 'software', 'digital', 'cloud', 'ai '],
    theme: {
      label: 'Technology Brief',
      badge: 'TECH SECTOR',
      accent: '#1f56d6',
      motif: (palette) => `
        ${Array.from({ length: 8 }, (_, idx) => {
          const x = 790 + (idx % 4) * 58;
          const y = 140 + Math.floor(idx / 4) * 72;
          return `<circle cx="${x + 24}" cy="${y + 24}" r="16" fill="none" stroke="${palette.accent}" stroke-width="3" opacity="0.55"/>
                  <line x1="${x + 40}" y1="${y + 24}" x2="${x + 58}" y2="${y + 24}" stroke="${palette.accent2}" stroke-width="2" opacity="0.35"/>`;
        }).join('')}
        <polyline points="790,360 860,320 930,340 1010,280" fill="none" stroke="${palette.accent}" stroke-width="5" opacity="0.62"/>
      `,
    },
  },
  {
    tokens: ['ipo', 'listing', 'drhp', 'prospectus', 'subscription'],
    theme: {
      label: 'Listing Brief',
      badge: 'IPO DESK',
      accent: '#9a6b16',
      motif: (palette) => `
        <ellipse cx="900" cy="250" rx="92" ry="28" fill="rgba(154, 107, 22, 0.18)" stroke="${palette.warm}" stroke-width="2"/>
        <rect x="860" y="170" width="80" height="110" rx="10" fill="rgba(15, 23, 42, 0.62)" stroke="${palette.accent2}" stroke-width="1.5"/>
        <path d="M880 200 H920 M880 220 H920 M880 240 H910" stroke="${palette.accent2}" stroke-width="3" opacity="0.35"/>
      `,
    },
  },
  {
    tokens: ['rbi', 'repo', 'inflation', 'gdp', 'budget', 'monetary', 'bond', 'yield', 'rupee'],
    theme: {
      label: 'Macro Brief',
      badge: 'MACRO VIEW',
      accent: '#9a6b16',
      motif: (palette) => `
        <circle cx="900" cy="250" r="88" fill="none" stroke="${palette.warm}" stroke-width="3" opacity="0.42"/>
        <path d="M900 162 L900 338 M812 250 H988" stroke="${palette.accent2}" stroke-width="2" opacity="0.22"/>
        <path d="M850 210 C870 180 930 180 950 210" fill="none" stroke="${palette.accent}" stroke-width="4" opacity="0.5"/>
        <rect x="830" y="320" width="140" height="54" rx="12" fill="rgba(15, 23, 42, 0.58)" stroke="${palette.warm}" stroke-width="1.5"/>
      `,
    },
  },
  {
    tokens: ['deal', 'merger', 'acquisition', 'stake', 'buyout', 'joint venture'],
    theme: {
      label: 'Corporate Action',
      badge: 'DEAL FLOW',
      accent: '#9a6b16',
      motif: (palette) => `
        <circle cx="860" cy="250" r="54" fill="none" stroke="${palette.warm}" stroke-width="4" opacity="0.58"/>
        <circle cx="940" cy="250" r="54" fill="none" stroke="${palette.accent2}" stroke-width="4" opacity="0.48"/>
        <rect x="885" y="330" width="30" height="70" rx="8" fill="${palette.accent}" opacity="0.42"/>
      `,
    },
  },
  {
    tokens: ['earnings', 'results', 'quarter', 'profit', 'margin', 'revenue', 'ebitda', 'pat'],
    theme: {
      label: 'Earnings Brief',
      badge: 'RESULTS',
      accent: '#0f7a5c',
      motif: (palette, rand) => `
        ${Array.from({ length: 10 }, (_, idx) => {
          const x = 790 + idx * 22;
          const height = 40 + rand() * 120;
          const y = 390 - height;
          const fill = idx % 3 === 0 ? palette.accent : palette.accent2;
          return `<rect x="${x}" y="${y}" width="14" height="${height}" rx="6" fill="${fill}" opacity="${(0.24 + rand() * 0.42).toFixed(2)}"/>`;
        }).join('')}
        <polyline points="790,300 860,260 930,280 1010,220" fill="none" stroke="${palette.accent}" stroke-width="6" opacity="0.72"/>
      `,
    },
  },
  {
    tokens: ['auto', 'ev ', 'vehicle', 'motor', 'tata motors', 'maruti', 'mahindra'],
    theme: {
      label: 'Auto Brief',
      badge: 'AUTO SECTOR',
      accent: '#1f56d6',
      motif: (palette) => `
        <rect x="810" y="290" width="180" height="46" rx="18" fill="rgba(15, 23, 42, 0.58)" stroke="${palette.accent}" stroke-width="2"/>
        <circle cx="850" cy="350" r="22" fill="none" stroke="${palette.accent2}" stroke-width="4"/>
        <circle cx="950" cy="350" r="22" fill="none" stroke="${palette.accent2}" stroke-width="4"/>
        <path d="M840 250 L960 250 L930 210 H870 Z" fill="${palette.accent}" opacity="0.34"/>
      `,
    },
  },
];

const inferResearchTheme = (title: string, source: string, label: string): ResearchVisualTheme => {
  const haystack = `${title} ${source} ${label}`.toLowerCase();
  for (const rule of RESEARCH_THEME_RULES) {
    if (rule.tokens.some((token) => haystack.includes(token))) {
      return rule.theme;
    }
  }
  return {
    label: 'Research Brief',
    badge: 'EDITORIAL',
    accent: '#0f7a5c',
    motif: (palette, rand) => `
      <rect x="780" y="150" width="240" height="170" rx="22" fill="rgba(15, 23, 42, 0.52)" stroke="${palette.accent2}" stroke-width="1.5"/>
      <polyline points="810,280 870,230 930,250 990,190" fill="none" stroke="${palette.accent}" stroke-width="6" opacity="0.68"/>
      ${Array.from({ length: 5 }, (_, idx) => {
        const x = 820 + idx * 34;
        const y = 330 + rand() * 40;
        return `<circle cx="${x}" cy="${y}" r="4" fill="${palette.warm}" opacity="0.42"/>`;
      }).join('')}
    `,
  };
};

const buildResearchCoverSvg = ({
  hash,
  title,
  source,
  label,
  rand,
}: {
  hash: number;
  title: string;
  source: string;
  label: string;
  rand: () => number;
}) => {
  const palette = RESEARCH_PALETTES[hash % RESEARCH_PALETTES.length];
  const theme = inferResearchTheme(title, source, label);
  const gradientId = `rg${hash.toString(16)}`;
  const gridId = `rg${hash.toString(16)}g`;
  const clipId = `rg${hash.toString(16)}c`;
  const eyebrow = compactUpper(label || theme.label, theme.label, 28);
  const sourceLabel = compactUpper(source, 'PROSPEKTLAB RESEARCH', 24);
  const titleLines = wrapTitle(title || source || theme.label);
  const motif = theme.motif(palette, rand);

  return `
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="675" viewBox="0 0 1200 675" role="img" aria-label="${escapeXml(title || eyebrow)}">
  <defs>
    <linearGradient id="${gradientId}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="${palette.bgA}"/>
      <stop offset="55%" stop-color="${palette.bgB}"/>
      <stop offset="100%" stop-color="#050a12"/>
    </linearGradient>
    <pattern id="${gridId}" width="72" height="72" patternUnits="userSpaceOnUse">
      <path d="M 72 0 L 0 0 0 72" fill="none" stroke="#eae3d6" stroke-width="1" opacity="0.08"/>
    </pattern>
    <clipPath id="${clipId}">
      <rect x="0" y="0" width="1200" height="675" rx="36"/>
    </clipPath>
  </defs>
  <g clip-path="url(#${clipId})">
    <rect width="1200" height="675" fill="url(#${gradientId})"/>
    <rect width="1200" height="675" fill="url(#${gridId})"/>
    <path d="M0 520 C180 430 320 560 500 470 C680 380 820 450 980 360 C1100 290 1160 310 1200 250 L1200 675 L0 675 Z" fill="${palette.panel}" opacity="0.36"/>
    <circle cx="180" cy="120" r="180" fill="${theme.accent}" opacity="0.07"/>
    <circle cx="1040" cy="560" r="220" fill="${palette.warm}" opacity="0.05"/>
    ${motif}
    <rect x="470" y="52" width="260" height="48" rx="18" fill="rgba(15, 23, 42, 0.58)" stroke="${theme.accent}" stroke-width="1.5" opacity="0.94"/>
    <text x="508" y="84" fill="#eae3d6" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="24" font-weight="800">PL</text>
    <text x="562" y="83" fill="${theme.accent}" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="15" font-weight="800" letter-spacing="2.4">RESEARCH</text>
    <text x="600" y="150" text-anchor="middle" fill="${theme.accent}" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="22" font-weight="800" letter-spacing="3.2">${escapeXml(eyebrow)}</text>
    <text x="600" y="194" text-anchor="middle" fill="#cbd5e1" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="20" font-weight="700" letter-spacing="2">${escapeXml(sourceLabel)}</text>
    <rect x="276" y="470" width="648" height="124" rx="28" fill="rgba(2, 6, 23, 0.62)" stroke="rgba(234, 227, 214, 0.16)"/>
    <text x="600" y="524" text-anchor="middle" fill="#f8fafc" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="39" font-weight="800">${escapeXml(titleLines[0] || sourceLabel)}</text>
    <text x="600" y="570" text-anchor="middle" fill="#cbd5e1" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="34" font-weight="720">${escapeXml(titleLines[1] || '')}</text>
    <rect x="494" y="606" width="212" height="42" rx="16" fill="rgba(15, 23, 42, 0.58)" stroke="${theme.accent}" stroke-width="1.5" opacity="0.9"/>
    <text x="600" y="633" text-anchor="middle" fill="${theme.accent}" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="15" font-weight="800" letter-spacing="2.8">${escapeXml(theme.badge)}</text>
  </g>
</svg>`.trim();
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

  if (kind === 'research') {
    const svg = buildResearchCoverSvg({
      hash,
      title: title || seed,
      source: source || symbol,
      label: label || KIND_LABELS.research,
      rand,
    });
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  }

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
    <text x="600" y="633" text-anchor="middle" fill="${palette.accent2}" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="15" font-weight="800" letter-spacing="2.8">LIVE SIGNAL</text>
  </g>
</svg>`.trim();

  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
};

import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { createServer, loadConfigFromFile, mergeConfig } from 'vite';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const appDir = path.resolve(__dirname, '..');
const exportDir = path.join(appDir, 'ui-exports');
const port = 4173;
const baseUrl = `http://127.0.0.1:${port}`;

const sharedUser = {
  email: 'demo@prospektlab.ai',
  name: 'Aarav Shah',
};

const mirrorPositions = [
  {
    symbol: 'RELIANCE',
    name: 'Reliance Industries',
    quantity: 24,
    market_value: 349920,
    cost_basis: 306000,
    avg_cost: 12750,
    last_price: 14580,
    sector: 'Energy',
    kind: 'equity',
    day_change_pct: 0.82,
  },
  {
    symbol: 'TCS',
    name: 'Tata Consultancy Services',
    quantity: 16,
    market_value: 63840,
    cost_basis: 58240,
    avg_cost: 3640,
    last_price: 3990,
    sector: 'Information Technology',
    kind: 'equity',
    day_change_pct: 0.44,
  },
  {
    symbol: 'INFY',
    name: 'Infosys',
    quantity: 28,
    market_value: 45080,
    cost_basis: 41580,
    avg_cost: 1485,
    last_price: 1610,
    sector: 'Information Technology',
    kind: 'equity',
    day_change_pct: -0.27,
  },
  {
    symbol: 'HDFCBANK',
    name: 'HDFC Bank',
    quantity: 22,
    market_value: 37620,
    cost_basis: 34980,
    avg_cost: 1590,
    last_price: 1710,
    sector: 'Financial Services',
    kind: 'equity',
    day_change_pct: 0.33,
  },
  {
    symbol: 'MOMF',
    name: 'Motilal Oswal Manufacturing Fund - Direct Growth',
    quantity: 520,
    market_value: 33800,
    cost_basis: 30160,
    avg_cost: 58,
    last_price: 65,
    sector: 'Thematic - Manufacturing',
    kind: 'mf',
    day_change_pct: 0.19,
  },
];

const quotes = {
  RELIANCE: {
    company_name: 'Reliance Industries',
    price: 14580,
    change_pct: 0.82,
    sector: 'Energy',
  },
  TCS: {
    company_name: 'Tata Consultancy Services',
    price: 3990,
    change_pct: 0.44,
    sector: 'Information Technology',
  },
  INFY: {
    company_name: 'Infosys',
    price: 1610,
    change_pct: -0.27,
    sector: 'Information Technology',
  },
  HDFCBANK: {
    company_name: 'HDFC Bank',
    price: 1710,
    change_pct: 0.33,
    sector: 'Financial Services',
  },
  ASIANPAINT: {
    company_name: 'Asian Paints',
    price: 3055,
    change_pct: 1.18,
    sector: 'Consumer',
  },
  ZOMATO: {
    company_name: 'Zomato',
    price: 212,
    change_pct: 2.64,
    sector: 'Internet',
  },
  ITC: {
    company_name: 'ITC',
    price: 472,
    change_pct: -0.52,
    sector: 'Consumer',
  },
  MOMF: {
    company_name: 'Motilal Oswal Manufacturing Fund - Direct Growth',
    price: 65,
    change_pct: 0.19,
    sector: 'Thematic - Manufacturing',
  },
};

const analytics = {
  total_cost_basis: 460960,
  total_market_value: 530260,
  unrealized_pnl: 69300,
  positions: mirrorPositions,
  sector_breakdown: {
    Energy: 0.66,
    'Information Technology': 0.2,
    'Financial Services': 0.08,
    'Thematic - Manufacturing': 0.06,
  },
  kind_breakdown: {
    equity: 0.94,
    mf: 0.06,
  },
  history: {
    portfolio: makeHistory(100, 132, 252, 1.2),
    benchmark: makeHistory(100, 121, 252, 0.8),
  },
  risk: {
    beta_vs_nifty: 1.08,
    hhi: 0.241,
    annualized_volatility_pct: 18.4,
  },
};

const indices = {
  india: [
    makeIndex('NIFTY 50', '24,812.35', '+186.40', 0.76, 24450),
    makeIndex('SENSEX', '81,324.80', '+522.10', 0.65, 81020),
    makeIndex('BANK NIFTY', '54,105.25', '+398.50', 0.74, 54010),
    makeIndex('NIFTY IT', '38,440.10', '-72.40', -0.19, 38500),
  ],
  us: [
    makeIndex('S&P 500', '5,418.22', '+18.70', 0.35, 5400),
    makeIndex('NASDAQ', '17,612.55', '+44.10', 0.25, 17580),
  ],
  currencies: [
    makeIndex('USD/INR', '83.12', '-0.08', -0.1, 83),
    makeIndex('EUR/INR', '90.56', '+0.12', 0.13, 90.3),
  ],
  crypto: [
    makeIndex('BTC', '68,440', '+1,120', 1.66, 67200),
  ],
  futures: [
    makeIndex('SGX NIFTY', '24,835.10', '+102.80', 0.42, 24710),
  ],
};

const marketNews = [
  {
    id: 'm-1',
    source: 'Business Desk',
    published: '12 min ago',
    title: 'Reliance and large-cap financials lead the latest push higher on the NSE.',
    description: 'Index breadth stayed positive while traders rotated back into energy and quality financials.',
  },
  {
    id: 'm-2',
    source: 'Market Wire',
    published: '28 min ago',
    title: 'IT majors trade mixed ahead of the next earnings cycle.',
    description: 'Investors are looking for commentary on deal wins, margin durability and discretionary demand.',
  },
  {
    id: 'm-3',
    source: 'Street Feed',
    published: '44 min ago',
    title: 'Consumer names soften as traders reassess near-term volume recovery.',
    description: 'Select FMCG and paints names gave back early gains even as defensives remained supported.',
  },
];

const portfolioNews = {
  items: [
    {
      id: 'p-1',
      source: 'Portfolio Brief',
      published: '8 min ago',
      title: 'HDFC Bank margins remain a key watch item for private-bank holders.',
      description: 'Street focus stays on deposit mix and loan growth discipline into the next result window.',
      related_holding: { symbol: 'HDFCBANK' },
    },
    {
      id: 'p-2',
      source: 'Portfolio Brief',
      published: '19 min ago',
      title: 'Zomato momentum names are seeing renewed speculative interest.',
      description: 'Fast-moving internet stocks are back on radar after a stronger delivery trend update.',
      related_holding: { symbol: 'ZOMATO' },
    },
  ],
};

const tokenUsage = {
  usage: 1820000,
  limit: 5000000,
};

const mfAnalytics = {
  total_mf_value: 33800,
  aum_weighted_ter_pct: 0.62,
  scheme_count: 1,
  category_breakdown: {
    'Thematic - Manufacturing': 1,
  },
  amc_concentration: {
    'Motilal Oswal': 1,
  },
};

const todayQueue = {
  items: [
    {
      title: 'Review Reliance weighting after recent move',
      reason: 'Largest portfolio position now drives more than half of daily P&L swings.',
      severity: 'high',
    },
    {
      title: 'Track TCS and Infosys for earnings commentary',
      reason: 'IT exposure is meaningful enough to move the next monthly return profile.',
      severity: 'medium',
    },
    {
      title: 'Confirm whether Zomato stays watchlist-only',
      reason: 'Momentum is improving, but exposure remains uncommitted.',
      severity: 'watch',
    },
  ],
};

const portfolioBrief = {
  brief: 'Your book is tilted toward quality Indian large caps, with concentration risk centered on Reliance and IT services.',
};

const captures = [
  {
    id: 'landing',
    route: '#/',
    mode: 'public',
    viewport: { width: 1440, height: 1400 },
    fullPage: true,
  },
  {
    id: 'features',
    route: '#/features',
    mode: 'public',
    viewport: { width: 1440, height: 1400 },
    fullPage: true,
  },
  {
    id: 'pricing',
    route: '#/pricing',
    mode: 'public',
    viewport: { width: 1440, height: 1400 },
    fullPage: true,
  },
  {
    id: 'testimonials',
    route: '#/testimonials',
    mode: 'public',
    viewport: { width: 1440, height: 1400 },
    fullPage: true,
  },
  {
    id: 'contact',
    route: '#/contact',
    mode: 'public',
    viewport: { width: 1440, height: 1200 },
    fullPage: true,
  },
  {
    id: 'login',
    route: '#/login',
    mode: 'public',
    viewport: { width: 1440, height: 1200 },
    fullPage: false,
  },
  {
    id: 'signup',
    route: '#/signup',
    mode: 'public',
    viewport: { width: 1440, height: 1380 },
    fullPage: false,
  },
  {
    id: 'onboarding',
    route: '#/onboarding',
    mode: 'auth-pre',
    viewport: { width: 1440, height: 1500 },
    fullPage: true,
  },
  {
    id: 'dashboard',
    route: '#/dashboard',
    mode: 'auth-post',
    viewport: { width: 1600, height: 1200 },
    fullPage: false,
  },
];

async function main() {
  await fs.mkdir(exportDir, { recursive: true });

  const server = await startServer();
  const browser = await chromium.launch({ headless: true });

  try {
    const manifest = [];

    for (const capture of captures) {
      const context = await browser.newContext({
        viewport: capture.viewport,
        colorScheme: 'dark',
        deviceScaleFactor: 1,
      });
      const page = await context.newPage();

      await installApiMocks(context, capture.mode);
      await seedClientState(page, capture.mode);

      const url = `${baseUrl}/${capture.route}`;
      await page.goto(url, { waitUntil: 'domcontentloaded' });
      await settlePage(page, capture.id);

      const pngPath = path.join(exportDir, `${capture.id}.png`);
      const svgPath = path.join(exportDir, `${capture.id}.svg`);

      await page.screenshot({
        path: pngPath,
        fullPage: capture.fullPage,
      });

      await writeFlatSvgFromPng(pngPath, svgPath, capture.viewport);

      manifest.push({
        id: capture.id,
        route: capture.route,
        mode: capture.mode,
        png: `./${capture.id}.png`,
        svg: `./${capture.id}.svg`,
      });

      await context.close();
      console.log(`exported ${capture.id}`);
    }

    await fs.writeFile(
      path.join(exportDir, 'manifest.json'),
      JSON.stringify(manifest, null, 2),
      'utf8',
    );

    const readme = [
      '# UI Exports',
      '',
      'These files are flat screen artboards exported from the React UI.',
      'Each screen has:',
      '- a PNG capture for easy review',
      '- an SVG wrapper that embeds the PNG for import into Figma or After Effects',
      '',
      'Important:',
      '- The SVG files are not layered vectors.',
      '- They import as flat artboards, which is useful for tracing, storyboard work, and layout recreation.',
      '- If you need fully editable Figma screens, the next step is rebuilding the layouts as native Figma frames/components.',
      '',
      'Generated files:',
      ...captures.map((capture) => `- ${capture.id}: \`${capture.id}.png\`, \`${capture.id}.svg\``),
      '',
    ].join('\n');

    await fs.writeFile(path.join(exportDir, 'README.md'), readme, 'utf8');
  } finally {
    await browser.close();
    await server.close();
  }
}

async function startServer() {
  const configPath = path.join(appDir, 'vite.config.ts');
  const loaded = await loadConfigFromFile(
    { command: 'serve', mode: 'development' },
    configPath,
  );

  const merged = mergeConfig(loaded?.config || {}, {
    configFile: false,
    root: appDir,
    server: {
      host: '127.0.0.1',
      port,
      strictPort: true,
    },
  });

  const server = await createServer(merged);
  await server.listen();
  return server;
}

async function installApiMocks(context, mode) {
  await context.route('**/*', async (route) => {
    const requestUrl = route.request().url();
    const url = new URL(requestUrl);
    const { pathname } = url;

    if (pathname.startsWith('/auth/') || pathname.startsWith('/portfolio/') || pathname.startsWith('/market/') || pathname.startsWith('/user/') || pathname.startsWith('/api/')) {
      const body = resolveMockResponse(pathname, url.searchParams, mode);
      if (body === null) {
        await route.fulfill({
          status: 401,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Unauthorized' }),
        });
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
      return;
    }

    if (url.hostname === 'accounts.google.com') {
      await route.fulfill({ status: 204, body: '' });
      return;
    }

    await route.continue();
  });
}

function resolveMockResponse(pathname, searchParams, mode) {
  if (pathname === '/auth/me') {
    return mode === 'public' ? null : sharedUser;
  }

  if (pathname === '/portfolio/mirror') {
    return mode === 'auth-post'
      ? { count: mirrorPositions.length, positions: mirrorPositions }
      : { count: 0, positions: [] };
  }

  if (pathname === '/portfolio/analytics') {
    return analytics;
  }

  if (pathname === '/portfolio/news') {
    return portfolioNews;
  }

  if (pathname === '/portfolio/mf-analytics') {
    return mfAnalytics;
  }

  if (pathname === '/portfolio/today') {
    return todayQueue;
  }

  if (pathname === '/portfolio/brief') {
    return portfolioBrief;
  }

  if (pathname === '/user/token-usage') {
    return tokenUsage;
  }

  if (pathname === '/market/quotes') {
    const requested = (searchParams.get('symbols') || '')
      .split(',')
      .map((item) => item.trim().toUpperCase())
      .filter(Boolean);

    const response = {};
    for (const symbol of requested) {
      if (quotes[symbol]) {
        response[symbol] = quotes[symbol];
      }
    }
    return response;
  }

  if (pathname === '/market/indices') {
    return indices;
  }

  if (pathname === '/market/news') {
    return marketNews;
  }

  if (pathname === '/api/portfolio/upload-cas' || pathname === '/api/portfolio/upload-screenshot') {
    return {
      code: 'MIRROR_SYNCHRONIZED',
      positions: mirrorPositions,
      sync_status: 'MIRROR_SYNCHRONIZED',
    };
  }

  if (pathname === '/api/portfolio/confirm-extraction') {
    return { positions: mirrorPositions };
  }

  return {};
}

async function seedClientState(page, mode) {
  await page.addInitScript(([authMode, user]) => {
    localStorage.clear();
    sessionStorage.clear();

    localStorage.setItem('prospektlab_username', 'Aarav');
    localStorage.setItem('prospektlab_style', 'Balanced');
    localStorage.setItem('pl_visits', '3');
    localStorage.setItem('prospektlab_watchlist', JSON.stringify(['RELIANCE', 'TCS', 'INFY', 'ASIANPAINT', 'ZOMATO']));
    localStorage.setItem('prospektlab_sidebar_width', '260');
    localStorage.setItem('prospektlab_chat_width', '380');

    const conversations = [
      { id: 'conv-demo-1', title: 'Portfolio concentration audit', date: 'Today' },
      { id: 'conv-demo-2', title: 'TCS vs Infosys review', date: 'Yesterday' },
    ];
    localStorage.setItem('prospektlab_conversations', JSON.stringify(conversations));
    localStorage.setItem(
      'prospektlab_messages_conv-demo-1',
      JSON.stringify([
        { sender: 'ai', text: "Arthik here. I don't do hope - I do numbers. Ask me anything about your book, a ticker, or the tape." },
        { sender: 'user', text: 'Where is my portfolio most concentrated?', depth: 'standard' },
        { sender: 'ai', text: 'Your concentration risk is centered on Reliance and large-cap IT. Energy plus IT together make up the majority of mark-to-market risk.' },
      ]),
    );

    if (authMode !== 'public') {
      localStorage.setItem(`prospektlab_onboarded:${user.email.toLowerCase()}`, authMode === 'auth-post' ? 'true' : 'false');
    }
  }, [mode, sharedUser]);
}

async function settlePage(page, id) {
  await page.evaluate(async () => {
    if (document.fonts?.ready) {
      await document.fonts.ready;
    }
  });

  await page.waitForTimeout(1200);

  if (id === 'dashboard') {
    await page.locator('text=Portfolio Value').first().waitFor({ timeout: 15000 });
  }

  if (id === 'onboarding') {
    await page.locator('text=Your Institutional Edge Starts Here').first().waitFor({ timeout: 15000 });
  }

  if (id === 'login' || id === 'signup') {
    await page.locator('text=ProspektLab').first().waitFor({ timeout: 15000 });
  }
}

async function writeFlatSvgFromPng(pngPath, svgPath, viewport) {
  const pngBytes = await fs.readFile(pngPath);
  const pngBase64 = pngBytes.toString('base64');
  const dimensions = await getPngDimensions(pngBytes);
  const width = dimensions.width || viewport.width;
  const height = dimensions.height || viewport.height;

  const svg = [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`,
    `  <image width="${width}" height="${height}" href="data:image/png;base64,${pngBase64}" />`,
    '</svg>',
    '',
  ].join('\n');

  await fs.writeFile(svgPath, svg, 'utf8');
}

async function getPngDimensions(pngBytes) {
  if (pngBytes.length < 24) {
    return { width: 0, height: 0 };
  }

  return {
    width: pngBytes.readUInt32BE(16),
    height: pngBytes.readUInt32BE(20),
  };
}

function makeIndex(symbol, value, change, changePct, anchor) {
  const sparkData = [0.92, 0.96, 1.01, 0.99, 1.04, 1.08, 1.06, 1.11].map((step, index) => {
    const wobble = (index % 2 === 0 ? 1 : -1) * 0.6;
    return anchor * step + wobble;
  });

  return {
    symbol,
    value,
    change,
    changePct,
    sparkData,
  };
}

function makeHistory(start, end, count, wobble) {
  const dates = [];
  const prices = [];
  const startDate = new Date('2025-06-03T00:00:00Z');

  for (let index = 0; index < count; index += 1) {
    const date = new Date(startDate);
    date.setUTCDate(startDate.getUTCDate() + index);
    dates.push(date.toISOString().slice(0, 10));

    const progress = index / (count - 1);
    const base = start + (end - start) * progress;
    const swing = Math.sin(index / 9) * wobble + Math.cos(index / 17) * (wobble / 2);
    prices.push(Number((base + swing).toFixed(2)));
  }

  return { dates, prices };
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

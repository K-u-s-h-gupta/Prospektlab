import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const appDir = path.resolve(__dirname, '..');
const cssPath = path.join(appDir, 'src', 'index.css');
const exportsDir = path.join(appDir, 'ui-exports');
const handoffDir = path.join(appDir, 'figma-handoff');

const components = [
  {
    name: 'Brand / Logo',
    figma_name: 'Brand/ProspektLab Logo',
    category: 'Brand',
    source_files: ['src/components/layout/Logo.tsx', 'public/prospektlab-logo.svg'],
    notes: 'Primary brand mark used in landing, auth, onboarding, sidebar, and mobile header.',
    anatomy: ['glyph', 'wordmark'],
  },
  {
    name: 'Button / Primary CTA',
    figma_name: 'Button/Primary',
    category: 'Actions',
    source_files: ['src/index.css', 'src/pages/LandingPage.tsx', 'src/pages/Login.tsx'],
    notes: 'Gradient brand action button with dark text and soft glow.',
    anatomy: ['container', 'label', 'optional trailing icon'],
  },
  {
    name: 'Button / Secondary',
    figma_name: 'Button/Secondary',
    category: 'Actions',
    source_files: ['src/index.css'],
    notes: 'Glass-style secondary button used across navigation, panels, and utilities.',
    anatomy: ['container', 'label', 'optional icon'],
  },
  {
    name: 'Badge / Status Pill',
    figma_name: 'Badge/Status',
    category: 'Data Display',
    source_files: ['src/index.css', 'src/pages/LandingPage.tsx', 'src/pages/Dashboard.tsx'],
    notes: 'Small uppercase pill for state, live flags, owned tags, premium tags, and sublabels.',
    anatomy: ['pill background', 'text', 'optional dot/icon'],
  },
  {
    name: 'Surface / Glass Card',
    figma_name: 'Surface/Glass Card',
    category: 'Foundation',
    source_files: ['src/index.css'],
    notes: 'Core elevated panel treatment reused across auth, onboarding, dashboard, and landing.',
    anatomy: ['panel fill', 'stroke', 'inner highlight', 'shadow'],
  },
  {
    name: 'Sidebar / App Navigation',
    figma_name: 'Navigation/App Sidebar',
    category: 'Navigation',
    source_files: ['src/components/layout/Sidebar.tsx', 'src/components/layout/AppShell.tsx'],
    notes: 'Resizable desktop sidebar with history, value summary, profile block, and footer actions.',
    anatomy: ['brand header', 'new chat button', 'nav item', 'history item', 'portfolio card', 'profile row'],
  },
  {
    name: 'Card / Index Ticker',
    figma_name: 'Dashboard/Index Ticker Card',
    category: 'Dashboard',
    source_files: ['src/components/dashboard/IndexTickerCard.tsx'],
    notes: 'Compact market card with symbol, value, change, and sparkline.',
    anatomy: ['header row', 'value', 'delta', 'sparkline'],
  },
  {
    name: 'Panel / Comparative Chart',
    figma_name: 'Dashboard/Comparative Chart Panel',
    category: 'Dashboard',
    source_files: ['src/pages/Dashboard.tsx', 'src/components/charts/InteractiveChart.tsx'],
    notes: 'Main portfolio-vs-benchmark chart panel with range chips and benchmark selector.',
    anatomy: ['panel header', 'chart canvas', 'legend', 'footer action'],
  },
  {
    name: 'Tile / Stat Metric',
    figma_name: 'Dashboard/Stat Tile',
    category: 'Dashboard',
    source_files: ['src/pages/Dashboard.tsx'],
    notes: 'Small highlight tile for best/worst, ratio, beta, and VaR.',
    anatomy: ['eyebrow', 'value', 'supporting caption'],
  },
  {
    name: 'List / News Card',
    figma_name: 'Dashboard/News Card',
    category: 'Dashboard',
    source_files: ['src/pages/Dashboard.tsx'],
    notes: 'Headline card with source, age, sentiment, and optional ticker chips.',
    anatomy: ['meta row', 'headline', 'ticker pills'],
  },
  {
    name: 'List / Earnings Row',
    figma_name: 'Dashboard/Earnings Row',
    category: 'Dashboard',
    source_files: ['src/pages/Dashboard.tsx'],
    notes: 'Three-part row with calendar chip, core info, and impact label.',
    anatomy: ['calendar sheet', 'issuer info', 'countdown/date', 'impact block'],
  },
  {
    name: 'Rail / Chat Workspace',
    figma_name: 'Chat/Right Rail',
    category: 'Chat',
    source_files: ['src/pages/Dashboard.tsx', 'src/components/chat/ChatInput.tsx', 'src/components/chat/MessageBubble.tsx'],
    notes: 'Persistent assistant rail with history thread, bubbles, input dock, and live state.',
    anatomy: ['rail header', 'message bubble', 'thinking panel', 'input composer', 'footer meta'],
  },
  {
    name: 'Form / Auth Input',
    figma_name: 'Forms/Auth Input',
    category: 'Forms',
    source_files: ['src/pages/Login.tsx', 'src/index.css'],
    notes: 'Icon-leading input shell used across sign-in, sign-up, reset, and mobile completion flows.',
    anatomy: ['label', 'input shell', 'leading icon', 'field', 'trailing action'],
  },
  {
    name: 'Form / Auth Tabs',
    figma_name: 'Forms/Auth Tabs',
    category: 'Forms',
    source_files: ['src/pages/Login.tsx'],
    notes: 'Two-state tab switch for sign-in/create-account.',
    anatomy: ['tab container', 'default tab', 'active tab'],
  },
  {
    name: 'Form / Password Strength Meter',
    figma_name: 'Forms/Password Strength',
    category: 'Forms',
    source_files: ['src/pages/Login.tsx'],
    notes: 'Five-step segmented meter with semantic color labels.',
    anatomy: ['segment row', 'strength label'],
  },
  {
    name: 'Onboarding / Style Card',
    figma_name: 'Onboarding/Style Choice Card',
    category: 'Onboarding',
    source_files: ['src/pages/Onboarding.tsx'],
    notes: 'Selectable investing-style choice card with icon, title, and explanatory copy.',
    anatomy: ['icon', 'title', 'description', 'selection state'],
  },
  {
    name: 'Onboarding / Upload Dropzone',
    figma_name: 'Onboarding/Upload Dropzone',
    category: 'Onboarding',
    source_files: ['src/pages/Onboarding.tsx'],
    notes: 'Statement upload area for PDF, CSV, Excel, or screenshot import.',
    anatomy: ['dropzone shell', 'upload icon', 'helper copy', 'broker chips'],
  },
];

const screenSpecs = [
  {
    id: 'landing',
    figma_frame: 'Screen/Landing Desktop',
    route: '#/',
    source_files: ['src/pages/LandingPage.tsx'],
    composition: ['Brand / Logo', 'Button / Primary CTA', 'Badge / Status Pill', 'Surface / Glass Card'],
    notes: 'Marketing homepage with hero split, social proof, feature storytelling, reviews, FAQ, and closing CTA.',
  },
  {
    id: 'features',
    figma_frame: 'Screen/Features Desktop',
    route: '#/features',
    source_files: ['src/pages/Features.tsx'],
    composition: ['Brand / Logo', 'Button / Primary CTA', 'Surface / Glass Card'],
    notes: 'Feature breakdown page aligned to the same marketing system.',
  },
  {
    id: 'pricing',
    figma_frame: 'Screen/Pricing Desktop',
    route: '#/pricing',
    source_files: ['src/pages/Pricing.tsx'],
    composition: ['Brand / Logo', 'Button / Primary CTA', 'Badge / Status Pill', 'Surface / Glass Card'],
    notes: 'Pricing and plan comparison page.',
  },
  {
    id: 'testimonials',
    figma_frame: 'Screen/Testimonials Desktop',
    route: '#/testimonials',
    source_files: ['src/pages/Testimonials.tsx'],
    composition: ['Brand / Logo', 'Surface / Glass Card', 'Badge / Status Pill'],
    notes: 'Long-form social proof page with featured reviews and quotes.',
  },
  {
    id: 'contact',
    figma_frame: 'Screen/Contact Desktop',
    route: '#/contact',
    source_files: ['src/pages/ContactUs.tsx'],
    composition: ['Brand / Logo', 'Form / Auth Input', 'Button / Primary CTA', 'Surface / Glass Card'],
    notes: 'Contact form and support-oriented layout.',
  },
  {
    id: 'login',
    figma_frame: 'Screen/Auth Sign In Desktop',
    route: '#/login',
    source_files: ['src/pages/Login.tsx'],
    composition: ['Brand / Logo', 'Form / Auth Tabs', 'Form / Auth Input', 'Form / Password Strength Meter', 'Button / Primary CTA', 'Surface / Glass Card'],
    notes: 'Primary sign-in screen.',
  },
  {
    id: 'signup',
    figma_frame: 'Screen/Auth Sign Up Desktop',
    route: '#/signup',
    source_files: ['src/pages/Login.tsx'],
    composition: ['Brand / Logo', 'Form / Auth Tabs', 'Form / Auth Input', 'Form / Password Strength Meter', 'Button / Primary CTA', 'Surface / Glass Card'],
    notes: 'Create-account state of the same auth shell.',
  },
  {
    id: 'onboarding',
    figma_frame: 'Screen/Onboarding Desktop',
    route: '#/onboarding',
    source_files: ['src/pages/Onboarding.tsx'],
    composition: ['Brand / Logo', 'Onboarding / Style Card', 'Onboarding / Upload Dropzone', 'Badge / Status Pill', 'Button / Primary CTA', 'Surface / Glass Card'],
    notes: 'Multi-step onboarding flow for investor profile, upload, watchlist, and launch.',
  },
  {
    id: 'dashboard',
    figma_frame: 'Screen/Dashboard Desktop',
    route: '#/dashboard',
    source_files: ['src/pages/Dashboard.tsx', 'src/components/layout/AppShell.tsx', 'src/components/layout/Sidebar.tsx'],
    composition: ['Sidebar / App Navigation', 'Card / Index Ticker', 'Panel / Comparative Chart', 'Tile / Stat Metric', 'List / News Card', 'List / Earnings Row', 'Rail / Chat Workspace'],
    notes: 'Main product cockpit with left navigation, data workspace, and right assistant rail.',
  },
];

async function main() {
  const css = await fs.readFile(cssPath, 'utf8');
  const manifest = JSON.parse(await fs.readFile(path.join(exportsDir, 'manifest.json'), 'utf8'));
  const tokens = parseTokens(css);
  const artboards = await enrichArtboards(manifest);

  await fs.mkdir(handoffDir, { recursive: true });

  await fs.writeFile(path.join(handoffDir, 'tokens.json'), JSON.stringify(tokens, null, 2), 'utf8');
  await fs.writeFile(path.join(handoffDir, 'components.json'), JSON.stringify(components, null, 2), 'utf8');
  await fs.writeFile(path.join(handoffDir, 'screens.json'), JSON.stringify(buildScreens(screenSpecs, artboards), null, 2), 'utf8');
  await fs.writeFile(path.join(handoffDir, 'artboards.json'), JSON.stringify(artboards, null, 2), 'utf8');
  await fs.writeFile(path.join(handoffDir, 'README.md'), buildReadme(tokens, artboards), 'utf8');
}

function parseTokens(css) {
  const rootMatch = css.match(/:root\s*\{([\s\S]*?)\}/);
  const rootBody = rootMatch ? rootMatch[1] : '';
  const variableMatches = Array.from(rootBody.matchAll(/--([A-Za-z0-9-]+)\s*:\s*([^;]+);/g));

  const variables = Object.fromEntries(
    variableMatches.map((match) => [match[1], match[2].trim()]),
  );

  return {
    colors: pickByPrefix(variables, ['bg-', 'accent-', 'profit', 'loss', 'neutral', 'text-']),
    typography: pickByPrefix(variables, ['font-']),
    radii: pickByPrefix(variables, ['radius-']),
    effects: pickByPrefix(variables, ['gradient-', 'edge-glow', 'blue-aura']),
    motion: pickByPrefix(variables, ['transition']),
  };
}

function pickByPrefix(source, prefixes) {
  return Object.fromEntries(
    Object.entries(source).filter(([key]) => prefixes.some((prefix) => key.startsWith(prefix))),
  );
}

async function enrichArtboards(manifest) {
  const enriched = [];

  for (const item of manifest) {
    const pngPath = path.join(exportsDir, `${item.id}.png`);
    const pngBytes = await fs.readFile(pngPath);
    enriched.push({
      ...item,
      width: pngBytes.readUInt32BE(16),
      height: pngBytes.readUInt32BE(20),
      png_path: toWorkspacePath(pngPath),
      svg_path: toWorkspacePath(path.join(exportsDir, `${item.id}.svg`)),
    });
  }

  return enriched;
}

function buildScreens(specs, artboards) {
  return specs.map((screen) => {
    const artboard = artboards.find((item) => item.id === screen.id);
    return {
      ...screen,
      artboard: artboard
        ? {
            width: artboard.width,
            height: artboard.height,
            png_path: artboard.png_path,
            svg_path: artboard.svg_path,
          }
        : null,
    };
  });
}

function buildReadme(tokens, artboards) {
  const colorLines = Object.entries(tokens.colors).map(([name, value]) => `- \`${name}\`: \`${value}\``);
  const typeLines = Object.entries(tokens.typography).map(([name, value]) => `- \`${name}\`: \`${value}\``);

  return [
    '# Figma Handoff',
    '',
    'This package turns the React UI into a structured rebuild spec for Figma.',
    '',
    'What is included:',
    '- `tokens.json`: colors, typography, radii, effects, and motion tokens extracted from `src/index.css`.',
    '- `components.json`: reusable component inventory mapped back to source files.',
    '- `screens.json`: screen-by-screen composition map tied to exported artboards.',
    '- `artboards.json`: exported screen dimensions and file paths.',
    '',
    'Recommended rebuild flow in Figma:',
    '1. Create color, effect, and radius variables from `tokens.json`.',
    '2. Create base components from `components.json` using the matching source files.',
    '3. Place each artboard from `ui-exports` as a temporary underlay.',
    '4. Rebuild each frame from `screens.json` using Auto Layout and component instances.',
    '5. Remove the underlay once the rebuilt screen matches the artboard.',
    '',
    'Core tokens:',
    ...colorLines,
    '',
    'Typography tokens:',
    ...typeLines,
    '',
    'Available artboards:',
    ...artboards.map((artboard) => `- \`${artboard.id}\`: ${artboard.width}x${artboard.height}`),
    '',
    'Important limitation:',
    '- This is a Figma-oriented rebuild package, not a native `.fig` file generated by the Figma API.',
    '- A real cloud Figma file still requires access to a Figma workspace or automation inside an authenticated Figma session.',
    '',
  ].join('\n');
}

function toWorkspacePath(targetPath) {
  return targetPath.replace(/\\/g, '/');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

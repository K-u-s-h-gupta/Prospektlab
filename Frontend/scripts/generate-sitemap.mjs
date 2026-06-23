import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const BASE_URL = 'https://prospektlab.com';
const PUBLIC_DIR = path.resolve(__dirname, '..', 'public');
const INSIGHTS_DIR = path.join(PUBLIC_DIR, 'insights');
const OUTPUT_FILE = path.join(PUBLIC_DIR, 'sitemap.xml');

function formatDate(date) {
  return date.toISOString().split('T')[0];
}

function getLastmod(dirPath) {
  try {
    const indexPath = path.join(dirPath, 'index.html');
    const stats = fs.statSync(indexPath);
    return formatDate(stats.mtime);
  } catch {
    return formatDate(new Date());
  }
}

const staticRoutes = [
  { loc: '/', priority: '1.0', changefreq: 'weekly' },
  { loc: '/get-started', priority: '0.8', changefreq: 'weekly' },
  { loc: '/dashboard/overview', priority: '0.9', changefreq: 'daily' },
  { loc: '/dashboard/portfolio', priority: '0.8', changefreq: 'daily' },
  { loc: '/dashboard/watchlist', priority: '0.8', changefreq: 'daily' },
  { loc: '/dashboard/screener', priority: '0.8', changefreq: 'daily' },
  { loc: '/dashboard/earnings', priority: '0.7', changefreq: 'weekly' },
  { loc: '/dashboard/governance', priority: '0.7', changefreq: 'weekly' },
  { loc: '/insights-studio', priority: '0.8', changefreq: 'weekly' },
  { loc: '/insights/research/', priority: '0.9', changefreq: 'daily' },
];

function generateSitemap() {
  const urls = [];
  const seen = new Set();

  staticRoutes.forEach(route => {
    const loc = `${BASE_URL}${route.loc}`;
    seen.add(loc);
    urls.push({
      loc,
      lastmod: formatDate(new Date()),
      changefreq: route.changefreq,
      priority: route.priority,
    });
  });

  if (fs.existsSync(INSIGHTS_DIR)) {
    const entries = fs.readdirSync(INSIGHTS_DIR, { withFileTypes: true });
    entries
      .filter(entry => entry.isDirectory())
      .forEach(entry => {
        const slug = entry.name;
        const dirPath = path.join(INSIGHTS_DIR, slug);
        const indexPath = path.join(dirPath, 'index.html');
        if (fs.existsSync(indexPath)) {
          const loc = `${BASE_URL}/insights/${slug}/`;
          if (seen.has(loc)) return;
          seen.add(loc);
          urls.push({
            loc,
            lastmod: getLastmod(dirPath),
            changefreq: 'monthly',
            priority: '0.8',
          });
        }
      });
  }

  let xml = `<?xml version="1.0" encoding="UTF-8"?>\n`;
  xml += `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n`;

  urls.forEach(u => {
    xml += `  <url>\n`;
    xml += `    <loc>${u.loc}</loc>\n`;
    xml += `    <lastmod>${u.lastmod}</lastmod>\n`;
    xml += `    <changefreq>${u.changefreq}</changefreq>\n`;
    xml += `    <priority>${u.priority}</priority>\n`;
    xml += `  </url>\n`;
  });

  xml += `</urlset>\n`;

  fs.writeFileSync(OUTPUT_FILE, xml, 'utf8');
  console.log(`✅ Sitemap generated with ${urls.length} URLs at ${OUTPUT_FILE}`);
}

generateSitemap();

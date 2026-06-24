const fs = require('node:fs');
const path = require('node:path');
const root = process.cwd();

function readState(file) {
  const fullPath = path.join(root, file);
  const original = fs.readFileSync(fullPath, 'utf8');
  const newline = original.includes('\r\n') ? '\r\n' : '\n';
  return { fullPath, newline, normalized: original.replace(/\r\n/g, '\n') };
}

function writeState(file, content, newline) {
  const fullPath = path.join(root, file);
  fs.writeFileSync(fullPath, content.replace(/\n/g, newline), 'utf8');
}

function replaceOnce(file, before, after) {
  const state = readState(file);
  if (!state.normalized.includes(before)) {
    throw new Error(`Expected snippet not found in ${file}: ${before.slice(0, 80)}`);
  }
  writeState(file, state.normalized.replace(before, after), state.newline);
}

replaceOnce(
  'Frontend/src/main.tsx',
  `initializeTelemetry()\n`,
  `try {\n  initializeTelemetry()\n} catch (error) {\n  console.error('Telemetry initialization failed.', error)\n}\n`
);

replaceOnce(
  'Frontend/src/App.tsx',
  `import { trackPageView } from './telemetry';`,
  `import { trackException, trackPageView } from './telemetry';`
);
replaceOnce(
  'Frontend/src/App.tsx',
  `  return null;\n};\n\nexport const AppContent: React.FC = () => {`,
  `  return null;\n};\n\ntype AppErrorBoundaryProps = {\n  children: React.ReactNode;\n};\n\ntype AppErrorBoundaryState = {\n  hasError: boolean;\n};\n\nclass AppErrorBoundary extends React.Component<AppErrorBoundaryProps, AppErrorBoundaryState> {\n  state: AppErrorBoundaryState = {\n    hasError: false,\n  };\n\n  static getDerivedStateFromError(): AppErrorBoundaryState {\n    return { hasError: true };\n  }\n\n  componentDidCatch(error: Error, info: React.ErrorInfo) {\n    trackException(error, {\n      source: 'app_error_boundary',\n      component_stack: info.componentStack || '',\n    });\n  }\n\n  render() {\n    if (this.state.hasError) {\n      return (\n        <div\n          style={{\n            minHeight: '100vh',\n            display: 'flex',\n            alignItems: 'center',\n            justifyContent: 'center',\n            padding: '24px',\n            background: '#03060d',\n            color: '#f8fbff',\n            fontFamily: \"'Inter', system-ui, sans-serif\",\n          }}\n        >\n          <div\n            style={{\n              width: 'min(520px, 100%)',\n              padding: '24px',\n              borderRadius: '18px',\n              border: '1px solid rgba(148, 163, 184, 0.18)',\n              background: 'rgba(15, 23, 42, 0.85)',\n              boxShadow: '0 24px 80px rgba(0, 0, 0, 0.35)',\n            }}\n          >\n            <div\n              style={{\n                fontSize: '12px',\n                fontWeight: 700,\n                letterSpacing: '0.08em',\n                textTransform: 'uppercase',\n                color: '#60a5fa',\n                marginBottom: '12px',\n              }}\n            >\n              ProspektLab\n            </div>\n            <h1 style={{ margin: 0, fontSize: '24px', lineHeight: 1.2 }}>\n              We hit a loading issue while opening the app.\n            </h1>\n            <p style={{ margin: '12px 0 20px', color: '#a8b4c8', lineHeight: 1.6 }}>\n              Refresh once to retry. If the problem continues, use the button below to reopen the dashboard cleanly.\n            </p>\n            <button\n              type=\"button\"\n              onClick={() => window.location.assign('/dashboard/overview')}\n              style={{\n                border: 'none',\n                borderRadius: '12px',\n                padding: '12px 18px',\n                background: 'linear-gradient(135deg, #eaf3ff 0%, #60a5fa 46%, #1d4ed8 100%)',\n                color: '#020617',\n                fontSize: '14px',\n                fontWeight: 800,\n                cursor: 'pointer',\n              }}\n            >\n              Open dashboard\n            </button>\n          </div>\n        </div>\n      );\n    }\n\n    return this.props.children;\n  }\n}\n\nexport const AppContent: React.FC = () => {`
);
replaceOnce(
  'Frontend/src/App.tsx',
  `export const App: React.FC = () => {\n  return (\n    <AuthProvider>\n      <AppContent />\n    </AuthProvider>\n  );\n};`,
  `export const App: React.FC = () => {\n  return (\n    <AppErrorBoundary>\n      <AuthProvider>\n        <AppContent />\n      </AuthProvider>\n    </AppErrorBoundary>\n  );\n};`
);

replaceOnce(
  'Frontend/src/pages/LandingPage.tsx',
  `import { useAuth } from '../context/AuthContext';\n`,
  `import { useAuth } from '../context/AuthContext';\nimport { safeLocalStorageGet, safeLocalStorageSet } from '../utils/browserStorage';\n`
);
replaceOnce(
  'Frontend/src/pages/LandingPage.tsx',
  `  let visitCount = 1;\n  if (typeof window !== 'undefined') {\n    visitCount = parseInt(localStorage.getItem('pl_visits') || '0', 10) + 1;\n  }\n`,
  `  let visitCount = 1;\n  if (typeof window !== 'undefined') {\n    const storedVisits = parseInt(safeLocalStorageGet('pl_visits', '0'), 10);\n    visitCount = (Number.isFinite(storedVisits) ? storedVisits : 0) + 1;\n  }\n`
);
replaceOnce(
  'Frontend/src/pages/LandingPage.tsx',
  `  const savedName = typeof window !== 'undefined' ? (localStorage.getItem('prospektlab_username') || '') : '';\n`,
  `  const savedName = safeLocalStorageGet('prospektlab_username');\n`
);
replaceOnce(
  'Frontend/src/pages/LandingPage.tsx',
  `  useEffect(() => { if (urlName) localStorage.setItem('prospektlab_username', urlName); }, [urlName]);\n`,
  `  useEffect(() => {\n    if (urlName) {\n      safeLocalStorageSet('prospektlab_username', urlName);\n    }\n  }, [urlName]);\n`
);
replaceOnce(
  'Frontend/src/pages/LandingPage.tsx',
  `  useEffect(() => {\n    if (typeof window !== 'undefined') localStorage.setItem('pl_visits', String(ctx.visitCount));\n  }, [ctx.visitCount]);\n`,
  `  useEffect(() => {\n    safeLocalStorageSet('pl_visits', String(ctx.visitCount));\n  }, [ctx.visitCount]);\n`
);

replaceOnce(
  'Frontend/src/pages/GatewayPage.tsx',
  `import { trackEvent } from '../telemetry';\n`,
  `import { trackEvent } from '../telemetry';\nimport { safeLocalStorageGet, safeLocalStorageSet } from '../utils/browserStorage';\n`
);
replaceOnce(
  'Frontend/src/pages/GatewayPage.tsx',
  `  const [name, setName] = useState(() => localStorage.getItem('prospektlab_username') || '');\n`,
  `  const [name, setName] = useState(() => safeLocalStorageGet('prospektlab_username'));\n`
);
replaceOnce(
  'Frontend/src/pages/GatewayPage.tsx',
  `  const [style, setStyle] = useState<'Conservative' | 'Balanced' | 'Growth'>(() => {\n    const saved = localStorage.getItem('prospektlab_style');\n    return (saved as any) || 'Balanced';\n  });\n`,
  `  const [style, setStyle] = useState<'Conservative' | 'Balanced' | 'Growth'>(() => {\n    const saved = safeLocalStorageGet('prospektlab_style');\n    return (saved as any) || 'Balanced';\n  });\n`
);
replaceOnce(
  'Frontend/src/pages/GatewayPage.tsx',
  `  const persistProfile = () => {\n    if (name.trim()) {\n      localStorage.setItem('prospektlab_username', name.trim());\n    }\n    localStorage.setItem('prospektlab_style', style);\n  };\n`,
  `  const persistProfile = () => {\n    if (name.trim()) {\n      safeLocalStorageSet('prospektlab_username', name.trim());\n    }\n    safeLocalStorageSet('prospektlab_style', style);\n  };\n`
);

replaceOnce(
  'Frontend/src/components/layout/Sidebar.tsx',
  `import { useAuth } from '../../context/AuthContext';\n`,
  `import { useAuth } from '../../context/AuthContext';\nimport { safeLocalStorageGet, safeLocalStorageSet } from '../../utils/browserStorage';\n`
);
replaceOnce(
  'Frontend/src/components/layout/Sidebar.tsx',
  `  const [width, setWidth] = useState<number>(() => {\n    const saved = localStorage.getItem('prospektlab_sidebar_width');\n    return saved ? parseInt(saved, 10) : 260;\n  });\n`,
  `  const [width, setWidth] = useState<number>(() => {\n    const saved = safeLocalStorageGet('prospektlab_sidebar_width');\n    return saved ? parseInt(saved, 10) : 260;\n  });\n`
);
replaceOnce(
  'Frontend/src/components/layout/Sidebar.tsx',
  `      setWidth(nextWidth);\n      localStorage.setItem('prospektlab_sidebar_width', String(nextWidth));\n`,
  `      setWidth(nextWidth);\n      safeLocalStorageSet('prospektlab_sidebar_width', String(nextWidth));\n`
);
replaceOnce(
  'Frontend/src/components/layout/Sidebar.tsx',
  `              setWidth(260);\n              localStorage.setItem('prospektlab_sidebar_width', '260');\n`,
  `              setWidth(260);\n              safeLocalStorageSet('prospektlab_sidebar_width', '260');\n`
);
replaceOnce(
  'Frontend/src/components/layout/Sidebar.tsx',
  `                  setWidth(260);\n                  localStorage.setItem('prospektlab_sidebar_width', '260');\n`,
  `                  setWidth(260);\n                  safeLocalStorageSet('prospektlab_sidebar_width', '260');\n`
);
replaceOnce(
  'Frontend/src/components/layout/Sidebar.tsx',
  `                  setWidth(56);\n                  localStorage.setItem('prospektlab_sidebar_width', '56');\n`,
  `                  setWidth(56);\n                  safeLocalStorageSet('prospektlab_sidebar_width', '56');\n`
);

replaceOnce(
  'Frontend/src/pages/Dashboard.tsx',
  `import { buildProspektCover } from '../utils/coverArt';\n`,
  `import { buildProspektCover } from '../utils/coverArt';\nimport { safeLocalStorageGet } from '../utils/browserStorage';\n`
);
replaceOnce(
  'Frontend/src/pages/Dashboard.tsx',
  `  const [chatWidth, setChatWidth] = useState<number>(() => {\n    const saved = localStorage.getItem(CHAT_WIDTH_STORAGE_KEY);\n    return saved ? normalizeChatWidth(parseInt(saved, 10)) : getDefaultChatWidth();\n  });\n`,
  `  const [chatWidth, setChatWidth] = useState<number>(() => {\n    const saved = safeLocalStorageGet(CHAT_WIDTH_STORAGE_KEY);\n    return saved ? normalizeChatWidth(parseInt(saved, 10)) : getDefaultChatWidth();\n  });\n`
);
replaceOnce(
  'Frontend/src/pages/Dashboard.tsx',
  `  const [isChatHidden, setIsChatHidden] = useState(() => {\n    const savedWidth = localStorage.getItem(CHAT_WIDTH_STORAGE_KEY);\n    return savedWidth ? parseInt(savedWidth, 10) <= 0 : false;\n  });\n`,
  `  const [isChatHidden, setIsChatHidden] = useState(() => {\n    const savedWidth = safeLocalStorageGet(CHAT_WIDTH_STORAGE_KEY);\n    return savedWidth ? parseInt(savedWidth, 10) <= 0 : false;\n  });\n`
);
replaceOnce(
  'Frontend/src/pages/Dashboard.tsx',
  `    const name = (user?.name || localStorage.getItem('prospektlab_username') || 'there').split(/\\s+/)[0];\n`,
  `    const name = (user?.name || safeLocalStorageGet('prospektlab_username', 'there') || 'there').split(/\\s+/)[0];\n`
);

replaceOnce(
  'Frontend/src/hooks/useMarketFeed.ts',
  `import { getMarketQuotes, getMarketIndices } from '../api/client';\n`,
  `import { getMarketQuotes, getMarketIndices } from '../api/client';\nimport { getRuntimeWebSocketBase } from '../utils/runtimeConfig';\n`
);
replaceOnce(
  'Frontend/src/hooks/useMarketFeed.ts',
  `const WS_URL = (() => {\n  const apiBase = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\\/$/, '');\n  return apiBase.replace(/^http/, 'ws') + '/ws/market';\n})();\n`,
  `const WS_URL = (() => {\n  const wsBase = getRuntimeWebSocketBase('http://localhost:8000');\n  return wsBase + '/ws/market';\n})();\n`
);

console.log('patched');

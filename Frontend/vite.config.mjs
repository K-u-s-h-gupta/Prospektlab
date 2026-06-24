import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const researchHubDevMiddleware = () => ({
  name: 'research-hub-dev-routes',
  configureServer(server) {
    server.middlewares.use((req, _res, next) => {
      const rawUrl = req.url || ''
      const [pathname, query = ''] = rawUrl.split('?')
      const normalized = pathname.endsWith('/') && pathname.length > 1
        ? pathname.slice(0, -1)
        : pathname

      if (normalized === '/research') {
        req.url = `/insights/research/index.html${query ? `?${query}` : ''}`
        next()
        return
      }

      const articleMatch = normalized.match(/^\/research\/([^/]+)$/)
      if (articleMatch?.[1]) {
        req.url = `/insights/${articleMatch[1]}/index.html${query ? `?${query}` : ''}`
      }

      next()
    })
  },
})

export default defineConfig({
  plugins: [react(), researchHubDevMiddleware()],
  build: {
    // Emit bundles at root for current Amplify deployment behavior.
    assetsDir: '',
  },
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/auth': 'http://localhost:8000',
      '^/research/(start|deep|export-all|export)': 'http://localhost:8000',
      '^/research/export/': 'http://localhost:8000',
      '/sessions': 'http://localhost:8000',
      '/portfolio': 'http://localhost:8000',
      '/ipo': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
      '/chat': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/memos': 'http://localhost:8000',
      '/market': 'http://localhost:8000',
      '/user': 'http://localhost:8000',
      '/public/market/ticker': 'http://localhost:8000',
      '^/insights(?:/|$)': {
        target: 'http://localhost:8000',
        changeOrigin: false,
        rewrite: (path) => path.replace(/\/+$/, '') || '/',
      },
    },
  },
})

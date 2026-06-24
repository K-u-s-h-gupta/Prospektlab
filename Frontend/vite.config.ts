import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // Amplify is serving the HTML and root-level static files correctly, but
    // the /assets/ directory is not being published reliably in this app's
    // current deployment flow. Emit the SPA bundle at the site root so the
    // production HTML can load it without depending on /assets/.
    assetsDir: '',
  },
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/auth': 'http://localhost:8000',
      '/research': 'http://localhost:8000',
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
      // Proxy public insights content routes to the backend.
      // The rewrite strips a trailing slash so the backend receives
      // /insights/slug (no slash) directly — avoiding a 307 redirect
      // that would break the browser out of the Vite proxy.
      '^/insights': {
        target: 'http://localhost:8000',
        changeOrigin: false,
        rewrite: (path) => path.replace(/\/+$/, '') || '/',
      },
    }
  }
})

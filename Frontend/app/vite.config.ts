import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/auth': 'http://localhost:8000',
      '/research': 'http://localhost:8000',
      '/sessions': 'http://localhost:8000',
      '/portfolio': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
      '/chat': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/memos': 'http://localhost:8000',
      '/market': 'http://localhost:8000',
      '/user': 'http://localhost:8000',
    }
  }
})

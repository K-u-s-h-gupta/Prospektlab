import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import { initializeTelemetry } from './telemetry'
import './index.css'
import './styles/enhancements.css'
import './components/charts/ThemeProvider'

const DIRECT_ENTRY_HASH_ROUTES = new Set([
  '/pricing',
  '/testimonials',
  '/features',
  '/contact',
  '/login',
  '/signup',
  '/get-started',
  '/onboarding',
  '/onboarding/manual',
  '/onboarding/upload',
  '/onboarding/watchlist',
  '/dashboard',
  '/dashboard/overview',
  '/dashboard/portfolio',
  '/dashboard/watchlist',
  '/dashboard/screener',
  '/dashboard/earnings',
  '/dashboard/governance',
  '/insights-studio',
])

function normalizeInitialHashRoute(): void {
  if (typeof window === 'undefined' || window.location.hash) {
    return
  }

  const normalizedPath = window.location.pathname.length > 1
    ? window.location.pathname.replace(/\/+$/, '')
    : window.location.pathname

  if (!DIRECT_ENTRY_HASH_ROUTES.has(normalizedPath)) {
    return
  }

  window.history.replaceState(null, '', `/#${normalizedPath}${window.location.search}`)
}

normalizeInitialHashRoute()
initializeTelemetry()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import { initializeTelemetry } from './telemetry'
import './index.css'
import './styles/enhancements.css'
import './components/charts/ThemeProvider'

/**
 * Migrate old hash-based URLs (e.g. /#/dashboard/overview) to clean URLs.
 * This handles backward compatibility for users who bookmarked or shared
 * the old hash-based routes.
 */
function migrateHashRouteToCleanUrl(): void {
  if (typeof window === 'undefined') return
  const hash = window.location.hash
  if (hash && hash.startsWith('#/')) {
    const cleanPath = hash.slice(1) // Remove the '#' prefix
    window.history.replaceState(null, '', cleanPath + window.location.search)
  }
}

migrateHashRouteToCleanUrl()
initializeTelemetry()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

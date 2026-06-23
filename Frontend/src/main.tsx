import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import { initializeTelemetry } from './telemetry'
import './index.css'
import './styles/enhancements.css'
import './components/charts/ThemeProvider'

try {
  initializeTelemetry()
} catch (error) {
  console.error('Telemetry initialization failed.', error)
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

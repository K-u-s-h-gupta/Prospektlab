import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import { initializeTelemetry } from './telemetry'
import './index.css'
import './components/charts/ThemeProvider'

initializeTelemetry()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)

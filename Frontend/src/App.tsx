import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation, useParams } from 'react-router-dom';
import GatewayPage from './pages/GatewayPage';
import ManualEntry from './pages/ManualEntry';
import UploadPage from './pages/UploadPage';
import WatchlistStep from './pages/WatchlistStep';
import Dashboard from './pages/Dashboard';
import DashboardEarningsPage from './pages/DashboardEarningsPage';
import DashboardGovernancePage from './pages/DashboardGovernancePage';
import DashboardIpoPage from './pages/DashboardIpoPage';
import InsightsStudio from './pages/InsightsStudio';
import IpoDashboard from './pages/IpoDashboard';
import IpoDetailPage from './pages/IpoDetailPage';
import IpoTrackingPage from './pages/IpoTrackingPage';
import { Login } from './pages/Login';
import { AuthProvider } from './context/AuthContext';
import { trackPageView } from './telemetry';
import CommandPalette from './components/common/CommandPalette';

type DashboardTabParam = 'overview' | 'portfolio' | 'watchlist' | 'screener';

// Global Error Boundary to prevent blank white pages on uncaught errors
class AppErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean; error: Error | null; autoRecovering: boolean }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false, error: null, autoRecovering: false };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ProspektLab] Uncaught render error:', error, info.componentStack);
    // Auto-recover from JSON/storage corruption errors after clearing bad keys
    const msg = error?.message || '';
    const isStorageCorruption = msg.toLowerCase().includes('json') ||
      msg.toLowerCase().includes('parse') ||
      msg.toLowerCase().includes('unexpected token') ||
      msg.toLowerCase().includes('unexpected end') ||
      error instanceof SyntaxError;
    if (isStorageCorruption) {
      this.clearCorruptedStorage();
      this.setState({ autoRecovering: true });
      setTimeout(() => window.location.reload(), 800);
    }
  }

  clearCorruptedStorage() {
    try {
      const toRemove: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (!key?.startsWith('prospektlab_')) continue;
        try {
          const raw = localStorage.getItem(key);
          if (raw) JSON.parse(raw);
        } catch {
          toRemove.push(key);
        }
      }
      toRemove.forEach(k => localStorage.removeItem(k));
    } catch { /* ignore */ }
  }

  render() {
    if (this.state.hasError) {
      if (this.state.autoRecovering) {
        return (
          <div style={{
            minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
            background: '#0a0e1a', color: '#38bdf8', fontFamily: 'Inter, system-ui, sans-serif',
            position: 'relative', zIndex: 10,
          }}>
            <div style={{ textAlign: 'center' }}>
              <p style={{ fontSize: 14 }}>Fixing corrupted cache, reloading...</p>
            </div>
          </div>
        );
      }
      return (
        <div style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#0a0e1a',
          color: '#e2e8f0',
          fontFamily: 'Inter, system-ui, sans-serif',
          padding: 32,
          position: 'relative',
          zIndex: 10,
        }}>
          <div style={{ maxWidth: 480, textAlign: 'center' }}>
            <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 12 }}>Something went wrong</h1>
            <p style={{ fontSize: 14, color: '#94a3b8', marginBottom: 20, lineHeight: 1.6 }}>
              {this.state.error?.message || 'An unexpected error occurred.'}
            </p>
            <button
              onClick={() => {
                this.clearCorruptedStorage();
                window.location.reload();
              }}
              style={{
                padding: '10px 24px',
                borderRadius: 8,
                border: '1px solid rgba(56, 189, 248, 0.3)',
                background: 'rgba(56, 189, 248, 0.15)',
                color: '#38bdf8',
                fontSize: 14,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Reload App
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const DashboardRoute: React.FC = () => {
  const { featureTab } = useParams<{ featureTab?: string }>();
  const normalized = String(featureTab || '').toLowerCase();
  const tab: DashboardTabParam =
    normalized === 'portfolio' || normalized === 'watchlist' || normalized === 'screener'
      ? (normalized as DashboardTabParam)
      : 'overview';

  return <Dashboard initialFeatureTab={tab} />;
};

const TelemetryRouteTracker: React.FC = () => {
  const location = useLocation();

  React.useEffect(() => {
    trackPageView(location.pathname, {
      route: location.pathname,
      search: location.search || '',
    });
  }, [location.pathname, location.search]);

  return null;
};

const ExternalRedirect: React.FC<{ to: string }> = ({ to }) => {
  React.useEffect(() => {
    window.location.replace(to);
  }, [to]);
  return null;
};

export const AppContent: React.FC = () => {
  return (
    <BrowserRouter>
      <TelemetryRouteTracker />
      <CommandPalette />
      <Routes>
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/pricing" element={<Navigate to="/dashboard/overview" replace />} />
        <Route path="/testimonials" element={<Navigate to="/dashboard/overview" replace />} />
        <Route path="/features" element={<Navigate to="/dashboard/overview" replace />} />
        <Route path="/contact" element={<Navigate to="/dashboard/overview" replace />} />

        <Route path="/get-started" element={<GatewayPage />} />
        <Route path="/onboarding/manual" element={<ManualEntry />} />
        <Route path="/onboarding/upload" element={<UploadPage />} />
        <Route path="/onboarding/watchlist" element={<WatchlistStep />} />
        <Route path="/onboarding" element={<Navigate to="/get-started" replace />} />

        {/* Auth routes - login/signup are optional, users can skip to dashboard */}
        <Route path="/login" element={<Login initialTab="login" />} />
        <Route path="/signup" element={<Login initialTab="signup" />} />

        <Route path="/research" element={<ExternalRedirect to="/research/" />} />
        <Route path="/dashboard" element={<Navigate to="/dashboard/overview" replace />} />
        <Route path="/dashboard/earnings" element={<DashboardEarningsPage />} />
        <Route path="/dashboard/governance" element={<DashboardGovernancePage />} />
        <Route path="/dashboard/ipo" element={<DashboardIpoPage />} />
        <Route path="/dashboard/:featureTab" element={<DashboardRoute />} />
        <Route path="/insights-studio" element={<InsightsStudio />} />
        <Route path="/ipo" element={<IpoDashboard />} />
        <Route path="/ipo/:slug/tracking" element={<IpoTrackingPage />} />
        <Route path="/ipo/:slug" element={<IpoDetailPage />} />

        <Route path="*" element={<Navigate to="/dashboard/overview" replace />} />
      </Routes>
    </BrowserRouter>
  );
};

export const App: React.FC = () => {
  return (
    <AppErrorBoundary>
      <AuthProvider>
        <AppContent />
      </AuthProvider>
    </AppErrorBoundary>
  );
};

export default App;

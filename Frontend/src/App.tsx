import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation, useParams } from 'react-router-dom';
import LandingPage from './pages/LandingPage';
import GatewayPage from './pages/GatewayPage';
import ManualEntry from './pages/ManualEntry';
import UploadPage from './pages/UploadPage';
import WatchlistStep from './pages/WatchlistStep';
import Dashboard from './pages/Dashboard';
import DashboardEarningsPage from './pages/DashboardEarningsPage';
import DashboardGovernancePage from './pages/DashboardGovernancePage';
import InsightsStudio from './pages/InsightsStudio';
import { AuthProvider } from './context/AuthContext';
import { trackException, trackPageView } from './telemetry';
import CommandPalette from './components/common/CommandPalette';

type DashboardTabParam = 'overview' | 'portfolio' | 'watchlist' | 'screener';

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

type AppErrorBoundaryProps = {
  children: React.ReactNode;
};

type AppErrorBoundaryState = {
  hasError: boolean;
};

class AppErrorBoundary extends React.Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = {
    hasError: false,
  };

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    trackException(error, {
      source: 'app_error_boundary',
      component_stack: info.componentStack || '',
    });
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            minHeight: '100vh',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '24px',
            background: '#03060d',
            color: '#f8fbff',
            fontFamily: "'Inter', system-ui, sans-serif",
          }}
        >
          <div
            style={{
              width: 'min(520px, 100%)',
              padding: '24px',
              borderRadius: '18px',
              border: '1px solid rgba(148, 163, 184, 0.18)',
              background: 'rgba(15, 23, 42, 0.85)',
              boxShadow: '0 24px 80px rgba(0, 0, 0, 0.35)',
            }}
          >
            <div
              style={{
                fontSize: '12px',
                fontWeight: 700,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                color: '#60a5fa',
                marginBottom: '12px',
              }}
            >
              ProspektLab
            </div>
            <h1 style={{ margin: 0, fontSize: '24px', lineHeight: 1.2 }}>
              We hit a loading issue while opening the app.
            </h1>
            <p style={{ margin: '12px 0 20px', color: '#a8b4c8', lineHeight: 1.6 }}>
              Refresh once to retry. If the problem continues, use the button below to reopen the dashboard cleanly.
            </p>
            <button
              type="button"
              onClick={() => window.location.assign('/dashboard/overview')}
              style={{
                border: 'none',
                borderRadius: '12px',
                padding: '12px 18px',
                background: 'linear-gradient(135deg, #eaf3ff 0%, #60a5fa 46%, #1d4ed8 100%)',
                color: '#020617',
                fontSize: '14px',
                fontWeight: 800,
                cursor: 'pointer',
              }}
            >
              Open dashboard
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export const AppContent: React.FC = () => {
  return (
    <BrowserRouter>
      <TelemetryRouteTracker />
      <CommandPalette />
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/pricing" element={<Navigate to="/dashboard/overview" replace />} />
        <Route path="/testimonials" element={<Navigate to="/dashboard/overview" replace />} />
        <Route path="/features" element={<Navigate to="/dashboard/overview" replace />} />
        <Route path="/contact" element={<Navigate to="/dashboard/overview" replace />} />

        <Route path="/get-started" element={<GatewayPage />} />
        <Route path="/onboarding/manual" element={<ManualEntry />} />
        <Route path="/onboarding/upload" element={<UploadPage />} />
        <Route path="/onboarding/watchlist" element={<WatchlistStep />} />
        <Route path="/onboarding" element={<Navigate to="/get-started" replace />} />

        {/* Auth paths are disabled in open-access mode. */}
        <Route path="/login" element={<Navigate to="/dashboard/overview" replace />} />
        <Route path="/signup" element={<Navigate to="/dashboard/overview" replace />} />

        <Route path="/dashboard" element={<Navigate to="/dashboard/overview" replace />} />
        <Route path="/dashboard/earnings" element={<DashboardEarningsPage />} />
        <Route path="/dashboard/governance" element={<DashboardGovernancePage />} />
        <Route path="/dashboard/:featureTab" element={<DashboardRoute />} />
        <Route path="/insights-studio" element={<InsightsStudio />} />

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

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
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
};

export default App;

import React from 'react';
import { HashRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import LandingPage from './pages/LandingPage';
import Pricing from './pages/Pricing';
import Testimonials from './pages/Testimonials';
import Features from './pages/Features';
import ContactUs from './pages/ContactUs';
import GatewayPage from './pages/GatewayPage';
import ManualEntry from './pages/ManualEntry';
import UploadPage from './pages/UploadPage';
import WatchlistStep from './pages/WatchlistStep';
import { Dashboard } from './pages/Dashboard';
import { Login } from './pages/Login';
import InsightsStudio from './pages/InsightsStudio';
import { AuthProvider, useAuth } from './context/AuthContext';
import { trackPageView } from './telemetry';
import CommandPalette from './components/common/CommandPalette';

// Protected Route for authenticated users
const ProtectedRoute: React.FC<{
  children: React.ReactElement;
  requireOnboarded?: boolean;
  /** Skip all onboarding checks — just require the user to be authenticated */
  authOnly?: boolean;
}> = ({ children, requireOnboarded = false, authOnly = false }) => {
  const { isAuthenticated, isLoading, onboarded } = useAuth();

  if (isLoading) {
    return (
      <div style={{ display: 'flex', width: '100%', height: '100vh', alignItems: 'center', justifyContent: 'center', backgroundColor: 'var(--bg-deep)' }}>
        <div style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>Loading workspace...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  // authOnly routes (e.g. Insights Studio) skip all portfolio-onboarding checks
  if (authOnly) {
    return children;
  }

  if (requireOnboarded && !onboarded) {
    return <Navigate to="/get-started" replace />;
  }

  if (!requireOnboarded && onboarded) {
    return <Navigate to="/dashboard" replace />;
  }

  return children;
};

// Route for anonymous users only (login/signup). If a redirect is provided in
// the URL query string, authenticated users are sent there instead of the default.
const PublicRoute: React.FC<{ children: React.ReactElement }> = ({ children }) => {
  const { isAuthenticated, isLoading, onboarded } = useAuth();
  const location = useLocation();
  const redirectTo = new URLSearchParams(location.search).get('redirect') || '';

  if (isLoading) {
    return (
      <div style={{ display: 'flex', width: '100%', height: '100vh', alignItems: 'center', justifyContent: 'center', backgroundColor: 'var(--bg-deep)' }}>
        <div style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>Loading workspace...</div>
      </div>
    );
  }

  if (isAuthenticated) {
    const target = redirectTo || (onboarded ? "/dashboard" : "/get-started");
    return <Navigate to={target} replace />;
  }

  return children;
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

export const AppContent: React.FC = () => {
  return (
    <HashRouter>
      <TelemetryRouteTracker />
      <CommandPalette />
      <Routes>
        {/* Marketing Pages */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/pricing" element={<Pricing />} />
        <Route path="/testimonials" element={<Testimonials />} />
        <Route path="/features" element={<Features />} />
        <Route path="/contact" element={<ContactUs />} />
        
        {/* Onboarding Gateway / Manual Entry — public, no auth required */}
        <Route path="/get-started" element={<GatewayPage />} />
        <Route path="/onboarding/manual" element={<ManualEntry />} />

        {/* Upload flow — requires auth (documents are processed server-side) */}
        <Route 
          path="/onboarding/upload" 
          element={
            <ProtectedRoute>
              <UploadPage />
            </ProtectedRoute>
          } 
        />

        <Route 
          path="/onboarding/watchlist" 
          element={
            <ProtectedRoute>
              <WatchlistStep />
            </ProtectedRoute>
          } 
        />

        {/* Legacy onboarding redirect */}
        <Route path="/onboarding" element={<Navigate to="/get-started" replace />} />

        {/* Auth Pages */}
        <Route 
          path="/login" 
          element={
            <PublicRoute>
              <Login initialTab="login" />
            </PublicRoute>
          } 
        />

        <Route 
          path="/signup" 
          element={
            <PublicRoute>
              <Login initialTab="signup" />
            </PublicRoute>
          } 
        />
        
        {/* Dashboard — accessible to everyone. Read-only mode when unauthenticated. */}
        <Route path="/dashboard" element={<Dashboard />} />

        <Route
          path="/insights-studio"
          element={
            <ProtectedRoute authOnly>
              <InsightsStudio />
            </ProtectedRoute>
          }
        />

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
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

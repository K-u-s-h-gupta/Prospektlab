import React from 'react';
import { HashRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import LandingPage from './pages/LandingPage';
import Pricing from './pages/Pricing';
import Testimonials from './pages/Testimonials';
import Features from './pages/Features';
import Onboarding from './pages/Onboarding';
import ContactUs from './pages/ContactUs';
import { Dashboard } from './pages/Dashboard';
import { ControlTowerPage } from './pages/ControlTower';
import { Login } from './pages/Login';
import { AuthProvider, useAuth } from './context/AuthContext';
import { hydrateAuthToken } from './api/client';
import { trackPageView } from './telemetry';

// Protected Route for authenticated users
const ProtectedRoute: React.FC<{
  children: React.ReactElement;
  requireOnboarded?: boolean;
  onboardingOnly?: boolean;
}> = ({
  children,
  requireOnboarded = false,
  onboardingOnly = false,
}) => {
  const { isAuthenticated, isLoading, onboarded } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div style={{ display: 'flex', width: '100%', height: '100vh', alignItems: 'center', justifyContent: 'center', backgroundColor: 'var(--bg-deep)' }}>
        <div style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>Loading workspace...</div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ next: location.pathname }} />;
  }

  if (requireOnboarded && !onboarded) {
    return <Navigate to="/onboarding" replace />;
  }

  if (onboardingOnly && onboarded) {
    return <Navigate to="/dashboard" replace />;
  }

  return children;
};

// Route for anonymous users only
const PublicRoute: React.FC<{ children: React.ReactElement }> = ({ children }) => {
  const { isAuthenticated, isLoading, onboarded } = useAuth();

  if (isLoading) {
    return (
      <div style={{ display: 'flex', width: '100%', height: '100vh', alignItems: 'center', justifyContent: 'center', backgroundColor: 'var(--bg-deep)' }}>
        <div style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>Loading workspace...</div>
      </div>
    );
  }

  if (isAuthenticated) {
    return <Navigate to={onboarded ? "/dashboard" : "/onboarding"} replace />;
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

function hydrateLocalDevTokenFromUrl() {
  if (typeof window === 'undefined') return;
  const isLocalHost = window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost';
  if (!isLocalHost) return;

  const rawHash = window.location.hash || '';
  const hashPath = rawHash.startsWith('#') ? rawHash.slice(1) : rawHash;
  const hashQuery = hashPath.includes('?') ? hashPath.slice(hashPath.indexOf('?') + 1) : '';
  const params = new URLSearchParams(hashQuery);
  const devToken = params.get('devToken');
  if (!devToken) return;

  hydrateAuthToken(devToken, true);
  params.delete('devToken');
  const nextPath = hashPath.includes('?') ? hashPath.slice(0, hashPath.indexOf('?')) : hashPath;
  const nextSearch = params.toString();
  const nextHash = `${nextPath}${nextSearch ? `?${nextSearch}` : ''}`;
  window.history.replaceState(null, '', `#${nextHash || '/'}`);
}

export const AppContent: React.FC = () => {
  hydrateLocalDevTokenFromUrl();

  return (
    <HashRouter>
      <TelemetryRouteTracker />
      <Routes>
        {/* Marketing Pages */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/pricing" element={<Pricing />} />
        <Route path="/testimonials" element={<Testimonials />} />
        <Route path="/features" element={<Features />} />
        <Route path="/contact" element={<ContactUs />} />
        
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
        
        {/* App Pages */}
        <Route 
          path="/onboarding" 
          element={
            <ProtectedRoute onboardingOnly>
              <Onboarding />
            </ProtectedRoute>
          } 
        />
        
        <Route 
          path="/dashboard" 
          element={
            <ProtectedRoute requireOnboarded>
              <Dashboard />
            </ProtectedRoute>
          } 
        />

        <Route
          path="/ops"
          element={
            <ProtectedRoute>
              <ControlTowerPage />
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

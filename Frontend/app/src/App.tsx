import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import LandingPage from './pages/LandingPage';
import Pricing from './pages/Pricing';
import Testimonials from './pages/Testimonials';
import Features from './pages/Features';
import Onboarding from './pages/Onboarding';
import ContactUs from './pages/ContactUs';
import { Dashboard } from './pages/Dashboard';
import { ControlTowerPage } from './pages/ControlTower';
import { AuthProvider } from './context/AuthContext';
import { hydrateAuthToken } from './api/client';
import { trackPageView } from './telemetry';

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

function upgradeLegacyHashLocation() {
  if (typeof window === 'undefined') return;
  const rawHash = window.location.hash || '';
  if (!rawHash.startsWith('#/')) return;

  const hashPath = rawHash.slice(1);
  const nextPath = hashPath.includes('?') ? hashPath.slice(0, hashPath.indexOf('?')) : hashPath;
  const hashQuery = hashPath.includes('?') ? hashPath.slice(hashPath.indexOf('?') + 1) : '';
  const current = new URL(window.location.href);
  const mergedParams = new URLSearchParams(current.search);
  const hashParams = new URLSearchParams(hashQuery);

  hashParams.forEach((value, key) => {
    if (!mergedParams.has(key)) {
      mergedParams.set(key, value);
    }
  });

  const nextSearch = mergedParams.toString();
  const nextUrl = `${nextPath || '/'}${nextSearch ? `?${nextSearch}` : ''}`;
  window.history.replaceState(null, '', nextUrl);
}

function hydrateBootstrapTokenFromUrl() {
  if (typeof window === 'undefined') return;
  const current = new URL(window.location.href);
  const params = new URLSearchParams(current.search);
  const opsToken = params.get('opsToken');
  const devToken = params.get('devToken');
  const isLocalHost = window.location.hostname === '127.0.0.1' || window.location.hostname === 'localhost';
  const bootstrapToken = opsToken || (isLocalHost ? devToken : '');
  if (!bootstrapToken) return;

  hydrateAuthToken(bootstrapToken, true);
  params.delete('opsToken');
  params.delete('devToken');
  const nextSearch = params.toString();
  window.history.replaceState(null, '', `${current.pathname}${nextSearch ? `?${nextSearch}` : ''}`);
}

export const AppContent: React.FC = () => {
  upgradeLegacyHashLocation();
  hydrateBootstrapTokenFromUrl();

  return (
    <BrowserRouter>
      <TelemetryRouteTracker />
      <Routes>
        {/* Marketing Pages */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/pricing" element={<Pricing />} />
        <Route path="/testimonials" element={<Testimonials />} />
        <Route path="/features" element={<Features />} />
        <Route path="/contact" element={<ContactUs />} />

        {/* Auth routes disabled in open-access mode */}
        <Route path="/login" element={<Navigate to="/dashboard" replace />} />
        <Route path="/signup" element={<Navigate to="/dashboard" replace />} />

        {/* App Pages */}
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/ops" element={<ControlTowerPage />} />

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
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

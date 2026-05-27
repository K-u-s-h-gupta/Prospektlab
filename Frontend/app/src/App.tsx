import React from 'react';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import Onboarding from './pages/Onboarding';
import { Dashboard } from './pages/Dashboard';
import { Login } from './pages/Login';
import { AuthProvider, useAuth } from './context/AuthContext';

// Protected Route for authenticated users
const ProtectedRoute: React.FC<{ children: React.ReactElement; requireOnboarded?: boolean }> = ({ 
  children, 
  requireOnboarded = false 
}) => {
  const { isAuthenticated, isLoading } = useAuth();
  const onboarded = localStorage.getItem('prospektlab_onboarded') === 'true';

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

  if (requireOnboarded && !onboarded) {
    return <Navigate to="/onboarding" replace />;
  }

  if (!requireOnboarded && onboarded) {
    return <Navigate to="/dashboard" replace />;
  }

  return children;
};

// Route for anonymous users only
const PublicRoute: React.FC<{ children: React.ReactElement }> = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth();
  const onboarded = localStorage.getItem('prospektlab_onboarded') === 'true';

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

export const AppContent: React.FC = () => {
  const { isAuthenticated } = useAuth();
  const onboarded = localStorage.getItem('prospektlab_onboarded') === 'true';

  return (
    <HashRouter>
      <Routes>
        <Route
          path="/"
          element={
            isAuthenticated 
              ? (onboarded ? <Navigate to="/dashboard" replace /> : <Navigate to="/onboarding" replace />)
              : <Navigate to="/login" replace />
          }
        />
        
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
        
        <Route 
          path="/onboarding" 
          element={
            <ProtectedRoute>
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

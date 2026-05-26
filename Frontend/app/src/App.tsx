import React from 'react';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import Onboarding from './pages/Onboarding';
import Dashboard from './pages/Dashboard';

export const App: React.FC = () => {
  // Check if user completed onboarding
  const isOnboarded = localStorage.getItem('prospektlab_onboarded') === 'true';

  return (
    <HashRouter>
      <Routes>
        {/* If onboarded, send to dashboard; otherwise onboarding */}
        <Route
          path="/"
          element={isOnboarded ? <Navigate to="/dashboard" replace /> : <Navigate to="/onboarding" replace />}
        />
        
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/dashboard" element={<Dashboard />} />

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  );
};
export default App;

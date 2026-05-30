import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { getAuthToken, getStoredAuthUser, apiLogin, apiSignup, apiLogout, apiGoogleAuth, getPortfolioMirror } from '../api/client';

export interface User {
  email: string;
  name: string;
  mobile?: string;
  require_mobile?: boolean;
}

export interface Toast {
  id: string;
  message: string;
  type: 'success' | 'error' | 'info';
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  onboarded: boolean;
  login: (email: string, password: string, remember?: boolean) => Promise<any>;
  signup: (name: string, email: string, password: string, mobile: string, verificationCode: string) => Promise<any>;
  googleLogin: (credential: string) => Promise<any>;
  logout: () => Promise<void>;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  updateUserMobile: (mobile: string) => void;
  setOnboarded: (next: boolean) => void;
  refreshOnboardingStatus: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [onboarded, setOnboardedState] = useState<boolean>(() => localStorage.getItem('prospektlab_onboarded') === 'true');
  const [isLoading, setIsLoading] = useState(true);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const setOnboarded = useCallback((next: boolean) => {
    setOnboardedState(next);
    if (next) {
      localStorage.setItem('prospektlab_onboarded', 'true');
    } else {
      localStorage.removeItem('prospektlab_onboarded');
    }
  }, []);

  const refreshOnboardingStatus = useCallback(async () => {
    try {
      const data = await getPortfolioMirror();
      const next = !!(data && (data.count > 0 || data.status === 'MIRROR_SYNCHRONIZED'));
      setOnboarded(next);
      return next;
    } catch (err) {
      console.error('Failed to resolve portfolio mirror state:', err);
      return localStorage.getItem('prospektlab_onboarded') === 'true';
    }
  }, [setOnboarded]);

  useEffect(() => {
    const localToken = getAuthToken();
    const localUser = getStoredAuthUser();

    if (localToken && localUser) {
      try {
        setToken(localToken);
        setUser(JSON.parse(localUser));
        void refreshOnboardingStatus();
      } catch (e) {
        console.error('Failed to parse cached user', e);
        localStorage.removeItem('prospektlab_token');
        localStorage.removeItem('prospektlab_user');
        sessionStorage.removeItem('prospektlab_token');
        sessionStorage.removeItem('prospektlab_user');
        setOnboarded(false);
      }
    }
    setIsLoading(false);
  }, [refreshOnboardingStatus, setOnboarded]);

  const showToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'info') => {
    const id = Date.now().toString() + Math.random().toString(36).substr(2, 5);
    setToasts((prev) => [...prev, { id, message, type }]);
    
    // Automatically remove toast after 4 seconds
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, [setToasts]);

  const login = useCallback(async (email: string, password: string, remember: boolean = true) => {
    try {
      const data = await apiLogin(email, password, remember);

      setToken(data.token);
      setUser({
        email: data.user?.email || email,
        name: data.user?.name || 'Researcher',
      });
      void refreshOnboardingStatus();

      showToast('Successfully signed in.', 'success');
      return data;
    } catch (err: any) {
      showToast(err.message || 'Login failed.', 'error');
      throw err;
    }
  }, [refreshOnboardingStatus, showToast, setToken, setUser]);

  const signup = useCallback(async (name: string, email: string, password: string, mobile: string, verificationCode: string) => {
    try {
      const data = await apiSignup(name, email, password, mobile, verificationCode);
      setToken(data.token);
      setUser({
        email: data.user?.email || email,
        name: data.user?.name || name,
      });
      setOnboarded(false);
      showToast('Account created successfully!', 'success');
      return data;
    } catch (err: any) {
      showToast(err.message || 'Signup failed.', 'error');
      throw err;
    }
  }, [setOnboarded, showToast, setToken, setUser]);

  const googleLogin = useCallback(async (credential: string) => {
    try {
      const data = await apiGoogleAuth(credential);

      setToken(data.token);
      setUser({
        email: data.email,
        name: data.name || data.full_name || 'Researcher',
        mobile: data.mobile,
        require_mobile: data.require_mobile,
      });
      void refreshOnboardingStatus();

      showToast('Successfully signed in with Google.', 'success');
      return data;
    } catch (err: any) {
      showToast(err.message || 'Google Auth failed.', 'error');
      throw err;
    }
  }, [refreshOnboardingStatus, showToast, setToken, setUser]);

  const logout = useCallback(async () => {
    try {
      void apiLogout();
      setToken(null);
      setUser(null);
      setOnboarded(false);
      showToast('Logged out successfully.', 'info');
    } catch (err) {
      console.error('Logout error', err);
      // Fallback clean local states
      localStorage.removeItem('prospektlab_token');
      localStorage.removeItem('prospektlab_user');
      localStorage.removeItem('prospektlab_onboarded');
      sessionStorage.removeItem('prospektlab_token');
      sessionStorage.removeItem('prospektlab_user');
      sessionStorage.removeItem('prospektlab_onboarded');
      setToken(null);
      setUser(null);
      setOnboarded(false);
    }
  }, [setOnboarded, showToast, setToken, setUser]);

  const updateUserMobile = useCallback((mobile: string) => {
    setUser((currentUser) => {
      if (currentUser) {
        const updatedUser = { ...currentUser, mobile, require_mobile: false };
        localStorage.setItem('prospektlab_user', JSON.stringify(updatedUser));
        return updatedUser;
      }
      return currentUser;
    });
  }, [setUser]);

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  const isAuthenticated = !!token;

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated,
        isLoading,
        onboarded,
        login,
        signup,
        googleLogin,
        logout,
        showToast,
        updateUserMobile,
        setOnboarded,
        refreshOnboardingStatus,
      }}
    >
      {children}
      
      {/* Global Toast Render Area */}
      {toasts.length > 0 && (
        <div className="toast-container">
          {toasts.map((toast) => (
            <div key={toast.id} className={`toast-notification ${toast.type}`}>
              <div className="toast-content">{toast.message}</div>
              <button className="toast-close" onClick={() => removeToast(toast.id)}>
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

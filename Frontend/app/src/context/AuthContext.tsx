import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { getAuthMe, getCachedUser, setCachedUser, apiLogin, apiSignup, apiLogout, apiGoogleAuth, getPortfolioMirror } from '../api/client';
import { clearTelemetryUser, setTelemetryUser, trackEvent } from '../telemetry';

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
  refreshOnboardingStatus: (emailOverride?: string) => Promise<boolean>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [onboarded, setOnboardedState] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState(true);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const onboardedKeyFor = useCallback((email?: string | null) => {
    const normalized = (email || '').trim().toLowerCase();
    return normalized ? `prospektlab_onboarded:${normalized}` : 'prospektlab_onboarded';
  }, []);

  const persistOnboarded = useCallback((next: boolean, email?: string | null) => {
    setOnboardedState(next);
    if (typeof window !== 'undefined') {
      const key = onboardedKeyFor(email || user?.email);
      if (next) {
        localStorage.setItem(key, 'true');
      } else {
        localStorage.removeItem(key);
      }
    }
  }, [onboardedKeyFor, user?.email]);

  const readPersistedOnboarded = useCallback((email?: string | null) => {
    if (typeof window === 'undefined') return false;
    return localStorage.getItem(onboardedKeyFor(email || user?.email)) === 'true';
  }, [onboardedKeyFor, user?.email]);

  const setOnboarded = useCallback((next: boolean) => {
    persistOnboarded(next);
  }, [persistOnboarded]);

  const refreshOnboardingStatus = useCallback(async (emailOverride?: string) => {
    try {
      const data = await getPortfolioMirror();
      const next = !!(data && Number(data.count) > 0);
      persistOnboarded(next, emailOverride);
      return next;
    } catch (err) {
      console.error('Failed to resolve portfolio mirror state:', err);
      const fallback = readPersistedOnboarded(emailOverride || user?.email);
      setOnboardedState(fallback);
      return fallback;
    }
  }, [persistOnboarded, readPersistedOnboarded, user?.email]);

  useEffect(() => {
    // On mount, check auth status via httpOnly cookie
    let cancelled = false;
    (async () => {
      const cached = getCachedUser();
      if (cached) {
        setUser(cached);
        await refreshOnboardingStatus(cached.email);
        if (!cancelled) setIsLoading(false);
        return;
      }
      try {
        const me = await getAuthMe();
        if (!cancelled) {
          if (me) {
            setUser(me);
            await refreshOnboardingStatus(me.email);
          } else {
            setUser(null);
            setOnboardedState(false);
          }
          setIsLoading(false);
        }
      } catch (e) {
        if (!cancelled) {
          setUser(null);
          setIsLoading(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [refreshOnboardingStatus]);

  useEffect(() => {
    if (user) {
      setTelemetryUser({
        email: user.email,
        name: user.name,
      });
    } else {
      clearTelemetryUser();
    }
  }, [user]);

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
      const signedInUser = {
        email: data.user?.email || email,
        name: data.user?.name || 'Researcher',
      };
      const nextOnboarded = await refreshOnboardingStatus(signedInUser.email);

      setUser(signedInUser);
      trackEvent('auth_login_success', {
        email: signedInUser.email,
        name: signedInUser.name,
        remember: String(remember),
        onboarded: String(nextOnboarded),
      });

      showToast('Successfully signed in.', 'success');
      return { ...data, onboarded: nextOnboarded };
    } catch (err: any) {
      trackEvent('auth_login_failed', {
        email,
        remember: String(remember),
        error_type: err?.name || 'Error',
      });
      showToast(err.message || 'Login failed.', 'error');
      throw err;
    }
  }, [refreshOnboardingStatus, showToast]);

  const signup = useCallback(async (name: string, email: string, password: string, mobile: string, verificationCode: string) => {
    try {
      const data = await apiSignup(name, email, password, mobile, verificationCode);
      const signedUpUser = {
        email: data.user?.email || email,
        name: data.user?.name || name,
      };
      setUser(signedUpUser);
      trackEvent('auth_signup_success', {
        email: signedUpUser.email,
        name: signedUpUser.name,
      });
      persistOnboarded(false, signedUpUser.email);
      showToast('Account created successfully!', 'success');
      return { ...data, onboarded: false };
    } catch (err: any) {
      trackEvent('auth_signup_failed', {
        email,
        error_type: err?.name || 'Error',
      });
      showToast(err.message || 'Signup failed.', 'error');
      throw err;
    }
  }, [persistOnboarded, showToast]);

  const googleLogin = useCallback(async (credential: string) => {
    try {
      const data = await apiGoogleAuth(credential);
      const signedInUser = {
        email: data.email,
        name: data.name || data.full_name || 'Researcher',
        mobile: data.mobile,
        require_mobile: data.require_mobile,
      };
      const nextOnboarded = data.require_mobile
        ? false
        : await refreshOnboardingStatus(signedInUser.email);

      setUser(signedInUser);
      trackEvent('auth_google_login_success', {
        email: signedInUser.email,
        name: signedInUser.name,
        require_mobile: String(!!signedInUser.require_mobile),
        onboarded: String(nextOnboarded),
      });

      showToast('Successfully signed in with Google.', 'success');
      return { ...data, onboarded: nextOnboarded };
    } catch (err: any) {
      trackEvent('auth_google_login_failed', {
        error_type: err?.name || 'Error',
      });
      showToast(err.message || 'Google Auth failed.', 'error');
      throw err;
    }
  }, [refreshOnboardingStatus, showToast]);

  const logout = useCallback(async () => {
    try {
      const activeUser = user;
      await apiLogout();
      setUser(null);
      setOnboarded(false);
      trackEvent('auth_logout', {
        email: activeUser?.email || '',
        name: activeUser?.name || '',
      });
      showToast('Logged out successfully.', 'info');
    } catch (err) {
      console.error('Logout error', err);
      setUser(null);
      setOnboarded(false);
    }
  }, [setOnboarded, showToast]);

  const updateUserMobile = useCallback((mobile: string) => {
    setUser((currentUser) => {
      if (currentUser) {
        const updatedUser = { ...currentUser, mobile, require_mobile: false };
        setCachedUser(updatedUser);
        return updatedUser;
      }
      return currentUser;
    });
  }, []);

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  const isAuthenticated = !!user;

  return (
    <AuthContext.Provider
      value={{
        user,
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

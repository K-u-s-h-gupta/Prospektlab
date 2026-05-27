import React, { createContext, useContext, useState, useEffect } from 'react';
import { getAuthToken, apiLogin, apiSignup, apiLogout, apiGoogleAuth, getPortfolioMirror } from '../api/client';

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
  login: (email: string, password: string) => Promise<any>;
  signup: (name: string, email: string, password: string, mobile: string, verificationCode: string) => Promise<any>;
  googleLogin: (credential: string) => Promise<any>;
  logout: () => Promise<void>;
  showToast: (message: string, type?: 'success' | 'error' | 'info') => void;
  updateUserMobile: (mobile: string) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    const localToken = getAuthToken();
    const localUser = localStorage.getItem('prospektlab_user');

    if (localToken && localUser) {
      try {
        setToken(localToken);
        setUser(JSON.parse(localUser));

        // Auto-detect onboarding status from portfolio holdings
        getPortfolioMirror().then((data) => {
          if (data && (data.count > 0 || data.status === 'MIRROR_SYNCHRONIZED')) {
            localStorage.setItem('prospektlab_onboarded', 'true');
          }
        }).catch((err) => {
          console.error('Failed to auto-resolve portfolio mirror state:', err);
        });
      } catch (e) {
        console.error('Failed to parse cached user', e);
        localStorage.removeItem('prospektlab_token');
        localStorage.removeItem('prospektlab_user');
      }
    }
    setIsLoading(false);
  }, []);

  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    const id = Date.now().toString() + Math.random().toString(36).substr(2, 5);
    setToasts((prev) => [...prev, { id, message, type }]);
    
    // Automatically remove toast after 4 seconds
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  };

  const login = async (email: string, password: string) => {
    setIsLoading(true);
    try {
      const data = await apiLogin(email, password);

      // Check if user has already uploaded a portfolio BEFORE triggering authentication redirects
      try {
        const portMirror = await getPortfolioMirror();
        if (portMirror && (portMirror.count > 0 || portMirror.status === 'MIRROR_SYNCHRONIZED')) {
          localStorage.setItem('prospektlab_onboarded', 'true');
        }
      } catch (e) {
        console.error('Failed to fetch portfolio status on login:', e);
      }

      setToken(data.token);
      setUser({
        email: data.user?.email || email,
        name: data.user?.name || 'Researcher',
      });

      showToast('Successfully signed in.', 'success');
      return data;
    } catch (err: any) {
      showToast(err.message || 'Login failed.', 'error');
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const signup = async (name: string, email: string, password: string, mobile: string, verificationCode: string) => {
    setIsLoading(true);
    try {
      const data = await apiSignup(name, email, password, mobile, verificationCode);
      setToken(data.token);
      setUser({
        email: data.user?.email || email,
        name: data.user?.name || name,
      });
      showToast('Account created successfully!', 'success');
      return data;
    } catch (err: any) {
      showToast(err.message || 'Signup failed.', 'error');
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const googleLogin = async (credential: string) => {
    setIsLoading(true);
    try {
      const data = await apiGoogleAuth(credential);

      // Check if user has already uploaded a portfolio BEFORE triggering authentication redirects
      try {
        const portMirror = await getPortfolioMirror();
        if (portMirror && (portMirror.count > 0 || portMirror.status === 'MIRROR_SYNCHRONIZED')) {
          localStorage.setItem('prospektlab_onboarded', 'true');
        }
      } catch (e) {
        console.error('Failed to fetch portfolio status on Google login:', e);
      }

      setToken(data.token);
      setUser({
        email: data.email,
        name: data.name || data.full_name || 'Researcher',
        mobile: data.mobile,
        require_mobile: data.require_mobile,
      });

      showToast('Successfully signed in with Google.', 'success');
      return data;
    } catch (err: any) {
      showToast(err.message || 'Google Auth failed.', 'error');
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const logout = async () => {
    setIsLoading(true);
    try {
      await apiLogout();
      setToken(null);
      setUser(null);
      showToast('Logged out successfully.', 'info');
    } catch (err) {
      console.error('Logout error', err);
      // Fallback clean local states
      localStorage.removeItem('prospektlab_token');
      localStorage.removeItem('prospektlab_user');
      localStorage.removeItem('prospektlab_onboarded');
      setToken(null);
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  };

  const updateUserMobile = (mobile: string) => {
    if (user) {
      const updatedUser = { ...user, mobile, require_mobile: false };
      setUser(updatedUser);
      localStorage.setItem('prospektlab_user', JSON.stringify(updatedUser));
    }
  };

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
        login,
        signup,
        googleLogin,
        logout,
        showToast,
        updateUserMobile,
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

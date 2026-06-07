import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { CheckCircle, MessageCircle, Sparkles, Users, X } from 'lucide-react';
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

const WHATSAPP_INVITE_URL = 'https://chat.whatsapp.com/Bpo5Bt5tVveGYGEVawkcUu';
const WHATSAPP_JOINED_KEY = 'prospektlab_whatsapp_joined';
const WHATSAPP_SNOOZE_UNTIL_KEY = 'prospektlab_whatsapp_invite_snooze_until';
const WHATSAPP_SNOOZE_MS = 48 * 60 * 60 * 1000;

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [onboarded, setOnboardedState] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState(true);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [showWhatsAppInvite, setShowWhatsAppInvite] = useState(false);

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

  const hasJoinedWhatsAppCommunity = useCallback(() => {
    return localStorage.getItem(WHATSAPP_JOINED_KEY) === 'true';
  }, []);

  const closeWhatsAppInvite = useCallback(() => {
    localStorage.setItem(WHATSAPP_SNOOZE_UNTIL_KEY, String(Date.now() + WHATSAPP_SNOOZE_MS));
    setShowWhatsAppInvite(false);
  }, []);

  const joinWhatsAppCommunity = useCallback(() => {
    localStorage.setItem(WHATSAPP_JOINED_KEY, 'true');
    localStorage.removeItem(WHATSAPP_SNOOZE_UNTIL_KEY);
    window.open(WHATSAPP_INVITE_URL, '_blank', 'noopener,noreferrer');
    setShowWhatsAppInvite(false);
  }, []);

  useEffect(() => {
    if (!showWhatsAppInvite) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeWhatsAppInvite();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [closeWhatsAppInvite, showWhatsAppInvite]);

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
      if (!hasJoinedWhatsAppCommunity()) {
        localStorage.removeItem(WHATSAPP_SNOOZE_UNTIL_KEY);
        setShowWhatsAppInvite(true);
      }
      return { ...data, onboarded: false };
    } catch (err: any) {
      trackEvent('auth_signup_failed', {
        email,
        error_type: err?.name || 'Error',
      });
      showToast(err.message || 'Signup failed.', 'error');
      throw err;
    }
  }, [hasJoinedWhatsAppCommunity, persistOnboarded, showToast]);

  const googleLogin = useCallback(async (credential: string) => {
    try {
      const data = await apiGoogleAuth(credential);
      const hasMobile = !!data.mobile;
      const requireMobile = data.require_mobile ?? !hasMobile;
      const signedInUser = {
        email: data.email,
        name: data.name || data.full_name || 'Researcher',
        mobile: data.mobile,
        require_mobile: requireMobile,
      };
      const nextOnboarded = requireMobile
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
      return { ...data, require_mobile: requireMobile, onboarded: nextOnboarded };
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
      setShowWhatsAppInvite(false);
      trackEvent('auth_logout', {
        email: activeUser?.email || '',
        name: activeUser?.name || '',
      });
      showToast('Logged out successfully.', 'info');
    } catch (err) {
      console.error('Logout error', err);
      setUser(null);
      setOnboarded(false);
      setShowWhatsAppInvite(false);
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

      {showWhatsAppInvite && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="whatsapp-invite-title"
          onClick={closeWhatsAppInvite}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 10000,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
            background: 'rgba(2, 6, 23, 0.76)',
            backdropFilter: 'blur(14px)',
            WebkitBackdropFilter: 'blur(14px)',
          }}
        >
          <style>{`
            @keyframes whatsappInviteIn {
              from { opacity: 0; transform: translateY(18px) scale(0.96); }
              to { opacity: 1; transform: translateY(0) scale(1); }
            }
            @keyframes whatsappInviteFloat {
              0%, 100% { transform: translateY(0); }
              50% { transform: translateY(-6px); }
            }
            @keyframes whatsappInvitePulse {
              0%, 100% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.25); }
              50% { box-shadow: 0 0 0 10px rgba(52, 211, 153, 0); }
            }
            @media (max-width: 520px) {
              .whatsapp-invite-card { padding: 22px 18px !important; }
              .whatsapp-invite-actions { flex-direction: column !important; }
              .whatsapp-invite-actions button { width: 100% !important; justify-content: center !important; }
            }
          `}</style>
          <div
            className="whatsapp-invite-card"
            onClick={(event) => event.stopPropagation()}
            style={{
              width: 'min(520px, 100%)',
              position: 'relative',
              overflow: 'hidden',
              padding: '30px',
              borderRadius: '24px',
              border: '1px solid rgba(52, 211, 153, 0.26)',
              background:
                'radial-gradient(circle at 18% 0%, rgba(52, 211, 153, 0.16), transparent 34%), radial-gradient(circle at 92% 18%, rgba(56, 189, 248, 0.12), transparent 32%), rgba(15, 23, 42, 0.96)',
              boxShadow: '0 28px 90px rgba(0, 0, 0, 0.58), inset 0 1px 0 rgba(255, 255, 255, 0.06)',
              animation: 'whatsappInviteIn 0.35s cubic-bezier(0.16, 1, 0.3, 1) forwards',
            }}
          >
            <button
              type="button"
              aria-label="Close WhatsApp invite"
              onClick={closeWhatsAppInvite}
              style={{
                position: 'absolute',
                top: 14,
                right: 14,
                width: 34,
                height: 34,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                borderRadius: 10,
                border: '1px solid rgba(148, 163, 184, 0.16)',
                background: 'rgba(15, 23, 42, 0.7)',
                color: 'var(--text-secondary)',
                padding: 0,
              }}
            >
              <X size={16} />
            </button>

            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 22 }}>
              <div
                style={{
                  width: 54,
                  height: 54,
                  borderRadius: 18,
                  background: 'linear-gradient(135deg, rgba(52, 211, 153, 0.22), rgba(56, 189, 248, 0.13))',
                  border: '1px solid rgba(52, 211, 153, 0.32)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'var(--profit)',
                  animation: 'whatsappInviteFloat 3.6s ease-in-out infinite',
                }}
              >
                <MessageCircle size={28} />
              </div>
              <div>
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginBottom: 6, color: 'var(--profit)', fontSize: 11, fontWeight: 800, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
                  <Sparkles size={12} /> New member invite
                </div>
                <h2 id="whatsapp-invite-title" style={{ margin: 0, color: 'var(--text-primary)', fontSize: 'clamp(22px, 4vw, 30px)', lineHeight: 1.12, letterSpacing: '-0.7px' }}>
                  Want the unfair edge to compound faster?
                </h2>
              </div>
            </div>

            <p style={{ margin: '0 0 18px', color: 'var(--text-secondary)', fontSize: 15, lineHeight: 1.72 }}>
              Join our private WhatsApp circle where early ProspektLab users share sharp market questions, useful prompts, product drops, and the mistakes worth avoiding before they cost real money.
            </p>

            <div style={{ display: 'grid', gap: 10, marginBottom: 22 }}>
              {[
                'Get practical examples you can use inside Arthik today.',
                'See what serious retail investors are researching this week.',
                'Ask for help when your first portfolio audit raises questions.',
              ].map((item) => (
                <div key={item} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                  <CheckCircle size={16} color="var(--profit)" style={{ marginTop: 2, flexShrink: 0 }} />
                  <span style={{ color: 'var(--text-primary)', fontSize: 13.5, lineHeight: 1.55 }}>{item}</span>
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', borderRadius: 14, border: '1px solid rgba(56, 189, 248, 0.15)', background: 'rgba(56, 189, 248, 0.06)', marginBottom: 22 }}>
              <Users size={17} color="var(--accent-cyan)" style={{ flexShrink: 0 }} />
              <span style={{ color: 'var(--text-secondary)', fontSize: 12.5, lineHeight: 1.5 }}>
                Best time to join is now, while the group is still small enough for real conversations.
              </span>
            </div>

            <div className="whatsapp-invite-actions" style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
              <button
                type="button"
                onClick={joinWhatsAppCommunity}
                style={{
                  flex: '1 1 auto',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 9,
                  border: 'none',
                  borderRadius: 12,
                  padding: '13px 18px',
                  background: 'linear-gradient(135deg, #34D399, #22C55E)',
                  color: '#052e1a',
                  fontSize: 14,
                  fontWeight: 800,
                  boxShadow: '0 14px 32px rgba(34, 197, 94, 0.22)',
                  animation: 'whatsappInvitePulse 2.4s ease-in-out infinite',
                }}
              >
                <MessageCircle size={17} /> Join the WhatsApp circle
              </button>
              <button
                type="button"
                onClick={closeWhatsAppInvite}
                style={{
                  flex: '0 0 auto',
                  border: '1px solid rgba(148, 163, 184, 0.16)',
                  borderRadius: 12,
                  padding: '13px 16px',
                  background: 'rgba(15, 23, 42, 0.64)',
                  color: 'var(--text-secondary)',
                  fontSize: 13,
                  fontWeight: 700,
                }}
              >
                I will explore first
              </button>
            </div>
          </div>
        </div>
      )}
      
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

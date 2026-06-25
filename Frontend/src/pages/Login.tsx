import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Logo } from '../components/layout/Logo';
import { Mail, Lock, User as UserIcon, Phone, ShieldCheck, Eye, EyeOff, Loader2 } from 'lucide-react';
import { apiForgotPassword, apiResetPassword, apiUpdateMobile } from '../api/client';

export const Login: React.FC<{ initialTab?: 'login' | 'signup' }> = ({ initialTab = 'login' }) => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const redirectTo = searchParams.get('redirect') || '';
  const { user, login, signup, googleLogin, updateUserMobile, logout, showToast, isAuthenticated, onboarded, setOnboarded, refreshOnboardingStatus, syncLocalPortfolio } = useAuth();

  // Tab State
  const [activeTab, setActiveTab] = useState<'login' | 'signup'>(initialTab);
  
  // Form values
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(true);
  
  // Signup specific values
  const [name, setName] = useState('');
  const [mobile, setMobile] = useState('');

  // Forgot password specific values
  const [forgotMode, setForgotMode] = useState(false);
  const [resetCode, setResetCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [resetCodeSent, setResetCodeSent] = useState(false);

  // UI state
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSendingCode, setIsSendingCode] = useState(false);

  // Google Auth mobile setup state
  const [requireMobileMode, setRequireMobileMode] = useState(false);
  const [mobileInput, setMobileInput] = useState('');
  const [isUpdatingMobile, setIsUpdatingMobile] = useState(false);
  const [isGoogleLoaded, setIsGoogleLoaded] = useState(false);

  // Determine where to send the user after successful authentication.
  // For /dashboard redirects, only sync manual local holdings if the account
  // does not already have a mirrored portfolio.
  const resolvePostAuthRedirect = async (nextOnboarded: boolean, emailOverride?: string): Promise<string> => {
    let resolvedOnboarded = nextOnboarded;
    if (!resolvedOnboarded) {
      resolvedOnboarded = await refreshOnboardingStatus(emailOverride || user?.email);
    }

    if (redirectTo) {
      if (redirectTo === '/dashboard' && !resolvedOnboarded) {
        const synced = await syncLocalPortfolio();
        if (synced) {
          return '/dashboard';
        }
        const refreshed = await refreshOnboardingStatus(emailOverride || user?.email);
        return refreshed ? '/dashboard' : '/get-started';
      }
      return redirectTo;
    }
    return resolvedOnboarded ? '/dashboard' : '/get-started';
  };

  // Sync requireMobileMode with user state on mount/change
  useEffect(() => {
    if (user?.require_mobile) {
      setRequireMobileMode(true);
    }
  }, [user]);

  // Redirect if already authenticated and doesn't require completing profile
  useEffect(() => {
    if (isAuthenticated && !user?.require_mobile) {
      const target = redirectTo || (onboarded ? '/dashboard' : '/get-started');
      navigate(target, { replace: true });
    }
  }, [isAuthenticated, navigate, onboarded, user, redirectTo]);

  // Google OAuth GIS initialization
  useEffect(() => {
    // Inject Google GIS script if not present
    if (!document.getElementById('google-gis-script')) {
      const script = document.createElement('script');
      script.id = 'google-gis-script';
      script.src = 'https://accounts.google.com/gsi/client';
      script.async = true;
      script.defer = true;
      document.body.appendChild(script);
    }

    const initGoogleGis = () => {
      const g = (window as any).google;
      if (g?.accounts?.id) {
        g.accounts.id.initialize({
          client_id: '140159239234-l6g7cqb4okkkb1g8g5fsbs6oiqmgpk5n.apps.googleusercontent.com',
          callback: async (response: any) => {
            if (isSubmitting) return;
            setIsSubmitting(true);
            try {
              const res = await googleLogin(response.credential);
              if (res.require_mobile) {
                setRequireMobileMode(true);
              } else {
                const target = await resolvePostAuthRedirect(Boolean(res?.onboarded), res?.email || user?.email);
                navigate(target, { replace: true });
              }
            } catch (err: any) {
              showToast(err.message || 'Google Auth failed', 'error');
            } finally {
              setIsSubmitting(false);
            }
          }
        });
      }
    };

    const g = (window as any).google;
    if (g?.accounts?.id) {
      setIsGoogleLoaded(true);
      initGoogleGis();
    } else {
      const checkInterval = setInterval(() => {
        const currentG = (window as any).google;
        if (currentG?.accounts?.id) {
          setIsGoogleLoaded(true);
          initGoogleGis();
          clearInterval(checkInterval);
        }
      }, 500);
      return () => clearInterval(checkInterval);
    }
  }, [navigate, showToast, googleLogin]);

  // Google Sign-In Button Ref renderer
  const googleBtnOverlayRef = React.useCallback((node: HTMLDivElement | null) => {
    if (node) {
      const renderGoogleBtn = () => {
        const g = (window as any).google;
        if (g?.accounts?.id) {
          g.accounts.id.renderButton(node, {
            theme: "filled_black",
            size: "large",
            width: Math.min(368, node.parentElement?.offsetWidth || 368),
            type: "standard",
            text: activeTab === 'login' ? 'signin_with' : 'signup_with',
            shape: "rectangular"
          });
        }
      };

      const g = (window as any).google;
      if (g?.accounts?.id) {
        renderGoogleBtn();
      } else {
        const interval = setInterval(() => {
          const currentG = (window as any).google;
          if (currentG?.accounts?.id) {
            renderGoogleBtn();
            clearInterval(interval);
          }
        }, 100);
        setTimeout(() => clearInterval(interval), 5000);
      }
    }
  }, [activeTab]);

  // Password strength checker helper
  const checkPasswordStrength = (pass: string): { score: number; label: string; color: string } => {
    if (!pass) return { score: 0, label: 'None', color: 'transparent' };
    let score = 0;
    if (pass.length >= 8) score += 1;
    if (/[a-z]/.test(pass) && /[A-Z]/.test(pass)) score += 1;
    if (/\d/.test(pass)) score += 1;
    if (/[^a-zA-Z\d]/.test(pass)) score += 1;
    if (pass.length >= 12) score += 1;

    const mapping = [
      { score: 0, label: 'Very Weak', color: '#f87171' },
      { score: 1, label: 'Weak', color: '#f87171' },
      { score: 2, label: 'Fair', color: '#fb923c' },
      { score: 3, label: 'Good', color: '#facc15' },
      { score: 4, label: 'Strong', color: '#60a5fa' },
      { score: 5, label: 'Excellent', color: '#34d399' }
    ];
    return mapping[score];
  };

  const strength = checkPasswordStrength(password);
  const resetStrength = checkPasswordStrength(newPassword);

  // Send forgot password reset email
  const handleSendResetCode = async () => {
    if (!email || !email.includes('@')) {
      showToast('Please enter a valid email address.', 'error');
      return;
    }
    setIsSendingCode(true);
    try {
      const data = await apiForgotPassword(email);
      setResetCodeSent(true);
      showToast(data.message || 'Reset code sent to your email.', 'success');
    } catch (err: any) {
      showToast(err.message || 'Failed to send reset code.', 'error');
    } finally {
      setIsSendingCode(false);
    }
  };

  // Submit Login
  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) return;
    setIsSubmitting(true);
    try {
      const res = await login(email, password, remember);
      const target = await resolvePostAuthRedirect(Boolean(res?.onboarded), email);
      navigate(target, { replace: true });
    } catch (err) {
      // handled in context
    } finally {
      setIsSubmitting(false);
    }
  };

  // Submit Signup
  const handleSignupSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !email || !password || !mobile) {
      showToast('Please fill all fields.', 'error');
      return;
    }
    if (strength.score < 3) {
      showToast('Password is too weak. Aim for at least "Good".', 'error');
      return;
    }
    setIsSubmitting(true);
    try {
      const res = await signup(name, email, password, mobile);
      setOnboarded(false);
      const target = await resolvePostAuthRedirect(Boolean(res?.onboarded), email);
      navigate(target, { replace: true });
    } catch (err) {
      // handled in context
    } finally {
      setIsSubmitting(false);
    }
  };

  // Submit Password Reset
  const handleResetSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !resetCode || !newPassword) return;
    if (resetStrength.score < 3) {
      showToast('Password is too weak. Aim for at least "Good".', 'error');
      return;
    }
    setIsSubmitting(true);
    try {
      await apiResetPassword(email, resetCode, newPassword);
      showToast('Password updated successfully. Please log in.', 'success');
      setForgotMode(false);
      setResetCodeSent(false);
      setResetCode('');
      setNewPassword('');
    } catch (err: any) {
      showToast(err.message || 'Failed to reset password.', 'error');
    } finally {
      setIsSubmitting(false);
    }
  };

  // Submit Google Auth Mobile Number Update
  const handleMobileSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!mobileInput || mobileInput.length !== 10) {
      showToast('Please enter a valid 10-digit mobile number.', 'error');
      return;
    }
    const formattedMobile = '+91' + mobileInput;
    const userEmail = user?.email;
    setIsUpdatingMobile(true);
    try {
      await apiUpdateMobile(formattedMobile);
      updateUserMobile(formattedMobile);
      const nextOnboarded = await refreshOnboardingStatus(userEmail);
      showToast('Profile completed successfully!', 'success');
      setRequireMobileMode(false);
      const target = redirectTo || (nextOnboarded ? '/dashboard' : '/get-started');
      navigate(target, { replace: true });
    } catch (err: any) {
      showToast(err.message || 'Failed to update mobile number.', 'error');
    } finally {
      setIsUpdatingMobile(false);
    }
  };

  // Google login trigger for the fallback button
  const handleGoogleSocialClick = async () => {
    const google = (window as Window & {
      google?: { accounts?: { id?: { prompt?: () => void } } };
    }).google;
    if (google?.accounts?.id?.prompt) {
      // GIS is loaded, trigger the popup
      google.accounts.id.prompt();
    } else {
      // GIS not available — likely blocked by ad blocker or network issue
      showToast('Google Sign-In is not available. Please check your ad blocker or try email login.', 'error');
    }
  };

  // Render Inline Complete Profile (Mobile Number) Layout
  if (requireMobileMode) {
    return (
      <div className="auth-container">
        <div className="auth-card animate-fade-in-up">
          <div className="auth-header">
            <Logo size={48} />
            <h2 className="auth-logo text-gradient" style={{ marginTop: '16px' }}>Complete Profile</h2>
            <p className="auth-subtitle">Please enter your mobile number to complete registration and secure your account.</p>
          </div>

          <form onSubmit={handleMobileSubmit}>
            <div className="auth-form-group">
              <label className="auth-label">Mobile Number</label>
              <div className="auth-input-wrapper" style={{ position: 'relative' }}>
                <Phone className="auth-input-icon" />
                <span style={{ position: 'absolute', left: '38px', top: '50%', transform: 'translateY(-50%)', fontSize: '13.5px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>+91</span>
                <input
                  type="tel"
                  className="auth-input text-mono"
                  placeholder="98765 43210"
                  value={mobileInput}
                  onChange={(e) => setMobileInput(e.target.value.replace(/\D/g, '').slice(0, 10))}
                  style={{ paddingLeft: '72px' }}
                  disabled={isUpdatingMobile}
                  required
                />
              </div>
            </div>

            <button type="submit" className="primary" style={{ width: '100%', padding: '12px', marginTop: '16px' }} disabled={isUpdatingMobile}>
              {isUpdatingMobile ? (
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
                  <Loader2 className="animate-spin-custom" size={16} /> Saving...
                </span>
              ) : (
                'Verify & Continue'
              )}
            </button>
          </form>

          <div style={{ marginTop: '20px', textAlign: 'center' }}>
            <button
              onClick={async () => {
                setRequireMobileMode(false);
                setMobileInput('');
                await logout();
              }}
              style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', fontSize: '13px' }}
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Render Inline Forgot Password Layout
  if (forgotMode) {
    return (
      <div className="auth-container">
        <div className="auth-card animate-fade-in-up">
          <div className="auth-header">
            <Logo size={48} />
            <h2 className="auth-logo text-gradient" style={{ marginTop: '16px' }}>Reset Password</h2>
            <p className="auth-subtitle">Verify your identity to choose a new password.</p>
          </div>

          <form onSubmit={handleResetSubmit}>
            <div className="auth-form-group">
              <label className="auth-label">Email Address</label>
              <div className="auth-input-wrapper">
                <Mail className="auth-input-icon" />
                <input
                  type="email"
                  className="auth-input"
                  placeholder="name@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={resetCodeSent || isSubmitting}
                  required
                />
                {!resetCodeSent && (
                  <button
                    type="button"
                    className="auth-input-right"
                    onClick={handleSendResetCode}
                    disabled={isSendingCode || !email}
                  >
                    {isSendingCode ? <Loader2 className="animate-spin" size={14} /> : 'Send Code'}
                  </button>
                )}
              </div>
            </div>

            {resetCodeSent && (
              <>
                <div className="auth-form-group">
                  <label className="auth-label">6-Digit Reset Code</label>
                  <div className="auth-input-wrapper">
                    <ShieldCheck className="auth-input-icon" />
                    <input
                      type="text"
                      maxLength={6}
                      className="auth-input text-mono"
                      placeholder="123456"
                      value={resetCode}
                      onChange={(e) => setResetCode(e.target.value)}
                      disabled={isSubmitting}
                      required
                    />
                  </div>
                </div>

                <div className="auth-form-group">
                  <label className="auth-label">New Password</label>
                  <div className="auth-input-wrapper">
                    <Lock className="auth-input-icon" />
                    <input
                      type={showPassword ? 'text' : 'password'}
                      className="auth-input"
                      placeholder="••••••••"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      disabled={isSubmitting}
                      required
                    />
                    <button
                      type="button"
                      className="auth-input-right"
                      onClick={() => setShowPassword(!showPassword)}
                    >
                      {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                    </button>
                  </div>
                </div>

                {newPassword && (
                  <div className="strength-container animate-fade-in-up">
                    <div className="strength-bar-bg">
                      {[1, 2, 3, 4, 5].map((index) => (
                        <div
                          key={index}
                          className="strength-bar-segment"
                          style={{
                            backgroundColor: index <= resetStrength.score ? resetStrength.color : 'transparent'
                          }}
                        />
                      ))}
                    </div>
                    <div className="strength-text" style={{ color: resetStrength.color }}>
                      Password Strength: {resetStrength.label}
                    </div>
                  </div>
                )}

                <button type="submit" className="primary" style={{ width: '100%', padding: '12px', marginTop: '10px' }} disabled={isSubmitting}>
                  {isSubmitting ? (
                    <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
                      <Loader2 className="animate-spin-custom" size={16} /> Updating...
                    </span>
                  ) : (
                    'Update Password'
                  )}
                </button>
              </>
            )}
          </form>

          <div style={{ marginTop: '20px', textAlign: 'center' }}>
            <button
              onClick={() => {
                setForgotMode(false);
                setResetCodeSent(false);
              }}
              style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', fontSize: '13px' }}
            >
              ← Back to Sign In
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Render Login & Signup tabbed layout
  return (
    <div className="auth-container">
      <div className="auth-card animate-fade-in-up">
        <div className="auth-header">
          <Logo size={48} />
          <h2 className="auth-logo text-gradient" style={{ marginTop: '16px' }}>ProspektLab</h2>
          <p className="auth-subtitle">India's quantitative research & portfolio intelligence terminal</p>
        </div>

        {/* Tab Selector */}
        <div className="auth-tabs">
          <button
            className={`auth-tab ${activeTab === 'login' ? 'auth-tab-active' : ''}`}
            onClick={() => {
              setActiveTab('login');
              setPassword('');
            }}
          >
            Sign In
          </button>
          <button
            className={`auth-tab ${activeTab === 'signup' ? 'auth-tab-active' : ''}`}
            onClick={() => {
              setActiveTab('signup');
              setPassword('');
            }}
          >
            Create Account
          </button>
        </div>

        {activeTab === 'login' ? (
          /* LOGIN FORM */
          <form onSubmit={handleLoginSubmit}>
            <div className="auth-form-group">
              <label className="auth-label">Email Address</label>
              <div className="auth-input-wrapper">
                <Mail className="auth-input-icon" />
                <input
                  type="email"
                  className="auth-input"
                  placeholder="name@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={isSubmitting}
                  required
                />
              </div>
            </div>

            <div className="auth-form-group">
              <label className="auth-label">Password</label>
              <div className="auth-input-wrapper">
                <Lock className="auth-input-icon" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  className="auth-input"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isSubmitting}
                  required
                />
                <button
                  type="button"
                  className="auth-input-right"
                  onClick={() => setShowPassword(!showPassword)}
                >
                  {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>

            <div className="auth-options">
              <label className="auth-checkbox-label">
                <input
                  type="checkbox"
                  className="auth-checkbox"
                  checked={remember}
                  onChange={(e) => setRemember(e.target.checked)}
                />
                Keep me signed in
              </label>
              <button
                type="button"
                className="auth-link"
                style={{ background: 'transparent', border: 'none', padding: 0 }}
                onClick={() => {
                  setForgotMode(true);
                  setResetCodeSent(false);
                }}
              >
                Forgot password?
              </button>
            </div>

            <button type="submit" className="primary" style={{ width: '100%', padding: '12px' }} disabled={isSubmitting}>
              {isSubmitting ? (
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
                  <Loader2 className="animate-spin-custom" size={16} /> Signing in...
                </span>
              ) : (
                'Sign In →'
              )}
            </button>
          </form>
        ) : (
          /* SIGNUP FORM */
          <form onSubmit={handleSignupSubmit}>
            <div className="auth-form-group">
              <label className="auth-label">Full Name</label>
              <div className="auth-input-wrapper">
                <UserIcon className="auth-input-icon" />
                <input
                  type="text"
                  className="auth-input"
                  placeholder="Kush Gupta"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  disabled={isSubmitting}
                  required
                />
              </div>
            </div>

            <div className="auth-form-group">
              <label className="auth-label">Email Address</label>
              <div className="auth-input-wrapper">
                <Mail className="auth-input-icon" />
                <input
                  type="email"
                  className="auth-input"
                  placeholder="name@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  disabled={isSubmitting}
                  required
                />
              </div>
            </div>

            <div className="auth-form-group">
              <label className="auth-label">Mobile Number</label>
              <div className="auth-input-wrapper">
                <Phone className="auth-input-icon" />
                <input
                  type="tel"
                  className="auth-input text-mono"
                  placeholder="+91 98765 43210"
                  value={mobile}
                  onChange={(e) => setMobile(e.target.value)}
                  disabled={isSubmitting}
                  required
                />
              </div>
            </div>

            <div className="auth-form-group">
              <label className="auth-label">Password</label>
              <div className="auth-input-wrapper">
                <Lock className="auth-input-icon" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  className="auth-input"
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isSubmitting}
                  required
                />
                <button
                  type="button"
                  className="auth-input-right"
                  onClick={() => setShowPassword(!showPassword)}
                >
                  {showPassword ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
            </div>

            {password && (
              <div className="strength-container animate-fade-in-up">
                <div className="strength-bar-bg">
                  {[1, 2, 3, 4, 5].map((index) => (
                    <div
                      key={index}
                      className="strength-bar-segment"
                      style={{
                        backgroundColor: index <= strength.score ? strength.color : 'transparent'
                      }}
                    />
                  ))}
                </div>
                <div className="strength-text" style={{ color: strength.color }}>
                  Password Strength: {strength.label}
                </div>
              </div>
            )}

            <button type="submit" className="primary" style={{ width: '100%', padding: '12px', marginTop: '10px' }} disabled={isSubmitting}>
              {isSubmitting ? (
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
                  <Loader2 className="animate-spin-custom" size={16} /> Creating account...
                </span>
              ) : (
                'Create Account →'
              )}
            </button>
          </form>
        )}

        {/* Third-Party Authentication */}
        <div className="auth-divider">or continue with</div>

        <div className={isSubmitting ? 'google-auth-shell disabled' : 'google-auth-shell'}>
          <button
            type="button"
            className="google-auth-visible"
            onClick={!isGoogleLoaded ? handleGoogleSocialClick : undefined}
            disabled={isSubmitting}
            tabIndex={isGoogleLoaded ? -1 : 0}
            aria-hidden={isGoogleLoaded ? true : undefined}
          >
            <span className="google-auth-mark" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path fill="#4285F4" d="M23.49 12.27c0-.81-.07-1.59-.2-2.34H12v4.44h6.45c-.28 1.48-1.12 2.74-2.38 3.59l3.71 2.87c2.17-2 3.71-4.94 3.71-8.56z" />
                <path fill="#34A853" d="M12 22.96c3.24 0 5.97-1.07 7.96-2.91l-3.71-2.87c-1.03.69-2.35 1.1-4.25 1.1-3.1 0-5.73-2.34-6.67-5.49l-3.81 2.95C3.44 20.33 7.37 22.96 12 22.96z" />
                <path fill="#FBBC05" d="M5.33 12.79c-.23-.68-.36-1.41-.36-2.16s.13-1.48.36-2.16L1.52 5.52C.72 7.12.27 8.91.27 10.79s.45 3.67 1.25 5.27l3.81-3.27z" />
                <path fill="#EA4335" d="M12 5.04c1.67 0 3.17.58 4.35 1.71l3.25-3.25C17.65 1.58 15.01 1 12 1 7.37 1 3.44 3.63 1.57 7.43l3.81 2.95C6.27 7.38 8.9 5.04 12 5.04z" />
              </svg>
            </span>
            <span>{activeTab === 'login' ? 'Sign in with Google' : 'Sign up with Google'}</span>
            <span className="google-auth-arrow" aria-hidden="true">→</span>
          </button>

          {isGoogleLoaded && (
            <div
              key={activeTab}
              ref={googleBtnOverlayRef}
              className="google-native-overlay"
              aria-label={activeTab === 'login' ? 'Sign in with Google' : 'Sign up with Google'}
            />
          )}
        </div>

        {/* Skip to Dashboard - login is optional */}
        <div style={{ marginTop: '20px', textAlign: 'center', borderTop: '1px solid rgba(255, 255, 255, 0.06)', paddingTop: '16px' }}>
          <button
            type="button"
            onClick={() => navigate('/dashboard/overview')}
            style={{
              background: 'rgba(56, 189, 248, 0.06)',
              border: '1px solid rgba(56, 189, 248, 0.18)',
              color: 'var(--accent-cyan)',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              padding: '10px 20px',
              borderRadius: '10px',
              width: '100%',
              transition: 'all 0.2s ease',
              letterSpacing: '0.01em',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(56, 189, 248, 0.12)'; e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.35)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(56, 189, 248, 0.06)'; e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.18)'; }}
          >
            Explore the dashboard — no account needed →
          </button>
          <p style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '10px', lineHeight: 1.5 }}>
            Sign in only to <strong style={{ color: 'var(--text-secondary)' }}>sync your portfolio across devices</strong> and unlock saved sessions. Everything else is free, anonymous, and instant.
          </p>
        </div>
      </div>
    </div>
  );
};

import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Logo } from '../components/layout/Logo';
import { Keyboard, UploadCloud, ArrowRight, TrendingUp, ShieldCheck, BadgeInfo } from 'lucide-react';
import { trackEvent } from '../telemetry';
import { APP_BETA_ACCESS_NOTE, APP_BETA_BADGE, APP_BETA_LABEL } from '../constants/beta';

interface GatewaySetupCardProps {
  embedded?: boolean;
  onClose?: () => void;
}

export const GatewaySetupCard: React.FC<GatewaySetupCardProps> = ({ embedded = false, onClose }) => {
  const navigate = useNavigate();
  const [name, setName] = useState(() => localStorage.getItem('prospektlab_username') || '');
  const [style, setStyle] = useState<'Conservative' | 'Balanced' | 'Growth'>(() => {
    const saved = localStorage.getItem('prospektlab_style');
    return (saved as any) || 'Balanced';
  });

  const styles = [
    {
      id: 'Conservative' as const,
      title: 'Conservative / Defensive',
      desc: 'Focus on index heavyweights, strong dividends, and clean debt structures.',
      icon: ShieldCheck,
    },
    {
      id: 'Balanced' as const,
      title: 'Balanced Analyst',
      desc: 'Value opportunities, PEG ratios, capital allocation, and medium-term sector expansion.',
      icon: BadgeInfo,
    },
    {
      id: 'Growth' as const,
      title: 'Growth / Momentum',
      desc: 'Emerging sectors, high-growth themes, and compounding disruptors.',
      icon: TrendingUp,
    },
  ];

  const persistProfile = () => {
    if (name.trim()) {
      localStorage.setItem('prospektlab_username', name.trim());
    }
    localStorage.setItem('prospektlab_style', style);
  };

  const handleManual = () => {
    persistProfile();
    trackEvent('onboarding_manual_selected', { style });
    navigate('/onboarding/manual');
  };

  const handleUpload = () => {
    persistProfile();
    trackEvent('onboarding_upload_selected', { style });
    navigate('/onboarding/upload');
  };

  return (
    <div className={`glass onboarding-card${embedded ? ' onboarding-card-embedded' : ''}`}>
      {embedded && onClose && (
        <div className="onboarding-card-close-row">
          <button type="button" className="onboarding-card-close" onClick={onClose}>
            Close
          </button>
        </div>
      )}

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', justifyContent: 'center' }}>
          <div style={{
            background: 'var(--gradient-brand)',
            borderRadius: '10px',
            padding: '6px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 15px rgba(56, 189, 248, 0.3)'
          }}>
            <Logo size={20} />
          </div>
          <span style={{ fontSize: '22px', fontWeight: 700, letterSpacing: '-0.5px' }} className="text-gradient">
            ProspektLab
          </span>
        </div>

        <div className="beta-inline-group" style={{ justifyContent: 'center' }}>
          <span className="beta-pill">{APP_BETA_BADGE}</span>
          <span className="beta-note">{APP_BETA_LABEL} • {APP_BETA_ACCESS_NOTE}</span>
        </div>

        <div style={{ textAlign: 'center' }}>
          <h2 style={{ fontSize: '20px', fontWeight: 600, color: 'var(--text-primary)' }}>
            Build your command center
          </h2>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px' }}>
            You are in the invite-only beta. Tell us a little about yourself, then choose how you want to set up your portfolio.
          </p>
        </div>

        {/* Profile mini-form */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '11px', color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              What should we call you?
            </label>
            <input
              type="text"
              placeholder="Your name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              style={{ fontSize: '14px', padding: '12px 14px', borderRadius: '10px' }}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '11px', color: 'var(--text-secondary)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Investing style
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
              {styles.map((s) => {
                const Icon = s.icon;
                const selected = style === s.id;
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setStyle(s.id)}
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '6px',
                      padding: '12px 8px',
                      borderRadius: '10px',
                      border: `1px solid ${selected ? 'var(--accent-cyan)' : 'rgba(255,255,255,0.06)'}`,
                      background: selected ? 'rgba(56, 189, 248, 0.06)' : 'rgba(255,255,255,0.01)',
                      color: 'var(--text-primary)',
                      textAlign: 'center',
                      cursor: 'pointer',
                      transition: 'var(--transition)'
                    }}
                  >
                    <Icon size={18} color={selected ? 'var(--accent-cyan)' : 'var(--text-secondary)'} style={{ margin: '0 auto' }} />
                    <span style={{ fontSize: '11px', fontWeight: 600, color: selected ? 'var(--accent-cyan)' : 'var(--text-primary)' }}>{s.id}</span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Choice cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px' }}>
          <button
            type="button"
            onClick={handleManual}
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
              padding: '22px 18px',
              borderRadius: '14px',
              border: '1px solid rgba(255,255,255,0.06)',
              background: 'rgba(255,255,255,0.01)',
              color: 'var(--text-primary)',
              textAlign: 'left',
              cursor: 'pointer',
              transition: 'var(--transition)'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'rgba(56, 189, 248, 0.04)';
              e.currentTarget.style.borderColor = 'rgba(56, 189, 248, 0.2)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'rgba(255,255,255,0.01)';
              e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)';
            }}
          >
            <div style={{
              background: 'rgba(56, 189, 248, 0.08)',
              color: 'var(--accent-cyan)',
              padding: '10px',
              borderRadius: '10px',
              display: 'inline-flex',
              alignSelf: 'flex-start'
            }}>
              <Keyboard size={22} />
            </div>
            <div>
              <div style={{ fontSize: '14px', fontWeight: 600 }}>Type manually</div>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                Enter your holdings quickly. Shared beta access is enough to preview your dashboard.
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--accent-cyan)', fontSize: '12px', fontWeight: 600, marginTop: 'auto' }}>
              Start typing <ArrowRight size={14} />
            </div>
          </button>

          <button
            type="button"
            onClick={handleUpload}
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
              padding: '22px 18px',
              borderRadius: '14px',
              border: '1px solid rgba(255,255,255,0.06)',
              background: 'rgba(255,255,255,0.01)',
              color: 'var(--text-primary)',
              textAlign: 'left',
              cursor: 'pointer',
              transition: 'var(--transition)'
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'rgba(129, 140, 248, 0.04)';
              e.currentTarget.style.borderColor = 'rgba(129, 140, 248, 0.2)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'rgba(255,255,255,0.01)';
              e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)';
            }}
          >
            <div style={{
              background: 'rgba(129, 140, 248, 0.08)',
              color: 'var(--accent-indigo)',
              padding: '10px',
              borderRadius: '10px',
              display: 'inline-flex',
              alignSelf: 'flex-start'
            }}>
              <UploadCloud size={22} />
            </div>
            <div>
              <div style={{ fontSize: '14px', fontWeight: 600 }}>Upload eCAS / Screenshot</div>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                Sync your real broker statement for the most accurate beta analysis.
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', color: 'var(--accent-indigo)', fontSize: '12px', fontWeight: 600, marginTop: 'auto' }}>
              Upload file <ArrowRight size={14} />
            </div>
          </button>
        </div>
    </div>
  );
};

export const GatewayPage: React.FC = () => {
  return (
    <div className="onboarding-screen animate-fade-in-up">
      <GatewaySetupCard />
    </div>
  );
};

export default GatewayPage;


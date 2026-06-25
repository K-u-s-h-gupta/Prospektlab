import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Rocket } from 'lucide-react';
import { AppShell } from '../components/layout/AppShell';
import FeatureTabs, { FeatureTabId } from '../components/layout/FeatureTabs';
import { ComingSoon } from '../components/common/ComingSoon';
import { useAuth } from '../context/AuthContext';

const pageContainerStyle: React.CSSProperties = {
  height: '100%',
  display: 'flex',
  flexDirection: 'column',
  background: 'var(--bg-deep)',
};

const contentStyle: React.CSSProperties = {
  flex: 1,
  overflowY: 'auto',
  minWidth: 0,
  padding: 'clamp(16px, 3vw, 24px) clamp(14px, 4vw, 32px) 60px',
};

export const DashboardIpoPage: React.FC = () => {
  const navigate = useNavigate();
  const { showToast } = useAuth();

  const handleFeatureTabChange = (tab: FeatureTabId) => {
    switch (tab) {
      case 'overview':
        navigate('/dashboard/overview');
        break;
      case 'portfolio':
        navigate('/dashboard/portfolio');
        break;
      case 'watchlist':
        navigate('/dashboard/watchlist');
        break;
      case 'screener':
        navigate('/dashboard/screener');
        break;
      case 'ipo':
        navigate('/dashboard/ipo');
        break;
      case 'earnings':
        navigate('/dashboard/earnings');
        break;
      case 'governance':
        navigate('/dashboard/governance');
        break;
      default:
        navigate('/dashboard/overview');
        break;
    }
  };

  return (
    <AppShell title="IPO">
      <div style={pageContainerStyle}>
        <div className="workspace-tabs-wrap">
          <FeatureTabs active="ipo" onChange={handleFeatureTabChange} />
        </div>
        <div style={contentStyle}>
          <div className="section-head">
            <div className="section-title">IPO Pipeline</div>
            <span className="section-sublabel">PREVIEW</span>
          </div>
          <div className="data-panel">
            <ComingSoon
              icon={Rocket}
              eyebrow="Primary Market Intelligence"
              title="IPO Pipeline is in final build"
              body="Live DRHP analysis across upcoming, open, and recently listed IPOs — including SME issues that most platforms skip."
              bullets={[
                'Real-time IPO tracking with GMP and subscription data',
                'AI-powered DRHP analysis and risk scoring',
                'Comprehensive coverage including SME issues',
                'Live subscription status and allotment updates',
              ]}
              onNotify={() => showToast('You are on the notify list for IPO Pipeline updates.', 'success')}
            />
          </div>
        </div>
      </div>
    </AppShell>
  );
};

export default DashboardIpoPage;

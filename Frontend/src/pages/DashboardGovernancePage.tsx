import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ShieldCheck } from 'lucide-react';
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

export const DashboardGovernancePage: React.FC = () => {
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
    <AppShell title="Governance">
      <div style={pageContainerStyle}>
        <div className="workspace-tabs-wrap">
          <FeatureTabs active="governance" onChange={handleFeatureTabChange} />
        </div>
        <div style={contentStyle}>
          <div className="section-head">
            <div className="section-title">Governance Workspace</div>
            <span className="section-sublabel">PREVIEW</span>
          </div>
          <div className="data-panel">
            <ComingSoon
              icon={ShieldCheck}
              eyebrow="Governance radar"
              title="The governance terminal is in final build"
              body="We're wiring director intelligence, pledge shifts, and regulatory alerts into one decision surface."
              bullets={[
                'Promoter pledge and holding trend trackers',
                'Board and auditor event timeline with severity tags',
                'Governance risk scorecards linked to portfolio exposure',
              ]}
              onNotify={() => showToast('You are on the notify list for Governance workspace updates.', 'success')}
            />
          </div>
        </div>
      </div>
    </AppShell>
  );
};

export default DashboardGovernancePage;

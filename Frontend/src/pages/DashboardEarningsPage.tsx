import React from 'react';
import { useNavigate } from 'react-router-dom';
import { CalendarClock } from 'lucide-react';
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

export const DashboardEarningsPage: React.FC = () => {
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
    <AppShell title="Earnings">
      <div style={pageContainerStyle}>
        <div className="workspace-tabs-wrap">
          <FeatureTabs active="earnings" onChange={handleFeatureTabChange} />
        </div>
        <div style={contentStyle}>
          <div className="section-head">
            <div className="section-title">Earnings Workspace</div>
            <span className="section-sublabel">PREVIEW</span>
          </div>
          <div className="data-panel">
            <ComingSoon
              icon={CalendarClock}
              eyebrow="Earnings intelligence"
              title="The earnings cockpit is almost ready"
              body="We're finishing the workspace for earnings dates, transcript summaries, and instant deviation flags."
              bullets={[
                'Live earnings calendar across your portfolio and watchlist',
                'Management commentary highlights with source links',
                'Beat/miss scorecards with quick portfolio impact views',
              ]}
              onNotify={() => showToast('You are on the notify list for Earnings workspace updates.', 'success')}
            />
          </div>
        </div>
      </div>
    </AppShell>
  );
};

export default DashboardEarningsPage;

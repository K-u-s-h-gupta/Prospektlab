import React from 'react';
import { useNavigate } from 'react-router-dom';
import { AppShell } from '../components/layout/AppShell';
import FeatureTabs, { FeatureTabId } from '../components/layout/FeatureTabs';
import { IpoDashboardContent } from './IpoDashboard';

const pageContainerStyle: React.CSSProperties = {
  height: '100%',
  display: 'flex',
  flexDirection: 'column',
  background: 'var(--bg-deep)',
};

export const DashboardIpoPage: React.FC = () => {
  const navigate = useNavigate();

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
        <IpoDashboardContent originPath="/dashboard/ipo" />
      </div>
    </AppShell>
  );
};

export default DashboardIpoPage;

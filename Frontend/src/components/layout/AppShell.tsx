import React from 'react';
import { Logo } from './Logo';
import { APP_BETA_BADGE } from '../../constants/beta';

interface AppShellProps {
  children: React.ReactNode;
  title: string;
  conversations?: Array<{ id: string; title: string; date: string }>;
  onDeleteConversation?: (id: string) => void;
  onClearHistory?: () => void;
  onSelectConversation?: (id: string) => void;
  onNewConversation?: () => void;
  activeConversationId?: string;
  portfolioSummary?: {
    totalValue: number;
    totalPnL: number;
    totalReturnPct: number;
  };
  tokenUsage?: any;
}

export const AppShell: React.FC<AppShellProps> = ({
  children,
}) => {
  return (
    <div className="app-container" style={{ display: 'flex', width: '100vw', height: '100vh', overflow: 'hidden' }}>
      {/* Main App Content Viewport - Full Height Cockpit */}
      <div className="main-viewport-container" style={{
        flex: 1,
        minWidth: 0,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        backgroundColor: 'transparent',
        overflow: 'hidden'
      }}>
        {/* Mobile Header Bar */}
        <header className="mobile-topbar">
          <div className="mobile-logo-container">
            <Logo size={20} />
            <span className="mobile-header-title text-gradient" style={{ letterSpacing: '0.08em', textTransform: 'uppercase' }}>Prospekt Lab</span>
            <span className="beta-pill" style={{ fontSize: 8, padding: '2px 6px' }}>{APP_BETA_BADGE}</span>
          </div>
        </header>

        <main style={{
          flex: 1,
          minHeight: 0,
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          position: 'relative'
        }}>
          {children}
        </main>
      </div>
    </div>
  );
};
export default AppShell;

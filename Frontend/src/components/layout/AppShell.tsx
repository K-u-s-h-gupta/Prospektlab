import React from 'react';
import { Sidebar } from './Sidebar';
import { Logo } from './Logo';
import { Menu } from 'lucide-react';
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
  conversations = [],
  onDeleteConversation,
  onClearHistory,
  onSelectConversation,
  onNewConversation,
  activeConversationId,
  portfolioSummary,
  tokenUsage
}) => {
  return (
    <div className="app-container" style={{ display: 'flex', width: '100vw', height: '100vh', overflow: 'hidden' }}>
      {/* Sidebar overlay backdrop for mobile */}
      <div 
        className="sidebar-overlay"
        onClick={() => document.body.classList.remove('pl-sidebar-active')}
      />

      {/* Navigation Sidebar */}
      <Sidebar
        conversations={conversations}
        onDeleteConversation={onDeleteConversation}
        onClearHistory={onClearHistory}
        onSelectConversation={onSelectConversation}
        onNewConversation={onNewConversation}
        activeConversationId={activeConversationId}
        portfolioSummary={portfolioSummary}
        tokenUsage={tokenUsage}
      />

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
          <button 
            className="mobile-hamburger-btn"
            onClick={() => document.body.classList.toggle('pl-sidebar-active')}
            title="Toggle Menu"
          >
            <Menu size={20} />
          </button>
          <div className="mobile-logo-container">
            <Logo size={20} />
            <span className="mobile-header-title text-gradient" style={{ letterSpacing: '0.08em', textTransform: 'uppercase' }}>Prospekt Lab</span>
            <span className="beta-pill" style={{ fontSize: 8, padding: '2px 6px' }}>{APP_BETA_BADGE}</span>
          </div>
          <div style={{ width: 36 }} /> {/* Balance space */}
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

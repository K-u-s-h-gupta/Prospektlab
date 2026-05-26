import React from 'react';
import { Sidebar } from './Sidebar';

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
}

export const AppShell: React.FC<AppShellProps> = ({
  children,
  conversations = [],
  onDeleteConversation,
  onClearHistory,
  onSelectConversation,
  onNewConversation,
  activeConversationId,
  portfolioSummary
}) => {
  return (
    <div className="app-container" style={{ display: 'flex', width: '100vw', height: '100vh', overflow: 'hidden' }}>
      {/* Navigation Sidebar */}
      <Sidebar
        conversations={conversations}
        onDeleteConversation={onDeleteConversation}
        onClearHistory={onClearHistory}
        onSelectConversation={onSelectConversation}
        onNewConversation={onNewConversation}
        activeConversationId={activeConversationId}
        portfolioSummary={portfolioSummary}
      />

      {/* Main App Content Viewport - Full Height Cockpit */}
      <div style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        backgroundColor: 'transparent',
        overflow: 'hidden'
      }}>
        <main style={{
          flex: 1,
          width: '100%',
          height: '100%',
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

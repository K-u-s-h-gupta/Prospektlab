import React from 'react';
import { useNavigate } from 'react-router-dom';
import { LayoutDashboard, MessageSquarePlus, Trash2, ArrowUpRight, ShieldCheck, Compass } from 'lucide-react';
import { Logo } from './Logo';

interface SidebarProps {
  conversations: Array<{ id: string; title: string; date: string }>;
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

export const Sidebar: React.FC<SidebarProps> = ({
  conversations = [],
  onDeleteConversation,
  onClearHistory,
  onSelectConversation,
  onNewConversation,
  activeConversationId,
  portfolioSummary
}) => {
  const navigate = useNavigate();

  const handleNewChatClick = () => {
    if (onNewConversation) {
      onNewConversation();
    }
  };

  const handleSelectChatClick = (id: string) => {
    if (onSelectConversation) {
      onSelectConversation(id);
    }
  };

  const hasPortfolio = portfolioSummary && portfolioSummary.totalValue > 0;

  return (
    <aside style={{
      width: '260px',
      background: 'rgba(15, 23, 42, 0.45)',
      backdropFilter: 'blur(20px)',
      WebkitBackdropFilter: 'blur(20px)',
      borderRight: '1px solid rgba(255, 255, 255, 0.06)',
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      flexShrink: 0,
      zIndex: 20
    }}>
      <div className="animate-fade-in-right" style={{
        padding: '24px 20px',
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
        cursor: 'pointer'
      }} onClick={() => navigate('/dashboard')}>
        <Logo size={24} />
        <span style={{
          fontWeight: 800,
          fontSize: '16px',
          color: 'var(--text-primary)',
          letterSpacing: '-0.3px'
        }} className="text-gradient text-gradient-animated">
          ProspektLab
        </span>
        <span className="badge badge-premium" style={{
          fontSize: '8px',
          padding: '2px 5px',
          marginLeft: 'auto'
        }}>
          PRO
        </span>
      </div>

      {/* New Chat Button */}
      <div style={{ padding: '16px 20px' }}>
        <button
          onClick={handleNewChatClick}
          className="glass-interactive"
          style={{
            width: '100%',
            color: 'var(--text-primary)',
            padding: '12px',
            borderRadius: '10px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            fontWeight: 600,
            fontSize: '13px',
            border: '1px solid rgba(255, 255, 255, 0.08)'
          }}
        >
          <MessageSquarePlus size={16} color="var(--accent-cyan)" />
          New Chat
        </button>
      </div>

      {/* Navigation */}
      <div style={{
        padding: '0 20px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: '4px'
      }}>
        <button
          onClick={() => navigate('/dashboard')}
          style={{
            width: '100%',
            background: 'rgba(255, 255, 255, 0.03)',
            border: '1px solid rgba(56, 189, 248, 0.1)',
            color: 'var(--accent-cyan)',
            padding: '10px 12px',
            borderRadius: '8px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            fontSize: '13px',
            fontWeight: 600,
            textAlign: 'left'
          }}
        >
          <LayoutDashboard size={16} />
          Dashboard
        </button>
      </div>

      {/* Conversation List */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '0 20px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px'
      }}>
        <div>
          <div style={{
            fontSize: '10px',
            color: 'var(--text-secondary)',
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            marginBottom: '8px',
            fontWeight: 700
          }}>
            History
          </div>
          
          {conversations.length === 0 ? (
            <div style={{
              fontSize: '12px',
              color: 'var(--text-secondary)',
              padding: '12px',
              textAlign: 'center',
              background: 'rgba(255, 255, 255, 0.01)',
              borderRadius: '8px',
              border: '1px solid rgba(255, 255, 255, 0.04)'
            }}>
              No past sessions
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              {conversations.map((chat) => {
                const isActive = activeConversationId === chat.id;
                return (
                  <div
                    key={chat.id}
                    style={{
                      position: 'relative',
                      display: 'flex',
                      alignItems: 'center'
                    }}
                  >
                    <button
                      onClick={() => handleSelectChatClick(chat.id)}
                      style={{
                        flex: 1,
                        background: isActive ? 'rgba(56, 189, 248, 0.06)' : 'transparent',
                        border: 'none',
                        borderLeft: isActive ? '3px solid var(--accent-cyan)' : 'none',
                        color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                        padding: '10px 12px',
                        borderRadius: isActive ? '0 8px 8px 0' : '8px',
                        fontSize: '13px',
                        textAlign: 'left',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        paddingRight: '32px',
                        transition: 'var(--transition)'
                      }}
                      onMouseEnter={(e) => {
                        if (!isActive) e.currentTarget.style.color = 'var(--text-primary)';
                      }}
                      onMouseLeave={(e) => {
                        if (!isActive) e.currentTarget.style.color = 'var(--text-secondary)';
                      }}
                    >
                      {chat.title}
                    </button>
                    {onDeleteConversation && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteConversation(chat.id);
                        }}
                        style={{
                          position: 'absolute',
                          right: '8px',
                          background: 'transparent',
                          border: 'none',
                          color: 'var(--loss)',
                          opacity: isActive ? 0.8 : 0.4,
                          padding: '4px',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          cursor: 'pointer',
                          transition: 'opacity 0.2s ease'
                        }}
                        onMouseEnter={(e) => e.currentTarget.style.opacity = '1'}
                        onMouseLeave={(e) => e.currentTarget.style.opacity = isActive ? '0.8' : '0.4'}
                        title="Delete session"
                      >
                        <Trash2 size={12} />
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Portfolio Value Summary Card */}
      {hasPortfolio && portfolioSummary && (
        <div style={{ padding: '0 20px 16px' }}>
          <div 
            style={{
              background: 'rgba(15, 23, 42, 0.5)',
              border: '1px solid rgba(56, 189, 248, 0.15)',
              borderRadius: '12px',
              padding: '14px 16px',
              display: 'flex',
              flexDirection: 'column',
              gap: '6px',
              position: 'relative',
              boxShadow: '0 4px 20px rgba(0, 0, 0, 0.2)'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '10px', color: 'var(--text-secondary)', fontWeight: 600, letterSpacing: '0.02em' }}>
              <ShieldCheck size={12} color="var(--accent-cyan)" />
              <span>PORTFOLIO VALUE</span>
            </div>
            
            <div className="animate-number-reveal" style={{ 
              fontSize: '18px', 
              fontWeight: 700, 
              color: 'var(--text-primary)',
              fontFamily: 'var(--font-mono)',
              letterSpacing: '-0.5px'
            }}>
              ₹{portfolioSummary.totalValue.toLocaleString('en-IN')}
            </div>

            <div className="animate-number-reveal" style={{ 
              display: 'flex', 
              alignItems: 'center', 
              gap: '4px', 
              fontSize: '11px',
              fontWeight: 600,
              color: portfolioSummary.totalPnL >= 0 ? 'var(--profit)' : 'var(--loss)'
            }}>
              <ArrowUpRight size={12} style={{ transform: portfolioSummary.totalPnL >= 0 ? 'none' : 'rotate(90deg)' }} />
              <span>
                {portfolioSummary.totalPnL >= 0 ? '+' : ''}
                ₹{portfolioSummary.totalPnL.toLocaleString('en-IN')} ({portfolioSummary.totalReturnPct.toFixed(1)}%)
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Footer Settings & Clear */}
      <div style={{
        padding: '16px 20px',
        borderTop: '1px solid rgba(255, 255, 255, 0.04)',
        display: 'flex',
        flexDirection: 'column',
        gap: '10px'
      }}>
        {onClearHistory && conversations.length > 0 && (
          <button
            onClick={onClearHistory}
            style={{
              width: '100%',
              background: 'transparent',
              border: '1px dashed rgba(251, 113, 133, 0.2)',
              color: 'var(--loss)',
              fontSize: '11px',
              padding: '8px 10px',
              borderRadius: '6px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px'
            }}
          >
            <Trash2 size={11} />
             Clear History
          </button>
        )}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: '11px',
          color: 'var(--text-secondary)',
          padding: '2px 4px'
        }}>
          <Compass size={12} />
           <span>Setup</span>
          <a
            href="/"
            onClick={(e) => {
              e.preventDefault();
              localStorage.removeItem('prospektlab_onboarded');
              navigate('/onboarding');
            }}
            style={{
              marginLeft: 'auto',
              color: 'var(--accent-cyan)',
              textDecoration: 'none',
              fontWeight: 600
            }}
          >
            Re-run
          </a>
        </div>
      </div>
    </aside>
  );
};
export default Sidebar;

import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  LayoutDashboard, 
  MessageSquarePlus, 
  Trash2, 
  ArrowUpRight, 
  ShieldCheck, 
  Compass, 
  LogOut,
  ChevronLeft,
  ChevronRight,
  X
} from 'lucide-react';
import { Logo } from './Logo';
import { useAuth } from '../../context/AuthContext';

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
  tokenUsage?: any;
}

export const Sidebar: React.FC<SidebarProps> = ({
  conversations = [],
  onDeleteConversation,
  onClearHistory,
  onSelectConversation,
  onNewConversation,
  activeConversationId,
  portfolioSummary,
  tokenUsage
}) => {
  const navigate = useNavigate();
  const { user, logout, setOnboarded } = useAuth();
  
  // Drag-to-resize state
  const [width, setWidth] = useState<number>(() => {
    const saved = localStorage.getItem('prospektlab_sidebar_width');
    return saved ? parseInt(saved, 10) : 260;
  });
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef<HTMLDivElement>(null);

  const isCollapsed = width <= 120;

  // Handle drag listeners
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging) return;
      let newWidth = e.clientX;
      
      // Snapping logic
      if (newWidth < 120) {
        newWidth = 56; // collapsed
      } else if (newWidth > 320) {
        newWidth = 320; // maximum width
      }
      
      setWidth(newWidth);
      localStorage.setItem('prospektlab_sidebar_width', newWidth.toString());
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      document.body.classList.remove('dragging');
    };

    if (isDragging) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
      document.body.classList.add('dragging');
    }

    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
      document.body.classList.remove('dragging');
    };
  }, [isDragging]);

  const dismissSidebarOnMobile = () => {
    if (window.innerWidth <= 768) {
      document.body.classList.remove('pl-sidebar-active');
    }
  };

  const handleNewChatClick = () => {
    dismissSidebarOnMobile();
    if (onNewConversation) {
      onNewConversation();
    }
  };

  const handleSelectChatClick = (id: string) => {
    dismissSidebarOnMobile();
    if (onSelectConversation) {
      onSelectConversation(id);
    }
  };

  const handleSignOut = async () => {
    dismissSidebarOnMobile();
    await logout();
    navigate('/login');
  };

  // Initials for avatar
  const getInitials = (name?: string) => {
    if (!name) return 'U';
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) {
      return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return name.slice(0, 2).toUpperCase();
  };

  const hasPortfolio = portfolioSummary && portfolioSummary.totalValue > 0;

  return (
    <div 
      className={`sidebar-container ${isCollapsed ? 'sidebar-collapsed' : ''}`}
      style={{
        position: 'relative',
        width: `${width}px`,
        height: '100%',
        display: 'flex',
        flexShrink: 0,
        zIndex: 20
      }}
    >
      <aside style={{
        width: '100%',
        background: 'rgba(15, 23, 42, 0.45)',
        backdropFilter: 'blur(20px)',
        WebkitBackdropFilter: 'blur(20px)',
        borderRight: '1px solid rgba(255, 255, 255, 0.06)',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden'
      }}>
        {/* Header Logo */}
        <div className="logo-container animate-fade-in-right" style={{
          padding: isCollapsed ? '20px 0' : '24px 20px',
          display: 'flex',
          flexDirection: isCollapsed ? 'column' : 'row',
          alignItems: 'center',
          justifyContent: isCollapsed ? 'center' : 'flex-start',
          gap: isCollapsed ? '12px' : '10px',
          borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
          cursor: 'pointer',
          flexShrink: 0
        }} onClick={() => {
          if (isCollapsed) {
            setWidth(260);
            localStorage.setItem('prospektlab_sidebar_width', '260');
          } else {
            dismissSidebarOnMobile();
            navigate('/dashboard');
          }
        }}
        title={isCollapsed ? "Expand Sidebar" : undefined}>
          {isCollapsed ? (
            <>
              <Logo size={24} />
              <button
                className="sidebar-toggle-btn collapsed"
                title="Expand Sidebar"
                onClick={(e) => {
                  e.stopPropagation();
                  setWidth(260);
                  localStorage.setItem('prospektlab_sidebar_width', '260');
                }}
              >
                <ChevronRight size={16} color="#38BDF8" style={{ minWidth: 16, minHeight: 16, display: 'block' }} />
              </button>
            </>
          ) : (
            <>
              <Logo size={24} />
              <span className="sidebar-header-title text-gradient text-gradient-animated" style={{
                fontWeight: 800,
                fontSize: '16px',
                color: 'var(--text-primary)',
                letterSpacing: '-0.3px',
                whiteSpace: 'nowrap',
                flexShrink: 0
              }}>
                ProspektLab
              </span>
              <span className="badge badge-premium nav-text" style={{
                fontSize: '8px',
                padding: '2px 5px',
                marginRight: '8px',
                whiteSpace: 'nowrap',
                flexShrink: 0
              }}>
                PRO
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setWidth(56);
                  localStorage.setItem('prospektlab_sidebar_width', '56');
                }}
                className="sidebar-toggle-btn"
                title="Collapse Sidebar"
                style={{
                  width: '24px',
                  height: '24px',
                  marginLeft: 'auto'
                }}
              >
                <ChevronLeft size={14} color="#38BDF8" style={{ minWidth: 14, minHeight: 14, display: 'block' }} />
              </button>
              {/* Mobile close button */}
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  dismissSidebarOnMobile();
                }}
                className="sidebar-close-btn"
                title="Close Menu"
                style={{
                  width: '28px',
                  height: '28px',
                  marginLeft: 'auto',
                  display: 'none'
                }}
              >
                <X size={14} color="#FB7185" style={{ minWidth: 14, minHeight: 14, display: 'block' }} />
              </button>
            </>
          )}
        </div>

        {/* New Chat Button */}
        <div style={{ padding: isCollapsed ? '16px 8px' : '16px 20px', flexShrink: 0 }}>
          <button
            onClick={handleNewChatClick}
            className="glass-interactive"
            title="New Chat"
            style={{
              width: '100%',
              color: 'var(--text-primary)',
              padding: '12px 8px',
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
            {!isCollapsed && <span className="nav-text">New Chat</span>}
          </button>
        </div>

        {/* Navigation */}
        <div style={{
          padding: isCollapsed ? '0 8px 12px' : '0 20px 16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
          flexShrink: 0
        }}>
          <button
            onClick={() => {
              dismissSidebarOnMobile();
              navigate('/dashboard');
            }}
            title="Dashboard"
            style={{
              width: '100%',
              background: 'rgba(255, 255, 255, 0.03)',
              border: '1px solid rgba(56, 189, 248, 0.1)',
              color: 'var(--accent-cyan)',
              padding: '10px',
              borderRadius: '8px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: isCollapsed ? 'center' : 'flex-start',
              gap: '10px',
              fontSize: '13px',
              fontWeight: 600,
              textAlign: 'left'
            }}
          >
            <LayoutDashboard size={16} />
            {!isCollapsed && <span className="nav-text">Dashboard</span>}
          </button>
        </div>

        {/* Conversation List */}
        {!isCollapsed && (
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
        )}

        {/* Portfolio Value Summary Card */}
        {hasPortfolio && portfolioSummary && !isCollapsed && (
          <div style={{ padding: '0 20px 16px', flexShrink: 0 }}>
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

        {/* User Profile Card (New Addition) */}
        {user && (
          <>
            <div className="profile-container" style={{
              padding: isCollapsed ? '12px 6px' : '14px 16px',
              borderTop: '1px solid rgba(255, 255, 255, 0.04)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: isCollapsed ? 'center' : 'space-between',
              gap: '10px',
              flexShrink: 0
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', overflow: 'hidden' }}>
                <div 
                  className="animate-pulse-glow"
                  style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '50%',
                    background: 'var(--gradient-brand)',
                    color: '#0f172a',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 700,
                    fontSize: '12px',
                    flexShrink: 0
                  }}
                >
                  {getInitials(user.name)}
                </div>
                {!isCollapsed && (
                  <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                    <span className="profile-text" style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {user.name}
                    </span>
                    <span className="profile-text" style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {user.email}
                    </span>
                  </div>
                )}
              </div>

              {!isCollapsed ? (
                <button 
                  onClick={handleSignOut}
                  title="Sign Out"
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: 'var(--text-secondary)',
                    padding: '6px',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    borderRadius: '4px'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.color = 'var(--loss)';
                    e.currentTarget.style.background = 'rgba(251, 113, 133, 0.06)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.color = 'var(--text-secondary)';
                    e.currentTarget.style.background = 'transparent';
                  }}
                >
                  <LogOut size={14} />
                </button>
              ) : (
                <button 
                  onClick={handleSignOut}
                  title="Sign Out"
                  style={{
                    display: 'none' // hidden or click avatar instead
                  }}
                />
              )}
            </div>
            {!isCollapsed && tokenUsage && (
              <div style={{
                padding: '0 16px 12px 16px',
                display: 'flex',
                flexDirection: 'column',
                gap: '4px',
                flexShrink: 0
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-secondary)' }}>
                  <span>Weekly Usage</span>
                  <span style={{ fontFamily: 'monospace' }}>
                    {((tokenUsage.usage / tokenUsage.limit) * 100).toFixed(1)}%
                  </span>
                </div>
                <div style={{ width: '100%', height: '4px', background: 'rgba(255, 255, 255, 0.06)', borderRadius: '2px', overflow: 'hidden' }}>
                  <div style={{
                    width: `${Math.min(100, (tokenUsage.usage / tokenUsage.limit) * 100)}%`,
                    height: '100%',
                    background: tokenUsage.usage >= tokenUsage.limit ? 'var(--loss)' : 'var(--accent-cyan)',
                    borderRadius: '2px'
                  }}></div>
                </div>
                <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>
                  {tokenUsage.usage.toLocaleString()} / {tokenUsage.limit.toLocaleString()} tokens
                </span>
              </div>
            )}
          </>
        )}

        {/* Footer Settings & Clear */}
        <div style={{
          padding: isCollapsed ? '8px 4px' : '16px 20px',
          borderTop: '1px solid rgba(255, 255, 255, 0.04)',
          display: 'flex',
          flexDirection: 'column',
          gap: '10px',
          flexShrink: 0
        }}>
          {onClearHistory && conversations.length > 0 && !isCollapsed && (
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
          {!isCollapsed ? (
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
                  setOnboarded(false);
                  dismissSidebarOnMobile();
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
          ) : (
            <button
              title="Re-run Setup"
              onClick={() => {
                setOnboarded(false);
                dismissSidebarOnMobile();
                navigate('/onboarding');
              }}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--text-muted)',
                width: '100%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '4px'
              }}
            >
              <Compass size={14} />
            </button>
          )}
        </div>
      </aside>

      {/* Resize Drag Handle */}
      <div 
        ref={dragRef}
        className={`drag-handle-vertical drag-handle-right ${isDragging ? 'dragging' : ''}`}
        onMouseDown={() => setIsDragging(true)}
      />
    </div>
  );
};
export default Sidebar;

import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { AppShell } from '../components/layout/AppShell';
import FeatureTabs, { FeatureTabId } from '../components/layout/FeatureTabs';
import GovernanceWorkspace from '../components/governance/GovernanceWorkspace';
import { ChatInput } from '../components/chat/ChatInput';
import { MessageBubble } from '../components/chat/MessageBubble';
import { AgentThinking } from '../components/chat/AgentThinking';
import ExportPanel from '../components/chat/ExportPanel';
import { useAuth } from '../context/AuthContext';
import {
  startResearch,
  streamSession,
  getSessionResult,
  AgentEventData,
} from '../api/client';
import { Lock, Search, Sparkles, MessageSquare, ChevronRight } from 'lucide-react';

interface Message {
  sender: 'user' | 'ai';
  text: string;
  richData?: any;
  depth?: 'standard' | 'deep';
  elapsedMs?: number;
  tokenLimitDetail?: any;
  sessionId?: string;
  wantsDocument?: boolean;
}

const DOC_INTENT_RE = /\b(report|document|doc|pdf|docx|memo|write[- ]?up|deck|dossier|whitepaper|white paper|one[- ]?pager|file)\b/i;
const DOC_VERB_RE = /\b(export|download|save|generate|create|make|produce|prepare|draft|build|give me|send me|put together)\b/i;
const DOC_NEG_RE = /\b(do not|don'?t|no need|without|skip|not a (report|document|pdf))\b/i;
function queryWantsDocument(text: string): boolean {
  const t = (text || '').toLowerCase();
  if (!t) return false;
  if (DOC_NEG_RE.test(t)) return false;
  if (/\b(as|to|in)\s+(a\s+)?(pdf|docx?|document|report|file)\b/.test(t)) return true;
  if (/\b(generate|create|make|give me|send me|build|prepare|draft|export|download)\s+(me\s+)?(a\s+|an\s+|the\s+)?(report|document|doc|pdf|docx|memo|deck|dossier|write[- ]?up|one[- ]?pager)\b/.test(t)) return true;
  return DOC_VERB_RE.test(t) && DOC_INTENT_RE.test(t);
}

export const DashboardGovernancePage: React.FC = () => {
  const navigate = useNavigate();
  const { user, showToast, isAuthenticated, isReadOnly, isPro } = useAuth();

  // Chat state
  const chatStorageScope = useMemo(() => {
    if (isAuthenticated && user?.email) {
      return user.email.toLowerCase();
    }
    return 'guest';
  }, [isAuthenticated, user?.email]);
  const conversationsStorageKey = useMemo(
    () => `prospektlab_conversations:${chatStorageScope}`,
    [chatStorageScope],
  );
  const [, setConversations] = useState<any[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string>('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [isThinking, setIsThinking] = useState(false);
  const [thinkingEvents, setThinkingEvents] = useState<AgentEventData[]>([]);
  const [pendingChatQuery, setPendingChatQuery] = useState<{ id: string; text: string; depth: 'standard' | 'deep' } | null>(null);
  const [isChatHighlighted, setIsChatHighlighted] = useState(false);

  // Resizable chat rail state
  const [chatWidth, setChatWidth] = useState<number>(() => {
    const saved = localStorage.getItem('prospektlab_chat_width');
    return saved ? parseInt(saved, 10) : 380;
  });
  const [isDraggingChat, setIsDraggingChat] = useState(false);
  const [isChatHidden, setIsChatHidden] = useState(() => {
    const savedWidth = localStorage.getItem('prospektlab_chat_width');
    return savedWidth ? parseInt(savedWidth, 10) <= 0 : false;
  });

  const abortStreamRef = useRef<(() => void) | null>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  const getMessageStorageKey = (conversationId: string) =>
    `prospektlab_messages:${chatStorageScope}:${conversationId}`;

  const readStoredMessages = (conversationId: string): string | null => {
    const scopedKey = getMessageStorageKey(conversationId);
    const scopedRaw = localStorage.getItem(scopedKey);
    if (scopedRaw) return scopedRaw;
    if (isAuthenticated) return null;
    const legacyKey = `prospektlab_messages_${conversationId}`;
    const legacyRaw = localStorage.getItem(legacyKey);
    if (legacyRaw) {
      localStorage.setItem(scopedKey, legacyRaw);
      localStorage.removeItem(legacyKey);
    }
    return legacyRaw;
  };

  // Load conversations
  useEffect(() => {
    const raw = localStorage.getItem(conversationsStorageKey);
    let parsed: any[] = [];
    try { parsed = raw ? JSON.parse(raw) : []; } catch { parsed = []; }
    if (!Array.isArray(parsed) || parsed.length === 0) {
      const defaultConv = { id: `conv_${Date.now()}`, title: 'Untitled' };
      parsed = [defaultConv];
      localStorage.setItem(conversationsStorageKey, JSON.stringify(parsed));
    }
    setConversations(parsed);
    setActiveConversationId(parsed[0].id);
    const storedRaw = readStoredMessages(parsed[0].id);
    const storedMsgs = storedRaw ? JSON.parse(storedRaw) : [];
    setMessages(storedMsgs);
  }, [conversationsStorageKey]);

  // Persist messages
  useEffect(() => {
    if (!activeConversationId) return;
    localStorage.setItem(getMessageStorageKey(activeConversationId), JSON.stringify(messages));
  }, [messages, activeConversationId, chatStorageScope]);

  // Chat drag resize
  useEffect(() => {
    if (!isDraggingChat) return;
    const handleMouseMove = (e: MouseEvent) => {
      const newWidth = Math.max(280, Math.min(600, window.innerWidth - e.clientX));
      setChatWidth(newWidth);
    };
    const handleMouseUp = () => {
      setIsDraggingChat(false);
      localStorage.setItem('prospektlab_chat_width', chatWidth.toString());
      if (chatWidth < 100) {
        setIsChatHidden(true);
        setChatWidth(0);
        localStorage.setItem('prospektlab_chat_width', '0');
      }
    };
    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDraggingChat, chatWidth]);

  const handleFeatureTabChange = (tab: FeatureTabId) => {
    switch (tab) {
      case 'overview': navigate('/dashboard/overview'); break;
      case 'portfolio': navigate('/dashboard/portfolio'); break;
      case 'watchlist': navigate('/dashboard/watchlist'); break;
      case 'screener': navigate('/dashboard/screener'); break;
      case 'ipo': navigate('/dashboard/ipo'); break;
      case 'earnings': navigate('/dashboard/earnings'); break;
      case 'governance': navigate('/dashboard/governance'); break;
      default: navigate('/dashboard/overview'); break;
    }
  };

  const handleSuggestQuery = (query: string, depth: 'standard' | 'deep' = 'standard') => {
    if (isReadOnly) {
      navigate('/login?redirect=/dashboard/governance');
      return;
    }
    if (isChatHidden) {
      setIsChatHidden(false);
      const w = 380;
      setChatWidth(w);
      localStorage.setItem('prospektlab_chat_width', w.toString());
    }
    setPendingChatQuery({ id: `draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, text: query, depth });
    setIsChatHighlighted(true);
    setTimeout(() => setIsChatHighlighted(false), 1600);
    setTimeout(() => {
      if (chatContainerRef.current) {
        chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
      }
    }, 120);
  };

  const handleSendMessage = async (message: string, depth: 'standard' | 'deep' = 'standard') => {
    if (!message.trim() || isThinking || isReadOnly) return;
    const conversationId = activeConversationId;

    const userMsg: Message = { sender: 'user', text: message, depth };
    const updatedMessages = [...messages, userMsg];
    setMessages(updatedMessages);
    localStorage.setItem(getMessageStorageKey(conversationId), JSON.stringify(updatedMessages));

    setIsThinking(true);
    setThinkingEvents([{
      seq: 0,
      type: 'phase',
      timestamp: new Date().toISOString(),
      payload: { phase: 'queued', note: 'Preparing the governance analysis' },
    }]);

    const startMs = performance.now();
    const wantsDoc = queryWantsDocument(message);
    let streamedMemoText = '';
    let runCompleted = false;

    const completeWithResponse = (aiResponse: Message) => {
      if (runCompleted) return;
      runCompleted = true;
      setMessages((prev) => {
        const next = [...prev, aiResponse];
        try {
          localStorage.setItem(getMessageStorageKey(conversationId), JSON.stringify(next));
        } catch (e) {
          console.warn('localStorage persist failed', e);
        }
        return next;
      });
      setIsThinking(false);
      setThinkingEvents([]);
    };

    try {
      const startRes = await startResearch(message, depth);
      const backendSessionId = startRes.session_id;

      const unsubscribe = streamSession(
        backendSessionId,
        (event) => {
          if (event.type === 'memo_token' && typeof event.payload?.chunk === 'string') {
            streamedMemoText += event.payload.chunk;
          }
          setThinkingEvents((prev) => [...prev, event]);
        },
        async (parsedEvent: any) => {
          if (runCompleted) return;
          const elapsed = Math.round(performance.now() - startMs);

          let aiResponse: Message;
          try {
            const finalResult = await getSessionResult(backendSessionId);
            const richPayload = finalResult.final?.rich || parsedEvent?.rich || null;
            const memoText =
              finalResult.memo ||
              finalResult.final?.memo ||
              finalResult.final?.memo_preview ||
              richPayload?.markdown_body ||
              finalResult.memo_event?.preview ||
              streamedMemoText.trim() ||
              parsedEvent?.memo ||
              parsedEvent?.memo_preview ||
              parsedEvent?.preview ||
              'Analysis complete.';
            aiResponse = {
              sender: 'ai',
              text: memoText,
              richData: richPayload,
              depth,
              elapsedMs: elapsed,
              sessionId: backendSessionId,
              wantsDocument: depth === 'deep' && wantsDoc,
            };
          } catch (resErr) {
            console.error('Failed to retrieve final memo', resErr);
            const fallbackRich = parsedEvent?.rich || null;
            const fallbackText =
              parsedEvent?.memo ||
              parsedEvent?.memo_preview ||
              parsedEvent?.preview ||
              fallbackRich?.markdown_body ||
              streamedMemoText.trim() ||
              'Analysis complete.';
            aiResponse = {
              sender: 'ai',
              text: fallbackText,
              richData: fallbackRich,
              depth,
              elapsedMs: elapsed,
              sessionId: backendSessionId,
              wantsDocument: depth === 'deep' && wantsDoc,
            };
            showToast('Failed to load full answer. Showing cached preview.', 'error');
          }

          completeWithResponse(aiResponse);
        },
        (error) => {
          if (runCompleted) return;
          const errMsg = error.message || 'Stream processing failed.';
          showToast(errMsg, 'error');
          completeWithResponse({ sender: 'ai', text: `**Research failed**: ${errMsg}\n\nPlease try again.` });
        }
      );

      abortStreamRef.current = unsubscribe;
    } catch (err: any) {
      setIsThinking(false);
      setThinkingEvents([]);
      const errMsg = err.message || 'Failed to connect.';
      showToast(errMsg, 'error');

      if (err.detail?.code === 'WEEKLY_TOKEN_LIMIT_EXCEEDED' || err.detail?.code === 'DEEP_PREMIUM_REQUIRED') {
        const limitResponse: Message = {
          sender: 'ai',
          text: err.detail?.code === 'DEEP_PREMIUM_REQUIRED' ? 'Deep Mode Limit Reached' : 'Weekly Token Limit Exceeded',
          tokenLimitDetail: err.detail,
        };
        setMessages((prev) => {
          const next = [...prev, limitResponse];
          try { localStorage.setItem(getMessageStorageKey(conversationId), JSON.stringify(next)); } catch (e) { /* ignore */ }
          return next;
        });
      } else {
        setMessages((prev) => [...prev, { sender: 'ai', text: `**Connection Error**: ${errMsg}` }]);
      }
    }
  };

  const handleStopGeneration = () => {
    if (abortStreamRef.current) {
      abortStreamRef.current();
      abortStreamRef.current = null;
    }
    setIsThinking(false);
  };

  const hasEngaged = messages.some((msg, index) => msg.sender === 'user' || index > 0);

  const getArthikGreeting = (): string => {
    const hour = new Date().getHours();
    const name = user?.name?.split(' ')[0] || '';
    const timeGreet = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';
    return name
      ? `${timeGreet}, ${name}. Ask me about any company's governance, pledge, or board risk.`
      : `${timeGreet}! I can analyze promoter pledge, board churn, auditor changes, and governance red flags for any company.`;
  };
  const arthikGreeting = getArthikGreeting();

  const suggestions = [
    'Why is the governance risk high for the top flagged company?',
    'Explain the promoter pledge trend for Reliance Infrastructure',
    'Which Nifty 500 companies have rising promoter pledge?',
  ];

  return (
    <AppShell title="Governance">
      <div className={`workbench ${isChatHidden ? 'chat-closed' : 'chat-open'}`} style={
        (typeof window !== 'undefined' && window.innerWidth > 768) ? {
          gridTemplateColumns: `minmax(0, 1fr) ${isChatHidden ? '0px' : `${chatWidth}px`}`,
          transition: isDraggingChat ? 'none' : undefined
        } : undefined
      }>
        {/* ════════════ LEFT: GOVERNANCE DATA ════════════ */}
        <div className="workbench-data">
          <div className="workspace-tabs-wrap">
            <FeatureTabs active="governance" onChange={handleFeatureTabChange} />
          </div>
          <div style={{ flex: 1, overflowY: 'auto', minWidth: 0, padding: 'clamp(16px, 3vw, 24px) clamp(14px, 4vw, 32px) 60px' }}>
            <GovernanceWorkspace />
          </div>
        </div>

        {/* ════════════ RIGHT: CHAT RAIL ════════════ */}
        <div className="workbench-chat" style={{
          position: 'relative',
          width: isChatHidden ? '0px' : `${chatWidth}px`,
          display: 'flex',
          flexDirection: 'column',
          borderLeft: isChatHidden ? 'none' : undefined,
          overflow: 'visible',
          transition: isDraggingChat ? 'none' : 'box-shadow 0.4s ease',
          boxShadow: isChatHighlighted ? '0 0 0 2px rgba(56, 189, 248, 0.45), -4px 0 24px rgba(56, 189, 248, 0.08)' : undefined
        }}>
          {isReadOnly && (
            <div
              onClick={() => navigate('/login?redirect=/dashboard/governance')}
              style={{
                position: 'absolute', inset: 0, zIndex: 20,
                backdropFilter: 'blur(6px)', WebkitBackdropFilter: 'blur(6px)',
                background: 'rgba(15, 23, 42, 0.35)',
                display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                gap: '12px', borderRadius: '12px', cursor: 'pointer'
              }}
            >
              <Lock size={32} color="var(--text-muted)" />
              <span style={{ color: 'var(--text-secondary)', fontSize: 14, fontWeight: 600 }}>Login to unlock</span>
            </div>
          )}

          <div style={{ display: isChatHidden ? 'none' : 'flex', flexDirection: 'column', width: '100%', height: '100%', overflow: 'hidden' }}>
            <button
              className="chat-mobile-handle"
              onClick={() => { setIsChatHidden(true); setChatWidth(0); localStorage.setItem('prospektlab_chat_width', '0'); }}
              aria-label="Close chat"
            >
              <div className="chat-mobile-handle-bar" />
            </button>

            <div className="drag-handle-vertical drag-handle-left" onMouseDown={() => setIsDraggingChat(true)} style={{ width: '6px' }} />

            <div className="chat-rail-head">
              <div className="chat-rail-title">Arthik</div>
              <div className="chat-rail-actions">
                <button className="chat-rail-iconbtn" title="Collapse Chat" onClick={() => { setIsChatHidden(true); setChatWidth(0); localStorage.setItem('prospektlab_chat_width', '0'); }}>
                  <ChevronRight size={16} color="#38BDF8" style={{ minWidth: 16, minHeight: 16, display: 'block' }} />
                </button>
              </div>
            </div>

            <div className="chat-rail-body" ref={chatContainerRef}>
              {!hasEngaged ? (
                <>
                  <div className="chat-rail-greeting">{arthikGreeting}</div>

                  {suggestions.map((s, i) => (
                    <button key={i} className="suggestion-card" onClick={() => handleSuggestQuery(s, 'standard')}>
                      <span>{s}</span>
                      <span className="suggestion-card-icon"><Search size={11} /></span>
                    </button>
                  ))}

                  <div className="explore-label">Or try one of these</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    <button
                      className="mode-chip"
                      onClick={() => handleSuggestQuery('Deep research: full governance and pledge risk dossier on SITI Networks.', 'deep')}
                      style={{ position: 'relative' }}
                    >
                      <Sparkles size={12} /> Full dossier
                      {!isPro && (
                        <span style={{ position: 'absolute', top: -6, right: -6, background: 'var(--gradient-brand)', color: '#0f172a', fontSize: 8, fontWeight: 800, padding: '1px 5px', borderRadius: 999 }}>
                          PRO
                        </span>
                      )}
                    </button>
                    <button className="mode-chip" onClick={() => handleSuggestQuery('Which companies have promoters pledging more shares this quarter?', 'standard')}>
                      Rising pledges
                    </button>
                    <button className="mode-chip" onClick={() => handleSuggestQuery('Show governance red flags: auditor and board changes.', 'standard')}>
                      Board &amp; auditor flags
                    </button>
                  </div>
                </>
              ) : (
                <>
                  {messages.map((msg, i) => {
                    if (i === 0 && msg.sender === 'ai') return null;

                    if (msg.tokenLimitDetail) {
                      const detail = msg.tokenLimitDetail;
                      const isDeepPremium = detail.code === 'DEEP_PREMIUM_REQUIRED';
                      if (isDeepPremium && isPro) return null;
                      return (
                        <div key={i} className="glass-card token-limit-card animate-slide-in-up" style={{
                          padding: '20px', margin: '12px 0', borderRadius: '12px',
                          border: isDeepPremium ? '1px solid rgba(56, 189, 248, 0.25)' : '1px solid rgba(239, 68, 68, 0.25)',
                          background: isDeepPremium ? 'rgba(56, 189, 248, 0.05)' : 'rgba(239, 68, 68, 0.05)',
                          display: 'flex', flexDirection: 'column', gap: '12px'
                        }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <div style={{
                              background: isDeepPremium ? 'rgba(56, 189, 248, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                              color: isDeepPremium ? '#38BDF8' : '#F87171',
                              width: '36px', height: '36px', borderRadius: '50%',
                              display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px', fontWeight: 'bold'
                            }}>{isDeepPremium ? '🔒' : '⚠️'}</div>
                            <div>
                              <h4 style={{ margin: 0, fontSize: '14px', fontWeight: 600, color: isDeepPremium ? '#38BDF8' : '#F87171' }}>
                                {isDeepPremium ? 'Deep Mode is Pro' : 'Research Limit Reached'}
                              </h4>
                              <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                                {isDeepPremium ? 'Free tier includes 1 deep run per week' : 'Weekly allocation exhausted'}
                              </span>
                            </div>
                          </div>
                          <p style={{ margin: 0, fontSize: '12px', lineHeight: '1.5', color: 'var(--text-secondary)' }}>
                            {detail.message || `You've consumed all allocated tokens for this period.`}
                          </p>
                          {detail.upgrade_available && !isPro && (
                            <button onClick={() => navigate('/pricing')} style={{
                              width: '100%', padding: '10px', borderRadius: 8, border: 'none',
                              background: 'var(--gradient-brand)', color: '#0f172a', fontSize: 13, fontWeight: 700, cursor: 'pointer',
                            }}>
                              Subscribe to Pro — Unlock Deep Mode
                            </button>
                          )}
                        </div>
                      );
                    }

                    return (
                      <div key={i} className="animate-slide-in-up">
                        <MessageBubble sender={msg.sender} text={msg.text} richData={msg.richData} depth={msg.depth} elapsedMs={msg.elapsedMs} />
                        {msg.sender === 'ai' && msg.depth === 'deep' && msg.wantsDocument && msg.sessionId && (
                          <ExportPanel sessionId={msg.sessionId} />
                        )}
                      </div>
                    );
                  })}
                </>
              )}
            </div>

            {isThinking && (
              <div className="chat-live-pipeline-panel" aria-live="polite" aria-label="Arthik live pipeline">
                <AgentThinking events={thinkingEvents} isActive={isThinking} />
              </div>
            )}

            <div className="chat-rail-dock">
              <ChatInput
                onSend={handleSendMessage}
                onStop={handleStopGeneration}
                disabled={isThinking || isReadOnly}
                pendingDraft={isReadOnly ? null : pendingChatQuery}
                onPendingConsumed={() => setPendingChatQuery(null)}
              />
              <div className="chat-rail-footer">
                {isReadOnly
                  ? 'Login to access Arthik AI — ask about any company governance'
                  : isPro
                    ? 'Arthik • Pro • Unlimited Deep • Esc to stop'
                    : 'Arthik • Free • 1 Deep run/week • Esc to stop'}
              </div>
            </div>
          </div>
        </div>
      </div>

      {!isChatHidden && (
        <div
          className="chat-mobile-backdrop"
          onClick={() => { setIsChatHidden(true); setChatWidth(0); localStorage.setItem('prospektlab_chat_width', '0'); }}
        />
      )}

      {isChatHidden && (
        <button
          className="chat-restore-btn"
          onClick={() => { setIsChatHidden(false); const w = 380; setChatWidth(w); localStorage.setItem('prospektlab_chat_width', w.toString()); }}
          title="Restore chat workspace"
        >
          <MessageSquare size={20} />
        </button>
      )}
    </AppShell>
  );
};

export default DashboardGovernancePage;

import React from 'react';
import { User, Brain } from 'lucide-react';
import { RichResponse } from './RichResponse';

const renderFormattedText = (text: string) => {
  if (!text) return '';
  const parts = text.split(/\*\*([^*]+)\*\*/g);
  return parts.map((part, index) => {
    if (index % 2 === 1) {
      return <strong key={index} style={{ fontWeight: 700, color: 'var(--accent-cyan)' }}>{part}</strong>;
    }
    return part;
  });
};

interface MessageBubbleProps {
  sender: 'user' | 'ai';
  text: string;
  richData?: any;
  depth?: 'chat' | 'standard' | 'deep';
  elapsedMs?: number;
}

export const MessageBubble: React.FC<MessageBubbleProps> = ({
  sender,
  text,
  richData,
  depth,
  elapsedMs
}) => {
  const isUser = sender === 'user';

  return (
    <div className="animate-slide-in-up" style={{
      display: 'flex',
      gap: '12px',
      width: '100%',
      maxWidth: '100%',
      alignSelf: 'center',
      flexDirection: isUser ? 'row-reverse' : 'row',
      marginBottom: '8px'
    }}>
      {/* Avatar Wrapper */}
      <div style={{
        width: '32px',
        height: '32px',
        borderRadius: '50%',
        backgroundColor: isUser ? 'var(--neutral-dim)' : 'rgba(129, 140, 248, 0.1)',
        border: '1px solid',
        borderColor: isUser ? 'var(--accent-cyan)' : 'var(--accent-indigo)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: isUser ? 'var(--accent-cyan)' : 'var(--accent-indigo)',
        flexShrink: 0,
        boxShadow: isUser ? '0 0 10px rgba(56, 189, 248, 0.1)' : '0 0 10px rgba(129, 140, 248, 0.1)'
      }}>
        {isUser ? <User size={14} /> : <Brain size={14} />}
      </div>

      {/* Bubble Content Area */}
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
        maxWidth: '85%'
      }}>
        {/* Name and Metadata Row */}
        {!isUser && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontSize: '11px',
            color: 'var(--text-secondary)'
          }}>
            <span style={{ fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '0.05em' }}>Mark-IT</span>
            {depth && (
              <span className="badge badge-info" style={{ fontSize: '9px', padding: '1px 5px', color: 'var(--accent-indigo)', borderColor: 'rgba(129, 140, 248, 0.2)', background: 'rgba(129, 140, 248, 0.1)' }}>
                {depth.toUpperCase()}
              </span>
            )}
            {elapsedMs && (
              <span>• done in {(elapsedMs / 1000).toFixed(2)}s</span>
            )}
          </div>
        )}

        {/* Message body */}
        <div style={{
          background: isUser ? 'rgba(56, 189, 248, 0.06)' : 'rgba(15, 23, 42, 0.75)',
          border: '1px solid',
          borderColor: isUser ? 'rgba(56, 189, 248, 0.25)' : 'rgba(255, 255, 255, 0.10)',
          borderRadius: '12px',
          padding: '14px 18px',
          fontSize: '13.5px',
          color: 'var(--text-primary)',
          lineHeight: 1.55,
          boxShadow: isUser ? '0 4px 20px rgba(0, 0, 0, 0.15)' : '0 4px 24px rgba(0, 0, 0, 0.25)',
          whiteSpace: 'pre-line'
        }}>
          {renderFormattedText(text)}
        </div>

        {/* Structured Visual Cards (Rich Renders) */}
        {!isUser && richData && (
          <div className="animate-scale-pop" style={{ marginTop: '4px', width: '100%' }}>
            <RichResponse data={richData} />
          </div>
        )}
      </div>
    </div>
  );
};

export default MessageBubble;

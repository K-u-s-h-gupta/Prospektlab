import React, { useState, KeyboardEvent } from 'react';
import { Send, Sparkles, ShieldCheck, Zap } from 'lucide-react';

interface ChatInputProps {
  onSend: (message: string, depth: 'chat' | 'standard' | 'deep') => void;
  onStop?: () => void;
  disabled?: boolean;
}

export const ChatInput: React.FC<ChatInputProps> = ({ onSend, onStop, disabled }) => {
  const [text, setText] = useState('');
  const [depth, setDepth] = useState<'chat' | 'standard' | 'deep'>('standard');
  const [isFocused, setIsFocused] = useState(false);

  const handleSend = () => {
    if (!text.trim() || disabled) return;
    onSend(text.trim(), depth);
    setText('');
  };

  const handleKeyPress = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className={isFocused ? 'animate-breathe' : ''} style={{
      display: 'flex',
      flexDirection: 'column',
      gap: '12px',
      background: 'rgba(15, 23, 42, 0.45)',
      border: '1px solid rgba(255, 255, 255, 0.08)',
      borderRadius: '12px',
      padding: '12px',
      width: '100%',
      boxShadow: '0 4px 24px rgba(0, 0, 0, 0.2)'
    }}>
      {/* Textarea Area */}
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyPress}
        onFocus={() => setIsFocused(true)}
        onBlur={() => setIsFocused(false)}
        disabled={disabled}
        placeholder="Ask Mark anything — a ticker, your portfolio, or the tape..."
        style={{
          width: '100%',
          minHeight: '60px',
          maxHeight: '180px',
          background: 'transparent',
          border: 'none',
          color: 'var(--text-primary)',
          fontSize: '13.5px',
          resize: 'none',
          padding: 0,
          outline: 'none',
          fontFamily: 'inherit',
          lineHeight: '1.4'
        }}
      />

      {/* Control Actions Row */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderTop: '1px solid rgba(255, 255, 255, 0.05)',
        paddingTop: '10px'
      }}>
        {/* Depth Mode Selector Chips */}
        <div style={{
          display: 'flex',
          gap: '8px'
        }}>
          {/* Quick Chat Mode */}
          <button
            onClick={() => setDepth('chat')}
            type="button"
            disabled={disabled}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              backgroundColor: depth === 'chat' ? 'var(--neutral-dim)' : 'transparent',
              borderColor: depth === 'chat' ? 'var(--accent-cyan)' : 'transparent',
              color: depth === 'chat' ? 'var(--accent-cyan)' : 'var(--text-secondary)',
              padding: '6px 10px',
              borderRadius: '6px',
              fontSize: '11px',
              fontWeight: 600,
              border: '1px solid',
              cursor: 'pointer',
              transform: 'none',
              lineHeight: 1
            }}
          >
            <Zap size={11} />
            Quick
          </button>

          {/* Standard Mode */}
          <button
            onClick={() => setDepth('standard')}
            type="button"
            disabled={disabled}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              backgroundColor: depth === 'standard' ? 'var(--neutral-dim)' : 'transparent',
              borderColor: depth === 'standard' ? 'var(--accent-indigo)' : 'transparent',
              color: depth === 'standard' ? 'var(--accent-indigo)' : 'var(--text-secondary)',
              padding: '6px 10px',
              borderRadius: '6px',
              fontSize: '11px',
              fontWeight: 600,
              border: '1px solid',
              cursor: 'pointer',
              transform: 'none',
              lineHeight: 1
            }}
          >
            <ShieldCheck size={11} />
            Standard
          </button>

          {/* Deep Research Mode */}
          <button
            onClick={() => setDepth('deep')}
            type="button"
            disabled={disabled}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              backgroundColor: depth === 'deep' ? 'var(--profit-dim)' : 'transparent',
              borderColor: depth === 'deep' ? 'var(--profit)' : 'transparent',
              color: depth === 'deep' ? 'var(--profit)' : 'var(--text-secondary)',
              padding: '6px 10px',
              borderRadius: '6px',
              fontSize: '11px',
              fontWeight: 600,
              border: '1px solid',
              cursor: 'pointer',
              transform: 'none',
              lineHeight: 1
            }}
          >
            <Sparkles size={11} />
            Deep
          </button>
        </div>

        {/* Submit / Stop button */}
        {disabled && onStop ? (
          <button
            onClick={onStop}
            style={{
              background: 'rgba(251, 113, 133, 0.1)',
              color: 'var(--loss)',
              border: '1px solid rgba(251, 113, 133, 0.3)',
              width: '32px',
              height: '32px',
              borderRadius: '8px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 0,
              cursor: 'pointer',
            }}
            title="Stop analysis (Esc)"
          >
            ■
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!text.trim() || disabled}
            style={{
              background: text.trim() && !disabled ? 'var(--gradient-brand)' : 'rgba(255, 255, 255, 0.03)',
              color: text.trim() && !disabled ? '#030712' : 'var(--text-muted)',
              border: 'none',
              width: '32px',
              height: '32px',
              borderRadius: '8px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 0,
              cursor: text.trim() && !disabled ? 'pointer' : 'default',
              transition: 'all 0.25s ease',
            }}
          >
            <Send size={13} color={text.trim() && !disabled ? '#030712' : 'var(--text-muted)'} />
          </button>
        )}
      </div>
    </div>
  );
};

export default ChatInput;

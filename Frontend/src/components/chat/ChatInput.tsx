import React, { useState, useEffect, useRef, KeyboardEvent } from 'react';
import { Send, Sparkles, ShieldCheck } from 'lucide-react';

interface ChatInputProps {
  onSend: (message: string, depth: 'standard' | 'deep') => void;
  onStop?: () => void;
  disabled?: boolean;
  /** When set, auto-populates the textarea with an editable draft */
  pendingDraft?: {
    id: string;
    text: string;
    depth: 'standard' | 'deep';
  } | null;
  /** Called after the pending draft has been consumed into the input */
  onPendingConsumed?: () => void;
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSend,
  onStop,
  disabled,
  pendingDraft,
  onPendingConsumed,
}) => {
  const [text, setText] = useState('');
  const [depth, setDepth] = useState<'standard' | 'deep'>('standard');
  const [isFocused, setIsFocused] = useState(false);
  const [isPulsing, setIsPulsing] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // Track the last pending draft id we consumed to allow same-text refills.
  const lastInjectedRef = useRef<string | undefined>(undefined);

  // When a new pending draft arrives, populate the input and focus
  useEffect(() => {
    if (pendingDraft && pendingDraft.id !== lastInjectedRef.current) {
      lastInjectedRef.current = pendingDraft.id;
      setText(pendingDraft.text);
      setDepth(pendingDraft.depth);
      // Pulse the input to draw attention
      setIsPulsing(true);
      setTimeout(() => setIsPulsing(false), 1200);
      // Focus and select so the user can overwrite, edit, or press Enter.
      setTimeout(() => {
        const node = textareaRef.current;
        if (!node) return;
        node.focus();
        node.setSelectionRange(0, pendingDraft.text.length);
      }, 80);
      // Notify parent that we consumed it
      onPendingConsumed?.();
    }
  }, [pendingDraft, onPendingConsumed]);

  const handleSend = () => {
    if (!text.trim() || disabled) return;
    onSend(text.trim(), depth);
    setText('');
    lastInjectedRef.current = undefined;
  };

  const handleKeyPress = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div
      className={isFocused ? 'animate-breathe' : ''}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
        background: 'rgba(15, 23, 42, 0.45)',
        border: `1px solid ${isPulsing ? 'rgba(56, 189, 248, 0.6)' : 'rgba(255, 255, 255, 0.08)'}`,
        borderRadius: '12px',
        padding: '12px',
        width: '100%',
        boxShadow: isPulsing
          ? '0 0 0 3px rgba(56, 189, 248, 0.18), 0 4px 24px rgba(0, 0, 0, 0.2)'
          : '0 4px 24px rgba(0, 0, 0, 0.2)',
        transition: 'border-color 0.4s ease, box-shadow 0.4s ease',
      }}
    >
      {/* Pending query badge */}
      {isPulsing && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '10px',
            color: 'var(--accent-cyan)',
            fontWeight: 600,
            letterSpacing: '0.04em',
            animation: 'fadeIn 0.3s ease',
          }}
        >
          <span style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: 'var(--accent-cyan)',
            display: 'inline-block',
            animation: 'pulse 1s ease infinite',
          }} />
          QUERY READY — review and press Enter to send
        </div>
      )}

      {/* Textarea Area */}
      <textarea
        ref={textareaRef}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyPress}
        onFocus={() => setIsFocused(true)}
        onBlur={() => setIsFocused(false)}
        disabled={disabled}
        placeholder="Ask Arthik anything — a ticker, your portfolio, or the tape..."
        style={{
          width: '100%',
          minHeight: '72px',
          maxHeight: '180px',
          background: 'transparent',
          border: 'none',
          color: 'var(--text-primary)',
          fontSize: '13.5px',
          resize: 'none',
          padding: '4px 2px',
          outline: 'none',
          fontFamily: 'inherit',
          lineHeight: '1.6',
          letterSpacing: 0,
        }}
      />

      {/* Control Actions Row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          borderTop: '1px solid rgba(255, 255, 255, 0.05)',
          paddingTop: '10px',
        }}
      >
        {/* Depth Mode Selector Chips */}
        <div style={{ display: 'flex', gap: '8px' }}>
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
              lineHeight: 1,
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
              lineHeight: 1,
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

import React, { useEffect, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, FileSearch, Loader2, Sparkles } from 'lucide-react';
import { flashJobStreamUrl, getEventSourceAuthToken } from '../../api/client';

interface PassEvent {
  pass_number: number;
  total_passes: number;
  objective: string;
  label: string;
  status: 'running' | 'done';
}

interface LogLine {
  level: string;
  message: string;
  ts: string;
}

interface FlashJobMonitorProps {
  jobId: string;
  mode: 'research' | 'automation' | string;
  label?: string;
  onComplete?: (slug?: string) => void;
}

export const FlashJobMonitor: React.FC<FlashJobMonitorProps> = ({ jobId, mode, label, onComplete }) => {
  const [passes, setPasses] = useState<PassEvent[]>([]);
  const [logs, setLogs] = useState<LogLine[]>([]);
  const [phase, setPhase] = useState<string>('Initialising...');
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contentSlug, setContentSlug] = useState<string | undefined>();
  const [qualityScore, setQualityScore] = useState<number | null>(null);
  const [ingestSummary, setIngestSummary] = useState<{ generated: number; published: number } | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const completionNotifiedRef = useRef(false);
  const contentSlugRef = useRef<string | undefined>();

  useEffect(() => {
    if (!jobId) return;

    completionNotifiedRef.current = false;
    contentSlugRef.current = undefined;
    setPasses([]);
    setLogs([]);
    setPhase('Initialising...');
    setDone(false);
    setError(null);
    setContentSlug(undefined);
    setQualityScore(null);
    setIngestSummary(null);

    const token = getEventSourceAuthToken() || '';
    const streamUrl = flashJobStreamUrl(jobId);
    const url = token
      ? `${streamUrl}${streamUrl.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
      : streamUrl;

    const es = new EventSource(url);
    esRef.current = es;

    const parsePayload = (event: MessageEvent, fallbackType?: string) => {
      try {
        const payload = JSON.parse(event.data);
        handleEvent(payload.type || fallbackType || event.type, payload);
      } catch {
        // Keep stream alive if the server emits a non-JSON line.
      }
    };

    es.onmessage = (event) => parsePayload(event);
    ['phase', 'flash_pass', 'deep_pass', 'content_done', 'error', 'done', 'log', 'ingest_done'].forEach((type) => {
      es.addEventListener(type, (event) => parsePayload(event as MessageEvent, type));
    });

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [jobId]);

  const notifyComplete = (slug?: string) => {
    if (completionNotifiedRef.current) return;
    completionNotifiedRef.current = true;
    onComplete?.(slug);
  };

  const handleEvent = (type: string, payload: any) => {
    if (type === 'phase') {
      setPhase(payload.note || payload.phase || 'Working...');
      return;
    }

    if (type === 'flash_pass' || type === 'deep_pass') {
      setPasses((prev) => {
        const updated = [...prev];
        const index = updated.findIndex((entry) => entry.pass_number === payload.pass_number);
        const nextEntry: PassEvent = {
          pass_number: payload.pass_number,
          total_passes: payload.total_passes,
          objective: payload.objective || '',
          label: payload.label || payload.deep_pass_label || `Pass ${payload.pass_number}`,
          status: payload.status === 'done' ? 'done' : 'running',
        };
        if (index >= 0) {
          updated[index] = nextEntry;
        } else {
          updated.push(nextEntry);
        }
        return updated.sort((a, b) => a.pass_number - b.pass_number);
      });
      return;
    }

    if (type === 'content_done') {
      setDone(true);
      contentSlugRef.current = payload.slug;
      setContentSlug(payload.slug);
      setQualityScore(payload.quality_score ?? null);
      setPhase(`Article ready: ${payload.title || payload.slug}`);
      esRef.current?.close();
      notifyComplete(payload.slug);
      return;
    }

    if (type === 'ingest_done') {
      setDone(true);
      setIngestSummary({
        generated: payload.generated ?? 0,
        published: payload.published ?? 0,
      });
      setPhase(`Official sweep complete: ${payload.generated ?? 0} drafted`);
      esRef.current?.close();
      notifyComplete();
      return;
    }

    if (type === 'done') {
      setDone(true);
      esRef.current?.close();
      notifyComplete(contentSlugRef.current);
      return;
    }

    if (type === 'error') {
      setError(payload.message || 'Workflow failed');
      esRef.current?.close();
      return;
    }

    if (type === 'log') {
      const line: LogLine = {
        level: payload.level || 'info',
        message: payload.message || '',
        ts: new Date().toLocaleTimeString(),
      };
      setLogs((prev) => [...prev.slice(-24), line]);
    }
  };

  const totalPasses = passes.length > 0 ? passes[0].total_passes : (mode === 'automation' ? 1 : 8);
  const donePasses = passes.filter((entry) => entry.status === 'done').length;
  const progress = totalPasses > 0 ? Math.round((donePasses / totalPasses) * 100) : 0;
  const title = mode === 'automation' ? 'Official-source sweep' : 'Research workflow';
  const icon = mode === 'automation'
    ? <FileSearch size={16} color="var(--accent-cyan)" />
    : <Sparkles size={16} color="var(--accent-cyan)" />;

  return (
    <div
      className="data-panel"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        padding: 16,
        border: '1px solid rgba(96,165,250,0.16)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {icon}
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>{title}</div>
          {label && (
            <div style={{ marginTop: 3, fontSize: 11, color: 'var(--text-muted)', overflowWrap: 'anywhere' }}>
              {label}
            </div>
          )}
        </div>
        {!done && !error && <Loader2 size={14} className="animate-spin-custom" style={{ color: 'var(--accent-cyan)' }} />}
        {done && !error && <CheckCircle2 size={14} color="var(--profit)" />}
        {error && <AlertCircle size={14} color="var(--loss)" />}
      </div>

      <div style={{ fontSize: 12, color: error ? 'var(--loss)' : 'var(--text-secondary)' }}>
        {error || phase}
      </div>

      {!error && (
        <div style={{ height: 4, background: 'rgba(255,255,255,0.06)', borderRadius: 999, overflow: 'hidden' }}>
          <div
            style={{
              width: `${done ? 100 : progress}%`,
              height: '100%',
              background: done ? 'var(--profit)' : 'var(--accent-cyan)',
              transition: 'width 0.35s ease',
            }}
          />
        </div>
      )}

      {passes.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {passes.map((entry) => (
            <div
              key={entry.pass_number}
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: 8,
                padding: '8px 10px',
                borderRadius: 8,
                background: entry.status === 'done' ? 'rgba(52,211,153,0.06)' : 'rgba(96,165,250,0.06)',
              }}
            >
              {entry.status === 'done' ? (
                <CheckCircle2 size={12} color="var(--profit)" style={{ marginTop: 1, flexShrink: 0 }} />
              ) : (
                <Loader2 size={12} color="var(--accent-cyan)" className="animate-spin-custom" style={{ marginTop: 1, flexShrink: 0 }} />
              )}
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-secondary)' }}>{entry.label}</div>
                <div style={{ marginTop: 3, fontSize: 11, color: 'var(--text-muted)', overflowWrap: 'anywhere' }}>
                  {entry.objective}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {done && !error && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {qualityScore !== null && (
            <span style={{ fontSize: 11, fontWeight: 700, color: qualityScore >= 90 ? 'var(--profit)' : '#FBBF24' }}>
              Quality {qualityScore.toFixed(0)}/100
            </span>
          )}
          {contentSlug && (
            <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {contentSlug}
            </span>
          )}
          {ingestSummary && (
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {ingestSummary.generated} drafted - {ingestSummary.published} published
            </span>
          )}
        </div>
      )}

      {logs.length > 0 && (
        <details style={{ fontSize: 10, color: 'var(--text-muted)' }}>
          <summary style={{ cursor: 'pointer' }}>Workflow log ({logs.length})</summary>
          <div style={{ marginTop: 8, maxHeight: 92, overflowY: 'auto', fontFamily: 'var(--font-mono)', lineHeight: 1.5 }}>
            {logs.map((line, index) => (
              <div key={`${line.ts}-${index}`} style={{ color: line.level === 'error' ? 'var(--loss)' : 'var(--text-muted)' }}>
                [{line.ts}] {line.message}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
};

export default FlashJobMonitor;

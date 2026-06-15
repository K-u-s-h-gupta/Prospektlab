import React, { useState, useCallback, useRef } from 'react';
import { FileText, FileSpreadsheet, File, Loader2, Check, AlertCircle } from 'lucide-react';
import {
  requestExport,
  pollExport,
  downloadExportAndSave,
  type ExportFormat,
  type ExportJobStatus,
} from '../../api/client';

interface ExportPanelProps {
  sessionId: string;
}

type ExportState = 'idle' | 'exporting' | 'done' | 'error';

const FORMATS: { fmt: ExportFormat; label: string; icon: React.ReactNode }[] = [
  { fmt: 'pdf', label: 'PDF', icon: <FileText size={13} /> },
  { fmt: 'docx', label: 'DOCX', icon: <File size={13} /> },
  { fmt: 'xlsx', label: 'XLSX', icon: <FileSpreadsheet size={13} /> },
];

const ExportPanel: React.FC<ExportPanelProps> = ({ sessionId }) => {
  const [activeFormat, setActiveFormat] = useState<ExportFormat | null>(null);
  const [state, setState] = useState<ExportState>('idle');
  const [error, setError] = useState<string>('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const cleanup = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const handleExport = useCallback(async (fmt: ExportFormat) => {
    cleanup();
    setActiveFormat(fmt);
    setState('exporting');
    setError('');

    try {
      const job = await requestExport(sessionId, fmt);
      const jobId = job.job_id;

      const poll = () => new Promise<void>((resolve, reject) => {
        let elapsed = 0;
        pollRef.current = setInterval(async () => {
          elapsed += 2000;
          if (elapsed > 120000) {
            cleanup();
            reject(new Error('Export timed out'));
            return;
          }
          try {
            const status: ExportJobStatus = await pollExport(jobId);
            if (status.status === 'done') {
              cleanup();
              resolve();
            } else if (status.status === 'error') {
              cleanup();
              reject(new Error(status.error || 'Export failed'));
            }
          } catch (e) {
            cleanup();
            reject(e);
          }
        }, 2000);
      });

      await poll();
      await downloadExportAndSave(jobId, fmt);
      setState('done');
      setTimeout(() => setState('idle'), 3000);
    } catch (e: any) {
      setState('error');
      setError(e.message || 'Export failed');
      setTimeout(() => { setState('idle'); setError(''); }, 5000);
    }
  }, [sessionId, cleanup]);

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '6px',
      padding: '6px 0 2px 44px',
    }}>
      <span style={{ fontSize: '10px', color: 'var(--text-secondary)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
        Export report
      </span>
      {FORMATS.map(({ fmt, label, icon }) => (
        <button
          key={fmt}
          onClick={() => handleExport(fmt)}
          disabled={state === 'exporting'}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px',
            padding: '3px 8px',
            fontSize: '11px',
            fontWeight: 500,
            borderRadius: '6px',
            border: '1px solid rgba(255,255,255,0.12)',
            background: activeFormat === fmt && state === 'exporting'
              ? 'rgba(129, 140, 248, 0.15)'
              : 'rgba(255,255,255,0.04)',
            color: activeFormat === fmt && state === 'exporting'
              ? 'var(--accent-indigo)'
              : 'var(--text-secondary)',
            cursor: state === 'exporting' ? 'wait' : 'pointer',
            transition: 'all 0.15s',
          }}
        >
          {activeFormat === fmt && state === 'exporting' ? <Loader2 size={12} className="animate-spin" /> : icon}
          {label}
        </button>
      ))}
      {state === 'done' && (
        <span style={{ fontSize: '11px', color: 'var(--profit)', display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
          <Check size={12} /> Downloaded
        </span>
      )}
      {state === 'error' && (
        <span style={{ fontSize: '11px', color: 'var(--loss)', display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
          <AlertCircle size={12} /> {error.slice(0, 60)}
        </span>
      )}
    </div>
  );
};

export default ExportPanel;

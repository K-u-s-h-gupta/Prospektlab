import React from 'react';
import { Check, Loader2, Circle, AlertTriangle } from 'lucide-react';

/**
 * Research pipeline timeline — turns SSE wait time into perceived intelligence.
 * Each agent is a glass node that pulses while active, collapses to a result
 * chip with source count when done. Theme-native; pure CSS animation.
 *
 * Stateless/presentational: parent feeds the current agent states (derived from
 * the SSE event stream), this renders them.
 */

export type AgentStatus = 'pending' | 'active' | 'done' | 'error';

export interface AgentStep {
  id: string;
  label: string;
  status: AgentStatus;
  detail?: string;
  sources?: number;
}

interface ResearchTimelineProps {
  steps: AgentStep[];
}

const StatusIcon: React.FC<{ status: AgentStatus }> = ({ status }) => {
  if (status === 'done') return <Check size={13} color="var(--profit)" />;
  if (status === 'active') return <Loader2 size={13} className="rt-spin" color="var(--accent-cyan)" />;
  if (status === 'error') return <AlertTriangle size={13} color="var(--loss)" />;
  return <Circle size={13} color="var(--text-muted)" />;
};

export const ResearchTimeline: React.FC<ResearchTimelineProps> = ({ steps }) => {
  if (!steps || steps.length === 0) return null;
  return (
    <div className="rt-timeline">
      {steps.map((s, i) => (
        <div key={s.id} className={`rt-node rt-${s.status}`}>
          <div className="rt-rail">
            <span className="rt-dot"><StatusIcon status={s.status} /></span>
            {i < steps.length - 1 && <span className="rt-line" />}
          </div>
          <div className="rt-body">
            <div className="rt-label-row">
              <span className="rt-label">{s.label}</span>
              {s.status === 'done' && typeof s.sources === 'number' && (
                <span className="rt-sources">{s.sources} source{s.sources === 1 ? '' : 's'}</span>
              )}
            </div>
            {s.detail && <div className="rt-detail">{s.detail}</div>}
          </div>
        </div>
      ))}
    </div>
  );
};

export default ResearchTimeline;

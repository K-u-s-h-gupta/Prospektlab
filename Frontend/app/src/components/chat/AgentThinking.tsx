import React from 'react';
import { Loader2, CheckCircle2, ChevronRight } from 'lucide-react';
import { AgentEventData } from '../../api/client';

interface AgentThinkingProps {
  events: AgentEventData[];
  isActive: boolean;
}

export const AgentThinking: React.FC<AgentThinkingProps> = ({ events, isActive }) => {
  if (!isActive && events.length === 0) return null;

  // Extract planned vs completed agents from event logs
  const plannedAgents = new Set<string>();
  const activeAgents = new Set<string>();
  const completedAgents = new Set<string>();
  const logs: string[] = [];

  events.forEach(e => {
    const payload = e.payload;
    const agent = payload.agent;
    const status = payload.status;
    const details = payload.details || payload.step || '';

    if (agent) {
      if (status === 'planned') {
        plannedAgents.add(agent);
      } else if (status === 'active') {
        plannedAgents.delete(agent);
        activeAgents.add(agent);
      } else if (status === 'completed') {
        activeAgents.delete(agent);
        completedAgents.add(agent);
      }
    }

    if (details) {
      logs.push(`${agent ? `[${agent}] ` : ''}${details}`);
    }
  });

  const recentLog = logs[logs.length - 1];

  return (
    <div className="glass animate-fade-in-up" style={{
      padding: '14px 18px',
      margin: '8px 0',
      display: 'flex',
      flexDirection: 'column',
      gap: '10px',
      background: 'rgba(15, 23, 42, 0.4)',
      border: '1px solid rgba(255, 255, 255, 0.05)',
      boxShadow: '0 4px 20px rgba(0, 0, 0, 0.2)'
    }}>
      {/* Progress bar */}
      {isActive && (
        <div className="progress-bar-pulse" style={{
          height: '2px',
          width: '100%',
          borderRadius: '2px',
          marginBottom: '8px'
        }} />
      )}
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
        paddingBottom: '8px'
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: '12px',
          fontWeight: 700,
          color: 'var(--text-primary)'
        }}>
          {isActive ? (
            <Loader2 size={13} color="var(--accent-cyan)" style={{ animation: 'spin 1.5s linear infinite' }} />
          ) : (
            <CheckCircle2 size={13} color="var(--profit)" />
          )}
          <span>Mark · Live Pipeline</span>
        </div>
        <span className="badge badge-info" style={{ fontSize: '9px', padding: '2px 6px' }}>
          {events.length} step{events.length === 1 ? '' : 's'} logged
        </span>
      </div>

      {/* Grid displays planned and active agents */}
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '6px',
        fontSize: '10.5px'
      }}>
        {/* Completed */}
        {Array.from(completedAgents).map(agent => (
          <span key={agent} className="badge badge-success" style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '9.5px', padding: '2px 6px' }}>
            <CheckCircle2 size={9} />
            {agent}
          </span>
        ))}

        {/* Active */}
        {Array.from(activeAgents).map(agent => (
          <span key={agent} className="badge badge-info" style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '9.5px', padding: '2px 6px', color: 'var(--accent-indigo)', borderColor: 'rgba(129, 140, 248, 0.2)', background: 'var(--secondaryDim)' }}>
            <Loader2 size={9} style={{ animation: 'spin 1.5s linear infinite' }} />
            {agent} working
          </span>
        ))}

        {/* Planned */}
        {Array.from(plannedAgents).map(agent => (
          <span key={agent} className="badge badge-info" style={{ opacity: 0.5, fontSize: '9.5px', padding: '2px 6px' }}>
            {agent}
          </span>
        ))}
      </div>

      {/* Live Log Console */}
      {recentLog && (
        <div style={{
          backgroundColor: 'rgba(3, 7, 18, 0.4)',
          border: '1px solid rgba(255, 255, 255, 0.04)',
          borderRadius: '8px',
          padding: '8px 12px',
          fontFamily: "var(--font-mono)",
          fontSize: '11px',
          color: 'var(--text-secondary)',
          display: 'flex',
          alignItems: 'flex-start',
          gap: '6px',
          maxHeight: '60px',
          overflowY: 'auto'
        }}>
          <ChevronRight size={11} color="var(--accent-cyan)" style={{ marginTop: '2px', flexShrink: 0 }} />
          <span style={{ wordBreak: 'break-all' }}>{recentLog}</span>
        </div>
      )}
    </div>
  );
};

export default AgentThinking;

import React, { useEffect, useRef } from 'react';
import {
  Activity,
  Brain,
  CheckCircle2,
  Database,
  FileSearch,
  Loader2,
  PenLine,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  Users,
} from 'lucide-react';
import { AgentEventData } from '../../api/client';

interface AgentThinkingProps {
  events: AgentEventData[];
  isActive: boolean;
}

type SummaryKind =
  | 'start'
  | 'target'
  | 'memory'
  | 'data'
  | 'search'
  | 'deep'
  | 'review'
  | 'specialist'
  | 'verify'
  | 'write'
  | 'done';

interface PhaseSummary {
  kind: SummaryKind;
  text: string;
  id: string;
}

const PHASE_COPY: Record<string, { label: string; kind: SummaryKind }> = {
  queued: { label: 'Starting research', kind: 'start' },
  memory: { label: 'Reviewing your prior context', kind: 'memory' },
  enrichment: { label: 'Fetching current market data', kind: 'data' },
  'breadth-survey': { label: 'Checking filings, news, and peer context', kind: 'search' },
  'deep-dive': { label: 'Investigating the important details', kind: 'deep' },
  reflection: { label: 'Checking answer quality', kind: 'review' },
  'multi-agent': { label: 'Running specialist checks', kind: 'specialist' },
  blindspot: { label: 'Filling coverage gaps', kind: 'search' },
  analysis: { label: 'Cross-checking the evidence', kind: 'verify' },
  synthesis: { label: 'Writing your answer', kind: 'write' },
  deep_research: { label: 'Running deep research', kind: 'deep' },
  portfolio_identify: { label: 'Loading your synced holdings', kind: 'data' },
  done: { label: 'Answer ready', kind: 'done' },
};

const INTERNAL_REPLACEMENTS: Array<[RegExp, string]> = [
  [/duckduckgo|bing|searxng/gi, 'trusted sources'],
  [/tenant[-_\s]*scoped/gi, 'your'],
  [/active holdings/gi, 'synced holdings'],
  [/portfolio_identify/gi, 'portfolio check'],
  [/breadth[-_\s]*survey/gi, 'source review'],
  [/deep[-_\s]*dive/gi, 'detail review'],
  [/multi[-_\s]*agent/gi, 'specialist review'],
  [/cross[-_\s]*source/gi, 'evidence'],
  [/query templates?/gi, 'research plan'],
  [/docs?\b/gi, 'sources'],
  [/\bapi(s)?\b/gi, 'data feeds'],
];

const NOTE_BY_PHASE: Record<string, string> = {
  queued: 'Preparing the live research run',
  memory: 'Reviewing useful context from earlier work',
  enrichment: 'Refreshing prices, company data, and market context',
  'breadth-survey': 'Checking filings, news, market data, and peer context',
  'deep-dive': 'Looking closer at the highest-signal evidence',
  reflection: 'Improving coverage before the final answer',
  'multi-agent': 'Asking specialist models to verify the view',
  blindspot: 'Looking for missing risks and overlooked evidence',
  analysis: 'Reconciling conflicts across sources',
  synthesis: 'Turning the evidence into a clear answer',
  portfolio_identify: 'Loading your synced holdings',
};

function cleanText(value: unknown, max = 120): string {
  let text = String(value || '').replace(/\s+/g, ' ').trim();
  for (const [pattern, replacement] of INTERNAL_REPLACEMENTS) {
    text = text.replace(pattern, replacement);
  }
  text = text.replace(/[_-]{2,}/g, ' ');
  text = text.replace(/\s+[:/]\s*$/g, '');
  if (text.length > max) text = `${text.slice(0, max - 1).trim()}...`;
  return text;
}

function phaseSummary(phase: string, note?: unknown): { kind: SummaryKind; text: string } {
  const mapped = PHASE_COPY[phase] || {
    label: cleanText(phase.replace(/[_-]+/g, ' '), 80),
    kind: 'review' as SummaryKind,
  };
  const cleanNote = note ? cleanText(note, 110) : '';
  const phaseNote = NOTE_BY_PHASE[phase] || cleanNote;
  const shouldShowNote = cleanNote && cleanNote !== mapped.label && cleanNote !== phaseNote;
  return {
    kind: mapped.kind,
    text: shouldShowNote ? `${mapped.label} - ${cleanNote}` : (phaseNote || mapped.label),
  };
}

function buildPhaseSummaries(events: AgentEventData[]): PhaseSummary[] {
  const summaries: PhaseSummary[] = [];

  events.forEach((e, idx) => {
    const p = e.payload || {};
    const evType = e.type;

    if (evType === 'session_started') {
      const target = p.target ? ` for ${cleanText(p.target, 50)}` : '';
      summaries.push({ kind: 'start', text: `Starting research${target}`, id: `ps-${idx}` });
    } else if (evType === 'entity_resolved' && p.canonical_name) {
      const ticker = p.yahoo_ticker ? ` (${cleanText(p.yahoo_ticker, 20)})` : '';
      summaries.push({ kind: 'target', text: `Locked onto ${cleanText(p.canonical_name, 56)}${ticker}`, id: `ps-${idx}` });
    } else if (evType === 'phase') {
      const phase = String(p.phase || '');
      const summary = phaseSummary(phase, p.note);
      summaries.push({ ...summary, id: `ps-${idx}` });
    } else if (evType === 'agent_task') {
      const task = cleanText(p.task || p.agent || 'Specialist check', 72);
      summaries.push({ kind: 'specialist', text: task, id: `ps-${idx}` });
    } else if (evType === 'orchestrator_wave') {
      const agents = ((p.agents || []) as string[]).map(a => cleanText(a, 24));
      const shown = agents.slice(0, 3).join(', ');
      const more = agents.length > 3 ? ` +${agents.length - 3}` : '';
      summaries.push({ kind: 'specialist', text: `Specialist review ${p.wave || 1}/${p.wave_total || 1}: ${shown}${more}`, id: `ps-${idx}` });
    } else if (evType === 'subagent_done' && (p.findings_count || 0) > 0) {
      summaries.push({
        kind: 'verify',
        text: `${cleanText(p.display || p.agent || 'Specialist', 40)} found ${p.findings_count} useful signal${p.findings_count === 1 ? '' : 's'}`,
        id: `ps-${idx}`,
      });
    } else if (evType === 'orchestrator_done') {
      summaries.push({ kind: 'verify', text: `Collected ${p.findings_total || 0} specialist signals`, id: `ps-${idx}` });
    } else if (evType === 'verifier_done') {
      summaries.push({ kind: 'verify', text: `Verified the strongest signals and checked source coverage`, id: `ps-${idx}` });
    } else if (evType === 'blindspot_dispatched') {
      summaries.push({ kind: 'search', text: `Checked ${p.queries || 0} remaining coverage gap${p.queries === 1 ? '' : 's'}`, id: `ps-${idx}` });
    } else if (evType === 'reflection_done') {
      summaries.push({ kind: 'review', text: `Improved answer coverage before writing`, id: `ps-${idx}` });
    } else if (evType === 'deep_complete') {
      summaries.push({ kind: 'done', text: `Deep research complete`, id: `ps-${idx}` });
    } else if (evType === 'finding' && p.confidence === 'HIGH') {
      summaries.push({ kind: 'verify', text: `Important signal: ${cleanText(p.headline, 82)}`, id: `ps-${idx}` });
    } else if (evType === 'quality_score' && (p.score || 0) >= 80) {
      summaries.push({ kind: 'review', text: `Coverage check passed`, id: `ps-${idx}` });
    } else if (evType === 'deep_pass') {
      const label = cleanText(p.deep_pass_label || `Research pass ${p.pass_number || ''}/${p.total_passes || ''}`, 72);
      summaries.push({ kind: 'deep', text: `${label} - ${cleanText(p.status || 'running', 20)}`, id: `ps-${idx}` });
    } else if (evType === 'memory_recall') {
      summaries.push({ kind: 'memory', text: `Found ${p.fact_count || 0} relevant prior note${p.fact_count === 1 ? '' : 's'}`, id: `ps-${idx}` });
    } else if (evType === 'query') {
      const status = p.status ? ` - ${cleanText(p.status, 18)}` : '';
      summaries.push({ kind: 'search', text: `Checking ${cleanText(p.query || 'source', 72)}${status}`, id: `ps-${idx}` });
    } else if (evType === 'source') {
      summaries.push({ kind: 'search', text: `Read ${cleanText(p.title || p.domain || 'a source', 72)}`, id: `ps-${idx}` });
    } else if (evType === 'visual_data_ready') {
      summaries.push({ kind: 'data', text: `Prepared query-specific visuals`, id: `ps-${idx}` });
    }
  });

  return summaries;
}

function IconForKind({ kind, active }: { kind: SummaryKind; active?: boolean }) {
  const props = { size: 14, strokeWidth: 2, color: active ? 'var(--accent-cyan)' : 'currentColor' };
  switch (kind) {
    case 'start': return <Sparkles {...props} />;
    case 'target': return <Target {...props} />;
    case 'memory': return <Brain {...props} />;
    case 'data': return <Database {...props} />;
    case 'search': return <Search {...props} />;
    case 'deep': return <FileSearch {...props} />;
    case 'specialist': return <Users {...props} />;
    case 'verify': return <ShieldCheck {...props} />;
    case 'write': return <PenLine {...props} />;
    case 'done': return <CheckCircle2 {...props} />;
    case 'review':
    default: return <Activity {...props} />;
  }
}

export const AgentThinking: React.FC<AgentThinkingProps> = ({ events, isActive }) => {
  if (!isActive && events.length === 0) return null;

  let currentPhase = '';
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type === 'phase') {
      currentPhase = phaseSummary(String(e.payload?.phase || ''), e.payload?.note).text;
      break;
    }
    if (e.type === 'deep_pass') {
      currentPhase = cleanText(e.payload?.deep_pass_label || `Research pass ${e.payload?.pass_number || ''}/${e.payload?.total_passes || ''}`, 84);
      break;
    }
  }
  if (!currentPhase && isActive) currentPhase = 'Preparing the live research run';

  const phaseSummaries = buildPhaseSummaries(events);
  const visibleSummaries = phaseSummaries.slice(-10);

  const scrollRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [visibleSummaries.length]);

  return (
    <div
      className="glass animate-fade-in-up"
      style={{
        width: '100%',
        minWidth: 0,
        overflow: 'hidden',
        padding: '14px 16px',
        margin: '8px 0',
        display: 'flex',
        flexDirection: 'column',
        gap: '10px',
        background: 'rgba(15, 23, 42, 0.42)',
        border: '1px solid rgba(255, 255, 255, 0.06)',
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.2)',
      }}
    >
      {isActive && (
        <div
          className="progress-bar-pulse"
          style={{ height: 2, width: '100%', borderRadius: 2, marginBottom: 4 }}
        />
      )}

      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 10,
          borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
          paddingBottom: 10,
          minWidth: 0,
        }}
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '18px minmax(0, 1fr)',
            columnGap: 8,
            rowGap: 2,
            minWidth: 0,
            flex: '1 1 auto',
          }}
        >
          <span style={{ gridRow: '1 / span 2', display: 'flex', alignItems: 'center', justifyContent: 'center', marginTop: 1 }}>
            {isActive ? (
              <Loader2 size={14} color="var(--accent-cyan)" style={{ animation: 'spin 1.5s linear infinite' }} />
            ) : (
              <CheckCircle2 size={14} color="var(--profit)" />
            )}
          </span>
          <span style={{ fontSize: 12, fontWeight: 800, color: 'var(--text-primary)', minWidth: 0 }}>
            Arthik {isActive ? 'is working' : 'finished'}
          </span>
          {currentPhase && (
            <span
              style={{
                fontSize: 11,
                color: 'var(--text-secondary)',
                fontWeight: 500,
                lineHeight: 1.4,
                minWidth: 0,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
              }}
            >
              {currentPhase}
            </span>
          )}
        </div>
        <span
          className="badge badge-info"
          style={{ fontSize: 9, padding: '2px 6px', flex: '0 0 auto', whiteSpace: 'nowrap', marginTop: 1 }}
        >
          {events.length} step{events.length === 1 ? '' : 's'}
        </span>
      </div>

      {visibleSummaries.length > 0 && (
        <div
          ref={scrollRef}
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 2,
            backgroundColor: 'rgba(3, 7, 18, 0.35)',
            border: '1px solid rgba(255, 255, 255, 0.05)',
            borderRadius: 8,
            padding: '10px 12px',
            maxHeight: 220,
            overflowY: 'auto',
            overflowX: 'hidden',
            minWidth: 0,
          }}
        >
          <div
            style={{
              fontSize: 10,
              fontWeight: 800,
              color: 'var(--text-muted)',
              letterSpacing: '0.04em',
              marginBottom: 6,
              textTransform: 'uppercase',
            }}
          >
            What Arthik is doing
          </div>
          {visibleSummaries.map((summary, i) => {
            const activeRow = i === visibleSummaries.length - 1;
            return (
              <div
                key={summary.id}
                className="animate-fade-in-up"
                style={{
                  display: 'grid',
                  gridTemplateColumns: '18px minmax(0, 1fr)',
                  alignItems: 'start',
                  gap: 8,
                  fontSize: 11.5,
                  lineHeight: 1.45,
                  color: activeRow ? 'var(--text-primary)' : 'var(--text-secondary)',
                  fontWeight: activeRow ? 650 : 450,
                  padding: '6px 0',
                  borderBottom: i < visibleSummaries.length - 1 ? '1px solid rgba(255,255,255,0.04)' : 'none',
                  minWidth: 0,
                }}
              >
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', marginTop: 1 }}>
                  <IconForKind kind={summary.kind} active={activeRow && isActive} />
                </span>
                <span
                  style={{
                    minWidth: 0,
                    whiteSpace: 'normal',
                    wordBreak: 'normal',
                    overflowWrap: 'normal',
                    hyphens: 'none',
                  }}
                >
                  {summary.text}
                </span>
              </div>
            );
          })}
          {isActive && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 10.5,
                color: 'var(--accent-cyan)',
                marginTop: 6,
                fontWeight: 700,
              }}
            >
              <Loader2 size={10} style={{ animation: 'spin 1.5s linear infinite' }} />
              <span>Working on the next step...</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default AgentThinking;

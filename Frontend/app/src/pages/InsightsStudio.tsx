import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  FileSearch,
  Globe,
  Info,
  Newspaper,
  RefreshCcw,
  Send,
  Sparkles,
} from 'lucide-react';
import AppShell from '../components/layout/AppShell';
import { FlashJobMonitor } from '../components/insights/FlashJobMonitor';
import { ArticleQueueTable } from '../components/insights/ArticleQueueTable';
import { DraftReviewDrawer } from '../components/insights/DraftReviewDrawer';
import '../components/insights/insightsStudio.css';
import {
  ArticleListItem,
  FlashGenerationRequest,
  generateFlashArticle,
  getContentAutomationStatus,
  listContentArticles,
  publishContentArticle,
  runContentAutomationNow,
  unpublishContentArticle,
  AutomationStatus,
} from '../api/client';

type ContentType = 'earnings' | 'sebi' | 'trend' | 'company' | 'manual';

interface ActiveJob {
  jobId: string;
  mode: 'research' | 'automation';
  label: string;
}

const CONTENT_TYPE_META: Record<ContentType, { label: string; colour: string; desc: string }> = {
  earnings: { label: 'Earnings', colour: '#34D399', desc: 'Quarterly and annual result analysis' },
  sebi: { label: 'Regulatory', colour: '#FB7185', desc: 'SEBI orders, settlements, and compliance shifts' },
  trend: { label: 'Trend', colour: '#60A5FA', desc: 'Sector, macro, and policy-led market stories' },
  company: { label: 'Company', colour: '#A78BFA', desc: 'Company intelligence with governance and risk context' },
  manual: { label: 'Manual', colour: '#94A3B8', desc: 'Operator-led research topic or angle' },
};

const labelStyle: React.CSSProperties = {
  display: 'block',
  marginBottom: 6,
  fontSize: 11,
  fontWeight: 700,
  color: 'var(--text-muted)',
  letterSpacing: '0.06em',
  textTransform: 'uppercase',
};

const inputStyle: React.CSSProperties = {
  width: '100%',
  padding: '11px 12px',
  borderRadius: 10,
  border: '1px solid rgba(255,255,255,0.08)',
  background: 'rgba(255,255,255,0.03)',
  color: 'var(--text-primary)',
  fontSize: 13,
  outline: 'none',
};

const actionButtonStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 8,
  padding: '10px 14px',
  borderRadius: 10,
  border: '1px solid rgba(96,165,250,0.25)',
  background: 'rgba(96,165,250,0.12)',
  color: 'var(--accent-cyan)',
  cursor: 'pointer',
  fontSize: 12,
  fontWeight: 600,
};

const secondaryButtonStyle: React.CSSProperties = {
  ...actionButtonStyle,
  border: '1px solid rgba(255,255,255,0.08)',
  background: 'rgba(255,255,255,0.03)',
  color: 'var(--text-secondary)',
};

const AUTOMATION_STATUS_LABELS: Record<string, string> = {
  running: 'sweep running',
  scheduled: 'watching 24/7',
  offline: 'scheduler offline',
  disabled: 'automation paused',
  manual_only: 'manual mode',
  idle: 'checking status',
};

const InsightsStudio: React.FC = () => {
  const [contentType, setContentType] = useState<ContentType>('earnings');
  const [target, setTarget] = useState('');
  const [objective, setObjective] = useState('');
  const [sourceUrl, setSourceUrl] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [activeJobs, setActiveJobs] = useState<ActiveJob[]>([]);
  const [articles, setArticles] = useState<ArticleListItem[]>([]);
  const [loadingArticles, setLoadingArticles] = useState(false);
  const [reviewArticle, setReviewArticle] = useState<ArticleListItem | null>(null);

  const [automationStatus, setAutomationStatus] = useState<AutomationStatus | null>(null);
  const [automationLoading, setAutomationLoading] = useState(false);
  const [automationLoadError, setAutomationLoadError] = useState<string | null>(null);

  const [generateLoading, setGenerateLoading] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null);

  const showToast = useCallback((msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type });
    window.setTimeout(() => setToast(null), 3500);
  }, []);

  const loadArticles = useCallback(async () => {
    setLoadingArticles(true);
    try {
      const { items } = await listContentArticles('insights', 100);
      setArticles(items.sort((a, b) => (b.generated_at ?? '').localeCompare(a.generated_at ?? '')));
    } catch (error) {
      console.error('Failed to load articles', error);
    } finally {
      setLoadingArticles(false);
    }
  }, []);

  const loadAutomation = useCallback(async () => {
    try {
      setAutomationLoadError(null);
      const next = await getContentAutomationStatus();
      setAutomationStatus(next);
    } catch (error) {
      console.error('Failed to load automation status', error);
      setAutomationLoadError('Automation status is unavailable. Check the active backend connection.');
    }
  }, []);

  useEffect(() => {
    loadArticles();
    loadAutomation();
  }, [loadArticles, loadAutomation]);

  useEffect(() => {
    const id = window.setInterval(() => {
      loadAutomation();
    }, 30000);
    return () => window.clearInterval(id);
  }, [loadAutomation]);

  const handleGenerate = async () => {
    if (!target.trim()) {
      setGenerateError('A company, event, or topic is required.');
      return;
    }

    setGenerateError(null);
    setGenerateLoading(true);
    try {
      const req: FlashGenerationRequest = {
        mode: 'research',
        content_type: contentType,
        target: target.trim(),
        objective: objective.trim() || undefined,
        source_url: sourceUrl.trim() || undefined,
        route_base: 'insights',
        include_image: true,
        overwrite: true,
      };
      const { job_id } = await generateFlashArticle(req);
      setActiveJobs((prev) => [{ jobId: job_id, mode: 'research', label: target.trim() }, ...prev]);
      showToast(`Research workflow started: ${job_id.slice(0, 8)}`);
    } catch (error: any) {
      setGenerateError(error.message || 'Failed to start research workflow');
      showToast(error.message || 'Failed to start research workflow', 'error');
    } finally {
      setGenerateLoading(false);
    }
  };

  const handleAutomationRun = async () => {
    setAutomationLoading(true);
    try {
      const { job_id } = await runContentAutomationNow();
      setActiveJobs((prev) => [{ jobId: job_id, mode: 'automation', label: 'Official-source sweep' }, ...prev]);
      showToast(`Official-source sweep started: ${job_id.slice(0, 8)}`);
    } catch (error: any) {
      showToast(error.message || 'Failed to start official-source sweep', 'error');
    } finally {
      setAutomationLoading(false);
    }
  };

  const handlePublish = async (article: ArticleListItem) => {
    try {
      await publishContentArticle(article.slug, article.route_base);
      setArticles((prev) => prev.map((entry) => (
        entry.slug === article.slug ? { ...entry, publish_status: 'published' } : entry
      )));
      showToast(`Published: ${article.slug}`);
    } catch (error: any) {
      showToast(error.message || 'Publish failed', 'error');
    }
  };

  const handleUnpublish = async (article: ArticleListItem) => {
    try {
      await unpublishContentArticle(article.slug, article.route_base);
      setArticles((prev) => prev.map((entry) => (
        entry.slug === article.slug ? { ...entry, publish_status: 'draft' } : entry
      )));
      showToast(`Moved back to draft: ${article.slug}`);
    } catch (error: any) {
      showToast(error.message || 'Unpublish failed', 'error');
    }
  };

  const handleJobComplete = async (jobId?: string) => {
    if (jobId) {
      setActiveJobs((prev) => prev.filter((job) => job.jobId !== jobId));
    }
    await Promise.all([loadArticles(), loadAutomation()]);
  };

  const handleStatusChanged = (slug: string, newStatus: 'draft' | 'published') => {
    setArticles((prev) => prev.map((entry) => (
      entry.slug === slug ? { ...entry, publish_status: newStatus } : entry
    )));
    setReviewArticle(null);
  };

  const stats = useMemo(() => ({
    total: articles.length,
    published: articles.filter((item) => item.publish_status === 'published').length,
    drafts: articles.filter((item) => item.publish_status !== 'published').length,
    sourceBacked: articles.filter((item) => item.ikg_covered).length,
  }), [articles]);

  const lastSummary = automationStatus?.last_summary || {};
  const currentRun = automationStatus?.current_run || {};
  const activityLog = (automationStatus?.activity_log || []).slice(0, 6);
  const recentItems = (automationStatus?.recent_items || []).slice(0, 4);
  const automationStatusLabel = automationStatus
    ? (AUTOMATION_STATUS_LABELS[automationStatus.status || 'idle'] || automationStatus.status || 'checking status')
    : (automationLoadError ? 'status unavailable' : 'checking status');
  const automationStatusColour = automationStatus?.status === 'running'
    ? 'var(--accent-cyan)'
    : automationStatus?.status === 'scheduled'
      ? 'var(--profit)'
      : automationStatus?.status === 'offline'
        ? 'var(--loss)'
        : automationStatus?.status === 'disabled' || automationStatus?.status === 'manual_only'
          ? '#FBBF24'
          : automationLoadError
            ? 'var(--loss)'
            : '#FBBF24';
  const lastRunLabel = automationStatus?.last_completed_at
    ? new Date(automationStatus.last_completed_at).toLocaleString()
    : automationStatus?.scheduler_status === 'running'
      ? 'waiting for first scheduled sweep'
      : automationLoadError
        ? 'backend status unavailable'
        : 'not available';
  const heartbeatLabel = automationStatus?.scheduler_last_heartbeat_at
    ? new Date(automationStatus.scheduler_last_heartbeat_at).toLocaleString()
    : 'not available';
  const nextRunLabel = automationStatus?.next_scheduled_run_at
    ? new Date(automationStatus.next_scheduled_run_at).toLocaleString()
    : 'not available';
  const currentPhaseLabel = currentRun.phase
    ? String(currentRun.phase).replace(/_/g, ' ')
    : automationStatus?.status === 'running'
      ? 'starting'
      : 'standing by';
  const currentFocusParts = [currentRun.company, currentRun.source ? String(currentRun.source).toUpperCase() : ''].filter(Boolean);
  const currentFocusLabel = currentFocusParts.length > 0 ? currentFocusParts.join(' - ') : 'Queue-level monitoring';
  const currentEvidenceLabel = [
    currentRun.attachment_type ? `attachment ${String(currentRun.attachment_type).replace(/_/g, ' ')}` : '',
    currentRun.attachment_extraction_status ? `status ${String(currentRun.attachment_extraction_status).replace(/_/g, ' ')}` : '',
    currentRun.attachment_parser ? `parser ${String(currentRun.attachment_parser).replace(/_/g, ' ')}` : '',
  ].filter(Boolean).join(' - ');
  const fallbackStatusLabel = automationStatus?.fallback_status
    ? String(automationStatus.fallback_status).replace(/_/g, ' ')
    : 'standing by';
  const fallbackDailyTarget = automationStatus?.fallback_daily_target ?? 10;
  const fallbackPublishedToday = automationStatus?.fallback_published_today ?? automationStatus?.fallback_daily_count ?? 0;
  const fallbackGeneratedToday = automationStatus?.fallback_generated_today ?? 0;
  const fallbackHeldToday = automationStatus?.fallback_held_today ?? 0;
  const fallbackRemainingToday = automationStatus?.fallback_remaining_today ?? Math.max(0, fallbackDailyTarget - fallbackPublishedToday);
  const fallbackQualifiedTopics = automationStatus?.fallback_qualified_topics ?? 0;
  const fallbackReviewReasons = Array.isArray(automationStatus?.fallback_review_reasons)
    ? automationStatus?.fallback_review_reasons ?? []
    : [];
  const fallbackNextLabel = automationStatus?.next_fallback_after
    ? new Date(automationStatus.next_fallback_after).toLocaleString()
    : 'eligible now';
  const searchConsole = automationStatus?.search_console;
  const searchConsoleLabel = !searchConsole?.enabled
    ? 'disabled'
    : !searchConsole?.configured
      ? 'needs setup'
      : searchConsole?.error
        ? 'connected with warnings'
        : 'connected';
  const searchConsoleDetail = !searchConsole?.enabled
    ? 'Enable Search Console credentials to submit sitemaps and track article performance.'
    : searchConsole?.error
      ? searchConsole.error
      : searchConsole?.site_url || 'Connected to the verified site property.';

  return (
    <AppShell title="Insights Studio">
      <div className="insights-studio">
        <div className="insights-studio__header">
          <div className="insights-studio__header-row">
            <div className="insights-studio__title-group">
              <div className="insights-studio__title-line">
                <Newspaper size={20} color="var(--accent-cyan)" />
                <span className="insights-studio__title">Insights Studio</span>
                <span className="insights-studio__badge">
                  <Sparkles size={12} />
                  Editorial Research
                </span>
              </div>
              <p className="insights-studio__subtitle">
                Each story is drafted for clean public reading, checked for evidence and compliance,
                and then routed through publication gates. Official filings stay first in line, while
                fallback market coverage keeps the archive moving only when the quality bar is met.
              </p>
            </div>

            <div className="insights-studio__stats">
              {[
                { label: 'Total', value: stats.total, colour: 'var(--text-primary)' },
                { label: 'Published', value: stats.published, colour: 'var(--profit)' },
                { label: 'Drafts', value: stats.drafts, colour: '#FBBF24' },
                { label: 'Source-backed', value: stats.sourceBacked, colour: 'var(--accent-cyan)' },
              ].map((item) => (
                <div key={item.label} className="insights-studio__stat">
                  <div className="insights-studio__stat-value" style={{ color: item.colour }}>{item.value}</div>
                  <div className="insights-studio__stat-label">{item.label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="insights-studio__main">
          <aside className="insights-studio__sidebar">
            <section className="data-panel">
              <div className="data-panel-head">
                <span className="data-panel-title">Generate Research Article</span>
              </div>
              <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div className="insights-panel-copy">
                  All articles use the same deep editorial workflow: official-source retrieval,
                  verified context enrichment, structured drafting, paragraph-level review, and
                  auto-publish only when the draft clears the quality gate.
                </div>

                <div>
                  <label style={labelStyle}>Content Type</label>
                  <div className="insights-type-grid">
                    {(Object.keys(CONTENT_TYPE_META) as ContentType[]).map((entry) => {
                      const meta = CONTENT_TYPE_META[entry];
                      const active = contentType === entry;
                      return (
                        <button
                          key={entry}
                          type="button"
                          className="insights-type-button"
                          onClick={() => setContentType(entry)}
                          style={{
                            borderColor: active ? `${meta.colour}44` : 'rgba(255,255,255,0.08)',
                            background: active ? `${meta.colour}14` : 'transparent',
                          }}
                        >
                          <div style={{ fontSize: 12, fontWeight: 700, color: active ? meta.colour : 'var(--text-primary)' }}>
                            {meta.label}
                          </div>
                          <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                            {meta.desc}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div>
                  <label style={labelStyle}>
                    {contentType === 'trend' || contentType === 'manual' ? 'Topic' : 'Company / Subject'}
                  </label>
                  <input
                    value={target}
                    onChange={(event) => setTarget(event.target.value)}
                    placeholder={
                      contentType === 'earnings' ? 'e.g. Infosys Q3 FY26 results' :
                      contentType === 'sebi' ? 'e.g. SEBI order against a listed company' :
                      contentType === 'trend' ? 'e.g. Domestic defence capex cycle' :
                      contentType === 'company' ? 'e.g. Reliance Industries' :
                      'e.g. Midcap chemicals pricing reset'
                    }
                    style={inputStyle}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') handleGenerate();
                    }}
                  />
                </div>

                <button
                  type="button"
                  onClick={() => setShowAdvanced((prev) => !prev)}
                  style={{ ...secondaryButtonStyle, justifyContent: 'space-between' }}
                >
                  <span>Advanced context</span>
                  <span>{showAdvanced ? 'Hide' : 'Show'}</span>
                </button>

                {showAdvanced && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <div>
                      <label style={labelStyle}>Custom Objective</label>
                      <textarea
                        value={objective}
                        onChange={(event) => setObjective(event.target.value)}
                        placeholder="Add a sharper editorial angle, publication goal, or scenario to validate."
                        rows={3}
                        style={{ ...inputStyle, resize: 'vertical', minHeight: 86, fontFamily: 'inherit' }}
                      />
                    </div>
                    <div>
                      <label style={labelStyle}>Primary Source URL</label>
                      <input
                        value={sourceUrl}
                        onChange={(event) => setSourceUrl(event.target.value)}
                        placeholder="https://www.bseindia.com/..."
                        style={inputStyle}
                      />
                    </div>
                  </div>
                )}

                {generateError && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--loss)', fontSize: 12 }}>
                    <AlertTriangle size={14} />
                    <span>{generateError}</span>
                  </div>
                )}

                <button
                  type="button"
                  onClick={handleGenerate}
                  disabled={generateLoading || !target.trim()}
                  style={{
                    ...actionButtonStyle,
                    width: '100%',
                    opacity: generateLoading || !target.trim() ? 0.6 : 1,
                    cursor: generateLoading || !target.trim() ? 'not-allowed' : 'pointer',
                  }}
                >
                  {generateLoading ? <RefreshCcw size={14} className="animate-spin-custom" /> : <Send size={14} />}
                  <span>{generateLoading ? 'Starting workflow...' : 'Start research article'}</span>
                </button>

                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: 12, borderRadius: 10, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                  <Info size={14} color="var(--text-muted)" style={{ marginTop: 2, flexShrink: 0 }} />
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6 }}>
                    The editorial gate checks headings, paragraphs, sourcing, compliance language, and
                    publish urgency before a draft goes live. Weak drafts stay in review instead of
                    bypassing the threshold.
                  </div>
                </div>
              </div>
            </section>

            {activeJobs.length > 0 && (
              <section>
                <div style={{ marginBottom: 8, fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  Active Workflows
                </div>
                <div className="insights-job-stack">
                  {activeJobs.map((job) => (
                    <FlashJobMonitor
                      key={job.jobId}
                      jobId={job.jobId}
                      mode={job.mode}
                      label={job.label}
                      onComplete={() => handleJobComplete(job.jobId)}
                    />
                  ))}
                </div>
              </section>
            )}

            <section className="data-panel">
              <div className="data-panel-head">
                <span className="data-panel-title">Automation Health</span>
              </div>
              <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div className="insights-form-grid">
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Status</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: automationStatusColour }}>
                      {automationStatusLabel}
                    </div>
                    <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>
                      Last run {lastRunLabel}
                    </div>
                  </div>
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>24/7 Mode</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
                      {automationStatus?.automation_label || 'Official-source monitor'}
                    </div>
                    <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>
                      {automationStatus?.status_detail || automationLoadError || 'The monitor chooses publishable topics from official-source updates.'}
                    </div>
                  </div>
                </div>

                <div className="insights-health-badges">
                  {(['nse', 'bse', 'sebi'] as const).map((source) => {
                    const health = automationStatus?.source_health?.[source] || {};
                    const sourceOk = !health.last_error;
                    return (
                      <span
                        key={source}
                        className="insights-health-badge"
                        style={{ color: sourceOk ? 'var(--profit)' : '#FBBF24' }}
                      >
                        <Activity size={12} />
                        {source}
                      </span>
                    );
                  })}
                </div>

                <div className="insights-automation-grid">
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Current Phase</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', textTransform: 'capitalize' }}>{currentPhaseLabel}</div>
                    <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>{currentFocusLabel}</div>
                  </div>
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Next Sweep</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>{nextRunLabel}</div>
                  </div>
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Scheduler Heartbeat</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>{heartbeatLabel}</div>
                  </div>
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Discovered</div>
                    <div style={{ fontSize: 18, fontWeight: 700 }}>{lastSummary.discovered ?? 0}</div>
                  </div>
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Published / Held</div>
                    <div style={{ fontSize: 18, fontWeight: 700 }}>{lastSummary.published ?? 0} / {lastSummary.drafts ?? 0}</div>
                  </div>
                </div>

                <div className="insights-automation-grid">
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Batch Progress</div>
                    <div style={{ fontSize: 18, fontWeight: 700 }}>
                      {currentRun.companies_scanned ?? 0} / {currentRun.companies_total ?? lastSummary.companies_scanned ?? 0}
                    </div>
                  </div>
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Live Decisions</div>
                    <div style={{ fontSize: 18, fontWeight: 700 }}>
                      {(currentRun.generated ?? 0) + (currentRun.skipped_seen ?? 0) + (currentRun.skipped_low_value ?? 0)}
                    </div>
                  </div>
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Fallback Desk</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', textTransform: 'capitalize' }}>
                      {fallbackStatusLabel}
                    </div>
                    <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>
                      {fallbackPublishedToday}/{fallbackDailyTarget} published today - {fallbackRemainingToday} remaining
                    </div>
                    <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>
                      Generated {fallbackGeneratedToday}, held {fallbackHeldToday}, next window {fallbackNextLabel}
                    </div>
                  </div>
                  <div className="insights-automation-stat">
                    <div style={{ ...labelStyle, marginBottom: 4 }}>Search Console</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', textTransform: 'capitalize' }}>
                      {searchConsoleLabel}
                    </div>
                    <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted)' }}>
                      {searchConsoleDetail}
                    </div>
                  </div>
                </div>

                {(automationStatus?.fallback_last_action || automationStatus?.fallback_candidates_considered) && (
                  <div className="insights-panel-copy">
                    Fallback activity: {automationStatus?.fallback_last_action || 'No fallback action recorded yet.'}
                    {' '}Candidates reviewed this cycle: {automationStatus?.fallback_candidates_considered ?? 0}. Qualified topics: {fallbackQualifiedTopics}.
                  </div>
                )}

                {fallbackReviewReasons.length > 0 && (
                  <div className="insights-panel-copy">
                    Recent fallback hold reasons: {fallbackReviewReasons.map((reason) => String(reason).replace(/_/g, ' ')).join(', ')}.
                  </div>
                )}

                {(currentEvidenceLabel || currentRun.review_reason) && (
                  <div className="insights-panel-copy">
                    {currentEvidenceLabel ? `Evidence pipeline: ${currentEvidenceLabel}. ` : ''}
                    {currentRun.review_reason ? `Current review reason: ${String(currentRun.review_reason).replace(/_/g, ' ')}.` : ''}
                  </div>
                )}

                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  <button type="button" onClick={loadAutomation} style={secondaryButtonStyle}>
                    <RefreshCcw size={14} />
                    Refresh status
                  </button>
                  <button type="button" onClick={handleAutomationRun} disabled={automationLoading} style={actionButtonStyle}>
                    {automationLoading ? <RefreshCcw size={14} className="animate-spin-custom" /> : <FileSearch size={14} />}
                    Run extra sweep now
                  </button>
                  <a
                    href="/insights/research/"
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ ...secondaryButtonStyle, textDecoration: 'none' }}
                  >
                    <Globe size={14} />
                    Public research
                  </a>
                </div>

                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, padding: 12, borderRadius: 10, background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)' }}>
                  <Info size={14} color="var(--text-muted)" style={{ marginTop: 2, flexShrink: 0 }} />
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.6 }}>
                    Automatic publishing is limited to official-source topics that clear the editorial gate. That includes earnings, company filings, and SEBI-driven regulatory stories from NSE, BSE, and SEBI feeds. Manual topics and general web news still need to be started from the form above.
                  </div>
                </div>

                <div className="insights-automation-list">
                  {activityLog.length === 0 ? (
                    <div className="insights-panel-copy">Live automation steps will appear here while the monitor is scanning and generating.</div>
                  ) : (
                    activityLog.map((item, index) => (
                      <div key={`${item.timestamp || index}-${item.message || 'activity'}`} className="insights-automation-item">
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', overflowWrap: 'anywhere' }}>
                            {item.message || 'Automation update'}
                          </div>
                          <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                            {item.phase ? String(item.phase).replace(/_/g, ' ') : 'status'} - {item.timestamp ? new Date(item.timestamp).toLocaleString() : 'timestamp unavailable'}
                          </div>
                        </div>
                        <div style={{ fontSize: 11, fontWeight: 700, color: item.level === 'error' ? 'var(--loss)' : item.level === 'warning' ? '#FBBF24' : item.level === 'success' ? 'var(--profit)' : 'var(--accent-cyan)', textTransform: 'uppercase' }}>
                          {item.level || 'info'}
                        </div>
                      </div>
                    ))
                  )}
                </div>

                <div className="insights-automation-list">
                  {recentItems.length === 0 ? (
                    <div className="insights-panel-copy">Recent automatic topic decisions will appear here after the next scheduled sweep.</div>
                  ) : (
                    recentItems.map((item, index) => (
                      <div key={`${item.slug || item.title || index}`} className="insights-automation-item">
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', overflowWrap: 'anywhere' }}>
                            {item.title || item.slug || 'Untitled item'}
                          </div>
                          <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                            {item.source?.toUpperCase()} - {item.timestamp ? new Date(item.timestamp).toLocaleString() : 'timestamp unavailable'}
                          </div>
                          {item.attachment_extraction_status || item.attachment_parser || item.attachment_type ? (
                            <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-muted)', overflowWrap: 'anywhere' }}>
                              {[
                                item.attachment_type ? `attachment ${String(item.attachment_type).replace(/_/g, ' ')}` : '',
                                item.attachment_extraction_status ? `status ${String(item.attachment_extraction_status).replace(/_/g, ' ')}` : '',
                                item.attachment_parser ? `parser ${String(item.attachment_parser).replace(/_/g, ' ')}` : '',
                              ].filter(Boolean).join(' - ')}
                            </div>
                          ) : null}
                          {item.review_reason || item.reason ? (
                            <div style={{ marginTop: 4, fontSize: 11, color: item.status === 'failed' ? 'var(--loss)' : '#8B6F47', lineHeight: 1.5, overflowWrap: 'anywhere' }}>
                              {String(item.review_reason || item.reason).replace(/_/g, ' ')}
                            </div>
                          ) : null}
                        </div>
                        <div style={{ fontSize: 11, fontWeight: 700, color: item.status === 'published' ? 'var(--profit)' : item.status === 'failed' ? 'var(--loss)' : '#FBBF24', textTransform: 'uppercase' }}>
                          {item.status || 'queued'}
                        </div>
                      </div>
                    ))
                  )}
                </div>

                {automationStatus?.last_error && (
                  <div style={{ fontSize: 11, color: 'var(--loss)', lineHeight: 1.5 }}>
                    {automationStatus.last_error}
                  </div>
                )}
              </div>
            </section>
          </aside>

          <div className="insights-studio__content">
            <ArticleQueueTable
              articles={articles}
              loading={loadingArticles}
              onRefresh={loadArticles}
              onPreview={setReviewArticle}
              onPublish={handlePublish}
              onUnpublish={handleUnpublish}
            />
          </div>
        </div>

        {toast && (
          <div
            style={{
              position: 'fixed',
              bottom: 18,
              right: 18,
              left: 'auto',
              maxWidth: 'min(420px, calc(100vw - 32px))',
              zIndex: 1200,
              padding: '12px 14px',
              borderRadius: 10,
              border: `1px solid ${toast.type === 'success' ? 'rgba(52,211,153,0.3)' : 'rgba(251,113,133,0.3)'}`,
              background: toast.type === 'success' ? 'rgba(52,211,153,0.12)' : 'rgba(251,113,133,0.12)',
              color: toast.type === 'success' ? 'var(--profit)' : 'var(--loss)',
              fontSize: 12,
              fontWeight: 600,
              overflowWrap: 'anywhere',
            }}
          >
            {toast.msg}
          </div>
        )}

        <DraftReviewDrawer
          article={reviewArticle}
          onClose={() => setReviewArticle(null)}
          onStatusChanged={handleStatusChanged}
        />
      </div>
    </AppShell>
  );
};

export default InsightsStudio;

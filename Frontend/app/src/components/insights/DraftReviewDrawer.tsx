import React, { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ExternalLink, FileText, Loader2, ShieldCheck, X } from 'lucide-react';
import { ArticleDetail, ArticleListItem, getContentArticle } from '../../api/client';

interface DraftReviewDrawerProps {
  article: ArticleListItem | null;
  onClose: () => void;
  onStatusChanged: (slug: string, newStatus: 'draft' | 'published') => void;
}

type DrawerTab = 'overview' | 'editorial' | 'sections';

const chipStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  padding: '6px 10px',
  borderRadius: 999,
  border: '1px solid rgba(255,255,255,0.08)',
  background: 'rgba(255,255,255,0.04)',
  color: 'var(--text-secondary)',
  fontSize: 11,
  fontWeight: 600,
};

const metricCardStyle: React.CSSProperties = {
  padding: 14,
  borderRadius: 14,
  border: '1px solid rgba(255,255,255,0.06)',
  background: 'rgba(255,255,255,0.03)',
};

const cardStyle: React.CSSProperties = {
  padding: 16,
  borderRadius: 16,
  border: '1px solid rgba(255,255,255,0.06)',
  background: 'rgba(255,255,255,0.03)',
};

function formatIssueLocation(location: string | undefined): string {
  if (!location) return 'Article';
  return location
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export const DraftReviewDrawer: React.FC<DraftReviewDrawerProps> = ({
  article,
  onClose,
  onStatusChanged: _onStatusChanged,
}) => {
  const [tab, setTab] = useState<DrawerTab>('overview');
  const [detail, setDetail] = useState<ArticleDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!article) return undefined;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [article, onClose]);

  useEffect(() => {
    if (!article) {
      setDetail(null);
      setError(null);
      setLoading(false);
      setTab('overview');
      return;
    }

    let cancelled = false;
    setTab('overview');
    setLoading(true);
    setError(null);

    getContentArticle(article.slug, article.route_base || 'insights')
      .then((next) => {
        if (!cancelled) {
          setDetail(next);
        }
      })
      .catch((err: any) => {
        if (!cancelled) {
          setError(err?.message || 'Unable to load article review.');
          setDetail(null);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [article]);

  const activeArticle = detail || article;
  const editorialReview = (detail?.editorial_review || article?.editorial_review || {}) as Record<string, any>;
  const sections = useMemo(() => {
    const articlePayload = detail?.article as Record<string, any> | undefined;
    const list = articlePayload?.sections;
    return Array.isArray(list) ? list : [];
  }, [detail]);
  const sources = useMemo(() => (Array.isArray(detail?.sources_used) ? detail?.sources_used : []), [detail]);

  if (!article || !activeArticle) {
    return null;
  }

  const localArticlePath = `/${activeArticle.route_base || 'insights'}/${activeArticle.slug}/`;
  const totalScore = activeArticle.editorial_quality_score ?? activeArticle.quality_score ?? activeArticle.confidence_score ?? 0;
  const urgencyScore = activeArticle.publish_urgency_score ?? editorialReview.urgency_score ?? 0;
  const publishReady = editorialReview.ready_to_publish !== false;
  const issues = Array.isArray(editorialReview.issues) ? editorialReview.issues : [];
  const reviewSections = Array.isArray(editorialReview.sections) ? editorialReview.sections : [];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Article review"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1500,
        display: 'flex',
        justifyContent: 'flex-end',
        background: 'rgba(2, 6, 23, 0.58)',
      }}
      onClick={onClose}
    >
      <aside
        className="insights-drawer"
        style={{ width: 'min(760px, 100vw)' }}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="insights-drawer__body">
          <div className="insights-drawer__header">
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, minWidth: 0, flex: 1 }}>
              <div
                style={{
                  width: 42,
                  height: 42,
                  borderRadius: 12,
                  display: 'grid',
                  placeItems: 'center',
                  background: 'rgba(56,189,248,0.12)',
                  color: 'var(--accent-cyan)',
                  flexShrink: 0,
                }}
              >
                <FileText size={18} />
              </div>

              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                  Editorial review
                </div>
                <h2 style={{ margin: '8px 0 0', fontSize: 24, lineHeight: 1.12, overflowWrap: 'anywhere' }}>
                  {activeArticle.title || activeArticle.slug}
                </h2>
                <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  <span style={chipStyle}>{(activeArticle.content_type || 'manual').toUpperCase()}</span>
                  <span style={chipStyle}>{activeArticle.publish_status === 'published' ? 'Published' : 'Draft'}</span>
                  <span style={{ ...chipStyle, color: publishReady ? 'var(--profit)' : '#FBBF24' }}>
                    {publishReady ? 'Ready to publish' : 'Held in review'}
                  </span>
                  {activeArticle.ikg_covered && (
                    <span style={{ ...chipStyle, color: 'var(--accent-cyan)' }}>
                      <ShieldCheck size={12} style={{ marginRight: 6 }} />
                      Source-backed
                    </span>
                  )}
                </div>
              </div>
            </div>

            <button
              type="button"
              onClick={onClose}
              aria-label="Close review drawer"
              style={{
                border: '1px solid rgba(255,255,255,0.08)',
                background: 'transparent',
                color: 'var(--text-secondary)',
                borderRadius: 10,
                width: 36,
                height: 36,
                display: 'grid',
                placeItems: 'center',
                cursor: 'pointer',
                flexShrink: 0,
              }}
            >
              <X size={16} />
            </button>
          </div>

          <div className="insights-tab-strip">
            {([
              ['overview', 'Overview'],
              ['editorial', 'Editorial Review'],
              ['sections', 'Sections'],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                style={{
                  padding: '8px 12px',
                  borderRadius: 999,
                  border: `1px solid ${tab === key ? 'rgba(96,165,250,0.35)' : 'rgba(255,255,255,0.06)'}`,
                  background: tab === key ? 'rgba(96,165,250,0.12)' : 'transparent',
                  color: tab === key ? 'var(--accent-cyan)' : 'var(--text-muted)',
                  fontSize: 11,
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                {label}
              </button>
            ))}
          </div>

          {loading ? (
            <div style={{ ...cardStyle, display: 'flex', alignItems: 'center', gap: 10, color: 'var(--text-secondary)' }}>
              <Loader2 size={16} className="animate-spin-custom" />
              Loading article review...
            </div>
          ) : error ? (
            <div style={{ ...cardStyle, display: 'flex', alignItems: 'flex-start', gap: 10, color: 'var(--loss)' }}>
              <AlertTriangle size={16} style={{ marginTop: 2, flexShrink: 0 }} />
              <div>{error}</div>
            </div>
          ) : (
            <>
              {tab === 'overview' && (
                <div className="insights-drawer__stack">
                  <div className="insights-drawer__metrics">
                    <div style={metricCardStyle}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                        Quality
                      </div>
                      <div style={{ marginTop: 8, fontSize: 24, fontWeight: 700, color: totalScore >= 90 ? 'var(--profit)' : totalScore >= 75 ? 'var(--accent-cyan)' : '#FBBF24' }}>
                        {totalScore}
                      </div>
                    </div>
                    <div style={metricCardStyle}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                        Publish Urgency
                      </div>
                      <div style={{ marginTop: 8, fontSize: 24, fontWeight: 700, color: urgencyScore >= 70 ? 'var(--profit)' : '#FBBF24' }}>
                        {urgencyScore}
                      </div>
                    </div>
                    <div style={metricCardStyle}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                        Revision Round
                      </div>
                      <div style={{ marginTop: 8, fontSize: 24, fontWeight: 700, color: 'var(--text-primary)' }}>
                        {editorialReview.revision_round ?? 0}
                      </div>
                    </div>
                  </div>

                  {activeArticle.description && (
                    <div style={cardStyle}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
                        Description
                      </div>
                      <div style={{ color: 'var(--text-secondary)', lineHeight: 1.65 }}>
                        {activeArticle.description}
                      </div>
                    </div>
                  )}

                  <div className="insights-drawer__grid">
                    <div style={cardStyle}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
                        Route
                      </div>
                      <div style={{ color: 'var(--text-primary)', overflowWrap: 'anywhere' }}>{localArticlePath}</div>
                    </div>
                    <div style={cardStyle}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
                        Generated
                      </div>
                      <div style={{ color: 'var(--text-primary)' }}>
                        {activeArticle.generated_at ? new Date(activeArticle.generated_at).toLocaleString() : 'Timestamp unavailable'}
                      </div>
                    </div>
                  </div>

                  <div style={cardStyle}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
                      Source Evidence
                    </div>
                    {sources.length === 0 ? (
                      <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Detailed source evidence is not available for this item yet.</div>
                    ) : (
                      <div className="insights-drawer__stack" style={{ gap: 10 }}>
                        {sources.map((source, index) => (
                          <a
                            key={`${source.url}-${index}`}
                            href={source.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                              display: 'flex',
                              justifyContent: 'space-between',
                              gap: 12,
                              padding: '10px 12px',
                              borderRadius: 12,
                              border: '1px solid rgba(255,255,255,0.05)',
                              background: 'rgba(255,255,255,0.02)',
                              color: 'var(--text-primary)',
                              textDecoration: 'none',
                            }}
                          >
                            <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}>{source.title || source.url}</span>
                            <ExternalLink size={14} style={{ flexShrink: 0, color: 'var(--accent-cyan)' }} />
                          </a>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {tab === 'editorial' && (
                <div className="insights-drawer__stack">
                  <div className="insights-drawer__metrics">
                    {[
                      ['Structure', editorialReview.structure_score ?? '-'],
                      ['Copy', editorialReview.copy_score ?? '-'],
                      ['Grounding', editorialReview.source_score ?? '-'],
                      ['Compliance', editorialReview.compliance_score ?? '-'],
                    ].map(([label, value]) => (
                      <div key={label} style={metricCardStyle}>
                        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                          {label}
                        </div>
                        <div style={{ marginTop: 8, fontSize: 22, fontWeight: 700, color: 'var(--text-primary)' }}>
                          {value}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div style={cardStyle}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
                      Decision
                    </div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: publishReady ? 'var(--profit)' : '#FBBF24' }}>
                      {publishReady ? 'Editorial gate cleared this draft.' : 'Editorial gate is still holding this draft.'}
                    </div>
                    {issues.length > 0 && (
                      <div className="insights-drawer__stack" style={{ marginTop: 14, gap: 10 }}>
                        {issues.map((issue, index) => (
                          <div
                            key={`${issue.code}-${index}`}
                            className="insights-drawer__issue"
                            style={{
                              borderColor:
                                issue.severity === 'critical'
                                  ? 'rgba(251,113,133,0.28)'
                                  : issue.severity === 'warning'
                                    ? 'rgba(251,191,36,0.28)'
                                    : 'rgba(255,255,255,0.06)',
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                              <span
                                style={{
                                  ...chipStyle,
                                  color:
                                    issue.severity === 'critical'
                                      ? 'var(--loss)'
                                      : issue.severity === 'warning'
                                        ? '#FBBF24'
                                        : 'var(--text-secondary)',
                                }}
                              >
                                {(issue.severity || 'info').toUpperCase()}
                              </span>
                              <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>
                                {formatIssueLocation(issue.location)}
                              </span>
                            </div>
                            <div style={{ marginTop: 10, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                              {issue.message}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                    {issues.length === 0 && (
                      <div style={{ marginTop: 10, color: 'var(--text-muted)' }}>
                        No editorial issues were stored for this draft.
                      </div>
                    )}
                  </div>

                  {reviewSections.length > 0 && (
                    <div style={cardStyle}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
                        Section Checks
                      </div>
                      <div className="insights-drawer__stack" style={{ gap: 12 }}>
                        {reviewSections.map((section, index) => (
                          <div key={`${section.heading}-${index}`} className="insights-drawer__section-card">
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                              <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{section.heading}</div>
                              <span style={chipStyle}>Heading {section.heading_score ?? '-'}</span>
                            </div>
                            {Array.isArray(section.paragraphs) && section.paragraphs.length > 0 && (
                              <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                                {section.paragraphs.map((paragraph: any, paragraphIndex: number) => (
                                  <span key={paragraphIndex} style={chipStyle}>
                                    Paragraph {paragraph.paragraph_index ?? paragraphIndex + 1}: {paragraph.score ?? '-'}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {tab === 'sections' && (
                <div className="insights-drawer__stack">
                  {sections.length === 0 ? (
                    <div style={cardStyle}>
                      <div style={{ color: 'var(--text-muted)' }}>
                        The stored article body is not available for this draft yet.
                      </div>
                    </div>
                  ) : (
                    sections.map((section: any, index: number) => (
                      <div key={`${section.heading || 'section'}-${index}`} style={cardStyle} className="insights-drawer__section-card">
                        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
                          Section {index + 1}
                        </div>
                        <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 12 }}>
                          {section.heading || `Section ${index + 1}`}
                        </div>
                        {Array.isArray(section.paragraphs) && section.paragraphs.length > 0 && (
                          <div className="insights-drawer__stack" style={{ gap: 12 }}>
                            {section.paragraphs.map((paragraph: string, paragraphIndex: number) => (
                              <div key={paragraphIndex} style={{ color: 'var(--text-secondary)', lineHeight: 1.7 }}>
                                {paragraph}
                              </div>
                            ))}
                          </div>
                        )}
                        {Array.isArray(section.bullets) && section.bullets.length > 0 && (
                          <ul style={{ margin: '14px 0 0', paddingLeft: 18, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
                            {section.bullets.map((bullet: string, bulletIndex: number) => (
                              <li key={bulletIndex}>{bullet}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    ))
                  )}
                </div>
              )}
            </>
          )}

          <div className="insights-drawer__footer">
            <a
              href={localArticlePath}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 8,
                minHeight: 42,
                padding: '0 14px',
                borderRadius: 10,
                border: '1px solid rgba(56,189,248,0.24)',
                background: 'rgba(56,189,248,0.1)',
                color: 'var(--accent-cyan)',
                textDecoration: 'none',
                fontSize: 13,
                fontWeight: 600,
              }}
            >
              <ExternalLink size={14} />
              Open article
            </a>

            <button
              type="button"
              onClick={onClose}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                minHeight: 42,
                padding: '0 14px',
                borderRadius: 10,
                border: '1px solid rgba(255,255,255,0.08)',
                background: 'transparent',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: 600,
              }}
            >
              Close
            </button>
          </div>
        </div>
      </aside>
    </div>
  );
};

export default DraftReviewDrawer;

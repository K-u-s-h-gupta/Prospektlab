import React, { useMemo, useState } from 'react';
import {
  CheckCircle2,
  ExternalLink,
  Eye,
  FileCheck2,
  Globe,
  Lock,
  RefreshCcw,
  ShieldCheck,
} from 'lucide-react';
import { ArticleListItem } from '../../api/client';

interface ArticleQueueTableProps {
  articles: ArticleListItem[];
  loading: boolean;
  onRefresh: () => void;
  onPreview: (article: ArticleListItem) => void;
  onPublish: (article: ArticleListItem) => void;
  onUnpublish: (article: ArticleListItem) => void;
}

const TYPE_COLOURS: Record<string, string> = {
  earnings: '#34D399',
  sebi: '#FB7185',
  trend: '#60A5FA',
  company: '#A78BFA',
  manual: '#94A3B8',
};

const actionButtonStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 6,
  padding: '7px 9px',
  borderRadius: 8,
  border: '1px solid rgba(255,255,255,0.08)',
  background: 'transparent',
  color: 'var(--text-secondary)',
  cursor: 'pointer',
  textDecoration: 'none',
};

export const ArticleQueueTable: React.FC<ArticleQueueTableProps> = ({
  articles, loading, onRefresh, onPreview, onPublish, onUnpublish,
}) => {
  const [tab, setTab] = useState<'all' | 'drafts' | 'published'>('all');

  const filtered = useMemo(() => articles.filter((article) => {
    if (tab === 'drafts') return article.publish_status !== 'published';
    if (tab === 'published') return article.publish_status === 'published';
    return true;
  }), [articles, tab]);

  const counts = useMemo(() => ({
    all: articles.length,
    drafts: articles.filter((article) => article.publish_status !== 'published').length,
    published: articles.filter((article) => article.publish_status === 'published').length,
  }), [articles]);

  return (
    <div className="data-panel" style={{ display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%' }}>
      <div className="data-panel-head" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span className="data-panel-title">Publication Queue</span>

        <div className="insights-tab-strip">
          {(['all', 'drafts', 'published'] as const).map((entry) => (
            <button
              key={entry}
              type="button"
              onClick={() => setTab(entry)}
              style={{
                padding: '5px 12px',
                borderRadius: 999,
                border: `1px solid ${tab === entry ? 'rgba(96,165,250,0.35)' : 'rgba(255,255,255,0.06)'}`,
                background: tab === entry ? 'rgba(96,165,250,0.12)' : 'transparent',
                color: tab === entry ? 'var(--accent-cyan)' : 'var(--text-muted)',
                fontSize: 11,
                fontWeight: 700,
                textTransform: 'capitalize',
                cursor: 'pointer',
              }}
            >
              {entry} ({counts[entry]})
            </button>
          ))}
        </div>

        <button type="button" onClick={onRefresh} disabled={loading} style={{ ...actionButtonStyle, marginLeft: 'auto' }}>
          <RefreshCcw size={12} className={loading ? 'animate-spin-custom' : undefined} />
          <span style={{ fontSize: 11, fontWeight: 600 }}>{loading ? 'Refreshing...' : 'Refresh'}</span>
        </button>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '12px 12px 8px' }}>
        {filtered.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
            {loading ? 'Loading queue...' : `No ${tab === 'all' ? '' : tab} articles right now.`}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {filtered.map((article) => (
              <ArticleRow
                key={article.slug}
                article={article}
                onPreview={onPreview}
                onPublish={onPublish}
                onUnpublish={onUnpublish}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

const ArticleRow: React.FC<{
  article: ArticleListItem;
  onPreview: (article: ArticleListItem) => void;
  onPublish: (article: ArticleListItem) => void;
  onUnpublish: (article: ArticleListItem) => void;
}> = ({ article, onPreview, onPublish, onUnpublish }) => {
  const isPublished = article.publish_status === 'published';
  const contentType = article.content_type || 'manual';
  const colour = TYPE_COLOURS[contentType] || '#94A3B8';
  const score = article.editorial_quality_score ?? article.quality_score ?? article.confidence_score ?? 0;
  const urgency = article.publish_urgency_score ?? 0;
  const sourceBacked = Boolean(article.ikg_covered);
  const publishReady = article.editorial_review?.ready_to_publish !== false;
  const localArticlePath = `/${article.route_base || 'insights'}/${article.slug}/`;

  return (
    <div
      className="insights-queue-row"
      style={{
        padding: 12,
        borderRadius: 12,
        border: '1px solid rgba(255,255,255,0.06)',
        background: 'rgba(255,255,255,0.02)',
      }}
    >
      <div style={{ paddingTop: 2, flexShrink: 0 }}>
        {isPublished ? <CheckCircle2 size={15} color="var(--profit)" /> : <FileCheck2 size={15} color="#FBBF24" />}
      </div>

      <div style={{ minWidth: 0, flex: 1 }}>
        <div className="insights-queue-meta" style={{ marginBottom: 6 }}>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              padding: '2px 7px',
              borderRadius: 999,
              background: `${colour}14`,
              color: colour,
              fontSize: 10,
              fontWeight: 700,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
            }}
          >
            {contentType}
          </span>
          {sourceBacked && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10, fontWeight: 700, color: 'var(--accent-cyan)' }}>
              <ShieldCheck size={11} />
              Source-backed
            </span>
          )}
          {!publishReady && (
            <span style={{ fontSize: 10, fontWeight: 700, color: '#FBBF24', textTransform: 'uppercase' }}>
              In review
            </span>
          )}
        </div>

        {isPublished ? (
          <a
            href={localArticlePath}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent-cyan)', textDecoration: 'none', overflowWrap: 'anywhere' }}
          >
            {article.title || article.slug}
          </a>
        ) : (
          <button
            type="button"
            onClick={() => onPreview(article)}
            style={{ padding: 0, border: 'none', background: 'transparent', fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', textAlign: 'left', cursor: 'pointer', overflowWrap: 'anywhere' }}
          >
            {article.title || article.slug}
          </button>
        )}

        {article.description && (
          <div style={{ marginTop: 6, fontSize: 12, lineHeight: 1.55, color: 'var(--text-secondary)', overflowWrap: 'anywhere' }}>
            {article.description}
          </div>
        )}

        <div className="insights-queue-meta" style={{ marginTop: 8 }}>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {article.generated_at ? new Date(article.generated_at).toLocaleString() : 'Timestamp unavailable'}
          </span>
          <span style={{ fontSize: 11, fontWeight: 700, color: score >= 90 ? 'var(--profit)' : score >= 75 ? 'var(--accent-cyan)' : '#FBBF24' }}>
            Quality {score}
          </span>
          {urgency > 0 && (
            <span style={{ fontSize: 11, fontWeight: 700, color: urgency >= 70 ? 'var(--profit)' : '#FBBF24' }}>
              Urgency {urgency}
            </span>
          )}
        </div>
      </div>

      <div className="insights-queue-actions">
        <button type="button" onClick={() => onPreview(article)} title="Open review drawer" style={actionButtonStyle}>
          <Eye size={12} />
        </button>
        {isPublished ? (
          <>
            <a href={localArticlePath} target="_blank" rel="noopener noreferrer" title="Open live article" style={actionButtonStyle}>
              <ExternalLink size={12} />
            </a>
            <button type="button" onClick={() => onUnpublish(article)} title="Move back to draft" style={{ ...actionButtonStyle, color: 'var(--loss)' }}>
              <Lock size={12} />
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => onPublish(article)}
            title={publishReady ? 'Publish article' : 'Editorial review has not approved this article yet'}
            disabled={!publishReady}
            style={{
              ...actionButtonStyle,
              color: publishReady ? 'var(--profit)' : 'var(--text-muted)',
              opacity: publishReady ? 1 : 0.5,
              cursor: publishReady ? 'pointer' : 'not-allowed',
            }}
          >
            <Globe size={12} />
          </button>
        )}
      </div>
    </div>
  );
};

export default ArticleQueueTable;

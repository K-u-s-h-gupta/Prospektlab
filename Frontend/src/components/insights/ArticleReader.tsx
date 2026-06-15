import React from 'react';
import { X, FileText, ExternalLink, Sparkles } from 'lucide-react';
import { ArticleDetail } from '../../api/client';

/**
 * Editorial article reader — based on the ProspektLab design system handoff
 * (newsroom layout: hero-banner + data panel + rail + prose with key points,
 * inline metrics, pull quotes). Re-themed to the existing ProspektLab dark
 * glassmorphism colours (no Tailwind, no UI lib).
 */

interface Props {
  detail: ArticleDetail;
  onClose: () => void;
}

function fmt(date: string): string {
  if (!date) return '';
  try {
    return new Date(date).toLocaleDateString('en-IN', { year: 'numeric', month: 'short', day: 'numeric' });
  } catch { return date; }
}

function readMinutes(article: ArticleDetail['article']): number {
  if (!article) return 4;
  const text = [
    article.narrative_lede, article.market_context, article.analyst_commentary,
    ...((article.sections || []).flatMap(s => s.paragraphs || [])),
  ].join(' ');
  return Math.max(2, Math.round(text.split(/\s+/).filter(Boolean).length / 220));
}

export const ArticleReader: React.FC<Props> = ({ detail, onClose }) => {
  const a = detail.article || {};
  const lede = a.narrative_lede || a.hero_summary || detail.description;
  const ctx = a.market_context;
  const analyst = a.analyst_commentary;
  const sections = a.sections || [];
  const metrics = (a.metrics || []).slice(0, 4);
  const takeaways = (a.key_takeaways || []).slice(0, 3);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  React.useEffect(() => {
    const el = document.querySelector<HTMLElement>('.ar-progress');
    if (!el) return;
    const scroller = document.querySelector<HTMLElement>('.ar-modal');
    if (!scroller) return;
    const onScroll = () => {
      const pct = Math.min(100, (scroller.scrollTop / Math.max(1, scroller.scrollHeight - scroller.clientHeight)) * 100);
      el.style.width = `${pct}%`;
    };
    scroller.addEventListener('scroll', onScroll, { passive: true });
    return () => scroller.removeEventListener('scroll', onScroll);
  }, []);

  return (
    <div className="ar-backdrop" onMouseDown={onClose}>
      <div className="ar-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="ar-progress" />
        <button className="ar-close" onClick={onClose} aria-label="Close">
          <X size={16} />
        </button>

        <article className="ar-article">
          {/* HERO */}
          <header className="ar-hero">
            <div className="ar-crumb">
              <span>Insights</span><span className="ar-sep">/</span>
              <span>{detail.content_type ? detail.content_type.replace(/_/g, ' ') : 'Coverage'}</span>
            </div>
            <h1 className="ar-title">{a.title || detail.title}</h1>
            {(a.hero_summary || detail.description) && (
              <p className="ar-dek">{a.hero_summary || detail.description}</p>
            )}
            <div className="ar-meta">
              <span className="ar-byline"><span className="ar-av">PL</span> ProspektLab Desk</span>
              <span>{fmt(detail.generated_at)}</span>
              <span>{readMinutes(a)} min read</span>
              <span>Educational · No recommendation</span>
            </div>
          </header>

          {/* DATA PANEL — only if we have metrics */}
          {metrics.length > 0 && (
            <section className="ar-data-panel">
              <div className="ar-data-grid">
                {metrics.map((m, i) => (
                  <div className="ar-stat" key={i}>
                    <div className="ar-stat-k">{m.label}</div>
                    <div className="ar-stat-v">{m.value}</div>
                    {(m.change || m.period) && (
                      <div className="ar-stat-sub">{[m.change, m.period].filter(Boolean).join(' · ')}</div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* BODY: rail + prose */}
          <div className="ar-body">
            <aside className="ar-rail">
              {sections.length > 0 && (
                <div className="ar-rail-block">
                  <h4>On this page</h4>
                  <ul className="ar-toc">
                    {sections.map((s, i) => (
                      <li key={i}><a href={`#ar-sec-${i}`}>{s.heading}</a></li>
                    ))}
                  </ul>
                </div>
              )}
              {takeaways.length > 0 && (
                <div className="ar-rail-block">
                  <h4>Key takeaways</h4>
                  <ul className="ar-rail-takeaways">
                    {takeaways.map((t, i) => (
                      <li key={i}><strong>{t.heading}.</strong> {t.detail}</li>
                    ))}
                  </ul>
                </div>
              )}
              {detail.sources_used && detail.sources_used.length > 0 && (
                <div className="ar-rail-block">
                  <h4>Sources</h4>
                  <ul className="ar-rail-sources">
                    {detail.sources_used.slice(0, 5).map((s, i) => (
                      <li key={i}>
                        <a href={s.url} target="_blank" rel="noopener noreferrer">
                          <ExternalLink size={11} /> {s.title || s.url}
                        </a>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </aside>

            <div className="ar-prose">
              {/* LiveMint-style inverted pyramid: lede → context → analyst */}
              {lede && <p className="ar-lede">{lede}</p>}
              {ctx && <p className="ar-context">{ctx}</p>}
              {analyst && (
                <div className="ar-analyst">
                  <span className="ar-analyst-label"><Sparkles size={11} /> Analyst view</span>
                  <p>{analyst}</p>
                </div>
              )}

              {sections.map((s, i) => (
                <section className="ar-sec" id={`ar-sec-${i}`} key={i}>
                  <span className="ar-sec-label">Section {String(i + 1).padStart(2, '0')}</span>
                  <h2>{s.heading}</h2>
                  {(s.paragraphs || []).map((p, j) => (
                    <p key={j} dangerouslySetInnerHTML={{ __html: enrichInline(p) }} />
                  ))}
                  {(s.bullets && s.bullets.length > 0) && (
                    <ul className="ar-bullets">
                      {s.bullets.map((b, k) => <li key={k}>{b}</li>)}
                    </ul>
                  )}
                </section>
              ))}

              {(a.faqs && a.faqs.length > 0) && (
                <section className="ar-faq">
                  <h2>Questions readers usually ask</h2>
                  <div className="ar-faq-list">
                    {a.faqs.map((f, i) => (
                      <details key={i} className="ar-faq-item">
                        <summary>{f.question}</summary>
                        <p>{f.answer}</p>
                      </details>
                    ))}
                  </div>
                </section>
              )}

              <footer className="ar-footer">
                <a className="ar-source-link" href={detail.public_url} target="_blank" rel="noopener noreferrer">
                  <FileText size={12} /> Open published page
                </a>
              </footer>
            </div>
          </div>
        </article>
      </div>
    </div>
  );
};

/** Lightweight inline enrichment: wrap numbers in <strong> to lift data density visually. */
function enrichInline(text: string): string {
  const escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return escaped.replace(
    /([₹$]?\d[\d,]*(?:\.\d+)?\s?(?:%|bps|cr|crore|lakh|bn|billion|trillion|x)?)/gi,
    (m) => `<strong class="ar-num">${m}</strong>`,
  );
}

export default ArticleReader;

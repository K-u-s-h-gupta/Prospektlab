import React, { useRef, useEffect, useState } from 'react';
import { Maximize2, Code2 } from 'lucide-react';

interface HtmlArtifactProps {
  html: string | Record<string, any>;
}

export const HtmlArtifact: React.FC<HtmlArtifactProps> = ({ html }) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const [expanded, setExpanded] = useState(false);

  const htmlContent = typeof html === 'string' ? html : JSON.stringify(html, null, 2);

  useEffect(() => {
    if (!iframeRef.current || !htmlContent) return;

    const iframe = iframeRef.current;
    const doc = iframe.contentDocument || iframe.contentWindow?.document;
    if (!doc) return;

    try {
      // Look for HTML content inside JSON
      let content = htmlContent;
      if (htmlContent.startsWith('{') || htmlContent.startsWith('"')) {
        try {
          const parsed = typeof html === 'object' ? html : JSON.parse(htmlContent);
          if (typeof parsed === 'string') {
            content = parsed;
          } else if (typeof parsed === 'object') {
            content = parsed.html || parsed.content || htmlContent;
          }
        } catch {
          content = htmlContent;
        }
      }

      doc.open();
      doc.write(content);
      doc.close();

      iframe.style.height = `${Math.min(doc.body.scrollHeight || 400, 800)}px`;
    } catch (e) {
      doc.open();
      doc.write(`<pre style="color:red;background:#1a1a2e;padding:16px">${htmlContent}</pre>`);
      doc.close();
    }
  }, [htmlContent]);

  if (!htmlContent) return null;

  return (
    <div className="animate-scale-pop" style={{
      width: '100%',
      margin: '12px 0',
      border: '1px solid rgba(129, 140, 248, 0.2)',
      borderRadius: '10px',
      overflow: 'hidden',
      background: 'rgba(15, 23, 42, 0.4)'
    }}>
      {/* Artifact header bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 14px',
        background: 'rgba(129, 140, 248, 0.08)',
        borderBottom: '1px solid rgba(129, 140, 248, 0.12)'
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          fontSize: '11px',
          fontWeight: 600,
          color: 'var(--accent-indigo)',
          letterSpacing: '0.03em'
        }}>
          <Code2 size={13} />
          INTERACTIVE ARTIFACT
        </div>
        <div
          onClick={() => setExpanded(!expanded)}
          style={{
            cursor: 'pointer',
            color: 'var(--text-secondary)',
            display: 'flex',
            alignItems: 'center',
            gap: '4px'
          }}
          title="Toggle fullscreen"
        >
          <Maximize2 size={13} />
        </div>
      </div>

      {/* Artifact body */}
      <div style={{
        padding: expanded ? 0 : '4px',
        minHeight: expanded ? '80vh' : '200px',
        maxHeight: expanded ? 'calc(100vh - 100px)' : '600px',
        overflow: 'auto',
        transition: 'all 0.3s ease'
      }}>
        <iframe
          ref={iframeRef}
          sandbox="allow-scripts allow-same-origin"
          style={{
            width: '100%',
            height: '100%',
            minHeight: '300px',
            border: 'none',
            display: 'block'
          }}
          title="prospektlab-artifact"
        />
      </div>
    </div>
  );
};

export default HtmlArtifact;

import React from 'react';
import { FileText, ExternalLink } from 'lucide-react';

/**
 * Provenance hover-card — the moat made visible.
 * Wraps any inline value; on hover shows the source paragraph / document /
 * confidence behind the claim. Theme-native, CSS-only transitions.
 */

export interface ProvenanceEvidence {
  source_table?: string;
  source_url?: string;
  detail?: string;
  [k: string]: any;
}

interface ProvenanceCardProps {
  children: React.ReactNode;
  evidence: ProvenanceEvidence;
  label?: string;
}

export const ProvenanceCard: React.FC<ProvenanceCardProps> = ({ children, evidence, label }) => {
  const url = evidence.source_url;
  const source = evidence.source_table || 'IKG';
  const entries = Object.entries(evidence).filter(
    ([k]) => !['source_table', 'source_url', 'detail'].includes(k)
  );

  return (
    <span className="prov-wrap">
      <span className="prov-anchor">{children}<sup className="prov-cite">◆</sup></span>
      <span className="prov-card" role="tooltip">
        <span className="prov-card-head">
          <FileText size={12} color="var(--accent-cyan)" />
          <span className="prov-card-source">{label || source}</span>
        </span>
        {evidence.detail && <span className="prov-card-detail">{evidence.detail}</span>}
        {entries.length > 0 && (
          <span className="prov-card-kv">
            {entries.slice(0, 5).map(([k, v]) => (
              <span className="prov-kv-row" key={k}>
                <span className="prov-kv-key">{k}</span>
                <span className="prov-kv-val">{String(v)}</span>
              </span>
            ))}
          </span>
        )}
        {url && (
          <a className="prov-card-link" href={url} target="_blank" rel="noopener noreferrer">
            <ExternalLink size={11} /> View source
          </a>
        )}
      </span>
    </span>
  );
};

export default ProvenanceCard;

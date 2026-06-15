import React from 'react';
import { X, ShieldAlert, FileText, GitBranch, Gauge, Loader2 } from 'lucide-react';
import {
  getCompanyGovernance, getCompanyProvenance, getCompanyHealth, getCompanyNetwork,
  GovernanceResult, CompanyProvenance, CompanyHealth, CompanyNetwork,
} from '../../api/client';
import { ProvenanceCard } from '../common/ProvenanceCard';

/**
 * Company Intel modal — single-company deep view fusing all IKG endpoints:
 * forensic governance, provenance (cited facts), graph completeness, and the
 * director network. Theme-native glass. Opened with a CIN.
 */

const BAND_COLOR: Record<string, string> = {
  LOW: 'var(--profit)', MODERATE: 'var(--accent-cyan)', ELEVATED: '#F59E0B', HIGH: 'var(--loss)',
};
const GRADE_LABEL: Record<string, string> = {
  evidence_grade: 'Evidence-grade', partial: 'Partial', thin: 'Thin',
};

interface Props {
  cin: string;
  name?: string;
  onClose: () => void;
}

export const CompanyIntelModal: React.FC<Props> = ({ cin, name, onClose }) => {
  const [gov, setGov] = React.useState<GovernanceResult | null>(null);
  const [prov, setProv] = React.useState<CompanyProvenance | null>(null);
  const [health, setHealth] = React.useState<CompanyHealth | null>(null);
  const [network, setNetwork] = React.useState<CompanyNetwork | null>(null);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let alive = true;
    setLoading(true);
    const settle = <T,>(p: Promise<T>) => p.catch(() => null);
    Promise.all([
      settle(getCompanyGovernance(cin)),
      settle(getCompanyProvenance(cin)),
      settle(getCompanyHealth(cin)),
      settle(getCompanyNetwork(cin)),
    ]).then(([g, p, h, n]) => {
      if (!alive) return;
      setGov(g as GovernanceResult | null);
      setProv(p as CompanyProvenance | null);
      setHealth(h as CompanyHealth | null);
      setNetwork(n as CompanyNetwork | null);
      setLoading(false);
    });
    return () => { alive = false; };
  }, [cin]);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="cim-backdrop" onMouseDown={onClose}>
      <div className="cim-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="cim-head">
          <div className="cim-title">
            <span className="cim-name">{prov?.company_name || name || cin}</span>
            <span className="cim-cin">{cin}</span>
          </div>
          <button className="cim-close" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>

        {loading ? (
          <div className="cim-loading"><Loader2 size={18} className="gov-spin" color="var(--accent-cyan)" /> Loading intelligence…</div>
        ) : (
          <div className="cim-body">
            {/* Governance */}
            <section className="cim-section">
              <div className="cim-section-head"><ShieldAlert size={14} color="var(--accent-cyan)" /> Forensic Governance</div>
              {gov ? (
                <>
                  <div className="cim-pill" style={{ borderColor: BAND_COLOR[gov.band], color: BAND_COLOR[gov.band] }}>
                    {gov.score.toFixed(0)} · {gov.band}
                  </div>
                  <div className="cim-flags">
                    {gov.flags.length === 0 && <span className="cim-muted">No governance flags.</span>}
                    {gov.flags.map((f, i) => (
                      <ProvenanceCard key={i} label={f.code} evidence={{ detail: f.detail, ...f.evidence }}>
                        <span className="cim-flag" data-sev={f.severity}>{f.code.replace(/_/g, ' ')}</span>
                      </ProvenanceCard>
                    ))}
                  </div>
                </>
              ) : <span className="cim-muted">No governance data.</span>}
            </section>

            {/* Completeness */}
            <section className="cim-section">
              <div className="cim-section-head"><Gauge size={14} color="var(--accent-cyan)" /> Data Completeness</div>
              {health ? (
                <div className="cim-health">
                  <span className="cim-grade">{GRADE_LABEL[health.grade] || health.grade}</span>
                  <span className="cim-muted">{health.completeness_score.toFixed(0)}% complete</span>
                  {health.missing.length > 0 && <span className="cim-missing">missing: {health.missing.join(', ')}</span>}
                </div>
              ) : <span className="cim-muted">No completeness data.</span>}
            </section>

            {/* Network */}
            <section className="cim-section">
              <div className="cim-section-head"><GitBranch size={14} color="var(--accent-cyan)" /> Director Network</div>
              {network && network.summary.connected_companies > 0 ? (
                <div className="cim-network">
                  <span className="cim-muted">
                    {network.summary.directors} directors · {network.summary.connected_companies} connected companies
                  </span>
                  <div className="cim-conn">
                    {network.connected_companies.slice(0, 8).map((c) => (
                      <span className="cim-conn-chip" key={c.id}>{c.name} <em>×{c.shared_directors}</em></span>
                    ))}
                  </div>
                </div>
              ) : <span className="cim-muted">No shared-director connections found.</span>}
            </section>

            {/* Provenance */}
            <section className="cim-section">
              <div className="cim-section-head">
                <FileText size={14} color="var(--accent-cyan)" /> Provenance
                {prov && <span className="cim-cite-ratio">{Math.round(prov.summary.citation_ratio * 100)}% cited</span>}
              </div>
              {prov ? (
                <div className="cim-prov">
                  {prov.sections.slice(0, 8).map((s) => (
                    <div className="cim-prov-row" key={s.predicate}>
                      <span className="cim-prov-label">{s.label}</span>
                      <span className="cim-prov-vals">
                        {s.facts.slice(0, 3).map((f, i) => (
                          <ProvenanceCard key={i} label={s.label} evidence={f.evidence}>
                            <span className="cim-prov-val">{String(f.value)}</span>
                          </ProvenanceCard>
                        ))}
                      </span>
                    </div>
                  ))}
                </div>
              ) : <span className="cim-muted">No provenance facts yet.</span>}
            </section>
          </div>
        )}
      </div>
    </div>
  );
};

export default CompanyIntelModal;

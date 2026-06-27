import React from 'react';
import { TrendingDown, AlertTriangle, AlertCircle } from 'lucide-react';
import { EarningsSubsidiaryAnalysis } from '../../api/client';

interface SubsidiaryMatrixProps {
  analysis: EarningsSubsidiaryAnalysis;
}

const SubsidiaryMatrix: React.FC<SubsidiaryMatrixProps> = ({ analysis }) => {
  // Safely destructure with defaults
  const standalone = analysis?.standalone || {};
  const consolidated = analysis?.consolidated || {};
  const subsidiary_contribution = analysis?.subsidiary_contribution || {};
  const flags = analysis?.flags || {};
  const verdict = analysis?.verdict || '';
  const alert_level = analysis?.alert_level || 'none';

  const alertClass = alert_level === 'high' ? 'alert-high' : alert_level === 'medium' ? 'alert-medium' : '';
  const hasData = standalone.revenue || consolidated.revenue || standalone.pat || consolidated.pat;

  if (!hasData) return null;

  const formatCr = (v?: number) => (v != null ? `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 0 })} Cr` : '—');
  const formatPct = (v?: number) => (v != null ? `${v >= 0 ? '+' : ''}${v.toFixed(1)}%` : '—');
  const getDeltaClass = (v?: number) => {
    if (v == null || v === 0) return 'neutral';
    return v > 0 ? 'positive' : 'negative';
  };

  return (
    <div className={`erd-subsidiary-matrix ${alertClass}`}>
      <div className="erd-subsidiary-header">
        <h4 className="erd-section-title">
          Subsidiary Performance Audit
          {alert_level && alert_level !== 'none' && (
            <span className={`erd-subsidiary-alert ${alert_level}`}>
              {alert_level === 'high' ? <AlertTriangle size={14} /> : <AlertCircle size={14} />}
              {alert_level.toUpperCase()}
            </span>
          )}
        </h4>
      </div>

      <div className="erd-subsidiary-table">
        <div className="erd-subsidiary-row header">
          <span>Metric</span>
          <span>Standalone</span>
          <span>Consolidated</span>
          <span>Subsidiary Δ</span>
        </div>

        {standalone.revenue != null && consolidated.revenue != null && (
          <div className="erd-subsidiary-row">
            <span className="erd-subsidiary-label">Revenue</span>
            <span>{formatCr(standalone.revenue)}</span>
            <span>{formatCr(consolidated.revenue)}</span>
            <span className={`erd-subsidiary-delta ${getDeltaClass(subsidiary_contribution.revenue)}`}>
              {formatCr(subsidiary_contribution.revenue)}
              <small>{formatPct(subsidiary_contribution.revenue_pct)}</small>
            </span>
          </div>
        )}

        {standalone.pat != null && consolidated.pat != null && (
          <div className="erd-subsidiary-row">
            <span className="erd-subsidiary-label">PAT</span>
            <span>{formatCr(standalone.pat)}</span>
            <span>{formatCr(consolidated.pat)}</span>
            <span className={`erd-subsidiary-delta ${getDeltaClass(subsidiary_contribution.pat)}`}>
              {formatCr(subsidiary_contribution.pat)}
              <small>{formatPct(subsidiary_contribution.pat_pct)}</small>
              {flags.profit_drain && <TrendingDown size={12} className="icon-drain" />}
            </span>
          </div>
        )}

        {standalone.ebitda != null && consolidated.ebitda != null && (
          <div className="erd-subsidiary-row">
            <span className="erd-subsidiary-label">EBITDA</span>
            <span>{formatCr(standalone.ebitda)}</span>
            <span>{formatCr(consolidated.ebitda)}</span>
            <span className={`erd-subsidiary-delta ${getDeltaClass(subsidiary_contribution.ebitda)}`}>
              {formatCr(subsidiary_contribution.ebitda)}
            </span>
          </div>
        )}

        {subsidiary_contribution.margin_drag != null && (
          <div className="erd-subsidiary-row">
            <span className="erd-subsidiary-label">EBITDA Margin</span>
            <span>{subsidiary_contribution.standalone_ebitda_margin?.toFixed(1)}%</span>
            <span>{subsidiary_contribution.consolidated_ebitda_margin?.toFixed(1)}%</span>
            <span className={`erd-subsidiary-delta ${getDeltaClass(subsidiary_contribution.margin_drag)}`}>
              {subsidiary_contribution.margin_drag >= 0 ? '+' : ''}{subsidiary_contribution.margin_drag.toFixed(1)} pts
              {flags.margin_dilution && <TrendingDown size={12} className="icon-drain" />}
            </span>
          </div>
        )}
      </div>

      {/* Flags */}
      {(flags.profit_drain || flags.margin_dilution || flags.revenue_dependent) && (
        <div className="erd-subsidiary-flags">
          {flags.profit_drain && <span className="erd-flag danger">PROFIT DRAIN</span>}
          {flags.margin_dilution && <span className="erd-flag warning">MARGIN DILUTION</span>}
          {flags.revenue_dependent && <span className="erd-flag info">SUBSIDIARY REVENUE &gt;25%</span>}
        </div>
      )}

      {verdict && <p className="erd-subsidiary-verdict">{verdict}</p>}
    </div>
  );
};

export default SubsidiaryMatrix;

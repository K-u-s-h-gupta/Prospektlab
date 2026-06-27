import React, { useState } from 'react';
import { ChevronDown, ChevronUp, TrendingUp, TrendingDown, AlertTriangle, AlertCircle } from 'lucide-react';
import { EarningsFootnotesDiff, FootnoteClause } from '../../api/client';

interface FootnoteDiffProps {
  diff: EarningsFootnotesDiff;
}

const FootnoteDiff: React.FC<FootnoteDiffProps> = ({ diff }) => {
  const [expanded, setExpanded] = useState(false);

  if (!diff) return null;

  if (diff.error) {
    return (
      <div className="erd-footnote-diff muted">
        <p className="erd-muted">{diff.error}</p>
      </div>
    );
  }

  const addedClauses = diff.added_clauses || [];
  const removedClauses = diff.removed_clauses || [];
  const modifiedClauses = diff.modified_clauses || [];
  const totalChanges = addedClauses.length + removedClauses.length + modifiedClauses.length;
  const alertLevel = diff.alert_level || 'none';

  if (totalChanges === 0) {
    return (
      <div className="erd-footnote-diff">
        <h4 className="erd-section-title">Footnote Variance Ledger</h4>
        <p className="erd-footnote-summary success">No significant changes in footnotes from previous quarter.</p>
      </div>
    );
  }

  const alertClass = alertLevel === 'high' ? 'alert-high' : alertLevel === 'medium' ? 'alert-medium' : '';

  const renderClause = (clause: FootnoteClause, type: 'added' | 'removed') => (
    <div className={`erd-footnote-clause ${type} ${clause.severity}`} key={clause.text.slice(0, 50)}>
      <div className="erd-clause-header">
        <span className={`erd-clause-badge ${type}`}>{type === 'added' ? 'NEW' : 'REMOVED'}</span>
        <span className="erd-clause-category">{clause.category.replace(/_/g, ' ')}</span>
        <span className={`erd-clause-severity ${clause.severity}`}>{clause.severity}</span>
      </div>
      <p className="erd-clause-text">{clause.text}</p>
    </div>
  );

  return (
    <div className={`erd-footnote-diff ${alertClass}`}>
      <div className="erd-footnote-header" onClick={() => setExpanded(!expanded)}>
        <h4 className="erd-section-title">
          Footnote Variance Ledger
          {alertLevel && alertLevel !== 'none' && (
            <span className={`erd-footnote-alert ${alertLevel}`}>
              {alertLevel === 'high' ? <AlertTriangle size={14} /> : <AlertCircle size={14} />}
              {alertLevel.toUpperCase()}
            </span>
          )}
        </h4>
        <button type="button" className="erd-footnote-expand">
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
      </div>

      <p className="erd-footnote-summary">{diff.summary || `${addedClauses.length} new, ${removedClauses.length} removed`}</p>

      {diff.current_quarter && diff.previous_quarter && (
        <p className="erd-footnote-quarters">
          Comparing <strong>{diff.current_quarter}</strong> vs <strong>{diff.previous_quarter}</strong>
        </p>
      )}

      {expanded && (
        <div className="erd-footnote-clauses">
          {addedClauses.length > 0 && (
            <div className="erd-clauses-section">
              <h5 className="erd-clauses-title added">
                <TrendingUp size={14} /> New Clauses ({addedClauses.length})
              </h5>
              {addedClauses.map((c) => renderClause(c, 'added'))}
            </div>
          )}

          {removedClauses.length > 0 && (
            <div className="erd-clauses-section">
              <h5 className="erd-clauses-title removed">
                <TrendingDown size={14} /> Removed Clauses ({removedClauses.length})
              </h5>
              {removedClauses.map((c) => renderClause(c, 'removed'))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default FootnoteDiff;

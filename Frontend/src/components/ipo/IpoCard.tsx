import React from 'react';
import { useNavigate } from 'react-router-dom';
import { TrendingUp, AlertTriangle, BarChart3, ExternalLink, Clock, CheckCircle2 } from 'lucide-react';
import { IpoCard } from '../../api/client';

interface IpoCardViewProps {
  card: IpoCard;
  originPath?: string;
}

export const scoreColor = (score?: number) => {
  if (score == null) return 'var(--text-muted)';
  if (score >= 70) return 'var(--accent-green, #22c55e)';
  if (score >= 55) return 'var(--accent-amber, #f59e0b)';
  return 'var(--accent-red, #ef4444)';
};

export const scoreGrade = (score?: number): string => {
  if (score == null) return '—';
  if (score >= 80) return 'A';
  if (score >= 70) return 'B+';
  if (score >= 60) return 'B';
  if (score >= 50) return 'C';
  return 'D';
};

const StatusBadge: React.FC<{ status: string; subscriptionStatus?: string }> = ({ status, subscriptionStatus }) => {
  if (status === 'live') {
    return (
      <div className="ipo-status-badge ipo-status-badge--live">
        <span className="ipo-pulse-dot" />
        {subscriptionStatus && subscriptionStatus.includes('subscribed')
          ? subscriptionStatus
          : 'Live'}
      </div>
    );
  }
  if (status === 'upcoming') {
    return (
      <div className="ipo-status-badge ipo-status-badge--upcoming">
        <Clock size={10} />
        Upcoming
      </div>
    );
  }
  if (status === 'listed') {
    return (
      <div className="ipo-status-badge ipo-status-badge--listed">
        <CheckCircle2 size={10} />
        Listed
      </div>
    );
  }
  return null;
};

const GmpBadge: React.FC<{ gmp?: number | null; priceBandHigh?: number }> = ({ gmp, priceBandHigh }) => {
  if (gmp == null) return null;
  const gmpPct = priceBandHigh && priceBandHigh > 0 ? ((gmp / priceBandHigh) * 100).toFixed(1) : null;
  const isPositive = gmp >= 0;
  return (
    <div className={`ipo-gmp-tag ${isPositive ? 'positive' : 'negative'}`}>
      <TrendingUp size={10} />
      <span>GMP {isPositive ? '+' : ''}{gmp}</span>
      {gmpPct && <span className="ipo-gmp-pct">({isPositive ? '+' : ''}{gmpPct}%)</span>}
    </div>
  );
};

/**
 * Log-scale subscription bar: preserves visual differentiation across all subscription levels.
 * 1x ≈ 33%  |  3x ≈ 50%  |  10x ≈ 66%  |  50x ≈ 83%  |  100x+ = 100%
 * Formula: log₂(ratio + 1) / log₂(101) * 100
 */
const subRatioToBarPct = (ratio: number): number => {
  if (ratio <= 0) return 0;
  return Math.min(100, (Math.log2(ratio + 1) / Math.log2(101)) * 100);
};

const fmtCardDate = (d?: string | null) => d
  ? new Date(d).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })
  : null;

export const IpoCardView = React.memo<IpoCardViewProps>(({ card, originPath = '/ipo' }) => {
  const navigate = useNavigate();
  const band = card.price_band;
  const priceLabel =
    band?.low && band?.high
      ? `₹${band.low}–₹${band.high}`
      : band?.high
      ? `₹${band.high}`
      : 'TBD';

  const ofsWarning = card.ofs_pct != null && card.ofs_pct >= 50;
  const isLive = card.status === 'live';
  const isListed = card.status === 'listed';
  const isUpcoming = card.status === 'upcoming';

  // Subscription ratio — from direct field or parsed from status string
  // card.subscription_times may arrive as a string from JSON; coerce to number
  const subMatch = card.subscription_status?.match(/([\d.]+)x/);
  const rawRatio = card.subscription_times ?? (subMatch ? parseFloat(subMatch[1]) : null);
  const subRatio = rawRatio != null ? (typeof rawRatio === 'number' ? rawRatio : parseFloat(String(rawRatio))) : null;
  const subBarPct = subRatio != null && !isNaN(subRatio) ? subRatioToBarPct(subRatio) : 0;

  // OFS percentage — from field or computed
  const computedOfsPct = card.ofs_pct ?? (() => {
    const fresh = card.fresh_issue_cr;
    const ofs = card.ofs_cr;
    if (fresh != null && ofs != null && fresh + ofs > 0) {
      return Math.round((ofs / (fresh + ofs)) * 100);
    }
    return null;
  })();

  return (
    <button
      type="button"
      className={`ipo-card ipo-card--${card.status}`}
      onClick={() => navigate(`/ipo/${card.slug}`, { state: { from: originPath, card } })}
      aria-label={`View analysis for ${card.company_name}`}
    >
      {/* Company name + score */}
      <div className="ipo-card-head">
        <div className="ipo-card-head-left">
          <div className="ipo-card-company">{card.company_name}</div>
          <div className="ipo-card-meta">
            {card.exchange && <span className="ipo-exchange-tag">{card.exchange}</span>}
            {card.is_sme && <span className="ipo-sme-tag">SME</span>}
            {card.nse_symbol && <span className="ipo-symbol-tag">{card.nse_symbol}</span>}
            {card.sector && <span>{card.sector}</span>}
          </div>
        </div>
        {card.composite_score != null && (
          <div
            className="ipo-score-badge"
            style={{ '--score-color': scoreColor(card.composite_score) } as React.CSSProperties}
          >
            <span className="ipo-score-value">{Math.round(card.composite_score)}</span>
            <span className="ipo-score-grade">{scoreGrade(card.composite_score)}</span>
            <span className="ipo-score-label">Score</span>
          </div>
        )}
      </div>

      {/* Status + GMP */}
      <div className="ipo-card-status-row">
        <StatusBadge status={card.status} subscriptionStatus={card.subscription_status} />
        <GmpBadge gmp={card.gmp} priceBandHigh={band?.high} />
      </div>

      {/* Stats grid — all available fields */}
      <div className="ipo-card-grid">
        {/* Issue size */}
        <div className="ipo-stat-cell">
          <div className="ipo-stat-label">Issue size</div>
          <div className="ipo-stat-value">{card.issue_size_cr ? `₹${card.issue_size_cr} cr` : '—'}</div>
        </div>

        {/* Price band */}
        <div className="ipo-stat-cell">
          <div className="ipo-stat-label">Price band</div>
          <div className="ipo-stat-value">{priceLabel}</div>
        </div>

        {/* Fresh / OFS with OFS% */}
        <div className="ipo-stat-cell">
          <div className="ipo-stat-label">
            Fresh / OFS
            {ofsWarning && (
              <AlertTriangle size={11} className="ipo-ofs-warn" aria-label="High OFS — promoters selling" />
            )}
          </div>
          <div className="ipo-stat-value">
            {card.fresh_issue_cr ? `₹${card.fresh_issue_cr}` : '—'}
            {' / '}
            {card.ofs_cr ? `₹${card.ofs_cr} cr` : '—'}
            {computedOfsPct != null && (
              <span className={`ipo-ofs-pct-tag${computedOfsPct >= 50 ? ' high' : ''}`}>
                {' '}({computedOfsPct}% OFS)
              </span>
            )}
          </div>
        </div>

        {/* Lot size */}
        {card.lot_size != null && (
          <div className="ipo-stat-cell">
            <div className="ipo-stat-label">Lot size</div>
            <div className="ipo-stat-value">
              {card.lot_size} sh{band?.high ? ` / ₹${(card.lot_size * band.high).toLocaleString('en-IN')}` : ''}
            </div>
          </div>
        )}

        {/* Date context — status-specific */}
        {isListed && card.listing_date ? (
          <div className="ipo-stat-cell">
            <div className="ipo-stat-label">Listed on</div>
            <div className="ipo-stat-value">
              {new Date(card.listing_date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}
            </div>
          </div>
        ) : isLive && card.subscription_open ? (
          <div className="ipo-stat-cell">
            <div className="ipo-stat-label">Subscription</div>
            <div className="ipo-stat-value">
              {fmtCardDate(card.subscription_open)}
              {card.subscription_close && ` – ${fmtCardDate(card.subscription_close)}`}
            </div>
          </div>
        ) : isUpcoming && card.subscription_open ? (
          <div className="ipo-stat-cell">
            <div className="ipo-stat-label">Opens</div>
            <div className="ipo-stat-value">{fmtCardDate(card.subscription_open)}</div>
          </div>
        ) : (
          <div className="ipo-stat-cell">
            <div className="ipo-stat-label">Filed</div>
            <div className="ipo-stat-value">
              {card.filing_date
                ? new Date(card.filing_date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
                : '—'}
            </div>
          </div>
        )}
      </div>

      {/* Live: key dates row */}
      {isLive && (card.allotment_date || card.listing_date || card.subscription_close) && (
        <div className="ipo-card-dates-row">
          {card.subscription_close && (
            <span className="ipo-date-chip">
              Closes: {fmtCardDate(card.subscription_close)}
            </span>
          )}
          {card.allotment_date && (
            <span className="ipo-date-chip">
              Allotment: {fmtCardDate(card.allotment_date)}
            </span>
          )}
          {card.listing_date && (
            <span className="ipo-date-chip">
              Listing: {fmtCardDate(card.listing_date)}
            </span>
          )}
        </div>
      )}

      {/* Subscription bar — log scale preserves differentiation at any subscription level */}
      {isLive && (card.subscription_status || card.subscription_times != null) && (
        <div className="ipo-card-sub-section">
          {subRatio != null ? (
            <>
              <div className="ipo-sub-bar-wrap">
                <div className="ipo-sub-bar-fill" style={{ width: `${subBarPct}%` }} />
              </div>
              <div className="ipo-sub-label">
                <span>{card.subscription_status || 'Subscribed'}</span>
                <span className={subRatio >= 1 ? 'text-up' : 'text-down'}>{Number(subRatio).toFixed(2)}x</span>
              </div>
            </>
          ) : (
            <div className="ipo-card-foot-text">
              <TrendingUp size={12} />
              {card.subscription_status}
            </div>
          )}
        </div>
      )}

      {/* CTA */}
      <div className="ipo-card-cta">
        <span>View analysis</span>
        <ExternalLink size={11} />
      </div>
    </button>
  );
});

IpoCardView.displayName = 'IpoCardView';

interface ScoreBarsProps {
  scores: Record<string, any>;
  composite?: number;
}

export const IpoScoreBars = React.memo<ScoreBarsProps>(({ scores, composite }) => {
  const dims = [
    { key: 'business_quality', label: 'Business Quality' },
    { key: 'valuation_fairness', label: 'Valuation Fairness' },
    { key: 'management_credibility', label: 'Management' },
    { key: 'financial_health', label: 'Financial Health' },
    { key: 'risk_profile', label: 'Risk Profile' },
  ];

  return (
    <div className="ipo-score-panel">
      {composite != null && (
        <div className="ipo-composite-score">
          <BarChart3 size={20} style={{ color: scoreColor(composite), flexShrink: 0 }} />
          <div className="ipo-composite-inner">
            <div className="ipo-composite-value" style={{ color: scoreColor(composite) }}>
              {Math.round(composite)}
            </div>
            <div className="ipo-composite-meta">
              <span className="ipo-composite-grade">{scoreGrade(composite)}</span>
              <span className="ipo-composite-label">ProspektLab Score</span>
            </div>
          </div>
        </div>
      )}
      <div className="ipo-score-bars">
        {dims.map((dim) => {
          const val = Number(scores?.[dim.key] ?? 0);
          const color = scoreColor(val || undefined);
          return (
            <div key={dim.key} className="ipo-score-row">
              <span className="ipo-score-row-label">{dim.label}</span>
              <div className="ipo-score-track">
                <div
                  className="ipo-score-fill"
                  style={{
                    width: `${Math.min(100, Math.max(0, val))}%`,
                    background: `linear-gradient(90deg, var(--accent-indigo, #2563eb), ${color})`,
                  }}
                />
              </div>
              <span className="ipo-score-row-val" style={{ color }}>
                {val ? Math.round(val) : '—'}
              </span>
            </div>
          );
        })}
      </div>
      <p className="ipo-disclaimer">
        {scores?.disclaimer ||
          'ProspektLab IPO Score is data-driven analysis based on DRHP disclosures — not investment advice.'}
      </p>
    </div>
  );
});

IpoScoreBars.displayName = 'IpoScoreBars';

export default IpoCardView;

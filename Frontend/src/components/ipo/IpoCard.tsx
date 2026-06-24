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

export const IpoCardView: React.FC<IpoCardViewProps> = ({ card, originPath = '/ipo' }) => {
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

  // Parse subscription ratio from status string e.g. "Day 2 — 1.8x subscribed"
  const subMatch = card.subscription_status?.match(/([\d.]+)x/);
  const subRatio = subMatch ? parseFloat(subMatch[1]) : null;
  const subPct = subRatio ? Math.min(subRatio * 100 / 3, 100) : 0; // cap bar at 3x

  return (
    <button
      type="button"
      className={`ipo-card ipo-card--${card.status}`}
      onClick={() => navigate(`/ipo/${card.slug}`, { state: { from: originPath } })}
      aria-label={`View analysis for ${card.company_name}`}
    >
      {/* Top: company info + score */}
      <div className="ipo-card-head">
        <div className="ipo-card-head-left">
          <div className="ipo-card-company">{card.company_name}</div>
          <div className="ipo-card-meta">
            {card.exchange && <span className="ipo-exchange-tag">{card.exchange}</span>}
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

      {/* Status + GMP row */}
      <div className="ipo-card-status-row">
        <StatusBadge status={card.status} subscriptionStatus={card.subscription_status} />
        <GmpBadge gmp={card.gmp} priceBandHigh={band?.high} />
      </div>

      {/* Stats grid */}
      <div className="ipo-card-grid">
        <div className="ipo-stat-cell">
          <div className="ipo-stat-label">Issue size</div>
          <div className="ipo-stat-value">{card.issue_size_cr ? `₹${card.issue_size_cr} cr` : '—'}</div>
        </div>
        <div className="ipo-stat-cell">
          <div className="ipo-stat-label">
            Fresh / OFS
            {ofsWarning && (
              <AlertTriangle size={11} className="ipo-ofs-warn" aria-label="High OFS — promoters selling" />
            )}
          </div>
          <div className="ipo-stat-value">
            {card.fresh_issue_cr ?? '—'} / {card.ofs_cr ?? '—'} cr
          </div>
        </div>
        <div className="ipo-stat-cell">
          <div className="ipo-stat-label">Price band</div>
          <div className="ipo-stat-value">{priceLabel}</div>
        </div>
        {isListed && card.listing_date ? (
          <div className="ipo-stat-cell">
            <div className="ipo-stat-label">Listed on</div>
            <div className="ipo-stat-value">{new Date(card.listing_date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}</div>
          </div>
        ) : (
          <div className="ipo-stat-cell">
            <div className="ipo-stat-label">GMP</div>
            <div className={`ipo-stat-value ${card.gmp != null ? (card.gmp >= 0 ? 'text-up' : 'text-down') : ''}`}>
              {card.gmp != null ? `₹${card.gmp}` : '—'}
            </div>
          </div>
        )}
      </div>

      {/* Subscription bar (live IPOs) */}
      {isLive && card.subscription_status && (
        <div className="ipo-card-sub-section">
          {subRatio != null ? (
            <>
              <div className="ipo-sub-bar-wrap">
                <div className="ipo-sub-bar-fill" style={{ width: `${subPct}%` }} />
              </div>
              <div className="ipo-sub-label">
                <span>{card.subscription_status}</span>
                <span className={subRatio >= 1 ? 'text-up' : 'text-down'}>{subRatio}x</span>
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

      {/* View analysis CTA */}
      <div className="ipo-card-cta">
        <span>View analysis</span>
        <ExternalLink size={11} />
      </div>
    </button>
  );
};

interface ScoreBarsProps {
  scores: Record<string, any>;
  composite?: number;
}

export const IpoScoreBars: React.FC<ScoreBarsProps> = ({ scores, composite }) => {
  const dims = [
    { key: 'business_quality', label: 'Business Quality', icon: '🏢' },
    { key: 'valuation_fairness', label: 'Valuation Fairness', icon: '⚖️' },
    { key: 'management_credibility', label: 'Management', icon: '👤' },
    { key: 'financial_health', label: 'Financial Health', icon: '💰' },
    { key: 'risk_profile', label: 'Risk Profile', icon: '🛡️' },
  ];

  return (
    <div className="ipo-score-panel">
      {composite != null && (
        <div className="ipo-composite-score">
          <BarChart3 size={20} style={{ color: scoreColor(composite), flexShrink: 0 }} />
          <div className="ipo-composite-inner">
            <div
              className="ipo-composite-value"
              style={{ color: scoreColor(composite) }}
            >
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
};

export default IpoCardView;

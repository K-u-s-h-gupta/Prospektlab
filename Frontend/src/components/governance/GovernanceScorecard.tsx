import React, { useEffect, useMemo, useState } from 'react';
import {
  ChevronLeft,
  AlertTriangle,
  Info,
  Building2,
  TrendingDown,
  Shield,
  Scale,
  Users,
  FileSearch,
  Database,
  Network,
  CheckCircle2,
  XCircle,
  AlertCircle,
  ExternalLink,
  HelpCircle,
  Lightbulb,
  Target,
  Eye,
} from 'lucide-react';
import { Line } from 'react-chartjs-2';
import { Radar } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  RadialLinearScale,
  Filler,
  Tooltip,
  Legend,
} from 'chart.js';
import {
  getCompanyGovernance,
  getCompanyHealth,
  getCompanyProvenance,
  getCompanyNetwork,
  GovernanceResult,
  CompanyHealth,
  CompanyProvenance,
  CompanyNetwork,
} from '../../api/client';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, RadialLinearScale, Filler, Tooltip, Legend);

type Band = 'LOW' | 'MODERATE' | 'ELEVATED' | 'HIGH';

const BAND_META: Record<Band, { label: string; color: string; bg: string; verdict: string; advice: string }> = {
  HIGH: {
    label: 'High Risk',
    color: '#F87171',
    bg: 'rgba(248,113,113,0.14)',
    verdict: 'Significant governance concerns detected. Exercise caution.',
    advice: 'This company shows multiple warning signs in how it is managed. If you own shares, monitor closely. If considering investing, do thorough additional research first.',
  },
  ELEVATED: {
    label: 'Elevated Risk',
    color: '#FB923C',
    bg: 'rgba(251,146,60,0.14)',
    verdict: 'Some governance red flags are present. Worth monitoring.',
    advice: 'There are areas of concern but not immediate danger. Keep an eye on quarterly updates and watch if these issues worsen over time.',
  },
  MODERATE: {
    label: 'Moderate',
    color: '#FBBF24',
    bg: 'rgba(251,191,36,0.14)',
    verdict: 'Minor governance concerns, generally acceptable.',
    advice: 'The company shows some areas that could improve, but nothing that demands immediate action. Standard monitoring is sufficient.',
  },
  LOW: {
    label: 'Low Risk',
    color: '#34D399',
    bg: 'rgba(52,211,153,0.12)',
    verdict: 'Good governance practices. No significant concerns.',
    advice: 'This company appears to be well-managed from a governance perspective. No red flags detected in the data we track.',
  },
};

// Plain-language explanations for non-finance users
const RISK_SIMPLE: Record<string, {
  title: string;
  simpleTitle: string;
  analogy: string;
  whyItMatters: string;
  goodVsBad: string;
  description: string;
}> = {
  pledge: {
    title: 'Promoter Share Pledge',
    simpleTitle: 'Owner Loan Collateral',
    analogy: 'Imagine you own a house and take a loan using that house as collateral. If you cannot repay, the bank takes your house. Similarly, company owners (promoters) sometimes pledge their shares as loan collateral. If the share price drops too much, the lender can forcibly sell those shares.',
    whyItMatters: 'When owners have pledged a high percentage of their shares, it means: (1) they needed money badly enough to risk their ownership, and (2) if the stock price falls, a chain reaction of forced selling can crash the price further.',
    goodVsBad: 'Below 10% = Generally safe. 10-25% = Worth watching. 25-50% = Concerning. Above 50% = Dangerous territory.',
    description: 'Percentage of owner shares used as loan collateral',
  },
  promoter_dilution: {
    title: 'Promoter Holding Dilution',
    simpleTitle: 'Owners Selling Their Stake',
    analogy: 'Think of it like a restaurant where the head chef gradually sells their ownership share to others. If they owned 60% and now own 35%, they have less reason to care about the restaurant\'s success. Their "skin in the game" is shrinking.',
    whyItMatters: 'When company owners steadily reduce their ownership, it may mean: (1) they are losing confidence in the company, (2) they need cash for other purposes, or (3) they are being forced to sell. This weakens their motivation to make the company succeed.',
    goodVsBad: 'Stable or increasing = Good sign. Slow decline over years = Normal in some cases. Rapid decline (10%+ in a few quarters) = Red flag.',
    description: 'How much ownership the founders/promoters have lost over time',
  },
  enforcement: {
    title: 'Regulatory Enforcement',
    simpleTitle: 'Government Penalties & Fines',
    analogy: 'Just like a person can get fined for breaking traffic rules, companies get penalized by regulators (like SEBI in India) for breaking market rules. These can range from small fines to serious bans.',
    whyItMatters: 'If a company has been penalized by regulators, it means they were caught doing something wrong. This could be insider trading, misleading investors, or other violations. It tells you the management may not always play by the rules.',
    goodVsBad: 'Zero enforcement actions = Clean record. Any active action = Serious concern. Multiple actions = Major red flag.',
    description: 'Whether the company has been fined or penalized by regulators',
  },
  auditor_instability: {
    title: 'Auditor Instability',
    simpleTitle: 'Changing Accountants Frequently',
    analogy: 'Imagine a person who keeps switching doctors every few months. You would wonder: are they "doctor shopping" to get the answer they want? Similarly, when a company frequently changes its auditor (the independent accountant who checks the books), it may mean the auditor refused to sign off on questionable accounts.',
    whyItMatters: 'Stable companies rarely change auditors. Frequent changes (2-3 different firms in 3-4 years) can signal: (1) auditors refused to approve the accounts, (2) management wanted someone more "flexible", or (3) internal disagreements about financial reporting.',
    goodVsBad: 'Same auditor for 4+ years = Stable. Changed once in 4 years = Usually normal. 2+ changes in 3 years = Suspicious.',
    description: 'How often the company has changed its independent accountants',
  },
  board_churn: {
    title: 'Board Churn',
    simpleTitle: 'Directors Quitting',
    analogy: 'A company\'s board of directors is like a team of advisors who oversee the CEO. If many of them resign in a short period, it is like crew members abandoning ship. They may know something that investors do not.',
    whyItMatters: 'Directors have insider knowledge about a company. When multiple directors resign at once (especially independent ones), it often signals they disagree with management decisions or foresee trouble ahead.',
    goodVsBad: 'Less than 10% turnover per year = Normal. 10-25% = Worth watching. Above 25% = Warning sign.',
    description: 'Rate of board member departures in the last 12 months',
  },
  predicted_failure: {
    title: 'AI Failure Probability Score',
    simpleTitle: 'AI Distress Prediction',
    analogy: 'Think of it like a weather forecast — the AI model has studied hundreds of companies that eventually had governance crises, and learned what patterns appeared beforehand. It uses those patterns to estimate how likely this company is to face similar problems.',
    whyItMatters: 'This score synthesises all the individual signals (pledge levels, board changes, enforcement history, etc.) through a machine learning model trained on real historical governance failures. It can catch early warning patterns that individual signals might miss.',
    goodVsBad: 'Below 15 = Low concern. 15-40 = Moderate watch. 40-65 = Elevated concern. Above 65 = High distress risk.',
    description: 'Machine learning model prediction of governance-linked distress probability',
  },
};

const GLOSSARY: Array<{ term: string; definition: string }> = [
  { term: 'Promoter', definition: 'The founder or main owner who started or controls the company. They typically hold a large portion of shares.' },
  { term: 'Pledge', definition: 'Using shares as collateral (guarantee) to get a loan from a bank. If the loan cannot be repaid, the bank can sell those shares.' },
  { term: 'Dilution', definition: 'When an owner\'s percentage of the company decreases, either because they sold shares or new shares were issued to others.' },
  { term: 'SEBI', definition: 'Securities and Exchange Board of India — the government body that regulates the stock market and protects investors.' },
  { term: 'Statutory Auditor', definition: 'An independent accounting firm hired to check whether the company\'s financial reports are accurate and honest.' },
  { term: 'Board of Directors', definition: 'A group of people elected by shareholders to oversee company management and make major decisions.' },
  { term: 'Enforcement Action', definition: 'A penalty or restriction imposed by a regulator (like SEBI) when a company breaks rules.' },
  { term: 'CIN', definition: 'Corporate Identification Number — a unique ID given to every company registered in India.' },
  { term: 'Composite Score', definition: 'A combined score (0-100) that considers all governance factors together. Higher = more risk.' },
  { term: 'ML Model', definition: 'Machine Learning model — a computer algorithm trained on historical data to predict which companies may face governance problems.' },
];

const HEALTH_GRADE_META: Record<string, { label: string; color: string; icon: any; simpleLabel: string }> = {
  evidence_grade: { label: 'Evidence Grade', color: '#34D399', icon: CheckCircle2, simpleLabel: 'Strong data — high confidence in this assessment' },
  partial: { label: 'Partial Data', color: '#FBBF24', icon: AlertCircle, simpleLabel: 'Some data missing — assessment may be incomplete' },
  thin: { label: 'Thin Coverage', color: '#F87171', icon: XCircle, simpleLabel: 'Limited data available — treat conclusions with caution' },
};

// ─── Helper Functions ────────────────────────────────────────────────────────

// Maps internal DB table / signal names → human-readable labels
const SIGNAL_LABELS: Record<string, string> = {
  shp_raw: 'Promoter shareholding filings',
  directors_raw: 'Board director records',
  auditor_history_raw: 'Auditor appointment history',
  enforcement_raw: 'Regulatory enforcement orders',
  ikg_edges: 'Corporate relationship graph',
  company_features: 'ML feature dataset',
  pledge_data: 'Share pledge disclosures',
  board_data: 'Board composition data',
  holding_data: 'Promoter holding data',
  auditor_data: 'Auditor change records',
};

// Converts raw evidence object → a readable plain-language sentence per flag code
function formatFlagEvidence(code: string, evidence: Record<string, any>): string | null {
  const fmt = (n: any, decimals = 1) =>
    n != null ? Number(n).toFixed(decimals) : null;
  const fmtInr = (n: any) =>
    n != null && Number(n) > 0 ? `₹${Number(n).toLocaleString('en-IN')}` : null;

  switch (code) {
    case 'PLEDGE_HIGH':
    case 'PLEDGE_ELEVATED': {
      const pct = fmt(evidence.value_pct);
      const q = evidence.quarter;
      if (!pct) return null;
      return `${pct}% of promoter shares currently pledged as loan collateral${q ? ` (as of quarter ${q})` : ''}.`;
    }
    case 'PLEDGE_RISING': {
      const from = fmt(evidence.from_pct);
      const to = fmt(evidence.to_pct);
      const date = evidence.as_on_date;
      if (!from || !to) return null;
      return `Pledge rose from ${from}% to ${to}%${date ? ` — latest reading on ${date}` : ''}. This upward trend increases forced-sale risk.`;
    }
    case 'PROMOTER_DILUTION': {
      const from = fmt(evidence.from_pct);
      const to = fmt(evidence.to_pct);
      const qs = evidence.quarters;
      if (!from || !to) return null;
      return `Promoter holding dropped from ${from}% to ${to}%${qs ? ` over ${qs} quarters` : ''}. That is a ${fmt(Number(from) - Number(to))}% reduction in owner stake.`;
    }
    case 'ENFORCEMENT_ACTION': {
      const count = evidence.count;
      const penalty = fmtInr(evidence.penalty_amount_inr ?? evidence.largest_penalty);
      const vtype = evidence.violation_type;
      const odate = evidence.order_date;
      const parts = [];
      if (count) parts.push(`${count} active regulatory order${count > 1 ? 's' : ''}`);
      if (vtype) parts.push(`violation: ${String(vtype).replace(/_/g, ' ')}`);
      if (penalty) parts.push(`largest fine: ${penalty}`);
      if (odate) parts.push(`order dated ${odate}`);
      return parts.length ? parts.join(' · ') + '.' : null;
    }
    case 'AUDITOR_CHURN': {
      const distinct = evidence.distinct_auditors;
      const fys = evidence.fiscal_years;
      const names = Array.isArray(distinct) ? distinct.join(', ') : null;
      if (!fys) return null;
      return `${Array.isArray(distinct) ? distinct.length : 'Multiple'} different audit firms appointed across ${fys} fiscal year(s)${names ? `: ${names}` : ''}. Frequent auditor changes are a recognised red flag.`;
    }
    case 'BOARD_CHURN': {
      const recent = evidence.recent_cessations;
      const total = evidence.board_size;
      if (recent == null || total == null) return null;
      const pct = total > 0 ? ((recent / total) * 100).toFixed(0) : '?';
      return `${recent} of ${total} board directors departed within 12 months — ${pct}% turnover rate. Independent directors leaving in groups is a serious warning sign.`;
    }
    default:
      return null;
  }
}

// Formats violation type raw string into readable form
function formatViolationType(raw: string | null | undefined): string {
  if (!raw) return 'Regulatory violation';
  const VIOLATION_MAP: Record<string, string> = {
    insider_trading: 'Insider Trading',
    front_running: 'Front Running (trading ahead of client orders)',
    market_manipulation: 'Market Manipulation',
    disclosure_violation: 'Failure to Disclose Information',
    takeover_violation: 'Takeover Code Violation',
    fraud: 'Fraud',
    misrepresentation: 'Misrepresentation to Investors',
    related_party: 'Related Party Transaction Violation',
    accounting_fraud: 'Accounting Fraud',
    non_compliance: 'Regulatory Non-Compliance',
  };
  const key = raw.toLowerCase().replace(/\s+/g, '_');
  return VIOLATION_MAP[key] || raw.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function generateVerdictSummary(data: GovernanceResult): { headline: string; details: string[]; takeaways: string[] } {
  const band = (data.igs?.band || data.band) as Band;
  const composite = data.igs?.composite_score ?? data.score;
  const flags = data.flags || [];
  const highFlags = flags.filter((f) => f.severity === 'high');
  const watchFlags = flags.filter((f) => f.severity === 'watch');
  const prob = data.igs?.model_probability;

  let headline = '';
  if (band === 'HIGH') {
    headline = 'This company has serious governance concerns that you should be aware of before investing.';
  } else if (band === 'ELEVATED') {
    headline = 'This company shows some warning signs in its governance that deserve your attention.';
  } else if (band === 'MODERATE') {
    headline = 'This company has minor governance issues but is generally in acceptable shape.';
  } else {
    headline = 'This company appears to be well-governed with no major concerns detected.';
  }

  const details: string[] = [];

  // Pledge context
  const pledgeScore = data.subscores?.pledge;
  if (pledgeScore != null && pledgeScore >= 75) {
    details.push('The owners have pledged a dangerously high portion of their shares as loan collateral. If the stock price falls significantly, it could trigger forced selling and a price crash.');
  } else if (pledgeScore != null && pledgeScore >= 50) {
    details.push('The owners have a significant portion of their shares pledged as loan collateral. This creates vulnerability if the stock price drops.');
  }

  // Dilution
  const dilScore = data.subscores?.promoter_dilution;
  if (dilScore != null && dilScore >= 50) {
    details.push('The owners have been steadily reducing their stake in the company. This decline in "skin in the game" is a concern.');
  }

  // Enforcement
  const enfScore = data.subscores?.enforcement;
  if (enfScore != null && enfScore > 0) {
    details.push('This company has active regulatory penalties or enforcement actions against it.');
  }

  // Probability
  if (prob != null && prob > 0.25) {
    details.push(`Based on historical patterns, our analysis estimates a ${(prob * 100).toFixed(0)}% chance this company could face governance-related distress.`);
  }

  // Key takeaways
  const takeaways: string[] = [];

  if (band === 'HIGH' || band === 'ELEVATED') {
    takeaways.push(`Overall governance risk score is ${composite?.toFixed(0)}/100 — ${band === 'HIGH' ? 'significantly above' : 'above'} the safety threshold of 25.`);
  } else {
    takeaways.push(`Overall governance risk score is ${composite?.toFixed(0)}/100 — within ${band === 'LOW' ? 'safe' : 'acceptable'} limits.`);
  }

  if (highFlags.length > 0) {
    takeaways.push(`${highFlags.length} critical warning${highFlags.length > 1 ? 's' : ''} detected that need attention.`);
  }
  if (watchFlags.length > 0) {
    takeaways.push(`${watchFlags.length} area${watchFlags.length > 1 ? 's' : ''} flagged for monitoring.`);
  }

  if (pledgeScore != null) {
    if (pledgeScore >= 50) {
      takeaways.push('High share pledge is the biggest single risk factor for this company.');
    } else if (pledgeScore === 0) {
      takeaways.push('No promoter shares are pledged — this is a positive sign.');
    }
  }

  if (prob != null) {
    if (prob < 0.1) {
      takeaways.push('Low probability of governance-linked financial distress.');
    } else if (prob > 0.3) {
      takeaways.push('Elevated probability of governance-linked problems — proceed with caution.');
    }
  }

  const coveredSignals = Object.values(data.coverage || {}).filter(Boolean).length;
  const totalSignals = Object.keys(data.coverage || {}).length;
  if (totalSignals > 0) {
    takeaways.push(`Assessment based on ${coveredSignals} out of ${totalSignals} possible data signals.`);
  }

  return { headline, details, takeaways };
}

function getScoreContext(score: number): string {
  if (score >= 75) return 'Critical — among the highest-risk companies';
  if (score >= 50) return 'High concern — above average risk';
  if (score >= 25) return 'Moderate — some areas need attention';
  return 'Good — below the concern threshold';
}

// ─── Sub-components ──────────────────────────────────────────────────────────

const BandChip: React.FC<{ band: Band | null | undefined }> = ({ band }) => {
  if (!band) return <span className="gov-band-chip" style={{ color: 'var(--text-muted)', background: 'rgba(148,163,184,0.10)' }}>Not rated</span>;
  const m = BAND_META[band];
  return <span className="gov-band-chip" style={{ color: m.color, background: m.bg }}>{m.label}</span>;
};

const ScoreBar: React.FC<{ value: number; band: Band }> = ({ value, band }) => {
  const pct = Math.max(2, Math.min(100, value));
  return (
    <div className="gov-scorebar">
      <div className="gov-scorebar-fill" style={{ width: `${pct}%`, background: BAND_META[band].color }} />
      <span className="gov-scorebar-val">{value.toFixed(0)}</span>
    </div>
  );
};

// ─── Score Gauge (Visual Meter) ──────────────────────────────────────────────

const ScoreGauge: React.FC<{ score: number; band: Band }> = ({ score, band }) => {
  const angle = (score / 100) * 180; // 0-180 degrees
  const meta = BAND_META[band];

  return (
    <div className="gov-gauge">
      <div className="gov-gauge-visual">
        <svg viewBox="0 0 200 110" className="gov-gauge-svg">
          {/* Background arc */}
          <path
            d="M 10 100 A 90 90 0 0 1 190 100"
            fill="none"
            stroke="rgba(148, 163, 184, 0.12)"
            strokeWidth="16"
            strokeLinecap="round"
          />
          {/* Color zones */}
          <path d="M 10 100 A 90 90 0 0 1 55 28" fill="none" stroke="rgba(52, 211, 153, 0.3)" strokeWidth="16" strokeLinecap="round" />
          <path d="M 55 28 A 90 90 0 0 1 100 10" fill="none" stroke="rgba(251, 191, 36, 0.3)" strokeWidth="16" />
          <path d="M 100 10 A 90 90 0 0 1 145 28" fill="none" stroke="rgba(251, 146, 60, 0.3)" strokeWidth="16" />
          <path d="M 145 28 A 90 90 0 0 1 190 100" fill="none" stroke="rgba(248, 113, 113, 0.3)" strokeWidth="16" strokeLinecap="round" />
          {/* Needle */}
          <line
            x1="100"
            y1="100"
            x2={100 + 70 * Math.cos(((180 - angle) * Math.PI) / 180)}
            y2={100 - 70 * Math.sin(((180 - angle) * Math.PI) / 180)}
            stroke={meta.color}
            strokeWidth="3"
            strokeLinecap="round"
          />
          <circle cx="100" cy="100" r="6" fill={meta.color} />
        </svg>
        {/* Labels */}
        <div className="gov-gauge-labels">
          <span className="gov-gauge-lo">Safe</span>
          <span className="gov-gauge-hi">High Risk</span>
        </div>
      </div>
      <div className="gov-gauge-score" style={{ color: meta.color }}>{score.toFixed(0)}<small>/100</small></div>
      <div className="gov-gauge-context">{getScoreContext(score)}</div>
    </div>
  );
};

// ─── Verdict Card ────────────────────────────────────────────────────────────

const VerdictCard: React.FC<{ data: GovernanceResult; band: Band }> = ({ data, band }) => {
  const { headline, details, takeaways } = useMemo(() => generateVerdictSummary(data), [data]);
  const meta = BAND_META[band];

  return (
    <div className="gov-verdict" style={{ borderColor: meta.color }}>
      <div className="gov-verdict-header">
        <div className="gov-verdict-icon" style={{ background: meta.bg, color: meta.color }}>
          {band === 'HIGH' ? <AlertTriangle size={22} /> :
           band === 'ELEVATED' ? <Eye size={22} /> :
           band === 'LOW' ? <CheckCircle2 size={22} /> :
           <Shield size={22} />}
        </div>
        <div className="gov-verdict-title-area">
          <h3 className="gov-verdict-title">Should You Be Concerned?</h3>
          <span className="gov-verdict-band" style={{ color: meta.color }}>{meta.label}</span>
        </div>
      </div>

      <p className="gov-verdict-headline">{headline}</p>

      {details.length > 0 && (
        <div className="gov-verdict-details">
          {details.map((d, i) => <p key={i} className="gov-verdict-detail-item">{d}</p>)}
        </div>
      )}

      <div className="gov-verdict-advice">
        <Lightbulb size={14} />
        <span>{meta.advice}</span>
      </div>

      {takeaways.length > 0 && (
        <div className="gov-takeaways">
          <div className="gov-takeaways-title"><Target size={13} /> Key Takeaways</div>
          <ul className="gov-takeaways-list">
            {takeaways.map((t, i) => <li key={i}>{t}</li>)}
          </ul>
        </div>
      )}
    </div>
  );
};

// ─── Metric Cards (with plain-language subtitles) ────────────────────────────

const MetricCards: React.FC<{ data: GovernanceResult; composite: number | null; band: Band | null }> = ({ data, composite }) => {
  const igs = data.igs;
  const insufficient = !!igs?.insufficient_data;

  return (
    <div className="gov-section">
      <div className="gov-section-title">
        <Scale size={14} /> Scores At a Glance
      </div>
      <div className="gov-metric-row">
        <div className="gov-metric">
          <span className="gov-metric-label">Overall Risk Score</span>
          <span className="gov-metric-value">{composite != null ? composite.toFixed(0) : '—'}<small>/100</small></span>
          <span className="gov-metric-hint">Combined measure of all governance risks. Higher = more risky.</span>
        </div>
        <div className="gov-metric">
          <span className="gov-metric-label">Rule-Based Score</span>
          <span className="gov-metric-value">{data.score != null ? data.score.toFixed(0) : '—'}</span>
          <span className="gov-metric-hint">Score from checking known risk patterns in official filings.</span>
        </div>
        <div className="gov-metric">
          <span className="gov-metric-label">AI Model Score</span>
          <span className="gov-metric-value">
            {igs?.model_risk != null ? igs.model_risk.toFixed(0) : insufficient ? 'N/A' : '—'}
          </span>
          <span className="gov-metric-hint">Machine learning prediction based on historical governance failures.</span>
        </div>
        <div className="gov-metric">
          <span className="gov-metric-label">Distress Probability</span>
          <span className="gov-metric-value">
            {igs?.model_probability != null ? `${(igs.model_probability * 100).toFixed(1)}%` : '—'}
          </span>
          <span className="gov-metric-hint">Estimated chance of governance-linked financial trouble.</span>
        </div>
      </div>
    </div>
  );
};

// ─── Pledge Trend Chart ──────────────────────────────────────────────────────

const PledgeTrendChart: React.FC<{ signals: GovernanceResult['signals'] }> = ({ signals }) => {
  if (!signals?.pledge_history || signals.pledge_history.length < 2) return null;

  const history = [...signals.pledge_history].reverse(); // oldest first
  const labels = history.map((h) => h.quarter || h.as_on_date || '—');
  const pledgeData = history.map((h) => h.pledge_pct ?? 0);
  const holdingData = history.map((h) => h.promoter_holding_pct ?? 0);

  // Determine trend
  const firstPledge = pledgeData[0] || 0;
  const lastPledge = pledgeData[pledgeData.length - 1] || 0;
  const firstHolding = holdingData[0] || 0;
  const lastHolding = holdingData[holdingData.length - 1] || 0;
  const pledgeTrend = lastPledge > firstPledge ? 'rising' : lastPledge < firstPledge ? 'falling' : 'stable';
  const holdingTrend = lastHolding < firstHolding ? 'falling' : lastHolding > firstHolding ? 'rising' : 'stable';

  const chartData = {
    labels,
    datasets: [
      {
        label: 'Shares Pledged %',
        data: pledgeData,
        borderColor: '#F87171',
        backgroundColor: 'rgba(248, 113, 113, 0.1)',
        fill: true,
        borderWidth: 2,
        tension: 0.3,
        pointRadius: 4,
        pointBackgroundColor: '#F87171',
      },
      {
        label: 'Owner Holding %',
        data: holdingData,
        borderColor: '#38BDF8',
        backgroundColor: 'rgba(56, 189, 248, 0.08)',
        fill: true,
        borderWidth: 2,
        tension: 0.3,
        pointRadius: 4,
        pointBackgroundColor: '#38BDF8',
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { intersect: false, mode: 'index' as const },
    plugins: {
      legend: {
        position: 'bottom' as const,
        labels: { color: '#94A3B8', usePointStyle: true, font: { size: 11 }, padding: 16 },
      },
      tooltip: {
        backgroundColor: 'rgba(15, 23, 42, 0.95)',
        titleColor: '#F1F5F9',
        bodyColor: '#94A3B8',
        borderColor: 'rgba(148, 163, 184, 0.2)',
        borderWidth: 1,
        callbacks: {
          label: (ctx: any) => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}%`,
        },
      },
    },
    scales: {
      x: { grid: { display: false }, ticks: { color: '#64748B', font: { size: 10 } } },
      y: {
        min: 0, max: 100,
        grid: { color: 'rgba(148, 163, 184, 0.08)' },
        ticks: { color: '#64748B', font: { size: 10 }, callback: (v: any) => `${v}%` },
      },
    },
  };

  return (
    <div className="gov-section gov-chart-section">
      <div className="gov-section-title">
        <TrendingDown size={14} /> Ownership & Pledge Trend Over Time
      </div>
      <div className="gov-chart-explain">
        <p><strong>What this chart shows:</strong> The red line is how much of the owner's shares are pledged (used as loan collateral). The blue line shows how much of the company the owners actually hold. Ideally, you want red (pledge) going DOWN and blue (holding) staying FLAT or going UP.</p>
        <div className="gov-chart-insight">
          <Lightbulb size={13} />
          <span>
            Pledge is <strong style={{ color: pledgeTrend === 'rising' ? '#F87171' : '#34D399' }}>{pledgeTrend}</strong>
            {' '}and owner holding is <strong style={{ color: holdingTrend === 'falling' ? '#F87171' : '#34D399' }}>{holdingTrend}</strong>
            {pledgeTrend === 'rising' && holdingTrend === 'falling' ? ' — this combination is a red flag.' : '.'}
          </span>
        </div>
      </div>
      <div className="gov-chart-container">
        <Line data={chartData} options={options} />
      </div>
    </div>
  );
};

// ─── Risk Radar Chart ────────────────────────────────────────────────────────

const RiskRadarChart: React.FC<{ subscores: Record<string, number> }> = ({ subscores }) => {
  const entries = Object.entries(subscores).filter(([, v]) => typeof v === 'number');
  if (entries.length < 3) return null;

  const labels = entries.map(([k]) => RISK_SIMPLE[k]?.simpleTitle || k.replace(/_/g, ' '));
  const data = entries.map(([, v]) => v);

  const chartData = {
    labels,
    datasets: [
      {
        label: 'Risk Level',
        data,
        backgroundColor: 'rgba(248, 113, 113, 0.15)',
        borderColor: '#F87171',
        borderWidth: 2,
        pointBackgroundColor: data.map((v) => (v >= 75 ? '#F87171' : v >= 50 ? '#FB923C' : v >= 25 ? '#FBBF24' : '#34D399')),
        pointRadius: 5,
        pointHoverRadius: 7,
      },
      {
        label: 'Concern Threshold',
        data: entries.map(() => 50),
        backgroundColor: 'transparent',
        borderColor: 'rgba(148, 163, 184, 0.3)',
        borderWidth: 1,
        borderDash: [4, 4],
        pointRadius: 0,
      },
    ],
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    scales: {
      r: {
        beginAtZero: true,
        max: 100,
        grid: { color: 'rgba(148, 163, 184, 0.1)' },
        angleLines: { color: 'rgba(148, 163, 184, 0.1)' },
        pointLabels: { color: '#94A3B8', font: { size: 10 } },
        ticks: { display: false },
      },
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'rgba(15, 23, 42, 0.95)',
        titleColor: '#F1F5F9',
        bodyColor: '#94A3B8',
        borderColor: 'rgba(148, 163, 184, 0.2)',
        borderWidth: 1,
        callbacks: { label: (ctx: any) => `Risk: ${ctx.parsed.r.toFixed(0)}/100` },
      },
    },
  };

  return (
    <div className="gov-section gov-chart-section">
      <div className="gov-section-title">
        <Shield size={14} /> Risk Overview — All Dimensions
      </div>
      <div className="gov-chart-explain">
        <p><strong>How to read:</strong> Each point on the radar shows one type of governance risk. Points closer to the center (smaller shape) = lower risk. Points stretching outward = higher risk. The dashed line marks the "concern threshold" — anything beyond it deserves attention.</p>
      </div>
      <div className="gov-radar-container">
        <Radar data={chartData} options={options} />
      </div>
    </div>
  );
};

// ─── Risk Dimension Detail (User-Friendly) ───────────────────────────────────

const RiskDimensionDetail: React.FC<{ subscores: Record<string, number>; coverage: Record<string, boolean> }> = ({ subscores, coverage }) => {
  const entries = Object.entries(subscores)
    .filter(([, v]) => typeof v === 'number')
    .sort((a, b) => (b[1] as number) - (a[1] as number));

  if (entries.length === 0) return null;

  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <div className="gov-section">
      <div className="gov-section-title">
        <Scale size={14} /> Understanding Each Risk Factor
      </div>
      <p className="gov-section-subtitle">Click any factor below to see a detailed explanation in plain language.</p>
      <div className="gov-dimensions-grid">
        {entries.map(([key, val]) => {
          const v = val as number;
          const b: Band = v >= 75 ? 'HIGH' : v >= 50 ? 'ELEVATED' : v >= 25 ? 'MODERATE' : 'LOW';
          const info = RISK_SIMPLE[key];
          const hasCoverage = coverage[key] !== false;
          const isExpanded = expanded === key;

          return (
            <div key={key} className={`gov-dim-detail ${isExpanded ? 'gov-dim-expanded' : ''}`} onClick={() => setExpanded(isExpanded ? null : key)}>
              <div className="gov-dim-detail-header">
                <div className="gov-dim-title-area">
                  <span className="gov-dim-detail-name">{info?.simpleTitle || key.replace(/_/g, ' ')}</span>
                  <span className="gov-dim-technical-name">{info?.title || key}</span>
                </div>
                <div className="gov-dim-detail-score">
                  <ScoreBar value={v} band={b} />
                </div>
                <HelpCircle size={14} className="gov-dim-expand-icon" />
              </div>

              {!hasCoverage && (
                <div className="gov-dim-no-data"><Info size={12} /> No data available — not factored into the score</div>
              )}

              {isExpanded && info && (
                <div className="gov-dim-detail-body">
                  <div className="gov-dim-analogy">
                    <strong>In simple terms:</strong> {info.analogy}
                  </div>
                  <div className="gov-dim-why">
                    <strong>Why it matters:</strong> {info.whyItMatters}
                  </div>
                  <div className="gov-dim-range">
                    <strong>What is good vs bad:</strong> {info.goodVsBad}
                  </div>
                  <div className="gov-dim-current">
                    <strong>This company:</strong> Score is {v.toFixed(0)}/100 — 
                    <span style={{ color: BAND_META[b].color, fontWeight: 700 }}> {BAND_META[b].label}</span>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ─── Data Health Indicator ───────────────────────────────────────────────────

// Human-readable labels for what each data signal actually represents
const HEALTH_SIGNAL_LABELS: Record<string, { label: string; description: string }> = {
  pledge: { label: 'Share Pledge Data', description: 'Quarterly disclosures of how much promoter stock is pledged' },
  promoter_dilution: { label: 'Ownership History', description: 'How promoter holding has changed quarter by quarter' },
  enforcement: { label: 'Regulatory Orders', description: 'SEBI / Exchange enforcement and penalty records' },
  auditor_instability: { label: 'Auditor Records', description: 'History of statutory auditor appointments and changes' },
  board_churn: { label: 'Board Records', description: 'Director appointment and resignation history' },
  shp_raw: { label: 'Shareholding Filings', description: 'Quarterly shareholding pattern data filed with exchanges' },
  directors_raw: { label: 'Director Database', description: 'Board composition and director history' },
  auditor_history_raw: { label: 'Auditor History', description: 'Year-by-year statutory auditor information' },
  enforcement_raw: { label: 'Enforcement Orders', description: 'Regulatory penalty and adjudication records' },
  ikg_edges: { label: 'Relationship Graph', description: 'Corporate connections through shared directors and entities' },
};

const DataHealthSection: React.FC<{ health: CompanyHealth | null; loading: boolean }> = ({ health, loading }) => {
  if (loading) return <div className="gov-section"><div className="gov-empty" style={{ padding: '16px', textAlign: 'left', fontSize: '12px' }}>Checking data quality…</div></div>;
  if (!health) return null;

  const meta = HEALTH_GRADE_META[health.grade] || HEALTH_GRADE_META.thin;
  const Icon = meta.icon;
  const pct = (health.completeness_score * 100).toFixed(0);

  const gradeExplain: Record<string, string> = {
    evidence_grade: `${pct}% of all possible governance signals are available for this company. This is a strong data set — the assessment below has high confidence.`,
    partial: `${pct}% of signals available. Some data is missing, which means a few governance dimensions could not be scored. The assessment is directionally correct but may not capture everything.`,
    thin: `Only ${pct}% of signals are available. This company has limited governance data in our database. Treat the scores as indicative, not definitive. Consider doing additional research.`,
  };

  return (
    <div className="gov-section gov-health-section">
      <div className="gov-section-title">
        <Database size={14} /> How Confident Are We In This Assessment?
      </div>
      <p className="gov-section-subtitle">
        Our scoring depends on how much official data exists for this company. This section tells you exactly how complete that data is.
      </p>

      <div className="gov-health-header">
        <div className="gov-health-badge" style={{ color: meta.color, borderColor: meta.color }}>
          <Icon size={16} />
          <span>{meta.label}</span>
        </div>
        <div className="gov-health-completeness">
          <div className="gov-health-bar-track">
            <div
              className="gov-health-bar-fill"
              style={{ width: `${pct}%`, background: meta.color }}
            />
          </div>
          <span style={{ color: meta.color }}>{pct}% complete</span>
        </div>
      </div>

      <p className="gov-health-simple">{gradeExplain[health.grade] || meta.simpleLabel}</p>

      <div className="gov-health-grid">
        <div className="gov-health-col">
          <span className="gov-health-col-title" style={{ color: '#34D399' }}>
            <CheckCircle2 size={12} /> Data We Have ({health.present.length} signals)
          </span>
          {health.present.map((p) => {
            const sig = HEALTH_SIGNAL_LABELS[p];
            return (
              <div key={p} className="gov-health-item gov-health-present">
                <CheckCircle2 size={11} />
                <div>
                  <span className="gov-health-item-label">{sig?.label || p.replace(/_/g, ' ')}</span>
                  {sig?.description && <span className="gov-health-item-desc">{sig.description}</span>}
                </div>
              </div>
            );
          })}
        </div>
        <div className="gov-health-col">
          <span className="gov-health-col-title" style={{ color: '#F87171' }}>
            <XCircle size={12} /> Data We Are Missing ({health.missing.length} signals)
          </span>
          {health.missing.length > 0 ? health.missing.map((m) => {
            const sig = HEALTH_SIGNAL_LABELS[m];
            return (
              <div key={m} className="gov-health-item gov-health-missing">
                <XCircle size={11} />
                <div>
                  <span className="gov-health-item-label">{sig?.label || m.replace(/_/g, ' ')}</span>
                  {sig?.description && <span className="gov-health-item-desc">{sig.description}</span>}
                </div>
              </div>
            );
          }) : (
            <div className="gov-health-item" style={{ color: '#34D399' }}>
              <CheckCircle2 size={11} /> All signals available — no gaps in coverage
            </div>
          )}
        </div>
      </div>

      <div className="gov-health-note">
        <Info size={12} />
        <span>
          <strong>Important:</strong> Missing data never inflates the risk score. If a signal is unavailable, that dimension is excluded from the calculation entirely. A score is only generated when there is real evidence.
        </span>
      </div>
    </div>
  );
};

// ─── Provenance / Sources Section ────────────────────────────────────────────

const ProvenanceSection: React.FC<{ provenance: CompanyProvenance | null; loading: boolean }> = ({ provenance, loading }) => {
  if (loading) return <div className="gov-section"><div className="gov-empty" style={{ padding: '16px', textAlign: 'left', fontSize: '12px' }}>Loading source data…</div></div>;
  if (!provenance || !provenance.sections || provenance.sections.length === 0) return null;

  const citePct = (provenance.summary.citation_ratio * 100).toFixed(0);
  const [showAll, setShowAll] = useState(false);
  const visibleSections = showAll ? provenance.sections : provenance.sections.slice(0, 5);

  return (
    <div className="gov-section">
      <div className="gov-section-title">
        <FileSearch size={14} /> Where Does This Data Come From?
      </div>
      <p className="gov-section-subtitle">
        Every fact used in this governance assessment is traced to an official source — regulatory filings, exchange disclosures, or government records.
        This section shows the evidence trail so you can verify anything independently.
      </p>

      <div className="gov-prov-stats-row">
        <div className="gov-prov-stat">
          <span className="gov-prov-stat-value">{provenance.summary.total_facts}</span>
          <span className="gov-prov-stat-label">Facts analyzed</span>
        </div>
        <div className="gov-prov-stat">
          <span className="gov-prov-stat-value" style={{ color: Number(citePct) >= 70 ? '#34D399' : '#FBBF24' }}>{citePct}%</span>
          <span className="gov-prov-stat-label">Backed by citations</span>
        </div>
        <div className="gov-prov-stat">
          <span className="gov-prov-stat-value">{provenance.summary.predicates}</span>
          <span className="gov-prov-stat-label">Data categories</span>
        </div>
      </div>

      {Number(citePct) < 70 && (
        <div className="gov-prov-warn">
          <AlertCircle size={13} />
          <span>
            Only {citePct}% of facts have direct source citations. The remaining facts are derived from cross-references and may have lower confidence.
          </span>
        </div>
      )}

      <div className="gov-prov-sections">
        {visibleSections.map((section) => (
          <div key={section.predicate} className="gov-prov-group">
            <div className="gov-prov-label">{section.label || section.predicate.replace(/_/g, ' ')}</div>
            <div className="gov-prov-facts">
              {section.facts.slice(0, 3).map((fact, i) => {
                const confPct = (fact.confidence * 100).toFixed(0);
                const confColor = fact.confidence >= 0.8 ? '#34D399' : fact.confidence >= 0.5 ? '#FBBF24' : '#F87171';
                const confLabel = fact.confidence >= 0.8 ? 'High confidence' : fact.confidence >= 0.5 ? 'Medium confidence' : 'Low confidence';
                return (
                  <div key={i} className="gov-prov-fact">
                    <span className="gov-prov-value">{String(fact.value).slice(0, 80)}</span>
                    <div className="gov-prov-fact-meta">
                      {fact.as_of && <span className="gov-prov-date">as of {fact.as_of}</span>}
                      <span
                        className="gov-prov-conf"
                        title={`${confLabel}: we are ${confPct}% confident in this data point`}
                        style={{ color: confColor, borderColor: confColor }}
                      >
                        {confPct}% {confLabel}
                      </span>
                      {fact.evidence?.source_url && (
                        <a href={fact.evidence.source_url} target="_blank" rel="noopener noreferrer" className="gov-prov-link">
                          <ExternalLink size={10} /> Verify source
                        </a>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {provenance.sections.length > 5 && (
        <button className="gov-prov-show-more" onClick={() => setShowAll(!showAll)}>
          {showAll ? 'Show less' : `Show ${provenance.sections.length - 5} more categories`}
        </button>
      )}
    </div>
  );
};

// ─── Network Section ─────────────────────────────────────────────────────────

const NetworkSection: React.FC<{ network: CompanyNetwork | null; loading: boolean }> = ({ network, loading }) => {
  if (loading) return <div className="gov-section"><div className="gov-empty" style={{ padding: '16px', textAlign: 'left', fontSize: '12px' }}>Loading connections…</div></div>;
  if (!network || !network.connected_companies || network.connected_companies.length === 0) return null;

  // Flag companies with many shared directors as higher risk connections
  const highlyConnected = network.connected_companies.filter(c => c.shared_directors >= 2);

  return (
    <div className="gov-section">
      <div className="gov-section-title">
        <Network size={14} /> Director Network — Connected Companies
      </div>
      <p className="gov-section-subtitle">
        A director sitting on multiple company boards creates links between those companies. This matters for governance because:
        decisions affecting one company can influence others, and a director may face conflicts of interest when the interests of two companies clash.
      </p>

      <div className="gov-net-stats">
        <div className="gov-net-stat">
          <span className="gov-net-stat-value">{network.summary.directors}</span>
          <span className="gov-net-stat-label">Board directors</span>
        </div>
        <div className="gov-net-stat">
          <span className="gov-net-stat-value">{network.summary.connected_companies}</span>
          <span className="gov-net-stat-label">Connected companies</span>
        </div>
        {highlyConnected.length > 0 && (
          <div className="gov-net-stat">
            <span className="gov-net-stat-value" style={{ color: '#FBBF24' }}>{highlyConnected.length}</span>
            <span className="gov-net-stat-label">Strong connections (2+ shared)</span>
          </div>
        )}
      </div>

      {highlyConnected.length > 0 && (
        <div className="gov-net-alert">
          <AlertCircle size={13} />
          <span>
            {highlyConnected.length} company{highlyConnected.length > 1 ? 's' : ''} share{highlyConnected.length === 1 ? 's' : ''} 2 or more directors with this company.
            Heavily overlapping boards can lead to coordinated decisions that may not be in the interest of minority shareholders.
          </span>
        </div>
      )}

      <div className="gov-net-grid">
        {network.connected_companies.slice(0, 12).map((co) => (
          <div key={co.id} className={`gov-net-item ${co.shared_directors >= 2 ? 'gov-net-item-strong' : ''}`}>
            <Building2 size={13} />
            <div className="gov-net-item-body">
              <span className="gov-net-co-name">{co.name}</span>
              <span className="gov-net-shared">
                {co.shared_directors} shared director{co.shared_directors > 1 ? 's' : ''}
                {co.shared_directors >= 2 && <span className="gov-net-strong-badge">Strong link</span>}
              </span>
            </div>
          </div>
        ))}
      </div>

      {network.connected_companies.length > 12 && (
        <div className="gov-net-more">
          + {network.connected_companies.length - 12} more connected companies not shown
        </div>
      )}
    </div>
  );
};

// ─── ML Feature Name Mapping ─────────────────────────────────────────────────

const ML_FEATURE_LABELS: Record<string, { name: string; explanation: string; category: string }> = {
  pledge_pct: {
    name: 'Current Pledge Level',
    explanation: 'What percentage of the promoter\'s shares are currently pledged as loan collateral.',
    category: 'Pledge Risk',
  },
  pledge_pct_qoq_delta: {
    name: 'Pledge Change (Quarter)',
    explanation: 'How much the pledge percentage changed from last quarter. Positive = pledge increased.',
    category: 'Pledge Risk',
  },
  pledge_slope_4q: {
    name: 'Pledge Trend (4 Quarters)',
    explanation: 'The overall direction of pledge over the last 4 quarters. Rising slope = pledge is consistently growing.',
    category: 'Pledge Risk',
  },
  pledge_accel: {
    name: 'Pledge Acceleration',
    explanation: 'Whether the rate of pledge increase is itself accelerating. Like a car speeding up — the problem is getting worse faster.',
    category: 'Pledge Risk',
  },
  promoter_holding_pct: {
    name: 'Current Owner Holding',
    explanation: 'What percentage of the company the promoters/owners currently hold.',
    category: 'Ownership',
  },
  holding_dilution_4q: {
    name: 'Ownership Decline (4 Quarters)',
    explanation: 'How much the promoter\'s holding has dropped over the last 4 quarters.',
    category: 'Ownership',
  },
  pledge_quarters_observed: {
    name: 'Data History Length',
    explanation: 'How many quarters of pledge data we have. More history = more reliable trend analysis.',
    category: 'Data Quality',
  },
  director_count: {
    name: 'Board Size',
    explanation: 'Total number of directors on the board. Very small boards may lack independent oversight.',
    category: 'Board',
  },
  board_churn_12m: {
    name: 'Board Turnover Rate',
    explanation: 'Percentage of directors who left in the past 12 months relative to total board size.',
    category: 'Board',
  },
  recent_cessations_12m: {
    name: 'Directors Departed',
    explanation: 'Number of directors who resigned or were removed in the last 12 months.',
    category: 'Board',
  },
  own_enforcement_count: {
    name: 'Company Penalties',
    explanation: 'Number of regulatory enforcement actions directly against this company.',
    category: 'Regulatory',
  },
  director_enforcement_count: {
    name: 'Director Penalties',
    explanation: 'Number of enforcement actions against individuals who serve as directors of this company.',
    category: 'Regulatory',
  },
  enforcement_proximity_hops: {
    name: 'Regulatory Proximity',
    explanation: 'How close this company is (through shared directors) to other companies with enforcement actions.',
    category: 'Regulatory',
  },
  auditor_count_5y: {
    name: 'Auditor Changes (5 Years)',
    explanation: 'Number of different audit firms in the last 5 years. Stable companies rarely change auditors.',
    category: 'Auditor',
  },
  mid_term_auditor_change: {
    name: 'Mid-Term Auditor Swap',
    explanation: 'Whether the auditor was changed in the middle of a term (not at natural rotation). This is unusual and suspicious.',
    category: 'Auditor',
  },
  rpt_party_count: {
    name: 'Related Party Transactions',
    explanation: 'Number of related parties the company transacts with. High numbers may indicate money flowing to connected entities.',
    category: 'Transparency',
  },
  rpt_relationship_types: {
    name: 'Related Party Types',
    explanation: 'Diversity of related-party relationship types. More types = more complex web of connected entities.',
    category: 'Transparency',
  },
  director_other_boards: {
    name: 'Directors\' Other Roles',
    explanation: 'How many other company boards the directors serve on. Over-committed directors may not provide adequate oversight.',
    category: 'Board',
  },
  shared_failure_director_count: {
    name: 'Directors from Failed Companies',
    explanation: 'Number of directors who also served on boards of companies that previously failed. A significant warning sign.',
    category: 'Board',
  },
  enforcement_2hop_count: {
    name: 'Network Enforcement Actions',
    explanation: 'Enforcement actions within 2 connections (shared directors) of this company. "Guilt by association" signal.',
    category: 'Regulatory',
  },
  beneish_m_score: {
    name: 'Earnings Manipulation Score',
    explanation: 'Statistical model (Beneish M-Score) that estimates the likelihood of earnings manipulation based on financial ratios.',
    category: 'Financial',
  },
  accrual_ratio: {
    name: 'Accrual Ratio',
    explanation: 'Measures how much of the reported profit is "real" cash vs accounting entries. High accruals can signal aggressive accounting.',
    category: 'Financial',
  },
};

// ─── Flagged Signals (User-Friendly) ─────────────────────────────────────────

const FlaggedSignals: React.FC<{ flags: GovernanceResult['flags'] }> = ({ flags }) => {
  if (!flags || flags.length === 0) return null;

  const highFlags = flags.filter((f) => f.severity === 'high');
  const watchFlags = flags.filter((f) => f.severity === 'watch');
  if (highFlags.length === 0 && watchFlags.length === 0) return null;

  const renderFlag = (f: typeof flags[0], i: number) => {
    const plainEvidence = formatFlagEvidence(f.code, f.evidence || {});
    const sourceUrl = f.evidence?.source_url || f.evidence?.pdf_url;
    const sourceTable = f.evidence?.source_table;
    const humanSource = sourceTable ? SIGNAL_LABELS[sourceTable] || sourceTable.replace(/_/g, ' ') : null;

    return (
      <div key={i} className="gov-flag">
        <span
          className="gov-flag-sev"
          style={{ color: f.severity === 'high' ? '#F87171' : '#FBBF24' }}
        >●</span>
        <div className="gov-flag-body">
          {/* Primary human-readable sentence */}
          <div className="gov-flag-detail">{f.detail}</div>

          {/* Plain-language evidence sentence */}
          {plainEvidence && (
            <div className="gov-flag-plain-evidence">{plainEvidence}</div>
          )}

          {/* Source attribution */}
          <div className="gov-flag-attribution">
            {humanSource && <span>Data source: {humanSource}</span>}
            {sourceUrl && (
              <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className="gov-prov-link">
                <ExternalLink size={10} /> View official filing
              </a>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="gov-section">
      <div className="gov-section-title">
        <AlertTriangle size={14} /> Specific Issues Found
      </div>
      <p className="gov-section-subtitle">
        These are concrete findings from official regulatory filings — not opinions. Every item below can be verified against a public source.
      </p>
      {highFlags.length > 0 && (
        <div className="gov-flag-group">
          <div className="gov-flag-group-title gov-flag-high">
            Serious Concerns ({highFlags.length}) — requires attention
          </div>
          {highFlags.map(renderFlag)}
        </div>
      )}
      {watchFlags.length > 0 && (
        <div className="gov-flag-group">
          <div className="gov-flag-group-title gov-flag-watch">
            Keep An Eye On ({watchFlags.length}) — monitor over next quarters
          </div>
          {watchFlags.map(renderFlag)}
        </div>
      )}
    </div>
  );
};

// ─── AI Model Factors (replaces raw "info" flags) ────────────────────────────

const AIModelFactors: React.FC<{ flags: GovernanceResult['flags']; probability: number | null }> = ({ flags, probability }) => {
  const infoFlags = (flags || []).filter((f) => f.severity === 'info');
  if (infoFlags.length === 0) return null;

  // Parse into structured factors
  const factors = infoFlags.map((f) => {
    const featureName = f.evidence?.feature || f.detail || '';
    const shapValue = typeof f.evidence?.shap === 'number' ? f.evidence.shap : 0;
    const value = f.evidence?.value;
    const direction = f.evidence?.direction || 'neutral';
    const meta = ML_FEATURE_LABELS[featureName];

    return { featureName, shapValue, value, direction, meta };
  });

  // Split into impactful vs neutral
  const impactful = factors.filter((f) => Math.abs(f.shapValue) > 0.001 || (f.direction !== 'neutral'));
  const neutral = factors.filter((f) => Math.abs(f.shapValue) <= 0.001 && f.direction === 'neutral');

  // Group by category
  const categories = new Map<string, typeof factors>();
  for (const f of factors) {
    const cat = f.meta?.category || 'Other';
    if (!categories.has(cat)) categories.set(cat, []);
    categories.get(cat)!.push(f);
  }

  const [showAll, setShowAll] = useState(false);

  return (
    <div className="gov-section gov-ai-section">
      <div className="gov-section-title">
        <Eye size={14} /> What Our AI Model Analyzed
      </div>
      
      <div className="gov-ai-intro">
        <p>
          Our machine learning model examines {factors.length} different data points about this company to predict governance risk. 
          Below is a transparency report showing what the model looked at and how each factor influenced its prediction.
        </p>
        {probability != null && (
          <p className="gov-ai-prediction">
            <strong>Model prediction:</strong> {(probability * 100).toFixed(1)}% estimated probability of governance-linked distress. 
            {probability < 0.1 ? ' This is low — the model sees no strong pattern of concern.' :
             probability < 0.25 ? ' This is moderate — some patterns worth watching.' :
             probability < 0.5 ? ' This is elevated — historical patterns suggest caution.' :
             ' This is high — the company matches patterns seen in past governance failures.'}
          </p>
        )}
      </div>

      {/* Summary of impact */}
      <div className="gov-ai-summary-bar">
        <div className="gov-ai-summary-item">
          <span className="gov-ai-count" style={{ color: '#F87171' }}>{impactful.filter(f => f.direction === 'risk').length}</span>
          <span className="gov-ai-count-label">Pushing risk UP</span>
        </div>
        <div className="gov-ai-summary-item">
          <span className="gov-ai-count" style={{ color: '#34D399' }}>{impactful.filter(f => f.direction === 'protective').length}</span>
          <span className="gov-ai-count-label">Reducing risk</span>
        </div>
        <div className="gov-ai-summary-item">
          <span className="gov-ai-count" style={{ color: '#94A3B8' }}>{neutral.length}</span>
          <span className="gov-ai-count-label">No impact</span>
        </div>
      </div>

      {/* Impactful factors */}
      {impactful.length > 0 && (
        <div className="gov-ai-group">
          <div className="gov-ai-group-title">Factors That Influenced the Prediction</div>
          {impactful.map((f, i) => (
            <div key={i} className="gov-ai-factor">
              <div className="gov-ai-factor-indicator" style={{
                background: f.direction === 'risk' ? 'rgba(248, 113, 113, 0.15)' : 
                            f.direction === 'protective' ? 'rgba(52, 211, 153, 0.15)' : 'rgba(148, 163, 184, 0.1)',
                borderColor: f.direction === 'risk' ? 'rgba(248, 113, 113, 0.3)' : 
                             f.direction === 'protective' ? 'rgba(52, 211, 153, 0.3)' : 'rgba(148, 163, 184, 0.15)',
              }}>
                <span style={{ color: f.direction === 'risk' ? '#F87171' : f.direction === 'protective' ? '#34D399' : '#94A3B8' }}>
                  {f.direction === 'risk' ? '▲' : f.direction === 'protective' ? '▼' : '—'}
                </span>
              </div>
              <div className="gov-ai-factor-body">
                <div className="gov-ai-factor-name">{f.meta?.name || f.featureName.replace(/_/g, ' ')}</div>
                <div className="gov-ai-factor-explain">{f.meta?.explanation || 'ML model input feature.'}</div>
                <div className="gov-ai-factor-meta">
                  {f.value != null && <span>Value: {typeof f.value === 'number' ? f.value.toFixed(2) : String(f.value)}</span>}
                  <span className="gov-ai-factor-cat">{f.meta?.category || 'General'}</span>
                  <span>Impact: {f.direction === 'risk' ? 'Increases risk' : f.direction === 'protective' ? 'Decreases risk' : 'Neutral'}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Neutral factors (collapsed by default) */}
      {neutral.length > 0 && (
        <div className="gov-ai-group gov-ai-neutral-group">
          <button className="gov-ai-neutral-toggle" onClick={() => setShowAll(!showAll)}>
            <span>{showAll ? 'Hide' : 'Show'} {neutral.length} neutral factors (no impact on prediction)</span>
            <ChevronLeft size={13} className={`gov-ai-chevron ${showAll ? 'gov-ai-chevron-open' : ''}`} />
          </button>
          {showAll && (
            <div className="gov-ai-neutral-list">
              <p className="gov-ai-neutral-explain">
                These factors were analyzed but had <strong>no meaningful impact</strong> on the risk prediction. 
                This could mean: (1) the data point is within normal ranges, (2) the data is not available for this company, 
                or (3) this factor is not relevant for this company's risk profile.
              </p>
              {neutral.map((f, i) => (
                <div key={i} className="gov-ai-factor gov-ai-factor-neutral">
                  <div className="gov-ai-factor-indicator gov-ai-indicator-neutral">
                    <span>—</span>
                  </div>
                  <div className="gov-ai-factor-body">
                    <div className="gov-ai-factor-name">{f.meta?.name || f.featureName.replace(/_/g, ' ')}</div>
                    <div className="gov-ai-factor-explain">{f.meta?.explanation || 'ML model input feature.'}</div>
                    {f.value != null && (
                      <div className="gov-ai-factor-meta">
                        <span>Value: {typeof f.value === 'number' ? f.value.toFixed(2) : String(f.value)}</span>
                        <span className="gov-ai-factor-cat">{f.meta?.category || 'General'}</span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="gov-ai-footer">
        <Info size={12} />
        <span>This transparency report shows which data points the model examined. A "neutral" result means the factor neither increased nor decreased the predicted risk — often because the data was unavailable or within normal ranges.</span>
      </div>
    </div>
  );
};


// ─── Enforcement Timeline ────────────────────────────────────────────────────

const EnforcementTimeline: React.FC<{ signals: GovernanceResult['signals'] }> = ({ signals }) => {
  const actions = signals?.enforcement_actions;
  if (!actions || actions.length === 0) return null;

  const active = actions.filter(a => a.status !== 'reversed');
  const reversed = actions.filter(a => a.status === 'reversed');

  return (
    <div className="gov-section">
      <div className="gov-section-title">
        <Scale size={14} /> Regulatory Penalties & Enforcement
      </div>
      <p className="gov-section-subtitle">
        These are official orders from regulators like SEBI (India's stock market watchdog) against this company.
        Each order means the regulator found a rule violation serious enough to warrant a penalty or restriction.
      </p>

      {active.length > 0 && (
        <div className="gov-enf-group">
          <div className="gov-enf-group-label gov-enf-active">
            Active Orders ({active.length}) — these penalties are currently in force
          </div>
          <div className="gov-enforcement-list">
            {active.map((action, i) => (
              <div key={i} className="gov-enforcement-item">
                <div className="gov-enforcement-dot" style={{ background: '#F87171' }} />
                <div className="gov-enforcement-body">
                  <div className="gov-enforcement-type">{formatViolationType(action.violation_type)}</div>
                  <div className="gov-enforcement-meta">
                    {action.order_date && <span>Date: {action.order_date}</span>}
                    {action.penalty_amount_inr != null && Number(action.penalty_amount_inr) > 0 && (
                      <span className="gov-enf-fine">
                        Fine: ₹{Number(action.penalty_amount_inr).toLocaleString('en-IN')}
                      </span>
                    )}
                    <span className="gov-enforcement-status active">Active</span>
                  </div>
                  {action.pdf_url && (
                    <a href={action.pdf_url} target="_blank" rel="noopener noreferrer" className="gov-enforcement-link">
                      <ExternalLink size={10} /> Read the official order
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {reversed.length > 0 && (
        <div className="gov-enf-group">
          <div className="gov-enf-group-label gov-enf-reversed">
            Overturned Orders ({reversed.length}) — these were successfully appealed or reversed
          </div>
          <div className="gov-enforcement-list">
            {reversed.map((action, i) => (
              <div key={i} className="gov-enforcement-item" style={{ opacity: 0.6 }}>
                <div className="gov-enforcement-dot" style={{ background: '#34D399' }} />
                <div className="gov-enforcement-body">
                  <div className="gov-enforcement-type">{formatViolationType(action.violation_type)}</div>
                  <div className="gov-enforcement-meta">
                    {action.order_date && <span>Date: {action.order_date}</span>}
                    <span className="gov-enforcement-status reversed">Overturned</span>
                  </div>
                  {action.pdf_url && (
                    <a href={action.pdf_url} target="_blank" rel="noopener noreferrer" className="gov-enforcement-link">
                      <ExternalLink size={10} /> View order
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

// ─── Auditor History ─────────────────────────────────────────────────────────

const AuditorHistory: React.FC<{ signals: GovernanceResult['signals'] }> = ({ signals }) => {
  const auditors = signals?.auditors;
  if (!auditors || auditors.length === 0) return null;

  const distinct = new Set(auditors.map((a) => (a.auditor_name || '').toUpperCase().trim()));
  const distinctCount = distinct.size;

  // Format fiscal year: convert raw int like 2023 → "FY 2022–23", or keep as-is if already string
  const formatFY = (fy: string | null): string => {
    if (!fy) return '—';
    const n = Number(fy);
    if (!isNaN(n) && n > 2000 && n < 2100) return `FY ${n - 1}–${String(n).slice(2)}`;
    return String(fy);
  };

  const stabilityLabel =
    distinctCount === 1 ? { text: 'Stable — same auditor throughout', color: '#34D399' } :
    distinctCount === 2 ? { text: 'Minor change — one auditor switch detected', color: '#FBBF24' } :
    { text: `Unstable — ${distinctCount} different firms in ${auditors.length} year(s)`, color: '#F87171' };

  return (
    <div className="gov-section">
      <div className="gov-section-title">
        <FileSearch size={14} /> Statutory Auditor History
      </div>
      <p className="gov-section-subtitle">
        A statutory auditor is an independent accounting firm that checks if the company's financial statements are honest and accurate.
        Frequent auditor changes are a red flag because they may mean auditors refused to approve the accounts.
      </p>

      <div className="gov-auditor-stability" style={{ color: stabilityLabel.color, borderColor: stabilityLabel.color }}>
        {distinctCount === 1 ? <CheckCircle2 size={14} /> : distinctCount === 2 ? <AlertCircle size={14} /> : <AlertTriangle size={14} />}
        <span>{stabilityLabel.text}</span>
      </div>

      <div className="gov-auditor-list">
        {auditors.map((aud, i) => {
          const isChange = i > 0 && (aud.auditor_name || '').toUpperCase().trim() !== (auditors[i - 1].auditor_name || '').toUpperCase().trim();
          return (
            <div key={i} className={`gov-auditor-item ${isChange ? 'gov-auditor-changed' : ''}`}>
              <span className="gov-auditor-fy">{formatFY(aud.fiscal_year)}</span>
              <span className="gov-auditor-name">{aud.auditor_name || 'Unknown'}</span>
              {isChange && <span className="gov-auditor-change-badge">Changed</span>}
              {aud.source_url && (
                <a href={aud.source_url} target="_blank" rel="noopener noreferrer" className="gov-prov-link">
                  <ExternalLink size={10} />
                </a>
              )}
            </div>
          );
        })}
      </div>

      {distinctCount >= 3 && (
        <div className="gov-auditor-note" style={{ borderLeftColor: '#F87171', background: 'rgba(248,113,113,0.06)' }}>
          <AlertTriangle size={12} style={{ color: '#F87171' }} />
          <span>
            {distinctCount} different audit firms across {auditors.length} year(s) is a significant red flag.
            Research on Indian listed companies shows that frequent auditor changes are strongly correlated with subsequent financial irregularities.
          </span>
        </div>
      )}
    </div>
  );
};

// ─── Board Composition ───────────────────────────────────────────────────────

const BoardComposition: React.FC<{ signals: GovernanceResult['signals'] }> = ({ signals }) => {
  const board = signals?.board;
  if (!board || board.total === 0) return null;

  const churnPct = board.total > 0 ? ((board.recent_cessations / board.total) * 100) : 0;

  return (
    <div className="gov-section gov-board-composition">
      <div className="gov-section-title">
        <Users size={14} /> Board Stability
      </div>
      <p className="gov-section-subtitle">How stable is the company's leadership team? High turnover can signal trouble.</p>
      <div className="gov-board-stats">
        <div className="gov-board-stat">
          <span className="gov-board-stat-value">{board.total}</span>
          <span className="gov-board-stat-label">Total Directors</span>
        </div>
        <div className="gov-board-stat">
          <span className="gov-board-stat-value" style={{ color: board.recent_cessations > 0 ? '#FBBF24' : '#34D399' }}>
            {board.recent_cessations}
          </span>
          <span className="gov-board-stat-label">Left in Past Year</span>
        </div>
        <div className="gov-board-stat">
          <span className="gov-board-stat-value" style={{ color: churnPct >= 25 ? '#F87171' : churnPct > 0 ? '#FBBF24' : '#34D399' }}>
            {churnPct.toFixed(0)}%
          </span>
          <span className="gov-board-stat-label">Turnover Rate</span>
        </div>
      </div>
      {churnPct >= 25 && (
        <div className="gov-board-warning">
          <AlertTriangle size={13} /> High turnover — more than 1 in 4 directors have left recently. This often precedes problems.
        </div>
      )}
    </div>
  );
};

// ─── Glossary Section ────────────────────────────────────────────────────────

const GlossarySection: React.FC = () => {
  const [open, setOpen] = useState(false);

  return (
    <div className="gov-section gov-glossary">
      <button className="gov-glossary-toggle" onClick={() => setOpen(!open)}>
        <HelpCircle size={14} />
        <span>{open ? 'Hide' : 'Show'} Glossary — Key Terms Explained</span>
        <ChevronLeft size={14} className={`gov-glossary-chevron ${open ? 'gov-glossary-open' : ''}`} />
      </button>
      {open && (
        <div className="gov-glossary-grid">
          {GLOSSARY.map((item) => (
            <div key={item.term} className="gov-glossary-item">
              <span className="gov-glossary-term">{item.term}</span>
              <span className="gov-glossary-def">{item.definition}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════════
// ── Main Scorecard Component ─────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════════

interface GovernanceScorecardProps {
  cin: string;
  fallbackName?: string;
  onBack: () => void;
}

const GovernanceScorecard: React.FC<GovernanceScorecardProps> = ({ cin, fallbackName, onBack }) => {
  const [data, setData] = useState<GovernanceResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [health, setHealth] = useState<CompanyHealth | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);

  const [provenance, setProvenance] = useState<CompanyProvenance | null>(null);
  const [provLoading, setProvLoading] = useState(true);

  const [network, setNetwork] = useState<CompanyNetwork | null>(null);
  const [netLoading, setNetLoading] = useState(true);

  // Fetch main governance data with detail
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    getCompanyGovernance(cin, true)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e?.message || 'Failed to load governance detail'))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [cin]);

  // Fetch auxiliary data in parallel
  useEffect(() => {
    let alive = true;
    setHealthLoading(true);
    getCompanyHealth(cin)
      .then((d) => alive && setHealth(d))
      .catch(() => alive && setHealth(null))
      .finally(() => alive && setHealthLoading(false));
    return () => { alive = false; };
  }, [cin]);

  useEffect(() => {
    let alive = true;
    setProvLoading(true);
    getCompanyProvenance(cin)
      .then((d) => alive && setProvenance(d))
      .catch(() => alive && setProvenance(null))
      .finally(() => alive && setProvLoading(false));
    return () => { alive = false; };
  }, [cin]);

  useEffect(() => {
    let alive = true;
    setNetLoading(true);
    getCompanyNetwork(cin)
      .then((d) => alive && setNetwork(d))
      .catch(() => alive && setNetwork(null))
      .finally(() => alive && setNetLoading(false));
    return () => { alive = false; };
  }, [cin]);

  const igs = data?.igs || null;
  const insufficient = !!igs?.insufficient_data;
  const band = (igs?.band || data?.band || null) as Band | null;
  const composite = igs?.composite_score ?? data?.score ?? null;

  return (
    <div className="gov-scorecard gov-scorecard-detail">
      <button className="gov-back" onClick={onBack}>
        <ChevronLeft size={16} /> Back to list
      </button>

      {/* Header */}
      <div className="gov-card-head">
        <div className="gov-card-title">
          <Building2 size={18} />
          <div>
            <div className="gov-co-name">{fallbackName || cin}</div>
            <div className="gov-co-cin">{cin}</div>
          </div>
        </div>
        <BandChip band={band} />
      </div>

      {loading && <div className="gov-empty">Analyzing governance data...</div>}
      {error && (
        <div className="gov-notice gov-notice-warn">
          <AlertTriangle size={15} /> {error}
        </div>
      )}

      {!loading && !error && data && band && (
        <>
          {insufficient && (
            <div className="gov-notice">
              <Info size={15} />
              <span>
                <strong>Limited data available</strong> — Not enough governance data to run our AI model. Assessment below uses rule-based analysis only.
              </span>
            </div>
          )}

          {/* Verdict Card — The "So What?" */}
          <VerdictCard data={data} band={band} />

          {/* Visual Score Gauge */}
          {composite != null && <ScoreGauge score={composite} band={band} />}

          {/* Metric Cards with plain subtitles */}
          <MetricCards data={data} composite={composite} band={band} />

          {/* Charts Row: Trend + Radar */}
          <div className="gov-charts-row">
            <PledgeTrendChart signals={data.signals} />
            <RiskRadarChart subscores={data.subscores} />
          </div>

          {/* Risk Dimensions with analogies */}
          <RiskDimensionDetail subscores={data.subscores} coverage={data.coverage} />

          {/* Signals Detail */}
          {data.signals && (
            <div className="gov-signals-detail-row">
              <EnforcementTimeline signals={data.signals} />
              <AuditorHistory signals={data.signals} />
              <BoardComposition signals={data.signals} />
            </div>
          )}

          {/* Flagged Signals (high + watch only) */}
          <FlaggedSignals flags={data.flags} />

          {/* AI Model Factors (info flags transformed) */}
          <AIModelFactors flags={data.flags} probability={igs?.model_probability ?? null} />

          {/* Data Health */}
          <DataHealthSection health={health} loading={healthLoading} />

          {/* Provenance */}
          <ProvenanceSection provenance={provenance} loading={provLoading} />

          {/* Network */}
          <NetworkSection network={network} loading={netLoading} />

          {/* Glossary */}
          <GlossarySection />

          {/* Footer */}
          <div className="gov-foot">
            {igs?.model_version ? `Model ${igs.model_version}` : 'Rules engine'}
            {igs?.as_of_date ? ` · as of ${igs.as_of_date}` : ''}
            {data.computed_at ? ` · computed ${new Date(data.computed_at).toLocaleDateString('en-IN')}` : ''}
            {' · '}All data sourced from official regulatory filings
          </div>
        </>
      )}
    </div>
  );
};

export default GovernanceScorecard;

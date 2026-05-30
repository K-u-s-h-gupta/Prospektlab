import React from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Brain, MessageSquare, Activity, TrendingUp, FileText, 
  Shield, BarChart3, Zap, Search, PieChart, 
  ArrowRight, CheckCircle, AlertTriangle, Globe, Clock
} from 'lucide-react';

interface Feature {
  icon: React.ElementType;
  title: string;
  subtitle: string;
  description: string;
  bullets: string[];
  metric: string;
  metricLabel: string;
}

const FEATURES: Feature[] = [
  {
    icon: MessageSquare,
    title: "Ask Anything. Get Answers in 8 Seconds.",
    subtitle: "Natural language → Institutional analysis",
    description: "Type in plain English. No jargon required. Arthik understands context, follows up, and synthesizes data across multiple sources into a single, readable response with cited numbers.",
    bullets: [
      "Is Reliance's debt ratio a long-term risk?",
      "Compare TCS vs Infosys on operating margins and capital efficiency",
      "Should I average down on Zomato or cut the loss?",
      "What is the intrinsic value of HDFC Bank using a 10% discount rate?"
    ],
    metric: "8.2s",
    metricLabel: "Average response time"
  },
  {
    icon: Activity,
    title: "Live Market Pulse. Not Yesterday's News.",
    subtitle: "Real-time NSE + global feeds",
    description: "Your dashboard tracks Nifty, Sensex, Bank Nifty, currencies, crypto, and commodities in real-time. But unlike a screener, Arthik interprets the moves and tells you what actually matters for your holdings.",
    bullets: [
      "Live NSE, BSE, and US market tickers with sparklines",
      "AI-generated market summaries from 4+ sources",
      "Anomaly detection on volume and price spikes",
      "Correlation alerts when your portfolio moves together"
    ],
    metric: "265ms",
    metricLabel: "Data refresh latency"
  },
  {
    icon: TrendingUp,
    title: "Transparent Valuation Models. Not Black Boxes.",
    subtitle: "DCF, Graham, Altman Z, Piotroski",
    description: "Every model shows its work. Change the growth rate. Adjust the terminal value. See the fair value update in real-time. This is how institutions value companies, and now you have the same engine.",
    bullets: [
      "Full two-stage DCF with editable WACC and growth assumptions",
      "Graham intrinsic value based on EPS, book value, and growth",
      "Altman Z-Score for bankruptcy risk detection",
      "Piotroski F-Score for financial health grading"
    ],
    metric: "4",
    metricLabel: "Valuation models included"
  },
  {
    icon: FileText,
    title: "Deep Research Memos. In Minutes, Not Days.",
    subtitle: "8-phase research loops",
    description: "Trigger an 8-phase deep research loop that reads annual filings, compares peer statement structures, checks news sentiment anomalies, and writes a full analyst-grade memo. What used to take a research associate 2 days, Arthik does in 90 seconds.",
    bullets: [
      "Automated annual report parsing and key metric extraction",
      "Peer benchmarking across up to 6 competitors",
      "News sentiment anomaly detection and source credibility scoring",
      "Export-ready memo with charts, tables, and source citations"
    ],
    metric: "90s",
    metricLabel: "Deep memo generation time"
  },
  {
    icon: Shield,
    title: "Portfolio Risk Audit. Know Your Blind Spots.",
    subtitle: "Concentration, correlation, beta",
    description: "Upload your trade statement. Arthik cross-checks sector concentration, correlation heatmaps, portfolio beta, and hidden leverage. It will warn you when 60% of your wealth is silently exposed to one macro factor.",
    bullets: [
      "Sector concentration and overlap detection",
      "Portfolio beta vs Nifty correlation analysis",
      "Hidden leverage and promoter pledge monitoring",
      "Rebalancing suggestions with risk-adjusted rationale"
    ],
    metric: "6",
    metricLabel: "Risk dimensions analyzed"
  },
  {
    icon: BarChart3,
    title: "Earnings Edge. Position Before the Move.",
    subtitle: "Pre-result intelligence",
    description: "Most retail investors get blindsided by earnings gaps. Arthik tracks upcoming result dates, whisper expectations, historical beat/miss rates, and options flow to help you position — or protect — before the announcement.",
    bullets: [
      "Earnings calendar synced to your watchlist",
      "Historical beat/miss rate per company",
      "Whisper expectation vs consensus gap analysis",
      "Pre-result positioning guide with scenario probabilities"
    ],
    metric: "5-day",
    metricLabel: "Advance positioning window"
  },
];

const COMPARISONS = [
  { feature: "Real-time NSE data", prospekt: true, brokers: false, screeners: true, chatgpt: false },
  { feature: "Transparent DCF models (editable)", prospekt: true, brokers: false, screeners: false, chatgpt: false },
  { feature: "Zero conflict of interest", prospekt: true, brokers: false, screeners: true, chatgpt: true },
  { feature: "Portfolio risk audit + beta", prospekt: true, brokers: false, screeners: false, chatgpt: false },
  { feature: "Deep research memos (8-phase)", prospekt: true, brokers: true, screeners: false, chatgpt: false },
  { feature: "Earnings pre-positioning", prospekt: true, brokers: false, screeners: false, chatgpt: false },
  { feature: "Cited, verifiable numbers", prospekt: true, brokers: false, screeners: true, chatgpt: false },
  { feature: "Price", prospekt: "Free / Rs 499/mo", brokers: "Rs 18K+/yr", screeners: "Free / Rs 5K/yr", chatgpt: "Rs 1,650/mo" },
];

export const Features: React.FC = () => {
  const navigate = useNavigate();

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-deep)', overflowY: 'auto' }}>
      <nav style={{ position: 'sticky', top: 0, zIndex: 50, background: 'rgba(3,7,18,0.9)', backdropFilter: 'blur(16px)', borderBottom: '1px solid var(--border-subtle)' }}>
        <div style={{ maxWidth: 1200, margin: '0 auto', padding: '14px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }} onClick={() => navigate('/')}>
            <div style={{ background: 'var(--gradient-brand)', borderRadius: 8, padding: 6, display: 'flex' }}>
              <Brain size={18} color="#0f172a" />
            </div>
            <span style={{ fontWeight: 700, fontSize: 18, letterSpacing: '-0.5px' }} className="text-gradient">ProspektLab</span>
          </div>
          <button onClick={() => navigate('/')} style={{ background: 'none', border: '1px solid var(--border-subtle)', color: 'var(--text-primary)', padding: '8px 16px', borderRadius: 8, fontSize: 13, cursor: 'pointer' }}>
            Back to Home
          </button>
        </div>
      </nav>

      <style>{`
        @media (max-width: 768px) {
          .feature-grid { grid-template-columns: 1fr !important; }
          .comparison-table { font-size: 11px !important; }
          .comparison-table th, .comparison-table td { padding: 6px 8px !important; }
        }
        @media (max-width: 600px) {
          .comparison-table th:nth-child(4),
          .comparison-table td:nth-child(4),
          .comparison-table th:nth-child(5),
          .comparison-table td:nth-child(5) { display: none !important; }
          .comparison-table th, .comparison-table td { font-size: 10px !important; padding: 5px 6px !important; }
        }
        @media (max-width: 480px) {
          .agent-grid { grid-template-columns: 1fr !important; }
          .feature-grid { gap: 24px !important; }
        }
      `}</style>

      {/* Hero */}
      <section style={{ padding: '80px 24px 40px', textAlign: 'center' }}>
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'rgba(56,189,248,0.08)', border: '1px solid rgba(56,189,248,0.15)', color: 'var(--accent-cyan)', padding: '6px 14px', borderRadius: 999, fontSize: 12, fontWeight: 600, marginBottom: 20 }}>
            <Zap size={14} /> Built for Serious Indian Investors
          </div>
          <h1 style={{ fontSize: 'clamp(32px, 4vw, 48px)', fontWeight: 800, lineHeight: 1.1, marginBottom: 16 }}>
            The <span style={{ background: 'var(--gradient-brand)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>8-Agent Intelligence Stack</span><br />
            That Institutions Pay Lakhs For
          </h1>
          <p style={{ fontSize: 17, color: 'var(--text-secondary)', lineHeight: 1.65, maxWidth: 620, margin: '0 auto 32px' }}>
            Arthik is not one chatbot. It is a coordinator of 8 specialist AI agents, each trained on a specific domain of financial analysis. Intent routing, market data, fundamentals, valuation, risk, news research, earnings, and portfolio audit. Working together, in parallel, in seconds.
          </p>
          <button onClick={() => navigate('/onboarding')} style={{ background: 'var(--gradient-brand)', color: '#0f172a', border: 'none', padding: '16px 32px', borderRadius: 12, fontSize: 16, fontWeight: 700, cursor: 'pointer', boxShadow: '0 0 24px rgba(56,189,248,0.15)' }}>
            Try It Free <ArrowRight size={18} style={{ display: 'inline', verticalAlign: 'middle', marginLeft: 6 }} />
          </button>
        </div>
      </section>

      {/* Agent Grid */}
      <section style={{ padding: '40px 24px 60px' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginBottom: 48 }} className="agent-grid">
            {[
              { icon: Search, name: "Intent Router", desc: "Classifies your query and routes to correct agents" },
              { icon: Globe, name: "Market Data", desc: "Fetches live NSE, BSE, US, and currency feeds" },
              { icon: BarChart3, name: "Fundamentals", desc: "Parses balance sheets, income statements, ratios" },
              { icon: TrendingUp, name: "Valuation", desc: "Runs DCF, Graham, WACC with editable assumptions" },
              { icon: Shield, name: "Risk Audit", desc: "Altman Z, Piotroski, leverage, and concentration" },
              { icon: FileText, name: "News Research", desc: "Scans filings, press, and sentiment anomalies" },
              { icon: Clock, name: "Earnings", desc: "Pre-result positioning and historical pattern analysis" },
              { icon: PieChart, name: "Portfolio", desc: "Beta, correlation, rebalancing, and overlap detection" },
            ].map((agent, i) => (
              <div key={i} style={{ background: 'rgba(15,23,42,0.4)', border: '1px solid var(--border-subtle)', borderRadius: 12, padding: 20, display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                <div style={{ width: 36, height: 36, borderRadius: 10, background: 'rgba(56,189,248,0.08)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <agent.icon size={18} color="var(--accent-cyan)" />
                </div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>{agent.name}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.4 }}>{agent.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Feature Cards */}
      <section style={{ padding: '0 24px 60px' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 48 }}>
          {FEATURES.map((feature, i) => (
            <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 40, alignItems: 'center' }} className="feature-grid">
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16, order: i % 2 === 1 ? 2 : 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{ width: 44, height: 44, borderRadius: 12, background: 'rgba(56,189,248,0.08)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <feature.icon size={22} color="var(--accent-cyan)" />
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--accent-cyan)', fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase' }}>{feature.subtitle}</div>
                </div>
                <h2 style={{ fontSize: 'clamp(22px, 2.5vw, 28px)', fontWeight: 700, lineHeight: 1.2 }}>{feature.title}</h2>
                <p style={{ fontSize: 15, color: 'var(--text-secondary)', lineHeight: 1.65 }}>{feature.description}</p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {feature.bullets.map((b, bi) => (
                    <div key={bi} style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                      <div style={{ width: 18, height: 18, borderRadius: '50%', background: 'rgba(52,211,153,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, marginTop: 2 }}>
                        <CheckCircle size={12} color="var(--profit)" />
                      </div>
                      <span style={{ fontSize: 14, color: 'var(--text-primary)' }}>{b}</span>
                    </div>
                  ))}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
                  <div style={{ background: 'rgba(15,23,42,0.6)', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: '10px 16px' }}>
                    <div style={{ fontSize: 22, fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)' }}>{feature.metric}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{feature.metricLabel}</div>
                  </div>
                </div>
              </div>
              <div style={{ background: 'rgba(15,23,42,0.4)', border: '1px solid var(--border-subtle)', borderRadius: 16, padding: 28, minHeight: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', order: i % 2 === 1 ? 1 : 2 }}>
                <div style={{ textAlign: 'center' }}>
                  <feature.icon size={48} color="var(--text-muted)" strokeWidth={1} />
                  <div style={{ marginTop: 16, fontSize: 13, color: 'var(--text-muted)' }}>Interactive demo available after signup</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Comparison Table */}
      <section style={{ padding: '0 24px 80px' }}>
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          <h2 style={{ fontSize: 'clamp(24px, 3vw, 32px)', fontWeight: 700, textAlign: 'center', marginBottom: 40 }}>
            How We <span style={{ background: 'var(--gradient-brand)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>Compare</span>
          </h2>
          <div style={{ background: 'rgba(15,23,42,0.4)', border: '1px solid var(--border-subtle)', borderRadius: 16, overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }} className="comparison-table">
              <thead>
                <tr style={{ background: 'rgba(255,255,255,0.02)', borderBottom: '1px solid var(--border-subtle)' }}>
                  <th style={{ padding: '16px 20px', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)', fontSize: 12, letterSpacing: '0.04em', textTransform: 'uppercase' }}>Feature</th>
                  <th style={{ padding: '16px 20px', textAlign: 'center', fontWeight: 700, color: 'var(--accent-cyan)', fontSize: 13, background: 'rgba(56,189,248,0.04)' }}>ProspektLab</th>
                  <th style={{ padding: '16px 20px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', fontSize: 13 }}>Broker Research</th>
                  <th style={{ padding: '16px 20px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', fontSize: 13 }}>Screeners</th>
                  <th style={{ padding: '16px 20px', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', fontSize: 13 }}>Generic AI</th>
                </tr>
              </thead>
              <tbody>
                {COMPARISONS.map((row, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                    <td style={{ padding: '14px 20px', fontWeight: 500, color: 'var(--text-primary)' }}>{row.feature}</td>
                    <td style={{ padding: '14px 20px', textAlign: 'center', fontWeight: 700, color: typeof row.prospekt === 'string' ? 'var(--text-primary)' : 'var(--profit)', background: 'rgba(56,189,248,0.02)' }}>
                      {typeof row.prospekt === 'boolean' ? (row.prospekt ? <CheckCircle size={16} color="var(--profit)" /> : <AlertTriangle size={16} color="var(--loss)" />) : row.prospekt}
                    </td>
                    <td style={{ padding: '14px 20px', textAlign: 'center', color: typeof row.brokers === 'string' ? 'var(--text-secondary)' : 'var(--text-muted)' }}>
                      {typeof row.brokers === 'boolean' ? (row.brokers ? <CheckCircle size={16} color="var(--profit)" /> : <span style={{ fontSize: 12 }}>No</span>) : row.brokers}
                    </td>
                    <td style={{ padding: '14px 20px', textAlign: 'center', color: typeof row.screeners === 'string' ? 'var(--text-secondary)' : 'var(--text-muted)' }}>
                      {typeof row.screeners === 'boolean' ? (row.screeners ? <CheckCircle size={16} color="var(--profit)" /> : <span style={{ fontSize: 12 }}>No</span>) : row.screeners}
                    </td>
                    <td style={{ padding: '14px 20px', textAlign: 'center', color: typeof row.chatgpt === 'string' ? 'var(--text-secondary)' : 'var(--text-muted)' }}>
                      {typeof row.chatgpt === 'boolean' ? (row.chatgpt ? <CheckCircle size={16} color="var(--profit)" /> : <span style={{ fontSize: 12 }}>No</span>) : row.chatgpt}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section style={{ padding: '0 24px 80px' }}>
        <div style={{ maxWidth: 720, margin: '0 auto', textAlign: 'center' }}>
          <h2 style={{ fontSize: 24, fontWeight: 700, marginBottom: 16 }}>See It In Action</h2>
          <p style={{ fontSize: 15, color: 'var(--text-secondary)', marginBottom: 24 }}>One question. Eight agents. One clear answer. Start free in 30 seconds.</p>
          <button onClick={() => navigate('/onboarding')} style={{ background: 'var(--gradient-brand)', color: '#0f172a', border: 'none', padding: '16px 32px', borderRadius: 12, fontSize: 16, fontWeight: 700, cursor: 'pointer', boxShadow: '0 0 24px rgba(56,189,248,0.15)' }}>
            Start Free Analysis <ArrowRight size={18} style={{ display: 'inline', verticalAlign: 'middle', marginLeft: 6 }} />
          </button>
        </div>
      </section>

      <footer style={{ borderTop: '1px solid var(--border-subtle)', padding: '40px 24px', background: 'rgba(3,7,18,0.6)' }}>
        <div style={{ maxWidth: 1200, margin: '0 auto', textAlign: 'center' }}>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', maxWidth: 640, margin: '0 auto', lineHeight: 1.6 }}>
            Disclaimer: ProspektLab is an informational AI intelligence platform. Not SEBI-registered investment advice. Please consult a professional financial advisor before making any investment decisions.
          </p>
          <p style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 12 }}>2026 ProspektLab. All rights reserved. Made in India.</p>
        </div>
      </footer>
    </div>
  );
};

export default Features;

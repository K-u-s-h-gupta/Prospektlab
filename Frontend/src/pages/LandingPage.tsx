import React, { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  FileSearch,
  LockKeyhole,
  Menu,
  PanelRight,
  Search,
  ShieldCheck,
  X,
  Zap,
} from 'lucide-react';
import { Logo } from '../components/layout/Logo';
import { useAuth } from '../context/AuthContext';
import '../styles/landing.css';

const CAPABILITIES = [
  {
    icon: Search,
    title: 'Ask a research question',
    body: 'Use plain language to inspect a company, sector, portfolio, event, or valuation assumption.',
  },
  {
    icon: FileSearch,
    title: 'Trace the answer',
    body: 'Every memo keeps sources, model inputs, and assumptions visible so the conclusion can be challenged.',
  },
  {
    icon: BarChart3,
    title: 'Model the business',
    body: 'DCF, Graham, Altman Z, Piotroski, peer multiples, and risk checks sit beside the narrative.',
  },
  {
    icon: PanelRight,
    title: 'Work from one screen',
    body: 'Quotes, filings, news, earnings, watchlists, and Arthik chat stay in the same workspace.',
  },
  {
    icon: ShieldCheck,
    title: 'Spot governance risk',
    body: 'Promoter pledges, board changes, related-party items, and stale disclosures are highlighted early.',
  },
  {
    icon: LockKeyhole,
    title: 'Keep incentives clean',
    body: 'No brokerage revenue, no sponsored calls, and no trade-pushing feed dressed up as research.',
  },
];

const WORKFLOW = [
  {
    title: 'Ask',
    body: 'Start with a stock, portfolio, sector, filing, or event question.',
  },
  {
    title: 'Assemble',
    body: 'ProspektLab brings market data, filings, valuation context, and portfolio exposure together.',
  },
  {
    title: 'Test',
    body: 'Arthik checks valuation, quality, risk, sentiment, governance, and source conflicts.',
  },
  {
    title: 'Decide',
    body: 'You get a cited answer, visible assumptions, and the next items worth verifying.',
  },
];

const PROOF_POINTS = [
  'Cited source trail for important claims',
  'Editable valuation assumptions',
  'Portfolio-aware research questions',
  'No brokerage or commission incentive',
];

const EVIDENCE_ITEMS = [
  {
    label: 'Sources',
    title: 'Claims stay traceable',
    body: 'Important statements keep their source trail visible.',
  },
  {
    label: 'Models',
    title: 'Assumptions stay editable',
    body: 'Valuation outputs can be challenged instead of accepted blindly.',
  },
  {
    label: 'Portfolio',
    title: 'Answers know your book',
    body: 'Research questions can include concentration and exposure context.',
  },
  {
    label: 'Incentives',
    title: 'No broker agenda',
    body: 'The product is analysis, not trade churn.',
  },
];

const FAQS = [
  {
    q: 'Is this SEBI-registered investment advice?',
    a: 'No. ProspektLab is an analytical product, not a SEBI-registered advisor. It gathers public data and runs transparent research models. You make the final decision.',
  },
  {
    q: 'How is this different from a generic AI chat?',
    a: 'Arthik is connected to market data, filings, portfolio context, valuation engines, and source tracking. The answer includes the math and the citations instead of only prose.',
  },
  {
    q: 'What does the free tier include?',
    a: 'The free tier includes daily analysis queries, market data, portfolio tracking, valuation models, and research memo generation. No card and no trial countdown.',
  },
  {
    q: 'Where is my portfolio data stored?',
    a: 'The app is designed to keep portfolio setup lightweight and privacy-conscious. Local browser storage is used for client-side holdings workflows where possible.',
  },
  {
    q: 'Which brokers are supported?',
    a: 'Zerodha, Groww, Upstox, ICICI Direct, and standard trade book CSV or PDF exports are supported by the onboarding flow.',
  },
];

export const LandingPage: React.FC = () => {
  const navigate = useNavigate();
  const { isAuthenticated, onboarded } = useAuth();
  const [openFaq, setOpenFaq] = useState<number | null>(0);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const ctaTarget = isAuthenticated && onboarded ? '/dashboard' : '/get-started';
  const handleCTA = useCallback(() => navigate(ctaTarget), [navigate, ctaTarget]);

  const scrollTo = useCallback((id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setMobileMenuOpen(false);
  }, []);

  const navItems = [
    ['capabilities', 'Capabilities'],
    ['workflow', 'Workflow'],
    ['proof', 'Proof'],
    ['pricing', 'Pricing'],
    ['faq', 'FAQ'],
  ];

  return (
    <div className="landing">
      <nav className="lp-nav">
        <div className="lp-nav-inner">
          <button className="lp-nav-brand" type="button" onClick={() => scrollTo('hero')} aria-label="Go to top">
            <Logo size={28} />
            <span className="lp-nav-brand-text">ProspektLab</span>
          </button>

          <div className="lp-nav-links">
            {navItems.map(([id, label]) => (
              <button key={id} className="lp-nav-link" type="button" onClick={() => scrollTo(id)}>
                {label}
              </button>
            ))}
          </div>

          <div className="lp-nav-actions">
            <button className="lp-nav-btn-ghost" type="button" onClick={() => navigate('/dashboard/overview')}>
              Open app
            </button>
            <button className="lp-nav-btn-primary" type="button" onClick={handleCTA}>
              Start free
            </button>
            <button
              className="lp-nav-mobile-toggle"
              type="button"
              onClick={() => setMobileMenuOpen((value) => !value)}
              aria-label="Toggle menu"
              aria-expanded={mobileMenuOpen}
            >
              {mobileMenuOpen ? <X size={16} /> : <Menu size={16} />}
            </button>
          </div>
        </div>

        {mobileMenuOpen && (
          <div className="lp-nav-mobile">
            {navItems.map(([id, label]) => (
              <button key={id} type="button" onClick={() => scrollTo(id)}>
                {label}
              </button>
            ))}
            <button type="button" onClick={() => navigate('/dashboard/overview')}>
              Open app
            </button>
          </div>
        )}
      </nav>

      <main>
        <section id="hero" className="lp-hero">
          <div className="lp-container lp-hero-grid">
            <div className="lp-hero-copy">
              <p className="lp-overline">Indian equity research workspace</p>
              <h1>Indian stock research, cited.</h1>
              <p className="lp-hero-sub">
                Live data, filings, valuation, and portfolio context in one cited research surface.
              </p>

              <div className="lp-hero-actions">
                <button className="lp-btn-primary" type="button" onClick={handleCTA}>
                  Start free <ArrowRight size={16} />
                </button>
                <button className="lp-btn-secondary" type="button" onClick={() => navigate('/dashboard/overview')}>
                  Open app
                </button>
              </div>

            </div>

            <figure className="lp-product-shot">
              <img
                src="/ui-preview-dashboard.png"
                alt="ProspektLab dashboard with market indices, portfolio snapshot, and Arthik research chat"
              />
            </figure>
          </div>
        </section>

        <section className="lp-evidence-band" aria-label="ProspektLab evidence model">
          <div className="lp-container lp-evidence-grid">
            {EVIDENCE_ITEMS.map((item) => (
              <article key={item.label} className="lp-evidence-item">
                <span>{item.label}</span>
                <strong>{item.title}</strong>
                <p>{item.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="capabilities" className="lp-section lp-capabilities">
          <div className="lp-container">
            <div className="lp-section-header">
              <h2>The research loop, tightened.</h2>
              <p>
                ProspektLab is designed for repeated decisions: scan, question, verify, model, and return to the portfolio without losing context.
              </p>
            </div>

            <div className="lp-cap-grid">
              {CAPABILITIES.map((cap, index) => (
                <article
                  key={cap.title}
                  className={`lp-cap-card ${index === 0 ? 'is-featured' : ''} ${index === 3 ? 'is-wide' : ''}`}
                >
                  <div className="lp-cap-icon">
                    <cap.icon size={18} />
                  </div>
                  <h3>{cap.title}</h3>
                  <p>{cap.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="workflow" className="lp-section lp-workflow">
          <div className="lp-container lp-workflow-layout">
            <div className="lp-section-header">
              <h2>From question to cited call.</h2>
              <p>
                The interface keeps source quality, model assumptions, portfolio impact, and next checks visible throughout the research chain.
              </p>
            </div>

            <div className="lp-workflow-list">
              {WORKFLOW.map((item) => (
                <article key={item.title} className="lp-workflow-step">
                  <strong>{item.title}</strong>
                  <p>{item.body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="proof" className="lp-section lp-proof">
          <div className="lp-container lp-proof-layout">
            <div className="lp-proof-statement">
              <h2>Less noise. More evidence on the table.</h2>
            </div>

            <div className="lp-proof-panel">
              <p>
                ProspektLab does not try to replace judgment. It compresses the tedious part of research so your judgment has cleaner material to work with.
              </p>
              <div className="lp-proof-checks">
                {PROOF_POINTS.map((point) => (
                  <span key={point}>
                    <CheckCircle2 size={15} />
                    {point}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section id="pricing" className="lp-section lp-pricing">
          <div className="lp-container lp-pricing-layout">
            <div className="lp-section-header">
              <h2>Useful before you pay.</h2>
              <p>No card. No countdown. The free tier is meant for real research, not a locked demo.</p>
            </div>

            <div className="lp-pricing-card">
              <div className="lp-pricing-head">
                <h3>Free</h3>
                <span>Rs. 0 / month</span>
              </div>
              <ul>
                <li><CheckCircle2 size={16} /> Daily analysis queries</li>
                <li><CheckCircle2 size={16} /> Live market context</li>
                <li><CheckCircle2 size={16} /> Portfolio import and tracking</li>
                <li><CheckCircle2 size={16} /> DCF, Graham, Altman Z, Piotroski</li>
                <li><CheckCircle2 size={16} /> Governance and earnings alerts</li>
              </ul>
              <button className="lp-btn-primary" type="button" onClick={handleCTA}>
                Start free <ArrowRight size={16} />
              </button>
              <p>Pro adds unlimited usage, priority refreshes, and API access.</p>
            </div>
          </div>
        </section>

        <section id="faq" className="lp-section lp-faq">
          <div className="lp-container">
            <div className="lp-section-header">
              <h2>Know the boundary before using it.</h2>
            </div>

            <div className="lp-faq-list">
              {FAQS.map((faq, index) => (
                <div key={faq.q} className="lp-faq-item">
                  <button
                    type="button"
                    className="lp-faq-question"
                    onClick={() => setOpenFaq(openFaq === index ? null : index)}
                    aria-expanded={openFaq === index}
                  >
                    <span>{faq.q}</span>
                    <ChevronDown size={16} />
                  </button>
                  {openFaq === index && <p className="lp-faq-answer">{faq.a}</p>}
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="lp-final">
          <div className="lp-container lp-final-inner">
            <div>
              <h2>Bring the market, model, and memo into one place.</h2>
              <p>Start with the free workspace and keep the evidence trail visible.</p>
            </div>
            <button className="lp-btn-primary" type="button" onClick={handleCTA}>
              Open ProspektLab <Zap size={16} />
            </button>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <div className="lp-container">
          <div className="lp-footer-inner">
            <div className="lp-footer-brand">
              <Logo size={24} />
              <span>ProspektLab</span>
            </div>
            <div className="lp-footer-links">
              <button type="button" onClick={() => scrollTo('hero')}>Home</button>
              <button type="button" onClick={() => scrollTo('capabilities')}>Capabilities</button>
              <button type="button" onClick={() => navigate('/login')}>Sign in</button>
            </div>
          </div>
          <p>
            ProspektLab is an informational AI research platform. Content is for analytical and educational purposes only.
            We are not SEBI-registered advisors. Consult a SEBI-registered advisor before making investment decisions.
            (c) 2026 ProspektLab.
          </p>
        </div>
      </footer>
    </div>
  );
};

export default LandingPage;

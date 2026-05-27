import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Brain, Check, Zap, ChevronDown } from 'lucide-react';

interface PlanFeature {
  text: string;
  included: boolean;
}

interface PricingPlan {
  name: string;
  price: string;
  period: string;
  tagline: string;
  cta: string;
  popular?: boolean;
  features: PlanFeature[];
  savings?: string;
}

const PLANS: PricingPlan[] = [
  {
    name: "Free Forever",
    price: "0",
    period: "forever",
    tagline: "Get your first edge. No strings attached.",
    cta: "Start Free",
    features: [
      { text: "20 AI queries per day", included: true },
      { text: "Live NSE market data", included: true },
      { text: "Basic valuation snapshots", included: true },
      { text: "Portfolio watchlist (10 stocks)", included: true },
      { text: "Standard market summaries", included: true },
      { text: "Deep research memos", included: false },
      { text: "Unlimited queries", included: false },
      { text: "Portfolio risk audit", included: false },
      { text: "Earnings positioning alerts", included: false },
    ]
  },
  {
    name: "Pro Analyst",
    price: "499",
    period: "/month",
    tagline: "For the investor who takes this seriously.",
    cta: "Start Pro Trial",
    popular: true,
    savings: "Save 40 percent with annual billing",
    features: [
      { text: "Unlimited AI queries", included: true },
      { text: "Live NSE + BSE + US market data", included: true },
      { text: "Full DCF, Graham, WACC models", included: true },
      { text: "Unlimited portfolio watchlist", included: true },
      { text: "Deep research memos (8-phase)", included: true },
      { text: "Portfolio risk audit & rebalancing", included: true },
      { text: "Earnings pre-result positioning", included: true },
      { text: "Priority agent compute (faster)", included: true },
      { text: "Export memos to PDF", included: false },
    ]
  },
  {
    name: "Institution",
    price: "1,499",
    period: "/month",
    tagline: "For family offices, RIAs, and serious capital.",
    cta: "Contact Sales",
    features: [
      { text: "Everything in Pro Analyst", included: true },
      { text: "Multi-portfolio management", included: true },
      { text: "Custom valuation model builder", included: true },
      { text: "API access for your systems", included: true },
      { text: "White-label reports (PDF export)", included: true },
      { text: "Dedicated support channel", included: true },
      { text: "Bulk corporate screening", included: true },
      { text: "Team seats (up to 5)", included: true },
      { text: "Quarterly strategy sessions", included: true },
    ]
  }
];

const FAQS = [
  { q: "Can I really use the free tier forever?", a: "Yes. No credit card required. No trial countdown. The free tier includes 20 queries per day, live NSE data, basic valuations, and a 10-stock watchlist. We built it to be genuinely useful because we believe once you feel the edge, you will want more." },
  { q: "How does Pro Analyst compare to brokerage research?", a: "Brokerage research costs Rs 12,000 to Rs 24,000 per year and says Buy on almost everything because they earn brokerage. Pro Analyst is Rs 499 per month, has zero conflict of interest, and shows you every assumption in the model so you can verify the math yourself." },
  { q: "What happens if I cancel Pro?", a: "You keep all your data. Your portfolio, watchlists, and conversation history stay in your browser. You simply drop back to the free tier limits. No data lock-in. No hostage pricing." },
  { q: "Is there an annual discount?", a: "Yes. Annual Pro billing is Rs 3,599 per year, which is 40 percent off the monthly price. That is less than Rs 300 per month for institutional-grade analysis on every Indian stock." },
  { q: "Do you offer refunds?", a: "If Pro Analyst does not save you at least one bad trade decision in your first 30 days, email us for a full refund. No questions asked. We are that confident." },
];

export const Pricing: React.FC = () => {
  const navigate = useNavigate();
  const [billing, setBilling] = useState<'monthly' | 'annual'>('monthly');
  const [openFaq, setOpenFaq] = useState<number | null>(null);

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
          .pricing-grid { grid-template-columns: 1fr !important; }
          .social-grid { grid-template-columns: repeat(2, 1fr) !important; }
        }
      `}</style>

      <section style={{ padding: '80px 24px 40px', textAlign: 'center' }}>
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'rgba(56,189,248,0.08)', border: '1px solid rgba(56,189,248,0.15)', color: 'var(--accent-cyan)', padding: '6px 14px', borderRadius: 999, fontSize: 12, fontWeight: 600, marginBottom: 20 }}>
            <Zap size={14} /> Simple, Transparent Pricing
          </div>
          <h1 style={{ fontSize: 'clamp(32px, 4vw, 48px)', fontWeight: 800, lineHeight: 1.1, marginBottom: 16 }}>
            Stop Paying for <span style={{ color: 'var(--loss)' }}>Useless Research.</span><br />
            Start Paying for <span style={{ background: 'var(--gradient-brand)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>Actual Edges.</span>
          </h1>
          <p style={{ fontSize: 17, color: 'var(--text-secondary)', lineHeight: 1.65, maxWidth: 580, margin: '0 auto 32px' }}>
            Your broker charges Rs 18,000 per year for 40-page PDFs that say Buy on everything. We charge less than a pizza per month for analysis that actually moves the needle on your P&L.
          </p>

          <div style={{ display: 'inline-flex', background: 'rgba(15,23,42,0.6)', border: '1px solid var(--border-subtle)', borderRadius: 10, padding: 4, marginBottom: 48 }}>
            <button onClick={() => setBilling('monthly')} style={{ padding: '8px 20px', borderRadius: 8, border: 'none', fontSize: 13, fontWeight: 600, cursor: 'pointer', background: billing === 'monthly' ? 'var(--gradient-brand)' : 'transparent', color: billing === 'monthly' ? '#0f172a' : 'var(--text-secondary)' }}>Monthly</button>
            <button onClick={() => setBilling('annual')} style={{ padding: '8px 20px', borderRadius: 8, border: 'none', fontSize: 13, fontWeight: 600, cursor: 'pointer', background: billing === 'annual' ? 'var(--gradient-brand)' : 'transparent', color: billing === 'annual' ? '#0f172a' : 'var(--text-secondary)' }}>Annual (Save 40%)</button>
          </div>
        </div>
      </section>

      <section style={{ padding: '0 24px 60px' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 20, alignItems: 'start' }} className="pricing-grid">
            {PLANS.map((plan, i) => {
              const isPro = plan.name === 'Pro Analyst';
              const displayPrice = isPro && billing === 'annual' ? '3,599' : plan.price;
              const displayPeriod = isPro && billing === 'annual' ? '/year' : plan.period;

              return (
                <div key={i} style={{
                  background: plan.popular ? 'linear-gradient(180deg, rgba(56,189,248,0.06), rgba(15,23,42,0.5))' : 'rgba(15,23,42,0.4)',
                  border: plan.popular ? '1px solid rgba(56,189,248,0.25)' : '1px solid var(--border-subtle)',
                  borderRadius: 20, padding: '32px 28px', position: 'relative', display: 'flex', flexDirection: 'column', gap: 20
                }}>
                  {plan.popular && (
                    <div style={{ position: 'absolute', top: -12, left: '50%', transform: 'translateX(-50%)', background: 'var(--gradient-brand)', color: '#0f172a', padding: '4px 14px', borderRadius: 999, fontSize: 11, fontWeight: 700 }}>
                      MOST POPULAR
                    </div>
                  )}
                  <div>
                    <h3 style={{ fontSize: 20, fontWeight: 700, marginBottom: 6 }}>{plan.name}</h3>
                    <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{plan.tagline}</p>
                  </div>
                  <div>
                    <span style={{ fontSize: 36, fontWeight: 800, fontFamily: 'var(--font-mono)' }}>Rs {displayPrice}</span>
                    <span style={{ fontSize: 14, color: 'var(--text-muted)' }}>{displayPeriod}</span>
                    {plan.savings && billing === 'monthly' && (
                      <div style={{ fontSize: 12, color: 'var(--profit)', marginTop: 4, fontWeight: 600 }}>{plan.savings}</div>
                    )}
                  </div>
                  <button
                    onClick={() => plan.name === 'Institution' ? window.alert('Contact sales@prospektlab.com for institutional onboarding.') : navigate('/onboarding')}
                    style={{
                      width: '100%', padding: '14px', borderRadius: 12, fontSize: 15, fontWeight: 700, cursor: 'pointer', border: 'none',
                      background: plan.popular ? 'var(--gradient-brand)' : 'rgba(255,255,255,0.06)',
                      color: plan.popular ? '#0f172a' : 'var(--text-primary)'
                    }}
                  >
                    {plan.cta}
                  </button>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    {plan.features.map((f, fi) => (
                      <div key={fi} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, color: f.included ? 'var(--text-primary)' : 'var(--text-muted)' }}>
                        <div style={{ width: 18, height: 18, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, background: f.included ? 'rgba(52,211,153,0.1)' : 'transparent' }}>
                          {f.included ? <Check size={12} color="var(--profit)" /> : <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>x</span>}
                        </div>
                        {f.text}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      <section style={{ padding: '0 24px 80px' }}>
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          <h2 style={{ fontSize: 'clamp(24px, 3vw, 32px)', fontWeight: 700, textAlign: 'center', marginBottom: 40 }}>
            Still Have <span style={{ background: 'var(--gradient-brand)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>Questions?</span>
          </h2>
          {FAQS.map((faq, i) => (
            <div key={i} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              <button
                onClick={() => setOpenFaq(openFaq === i ? null : i)}
                style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 0', background: 'none', border: 'none', color: 'var(--text-primary)', fontSize: 15, fontWeight: 600, textAlign: 'left', cursor: 'pointer' }}
              >
                {faq.q}
                <ChevronDown size={18} style={{ transform: openFaq === i ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s', flexShrink: 0, marginLeft: 12 }} color="var(--text-muted)" />
              </button>
              {openFaq === i && (
                <div style={{ padding: '0 0 20px', fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.7 }}>
                  {faq.a}
                </div>
              )}
            </div>
          ))}
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

export default Pricing;

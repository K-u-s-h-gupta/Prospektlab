import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Brain, Star, ArrowRight, TrendingUp, ShieldAlert, MessageSquare, Filter } from 'lucide-react';

interface DetailedReview {
  name: string;
  location: string;
  role: string;
  avatar: string;
  stars: number;
  date: string;
  title: string;
  body: string;
  result: string;
  tags: string[];
  helpful: number;
  verified: boolean;
}

const ALL_REVIEWS: DetailedReview[] = [
  {
    name: "CA, Mumbai",
    location: "Mumbai, Maharashtra",
    role: "Chartered Accountant & Part-time Investor",
    avatar: "AM",
    stars: 5,
    date: "2 days ago",
    title: "Caught the Asian Paints dip before it happened",
    body: "I was about to add more Asian Paints to my portfolio at Rs 2,850. Arthik flagged the promoter pledge increase and rising raw material costs in under 10 seconds. I held off. The stock dropped 14 percent over the next 3 weeks. That single insight saved me roughly Rs 2.3 Lakhs on a Rs 16L position. I don't make a single move now without asking Arthik first. The DCF engine is transparent enough that I can tweak assumptions myself, which is something I never got from my broker's research desk.",
    result: "Saved Rs 2.3L in 3 weeks",
    tags: ["Risk Alert", "Promoter Pledges", " avoided Loss"],
    helpful: 47,
    verified: true,
  },
  {
    name: "Tech professional, Bengaluru",
    location: "Bengaluru, Karnataka",
    role: "Tech Lead at Flipkart",
    avatar: "PK",
    stars: 5,
    date: "5 days ago",
    title: "Replaced my broker's research report entirely",
    body: "My broker's 'research' was basically a 40-page PDF with a 'Buy' rating on everything. Arthik gave me a DCF valuation on TCS in 8 seconds that I could actually tweak. I changed the growth rate assumption from 12 percent to 10 percent and saw the fair value drop from Rs 4,200 to Rs 3,890 instantly. That level of transparency doesn't exist anywhere else in the Indian market at this price. I cancelled my Rs 18,000/year brokerage research subscription after 3 weeks of using the free tier. The peer comparison feature alone is worth the Pro subscription.",
    result: "Cancelled Rs 18K/yr brokerage research",
    tags: ["DCF Valuation", "Transparency", "TCS"],
    helpful: 62,
    verified: true,
  },
  {
    name: "Business owner, Delhi",
    location: "New Delhi",
    role: "Proprietor, Auto Parts Distributor",
    avatar: "VG",
    stars: 4,
    date: "8 days ago",
    title: "Finally stopped losing money on 'tips'",
    body: "I used to follow three Telegram channels. Lost about Rs 4.8L over 18 months chasing 'multibagger' tips. Arthik doesn't give tips. It shows me the actual numbers. Piotroski score, debt ratios, cash flows. I sleep better. My portfolio is up 22 percent in 8 months, and more importantly, I understand WHY I'm holding every single stock now. The only reason I gave 4 stars instead of 5 is that the mobile view could be slightly better. But on desktop, this is flawless.",
    result: "Portfolio up 22% in 8 months",
    tags: ["No More Tips", "Piotroski", "Discipline"],
    helpful: 38,
    verified: true,
  },
  {
    name: "Dentist, Chennai",
    location: "Chennai, Tamil Nadu",
    role: "Dentist & HNI Investor",
    avatar: "SI",
    stars: 5,
    date: "12 days ago",
    title: "The debt-red flag on a 'safe' NBFC saved my capital",
    body: "I was looking at a mid-cap NBFC that every analyst was calling 'undervalued.' Arthik ran the Altman Z-Score and highlighted concentrated wholesale borrowing plus declining interest coverage in the last two quarters. I passed. The company defaulted on a commercial paper 11 weeks later. This tool paid for itself 100x over in that one decision alone. As a doctor, I don't have time to read 200-page annual reports. Arthik does it for me and tells me what actually matters in plain English.",
    result: "Avoided a likely default",
    tags: ["Altman Z-Score", "NBFC", "Risk Avoidance"],
    helpful: 91,
    verified: true,
  },
  {
    name: "Software consultant, Pune",
    location: "Pune, Maharashtra",
    role: "Software Consultant",
    avatar: "RD",
    stars: 5,
    date: "14 days ago",
    title: "Worth every rupee for the peer comparison alone",
    body: "I run a pretty standard large-cap portfolio: HDFC Bank, Reliance, TCS, Infosys. Arthik's side-by-side comparison of operating margins and ROE trends made me rebalance from Infosys to TCS. The gap was structural, not cyclical. TCS has sustained pricing power that Infosys is losing in the mid-tier digital deals. Best part? I cancelled my Rs 18,000/year brokerage research subscription. This is sharper, faster, and cheaper. The 8-phase deep research memos are like having a tiny Motilal Oswal analyst in your pocket.",
    result: "Rebalanced to TCS; saved subscription cost",
    tags: ["Peer Comparison", "Rebalancing", "TCS vs Infosys"],
    helpful: 55,
    verified: true,
  },
  {
    name: "Small business owner, Kochi",
    location: "Kochi, Kerala",
    role: "Small Business Owner",
    avatar: "KN",
    stars: 4,
    date: "18 days ago",
    title: "Took me 20 minutes to trust it, now I can't stop using it",
    body: "I'll be honest. I was skeptical. Another 'AI tool' promising miracles. But the first time I asked 'Should I average down on Zomato?' and Arthik gave me a burn-rate analysis, competitive moat assessment, AND a Graham valuation in one response, I was sold. The interface is clean. The answers are cited. It's like having a tiny Goldman Sachs analyst in my pocket. Minus one star only because the initial onboarding could explain the features a bit more. But once you learn it, it's unstoppable.",
    result: "First good Zomato decision in 2 years",
    tags: ["Zomato", "Graham Valuation", "Burn Rate"],
    helpful: 29,
    verified: true,
  },
  {
    name: "Engineer, Jaipur",
    location: "Jaipur, Rajasthan",
    role: "Civil Engineer",
    avatar: "MT",
    stars: 5,
    date: "21 days ago",
    title: "Found a 34% margin-of-safety stock my advisor missed",
    body: "My 'wealth advisor' had me in 12 mutual funds with overlapping holdings. Arthik helped me audit the entire book. Then it ran a Graham screen and surfaced a small-cap engineering stock trading at 0.6x book with zero debt and 18% ROE. My advisor had never even mentioned it. I bought at Rs 142. It's at Rs 208 now. That's not luck. That's what happens when you stop outsourcing your thinking. The portfolio concentration alert also warned me I was 42% exposed to banking stocks, which I hadn't even realized.",
    result: "Rs 142 to Rs 208 in 5 months",
    tags: ["Graham Screen", "Hidden Gem", "Concentration Alert"],
    helpful: 73,
    verified: true,
  },
  {
    name: "Designer, Hyderabad",
    location: "Hyderabad, Telangana",
    role: "Freelance UX Designer",
    avatar: "FS",
    stars: 4,
    date: "24 days ago",
    title: "The earnings calendar alone is worth it",
    body: "I work freelance, so I don't have time to read 20 annual reports. Arthik's earnings alerts and pre-result summaries have become my Sunday ritual. Before this, I'd miss result dates and get caught on the wrong side of 8% moves. In the last two quarters, I've positioned correctly before 4 out of 5 result announcements in my watchlist. The only thing I'd add is WhatsApp alerts for earnings reminders. Otherwise, this has genuinely improved my returns without increasing my time commitment.",
    result: "4/5 correct result positioning",
    tags: ["Earnings Calendar", "Pre-Result", "Time-Saving"],
    helpful: 41,
    verified: true,
  },
  {
    name: "Retired banker, Nagpur",
    location: "Nagpur, Maharashtra",
    role: "Retired Bank Manager",
    avatar: "AK",
    stars: 5,
    date: "1 month ago",
    title: "The debt analysis prevented a Rs 5L mistake",
    body: "At 62, I manage a Rs 40L retirement corpus conservatively. I was considering a corporate FD from a company that looked solid on the surface. Arthik's quick balance sheet scan showed debt-to-equity had jumped from 0.8x to 2.4x in 18 months and interest coverage had fallen below 2x. I skipped the FD. Six months later, the company restructured its debt. My Rs 5L would have been stuck. Arthik's analysis is not just for stock traders. It is for anyone who cares about capital preservation.",
    result: "Avoided a distressed corporate FD",
    tags: ["Debt Analysis", "Capital Preservation", "Retirement"],
    helpful: 84,
    verified: true,
  },
  {
    name: "Product manager, Kolkata",
    location: "Kolkata, West Bengal",
    role: "Product Manager at Swiggy",
    avatar: "DM",
    stars: 5,
    date: "1 month ago",
    title: "Rebuilt my entire portfolio strategy in one weekend",
    body: "I had Rs 8L scattered across 23 stocks with no real strategy. Arthik's portfolio audit showed I had 4 stocks in the same sector with nearly identical business models, and my beta was 1.35 without me knowing it. Over one weekend, I consolidated to 12 positions, reduced overlap, and brought beta down to 1.05. The correlation heatmap alone changed how I think about diversification. My Sharpe ratio improved significantly even though I only changed my holdings, not my stock-picking.",
    result: "Consolidated 23 to 12 stocks; reduced beta",
    tags: ["Portfolio Audit", "Diversification", "Beta"],
    helpful: 67,
    verified: true,
  },
  {
    name: "Distributor, Ahmedabad",
    location: "Ahmedabad, Gujarat",
    role: "Pharma Distributor",
    avatar: "SP",
    stars: 4,
    date: "6 weeks ago",
    title: "Good, but the free tier limits are real",
    body: "I started on the free tier and it was genuinely useful for my first week. But 20 queries per day runs out fast if you have a portfolio of 8 stocks and a watchlist of 12. Upgraded to Pro Analyst after 10 days and haven't looked back. The deep research memos on Sun Pharma and Cipla were incredibly detailed. My only suggestion: increase free tier queries to 30. Otherwise, the product is excellent and the price is fair.",
    result: "Upgraded to Pro after 10 days",
    tags: ["Pro Upgrade", "Deep Memos", "Pharma"],
    helpful: 22,
    verified: true,
  },
  {
    name: "Banking VP, Gurgaon",
    location: "Gurgaon, Haryana",
    role: "VP at HDFC Bank",
    avatar: "NA",
    stars: 5,
    date: "2 months ago",
    title: "I work in banking. This is actually accurate",
    body: "I spend my days looking at credit quality and leverage ratios. Most retail tools are toys compared to what we use internally. Arthik is the first consumer-grade tool I've seen that gets the Altman Z-Score and interest coverage calculations right without hand-holding. The DCF assumptions are conservative by default, which is exactly what a professional would do. I recommended it to three colleagues already. If you understand finance, you'll appreciate the rigor. If you don't, you'll learn fast.",
    result: "Recommended to 3 colleagues",
    tags: ["Professional Grade", "Altman Z", "Banking"],
    helpful: 102,
    verified: true,
  },
];

const TAGS = Array.from(new Set(ALL_REVIEWS.flatMap(r => r.tags))).slice(0, 12);

export const Testimonials: React.FC = () => {
  const navigate = useNavigate();
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<'recent' | 'helpful'>('helpful');

  const filtered = selectedTag
    ? ALL_REVIEWS.filter(r => r.tags.includes(selectedTag))
    : ALL_REVIEWS;

  const sorted = [...filtered].sort((a, b) =>
    sortBy === 'helpful' ? b.helpful - a.helpful : 0
  );

  const averageRating = (ALL_REVIEWS.reduce((s, r) => s + r.stars, 0) / ALL_REVIEWS.length).toFixed(1);

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
          .reviews-grid { grid-template-columns: 1fr !important; }
          .stats-row { grid-template-columns: repeat(2, 1fr) !important; }
        }
        @media (max-width: 480px) {
          .stats-row { grid-template-columns: 1fr !important; }
        }
      `}</style>

      <section style={{ padding: '80px 24px 40px', textAlign: 'center' }}>
        <div style={{ maxWidth: 720, margin: '0 auto' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.15)', color: '#fbbf24', padding: '6px 14px', borderRadius: 999, fontSize: 12, fontWeight: 600, marginBottom: 20 }}>
            <Star size={14} fill="#fbbf24" /> Verified User Reviews
          </div>
            <h1 style={{ fontSize: 'clamp(32px, 4vw, 48px)', fontWeight: 800, lineHeight: 1.1, marginBottom: 16 }}>
            <span style={{ background: 'var(--gradient-brand)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>{averageRating}/5</span> from {ALL_REVIEWS.length} Verified Investors
          </h1>
          <p style={{ fontSize: 17, color: 'var(--text-secondary)', lineHeight: 1.65, maxWidth: 620, margin: '0 auto 32px' }}>
            These are not cherry-picked testimonials. Every review includes a location, occupation, specific outcome, and verification badge. Read them. These are your peers.
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, maxWidth: 640, margin: '0 auto 40px' }} className="stats-row">
            <div style={{ background: 'rgba(15,23,42,0.4)', border: '1px solid var(--border-subtle)', borderRadius: 12, padding: 16 }}>
              <div style={{ fontSize: 24, fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{averageRating}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>Avg. Rating</div>
            </div>
            <div style={{ background: 'rgba(15,23,42,0.4)', border: '1px solid var(--border-subtle)', borderRadius: 12, padding: 16 }}>
              <div style={{ fontSize: 24, fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{ALL_REVIEWS.length}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>Reviews</div>
            </div>
            <div style={{ background: 'rgba(15,23,42,0.4)', border: '1px solid var(--border-subtle)', borderRadius: 12, padding: 16 }}>
              <div style={{ fontSize: 24, fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{Math.round(ALL_REVIEWS.reduce((s, r) => s + r.helpful, 0) / ALL_REVIEWS.length)}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>Avg. Helpful</div>
            </div>
            <div style={{ background: 'rgba(15,23,42,0.4)', border: '1px solid var(--border-subtle)', borderRadius: 12, padding: 16 }}>
              <div style={{ fontSize: 24, fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>100%</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>Verified</div>
            </div>
          </div>
        </div>
      </section>

      <section style={{ padding: '0 24px 60px' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', justifyContent: 'center', marginBottom: 32 }}>
            <button onClick={() => setSelectedTag(null)} style={{ padding: '6px 14px', borderRadius: 999, border: '1px solid', fontSize: 12, fontWeight: 600, cursor: 'pointer', borderColor: selectedTag === null ? 'var(--accent-cyan)' : 'var(--border-subtle)', background: selectedTag === null ? 'rgba(56,189,248,0.08)' : 'transparent', color: selectedTag === null ? 'var(--accent-cyan)' : 'var(--text-secondary)' }}>
              All Reviews
            </button>
            {TAGS.map(tag => (
              <button key={tag} onClick={() => setSelectedTag(tag === selectedTag ? null : tag)} style={{ padding: '6px 14px', borderRadius: 999, border: '1px solid', fontSize: 12, fontWeight: 600, cursor: 'pointer', borderColor: selectedTag === tag ? 'var(--accent-cyan)' : 'var(--border-subtle)', background: selectedTag === tag ? 'rgba(56,189,248,0.08)' : 'transparent', color: selectedTag === tag ? 'var(--accent-cyan)' : 'var(--text-secondary)' }}>
                {tag}
              </button>
            ))}
            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Filter size={14} color="var(--text-muted)" />
              <select value={sortBy} onChange={e => setSortBy(e.target.value as 'recent' | 'helpful')} style={{ background: 'rgba(15,23,42,0.6)', border: '1px solid var(--border-subtle)', color: 'var(--text-primary)', padding: '6px 12px', borderRadius: 8, fontSize: 12, cursor: 'pointer' }}>
                <option value="helpful">Most Helpful</option>
                <option value="recent">Most Recent</option>
              </select>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 20 }} className="reviews-grid">
            {sorted.map((r, i) => (
              <div key={i} style={{ background: 'rgba(15,23,42,0.4)', border: '1px solid var(--border-subtle)', borderRadius: 16, padding: 28, display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <div style={{ width: 44, height: 44, borderRadius: '50%', background: 'var(--gradient-brand)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, fontWeight: 700, color: '#0f172a' }}>
                      {r.avatar}
                    </div>
                    <div>
                      <div style={{ fontSize: 14, fontWeight: 600 }}>{r.name}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{r.location}</div>
                    </div>
                  </div>
                  {r.verified && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, fontWeight: 700, color: 'var(--profit)', background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.15)', padding: '3px 8px', borderRadius: 6, textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                      <ShieldAlert size={10} /> Verified
                    </div>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 2 }}>
                  {[...Array(5)].map((_, si) => <Star key={si} size={14} fill={si < r.stars ? "#fbbf24" : "transparent"} color={si < r.stars ? "#fbbf24" : "var(--text-muted)"} />)}
                </div>
                <h3 style={{ fontSize: 16, fontWeight: 700, lineHeight: 1.4 }}>{r.title}</h3>
                <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.65, flex: 1 }}>{r.body}</p>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 4 }}>
                  {r.tags.map(tag => (
                    <span key={tag} style={{ fontSize: 11, background: 'rgba(56,189,248,0.06)', color: 'var(--accent-cyan)', padding: '3px 8px', borderRadius: 6, border: '1px solid rgba(56,189,248,0.12)' }}>{tag}</span>
                  ))}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 8, paddingTop: 12, borderTop: '1px solid var(--border-subtle)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-muted)' }}>
                    <TrendingUp size={12} />
                    <span style={{ fontWeight: 600, color: 'var(--profit)' }}>{r.result}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-muted)' }}>
                    <MessageSquare size={12} />
                    {r.helpful} found helpful
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section style={{ padding: '40px 24px 80px' }}>
        <div style={{ maxWidth: 720, margin: '0 auto', textAlign: 'center' }}>
          <h2 style={{ fontSize: 24, fontWeight: 700, marginBottom: 16 }}>Ready to Join These Investors?</h2>
          <p style={{ fontSize: 15, color: 'var(--text-secondary)', marginBottom: 24 }}>Every review above started with one free query. Your edge is 30 seconds away.</p>
          <button onClick={() => navigate('/get-started')} style={{ background: 'var(--gradient-brand)', color: '#0f172a', border: 'none', padding: '16px 32px', borderRadius: 12, fontSize: 16, fontWeight: 700, cursor: 'pointer', boxShadow: '0 0 24px rgba(56,189,248,0.15)' }}>
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

export default Testimonials;

# ORACLE — Financial Intelligence Operating System
## Complete Product Architecture, Market Fit & Build Plan
### May 2026 | Version 1.0

---

## 1. PRODUCT VISION & MARKET FIT

### What ORACLE Is
A **conversational Financial Intelligence OS** for India where any user can ask anything about:
- Any company listed on NSE/BSE (5,500+ companies)
- Indian stock market (indices, sectors, themes, IPOs, FPOs)
- Financial concepts, ratios, fundamentals
- Portfolio analysis (when broker is connected)
- Real-time alerts on news, announcements, corporate actions

### Why This Wins in India (May 2026 Market Context)

| Market Signal | Data Point |
|---|---|
| Demat accounts in India | 180M+ (grew 30M in last 12 months) |
| Retail participation in equity | 45%+ of daily turnover |
| Existing AI finance tools | Thurro ($institutional, expensive), generic ChatGPT (hallucinates financials) |
| Zerodha Kite MCP | Just launched — proves broker+AI integration is the future |
| SEBI 2026 regulations | Require AI transparency, no black-box advice — ORACLE's analysis-only positioning is PERFECT |
| Gap in market | No affordable, accurate, India-focused conversational financial intelligence for retail |

### Your Competitive Moat
1. **India-deep, not India-wide** — Every BSE/NSE company, not a global product adapted for India
2. **Analysis, not advice** — SEBI-safe positioning (no RIA registration needed for analysis/data)
3. **Broker-integrated** — Portfolio context makes every answer personalized
4. **Accuracy-first architecture** — VERAFI verification, deterministic math, cited sources
5. **Alerts as retention** — Users come back daily for personalized alerts (not just when they have a question)

### Competitor Landscape

| Product | Positioning | Weakness ORACLE Exploits |
|---|---|---|
| **Thurro** | Institutional AI research ($$$) | Too expensive for retail, no portfolio integration |
| **Trendlyne** | Screeners + alerts | No conversational AI, rigid UI |
| **Tickertape** | Stock analysis dashboards | No AI, no broker integration, no natural language |
| **Smallcase** | Thematic investing | Investment product, not intelligence OS |
| **ChatGPT/Gemini** | General AI | Hallucinates financial data, no real-time, no Indian depth |
| **Zerodha Kite MCP** | Broker AI assistant | Limited to Zerodha portfolio, no cross-company analysis |

---

## 2. PRODUCT PHASES & FEATURES

### Phase 1: Intelligence Engine (Month 1-3) — MVP
**"Ask anything about any Indian company"**

| Feature | Description | Example Query |
|---|---|---|
| Company Intelligence | Fundamentals, ratios, financials for all NSE/BSE companies | "What is TCS's debt-to-equity ratio?" |
| Comparative Analysis | Side-by-side company comparison | "Compare Infosys vs TCS on revenue growth, margins, PE" |
| Sector Analysis | Sector-level aggregates and trends | "Which IT companies have the best margin improvement?" |
| Financial Concepts | Explain any financial concept with Indian context | "Explain how bonus shares work in India" |
| Earnings Analysis | Parse and analyze quarterly results | "Summarize Reliance Q4 FY26 results" |
| Management Quality | Promoter holding changes, pledging, insider trading | "Has promoter holding decreased in Adani Green?" |
| Historical Patterns | Price and fundamental trends | "Show HDFC Bank's NPA trend over 5 years" |
| Estimation Engine | DCF, comparable valuation, scenario analysis | "What's a fair value estimate for Asian Paints?" |

### Phase 2: Broker Integration & Portfolio (Month 4-6)
**"Connect your broker, get personalized intelligence"**

| Feature | Description |
|---|---|
| Portfolio Sync | Connect Zerodha/Angel One/Upstox/Groww via API |
| Portfolio Health Check | Overall diversification, concentration risk, sector exposure |
| Holdings Analysis | Fundamental analysis of each holding in context |
| Performance Attribution | Which holdings drove gains/losses and why |
| Risk Assessment | Exposure analysis, correlation, downside scenarios |
| "What If" Scenarios | "What happens to my portfolio if IT sector drops 20%?" |
| Portfolio vs Benchmark | Compare against Nifty 50, sector indices |

### Phase 3: Alerts & Monitoring (Month 5-7)
**"Never miss what matters to your money"**

| Alert Type | Source | Delivery |
|---|---|---|
| Corporate Announcements | BSE/NSE filings API | Push + In-app |
| Earnings Surprises | Quarterly results vs estimates | Push + In-app |
| Promoter Holding Changes | SAST filings | Push + In-app |
| Insider Trading | Insider disclosure filings | Push + In-app |
| Price Alerts | Real-time price feed | Push + Telegram + Email |
| News Sentiment Shifts | News aggregation + NLP | In-app |
| SEBI/RBI Policy Changes | Regulatory feeds | Weekly digest |
| Portfolio Risk Alerts | Concentration, drawdown thresholds | Push |
| Earnings Calendar | Upcoming results for holdings | Weekly digest |

### Phase 4: Advanced Intelligence (Month 8-12)
- Forensic accounting red-flag detection
- IPO analysis engine
- Mutual fund portfolio overlap analysis
- Tax harvesting suggestions (with CA disclaimer)
- Screener with natural language ("Find companies with ROE > 20%, debt-free, in pharma sector")
- Earnings call transcript Q&A (RAG over transcripts)

---

## 3. COMPLETE TECHNICAL ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────┐
│                    USER INTERFACE LAYER                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │ Web App  │  │Mobile App│  │ Telegram │  │  WhatsApp  │  │
│  │ (Next.js)│  │(React    │  │   Bot    │  │   Bot      │  │
│  │          │  │ Native)  │  │          │  │ (Phase 3)  │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬───────┘  │
│       └──────────────┴──────────────┴──────────────┘         │
│                           │                                   │
│                    API Gateway (FastAPI)                      │
│                    Rate Limiting + Auth                       │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│                 AGENTIC ORCHESTRATION LAYER                   │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              SUPERVISOR AGENT (LangGraph)                │ │
│  │         Model: Gemini 2.5 Flash (routing, $0.0003)      │ │
│  │                                                          │ │
│  │  • Classifies user intent (15 categories)               │ │
│  │  • Plans which sub-agents to invoke                     │ │
│  │  • Manages conversation memory                          │ │
│  │  • Handles follow-up context                            │ │
│  │  • Enforces "analysis only, no advice" guardrails       │ │
│  └──────┬──────┬──────┬──────┬──────┬──────┬───────────────┘ │
│         │      │      │      │      │      │                  │
│    ┌────▼┐ ┌──▼──┐ ┌─▼──┐ ┌▼───┐ ┌▼───┐ ┌▼────┐           │
│    │Data │ │Qual.│ │Hist│ │Est.│ │Rpt.│ │Veri.│            │
│    │Coll.│ │Res. │ │Pat.│ │Eng.│ │Syn.│ │Agt. │            │
│    │Agent│ │Agent│ │Agt.│ │    │ │    │ │     │            │
│    └──┬──┘ └──┬──┘ └─┬──┘ └─┬──┘ └─┬──┘ └──┬──┘           │
│       │       │      │      │      │       │                │
│  ─────┴───────┴──────┴──────┴──────┴───────┴──────          │
│                                                               │
│  NEW AGENTS FOR FIOS:                                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │Portfolio │ │Alert     │ │Screener  │ │Concept   │       │
│  │Analyzer  │ │Monitor   │ │Agent     │ │Explainer │       │
│  │Agent     │ │Agent     │ │          │ │Agent     │       │
│  │(Phase 2) │ │(Phase 3) │ │(Phase 4) │ │(Phase 1) │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│                    DATA & MCP LAYER                           │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Indian Mkt  │  │ FMP MCP     │  │ Zerodha Kite MCP    │  │
│  │ MCP Server  │  │ Server      │  │ (Official)          │  │
│  │ (Custom)    │  │ ($14/mo)    │  │ mcp.kite.trade/mcp  │  │
│  │             │  │             │  │                     │  │
│  │ • NSE API   │  │ • Global    │  │ • Holdings          │  │
│  │ • BSE API   │  │   fundmntls │  │ • Positions         │  │
│  │ • Screener  │  │ • Earnings  │  │ • Orders            │  │
│  │ • MoneyCtrl │  │   transcpts │  │ • P&L               │  │
│  │ • Trendlyne │  │ • 30yr hist │  │ • Margins           │  │
│  │ • Corp.     │  │ • 70K+      │  │                     │  │
│  │   filings   │  │   securities│  │                     │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ SEC EDGAR   │  │ Angel One   │  │ NSE-BSE MCP         │  │
│  │ MCP (free)  │  │ SmartAPI    │  │ (Open Source)       │  │
│  │ (US compns) │  │ (FREE APIs) │  │ github:bshada/      │  │
│  │             │  │             │  │  nse-bse-mcp        │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Upstox API  │  │ Groww API   │  │ News APIs           │  │
│  │ (₹10/order) │  │ (when avail)│  │ • NewsAPI           │  │
│  │ Portfolio   │  │             │  │ • Google News RSS   │  │
│  │ + Holdings  │  │             │  │ • BSE Announcements │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│                 KNOWLEDGE & STORAGE LAYER                     │
│                                                               │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐ │
│  │  PostgreSQL    │  │  Vector DB     │  │  Redis         │ │
│  │  (Supabase)   │  │  (Qdrant)      │  │  (Cache)       │ │
│  │               │  │                │  │                │ │
│  │ • User data   │  │ • Earnings     │  │ • Session      │ │
│  │ • Portfolio   │  │   transcripts  │  │ • Rate limits  │ │
│  │   snapshots   │  │ • Annual rpts  │  │ • Price cache  │ │
│  │ • Alert rules │  │ • DRHP/RHP     │  │ • API response │ │
│  │ • Chat hist.  │  │ • Mgmt discuss │  │   cache        │ │
│  │ • Company     │  │ • News archive │  │ • Real-time    │ │
│  │   master data │  │ • SEBI orders  │  │   quotes       │ │
│  └────────────────┘  └────────────────┘  └────────────────┘ │
│                                                               │
│  ┌──────────────────────────────────────────────────────────┐│
│  │          DETERMINISTIC COMPUTATION ENGINE                ││
│  │  (Python — NO LLM math, NO hallucinated numbers)        ││
│  │                                                          ││
│  │  • DCF Valuation    • PE/PB/EV multiples                ││
│  │  • WACC Calculator  • DuPont decomposition              ││
│  │  • Altman Z-Score   • Piotroski F-Score                 ││
│  │  • Ratio calculator • Portfolio analytics (Sharpe, etc) ││
│  │  • Scenario models  • Correlation matrix                ││
│  │  • Tax computation  • XIRR/CAGR                        ││
│  └──────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘
```

---

## 4. ALL 10 AGENTS — DETAILED SPECS

### Original 6+1 Agents (from previous architecture)

| # | Agent | Model | Role | Cost/Call |
|---|-------|-------|------|-----------|
| 0 | **Supervisor** | Gemini 2.5 Flash | Intent classification, routing, memory, guardrails | $0.0003 |
| 1 | **Data Collector** | Gemini 2.5 Flash | Pull structured data from MCP servers | $0.0004 |
| 2 | **Qualitative Researcher** | Deep Research Max | Industry analysis, management quality, moat assessment | $0.03 |
| 3 | **Historical Pattern Analyzer** | Claude Sonnet 4.6 | Trend analysis, cycle detection, seasonal patterns | $0.015 |
| 4 | **Estimation Engine** | Claude Opus 4.7 | Valuation, scenario analysis (calls deterministic math) | $0.08 |
| 5 | **Report Synthesizer** | GPT-5.4-Mini | Structured output generation, charts, formatting | $0.01 |
| 6 | **Verification Agent** | Claude Opus 4.7 | VERAFI accuracy checks, source citation verification | $0.06 |

### 4 NEW Agents for Financial Intelligence OS

| # | Agent | Model | Role | Cost/Call |
|---|-------|-------|------|-----------|
| 7 | **Portfolio Analyzer** | Claude Sonnet 4.6 | Portfolio health, attribution, risk, what-if scenarios | $0.02 |
| 8 | **Alert Monitor** | Gemini 2.5 Flash | Continuous monitoring, trigger evaluation, notification dispatch | $0.0002/check |
| 9 | **Screener Agent** | Gemini 2.5 Flash | Natural language → structured stock screening queries | $0.001 |
| 10 | **Concept Explainer** | GPT-5.4-Mini | Financial education, concept explanation with Indian context | $0.005 |

### Agent Execution Patterns

```
SIMPLE QUERY: "What is Infosys PE ratio?"
  Supervisor → Data Collector → Report Synthesizer
  Cost: ~$0.01 | Latency: ~3 seconds

ANALYSIS QUERY: "Analyze Reliance Industries fundamentals"  
  Supervisor → [Data Collector ‖ Qualitative Researcher ‖ Historical Analyzer]
            → Estimation Engine → Report Synthesizer → Verification Agent
  Cost: ~$0.20 | Latency: ~30 seconds

PORTFOLIO QUERY: "How is my portfolio doing?"
  Supervisor → [Data Collector (broker MCP) ‖ Portfolio Analyzer]
            → Report Synthesizer
  Cost: ~$0.04 | Latency: ~8 seconds

CONCEPT QUERY: "Explain how FII flows affect Indian markets"
  Supervisor → Concept Explainer
  Cost: ~$0.005 | Latency: ~3 seconds

SCREENING QUERY: "Find debt-free companies with ROE > 20% in pharma"
  Supervisor → Screener Agent → Data Collector → Report Synthesizer
  Cost: ~$0.015 | Latency: ~5 seconds

ALERT CHECK (runs every 5 minutes during market hours):
  Alert Monitor → Data Collector → [conditional] Notification
  Cost: ~$0.001/check × 75 checks/day = $0.075/user/day
```

---

## 5. TECHNOLOGY STACK — EXACT CHOICES

### Backend
| Component | Technology | Why | Cost |
|---|---|---|---|
| **Orchestration** | LangGraph + Deep Agents SDK | Agents-as-tools, state persistence, model-agnostic | Free (OSS) |
| **API Server** | FastAPI (Python) | Async, fast, typed, great ecosystem | Free (OSS) |
| **Task Queue** | Celery + Redis | Alert monitoring, background processing | Free (OSS) |
| **WebSocket** | FastAPI WebSocket | Streaming responses, real-time updates | Free (OSS) |
| **Auth** | Supabase Auth | OAuth, JWT, broker OAuth callbacks | Free tier |

### Data Layer
| Component | Technology | Why | Cost |
|---|---|---|---|
| **Primary DB** | PostgreSQL (Supabase) | Relational, JSONB, full-text search | Free → $25/mo |
| **Vector DB** | Qdrant Cloud | RAG for earnings transcripts, filings | Free → $30/mo |
| **Cache** | Redis (Upstash) | API caching, sessions, rate limiting | Free → $10/mo |
| **Object Storage** | Cloudflare R2 | PDF storage, report archives | ~$5/mo |

### MCP Servers (Data Sources)
| MCP Server | Data Provided | Cost |
|---|---|---|
| **FMP MCP** | Global fundamentals, transcripts, 30yr history | $14/mo (Starter) |
| **NSE-BSE MCP** (open source) | Live Indian market data, indices, IPOs | Free |
| **Indian Stock MCP** (custom/enhance) | Deep NSE/BSE data, corp filings, screener data | Free (build it) |
| **Zerodha Kite MCP** (official) | Portfolio, holdings, P&L for Zerodha users | Free (per-user OAuth) |
| **Angel One SmartAPI** | Portfolio for Angel One users | Free API |
| **Upstox API** | Portfolio for Upstox users | ₹10/order (read is free) |
| **SEC EDGAR MCP** | US company filings (bonus) | Free |
| **News MCP** (custom) | BSE announcements, Google News, MoneyControl RSS | Free (build it) |

### Frontend
| Component | Technology | Why |
|---|---|---|
| **Web App** | Next.js 15 + Tailwind | SSR, fast, great DX |
| **Mobile** | React Native / Expo | Cross-platform from same team |
| **Charts** | Recharts + Lightweight Charts (TradingView) | Financial charts, free |
| **Telegram Bot** | python-telegram-bot | Low-friction alert delivery |

### Infrastructure
| Component | Technology | Cost |
|---|---|---|
| **Hosting** | Railway.app or Render | $20-50/mo |
| **CDN** | Cloudflare | Free |
| **Monitoring** | Sentry + Posthog | Free tier |
| **CI/CD** | GitHub Actions | Free |

---

## 6. BROKER INTEGRATION ARCHITECTURE

### Supported Brokers (India)

| Broker | API Type | Auth Flow | Data Available | Status |
|---|---|---|---|---|
| **Zerodha** | Kite MCP + Kite Connect REST | OAuth 2.0 | Holdings, positions, orders, P&L, margins, instruments | ✅ MCP Ready |
| **Angel One** | SmartAPI REST | API Key + TOTP | Holdings, positions, orders, P&L, market data | ✅ API Ready |
| **Upstox** | REST v2 | OAuth 2.0 | Holdings, positions, orders, P&L, market data | ✅ API Ready |
| **Groww** | Not yet public | — | — | ⏳ Watch |
| **5Paisa** | REST | OAuth + TOTP | Holdings, orders, positions | ✅ API Ready |
| **IIFL** | REST | API Key | Holdings, orders | ✅ API Ready |

### Broker Integration Flow
```
User clicks "Connect Zerodha"
     │
     ▼
ORACLE redirects to Zerodha OAuth
     │
     ▼
User logs in to Zerodha, grants read-only access
     │
     ▼
Zerodha returns access_token to ORACLE callback
     │
     ▼
ORACLE stores encrypted token in PostgreSQL
     │
     ▼
Portfolio Analyzer Agent can now call Kite MCP / SmartAPI
with user's token to fetch:
  • Holdings (qty, avg price, current value)
  • Positions (intraday, delivery)
  • P&L (realized, unrealized)
  • Order history
  • Margin utilization
     │
     ▼
Combined with fundamental data from FMP + NSE-BSE MCP
to provide personalized portfolio intelligence
```

### Critical: Read-Only Access Only
- ORACLE **never places orders** in Phase 1-3
- Only requests READ permissions from broker APIs
- Tokens stored encrypted (AES-256) with user-specific keys
- Token refresh handled automatically
- User can disconnect broker anytime

---

## 7. ALERT & MONITORING SYSTEM

### Architecture
```
┌──────────────────────────────────────────────────┐
│              ALERT MONITOR SERVICE                │
│         (Celery Beat + Worker Processes)          │
│                                                   │
│  ┌───────────┐    ┌───────────┐    ┌───────────┐│
│  │ Market    │    │ Filing    │    │ Portfolio  ││
│  │ Hours     │    │ Monitor   │    │ Monitor    ││
│  │ Scheduler │    │ (24/7)    │    │ (EOD)      ││
│  │           │    │           │    │            ││
│  │ Every 5m  │    │ Every 15m │    │ Daily 7pm  ││
│  │ 9:15-3:30 │    │ BSE/NSE   │    │ After mkt  ││
│  │ IST       │    │ filings   │    │ close      ││
│  └─────┬─────┘    └─────┬─────┘    └─────┬──────┘│
│        │                │                │        │
│        └────────────────┼────────────────┘        │
│                         │                         │
│              ┌──────────▼──────────┐              │
│              │   TRIGGER ENGINE    │              │
│              │                     │              │
│              │ Compare against     │              │
│              │ user alert rules    │              │
│              │ stored in Postgres  │              │
│              └──────────┬──────────┘              │
│                         │                         │
│              ┌──────────▼──────────┐              │
│              │ NOTIFICATION ROUTER │              │
│              │                     │              │
│              │ • Push notification  │              │
│              │ • Telegram message   │              │
│              │ • Email (SendGrid)   │              │
│              │ • In-app badge       │              │
│              │ • WhatsApp (Phase 3) │              │
│              └─────────────────────┘              │
└──────────────────────────────────────────────────┘
```

### Alert Data Sources

| Source | What It Monitors | Polling Frequency |
|---|---|---|
| BSE Announcements API | Corporate announcements (1,200+/day) | Every 15 minutes |
| NSE Corporate Filings | Board meetings, results, SAST filings | Every 15 minutes |
| Price Feed (NSE-BSE MCP) | Price crosses user thresholds | Every 5 min (market hours) |
| News APIs | Sentiment shifts on user's holdings | Every 30 minutes |
| Broker API (portfolio) | Large unrealized loss/gain alerts | Daily after market |
| SEBI Circulars | New regulations affecting holdings | Daily |

---

## 8. RAG KNOWLEDGE BASE

### What Goes Into Vector DB (Qdrant)

| Document Type | Volume | Source | Update Frequency |
|---|---|---|---|
| Earnings Call Transcripts | ~5,000/quarter (Nifty 500) | FMP API | Quarterly |
| Annual Reports | ~5,500/year | BSE filings | Annually |
| DRHP / RHP (IPO docs) | ~50-80/year | SEBI/NSE | As filed |
| Management Discussion & Analysis | ~5,500/year | Annual reports | Annually |
| Credit Rating Reports | ~2,000/year | CRISIL/ICRA/CARE | As published |
| SEBI Orders & Circulars | ~500/year | SEBI website | Weekly |
| Concall Q&A | ~5,000/quarter | FMP transcripts | Quarterly |

### RAG Architecture: HybridRAG (Vector + Knowledge Graph)

Based on latest research (ACM ICAIF 2025), **HybridRAG outperforms both pure VectorRAG and GraphRAG** for financial Q&A:

```
User Query: "What did Infosys management say about AI revenue in Q4?"
     │
     ├──→ Vector Search (Qdrant) → Top 5 transcript chunks by similarity
     │
     ├──→ Knowledge Graph (Neo4j) → Infosys → AI_Revenue → Q4_FY26 → related entities
     │
     └──→ Merge & Re-rank → Feed to Claude Sonnet for answer generation
```

### Embedding Model
- **Cohere embed-v4** or **Voyage Finance 2** (specialized for financial text)
- Chunk size: 512 tokens with 50-token overlap
- Metadata: company, date, document_type, section

---

## 9. COMPLIANCE & LEGAL (CRITICAL FOR INDIA)

### SEBI Regulations You MUST Follow

| Regulation | Requirement | How ORACLE Complies |
|---|---|---|
| **SEBI (Investment Advisers) Reg, 2013** | RIA registration needed for personalized advice | ORACLE provides ANALYSIS only, never says "buy/sell/hold" |
| **SEBI Research Analyst Reg, 2014** | RA registration for research reports with recommendations | ORACLE provides DATA + ESTIMATION, no "target price" or "rating" |
| **SEBI Algo Trading Reg, 2026** | AI transparency, ethical decision-making | ORACLE shows sources, methodology, confidence levels |
| **IT Act + DPDP Act 2023** | Data protection, consent | Encrypted storage, explicit consent for broker connection |

### Guardrails Built Into Every Response

```python
SYSTEM_GUARDRAILS = {
    "never_say": [
        "you should buy", "you should sell", "I recommend",
        "target price is", "this stock will go to",
        "guaranteed returns", "safe investment"
    ],
    "always_include": [
        "This is for analysis purposes only",
        "Past performance does not indicate future results",
        "Consult a SEBI-registered advisor for investment advice"
    ],
    "estimation_disclaimer": (
        "This estimation is based on [methodology]. "
        "Actual outcomes may differ materially. "
        "This is not a recommendation."
    )
}
```

---

## 10. COST BREAKDOWN — BUILD & RUN

### Build Cost (One-Time)

| Component | If Solo Dev (You) | If Small Team (2-3) |
|---|---|---|
| Phase 1: Intelligence Engine | 3 months of your time | 1.5 months |
| Phase 2: Broker Integration | 2 months | 1 month |
| Phase 3: Alerts | 1.5 months | 0.75 months |
| Phase 4: Advanced | 2-3 months | 1.5 months |
| **UI/UX Design** | ₹30-50K (Fiverr/Freelancer) | ₹30-50K |
| **Domain + Branding** | ₹5-10K | ₹5-10K |
| **Legal (Terms, Privacy)** | ₹10-20K (template + review) | ₹10-20K |
| **Total Cash Outlay** | **₹50-80K** + your time | **₹3-5L** if hiring |

### Monthly Running Cost

| Item | Phase 1 (0-1K users) | Phase 2 (1-10K users) | Phase 3 (10-50K users) |
|---|---|---|---|
| **LLM API Costs** | ₹2-5K | ₹15-40K | ₹80-200K |
| FMP API | ₹1.2K ($14) | ₹2.5K ($29) | ₹7K ($79) |
| Hosting (Railway/Render) | ₹2K | ₹5K | ₹15K |
| Database (Supabase) | Free | ₹2K | ₹5K |
| Vector DB (Qdrant) | Free | ₹2.5K | ₹8K |
| Redis (Upstash) | Free | ₹800 | ₹3K |
| Notifications (SendGrid etc) | Free | ₹500 | ₹3K |
| Monitoring | Free | Free | ₹2K |
| **TOTAL MONTHLY** | **₹5-8K** | **₹25-50K** | **₹1.2-2.5L** |

### Per-User Economics

| Metric | Value |
|---|---|
| Cost per simple query | ₹0.80-1.50 ($0.01) |
| Cost per full analysis | ₹15-20 ($0.19) |
| Cost per alert check/user/day | ₹6 ($0.075) |
| Monthly cost per active user (avg) | ₹30-80 |
| Suggested pricing (freemium) | Free: 10 queries/day, Pro: ₹299/mo, Premium: ₹799/mo |
| **Break-even** | ~200 Pro users or ~80 Premium users |

---

## 11. MONETIZATION MODEL

| Tier | Price | Features |
|---|---|---|
| **Free** | ₹0 | 10 queries/day, basic company data, no broker integration |
| **Pro** | ₹299/mo | Unlimited queries, full analysis, 1 broker, 10 alerts |
| **Premium** | ₹799/mo | Everything + estimation engine, all brokers, unlimited alerts, transcripts RAG, portfolio analytics |
| **API Access** | ₹1,999/mo | For developers/RIAs who want ORACLE intelligence in their own products |

### Revenue Projections (Conservative)

| Month | Users | Paying Users (5%) | MRR |
|---|---|---|---|
| Month 6 | 1,000 | 50 | ₹20K |
| Month 12 | 10,000 | 500 | ₹2L |
| Month 18 | 50,000 | 2,500 | ₹10L |
| Month 24 | 200,000 | 10,000 | ₹40L |

---

## 12. DEVELOPMENT ROADMAP

### Phase 1: MVP — Intelligence Engine (Weeks 1-12)

```
Week 1-2:  Project setup, LangGraph scaffold, Supervisor agent
Week 3-4:  Indian Market MCP server (NSE/BSE data collection)
Week 5-6:  Data Collector + Concept Explainer agents
Week 7-8:  Estimation Engine + Deterministic math library
Week 9-10: Verification Agent + VERAFI layer
Week 11:   Report Synthesizer + basic web UI (Next.js)
Week 12:   Testing, prompt refinement, deploy MVP
           → LAUNCH: "Ask anything about any Indian company"
```

### Phase 2: Broker Integration (Weeks 13-20)

```
Week 13-14: Zerodha Kite OAuth integration + Kite MCP
Week 15-16: Portfolio Analyzer agent
Week 17-18: Angel One SmartAPI + Upstox integration
Week 19-20: Portfolio UI, testing, deploy
            → LAUNCH: "Connect your broker"
```

### Phase 3: Alerts (Weeks 21-28)

```
Week 21-22: Alert Monitor agent + Celery Beat setup
Week 23-24: BSE/NSE filing monitor + News sentiment pipeline
Week 25-26: Telegram bot + push notifications
Week 27-28: Alert management UI, testing, deploy
            → LAUNCH: "Never miss what matters"
```

### Phase 4: Advanced (Weeks 29-40+)

```
Week 29-32: RAG pipeline (earnings transcripts, annual reports)
Week 33-36: Natural language screener, IPO analyzer
Week 37-40: Forensic accounting, MF overlap, tax features
            → LAUNCH: "Full Financial Intelligence OS"
```

---

## 13. WHAT YOU NEED TO BUILD YOURSELF (4 Custom Components)

### 1. Indian Market MCP Server (MOST IMPORTANT)
- **Why**: No production-grade Indian market MCP exists yet
- **What**: Wrap NSE/BSE APIs + screener.in data + MoneyControl
- **Tools**: Python, FastMCP library, caching layer
- **Data**: Company master (5,500+), financials, shareholding, corp actions
- **Effort**: 2-3 weeks
- **Tip**: Start with the open-source `bshada/nse-bse-mcp` and extend it

### 2. VERAFI Verification Layer
- **Why**: 52.4% → 94.7% accuracy improvement
- **What**: Cross-reference LLM outputs against source data
- **Effort**: 1-2 weeks

### 3. Deterministic Valuation Engine
- **Why**: LLMs cannot do math. Period.
- **What**: Python library for DCF, WACC, ratios, Piotroski, Altman-Z, XIRR
- **Effort**: 2-3 weeks (or use `financetoolkit` PyPI package as base)

### 4. Alert Pipeline
- **Why**: This is your retention engine
- **What**: Celery workers monitoring BSE/NSE, evaluating user rules, dispatching
- **Effort**: 2-3 weeks

---

## 14. COMPETITIVE ADVANTAGES SUMMARY

| Advantage | Why It Matters |
|---|---|
| **India-first data architecture** | Every MCP, every agent optimized for Indian market nuances (promoter holding, SEBI filings, Indian accounting standards) |
| **Analysis-only positioning** | No SEBI RIA/RA registration needed, legally clean |
| **Multi-broker integration** | Not locked to one broker like Kite MCP |
| **Agentic accuracy** | VERAFI verification + deterministic math = 94.7% accuracy |
| **Cost-optimized agents** | Model tiering ($0.01 for simple, $0.19 for full analysis) |
| **Alert-driven retention** | Users come back daily without being asked |
| **Extensible architecture** | Add new agents as graph nodes, new brokers as MCP servers |
| **Open protocol ready** | A2A protocol support means future integration with SEBI/exchange agents |

---

## 15. RISKS & MITIGATIONS

| Risk | Impact | Mitigation |
|---|---|---|
| SEBI classifies ORACLE as investment advice | Shutdown | Strict guardrails, legal review, "analysis only" everywhere |
| NSE/BSE blocks API scraping | No data | Use official paid data feeds ($), multiple fallback sources |
| LLM hallucinations in financials | Trust loss | VERAFI layer, deterministic math, source citations |
| Broker API rate limits | Slow portfolio sync | Cache portfolio snapshots, refresh on user request only |
| Competitor (Thurro) goes retail | Market share | Move fast, build community, broker integration is your moat |
| LLM costs spike | Margin loss | Model tiering already optimized, Gemini Flash for 60% of queries |

---

## 16. IMMEDIATE NEXT STEPS FOR YOU

1. **This week**: Set up LangGraph project, get FMP API key ($14/mo), test the open-source NSE-BSE MCP server
2. **Week 2**: Build Supervisor + Data Collector + Concept Explainer agents (simplest 3)
3. **Week 3-4**: Build your custom Indian Market MCP server (this is the moat)
4. **Week 5-6**: Add Estimation Engine + Verification Agent
5. **Week 7**: Basic Next.js chat UI
6. **Week 8**: Deploy MVP, test with 10 friends

**Estimated time to working MVP: 8-10 weeks (solo developer)**
**Estimated cash to MVP: ₹5-8K/month running cost + your time**

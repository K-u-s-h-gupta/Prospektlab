# PROSPEKTLAB — Complete Latest Architecture Documentation

> **Financial Intelligence Operating System**  
> AI-powered automated financial research, portfolio analytics, content generation, and governance intelligence for Indian capital markets.

> **Version:** 2.0  
> **Last Updated:** June 2026  
> **Repository Root:** `D:\PROSPEKTLAB`

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [Technology Stack](#3-technology-stack)
4. [Directory Structure](#4-directory-structure)
5. [Frontend Architecture](#5-frontend-architecture)
6. [Backend Architecture](#6-backend-architecture)
7. [API Reference](#7-api-reference)
8. [Data Flows & Workflows](#8-data-flows--workflows)
9. [Multi-Agent Research Engine](#9-multi-agent-research-engine)
10. [Intelligent Knowledge Graph (IKG)](#10-intelligent-knowledge-graph-ikg)
11. [Portfolio Analytics Engine](#11-portfolio-analytics-engine)
12. [Content Automation Engine](#12-content-automation-engine)
13. [Database Schema](#13-database-schema)
14. [State Management](#14-state-management)
15. [Authentication & Security](#15-authentication--security)
16. [Deployment & Infrastructure](#16-deployment--infrastructure)
17. [Configuration Reference](#17-configuration-reference)
18. [Third-Party Integrations](#18-third-party-integrations)
19. [Roadmap & Upcoming Modules](#19-roadmap--upcoming-modules)

---

## 1. Executive Summary

ProspektLab is a multi-surface financial intelligence platform built around three core assets:

1. **FinAgent Research Engine** — a multi-agent / swarm-based equity research system that produces citation-backed memos, interactive canvases, and structured claims.
2. **Intelligent Knowledge Graph (IKG)** — a proprietary Indian corporate knowledge graph sourced from NSE, BSE, SEBI, MCA, annual reports, XBRL, and shareholding patterns.
3. **Portfolio Analytics Engine** — multi-format portfolio ingestion, risk analytics, governance overlay, tax summaries, and AI commentary.

The product is delivered as a **React/Vite/TypeScript SPA** hosted on AWS Amplify, backed by a **FastAPI Python gateway** running on AWS ECS Fargate, with data persistence in **Supabase PostgreSQL** and IKG processing on **Azure VMs**. It supports research chat, deep research, portfolio management, a market screener, content publishing, and governance intelligence.

---

## 2. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     AWS AMPLIFY (Frontend)                          │
│   React 18 + Vite + TypeScript SPA                                  │
│   BrowserRouter, Google OAuth, Razorpay Checkout                    │
│   Azure Application Insights telemetry                              │
└────────────────────────┬────────────────────────────────────────────┘
                         │  HTTPS (API calls + SSE streaming)
                         │
┌────────────────────────▼────────────────────────────────────────────┐
│                  AWS ECS FARGATE (Backend Gateway)                  │
│   FastAPI + Uvicorn (finagent.gateway.run:app)                      │
│                                                                     │
│   ┌──────────────┐ ┌──────────────┐ ┌───────────────────────────┐  │
│   │ Auth Module  │ │ Research     │ │ Portfolio Analytics       │  │
│   │ (JWT+Google) │ │ Swarm + Chat │ │ & Governance Engine       │  │
│   └──────────────┘ └──────────────┘ └───────────────────────────┘  │
│   ┌──────────────┐ ┌──────────────┐ ┌───────────────────────────┐  │
│   │ Content      │ │ Market Data  │ │ Payments (Razorpay)       │  │
│   │ Automation   │ │ APIs         │ │                           │  │
│   └──────────────┘ └──────────────┘ └───────────────────────────┘  │
│   ┌──────────────┐ ┌──────────────┐ ┌───────────────────────────┐  │
│   │ IKG Service  │ │ Screener     │ │ Ops / Control Tower       │  │
│   │ Facade       │ │              │ │                           │  │
│   └──────────────┘ └──────────────┘ └───────────────────────────┘  │
└───┬──────────────┬──────────────┬──────────────┬───────────────────┘
    │              │              │              │
    ▼              ▼              ▼              ▼
┌────────┐  ┌───────────┐  ┌────────────┐  ┌─────────────────────┐
│Supabase│  │Azure VMs  │  │OpenAI /    │  │External Data       │
│        │  │(IKG Stack)│  │Azure / xAI │  │Sources             │
│Postgres│  │           │  │            │  │                    │
│Auth    │  │Postgres 16│  │GPT-5.4-mini│  │Yahoo Finance, SEC  │
│Users   │  │Redis 7    │  │GPT-4o-mini │  │NSE, BSE, SEBI, MCA │
│Payments│  │Qdrant     │  │Grok-3      │  │Reddit, HackerNews  │
│Memory  │  │Celery     │  │            │  │Wikipedia, News RSS │
│        │  │Memgraph*  │  │            │  │                    │
│        │  │Scrapers   │  │            │  │                    │
└────────┘  └───────────┘  └────────────┘  └─────────────────────┘

* Memgraph MAGE is deployed for graph algorithms; the current system-of-record
  graph backend is PostgreSQL (ikg_vertices / ikg_edges) with an in-memory
  fallback for local development.
```

### Multi-Cloud Topology

| Component | Cloud Provider | Service |
|-----------|---------------|---------|
| **Frontend SPA** | AWS | Amplify Hosting |
| **Backend Gateway** | AWS | ECS Fargate |
| **CI/CD** | AWS | CodeBuild + CodePipeline |
| **IKG Pipeline Workers** | Azure | Linux VMs (Docker Compose) |
| **Database** | Supabase | Managed PostgreSQL |
| **Email/SMS** | Azure | Communication Services (ACS) |
| **Monitoring** | Azure | Application Insights + Monitor |

---

## 3. Technology Stack

### Backend — Python 3.11

| Layer | Technology | Version |
|-------|-----------|---------|
| **Web Framework** | FastAPI | 0.100+ |
| **ASGI Server** | Uvicorn | 0.23+ |
| **AI/LLM** | OpenAI SDK, xAI Grok | 1.0+ |
| **Agent Framework** | LangChain/LangGraph (legacy), custom Swarm | 0.2+ |
| **Data Science** | Pandas, NumPy | 2.0+ / 1.24+ |
| **Finance** | yfinance, PyPortfolioOpt | 0.2.40+ |
| **Doc Parsing** | pypdf, PyMuPDF, casparser, msoffcrypto-tool, Azure Doc Intelligence, Docling, MinerU | |
| **Web Scraping** | Patchright (Playwright), crawl4ai, httpx, aiohttp | |
| **Search** | Qdrant (vector), Azure Cognitive Search (hybrid) | |
| **Graph DB** | PostgreSQL adjacency-list (primary), Memgraph MAGE (algorithms) | |
| **Database** | psycopg (PostgreSQL via Supabase) | 3.1+ |
| **Task Queue** | Celery + Redis broker | 5.4+ |
| **Scheduler** | APScheduler | 3.10+ |
| **Auth** | PyJWT, Google Identity Services | 2.0+ |
| **Payments** | Razorpay SDK | 1.4+ |
| **Charts** | Matplotlib | 3.8+ |
| **MCP** | fastmcp | 2.0+ |
| **Testing** | pytest | 8.0+ |

### Frontend — TypeScript

| Layer | Technology | Version |
|-------|-----------|---------|
| **Framework** | React | 18.3.1 |
| **Build Tool** | Vite | 5.2+ |
| **Language** | TypeScript | 5.2+ |
| **Routing** | React Router DOM (BrowserRouter) | 6.23+ |
| **Charts** | Chart.js + react-chartjs-2 + chartjs-chart-treemap | 4.4+ |
| **Icons** | lucide-react | 0.379+ |
| **Auth** | Google Identity Services (GIS) | — |
| **Payments** | Razorpay Checkout | — |
| **Telemetry** | Azure Application Insights | — |

---

## 4. Directory Structure

```
D:\PROSPEKTLAB\
│
├── pyproject.toml                  # Python project config & dependencies
├── uv.lock                         # Python dependency lock file
├── package.json                    # Root-level Node tooling (playwright)
├── Dockerfile                      # Main FastAPI gateway Docker image
├── .python-version                 # 3.11
├── .mcp.json                       # MCP server config (Greptile)
├── opencode.json                   # OpenCode AI config
├── .gitignore / .dockerignore
│
├── README.md                       # (short) Greptile / MCP integration note
├── README-DEPLOYMENT.md
├── AWS-DEPLOYMENT-COMMANDS.sh
├── deploy-production.sh
├── start_server.ps1                # Launcher: FastAPI gateway
├── start_ikg_scheduler.ps1         # Launcher: IKG scheduler
├── run_qdrant_index.py
├── bootstrap_db.py
├── smoke_test.py
├── test_*.py                       # 15+ root-level integration tests
│
├── backend/
│   └── finagent/                   # *** MAIN BACKEND PACKAGE ***
│       ├── __init__.py             # Env loading, SSL certificate fix
│       ├── __main__.py             # python -m finagent entry
│       ├── api.py                  # Standalone chat-only API (/api/chat, /api/chat/stream)
│       ├── cli.py                  # CLI entry point
│       ├── cache.py                # TTL cache (in-memory + Redis fallback)
│       ├── events.py               # Event bus for SSE streaming
│       ├── telemetry.py            # Azure App Insights telemetry
│       ├── telemetry_burner.py     # Batch telemetry sender
│       ├── env.py                  # Env loading helpers
│       ├── paths.py                # File path resolution
│       ├── settings.py             # FinAgentSettings config dataclass
│       ├── runtime_provider.py     # LLM provider resolution (Azure/OpenAI/xAI)
│       ├── run_agent.py            # Legacy research agent loop
│       ├── swarm_research.py       # NEW: swarm-based standard/deep research
│       ├── chat_reply.py           # NEW: lightweight conversational chat mode
│       ├── chat_tools.py           # NEW: finance tool specs for chat
│       ├── research_planner.py     # Research plan builder
│       ├── synthesis.py            # Memo synthesis engine
│       ├── prompt_builder.py       # System prompt builder
│       ├── rich_builder.py         # Rich output builder
│       ├── accuracy_validator.py   # Fact-checking validator
│       ├── intent.py               # Intent detection
│       ├── content_automation.py   # Automated article generation
│       ├── portfolio_mirrors.py    # Portfolio mirror management
│       ├── portfolio_sentinel.py   # Portfolio monitoring
│       │
│       ├── gateway/                # FASTAPI GATEWAY (main server entry)
│       │   ├── run.py              # *** APP DEFINITION *** (all routes)
│       │   ├── auth_guard.py       # JWT auth verification + rate limiting
│       │   ├── supabase_client.py  # Supabase API client
│       │   ├── session.py          # Session record dataclass
│       │   ├── state_store.py      # SQLite state store for tokens/meta
│       │   ├── email_delivery.py   # ACS email delivery
│       │   ├── sms_delivery.py     # ACS SMS delivery
│       │   ├── components/Charts/  # Server-rendered chart components
│       │   └── *.html              # Static HTML templates
│       │
│       ├── agents/                 # MULTI-AGENT ORCHESTRATION
│       │   ├── base.py             # Base subagent class
│       │   ├── blueprint.py        # Agent blueprint builder
│       │   ├── orchestrator.py     # Parallel wave-based orchestrator
│       │   ├── blindspot.py        # Blind-spot detection agent
│       │   ├── grader.py           # Quality grader agent
│       │   ├── verifier.py         # Output verifier agent
│       │   ├── context_loaders.py  # Context loaders per specialist
│       │   └── specialists/        # 10 SPECIALIST AGENTS
│       │       ├── accounting.py
│       │       ├── community.py
│       │       ├── competitor.py
│       │       ├── financials.py
│       │       ├── governance.py
│       │       ├── macro.py
│       │       ├── news.py
│       │       ├── risk.py
│       │       ├── technical.py
│       │       └── valuation.py
│       │
│       ├── swarm/                  # NEW: DYNAMIC SWARM ORCHESTRATION
│       │   ├── __init__.py
│       │   ├── blackboard.py       # EvidenceBlackboard (claims, contradictions, gaps)
│       │   ├── orchestrator.py     # SwarmOrchestrator
│       │   ├── models.py           # SubTask, SubTaskResult, SwarmContext, SwarmPlan
│       │   ├── skills.py           # AgentSkill / SkillRegistry
│       │   ├── supervisor.py       # Supervisor
│       │   ├── runner.py           # Swarm runner
│       │   ├── llm.py              # LLM helpers for swarm
│       │   └── document_agent.py   # Document-aware sub-agent
│       │
│       ├── canvas/                 # NEW: INTERACTIVE RESEARCH CANVAS
│       │   ├── models.py           # InteractiveResearchCanvas, CanvasSection, CanvasClaim
│       │   └── store.py            # CanvasStore + CanvasController (steer)
│       │
│       ├── accuracy/               # NEW: ACCURACY LAYER
│       │   └── layer.py            # AccuracyLayer, AccuracyReport
│       │
│       ├── ikg/                    # INTELLIGENT KNOWLEDGE GRAPH
│       │   ├── service.py          # IKG service facade
│       │   ├── db.py               # IKG database adapter
│       │   ├── schema.py           # IKG schema definition
│       │   ├── entity_resolver.py  # Entity name → CIN resolution
│       │   ├── graph_client.py     # PostgreSQL adjacency-list graph client
│       │   ├── governance_score.py # Forensic governance scoring
│       │   ├── director_network.py # Board interlock analysis
│       │   ├── company_provenance.py
│       │   ├── document_selector.py
│       │   ├── graph_health.py
│       │   ├── staleness.py
│       │   ├── pipeline/           # IKG ETL PIPELINE
│       │   │   ├── scheduler.py
│       │   │   ├── celery_app.py
│       │   │   ├── orchestrator.py
│       │   │   ├── run_store.py
│       │   │   └── company_integrity_audit.py
│       │   └── scrapers/           # 20+ DATA SCRAPERS
│       │       ├── _engine.py
│       │       ├── _nse_session.py
│       │       ├── _proxy_manager.py
│       │       ├── annual_reports.py
│       │       ├── bse_eod.py
│       │       ├── bse_shp.py
│       │       ├── concall_transcripts.py
│       │       ├── corporate_governance_directors.py
│       │       ├── director_kmp_enricher.py
│       │       ├── financial_data.py
│       │       ├── mca_companies.py
│       │       ├── mca_directors.py
│       │       ├── nse_index.py
│       │       ├── sebi_corporate_filings.py
│       │       ├── sebi_enforcement.py
│       │       └── xbrl_utils.py
│       │
│       ├── content/                # CONTENT AUTOMATION ENGINE
│       │   ├── flash_engine.py
│       │   ├── editorial.py
│       │   ├── editorial_calendar.py
│       │   ├── official_monitor.py
│       │   ├── filing_triage.py
│       │   ├── livemint_blocker.py
│       │   ├── livemint_editorial.py
│       │   ├── specialist_agents.py
│       │   └── content_accuracy.py
│       │
│       ├── portfolio/              # PORTFOLIO ANALYTICS ENGINE
│       │   ├── analytics.py
│       │   ├── sectors.py
│       │   ├── news.py
│       │   ├── alerts.py
│       │   ├── stress_test.py
│       │   ├── tax.py
│       │   ├── dividends.py
│       │   ├── corporate_actions.py
│       │   ├── governance_xray.py
│       │   ├── action_queue.py
│       │   ├── holding_detail.py
│       │   ├── commentary.py
│       │   └── mf_analytics.py
│       │
│       ├── output/                 # OUTPUT GENERATION & FORMATTING
│       │   ├── contracts.py
│       │   ├── artifact_builder.py
│       │   ├── chart_generator.py
│       │   ├── renderer.py
│       │   ├── memo_formatter.py
│       │   ├── report_exporter.py
│       │   ├── export_jobs.py
│       │   ├── templates.py
│       │   ├── fact_check.py
│       │   ├── confidence_scorer.py
│       │   ├── conflict_reporter.py
│       │   ├── compliance.py
│       │   ├── output_scrubber.py
│       │   ├── query_guards.py
│       │   └── intent_classifier.py
│       │
│       ├── tools/                  # TOOL ECOSYSTEM
│       │   ├── data/               # Market data fetching tools
│       │   ├── web/                # Web scraping tools
│       │   ├── social/             # Social media tools
│       │   ├── prospektlab/        # ProspektLab-specific tools
│       │   ├── mcp/                # MCP toolkits (ikg_toolkit, etc.)
│       │   ├── mcp_servers/        # MCP servers
│       │   ├── valuation_engine.py
│       │   ├── registry.py
│       │   └── mcp_config.py
│       │
│       ├── router/                 # QUERY ROUTING
│       ├── geo/                    # GEOGRAPHY HANDLING
│       ├── news/                   # NEWS AGGREGATION
│       ├── memory/                 # MEMORY SYSTEM
│       ├── storage/                # STORAGE ADAPTERS
│       ├── ingestion/              # PORTFOLIO DOCUMENT INGESTION
│       ├── retrieval/              # HYBRID RETRIEVAL (RAG)
│       ├── graphrag/               # GRAPH RAG
│       ├── harness/                # AGENT HARNESS
│       ├── state/                  # STATE MANAGEMENT
│       ├── playbooks/              # PLAYBOOK SYSTEM
│       ├── dreaming/               # DREAMING LAYER (offline learning)
│       ├── learning/               # ONLINE LEARNING
│       ├── seo/                    # SEO
│       ├── ops/                    # OPERATIONS
│       ├── analysis/               # ANALYSIS
│       └── prompts/                # SYSTEM PROMPTS
│
├── frontend/                       # REACT FRONTEND (Vite + TypeScript)
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.mjs
│   ├── index.html
│   ├── .env
│   ├── amplify.yml
│   ├── public/
│   │   ├── env-config.js
│   │   └── insights/               # Generated public article HTML
│   └── src/
│       ├── main.tsx
│       ├── App.tsx                 # BrowserRouter + route definitions
│       ├── index.css
│       ├── telemetry.ts
│       ├── api/client.ts           # All backend API calls
│       ├── context/AuthContext.tsx
│       ├── data/indianStocks.ts
│       ├── pages/                  # Page-level routes
│       │   ├── LandingPage.tsx
│       │   ├── GatewayPage.tsx
│       │   ├── ManualEntry.tsx
│       │   ├── UploadPage.tsx
│       │   ├── WatchlistStep.tsx
│       │   ├── Dashboard.tsx
│       │   ├── DashboardOverviewPage.tsx
│       │   ├── DashboardPortfolioPage.tsx
│       │   ├── DashboardWatchlistPage.tsx
│       │   ├── DashboardScreenerPage.tsx
│       │   ├── DashboardEarningsPage.tsx      # Coming Soon
│       │   ├── DashboardGovernancePage.tsx    # Coming Soon
│       │   ├── InsightsStudio.tsx
│       │   ├── Login.tsx / Signup.tsx (currently redirected)
│       │   └── ...
│       ├── components/
│       │   ├── layout/             # AppShell, FeatureTabs, Sidebar, Logo
│       │   ├── chat/               # AgentThinking, ChatInput, MessageBubble, RichResponse, etc.
│       │   ├── charts/             # AreaChart, BarChart, DonutChart, etc.
│       │   ├── dashboard/           # PortfolioTable, WatchlistCard, GovernancePanel, etc.
│       │   ├── screener/          # ScreenerWorkspace
│       │   ├── insights/          # ArticleQueueTable, ArticleReader, DraftReviewDrawer, FlashJobMonitor
│       │   └── common/            # CommandPalette, ProvenanceCard, ComingSoon
│       └── utils/                  # coverArt, etc.
│
├── deployment/                     # INFRASTRUCTURE SCRIPTS
│   ├── Dockerfile.ikg-worker
│   ├── docker-compose.ikg.yml
│   ├── requirements.ikg-worker.txt
│   ├── fargate-backend.yml
│   ├── azure_vm_*.sh
│   ├── azure-monitoring.bicep
│   └── *.sql / migrate_*.py
│
├── supabase/                       # SUPABASE DATABASE MIGRATIONS
│   ├── config.toml
│   └── migrations/
│       ├── 20260603080031_sebi_verified_leads.sql
│       ├── 20260603081825_prospektlab_core_tables.sql
│       ├── 20260603091459_grant_service_role_public_schema.sql
│       ├── 20260606054201_outreach_personalized_setup.sql
│       ├── 20260606175500_public_outreach_unsubscribe_rpc.sql
│       ├── 20260606210500_outreach_unsubscribes.sql
│       └── 20260613180000_subscription_payments.sql
│
├── outreach/                       # OUTREACH / LEAD GEN MODULE
│   ├── config.example.json
│   ├── leads.sample.csv
│   ├── suppression.sample.csv
│   ├── Dockerfile.azure
│   ├── scripts/
│   └── templates/
│
├── scripts/                        # UTILITY SCRIPTS
├── data/                           # STATIC DATA
├── .github/                        # GitHub Actions workflows
├── .finagent/                      # Agent runtime state directory
└── audit_logs/ / cache/ / pipeline_logs/
```

---

## 5. Frontend Architecture

### 5.1 Routing

The frontend uses **React Router DOM `BrowserRouter`** (not HashRouter in the current build). The route map in `frontend/src/App.tsx` is:

| Route | Page | Access |
|-------|------|--------|
| `/` | `LandingPage` | Public |
| `/pricing`, `/testimonials`, `/features`, `/contact` | Redirect → `/dashboard/overview` | Public |
| `/get-started` | `GatewayPage` | Public (onboarding) |
| `/onboarding/manual` | `ManualEntry` | Public |
| `/onboarding/upload` | `UploadPage` | Public |
| `/onboarding/watchlist` | `WatchlistStep` | Public |
| `/login`, `/signup` | Redirect → `/dashboard/overview` | Public (currently disabled in open-access mode) |
| `/dashboard` | Redirect → `/dashboard/overview` | Public |
| `/dashboard/:featureTab` | `Dashboard` with tab | Public |
| `/dashboard/earnings` | `DashboardEarningsPage` | Public (Coming Soon) |
| `/dashboard/governance` | `DashboardGovernancePage` | Public (Coming Soon) |
| `/insights-studio` | `InsightsStudio` | Public |
| `*` | Redirect → `/dashboard/overview` | Public |

### 5.2 Dashboard Feature Tabs

The main workspace in `Dashboard.tsx` is organized into tabs defined by `FeatureTabs`:

- **Overview** — market indices, quick pulse, portfolio summary, news, research chat
- **Portfolio** — portfolio table, allocation, analytics, governance overlay
- **Watchlist** — custom watchlist workspace
- **Screener** — company discovery and analysis
- **Earnings** — placeholder / coming soon (June 2026)
- **Governance** — placeholder / coming soon (June 2026)

### 5.3 Component Hierarchy

```
App (BrowserRouter)
│
├── AuthProvider (React Context)
│   ├── user, token, isAuthenticated, isOnboarded
│   ├── login(), logout(), refreshUser()
│   └── Toast notifications
│
├── TelemetryRouteTracker
│   └── Tracks page views via Azure App Insights
│
├── CommandPalette (global, Ctrl+K)
│
└── Routes
    │
    ├── /            → LandingPage
    ├── /get-started → GatewayPage
    ├── /onboarding/* → ManualEntry / UploadPage / WatchlistStep
    ├── /dashboard/* → Dashboard
    │   └── AppShell
    │       ├── Sidebar
    │       ├── FeatureTabs
    │       └── Content Area
    │           ├── DashboardOverviewPage
    │           ├── DashboardPortfolioPage
    │           ├── DashboardWatchlistPage
    │           ├── DashboardScreenerPage
    │           ├── DashboardEarningsPage (ComingSoon)
    │           └── DashboardGovernancePage (ComingSoon)
    │
    └── /insights-studio → InsightsStudio
```

### 5.4 API Client

`frontend/src/api/client.ts` (~2200+ lines) is the single point of contact with the backend. It exports:

- Auth helpers
- `startResearch`, `streamSession`, `stopSession`, `getSessionResult`, `getSessionCanvas`, `steerCanvas`
- Portfolio helpers: `getPortfolioMirror`, `replacePortfolioMirror`, `syncManualPortfolio`, `uploadCas`, `uploadDocument`, `uploadScreenshot`, `confirmExtraction`, `getPortfolioAnalytics`, `getPortfolioGovernance`, `postStressTest`, etc.
- Market helpers: `getMarketIndices`, `getMarketQuotes`, `getMarketHistory`, `getMarketNews`, `getScreenerSearch`, `getScreenerSnapshot`, etc.
- Content helpers: `listContentArticles`, `generateArticle`, `publishArticle`, etc.

---

## 6. Backend Architecture

### 6.1 Gateway

`backend/finagent/gateway/run.py` is the central FastAPI application containing **125+ route declarations**. It covers the entire product surface:

- Auth (Google, email/password, OTP, password reset)
- Research (`/research/start`, `/research/deep`, `/chat/research`)
- Session management (`/sessions/{id}/stop`, `/sessions/{id}/result`, `/sessions/{id}/stream`, `/sessions/{id}/memo`, `/sessions/{id}/canvas`, `/sessions/{id}/canvas/steer`)
- Market data (`/market/history`, `/market/quotes`, `/market/news`, `/market/indices`, `/public/market/ticker`)
- Screener (`/screener/search`, `/screener/company/{identifier}/snapshot`, `/screener/company/{identifier}/financials`, `/screener/company/{identifier}/technicals`, `/screener/company/{identifier}/events`, `/screener/company/{identifier}/analyze`, `/screener/query`)
- Portfolio (mirror, upload, analytics, governance, news, sectors, tax, dividends, stress-test, mf-analytics, today, brief, commentary)
- Watchlist (`/watchlist/snapshot`)
- IKG (`/company/{cin}/governance`, `/company/{cin}/network`, `/company/{cin}/provenance`, `/company/{cin}/health`, `/company/{cin}/staleness`, `/admin/ikg/health`, `/filings/triage`)
- Memory (`/memory/stats`, `/memory/facts`, `/memory/sessions`, `/memory/clear/{target}`)
- Content automation (`/api/content/articles/*`, `/api/content/flash/*`, `/api/content/automation/*`)
- Payments (`/api/create-order`, `/api/verify-payment`, `/user/subscription`, `/user/token-usage`, `/user/upgrade-plan`)
- Ops (`/ops`, `/api/ops/control-tower`, `/metrics/snapshot`)
- Static pages (`/landing`, `/login`, `/signup`, `/onboarding`, `/dashboard`, `/insights-studio`, `/profile`, `/settings`, `/app`, `/ops`, `/unsubscribe`)

`backend/finagent/api.py` exposes a smaller standalone chat API (`/api/chat`, `/api/chat/stream`, `/api/health/mcp`) for independent use.

### 6.2 Core Subsystems

| Subsystem | Entry Point | Responsibility |
|-----------|-------------|----------------|
| **Swarm Research** | `swarm_research.py` | New standard/deep research orchestration using `SwarmOrchestrator` + `EvidenceBlackboard` |
| **Legacy Research** | `run_agent.py` | Original single-pipeline research loop; still used for chat/lightweight flows |
| **Conversational Chat** | `chat_reply.py` + `chat_tools.py` | Fast, direct chat answers with optional tool use for live market data |
| **Interactive Canvas** | `canvas/models.py` + `canvas/store.py` | Living research document with sections, claims, contradictions, gaps, user steers |
| **Accuracy Layer** | `accuracy/layer.py` | Source verification, contradiction detection, uncertainty quantification, gap filling |
| **IKG Service** | `ikg/service.py` | Unified provenance-first company bundle facade |
| **Portfolio Analytics** | `portfolio/analytics.py` | Returns, risk metrics, benchmark analytics, NAV history |
| **Content Automation** | `content/flash_engine.py` + `content_automation.py` | Flash articles, editorial review, publish gating |
| **Auth Guard** | `gateway/auth_guard.py` | JWT verification, rate limiting, session ownership |
| **Telemetry** | `telemetry.py` + `telemetry_burner.py` | Azure Application Insights ingestion |

---

## 7. API Reference

### 7.1 Authentication

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/auth/google` | None | Google OAuth sign-in → verify tokeninfo → mint JWT |
| `POST` | `/auth/google/update-mobile` | JWT | Update user mobile number |
| `POST` | `/auth/signup` | None | Email + password signup via Supabase Auth Admin |
| `POST` | `/auth/login` | None | Email + password login → JWT issued |
| `POST` | `/auth/logout` | None | Clear `prospektlab_token` httpOnly cookie |
| `POST` | `/auth/send-verification` | None | Send OTP via email (ACS) or SMS (ACS) |
| `POST` | `/auth/forgot-password` | None | Request password reset → email code |
| `POST` | `/auth/reset-password` | None | Verify code → update password |
| `GET` | `/auth/me` | JWT | Return user + plan + usage stats |

> **Note:** In the current open-access build, `/login` and `/signup` frontend routes redirect to `/dashboard/overview`. The backend auth endpoints remain in place for gated deployments.

### 7.2 Research & Sessions

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/research/start` | JWT + Token check | Start standard research |
| `POST` | `/research/deep` | JWT + Token + Deep quota | Start deep multi-pass research |
| `POST` | `/chat/research` | JWT + Token check | Chat-UI friendly research wrapper |
| `POST` | `/sessions/{id}/stop` | JWT + Ownership | Cancel running session |
| `DELETE` | `/sessions/{id}` | JWT + Ownership | Delete session + artifacts |
| `GET` | `/sessions/{id}/status` | JWT + Ownership | Poll session status |
| `GET` | `/sessions/{id}/events` | JWT + Ownership | Poll events with `?after=<cursor>` |
| `GET` | `/sessions/{id}/result` | JWT + Ownership | Get final synthesized result |
| `GET` | `/sessions/{id}/stream` | JWT + Ownership | **SSE** event stream |
| `GET` | `/sessions/{id}/memo` | JWT + Ownership | Get memo in Markdown |
| `GET` | `/sessions/{id}/canvas` | JWT + Ownership | Get interactive research canvas |
| `POST` | `/sessions/{id}/canvas/steer` | JWT + Ownership | Apply user steer to canvas |
| `POST` | `/research/export` | JWT + Ownership | Export research as PDF/DOCX/XLSX |
| `POST` | `/research/export-all` | JWT + Ownership | Bulk export sessions |
| `GET` | `/research/export/{job_id}` | JWT | Check export job status |
| `GET` | `/research/export/{job_id}/download` | JWT | Download completed export |
| `GET` | `/memos` | JWT | List saved memos |
| `GET` | `/chat/history` | JWT | Get chat history |
| `GET` | `/memory/stats` | JWT | Memory usage statistics |
| `GET` | `/memory/facts` | JWT | Browse stored memory facts |
| `GET` | `/memory/sessions` | JWT | List session summaries |
| `DELETE` | `/memory/clear/{target}` | JWT | Clear facts for a specific entity |

### 7.3 Portfolio

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/portfolio/mirror` | JWT | Get current portfolio positions |
| `POST` | `/portfolio/mirror` | JWT | Replace all portfolio positions |
| `DELETE` | `/portfolio/mirror` | JWT | Clear all positions |
| `POST` | `/portfolio/mirror/sync-manual` | JWT | Sync manually entered positions with Yahoo |
| `POST` | `/api/portfolio/upload-cas` | JWT | Upload CAS/eCAS PDF |
| `POST` | `/api/portfolio/upload-document` | JWT | Upload any portfolio document |
| `POST` | `/portfolio/mirror/ecas` | JWT | Upload eCAS PDF specifically |
| `POST` | `/api/portfolio/upload-screenshot` | JWT | Upload portfolio screenshot (GPT-4o Vision) |
| `POST` | `/api/portfolio/confirm-extraction` | JWT | Confirm reviewed extraction → save to mirror |
| `POST` | `/api/portfolio/cancel-extraction` | JWT | Cancel/reject pending extraction |
| `GET` | `/portfolio/analytics` | JWT | Full portfolio analytics |
| `GET` | `/portfolio/governance` | JWT | Governance X-Ray overlay |
| `GET` | `/portfolio/news` | JWT | Portfolio-specific news |
| `GET` | `/portfolio/sectors` | JWT | Sector/sub-sector breakdown |
| `GET` | `/portfolio/holding/{symbol}` | JWT | Deep-dive on single holding |
| `GET` | `/portfolio/corporate-actions` | JWT | Recent/upcoming corporate actions |
| `GET` | `/portfolio/alerts` | JWT | Computed alerts & warnings |
| `GET` | `/portfolio/tax-summary` | JWT | Tax summary (LTCG/STCG India) |
| `GET` | `/portfolio/dividends` | JWT | Dividend history & calendar |
| `POST` | `/portfolio/stress-test` | JWT | Monte Carlo stress test scenarios |
| `GET` | `/portfolio/mf-analytics` | JWT | Mutual fund-specific analytics |
| `GET` | `/portfolio/today` | JWT | Daily action queue |
| `GET` | `/portfolio/brief` | JWT | Portfolio summary brief |
| `GET` | `/portfolio/commentary` | JWT | AI-generated portfolio commentary |

### 7.4 Market Data & Screener

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/watchlist/snapshot` | JWT | Watchlist quote snapshot |
| `GET` | `/market/history` | JWT | Price history (1M/3M/6M/YTD/1Y/MAX) |
| `GET` | `/market/quotes` | Optional JWT | Real-time stock quotes |
| `GET` | `/market/news` | Optional JWT | Market-wide news headlines |
| `GET` | `/market/indices` | Optional JWT | Real-time indices |
| `GET` | `/public/market/ticker` | None | Public ticker data |
| `GET` | `/screener/search` | JWT | Company search |
| `GET` | `/screener/company/{identifier}/snapshot` | JWT | Company snapshot |
| `GET` | `/screener/company/{identifier}/financials` | JWT | Financials view |
| `GET` | `/screener/company/{identifier}/technicals` | JWT | Technicals view |
| `GET` | `/screener/company/{identifier}/events` | JWT | Events view |
| `GET` | `/screener/company/{identifier}/analyze` | JWT | Analysis run |
| `POST` | `/screener/query` | JWT | Structured screener query |

### 7.5 Company Intelligence (IKG)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/company/{cin}/governance` | JWT | Forensic governance score |
| `GET` | `/company/{cin}/network` | JWT | Director board interlock network |
| `GET` | `/company/{cin}/provenance` | JWT | Citation-backed company facts |
| `GET` | `/company/{cin}/health` | JWT | Graph completeness/health |
| `GET` | `/company/{cin}/staleness` | JWT | Data freshness verdict |
| `GET` | `/admin/ikg/health` | JWT + Admin | IKG corpus health dashboard |
| `POST` | `/filings/triage` | JWT | Classify filings by materiality |

### 7.6 Content Automation

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/content/articles/generate` | JWT | Generate single article |
| `POST` | `/api/content/articles/generate-batch` | JWT | Batch article generation |
| `POST` | `/api/content/events/ingest` | JWT | Ingest market/regulatory events |
| `GET` | `/api/content/articles` | Optional | List articles (published + draft) |
| `GET` | `/api/content/articles/{slug}` | JWT | Get article JSON |
| `GET` | `/api/content/articles/{slug}/html` | None | Get published article HTML |
| `POST` | `/api/content/articles/{slug}/publish` | JWT | Publish article |
| `POST` | `/api/content/articles/{slug}/unpublish` | JWT | Unpublish article |
| `POST` | `/api/content/flash/generate` | JWT | Start flash content generation |
| `POST` | `/api/content/flash/ingest-events` | JWT | Flash event ingestion |
| `GET` | `/api/content/automation/status` | JWT | Automation pipeline status |
| `POST` | `/api/content/automation/run-now` | JWT | Trigger official monitor sweep |

### 7.7 Payments & Ops

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/create-order` | JWT | Create Razorpay order |
| `POST` | `/api/verify-payment` | JWT | Verify Razorpay signature |
| `GET` | `/user/subscription` | JWT | Current plan + quota |
| `GET` | `/user/token-usage` | JWT | Weekly LLM token consumption |
| `POST` | `/user/upgrade-plan` | JWT | Admin-only: upgrade plan |
| `GET` | `/ops/control-tower` | Optional | Control tower dashboard UI |
| `GET` | `/api/ops/control-tower` | Optional | Control tower API data |
| `GET` | `/metrics/snapshot` | JWT + Admin | DAU/MAU/retention snapshot |
| `POST` | `/api/outreach/unsubscribe` | Rate-limited | Email unsubscribe |
| `POST` | `/admin/reset-all-portfolios` | JWT + Admin Key | Wipe all portfolios |

### 7.8 Standalone Chat API

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/chat` | JWT | Standalone chat (JSON) |
| `POST` | `/api/chat/stream` | JWT | Standalone chat (SSE) |
| `GET` | `/api/health/mcp` | None | MCP health check |

---

## 8. Data Flows & Workflows

### 8.1 Standard / Deep Research (Swarm Path)

```
User Query
    │
    ▼
POST /chat/research or /research/deep
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  FastAPI Gateway                                        │
│  1. JWT + rate limit + token budget check              │
│  2. Intent classification (portfolio scope / compare)   │
│  3. Create SessionRecord + EventBus + CanvasStore      │
│  4. Launch swarm_research in background task            │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Swarm Research Engine (swarm_research.py)              │
│                                                         │
│  Phase 1: ENRICHMENT (parallel asyncio)                 │
│    - Yahoo Finance quote                                │
│    - NSE/BSE India snapshot                             │
│    - News fetch                                         │
│    - SEBI filing                                        │
│    - Shareholding pattern                               │
│    - FX (USDINR)                                        │
│    - IKG company bundle                                 │
│                                                         │
│  Phase 2: SWARM (EvidenceBlackboard)                    │
│    - Spawn specialist sub-agents via SwarmOrchestrator  │
│    - Financials, Valuation, Risk, Governance, News,   │
│      Competitor, Macro, Technical, Accounting           │
│    - Ingest claims, findings, sources into blackboard   │
│                                                         │
│  Phase 3: ACCURACY LAYER                                │
│    - Verify claims against sources                      │
│    - Detect numeric contradictions                    │
│    - Quantify uncertainty                               │
│    - Fill gaps                                          │
│                                                         │
│  Phase 4: SYNTHESIS                                     │
│    - Build InteractiveResearchCanvas                    │
│    - Generate memo fallback                             │
│    - Emit events (progress, citation, chart, result)    │
│                                                         │
│  Phase 5: USER STEER (optional)                         │
│    - POST /sessions/{id}/canvas/steer                   │
│    - CanvasController spawns follow-up subtasks         │
└─────────────────────────────────────────────────────────┘
```

### 8.2 Conversational Chat Flow

```
User asks a quick market question
    │
    ▼
POST /chat/research with mode=chat
    │
    ▼
chat_reply.py
    - Resolve entity
    - Optionally call chat_tools (get_quote, get_shareholding, get_governance,
      get_filings, get_news, web_search)
    - Stream direct answer over SSE
    - Persist to session memo
```

Chat mode is deliberately **not** a full research memo: it answers directly, no formal report scaffolding, no charts/tables, and no buy/sell recommendations.

### 8.3 Portfolio Onboarding Flow

```
Landing / Get Started → Manual Entry / Upload / Watchlist
    │
    ▼
Parsing Pipeline:
  - CAS PDF → casparser
  - PDF → PyMuPDF / Azure DI
  - CSV/XLSX → pandas / openpyxl
  - Screenshot → GPT-4o Vision
    │
    ▼
ISIN Resolution → NSE/BSE symbols
    │
    ▼
Extraction Review → Confirm → Portfolio Mirror (Supabase)
    │
    ▼
Dashboard
```

### 8.4 Content Automation Flow

```
Official Monitor (every 30 min)
  ┌──────┐ ┌──────┐ ┌─────┐
  │ SEBI │ │ BSE  │ │ NSE │  ← RSS + scrapers
  └──────┘ └──────┘ └─────┘
       │
       ▼
Filing Triage → materiality score 0-1
       │
       ▼
Flash Content Engine → structured article
       │
       ▼
Editorial Review (dedupe, accuracy, SEO)
       │
       ▼
Publish → insights/ HTML + sitemap + Google Search Console
```

### 8.5 IKG Data Pipeline

```
APScheduler (Cron)
  Every 6h  ──▶ NSE Corporate Filings
  Every 12h ──▶ BSE Announcements
  Every 24h ──▶ SEBI Enforcement Orders
  Every 24h ──▶ MCA Director/Company Data
  Quarterly ──▶ Shareholding Pattern
  Daily     ──▶ BSE EOD Data
  Weekly    ──▶ Annual Report Extraction
  Weekly    ──▶ Governance Score Recompute
       │
       ▼
Celery Worker Pool (10 threads, multi-queue)
       │
       ▼
PostgreSQL 16 (IKG system of record)
  - ikg_vertices / ikg_edges (graph)
  - company master, directors, financial facts
  - shareholding, enforcement, XBRL facts
  - annual reports, index constituents
       │
       ▼
Qdrant (vector search) + Memgraph MAGE (graph algorithms)
```

---

## 9. Multi-Agent Research Engine

### 9.1 Research Modes

| Mode | Entry | Use Case | Engine |
|------|-------|----------|--------|
| **Chat** | `/chat/research` `mode=chat` | Quick, conversational answers | `chat_reply.py` + optional tools |
| **Standard** | `/chat/research` `mode=standard` | Citation-backed research memo | `swarm_research.py` |
| **Deep** | `/research/deep` | Marathon, multi-pass research | `swarm_research.py` with extended budget |
| **Legacy** | `/research/start` | Direct control over parameters | `run_agent.py` |

### 9.2 Swarm Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    SwarmOrchestrator                     │
│  (backend/finagent/swarm/orchestrator.py)                │
│                                                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │  EvidenceBlackboard                               │   │
│  │  - Claims (text, source, confidence, metrics)     │   │
│  │  - Contradictions                                │   │
│  │  - Gaps                                           │   │
│  └─────────────────────────────────────────────────┘   │
│                                                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │  SubTask → AgentSkill → SkillRegistry            │   │
│  │  Dynamic dispatch based on query intent          │   │
│  └─────────────────────────────────────────────────┘   │
│                                                          │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Supervisor → monitors / re-plans / cancels      │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 9.3 Specialist Agents

The 10 legacy specialist agents still feed into the swarm blackboard:

| Agent | Domain | Key Outputs |
|-------|--------|-------------|
| **Financials** | P&L, BS, CF | Revenue CAGR, margins, ROE/ROCE, FCF yield |
| **Valuation** | DCF, multiples | Intrinsic value, P/E range, EV/EBITDA, DCF sensitivity |
| **Risk** | Risk factors | Beta, VaR, concentration, regulatory, operational |
| **Governance** | Corporate governance | Board composition, RPT, SEBI orders, promoter pledges |
| **Competitor** | Peer comparison | Market share, moat analysis, positioning |
| **Macro** | Macroeconomic | GDP linkage, rate sensitivity, currency, sector outlook |
| **News** | News sentiment | Sentiment score, event timeline, market impact |
| **Technical** | Price action | Support/resistance, RSI, MACD, moving averages |
| **Accounting** | Forensic accounting | Red flags, earnings quality, auditor opinion |
| **Community** | Social sentiment | Reddit/HN/StockTwits sentiment, retail interest |

### 9.4 Accuracy Layer

`backend/finagent/accuracy/layer.py` runs after the swarm pass:

1. **Source verification** — claims without sources are downgraded to LOW confidence.
2. **Contradiction detection** — numeric mismatches across claims are flagged and resolved by source strength.
3. **Gap detection** — thin domains (`financials`, `governance`, `risk`, `valuation`, `news`) are flagged for follow-up.
4. **Uncertainty quantification** — confidence is re-labeled based on source diversity and domain heuristics.

### 9.5 Interactive Canvas

`InteractiveResearchCanvas` is a living research document with:

- `phases`: `[plan, enrich, swarm, verify, synthesize, export]`
- `tasks`: per-agent status list
- `sections`: `Financial Analysis`, `Valuation`, `Governance & Forensics`, `Risks & Red Flags`, `Macro & Sector Overlay`, `News & Sentiment`, `Competitive Landscape`, etc.
- `claims`: structured evidence with sources, confidence, metrics, uncertainty notes, contradiction IDs
- `citations`: accumulated sources
- `user_steers`: user follow-up commands that generate new subtasks

The canvas is persisted via `CanvasStore` and can be steered via `POST /sessions/{id}/canvas/steer`.

### 9.6 LLM Provider Resolution

```python
# runtime_provider.py
- Sub-agents:     OpenAI GPT-5.4-mini → Azure Foundry → xAI Grok-3
- Synthesis:      OpenAI GPT-5.4-mini → Azure Foundry
- Light tasks:    OpenAI GPT-4o-mini
- Embeddings:     OpenAI text-embedding-3-small
```

---

## 10. Intelligent Knowledge Graph (IKG)

### 10.1 Overview

The IKG is a comprehensive knowledge base of Indian companies. Current implementation:

- **Relational system of record:** PostgreSQL 16 (`ikg_vertices`, `ikg_edges`, plus staging tables).
- **In-memory fallback:** for local development when `IKG_BACKEND=memory`.
- **Vector embeddings:** Qdrant for semantic search over documents.
- **Graph algorithms:** Memgraph MAGE deployed on Azure VMs for traversal, PageRank, betweenness, community detection, and shortest-path enforcement proximity.

### 10.2 Current Production Coverage (Live, June 2026)

| Table | Rows | Note |
|-------|------|------|
| `ikg_company_master` | 3,138,081 | Full MCA India registry |
| `ikg_facts` | 89,737 | Time-stamped fact store |
| `document_sections` | 45,548 | Chunked filings/reports |
| `shp_raw` (shareholding) | 15,441 | Pledge source — strong |
| `annual_reports_raw` | 1,952 | |
| `enforcement_raw` (SEBI) | 467 | |
| `auditor_history_raw` | 372 | |
| `directors_raw` | 4,993 | 451 companies, 4,035 DINs |
| Graph vertices | 46,835 | |
| Graph edges | 39,208 | |
| Companies promoted to graph | 1,271 | |

### 10.3 Graph Edge Labels

| Edge | Count | Dimension | Health |
|------|-------|-----------|--------|
| `OWNS_STAKE_IN` | 11,846 | Pledge / ownership | Strong |
| `ISSUED` (regulator→order) | 467 | Enforcement | OK |
| `AUDITOR_OF` | 116 | Auditor | Thin |
| `DIRECTOR_OF` | 175 | Director network | Thin |
| `ENFORCEMENT_ACTION_AGAINST` | 11 | Enforcement proximity | Very thin |
| `RELATED_PARTY_TRANSACTION` | 0 | RPT density | Missing |

### 10.4 Data Sources

| Source | Data | Frequency |
|--------|------|-----------|
| **NSE Corporate Filings** | Financial results, press releases, announcements | Every 6 hours |
| **BSE Announcements** | Same as NSE + additional filings | Every 12 hours |
| **SEBI Enforcement** | Orders, adjudications, settlements | Daily |
| **MCA** | Company master data, director details | Daily |
| **Annual Reports** | Full PDF extraction via Docling + Azure DI | Weekly |
| **XBRL Filings** | Structured financial facts | Weekly |
| **Shareholding Patterns** | Promoter, FII, DII, public holdings | Quarterly |
| **BSE EOD Data** | Daily prices, volumes, market cap | Daily |
| **Conference Call Transcripts** | Management commentary | Event-driven |

### 10.5 Governance Scoring

Current `governance_score.py` is a deterministic rules engine:

| Dimension | Weight | Signals |
|-----------|--------|---------|
| Regulatory / SEBI orders | 30% | Penalties, bans, warnings |
| Related-party transactions | 20% | RPT density |
| Promoter pledge | 15% | Pledged promoter % |
| Board independence | 20% | Independent directors, tenure |
| Auditor quality | 10% | Qualified opinions, auditor changes |
| Earnings quality | 5% | Accrual ratios, red flags |

Score bands: 80-100 Excellent (Green), 60-79 Fair (Yellow), 40-59 Warning (Orange), 0-39 Red Flag (Red).

### 10.6 IKG Service Consumers

The IKG is consumed by:

- `agents/context_loaders.py` and `agents/base.py` — inject IKG bundle into specialists.
- `tools/mcp_servers/ikg_server.py` — 24 MCP tools for agent reasoning.
- `portfolio/governance_xray.py` — portfolio-level governance overlay.
- `content/flash_engine.py` and `content/official_monitor.py` — governance content.
- `gateway/run.py` — HTTP endpoints.
- `dreaming/worker.py` — writes candidate facts back into IKG.
- `swarm_research.py` — loads IKG bundle during enrichment.

---

## 11. Portfolio Analytics Engine

### 11.1 Core Modules

```
portfolio/
├── analytics.py          # Returns, risk metrics, allocation, NAV history
├── sectors.py            # Sector/sub-sector classification
├── news.py               # Per-holding + portfolio-level news
├── alerts.py             # Rule-based alert computation
├── stress_test.py        # Monte Carlo + historical scenarios
├── tax.py                # Indian capital gains tax (LTCG/STCG)
├── dividends.py           # Yield, history, calendar
├── corporate_actions.py  # Bonus, splits, buybacks
├── governance_xray.py     # IKG governance overlay per holding
├── action_queue.py        # Daily recommended actions
├── holding_detail.py      # Single holding deep dive
├── commentary.py          # LLM natural-language portfolio review
└── mf_analytics.py        # Mutual fund analysis
```

### 11.2 Current Metrics

- Portfolio value, day change P&L, total returns, XIRR
- Beta, annualized volatility, max drawdown, Sharpe, Sortino, Calmar, VaR/CVaR, HHI, top-5 concentration
- Sector / sub-sector allocation
- Governance X-Ray per holding and portfolio-weighted exposure
- Tax summary (STCG/LTCG split, estimated liability, harvest-opportunity list)
- Dividend tracking & yield
- Corporate actions calendar
- AI-generated portfolio commentary
- Daily action queue (alerts, corp actions, news, movers)

### 11.3 Multi-Format Ingestion

Supported document types:

- CAS / eCAS PDF (CAMS/Kfintech)
- Generic PDF brokerage statements
- CSV / XLSX position files
- Portfolio screenshots (GPT-4o Vision)
- Manual entry

ISIN resolution maps to NSE/BSE symbols. Validation rules in `portfolio_guardrails.py`.

---

## 12. Content Automation Engine

### 12.1 Flash Content Engine

`content/flash_engine.py` (~4979 lines) generates research articles from official filings:

1. Monitor official sources (SEBI/BSE/NSE RSS)
2. Ingest new filings/announcements
3. Filing Triage → materiality classification
4. Research context → company background, sector, peers
5. Article generation → LLM produces structured article
6. Editorial review → accuracy, originality, SEO checks
7. Cover image → DALL-E prompt generation
8. Publish → write HTML, update sitemap, submit to Google Search Console

### 12.2 Article Structure

```json
{
  "slug": "tcs-q4-fy2025-results-analysis",
  "headline": "TCS Q4 FY2025: Revenue Hits ₹62,000 Cr, Margins Expand to 26%",
  "summary": "...",
  "sections": [
    { "heading": "Revenue Analysis", "content": "...", "chart": {...} },
    { "heading": "Margin Analysis", "content": "...", "callout": {...} },
    { "heading": "Segment Performance", "content": "...", "table": {...} },
    { "heading": "Market Reaction", "content": "...", "metric_cards": [...] }
  ],
  "citations": [...],
  "seo": { "meta_description": "...", "keywords": [...], "cover_image_alt": "..." }
}
```

### 12.3 Editorial Gating

`content/editorial.py` performs:

- Livemint duplicate detection (`livemint_blocker.py`)
- Accuracy validation (`content_accuracy.py`)
- SEO metadata generation
- Draft status before publish

---

## 13. Database Schema

### 13.1 Supabase (User-Facing PostgreSQL)

```sql
-- profiles: Core user table
CREATE TABLE public.profiles (
  id UUID PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  full_name TEXT,
  auth_provider TEXT,           -- 'google' | 'email'
  mobile TEXT,
  plan TEXT DEFAULT 'free',     -- 'free' | 'pro' | 'enterprise'
  avatar_url TEXT,
  referral_source TEXT,
  onboarding_status TEXT DEFAULT 'pending',
  onboarded_at TIMESTAMPTZ,
  deep_runs_used INTEGER DEFAULT 0,
  deep_runs_period_start TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- token_usage: Weekly LLM token tracking
CREATE TABLE public.token_usage (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID REFERENCES profiles(id),
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  model TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- subscription_payments: Razorpay transactions
CREATE TABLE public.subscription_payments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id),
  razorpay_order_id TEXT,
  razorpay_payment_id TEXT,
  razorpay_signature TEXT,
  amount INTEGER,               -- in paise (INR)
  currency TEXT DEFAULT 'INR',
  plan_id TEXT,
  plan_name TEXT,
  status TEXT,                  -- 'created' | 'paid' | 'failed'
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- contacts: Scraped financial advisor / lead records
CREATE TABLE public.contacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT,
  email TEXT,
  raw_email TEXT,
  email_status TEXT,
  email_confidence DOUBLE PRECISION,
  email_normalized TEXT,
  phone TEXT,
  linkedin_url TEXT,
  designation TEXT,
  organisation TEXT,
  sebi_reg_number TEXT,
  sebi_reg_type TEXT,
  amfi_arn TEXT,
  priority_score DOUBLE PRECISION,
  extraction_confidence DOUBLE PRECISION,
  intent_signals JSONB DEFAULT '{}',
  primary_source TEXT,
  opted_out BOOLEAN DEFAULT FALSE,
  data_sources JSONB DEFAULT '[]',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- scrape_jobs / scrape_checkpoints / extraction_rules
-- Background scraping and data extraction job management

-- export_jobs: Document export tracking
CREATE TABLE public.export_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id),
  session_id TEXT,
  format TEXT,                  -- 'pdf' | 'docx' | 'xlsx'
  status TEXT DEFAULT 'pending',
  file_path TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- verification_codes: Auth OTPs
CREATE TABLE public.verification_codes (
  id BIGSERIAL PRIMARY KEY,
  email TEXT,
  mobile TEXT,
  code TEXT,
  purpose TEXT,                 -- 'signup' | 'login' | 'reset'
  expires_at TIMESTAMPTZ,
  used BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- outreach_* tables: campaigns, leads, messages, events, replies, unsubscribes
-- payments table: Razorpay verification and plan billing
```

### 13.2 IKG Database (PostgreSQL 16 — Separate Instance)

Key tables and graph schema:

```sql
-- Graph system of record
ikg_vertices (vertex_id PK, label, properties JSONB)
ikg_edges (id PK, from_vertex_id, to_vertex_id, label, properties JSONB)

-- Company master data
ikg_company_master (cin, name, status, incorporation_date, category, ...)

-- Directors and KMP
directors_raw (din, name, designation, appointment_date, cin)

-- Financial facts from XBRL
ikg_facts (id, cin, fact_id, concept, value, unit, period, filing_date, source_url)

-- Shareholding patterns
shp_raw (cin, quarter, owner_vertex_id, owner_name, holding_pct, pledge_pct, source_url)

-- SEBI enforcement
enforcement_raw (order_id, date, cin, company_name, type, penalty_amount, summary, url)

-- Annual reports
annual_reports_raw (cin, year, source_url, extracted_text, key_findings)

-- Index constituents
index_constituents (index_name, symbol, isin, weight, effective_date)

-- Governance scores
ikg_governance_scores (cin, score, regulatory_sub_score, board_sub_score,
                     rpt_sub_score, promoter_sub_score, computed_at)
```

---

## 14. State Management

### 14.1 Backend State

| Store | Technology | Scope | Persistence |
|-------|-----------|-------|-------------|
| **Session Store** | In-memory dict + JSON files | Per session | Disk (JSON), volatile on restart |
| **Event Bus** | `asyncio.Queue` per session + JSONL | Per session | Disk (JSONL), capped |
| **Canvas Store** | JSON files | Per session | Disk, durable |
| **Memory Store** | Tiered (episodic/semantic/procedural) | Per user | Supabase / SQLite fallback |
| **Portfolio Mirror** | PostgreSQL (Supabase) | Per user | Durable |
| **TTL Cache** | In-memory dict + Redis optional | Global | In-memory LRU + TTL |
| **Token Usage** | PostgreSQL (Supabase) | Per user, weekly | Durable |
| **Rate Limiting** | PostgreSQL sliding window | Per endpoint class | Durable |
| **JWT Blacklist** | SQLite / PostgreSQL | Global | Persistent |
| **Pipeline Runs** | PostgreSQL (IKG) | Global | Durable |

### 14.2 Frontend State

| Store | Technology | Persistence |
|-------|-----------|-------------|
| **Auth** | React Context + localStorage | Browser storage |
| **UI State** | Component `useState`/`useEffect` | In-memory |
| **Onboarding** | localStorage keyed by email | Browser storage |
| **Manual Portfolio** | localStorage | Browser storage |
| **SSE Connection** | Custom fetch stream | In-memory |
| **Telemetry Session** | Azure App Insights | Azure cloud |

---

## 15. Authentication & Security

### 15.1 Authentication

```
Google OAuth (GIS popup) ──▶
Email/Password (Supabase Auth) ──▶
Supabase JWT (direct) ──▶
       │
       ▼
┌─────────────────────────────────────────┐
│  FastAPI Auth Guard                     │
│  gateway/auth_guard.py                  │
│                                         │
│  get_current_user() extracts token from:│
│    1. Authorization: Bearer <token>     │
│    2. prospektlab_token cookie          │
│    3. ?token=<token> query param (GET)  │
│                                         │
│  Validation:                            │
│    - HS256 signature                    │
│    - Issuer/audience checks             │
│    - Expiry (30 days) + clock skew      │
│    - jti blacklist                      │
│    - Supabase JWT fallback              │
└─────────────────────────────────────────┘
```

### 15.2 Authorization & Rate Limits

- **Token budgets:** Free plan 1,000,000 tokens/week + 1 deep run/week; Pro plan higher limits.
- **Session ownership:** `tenant_id` + email must match session metadata for all `/sessions/{id}/*` endpoints.
- **Admin gates:** `/admin/*`, `/ops/control-tower`, `/metrics/snapshot` require email allowlists.
- **Rate limiter classes:**
  - `research_rate_limiter`: 5 requests / 60 seconds
  - `auth_rate_limiter`: 10 requests / 60 seconds
  - `default_rate_limiter`: 100 requests / 60 seconds

### 15.3 Security Hardening

- **CSP headers** per route (ops, insights, main app)
- **X-Frame-Options: DENY**, **X-Content-Type-Options: nosniff**, **HSTS**
- **Prompt injection guard** via regex patterns
- **File upload validation:** magic bytes, size limits, extension whitelist
- **HTML sanitization** on output
- **CORS:** origin whitelist via `CORS_ORIGINS`
- **Cookies:** httpOnly, SameSite=Lax, Secure in production

---

## 16. Deployment & Infrastructure

### 16.1 AWS (Frontend + Backend)

```
┌─────────────────────────────────────────────────────────────┐
│                        AWS CLOUD                            │
│                                                             │
│  AWS Amplify (React SPA) ──HTTPS──▶ AWS ECS Fargate         │
│   Region: us-east-1                Task: 1 vCPU, 2GB RAM   │
│   Build: npm ci && vite build      Port: 8080               │
│   Artifacts: dist/                 Image: ECR               │
│                                    Auto-scaling: 1-4 tasks  │
│                                                             │
│  AWS CodeBuild + CodePipeline                               │
│   GitHub → Build Docker → Push ECR → Deploy ECS             │
└─────────────────────────────────────────────────────────────┘
```

### 16.2 Azure (IKG + Monitoring + Communication)

```
┌─────────────────────────────────────────────────────────────┐
│                       AZURE CLOUD                           │
│                                                             │
│  Azure Linux VM (prospektlab-ikg-vm)                        │
│    Docker Compose stack:                                    │
│      - postgres:16                                          │
│      - redis:7 (broker)                                     │
│      - qdrant (vector)                                      │
│      - celery-worker (10 threads)                           │
│      - scheduler (APScheduler)                            │
│      - memgraph-mage + memgraph-lab (graph algorithms)      │
│                                                             │
│  Azure Communication Services (ACS)                         │
│    - Email delivery (verification, notifications)           │
│    - SMS delivery (verification OTP)                        │
│                                                             │
│  Azure Monitor + Application Insights                     │
│    - Backend + frontend telemetry                           │
│    - IKG pipeline monitoring                                │
└─────────────────────────────────────────────────────────────┘
```

### 16.3 Supabase (User Data & Auth)

```
┌─────────────────────────────────────────────┐
│              SUPABASE CLOUD                 │
│                                             │
│  Managed PostgreSQL:                        │
│    - profiles, token_usage, payments        │
│    - contacts, scrape_jobs, export_jobs     │
│    - outreach_* tables                      │
│                                             │
│  Auth Service:                              │
│    - Google OAuth social login            │
│    - Email/password with Admin API          │
│    - JWT verification via project secret    │
└─────────────────────────────────────────────┘
```

### 16.4 Background Services

| Service | Entry Point | Schedule |
|---------|-------------|----------|
| **Gateway periodic tasks** | `gateway/run.py` lifespan | Every 5 min: reap tasks, cleanup sessions, cleanup SQLite |
| **IKG Scheduler** | `finagent.ikg.pipeline.scheduler` | APScheduler cron: 6h/12h/24h intervals |
| **Celery Workers** | `finagent.ikg.pipeline.celery_app` | Continuous, 10 threads across multiple queues |
| **Dreaming Layer** | `finagent.dreaming.scheduler` | Nightly at 2 AM IST |
| **Content Official Monitor** | `finagent.content.official_monitor` | Every 30 min |
| **Flash Content Engine** | `finagent.content.flash_engine` | On-demand |

---

## 17. Configuration Reference

### 17.1 Required Environment Variables

| Variable | Purpose |
|----------|---------|
| `JWT_SECRET` | HS256 signing key for local JWTs |
| `OPENAI_API_KEY` | OpenAI API key |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase service role key |
| `SUPABASE_JWT_SECRET` | Supabase project JWT secret |
| `SUPABASE_DB_URL` | Direct PostgreSQL connection URL |
| `IKG_DATABASE_URL` | IKG PostgreSQL connection URL |
| `CORS_ORIGINS` | Comma-separated allowed origins |

### 17.2 AI/LLM Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `FINAGENT_MODEL` | `gpt-5.4-mini` | Default LLM for sub-agents |
| `FINAGENT_SYNTH_MODEL` | `gpt-5.4-mini` | LLM for synthesis |
| `FINAGENT_LIGHT_MODEL` | `gpt-4o-mini` | Lightweight tasks |
| `AZURE_AI_FOUNDRY_API_KEY` | — | Azure Foundry fallback |
| `XAI_API_KEY` | — | xAI Grok fallback |
| `FINAGENT_TEMPERATURE` | `0.3` | LLM temperature |
| `FINAGENT_MAX_TOKENS` | `4096` | Max completion tokens |
| `FINAGENT_SYNTH_MAX_TOKENS` | `16384` | Max synthesis tokens |

### 17.3 Quotas & Limits

| Variable | Default | Purpose |
|----------|---------|---------|
| `WEEKLY_TOKEN_LIMIT` | `1000000` | Free plan weekly token budget |
| `PRO_WEEKLY_TOKEN_LIMIT` | `2000000` | Pro plan weekly token budget |
| `FREE_WEEKLY_DEEP_RUNS` | `1` | Free plan deep research quota |

### 17.4 Payments & Communication

| Variable | Purpose |
|----------|---------|
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` | Razorpay |
| `VITE_RAZORPAY_KEY_ID` | Frontend Razorpay key |
| `ACS_EMAIL_CONNECTION_STRING` | Azure email endpoint |
| `ACS_SMS_CONNECTION_STRING` | Azure SMS endpoint |
| `PROSPEKTLAB_FROM_EMAIL` | Sender email address |

### 17.5 Infrastructure

| Variable | Default | Purpose |
|----------|---------|---------|
| `PROSPEKTLAB_ENV` | `production` | `production` | `local` |
| `BACKEND_API_URL` | — | Backend URL for frontend injection |
| `FINAGENT_HOME` | `.finagent` | Agent state directory |
| `NSE_COOKIE_STRING` | — | NSE session bypass cookie |
| `MCA_COMPANY_MASTER_CSV` | — | Path to company master CSV |
| `FINAGENT_DEFAULT_GEO` | `IN` | Default geography |
| `FINAGENT_EXCHANGE_SUFFIX` | `.NS` | Default exchange suffix |
| `IKG_BACKEND` | `memory` | `postgres` | `memory` — graph backend |
| `IKG_POSTGRES_URL` | — | IKG PostgreSQL URL override |

### 17.6 Admin

| Variable | Purpose |
|----------|---------|
| `ADMIN_RESET_KEY` | Secret key for admin reset endpoint |
| `CONTROL_TOWER_ALLOWED_EMAILS` | Emails allowed for control tower |
| `FINAGENT_METRICS_ADMIN_EMAILS` | Emails allowed for metrics snapshot |

---

## 18. Third-Party Integrations

### 18.1 AI / LLM

| Provider | Service | Models |
|----------|---------|--------|
| **OpenAI** | Chat Completions | GPT-5.4-mini, GPT-4o-mini, text-embedding-3-small |
| **Azure AI Foundry** | OpenAI on Azure | GPT-4o-mini (fallback) |
| **xAI** | Grok API | Grok-3 (fallback) |

### 18.2 Database & Storage

| Provider | Service | Purpose |
|----------|---------|---------|
| **Supabase** | Managed PostgreSQL | User data, payments, token usage, outreach |
| **PostgreSQL** | Self-hosted (Azure VM) | IKG system of record |
| **Qdrant** | Vector Database | Embedding search |
| **Memgraph** | Graph Database | Graph algorithms (MAGE) |
| **Redis** | In-memory store | Celery broker, optional cache |

### 18.3 Cloud Services

| Provider | Service | Purpose |
|----------|---------|---------|
| **AWS** | ECS Fargate | Backend gateway |
| **AWS** | Amplify | Frontend hosting |
| **AWS** | CodeBuild / CodePipeline | CI/CD |
| **Azure** | VMs | IKG worker stack |
| **Azure** | Communication Services | Email + SMS |
| **Azure** | Document Intelligence | AI document parsing |
| **Azure** | Cognitive Search | Full-text + semantic search |
| **Azure** | Application Insights / Monitor | Telemetry |

### 18.4 Data Sources

| Source | Type | Data |
|--------|------|------|
| **Yahoo Finance** | API | Quotes, history, indices, fundamentals |
| **NSE India** | Web scraping | Filings, index constituents, equity snapshots |
| **BSE India** | Web scraping | Announcements, EOD, shareholding patterns |
| **SEBI** | Web scraping | Enforcement orders, circulars |
| **MCA** | CSV / scraping | Company master, director KMP data |
| **SEC EDGAR** | API | US filings (10-K, 10-Q, 8-K) |
| **Reddit / HN / StockTwits** | API | Social sentiment |
| **Wikipedia** | API | Entity enrichment |
| **RBI / AMFI** | RSS / scraping | Monetary policy, MF NAV/AUM |
| **SearXNG / DuckDuckGo** | Search | Web search |
| **Crawl4AI** | Library | AI-optimized crawling |

### 18.5 Auth & Payments

| Provider | Service | Purpose |
|----------|---------|---------|
| **Google Identity Services** | OAuth 2.0 | Social login |
| **Supabase Auth** | Admin API | Email/password management |
| **Razorpay** | Payment Gateway | INR subscription payments |

### 18.6 Document Processing

| Library/Service | Purpose |
|-----------------|---------|
| **casparser** | CAMS/Kfintech CAS PDF parsing |
| **pypdf / PyMuPDF** | Generic PDF extraction |
| **openpyxl** | Excel parsing |
| **python-docx** | DOCX generation |
| **msoffcrypto-tool** | Password-protected Excel |
| **Azure Doc Intelligence** | Cloud structured extraction |
| **Docling** | IBM annual-report parsing |
| **MinerU** | Document structure extraction |

### 18.7 DevOps

| Tool | Purpose |
|------|---------|
| **Docker** | Containerization |
| **Docker Compose** | IKG multi-service stack |
| **uv** | Python package manager |
| **Playwright / Patchright** | Headless browser automation |
| **fastmcp** | MCP server framework |
| **Celery** | Distributed task queue |
| **APScheduler** | Cron scheduling |

---

## 19. Roadmap & Upcoming Modules

### 19.1 Earnings Analysis (High Priority)

Target capabilities:

- Quarterly/annual result ingestion from NSE/BSE filings, PDFs, transcripts, press releases
- KPI extraction: revenue, EBITDA, PAT, margins, guidance, order book, deal wins, asset quality, ARPU, volume growth
- YoY, QoQ, TTM, consensus-versus-actual analysis
- Earnings surprise detection and management commentary summarization
- Segment-level analysis for banks, IT, autos, FMCG, pharma, infra, telecom, financials
- Portfolio impact view: owned holdings with upcoming/recent earnings
- Earnings calendar and watchlist alerts
- Post-result research memos with valuation, risk, governance context
- Content Studio integration for publishable result explainers

### 19.2 IPO Analysis (Medium Priority)

Target capabilities:

- IPO calendar: upcoming, open, closed, allotment, listing, SME, mainboard
- DRHP/RHP ingestion and section extraction
- Offer structure: fresh issue, OFS, promoter selling, objects, price band, lot size
- Financial trend extraction from offer documents
- Peer comparison and valuation banding
- Promoter, group, related-party, litigation, pledge checks via IKG
- Risk summary: debt, customer concentration, margin volatility, working capital, RPT, auditor notes
- Subscription and GMP tracking (where compliant)
- Listing-day analysis and post-listing scorecard
- Portfolio/watchlist integration

### 19.3 Governance IGS — India Governance Standard (High Priority)

IGS is the next-generation governance intelligence layer. It moves from a heuristic score to a validated, predictive system.

Target dimensions:

- Director network risk (centrality, enforcement proximity, board churn)
- Auditor change and audit-quality risk
- Promoter pledge and ownership dilution trajectory
- Related-party transaction density
- Enforcement proximity across companies, directors, promoters, related entities
- Board churn, independence, tenure, concentration
- Failure labels: delisting, debarment, insolvency, struck-off, trading suspension

Implementation path:

1. Create `failure_events` table and backfill 15 years of labels.
2. Densify `DIRECTOR_OF`, `AUDITOR_OF`, `RELATED_PARTY_TRANSACTION`, `ENFORCEMENT_ACTION_AGAINST` edges.
3. Add graph algorithms via Memgraph MAGE (proximity, centrality, community detection).
4. Build temporal `company_features` store.
5. Train interpretable LightGBM/XGBoost model with SHAP explanations.
6. Keep current governance score contract stable while replacing internals with IGS when coverage is sufficient.
7. Add portfolio-level IGS exposure, trend, peer percentile, and alerting.

Success criteria:

- Coverage: all ~2,000 actively listed companies scored
- Accuracy: AUC ≥ 0.80 on held-out failures
- Lead time: predictions lead enforcement/delisting by 6–12 months on backtest
- Explainability: every flag carries a source URL
- Freshness: incremental refresh per dimension

### 19.4 Portfolio Analytics Upgrade

Planned upgrades (from `PORTFOLIO_ANALYTICS_UPGRADE.md`):

1. **Factor exposure & attribution** — decompose returns into market, size, value, quality, momentum, low-volatility bets.
2. **Regime-based risk decomposition** — risk metrics conditioned on bull/bear, rate, inflation, volatility regimes.
3. **Tax-loss harvesting optimizer** — lot-level, wash-sale-aware, multi-year tax-shield optimizer.
4. **Drawdown path analysis** — duration, recovery, contributors, current percentile.
5. **Conditional correlation matrix** — normal vs. stress regime.
6. **Liquidity-adjusted risk** — Amihud illiquidity, days-to-liquidate, liquidity ladder.
7. **Forward-looking earnings impact** — estimate revision momentum, forward P/E, EPS dispersion.
8. **Behavioral bias detection** — disposition effect, overtrading, home bias, momentum chasing.
9. **Rebalancing & glide-path simulation** — goal-based drift bands, transaction-cost-aware rebalancing.
10. **Improved tail-risk stress testing** — path-based historical scenarios and CDaR.

---

> **Document Version:** 2.0  
> **Last Updated:** June 2026  
> **Platform:** ProspektLab — Financial Intelligence Operating System

# PROSPEKTLAB — Complete Architecture Documentation

> **Financial Intelligence Operating System**  
> AI-powered automated financial research, portfolio analytics, content generation, and governance intelligence platform.

---

## Table of Contents

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Technology Stack](#2-technology-stack)
3. [Directory Structure](#3-directory-structure)
4. [API Reference (All Endpoints)](#4-api-reference-all-endpoints)
5. [Data Flow & Workflows](#5-data-flow--workflows)
6. [Multi-Agent Research Engine (FinAgent)](#6-multi-agent-research-engine-finagent)
7. [Intelligent Knowledge Graph (IKG)](#7-intelligent-knowledge-graph-ikg)
8. [Portfolio Analytics Engine](#8-portfolio-analytics-engine)
9. [Content Automation Engine](#9-content-automation-engine)
10. [Frontend Architecture](#10-frontend-architecture)
11. [Database Schema](#11-database-schema)
12. [State Management](#12-state-management)
13. [Authentication & Security](#13-authentication--security)
14. [Deployment & Infrastructure](#14-deployment--infrastructure)
15. [CI/CD Pipelines](#15-cicd-pipelines)
16. [Configuration Reference](#16-configuration-reference)
17. [Third-Party Integrations](#17-third-party-integrations)

---

## 1. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     AWS AMPLIFY (Frontend)                       │
│   React 18 + Vite + TypeScript SPA                               │
│   HashRouter, Google OAuth, Razorpay Checkout                    │
│   Azure Application Insights telemetry                           │
└────────────────────────┬────────────────────────────────────────┘
                         │  HTTPS (API calls + SSE streaming)
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                  AWS ECS FARGATE (Backend Gateway)                │
│   FastAPI + Uvicorn (finagent.gateway.run:app)                   │
│                                                                  │
│   ┌─────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│   │ Auth Module  │  │ Research     │  │ Portfolio Analytics   │  │
│   │ (JWT+Google) │  │ Orchestrator │  │ & Governance Engine   │  │
│   └─────────────┘  └──────────────┘  └───────────────────────┘  │
│   ┌─────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│   │ Content      │  │ Market Data  │  │ Payments (Razorpay)   │  │
│   │ Automation   │  │ APIs         │  │                       │  │
│   └─────────────┘  └──────────────┘  └───────────────────────┘  │
└───┬──────────────┬──────────────┬──────────────┬────────────────┘
    │              │              │              │
    ▼              ▼              ▼              ▼
┌────────┐  ┌───────────┐  ┌───────────┐  ┌────────────────────┐
│Supabase│  │Azure VMs  │  │OpenAI     │  │External Data        │
│        │  │(IKG Stack)│  │Azure/xAI  │  │Sources              │
│Postgres│  │           │  │           │  │                     │
│Auth    │  │Postgres 16│  │GPT-5.4-min│  │Yahoo Finance, SEC   │
│Users   │  │Redis 7    │  │GPT-4o-mini│  │NSE, BSE, SEBI, MCA │
│Payments│  │Qdrant     │  │Grok-3     │  │Reddit, HackerNews   │
│Memory  │  │Celery     │  │           │  │Wikipedia, News RSS  │
│        │  │Neo4j      │  │           │  │                     │
│        │  │Scrapers   │  │           │  │                     │
└────────┘  └───────────┘  └───────────┘  └────────────────────┘
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

## 2. Technology Stack

### Backend — Python 3.11

| Layer | Technology | Version |
|-------|-----------|---------|
| **Web Framework** | FastAPI | 0.100+ |
| **ASGI Server** | Uvicorn | 0.23+ |
| **AI/LLM** | OpenAI SDK, xAI Grok | 1.0+ |
| **Agent Framework** | LangChain, LangGraph | 0.2+ |
| **Data Science** | Pandas, NumPy | 2.0+ / 1.24+ |
| **Finance** | yfinance, PyPortfolioOpt | 0.2.40+ |
| **Doc Parsing** | pypdf, PyMuPDF, casparser, msoffcrypto-tool, Azure Doc Intelligence | |
| **Web Scraping** | Patchright (Playwright), crawl4ai, httpx, aiohttp | |
| **Search** | Qdrant (vector), Azure Cognitive Search (hybrid) | |
| **Graph DB** | Neo4j | 5.20+ |
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
| **Framework** | React | 18.3 |
| **Build Tool** | Vite | 5.2+ |
| **Language** | TypeScript | 5.2+ |
| **Routing** | React Router DOM (hash-based) | 6.23+ |
| **Charts** | Chart.js + react-chartjs-2 + chartjs-chart-treemap | 4.4+ |
| **Icons** | lucide-react | 0.379+ |
| **Auth** | Google Identity Services (GIS) | — |
| **Payments** | Razorpay Checkout | — |
| **Telemetry** | Azure Application Insights | — |

---

## 3. Directory Structure

```
D:\PROSPEKTLAB\
│
├── pyproject.toml                  # Python project config & dependencies
├── package.json                    # Root: playwright dependency
├── uv.lock                         # Python dependency lock file
├── Dockerfile                      # Main FastAPI gateway Docker image
├── .python-version                 # 3.11
├── .mcp.json                       # MCP server config (Greptile)
├── opencode.json                   # OpenCode AI config
├── .gitignore / .dockerignore
│
├── README.md
├── README-DEPLOYMENT.md
├── AWS-DEPLOYMENT-COMMANDS.sh
├── deploy-production.sh
├── start_server.ps1                # Launcher: FastAPI gateway
├── start_ikg_scheduler.ps1         # Launcher: IKG scheduler
├── run_qdrant_index.py
├── bootstrap_db.py
├── smoke_test.py
├── cover_prompts.txt
├── test_*.py                       # 15+ root-level integration tests
│
├── backend/
│   └── finagent/                   # *** MAIN BACKEND PACKAGE ***
│       ├── __init__.py             # Env loading, SSL certificate fix
│       ├── __main__.py             # python -m finagent entry
│       ├── api.py                  # Standalone FastAPI (/api/chat, /api/chat/stream)
│       ├── cli.py                  # CLI entry point
│       ├── cache.py                # TTL cache (in-memory + Redis fallback)
│       ├── events.py               # Event bus for SSE streaming
│       ├── telemetry.py            # Azure App Insights telemetry
│       ├── telemetry_burner.py     # Batch telemetry sender
│       ├── env.py                  # Env loading helpers
│       ├── paths.py                # File path resolution
│       ├── settings.py             # FinAgentSettings config dataclass
│       ├── runtime_provider.py     # LLM provider resolution (Azure/OpenAI/xAI)
│       ├── run_agent.py            # Core research agent loop (~3120 lines)
│       ├── research_planner.py     # Research plan builder
│       ├── synthesis.py            # Memo synthesis engine
│       ├── prompt_builder.py       # System prompt builder
│       ├── rich_builder.py         # Rich output builder
│       ├── accuracy_validator.py   # Fact-checking validator
│       ├── intent.py               # Intent detection
│       ├── content_automation.py   # Automated article generation (~5482 lines)
│       ├── portfolio_mirrors.py    # Portfolio mirror management
│       ├── portfolio_sentinel.py   # Portfolio monitoring
│       │
│       ├── gateway/                # FASTAPI GATEWAY (main server entry)
│       │   ├── run.py              # *** APP DEFINITION *** (~5640 lines, ALL routes)
│       │   ├── auth_guard.py       # JWT auth verification + rate limiting
│       │   ├── supabase_client.py  # Supabase API client (~779 lines)
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
│       │       ├── accounting.py   # Forensic accounting analysis
│       │       ├── community.py    # Community/social sentiment
│       │       ├── competitor.py   # Competitor & peer analysis
│       │       ├── financials.py   # Financial statement analysis
│       │       ├── governance.py   # Corporate governance review
│       │       ├── macro.py        # Macroeconomic outlook
│       │       ├── news.py         # News & event briefing
│       │       ├── risk.py         # Risk factor analysis
│       │       ├── technical.py    # Technical/chart analysis
│       │       └── valuation.py    # DCF & valuation analysis
│       │
│       ├── agent/                  # LEGACY AGENT (being migrated)
│       │   ├── query_analysis.py   # Query understanding
│       │   └── reflection.py       # Reflection loop
│       │
│       ├── ikg/                    # INTELLIGENT KNOWLEDGE GRAPH
│       │   ├── service.py          # IKG service layer
│       │   ├── db.py               # IKG database adapter
│       │   ├── schema.py           # IKG schema definition
│       │   ├── entity_resolver.py  # Entity name → CIN resolution
│       │   ├── graph_client.py     # Neo4j graph client
│       │   ├── governance_score.py # Forensic governance scoring
│       │   ├── director_network.py # Board interlock analysis
│       │   ├── company_provenance.py # Citation-backed company facts
│       │   ├── document_selector.py  # Filing document selection
│       │   ├── graph_health.py     # Graph completeness health
│       │   ├── staleness.py        # Data freshness checker
│       │   ├── pipeline/           # IKG ETL PIPELINE
│       │   │   ├── scheduler.py    # APScheduler cron dispatcher
│       │   │   ├── celery_app.py   # Celery app definition
│       │   │   ├── orchestrator.py # Full pipeline orchestration
│       │   │   ├── run_store.py    # Pipeline run tracking
│       │   │   └── company_integrity_audit.py
│       │   └── scrapers/           # 20+ DATA SCRAPERS
│       │       ├── _engine.py      # Scraping engine base
│       │       ├── _nse_session.py # NSE cookie/session management
│       │       ├── _proxy_manager.py # Rotating proxies
│       │       ├── annual_reports.py   # Annual report PDF extraction
│       │       ├── bse_eod.py          # BSE end-of-day data
│       │       ├── bse_shp.py          # BSE shareholding patterns
│       │       ├── concall_transcripts.py # Conference call transcripts
│       │       ├── corporate_governance_directors.py
│       │       ├── director_kmp_enricher.py
│       │       ├── financial_data.py
│       │       ├── mca_companies.py    # MCA company master data
│       │       ├── mca_directors.py    # MCA director data
│       │       ├── nse_index.py        # NSE index constituents
│       │       ├── sebi_corporate_filings.py
│       │       ├── sebi_enforcement.py  # SEBI enforcement orders
│       │       └── xbrl_utils.py       # XBRL parsing utilities
│       │
│       ├── content/                # CONTENT AUTOMATION ENGINE
│       │   ├── flash_engine.py     # Flash content engine (~4979 lines)
│       │   ├── editorial.py        # Editorial review & QA
│       │   ├── editorial_calendar.py
│       │   ├── official_monitor.py # Official source RSS monitoring
│       │   ├── filing_triage.py    # Filing materiality classification
│       │   ├── livemint_blocker.py # Duplicate detection
│       │   ├── livemint_editorial.py
│       │   ├── specialist_agents.py # Content specialist agents
│       │   └── content_accuracy.py # Content fact-checking
│       │
│       ├── portfolio/              # PORTFOLIO ANALYTICS ENGINE
│       │   ├── analytics.py        # Core analytics computation
│       │   ├── sectors.py          # Sector/industry breakdown
│       │   ├── news.py             # Portfolio-specific news
│       │   ├── alerts.py           # Alert computation
│       │   ├── stress_test.py      # Monte Carlo stress testing
│       │   ├── tax.py              # Tax liability summary (India)
│       │   ├── dividends.py        # Dividend tracking
│       │   ├── corporate_actions.py # Bonus, splits, buybacks
│       │   ├── governance_xray.py  # Governance overlay per holding
│       │   ├── action_queue.py     # Daily recommended actions
│       │   ├── holding_detail.py   # Single holding deep-dive
│       │   ├── commentary.py       # AI portfolio commentary
│       │   └── mf_analytics.py     # Mutual fund analysis
│       │
│       ├── output/                 # OUTPUT GENERATION & FORMATTING
│       │   ├── contracts.py        # Output mode schema contracts
│       │   ├── artifact_builder.py # Rich artifact construction
│       │   ├── chart_generator.py  # Matplotlib chart generation
│       │   ├── renderer.py         # HTML/Markdown renderer
│       │   ├── memo_formatter.py   # Research memo formatting
│       │   ├── report_exporter.py  # PDF/DOCX/XLSX export
│       │   ├── export_jobs.py      # Async export job management
│       │   ├── templates.py        # Output templates
│       │   ├── fact_check.py       # Post-hoc fact checking
│       │   ├── confidence_scorer.py # Confidence scoring
│       │   ├── conflict_reporter.py # Interest conflict detection
│       │   ├── compliance.py       # Regulatory compliance checks
│       │   ├── output_scrubber.py  # Output sanitization
│       │   ├── query_guards.py     # Query safety guardrails
│       │   └── intent_classifier.py # Intent → output mode classifier
│       │
│       ├── tools/                  # TOOL ECOSYSTEM
│       │   ├── data/               # Market data fetching tools
│       │   │   ├── yahoo_finance.py, india.py, nse_snapshot.py
│       │   │   ├── sec_edgar.py, sec_filings.py
│       │   │   ├── news_feed.py, reddit.py, hackernews.py, stocktwits.py
│       │   │   ├── wikipedia.py, forex.py
│       │   │   └── cache.py, units.py
│       │   ├── web/                # Web scraping tools
│       │   │   ├── scraper.py, http_fetcher.py
│       │   │   ├── searxng_client.py, exchange_fetcher.py
│       │   │   └── crawl4ai_sites.py, table_parser.py
│       │   ├── social/             # Social media tools
│       │   │   └── viral_verifier.py
│       │   ├── prospektlab/        # ProspektLab-specific tools
│       │   │   ├── enricher.py, entity_fetcher.py
│       │   │   ├── event_monitor.py, exporter.py, navigator.py
│       │   ├── mcp_servers/        # Model Context Protocol servers
│       │   │   ├── discovery_server.py, docs_server.py
│       │   │   ├── fundamentals_server.py, ikg_server.py
│       │   │   ├── mcp_valuation.py, nse_server.py
│       │   │   ├── quant_server.py, research_server.py
│       │   ├── valuation_engine.py # Deterministic DCF/math engine (~1016 lines)
│       │   ├── registry.py         # Tool registry
│       │   └── mcp_config.py       # MCP configuration
│       │
│       ├── router/                 # QUERY ROUTING
│       │   ├── intent_router.py    # Intent-based routing
│       │   ├── tool_selector.py    # Tool selection logic
│       │   ├── domain_taxonomy.py  # Domain classification
│       │   ├── geography_router.py # Geographic routing
│       │   └── policies.py         # Routing policies
│       │
│       ├── geo/                    # GEOGRAPHY HANDLING
│       │   ├── entity_resolver.py  # Geo-aware entity resolution
│       │   ├── ticker_mapper.py    # Symbol → exchange mapping
│       │   ├── jurisdiction_profiles.py
│       │   ├── currency_policy.py, source_policy.py
│       │   └── query_localizer.py
│       │
│       ├── news/                   # NEWS AGGREGATION
│       │   ├── cache.py, dedupe.py, scorer.py
│       │   └── sources/
│       │       ├── sebi_rss.py, bse_announcements.py, nse_announcements.py
│       │       ├── rbi_press.py, mca_updates.py, rss_aggregator.py
│       │       ├── searxng_source.py, amfi_source.py
│       │       └── exchange_announcements.py
│       │
│       ├── memory/                 # MEMORY SYSTEM
│       │   ├── store.py            # Memory fact store
│       │   ├── tiered_store.py     # Tiered (episodic/semantic/procedural)
│       │   └── chat_memory.py      # Chat history management
│       │
│       ├── storage/                # STORAGE ADAPTERS
│       │   ├── sqlite.py           # SQLite adapter
│       │   └── supabase_store.py   # Supabase PostgreSQL adapter
│       │
│       ├── ingestion/              # PORTFOLIO DOCUMENT INGESTION
│       │   ├── portfolio_document.py  # Multi-format parser (CAS/PDF/CSV/XLSX/image)
│       │   ├── portfolio_schema.py    # Extraction Pydantic schema
│       │   ├── image_ingestion.py     # Screenshot → positions (GPT-4o Vision)
│       │   ├── cas_adapter.py         # CAS/eCAS PDF parsing
│       │   ├── pdf_transformer.py     # PDF → structured data
│       │   ├── markdown_extractor.py  # Markdown table extraction
│       │   ├── azure_doc_intel.py     # Azure Document Intelligence
│       │   ├── mineru_transformer.py  # MinerU document parsing
│       │   ├── isin_resolver.py       # ISIN → Symbol resolution
│       │   ├── di_cost_report.py      # Document Intelligence cost tracking
│       │   └── portfolio_guardrails.py # Portfolio validation rules
│       │
│       ├── retrieval/              # HYBRID RETRIEVAL (RAG)
│       │   ├── planner.py          # Retrieval planner
│       │   ├── fusion.py           # BM25 + dense fusion
│       │   ├── dense_index.py      # Dense vector index
│       │   ├── sparse_index.py     # Sparse (BM25) index
│       │   ├── graph_index.py      # Graph-based index
│       │   ├── reranker.py         # Result re-ranking
│       │   └── hyde.py             # Hypothetical Document Embeddings (HyDE)
│       │
│       ├── graphrag/               # GRAPH RAG
│       │   ├── indexer.py, query.py
│       │   ├── azure_search.py     # Azure Cognitive Search integration
│       │   ├── qdrant_store.py     # Qdrant vector store
│       │   ├── qdrant_indexer.py   # Qdrant index builder
│       │   ├── qdrant_search.py    # Qdrant search client
│       │   ├── section_materializer.py
│       │   └── mcp_server.py
│       │
│       ├── harness/                # AGENT HARNESS
│       │   ├── orchestrator.py     # Long-running agent orchestrator
│       │   ├── context_manager.py  # Context window management
│       │   ├── error_recovery.py   # Error recovery strategies
│       │   ├── footprint_enforcer.py # Token/context budget enforcement
│       │   ├── human_gates.py      # Human-in-the-loop checkpoints
│       │   ├── interrupt_handler.py # Cancellation/interrupt handling
│       │   └── preflight.py        # Pre-execution validation
│       │
│       ├── state/                  # STATE MANAGEMENT
│       │   ├── checkpoint.py       # Checkpoint save/restore
│       │   ├── citation_log.py     # Citation tracking
│       │   ├── compression.py      # Context compression
│       │   ├── research_state.py   # Research state machine
│       │   └── session_context.py  # Session-level context
│       │
│       ├── playbooks/              # PLAYBOOK SYSTEM
│       │   ├── executor.py, promoter.py
│       │   ├── retriever.py, schema.py, store.py
│       │
│       ├── dreaming/               # DREAMING LAYER (offline learning)
│       │   ├── consolidator.py     # Insight consolidation
│       │   ├── pattern_detector.py # Pattern detection
│       │   ├── preloader.py        # Pre-caching
│       │   ├── scheduler.py        # Nightly scheduler (2 AM IST)
│       │   └── worker.py           # Dream worker
│       │
│       ├── learning/               # ONLINE LEARNING
│       │   ├── reflexion.py        # Reflexion-based improvement
│       │   ├── spl.py              # Self-play learning
│       │   └── strategy_loader.py  # Strategy loading
│       │
│       ├── seo/                    # SEO
│       │   └── google_search_console.py # Sitemap submission
│       │
│       ├── ops/                    # OPERATIONS
│       │   ├── control_tower.py    # Control tower dashboard
│       │   └── metrics_warehouse.py # DAU/MAU/retention metrics
│       │
│       ├── analysis/               # ANALYSIS
│       │   ├── conflicts.py        # Conflict analysis
│       │   └── quality.py          # Quality analysis
│       │
│       ├── prompts/                # SYSTEM PROMPTS
│       │   └── finagent_system.txt # Master system prompt
│       │
│       ├── tests/                  # Package unit tests
│       └── data/                   # Local data
│
├── frontend/                       # REACT FRONTEND (Vite + TypeScript)
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts / vite.config.mjs
│   ├── index.html
│   ├── .env                        # VITE_RAZORPAY_KEY_ID
│   ├── amplify.yml                 # Amplify hosting config
│   ├── public/
│   │   ├── *.svg, *.html           # Static assets + landing pages
│   │   ├── env-config.js           # Runtime BACKEND_API_URL injection
│   │   └── insights/               # Generated public article HTML
│   └── src/
│       ├── main.tsx                # Entry point
│       ├── App.tsx                 # HashRouter + route definitions
│       ├── index.css               # Global styles
│       ├── telemetry.ts            # Frontend telemetry (~491 lines)
│       ├── api/
│       │   └── client.ts           # *** API CLIENT *** (~2200+ lines, all backend calls)
│       ├── context/
│       │   └── AuthContext.tsx      # Auth state (JWT, user, role) (~626 lines)
│       ├── data/
│       │   └── indianStocks.ts     # Stock metadata list
│       ├── pages/
│       │   ├── LandingPage.tsx     # Marketing landing
│       │   ├── Login.tsx           # Google/Email auth
│       │   ├── Dashboard.tsx       # Main app dashboard
│       │   ├── GatewayPage.tsx     # Research gateway
│       │   ├── InsightsStudio.tsx  # Content management
│       │   ├── Pricing.tsx         # Pricing plans
│       │   ├── Testimonials.tsx    # Social proof
│       │   ├── Features.tsx        # Feature showcase
│       │   ├── ContactUs.tsx       # Contact form
│       │   ├── ManualEntry.tsx     # Manual portfolio entry
│       │   ├── UploadPage.tsx      # Portfolio upload
│       │   └── WatchlistStep.tsx   # Watchlist onboarding
│       └── components/
│           ├── common/             # CommandPalette, ProvenanceCard
│           ├── layout/             # AppShell, Logo, Sidebar
│           ├── chat/               # AgentThinking, ChatInput, MessageBubble,
│           │                       # RichResponse, ExportPanel, HtmlArtifact,
│           │                       # SuggestedPrompts, SectionBlock, CalloutBlock
│           ├── charts/             # AreaChart, BarChart, DonutChart, InteractiveChart,
│           │                       # MetricCard, RadarChart, TableBlock, TreemapChart,
│           │                       # ThemeProvider
│           ├── dashboard/          # AssetHistoryModal, CompanyIntelModal,
│           │                       # GovernancePanel, IndexTickerCard, PortfolioTable,
│           │                       # QuickActions, QuickPulse, RecentInsights,
│           │                       # Sparkline, WatchlistCard
│           ├── insights/           # ArticleQueueTable, ArticleReader,
│           │                       # DraftReviewDrawer, FlashJobMonitor
│           └── research/           # ResearchTimeline
│
├── deployment/                     # INFRASTRUCTURE SCRIPTS
│   ├── Dockerfile.ikg-worker
│   ├── Dockerfile.ikg-worker-only
│   ├── docker-compose.ikg.yml
│   ├── docker-compose.ikg.worker-only.yml
│   ├── requirements.ikg-worker.txt
│   ├── fargate-backend.yml         # AWS Fargate config
│   ├── deploy-azure-ikg.ps1 / .sh
│   ├── deploy-backend.ps1
│   ├── deploy_frontend.py
│   ├── zip_backend.py
│   ├── azure_vm_*.sh               # 15+ Azure VM management scripts
│   ├── azure-cost-guardrail.ps1
│   ├── azure-monitoring.bicep      # Azure IaC
│   ├── azure-security-subscription.bicep
│   ├── ikg_watchdog.ps1 / .sh
│   └── *.sql / migrate_*.py        # Database bootstrap & migration
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
│   │   ├── run_azure_job.py
│   │   ├── run_india_outreach_scheduled.ps1
│   │   ├── run_supabase_outreach_batch.py
│   │   └── send_outreach_batch.py
│   └── templates/
│       └── prospektlab_feedback.md
│
├── scripts/                        # UTILITY SCRIPTS
│   ├── daily_publisher.py
│   ├── publish_pipeline.py
│   ├── cleanup_published.py
│   ├── fundamentals.py
│   ├── run_content_quality_audit.py
│   ├── regenerate_published_covers.py
│   ├── sync_public_research_assets.py
│   ├── reset_ikg_data.py
│   └── register_daily_task.ps1
│
├── data/                           # STATIC DATA
│   ├── company_master_data_2026-06-01.csv  # MCA company master
│   └── fine_tuning/
│
├── .github/                        # GitHub Actions workflows
├── .finagent/                      # Agent runtime state directory
├── audit_logs/ / cache/ / pipeline_logs/
└── finagent/                       # Legacy/deprecated package root
```

---

## 4. API Reference (All Endpoints)

### 4.1 Authentication

| Method | Path | Auth | Rate Limit | Description |
|--------|------|------|-----------|-------------|
| `POST` | `/auth/google` | None (receives Google ID token) | 10/min | Google OAuth sign-in → verify tokeninfo → mint JWT |
| `POST` | `/auth/google/update-mobile` | JWT | 10/min | Update user mobile number |
| `POST` | `/auth/signup` | None | 10/min | Email + password signup via Supabase Auth Admin |
| `POST` | `/auth/login` | None | 10/min | Email + password login → JWT issued |
| `POST` | `/auth/logout` | None | — | Clear `prospektlab_token` httpOnly cookie |
| `POST` | `/auth/send-verification` | None | 10/min | Send OTP via email (ACS) or SMS (ACS) |
| `POST` | `/auth/forgot-password` | None | 10/min | Request password reset → email code |
| `POST` | `/auth/reset-password` | None | 10/min | Verify code → update password |
| `GET`  | `/auth/me` | JWT | — | Return user + plan (free/pro) + usage stats |

**Example — Google Sign-In Flow:**
```
1. Frontend: google.accounts.id.initialize() → prompt() → user selects account
2. Frontend: POST /auth/google { "credential": "<google_id_token>" }
3. Backend: verify via https://oauth2.googleapis.com/tokeninfo?id_token=...
4. Backend: upsert user in Supabase profiles table
5. Backend: mint JWT (HS256, issuer=prospektlab, 30d expiry)
6. Backend: set httpOnly cookie + return token in JSON
7. Frontend: store JWT in localStorage for API calls
```

### 4.2 Research

| Method | Path | Auth | Rate Limit | Description |
|--------|------|------|-----------|-------------|
| `POST` | `/research/start` | JWT + Token check | 5/min | Start standard research (full control over params) |
| `POST` | `/research/deep` | JWT + Token + Deep quota | 5/min | Start deep multi-pass research |
| `POST` | `/chat/research` | JWT + Token check | 5/min | Chat-UI friendly wrapper (simpler payload) |
| `POST` | `/sessions/{id}/stop` | JWT + Ownership | — | Cancel running session |
| `DELETE` | `/sessions/{id}` | JWT + Ownership | — | Delete session + artifacts + files |
| `GET` | `/sessions/{id}/status` | JWT + Ownership | — | Poll session status (pending/running/done/error) |
| `GET` | `/sessions/{id}/events` | JWT + Ownership | — | Poll events with `?after=<cursor>` for pagination |
| `GET` | `/sessions/{id}/result` | JWT + Ownership | — | Get final synthesized result object |
| `GET` | `/sessions/{id}/stream` | JWT + Ownership | — | **SSE** event stream (real-time progress) |
| `GET` | `/sessions/{id}/memo` | JWT + Ownership | — | Get memo in Markdown format |
| `POST` | `/research/export` | JWT + Ownership | — | Export research as PDF/DOCX/XLSX |
| `GET` | `/research/export/{job_id}` | JWT | — | Check export job status |
| `GET` | `/research/export/{job_id}/download` | JWT | — | Download completed export |
| `GET` | `/memos` | JWT | — | List all user's saved memos |
| `GET` | `/chat/history` | JWT | — | Get full chat history (last N messages) |
| `GET` | `/memory/stats` | JWT | — | Memory usage statistics |
| `GET` | `/memory/facts` | JWT | — | Browse stored memory facts |
| `GET` | `/memory/sessions` | JWT | — | List session summaries |
| `DELETE` | `/memory/clear/{target}` | JWT | — | Clear facts for a specific entity/symbol |

**Example — Standard Research Request:**
```json
POST /chat/research
{
  "query": "Analyze Tata Motors' EV strategy and competitive position",
  "session_id": null,       // null = new session
  "context": [],            // previous messages for follow-up detection
  "mode": "standard",       // "standard" | "deep" | "chat"
  "portfolio_symbols": [],  // auto-scope to portfolio
  "geography": "IN"
}
```

**Example — SSE Stream Events:**
```
event: progress
data: {"phase": "research", "step": "financials", "status": "running"}

event: progress
data: {"phase": "research", "step": "valuation", "status": "running"}

event: citation
data: {"source": "NSE Corporate Filings", "url": "...", "text": "..."}

event: chart
data: {"type": "area", "title": "Revenue Growth", "data": {...}}

event: result
data: {"memo": "...", "citations": [...], "charts": [...], "metrics": [...]}

event: done
data: {}
```

### 4.3 Portfolio

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/portfolio/mirror` | JWT | Get current portfolio positions |
| `POST` | `/portfolio/mirror` | JWT | Replace all portfolio positions |
| `DELETE` | `/portfolio/mirror` | JWT | Clear all positions |
| `POST` | `/portfolio/mirror/sync-manual` | JWT | Sync manually entered positions with Yahoo |
| `POST` | `/api/portfolio/upload-cas` | JWT | Upload CAS/eCAS PDF, CSV, or XLSX |
| `POST` | `/api/portfolio/upload-document` | JWT | Upload any portfolio document |
| `POST` | `/portfolio/mirror/ecas` | JWT | Upload eCAS PDF specifically |
| `POST` | `/api/portfolio/upload-screenshot` | JWT | Upload portfolio screenshot (GPT-4o Vision) |
| `POST` | `/api/portfolio/confirm-extraction` | JWT | User confirms reviewed extraction → save to mirror |
| `POST` | `/api/portfolio/cancel-extraction` | JWT | Cancel/reject pending extraction |
| `GET` | `/portfolio/analytics` | JWT | Full portfolio analytics (returns, risk, allocation) |
| `GET` | `/portfolio/governance` | JWT | Governance X-Ray overlay on all holdings |
| `GET` | `/portfolio/news` | JWT | Portfolio-specific curated news |
| `GET` | `/portfolio/sectors` | JWT | Sector/sub-sector breakdown |
| `GET` | `/portfolio/holding/{symbol}` | JWT | Deep-dive on single holding |
| `GET` | `/portfolio/corporate-actions` | JWT | Recent/upcoming corporate actions |
| `GET` | `/portfolio/alerts` | JWT | Computed alerts & warnings |
| `GET` | `/portfolio/tax-summary` | JWT | Tax summary (LTCG/STCG in India) |
| `GET` | `/portfolio/dividends` | JWT | Dividend history & calendar |
| `POST` | `/portfolio/stress-test` | JWT | Run Monte Carlo stress test scenarios |
| `GET` | `/portfolio/mf-analytics` | JWT | Mutual fund-specific analytics |
| `GET` | `/portfolio/today` | JWT | Daily action queue for user |
| `GET` | `/portfolio/brief` | JWT | Portfolio summary brief |
| `GET` | `/portfolio/commentary` | JWT | AI-generated portfolio commentary |

### 4.4 Market Data

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/market/indices` | Optional JWT | Real-time indices (Nifty 50, Sensex, NASDAQ, S&P 500, crypto, forex) |
| `GET` | `/market/quotes` | Optional JWT | Real-time stock quotes (symbols as CSV) |
| `GET` | `/market/history` | JWT | Price history (1M/3M/6M/YTD/1Y/MAX) |
| `GET` | `/market/news` | Optional JWT | Market-wide news headlines |
| `GET` | `/public/market/ticker` | None | Public ticker data (no auth needed) |

### 4.5 Company Intelligence (IKG)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/company/{cin}/governance` | JWT | Forensic governance score (0-100) |
| `GET` | `/company/{cin}/network` | JWT | Director board interlock network graph |
| `GET` | `/company/{cin}/provenance` | JWT | Citation-backed company facts |
| `GET` | `/company/{cin}/health` | JWT | Graph data completeness/health score |
| `GET` | `/company/{cin}/staleness` | JWT | Data freshness verdict per category |
| `POST` | `/filings/triage` | JWT | Classify filings by materiality |

### 4.6 Content Automation

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/content/articles/generate` | JWT | Generate single article |
| `POST` | `/api/content/articles/generate-batch` | JWT | Batch article generation from events |
| `POST` | `/api/content/events/ingest` | JWT | Ingest market/regulatory events |
| `GET` | `/api/content/articles` | Optional | List articles (published + draft) |
| `GET` | `/api/content/articles/{slug}` | JWT | Get article JSON |
| `GET` | `/api/content/articles/{slug}/html` | None | Get published article HTML (public) |
| `POST` | `/api/content/articles/{slug}/publish` | JWT | Publish article |
| `POST` | `/api/content/articles/{slug}/unpublish` | JWT | Unpublish article |
| `POST` | `/api/content/flash/generate` | JWT | Start flash content generation job |
| `POST` | `/api/content/flash/ingest-events` | JWT | Flash event ingestion |
| `GET` | `/api/content/automation/status` | JWT | Get automation pipeline status |
| `POST` | `/api/content/automation/run-now` | JWT | Trigger official monitor sweep manually |

### 4.7 Payments

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/create-order` | JWT | Create Razorpay order for INR amount |
| `POST` | `/api/verify-payment` | JWT | Verify Razorpay signature after checkout |
| `GET` | `/user/subscription` | JWT | Get current plan + quota details |
| `GET` | `/user/token-usage` | JWT | Get weekly LLM token consumption |
| `POST` | `/user/upgrade-plan` | JWT | Admin-only: upgrade user plan |

### 4.8 Other Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/health` | None | Health check (returns `ok`) |
| `GET` | `/capabilities` | None | Agent capabilities + supported domains |
| `GET` | `/config` | None | Configuration status (Supabase, OpenAI, etc.) |
| `POST` | `/api/outreach/unsubscribe` | Rate-limited | Email unsubscribe |
| `POST` | `/admin/reset-all-portfolios` | JWT + Admin Key | Wipe all portfolios |
| `GET` | `/admin/ikg/health` | JWT + Admin email | IKG corpus health dashboard |
| `GET` | `/metrics/snapshot` | JWT + Admin email | DAU/MAU/retention snapshot |
| `GET` | `/ops/control-tower` | Optional | Control tower dashboard UI |
| `GET` | `/api/ops/control-tower` | Optional | Control tower API data |
| `POST` | `/api/chat` | JWT | Standalone chat (JSON) |
| `POST` | `/api/chat/stream` | JWT | Standalone chat (SSE) |

---

## 5. Data Flow & Workflows

### 5.1 Research Query — Standard/Deep

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  FRONTEND                                                           │
│  ┌──────────┐    ┌────────────┐    ┌──────────────────────────┐   │
│  │ ChatInput │───▶│ POST       │───▶│ SSE Stream Consumer      │   │
│  │           │    │ /chat/     │    │ (EventSource-like,       │   │
│  │ "Analyze  │    │ research   │    │  auto-reconnect,         │   │
│  │  TCS..."  │    │            │    │  Last-Event-ID)          │   │
│  └──────────┘    └──────┬─────┘    └──────────┬───────────────┘   │
│                         │                      │                    │
└─────────────────────────┼──────────────────────┼────────────────────┘
                          │                      │
                          ▼                      │
┌─────────────────────────────────────────────────┼────────────────────┐
│  BACKEND GATEWAY (FastAPI)                      │                    │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  1. AUTH: verify JWT from cookie/bearer/query param           │   │
│  │  2. RATE LIMIT: check token budget + rate limit               │   │
│  │  3. PROMPT GUARD: regex injection detection                   │   │
│  │  4. CONTEXTUALIZER: LLM detects follow-up vs new query        │   │
│  │  5. INTENT ROUTER: classify (portfolio_scope/comparison/      │   │
│  │     deep/standard) + auto-select geography + domains          │   │
│  │  6. SESSION: create SessionRecord, open EventBus              │   │
│  │  7. ASYNC TASK: launch _runner() in background               │   │
│  │  8. SSE: stream events back to client                         │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  RESEARCH RUNNER (run_agent.py)                              │   │
│  │                                                              │   │
│  │  Phase 1: ENTITY RESOLUTION                                  │   │
│  │    ┌─────┐   ┌─────┐   ┌─────┐                              │   │
│  │    │ IKG │   │ CIN │   │Yahoo│                              │   │
│  │    │entity│──▶│lookup│──▶│symb │  → "Tata Consultancy →     │   │
│  │    │resolv│   │     │   │resl │     CIN L22210MH1995 →      │   │
│  │    └─────┘   └─────┘   └─────┘     TCS.NS"                  │   │
│  │                                                              │   │
│  │  Phase 2: ENRICHMENT (parallel, asyncio)                     │   │
│  │    ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐            │   │
│  │    │Yahoo │ │NSE   │ │SEBI  │ │SEC   │ │News  │ ...           │   │
│  │    │Fin   │ │Snapshot│ │Filings│ │EDGAR │ │RSS  │            │   │
│  │    └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘            │   │
│  │       └────┬───┴─────┬───┴──────┴───────┴─────┘             │   │
│  │            ▼                                                │   │
│  │       Enrichment Context Bundle                              │   │
│  │                                                              │   │
│  │  Phase 3: SPECIALIST SUB-AGENTS (parallel waves)             │   │
│  │                                                              │   │
│  │  Wave 0 (no deps):                                          │   │
│  │  ┌──────────┐  ┌──────────┐                                 │   │
│  │  │Financials│  │  News    │                                 │   │
│  │  │  Agent   │  │  Agent   │                                 │   │
│  │  └────┬─────┘  └────┬─────┘                                 │   │
│  │       └──────┬──────┘                                       │   │
│  │              ▼                                              │   │
│  │  Wave 1 (depends on financials & news):                      │   │
│  │  ┌────────┐ ┌──────┐ ┌──────────┐ ┌────────┐               │   │
│  │  │Valuat. │ │Risk  │ │Governance│ │Competit│               │   │
│  │  └───┬────┘ └──┬───┘ └────┬─────┘ └───┬────┘               │   │
│  │      └────┬────┴────┬─────┴─────┬────┘                      │   │
│  │           ▼                                                  │   │
│  │  Wave 2 (depends on all above):                              │   │
│  │  ┌──────────┐ ┌─────────┐ ┌──────────┐                      │   │
│  │  │Technical │ │  Macro  │ │Community │                      │   │
│  │  └──────────┘ └─────────┘ └──────────┘                      │   │
│  │                                                              │   │
│  │  Phase 4: BLIND-SPOT DETECTION                               │   │
│  │    BlindSpotAgent scans for gaps → triggers additional runs   │   │
│  │                                                              │   │
│  │  Phase 5: REFLECTION LOOP                                    │   │
│  │    Grader scores → if < threshold → gap-filling re-run        │   │
│  │                                                              │   │
│  │  Phase 6: SYNTHESIS                                         │   │
│  │    LLM synthesizes all evidence → structured memo             │   │
│  │    + charts (Matplotlib) + metric cards                       │   │
│  │                                                              │   │
│  │  Phase 7: FACT-CHECKING                                      │   │
│  │    AccuracyValidator verifies claims against sources          │   │
│  │                                                              │   │
│  │  Phase 8: OUTPUT                                            │   │
│  │    - Save memo.md to disk                                    │   │
│  │    - Persist chat history                                    │   │
│  │    - Update memory facts                                     │   │
│  │    - Update token usage                                      │   │
│  │    - Emit result + done events                               │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 Deep Research — Detailed Flow

```
User Query → POST /research/deep
    │
    ▼
┌──────────────────────────────────────────┐
│  1. Intent Analysis & Pass Selection     │
│     LLM picks from these available passes:│
│     - financials (always included)        │
│     - valuation                           │
│     - risk                                │
│     - governance                          │
│     - shareholding                        │
│     - macro_sector                        │
│     - hidden_catalysts                    │
│     - news_narrative                      │
│     - peer_comparison                     │
│     - capital_allocation                  │
│     - competitive_moat                    │
│     - historical_sentiment                │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│  2. EVIDENCE PASSES — ALL IN PARALLEL    │
│     asyncio.gather(                      │
│       financials_evidence(),             │
│       valuation_evidence(),              │
│       risk_evidence(),                   │
│       governance_evidence(),             │
│       ...                                │
│     )                                    │
│     Each pass runs entity resolution →   │
│     enrichment → specialist agent →      │
│     structured evidence block            │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│  3. GUARDRAIL PASS                       │
│     If evidence gaps detected →           │
│     rerun missing passes with more       │
│     aggressive retrieval                  │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│  4. SYNTHESIS PASS (with Reflection)      │
│     - Integrate all evidence blocks       │
│     - Resolve contradictions              │
│     - Generate structured answer          │
│     - Build charts, metrics, citations    │
│     - Quality self-reflection loop        │
└──────────────┬───────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────┐
│  5. AnswerArtifact                       │
│     {                                     │
│       "sections": [...],                  │
│       "charts": [...],                    │
│       "metrics": [...],                   │
│       "citations": [...],                 │
│       "confidence": 0.82,                 │
│       "memo_md": "..."                   │
│     }                                     │
│                                           │
│  6. Optional Export: PDF / DOCX / XLSX   │
└──────────────────────────────────────────┘
```

### 5.3 User Onboarding Flow

```
┌──────────┐    ┌─────────┐    ┌────────────┐    ┌───────────┐
│ Landing  │───▶│ Google  │───▶│ Get Started│───▶│ Upload    │
│ Page     │    │ or Email│    │ Page       │    │ Portfolio │
│          │    │ Signup  │    │            │    │           │
└──────────┘    └────┬────┘    └────────────┘    └─────┬─────┘
                     │                                 │
                     ▼               ┌─────────────────┼───────────┐
              ┌──────────┐          │                              │
              │ JWT      │          ▼               ▼              ▼
              │ Minted   │    ┌──────────┐  ┌──────────┐  ┌───────────┐
              └──────────┘    │ CAS/PDF  │  │ CSV/XLSX │  │Screenshot │
                              │ Upload   │  │ Upload   │  │ Upload    │
                              └────┬─────┘  └────┬─────┘  └─────┬─────┘
                                   │              │               │
                                   ▼              ▼               ▼
                              ┌───────────────────────────────────────┐
                              │         PARSING PIPELINE               │
                              │  CAS ─▶ casparser ─▶ positions         │
                              │  PDF ─▶ PyMuPDF/Azure DI ─▶ positions  │
                              │  CSV ─▶ pandas ─▶ positions            │
                              │  Image─▶ GPT-4o Vision ─▶ positions    │
                              │  XLSX─▶ openpyxl ─▶ positions          │
                              └──────────────────┬────────────────────┘
                                                 │
                                                 ▼
                              ┌───────────────────────────────────────┐
                              │         EXTRACTION REVIEW              │
                              │  Positions: [{symbol, quantity, cost}]│
                              │  ISIN Resolution → NSE/BSE symbols      │
                              │  Portfolio Guardrails validation        │
                              │  → Show user for confirmation           │
                              └──────────────────┬────────────────────┘
                                                 │
                                                 ▼
                              ┌───────────────────────────────────────┐
                              │  Confirm → Save to Portfolio Mirror     │
                              │  Set onboarding_status = 'onboarded'   │
                              │  Redirect to Dashboard                 │
                              └───────────────────────────────────────┘
```

### 5.4 Content Automation Flow

```
┌────────────────────────────┐
│   OFFICIAL MONITOR         │
│   (Polling every 30 min)   │
│                            │
│  ┌──────┐ ┌──────┐ ┌─────┐│
│  │ SEBI │ │ BSE  │ │ NSE ││  ← RSS feeds + scrapers
│  │ RSS  │ │ RSS  │ │ RSS ││
│  └──┬───┘ └──┬───┘ └──┬──┘│
│     └──────┬──┴──────┬───┘│
│            ▼          ▼    │
└────────────┬──────────┬────┘
             │          │
     Raw filings/announcements
             │
             ▼
┌────────────────────────────┐
│   FILING TRIAGE            │
│   Materiality classifier   │
│   ┌─────────────────────┐  │
│   │ Score 0-1 per filing │  │
│   │ > 0.7 → Article     │  │
│   │ 0.3-0.7 → Brief     │  │
│   │ < 0.3 → Skip        │  │
│   └─────────────────────┘  │
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│   FLASH CONTENT ENGINE     │
│   1. Research context       │
│   2. Synthesis              │
│   3. Structured article     │
│      - Headline             │
│      - Summary              │
│      - Analysis body        │
│      - Market impact        │
│      - Charts/metrics       │
│      - Citations            │
│      - Cover image prompt   │
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│   EDITORIAL REVIEW         │
│   - Livemint dedupe check   │
│   - Accuracy validation     │
│   - SEO metadata generation │
│   → Draft status           │
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│   PUBLISH                  │
│   - Write to insights/ dir │
│   - Update sitemap         │
│   - Submit to Google       │
│     Search Console         │
│   - Mirror to public hub   │
└────────────────────────────┘
```

### 5.5 IKG Data Pipeline

```
┌────────────────────────────────────────────────────────────┐
│                     APSCHEDULER (Cron)                     │
│                                                            │
│  Every 6h ─▶ NSE Corporate Filings Scraper                 │
│  Every 12h─▶ BSE Announcements Scraper                     │
│  Every 24h─▶ SEBI Enforcement Orders Scraper               │
│  Every 24h─▶ MCA Director/Company Data Scraper              │
│  Quarterly─▶ Shareholding Pattern Scraper                  │
│  Daily    ─▶ BSE End-of-Day Data Scraper                   │
│  Weekly   ─▶ Annual Report Extraction (Docling + Azure DI) │
│  Weekly   ─▶ Governance Score Recompute                    │
└──────────────────────┬─────────────────────────────────────┘
                       │
                       ▼ Dispatch to Celery
┌────────────────────────────────────────────────────────────┐
│                    CELERY WORKER POOL                       │
│  10 concurrent threads across 6 queues:                    │
│                                                            │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌───────────┐       │
│  │  nse    │ │  bse    │ │  sebi   │ │ documents │       │
│  │ queue   │ │  queue  │ │  queue  │ │  queue    │       │
│  └────┬────┘ └────┬────┘ └────┬────┘ └─────┬─────┘       │
│       └──────┬─────┴──────┬────┴──────┬────┘              │
│              │            │           │                    │
│  ┌──────────┴────────────┴───────────┴────────────┐      │
│  │        POSTGRESQL 16 (IKG Database)             │      │
│  │  - companies, directors, financial facts         │      │
│  │  - shareholding, enforcement, XBRL facts         │      │
│  │  - index constituents                           │      │
│  └──────────┬──────────────────────────────────────┘      │
│             │                                              │
│  ┌──────────┴──────────┐                                   │
│  │                     │                                   │
│  ▼                     ▼                                   │
│ ┌───────┐     ┌────────────┐                               │
│ │Qdrant │     │   Neo4j    │                               │
│ │Vector │     │  Graph DB  │                               │
│ │Embed  │     │            │                               │
│ └───────┘     │ - Companies│                               │
│               │ - Directors│                               │
│               │ - Edges    │                               │
│               │   (inter-  │                               │
│               │   locks,   │                               │
│               │   filings) │                               │
│               └────────────┘                               │
└────────────────────────────────────────────────────────────┘
```

### 5.6 Portfolio Analytics Flow

```
User Portfolio Mirror (PostgreSQL)
    │
    │ positions: [{symbol, quantity, avg_cost, isin, ...}]
    │
    ▼
┌───────────────────────────────────────────────────┐
│              ANALYTICS COMPUTATION                 │
│                                                   │
│  ┌─────────────────────┐ ┌─────────────────────┐  │
│  │ CORE ANALYTICS       │ │ GOVERNANCE X-RAY    │  │
│  │ - Portfolio value    │ │ - IKG score lookup  │  │
│  │ - Day change P&L     │ │   per holding       │  │
│  │ - Total returns      │ │ - Red/orange/green  │  │
│  │ - XIRR               │ │   classification    │  │
│  │ - Beta, Sharpe,      │ │ - Board quality     │  │
│  │   Sortino ratios     │ │ - Enforcement flags │  │
│  └─────────────────────┘ └─────────────────────┘  │
│                                                   │
│  ┌─────────────────────┐ ┌─────────────────────┐  │
│  │ SECTOR ANALYSIS      │ │ STRESS TEST          │  │
│  │ - Sector weights     │ │ - 2008-style crash  │  │
│  │ - Sub-sector drill   │ │ - COVID-style crash  │  │
│  │ - Concentration      │ │ - Interest rate      │  │
│  │   risk metrics       │ │   shock              │  │
│  └─────────────────────┘ │ - Monte Carlo (1000   │  │
│                           │   simulations)       │  │
│  ┌─────────────────────┐ └─────────────────────┘  │
│  │ TAX SUMMARY (India)  │                         │
│  │ - LTCG (>1Y holdings)│ ┌─────────────────────┐  │
│  │ - STCG (<1Y holdings)│ │ DIVIDEND TRACKING   │  │
│  │ - Tax liability est. │ │ - Historical          │  │
│  └─────────────────────┘ │ - Calendar            │  │
│                           │ - Yield analysis      │  │
│  ┌─────────────────────┐ └─────────────────────┘  │
│  │ ALERTS & ACTIONS     │                         │
│  │ - Over-concentration │ ┌─────────────────────┐  │
│  │ - Governance risk    │ │ AI COMMENTARY       │  │
│  │ - Earnings calendar  │ │ - LLM generates      │  │
│  │ - Stop-loss breach   │ │   natural-language   │  │
│  │ - Corp action alert  │ │   portfolio review   │  │
│  └─────────────────────┘ └─────────────────────┘  │
│                                                   │
└───────────────────────┬───────────────────────────┘
                        │
                        ▼
              Frontend Dashboard
```

---

## 6. Multi-Agent Research Engine (FinAgent)

### 6.1 Architecture

The FinAgent is a **multi-agent LLM orchestration system** designed for equity research. It coordinates 10+ specialist AI agents that run in **parallel waves** based on dependency ordering.

```
┌─────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR                          │
│  (backend/finagent/agents/orchestrator.py)               │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │              WAVE SCHEDULING                      │   │
│  │  Agent dependency graph → topological sort →     │   │
│  │  parallel waves (asyncio.gather per wave)        │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │              CONTEXT MANAGEMENT                   │   │
│  │  Per-agent context loaders → context_window_     │   │
│  │  budget enforcement → token counting             │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │              QUALITY CONTROL                      │   │
│  │  Grader agent → blind-spot agent → verifier      │   │
│  │  → reflection loop (re-run if < threshold)      │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### 6.2 Specialist Agents

| Agent | File | Domain | Key Outputs |
|-------|------|--------|-------------|
| **Financials** | `specialists/financials.py` | P&L, Balance Sheet, Cash Flow | Revenue CAGR, margin trends, ROE/ROCE, FCF yield, debt ratios |
| **Valuation** | `specialists/valuation.py` | DCF, multiples | Intrinsic value, P/E 5Y range, EV/EBITDA, PEG ratio, DCF with sensitivity |
| **Risk** | `specialists/risk.py` | Risk factors | Beta, VaR, concentration risk, regulatory risk, operational risk, geopolitical |
| **Governance** | `specialists/governance.py` | Corporate governance | Board composition, related-party transactions, SEBI orders, promoter pledges |
| **Competitor** | `specialists/competitor.py` | Peer comparison | Market share, positioning, moat analysis, competitive advantages |
| **Macro** | `specialists/macro.py` | Macroeconomic | GDP growth linkage, interest rate sensitivity, currency exposure, sector outlook |
| **News** | `specialists/news.py` | News sentiment | Sentiment score, key events timeline, market impact analysis |
| **Technical** | `specialists/technical.py` | Price action | Support/resistance, RSI, MACD, moving averages, volume analysis |
| **Accounting** | `specialists/accounting.py` | Forensic accounting | Red flags, earnings quality, auditor opinion, related-party analysis |
| **Community** | `specialists/community.py` | Social sentiment | Reddit/HN/StockTwits sentiment, trending topics, retail interest |

### 6.3 Agent Execution Example

```python
# Orchestrator schedules specialists in waves:

# Wave 0 — Independent (no dependencies)
wave_0 = asyncio.gather(
    financials_agent.run(query, context),      # Financial statements
    news_agent.run(query, context),            # News + sentiment
)

# Wave 1 — Depends on Wave 0 outputs
wave_1 = asyncio.gather(
    valuation_agent.run(query, context, deps={financials_result}),
    risk_agent.run(query, context, deps={financials_result, news_result}),
    governance_agent.run(query, context, deps={financials_result}),
    competitor_agent.run(query, context, deps={financials_result}),
)

# Wave 2 — Depends on all prior outputs
wave_2 = asyncio.gather(
    macro_agent.run(query, context, deps={financials, competitor}),
    technical_agent.run(query, context, deps={risk, valuation}),
    community_agent.run(query, context, deps={news}),
    accounting_agent.run(query, context, deps={financials}),
)

# Quality gates
blindspot_result = blindspot_agent.run(all_results)
quality_score = grader_agent.score(all_results)
if quality_score < threshold:
    gap_fill_rerun(query, target_gaps)
```

### 6.4 Reflection Loop

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Generate  │───▶│  Grade   │───▶│ <threshold│───▶│ Gap-fill │
│ response  │    │ quality  │ NO │           │ YES│ re-run   │
└──────────┘    └──────────┘    └─────┬─────┘    └────┬─────┘
                                      │               │
                                      ▼               │
                              ┌──────────┐    ◄───────┘
                              │  Done    │    (up to 3 iterations)
                              └──────────┘
```

### 6.5 LLM Provider Resolution

```python
# runtime_provider.py
# Resolves which LLM to use based on task + availability:

For synthesis:   OpenAI GPT-5.4-mini (primary) → Azure Foundry (fallback)
For sub-agents:  OpenAI GPT-4o-mini (primary) → Azure Foundry (fallback) → xAI Grok-3 (fallback)
For embeddings:  OpenAI text-embedding-3-small
For intent:      OpenAI GPT-4o-mini
```

---

## 7. Intelligent Knowledge Graph (IKG)

### 7.1 Overview

The IKG is a **comprehensive knowledge base of Indian companies** built from regulatory data sources. It combines:

- **Relational data** (PostgreSQL 16) — structured financials, directors, filings
- **Vector embeddings** (Qdrant) — semantic search over documents
- **Graph data** (Neo4j) — director interlock networks, corporate relationships

### 7.2 Data Sources

| Source | Data | Frequency |
|--------|------|-----------|
| **NSE Corporate Filings** | Financial results, press releases, announcements | Every 6 hours |
| **BSE Announcements** | Same as NSE + additional filings | Every 12 hours |
| **SEBI Enforcement** | Orders, adjudications, settlements | Daily |
| **MCA (Ministry of Corporate Affairs)** | Company master data, director details | Daily |
| **Annual Reports** | Full PDF extraction via Docling + Azure DI | Weekly |
| **XBRL Filings** | Structured financial facts (P&L, BS, CF) | Weekly |
| **Shareholding Patterns** | Promoter, FII, DII, public holdings | Quarterly |
| **BSE EOD Data** | Daily prices, volumes, market cap | Daily |
| **Conference Call Transcripts** | Management commentary | Event-driven |

### 7.3 Evidence-Based Governance Scoring

```
┌─────────────────────────────────────────────────────────────┐
│                GOVERNANCE SCORING PIPELINE                   │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ SEBI Orders  │  │ Auditor      │  │ Shareholding        │ │
│  │ - Penalties  │  │ - Qualified  │  │ - Promoter pledge % │ │
│  │ - Bans       │  │   opinions   │  │ - FII confidence    │ │
│  │ - Warnings   │  │ - Auditor    │  │ - Pledged promoter  │ │
│  └──────┬───────┘  │   changes    │  └──────────┬──────────┘ │
│         │          └──────┬───────┘             │            │
│         ▼                ▼                     ▼            │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              WEIGHTED SCORING ENGINE                     │ │
│  │                                                         │ │
│  │  Regulatory:    30% weight  │  Board Independence: 20%  │ │
│  │  Related-Party: 20% weight  │  Auditor Quality:    10%  │ │
│  │  Promoter Pledge:15% weight │  Earnings Quality:   15%  │ │
│  │                                                         │ │
│  │  Total Score: 0-100 (higher = better governance)        │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                             │
│  Output:                                                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Score  │ Label          │ Color  │ Action            │    │
│  │────────│────────────────│────────│───────────────────│    │
│  │ 80-100 │ Excellent      │ Green  │ No concerns        │    │
│  │ 60-79  │ Fair           │ Yellow │ Monitor            │    │
│  │ 40-59  │ Warning        │ Orange │ Caution advised    │    │
│  │ 0-39   │ Red Flag       │ Red    │ Serious concerns   │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 7.4 Director Network Analysis

```
Neo4j Graph Query:
  MATCH (c:Company)<-[:DIRECTOR_OF]-(d:Director)-[:DIRECTOR_OF]->(other:Company)
  WHERE c.cin = $cin
  RETURN d, other

Output: Board interlock map showing:
  - Common directors across companies
  - Network density metrics
  - Potential conflict of interest patterns
```

### 7.5 Company Provenance (Citation-Backed Facts)

```
For any company fact, the system traces back to the source filing:

Example:
  "TCS reported ₹2,45,315 Cr revenue in FY2025"
  └── Source: NSE Corporate Filing #12345 (2025-04-10)
      ├── URL: https://nsearchives.nseindia.com/...
      ├── Filing Type: Annual Audited Results
      ├── Page: 3, Paragraph: 2
      └── Extraction Date: 2025-04-11
```

---

## 8. Portfolio Analytics Engine

### 8.1 Core Modules

```
portfolio/
├── analytics.py          # Returns, risk metrics, allocation
├── sectors.py            # Sector/sub-sector classification
├── news.py               # Per-holding + portfolio-level news
├── alerts.py             # Rule-based alert computation
├── stress_test.py        # Monte Carlo + historical scenarios
├── tax.py                # Indian capital gains tax (LTCG/STCG)
├── dividends.py          # Yield, history, calendar
├── corporate_actions.py  # Bonus, splits, buybacks notification
├── governance_xray.py    # IKG governance overlay per holding
├── action_queue.py       # AI-generated daily recommendations
├── holding_detail.py     # Single holding deep dive
├── commentary.py         # LLM natural language portfolio review
└── mf_analytics.py       # Mutual fund specific analysis
```

### 8.2 Stress Test Examples

```
Scenario: "2008 Financial Crisis"
  - Nifty 50 drawdown: -55%
  - Portfolio impact: -48% (better diversified)
  - Max single stock drawdown: -82%

Scenario: "COVID-19 Crash (Mar 2020)"
  - Nifty 50 drawdown: -38%
  - Portfolio impact: -31%

Scenario: "Interest Rate Shock (+200 bps)"
  - Financial sector impact: -15%
  - Real estate impact: -22%
  - Tech sector impact: -5%

Monte Carlo (1000 simulations, 1Y horizon):
  - 95% VaR: -₹3,25,000
  - Expected shortfall: -₹4,10,000
  - Best case (95th %ile): +₹6,80,000
```

---

## 9. Content Automation Engine

### 9.1 Flash Content Engine

The Flash Content Engine automatically generates research articles from official filings:

```
flash_engine.py (~4979 lines)

Core workflow:
  1. Monitor official sources (SEBI/BSE/NSE RSS)
  2. Ingest new filings/announcements
  3. Filing Triage → classify materiality
  4. Research Context → fetch company background, sector, peers
  5. Article Generation → LLM produces structured article
  6. Editorial Review → accuracy, originality, SEO checks
  7. Cover Image → DALL-E prompt generation
  8. Publish → write HTML, update sitemap, submit to Google
```

### 9.2 Article Structure

```json
{
  "slug": "tcs-q4-fy2025-results-analysis",
  "headline": "TCS Q4 FY2025: Revenue Hits ₹62,000 Cr, Margins Expand to 26%",
  "summary": "Tata Consultancy Services reported Q4 revenue...",
  "sections": [
    {
      "heading": "Revenue Analysis",
      "content": "...",
      "chart": { "type": "bar", "title": "Quarterly Revenue Trend", ... }
    },
    {
      "heading": "Margin Analysis",
      "content": "...",
      "callout": { "type": "info", "text": "EBIT margin expanded 120bps YoY" }
    },
    {
      "heading": "Segment Performance",
      "content": "...",
      "table": { "headers": ["Vertical", "Revenue", "Growth"], "rows": [...] }
    },
    {
      "heading": "Market Reaction",
      "content": "...",
      "metric_cards": [
        { "label": "Stock Move", "value": "+3.2%", "trend": "up" }
      ]
    }
  ],
  "citations": [
    { "source": "NSE Filing", "url": "...", "text": "..." }
  ],
  "seo": {
    "meta_description": "TCS Q4 FY2025 results analysis: Revenue, margins...",
    "keywords": ["TCS", "Q4 Results", "IT Sector"],
    "cover_image_alt": "TCS Q4 FY2025 financial results chart"
  }
}
```

---

## 10. Frontend Architecture

### 10.1 Component Hierarchy

```
App (HashRouter)
│
├── AuthProvider (React Context)
│   ├── user, token, isAuthenticated, isOnboarded
│   ├── login(), logout(), refreshUser()
│   └── Toast notifications + WhatsApp invite prompt
│
├── TelemetryRouteTracker
│   └── Tracks page views via Azure App Insights
│
├── CommandPalette (global, Ctrl+K)
│
└── Routes
    │
    ├── /            → LandingPage      (Public)
    ├── /pricing     → Pricing          (Public)
    ├── /testimonials→ Testimonials     (Public)
    ├── /features    → Features         (Public)
    ├── /contact     → ContactUs        (Public)
    ├── /login       → Login            (PublicRoute → redirect if authenticated)
    │
    ├── /app         → GatewayPage      (ProtectedRoute)
    ├── /insights    → InsightsStudio   (ProtectedRoute)
    │
    ├── /onboarding/manual   → ManualEntry    (Protected, pre-onboarding)
    ├── /onboarding/upload   → UploadPage     (Protected, pre-onboarding)
    ├── /onboarding/watchlist→ WatchlistStep  (Protected, pre-onboarding)
    │
    └── /dashboard   → Dashboard        (ProtectedRoute, requires onboarded)
        │
        └── AppShell
            ├── Sidebar (Logo, navigation, user profile)
            │
            └── Content Area
                ├── QuickPulse (animated market ticker bar)
                ├── IndexTickerCard × N (Nifty, Sensex, NASDAQ, S&P 500, BTC, USDINR)
                │
                ├── PortfolioTable
                │   └── Row: AssetHistoryModal, CompanyIntelModal
                │
                ├── GovernancePanel (per-holding governance overlay)
                ├── WatchlistCard (custom watchlist)
                │
                ├── Chat Interface
                │   ├── ChatInput (text input + enter key)
                │   ├── SuggestedPrompts (contextual suggestions)
                │   └── MessageBubble (per message)
                │       ├── User message (plain text)
                │       └── AI response
                │           ├── AgentThinking (animated dots + step label)
                │           ├── RichResponse
                │           │   ├── SectionBlock (heading + text)
                │           │   ├── CalloutBlock (warning/info/success)
                │           │   ├── MetricCard (single metric display)
                │           │   ├── TableBlock (sortable data table)
                │           │   ├── Chart (AreaChart, BarChart, DonutChart,
                │           │   │         RadarChart, TreemapChart)
                │           │   └── HtmlArtifact (embedded HTML)
                │           └── ExportPanel (download PDF/DOCX/XLSX)
                │
                ├── ResearchTimeline (session history)
                ├── RecentInsights (latest published articles)
                ├── QuickActions (one-click research prompts)
                │
                └── InsightsStudio Mode
                    ├── ArticleQueueTable
                    ├── ArticleReader
                    ├── DraftReviewDrawer
                    └── FlashJobMonitor
```

### 10.2 API Client Layer

```typescript
// frontend/src/api/client.ts (~2200+ lines)

// Core pattern — all API calls go through this client:
async function apiCall<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getAuthToken();
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...options,
    headers: {
      ...options?.headers,
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });
  if (res.status === 401) { /* redirect to login */ }
  if (!res.ok) { throw new ApiError(res); }
  return res.json();
}

// SSE Stream consumer:
function streamEvents(sessionId: string, onEvent: (evt) => void): AbortController {
  const controller = new AbortController();
  const url = `${BACKEND_URL}/sessions/${sessionId}/stream`;
  // Uses fetch with streaming, parses SSE protocol manually
  // Auto-reconnect on disconnect with Last-Event-ID header
  return controller;
}

// Auth calls:    apiClient.auth.*
// Research:      apiClient.research.*
// Portfolio:     apiClient.portfolio.*
// Market:        apiClient.market.*
// Company:       apiClient.company.*
// Content:       apiClient.content.*
// Payments:      apiClient.payments.*
```

### 10.3 Auth Context

```typescript
// frontend/src/context/AuthContext.tsx (~626 lines)

interface AuthState {
  user: UserProfile | null;
  token: string | null;
  isAuthenticated: boolean;
  isOnboarded: boolean;
  isLoading: boolean;
}

// Google OAuth:
// 1. Load Google Identity Services script
// 2. google.accounts.id.initialize({ client_id, callback: handleCredentialResponse })
// 3. POST /auth/google with credential
// 4. Store JWT, set user, redirect

// Email Auth:
// 1. POST /auth/signup or /auth/login
// 2. Store JWT, set user, redirect

// Token persistence:
// - httpOnly cookie (auto-included with requests)
// - localStorage (for API Authorization header)
// - Token refresh on app mount via GET /auth/me
```

---

## 11. Database Schema

### 11.1 Supabase (User-Facing PostgreSQL)

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
  onboarding_status TEXT DEFAULT 'pending',  -- 'pending' | 'onboarding' | 'onboarded'
  onboarded_at TIMESTAMPTZ,
  deep_runs_used INTEGER DEFAULT 0,
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

-- contacts: Scraped financial advisor leads
CREATE TABLE public.contacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source TEXT,                  -- 'sebi' | 'linkedin' | 'amfi'
  name TEXT,
  email TEXT,
  phone TEXT,
  linkedin_url TEXT,
  designation TEXT,
  organisation TEXT,
  sebi_registration TEXT,
  priority_score INTEGER DEFAULT 0,
  opted_out BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- outreach_leads / outreach_sends / outreach_events
-- Email/SMS outreach campaign management

-- outreach_unsubscribes: GDPR-compliant unsubscribe
CREATE TABLE public.outreach_unsubscribes (
  email TEXT PRIMARY KEY,
  unsubscribed_at TIMESTAMPTZ DEFAULT NOW()
);

-- export_jobs: Document export tracking
CREATE TABLE public.export_jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES profiles(id),
  session_id TEXT,
  format TEXT,                  -- 'pdf' | 'docx' | 'xlsx'
  status TEXT DEFAULT 'pending',-- 'pending' | 'processing' | 'done' | 'error'
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

-- scrape_jobs / scrape_checkpoints / extraction_rules
-- Background scraping and data extraction job management
```

### 11.2 IKG Database (PostgreSQL 16 — Separate Instance)

```sql
-- Company master data
companies (cin, name, status, incorporation_date, category, sub_category,
           class, authorised_cap, paidup_cap, state, roc_code)

-- Directors
directors (din, name, designation, appointment_date, cin)

-- Financial facts (XBRL)
financial_facts (cin, fact_id, concept, value, unit, period, filing_date, source_url)

-- Shareholding patterns
shareholding (cin, quarter, promoter_pct, fii_pct, dii_pct, public_pct,
              pledged_promoter_pct, total_shares)

-- SEBI enforcement
sebi_enforcement (order_id, date, cin, company_name, type, penalty_amount,
                  summary, url)

-- Annual reports
annual_reports (cin, year, source_url, extracted_text, key_findings)

-- Index constituents
index_constituents (index_name, symbol, isin, weight, effective_date)

-- Governance scores (computed)
governance_scores (cin, score, regulatory_sub_score, board_sub_score,
                   rpt_sub_score, promoter_sub_score, computed_at)
```

### 11.3 Neo4j Graph Schema (Director/Company Network)

```
(:Company {cin, name, status})
(:Director {din, name, gender})
(:Filings {filing_id, type, date, cin})

Relationships:
  (:Director)-[:DIRECTOR_OF {designation, from_date, to_date}]->(:Company)
  (:Company)-[:FILED {type, date}]->(:Filings)
  (:Director)-[:BOARD_INTERLOCK {via_company}]->(:Director)
  (:Company)-[:PEER_OF {similarity_score}]->(:Company)
```

---

## 12. State Management

### 12.1 Backend State

| Store | Technology | Scope | Persistence |
|-------|-----------|-------|-------------|
| **Session Store** | In-memory dict + JSON files | Per session | Disk (JSON), volatile on restart |
| **Event Bus** | `asyncio.Queue` per session + JSONL append | Per session | Disk (JSONL), capped at max entries |
| **Memory Store** | Tiered (episodic/semantic/procedural) | Per user | Supabase PostgreSQL / SQLite fallback |
| **Portfolio Mirror** | PostgreSQL (Supabase) | Per user | Durable |
| **TTL Cache** | In-memory dict + Redis optional | Global | In-memory (LRU + TTL) |
| **Token Usage** | PostgreSQL (Supabase) | Per user, weekly | Durable |
| **Rate Limiting** | PostgreSQL sliding window | Per endpoint class | Durable |
| **JWT Blacklist** | SQLite / PostgreSQL | Global | Persistent |
| **Pipeline Runs** | PostgreSQL (IKG) | Global | Durable |

### 12.2 Frontend State

| Store | Technology | Persistence |
|-------|-----------|-------------|
| **Auth** | React Context + localStorage/sessionStorage | Browser storage |
| **UI State** | Component `useState`/`useEffect` | None (in-memory) |
| **Onboarding** | localStorage keyed by email | Browser storage |
| **Manual Portfolio** | localStorage | Browser storage |
| **SSE Connection** | Custom fetch stream | In-memory |
| **Telemetry Session** | Azure App Insights | Azure cloud |

---

## 13. Authentication & Security

### 13.1 Authentication Methods

```
┌──────────────────┐     ┌─────────────────┐     ┌──────────────────┐
│  Google OAuth    │     │  Email/Password │     │  Supabase JWT    │
│  (GIS popup)     │     │  (Supabase Auth)│     │  (direct token)  │
└────────┬─────────┘     └────────┬────────┘     └────────┬─────────┘
         │                        │                        │
         ▼                        ▼                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FastAPI Auth Guard                            │
│  auth_guard.py                                                   │
│                                                                  │
│  get_current_user() extracts token from:                         │
│    1. Authorization: Bearer <token> header                       │
│    2. prospektlab_token cookie (httpOnly)                        │
│    3. ?token=<token> query param (GET requests only)             │
│                                                                  │
│  Token validation:                                               │
│    - Verify JWT signature (HS256)                                │
│    - Check issuer (prospektlab) and audience (prospektlab-api)  │
│    - Check expiry (30 days) with 60s clock skew                  │
│    - Check jti against blacklist (revoked tokens)                │
│    ─ Accept fallback: verify Supabase-issued JWT with Supabase  │
│       project secret                                              │
└─────────────────────────────────────────────────────────────────┘
```

### 13.2 Authorization Levels

```
Token Budget Enforcement:
  - Free plan:   1,000,000 tokens/week, 1 deep research run/week
  - Pro plan:    2,000,000 tokens/week, unlimited deep research
  - Checked on research/deep/content generation endpoints

Session Ownership (BOLA protection):
  - verify_session_ownership(): tenant_id + email must match session metadata
  - Applied to all /sessions/{id}/* endpoints

Admin Gates:
  - /admin/* endpoints: email must be in allowed list
  - /ops/control-tower: email allowlist (CONTROL_TOWER_ALLOWED_EMAILS)
  - /metrics/snapshot: email allowlist (FINAGENT_METRICS_ADMIN_EMAILS)
  - Admin reset: requires ADMIN_RESET_KEY env var
```

### 13.3 Rate Limiting

```
Rate limiter classes (sliding window in PostgreSQL):

  research_rate_limiter:    5 requests  / 60 seconds
  auth_rate_limiter:       10 requests  / 60 seconds
  default_rate_limiter:   100 requests  / 60 seconds
```

### 13.4 Security Hardening

```
Headers:
  Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline' https:;
    img-src 'self' data: https:; connect-src 'self' https://*.supabase.co
    (per-route variations for ops, insights, main app)
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  Strict-Transport-Security: max-age=31536000

Input Safety:
  - Prompt injection guard (regex patterns for known attacks: "ignore instructions",
    "DAN", "jailbreak", "system prompt", etc.)
  - File upload: magic byte validation, size limits, extension whitelist
  - HTML sanitization on output
  - CORS: whitelist of allowed origins via CORS_ORIGINS env var

Cookie Security:
  - httpOnly: true
  - SameSite: Lax
  - Secure: true (in production)
```

---

## 14. Deployment & Infrastructure

### 14.1 Deployment Topology

```
┌──────────────────────────────────────────────────────────────────────┐
│                          AWS CLOUD                                    │
│                                                                      │
│  ┌─────────────────────┐         ┌──────────────────────────────┐   │
│  │   AWS Amplify        │         │   AWS ECS Fargate             │   │
│  │   (Frontend SPA)     │  HTTPS  │   (Backend Gateway)           │   │
│  │                      │────────▶│                               │   │
│  │  Region: us-east-1   │         │  Task: 1 vCPU, 2GB RAM       │   │
│  │  Build: npm ci &&    │         │  Port: 8080                   │   │
│  │  vite build          │         │  Image: ECR                   │   │
│  │  Artifacts: dist/    │         │  Auto-scaling: 1-4 tasks     │   │
│  └─────────────────────┘         └──────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │   AWS CodeBuild + CodePipeline                                │   │
│  │  Source: GitHub → Build: Docker → Push: ECR → Deploy: ECS    │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                          AZURE CLOUD                                  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │   Azure Linux VM (IKG Workers)                                 │   │
│  │                                                                │   │
│  │   Docker Compose stack:                                        │   │
│  │   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐      │   │
│  │   │ Postgres │ │  Redis   │ │  Qdrant  │ │  Celery   │      │   │
│  │   │    16    │ │    7     │ │  Vector  │ │  Workers  │      │   │
│  │   │          │ │ (broker) │ │    DB    │ │ (10 thr.) │      │   │
│  │   └──────────┘ └──────────┘ └──────────┘ └───────────┘      │   │
│  │   ┌──────────┐ ┌──────────────┐                              │   │
│  │   │  Neo4j   │ │  Scheduler   │                              │   │
│  │   │  Graph   │ │ (APScheduler)│                              │   │
│  │   └──────────┘ └──────────────┘                              │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │   Azure Communication Services (ACS)                           │   │
│  │   - Email delivery (verification, notifications)               │   │
│  │   - SMS delivery (verification OTP)                            │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │   Azure Monitor + Application Insights                         │   │
│  │   - Backend telemetry                                          │   │
│  │   - Frontend telemetry                                         │   │
│  │   - IKG pipeline monitoring                                    │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────┐
│                          SUPABASE CLOUD                               │
│                                                                      │
│  Managed PostgreSQL:                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐              │
│  │ profiles │ │ token_   │ │ payments │ │ contacts │               │
│  │          │ │ usage    │ │          │ │          │               │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                           │
│  │ outreach │ │ verif.   │ │ export   │                           │
│  │  tables  │ │  codes   │ │  jobs    │                           │
│  └──────────┘ └──────────┘ └──────────┘                           │
│                                                                      │
│  Auth Service:                                                       │
│  - Google OAuth social login                                         │
│  - Email/password with Admin API                                     │
│  - JWT verification via project secret                               │
└──────────────────────────────────────────────────────────────────────┘
```

### 14.2 Docker Compose — IKG Stack

```yaml
# deployment/docker-compose.ikg.yml (simplified)

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: ikg
      POSTGRES_USER: ikg_user
      POSTGRES_PASSWORD: ${IKG_DB_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage

  neo4j:
    image: neo4j:5-community
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD}

  celery-worker:
    build:
      context: ..
      dockerfile: deployment/Dockerfile.ikg-worker
    command: celery -A finagent.ikg.pipeline.celery_app worker
             --concurrency=10
             --queues=nse,bse,sebi,documents,financials,graph
    depends_on:
      - postgres
      - redis
      - qdrant
      - neo4j

  scheduler:
    build:
      context: ..
      dockerfile: deployment/Dockerfile.ikg-worker
    command: python -m finagent.ikg.pipeline.scheduler
    depends_on:
      - postgres
      - redis
```

### 14.3 Background Services

| Service | Entry Point | Schedule |
|---------|-------------|----------|
| **Gateway periodic tasks** | `gateway/run.py` (FastAPI lifespan) | Every 5 min: reap completed tasks, cleanup old sessions, cleanup SQLite |
| **IKG Scheduler** | `finagent.ikg.pipeline.scheduler` | APScheduler cron: 6h/12h/24h intervals for different scrapers |
| **Celery Workers** | `finagent.ikg.pipeline.celery_app` | Continuous, 10 threads across 6 queues |
| **Dreaming Layer** | `finagent.dreaming.scheduler` | Nightly at 2 AM IST: consolidation, pattern detection, preloading |
| **Content Official Monitor** | `finagent.content.official_monitor` | Every 30 min: poll SEBI/BSE/NSE RSS |
| **Flash Content Engine** | `finagent.content.flash_engine` | On-demand: article generation from filings |

---

## 15. CI/CD Pipelines

### 15.1 Frontend (AWS Amplify)

```yaml
# amplify-buildspec.yml
version: 1
frontend:
  phases:
    preBuild:
      commands:
        - cd frontend
        - npm ci
        - echo "Backend URL: $BACKEND_API_URL"
    build:
      commands:
        - npx tsc
        - npx vite build --config vite.config.mjs
  artifacts:
    baseDirectory: frontend/dist
    files:
      - '**/*'
```

**Runtime Config Injection:**
```javascript
// frontend/public/env-config.js (generated at deploy time)
window.__ENV = {
  BACKEND_API_URL: "https://api.prospektlab.com",
  // Dynamically replaced based on environment
};
```

### 15.2 Backend (AWS CodeBuild)

```yaml
# buildspec.yml
phases:
  pre_build:
    commands:
      - echo "Logging into ECR..."
      - aws ecr get-login-password | docker login --username AWS --password-stdin $ECR_REPO
      - IMAGE_TAG=$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c 1-7)
  build:
    commands:
      - docker build -t $ECR_REPO:latest -t $ECR_REPO:$IMAGE_TAG .
      - docker push $ECR_REPO:latest
      - docker push $ECR_REPO:$IMAGE_TAG
  post_build:
    commands:
      - aws ecs update-service --cluster prospektlab-prod --service prospektlab-backend --force-new-deployment
```

### 15.3 IKG Workers (Manual Deployment)

```powershell
# deployment/deploy-azure-ikg.ps1
# 1. SSH into Azure VM
# 2. git pull latest code
# 3. docker-compose -f docker-compose.ikg.yml up -d --build
# 4. Verify: check_ikg_counts.sh
```

---

## 16. Configuration Reference

### 16.1 Environment Variables

#### Required

| Variable | Purpose |
|----------|---------|
| `JWT_SECRET` | HS256 signing key for local JWTs |
| `OPENAI_API_KEY` | OpenAI API key for LLM calls |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase service role key |
| `SUPABASE_JWT_SECRET` | Supabase project JWT secret for verifying Supabase tokens |
| `SUPABASE_DB_URL` | Direct PostgreSQL connection URL (postgres://...) |
| `IKG_DATABASE_URL` | IKG PostgreSQL connection URL |
| `CORS_ORIGINS` | Comma-separated allowed origins |

#### AI/LLM

| Variable | Default | Purpose |
|----------|---------|---------|
| `FINAGENT_MODEL` | `gpt-5.4-mini` | Default LLM for sub-agents |
| `FINAGENT_SYNTH_MODEL` | `gpt-5.4-mini` | LLM for synthesis |
| `FINAGENT_LIGHT_MODEL` | `gpt-4o-mini` | LLM for lightweight tasks (intent, contextualizer) |
| `AZURE_AI_FOUNDRY_API_KEY` | — | Azure Foundry endpoint key (fallback) |
| `XAI_API_KEY` | — | xAI Grok API key (final fallback) |
| `FINAGENT_TEMPERATURE` | `0.3` | LLM temperature |
| `FINAGENT_MAX_TOKENS` | `4096` | Max completion tokens |
| `FINAGENT_SYNTH_MAX_TOKENS` | `16384` | Max tokens for synthesis |

#### Quotas & Limits

| Variable | Default | Purpose |
|----------|---------|---------|
| `WEEKLY_TOKEN_LIMIT` | `1000000` | Free plan weekly token budget |
| `PRO_WEEKLY_TOKEN_LIMIT` | `2000000` | Pro plan weekly token budget |
| `FREE_WEEKLY_DEEP_RUNS` | `1` | Free plan deep research quota/week |

#### Payments

| Variable | Purpose |
|----------|---------|
| `RAZORPAY_KEY_ID` | Razorpay API key ID |
| `RAZORPAY_KEY_SECRET` | Razorpay API key secret |
| `VITE_RAZORPAY_KEY_ID` | Frontend Razorpay key (passed to React via Vite) |

#### Communication

| Variable | Purpose |
|----------|---------|
| `ACS_EMAIL_CONNECTION_STRING` | Azure email delivery endpoint |
| `ACS_SMS_CONNECTION_STRING` | Azure SMS delivery endpoint |
| `PROSPEKTLAB_FROM_EMAIL` | Sender email address |

#### Infrastructure

| Variable | Default | Purpose |
|----------|---------|---------|
| `PROSPEKTLAB_ENV` | — | `production` | `local` |
| `BACKEND_API_URL` | — | Backend URL (for frontend injection) |
| `FINAGENT_HOME` | `.finagent` | Agent state directory |
| `NSE_COOKIE_STRING` | — | NSE session bypass cookie for scrapers |
| `MCA_COMPANY_MASTER_CSV` | — | Path to company master CSV |
| `FINAGENT_DEFAULT_GEO` | `IN` | Default geography |
| `FINAGENT_EXCHANGE_SUFFIX` | `.NS` | Default exchange suffix |

#### Admin

| Variable | Purpose |
|----------|---------|
| `ADMIN_RESET_KEY` | Secret key for admin reset endpoint |
| `CONTROL_TOWER_ALLOWED_EMAILS` | Comma-separated emails for control tower access |
| `FINAGENT_METRICS_ADMIN_EMAILS` | Comma-separated emails for metrics access |

### 16.2 Python Settings (FinAgentSettings)

```python
# finagent/settings.py
@dataclass
class FinAgentSettings:
    model: str                        # GPT model for sub-agents
    synthesis_model: str              # GPT model for final synthesis
    light_model: str                  # Fast model for intent/contextualizer
    temperature: float = 0.3
    max_tokens: int = 4096
    synthesis_max_tokens: int = 16384
    default_geo: str = "IN"
    exchange_suffix: str = ".NS"
    max_refinement_rounds: int = 3     # Reflection loop iterations
    blind_spot_threshold: float = 0.6  # Quality threshold for re-runs
    search_web: bool = True
    search_news: bool = True
    search_social: bool = False        # Reddit/HN/StockTwits (opt-in)
```

---

## 17. Third-Party Integrations

### AI/LLM
| Provider | Service | Models Used |
|----------|---------|-------------|
| **OpenAI** | Chat Completions API | GPT-5.4-mini, GPT-4o-mini, text-embedding-3-small |
| **Azure AI Foundry** | OpenAI on Azure | GPT-4o-mini (fallback) |
| **xAI** | Grok API | Grok-3 (fallback) |

### Database & Storage
| Provider | Service | Purpose |
|----------|---------|---------|
| **Supabase** | Managed PostgreSQL | User data, payments, token usage, outreach |
| **Qdrant** | Vector Database | Embedding search for IKG documents |
| **Neo4j** | Graph Database | Director interlock networks, corporate relationships |
| **Redis** | In-memory store | Celery message broker, optional TTL cache |

### Cloud Services
| Provider | Service | Purpose |
|----------|---------|---------|
| **AWS ECS Fargate** | Container hosting | Backend gateway |
| **AWS Amplify** | Web hosting | Frontend SPA |
| **AWS CodeBuild** | CI/CD | Docker build + ECR push + ECS deploy |
| **AWS CodePipeline** | CI/CD | Orchestrate CodeBuild stages |
| **Azure VMs** | Virtual machines | IKG worker Docker Compose host |
| **Azure Communication Services** | Email + SMS | Verification codes, notifications |
| **Azure Document Intelligence** | AI document parsing | PDF → structured text for portfolio ingestion |
| **Azure Cognitive Search** | Full-text + semantic search | Document search for RAG |
| **Azure Application Insights** | Telemetry | Backend + frontend monitoring |
| **Azure Monitor** | Monitoring | IKG pipeline health |

### Data Sources
| Source | Type | Data |
|--------|------|------|
| **Yahoo Finance** | API | Quotes, history, indices, fundamentals |
| **NSE India** | Web scraping | Corporate filings, index constituents, equity snapshots |
| **BSE India** | Web scraping | Announcements, EOD data, shareholding patterns |
| **SEBI** | Web scraping | Enforcement orders, intermediary data |
| **MCA** | CSV / Web scraping | Company master data, director KMP data |
| **SEC EDGAR** | API | US company filings (Form 10-K, 10-Q, 8-K) |
| **Reddit** | API | Social sentiment (r/IndianStockMarket, r/stocks) |
| **Hacker News** | API | Tech/startup sentiment |
| **StockTwits** | API | Retail trader sentiment |
| **Wikipedia** | API | Entity data enrichment |
| **Google Search Console** | API | Sitemap submission for SEO |
| **RBI** | RSS | Monetary policy, circulars, press releases |
| **AMFI** | Web scraping | Mutual fund NAV, AUM data |
| **SearXNG** | Self-hosted search | Privacy-focused web search |
| **Crawl4AI** | Library | AI-optimized web crawling |
| **DuckDuckGo** | API | Web search |

### Auth & Payments
| Provider | Service | Purpose |
|----------|---------|---------|
| **Google Identity Services** | OAuth 2.0 | Social login |
| **Supabase Auth** | Auth Admin API | Email/password management |
| **Razorpay** | Payment Gateway | INR subscription payments |

### Document Processing
| Library/Service | Purpose |
|-----------------|---------|
| **casparser** | CAMS/KFintech CAS PDF parsing |
| **pypdf / PyMuPDF** | Generic PDF extraction |
| **openpyxl** | Excel file parsing |
| **python-docx** | DOCX generation for exports |
| **msoffcrypto-tool** | Password-protected Excel files |
| **Azure Doc Intelligence** | Cloud-based structured extraction |
| **Docling** | IBM's document understanding (annual reports) |
| **MinerU** | Document structure extraction |

### DevOps Tools
| Tool | Purpose |
|------|---------|
| **Docker** | Containerization |
| **Docker Compose** | Multi-service IKG stack |
| **uv** | Python package manager |
| **Playwright/Patchright** | Headless browser automation for scrapers |
| **fastmcp** | MCP server framework |
| **Celery** | Distributed task queue |
| **APScheduler** | Cron-based scheduling |

---

> **Document Version:** 1.0  
> **Generated:** June 2026  
> **Platform:** ProspektLab — Financial Intelligence Operating System

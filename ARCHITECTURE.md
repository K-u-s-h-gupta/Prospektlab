# PROSPEKTLAB Architecture

This document describes the complete architecture, workflow, and component breakdown of the ProspektLab platform — an AI-powered financial research system with India-first design.

---

## Table of Contents

1. [High-Level Architecture](#high-level-architecture)
2. [Technology Stack](#technology-stack)
3. [System Layers](#system-layers)
4. [Request Flow](#request-flow)
5. [Core Agent Loop](#core-agent-loop)
6. [Multi-Agent Orchestration](#multi-agent-orchestration)
7. [Deep Research (Multi-Pass)](#deep-research-multi-pass)
8. [MCP Server Layer](#mcp-server-layer)
9. [Portfolio System](#portfolio-system)
10. [Memory System](#memory-system)
11. [Entity Resolution & Geography](#entity-resolution--geography)
12. [Synthesis & Output](#synthesis--output)
13. [Data Layer & External Providers](#data-layer--external-providers)
14. [Frontend Architecture](#frontend-architecture)
15. [Gateway & API Endpoints](#gateway--api-endpoints)
16. [Security & Auth](#security--auth)
17. [Monitoring & Telemetry](#monitoring--telemetry)
18. [Deployment](#deployment)
19. [Data Flow Diagrams](#data-flow-diagrams)
20. [Complete File Inventory](#complete-file-inventory)

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     PRESENTATION LAYER                           │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  React 18 + Vite 5 + TypeScript 5 (Frontend/app/)          │  │
│  │  • Dashboard, Chat, Portfolio, Auth, Marketing Pages       │  │
│  │  • SSE event consumption for real-time agent progress      │  │
│  │  • HashRouter SPA with AuthContext                         │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                    HTTPS / SSE Stream
                              │
┌─────────────────────────────────────────────────────────────────┐
│                     APPLICATION LAYER                            │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  FastAPI Gateway (finagent/gateway/run.py)                 │  │
│  │  • Auth endpoints (local + Supabase JWT)                   │  │
│  │  • Research orchestration & SSE streaming                  │  │
│  │  • Portfolio ingestion & analytics                         │  │
│  │  • Intent classification, rate limiting, CORS              │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            │                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Core Agent Loop (finagent/run_agent.py)                   │  │
│  │  • Identify → Enrich → Search → Multi-Agent → Synthesis    │  │
│  │  • SessionBus event emission                               │  │
│  │  • Configurable depth/reflection/memory                    │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            │                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Multi-Agent Orchestrator (finagent/agents/)               │  │
│  │  10 specialist subagents in dependency-aware waves         │  │
│  │  + Verifier + Blind-spot detector                          │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                     TOOLING & DATA LAYER                          │
│  ┌────────────────────┐  ┌────────────────────────────────────┐ │
│  │  MCP Servers        │  │  Direct Data Tools                 │ │
│  │  • :8003 Discovery  │  │  • yfinance (quotes + fundamentals)│ │
│  │    (search, NSE,    │  │  • SEC EDGAR (company facts)       │ │
│  │    docs, research)  │  │  • India (Screener.in, Moneycontrol)│ │
│  │  • :8005 Quant       │  │  • Reddit, HackerNews, StockTwits │ │
│  │    (fundamentals,    │  │  • Wikipedia, News Feed, Forex    │ │
│  │    valuation, risk)  │  │  • DuckDuckGo search + scraping   │ │
│  └────────────────────┘  │  • Crawl4AI full-page extraction    │ │
│                          │  • SearXNG meta-search              │ │
│                          │  • Valuation Engine (deterministic) │ │
│                          └────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                     STORAGE LAYER                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  SQLite       │  │  Supabase    │  │  File System         │  │
│  │  .finagent/   │  │  PostgreSQL  │  │  memos/, sessions/   │  │
│  │  memory.sqlite3│  │  (auth+data) │  │  cache/, users/      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack

### Backend (Python 3.11+)

| Category | Technology | Purpose |
|----------|-----------|---------|
| Web Framework | FastAPI + Uvicorn | REST API, SSE streaming, static pages |
| LLM Provider | OpenAI (GPT-4o) | Primary model for synthesis, reflection, orchestration |
| Fallback LLM | xAI (Grok-3) | Via OpenAI-compatible endpoint |
| Agent Framework | LangGraph | Supervisor-based multi-agent orchestration |
| LLM Chaining | LangChain | LLM abstraction, tool integration |
| MCP Protocol | FastMCP (>=2.0.0) | Standalone tool servers (discovery + quant) |
| Data Validation | Pydantic (>=2.0.0) | Request/response schemas, data models |
| HTTP Client | httpx + aiohttp (async) | Shared HTTP client for all external API calls |
| Finance Data | yfinance (>=0.2.40) | Quotes, fundamentals, financial statements |
| Portfolio Math | PyPortfolioOpt | Portfolio optimization |
| Auth | PyJWT | JWT signing and validation |
| Chart Generation | matplotlib | Answer artifact charts |
| PDF Parsing | pymupdf (PyMuPDF), pypdf | Statement extraction |
| CAS Parsing | casparser | Indian eCAS (CAMS/KFintech) |
| Web Scraping | Crawl4AI, BeautifulSoup | Full page extraction with Chromium |
| Web Search | DuckDuckGo (duckduckgo_search) | Layered breadth searches |
| OCR | image_ingestion | Screenshot portfolio extraction |
| Doc Parsing | docling, feedparser, msoffcrypto-tool | Document ingestion pipeline |

### Frontend (TypeScript + React 18)

| Category | Technology | Purpose |
|----------|-----------|---------|
| Framework | React 18.3 | UI components and state |
| Build Tool | Vite 5.x | Dev server, HMR, production bundling |
| Language | TypeScript 5.2 | Type safety |
| Routing | react-router-dom v6 (HashRouter) | Client-side routing |
| Charts | Chart.js + react-chartjs-2 + chartjs-chart-treemap | Portfolio and market charts |
| Icons | Lucide React | UI iconography |
| Auth | Google Identity Services (GIS) | Google OAuth via inline script injection |
| Styling | CSS (custom design system) | Dark theme, glassmorphism, animations |

### Infrastructure

| Component | Technology |
|-----------|------------|
| Containerization | Docker (python:3.11-slim) |
| Container Registry | Amazon ECR |
| Orchestration | AWS ECS Fargate |
| Frontend Hosting | AWS Amplify |
| CI/CD | GitHub Actions + AWS CodeBuild |
| Auth Database | Supabase (PostgreSQL) |
| Local Storage | SQLite (WAL mode, `.finagent/`) |
| Monitoring | Azure Application Insights (frontend + backend) | |

### Dependency Management

- **Authoritative dependency list:** `finagent/requirements-finagent.txt` — the complete set used by Docker and production
- **Summary file:** `pyproject.toml` — contains core dependencies only; not used for production installs
- **UV lock file:** `uv.lock` — local development lockfile

---

## System Layers

### Layer 1: Presentation (Frontend)

**Entry Point:** `Frontend/app/src/main.tsx` → `App.tsx`

The frontend is a single-page React application built with Vite. It uses a `HashRouter` for routing and `AuthContext` for state management.

**Marketing Pages:**
- **Landing** (`pages/LandingPage.tsx`): Product landing page
- **Features** (`pages/Features.tsx`): Feature showcase
- **Pricing** (`pages/Pricing.tsx`): Pricing tiers
- **Testimonials** (`pages/Testimonials.tsx`): User testimonials

**App Pages:**
- **Login** (`pages/Login.tsx`): Handles email login, signup, password reset, and Google OAuth (via Google Identity Services inline script)
- **Onboarding** (`pages/Onboarding.tsx`): Portfolio document upload and holding confirmation flow
- **Dashboard** (`pages/Dashboard.tsx`): Main workspace with portfolio overview, chat interface, charts, news feed, and watchlist

**Key architectural decisions:**
- No Redux or global state library — uses React Context for auth, component-local `useState`/`useRef` for everything else
- SSE (Server-Sent Events) for real-time agent progress with 25s proactive reconnect (accommodates AWS API Gateway's 30s timeout)
- Runtime backend URL resolution: checks `window.__BACKEND_URL`, then `__CONFIG__`, then `VITE_BACKEND_API_URL`, then falls back to Vite proxy
- All chart components wrap Chart.js with consistent theming via `ThemeProvider.ts`

### Layer 2: Application (Gateway + Agent Loop)

**Gateway:** `finagent/gateway/run.py` — the central HTTP server on port 8080.

The gateway:
1. Receives user requests (chat, research, portfolio, auth)
2. Manages authentication via JWT (local + Supabase)
3. Routes queries through `route_objective()` in `finagent/router/intent_router.py` (extracts entities, determines depth, detects follow-ups, classifies portfolio scope)
4. Launches research sessions via `run_research_session()` in a background task
5. Streams progress events to the frontend via `SessionBus` → SSE
6. Serves portfolio analytics and static HTML pages

**Key patterns:**
- `InMemSlidingWindowRateLimiter` for per-user rate limiting
- `SessionBus` (`events.py`) — in-process pub/sub event bus using `asyncio.Queue`
- Events persisted to JSONL files for replay on reconnect (max 5000 events)
- `ChatMemoryManager` for session-scoped chat history
- `route_objective()` handles entity extraction, follow-up detection, complexity classification, portfolio scope, and deep research eligibility

### Layer 3: Tooling & Data

**MCP Servers** (2 active standalone processes, consolidating what was previously 5+ servers):

| Port | Server | File | Consolidates |
|------|--------|------|--------------|
| 8003 | **Discovery** | `finagent/tools/mcp_servers/discovery_server.py` | NSE Market Data, Web & News Search, Document Pipeline (RAG) |
| 8005 | **Quant** | `finagent/tools/mcp_servers/quant_server.py` | Fundamentals (yfinance), Valuation Engine, Portfolio Risk Engine |

Legacy standalone server files exist in the same directory but are no longer deployed as separate processes:
`nse_server.py`, `research_server.py`, `fundamentals_server.py`, `docs_server.py`, `mcp_valuation.py`

**MCP Config** (`finagent/tools/mcp_config.py`): Wires discovery (8003) and quant (8005) with `streamable_http` transport. URLs configurable via `MCP_DISCOVERY_URL` and `MCP_QUANT_URL` env vars.

**Direct Data Tools** (in-process, no MCP):
- `finagent/tools/data/yahoo_finance.py` — yfinance quotes + fundamentals
- `finagent/tools/data/india.py` — NSE/Screener.in/Moneycontrol/SEBI fetchers
- `finagent/tools/data/sec_edgar.py` — SEC EDGAR company facts
- `finagent/tools/data/sec_filings.py` — SEC filing narratives
- `finagent/tools/data/wikipedia.py` — Wikipedia REST summary
- `finagent/tools/data/news_feed.py` — Google News RSS
- `finagent/tools/data/reddit.py` — Reddit search (WSB, IndianStreetBets, etc.)
- `finagent/tools/data/hackernews.py` — HN Algolia search
- `finagent/tools/data/stocktwits.py` — StockTwits sentiment
- `finagent/tools/data/forex.py` — USD/INR FX rates
- `finagent/tools/data/units.py` — Indian number formatting (crore/lakh)

**Web Tools:**
- `finagent/tools/web/scraper.py` — DuckDuckGo layered search + HTML page scraping
- `finagent/tools/web/crawl4ai_sites.py` — Crawl4AI full-page extraction (Chromium-based)
- `finagent/tools/web/searxng_client.py` — SearXNG meta-search engine
- `finagent/tools/web/http_fetcher.py` — Shared async httpx client
- `finagent/tools/web/table_parser.py` — HTML table extraction

**Browser Tools (Archived):**
- `finagent/tools/browser/deep_crawler.py` — Playwright deep domain crawler (ARCHIVED — NOT ACTIVE; references removed `playwright_backend.py`)

**Valuation Engine** (`finagent/tools/valuation_engine.py`):
- All financial math is deterministic — the LLM *never* does calculations
- Computations: DCF, PE valuation, Graham number, EV/EBITDA, Dividend Discount Model, WACC, CAGR, Piotroski F-Score, Altman Z-Score, DuPont analysis
- Returns structured Pydantic models with intermediate inputs shown

**Social Tools:**
- `finagent/tools/social/viral_verifier.py` — Pump-and-dump signal detection

**ProspektLab Tools:**
- `finagent/tools/prospektlab/enricher.py` — Entity enrichment
- `finagent/tools/prospektlab/entity_fetcher.py` — Entity data fetching
- `finagent/tools/prospektlab/event_monitor.py` — Event monitoring
- `finagent/tools/prospektlab/exporter.py` — Data export
- `finagent/tools/prospektlab/navigator.py` — Data navigation

### Layer 4: Storage

| Store | Location | Content |
|-------|----------|---------|
| Memory SQLite | `.finagent/memory.sqlite3` | Financial facts, session summaries, per-user durable knowledge |
| Chat Memory | `.finagent/chat_memory.db` | Per-session chat history |
| Playbooks SQLite | `.finagent/playbooks.sqlite3` | Reusable research playbooks |
| Research State | `.finagent/research_state.sqlite3` | Research checkpoints and state |
| Position Mirror | `.finagent/memory.sqlite3` | User portfolio holdings (per-tenant) |
| Memos | `.finagent/memos/` | Generated research memos (markdown) |
| Sessions | `.finagent/sessions/` | Event JSONL + session metadata |
| Cache | `.finagent/cache/` | Per-session query cache |
| Users | `.finagent/users/` | User-specific data |
| Supabase | Cloud PostgreSQL | User auth, profiles, global state |

### `.finagent/` Runtime Directory Structure

```
.finagent/                          # Created automatically at first run
├── memory.sqlite3                  # Financial facts + portfolio mirror (WAL mode)
├── memory.sqlite3-shm              # WAL shared memory
├── memory.sqlite3-wal              # WAL journal
├── chat_memory.db                  # Per-session chat history
├── playbooks.sqlite3               # Reusable research playbooks
├── research_state.sqlite3          # Research checkpoints
├── state.sqlite3                   # Session state store
├── state.sqlite3-shm/wal           # WAL files
├── robots_cache.db                 # robots.txt cache for web scrapers
├── global_sqlite_test.db           # Test database
├── crawl4ai_test.db                # Crawl4AI test database
├── .crawl4ai/                      # Crawl4AI browser profiles
├── cache/                          # Per-session query cache
├── data/                           # Downloaded reference data cache
├── ingestion_state/                # Portfolio ingestion work-in-progress
├── isin_master.json                # Cached ISIN lookup data
├── magic_pdf_models/               # MinerU PDF model weights
├── memos/                          # Generated research memos (markdown)
├── portfolio_mirror_cache/         # Cached portfolio snapshots
├── sessions/                       # Session event JSONL + metadata
└── users/                          # User-specific data
```

---

## Request Flow

### Standard Research Session — End-to-End Flow

```
User submits query (e.g., "Analyze Reliance Industries")
  │
  ▼
[Frontend: Dashboard.tsx]
  │  POST /chat/research  (or /research/start)
  ▼
[Gateway: run.py]
  │  1. Validate JWT auth
  │  2. Rate limit check
  │  3. route_objective(query) in intent_router.py
  │     → Detects follow-up via chat history
  │     → Extracts ticker/entities via entity_resolver.py
  │     → Classifies complexity (simple/moderate/complex)
  │     → Checks portfolio scope
  │     → Checks deep research eligibility via policies.should_enable_deep_research()
  │  4. Create session record, set "running"
  │  5. Spawn background task: run_research_session()
  │  6. Return session_id to frontend
  ▼
[Core Agent Loop: run_agent.py → run_research_session()]
  │
  │  PHASE 1: IDENTIFY
  │  ┌──────────────────────────────────────────────┐
  │  │ • Resolve entities (geo/entity_resolver.py)   │
  │  │   → Canonical ticker, exchange suffix (.NS)   │
  │  │   → Geography detection (IN/US)               │
  │  │   → Preferred data source domains             │
  │  │ • Load memory facts (recall past analysis)     │
  │  │ • Retrieve playbooks (reusable research plans) │
  │  │ • Build ResearchPlan                           │
  │  └──────────────────────────────────────────────┘
  │
  │  PHASE 2: ENRICHMENT (parallel, asyncio.gather)
  │  ┌──────────────────────────────────────────────┐
  │  │ • Yahoo Finance quote + fundamentals          │
  │  │ • Wikipedia company summary                   │
  │  │ • India company snapshot (NSE/Screener.in)    │
  │  │ • USD/INR forex rate                          │
  │  │ • News headlines (Google News RSS)            │
  │  │ • Reddit search (WSB / IndianStreetBets)      │
  │  │ • Hacker News mentions                        │
  │  │ • StockTwits sentiment                        │
  │  │ • SEC EDGAR (US companies)                   │
  │  │ • SEBI filings (Indian companies)             │
  │  │ • Shareholding pattern                        │
  │  │ → All run concurrently                       │
  │  └──────────────────────────────────────────────┘
  │
  │  PHASE 3: BREADTH SURVEY
  │  ┌──────────────────────────────────────────────┐
  │  │ • Localize search queries (IN/US specific)    │
  │  │ • 4 search angles:                            │
  │  │   1. Business overview + fundamentals         │
  │  │   2. Growth catalysts + future outlook        │
  │  │   3. Risk factors + red flags                 │
  │  │   4. Competitive landscape + industry         │
  │  │ • Each angle: DuckDuckGo search → scrape top 6 │
  │  │ • Preferred domain filter (source_policy.py)  │
  │  │ • Result deduplication + relevance scoring    │
  │  │ → Scored, deduped document corpus            │
  │  └──────────────────────────────────────────────┘
  │
  │  PHASE 4: DEEP DIVE (iterative, up to 4 rounds)
  │  ┌──────────────────────────────────────────────┐
  │  │ • Identify knowledge gaps from breadth data   │
  │  │ • Generate targeted follow-up queries         │
  │  │ • Search + scrape → answer gap questions      │
  │  │ • Each round: check if enough coverage        │
  │  │ • Stop early if all gaps filled or max rounds │
  │  └──────────────────────────────────────────────┘
  │
  │  PHASE 5: ANALYSIS
  │  ┌──────────────────────────────────────────────┐
  │  │ • Multi-agent orchestration (10 specialists)   │
  │  │ • Cross-source conflict detection             │
  │  │ • Research quality scoring (0-100)            │
  │  │ • Claim accuracy validation                   │
  │  │ • Blind spot detection                        │
  │  │ • Pump & dump signal detection               │
  │  └──────────────────────────────────────────────┘
  │
  │  PHASE 6: SYNTHESIS
  │  ┌──────────────────────────────────────────────┐
  │  │ • Build EnrichmentBundle from all data        │
  │  │ • Call synthesize_memo() (OpenAI GPT-4o)     │
  │  │ • 8-section structured memo                   │
  │  │ • Cross-source conflict report                │
  │  │ • Confidence score with rationale             │
  │  │ • Citation log (all sources linked)           │
  │  │ • INR-first formatting (crore/lakh)           │
  │  └──────────────────────────────────────────────┘
  │
  │  Persists: memos, memory facts, session events, playbooks
  │
  ▼
[Frontend receives final "done" event via SSE]
  → Transitions from AgentThinking to final MessageBubble
  → Renders RichResponse with memo, charts, metrics
```

### SSE Event Streaming Architecture

```
┌──────────┐     SessionBus (events.py)     ┌──────────────┐
│  Agent   │ ───►  asyncio.Queue ─────────►  │  Gateway     │
│  Loop    │     │  • emit(event)           │  SSE endpoint │
│          │     │  • persist to JSONL      │  /stream      │
└──────────┘     │  • replay on request     └──────────────┘
                 └─────────────────────────────────────────┘
                                       │
                                       │ text/event-stream
                                       ▼
                              ┌──────────────────┐
                              │  Frontend        │
                              │  streamSession() │
                              │  • EventSource   │
                              │  • Reconnect @25s│
                              │  • JSON parse    │
                              └──────────────────┘
```

Event types emitted:
- `phase_change` / `phase` — Current pipeline phase (enriching, searching, analyzing, synthesizing)
- `step_start` / `step_end` — Individual tool call with label + metadata
- `agent_start` / `agent_end` — Sub-agent execution with name + progress
- `source` — Source domain discovered
- `status` — Session status updates
- `done` — Final result with memo URL
- `error` — Error events with message

---

## Core Agent Loop

**File:** `finagent/run_agent.py`

The core loop is the heart of the system. It follows a 6-phase pipeline:

1. **Identify** — Resolve target to ticker, determine geography, load memory & playbooks
2. **Enrichment** — Pull authoritative JSON APIs in parallel (SEC EDGAR, Yahoo Finance, Wikipedia)
3. **Breadth Survey** — Layered DuckDuckGo search across 4 angles
4. **Deep Dive** — Iterative targeted second-pass queries to fill gaps
5. **Analysis** — Cross-source conflict detection, multi-agent findings, viral scoring
6. **Synthesis** — OpenAI / template memo using facts, not just excerpts

Configuration is driven by `AgentLoopConfig`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_steps` | 8-18 (standard) | Max enrichment + search steps |
| `enable_scraping` | True | Full page scraping via Crawl4AI |
| `enable_enrichment` | True | Yahoo, Wikipedia, news, etc. |
| `enable_deep_dive` | True | Iterative deep dive phase |
| `enable_memory` | True | Recall past facts |
| `enable_reflection` | True | Self-improvement loop |
| `reflection_max_rounds` | 5 | Max reflection iterations |
| `quality_threshold` | 75.0 | Min quality score before triggering reflection |
| `auto_depth` | True | Auto-adjust steps by query complexity |

**Deep research variant:** When triggered, `max_steps` boosts to 80, reflection rounds cap at 2, and per-query timeout tightens to 18s.

**Key design principle:** The LLM only does reasoning and synthesis. All data fetching, computation, and formatting happen in deterministic Python code.

---

## Multi-Agent Orchestration

**Directory:** `finagent/agents/`

### Design Pattern: Hermes Wave-Based Parallel Orchestration

The `Orchestrator` (`agents/orchestrator.py`) manages 10 specialist sub-agents, each implemented as an async function returning structured `Finding` objects. Agents are organized into **dependency waves** — agents in the same wave can run in parallel, but later waves may depend on earlier waves' output. Each agent has its own timeout via `SubAgentContext.deadline_ms`.

### Agent Roster (`agents/specialists/default_roster()`)

| Wave | Agent | File | Priority | Description |
|------|-------|------|----------|-------------|
| 0 | **Financials** | `specialists/financials.py` | p10 | Income statement, balance sheet, cash flow analysis. Computes YoY/QQ growth, margin trends, ratio analysis. |
| 0 | **Risk** | `specialists/risk.py` | p20 | Operational, financial, regulatory, and market risk factors. Debt levels, liquidity, concentration risk. |
| 0 | **News** | `specialists/news.py` | p20 | Recent news sentiment analysis. Identifies material events, management changes, regulatory actions. |
| 1 | **Technical** | `specialists/technical.py` | p30 | Price action, volume, moving averages, RSI, MACD, support/resistance levels. |
| 1 | **Community** | `specialists/community.py` | p30 | Reddit (WSB, IndianStreetBets), StockTwits, Hacker News sentiment. Viral/pump-and-dump detection. |
| 2 | **Competitor** | `specialists/competitor.py` | p40 | Peer comparison on key metrics. Market share analysis, competitive moat assessment. |
| 2 | **Valuation** | `specialists/valuation.py` | p40 | DCF, PE multiple, Graham number, EV/EBITDA. Fair value estimation with bullish/bearish/best-estimate scenarios. |
| 3 | **Accounting** | `specialists/accounting.py` | p45 | Forensic accounting anomaly detection. Accrual ratios, Beneish M-Score, revenue recognition red flags. |
| 4 | **Macro** | `specialists/macro.py` | p50 | Interest rates, inflation, GDP, forex, industry cycle positioning. Regulatory/tax regime impact. |
| 5 | **Governance** | `specialists/governance.py` | p60 | Board composition, management quality, related-party transactions, shareholder rights. |

### Context (`agents/base.py`)

Each sub-agent receives a `SubAgentContext` containing:
- The enrichment bundle (quotes, financials, news, social data)
- The search corpus (deduped, scored web documents)
- Prior wave findings (for dependency-aware analysis)
- Entity metadata (ticker, geography, sector)

### Verification (`agents/verifier.py`)

After all agents complete, the `Verifier`:
- Cross-checks claims across different agents/sources
- Flags inconsistencies (e.g., valuation agent says "undervalued" but financials agent warns of declining revenues)
- Returns confidence-adjusted claim list

### Blind Spot Detection (`agents/blindspot.py`)

Auto-generates follow-up questions for:
- Areas with no agent coverage
- Contradictory findings
- Low-confidence claims
- Missing data points (e.g., no forward guidance found)

---

## Deep Research (Multi-Pass)

**Endpoint:** `POST /research/deep`

Deep research runs multiple parallel research passes, each a complete research session with boosted step budgets (max_steps=80). It is triggered when the query matches keyword patterns in `should_enable_deep_research()` (e.g., "deep", "comprehensive", "forensic", "due diligence", "portfolio risk", "risk audit").

**How it works:**
1. Pass 0 runs first (context-building pass: financials foundation)
2. Passes 1 through N-1 execute in parallel via `asyncio.gather()`
3. A final synthesis pass runs serially after all others complete

The number of passes is dynamic — driven by the breadth queries generated during earlier passes, not hardcoded. Each non-final pass skips memo generation; only the synthesis pass emits the final "done" event.

Each pass has its own:
- `max_steps` boosted to 80
- Reflection rounds capped at 2
- Per-query timeout tightened to 18s
- Blindspot max queries set to 10

The final synthesis pass integrates all intermediate findings into a single comprehensive report.

---

## MCP Server Layer

### Active Configuration

Only **2 MCP servers** are actively configured and deployed:

| Port | Server | Source File | Scope |
|------|--------|-------------|-------|
| 8003 | **Discovery** | `tools/mcp_servers/discovery_server.py` | Consolidated: NSE Market Data, Web & News Search, Document Pipeline (RAG/Qdrant) |
| 8005 | **Quant** | `tools/mcp_servers/quant_server.py` | Consolidated: Fundamentals (yfinance), Valuation Engine, Portfolio Risk Engine |

Both use `streamable_http` transport via FastMCP (>=2.0.0).

### MCP Configuration

**File:** `tools/mcp_config.py`

```python
MCP_SERVERS = {
    "discovery": {"url": mcp_discovery_url, "transport": "streamable_http"},   # default :8003
    "quant":     {"url": mcp_quant_url, "transport": "streamable_http"},       # default :8005
}
```

Environment variables: `MCP_DISCOVERY_URL`, `MCP_QUANT_URL`.

### Dynamic Loading (`tools/mcp/dynamic_loader.py`)

Loads MCP tools at runtime, supporting hot-reload and graceful fallback when servers are unavailable.

### Legacy Standalone Servers

The following server files exist in `tools/mcp_servers/` but are no longer deployed as standalone processes (their capability was consolidated into discovery and quant):
- `nse_server.py` — NSE Market Data
- `research_server.py` — Web & News Search
- `fundamentals_server.py` — Fundamentals
- `docs_server.py` — Documents
- `mcp_valuation.py` — Valuation

---

## Portfolio System

### Architecture

```
                    POST /api/portfolio/upload-cas
                    POST /api/portfolio/upload-document
                    POST /api/portfolio/upload-screenshot
                    POST /portfolio/mirror  (manual entry)
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 PORTFOLIO INGESTION                         │
│  ┌────────────┐  ┌────────────┐  ┌─────────────────────┐   │
│  │ eCAS Parser│  │ PDF Parser │  │ Screenshot OCR      │   │
│  │ cas_adapter│  │ pdf_trans- │  │ image_ingestion     │   │
│  │ .py        │  │ former.py  │  │ .py                 │   │
│  │            │  │ mineru_    │  │                     │   │
│  │ CAMS/KFin  │  │ trans.py   │  │                     │   │
│  └────────────┘  └────────────┘  └─────────────────────┘   │
│                              │                              │
│              Extraction Schema (portfolio_schema.py)        │
│              → List of Position objects                     │
│                              │                              │
│                   User Review / Confirmation                │
│                              │                              │
│                              ▼                              │
│              Position Mirror DB (portfolio_mirrors.py)      │
│              → SQLite, per-tenant, active flag              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 PORTFOLIO ANALYTICS                         │
│  ┌───────────┐ ┌──────────┐ ┌─────────┐ ┌──────────────┐ │
│  │ Analytics │ │ Sectors  │ │Alerts   │ │Stress Test   │ │
│  │ P&L,      │ │ Sector   │ │Price    │ │Scenario      │ │
│  │ XIRR,     │ │ breakup, │ │alerts,  │ │analysis,     │ │
│  │ allocation│ │concentra-│ │MA alerts│ │monte carlo   │ │
│  │           │ │tion risk │ │52w high │ │              │ │
│  └───────────┘ └──────────┘ └─────────┘ └──────────────┘ │
│  ┌───────────┐ ┌──────────┐ ┌─────────┐ ┌──────────────┐ │
│  │ Dividends │ │ Tax      │ │ Corp    │ │ MF Analytics │ │
│  │ History + │ │ STCG/LTCG│ │Actions  │ │ Scheme       │ │
│  │ Upcoming  │ │ Summary  │ │ Split,  │ │ performance  │ │
│  │           │ │          │ │ Bonus   │ │ NAV tracking │ │
│  └───────────┘ └──────────┘ └─────────┘ └──────────────┘ │
│  ┌───────────┐ ┌──────────┐ ┌────────────────────────────┐ │
│  │Action     │ │Holding   │ │ Portfolio News              │ │
│  │Queue      │ │Detail    │ │ News relevant to holdings   │ │
│  │Daily      │ │Deep dive │ │                             │ │
│  └───────────┘ └──────────┘ └────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Portfolio Endpoints

All portfolio endpoints live in `finagent/gateway/run.py`:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/portfolio/mirror` | Get current holdings |
| POST | `/portfolio/mirror` | Replace holdings manually |
| DELETE | `/portfolio/mirror` | Clear all holdings |
| POST | `/portfolio/mirror/ecas` | Replace holdings from eCAS |
| POST | `/api/portfolio/upload-cas` | Upload eCAS/PDF/CSV/XLSX |
| POST | `/api/portfolio/upload-document` | Upload document |
| POST | `/api/portfolio/upload-screenshot` | Upload screenshot (OCR) |
| POST | `/api/portfolio/confirm-extraction` | Confirm extracted holdings |
| POST | `/api/portfolio/cancel-extraction` | Cancel extraction |
| GET | `/portfolio/analytics` | Full portfolio analytics |
| GET | `/portfolio/sectors` | Sector breakdown |
| GET | `/portfolio/holding/{symbol}` | Single holding detail |
| GET | `/portfolio/alerts` | Price/Moving Average alerts |
| GET | `/portfolio/news` | Portfolio-relevant news |
| GET | `/portfolio/corporate-actions` | Bonuses, splits, dividends |
| GET | `/portfolio/tax-summary` | STCG/LTCG summary |
| GET | `/portfolio/dividends` | Dividend history + upcoming |
| POST | `/portfolio/stress-test` | Run stress test scenario |
| GET | `/portfolio/mf-analytics` | Mutual fund analytics |
| GET | `/portfolio/today` | Today's action queue |
| GET | `/portfolio/brief` | Text summary for chat context |

### Portfolio-Scoped Research

When a user has holdings and asks a general question like "should I rebalance?", `is_portfolio_scope_query()` in `intent_router.py` detects portfolio scope and feeds holdings data into the agent loop's context, enabling:
- "What's my worst performing stock?" → queries portfolio + analyzes
- "Am I overexposed to IT?" → computes sector allocation + research
- "Show me news affecting my holdings" → portfolio news endpoint

The `query_guards.py` module prevents false classification: when a portfolio query contains comparison words like "vs" or "compared to", it is treated as a portfolio query, not a company-vs-company comparison.

---

## Memory System

**Directory:** `finagent/memory/`

### Architecture

```
┌────────────────────────────────────────────────────┐
│                  MEMORY SYSTEM                      │
│                                                     │
│  ┌──────────────────┐    ┌────────────────────┐    │
│  │  Memory Store     │    │  Chat Memory       │    │
│  │  store.py         │    │  chat_memory.py    │    │
│  │  SQLite           │    │  SQLite            │    │
│  │  memory.sqlite3   │    │  chat_memory.db    │    │
│  └──────────────────┘    └────────────────────┘    │
│                                                     │
│  Fact Types:                 Chat:                  │
│  • identity                  • Per-session          │
│  • financial                 • User messages        │
│  • risk                      • Assistant responses  │
│  • market_data               • For follow-up        │
│  • news_event                  detection            │
│  • conflict                                          │
│  • sentiment                                         │
│  • valuation                                         │
└────────────────────────────────────────────────────┘
```

### Memory Store (`memory/store.py`)

- Per-user isolation (scoped by tenant)
- Facts normalized by target (`normalize_target()`)
- Fact categories: identity, financial, risk, market_data, news_event, conflict, sentiment, valuation
- Recalled on subsequent sessions via `recall_facts(target, limit=n)`
- Stale fact pruning and deduplication

### Chat Memory (`memory/chat_memory.py`)

- Per-session chat history persistence
- `ChatMemoryManager` class:
  - `save_message(session_id, role, content)`
  - `get_history(session_id, limit=n)` → returns recent messages
  - `clear_history(session_id)`
- Used by intent router for follow-up detection
- Used to build conversation context for the LLM

### Memory Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/memory/stats` | Memory statistics |
| GET | `/memory/facts` | Browse stored facts |
| GET | `/memory/sessions` | Session summaries |
| DELETE | `/memory/clear/{target}` | Clear target facts |

---

## Entity Resolution & Geography

**Directory:** `finagent/geo/`

### Resolution Pipeline

```
User query: "Analyze TCS"
           │
           ▼
  resolve_entity(query, geography_hint=None)
  finagent/geo/entity_resolver.py
           │
           ├──► Extract potential ticker ("TCS")
           ├──► Check mapping table (ticker_mapper.py)
           │    → "TCS" → "TCS.NS" (NSE), market cap, sector
           ├──► Determine geography (jurisdiction_profiles.py)
           │    → India (IN) profile
           ├──► Apply exchange suffix policy
           │    → .NS for NSE, .BO for BSE
           ├──► Load preferred data domains (source_policy.py)
           │    → screener.in, moneycontrol.com, nseindia.com
           └──► Return ResolvedEntity:
                 • ticker: "TCS.NS"
                 • name: "Tata Consultancy Services"
                 • geography: "IN"
                 • exchange: "NSE"
                 • preferred_domains: ["screener.in", ...]
```

### Components

| File | Purpose |
|------|---------|
| `entity_resolver.py` | Main entity resolution: ticker extraction, suffix application, mapping table lookup |
| `ticker_mapper.py` | Symbol-to-ticker mapping database (e.g., "TCS" → "TCS.NS") |
| `jurisdiction_profiles.py` | Country-specific config: data sources, currency, exchange conventions |
| `source_policy.py` | Preferred domain URLs per country/sector for web search |
| `query_localizer.py` | Adapts search queries for local context (IN vs US) |
| `currency_policy.py` | Currency formatting: INR defaults to crore/lakh, US to millions/billions |

### Geography Profiles

**India (IN):**
- Exchange suffixes: .NS (NSE), .BO (BSE)
- Data sources: yfinance, Screener.in, Moneycontrol, NSE, BSE
- Preferred domains: screener.in, moneycontrol.com, nseindia.com, bseindia.com
- Currency: INR (crore/lakh formatting)
- News: SEBI filings, BSE/NSE announcements, AMFI
- Social: IndianStreetBets, ValuePickr

**United States (US):**
- Exchange suffixes: none (direct symbol)
- Data sources: yfinance, SEC EDGAR
- Preferred domains: sec.gov, seekingalpha.com, gurufocus.com
- Currency: USD (millions/billions)
- News: SEC filings, Bloomberg, Reuters
- Social: WallStreetBets, StockTwits

---

## Synthesis & Output

**Directory:** `finagent/synthesis.py`, `finagent/output/`

### Synthesis Pipeline

```
All research data
  │
  ▼
EnrichmentBundle (dataclass)
  • india_snap: IndiaCompanySnapshot
  • sebi_filing: SEBIFiling
  • shareholding: dict
  • yahoo: YahooQuote
  • wikipedia: WikipediaSummary
  • fx: FxRate
  • news: list[NewsItem]
  • And more populated at runtime by run_agent.py
  │
  ▼
synthesize_memo(bundle, config) → SynthesisResult
  │
  ├──► Build system prompt (prompt_builder.py)
  │    → INR-first formatting instructions
  │    → Confidentiality and disclaimer
  │
  ├──► Format enrichment data as structured context
  │    → Numbers formatted in INR (crore/lakh) for IN companies
  │    → All citations tracked
  │
  ├──► Call OpenAI GPT-4o (with token streaming)
  │    → Falls back to template-based synthesis when no API key
  │    → 8-section memo template
  │    → Include conflict warnings
  │    → Include confidence score with rationale
  │    → Include data freshness timestamps
  │
  └──► Return formatted markdown memo
  │
  ▼
build_answer_artifact() → structured AnswerArtifact for frontend
```

### 8-Section Memo Template

1. **Executive Summary** — 2-3 paragraph TL;DR with key metrics and verdict
2. **Business Overview** — What the company does, segments, market position
3. **Financial Analysis** — Revenue/PAT trends, margins, ratios, cash flow quality
4. **Valuation** — Fair value estimate with bullish/bearish/best-estimate, peer comparison
5. **Risks & Red Flags** — Key risk factors, accounting red flags, regulatory concerns
6. **Market Sentiment** — News sentiment, social media buzz, analyst consensus
7. **Competitive Landscape** — Peer comparison table, market share, moat analysis
8. **Verdict / Investment Thesis** — Bull/bear/base scenarios, conviction level, catalysts

### Output Components (`output/`)

| File | Purpose |
|------|---------|
| `contracts.py` | `OutputMode` enum (quick/moderate/deep), `ResponseDepth` enum, `AnswerArtifact` model |
| `intent_classifier.py` | Classifies query complexity → `ResponseDepth`, extracts finance entities |
| `memo_formatter.py` | Converts raw memo sections to display-ready format |
| `renderer.py` | Markdown-to-JSON rendering engine |
| `artifact_builder.py` | Builds structured answer artifacts for the frontend |
| `chart_generator.py` | Matplotlib chart image generation |
| `confidence_scorer.py` | 0-100 confidence with source weighting |
| `conflict_reporter.py` | Cross-source conflict detection and reporting |
| `report_exporter.py` | Export to PDF/HTML |
| `templates.py` | Output templates for different response modes |
| `query_guards.py` | Guards against misclassifying portfolio comparison queries as company comparisons |

### Intent Classification (`intent.py`, `output/intent_classifier.py`)

Two-layer intent system:
1. `intent.py` — Keyword-based intent detection and rich mode classification (chart, news, valuation, comparison, filing, snapshot)
2. `output/intent_classifier.py` — Complexity classification (simple/moderate/complex) and `ResponseDepth` assignment

### Rich Response Builder (`rich_builder.py`)

Assembles typed `RichResponse` objects that the React frontend renders as metric cards, charts, comparison tables, strengths/risks panels, and other structured visuals. Falls back to plain markdown when tool outputs are insufficient.

### Valuation Engine (`tools/valuation_engine.py`)

All calculations are deterministic:

- **DCF** — Free cash flow projection, terminal value (perpetuity growth / exit multiple), WACC discounting
- **PE Valuation** — Trailing and forward PE, industry-adjusted
- **Graham Number** — Benjamin Graham intrinsic value formula
- **EV/EBITDA** — Enterprise value to EBITDA multiple comparison
- **DDM** — Dividend discount model with growth assumptions
- **WACC** — Cost of equity (CAPM) + cost of debt, country risk premium
- **CAGR** — Compounded annual growth rate over configurable periods
- **Piotroski F-Score** — 9-point accounting quality score
- **Altman Z-Score** — Bankruptcy prediction model
- **DuPont Analysis** — ROE decomposition (profit margin × asset turnover × equity multiplier)

Each function returns a Pydantic model with:
- The computed value
- Input assumptions (transparent)
- Intermediate calculations (auditable)
- Confidence level

---

## Data Layer & External Providers

### Provider Map

```
                    ┌─────────────────┐
                    │   finagent      │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│  yfinance      │   │  SEC EDGAR    │   │  NSE / BSE    │
│  • Quotes      │   │  • Company    │   │  • Screener.in│
│  • Financials  │   │    Facts      │   │  • Moneycontrol│
│  • History     │   │  • Filings    │   │  • Shareholding│
│  • Dividends   │   │  • XBRL Data  │   │  • Corp Actions│
└───────────────┘   └───────────────┘   └───────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│  News & Social │   │  Web Search   │   │  Reference    │
│  • Google News │   │  • DuckDuckGo │   │  • Wikipedia  │
│  • Reddit      │   │  • Crawl4AI   │   │  • Forex API  │
│  • HackerNews  │   │  • SearXNG    │   │               │
│  • StockTwits  │   │               │   │               │
└───────────────┘   └───────────────┘   └───────────────┘
```

### Data Fetch Pattern

All data fetchers follow a consistent pattern:

```python
# finagent/tools/data/ — re-exports
# finagent/tools/data/yahoo_finance.py
async def fetch_yahoo_quote(symbol: str) -> YahooQuote:
    """Fetch via yfinance, return structured Pydantic model."""

# Usage in run_agent.py (parallel):
results = await asyncio.gather(
    fetch_yahoo_quote(ticker),
    fetch_wikipedia_summary(ticker),
    fetch_india_snapshot(ticker),
    fetch_news(ticker),
    search_reddit(ticker),
    # ... etc
)
```

### Caching

- **Per-session query cache** (`tools/data/cache.py`): In-memory cache for the duration of a research session
- **News cache** (`news/cache.py`): SQLite-backed cache with configurable TTL
- **News deduplication** (`news/dedupe.py`): Cosine similarity + title matching

---

## Frontend Architecture

### Directory Structure

```
Frontend/app/src/
├── main.tsx                    # React entry, AuthProvider wrapper
├── App.tsx                     # Route definitions, auth guards
├── index.css                   # Global styles (dark theme design system)
├── api/
│   └── client.ts               # Full API client (all endpoints, SSE streaming)
├── context/
│   └── AuthContext.tsx          # Auth state, Google OAuth, onboarding
├── data/
│   └── indianStocks.ts         # Indian stock reference data for search
├── pages/
│   ├── Dashboard.tsx           # Main workspace
│   ├── Login.tsx               # Auth pages (login + signup + password reset)
│   ├── Onboarding.tsx          # Portfolio onboarding
│   ├── LandingPage.tsx         # Product landing page
│   ├── Features.tsx            # Feature showcase
│   ├── Pricing.tsx             # Pricing tiers
│   └── Testimonials.tsx        # User testimonials
└── components/
    ├── layout/
    │   ├── AppShell.tsx        # Main layout wrapper
    │   ├── Logo.tsx            # Logo component
    │   └── Sidebar.tsx         # Navigation sidebar
    ├── chat/
    │   ├── AgentThinking.tsx   # Agent progress visualization
    │   ├── ChatInput.tsx       # Chat input + depth selector
    │   ├── MessageBubble.tsx   # Chat message rendering
    │   ├── RichResponse.tsx    # Rich data visualization
    │   ├── SuggestedPrompts.tsx # Prompt suggestions
    │   ├── CalloutBlock.tsx    # Callout/highlight block
    │   ├── HtmlArtifact.tsx    # HTML artifact renderer
    │   └── SectionBlock.tsx    # Section block wrapper
    ├── charts/
    │   ├── AreaChart.tsx       # Chart.js area chart
    │   ├── BarChart.tsx        # Chart.js bar chart
    │   ├── DonutChart.tsx      # Chart.js donut chart
    │   ├── InteractiveChart.tsx # Interactive time-series
    │   ├── MetricCard.tsx      # Single metric display
    │   ├── ThemeProvider.ts    # Chart.js theming
    │   ├── RadarChart.tsx      # Radar/spider chart
    │   ├── TreemapChart.tsx    # Treemap visualization
    │   └── TableBlock.tsx      # Table rendering block
    └── dashboard/
        ├── IndexTickerCard.tsx  # Nifty/Sensex ticker
        ├── PortfolioTable.tsx   # Holdings table
        ├── QuickActions.tsx     # Quick action buttons
        ├── QuickPulse.tsx       # Market pulse overview
        ├── RecentInsights.tsx   # Recent research list
        ├── Sparkline.tsx        # Mini chart
        ├── WatchlistCard.tsx    # User watchlist
        └── AssetHistoryModal.tsx # Asset history modal
```

### Route Configuration (`App.tsx`)

```
HashRouter:
  /                  → LandingPage (marketing)
  /pricing           → Pricing page
  /testimonials      → Testimonials page
  /features          → Features page
  /login             → Login page (PublicRoute guard)
  /signup            → Login page — signup tab (PublicRoute guard)
  /onboarding        → Portfolio onboarding (ProtectedRoute, requireOnboarded=false)
  /dashboard         → Main workspace (ProtectedRoute, requireOnboarded=true)
  *                  → Redirect to /
```

`ProtectedRoute` checks authentication and optionally verifies onboarding status. `PublicRoute` redirects authenticated users away from auth pages.

### Auth State (`context/AuthContext.tsx`)

```typescript
interface AuthContextType {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  onboarded: boolean;
  login: (email, password, remember?) => Promise<void>;
  signup: (name, email, password, mobile, code) => Promise<void>;
  googleLogin: (credential) => Promise<void>;
  logout: () => Promise<void>;
  showToast: (message, type?) => void;
  updateUserMobile: (mobile) => void;
  setOnboarded: (next) => void;
  refreshOnboardingStatus: () => Promise<boolean>;
}
```

- Token stored in localStorage
- Google OAuth via Google Identity Services (GIS) — inline script injection, not a npm package
- Automatically validates token on app load
- No UI framework dependency (no Tailwind, MUI, Ant Design) — pure CSS design system

### API Client (`api/client.ts`)

Key features:
- Dynamic backend URL resolution (runtime config `__BACKEND_URL`, `__CONFIG__`, env var `VITE_BACKEND_API_URL`, or Vite proxy)
- Bearer token injection on every authenticated request
- Configurable timeouts: auth 15s, mirror status 8s, chat start 20s
- Full coverage: auth, portfolio, research, memory, chat, market data endpoints
- SSE streaming with `streamSession(sessionId)`:
  - Uses `EventSource` API
  - 25-second proactive reconnect (works with AWS API Gateway 30s limit)
  - Parses JSON event data, calls `onEvent` callback per event type

### Dashboard (`pages/Dashboard.tsx`)

The dashboard is organized into sections:
1. **Portfolio Overview** — Holdings table, allocation donut, top movers, alerts
2. **Market Pulse** — Ticker cards, watchlist with sparklines, sector heatmap
3. **Research Chat** — Chat input, message history, agent thinking panel, rich responses (memos, charts, callouts, sections, HTML artifacts)
4. **Recent Insights** — Saved memos and research sessions
5. **Quick Actions** — Pre-built research prompts

State management is entirely React `useState`/`useRef` with no external library.

---

## Gateway & API Endpoints

**File:** `finagent/gateway/run.py`

### Complete Endpoint Reference

#### Auth

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/google` | No | Google OAuth login/signup |
| POST | `/auth/google/update-mobile` | Yes | Update mobile number |
| POST | `/auth/signup` | No | Email + password signup |
| POST | `/auth/login` | No | Email + password login |
| POST | `/auth/logout` | Yes | Invalidate session |
| POST | `/auth/send-verification` | No | Send email verification code |
| POST | `/auth/forgot-password` | No | Send password reset code |
| POST | `/auth/reset-password` | No | Reset password with code |

#### Research & Sessions

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/research/start` | Yes | Standard research (auto-depth) |
| POST | `/research/deep` | Yes | Multi-pass deep research |
| POST | `/chat/research` | Yes | Chat-friendly research entry |
| POST | `/sessions/{id}/stop` | Yes | Cancel running session |
| DELETE | `/sessions/{id}` | Yes | Delete session artifacts |
| GET | `/sessions/{id}/status` | Yes | Session status |
| GET | `/sessions/{id}/events` | Yes | Poll events (JSON array) |
| GET | `/sessions/{id}/stream` | Yes | SSE event stream |
| GET | `/sessions/{id}/result` | Yes | Final result + memo |
| GET | `/sessions/{id}/memo` | Yes | Memo markdown |
| GET | `/memos` | Yes | List saved memos |
| GET | `/chat/history` | Yes | Chat history |

#### Portfolio

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/portfolio/mirror` | Yes | Get holdings |
| POST | `/portfolio/mirror` | Yes | Replace holdings |
| DELETE | `/portfolio/mirror` | Yes | Clear holdings |
| POST | `/portfolio/mirror/ecas` | Yes | Replace from eCAS data |
| POST | `/api/portfolio/upload-cas` | Yes | Upload eCAS/PDF/CSV/XLSX |
| POST | `/api/portfolio/upload-document` | Yes | Upload document |
| POST | `/api/portfolio/upload-screenshot` | Yes | Upload screenshot |
| POST | `/api/portfolio/confirm-extraction` | Yes | Confirm extraction |
| POST | `/api/portfolio/cancel-extraction` | Yes | Cancel extraction |
| GET | `/portfolio/analytics` | Yes | Portfolio analytics |
| GET | `/portfolio/news` | Yes | Portfolio news |
| GET | `/portfolio/sectors` | Yes | Sector breakdown |
| GET | `/portfolio/holding/{symbol}` | Yes | Holding detail |
| GET | `/portfolio/corporate-actions` | Yes | Corporate actions |
| GET | `/portfolio/alerts` | Yes | Portfolio alerts |
| GET | `/portfolio/tax-summary` | Yes | Tax summary |
| GET | `/portfolio/dividends` | Yes | Dividend data |
| POST | `/portfolio/stress-test` | Yes | Run stress test |
| GET | `/portfolio/mf-analytics` | Yes | MF analytics |
| GET | `/portfolio/today` | Yes | Today's action queue |
| GET | `/portfolio/brief` | Yes | Portfolio text brief |

#### Market Data

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/market/history` | Yes | Market price history |
| GET | `/market/quotes` | Yes | Live market quotes |
| GET | `/market/news` | Yes | Market news |
| GET | `/market/indices` | Yes | Index data (Nifty, Sensex) |

#### Memory & User

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/memory/stats` | Yes | Memory statistics |
| GET | `/memory/facts` | Yes | Browse facts |
| GET | `/memory/sessions` | Yes | Session summaries |
| DELETE | `/memory/clear/{target}` | Yes | Clear target facts |
| GET | `/user/token-usage` | Yes | Token usage stats |

#### System & Pages

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Health check |
| GET | `/capabilities` | No | Agent capabilities |
| GET | `/config` | No | Config info |
| GET | `/` | No | Landing page (HTML) |
| GET | `/app` | No | Widget page (loads React app) |
| GET | `/landing` | No | Landing page |
| GET | `/login` | No | Login page |
| GET | `/signup` | No | Signup page |
| GET | `/profile` | No | Profile page |
| GET | `/settings` | No | Settings page |

---

## Security & Auth

### Authentication Flow

```
┌─────────────────────────────────────────────────────┐
│                  AUTH ARCHITECTURE                   │
│                                                      │
│  ┌──────────────┐         ┌──────────────────┐      │
│  │  Email/Pass  │────────►│  Supabase Auth    │      │
│  │  Signup/Login│         │  (or Local JWT)   │      │
│  └──────────────┘         └────────┬─────────┘      │
│                                    │                 │
│  ┌──────────────┐                  │                 │
│  │  Google      │─────────────────►│                 │
│  │  OAuth (GIS) │                  │                 │
│  └──────────────┘                  ▼                 │
│                          ┌──────────────────┐      │
│                          │  JWT Token        │      │
│                          │  • user_id       │      │
│                          │  • email         │      │
│                          │  • tenant_id     │      │
│                          │  • exp           │      │
│                          └────────┬─────────┘      │
│                                   │                  │
│                          Set as Bearer token         │
│                          in Authorization header     │
│                                   │                  │
│                                   ▼                  │
│                          ┌──────────────────┐      │
│                          │  auth_guard.py    │      │
│                          │  • Verify JWT     │      │
│                          │  • Extract user   │      │
│                          │  • Check expiry   │      │
│                          └──────────────────┘      │
└─────────────────────────────────────────────────────┘
```

### Key Security Features

- **Rate Limiting:** `InMemSlidingWindowRateLimiter` — configurable requests/window per IP or token
- **JWT Validation:** `auth_guard.py` supports both local JWT secrets and Supabase auth tokens
- **CORS:** Configurable origins via `CORS_ORIGINS` environment variable
- **Input Validation:** Pydantic models for all request bodies
- **Password Hashing:** Via Supabase (argon2) or local bcrypt
- **Email Verification:** Supabase email verification flow
- **Password Reset:** Email code → reset flow

### Supabase Integration (`gateway/supabase_client.py`)

- REST API client using httpx
- Manages user creation, auth, profile updates
- Email verification and password reset flows
- Admin API key for server-side operations

---

## Monitoring & Telemetry

ProspektLab uses **Azure Application Insights** for both frontend and backend telemetry, with structured event tracking, dependency monitoring, and exception reporting.

### Frontend Telemetry (`Frontend/app/src/telemetry.ts`)

- Custom lightweight telemetry client (no SDK dependency)
- Batched envelope posting to Application Insights ingestion endpoint
- Tracks:
  - **Page views** — route changes via `TelemetryRouteTracker`
  - **Custom events** — user actions (login, research, portfolio)
  - **Dependencies** — API call duration and success/failure
  - **Exceptions** — unhandled errors with stack traces
  - **Metrics** — custom measurements
- Runtime configuration via `window.__CONFIG__.telemetry` (injected by Amplify build)
- Configuration keys: `connectionString`, `roleName`, `cloudRoleInstance`, `enabled`

### Backend Telemetry (`finagent/telemetry.py`)

- `TelemetryClient` class with async support (httpx)
- Tracks:
  - **Requests** — HTTP method, URL, duration, status code, result code
  - **Custom events** — research phases, agent execution, data fetches
  - **Exceptions** — captured with stack trace and severity
  - **Metrics** — token usage, latency, quality scores
- Telemetry user context: email, user_id, tenant_id, auth_provider
- Environment-driven configuration via `APPINSIGHTS_*` variables
- Graceful degradation: telemetry failures never block application logic

### Runtime Configuration (`env-config.js`)

Generated at Amplify build time, this file injects:
- `window.__BACKEND_URL` — backend API base URL
- `window.__CONFIG__` — environment, telemetry connection string, role names

For local development, `env-config.js` defaults to `http://127.0.0.1:8000`.

---

## Deployment

### Docker

**File:** `Dockerfile`

```dockerfile
FROM python:3.11-slim
# Install system deps (Chromium libs for Crawl4AI)
# Install Python deps from finagent/requirements-finagent.txt
# Run crawl4ai-setup to download Chromium browser binary
# Copy finagent/ into /app/finagent/
# Expose 8080
# CMD: uvicorn finagent.gateway.run:app --host 0.0.0.0 --port 8080
```

The Dockerfile runs only the FastAPI gateway. MCP servers (discovery, quant) would be deployed as separate containers in production.

### AWS Amplify Build (`Frontend/app/amplify.yml`)

The Amplify build pipeline:

1. **preBuild:** `npm ci` to install dependencies, generates `public/env-config.js` from environment variables (`BACKEND_API_URL`, `APPINSIGHTS_ENABLED`, `APPINSIGHTS_CONNECTION_STRING`)
2. **build:** `npm run build` (Vite production build → `dist/`)
3. **postBuild:** Verification of build output
4. **Artifacts:** `dist/` directory served via CloudFront CDN
5. **Cache:** `node_modules/` preserved between builds
6. **Rewrites:** SPA fallback for client-side routing; API proxy rewrites configured in Amplify Console for `/auth`, `/chat`, `/portfolio`, etc.

### AWS Infrastructure

```
┌────────────────────────────────────────────────────┐
│                    AWS CLOUD                        │
│                                                     │
│  ┌──────────────┐    ┌──────────────────────────┐  │
│  │  GitHub       │    │  AWS ECR                 │  │
│  │  Actions      │───►│  Container Registry       │  │
│  └──────────────┘    └─────────┬────────────────┘  │
│                                │                     │
│  ┌──────────────┐              │                     │
│  │  AWS          │              ▼                     │
│  │  CodeBuild    │───► ┌──────────────────────┐    │
│  └──────────────┘      │  AWS ECS Fargate     │    │
│                        │  • Task definition    │    │
│                        │  • Service (8080)     │    │
│                        │  • Auto-scaling       │    │
│                        └──────────────────────┘    │
│                                                     │
│  ┌──────────────────────────┐                       │
│  │  AWS Amplify             │                       │
│  │  • Frontend/app/ → dist/ │                       │
│  │  • CDN (CloudFront)      │                       │
│  │  • HTTPS                 │                       │
│  └──────────────────────────┘                       │
└────────────────────────────────────────────────────┘
```

### CI/CD Pipelines

**GitHub Actions (`.github/workflows/deploy-production.yml`)**:
- Trigger: push to `production` or `main`
- Build Docker image, push to ECR
- Update ECS task definition, force new deployment
- Health check (curl `/health`)
- Trigger Amplify deploy
- Slack notification

**AWS CodeBuild (`buildspec.yml`, `buildspec-prod.yml`)**:
- Alternative deployment path
- Docker build + push to ECR
- ECS service update

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | OpenAI API key for GPT-4o |
| `FINAGENT_HOME` | Override data directory (default: `.finagent/`) |
| `CORS_ORIGINS` | Allowed CORS origins (comma-separated) |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase admin/service key |
| `JWT_SECRET` | JWT signing secret |
| `MCP_DISCOVERY_URL` | Discovery MCP server URL (default: `http://127.0.0.1:8003/mcp`) |
| `MCP_QUANT_URL` | Quant MCP server URL (default: `http://127.0.0.1:8005/mcp`) |
| `SMTP_*` | SMTP config for email verification/password reset |
| `FINAGENT_MAX_STEPS` | Default max research steps |
| `FINAGENT_DEEP_DIVE` | Enable deep dive (true/false) |
| `FINAGENT_REFLECTION` | Enable reflection loop (true/false) |
| `FINAGENT_QUALITY_THRESHOLD` | Min quality score for reflection |
| `FINAGENT_MEMORY` | Enable memory system (true/false) |

---

## Data Flow Diagrams

### Research Session: Full Data Flow

```
User Query: "Analyze TCS valuation"
     │
     ▼
┌──────────────────────────────────────────────────────────┐
│ GATEWAY: run.py                                           │
│                                                            │
│  route_objective() in intent_router.py                    │
│    ├── ChatHistory (context for follow-up detection)       │
│    ├── Entity Extraction → "TCS"                           │
│    ├── Complexity → moderate                               │
│    ├── Deep Research? → No                                 │
│    └── Portfolio Scope? → No                               │
│                                                            │
│  Spawn: asyncio.create_task(run_research_session(...))     │
│  Return: { "session_id": "abc-123" }                       │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│ CORE LOOP: run_agent.py                                   │
│                                                            │
│  ┌────────────────────────────────────────────────────┐   │
│  │ 1. IDENTIFY                                         │   │
│  │    resolve_entity("TCS") →                           │   │
│  │      ticker: "TCS.NS"                               │   │
│  │      name: "Tata Consultancy Services"              │   │
│  │      geo: "IN"  sector: "IT"                        │   │
│  │      preferred_domains: [screener.in, ...]          │   │
│  │    load memory facts, retrieve playbooks             │   │
│  └────────────────────────────────────────────────────┘   │
│                              │                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │ 2. ENRICHMENT (parallel, asyncio.gather)            │   │
│  │    fetch_yahoo_quote("TCS.NS")                      │   │
│  │    fetch_wikipedia_summary("TCS")                    │   │
│  │    fetch_india_snapshot("TCS")                       │   │
│  │    get_usd_inr()                                     │   │
│  │    fetch_news("TCS")                                 │   │
│  │    search_reddit("TCS")                              │   │
│  │    search_hackernews("TCS")                          │   │
│  │    fetch_stocktwits("TCS")                           │   │
│  │    fetch_shareholding_pattern("TCS.NS")              │   │
│  │    ↓ EnrichmentBundle populated                     │   │
│  └────────────────────────────────────────────────────┘   │
│                              │                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │ 3. BREADTH SURVEY                                    │   │
│  │    localize_search_query("TCS valuation", "IN")      │   │
│  │    → "Tata Consultancy Services valuation analysis" │   │
│  │                                                      │   │
│  │    4 search angles (each → DuckDuckGo → top 6 URLs) │   │
│  │    Angle 1: "business overview + fundamentals"       │   │
│  │    Angle 2: "growth catalysts + future outlook"      │   │
│  │    Angle 3: "risk factors + red flags"              │   │
│  │    Angle 4: "competitive landscape + industry"       │   │
│  │                                                      │   │
│  │    Each URL → scrape → dedup → score                 │   │
│  │    → 24 scraped documents (filtered/scored)          │   │
│  └────────────────────────────────────────────────────┘   │
│                              │                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │ 4. DEEP DIVE (iterative, up to 4 rounds)            │   │
│  │    Round 1: "Why is TCS PE premium shrinking?"      │   │
│  │    Round 2: "TCS AI/GenAI revenue contribution"     │   │
│  │    → Stop after 2 rounds (no significant gaps)       │   │
│  └────────────────────────────────────────────────────┘   │
│                              │                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │ 5. ANALYSIS                                          │   │
│  │    Multi-agent waves (10 specialists)                │   │
│  │    detect_conflicts(findings)                        │   │
│  │    score_research(data, findings)                    │   │
│  │    Verifier cross-checks claims                      │   │
│  │    Blind-spot detector fills gaps                    │   │
│  │    Quality ≥ 75 → skip reflection                    │   │
│  └────────────────────────────────────────────────────┘   │
│                              │                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │ 6. SYNTHESIS                                         │   │
│  │    synthesize_memo(bundle) → 8-section markdown      │   │
│  │    • Executive Summary                               │   │
│  │    • Business Overview                               │   │
│  │    • Financial Analysis (INR crore)                   │   │
│  │    • Valuation (DCF: ₹3842 PE: ₹3950 EV/EBITDA)     │   │
│  │    • Risks & Red Flags                               │   │
│  │    • Market Sentiment                                │   │
│  │    • Competitive Landscape                           │   │
│  │    • Verdict: Buy with 15% margin of safety          │   │
│  │                                                      │   │
│  │    build_answer_artifact() → frontend-ready data     │   │
│  └────────────────────────────────────────────────────┘   │
│                              │                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │ PERSISTENCE                                          │   │
│  │    store_facts() → SQLite                            │   │
│  │    save_memo() → .finagent/memos/                    │   │
│  │    save_session_events() → JSONL                     │   │
│  │    maybe_promote_playbook() → playbooks.sqlite3      │   │
│  └────────────────────────────────────────────────────┘   │
│                                                            │
│  Event Bus: BUS.emit() at every step                       │
│  → phase, step_start, agent_start, source, done            │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│ FRONTEND: Dashboard.tsx                                   │
│                                                            │
│  SSE stream receives events in order:                      │
│    phase: "enriching"                                      │
│    step_start: "Fetching Yahoo Finance quote..."           │
│    step_end: "Yahoo Finance complete"                      │
│    agent_start: "Valuation Analysis"                       │
│    agent_end: "Valuation complete"                         │
│    source: "screener.in"                                   │
│    done: { memo_url: "..." }                               │
│                                                            │
│  AgentThinking.tsx shows live progress                     │
│  MessageBubble.tsx renders final memo                      │
│  RichResponse.tsx shows charts, metrics, citations          │
└──────────────────────────────────────────────────────────┘
```

### Portfolio Ingestion Flow

```
User uploads eCAS PDF
     │
     ▼
POST /api/portfolio/upload-cas
     │
     ▼
parse_portfolio_document(bytes, filename)
     │
     ├── PDF? → pdf_transformer.py (PyMuPDF) → extract tables
     ├── XLSX? → openpyxl → extract rows
     ├── CSV? → csv module → extract rows
     └── CAS? → cas_adapter.py → parse CAMS/KFintech eCAS
     │
     ▼
File parsed → raw text/tables
     │
     ▼
mineru_transformer.py / markdown_extractor.py
→ Convert to structured markdown
     │
     ▼
isin_resolver.py
→ Resolve ISIN → ticker + name
     │
     ▼
PortfolioExtractionSchema (Pydantic)
→ List of extracted positions with confidence
     │
     ▼
Return to frontend for user review
     │
     ├── POST /api/portfolio/confirm-extraction
     │   → Save to position_mirrors table
     │   → Trigger analytics computation
     │
     └── POST /api/portfolio/cancel-extraction
         → Discard extraction
```

---

## Complete File Inventory

### Backend Python Files

#### Core (`finagent/` root)

| File | Purpose |
|------|---------|
| `__init__.py` | Package init, Windows CA cert fix, .env loading, version (0.1.0) |
| `__main__.py` | `python -m finagent` entry point |
| `run_agent.py` | Core agent loop (6-phase pipeline: identify → enrich → breadth → deep-dive → analysis → synthesis) |
| `synthesis.py` | LLM memo synthesis engine (OpenAI streaming + template fallback) |
| `events.py` | SessionBus: in-process pub/sub event bus with JSONL persistence |
| `api.py` | Legacy standalone FastAPI |
| `cli.py` | CLI: preflight, run-stub commands |
| `accuracy_validator.py` | Claim validation and source confidence scoring |
| `intent.py` | Keyword-based intent detection + rich mode classification |
| `rich_builder.py` | RichResponse builder: turns tool outputs into typed structured visuals |
| `paths.py` | Data directory path resolution |
| `prompt_builder.py` | System prompt loader |
| `research_planner.py` | ResearchPlan, PlanStep Pydantic models |
| `runtime_provider.py` | LLM provider resolution (OpenAI/xAI) |
| `settings.py` | Environment-driven FinAgentSettings |
| `telemetry.py` | Azure Application Insights telemetry client (async httpx) |
| `portfolio_mirrors.py` | Position mirror CRUD (SQLite) |
| `portfolio_sentinel.py` | Portfolio monitoring |
| `test_events.py` | Event bus tests |

#### Reference Data (`finagent/data/`)

| File | Purpose |
|------|---------|
| `isin_master.json` | ISIN-to-ticker lookup map for Indian equities |
| `nifty500_sectors.json` | Nifty 500 sector classification data |
| `amfi_schemes_meta.json` | Indian mutual fund scheme metadata from AMFI |
| `news_cache.sqlite3` | Cached news articles with TTL |
| `sector_cache.sqlite3` | Cached sector classification data |
| `build_isin_master.py` | Script to rebuild ISIN master from source data |
| `generate_sector_lookup.py` | Script to regenerate sector lookup data |

#### Agent (`finagent/agent/`)

| File | Purpose |
|------|---------|
| `reflection.py` | Reflection loop for iterative self-improvement |

#### Agents (`finagent/agents/`)

| File | Purpose |
|------|---------|
| `__init__.py` | Re-exports: Orchestrator, SubAgentContext, Verifier, detect_blind_spots |
| `base.py` | BaseSubAgent ABC, SubAgentContext, Finding, AgentTaskResult |
| `blindspot.py` | Auto-generate follow-up questions for uncovered areas |
| `orchestrator.py` | Wave-based parallel agent execution engine |
| `verifier.py` | Cross-agent claim verification and confidence adjustment |
| `specialists/__init__.py` | `default_roster()` factory (10 agents) |
| `specialists/accounting.py` | Forensic accounting anomaly detection |
| `specialists/community.py` | Reddit/StockTwits/HN sentiment analysis |
| `specialists/competitor.py` | Peer comparison and competitive analysis |
| `specialists/financials.py` | Financial statement analysis |
| `specialists/governance.py` | Corporate governance review |
| `specialists/macro.py` | Macro-economic overlay |
| `specialists/news.py` | News sentiment and material events |
| `specialists/risk.py` | Risk factor identification |
| `specialists/technical.py` | Technical price analysis |
| `specialists/valuation.py` | Valuation framework analysis |

#### Analysis (`finagent/analysis/`)

| File | Purpose |
|------|---------|
| `conflicts.py` | Cross-source conflict detection |
| `quality.py` | Research quality scoring (0-100) |

#### Gateway (`finagent/gateway/`)

| File | Purpose |
|------|---------|
| `run.py` | Main FastAPI gateway: all REST + SSE endpoints (~60 routes) |
| `auth_guard.py` | JWT validation (local + Supabase) |
| `session.py` | SessionRecord dataclass |
| `supabase_client.py` | Supabase Admin API client |
| `server.cjs` | CommonJS server entry point |
| `test_gateway.py` | Gateway tests |
| `test_security.py` | Security tests |
| `landing.html` | Static landing page |
| `login.html` | Static login page |
| `signup.html` | Static signup page |
| `profile.html` | Static profile page |
| `settings.html` | Static settings page |
| `widget.html` | Static widget page |
| `components/Charts/` | Server-side chart components |

#### Geography & Entity Resolution (`finagent/geo/`)

| File | Purpose |
|------|---------|
| `entity_resolver.py` | Main entity resolution pipeline |
| `ticker_mapper.py` | Symbol-to-ticker lookup database |
| `currency_policy.py` | Currency formatting policies |
| `jurisdiction_profiles.py` | Country-specific data source configs |
| `query_localizer.py` | Search query adaptation per geography |
| `source_policy.py` | Preferred web domains per entity type |
| `test_entity_resolver.py` | Entity resolver tests |

#### Harness (`finagent/harness/`)

| File | Purpose |
|------|---------|
| `context_manager.py` | Context compression strategies |
| `error_recovery.py` | Error recovery and retry logic |
| `footprint_enforcer.py` | Token/memory/resource limit enforcement |
| `human_gates.py` | Human-in-the-loop approval checkpoints |
| `interrupt_handler.py` | SIGINT/SIGTERM graceful shutdown |
| `orchestrator.py` | Harness-level orchestration |
| `preflight.py` | Pre-flight clarification prompt generation |

#### Ingestion (`finagent/ingestion/`)

| File | Purpose |
|------|---------|
| `cas_adapter.py` | CAMS/KFintech eCAS statement parser |
| `image_ingestion.py` | Screenshot OCR portfolio extraction |
| `isin_resolver.py` | ISIN → ticker resolution |
| `markdown_extractor.py` | Markdown table extraction |
| `mineru_transformer.py` | MinerU PDF transformer |
| `pdf_transformer.py` | Generic PDF text/table extraction (PyMuPDF) |
| `portfolio_document.py` | Unified parser (PDF/CSV/XLSX/CAS) |
| `portfolio_schema.py` | Pydantic models for extracted holdings |

#### Memory (`finagent/memory/`)

| File | Purpose |
|------|---------|
| `chat_memory.py` | Chat history SQLite persistence |
| `store.py` | Memory fact store with per-user scoping |

#### News (`finagent/news/`)

| File | Purpose |
|------|---------|
| `cache.py` | News caching with TTL |
| `dedupe.py` | News article deduplication |
| `scorer.py` | News relevance scoring |
| `sources/amfi_source.py` | AMFI India mutual fund data |
| `sources/bse_announcements.py` | BSE corporate announcements |
| `sources/nse_announcements.py` | NSE corporate announcements |
| `sources/rss_aggregator.py` | Generic RSS feed aggregation |
| `sources/searxng_source.py` | SearXNG meta-search news |
| `sources/sebi_rss.py` | SEBI regulatory RSS feed |

#### Output (`finagent/output/`)

| File | Purpose |
|------|---------|
| `contracts.py` | OutputMode, ResponseDepth enums, AnswerArtifact model |
| `intent_classifier.py` | Query complexity → OutputMode classification |
| `memo_formatter.py` | Memo markdown formatting |
| `renderer.py` | Markdown/JSON rendering |
| `artifact_builder.py` | Structured answer artifact construction |
| `chart_generator.py` | Matplotlib chart image generation |
| `confidence_scorer.py` | 0-100 confidence with source weighting |
| `conflict_reporter.py` | Cross-source conflict reporting |
| `report_exporter.py` | PDF/HTML report export |
| `templates.py` | Output templates per response mode |
| `query_guards.py` | Portfolio comparison query guards |
| `test_artifact_builder.py` | Artifact builder tests |

#### Playbooks (`finagent/playbooks/`)

| File | Purpose |
|------|---------|
| `executor.py` | Playbook execution engine |
| `promoter.py` | Playbook promotion logic (reuse detection) |
| `retriever.py` | Playbook retrieval by keyword/similarity |
| `schema.py` | Playbook data model |
| `store.py` | Playbook SQLite persistence |

#### Portfolio (`finagent/portfolio/`)

| File | Purpose |
|------|---------|
| `action_queue.py` | Daily action queue builder |
| `alerts.py` | Price/MA/event alert computation |
| `analytics.py` | Core portfolio analytics (P&L, XIRR, allocation) |
| `corporate_actions.py` | Bonus/split/dividend corporate actions |
| `dividends.py` | Dividend history and upcoming calendar |
| `holding_detail.py` | Per-holding deep analysis |
| `mf_analytics.py` | Mutual fund scheme analytics |
| `news.py` | Portfolio-level news aggregation |
| `sectors.py` | Sector allocation and breakdown |
| `stress_test.py` | Scenario-based stress testing |
| `tax.py` | STCG/LTCG tax computation |

#### Retrieval (`finagent/retrieval/`)

| File | Purpose |
|------|---------|
| `dense_index.py` | Dense vector (embedding) index |
| `fusion.py` | Hybrid result fusion (dense + sparse) |
| `graph_index.py` | Graph-based document indexing |
| `planner.py` | Retrieval plan builder |
| `reranker.py` | Result reranking |
| `sparse_index.py` | Sparse keyword (BM25) index |
| `test_planner.py` | Planner tests |
| `test_reranker.py` | Reranker tests |

#### Router (`finagent/router/`)

| File | Purpose |
|------|---------|
| `domain_taxonomy.py` | Agent-to-keyword taxonomy mapping |
| `geography_router.py` | Geography-based routing decisions |
| `intent_router.py` | Intent classification, entity extraction, portfolio scope, query routing |
| `policies.py` | Deep research trigger policy (keyword matching) |
| `tool_selector.py` | Tool selection by intent/entity |
| `test_intent_router.py` | Intent router tests |

#### State (`finagent/state/`)

| File | Purpose |
|------|---------|
| `checkpoint.py` | Checkpoint, StepResult data models |
| `citation_log.py` | Citation tracking and source linking |
| `compression.py` | Context compression utilities |
| `research_state.py` | Research state store (SQLite) |
| `session_context.py` | Thread-local session context (contextvars: active agents, MCPs, websites per async task chain) |

#### Storage (`finagent/storage/`)

| File | Purpose |
|------|---------|
| `sqlite.py` | SQLite WAL connection helper |
| `supabase_store.py` | Supabase PostgreSQL-backed storage for portfolio mirrors, rate limiting (shared across containers) |

#### Tools — Data (`finagent/tools/data/`)

| File | Purpose |
|------|---------|
| `yahoo_finance.py` | yfinance quote + fundamentals |
| `india.py` | NSE/Screener.in/Moneycontrol/SEBI fetchers |
| `sec_edgar.py` | SEC EDGAR company facts API |
| `sec_filings.py` | SEC filing narratives |
| `wikipedia.py` | Wikipedia REST summary API |
| `news_feed.py` | Google News RSS fetcher |
| `reddit.py` | Reddit search |
| `hackernews.py` | HN Algolia search API |
| `stocktwits.py` | StockTwits sentiment API |
| `forex.py` | USD/INR forex rate fetcher |
| `units.py` | Indian number formatting (crore/lakh) |
| `cache.py` | Per-session in-memory query cache |
| `test_units.py` | Units tests |

#### Tools — Web (`finagent/tools/web/`)

| File | Purpose |
|------|---------|
| `scraper.py` | DuckDuckGo search + HTML scraping |
| `crawl4ai_sites.py` | Crawl4AI full-page extraction |
| `searxng_client.py` | SearXNG meta-search client |
| `http_fetcher.py` | Shared async httpx client |
| `table_parser.py` | HTML table extraction |
| `test_ingestion.py` | Ingestion tests |

#### Tools — MCP Servers (`finagent/tools/mcp_servers/`)

| File | Status | Purpose |
|------|--------|---------|
| `discovery_server.py` | **Active** | Consolidated OSINT & Data Discovery (NSE + search + docs) |
| `quant_server.py` | **Active** | Consolidated Quantitative Compute (fundamentals + valuation + risk) |
| `nse_server.py` | Legacy | Standalone NSE Market Data |
| `research_server.py` | Legacy | Standalone Web & News Search |
| `fundamentals_server.py` | Legacy | Standalone Fundamentals |
| `docs_server.py` | Legacy | Standalone Documents |
| `mcp_valuation.py` | Legacy | Standalone Valuation |

#### Tools — Other (`finagent/tools/`)

| File | Purpose |
|------|---------|
| `registry.py` | Tool registry |
| `mcp_config.py` | MCP server connection configuration (discovery + quant) |
| `valuation_engine.py` | Deterministic finance math (DCF, PE, Graham, etc.) |
| `mcp/dynamic_loader.py` | Dynamic MCP tool loading |
| `browser/deep_crawler.py` | Playwright deep crawler (ARCHIVED — NOT ACTIVE) |
| `social/viral_verifier.py` | Pump-and-dump signal detection |
| `prospektlab/enricher.py` | Entity enrichment |
| `prospektlab/entity_fetcher.py` | Entity data fetching |
| `prospektlab/event_monitor.py` | Event monitoring |
| `prospektlab/exporter.py` | Data export |
| `prospektlab/navigator.py` | Data navigation |

#### Tests (`finagent/tests/`)

| File | Purpose |
|------|---------|
| `test_synthesis_speed_profiles.py` | Synthesis speed tests |
| `test_rich_builder.py` | Rich builder tests |
| `test_v3_backend_contract.py` | V3 backend contract tests |

### Frontend TypeScript Files

#### Root & API

| File | Purpose |
|------|---------|
| `main.tsx` | React entry point, AuthProvider |
| `App.tsx` | Route definitions, auth guards |
| `index.css` | Global design system (dark theme) |
| `telemetry.ts` | Azure Application Insights telemetry client (batched envelope posting) |
| `api/client.ts` | Full API client + SSE streaming |
| `context/AuthContext.tsx` | Auth state + Google OAuth |
| `data/indianStocks.ts` | Indian stock reference data |

#### Pages

| File | Purpose |
|------|---------|
| `pages/Dashboard.tsx` | Main workspace |
| `pages/Login.tsx` | Auth pages (login, signup, password reset) |
| `pages/Onboarding.tsx` | Portfolio onboarding |
| `pages/LandingPage.tsx` | Product landing page |
| `pages/Features.tsx` | Feature showcase |
| `pages/Pricing.tsx` | Pricing tiers |
| `pages/Testimonials.tsx` | User testimonials |
| `pages/ContactUs.tsx` | Contact form page |

#### Components — Layout

| File | Purpose |
|------|---------|
| `components/layout/AppShell.tsx` | Main layout wrapper |
| `components/layout/Logo.tsx` | Logo |
| `components/layout/Sidebar.tsx` | Navigation sidebar |

#### Components — Chat

| File | Purpose |
|------|---------|
| `components/chat/AgentThinking.tsx` | Agent progress visualization |
| `components/chat/ChatInput.tsx` | Chat input + depth selector |
| `components/chat/MessageBubble.tsx` | Chat message rendering |
| `components/chat/RichResponse.tsx` | Rich data visualization |
| `components/chat/SuggestedPrompts.tsx` | Prompt suggestions |
| `components/chat/CalloutBlock.tsx` | Callout/highlight rendering |
| `components/chat/HtmlArtifact.tsx` | HTML artifact rendering |
| `components/chat/SectionBlock.tsx` | Section block wrapper |

#### Components — Charts

| File | Purpose |
|------|---------|
| `components/charts/AreaChart.tsx` | Chart.js area chart |
| `components/charts/BarChart.tsx` | Chart.js bar chart |
| `components/charts/DonutChart.tsx` | Chart.js donut chart |
| `components/charts/InteractiveChart.tsx` | Interactive time-series |
| `components/charts/MetricCard.tsx` | Single metric card |
| `components/charts/ThemeProvider.ts` | Chart.js theme config |
| `components/charts/RadarChart.tsx` | Radar/spider chart |
| `components/charts/TreemapChart.tsx` | Treemap visualization |
| `components/charts/TableBlock.tsx` | Table rendering |

#### Components — Dashboard

| File | Purpose |
|------|---------|
| `components/dashboard/IndexTickerCard.tsx` | Nifty/Sensex ticker |
| `components/dashboard/PortfolioTable.tsx` | Holdings table |
| `components/dashboard/QuickActions.tsx` | Quick action buttons |
| `components/dashboard/QuickPulse.tsx` | Market pulse overview |
| `components/dashboard/RecentInsights.tsx` | Recent research list |
| `components/dashboard/Sparkline.tsx` | Mini sparkline chart |
| `components/dashboard/WatchlistCard.tsx` | User watchlist |
| `components/dashboard/AssetHistoryModal.tsx` | Asset history modal |

### Infrastructure Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Python 3.11-slim, Crawl4AI + Chromium, FastAPI gateway |
| `pyproject.toml` | Project metadata, core dependencies (summary only) |
| `uv.lock` | UV lockfile for local development |
| `package.json` | Root: Playwright dependency only (for browser tests) |
| `finagent/requirements-finagent.txt` | **Authoritative** dependency list for production builds |
| `.github/workflows/deploy-production.yml` | CI/CD: build → ECR → ECS → Amplify |
| `buildspec.yml` | AWS CodeBuild specification |
| `buildspec-prod.yml` | AWS CodeBuild production specification |
| `Frontend/app/amplify.yml` | AWS Amplify build specification (Vite build + env-config.js generation) |
| `deployment/` | Deployment configurations (backend deploy scripts, Fargate YAML, Supabase SQL) |
| `scratch/` | Ad-hoc scripts and experimental code |
| `start_server.ps1` | Local server start script (PowerShell) |

---

## Architectural Principles

1. **LLM for reasoning only** — All math, data fetching, and formatting happen in deterministic Python. The LLM synthesizes, interprets, and writes — never calculates.

2. **India-first, US-second** — Defaults to IN geography, `.NS` exchange suffix, NSE/Screener.in data, SEBI filings, INR formatting (crore/lakh). US is fully supported but secondary.

3. **Parallelism everywhere** — Enrichment fetches, multi-agent waves, deep research passes, and data operations all run concurrently via `asyncio.gather()`.

4. **Deterministic finance math** — `valuation_engine.py` handles all calculations with Pydantic-validated inputs and transparent intermediate steps.

5. **Event-driven SSE** — The `SessionBus` decouples the agent loop from the HTTP gateway. Events are buffered, persisted to JSONL, and replayable.

6. **Multi-agent Hermes pattern** — 10 specialist sub-agents run in dependency-aware waves, each returning structured findings. An orchestrator merges, a verifier cross-checks, and a blind-spot detector fills gaps.

7. **Two-layer intent system** — `intent_router.py` handles query routing (entities, depth, portfolio scope, deep research eligibility) while `intent.py` handles rich output mode classification.

8. **Durable memory** — Facts persist across sessions per user, enabling long-term learning about companies, sectors, and events.

9. **Portfolio-aware research** — The system understands the user's actual holdings and can scope research to portfolio context, with guards against misclassification.

10. **Structured output** — All outputs follow a consistent 8-section memo template with citations, confidence scores, conflict reports, and geography-appropriate formatting.

11. **Consolidated MCP layer** — Two active MCP servers (discovery + quant) consolidate what was previously 5+ standalone servers, simplifying deployment.

12. **Double dependency source** — `requirements-finagent.txt` is the authoritative production dependency list; `pyproject.toml` is a summary. The Dockerfile uses `requirements-finagent.txt`.

---

*Document generated from full codebase analysis. Last updated: May 2026.*

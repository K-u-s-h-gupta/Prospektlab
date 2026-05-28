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
7. [Deep Research (8-Pass)](#deep-research-8-pass)
8. [MCP Server Layer](#mcp-server-layer)
9. [Portfolio System](#portfolio-system)
10. [Memory System](#memory-system)
11. [Entity Resolution & Geography](#entity-resolution--geography)
12. [Synthesis & Output](#synthesis--output)
13. [Data Layer & External Providers](#data-layer--external-providers)
14. [Frontend Architecture](#frontend-architecture)
15. [Gateway & API Endpoints](#gateway--api-endpoints)
16. [Security & Auth](#security--auth)
17. [Deployment](#deployment)
18. [Data Flow Diagrams](#data-flow-diagrams)
19. [Complete File Inventory](#complete-file-inventory)

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     PRESENTATION LAYER                           │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  React + Vite (Frontend/app/)                              │  │
│  │  • Dashboard, Chat, Portfolio, Auth                       │  │
│  │  • SSE event consumption for real-time agent progress      │  │
│  │  • HashRouter SPA with AuthContext                        │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                    HTTPS / SSE Stream
                              │
┌─────────────────────────────────────────────────────────────────┐
│                     APPLICATION LAYER                            │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  FastAPI Gateway (finagent/gateway/run.py — 2261 loc)      │  │
│  │  • Auth endpoints (local + Supabase JWT)                   │  │
│  │  • Research orchestration & SSE streaming                  │  │
│  │  • Portfolio ingestion & analytics                         │  │
│  │  • Contextualization & intent classification               │  │
│  │  • Rate limiting, CORS, error handling                     │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            │                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Core Agent Loop (finagent/run_agent.py — 2119 loc)        │  │
│  │  • Enrichment → Search → Multi-Agent → Synthesis pipeline  │  │
│  │  • SessionBus event emission                               │  │
│  │  • Configurable depth/reflection/memory                    │  │
│  └───────────────────────────────────────────────────────────┘  │
│                            │                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Multi-Agent Orchestrator (finagent/agents/)               │  │
│  │  10 specialist subagents in dependency-aware waves         │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                     TOOLING & DATA LAYER                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  MCP Servers  │  │  Data Tools  │  │  Valuation Engine    │  │
│  │  :8001 - NSE  │  │  yfinance    │  │  (deterministic math) │  │
│  │  :8002 - Fund │  │  SEC EDGAR   │  │  DCF, PE, Graham,    │  │
│  │  :8003 - Res  │  │  Reddit/HN   │  │  EV/EBITDA, WACC,    │  │
│  │  :8004 - Docs │  │  Wikipedia   │  │  Piotroski, Altman Z │  │
│  │  :8005 - Valu │  │  SearXNG     │  │  DuPont, DDM, CAGR   │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                     STORAGE LAYER                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  SQLite       │  │  Supabase    │  │  File System         │  │
│  │  .finagent/   │  │  PostgreSQL  │  │  memos/, sessions/   │  │
│  │  memory.sqlite│  │  (auth+data) │  │  cache/, users/      │  │
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
| MCP Protocol | FastMCP (>=2.0.0) | Tool servers for NSE, fundamentals, research, docs, valuation |
| Data Validation | Pydantic (>=2.0.0) | Request/response schemas, data models |
| HTTP Client | httpx (async) | Shared HTTP client for all external API calls |
| Finance Data | yfinance (>=0.2.40) | Quotes, fundamentals, financial statements |
| Portfolio Math | PyPortfolioOpt | Portfolio optimization |
| Auth | PyJWT | JWT signing and validation |
| Chart Generation | matplotlib | Answer artifact charts |
| PDF Parsing | PyMuPDF, pypdf | Statement extraction |
| CAS Parsing | casparser | Indian eCAS (CAMS/KFintech) |
| Web Scraping | Crawl4AI, Playwright, BeautifulSoup | Full page extraction, JS rendering |
| Web Search | DuckDuckGo (duckduckgo_search) | Layered breadth searches |
| OCR | (via image_ingestion) | Screenshot portfolio extraction |

### Frontend (TypeScript + React 18)

| Category | Technology | Purpose |
|----------|-----------|---------|
| Framework | React 18.3 | UI components and state |
| Build Tool | Vite 5.x | Dev server, HMR, production bundling |
| Language | TypeScript 5.x | Type safety |
| Routing | react-router-dom v6 (HashRouter) | Client-side routing |
| Charts | Chart.js + react-chartjs-2 | Portfolio and market charts |
| Icons | Lucide React | UI iconography |
| Auth | Google Identity Services (GIS) | Google OAuth |
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

---

## System Layers

### Layer 1: Presentation (Frontend)

**Entry Point:** `Frontend/app/src/main.tsx` → `App.tsx`

The frontend is a single-page React application built with Vite. It uses a `HashRouter` for routing and `AuthContext` for state management. The UI is composed of three main pages:

- **Login** (`pages/Login.tsx`): Handles email login, signup, password reset, and Google OAuth
- **Onboarding** (`pages/Onboarding.tsx`): Portfolio document upload and holding confirmation flow
- **Dashboard** (`pages/Dashboard.tsx`, 2233 loc): Main workspace with portfolio overview, chat interface, charts, news feed, and watchlist

**Key architectural decisions:**
- No Redux or global state library — uses React Context for auth, component-local `useState`/`useRef` for everything else
- SSE (Server-Sent Events) for real-time agent progress with 25s proactive reconnect (accommodates AWS API Gateway's 30s timeout)
- Runtime backend URL resolution: checks `window.__BACKEND_URL`, then `VITE_BACKEND_API_URL`, then falls back to Vite proxy
- All chart components wrap Chart.js with consistent theming via `ThemeProvider.ts`

### Layer 2: Application (Gateway + Agent Loop)

**Gateway:** `finagent/gateway/run.py` (2261 loc) — the central HTTP server on port 8080.

The gateway:
1. Receives user requests (chat, research, portfolio, auth)
2. Manages authentication via JWT (local + Supabase)
3. Contextualizes queries using `LLMQueryContextualizer` (detects follow-ups, determines complexity, extracts entities)
4. Launches research sessions via `run_research_session()` in a background task
5. Streams progress events to the frontend via `SessionBus` → SSE
6. Serves portfolio analytics and static HTML pages

**Key patterns:**
- `InMemSlidingWindowRateLimiter` for per-user rate limiting
- `SessionBus` (`events.py`) — in-process pub/sub event bus using `asyncio.Queue`
- Events persisted to JSONL files for replay on reconnect
- `ChatMemoryManager` for session-scoped chat history
- `LLMQueryContextualizer` for follow-up detection and entity extraction

### Layer 3: Tooling & Data

**MCP Servers** (5 standalone processes):
- `:8001` — NSE Market Data: live quotes, historical, options, shareholding, announcements
- `:8002` — Fundamentals: profiles, statements, ratios, dividends, peer comparison
- `:8003` — Research & News: web/Google/news search, URL extraction
- `:8004` — Documents: document search, PDF/URL ingest, annual reports, prospectus comparison
- `:8005` — Valuation: deterministic DCF, PE, Graham, EV/EBITDA, DDM, WACC, Piotroski, Altman Z, DuPont

**Direct Data Tools** (in-process, no MCP):
- `tools/data/yahoo_finance.py` — yfinance quotes + fundamentals
- `tools/data/india.py` — NSE/Screener.in/Moneycontrol fetchers
- `tools/data/sec_edgar.py` — SEC EDGAR company facts
- `tools/data/sec_filings.py` — SEC filing narratives
- `tools/data/wikipedia.py` — Wikipedia REST summary
- `tools/data/news_feed.py` — Google News RSS
- `tools/data/reddit.py` — Reddit search (WSB, IndianStreetBets, etc.)
- `tools/data/hackernews.py` — HN Algolia search
- `tools/data/stocktwits.py` — StockTwits sentiment
- `tools/data/forex.py` — USD/INR FX rates
- `tools/data/units.py` — Indian number formatting (crore/lakh)

**Web Tools:**
- `tools/web/scraper.py` — DuckDuckGo layered search + page scraping
- `tools/web/crawl4ai_sites.py` — Crawl4AI full-page extraction
- `tools/web/searxng_client.py` — SearXNG meta-search engine
- `tools/web/http_fetcher.py` — Shared async httpx client
- `tools/web/table_parser.py` — HTML table extraction
- `tools/browser/deep_crawler.py` — Playwright deep domain crawler

**Valuation Engine** (`tools/valuation_engine.py`, 994 loc):
- All financial math is deterministic — the LLM *never* does calculations
- Computations: DCF, PE valuation, Graham number, EV/EBITDA, Dividend Discount Model, WACC, CAGR, Piotroski F-Score, Altman Z-Score, DuPont analysis
- Returns structured Pydantic models with intermediate inputs shown

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
  │  3. LLMQueryContextualizer.classify()
  │     → Detect if follow-up to prior chat
  │     → Extract ticker/entities
  │     → Determine complexity (simple/moderate/complex)
  │     → Check if portfolio-scoped
  │  4. Create SessionRecord, set "running"
  │  5. Spawn background task: run_research_session()
  │  6. Return session_id to frontend
  ▼
[Core Agent Loop: run_agent.py → run_research_session()]
  │
  │  PHASE 1: CONTEXT BUILDING
  │  ┌──────────────────────────────────────────────┐
  │  │ • Resolve entities (geo/entity_resolver.py)   │
  │  │   → Canonical ticker, exchange suffix (.NS)   │
  │  │   → Geography detection (IN/US)               │
  │  │   → Preferred data source domains             │
  │  │ • Load memory facts (recall past analysis)     │
  │  │ • Retrieve playbooks (reusable research plans) │
  │  │ • Routing: route_objective() → classification  │
  │  │ • Build ResearchPlan from playbook/default     │
  │  └──────────────────────────────────────────────┘
  │
  │  PHASE 2: ENRICHMENT (parallel)
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
  │  │ → All run concurrently via asyncio.gather()   │
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
  │  PHASE 5: MULTI-AGENT ORCHESTRATION
  │  ┌──────────────────────────────────────────────┐
  │  │ • 10 specialist subagents run in dependency   │
  │  │   waves (see Multi-Agent section below)       │
  │  │ • Each returns structured Finding objects     │
  │  │ • Verifier cross-checks key claims           │
  │  │ • Blind spot detector generates follow-ups   │
  │  └──────────────────────────────────────────────┘
  │
  │  PHASE 6: ANALYSIS
  │  ┌──────────────────────────────────────────────┐
  │  │ • Cross-source conflict detection             │
  │  │ • Research quality scoring (0-100)            │
  │  │ • Claim accuracy validation                   │
  │  │ • Pump & dump signal detection               │
  │  └──────────────────────────────────────────────┘
  │
  │  PHASE 7: REFLECTION (optional, configurable)
  │  ┌──────────────────────────────────────────────┐
  │  │ • If quality < threshold (default 75):        │
  │  │   → Identify weak areas                      │
  │  │   → Generate targeted follow-up queries       │
  │  │   → Re-run search + analysis for weaknesses  │
  │  │   → Max 5 reflection rounds                  │
  │  │   → Max 6 follow-up queries per round        │
  │  └──────────────────────────────────────────────┘
  │
  │  PHASE 8: SYNTHESIS
  │  ┌──────────────────────────────────────────────┐
  │  │ • Build EnrichmentBundle from all data        │
  │  │ • Call synthesize_memo() (OpenAI GPT-4o)     │
  │  │ • 8-section structured memo:                 │
  │  │   1. Executive Summary                        │
  │  │   2. Business Overview                        │
  │  │   3. Financial Analysis                       │
  │  │   4. Valuation                                │
  │  │   5. Risks & Red Flags                        │
  │  │   6. Market Sentiment                         │
  │  │   7. Competitive Landscape                    │
  │  │   8. Verdict / Investment Thesis              │
  │  │ • Cross-source conflict report                │
  │  │ • Confidence score with rationale             │
  │  │ • Citation log (all sources linked)           │
  │  │ • INR-first formatting (crore/lakh)           │
  │  └──────────────────────────────────────────────┘
  │
  │  PHASE 9: PERSISTENCE
  │  ┌──────────────────────────────────────────────┐
  │  │ • Write memo to .finagent/memos/              │
  │  │ • Store facts to memory SQLite                │
  │  │ • Save session events to JSONL                │
  │  │ • Promote to playbook if reusable             │
  │  │ • Update session status to "completed"        │
  │  └──────────────────────────────────────────────┘
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
- `phase_change` — Current pipeline phase (enriching, searching, analyzing, synthesizing)
- `step_start` / `step_end` — Individual tool call with label + metadata
- `agent_start` / `agent_end` — Sub-agent execution with name + progress
- `source` — Source domain discovered
- `status` — Session status updates
- `done` — Final result with memo URL
- `error` — Error events with message

---

## Core Agent Loop

**File:** `finagent/run_agent.py` (2119 lines)

The core loop is the heart of the system. It is configured via `AgentLoopConfig`:

```python
@dataclass
class AgentLoopConfig:
    max_steps: int = 40              # Max enrichment + search steps
    enable_scraping: bool = True     # Full page scraping
    enable_enrichment: bool = True   # Yahoo, Wikipedia, news, etc.
    enable_deep_dive: bool = True    # Iterative deep dive phase
    enable_memory: bool = True       # Recall past facts
    enable_reflection: bool = True   # Self-improvement loop
    reflection_max_rounds: int = 5   # Max reflection iterations
    quality_threshold: float = 75.0  # Min quality before reflection
    auto_depth: bool = True          # Auto-adjust steps by complexity
```

**Entry point:** `run_research_session(objective, config, session_id=None) → str`

The function:
1. Resolves entities and builds context
2. Runs enrichment in parallel (asyncio.gather)
3. Executes layered breadth search
4. Performs iterative deep dives
5. Orchestrates multi-agent analysis
6. Runs reflection if quality below threshold
7. Synthesizes final memo
8. Persists everything
9. Returns final answer text

**Key design principle:** The LLM only does reasoning and synthesis. All data fetching, computation, and formatting happen in deterministic Python code.

---

## Multi-Agent Orchestration

**Directory:** `finagent/agents/`

### Design Pattern: Hermes Wave-Based Parallel Orchestration

The `Orchestrator` (`agents/orchestrator.py`) manages 10 specialist sub-agents, each implemented as an async function returning structured `Finding` objects. Agents are organized into **dependency waves** — agents in the same wave can run in parallel, but later waves may depend on earlier waves' output.

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

## Deep Research (8-Pass)

**Endpoint:** `POST /research/deep`

Deep research runs **8 parallel passes**, each a complete research session with its own 40-step budget:

| Pass | Theme | Description |
|------|-------|-------------|
| 0 | **Financials Foundation** | Multi-year financial analysis, segment breakdown, cash flow quality |
| 1 | **Competitive Moat** | Porter's 5 forces, barrier to entry, switching costs, brand value |
| 2 | **Management & Governance** | Leadership track record, capital allocation history, insider ownership |
| 3 | **Valuation Deep-Dive** | Multiple valuation frameworks, scenario analysis, margin of safety |
| 4 | **Risk & Red Flags** | Forensic accounting, legal issues, regulatory headwinds |
| 5 | **Macro / Sector Overlay** | Industry cycle, policy impacts, global macro tailwinds/headwinds |
| 6 | **Institutional / Shareholding** | FII/DII flows, promoter holding trends, pledge data |
| 7 | **Hidden Catalysts** | Unrecognized assets, upcoming events, optionality value |
| **Synthesis** | Serial pass integrates all 8 into investment-grade report |

The 8 parallel passes run concurrently via `asyncio.gather()`. The final synthesis pass runs serially after all 8 complete, integrating findings into a single comprehensive report.

---

## MCP Server Layer

The Model Context Protocol (MCP) servers are standalone Python processes using FastMCP. Each exposes tools that LangGraph agents can call.

### Server Inventory

| Port | Server | File | Tools |
|------|--------|------|-------|
| 8001 | **NSE Market Data** | `tools/mcp_servers/nse_server.py` | get_quote, get_history, get_option_chain, get_shareholding, get_announcements, get_board_meetings |
| 8002 | **Fundamentals** | `tools/mcp_servers/fundamentals_server.py` | get_profile, get_statements (IS/BS/CF), get_ratios, get_quarterly, get_peers, get_dividends |
| 8003 | **Research & News** | `tools/mcp_servers/research_server.py` | search_web, search_finance, search_news, extract_url |
| 8003* | **Discovery** | `tools/mcp_servers/discovery_server.py` | Entity discovery and enrichment |
| 8004 | **Documents** | `tools/mcp_servers/docs_server.py` | search_docs, ingest_pdf, ingest_url, get_annual_report, compare_prospectus |
| 8005 | **Valuation** | `tools/mcp_servers/mcp_valuation.py` | compute_dcf, compute_pe, compute_graham, compute_ev_ebitda, compute_ddm, compute_wacc, compute_cagr, compute_piotroski, compute_altman_z, compute_dupont, full_valuation |
| 8005* | **Quant** | `tools/mcp_servers/quant_server.py` | Quantitative analysis and screening |

*\* Shared port — multiple servers can run on the same port using different endpoints.*

### MCP Configuration

**File:** `tools/mcp_config.py`

Dynamically configures MCP server connections via environment variables:
- `MCP_NSE_URL` (default: `http://localhost:8001`)
- `MCP_FUNDAMENTALS_URL` (default: `http://localhost:8002`)
- `MCP_RESEARCH_URL` (default: `http://localhost:8003`)
- `MCP_DOCS_URL` (default: `http://localhost:8004`)
- `MCP_VALUATION_URL` (default: `http://localhost:8005`)

**Dynamic loading** (`tools/mcp/dynamic_loader.py`): Loads MCP tools at runtime, supporting hot-reload and fallback when servers are unavailable.

---

## Portfolio System

### Architecture

```
                    POST /api/portfolio/upload-cas
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
| POST | `/api/portfolio/upload-cas` | Upload eCAS/PDF/CSV/XLSX |
| POST | `/api/portfolio/upload-screenshot` | Upload screenshot (OCR) |
| POST | `/api/portfolio/confirm-extraction` | Confirm extracted holdings |
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

When a user has holdings and asks a general question like "should I rebalance?", the `LLMQueryContextualizer` detects portfolio scope and feeds holdings data into the agent loop's context, enabling:
- "What's my worst performing stock?" → queries portfolio + analyzes
- "Am I overexposed to IT?" → computes sector allocation + research
- "Show me news affecting my holdings" → portfolio news endpoint

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
- Facts are normalized by target (`normalize_target()`)
- Facts categorized: identity, financial, risk, market_data, news_event, conflict, sentiment, valuation
- Recalled on subsequent sessions via `recall_facts(target, limit=n)`
- Stale fact pruning and deduplication

### Chat Memory (`memory/chat_memory.py`)

- Per-session chat history persistence
- `ChatMemoryManager` class:
  - `save_message(session_id, role, content)`
  - `get_history(session_id, limit=n)` → returns recent messages
  - `clear_history(session_id)`
- Used by `LLMQueryContextualizer` for follow-up detection
- Used to build conversation context for the LLM

### Endpoints

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

**Directory:** `finagent/synthesis.py` (2081 lines), `finagent/output/`

### Synthesis Pipeline

```
All research data
  │
  ▼
EnrichmentBundle (dataclass)
  • YahooQuote, YahooFundamentals
  • WikipediaSummary
  • IndiaCompanySnapshot (or SECCompanySnapshot)
  • List[NewsItem]
  • List[ScrapedDoc] (search corpus)
  • List[RedditPost]
  • List[HNStory]
  • StockTwitsSnapshot
  • FxRate (USD/INR)
  • List[Finding] (from multi-agent)
  • ConflictReport
  • QualityScore
  • List[Citation]
  │
  ▼
synthesize_memo(bundle, config) → str (markdown)
  │
  ├──► Build system prompt (prompt_builder.py)
  │    → Includes finagent_system.txt
  │    → INR-first formatting instructions
  │    → Confidentiality and disclaimer
  │
  ├──► Format enrichment data as structured context
  │    → Numbers formatted in INR (crore/lakh) for IN companies
  │    → All citations tracked
  │
  ├──► Call OpenAI GPT-4o
  │    → 8-section memo template
  │    → Include conflict warnings
  │    → Include confidence score with rationale
  │    → Include data freshness timestamps
  │
  └──► Return formatted markdown memo
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
| `contracts.py` | `OutputMode` enum (quick/moderate/deep), `ResponseDepth` enum |
| `intent_classifier.py` | Classifies query complexity → ResponseDepth |
| `memo_formatter.py` | Converts raw memo to display-ready format |
| `renderer.py` | Markdown/JSON rendering engine |
| `artifact_builder.py` | Builds structured answer artifacts for the frontend |
| `chart_generator.py` | Matplotlib chart image generation |
| `confidence_scorer.py` | 0-100 confidence with source weighting |
| `conflict_reporter.py` | Cross-source conflict detection and reporting |
| `report_exporter.py` | Export to PDF/HTML |
| `templates.py` | Output templates for different response modes |

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
# tools/data/__init__.py — re-exports
# tools/data/yahoo_finance.py
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

- **Per-session query cache** (`tools/data/cache.py`): In-memory LRU cache for the duration of a research session
- **News cache** (`news/cache.py`): SQLite-backed cache with configurable TTL
- **News deduplication** (`news/dedupe.py`): Cosine similarity + title matching

---

## Frontend Architecture

### Directory Structure

```
Frontend/app/src/
├── main.tsx                    # React entry, AuthProvider wrapper
├── App.tsx                     # Route definitions, protected routes
├── index.css                   # Global styles (1894 lines)
├── api/
│   └── client.ts               # Full API client (all endpoints)
├── context/
│   └── AuthContext.tsx          # Auth state, Google OAuth
├── data/
│   └── indianStocks.ts         # Reference data for search
├── pages/
│   ├── Dashboard.tsx           # Main workspace (2233 lines)
│   ├── Login.tsx               # Auth pages
│   └── Onboarding.tsx          # Portfolio onboarding
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
    │   └── SuggestedPrompts.tsx # Prompt suggestions
    ├── charts/
    │   ├── AreaChart.tsx       # Chart.js area chart
    │   ├── BarChart.tsx        # Chart.js bar chart
    │   ├── DonutChart.tsx      # Chart.js donut
    │   ├── InteractiveChart.tsx # Interactive time-series
    │   ├── MetricCard.tsx      # Single metric display
    │   └── ThemeProvider.ts    # Chart.js theming
    └── dashboard/
        ├── IndexTickerCard.tsx  # Nifty/Sensex ticker
        ├── PortfolioTable.tsx   # Holdings table
        ├── QuickActions.tsx     # Quick action buttons
        ├── QuickPulse.tsx       # Market pulse overview
        ├── RecentInsights.tsx   # Recent research list
        ├── Sparkline.tsx        # Mini chart
        └── WatchlistCard.tsx    # User watchlist
```

### Route Configuration (`App.tsx`)

```
HashRouter:
  / → Redirect to /dashboard (if authenticated) or /login
  /login → Login page (email + Google OAuth)
  /signup → Login page (signup tab)
  /onboarding → Portfolio onboarding (protected)
  /dashboard → Main workspace (protected)
  * → Redirect to /
```

Protected routes check for authentication and redirect to login if missing.

### Auth State (`context/AuthContext.tsx`)

```typescript
interface AuthContextType {
  token: string | null;
  user: User | null;
  isAuthenticated: boolean;
  login: (email, password) => Promise<void>;
  signup: (email, password) => Promise<void>;
  loginWithGoogle: (credential) => Promise<void>;
  logout: () => void;
  // ...
}
```

- Token stored in localStorage
- Google OAuth via Google Identity Services (GIS) CDN
- Automatically validates token on app load

### API Client (`api/client.ts`)

Key features:
- Dynamic backend URL resolution (runtime config, env var, or Vite proxy)
- Bearer token injection on every request
- Full coverage: auth, portfolio, research, memory, chat endpoints
- SSE streaming with `streamSession(sessionId)`:
  - Uses `EventSource` API
  - 25-second proactive reconnect (works with AWS API Gateway 30s limit)
  - Parses JSON event data, calls `onEvent` callback per event type

### Dashboard (`pages/Dashboard.tsx`, 2233 lines)

The dashboard is organized into sections:
1. **Portfolio Overview** — Holdings table, allocation donut, top movers, alerts
2. **Market Pulse** — Ticker cards, watchlist with sparklines, sector heatmap
3. **Research Chat** — Chat input, message history, agent thinking panel, rich responses
4. **Recent Insights** — Saved memos and research sessions
5. **Quick Actions** — Pre-built research prompts

State management is entirely React `useState`/`useRef` with no external library.

---

## Gateway & API Endpoints

**File:** `finagent/gateway/run.py` (2261 lines)

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

#### Research

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/research/start` | Yes | Standard research (auto-depth) |
| POST | `/research/deep` | Yes | 8-pass deep research |
| POST | `/chat/research` | Yes | Chat-friendly research entry |
| POST | `/sessions/{id}/stop` | Yes | Cancel running session |
| DELETE | `/sessions/{id}` | Yes | Delete session artifacts |
| GET | `/sessions/{id}/status` | Yes | Session status |
| GET | `/sessions/{id}/events` | Yes | Poll events (JSON array) |
| GET | `/sessions/{id}/stream` | Yes | SSE event stream |
| GET | `/sessions/{id}/result` | Yes | Final result + memo |
| GET | `/sessions/{id}/memo` | Yes | Memo markdown |
| GET | `/chat/history` | Yes | Chat history |

#### Portfolio

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/portfolio/mirror` | Yes | Get holdings |
| POST | `/portfolio/mirror` | Yes | Replace holdings |
| DELETE | `/portfolio/mirror` | Yes | Clear holdings |
| POST | `/api/portfolio/upload-cas` | Yes | Upload eCAS/PDF/CSV/XLSX |
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

#### Memory & Discovery

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/memory/stats` | Yes | Memory statistics |
| GET | `/memory/facts` | Yes | Browse facts |
| GET | `/memory/sessions` | Yes | Session summaries |
| DELETE | `/memory/clear/{target}` | Yes | Clear target facts |
| GET | `/memos` | Yes | List saved memos |

#### System

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

## Deployment

### Docker

```dockerfile
FROM python:3.11-slim
# Install system deps (chromium, Playwright deps)
# Install Python deps from requirements-finagent.txt
# Copy finagent/ source
# Expose 8080
# Run: uvicorn finagent.gateway.run:app --host 0.0.0.0 --port 8080
```

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

#### GitHub Actions (`.github/workflows/deploy-production.yml`)
- Trigger: push to `production` or `main`
- Build Docker image
- Push to ECR
- Update ECS task definition
- Force new deployment on ECS service
- Health check (curl `/health`)
- Trigger Amplify deploy
- Slack notification

#### AWS CodeBuild (`buildspec.yml`, `buildspec-prod.yml`)
- Alternative/deployment build path
- Docker build + push to ECR
- ECS task definition update
- Service deployment

### Environment Variables

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | OpenAI API key for GPT-4o |
| `FINAGENT_HOME` | Override data directory (default: `.finagent/`) |
| `CORS_ORIGINS` | Allowed CORS origins (comma-separated) |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase admin/service key |
| `JWT_SECRET` | JWT signing secret |
| `MCP_NSE_URL` | NSE MCP server URL |
| `MCP_FUNDAMENTALS_URL` | Fundamentals MCP server URL |
| `MCP_RESEARCH_URL` | Research MCP server URL |
| `MCP_DOCS_URL` | Docs MCP server URL |
| `MCP_VALUATION_URL` | Valuation MCP server URL |
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
│  LLMQueryContextualizer                                    │
│    ├── ChatHistory (context for follow-up detection)       │
│    ├── Intent Classification (moderate complexity)        │
│    ├── Entity Extraction → "TCS"                           │
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
│  │ 1. ENTITY RESOLUTION                                │   │
│  │    resolve_entity("TCS") →                           │   │
│  │      ticker: "TCS.NS"                               │   │
│  │      name: "Tata Consultancy Services"              │   │
│  │      geo: "IN"  sector: "IT"                        │   │
│  │      preferred_domains: [screener.in, ...]          │   │
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
│  │    ↓ EnrichmentBundle (YahooQuote, News[], ...)     │   │
│  └────────────────────────────────────────────────────┘   │
│                              │                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │ 3. BREADTH SEARCH                                    │   │
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
│  │ 5. MULTI-AGENT ORCHESTRATION                        │   │
│  │    Wave 0 (parallel): Financials + Risk + News       │   │
│  │    Wave 1 (parallel): Technical + Community           │   │
│  │    Wave 2 (parallel): Competitor + Valuation          │   │
│  │    Wave 3: Accounting                                │   │
│  │    Wave 4: Macro                                     │   │
│  │    Wave 5: Governance                                │   │
│  │    → 10 Finding objects                              │   │
│  └────────────────────────────────────────────────────┘   │
│                              │                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │ 6. ANALYSIS                                          │   │
│  │    detect_conflicts(findings) → 2 conflicts found   │   │
│  │    score_research(data, findings) → 82/100 quality  │   │
│  │    validate_accuracy(claims) → 85% verified          │   │
│  │    Quality ≥ 75 → skip reflection                    │   │
│  └────────────────────────────────────────────────────┘   │
│                              │                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │ 7. SYNTHESIS                                         │   │
│  │    synthesize_memo(bundle) → 8-section markdown      │   │
│  │    • Executive Summary                               │   │
│  │    • Business Overview                               │   │
│  │    • Financial Analysis (INR crore)                   │   │
│  │    • Valuation (DCF: ₹3,842 PE: ₹3,950 EV/EBITDA)   │   │
│  │    • Risks & Red Flags                               │   │
│  │    • Market Sentiment                                │   │
│  │    • Competitive Landscape                           │   │
│  │    • Verdict: Buy with 15% margin of safety          │   │
│  └────────────────────────────────────────────────────┘   │
│                              │                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │ 8. PERSISTENCE                                       │   │
│  │    store_facts() → SQLite (financial, valuation...)  │   │
│  │    save_memo() → .finagent/memos/tcs_valuation.md   │   │
│  │    save_session_events() → JSONL                     │   │
│  │    maybe_promote_playbook() → playbooks.sqlite3      │   │
│  └────────────────────────────────────────────────────┘   │
│                                                            │
│  Event Bus: BUS.emit() at every step                       │
│  → phase_change, step_start, agent_start, source, done     │
└──────────────────────────┬───────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│ FRONTEND: Dashboard.tsx                                   │
│                                                            │
│  SSE stream receives events in order:                      │
│    phase_change: "enriching"                               │
│    step_start: "Fetching Yahoo Finance quote..."           │
│    step_end: "Yahoo Finance complete"                      │
│    ...                                                     │
│    agent_start: "Valuation Analysis"                       │
│    agent_end: "Valuation complete"                         │
│    source: "screener.in"                                   │
│    ...                                                     │
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

### Backend Python Files (`finagent/`)

#### Core (root)
| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | ~20 | Package init, environment loading, CA cert fix |
| `__main__.py` | ~10 | `python -m finagent` entry point |
| `run_agent.py` | 2119 | Core agent loop pipeline |
| `api.py` | ~500 | Legacy standalone FastAPI (merged) |
| `cli.py` | ~150 | CLI: preflight, run-stub commands |
| `events.py` | ~200 | SessionBus — in-process event bus with JSONL persistence |
| `accuracy_validator.py` | ~150 | Claim validation and source confidence scoring |
| `intent.py` | ~100 | Intent classification utilities |
| `paths.py` | ~40 | Data directory path resolution |
| `prompt_builder.py` | ~80 | System prompt loader |
| `research_planner.py` | ~120 | ResearchPlan, PlanStep Pydantic models |
| `rich_builder.py` | ~300 | Rich response builder for teammate |
| `runtime_provider.py` | ~80 | LLM provider resolution (OpenAI/xAI) |
| `settings.py` | ~100 | Environment-driven FinAgentSettings |
| `synthesis.py` | 2081 | LLM memo synthesis engine |
| `portfolio_mirrors.py` | ~200 | Position mirror CRUD (SQLite) |
| `portfolio_sentinel.py` | ~100 | Portfolio monitoring |

#### Agent
| File | Purpose |
|------|---------|
| `agent/reflection.py` | Reflection loop for iterative self-improvement |

#### Agents (Multi-Agent System)
| File | Purpose |
|------|---------|
| `agents/__init__.py` | Re-exports: Orchestrator, Verifier, detect_blind_spots |
| `agents/base.py` | BaseSubAgent ABC, SubAgentContext, Finding, AgentTaskResult |
| `agents/blindspot.py` | Auto-generate follow-up questions for uncovered areas |
| `agents/orchestrator.py` | Wave-based parallel agent execution engine |
| `agents/verifier.py` | Cross-agent claim verification and confidence adjustment |
| `agents/specialists/__init__.py` | `default_roster()` factory (10 agents) |
| `agents/specialists/accounting.py` | Forensic accounting anomaly detection |
| `agents/specialists/community.py` | Reddit/StockTwits/HN sentiment analysis |
| `agents/specialists/competitor.py` | Peer comparison and competitive analysis |
| `agents/specialists/financials.py` | Financial statement analysis |
| `agents/specialists/governance.py` | Corporate governance review |
| `agents/specialists/macro.py` | Macro-economic overlay |
| `agents/specialists/news.py` | News sentiment and material events |
| `agents/specialists/risk.py` | Risk factor identification |
| `agents/specialists/technical.py` | Technical price analysis |
| `agents/specialists/valuation.py` | Valuation framework analysis |

#### Analysis
| File | Purpose |
|------|---------|
| `analysis/conflicts.py` | Cross-source conflict detection |
| `analysis/quality.py` | Research quality scoring (0-100) |

#### Gateway (Web Server)
| File | Lines | Purpose |
|------|-------|---------|
| `gateway/__init__.py` | ~5 | Package init |
| `gateway/run.py` | 2261 | Main FastAPI gateway: all REST + SSE endpoints |
| `gateway/auth_guard.py` | ~80 | JWT validation (local + Supabase) |
| `gateway/session.py` | ~50 | SessionRecord dataclass |
| `gateway/supabase_client.py` | ~150 | Supabase Admin API client |
| `gateway/server.cjs` | ~20 | CommonJS server entry point |

#### Geography & Entity Resolution
| File | Purpose |
|------|---------|
| `geo/__init__.py` | Re-exports: resolve_entity, Entity |
| `geo/entity_resolver.py` | Main entity resolution pipeline |
| `geo/ticker_mapper.py` | Symbol-to-ticker lookup database |
| `geo/currency_policy.py` | Currency formatting policies |
| `geo/jurisdiction_profiles.py` | Country-specific data source configs |
| `geo/query_localizer.py` | Search query adaptation per geography |
| `geo/source_policy.py` | Preferred web domains per entity type |

#### Harness (Long-Running Agent)
| File | Purpose |
|------|---------|
| `harness/__init__.py` | Re-exports: Harness, HarnessConfig |
| `harness/context_manager.py` | Context compression strategies |
| `harness/error_recovery.py` | Error recovery and retry logic |
| `harness/footprint_enforcer.py` | Token/memory/resource limit enforcement |
| `harness/human_gates.py` | Human-in-the-loop approval checkpoints |
| `harness/interrupt_handler.py` | SIGINT/SIGTERM graceful shutdown |
| `harness/orchestrator.py` | Harness-level orchestration |
| `harness/preflight.py` | Pre-flight clarification prompt generation |

#### Ingestion (Portfolio Documents)
| File | Purpose |
|------|---------|
| `ingestion/__init__.py` | Re-exports |
| `ingestion/cas_adapter.py` | CAMS/KFintech eCAS statement parser |
| `ingestion/image_ingestion.py` | Screenshot OCR portfolio extraction |
| `ingestion/isin_resolver.py` | ISIN → ticker resolution |
| `ingestion/markdown_extractor.py` | Markdown table extraction |
| `ingestion/mineru_transformer.py` | MinerU PDF transformer |
| `ingestion/pdf_transformer.py` | Generic PDF text/table extraction |
| `ingestion/portfolio_document.py` | Unified parser (PDF/CSV/XLSX/CAS) |
| `ingestion/portfolio_schema.py` | Pydantic models for extracted holdings |

#### Memory
| File | Purpose |
|------|---------|
| `memory/__init__.py` | Re-exports: MemoryFact, get_memory_store |
| `memory/chat_memory.py` | Chat history SQLite persistence |
| `memory/store.py` | Memory fact store with per-user scoping |

#### News
| File | Purpose |
|------|---------|
| `news/__init__.py` | Re-exports |
| `news/cache.py` | News caching with TTL |
| `news/dedupe.py` | News article deduplication |
| `news/scorer.py` | News relevance scoring |
| `news/sources/amfi_source.py` | AMFI India mutual fund data |
| `news/sources/bse_announcements.py` | BSE corporate announcements |
| `news/sources/nse_announcements.py` | NSE corporate announcements |
| `news/sources/rss_aggregator.py` | Generic RSS feed aggregation |
| `news/sources/searxng_source.py` | SearXNG meta-search news |
| `news/sources/sebi_rss.py` | SEBI regulatory RSS feed |

#### Output
| File | Purpose |
|------|---------|
| `output/__init__.py` | Re-exports |
| `output/contracts.py` | OutputMode, ResponseDepth enums |
| `output/intent_classifier.py` | Query complexity → OutputMode classifier |
| `output/memo_formatter.py` | Memo markdown formatting |
| `output/renderer.py` | Markdown/JSON rendering |
| `output/artifact_builder.py` | Structured answer artifact construction |
| `output/chart_generator.py` | Matplotlib chart image generation |
| `output/confidence_scorer.py` | 0-100 confidence with source weighting |
| `output/conflict_reporter.py` | Cross-source conflict reporting |
| `output/report_exporter.py` | PDF/HTML report export |
| `output/templates.py` | Output templates per response mode |

#### Playbooks
| File | Purpose |
|------|---------|
| `playbooks/executor.py` | Playbook execution engine |
| `playbooks/promoter.py` | Playbook promotion logic (reuse detection) |
| `playbooks/retriever.py` | Playbook retrieval by keyword/similarity |
| `playbooks/schema.py` | Playbook data model |
| `playbooks/store.py` | Playbook SQLite persistence |

#### Portfolio
| File | Purpose |
|------|---------|
| `portfolio/__init__.py` | Re-exports |
| `portfolio/action_queue.py` | Daily action queue builder |
| `portfolio/alerts.py` | Price/MA/event alert computation |
| `portfolio/analytics.py` | Core portfolio analytics (P&L, XIRR, allocation) |
| `portfolio/corporate_actions.py` | Bonus/split/dividend corporate actions |
| `portfolio/dividends.py` | Dividend history and upcoming calendar |
| `portfolio/holding_detail.py` | Per-holding deep analysis |
| `portfolio/mf_analytics.py` | Mutual fund scheme analytics |
| `portfolio/news.py` | Portfolio-level news aggregation |
| `portfolio/sectors.py` | Sector allocation and breakdown |
| `portfolio/stress_test.py` | Scenario-based stress testing |
| `portfolio/tax.py` | STCG/LTCG tax computation |

#### Retrieval
| File | Purpose |
|------|---------|
| `retrieval/__init__.py` | Re-exports |
| `retrieval/dense_index.py` | Dense vector (embedding) index |
| `retrieval/fusion.py` | Hybrid result fusion (dense + sparse) |
| `retrieval/graph_index.py` | Graph-based document indexing |
| `retrieval/planner.py` | Retrieval plan builder |
| `retrieval/reranker.py` | Result reranking |
| `retrieval/sparse_index.py` | Sparse keyword (BM25) index |

#### Router
| File | Purpose |
|------|---------|
| `router/__init__.py` | Re-exports |
| `router/domain_taxonomy.py` | Agent-to-keyword taxonomy mapping |
| `router/geography_router.py` | Geography-based routing decisions |
| `router/intent_router.py` | Intent classification and agent routing |
| `router/policies.py` | Deep research policy definitions |
| `router/tool_selector.py` | Tool selection by intent/entity |

#### State
| File | Purpose |
|------|---------|
| `state/__init__.py` | Re-exports |
| `state/checkpoint.py` | Checkpoint, StepResult data models |
| `state/citation_log.py` | Citation tracking and source linking |
| `state/compression.py` | Context compression utilities |
| `state/research_state.py` | Research state store (SQLite) |
| `state/session_context.py` | Thread-local session context (contextvars) |

#### Storage
| File | Purpose |
|------|---------|
| `storage/__init__.py` | Re-exports |
| `storage/sqlite.py` | SQLite WAL connection helper |

#### Tools — Data
| File | Purpose |
|------|---------|
| `tools/data/__init__.py` | All data fetcher re-exports |
| `tools/data/cache.py` | Per-session in-memory query cache |
| `tools/data/forex.py` | USD/INR forex rate fetcher |
| `tools/data/hackernews.py` | HN Algolia search API |
| `tools/data/india.py` | NSE/Screener.in/Moneycontrol/SEBI fetchers |
| `tools/data/news_feed.py` | Google News RSS fetcher |
| `tools/data/reddit.py` | Reddit search (Pushshift/API) |
| `tools/data/sec_edgar.py` | SEC EDGAR company facts API |
| `tools/data/sec_filings.py` | SEC filing narratives |
| `tools/data/stocktwits.py` | StockTwits sentiment API |
| `tools/data/units.py` | Indian number formatting (crore/lakh) |
| `tools/data/wikipedia.py` | Wikipedia REST summary API |
| `tools/data/yahoo_finance.py` | yfinance quote + fundamentals |

#### Tools — Web
| File | Purpose |
|------|---------|
| `tools/web/crawl4ai_sites.py` | Crawl4AI full-page scraper |
| `tools/web/http_fetcher.py` | Shared async httpx client |
| `tools/web/scraper.py` | DuckDuckGo search + HTML scrape |
| `tools/web/searxng_client.py` | SearXNG meta-search client |
| `tools/web/table_parser.py` | HTML table extraction |

#### Tools — Other
| File | Purpose |
|------|---------|
| `tools/__init__.py` | Re-exports |
| `tools/registry.py` | Tool registry |
| `tools/mcp_config.py` | MCP server connection configuration |
| `tools/valuation_engine.py` | Deterministic finance math (994 lines) |
| `tools/browser/deep_crawler.py` | Playwright deep domain crawler |
| `tools/mcp/dynamic_loader.py` | Dynamic MCP tool loading |
| `tools/social/viral_verifier.py` | Pump-and-dump signal detection |
| `tools/prospektlab/enricher.py` | Entity enrichment |
| `tools/prospektlab/entity_fetcher.py` | Entity data fetching |
| `tools/prospektlab/event_monitor.py` | Event monitoring |
| `tools/prospektlab/exporter.py` | Data export |
| `tools/prospektlab/navigator.py` | Data navigation |

### Frontend TypeScript Files (`Frontend/app/src/`)

| File | Lines | Purpose |
|------|-------|---------|
| `main.tsx` | ~20 | React entry point, AuthProvider |
| `App.tsx` | ~100 | Route definitions, auth guards |
| `index.css` | 1894 | Global design system (dark theme) |
| `api/client.ts` | ~400 | Full API client + SSE streaming |
| `context/AuthContext.tsx` | ~250 | Auth state + Google OAuth |
| `data/indianStocks.ts` | ~200 | Indian stock reference data |
| `pages/Dashboard.tsx` | 2233 | Main workspace |
| `pages/Login.tsx` | ~400 | Authentication pages |
| `pages/Onboarding.tsx` | ~300 | Portfolio onboarding |
| `components/layout/AppShell.tsx` | ~80 | Main layout |
| `components/layout/Logo.tsx` | ~30 | Logo |
| `components/layout/Sidebar.tsx` | ~150 | Navigation |
| `components/chat/AgentThinking.tsx` | ~200 | Agent progress |
| `components/chat/ChatInput.tsx` | ~150 | Chat input |
| `components/chat/MessageBubble.tsx` | ~150 | Message rendering |
| `components/chat/RichResponse.tsx` | ~200 | Rich data display |
| `components/chat/SuggestedPrompts.tsx` | ~50 | Prompts |
| `components/charts/AreaChart.tsx` | ~60 | Chart.js area |
| `components/charts/BarChart.tsx` | ~60 | Chart.js bar |
| `components/charts/DonutChart.tsx` | ~60 | Chart.js donut |
| `components/charts/InteractiveChart.tsx` | ~100 | Interactive chart |
| `components/charts/MetricCard.tsx` | ~40 | Metric card |
| `components/charts/ThemeProvider.ts` | ~40 | Chart theme |
| `components/dashboard/IndexTickerCard.tsx` | ~80 | Index ticker |
| `components/dashboard/PortfolioTable.tsx` | ~200 | Holdings table |
| `components/dashboard/QuickActions.tsx` | ~40 | Quick actions |
| `components/dashboard/QuickPulse.tsx` | ~80 | Market pulse |
| `components/dashboard/RecentInsights.tsx` | ~80 | Insights list |
| `components/dashboard/Sparkline.tsx` | ~60 | Sparkline |
| `components/dashboard/WatchlistCard.tsx` | ~100 | Watchlist |

---

## Architectural Principles

1. **LLM for reasoning only** — All math, data fetching, and formatting happen in deterministic Python. The LLM synthesizes, interprets, and writes — never calculates.

2. **India-first, US-second** — Defaults to IN geography, `.NS` exchange suffix, NSE/Screener.in data, SEBI filings, INR formatting (crore/lakh). US is fully supported but secondary.

3. **Parallelism everywhere** — Enrichment, multi-agent waves, deep research passes, and data fetches all run concurrently via `asyncio.gather()`.

4. **Deterministic finance math** — `valuation_engine.py` (994 lines) handles all calculations with Pydantic-validated inputs and transparent intermediate steps.

5. **Event-driven SSE** — The `SessionBus` decouples the agent loop from the HTTP gateway. Events are buffered, persisted to JSONL, and replayable.

6. **Multi-agent Hermes pattern** — 10 specialist sub-agents run in dependency-aware waves, each returning structured findings. An orchestrator merges, a verifier cross-checks, and a blind-spot detector fills gaps.

7. **Contextualized queries** — `LLMQueryContextualizer` handles follow-up detection, entity extraction, complexity classification, and portfolio scope detection before the agent loop starts.

8. **Durable memory** — Facts persist across sessions per user, enabling long-term learning about companies, sectors, and events.

9. **Portfolio-aware research** — The system understands the user's actual holdings and can scope research to portfolio context.

10. **Structured output** — All outputs follow a consistent 8-section memo template with citations, confidence scores, conflict reports, and geography-appropriate formatting.

---

*Document generated from full codebase analysis. Last updated: May 2026.*

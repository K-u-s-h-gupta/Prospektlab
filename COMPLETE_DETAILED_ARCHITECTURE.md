# ProspektLab / ORACLE FIOS / FinAgent — Complete Detailed Architecture

> **Version:** 2.0.0  
> **Date:** May 2026  
> **Classification:** Financial Intelligence Operating System for the Indian Stock Market  
> **Status:** Production-Ready

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [Technology Stack](#3-technology-stack)
4. [Directory Structure & File Inventory](#4-directory-structure--file-inventory)
5. [Core Components Deep-Dive](#5-core-components-deep-dive)
6. [FinAgent 8-Phase Research Pipeline](#6-finagent-8-phase-research-pipeline)
7. [Specialist Multi-Agent System](#7-specialist-multi-agent-system)
8. [Data Flow & Integration](#8-data-flow--integration)
9. [State, Memory & Persistence](#9-state-memory--persistence)
10. [MCP Server Architecture](#10-mcp-server-architecture)
11. [Gateway API Specification](#11-gateway-api-specification)
12. [Frontend Architecture](#12-frontend-architecture)
13. [Research Quality & Accuracy](#13-research-quality--accuracy)
14. [Web Scraping & Search Infrastructure](#14-web-scraping--search-infrastructure)
15. [Synthesis & Output Generation](#15-synthesis--output-generation)
16. [Security & Authentication](#16-security--authentication)
17. [Deployment & Infrastructure](#17-deployment--infrastructure)
18. [Testing & Quality Assurance](#18-testing--quality-assurance)
19. [Environment Configuration](#19-environment-configuration)
20. [Roadmap & Future Phases](#20-roadmap--future-phases)

---

## 1. Executive Summary

**ProspektLab** (branded as **ORACLE FIOS** and **FinAgent**) is a production-grade, conversational AI-powered financial intelligence operating system focused on the **Indian stock market** (NSE/BSE). It provides investment-grade research memos by combining live market data, autonomous web research, deterministic financial modeling, and multi-agent AI synthesis.

### Core Principles
- **Live Data First:** Every numeric claim is sourced from live market data (NSE India, BSE, Yahoo Finance, SEBI filings) or reputable financial media. The system never invents figures.
- **Deterministic Math:** All valuation calculations (DCF, PE, Graham, EV/EBITDA, etc.) run through a 35,000+ line pure-Python engine. The LLM never performs arithmetic.
- **Multi-Agent Orchestration:** 10+ specialist financial analysts run in dependency-aware parallel waves, each focused on a specific domain (financials, risk, valuation, governance, macro, etc.).
- **Cited Output:** Every claim includes source attribution with URL badges.
- **Three Execution Modes:** Quick Chat (5-15s), Deep Research (2-5 min), and Marathon Mode (up to 4 hours).

### Example Queries
- *"What is TCS's PE ratio?"*
- *"Compare Infosys vs TCS on revenue growth and margins"*
- *"Deep analysis of Asian Paints with valuation and risks"*
- *"Show me IT sector trends and macro headwinds"*

---

## 2. System Architecture Overview

### High-Level Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           PRESENTATION LAYER                                │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐ │
│  │ Next.js Frontend│  │ Gateway HTML    │  │ Embeddable Widget           │ │
│  │ (React + TS)    │  │ Widgets         │  │ (widget.html)               │ │
│  │                 │  │ (landing, login,│  │                             │ │
│  │ • Chat UI       │  │  profile, etc.) │  │ • Standalone research panel │ │
│  │ • SSE streaming │  │                 │  │ • Real-time agent viz       │ │
│  │ • Charts        │  │ • No-build UI   │  │ • Source badges             │ │
│  │ • Agent process │  │ • Auth flows    │  │                             │ │
│  └────────┬────────┘  └────────┬────────┘  └──────────────┬──────────────┘ │
│           │                    │                         │                │
│           └────────────────────┼─────────────────────────┘                │
│                                │ HTTPS / SSE / REST                       │
└────────────────────────────────┼────────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────────────────┐
│                           APPLICATION LAYER                               │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ FastAPI Gateway (finagent/gateway/run.py) ~1,700 lines              │ │
│  │                                                                     │ │
│  │  • REST endpoints: /chat/research, /research/start, /research/deep  │ │
│  │  • SSE streaming: /sessions/{id}/stream                             │ │
│  │  • Auth: JWT + Supabase + Google OAuth                              │ │
│  │  • Rate limiting: per-IP / per-token sliding window                 │ │
│  │  • Static HTML: landing, login, signup, profile, settings, widget │ │
│  └──────────────────────────────┬──────────────────────────────────────┘ │
│                                 │                                         │
└─────────────────────────────────┼─────────────────────────────────────────┘
                                  │
┌─────────────────────────────────▼─────────────────────────────────────────┐
│                         ORCHESTRATION LAYER                              │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ FinAgent Research Engine (finagent/run_agent.py) ~2,000 lines       │ │
│  │                                                                     │ │
│  │  • 8-phase autonomous research pipeline                             │ │
│  │  • Intent classification & query routing                          │ │
│  │  • Multi-agent orchestrator (wave-based parallel execution)         │ │
│  │  • Reflection & quality loops                                       │ │
│  │  • Verification & blind-spot detection                              │ │
│  └──────────────────────────────┬──────────────────────────────────────┘ │
│           ┌─────────────────────┼─────────────────────┐                   │
│           │                     │                     │                   │
│  ┌────────▼────────┐  ┌─────────▼──────────┐  ┌─────▼──────┐           │
│  │ SPECIALIST      │  │ DATA & TOOLS       │  │ MEMORY &   │           │
│  │ AGENTS          │  │ LAYER              │  │ STATE      │           │
│  │                 │  │                    │  │            │           │
│  │ • Financials    │  │ • NSE India API    │  │ • SQLite   │           │
│  │ • Valuation     │  │ • Yahoo Finance    │  │   (WAL)    │           │
│  │ • Risk          │  │ • SEC EDGAR        │  │ • FTS5     │           │
│  │ • News          │  │ • SEBI Filings     │  │   Search   │           │
│  │ • Technical     │  │ • Web Search       │  │ • Check-   │           │
│  │ • Governance    │  │ • TimesFM Forecast │  │   pointing │           │
│  │ • Macro         │  │ • Qdrant Vector DB │  │ • Citation │           │
│  │ • Community     │  │ • Valuation Engine │  │   Logs     │           │
│  │ • Competitor    │  │ • Playwright Scrap │  │            │           │
│  │ • Accounting    │  │                    │  │            │           │
│  └─────────────────┘  └────────────────────┘  └────────────┘           │
└─────────────────────────────────────────────────────────────────────────┘
```

### Layer Summary

| Layer | Technology | Responsibility |
|-------|------------|--------------|
| **Presentation** | Next.js 14+ (App Router), React, TypeScript | Chat UI, real-time SSE streaming, SVG charts, agent process visualization, source badges |
| **API Gateway** | FastAPI + Uvicorn + AsyncIO | Chat/research endpoints, rate limiting, JWT auth, Supabase integration, static HTML widgets |
| **Orchestration** | Custom LangGraph-style orchestrator | 8-phase pipeline, wave-based parallel agent execution, query routing, reflection loops |
| **Agents** | Python async classes (10+ specialists) | Domain-specific financial analysis: financials, risk, valuation, governance, macro, etc. |
| **Data/Tools** | MCP servers + direct API clients | NSE, Yahoo, SEC, SEBI, web search, browser scraping, TimesFM forecasting |
| **Memory/State** | SQLite (WAL mode) + FTS5 | Session checkpoints, citation logs, long-term facts, chat history, event replay |
| **Time-Series** | Google TimesFM 2.5 200M | Zero-shot revenue forecasting, anomaly detection (P10-P90 corridors) |

---

## 3. Technology Stack

### Backend
| Component | Technology | Version/Notes |
|-----------|------------|---------------|
| Language | Python | >= 3.11 (production), >= 3.14 (pyproject.toml) |
| Web Framework | FastAPI | Async REST API with automatic OpenAPI docs |
| Server | Uvicorn | ASGI server with reload support for development |
| AI/LLM | OpenAI GPT-4o | Streaming synthesis, query contextualization |
| Time-Series | Google TimesFM 2.5 200M | Standalone microservice (FastAPI + FastMCP) |
| Web Scraping | Crawl4AI + Playwright | Chromium browser pool for JS-heavy pages |
| HTTP Client | httpx | Async with connection pooling, User-Agent rotation |
| Vector Search | Qdrant | Document retrieval pipeline (MCP :8004) |
| Search APIs | Tavily, DuckDuckGo, Bing, SearXNG | Tiered fallback chain |
| Auth | JWT + Supabase Auth | Local JWT validation + Supabase for production |
| Email | SMTP (optional) | Verification codes, password reset |

### Frontend
| Component | Technology | Notes |
|-----------|------------|-------|
| Framework | Next.js 14+ | App Router, React Server Components |
| Language | TypeScript | Strict mode |
| Styling | Tailwind CSS (assumed) | Based on component structure |
| Charts | SVG (custom) | AreaChart, BarChart, DonutChart, GaugeChart, MultiSeries |
| Streaming | EventSource (SSE) | Real-time phase/agent/source updates |
| Build | AWS Amplify | CI/CD via `amplify-buildspec.yml` |

### Infrastructure
| Component | Technology | Notes |
|-----------|------------|-------|
| Container | Docker | Python 3.11-slim + Playwright deps |
| Registry | AWS ECR | Backend image storage |
| Compute | AWS ECS Fargate | Serverless container orchestration |
| Frontend CDN | AWS Amplify | Next.js static/site generation |
| DNS | Route53 | `api.prospektlab.com`, `app.prospektlab.com` |
| Load Balancer | AWS ALB | TLS termination, health checks |
| CI/CD | GitHub Actions + AWS CodeBuild | `buildspec.yml`, `buildspec-prod.yml` |
| Database | SQLite (serverless) | WAL mode, FTS5, no managed DB required |

---

## 4. Directory Structure & File Inventory

```
PROSPEKTLAB/
│
├── main.py                              # Minimal project entry stub
├── pyproject.toml                       # Python project metadata (requires >=3.14)
├── Dockerfile                           # Production backend container image
├── buildspec.yml                        # AWS CodeBuild spec (staging)
├── buildspec-prod.yml                   # AWS CodeBuild spec (production)
├── amplify-buildspec.yml                # AWS Amplify frontend build spec
├── deploy-production.sh                 # Production deployment script
├── README.md                            # Project README (currently empty)
│
├── finagent/                            # ← CORE RESEARCH ENGINE (~100K+ lines)
│   │
│   ├── run_agent.py                     # 8-phase autonomous research pipeline (~2K lines)
│   ├── api.py                           # API models & Pydantic schemas
│   ├── cli.py                           # Command-line interface for research jobs
│   ├── events.py                        # Real-time event bus (asyncio.Queue + JSONL)
│   ├── intent.py                        # Query intent classification
│   ├── synthesis.py                     # Memo generation & LLM streaming (~2K lines)
│   ├── rich_builder.py                  # Rich output formatting (~92K lines)
│   ├── accuracy_validator.py            # Claim-by-claim numeric validation
│   ├── prompt_builder.py                # LLM prompt construction utilities
│   ├── research_planner.py              # Research plan generation from query
│   ├── settings.py                      # Configuration & environment loading
│   ├── paths.py                         # File path utilities (FINAGENT_HOME)
│   │
│   ├── agent/
│   │   └── reflection.py                # Hermes-style reflection loop for self-improvement
│   │
│   ├── agents/
│   │   ├── base.py                      # BaseSubAgent abstract class & AgentTaskResult
│   │   ├── orchestrator.py              # Wave-based topological parallel execution
│   │   ├── verifier.py                  # Post-analysis fact-checking against multiple sources
│   │   ├── blindspot.py                 # Missing-angle detection & auto-follow-up queries
│   │   └── specialists/
│   │       ├── accounting.py            # Forensic anomaly detection (TimesFM z-scores)
│   │       ├── financials.py            # Revenue, margin, cash-flow trend analysis
│   │       ├── valuation.py             # DCF, relative PE, fair value with TimesFM forecasts
│   │       ├── competitor.py            # Peer benchmarking & market share analysis
│   │       ├── risk.py                  # Credit risk, operational risk, red-flag detection
│   │       ├── technical.py             # Price action, 52w position, MA20/MA50, volatility
│   │       ├── news.py                  # Event-driven sentiment & recent developments
│   │       ├── governance.py            # Board structure, insider dealings, ESG, SEBI disclosures
│   │       ├── macro.py                 # Sector tailwinds/headwinds, policy exposure
│   │       └── community.py             # Reddit/HN/StockTwits sentiment + pump-and-dump scoring
│   │
│   ├── analysis/
│   │   ├── quality.py                   # 10-dimension research quality heuristic (max 100 pts)
│   │   └── conflicts.py                 # Cross-source numeric conflict detection
│   │
│   ├── docs/
│   │   └── MARATHON_AND_BROWSER.md      # Internal documentation for marathon mode & browser pool
│   │
│   ├── gateway/
│   │   ├── run.py                       # FastAPI gateway (~1,700 lines): REST, SSE, auth, widgets
│   │   ├── email_service.py             # SMTP email notifications (verification, reset)
│   │   ├── supabase_client.py           # Supabase auth & database backend integration
│   │   ├── test_gateway.py              # API integration tests
│   │   ├── test_security.py             # Auth bypass & security tests
│   │   ├── landing.html                 # Marketing landing page
│   │   ├── login.html                   # User login flow
│   │   ├── signup.html                  # User registration flow
│   │   ├── profile.html                 # User dashboard
│   │   ├── settings.html                # Configuration UI
│   │   └── widget.html                  # Embeddable research widget (charts + real-time viz)
│   │
│   ├── geo/
│   │   ├── entity_resolver.py           # Ticker/company name → canonical identifier
│   │   ├── query_localizer.py           # Geography-aware query routing
│   │   ├── source_policy.py             # Domain tiering & preference rules
│   │   └── ticker_mapper.py             # NSE/BSE/Yahoo ticker cross-mapping
│   │
│   ├── harness/
│   │   ├── context_manager.py           # Token budget allocation & tracking
│   │   ├── preflight.py                 # Pre-execution validation checks
│   │   ├── error_recovery.py            # Graceful degradation & retry strategies
│   │   └── footprint_enforcer.py        # Resource limit enforcement (pages, fetches, time)
│   │
│   ├── memory/
│   │   ├── store.py                     # Long-term SQLite memory (FTS5 facts per company)
│   │   └── chat_memory.py               # Per-user persistent conversation history
│   │
│   ├── output/
│   │   ├── intent_classifier.py         # Output mode classification (table, chart, text)
│   │   ├── artifact_builder.py            # Constructs AnswerArtifact (charts, tables, cards)
│   │   ├── memo_formatter.py            # Memo section formatter (Executive, Financials, etc.)
│   │   ├── renderer.py                  # Markdown / JSON / Rich text rendering for widgets
│   │   ├── contracts.py                 # Output type definitions (dataclasses)
│   │   └── rich_builder.py              # (symlink/duplicate) Rich formatting helpers
│   │
│   ├── playbooks/
│   │   ├── schema.py                    # Playbook template schema
│   │   ├── store.py                     # Playbook persistence
│   │   └── executor.py                  # Pre-built research template execution
│   │
│   ├── prompts/
│   │   └── finagent_system.txt          # System prompt for LLM synthesis layer
│   │
│   ├── prospektlab_adapter/
│   │   └── plugin.py                    # Safe no-op plugin hook for host app integration
│   │
│   ├── retrieval/
│   │   ├── planner.py                   # Document retrieval orchestration planner
│   │   ├── fusion.py                    # Dense + sparse hybrid retrieval fusion
│   │   ├── dense_index.py               # Dense vector indexing (Qdrant)
│   │   ├── sparse_index.py              # Sparse keyword indexing
│   │   └── reranker.py                  # Cross-encoder / heuristic result reranking
│   │
│   ├── router/
│   │   ├── intent_router.py             # Query intent classification & complexity scoring
│   │   ├── domain_taxonomy.py           # Domain/category mapping for routing
│   │   ├── geography_router.py          # Geo-routing (IN, US, global)
│   │   └── tool_selector.py             # Agent & tool selection based on intent
│   │
│   ├── state/
│   │   ├── checkpoint.py                # Session serialization (JSON dataclass)
│   │   ├── research_state.py            # SQLite session store with FTS5 findings table
│   │   ├── session_context.py           # Runtime per-session state (async-safe)
│   │   ├── citation_log.py              # Source citation tracking per claim
│   │   └── compression.py               # Context compression for token budget management
│   │
│   ├── tools/
│   │   ├── data.py                      # Core data models (IndiaCompanySnapshot, YahooQuote, etc.)
│   │   ├── india.py                     # NSE India API client (BennyThadikaran library)
│   │   ├── yahoo_finance.py             # Yahoo Finance client (yfinance wrapper)
│   │   ├── sec_edgar.py                 # US SEC EDGAR API client (10-K, 10-Q, CIK resolution)
│   │   ├── sec_filings.py               # SEC filing narrative extraction
│   │   ├── valuation_engine.py          # Deterministic finance math (~35K lines)
│   │   ├── forex.py                     # USD/INR rate fetching
│   │   ├── table_parser.py              # HTML table extraction & normalization
│   │   ├── scraper.py                   # Web search orchestrator (~48K lines)
│   │   ├── hackernews.py                # Hacker News Algolia search
│   │   ├── reddit.py                    # Reddit (PRAW/httpx) search & sentiment
│   │   ├── stocktwits.py                # StockTwits retail sentiment
│   │   ├── wikipedia.py                 # Wikipedia REST API summaries
│   │   ├── forecasting.py               # TimesFM integration wrapper
│   │   ├── news_feed.py                 # Google News RSS parser
│   │   ├── viral_verifier.py            # Pump-and-dump / viral content scoring
│   │   │
│   │   ├── browser/                     # Playwright Chromium pool
│   │   │   └── (helpers)                # browser_extract(), screenshot_page(), page pool mgmt
│   │   │
│   │   ├── mcp/
│   │   │   ├── mcp_forecasting.py       # MCP wrapper for TimesFM forecasting
│   │   │   └── forecasting.py           # TimesFM zero-shot + anomaly detection logic
│   │   │
│   │   ├── mcp_servers/
│   │   │   ├── nse_server.py            # FastMCP: NSE Market Data (:8001)
│   │   │   ├── fundamentals_server.py   # FastMCP: Fundamentals (:8002)
│   │   │   ├── research_server.py       # FastMCP: Research & News (:8003)
│   │   │   ├── docs_server.py           # FastMCP: Documents & Qdrant (:8004)
│   │   │   └── mcp_valuation.py         # FastMCP: Valuation Engine (:8005)
│   │   │
│   │   └── web/
│   │       ├── http_fetcher.py          # Shared async httpx client with retries
│   │       ├── scraper.py               # Search backend abstraction (DDG, Bing, Tavily)
│   │       ├── test_ingestion.py        # Scraper regression tests
│   │       └── test_units.py            # Unit conversion tests
│   │
│   └── tests/                           # Pytest suite for agent logic & integration
│
├── Frontend/                            # Next.js React Frontend
│   └── app/
│       ├── _components/
│       │   └── Charts/
│       │       ├── AreaChart.tsx        # SVG stacked/area chart component
│       │       ├── BarChart.tsx         # SVG horizontal bar chart (locale: en-IN)
│       │       ├── DonutChart.tsx       # SVG donut/ring chart
│       │       ├── GaugeChart.tsx       # SVG radial gauge
│       │       ├── MultiSeriesBarChart.tsx   # Grouped comparison bars
│       │       └── MultiSeriesLineChart.tsx  # Multi-line time series
│       └── (Next.js App Router pages)   # page.tsx, layout.tsx, etc.
│
├── timesfm-service/                     # TimesFM Standalone Microservice
│   ├── main.py                          # FastAPI: /forecast, /anomaly endpoints
│   ├── mcp_server.py                    # FastMCP wrapper for MCP client integration
│   ├── Dockerfile                       # Bakes model weights into image (~300MB)
│   ├── deploy-azure.ps1                 # Azure Container Apps deployment
│   └── deploy-cloud-shell.sh            # Cloud shell deployment script
│
├── deployment/                          # AWS Deployment Helpers
│   ├── fargate-backend.yml              # ECS Fargate task definition
│   ├── deploy-backend.ps1             # PowerShell deployment script
│   ├── deploy_frontend.py               # Amplify frontend deployment helper
│   └── zip_backend.py                 # Backend packaging utility
│
└── (Architecture & Documentation)       # 20+ reference markdown files
    ├── ARCHITECTURE.md                  # Mermaid diagram high-level overview
    ├── COMPLETE_ARCHITECTURE.md         # Exhaustive architecture reference
    ├── QUICK_ARCHITECTURE_OVERVIEW.md   # TL;DR quick reference
    ├── FINAGENT_ARCHITECTURE_BLUEPRINT.md
    ├── ORACLE_FIOS_architecture.md
    ├── PRODUCTION_DEPLOYMENT_GUIDE.md
    ├── PRODUCTION_VERIFICATION_CHECKLIST.md
    └── ...
```

---

## 5. Core Components Deep-Dive

### 5.1 FastAPI Gateway (`finagent/gateway/run.py`)
The gateway is the single entry point for all client interactions. It handles ~1,700 lines of FastAPI routes, auth, SSE streaming, and static HTML serving.

**Key Design Decisions:**
- **Dual UI Strategy:** Serves both a Next.js frontend (via CORS) and standalone HTML widgets for zero-build deployments.
- **SSE Event Bus:** Each research session gets an `asyncio.Queue`. Events are serialized to JSONL for replay after disconnect.
- **Session Ownership:** All session endpoints enforce `verify_session_ownership()` via JWT email match.
- **Rate Limiting:** `InMemSlidingWindowRateLimiter` with per-IP and per-token windows.

**REST Endpoints:**

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/health` | GET | No | Liveness probe for ALB/ECS |
| `/capabilities` | GET | No | Feature discovery for orchestrators |
| `/api/chat` | POST | Optional | Quick synchronous chat response |
| `/research/start` | POST | Optional | Start standard research job (async) |
| `/research/deep` | POST | Optional | Start deep multi-pass research |
| `/chat/research` | POST | Optional | Cloud chat interface — returns poll/SSE/result URLs |
| `/sessions/{id}/status` | GET | Yes | Pollable status (phase, progress, agents) |
| `/sessions/{id}/events` | GET | Yes | Replayable event history (`?after=N`) |
| `/sessions/{id}/stream` | GET | Yes | **SSE** real-time event stream |
| `/sessions/{id}/result` | GET | Yes | Final memo markdown |
| `/sessions/{id}/memo` | GET | Yes | Raw memo markdown (alias) |
| `/auth/google` | POST | No | Google OAuth login/initiation |
| `/auth/signup` | POST | No | Email/password registration |
| `/auth/login` | POST | No | Email/password login |
| `/auth/forgot-password` | POST | No | Password reset code request |
| `/auth/reset-password` | POST | No | Password reset confirmation |
| `/memory/stats` | GET | Yes | Long-term memory statistics |
| `/memory/facts` | GET | Yes | Retrieved facts for a target |
| `/memory/sessions` | GET | Yes | User's research session history |

### 5.2 Event Bus (`finagent/events.py`)
The event bus bridges the async research pipeline with the HTTP/SSE layer.

**Architecture:**
- **In-Memory Bus:** `SessionBus` wraps `asyncio.Queue` per active session.
- **Durable Log:** Every event is appended to `FINAGENT_HOME/sessions/{session_id}/events.jsonl`.
- **Replay:** On SSE reconnect, the gateway replays missed events from the JSONL file before streaming new ones.
- **Event Types:** `phase`, `agent_task`, `subagent_started`, `subagent_done`, `source`, `intel`, `memo`, `deep_pass`, `heartbeat`, `error`, `final`.

### 5.3 Intent Router (`finagent/router/intent_router.py`)
Determines how a query should be handled before any research begins.

**Outputs:**
- **Mode:** `quick` (single agent), `standard` (8-phase), `deep` (multi-pass), `marathon` (up to 4h)
- **Entities:** Extracted company names / tickers
- **Intent:** `FUNDAMENTALS`, `COMPARISON`, `NEWS`, `VALUATION`, `RISK`, `TECHNICAL`, `GOVERNANCE`, `MACRO`, `COMMUNITY`
- **Complexity Score:** 1-10 (drives pass count in deep mode)
- **Depth:** `shallow`, `moderate`, `deep`

### 5.4 Research Planner (`finagent/research_planner.py`)
Generates a structured research plan from the intent router output.

**Plan Structure:**
```python
@dataclass
class ResearchPlan:
    objectives: List[str]          # What to discover
    agents_needed: List[str]       # Which specialist agents to invoke
    data_sources: List[str]        # Preferred APIs (NSE, Yahoo, SEC, etc.)
    search_queries: List[str]      # Pre-generated web search queries
    max_passes: int                # For deep/marathon mode
    expected_duration_sec: int     # Time budget hint
```

---

## 6. FinAgent 8-Phase Research Pipeline

**File:** `finagent/run_agent.py` (~2,000 lines)  
**Core Function:** `run_research_session()`

This is the heart of the system. Every research job (standard, deep, or marathon) flows through these 8 phases.

| Phase | Name | Purpose | Parallel? | Key Output |
|-------|------|---------|-----------|------------|
| **1** | **Identify** | Resolve user target to canonical identifier (NSE symbol, Yahoo ticker, CIK) | No | `resolved_entity` with `symbol`, `exchange`, `country` |
| **2** | **Enrichment** | Parallel fan-out to all primary data sources | **Yes** | `EnrichmentBundle` (Yahoo, NSE, SEC, SEBI, Wiki, FX, News) |
| **3** | **Breadth Survey** | Layered web search across 4 discovery angles (financials, news, governance, macro) | **Yes** | `BreadthFindings` with URLs, snippets, domain diversity score |
| **4** | **Deep Dive** | Iterative targeted queries to fill coverage gaps identified in Phase 3 | No | `DeepFindings` with detailed extracts |
| **5** | **Analysis** | Cross-source conflict detection + viral/pump-and-dump scoring + quality heuristic | No | `QualityScore` (0-100), `ConflictReport`, `ViralScore` |
| **6** | **Specialist Multi-Agent** | Run 10+ agents in dependency-aware waves (see Section 7) | **Yes** (wave-based) | `AgentFindings` (one per agent) |
| **7** | **Verification** | Fact-check claims against multiple sources; numeric sanity checks | No | `VerifiedClaims` with confidence adjustments |
| **8** | **Synthesis** | Generate final memo with executive summary, financials, valuation, risks, citations | No | `FinalMemo` (markdown + structured artifact) |

### Deep Research / Marathon Mode
For complex queries, the pipeline runs multiple times:

```
Pass 0: Core financials & identity
Pass 1: Competitive moat & peers
Pass 2: Management & governance
Pass 3: Valuation & fair value
Pass 4: Risk scan & red flags
Pass 5: Macro & sector context
Pass 6: Technical & price action
Pass 7: Community sentiment
Pass 8: News & events deep-dive
Pass 9: Accounting & forensic
Pass 10: Cross-validation synthesis
Pass 11: Final investment-grade memo (synthesis pass — runs SERIAL)
```

- **Passes 0 to N-2:** Run in **parallel** (each is an independent `run_research_session()`)
- **Pass N-1 (Synthesis):** Runs **serial** after all parallel passes complete. Integrates all findings into a single investment-grade memo.
- **Heartbeat:** SSE `heartbeat` event every 20 seconds during marathon mode to keep connection alive.
- **Time Budget:** `max_wall_seconds` (default 14,400 = 4 hours). Emits `phase=stopped` with `reason=time_budget` when reached.

---

## 7. Specialist Multi-Agent System

**Base Class:** `finagent/agents/base.py` — `BaseSubAgent`  
**Orchestrator:** `finagent/agents/orchestrator.py` — `Orchestrator`  
**Location:** `finagent/agents/specialists/`

### 7.1 Agent Base Architecture

Every specialist inherits from `BaseSubAgent`:

```python
@dataclass
class BaseSubAgent:
    name: str                # Machine ID (e.g., "valuation")
    display: str             # Human label (e.g., "Valuation & DCF")
    priority: int            # Lower = earlier in wave
    dependencies: Tuple[str] # Agents that must complete first
    
    async def precondition(ctx: SessionContext) -> Tuple[bool, str]:
        # Returns (should_run, reason_if_skipped)
        
    async def execute(ctx: SessionContext) -> AgentTaskResult:
        # Returns findings, claims, evidence, confidence
```

### 7.2 Agent Roster

| Agent | Priority | Dependencies | Key Technique | File |
|-------|----------|--------------|---------------|------|
| **financials** | 10 | — | Revenue/margin/CAGR trend analysis from Yahoo/SEC/NSE | `financials.py` |
| **news** | 20 | — | Google News RSS + targeted search, topic bucketing | `news.py` |
| **risk** | 20 | — | Item 1A digest, litigation/regulatory pattern scan | `risk.py` |
| **technical** | 30 | — | 52-week position, MA20/MA50, volatility, max drawdown | `technical.py` |
| **community** | 30 | — | Reddit/HN/StockTwits sentiment + pump-and-dump scoring | `community.py` |
| **competitor** | 40 | — | Peer discovery via web search, named-entity extraction | `competitor.py` |
| **valuation** | 40 | `financials` | TimesFM zero-shot revenue forecasts → DCF terminal growth | `valuation.py` |
| **accounting** | 45 | `financials` | TimesFM anomaly detection (P10-P90 corridors) or ±2σ z-score | `accounting.py` |
| **macro** | 50 | — | Sector tailwinds/headwinds, RBI/policy exposure | `macro.py` |
| **governance** | 60 | — | Promoter transactions, board changes, SEBI disclosures | `governance.py` |

### 7.3 Orchestrator Logic

1. **Wave 0:** All agents with `dependencies=[]` fire concurrently via `asyncio.gather()`
2. **Wave N:** Agents whose dependencies are all satisfied by prior waves
3. **Timeout:** Each agent has its own `deadline_ms` so one slow agent doesn't block the wave
4. **Cycle Detection:** If a dependency cycle is detected, remaining agents are released into one defensive wave
5. **Preconditions:** Agents can self-skip if required data is missing (e.g., `valuation` skips if no financials)

### 7.4 Verifier (`finagent/agents/verifier.py`)

Runs **after** all specialist waves complete:

1. **Tier-1 Enforcement:** HIGH-confidence findings must have SEC/regulator evidence
2. **Cross-Source Corroboration:** Same claim in multiple agents → confidence boost
3. **Numeric Sanity:** `detect_conflicts()` flags unit mismatches or stale data
4. **AccuracyValidator:** Passthrough validation on up to 60 claims per session
5. **Claim Structure:**
   ```python
   @dataclass
   class Claim:
       text: str           # "TCS revenue ₹200k Cr"
       source: str         # URL or document
       confidence: float   # 0.0-1.0
       timestamp: datetime
   ```

### 7.5 Blind Spot Detector (`finagent/agents/blindspot.py`)

Post-analysis gap finder:
- Detects missing angles (e.g., no customer concentration data, no FX exposure, no insider activity)
- Auto-dispatches follow-up queries if `enable_blindspot=True`
- Emits `blindspot_detected` events to SSE stream

---

## 8. Data Flow & Integration

### 8.1 Standard Query Flow (e.g., "What is Reliance's PE?")

```
User → Next.js Frontend
  → POST /chat/research
    { "message": "What is Reliance's PE?", "mode": "quick" }

  → Gateway: Intent classifier
    → entities: ["Reliance"]
    → intent: FUNDAMENTALS
    → mode: quick
    → complexity: 2

  → Orchestrator: Route to Fundamentals agent
    → No need for full 8-phase pipeline

  → MCP Fundamentals Service (:8002)
    → yfinance.fetch("RELIANCE.NS")
    → Returns: PE = 42.5x, EPS = 123.4, Market Cap = 15.2T INR

  → LLM Synthesis (OpenAI stream)
    → "Reliance Industries Ltd (RELIANCE.NS) trades at a PE ratio of 42.5x..."
    → Source badges: [Yahoo Finance, NSE India]

  → SSE stream events:
    phase: "identify" → "enrichment" → "synthesis"
    source: "Yahoo Finance"
    source: "NSE India"
    final: { memo: "...", citations: [...] }

  → Frontend renders:
    ✓ Text summary
    ✓ Metric card: PE 42.5x (▲ 1.2%)
    ✓ Source badges: yahoo.com, nseindia.com
```

### 8.2 Deep Research Flow (e.g., "Full analysis of TCS")

```
User → POST /research/deep
  {
    "target": "TCS",
    "message": "Deep research memo with risks, valuation, and competitors",
    "passes": 5,
    "mode": "deep"
  }

  → Gateway mints master_session_id

  → Deep runner executes passes 0 to N-2 in PARALLEL:
    Pass 0: Core financials (run_research_session with focused objective)
    Pass 1: Competitive moat
    Pass 2: Management/governance
    Pass 3: Valuation
    Pass 4: Risk scan

    Each pass = independent 8-phase pipeline with narrowed scope

  → Pass N-1 (Synthesis) runs SERIAL after parallel passes complete
    → Integrates all AgentFindings into single investment-grade memo
    → Conflict resolution across passes
    → Cross-pass citation deduplication

  → Events emitted via SSE:
    deep_pass: { pass: 0, status: "running" }
    deep_pass: { pass: 1, status: "running" }
    ...
    deep_pass: { pass: 0, status: "done" }
    phase: "synthesis"
    memo: { title: "TCS Investment Memo", ... }
    final: { markdown: "...", artifact: {...} }

  → Frontend:
    ✓ Live pass progress bars
    ✓ Agent cards (Financials ✓, Risk ✓, Valuation ✓)
    ✓ Final memo with sections
```

### 8.3 Marathon Mode Flow

```
User → POST /research/deep
  {
    "target": "Asian Paints",
    "passes": 12,
    "pass_depth": 120,
    "max_wall_seconds": 14400,
    "heartbeat_interval_s": 20
  }

  → Same deep runner but with extended budget
  → Heartbeat SSE event every 20 seconds:
    heartbeat: { elapsed_sec: 120, passes_done: 3, passes_total: 12 }

  → If time budget exceeded:
    phase: "stopped"
    reason: "time_budget"
    → Synthesizes from all evidence collected so far

  → Output: Full investment-grade report (up to 12,000 characters)
```

---

## 9. State, Memory & Persistence

The system is **intentionally serverless/SQLite-first** to minimize infrastructure cost while maintaining full persistence and searchability.

### 9.1 SQLite Databases

All databases live under `FINAGENT_HOME` (default `~/.finagent/`).

| Database | File | Schema Highlights | Purpose |
|----------|------|-------------------|---------|
| **Research State** | `research_state.sqlite3` | `sessions` (metadata), `checkpoints` (JSON snapshots), `findings` (FTS5 virtual table) | Session checkpointing, resume after crash, full-text search across all discovered facts |
| **Long-Term Memory** | `memory.sqlite3` | `facts` (target_key, kind, body, confidence, source_url, session_id) + `facts_fts` (FTS5 virtual) + `session_summaries` | Persistent company facts learned across sessions; BM25 full-text recall |
| **Chat Memory** | `chat_memory.db` | `messages` (user_email, session_id, role, content, timestamp) | Per-user persistent conversation history |

### 9.2 Checkpoint System (`state/checkpoint.py`)

```python
@dataclass
class Checkpoint:
    step: int                          # Current phase (1-8)
    completed_steps: List[StepResult]  # What finished successfully
    pending_steps: List[ResearchStep]  # What's queued
    citation_log: List[Citation]       # All sources found so far
    confidence_summary: Dict[str, float]  # Per-dimension confidence
    context_tokens_used: int           # Token budget tracking
```

- **Serialization:** JSON via `serialize_checkpoint()` / `deserialize_checkpoint()`
- **Frequency:** Saved after every phase completion
- **Recovery:** On session resume, the orchestrator reads the latest checkpoint and skips completed phases

### 9.3 Session Context (`state/session_context.py`)

Runtime per-session state that is **not** persisted (rebuilt on resume):
- `asyncio.Queue` for SSE events
- `httpx.AsyncClient` for HTTP fetches
- Playwright browser context (if active)
- LLM streaming tokens buffer

### 9.4 Citation Log (`state/citation_log.py`)

Tracks every source used in a session:
```python
@dataclass
class Citation:
    url: str
    title: str
    date_accessed: datetime
    kind: str  # "primary" | "secondary" | "tertiary"
    domain_tier: int  # 1 = NSE/SEBI, 2 = IR filings, 3-4 = Indian research, 6 = global wires
```

### 9.5 Design Patterns

- **WAL Mode:** Enabled on all SQLite connections for concurrency safety
- **Thread Safety:** Each method opens a fresh SQLite connection; no shared handles across threads
- **Normalization:** Company names stripped of "Ltd/Inc/Corp/PLC" suffixes for consistent memory keys (`normalize_target("NVIDIA Corporation")` → `"nvidia"`)
- **Session Bus:** In-process `asyncio.Queue` per SSE session + durable `events.jsonl` append-only log for replay after disconnect

---

## 10. MCP Server Architecture

The system embeds **5 FastMCP servers** (using `fastmcp` library). In local development they run on ports 8001–8005; in production they are internal microservices or sidecars.

### 10.1 Service Registry

| Port | Service | File | Engine | Key Tools |
|------|---------|------|--------|-----------|
| **8001** | NSE Market Data | `tools/mcp_servers/nse_server.py` | `NseIndiaApi` (BennyThadikaran) | `nse_get_quote`, `nse_get_historical`, `nse_get_option_chain`, `nse_get_index`, `nse_get_shareholding`, `nse_get_actions`, `nse_get_announcements` |
| **8002** | Fundamentals | `tools/mcp_servers/fundamentals_server.py` | `yfinance` + NSE fallback | `get_profile`, `get_statements`, `get_ratios`, `get_quarterly`, `get_peers`, `get_dividend_history` |
| **8003** | Research & News | `tools/mcp_servers/research_server.py` | Tavily + DDG + Bing | `web_search`, `finance_search`, `news_search`, `url_extract` |
| **8004** | Documents | `tools/mcp_servers/docs_server.py` | Qdrant + Tavily | `document_search`, `pdf_ingest`, `url_ingest`, `annual_report_fetch`, `drhp_rhp_compare` |
| **8005** | Valuation | `tools/mcp_servers/mcp_valuation.py` | `valuation_engine.py` (~35K lines) | `dcf_valuation`, `pe_valuation`, `graham_valuation`, `ev_ebitda_valuation`, `ddm_valuation`, `wacc`, `cagr`, `piotroski_score`, `altman_z_score`, `dupont_analysis`, `full_valuation` |

### 10.2 MCP Lifecycle

- **Startup:** `Backend/start_servers.ps1` launches all 5 servers in background
- **Shutdown:** `Backend/stop_servers.ps1` terminates all servers
- **Config:** `Backend/mcp_config.py` contains service URLs and retry policies
- **Health:** Each MCP exposes a `/health` endpoint for gateway health checks
- **Fallback:** If an MCP is down, the gateway can call tools directly (with degraded performance)

### 10.3 Valuation Engine (~35K Lines)

The valuation MCP is unique because it contains zero LLM calls — it is pure deterministic Python math:

| Model | Inputs | Output |
|-------|--------|--------|
| **DCF** | Revenue, EBITDA, capex, working capital, WACC, terminal growth | Enterprise value, equity value per share |
| **PE Valuation** | Current PE, sector avg PE, EPS growth | Fair value range |
| **Graham** | EPS, book value, AAA bond yield | Intrinsic value (conservative) |
| **EV/EBITDA** | EBITDA, EV multiple, net debt | Enterprise value, equity value |
| **DDM** | DPS, cost of equity, growth rate | Per-share fair value |
| **WACC** | Debt/equity ratio, cost of debt, beta, risk-free rate, market premium | Discount rate |
| **CAGR** | Starting value, ending value, periods | Growth rate % |
| **Piotroski** | ROA, CFO, delta ROA, accruals, delta leverage, delta liquidity, etc. | F-Score (0-9) |
| **Altman Z** | Working capital, retained earnings, EBIT, sales, total assets | Bankruptcy probability score |
| **DuPont** | Net margin, asset turnover, equity multiplier | ROE decomposition |

---

## 11. Gateway API Specification

### 11.1 Authentication Flows

#### Google OAuth
```
POST /auth/google
Body: { "token": "<google_id_token>" }
Response: { "jwt": "<finagent_jwt>", "user": { "email", "name", "picture" } }
```

#### Email/Password
```
POST /auth/signup
Body: { "email": "...", "password": "..." }
→ Sends verification code via SMTP

POST /auth/login
Body: { "email": "...", "password": "..." }
Response: { "jwt": "...", "user": { ... } }

POST /auth/forgot-password
Body: { "email": "..." }
→ Sends reset code

POST /auth/reset-password
Body: { "email": "...", "code": "...", "new_password": "..." }
```

### 11.2 Research Job Lifecycle

#### Start Standard Research
```http
POST /research/start
Content-Type: application/json
Authorization: Bearer <jwt>

{
  "target": "TCS",
  "message": "What is the current PE and how does it compare to peers?",
  "mode": "standard"
}
```

**Response:**
```json
{
  "session_id": "sess_abc123",
  "status": "running",
  "urls": {
    "status": "/sessions/sess_abc123/status",
    "events": "/sessions/sess_abc123/events",
    "stream": "/sessions/sess_abc123/stream",
    "result": "/sessions/sess_abc123/result"
  }
}
```

#### SSE Stream
```http
GET /sessions/{session_id}/stream
Authorization: Bearer <jwt>
Accept: text/event-stream
```

**Event Examples:**
```
event: phase
data: {"phase": "identify", "status": "running", "message": "Resolving TCS to NSE symbol..."}

event: agent_task
data: {"agent": "financials", "task": "fetch_revenue_margins", "status": "started"}

event: subagent_done
data: {"agent": "financials", "findings_count": 12, "duration_ms": 2340}

event: source
data: {"domain": "nseindia.com", "tier": 1, "title": "TCS Share Price"}

event: intel
data: {"kind": "metric", "label": "PE Ratio", "value": "42.5", "currency": "INR"}

event: memo
data: {"section": "Executive Summary", "content": "TCS is trading at a premium..."}

event: final
data: {"markdown": "# TCS Research Memo\n\n...", "artifact": {...}, "quality_score": 82}
```

### 11.3 Session Status Response
```http
GET /sessions/{session_id}/status
```

```json
{
  "session_id": "sess_abc123",
  "phase": "synthesis",
  "progress_pct": 85,
  "agents_completed": ["financials", "news", "risk", "technical"],
  "agents_running": ["valuation"],
  "agents_pending": ["governance"],
  "sources_found": 23,
  "quality_score": 78,
  "elapsed_sec": 145,
  "estimated_remaining_sec": 30
}
```

---

## 12. Frontend Architecture

### 12.1 Framework & Structure

- **Next.js 14+** with App Router (`Frontend/app/`)
- **React + TypeScript** with `"use client"` directives for interactive components
- **SVG Charts** — no external charting library; all charts are custom SVG for minimal bundle size

### 12.2 Chart Components (`Frontend/app/_components/Charts/`)

| Component | Render Type | Features |
|-----------|-------------|----------|
| `AreaChart.tsx` | SVG polygon + polyline | Stacked/area fills, grid lines, tooltip-ready |
| `BarChart.tsx` | SVG + CSS grid | Horizontal bars, percentage widths, locale-formatted values (`en-IN`) |
| `DonutChart.tsx` | SVG circle arcs | Ring segments, percentage labels, color coding |
| `GaugeChart.tsx` | SVG arc + needle | Radial gauge, min/max range, value indicator |
| `MultiSeriesBarChart.tsx` | SVG rect groups | Grouped/comparison bars, legend, axis labels |
| `MultiSeriesLineChart.tsx` | SVG path + circles | Multi-line time series, hover points, grid |

### 12.3 Communication Patterns

#### Server-Sent Events (Primary)
```typescript
const es = new EventSource(`/sessions/${sessionId}/stream`);
es.addEventListener('phase', (e) => updatePhaseBar(JSON.parse(e.data)));
es.addEventListener('agent_task', (e) => updateAgentCard(JSON.parse(e.data)));
es.addEventListener('source', (e) => addSourceBadge(JSON.parse(e.data)));
es.addEventListener('intel', (e) => updateMetricCard(JSON.parse(e.data)));
es.addEventListener('final', (e) => renderFinalMemo(JSON.parse(e.data)));
```

#### Polling Fallback
```typescript
// Poll status every 5 seconds if SSE fails
const status = await fetch(`/sessions/${sessionId}/status`).then(r => r.json());
// Poll events with cursor
const events = await fetch(`/sessions/${sessionId}/events?after=${lastEventId}`).then(r => r.json());
```

### 12.4 UI Panels

1. **Chat Thread** — Markdown rendering with syntax highlighting, citation links
2. **Agent Process Panel** — Live cards for each specialist agent (running/done/error)
3. **Source Badges** — Domain pills with tier coloring (tier-1 = gold, tier-2 = silver)
4. **Metric Cards** — Sparkline + current value + change indicator
5. **Comparison Tables** — Sortable, filterable data tables
6. **Charts Panel** — Rendered SVG charts from `AnswerArtifact`

### 12.5 Gateway-Served Static UIs

For zero-build deployments or embed scenarios, the FastAPI gateway serves complete HTML pages:
- `landing.html` — Marketing landing with feature highlights
- `login.html` / `signup.html` — Auth flows with Google OAuth + email/password
- `profile.html` — User dashboard with session history
- `settings.html` — API keys, preferences, notification settings
- `widget.html` — Embeddable research widget (iframe-ready) with real-time agent visualization

---

## 13. Research Quality & Accuracy

### 13.1 Quality Scoring (`analysis/quality.py`)

10-dimension heuristic score (max ~100 points). Pass threshold: **≥ 75**.

| Dimension | Weight | Description | Check |
|-----------|--------|-------------|-------|
| `identity` | 8 | Company identification confidence | Symbol resolved? Multiple exchanges? |
| `financials` | 16 | Coverage of revenue, margins, cash flow | 3+ years? Quarterly? Segment data? |
| `history` | 12 | Multi-year historical data availability | 5+ years price history? |
| `filing_narrative` | 10 | SEBI/SEC filing analysis | Latest 10-K/annual report parsed? |
| `live_quote` | 6 | Real-time market data freshness | LTP within 15 minutes? |
| `press_coverage` | 10 | News and media coverage depth | 5+ distinct articles? |
| `web_diversity` | 12 | Number of distinct source domains | 6+ domains? |
| `citation_tiering` | 10 | Primary vs secondary source ratio | ≥ 40% tier-1? |
| `conflicts` | 4 | Cross-source consistency | No major numeric conflicts? |
| `competitive` | 4 | Peer/competitor analysis coverage | 3+ peers compared? |

**Auto-Actions:**
- If score < 75: Auto-generates `suggested_queries` for missing dimensions
- If score < 60: Extends deep research with an additional pass
- If score < 40: Falls back to template-based memo (no LLM synthesis to avoid hallucination)

### 13.2 Conflict Detection (`analysis/conflicts.py`)

- **Cross-Source Validation:** If Yahoo Finance revenue ≠ SEC revenue → flags conflict with confidence degradation
- **Unit Mismatch Detection:** Catches "Cr" vs "Lakh" vs "Mn" discrepancies
- **Staleness Detection:** Flags data older than 90 days for financial statements
- **Outlier Detection:** Z-score > 3 for any metric compared to historical range

### 13.3 Source Tiering

| Tier | Sources | Confidence Weight |
|------|---------|-------------------|
| **1** | NSE India, BSE, SEBI, SEC EDGAR, Company IR | 1.0 |
| **2** | Yahoo Finance, Bloomberg, Reuters | 0.9 |
| **3** | Moneycontrol, Screener.in, Trendlyne | 0.8 |
| **4** | Economic Times, Business Standard, Mint | 0.7 |
| **5** | Brokerage research notes, rating agencies | 0.6 |
| **6** | Global wires (FT, WSJ), Wikipedia | 0.5 |
| **7** | Social media, forums, blogs | 0.3 |

---

## 14. Web Scraping & Search Infrastructure

### 14.1 Search Backends (`tools/web/scraper.py`)

Tiered fallback chain ensures maximum coverage:

1. **DuckDuckGo** — Default, no API key required, rate-limited
2. **Bing** — Secondary web search (requires `BING_API_KEY`)
3. **Tavily API** — AI-native search + content extraction (requires `TAVILY_API_KEY`)
4. **SearXNG** — Private instance when `FINAGENT_SEARXNG_URL` is set
5. **Playwright Chromium** — For JS-heavy or blocked pages (final fallback)

### 14.2 Browser Pool (`tools/browser/`)

**Playwright Chromium** with async page pool:
- `FINAGENT_BROWSER_FALLBACK=1` — Retry failed searches via Chromium rendering
- `FINAGENT_BROWSER_FALLBACK_HTTP=1` — Retry failed HTTP fetches via Chromium
- `FINAGENT_BROWSER_MAX_PAGES=3` — Cap concurrent rendered pages (memory safety)
- **Helpers:**
  - `browser_extract(url, selector)` — DOM extraction from allowlisted JS-heavy pages
  - `screenshot_page(url)` — PNG evidence capture for archival

### 14.3 HTTP Fetcher (`tools/web/http_fetcher.py`)

- Shared async `httpx.AsyncClient` with connection pooling
- Automatic User-Agent rotation from a pool of 12 realistic strings
- Timeout handling: 30s connect, 60s read
- Retry logic: 3 retries with exponential backoff for 5xx and network errors
- Connection cleanup on shutdown (`aclose_shared_client()`)

### 14.4 Crawl4AI Integration

- Used for deep content extraction from financial media sites
- Playwright-based rendering for JavaScript-dependent pages
- Automatic table extraction and markdown conversion

---

## 15. Synthesis & Output Generation

### 15.1 Enrichment Bundle (`synthesis.py`)

Before synthesis, all data is normalized into an `EnrichmentBundle`:

```python
@dataclass
class EnrichmentBundle:
    india_snap: IndiaCompanySnapshot       # NSE/BSE live data
    sebi_filing: SEBIFiling                # Latest SEBI filing narrative
    shareholding: ShareholdingPattern      # Promoter / FII / DII / Public breakdown
    yahoo: YahooQuote                      # Quote & financial history
    wikipedia: WikipediaSummary            # Company overview
    fx: FxRate                             # USD/INR rate
    news: List[NewsItem]                  # Headlines with sentiment
    sec: Optional[SECCompanySnapshot]      # US data (if applicable)
```

### 15.2 Memo Generation (`synthesis.py`)

**Currency Policy:** All monetary figures in **INR** (crore/lakh notation) first. USD values secondary.

**Source Policy:** Every number sourced from NSE/BSE, Moneycontrol, Screener.in, SEBI filings, Yahoo `.NS`/`.BO`, or domestic financial media.

**LLM Strategy:**
- **Primary:** OpenAI GPT-4o streaming when `OPENAI_API_KEY` is available
- **Fallback:** Template-based assembly when API unavailable or rate-limited
- **Budget:** `_MEMO_BUDGET_CHARS = 12,000` character limit to control token cost

**Memo Sections:**
1. Executive Summary (3-4 bullets)
2. Company Overview (sector, history, business model)
3. Financial Analysis (revenue, margins, cash flow, balance sheet)
4. Valuation & Fair Value (DCF, PE, Graham, EV/EBITDA consensus)
5. Competitive Landscape (peers, market share, moat)
6. Risk Factors (operational, financial, regulatory, macro)
7. Recent News & Events (earnings, M&A, management changes)
8. Citations & Sources (domain-grouped URL list)

### 15.3 Output Artifacts (`output/`)

```python
@dataclass
class AnswerArtifact:
    sections: List[ResponseSection]        # Text blocks
    charts: List[AnswerChart]              # SVG chart descriptors
    tables: List[AnswerTable]            # Data tables
    metric_cards: List[MetricCard]         # Sparkline + value + change
    comparisons: List[ComparisonResult]    # Side-by-side peer metrics
    citations: List[AnswerCitation]      # Source links with badges
```

### 15.4 Renderer (`output/renderer.py`)

- `render_markdown()` — Plain markdown for chat widgets
- `render_rich_json()` — Structured JSON for interactive frontend rendering
- `render_email()` — HTML email template for share/digest features

---

## 16. Security & Authentication

### 16.1 Authentication Methods

| Method | Flow | Use Case |
|--------|------|----------|
| **Google OAuth** | ID token → verify with Google → mint FinAgent JWT | Social login |
| **Email/Password** | bcrypt hash + verification code via SMTP | Traditional auth |
| **JWT Bearer** | `Authorization: Bearer <token>` | All authenticated API calls |

### 16.2 JWT Claims

```json
{
  "sub": "user@example.com",
  "email": "user@example.com",
  "name": "User Name",
  "iat": 1717000000,
  "exp": 1717086400,
  "iss": "finagent-gateway"
}
```

### 16.3 Rate Limiting

`InMemSlidingWindowRateLimiter`:
- **Per-IP:** 20 requests/minute for unauthenticated users
- **Per-Token:** 60 requests/minute for authenticated users
- **Research Jobs:** 5 concurrent jobs per user
- **Window:** 60-second sliding window with automatic cleanup

### 16.4 Session Ownership

All `/sessions/{id}/*` endpoints call `verify_session_ownership()`:
- Extracts JWT from `Authorization` header
- Compares `jwt.email` against `session.owner_email`
- Returns 403 if mismatch

### 16.5 Data Privacy

- **No PII in logs:** User emails hashed in access logs
- **Session isolation:** SQLite databases are per-deployment; no cross-tenant data leakage
- **API key masking:** Keys logged as `sk-...XXXX` (last 4 chars only)

---

## 17. Deployment & Infrastructure

### 17.1 Containerization

**Backend Dockerfile (root):**
```dockerfile
FROM python:3.11-slim
# Install Playwright system dependencies
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdrm2 libdbus-1-3 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2
# Install Python deps
COPY requirements-finagent.txt .
RUN pip install -r requirements-finagent.txt
# Install Playwright browsers
RUN playwright install chromium
# Copy app
COPY finagent/ /app/finagent/
WORKDIR /app
CMD ["uvicorn", "finagent.gateway.run:app", "--host", "0.0.0.0", "--port", "8080"]
```

**TimesFM Dockerfile (`timesfm-service/`):**
- Bakes `google/timesfm-2.5-200m-pytorch` weights at build time (~300MB layer)
- Exposes FastAPI on port 8000 + FastMCP on port 8001

### 17.2 CI/CD Pipeline

```
GitHub push to production branch
    ↓
GitHub Actions triggered (.github/workflows/deploy-production.yml)
    ↓
Step 1: Run pytest suite (finagent/tests/)
    ↓
Step 2: docker build -t prospektlab-backend:latest .
    ↓
Step 3: docker push $AWS_ECR_URI/prospektlab-backend:latest
    ↓
Step 4: aws ecs update-service \
           --cluster prospektlab \
           --service backend \
           --force-new-deployment
    ↓
Step 5: Fargate pulls new image, starts container (port 8080)
    ↓
Step 6: ALB health check /health → 200 OK
    ↓
Step 7: Route53 → https://api.prospektlab.com
    ↓
Step 8: Slack notification: "Deployment successful!"
    ↓
Frontend: AWS Amplify detects git push → builds & deploys Next.js app
```

### 17.3 AWS Infrastructure

```
┌─────────────────────────────────────────────────────────────┐
│                          AWS CLOUD                           │
│                                                              │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐    │
│  │   Route53   │────▶│    ALB      │────▶│ ECS Fargate │    │
│  │  (DNS)      │     │ (TLS/HTTP)  │     │  (Backend)  │    │
│  └─────────────┘     └─────────────┘     └─────────────┘    │
│                               │                              │
│                               ▼                              │
│                        ┌─────────────┐                        │
│                        │ AWS ECR     │                        │
│                        │ (Images)    │                        │
│                        └─────────────┘                        │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ AWS Amplify (Frontend)                                   │ │
│  │  • Next.js build                                         │ │
│  │  • CDN distribution                                      │ │
│  │  • Connects to api.prospektlab.com                       │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ AWS CodeBuild (CI/CD)                                    │ │
│  │  • buildspec.yml (staging)                               │ │
│  │  • buildspec-prod.yml (production)                       │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### 17.4 Local Development

```bash
# Terminal 1: Start MCP servers
powershell -File Backend/start_servers.ps1

# Terminal 2: Start backend gateway
uvicorn finagent.gateway.run:app --host 0.0.0.0 --port 8080 --reload

# Terminal 3: Start TimesFM service (optional)
cd timesfm-service && uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 4: Start Next.js frontend
cd Frontend && npm run dev
```

### 17.5 Environment Variables (Production)

```env
# === API Keys ===
OPENAI_API_KEY=sk-proj-...
TAVILY_API_KEY=tvly-...
BING_API_KEY=...

# === MCP Service URLs (internal ECS service discovery) ===
MCP_NSE_INDIA_URL=http://mcp-nse-service:8001/mcp
MCP_FUNDAMENTALS_URL=http://mcp-fundamentals-service:8002/mcp
MCP_RESEARCH_URL=http://mcp-research-service:8003/mcp
MCP_DOCS_URL=http://mcp-docs-service:8004/mcp
MCP_VALUATION_URL=http://mcp-valuation-service:8005/mcp

# === TimesFM ===
TIMESFM_REMOTE_URL=http://timesfm-service:8000

# === Auth ===
SUPABASE_URL=https://....supabase.co
SUPABASE_KEY=eyJ...
JWT_SECRET=...
SMTP_HOST=smtp.gmail.com
SMTP_USER=...
SMTP_PASS=...

# === CORS ===
CORS_ORIGINS=https://app.prospektlab.com,https://www.prospektlab.com

# === Frontend ===
BACKEND_API_URL=https://api.prospektlab.com

# === Browser & Scraping ===
FINAGENT_BROWSER_FALLBACK=1
FINAGENT_BROWSER_MAX_PAGES=3
FINAGENT_FETCH_CONCURRENCY=6

# === Geo & Search ===
FINAGENT_DEFAULT_GEO=IN
FINAGENT_SEARXNG_URL=
FINAGENT_DOMAIN_PINNED_QUERIES=1
```

---

## 18. Testing & Quality Assurance

### 18.1 Test Suite

| Test File | Scope | Coverage |
|-----------|-------|----------|
| `finagent/tests/` | Agent logic, orchestrator, state | Unit tests for BaseSubAgent, Orchestrator, Checkpoint |
| `gateway/test_gateway.py` | API endpoints, SSE, job lifecycle | Integration tests for /research/start, /chat/research, /sessions/*/stream |
| `gateway/test_security.py` | Auth, rate limiting, session ownership | JWT validation, bypass attempts, ownership enforcement |
| `tools/web/test_ingestion.py` | Scraper regression | DDG, Bing, Tavily extraction consistency |
| `tools/web/test_units.py` | Unit conversions | Crore/lakh/million/billion normalization |
| `tests/test_valuation.py` | Valuation engine | DCF, PE, Graham, Altman Z expected values |

### 18.2 Test Strategy

- **Unit Tests:** Pytest with `pytest-asyncio` for async agent tests
- **Mocking:** `respx` for httpx mocking, `pytest-mock` for Playwright/browser mocking
- **Integration Tests:** Live MCP server spin-up in `setup_module`, teardown in `teardown_module`
- **Valuation Regression:** Pre-computed expected values for 20 known companies; any engine change must pass

### 18.3 Quality Gates

1. **Pytest Pass:** All tests must pass before merge
2. **Type Checking:** `mypy` on `finagent/` (strict mode for gateway)
3. **Linting:** `ruff` for style and import sorting
4. **Security Scan:** `bandit` for high-severity issues
5. **Docker Build:** Image must build and `/health` must return 200 within 60s

---

## 19. Environment Configuration

### 19.1 Required Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | LLM synthesis, query contextualization |
| `FINAGENT_HOME` | No (default `~/.finagent`) | Base directory for all state files |

### 19.2 Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TAVILY_API_KEY` | — | Tavily search API (enables tier-3 search) |
| `BING_API_KEY` | — | Bing web search API |
| `MCP_NSE_INDIA_URL` | `http://localhost:8001/mcp` | NSE MCP service URL |
| `MCP_FUNDAMENTALS_URL` | `http://localhost:8002/mcp` | Fundamentals MCP URL |
| `MCP_RESEARCH_URL` | `http://localhost:8003/mcp` | Research MCP URL |
| `MCP_DOCS_URL` | `http://localhost:8004/mcp` | Docs MCP URL |
| `MCP_VALUATION_URL` | `http://localhost:8005/mcp` | Valuation MCP URL |
| `TIMESFM_REMOTE_URL` | — | External TimesFM service (if not running in-process) |
| `FINAGENT_BROWSER_FALLBACK` | `0` | Retry failed searches via Chromium |
| `FINAGENT_BROWSER_FALLBACK_HTTP` | `0` | Retry failed HTTP via Chromium |
| `FINAGENT_BROWSER_MAX_PAGES` | `3` | Max concurrent browser pages |
| `FINAGENT_FETCH_CONCURRENCY` | `6` | Max concurrent HTTP fetches |
| `FINAGENT_SEARXNG_URL` | — | Private SearXNG instance URL |
| `FINAGENT_DOMAIN_PINNED_QUERIES` | `1` | Enable tier-1 domain-pinned breadth queries |
| `FINAGENT_DEFAULT_GEO` | — | Lock entity resolution to `IN` (India) by default |
| `CORS_ORIGINS` | `*` | Allowed CORS origins (comma-separated) |
| `BACKEND_API_URL` | — | Frontend backend URL |

---

## 20. Roadmap & Future Phases

| Phase | Timeline | Feature | Impact |
|-------|----------|---------|--------|
| **Phase 1** (Current) | May 2026 | Multi-agent research, live NSE/BSE data, valuation engine, SSE streaming, AWS deployment | Production-ready financial intelligence OS |
| **Phase 2** | Q2–Q3 2026 | **Broker integration** (Zerodha Kite, Angel One, Upstox APIs); **Portfolio context** import; **Personalized risk analysis** based on actual holdings | From research → actionable portfolio intelligence |
| **Phase 3** | Q3–Q4 2026 | **Real-time alerts:** price triggers, corporate announcements, earnings surprises, portfolio risk alerts; **Push notifications** via email/SMS | Proactive intelligence, not just reactive queries |
| **Phase 4** | Q4 2026+ | **Forensic accounting red flags** engine; **IPO analysis** (DRHP/RHP deep-read); **Mutual fund overlap** analysis; **Tax harvesting** suggestions; **Options strategy** builder | Expand beyond equities to full wealth management |
| **Phase 5** | 2027+ | **Multi-market expansion** (US, UK, Singapore); **Real-time voice interface**; **White-label API** for brokerages and fintechs | Platformization and global scale |

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **MCP** | Model Context Protocol — FastMCP microservices that expose tools to the orchestrator |
| **SSE** | Server-Sent Events — HTTP streaming protocol for real-time frontend updates |
| **FTS5** | SQLite Full-Text Search engine (version 5) for fast text retrieval |
| **WAL** | Write-Ahead Logging — SQLite concurrency mode allowing multiple readers |
| **NSE** | National Stock Exchange of India |
| **BSE** | Bombay Stock Exchange |
| **SEBI** | Securities and Exchange Board of India |
| **DRHP/RHP** | Draft Red Herring Prospectus / Red Herring Prospectus (IPO documents) |
| **FII/DII** | Foreign Institutional Investor / Domestic Institutional Investor |
| **PE** | Price-to-Earnings ratio |
| **DCF** | Discounted Cash Flow valuation model |
| **WACC** | Weighted Average Cost of Capital |
| **CAGR** | Compound Annual Growth Rate |
| **TimesFM** | Google's zero-shot time-series forecasting model |

---

**ProspektLab 2.0.0** | May 2026 | Financial Intelligence OS for India

*This architecture document is maintained as part of the ProspektLab codebase. For the latest updates, refer to the repository's `ARCHITECTURE.md` and `COMPLETE_ARCHITECTURE.md` files.*

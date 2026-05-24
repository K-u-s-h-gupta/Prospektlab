# ProspektLab / ORACLE FIOS — Complete Architecture

> A Conversational Financial Intelligence OS for the Indian Stock Market.  
> Version: 2.0.0 | Date: May 2026

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [High-Level System Architecture](#2-high-level-system-architecture)
3. [Execution Modes](#3-execution-modes)
4. [FinAgent 8-Phase Research Pipeline](#4-finagent-8-phase-research-pipeline)
5. [Specialist Agents](#5-specialist-agents)
6. [State, Memory & Persistence](#6-state-memory--persistence)
7. [MCP Server Architecture](#7-mcp-server-architecture)
8. [Data & Tooling Layer](#8-data--tooling-layer)
9. [Research Quality & Accuracy](#9-research-quality--accuracy)
10. [Web Scraping & Search](#10-web-scraping--search)
11. [Synthesis & Output](#11-synthesis--output)
12. [Gateway API (FastAPI)](#12-gateway-api-fastapi)
13. [Frontend Architecture](#13-frontend-architecture)
14. [Deployment & Infrastructure](#14-deployment--infrastructure)
15. [Testing & QA](#15-testing--qa)
16. [Complete Data Flow Example](#16-complete-data-flow-example)
17. [Roadmap](#17-roadmap)
18. [File Organization](#18-file-organization)

---

## 1. Product Overview

**ProspektLab** (also known as **ORACLE FIOS** and **FinAgent**) is a conversational AI system that provides analyzed, cited financial intelligence for the Indian stock market.

**Example queries it handles:**
- *"What is TCS's PE ratio?"*
- *"Compare Infosys vs TCS on revenue growth"*
- *"Deep analysis of Asian Paints"*
- *"Show me IT sector trends"*

**Core principle:** Every number is sourced from live market data (NSE/BSE, Yahoo Finance, SEBI filings) or reputable financial media. The system never invents figures.

---

## 2. High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  PRESENTATION LAYER                                         │
│  • Next.js Frontend (React + TypeScript)                    │
│    - Chat UI, SSE streaming, charts, agent visualization    │
└────────────────────┬──────────────────────────────────────────┘
                     │ HTTPS / SSE
┌────────────────────▼──────────────────────────────────────────┐
│  APPLICATION / API LAYER                                      │
│  • FastAPI Gateway (finagent/gateway/run.py)                  │
│    - /api/chat, /research/deep, /chat/research              │
│    - Rate limiting, JWT auth, Supabase integration            │
│    - Serves standalone HTML widgets                         │
└────────────────────┬──────────────────────────────────────────┘
                     │
┌────────────────────▼──────────────────────────────────────────┐
│  ORCHESTRATION LAYER                                          │
│  • FinAgent Research Engine (finagent/run_agent.py)           │
│    - 8-phase autonomous research pipeline                     │
│    - Multi-agent orchestrator (agents/orchestrator.py)       │
│    - Reflection & quality loops                               │
└──────────┬─────────┬──────────┬───────────────────────────────┘
           │         │          │
┌──────────▼──┐ ┌────▼────┐ ┌───▼──────┐ ┌──────────────────────┐
│  SPECIALIST │ │  DATA   │ │  WEB     │ │  MEMORY & STATE      │
│  AGENTS     │ │  APIs    │ │  SEARCH  │ │                      │
│             │ │          │ │          │ │  • Checkpointing     │
│ • Accounting│ │ • NSE    │ │ • DDG    │ │  • Citation logs     │
│ • Financials│ │ • Yahoo  │ │ • Bing   │ │  • Memory store      │
│ • Valuation │ │ • SEC    │ │ • Tavily │ │  • Session events    │
│ • Competitor│ │ • SEBI   │ │ • SearXNG│ │                      │
│ • Risk      │ │ • India  │ │ • Reddit │ │                      │
│ • Technical │ │ • Wiki   │ │ • HN     │ │                      │
│ • News      │ │          │ │          │ │                      │
│ • Governance│ │          │ │ • Browser│ │                      │
│ • Macro     │ │          │ │   (Playwright)                     │
└─────────────┘ └──────────┘ └──────────┘ └──────────────────────┘
```

### Layer Summary

| Layer | Technology | Responsibility |
|-------|------------|--------------|
| **Presentation** | Next.js + React + TypeScript | Chat UI, real-time SSE streaming, charts, agent process visualization |
| **API Gateway** | FastAPI + AsyncIO | Chat endpoint, research jobs, rate limiting, JWT auth, Supabase |
| **Orchestration** | LangGraph concepts + custom orchestrator | 8-phase pipeline, wave-based parallel agent execution |
| **Agents** | Python async classes | 10+ specialist financial analysts |
| **Data/Tools** | MCP servers + direct APIs | NSE, Yahoo, SEC, SEBI, web search, browser scraping |
| **Memory/State** | SQLite (WAL mode) + FTS5 | Session checkpoints, citation logs, long-term facts |

---

## 3. Execution Modes

### Mode 1: Quick Chat (ORACLE) ⚡
**For:** Fast questions (5–15 seconds)  
**Engine:** FastAPI gateway + LangGraph-style routing  
**Flow:**
```
User: "What is Reliance's PE?"
       ↓
Intent classifier → "Need fundamentals data"
       ↓
Orchestrator → Route to Fundamentals agent
       ↓
MCP Fundamentals service → Returns current data
       ↓
LLM synthesizes response
       ↓
"Reliance PE: 42.5x (as of today)"
```

### Mode 2: Deep Research (FinAgent) 🔬
**For:** Thorough company analysis (2–5 minutes, up to 4 hours in Marathon mode)  
**Engine:** `finagent/run_agent.py` (8-phase pipeline)  
**Flow:** see [Section 4](#4-finagent-8-phase-research-pipeline)

### Mode 3: Marathon Mode 🏃
**For:** Exhaustive multi-pass research  
**Config:**
```json
{
  "target": "TCS",
  "passes": 12,
  "pass_depth": 120,
  "max_wall_seconds": 14400,
  "heartbeat_interval_s": 20
}
```
**Behavior:** Runs up to 4 hours with heartbeat SSE events every 20 seconds. Emits `phase=stopped` with `reason=time_budget` when limit reached, then synthesizes from collected evidence.

---

## 4. FinAgent 8-Phase Research Pipeline

**Location:** `finagent/run_agent.py` (~2,000 lines)  
**Core loop:** `run_research_session()`

| Phase | Name | Purpose | Parallel? |
|-------|------|---------|-----------|
| **1** | **Identify** | Resolve target to SEC ticker / CIK (US) or NSE symbol (India) | No |
| **2** | **Enrichment** | Parallel API pulls: SEC EDGAR, Yahoo Finance, Wikipedia, NSE India, SEBI | **Yes** |
| **3** | **Breadth Survey** | Layered web search across 4 angles (DDG, Bing, optional SearXNG) | **Yes** |
| **4** | **Deep Dive** | Iterative targeted queries to fill gaps found in Phase 3 | No |
| **5** | **Analysis** | Cross-source conflict detection + viral/pump-and-dump scoring | No |
| **6** | **Specialist Multi-Agent** | Run 10+ specialist agents in dependency-aware waves | **Yes** (wave-based) |
| **7** | **Verification** | Fact-check claims against multiple sources | No |
| **8** | **Synthesis** | Generate final memo with executive summary, financials, valuation, risks, citations | No |

**Output:** Saved to `~/.finagent/memos/session_{id}.md`

---

## 5. Specialist Agents

**Location:** `finagent/agents/specialists/`  
**Orchestration:** `finagent/agents/orchestrator.py` (wave-based topological execution)

### Base Architecture (`agents/base.py`)
Every specialist inherits from `BaseSubAgent`:
- `name`: machine identifier (e.g., `"valuation"`)
- `display`: human label (e.g., `"Valuation & DCF Projections"`)
- `priority`: lower = earlier in wave
- `dependencies`: tuple of agent names that must complete first
- `precondition(ctx)`: returns `(bool, reason)` — skips if data missing
- `execute(ctx)`: returns `AgentTaskResult` with findings, claims, evidence

### Agent Roster

| Agent | Priority | Dependencies | Key Technique | File |
|-------|----------|--------------|---------------|------|
| **accounting** | 45 | `financials` | TimesFM anomaly detection (P10–P90 corridors) or ±2σ z-score fallback | `accounting.py` |
| **financials** | 30 | — | Revenue, margins, cash-flow trend analysis | `financials.py` |
| **valuation** | 40 | `financials` | TimesFM zero-shot revenue forecasts → DCF terminal growth; CAGR fallback | `valuation.py` |
| **competitor** | 25 | — | Peer benchmarking, market share analysis | `competitor.py` |
| **risk** | 35 | — | Credit risk, operational risk, red-flag detection | `risk.py` |
| **technical** | 20 | — | Price action, chart patterns, indicators | `technical.py` |
| **news** | 15 | — | Event-driven sentiment, recent developments | `news.py` |
| **governance** | 28 | — | Board structure, insider dealings, ESG | `governance.py` |
| **macro** | 18 | — | Sector and economy-wide context | `macro.py` |
| **community** | 22 | — | Reddit, HN, StockTwits sentiment + pump-and-dump scoring | `community.py` |

### Orchestrator Logic
- **Wave 0**: All agents with no dependencies fire concurrently via `asyncio.gather`
- **Wave N**: Agents whose dependencies are all met from prior waves
- **Timeout**: Each agent has its own `deadline_ms` so one slow agent doesn't block the wave
- **Cycle detection**: If dependency cycle detected, remaining agents are released into one wave defensively

---

## 6. State, Memory & Persistence

All persistence is **SQLite-based** (serverless, WAL-mode for concurrency, FTS5 for search).

### 6.1 Session Checkpoints (`state/checkpoint.py`)
**Dataclass:** `Checkpoint`
- `step`: current phase number
- `completed_steps`: list of `StepResult` (name, summary, ok/fail)
- `pending_steps`: list of `ResearchStep` (name, tool, expected_output)
- `citation_log`: list of `Citation` (url, title, date_accessed, kind)
- `confidence_summary`: per-dimension confidence scores
- `context_tokens_used`: token budget tracking

**Serialization:** JSON via `serialize_checkpoint()` / `deserialize_checkpoint()`  
**Use case:** Resume long-running sessions after crashes or timeouts.

### 6.2 Research State Store (`state/research_state.py`)
**Schema:**
```sql
CREATE TABLE sessions (id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT, metadata_json TEXT);
CREATE TABLE checkpoints (id INTEGER PRIMARY KEY, session_id TEXT, step INTEGER, payload_json TEXT, created_at TEXT);
CREATE VIRTUAL TABLE findings USING fts5(session_id UNINDEXED, body, tokenize='porter');
```
- Sessions table tracks research job metadata
- Checkpoints table stores full state snapshots per phase
- **FTS5 findings table** enables full-text search across all discovered facts

**CLI init:** `python -m finagent.state.research_state --init`

### 6.3 Long-Term Memory (`memory/store.py`)
**Database:** `memory.sqlite3` (under `FINAGENT_HOME`)

**Schema — one row per `MemoryFact`:**
| Column | Type | Description |
|--------|------|-------------|
| `target_key` | TEXT | Canonical normalized identifier (ticker or lowercased company name) |
| `kind` | TEXT | `financial`, `risk`, `sentiment`, `news_event`, `competitive`, `governance`, `identity`, `other` |
| `body` | TEXT | The fact text |
| `confidence` | TEXT | `HIGH` / `MEDIUM` / `LOW` |
| `source_url` | TEXT | Mandatory for HIGH confidence |
| `session_id` | TEXT | Provenance tracking |

**Normalization:** `normalize_target("NVIDIA Corporation")` → `"nvidia"` (strips Corp/Inc/Ltd/PLC suffixes).  
**Recall:** FTS5 fuzzy search by `target_key` + optional `kind` filter.  
**Thread safety:** Each method opens a fresh SQLite connection.

---

## 7. MCP Server Architecture

The system embeds **5 FastMCP servers** (using `fastmcp` library). In local development they run on ports 8001–8005; in production they are internal microservices.

### 7.1 NSE Market Data Server (`tools/mcp_servers/nse_server.py`)
- **Port:** `8001`
- **Engine:** `NseIndiaApi` (BennyThadikaran) — free, no API key required
- **Tools:**
  - `nse_get_quote` — real-time LTP, change, volume
  - `nse_get_historical` — OHLCV history from NSE directly
  - `nse_get_option_chain` — PCR, max pain calculation
  - `nse_get_index` — Nifty 50, Bank Nifty, etc.
  - `nse_get_shareholding` — promoter / public / FII / DII holding pattern
  - `nse_get_actions` — dividends, splits, bonuses
  - `nse_get_announcements` — corporate announcements
- **Lazy init:** NSE client initializes on first tool call to avoid cookie issues at import time.

### 7.2 Fundamentals Server (`tools/mcp_servers/fundamentals_server.py`)
- **Port:** `8002`
- **Sources:** Yahoo Finance (`yfinance`) + NSE India fallback
- **Tools:** company profile, financial statements, ratios, quarterly results, peer comparison, dividend history

### 7.3 Research & News Server (`tools/mcp_servers/research_server.py`)
- **Port:** `8003`
- **Sources:** Tavily Search + Extract API, DuckDuckGo, Bing
- **Tools:** `web_search`, `finance_search`, `news_search`, `url_extract`
- **Fallback chain:** Tavily → DuckDuckGo → Bing → Playwright browser rendering

### 7.4 Documents Server (`tools/mcp_servers/docs_server.py`)
- **Port:** `8004`
- **Vector DB:** Qdrant for semantic retrieval
- **Tools:** document search, PDF ingest, URL ingest, annual report fetch, DRHP/RHP/prospectus comparison

### 7.5 Valuation Server (`tools/mcp_servers/mcp_valuation.py`)
- **Port:** `8005`
- **Engine:** `valuation_engine.py` (~35K lines of deterministic finance math)
- **Tools:**
  - `dcf_valuation` — Discounted Cash Flow
  - `pe_valuation` — Relative PE
  - `graham_valuation` — Benjamin Graham intrinsic value
  - `ev_ebitda_valuation` — Enterprise value multiples
  - `ddm_valuation` — Dividend Discount Model
  - `wacc` — Weighted Average Cost of Capital
  - `cagr` — Compound Annual Growth Rate
  - `piotroski_score` — Piotroski F-Score (9-point quality scale)
  - `altman_z_score` — Altman Z-Score (bankruptcy predictor)
  - `dupont_analysis` — ROE decomposition
  - `full_valuation` — Composite report combining all models
- **Deterministic:** zero LLM calls; pure Python math on fetched financials.

---

## 8. Data & Tooling Layer

### 8.1 Core Data Models (`tools/data.py`)
Key dataclasses:
- `IndiaCompanySnapshot` — NSE/BSE live data
- `YahooQuote` — price, market cap, revenue history
- `SECCompanySnapshot` / `SECTimeSeries` — US SEC data
- `SEBIFiling` — Indian regulatory filings
- `FxRate` — USD/INR conversion
- `NewsItem` — press articles with sentiment
- `WikipediaSummary` — company overview
- `HNStory` / `RedditPost` / `StockTwitsSnapshot` — social signals

### 8.2 India Market Data (`tools/india.py`)
- NSE live quotes, historical prices
- SEBI filing fetch
- Shareholding pattern analysis (promoter, FII, DII, public)
- Company snapshot from NseIndiaApi

### 8.3 US Market Data (`tools/sec_edgar.py`)
- SEC EDGAR company facts (10-K, 10-Q)
- Filing narrative extraction
- CIK → ticker resolution

### 8.4 Yahoo Finance (`tools/yahoo_finance.py`)
- Historical price charts
- Annual/quarterly revenue, net income, margins
- Market cap, PE, PB, dividend yield
- Currency detection

### 8.5 Forecasting (`tools/mcp/forecasting.py`)
- **TimesFM integration:** zero-shot time-series forecasting for revenue projections
- **Anomaly detection:** P10–P90 confidence corridors
- **Fallback:** CAGR-based growth when TimesFM unavailable

---

## 9. Research Quality & Accuracy

### 9.1 Quality Scoring (`analysis/quality.py`)
**10-dimension heuristic score** (max ~100 points):

| Dimension | Weight | Description |
|-----------|--------|-------------|
| `identity` | 8 | Company identification confidence |
| `financials` | 16 | Coverage of revenue, margins, cash flow |
| `history` | 12 | Multi-year historical data availability |
| `filing_narrative` | 10 | SEBI/SEC filing analysis |
| `live_quote` | 6 | Real-time market data freshness |
| `press_coverage` | 10 | News and media coverage depth |
| `web_diversity` | 12 | Number of distinct source domains |
| `citation_tiering` | 10 | Primary vs secondary source ratio |
| `conflicts` | 4 | Cross-source consistency |
| `competitive` | 4 | Peer/competitor analysis coverage |

- **Pass threshold:** `score >= 75.0`
- **Gaps & suggested_queries:** auto-generated follow-ups for missing dimensions

### 9.2 Conflict Detection (`analysis/conflicts.py`)
- Cross-source validation: if Yahoo Finance revenue ≠ SEC revenue, flags conflict with confidence degradation.
- Detects data staleness and unit mismatches.

### 9.3 Verifier (`agents/verifier.py`)
- Post-analysis fact-checking against multiple sources.
- Claims validated via `AccuracyValidator` (`accuracy_validator.py`).
- **Claim structure:**
  ```python
  @dataclass
  class Claim:
      text: str           # "TCS revenue ₹200k Cr"
      source: str         # URL or document
      confidence: float   # 0.0-1.0
      timestamp: datetime
  ```

### 9.4 Blind Spot Detector (`agents/blindspot.py`)
- Detects missing analysis angles.
- Example: no governance data found → suggest board-structure query.

---

## 10. Web Scraping & Search

### 10.1 Search Backends (`tools/web/scraper.py`)
**Tiered fallback:**
1. **DuckDuckGo** — default, no API key
2. **Bing** — secondary web search
3. **Tavily API** — when `TAVILY_API_KEY` is set
4. **SearXNG** — private instance when `FINAGENT_SEARXNG_URL` is set
5. **Playwright Chromium** — for JS-heavy or blocked pages

### 10.2 Browser Pool (`tools/browser/`)
**Playwright Chromium** with async page pool:
- `FINAGENT_BROWSER_FALLBACK=1` — retry failed searches via Chromium
- `FINAGENT_BROWSER_FALLBACK_HTTP=1` — retry failed HTTP fetches via Chromium
- `FINAGENT_BROWSER_MAX_PAGES=3` — cap concurrent rendered pages
- `FINAGENT_FETCH_CONCURRENCY=6` — cap concurrent page fetches
- **Helpers:**
  - `browser_extract(url, selector)` — DOM extraction from allowlisted JS-heavy pages
  - `screenshot_page(url)` — PNG evidence capture

### 10.3 HTTP Fetcher (`tools/web/http_fetcher.py`)
- Shared async `httpx` client with connection pooling
- Automatic User-Agent rotation
- Timeout handling and retry logic
- Connection cleanup on shutdown (`aclose_shared_client()`)

---

## 11. Synthesis & Output

### 11.1 Enrichment Bundle (`synthesis.py`)
Before synthesis, all data is normalized into an `EnrichmentBundle`:
- `india_snap` — NSE/BSE snapshot
- `sebi_filing` — latest SEBI filing
- `shareholding` — promoter/FII/DII breakdown
- `yahoo` — Yahoo Finance quote & history
- `wikipedia` — company overview
- `fx` — USD/INR rate
- `news` — list of `NewsItem`

### 11.2 Memo Generation (`synthesis.py`, ~2,000 lines)
**Currency policy:** All monetary figures in **INR** (crore/lakh notation) first.  
**Source policy:** Every number sourced from NSE/BSE, Moneycontrol, Screener.in, SEBI filings, Yahoo `.NS`/`.BO`, or domestic financial media.  
**LLM:** OpenAI streaming when key available; template-based fallback otherwise.  
**Budget:** `_MEMO_BUDGET_CHARS = 12,000` character limit.

**Memo sections:**
1. Executive Summary
2. Company Overview
3. Financial Analysis
4. Valuation & Fair Value
5. Competitive Landscape
6. Risk Factors
7. Recent News & Events
8. Citations & Sources

### 11.3 Output Formatting (`output/`)
| Module | Purpose |
|--------|---------|
| `output/intent_classifier.py` | Classifies user intent (quick vs deep, entities, depth) |
| `output/artifact_builder.py` | Builds `AnswerArtifact` |
| `output/memo_formatter.py` | Sections: Executive Summary, Financials, Valuation, Risks, Competitive, Citations |
| `output/renderer.py` | `render_markdown()` and `render_rich_json()` for chat widgets |

### 11.4 Rich Builder (`rich_builder.py`, ~92K lines)
Formats responses with:
- Embedded charts (candlestick, line, bar, gauge, donut)
- Data tables
- Citation links
- Contextual cards

---

## 12. Gateway API (FastAPI)

**File:** `finagent/gateway/run.py` (~1,700 lines)

### 12.1 REST Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/chat` | POST | Quick synchronous chat response |
| `/research/deep` | POST | Start deep research job (async background) |
| `/chat/research` | POST | Cloud chat interface — returns poll/SSE/result URLs |
| `/capabilities` | GET | Feature discovery for orchestrators |
| `/health` | GET | Liveness probe |

### 12.2 Job Lifecycle (`/chat/research`)
**Request:**
```json
{
  "target": "TCS",
  "message": "Deep research memo with risks, valuation, and competitors",
  "mode": "standard"
}
```

**Response URLs:**
- `status` — poll for phase/state
- `events` — poll with `?after=N` for replayable history
- `stream` — optional SSE for live UIs
- `result` — fetch final memo when done

### 12.3 Session Persistence
- Events written to `FINAGENT_HOME/sessions/{session_id}/events.jsonl`
- Allows recovery after SSE disconnect or server restart
- For multi-replica cloud: put `FINAGENT_HOME` on shared storage or replace with Redis/object-store adapter

### 12.4 Security & Auth
- **Rate limiting:** `InMemSlidingWindowRateLimiter` (per IP or JWT token)
- **JWT validation:** `Authorization: Bearer <token>`
- **Supabase:** user auth + database backend (`gateway/supabase_client.py`)
- **Email service:** `gateway/email_service.py`

### 12.5 Static HTML Pages
The gateway serves complete standalone UIs:
- `landing.html` — marketing landing
- `login.html` / `signup.html` — auth flows
- `profile.html` — user dashboard
- `settings.html` — configuration
- `widget.html` — embeddable research widget with charts

---

## 13. Frontend Architecture

**Framework:** Next.js 14+ (App Router), React, TypeScript

### 13.1 Location
- `Frontend/app/` — Next.js pages
- `Frontend/app/_components/Charts/` — chart components
- `finagent/gateway/components/Charts/` — additional chart components served by gateway

### 13.2 Chart Components
| Component | Type |
|-----------|------|
| `AreaChart.tsx` | Area / stacked area |
| `BarChart.tsx` | Vertical bar |
| `DonutChart.tsx` | Donut / ring |
| `GaugeChart.tsx` | Radial gauge |
| `MultiSeriesBarChart.tsx` | Grouped/comparison bars |
| `MultiSeriesLineChart.tsx` | Multi-line time series |

### 13.3 Communication
- **Server-Sent Events (SSE)** from `/api/chat/stream` or `/chat/research` stream URL
- Real-time phase updates, agent progress, source badges

### 13.4 UI Panels
- Chat thread with markdown rendering
- Active / planned / completed sub-agent visualization
- Process steps timeline
- Source domain badges (e.g., "nseindia.com", "moneycontrol.com")
- Embedded charts and data tables

---

## 14. Deployment & Infrastructure

### 14.1 Containerization
- **Dockerfile** at repo root
- Python 3.14+ base image
- Installs `requirements-finagent.txt` + Playwright Chromium

### 14.2 CI/CD Pipeline (`.github/workflows/deploy-production.yml`)
```
1. Push to production branch
       ↓
2. GitHub Actions triggered
       ↓
3. Build Docker image
   docker build -t prospektlab-backend:latest .
       ↓
4. Push to AWS ECR
       ↓
5. Update ECS task definition
   aws ecs update-service --cluster prospektlab --service backend
       ↓
6. Fargate pulls image, starts container (port 8080)
       ↓
7. ALB → Route53 → https://api.prospektlab.com
       ↓
8. Slack notification: "Deployment successful!"
       ↓
9. Frontend (AWS Amplify) connects to new backend
```

### 14.3 Buildspecs
- `buildspec.yml` / `buildspec-prod.yml` — AWS CodeBuild
- `amplify-buildspec.yml` — AWS Amplify for frontend

### 14.4 Environment Variables

#### Production (AWS ECS)
```env
# API Keys
OPENAI_API_KEY=sk-proj-...
TAVILY_API_KEY=tvly-...

# MCP Service URLs (internal service discovery)
MCP_NSE_INDIA_URL=http://mcp-nse-service:8001/mcp
MCP_FUNDAMENTALS_URL=http://mcp-fundamentals-service:8002/mcp
MCP_RESEARCH_URL=http://mcp-research-service:8003/mcp
MCP_DOCS_URL=http://mcp-docs-service:8004/mcp
MCP_VALUATION_URL=http://mcp-valuation-service:8005/mcp

# CORS
CORS_ORIGINS=https://app.prospektlab.com

# Frontend
BACKEND_API_URL=https://api.prospektlab.com
```

#### Local Development
```env
OPENAI_API_KEY=sk-proj-...
MCP_NSE_INDIA_URL=http://localhost:8001/mcp
MCP_FUNDAMENTALS_URL=http://localhost:8002/mcp
# ... (same pattern for all MCP URLs)
```

### 14.5 Cloud Chat Interface
Use `/chat/research` when FinAgent runs behind a chat UI. Returns URLs for polling, SSE, and final result retrieval.

---

## 15. Testing & QA

| Test File | Purpose |
|-----------|---------|
| `finagent/tests/` | Pytest suite for agent logic |
| `gateway/test_gateway.py` | API integration tests |
| `gateway/test_security.py` | Auth & bypass tests |
| `tools/web/test_ingestion.py` | Scraper regression tests |
| `tools/web/test_units.py` | Unit conversion tests |

---

## 16. Complete Data Flow Example

**Query:** *"Compare TCS vs Infosys on profit margins"*

```
1. Frontend (Next.js)
   → POST /api/chat
   { "message": "Compare TCS vs Infosys on profit margins", "mode": "research" }

2. Gateway (FastAPI)
   → Intent classifier detects:
     entities: [TCS, Infosys]
     intent: COMPARISON + FUNDAMENTALS

3. Orchestrator (LangGraph-style)
   → Route to Fundamentals Agent (×2 parallel sub-jobs)
     Job A: get TCS margins
     Job B: get Infosys margins

4. MCP Fundamentals Service (:8002)
   → yfinance.fetch("TCS.NS") → profit margins
   → yfinance.fetch("INFY.NS") → profit margins

5. Specialist Agents
   → Competitor agent: peer comparison
   → Valuation agent: relative PE (depends on financials)

6. Analysis Layer
   → Conflict detection: verify margin consistency across Yahoo vs NSE
   → Quality score: 82/100 (passes)

7. Synthesis Layer
   → OpenAI stream (or template fallback)
   → Format in INR, build comparison table, bar chart

8. Response
   → SSE stream to Frontend
   → React re-renders:
     ✓ Text summary
     ✓ Margin comparison table
     ✓ Bar chart (TCS vs Infosys)
     ✓ Source badges (Yahoo Finance, NSE India)
```

---

## 17. Roadmap

| Phase | Timeline | Feature |
|-------|----------|---------|
| **Phase 2** | Q2–Q3 2026 | Broker integration (Zerodha, Angel One, Upstox APIs); portfolio context; personalized risk analysis |
| **Phase 3** | Q3–Q4 2026 | Real-time alerts: price triggers, corporate announcements, earnings surprises, portfolio risk alerts |
| **Phase 4** | Q4 2026+ | Forensic accounting red flags; IPO analysis engine; mutual fund overlap analysis; tax harvesting suggestions |

---

## 18. File Organization

```
PROSPEKTLAB/
│
├── finagent/                          ← Core research engine (Python)
│   ├── run_agent.py                   • 8-phase research pipeline (~2K lines)
│   ├── gateway/
│   │   ├── run.py                     • FastAPI backend + HTML widgets (~1.7K lines)
│   │   ├── email_service.py           • Email notifications
│   │   ├── supabase_client.py         • Supabase auth & DB
│   │   ├── test_gateway.py            • API tests
│   │   ├── test_security.py           • Security tests
│   │   ├── landing.html               • Marketing page
│   │   ├── login.html / signup.html   • Auth flows
│   │   ├── profile.html               • User dashboard
│   │   ├── settings.html              • Configuration UI
│   │   └── widget.html                • Embeddable research widget
│   │
│   ├── api.py                         • API models & entry points
│   ├── cli.py                         • CLI interface
│   ├── events.py                      • Real-time event bus
│   ├── intent.py                      • Query intent classification
│   ├── synthesis.py                   • Memo generation (~2K lines)
│   ├── rich_builder.py                • Rich output formatting (~92K lines)
│   ├── accuracy_validator.py          • Claim validation
│   ├── prompt_builder.py              • LLM prompt construction
│   ├── research_planner.py            • Research plan generation
│   ├── settings.py                    • Configuration
│   ├── paths.py                       • File path utilities
│   │
│   ├── agents/
│   │   ├── base.py                    • Agent base classes
│   │   ├── orchestrator.py            • Wave-based parallel execution
│   │   ├── verifier.py                • Fact-checking agent
│   │   ├── blindspot.py               • Missing-angle detection
│   │   └── specialists/
│   │       ├── accounting.py          • Forensic anomaly detection
│   │       ├── financials.py          • Financial trend analysis
│   │       ├── valuation.py           • DCF & fair value
│   │       ├── competitor.py          • Peer benchmarking
│   │       ├── risk.py                • Risk analysis
│   │       ├── technical.py           • Technical indicators
│   │       ├── news.py                • News sentiment
│   │       ├── governance.py          • ESG & board analysis
│   │       ├── macro.py               • Sector/economy context
│   │       └── community.py           • Social sentiment
│   │
│   ├── analysis/
│   │   ├── quality.py                 • Research quality scoring
│   │   └── conflicts.py               • Cross-source conflict detection
│   │
│   ├── state/
│   │   ├── checkpoint.py              • Session serialization
│   │   ├── citation_log.py            • Source citation tracking
│   │   ├── compression.py             • Context compression
│   │   ├── research_state.py          • SQLite session store
│   │   └── session_context.py         • Runtime session state
│   │
│   ├── memory/
│   │   ├── store.py                   • Long-term SQLite memory (FTS5)
│   │   └── chat_memory.py             • Conversation history
│   │
│   ├── tools/
│   │   ├── data.py                    • Core data models
│   │   ├── scraper.py                 • Web search orchestrator (~48K lines)
│   │   ├── yahoo_finance.py           • Yahoo Finance client
│   │   ├── sec_edgar.py               • US SEC EDGAR client
│   │   ├── india.py                   • NSE/SEBI India client
│   │   ├── sec_filings.py             • SEC filing parser
│   │   ├── forex.py                   • USD/INR rates
│   │   ├── valuation_engine.py        • Deterministic finance math (~35K lines)
│   │   ├── table_parser.py            • HTML table extraction
│   │   ├── hackernews.py              • HN search
│   │   ├── reddit.py                  • Reddit search
│   │   ├── stocktwits.py              • StockTwits sentiment
│   │   ├── wikipedia.py               • Wikipedia summaries
│   │   ├── forecasting.py             • TimesFM projections
│   │   ├── mcp/
│   │   │   ├── mcp_forecasting.py     • MCP forecasting wrapper
│   │   │   └── forecasting.py         • TimesFM integration
│   │   ├── mcp_servers/
│   │   │   ├── nse_server.py          • MCP: NSE India (:8001)
│   │   │   ├── fundamentals_server.py • MCP: Fundamentals (:8002)
│   │   │   ├── research_server.py     • MCP: Research & News (:8003)
│   │   │   ├── docs_server.py         • MCP: Documents & Qdrant (:8004)
│   │   │   └── mcp_valuation.py       • MCP: Valuation (:8005)
│   │   ├── web/
│   │   │   ├── http_fetcher.py        • Async HTTP client
│   │   │   ├── scraper.py             • Search backends
│   │   │   └── table_parser.py        • Table extraction
│   │   ├── browser/
│   │   │   └── (Playwright helpers)   • Chromium pool
│   │   └── social/
│   │       └── viral_verifier.py      • Pump-and-dump detection
│   │
│   ├── output/
│   │   ├── intent_classifier.py       • Output mode classification
│   │   ├── artifact_builder.py        • Response artifact builder
│   │   ├── memo_formatter.py          • Memo section formatter
│   │   ├── renderer.py                • Markdown / JSON renderer
│   │   └── contracts.py               • Output type definitions
│   │
│   ├── geo/
│   │   ├── resolve_entity.py          • Entity resolution
│   │   ├── query_localizer.py         • Query localization
│   │   └── source_policy.py           • Domain preference rules
│   │
│   ├── harness/
│   │   └── (Context management)       • Token budget & compression
│   │
│   ├── playbooks/
│   │   └── (Research playbooks)       • Pre-built research templates
│   │
│   ├── router/
│   │   └── (Query routing)            • Objective routing
│   │
│   ├── retrieval/
│   │   └── (Retrieval plans)          • Document retrieval orchestration
│   │
│   └── tests/
│       └── (Pytest suite)             • Unit & integration tests
│
├── Frontend/                          ← Next.js React UI
│   └── app/
│       └── _components/
│           └── Charts/
│               ├── AreaChart.tsx
│               ├── BarChart.tsx
│               └── ...
│
├── deployment/                        ← AWS deployment configs
│
├── Dockerfile                         ← Container image
├── pyproject.toml                     ← Python project config (3.14+)
├── main.py                            ← Entry stub
│
└── (Architecture documentation)       ← 20+ MD files
    ├── ARCHITECTURE.md
    ├── QUICK_ARCHITECTURE_OVERVIEW.md
    ├── FINAGENT_ARCHITECTURE_BLUEPRINT.md
    ├── ORACLE_FIOS_architecture.md
    ├── PRODUCTION_DEPLOYMENT_GUIDE.md
    └── ...
```

---

## Appendix: Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | OpenAI API key for LLM synthesis |
| `TAVILY_API_KEY` | — | Tavily search API key |
| `MCP_NSE_INDIA_URL` | `http://localhost:8001/mcp` | NSE MCP service URL |
| `MCP_FUNDAMENTALS_URL` | `http://localhost:8002/mcp` | Fundamentals MCP URL |
| `MCP_RESEARCH_URL` | `http://localhost:8003/mcp` | Research MCP URL |
| `MCP_DOCS_URL` | `http://localhost:8004/mcp` | Docs MCP URL |
| `MCP_VALUATION_URL` | `http://localhost:8005/mcp` | Valuation MCP URL |
| `FINAGENT_BROWSER_FALLBACK` | `0` | Retry failed searches via Chromium |
| `FINAGENT_BROWSER_FALLBACK_HTTP` | `0` | Retry failed HTTP via Chromium |
| `FINAGENT_BROWSER_MAX_PAGES` | `3` | Max concurrent browser pages |
| `FINAGENT_FETCH_CONCURRENCY` | `6` | Max concurrent page fetches |
| `FINAGENT_SEARXNG_URL` | — | Private SearXNG instance URL |
| `FINAGENT_DOMAIN_PINNED_QUERIES` | `1` | Enable tier-1 domain-pinned breadth queries |
| `CORS_ORIGINS` | `*` | Allowed CORS origins |
| `BACKEND_API_URL` | — | Frontend backend URL |

---

**ProspektLab 2.0.0** | May 2026 | Financial Intelligence OS for India 🇮🇳📈

# 🔬 ProspektLab Codebase Diagnostic & Detailed Walkthrough

**Date:** May 21, 2026  
**Repository:** https://github.com/K-u-s-h-gupta/Prospektlab_intelligence  
**Branch:** production  
**Version:** 2.0.0 (FinAgent Era)

---

## 📋 Executive Summary

**ProspektLab** is a **conversational Financial Intelligence Operating System** for the Indian equity market. It comprises three main technical layers:

1. **Frontend** — Next.js React UI (investor-facing chat interface)
2. **Backend** — FastAPI + LangGraph (ORACLE FIOS chat engine)
3. **FinAgent** — Advanced autonomous research subsystem (long-form analysis engine)

The codebase is **Python-centric** (FastAPI, LangGraph, LangChain, Anthropic Claude) with a **Next.js frontend**. It integrates with **5 Model Context Protocol (MCP) microservices** for domain-specific data (NSE, fundamentals, research, docs, valuation) and uses **AWS ECS/Fargate** for production deployment.

---

## 🏗️ System Architecture Overview

### High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                   │
│                  app/ _components/ page.tsx                 │
│                   (Chat UI + Widget Framework)              │
└────────────────┬────────────────────────────────────────────┘
				 │ HTTPS
				 ▼
┌─────────────────────────────────────────────────────────────┐
│               Backend API Layer (FastAPI)                   │
│                                                             │
│  ┌──────────────────┐  ┌──────────────────────────────────┐ │
│  │   Backend/api.py │  │  finagent/api.py (merged)        │ │
│  │  - CORS config   │  │  - Real agent loop integration   │ │
│  │  - Chat endpoint │  │  - Output modes (chat|standard   │ │
│  │  - Error handle  │  │    |deep|marathon)               │ │
│  └────────┬─────────┘  └──────────┬───────────────────────┘ │
│           │                       │                         │
│  ┌────────▼───────────────────────▼───────────┐            │
│  │  Backend/graph.py (LangGraph supervision)  │            │
│  │  - Main research graph orchestration       │            │
│  │  - Node supervision & routing              │            │
│  │  - State management                        │            │
│  │  - Agent coordination                      │            │
│  └──────────────────┬──────────────────────────┘            │
│                     │                                       │
│  ┌──────────────────▼──────────────────┐                   │
│  │ finagent/ (Autonomous Research)    │                   │
│  │                                    │                   │
│  │ ┌─ run_agent.py (pipeline)        │                   │
│  │ ├─ agents/* (orchestrator, etc)   │                   │
│  │ ├─ analysis/* (conflicts, quality)│                   │
│  │ ├─ tools/* (data, web, MCP)       │                   │
│  │ ├─ memory/* (long-term store)     │                   │
│  │ ├─ state/* (checkpointing)        │                   │
│  │ └─ synthesis.py (memo generation) │                   │
│  └─────────────────┬──────────────────┘                   │
│                    │                                       │
└────────────────────┼───────────────────────────────────────┘
					 │
		┌────────────┼────────────┐
		│            │            │
		▼            ▼            ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ MCP NSE      │ │ MCP Fund.    │ │ MCP Research │
│ Port 8001    │ │ Port 8002    │ │ Port 8003    │
└──────────────┘ └──────────────┘ └──────────────┘
						│
						▼
		┌───────────────────────────────────┐
		│  External Data Sources            │
		│                                   │
		│  - NSE API (live prices)          │
		│  - SEC EDGAR (US financials)      │
		│  - Yahoo Finance                  │
		│  - Wikipedia                      │
		│  - DuckDuckGo (search)            │
		│  - Reddit, HackerNews, StockTwits │
		│  - News aggregators               │
		└───────────────────────────────────┘
```

---

## 📁 Directory Structure & Package Map

```
PROSPEKTLAB/
│
├── Frontend/                          # Next.js React frontend
│   ├── app/                          # App router (Next.js 13+)
│   │   ├── page.tsx                  # Main chat interface
│   │   ├── layout.tsx                # Root layout
│   │   └── _components/              # Reusable React components
│   │       ├── Charts/               # Chart components
│   │       ├── ...
│   └── package.json                  # Node dependencies
│
├── Backend/                           # Legacy ORACLE API layer
│   ├── api.py                        # FastAPI main entry (703 lines)
│   │   └── Key endpoints: /api/chat (streaming), /api/agents
│   ├── graph.py                      # LangGraph supervision engine
│   ├── intent.py                     # Query intent classification
│   ├── rich_builder.py               # Rich output formatting
│   ├── mcp_config.py                 # MCP server configuration
│   └── tests/
│       └── test_rich_builder.py
│
├── finagent/                          # ✨ Autonomous research engine (NEW)
│   │
│   ├── run_agent.py                  # Core 8-phase research pipeline (2000 lines)
│   │   ├─ Phase 1: Identify (entity resolution)
│   │   ├─ Phase 2: Enrichment (parallel API pulls)
│   │   ├─ Phase 3: Breadth Survey (layered search)
│   │   ├─ Phase 4: Deep Dive (gap-filling queries)
│   │   ├─ Phase 5: Analysis (conflict detection)
│   │   ├─ Phase 6: Synthesis (memo generation)
│   │   ├─ Phase 7: Verification (verifier pass)
│   │   └─ Phase 8: Blind Spot Expansion
│   │
│   ├── api.py                        # FastAPI merged backend (152 lines)
│   │   ├─ /api/chat - Standard JSON endpoint
│   │   ├─ /api/stream - SSE streaming endpoint
│   │   └─ /api/session/{session_id} - Progress tracking
│   │
│   ├── gateway/                      # Standalone FastAPI gateway
│   │   ├── run.py                    # Main gateway (1657 lines)
│   │   │   ├─ Session management
│   │   ├─ events.py                  # In-process session bus (SSE)
│   │   ├─ widget.html                # Embeddable widget HTML
│   │   └── supabase_client.py        # Auth integration
│   │
│   ├── agents/                       # Multi-agent orchestration
│   │   ├── __init__.py
│   │   ├── base.py                   # BaseAgent class (LangChain agent)
│   │   ├── orchestrator.py           # Orchestrator agent (coordinator)
│   │   ├── verifier.py               # Verifier agent (fact-checking)
│   │   ├── blindspot.py              # Blind spot detection
│   │   └── specialists/              # Specialist subagents
│   │       ├── accounting.py
│   │       ├── competitive.py
│   │       ├── governance.py
│   │       └── ...
│   │
│   ├── analysis/                     # Post-research analysis
│   │   ├── conflicts.py              # Multi-source conflict detection
│   │   ├── quality.py                # Research quality scoring
│   │   └── __init__.py
│   │
│   ├── tools/                        # Data & tool integration layer
│   │   ├── data.py                   # Data models (IndiaCompanySnapshot, etc)
│   │   ├── web/                      # Web scraping & search
│   │   │   ├── scraper.py            # search_layered(), ScrapedDoc
│   │   │   ├── http_fetcher.py       # httpx client management
│   │   │   └── ...
│   │   ├── mcp/                      # MCP tool definitions
│   │   │   ├── nse_india.py          # NSE MCP integration
│   │   │   ├── fundamentals.py       # Fundamentals MCP
│   │   │   ├── research.py           # Research MCP
│   │   │   ├── dynamic_loader.py     # MCP discovery (stub)
│   │   │   └── ...
│   │   ├── social/                   # Social sentiment tools
│   │   │   ├── reddit.py
│   │   │   ├── hackernews.py
│   │   │   └── viral_verifier.py     # Pump & dump detection
│   │   └── data_sources/
│   │       ├── sec.py                # SEC EDGAR integration
│   │       ├── yahoo_finance.py
│   │       └── wikipedia.py
│   │
│   ├── memory/                       # Long-term memory store
│   │   ├── store.py                  # MemoryStore class (persistence)
│   │   ├── chat_memory.py            # ChatMemoryManager (conversation history)
│   │   └── fact_db.py                # Fact database
│   │
│   ├── state/                        # State management & checkpointing
│   │   ├── checkpoint.py             # Checkpoint & StepResult dataclasses
│   │   ├── citation_log.py           # Citation tracking
│   │   └── ...
│   │
│   ├── retrieval/                    # Retrieval planning
│   │   ├── __init__.py               # build_retrieval_plan()
│   │   └── ...
│   │
│   ├── router/                       # Query routing logic
│   │   ├── __init__.py               # route_objective()
│   │   └── ...
│   │
│   ├── synthesis/                    # Memo & report generation
│   │   └── __init__.py               # synthesize_memo()
│   │
│   ├── prompts/                      # Prompt templates
│   │   ├── system.txt                # System prompts
│   │   ├── research.txt
│   │   └── ...
│   │
│   ├── geo/                          # Entity resolution & localization
│   │   ├── entity_resolver.py        # resolve_entity()
│   │   ├── query_localizer.py        # localize_search_query()
│   │   └── source_policy.py          # preferred_domains_for_entity()
│   │
│   ├── harness/                      # Context compression & management
│   │   ├── __init__.py               # Harness, HarnessConfig
│   │   └── context_manager.py        # should_compress()
│   │
│   ├── memory/                       # Memory subsystem (also in tools/)
│   │   ├── store.py                  # Persistent memory store
│   │   └── chat_memory.py            # Chat history
│   │
│   ├── output/                       # Output classification
│   │   ├── intent_classifier.py      # classify_output_mode()
│   │   └── ...
│   │
│   ├── playbooks/                    # Query playbooks (reusable patterns)
│   │   ├── __init__.py               # apply_playbook_to_queries()
│   │   └── ...
│   │
│   ├── prospektlab_adapter/          # Host adapter (stub)
│   │   └── plugin.py
│   │
│   ├── accuracy_validator.py         # Claim & Source tracking
│   ├── cli.py                        # CLI entry point
│   ├── __main__.py                   # python -m finagent
│   ├── .env.example                  # Environment template
│   ├── requirements-finagent.txt     # Python dependencies
│   └── tests/
│       └── test_*.py                 # Unit tests
│
├── deployment/                        # Deployment configurations
│   ├── deploy-backend.ps1            # PowerShell deploy script
│   ├── deploy_frontend.py            # Python frontend deploy
│   ├── fargate-backend.yml           # AWS Fargate task definition
│   ├── zip_backend.py                # Lambda packaging
│   └── ...
│
├── .github/workflows/                 # CI/CD workflows
│   ├── deploy-production.yml
│   └── ...
│
├── Documentation/                     # Architecture & deployment docs
│   ├── FINAGENT_ARCHITECTURE_BLUEPRINT.md
│   ├── ORACLE_FIOS_architecture.md
│   ├── ORACLE_Phase1_Architecture_Guide.md
│   ├── DEPLOYMENT-COMPLETE.md
│   ├── PRODUCTION_DEPLOYMENT_GUIDE.md
│   ├── PRE-DEPLOYMENT-CHECKLIST.md
│   ├── INDEX.md                      # Master index
│   └── ... (15+ docs)
│
├── Dockerfile                         # Docker image for finagent gateway
├── README.md                          # Project root README (if exists)
└── PROSPEKTLAB.slnx                   # Visual Studio solution file

```

---

## 🔑 Core Components Deep Dive

### 1. **Frontend** (`Frontend/app/`)
**Technology:** Next.js 13+ (React, TypeScript)  
**Purpose:** Investor-facing conversational chat interface

**Key Components:**
- `page.tsx` — Main chat interface
  - Message input & send button
  - Streaming message display
  - Agent visualization (which agents are running)
  - Rich output rendering (charts, tables, memos)
- `_components/` — Reusable React components
  - Charts (candlestick, line graphs)
  - Table views for financials
  - Memo renderers
- `layout.tsx` — Root layout with global styling

**API Integration:**
```typescript
// Frontend → Backend
POST /api/chat (or /stream)
{
  message: "Compare Infosys vs TCS",
  mode: "research|marathon",
  response_depth?: "deep|standard|chat|marathon"
}

// Response (SSE or JSON)
{
  reply: "...",
  agents_used: ["nse_agent", "fundamentals_agent"],
  rich: { charts: [...], tables: [...] }
}
```

**Environment:**
```env
BACKEND_API_URL=http://localhost:8000
NEXT_PUBLIC_API_BASE=https://api.prospektlab.com
```

---

### 2. **Backend API Layer** (`Backend/api.py` + `finagent/api.py`)

#### **Backend/api.py** (ORACLE FIOS) — 703 lines
**Purpose:** Legacy FastAPI wrapper over LangGraph

**Key Exports:**
- `FastAPI app` instance
- CORS middleware config
- `/api/chat` — POST streaming endpoint

**Responsibilities:**
1. CORS origin configuration (environment-driven)
2. Request validation (ChatRequest: message + mode)
3. Graph lifecycle management (_graph, _graph_lock)
4. Error handling (OpenAI auth, rate limits, timeouts)
5. Agent availability tracking
6. Server health checks

**Key Constants:**
```python
GRAPH_RUN_TIMEOUT_SECONDS = 240
GRAPH_IDLE_TIMEOUT_SECONDS = 90
GRAPH_REBUILD_COOLDOWN_SECONDS = 5
AGENT_SERVER_DEPENDENCIES = {...}  # From intent.py
```

**Core Endpoint:**
```python
@app.post("/api/chat")
async def chat(req: ChatRequest) -> ChatResponse:
	# Stream from LangGraph via Backend/graph.py
	async for chunk in _stream_graph(req.message, req.mode):
		yield json.dumps(chunk)
```

---

#### **finagent/api.py** (Merged Runtime) — 152 lines
**Purpose:** Modern FastAPI with real agent loop integration

**Key Exports:**
- `FastAPI app` instance (FinAgent API, v2.0.0)
- `/api/chat` — Standard JSON endpoint
- `/api/stream` — SSE streaming endpoint

**Request/Response Models:**
```python
class ChatRequest(BaseModel):
	message: str
	response_depth: str = "deep"  # chat | standard | deep | marathon

class ChatResponse(BaseModel):
	reply: str
	agents_used: list[str]
	rich: dict[str, Any] | None
	output_mode: str | None
	response_depth: str | None
```

**Key Difference from Backend/api.py:**
- Integrates directly with `finagent/run_agent.py`
- Supports response depth modes (research intensity)
- Output mode classification
- Chat history context window

---

### 3. **LangGraph Orchestration** (`Backend/graph.py`)
**Purpose:** Manages multi-agent supervision and routing

**Not fully detailed in this walkthrough, but includes:**
- Agent node definitions (for each MCP service)
- Routing logic (supervisor node decides which agent to invoke)
- State management (persistent conversation state)
- Fallback chains (if one agent fails, invoke alternative)

---

### 4. **FinAgent Autonomous Research Engine** (`finagent/`)

#### **Core Research Pipeline** (`finagent/run_agent.py` — 2000 lines)

**Purpose:** Orchestrate an 8-phase research workflow for deep company analysis

**8-Phase Pipeline:**

1. **Identify** — Entity resolution
   - Input: Query (e.g., "Reliance Industries")
   - Output: Resolved entity (ticker, CIK, legal name)
   - Tools: `finagent.geo.entity_resolver`

2. **Enrichment** — Parallel authoritative API pulls
   - SEC EDGAR company facts (US)
   - Yahoo Finance historical pricing
   - Wikipedia company summary
   - NSE/BSE snapshot (India)
   - Runs in parallel for speed

3. **Breadth Survey** — Layered DuckDuckGo search
   - Query 1: "{company} fundamentals"
   - Query 2: "{company} revenue growth"
   - Query 3: "{company} competitors"
   - Query 4: "{company} recent news"
   - Scrapes top 5 results per query

4. **Deep Dive** — Gap-filling iterative search
   - Analyzes breadth survey results
   - Identifies knowledge gaps
   - Performs targeted second-pass queries
   - Example: "If no debt info found, search '{company} debt leverage'"

5. **Analysis** — Multi-source conflict detection
   - Scores data conflicts (e.g., revenue discrepancies)
   - Detects pump-and-dump social signals
   - Quality scoring of research
   - Tools: `finagent.analysis.conflicts`, `finagent.analysis.quality`

6. **Specialist Multi-Agent Analysis** — Role-based experts
   - Accounting specialist (forensic analysis)
   - Competitive positioning specialist
   - Governance & management quality specialist
   - Valuation specialist
   - Each runs in parallel

7. **Verification** — Verifier agent fact-check pass
   - Cross-checks all claims
   - Validates math (ratios, valuations)
   - Flags unverifiable claims
   - Tools: `finagent.agents.verifier`

8. **Synthesis** — Generate memo
   - Templates + data → markdown memo
   - Includes citations & sources
   - Stores in ~/.finagent/memos/
   - Tools: `finagent.synthesis.synthesize_memo`

**Key Dataclasses:**
```python
@dataclass
class AgentLoopConfig:
	target: str                    # Entity to research
	query: str                     # Original user query
	depth: Literal["chat"|"standard"|"deep"|"marathon"]
	output_mode: str               # Output format

@dataclass
class Checkpoint:
	phase: str
	timestamp: datetime
	result: StepResult
	memo_draft: str | None
	memory_facts: list[MemoryFact]
```

**Error Handling:**
- Graceful degradation if MCP service down
- Fallback to web search if API fails
- Timeout handling (240s max per research session)

---

#### **Multi-Agent Orchestration** (`finagent/agents/`)

**BaseAgent** (`agents/base.py`)
- Abstract LangChain agent
- Tool invocation framework
- Callback handling
- Inheritors: Orchestrator, Verifier, specialists

**Orchestrator** (`agents/orchestrator.py`)
- Coordinates specialist agents
- Decides which agents to invoke based on query
- Aggregates results

**Verifier** (`agents/verifier.py`)
- Fact-checks claims extracted from sources
- Validates math/calculations
- Generates verification report

**Specialists** (`agents/specialists/`)
- `accounting.py` — Forensic accounting, red flags
- `competitive.py` — Competitive positioning, SWOT
- `governance.py` — Management quality, board analysis
- `valuation.py` — DCF, comparables, fair value
- `market.py` — Sector trends, market positioning

---

#### **Data Integration** (`finagent/tools/`)

**Data Models** (`tools/data.py`)
```python
@dataclass
class IndiaCompanySnapshot:
	ticker: str
	company_name: str
	sector: str
	market_cap: float
	pe_ratio: float
	roe: float
	# ... 50+ fields

@dataclass
class SECCompanySnapshot:
	cik: str
	ticker: str
	legal_name: str
	fiscal_year: int
	revenues: float
	net_income: float
	# ... 100+ fields

@dataclass
class NewsItem:
	headline: str
	source: str
	url: str
	timestamp: datetime
	sentiment: str  # positive | neutral | negative
```

**Web Scraping** (`tools/web/scraper.py`)
```python
async def search_layered(
	query: str,
	angles: list[str],  # ["fundamentals", "growth", "competitors", "news"]
	depth: int = 5      # results per angle
) -> list[ScrapedDoc]:
	"""Multi-angle search with DuckDuckGo + HTML scraping"""
	# Returns list of { url, text, structured_data }
```

**MCP Integration** (`tools/mcp/`)
- `nse_india.py` — NSE MCP client (price, volume, fundamentals)
- `fundamentals.py` — Fundamentals MCP client
- `research.py` — Research MCP client
- Handles MCP protocol: LLM → tool call → MCP → JSON response

**External Data** (`tools/data_sources/`)
- `sec.py` — SEC EDGAR API (US companies)
- `yahoo_finance.py` — Yahoo Finance (prices, history)
- `wikipedia.py` — Wikipedia REST API (company summaries)

---

#### **Memory Subsystem** (`finagent/memory/`)

**MemoryStore** (`memory/store.py`)
```python
class MemoryStore:
	async def recall(target: str, query: str) -> list[MemoryFact]:
		"""Retrieve cached facts about target"""

	async def store(fact: MemoryFact) -> None:
		"""Persist fact for future recall"""

	async def forget(target: str, older_than: timedelta) -> None:
		"""Prune old facts"""

@dataclass
class MemoryFact:
	target: str           # Entity researched
	claim: str            # "TCS revenue ₹200k Cr"
	source: str           # URL or document
	confidence: float     # 0.0-1.0
	timestamp: datetime
```

**Chat Memory** (`memory/chat_memory.py`)
```python
class ChatMemoryManager:
	async def add_message(user_id: str, message: str, role: str) -> None
	async def get_context(user_id: str, last_n: int = 10) -> str
```

**Storage Backend:** Filesystem (~/.finagent/memory/) + optional Supabase

---

#### **Output & Classification** (`finagent/output/`)

**Intent Classifier** (`output/intent_classifier.py`)
```python
def classify_output_mode(query: str) -> str:
	"""Classify as: chart | narrative | calculation | comparison"""

def normalize_depth(depth: str) -> str:
	"""Normalize to: chat | standard | deep | marathon"""

def extract_finance_entities(query: str) -> list[str]:
	"""Extract tickers, entity names from query"""
```

---

### 5. **Gateway** (`finagent/gateway/run.py` — 1657 lines)

**Purpose:** Standalone FastAPI server for long-running research sessions

**Session Management:**
```python
class SessionManager:
	def create_session() -> str  # Returns session_id (UUID)
	async def get_session(session_id: str) -> Session
	async def push_event(session_id: str, event: str) -> None
	async def close_session(session_id: str) -> None
```

**Endpoints:**
- `POST /api/research` — Start new research session
- `GET /api/session/{session_id}/events` — SSE stream of events
- `GET /api/session/{session_id}/status` — Get session status
- `GET /gateway` — Embedded widget HTML
- `GET /` — Gateway homepage

**Event Flow (SSE):**
```
Client connects → GET /api/session/{id}/events
	↓
Server streams events:
	event: phase_start
	data: {"phase": "enrichment", "progress": 15}

	event: phase_complete
	data: {"phase": "enrichment", "result": {...}}

	event: research_complete
	data: {"memo": "...", "citations": [...]}
```

**Rate Limiting:**
```python
class InMemSlidingWindowRateLimiter:
	def __init__(self, requests_limit: int = 100, window_seconds: int = 60)
```

---

## 🔗 Data Flow & Integration Patterns

### Chat Request Flow (ORACLE)

```
Frontend User Message
		↓
POST /api/chat (Backend/api.py)
		↓
LangGraph orchestration (Backend/graph.py)
		↓
Supervisor node decides: Which agent? (intent.py)
		↓
Agent node invokes:
   - If NSE agent: call MCP NSE service (port 8001)
   - If Fundamentals: call MCP Fundamentals (port 8002)
   - If Research: call MCP Research (port 8003)
		↓
MCP service returns JSON data
		↓
LangChain agent processes response
		↓
Supervisor node checks: More agents needed? Or done?
		↓
If done: synthesize_memo(collected_data) → rich formatting (rich_builder.py)
		↓
ChatResponse streamed back to Frontend
		↓
Frontend renders agents_used + reply + rich output
```

### Deep Research Flow (FinAgent)

```
User requests deep analysis via finagent/gateway
		↓
POST /api/research
		↓
run_research_session(query, depth="deep")
		↓
Phase 1-8 executed sequentially (see above)
		↓
For each phase:
   - Emit SSE event to connected clients
   - Update checkpoint in state/
   - Store progress in memory/
		↓
Phase 8: synthesize_memo() → ~/.finagent/memos/{session_id}.md
		↓
SSE event: research_complete with memo URL
		↓
Client receives event and displays memo
```

---

## 🛠️ Technology Stack

### Backend Stack
| Layer | Technology | Purpose |
|-------|-----------|---------|
| **API Framework** | FastAPI 0.100+ | REST API, SSE streaming |
| **LLM Orchestration** | LangGraph 0.1+ | Multi-agent supervision, state management |
| **LLM Library** | LangChain 0.1+ | Agent framework, tool calling, chains |
| **LLM Provider** | Anthropic Claude 3.x (via API) | Core reasoning engine |
| **Web Framework** | AsyncIO, httpx | Async request handling, parallel execution |
| **HTML/CSS** | FastAPI + Jinja2 | Gateway widget templates |

### Data & Integration
| Component | Technology | Purpose |
|-----------|-----------|---------|
| **MCP Integration** | Model Context Protocol (JSON-RPC) | Microservice integration for NSE, fundamentals, research, docs, valuation |
| **Web Scraping** | httpx + BeautifulSoup/Parsel | DuckDuckGo search result scraping |
| **External APIs** | httpx (async) | SEC EDGAR, Yahoo Finance, Wikipedia, news feeds |
| **Caching** | In-memory dict + file store | Session state, memory facts, checkpoints |

### Frontend Stack
| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Framework** | Next.js 13+ | React SSR, API routes, deployment |
| **UI Components** | React, TypeScript | Chat UI, charts, tables, memo renderer |
| **Styling** | TailwindCSS (assumed) | Component styling |
| **Streaming** | Server-Sent Events (SSE) | Real-time message and event display |

### Infrastructure
| Component | Service | Purpose |
|-----------|---------|---------|
| **Container** | Docker | Package finagent gateway |
| **Orchestration** | AWS ECS/Fargate | Run containerized app |
| **Task Definition** | AWS CloudFormation or Fargate UI | Define container, CPU, memory, environment |
| **Load Balancer** | AWS ALB | Route traffic, SSL termination |
| **Domain** | AWS Route53 | DNS routing |
| **CI/CD** | GitHub Actions | Automated deployment on push |
| **Auth** | Supabase (JWT) | Optional user authentication |

---

## 📊 MCP Microservices Architecture

The backend depends on **5 MCP microservices** running separately:

| MCP Service | Port | Purpose | Data Provided |
|---|---|---|---|
| **NSE India** | 8001 | Stock prices, volumes, OHLC | Live market data for NSE/BSE |
| **Fundamentals** | 8002 | Company financials, ratios | P/E, ROE, debt, equity, etc. |
| **Research** | 8003 | Company research reports | Analyst reports, recommendations |
| **Docs** | 8004 | Company documents | Filings, announcements, presentations |
| **Valuation** | 8005 | Valuation models | DCF, comparables, fair value estimates |

**Integration Pattern:**
```python
# In finagent/tools/mcp/nse_india.py
async def get_company_price(ticker: str) -> float:
	# Call MCP NSE service
	response = await mcp_client.call_tool(
		server_url="http://mcp-nse-service:8001/mcp",
		tool_name="get_price",
		arguments={"ticker": ticker}
	)
	return response["price"]
```

**Environment Variables:**
```env
MCP_NSE_INDIA_URL=http://mcp-nse-service:8001/mcp
MCP_FUNDAMENTALS_URL=http://mcp-fundamentals-service:8002/mcp
MCP_RESEARCH_URL=http://mcp-research-service:8003/mcp
MCP_DOCS_URL=http://mcp-docs-service:8004/mcp
MCP_VALUATION_URL=http://mcp-valuation-service:8005/mcp
```

---

## 🚀 Deployment Architecture

### Docker Image Build
```dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install -r finagent/requirements-finagent.txt
COPY finagent/ ./finagent/
EXPOSE 8080
CMD ["uvicorn", "finagent.gateway.run:app", "--host", "0.0.0.0", "--port", "8080"]
```

### AWS ECS Task Definition (fargate-backend.yml)
```yaml
cpu: 2048                # 2 vCPU
memory: 4096             # 4 GB
containerPort: 8080
environment:
  OPENAI_API_KEY: ***
  MCP_NSE_INDIA_URL: http://mcp-nse:8001/mcp
  # ... 4 more MCP URLs
  CORS_ORIGINS: https://app.amplifyapp.com
logging:
  awslogs-group: /ecs/prospektlab-backend
  awslogs-stream-prefix: ecs
```

### CI/CD Pipeline (.github/workflows/)
```yaml
# deploy-production.yml
trigger: push to production branch
steps:
  1. Build Docker image
  2. Push to AWS ECR
  3. Update ECS task definition
  4. Deploy to Fargate
  5. Run smoke tests
  6. Send Slack notification
```

---

## 🔐 Configuration & Environment

### Required Environment Variables

**OPENAI_API_KEY** (Backend)
- OpenAI API key for Claude model calls
- Location: ECS task definition

**CORS_ORIGINS** (Backend)
- Comma-separated list of allowed CORS origins
- Example: `https://app.amplifyapp.com,http://localhost:3000`
- Default: Localhost (dev only)

**MCP URLs** (Backend → MCP Services)
```env
MCP_NSE_INDIA_URL=http://mcp-nse-service:8001/mcp
MCP_FUNDAMENTALS_URL=http://mcp-fundamentals-service:8002/mcp
MCP_RESEARCH_URL=http://mcp-research-service:8003/mcp
MCP_DOCS_URL=http://mcp-docs-service:8004/mcp
MCP_VALUATION_URL=http://mcp-valuation-service:8005/mcp
```

**Frontend Configuration**
```env
BACKEND_API_URL=https://api.prospektlab.com
NEXT_PUBLIC_API_BASE=https://api.prospektlab.com
```

### Local Development (.env)
```env
OPENAI_API_KEY=sk-proj-...
MCP_NSE_INDIA_URL=http://localhost:8001/mcp
# ... etc
```

---

## 📈 Performance & Scalability Considerations

### Timeout Configuration
```python
GRAPH_RUN_TIMEOUT_SECONDS = 240      # 4 minutes max for graph
GRAPH_IDLE_TIMEOUT_SECONDS = 90      # 90 seconds idle threshold
GRAPH_REBUILD_COOLDOWN_SECONDS = 5   # Rebuild delay after fail
```

### Concurrency Model
- **Frontend:** SSE (Server-Sent Events) for real-time updates
- **Backend:** AsyncIO for non-blocking I/O
  - Parallel phase execution in finagent (enrichment, search, MCP calls)
  - httpx for concurrent HTTP requests
- **MCP:** HTTP endpoints (can be load-balanced)

### Memory Management
- In-memory session storage (can upgrade to Redis)
- Checkpoint files stored to disk (~/.finagent/state/)
- Memory facts persisted to memory store

### Scaling Strategy (AWS)
1. **Vertical:** Increase ECS task CPU/memory
2. **Horizontal:** Auto-scaling group with ALB
3. **Caching:** Add Redis for session storage, MCP response caching
4. **CDN:** CloudFront for static assets (frontend)

---

## 🧪 Testing Strategy

### Test Structure
```
finagent/tests/
├── test_run_agent.py          # Unit tests for research pipeline
├── test_agents.py              # Multi-agent tests
├── test_memory.py              # Memory store tests
├── test_synthesis.py           # Memo generation tests
└── test_mcp_integration.py     # MCP integration tests

Backend/tests/
└── test_rich_builder.py        # Rich output formatting tests
```

### Testing Approach
- **Unit tests:** Individual modules (tools, agents, analysis)
- **Integration tests:** End-to-end research session
- **Fixture tests:** Pre-recorded API responses (no live API calls in CI)

---

## 🔍 Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| **Python for backend** | LangChain, LangGraph ecosystem; LLM-native |
| **AsyncIO** | High concurrency for parallel research phases |
| **MCP for data** | Decoupled microservices, easy to scale/swap |
| **FastAPI** | Modern, async-native, auto-generated OpenAPI docs |
| **Next.js frontend** | SSR, API routes, Vercel deployment |
| **Session-based FinAgent** | Long-running research ≠ quick chat |
| **Checkpointing** | Resume research if interrupted; audit trail |
| **Memory store** | Persistent recall of past research |
| **Verification pass** | Reduce hallucinations, improve accuracy |

---

## ⚠️ Known Limitations & Future Work

### Current Limitations
1. **FinAgent not integrated into live app** — Runs as separate gateway, not called by Frontend
2. **MCP dynamic discovery stub** — Currently hardcoded MCP URLs, should auto-discover
3. **Memory recall** — Basic keyword matching; could use RAG/embeddings
4. **No real-time alerts** — Alert engine designed but not deployed
5. **Portfolio integration stub** — Broker connection (Zerodha API) not implemented
6. **Multi-user state** — Session-based; no per-user workspace yet

### Roadmap (from ORACLE_FIOS_architecture.md)
1. **Phase 2 (Months 4-6):** Broker integration (Zerodha, Angel One, Upstox)
2. **Phase 3 (Months 5-7):** Alerts & monitoring (real-time price, news, earnings)
3. **Phase 4 (Months 8-12):** Advanced intelligence (forensic accounting, IPO analysis)

---

## 🎯 Getting Started: Key Entry Points

### For Developers

**Run Frontend Locally:**
```bash
cd Frontend
npm install
npm run dev  # http://localhost:3000
```

**Run Backend Locally:**
```bash
cd Backend
pip install -r requirements.txt
python -m uvicorn api:app --reload  # http://localhost:8000
```

**Run FinAgent Gateway:**
```bash
cd finagent
pip install -r requirements-finagent.txt
python -m uvicorn gateway.run:app --reload  # http://localhost:8000/gateway
```

**Run FinAgent CLI:**
```bash
cd finagent
python -m finagent --query "Analyze TCS" --depth deep
```

### For DevOps

**Build Docker Image:**
```bash
docker build -t prospektlab-backend:latest .
```

**Deploy to AWS Fargate:**
```bash
# Authenticate
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# Tag image
docker tag prospektlab-backend:latest <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/prospektlab-backend:latest

# Push
docker push <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/prospektlab-backend:latest

# Update task definition & deploy
aws ecs update-service --cluster prospektlab --service backend --force-new-deployment
```

---

## 📚 Documentation Map

All architecture & deployment docs are in the root directory:

| Document | Purpose | Read Time |
|----------|---------|-----------|
| **FINAGENT_ARCHITECTURE_BLUEPRINT.md** | FinAgent internals | 30 min |
| **ORACLE_FIOS_architecture.md** | Product vision & market fit | 45 min |
| **ORACLE_Phase1_Architecture_Guide.md** | Phase 1 feature set | 40 min |
| **PRODUCTION_DEPLOYMENT_GUIDE.md** | Deployment walkthrough | 30 min |
| **PRE-DEPLOYMENT-CHECKLIST.md** | Pre-flight checklist | 20 min |
| **INDEX.md** | Master documentation index | 5 min |

---

## 🔗 Repository Structure Summary

```
✅ Frontend (Production-Ready)
   - Next.js chat UI
   - Real-time streaming display
   - Rich output rendering

✅ Backend/ORACLE (Production-Ready)
   - FastAPI chat endpoint
   - LangGraph multi-agent orchestration
   - MCP service integration

🚀 FinAgent (New, Autonomous Research)
   - 8-phase research pipeline
   - Multi-agent orchestration
   - Long-term memory
   - Gateway API (standalone)
   - NOT YET INTEGRATED into Frontend

📦 MCP Microservices
   - 5 independent services
   - Data providers (NSE, fundamentals, research, docs, valuation)
   - Easy to scale/replace

☁️ Deployment (AWS)
   - Docker containerization
   - ECS/Fargate orchestration
   - GitHub Actions CI/CD
   - Production-ready

📖 Documentation (15+ docs)
   - Architecture blueprints
   - Deployment guides
   - Verification checklists
```

---

## 🎓 Conclusion

**ProspektLab** is a sophisticated, multi-layered financial intelligence platform:

1. **Conversational AI** for quick answers (ORACLE FIOS in Backend/)
2. **Deep Research Engine** for thorough analysis (FinAgent in finagent/)
3. **Microservice Architecture** for scalability and resilience (MCP services)
4. **Production-Ready** deployment pipeline (AWS + GitHub Actions)

The codebase is well-architected, documented, and ready for scaling. The main integration opportunity is to connect FinAgent's deep research capabilities into the live frontend for users who want more thorough analysis.

---

**Last Updated:** May 21, 2026  
**Version:** 2.0.0 (FinAgent Era)  
**Repository:** https://github.com/K-u-s-h-gupta/Prospektlab_intelligence


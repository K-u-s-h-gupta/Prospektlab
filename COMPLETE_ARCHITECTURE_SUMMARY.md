# 🏗️ ProspektLab Complete Architecture Summary

**Version:** 2.0.0 (FinAgent Era)  
**Last Updated:** May 21, 2026  
**Purpose:** Complete system architecture overview in one document

---

## 📐 System Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                                   Users                                        │
│                          (Web Browser / Mobile)                                │
└────────────────────┬─────────────────────────────────────────────────────────────┘
					 │ HTTPS (REST API + SSE)
					 ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                          PRESENTATION LAYER                                    │
│                                                                                │
│                    Frontend (AWS Amplify - Next.js)                           │
│                    ├─ App Router (app/page.tsx)                               │
│                    ├─ Chat Interface Component                                │
│                    ├─ Message Streaming (SSE)                                │
│                    ├─ Rich Output Rendering (Charts, Tables)                 │
│                    ├─ Agent Visualization                                    │
│                    └─ Real-time Progress Display                             │
│                                                                                │
└────────────────────┬─────────────────────────────────────────────────────────────┘
					 │ HTTP/REST
					 ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                           API GATEWAY LAYER                                    │
│                                                                                │
│                AWS Application Load Balancer (ALB)                            │
│                ├─ HTTPS Termination                                           │
│                ├─ SSL Certificate                                             │
│                ├─ Request Routing                                             │
│                └─ Health Checks                                               │
│                                                                                │
└────────────────────┬─────────────────────────────────────────────────────────────┘
					 │ Internal Network (ECS)
					 ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                         APPLICATION LAYER                                      │
│                                                                                │
│         AWS ECS/Fargate (Docker Container)                                   │
│         ┌─────────────────────────────────────────────────────────┐           │
│         │                 FastAPI Application                     │           │
│         │                                                         │           │
│         │  ┌────────────────────────────────────────────────────┐ │           │
│         │  │ ORACLE FIOS Chat Engine                            │ │           │
│         │  │ ├─ Backend/api.py (703 lines)                      │ │           │
│         │  │ │  ├─ POST /api/chat endpoint                     │ │           │
│         │  │ │  ├─ Request validation (Pydantic)               │ │           │
│         │  │ │  ├─ CORS middleware                             │ │           │
│         │  │ │  ├─ Rate limiting (100 req/min)                 │ │           │
│         │  │ │  ├─ Error handling                              │ │           │
│         │  │ │  └─ Streaming responses (SSE)                   │ │           │
│         │  │ │                                                 │ │           │
│         │  │ ├─ Backend/intent.py                             │ │           │
│         │  │ │  └─ Query intent classification                │ │           │
│         │  │ │                                                 │ │           │
│         │  │ ├─ Backend/rich_builder.py                       │ │           │
│         │  │ │  └─ Rich output formatting                     │ │           │
│         │  │ │                                                 │ │           │
│         │  │ └─ Backend/graph.py                              │ │           │
│         │  │    └─ LangGraph orchestration engine             │ │           │
│         │  │       ├─ Multi-agent supervision                 │ │           │
│         │  │       ├─ Routing logic                           │ │           │
│         │  │       ├─ State management                        │ │           │
│         │  │       └─ Fallback chains                         │ │           │
│         │  └────────────────────────────────────────────────────┘ │           │
│         │                                                         │           │
│         │  ┌────────────────────────────────────────────────────┐ │           │
│         │  │ FinAgent Autonomous Research Engine               │ │           │
│         │  │ ├─ finagent/api.py (152 lines)                    │ │           │
│         │  │ │  ├─ POST /api/chat (streaming)                │ │           │
│         │  │ │  ├─ POST /api/research (start)                │ │           │
│         │  │ │  ├─ GET /api/stream (SSE)                     │ │           │
│         │  │ │  └─ Response depth modes                       │ │           │
│         │  │ │                                                │ │           │
│         │  │ ├─ finagent/run_agent.py (2000 lines)            │ │           │
│         │  │ │  └─ 8-Phase Research Pipeline:                │ │           │
│         │  │ │     1. Identify (entity resolution)            │ │           │
│         │  │ │     2. Enrichment (parallel APIs)              │ │           │
│         │  │ │     3. Breadth Survey (layered search)         │ │           │
│         │  │ │     4. Deep Dive (gap filling)                 │ │           │
│         │  │ │     5. Analysis (conflict detection)           │ │           │
│         │  │ │     6. Specialist Analysis (4 experts)         │ │           │
│         │  │ │     7. Verification (fact-checking)            │ │           │
│         │  │ │     8. Synthesis (memo generation)             │ │           │
│         │  │ │                                                │ │           │
│         │  │ ├─ finagent/gateway/run.py (1657 lines)          │ │           │
│         │  │ │  ├─ Session management                         │ │           │
│         │  │ │  ├─ SSE event streaming                        │ │           │
│         │  │ │  ├─ Progress tracking                          │ │           │
│         │  │ │  └─ Rate limiting                              │ │           │
│         │  │ │                                                │ │           │
│         │  │ ├─ finagent/agents/ (Multi-agent orchestration)  │ │           │
│         │  │ │  ├─ Orchestrator (coordinates experts)         │ │           │
│         │  │ │  ├─ Verifier (fact-checking)                  │ │           │
│         │  │ │  └─ Specialists/                              │ │           │
│         │  │ │     ├─ accounting.py                          │ │           │
│         │  │ │     ├─ competitive.py                         │ │           │
│         │  │ │     ├─ governance.py                          │ │           │
│         │  │ │     └─ valuation.py                           │ │           │
│         │  │ │                                                │ │           │
│         │  │ ├─ finagent/tools/ (Data & MCP Integration)      │ │           │
│         │  │ │  ├─ data.py (50+ data models)                │ │           │
│         │  │ │  ├─ web/ (DuckDuckGo, scraping)              │ │           │
│         │  │ │  ├─ mcp/ (MCP service clients)               │ │           │
│         │  │ │  └─ data_sources/ (SEC, Yahoo, Wiki)         │ │           │
│         │  │ │                                                │ │           │
│         │  │ ├─ finagent/memory/ (Long-term memory)           │ │           │
│         │  │ │  ├─ store.py (persistent facts)              │ │           │
│         │  │ │  └─ chat_memory.py (conversation history)     │ │           │
│         │  │ │                                                │ │           │
│         │  │ ├─ finagent/state/ (State & checkpointing)       │ │           │
│         │  │ │  ├─ checkpoint.py (phase snapshots)           │ │           │
│         │  │ │  └─ citation_log.py (fact attribution)        │ │           │
│         │  │ │                                                │ │           │
│         │  │ ├─ finagent/synthesis/ (Memo generation)         │ │           │
│         │  │ │  └─ Markdown report generation with citations  │ │           │
│         │  │ │                                                │ │           │
│         │  │ ├─ finagent/geo/ (Entity resolution)             │ │           │
│         │  │ │  ├─ entity_resolver.py (ticker lookup)        │ │           │
│         │  │ │  └─ query_localizer.py (geography context)    │ │           │
│         │  │ │                                                │ │           │
│         │  │ ├─ finagent/analysis/ (Post-research)            │ │           │
│         │  │ │  ├─ conflicts.py (multi-source validation)     │ │           │
│         │  │ │  └─ quality.py (research scoring)             │ │           │
│         │  │ │                                                │ │           │
│         │  │ ├─ finagent/retrieval/ (Query planning)          │ │           │
│         │  │ ├─ finagent/router/ (Query routing)              │ │           │
│         │  │ ├─ finagent/playbooks/ (Query patterns)          │ │           │
│         │  │ ├─ finagent/harness/ (Context compression)       │ │           │
│         │  │ └─ finagent/output/ (Output classification)      │ │           │
│         │  └────────────────────────────────────────────────────┘ │           │
│         │                                                         │           │
│         └─────────────────────────────────────────────────────────┘           │
│                                                                                │
│  Technology Stack:                                                            │
│  ├─ FastAPI (REST API framework)                                             │
│  ├─ LangGraph (Multi-agent orchestration)                                    │
│  ├─ LangChain (Agent framework)                                              │
│  ├─ Anthropic Claude 3.x (LLM)                                               │
│  ├─ AsyncIO (Async runtime)                                                  │
│  ├─ httpx (Async HTTP client)                                                │
│  ├─ Pydantic (Data validation)                                               │
│  └─ Python 3.11+                                                             │
│                                                                                │
└────────────────────┬─────────────────────────────────────────────────────────────┘
					 │ Internal Network (ECS Tasks)
					 │
		┌────────────┼────────────┬──────────────┐
		│            │            │              │
		▼            ▼            ▼              ▼
	┌────────┐  ┌────────┐  ┌─────────┐  ┌──────────┐
	│  MCP   │  │  MCP   │  │   MCP   │  │   MCP    │
	│ Service│  │Service │  │ Service │  │ Service  │
	│  NSE   │  │ Funds  │  │Research │  │   Docs   │
	│ 8001   │  │ 8002   │  │  8003   │  │  8004    │
	└────────┘  └────────┘  └─────────┘  └──────────┘
		│            │            │              │
		│                         │              │
		└─────────────────────────┴──────────────┘
					 │
					 ▼
	┌──────────────────────────────────────────────────┐
	│  MCP Valuation Service (8005)                    │
	│  ├─ DCF models                                   │
	│  ├─ Comparable valuations                        │
	│  └─ Fair value estimates                         │
	└──────────────────────────────────────────────────┘
					 │
		┌────────────┼────────────┐
		│            │            │
		▼            ▼            ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ External API │ │ Web Scraping │ │ Social Media │
│              │ │              │ │              │
├─ NSE API    │ ├─ DuckDuckGo  │ ├─ Reddit API │
├─ SEC EDGAR  │ ├─ BeautifulSoup├─ StockTwits  │
├─Yahoo Finance├─ httpx        │ ├─HackerNews  │
└──────────────┘ │ (HTML parsing)│ └──────────────┘
				 └──────────────┘

```

---

## 🎯 Core Layers & Components

### Layer 1: Presentation (Frontend)

**Technology:** Next.js 13+, React, TypeScript  
**Location:** `Frontend/app/`  
**Deployment:** AWS Amplify

**Components:**
- `page.tsx` — Main chat interface
  - Message input form
  - Send button
  - Conversation display
  - Real-time message streaming (SSE)
  - Agent visualization
  - Rich output rendering

- `_components/` — Reusable components
  - `Charts/` — Candlestick, line, bar, gauge charts
  - `Tables/` — Data table views
  - `Memo/` — Research memo renderer
  - `Loading/` — Progress indicators

**Key Features:**
- Server-Sent Events (SSE) streaming
- Real-time UI updates
- Chart rendering with TradingView-like interface
- Markdown memo display with citations
- Responsive design (mobile-friendly)

**State Management:**
- React hooks (useState, useEffect)
- EventSource API for SSE
- Context API (optional, no Redux)

---

### Layer 2: API Gateway

**Technology:** AWS ALB (Application Load Balancer)  
**Configuration:**
- HTTPS listener (port 443)
- HTTP redirect to HTTPS (port 80)
- SSL certificate (ACM)
- Target group → ECS tasks

**Features:**
- Traffic routing
- Health checks
- Request logging
- DDoS protection (optional: AWS Shield)

---

### Layer 3: Backend API

#### **Component 3A: ORACLE FIOS (Quick Chat)**

**Files:**
- `Backend/api.py` (703 lines)
- `Backend/graph.py` (LangGraph orchestration)
- `Backend/intent.py` (Query classification)
- `Backend/rich_builder.py` (Output formatting)

**Endpoints:**
```
POST /api/chat
├─ Request: {"message": "...", "mode": "research|marathon"}
├─ Process: Intent → Route → Agent → Response
└─ Response: JSON with reply, agents_used, rich output

GET /api/agents (list available agents)
GET /api/health (health check)
```

**Flow:**
```
Request
  ↓
CORS Check → Rate Limit Check
  ↓
Intent Classification
  ├─ Extract entities (tickers, companies)
  ├─ Classify intent (valuation, comparison, news, etc)
  └─ Determine needed data sources
  ↓
LangGraph Orchestration
  ├─ Supervisor node
  ├─ Routing decision
  ├─ Agent invocation (1+ agents)
  ├─ Tool calls (MCP services)
  ├─ Loop until done or timeout
  └─ State accumulation
  ↓
Error Handling
  ├─ Timeouts (240s max)
  ├─ API errors (graceful degradation)
  └─ Rate limits (429 response)
  ↓
Response Formatting
  ├─ Main text reply
  ├─ Agent list
  ├─ Rich output (charts, tables)
  └─ Citations
  ↓
Stream Response (SSE)
  └─ Send to client
```

**Timeouts:**
```python
GRAPH_RUN_TIMEOUT_SECONDS = 240      # 4 minutes max
GRAPH_IDLE_TIMEOUT_SECONDS = 90      # Idle threshold
GRAPH_REBUILD_COOLDOWN_SECONDS = 5   # Rebuild delay after fail
```

---

#### **Component 3B: FinAgent (Deep Research)**

**Files:**
- `finagent/run_agent.py` (2000 lines) — Core pipeline
- `finagent/api.py` (152 lines) — API endpoints
- `finagent/gateway/run.py` (1657 lines) — Standalone gateway

**Endpoints:**
```
POST /api/research
├─ Request: {"query": "...", "depth": "deep|standard|chat|marathon"}
├─ Response: {"session_id": "uuid", "events_url": "/api/session/{id}/events"}
└─ Status: 202 Accepted (async)

GET /api/session/{session_id}/events (SSE)
├─ Event: phase_start → phase_complete → ...
├─ Final: research_complete
└─ Data: real-time progress

GET /api/session/{session_id}/status
├─ Status: running|complete|failed
├─ Progress: 0-100%
└─ Result: memo_url, quality_score

GET /api/session/{session_id}/memo
└─ Return: Markdown research memo
```

**8-Phase Pipeline:**

```
Phase 1: IDENTIFY
  Input: Query (e.g., "TCS")
  Process: Entity resolution
  Output: Ticker, ISIN, exchange, legal name
  Time: 5-10s
  Tools: geo.entity_resolver
  ↓

Phase 2: ENRICHMENT (Parallel)
  Input: Resolved entity
  Process: Fetch from 4+ APIs simultaneously
	├─ NSE API (prices, volume)
	├─ Yahoo Finance (historical)
	├─ Wikipedia (overview)
	└─ News aggregator (recent news)
  Output: Snapshot data, news items
  Time: 20-30s
  Tools: tools/data_sources/*
  ↓

Phase 3: BREADTH SURVEY
  Input: Entity + initial data
  Process: Multi-angle web search (5 angles, 5 results each)
	├─ Fundamentals search
	├─ Growth search
	├─ Competitors search
	├─ Management search
	└─ Risks search
  Output: 25 web results, scraped content
  Time: 30-60s
  Tools: tools/web/scraper
  ↓

Phase 4: DEEP DIVE
  Input: Breadth survey results
  Process: Identify gaps, targeted follow-up queries
	├─ Analyze what's missing
	├─ Generate targeted queries
	└─ Scrape additional results
  Output: Gap-filling data
  Time: 30-45s
  Tools: tools/web/scraper (again)
  ↓

Phase 5: ANALYSIS
  Input: All collected data
  Process: Multi-source conflict detection
	├─ Compare data from different sources
	├─ Score conflicts (0-1)
	├─ Detect pump-and-dump signals
	├─ Quality score research
	└─ Extract key metrics
  Output: Conflict report, quality score
  Time: 15-20s
  Tools: analysis/conflicts, analysis/quality
  ↓

Phase 6: SPECIALIST ANALYSIS (Parallel)
  Input: Accumulated data
  Process: 4 specialist agents analyze in parallel
	├─ Accounting Specialist
	│  ├─ Forensic analysis
	│  ├─ Red flag detection
	│  └─ Ratio analysis
	├─ Competitive Specialist
	│  ├─ Market position
	│  ├─ SWOT analysis
	│  └─ Competitive advantages
	├─ Governance Specialist
	│  ├─ Board analysis
	│  ├─ Promoter changes
	│  └─ Management quality
	└─ Valuation Specialist
	   ├─ DCF model
	   ├─ Comparable valuation
	   └─ Fair value estimate
  Output: 4 specialist reports
  Time: 60-120s (parallel, so slower specialist doesn't delay)
  Tools: agents/specialists/*
  ↓

Phase 7: VERIFICATION
  Input: All claims, specialist reports
  Process: Verifier agent fact-checks
	├─ Extract claims
	├─ Cross-check against sources
	├─ Validate math/calculations
	├─ Flag unverifiable claims
	└─ Score confidence
  Output: Verification report
  Time: 30-45s
  Tools: agents/verifier
  ↓

Phase 8: SYNTHESIS
  Input: All previous phases' output
  Process: Generate polished markdown memo
	├─ Template-based generation
	├─ Include: Executive summary, financials, valuation, risks
	├─ Add citations & sources
	├─ Store to ~/.finagent/memos/
	└─ Create memory facts for future recall
  Output: Markdown memo, memory facts, citations
  Time: 15-30s
  Tools: synthesis/synthesize_memo
  ↓

COMPLETE
  Status: complete
  Save checkpoint to ~/.finagent/state/
  Emit: research_complete event
  Total time: 2-5 minutes (depends on depth)
```

---

### Layer 4: Data & Integration

#### **Component 4A: MCP Services (5 Services)**

**Model Context Protocol (JSON-RPC over HTTP)**

```
┌─────────────────────────┐
│  MCP Service Contract   │
└─────────────────────────┘
		↓
HTTP POST /mcp
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
	"name": "tool_name",
	"arguments": {...}
  }
}
		↓
Response:
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {...}
}
```

**Service 1: NSE India (Port 8001)**
- `get_price(ticker)` → Live price
- `get_volume(ticker)` → Trading volume
- `get_ohlc(ticker, period)` → OHLC data
- `get_market_cap(ticker)` → Market capitalization
- Data: NSE API, real-time stock data

**Service 2: Fundamentals (Port 8002)**
- `get_pe_ratio(ticker)` → P/E ratio
- `get_roe(ticker)` → Return on equity
- `get_debt_equity(ticker)` → Debt/equity ratio
- `get_dividend_yield(ticker)` → Dividend yield
- `get_profit_margin(ticker)` → Profit margin
- Data: Company financials, ratios, metrics

**Service 3: Research (Port 8003)**
- `get_analyst_reports(ticker)` → Research reports
- `get_recommendations(ticker)` → Buy/hold/sell
- `get_price_targets(ticker)` → Price targets
- Data: Analyst research, recommendations

**Service 4: Docs (Port 8004)**
- `get_latest_filing(ticker)` → Latest filing
- `get_announcements(ticker)` → Company announcements
- `get_presentations(ticker)` → Investor presentations
- Data: Company filings, announcements, documents

**Service 5: Valuation (Port 8005)**
- `calculate_dcf(ticker, assumptions)` → DCF value
- `get_comparable_valuation(ticker)` → Comparables
- `get_fair_value_estimate(ticker)` → Fair value
- Data: Valuation models, estimates

**Integration Pattern:**
```python
# In finagent/tools/mcp/nse_india.py
async def get_company_price(ticker: str) -> float:
	response = await mcp_client.call_tool(
		server_url=os.getenv("MCP_NSE_INDIA_URL"),
		tool_name="get_price",
		arguments={"ticker": ticker}
	)
	return response["price"]
```

---

#### **Component 4B: Web Scraping & Search**

**Tools:**
- `DuckDuckGo` — Search engine
- `BeautifulSoup` / `Parsel` — HTML parsing
- `httpx` — Async HTTP requests

**Pattern:**
```python
async def search_layered(query, angles, depth):
	"""Multi-angle web search."""
	results = []
	for angle in angles:
		refined_query = f"{query} {angle}"
		docs = await search_web(refined_query)
		for doc in docs[:depth]:
			content = await scrape_html(doc.url)
			results.append(ScrapedDoc(url, text, facts))
	return results
```

**Features:**
- Concurrent requests (speedup)
- HTML parsing to extract facts
- Rate limit respect (polite scraping)
- Timeout handling (30s max per page)

---

#### **Component 4C: External APIs**

**SEC EDGAR (US Companies)**
- Endpoint: `https://data.sec.gov/api/xbrl/companyfacts/...`
- Data: Financial statements, filings

**Yahoo Finance**
- Endpoint: `https://query2.finance.yahoo.com/...`
- Data: Historical prices, dividends, splits

**Wikipedia**
- Endpoint: `https://en.wikipedia.org/api/rest_v1/page/...`
- Data: Company overviews, summaries

**News Aggregators**
- NewsAPI, RSS feeds
- Data: Latest news, sentiment

**Social Media**
- Reddit API, Twitter API, StockTwits API
- Data: Sentiment, discussions, pump-and-dump detection

---

#### **Component 4D: Memory Store**

**Location:** `~/.finagent/memory/`

**Structure:**
```
entity_TCS.json
{
  "target": "TCS",
  "facts": [
	{
	  "id": "fact-001",
	  "claim": "TCS revenue in FY25 is ₹200,000 Cr",
	  "source": "NSE API",
	  "confidence": 0.95,
	  "verified": true,
	  "created_at": "2026-05-20T15:30:00Z",
	  "tags": ["financials", "revenue", "fy25"]
	},
	...
  ]
}
```

**Features:**
- Persistent storage of facts
- Confidence scoring (0-1)
- Verification status
- TTL (expires_at) for seasonal data
- Keyword search for recall

---

### Layer 5: Orchestration & State

#### **Component 5A: LangGraph**

**Purpose:** Multi-agent supervision and routing

**Key Concepts:**
- **Nodes:** Individual agent tasks
- **Edges:** Transitions between nodes
- **State:** Accumulated conversation/research state
- **Supervisor:** Routes to appropriate agent

**Graph Structure:**
```
START
  ↓
Supervisor Node (Decision)
  ├─ Decision: Which agent to invoke?
  ├─ Options: NSE agent, Fundamentals, Research, Valuation
  └─ Route based on intent + current state
  ↓
Selected Agent Node
  ├─ Execute: Call MCP service or web search
  ├─ Tool use: Parse response
  └─ Update state
  ↓
Supervisor Node (Decision)
  ├─ Question: Do we have enough data?
  ├─ Loop: If no, invoke another agent
  └─ Exit: If yes, go to END
  ↓
END (Response generated)
```

**State Machine:**
```python
@dataclass
class GraphState(TypedDict):
	messages: Annotated[list, add_messages]      # Conversation
	context: dict                                 # Rich context
	agents_available: list[str]                   # Agents to invoke
	current_agent: str                            # Currently running
	confidence_score: float                       # 0-1
	is_complete: bool                             # Done?
	error_message: str | None                     # Error if any
```

---

#### **Component 5B: Session & Checkpoint**

**Session Lifecycle:**
```
1. CREATE
   - session_id = UUID
   - status = "running"
   - Store in sessions dict

2. RUN PHASES (8 phases)
   - Each phase updates checkpoint
   - Progress: 0 → 100%
   - Events emitted (phase_start, phase_complete)

3. COMPLETE
   - Checkpoint saved to disk
   - Status = "complete"
   - Memo generated
   - Memory facts stored

4. CLEANUP
   - Delete from sessions dict
   - Archive to disk
   - Prune after 24h
```

**Checkpoint Format:**
```json
{
  "session_id": "uuid",
  "phases": {
	"identify": {
	  "result": {...},
	  "progress": 10,
	  "elapsed_seconds": 5
	},
	"enrichment": {...},
	...
  },
  "memory_facts": [...],
  "citations": [...],
  "status": "complete"
}
```

---

## 🔄 Complete Request Flow (End-to-End)

### Quick Chat Flow (5-15 seconds)

```
User: "What's TCS's dividend yield?"
  ↓
1. Frontend sends POST /api/chat
   Payload: {"message": "What's TCS's dividend yield?"}
  ↓
2. Backend receives request
   ├─ CORS validation ✓
   ├─ Rate limit check ✓
   └─ Input validation (Pydantic) ✓
  ↓
3. Intent Classification (intent.py)
   ├─ Extract entity: "TCS"
   ├─ Classify intent: "VALUATION_METRICS"
   └─ Determine needed: "fundamentals_data"
  ↓
4. LangGraph Starts
   ├─ Initialize state
   ├─ Call Supervisor node
   └─ Decision: "Invoke Fundamentals Agent"
  ↓
5. Fundamentals Agent
   ├─ Tool: get_dividend_yield("TCS")
   ├─ Call MCP Fundamentals Service (port 8002)
   └─ MCP Response: {"dividend_yield": 1.85, "last_dividend": 6.50}
  ↓
6. LangGraph Continues
   ├─ Supervisor checks: "Enough data?"
   ├─ Decision: "Yes, done"
   └─ Exit graph
  ↓
7. Response Formatting (rich_builder.py)
   ├─ Main text: "TCS dividend yield is 1.85%"
   ├─ Rich output: Gauge chart + table
   ├─ Agents used: ["fundamentals_agent"]
   └─ Citations: [NSE source]
  ↓
8. Send Response (SSE or JSON)
   {"reply": "...", "agents_used": [...], "rich": {...}}
  ↓
9. Frontend displays response
   ├─ Render text
   ├─ Show agents
   ├─ Draw chart
   └─ Display references
```

### Deep Research Flow (2-5 minutes)

```
User: "Deep analysis of Asian Paints"
  ↓
1. Frontend sends POST /api/research
   Payload: {"query": "Deep analysis of Asian Paints", "depth": "deep"}
  ↓
2. Backend receives
   ├─ Create session_id
   ├─ Create Session object (in-memory)
   └─ Return: {"session_id": "uuid", "events_url": "/api/session/{id}/events"}
  ↓
3. Frontend subscribes: GET /api/session/{id}/events (SSE)
  ↓
4. Backend starts research (background task)
   ├─ Phase 1: Identify
   │  ├─ Entity resolver: "Asian Paints" → "ASIANPAINT"
   │  ├─ Emit: phase_complete (progress: 10%)
   │  └─ Save checkpoint
   │
   ├─ Phase 2: Enrichment
   │  ├─ Parallel fetch:
   │  │  ├─ NSE snapshot (₹3250 price, ₹2.1T market cap)
   │  │  ├─ Yahoo Finance (historical data)
   │  │  ├─ Wikipedia (company overview)
   │  │  └─ News aggregator (recent news)
   │  ├─ Emit: phase_complete (progress: 35%)
   │  └─ Save checkpoint
   │
   ├─ Phase 3: Breadth Survey
   │  ├─ Search 5 angles × 5 results = 25 docs
   │  ├─ Parse HTML, extract facts
   │  ├─ Emit: phase_complete (progress: 50%)
   │  └─ Save checkpoint
   │
   ├─ Phase 4: Deep Dive
   │  ├─ Identify gaps in data
   │  ├─ Targeted follow-up queries
   │  ├─ Emit: phase_complete (progress: 65%)
   │  └─ Save checkpoint
   │
   ├─ Phase 5: Analysis
   │  ├─ Detect conflicts between sources
   │  ├─ Score data quality (1-100)
   │  ├─ Emit: phase_complete (progress: 75%)
   │  └─ Save checkpoint
   │
   ├─ Phase 6: Specialist Analysis (Parallel)
   │  ├─ Accounting Specialist → Report
   │  ├─ Competitive Specialist → Report
   │  ├─ Governance Specialist → Report
   │  ├─ Valuation Specialist → Report
   │  ├─ Emit: phase_complete (progress: 90%)
   │  └─ Save checkpoint
   │
   ├─ Phase 7: Verification
   │  ├─ Verifier agent fact-checks claims
   │  ├─ Score confidence per claim
   │  ├─ Emit: phase_complete (progress: 95%)
   │  └─ Save checkpoint
   │
   └─ Phase 8: Synthesis
	  ├─ Generate markdown memo:
	  │  # Asian Paints Analysis
	  │  ## Executive Summary
	  │  ## Financial Overview
	  │  ## Competitive Position
	  │  ## Management Quality
	  │  ## Investment Thesis
	  │  ## Risks
	  │  ## References [1-40]
	  ├─ Save memo to ~/.finagent/memos/uuid.md
	  ├─ Extract memory facts for recall
	  ├─ Track citations
	  ├─ Emit: research_complete (progress: 100%)
	  └─ Save checkpoint
  ↓
5. Frontend receives SSE events in real-time
   ├─ phase_start → Update UI with phase name
   ├─ phase_complete → Update progress bar
   └─ research_complete → Display memo button
  ↓
6. User clicks "View Memo"
   GET /api/session/{id}/memo
  ↓
7. Frontend renders markdown memo
   ├─ Display formatted HTML
   ├─ Show citation links
   └─ Make memo downloadable
```

---

## 🗄️ Data Models

### Input Models

```python
# Quick Chat
class ChatRequest(BaseModel):
	message: str                           # User query
	mode: str = Field(default="research")  # research|marathon

# Deep Research
class ResearchRequest(BaseModel):
	query: str                             # What to research
	depth: str = "deep"                    # chat|standard|deep|marathon
	target: str | None = None              # Optional specific ticker
```

### Output Models

```python
# Response
class ChatResponse(BaseModel):
	reply: str                             # Main response
	agents_used: list[str]                 # Which agents ran
	rich: dict[str, Any] | None            # Charts, tables, etc
	output_mode: str | None                # narrative|chart|table
	response_depth: str | None             # Actual depth

# Research
class ResearchResponse(BaseModel):
	session_id: str
	status: str                            # running|complete|failed
	created_at: datetime
	events_url: str
	progress: float
```

### Internal Models

```python
# Entity Resolution
class ResolvedEntity(BaseModel):
	ticker: str                            # TCS
	isin: str                              # INE467B01029
	exchange: str                          # NSE
	company_name: str
	sector: str

# Company Data
class IndiaCompanySnapshot(BaseModel):
	ticker: str
	price: float
	market_cap: float
	pe_ratio: float
	roe: float
	dividend_yield: float
	# ... 50+ fields

# Memory Fact
class MemoryFact(BaseModel):
	target: str                            # Entity researched
	claim: str                             # What was found
	source: str                            # Where it came from
	confidence: float                      # 0.0-1.0
	verified: bool
	created_at: datetime

# Citation
class Citation(BaseModel):
	claim_text: str                        # What was cited
	source_name: str                       # NSE, Wikipedia, etc
	source_url: str | None                 # URL to source
	confidence: float                      # 0.0-1.0
	extracted_at: datetime
```

---

## 🚀 Deployment Architecture

### Local Development

```
Developer Machine
├─ Frontend (npm run dev)
│  └─ http://localhost:3000
├─ Backend (uvicorn Backend.api:app)
│  └─ http://localhost:8000
├─ FinAgent (python -m finagent)
│  └─ http://localhost:8001
└─ MCP Services (separate processes)
   ├─ Port 8001 (NSE)
   ├─ Port 8002 (Fundamentals)
   ├─ Port 8003 (Research)
   ├─ Port 8004 (Docs)
   └─ Port 8005 (Valuation)
```

### Production Deployment

```
AWS Infrastructure
│
├─ Route53 (DNS)
│  └─ api.prospektlab.com
│
├─ CloudFront (CDN - optional)
│  └─ Caches static assets
│
├─ ALB (Application Load Balancer)
│  ├─ HTTPS listener (port 443)
│  │  └─ SSL certificate (ACM)
│  ├─ HTTP listener (port 80)
│  │  └─ Redirect to HTTPS
│  └─ Target group → ECS tasks
│
├─ ECS Cluster
│  ├─ ECS Service (Backend)
│  │  ├─ Task Definition
│  │  │  ├─ Docker image: prospektlab-backend:latest
│  │  │  ├─ CPU: 2 vCPU
│  │  │  ├─ Memory: 4 GB
│  │  │  ├─ Port: 8080
│  │  │  └─ Environment variables
│  │  │     ├─ OPENAI_API_KEY
│  │  │     ├─ MCP_NSE_INDIA_URL
│  │  │     ├─ MCP_FUNDAMENTALS_URL
│  │  │     ├─ MCP_RESEARCH_URL
│  │  │     ├─ MCP_DOCS_URL
│  │  │     ├─ MCP_VALUATION_URL
│  │  │     ├─ CORS_ORIGINS
│  │  │     └─ LOG_LEVEL
│  │  ├─ Replicas: 2-3
│  │  ├─ Auto-scaling rules
│  │  └─ Health checks
│  │
│  └─ ECS Service (MCP Services)
│     ├─ NSE Service (port 8001)
│     ├─ Fundamentals Service (port 8002)
│     ├─ Research Service (port 8003)
│     ├─ Docs Service (port 8004)
│     └─ Valuation Service (port 8005)
│
├─ Amplify (Frontend)
│  ├─ Build: npm run build
│  ├─ Deploy: S3 + CloudFront
│  └─ Environment
│     ├─ NEXT_PUBLIC_API_BASE=https://api.prospektlab.com
│     └─ BACKEND_API_URL=https://api.prospektlab.com
│
├─ ECR (Elastic Container Registry)
│  ├─ Backend image: prospektlab-backend:latest
│  └─ MCP images: mcp-nse, mcp-fundamentals, etc
│
├─ CloudWatch (Monitoring)
│  ├─ Logs (CloudWatch Logs)
│  ├─ Metrics
│  └─ Alarms
│
└─ Secrets Manager (Secure secrets)
   ├─ OPENAI_API_KEY
   ├─ Database credentials (future)
   └─ API keys (future)
```

### CI/CD Pipeline

```
GitHub Repository (production branch)
  ↓
GitHub Actions Triggered
  ├─ Checkout code
  ├─ Run tests
  ├─ Build Docker image
  ├─ Push to ECR
  ├─ Update ECS task definition
  ├─ Deploy to Fargate
  ├─ Run smoke tests
  ├─ Send Slack notification
  └─ Complete ✓
  ↓
ECS Updates Service
  ├─ Pull new image from ECR
  ├─ Start new task (with new image)
  ├─ Wait for health check
  ├─ Route traffic (ALB)
  ├─ Stop old task
  └─ Service running (rolling update)
```

---

## 🔌 Integration Points

### With Frontend

```
Frontend → Backend
  ├─ POST /api/chat (JSON)
  ├─ POST /api/research (JSON)
  ├─ GET /api/session/{id}/events (SSE)
  └─ GET /api/session/{id}/status (JSON)

Backend → Frontend
  ├─ ChatResponse (JSON over HTTP)
  ├─ ResearchResponse (JSON 202 Accepted)
  ├─ Events (SSE stream)
  └─ Memo (Markdown text)
```

### With MCP Services

```
Backend → MCP Service
  POST /mcp
  {
	"jsonrpc": "2.0",
	"id": 1,
	"method": "tools/call",
	"params": {"name": "...", "arguments": {...}}
  }

MCP Service → Backend
  {
	"jsonrpc": "2.0",
	"id": 1,
	"result": {...}
  }
```

### With External APIs

```
Backend → External API
  ├─ NSE API (REST)
  ├─ SEC EDGAR (REST)
  ├─ Yahoo Finance (REST)
  ├─ Wikipedia (REST)
  ├─ News APIs (REST)
  ├─ Reddit API (REST)
  ├─ DuckDuckGo (web scraping)
  └─ Other sources (web scraping)
```

---

## 📊 Performance Characteristics

| Operation | Time | Bottleneck |
|-----------|------|-----------|
| Quick chat query | 5-15s | MCP latency |
| Single MCP call | 1-3s | Network |
| Deep research | 2-5m | Specialist agents |
| Web scraping | 10-20s | HTML parsing |
| Memory recall | <1s | Keyword matching |
| Memo generation | 10-20s | Template + data |

---

## 🔐 Security Model

### Current

✅ CORS protection  
✅ Rate limiting (100 req/min per IP)  
✅ API key management (env vars)  
✅ Input validation (Pydantic)  
✅ Error handling (no sensitive data leaked)  
✅ Timeout protection (240s max)  
✅ HTTPS in production (via ALB)  

### Future

⏳ JWT authentication  
⏳ API key per user  
⏳ Per-user quotas  
⏳ Encryption at rest  
⏳ Audit logging  
⏳ OAuth2 integration  

---

## 🎯 Scalability

### Horizontal Scaling

```
More traffic? → Add more ECS tasks
├─ Auto-scaling group (2-10 tasks)
├─ ALB distributes traffic
└─ Each task independent

More users? → Add database replication
└─ PostgreSQL read replicas (future)
```

### Vertical Scaling

```
High latency? → Increase task resources
├─ From 2 vCPU/4GB to 4 vCPU/8GB
├─ More parallel processing
└─ Better response times
```

### Caching

```
Same queries? → Cache results
├─ In-memory cache (finagent)
├─ Session-level cache (checkpoints)
├─ Redis cache (future)
└─ CDN cache (frontend, CloudFront)
```

---

## 📈 Key Metrics

**System Health:**
- Response time (p50, p95, p99)
- Error rate (4xx, 5xx)
- Success rate (% completed)

**Usage:**
- Requests per minute
- Active sessions
- Agents used per query

**Performance:**
- Phase duration (per research phase)
- Memory usage
- CPU utilization
- Network I/O

---

## 🚀 What's Unique

1. **Dual-Engine Design**
   - ORACLE: Fast conversational chat (5-15s)
   - FinAgent: Deep research analysis (2-5m)

2. **8-Phase Research Pipeline**
   - Sophisticated multi-stage approach
   - Parallel execution where possible
   - Verification pass (reduces hallucinations)

3. **Multi-Agent Orchestration**
   - Specialist agents (accounting, competitive, governance, valuation)
   - LangGraph supervision
   - Intelligent routing

4. **MCP Microservices**
   - Decoupled data layer
   - 5 independent services
   - Easy to scale/replace

5. **Real-time Streaming**
   - SSE for live progress
   - Event-based architecture
   - No polling required

6. **Memory & Citation Tracking**
   - Long-term fact store
   - Confidence scoring
   - Full citation tracking

---

## 🎊 Summary

**ProspektLab** is a sophisticated, multi-layered financial intelligence system:

- **Frontend:** React SPA with real-time streaming
- **API:** FastAPI with LangGraph orchestration
- **Processing:** Dual-engine (quick chat + deep research)
- **Data:** 5 MCP services + 15+ external data sources
- **State:** Checkpointing + long-term memory
- **Deployment:** AWS ECS/Fargate with ALB
- **Scaling:** Auto-scaling, horizontal & vertical
- **Security:** CORS, rate limiting, timeouts, secrets management

---

**Repository:** https://github.com/K-u-s-h-gupta/Prospektlab_intelligence  
**Current Status:** Production-Ready  
**Last Updated:** May 21, 2026


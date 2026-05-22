# 🔀 ProspektLab - Data Flow & Integration Patterns

## Complete Request/Response Cycle

### Scenario 1: Quick Chat Query (5-15 seconds)

**User Query:** "What's TCS's dividend yield?"

```
┌─────────────────────────────────────────────────────────────────┐
│ FRONTEND (Next.js)                                              │
│                                                                 │
│ User types: "What's TCS's dividend yield?"                      │
│ Click: Send                                                     │
│                                                                 │
│ Code: POST /api/chat                                            │
│ Payload: { message: "What's TCS's dividend yield?" }            │
└────────────────────┬────────────────────────────────────────────┘
					 │ HTTPS
					 │ Content-Type: application/json
					 │
┌────────────────────▼────────────────────────────────────────────┐
│ BACKEND API (FastAPI - Backend/api.py)                          │
│                                                                 │
│ 1. Receive ChatRequest                                          │
│    {                                                            │
│      message: "What's TCS's dividend yield?",                   │
│      mode: "research"                                           │
│    }                                                            │
│                                                                 │
│ 2. Call intent.py                                               │
│    intent = classify_intent("What's TCS's dividend yield?")     │
│    → { entities: ["TCS"], type: "FUNDAMENTALS", metric: "dps" } │
│                                                                 │
│ 3. Initialize LangGraph                                         │
│    _graph = build_graph()  # Lazy-loaded, cached                │
│                                                                 │
│ 4. Create chat state:                                           │
│    state = {                                                    │
│      messages: [HumanMessage("What's TCS's dividend yield?")],  │
│      context: { entities: ["TCS"], ...},                        │
│      agents_available: ["nse", "fundamentals", "valuation"]     │
│    }                                                            │
│                                                                 │
└────────────────────┬────────────────────────────────────────────┘
					 │
		 ┌───────────▼──────────────┐
		 │ LangGraph (Backend/graph.py)
		 │
		 │ Node 1: Supervisor
		 │ ├─ Reads state.context
		 │ ├─ Decides: Which agent?
		 │ └─ Routes to: fundamentals_agent
		 │
		 │ (Loop continues until END node)
		 └───────────────┬────────────────────────┘
						 │
		┌────────────────▼──────────────────────┐
		│ Fundamentals Agent (LangChain)        │
		│                                       │
		│ Tools available:                      │
		│ - get_company_pe()                    │
		│ - get_dividend_yield()  ← We need   │
		│ - get_profit_margin()                 │
		│ - get_roe()                           │
		└───────┬──────────────────────────────┘
				│
				│ Agent decides to call:
				│ get_dividend_yield("TCS")
				│
		┌───────▼──────────────────────────────┐
		│ finagent/tools/mcp/fundamentals.py   │
		│                                      │
		│ async def get_dividend_yield(ticker):│
		│   return await call_mcp_tool(        │
		│     server_url = env(                │
		│       "MCP_FUNDAMENTALS_URL"         │
		│     ),                               │
		│     tool_name = "get_dividend_yield",│
		│     args = {"ticker": ticker}        │
		│   )                                  │
		└───────┬──────────────────────────────┘
				│ HTTP POST
				│ (Internal network)
		┌───────▼──────────────────────────────┐
		│ MCP Fundamentals Service (port 8002) │
		│ (Separate deployment)                │
		│                                      │
		│ POST /mcp                            │
		│ {                                    │
		│   "jsonrpc": "2.0",                  │
		│   "id": 1,                           │
		│   "method": "tools/call",            │
		│   "params": {                        │
		│     "name": "get_dividend_yield",    │
		│     "arguments": {"ticker": "TCS"}   │
		│   }                                  │
		│ }                                    │
		│                                      │
		│ Returns:                             │
		│ {                                    │
		│   "jsonrpc": "2.0",                  │
		│   "id": 1,                           │
		│   "result": {                        │
		│     "dividend_yield": 1.85,          │
		│     "last_dividend": ₹6.50,          │
		│     "dps_ttm": ₹6.50                 │
		│   }                                  │
		│ }                                    │
		└───────┬──────────────────────────────┘
				│
		┌───────▼──────────────────────────────┐
		│ Fundamentals Agent processes response│
		│                                      │
		│ Tool result: {                       │
		│   "dividend_yield": 1.85,            │
		│   "last_dividend": ₹6.50             │
		│ }                                    │
		│                                      │
		│ Updates state:                       │
		│ state.messages.append(               │
		│   AIMessage("dividend_yield: 1.85%")│
		│ )                                    │
		│                                      │
		│ Supervisor checks: More agents?     │
		│ Decision: NO, enough data           │
		└───────┬──────────────────────────────┘
				│ End graph
		┌───────▼──────────────────────────────┐
		│ rich_builder.py formats output       │
		│                                      │
		│ create_rich_output({                 │
		│   data: {                            │
		│     dividend_yield: 1.85,            │
		│     ticker: "TCS"                    │
		│   },                                 │
		│   output_mode: "narrative"           │
		│ })                                   │
		│                                      │
		│ Result:                              │
		│ {                                    │
		│   text: "TCS has a dividend...",     │
		│   chart: { type: "gauge", ... },     │
		│   table: { ... }                     │
		│ }                                    │
		└───────┬──────────────────────────────┘
				│
		┌───────▼──────────────────────────────┐
		│ ChatResponse built                   │
		│                                      │
		│ {                                    │
		│   reply: "TCS has a dividend...",    │
		│   agents_used: ["fundamentals"],     │
		│   rich: {                            │
		│     text: "...",                     │
		│     gauge_chart: { ... },            │
		│     table: { ... }                   │
		│   }                                  │
		│ }                                    │
		│                                      │
		│ Stream via SSE to Frontend           │
		└────────────────┬──────────────────────┘
						 │ SSE (Keep-Alive)
						 │ Content-Type: text/event-stream
						 │
┌────────────────────────▼──────────────────────────────────────┐
│ FRONTEND (React component)                                    │
│                                                               │
│ useEffect(() => {                                             │
│   eventSource.onmessage = (event) => {                        │
│     const data = JSON.parse(event.data);                      │
│     // Display reply                                          │
│     setMessages([...messages, {                               │
│       role: "assistant",                                      │
│       content: data.reply,                                    │
│       rich: data.rich                                         │
│     }]);                                                      │
│     // Render agents_used badges                              │
│     setAgentsUsed(data.agents_used);                           │
│     // Render rich chart                                      │
│     <GaugeChart data={data.rich.gauge_chart} />               │
│   };                                                          │
│ }, []);                                                       │
│                                                               │
│ Display to user:                                              │
│ ┌────────────────────────────────┐                            │
│ │ Assistant (TCS Agent, Fund)    │                            │
│ │                                │                            │
│ │ TCS has a dividend yield of    │                            │
│ │ 1.85%, with the last dividend  │                            │
│ │ being ₹6.50 per share.         │                            │
│ │                                │                            │
│ │ [Gauge Chart: 1.85%]           │                            │
│ │ [Table: DPS TTM, Last Div...]  │                            │
│ └────────────────────────────────┘                            │
└────────────────────────────────────────────────────────────────┘
```

---

## Scenario 2: Deep Research Query (2-5 minutes)

**User Query:** "Deep analysis of Asian Paints"

```
┌─────────────────────────────────────────────────────────────────┐
│ FRONTEND or CLI or Direct API Call                              │
│                                                                 │
│ POST /api/research (or finagent/gateway/run.py)                │
│ {                                                               │
│   "query": "Deep analysis of Asian Paints",                     │
│   "depth": "deep"                                               │
│ }                                                               │
│                                                                 │
│ Returns: { session_id: "uuid-123" }                             │
└────────────────────┬────────────────────────────────────────────┘
					 │
		┌────────────▼──────────────────────────┐
		│ finagent/gateway/run.py                │
		│                                       │
		│ 1. Create session                     │
		│    session_id = uuid.uuid4()          │
		│    session = Session(                 │
		│      id=session_id,                   │
		│      query="Deep analysis...",        │
		│      status="running",                │
		│      events=[]                        │
		│    )                                  │
		│                                       │
		│ 2. Store in SessionManager            │
		│    sessions[session_id] = session     │
		│                                       │
		│ 3. Start background task              │
		│    asyncio.create_task(               │
		│      run_research_session(            │
		│        query,                         │
		│        session_id,                    │
		│        depth="deep"                   │
		│      )                                │
		│    )                                  │
		└────────────┬─────────────────────────┘
					 │
		┌────────────▼──────────────────────────┐
		│ finagent/run_agent.py                  │
		│ run_research_session()                │
		│                                       │
		│ PHASE 1: IDENTIFY                     │
		│ ├─ Input: "Asian Paints"              │
		│ ├─ resolve_entity()                   │
		│ └─ Output: {                           │
		│     ticker: "ASIANPAINT",             │
		│     isin: "INE021A01012",             │
		│     exchange: "NSE"                   │
		│   }                                   │
		│                                       │
		│ Emit event:                           │
		│ event: "phase_start"                  │
		│ data: { phase: "identify", ... }      │
		│                                       │
		│ event: "phase_complete"               │
		│ data: { phase: "identify", result: {} │
		└────────────┬─────────────────────────┘
					 │ Events pushed to session.events
					 │ Frontend polls via SSE: /api/session/{id}/events
					 │
		┌────────────▼─────────────────────────────┐
		│ PHASE 2: ENRICHMENT (Parallel)          │
		│                                          │
		│ Run in parallel:                         │
		│                                          │
		│ Task 1: fetch_india_snapshot(ticker)    │
		│ → NSE MCP service                       │
		│ → Returns: {                            │
		│     price: ₹3250,                       │
		│     market_cap: ₹2.1T,                  │
		│     pe: 42.5,                           │
		│     roe: 18.2%                          │
		│   }                                     │
		│                                          │
		│ Task 2: fetch_news(ticker)              │
		│ → News aggregator API                   │
		│ → Returns: [                            │
		│     {headline: "...", source: "..."},   │
		│     ...                                 │
		│   ]                                     │
		│                                          │
		│ Task 3: fetch_wikipedia_summary()       │
		│ → Wikipedia REST API                    │
		│ → Returns: {summary: "..."}             │
		│                                          │
		│ Task 4: search_reddit(ticker)           │
		│ → Reddit API + sentiment analysis       │
		│ → Returns: [posts with sentiment]       │
		│                                          │
		│ All tasks await concurrently            │
		│ Emit: "enrichment_progress" (50%)       │
		└────────────┬──────────────────────────┘
					 │
		┌────────────▼──────────────────────────┐
		│ PHASE 3: BREADTH SURVEY                │
		│                                        │
		│ search_layered(                        │
		│   query="Asian Paints fundamentals",   │
		│   angles=[                             │
		│     "fundamentals",                    │
		│     "growth",                          │
		│     "competitors",                     │
		│     "management",                      │
		│     "risks"                            │
		│   ],                                   │
		│   depth=5                              │
		│ )                                      │
		│                                        │
		│ For each angle:                        │
		│ 1. Query DuckDuckGo                    │
		│ 2. Scrape top 5 results                │
		│ 3. Parse HTML → structured text       │
		│ 4. Extract facts                      │
		│                                        │
		│ Result: [ScrapedDoc, ScrapedDoc, ...]  │
		│ Emit: "breadth_complete" (75%)         │
		└────────────┬──────────────────────────┘
					 │
		┌────────────▼──────────────────────────┐
		│ PHASE 4: DEEP DIVE                    │
		│                                        │
		│ Analyze breadth results:              │
		│ - Missing data? → gaps = []           │
		│ - Need more on: debt, expansion plans │
		│                                        │
		│ Targeted queries:                     │
		│ 1. "Asian Paints debt equity ratio"   │
		│ 2. "Asian Paints expansion strategy"  │
		│ 3. "Asian Paints FDI investments"     │
		│                                        │
		│ Scrape results, extract facts        │
		│ Emit: "deep_dive_complete" (85%)      │
		└────────────┬──────────────────────────┘
					 │
		┌────────────▼──────────────────────────┐
		│ PHASE 5: ANALYSIS                     │
		│                                        │
		│ detect_conflicts(                     │
		│   facts=[...],                        │
		│   sources=[...]                       │
		│ )                                      │
		│                                        │
		│ Compare:                              │
		│ - Source A says PE=42.5               │
		│ - Source B says PE=42.8               │
		│ → Conflict score: LOW (0.3%)          │
		│                                        │
		│ score_research()                      │
		│ → Quality report: {                   │
		│     data_completeness: 85,            │
		│     source_diversity: 78,             │
		│     conflicts: 2,                     │
		│     score: 82                         │
		│   }                                    │
		│                                        │
		│ Emit: "analysis_complete" (90%)       │
		└────────────┬──────────────────────────┘
					 │
		┌────────────▼──────────────────────────┐
		│ PHASE 6: SPECIALIST ANALYSIS          │
		│                                        │
		│ Run 4 specialist agents in parallel:  │
		│                                        │
		│ Accounting Specialist:                │
		│ - Analyze profitability trends        │
		│ - Detect red flags                    │
		│ → Report: "Strong margins, stable"    │
		│                                        │
		│ Competitive Specialist:               │
		│ - Market position                     │
		│ - Competitive advantages              │
		│ → Report: "Market leader in India"    │
		│                                        │
		│ Governance Specialist:                │
		│ - Board composition                   │
		│ - Promoter holding changes            │
		│ → Report: "Stable governance"         │
		│                                        │
		│ Valuation Specialist:                 │
		│ - DCF model                           │
		│ - Comparable analysis                 │
		│ → Report: "Fair value: ₹3200-3400"   │
		│                                        │
		│ Emit: "specialists_complete" (95%)    │
		└────────────┬──────────────────────────┘
					 │
		┌────────────▼──────────────────────────┐
		│ PHASE 7: VERIFICATION                 │
		│                                        │
		│ Verifier agent fact-checks all claims:
		│                                        │
		│ Claim 1: "Market cap ₹2.1T"           │
		│ Verification: ✓ Confirmed (NSE data)  │
		│                                        │
		│ Claim 2: "ROE 18.2%"                  │
		│ Verification: ✓ Confirmed (calc OK)   │
		│                                        │
		│ Claim 3: "Fair value ₹3200"           │
		│ Verification: ✓ DCF model shown       │
		│                                        │
		│ Generate VerifierReport               │
		│ Emit: "verification_complete" (98%)   │
		└────────────┬──────────────────────────┘
					 │
		┌────────────▼──────────────────────────┐
		│ PHASE 8: SYNTHESIS                    │
		│                                        │
		│ synthesize_memo(                      │
		│   enrichment_bundle={                 │
		│     ticker: "ASIANPAINT",             │
		│     india_snapshot: {...},            │
		│     news: [...],                      │
		│     breadth_facts: [...],             │
		│     specialist_reports: [...],        │
		│     verification_report: {...}        │
		│   },                                  │
		│   template="deep_analysis"            │
		│ )                                      │
		│                                        │
		│ Generate markdown:                    │
		│ # Asian Paints Deep Analysis          │
		│ ## Executive Summary                  │
		│ ## Financials & Valuation             │
		│ ## Competitive Position               │
		│ ## Management Quality                 │
		│ ## Investment Thesis                  │
		│ ## Risks & Mitigants                  │
		│ ## References                         │
		│                                        │
		│ Save to:                              │
		│ ~/.finagent/memos/{session_id}.md     │
		│                                        │
		│ Create Citation object for each fact: │
		│ Citation {                            │
		│   claim: "Market cap ₹2.1T",          │
		│   source: "NSE API",                  │
		│   url: "...",                         │
		│   date: "2026-05-21"                  │
		│ }                                      │
		│                                        │
		│ Store in state/citation_log.py        │
		│                                        │
		│ Emit: "synthesis_complete" (99%)      │
		│ Data: { memo_path: "...", citations } │
		└────────────┬──────────────────────────┘
					 │
		┌────────────▼──────────────────────────┐
		│ RESEARCH COMPLETE                     │
		│                                        │
		│ Checkpoint saved to disk               │
		│ Memory facts persisted                 │
		│ Session marked: status="complete"     │
		│                                        │
		│ Emit: "research_complete" (100%)      │
		│ Data: {                               │
		│   memo_url: "/memos/{id}.md",         │
		│   summary: "...",                     │
		│   quality_score: 82,                  │
		│   total_time: "3m 45s",               │
		│   sources_used: 47,                   │
		│   facts_verified: 23                  │
		│ }                                      │
		└────────────┬──────────────────────────┘
					 │
┌────────────────────▼───────────────────────────────────────┐
│ FRONTEND (SSE EventSource)                                │
│                                                            │
│ useEffect(() => {                                          │
│   const es = new EventSource(                              │
│     `/api/session/${sessionId}/events`                     │
│   );                                                       │
│                                                            │
│   es.addEventListener("phase_start", (e) => {            │
│     setPhase(JSON.parse(e.data).phase);                    │
│     setProgress(10);                                       │
│   });                                                      │
│                                                            │
│   es.addEventListener("phase_complete", (e) => {         │
│     setProgress(prev => prev + 15);                        │
│   });                                                      │
│                                                            │
│   es.addEventListener("research_complete", (e) => {      │
│     const data = JSON.parse(e.data);                       │
│     setMemo(data.memo_url);                                │
│     setQualityScore(data.quality_score);                   │
│     // Fetch and display memo                             │
│     fetchMemo(data.memo_url);                              │
│   });                                                      │
│ }, []);                                                    │
│                                                            │
│ Display to user:                                           │
│ ┌────────────────────────────────────────┐               │
│ │ 🔬 Research in Progress                │               │
│ │                                        │               │
│ │ Phase: Specialist Analysis (6/8)       │               │
│ │ Progress: ████████░░░░░░░░░ 85%        │               │
│ │ Time Elapsed: 2m 30s                   │               │
│ │                                        │               │
│ │ Agents Running:                        │               │
│ │ • Accounting Specialist ✓              │               │
│ │ • Competitive Specialist (active)      │               │
│ │ • Governance Specialist (active)       │               │
│ │ • Valuation Specialist (active)        │               │
│ └────────────────────────────────────────┘               │
│                                                            │
│ ... (2m later) ...                                        │
│                                                            │
│ ┌────────────────────────────────────────┐               │
│ │ ✅ Research Complete                   │               │
│ │                                        │               │
│ │ Quality Score: 82/100                  │               │
│ │ Total Time: 3m 45s                     │               │
│ │ Sources Used: 47                       │               │
│ │ Facts Verified: 23                     │               │
│ │                                        │               │
│ │ [View Full Memo]                       │               │
│ │ [Download PDF]                         │               │
│ │ [Copy to Clipboard]                    │               │
│ │                                        │               │
│ │ # Asian Paints Deep Analysis (Memo)    │               │
│ │ ## Executive Summary                   │               │
│ │ Asian Paints is India's largest paint  │               │
│ │ company with strong market positioning.│               │
│ │ ...                                    │               │
│ └────────────────────────────────────────┘               │
└────────────────────────────────────────────────────────────┘
```

---

## Event Stream Format (SSE)

### Example Real-Time Events

```
# Event 1: Research Started
event: research_started
data: {"session_id": "abc-123", "query": "Analyze TCS", "depth": "deep"}

# Event 2: Phase 1 Starting
event: phase_start
data: {"phase": "identify", "progress": 5}

# Event 3: Phase 1 Complete
event: phase_complete
data: {"phase": "identify", "progress": 10, "result": {"ticker": "TCS", "isin": "INE467B01029"}}

# Event 4: Phase 2 Progress Update
event: enrichment_progress
data: {"sub_phase": "fetching_india_snapshot", "progress": 25}

# Event 5: Phase 2 Complete (Parallel tasks all done)
event: phase_complete
data: {"phase": "enrichment", "progress": 35, "tasks_completed": 4}

# Event 6-11: Phases 3-8 similarly...

# Event 12: Research Complete
event: research_complete
data: {
  "session_id": "abc-123",
  "memo_url": "/memos/abc-123.md",
  "summary": "TCS shows strong fundamentals...",
  "quality_score": 85,
  "total_time_seconds": 245,
  "sources_used": 52,
  "facts_verified": 28,
  "citations_count": 45,
  "warnings": []
}
```

---

## Data Models at Key Stages

### Stage 1: Intent Classification
```python
@dataclass
class Intent:
	entities: list[str]           # ["TCS", "INFY"]
	intent_type: str              # "COMPARISON", "ANALYSIS", "NEWS_SEARCH"
	metrics_needed: list[str]     # ["pe", "roe", "debt_to_equity"]
	data_sources: list[str]       # ["NSE", "FUNDAMENTALS", "NEWS"]
	response_depth: str           # "chat", "standard", "deep", "marathon"
```

### Stage 2: Entity Resolution
```python
@dataclass
class ResolvedEntity:
	ticker: str                   # "TCS"
	isin: str                     # "INE467B01029"
	exchange: str                 # "NSE"
	company_name: str             # "Tata Consultancy Services Limited"
	sector: str                   # "IT Services"
	market_cap: float             # In INR
```

### Stage 3: Enriched Data
```python
@dataclass
class IndiaCompanySnapshot:
	ticker: str
	price: float                  # Current share price
	market_cap: float
	pe_ratio: float
	roe: float
	debt_to_equity: float
	dividend_yield: float
	# ... 50+ financial metrics

@dataclass
class NewsItem:
	headline: str
	source: str                   # "Reuters", "Bloomberg", "Economic Times"
	url: str
	timestamp: datetime
	sentiment: str                # "positive", "neutral", "negative"
```

### Stage 4: Analyzed Data
```python
@dataclass
class ConflictReport:
	claim: str
	sources: list[str]
	conflict_level: float         # 0.0-1.0 (0 = no conflict, 1 = high conflict)
	resolution: str               # "Use median", "Source A is more reliable"

@dataclass
class QualityReport:
	data_completeness: float      # 0-100
	source_diversity: float       # 0-100
	conflict_count: int
	unverifiable_claims: int
	overall_score: float          # 0-100
```

### Stage 5: Verification
```python
@dataclass
class Claim:
	text: str                     # "TCS has a PE of 42.5x"
	source: str                   # URL or document name
	confidence: float             # 0.0-1.0
	verified: bool
	verification_method: str      # "cross_source", "calculation", "recent_api"

@dataclass
class VerifierReport:
	claims_checked: int
	claims_verified: int
	claims_unverifiable: int
	red_flags: list[str]
	overall_confidence: float     # 0.0-1.0
```

### Stage 6: Specialist Analysis
```python
@dataclass
class SpecialistReport:
	specialist_type: str          # "accounting", "competitive", "governance", "valuation"
	findings: str                 # Markdown text
	key_metrics: dict             # Specialist-specific KPIs
	recommendations: list[str]
	confidence_level: float
```

### Stage 7: Final Memo
```python
@dataclass
class ResearchMemo:
	session_id: str
	target: str                   # "TCS"
	query: str
	generated_at: datetime

	executive_summary: str        # Markdown
	financials_section: str       # Markdown
	competitive_analysis: str     # Markdown
	valuation_analysis: str       # Markdown
	management_quality: str       # Markdown
	risks_section: str            # Markdown
	investment_thesis: str        # Markdown

	citations: list[Citation]
	quality_score: float
	specialist_reports: list[SpecialistReport]
	verification_report: VerifierReport
```

---

## Error Handling & Resilience

### MCP Service Failure

```python
# If MCP Fundamentals service is down (port 8002):

1. Agent calls: get_dividend_yield("TCS")
   ↓
2. MCP client times out (default: 30s)
   ↓
3. Catch exception:
   except httpx.ConnectError:
	   logger.warning("MCP Fundamentals unavailable, falling back to web search")
   ↓
4. Fallback: search_web("TCS dividend yield")
   ↓
5. Parse web results, extract data
   ↓
6. Return result with lower confidence score
   ↓
7. Continue research (do not fail entire session)
   ↓
8. Flag in memo: "Data sources note: Some facts from web search (lower confidence)"
```

### Web Scraping Rate Limiting

```python
class InMemSlidingWindowRateLimiter:
	def __init__(self, requests_limit=100, window_seconds=60):
		self.limit = requests_limit
		self.window = window_seconds
		self.requests = []

	async def wait_if_needed(self):
		# If 100 requests in last 60s, wait
		now = time.time()
		self.requests = [t for t in self.requests if now - t < self.window]

		if len(self.requests) >= self.limit:
			sleep_time = self.requests[0] + self.window - now
			await asyncio.sleep(sleep_time)

		self.requests.append(now)
```

### Timeout Handling

```python
PHASE_TIMEOUTS = {
	"identify": 10,         # 10 seconds
	"enrichment": 30,       # 30 seconds
	"breadth_survey": 60,   # 1 minute
	"deep_dive": 90,        # 1.5 minutes
	"analysis": 30,
	"specialist": 120,      # 2 minutes (parallel tasks)
	"verification": 60,
	"synthesis": 30,
}

# Usage:
async def run_phase(phase_name, phase_task):
	try:
		result = await asyncio.wait_for(
			phase_task(),
			timeout=PHASE_TIMEOUTS[phase_name]
		)
		return result
	except asyncio.TimeoutError:
		logger.error(f"Phase {phase_name} timed out")
		return partial_result_or_fallback()
```

---

## Performance Metrics

### Typical Response Times

| Query Type | Mode | Typical Time | Bottleneck |
|---|---|---|---|
| "What's TCS's PE?" | Quick Chat | 2-5 sec | MCP latency |
| "Compare TCS vs INFY" | Quick Chat | 5-10 sec | 2 MCP calls |
| "Latest TCS news" | Quick Chat | 3-8 sec | News API |
| "Analyze TCS" | Deep Research | 2-5 min | Specialist agents |
| "Full company report" | Marathon | 5-10 min | All phases |

### Resource Usage (AWS ECS)

```
CPU: 2 vCPU
Memory: 4 GB
Per-session max:
  - 240s wall-clock time
  - 1 GB memory (average)
  - 50 HTTP requests

Scaling:
  - Concurrent sessions: 10-20 per task
  - Total throughput: 100-200 requests/minute
  - Recommend: 3-5 ECS tasks for prod
```

---

## Caching Strategy

### In-Process Cache (finagent)

```python
class InProcessCache:
	_cache = {}

	@staticmethod
	def get(key):
		# Check if expired
		if key in _cache and _cache[key]['expires'] > time.time():
			return _cache[key]['value']
		return None

	@staticmethod
	def set(key, value, ttl_seconds=3600):
		_cache[key] = {
			'value': value,
			'expires': time.time() + ttl_seconds
		}

# Usage:
cache_key = f"india_snapshot:TCS"
cached = InProcessCache.get(cache_key)
if cached:
	return cached
else:
	snapshot = await fetch_india_snapshot("TCS")
	InProcessCache.set(cache_key, snapshot, ttl=3600)
	return snapshot
```

### Session-Level Cache

```python
# Store in ~/finagent/state/session_{id}.json
{
  "session_id": "abc-123",
  "target": "TCS",
  "phases": {
	"identify": {
	  "entity": {...},
	  "timestamp": "2026-05-21T10:30:00Z"
	},
	"enrichment": {
	  "india_snapshot": {...},
	  "news": [...],
	  "wikipedia": {...},
	  "timestamp": "2026-05-21T10:30:15Z"
	},
	...
  }
}
```

---

## Summary: Complete Integration Map

```
┌─────────────┐
│  Frontend   │ ← SSE streaming
└──────┬──────┘
	   │ REST JSON
	   ▼
┌──────────────────────────────────────┐
│  Backend API (FastAPI)              │
│  - /api/chat (quick)                │
│  - /api/research (deep)             │
│  - /api/session/{id}/events (SSE)   │
└──────┬───────────────────────────────┘
	   │
	   ├─→ Intent Classification → Entity Resolution
	   │
	   ├─→ LangGraph Supervisor
	   │   └─→ Route to agents
	   │       ├─→ Fundamentals Agent
	   │       ├─→ NSE Agent
	   │       ├─→ Research Agent
	   │       └─→ Valuation Agent
	   │
	   ├─→ finagent/run_agent (8-phase)
	   │   ├─ Phase 1-8
	   │   ├─ Specialist agents
	   │   └─ Verification
	   │
	   └─→ Data Layer
		   ├─→ MCP Services (NSE, Fundamentals, Research, Docs, Valuation)
		   ├─→ Web Search (DuckDuckGo, Scraping)
		   ├─→ External APIs (SEC, Yahoo, Wikipedia, News)
		   └─→ Memory Store (Persistent facts)
```

This covers the complete end-to-end data flow for both quick chat and deep research modes!


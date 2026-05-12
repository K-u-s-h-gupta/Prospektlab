# ORACLE FIOS Codebase Walkthrough

This document is a practical walkthrough of the current codebase.

It is written for someone who wants to understand:
- what the project is
- what each major file does
- how data and control move through the system
- where the important logic lives
- what the current rough edges are

This walkthrough covers the maintained application code, not third-party dependencies inside virtual environments or `node_modules`.

## 1. What This Project Is

ORACLE FIOS is a local financial intelligence application with:
- a `Next.js` frontend
- a `FastAPI` backend
- a `LangGraph` multi-agent orchestration layer
- five `FastMCP` servers that expose specialist finance/document tools

The system is designed to answer financial questions by routing the query to specialist sub-agents, which then call live tools instead of answering from model memory.

Core product themes:
- live Indian market data
- company fundamentals
- peer comparison
- financial news and research
- filing and DRHP/RHP/prospectus analysis
- valuation and calculation workflows

## 2. Directory Map

At the root level:

- `Backend/`
  Python backend, LangGraph orchestration, MCP servers, tests, startup scripts
- `Frontend/`
  Next.js chat UI with live process panel
- `ARCHITECTURE.md`
  current architecture overview
- `ORACLE_FIOS_architecture.md`
  older architecture document
- `ORACLE_Phase1_Architecture_Guide.md`
  older phase guide
- `CODEBASE_WALKTHROUGH.md`
  this document

## 3. High-Level Runtime Flow

When a user submits a query:

1. The frontend sends the prompt to `POST /api/chat/stream`.
2. The backend reads the query and plans likely agents.
3. The backend asks LangGraph to run the supervisor.
4. The supervisor delegates to one or more specialist agents.
5. Those agents call MCP tools hosted on local ports `8001` to `8005`.
6. MCP servers fetch live data from providers like NSE, yfinance, Tavily, or Qdrant.
7. Results go back through the agent layer to the supervisor.
8. The backend streams progress events back to the frontend.
9. The frontend shows:
   - planned sub-agents
   - started/completed sub-agents
   - process steps
   - source websites
   - final answer

## 4. Backend Folder Walkthrough

### `Backend/api.py`

This is the runtime entrypoint of the application backend.

Main responsibilities:
- expose HTTP endpoints
- build or reuse the graph
- stream progress events
- infer which agents should probably be used
- guard against fallback and missing-agent failure modes
- normalize backend errors for the UI

Important concepts inside this file:

- `ChatRequest`, `ChatResponse`
  request/response schemas for normal chat

- `_get_graph()`
  lazily builds the LangGraph app and caches it

- `_planned_agents_for_message()`
  heuristic router that detects intent from text
  examples:
  - compare queries -> `comparison_agent`
  - DCF / valuation / WACC -> `valuation_agent`
  - DRHP / prospectus -> `document_retrieval_agent`
  - future / forecast / outlook -> `valuation_agent` + `news_and_research_agent`

- `_augment_query_for_routing()`
  appends routing hints into the prompt so the supervisor is strongly nudged toward the right sub-agents

- `_stream_graph_run()`
  the most important runtime function for the UI
  it streams:
  - `status`
  - `agent_planned`
  - `agent_started`
  - `agent_tool`
  - `agent_completed`
  - `agent_unavailable`
  - `source`
  - `final`

- `/api/chat`
  non-streaming endpoint

- `/api/chat/stream`
  streaming SSE endpoint used by the UI

Design note:
- this file contains a lot of product logic, not just transport logic
- routing heuristics currently live here rather than in a separate router module

### `Backend/graph.py`

This file builds the LangGraph supervisor and all specialist agents.

Main responsibilities:
- connect to MCP servers
- load tools server by server
- construct agents
- compile the supervisor
- create a fallback graph if no MCP tools are available

Key functions:

- `_get_llm()`
  returns the OpenAI chat model used by the graph
  currently tuned with:
  - low temperature
  - reduced timeout
  - reduced retries

- `_load_tools_by_server()`
  very important fault-tolerance function
  if one MCP server fails, it does not immediately kill the whole startup

- `build_oracle_graph()`
  central graph-construction function

The graph builds these agents:

- `market_data_agent`
  uses NSE tools

- `fundamental_analysis_agent`
  uses financial statement and key-metric tools

- `comparison_agent`
  now intentionally narrow
  uses comparison-oriented tools only

- `news_and_research_agent`
  uses Tavily search/extract tools

- `document_retrieval_agent`
  uses document tools plus research tools

- `valuation_agent`
  uses the valuation MCP tools

The supervisor prompt is also here.

It contains:
- routing examples
- live-data guardrails
- instructions to keep using available agents even if some specialists are missing

Fallback mode:
- if no MCP tools can be loaded, `_build_fallback_graph()` is used
- this fallback now behaves as a system-status path only
- it should not answer finance questions from memory

### `Backend/mcp_config.py`

This is the MCP registry for LangGraph.

It maps logical server names to HTTP endpoints:
- `nse_india` -> `8001`
- `fundamentals` -> `8002`
- `research_news` -> `8003`
- `docs_pipeline` -> `8004`
- `valuation_engine` -> `8005`

This file is small, but if it is wrong, the whole backend loses tool access.

### `Backend/start_servers.ps1`

This script starts all MCP servers.

Current behavior:
- kills anything on ports `8001` to `8005`
- launches each MCP server as a detached background process
- writes tracked process metadata to `.server_pids.json`
- performs a quick health check

Why this mattered:
- earlier versions used PowerShell jobs that did not stay alive reliably
- that caused the backend to fail with:
  `No MCP tools could be loaded from any configured server`

### `Backend/stop_servers.ps1`

This script stops the MCP servers.

It:
- kills by port
- kills any tracked process IDs from `.server_pids.json`
- cleans old PID-tracking files

### `Backend/main.py`

This file is effectively a placeholder.

It only prints:
- `"Hello from backend!"`

It is not part of the production runtime path.

### `Backend/pyproject.toml`

This defines Python dependencies.

Important packages:
- `fastapi`
- `fastmcp`
- `langgraph`
- `langgraph-supervisor`
- `langchain-openai`
- `langchain-mcp-adapters`
- `nse`
- `yfinance`
- `tavily-python`
- `qdrant-client`
- `sentence-transformers`
- `pymupdf`

### `Backend/requirements.txt`

This appears to exist alongside `pyproject.toml`.

Project direction appears to be leaning toward `uv` / `pyproject.toml`, but both are present.

### `Backend/README.md`

Currently empty or effectively unused.

This is a maintenance gap.

## 5. MCP Server Walkthrough

The MCP layer is the real data/tool layer of the application.

Each MCP server exposes concrete tools to LangGraph.

### `Backend/mcp_servers/nse_server.py`

Purpose:
- live Indian market data from `NseIndiaApi`

Key helper logic:
- `_get_nse()`
  lazy-initializes the NSE client
- `_parse_date()`
  parses user date input
- `_safe_get()`
  defensive nested-dict access

Tools exposed:
- `nse_get_quote`
- `nse_get_trade_info`
- `nse_get_historical`
- `nse_get_option_chain`
- `nse_get_index`
- `nse_get_shareholding`
- `nse_get_actions`
- `nse_get_announcements`
- `nse_get_board_meetings`

Typical usage:
- current stock quote
- option chain / PCR analysis
- historical price retrieval

### `Backend/mcp_servers/fundamentals_server.py`

Purpose:
- company profile, statements, and ratio analysis from `yfinance`

This is one of the more important and more evolved files.

Key helper logic:
- Windows-safe CA certificate handling
- yfinance timezone cache relocation
- `_get_info()`
  cached `yfinance` info lookups
- `_resolve_ticker_and_info()`
  resolves both ticker-style input and common company names

Why the resolver matters:
- user may ask for `Infosys`
- yfinance expects `INFY.NS`
- this file now bridges that gap

Tools exposed:
- `profile`
- `income_statement`
- `balance_sheet`
- `cash_flow`
- `key_metrics`
- `get_quarterly_results`
- `get_shareholding`
- `compare_stocks`
- `get_peer_comparison`
- `get_dividend_history`

Typical usage:
- company fundamentals
- financial ratio analysis
- company-vs-company comparison

### `Backend/mcp_servers/research_server.py`

Purpose:
- web search, news search, and page extraction via Tavily

Key helper logic:
- `_get_tavily()`
  lazy Tavily client creation

Tools exposed:
- `search_web`
- `search_news`
- `search_financial`
- `extract_url`
- `research_company`

Design note:
- `research_company` is powerful but expensive because it chains multiple searches
- the main graph now intentionally prefers lighter tools in common paths

Typical usage:
- latest company news
- financial-source search
- content extraction from URLs

### `Backend/mcp_servers/docs_server.py`

Purpose:
- document ingestion, retrieval, chunking, indexing, and offer-document comparison

This is the most pipeline-oriented MCP server.

Core stages:

1. check Qdrant for existing content
2. ingest PDF or URL content if needed
3. embed and store chunks
4. retrieve relevant sections for analysis

Key helpers:
- `_get_qdrant()`
- `_get_embedder()`
- `_embed_texts()`
- `_chunk_text()`
- `_extract_pdf_text()`
- `_extract_named_sections()`
- `_build_transition_notes()`

Tools exposed:
- `doc_search`
- `doc_ingest_pdf`
- `doc_ingest_url`
- `doc_fetch_annual_report`
- `doc_compare_offer_documents`
- `doc_list_collections`

Most important specialized tool:
- `doc_compare_offer_documents`
  this is for DRHP vs RHP vs prospectus comparison
  it:
  - finds candidate filings
  - extracts them
  - detects major sections
  - builds a section matrix
  - returns transition notes

Typical usage:
- DRHP risk analysis
- annual report extraction
- document version comparison

### `Backend/mcp_servers/mcp_valuation.py`

Purpose:
- expose valuation and scoring calculations as MCP tools

This file wraps `valuation_engine.py` and enriches it with live `yfinance` inputs.

Key helper logic:
- Windows-safe CA handling
- yfinance cache setup
- `get_stock_data()`
  cached live data fetch for one stock

Tools exposed:
- `run_dcf_valuation`
- `run_graham_valuation`
- `run_pe_valuation`
- `run_ev_ebitda_valuation`
- `run_ddm_valuation`
- `run_piotroski_score`
- `run_altman_z_score`
- `run_dupont_analysis`
- `run_ratio_scorecard`
- `run_full_valuation`
- `run_cagr`
- `run_wacc`

Typical usage:
- “Run a DCF on TCS”
- “Calculate WACC”
- “Give me a full valuation”

## 6. Deterministic Math Layer

### `Backend/valuation_engine.py`

This file is pure calculation logic.

Very important design idea:
- the LLM should not invent finance math
- the LLM should call deterministic functions and explain the returned results

Major functions:
- `dcf_valuation`
- `graham_valuation`
- `pe_valuation`
- `ddm_valuation`
- `ev_ebitda_valuation`
- `calculate_piotroski_score`
- `calculate_altman_z_score`
- `calculate_wacc`
- `calculate_cost_of_equity_capm`
- `dupont_analysis`
- `calculate_cagr`
- `calculate_future_value`
- `analyze_ratios`
- `full_valuation`

This is the cleanest “business logic” layer in the repo.

If someone wants to trust the finance calculations, this file is where they should read first.

## 7. Frontend Walkthrough

### `Frontend/app/page.tsx`

This is the main UI page and effectively the whole current frontend application.

Responsibilities:
- render the chat UI
- post user messages to the backend
- consume SSE
- maintain process state
- show sub-agents
- show source domains
- render the final answer

Important state:
- `messages`
- `input`
- `isLoading`
- `processSteps`
- `sourceDomains`

Important logic:
- `handleSubmit()`
  sends the streaming request

- `upsertProcessStep()`
  translates backend events into UI state

- `fallbackToJsonChat()`
  fallback path if the browser cannot read the stream body

Important event types the UI understands:
- `status`
- `error`
- `source`
- `agent_planned`
- `agent_started`
- `agent_completed`
- `agent_unavailable`
- `final`

Current UI panels:
- chat thread
- live “Sub Agents” panel
- process panel
- source-domain badges

### `Frontend/app/layout.tsx`

Root layout for Next.js app router.

Responsibilities:
- import fonts
- apply root HTML/body wrappers
- set page metadata

Maintenance note:
- metadata is still generic:
  - title: `Create Next App`
  - description: `Generated by create next app`

This should be customized.

### `Frontend/app/globals.css`

Global design tokens and shared styles.

Contains:
- Tailwind theme tokens
- glass panel styles
- scrollbar styling

Design note:
- the app currently uses `Geist` fonts
- visual direction is dark, dashboard-like, glass-panel based

### `Frontend/package.json`

Shows the frontend stack:
- Next.js 16
- React 19
- Tailwind 4
- `react-markdown`
- `lucide-react`

Notable point:
- `framer-motion` and `ai` are present but not central in the current page implementation

## 8. Test Folder Walkthrough

### Testing style

The backend tests are not formal `pytest` assertion suites.

They are closer to:
- executable smoke-test scripts
- operator-facing test scripts

That means:
- good for manual verification
- weaker for CI enforcement

### `Backend/tests/test_langgraph.py`

Purpose:
- build the graph
- stream a representative multi-agent query
- print seen agent activity

This is useful when debugging orchestration.

### `Backend/tests/test_nse_server.py`

Purpose:
- manual smoke tests for NSE tools

It tests:
- quotes
- invalid symbols
- trade info
- historical data
- shareholding
- actions

### `Backend/tests/test_fundamentals_server.py`

Purpose:
- manual smoke tests for yfinance-based fundamentals tools

It tests:
- profile
- statements
- metrics
- one US stock case

### `Backend/tests/test_research_server.py`

Purpose:
- manual smoke tests for Tavily-based tools

It tests:
- generic search
- news search
- finance search
- URL extraction

### `Backend/tests/test_docs_server.py`

Purpose:
- manual checks for document chunking and Qdrant-related behavior

It mostly validates:
- text chunking
- document search behavior when Qdrant may or may not be running

## 9. Operational Behavior by Query Type

### A. Price query

Example:
- “What is the current price of TCS?”

Expected path:
- frontend -> `/api/chat/stream`
- backend routing -> `market_data_agent`
- `nse_server.py` -> `nse_get_quote`

### B. Fundamentals query

Example:
- “Analyze Infosys financials”

Expected path:
- `fundamental_analysis_agent`
- `fundamentals_server.py`

### C. Comparison query

Example:
- “Compare TCS with Infosys”

Expected path:
- `comparison_agent`
- `compare_stocks`

### D. Forecast / outlook style comparison

Example:
- “Compare TCS with Infosys and provide their future forecast”

Expected path:
- `comparison_agent`
- `valuation_agent`
- `news_and_research_agent`

### E. DRHP / prospectus query

Example:
- “Analyze company DRHP and list the risks”

Expected path:
- `document_retrieval_agent`
- sometimes `fundamental_analysis_agent`

### F. Valuation / calculation query

Example:
- “Run a DCF on TCS”

Expected path:
- `valuation_agent`
- `mcp_valuation.py`
- `valuation_engine.py`

## 10. Current Strengths

- clear separation between orchestration and tool execution
- deterministic math layer exists
- document comparison path exists
- live streaming UI gives visibility into process
- backend now handles missing-agent and fallback cases better than before
- MCP server startup is now process-based and reliable

## 11. Current Weak Spots and Maintenance Notes

These are the main issues I observed during the codebase diagnosis.

### 1. `api.py` is doing too much

It currently combines:
- transport
- routing heuristics
- graph lifecycle
- event normalization
- error handling
- process-stream formatting

It works, but it is becoming a “god file”.

### 2. `graph.py` supervisor prompt is large and product-specific

That is not wrong, but it means behavior is partly encoded in prompt examples instead of a more explicit planning layer.

### 3. Tests are mostly manual smoke scripts

This means:
- easier local debugging
- weaker automated regression protection

### 4. Some project metadata is still scaffold/default quality

Examples:
- `Backend/main.py` is placeholder only
- `Backend/README.md` is effectively empty
- `Frontend/app/layout.tsx` still has default Next metadata

### 5. Routing heuristics are string-trigger based

This is pragmatic, but brittle.

Examples:
- wording differences can change agent planning
- unusual company phrasing may still require more normalization over time

### 6. Document and research flows depend on external providers

Heavy paths can still be slow because they depend on:
- Tavily
- Qdrant
- yfinance
- NSE

The architecture is good, but the runtime remains I/O-heavy.

### 7. Multiple architecture docs exist at root

You currently have:
- `ARCHITECTURE.md`
- `ORACLE_FIOS_architecture.md`
- `ORACLE_Phase1_Architecture_Guide.md`

This can drift over time unless one is treated as the source of truth.

## 12. Recommended Reading Order

If you want to understand the system from top to bottom, read in this order:

1. `ARCHITECTURE.md`
2. `Backend/api.py`
3. `Backend/graph.py`
4. `Frontend/app/page.tsx`
5. `Backend/mcp_config.py`
6. `Backend/mcp_servers/fundamentals_server.py`
7. `Backend/mcp_servers/nse_server.py`
8. `Backend/mcp_servers/research_server.py`
9. `Backend/mcp_servers/docs_server.py`
10. `Backend/mcp_servers/mcp_valuation.py`
11. `Backend/valuation_engine.py`
12. `Backend/start_servers.ps1` and `Backend/stop_servers.ps1`
13. `Backend/tests/`

## 13. Practical Mental Model

The easiest way to think about this project is:

- `Frontend`
  UI and live progress display

- `api.py`
  traffic controller and stream manager

- `graph.py`
  brain builder

- `MCP servers`
  specialist hands that fetch or calculate

- `valuation_engine.py`
  finance math library

- `Qdrant`
  memory layer for documents

## 14. Bottom-Line Diagnosis

The codebase is no longer a simple prototype.

It has become a real multi-layer local AI application with:
- orchestration
- live tool access
- document retrieval
- deterministic finance calculation
- a streaming operator UI

The most important parts are now working together in a coherent way, but the repo is at the stage where the next big improvement should be code organization and test hardening, not just adding more features.

If you continue building on this, the next best structural step would be:
- split `api.py` into router + streaming + graph-lifecycle modules
- add real automated tests around routing and fallback behavior
- centralize documentation so there is one canonical engineering guide

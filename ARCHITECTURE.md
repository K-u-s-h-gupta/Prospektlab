# ORACLE FIOS Architecture

This document describes the current architecture of the ORACLE Financial Intelligence OS that we built across the frontend, backend, LangGraph supervisor, MCP servers, and external data providers.

## High-Level Architecture

```mermaid
flowchart TD
    U[User] --> F[Next.js Frontend<br/>Frontend/app/page.tsx]

    F -->|POST /api/chat/stream| API[FastAPI Backend<br/>Backend/api.py]
    API -->|build/get graph| G[LangGraph Supervisor<br/>Backend/graph.py]

    G --> S[Supervisor]

    S --> A1[market_data_agent]
    S --> A2[fundamental_analysis_agent]
    S --> A3[comparison_agent]
    S --> A4[news_and_research_agent]
    S --> A5[document_retrieval_agent]
    S --> A6[valuation_agent]

    A1 --> M1[NSE MCP Server<br/>mcp_servers/nse_server.py<br/>:8001]
    A2 --> M2[Fundamentals MCP Server<br/>mcp_servers/fundamentals_server.py<br/>:8002]
    A3 --> M2
    A4 --> M3[Research MCP Server<br/>mcp_servers/research_server.py<br/>:8003]
    A5 --> M4[Docs MCP Server<br/>mcp_servers/docs_server.py<br/>:8004]
    A5 --> M3
    A6 --> M5[Valuation MCP Server<br/>mcp_servers/mcp_valuation.py<br/>:8005]

    M1 --> X1[NSE India / NseIndiaApi]
    M2 --> X2[yfinance / Yahoo Finance]
    M3 --> X3[Tavily Search + Extract]
    M4 --> X3
    M4 --> X4[Qdrant Vector DB]
    M5 --> X2
    M5 --> X5[valuation_engine.py]

    G --> OAI[OpenAI Chat Model]

    API -->|SSE events| F
    F --> P[Live Process Panel<br/>sub-agents, steps, source domains]
```

## Runtime Request Flow

```mermaid
sequenceDiagram
    participant User
    participant Frontend as Next.js Frontend
    participant API as FastAPI
    participant Graph as LangGraph Supervisor
    participant Agents as Specialist Agents
    participant MCP as MCP Servers
    participant Providers as External Providers

    User->>Frontend: Submit finance query
    Frontend->>API: POST /api/chat/stream
    API->>API: Plan agents from query
    API->>Graph: Run supervisor with routing hints
    Graph->>Agents: Delegate to one or more sub-agents
    Agents->>MCP: Call specialist tools
    MCP->>Providers: Fetch live data / documents / news / valuation inputs
    Providers-->>MCP: Return data
    MCP-->>Agents: Return tool results
    Agents-->>Graph: Return specialist output
    Graph-->>API: Final synthesized answer
    API-->>Frontend: SSE stream with status, agents, sources, final answer
    Frontend-->>User: Chat answer + live sub-agent/process view
```

## Component Breakdown

### 1. Frontend
- `Frontend/app/page.tsx`
- Sends chat requests to the backend
- Consumes streaming SSE events
- Shows:
  - chat response
  - active/planned/completed sub-agents
  - process steps
  - source website domains

### 2. Backend API
- `Backend/api.py`
- Exposes:
  - `POST /api/chat`
  - `POST /api/chat/stream`
  - `GET /health`
- Responsibilities:
  - build and cache the graph
  - compute query-to-agent routing hints
  - stream progress events to the frontend
  - handle fallback, timeout, and provider errors

### 3. LangGraph Supervisor Layer
- `Backend/graph.py`
- Builds the multi-agent system from live MCP tools
- Creates these specialist agents:
  - `market_data_agent`
  - `fundamental_analysis_agent`
  - `comparison_agent`
  - `news_and_research_agent`
  - `document_retrieval_agent`
  - `valuation_agent`
- Uses OpenAI for reasoning and synthesis

### 4. MCP Server Layer

#### `:8001` NSE Market Data
- `Backend/mcp_servers/nse_server.py`
- Tools for:
  - live quote
  - historical prices
  - option chain
  - shareholding
  - announcements
  - board meetings

#### `:8002` Fundamentals
- `Backend/mcp_servers/fundamentals_server.py`
- Tools for:
  - profile
  - statements
  - ratios
  - quarterly results
  - peer comparison
  - dividend history

#### `:8003` Research & News
- `Backend/mcp_servers/research_server.py`
- Tools for:
  - web search
  - finance search
  - news search
  - URL extraction

#### `:8004` Documents Pipeline
- `Backend/mcp_servers/docs_server.py`
- Tools for:
  - document search
  - PDF ingest
  - URL ingest
  - annual report fetch
  - DRHP/RHP/prospectus comparison
- Uses Qdrant for indexed document retrieval

#### `:8005` Valuation Engine
- `Backend/mcp_servers/mcp_valuation.py`
- Backed by `Backend/valuation_engine.py`
- Tools for:
  - DCF
  - PE valuation
  - Graham valuation
  - EV/EBITDA
  - DDM
  - WACC
  - CAGR
  - Piotroski
  - Altman Z
  - DuPont
  - full valuation

## Data and Control Boundaries

```mermaid
flowchart LR
    subgraph UI[Presentation Layer]
        FE[Next.js UI]
    end

    subgraph APP[Application Layer]
        API[FastAPI]
        LG[LangGraph Supervisor]
    end

    subgraph TOOLS[Tooling Layer]
        MCP1[NSE MCP]
        MCP2[Fundamentals MCP]
        MCP3[Research MCP]
        MCP4[Docs MCP]
        MCP5[Valuation MCP]
    end

    subgraph DATA[Data Layer]
        QD[Qdrant]
        VE[valuation_engine.py]
        NSE[NSE]
        YF[yfinance]
        TV[Tavily]
    end

    FE --> API
    API --> LG
    LG --> MCP1
    LG --> MCP2
    LG --> MCP3
    LG --> MCP4
    LG --> MCP5
    MCP4 --> QD
    MCP5 --> VE
    MCP1 --> NSE
    MCP2 --> YF
    MCP5 --> YF
    MCP3 --> TV
    MCP4 --> TV
```

## Operational Notes

- MCP server registry: `Backend/mcp_config.py`
- MCP startup script: `Backend/start_servers.ps1`
- MCP shutdown script: `Backend/stop_servers.ps1`
- If MCP servers are down, the backend can enter fallback mode and live financial analysis will not work correctly.
- The frontend sub-agent panel depends on streamed events from `api.py`.

## Current Design Intent

- Keep the UI thin
- Keep orchestration in FastAPI + LangGraph
- Keep data acquisition and calculations in MCP servers
- Keep deterministic finance math in `valuation_engine.py`
- Keep document memory in Qdrant
- Keep live process visibility in the frontend

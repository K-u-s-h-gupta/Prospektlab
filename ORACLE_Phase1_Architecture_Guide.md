# ORACLE Phase 1 — Complete Architecture & Implementation Guide
## How to Build It: Technologies, Tools, and Step-by-Step Architecture
### May 2026

---

## TABLE OF CONTENTS

1. [System Architecture Overview](#1-system-architecture-overview)
2. [Technology Stack (Complete)](#2-technology-stack)
3. [Backend Architecture — The AI Brain](#3-backend-architecture)
4. [MCP Servers — Your Data Layer](#4-mcp-servers)
5. [Multi-Agent System — LangGraph Supervisor](#5-multi-agent-system)
6. [RAG Pipeline — Qdrant + Embeddings](#6-rag-pipeline)
7. [Frontend Architecture — Next.js + assistant-ui](#7-frontend-architecture)
8. [Generative UI — Streaming React Components](#8-generative-ui)
9. [Project Structure & File Layout](#9-project-structure)
10. [Infrastructure & Deployment](#10-infrastructure)
11. [API Keys & Services You Need](#11-api-keys)
12. [Build Sequence — What to Build First](#12-build-sequence)

---

## 1. SYSTEM ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER (Browser)                                │
│                     Next.js 16 App (React 19)                        │
│              assistant-ui Chat + Canvas Layout                       │
│         Generative UI Components (Cards, Charts, Tables)             │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ WebSocket / SSE Stream
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    LANGGRAPH PLATFORM                                 │
│                                                                      │
│  ┌─────────────┐    ┌──────────────────────────────────────────┐    │
│  │  SUPERVISOR  │───▶│           SUB-AGENTS                     │    │
│  │   AGENT      │    │                                          │    │
│  │ (Router +    │    │  📊 Market Data Agent                    │    │
│  │  Planner)    │    │  📈 Fundamental Analysis Agent           │    │
│  │              │    │  📰 News & Sentiment Agent               │    │
│  └──────┬───────┘    │  🧮 Valuation Agent                     │    │
│         │            │  🔍 Screening Agent                      │    │
│         │            │  📚 Education Agent                      │    │
│         │            └──────────────┬───────────────────────────┘    │
│         │                           │                                │
│         ▼                           ▼                                │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │           langchain-mcp-adapters (MultiServerMCPClient)      │    │
│  └──────────────────────────┬──────────────────────────────────┘    │
│                              │                                       │
└──────────────────────────────┼───────────────────────────────────────┘
                               │
          ┌────────────────────┼─────────────────────┐
          ▼                    ▼                      ▼
┌──────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  MCP Server  │   │   MCP Server     │   │   MCP Server     │
│  NSE India   │   │   FMP (Global    │   │   News &         │
│  (FastMCP)   │   │   Fundamentals)  │   │   Sentiment      │
│              │   │                  │   │   (FastMCP)      │
│ • Live quotes│   │ • Income stmt    │   │ • RSS feeds      │
│ • Bhavcopy   │   │ • Balance sheet  │   │ • MoneyControl   │
│ • Option     │   │ • Cash flow      │   │ • Economic Times │
│   chain      │   │ • Ratios         │   │ • Sentiment      │
│ • Index data │   │ • Peer compare   │   │   scoring        │
│ • Historical │   │ • DCF inputs     │   │                  │
└──────────────┘   └──────────────────┘   └──────────────────┘

          ┌────────────────────┐
          ▼                    ▼
┌──────────────────┐   ┌──────────────────┐
│   Qdrant         │   │   PostgreSQL     │
│   (Vector DB)    │   │   (App State)    │
│                  │   │                  │
│ • Annual reports │   │ • User sessions  │
│ • Con-call       │   │ • Chat history   │
│   transcripts    │   │ • Watchlists     │
│ • Research notes │   │ • Saved analyses │
│ • SEBI filings   │   │                  │
└──────────────────┘   └──────────────────┘
```

### How a Query Flows Through ORACLE

```
User: "Compare TCS vs Infosys — which is better for long term?"
  │
  ▼
1. Frontend sends message via assistant-ui → LangGraph endpoint
  │
  ▼
2. SUPERVISOR AGENT receives query, classifies intent: "comparison"
   Plans: need fundamentals for both + valuation + recent news
  │
  ▼
3. Supervisor dispatches to SUB-AGENTS in parallel:
   ├─ Market Data Agent → calls NSE MCP: get_quote("TCS"), get_quote("INFY")
   ├─ Fundamental Agent → calls FMP MCP: get_financials("TCS.NS"), get_financials("INFY.NS")
   ├─ News Agent → calls News MCP: get_news("TCS"), get_news("Infosys")
   └─ Valuation Agent → calculates PE, PB, DCF for both
  │
  ▼
4. Each agent streams back structured JSON results
  │
  ▼
5. Supervisor aggregates results → produces verdict
  │
  ▼
6. LangGraph emits UI message: push_ui_message("ComparisonTable", data)
  │
  ▼
7. Frontend renders <ComparisonTable> component on Canvas
   with animated charts, side-by-side metrics, verdict badge
```

---

## 2. TECHNOLOGY STACK (COMPLETE)

### Backend (Python)

| Technology | Version | Purpose | Install |
|---|---|---|---|
| **Python** | 3.12+ | Runtime | — |
| **LangGraph** | 0.3+ | Agent orchestration, state machine | `pip install langgraph` |
| **langgraph-supervisor** | latest | Prebuilt supervisor pattern | `pip install langgraph-supervisor` |
| **langchain-mcp-adapters** | latest | Connect LangGraph agents to MCP tools | `pip install langchain-mcp-adapters` |
| **FastMCP** | 2.0+ | Build your own MCP servers | `pip install fastmcp` |
| **LangChain** | 0.3+ | LLM abstraction, embeddings, chains | `pip install langchain langchain-openai` |
| **Qdrant** | latest | Vector DB for RAG | `pip install qdrant-client` |
| **jugaad-data** | latest | NSE India historical + live data | `pip install jugaad-data` |
| **nsetools** | 2.0+ | NSE real-time quotes | `pip install nsetools` |
| **FinanceToolkit** | latest | Financial calculations (ratios, DCF) | `pip install financetoolkit` |
| **httpx** | latest | Async HTTP client for API calls | `pip install httpx` |
| **FastAPI** | latest | API layer (if self-hosting) | `pip install fastapi uvicorn` |
| **PostgreSQL** | 16+ | App database (users, sessions) | Docker / Supabase |

### Frontend (TypeScript/React)

| Technology | Version | Purpose | Install |
|---|---|---|---|
| **Next.js** | 15/16 | React framework (App Router) | `npx create-next-app@latest` |
| **assistant-ui** | latest | ⭐ THE chat UI library for AI apps | `npx assistant-ui@latest init` |
| **@langchain/langgraph-sdk** | latest | LangGraph React hooks (`useStream`) | `npm install @langchain/langgraph-sdk` |
| **shadcn/ui** | latest | Component library (Tailwind-based) | `npx shadcn@latest init` |
| **Tailwind CSS** | v4 | Utility-first CSS | Included with Next.js |
| **Recharts** | 2.x | Charts (bar, line, pie, area) | `npm install recharts` |
| **lightweight-charts** | 4.x | TradingView candlestick charts | `npm install lightweight-charts` |
| **Framer Motion** | 12+ | Animations | `npm install framer-motion` |
| **Lucide React** | latest | Icons | `npm install lucide-react` |
| **nuqs** | latest | URL state management | `npm install nuqs` |

### LLM Provider

| Option | Best For | Cost |
|---|---|---|
| **GPT-4.1** (OpenAI) | Best tool-calling, reliable JSON output | ~$2/M input, $8/M output |
| **Claude Sonnet 4** | Best reasoning, nuanced analysis | ~$3/M input, $15/M output |
| **Gemini 2.5 Flash** | Cheapest, fastest, good enough for routing | ~$0.15/M input |
| **Recommendation** | Use **Gemini Flash for Supervisor routing** + **GPT-4.1 for analysis agents** | Hybrid approach |

---

## 3. BACKEND ARCHITECTURE — THE AI BRAIN

### 3.1 LangGraph — Why This is the Core

LangGraph is a **state machine for AI agents**. It's NOT just "LangChain with graphs." Here's why it's perfect for ORACLE:

- **Stateful**: Each conversation maintains state (what data was fetched, what analysis was done)
- **Multi-agent**: Built-in supervisor and swarm patterns
- **Streaming**: Streams tokens + tool calls + UI components to frontend in real-time
- **Persistent**: Can save/resume conversations (checkpointing)
- **Human-in-the-loop**: Can pause for user input (e.g., "Do you want me to run DCF with these assumptions?")

### 3.2 The Supervisor Pattern

```python
# backend/graph.py — THE CORE OF ORACLE

from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph_supervisor import create_supervisor
from langgraph.prebuilt import create_react_agent
from langchain_mcp_adapters.client import MultiServerMCPClient

# --- LLM Configuration ---
router_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")  # Fast, cheap for routing
analysis_llm = ChatOpenAI(model="gpt-4.1")  # Smart, reliable for analysis

# --- MCP Client (connects to all your data servers) ---
mcp_client = MultiServerMCPClient({
    "nse_india": {
        "url": "http://localhost:8001/mcp",
        "transport": "streamable_http",
    },
    "fundamentals": {
        "url": "http://localhost:8002/mcp",
        "transport": "streamable_http",
    },
    "news": {
        "url": "http://localhost:8003/mcp",
        "transport": "streamable_http",
    },
})

# Get all tools from all MCP servers
all_tools = await mcp_client.get_tools()

# Partition tools by domain
nse_tools = [t for t in all_tools if t.name.startswith("nse_")]
fundamental_tools = [t for t in all_tools if t.name.startswith("fmp_")]
news_tools = [t for t in all_tools if t.name.startswith("news_")]

# --- Sub-Agents (each is a specialist) ---
market_data_agent = create_react_agent(
    model=analysis_llm,
    tools=nse_tools,
    name="market_data_agent",
    prompt=(
        "You are a market data specialist for Indian stocks. "
        "You fetch live prices, historical data, option chains, and index data from NSE. "
        "Always return structured JSON with: symbol, price, change_pct, volume, "
        "52w_high, 52w_low. For historical data, return OHLCV arrays."
    ),
)

fundamental_agent = create_react_agent(
    model=analysis_llm,
    tools=fundamental_tools,
    name="fundamental_analysis_agent",
    prompt=(
        "You are a fundamental analysis expert for Indian companies. "
        "You fetch and analyze income statements, balance sheets, cash flows, "
        "and key ratios. Always calculate: ROE, ROCE, debt-to-equity, "
        "operating margin, PAT growth (3Y/5Y CAGR). Compare with industry averages."
    ),
)

news_agent = create_react_agent(
    model=analysis_llm,
    tools=news_tools,
    name="news_sentiment_agent",
    prompt=(
        "You are a news and sentiment analyst for Indian markets. "
        "Fetch latest news, analyze sentiment (bullish/bearish/neutral), "
        "identify key themes, and flag any red flags (regulatory issues, "
        "management changes, fraud allegations)."
    ),
)

valuation_agent = create_react_agent(
    model=analysis_llm,
    tools=fundamental_tools,  # Reuses fundamental data
    name="valuation_agent",
    prompt=(
        "You are a valuation expert. Calculate fair value using: "
        "1) PE relative valuation (vs sector, vs historical) "
        "2) DCF with explicit assumptions (revenue growth, margins, WACC, terminal growth) "
        "3) PB valuation for banks/NBFCs. "
        "Always state your assumptions clearly and give a bull/base/bear case."
    ),
)

screening_agent = create_react_agent(
    model=analysis_llm,
    tools=fundamental_tools + nse_tools,
    name="screening_agent",
    prompt=(
        "You are a stock screener. Convert natural language queries into "
        "structured screening criteria. Example: 'high growth midcaps' → "
        "market_cap: 5000-50000 Cr, revenue_growth_3y > 15%, ROE > 15%. "
        "Return top matches as a sorted table with key metrics."
    ),
)

education_agent = create_react_agent(
    model=analysis_llm,
    tools=[],  # No tools needed — pure LLM knowledge
    name="education_agent",
    prompt=(
        "You are a financial education expert who explains concepts in simple "
        "Hindi-English (Hinglish). Use real Indian company examples. "
        "Explain formulas visually. Target audience: Indian retail investors "
        "who are smart but may not know jargon."
    ),
)

# --- Supervisor (the orchestrator) ---
oracle_graph = create_supervisor(
    model=router_llm,  # Cheap Gemini Flash for routing decisions
    agents=[
        market_data_agent,
        fundamental_agent,
        news_agent,
        valuation_agent,
        screening_agent,
        education_agent,
    ],
    prompt=(
        "You are ORACLE, an AI-powered Indian stock market research assistant. "
        "Route user queries to the appropriate specialist agents. "
        "For complex queries, dispatch to MULTIPLE agents in parallel. "
        "Examples:\n"
        "- 'Analyze TCS' → market_data + fundamental + news + valuation\n"
        "- 'Compare TCS vs Infosys' → fundamental + valuation (for both)\n"
        "- 'What is PE ratio?' → education\n"
        "- 'Find undervalued IT stocks' → screening\n"
        "- 'TCS stock price' → market_data only\n\n"
        "After all agents respond, synthesize a final verdict. "
        "Always be specific with numbers and cite data sources."
    ),
)

# Compile the graph
app = oracle_graph.compile()
```

### 3.3 How the Supervisor Works Internally

```
User Query
    │
    ▼
┌───────────────┐
│   SUPERVISOR   │ ← Gemini Flash (cheap, fast)
│   Decides:     │
│   1. Which     │
│      agents    │
│   2. In what   │
│      order     │
│   3. What data │
│      to pass   │
└───────┬───────┘
        │
        ├──► Agent A (parallel) ──► MCP Tools ──► Results
        ├──► Agent B (parallel) ──► MCP Tools ──► Results
        └──► Agent C (parallel) ──► MCP Tools ──► Results
                                                    │
                                                    ▼
                                            ┌───────────────┐
                                            │   SUPERVISOR   │
                                            │   Aggregates   │
                                            │   + Synthesizes│
                                            │   Final Answer │
                                            └───────────────┘
```

---

## 4. MCP SERVERS — YOUR DATA LAYER

MCP (Model Context Protocol) servers are **standalone microservices** that expose data/tools to AI agents. You need to build 3 custom ones:

### 4.1 NSE India MCP Server (FastMCP)

```python
# mcp_servers/nse_server.py

from fastmcp import FastMCP
from jugaad_data.nse import stock_df, NSELive
from nsetools import Nse
import httpx
from datetime import date, timedelta

mcp = FastMCP(name="NSEIndiaServer")
nse = Nse()
nse_live = NSELive()

@mcp.tool
def nse_get_quote(symbol: str) -> dict:
    """Get real-time stock quote from NSE India.
    Returns: price, change, change_pct, volume, 52w high/low, market cap."""
    try:
        q = nse_live.stock_quote(symbol.upper())
        price_info = q.get("priceInfo", {})
        return {
            "symbol": symbol.upper(),
            "price": price_info.get("lastPrice"),
            "change": price_info.get("change"),
            "change_pct": price_info.get("pChange"),
            "open": price_info.get("open"),
            "high": price_info.get("intraDayHighLow", {}).get("max"),
            "low": price_info.get("intraDayHighLow", {}).get("min"),
            "prev_close": price_info.get("previousClose"),
            "volume": q.get("securityWiseDP", {}).get("quantityTraded"),
            "week_52_high": price_info.get("weekHighLow", {}).get("max"),
            "week_52_low": price_info.get("weekHighLow", {}).get("min"),
        }
    except Exception as e:
        return {"error": str(e), "symbol": symbol}

@mcp.tool
def nse_get_historical(symbol: str, days: int = 365) -> list:
    """Get historical OHLCV data for a stock from NSE.
    Returns list of {date, open, high, low, close, volume}."""
    end = date.today()
    start = end - timedelta(days=days)
    df = stock_df(symbol=symbol.upper(), from_date=start, to_date=end)
    return df[["DATE", "OPEN", "HIGH", "LOW", "CLOSE", "VOLUME"]].to_dict("records")

@mcp.tool
def nse_get_option_chain(symbol: str) -> dict:
    """Get option chain data for a stock/index from NSE."""
    data = nse_live.equities_option_chain(symbol.upper())
    return {
        "underlying_value": data.get("records", {}).get("underlyingValue"),
        "expiry_dates": data.get("records", {}).get("expiryDates", [])[:5],
        "total_ce_oi": data.get("filtered", {}).get("CE", {}).get("totOI"),
        "total_pe_oi": data.get("filtered", {}).get("PE", {}).get("totOI"),
        "pcr": round(
            data["filtered"]["PE"]["totOI"] / data["filtered"]["CE"]["totOI"], 2
        ) if data.get("filtered") else None,
    }

@mcp.tool
def nse_get_index(index_name: str = "NIFTY 50") -> dict:
    """Get live index data (NIFTY 50, NIFTY BANK, etc.)."""
    data = nse_live.live_index(index_name)
    return data

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8001)
```

### 4.2 Fundamentals MCP Server (FMP API)

```python
# mcp_servers/fundamentals_server.py

from fastmcp import FastMCP
import httpx
import os

mcp = FastMCP(name="FundamentalsServer")
FMP_KEY = os.getenv("FMP_API_KEY")
BASE = "https://financialmodelingprep.com/stable"

async def fmp_get(endpoint: str, params: dict = {}) -> dict:
    params["apikey"] = FMP_KEY
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{BASE}/{endpoint}", params=params)
        return r.json()

@mcp.tool
async def fmp_income_statement(symbol: str, period: str = "annual", limit: int = 5) -> list:
    """Get income statement for a company. Period: annual or quarter."""
    # For Indian stocks, FMP uses .NS suffix (e.g., TCS.NS)
    ticker = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
    return await fmp_get("income-statement", {
        "symbol": ticker, "period": period, "limit": limit
    })

@mcp.tool
async def fmp_balance_sheet(symbol: str, period: str = "annual", limit: int = 5) -> list:
    """Get balance sheet for a company."""
    ticker = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
    return await fmp_get("balance-sheet-statement", {
        "symbol": ticker, "period": period, "limit": limit
    })

@mcp.tool
async def fmp_cash_flow(symbol: str, period: str = "annual", limit: int = 5) -> list:
    """Get cash flow statement for a company."""
    ticker = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
    return await fmp_get("cash-flow-statement", {
        "symbol": ticker, "period": period, "limit": limit
    })

@mcp.tool
async def fmp_key_metrics(symbol: str, period: str = "annual", limit: int = 5) -> list:
    """Get key financial metrics/ratios: PE, PB, ROE, ROA, etc."""
    ticker = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
    return await fmp_get("key-metrics", {
        "symbol": ticker, "period": period, "limit": limit
    })

@mcp.tool
async def fmp_company_profile(symbol: str) -> dict:
    """Get company profile: sector, industry, description, market cap, employees."""
    ticker = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
    data = await fmp_get("profile", {"symbol": ticker})
    return data[0] if data else {}

@mcp.tool
async def fmp_peers(symbol: str) -> list:
    """Get peer/comparable companies for a stock."""
    ticker = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
    return await fmp_get("stock_peers", {"symbol": ticker})

@mcp.tool
async def fmp_dcf(symbol: str) -> dict:
    """Get pre-calculated DCF fair value for a stock."""
    ticker = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
    data = await fmp_get("discounted-cash-flow", {"symbol": ticker})
    return data[0] if data else {}

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8002)
```

### 4.3 News & Sentiment MCP Server

```python
# mcp_servers/news_server.py

from fastmcp import FastMCP
import httpx
import os
from datetime import datetime

mcp = FastMCP(name="NewsServer")
FMP_KEY = os.getenv("FMP_API_KEY")

@mcp.tool
async def news_get_stock_news(symbol: str, limit: int = 10) -> list:
    """Get latest news for a specific stock."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://financialmodelingprep.com/stable/news/stock-latest",
            params={"symbol": f"{symbol}.NS", "limit": limit, "apikey": FMP_KEY}
        )
        articles = r.json()
        return [{
            "title": a.get("title"),
            "source": a.get("site"),
            "date": a.get("publishedDate"),
            "url": a.get("url"),
            "snippet": a.get("text", "")[:300],
        } for a in articles]

@mcp.tool
async def news_get_market_news(limit: int = 15) -> list:
    """Get general Indian market news."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://financialmodelingprep.com/stable/news/general-latest",
            params={"limit": limit, "apikey": FMP_KEY}
        )
        return [{
            "title": a.get("title"),
            "source": a.get("site"),
            "date": a.get("publishedDate"),
            "snippet": a.get("text", "")[:300],
        } for a in r.json()]

@mcp.tool
async def news_sentiment_score(symbol: str) -> dict:
    """Analyze sentiment for a stock based on recent news.
    Returns: overall_sentiment, score (-1 to 1), bullish_count, bearish_count."""
    # In production, use a proper NLP model. For MVP, use LLM-based scoring.
    news = await news_get_stock_news(symbol, limit=15)
    # This is a simplified version — in production, run sentiment model
    return {
        "symbol": symbol,
        "news_count": len(news),
        "latest_headlines": [n["title"] for n in news[:5]],
        "note": "Sentiment scoring done by analysis agent using these headlines"
    }

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8003)
```

### 4.4 How MCP Servers Connect to LangGraph

```python
# backend/mcp_config.py — Configuration for all MCP servers

MCP_SERVERS = {
    "nse_india": {
        "url": "http://localhost:8001/mcp",
        "transport": "streamable_http",
    },
    "fundamentals": {
        "url": "http://localhost:8002/mcp",
        "transport": "streamable_http",
    },
    "news": {
        "url": "http://localhost:8003/mcp",
        "transport": "streamable_http",
    },
}

# In your graph setup:
from langchain_mcp_adapters.client import MultiServerMCPClient

async def get_all_tools():
    async with MultiServerMCPClient(MCP_SERVERS) as client:
        tools = await client.get_tools()
        return tools

# Tools are now LangChain-compatible and can be passed to any agent
```

---

## 5. MULTI-AGENT SYSTEM — DEEP DIVE

### 5.1 Agent Responsibilities

| Agent | Triggers On | MCP Tools Used | Output Format |
|---|---|---|---|
| **Market Data** | "price of X", "chart of X", "how is market" | `nse_get_quote`, `nse_get_historical`, `nse_get_index` | `{price, change, ohlcv[]}` |
| **Fundamental** | "analyze X", "financials of X", "how is X doing" | `fmp_income_statement`, `fmp_balance_sheet`, `fmp_key_metrics` | `{revenue, profit, ratios{}}` |
| **News** | "news about X", "any red flags in X" | `news_get_stock_news`, `news_sentiment_score` | `{articles[], sentiment}` |
| **Valuation** | "fair value of X", "is X overvalued" | `fmp_key_metrics`, `fmp_dcf` | `{pe_val, dcf_val, verdict}` |
| **Screening** | "find stocks with...", "undervalued midcaps" | `fmp_key_metrics` + loop | `{criteria{}, results[]}` |
| **Education** | "what is PE ratio", "explain DCF" | None (pure LLM) | `{concept, formula, example}` |

### 5.2 Parallel Execution

The supervisor can dispatch multiple agents simultaneously:

```python
# When user says "Analyze TCS", supervisor routes to:
# 1. market_data_agent → fetches live price, 1Y chart
# 2. fundamental_agent → fetches financials, ratios
# 3. news_agent → fetches latest news, sentiment
# 4. valuation_agent → calculates fair value
#
# All 4 run IN PARALLEL, then supervisor aggregates
```

This is built into `langgraph-supervisor` — you don't need to code parallelism manually.

### 5.3 Streaming Agent Progress to Frontend

```python
# The LangGraph platform streams events to the frontend.
# Each agent's tool call and result is streamed as an event:

# Event stream looks like:
# {"agent": "market_data_agent", "status": "started"}
# {"agent": "market_data_agent", "tool": "nse_get_quote", "status": "calling"}
# {"agent": "market_data_agent", "tool": "nse_get_quote", "result": {...}}
# {"agent": "market_data_agent", "status": "completed"}
# {"agent": "fundamental_agent", "status": "started"}
# ... etc

# Frontend uses these events to power the "Agent Thinking" indicator
```

---

## 6. RAG PIPELINE — QDRANT + EMBEDDINGS

### 6.1 What Goes Into the Vector DB

| Document Type | Source | Update Frequency |
|---|---|---|
| Annual Reports (PDFs) | BSE/NSE filings | Yearly |
| Quarterly Results | BSE/NSE filings | Quarterly |
| Con-call Transcripts | Trendlyne / manual | Quarterly |
| Broker Research Reports | Manual upload | Ad-hoc |
| SEBI Circulars | SEBI website | Weekly |
| RBI Policy Documents | RBI website | Monthly |

### 6.2 Ingestion Pipeline

```python
# backend/rag/ingest.py

from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
import os

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION = "oracle_documents"

embeddings = OpenAIEmbeddings(model="text-embedding-3-small")  # 1536 dims, cheap

client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

# Create collection (run once)
client.create_collection(
    collection_name=COLLECTION,
    vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
)

# Text splitter tuned for financial documents
splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=200,
    separators=["\n\n", "\n", ". ", " "],
)

def ingest_document(text: str, metadata: dict):
    """Ingest a document into Qdrant.
    metadata should include: company, doc_type, date, source_url
    """
    chunks = splitter.split_text(text)
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=COLLECTION,
        embedding=embeddings,
    )
    metadatas = [{**metadata, "chunk_index": i} for i in range(len(chunks))]
    vector_store.add_texts(texts=chunks, metadatas=metadatas)
    return len(chunks)

def search_documents(query: str, company: str = None, top_k: int = 5):
    """Search vector DB for relevant document chunks."""
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=COLLECTION,
        embedding=embeddings,
    )
    filter_dict = None
    if company:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        filter_dict = Filter(must=[
            FieldCondition(key="metadata.company", match=MatchValue(value=company))
        ])
    results = vector_store.similarity_search(query, k=top_k, filter=filter_dict)
    return results
```

### 6.3 RAG as an MCP Tool

```python
# Add to any MCP server or create a dedicated RAG MCP server

@mcp.tool
def rag_search(query: str, company: str = None, doc_type: str = None) -> list:
    """Search ORACLE's knowledge base of annual reports, con-call transcripts,
    and research documents. Use this when the user asks about specific
    management commentary, guidance, or document-specific information."""
    results = search_documents(query, company=company)
    return [{
        "content": r.page_content,
        "company": r.metadata.get("company"),
        "doc_type": r.metadata.get("doc_type"),
        "date": r.metadata.get("date"),
        "source": r.metadata.get("source_url"),
    } for r in results]
```

---

## 7. FRONTEND ARCHITECTURE — NEXT.JS + ASSISTANT-UI

### 7.1 Project Setup

```bash
# Step 1: Create Next.js project with assistant-ui LangGraph template
npx create-assistant-ui@latest -t langgraph oracle-frontend
cd oracle-frontend

# Step 2: Install additional dependencies
npm install recharts lightweight-charts framer-motion lucide-react nuqs
npm install @radix-ui/react-tabs @radix-ui/react-tooltip @radix-ui/react-slider

# Step 3: Initialize shadcn/ui
npx shadcn@latest init
npx shadcn@latest add card badge tabs table separator skeleton
```

### 7.2 The Chat + Canvas Layout

```tsx
// app/page.tsx — The main layout

"use client";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useLangGraphRuntime } from "@assistant-ui/react-langgraph";
import { ChatPanel } from "@/components/chat-panel";
import { CanvasPanel } from "@/components/canvas-panel";

export default function OraclePage() {
  const runtime = useLangGraphRuntime({
    threadId: undefined, // auto-creates new thread
    stream: async function* (messages, config) {
      // Connect to your LangGraph backend
      const response = await fetch("/api/chat", {
        method: "POST",
        body: JSON.stringify({ messages }),
      });
      // Stream the response
      yield* streamResponse(response);
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex h-screen bg-background">
        {/* Chat Panel — 40% width */}
        <div className="w-[40%] border-r border-border flex flex-col">
          <ChatPanel />
        </div>

        {/* Canvas Panel — 60% width */}
        <div className="w-[60%] flex flex-col overflow-y-auto">
          <CanvasPanel />
        </div>
      </div>
    </AssistantRuntimeProvider>
  );
}
```

### 7.3 assistant-ui Integration with LangGraph

```tsx
// components/chat-panel.tsx

"use client";
import { Thread, Composer, ThreadPrimitive } from "@assistant-ui/react";
import { AgentThinkingIndicator } from "./generative-ui/agent-thinking";

export function ChatPanel() {
  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-border">
        <h1 className="text-lg font-semibold text-purple-400">
          🔮 ORACLE
        </h1>
        <p className="text-xs text-muted-foreground">
          AI-Powered Indian Market Intelligence
        </p>
      </div>

      {/* Message Thread */}
      <Thread
        assistantMessage={{
          components: {
            // This is where Generative UI magic happens!
            // assistant-ui renders custom components based on
            // the type field in the streamed message
            Text: ({ content }) => (
              <div className="prose prose-invert prose-sm">
                {content}
              </div>
            ),
          },
        }}
      />

      {/* Composer (Input) */}
      <div className="p-4 border-t border-border">
        <Composer
          placeholder="Ask about any Indian stock... (e.g., 'Analyze TCS')"
        />
      </div>
    </div>
  );
}
```

### 7.4 Canvas Panel — Where Generative UI Lives

```tsx
// components/canvas-panel.tsx

"use client";
import { useStream } from "@langchain/langgraph-sdk/react";
import { LoadExternalComponent } from "@langchain/langgraph-sdk/react-ui";
import { motion, AnimatePresence } from "framer-motion";

export function CanvasPanel() {
  const { thread, values } = useStream({
    apiUrl: process.env.NEXT_PUBLIC_LANGGRAPH_URL!,
    assistantId: "oracle",
  });

  return (
    <div className="p-6 space-y-4">
      {/* Welcome state when no components */}
      {!values?.ui?.length && (
        <WelcomeScreen />
      )}

      {/* Rendered Generative UI components */}
      <AnimatePresence mode="popLayout">
        {values?.ui?.map((uiMessage, i) => (
          <motion.div
            key={uiMessage.id}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.1 }}
          >
            <LoadExternalComponent
              stream={thread}
              message={uiMessage}
            />
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

function WelcomeScreen() {
  const suggestions = [
    "Analyze TCS — full company intelligence",
    "Compare HDFC Bank vs ICICI Bank",
    "Find undervalued IT stocks with ROE > 20%",
    "What is the fair value of Reliance?",
    "Explain P/E ratio with Indian examples",
  ];

  return (
    <div className="flex flex-col items-center justify-center h-full text-center">
      <div className="text-6xl mb-4">🔮</div>
      <h2 className="text-2xl font-bold mb-2">Welcome to ORACLE</h2>
      <p className="text-muted-foreground mb-8">
        Ask me anything about Indian stocks
      </p>
      <div className="grid grid-cols-1 gap-2 max-w-md">
        {suggestions.map((s) => (
          <button
            key={s}
            className="text-left p-3 rounded-lg border border-border
                       hover:border-purple-500 hover:bg-purple-500/10
                       transition-colors text-sm"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
```

---

## 8. GENERATIVE UI — STREAMING REACT COMPONENTS

### 8.1 How It Works (The Key Innovation)

Instead of returning text, your LangGraph backend emits **UI messages** that tell the frontend to render specific React components with specific data:

```python
# In your LangGraph agent (Python backend):
from langgraph.types import UIMessage

def emit_company_card(state, config):
    # After fetching all data...
    push_ui_message(
        config,
        message="CompanyIntelligenceCard",
        data={
            "symbol": "TCS",
            "price": 4250.50,
            "change_pct": 1.2,
            "pe_ratio": 32.5,
            "roe": 45.2,
            "revenue_growth_3y": 12.5,
            "financials": [...],
            "chart_data": [...],
        }
    )
```

```tsx
// Frontend registers the component:
// components/generative-ui/company-card.tsx

"use client";
import { Card, CardHeader, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { motion } from "framer-motion";
import { TrendingUp, TrendingDown, Shield } from "lucide-react";

interface CompanyCardProps {
  symbol: string;
  price: number;
  change_pct: number;
  pe_ratio: number;
  roe: number;
  revenue_growth_3y: number;
  financials: any[];
  chart_data: any[];
}

export function CompanyIntelligenceCard(props: CompanyCardProps) {
  const isPositive = props.change_pct >= 0;

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
    >
      <Card className="bg-zinc-900 border-zinc-800">
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <h3 className="text-xl font-bold">{props.symbol}</h3>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-2xl font-mono font-bold">
                ₹{props.price.toLocaleString("en-IN")}
              </span>
              <Badge variant={isPositive ? "default" : "destructive"}>
                {isPositive ? <TrendingUp className="w-3 h-3 mr-1" /> : <TrendingDown className="w-3 h-3 mr-1" />}
                {isPositive ? "+" : ""}{props.change_pct.toFixed(2)}%
              </Badge>
            </div>
          </div>
          <Badge variant="outline" className="border-green-500 text-green-500">
            <Shield className="w-3 h-3 mr-1" /> VERIFIED
          </Badge>
        </CardHeader>

        <CardContent>
          {/* Price Chart */}
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={props.chart_data}>
              <defs>
                <linearGradient id="gradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#6C5CE7" stopOpacity={0.3} />
                  <stop offset="100%" stopColor="#6C5CE7" stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="date" hide />
              <YAxis hide domain={["auto", "auto"]} />
              <Tooltip />
              <Area
                type="monotone"
                dataKey="close"
                stroke="#6C5CE7"
                fill="url(#gradient)"
                strokeWidth={2}
              />
            </AreaChart>
          </ResponsiveContainer>

          {/* Key Metrics */}
          <Tabs defaultValue="overview" className="mt-4">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="financials">Financials</TabsTrigger>
              <TabsTrigger value="valuation">Valuation</TabsTrigger>
            </TabsList>
            <TabsContent value="overview">
              <div className="grid grid-cols-3 gap-4 mt-3">
                <MetricBox label="P/E Ratio" value={props.pe_ratio} />
                <MetricBox label="ROE" value={`${props.roe}%`} />
                <MetricBox label="3Y Growth" value={`${props.revenue_growth_3y}%`} />
              </div>
            </TabsContent>
            {/* ... more tabs */}
          </Tabs>
        </CardContent>
      </Card>
    </motion.div>
  );
}

function MetricBox({ label, value }: { label: string; value: any }) {
  return (
    <div className="p-3 rounded-lg bg-zinc-800">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-lg font-mono font-bold mt-1">{String(value)}</p>
    </div>
  );
}
```

### 8.2 The 7 Generative UI Components to Build

| # | Component | Triggered By | Key Features |
|---|---|---|---|
| 1 | `CompanyIntelligenceCard` | "Analyze X" | Price chart, metrics, tabbed financials |
| 2 | `ComparisonTable` | "Compare X vs Y" | Side-by-side metrics, grouped bar chart, verdict |
| 3 | `DCFEstimationCard` | "Fair value of X" | **Interactive sliders** for assumptions → live recalc |
| 4 | `EarningsFlashCard` | "Q4 results of X" | Beat/miss badge, segment treemap, guidance |
| 5 | `ConceptExplainerCard` | "What is PE ratio" | Formula viz, real Indian examples, difficulty badge |
| 6 | `ScreeningResultsCard` | "Find stocks with..." | Sortable table, filter chips, criteria display |
| 7 | `AgentThinkingIndicator` | Every query | Shows which agents are working, progress steps |

---

## 9. PROJECT STRUCTURE & FILE LAYOUT

```
oracle/
├── backend/                          # Python backend
│   ├── pyproject.toml                # Dependencies (use uv or poetry)
│   ├── .env                          # API keys
│   │
│   ├── graph.py                      # ⭐ Main LangGraph supervisor + agents
│   ├── mcp_config.py                 # MCP server connection config
│   │
│   ├── mcp_servers/                  # Your custom MCP servers
│   │   ├── nse_server.py             # NSE India data (FastMCP)
│   │   ├── fundamentals_server.py    # FMP financial data (FastMCP)
│   │   ├── news_server.py            # News & sentiment (FastMCP)
│   │   └── rag_server.py             # RAG search over documents (FastMCP)
│   │
│   ├── rag/                          # RAG pipeline
│   │   ├── ingest.py                 # Document ingestion into Qdrant
│   │   ├── search.py                 # Vector search functions
│   │   └── documents/                # Raw documents to ingest
│   │
│   ├── langgraph.json                # LangGraph Platform config
│   └── Dockerfile                    # For deployment
│
├── frontend/                         # Next.js frontend
│   ├── package.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── .env.local                    # NEXT_PUBLIC_LANGGRAPH_URL, etc.
│   │
│   ├── app/
│   │   ├── layout.tsx                # Root layout (dark theme, fonts)
│   │   ├── page.tsx                  # ⭐ Main Chat + Canvas page
│   │   └── api/
│   │       └── chat/
│   │           └── route.ts          # API route → LangGraph backend
│   │
│   ├── components/
│   │   ├── ui/                       # shadcn/ui components
│   │   │   ├── card.tsx
│   │   │   ├── badge.tsx
│   │   │   ├── tabs.tsx
│   │   │   └── ...
│   │   │
│   │   ├── chat-panel.tsx            # Left panel: assistant-ui Thread
│   │   ├── canvas-panel.tsx          # Right panel: Generative UI cards
│   │   ├── oracle-header.tsx         # App header/nav
│   │   │
│   │   └── generative-ui/           # ⭐ THE WOW FACTOR
│   │       ├── company-card.tsx       # Company Intelligence Card
│   │       ├── comparison-table.tsx   # Side-by-side comparison
│   │       ├── dcf-card.tsx           # Interactive DCF with sliders
│   │       ├── earnings-flash.tsx     # Quarterly results card
│   │       ├── concept-explainer.tsx  # Education card
│   │       ├── screening-results.tsx  # Stock screener results
│   │       └── agent-thinking.tsx     # Agent progress indicator
│   │
│   └── lib/
│       ├── langgraph-client.ts       # LangGraph SDK setup
│       └── utils.ts                  # Formatters (INR, %, dates)
│
├── docker-compose.yml                # Run everything locally
└── README.md
```

---

## 10. INFRASTRUCTURE & DEPLOYMENT

### 10.1 Local Development

```yaml
# docker-compose.yml

services:
  # --- MCP Servers ---
  nse-mcp:
    build: ./backend
    command: python mcp_servers/nse_server.py
    ports: ["8001:8001"]
    env_file: ./backend/.env

  fundamentals-mcp:
    build: ./backend
    command: python mcp_servers/fundamentals_server.py
    ports: ["8002:8002"]
    env_file: ./backend/.env

  news-mcp:
    build: ./backend
    command: python mcp_servers/news_server.py
    ports: ["8003:8003"]
    env_file: ./backend/.env

  # --- LangGraph Backend ---
  langgraph:
    build: ./backend
    command: langgraph up  # or uvicorn graph:app
    ports: ["8100:8000"]
    env_file: ./backend/.env
    depends_on: [nse-mcp, fundamentals-mcp, news-mcp]

  # --- Qdrant Vector DB ---
  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333", "6334:6334"]
    volumes: ["qdrant_data:/qdrant/storage"]

  # --- PostgreSQL ---
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: oracle
      POSTGRES_USER: oracle
      POSTGRES_PASSWORD: oracle_secret
    ports: ["5432:5432"]
    volumes: ["pg_data:/var/lib/postgresql/data"]

  # --- Frontend ---
  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    environment:
      NEXT_PUBLIC_LANGGRAPH_URL: http://langgraph:8000

volumes:
  qdrant_data:
  pg_data:
```

### 10.2 Production Deployment

| Component | Deploy To | Why |
|---|---|---|
| **Frontend** | Vercel | Free tier, Edge network, auto-deploy from Git |
| **LangGraph Backend** | LangGraph Platform (LangSmith Cloud) OR Railway/Fly.io | Native LangGraph hosting with built-in streaming |
| **MCP Servers** | Railway / Fly.io / AWS ECS | Each as a separate microservice |
| **Qdrant** | Qdrant Cloud (free tier: 1GB) | Managed, no ops |
| **PostgreSQL** | Supabase (free tier) or Neon | Managed Postgres |

---

## 11. API KEYS & SERVICES YOU NEED

| Service | What For | Cost | Sign Up |
|---|---|---|---|
| **OpenAI** | GPT-4.1 for analysis agents | Pay-per-use (~$2-8/M tokens) | platform.openai.com |
| **Google AI** | Gemini Flash for supervisor routing | Free tier: 1500 req/day | aistudio.google.com |
| **Financial Modeling Prep** | Fundamentals, financials, news | Free: 250 calls/day | financialmodelingprep.com |
| **Qdrant Cloud** | Vector DB for RAG | Free: 1GB cluster | cloud.qdrant.io |
| **Vercel** | Frontend hosting | Free tier: generous | vercel.com |
| **LangSmith** (optional) | Agent tracing, debugging | Free tier: 5K traces/mo | smith.langchain.com |

**Total cost to start: $0/month** (all have free tiers). Production: ~$50-100/month.

---

## 12. BUILD SEQUENCE — WHAT TO BUILD FIRST

### Week 1-2: Foundation
```
□ Set up monorepo (backend/ + frontend/)
□ Create Python backend with FastMCP
□ Build NSE MCP server (nse_get_quote, nse_get_historical)
□ Build Fundamentals MCP server (income_statement, key_metrics, profile)
□ Test both servers with MCP Inspector CLI
□ Set up LangGraph with ONE agent (fundamental_agent) + supervisor
□ Verify: ask "Analyze TCS" → get structured JSON back
```

### Week 3-4: Multi-Agent + RAG
```
□ Add all 6 sub-agents with proper prompts
□ Add News MCP server
□ Set up Qdrant Cloud + ingestion pipeline
□ Ingest 10 annual reports (TCS, Infosys, HDFC Bank, Reliance, etc.)
□ Add RAG MCP server (rag_search tool)
□ Test multi-agent queries: "Compare TCS vs Infosys"
□ Add LangSmith tracing for debugging
```

### Week 5-6: Frontend + Generative UI
```
□ Set up Next.js with assistant-ui LangGraph template
□ Build Chat + Canvas layout (40/60 split)
□ Build CompanyIntelligenceCard component
□ Build ComparisonTable component
□ Build DCFEstimationCard with interactive sliders
□ Build AgentThinkingIndicator
□ Wire frontend → LangGraph backend (streaming)
□ Test full flow: ask question → see agents work → card appears
```

### Week 7-8: Polish + Deploy
```
□ Build remaining Generative UI components (Earnings, Education, Screening)
□ Add animations (Framer Motion: card entry, chart draw-in, number count-up)
□ Mobile responsive layout
□ Error handling + loading states
□ Deploy: Vercel (frontend) + Railway (backend) + Qdrant Cloud
□ Add VERAFI verification badges
□ Performance optimization (cache MCP responses)
```

---

## ARCHITECTURE DECISION SUMMARY

| Decision | Choice | Why |
|---|---|---|
| Agent Framework | **LangGraph** (not CrewAI, not AutoGen) | Best streaming, best state management, supervisor pattern, MCP support |
| Data Protocol | **MCP via FastMCP** (not direct API calls) | Decoupled, reusable, standardized, each data source is independent |
| MCP-to-Agent Bridge | **langchain-mcp-adapters** | Official LangChain library, converts MCP tools to LangChain tools |
| Vector DB | **Qdrant** (not Pinecone, not Weaviate) | Free cloud tier, fast, Python-native, great LangChain integration |
| Frontend Chat | **assistant-ui** (not CopilotKit) | Built for LangGraph, Generative UI support, streaming, production-ready |
| Generative UI | **LangGraph push_ui_message + React** | Stream React components from backend, not just text |
| Charts | **Recharts + TradingView Lightweight** | Recharts for financial metrics, TradingView for candlestick charts |
| LLM Strategy | **Gemini Flash (router) + GPT-4.1 (agents)** | Cheap routing + smart analysis = cost-efficient |
| Indian Data | **jugaad-data + nsetools + FMP** | jugaad for NSE raw data, FMP for global fundamentals, nsetools for live |
| Styling | **shadcn/ui + Tailwind v4** | Best DX, customizable, dark mode native |
| Deployment | **Vercel + Railway + Qdrant Cloud** | All have free tiers, production-grade |

---

## THE BOTTOM LINE

**ORACLE Phase 1 is essentially 4 systems working together:**

1. **3 MCP Servers** (FastMCP) — Your data microservices (NSE, Fundamentals, News)
2. **1 LangGraph Supervisor** — The AI brain that routes queries to 6 specialist agents
3. **1 Qdrant Vector DB** — Long-term memory for annual reports and transcripts
4. **1 Next.js Frontend** — Chat + Canvas with 7 Generative UI components via assistant-ui

**That's it.** Everything else (animations, auth, caching) is polish on top of these 4 pillars.

Start with Pillar 1 (MCP servers) → Pillar 2 (LangGraph) → Pillar 3 (Qdrant) → Pillar 4 (Frontend).

Each pillar can be tested independently before connecting them together.

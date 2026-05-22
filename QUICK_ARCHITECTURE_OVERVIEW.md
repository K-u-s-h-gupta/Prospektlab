# 🚀 ProspektLab - Quick Architecture Overview

## What is ProspektLab?

A **Conversational Financial Intelligence OS for Indian Stock Market**.

Users ask questions like:
- "What is TCS's PE ratio?"
- "Compare Infosys vs TCS on revenue growth"
- "Analyze Asian Paints fundamentals"
- "Show me IT sector trends"

The system provides **analyzed, cited answers** backed by real data.

---

## System Layers

```
┌──────────────────────────────────────────────────┐
│  Frontend (Next.js React)                        │
│  - Chat UI                                       │
│  - Real-time message streaming (SSE)             │
│  - Rich output (charts, tables, memos)           │
│  - Agent visualization                           │
└───────────────┬────────────────────────────────────┘
				│ HTTPS
				▼
┌──────────────────────────────────────────────────┐
│  Backend API (FastAPI)                           │
│  - Chat endpoint: POST /api/chat                 │
│  - LangGraph multi-agent orchestration           │
│  - Intent classification (which data to get?)    │
│  - Rich output formatting                        │
└───────────────┬────────────────────────────────────┘
				│
	┌───────────┼───────────┐
	▼           ▼           ▼
  LangGraph  FinAgent    MCP Services
 Agents     Research    (NSE, Funds,
			Engine      Research, etc)
```

---

## Two Execution Modes

### Mode 1: Quick Chat (ORACLE) ⚡
**For:** Fast questions  
**Engine:** Backend/api.py + LangGraph  
**Time:** 5-15 seconds

```
User: "What is Reliance's PE?"
	   ↓
Intent classifier → "Need fundamentals data"
	   ↓
LangGraph supervisor → Route to NSE agent
	   ↓
NSE MCP service → Returns current data
	   ↓
LLM synthesizes response
	   ↓
"Reliance PE: 42.5x (as of today)"
```

### Mode 2: Deep Research (FinAgent) 🔬
**For:** Thorough company analysis  
**Engine:** finagent/run_agent.py (8-phase pipeline)  
**Time:** 2-5 minutes

```
User: "Deep analysis of Asian Paints"
	   ↓
Phase 1: Identify entity (ticker: ASIANPAINT)
	   ↓
Phase 2: Enrichment (parallel API pulls)
		 - SEC EDGAR (US parent company)
		 - Yahoo Finance (historical prices)
		 - Wikipedia (company overview)
		 - NSE API (India pricing)
	   ↓
Phase 3: Breadth Survey (layered web search)
	   ↓
Phase 4: Deep Dive (gap-filling queries)
	   ↓
Phase 5: Conflict Detection (validate data)
	   ↓
Phase 6: Specialist Multi-Agent Analysis
		 - Accounting specialist
		 - Competitive analyst
		 - Valuation expert
	   ↓
Phase 7: Verification (fact-check)
	   ↓
Phase 8: Synthesis (generate memo)
	   ↓
Saved to: ~/.finagent/memos/session_123.md
Memo includes: Executive summary, financials, valuation, risks, citations
```

---

## Technology Stack at a Glance

| Layer | Tech | Why |
|-------|------|-----|
| **Frontend** | Next.js + React + TypeScript | Modern SSR, real-time capable |
| **API** | FastAPI + AsyncIO | High performance, async-native |
| **Agent Engine** | LangGraph + LangChain | Multi-agent orchestration |
| **LLM** | Anthropic Claude 3.x | Best reasoning for finance |
| **Data** | MCP (5 services) | Decoupled, scalable architecture |
| **Search** | DuckDuckGo + httpx + BeautifulSoup | Fast web scraping |
| **Deployment** | Docker + AWS ECS/Fargate + GitHub Actions | Production-ready |

---

## Key Services

### MCP Microservices (Separate Deployments)

| Service | Port | Data |
|---------|------|------|
| NSE India | 8001 | NSE/BSE stock prices, volumes |
| Fundamentals | 8002 | Company P/E, ROE, debt ratios |
| Research | 8003 | Analyst reports, recommendations |
| Docs | 8004 | Company filings, announcements |
| Valuation | 8005 | DCF, fair value estimates |

Each service:
- Runs independently
- Exposes JSON-RPC endpoint
- Can be scaled separately
- Can be replaced without affecting others

---

## Data Flow Example

### Query: "Compare TCS vs Infosys on margins"

```
Frontend User Input
	   ↓
/api/chat POST
{
  message: "Compare TCS vs Infosys on margins",
  mode: "research"
}
	   ↓
Backend/api.py receives request
	   ↓
Intent classifier detects:
  - Entities: TCS, Infosys
  - Intent: Comparison + Financials
	   ↓
LangGraph supervisor routes to:
  1. Fundamentals agent (get TCS margins)
  2. Fundamentals agent (get Infosys margins)
	   ↓
Call MCP Fundamentals service (port 8002)
  Request: { "ticker": "TCS", "metric": "profit_margin" }
  Response: { "gross_margin": 42.3, "net_margin": 18.2, "ebitda_margin": 28.1 }
	   ↓
Call MCP Fundamentals service
  Request: { "ticker": "INFY", "metric": "profit_margin" }
  Response: { "gross_margin": 38.1, "net_margin": 15.6, "ebitda_margin": 25.3 }
	   ↓
LLM synthesizes comparison
	   ↓
Rich output builder formats:
  - Text summary
  - Comparison table
  - Margin chart (visual)
	   ↓
ChatResponse
{
  reply: "TCS has stronger margins...",
  agents_used: ["fundamentals_agent"],
  rich: {
	tables: [{"company": "TCS", "margin": 18.2}, ...],
	chart: { type: "bar", data: [...] }
  }
}
	   ↓
Frontend SSE stream receives response
	   ↓
React re-renders with data + chart
```

---

## File Organization

```
PROSPEKTLAB/
├── Frontend/               ← Next.js React UI
├── Backend/                ← ORACLE FastAPI (chat engine)
│   ├── api.py              • Main API
│   ├── graph.py            • LangGraph orchestration
│   └── mcp_config.py       • MCP service URLs
├── finagent/               ← NEW: Autonomous research engine
│   ├── run_agent.py        • 8-phase research pipeline
│   ├── gateway/run.py      • Standalone FastAPI gateway
│   ├── agents/             • Multi-agent orchestration
│   ├── tools/              • Data & MCP integration
│   ├── memory/             • Long-term memory store
│   ├── synthesis/          • Memo generation
│   └── ...
├── deployment/             ← AWS deployment configs
├── Dockerfile              ← Container image
└── Docs/                   ← 15+ architecture docs
	├── FINAGENT_ARCHITECTURE_BLUEPRINT.md
	├── ORACLE_FIOS_architecture.md
	├── PRODUCTION_DEPLOYMENT_GUIDE.md
	└── ...
```

---

## Environment Configuration

### Production (AWS ECS)

```env
# API Keys
OPENAI_API_KEY=sk-proj-...

# MCP Service URLs (internal network)
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

### Local Development

```env
OPENAI_API_KEY=sk-proj-...
MCP_NSE_INDIA_URL=http://localhost:8001/mcp
# ... (same MCP URLs, pointing to localhost)
```

---

## Key Concepts

### Intent Classification
**What:** Determine what data the user needs  
**Where:** Backend/intent.py  
**Example:**
```
Input:  "Is Reliance's PE reasonable?"
Output: COMPARISON + VALUATION_METRICS
```

### Multi-Agent Orchestration
**What:** Route query to appropriate expert agents  
**Where:** Backend/graph.py (LangGraph)  
**Agents:**
- NSE Agent (prices, volume)
- Fundamentals Agent (ratios, financials)
- Research Agent (analyst insights)
- Valuation Agent (fair value)

### Rich Output Formatting
**What:** Format response with charts, tables, citations  
**Where:** Backend/rich_builder.py  
**Output Types:**
- Markdown text
- Embedded charts (candlestick, line, bar)
- Data tables
- Citation links

### Research Pipeline (FinAgent)
**What:** Multi-phase deep research workflow  
**Where:** finagent/run_agent.py  
**Phases:** Identify → Enrich → Survey → Dive → Analyze → Synthesize → Verify → Blind Spots

### Accuracy Validation
**What:** Verify claims against multiple sources  
**Where:** finagent/accuracy_validator.py  
**Claim structure:**
```python
@dataclass
class Claim:
	text: str              # "TCS revenue ₹200k Cr"
	source: str            # URL or document
	confidence: float      # 0.0-1.0 (higher = more verified)
	timestamp: datetime
```

---

## Deployment Pipeline

### Local → Production (Simplified)

```
1. Developer pushes to production branch
   git push origin production
	   ↓
2. GitHub Actions CI/CD triggered
	   ↓
3. Build Docker image
   docker build -t prospektlab-backend:latest .
	   ↓
4. Push to AWS ECR
   docker push <ACCOUNT_ID>.dkr.ecr.../prospektlab-backend:latest
	   ↓
5. Update ECS task definition
   aws ecs update-service --cluster prospektlab --service backend
	   ↓
6. Fargate pulls image, starts container
   Port 8080 (internally) → ALB → Route53 → https://api.prospektlab.com
	   ↓
7. Slack notification
   "Deployment successful! API live."
	   ↓
8. Frontend (Amplify) connects to new backend
```

---

## Testing Entry Points

### Quick Smoke Test
```bash
# 1. Frontend
npm run dev
# Go to http://localhost:3000, ask "What is Reliance's PE?"

# 2. Backend
python -m uvicorn Backend.api:app --reload
# POST http://localhost:8000/api/chat
# { "message": "What is Reliance's PE?" }

# 3. FinAgent
python -m uvicorn finagent.gateway.run:app --reload
# POST http://localhost:8000/api/research
# { "query": "Analyze Asian Paints", "depth": "deep" }
```

---

## Common Questions

**Q: Why are there two backends (Backend/api.py and finagent/api.py)?**  
A: Backend/api.py is the live ORACLE chat engine. finagent/api.py is the new autonomous research engine. They can run independently or be merged in the future.

**Q: Why MCP microservices instead of direct API calls?**  
A: MCP provides a standard interface. You can swap services without changing Backend code. Easier to scale, replace, or add new data sources.

**Q: How long does a deep research session take?**  
A: 2-5 minutes. It runs 8 phases sequentially, each with parallel operations. Optimized with caching and early-exit logic.

**Q: Can I run FinAgent without the frontend?**  
A: Yes! Use the CLI: `python -m finagent --query "Analyze TCS" --depth deep`

**Q: Where is user data stored?**  
A: Sessions in-memory + optional Supabase. Memory facts in ~/.finagent/memory/. Can upgrade to Postgres for production.

**Q: How do I add a new data source?**  
A: Create a new MCP service, register in mcp_config.py, define tool in finagent/tools/mcp/.

---

## Next Steps (Roadmap)

### Phase 2 (Q2-Q3 2026): Broker Integration
- Connect Zerodha, Angel One, Upstox APIs
- Portfolio context for all queries
- Personalized risk analysis

### Phase 3 (Q3-Q4 2026): Alerts & Monitoring
- Real-time price alerts
- Corporate announcement triggers
- Earnings surprise notifications
- Portfolio risk alerts

### Phase 4 (Q4 2026+): Advanced Intelligence
- Forensic accounting red flags
- IPO analysis engine
- Mutual fund overlap analysis
- Tax harvesting suggestions

---

## Key Files to Review

Start here if diving deeper:

1. **Backend/api.py** (703 lines) — Chat API entry point
2. **Backend/graph.py** — LangGraph orchestration
3. **finagent/run_agent.py** (2000 lines) — Research pipeline
4. **finagent/gateway/run.py** (1657 lines) — Standalone gateway
5. **finagent/agents/orchestrator.py** — Multi-agent coordination
6. **finagent/tools/data.py** — Data models
7. **finagent/synthesis.py** — Memo generation
8. **Backend/mcp_config.py** — MCP service registration

---

## Resources

- **Product Vision:** ORACLE_FIOS_architecture.md
- **Technical Blueprint:** FINAGENT_ARCHITECTURE_BLUEPRINT.md
- **Deployment Guide:** PRODUCTION_DEPLOYMENT_GUIDE.md
- **API Reference:** (auto-generated by FastAPI at http://localhost:8000/docs)
- **Repository:** https://github.com/K-u-s-h-gupta/Prospektlab_intelligence

---

**ProspektLab 2.0.0** | May 2026 | Financial Intelligence OS for India 🇮🇳📈


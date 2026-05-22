# 📚 COMPLETE PROSPEKTLAB DOCUMENTATION INDEX

**Version:** 2.0.0 (FinAgent Era)  
**Last Updated:** May 21, 2026  
**Repository:** https://github.com/K-u-s-h-gupta/Prospektlab_intelligence  
**Branch:** production

---

## 🎯 Master Index - Start Here

This document is your **complete navigation guide** to the entire ProspektLab codebase.

### Quick Navigation

| Document | Purpose | Read Time | Audience |
|----------|---------|-----------|----------|
| **THIS FILE** | Navigation & overview | 10 min | Everyone |
| [QUICK_ARCHITECTURE_OVERVIEW](#quick-overview) | Visual system architecture | 15 min | Designers, PMs, New devs |
| [CODEBASE_DIAGNOSTIC_WALKTHROUGH](#diagnostic) | Technical deep-dive | 45 min | Backend engineers |
| [DATA_FLOW_AND_INTEGRATION](#data-flow) | Request/response flows | 30 min | Integration engineers |
| [COMPLETE_API_REFERENCE](#api-reference) | All endpoints & models | 40 min | Backend devs, API consumers |
| [DATABASE_AND_STATE_SCHEMA](#state-schema) | Data models & persistence | 30 min | Backend devs, DBAs |
| [SECURITY_AND_AUTH_GUIDE](#security) | Auth, tokens, vulnerabilities | 25 min | Security engineers |
| [TESTING_AND_QA_STRATEGY](#testing) | Test structure, coverage | 20 min | QA, Test engineers |
| [DEPLOYMENT_COMPLETE_GUIDE](#deployment) | Production runbook | 45 min | DevOps, SREs |
| [DEVELOPMENT_GUIDELINES](#dev-guidelines) | Coding standards, patterns | 30 min | All developers |
| [PERFORMANCE_OPTIMIZATION](#performance) | Scaling, caching, tuning | 35 min | Backend architects |
| [TROUBLESHOOTING_GUIDE](#troubleshooting) | Common issues & fixes | 20 min | Operations, Support |
| [FEATURE_ROADMAP](#roadmap) | Implementation path | 25 min | Product, Engineering leads |
| [EXTERNAL_DEPENDENCIES](#dependencies) | APIs, services, libraries | 15 min | DevOps, Architects |

---

## 📋 Document Contents Overview

### Existing Documents (Already Created)

1. **QUICK_ARCHITECTURE_OVERVIEW.md** ✅
   - System architecture diagram
   - Two execution modes (quick chat vs deep research)
   - Technology stack summary
   - MCP microservices overview
   - Common questions answered
   - Quick start commands

2. **CODEBASE_DIAGNOSTIC_WALKTHROUGH.md** ✅
   - Executive summary
   - Complete system architecture
   - Directory structure & package map
   - Core components deep dive
   - Data flow & integration patterns
   - Technology stack details
   - MCP microservices architecture
   - Deployment architecture
   - Configuration & environment
   - Performance & scalability
   - Testing strategy
   - Architectural decisions
   - Known limitations & roadmap
   - Getting started entry points

3. **DATA_FLOW_AND_INTEGRATION.md** ✅
   - Scenario 1: Quick chat flow (5-15 sec)
   - Scenario 2: Deep research flow (2-5 min)
   - Event stream format (SSE)
   - Data models at each stage
   - Error handling & resilience
   - Performance metrics
   - Caching strategy
   - Complete integration map

---

## 🆕 New Comprehensive Documents

### 4. Complete API Reference (NEW)
**File:** `COMPLETE_API_REFERENCE.md`

Covers:
- All REST endpoints
- Request/response models with examples
- Authentication requirements
- Rate limiting
- Error responses
- Code examples (curl, Python, JavaScript)
- Webhook integration (if applicable)
- OpenAPI/Swagger info

### 5. Database & State Schema (NEW)
**File:** `DATABASE_AND_STATE_SCHEMA.md`

Covers:
- State dataclasses
- Checkpoint structure
- Memory store schema
- Session storage
- Citation log format
- Persistent storage locations
- Data retention policies
- Migration strategy

### 6. Security & Auth Guide (NEW)
**File:** `SECURITY_AND_AUTH_GUIDE.md`

Covers:
- Authentication mechanisms (JWT, API keys)
- Authorization & RBAC
- CORS configuration
- Rate limiting strategy
- API key management
- Secrets management
- Common vulnerabilities & mitigations
- Security checklist

### 7. Testing & QA Strategy (NEW)
**File:** `TESTING_AND_QA_STRATEGY.md`

Covers:
- Test structure (unit, integration, e2e)
- Test frameworks used
- Running tests locally
- CI/CD testing pipeline
- Test coverage targets
- Mocking strategy
- Common test patterns
- Writing new tests

### 8. Deployment Complete Guide (NEW)
**File:** `DEPLOYMENT_COMPLETE_GUIDE.md`

Covers:
- Local development setup
- Docker build & test
- AWS ECS deployment
- Environment configuration
- Database migrations
- Rollback procedures
- Post-deployment validation
- Monitoring & alerting

### 9. Development Guidelines (NEW)
**File:** `DEVELOPMENT_GUIDELINES.md`

Covers:
- Code style & formatting
- Git workflow & branching
- Commit message standards
- Code review process
- Documentation requirements
- Logging standards
- Error handling patterns
- Async/await best practices

### 10. Performance Optimization (NEW)
**File:** `PERFORMANCE_OPTIMIZATION_GUIDE.md`

Covers:
- Profiling tools & methods
- Database query optimization
- Caching strategies
- API response time tuning
- Memory usage optimization
- Scaling strategies (vertical & horizontal)
- Load testing approach
- CDN & static asset optimization

### 11. Troubleshooting Guide (NEW)
**File:** `TROUBLESHOOTING_GUIDE.md`

Covers:
- Common errors & solutions
- Debug logging setup
- Performance issues diagnosis
- MCP service failures
- Memory leaks detection
- Rate limiting issues
- Timeout debugging
- Production incident response

### 12. Feature Implementation Roadmap (NEW)
**File:** `FEATURE_IMPLEMENTATION_ROADMAP.md`

Covers:
- Phase 1 features (current)
- Phase 2 roadmap (broker integration)
- Phase 3 roadmap (alerts & monitoring)
- Phase 4 roadmap (advanced intelligence)
- Implementation priorities
- Effort estimates
- Dependencies & prerequisites
- Success metrics

### 13. External Dependencies (NEW)
**File:** `EXTERNAL_DEPENDENCIES_GUIDE.md`

Covers:
- OpenAI API integration
- MCP service contracts
- Third-party APIs (NSE, SEC, Yahoo, etc.)
- Python package dependencies
- Frontend npm dependencies
- Version constraints & compatibility
- License information
- Update strategy

---

## 🚀 How to Use This Package

### For Different Roles

#### **Project Manager / Product Manager**
1. Read: `QUICK_ARCHITECTURE_OVERVIEW.md` (15 min)
2. Read: `FEATURE_IMPLEMENTATION_ROADMAP.md` (25 min)
3. Bookmark: `TROUBLESHOOTING_GUIDE.md` (for ops issues)

#### **Backend Engineer (New to Project)**
1. Read: `QUICK_ARCHITECTURE_OVERVIEW.md` (15 min)
2. Read: `CODEBASE_DIAGNOSTIC_WALKTHROUGH.md` (45 min)
3. Read: `COMPLETE_API_REFERENCE.md` (40 min)
4. Read: `DATABASE_AND_STATE_SCHEMA.md` (30 min)
5. Read: `DEVELOPMENT_GUIDELINES.md` (30 min)
6. Clone & run locally: `DEPLOYMENT_COMPLETE_GUIDE.md`

#### **Frontend Engineer**
1. Read: `QUICK_ARCHITECTURE_OVERVIEW.md` (15 min)
2. Read: `DATA_FLOW_AND_INTEGRATION.md` (30 min)
3. Read: `COMPLETE_API_REFERENCE.md` (40 min)
4. Read: `DEVELOPMENT_GUIDELINES.md` (30 min)

#### **DevOps / SRE**
1. Read: `DEPLOYMENT_COMPLETE_GUIDE.md` (45 min)
2. Read: `EXTERNAL_DEPENDENCIES_GUIDE.md` (15 min)
3. Read: `SECURITY_AND_AUTH_GUIDE.md` (25 min)
4. Read: `PERFORMANCE_OPTIMIZATION_GUIDE.md` (35 min)
5. Read: `TROUBLESHOOTING_GUIDE.md` (20 min)

#### **QA / Test Engineer**
1. Read: `TESTING_AND_QA_STRATEGY.md` (20 min)
2. Read: `COMPLETE_API_REFERENCE.md` (40 min)
3. Read: `DEPLOYMENT_COMPLETE_GUIDE.md` (for staging)

#### **Security Engineer**
1. Read: `SECURITY_AND_AUTH_GUIDE.md` (25 min)
2. Read: `EXTERNAL_DEPENDENCIES_GUIDE.md` (15 min)
3. Read: `DEVELOPMENT_GUIDELINES.md` (30 min)

#### **Architect / Technical Lead**
1. Read: `CODEBASE_DIAGNOSTIC_WALKTHROUGH.md` (45 min)
2. Read: `PERFORMANCE_OPTIMIZATION_GUIDE.md` (35 min)
3. Read: `FEATURE_IMPLEMENTATION_ROADMAP.md` (25 min)
4. Read: `EXTERNAL_DEPENDENCIES_GUIDE.md` (15 min)
5. Read: All others for completeness

---

## 📊 System Architecture Quick Reference

```
┌─────────────────────────────────────────────────────────┐
│                   Frontend (Next.js)                    │
│            - Chat UI                                    │
│            - Real-time SSE streaming                    │
│            - Rich output (charts, tables)               │
└────────────────────┬────────────────────────────────────┘
					 │ HTTPS/REST
					 ▼
┌─────────────────────────────────────────────────────────┐
│                  Backend API (FastAPI)                  │
│  ┌──────────────────┐    ┌──────────────────────────┐  │
│  │ Backend/api.py   │    │ finagent/api.py          │  │
│  │ (ORACLE FIOS)    │    │ (Research Engine)        │  │
│  └────────┬─────────┘    └─────────┬────────────────┘  │
│           │                        │                   │
│           └───────────────┬────────┘                    │
│                           ▼                             │
│          ┌────────────────────────────────┐            │
│          │ LangGraph Orchestration        │            │
│          │ Multi-agent supervision        │            │
│          └──────────────┬─────────────────┘            │
│                         │                              │
│          ┌──────────────▼─────────────────┐            │
│          │ finagent/ (8-phase pipeline)   │            │
│          │ - Research orchestration       │            │
│          │ - Specialist agents            │            │
│          │ - Verification                 │            │
│          │ - Memory management            │            │
│          └──────────────┬─────────────────┘            │
└─────────────────────────┼──────────────────────────────┘
						  │
		┌─────────────────┼─────────────────┐
		│                 │                 │
		▼                 ▼                 ▼
	┌────────┐       ┌─────────┐      ┌──────────┐
	│MCP     │       │External │      │Memory    │
	│Service │       │APIs     │      │Store     │
	│(5x)    │       │         │      │          │
	└────────┘       └─────────┘      └──────────┘
```

---

## 🔑 Key Statistics

| Metric | Value |
|--------|-------|
| **Total Python Lines of Code** | ~15,000+ |
| **Main Backend File** | Backend/api.py (703 lines) |
| **Research Engine** | finagent/run_agent.py (2000 lines) |
| **Gateway API** | finagent/gateway/run.py (1657 lines) |
| **Frontend Components** | 15+ React components |
| **MCP Services** | 5 (NSE, Fundamentals, Research, Docs, Valuation) |
| **Documentation Pages** | 15+ (now) |
| **API Endpoints** | 10+ |
| **Agents (LangChain)** | 6+ (Orchestrator, Verifier, 4 Specialists) |
| **Data Sources** | 15+ (APIs, web, social) |

---

## 🎯 Core Concepts Glossary

### **ORACLE FIOS**
Quick chat engine for immediate answers. Runs in ~5-15 seconds.

### **FinAgent**
Autonomous research engine with 8-phase pipeline. Runs in ~2-5 minutes for deep analysis.

### **LangGraph**
State machine framework for multi-agent orchestration. Manages agent routing & supervision.

### **MCP (Model Context Protocol)**
JSON-RPC protocol for tool/service integration. Your data comes through 5 MCP services.

### **Intent Classification**
NLP layer that determines what data user needs (NSE data? Fundamentals? Research?)

### **Specialist Agents**
Expert LangChain agents that analyze specific domains (accounting, competitive, governance, valuation).

### **Verification Pass**
Final phase where facts are cross-checked against sources. Reduces hallucinations.

### **Synthesis**
Process of converting raw research data into a polished markdown memo with citations.

### **Session**
Long-running research context. Stores state, events, checkpoints, memory facts.

### **Checkpoint**
Snapshot of research progress. Used for resuming interrupted sessions.

### **Citation**
Attribution of a claim to its source. Tracks URL, source name, confidence, date.

### **Rich Output**
Formatted response with text, charts, tables, structured data (vs plain text).

---

## 📈 What's Implemented vs Planned

### ✅ Implemented & Production-Ready

- [x] Quick chat API (ORACLE FIOS)
- [x] LangGraph multi-agent orchestration
- [x] 5 MCP service integration
- [x] FastAPI backend with async/await
- [x] Next.js React frontend
- [x] SSE real-time streaming
- [x] Rich output formatting
- [x] Docker containerization
- [x] AWS ECS/Fargate deployment
- [x] GitHub Actions CI/CD
- [x] Error handling & timeouts
- [x] FinAgent 8-phase research pipeline
- [x] Specialist agents (accounting, competitive, governance, valuation)
- [x] Verification agent
- [x] Memory store (persistent)
- [x] Session management
- [x] Citation tracking

### 🚀 Built But Not Yet Integrated

- [x] FinAgent gateway API (runs standalone, not called from Frontend)
- [x] Specialist analysis (built, not used in quick chat)
- [x] Deep research UX (API exists, Frontend integration pending)

### 📋 Designed But Not Yet Implemented

- [ ] Broker integration (Zerodha, Angel One, Upstox API)
- [ ] Portfolio context for queries
- [ ] Real-time alerts engine
- [ ] News sentiment monitoring
- [ ] Earnings surprise detection
- [ ] Insider trading alerts
- [ ] Forensic accounting red flags
- [ ] IPO analysis engine
- [ ] Mutual fund overlap analysis
- [ ] Tax harvesting suggestions
- [ ] RAG-based memory (embeddings)
- [ ] Dynamic MCP discovery
- [ ] Multi-user workspaces
- [ ] User authentication (basic stub exists)

---

## 🔐 Important Files to Know

### **Must Know**
- `Backend/api.py` — Chat endpoint entry point
- `finagent/run_agent.py` — Research pipeline
- `finagent/gateway/run.py` — Research gateway
- `Backend/graph.py` — LangGraph orchestration
- `Backend/intent.py` — Intent classification

### **Important for Integration**
- `finagent/tools/mcp/` — MCP service clients
- `finagent/tools/data.py` — Data models
- `finagent/agents/orchestrator.py` — Agent coordination
- `finagent/synthesis.py` — Memo generation

### **Important for Deployment**
- `Dockerfile` — Container image
- `deployment/fargate-backend.yml` — ECS task definition
- `.github/workflows/deploy-production.yml` — CI/CD
- `.env.example` — Environment template

### **Important for Development**
- `Frontend/app/page.tsx` — Chat UI
- `finagent/requirements-finagent.txt` — Dependencies
- `Backend/requirements.txt` — Backend dependencies

---

## 🚨 Critical Configuration

### **Must Set (Production)**
```env
OPENAI_API_KEY=sk-proj-...                              # Required
MCP_NSE_INDIA_URL=http://mcp-nse-service:8001/mcp       # Required
MCP_FUNDAMENTALS_URL=http://mcp-fundamentals:8002/mcp   # Required
MCP_RESEARCH_URL=http://mcp-research:8003/mcp           # Required
MCP_DOCS_URL=http://mcp-docs:8004/mcp                   # Required
MCP_VALUATION_URL=http://mcp-valuation:8005/mcp         # Required
CORS_ORIGINS=https://app.prospektlab.com                # Required
```

### **Important (Deployment)**
```env
GRAPH_RUN_TIMEOUT_SECONDS=240
GRAPH_IDLE_TIMEOUT_SECONDS=90
GRAPH_REBUILD_COOLDOWN_SECONDS=5
```

---

## ⚡ Performance SLAs

| Operation | Target | Typical | Bottleneck |
|-----------|--------|---------|------------|
| Quick chat query | <15s | 5-10s | MCP latency |
| Single MCP call | <5s | 1-3s | Network |
| Deep research | 2-5m | 3m | Specialist agents |
| Web scraping | <30s | 10-20s | Parsing |
| Memory recall | <1s | <1s | In-memory |

---

## 📞 When to Escalate

### **If you encounter:**

| Issue | Who to Contact | Document |
|-------|---|---|
| API returns 500 error | Backend engineer | TROUBLESHOOTING_GUIDE.md |
| Slow response times | DevOps / Backend lead | PERFORMANCE_OPTIMIZATION_GUIDE.md |
| MCP service is down | DevOps | TROUBLESHOOTING_GUIDE.md |
| Rate limiting issues | Backend engineer | SECURITY_AND_AUTH_GUIDE.md |
| Deployment failure | DevOps / SRE | DEPLOYMENT_COMPLETE_GUIDE.md |
| Data inconsistency | QA / Backend lead | DATABASE_AND_STATE_SCHEMA.md |
| Security vulnerability | Security engineer | SECURITY_AND_AUTH_GUIDE.md |
| Need to add new MCP service | Architect / Lead | EXTERNAL_DEPENDENCIES_GUIDE.md |

---

## 🎓 Learning Path

### **Week 1: Foundations**
- Day 1: Read `QUICK_ARCHITECTURE_OVERVIEW.md`
- Day 2: Read `CODEBASE_DIAGNOSTIC_WALKTHROUGH.md`
- Day 3: Read `DATA_FLOW_AND_INTEGRATION.md`
- Day 4-5: Clone & run locally (see DEPLOYMENT_COMPLETE_GUIDE.md)

### **Week 2: API & Data**
- Day 1: Read `COMPLETE_API_REFERENCE.md`
- Day 2: Read `DATABASE_AND_STATE_SCHEMA.md`
- Day 3: Explore code: `Backend/api.py`
- Day 4-5: Write test API calls

### **Week 3: Deep Systems**
- Day 1: Read `TESTING_AND_QA_STRATEGY.md`
- Day 2: Read `SECURITY_AND_AUTH_GUIDE.md`
- Day 3: Read `DEVELOPMENT_GUIDELINES.md`
- Day 4-5: Run tests locally

### **Week 4: Operations & Future**
- Day 1: Read `DEPLOYMENT_COMPLETE_GUIDE.md`
- Day 2: Read `TROUBLESHOOTING_GUIDE.md`
- Day 3: Read `PERFORMANCE_OPTIMIZATION_GUIDE.md`
- Day 4: Read `FEATURE_IMPLEMENTATION_ROADMAP.md`
- Day 5: Plan first contribution

---

## ✅ Checklist: Getting Started

### Before First Day
- [ ] Clone repository: `git clone https://github.com/K-u-s-h-gupta/Prospektlab_intelligence`
- [ ] Switch to production: `git checkout production`
- [ ] Read this index document

### First Day
- [ ] Read `QUICK_ARCHITECTURE_OVERVIEW.md`
- [ ] Read `CODEBASE_DIAGNOSTIC_WALKTHROUGH.md`
- [ ] Install Python 3.11+
- [ ] Create virtual environment: `python -m venv venv`
- [ ] Activate: `source venv/bin/activate` (or `.venv\Scripts\Activate.ps1` on Windows)

### Second Day
- [ ] Install dependencies: `pip install -r Backend/requirements.txt`
- [ ] Install Node.js 18+
- [ ] Install Frontend deps: `cd Frontend && npm install`
- [ ] Copy `.env.example` to `.env` in `finagent/`
- [ ] Set `OPENAI_API_KEY` in `.env`

### Third Day
- [ ] Run backend: `python -m uvicorn Backend.api:app --reload`
- [ ] Run frontend: `cd Frontend && npm run dev`
- [ ] Test chat: Visit http://localhost:3000
- [ ] Read `DATA_FLOW_AND_INTEGRATION.md`

### First Week
- [ ] Read all API documentation
- [ ] Run tests: `pytest finagent/tests/`
- [ ] Explore code structure
- [ ] Set up IDE (VS Code, PyCharm)
- [ ] Make first code commit

---

## 📞 Key Contacts & Resources

### **Documentation**
- Architecture: `CODEBASE_DIAGNOSTIC_WALKTHROUGH.md`
- API: `COMPLETE_API_REFERENCE.md`
- Deployment: `DEPLOYMENT_COMPLETE_GUIDE.md`

### **Code Repositories**
- **Main:** https://github.com/K-u-s-h-gupta/Prospektlab_intelligence
- **Branch:** production (live), main (development)

### **External APIs**
- OpenAI API: https://platform.openai.com
- NSE API: (via MCP service)
- SEC EDGAR: https://www.sec.gov/edgar
- Yahoo Finance: https://finance.yahoo.com

### **Deployment Platforms**
- AWS ECS: https://console.aws.amazon.com/ecs
- AWS Amplify: https://console.aws.amazon.com/amplify
- GitHub Actions: https://github.com/K-u-s-h-gupta/Prospektlab_intelligence/actions

---

## 🎉 You're Ready!

You now have access to:
- ✅ 13 comprehensive documentation files
- ✅ Complete system overview
- ✅ Architecture diagrams
- ✅ API reference
- ✅ Deployment guides
- ✅ Development standards
- ✅ Troubleshooting help
- ✅ Roadmap & priorities

**Next Step:** Pick your role from "For Different Roles" section and follow the reading list!

---

**Last Updated:** May 21, 2026  
**Maintained by:** ProspektLab Team  
**Repository:** https://github.com/K-u-s-h-gupta/Prospektlab_intelligence


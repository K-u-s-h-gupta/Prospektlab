# ProspektLab / FinAgent — Complete Current Architecture (2026)

**Status**: Authoritative snapshot of the **live** system (as of the current codebase).  
This supersedes older documents that describe the previous “ORACLE FIOS / LangGraph + MCP” architecture.

---

## 1. Executive Summary

ProspektLab is an **AI-native financial intelligence platform** that produces investment-grade research memos and reports for listed companies (primarily Indian equities, with global support).

- **Core product**: A long-running, self-improving research agent (`FinAgent`) that combines authoritative data pulls, web research, reflection, multi-agent orchestration, and high-quality synthesis.
- **Delivery surface**: A single FastAPI gateway that serves both the full web UI (static HTML + JS) **and** all research APIs with authentication, session management, and real-time streaming.
- **Modes**: `chat` (fast) → `standard` → `deep` → `marathon` (12-pass, multi-hour, institutional-grade).
- **Key differentiators**: India-first entity resolution, persistent memory across sessions, reflection + blind-spot detection, rich structured output, and production-grade auth/session isolation.

The system is **not** using LangGraph or separate MCP servers anymore. Those components exist only in historical documentation.

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Browser / User                              │
│  (landing.html, widget.html — single-page Tailwind + vanilla JS)    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ HTTPS + JWT cookie / Bearer
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│              FastAPI Gateway  (finagent/gateway/run.py)             │
│  • Auth (Google GIS + email/password via Supabase)                  │
│  • Session ownership / BOLA protection                              │
│  • Rate limiting, security headers                                  │
│  • Research orchestration: /research/start, /research/deep, /chat/* │
│  • SSE streaming per session (/sessions/{id}/stream)                │
│  • Memos, memory viewer, chat history endpoints                     │
│  • Serves all static HTML pages                                     │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ in-process calls + shared BUS
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     FinAgent Runtime Core                           │
│  finagent/run_agent.py  +  run_research_session()                   │
│                                                                     │
│  Pipeline (configurable depth):                                     │
│   1. Entity resolution (geo layer, India-first)                     │
│   2. Authoritative enrichment (Yahoo, NSE/BSE signals, SEBI, Wiki)  │
│   3. Layered web search (DDG + Bing + optional SearxNG)             │
│   4. Deep-dive + Reflection loops (self-critique)                   │
│   5. Optional: Multi-agent orchestration (parallel specialists)     │
│   6. Blind-spot detection                                           │
│   7. Conflict detection + quality scoring                           │
│   8. Synthesis (OpenAI streaming or structured template)            │
│   9. Rich output artifact + memo markdown                           │
│                                                                     │
│  Event Bus (finagent/events.py) → drives live UI progress           │
└─────────────────────────────────────────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
       Web/Search Tools   Financial Data    Memory + State
       (scraper, http)    (yfinance, etc.)  (SQLite facts + chat history)
```

---

## 3. Component Breakdown

### 3.1 Gateway (`finagent/gateway/run.py`)
- **Primary production surface** (the one users actually hit).
- Full auth system:
  - Google One-Tap / GIS → Supabase user creation + local JWT cookie.
  - Email/password signup with verification codes (SMTP or console fallback).
  - Password reset flow.
- Research entry points:
  - `POST /research/start` — standard/deep single-pass or fast modes.
  - `POST /research/deep` — multi-pass marathon (up to 12 passes).
  - `POST /chat/research` — chat-friendly wrapper that routes to the above.
- Real-time: Server-Sent Events (SSE) per session with full event history replay.
- Persistence: Memos (`~/.finagent/memos/{session}.md`), session metadata, events.jsonl.
- Security: JWT + Supabase JWT dual verification, session ownership checks on every sensitive route, rate limiters, strong CSP + security headers.
- Also serves: memory browser, fact viewer, memo listing, chat history.

### 3.2 Lightweight API (`finagent/api.py`)
- Simpler FastAPI app for quick testing or external integration.
- Endpoints: `/api/chat`, `/api/chat/stream`, MCP health stub.
- Does **not** have the full auth/session system of the gateway.

### 3.3 Agent Runtime (`finagent/run_agent.py`)
The heart of the system. `AgentLoopConfig` controls almost everything:
- Depth modes, step budgets, timeouts (Windows gets doubled timeouts).
- Reflection (Hermes-style self-critique), blind-spot detection, multi-agent waves.
- Memory recall, peer-target enrichment for comparisons.
- Output mode forcing (`company_snapshot`, `company_comparison`, `deep_research_report`, etc.).

### 3.4 Synthesis & Output (`finagent/synthesis.py` + `finagent/output/`)
- Turns the entire evidence pool into a polished memo.
- Two paths:
  1. OpenAI streaming (when key present) — high quality.
  2. Structured/template fallback.
- Produces:
  - Markdown memo (saved to disk).
  - `AnswerArtifact` (structured JSON with sections, citations, tables, rich blocks).
  - `rich` payload for the UI (charts, comparison tables, etc.).
- Special support for comparison queries (fetches enrichment for both entities).

### 3.5 Tools & Data Layer
- **Web**: Layered search (`search_layered`), crawl4ai + Playwright fallback, HTTP fetcher with caching.
- **Financial**:
  - Yahoo Finance via `yfinance` (quotes + fundamentals).
  - India-specific: Screener.in, NSE/BSE signals, SEBI filings, shareholding patterns (via scrapers).
- **Social/Sentiment**: Reddit, StockTwits, Hacker News (limited).
- **Registry**: Simple capability registry (mostly for future tool-use agents).

### 3.6 Memory & State
- **Persistent fact store** (`finagent/memory/store.py`): SQLite `facts` + `session_summaries`.
- **Chat history** per user + session (`ChatMemoryManager`).
- **Session bus events** (`events.jsonl` per session) — durable replay for SSE.
- Compression and checkpointing hooks exist for very long runs.

### 3.7 Multi-Agent & Quality
- `agents/orchestrator.py`: Wave-based parallel execution of specialist sub-agents with dependency topology.
- `agent/reflection.py`: Iterative critique + gap-filling.
- `agents/blindspot.py`, `analysis/conflicts.py`, `analysis/quality.py`.
- Playbooks: reusable research templates that can be promoted from successful runs.

### 3.8 Frontend / UI
- **No separate Next.js / React app in production**.
- All UI is served by the gateway as static files:
  - `landing.html`, `login.html`, `signup.html`, `profile.html`, `settings.html`.
  - `widget.html` (≈ 5,000 lines of Tailwind + vanilla JS + Chart.js + export libs) — the main interactive research interface.
- The `Frontend/` directory contains only two leftover chart components and is **not** part of the current runtime.
- Widget communicates exclusively via `fetch` + `EventSource` to the gateway (same origin).

### 3.9 Auth & Identity
- Primary: Supabase (`auth.users` + `public.profiles`).
- Gateway issues its own HS256 JWTs (cookie `prospektlab_auth`) for all subsequent calls.
- Dual JWT verification path (local secret or Supabase secret) to support both flows.
- Mobile number collection post-Google signup.

---

## 4. Request Lifecycle (Typical Deep Research)

1. User authenticates → receives JWT cookie.
2. Widget sends `POST /research/start` or `/research/deep` (with target + objective).
3. Gateway:
   - Verifies ownership (if resuming).
   - Opens BUS for the session.
   - Spawns background task `run_research_session(...)`.
4. Agent loop emits live events (`phase`, `source`, `agent_task`, `deep_pass`, etc.).
5. Gateway streams them via SSE; widget renders progress in real time.
6. On completion:
   - Synthesis writes memo + rich artifact.
   - Gateway emits `final` + `memo` events.
   - Memo is persisted and memory facts are updated.
7. User can view `/sessions/{id}/memo`, download, or start follow-up (with session continuity).

---

## 5. Data & Persistence

- `~/.finagent/` (or `FINAGENT_HOME`):
  - `memos/{session_id}.md`
  - `sessions/{session_id}/` (meta.json, events.jsonl, closed marker)
  - `memory/facts.db` (SQLite)
  - `users/` (legacy local hashed credentials — mostly unused now)
  - `skills/auto/` (self-generated tools — experimental)
- Supabase: users, profiles, (future) shared research artifacts.

---

## 6. External Integrations & Dependencies

**Required**:
- OpenAI API (synthesis — primary quality path)
- Yahoo Finance (via yfinance)
- Web search: DuckDuckGo (primary), Bing (optional), Tavily (optional)

**India-specific** (via scraping):
- Screener.in, NSE India, SEBI filings, Moneycontrol, etc.

**Auth**:
- Supabase
- Google Identity Services (GIS)

**Optional / graceful**:
- Playwright (browser scraping)
- SMTP (email verification)
- SearxNG self-hosted metasearch
- MCP servers (legacy — not used in current path)

**Python packages** (see `requirements-finagent.txt`):
`openai`, `fastapi`, `uvicorn`, `httpx`, `beautifulsoup4`, `crawl4ai`, `yfinance`, `tavily-python`, `PyJWT`, `reportlab`/`python-docx` (Marathon exports), etc.

---

## 7. Deployment & Infrastructure

- **Container**: Dockerfile (Python + Playwright browsers via crawl4ai setup)
- **AWS**:
  - ECS Fargate or EC2 for the gateway (`deployment/fargate-backend.yml`, `deploy-backend.ps1`)
  - Amplify (historical static hosting — currently the gateway serves everything)
  - `buildspec*.yml`, `amplify-buildspec.yml`
- **Environment variables**: `OPENAI_API_KEY`, `SUPABASE_*`, `JWT_SECRET`, `FINAGENT_*` tuning, SMTP, etc.
- **Local dev**: `python -m finagent.gateway.run` or `uvicorn finagent.gateway.run:app`
- **Health**: `/health`, `/capabilities`, `/config`

---

## 8. Key Design Decisions & Trade-offs

- **Single-process agent loop** (instead of distributed LangGraph) → simpler deployment, harder horizontal scaling.
- **Reflection + blind-spot + multi-agent** instead of pure ReAct/tool-calling → dramatically higher research quality at the cost of latency and token spend.
- **India-first default** + geo-aware source selection → best-in-class accuracy for Indian equities.
- **Persistent cross-session memory** → the agent “remembers” companies it has researched.
- **Rich + Markdown dual output** → excellent human readability + machine-parseable artifacts for future automation.
- **Static HTML widget served from gateway** → zero frontend build/deploy complexity; easy to self-host.
- **Dual JWT path** → supports both Google and email users cleanly.

---

## 9. Diagnosis — What’s Real vs. Historical

| Area                        | Current Reality (2026)                          | Old Docs / Historical                  |
|----------------------------|--------------------------------------------------|----------------------------------------|
| Orchestration              | Pure Python `run_agent.py` + reflection loop    | LangGraph supervisor + many MCPs      |
| MCP servers                | Not used in runtime (legacy code may exist)     | Core of the old architecture          |
| Frontend                   | Static `widget.html` + gateway-served pages     | Next.js `Frontend/app/` (mostly dead) |
| Auth                       | Supabase + gateway JWT cookies                  | Mentioned but not fully implemented   |
| Research depth             | chat/standard/deep/marathon (up to 12 passes)   | Much simpler single-pass              |
| Memory                     | Full SQLite facts + chat history                | Minimal or absent                     |

**Recommendation**: Archive or clearly label all pre-2025 architecture docs as “historical”. The single source of truth is now this document + the code in `finagent/gateway/` and `finagent/run_agent.py`.

---

## 10. Quick Start (for developers)

```bash
# 1. Install
pip install -r finagent/requirements-finagent.txt

# 2. Set keys
export OPENAI_API_KEY=...
export SUPABASE_URL=...
export SUPABASE_SERVICE_ROLE_KEY=...

# 3. Run gateway (serves UI + APIs)
python -m finagent.gateway.run --port 8080

# 4. Open http://localhost:8080/landing → sign up / log in → /app
```

For production use the AWS deployment scripts in `deployment/` and the various `buildspec*.yml`.

---

**Maintained by**: ProspektLab team  
**Last updated**: 2026-05-22 (current codebase scan)

This document reflects the **actual running system**, not aspirational or previous designs.

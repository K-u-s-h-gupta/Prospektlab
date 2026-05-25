# FINAGENT QUERY ROUTING ANALYSIS - COMPLETE DOCUMENTATION

**Created**: May 25, 2026
**Codebase**: finagent (ProspektLab)
**Analysis Scope**: Query classification, routing decisions, portfolio detection, follow-up context awareness, and execution paths

---

## DOCUMENTATION FILES

Three comprehensive analysis documents have been created:

### 1. **QUERY_ROUTING_ANALYSIS.md** (20.4 KB)
Complete technical analysis covering:
- Portfolio-related query detection mechanism
- Query routing architecture and flow
- Follow-up question context awareness
- Query complexity classification
- Decision: web search vs portfolio-specific analysis
- Mutual fund holdings tracking and access
- Agent selection & specialization
- Research plan & retrieval strategies
- Key file references and line numbers

**Use this for**: Understanding the complete system architecture, data structures, and decision points.

### 2. **QUERY_ROUTING_QUICK_REFERENCE.md** (11.0 KB)
Quick lookup guide with:
- Query classification decision tree
- Portfolio scope detection patterns (11 pattern list)
- Follow-up context handling summary
- Mutual fund holdings tracking quick reference
- Web search vs portfolio analysis comparison
- Complexity classification matrix
- Agent keyword taxonomy table
- Key files and line references

**Use this for**: Quick lookups, pattern matching, and decision tree navigation during development.

### 3. **QUERY_ROUTING_CODE_EXAMPLES.md** (25.5 KB)
Detailed code walkthroughs with examples:
- Portfolio query detection with code walkthrough
- Follow-up context resolution with 3 example scenarios
- Routing decision comparison (portfolio vs web search)
- Portfolio analysis activation in agent run
- Mutual fund holdings access patterns
- Web search pipeline (layered execution)
- Complexity-based configuration examples
- Error handling and fallback mechanisms

**Use this for**: Understanding code flows, debugging, implementing similar features.

---

## KEY FINDINGS SUMMARY

### 1. PORTFOLIO DETECTION
**Mechanism**: Exact string pattern matching (case-insensitive)
`
_PORTFOLIO_SCOPE_PATTERNS = (
    "my portfolio", "our portfolio", "portfolio risk", "portfolio audit", "risk audit",
    "our holdings", "my holdings", "holdings audit", "portfolio concentration",
    "concentration risk", "asset allocation"
)
`
**Entry Point**: is_portfolio_scope_query() in outer/intent_router.py:123
**Impact**: Sets intent_key = "PORTFOLIO_AUDIT", forces complexity="complex", deep_research=True

### 2. FOLLOW-UP AWARENESS
**Method**: Dual-provider LLM (OpenAI + Grok/xAI fallback)
**Input**: Prior target + chat history (last 6 turns) + current query
**Output**: is_followup (boolean), contextualized_query (pronouns rewritten), target (company name)
**Key Feature**: Session isolation — creates new session if target changes to prevent data leakage

**File**: outer/intent_router.py:214-347 (LLMQueryContextualizer class)

### 3. COMPLEXITY ROUTING
`
SIMPLE       (0-1 keywords): PE ratio, share price, current price, EPS
               → Skip reflection, blindspot, deep-dive | max_steps=0

MODERATE     (standard): Earnings, revenue growth, news
               → 1 deep-dive round | skip blindspot | max_steps=1

COMPLEX      (all deep): Compare, peer analysis, risk factors, "deep analysis"
               → All phases enabled | max_steps=4
`

### 4. PORTFOLIO VS WEB SEARCH
**Portfolio Path**: 
- Triggered by portfolio scope patterns
- Loads active positions from position_mirrors table
- Computes HHI, concentration, portfolio risk metrics
- Uses portfolio-focused agents: [risk, governance, accounting, financials, valuation]

**Web Search Path**:
- All non-portfolio queries
- Uses SearXNG (primary) + Tavily (fallback) + DDG/Bing
- Breadth survey (4-6 angled queries) → deep dive → analysis → synthesis

### 5. MUTUAL FUND ACCESS
**Storage**: SQLite position_mirrors table with columns:
- kind = "mf" (identifies mutual fund positions)
- mfi: AMFI scheme code (6 digits)
- exchange = "AMFI" (for mutual funds)
- market_value, quantity, isin, etc.

**Analytics**: compute_mf_analytics() provides:
- Total MF value & scheme count
- AUM-weighted TER (Total Expense Ratio)
- Category breakdown (large_cap, mid_cap, small_cap, debt, hybrid, elss, liquid, index_etf)
- AMC concentration analysis
- Lookthrough exposure (Phase 2 placeholder)

**Query Flow**: 
`
load_active_positions(tenant_id)
    → filter(kind="mf")
    → compute_mf_analytics()
    → returns category breakdown, TER, concentration
`

---

## ARCHITECTURE AT A GLANCE

`
USER QUERY
    ↓
[Primary Target Extraction] → primary_target_from_query()
    ↓
[Follow-up Detection] → LLMQueryContextualizer (if session exists)
    │                     ├─ Follow-up? → Rewrite pronouns, maintain context
    │                     └─ New topic? → Session isolation, new target
    ↓
[Portfolio Scope Check] → is_portfolio_scope_query()
    │
    ├─ YES (PORTFOLIO_AUDIT)
    │  ├─ Complexity: complex
    │  ├─ Deep research: True
    │  ├─ Agents: [risk, governance, accounting, financials, valuation]
    │  ├─ Load: load_active_positions(tenant_id) → [PositionMirror]
    │  ├─ Analyze: portfolio risk (HHI, correlation, beta)
    │  └─ Result: Portfolio audit memo
    │
    └─ NO (STANDARD)
       ├─ Classify complexity (simple/moderate/complex)
       ├─ Route to agents by keyword matching
       ├─ Execute web search (search_layered)
       ├─ Breadth → Deep-dive → Analysis
       └─ Result: Company snapshot or research report
`

---

## CRITICAL CODE PATHS

### Portfolio Query Detection
`
finagent/router/intent_router.py:123-125
    is_portfolio_scope_query(objective: str) → bool

finagent/gateway/run.py:1569
    if is_portfolio_scope_query(raw_query):
        _require_synchronized_portfolio(tenant_id)

finagent/gateway/run.py:1821
    if is_portfolio_scope_query(raw_query):
        _require_synchronized_portfolio(tenant_id)
`

### Routing Decision
`
finagent/router/intent_router.py:128-199
    route_objective(objective, entity) → RoutingDecision
        ├─ detect_operational_intent()
        ├─ is_portfolio_scope_query()
        ├─ _classify_complexity()
        └─ Agent selection via AGENT_KEYWORDS

finagent/gateway/run.py:1558-1713
    start_research() POST /research/start
        ├─ LLMQueryContextualizer.contextualize() (if session exists)
        ├─ route_objective()
        └─ run_research_session()
`

### Portfolio Analysis
`
finagent/run_agent.py:1337-1366
    if routing.intent_key == "PORTFOLIO_AUDIT":
        portfolio_sentinel = await run_portfolio_sentinel(cfg.tenant_id)

finagent/portfolio_sentinel.py:35-63
    run_portfolio_sentinel(tenant_id)
        ├─ load_active_positions(tenant_id)
        ├─ portfolio_weights()
        └─ run_full_portfolio_risk()

finagent/portfolio_mirrors.py:189-229
    load_active_positions(tenant_id) → list[PositionMirror]
        → From portfolio_mirrors table, filtered by tenant_id & active=1
        → Includes equity, MF, all holdings
`

### Web Search Pipeline
`
finagent/run_agent.py:1428-1454
    search_layered(target, queries, ...) → list[ScrapedDoc]

finagent/tools/web/scraper.py:888-1180
    search_web(query, ...) → list[ScrapedDoc]
        ├─ Stage 1: SearXNG (primary) / Tavily (fallback)
        ├─ Stage 2: URL selection
        ├─ Stage 3: Crawl4AI deep extraction
        └─ Stage 4: Combine & return
`

---

## DATA STRUCTURES

### PositionMirror (Portfolio Holding)
`python
@dataclass(frozen=True)
class PositionMirror:
    tenant_id: str
    symbol: str              # "RELIANCE.NS", "120308" (AMFI)
    exchange: str            # "NSE", "BSE", "AMFI"
    quantity: float
    market_value: float
    cost_basis: float
    active: bool
    name: str
    isin: str
    amfi: str               # AMFI code for MFs
    kind: str               # "equity", "mf"
    sector: str
    industry: str
    avg_cost: float
    last_price: float
    as_of: str
`

### RoutingDecision
`python
@dataclass
class RoutingDecision:
    selected_agents: list[str]        # ["risk", "governance", "accounting", ...]
    confidence: str
    selected_tools: list[str]
    retrieval_plan: list[str]
    fallback_policy: str
    deep_research: bool               # True for portfolio queries
    query_complexity: str             # "simple", "moderate", "complex"
    skip_reflection: bool
    skip_blindspot: bool
    skip_deep_dive: bool
    max_deep_dive_rounds: int
    operational_intent: str           # "news", "valuation", "snapshot", etc.
    intent_key: str                   # "PORTFOLIO_AUDIT" or "SNAPSHOT", "NEWS", etc.
    is_followup: bool
`

### ContextualizeResult (Follow-up Detection)
`python
@dataclass
class ContextualizeResult:
    is_followup: bool                 # True if continuing prior conversation
    contextualized_query: str         # Pronouns rewritten to company names
    target: str | None                # Extracted/confirmed company name
`

### PortfolioSentinelResult
`python
@dataclass
class PortfolioSentinelResult:
    tenant_id: str
    positions_found: int
    symbols: list[str]                # ["RELIANCE.NS", "INFY.NS", ...]
    weights: dict[str, float]         # {"RELIANCE.NS": 0.25, ...}
    risk: dict[str, Any]              # HHI, correlation, beta, volatility
    rules: list[str]                  # Concentration alert rules
    error: str | None
    
    @property
    def concentration_alert(self) -> bool:
        return hhi >= 0.25
`

---

## ENVIRONMENT VARIABLES

| Variable | Purpose | Example |
|----------|---------|---------|
| OPENAI_API_KEY | Primary LLM for contextualizer | sk-... |
| OPENAI_API_BASE | Custom OpenAI base URL | https://... |
| XAI_API_KEY | Grok/xAI fallback for contextualizer | xai-... |
| FINAGENT_XAI_MODEL | xAI model selection | grok-3-mini |
| FINAGENT_SEARXNG_URL | Self-hosted SearXNG endpoint | http://localhost:8888 |
| TAVILY_API_KEY | Tavily API for web search | tvly-... |

---

## TESTING PATTERNS

### Test Portfolio Detection
`python
from finagent.router.intent_router import is_portfolio_scope_query

is_portfolio_scope_query("What is my portfolio risk?")  → True
is_portfolio_scope_query("run a risk audit on my portfolio concentration")  → True
is_portfolio_scope_query("What's the latest news on Reliance?")  → False
`

### Test Routing Decision
`python
from finagent.geo.entity_resolver import resolve_entity
from finagent.router.intent_router import route_objective

entity = resolve_entity("my portfolio risk audit")
decision = route_objective("run a risk audit on my portfolio concentration", entity)

assert decision.intent_key == "PORTFOLIO_AUDIT"
assert decision.deep_research is True
assert decision.query_complexity == "complex"
assert {"risk", "governance", "accounting"}.issubset(set(decision.selected_agents))
`

### Test Follow-up Detection
`python
from finagent.router.intent_router import LLMQueryContextualizer
import asyncio

result = asyncio.run(
    LLMQueryContextualizer().contextualize(
        "provide me its latest news",
        "Adani Power"
    )
)

assert result.is_followup is True
assert "Adani Power" in result.contextualized_query
assert "latest news" in result.contextualized_query.lower()
`

---

## QUICK DECISION MATRIX

`
Query Type                          | Portfolio? | Complexity | Deep? | Result Route
------------------------------------|------------|------------|-------|------------------
"my portfolio risk"                 | YES        | complex    | YES   | PORTFOLIO_AUDIT
"What is Reliance's PE ratio?"      | NO         | simple     | NO    | WEB_SEARCH
"Compare TCS vs Infosys"            | NO         | complex    | YES   | WEB_SEARCH
"our holdings audit"                | YES        | complex    | YES   | PORTFOLIO_AUDIT
"Its latest earnings" (after TCS)   | NO         | moderate   | YES   | WEB_SEARCH (TCS)
"latest news"                       | NO         | moderate   | NO    | WEB_SEARCH
"Deep analysis of valuation"        | NO         | complex    | YES   | WEB_SEARCH
"asset allocation review"           | YES        | complex    | YES   | PORTFOLIO_AUDIT
`

---

## KNOWN LIMITATIONS & GOTCHAS

1. **Portfolio patterns are exact string matches** - "portfolio risk audit" (with "risk") will match, but variations might not
2. **MF lookthrough exposure** - Currently a placeholder; Phase 2 enhancement needed for underlying stock exposure
3. **LLM contextualizer requires API keys** - No fallback if both OpenAI and xAI are unavailable (returns 503)
4. **Session isolation** - Only created when target changes; same company queries continue in same session
5. **Web search timeout varies by platform** - Windows has 3x multiplier (45s * 3 = 135s) vs Linux (45s)
6. **Portfolio HHI calculation** - Uses simple market value weights; doesn't account for correlated risks
7. **AMFI scheme metadata** - Bundled data; no real-time TER updates

---

## RECOMMENDED NEXT STEPS

1. **Extend portfolio patterns** - Add more conversational variations (e.g., "How concentrated is my portfolio?")
2. **Implement lookthrough exposure** - Query AMFI scheme holdings for MF positions
3. **Add sector concentration checks** - Current HHI is portfolio-level; sector-level concentration might be valuable
4. **Portfolio trend tracking** - Compare current weights vs historical (week/month ago)
5. **Integration with rebalancing** - Suggest rebalancing based on concentration alerts
6. **Add portfolio sensitivity analysis** - Stress testing for market movements

---

## DOCUMENT REFERENCES

- **QUERY_ROUTING_ANALYSIS.md**: Complete technical documentation (10 sections)
- **QUERY_ROUTING_QUICK_REFERENCE.md**: Quick lookups and decision matrices
- **QUERY_ROUTING_CODE_EXAMPLES.md**: Code walkthroughs with 8 detailed examples

**Total Documentation**: 57 KB across 3 markdown files

---

**Analysis Date**: May 25, 2026
**Analyzed Codebase**: D:\PROSPEKTLAB\finagent
**Primary Components**: router, gateway, portfolio, tools/web

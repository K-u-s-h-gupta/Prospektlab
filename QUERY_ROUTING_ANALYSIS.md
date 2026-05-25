# FINAGENT QUERY CLASSIFICATION & ROUTING ANALYSIS

## EXECUTIVE SUMMARY

The finagent codebase implements a sophisticated query routing system that classifies queries based on:
1. **Portfolio scope detection** - distinguishes portfolio audit queries from single-entity queries
2. **Query complexity analysis** - routes to appropriate pipeline depth (simple/moderate/complex)
3. **Follow-up context awareness** - uses LLM to rewrite pronouns and maintain conversation context
4. **Agent specialization** - selects domain-specific agents based on query keywords
5. **Web search vs portfolio analysis** - routes to portfolio-specific analysis when portfolio queries detected

---

## 1. PORTFOLIO-RELATED QUERY DETECTION

### Primary Detection Function: is_portfolio_scope_query()
**Location**: D:\PROSPEKTLAB\finagent\router\intent_router.py:123-125

`python
def is_portfolio_scope_query(objective: str) -> bool:
    lower = (objective or "").lower()
    return any(pattern in lower for pattern in _PORTFOLIO_SCOPE_PATTERNS)
`

### Portfolio Scope Patterns (Lines 44-56)
`
_PORTFOLIO_SCOPE_PATTERNS = (
    "my portfolio",
    "our portfolio",
    "portfolio risk",
    "portfolio audit",
    "risk audit",
    "our holdings",
    "my holdings",
    "holdings audit",
    "portfolio concentration",
    "concentration risk",
    "asset allocation",
)
`

### Usage Points
1. **Gateway initialization** (gateway\run.py:1569) - When a query comes in via /research/start, the system checks if it's a portfolio query and ensures portfolio is synchronized
2. **Deep research endpoint** (gateway\run.py:1821) - Same check for /research/deep endpoint
3. **Portfolio details endpoint** (gateway\run.py:2038) - Validates portfolio scope before fetching details

---

## 2. QUERY ROUTING ARCHITECTURE

### Entry Point: /research/start Endpoint
**Location**: D:\PROSPEKTLAB\finagent\gateway\run.py:1558-1713

#### Query Processing Flow

`
START_RESEARCH REQUEST
    ↓
[Portfolio Scope Check] → is_portfolio_scope_query(raw_query)
    ↓
    YES → _require_synchronized_portfolio(tenant_id)
    ↓
[Follow-up Context Resolution] 
    ↓
    IF (session_id && prior_target):
        → LLMQueryContextualizer.contextualize()
        → Rewrites pronouns into self-contained queries
        → Detects if follow-up vs new topic
        → May create new session if target changed
    ↓
[Routing Decision via route_objective()] (lines 1655-1656)
    ↓
[Run Research Session]
    ↓
    IF portfolio_scope:
        → run_portfolio_sentinel()
        → Load tenant-scoped active holdings
        → Compute portfolio risk metrics
        → Selected agents: risk, governance, accounting, financials, valuation
    ELSE:
        → Web search pipeline (search_layered → breadth survey → deep dive)
        → Selected agents based on AGENT_KEYWORDS taxonomy
`

### Configuration Mode Selection (Lines 1619-1645)
`
mode = chat (default) → base_steps = 28
mode = standard        → base_steps = 38
mode = deep           → base_steps = 60
max_steps override    → base_steps = req.max_steps

Pipeline Configuration:
- is_fast_mode = (mode in {"standard", "chat"})
- is_deep_mode = (mode == "deep")

Fast mode disables:
  - enable_multi_agent = False
  - enable_blindspot = False
  - reflection_max_rounds = 1
  - Tighter search timeouts
`

---

## 3. FOLLOW-UP QUESTION CONTEXT AWARENESS

### LLMQueryContextualizer Class
**Location**: D:\PROSPEKTLAB\finagent\router\intent_router.py:214-347

#### Follow-up Detection & Rewriting
The system uses a pure-LLM approach with dual-provider fallback:

1. **Primary Provider**: OpenAI (via resolve_openai_config())
2. **Fallback Provider**: Grok/xAI (via XAI_API_KEY env var)

#### System Prompt Logic (Lines 251-280)
The contextualizer receives:
- Prior target company from session metadata
- Recent chat history (last 6 turns, max 300 chars each)
- Current query

Decision criteria:
`
IF query refers to prior target using pronouns (it, its, they, their, this company, that company, same company):
    → is_followup = true
    → contextualized_query = rewritten with company name
    → target = prior_target

ELIF query introduces completely different company/ticker:
    → is_followup = false
    → contextualized_query = unchanged
    → target = newly mentioned company or null

ELIF query is a comparison (e.g., "compare it with TCS"):
    → is_followup = true
    → Both entities explicitly written into contextualized_query
`

#### Follow-up Impact on Routing (intent_router.py:107-120)
`python
def detect_operational_intent(objective: str, *, has_prior_entity: bool = False) -> tuple[str, bool]:
    # Determines focus: news, valuation, shareholding, price_history, snapshot
    is_followup = has_prior_entity and (
        any(pronoun in lower for pronoun in _FOLLOWUP_PRONOUNS)
        or (focus != "snapshot" and len(lower.split()) <= 8)
    )
    return focus, is_followup
`

#### Complexity Adjustment for Follow-ups (intent_router.py:160)
`python
complexity = "simple" if is_followup and operational_intent in 
    {"news", "valuation", "shareholding", "price_history"} 
else _classify_complexity(objective)
`
**Effect**: Follow-up questions about simple intents skip expensive phases (reflection, blindspot).

#### Session Isolation (gateway\run.py:1599-1605)
`
IF (prior_target differs from new target) AND (not is_followup):
    → Create fresh session_id
    → Reset event bus
    → Prevents data leakage between entities
`

---

## 4. QUERY COMPLEXITY CLASSIFICATION & PHASE ROUTING

### Complexity Levels
**Location**: D:\PROSPEKTLAB\finagent\router\intent_router.py:26-83

#### Simple Queries (Lines 27-33)
Skip heavy phases: reflection, blindspot, deep-dive
`
"pe ratio", "p/e", "pb ratio", "current price", "share price", "stock price",
"live price", "market cap", "eps", "dividend yield", "book value", "52 week",
"what is the price", "historical price", "price history"
`

#### Moderate Queries (Lines 35-41)
Run 1 deep-dive round, skip blindspot
`
"quarterly results", "earnings", "revenue growth", "profit", "net income",
"ebitda", "margin", "balance sheet", "cash flow", "latest news",
"recent news", "sector outlook", "analyst target", "shareholding"
`

#### Complex Queries (Lines 66-72)
Full pipeline: all phases enabled
`
"deep", "comprehensive", "exhaustive", "due diligence", "full analysis",
"investigate", "compare", "vs", "versus", "peer analysis", "risk factors",
"sebi", "fraud", "investigation", "governance", "long term",
"investment thesis", "initiation", "moat"
`

### Phase Execution Matrix
`
Query Type    | Complexity | Reflection | Blindspot | Deep-Dive | Max Rounds
Simple        | simple     | SKIP       | SKIP      | SKIP      | 0
Moderate      | moderate   | RUN        | SKIP      | RUN 1x    | 1
Complex       | complex    | RUN        | RUN       | RUN 4x    | 4
Portfolio     | complex    | RUN        | RUN       | RUN 4x    | 4
`

---

## 5. DECISION: WEB SEARCH VS PORTFOLIO-SPECIFIC ANALYSIS

### Web Search Activation
**Location**: D:\PROSPEKTLAB\finagent\run_agent.py:1428-1454

Web search (search_layered) is triggered unless:
- Query is portfolio-scoped AND portfolio exists
- Query is about a specific entity (company/stock)

`
if cfg.enable_scraping:
    search_layered(
        canonical_label,      # Company/entity name
        queries=retrieval_plan.breadth_queries,
        preferred_domains=preferred_domains,
        entity=entity,
        timeout_s=breadth_search_timeout
    )
`

### Portfolio Analysis Activation
**Location**: D:\PROSPEKTLAB\finagent\run_agent.py:1337-1366

`python
portfolio_sentinel = None
if routing.intent_key == "PORTFOLIO_AUDIT":
    BUS.emit(session_id, "phase", phase="portfolio_identify", note="Loading tenant-scoped active holdings")
    if cfg.tenant_id:
        portfolio_sentinel = await run_portfolio_sentinel(cfg.tenant_id)
        # Emits:
        # - portfolio_identify: positions_found, symbols, weights, error
        # - portfolio_sentinel: risk, rules, concentration_alert
`

### Routing Decision Logic (intent_router.py:128-199)
`python
def route_objective(objective, entity, ...) -> RoutingDecision:
    portfolio_scope = is_portfolio_scope_query(objective)
    intent_key = "PORTFOLIO_AUDIT" if portfolio_scope else operational_intent.upper()
    
    # PORTFOLIO_AUDIT forces:
    if portfolio_scope:
        complexity = "complex"
        selected = [risk, governance, accounting, financials, valuation, ...]
        deep = True
    else:
        complexity = _classify_complexity(objective)
        deep = should_enable_deep_research(objective)
        selected = [agents matching query keywords]
`

---

## 6. MUTUAL FUND HOLDINGS & PORTFOLIO DATA ACCESS

### Data Storage Architecture
**Location**: D:\PROSPEKTLAB\finagent\portfolio_mirrors.py

#### Position Storage Table (Lines 21-44)
`sql
CREATE TABLE position_mirrors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL DEFAULT 'NSE',    -- NSE, BSE, AMFI (for MFs)
    quantity REAL NOT NULL DEFAULT 0,
    market_value REAL NOT NULL DEFAULT 0,
    cost_basis REAL NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    name TEXT,
    isin TEXT,
    amfi TEXT,                               -- AMFI code for mutual funds
    kind TEXT NOT NULL DEFAULT 'equity',     -- equity, mf, etc.
    sector TEXT,
    industry TEXT,
    avg_cost REAL NOT NULL DEFAULT 0,
    last_price REAL NOT NULL DEFAULT 0,
    as_of TEXT
);
`

#### PositionMirror Dataclass (Lines 47-81)
`python
@dataclass(frozen=True)
class PositionMirror:
    tenant_id: str
    symbol: str
    exchange: str              # NSE, BSE, AMFI
    quantity: float
    market_value: float
    cost_basis: float = 0.0
    active: bool = True
    name: str = ""
    isin: str = ""
    amfi: str = ""            # AMFI scheme code (6 digits) for mutual funds
    kind: str = "equity"      # equity or mf
    sector: str = ""
    industry: str = ""
    avg_cost: float = 0.0
    last_price: float = 0.0
    as_of: str = ""
`

### Mutual Fund Holdings Access
**Location**: D:\PROSPEKTLAB\finagent\portfolio\mf_analytics.py

#### MF Analytics Computation (Lines 56-105)
`python
def compute_mf_analytics(positions: list[PositionMirror]) -> dict[str, Any] | None:
    # Filter only MF positions
    mf_positions = [p for p in positions if p.kind == "mf"]
    
    # Compute:
    # - AUM-weighted TER (Total Expense Ratio)
    # - Category breakdown (large_cap, mid_cap, small_cap, debt, hybrid, elss, liquid, index_etf)
    # - AMC concentration (Asset Management Company concentration)
    # - Scheme type counts
    # - Lookthrough exposure (placeholder for Phase 2)
    
    return {
        "status": "OK",
        "total_mf_value": ...,
        "scheme_count": ...,
        "aum_weighted_ter_pct": ...,
        "category_breakdown": {...},     # Category -> % of portfolio
        "amc_concentration": {...},      # AMC -> % of portfolio
        "scheme_type_counts": {...},
        "lookthrough_exposure": {},      # Future: underlying stock exposure
    }
`

#### MF Category Classification (Lines 34-53)
`python
def _classify_mf_category(scheme_name: str, scheme_type: str = "") -> str:
    # Classifies based on scheme name/type keywords:
    # - "debt", "gilt", "money market" → "debt"
    # - "hybrid", "balanced", "allocation" → "hybrid"
    # - "large" → "large_cap"
    # - "mid" → "mid_cap"
    # - "small" → "small_cap"
    # - "index", "etf" → "index_etf"
    # - "liquid", "ultra short" → "liquid"
    # - "elss", "tax saver" → "elss"
`

#### AMFI Scheme Metadata (Lines 21-31)
`python
_MF_META_PATH = Path(__file__).resolve().parent.parent / "data" / "amfi_schemes_meta.json"

def _load_scheme_meta() -> dict[str, Any]:
    # Loads bundled AMFI scheme metadata keyed by AMFI code
    # Contains: ter (TER %), amc (Asset Management Company), scheme_type
`

### Loading Active Portfolio (portfolio_mirrors.py:189-229)
`python
def load_active_positions(tenant_id: str) -> list[PositionMirror]:
    # Query: SELECT ... WHERE tenant_id = ? AND active = 1
    # Returns positions sorted by market_value DESC, symbol ASC
    # Includes both equity and mf positions
`

### Portfolio Weight Calculation (Lines 344-353)
`python
def portfolio_weights(positions: Iterable[PositionMirror]) -> dict[str, float]:
    # Returns: {symbol: weight, ...}
    # symbol is exchange_symbol (e.g., "RELIANCE.NS" for equity, "120308" for AMFI code MF)
    # weight = market_value / total_portfolio_value
`

### Portfolio Analytics Flow
**Location**: D:\PROSPEKTLAB\finagent\portfolio_sentinel.py:35-63

`
run_portfolio_sentinel(tenant_id)
    ↓
load_active_positions(tenant_id)
    → Returns all active equity + MF positions
    ↓
portfolio_weights(positions)
    → Computes portfolio allocation
    ↓
run_full_portfolio_risk(weights, benchmark, period, portfolio_value)
    → Computes HHI (Herfindahl index), correlation, beta, volatility
    ↓
Returns PortfolioSentinelResult:
    - positions_found: count
    - symbols: list of exchange_symbol
    - weights: {symbol: weight}
    - risk: {hhi_analysis, correlation, beta, volatility}
    - concentration_alert: HHI >= 0.25
`

---

## 7. AGENT SELECTION & SPECIALIZATION

### Agent Taxonomy
**Location**: D:\PROSPEKTLAB\finagent\router\domain_taxonomy.py:4-15

`python
AGENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "financials": ("financial", "revenue", "margin", "balance sheet", "cash flow", ...),
    "risk": ("risk", "lawsuit", "investigation", "fraud", "headwind"),
    "technical": ("technical", "chart", "momentum", "breakout", ...),
    "news": ("news", "headline", "update", "earnings", "deal", ...),
    "community": ("sentiment", "retail", "community", "buzz"),
    "competitor": ("compare", "competitor", "peer", "vs", "versus", ...),
    "macro": ("macro", "rates", "inflation", "fx", "commodity", ...),
    "governance": ("governance", "board", "management", "insider", ...),
    "valuation": ("valuation", "dcf", "intrinsic value", "target price", ...),
    "accounting": ("accounting", "anomaly", "forensic", "earnings quality", ...),
}
`

### Agent Selection Logic (intent_router.py:144-158)
`python
# 1. Keyword-based selection from AGENT_KEYWORDS
selected = []
for agent, keywords in AGENT_KEYWORDS.items():
    if any(term in lower_objective for term in keywords):
        selected.append(agent)

# 2. Country-specific augmentation
if entity.country_code not in ("US",) and "financials" not in selected:
    selected.append("financials")  # Always include for India

# 3. Playbook-driven augmentation
if playbook_agents:
    for agent in playbook_agents:
        if agent not in selected:
            selected.append(agent)

# 4. Complexity-based pruning
if complexity == "simple":
    # Keep only: financials, news, risk, governance, valuation, accounting, competitor, technical
    selected = [a for a in selected if a in (...)]
elif complexity == "moderate":
    # Keep only: financials, risk, news, competitor, governance, valuation, accounting
    selected = [a for a in selected if a in (...)]
# complex: keep all selected
`

### Portfolio Query Agent Override (Lines 161-163)
`python
if portfolio_scope:
    complexity = "complex"
    selected = list(dict.fromkeys(["risk", "governance", "accounting", "financials", "valuation", *selected]))
    # Enforces specialized agent roster for portfolio audits
`

---

## 8. RESEARCH PLAN & RETRIEVAL

### Breadth Survey Queries
**Location**: D:\PROSPEKTLAB\finagent\research_planner.py (referenced in intent_router.py)

For non-portfolio queries:
`
Phase 0: memory recall
Phase 1: enrichment (Yahoo Finance, Wikipedia, India Snapshot, SEC data)
Phase 2: breadth survey (search_layered with 4-6 angle queries)
Phase 3: deep dive (iterative follow-up queries to fill gaps)
Phase 4: synthesis (multi-agent analysis + reflection)
Phase 5: verification (accuracy checking)
`

For portfolio queries:
`
Phase 0: memory recall
Phase 1: portfolio_identify (load holdings, compute risk)
Phase 2: enrichment (parallel enrichment for top holdings)
Phase 3: breadth survey (search on portfolio health topics)
Phase 4: deep dive (risk-focused follow-ups)
Phase 5: synthesis (portfolio-scoped memo)
Phase 6: verification (portfolio accuracy check)
`

---

## 9. SUMMARY: QUERY FLOW DIAGRAM

`
USER QUERY
    ↓
┌─────────────────────────────────────────────────────────────┐
│ GATE 1: PRIMARY TARGET EXTRACTION                            │
│ - extract_finance_entities(query)                            │
│ - primary_target_from_query(query)                           │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ GATE 2: FOLLOW-UP CONTEXT RESOLUTION (if session exists)     │
│ - LLMQueryContextualizer.contextualize()                     │
│ - Rewrite pronouns into self-contained query                │
│ - Detect follow-up vs new topic                             │
│ - Session isolation if target changed                        │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ GATE 3: PORTFOLIO SCOPE DETECTION                            │
│ is_portfolio_scope_query(objective)?                         │
└─────────────────────────────────────────────────────────────┘
    ↓
    ├─ YES (Portfolio detected)
    │     ↓
    │  ┌──────────────────────────────────────────┐
    │  │ PORTFOLIO AUDIT PATH                     │
    │  │ - intent_key = "PORTFOLIO_AUDIT"         │
    │  │ - complexity = "complex"                 │
    │  │ - deep_research = True                   │
    │  │ - agents = [risk, governance, accounting,│
    │  │            financials, valuation, ...]   │
    │  │ - Load active positions via tenant_id    │
    │  │ - Compute portfolio risk (HHI, beta)     │
    │  │ - Emit portfolio_identify event          │
    │  │ - Run multi-agent analysis on holdings   │
    │  │ - Synthesis: portfolio audit report      │
    │  └──────────────────────────────────────────┘
    │
    └─ NO (Standard query)
          ↓
       ┌──────────────────────────────────────────┐
       │ STANDARD RESEARCH PATH                    │
       │ - Classify complexity (simple/moderate)   │
       │ - route_objective() → RoutingDecision    │
       │ - Select agents by keyword matching       │
       │ - Complexity-based phase selection        │
       │ - Web search (search_layered)             │
       │ - Breadth → Deep-dive → Analysis          │
       │ - Synthesis: company snapshot/memo        │
       └──────────────────────────────────────────┘

RESULT SYNTHESIS & VERIFICATION
    ↓
EMIT MEMO & CLOSE SESSION
`

---

## 10. KEY FILES REFERENCE

| Feature | File | Lines |
|---------|------|-------|
| Portfolio scope detection | outer/intent_router.py | 123-125, 44-56 |
| Follow-up contextualizer | outer/intent_router.py | 214-347 |
| Routing decision | outer/intent_router.py | 128-199 |
| Gateway start_research | gateway/run.py | 1558-1713 |
| Portfolio sentinel | portfolio_sentinel.py | 35-63 |
| Portfolio mirrors | portfolio_mirrors.py | - |
| MF analytics | portfolio/mf_analytics.py | 56-105 |
| Web search pipeline | 	ools/web/scraper.py | 888-1180 |
| Intent classification | output/intent_classifier.py | - |
| Agent taxonomy | outer/domain_taxonomy.py | 4-15 |
| Complexity policies | outer/policies.py | 4-22 |


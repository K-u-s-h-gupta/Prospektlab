# FINAGENT QUERY ROUTING: CODE EXAMPLES & FLOW TRACES

## 1. PORTFOLIO QUERY DETECTION - CODE WALKTHROUGH

### Source Code Reference
**File**: inagent/router/intent_router.py:123-141

`python
# Step 1: Define portfolio scope patterns (lines 44-56)
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

# Step 2: Check if query matches any pattern (lines 123-125)
def is_portfolio_scope_query(objective: str) -> bool:
    lower = (objective or "").lower()
    return any(pattern in lower for pattern in _PORTFOLIO_SCOPE_PATTERNS)

# Step 3: Use in routing decision (lines 141-142)
portfolio_scope = is_portfolio_scope_query(objective)
intent_key = "PORTFOLIO_AUDIT" if portfolio_scope else operational_intent.upper()
`

### Example Queries

`python
is_portfolio_scope_query("What is my portfolio risk?")
→ True (matches "my portfolio", "portfolio risk")

is_portfolio_scope_query("run a risk audit on my portfolio concentration")
→ True (matches "my portfolio", "portfolio concentration", "risk audit")

is_portfolio_scope_query("What's the latest news on Reliance?")
→ False (no portfolio patterns)

is_portfolio_scope_query("Our holdings are concentrated in tech, what should we do?")
→ True (matches "our holdings")
`

---

## 2. FOLLOW-UP CONTEXT RESOLUTION - COMPLETE FLOW

### Source Code Reference
**File**: inagent/gateway/run.py:1572-1611

### Request Data Structure
`python
# Incoming request at /research/start
class StartResearchRequest(BaseModel):
    target: str           # Raw query text
    objective: str | None # Optional explicit objective
    session_id: str | None  # Session to continue
    mode: str | None      # "chat", "standard", or "deep"

# Session metadata loaded from disk
meta = _load_session_meta(session_id)
# Contains: target_display, target, tenant_id, user_email, prior_entity
`

### Flow with Examples

#### Example 1: First Query (No Prior Context)
`
User: "What is Reliance's share price?"
Request: StartResearchRequest(target="What is Reliance's share price?", session_id=None)

Code Path:
    meta = _load_session_meta(None)  → {} (empty)
    prior_target = None
    
    # Skip contextualizer (line 1582)
    if req.session_id and prior_target:  → False
        pass
    
    # Fall back to extraction
    target = primary_target_from_query(raw_query)
    → "Reliance"
    
    objective = "What is Reliance's share price?"
`

#### Example 2: Follow-up in Same Session
`
Prior Session: session_id=abc123, target="Reliance"
User: "What about its latest earnings?"
Request: StartResearchRequest(target="What about its latest earnings?", session_id="abc123")

Code Path:
    meta = _load_session_meta("abc123")
    → {"target_display": "Reliance", "target": "Reliance", ...}
    
    prior_target = "Reliance"
    
    chat_history = _MEMORY_MANAGER.get_history(user_email, "abc123")
    → [{"role": "user", "message": "What is Reliance's share price?"},
       {"role": "assistant", "message": "Reliance shares are trading at..."}]
    
    contextualizer = LLMQueryContextualizer()
    result = await contextualizer.contextualize(
        query="What about its latest earnings?",
        prior_target="Reliance",
        chat_history=[...]
    )
    
    LLM Reasoning:
        System prompt: "You are a financial-query contextualizer..."
        History: Shows we were discussing Reliance
        Query: "its latest earnings" → pronoun "its" refers to Reliance
        Decision: is_followup=True, target="Reliance"
    
    LLM Response:
    {
      "is_followup": true,
      "contextualized_query": "Reliance's latest earnings",
      "target": "Reliance"
    }
    
    Code:
        is_followup = result.is_followup  → True
        target = prior_target  → "Reliance"
        objective = result.contextualized_query  → "Reliance's latest earnings"
    
    Result: Follow-up detected, same session continues, rewritten query passed to agent
`

#### Example 3: Topic Change Mid-Session
`
Prior Session: session_id=abc123, target="Reliance"
User: "How about TCS? Is it a good investment?"
Request: StartResearchRequest(target="How about TCS? Is it a good investment?", session_id="abc123")

Code Path:
    prior_target = "Reliance"
    
    contextualizer.contextualize(
        query="How about TCS? Is it a good investment?",
        prior_target="Reliance",
        chat_history=[...]
    )
    
    LLM Reasoning:
        "TCS" is explicitly named
        No pronouns referring to prior target
        Different company introduced
        Decision: is_followup=False, target="TCS"
    
    LLM Response:
    {
      "is_followup": false,
      "contextualized_query": "How about TCS? Is it a good investment?",
      "target": "TCS"
    }
    
    Code:
        is_followup = False
        target = "TCS"  (newly extracted)
        
        # Session isolation check (lines 1602-1605)
        if prior_target and target and prior_target.lower() != target.lower():
            session_id = uuid.uuid4().hex[:12]  → NEW SESSION "def456"
            BUS.open(session_id, reset=True)
    
    Result: New session created for TCS, no data leakage from Reliance analysis
`

---

## 3. ROUTING DECISION - PORTFOLIO VS WEB SEARCH

### Source Code Reference
**File**: inagent/router/intent_router.py:128-199

### Flow Comparison

#### Scenario A: "my portfolio risk audit"
`python
# Input
objective = "run a risk audit on my portfolio concentration"
entity = ResolvedEntity(...)  # from resolve_entity()

# Execution
portfolio_scope = is_portfolio_scope_query(objective)
→ True

operational_intent, is_followup = detect_operational_intent(objective, has_prior_entity=False)
→ ("snapshot", False)

intent_key = "PORTFOLIO_AUDIT"  # (because portfolio_scope=True)
complexity = "complex"  # (because portfolio_scope=True, line 162)
deep = True  # (because portfolio_scope=True, line 164)

# Agent selection (line 163)
selected = list(dict.fromkeys([
    "risk",           # forced
    "governance",     # forced
    "accounting",     # forced
    "financials",     # forced
    "valuation",      # forced
    ...any matched agents...
]))

# Result
RoutingDecision(
    selected_agents=["risk", "governance", "accounting", "financials", "valuation", ...],
    deep_research=True,
    query_complexity="complex",
    intent_key="PORTFOLIO_AUDIT",
    skip_reflection=False,
    skip_blindspot=False,
    skip_deep_dive=False,
    max_deep_dive_rounds=4,
)
`

#### Scenario B: "Compare Reliance vs TCS"
`python
# Input
objective = "Compare Reliance vs TCS"
entity = ResolvedEntity(name="Reliance", country_code="IN")

# Execution
portfolio_scope = is_portfolio_scope_query(objective)
→ False

operational_intent, is_followup = detect_operational_intent(objective, has_prior_entity=False)
→ ("snapshot", False)

complexity = _classify_complexity(objective)
→ "complex" (matches "compare", "vs")

intent_key = "SNAPSHOT"
deep = should_enable_deep_research(objective)
→ True (matches "compare")

# Agent selection (lines 146-148)
for agent, keywords in AGENT_KEYWORDS.items():
    if any(term in lower for term in keywords):
        selected.append(agent)

Keywords matched:
- "competitor": ("compare", "competitor", "peer", "vs", "versus", "market share")
  → add "competitor"
- "financials": revenue, margin, etc.
  → (no direct match but added for India)

selected = ["competitor", "financials"]

# India-specific augmentation (lines 153-154)
if entity.country_code not in ("US",) and "financials" not in selected:
    selected.append("financials")
→ Already has financials, no change

# Result
RoutingDecision(
    selected_agents=["competitor", "financials"],
    deep_research=True,
    query_complexity="complex",
    intent_key="SNAPSHOT",
    skip_reflection=False,
    skip_blindspot=False,
    skip_deep_dive=False,
    max_deep_dive_rounds=4,
)
`

#### Scenario C: "What is the PE ratio of Infosys?"
`python
# Input
objective = "What is the PE ratio of Infosys?"
entity = ResolvedEntity(name="Infosys", ...)

# Execution
portfolio_scope = False
operational_intent, is_followup = detect_operational_intent(objective, has_prior_entity=False)
→ ("valuation", False)

complexity = _classify_complexity(objective)
→ "simple" (matches "pe ratio")

intent_key = "VALUATION"
deep = should_enable_deep_research(objective)
→ False (no deep terms)

# Agent selection
selected = ["valuation"]

# Result
RoutingDecision(
    selected_agents=["valuation"],
    deep_research=False,
    query_complexity="simple",
    intent_key="VALUATION",
    skip_reflection=True,
    skip_blindspot=True,
    skip_deep_dive=True,
    max_deep_dive_rounds=0,
)

# Pipeline Configuration (gateway/run.py)
if mode == "chat":
    base_steps = 28
    enable_multi_agent = False
    enable_blindspot = False
    reflection_max_rounds = 1
    breadth_search_timeout = 45.0s
    followup_search_timeout = 25.0s
`

---

## 4. PORTFOLIO ANALYSIS ACTIVATION - AGENT RUN

### Source Code Reference
**File**: inagent/run_agent.py:1337-1366

`python
# Input from routing decision
routing.intent_key == "PORTFOLIO_AUDIT"  # True for portfolio queries

# Execution
portfolio_sentinel = None
if routing.intent_key == "PORTFOLIO_AUDIT":
    BUS.emit(session_id, "phase", phase="portfolio_identify", 
             note="Loading tenant-scoped active holdings")
    
    if not cfg.tenant_id:
        BUS.emit(session_id, "warning", 
                message="Portfolio audit requires a verified tenant_id.")
    else:
        try:
            from finagent.portfolio_sentinel import run_portfolio_sentinel
            
            # Load holdings from database
            portfolio_sentinel = await run_portfolio_sentinel(cfg.tenant_id)
            
            # Emit diagnostics event
            BUS.emit(
                session_id,
                "portfolio_identify",
                tenant_id=cfg.tenant_id,
                positions_found=portfolio_sentinel.positions_found,
                symbols=portfolio_sentinel.symbols,
                weights=portfolio_sentinel.weights,
                error=portfolio_sentinel.error,
            )
            
            # Emit risk analysis event
            BUS.emit(
                session_id,
                "portfolio_sentinel",
                risk=portfolio_sentinel.risk,
                rules=portfolio_sentinel.rules,
                concentration_alert=portfolio_sentinel.concentration_alert,
                error=portfolio_sentinel.error,
            )
        except Exception as exc:
            logger.warning("Portfolio Sentinel preflight failed: %s", exc)
            BUS.emit(session_id, "warning", 
                    message=f"Portfolio Sentinel failed: {exc}")

# Typical portfolio_sentinel output:
# PortfolioSentinelResult(
#     tenant_id="user123",
#     positions_found=15,
#     symbols=["RELIANCE.NS", "INFY.NS", "TCS.NS", "AXISBANK.NS", ...],
#     weights={
#         "RELIANCE.NS": 0.25,
#         "INFY.NS": 0.18,
#         "TCS.NS": 0.15,
#         "AXISBANK.NS": 0.12,
#         ...
#     },
#     risk={
#         "hhi_analysis": {"hhi_decimal": 0.18, "concentration": "moderate"},
#         "correlation_matrix": [...],
#         "beta_vs_nifty": 0.95,
#         "portfolio_volatility": 0.22,
#     },
#     rules=["High structural concentration detected..."],
#     concentration_alert=False,
#     error=None
# )
`

### run_portfolio_sentinel() Detail
**File**: inagent/portfolio_sentinel.py:35-63

`python
async def run_portfolio_sentinel(tenant_id: str) -> PortfolioSentinelResult:
    result = PortfolioSentinelResult(tenant_id=tenant_id)
    
    # Step 1: Load positions from database
    positions = load_active_positions(tenant_id)
    # Returns: list[PositionMirror] sorted by market_value DESC
    # Each PositionMirror contains:
    #   - symbol: "RELIANCE.NS" or "120308" (for MFs via AMFI)
    #   - exchange: "NSE", "BSE", or "AMFI"
    #   - kind: "equity", "mf"
    #   - quantity, market_value, cost_basis
    #   - name, isin, amfi, sector, industry
    
    result.positions_found = len(positions)
    
    # Step 2: Extract symbols and weights
    result.symbols = [pos.exchange_symbol for pos in positions if pos.exchange_symbol]
    result.weights = portfolio_weights(positions)
    # weights = {symbol: market_value / total_portfolio_value}
    
    if not result.weights:
        result.error = "No active portfolio holdings found. Upload eCAS or CSV positions first."
        return result
    
    # Step 3: Compute portfolio risk metrics
    try:
        from finagent.tools.mcp_servers.quant_server import run_full_portfolio_risk
        
        portfolio_value = sum(pos.market_value for pos in positions if pos.market_value > 0)
        risk = await asyncio.to_thread(
            run_full_portfolio_risk,
            result.weights,           # {symbol: weight}
            "^NSEI",                 # benchmark (Nifty 50)
            "1y",                    # lookback period
            portfolio_value,         # total value in rupees
        )
        result.risk = risk if isinstance(risk, dict) else {"error": "Unexpected risk result"}
        
        # Check concentration alert (HHI >= 0.25 = high concentration)
        if result.concentration_alert:
            result.rules.append(CONCENTRATION_RULE)
    except Exception as exc:
        logger.warning("Portfolio Sentinel failed for tenant %s: %s", tenant_id, exc)
        result.error = str(exc)
    
    return result
`

---

## 5. MUTUAL FUND HOLDINGS ACCESS

### Source Code Reference
**File**: inagent/portfolio_mirrors.py:189-229 + inagent/portfolio/mf_analytics.py

### Loading MF Holdings

`python
# Load all active positions (both equity and MF)
def load_active_positions(tenant_id: str) -> list[PositionMirror]:
    with connect_wal(db_path) as conn:
        rows = conn.execute("""
            SELECT tenant_id, symbol, exchange, quantity, market_value, cost_basis, active,
                   name, isin, amfi, kind, sector, industry, avg_cost, last_price, as_of
            FROM position_mirrors
            WHERE tenant_id = ? AND active = 1
            ORDER BY market_value DESC, symbol ASC
        """, (tenant_id,)).fetchall()
    
    # Example result for a portfolio with equities + MFs:
    # [
    #   PositionMirror(
    #       symbol="RELIANCE.NS", exchange="NSE", kind="equity",
    #       market_value=50000, ...
    #   ),
    #   PositionMirror(
    #       symbol="120308", exchange="AMFI", kind="mf",
    #       amfi="120308", name="Axis Direct Equity Fund",
    #       market_value=30000, ...
    #   ),
    #   ...
    # ]

# Filter to MF-only positions
mf_positions = [p for p in positions if p.kind == "mf"]

# Example MF positions structure:
# [
#   {
#       "symbol": "120308",
#       "exchange": "AMFI",
#       "kind": "mf",
#       "amfi": "120308",
#       "name": "Axis Direct Equity Fund - Regular Plan",
#       "market_value": 30000.0,
#       "quantity": 1250.0,  # units held
#       "category": "large_cap" (derived)
#   },
#   {
#       "symbol": "123456",
#       "exchange": "AMFI",
#       "kind": "mf",
#       "amfi": "123456",
#       "name": "ICICI Prudential Equity Fund",
#       "market_value": 20000.0,
#       "quantity": 800.0
#   }
# ]
`

### Analyzing MF Holdings

`python
def compute_mf_analytics(positions: list[PositionMirror]) -> dict[str, Any] | None:
    mf_positions = [p for p in positions if p.kind == "mf"]
    if not mf_positions:
        return None
    
    # Load AMFI scheme metadata
    meta = _load_scheme_meta()
    # meta = {
    #   "120308": {
    #       "ter": 0.75,           # Total Expense Ratio: 0.75%
    #       "amc": "Axis",         # Asset Management Company
    #       "scheme_type": "large-cap direct"
    #   },
    #   "123456": {
    #       "ter": 0.65,
    #       "amc": "ICICI Prudential",
    #       "scheme_type": "large-cap regular"
    #   }
    # }
    
    total_mf_value = sum(p.market_value for p in mf_positions if p.market_value > 0)
    
    # Compute metrics
    amc_totals = {}
    category_totals = {}
    weighted_ter = 0.0
    scheme_types = {}
    
    for pos in mf_positions:
        weight = pos.market_value / total_mf_value
        scheme_meta = meta.get(pos.amfi, {})
        ter = scheme_meta.get("ter", 0.0)
        amc = scheme_meta.get("amc", "Unknown")
        scheme_type = scheme_meta.get("scheme_type", "")
        
        weighted_ter += weight * ter
        amc_totals[amc] = amc_totals.get(amc, 0.0) + pos.market_value
        category = _classify_mf_category(pos.name, scheme_type)
        category_totals[category] = category_totals.get(category, 0.0) + pos.market_value
        scheme_types[scheme_type or category] = scheme_types.get(scheme_type or category, 0) + 1
    
    # Return structured result
    return {
        "status": "OK",
        "total_mf_value": round(total_mf_value, 2),        # e.g., 50000.0
        "scheme_count": len(mf_positions),                 # e.g., 2
        "aum_weighted_ter_pct": round(weighted_ter, 2),   # e.g., 0.71
        "category_breakdown": {                            # MF asset class breakdown
            "large_cap": 55.0,      # % of MF portfolio
            "mid_cap": 25.0,
            "small_cap": 20.0,
        },
        "amc_concentration": {                             # AMC concentration
            "Axis": 60.0,           # % of MF portfolio
            "ICICI Prudential": 40.0,
        },
        "scheme_type_counts": {
            "large-cap direct": 1,
            "large-cap regular": 1,
        },
        "lookthrough_exposure": {},  # Placeholder for Phase 2
    }
`

---

## 6. WEB SEARCH PIPELINE - LAYERED EXECUTION

### Source Code Reference
**File**: inagent/tools/web/scraper.py:1090-1180

### search_layered() Flow

`python
async def search_layered(
    target: str,                          # Company name (e.g., "Reliance Industries")
    on_query: Callable[[str, str, int], None],  # Progress callback
    queries: list[str],                   # 4-6 angled queries
    preferred_domains: list[str],         # NSE, BSE, Moneycontrol, etc.
    entity: ResolvedEntity,
    timeout_s: float = 90.0,
) -> list[ScrapedDoc]:
    """Execute breadth survey queries in parallel, return all unique docs."""
    
    all_docs: list[ScrapedDoc] = []
    seen_urls: set[str] = set()
    
    async def _one(q: str) -> list[ScrapedDoc]:
        on_query(q, "running", 0)
        try:
            # Use search_web() for single query
            results = await asyncio.wait_for(
                search_web(
                    q,
                    max_results=15,
                    preferred_domains=preferred_domains,
                    entity=entity,
                ),
                timeout=timeout_s / len(queries),
            )
            on_query(q, "done", len(results))
            return results
        except asyncio.TimeoutError:
            on_query(q, "timeout", 0)
            return []
        except Exception as exc:
            on_query(q, "error", 0)
            return []
    
    # Execute queries in parallel
    tasks = [_one(q) for q in queries]
    results_batch = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Deduplicate by URL
    for batch in results_batch:
        for doc in batch:
            url_key = (doc.final_url or doc.url).split("#", 1)[0]
            if url_key not in seen_urls:
                all_docs.append(doc)
                seen_urls.add(url_key)
    
    return all_docs

# Example breadth queries for "Reliance Industries":
# [
#     "Reliance Industries latest financial results earnings",
#     "Reliance Industries annual report risk factors",
#     "Reliance Industries management board governance",
#     "Reliance Industries valuation PE ratio target price",
#     "Reliance Industries peer comparison vs ONGC, TCS",
#     "Reliance Industries news announcements latest updates"
# ]
`

### search_web() Detail (Stage-Based)

`python
async def search_web(
    query: str,
    max_results: int = 15,
    preferred_domains: list[str],
    entity: ResolvedEntity,
) -> list[ScrapedDoc]:
    """Multi-stage search: SearXNG/Tavily (snippets) + Crawl4AI (deep extraction)"""
    
    # Stage 1: Candidate sourcing
    # Primary: SearXNG (self-hosted) or Tavily API
    # Fallback: DDG + Bing HTML scrapers
    
    searxng_results = await SearXNGClient().search(query, max_results)
    tavily_results = await _search_tavily(query, max_results)
    combined_candidates = deduplicate(searxng_results + tavily_results)
    
    # Stage 2: URL selection for deep extraction
    selected_urls = [
        c.url for c in combined_candidates[:8]
        if not is_blocked(c.domain)
    ]
    
    # Stage 3: Deep extraction via Crawl4AI
    crawl4ai_docs = await crawl4ai_batch(selected_urls, timeout=30.0)
    
    # Stage 4: Combine snippet-level docs with extracted docs
    final_docs = []
    
    # Snippet-level (lightweight, fast)
    for cand in combined_candidates:
        final_docs.append(ScrapedDoc(
            url=cand.url,
            title=cand.title,
            excerpt=cand.snippet,  # Pre-extracted snippet
            domain=extract_domain(cand.url),
            tier=score_tier(cand.url, preferred_domains),
            final_url=cand.url,
        ))
    
    # Extracted (heavy, precise)
    for crawled in crawl4ai_docs:
        final_docs.append(ScrapedDoc(
            url=crawled.url,
            title=crawled.title,
            excerpt=crawled.markdown[:500],  # Full-text extraction
            domain=extract_domain(crawled.url),
            tier=1,  # Tier 1 (highest) for successfully extracted
            final_url=crawled.final_url,
            full_text=crawled.markdown,
        ))
    
    return final_docs
`

---

## 7. COMPLEXITY-BASED CONFIGURATION EXAMPLE

### User Query: "I want a deep analysis of Reliance's valuation"

`python
# Step 1: Query classification
objective = "I want a deep analysis of Reliance's valuation"
complexity = _classify_complexity(objective)
# Matches "deep analysis" and "valuation"
# → returns "complex"

# Step 2: Routing
routing = route_objective(objective, entity)
# Result:
RoutingDecision(
    selected_agents=["valuation", ...],
    query_complexity="complex",
    deep_research=True,
    skip_reflection=False,
    skip_blindspot=False,
    skip_deep_dive=False,
    max_deep_dive_rounds=4,
)

# Step 3: Pipeline configuration
if mode == "standard":  # User selected "research"
    config = AgentLoopConfig(
        max_steps=38,
        enable_scraping=True,
        enable_enrichment=True,
        enable_deep_dive=True,
        enable_multi_agent=True,
        enable_blindspot=True,
        enable_reflection=True,
        reflection_max_rounds=3,
        reflection_per_query_timeout=35.0,
        blindspot_per_query_timeout=30.0,
        breadth_search_timeout=90.0,
        followup_search_timeout=45.0,
        quality_threshold=70.0,
        reflection_max_new_docs=60,
    )
elif mode == "deep":
    config = AgentLoopConfig(
        max_steps=60,
        ...timeouts are 150s+ instead of 90s/45s
        reflection_max_rounds=5,
        reflection_max_new_docs=80,
        quality_threshold=75.0,
    )

# Step 4: Execution phases
# Phase 0: Memory recall (12 prior facts if available)
# Phase 1: Enrichment (Yahoo Finance, Wikipedia, NSE/BSE snapshot)
# Phase 2: Breadth Survey (4-6 angled queries via search_layered)
# Phase 3: Deep Dive (4 rounds of iterative follow-ups to fill gaps)
# Phase 4: Analysis (conflict detection, cross-source verification)
# Phase 5: Synthesis (integrated memo with DCF, comparables, etc.)
# Phase 6: Verification (accuracy checking on key claims)
`

---

## 8. ERROR HANDLING - CONTEXTUALIZER FALLBACK

### Source Code Reference
**File**: inagent/router/intent_router.py:282-347 + gateway/run.py:1606-1611

`python
async def contextualize(self, query: str, prior_target: str, chat_history):
    """Dual-provider fallback for follow-up detection."""
    
    # Primary attempt
    primary_cfg = resolve_openai_config()
    if primary_cfg:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=primary_cfg.api_key, base_url=primary_cfg.base_url)
            result = await _invoke_llm(client, primary_cfg.model, system_prompt, query)
            logger.info("[ROUTER-LLM] primary_success")
            return result
        except Exception as primary_exc:
            logger.warning("[ROUTER-LLM] primary_failed | will_try_grok_fallback")
    
    # Fallback: Grok/xAI
    xai_key = os.getenv("XAI_API_KEY")
    if xai_key:
        try:
            from openai import AsyncOpenAI
            grok_client = AsyncOpenAI(api_key=xai_key, base_url="https://api.x.ai/v1")
            grok_model = os.getenv("FINAGENT_XAI_MODEL", "grok-3-mini")
            result = await _invoke_llm(grok_client, grok_model, system_prompt, query)
            logger.info("[ROUTER-LLM] grok_fallback_success")
            return result
        except Exception as grok_exc:
            logger.warning("[ROUTER-LLM] grok_fallback_failed | error=%s", grok_exc)
    
    # Both failed
    raise ContextualizerError(
        "All LLM contextualizer providers failed (OpenAI and xAI both unavailable). "
        "Cannot determine whether this is a follow-up query."
    )

# Gateway error handling
try:
    result = await contextualizer.contextualize(raw_query, prior_target, chat_history)
    is_followup = result.is_followup
except ContextualizerError as exc:
    logger.error("Contextualizer failed for session %s: %s", session_id, exc)
    raise HTTPException(status_code=503, detail="Context service unavailable")
except Exception as exc:
    logger.error("Unexpected contextualizer error for session %s: %s", session_id, exc)
    raise HTTPException(status_code=503, detail="Context service unavailable")
`

---


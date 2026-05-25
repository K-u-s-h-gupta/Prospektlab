# FINAGENT QUERY ROUTING: QUICK REFERENCE

## Query Classification Decision Tree

`
Query arrives at /research/start
    ↓
Extract primary target from query
    ↓
Is there a prior conversation?
    ├─ YES → Use LLMQueryContextualizer
    │        - Check if follow-up (pronouns: it, its, they, their, this/that/same company)
    │        - Rewrite pronouns to company names
    │        - Detect if target changed (new session if yes)
    └─ NO → Use primary_target_from_query()

Does query match portfolio patterns?
    ├─ YES (my portfolio, our portfolio, portfolio risk, portfolio audit, risk audit,
    │        our/my holdings, holdings audit, concentration risk, asset allocation)
    │        ↓
    │   PORTFOLIO AUDIT PATH:
    │   • intent_key = "PORTFOLIO_AUDIT"
    │   • complexity = "complex" (forced)
    │   • deep_research = True
    │   • agents = [risk, governance, accounting, financials, valuation, ...]
    │   • Load tenant positions from portfolio_mirrors table
    │   • Compute portfolio analytics (HHI, concentration, correlation, beta)
    │   • Multi-agent analysis of holdings
    │   • Result: Portfolio audit memo
    │
    └─ NO → STANDARD RESEARCH PATH
           ↓
        Classify complexity (simple/moderate/complex):
           ├─ SIMPLE: "pe ratio", "share price", "current price", "eps", "dividend yield"
           │          → Skip reflection, blindspot, deep-dive | max_rounds=0
           │
           ├─ MODERATE: "earnings", "revenue growth", "balance sheet", "news"
           │            → Run 1 deep-dive round | Skip blindspot | max_rounds=1
           │
           └─ COMPLEX: "deep", "comprehensive", "compare", "peer analysis", "risk factors"
                       → Full pipeline | all phases enabled | max_rounds=4

        Select agents via AGENT_KEYWORDS matching:
           • financials: revenue, margin, balance sheet, cash flow
           • risk: risk, lawsuit, investigation, fraud
           • news: news, headline, update, earnings
           • governance: governance, board, management, insider
           • valuation: valuation, dcf, target price
           • accounting: forensic, anomaly, red flag, manipulation
           • (+ competitor, technical, community, macro agents)

        Execute web search pipeline:
           1. Breadth Survey: search_layered (4-6 angled queries, SearXNG+Tavily+DDG+Bing)
           2. Deep Dive: Iterative follow-up queries (if complexity >= moderate)
           3. Analysis: Cross-source conflict detection
           4. Synthesis: Multi-agent memo generation
           5. Verification: Accuracy checking
           ↓
           Result: Company snapshot, investment view, or deep research report
`

---

## Portfolio Scope Detection Patterns

Exact string matching (case-insensitive):
`
"my portfolio"              → PORTFOLIO_AUDIT
"our portfolio"            → PORTFOLIO_AUDIT
"portfolio risk"           → PORTFOLIO_AUDIT
"portfolio audit"          → PORTFOLIO_AUDIT
"risk audit"               → PORTFOLIO_AUDIT
"our holdings"             → PORTFOLIO_AUDIT
"my holdings"              → PORTFOLIO_AUDIT
"holdings audit"           → PORTFOLIO_AUDIT
"portfolio concentration"  → PORTFOLIO_AUDIT
"concentration risk"       → PORTFOLIO_AUDIT
"asset allocation"         → PORTFOLIO_AUDIT
`

---

## Follow-up Question Context Handling

LLMQueryContextualizer (async, dual-provider):

**Primary**: OpenAI API (via OPENAI_API_KEY, base_url)
**Fallback**: Grok/xAI (via XAI_API_KEY, model=grok-3-mini or FINAGENT_XAI_MODEL)

**Input**:
- prior_target: company from session metadata
- query: current user question
- chat_history: last 6 turns (300 chars max per turn)

**Output**:
`json
{
  "is_followup": boolean,
  "contextualized_query": "pronoun-free, self-contained query",
  "target": "company name or null"
}
`

**Decision Logic**:
- Follow-up: pronouns (it, its, they, their, this/that company) + short query (≤8 words) + prior entity
- New topic: introduces different company OR no pronouns + not short-query pattern

**Side Effects**:
- If target changed: new session_id created, prevents data leakage
- If follow-up: complexity may be reduced for simple intents (news, valuation, price_history)

---

## Mutual Fund Holdings Tracking

**Storage**: SQLite table position_mirrors
**Key Columns**:
- kind: "equity" or "mf"
- mfi: AMFI scheme code (6 digits) for mutual funds
- isin: ISIN code (for all securities)
- symbol: NSE/BSE/AMFI identifier
- exchange: "NSE", "BSE", or "AMFI" (for mutual funds)
- market_value: current value
- quantity: units held

**MF Analytics** (compute_mf_analytics):
- Total MF value in portfolio
- AUM-weighted TER (Total Expense Ratio)
- Category breakdown: large_cap, mid_cap, small_cap, debt, hybrid, elss, liquid, index_etf
- AMC (Asset Management Company) concentration
- Scheme type counts
- Lookthrough exposure (placeholder for Phase 2)

**Access Path**:
`
portfolio_sentinel (for portfolio queries)
    ↓
load_active_positions(tenant_id)
    ↓
filter(positions, kind="mf")
    ↓
compute_mf_analytics(mf_positions)
`

---

## Web Search Routing vs Portfolio Analysis

**Web Search Triggered When**:
- Query is NOT portfolio-scoped (no "my portfolio" / "portfolio risk" / etc.)
- Query targets specific entity (company/stock name extracted)
- Enable_scraping = True (default for standard/deep modes)

**Pipeline**:
1. search_layered() → 4-6 angled queries to SearXNG/Tavily/DDG/Bing
2. Parallel doc processing (tier-based scoring)
3. Deep-dive (iterative follow-up queries)
4. Synthesis (template + facts-based memo)

**Portfolio Analysis Triggered When**:
- Query matches _PORTFOLIO_SCOPE_PATTERNS (string matching)
- intent_key = "PORTFOLIO_AUDIT"
- complexity = "complex" (forced)
- Portfolio synchronized for tenant_id

**Pipeline**:
1. run_portfolio_sentinel() → load holdings, compute risk metrics
2. Parallel enrichment for top holdings (by weight)
3. Multi-agent analysis (risk, governance, accounting agents)
4. Synthesis (portfolio audit memo with concentration alerts)

---

## Complexity Classification → Phase Execution

`
Phase                | Simple | Moderate | Complex | Portfolio
---------------------|--------|----------|---------|----------
Reflection (iterative) | SKIP   | RUN     | RUN    | RUN
Blindspot (gap finder) | SKIP   | SKIP    | RUN    | RUN
Deep-Dive (follow-ups) | SKIP   | RUN 1x  | RUN 4x | RUN 4x
Multi-Agent            | LIMITED| LIMITED | RUN    | RUN
Search Timeout         | 45s    | 90s     | 150s   | 150s+
Max Steps              | 28     | 38      | 60     | 60+
`

**Simple Query Config**:
`
enable_multi_agent = True
enable_blindspot = False
enable_reflection = True
reflection_max_rounds = 1
skip_reflection = True
skip_blindspot = True
skip_deep_dive = True
`

**Moderate Query Config**:
`
enable_multi_agent = True
enable_blindspot = False
enable_reflection = True
reflection_max_rounds = 1
skip_reflection = False
skip_blindspot = True
skip_deep_dive = False
max_deep_dive_rounds = 1
`

**Complex Query Config**:
`
enable_multi_agent = True
enable_blindspot = True
enable_reflection = True
reflection_max_rounds = 3-5
skip_reflection = False
skip_blindspot = False
skip_deep_dive = False
max_deep_dive_rounds = 4
`

---

## Agent Keyword Taxonomy

| Agent | Keywords |
|-------|----------|
| financials | financial, revenue, margin, balance sheet, cash flow, valuation, forecast, guidance, outlook |
| risk | risk, lawsuit, investigation, fraud, headwind |
| technical | technical, chart, momentum, breakout, moving average |
| news | news, headline, update, earnings, deal, commentary, forecast, outlook, catalyst |
| community | sentiment, retail, community, buzz |
| competitor | compare, competitor, peer, vs, versus, market share |
| macro | macro, rates, inflation, fx, commodity, sector, forecast, outlook |
| governance | governance, board, management, insider, compensation |
| valuation | valuation, dcf, intrinsic value, target price, upside, undervalued, overvalued |
| accounting | accounting, anomaly, forensic, earnings quality, restatement, red flag, manipulation |

**Portfolio Audit Override**:
Always includes: [risk, governance, accounting, financials, valuation] + any matched agents

---

## Key Files & Line References

| Component | File | Key Function |
|-----------|------|--------------|
| Portfolio Detection | outer/intent_router.py:123 | is_portfolio_scope_query() |
| Routing Decision | outer/intent_router.py:128 | oute_objective() |
| Follow-up Context | outer/intent_router.py:214 | LLMQueryContextualizer.contextualize() |
| Gateway Entry | gateway/run.py:1558 | start_research() POST /research/start |
| Portfolio Sentinel | portfolio_sentinel.py:35 | un_portfolio_sentinel() |
| Holdings Storage | portfolio_mirrors.py:189 | load_active_positions() |
| MF Analytics | portfolio/mf_analytics.py:56 | compute_mf_analytics() |
| Web Search | 	ools/web/scraper.py:888 | search_web() |
| Intent Classifier | output/intent_classifier.py:88 | primary_target_from_query() |

---

## Complexity Patterns

### Simple Patterns (return "simple")
`
pe ratio, p/e, pb ratio, p/b, current price, share price, stock price,
live price, market cap, eps, dividend yield, book value, 52 week,
what is the price, historical price, price history, stock history,
share price history, face value, circuit limit
`

### Moderate Patterns (return "moderate")
`
quarterly results, earnings, revenue growth, profit, net income,
ebitda, margin, balance sheet, cash flow, latest news,
recent news, sector outlook, analyst target, shareholding,
fii holding, dii holding
`

### Complex Patterns (return "complex")
`
deep, comprehensive, exhaustive, due diligence, full analysis,
investigate, compare, vs, versus, peer analysis, risk factors,
sebi, fraud, investigation, governance, long term,
investment thesis, initiation, moat
`

---

## Operational Intent Classification

When LLM or pattern matching determines intent:

| Focus | Patterns | Use Case |
|-------|----------|----------|
| snapshot | (default) | Company overview |
| news | latest news, recent news, updates, headlines | News brief |
| valuation | valuation, p/e, ev/ebitda, target price, multiples | Valuation insight |
| financials | results, revenue, profit, margin, balance sheet, cash flow | Financial analysis |
| price_history | historical price, past price, stock history | Price trends |
| shareholding | shareholding, promoter, fii, dii, pledge | Shareholding patterns |
| risk | risk, red flag, governance, lawsuit, investigation, penalty | Risk assessment |

---

## Session Isolation & Target Switching

When user asks about different company mid-conversation:

`
Session 1: "Reliance share price"
    → target = "Reliance"
    → session_id = abc123

Query 2: "What about TCS?"
    → LLMQueryContextualizer detects new target
    → is_followup = False
    → target changed: "Reliance" → "TCS"
    → NEW session_id = def456 (created)
    → BUS.open(def456, reset=True)
    
Effect:
- Prevents accidental mixing of Reliance/TCS search results
- Separate memory/cache for each company
- Clean event history per company in UI
`


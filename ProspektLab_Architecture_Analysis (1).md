# ProspektLab / ORACLE FIOS — Architecture Analysis & Optimization Report
> Deep analysis of critical gaps, high-value integrations, and the Chronos-2 roadmap  
> Prepared: May 2026

---

## TABLE OF CONTENTS

1. [Architecture Assessment Summary](#1-architecture-assessment-summary)
2. [Critical Architecture Optimizations](#2-critical-architecture-optimizations)
3. [Portfolio System — What You Provide & What's Missing](#3-portfolio-system--what-you-provide--whats-missing)
4. [Con Calls, Annual Reports & Corporate Announcements — Full Integration Plan](#4-con-calls-annual-reports--corporate-announcements--full-integration-plan)
5. [Chronos-2 Deep Research & Integration Blueprint](#5-chronos-2-deep-research--integration-blueprint)
6. [Other Major Models & Tools to Integrate](#6-other-major-models--tools-to-integrate)
7. [Obsession-Driving UX Enhancements](#7-obsession-driving-ux-enhancements)
8. [Priority Execution Roadmap](#8-priority-execution-roadmap)
9. [Karpathy autoresearch Pattern — Impact Analysis & Integration Blueprint](#9-karpathy-autoresearch-pattern--impact-analysis--integration-blueprint)

---

## 1. ARCHITECTURE ASSESSMENT SUMMARY

ProspektLab is already a seriously sophisticated financial intelligence OS. You have an 8-phase research pipeline, 10+ specialist agents, wave-based parallel orchestration, MCP microservices, NSE/BSE/SEBI integration, portfolio ingestion from CAS, and a Qdrant-backed documents server. The core bones are sound.

**The major gap categories identified:**

| Gap Category | Severity | User Impact |
|---|---|---|
| No earnings call / con call ingestion | 🔴 Critical | Users can't query "what did TCS management say about margins?" |
| No annual report / AR deep-read pipeline | 🔴 Critical | Valuation quality misses management guidance context |
| Forecasting is deterministic CAGR only — no ML | 🔴 Critical | Price/earnings estimates lack confidence intervals |
| LLM is single-provider (OpenAI only) | 🟠 High | Single point of failure for all synthesis |
| SQLite at scale will break | 🟠 High | WAL mode won't survive concurrent users in production |
| No real-time SEBI corporate action alerts push | 🟠 High | Users miss dividends, buybacks, splits in their portfolio |
| Sentiment scoring is community/Reddit only | 🟠 High | Management tone from earnings not captured |
| No multi-turn memory for financial context | 🟡 Medium | Follow-up queries lose prior research context |
| Frontend charts are minimal (only Area + Bar) | 🟡 Medium | Poor data visualization reduces trust in numbers |
| No sector/macro overlay for portfolio positions | 🟡 Medium | Portfolio analysis is position-level, not macro-aware |

---

## 2. CRITICAL ARCHITECTURE OPTIMIZATIONS

### 2.1 Replace SQLite with a Proper Production Backend

**Current:** All memory, session state, portfolio data, and news cache are in SQLite (WAL mode).  
**Problem:** WAL mode is excellent for local/single-writer but breaks under concurrent Fargate tasks. When your ECS service scales to 2+ tasks, each has its own SQLite file — data diverges silently.

**Fix:**
```
SQLite (dev) → PostgreSQL (prod) via Supabase (you already have Supabase!)
```
- `memory.sqlite3` → Supabase Postgres `memory_facts` table with `pg_trgm` for fuzzy search (replaces FTS5)
- `news_cache.sqlite3` → Supabase Postgres with a TTL column + `pg_cron` for expiry
- Portfolio holdings → Already targeting Supabase; complete the migration for `portfolio_mirrors`
- Research sessions/checkpoints → Supabase Postgres with `sessions` + `checkpoints` tables
- Keep SQLite only for local dev with a `FINAGENT_DB_BACKEND=sqlite|postgres` toggle

**Impact:** Enables horizontal scaling on Fargate without data divergence. Zero new cost — you're already paying for Supabase.

---

### 2.2 Upgrade LLM Layer to Multi-Provider with Fallback

**Current:** `OPENAI_API_KEY` only — template fallback otherwise.  
**Problem:** OpenAI downtime = full system degradation. Also misses Gemini's massive 1M context window (critical for reading entire annual reports in one shot).

**Fix: LLM Router Layer**
```python
# New: llm_router.py
class LLMRouter:
    providers = [
        ("claude-3-5-sonnet", priority=1, context=200k),   # Best reasoning
        ("gemini-2.0-flash", priority=2, context=1M),       # Long docs (ARs, con calls)
        ("gpt-4o", priority=3, context=128k),               # Existing primary
        ("gpt-4o-mini", priority=4, context=128k),          # Cost fallback
    ]
    
    def route(self, task_type: str) -> str:
        if task_type == "annual_report_read":
            return "gemini-2.0-flash"   # 1M context = full AR in single call
        if task_type == "con_call_analysis":
            return "claude-3-5-sonnet"  # Best at nuanced reasoning
        return "gpt-4o"                 # Default
```

**Key insight:** Use **Gemini 1.5 Pro / 2.0 Flash's 1M token context** specifically for reading full annual reports (typically 200–400 pages) without chunking. This is a massive accuracy win over your current RAG approach for long documents.

---

### 2.3 Fix the Valuation Agent — Add Probabilistic Forecasting

**Current:** `valuation.py` uses "deterministic DCF, CAGR fallback (no ML forecasting dependency)". The `accounting.py` references TimesFM for anomaly detection but it's absent in production.

**Problem:** Deterministic DCF gives a single point estimate with no confidence range. Users (especially retail investors) don't know how uncertain the number is. A bad estimate with high confidence kills trust permanently.

**Fix:** See Section 5 for the complete Chronos-2 integration. The short version: replace the CAGR extrapolation in `valuation.py` with Chronos-2's probabilistic P10/P50/P90 corridors for revenue and earnings forecasts. The DCF model then becomes a distribution, not a point.

---

### 2.4 Add a Dedicated MCP Server for Documents & Filings (Port 8006)

**Current:** `docs_server.py` at port 8004 handles PDF ingest, annual report fetch, and Qdrant. It's overloaded.  
**Problem:** Annual reports, con call transcripts, and DRHP/prospectuses are all structurally different documents requiring different parsing strategies. Lumping them together hurts retrieval quality.

**Fix: Split into specialized document servers:**

```
Port 8004 → docs_server.py (existing: DRHP/RHP, general PDFs)
Port 8006 → NEW: filings_server.py (annual reports, quarterly results, investor presentations)
Port 8007 → NEW: transcripts_server.py (earnings calls, AGM transcripts, con call notes)
```

Each server uses a different chunking strategy:
- Annual reports: section-aware chunking (MD&A, Financials, Notes, Risk Factors as separate chunks)
- Con calls: speaker-turn chunking + Q&A extraction
- SEBI filings: paragraph-level with regulation cross-reference indexing

---

### 2.5 Implement a Proper Caching Layer (Redis)

**Current:** HTTP fetch concurrency capped at 6. News caching is SQLite. No shared cache across MCP services.  
**Problem:** Every research request re-fetches the same NSE data, Yahoo Finance data, and news articles. At scale, this creates rate limiting and latency.

**Fix:**
```
Add Redis (AWS ElastiCache t3.micro ≈ $15/month) for:
  - NSE/Yahoo quote cache: TTL 60s (real-time feel without hammering APIs)
  - News cache: TTL 15 minutes
  - Research enrichment bundle: TTL 30 minutes
  - Con call transcript store: TTL 7 days
```

This alone can cut your Phase 2 (Enrichment) time from ~8 seconds to under 1 second for cached tickers — which directly drives user obsession through speed.

---

### 2.6 Add Streaming Research Phase Summaries

**Current:** SSE streams phase updates and agent progress, but the content of each phase arrives only at synthesis (end).  
**Problem:** A 2-5 minute deep research response with a spinner is a retention killer. Users abandon.

**Fix: Progressive research streaming**
```
Phase 3 completes → immediately stream: 
  "📰 Found 47 sources. Top signal: TCS guided 12% revenue growth in Q4 call."

Phase 6 (Valuation agent) completes → stream:
  "💰 Valuation: DCF fair value ₹4,200–₹4,800 (P10–P90). Current: ₹3,950. Upside: ~6–21%"

Phase 6 (Risk agent) completes → stream:
  "⚠️ Risk: 3 red flags detected. Employee attrition rate rising 18% YoY."
```

This is the single biggest UX win for user obsession. Users feel they're watching a live analyst work, not waiting for a black box.

---

### 2.7 Structured Claim Confidence Display

**Current:** `confidence_scorer.py` computes scores, but the final memo shows a flat research quality score (82/100). Users don't see per-claim confidence.  
**Problem:** "TCS revenue ₹200,000 Cr" and "possible promoter pledging concern" look equally authoritative in the output.

**Fix:** Add inline confidence badges to every claim in the memo:
```
TCS Revenue: ₹2,40,893 Cr  [NSE ✓] [HIGH confidence]
Fair Value: ₹4,200–4,800   [DCF model] [MEDIUM confidence — 3 estimates diverge]
Governance concern flagged  [Reddit + 1 news source] [LOW confidence — unverified]
```

This is what makes users trust the system deeply — transparency about uncertainty.

---

## 3. PORTFOLIO SYSTEM — WHAT YOU PROVIDE & WHAT'S MISSING

### What You Currently Provide (from architecture)

| Feature | Status |
|---|---|
| CAS / eCAS statement ingestion (PDF/image) | ✅ Built |
| ISIN resolution to NSE/BSE symbol | ✅ Built |
| Portfolio analytics: risk metrics, NAV history | ✅ Built |
| Beta-based stress testing vs Nifty | ✅ Built |
| Sector breakdown | ✅ Built |
| Corporate actions: dividends, splits, bonuses | ✅ Built |
| Tax summary (LTCG/STCG) | ✅ Built |
| Portfolio-scoped news | ✅ Built |
| Mutual fund analytics | ✅ Built |
| "5 things you should know today" action queue | ✅ Built |
| Concentration alerts | ✅ Built |

### Critical Gaps in Portfolio System

**Gap 1: No Fundamental Quality Score per Holding**  
Users can see their holdings but not "which of my 15 stocks are fundamentally weak right now?" Add a Piotroski F-Score + Altman Z-Score badge on every holding card (you already compute these in `valuation_engine.py`).

**Gap 2: No Earnings Calendar for Portfolio Holdings**  
Show users: "In the next 14 days, 4 of your holdings report results: TCS (Tue), HDFC Bank (Thu)..." This creates daily retention.

**Gap 3: No Portfolio-Level Con Call Digest**  
When TCS reports quarterly results, users with TCS in their portfolio should get: "Your holding TCS just had an earnings call. Management guided for 12% revenue growth. 3 analysts asked about margin pressure. Key risk: higher visa costs for US operations." This is the killer feature described in Section 4.

**Gap 4: No What-If / Scenario Modeler**  
"What happens to my portfolio if Nifty drops 15%?" — you have stress_test.py but it's beta-based and Nifty-only. Extend it to: FII outflow scenarios, RBI rate hike scenarios, INR depreciation scenarios.

**Gap 5: No Entry/Exit Signals Integrated into Portfolio View**  
The technical agent runs standalone for research. It should overlay on portfolio holdings to show: "TCS: RSI 71 (overbought). Consider trimming 10%."

**Gap 6: No SIP/DCA Optimizer**  
For mutual fund holdings, show: "At your current SIP of ₹5,000/month in Axis Bluechip, you'll reach ₹X in Y years." Indian retail users are heavily SIP-oriented.

---

## 4. CON CALLS, ANNUAL REPORTS & CORPORATE ANNOUNCEMENTS — FULL INTEGRATION PLAN

This is the biggest feature gap and the biggest opportunity for user obsession. Here's the complete blueprint.

### 4.1 Earnings Call / Conference Call Transcripts

**Sources for India:**
| Source | Coverage | Access Method |
|---|---|---|
| **Trendlyne** | Most NSE/BSE listed companies | Web scraping (Crawl4AI — you already have it) |
| **BSE/NSE Filing PDFs** | Under SEBI LODR Regulation 30, companies must file con call transcripts | BSE XML API + NSE announcements endpoint |
| **TickerTape / Screener.in** | Selected large-cap transcripts | Web scrape |
| **Company IR websites** | Direct transcripts | Domain-specific Crawl4AI spiders |
| **Financial Modeling Prep (FMP) API** | Transcripts API — includes some NSE-listed | `financialmodelingprep.com/api/v3/earning_call_transcript` |
| **Finnhub** | Earnings call transcript API | `finnhub.io/api/v1/stock/transcripts` |

**Transcript Ingestion Pipeline (new `transcripts_server.py`):**

```python
class ConCallPipeline:
    
    async def ingest_transcript(self, symbol: str, quarter: str) -> ConCallDocument:
        # 1. Fetch raw transcript (PDF or text)
        raw = await self.fetch_from_bse_or_trendlyne(symbol, quarter)
        
        # 2. Parse into structured turns
        turns = self.parser.parse_speaker_turns(raw)  
        # Output: [{speaker: "Rajiv Bansal (CFO)", text: "..."}, ...]
        
        # 3. Classify turns
        prepared_remarks = [t for t in turns if t.section == "prepared"]
        qa_exchanges = [t for t in turns if t.section == "qa"]
        
        # 4. Extract key metrics mentioned
        metrics = self.metric_extractor.extract(turns)
        # Output: {revenue_guidance: "₹62,000 Cr", margin_guidance: "24-25%", ...}
        
        # 5. Run FinBERT sentiment on each management turn
        sentiment = self.finbert.analyze_batch([t.text for t in turns])
        
        # 6. Identify analyst concerns (from Q&A)
        concerns = self.qa_analyzer.top_concerns(qa_exchanges)
        # Output: ["margin pressure", "visa costs", "deal pipeline"]
        
        # 7. Store in Qdrant with structured metadata
        await self.vector_store.upsert(symbol, quarter, turns, metrics, sentiment)
        
        return ConCallDocument(turns, metrics, sentiment, concerns)
```

**Key LLM Prompt for Con Call Analysis:**
```
System: You are a sell-side financial analyst specializing in Indian equities.
Given this Q{N} FY{year} earnings call transcript for {company}:

Extract and structure:
1. Revenue/profit GUIDANCE provided by management (exact numbers, not paraphrases)
2. Key RISKS management acknowledged (be literal, not interpretive)  
3. KEY METRICS mentioned: margin%, EBITDA, capex, headcount, deal wins
4. Management TONE: confident/cautious/defensive (quote specific language)
5. Analyst CONCERNS from Q&A: what did analysts push back on?
6. Any CHANGES from last quarter's call (compare with prior guidance)
7. Forward-looking STATEMENTS flagged for tracking

Output JSON. Every claim must cite exact speaker + timestamp in transcript.
```

---

### 4.2 Annual Report Deep-Read Pipeline

Annual reports (ARs) for Indian companies are typically 150–400 page PDFs filed on BSE/NSE.

**Ingestion Strategy:**

```
Step 1: Fetch AR PDF
  Source: BSE filing API → /bseplus/StockReach/AdvanceSearch (filter: Annual Report)
  Tool: Your existing BSE announcements MCP + Crawl4AI

Step 2: Parse with MinerU (you already have mineru_transformer.py!)
  MinerU handles multi-column layouts, tables, and embedded charts — critical for ARs.
  Output: structured markdown with section labels

Step 3: Section Detection  
  Detect: MD&A | Directors' Report | Financial Statements | Notes to Accounts |
          Corporate Governance | Risk Factors | Segment Performance

Step 4: LLM Sectional Analysis (use Gemini 2.0 Flash — 1M context)
  For MD&A: "Summarize management's view on growth drivers and risks in 5 bullet points"
  For Financials: Extract all segment revenues, margins, capex into structured JSON
  For Notes: Flag related-party transactions, contingent liabilities, pledge details
  For Governance: Board changes, promoter holdings change, auditor qualifications

Step 5: Year-over-Year Comparison
  Store extracted JSON per year. Diff FY2024 vs FY2025:
  - Revenue CAGR by segment
  - Margin trend
  - Debt trend
  - Promoter holding change
  - R&D spend change (for pharma/tech)

Step 6: Embed into Qdrant with rich metadata
  {symbol, fiscal_year, section, content, extracted_metrics}
```

**New `annual_report_agent.py` to add to your specialist roster:**
```python
class AnnualReportAgent(BaseSubAgent):
    name = "annual_report"
    display = "Annual Report Analysis"
    priority = 32
    dependencies = ("financials",)
    
    async def execute(self, ctx: SessionContext) -> AgentTaskResult:
        # Retrieve latest 3 years of AR data from docs server
        ar_data = await self.mcp_docs.search_annual_reports(ctx.target, years=3)
        
        # Compare management guidance vs actual delivery
        guidance_accuracy = self.compute_guidance_accuracy(ar_data)
        
        # Flag: does management consistently over-promise?
        credibility_score = self.score_management_credibility(ar_data)
        
        return AgentTaskResult(
            findings=ar_data,
            claims=[...],
            credibility_score=credibility_score
        )
```

---

### 4.3 Daily Corporate Announcements Pipeline

**Current:** You have `nse_announcements.py` and `bse_announcements.py` in the news subsystem. This is the right foundation but needs significant enhancement.

**What needs to be added:**

```python
class CorporateAnnouncementClassifier:
    """
    Classifies and routes every BSE/NSE announcement to the right action.
    """
    
    HIGH_IMPACT = [
        "board_meeting_results",    # → Trigger deep research refresh
        "dividend_announcement",    # → Portfolio alert for holders
        "buyback",                  # → Valuation signal
        "merger_acquisition",       # → Immediate deep research
        "promoter_pledge_change",   # → Risk agent re-run
        "auditor_qualification",    # → Governance alert (critical)
        "management_change",        # → Research refresh
        "earnings_release",         # → Con call fetch trigger
        "credit_rating_change",     # → Risk alert
        "sebi_show_cause",          # → Red flag alert
    ]
    
    MEDIUM_IMPACT = [
        "investor_presentation",    # → Fetch and index
        "analyst_meet",             # → Transcript when available
        "capex_announcement",       # → Update DCF model
        "order_win",                # → Revenue guidance update
    ]
    
    async def process(self, announcement: Announcement):
        category = self.classify(announcement)
        
        if category in self.HIGH_IMPACT:
            # Immediately notify portfolio holders
            await self.portfolio_sentinel.alert_holders(announcement)
            # Queue a research refresh
            await self.research_queue.enqueue(
                target=announcement.symbol,
                reason=category,
                priority="high"
            )
        
        # Always: store + emit on portfolio event bus
        await self.event_bus.emit(AnnouncementEvent(announcement, category))
```

**Announcement sources to add:**
- NSE: `https://www.nseindia.com/companies-listing/corporate-filings-announcements` (you have this)
- BSE: `https://api.bseindia.com/BseIndiaAPI/api/AnnGetData/w` (you have this)
- **NEW: SEBI Orders/Enforcement actions** — `https://www.sebi.gov.in/enforcement/orders/` — for governance risk
- **NEW: RBI policy announcements** — for banking sector holdings macro overlay
- **NEW: Ministry of Finance / Finance Ministry press releases** — for sectoral policy changes

---

### 4.4 New Chat Capabilities Enabled by This Integration

Once the above pipelines are live, the chat model can answer:

```
User: "What did TCS management say about margins in the last earnings call?"
→ Transcript agent retrieves Q4FY26 con call
→ Quotes exact CFO statement: "We expect margins to be in the 24-25% range..."
→ Compares with Q3 guidance (23-24%) — shows improvement
→ Notes: 2 analysts questioned sustainability

User: "Has HDFC Bank been consistently hitting their guidance over the last 4 years?"
→ Annual report agent fetches FY2022-FY2026 ARs
→ Extracts all management guidance statements
→ Computes guidance accuracy score: 78% (usually beats by 3-5%)
→ Returns: "Management has a strong guidance delivery track record"

User: "Show me all announcements for companies in my portfolio from this week"
→ Portfolio sentinel + corporate announcement classifier
→ Returns prioritized digest: 2 dividends, 1 earnings release, 1 order win

User: "Any red flags in Zee Entertainment's annual report?"
→ AR deep-read: flags related-party transactions in Notes
→ Flags promoter pledge at 72% (critical threshold)
→ Flags auditor emphasis of matter on going concern
```

---

## 5. CHRONOS-2 DEEP RESEARCH & INTEGRATION BLUEPRINT

### 5.1 What Chronos-2 Is

Chronos-2 is a 120M-parameter, encoder-only time series foundation model for zero-shot forecasting. It supports univariate, multivariate, and covariate-informed tasks within a single architecture.

Chronos-2 achieves the best performance on fev-bench, GIFT-Eval, and Chronos Benchmark II amongst pretrained models. It offers zero-shot support for univariate, multivariate, and covariate-informed forecasting tasks.

The accuracy of Chronos-2 often exceeds statistical baseline models and task-specific deep learning models such as DeepAR and TemporalFusionTransformer.

**The key architectural innovation:** Chronos-2 uses two kinds of attention mechanisms that work together: time-attention that works along each time series independently, and group-attention that allows information to flow across related series. This enables covariate-informed forecasting — for example, feeding sector index as a covariate when forecasting a stock's revenue.

### 5.2 Why It Matters for ProspektLab Specifically

Your current `valuation.py` uses deterministic CAGR with no confidence intervals. This is the #1 accuracy gap. Chronos-2 gives you:

1. **P10/P50/P90 revenue corridors** — your DCF becomes a distribution
2. **Multi-series forecasting** — forecast Revenue + EBITDA + Cash Flow jointly (they co-evolve)
3. **Covariate support** — feed sector performance, macro indicators, or credit ratings as external drivers
4. **Zero-shot** — works immediately on Indian company financials without task-specific fine-tuning
5. **Quantile forecasts** — output "70% probability TCS revenue exceeds ₹2.5L Cr in FY27"

Research on using Chronos-2 for multivariate financial forecasting spans evaluation periods covering 2000–2025 with monthly rolling forecasts, demonstrating realistic deployment cadence and covering short-to-medium historical windows.

### 5.3 Integration Architecture

**New MCP Server: `forecasting_server.py` (Port 8008)**

```python
# requirements: pip install chronos-forecasting autogluon.timeseries torch
from chronos import BaseChronosPipeline
import torch

class Chronos2ForecastingServer:
    """
    Wraps Chronos-2 for financial metric forecasting.
    Deployed on AWS SageMaker Serverless Endpoint (no idle cost).
    """
    
    def __init__(self):
        # Use smallest model on CPU for cost efficiency
        self.pipeline = BaseChronosPipeline.from_pretrained(
            "amazon/chronos-2",
            device_map="cpu",
            torch_dtype=torch.float32,
        )
    
    async def forecast_financial_metric(
        self,
        symbol: str,
        metric: str,           # "revenue" | "ebitda" | "pat" | "eps"
        history_quarters: int = 20,
        forecast_quarters: int = 4,
        covariates: list = None  # e.g., [sector_index, nifty_pe]
    ) -> ForecastResult:
        
        # 1. Fetch historical quarterly data
        history = await self.fetch_quarterly_history(symbol, metric, history_quarters)
        
        # 2. Prepare input tensors
        context = torch.tensor(history, dtype=torch.float32)
        
        # 3. If covariates provided, use group/covariate mode
        if covariates:
            # Group = [target_series, covariate_1, covariate_2, ...]
            group = [context] + [torch.tensor(c) for c in covariates]
        else:
            group = context
        
        # 4. Run Chronos-2 inference
        quantile_levels = [0.1, 0.25, 0.5, 0.75, 0.9]
        forecast = self.pipeline.predict_quantiles(
            group,
            prediction_length=forecast_quarters,
            quantile_levels=quantile_levels,
        )
        
        # 5. Return structured result
        return ForecastResult(
            symbol=symbol,
            metric=metric,
            p10=forecast[0.1].tolist(),   # Bear case
            p50=forecast[0.5].tolist(),   # Base case
            p90=forecast[0.9].tolist(),   # Bull case
            quarters_ahead=forecast_quarters,
            confidence=self.compute_confidence(history, forecast)
        )
```

**Enhanced `valuation.py` with Chronos-2:**

```python
class ValuationAgent(BaseSubAgent):
    
    async def execute(self, ctx: SessionContext) -> AgentTaskResult:
        # Old: single CAGR extrapolation
        # revenue_forecast = self.cagr_extrapolate(historical_revenue, years=5)
        
        # New: Chronos-2 probabilistic forecast
        revenue_forecast = await self.mcp_forecasting.forecast_financial_metric(
            symbol=ctx.target,
            metric="revenue",
            covariates=[ctx.sector_index, ctx.nifty_pe_ratio]
        )
        
        ebitda_forecast = await self.mcp_forecasting.forecast_financial_metric(
            symbol=ctx.target,
            metric="ebitda"
        )
        
        # DCF now runs on P10, P50, P90 revenue scenarios
        dcf_bear = self.dcf_engine.compute(revenue_forecast.p10, ebitda_forecast.p10)
        dcf_base = self.dcf_engine.compute(revenue_forecast.p50, ebitda_forecast.p50)
        dcf_bull = self.dcf_engine.compute(revenue_forecast.p90, ebitda_forecast.p90)
        
        return AgentTaskResult(
            findings={
                "fair_value_range": f"₹{dcf_bear:.0f} – ₹{dcf_bull:.0f}",
                "base_case": f"₹{dcf_base:.0f}",
                "confidence": revenue_forecast.confidence,
                "revenue_p50_next_year": revenue_forecast.p50[3]  # 4th quarter
            }
        )
```

### 5.4 Deployment on AWS (Your Existing Infrastructure)

Chronos-2 can be deployed on Amazon SageMaker with real-time GPU and CPU inference, serverless endpoints (run on demand, no idle costs), and batch transform for large-scale forecasting.

Since you're already on AWS ECS/Fargate:

```yaml
# Option 1: SageMaker Serverless Endpoint (recommended — no idle cost)
# In forecasting_server.py startup:
import boto3
sm_client = boto3.client('sagemaker')

# Deploy Chronos-2 as serverless endpoint
# ~$0.0000007 per inference token
# Cold start: ~3-5 seconds (acceptable for deep research, not quick chat)

# Option 2: Run on ECS Fargate task directly (CPU only)
# Add to Dockerfile:
# RUN pip install chronos-forecasting torch --index-url https://download.pytorch.org/whl/cpu
# 120M param model on CPU: ~2-4 seconds per forecast — acceptable
```

**Recommended:** Run Chronos-2 inference directly in your `quant_server.py` Fargate task (CPU mode). Chronos-2 supports both GPU and CPU inference, so no GPU instance needed. A `t3.medium` Fargate task handles it fine.

### 5.5 What Chronos-2 Enables in the Chat Model

```
User: "What's TCS likely to earn in FY27?"
→ Chronos-2 runs on 20 quarters of TCS revenue/PAT history
→ Returns: "Base case PAT: ₹48,500 Cr ± ₹3,200 Cr (P25–P75)"
→ Combines with sector PE → "Implied fair value range: ₹4,100–₹4,700"
→ Disclaimer: "This is a statistical model forecast, not a guarantee."

User: "Model TCS revenue under a US slowdown scenario"
→ Feed US IT spending index as covariate (historical correlation known)
→ Chronos-2 covariate mode: revenue forecast shifts with macro input
→ "Under a 10% US IT budget cut scenario: TCS revenue growth falls to 4% (base: 9%)"
```

### 5.6 Important Caveats for Financial Use

Be transparent in your UI about these:
- Chronos-2 is a **statistical model**, not a financial analyst. It sees patterns in numbers, not business fundamentals.
- Stock prices have very low signal-to-noise; use Chronos-2 for **fundamental metrics** (revenue, EBITDA, EPS), not for price prediction.
- Always combine Chronos-2 output with your existing DCF/qualitative analysis — never standalone.
- Add a clear SEBI-compliant disclaimer on all forecast outputs.

---

## 6. OTHER MAJOR MODELS & TOOLS TO INTEGRATE

### 6.1 FinBERT — For Management Tone Analysis (HIGH PRIORITY)

FinBERT is specifically fine-tuned for sentiment analysis of Indian stock market news, trained on the foundation of FinBERT (a BERT model pre-trained on extensive financial communication text), focusing on enhancing sentiment analysis within the context of the Indian financial landscape.

**Where to use it in your pipeline:**

| Use Case | Current Approach | With FinBERT |
|---|---|---|
| Con call tone analysis | None | Sentence-level tone: management confidence score |
| News sentiment | Reddit + HN only | Every news article gets a FinBERT sentiment score |
| Annual report tone shift | None | MD&A tone YoY comparison (management getting more cautious?) |
| SEBI filing language | None | Detect defensive language patterns |

Incorporating sentiment analysis from FinBERT significantly enhances a model's ability to anticipate market fluctuations, outperforming standard BERT, standalone LSTM, and traditional ARIMA models when predicting stock movement.

**Integration (add to `community.py` and new `transcripts_server.py`):**
```python
from transformers import pipeline

# Use India-specific fine-tuned version
finbert_india = pipeline(
    "sentiment-analysis", 
    model="kdave/FineTuned_Finbert",  # India-specific
    tokenizer="kdave/FineTuned_Finbert"
)

# In ConCallAnalyzer:
def analyze_management_tone(self, transcript_turns: list[Turn]) -> ToneReport:
    mgmt_statements = [t.text for t in transcript_turns if t.is_management]
    sentiments = finbert_india(mgmt_statements, truncation=True, max_length=512)
    
    tone_score = sum(1 if s["label"] == "positive" else -1 
                    for s in sentiments) / len(sentiments)
    
    return ToneReport(
        overall_tone=tone_score,        # -1 (very cautious) to +1 (very confident)
        confident_statements=[...],
        defensive_statements=[...],
        guidance_language=[...]
    )
```

---

### 6.2 Trendlyne — Best Source for Indian Earnings Transcripts

Trendlyne provides conference call transcripts for NSE and BSE stocks, including company performance, financials, and capex plans, with transcripts filed directly from earnings conference calls with investors and analysts.

`trendlyne.com/earnings-transcripts/` is the single best source for Indian con call transcripts. Add a dedicated Crawl4AI spider for this domain in your `crawl4ai_sites.py`.

---

### 6.3 Financial Modeling Prep (FMP) API — Transcripts for MNCs Listed in India

FMP provides access to full transcripts of company earnings calls via the Earnings Transcript API, along with earnings call dates by symbol and a complete list of available transcript symbols.

For companies like Infosys, Wipro, HCL that dual-list on NYSE/NSE and file with SEC, FMP has full transcript coverage. Add `FINAGENT_FMP_API_KEY` to your env vars.

---

### 6.4 AutoGluon TimesSeries — Ensemble Forecasting Wrapper

AutoGluon provides a clean interface to train and evaluate Chronos-2 with just a few lines of code, with reasonable defaults that performed well in large-scale benchmarking.

Use AutoGluon as a wrapper around Chronos-2 to automatically benchmark it against your existing deterministic models. If AutoGluon's ensemble (Chronos-2 + ETS + ARIMA) outperforms standalone Chronos-2 on backtests of Indian financial data, use the ensemble.

---

### 6.5 GraphRAG / Knowledge Graph for Company Relationships

Your `retrieval/graph_index.py` exists but the architecture doc doesn't describe what's in it. This is an underutilized component.

**What to build:** A company knowledge graph where:
- Nodes: Companies, Promoters, Directors, Subsidiaries, JVs, Competitors, Customers, Suppliers
- Edges: ownership %, board membership, supply chain relationship, past M&A

**Use case:** "Analyse the governance risk at Adani Ports" → graph traversal reveals: promoter holding % at parent, cross-holdings with group entities, FII exposure change. This is something no existing Indian retail tool provides.

**Tools:** 
- `networkx` for in-memory graphs (you likely have it)
- Extend `graph_index.py` with entity relationships from SEBI filings, MCA data

---

### 6.6 Whisper — For Audio Earnings Call Transcription

Many Indian companies file audio recordings of earnings calls but not text transcripts. OpenAI's Whisper (open-source, self-hostable) can transcribe these.

```python
# In transcripts_server.py
import whisper

class AudioTranscriber:
    def __init__(self):
        self.model = whisper.load_model("medium")  # ~1.5GB, good accuracy
    
    async def transcribe_earnings_call(self, audio_url: str) -> str:
        audio_path = await self.download(audio_url)
        result = self.model.transcribe(audio_path, language="en")
        return result["text"]
```

The audio recordings are publicly available on company IR websites and BSE filings. This unlocks a huge corpus of unstructured intelligence that your competitors don't have.

---

### 6.7 MCA21 (Ministry of Corporate Affairs) Integration

Currently absent from your architecture. MCA21 is mandatory for:
- **Promoter shareholding changes** (beyond NSE data)
- **Director network mapping** (shared directors across companies)
- **Related party transactions** detection
- **Pledge/encumbrance details** on promoter shares

API: `https://www.mca.gov.in/content/mca/global/en/data-and-reports/company-master-data.html`

---

## 7. OBSESSION-DRIVING UX ENHANCEMENTS

### 7.1 "What Changed Today for My Portfolio"

The single highest-retention feature for daily active users. Every morning at 8 AM IST:

```
🔔 Good morning! Here's what changed for your portfolio overnight:

📊 HDFC Bank: Q4 results out. Net profit ₹16,512 Cr (+18% YoY). 
   Management guided 16-17% loan growth. Margin stable at 4.3%.
   → 2 of 3 analyst concerns from last quarter resolved ✓

📢 TCS: Board meeting scheduled for May 30. Likely dividend announcement.
   Based on last 4 years: ~₹30-35 dividend expected.

⚠️ Zee Entertainment: Promoter pledge increased to 72% (was 68%).
   RED FLAG — monitor closely.

📈 Your portfolio: +0.8% today vs Nifty +0.3%. 
   Outperformers: HDFC Bank (+2.1%), TCS (+0.9%)
```

This requires: Corporate announcement classifier (Section 4.3) + Con call pipeline (Section 4.1) + Portfolio sentinel (you have this base).

### 7.2 "Ask Your Portfolio" Feature

```
User: "Should I add more TCS or switch to Infosys?"
→ Fetches last 2 con calls for both
→ Compares management guidance accuracy scores
→ Runs Chronos-2 on revenue forecasts for both
→ Shows valuation gap: "TCS at 28x PE vs Infosys 22x — Infosys 21% cheaper on EV/EBITDA"
→ Considers user's current holding cost: "You bought TCS at ₹3,200, now ₹3,950 — 23% gain"
```

### 7.3 Earnings Surprise Tracker

After every quarterly result: compare actual vs Chronos-2/consensus estimate. Track which companies consistently beat. Surface this in portfolio: "HDFC Bank has beaten estimates 7 of last 8 quarters (+4% avg surprise)."

### 7.4 Chat Memory for Financial Context

**Current:** `chat_memory.py` stores conversation history. But it doesn't store financial facts discussed in prior sessions.

**Needed:** When a user asks "Is TCS still a buy?" and you ran a full deep research 3 weeks ago, the system should recall: "3 weeks ago we found fair value ₹4,200–4,800. Current price ₹3,950. Valuation has not significantly changed. No material announcements since." Instead of re-running the full 8-phase pipeline.

Store the research memo summary in `memory/store.py` with TTL of 7-14 days per company. Cache hit = instant answer, no API calls.

---

## 8. PRIORITY EXECUTION ROADMAP

### Phase 1 — Foundation Fixes (Weeks 1–3) 🔴

| Item | Effort | Impact |
|---|---|---|
| Migrate SQLite → Supabase Postgres (sessions, memory, portfolio) | 3 days | Enables horizontal scaling |
| Add Redis caching for NSE/Yahoo quotes | 1 day | 10x faster repeat queries |
| Add LLM Router (OpenAI + Anthropic Claude fallback) | 1 day | Eliminates single point of failure |
| Corporate Announcement Classifier | 3 days | Foundation for all alert features |
| Add streaming phase summaries to SSE | 2 days | Biggest UX win, drives retention |

### Phase 2 — Document Intelligence (Weeks 4–7) 🟠

| Item | Effort | Impact |
|---|---|---|
| Con Call Transcript Pipeline (Trendlyne + BSE scraping) | 5 days | Enables con call queries in chat |
| FinBERT management tone scoring | 2 days | Adds qualitative depth to research |
| Annual Report ingestion with MinerU + sectional analysis | 5 days | Enables "what did management guide?" |
| New AnnualReport specialist agent | 2 days | Integrates into 8-phase pipeline |
| Whisper audio transcription for missing transcripts | 2 days | Expands transcript corpus |

### Phase 3 — ML Forecasting (Weeks 8–11) 🟡

| Item | Effort | Impact |
|---|---|---|
| Chronos-2 forecasting_server.py (Port 8008) | 3 days | Probabilistic revenue/EBITDA forecasts |
| Upgrade valuation.py to P10/P50/P90 DCF | 2 days | Huge accuracy improvement |
| Earnings surprise tracker | 2 days | Daily engagement driver |
| AutoGluon ensemble backtesting on Indian data | 3 days | Validates model accuracy before launch |

### Phase 4 — Portfolio Intelligence & Obsession Loop (Weeks 12–16) 🟢

| Item | Effort | Impact |
|---|---|---|
| Daily portfolio digest (8AM push) | 3 days | Daily active user driver |
| "Ask Your Portfolio" chat mode | 4 days | Killer feature, viral potential |
| Earnings calendar overlay on portfolio | 2 days | High-value, low-effort |
| Company knowledge graph (GraphRAG) | 5 days | Unique competitive moat |
| Per-holding confidence badge display | 1 day | Trust driver |

---

## 9. KARPATHY AUTORESEARCH PATTERN — IMPACT ANALYSIS & INTEGRATION BLUEPRINT

### 9.1 What autoresearch Actually Is (Precisely)

Before discussing impact, it's critical to be precise about what this repo is and is not, because it is frequently misread.

autoresearch is NOT a general-purpose AI research framework, a data pipeline tool, or an application architecture. It is a pattern for autonomous iterative self-improvement of any measurable system. The repo itself is specifically a single-GPU LLM training experiment runner — Karpathy's nanochat training loop — but the core pattern is entirely domain-agnostic.

The pattern has exactly four components. First, one mutable file — the only file the agent is allowed to modify. In the original repo this is train.py (the model + training loop). Second, one fixed metric — a single number that defines what "better" means. In the original this is val_bpb (validation bits per byte), lower is better. Third, a fixed time budget per experiment — 5 minutes per run, giving ~12 experiments per hour, ~100 overnight. Fourth, a program.md file — a plain English instruction file written by the human that tells the agent what to explore, what constraints to respect, and what hypotheses to test. The agent reads this, forms a hypothesis, modifies the mutable file, runs the experiment, reads the metric, keeps or reverts via git, and loops forever without asking the human for permission.

The key philosophical insight from Karpathy is that the human's job shifts from doing the work to writing the research direction. You don't optimize train.py — you optimize program.md. You're programming the programmer.

The second key insight, identified by several practitioners applying this beyond ML, is this: autoresearch works on anything you can score. It is not limited to LLM training. One file to modify. One metric. Fixed time budget. Keep or discard. Loop forever. This generalized pattern is what matters for ProspektLab.

### 9.2 Does autoresearch Directly Apply to ProspektLab?

The direct answer: the repo's code cannot be imported into ProspektLab at all. train.py is an LLM training script for a GPT model on text data. prepare.py is a BPE tokenizer and data loader for that same training task. None of this code touches financial data, agent orchestration, or any component in your architecture.

However, the pattern — the autonomous iterative improvement loop with a fixed metric — applies powerfully to at least four specific subsystems in ProspektLab. Each of these is a case where you currently make manual decisions that could instead be discovered autonomously overnight while you sleep, exactly as Karpathy described.

### 9.3 Integration Point 1 — Chronos-2 Fine-Tuning Hyperparameter Search

This is the single highest-impact application of the autoresearch pattern in your project, and it fits perfectly because you just discussed fine-tuning Chronos-2.

The problem with manual fine-tuning is that you have at minimum 6 hyperparameters to tune: learning rate, context length in quarters, prediction horizon in quarters, batch size, number of training steps, and covariate selection strategy. Manually testing combinations is what Karpathy was doing before autoresearch — 8-10 experiments per working day. With the autoresearch pattern applied to Chronos-2 fine-tuning, you get 100 hyperparameter combinations tested overnight.

How to implement this for your project:

Create a new directory called `autoresearch/chronos_finetune/`. Inside it, create three files mirroring the pattern exactly. The first file, `prepare_india.py` (fixed, never modified), handles the one-time work: downloads 15 years of NSE quarterly financial data for 500 companies, normalizes it into a chronos-compatible time series dataset, creates train/val splits holding out the last 8 quarters for evaluation, and defines the single metric function — MAPE on the validation set. The second file, `finetune_config.py` (the mutable file the agent modifies), contains every tunable aspect of the fine-tuning run: learning rate, context_length, prediction_length, batch_size, training_steps, whether to include covariates and which ones, the learning rate schedule, and weight decay. The agent modifies only this file. The third file, `program_chronos.md` (the human-written instruction file), tells the agent what you want: minimize MAPE on Indian quarterly financial data across NSE 500, prefer configurations that generalize across sectors rather than overfitting to IT, try increasing context length first since Indian companies have seasonal patterns, test with and without macro covariates such as USD/INR and Nifty PE. Set the time budget to 15 minutes per experiment rather than 5, since Chronos-2 fine-tuning on a GPU needs more time to converge. You get approximately 4 experiments per hour, roughly 30 to 40 experiments overnight on an A10G instance.

This gives you the optimally fine-tuned Chronos-2 for Indian financial data without a single manual hyperparameter decision. The only human effort is writing program_chronos.md — describing the direction, not doing the work.

The fixed metric is MAPE on held-out quarterly data. Lower is better. Binary keep-or-revert decision after each run. This is an exact port of the autoresearch pattern into your domain.

### 9.4 Integration Point 2 — Specialist Agent Prompt Optimization

This is the second highest-impact application, and it connects directly to your existing `prompts/finagent_system.txt` and `prompt_builder.py`.

Your 10 specialist agents — valuation, financials, accounting, risk, competitor, governance, macro, technical, news, community — each produce findings that feed into the final research memo. The quality of those findings is almost entirely determined by the prompts. Currently, you wrote those prompts manually and they stay fixed until you manually edit them again. This is exactly the situation autoresearch was built to escape.

The autoresearch pattern applied here: create `autoresearch/agent_prompts/` with a mutable file being the prompt file for one agent at a time, a fixed evaluation harness that runs that agent on 50 known test companies and scores its output against a ground truth (you can build this ground truth from Screener.in data for fundamental metrics), and a program.md telling the agent to explore different prompt structures, levels of detail, explicit vs implicit instructions, and chain-of-thought vs direct output formats.

The metric for prompt quality can come from your existing `output/confidence_scorer.py` and `analysis/quality.py` — you already have a quality scoring system (0-100 scale). Use that. The agent modifies the prompt file, the evaluation harness runs the agent on 50 test companies, the quality score is computed, keep or revert based on whether it improved.

Start with the valuation agent's prompt since that is the most critical for user trust. Let it run overnight. You will likely discover prompt structures that significantly outperform your manually crafted ones. Then systematically work through each specialist agent.

### 9.5 Integration Point 3 — Annual Report Chunking Strategy Optimization

When you build the annual report ingestion pipeline described in Section 4, you will face a hard decision about chunking strategy: how large should each chunk be, how much overlap, should you use fixed-size chunks or section-boundary chunks, how many top-k chunks to retrieve. These decisions directly determine the quality of answers to questions like "what did management say about margin pressure in TCS's FY2025 AR?"

This is another perfect autoresearch target. The mutable file is `chunking_config.py` — chunk size, overlap, section boundary detection rules, top-k retrieval parameter, embedding model choice. The metric is retrieval precision at k, measured by asking 100 known questions against known annual reports and checking whether the correct passage is in the top-k retrieved chunks. The program.md tells the agent to try larger chunks for financial statements sections and smaller chunks for Notes to Accounts, to experiment with section-boundary detection rules for Indian Ind-AS reporting format, and to test whether adding the section header as a prefix to each chunk improves retrieval.

This is a problem that is genuinely hard to solve by manual intuition because the interactions between chunk size, overlap, and retrieval quality are non-linear. An overnight autoresearch run will find configurations you would never find manually.

### 9.6 Integration Point 4 — Research Pipeline Configuration Optimization

Your 8-phase pipeline in `run_agent.py` has multiple configurable parameters: number of breadth survey passes, pass depth, max wall time, which specialist agents run in which wave, and the quality threshold for proceeding to synthesis (currently 75.0). These are currently hardcoded or set by manual judgment.

Use autoresearch to find the optimal configuration. The mutable file is `pipeline_config.py`. The metric is the final research quality score from `analysis/quality.py`, normalized by wall clock time (quality per second — you want the best quality in the least time). The program.md tells the agent to explore whether reducing pass depth from 120 to 60 costs quality, whether reordering agent waves changes output quality, and whether the 75.0 quality threshold is the right gate for synthesis or whether a higher threshold produces noticeably better memos.

### 9.7 What You Do NOT Take from autoresearch

Be explicit about this to avoid over-engineering. You do not take train.py. You do not take prepare.py. You do not take the GPT model, the Muon optimizer, the BPE tokenizer, or the text training loop. None of those have any relevance to ProspektLab. You take only the loop pattern: one mutable file, one metric, fixed time budget, keep-or-revert, loop forever. That pattern costs roughly one day of engineering to adapt to each target subsystem.

Also do not apply this pattern to everything. It only adds value when you have a single measurable metric, a single clearly bounded thing to modify, and more than 20 experiments worth running. For your user-facing chat flows, your authentication system, and your data ingestion pipelines, the autoresearch pattern is overkill — those are better improved by direct engineering judgment.

### 9.8 Updated Execution Roadmap for autoresearch Integration

Add these to your existing Phase roadmap:

Phase 1 addition (Week 2): Set up autoresearch framework skeleton — the three-file pattern, the git keep/revert loop, the results logging. This is one day of work and creates the reusable infrastructure for all subsequent applications.

Phase 3 addition (Week 8, alongside Chronos-2 implementation): Immediately apply autoresearch to Chronos-2 fine-tuning hyperparameter search. Write program_chronos.md, kick off the overnight run on the AWS A10G SageMaker instance you'll already be provisioning for Chronos-2. The output is an optimally configured fine-tuning setup at essentially zero additional engineering cost.

Phase 2 addition (Week 6, alongside annual report pipeline): Apply autoresearch to chunking strategy optimization the week after you build the AR ingestion pipeline. You need a working pipeline before you can run the optimization, so it's a natural week-two follow-up to the ingestion work.

Ongoing (starting Phase 4): Apply autoresearch to specialist agent prompts one agent per week. Start with valuation, then risk, then financials. Each overnight run either improves the prompt or confirms the current one is already near-optimal. Either result is valuable.

---

## SUMMARY: TOP 5 THINGS TO BUILD FIRST

1. **Corporate Announcement Classifier** — the foundation that unlocks alerts, portfolio digest, research refresh triggers. Everything else builds on top of it.
2. **Con Call Transcript Pipeline** — this is the #1 missing feature for users who care about fundamentals. Trendlyne + BSE XML + FinBERT sentiment = complete solution.
3. **Chronos-2 in valuation.py** — replace CAGR with probabilistic P10/P50/P90. This directly improves the quality and trustworthiness of every research report.
4. **Streaming Phase Summaries** — show partial results as agents complete. This changes the UX from "waiting" to "watching a live analyst work". Users stay.
5. **Daily Portfolio Digest** — one push notification per day combining all of the above. This is the habit loop that drives obsession.

---

*ProspektLab / ORACLE FIOS | Architecture Analysis | May 2026*

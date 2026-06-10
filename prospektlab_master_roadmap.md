# ProspektLab: Master Roadmap
### Complete Architecture Audit + Moat Build Plan + Research Integration + Execution Sequence

> This document is the synthesis of every strategic conversation, architecture review, research paper analysis, IKG guide, and portfolio UI research conducted. It is the single source of truth for what to build next, what to fix, what to throw away, and in what order to do it.

---

## Part 1: Architecture Audit — Keep, Optimize, Delete

Before adding anything, you need to know what you have, what works, what needs fixing, and what is actively hurting you.

### What to KEEP Exactly As-Is

**The 10-Specialist Agent Wave Orchestration**
This is your strongest differentiator against every Indian retail tool. Trendlyne, Screener, Tijori — none of them have orchestrated multi-agent research. Do not change the wave architecture. The agents are correct. The specializations are correct. Only the inter-agent communication needs upgrading.

**The Deterministic Valuation Engine**
DCF, Piotroski F-Score, Altman Z-Score, Graham Number, DuPont — all computed in Python, never by an LLM. This is architecturally correct and is your primary defense against the hallucination problem that will kill your competitors. Never move numerical computations into the LLM layer regardless of how confident a model seems.

**India-First Entity Resolution**
The `.NS`/`.BO` suffix handling, INR crore/lakh formatting, Screener.in/Moneycontrol domain preferences, shareholding pattern fetching — this is real India localization work. Keep every line of it.

**eCAS / CAS Portfolio Parser**
CAMS and KFintech format parsing is non-trivial. No other tool does this. It is a distribution wedge and a switching cost. Keep it and expand it.

**SessionBus SSE Architecture**
The async streaming with JSONL event replay is correct for long-running research jobs. It handles AWS API Gateway timeouts gracefully and gives users real-time progress. Keep the architecture. Add interruption points to it (see Optimize section).

**MCP Server Structure**
Discovery Server (:8003) + Quant Server (:8005) is the right separation of concerns. The IKG will be a third MCP server. The earnings transcript processor will be a fourth. Keep building MCP servers for new data capabilities rather than stuffing everything into the main agent loop.

**FastAPI + LangGraph + React Stack**
Correct choices. Do not rewrite anything. LangGraph has native support for every pattern you need (state machines, checkpointing, interruption points, multi-agent). The frontend component library (DonutChart, TreemapChart, AreaChart, RadarChart, MetricCard, Sparkline) is all reusable. Build on top of what exists.

---

### What to OPTIMIZE

**Memory System: SQLite → Letta (MemGPT) Architecture**

Current: Facts are written to `memory.sqlite3` during sessions. A flat key-value store. No hierarchy, no paging, no background consolidation. Scales poorly above a few hundred facts per user.

Required change: Replace the flat SQLite memory with a three-tier Letta architecture:
- Tier 1 — Core Memory (always in context): User's portfolio companies, active research mandates, user preferences
- Tier 2 — Recall Storage (fast retrieval): Verified financial facts from all sessions, searchable by company CIN + fact type
- Tier 3 — Archival Storage (dreaming layer target): Consolidated patterns, management credibility records, historical financial snapshots

Install: `pip install letta`. Migrate existing SQLite facts into Letta's memory blocks as a one-time migration script. The API interface stays the same — agents call `memory.search()` and `memory.append()` — but the underlying architecture now supports paging, hierarchical storage, and the Dreaming Layer background worker.

**System Prompts: Generic → Agent-Specific Context Engineering**

Current: Each agent receives approximately the same context structure. System prompt defines role, retrieved documents fill the rest.

Required change: Apply Karpathy's Context Engineering discipline. Each agent's context window should be individually curated to contain only what that agent needs:

- Governance Agent: IKG subgraph (ownership chain, director network, enforcement flags), pledge trend history from dreaming layer, India-specific governance failure patterns from SPL strategy scratchpad. Nothing else.
- Valuation Agent: Normalized financial statements from deterministic engine, comparable company multiples, India cost of capital parameters, DCF assumption history from dreaming layer. Nothing else.
- Risk Agent: Beta/volatility data, sector cyclicality scores, promoter pledge exposure, credit rating of debt instruments in portfolio. Nothing else.
- News Agent: Last 90 days of verified news items, management commentary extracts from dreaming layer, regulatory event flags. Nothing else.
- Synthesis Agent: All other agents' verified outputs only. No raw retrieval data. No redundant source citations.

The measurement framework: track which portion of each agent's context was actually cited in its output. Content never cited is noise. Remove it. Measure quality before and after removal. This is ongoing work, not a one-time task.

**Synthesis Template: Remove Verdict Language**

Current: Section 8 of your synthesis is "Verdict / Investment Thesis" with "Bull/Bear/Base scenarios, conviction level, catalysts." Your sample output contains "Verdict: Buy with 15% margin of safety." This is your most urgent architectural risk. Not a future risk. A current production risk under SEBI Research Analyst Regulations 2014.

Required change: Replace the verdict section entirely with Scenario Implication Matrices:

```
Old (DELETE):
"Verdict: Buy with 15% margin of safety. Conviction: High. Target: ₹3,200."

New (REPLACE WITH):
"Scenario Analysis:
- Base case (margin stable at 18.2%, revenue growth 12%): 
  DCF model implies ₹2,900-3,100 range under these assumptions.
- Upside scenario (margin expands to 19.5%, growth accelerates to 15%): 
  Model implies ₹3,200-3,400 under these assumptions.
- Downside scenario (margin compresses to 16%, growth decelerates to 8%): 
  Model implies ₹2,400-2,600 under these assumptions.
The final assessment of which scenario is most probable is the user's judgement call."
```

Every synthesis agent prompt must be rewritten to produce conditional mathematical statements rather than directional recommendations. This is a 1-2 week text change in your agent prompts. Do it this week.

**intent_router.py: Add Pre-Flight Gate**

Current: Queries go from user → intent classification → research launch. No pause for ambiguous queries.

Required change: Add a confidence threshold. If entity resolution confidence is below 0.80 (multiple possible companies for the same name) OR if query type is ambiguous (could be portfolio analytics OR research), pause and present a one-tap clarification to the user before launching the agent loop. This costs 0.5-1 second and saves 15-45 seconds of wrong-direction research.

**Deep Research Loop: Add Interruption Points**

Current: Research runs start-to-finish without user interaction.

Required change: LangGraph natively supports `interrupt()` calls at node boundaries. Add two interruption points:
1. After Blueprint Specification is generated and before agents launch — show spec to user, one-tap to approve or modify
2. When any agent discovers a materially unexpected finding (SEBI action not in recent coverage, pledge above 50%, auditor resignation) — surface immediately, ask if user wants to reprioritize remaining research around this finding

**Data Sources: Supplement yfinance**

Current: yfinance as primary price and financial data source. 15-minute delayed prices. Known data gaps for smaller companies.

Required change: Do not remove yfinance. Add NSE/BSE direct download as a parallel source. For daily batch updates: use BSE's bulk download for EOD prices (free, official). For real-time: continue with yfinance for now, plan NSE licensed feed when first institutional client commits. For financial data: Screener.in API (free tier) as cross-validation source. Three-source validation for any financial fact written to Letta memory.

---

### What to DELETE

These items are in your current architecture and need to be removed or replaced. Some are compliance risks. Some are architectural dead ends. Some are just noise.

**DELETE: All Buy / Sell / Hold / Strong Buy / Accumulate language from every agent prompt and synthesis template.** Replace with scenario conditional framing everywhere. Do this before scaling user acquisition.

**DELETE: Conviction level labels** ("High Conviction," "Strong Conviction," "Moderate Conviction"). These are advisory language under SEBI's reading. Replace with model confidence intervals expressed as probability ranges under stated assumptions.

**DELETE: "Target Price: ₹X" outputs from any agent or synthesis.** Replace with "Fair value range under [stated assumptions]: ₹X-Y."

**DELETE: "We recommend" and "Investors should" language from every prompt.** Replace with "The data suggests" and "Under these assumptions, the model implies."

**DELETE: The conversational filler in system prompts** ("You are a helpful financial analyst who aims to provide balanced perspectives..."). Replace every agent's system prompt with dense, specific, financial-context instructions. No personality framing. No helpfulness theater. Pure financial context and task specification.

**DELETE: Reddit / StockTwits as primary sentiment sources.** Keep them as supplementary. Pump-and-dump signals from social media are already handled by your social signal detection agent. But social sentiment from these platforms is too noisy to be a primary input. Move them to a low-weight supplementary role.

**DELETE: SQLite single-file memory architecture** once Letta migration is complete. Do not run both simultaneously for more than a 2-week migration window.

---

## Part 2: The Moat Stack — Ordered by Impact and Timeline

These are the things that make ProspektLab genuinely difficult to replicate. Ordered by how much moat they create. Build them in this order.

### Moat Tier 1: Creates Permanent Defensibility (Build These First)

**1. Indian Corporate Knowledge Graph (IKG)**
Why it is Tier 1: It is a data asset. Once built, a competitor needs the same 18-24 months to replicate it. The data compounds (each new company adds more relationship edges). User research sessions enrich it automatically. It is the single element that converts ProspektLab from "sophisticated AI wrapper on public data" to "proprietary intelligence platform."

**2. Dreaming Layer (Per-User Memory Compounding)**
Why it is Tier 1: It creates switching costs that increase with tenure. A user who has been on ProspektLab for 18 months has 18 months of curated company-specific memory that no competitor can access. The switching cost is the loss of that memory. This cannot be bought or rushed — it requires time and active users.

**3. System Prompt Learning Strategy Scratchpad**
Why it is Tier 1: The system gets better at Indian financial research automatically, without human intervention, across every session. After 12 months it will outperform a freshly deployed version of itself running the same base model. Competitors who launch later start from zero.

### Moat Tier 2: Creates Institutional Lock-In (Build Second)

**4. SEBI Compliance Infrastructure**
The Five-Year Compliance Ledger, the Deterministic Output Scrubber, the Scenario Implication Matrix framing — these make ProspektLab the only platform that institutional buyers (AMCs, brokerages, PMS firms) can procure without legal review of every output. This is a procurement gate that competitors without this infrastructure cannot pass.

**5. Per-Company Memory Pre-Loading**
When research on Infosys starts with 18 months of curated context already in the context window, the research quality is materially better than any competitor starting from zero. This becomes visible to users and creates a "this platform just knows more" perception that is accurate and differentiating.

**6. Multi-Tenancy and Institutional Workflows**
Team workspaces, role-based access, shared research notes, audit trails — these are table stakes for enterprise sales. They are not exciting features. But without them, you cannot sell to anyone above a sophisticated retail user.

### Moat Tier 3: Creates Quality Perception (Build Third)

**7. GraphRAG on Document Corpus**
When IKG is populated, GraphRAG synthesizes patterns across thousands of annual reports and SEBI orders automatically, producing insights that no agent running against a flat vector store can match.

**8. Cross-Agent Adversarial Critique**
Forces higher-quality outputs by having agents challenge each other's assumptions. Visible to users as a "Research Quality Score." Differentiates from all tools that produce a single agent's unchallenged analysis.

**9. Blueprint Specification Architecture**
Makes research feel professional rather than chatbot-like. Creates an audit trail that institutional clients value.

---

## Part 3: Phase-by-Phase Roadmap

### Phase 0: Right Now (Next 2 Weeks) — Stop the Bleeding

These are not features. These are fixes to things that are wrong today.

**Week 1:**
- Rewrite synthesis template: Remove all verdict/buy/sell/conviction language. Replace with Scenario Implication Matrices. This is the most urgent item in this entire document. If you scale user acquisition with the current synthesis template and SEBI notices you, the company could face enforcement action.
- Add Output Scrubber to outbound pipeline: A Python function that scans every response before it reaches the frontend, flags advisory language, replaces or strips it. Start with a keyword list; evolve to semantic checking later. One day of engineering work.
- Apply for MCA Data Lake access: Go to mca.gov.in/data-lake today. Fill the application. Takes 20 minutes. Returns structured MCA data access in 4-6 weeks.
- Apply for SEBI Innovation Sandbox: Same urgency. sebi.gov.in innovation sandbox application. Both applications cost nothing and take 20 minutes each.

**Week 2:**
- Enable Prompt Caching on all OpenAI/Anthropic API calls: Add `cache_control` parameter to your API calls for the pre-loaded memory context portion. Immediate 30-50% cost reduction on cached content. One day of engineering work.
- Switch all IKG extraction to JSON structured outputs: Any place where you call an LLM to extract entities from documents, add a `response_format: {type: "json_object"}` parameter and provide a schema. Extraction accuracy goes from ~80% to ~93% immediately.
- Download BSE Shareholding Pattern data for Nifty 500: Write the BSE SHP downloader script. Nifty 500 scrip codes are publicly available. Download 8 quarters of SHP data overnight. This is the foundation of the IKG and it is free.

---

### Phase 1: Months 1-3 — Core Moat Foundations

#### Month 1: Intelligence Infrastructure

**Context Engineering for All 10 Agents**
Rewrite every agent's system prompt using Context Engineering principles. Remove all generic framing. Replace with dense, agent-specific financial context. Add agent-specific context loaders that inject the right pre-loaded data for each agent type (IKG data for Governance Agent, financial model outputs for Valuation Agent, etc.). Track which context is cited. Remove uncited content. This is 3-4 weeks of iterative prompt work.

**Pre-Flight Intent Clarification Gate**
Add entity disambiguation to intent_router.py. When the system detects a company name that could resolve to multiple entities (HDFC, L&T Finance, Tata), surface a one-tap disambiguation before launching the research loop. When a query has multiple valid research approaches, present them as options. Estimated effort: 1 week.

**Blueprint Specification Architecture**
Before research sessions launch, generate a formal research spec: stated goals, explicit boundaries, non-goals, success criteria. Present to user for one-tap approval or modification. Agents receive the spec as part of their context. Effort: 2 weeks.

**RouteLLM Integration**
Install routellm, configure routing between GPT-4o-mini (for simple factual queries) and GPT-4o (for complex research). Expected API cost reduction: 40-60% with under 5% quality loss across the full query distribution. Effort: 3-4 days.

**HyDE for Retrieval**
Wrap the retrieval calls in all agents with HyDE: generate a hypothetical answer first, embed that instead of the raw query, retrieve using the better embedding. Apply specifically to annual report and SEBI filing retrieval where vocabulary gap is largest. Effort: 1 week.

#### Month 2: Self-Learning Foundations

**System Prompt Learning via optillm/spl**
Install optillm as a proxy layer between your application and the OpenAI API. Configure the SPL plugin to extract reusable strategies after each graded research session. Store strategies per sector (IT, NBFC, Infrastructure, etc.) and per research type (forensic, valuation, governance). The strategies accumulate in a searchable database. Load top-3 relevant strategies at session start. This is the compounding intelligence system. Effort: 2-3 weeks.

**Reflexion Feedback Loop**
After every research session the Outcome Rubric Grader produces quality flags. Add a Reflexion step: the relevant agent receives the grader's flag and writes a one-paragraph verbal lesson: "I failed to check [X]. Next time I analyze [Y type of company], I will specifically retrieve [Z]." Store these per agent type in Letta Tier 2 memory. Load relevant lessons at session start. Connects the grader's output to actual agent improvement. Effort: 1-2 weeks.

**Outcome Rubric Grader**
Build the independent post-synthesis grader. It receives the final memo and evaluates against a structured rubric: WACC consistency, governance completeness (is pledge % addressed if it's above 15%?), source coverage, SEBI compliance check, internal contradiction detection. Outputs a Research Quality Score (0-100) and specific flags. Effort: 2 weeks.

#### Month 3: IKG Phase 1 Bootstrap

**Oracle Cloud Setup**
Create Oracle Cloud Always Free account. Provision ARM A1 instance (4 OCPUs, 24GB RAM). Install Neo4j Community Edition 5.x. Verify operational. One day.

**Neo4j Schema Implementation**
Implement the full schema: Company nodes (CIN canonical key), Person nodes (DIN canonical key), PromoterGroup nodes, RegulatorAction nodes, Bank nodes, AuditFirm nodes. Implement all edge types: DIRECTOR_OF (with from/to dates), OWNS_STAKE_IN (with %, pledge %, quarter), SUBSIDIARY_OF, PLEDGED_TO, ENFORCEMENT_ACTION_AGAINST, RELATED_PARTY_TRANSACTION. Add confidence score and source citation fields to every edge. Effort: 1 week.

**BSE SHP Ingestion Pipeline**
Build the automated ingestion pipeline: download BSE Shareholding Pattern XMLs for Nifty 500 companies (8 quarters back), parse the XML structure, extract promoter holding %, pledge %, institutional %, write to PostgreSQL staging, load to Neo4j as OWNS_STAKE_IN and PLEDGED_TO edges. This runs as a quarterly cron job forever after. Effort: 2 weeks. Expected output: 500 Company nodes + ~2,000 PromoterGroup nodes + ~60,000 edges.

**MCA Director Network Ingestion**
Write the MCA21 scraper for director DIN linkages. Rate-limit to 100 requests/hour (run overnight). For all 500 Nifty companies (using confirmed CINs), fetch director records: DIN, name, designation, appointment date, cessation date. Load to Neo4j as Person nodes and DIRECTOR_OF edges. Effort: 2 weeks including entity resolution for director names. Expected output: ~15,000 Person nodes + ~30,000 DIRECTOR_OF edges.

**IKG MCP Server**
Build the fourth MCP server: IKG Query Server (:8007). Expose graph query endpoints:
- `GET /ikg/company/{cin}` — full company subgraph
- `GET /ikg/director/{din}` — director's complete board history and company connections
- `GET /ikg/promoter-chain/{cin}` — full ownership chain above the company
- `GET /ikg/shared-directors/{cin1}/{cin2}` — directors common to two companies
- `GET /ikg/enforcement/{cin}` — all SEBI actions against company and its directors
- `GET /ikg/pledge-risk/{cin}` — pledge exposure summary for promoter entities

Register IKG tools with all relevant agents. Governance Agent should auto-call IKG before writing any governance section. Effort: 1 week for server + 1 week for agent integration.

---

### Phase 2: Months 4-9 — Moat Deepening

#### Month 4-5: Dreaming Layer

**Letta Migration**
Migrate memory system from SQLite to Letta. Install letta, provision Letta server on Oracle Always Free VM. Write migration script: read all existing SQLite facts, convert to Letta memory blocks organized by company CIN. Deprecate SQLite after 2-week parallel run. Effort: 3-4 weeks.

**Background Curation Worker (The Dreaming Layer)**
Build the async background worker that runs between user sessions (nightly, 2-5am). The worker:
1. Reads all session JSONL files from the last 24 hours
2. Extracts verified financial claims per company
3. Cross-references new claims against existing Letta Tier 3 memory for that company
4. Detects patterns: consecutive guidance cuts, promoter stake trend, margin trajectory
5. Cross-references patterns across companies for sector-wide signals
6. Writes consolidated, high-signal facts to Letta Tier 3 (archival memory)
7. Generates per-ticker memory summary files for pre-loading

The worker runs as a separate process (not in the main API server). Observable: it logs every consolidation decision. Its output is readable by engineers — the accumulated memory should be inspectable, correctable, and deletable. Effort: 4-6 weeks.

**Pre-Loading Context from Dreaming Layer**
When a user starts a research session on ticker XYZ, the gateway checks if a dreaming-layer memory file exists for XYZ. If it does, it is loaded into the agents' Tier 1 (Core Memory) context before the session begins. The agents start research already knowing the historical context accumulated from all previous sessions on that company. Effort: 1 week.

#### Month 5-6: GraphRAG Integration

**Document Corpus for Nifty 500**
Download last 3 years of annual reports for Nifty 500 companies from BSE (free, mandatory filings). Download all available SEBI enforcement order PDFs (free). Build the document ingestion pipeline for GraphRAG. Effort: 2-3 weeks.

**GraphRAG Setup**
Install `pip install graphrag`. Configure entity types specific to Indian finance: COMPANY, PERSON (DIN), PROMOTER_GROUP, REGULATORY_BODY, FINANCIAL_INSTRUMENT, TRANSACTION_TYPE, AUDIT_FIRM. Run the indexing pipeline on the document corpus. Entity nodes extracted by GraphRAG are linked to IKG nodes using CIN/DIN as canonical identifiers (when GraphRAG extracts "Reliance Industries" it resolves to the same node as the IKG's CIN-based node). Effort: 2-3 weeks.

**GraphRAG MCP Tool**
Expose two query modes as MCP tools:
- Local query: "What does the document corpus say about [company]'s related-party transactions?"
- Global query: "What are the most common governance failure patterns in Indian [sector] companies?"

Research agents call local queries for company-specific analysis; the synthesis agent uses global queries for sector-level context. Effort: 1 week.

#### Month 6-7: Cross-Agent Consensus + STORM

**Cross-Agent Adversarial Critique Panel**
After all 10 specialist agents complete their waves, before synthesis, add a dedicated Critique Agent. Its mandate is adversarial: find WACC inconsistencies between the valuation and risk sections, identify governance signals not addressed in the valuation model, detect forward guidance that contradicts reported financials. Its output is a structured list of flags that the Synthesis Agent must address before writing the final memo. Effort: 2-3 weeks.

**STORM Cross-Agent Interrogation**
Adapt the STORM pattern for the research wave. After initial agent outputs, each agent generates 2-3 targeted questions for specific other agents based on its findings. The Governance Agent's finding about a ₹200cr promoter loan generates a question for the Financials Agent: "What is the interest rate on this loan vs. the company's cost of capital?" This cross-interrogation pass runs before synthesis. Effort: 3-4 weeks.

#### Month 7-9: IKG Phase 2 + Compliance Infrastructure

**SEBI Enforcement Order Pipeline**
Download all SEBI enforcement PDFs (~3,500 documents). Build pdfplumber + spaCy NER extraction pipeline. Train NER model on 500 annotated examples using Google Colab (free). Extract: company name → resolve to CIN, individual names → resolve to DIN where mentioned, violation type, penalty, date, status. Load as ENFORCEMENT_ACTION_AGAINST edges in Neo4j. Effort: 4-6 weeks.

**Annual Report RPT Extraction**
Build camelot-py pipeline for Related Party Transaction table extraction from annual report PDFs. Use JSON structured outputs mode for LLM-assisted extraction. Load as RELATED_PARTY_TRANSACTION edges in Neo4j. Effort: 3-4 weeks.

**ColPali Integration for Annual Report Processing**
Install colpali-engine. Replace text-based PDF extraction for complex financial tables with ColPali's vision-based retrieval. ColPali screenshots each page and embeds it as an image, handling complex multi-column tables and charts that break text extractors. Apply specifically to: RPT tables (most complex layout), financial statement footnotes, director report sections. Effort: 2-3 weeks.

**Compliance Ledger**
Build a separate write-once append-only compliance log. Every research session writes an immutable record: timestamp, input query, Blueprint spec used, data sources accessed, intermediate agent outputs, final memo hash, grader score. Retained for 5 years. Queryable by company, date range, and quality score. This is the institutional procurement requirement. Effort: 1 week for initial version.

**Five-Year Data Sovereignty Review**
Get legal assessment of DPDP Act compliance for current AWS us-east data residency. If required, plan migration to AWS ap-south-1 (Mumbai). Set cookie/consent framework for dreaming layer data processing. Not a feature. A business requirement.

**Portfolio Analytics Dedicated Page**
Build PortfolioAnalyticsPage.tsx using existing components (DonutChart, TreemapChart, AreaChart, RadarChart, MetricCard). Wire to existing portfolio endpoints. New backend additions needed: health score computation, benchmark comparison data, return attribution calculation. Full specification is in the Portfolio Analytics UI document. Effort: 4-6 weeks total.

---

### Phase 3: Months 10-24 — Unicorn Territory

These are the items that take the product from strong to genuinely defensible. Do not start these until Phase 1 and Phase 2 are complete and stable.

**GNN Link Prediction for IKG**
Install PyTorch Geometric. Train a GraphSAGE model on existing IKG edges (verified edges = positive examples, sampled non-edges = negative examples). Run inference to generate "probable but unverified" edge predictions ranked by confidence. These become the highest-priority items for the human validation queue. Estimated coverage increase: 15-25% more edges discovered without additional data ingestion.

**HippoRAG Memory Upgrade**
Replace flat vector retrieval in Letta Tier 3 with HippoRAG's graph-based retrieval. Every memory fact now has connections to related facts (spreading activation). A query about Infosys margin compression activates the entire network of related facts: sector margin cycle, management credibility history, comparable company margins. 30-40% improvement on multi-hop reasoning tasks.

**Time Series Foundation Models**
Integrate TimesFM (Google) or Chronos (Amazon) for financial metric trend analysis and anomaly detection. Applications: detect abnormal revenue/margin deviations from historical patterns (IKG enrichment signal), project LTCG eligibility dates for portfolio holdings (tax optimizer feature), generate probabilistic portfolio value distributions for stress testing (replaces scenario % shocks with model-based distributions).

**Earnings Transcript Analysis Pipeline**
Build systematic detector for earnings call transcript attachments in BSE/NSE corporate filing APIs. When a transcript is detected, route through: structured extraction of management commentary by category (guidance, competition, margins, capital allocation), quarter-over-quarter language sentiment comparison using FinBERT, management promise tracking feed into dreaming layer. This is the highest-signal unstructured data source for Indian equity research currently untapped by any retail tool.

**Regulatory Event Horizon System**
Build monitors for: SEBI consultation papers and circulars, RBI policy communications affecting banking/NBFC stocks, IRDAI circulars affecting insurance companies, TRAI communications affecting telecom, CERC/SERC orders affecting power utilities. When a new regulatory filing is detected, classify affected sector and listed companies, alert users with holdings in affected sectors, auto-trigger deep-dive research on most material changes.

**Multi-Tenancy for B2B**
Add team workspace concept: shared research notes, role-based access (analyst vs. PM vs. compliance officer), collaborative annotation of research memos, user management per organization. This is the feature that enables AMC and brokerage sales. Required for institutional procurement.

**External Intelligence API**
Design and launch ProspektLab Intelligence API: a documented, versioned API that third parties can use to access IKG queries, research sessions, and valuation engine results. Positioned as the data infrastructure layer for Indian fintech. This is potentially the highest-revenue per-customer product in the portfolio.

**DSPy Systematic Prompt Optimization**
Once you have 3 months of Research Quality Scores from the Outcome Rubric Grader, use DSPy to systematically optimize every agent's prompt against that metric. Define research quality as the optimization target. DSPy runs over a weekend, evaluates hundreds of prompt variations, selects the optimal prompt for each agent. Repeat quarterly or when switching base LLM versions.

**Model Fine-Tuning Initiative**
At 12-18 months of operation, ProspektLab will have accumulated thousands of high-quality research memos — verified, graded, cross-agent reviewed outputs on Indian equities. Begin collecting these as a fine-tuning dataset. Evaluate fine-tuning a smaller open-weight model (Qwen, Llama) on this dataset for Indian equity research tasks. A fine-tuned model outperforms GPT-4o on your specific tasks and dramatically reduces per-session API costs.

**Era of Experience Feedback Loop**
Begin tracking outcome data: every research session's key findings and predictions are logged in structured format with the ticker and date. Set automated review at 6, 12, and 24 months to check whether flagged risks materialized. True positives feed back as positive training signal. False positives feed back as negative signal. This is the long-horizon learning loop that makes ProspektLab's research quality compound with real-world validation rather than just with more data.

---

## Part 4: IKG Complete Integration Plan

### The Architecture in One View

```
User Research Session
         │
         ▼
Pre-Flight Gate (entity disambiguation)
         │
         ▼
Blueprint Specification Generated
         │
         ▼
Dreaming Layer Pre-Load (company memory injected)
         │
         ▼
10-Agent Research Wave
    ├── Governance Agent → calls IKG MCP :8007
    │         ├── /ikg/promoter-chain/{cin}
    │         ├── /ikg/enforcement/{cin}
    │         └── /ikg/related-party/{cin}
    ├── Valuation Agent → calls Quant MCP :8005
    ├── Risk Agent → calls IKG :8007 + Quant :8005
    │         └── /ikg/pledge-risk/{cin}
    ├── News Agent → calls Discovery MCP :8003
    ├── [Other 6 agents]
    │
    ▼
STORM Cross-Interrogation Pass
    (agents ask each other targeted questions)
         │
         ▼
Cross-Agent Adversarial Critique
    (Critique Agent challenges assumptions)
         │
         ▼
Synthesis Agent (produces memo)
         │
         ▼
Output Scrubber (strips advisory language)
         │
         ▼
Outcome Rubric Grader (quality score + flags)
         │
         ▼
Reflexion Step (agents write lessons from flags)
         │
         ▼
System Prompt Learning Update (strategies extracted)
         │
         ▼
User Sees Research Memo
         │
         ▼
Dreaming Layer Worker (nightly consolidation)
    (session data → curated memory → future pre-load)
```

### IKG Data Pipeline — Phase 1 Build Sequence

**Day 1-3: Infrastructure**
- Oracle Cloud Always Free: provision ARM A1 (4 OCPUs, 24GB RAM, Ubuntu 22.04)
- Install Neo4j Community 5.x + APOC plugin
- Install PostgreSQL (staging database for raw ingested data before graph write)
- Install Apache Airflow (pipeline orchestration)
- Verify all services running

**Day 4-7: Schema + Entity Resolution**
- Implement full Neo4j schema (Company, Person, PromoterGroup, RegulatorAction, Bank, AuditFirm nodes)
- Implement all edge types with confidence scores and source citations
- Build CIN-based entity resolver for company names
- Build DIN-based entity resolver for director names
- Build fuzzy matching layer (rapidfuzz) for names without canonical IDs

**Week 2-3: MCA Data**
- Download MCA company master bulk CSV (free official download)
- Load to PostgreSQL staging: ~2 million company records
- Filter to Nifty 500 + their subsidiaries (~2,000 companies)
- Resolve all CINs for Nifty 500 companies (cross-reference BSE scrip codes → CIN via MCA lookup)
- Write 2,000 Company nodes to Neo4j

**Week 3-4: BSE SHP Pipeline**
- Build BSE SHP downloader: takes list of BSE scrip codes, downloads all available SHP XML files for each company (8 quarters)
- Parse XML: extract promoter names, holding %, pledge %
- Resolve promoter entity names to CIN where available (most major promoters have MCA registrations)
- Write OWNS_STAKE_IN and PLEDGED_TO edges to Neo4j
- Set up Airflow DAG to run this quarterly automatically

**Week 4-5: Director Network**
- Build MCA21 director lookup scraper (rate-limited to 100 req/hour)
- For each of 2,000 companies (by CIN), fetch director records
- Resolve director DINs → Person nodes
- Write DIRECTOR_OF edges with date ranges
- Handle cessation dates (past directors need to_date set, not deleted)

**Week 5-6: IKG MCP Server**
- Build FastAPI server at :8007
- Implement all 6 query endpoints (see Phase 1 Month 3 above)
- Register IKG tools with Governance Agent, Risk Agent, and Synthesis Agent
- Test: Governance Agent now calls `/ikg/enforcement/{cin}` automatically for every governance analysis
- Test: Risk Agent calls `/ikg/pledge-risk/{cin}` automatically for every risk assessment

**Week 6-8: SEBI Enforcement Layer**
- Build SEBI PDF scraper (downloads all enforcement orders from sebi.gov.in/enforcement)
- Build pdfplumber extraction pipeline for enforcement order text
- Train spaCy NER model on 300-500 annotated examples (use Doccano annotation tool, free)
- Extract company names, DINs, violation types, penalties, dates
- Resolve extracted names to CINs/DINs
- Write ENFORCEMENT_ACTION_AGAINST edges to Neo4j
- Add enforcement flag to Company nodes (boolean + count + most_recent_date)

**Ongoing: GraphRAG Layer**
- Install graphrag, configure for Indian financial entities
- Index downloaded annual reports corpus (Nifty 500, last 3 years)
- Link GraphRAG entity nodes to IKG nodes via CIN matching
- Expose GraphRAG as new MCP tool (:8009)
- Research agents can now query BOTH the structured IKG AND the document-derived GraphRAG graph

### User Contribution to IKG (The Flywheel)

**Implicit Contribution (Zero User Effort):**
Every research session automatically proposes IKG edges via the Dreaming Layer. The worker extracts entity relationships mentioned in research memos, proposes them to the validation queue. Three independent mentions of the same relationship across different sessions auto-promotes to main graph with confidence score proportional to source quality. At 1,000 users × 5 sessions/week = 5,000 sessions × 3 average edge proposals = 15,000 new edge proposals per week. This is the flywheel.

**Passive Contribution (Document Upload):**
When users upload documents (annual reports, SEBI notices, forensic reports), the extraction pipeline processes them as a side effect. User asks a question about the document. IKG proposes new edges from the document. Zero extra user action required.

**Active Contribution (Validation):**
Users see confidence indicators on IKG-derived data in their research sessions. A small "Confirm / Flag as Outdated" affordance on low-confidence data points. Confirmations that are corroborated by official sources update the confidence score. Flags trigger re-verification against current official source. Contributors accumulate reputation score visible on their profile. Top contributors get research credit tokens.

---

## Part 5: Self-Learning Stack — Complete Implementation

This is the system that makes ProspektLab get better automatically over time. It has four components that work together.

### Component 1: System Prompt Learning (SPL)
**What it does:** After every graded research session, extracts reusable strategies and stores them in a searchable scratchpad. Future sessions load relevant strategies at start.

**Implementation:**
Install optillm as an API proxy (github.com/codelion/optillm). Configure SPL plugin. Customize strategy extraction prompt:
```
"You are a financial research quality specialist focused on Indian equity markets. 
After reviewing this research session and its quality assessment, identify ONE specific 
strategy that would have improved the research quality. Express it as an actionable 
rule for future sessions of this type: [sector], [company_type], [research_type].
Format: IF [condition] THEN [specific action to improve research quality]."
```

**Storage:** PostgreSQL table `spl_strategies` with fields: strategy_text, sector, company_type, research_type, confidence_score, times_applied, average_quality_improvement, created_date.

**Retrieval:** At session start, query `spl_strategies` by sector + research_type, load top-3 by (confidence_score × times_applied), inject into each relevant agent's context before research begins.

### Component 2: Dreaming Layer (Memory Curation)
**What it does:** Nightly background worker consolidates session data into curated company-specific memory. Future sessions start with this pre-loaded context.

**Memory types consolidated:**
- Financial facts (verified by Outcome Rubric Grader, source-cited)
- Management credibility records (guidance accuracy, promise vs. delivery tracking)
- Governance risk trajectory (pledge % trend, director changes, auditor changes)
- Sector patterns (cross-company observations about the sector)
- Research quality patterns (what types of analysis produce best results for this company)

**Staleness management:** Every stored fact has a `expires_at` field. Financial ratios expire in 90 days. Director records expire in 180 days. Management credibility records never expire but are additive (new data appends, old data stays for historical context). Outdated facts are flagged, not deleted — historical context is valuable.

### Component 3: Reflexion (Agent-Level Lesson Learning)
**What it does:** After grader flags are produced, relevant agents write verbal lessons. These lessons are stored per agent type and loaded at future session starts.

**Implementation:**
After grader produces flags, route each flag to the responsible agent type with prompt:
```
"The Outcome Rubric Grader flagged the following issue in your analysis: [flag].
Write a one-paragraph lesson for yourself to prevent this issue in future analyses 
of [company_type] companies in the [sector] sector. Be specific about what you 
should check, retrieve, or verify that you did not in this session."
```

Store in Letta Tier 2 per agent type. Load 3 most recent relevant lessons per agent at session start.

### Component 4: Era of Experience (Outcome Validation)
**What it does:** Tracks whether the risks and scenarios identified in research sessions materialise over time. Correct predictions strengthen the strategies that produced them. Incorrect predictions weaken them.

**Implementation:**
Every research session logs structured predictions:
```json
{
  "session_id": "...",
  "ticker": "INFY",
  "date": "2026-02-14",
  "predictions": [
    {"type": "governance_risk", "description": "Promoter pledge at 34% - elevated risk", "review_date": "2026-08-14"},
    {"type": "margin_scenario", "description": "Base case margin 18.2%, downside 16%", "review_date": "2026-05-14"}
  ]
}
```

An automated Airflow job runs at each review_date, fetches current data for the ticker, evaluates whether the flagged risk materialized, and updates the SPL strategy confidence score for strategies that produced this prediction.

This is the only learning signal grounded in real-world financial outcomes rather than just research quality scores. Start collecting the data now even if the feedback loop isn't fully implemented yet.

---

## Part 6: Research Integrations — Complete Priority List

Every innovation from our research conversations, sorted by implementation priority and impact.

### Implement Now (Weeks 1-4)

| Innovation | Source | Application | Effort |
|---|---|---|---|
| Prompt Caching | OpenAI / Anthropic | Add cache_control to all pre-loaded context API calls | 1 day |
| JSON Structured Outputs | OpenAI API | All IKG extraction calls | 2 days |
| Output Scrubber | Constitutional AI principle | Post-synthesis compliance filter | 3 days |
| RouteLLM | LMSys (open source) | Route simple queries to cheaper models | 3-4 days |
| HyDE | Research paper (open source) | Wrap retrieval calls for annual report queries | 1 week |
| Pre-Flight Gate | Original design | Add to intent_router.py | 1 week |

### Implement in Phase 1 (Months 1-3)

| Innovation | Source | Application | Effort |
|---|---|---|---|
| System Prompt Learning | Karpathy / optillm | Strategy scratchpad per sector | 2-3 weeks |
| Context Engineering | Karpathy June 2025 | Agent-specific context optimization | 3-4 weeks |
| Reflexion | Shinn et al. 2023 | Post-grader agent lesson loop | 2 weeks |
| Blueprint Specification | Original design | Pre-session research contract | 2 weeks |
| IKG Phase 1 Build | Original design | Neo4j + BSE SHP + MCA directors | 6-8 weeks |
| Outcome Rubric Grader | Original design | Post-synthesis quality evaluator | 2 weeks |

### Implement in Phase 2 (Months 4-9)

| Innovation | Source | Application | Effort |
|---|---|---|---|
| Dreaming Layer | MemGPT / Letta | Background memory curation worker | 4-6 weeks |
| GraphRAG | Microsoft (open source) | Document graph on annual reports | 3-5 weeks |
| ColPali | Faysse et al. 2024 | Vision-based PDF table extraction | 2-3 weeks |
| STORM Pattern | Stanford (open source) | Cross-agent interrogation in research wave | 3-4 weeks |
| Cross-Agent Adversarial Critique | Original design | Devil's advocate agent post-wave | 2-3 weeks |
| HippoRAG | OSU NLP (open source) | Graph-based memory retrieval in Letta Tier 3 | 2-3 weeks |
| Reasoning Model Integration | DeepSeek R1 / o1 | Forensic research route to reasoning model | 1-2 weeks |

### Implement in Phase 3 (Months 10-24)

| Innovation | Source | Application | Effort |
|---|---|---|---|
| GNN Link Prediction | PyTorch Geometric | IKG gap filling for probable edges | 3-4 weeks |
| DSPy Optimization | Stanford (open source) | Systematic prompt optimization for all agents | 2 weeks setup + ongoing |
| Time Series Foundation Models | TimesFM (Google) / Chronos | Financial metric anomaly detection | 2-3 weeks |
| Mixture of Agents | TogetherAI (open source) | Multi-LLM synthesis layer | 1-2 weeks |
| Multi-Agent Debate | Du et al. 2023 | Bull vs. bear thesis arguing before synthesis | 2-3 weeks |
| FinBERT | HuggingFace (free) | Financial sentiment for news and earnings | 1 week |
| Model Fine-Tuning | Domain-specific | ProspektLab-native Indian finance model | 8-12 weeks |
| Era of Experience Feedback | Sutton & Silver 2025 | Outcome-grounded strategy validation | Ongoing |

### Never Implement (Wrong Tool for This Job)

| Innovation | Reason to Skip |
|---|---|
| Text-to-image / DALL-E | Not a product need |
| Mamba / SSM architectures | Pre-training concern, not application layer |
| Liquid Neural Networks | Same — training paradigm, not your domain |
| Robotics / embodied AI | Completely unrelated |
| New benchmark model comparisons | Evaluate quarterly, not with every release |

---

## Part 7: What Actually Builds the Moat — The One-Page Summary

**The moat is not the multi-agent architecture.** LangGraph is open source. Anyone can build 10 agents in 2 months.

**The moat is not the AI research quality.** GPT-4o is available to every competitor. Even with all the research integrations above, a well-funded competitor can replicate the architecture.

**The moat is three things that require time to accumulate:**

**One: The IKG data asset.** A cleaned, curated, continuously-updating graph of Indian corporate relationships built from MCA, BSE, SEBI, and NCLT data. The first mover who builds this and maintains it is 18-24 months ahead. The data compounds: each new company adds edges with all other companies already in the graph. User research sessions enrich it automatically. This is the only thing that cannot be bought or rushed.

**Two: Per-user memory compounding.** The Dreaming Layer creates memory that deepens with each session. After 18 months, a user's ProspektLab context about their portfolio companies is richer and more curated than anything they could get starting from zero on a competitor platform. This switching cost is real, invisible to users until they try to leave, and grows every week they stay.

**Three: The self-learning loop.** System Prompt Learning + Reflexion + Dreaming Layer + Era of Experience create a system that improves automatically with every session, every user, and every real-world outcome validation. A ProspektLab deployed in January 2027 with 18 months of accumulated learning will outperform a fresh deployment of the same architecture on a competitors platform. The improvement is in the accumulated strategies and memory, not in the code.

Everything else — the compliance infrastructure, the portfolio analytics, the research integrations, the STORM cross-interrogation, the ColPali PDF processing — these are quality features that make users love the product. But the three things above are what makes it defensible.

**The test for any feature you consider building:** Does this accumulate data that is harder to replicate over time? Does this create switching cost that grows with tenure? Does this make the system smarter automatically without proportional engineering work? If yes, build it urgently. If no, it is a quality feature — valuable but not a moat.

---

## Part 8: Weekly Execution Checklist — Next 30 Days

This is the only section that matters right now. Everything above is strategy. This is action.

**This Week:**
- [ ] Rewrite synthesis template: Remove all buy/sell/hold/conviction language. Replace with Scenario Implication Matrices. Do not ship another user-facing session until this is done.
- [ ] Add Output Scrubber function to outbound pipeline. Keyword list minimum viable version.
- [ ] Apply for MCA Data Lake. (20 minutes. mca.gov.in/data-lake)
- [ ] Apply for SEBI Innovation Sandbox. (20 minutes. sebi.gov.in)
- [ ] Enable Prompt Caching on all API calls that have stable pre-loaded context.
- [ ] Download MCA company master bulk CSV. Load into PostgreSQL.
- [ ] Write BSE SHP downloader for Nifty 500. Run it.

**Week 2:**
- [ ] Switch all extraction LLM calls to JSON structured outputs mode with defined schemas.
- [ ] Set up Oracle Cloud Always Free account. Provision ARM A1 instance.
- [ ] Install Neo4j Community Edition on Oracle VM.
- [ ] Implement Neo4j schema (Company, Person, PromoterGroup nodes + DIRECTOR_OF, OWNS_STAKE_IN, PLEDGED_TO edges).
- [ ] Add RouteLLM between your application and OpenAI API. Configure routing rules.

**Week 3:**
- [ ] Load BSE SHP data into Neo4j: Company nodes + PromoterGroup nodes + OWNS_STAKE_IN and PLEDGED_TO edges.
- [ ] Build MCA director scraper. Run overnight for Nifty 500.
- [ ] Implement Pre-Flight Intent Clarification Gate in intent_router.py.
- [ ] Begin agent-by-agent Context Engineering for Governance and Valuation agents first.

**Week 4:**
- [ ] Load director data into Neo4j: Person nodes + DIRECTOR_OF edges.
- [ ] Build IKG MCP server (:8007). Implement first 3 query endpoints.
- [ ] Register IKG tool with Governance Agent. Test: agent now calls IKG for every governance section.
- [ ] Begin optillm/spl integration for System Prompt Learning.

**End of Month 1 State:**
A working Phase 1 IKG covering Nifty 500 with company nodes, director networks, and promoter stake history. The Governance Agent automatically querying the IKG for every research session. The synthesis template producing legally safe scenario framing instead of investment advice. The self-learning loop beginning to accumulate strategies from graded sessions. The product is faster (RouteLLM), more accurate (HyDE, structured outputs), and compliant (Output Scrubber).

That is the foundation. Everything after that builds on it.

---

*Master roadmap document synthesizing 6 strategy documents, full architecture review, IKG build guide, research integration analysis, portfolio analytics UI research, and moat deep-dive. ProspektLab Internal. May 2026.*

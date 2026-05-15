# FinAgent Diagnosis And Walkthrough

This document is a code-based diagnosis of the `finagent/` subsystem as it exists in this repository on May 14, 2026.

It has two goals:

1. explain why FinAgent is often not giving strong answers,
2. explain what each major part of the codebase does and how the runtime really works.

## Executive Summary

FinAgent looks more advanced from the outside than it currently is on the inside.

It has:

- a real standalone gateway,
- a real long-running session loop,
- real enrichment and web scraping,
- a real event stream,
- real reflection, specialist orchestration, verification, memory, checkpoints, and memo output.

But the main reasons answers still feel weak are:

- the specialist layer is not a first-class input to the final memo,
- the LLM is only used at the very end for memo writing, not for most of the reasoning pipeline,
- the new retrieval layer is mostly heuristic scoring scaffolding, not a true indexed retrieval system,
- non-US analysis is still much thinner than the architecture diagram implies,
- several integrations are still placeholders,
- many failures degrade silently into empty results instead of explicit failures.

That is the core truth of the current codebase.

## Findings

## Finding 1

**The multi-agent specialist layer is not directly used by the final memo synthesizer, so a lot of the “smart” work is not actually first-class input to the answer.**

Evidence:

- [run_agent.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/run_agent.py:1283) stores specialist output in `orchestration_findings`.
- [run_agent.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/run_agent.py:1466) calls `synthesize_memo(...)`.
- [synthesis.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/synthesis.py:911) shows `synthesize_memo(...)` accepts `docs`, `checkpoint`, `conflicts`, and `enrichment`, but not specialist findings.

Why this matters:

- `financials`, `risk`, `news`, `macro`, and other specialists produce structured `Finding` objects.
- those findings are emitted to the UI and used by the verifier,
- but they are not passed as a structured knowledge block into the memo composer.

Effect:

- the user sees a “multi-agent” system,
- but the final answer is still mainly built from raw docs and enrichment, not from the full specialist reasoning output.

This is one of the biggest reasons the final answer can feel generic even when the pipeline did a lot of work.

## Finding 2

**The LLM is only used at the synthesis stage. Planning, routing, retrieval, and specialists are almost entirely heuristic code, not model reasoning.**

Evidence:

- [run_agent.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/run_agent.py:988) loads `default_system_prompt()` and discards it.
- [runtime_provider.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/runtime_provider.py:20) resolves the OpenAI config.
- [synthesis.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/synthesis.py:305) is the only real OpenAI memo generation path.
- [intent_router.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/router/intent_router.py:20) routes with keyword matching.
- [financials.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/agents/specialists/financials.py:1), [news.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/agents/specialists/news.py:1), and [risk.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/agents/specialists/risk.py:1) are rule-based specialists.

Why this matters:

- the system appears to be a “deep research AI,”
- but most of the intelligence is actually deterministic heuristics and regex-style scoring,
- and the LLM mostly writes the final memo rather than driving deep reasoning across the run.

Effect:

- answers can be well-formatted,
- but not necessarily deeply reasoned.

## Finding 3

**The new retrieval layer is helpful, but it is not yet a real dense/sparse/graph retrieval system. It is currently heuristic scoring on top of live search results.**

Evidence:

- [dense_index.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/retrieval/dense_index.py:25) uses synonym-expanded token overlap, not embeddings.
- [sparse_index.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/retrieval/sparse_index.py:13) uses token intersection, not BM25 infrastructure.
- [graph_index.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/retrieval/graph_index.py:21) uses regex-extracted entity mentions, not a graph store.
- [reranker.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/retrieval/reranker.py:27) fuses these heuristic scores plus domain and tier boosts.

Why this matters:

- the architecture language sounds like institutional hybrid retrieval,
- but the implementation is still light-weight ranking logic over scraped search results.

Effect:

- it is a good start,
- but it does not yet provide the precision or recall of a true retrieval backend.

## Finding 4

**Non-US coverage is improved at the query-planning layer, but still thin at the structured-data layer.**

Evidence:

- [run_agent.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/run_agent.py:138) skips SEC for non-US entities.
- [jurisdiction_profiles.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/geo/jurisdiction_profiles.py:44) adds India-specific preferred domains.
- [entity_resolver.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/geo/entity_resolver.py:22) uses a small hardcoded country-resolution map.
- [yahoo_finance.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/tools/data/yahoo_finance.py:36) mostly contributes quote/chart style data.

Why this matters:

- the code now localizes search for India, Japan, and Europe better than before,
- but there is still no equivalent of SEC-grade structured fundamentals for those markets inside FinAgent.

Effect:

- outside the US, FinAgent often falls back to:
  - Yahoo quote data,
  - Google News RSS,
  - scraped IR/search results,
  - community/news signals.

That is useful, but it is not the same as having a real country-native fundamentals ingestion layer.

## Finding 5

**Several important integration paths are still placeholders, so the codebase is broader than the real runtime.**

Evidence:

- [prospektlab_adapter/plugin.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/prospektlab_adapter/plugin.py:6) raises `NotImplementedError`.
- [tools/mcp/dynamic_loader.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/tools/mcp/dynamic_loader.py:18) returns `[]`.
- [tools/web/search.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/tools/web/search.py:4) is a full stub.
- the browser/file helper stubs found by search are still not wired.

Why this matters:

- FinAgent has the shape of a larger platform,
- but not all of that platform is operational.

Effect:

- some architecture docs can overstate what is live,
- and some code paths are design scaffolding rather than production behavior.

## Finding 6

**A lot of failure modes are silently converted into empty lists, which makes the system look “weak” instead of “broken.”**

Evidence:

- [news_feed.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/tools/data/news_feed.py:57) catches exceptions and returns `[]`.
- [agents/base.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/agents/base.py:228) converts timed-out or failed search calls into `[]`.
- [scraper.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/tools/web/scraper.py:221) returns `[]` when Bing or DDG search fails.

Why this matters:

- a failed news/search branch does not necessarily surface as a hard failure,
- it simply starves later reasoning stages of evidence.

Effect:

- the final answer can become thin or generic,
- while the system still appears to have “succeeded.”

This is a major reliability and debugging problem.

## Finding 7

**The router is intentionally simple, but still too shallow for high-quality specialist selection.**

Evidence:

- [intent_router.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/router/intent_router.py:20) does keyword matching only.
- [domain_taxonomy.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/router/domain_taxonomy.py:4) is a fixed keyword map.

Why this matters:

- routing is one of the places where a finance research system needs strong classification,
- but the current router is still a text-keyword classifier.

Effect:

- complex questions can still be routed too broadly or too narrowly,
- especially when the user asks multi-part or domain-specific questions.

## Finding 8

**The settings UI suggests “bring your own OpenAI key,” but that key is only saved in browser local storage and is not sent to the server runtime.**

Evidence:

- [settings.html](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/gateway/settings.html:150) defines the `openaiKey` field.
- [settings.html](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/gateway/settings.html:182) loads it from `localStorage`.
- [settings.html](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/gateway/settings.html:202) saves it back to `localStorage`.
- [gateway/run.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/gateway/run.py:125) checks server-side environment variables, not browser storage.

Why this matters:

- a user can believe they configured a key,
- but the server runtime will still report OpenAI as disabled unless `OPENAI_API_KEY` is set on the server.

Effect:

- confusing UX,
- easy misdiagnosis,
- support burden.

## Why FinAgent Often Gives Weak Answers

The short explanation is:

1. the data is often thinner than the UI suggests,
2. the reasoning is often more heuristic than the architecture suggests,
3. the final answer does not directly consume all of the structured specialist work,
4. failures often become empty evidence instead of explicit errors.

That combination creates a system that can look sophisticated while still producing generic or underpowered answers.

## What The Code Actually Does

## 1. Entry Points

### `finagent/gateway/run.py`

Job:

- launches the standalone FastAPI app,
- handles auth screens and HTML pages,
- starts research sessions,
- streams SSE events,
- exposes memo download endpoints.

Important routes:

- `/research/start`
- `/sessions/{session_id}/stream`
- `/sessions/{session_id}/memo`
- `/memos`
- `/health`
- `/config`

Runtime truth:

- this is a standalone app path,
- not the main `Frontend/` + `Backend/` ORACLE path.

### `finagent/cli.py` and `finagent/__main__.py`

Job:

- allow local CLI-based launching/testing.

## 2. Environment and Boot

### `finagent/__init__.py`

Job:

- loads `.env`,
- exposes `FinAgentSettings`.

### `finagent/settings.py`

Job:

- centralizes environment-derived runtime settings like:
  - `OPENAI_API_KEY`
  - `PROSPEKTLAB_MCP_URL`
  - checkpoint cadence
  - compression cadence

### `finagent/runtime_provider.py`

Job:

- resolves the OpenAI runtime configuration,
- currently defaults to `gpt-4o-mini`.

## 3. Session Transport

### `finagent/events.py`

Job:

- in-process session bus,
- one queue per session,
- transports runtime events from the agent loop to the SSE stream.

Why it matters:

- this is what makes FinAgent feel alive while it runs.

## 4. The Core Engine

### `finagent/run_agent.py`

This is the center of gravity of the entire subsystem.

What it does:

1. resolves the entity and geography,
2. loads preferred domains,
3. retrieves a playbook if one exists,
4. builds a retrieval plan,
5. routes the objective to specialists,
6. runs enrichment,
7. runs search and document processing,
8. runs reflection,
9. runs specialist orchestration,
10. runs verifier and blind spots,
11. synthesizes the memo,
12. persists memo, memory, checkpoints, and playbook promotion.

This file is the real FinAgent runtime.

## 5. Research Planning

### `finagent/research_planner.py`

Job:

- defines `ResearchPlan` and `PlanStep`,
- emits a high-level plan shown to the user.

Diagnosis:

- it is more of a descriptive plan object than a true planner.
- the deeper runtime logic lives in `run_agent.py`, not here.

## 6. Geography Layer

### `finagent/geo/entity_resolver.py`

Job:

- normalize the user target,
- infer a country/jurisdiction,
- infer ticker label and Yahoo-compatible symbol,
- attach a `JurisdictionProfile`.

Diagnosis:

- this is useful and improves global behavior,
- but the resolver still depends on:
  - hardcoded aliases,
  - suffix heuristics,
  - limited country hints.

### `finagent/geo/jurisdiction_profiles.py`

Job:

- define country profiles for:
  - `US`
  - `IN`
  - `JP`
  - `EU`
  - `GLOBAL`

It provides:

- exchanges,
- regulator,
- preferred domains,
- filing/search terms,
- Google News locale settings.

Diagnosis:

- strong architecture move,
- still a small curated profile list, not a comprehensive market registry.

### `query_localizer.py`, `source_policy.py`, `ticker_mapper.py`, `currency_policy.py`

Job:

- rewrite generic search prompts into market-specific ones,
- shape preferred domains,
- infer Yahoo ticker suffixes,
- normalize currency context.

## 7. Retrieval Layer

### `finagent/retrieval/planner.py`

Job:

- build breadth queries based on:
  - geography,
  - objective tags,
  - simple intent expansion.

Diagnosis:

- useful planner,
- but still mostly query-template generation.

### `finagent/retrieval/sparse_index.py`

Job:

- tokenization and exact token overlap score.

Diagnosis:

- this is not BM25 infrastructure,
- it is a lightweight lexical scorer.

### `finagent/retrieval/dense_index.py`

Job:

- expand finance synonyms and compute overlap ratio.

Diagnosis:

- this is not embedding-based dense retrieval,
- it is semantic-ish token expansion.

### `finagent/retrieval/graph_index.py`

Job:

- regex-based extraction of related capitalized entity names,
- lightweight relationship score.

Diagnosis:

- this is not a graph database or graph traversal engine,
- it is a heuristic relationship scorer.

### `finagent/retrieval/reranker.py`

Job:

- combine sparse score,
- semantic score,
- entity relationship score,
- preferred-domain boosts,
- source-tier boosts,
- blocked-source penalty.

Diagnosis:

- good practical ranking layer,
- but still dependent on the underlying live search results being good.

## 8. Data Acquisition

### `finagent/tools/data/*`

Key jobs:

- `sec_edgar.py`
  - SEC company lookup, filings, facts, history
- `sec_filings.py`
  - filing narrative extraction
- `yahoo_finance.py`
  - quote and one-month chart snapshot
- `wikipedia.py`
  - encyclopedia summary
- `news_feed.py`
  - Google News RSS
- `reddit.py`
  - Reddit search/sentiment
- `hackernews.py`
  - HN Algolia search
- `stocktwits.py`
  - StockTwits stream snapshot
- `forex.py`
  - USD/INR conversion

Diagnosis:

- this is the strongest real evidence layer in the system,
- but it is much stronger for US companies than for non-US fundamentals.

### `finagent/tools/web/scraper.py`

Job:

- run DuckDuckGo and Bing HTML search,
- interleave and dedupe results,
- fetch pages,
- parse text,
- assign source tiers,
- rerank the docs.

Diagnosis:

- this is a real and useful scraper,
- but it is still web-search dependent and fragile compared with a proper indexed corpus.

### `finagent/tools/web/http_fetcher.py`

Job:

- common fetch wrapper,
- retries,
- robots handling,
- browser fallback hooks.

Diagnosis:

- important infra piece,
- but some browser-assisted fallbacks are still stubs elsewhere.

### `finagent/tools/web/search.py`

Diagnosis:

- pure stub,
- not part of the real live path today.

## 9. Reflection

### `finagent/agent/reflection.py`

Job:

- score coverage quality,
- identify gaps,
- generate more queries,
- keep improving the evidence set.

Diagnosis:

- this is one of the better parts of the design,
- but its value is capped by the quality of the underlying retrieval and by silent failure patterns.

## 10. Specialists

### `finagent/agents/base.py`

Job:

- base classes and dataclasses for:
  - `Finding`
  - `AgentTaskResult`
  - `SubAgentContext`
  - `BaseSubAgent`
- common helper `search_and_dedupe(...)`

Diagnosis:

- clean abstraction,
- but helper failures return empty results silently.

### `finagent/agents/orchestrator.py`

Job:

- run dependency-aware waves of specialists in parallel,
- collect findings and new docs.

Diagnosis:

- solid orchestrator,
- but it is only as useful as the downstream synthesis consumption.

### `finagent/agents/verifier.py`

Job:

- demote unsupported high-confidence findings,
- corroborate repeated claims,
- detect numeric conflicts,
- run the `AccuracyValidator`.

Diagnosis:

- valuable trust-control layer,
- but its output is also not fully elevated into the final memo input structure.

### `finagent/agents/specialists/*`

Current specialists:

- `financials`
- `risk`
- `technical`
- `news`
- `community`
- `competitor`
- `macro`
- `governance`

Diagnosis:

- these are mostly deterministic specialists,
- not LLM-driven domain experts.

That means they can be fast and structured, but also shallow.

## 11. Synthesis

### `finagent/synthesis.py`

Job:

- build the final memo,
- either through:
  - OpenAI streaming prose generation,
  - or structured fallback prose.

Diagnosis:

- the code is well-built for output formatting,
- but this file is also where the main architecture disconnect appears:
  - it reasons over docs, enrichment, conflicts, and citations,
  - not over the full structured specialist knowledge graph produced earlier.

This is the single most important explanation for why the final answer can feel less intelligent than the runtime diagram suggests.

## 12. Memory and State

### `finagent/memory/store.py`

Job:

- SQLite + FTS5 fact memory,
- save reusable facts,
- save session summaries,
- recall previous context by normalized target.

Diagnosis:

- useful,
- but still mainly fact memory rather than deep reusable analytical memory.

### `finagent/playbooks/*`

Job:

- store reusable workflows by geography and intent,
- reapply prior successful query templates and agent selections.

Diagnosis:

- strong direction,
- but the playbook layer is still lightweight and not yet a full workflow-learning engine.

### `finagent/state/*`

Job:

- checkpoint model,
- citation log,
- research-state persistence,
- context compression scaffolding.

Diagnosis:

- practical and valuable,
- especially for long sessions.

## 13. Gateway UI

### `finagent/gateway/widget.html`

Job:

- render the live research app,
- show activity stream,
- show memo,
- show source events,
- show runtime status.

Diagnosis:

- nice standalone UI,
- but some settings are presentational rather than truly connected to server behavior.

### `finagent/gateway/settings.html`

Job:

- local browser preferences UI.

Diagnosis:

- not a true server-side configuration surface.

## 14. What Is Real Versus What Is Placeholder

### Real today

- gateway
- session stream
- research loop
- enrichment
- search/scrape
- reflection
- specialist orchestration
- verifier
- memo synthesis
- memo persistence
- memory
- checkpoints
- geography-aware query shaping
- playbook persistence

### Partially real today

- hybrid retrieval
- specialist routing
- deep research controls
- workflow learning

### Placeholder or unfinished

- host plugin registration
- MCP dynamic loading
- browser deep crawler
- browser screenshot backend
- file OCR and PDF/table helpers
- generic web search wrapper stubs

## 15. Recommended Fix Order

If you want FinAgent to start giving much better answers, the highest-value order is:

1. pass specialist findings directly into `synthesize_memo(...)`
2. make failures explicit instead of returning empty lists everywhere
3. strengthen non-US structured data ingestion
4. upgrade the router beyond keyword matching
5. replace heuristic retrieval scoring with real retrieval infrastructure
6. wire the settings key flow to the server or remove the misleading BYO-key UI
7. finish or remove placeholder integration surfaces so the architecture is less deceptive

## 16. Recommended Reading Order

If you want to understand FinAgent properly, read in this order:

1. [run_agent.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/run_agent.py:988)
2. [gateway/run.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/gateway/run.py:1)
3. [tools/web/scraper.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/tools/web/scraper.py:1)
4. [tools/data/sec_edgar.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/tools/data/sec_edgar.py:1)
5. [agents/base.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/agents/base.py:1)
6. [agents/orchestrator.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/agents/orchestrator.py:1)
7. [agents/verifier.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/agents/verifier.py:1)
8. [agent/reflection.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/agent/reflection.py:1)
9. [synthesis.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/synthesis.py:911)
10. [memory/store.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/memory/store.py:1)
11. [playbooks/store.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/playbooks/store.py:1)
12. [geo/entity_resolver.py](/C:/Users/kusha/OneDrive/डेस्कटॉप/PROSPEKTLAB/finagent/geo/entity_resolver.py:1)

## Final Diagnosis

FinAgent is not “bad code.”

It is a promising autonomous research subsystem with:

- good orchestration ideas,
- useful acquisition code,
- practical reliability mechanisms,
- and strong architectural direction.

But today it is still in the middle stage between:

- a convincing prototype,
- and a fully trustworthy financial research engine.

The current answers feel weaker than expected because the runtime is more heuristic, more search-dependent, more US-weighted, and less tightly integrated end-to-end than the surface architecture suggests.

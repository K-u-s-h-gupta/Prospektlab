# ProspektLab IGS — Complete Implementation Plan

### India's Governance Intelligence Standard: from heuristic score to validated predictive system

> Researched June 2026 against the **live** production stack (Azure VM `prospektlab-ikg-vm`, Docker Postgres). Coverage numbers below are real, pulled from the running database — not estimates.

---

## Table of Contents

1. [Executive Verdict](#1-executive-verdict)
2. [Current State — Real Production Coverage](#2-current-state--real-production-coverage)
3. [How IGS Actually Predicts Anomalies](#3-how-igs-actually-predicts-anomalies)
4. [Latest Technology & Tooling](#4-latest-technology--tooling)
5. [Failed / Delisted Companies — The Mandatory Label Set](#5-failed--delisted-companies--the-mandatory-label-set)
6. [Best Approach to Get Director Data for Free](#6-best-approach-to-get-director-data-for-free)
7. [How Much Historical Data to Scrape](#7-how-much-historical-data-to-scrape)
8. [Where the IKG Is Used (Blast Radius)](#8-where-the-ikg-is-used-blast-radius)
9. [Restructure / Upgrade / Remove / Add](#9-restructure--upgrade--remove--add)
10. [Phased Implementation Plan](#10-phased-implementation-plan)
11. [Success Criteria](#11-success-criteria)

---

## 1. Executive Verdict

**Can the app build IGS? Yes — the architecture is real and capable, not vaporware.** Schema, scraper fleet, pipeline orchestration, graph store (Postgres + Memgraph), and a scoring skeleton all exist and run.

**Can it build IGS today? No.** Two structural gaps block it:

1. **Data density.** Of the five IGS dimensions, only *promoter pledge* has production-grade coverage. Director networks, enforcement proximity, and RPT density have near-zero graph edges.
2. **No predictive layer.** The current governance score is a hand-tuned rules engine. It *describes* present risk; it does not *learn* or *predict* failure. There is no training-label set, no model, no backtest.

**"100% accuracy" is not a meaningful target** — governance failure prediction is probabilistic. The achievable, defensible standard is: **full listed-universe coverage, AUC ≥ 0.80 against real failures, every flag source-cited, predictions leading enforcement by 6–12 months on backtest.**

The single highest-leverage action is **capturing failed/delisted/struck-off companies as training labels** (Section 5). Without the positive class, no amount of modeling produces a predictor.

---

## 2. Current State — Real Production Coverage

**Infrastructure:** VM `prospektlab-ikg-vm` (resource group `PROSPEKTLAB-IKG-RG`, Central India) running a 7-container Docker stack: `postgres:16` (healthy), `redis:7`, `qdrant`, `memgraph-mage`, `memgraph-lab`, `celery-worker`, `scheduler`. A second VM `prospektlab-scraper-vm` (5 public IPs) is available for parallel scraping.

**Database coverage (live):**

| Table | Rows | Note |
|---|---|---|
| `ikg_company_master` | 3,138,081 | Full MCA India registry (incl. struck-off — see §5) |
| `ikg_facts` | 89,737 | Time-stamped fact store |
| `document_sections` | 45,548 | Chunked filings/reports |
| `shp_raw` (shareholding) | 15,441 | Pledge source — strong |
| `annual_reports_raw` | 1,952 | |
| `enforcement_raw` (SEBI orders) | 467 | |
| `auditor_history_raw` | 372 | |
| `directors_raw` | 4,993 | 451 companies, 4,035 DINs |

**Graph:** 46,835 vertices, 39,208 edges. Only **1,271** companies promoted to graph `Company` nodes.

**Edge labels — the core diagnostic:**

| Edge | Count | IGS dimension | Health |
|---|---|---|---|
| `OWNS_STAKE_IN` | 11,846 | Dim 3 Pledge | 🟢 Strong |
| `ISSUED` (regulator→order) | 467 | — | 🟢 |
| `AUDITOR_OF` | 116 | Dim 2 Auditor | 🟡 Thin |
| `DIRECTOR_OF` | **175** | Dim 1 Director network | 🔴 Dead |
| `ENFORCEMENT_ACTION_AGAINST` | **11** | Dim 5 Enforcement proximity | 🔴 Dead (11 of 467 orders linked = 2.4%) |
| `RELATED_PARTY_TRANSACTION` | **0** | Dim 4 RPT density | 🔴 Missing (no edge builder) |

**Gap matrix (root causes):**

| Dimension | Status | Root cause |
|---|---|---|
| Dim 1 Director network | Dead | MCA director scraper disabled; governance-filing scraper run on scoped subset; Person nodes not densely deduped by DIN |
| Dim 2 Auditor | Thin | Annual-report auditor extraction run on small universe |
| Dim 3 Pledge | Working | SHP scraper at 40-quarter depth; scorer logic solid |
| Dim 4 RPT | Missing | `RelatedPartyEdge` defined in schema but no code populates it; RPT data sits in `corporate_xbrl_facts`, never built into edges |
| Dim 5 Enforcement proximity | Dead | SEBI-order → company linking relies on exact name match (`run_store.py`); rarely matches; never resolves to `person:{din}` |

**Scorer gap:** `governance_score.py` computes only *single-company* signals (pledge, dilution, own-company enforcement, auditor churn, board churn). The IGS cross-graph dimensions (director-network-risk, enforcement-proximity distance, RPT-density) are **not implemented at all** — even where edge data existed, the scorer does not traverse it.

---

## 3. How IGS Actually Predicts Anomalies

**The current system does not predict.** `governance_score.py` is a deterministic rules engine: fixed weights (pledge 0.30, enforcement 0.30, etc.) and fixed thresholds (`pledge ≥ 50 → flag`), all hand-chosen. It is a present-risk descriptor, not a forecaster.

True anomaly prediction requires three components:

**(a) Temporal features** — signals derived from the time-stamped graph that move *before* failure:
- promoter pledge slope (Δ% per quarter) and acceleration
- promoter holding dilution velocity
- board churn rate; enforcement-proximity distance of newly appointed directors
- auditor tenure and mid-term-change flag
- RPT density trend (% revenue to related parties, year over year)
- enforcement graph distance (0 / 1 / 2 hops to any enforcement node)
- financial-statement forensics (Beneish M-score, accrual ratios)

**(b) Labels** — the outcome being predicted: companies that *actually failed* (Section 5). This is the missing half.

**(c) Model** — learns which feature combinations preceded failure, from outcomes rather than human guesswork:

```
features at time T  ──►  did an anomaly occur in [T+1, T+12 months]?

pledge↑ + director joins enforcement-adjacent board + mid-term auditor change
        ──►  YES (SEBI order issued 8 months later)
```

**Pattern detection = supervised learning over a temporal graph, validated against real failures.** The model scores live companies and flags those whose current pattern matches historical failure patterns. SHAP values explain each flag, preserving the citation-grade `GovernanceFlag.evidence` contract the product already uses.

---

## 4. Latest Technology & Tooling

The IKG already timestamps every edge and fact (`from_date`/`to_date`, `quarter`, `as_of_date`, `event_date`) — the temporal foundation exists. The missing piece is the predictive layer. Recommended methods, ordered reliable → frontier:

| Approach | Role | Tooling | Apply to |
|---|---|---|---|
| **Gradient-boosted trees** | Core risk model; interpretable via SHAP. The proven workhorse for fraud prediction. | **LightGBM / XGBoost + SHAP** | Primary PGS score |
| **Graph algorithms** | Enforcement-proximity (shortest path), director centrality, community detection, risk PageRank | **Memgraph MAGE (already deployed)** | Dim 1 + Dim 5 features — usable now |
| **GNN embeddings** | Learn company/director embeddings from relationship structure → features | **PyTorch Geometric / DGL / node2vec** | Strengthen director-network signal |
| **Survival analysis** | Time-to-event ("when", not just "if") | **scikit-survival / DeepSurv (Cox)** | The "6–12 months before" claim |
| **Unsupervised anomaly** | Catch novel patterns with no label yet | **Isolation Forest; graph autoencoders (DOMINANT)** | Early-warning safety net |
| **Time-series** | Pledge / financial trajectory modeling | **LightGBM lags / Temporal Fusion Transformer** | Trajectory dimensions |
| **LLM extraction** | RPT notes, SEBI-order entities, auditor opinions from PDFs | **Azure Document Intelligence + GPT (in stack)** | Unstructured → structured |

**Key leverage:** Memgraph-MAGE is already running on the VM. PageRank, betweenness, node2vec, and community detection are available immediately, with no new infrastructure, the moment the graph edges are dense.

**Recommended layered architecture** (each layer reliable and explainable):

```
Layer 0  Memgraph graph algorithms      → proximity / centrality features
Layer 1  LightGBM on temporal+graph     → calibrated risk probability + SHAP reasons   ◄── CORE
Layer 2  scikit-survival                → expected months-to-event
Layer 3  Isolation Forest               → novelty / anomaly flag (no-label safety net)
Ensemble → PGS 0–100 + band + cited flags (retain existing GovernanceFlag.evidence)
```

Do **not** start with deep GNNs. Gradient-boosted trees over well-engineered features outperform them for tabular fraud and provide the per-flag SHAP citations the product needs. Add GNN embeddings later as additional features, never as a replacement for the interpretable core.

---

## 5. Failed / Delisted Companies — The Mandatory Label Set

**This is the number-one requirement, not optional.** A model trained only on surviving companies learns nothing about failure — classic **survivorship bias**. The positive class *is* the failed/delisted/debarred set. No failures in training data → the model cannot recognise failure patterns → predictions are worthless.

**Failure events to capture as labels:**

| Failure type | Source | Signal strength |
|---|---|---|
| Compulsory delisting (for cause) | NSE/BSE delisting circulars | Strongest |
| SEBI debarment / promoter barred | SEBI orders (467 already scraped) | Strong |
| NCLT / IBC insolvency | IBBI, NCLT order lists | Strong (financial failure) |
| Struck-off / under liquidation | **MCA master `status` column (already held — 3.1M rows)** | Strong (corporate death) |
| Trading suspension | Exchange suspension lists | Moderate (distress) |
| Mid-term auditor resignation | Exchange filings | Moderate (pre-failure tremor) |
| Audit qualification / going-concern doubt | Annual reports | Moderate |

**Goldmine already in hand:** the 3.1M MCA master includes struck-off, dormant, and under-liquidation companies via the `status` column — millions of negative outcomes already scraped and currently unused (only 1,271 "alive" companies are promoted to the graph).

**Action:** create a `failure_events` table — `(cin, event_type, event_date, source_url, confidence)` — and backfill 15 years. This becomes the label set that converts the heuristic into a predictor. Everything else in this plan is cosmetic without it.

---

## 6. Best Approach to Get Director Data for Free

**Conclusion: the MCA21 portal (with its per-step CAPTCHA) is NOT required to build listed-company director networks.** The free, structured, no-CAPTCHA path already exists in the codebase and already parses DIN. The fix is operational, not a new scraper.

### Ranked free sources

**Tier 1 — NSE / BSE Corporate Governance API (BEST: free, structured, DIN-bearing, no CAPTCHA)**
- NSE endpoints already wired in `corporate_governance_directors.py`:
  - `https://www.nseindia.com/api/corporate-governance-master` → filing list
  - `https://www.nseindia.com/api/corporate-governance?recId=<id>` → board detail
- The parser already extracts DIN: `re.search(r"<[^>]*(?:DIN|DirectorIdentificationNumber)[^>]*>\s*(\d{8})\s*</", ...)`, keyed `(cin, din)`.
- Source = quarterly Reg 27(2) corporate-governance reports. Provides board composition, DIN, designation, and director category.
- **This alone covers the listed-company director graph that IGS needs.** Currently underused only because it was run on a scoped subset and fell back to PDF/Azure-DI extraction when the structured parse failed.
- BSE equivalent: board-of-directors / governance filings via `api.bseindia.com` — add as a second structured source for cross-validation.

**Tier 2 — NSE / BSE Corporate Announcements (free: tenure dates / board-change events)**
- Director appointment/cessation announcements give the temporal `from_date` / `to_date` needed for tenure and churn signals.
- NSE `corporate-announcements`, BSE `AnnGetData` / corporate announcements API.

**Tier 3 — Annual Report board section (free: cross-validation + auditor + KMP)**
- Already scraped (1,952 reports). Azure DI extracts board + DIN + statutory auditor. Use to cross-validate Tier 1 and to populate the auditor dimension.

**Tier 4 — OpenCorporates free tier (free: cross-company DIN for *unlisted* boards)**
- Sourced from MCA; includes company officers. Coverage is patchy and rate-limited, but it is free and useful for filling a director's *unlisted/shell* board memberships — the enforcement-adjacency moat. Use sparingly and attribute.

### Why MCA21 CAPTCHA is unnecessary here

The IGS director-network moat is about **listed companies and their directors**, and the enforcement-adjacent companies that show up in SEBI orders. All of those are reachable through Tier 1–3 (listed-company filings) with DIN included. The MCA portal is only needed to enumerate a director's *unlisted private* boards at full depth — and for that, the compliant route is **MCA bulk data purchase / data.gov.in datasets**, not CAPTCHA scraping.

> **Compliance note:** MCA21 data is public, but automated bulk scraping may breach the portal's terms of service. The free structured-API path (Tier 1–3) raises no such concern because exchange filings are published for public consumption. If unlisted-board depth is later required at scale, purchase MCA bulk data rather than scraping behind the CAPTCHA.

### The actual fix (operational, free)

1. Run the governance-filing director scraper with `FINAGENT_LISTED_COMPANY_SCOPE=all_listed`.
2. Prefer the **structured NSE/BSE governance API** over PDF extraction; fall back to PDF only when the API record is absent.
3. **Deduplicate `Person` nodes by DIN** in the graph build so one director links to all their boards (this is what turns 175 edges into a real network).
4. Add BSE governance as a parallel structured source for coverage and cross-validation.
5. Layer corporate-announcement board-change events for `from_date`/`to_date`.

Expected result: `DIRECTOR_OF` edges grow from 175 to the order of 50k–60k across the listed universe — at **zero cost and zero CAPTCHA**.

---

## 7. How Much Historical Data to Scrape

IGS is pattern detection, so it needs history — but depth differs per dimension. Target **10 years per company** as the standard (covers all dimensions), and **15 years market-wide for enforcement** (to accumulate enough failure labels).

| Dimension | Minimum | Ideal | Rationale |
|---|---|---|---|
| Pledge trajectory | 8 quarters (2y) | **40 quarters (10y)** | Crisis cases deteriorated 6–12 months before blowup; need multiple cycles. Already configured (`FINAGENT_SHP_QUARTERS=40`). |
| Enforcement (backtest) | 10y | **15y market-wide** | Need enough positive (order-issued) cases to validate. |
| Director tenure / churn | current board | **5y of changes** | Serial-director and churn patterns need dated history. |
| Auditor stability | 5y | **10y** | Rotation law: 5y term, 10y firm cap; mid-tenure change needs the full window. |
| RPT density | 3y | **5y** | Trend in related-party share of revenue. |
| Accounting forensics | 5y | **8–10y** | Beneish M-score and accrual series need long history. |

**Volume targets for ~2,000 active listed (5,000 total):** ~200k SHP rows, ~50k annual reports, ~100k governance filings, ~60k `DIRECTOR_OF` edges. Current coverage is a demo-scale sample (4–8% of target); the work is volume and linking, not capability.

---

## 8. Where the IKG Is Used (Blast Radius)

Changes to the IKG ripple to these consumers. Keep the `GovernanceResult` and `IKGCompanyBundle` **output contracts stable** — swap internals (rules → model) behind the facade so nothing downstream breaks.

| Consumer | File | Uses IKG for |
|---|---|---|
| Service facade | `ikg/service.py` — `build_company_bundle()` | Central entry — chat + deep research |
| Agent context | `agents/context_loaders.py`, `agents/base.py` | Injects IKG bundle into specialist agents |
| Agent definitions | `agents/blueprint.py` | Governance/Accounting agents consume the score |
| MCP tools | `tools/mcp_servers/ikg_server.py` | 24 tools exposed to agent reasoning |
| Portfolio | `portfolio/governance_xray.py` | Portfolio-level governance overlay (UX Pillar 5) |
| API | `gateway/run.py` | HTTP endpoints |
| Content | `content/flash_engine.py`, `content/official_monitor.py` | Daily governance content |
| Dreaming layer | `dreaming/worker.py`, `consolidator.py`, `preloader.py` | Writes candidate facts + refresh hints back into IKG |
| Retrieval | `graphrag/*` | Qdrant document retrieval |
| Synthesis | `synthesis.py` | Final research memo |

`governance_score.py` specifically is consumed by `governance_xray.py`, `gateway/run.py`, `ikg_server.py`, and `agents/blueprint.py`.

---

## 9. Restructure / Upgrade / Remove / Add

### ➕ Add
- **`failure_events` table + scraper** — delisting, IBC/NCLT, SEBI debarment, struck-off labels (§5). *Highest priority.*
- **`RELATED_PARTY_TRANSACTION` edge builder** — RPT data already exists in `corporate_xbrl_facts` (read by `service.get_related_party_transactions`) but is never built into graph edges. Wire XBRL RPT facts + annual-report AS-18 / Ind AS 24 notes into edges.
- **Feature store** — materialized `company_features` table (temporal + graph features per company per quarter); the model's input.
- **`igs_model` module** — LightGBM training + inference + SHAP, parallel to `governance_score.py`.
- **Backtest harness** — date-shifted scoring vs `failure_events`; report precision/recall/AUC and lead-time.
- **BSE governance structured source** — second free DIN source alongside NSE (§6).

### ⬆️ Upgrade
- **`governance_score.py`** — add the three graph dimensions (director-network-risk, enforcement-proximity BFS, RPT-density). Keep the output contract; route through the model when trained, fall back to rules otherwise.
- **Enforcement linking (`run_store.py`)** — replace exact name match with the trigram resolver over the 3.1M master; add `ENFORCEMENT_ACTION_AGAINST → person:{din}` so barred individuals link. Target 11 → 400+.
- **`graph_client.get_shared_directors`** — pairwise today; add network-wide `get_enforcement_proximity(cin)` via Memgraph shortest-path.
- **Director scraper** — `scope=all_listed`; prefer structured governance API over PDF; dedupe Person by DIN (§6).
- **Scrapers → incremental watermark** — reuse `_last_successful_completed_at` across governance, SHP, and enforcement scrapers for delta-only refresh.

### 🔧 Restructure
- **Graph storage split** — Postgres remains system-of-record; **project to Memgraph for traversal and graph algorithms** (MAGE already deployed). Heavy graph math belongs in Memgraph, not SQL recursive CTEs. Fix the broken `memgraph_projection_refresh` task (currently fails on a stale `neo4j` import).
- **Separate "current risk" (rules, always-on) from "predicted risk" (model, when trained)** — expose both as distinct subscores in `GovernanceResult`; never let model uncertainty break the deterministic baseline.

### ❌ Remove / Deprecate
- Stop scheduling the deprecated `mca_director_refresh` no-op (it logs three empty runs per day).
- Resolve the Memgraph-vs-Neo4j driver confusion: the projection task imports `neo4j` but the stack runs Memgraph. Either fix the projection to use the Memgraph driver or remove the task — do not keep a task that times out at 111s every run.

---

## 10. Phased Implementation Plan

**Phase A — Labels + density (unblocks prediction). ~2–3 weeks**
1. Create `failure_events`; mine MCA `status` for struck-off/liquidation; scrape delisting + IBC/NCLT + debarment.
2. Director density via the free structured governance API (`scope=all_listed`, DIN dedupe) — §6.
3. Enforcement fuzzy-linking 11 → 400+; add DIN linking.
4. RPT edge builder from XBRL facts + annual-report notes.

**Phase B — Features + backtest. ~2 weeks**
5. Build `company_features` store (temporal + Memgraph graph features).
6. Backtest harness vs `failure_events`.

**Phase C — Model. ~2–3 weeks**
7. LightGBM + SHAP → `igs_model`, behind the `governance_score` contract.
8. Survival model for timing; Isolation Forest for novelty.

**Phase D — Productionise**
9. Score all listed companies quarterly; store score history (enables the "PGS downgrade" intelligence feed).
10. Calibrate weights; publish backtest AUC and lead-time.

**Sequence rationale:** Fix the entity-resolution foundation (A2/A3) first — it is what everything depends on. Run the volume backfill in the background on the scraper VM while features and the model are built.

---

## 11. Success Criteria

Not "100%". The defensible IGS standard is:

- **Coverage:** all ~2,000 actively listed companies scored (full 5,000 over time).
- **Accuracy:** AUC ≥ 0.80 on held-out failures; calibrated probabilities.
- **Lead time:** predictions lead enforcement/delisting by 6–12 months on backtest.
- **Explainability:** every flag carries a source URL (the existing `GovernanceFlag.evidence` contract).
- **Freshness:** incremental refresh keeps each dimension within its natural update cadence.

**The keystone:** capture failed/delisted/struck-off companies as labels (§5). The label goldmine — millions of struck-off companies — is already scraped in the MCA master and sitting unused. Start there.

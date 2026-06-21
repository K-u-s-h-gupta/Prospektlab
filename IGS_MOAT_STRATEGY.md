# IGS — Moat Strategy & Historical-Data Plan

> Companion to `IGS_IMPLEMENTATION_PLAN.md`. Written against the **live** stack on
> `prospektlab-ikg-vm` only (no scraper-vm). Reflects what is actually built + the
> data-depth and defensibility strategy to turn IGS into a durable moat.

## 1. What the moat actually is

IGS is not "a governance score" — competitors can show today's pledge %. The moat is the
**compounding, failure-labelled, temporal knowledge graph of the Indian listed universe**,
plus the trained+calibrated predictor on top of it. Four layers, each hard to copy:

1. **Entity-resolution spine** — CIN ⇄ DIN ⇄ ISIN ⇄ NSE symbol ⇄ BSE scrip, resolved by
   trigram over the full 3.1M MCA master. This linking is what lets a SEBI order, a board
   seat, and a pledge all attach to one company. (Built: enforcement 11→811 via this.)
2. **Failure label set** — 946k corporate-death outcomes mined from MCA `status` +
   SEBI debarments. The positive class nobody else has assembled. (Built.)
3. **Temporal depth** — 10 years of per-company history so the model sees the
   *trajectory* before failure, not just the snapshot. (Accruing now.)
4. **Calibrated, SHAP-cited predictor** — every flag carries a source URL. Regulated-
   grade explainability is the enterprise wedge. (Built: LightGBM + merge facade.)

**Defensibility = time × coverage.** Each quarter scraped deepens the trajectory and, as
listed companies deteriorate and fail, converts survivors into labelled positives. A new
entrant starts at zero history and cannot retro-scrape delisted companies. The graph is a
data flywheel: more coverage → better labels → better model → more users → more reason to
keep scraping.

## 2. How much history per company (the answer)

Target **10 years per company** standard, **15 years market-wide for enforcement**.

| Dimension | Min | **Target** | Source on ikg-vm (BSE-first) | Why |
|---|---|---|---|---|
| Promoter pledge (SHP) | 8q | **40 quarters (10y)** | BSE `Corp_shpSec...` API ✅ not IP-blocked | deterioration leads blowup 6–12mo; needs cycles |
| Financials | 5y | **8–10y** | screener.in / yfinance ✅ | Beneish M-score + accrual series need long runs |
| Annual reports | 5y | **10y** | BSE annual filings ✅ (local-first extract) | auditor change, RPT trend, going-concern |
| Director / board | board | **5y of changes** | BSE governance filings ✅ (NSE blocked) | tenure, churn, serial-director |
| Enforcement | 10y | **15y market-wide** | SEBI orders ✅ | enough positives to validate |
| RPT | 3y | **5y** | annual-report AS-18 / Ind AS 24 notes ✅ | related-party share trend |
| Corporate actions/filings | 3y | **5–10y** | BSE corporate filings ✅ | context + event dating |

**Volume at full depth (~2,000 active listed, ~6,000 total BSE):** ~80k SHP rows,
~20k annual reports, ~60k director edges, 15y enforcement. Pledge is already configured at
40 quarters (`FINAGENT_SHP_QUARTERS=40`).

## 3. The ikg-vm-only constraint → BSE-first architecture

**NSE 403s Azure datacenter IPs** (`_nse_session.py`). Since everything must run on
`prospektlab-ikg-vm` (Azure, Central India), the strategy is **BSE-first**:

- **Workhorse = BSE** (SHP, annual reports, corporate filings, governance/board, corporate
  actions) — all reachable from the VM.
- **SEBI** (enforcement) and **screener.in/yfinance** (financials) — also reachable.
- **NSE** (full equity list, governance directors, announcements) — only via
  `NSE_COOKIE_STRING` (browser cookie, 1–4h life) injected into the worker env. Code is
  wired (`nse_index.py` applies it + has the full `EQUITY_L.csv` universe); it just needs a
  cookie refreshed periodically. Treat NSE as a *cross-validation enrichment*, not the spine.

Universe is sourced from **BSE bhavcopy** (`daily_prices`, 6,136 scrips + ISIN) →
`ikg_company_master.bse_scrip_code` (guarded unique-name + ISIN match). This lifted the
scrapeable universe from ~500 to **3,680** and is the path to the full ~6,000.

## 4. The real model blocker (and the honest path to AUC ≥ 0.80)

Current AUC ≈ 0.57 — **data-bound, not code-bound.** The 946k failure labels are mostly tiny
struck-off companies that were never scraped, while features sit on large alive companies →
label ∩ feature overlap is tiny. Two fixes, both pure data/time:

1. **Coverage** — scrape SHP/financials/annual for the full 3,680→6,000 BSE universe at 10y
   depth (running now, detached). This is the flywheel fuel.
2. **Point-in-time features** — the model must train on features *as of a date before the
   outcome*. Requires a `quarter-code → calendar-date` mapping for `shp_raw.quarter` (BSE
   QtrCode), then a `company_features` row per (cin, as-of quarter). This is the single
   highest-leverage remaining engineering task; the backtest harness (`igs/backtest.py`)
   already expects dated folds. **Next build.**

With both, the predictor learns trajectories that preceded real failures and the backtest
can prove 6–12mo lead — the published, defensible standard.

## 5. Status (built vs next)

**Built & verified on the VM:** entity-resolution enforcement linking (811), director graph
(4,993), RPT builder (199), 946k failure labels, feature store, LightGBM model + SHAP,
rules+model merge facade, score history, API bundle wiring, cost-gated extraction
(PyMuPDF-first → Azure DI fallback), universe expansion to 3,680, deep 40q SHP backfill
running.

**Next, in priority order:** (1) point-in-time feature snapshots (QtrCode→date) — unlocks
real training/backtest; (2) finish the 10y backfill across the full BSE universe; (3) BSE
governance-director scraper for board depth (NSE blocked); (4) fix `director_kmp` deadlock +
qdrant OpenAI key; (5) inject `NSE_COOKIE_STRING` to add NSE cross-validation; (6) quarterly
auto-score + publish backtest AUC/lead-time.

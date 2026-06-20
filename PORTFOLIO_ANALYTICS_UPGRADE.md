# Portfolio Analytics Upgrade Strategy — From Dashboard Filler to Investor Edge

> **Goal:** Upgrade the ProspektLab portfolio analytics engine so it delivers genuinely actionable, hard-to-compute insights that serious retail investors cannot get from Zerodha, Groww, INDmoney, or even most Western net-worth apps.  
> **Date:** June 2026  
> **Scope:** Gap analysis vs. institutional-grade analytics, advanced metrics to add, and a keep / improve / drop prioritization driven by investor utility, not dashboard vanity.

---

## 1. Executive Summary

The current platform is already **ahead of the average Indian broker dashboard** in three areas: (1) multi-format ingestion (CAS PDF, CSV/XLSX, manual, screenshots), (2) a forensic governance overlay powered by the IKG, and (3) a tax-loss harvesting signal in the tax summary.  

However, most of the remaining metrics — portfolio value, P&L, XIRR, beta, Sharpe, Sortino, sector allocation, correlation heatmap, standard Monte Carlo, and a generic daily action queue — are **surface-level numbers that are either already on broker apps or available for free on sites like Portfolio Visualizer**.  They answer "what happened?" but rarely "why did it happen?" or "what should I do next, given my specific book?".

The upgrade should move the product from **reporting** to **decision support**.  The highest-value additions, in order, are:

1. **Factor exposure & attribution** — decompose returns into market, size, value, quality, momentum, and low-volatility bets.
2. **Regime-based risk decomposition** — show how risk and correlations change in bull/bear, high/low inflation, high/low rates, and high/low volatility regimes.
3. **Drawdown path analysis** — go beyond max drawdown to time-to-recover, drawdown contributors, and recovery velocity.
4. **Tax-loss harvesting optimizer** — move from a static list of loss-making positions to a sequence-aware, wash-sale-aware, multi-year tax-shield optimizer.
5. **Liquidity-adjusted risk** — measure how much of the book can be exited quickly without moving the market.
6. **Forward-looking earnings impact** — overlay earnings estimate revisions, forward P/E, and EPS momentum on holdings.
7. **Behavioral bias detection** — detect the user's own disposition effect, home bias, overtrading, and momentum chasing from trade history.
8. **Rebalancing & glide-path simulation** — goal-based drift bands, transaction-cost-aware rebalancing, and glide-path scenario planning.
9. **Conditional cross-asset correlation** — correlation matrices that are regime-conditional, not static.
10. **Improved tail-risk stress testing** — path-based historical scenarios and conditional drawdown at risk (CDaR), not just single-point shocks.

The report below explains why each matters, how hard it is to implement, and whether the current equivalent metric should be kept, improved, or dropped.

---

## 2. What the Current Platform Already Does Well

| Capability | Assessment |
|------------|------------|
| **Ingestion** | CAS PDF, CSV/XLSX, manual entry, screenshot parsing, ISIN resolution.  Strong differentiation vs. Indian brokers. |
| **Governance X-Ray** | IKG forensic governance score per holding, weighted portfolio governance exposure, flagged holdings.  Genuinely rare in retail. |
| **Core risk metrics** | Beta, annualized volatility, max drawdown, Sharpe, Sortino, Calmar, VaR/CVaR, HHI, top-5 concentration.  Solid foundation. |
| **Tax summary** | STCG/LTCG split, estimated tax liability, and a simple harvest-opportunity list.  Directionally correct but not optimized. |
| **Dividend & corporate action tracking** | Useful for income-oriented investors.  Keep. |
| **AI commentary** | Deterministic fallback + LLM summary.  Good UX, but currently under-informed by factor, regime, and tax context. |
| **Action queue** | Alerts + corporate actions + news + day movers.  Functional but noisy; day movers are low signal. |

The platform already has the **data plumbing** (NSE/BSE prices, corporate filings, governance graph, holdings mirror) to build the next layer.  The gap is mostly in **models and interpretation**, not data access.

---

## 3. The Retail Baseline: What Indian Brokers Already Show

Zerodha (Console/Kite), Groww, and INDmoney already give investors most of the current metrics for free:

* Portfolio value, day P&L, total returns, XIRR.
* Sector allocation (often at a single level).
* Basic stock-level beta and correlation.
* Tax reports (realized P&L, STCG/LTCG splits) — though rarely a true "tax optimizer".
* Dividend history.
* Recent news and corporate actions.
* INDmoney adds US-stock tracking, credit tracking, and some net-worth aggregation.

**What they do not give:** factor decomposition, regime-conditioned risk, liquidity-adjusted risk, behavioral diagnostics, or goal-based rebalancing simulation.  That is where the platform can build a moat.

---

## 4. Gap Analysis: Current Metrics vs. Institutional-Grade Analytics

### 4.1 Performance Measurement

| Current Metric | Institutional Practice | Gap |
|----------------|------------------------|-----|
| Total return, XIRR | **Time-weighted return (TWR)** vs. money-weighted return (IRR), benchmark-relative return, attribution by sector/security/factor, information ratio, tracking error. | No benchmark-relative attribution or TWR; XIRR is useful but mixes investor timing and manager performance. |
| Sharpe / Sortino / Calmar | **Rolling Sharpe/Sortino**, confidence intervals, drawdown-adjusted ratios, omega ratio, upside/downside capture. | Single-point ratios are fragile; no sense of statistical significance. |
| Annualized return | **Alpha vs. beta separation**, Jensen's alpha, Treynor ratio. | No way to know if returns came from market exposure or skill/factor bets. |

### 4.2 Risk Measurement

| Current Metric | Institutional Practice | Gap |
|----------------|------------------------|-----|
| Beta vs. Nifty | **Factor beta** (size, value, quality, momentum, low-vol), **conditional beta** by regime, **downside beta**. | A single market beta hides the true drivers of risk. |
| Volatility | **GARCH/EGARCH** forecast volatility, realized volatility, volatility term structure, volatility clustering. | No forward-looking volatility estimate. |
| Max drawdown | **Drawdown path analysis**, time-to-recover, **conditional drawdown at risk (CDaR)**, **Burke ratio**, **pain ratio**. | Max drawdown is one number; institutions care about the shape of the underwater curve. |
| Historical VaR/CVaR | **Monte Carlo VaR**, **filtered historical simulation**, **extreme value theory** tail estimates, **Cornish-Fisher** adjustment. | Historical VaR assumes the future looks like the past. |
| Correlation heatmap | **Conditional correlation** by regime, **rolling correlation**, **Graphical Lasso / shrinkage covariance**, **HRP** (hierarchical risk parity). | Static correlations rise sharply in crises and mislead investors. |
| Stress test | **Scenario path analysis** (full GFC or COVID trajectory), **factor stress**, **liquidity stress**, **counterparty stress**. | Current shock is a single percentage point; it does not simulate path dependency or recovery. |

### 4.3 Allocation & Construction

| Current Metric | Institutional Practice | Gap |
|----------------|------------------------|-----|
| Sector allocation | **Factor allocation** overlap, **style-box exposure**, **active share** vs. Nifty 50, **tracking error**. | Sector weights alone do not reveal factor concentration. |
| Basic stress test | **Black-Litterman**, **risk parity**, **HRP**, **mean-variance optimization** with transaction costs, **liability-driven investing**. | No portfolio construction advice beyond generic actions. |
| None | **Glide-path simulation** for goals (retirement, child education), **liability matching**, **annuitization risk**. | Missing for goal-based investors. |

### 4.4 Tax & Transaction Cost Intelligence

| Current Metric | Institutional Practice | Gap |
|----------------|------------------------|-----|
| STCG/LTCG estimate | **Tax-loss harvesting optimizer**, **wash-sale monitoring**, **gain/loss sequencing**, **carryforward planning**, **lot-level accounting**. | Current code lists harvest opportunities but does not optimize which lots to sell, when, and in what order. |
| None | **Transaction cost modeling** (market impact, bid-ask spread, slippage), **turnover analysis**. | Rebalancing recommendations ignore execution cost. |

### 4.5 Behavioral & Governance Intelligence

| Current Metric | Institutional Practice | Gap |
|----------------|------------------------|-----|
| Governance X-Ray | **Governance trend/delta**, **peer-relative governance**, **event-driven governance alerts**. | Score is static snapshot; trend and relative position matter more. |
| None | **Behavioral bias detection**: disposition effect, overtrading, home bias, momentum chasing, herding, **regret aversion**. | Not addressed; this is a genuinely unique retail feature. |
| AI commentary | **Causal, factor-aware, regime-aware commentary** with confidence intervals and actionable framing. | Current commentary is descriptive, not diagnostic. |

---

## 5. Advanced Metrics to Add (Prioritized by Investor Utility)

The following table ranks each metric by **investor utility** (U) and **implementation feasibility** (F), with a short rationale and implementation notes.  
*U = High/Medium/Low. F = Easy/Medium/Hard.*

### Tier 1 — Build First (High Utility, Feasible)

| # | Metric | U | F | Why It Matters | Implementation Notes |
|---|--------|---|---|----------------|----------------------|
| 1 | **Factor Exposure & Attribution** | High | Medium | Tells the user whether returns came from market beta, value, size, quality, momentum, or low-volatility bets.  Explains *why* the portfolio behaved the way it did. | Regress portfolio (and each holding) on NSE-style factor mimicking portfolios or Fama-French 5 + Momentum + Quality.  If NSE factor data is unavailable, build proxy factors from NSE 500 constituents (size, value, quality, momentum) using BSE/NSE historical data.  Surface factor loadings, t-stats, R², and alpha. |
| 2 | **Regime-Based Risk Decomposition** | High | Medium | Risk is not constant.  Show VaR, beta, and correlation in four regimes: bull/bear, high/low inflation, high/low rates, high/low VIX/Nifty volatility. | Define regimes from Nifty drawdowns, CPI, repo rate, and India VIX.  Recompute all risk metrics per regime.  Requires ~5 years of regime labels; can be done with downloaded macro data. |
| 3 | **Tax-Loss Harvesting Optimizer** | High | Medium | Converts tax summary from a static list into a ranked action plan: which lots to sell, in what order, to offset STCG/LTCG and minimize wash-sale risk. | Extend `tax.py` with lot-level simulation.  Model carryforward, STCG vs. LTCG rate arbitrage, and 30-day wash-sale guard.  Integrate with action queue as a high-priority task. |
| 4 | **Drawdown Path Analysis** | High | Easy | Max drawdown is a headline; institutions care about *how long* drawdowns last and *which positions* caused them. | Re-use the existing underwater curve.  Add: (a) peak-to-trough duration, (b) recovery duration, (c) per-position drawdown contribution, (d) max consecutive down days, (e) current drawdown percentile vs. historical. |
| 5 | **Conditional Correlation Matrix** | High | Medium | Static correlations collapse in crises.  Show a "normal" matrix and a "stress" matrix. | Compute two correlation matrices: full sample and periods when Nifty fell > 10% or VIX was elevated.  Highlight pairs that become dangerously correlated under stress. |

### Tier 2 — Build Next (High Utility, Harder)

| # | Metric | U | F | Why It Matters | Implementation Notes |
|---|--------|---|---|----------------|----------------------|
| 6 | **Liquidity-Adjusted Risk (LAR)** | High | Hard | A 20% position in an illiquid small-cap is not the same as a 20% position in Reliance.  Institutions know their "liquidity ladder." | Add Amihud illiquidity, average daily value traded (ADVT), bid-ask spread, and days-to-liquidate estimates.  Build a portfolio liquidity score and a "liquidity ladder" (how much can be sold in 1, 5, 20 days without crossing X% of ADV).  Data source: NSE/BSE trade files (volume, close, high-low). |
| 7 | **Forward-Looking Earnings Impact** | High | Hard | Most retail investors are backward-looking.  Institutions overweight estimate revision, earnings surprise, and forward P/E. | Integrate consensus EPS estimates from NSE/BSE/Reuters where available; fallback to company filings + IKG.  Compute: EPS revision momentum, forward P/E, earnings risk (dispersion of estimates), and aggregate portfolio earnings growth.  Flag holdings where estimates are deteriorating. |
| 8 | **Behavioral Bias Detection** | High | Medium | The user's own trading patterns are often the biggest risk.  Detecting disposition effect, overtrading, home bias, and momentum chasing is a genuine differentiator. | Requires transaction history (not just current positions).  Calculate: realized winners vs. losers holding periods, turnover, concentration in home country/state/sector, buy/sell clustering around news/volatility.  Present as a "behavioral report card." |
| 9 | **Rebalancing & Glide-Path Simulation** | High | Medium / Hard | Turns the action queue from reactive to proactive.  Users need to know not just *what* to rebalance, but *how much* and *when*, given their goal. | Build a goal-based simulator: target allocation, drift bands, transaction costs, tax costs, and glide path toward lower equity over time.  Start with simple mean-variance or HRP; later add Black-Litterman views from FinAgent research. |
| 10 | **Improved Tail-Risk Stress Testing** | High | Medium | Current stress tests are single-point shocks.  Path-based historical scenarios and CDaR are more informative. | Implement conditional drawdown at risk (CDaR), run the portfolio through the full 2008/COVID/2022 rate-shock path, and show sector/factor contributions under each scenario. |

### Tier 3 — Differentiating Additions (Medium Utility or Data-Dependent)

| # | Metric | U | F | Why It Matters | Implementation Notes |
|---|--------|---|---|----------------|----------------------|
| 11 | **Active Share & Tracking Error** | Medium | Easy | Quantifies how different the book is from Nifty 50.  Useful for stock-pickers. | Compute active weights vs. Nifty 50 and rolling tracking error.  Add to risk block. |
| 12 | **Upside / Downside Capture** | Medium | Easy | Tells whether the portfolio participates in rallies and protects in falls. | Regression of portfolio returns on market up/down months. |
| 13 | **Information Ratio & Treynor Ratio** | Medium | Easy | Benchmark-relative risk-adjusted performance. | Use Nifty 50 as benchmark. |
| 14 | **Rolling Factor Exposures** | Medium | Medium | Factor bets drift.  Rolling 12-36 month factor loadings show style drift. | Extend factor regression with rolling windows. |
| 15 | **ESG / Forensic Governance Trend** | Medium | Medium | Governance score is more useful if shown over time and relative to peers. | Store historical governance scores; show 1-year delta and peer percentile. |
| 16 | **Variance Drain / Compounding Drag** | Medium | Easy | Volatility reduces compounded returns.  A simple but underused insight. | Compute `geometric return ≈ arithmetic return - σ²/2` and show the drag. |
| 17 | **Sequence-of-Returns Risk** | Medium | Medium | Critical for investors near a goal or retirement. | Monte Carlo with withdrawals; show probability of ruin under different starting valuations. |
| 18 | **Manager Style Drift (for MF holdings)** | Medium | Medium | Indian mutual funds often drift between large/mid/small and growth/value. | Use NAV regression on Nifty 50, Nifty Midcap, Nifty Smallcap, and a bond index; track rolling loadings. |

---

## 6. Keep / Improve / Drop Recommendations

### 6.1 KEEP (solid foundation, no major changes)

| Metric | Rationale |
|--------|-----------|
| **XIRR / money-weighted return** | Correct measure for an investor who adds/withdraws capital.  Add TWR as a complement, but keep XIRR. |
| **Governance X-Ray** | A genuine differentiator in India.  The IKG forensic score is hard to replicate. |
| **Sector / sub-sector allocation** | Keep, but augment with factor allocation overlap. |
| **Dividend tracking & yield** | Useful income metric.  Keep. |
| **Corporate actions calendar** | Keep; integrate with action queue. |
| **Portfolio-specific news** | Keep, but score by materiality and sentiment, not just recency. |
| **Price coverage ratio** | Good transparency for data quality. |

### 6.2 IMPROVE (currently present but shallow or noisy)

| Current Metric | Recommended Improvement |
|----------------|-------------------------|
| **Sharpe / Sortino / Calmar** | Add rolling 12-36 month series, confidence intervals, and regime-conditioned values.  Surface if the ratio is statistically distinguishable from the benchmark. |
| **Beta** | Decompose into market beta + factor betas + downside beta.  Show beta by regime. |
| **Max drawdown** | Add drawdown path analytics: duration, recovery, contributors, current percentile. |
| **Correlation heatmap** | Add a stress-regime matrix and flag "false diversifiers" (pairs that become correlated in crises). |
| **Stress test** | Replace single-point shocks with full path-based historical scenarios and CDaR.  Add sector-specific and liquidity-stress layers. |
| **Tax summary** | Upgrade to a true tax-loss harvesting optimizer with lot-level sequencing, wash-sale guards, and multi-year carryforward modeling.  Correctly handle debt-MF indexation removal (post-April 2023) and new FY 2025-26 equity rates. |
| **AI commentary** | Feed factor attribution, regime state, tax opportunities, and governance flags into the LLM prompt.  Add confidence intervals and a causal "why." |
| **Action queue** | Deprioritize day movers.  Prioritize: governance red flags → tax-loss harvest opportunities → rebalancing drift → earnings estimate deterioration → corporate actions → material news. |
| **Health score** | Redefine inputs to include factor diversification, regime resilience, liquidity, governance, and tax efficiency — not just HHI + Sharpe + drawdown. |
| **Attribution (top contributors/detractors)** | Add factor-attribution: how much of each holding's contribution came from market, sector, style, or idiosyncratic alpha. |

### 6.3 DROP / DEPRIORITIZE (low signal, noisy, or superseded)

| Current Item | Rationale |
|--------------|-----------|
| **Generic Monte Carlo simulation (1000 runs, 1Y horizon)** | Drop as a standalone vanity metric unless it is regime-conditioned, includes fat-tailed returns, and is tied to a goal (e.g., probability of reaching a target).  A plain Gaussian Monte Carlo is misleading. |
| **Day-change movers as action-queue items** | Deprioritize.  A 3% daily move is noise for a long-term investor.  Move to a separate "market pulse" card, not the action queue. |
| **Generic buy/sell/hold recommendations without conviction** | Drop.  Either generate high-conviction, evidence-backed actions (tax harvest, rebalance, governance flag) or do not generate them at all.  Weak recommendations destroy trust. |
| **Static health score as currently defined** | Redefine or hide until it incorporates factor, regime, liquidity, and governance inputs.  A 0-100 score with five components is too reductive and can give false comfort. |
| **Plain VaR without tail adjustment** | Improve or de-emphasize.  Historical VaR assumes i.i.d. returns and underestimates tail risk.  Add CVaR/ES (already present) and Cornish-Fisher / EVT. |
| **"Interest rate shock" as a single sector shock** | Replace with a full factor/rate-path scenario that accounts for duration, credit, and equity sensitivity simultaneously. |

---

## 7. What Cutting-Edge Retail Platforms Are Doing

### 7.1 Kubera
Kubera is a **personal balance sheet** for high-net-worth individuals, not a deep portfolio analytics engine. Its strengths are:

* AI import of brokerage statements and screenshots.
* Multi-currency, multi-entity (trusts, LLCs), nested portfolios.
* AI appraiser for real estate, cars, jewelry, private assets.
* Cash management and cash-flow forecasting.
* Club benchmarks (aggregate peer allocation benchmarks).
* Dead man's switch for estate transfer.
* MCP integration with ChatGPT/Claude/Gemini.

**What it does not do:** factor attribution, regime-based risk, Indian tax optimization, forensic governance scoring, or behavioral diagnostics.  ProspektLab should **not** try to be Kubera; it should double down on the analytics Kubera lacks.

### 7.2 Copilot Money
Copilot is a **budgeting, spending, and net-worth tracker** with beautiful design.  It focuses on:

* AI transaction categorization and budgeting.
* Live account aggregation and net worth.
* Allocation views (equity, crypto, ETF, cash).
* Real-estate tracking via Zillow.

**What it does not do:** serious portfolio risk analytics, tax optimization, or governance intelligence.  It is not a competitor for the serious equity investor.

### 7.3 Portfolio Visualizer (the closest advanced retail benchmark)
Portfolio Visualizer is the closest free/advanced tool to what institutions use.  It offers:

* **Factor regression** (CAPM, Fama-French 3/5, Carhart 4, q-factors, AQR factors).
* **Risk factor allocation** and performance attribution.
* **Efficient frontier, Black-Litterman, rolling optimization, tactical asset allocation.**
* **Monte Carlo simulation** and financial goal planning.
* **Asset correlations** and fund screeners.

**Key insight:** Portfolio Visualizer proves that retail investors *will* use institutional-grade analytics if they are presented clearly.  ProspektLab should match or exceed this in the Indian context, then layer on its proprietary governance graph and tax engine.

### 7.4 Wealthfront (robo-advisor benchmark)
Wealthfront's main retail edge is **tax-loss harvesting** and **direct indexing**.  It claims the average client receives a tax benefit worth up to 13x its advisory fee.  This is the benchmark for the tax-loss harvesting optimizer in the Indian context.

---

## 8. Implementation Roadmap

### Phase 1 — Quick Wins (4–6 weeks)
1. **Factor exposure & attribution** using NSE 500 proxy factors or available factor data.
2. **Drawdown path analysis** (duration, recovery, contributors) on the existing underwater curve.
3. **Conditional correlation matrix** (normal vs. stress regime).
4. **Upgrade AI commentary** to include factor, regime, and tax context.
5. **Re-rank action queue** to prioritize tax/governance/rebalancing over day movers.

### Phase 2 — Core Differentiators (8–12 weeks)
6. **Regime-based risk decomposition** (bull/bear, rate regimes, inflation regimes, volatility regimes).
7. **Tax-loss harvesting optimizer** with lot-level sequencing and wash-sale guard.
8. **Active share, tracking error, information ratio, upside/downside capture** vs. Nifty 50.
9. **Governance trend/delta** and peer-relative governance score.
10. **Improved stress testing** with path-based historical scenarios and CDaR.

### Phase 3 — Advanced Moat (12–20 weeks)
11. **Liquidity-adjusted risk** and liquidity ladder.
12. **Forward-looking earnings impact** overlay.
13. **Behavioral bias detection** from transaction history.
14. **Rebalancing & glide-path simulation** with transaction costs and tax costs.
15. **Black-Litterman or HRP optimization** (optional; can use FinAgent research views as inputs).

### Phase 4 — Polish & Trust (ongoing)
16. Add confidence intervals and statistical significance to all risk metrics.
17. Backtest the new metrics on historical portfolios to validate edge.
18. Build user-facing explanations: "Why this matters" and "What you can do."
19. A/B test which analytics actually change user behavior (not just look good).

---

## 9. Competitive Positioning Summary

| Layer | Zerodha/Groww/INDmoney | Kubera / Copilot | Portfolio Visualizer | ProspektLab (proposed) |
|-------|------------------------|------------------|----------------------|------------------------|
| Ingestion | Broker-only or manual | AI import + sync | Manual ticker entry | **CAS/PDF/CSV/XLSX/screenshot + AI** |
| Net worth / PFM | Basic | Excellent | None | Basic-to-medium |
| Core risk metrics | Basic | Basic | Advanced | **Advanced + regime-conditioned** |
| Factor attribution | None | None | Yes | **Yes (Indian factors)** |
| Tax optimization | None | None | None | **Yes (harvesting optimizer)** |
| Governance | None | None | None | **Yes (IKG forensic)** |
| Behavioral diagnostics | None | None | None | **Yes** |
| Goal-based rebalancing | None | Basic | Yes | **Yes** |

The strategic opportunity is clear: **be the Indian equivalent of Portfolio Visualizer + Wealthfront's tax engine + a forensic governance overlay**, all wrapped in an AI-native interface.

---

## 10. Conclusion

The current platform is **not just surface-level** — it has a real governance edge and good data plumbing.  But most of its portfolio metrics are commodity numbers that do not create an investor edge.  The next upgrade should focus on **interpretation and action**, not more charts.

**Top three priorities:**

1. **Factor attribution & regime-conditioned risk** — explain *why* the portfolio behaves the way it does and how it changes under stress.
2. **Tax-loss harvesting optimizer** — turn tax awareness into quantified after-tax alpha.
3. **Behavioral bias detection** — help the user become a better investor by surfacing their own patterns.

Do these three well, and the platform becomes genuinely hard to replace.  Add the rest as a phased roadmap, always prioritizing metrics that change decisions over metrics that merely fill dashboards.

---

## 11. Sources & References

* AQR Capital Management. *Systematic Equity Investing* and *Tax-Aware Investing*.  https://www.aqr.com
* Chen, J. (Investopedia, 2026). *Understanding Factor Investing*.  https://www.investopedia.com/terms/f/factor-investing.asp
* Fama, E. F., & French, K. R. (1996). *Multifactor Explanations of Asset Pricing Anomalies.* Journal of Finance.
* Portfolio Visualizer. *Factor Regression Analysis*.  https://www.portfoliovisualizer.com/factor-analysis
* Quantpedia. *The Encyclopedia of Algorithmic and Quantitative Trading Strategies*.  https://www.quantpedia.com
* Wealthfront. *Tax-Loss Harvesting 101*.  https://www.wealthfront.com/blog/tax-loss-harvesting
* Kubera. *The Balance Sheet for those who manage their own wealth*.  https://www.kubera.com
* Copilot Money. *Your money, beautifully organized*.  https://copilot.money
* CFA Institute. *Financial Analysts Journal — Performance Measurement and Attribution*.  https://rpc.cfainstitute.org

---

*End of report.*

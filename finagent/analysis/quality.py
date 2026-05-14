"""Research coverage / quality scoring.

Rates the *current* research state across the dimensions a junior analyst
would expect to see in a finished memo. Each dimension has a weight; the
final score is 0-100. Anything below the configured threshold means the
agent should keep digging instead of synthesising.

Dimensions (with weights):
- identity        (8)   canonical entity resolved (SEC CIK / Yahoo / Wiki)
- financials      (16)  ≥6 of the 12 SEC concept metrics resolved
- history         (12)  multi-year time series for revenue + net income
- filing_narrative (10) Item 1A and / or Item 7 prose extracted
- live_quote      (6)   Yahoo Finance current quote + 1-month series
- press_coverage  (10)  ≥4 distinct news headlines from ≥3 outlets
- community       (8)   Reddit/HN/StockTwits aggregated signal present
- web_diversity   (12)  ≥10 scraped docs from ≥6 distinct domains
- citation_tiering (10) ≥2 tier-1 citations + ≥4 tier-2
- conflicts       (4)   conflict scan ran (presence of conflicts is OK)
- competitive     (4)   at least one peer / competitor mentioned in docs

This is intentionally heuristic — the goal is to detect *clear* gaps so
the reflection loop can patch them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


@dataclass
class QualityReport:
    score: float
    dimensions: dict[str, dict[str, Any]] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    suggested_queries: list[str] = field(default_factory=list)

    @property
    def passes(self) -> bool:
        return self.score >= 75.0

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "dimensions": self.dimensions,
            "gaps": self.gaps,
            "suggested_queries": self.suggested_queries,
            "passes": self.passes,
        }


_WEIGHTS: dict[str, float] = {
    "identity": 8,
    "financials": 16,
    "history": 12,
    "filing_narrative": 10,
    "live_quote": 6,
    "press_coverage": 10,
    "community": 8,
    "web_diversity": 12,
    "citation_tiering": 10,
    "conflicts": 4,
    "competitive": 4,
}


def _norm_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


_COMPETITOR_HINTS = (
    " vs ",
    "competitor",
    "competitors",
    "rival",
    "rivals",
    "market share",
    "peer comparison",
    "alternatives to",
)


def score_research(
    *,
    target: str,
    bundle,  # EnrichmentBundle
    docs,  # list[ScrapedDoc]
    checkpoint,  # Checkpoint with citation_log
    conflicts: list | None = None,
) -> QualityReport:
    rep = QualityReport(score=0.0)
    earned = 0.0

    # ── identity ──
    has_sec = bundle and bundle.sec is not None
    has_yahoo = bundle and bundle.yahoo is not None
    has_wiki = bundle and bundle.wikipedia is not None
    id_score = (has_sec * 0.6 + has_yahoo * 0.25 + has_wiki * 0.15)
    rep.dimensions["identity"] = {
        "weight": _WEIGHTS["identity"],
        "ratio": round(id_score, 2),
        "ok": id_score >= 0.6,
        "detail": f"sec={has_sec} yahoo={has_yahoo} wiki={has_wiki}",
    }
    earned += _WEIGHTS["identity"] * id_score
    if id_score < 0.6:
        rep.gaps.append("Canonical entity not fully resolved across SEC + Yahoo + Wikipedia.")

    # ── financials ──
    metrics_n = len((bundle.sec.metrics if has_sec else {}) or {})
    fin_ratio = min(1.0, metrics_n / 10.0)
    rep.dimensions["financials"] = {
        "weight": _WEIGHTS["financials"],
        "ratio": round(fin_ratio, 2),
        "ok": metrics_n >= 6,
        "detail": f"{metrics_n} SEC concept metrics resolved",
    }
    earned += _WEIGHTS["financials"] * fin_ratio
    if metrics_n < 6:
        rep.gaps.append(f"Only {metrics_n} financial metrics resolved (target ≥6).")
        rep.suggested_queries.extend([
            f"{target} latest 10-K revenue gross margin operating income",
            f"{target} annual report fiscal year financial highlights",
        ])

    # ── history (multi-year time series) ──
    hist = (bundle.sec.history if has_sec else {}) or {}
    rev_years = len(((hist.get("revenue") or type("o", (), {"annual": []})()).annual)) if hist else 0
    ni_years = len(((hist.get("net_income") or type("o", (), {"annual": []})()).annual)) if hist else 0
    h_ratio = min(1.0, ((rev_years + ni_years) / 12.0))
    rep.dimensions["history"] = {
        "weight": _WEIGHTS["history"],
        "ratio": round(h_ratio, 2),
        "ok": rev_years >= 5 and ni_years >= 5,
        "detail": f"revenue years={rev_years}, net_income years={ni_years}",
    }
    earned += _WEIGHTS["history"] * h_ratio
    if not (rev_years >= 5 and ni_years >= 5):
        rep.gaps.append(f"Multi-year history thin (rev={rev_years}, ni={ni_years}).")

    # ── filing_narrative ──
    fil = bundle.filing if bundle else None
    has_risks = bool(fil and getattr(fil, "risk_factors", None))
    has_mdna = bool(fil and getattr(fil, "mdna", None))
    fn_ratio = 0.5 * has_risks + 0.5 * has_mdna
    rep.dimensions["filing_narrative"] = {
        "weight": _WEIGHTS["filing_narrative"],
        "ratio": round(fn_ratio, 2),
        "ok": has_risks and has_mdna,
        "detail": f"risk_factors={has_risks} mdna={has_mdna}",
    }
    earned += _WEIGHTS["filing_narrative"] * fn_ratio
    if not (has_risks and has_mdna):
        rep.gaps.append("Missing 10-K Item 1A and/or Item 7 narrative.")
        rep.suggested_queries.append(f"{target} 10-K risk factors site:sec.gov")

    # ── live_quote ──
    q_ratio = 1.0 if (has_yahoo and getattr(bundle.yahoo, "series_closes", None)) else (0.5 if has_yahoo else 0.0)
    rep.dimensions["live_quote"] = {
        "weight": _WEIGHTS["live_quote"],
        "ratio": round(q_ratio, 2),
        "ok": q_ratio >= 0.5,
        "detail": "yahoo quote " + ("with series" if q_ratio == 1 else "missing" if q_ratio == 0 else "quote only"),
    }
    earned += _WEIGHTS["live_quote"] * q_ratio

    # ── press_coverage ──
    news = (bundle.news if bundle else None) or []
    sources = {(n.source or "").strip() for n in news if (n.source or "").strip()}
    pc_ratio = min(1.0, (len(news) / 6.0) * 0.6 + (len(sources) / 4.0) * 0.4)
    rep.dimensions["press_coverage"] = {
        "weight": _WEIGHTS["press_coverage"],
        "ratio": round(pc_ratio, 2),
        "ok": len(news) >= 4 and len(sources) >= 3,
        "detail": f"{len(news)} headlines, {len(sources)} outlets",
    }
    earned += _WEIGHTS["press_coverage"] * pc_ratio
    if len(news) < 4:
        rep.gaps.append("Press coverage thin (<4 headlines).")
        rep.suggested_queries.append(f"{target} latest news earnings analyst")

    # ── community ──
    reddit_n = len((bundle.reddit if bundle else None) or [])
    hn_n = len((bundle.hackernews if bundle else None) or [])
    has_st = bool(bundle and bundle.stocktwits)
    com_ratio = min(1.0, (reddit_n / 8.0) * 0.5 + (hn_n / 3.0) * 0.25 + 0.25 * has_st)
    rep.dimensions["community"] = {
        "weight": _WEIGHTS["community"],
        "ratio": round(com_ratio, 2),
        "ok": reddit_n + hn_n >= 4 or has_st,
        "detail": f"reddit={reddit_n} hn={hn_n} stocktwits={has_st}",
    }
    earned += _WEIGHTS["community"] * com_ratio
    if reddit_n + hn_n < 4 and not has_st:
        rep.gaps.append("Community signal sparse.")

    # ── web_diversity ──
    domains: set[str] = set()
    for d in docs or []:
        dom = _norm_domain(d.final_url or d.url or "")
        if dom:
            domains.add(dom)
    wd_ratio = min(1.0, (len(docs or []) / 14.0) * 0.5 + (len(domains) / 8.0) * 0.5)
    rep.dimensions["web_diversity"] = {
        "weight": _WEIGHTS["web_diversity"],
        "ratio": round(wd_ratio, 2),
        "ok": len(docs or []) >= 10 and len(domains) >= 6,
        "detail": f"{len(docs or [])} docs across {len(domains)} domains",
    }
    earned += _WEIGHTS["web_diversity"] * wd_ratio
    if len(domains) < 6:
        rep.gaps.append(f"Source diversity low ({len(domains)} unique domains).")
        rep.suggested_queries.append(f"{target} institutional analyst report")

    # ── citation_tiering ──
    cl = getattr(checkpoint, "citation_log", []) if checkpoint else []
    n_primary = sum(1 for c in cl if getattr(c, "kind", "") == "primary")
    n_secondary = sum(1 for c in cl if getattr(c, "kind", "") == "secondary")
    ct_ratio = min(1.0, (n_primary / 3.0) * 0.5 + (n_secondary / 5.0) * 0.5)
    rep.dimensions["citation_tiering"] = {
        "weight": _WEIGHTS["citation_tiering"],
        "ratio": round(ct_ratio, 2),
        "ok": n_primary >= 2 and n_secondary >= 4,
        "detail": f"primary={n_primary} secondary={n_secondary}",
    }
    earned += _WEIGHTS["citation_tiering"] * ct_ratio
    if n_primary < 2:
        rep.gaps.append("Tier-1 (primary) citations under-represented.")
        rep.suggested_queries.append(f"{target} site:sec.gov 10-K")

    # ── conflicts ── (dimension is "scan ran", not "no conflicts found")
    conf_ran = conflicts is not None
    co_ratio = 1.0 if conf_ran else 0.0
    rep.dimensions["conflicts"] = {
        "weight": _WEIGHTS["conflicts"],
        "ratio": co_ratio,
        "ok": conf_ran,
        "detail": f"conflicts found={len(conflicts or [])}",
    }
    earned += _WEIGHTS["conflicts"] * co_ratio

    # ── competitive context ──
    comp_hits = 0
    for d in docs or []:
        text = ((d.title or "") + " " + (d.excerpt or "")).lower()
        if any(h in text for h in _COMPETITOR_HINTS):
            comp_hits += 1
    comp_ratio = min(1.0, comp_hits / 3.0)
    rep.dimensions["competitive"] = {
        "weight": _WEIGHTS["competitive"],
        "ratio": round(comp_ratio, 2),
        "ok": comp_hits >= 2,
        "detail": f"competitor/peer mentions across {comp_hits} docs",
    }
    earned += _WEIGHTS["competitive"] * comp_ratio
    if comp_hits < 2:
        rep.gaps.append("Competitive landscape not yet covered.")
        rep.suggested_queries.append(f"{target} top competitors market share comparison")

    total_weight = sum(_WEIGHTS.values())
    rep.score = (earned / total_weight) * 100.0
    # De-duplicate suggested queries, preserve order
    seen = set()
    rep.suggested_queries = [q for q in rep.suggested_queries if not (q in seen or seen.add(q))]
    return rep

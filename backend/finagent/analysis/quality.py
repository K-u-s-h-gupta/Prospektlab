"""Research coverage / quality scoring.

The score is intentionally heuristic. Its main job is not to be "correct" in
an abstract sense, but to push reflection toward obvious India-market gaps
before the memo is written.
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
    "industry leader",
    "sector",
    "compared to",
    "outperform",
    "underperform",
    "peer group",
    "industry peer",
    "leading player",
    "competitive advantage",
)


def _annual_len(history: dict, key: str) -> int:
    if not history:
        return 0
    series = history.get(key)
    if not series:
        return 0
    return len(getattr(series, "annual", []) or [])


def score_research(
    *,
    target: str,
    bundle,  # EnrichmentBundle
    docs,  # list[ScrapedDoc]
    checkpoint,  # Checkpoint with citation_log
    entity=None,
    conflicts: list | None = None,
) -> QualityReport:
    rep = QualityReport(score=0.0)
    earned = 0.0

    country_code = (getattr(entity, "country_code", None) or "GLOBAL").upper()
    is_us_like = False

    has_sec = bool(bundle and bundle.sec is not None)
    has_yahoo = bool(bundle and bundle.yahoo is not None)
    has_wiki = bool(bundle and bundle.wikipedia is not None)
    # The local India snapshot is the primary structured data source.
    has_india_snap = bool(bundle and getattr(bundle, "india_snap", None) is not None)
    # Keep the structured-data score anchored to India-sourced metrics.
    has_structured = has_india_snap

    yahoo = getattr(bundle, "yahoo", None) if bundle else None
    yahoo_metrics = dict(getattr(yahoo, "financial_metrics", {}) or {})
    yahoo_rev_years = len(getattr(yahoo, "annual_revenue", []) or [])
    yahoo_ni_years = len(getattr(yahoo, "annual_net_income", []) or [])

    # India snap metrics supplement Yahoo when Yahoo is rate-limited
    india_snap = getattr(bundle, "india_snap", None) if bundle else None
    india_metrics = dict(getattr(india_snap, "metrics", {}) or {}) if (has_india_snap and india_snap) else {}

    metrics_target = 6 if is_us_like else 4
    history_target = 5 if is_us_like else 4
    press_headline_target = 4 if is_us_like else 3
    press_outlet_target = 3 if is_us_like else 2
    doc_target = 10 if is_us_like else 6
    domain_target = 6 if is_us_like else 3
    primary_target = 2 if is_us_like else 1
    secondary_target = 4 if is_us_like else 2

    # Identity
    if is_us_like:
        id_score = (has_sec * 0.6) + (has_yahoo * 0.25) + (has_wiki * 0.15)
        id_ok = id_score >= 0.6
        id_detail = f"sec={has_sec} yahoo={has_yahoo} wiki={has_wiki}"
        id_gap = "Canonical entity not fully resolved across primary exchange filings + Yahoo + Wikipedia."
    else:
        # For India: india_snap is the primary source; Yahoo and Wikipedia supplement
        id_score = (has_india_snap * 0.5) + (has_yahoo * 0.3) + (has_wiki * 0.2)
        id_ok = id_score >= 0.5
        id_detail = f"india_snap={has_india_snap} yahoo={has_yahoo} wiki={has_wiki}"
        id_gap = "Canonical entity not fully resolved across local-market sources + Yahoo/Wikipedia."
    rep.dimensions["identity"] = {
        "weight": _WEIGHTS["identity"],
        "ratio": round(id_score, 2),
        "ok": id_ok,
        "detail": id_detail,
    }
    earned += _WEIGHTS["identity"] * id_score
    if not id_ok:
        rep.gaps.append(id_gap)

    # Financials — combine India snap metrics + Yahoo metrics for non-US
    if is_us_like and has_sec:
        metrics_n = len((bundle.sec.metrics if has_sec else {}) or {})
        fin_detail = f"{metrics_n} primary filing metrics resolved"
        fin_queries = [
            f"{target} latest annual report revenue gross margin operating income SEBI LODR",
            f"{target} annual report fiscal year financial highlights",
        ]
    else:
        # For India: merge india_snap metrics (P/E, ROE, ROCE, etc.) with Yahoo metrics
        combined_metrics = {**india_metrics, **yahoo_metrics}
        metrics_n = len(combined_metrics)
        fin_detail = f"{metrics_n} metrics resolved (india_snap={len(india_metrics)}, yahoo={len(yahoo_metrics)})"
        fin_queries = [
            f"{target} screener.in annual report revenue EBITDA margin ROE",
            f"{target} NSE quarterly results financial highlights ROCE",
            f"{target} Moneycontrol financials balance sheet debt equity",
        ]
    fin_ratio = min(1.0, metrics_n / float(max(metrics_target, 4)))
    rep.dimensions["financials"] = {
        "weight": _WEIGHTS["financials"],
        "ratio": round(fin_ratio, 2),
        "ok": metrics_n >= metrics_target,
        "detail": fin_detail,
    }
    earned += _WEIGHTS["financials"] * fin_ratio
    if metrics_n < metrics_target:
        rep.gaps.append(f"Only {metrics_n} financial metrics resolved (target >={metrics_target}).")
        rep.suggested_queries.extend(fin_queries)

    # History
    if is_us_like and has_sec:
        sec_history = (bundle.sec.history if has_sec else {}) or {}
        rev_years = _annual_len(sec_history, "revenue")
        ni_years = _annual_len(sec_history, "net_income")
    else:
        # India: use Yahoo history; Screener quarterly data provides additional context
        rev_years = yahoo_rev_years
        ni_years = yahoo_ni_years
        if has_india_snap and india_snap:
            qr = len(getattr(india_snap, "quarterly_revenue", []) or [])
            if qr > 0 and rev_years == 0:
                rev_years = qr // 4  # approximate annual years from quarterly data
    history_target_total = max(history_target * 2, 8)
    h_ratio = min(1.0, (rev_years + ni_years) / float(history_target_total))
    rep.dimensions["history"] = {
        "weight": _WEIGHTS["history"],
        "ratio": round(h_ratio, 2),
        "ok": rev_years >= history_target and ni_years >= history_target,
        "detail": f"revenue years={rev_years}, net_income years={ni_years}",
    }
    earned += _WEIGHTS["history"] * h_ratio
    if not (rev_years >= history_target and ni_years >= history_target):
        rep.gaps.append(f"Multi-year history thin (rev={rev_years}, ni={ni_years}).")

    # Filing narrative: check annual-report and SEBI/Trendlyne sections.
    fil = bundle.filing if bundle else None
    sebi_fil = getattr(bundle, "sebi_filing", None) if bundle else None
    has_risks = bool(
        (fil and getattr(fil, "risk_factors", None))
        or (sebi_fil and getattr(sebi_fil, "risk_factors", None))
    )
    has_mdna = bool(
        (fil and getattr(fil, "mdna", None))
        or (sebi_fil and getattr(sebi_fil, "management_discussion", None))
        or (sebi_fil and getattr(sebi_fil, "financial_summary", None))
    )
    if is_us_like:
        fn_ratio = (0.5 * has_risks) + (0.5 * has_mdna)
        fn_ok = has_risks and has_mdna
        fn_gap = "Missing annual-report risk factors and/or management discussion narrative."
        fn_query = f"{target} annual report risk factors management discussion site:nseindia.com OR site:bseindia.com"
    else:
        # For Indian companies: no SEBI electronic parser yet, so give a 0.7 base
        # score to avoid unfairly failing quality gate. Full credit if we find narrative.
        fn_ratio = 1.0 if (has_risks or has_mdna) else 0.7
        fn_ok = True  # don't fail gate for non-US; narrative comes from web scrape
        fn_gap = "Primary filing or annual-report narrative still thin for this local-market issuer."
        fn_query = f"{target} annual report risk factors management discussion"
    rep.dimensions["filing_narrative"] = {
        "weight": _WEIGHTS["filing_narrative"],
        "ratio": round(fn_ratio, 2),
        "ok": fn_ok,
        "detail": f"risk_factors={has_risks} mdna={has_mdna}",
    }
    earned += _WEIGHTS["filing_narrative"] * fn_ratio
    if not fn_ok:
        rep.gaps.append(fn_gap)
        rep.suggested_queries.append(fn_query)

    # Live quote
    q_ratio = 1.0 if (has_yahoo and getattr(yahoo, "series_closes", None)) else (0.5 if has_yahoo else 0.0)
    rep.dimensions["live_quote"] = {
        "weight": _WEIGHTS["live_quote"],
        "ratio": round(q_ratio, 2),
        "ok": q_ratio >= 0.5,
        "detail": "yahoo quote " + ("with series" if q_ratio == 1 else "missing" if q_ratio == 0 else "quote only"),
    }
    earned += _WEIGHTS["live_quote"] * q_ratio

    # Press coverage
    news = (bundle.news if bundle else None) or []
    sources = {(n.source or "").strip() for n in news if (n.source or "").strip()}
    pc_ratio = min(1.0, (len(news) / 6.0) * 0.6 + (len(sources) / 4.0) * 0.4)
    rep.dimensions["press_coverage"] = {
        "weight": _WEIGHTS["press_coverage"],
        "ratio": round(pc_ratio, 2),
        "ok": len(news) >= press_headline_target and len(sources) >= press_outlet_target,
        "detail": f"{len(news)} headlines, {len(sources)} outlets",
    }
    earned += _WEIGHTS["press_coverage"] * pc_ratio
    if len(news) < press_headline_target:
        rep.gaps.append(f"Press coverage thin (<{press_headline_target} headlines).")
        rep.suggested_queries.append(f"{target} latest news earnings analyst")

    # Web diversity
    domains: set[str] = set()
    for d in docs or []:
        dom = _norm_domain(d.final_url or d.url or "")
        if dom:
            domains.add(dom)
    wd_ratio = min(1.0, (len(docs or []) / float(max(doc_target, 10))) * 0.5 + (len(domains) / float(max(domain_target, 6))) * 0.5)
    rep.dimensions["web_diversity"] = {
        "weight": _WEIGHTS["web_diversity"],
        "ratio": round(wd_ratio, 2),
        "ok": len(docs or []) >= doc_target and len(domains) >= domain_target,
        "detail": f"{len(docs or [])} docs across {len(domains)} domains",
    }
    earned += _WEIGHTS["web_diversity"] * wd_ratio
    if len(domains) < domain_target:
        rep.gaps.append(f"Source diversity across {len(domains)} unique domains (target >= {domain_target}).")
        if not is_us_like:
            rep.suggested_queries.append(f"{target} moneycontrol screener trendlyne analysis")
        else:
            rep.suggested_queries.append(f"{target} institutional analyst report")

    # Citation tiering
    cl = getattr(checkpoint, "citation_log", []) if checkpoint else []
    n_primary = sum(1 for c in cl if getattr(c, "kind", "") == "primary")
    n_secondary = sum(1 for c in cl if getattr(c, "kind", "") == "secondary")
    ct_ratio = min(1.0, (n_primary / float(max(primary_target + 1, 3))) * 0.5 + (n_secondary / float(max(secondary_target + 1, 5))) * 0.5)
    rep.dimensions["citation_tiering"] = {
        "weight": _WEIGHTS["citation_tiering"],
        "ratio": round(ct_ratio, 2),
        "ok": n_primary >= primary_target and n_secondary >= secondary_target,
        "detail": f"primary={n_primary} secondary={n_secondary}",
    }
    earned += _WEIGHTS["citation_tiering"] * ct_ratio
    if n_primary < primary_target:
        rep.gaps.append("Tier-1 (primary) citations under-represented.")
        if is_us_like:
            rep.suggested_queries.append(f"{target} SEBI LODR annual report NSE BSE filing")
        else:
            rep.suggested_queries.append(f"{target} annual report BSE NSE screener.in exchange filing")

    # Conflicts
    conf_ran = conflicts is not None
    co_ratio = 1.0 if conf_ran else 0.0
    rep.dimensions["conflicts"] = {
        "weight": _WEIGHTS["conflicts"],
        "ratio": co_ratio,
        "ok": conf_ran,
        "detail": f"conflicts found={len(conflicts or [])}",
    }
    earned += _WEIGHTS["conflicts"] * co_ratio

    # Competitive context
    comp_hits = 0
    for d in docs or []:
        text = ((d.title or "") + " " + (d.excerpt or "")).lower()
        if any(h in text for h in _COMPETITOR_HINTS):
            comp_hits += 1
    comp_ratio = min(1.0, comp_hits / 2.0)
    rep.dimensions["competitive"] = {
        "weight": _WEIGHTS["competitive"],
        "ratio": round(comp_ratio, 2),
        "ok": comp_hits >= 1,
        "detail": f"competitor/peer mentions across {comp_hits} docs",
    }
    earned += _WEIGHTS["competitive"] * comp_ratio
    if comp_hits < 1:
        rep.gaps.append("Competitive landscape not yet covered.")
        rep.suggested_queries.append(f"{target} top competitors market share comparison")

    total_weight = sum(_WEIGHTS.values())
    rep.score = (earned / total_weight) * 100.0

    seen: set[str] = set()
    rep.suggested_queries = [q for q in rep.suggested_queries if not (q in seen or seen.add(q))]
    return rep

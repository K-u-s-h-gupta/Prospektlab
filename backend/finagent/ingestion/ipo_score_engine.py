"""ProspektLab IPO Score — five-dimension composite scoring engine."""

from __future__ import annotations

import re
from typing import Any


RISK_CATEGORY_KEYWORDS = {
    "business": ("competition", "customer", "market", "demand", "technology", "product", "supply"),
    "regulatory": ("regulatory", "sebi", "rbi", "government", "policy", "license", "compliance", "statutory"),
    "management": ("management", "promoter", "director", "key personnel", "succession", "conflict"),
    "financial": ("financial", "debt", "borrowing", "liquidity", "working capital", "cash flow", "interest"),
    "market": ("market price", "volatility", "exchange", "trading", "foreign exchange", "currency", "interest rate"),
}

SEVERITY_KEYWORDS = {
    "high": ("material adverse", "significant", "substantial", "may adversely", "could materially", "going concern"),
    "medium": ("may affect", "could impact", "subject to", "depends on"),
    "low": ("minor", "limited", "unlikely"),
}


def classify_risks(risks: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify numbered risk factors by category and severity (FinBERT-compatible heuristic)."""
    categorized: dict[str, list[dict[str, Any]]] = {key: [] for key in RISK_CATEGORY_KEYWORDS}
    uncategorized: list[dict[str, Any]] = []

    for risk in risks:
        text = (risk.get("text") or "").lower()
        severity = "medium"
        for level, keywords in SEVERITY_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                severity = level
                break
        category = None
        for cat, keywords in RISK_CATEGORY_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                category = cat
                break
        enriched = {**risk, "severity": severity, "category": category or "business"}
        if category:
            categorized[category].append(enriched)
        else:
            uncategorized.append(enriched)
            categorized["business"].append(enriched)

    severity_weight = {"high": 3, "medium": 2, "low": 1}
    concentration: dict[str, Any] = {}
    for cat, items in categorized.items():
        score = sum(severity_weight.get(item["severity"], 2) for item in items)
        concentration[cat] = {"count": len(items), "severity_score": score}

    top_risks = sorted(
        [item for items in categorized.values() for item in items],
        key=lambda r: severity_weight.get(r["severity"], 2),
        reverse=True,
    )[:5]

    dominant_category = max(concentration.items(), key=lambda kv: kv[1]["severity_score"])[0] if concentration else None

    return {
        "total_count": len(risks),
        "by_category": concentration,
        "dominant_category": dominant_category,
        "top_risks": top_risks,
        "regulatory_or_management_alert": any(
            concentration.get(cat, {}).get("count", 0) >= 5 for cat in ("regulatory", "management")
        ),
    }


def detect_sme_fraud_signals(
    *,
    promoters: dict[str, Any],
    objects: dict[str, Any],
    financials: dict[str, Any],
    related_party_section: str,
    full_text: str,
) -> list[dict[str, str]]:
    """SME IPO fraud heuristic layer from the plan."""
    signals: list[dict[str, str]] = []
    text = (full_text or "").lower()
    rpt_text = (related_party_section or "").lower()

    if re.search(r"dissolved|struck off|failed venture|earlier venture", text):
        signals.append({"code": "promoter_failed_companies", "label": "Promoter background mentions dissolved or failed companies"})

    rpt_pct_match = re.search(r"related party[^%]{0,80}(\d+(?:\.\d+)?)\s*%", rpt_text or text)
    if rpt_pct_match and float(rpt_pct_match.group(1)) >= 30:
        signals.append({"code": "high_related_party", "label": "Related-party transactions exceed 30% threshold"})

    if "high_gcp_allocation" in (objects.get("flags") or []):
        signals.append({"code": "high_gcp", "label": "More than 60% of fresh issue allocated to general corporate purposes"})

    if re.search(r"remuneration.{0,80}increase|enhanced remuneration", text):
        signals.append({"code": "promoter_remuneration_spike", "label": "Recent significant increase in promoter remuneration"})

    if re.search(r"emphasis of matter|qualified opinion|material uncertainty", text):
        signals.append({"code": "auditor_qualification", "label": "Auditor qualification or emphasis-of-matter paragraph"})

    if len(signals) >= 2:
        for signal in signals:
            signal["governance_alert"] = "true"
    return signals


def compute_peer_valuation(
    peers: list[dict[str, Any]],
    ipo_pe: float | None = None,
    ipo_ev_ebitda: float | None = None,
) -> dict[str, Any]:
    """Compare IPO implied multiples vs listed peer averages."""
    peer_pes = [p["pe"] for p in peers if p.get("pe") is not None]
    peer_ev = [p["ev_ebitda"] for p in peers if p.get("ev_ebitda") is not None]
    result: dict[str, Any] = {
        "ipo_pe": ipo_pe,
        "ipo_ev_ebitda": ipo_ev_ebitda,
        "peer_avg_pe": round(sum(peer_pes) / len(peer_pes), 1) if peer_pes else None,
        "peer_avg_ev_ebitda": round(sum(peer_ev) / len(peer_ev), 1) if peer_ev else None,
        "peers": peers,
        "premium_pct": None,
        "historical_note": None,
    }
    if ipo_pe and result["peer_avg_pe"]:
        result["premium_pct"] = round(100.0 * (ipo_pe - result["peer_avg_pe"]) / result["peer_avg_pe"], 1)
        premium = result["premium_pct"]
        if premium >= 40:
            result["historical_note"] = (
                "IPOs priced above 40% peer premium historically show modest listing gains "
                "and weaker 6-month returns in our 3-year backfill sample."
            )
        elif premium >= 20:
            result["historical_note"] = "IPO trades at a moderate premium to listed peers."
        elif premium <= -10:
            result["historical_note"] = "IPO appears priced at a discount to peer averages."
    return result


def compute_ipo_score(parsed: dict[str, Any], *, peer_valuation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Synthesize five dimension scores (0-100) plus composite."""
    financials = parsed.get("financials") or {}
    trends = financials.get("trends") or {}
    objects = parsed.get("objects_of_issue") or {}
    risks = parsed.get("risk_factors") or {}
    promoters = parsed.get("promoters") or {}
    fraud_signals = parsed.get("fraud_signals") or []
    kpis = parsed.get("kpi_rows") or []
    if not kpis and isinstance(parsed.get("kpis"), list):
        kpis = parsed.get("kpis") or []
    peer_valuation = peer_valuation or {}

    # Business Quality
    business = 55.0
    rev_cagr = trends.get("revenue_cagr_pct")
    if rev_cagr is not None:
        business += min(25, max(-20, rev_cagr))
    deteriorating_kpis = sum(1 for k in kpis if k.get("trend") == "deteriorating")
    business -= min(15, deteriorating_kpis * 3)
    if "margin_compression" in (financials.get("flags") or []):
        business -= 8
    business = max(0, min(100, business))

    # Valuation Fairness
    valuation = 60.0
    premium = peer_valuation.get("premium_pct")
    if premium is not None:
        valuation -= min(35, max(-15, premium * 0.6))
    valuation = max(0, min(100, valuation))

    # Management Credibility
    management = 70.0
    management -= min(20, (promoters.get("litigation_count") or 0) * 2)
    management -= min(25, len(fraud_signals) * 8)
    if objects.get("ofs_pct") and objects["ofs_pct"] >= 50:
        management -= 10
    management = max(0, min(100, management))

    # Financial Health
    financial_health = 65.0
    for flag in financials.get("flags") or []:
        if flag in {"rising_debt", "pat_decline", "revenue_decline"}:
            financial_health -= 8
    if "high_debt_repayment_allocation" in (objects.get("flags") or []):
        financial_health -= 6
    financial_health = max(0, min(100, financial_health))

    # Risk Profile (higher score = lower risk)
    risk_profile = 75.0
    total_risks = risks.get("total_count") or 0
    risk_profile -= min(25, total_risks * 0.15)
    dom = risks.get("dominant_category")
    if dom in {"regulatory", "management"}:
        risk_profile -= 10
    if risks.get("regulatory_or_management_alert"):
        risk_profile -= 8
    risk_profile = max(0, min(100, risk_profile))

    composite = round(
        0.22 * business + 0.22 * valuation + 0.18 * management + 0.20 * financial_health + 0.18 * risk_profile,
        1,
    )

    return {
        "composite_score": composite,
        "business_quality": round(business, 1),
        "valuation_fairness": round(valuation, 1),
        "management_credibility": round(management, 1),
        "financial_health": round(financial_health, 1),
        "risk_profile": round(risk_profile, 1),
        "disclaimer": (
            "ProspektLab IPO Score is a data-driven analysis tool based on DRHP disclosures. "
            "It is not investment advice or a buy/sell recommendation."
        ),
        "governance_alert": len(fraud_signals) >= 2,
        "fraud_signal_count": len(fraud_signals),
    }

"""BlindSpot generator — "what aren't we asking?"

Takes the orchestrated findings + verifier report and asks the
skeptical-analyst question: which topics that *should* be present in a
complete due-diligence packet are still missing?

Each blind spot has:
- topic: short label (e.g. "supply_chain", "customer_concentration")
- question: the question a senior analyst would ask
- queries: targeted follow-up searches the orchestrator can run

If `auto_dispatch=True`, the run_research_session loop will execute
those queries and feed the new docs through `_process_doc` so the
synthesis layer sees them. Models the second-pass "reflection" you'd
expect from a Hermes-style agent that catches its own gaps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class BlindSpot:
    topic: str
    question: str
    queries: list[str] = field(default_factory=list)
    severity: str = "medium"  # low | medium | high

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "question": self.question,
            "queries": self.queries,
            "severity": self.severity,
        }


# Topic -> (covering agent kinds, default question template, query template)
_TOPIC_RULES: list[dict] = [
    {
        "topic": "customer_concentration",
        "needs_kind": ("financial", "risk"),
        "needs_keyword": ("customer", "concentration", "top customer"),
        "question": "Is revenue concentrated in a handful of customers? What % from the top 1–3?",
        "queries": ["{label} customer concentration top customers percentage revenue", "{label} 10-K largest customer disclosure"],
        "severity": "high",
    },
    {
        "topic": "supply_chain",
        "needs_kind": ("risk", "macro"),
        "needs_keyword": ("supplier", "supply chain", "manufacturing", "foundry"),
        "question": "What are the supply-chain dependencies? Single-source suppliers?",
        "queries": ["{label} supply chain risk single-source supplier", "{label} foundry partner manufacturing dependency"],
        "severity": "high",
    },
    {
        "topic": "fx_exposure",
        "needs_kind": ("macro", "financial"),
        "needs_keyword": ("currency", "fx", "foreign exchange", "dollar"),
        "question": "What's the FX exposure of revenue and cost of goods?",
        "queries": ["{label} foreign exchange exposure revenue cost", "{label} currency hedging program"],
        "severity": "medium",
    },
    {
        "topic": "capital_allocation",
        "needs_kind": ("financial", "governance"),
        "needs_keyword": ("buyback", "dividend", "capex", "capital return", "share repurchase"),
        "question": "What's the capital-return story? Buybacks, dividends, capex intensity?",
        "queries": ["{label} buyback program dividend yield payout ratio", "{label} capex R&D as percent of revenue"],
        "severity": "medium",
    },
    {
        "topic": "valuation_anchor",
        "needs_kind": ("financial", "technical"),
        "needs_keyword": ("p/e", "ev/ebitda", "valuation", "multiple", "price/sales"),
        "question": "What's the current valuation vs sector / vs own history?",
        "queries": ["{label} P/E EV/EBITDA valuation multiple", "{label} forward P/E historical average"],
        "severity": "high",
    },
    {
        "topic": "guidance",
        "needs_kind": ("financial", "news"),
        "needs_keyword": ("guidance", "outlook", "forecast", "expects", "fiscal year"),
        "question": "What forward guidance has management provided?",
        "queries": ["{label} guidance fiscal year outlook revenue forecast", "{label} CFO guidance quarterly"],
        "severity": "high",
    },
    {
        "topic": "insider_activity",
        "needs_kind": ("governance",),
        "needs_keyword": ("insider", "form 4", "ceo sold", "executive buying"),
        "question": "Recent insider transactions — net buying or net selling?",
        "queries": ["{label} insider trading recent form 4 net buying selling", "{label} CEO CFO share sale purchase"],
        "severity": "medium",
    },
    {
        "topic": "short_interest",
        "needs_kind": ("technical", "community"),
        "needs_keyword": ("short interest", "short ratio", "days to cover", "float"),
        "question": "What does short interest say about smart-money positioning?",
        "queries": ["{label} short interest float days to cover", "{label} institutional short positioning"],
        "severity": "medium",
    },
    {
        "topic": "esg_controversy",
        "needs_kind": ("risk", "governance"),
        "needs_keyword": ("esg", "controversy", "boycott", "scandal", "labor", "discrimination"),
        "question": "Any ESG or reputational controversies brewing?",
        "queries": ["{label} ESG controversy scandal labor practices", "{label} boycott reputational damage"],
        "severity": "low",
    },
    {
        "topic": "options_flow",
        "needs_kind": ("technical",),
        "needs_keyword": ("options", "implied volatility", "put call ratio", "unusual options"),
        "question": "Any unusual options flow ahead of catalysts?",
        "queries": ["{label} unusual options activity put call ratio", "{label} implied volatility skew"],
        "severity": "low",
    },
]


def _findings_blob(findings: Iterable) -> str:
    parts = []
    for f in findings:
        parts.append((f.headline or "").lower())
        parts.append((f.detail or "").lower())
    return " ".join(parts)


def detect_blind_spots(
    *,
    target_label: str,
    findings: list,
    seed_docs: list | None = None,
    top_n: int = 6,
) -> list[BlindSpot]:
    """Return up to `top_n` blind spots, ranked by severity.

    A topic is a blind spot if NEITHER:
      - any finding has the required kind AND keyword, NOR
      - any seed-doc text contains the keyword.
    """
    text = _findings_blob(findings)
    if seed_docs:
        for d in seed_docs:
            text += " " + (d.title or "").lower() + " " + (d.excerpt or "").lower()

    out: list[BlindSpot] = []
    for rule in _TOPIC_RULES:
        kinds = set(rule["needs_kind"])
        kws = rule["needs_keyword"]
        covered_by_kind = any(f.kind in kinds for f in findings)
        covered_by_kw = any(k in text for k in kws)
        if covered_by_kind and covered_by_kw:
            continue
        if covered_by_kw and not covered_by_kind:
            continue
        queries = [q.format(label=target_label) for q in rule["queries"]]
        out.append(
            BlindSpot(
                topic=rule["topic"],
                question=rule["question"],
                queries=queries,
                severity=rule["severity"],
            )
        )
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda b: severity_rank.get(b.severity, 2))
    return out[:top_n]

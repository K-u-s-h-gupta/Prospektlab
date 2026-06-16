"""Forensic Governance Score — IKG-derived corporate-governance risk signal.

Fuses primary-source signals already present in the IKG into a single
0–100 risk score (higher = more risk) plus a list of evidence-carrying flags:

  - Promoter share pledge level and trend          (shp_raw)
  - Promoter holding dilution                       (shp_raw)
  - Regulatory enforcement actions                  (ikg_edges ENFORCEMENT_ACTION_AGAINST)
  - Statutory auditor instability / churn           (auditor_history_raw)
  - Board churn (recent director cessations)        (directors_raw)

Design:
  - `compute_governance_score(signals)` is a PURE function (no DB) → unit-testable.
  - `GovernanceScorer.score_company(cin)` fetches signals from Postgres then calls it.
  - Every flag carries `evidence` with the source table/value so the score is
    citation-grade (the provenance moat made consumable).

Raises `GovernanceLookupError` on DB/infrastructure failure so callers can
distinguish "could not look up" from "no governance risk found".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from finagent.ikg.db import connect_postgres, get_database_url

logger = logging.getLogger("finagent.ikg.governance_score")


class GovernanceLookupError(Exception):
    """Raised when governance scoring fails due to a DB/infrastructure error."""


# ── Risk band thresholds (composite score) ───────────────────────────────────
BAND_LOW = 25.0
BAND_MODERATE = 50.0
BAND_ELEVATED = 75.0

# ── Signal weights (sum need not be 1.0; composite is clamped to 0–100) ───────
_WEIGHTS = {
    "pledge": 0.30,
    "promoter_dilution": 0.15,
    "enforcement": 0.30,
    "auditor_instability": 0.15,
    "board_churn": 0.10,
}


@dataclass
class GovernanceFlag:
    code: str
    severity: str          # "info" | "watch" | "high"
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class GovernanceResult:
    cin: str
    score: float                       # 0–100 composite risk (higher = worse)
    band: str                          # LOW | MODERATE | ELEVATED | HIGH
    subscores: dict[str, float]
    flags: list[GovernanceFlag]
    coverage: dict[str, bool]          # which signals had data
    computed_at: str


def _band(score: float) -> str:
    if score < BAND_LOW:
        return "LOW"
    if score < BAND_MODERATE:
        return "MODERATE"
    if score < BAND_ELEVATED:
        return "ELEVATED"
    return "HIGH"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Pure scoring core (no DB — unit-testable) ─────────────────────────────────

def compute_governance_score(signals: dict[str, Any], *, cin: str = "", computed_at: str = "") -> GovernanceResult:
    """Compute the composite governance risk score from pre-fetched signals.

    signals shape:
      {
        "pledge_quarters": [{"quarter","total_pledge_pct","total_promoter_holding_pct","source_url","as_on_date"}...],  # newest first
        "enforcement": [{"violation_type","penalty_amount_inr","order_date","status","pdf_url"}...],
        "auditors": [{"auditor_name","fiscal_year","source_url"}...],                                                   # newest first
        "board": {"recent_cessations": int, "total": int},
      }
    """
    subscores: dict[str, float] = {}
    flags: list[GovernanceFlag] = []
    coverage: dict[str, bool] = {
        "pledge": False, "promoter_dilution": False, "enforcement": False,
        "auditor_instability": False, "board_churn": False,
    }

    # 1) Pledge level + trend
    pledge_q = signals.get("pledge_quarters") or []
    if pledge_q:
        coverage["pledge"] = True
        coverage["promoter_dilution"] = True
        latest = pledge_q[0]
        latest_pledge = _num(latest.get("total_pledge_pct")) or 0.0
        # Risk ramps: 0% → 0, 50%+ → 100
        pledge_risk = _clamp(latest_pledge * 2.0)
        # Trend bump: pledge rose vs an earlier quarter
        if len(pledge_q) > 1:
            prior_pledge = _num(pledge_q[1].get("total_pledge_pct")) or 0.0
            if latest_pledge - prior_pledge >= 5.0:
                pledge_risk = _clamp(pledge_risk + 15.0)
                flags.append(GovernanceFlag(
                    code="PLEDGE_RISING",
                    severity="high",
                    detail=f"Promoter pledge rose {prior_pledge:.1f}% → {latest_pledge:.1f}% ({pledge_q[1].get('quarter')} → {latest.get('quarter')})",
                    evidence={"source_table": "shp_raw", "source_url": latest.get("source_url"),
                              "from_pct": prior_pledge, "to_pct": latest_pledge, "as_on_date": str(latest.get("as_on_date"))},
                ))
        subscores["pledge"] = pledge_risk
        if latest_pledge >= 50.0:
            flags.append(GovernanceFlag(
                code="PLEDGE_HIGH",
                severity="high",
                detail=f"Promoter pledge at {latest_pledge:.1f}% of holding",
                evidence={"source_table": "shp_raw", "source_url": latest.get("source_url"),
                          "value_pct": latest_pledge, "quarter": latest.get("quarter")},
            ))
        elif latest_pledge >= 25.0:
            flags.append(GovernanceFlag(
                code="PLEDGE_ELEVATED", severity="watch",
                detail=f"Promoter pledge at {latest_pledge:.1f}% of holding",
                evidence={"source_table": "shp_raw", "value_pct": latest_pledge, "quarter": latest.get("quarter")},
            ))

        # Promoter dilution over the available window
        oldest_hold = _num(pledge_q[-1].get("total_promoter_holding_pct"))
        latest_hold = _num(latest.get("total_promoter_holding_pct"))
        dilution_risk = 0.0
        if oldest_hold is not None and latest_hold is not None:
            drop = oldest_hold - latest_hold
            if drop > 0:
                dilution_risk = _clamp(drop * 5.0)  # 20pp drop → 100
            if drop >= 5.0:
                flags.append(GovernanceFlag(
                    code="PROMOTER_DILUTION", severity="watch",
                    detail=f"Promoter holding fell {oldest_hold:.1f}% → {latest_hold:.1f}% over {len(pledge_q)} quarters",
                    evidence={"source_table": "shp_raw", "from_pct": oldest_hold, "to_pct": latest_hold,
                              "quarters": len(pledge_q)},
                ))
        subscores["promoter_dilution"] = dilution_risk

    # 2) Enforcement actions
    enforcement = signals.get("enforcement") or []
    if enforcement is not None and signals.get("enforcement") is not None:
        coverage["enforcement"] = True
    active = [e for e in enforcement if str(e.get("status") or "active").lower() != "reversed"]
    if active:
        # Each active order: base 30, +penalty weighting, capped
        enf_risk = 0.0
        max_penalty = 0.0
        for e in active:
            enf_risk += 30.0
            pen = _num(e.get("penalty_amount_inr")) or 0.0
            max_penalty = max(max_penalty, pen)
        enf_risk = _clamp(enf_risk)
        subscores["enforcement"] = enf_risk
        worst = max(active, key=lambda e: _num(e.get("penalty_amount_inr")) or 0.0)
        flags.append(GovernanceFlag(
            code="ENFORCEMENT_ACTION", severity="high",
            detail=f"{len(active)} active regulatory enforcement action(s); largest penalty ₹{max_penalty:,.0f}",
            evidence={"source_table": "enforcement_raw", "count": len(active),
                      "violation_type": worst.get("violation_type"), "order_date": str(worst.get("order_date")),
                      "pdf_url": worst.get("pdf_url")},
        ))
    else:
        subscores.setdefault("enforcement", 0.0)

    # 3) Auditor instability
    auditors = signals.get("auditors")
    if auditors is not None:
        coverage["auditor_instability"] = True
        distinct = {str(a.get("auditor_name") or "").strip().upper() for a in auditors if a.get("auditor_name")}
        n_fy = len({str(a.get("fiscal_year") or "") for a in auditors if a.get("fiscal_year")})
        aud_risk = 0.0
        # 2+ distinct auditors across a short window = churn
        if len(distinct) >= 3:
            aud_risk = 80.0
        elif len(distinct) == 2:
            aud_risk = 50.0
        subscores["auditor_instability"] = aud_risk
        if len(distinct) >= 2 and n_fy <= 4:
            flags.append(GovernanceFlag(
                code="AUDITOR_CHURN", severity="high" if len(distinct) >= 3 else "watch",
                detail=f"{len(distinct)} distinct statutory auditors across {max(n_fy,1)} fiscal year(s)",
                evidence={"source_table": "auditor_history_raw", "distinct_auditors": sorted(distinct),
                          "fiscal_years": n_fy},
            ))

    # 4) Board churn
    board = signals.get("board")
    if board is not None:
        coverage["board_churn"] = True
        total = int(board.get("total") or 0)
        recent = int(board.get("recent_cessations") or 0)
        churn_risk = 0.0
        if total > 0:
            ratio = recent / total
            churn_risk = _clamp(ratio * 200.0)  # 50% of board leaving in 12m → 100
            if ratio >= 0.25 and recent >= 2:
                flags.append(GovernanceFlag(
                    code="BOARD_CHURN", severity="watch",
                    detail=f"{recent} of {total} board members departed in last 12 months",
                    evidence={"source_table": "directors_raw", "recent_cessations": recent, "board_size": total},
                ))
        subscores["board_churn"] = churn_risk

    # Composite: weight only the signals we have coverage for, renormalized.
    active_weight = 0.0
    weighted = 0.0
    for key, w in _WEIGHTS.items():
        cov_key = key
        if not coverage.get(cov_key, False):
            continue
        weighted += subscores.get(key, 0.0) * w
        active_weight += w
    composite = _clamp(weighted / active_weight) if active_weight > 0 else 0.0

    flags.sort(key=lambda f: {"high": 0, "watch": 1, "info": 2}.get(f.severity, 3))

    return GovernanceResult(
        cin=cin,
        score=round(composite, 1),
        band=_band(composite),
        subscores={k: round(v, 1) for k, v in subscores.items()},
        flags=flags,
        coverage=coverage,
        computed_at=computed_at,
    )


# ── DB-backed scorer ──────────────────────────────────────────────────────────

class GovernanceScorer:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = get_database_url(database_url)

    def _connect(self) -> Any:
        from psycopg.rows import dict_row
        return connect_postgres(self.database_url, row_factory=dict_row, connect_timeout=5)

    def _fetch_signals(self, cin: str) -> dict[str, Any]:
        signals: dict[str, Any] = {}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select quarter, total_pledge_pct, total_promoter_holding_pct, source_url, as_on_date
                    from shp_raw
                    where cin = %s
                    order by as_on_date desc nulls last, quarter desc
                    limit 8
                    """,
                    (cin,),
                )
                signals["pledge_quarters"] = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    """
                    select v.properties as properties
                    from ikg_edges e
                    join ikg_vertices v on v.vertex_id = e.from_vertex_id
                    where e.label = 'ENFORCEMENT_ACTION_AGAINST'
                      and e.to_vertex_id = %s
                    """,
                    (f"company:{cin}",),
                )
                enf: list[dict[str, Any]] = []
                for r in cur.fetchall():
                    props = r.get("properties") or {}
                    enf.append({
                        "violation_type": props.get("violation_type"),
                        "penalty_amount_inr": props.get("penalty_amount_inr"),
                        "order_date": props.get("order_date"),
                        "status": props.get("status", "active"),
                        "pdf_url": props.get("pdf_url"),
                    })
                signals["enforcement"] = enf

                cur.execute(
                    """
                    select auditor_name, fiscal_year, source_url
                    from auditor_history_raw
                    where cin = %s and role = 'statutory_auditor'
                    order by fiscal_year desc
                    limit 8
                    """,
                    (cin,),
                )
                signals["auditors"] = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    """
                    select
                      count(*) filter (
                        where cessation_date is not null
                          and cessation_date > (now() - interval '12 months')
                      ) as recent_cessations,
                      count(*) as total
                    from directors_raw
                    where cin = %s
                    """,
                    (cin,),
                )
                row = cur.fetchone() or {}
                signals["board"] = {"recent_cessations": row.get("recent_cessations") or 0,
                                    "total": row.get("total") or 0}
        return signals

    def score_company(self, cin: str) -> GovernanceResult | None:
        """Score one company by CIN. Returns None if no governance data exists.
        Raises GovernanceLookupError on DB failure."""
        from datetime import datetime, timezone
        cin = (cin or "").upper().strip()
        if not cin or not self.database_url:
            return None
        try:
            signals = self._fetch_signals(cin)
        except Exception as exc:
            raise GovernanceLookupError(f"Governance scoring failed for {cin}: {exc}") from exc

        has_any = bool(
            signals.get("pledge_quarters") or signals.get("enforcement")
            or signals.get("auditors") or (signals.get("board") or {}).get("total")
        )
        if not has_any:
            return None
        return compute_governance_score(
            signals, cin=cin, computed_at=datetime.now(timezone.utc).isoformat()
        )


_scorer: GovernanceScorer | None = None


def get_governance_scorer() -> GovernanceScorer:
    global _scorer
    if _scorer is None:
        _scorer = GovernanceScorer()
    return _scorer


def result_to_dict(result: GovernanceResult) -> dict[str, Any]:
    return {
        "cin": result.cin,
        "score": result.score,
        "band": result.band,
        "subscores": result.subscores,
        "flags": [
            {"code": f.code, "severity": f.severity, "detail": f.detail, "evidence": f.evidence}
            for f in result.flags
        ],
        "coverage": result.coverage,
        "computed_at": result.computed_at,
    }

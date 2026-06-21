"""IGS Phase B — temporal + graph feature builder.

Materialises ``company_features`` from the IKG. Set-based: each feature group is one
query over all target companies, merged by CIN, then bulk-upserted. The pledge-
trajectory maths is a pure function so it is unit-testable without a database.

Enforcement proximity uses the edges the Phase-0 fix populated:
  - hop 0: company has a direct ENFORCEMENT_ACTION_AGAINST edge
  - hop 1: a director of the company is named in any SEBI order
  - else: null (2-hop community proximity is a Memgraph-MAGE extension, Phase B+)
"""

from __future__ import annotations

import logging
from typing import Any

from finagent.ikg.db import connect_postgres, get_database_url

logger = logging.getLogger("finagent.ikg.igs.feature_builder")

FEATURE_VERSION = "igs_features_v1"


# ── Pure pledge-trajectory maths (no DB — unit-testable) ──────────────────────

def _slope(values: list[float]) -> float | None:
    """Least-squares slope of evenly-spaced values (oldest→newest). Δ per step."""
    n = len(values)
    if n < 2:
        return None
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values)) / denom


def compute_pledge_features(quarters_newest_first: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute pledge/holding trajectory features from SHP quarters (newest first)."""
    def _num(v: Any) -> float | None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    q = [x for x in quarters_newest_first if x]
    out: dict[str, Any] = {
        "pledge_pct": None, "pledge_pct_qoq_delta": None, "pledge_slope_4q": None,
        "pledge_accel": None, "promoter_holding_pct": None, "holding_dilution_4q": None,
        "pledge_quarters_observed": len(q),
    }
    if not q:
        return out
    pledges = [_num(x.get("total_pledge_pct")) for x in q]
    holdings = [_num(x.get("total_promoter_holding_pct")) for x in q]
    out["pledge_pct"] = pledges[0]
    out["promoter_holding_pct"] = holdings[0]
    if len(q) >= 2 and pledges[0] is not None and pledges[1] is not None:
        out["pledge_pct_qoq_delta"] = round(pledges[0] - pledges[1], 3)

    # Oldest→newest series of the last up-to-4 quarters for slope/accel.
    series = [p for p in reversed(pledges[:4]) if p is not None]
    if len(series) >= 2:
        out["pledge_slope_4q"] = round(_slope(series) or 0.0, 4)
    # Acceleration = slope(recent half) − slope(older half) across last up-to-4.
    if len(series) >= 4:
        recent = _slope(series[2:]) or 0.0
        older = _slope(series[:2]) or 0.0
        out["pledge_accel"] = round(recent - older, 4)

    hold_series = [h for h in holdings[:4] if h is not None]
    if len(hold_series) >= 2:
        out["holding_dilution_4q"] = round(hold_series[-1] - hold_series[0], 3)
    return out


# ── DB-backed set-based builder ───────────────────────────────────────────────

_COMPANY_FEATURES_DDL = """
create table if not exists company_features (
    cin text not null, as_of_date date not null, quarter text,
    pledge_pct numeric, pledge_pct_qoq_delta numeric, pledge_slope_4q numeric,
    pledge_accel numeric, promoter_holding_pct numeric, holding_dilution_4q numeric,
    pledge_quarters_observed int,
    director_count int, board_churn_12m numeric, recent_cessations_12m int,
    own_enforcement_count int, director_enforcement_count int, enforcement_proximity_hops int,
    auditor_count_5y int, mid_term_auditor_change boolean,
    rpt_party_count int, rpt_relationship_types int,
    beneish_m_score numeric, accrual_ratio numeric,
    feature_version text not null default 'igs_features_v1',
    computed_at timestamptz not null default now(),
    primary key (cin, as_of_date)
);
create index if not exists idx_company_features_asof on company_features (as_of_date);
create index if not exists idx_company_features_cin on company_features (cin);
"""


def _target_cins(cur: Any, cins: set[str] | None) -> list[str]:
    if cins:
        return [c for c in cins if c]
    cur.execute(
        "select cin from ikg_company_master where listing_status ilike 'listed' and cin is not null"
    )
    return [r["cin"] for r in cur.fetchall()]


def build_company_features(
    database_url: str | None = None,
    cins: set[str] | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Compute and upsert company_features for the target companies."""
    db_url = get_database_url(database_url)
    if not db_url:
        return {"success": False, "error": "no database_url", "rows_upserted": 0}

    from datetime import date
    from psycopg.rows import dict_row

    as_of_date = as_of or date.today().isoformat()
    stats: dict[str, Any] = {"success": False, "rows_upserted": 0}
    try:
        with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.execute(_COMPANY_FEATURES_DDL)
                conn.commit()
                targets = _target_cins(cur, cins)
                if not targets:
                    return {"success": True, "rows_upserted": 0, "note": "no target cins"}
                feats: dict[str, dict[str, Any]] = {c: {"cin": c} for c in targets}

                # 1) Pledge / holding trajectory (group SHP rows in Python).
                cur.execute(
                    """
                    select cin, quarter, total_pledge_pct, total_promoter_holding_pct
                    from shp_raw
                    where cin = any(%s)
                    order by cin, fetched_at desc nulls last, quarter desc
                    """,
                    (targets,),
                )
                by_cin: dict[str, list[dict[str, Any]]] = {}
                for r in cur.fetchall():
                    by_cin.setdefault(r["cin"], []).append(r)
                for c, rows in by_cin.items():
                    pf = compute_pledge_features(rows[:8])
                    pf["quarter"] = rows[0].get("quarter") if rows else None
                    feats.setdefault(c, {"cin": c}).update(pf)

                # 2) Board: director count + recent cessations.
                cur.execute(
                    """
                    select cin,
                           count(*) as director_count,
                           count(*) filter (
                             where cessation_date is not null
                               and cessation_date > (now() - interval '12 months')
                           ) as recent_cessations_12m
                    from directors_raw where cin = any(%s) group by cin
                    """,
                    (targets,),
                )
                for r in cur.fetchall():
                    dc = int(r["director_count"] or 0)
                    rc = int(r["recent_cessations_12m"] or 0)
                    feats.setdefault(r["cin"], {"cin": r["cin"]}).update({
                        "director_count": dc,
                        "recent_cessations_12m": rc,
                        "board_churn_12m": round(rc / dc, 3) if dc else None,
                    })

                # 3) Own enforcement (direct edges into the company).
                cur.execute(
                    """
                    select replace(to_vertex_id, 'company:', '') as cin, count(*) as n
                    from ikg_edges
                    where label = 'ENFORCEMENT_ACTION_AGAINST' and to_vertex_id like 'company:%%'
                      and replace(to_vertex_id, 'company:', '') = any(%s)
                    group by 1
                    """,
                    (targets,),
                )
                for r in cur.fetchall():
                    feats.setdefault(r["cin"], {"cin": r["cin"]})["own_enforcement_count"] = int(r["n"] or 0)

                # 4) Director enforcement: company directors named in any SEBI order.
                cur.execute(
                    """
                    select replace(d.to_vertex_id, 'company:', '') as cin,
                           count(distinct d.from_vertex_id) as n
                    from ikg_edges d
                    join ikg_edges e
                      on e.to_vertex_id = d.from_vertex_id
                     and e.label = 'ENFORCEMENT_ACTION_AGAINST'
                    where d.label = 'DIRECTOR_OF' and d.to_vertex_id like 'company:%%'
                      and replace(d.to_vertex_id, 'company:', '') = any(%s)
                    group by 1
                    """,
                    (targets,),
                )
                for r in cur.fetchall():
                    feats.setdefault(r["cin"], {"cin": r["cin"]})["director_enforcement_count"] = int(r["n"] or 0)

                # 5) Auditor stability (distinct auditors / fiscal years, last 5y).
                cur.execute(
                    """
                    select cin,
                           count(distinct upper(btrim(auditor_name))) as distinct_auditors,
                           count(distinct fiscal_year) as distinct_fy
                    from auditor_history_raw
                    where cin = any(%s) and role = 'statutory_auditor'
                    group by cin
                    """,
                    (targets,),
                )
                for r in cur.fetchall():
                    da = int(r["distinct_auditors"] or 0)
                    fy = int(r["distinct_fy"] or 0)
                    feats.setdefault(r["cin"], {"cin": r["cin"]}).update({
                        "auditor_count_5y": da,
                        "mid_term_auditor_change": bool(da >= 2 and fy <= 4),
                    })

                # 6) Related-party density.
                cur.execute(
                    """
                    select replace(from_vertex_id, 'company:', '') as cin,
                           count(*) as n,
                           count(distinct properties->>'relationship') as rel_types
                    from ikg_edges
                    where label = 'RELATED_PARTY_TRANSACTION' and from_vertex_id like 'company:%%'
                      and replace(from_vertex_id, 'company:', '') = any(%s)
                    group by 1
                    """,
                    (targets,),
                )
                for r in cur.fetchall():
                    feats.setdefault(r["cin"], {"cin": r["cin"]}).update({
                        "rpt_party_count": int(r["n"] or 0),
                        "rpt_relationship_types": int(r["rel_types"] or 0),
                    })

                # Derived: enforcement proximity hops.
                for c, f in feats.items():
                    own = int(f.get("own_enforcement_count") or 0)
                    dirn = int(f.get("director_enforcement_count") or 0)
                    f["enforcement_proximity_hops"] = 0 if own else (1 if dirn else None)

                rows = list(feats.values())
                stats["rows_upserted"] = _upsert_features(cur, rows, as_of_date)
            conn.commit()
        stats["success"] = True
        stats["companies"] = len(targets)
    except Exception as exc:
        logger.error("Feature build failed: %s", exc)
        stats["error"] = str(exc)
    return stats


_FEATURE_COLUMNS = (
    "pledge_pct", "pledge_pct_qoq_delta", "pledge_slope_4q", "pledge_accel",
    "promoter_holding_pct", "holding_dilution_4q", "pledge_quarters_observed",
    "director_count", "board_churn_12m", "recent_cessations_12m",
    "own_enforcement_count", "director_enforcement_count", "enforcement_proximity_hops",
    "auditor_count_5y", "mid_term_auditor_change", "rpt_party_count", "rpt_relationship_types",
    "beneish_m_score", "accrual_ratio",
)


def _upsert_features(cur: Any, rows: list[dict[str, Any]], as_of_date: str) -> int:
    cols = ("cin", "as_of_date", "quarter", *_FEATURE_COLUMNS, "feature_version")
    placeholders = "(" + ", ".join(["%s"] * len(cols)) + ")"
    updates = ", ".join(f"{c} = excluded.{c}" for c in (*_FEATURE_COLUMNS, "quarter", "feature_version"))
    n = 0
    for f in rows:
        params = [f.get("cin"), as_of_date, f.get("quarter")]
        params += [f.get(c) for c in _FEATURE_COLUMNS]
        params.append(FEATURE_VERSION)
        cur.execute(
            f"""insert into company_features ({", ".join(cols)}) values {placeholders}
                on conflict (cin, as_of_date) do update set {updates}, computed_at = now()""",
            params,
        )
        n += 1
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import json

    print(json.dumps(build_company_features(), default=str, indent=2))

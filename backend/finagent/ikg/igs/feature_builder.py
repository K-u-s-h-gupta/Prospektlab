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
    director_other_boards int, shared_failure_director_count int, enforcement_2hop_count int,
    beneish_m_score numeric, accrual_ratio numeric,
    feature_version text not null default 'igs_features_v1',
    computed_at timestamptz not null default now(),
    primary key (cin, as_of_date)
);
create index if not exists idx_company_features_asof on company_features (as_of_date);
create index if not exists idx_company_features_cin on company_features (cin);
alter table company_features add column if not exists director_other_boards int;
alter table company_features add column if not exists shared_failure_director_count int;
alter table company_features add column if not exists enforcement_2hop_count int;
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

                # 7) Director-network contagion (the cross-company moat signal):
                #    shared directors who also sit on failed / enforced boards.
                cur.execute(
                    """
                    with tgt(cin) as (select unnest(%s::text[])),
                    co_din as (
                        select replace(e.to_vertex_id, 'company:', '') as cin, e.from_vertex_id as din
                        from ikg_edges e
                        join tgt on tgt.cin = replace(e.to_vertex_id, 'company:', '')
                        where e.label = 'DIRECTOR_OF'
                    ),
                    din_other as (
                        select e.from_vertex_id as din, replace(e.to_vertex_id, 'company:', '') as other_cin
                        from ikg_edges e where e.label = 'DIRECTOR_OF'
                    )
                    select cd.cin,
                           count(distinct dou.other_cin) filter (where dou.other_cin <> cd.cin) as other_boards,
                           count(distinct cd.din) filter (
                               where exists (select 1 from failure_events fe
                                             where fe.cin = dou.other_cin and fe.is_failure)
                           ) as shared_failure_directors,
                           count(distinct cd.din) filter (
                               where exists (select 1 from ikg_edges en
                                             where en.label = 'ENFORCEMENT_ACTION_AGAINST'
                                               and en.to_vertex_id = 'company:' || dou.other_cin)
                           ) as enf2
                    from co_din cd
                    join din_other dou on dou.din = cd.din
                    group by cd.cin
                    """,
                    (targets,),
                )
                for r in cur.fetchall():
                    feats.setdefault(r["cin"], {"cin": r["cin"]}).update({
                        "director_other_boards": int(r["other_boards"] or 0),
                        "shared_failure_director_count": int(r["shared_failure_directors"] or 0),
                        "enforcement_2hop_count": int(r["enf2"] or 0),
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
    "director_other_boards", "shared_failure_director_count", "enforcement_2hop_count",
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


def _qtrid_to_quarter_end(qtrid: int) -> str | None:
    """Map a BSE SHP quarter id → calendar quarter-end date (point-in-time axis).

    Anchored on a known recent quarter; each qtrid step is one calendar quarter.
    Anchor is configurable (IGS_SHP_ANCHOR_QTRID / IGS_SHP_ANCHOR_DATE) so it can be
    corrected without code changes.
    """
    import calendar
    from datetime import date

    try:
        anchor_qtrid = int(os.getenv("IGS_SHP_ANCHOR_QTRID", "129"))
        ay, am, _ = (int(x) for x in os.getenv("IGS_SHP_ANCHOR_DATE", "2026-03-31").split("-"))
    except Exception:
        anchor_qtrid, ay, am = 129, 2026, 3
    months_back = (anchor_qtrid - int(qtrid)) * 3
    total = (ay * 12 + (am - 1)) - months_back
    ny, nm0 = divmod(total, 12)
    nm = nm0 + 1
    if ny < 1990 or ny > 2100:
        return None
    return date(ny, nm, calendar.monthrange(ny, nm)[1]).isoformat()


def build_historical_features(
    database_url: str | None = None,
    cins: set[str] | None = None,
    quarters_back: int = 40,
) -> dict[str, Any]:
    """Build point-in-time company_features snapshots from SHP quarter history.

    For each company and each historical SHP quarter Q, write a company_features row
    dated at Q's quarter-end using only data up to Q (leak-free). This is the temporal
    training/backtest matrix that lets the model learn pre-failure pledge trajectories.
    Graph features (enforcement/RPT) are left null in historical rows — they are not
    reliably dateable yet, so they stay out to avoid look-ahead leakage.
    """
    db_url = get_database_url(database_url)
    if not db_url:
        return {"success": False, "error": "no database_url", "rows_upserted": 0}
    from psycopg.rows import dict_row

    stats: dict[str, Any] = {"success": False, "rows_upserted": 0, "companies": 0}
    try:
        with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.execute(_COMPANY_FEATURES_DDL)
                conn.commit()
                where = "where cin = any(%s)" if cins else "where cin is not null"
                params: list[Any] = [list(cins)] if cins else []
                cur.execute(
                    f"""
                    select cin,
                           coalesce((raw_json->>'qtrid')::int, null) as qtrid,
                           quarter, total_pledge_pct, total_promoter_holding_pct
                    from shp_raw
                    {where}
                    order by cin, qtrid desc nulls last
                    """,
                    params,
                )
                by_cin: dict[str, list[dict[str, Any]]] = {}
                for r in cur.fetchall():
                    if r.get("qtrid") is None:
                        continue
                    by_cin.setdefault(r["cin"], []).append(r)

                upserted = 0
                for cin, rows in by_cin.items():
                    rows.sort(key=lambda x: x["qtrid"], reverse=True)  # newest first
                    # Each distinct qtrid is one as-of snapshot; features use rows at/before it.
                    seen_q: set[int] = set()
                    for i, row in enumerate(rows):
                        q = int(row["qtrid"])
                        if q in seen_q:
                            continue
                        seen_q.add(q)
                        as_of = _qtrid_to_quarter_end(q)
                        if not as_of:
                            continue
                        window = rows[i:i + 8]  # this quarter + up to 7 prior (newest-first)
                        pf = compute_pledge_features(window)
                        pf["quarter"] = row.get("quarter")
                        _upsert_features(cur, [{"cin": cin, **pf}], as_of)
                        upserted += 1
                    conn.commit()
                stats["rows_upserted"] = upserted
                stats["companies"] = len(by_cin)
        stats["success"] = True
    except Exception as exc:
        logger.error("Historical feature build failed: %s", exc)
        stats["error"] = str(exc)
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import argparse
    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--historical", action="store_true", help="Build point-in-time snapshots")
    args = parser.parse_args()
    if args.historical:
        print(json.dumps(build_historical_features(), default=str, indent=2))
    else:
        print(json.dumps(build_company_features(), default=str, indent=2))

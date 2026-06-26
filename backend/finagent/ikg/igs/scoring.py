"""IGS Phase D — productionised governance scoring facade.

Blends the deterministic rules engine (``finagent.ikg.governance_score``) with the
trained predictive model (``finagent.ikg.igs.model.score_company``) into a single
composite 0–100 governance-risk signal, and materialises a dated history table
(``company_governance_scores``) the product reads from.

Design:
  - :func:`merge_scores` is a PURE function (no DB, no model import) → unit-testable.
    It keeps the GovernanceResult contract stable (composite 0–100, band, subscores,
    flags) while folding in the model's ``predicted_failure`` subscore and reasons.
  - :func:`score_all_listed` iterates listed CINs, calls the rules scorer and the model
    *defensively* (one company's failure never aborts the run), merges, and upserts.
  - The model import is LAZY and guarded: if ``igs.model`` is missing or raises, the
    pipeline degrades to rules-only and never breaks.

Band thresholds (shared with GovernanceResult): <25 LOW, <50 MODERATE, <75 ELEVATED,
else HIGH. Higher score = more governance risk.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from finagent.ikg.db import connect_postgres, get_database_url

logger = logging.getLogger(__name__)

# ── Risk band thresholds (mirror finagent.ikg.governance_score) ───────────────
BAND_LOW = 25.0
BAND_MODERATE = 50.0
BAND_ELEVATED = 75.0


def _band(score: float) -> str:
    """Map a composite 0–100 risk score to a band (higher = worse)."""
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
    """Best-effort float coercion (None / unparseable → None)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Pure merge core (no DB — unit-testable) ───────────────────────────────────

def merge_scores(
    rules: dict | None,
    model: dict | None,
    *,
    model_weight: float = 0.5,
) -> dict:
    """Combine a rules result dict with a model dict into a composite score.

    The rules dict is the output of ``governance_score.result_to_dict`` and carries
    ``score`` (0–100), ``band``, ``subscores``, ``flags``, ``coverage``. The model
    dict is the output of ``igs.model.score_company`` and carries ``predicted_risk``
    (0–100), ``probability`` (0–1), ``reasons`` (list of dicts) and ``model_version``.

    Composite semantics (deterministic):
      - both present → weighted blend ``model_risk * w + rules_score * (1 - w)``;
      - only one present → that one's score verbatim;
      - neither present → composite 0.0 (LOW), rules-only is never broken by a missing
        model.

    The returned ``subscores`` are the rules subscores plus ``predicted_failure`` (the
    model risk). The returned ``flags`` are the rules flags followed by each model
    reason mapped to an ``IGS_MODEL_SIGNAL`` flag, so the GovernanceResult flag contract
    is preserved while the predictive signal becomes citable.

    Args:
        rules: rules-engine result dict, or None if rules scoring had no data.
        model: model result dict, or None if no model contributed.
        model_weight: weight on the model risk when both are present (0–1).

    Returns:
        A dict with keys: composite_score, band, rules_score, model_risk,
        model_probability, model_version, subscores, flags.
    """
    rules = rules or None
    model = model or None
    weight = max(0.0, min(1.0, float(model_weight)))

    rules_score = _num((rules or {}).get("score")) if rules else None
    model_risk = _num((model or {}).get("predicted_risk")) if model else None
    model_probability = _num((model or {}).get("probability")) if model else None
    model_version = (model or {}).get("model_version") if model else None

    # Composite: weighted blend when both present, else whichever exists.
    if rules_score is not None and model_risk is not None:
        composite = model_risk * weight + rules_score * (1.0 - weight)
    elif model_risk is not None:
        composite = model_risk
    elif rules_score is not None:
        composite = rules_score
    else:
        composite = 0.0
    composite = round(_clamp(composite), 1)

    # Merged subscores: rules subscores + the predictive subscore.
    subscores: dict[str, Any] = {}
    if rules and isinstance(rules.get("subscores"), dict):
        subscores.update(rules["subscores"])
    if model_risk is not None:
        subscores["predicted_failure"] = round(model_risk, 1)

    # Merged flags: rules flags first, then model reasons mapped to citable flags.
    flags: list[dict[str, Any]] = []
    if rules and isinstance(rules.get("flags"), list):
        flags.extend(rules["flags"])
    for reason in (model or {}).get("reasons") or []:
        if not isinstance(reason, dict):
            continue
        evidence = reason.get("evidence")
        if not isinstance(evidence, dict):
            # Fold any non-dict metadata into evidence so nothing is lost.
            evidence = {k: v for k, v in reason.items()
                        if k not in {"severity", "detail", "code"}}
        flags.append({
            "code": "IGS_MODEL_SIGNAL",
            "severity": reason.get("severity") or "info",
            "detail": reason.get("detail") or reason.get("feature") or "Model signal",
            "evidence": evidence,
        })

    source = "rules+model" if (rules and model) else ("model" if model else "rules")

    return {
        "composite_score": composite,
        "band": _band(composite),
        "rules_score": round(rules_score, 1) if rules_score is not None else None,
        "model_risk": round(model_risk, 1) if model_risk is not None else None,
        "model_probability": model_probability,
        "model_version": model_version,
        "subscores": subscores,
        "flags": flags,
        "source": source,
    }


# ── DDL (idempotent — mirrors deployment/ikg_governance_scores.sql) ───────────

_GOVERNANCE_SCORES_DDL = """
create table if not exists company_governance_scores (
    cin               text not null,
    as_of_date        date not null,
    composite_score   numeric,
    band              text,
    rules_score       numeric,
    model_risk        numeric,
    model_probability numeric,
    model_version     text,
    subscores         jsonb not null default '{}'::jsonb,
    flags             jsonb not null default '[]'::jsonb,
    source            text,
    computed_at       timestamptz not null default now(),
    primary key (cin, as_of_date)
);
create index if not exists idx_company_governance_scores_asof
    on company_governance_scores (as_of_date);
create index if not exists idx_company_governance_scores_cin
    on company_governance_scores (cin);
"""


def ensure_scores_table(database_url: str | None = None) -> bool:
    """Ensure ``company_governance_scores`` exists. Idempotent; safe to re-run."""
    db_url = get_database_url(database_url)
    if not db_url:
        logger.warning("ensure_scores_table: no database_url configured")
        return False
    try:
        with connect_postgres(db_url, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.execute(_GOVERNANCE_SCORES_DDL)
            conn.commit()
        return True
    except Exception as exc:
        logger.error("ensure_scores_table failed: %s", exc)
        return False


# ── Defensive scorer wrappers ─────────────────────────────────────────────────

def _score_rules(cin: str) -> dict | None:
    """Run the rules engine for one CIN, returning its result dict or None."""
    try:
        from finagent.ikg.governance_score import get_governance_scorer, result_to_dict

        result = get_governance_scorer().score_company(cin)
        if result is None:
            return None
        return result_to_dict(result)
    except Exception as exc:
        logger.warning("rules scoring failed for %s: %s", cin, exc)
        return None


def _score_model(cin: str, model_path: str | None = None) -> dict | None:
    """Run the predictive model for one CIN, returning its dict or None.

    The model module may be mid-development: the import is lazy and any failure
    (missing module, untrained model, runtime error) degrades to None so scoring
    proceeds rules-only.
    """
    try:
        from finagent.ikg.igs.model import score_company  # type: ignore
    except Exception:
        return None
    try:
        try:
            result = score_company(cin, model_path=model_path)  # type: ignore[call-arg]
        except TypeError:
            # Tolerate a simpler signature score_company(cin).
            result = score_company(cin)  # type: ignore[misc]
        if result is None:
            return None
        return dict(result)
    except Exception as exc:
        logger.warning("model scoring failed for %s: %s", cin, exc)
        return None


# ── DB-backed batch scorer ────────────────────────────────────────────────────

_UPSERT_SQL = """
insert into company_governance_scores (
    cin, as_of_date, composite_score, band, rules_score, model_risk,
    model_probability, model_version, subscores, flags, source
) values (
    %(cin)s, %(as_of_date)s, %(composite_score)s, %(band)s, %(rules_score)s,
    %(model_risk)s, %(model_probability)s, %(model_version)s,
    %(subscores)s, %(flags)s, %(source)s
)
on conflict (cin, as_of_date) do update set
    composite_score   = excluded.composite_score,
    band              = excluded.band,
    rules_score       = excluded.rules_score,
    model_risk        = excluded.model_risk,
    model_probability = excluded.model_probability,
    model_version     = excluded.model_version,
    subscores         = excluded.subscores,
    flags             = excluded.flags,
    source            = excluded.source,
    computed_at       = now()
"""


def _recalibrate_bands_by_percentile(cur: Any, as_of_date: str) -> int:
    """Re-assign ``band`` by percentile of composite_score within an as_of cohort.

    The trained model ranks well (AUC ~0.79) but calibrated probabilities cluster
    below the listed-universe base rate, so absolute thresholds (25/50/75) push the
    vast majority into LOW (observed: 97.7% LOW / 6 ELEVATED). Percentile bands turn
    the model's good *ranking* into a usable distribution that always surfaces the
    relatively-riskiest names. Gated by IGS_PERCENTILE_BANDS (default on); set to 0
    to keep absolute-threshold bands.

    Cohort cut points (riskiest first): top 2% HIGH, next 8% ELEVATED, next 20%
    MODERATE, remainder LOW. Returns the number of rows updated.
    """
    if os.getenv("IGS_PERCENTILE_BANDS", "1").strip().lower() in {"0", "false", "no"}:
        return 0
    # Data-backed companies (a real model risk) are percentile-ranked among
    # THEMSELVES. Companies without a model contribution (insufficient_data →
    # rules-only) are NOT ranked — ranking a large tied block just dumps it into
    # whatever band its cumulative position lands. They are set LOW explicitly so
    # only data-backed risk ever occupies MODERATE/ELEVATED/HIGH.
    cur.execute(
        """
        with ranked as (
            select cin,
                   percent_rank() over (order by composite_score desc) as pr
            from company_governance_scores
            where as_of_date = %(as_of)s and model_risk is not null
        )
        update company_governance_scores g set band = case
            when r.pr <= 0.02 then 'HIGH'
            when r.pr <= 0.10 then 'ELEVATED'
            when r.pr <= 0.30 then 'MODERATE'
            else 'LOW' end
        from ranked r
        where g.cin = r.cin and g.as_of_date = %(as_of)s
        """,
        {"as_of": as_of_date},
    )
    ranked_rows = cur.rowcount or 0
    cur.execute(
        """
        update company_governance_scores set band = 'LOW'
        where as_of_date = %(as_of)s and model_risk is null
        """,
        {"as_of": as_of_date},
    )
    return ranked_rows


def _listed_cins(cur: Any, limit: int | None) -> list[str]:
    """Return listed CINs from the company master (optionally capped)."""
    sql = (
        "select cin from ikg_company_master "
        "where listing_status ilike 'listed' and cin is not null "
        "order by cin"
    )
    if limit:
        sql += " limit %s"
        cur.execute(sql, (int(limit),))
    else:
        cur.execute(sql)
    return [r["cin"] for r in cur.fetchall() if r.get("cin")]


def score_all_listed(
    database_url: str | None = None,
    as_of: str | None = None,
    limit: int | None = None,
    model_path: str | None = None,
) -> dict[str, Any]:
    """Score every listed company and upsert into ``company_governance_scores``.

    For each CIN the rules scorer and the model are both invoked defensively; their
    outputs are merged by :func:`merge_scores` and upserted. Errors on a single company
    are counted and skipped, never aborting the loop. The transaction is committed
    periodically so a long run is resumable.

    Args:
        database_url: explicit DB URL; falls back to the configured IKG URL.
        as_of: ISO date for the score snapshot; defaults to today (UTC).
        limit: optional cap on the number of companies (for smoke runs).
        model_path: optional path forwarded to the model scorer.

    Returns:
        {"success", "scored", "with_model", "errors", "as_of"} stats dict.
    """
    import json
    from datetime import date

    db_url = get_database_url(database_url)
    as_of_date = as_of or date.today().isoformat()
    stats: dict[str, Any] = {
        "success": False, "scored": 0, "with_model": 0, "errors": 0, "as_of": as_of_date,
    }
    if not db_url:
        stats["error"] = "no database_url"
        return stats

    from psycopg.rows import dict_row

    commit_every = 200
    try:
        with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.execute(_GOVERNANCE_SCORES_DDL)
                conn.commit()
                targets = _listed_cins(cur, limit)
                if not targets:
                    stats["success"] = True
                    stats["note"] = "no listed cins"
                    return stats

                for i, cin in enumerate(targets, start=1):
                    try:
                        rules = _score_rules(cin)
                        model = _score_model(cin, model_path=model_path)
                        if rules is None and model is None:
                            # Nothing to record for this company.
                            continue
                        merged = merge_scores(rules, model)
                        cur.execute(_UPSERT_SQL, {
                            "cin": cin,
                            "as_of_date": as_of_date,
                            "composite_score": merged["composite_score"],
                            "band": merged["band"],
                            "rules_score": merged["rules_score"],
                            "model_risk": merged["model_risk"],
                            "model_probability": merged["model_probability"],
                            "model_version": merged["model_version"],
                            "subscores": json.dumps(merged["subscores"], default=str),
                            "flags": json.dumps(merged["flags"], default=str),
                            "source": merged["source"],
                        })
                        stats["scored"] += 1
                        if model is not None:
                            stats["with_model"] += 1
                    except Exception as exc:
                        stats["errors"] += 1
                        logger.warning("scoring failed for %s: %s", cin, exc)

                    if i % commit_every == 0:
                        conn.commit()
                conn.commit()
                # Turn the model's ranking into a usable band distribution.
                try:
                    rebanded = _recalibrate_bands_by_percentile(cur, as_of_date)
                    if rebanded:
                        stats["rebanded"] = rebanded
                    conn.commit()
                except Exception as exc:
                    logger.warning("band recalibration skipped: %s", exc)
            conn.commit()
        stats["success"] = True
        stats["companies"] = len(targets)
    except Exception as exc:
        logger.error("score_all_listed failed: %s", exc)
        stats["error"] = str(exc)
    return stats


def get_latest_score(cin: str, database_url: str | None = None) -> dict | None:
    """Return the most recent governance score row for a CIN, or None.

    Args:
        cin: company identification number.
        database_url: explicit DB URL; falls back to the configured IKG URL.

    Returns:
        A dict of the latest ``company_governance_scores`` row, or None if absent.
    """
    cin = (cin or "").upper().strip()
    db_url = get_database_url(database_url)
    if not cin or not db_url:
        return None
    from psycopg.rows import dict_row

    try:
        with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select cin, as_of_date, composite_score, band, rules_score,
                           model_risk, model_probability, model_version,
                           subscores, flags, source, computed_at
                    from company_governance_scores
                    where cin = %s
                    order by as_of_date desc
                    limit 1
                    """,
                    (cin,),
                )
                row = cur.fetchone()
        return dict(row) if row else None
    except Exception as exc:
        logger.warning("get_latest_score failed for %s: %s", cin, exc)
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import argparse
    import json

    parser = argparse.ArgumentParser(description="IGS Phase D — score listed companies")
    parser.add_argument("--limit", type=int, default=None, help="cap number of companies")
    parser.add_argument("--as-of", dest="as_of", default=None, help="ISO score date (YYYY-MM-DD)")
    parser.add_argument("--model-path", dest="model_path", default=None, help="optional model path")
    args = parser.parse_args()

    print(json.dumps(
        score_all_listed(as_of=args.as_of, limit=args.limit, model_path=args.model_path),
        default=str, indent=2,
    ))

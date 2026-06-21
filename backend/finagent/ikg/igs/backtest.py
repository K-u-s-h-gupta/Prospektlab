"""IGS Phase B — date-shifted backtest harness.

Evaluates the predictive governance-failure model with a walk-forward / date-shifted
protocol: at each evaluation date ``T`` the model is trained on data strictly before
``T`` and scored against the labelled set as of ``T``. The label is 1 when a CIN has a
*datable* failure within the horizon ``(T, T+horizon_months]`` or an *undatable*
``is_failure`` row (many MCA struck-off rows carry no ``event_date``), else 0.

The metric core (``roc_auc``, ``precision_recall_at_threshold``, ``lead_time_months``)
is pure Python — no numpy/sklearn — so it imports and unit-tests with zero third-party
libraries installed. Heavy/optional imports (psycopg, the IGS model) are guarded inside
functions; the module always imports and ``py_compile``s even while ``igs/model.py`` is
mid-development.

The model interface is imported lazily and defensively from ``finagent.ikg.igs.model``:
``train_failure_model``, ``IGSModel``, ``feature_vector`` and ``FEATURE_COLUMNS``. If any
symbol is absent the harness degrades to ``{"success": False, "reason": ...}`` rather than
raising.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)


# ── Pure, dependency-free metric functions (unit-testable) ────────────────────


def roc_auc(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    """Area under the ROC curve via the rank-based Mann–Whitney U statistic.

    Equivalent to the probability that a randomly chosen positive outranks a
    randomly chosen negative. Tied scores contribute 0.5 (average ranks). Returns
    ``0.5`` for any degenerate input (length mismatch, empty, or a single class),
    which is the uninformative baseline.

    >>> roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9])
    1.0
    >>> roc_auc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1])
    0.0
    """
    if y_true is None or y_score is None:
        return 0.5
    if len(y_true) != len(y_score) or len(y_true) == 0:
        return 0.5

    n_pos = sum(1 for t in y_true if t)
    n_neg = len(y_true) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5

    # Average ranks (1-based), ties share the mean of their rank block.
    order = sorted(range(len(y_score)), key=lambda i: y_score[i])
    ranks = [0.0] * len(y_score)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and y_score[order[j + 1]] == y_score[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # mean of 1-based ranks in [i, j]
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank
        i = j + 1

    sum_ranks_pos = sum(ranks[i] for i in range(len(y_true)) if y_true[i])
    # Mann–Whitney U for the positive class.
    u_pos = sum_ranks_pos - n_pos * (n_pos + 1) / 2.0
    return u_pos / (n_pos * n_neg)


def precision_recall_at_threshold(
    y_true: Sequence[int], y_score: Sequence[float], threshold: float
) -> dict[str, Any]:
    """Confusion-matrix counts plus precision/recall at a decision threshold.

    A sample is predicted positive when ``score >= threshold``. Precision and
    recall are ``None`` when their denominator is zero (no predicted positives /
    no actual positives) so callers can distinguish "0.0" from "undefined".

    Returns ``{precision, recall, f1, tp, fp, fn, tn, threshold, n}``.
    """
    tp = fp = fn = tn = 0
    n = min(len(y_true), len(y_score)) if (y_true and y_score) else 0
    for i in range(n):
        predicted_pos = y_score[i] >= threshold
        actual_pos = bool(y_true[i])
        if predicted_pos and actual_pos:
            tp += 1
        elif predicted_pos and not actual_pos:
            fp += 1
        elif not predicted_pos and actual_pos:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1: Optional[float] = 2 * precision * recall / (precision + recall)
    else:
        f1 = None

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "threshold": threshold,
        "n": n,
    }


def _to_date(value: Any) -> Optional[date]:
    """Coerce a date / datetime / ISO-ish string to a ``date`` (or ``None``)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def lead_time_months(
    predicted_dates_or_index: Sequence[Any],
    event_dates: Sequence[Any],
) -> dict[str, Any]:
    """Summarise how far ahead positive predictions were flagged.

    ``predicted_dates_or_index`` are the as-of / observation dates at which each
    positive was flagged; ``event_dates`` are the corresponding realised failure
    dates (``None`` is common — many MCA labels lack a date). Lead time is the
    month gap ``event - observed`` for each datable pair. Reports ``count`` of
    datable pairs, ``coverage`` (datable / total), and min/median/mean/max in
    months. Undatable events are counted but excluded from the statistics rather
    than dropped silently.

    Returns a dict that is JSON-safe and never raises on ragged / ``None`` input.
    """
    obs = list(predicted_dates_or_index or [])
    evt = list(event_dates or [])
    total = max(len(obs), len(evt))

    leads: list[float] = []
    undatable = 0
    for i in range(total):
        observed = _to_date(obs[i]) if i < len(obs) else None
        realised = _to_date(evt[i]) if i < len(evt) else None
        if realised is None:
            undatable += 1
            continue
        if observed is None:
            # Can't compute a lead without the reference observation date.
            undatable += 1
            continue
        months = (realised.year - observed.year) * 12 + (realised.month - observed.month)
        # Fractional month from day offset for a smoother summary.
        months += (realised.day - observed.day) / 30.0
        leads.append(months)

    if not leads:
        return {
            "count": 0,
            "datable_events": 0,
            "undatable_events": undatable,
            "coverage": 0.0 if total else None,
            "min_months": None,
            "median_months": None,
            "mean_months": None,
            "max_months": None,
            "positive_lead_share": None,
        }

    srt = sorted(leads)
    mid = len(srt) // 2
    median = srt[mid] if len(srt) % 2 else (srt[mid - 1] + srt[mid]) / 2.0
    positive_lead = sum(1 for x in leads if x > 0)

    return {
        "count": len(leads),
        "datable_events": len(leads),
        "undatable_events": undatable,
        "coverage": (len(leads) / total) if total else None,
        "min_months": round(min(leads), 2),
        "median_months": round(median, 2),
        "mean_months": round(sum(leads) / len(leads), 2),
        "max_months": round(max(leads), 2),
        "positive_lead_share": round(positive_lead / len(leads), 3),
    }


# ── Model-interface shim (defensive lazy import) ──────────────────────────────


def _load_model_module() -> dict[str, Any]:
    """Best-effort import of ``finagent.ikg.igs.model``.

    Returns a dict of whichever of ``train_failure_model``, ``IGSModel``,
    ``feature_vector``, ``FEATURE_COLUMNS`` are present. Always returns a dict so
    callers can probe membership without a try/except. ``feature_columns`` falls
    back to ``feature_builder``'s materialised column list when the model module
    does not (yet) export ``FEATURE_COLUMNS``.
    """
    found: dict[str, Any] = {}
    try:
        from finagent.ikg.igs import model as _model  # type: ignore
    except Exception as exc:  # ImportError or mid-development SyntaxError, etc.
        logger.warning("igs.model not importable yet: %s", exc)
        _model = None  # type: ignore[assignment]

    if _model is not None:
        for name in ("train_failure_model", "IGSModel", "feature_vector", "FEATURE_COLUMNS"):
            if hasattr(_model, name):
                found[name] = getattr(_model, name)

    if "FEATURE_COLUMNS" not in found:
        try:
            from finagent.ikg.igs.feature_builder import _FEATURE_COLUMNS

            found["FEATURE_COLUMNS"] = list(_FEATURE_COLUMNS)
            logger.info("Using feature_builder._FEATURE_COLUMNS as fallback feature set")
        except Exception:  # noqa: BLE001 - best effort only
            pass
    return found


def _feature_vector(model_api: dict[str, Any], row: dict[str, Any]) -> list[float]:
    """Build a numeric feature vector for one ``company_features`` row.

    Prefers ``model.feature_vector`` when available; otherwise reads the columns
    in ``FEATURE_COLUMNS`` order, coercing booleans/None to floats. Kept in this
    module so scoring works even if the model only exposes a bare predictor.
    """
    fv = model_api.get("feature_vector")
    if callable(fv):
        try:
            return list(fv(row))
        except Exception as exc:  # noqa: BLE001
            logger.debug("model.feature_vector failed, falling back: %s", exc)

    columns = model_api.get("FEATURE_COLUMNS") or []
    vec: list[float] = []
    for col in columns:
        val = row.get(col)
        if isinstance(val, bool):
            vec.append(1.0 if val else 0.0)
        elif val is None:
            vec.append(0.0)
        else:
            try:
                vec.append(float(val))
            except (TypeError, ValueError):
                vec.append(0.0)
    return vec


def _score_rows(
    model_api: dict[str, Any],
    model: Any,
    rows: list[dict[str, Any]],
) -> Optional[list[float]]:
    """Score feature rows with a trained model, trying known predictor APIs.

    The IGS ``IGSModel`` exposes per-row ``predict_proba(features: dict) -> float``
    (a single positive-class probability) and ``risk_score(features) -> float`` —
    so a row *dict* is passed, not a vector. This is attempted first. For an
    unknown/foreign model we fall back to vector-based ``predict_proba`` /
    ``predict`` and a ``score_row`` convenience API. Returns ``None`` when no
    known entrypoint works, so the caller can fail the fold cleanly.
    """
    if model is None:
        return None

    # 1) IGSModel-style per-row dict scorer returning a scalar probability.
    if hasattr(model, "predict_proba"):
        try:
            scores: list[float] = []
            per_row_ok = True
            for r in rows:
                p = model.predict_proba(r)  # IGSModel: dict -> float
                if isinstance(p, (list, tuple)):
                    # Foreign sklearn-style proba; this branch is per-row so a
                    # single 2-class pair is expected -> take positive column.
                    scores.append(float(p[-1]))
                else:
                    scores.append(float(p))
            if per_row_ok and len(scores) == len(rows):
                return scores
        except Exception as exc:  # noqa: BLE001
            logger.debug("model.predict_proba(row) failed, trying fallbacks: %s", exc)

    # 2) IGSModel.risk_score (0..100) — normalise to a 0..1 ordering score.
    if hasattr(model, "risk_score"):
        try:
            return [float(model.risk_score(r)) / 100.0 for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.debug("model.risk_score failed: %s", exc)

    # 3) Per-row convenience API (governance_score style).
    if hasattr(model, "score_row"):
        try:
            return [float(model.score_row(r)) for r in rows]
        except Exception as exc:  # noqa: BLE001
            logger.debug("model.score_row failed: %s", exc)

    # 4) Foreign batch/vector predictor.
    vectors = [_feature_vector(model_api, r) for r in rows]
    if hasattr(model, "predict"):
        try:
            return [float(v) for v in model.predict(vectors)]
        except Exception as exc:  # noqa: BLE001
            logger.debug("model.predict failed: %s", exc)

    return None


# ── DB-backed fold assembly ───────────────────────────────────────────────────


def _fetch_features_asof(cur: Any, as_of: str) -> list[dict[str, Any]]:
    """Latest ``company_features`` row per CIN at/just before ``as_of``."""
    cur.execute(
        """
        select distinct on (cin) *
        from company_features
        where as_of_date <= %s
        order by cin, as_of_date desc
        """,
        (as_of,),
    )
    return list(cur.fetchall())


def _fetch_outcomes(
    cur: Any, as_of: str, horizon_end: str
) -> dict[str, dict[str, Any]]:
    """Map CIN → outcome for the horizon window.

    Positive when a CIN has a *datable* failure in ``(as_of, horizon_end]`` or an
    *undatable* ``is_failure`` row (event_date is NULL). The earliest in-window
    event date is retained for lead-time reporting.
    """
    cur.execute(
        """
        select cin,
               bool_or(
                   is_failure and (
                       (event_date is not null and event_date > %s and event_date <= %s)
                       or event_date is null
                   )
               ) as is_positive,
               min(event_date) filter (
                   where is_failure and event_date is not null
                     and event_date > %s and event_date <= %s
               ) as first_event_date
        from failure_events
        group by cin
        """,
        (as_of, horizon_end, as_of, horizon_end),
    )
    outcomes: dict[str, dict[str, Any]] = {}
    for r in cur.fetchall():
        outcomes[r["cin"]] = {
            "is_positive": bool(r.get("is_positive")),
            "first_event_date": r.get("first_event_date"),
        }
    return outcomes


def _add_months(iso_date: str, months: int) -> str:
    """Add ``months`` to an ISO date string, clamping the day to month length."""
    d = _to_date(iso_date) or date.today()
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    # Clamp day to the last valid day of the target month.
    if month == 12:
        next_first = date(year + 1, 1, 1)
    else:
        next_first = date(year, month + 1, 1)
    from datetime import timedelta

    last_day = (next_first - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day)).isoformat()


def _default_as_of_dates(cur: Any) -> list[str]:
    """Distinct ``as_of_date`` values present in ``company_features`` (ascending)."""
    cur.execute("select distinct as_of_date from company_features order by as_of_date")
    return [_to_date(r["as_of_date"]).isoformat() for r in cur.fetchall() if r.get("as_of_date")]


def _resolve_trained_model(model_api: dict[str, Any], result: Any) -> Any:
    """Turn the output of ``train_failure_model`` into a scoreable model object.

    The IGS trainer returns a *dict* (``{"success": True, "model_path": ...}``)
    and persists the bundle to disk, so the scoreable object is obtained via
    ``IGSModel.load(model_path)``. If the trainer instead returned a model-like
    object (foreign trainer, or a future direct-return API), it is used as-is.
    Returns ``None`` when no model can be resolved.
    """
    if result is None:
        return None
    # A model-like object returned directly.
    if any(hasattr(result, m) for m in ("predict_proba", "risk_score", "predict", "score_row")):
        return result
    if isinstance(result, dict):
        if not result.get("success", True):
            return None
        path = result.get("model_path")
        igs_model = model_api.get("IGSModel")
        if igs_model is not None and hasattr(igs_model, "load"):
            try:
                return igs_model.load(path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("IGSModel.load(%s) failed: %s", path, exc)
                return None
    return None


def _evaluate_fold(
    cur: Any,
    model_api: dict[str, Any],
    as_of: str,
    horizon_months: int,
    threshold: float,
    min_positives: int,
) -> dict[str, Any]:
    """Train-before-T / evaluate-at-T for a single as-of date."""
    horizon_end = _add_months(as_of, horizon_months)
    feature_rows = _fetch_features_asof(cur, as_of)
    if not feature_rows:
        return {"as_of": as_of, "success": False, "reason": "no_features_at_asof"}

    outcomes = _fetch_outcomes(cur, as_of, horizon_end)
    y_true: list[int] = []
    obs_dates: list[Any] = []
    event_dates: list[Any] = []
    eval_rows: list[dict[str, Any]] = []
    for row in feature_rows:
        cin = row.get("cin")
        outcome = outcomes.get(cin, {})
        label = 1 if outcome.get("is_positive") else 0
        y_true.append(label)
        eval_rows.append(row)
        if label:
            obs_dates.append(row.get("as_of_date"))
            event_dates.append(outcome.get("first_event_date"))

    positives = sum(y_true)
    if positives < min_positives or (len(y_true) - positives) < 1:
        return {
            "as_of": as_of,
            "success": False,
            "reason": "insufficient_positives",
            "n": len(y_true),
            "positives": positives,
        }

    # Train strictly before T (preferred), else fall back to a preloaded model.
    train_fn = model_api.get("train_failure_model")
    model = model_api.get("_preloaded_model")
    train_meta: dict[str, Any] = {}
    if model is None and callable(train_fn):
        try:
            result = train_fn(as_of=as_of)
        except TypeError:
            try:
                result = train_fn(as_of)  # positional fallback
            except Exception as exc:  # noqa: BLE001
                logger.warning("train_failure_model(as_of=%s) failed: %s", as_of, exc)
                result = None
        except Exception as exc:  # noqa: BLE001
            logger.warning("train_failure_model(as_of=%s) failed: %s", as_of, exc)
            result = None
        model = _resolve_trained_model(model_api, result)
        if isinstance(result, dict):
            train_meta = {k: result.get(k) for k in ("auc_cv", "n_train", "n_pos", "backend") if k in result}
            if not result.get("success", True):
                return {"as_of": as_of, "success": False,
                        "reason": f"train_failed: {result.get('error', 'unknown')}",
                        "n": len(y_true), "positives": positives}

    if model is None:
        return {"as_of": as_of, "success": False, "reason": "no_trained_model",
                "n": len(y_true), "positives": positives}

    y_score = _score_rows(model_api, model, eval_rows)
    if y_score is None:
        return {"as_of": as_of, "success": False, "reason": "model_has_no_scorer",
                "n": len(y_true), "positives": positives}

    auc = roc_auc(y_true, y_score)
    pr = precision_recall_at_threshold(y_true, y_score, threshold)
    # Lead time uses only the positives that the model actually flagged.
    flagged_obs: list[Any] = []
    flagged_evt: list[Any] = []
    pos_i = 0
    for i, label in enumerate(y_true):
        if label and y_score[i] >= threshold:
            flagged_obs.append(obs_dates[pos_i])
            flagged_evt.append(event_dates[pos_i])
        if label:
            pos_i += 1
    lead = lead_time_months(flagged_obs, flagged_evt)

    return {
        "as_of": as_of,
        "horizon_end": horizon_end,
        "success": True,
        "n": len(y_true),
        "positives": positives,
        "auc": round(auc, 4),
        "precision_recall": pr,
        "lead_time": lead,
        "train": train_meta or None,
    }


def run_backtest(
    database_url: Optional[str] = None,
    as_of_dates: Optional[list[str]] = None,
    horizon_months: int = 12,
    threshold: float = 0.5,
    min_positives: int = 5,
) -> dict[str, Any]:
    """Run a date-shifted backtest of the IGS failure model.

    For each as-of date ``T`` the model is trained on data strictly before ``T``
    and scored against the labelled set as of ``T`` (positive = failure within
    ``(T, T+horizon_months]`` or an undatable ``is_failure`` row). Aggregates AUC,
    precision/recall at ``threshold``, positive counts and lead-time across folds.

    Robust by contract: returns ``{"success": False, "reason": ...}`` (never raises)
    on a missing DB, a missing/immature model module, or too few positives.
    """
    from finagent.ikg.db import get_database_url

    db_url = get_database_url(database_url)
    if not db_url:
        return {"success": False, "reason": "no_database_url", "folds": []}

    model_api = _load_model_module()
    has_trainer = callable(model_api.get("train_failure_model"))
    has_columns = bool(model_api.get("FEATURE_COLUMNS"))
    if not has_trainer and "_preloaded_model" not in model_api:
        # Without a trainer we can still proceed if a model is preloaded elsewhere,
        # but for the default entrypoint this means the model module is not ready.
        if not has_columns:
            return {"success": False, "reason": "igs_model_unavailable", "folds": []}

    try:
        from psycopg.rows import dict_row

        from finagent.ikg.db import connect_postgres
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "reason": f"psycopg_unavailable: {exc}", "folds": []}

    folds: list[dict[str, Any]] = []
    try:
        with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                dates = as_of_dates or _default_as_of_dates(cur)
                if not dates:
                    return {"success": False, "reason": "no_as_of_dates", "folds": []}
                dates = [_to_date(d).isoformat() for d in dates if _to_date(d)]
                for as_of in dates:
                    try:
                        folds.append(
                            _evaluate_fold(
                                cur, model_api, as_of, horizon_months, threshold, min_positives
                            )
                        )
                    except Exception as exc:  # noqa: BLE001 - one bad fold must not kill the run
                        logger.error("Fold %s failed: %s", as_of, exc)
                        folds.append({"as_of": as_of, "success": False, "reason": f"error: {exc}"})
    except Exception as exc:  # noqa: BLE001
        logger.error("Backtest DB phase failed: %s", exc)
        return {"success": False, "reason": f"db_error: {exc}", "folds": folds}

    return _aggregate(folds, horizon_months, threshold)


def _aggregate(folds: list[dict[str, Any]], horizon_months: int, threshold: float) -> dict[str, Any]:
    """Roll fold results into an overall summary (micro + macro averages)."""
    ok = [f for f in folds if f.get("success")]
    if not ok:
        reason = folds[0].get("reason") if folds else "no_folds"
        return {
            "success": False,
            "reason": reason or "no_successful_folds",
            "horizon_months": horizon_months,
            "threshold": threshold,
            "folds": folds,
        }

    total_n = sum(f["n"] for f in ok)
    total_pos = sum(f["positives"] for f in ok)
    macro_auc = sum(f["auc"] for f in ok) / len(ok)

    tp = sum(f["precision_recall"]["tp"] for f in ok)
    fp = sum(f["precision_recall"]["fp"] for f in ok)
    fn = sum(f["precision_recall"]["fn"] for f in ok)
    tn = sum(f["precision_recall"]["tn"] for f in ok)
    micro_precision = tp / (tp + fp) if (tp + fp) else None
    micro_recall = tp / (tp + fn) if (tp + fn) else None

    all_leads = [f["lead_time"]["median_months"] for f in ok if f["lead_time"].get("median_months") is not None]
    median_lead = (sum(all_leads) / len(all_leads)) if all_leads else None

    return {
        "success": True,
        "horizon_months": horizon_months,
        "threshold": threshold,
        "folds_total": len(folds),
        "folds_evaluated": len(ok),
        "samples": total_n,
        "positives": total_pos,
        "macro_auc": round(macro_auc, 4),
        "micro_precision": round(micro_precision, 4) if micro_precision is not None else None,
        "micro_recall": round(micro_recall, 4) if micro_recall is not None else None,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "mean_fold_median_lead_months": round(median_lead, 2) if median_lead is not None else None,
        "folds": folds,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import json

    print(json.dumps(run_backtest(), default=str, indent=2))

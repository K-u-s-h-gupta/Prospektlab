"""IGS Phase C — predictive failure-risk model over ``company_features``.

Trains a gradient-boosted classifier on the Phase-B feature store
(``company_features``) against a binary failure label sourced from
``failure_events``, calibrates the probabilities, and persists the model so a
single company can be scored on demand. The model output is intentionally kept
as plain dicts (a 0–100 subscore plus SHAP-derived "reasons") so the lead can
merge it into :class:`finagent.ikg.governance_score.GovernanceResult` without
this module importing or mutating that dataclass.

Design notes mirroring the rest of the IGS package:
  - ``feature_vector`` is a PURE function (no DB, no heavy deps) → unit-testable.
  - Every heavy dependency (lightgbm, shap, scikit-survival, sklearn, joblib) is
    imported INSIDE the function that needs it and guarded with try/except so the
    module imports cleanly on a machine where none of them are installed.
  - Training and scoring return structured dicts; failures surface as
    ``{"success": False, "error": ...}`` rather than raising, so the scheduler
    and gateway can degrade gracefully.

LightGBM is preferred; if it is unavailable we fall back to sklearn's
``GradientBoostingClassifier``. SHAP is preferred for explanations; if it is
unavailable we fall back to ``feature_importance * value`` contributions.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any

from finagent.ikg.db import connect_postgres, get_database_url
from finagent.ikg.igs.feature_builder import FEATURE_VERSION

logger = logging.getLogger("finagent.ikg.igs.model")

MODEL_VERSION = "igs_model_v1"

#: Default on-disk location for the persisted model bundle. Overridable via the
#: ``IGS_MODEL_PATH`` environment variable or the ``model_path`` argument.
DEFAULT_MODEL_PATH = "/app/models/igs_lgbm.pkl"

# ── Feature schema ────────────────────────────────────────────────────────────
# Ordered numeric/bool feature list (identity/version columns excluded). MUST
# stay in sync with ``feature_builder._FEATURE_COLUMNS`` so a row materialised by
# the builder maps positionally to this vector.
FEATURE_COLUMNS: list[str] = [
    "pledge_pct",
    "pledge_pct_qoq_delta",
    "pledge_slope_4q",
    "pledge_accel",
    "promoter_holding_pct",
    "holding_dilution_4q",
    "pledge_quarters_observed",
    "director_count",
    "board_churn_12m",
    "recent_cessations_12m",
    "own_enforcement_count",
    "director_enforcement_count",
    "enforcement_proximity_hops",
    "auditor_count_5y",
    "mid_term_auditor_change",
    "rpt_party_count",
    "rpt_relationship_types",
    "director_other_boards",
    "shared_failure_director_count",
    "enforcement_2hop_count",
    "beneish_m_score",
    "accrual_ratio",
]

#: Columns that are semantically boolean in ``company_features``.
_BOOL_COLUMNS = frozenset({"mid_term_auditor_change"})


# ── Pure helpers (no DB, no heavy deps — unit-testable) ───────────────────────

def feature_vector(row: dict[str, Any]) -> list[float]:
    """Map a ``company_features`` row dict → an ordered numeric vector.

    Booleans become 0.0/1.0, missing/None values become ``nan`` (LightGBM and
    sklearn HistGradientBoosting both treat ``nan`` as "missing"; the sklearn
    GradientBoostingClassifier fallback gets ``nan`` imputed in :func:`_impute`).
    The ordering is exactly :data:`FEATURE_COLUMNS`.
    """
    vector: list[float] = []
    for col in FEATURE_COLUMNS:
        value = row.get(col)
        if value is None:
            vector.append(float("nan"))
        elif isinstance(value, bool):
            vector.append(1.0 if value else 0.0)
        else:
            try:
                vector.append(float(value))
            except (TypeError, ValueError):
                vector.append(float("nan"))
    return vector


def probability_to_score(probability: float) -> float:
    """Map a calibrated probability in ``[0, 1]`` → a 0–100 risk subscore.

    Linear and monotonic so the higher-is-worse contract of GovernanceResult
    holds. NaN/invalid inputs clamp to 0.0.
    """
    try:
        p = float(probability)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(p) or math.isinf(p):
        return 0.0
    return round(max(0.0, min(1.0, p)) * 100.0, 1)


def _impute(vector: list[float], medians: list[float] | None) -> list[float]:
    """Replace NaNs with per-feature medians (or 0.0 if no medians supplied)."""
    out: list[float] = []
    for i, value in enumerate(vector):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            if medians is not None and i < len(medians):
                out.append(medians[i])
            else:
                out.append(0.0)
        else:
            out.append(value)
    return out


def _direction(shap_value: float) -> str:
    """Human-readable direction of a SHAP/contribution value."""
    if shap_value > 0:
        return "increases_risk"
    if shap_value < 0:
        return "decreases_risk"
    return "neutral"


# ── Persisted-model metadata container ────────────────────────────────────────

@dataclass
class ModelBundle:
    """Everything needed to score a company, serialised together via joblib.

    ``estimator`` is the (possibly calibrated) classifier. ``medians`` is the
    per-feature training median used to impute NaNs for estimators that cannot
    consume missing values natively. ``feature_importances`` powers the SHAP
    fallback. ``backend`` records which library produced the estimator.
    """

    estimator: Any
    feature_columns: list[str] = field(default_factory=lambda: list(FEATURE_COLUMNS))
    medians: list[float] | None = None
    feature_importances: list[float] | None = None
    backend: str = "unknown"
    model_version: str = MODEL_VERSION
    feature_version: str = FEATURE_VERSION
    metadata: dict[str, Any] = field(default_factory=dict)


# ── DB load: features joined to a binary failure label ────────────────────────

def _load_training_frame(
    db_url: str, as_of: str | None, *, temporal: bool = False
) -> tuple[list[list[float]], list[int], list[str], dict[str, Any]]:
    """Load ``(X, y, stats)`` from Postgres.

    The label is 1 when the company (by CIN) has at least one
    ``failure_events`` row with ``is_failure = true`` whose ``event_date`` is
    null OR falls on/after the feature row's ``as_of_date`` (i.e. the failure is
    contemporaneous-or-future relative to the features — no look-ahead leakage).
    Otherwise the label is 0.

    When ``as_of`` is supplied only feature rows for that date are used;
    otherwise the latest ``as_of_date`` per CIN is taken.
    """
    from psycopg.rows import dict_row

    rows_x: list[list[float]] = []
    labels: list[int] = []
    groups: list[str] = []
    n_pos = 0

    # Pick the feature snapshot: an explicit as_of; else temporal (ALL point-in-time
    # snapshots, for a richer trajectory-aware fit) or just the newest per cin.
    if as_of:
        feature_filter = "cf.as_of_date = %(as_of)s"
        params: dict[str, Any] = {"as_of": as_of}
    elif temporal:
        feature_filter = "true"
        params = {}
    else:
        feature_filter = """cf.as_of_date = (
            select max(c2.as_of_date) from company_features c2 where c2.cin = cf.cin
        )"""
        params = {}

    # Point-in-time label (leak-free, date-aware):
    #   • dated failure → positive only for snapshots inside the pre-failure window
    #     [event_date - horizon, event_date] (i.e. "failure is imminent"); snapshots
    #     long before, or after, the event are negative.
    #   • undated failure (most MCA strike-offs / BSE delistings) → label ONLY the
    #     latest snapshot positive, never historical ones (we can't know when it began).
    horizon_months = int(os.getenv("IGS_LABEL_HORIZON_MONTHS", "18"))
    params["horizon"] = horizon_months
    query = f"""
        select cf.*,
               coalesce((
                   select bool_or(
                       case
                         when fe.event_date is not null then
                              cf.as_of_date <= fe.event_date
                              and fe.event_date <= (cf.as_of_date + (%(horizon)s || ' months')::interval)
                         else cf.as_of_date = (
                              select max(c3.as_of_date) from company_features c3 where c3.cin = cf.cin
                         )
                       end
                   )
                   from failure_events fe
                   where fe.cin = cf.cin
                     and fe.is_failure = true
               ), false) as label_is_failure
        from company_features cf
        where {feature_filter}
    """

    with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            for row in cur.fetchall():
                rows_x.append(feature_vector(row))
                label = 1 if row.get("label_is_failure") else 0
                labels.append(label)
                groups.append(str(row.get("cin") or ""))
                n_pos += label

    stats = {
        "n_train": len(labels), "n_pos": n_pos, "n_neg": len(labels) - n_pos,
        "temporal": temporal, "n_groups": len(set(groups)),
    }
    return rows_x, labels, groups, stats


def _column_medians(rows_x: list[list[float]]) -> list[float]:
    """Per-feature median ignoring NaNs (0.0 for an all-NaN column)."""
    medians: list[float] = []
    width = len(FEATURE_COLUMNS)
    for i in range(width):
        column = [
            r[i] for r in rows_x
            if i < len(r) and r[i] is not None and not (isinstance(r[i], float) and math.isnan(r[i]))
        ]
        if not column:
            medians.append(0.0)
            continue
        column.sort()
        mid = len(column) // 2
        if len(column) % 2:
            medians.append(column[mid])
        else:
            medians.append((column[mid - 1] + column[mid]) / 2.0)
    return medians


# ── Training ──────────────────────────────────────────────────────────────────

def train_failure_model(
    database_url: str | None = None,
    as_of: str | None = None,
    model_path: str | None = None,
) -> dict[str, Any]:
    """Train, calibrate and persist the IGS failure-risk classifier.

    Returns a result dict with ``success`` plus diagnostics
    (``n_train``, ``n_pos``, ``auc_cv``, ``backend``, ``model_path`` …). All heavy
    imports are guarded so a missing dependency yields a clear error dict instead
    of an ``ImportError`` at module import time.
    """
    db_url = get_database_url(database_url)
    if not db_url:
        return {"success": False, "error": "no database_url"}

    out_path = model_path or os.getenv("IGS_MODEL_PATH") or DEFAULT_MODEL_PATH

    # Heavy deps, guarded.
    try:
        import numpy as np
    except ImportError as exc:
        return {"success": False, "error": f"numpy unavailable: {exc}"}
    try:
        import joblib
    except ImportError as exc:
        return {"success": False, "error": f"joblib unavailable: {exc}"}

    # Temporal mode trains on every point-in-time snapshot (trajectory-aware) and
    # uses cin-grouped CV so a company's quarters never straddle folds (no leakage).
    temporal = (as_of is None) and os.getenv("IGS_TEMPORAL_TRAIN", "1").strip().lower() in {"1", "true", "yes", "on"}
    try:
        rows_x, labels, groups, stats = _load_training_frame(db_url, as_of, temporal=temporal)
    except Exception as exc:
        logger.error("IGS training load failed: %s", exc)
        return {"success": False, "error": f"load failed: {exc}"}

    if stats["n_train"] == 0:
        return {"success": False, "error": "no training rows", **stats}
    if stats["n_pos"] == 0 or stats["n_neg"] == 0:
        return {"success": False, "error": "single-class label set; cannot train", **stats}

    medians = _column_medians(rows_x)

    backend = "unknown"
    estimator: Any = None
    supports_nan = False

    # Prefer LightGBM (handles NaN natively, fast, gives feature_importances_).
    try:
        import lightgbm as lgb  # type: ignore

        estimator = lgb.LGBMClassifier(
            n_estimators=300,
            learning_rate=0.03,
            num_leaves=31,
            subsample=0.8,
            colsample_bytree=0.8,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        backend = "lightgbm"
        supports_nan = True
    except ImportError:
        try:
            from sklearn.ensemble import GradientBoostingClassifier

            estimator = GradientBoostingClassifier(random_state=42)
            backend = "sklearn_gbc"
            supports_nan = False
        except ImportError as exc:
            return {"success": False, "error": f"no classifier backend available: {exc}", **stats}

    # Build the design matrix (impute for estimators that can't take NaN).
    if supports_nan:
        x_arr = np.asarray(rows_x, dtype=float)
    else:
        x_arr = np.asarray([_impute(r, medians) for r in rows_x], dtype=float)
    y_arr = np.asarray(labels, dtype=int)

    # Cross-validated AUC (best-effort; small/degenerate folds are tolerated).
    auc_cv: float | None = None
    try:
        from sklearn.model_selection import StratifiedKFold, cross_val_score

        n_splits = max(2, min(5, int(stats["n_pos"]), int(stats["n_neg"])))
        if n_splits >= 2 and temporal and len(set(groups)) >= n_splits:
            # Group-aware CV: keep all of a company's snapshots in one fold so the
            # reported AUC is leak-free (the only honest number for a moat claim).
            from sklearn.model_selection import GroupKFold

            gkf = GroupKFold(n_splits=n_splits)
            scores = cross_val_score(
                estimator, x_arr, y_arr, cv=gkf, groups=np.asarray(groups), scoring="roc_auc"
            )
            auc_cv = float(np.mean(scores))
            stats["cv"] = "group_kfold_by_cin"
        elif n_splits >= 2:
            skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
            scores = cross_val_score(estimator, x_arr, y_arr, cv=skf, scoring="roc_auc")
            auc_cv = float(np.mean(scores))
            stats["cv"] = "stratified_kfold"
    except Exception as exc:  # pragma: no cover - depends on sklearn presence
        logger.warning("IGS AUC CV skipped: %s", exc)

    # Fit, then probability-calibrate on top (isotonic if enough data, else sigmoid).
    final_estimator: Any = estimator
    calibrated = False
    try:
        from sklearn.calibration import CalibratedClassifierCV

        min_class = min(int(stats["n_pos"]), int(stats["n_neg"]))
        cal_folds = max(2, min(3, min_class))
        method = "isotonic" if stats["n_train"] >= 1000 else "sigmoid"
        if min_class >= 2:
            calibrator = CalibratedClassifierCV(estimator, method=method, cv=cal_folds)
            calibrator.fit(x_arr, y_arr)
            final_estimator = calibrator
            calibrated = True
    except Exception as exc:  # pragma: no cover - depends on sklearn presence
        logger.warning("IGS calibration skipped: %s", exc)

    if not calibrated:
        estimator.fit(x_arr, y_arr)
        final_estimator = estimator

    # Pull feature importances from the base estimator for the SHAP fallback.
    feature_importances: list[float] | None = None
    base = estimator
    try:
        importances = getattr(base, "feature_importances_", None)
        if importances is not None:
            feature_importances = [float(v) for v in importances]
    except Exception:  # pragma: no cover - defensive
        feature_importances = None

    bundle = ModelBundle(
        estimator=final_estimator,
        feature_columns=list(FEATURE_COLUMNS),
        medians=medians,
        feature_importances=feature_importances,
        backend=backend,
        metadata={
            "calibrated": calibrated,
            "supports_nan": supports_nan,
            "as_of": as_of,
            **stats,
        },
    )

    try:
        directory = os.path.dirname(out_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        joblib.dump(bundle, out_path)
    except Exception as exc:
        logger.error("IGS model persist failed: %s", exc)
        return {"success": False, "error": f"persist failed: {exc}", **stats}

    logger.info(
        "IGS model trained: backend=%s n_train=%d n_pos=%d auc_cv=%s path=%s",
        backend, stats["n_train"], stats["n_pos"], auc_cv, out_path,
    )
    return {
        "success": True,
        "model_path": out_path,
        "backend": backend,
        "calibrated": calibrated,
        "auc_cv": auc_cv,
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        **stats,
    }


# ── Inference ──────────────────────────────────────────────────────────────────

class IGSModel:
    """Loads a persisted :class:`ModelBundle` and scores a single company."""

    def __init__(self, bundle: ModelBundle | None = None) -> None:
        self.bundle = bundle

    @classmethod
    def load(cls, model_path: str | None = None) -> "IGSModel":
        """Load a persisted model bundle from disk.

        Raises ``FileNotFoundError`` if the path is missing and ``RuntimeError``
        if joblib is unavailable, so callers can distinguish "not trained yet"
        from "runtime broken".
        """
        path = model_path or os.getenv("IGS_MODEL_PATH") or DEFAULT_MODEL_PATH
        if not os.path.exists(path):
            raise FileNotFoundError(f"IGS model not found at {path}")
        try:
            import joblib
        except ImportError as exc:
            raise RuntimeError(f"joblib unavailable: {exc}") from exc
        bundle = joblib.load(path)
        if not isinstance(bundle, ModelBundle):
            raise RuntimeError(f"unexpected model artifact at {path}: {type(bundle)!r}")
        return cls(bundle=bundle)

    # -- internal --------------------------------------------------------------

    def _design_row(self, features: dict[str, Any]) -> Any:
        """Build a 1×N numpy design row, imputing NaNs when the estimator needs it."""
        import numpy as np

        vector = feature_vector(features)
        supports_nan = bool((self.bundle.metadata or {}).get("supports_nan")) if self.bundle else False
        if not supports_nan:
            vector = _impute(vector, self.bundle.medians if self.bundle else None)
        return np.asarray([vector], dtype=float)

    def predict_proba(self, features: dict[str, Any]) -> float:
        """Return the calibrated probability of failure in ``[0, 1]``."""
        if self.bundle is None:
            raise RuntimeError("IGSModel has no bundle loaded")
        row = self._design_row(features)
        proba = self.bundle.estimator.predict_proba(row)
        # predict_proba → shape (1, 2); positive class is column index 1.
        try:
            return float(proba[0][1])
        except (IndexError, TypeError):
            return float(proba[0])

    def risk_score(self, features: dict[str, Any]) -> float:
        """Probability mapped to a 0–100 risk subscore (higher = worse)."""
        return probability_to_score(self.predict_proba(features))

    def explain(self, features: dict[str, Any], top_k: int = 6) -> list[dict[str, Any]]:
        """Top contributing features as ``[{feature, value, shap, direction}]``.

        Prefers SHAP TreeExplainer over the base estimator; falls back to
        ``feature_importance * value`` when SHAP (or the base estimator's tree
        structure) is unavailable. Sorted by absolute contribution, descending.
        """
        if self.bundle is None:
            raise RuntimeError("IGSModel has no bundle loaded")

        vector = feature_vector(features)
        display_values = _impute(vector, self.bundle.medians)
        contributions: list[float] | None = None

        # 1) Try SHAP on the underlying (uncalibrated) tree estimator.
        base = self._base_estimator()
        if base is not None:
            try:
                import shap  # type: ignore

                row = self._design_row(features)
                explainer = shap.TreeExplainer(base)
                shap_out = explainer.shap_values(row)
                contributions = _flatten_shap(shap_out)
            except Exception as exc:  # pragma: no cover - depends on shap presence
                logger.debug("SHAP explain unavailable, falling back: %s", exc)
                contributions = None

        # 2) Fallback: feature_importance * value.
        if contributions is None:
            importances = self.bundle.feature_importances
            if importances:
                contributions = [
                    float(importances[i]) * float(display_values[i])
                    for i in range(min(len(importances), len(display_values)))
                ]
            else:
                contributions = [0.0 for _ in display_values]

        reasons: list[dict[str, Any]] = []
        for i, col in enumerate(self.bundle.feature_columns):
            if i >= len(contributions):
                break
            shap_value = float(contributions[i])
            reasons.append({
                "feature": col,
                "value": _clean_number(vector[i]) if i < len(vector) else None,
                "shap": round(shap_value, 6),
                "direction": _direction(shap_value),
            })
        reasons.sort(key=lambda r: abs(r["shap"]), reverse=True)
        return reasons[:top_k]

    def _base_estimator(self) -> Any:
        """Return the underlying tree estimator, unwrapping a calibrator if present."""
        if self.bundle is None:
            return None
        est = self.bundle.estimator
        # CalibratedClassifierCV stores fitted sub-estimators differently across
        # sklearn versions; probe the common attributes defensively.
        for attr in ("estimator", "base_estimator"):
            inner = getattr(est, attr, None)
            if inner is not None and hasattr(inner, "feature_importances_"):
                return inner
        calibrated = getattr(est, "calibrated_classifiers_", None)
        if calibrated:
            inner = getattr(calibrated[0], "estimator", None) or getattr(
                calibrated[0], "base_estimator", None
            )
            if inner is not None and hasattr(inner, "feature_importances_"):
                return inner
        if hasattr(est, "feature_importances_"):
            return est
        return None


def _flatten_shap(shap_out: Any) -> list[float]:
    """Normalise the various SHAP return shapes to a flat per-feature list."""
    values = shap_out
    # Binary classifiers return a list [class0, class1]; take the positive class.
    if isinstance(values, list):
        values = values[-1]
    try:
        import numpy as np

        arr = np.asarray(values)
        if arr.ndim == 2:
            arr = arr[0]
        elif arr.ndim == 3:  # (n_classes, n_rows, n_features) in some versions
            arr = arr[-1][0]
        return [float(v) for v in arr.ravel()]
    except Exception:  # pragma: no cover - defensive
        try:
            return [float(v) for v in values[0]]
        except Exception:
            return []


def _clean_number(value: Any) -> float | None:
    """Convert a vector entry to a JSON-safe number (NaN → None)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


# ── One-shot company scoring (DB + model) ─────────────────────────────────────

def _fetch_latest_features(db_url: str, cin: str) -> dict[str, Any] | None:
    """Fetch the most recent ``company_features`` row for a CIN."""
    from psycopg.rows import dict_row

    with connect_postgres(db_url, row_factory=dict_row, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select * from company_features
                where cin = %s
                order by as_of_date desc
                limit 1
                """,
                (cin,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def score_company(
    cin: str,
    database_url: str | None = None,
    model_path: str | None = None,
) -> dict[str, Any] | None:
    """Score one company by CIN against the persisted IGS model.

    Returns ``{cin, predicted_risk, probability, reasons, model_version, ...}``
    or ``None`` if the company has no materialised features. Model/infra failures
    surface as ``{"error": ...}`` in the returned dict (with ``predicted_risk``
    omitted) rather than raising, so the caller can degrade gracefully.
    """
    db_url = get_database_url(database_url)
    cin = (cin or "").upper().strip()
    if not cin or not db_url:
        return None

    try:
        features = _fetch_latest_features(db_url, cin)
    except Exception as exc:
        logger.error("IGS feature fetch failed for %s: %s", cin, exc)
        return {"cin": cin, "error": f"feature fetch failed: {exc}"}

    if features is None:
        return None

    try:
        model = IGSModel.load(model_path)
    except FileNotFoundError as exc:
        return {"cin": cin, "error": str(exc), "model_version": MODEL_VERSION}
    except Exception as exc:
        logger.error("IGS model load failed: %s", exc)
        return {"cin": cin, "error": f"model load failed: {exc}"}

    try:
        probability = model.predict_proba(features)
        reasons = model.explain(features)
    except Exception as exc:
        logger.error("IGS scoring failed for %s: %s", cin, exc)
        return {"cin": cin, "error": f"scoring failed: {exc}"}

    return {
        "cin": cin,
        "predicted_risk": probability_to_score(probability),
        "probability": round(float(probability), 6),
        "reasons": reasons,
        "model_version": (model.bundle.model_version if model.bundle else MODEL_VERSION),
        "feature_version": (model.bundle.feature_version if model.bundle else FEATURE_VERSION),
        "as_of_date": str(features.get("as_of_date")),
    }


# ── Optional: survival model (months-to-event) ────────────────────────────────

def train_survival_model(
    database_url: str | None = None,
    as_of: str | None = None,
    model_path: str | None = None,
) -> dict[str, Any]:
    """Optionally fit a Cox PH survival model (scikit-survival) for time-to-failure.

    Fully import-guarded and optional — returns ``{"success": False,
    "error": ...}`` when scikit-survival is not installed rather than raising.
    The duration is months between the feature ``as_of_date`` and the failure
    ``event_date`` (right-censored at the latest observed date for survivors).
    """
    db_url = get_database_url(database_url)
    if not db_url:
        return {"success": False, "error": "no database_url"}

    try:
        import numpy as np
        import joblib
        from sksurv.linear_model import CoxPHSurvivalAnalysis  # type: ignore
    except ImportError as exc:
        return {"success": False, "error": f"survival deps unavailable: {exc}", "optional": True}

    out_path = model_path or os.getenv("IGS_SURVIVAL_MODEL_PATH") or "/app/models/igs_coxph.pkl"

    try:
        from datetime import date
        from psycopg.rows import dict_row

        rows_x: list[list[float]] = []
        events: list[bool] = []
        durations: list[float] = []
        today = date.today()

        feature_filter = "cf.as_of_date = %(as_of)s" if as_of else """cf.as_of_date = (
            select max(c2.as_of_date) from company_features c2 where c2.cin = cf.cin
        )"""
        params: dict[str, Any] = {"as_of": as_of} if as_of else {}

        query = f"""
            select cf.*, fe.event_date as failure_date,
                   coalesce(fe.is_failure, false) as label_is_failure
            from company_features cf
            left join lateral (
                select event_date, is_failure
                from failure_events fe
                where fe.cin = cf.cin and fe.is_failure = true
                  and (fe.event_date is null or fe.event_date >= cf.as_of_date)
                order by fe.event_date asc nulls last
                limit 1
            ) fe on true
            where {feature_filter}
        """

        with connect_postgres(db_url, row_factory=dict_row, connect_timeout=30) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                for row in cur.fetchall():
                    as_of_date = row.get("as_of_date")
                    failed = bool(row.get("label_is_failure"))
                    failure_date = row.get("failure_date")
                    if failed and failure_date and as_of_date:
                        months = max(0.0, (failure_date - as_of_date).days / 30.4375)
                    elif as_of_date:
                        months = max(0.0, (today - as_of_date).days / 30.4375)
                    else:
                        continue
                    rows_x.append(_impute(feature_vector(row), None))
                    events.append(failed)
                    durations.append(float(months))
    except Exception as exc:
        return {"success": False, "error": f"survival load failed: {exc}", "optional": True}

    if len(durations) < 2 or not any(events):
        return {"success": False, "error": "insufficient survival data", "optional": True}

    try:
        x_arr = np.asarray(rows_x, dtype=float)
        y_struct = np.array(
            list(zip(events, durations)),
            dtype=[("event", "?"), ("time", "<f8")],
        )
        model = CoxPHSurvivalAnalysis()
        model.fit(x_arr, y_struct)
        directory = os.path.dirname(out_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        joblib.dump(
            ModelBundle(
                estimator=model,
                feature_columns=list(FEATURE_COLUMNS),
                backend="sksurv_coxph",
                model_version="igs_survival_v1",
            ),
            out_path,
        )
    except Exception as exc:
        return {"success": False, "error": f"survival fit/persist failed: {exc}", "optional": True}

    return {
        "success": True,
        "model_path": out_path,
        "n_train": len(durations),
        "n_events": int(sum(events)),
        "optional": True,
    }


# ── Optional: novelty / anomaly score (IsolationForest) ───────────────────────

def novelty_score(features: dict[str, Any], model_path: str | None = None) -> float | None:
    """Anomaly/novelty score in ``[0, 1]`` for a feature row (higher = stranger).

    Loads (or lazily relies on a caller-trained) IsolationForest bundle. Returns
    ``None`` when sklearn or the model artifact is unavailable — this is an
    optional signal and must never block scoring.
    """
    path = model_path or os.getenv("IGS_NOVELTY_MODEL_PATH") or "/app/models/igs_iforest.pkl"
    if not os.path.exists(path):
        return None
    try:
        import numpy as np
        import joblib
    except ImportError:
        return None
    try:
        bundle = joblib.load(path)
        estimator = bundle.estimator if isinstance(bundle, ModelBundle) else bundle
        vector = _impute(
            feature_vector(features),
            bundle.medians if isinstance(bundle, ModelBundle) else None,
        )
        row = np.asarray([vector], dtype=float)
        # score_samples: higher = more normal; flip and squash to [0, 1].
        raw = float(estimator.score_samples(row)[0])
        return round(1.0 / (1.0 + math.exp(raw)), 6)
    except Exception as exc:  # pragma: no cover - optional path
        logger.debug("novelty_score unavailable: %s", exc)
        return None


def train_novelty_model(
    database_url: str | None = None,
    as_of: str | None = None,
    model_path: str | None = None,
) -> dict[str, Any]:
    """Optionally fit an IsolationForest over the feature store (unsupervised)."""
    db_url = get_database_url(database_url)
    if not db_url:
        return {"success": False, "error": "no database_url"}
    try:
        import numpy as np
        import joblib
        from sklearn.ensemble import IsolationForest
    except ImportError as exc:
        return {"success": False, "error": f"novelty deps unavailable: {exc}", "optional": True}

    out_path = model_path or os.getenv("IGS_NOVELTY_MODEL_PATH") or "/app/models/igs_iforest.pkl"
    try:
        rows_x, _labels, _groups, stats = _load_training_frame(db_url, as_of)
    except Exception as exc:
        return {"success": False, "error": f"load failed: {exc}", "optional": True}
    if stats["n_train"] < 2:
        return {"success": False, "error": "insufficient rows", "optional": True}

    try:
        medians = _column_medians(rows_x)
        x_arr = np.asarray([_impute(r, medians) for r in rows_x], dtype=float)
        estimator = IsolationForest(random_state=42, contamination="auto")
        estimator.fit(x_arr)
        directory = os.path.dirname(out_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        joblib.dump(
            ModelBundle(
                estimator=estimator,
                feature_columns=list(FEATURE_COLUMNS),
                medians=medians,
                backend="sklearn_iforest",
                model_version="igs_novelty_v1",
            ),
            out_path,
        )
    except Exception as exc:
        return {"success": False, "error": f"novelty fit/persist failed: {exc}", "optional": True}

    return {"success": True, "model_path": out_path, "optional": True, **stats}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import json

    print(json.dumps(train_failure_model(), default=str, indent=2))

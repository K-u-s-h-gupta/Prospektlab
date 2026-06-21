"""Pure unit tests for IGS Phase C model helpers.

These tests deliberately avoid any DB connection and any heavy ML dependency
(lightgbm/shap/sklearn/scikit-survival), exercising only the pure functions so
they run on a bare Python install. Run with::

    python backend/finagent/ikg/igs/test_model.py
"""

from __future__ import annotations

import math
import os
import sys

# Allow `python backend/finagent/ikg/igs/test_model.py` from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from finagent.ikg.igs.model import (  # noqa: E402
    FEATURE_COLUMNS,
    feature_vector,
    probability_to_score,
    _direction,
    _impute,
    _column_medians,
)


def test_feature_vector_ordering_and_length() -> None:
    row = {col: float(i) for i, col in enumerate(FEATURE_COLUMNS)}
    vec = feature_vector(row)
    assert len(vec) == len(FEATURE_COLUMNS), "vector width must match FEATURE_COLUMNS"
    assert vec == [float(i) for i in range(len(FEATURE_COLUMNS))], "order must be preserved"


def test_feature_vector_bool_to_float() -> None:
    row = {"mid_term_auditor_change": True}
    vec = feature_vector(row)
    idx = FEATURE_COLUMNS.index("mid_term_auditor_change")
    assert vec[idx] == 1.0
    row["mid_term_auditor_change"] = False
    assert feature_vector(row)[idx] == 0.0


def test_feature_vector_none_to_nan() -> None:
    vec = feature_vector({})  # nothing present → all nan
    assert len(vec) == len(FEATURE_COLUMNS)
    assert all(math.isnan(v) for v in vec), "missing values must become nan"


def test_feature_vector_bad_string_to_nan() -> None:
    row = {"pledge_pct": "not-a-number"}
    idx = FEATURE_COLUMNS.index("pledge_pct")
    assert math.isnan(feature_vector(row)[idx])


def test_probability_to_score_mapping() -> None:
    assert probability_to_score(0.0) == 0.0
    assert probability_to_score(1.0) == 100.0
    assert probability_to_score(0.5) == 50.0
    assert probability_to_score(0.123) == 12.3
    # Out-of-range and invalid inputs clamp safely.
    assert probability_to_score(1.5) == 100.0
    assert probability_to_score(-0.2) == 0.0
    assert probability_to_score(float("nan")) == 0.0
    assert probability_to_score("nope") == 0.0


def test_probability_to_score_monotonic() -> None:
    scores = [probability_to_score(p / 10) for p in range(11)]
    assert scores == sorted(scores), "score must be monotonic in probability"


def test_direction() -> None:
    assert _direction(1.0) == "increases_risk"
    assert _direction(-1.0) == "decreases_risk"
    assert _direction(0.0) == "neutral"


def test_impute_uses_medians() -> None:
    vector = [float("nan"), 2.0, float("nan")]
    medians = [9.0, 0.0, 7.0]
    assert _impute(vector, medians) == [9.0, 2.0, 7.0]
    # No medians → fall back to 0.0.
    assert _impute([float("nan"), 3.0], None) == [0.0, 3.0]


def test_column_medians_ignores_nan() -> None:
    # Build rows with a known column; only first feature column matters here.
    width = len(FEATURE_COLUMNS)

    def _row(first: float) -> list[float]:
        return [first] + [float("nan")] * (width - 1)

    rows = [_row(1.0), _row(3.0), _row(float("nan")), _row(5.0)]
    medians = _column_medians(rows)
    assert medians[0] == 3.0, "median of [1,3,5] ignoring nan must be 3"
    # All-nan column → 0.0.
    assert medians[1] == 0.0


def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
        except Exception as exc:  # pragma: no cover
            failures += 1
            print(f"ERROR {test.__name__}: {exc!r}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_run())

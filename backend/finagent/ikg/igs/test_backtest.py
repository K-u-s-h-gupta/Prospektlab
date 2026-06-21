"""Pure unit tests for the IGS backtest metric core (no DB, no third-party libs).

Runnable with the system ``python`` directly:

    python backend/finagent/ikg/igs/test_backtest.py

or via pytest. The metric functions are dependency-free, so these tests never
touch Postgres or the (possibly mid-development) ``igs.model`` module.
"""

from __future__ import annotations

import os
import sys

# Make ``finagent`` importable when run as a bare script from anywhere.
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from finagent.ikg.igs.backtest import (  # noqa: E402
    lead_time_months,
    precision_recall_at_threshold,
    roc_auc,
)


# ── roc_auc ───────────────────────────────────────────────────────────────────


def test_roc_auc_perfect():
    assert roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0


def test_roc_auc_perfectly_wrong():
    assert roc_auc([0, 0, 1, 1], [0.9, 0.8, 0.2, 0.1]) == 0.0


def test_roc_auc_random_is_half():
    # Interleaved scores → no separation.
    assert roc_auc([0, 1, 0, 1], [0.5, 0.5, 0.5, 0.5]) == 0.5


def test_roc_auc_handles_ties():
    # One tie straddling the boundary: 2 pos, 2 neg.
    # scores: neg=0.2, neg=0.5, pos=0.5, pos=0.9
    # pairs(pos,neg): (0.5 vs 0.2)=1, (0.5 vs 0.5)=0.5, (0.9 vs 0.2)=1, (0.9 vs 0.5)=1
    # AUC = (1 + 0.5 + 1 + 1) / 4 = 0.875
    auc = roc_auc([0, 0, 1, 1], [0.2, 0.5, 0.5, 0.9])
    assert abs(auc - 0.875) < 1e-9


def test_roc_auc_degenerate_single_class():
    assert roc_auc([1, 1, 1], [0.1, 0.2, 0.3]) == 0.5
    assert roc_auc([], []) == 0.5
    assert roc_auc([0, 1], [0.5]) == 0.5  # length mismatch


# ── precision_recall_at_threshold ─────────────────────────────────────────────


def test_precision_recall_perfect_split():
    res = precision_recall_at_threshold([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9], 0.5)
    assert res["tp"] == 2 and res["fp"] == 0 and res["fn"] == 0 and res["tn"] == 2
    assert res["precision"] == 1.0
    assert res["recall"] == 1.0
    assert res["f1"] == 1.0


def test_precision_recall_with_errors():
    # threshold 0.5 → predicted pos: idx0(0.6),idx2(0.9); actual pos: idx1,idx2
    y_true = [0, 1, 1, 0]
    y_score = [0.6, 0.3, 0.9, 0.4]
    res = precision_recall_at_threshold(y_true, y_score, 0.5)
    assert res["tp"] == 1  # idx2
    assert res["fp"] == 1  # idx0
    assert res["fn"] == 1  # idx1
    assert res["tn"] == 1  # idx3
    assert res["precision"] == 0.5
    assert res["recall"] == 0.5


def test_precision_recall_no_predicted_positives():
    res = precision_recall_at_threshold([0, 1], [0.1, 0.2], 0.9)
    assert res["tp"] == 0 and res["fp"] == 0
    assert res["precision"] is None  # undefined, not 0.0
    assert res["recall"] == 0.0


# ── lead_time_months ──────────────────────────────────────────────────────────


def test_lead_time_basic():
    res = lead_time_months(["2025-01-01", "2025-01-01"], ["2025-07-01", "2026-01-01"])
    assert res["count"] == 2
    assert res["undatable_events"] == 0
    assert abs(res["min_months"] - 6.0) < 1e-6
    assert abs(res["max_months"] - 12.0) < 1e-6
    assert res["coverage"] == 1.0


def test_lead_time_handles_none_event_dates():
    # Two undatable (None) events, one datable.
    res = lead_time_months(
        ["2025-01-01", "2025-01-01", "2025-01-01"],
        [None, None, "2025-04-01"],
    )
    assert res["count"] == 1
    assert res["undatable_events"] == 2
    assert abs(res["coverage"] - (1 / 3)) < 1e-6
    assert abs(res["median_months"] - 3.0) < 1e-6


def test_lead_time_all_undatable():
    res = lead_time_months(["2025-01-01"], [None])
    assert res["count"] == 0
    assert res["undatable_events"] == 1
    assert res["median_months"] is None
    assert res["coverage"] == 0.0


def _run_all() -> int:
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in funcs:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR {fn.__name__}: {exc!r}")
    print(f"\n{len(funcs) - failures}/{len(funcs)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_all())

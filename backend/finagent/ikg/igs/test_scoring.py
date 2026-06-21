"""Pure unit tests for IGS Phase D ``merge_scores`` (no DB, no model import).

Run: ``python -m pytest backend/finagent/ikg/igs/test_scoring.py`` or directly
``python backend/finagent/ikg/igs/test_scoring.py`` (built-in harness, no pytest).
"""

from __future__ import annotations

from finagent.ikg.igs.scoring import merge_scores


def _rules(score: float) -> dict:
    return {
        "score": score,
        "band": "MODERATE",
        "subscores": {"pledge": 40.0, "enforcement": 0.0},
        "flags": [
            {"code": "PLEDGE_ELEVATED", "severity": "watch", "detail": "x", "evidence": {"v": 1}},
        ],
        "coverage": {"pledge": True},
    }


def _model(risk: float) -> dict:
    return {
        "cin": "X",
        "predicted_risk": risk,
        "probability": risk / 100.0,
        "model_version": "igs_model_v1",
        "reasons": [
            {"severity": "high", "detail": "high pledge slope", "evidence": {"feature": "pledge_slope_4q"}},
        ],
    }


def test_rules_only_composite_equals_rules_score():
    out = merge_scores(_rules(40.0), None)
    assert out["composite_score"] == 40.0, out
    assert out["band"] == "MODERATE", out          # 25 <= 40 < 50
    assert out["rules_score"] == 40.0
    assert out["model_risk"] is None
    assert out["model_version"] is None
    assert out["source"] == "rules"
    # rules subscores preserved, no predictive subscore added when model absent.
    assert out["subscores"] == {"pledge": 40.0, "enforcement": 0.0}
    assert "predicted_failure" not in out["subscores"]
    # only the rules flag survives.
    assert [f["code"] for f in out["flags"]] == ["PLEDGE_ELEVATED"]


def test_rules_only_band_thresholds():
    assert merge_scores(_rules(10.0), None)["band"] == "LOW"        # < 25
    assert merge_scores(_rules(25.0), None)["band"] == "MODERATE"   # boundary
    assert merge_scores(_rules(60.0), None)["band"] == "ELEVATED"   # 50 <= x < 75
    assert merge_scores(_rules(75.0), None)["band"] == "HIGH"       # boundary
    assert merge_scores(_rules(90.0), None)["band"] == "HIGH"


def test_model_only():
    out = merge_scores(None, _model(80.0))
    assert out["composite_score"] == 80.0, out
    assert out["band"] == "HIGH"
    assert out["rules_score"] is None
    assert out["model_risk"] == 80.0
    assert out["model_probability"] == 0.8
    assert out["model_version"] == "igs_model_v1"
    assert out["source"] == "model"
    assert out["subscores"]["predicted_failure"] == 80.0
    assert [f["code"] for f in out["flags"]] == ["IGS_MODEL_SIGNAL"]
    assert out["flags"][0]["evidence"] == {"feature": "pledge_slope_4q"}


def test_both_present_weighted_blend():
    # default model_weight=0.5 → (60*0.5 + 40*0.5) = 50.0
    out = merge_scores(_rules(40.0), _model(60.0))
    assert out["composite_score"] == 50.0, out
    assert out["band"] == "ELEVATED"   # 50 <= 50 < 75
    assert out["rules_score"] == 40.0
    assert out["model_risk"] == 60.0
    assert out["source"] == "rules+model"
    # predictive subscore folded in alongside rules subscores.
    assert out["subscores"]["predicted_failure"] == 60.0
    assert out["subscores"]["pledge"] == 40.0


def test_custom_weight_blend():
    # model_weight=0.75 → (80*0.75 + 20*0.25) = 65.0
    out = merge_scores(_rules(20.0), _model(80.0), model_weight=0.75)
    assert out["composite_score"] == 65.0, out


def test_flags_merged_order():
    out = merge_scores(_rules(40.0), _model(60.0))
    codes = [f["code"] for f in out["flags"]]
    assert codes == ["PLEDGE_ELEVATED", "IGS_MODEL_SIGNAL"], codes


def test_neither_present():
    out = merge_scores(None, None)
    assert out["composite_score"] == 0.0
    assert out["band"] == "LOW"
    assert out["flags"] == []
    assert out["subscores"] == {}
    assert out["source"] == "rules"


def test_empty_dicts_treated_as_absent():
    # empty dicts must not crash and behave like "no data".
    out = merge_scores({}, {})
    assert out["composite_score"] == 0.0
    assert out["rules_score"] is None
    assert out["model_risk"] is None


def _run() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {t.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"ERROR {t.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys

    sys.exit(_run())

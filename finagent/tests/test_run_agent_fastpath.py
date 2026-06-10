from types import SimpleNamespace

from finagent.run_agent import _ikg_can_answer_objective, _objective_needs_fresh_web


def test_static_shareholding_question_does_not_force_fresh_web():
    assert _objective_needs_fresh_web(
        "Explain the promoter holding structure and pledged shares in 360 ONE WAM."
    ) is False


def test_latest_shareholding_question_still_forces_fresh_web():
    assert _objective_needs_fresh_web(
        "What is the latest promoter pledge update and shareholding change in 360 ONE WAM?"
    ) is True


def test_ikg_objective_fastpath_accepts_ownership_question_with_coverage():
    bundle = SimpleNamespace(
        ikg=SimpleNamespace(
            status="partial",
            coverage={"identity": "complete", "ownership": "complete", "governance": "partial"},
        )
    )

    assert _ikg_can_answer_objective(
        bundle,
        "Explain the promoter holding structure and pledged shares in 360 ONE WAM.",
        "direct_answer",
    ) is True

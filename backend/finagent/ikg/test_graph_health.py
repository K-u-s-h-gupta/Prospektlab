"""Unit tests for graph-health completeness scoring (pure)."""

from __future__ import annotations

from finagent.ikg.graph_health import score_completeness


def test_full_profile_evidence_grade():
    presence = {d: True for d in ("directors", "shareholding", "auditors", "financials", "filings")}
    out = score_completeness(presence)
    assert out["completeness_score"] == 100.0
    assert out["grade"] == "evidence_grade"
    assert out["missing"] == []


def test_partial_profile():
    presence = {"directors": True, "shareholding": True, "auditors": True,
                "financials": False, "filings": False}
    out = score_completeness(presence)
    assert out["completeness_score"] == 60.0
    assert out["grade"] == "partial"
    assert set(out["missing"]) == {"financials", "filings"}


def test_thin_profile():
    presence = {"directors": True}
    out = score_completeness(presence)
    assert out["completeness_score"] == 20.0
    assert out["grade"] == "thin"


def test_empty_profile():
    out = score_completeness({})
    assert out["completeness_score"] == 0.0
    assert out["grade"] == "thin"
    assert len(out["missing"]) == 5


def test_enforcement_informational_not_required():
    # enforcement present but no required dims → still thin; flag surfaced separately
    out = score_completeness({"enforcement": True})
    assert out["has_enforcement"] is True
    assert out["completeness_score"] == 0.0


def test_evidence_grade_threshold_at_80():
    presence = {"directors": True, "shareholding": True, "auditors": True,
                "financials": True, "filings": False}
    out = score_completeness(presence)
    assert out["completeness_score"] == 80.0
    assert out["grade"] == "evidence_grade"

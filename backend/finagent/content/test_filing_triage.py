"""Unit tests for filing materiality triage (pure rules + LLM escalation)."""

from __future__ import annotations

from finagent.content.filing_triage import classify_materiality, should_alert, triage_filing


def test_auditor_resignation_high():
    r = classify_materiality({"subject": "Resignation of Statutory Auditor"})
    assert r["band"] == "HIGH"
    assert r["category"] == "auditor_change"
    assert should_alert(r)


def test_pledge_high():
    r = classify_materiality({"headline": "Creation of pledge over promoter shares"})
    assert r["band"] == "HIGH"
    assert r["category"] == "pledge"


def test_routine_board_meeting_suppressed():
    r = classify_materiality({"subject": "Board Meeting Intimation to be held on 30 June"})
    assert r["band"] == "ROUTINE"
    assert not should_alert(r)


def test_high_dominates_over_routine_cooccurrence():
    # board meeting (routine) to consider fundraise (high) → HIGH
    r = classify_materiality({"subject": "Board meeting to be held to consider QIP fund raising"})
    assert r["band"] == "HIGH"
    assert r["category"] == "fundraise"


def test_default_insolvency_high():
    r = classify_materiality({"body": "Company received notice under IBC for default in payment"})
    assert r["band"] == "HIGH"
    assert r["category"] == "default_insolvency"


def test_rating_downgrade_high():
    r = classify_materiality({"subject": "Credit rating downgrade by CRISIL"})
    assert r["band"] == "HIGH"
    assert r["category"] == "rating_change"


def test_unclassified_is_ambiguous_medium():
    r = classify_materiality({"subject": "Update on factory operations in Pune"})
    assert r["band"] == "MEDIUM"
    assert r["ambiguous"] is True


def test_empty_filing_routine():
    r = classify_materiality({})
    assert r["band"] == "ROUTINE"
    assert r["category"] == "empty"


def test_multiple_high_signals_higher_score():
    one = classify_materiality({"subject": "Pledge created"})
    two = classify_materiality({"subject": "Pledge created and resignation of auditor amid SEBI order"})
    assert two["score"] >= one["score"]
    assert len(two["reasons"]) >= 2


def test_llm_escalation_resolves_ambiguous():
    filing = {"subject": "Strategic update on operations"}
    r = triage_filing(filing, llm_classify=lambda f: "HIGH")
    assert r["band"] == "HIGH"
    assert "llm" in r["reasons"]
    assert r["ambiguous"] is False


def test_llm_error_keeps_rule_verdict():
    filing = {"subject": "Strategic update on operations"}
    def boom(_f):
        raise RuntimeError("llm down")
    r = triage_filing(filing, llm_classify=boom)
    assert r["band"] == "MEDIUM"  # original ambiguous verdict preserved
    assert "llm_error" in r["reasons"]


def test_llm_not_called_for_clear_high():
    calls = []
    def spy(f):
        calls.append(f); return "ROUTINE"
    r = triage_filing({"subject": "Resignation of auditor"}, llm_classify=spy)
    assert r["band"] == "HIGH"
    assert calls == []  # clear rule verdict → no LLM call

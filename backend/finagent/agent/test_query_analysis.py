"""Tests for chatbot query analysis (complexity, export intent, budgets)."""

from __future__ import annotations

from finagent.agent.query_analysis import (
    adaptive_wall_budget,
    classify_query_complexity,
    detect_export_intent,
    reflection_rounds_for_budget,
)


# ── Complexity classifier ────────────────────────────────────────────────────

def test_simple_query_no_verification():
    c = classify_query_complexity("What does ProspektLab do?")
    assert c.tier == "simple"
    assert c.enable_verification is False


def test_numeric_query_enables_verification():
    c = classify_query_complexity("What is the PE ratio and ROE of Infosys?")
    assert c.enable_verification is True
    assert c.signals["numeric"] is True


def test_comparative_query_complex():
    c = classify_query_complexity("Compare TCS vs Infosys on margins and growth")
    assert c.signals["comparative"] is True
    assert c.enable_verification is True
    assert c.tier in ("standard", "complex")


def test_governance_query_is_complex_and_verified():
    c = classify_query_complexity("Are there promoter pledge or auditor resignation red flags at Vodafone Idea?")
    assert c.signals["governance"] is True
    assert c.enable_verification is True
    assert c.tier == "complex"


def test_empty_query():
    c = classify_query_complexity("")
    assert c.tier == "simple"
    assert c.enable_verification is False


# ── Export intent ────────────────────────────────────────────────────────────

def test_export_phrase_detected():
    e = detect_export_intent("Research Reliance and generate a report")
    assert e.wants_export is True
    assert e.confidence >= 0.5


def test_export_save_as_pdf():
    e = detect_export_intent("Do a deep dive on HDFC Bank and save it as a PDF")
    assert e.wants_export is True


def test_export_verb_object_window():
    e = detect_export_intent("download the full document for TCS")
    assert e.wants_export is True
    assert any("download" in m for m in e.matched)


def test_no_export_intent_plain_query():
    e = detect_export_intent("Give me a deep analysis of TCS fundamentals")
    assert e.wants_export is False


def test_export_negation_suppressed():
    e = detect_export_intent("Analyze TCS but don't generate a report")
    assert e.negated is True
    assert e.wants_export is False


def test_export_verb_without_object_not_triggered():
    # "generate" alone (object is "analysis", not a doc) should not auto-export
    e = detect_export_intent("generate a quick analysis of the numbers")
    assert e.wants_export is False


# ── Adaptive budget ──────────────────────────────────────────────────────────

def test_simple_query_small_budget():
    b = adaptive_wall_budget("What is ProspektLab?")
    assert b == 55.0 or b >= 45.0  # base, clamped to min


def test_governance_query_larger_budget():
    simple = adaptive_wall_budget("Tell me about TCS")
    gov = adaptive_wall_budget("Deep governance review: promoter pledge, auditor changes, SEBI enforcement and related party transactions at Adani")
    assert gov > simple
    assert gov <= 300.0


def test_user_max_caps_budget():
    b = adaptive_wall_budget(
        "Compare governance and pledge risk across Adani, Reliance and Tata with numbers",
        user_max=90.0,
    )
    assert b <= 90.0


def test_budget_never_below_min():
    b = adaptive_wall_budget("hi", min_seconds=45.0)
    assert b >= 45.0


# ── Reflection rounds ────────────────────────────────────────────────────────

def test_reflection_rounds_capped_at_three():
    assert reflection_rounds_for_budget(300.0, 0.0, per_round_s=30.0) == 3


def test_reflection_rounds_zero_when_budget_spent():
    assert reflection_rounds_for_budget(60.0, 50.0, per_round_s=30.0) == 0


def test_reflection_rounds_partial():
    assert reflection_rounds_for_budget(120.0, 30.0, per_round_s=30.0) == 3 - 0  # remaining 90 → 3 rounds capped
    assert reflection_rounds_for_budget(95.0, 30.0, per_round_s=30.0) == 2       # remaining 65 → 2

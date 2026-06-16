from finagent.output.contracts import OutputMode, ResponseDepth
from finagent.synthesis import (
    _adapt_profile_for_timeout,
    _compact_chat_history,
    _sanitize_llm_memo,
    _should_inject_comparison_instructions,
    _synthesis_profile,
)


def test_standard_snapshot_profile_stays_latency_bounded():
    profile = _synthesis_profile(
        OutputMode.COMPANY_SNAPSHOT,
        ResponseDepth.STANDARD,
        "Analyze TCS and give me the latest snapshot",
    )

    assert profile["timeout_s"] == 35.0
    assert profile["max_tokens"] == 1800
    assert profile["digest_budget_chars"] == 5200


def test_deep_report_profile_keeps_larger_budget():
    profile = _synthesis_profile(
        OutputMode.DEEP_RESEARCH_REPORT,
        ResponseDepth.DEEP,
        "Build a full-scale deep research report on TCS",
    )

    assert profile["timeout_s"] == 180.0
    assert profile["max_tokens"] == 8000
    assert profile["digest_budget_chars"] > 5200


def test_standard_deep_lite_profile_downshifts_under_tight_timeout():
    base = _synthesis_profile(
        OutputMode.COMPANY_SNAPSHOT,
        ResponseDepth.STANDARD,
        "Analyze Reliance governance and valuation in depth",
        is_deep_lite=True,
    )

    tuned = _adapt_profile_for_timeout(
        base,
        timeout_s=22.0,
        depth=ResponseDepth.STANDARD,
        is_deep_lite=True,
    )

    assert tuned["max_tokens"] < base["max_tokens"]
    assert tuned["digest_budget_chars"] < base["digest_budget_chars"]


def test_standard_fast_profile_keeps_latency_bounded_under_short_timeout():
    base = _synthesis_profile(
        OutputMode.DIRECT_ANSWER,
        ResponseDepth.STANDARD,
        "What is TCS PE today?",
        is_deep_lite=False,
    )

    tuned = _adapt_profile_for_timeout(
        base,
        timeout_s=12.0,
        depth=ResponseDepth.STANDARD,
        is_deep_lite=False,
    )

    assert tuned["max_tokens"] <= 1400
    assert tuned["digest_budget_chars"] <= 4200


def test_comparison_instructions_only_for_company_comparison_mode():
    assert _should_inject_comparison_instructions(
        "Compare TCS vs Infosys on margins",
        OutputMode.COMPANY_COMPARISON,
    ) is True
    assert _should_inject_comparison_instructions(
        "Analyze valuation versus 5-year history",
        OutputMode.COMPANY_SNAPSHOT,
    ) is False


def test_sanitize_llm_memo_removes_artifacts_and_repairs_tail():
    raw = "Price is \u00e2\u201a\u00b9100.00 **[CONFLICT]** ****\n\nLimitations: data cut on P"
    cleaned = _sanitize_llm_memo(raw)

    assert "\u00e2\u201a\u00b9" not in cleaned
    assert "\u20b9100.00" in cleaned
    assert "[CONFLICT]" not in cleaned
    assert "****" not in cleaned
    assert not cleaned.endswith(" on P")


def test_standard_history_compaction_trims_context_aggressively():
    history = [
        {"role": "user", "content": "Question " + str(i) + " " + ("u" * 1200)}
        if i % 2 == 0
        else {"role": "assistant", "content": "Answer " + str(i) + " " + ("a" * 2000)}
        for i in range(8)
    ]

    compact = _compact_chat_history(
        history,
        focused=False,
        depth=ResponseDepth.STANDARD,
    )

    assert len(compact) <= 4
    for msg in compact:
        limit = 700 if msg["role"] == "assistant" else 500
        assert len(msg["content"]) <= limit


def test_focused_standard_history_drops_assistant_recap():
    history = [
        {"role": "assistant", "content": "Long memo " + ("x" * 1000)},
        {"role": "user", "content": "Tell me the latest risk in one paragraph"},
    ]

    compact = _compact_chat_history(
        history,
        focused=True,
        depth=ResponseDepth.STANDARD,
    )

    assert compact == [{"role": "user", "content": history[1]["content"][:420]}]

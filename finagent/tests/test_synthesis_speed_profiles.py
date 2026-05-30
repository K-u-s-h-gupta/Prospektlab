from finagent.output.contracts import OutputMode, ResponseDepth
from finagent.synthesis import _compact_chat_history, _synthesis_profile


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

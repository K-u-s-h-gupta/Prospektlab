"""Tests for the ten-specialist research wave."""

from __future__ import annotations

import asyncio
import json

from finagent.content.specialist_agents import (
    SPECIALIST_KINDS,
    SpecialistMemo,
    compute_quality_score,
    run_specialist_wave,
    summarise_wave,
    wave_to_prompt_block,
)


def _runa(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _good_response(kind: str) -> str:
    return json.dumps(
        {
            "headline": f"{kind.title()} headline",
            "body": (
                f"This is a substantive memo for the {kind} specialist with enough "
                "prose to count as covered content. It walks the reader through "
                "filings, ratios, and context anchored in NSE and BSE disclosures."
            ),
            "bullets": [
                "First evidence-backed point with a number 25%.",
                "Second filing-grounded observation.",
                "Third specific data point.",
            ],
            "metrics": [
                {"label": "Revenue", "value": "INR 1,200 cr", "period": "Q4 FY25", "source": "BSE filing"}
            ],
            "sources": [
                {"title": "BSE filing", "url": "https://www.bseindia.com/x", "source_type": "official"},
                {"title": "Livemint piece", "url": "https://www.livemint.com/x", "source_type": "press"},
            ],
        }
    )


def test_wave_runs_all_ten_and_strips_livemint() -> None:
    async def fake_llm(system: str, user: str) -> str:
        for kind in SPECIALIST_KINDS:
            if f"Specialist: {kind.title()}" in system:
                return _good_response(kind)
        return _good_response("financials")

    memos = _runa(run_specialist_wave("Reliance Industries", "Pipeline context", fake_llm))
    assert set(memos.keys()) == set(SPECIALIST_KINDS)
    for memo in memos.values():
        assert memo.has_content
        urls = [s["url"] for s in memo.sources]
        assert not any("livemint.com" in u for u in urls)
    summary = summarise_wave(memos)
    assert summary["quality_score"] == 100
    assert len(summary["kinds_covered"]) == 10


def test_wave_degrades_quality_on_partial_coverage() -> None:
    async def patchy_llm(system: str, user: str) -> str:
        for kind in ("financials", "risk", "news"):
            if f"Specialist: {kind.title()}" in system:
                return _good_response(kind)
        return "{}"

    memos = _runa(run_specialist_wave("Infosys", "ctx", patchy_llm, timeout_s=1.0))
    score = compute_quality_score(memos)
    assert score == 30


def test_wave_handles_llm_errors_without_aborting() -> None:
    async def boom(system: str, user: str) -> str:
        raise RuntimeError("network down")

    memos = _runa(run_specialist_wave("X Ltd", "", boom))
    assert set(memos.keys()) == set(SPECIALIST_KINDS)
    for memo in memos.values():
        assert memo.error.startswith("llm_error")
    assert compute_quality_score(memos) == 0


def test_prompt_block_truncates_and_marks_missing() -> None:
    memos = {
        "financials": SpecialistMemo(
            kind="financials",
            headline="Headline",
            body="Body prose " * 10,
            bullets=["a", "b"],
            sources=[{"title": "BSE", "url": "https://bseindia.com/x"}],
        ),
        "risk": SpecialistMemo(kind="risk", headline="", body="", error="timeout"),
    }
    block = wave_to_prompt_block(memos)
    assert "FINANCIALS" in block
    assert "RISK: not available" in block

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

from finagent.content.official_monitor import (
    _triage_event,
    get_monitor_status,
    record_scheduler_heartbeat,
    run_official_monitor,
)


def test_triage_event_skips_low_value_notice():
    result = _triage_event(
        "nse",
        {
            "title": "Closure of trading window for quarter end",
            "description": "Routine compliance certificate under regulation",
        },
    )

    assert result["generate"] is False
    assert result["skip_reason"] == "low_value"


async def _fake_generate(*args, **kwargs):
    class _Result:
        slug = "abc-results"
        title = "ABC results"
        publish_status = "published"
        generated_at = "2026-06-08T00:00:00+00:00"

    return _Result()


def test_official_monitor_generates_for_material_event(monkeypatch, tmp_path: Path):
    state_path = tmp_path / "official_monitor_state.json"

    monkeypatch.setattr("finagent.content.official_monitor._STATE_PATH", state_path)
    monkeypatch.setattr(
        "finagent.content.official_monitor.get_listed_companies",
        lambda nifty500_only=True: [
            {
                "company_name": "ABC Limited",
                "nse_symbol": "ABC",
                "bse_scrip_code": "",
                "isin": "INE000A01001",
            }
        ],
    )
    monkeypatch.setattr("finagent.content.official_monitor.fetch_sebi_news", lambda max_results=8: [])
    monkeypatch.setattr(
        "finagent.content.official_monitor.fetch_nse_corporate_filings",
        lambda symbol, years_back=1: [
            {
                "title": "Financial Results for the quarter ended March 2026",
                "description": "Official filing with detailed results.",
                "attachment_url": "https://www.nseindia.com/test.pdf",
                "announced_at": "2026-06-08T00:00:00+00:00",
            }
        ],
    )
    monkeypatch.setattr("finagent.content.official_monitor.fetch_bse_corporate_filings", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "finagent.content.official_monitor._stage_attachment_evidence",
        lambda source, record: {
            "attachment_required": True,
            "attachment_extraction_status": "ok",
            "attachment_text_sufficient": True,
            "attachment_type": "pdf",
            "attachment_parser": "pymupdf",
            "attachment_document_type": "pdf",
            "attachment_text": "Revenue rose 12% YoY and EBITDA margin improved.",
            "attachment_tables": [],
            "attachment_structured_facts": {"revenue_growth_yoy": "12%"},
        },
    )
    monkeypatch.setattr("finagent.content.official_monitor.generate_flash_article", AsyncMock(side_effect=_fake_generate))

    result = asyncio.run(
        run_official_monitor(
            requested_by="tester@example.com",
            company_batch_size=1,
            max_events_per_company=1,
        )
    )

    assert result["generated"] == 1
    assert result["published"] == 1
    assert result["failures"] == []
    assert state_path.is_file()
    saved = state_path.read_text(encoding="utf-8")
    assert "Sweep finished" in saved
    assert "Published article" in saved


def test_monitor_status_reports_scheduled_when_scheduler_heartbeat_is_fresh(monkeypatch, tmp_path: Path):
    state_path = tmp_path / "official_monitor_state.json"
    scheduler_path = tmp_path / "official_monitor_scheduler.json"

    monkeypatch.setattr("finagent.content.official_monitor._STATE_PATH", state_path)
    monkeypatch.setattr("finagent.content.official_monitor._SCHEDULER_STATE_PATH", scheduler_path)
    monkeypatch.setenv("FINAGENT_SCHEDULER_ENABLE_CRON", "1")
    monkeypatch.setattr("finagent.content.official_monitor._runtime_control_enabled", lambda *args, **kwargs: True)

    record_scheduler_heartbeat(
        status="running",
        note="Scheduler online and watching official sources",
        next_official_monitor_at="2026-06-08T00:10:00+00:00",
        job_count=3,
        pid=1234,
    )

    status = get_monitor_status()

    assert status["status"] == "scheduled"
    assert status["scheduler_status"] == "running"
    assert status["automation_mode"] == "automatic_topics"
    assert status["next_scheduled_run_at"] == "2026-06-08T00:10:00+00:00"
    assert status["fallback_daily_target"] >= 1
    assert status["fallback_remaining_today"] >= 0
    assert isinstance(status["fallback_review_reasons"], list)
    assert status["current_run"] == {}
    assert isinstance(status["activity_log"], list)


def test_monitor_status_reports_manual_only_when_cron_is_disabled(monkeypatch, tmp_path: Path):
    state_path = tmp_path / "official_monitor_state.json"
    scheduler_path = tmp_path / "official_monitor_scheduler.json"

    monkeypatch.setattr("finagent.content.official_monitor._STATE_PATH", state_path)
    monkeypatch.setattr("finagent.content.official_monitor._SCHEDULER_STATE_PATH", scheduler_path)
    monkeypatch.setenv("FINAGENT_SCHEDULER_ENABLE_CRON", "0")
    monkeypatch.setattr("finagent.content.official_monitor._runtime_control_enabled", lambda *args, **kwargs: True)

    status = get_monitor_status()

    assert status["status"] == "manual_only"
    assert status["scheduler_status"] == "manual_only"
    assert status["fallback_daily_target"] >= 1
    assert status["fallback_remaining_today"] >= 0


def test_fallback_can_publish_multiple_articles_in_single_sweep(monkeypatch, tmp_path: Path):
    state_path = tmp_path / "official_monitor_state.json"
    monkeypatch.setattr("finagent.content.official_monitor._STATE_PATH", state_path)
    monkeypatch.setattr(
        "finagent.content.official_monitor.get_listed_companies",
        lambda nifty500_only=True: [
            {
                "company_name": "ABC Limited",
                "nse_symbol": "ABC",
                "bse_scrip_code": "",
                "isin": "INE000A01001",
            }
        ],
    )
    monkeypatch.setattr("finagent.content.official_monitor.fetch_sebi_news", lambda max_results=8: [])
    monkeypatch.setattr("finagent.content.official_monitor.fetch_nse_corporate_filings", lambda *args, **kwargs: [])
    monkeypatch.setattr("finagent.content.official_monitor.fetch_bse_corporate_filings", lambda *args, **kwargs: [])
    monkeypatch.setattr("finagent.content.official_monitor._collect_fallback_news", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "finagent.content.official_monitor._build_fallback_candidates",
        lambda items, universe: [
            {
                "group_key": f"theme:market-{idx}",
                "topic_key": f"topic-{idx}",
                "target": f"Fallback Topic {idx}",
                "content_type": "trend",
                "objective": "Write a source-backed business analysis.",
                "source_url": "https://www.reuters.com/world/india/",
                "supporting_sources": [],
                "score": 9.0 - idx,
            }
            for idx in range(5)
        ],
    )

    async def _fake_fallback_generate(*args, **kwargs):
        class _Result:
            slug = f"fallback-{kwargs.get('job_id', 'x')}"
            title = "Fallback analysis"
            publish_status = "published"
            confidence_score = 97
            generated_at = "2026-06-08T00:00:00+00:00"

        return _Result()

    monkeypatch.setattr(
        "finagent.content.official_monitor.generate_flash_article",
        AsyncMock(side_effect=_fake_fallback_generate),
    )

    result = asyncio.run(
        run_official_monitor(
            requested_by="tester@example.com",
            company_batch_size=1,
            max_events_per_company=1,
        )
    )

    assert result["generated"] == 3
    assert result["published"] == 3
    assert result["drafts"] == 0

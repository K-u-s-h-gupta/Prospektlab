import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from finagent.content import official_monitor as _om
from finagent.content.official_monitor import (
    _triage_event,
    get_monitor_status,
    record_scheduler_heartbeat,
    run_official_monitor,
)


@pytest.fixture(autouse=True)
def _reset_cross_source_seen():
    """The official monitor module keeps a runtime cross-source dedup cache
    (_CROSS_SOURCE_SEEN) so the same event from NSE/BSE/SEBI is generated only
    once per process. Tests reuse identical titles across cases, which would
    otherwise leak the fingerprint between tests and cause spurious skips."""
    _om._CROSS_SOURCE_SEEN.clear()
    yield
    _om._CROSS_SOURCE_SEEN.clear()


def test_load_watch_universe_uses_bundled_isin_master_when_db_unavailable(monkeypatch, tmp_path: Path):
    missing_bundle = tmp_path / "isin_master.json"
    monkeypatch.setattr("finagent.content.official_monitor.get_listed_companies", lambda *args, **kwargs: [])
    monkeypatch.setattr("finagent.content.official_monitor.finagent_data_path", lambda *parts: missing_bundle)

    universe = _om._load_watch_universe()

    assert len(universe) > 0
    first = universe[0]
    assert first.get("company_name")
    assert first.get("nse_symbol") or first.get("isin")


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


def test_triage_event_enforces_materiality_and_urgency_thresholds(monkeypatch):
    monkeypatch.setattr("finagent.content.official_monitor._OFFICIAL_TRIAGE_MIN_MATERIALITY", 75)
    monkeypatch.setattr("finagent.content.official_monitor._OFFICIAL_TRIAGE_MIN_URGENCY", 71)
    result = _triage_event(
        "nse",
        {
            "title": "Financial Results for quarter ended March 2026",
            "description": "Official filing with full numbers and discussion.",
            "attachment_url": "https://www.nseindia.com/test.pdf",
        },
    )

    assert result["materiality_score"] >= 75
    assert result["urgency_score"] < 71
    assert result["generate"] is False
    assert result["skip_reason"] == "not_urgent_enough"
    assert result["materiality_tier"] in {"material_with_attachment", "material_without_attachment"}
    assert result["selection_reason"] in {"urgent_material_official_event", "evidence_rich_official_update", "material_official_update"}


async def _fake_generate(*args, **kwargs):
    class _Result:
        slug = "abc-results"
        title = "ABC results"
        publish_status = "published"
        generated_at = "2026-06-08T00:00:00+00:00"

    return _Result()


def test_official_monitor_generates_for_material_event(monkeypatch, tmp_path: Path):
    state_path = tmp_path / "official_monitor_state.json"
    recent_announced_at = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(microsecond=0).isoformat()

    monkeypatch.setattr("finagent.content.official_monitor._STATE_PATH", state_path)
    monkeypatch.setattr(
        "finagent.content.official_monitor.get_listed_companies",
        lambda *args, **kwargs: [
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
                "announced_at": recent_announced_at,
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
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert any("Sweep finished" in str(entry.get("message") or "") for entry in saved.get("activity_log") or [])
    assert any("Published article" in str(entry.get("message") or "") for entry in saved.get("activity_log") or [])
    latest = (saved.get("recent_items") or [])[0]
    assert latest.get("materiality_tier") in {"material_with_attachment", "material_without_attachment"}
    assert int(latest.get("urgency_score") or 0) >= 65
    assert latest.get("selection_reason")
    assert isinstance(latest.get("quality_blockers"), list)


def test_official_monitor_holds_material_but_evidence_thin(monkeypatch, tmp_path: Path):
    state_path = tmp_path / "official_monitor_state.json"
    recent_announced_at = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0).isoformat()

    monkeypatch.setattr("finagent.content.official_monitor._STATE_PATH", state_path)
    monkeypatch.setattr(
        "finagent.content.official_monitor.get_listed_companies",
        lambda *args, **kwargs: [
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
                "description": "Official filing with limited text in attachment.",
                "attachment_url": "https://www.nseindia.com/test.pdf",
                "announced_at": recent_announced_at,
            }
        ],
    )
    monkeypatch.setattr("finagent.content.official_monitor.fetch_bse_corporate_filings", lambda *args, **kwargs: [])
    monkeypatch.setattr("finagent.content.official_monitor._collect_fallback_news", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "finagent.content.official_monitor._stage_attachment_evidence",
        lambda source, record: {
            "attachment_required": True,
            "attachment_extraction_status": "ok",
            "attachment_text_sufficient": False,
            "attachment_type": "pdf",
            "attachment_parser": "docling",
            "attachment_document_type": "pdf",
            "attachment_text": "Thin content",
            "attachment_tables": [],
            "attachment_structured_facts": {},
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

    assert result["generated"] == 0
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    latest = (saved.get("recent_items") or [])[0]
    assert latest.get("status") == "under_review"
    assert latest.get("review_reason") == "material_but_evidence_thin"
    assert "material_but_evidence_thin" in (latest.get("quality_blockers") or [])


def test_official_monitor_propagates_publish_gate_blockers(monkeypatch, tmp_path: Path):
    state_path = tmp_path / "official_monitor_state.json"
    recent_announced_at = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0).isoformat()

    monkeypatch.setattr("finagent.content.official_monitor._STATE_PATH", state_path)
    monkeypatch.setattr(
        "finagent.content.official_monitor.get_listed_companies",
        lambda *args, **kwargs: [
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
                "announced_at": recent_announced_at,
            }
        ],
    )
    monkeypatch.setattr("finagent.content.official_monitor.fetch_bse_corporate_filings", lambda *args, **kwargs: [])
    monkeypatch.setattr("finagent.content.official_monitor._collect_fallback_news", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "finagent.content.official_monitor._stage_attachment_evidence",
        lambda source, record: {
            "attachment_required": True,
            "attachment_extraction_status": "ok",
            "attachment_text_sufficient": True,
            "attachment_type": "pdf",
            "attachment_parser": "docling",
            "attachment_document_type": "pdf",
            "attachment_text": "Revenue rose 12% YoY and EBITDA margin improved.",
            "attachment_tables": [],
            "attachment_structured_facts": {"revenue_growth_yoy": "12%"},
        },
    )

    async def _fake_draft(*args, **kwargs):
        class _Result:
            slug = "abc-results-draft"
            title = "ABC results draft"
            publish_status = "draft"
            generated_at = "2026-06-08T00:00:00+00:00"
            publish_reasons = ["draft"]

        return _Result()

    monkeypatch.setattr("finagent.content.official_monitor.generate_flash_article", AsyncMock(side_effect=_fake_draft))
    monkeypatch.setattr(
        "finagent.content.official_monitor._load_article_gate_snapshot",
        lambda slug, route_base: {
            "publish_gate_status": "draft",
            "publish_gate_score": 88,
            "review_reason": "missing_company_history",
            "quality_blockers": ["missing_company_history", "missing_management_context"],
            "source_count": 4,
            "word_count": 900,
            "evidence_claim_count": 5,
            "document_evidence_status": "ready",
            "context_enrichment_status": "insufficient",
        },
    )

    result = asyncio.run(
        run_official_monitor(
            requested_by="tester@example.com",
            company_batch_size=1,
            max_events_per_company=1,
        )
    )

    assert result["generated"] == 1
    assert result["published"] == 0
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    latest = (saved.get("recent_items") or [])[0]
    assert latest.get("status") == "draft"
    assert latest.get("review_reason") == "missing_company_history"
    blockers = latest.get("quality_blockers") or []
    assert "missing_company_history" in blockers
    assert "missing_management_context" in blockers


def test_official_monitor_skips_official_items_older_than_24_hours(monkeypatch, tmp_path: Path):
    state_path = tmp_path / "official_monitor_state.json"
    stale_announced_at = (datetime.now(timezone.utc) - timedelta(hours=48)).replace(microsecond=0).isoformat()

    monkeypatch.setattr("finagent.content.official_monitor._STATE_PATH", state_path)
    monkeypatch.setattr(
        "finagent.content.official_monitor.get_listed_companies",
        lambda *args, **kwargs: [
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
                "announced_at": stale_announced_at,
            }
        ],
    )
    monkeypatch.setattr("finagent.content.official_monitor.fetch_bse_corporate_filings", lambda *args, **kwargs: [])
    monkeypatch.setattr("finagent.content.official_monitor._collect_fallback_news", AsyncMock(return_value=[]))
    monkeypatch.setattr("finagent.content.official_monitor.generate_flash_article", AsyncMock(side_effect=_fake_generate))

    result = asyncio.run(
        run_official_monitor(
            requested_by="tester@example.com",
            company_batch_size=1,
            max_events_per_company=1,
        )
    )

    assert result["generated"] == 0
    assert result["published"] == 0
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert any("older than 24 hours" in str(entry.get("message") or "") for entry in saved.get("activity_log") or [])


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
    monkeypatch.setenv("FINAGENT_OFFICIAL_MONITOR_REALTIME_LOOP", "0")
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
        lambda *args, **kwargs: [
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
                "supporting_sources": [
                    {
                        "url": "https://www.reuters.com/world/india/markets/",
                        "source": "Reuters",
                        "title": f"Markets pulse {idx}",
                    },
                    {
                        "url": "https://economictimes.indiatimes.com/markets/stocks/news",
                        "source": "Economic Times",
                        "title": f"Sector rotation {idx}",
                    },
                    {
                        "url": "https://www.livemint.com/market",
                        "source": "Mint",
                        "title": f"Business trend {idx}",
                    },
                ],
                "score": 9.0 - idx,
            }
            for idx in range(5)
        ],
    )
    monkeypatch.setattr(
        "finagent.content.official_monitor._load_article_gate_snapshot",
        lambda slug, route_base: {
            "publish_gate_status": "publish",
            "publish_gate_score": 98,
            "review_reason": "",
            "source_count": 4,
            "word_count": 1100,
            "evidence_claim_count": 8,
            "document_evidence_status": "ready",
            "context_enrichment_status": "ready",
        },
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

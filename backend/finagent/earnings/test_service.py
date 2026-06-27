from datetime import date, datetime, timedelta, timezone

from finagent.earnings import service


def test_detail_returns_none_when_db_unavailable(monkeypatch):
    monkeypatch.setattr(service, "_query_available", lambda: False)

    assert service.get_earnings_detail("NMDC", date.today().isoformat()) is None


def test_db_detail_row_normalizes_partial_json_payloads():
    row = {
        "event_uid": "evt-1",
        "symbol": "TEST",
        "company_name": "Test Limited",
        "sector": "Industrials",
        "meeting_date": date(2026, 6, 24),
        "timing": "Post-market",
        "fiscal_quarter": "Q1 FY27",
        "highlights_json": {},
        "management_json": {},
        "transcript_json": {},
        "documents_json": {},
        "financials_json": {},
        "attachment_urls": ["https://example.com/filing.pdf"],
        "summary": "",
        "updated_at": "2026-06-24T10:00:00Z",
    }

    detail = service._detail_row_from_db(row)

    assert detail["headline_highlights"] == []
    assert detail["management_commentary"] == []
    assert detail["transcript"] == {"prepared_remarks": [], "qa": []}
    assert detail["financials"] == {"rows": []}
    assert detail["documents"] == [
        {
            "type": "Official attachment",
            "title": "Exchange filing",
            "url": "https://example.com/filing.pdf",
            "storage_path": "",
        }
    ]


def test_db_company_row_normalizes_highlights_and_fallbacks():
    row = {
        "event_uid": "evt-2",
        "symbol": "TEST",
        "name": "Test Limited",
        "sector": None,
        "index_bucket": None,
        "market_cap_bucket": None,
        "date": "2026-06-24",
        "timing": None,
        "fiscal_quarter": None,
        "highlights": "[]",
        "attachment_urls": ["https://example.com/filing.pdf"],
        "summary": "Revenue rose 12% and PAT improved 8% as margins expanded during the quarter.",
    }

    company = service._company_row_from_db(row)

    assert company["sector"] == "Other"
    assert company["index"] == "All"
    assert company["market_cap"] == "All"
    assert company["timing"] == "TAS"
    assert company["highlights"]
    assert company["highlights"][0]["url"] == "https://example.com/filing.pdf"

def test_result_preserves_parser_financial_payload(monkeypatch):
    monkeypatch.setattr(
        service,
        "_query_result_detail_row",
        lambda _symbol, _selected: {
            "symbol": "TEST",
            "name": "Test Limited",
            "sector": "Industrials",
            "date": "2026-06-24",
            "timing": "Post-market",
            "fiscal_quarter": "Q1 FY27",
            "headline_highlights": [],
            "transcript": {"prepared_remarks": [], "qa": []},
            "documents": [],
            "summary": "",
            "financials": {
                "source": "pymupdf_local",
                "rows": [{"key": "revenue", "label": "Revenue", "unit": "Rs Cr", "current": 1200}],
                "consolidated_tables": [{"page_number": 1, "rows": [["Revenue", "1200"]]}],
            },
        },
    )
    monkeypatch.setattr(service, "get_earnings_history", lambda _symbol, limit=8, fallback_demo=False: [])

    from finagent.earnings import yahoo_scraper

    monkeypatch.setattr(yahoo_scraper, "fetch_current_price", lambda _symbol: None)

    result = service.get_earnings_result("TEST", "2026-06-24")

    assert result is not None
    assert result["financials"]["source"] == "pymupdf_local"
    assert result["financials"]["rows"][0]["current"] == 1200
    assert result["financials"]["consolidated_tables"][0]["rows"][0][0] == "Revenue"

def test_result_falls_back_to_announcement_when_detail_missing(monkeypatch):
    monkeypatch.setattr(
        service,
        "_query_result_detail_row",
        lambda _symbol, _selected: {
            "symbol": "TEST",
            "name": "Test Limited",
            "sector": "Industrials",
            "date": "2026-06-24",
            "timing": "Post-market",
            "fiscal_quarter": "Q1 FY27",
            "headline_highlights": [
                {"text": "Revenue rose after the declared result.", "url": "https://example.com/result.pdf", "source_label": "official filing"}
            ],
            "transcript": {"prepared_remarks": [], "qa": []},
            "documents": [
                {"type": "Official attachment", "title": "Exchange filing", "url": "https://example.com/result.pdf", "storage_path": ""}
            ],
            "summary": "Revenue rose after the declared result.",
            "financials": {"source": "announcement_fallback", "rows": []},
        },
    )
    monkeypatch.setattr(service, "get_earnings_history", lambda _symbol, limit=8, fallback_demo=False: [])

    from finagent.earnings import yahoo_scraper

    monkeypatch.setattr(yahoo_scraper, "fetch_current_price", lambda _symbol: None)

    result = service.get_earnings_result("TEST", "2026-06-24")

    assert result is not None
    assert result["symbol"] == "TEST"
    assert result["documents"][0]["url"] == "https://example.com/result.pdf"
    assert result["financials"]["source"] == "announcement_fallback"

def test_result_does_not_call_live_price_fetch(monkeypatch):
    monkeypatch.setattr(
        service,
        "_query_result_detail_row",
        lambda _symbol, _selected: {
            "symbol": "TEST",
            "name": "Test Limited",
            "sector": "Industrials",
            "date": "2026-06-24",
            "timing": "Post-market",
            "fiscal_quarter": "Q1 FY27",
            "headline_highlights": [],
            "transcript": {"prepared_remarks": [], "qa": []},
            "documents": [],
            "summary": "",
            "financials": {"rows": []},
        },
    )
    monkeypatch.setattr(service, "get_earnings_history", lambda _symbol, limit=8, fallback_demo=False: [])

    from finagent.earnings import yahoo_scraper

    def fail_fetch(_symbol):
        raise AssertionError("live price fetch should not run in result request")

    monkeypatch.setattr(yahoo_scraper, "fetch_current_price", fail_fetch)

    result = service.get_earnings_result("TEST", "2026-06-24")

    assert result is not None
    assert result["current_price"] is None


def test_on_demand_detail_parse_stores_detail(monkeypatch):
    statuses = []
    monkeypatch.setattr(service, "_query_detail_row", lambda _symbol, _selected: None)
    monkeypatch.setattr(
        service,
        "_query_announcement_record_for_parse",
        lambda _symbol, _selected: {
            "event_uid": "evt-parse",
            "symbol": "TEST",
            "company_name": "Test Limited",
            "meeting_date": "2026-06-24",
            "attachment_urls": ["https://example.com/result.pdf"],
            "processing_status": "stored",
        },
    )
    monkeypatch.setattr(service, "_set_announcement_processing_status", lambda _event_uid, status: statuses.append(status) or True)
    monkeypatch.setattr(service, "upsert_detail", lambda detail: detail["event_uid"] == "evt-parse")

    from finagent.earnings import scraper

    monkeypatch.setattr(
        scraper,
        "build_detail_from_announcement",
        lambda record: {"event_uid": record["event_uid"], "symbol": record["symbol"], "financials": {"rows": []}},
    )

    result = service.ensure_earnings_detail_for_result("TEST", "2026-06-24")

    assert result == {"stored": True, "event_uid": "evt-parse"}
    assert statuses == ["parsing", "parsed"]

def test_on_demand_detail_parse_skips_recent_parsing(monkeypatch):
    monkeypatch.setattr(service, "_query_detail_row", lambda _symbol, _selected: None)
    monkeypatch.setattr(
        service,
        "_query_announcement_record_for_parse",
        lambda _symbol, _selected: {
            "event_uid": "evt-recent",
            "symbol": "TEST",
            "company_name": "Test Limited",
            "meeting_date": "2026-06-24",
            "attachment_urls": ["https://example.com/result.pdf"],
            "processing_status": "parsing",
            "updated_at": datetime.now(timezone.utc),
        },
    )

    def fail_status(_event_uid, _status):
        raise AssertionError("recent parsing job should not be restarted")

    monkeypatch.setattr(service, "_set_announcement_processing_status", fail_status)

    result = service.ensure_earnings_detail_for_result("TEST", "2026-06-24")

    assert result == {"stored": False, "reason": "already_parsing"}


def test_on_demand_detail_parse_retries_stale_parsing(monkeypatch):
    statuses = []
    monkeypatch.setattr(service, "_query_detail_row", lambda _symbol, _selected: None)
    monkeypatch.setattr(
        service,
        "_query_announcement_record_for_parse",
        lambda _symbol, _selected: {
            "event_uid": "evt-stale",
            "symbol": "TEST",
            "company_name": "Test Limited",
            "meeting_date": "2026-06-24",
            "attachment_urls": ["https://example.com/result.pdf"],
            "processing_status": "parsing",
            "updated_at": datetime.now(timezone.utc) - timedelta(minutes=30),
        },
    )
    monkeypatch.setattr(service, "_set_announcement_processing_status", lambda _event_uid, status: statuses.append(status) or True)
    monkeypatch.setattr(service, "upsert_detail", lambda detail: detail["event_uid"] == "evt-stale")

    from finagent.earnings import scraper

    monkeypatch.setattr(
        scraper,
        "build_detail_from_announcement",
        lambda record: {"event_uid": record["event_uid"], "symbol": record["symbol"], "financials": {"rows": []}},
    )

    result = service.ensure_earnings_detail_for_result("TEST", "2026-06-24")

    assert result == {"stored": True, "event_uid": "evt-stale"}
    assert statuses == ["parsing", "parsed"]

def test_local_ai_summary_fallback_uses_extracted_metrics_without_hallucinating():
    rows = [
        {"key": "revenue", "label": "Revenue", "unit": "Rs Cr", "current": 60.62, "qoq_pct": 3.2, "yoy_pct": 107.1},
        {"key": "pat", "label": "PAT", "unit": "Rs Cr", "current": 0.95, "qoq_pct": -42.4, "yoy_pct": -38.3},
        {"key": "ebitda", "label": "EBITDA", "unit": "Rs Cr", "current": 2.31, "qoq_pct": -31.2, "yoy_pct": -1.7},
        {"key": "eps", "label": "EPS", "unit": "Rs", "current": 0.05, "qoq_pct": -37.5, "yoy_pct": -44.4},
        {"key": "ebitda_margin", "label": "EBITDA Margin", "unit": "%", "current": 3.81, "qoq_pct": -33.4, "yoy_pct": -52.6},
    ]

    summary = service._build_local_ai_summary(
        company_name="Ajooni Biotech",
        symbol="AJOONI",
        fiscal_quarter="Q4 FY26",
        meeting_date="2026-05-28",
        financials_payload={"rows": rows},
        highlights=[],
    )

    assert summary["rating"] == "Neutral"
    assert "Revenue was Rs 60.62 Cr" in summary["performance_narrative"]
    assert "Profit after tax was Rs 0.95 Cr" in summary["performance_narrative"]
    assert "No explicit management guidance" in summary["key_highlights"]["management_guidance"]
    assert "No order book" in summary["key_highlights"]["order_book"]
    assert "not present in the parsed text" in summary["confidence_factors"]

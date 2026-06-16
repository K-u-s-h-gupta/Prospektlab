from __future__ import annotations

from types import SimpleNamespace

from finagent.ingestion.azure_doc_intel import ExtractedTable
from finagent.ikg.document_selector import (
    PagePreview,
    build_document_sections_from_extraction,
    pages_to_ranges,
    select_useful_annual_report_pages,
)
from finagent.ikg.db import get_database_url, is_supabase_database_url
from finagent.ikg.graph_client import IKGClient, InMemoryGraphBackend
from finagent.ikg.pipeline.scheduler import (
    _build_scheduler,
    _monitor_batch_size,
    _monitor_events_per_company,
    _official_monitor_interval_minutes,
)
from finagent.ikg.scrapers.annual_reports import (
    _is_annual_report_announcement,
    _normalize_bse_attachment_url,
    _parse_bse_annual_report_json,
    sanitize_annual_report_pdf_url,
)
from finagent.ikg.scrapers.bse_eod import pick_bse_eod_filename
from finagent.ikg.scrapers.bse_shp import parse_bse_shp_html, parse_bse_shp_response, parse_bse_shp_xbrl
from finagent.ikg.scrapers.concall_transcripts import _is_transcript_announcement
from finagent.ikg.scrapers.corporate_governance_directors import (
    _is_governance_announcement,
    parse_governance_directors_from_payload,
    parse_governance_directors_from_text,
)
from finagent.ikg.scrapers.financial_data import cross_validate_financials
from finagent.ikg.scrapers.director_kmp_enricher import parse_director_kmp_from_text
from finagent.ikg.scrapers.mca_companies import build_mca_export_payload, extract_mca_export_form
from finagent.ikg.scrapers.mca_directors import parse_mca_filtered_directors
from finagent.ikg.scrapers.nse_index import _normalize_company_name_for_match
from finagent.ikg.scrapers.sebi_corporate_filings import (
    _attachment_candidates_for_record,
    _category_for_announcement,
    _extract_with_fallback_candidates,
    _normalize_attachment_url,
    _store_corporate_action_for_record,
    _store_xbrl_for_record,
    parse_sebi_corporate_filing_page,
)
from finagent.ikg.scrapers.xbrl_utils import (
    extract_auditor_names_from_text,
    extract_corporate_action_from_text,
    is_probable_xbrl,
    parse_xbrl_facts,
    summarize_xbrl_facts,
)
from finagent.ikg.scrapers import sebi_enforcement
from finagent.ikg.scrapers.sebi_enforcement import _parse_records_window, parse_sebi_orders_html


def test_supabase_db_url_is_postgres_compatible(monkeypatch):
    monkeypatch.delenv("IKG_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://postgres.example:secret@aws-0-ap-south-1.pooler.supabase.com:6543/postgres?sslmode=require",
    )

    db_url = get_database_url()

    assert "pooler.supabase.com" in db_url
    assert is_supabase_database_url(db_url)


def test_scheduler_registers_official_source_jobs(monkeypatch):
    monkeypatch.setenv("FINAGENT_OFFICIAL_MONITOR_REALTIME_LOOP", "0")
    scheduler = _build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert "mca_company_master_monthly" in job_ids
    assert "sebi_enforcement_weekly" in job_ids
    assert "sebi_corporate_filings_weekly" in job_ids
    assert "annual_reports_weekly" in job_ids
    assert "concall_transcripts_weekly" in job_ids
    assert "director_kmp_enrichment_weekly" in job_ids
    assert "pipeline_health_6h" in job_ids
    assert "official_content_monitor_10m" in job_ids
    assert "scheduler_heartbeat_2m" in job_ids
    assert "dreaming_layer_nightly" in job_ids


def test_scheduler_realtime_loop_skips_official_monitor_cron_jobs(monkeypatch):
    monkeypatch.setenv("FINAGENT_OFFICIAL_MONITOR_REALTIME_LOOP", "1")
    scheduler = _build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert "official_content_monitor_10m" not in job_ids
    assert "scheduler_heartbeat_2m" not in job_ids


def test_scheduler_realtime_defaults(monkeypatch):
    monkeypatch.setenv("FINAGENT_OFFICIAL_MONITOR_REALTIME", "1")
    monkeypatch.delenv("FINAGENT_OFFICIAL_MONITOR_INTERVAL_MINUTES", raising=False)
    monkeypatch.delenv("FINAGENT_OFFICIAL_MONITOR_BATCH_SIZE", raising=False)
    monkeypatch.delenv("FINAGENT_OFFICIAL_MONITOR_MAX_EVENTS_PER_COMPANY", raising=False)

    assert _official_monitor_interval_minutes() == 1
    assert _monitor_batch_size() == 40
    assert _monitor_events_per_company() == 4


def test_scheduler_realtime_knobs_are_clamped(monkeypatch):
    monkeypatch.setenv("FINAGENT_OFFICIAL_MONITOR_REALTIME", "1")
    monkeypatch.setenv("FINAGENT_OFFICIAL_MONITOR_INTERVAL_MINUTES", "0")
    monkeypatch.setenv("FINAGENT_OFFICIAL_MONITOR_BATCH_SIZE", "9999")
    monkeypatch.setenv("FINAGENT_OFFICIAL_MONITOR_MAX_EVENTS_PER_COMPANY", "99")

    assert _official_monitor_interval_minutes() == 1
    assert _monitor_batch_size() == 500
    assert _monitor_events_per_company() == 20


def test_sebi_orders_html_parser_extracts_pdf_order():
    html = """
    <html><body>
      <a href="/enforcement/orders/jun-2026/adjudication-order-in-the-matter-of-acme-limited-june-03-2026.pdf">
        Adjudication Order in the matter of ACME Limited June 03, 2026
      </a>
    </body></html>
    """

    orders = parse_sebi_orders_html(
        html,
        category="adjudication",
        source_url="https://www.sebi.gov.in/enforcement/orders/adjudication-orders.html",
    )

    assert len(orders) == 1
    assert orders[0]["category"] == "adjudication"
    assert orders[0]["pdf_url"].startswith("https://www.sebi.gov.in/")
    assert str(orders[0]["order_date"]) == "2026-06-03"


def test_sebi_corporate_filing_parser_classifies_required_categories():
    html = """
    <table>
      <tr>
        <td>2</td>
        <td><p><strong>Shareholding Patterns</strong></p></td>
        <td><a href="https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern">
          https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern
        </a></td>
      </tr>
      <tr>
        <td>3</td>
        <td><p><strong>Business Responsibility And Sustainability Reports</strong></p></td>
        <td><a href="https://www.nseindia.com/companies-listing/corporate-filings-bussiness-sustainabilitiy-reports">
          https://www.nseindia.com/companies-listing/corporate-filings-bussiness-sustainabilitiy-reports
        </a></td>
      </tr>
      <tr>
        <td>7</td>
        <td><p><strong>Related Party Transactions</strong></p></td>
        <td><a href="https://www.nseindia.com/companies-listing/related-party-transactions">
          https://www.nseindia.com/companies-listing/related-party-transactions
        </a></td>
      </tr>
    </table>
    """

    records = parse_sebi_corporate_filing_page(html)
    categories = {record["category"] for record in records}
    exchanges = {record["exchange"] for record in records}

    assert "shareholding_pattern" in categories
    assert "brsr" in categories
    assert "related_party_transactions" in categories
    assert {"NSE", "BSE"} <= exchanges


def test_corporate_filing_announcement_classifier_handles_exchange_rows():
    assert (
        _category_for_announcement(
            "Compliances-Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate",
            "Statement of investor complaints for the quarter ended March 2026",
        )
        == "investor_complaints"
    )
    assert (
        _category_for_announcement(
            "Announcement under Regulation 30 (LODR)-Analyst / Investor Meet - Outcome",
            "Trading window closure under SEBI PIT Regulations",
        )
        == "insider_trading"
    )
    assert _normalize_attachment_url(
        "sample.pdf",
        "https://www.bseindia.com",
    ).startswith("https://www.bseindia.com/xml-data/corpfiling/AttachLive/")


def test_bse_shp_parser_handles_variant_json_rows():
    parsed = parse_bse_shp_response(
        {
            "Table": [
                {
                    "ShareHolderCategory": "Promoter and Promoter Group",
                    "ShareholPercentage": "51.25",
                    "PledgePercentage": "2.5",
                    "ShareHolderName": "ACME Promoters",
                },
                {"CATEGORY": "Foreign Institutional Investors", "percentage": "12.25"},
                {"CATEGORY": "Public", "percentage": "36.50"},
            ]
        },
        scrip_code="500001",
        quarter="202603",
    )

    assert parsed["total_promoter_holding_pct"] == 51.25
    assert parsed["total_pledge_pct"] == 2.5
    assert parsed["fii_holding_pct"] == 12.25
    assert parsed["public_holding_pct"] == 36.5


def test_bse_shp_html_parser_collects_filing_links():
    html = """
    <a href="/xml-data/corpfiling/AttachLive/shareholding_500001_202603.xml">XBRL</a>
    <a href="/xml-data/corpfiling/AttachLive/shareholding_500001_202603.pdf">PDF</a>
    """

    parsed = parse_bse_shp_html(
        html,
        scrip_code="500001",
        quarter="202603",
        source_url="https://www.bseindia.com/corporates/Sharehold_Searchnew?scripcd=500001",
    )

    assert parsed is not None
    links = parsed["raw_data"]["filing_links"]
    assert len(links) == 2
    assert links[0]["url"].startswith("https://www.bseindia.com/")


def test_bse_shp_xbrl_parser_extracts_aggregate_percentages():
    xml = """
    <xbrl>
      <ShareholdingOfPromoterAndPromoterGroupPercentage>51.25</ShareholdingOfPromoterAndPromoterGroupPercentage>
      <PledgedOrOtherwiseEncumberedSharesPercentage>2.50</PledgedOrOtherwiseEncumberedSharesPercentage>
      <PublicShareholdingPercentage>48.75</PublicShareholdingPercentage>
    </xbrl>
    """

    parsed = parse_bse_shp_xbrl(
        xml,
        scrip_code="500001",
        quarter="202603",
        source_url="https://www.bseindia.com/xml-data/corpfiling/AttachLive/shareholding.xml",
    )

    assert parsed["total_promoter_holding_pct"] == 51.25
    assert parsed["total_pledge_pct"] == 2.5
    assert parsed["public_holding_pct"] == 48.75


def test_corporate_action_announcement_is_classified():
    assert (
        _category_for_announcement(
            "Board approves bonus issue and record date",
            "Corporate action: issue of bonus shares in the ratio 1:1",
        )
        == "corporate_actions"
    )
    parsed = extract_corporate_action_from_text(
        "Approved bonus issue in the ratio of 1:1. Record Date 15-Jul-2026."
    )
    assert parsed["action_type"] == "bonus"
    assert parsed["ratio"] == "1:1"
    assert parsed["record_date_raw"] == "15-Jul-2026"


def test_bse_attachment_normalizer_routes_structured_files_to_attach_live():
    assert _normalize_attachment_url(
        "corp_action_2026.xml",
        "https://www.bseindia.com",
    ) == "https://www.bseindia.com/xml-data/corpfiling/AttachLive/corp_action_2026.xml"
    assert _normalize_attachment_url(
        "filing_bundle.zip",
        "https://www.bseindia.com",
    ) == "https://www.bseindia.com/xml-data/corpfiling/AttachLive/filing_bundle.zip"
    assert _normalize_attachment_url("-", "https://www.nseindia.com") == ""


def test_attachment_candidates_prefer_structured_nse_urls():
    row = {
        "xbrl": "/corporate/acme_2026.xbrl",
        "csvName": "acme_2026.csv",
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/acme_2026.pdf",
    }

    candidates = _attachment_candidates_for_record(
        "NSE",
        row,
        base_url="https://www.nseindia.com",
        fallback_url=row["attchmntFile"],
    )

    assert candidates[0].endswith(".xbrl")
    assert candidates[1].endswith(".csv")
    assert candidates[-1].endswith(".pdf")


def test_attachment_candidate_extraction_falls_back_from_structured_to_pdf(monkeypatch):
    calls: list[str] = []

    def fake_extract(url: str, timeout_s: float = 0.0):
        calls.append(url)
        if url.endswith(".xbrl"):
            return {
                "attachment_text": "",
                "attachment_text_length": 0,
                "attachment_extraction_status": "failed",
                "attachment_extraction_error": "404",
            }
        return {
            "attachment_text": "pdf text",
            "attachment_text_length": 8,
            "attachment_extraction_status": "ok",
            "attachment_extraction_error": None,
        }

    monkeypatch.setattr(
        "finagent.ikg.scrapers.sebi_corporate_filings.extract_attachment_content",
        fake_extract,
    )

    result = _extract_with_fallback_candidates(
        ["https://example.com/acme.xbrl", "https://example.com/acme.pdf"]
    )

    assert calls == ["https://example.com/acme.xbrl", "https://example.com/acme.pdf"]
    assert result["attachment_extraction_status"] == "ok"
    assert result["resolved_attachment_url"].endswith(".pdf")


def test_hydrated_records_can_normalize_xbrl_and_corporate_actions():
    class CaptureCursor:
        def __init__(self):
            self.sql: list[str] = []

        def execute(self, sql, params=None):
            self.sql.append(" ".join(str(sql).split()))

    xml = """
    <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
                xmlns:ca="http://example.com/corporate-actions">
      <xbrli:context id="I2026">
        <xbrli:entity><xbrli:identifier scheme="isin">INE001A01036</xbrli:identifier></xbrli:entity>
        <xbrli:period><xbrli:instant>2026-01-12</xbrli:instant></xbrli:period>
      </xbrli:context>
      <ca:RecordDate contextRef="I2026">12-Jan-2026</ca:RecordDate>
      <ca:BonusRatio contextRef="I2026">1:1</ca:BonusRatio>
    </xbrli:xbrl>
    """
    record = {
        "category": "corporate_actions",
        "exchange": "BSE",
        "source_uid": "act-1",
        "cin": "L12345MH2000PLC000001",
        "symbol": "ACME",
        "scrip_code": "500001",
        "company_name": "ACME LTD",
        "announced_at": None,
        "title": "Board approves bonus issue in the ratio 1:1 with record date 12-Jan-2026",
        "description": "",
        "attachment_url": "https://www.bseindia.com/xml-data/corpfiling/AttachLive/corp_action_2026.xml",
        "source_url": "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
        "attachment_text": xml,
        "attachment_content_type": "application/xml",
        "raw_json": {},
    }
    cur = CaptureCursor()

    assert _store_xbrl_for_record(cur, record) >= 2
    assert _store_corporate_action_for_record(cur, record) == 1
    joined_sql = "\n".join(cur.sql)
    assert "insert into xbrl_filings_raw" in joined_sql
    assert "insert into corporate_event_xbrl" in joined_sql
    assert "insert into corporate_actions_raw" in joined_sql


def test_xbrl_normalization_recovers_structured_candidate_from_raw_json(monkeypatch):
    class CaptureCursor:
        def __init__(self):
            self.sql: list[str] = []

        def execute(self, sql, params=None):
            self.sql.append(" ".join(str(sql).split()))

    xml = """
    <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
                xmlns:ca="http://example.com/corporate-actions">
      <xbrli:context id="I2026">
        <xbrli:entity><xbrli:identifier scheme="isin">INE001A01036</xbrli:identifier></xbrli:entity>
        <xbrli:period><xbrli:instant>2026-01-12</xbrli:instant></xbrli:period>
      </xbrli:context>
      <ca:RecordDate contextRef="I2026">12-Jan-2026</ca:RecordDate>
      <ca:BonusRatio contextRef="I2026">1:1</ca:BonusRatio>
    </xbrli:xbrl>
    """
    calls: list[str] = []

    def fake_extract(url: str, timeout_s: float = 0.0):
        calls.append(url)
        if url.endswith(".xml"):
            return {
                "attachment_text": xml,
                "attachment_text_length": len(xml),
                "attachment_sha256": "abc",
                "attachment_content_type": "application/xml",
                "attachment_extracted_model": "fake",
                "attachment_parser": "fake",
                "attachment_document_type": "xml",
                "attachment_tables": [],
                "attachment_structured_facts": None,
                "attachment_text_sufficient": True,
                "attachment_sufficiency_reason": "ok",
                "attachment_page_count": 0,
                "attachment_extraction_status": "ok",
                "attachment_extraction_error": None,
                "resolved_attachment_url": url,
            }
        return {
            "attachment_text": "pdf text",
            "attachment_text_length": 8,
            "attachment_extraction_status": "ok",
            "attachment_extraction_error": None,
            "resolved_attachment_url": url,
        }

    monkeypatch.setattr(
        "finagent.ikg.scrapers.sebi_corporate_filings.extract_attachment_content",
        fake_extract,
    )

    record = {
        "category": "corporate_actions",
        "exchange": "BSE",
        "source_uid": "act-1",
        "cin": "L12345MH2000PLC000001",
        "symbol": "ACME",
        "scrip_code": "500001",
        "company_name": "ACME LTD",
        "announced_at": None,
        "title": "Board approves bonus issue in the ratio 1:1 with record date 12-Jan-2026",
        "description": "",
        "attachment_url": "https://www.bseindia.com/corporates/ann.html",
        "source_url": "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
        "attachment_text": "",
        "attachment_content_type": None,
        "raw_json": {"ATTACHMENTNAME": "corp_action_2026.xml"},
    }
    cur = CaptureCursor()

    assert _store_xbrl_for_record(cur, record) >= 2
    assert any(url.endswith(".xml") for url in calls)
    joined_sql = "\n".join(cur.sql)
    assert "insert into xbrl_filings_raw" in joined_sql
    assert "insert into corporate_event_xbrl" in joined_sql


def test_auditor_name_extractor_finds_statutory_auditor():
    auditors = extract_auditor_names_from_text(
        "The statutory auditors of the company are M/s BSR & Co. LLP, Chartered Accountants."
    )
    names = [row["auditor_name"] for row in auditors]
    assert any("BSR" in name for name in names)


def test_generic_xbrl_parser_preserves_context_and_financial_summary():
    xml = """
    <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
                xmlns:in-gaap="http://www.mca.gov.in/xbrl/taxonomy">
      <xbrli:context id="D2026">
        <xbrli:entity><xbrli:identifier scheme="isin">INE001A01036</xbrli:identifier></xbrli:entity>
        <xbrli:period>
          <xbrli:startDate>2025-04-01</xbrli:startDate>
          <xbrli:endDate>2026-03-31</xbrli:endDate>
        </xbrli:period>
      </xbrli:context>
      <xbrli:unit id="INR"><xbrli:measure>iso4217:INR</xbrli:measure></xbrli:unit>
      <in-gaap:RevenueFromOperations contextRef="D2026" unitRef="INR" decimals="-6">123456</in-gaap:RevenueFromOperations>
      <in-gaap:ProfitBeforeTax contextRef="D2026" unitRef="INR" decimals="-6">12000</in-gaap:ProfitBeforeTax>
      <in-gaap:BasicEarningsLossPerShare contextRef="D2026" unitRef="INR">14.25</in-gaap:BasicEarningsLossPerShare>
    </xbrli:xbrl>
    """

    parsed = parse_xbrl_facts(xml)
    summary = summarize_xbrl_facts("financial_results", parsed["facts"])

    assert is_probable_xbrl(xml, url="result.xml")
    assert parsed["success"] is True
    assert len(parsed["facts"]) == 3
    assert parsed["facts"][0]["period_start"] == "2025-04-01"
    assert parsed["facts"][0]["period_end"] == "2026-03-31"
    assert summary["revenue_from_operations"] == 123456
    assert summary["profit_before_tax"] == 12000
    assert summary["eps_basic"] == 14.25


def test_annual_report_json_parser_extracts_pdf_links():
    reports = _parse_bse_annual_report_json(
        {"Table": [{"PDFURL": "/bseplus/AnnualReport/500001/5000010326.pdf", "Year": "2026"}]},
        scrip_code="500001",
        source_url="https://api.bseindia.com/BseIndiaAPI/api/AnnualReport/w?scripcode=500001",
    )

    assert len(reports) == 1
    assert reports[0]["year"] == "2026"
    assert reports[0]["pdf_url"].startswith("https://www.bseindia.com/")


def test_mca_export_form_parser_and_payload():
    html = """
    <form id="exportForm" method="POST" action="cdm/export_company_master_details.php">
      <input type="hidden" name="csrf_token" id="csrf_token" value="abc123token">
    </form>
    """

    token, action = extract_mca_export_form(html)
    payload = build_mca_export_payload(token, captcha_value="ZXCV12")

    assert token == "abc123token"
    assert action.endswith("/cdm/export_company_master_details.php")
    assert payload["csrf_token"] == "abc123token"
    assert payload["companystate[]"] == "all"
    assert payload["companyindustrialclassification[]"] == "all"
    assert payload["captcha_input"] == "ZXCV12"
    assert payload["captcha_hidden"] == "ZXCV12"


def test_nse_company_name_normalizer_matches_mca_limited_suffixes():
    assert _normalize_company_name_for_match("ABB India Ltd.") == _normalize_company_name_for_match("ABB INDIA LIMITED")
    assert _normalize_company_name_for_match("Aarti Industries Ltd.") == _normalize_company_name_for_match("AARTI INDUSTRIES LIMITED")


def test_annual_report_url_sanitizer_removes_escaped_backslashes():
    url = sanitize_annual_report_pdf_url(
        r"/xml-data/corpfiling/AttachHis/\b55b5dfc-a3bf-4f24-9d7f-ca09774a1dd9.pdf",
        "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode=500325",
    )
    assert url.startswith("https://www.bseindia.com/xml-data/corpfiling/AttachHis/")
    assert "\\" not in url


def test_annual_report_announcement_helpers_identify_regulation_34_pdf():
    assert _is_annual_report_announcement(
        "Annual Report for FY 2024-25",
        "Submitted under Regulation 34 of SEBI LODR",
    )
    url = _normalize_bse_attachment_url("abc123.pdf")
    assert url == "https://www.bseindia.com/xml-data/corpfiling/AttachLive/abc123.pdf"


def test_bse_eod_filename_picker_prefers_csv_or_zip_rows():
    payload = {
        "dsedcudiff": [
            {"filename": "BhavCopy_BSE_CM_0_0_0_20260603_F_0000.CSV", "Filetype": "EQ"},
        ],
        "dsBhav": [
            {"filename": "EQ030626_CSV.ZIP"},
        ],
    }
    assert pick_bse_eod_filename(payload) == "BhavCopy_BSE_CM_0_0_0_20260603_F_0000.CSV"


def test_concall_filter_accepts_analyst_meet_transcript_pdf():
    row = {
        "desc": "Analysts/Institutional Investor Meet/Con. Call Updates",
        "attchmntText": (
            "Transcript of the discussion on the audited financial results "
            "at the analyst meet held on April 24, 2026."
        ),
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/sample_transcript.pdf",
    }
    assert _is_transcript_announcement(row)


def test_governance_filter_accepts_integrated_governance_pdf():
    row = {
        "desc": "Integrated Filing- Governance",
        "attchmntText": "Corporate Governance Report under Regulation 27 for quarter ended March 31, 2026",
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/ACME2026_governance.pdf",
    }

    assert _is_governance_announcement(row)


def test_governance_director_parser_extracts_din_rows():
    text = """
    I. Composition of Board of Directors
    Name of Director DIN Category Date of Appointment Date of Cessation
    Anita Rao 01234567 Chairperson Non-Executive Independent Director 01-04-2021 -
    Bharat Kumar 07654321 Managing Director Executive Director 15/07/2020 -
    """

    directors = parse_governance_directors_from_text(
        text,
        cin="L12345MH2000PLC000001",
        nse_symbol="ACME",
        source_url="https://nsearchives.nseindia.com/corporate/acme_governance.pdf",
        quarter="Q4-FY2026",
    )

    assert {row["din"] for row in directors} == {"01234567", "07654321"}
    assert directors[0]["cin"] == "L12345MH2000PLC000001"
    assert directors[0]["source"] == "exchange_corporate_governance"
    assert directors[0]["quarter"] == "Q4-FY2026"


def test_governance_payload_parser_extracts_nse_board_composition():
    payload = {
        "cobod": [
            {
                "recId": "105075",
                "data": {
                    "CompositionBOD": [
                        {
                            "din": "07362344",
                            "directorName": "Sanjeev Sharma",
                            "category": "Executive Director-MD",
                            "dateOfAppointment": "01-JAN-2022",
                            "dateOfCessation": "-",
                            "status": "Active",
                            "membershipinCommofCompany": "Stakeholders Relationship Committee",
                        }
                    ]
                },
            }
        ]
    }

    directors = parse_governance_directors_from_payload(
        payload,
        cin="L32202KA1949PLC032923",
        nse_symbol="ABB",
        source_url="https://www.nseindia.com/api/corporate-governance?recId=105075",
        quarter="Q3-FY2025",
    )

    assert len(directors) == 1
    assert directors[0]["din"] == "07362344"
    assert directors[0]["name"] == "Sanjeev Sharma"
    assert directors[0]["designation"] == "Executive Director-MD"
    assert directors[0]["appointment_date"] == "2022-01-01"


def test_sebi_records_window_parser_extracts_range():
    window = _parse_records_window("Displaying 26 to 50 of 138 records")
    assert window == (26, 50, 138)


def test_mca_filtered_director_parser_maps_session_payload():
    payload = [
        {
            "DIN": "01234567",
            "firstName": "ALPHA",
            "lastName": "DIRECTOR",
            "MCAUserRole": [
                {
                    "cin": "L12345MH2000PLC000001",
                    "designation": "Director",
                    "appointmentDate": "12/04/2021",
                    "cessationDate": "",
                    "signatoryAssociationStatus": "Active",
                }
            ],
        }
    ]

    rows = parse_mca_filtered_directors(payload, "L12345MH2000PLC000001")
    assert len(rows) == 1
    assert rows[0]["din"] == "01234567"
    assert rows[0]["name"] == "ALPHA DIRECTOR"
    assert rows[0]["designation"] == "Director"
    assert rows[0]["appointment_date"] == "2021-04-12"


def test_sebi_category_fetch_works_inside_running_event_loop(monkeypatch):
    class _Resp:
        status_code = 200
        text = """
        <html><body>
          <a href="/sebiweb/home/HomeAction.do?doListing=yes&sid=2&smid=6">
            Adjudication Orders
          </a>
        </body></html>
        """

    async def _fake_async_fetch_categories(client, timeout_s):
        return _Resp()

    monkeypatch.setattr(sebi_enforcement, "_async_fetch_categories", _fake_async_fetch_categories)

    import asyncio

    async def _run():
        categories = sebi_enforcement.fetch_sebi_order_categories()
        assert categories["adjudication"].startswith("https://www.sebi.gov.in/")

    asyncio.run(_run())


def test_cross_validate_financials_includes_statement_payloads():
    yf_data = {
        "info": {"pe_ratio": 20.0},
        "financials_json": '{"Revenue":{"2025":1000}}',
        "balance_sheet_json": '{"Assets":{"2025":2500}}',
        "cashflow_json": '{"OperatingCashFlow":{"2025":400}}',
    }
    screener_data = {"key_ratios": {"pe_ratio": 22.0}}

    validated = cross_validate_financials(yf_data, screener_data, "ACME")

    assert validated["income_statement_json"]["Revenue"]["2025"] == 1000
    assert validated["balance_sheet_json"]["Assets"]["2025"] == 2500
    assert validated["cashflow_json"]["OperatingCashFlow"]["2025"] == 400
    assert "pe_ratio" in validated["validated_metrics"]


def test_annual_report_selector_expands_table_continuations():
    previews = [
        PagePreview(1, "Cover and awards"),
        PagePreview(2, "Corporate Governance Board of Directors Audit Committee"),
        PagePreview(3, "Related Party Transactions Particulars Amount Rs. crore 2025 2024 Total 100 80"),
        PagePreview(4, "Related party transactions continued Particulars Amount Rs. crore 2025 2024 Total 120 90"),
        PagePreview(5, "Proxy form attendance slip e-voting instructions"),
    ]

    selection = select_useful_annual_report_pages(previews, min_score=3, context_pages=0)

    assert selection.page_ranges == "2-4"
    assert 4 in selection.pages
    assert pages_to_ranges([1, 2, 3, 5, 7, 8]) == "1-3,5,7-8"


def test_document_sections_keep_whole_selected_page_ranges_with_tables():
    selection = select_useful_annual_report_pages(
        [
            PagePreview(1, "Corporate Governance Board of Directors"),
            PagePreview(2, "Particulars Amount Rs. crore 2025 2024 Total 100 90"),
        ],
        min_score=3,
        context_pages=1,
    )
    table = SimpleNamespace(
        page_number=2,
        page_numbers=[2],
        markdown="| Particulars | 2025 |\n| --- | --- |\n| Total | 100 |",
    )
    pages = [
        SimpleNamespace(page_number=1, text="Corporate Governance Board of Directors"),
        SimpleNamespace(page_number=2, text="Particulars Amount Rs. crore 2025 2024 Total 100 90"),
    ]

    sections = build_document_sections_from_extraction(
        document_uid="annual:abc",
        document_type="annual_report",
        source_url="https://example.com/report.pdf",
        selection=selection,
        extracted_pages=pages,
        tables=table and [table],
        company_cin="L12345",
        company_symbol="ACME",
        company_scrip_code="500001",
        company_name="Acme Industries Limited",
    )

    assert len(sections) == 1
    assert sections[0]["page_start"] == 1
    assert sections[0]["page_end"] == 2
    assert "Corporate Governance" in sections[0]["text"]
    assert "| Particulars |" in sections[0]["tables_markdown"]
    assert sections[0]["metadata"]["cin"] == "L12345"
    assert sections[0]["metadata"]["company_cin"] == "L12345"
    assert sections[0]["metadata"]["nse_symbol"] == "ACME"
    assert sections[0]["metadata"]["bse_scrip_code"] == "500001"
    assert sections[0]["metadata"]["company_identifier"] == "L12345"


def test_extracted_table_markdown_handles_none_cells():
    table = ExtractedTable(
        page_number=1,
        rows=[["Metric", None], ["Revenue", 123], [None, "456"]],
        header_row=["Metric", None],
    )

    markdown = table.markdown

    assert "| Metric |  |" in markdown
    assert "| Revenue | 123 |" in markdown
    assert "|  | 456 |" in markdown


def test_ikg_client_supports_current_and_legacy_director_edges():
    async def _run():
        backend = InMemoryGraphBackend()
        client = IKGClient(backend=backend)
        await client.upsert_vertex("company:L1", "Company", {"cin": "L1"})
        await client.upsert_vertex("person:1", "Person", {"din": "1"})
        await client.upsert_vertex("person:2", "Person", {"din": "2"})
        await client.upsert_edge("person:1", "company:L1", "DIRECTOR_OF", {"designation": "CEO"})
        await client.upsert_edge("person:2", "company:L1", "SERVES_AS_DIRECTOR", {"designation": "Director"})

        history = await client.get_director_history("L1")
        assert {edge["from"] for edge in history} == {"person:1", "person:2"}

    import asyncio

    asyncio.run(_run())


def test_azure_search_reports_missing_config(monkeypatch):
    monkeypatch.delenv("AZURE_SEARCH_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_SEARCH_KEY", raising=False)
    monkeypatch.delenv("AZURE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_AI_SEARCH_KEY", raising=False)

    from finagent.graphrag.azure_search import check_azure_search

    status = check_azure_search()

    assert status["configured"] is False
    assert status["ok"] is False


def test_celery_app_registers_ikg_tasks():
    import pytest

    from finagent.ikg.pipeline.celery_app import celery_app

    if celery_app is None:
        pytest.skip("Celery is optional in this test environment")
    task_names = set(celery_app.tasks.keys())
    assert "finagent.ikg.bse_shp" in task_names
    assert "finagent.ikg.corporate_filings" in task_names
    assert "finagent.ikg.director_kmp" in task_names
    assert "finagent.ikg.build_graph" in task_names
    assert "finagent.ikg.mca_directors" not in task_names


def test_mca_director_refresh_is_disabled():
    from finagent.ikg.pipeline.orchestrator import run_mca_director_refresh

    result = run_mca_director_refresh(max_companies=1)
    assert result.success is True
    assert result.records_stored == 0
    assert result.metadata.get("deprecated") is True


def test_director_kmp_parser_extracts_din_rows():
    text = """
    Corporate Governance Report
    DIN: 01234567 Mr. Sanjeev Sharma Independent Director
    DIN: 07654321 Ms. Anjali Rao Whole-time Director
    """
    rows = parse_director_kmp_from_text(
        text,
        cin="L12345MH2000PLC000001",
        source="NSE_corporate_governance",
        source_url="https://example.com/governance.pdf",
    )
    dins = {row["din"] for row in rows}
    assert "01234567" in dins
    assert "07654321" in dins


def test_director_kmp_parser_generates_alt_ids_without_din():
    text = """
    Board of Directors and Key Managerial Personnel
    Mr. Rajesh Kumar - Chief Financial Officer
    Ms. Priya Menon - Company Secretary
    """
    rows = parse_director_kmp_from_text(
        text,
        cin="L12345MH2000PLC000001",
        source="annual_report_board_section",
        source_url="https://example.com/annual.pdf",
        quarter="2025-26",
    )
    assert len(rows) >= 2
    assert all(str(row["din"]).startswith("ALT") for row in rows)

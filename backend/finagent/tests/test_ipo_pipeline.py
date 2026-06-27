from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

from finagent.ingestion.financial_table_extractor import extract_restated_financials
from finagent.ingestion.drhp_parser import (
    extract_business_overview_paragraphs,
    extract_kpi_rows,
    extract_kpis,
    extract_management,
    extract_sections,
)
from finagent.ipo.service import IpoService
from finagent.tools.data.ipo_enricher import enrich_filing
from finagent.tools.data.ipo_fetcher import _records_from_nse_offer_api_rows, _records_from_nse_offer_rss


class FakeIpoStore:
    def __init__(self, rows: list[dict[str, Any]]):
        self.rows = [dict(row) for row in rows]

    async def list_filings(self, limit: int = 200, status: str | None = None) -> list[dict[str, Any]]:
        rows = self.rows[:limit]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return [dict(row) for row in rows]

    async def upsert_filing(self, row: dict[str, Any]) -> None:
        slug = row.get("slug")
        for idx, existing in enumerate(self.rows):
            if existing.get("slug") == slug:
                self.rows[idx] = dict(row)
                return
        self.rows.append(dict(row))

    async def get_filing(self, slug: str) -> dict[str, Any] | None:
        for row in self.rows:
            if row.get("slug") == slug:
                return dict(row)
        return None

    async def get_analysis(self, slug: str) -> dict[str, Any] | None:
        return None

    async def get_scores(self, slug: str) -> dict[str, Any]:
        return {}


def test_enrich_filing_marks_live_only_inside_subscription_window() -> None:
    today = date.today()

    live = enrich_filing(
        {
            "company_name": "Current Live Limited",
            "doc_type": "rhp",
            "status": "live",
            "subscription_open": (today - timedelta(days=1)).isoformat(),
            "subscription_close": (today + timedelta(days=1)).isoformat(),
        }
    )
    assert live["status"] == "live"

    closed = enrich_filing(
        {
            "company_name": "Closed Issue Limited",
            "doc_type": "rhp",
            "status": "live",
            "subscription_open": (today - timedelta(days=5)).isoformat(),
            "subscription_close": (today - timedelta(days=1)).isoformat(),
        }
    )
    assert closed["status"] == "closed"

    rhp_without_exchange_dates = enrich_filing(
        {
            "company_name": "RHP Without Exchange Dates Limited",
            "doc_type": "rhp",
            "status": "live",
        }
    )
    assert rhp_without_exchange_dates["status"] == "upcoming"


def test_dashboard_live_bucket_requires_official_current_exchange_slug() -> None:
    today = date.today()
    rows = [
        {
            "slug": "current-live",
            "company_name": "Current Live Limited",
            "doc_type": "rhp",
            "status": "live",
            "source": "nse_api",
            "source_url": "https://www.nseindia.com/api/ipo-current-issue",
            "subscription_open": (today - timedelta(days=1)).isoformat(),
            "subscription_close": (today + timedelta(days=1)).isoformat(),
            "price_band_low": 100,
            "price_band_high": 110,
            "issue_size_cr": 50.0,
        },
        {
            "slug": "missing-metrics",
            "company_name": "Missing Metrics Limited",
            "doc_type": "rhp",
            "status": "live",
            "source": "nse_api",
            "source_url": "https://www.nseindia.com/api/ipo-current-issue",
            "subscription_open": (today - timedelta(days=1)).isoformat(),
            "subscription_close": (today + timedelta(days=1)).isoformat(),
        },
        {
            "slug": "postponed-issue",
            "company_name": "Postponed Issue Limited - Issue postponed",
            "doc_type": "rhp",
            "status": "live",
            "source": "nse_api",
            "source_url": "https://www.nseindia.com/api/ipo-current-issue",
            "subscription_open": (today - timedelta(days=1)).isoformat(),
            "subscription_close": (today + timedelta(days=1)).isoformat(),
            "price_band_low": 100,
            "price_band_high": 110,
            "issue_size_cr": 50.0,
        },
        {
            "slug": "stale-live",
            "company_name": "Stale Live Limited",
            "doc_type": "rhp",
            "status": "live",
            "subscription_open": (today - timedelta(days=7)).isoformat(),
            "subscription_close": (today - timedelta(days=1)).isoformat(),
        },
        {
            "slug": "future-ipo",
            "company_name": "Future IPO Limited",
            "doc_type": "rhp",
            "status": "upcoming",
            "subscription_open": (today + timedelta(days=2)).isoformat(),
            "subscription_close": (today + timedelta(days=5)).isoformat(),
        },
    ]
    service = IpoService(store=FakeIpoStore(rows))
    service._start_exchange_refresh_background = lambda: None  # type: ignore[method-assign]

    dashboard = asyncio.run(service.pipeline_dashboard())
    live_slugs = [card["slug"] for card in dashboard["buckets"]["live"]]
    all_slugs = {card["slug"] for cards in dashboard["buckets"].values() for card in cards}

    assert live_slugs == ["current-live"]
    assert "future-ipo" in {card["slug"] for card in dashboard["buckets"]["upcoming"]}
    assert "stale-live" not in all_slugs
    assert "missing-metrics" not in all_slugs
    assert "postponed-issue" not in all_slugs


def test_section_detection_prefers_actual_risk_heading_over_intro_reference() -> None:
    markdown = "\n".join(
        [
            '"Risk Factors - Significant differences exist between Ind AS and other accounting principles."',
            "This sentence is a cross-reference, not the beginning of the risk chapter.",
            "SECTION I - GENERAL",
            "General company details.",
            "SECTION II - RISK FACTORS",
            "1. Our business depends on a limited number of suppliers and any disruption may affect operations.",
            "2. We may face working capital pressure if receivables increase.",
            "SECTION III - INTRODUCTION",
            "Objects of the issue are discussed later.",
        ]
    )

    parsed = extract_sections(markdown)

    assert parsed.sections["risk_factors"].text.startswith("SECTION II - RISK FACTORS")
    assert "Our business depends" in parsed.sections["risk_factors"].text


def test_kpi_extraction_prefers_table_rows_and_ignores_crore_alias_noise() -> None:
    section = """
    The issue size is Rs 9.0 crore and face value is Rs 10 per share.
    | Particulars | FY 2025 | FY 2026 |
    | --- | ---: | ---: |
    | EBITDA Margin | 12.05% | 17.37% |
    | PAT Margin | 6.32% | 9.80% |
    | Debt / Equity | 0.57 | 0.18 |
    | ROE | 22.80% | 37.26% |
    | ROCE | 23.85% | 46.90% |
    """

    kpis = extract_kpis(section)
    rows = extract_kpi_rows(section)

    assert kpis["ebitda_margin_pct"] == 17.37
    assert kpis["pat_margin_pct"] == 9.80
    assert kpis["roe_pct"] == 37.26
    assert kpis["roce_pct"] == 46.90
    assert kpis["debt_equity_ratio"] == 0.18
    assert next(row for row in rows if row["label"] == "Debt / Equity")["trend"] == "improving"



def test_official_document_resolver_reuses_related_sebi_filing() -> None:
    rows = [
        {
            "slug": "turtlemint-fintech",
            "company_name": "Turtlemint Fintech",
            "doc_type": "rhp",
            "status": "upcoming",
        },
        {
            "slug": "turtlemint-fintech-solutions",
            "company_name": "TURTLEMINT FINTECH SOLUTIONS LIMITED",
            "doc_type": "prospectus",
            "filing_date": "2026-06-24",
            "pdf_url": "https://www.sebi.gov.in/sebi_data/attachdocs/jun-2026/example.pdf",
            "source": "sebi",
        },
    ]
    service = IpoService(store=FakeIpoStore(rows))
    service._select_best_cached_pdf = lambda *_args, **_kwargs: None  # isolate from developer machine cache

    async def run() -> dict[str, Any]:
        filing = await service.store.get_filing("turtlemint-fintech")
        updated, path = await service._ensure_official_document(filing, allow_network=False)
        assert path is None
        return updated

    updated = asyncio.run(run())

    assert updated["pdf_url"].startswith("https://www.sebi.gov.in/")
    assert updated["doc_type"] == "prospectus"
    assert updated["prospectus_filing_date"] == "2026-06-24"




def test_nse_offer_api_extracts_sme_rhp_zip_document() -> None:
    rows = [
        {
            "company": "Sri Priyanka Geo Commex Limited",
            "rhp": "Red Herring Prospectus",
            "rhpDate": "18-Jun-2026",
            "rhpAttach": "https://nsearchives.nseindia.com/emerge/corporates/content/SriPriyankaGeoCommexLimited_RHP.zip",
            "drhp": "Draft Prospectus/Draft Red Herring Prospectus",
            "drhpDate": "14-Aug-2025",
            "drhpAttach": "https://nsearchives.nseindia.com/emerge/corporates/content/AD_IPO_6098_06012026185806.zip",
            "pan_no": "AABCS0583L",
        }
    ]

    records = _records_from_nse_offer_api_rows(rows, index="sme")

    assert [record.doc_type for record in records] == ["rhp", "drhp"]
    assert records[0].slug == "sri-priyanka-geo-commex"
    assert records[0].pdf_url.endswith("/SriPriyankaGeoCommexLimited_RHP.zip")
    assert records[0].exchange == "NSE SME"

def test_nse_offer_rss_extracts_zip_rhp_document() -> None:
    xml = """<?xml version="1.0"?><rss><channel><item>
    <title>Sri Priyanka Geo Commex Limited</title>
    <link>https://nsearchives.nseindia.com/corporate/SriPriyankaGeoCommexLimited_RHP.zip</link>
    <description>Sri Priyanka Geo Commex Limited has filled RHP for its IPO</description>
    <pubDate>18-Jun-2026</pubDate>
    </item></channel></rss>"""

    records = _records_from_nse_offer_rss(xml)

    assert len(records) == 1
    assert records[0].slug == "sri-priyanka-geo-commex"
    assert records[0].doc_type == "rhp"
    assert records[0].pdf_url.endswith("_RHP.zip")
    assert records[0].source == "nse_offer_documents"


def test_management_numbered_director_blocks_are_extracted() -> None:
    section = """
    OUR MANAGEMENT

    (1)
    Dhirendra Nalin Mahyavanshi*
    Designation: Chairperson and Managing Director and
    Chief Executive Officer
    Address: Mumbai, Maharashtra, India
    Date of birth: December 1, 1978
    DIN: 06652017

    (2)
    Anand Rohidas Prabhudesai*
    Designation: Executive Director and Chief Operating
    Officer
    Address: Mumbai, Maharashtra, India
    DIN: 07106615
    """

    management = extract_management(section, section)

    assert [person["name"] for person in management[:2]] == [
        "Dhirendra Nalin Mahyavanshi",
        "Anand Rohidas Prabhudesai",
    ]
    assert "Managing Director" in management[0]["designation"]


def test_kpi_paragraph_fallback_does_not_promote_face_value_numbers() -> None:
    section = """
    The Offer Price is 5 times the face value of the Equity Shares.
    The face value is Rs 4 per Equity Share. Net asset value and EPS are discussed elsewhere.
    """

    assert extract_kpis(section) == {}

def test_business_overview_extractor_skips_offer_document_boilerplate() -> None:
    section = """
    OUR BUSINESS

    We have included various operational and financial performance indicators in this Red Herring Prospectus,
    some of which may not be derived from our Restated Consolidated Financial Information. Investors are
    accordingly cautioned while comparing such indicators with other companies.

    Further, names of certain customers and suppliers have not been included in this Red Herring Prospectus
    either because relevant consents for disclosure of their names were not available.

    Unless the context otherwise requires, references to our Company refer to Example Technologies Limited.

    We are amongst the few IT solutions companies who have delivered first-of-its-kind projects for government
    as well as private-sector customers. We specialise in providing GovTech solutions and digital transformation
    services across mining, agriculture, education, healthcare and tourism.

    These solutions are aimed at streamlining operations, improving data-driven decision-making, and facilitating
    citizen-centric services for government organisations and corporate clients.
    """

    paragraphs = extract_business_overview_paragraphs(section, limit=2)

    assert paragraphs[0].startswith("We are amongst the few IT solutions companies")
    assert "operational and financial performance indicators" not in " ".join(paragraphs)
    assert len(paragraphs) == 2


def test_lifecycle_keeps_future_listing_pending_for_live_ipo() -> None:
    today = date.today()
    service = IpoService(store=FakeIpoStore([]))

    lifecycle = service._build_lifecycle(
        {
            "slug": "current-live",
            "company_name": "Current Live Limited",
            "doc_type": "rhp",
            "status": "live",
            "filing_date": (today - timedelta(days=10)).isoformat(),
            "subscription_open": (today - timedelta(days=1)).isoformat(),
            "subscription_close": (today + timedelta(days=1)).isoformat(),
            "listing_date": (today + timedelta(days=5)).isoformat(),
        }
    )

    stages = {stage["key"]: stage for stage in lifecycle["stages"]}

    assert stages["rhp"]["state"] == "current"
    assert stages["listed"]["state"] == "pending"
    assert stages["listed"]["countdown"]["days"] == 5

def test_financial_extractor_parses_multirow_kpi_table_and_scales_lakhs() -> None:
    table = """
    |  | Unit of measurement | As on the |  |  |  |
    | --- | --- | --- | --- | --- | --- |
    |  |  | Nine months |  |  |  |
    |  |  |  | Financial year | Financial year | Financial year |
    | KPI |  | period ended |  |  |  |
    |  |  |  | ended March | ended March | ended March |
    |  |  | December 31, |  |  |  |
    |  |  |  | 31, 2025 | 31, 2024 | 31, 2023 |
    |  |  | 2025 |  |  |  |
    | Revenue from operations(1) | Rs. lakhs | 16,552.36 | 19,924.42 | 19,671.05 | 16,043.87 |
    | Total Income(2) | Rs. lakhs | 16,704.99 | 20,062.73 | 19,865.05 | 16,150.49 |
    | EBITDA(3) | Rs. lakhs | 3,006.66 | 2,927.00 | 2,370.94 | 2,787.23 |
    | EBITDA Margin(4) | % | 18.16% | 14.69% | 12.05% | 17.37% |
    | PAT(5) | Rs. lakhs | 1,470.14 | 1,408.65 | 1,254.93 | 1,582.40 |
    | PAT Margin(6) | % | 8.80% | 7.02% | 6.32% | 9.80% |
    | Total Debt to Equity(8) | Times | 0.86 | 0.46 | 0.57 | 0.18 |
    """

    financials = extract_restated_financials(table, table)

    assert financials["years"] == ["FY2023", "FY2024", "FY2025", "9M FY26"]
    assert financials["metrics"]["revenue"] == [160.4387, 196.7105, 199.2442, 165.5236]
    assert financials["metrics"]["ebitda"] == [27.8723, 23.7094, 29.27, 30.0666]
    assert financials["metrics"]["pat"] == [15.824, 12.5493, 14.0865, 14.7014]
    assert "total_debt" not in financials["metrics"]
    assert financials["trends"]["revenue_cagr_pct"] == 11.4
    assert "revenue_decline" not in financials["flags"]


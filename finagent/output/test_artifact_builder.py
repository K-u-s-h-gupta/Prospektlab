from types import SimpleNamespace

from finagent.output.artifact_builder import _build_price_chart, _objective_wants_visuals, build_answer_artifact
from finagent.output.contracts import OutputMode, ResponseDepth
from finagent.output.intent_classifier import classify_output_mode
from finagent.state.checkpoint import empty_checkpoint


def test_news_brief_is_text_only_even_when_rich_data_exists():
    assert _objective_wants_visuals("provide me its latest news", OutputMode.NEWS_BRIEF) is False


def test_historical_price_direct_answer_allows_price_chart():
    assert _objective_wants_visuals("historical price of tata motor", OutputMode.DIRECT_ANSWER) is True


def test_price_chart_uses_real_price_series_not_revenue_fallback():
    bundle = SimpleNamespace(
        yahoo=SimpleNamespace(
            series_dates=["2026-05-01", "2026-05-02"],
            series_closes=[100.0, 105.0],
            annual_revenue=[1_000_000.0, 2_000_000.0],
            annual_revenue_dates=["2025", "2026"],
            currency="INR",
            price=105.0,
        )
    )

    chart = _build_price_chart(bundle)
    assert chart is not None
    assert chart.labels == ["2026-05-01", "2026-05-02"]
    assert [point.value for point in chart.series[0].data] == [100.0, 105.0]


def test_visual_sections_include_text_after_artifact_fill():
    bundle = SimpleNamespace(
        yahoo=SimpleNamespace(
            name="TCS",
            ticker="TCS.NS",
            price=100.0,
            market_cap=1_000_000.0,
            currency="INR",
            financial_metrics={"total_revenue": 2_000_000.0, "profit_margins": 0.1},
            series_dates=[],
            series_closes=[],
            annual_revenue=[],
            annual_revenue_dates=[],
        ),
        wikipedia=SimpleNamespace(extract="TCS is an IT services company."),
        sec=None,
        filing=None,
        news=[],
    )

    artifact = build_answer_artifact(
        target="TCS",
        objective="Analyze TCS financial performance",
        mode=OutputMode.COMPANY_SNAPSHOT,
        depth=ResponseDepth.STANDARD,
        bundle=bundle,
        docs=[],
        checkpoint=empty_checkpoint(),
        entity=SimpleNamespace(canonical_name="TCS", country_code="IN"),
        specialist_findings=[],
    )

    text_sections = [s for s in artifact.visual_sections if s.section_type == "text_block"]
    assert text_sections
    assert any(s.title == "Company Overview" for s in text_sections)


def test_ownership_query_classifies_as_direct_answer():
    mode = classify_output_mode(
        query="Explain promoter holding and pledged shares in 360 ONE WAM",
        target="360ONE",
        entity=SimpleNamespace(canonical_name="360 ONE WAM LIMITED", country_code="IN"),
        depth=ResponseDepth.STANDARD,
    )
    assert mode == OutputMode.DIRECT_ANSWER


def test_direct_answer_uses_ikg_ownership_when_enrichment_is_missing():
    ikg_bundle = SimpleNamespace(
        entity={"name": "360 ONE WAM LIMITED", "cin": "L74140MH2008PLC177884"},
        as_of_date="2026-06-05",
        warnings=["Financial coverage is incomplete; rely on enrichment/web corroboration."],
        trusted_facts=lambda limit=3: [],
        ownership={
            "pledge_summary": {
                "as_of_date": "2026-06-05",
                "total_promoter_holding_pct": 6.23,
                "total_pledge_pct": 5.58,
                "pledge_flag": "LOW",
                "pledged_promoters": [
                    {
                        "promoter": "Yatin Shah",
                        "holding_pct": 2.39,
                        "pledge_pct_of_holding": 96.91,
                    }
                ],
            }
        },
        governance={"auditors": [], "directors": [], "director_history": []},
    )
    bundle = SimpleNamespace(
        yahoo=None,
        wikipedia=None,
        sec=None,
        filing=None,
        news=[],
        ikg=ikg_bundle,
    )

    artifact = build_answer_artifact(
        target="360ONE",
        objective="Explain promoter holding and pledged shares in 360 ONE WAM",
        mode=OutputMode.DIRECT_ANSWER,
        depth=ResponseDepth.STANDARD,
        bundle=bundle,
        docs=[],
        checkpoint=empty_checkpoint(),
        entity=SimpleNamespace(canonical_name="360 ONE WAM LIMITED", country_code="IN"),
        specialist_findings=[],
    )

    answer = artifact.sections[0].body
    assert "6.23%" in answer
    assert "5.58%" in answer
    assert "Yatin Shah" in answer

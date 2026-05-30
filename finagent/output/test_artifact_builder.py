from types import SimpleNamespace

from finagent.output.artifact_builder import _build_price_chart, _objective_wants_visuals, build_answer_artifact
from finagent.output.contracts import OutputMode, ResponseDepth
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

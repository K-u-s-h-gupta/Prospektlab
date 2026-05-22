from types import SimpleNamespace

from finagent.output.artifact_builder import _build_price_chart, _objective_wants_visuals
from finagent.output.contracts import OutputMode


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

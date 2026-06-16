from __future__ import annotations

from types import SimpleNamespace

from finagent import rich_builder


def test_build_news_mode_with_headlines_returns_rich_response():
    outputs = [
        rich_builder.ToolOutput(
            agent="news_and_research_agent",
            name="get_latest_company_news",
            args={"company": "HDFC Bank"},
            content={
                "headlines": [
                    {
                        "title": "HDFC Bank reports quarterly growth",
                        "url": "https://example.com/news/1",
                        "source": "Example News",
                        "published": "2026-05-17",
                        "snippet": "Quarterly growth remained stable.",
                    }
                ]
            },
        )
    ]

    rich = rich_builder.build("latest news on hdfc bank", outputs, ["news_and_research_agent"], "Latest news below.")
    assert rich is not None
    assert rich.mode == "news"
    assert len(rich.headlines) == 1


def test_build_chat_mode_without_structured_outputs_returns_none():
    rich = rich_builder.build("price of reliance", [], ["market_data_agent"], "Reliance is trading at ...")
    assert rich is None


def test_wants_charts_filtering():
    # Regulatory lookup should not want charts
    assert not rich_builder._wants_charts("what are the latest SEBI LODR Regulation 30 corporate announcements for TCS")
    assert not rich_builder._wants_charts("TCS board meeting notice and filing details")
    
    # Snapshot/History/Growth should want charts
    assert rich_builder._wants_charts("TCS")
    assert rich_builder._wants_charts("historical revenue comparison of TCS vs Infosys")
    assert rich_builder._wants_charts("valuation and revenue growth projections for TCS")
    
    # Regulatory lookup with explicit visual request should want charts
    assert rich_builder._wants_charts("plot a trend chart of promoter pledge SEBI filings for TCS")


def test_native_valuation_does_not_chart_synthetic_terminal_placeholder():
    bundle = SimpleNamespace(
        yahoo=SimpleNamespace(
            name="Test Co",
            ticker="TEST.NS",
            exchange="NSE",
            currency="INR",
            price=100.0,
            market_cap=None,
            change_pct=None,
            fifty_two_week_high=None,
            fifty_two_week_low=None,
            financial_metrics={},
        )
    )
    findings = [
        SimpleNamespace(
            agent="valuation",
            metrics={
                "projected_terminal_revenue": 1_000.0,
                "model_used": "statistical_cagr_2sigma",
            },
        )
    ]

    rich = rich_builder.build_from_native("valuation projection for TEST", bundle, [], findings, "memo text")

    assert rich is not None
    assert all(chart.id != "dcf-projection" for chart in rich.charts)
    assert all(card.value.lower() != "n/a" for card in rich.metric_cards)

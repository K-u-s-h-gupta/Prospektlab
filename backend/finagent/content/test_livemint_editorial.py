"""Tests for LiveMint editorial quality scoring (pure)."""

from __future__ import annotations

from finagent.content.livemint_editorial import (
    PASS_THRESHOLD,
    evaluate_livemint_quality,
    score_data_integration,
    score_headline,
)


def test_headline_sweet_spot_with_number():
    h = score_headline("TCS Q3 net profit jumps 12% to ₹11,400 crore as deal pipeline hits $42 billion")
    assert h["score"] >= 70


def test_headline_generic_seo_penalised():
    h = score_headline("A Comprehensive Guide to Understanding the Indian IT Sector")
    assert h["score"] < 50


def test_headline_too_short_no_number():
    h = score_headline("IT stocks rise")
    assert h["score"] < 40
    assert any("number" in r or "60-100" in r for r in h["reasons"])


def test_data_integration_density():
    rich = {
        "narrative_lede": "Infosys reported revenue of ₹38,800 crore, up 8% YoY, while margins expanded 120 bps to 21%.",
        "market_context": "The Nifty IT index gained 3% as the rupee slipped 1.2% against the dollar to 84.3.",
        "analyst_commentary": "Analysts peg FY26 growth at 9% with EPS of ₹62, implying a 24x forward multiple.",
        "sections": [], "tables": [{}], "metrics": [{}],
    }
    out = score_data_integration(rich)
    assert out["score"] >= 70


def test_data_integration_block_only_penalised():
    poor = {
        "narrative_lede": "The company did well this quarter and investors were pleased with the outcome overall.",
        "market_context": "Markets were broadly positive and sentiment improved across the board for the sector.",
        "analyst_commentary": "Experts believe the future looks bright and growth should continue going forward nicely.",
        "sections": [], "tables": [], "metrics": [],
    }
    out = score_data_integration(poor)
    assert out["score"] < 50


def _good_article():
    return {
        "title": "Reliance Q3 profit rises 9% to ₹18,900 crore on Jio ARPU climb to ₹203",
        "narrative_lede": (
            "Reliance Industries posted a 9% rise in net profit to ₹18,900 crore for the December quarter, "
            "as Jio's average revenue per user climbed to ₹203 and retail revenue crossed ₹83,000 crore, "
            "beating Street estimates of ₹17,500 crore."
        ),
        "market_context": (
            "The result lands as the Nifty 50 trades near 24,800 and energy margins recover, with Singapore "
            "GRMs averaging $8.4 a barrel through the quarter versus $6.1 a year earlier, lifting the refining segment."
        ),
        "analyst_commentary": (
            "Morgan Stanley keeps an overweight rating with a ₹3,100 target, arguing that Jio's tariff hike will add "
            "180 bps to EBITDA margins by FY26, while retail's 18% same-store growth underpins a 22x forward multiple."
        ),
        "sections": [
            {"paragraphs": [
                "Jio added 11 million subscribers in the quarter, taking its base to 482 million, even as competition "
                "from Airtel intensified in the premium tier where 5G adoption reached 38% of post-paid users.",
                "Retail's footprint expanded to 18,900 stores, and the digital commerce mix rose to 27% of sales, a shift "
                "that analysts say lifts blended margins by roughly 90 bps versus a pure offline model."],
             "bullets": []},
            {"paragraphs": [
                "The oil-to-chemicals segment saw EBITDA of ₹14,500 crore, up 4% sequentially, helped by firmer polymer "
                "spreads that widened to $420 a tonne from $360 in the prior quarter as Chinese demand stabilised."],
             "bullets": []},
        ],
        "tables": [{"title": "Segment EBITDA"}],
        "metrics": [{"label": "Net profit", "value": "₹18,900 cr"}],
    }


def test_good_article_passes_gate():
    out = evaluate_livemint_quality(_good_article())
    assert out["passed"] is True
    assert out["score"] >= PASS_THRESHOLD
    assert set(out["dimensions"]) == {"headline_punch", "narrative_flow", "data_integration", "journalistic_cadence"}


def test_rigid_template_article_fails_gate():
    poor = {
        "title": "Understanding the IT Sector: A Comprehensive Overview",
        "narrative_lede": "",
        "market_context": "",
        "analyst_commentary": "",
        "sections": [{"paragraphs": ["The sector is good."], "bullets": ["point one", "point two", "point three"]}],
        "tables": [], "metrics": [],
    }
    out = evaluate_livemint_quality(poor)
    assert out["passed"] is False
    assert len(out["revision_guidance"]) > 0


def test_guidance_is_actionable_tagged():
    out = evaluate_livemint_quality({"title": "x", "sections": []})
    assert all(g.startswith("[") for g in out["revision_guidance"])

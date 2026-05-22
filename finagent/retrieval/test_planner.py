from finagent.geo.entity_resolver import resolve_entity
from finagent.retrieval.planner import build_breadth_queries


def test_smallcap_plan_uses_lodr_statutory_queries():
    entity = resolve_entity("CG Power")
    queries = build_breadth_queries(entity, "latest financials")
    joined = " ".join(queries)
    assert "Regulation 33" in joined
    assert "outcome of board meeting" in joined
    assert "Regulation 31" in joined


def test_news_followup_plan_does_not_expand_to_full_statutory_pack():
    entity = resolve_entity("Adani Power")
    queries = build_breadth_queries(entity, "provide me Adani Power's latest news")
    joined = " ".join(queries)
    assert "latest news" in joined
    assert "Regulation 33" not in joined
    assert "annual report PDF" not in joined
    assert len(queries) <= 4

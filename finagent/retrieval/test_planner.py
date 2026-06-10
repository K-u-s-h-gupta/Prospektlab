from finagent.geo.entity_resolver import resolve_entity
from finagent.geo.query_localizer import localize_search_query
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


def test_instructional_objective_is_normalized_into_company_scoped_query():
    entity = resolve_entity("TCS")
    queries = build_breadth_queries(entity, "Analyze TCS key risks and business quality briefly with evidence.")
    first = queries[0].lower()
    assert first.startswith("tcs ")
    assert "analyze" not in first
    assert "briefly" not in first
    assert "evidence" not in first
    assert "risks" in first
    assert "quality" in first


def test_ownership_objective_gets_shareholding_queries():
    entity = resolve_entity("360ONE")
    queries = build_breadth_queries(entity, "shareholding pattern and promoter pledge of 360ONE")
    joined = " ".join(queries).lower()
    assert "shareholding pattern" in joined
    assert "promoter pledge" in joined
    assert len(queries) <= 4


def test_localizer_does_not_duplicate_india_exchange_terms():
    entity = resolve_entity("TCS")
    localized = localize_search_query("TCS India NSE BSE latest results", entity).lower()
    assert localized.count("india") == 1
    assert localized.count("nse") == 1
    assert localized.count("bse") == 1

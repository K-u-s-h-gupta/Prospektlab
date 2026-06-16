import asyncio

from finagent.geo.entity_resolver import resolve_entity
from finagent.router.intent_router import LLMQueryContextualizer, detect_operational_intent, route_objective


def test_pronoun_news_followup_is_contextualized_without_llm():
    result = asyncio.run(
        LLMQueryContextualizer().contextualize("provide me its latest news", "Adani Power")
    )

    assert result.is_followup is True
    assert "Adani Power" in result.contextualized_query
    assert "latest news" in result.contextualized_query.lower()


def test_named_new_company_is_not_attached_to_previous_target():
    result = asyncio.run(
        LLMQueryContextualizer().contextualize("Tata Motors latest news", "Adani Power")
    )

    assert result.is_followup is False
    assert result.contextualized_query == "Tata Motors latest news"


def test_followup_focus_is_decoupled_from_entity_resolution():
    focus, is_followup = detect_operational_intent("provide me Adani Power's latest news", has_prior_entity=True)

    assert focus == "news"
    assert is_followup is True


def test_portfolio_query_routes_to_portfolio_audit_deep_research():
    entity = resolve_entity("my portfolio risk audit")
    decision = route_objective("run a risk audit on my portfolio concentration", entity)

    assert decision.intent_key == "PORTFOLIO_AUDIT"
    assert decision.deep_research is True
    assert decision.query_complexity == "complex"
    assert {"risk", "governance", "accounting"}.issubset(set(decision.selected_agents))

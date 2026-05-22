import asyncio

from finagent.router.intent_router import LLMQueryContextualizer, detect_operational_intent


def test_pronoun_news_followup_is_contextualized_without_llm():
    contextualized, is_followup = asyncio.run(
        LLMQueryContextualizer().contextualize("provide me its latest news", "Adani Power")
    )

    assert is_followup is True
    assert "Adani Power" in contextualized
    assert "latest news" in contextualized.lower()


def test_named_new_company_is_not_attached_to_previous_target():
    contextualized, is_followup = asyncio.run(
        LLMQueryContextualizer().contextualize("Tata Motors latest news", "Adani Power")
    )

    assert is_followup is False
    assert contextualized == "Tata Motors latest news"


def test_followup_focus_is_decoupled_from_entity_resolution():
    focus, is_followup = detect_operational_intent("provide me Adani Power's latest news", has_prior_entity=True)

    assert focus == "news"
    assert is_followup is True

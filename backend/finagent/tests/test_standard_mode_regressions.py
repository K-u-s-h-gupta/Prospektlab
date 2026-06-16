from finagent.output.contracts import OutputMode, ResponseDepth
from finagent.output.intent_classifier import classify_output_mode
from finagent.playbooks.executor import apply_playbook_to_queries
from finagent.playbooks.schema import FinancialPlaybook


def test_apply_playbook_queries_rewrites_to_current_target_and_skips_unsafe_templates():
    base = [
        "Reliance Industries Limited RELIANCE governance and valuation India NSE BSE",
    ]
    playbook = FinancialPlaybook(
        name="in_valuation_playbook",
        geography="IN",
        intent_key="valuation",
        query_templates=[
            # Legacy concrete query: should be rewritten via example_target.
            "Adani Power Limited ADANIPOWER valuation PE PB EV EBITDA India NSE BSE",
            # Unsafe template unrelated to current target and no placeholder: should be dropped.
            "Alphageo (India) Limited peer valuation multiples India NSE BSE",
            # Placeholder query: should be rendered for the new target.
            "{target_label} analyst target price rating Moneycontrol Economic Times",
        ],
        example_target="Adani Power Limited",
    )

    out = apply_playbook_to_queries(
        base,
        playbook,
        target_label="Reliance Industries Limited RELIANCE",
    )

    assert len(out) == 3
    assert all("alphageo" not in q.lower() for q in out)
    assert any("reliance industries limited reliance valuation" in q.lower() for q in out)
    assert any("reliance industries limited reliance analyst target price" in q.lower() for q in out)


def test_classify_output_mode_keeps_complex_governance_requests_in_snapshot_mode():
    mode = classify_output_mode(
        query=(
            "Give a comprehensive analysis of Reliance governance, ownership structure, valuation, "
            "regulatory risks, historical context over the last 5 years, and latest developments"
        ),
        target="Reliance Industries Limited",
        depth=ResponseDepth.STANDARD,
    )
    assert mode == OutputMode.COMPANY_SNAPSHOT


def test_classify_output_mode_keeps_simple_ownership_question_direct_answer():
    mode = classify_output_mode(
        query="Who owns Adani Enterprises and what is the promoter shareholding?",
        target="Adani Enterprises",
        depth=ResponseDepth.STANDARD,
    )
    assert mode == OutputMode.DIRECT_ANSWER


def test_classify_output_mode_does_not_treat_vs_history_as_company_comparison():
    mode = classify_output_mode(
        query=(
            "Analyze Reliance valuation versus 5-year history, governance quality, "
            "and key risks with latest catalysts"
        ),
        target="Reliance Industries",
        depth=ResponseDepth.STANDARD,
    )
    assert mode == OutputMode.COMPANY_SNAPSHOT


def test_classify_output_mode_detects_true_company_vs_company_comparison():
    mode = classify_output_mode(
        query="Compare TCS vs Infosys on valuation, margins, and governance quality",
        target="TCS",
        depth=ResponseDepth.STANDARD,
    )
    assert mode == OutputMode.COMPANY_COMPARISON

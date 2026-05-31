from __future__ import annotations

from finagent.output.compliance import enforce_sebi_compliance


def test_enforce_sebi_compliance_rewrites_advisory_headers_and_actions():
    raw = """
## Investment Verdict
This is a strong buy. Investors should buy now because the target price is Rs 500.
The stock is potentially UNDERVALUED.
"""

    safe = enforce_sebi_compliance(raw)
    lower = safe.lower()

    assert "investment verdict" not in lower
    assert "strong buy" not in lower
    assert "should buy" not in lower
    assert "target price" not in lower
    assert "undervalued" not in lower
    assert "evidence-based view" in lower
    assert "not investment advice" in lower


def test_enforce_sebi_compliance_keeps_research_language():
    raw = "## Risk Factors\nPromoter pledge increased by 5 percentage points based on the latest filing."

    safe = enforce_sebi_compliance(raw)

    assert "Promoter pledge increased" in safe
    assert "Regulatory note:" in safe

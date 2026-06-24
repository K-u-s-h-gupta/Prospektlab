"""Tests for the numeric claim ledger."""
from finagent.content.claim_ledger import (
    build_ledger,
    ledger_coverage,
    ledger_number_set,
    verify_article_numbers,
)

SOURCE = (
    "Infosys Q2 FY26: revenue Rs 42,310 crore, up 8.6% YoY. PAT Rs 6,920 crore. "
    "EBIT margin 21.3%. Large-deal TCV USD 3.8 billion. Headcount 3,29,900."
)


def test_build_ledger_extracts_numbers():
    ledger = build_ledger({}, SOURCE)
    nums = ledger_number_set(ledger)
    assert "42310" in nums
    assert "8.6" in nums
    assert "6920" in nums
    assert "21.3" in nums
    assert "3.8" in nums
    assert "329900" in nums


def test_verify_passes_when_all_grounded():
    ledger = build_ledger({}, SOURCE)
    article = "Revenue rose 8.6% to Rs 42,310 crore with a 21.3% margin and TCV of USD 3.8 billion."
    assert verify_article_numbers(article, ledger) == []


def test_verify_flags_invented_number():
    ledger = build_ledger({}, SOURCE)
    article = "Revenue was Rs 52,000 crore this quarter."  # 52000 not in source
    bad = verify_article_numbers(article, ledger)
    assert "52000" in bad


def test_years_and_trivial_ignored():
    ledger = build_ledger({}, SOURCE)
    # FY26 / Q2 / 2 should not count as ungrounded.
    article = "In Q2 FY26 the company had 2 segments leading growth."
    assert verify_article_numbers(article, ledger) == []


def test_messy_numbers_parsed():
    ledger = build_ledger({}, "Range guidance 30.0-40.0%; dividend Rs 21 per share; 109% FCF/PAT.")
    nums = ledger_number_set(ledger)
    # Non-trivial figures land; small numbers (0-4) are intentionally ignored,
    # consistent with content_accuracy's trivia filter.
    assert "30" in nums and "40" in nums and "21" in nums and "109" in nums


def test_coverage_ratio():
    ledger = build_ledger({}, SOURCE)
    cov = ledger_coverage("Margin 21.3% but revenue allegedly Rs 99,999 crore.", ledger)
    assert cov["grounded"] >= 1
    assert cov["ungrounded"] >= 1
    assert 0.0 <= cov["ratio"] <= 1.0


def test_evidence_pack_sources_feed_ledger():
    pack = {"evidence_claims": [{"claim": "Net profit was Rs 6,920 crore", "source_title": "BSE"}]}
    ledger = build_ledger(pack, "")
    assert "6920" in ledger_number_set(ledger)

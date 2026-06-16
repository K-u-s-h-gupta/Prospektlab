"""Tests for the article accuracy guards."""

from __future__ import annotations

from finagent.content.content_accuracy import (
    enforce_article_accuracy,
    extract_number_tokens,
    is_placeholder_metric_value,
    is_suspect_url,
    placeholder_metrics,
    repair_replacement_chars,
    suspect_evidence_urls,
    ungrounded_headline_numbers,
    visual_issues,
)


def test_placeholder_metric_values_flagged():
    assert is_placeholder_metric_value("Disclosed")
    assert is_placeholder_metric_value("Trend disclosed")
    assert is_placeholder_metric_value("Broad band disclosed")
    assert is_placeholder_metric_value("Broadly stable")
    # Period tokens alone are not real numbers.
    assert is_placeholder_metric_value("Disclosed in Q4 FY25")
    assert is_placeholder_metric_value("Reported for FY25")


def test_real_metric_values_pass():
    assert not is_placeholder_metric_value("21.1%")
    assert not is_placeholder_metric_value("Rs 3.77 lakh crore")
    assert not is_placeholder_metric_value("+120 bps")
    assert not is_placeholder_metric_value("11.2x")
    assert not is_placeholder_metric_value("Rs 1,240 crore in Q4 FY25")


def test_placeholder_metrics_collects_labels():
    metrics = [
        {"label": "Operating margin", "value": "21%"},
        {"label": "Attrition", "value": "Trend disclosed"},
    ]
    assert placeholder_metrics(metrics) == ["Attrition"]


# ── mojibake ────────────────────────────────────────────────────────────────


def test_repair_replacement_chars_fixes_apostrophe():
    assert repair_replacement_chars("India�s largest firm") == "India's largest firm"
    assert repair_replacement_chars("the company�s board") == "the company's board"


def test_repair_replacement_chars_noop_when_clean():
    assert repair_replacement_chars("Plain text") == "Plain text"


# ── headline grounding ──────────────────────────────────────────────────────


def test_ungrounded_headline_number_flagged():
    title = "TCS Q4 FY25: 1.3% revenue growth and margin resilience"
    grounded = "The company disclosed revenue growth and operating margin in the results package."
    assert ungrounded_headline_numbers(title, grounded) == ["1.3"]


def test_grounded_headline_number_passes():
    title = "TCS Q4 FY25: 1.3% revenue growth and margin resilience"
    grounded = "According to the BSE filing, revenue grew 1.3% sequentially in Q4 FY25."
    assert ungrounded_headline_numbers(title, grounded) == []


def test_year_and_quarter_tokens_are_not_stats():
    title = "Infosys Q4 FY25 results: FY26 guidance in focus"
    assert ungrounded_headline_numbers(title, "no numbers here at all") == []


def test_extract_number_tokens_normalises():
    assert "1.3" in extract_number_tokens("growth of 1.30%")
    assert "40925" in extract_number_tokens("Rs 40,925 crore")


# ── visuals ─────────────────────────────────────────────────────────────────


def test_placeholder_visual_flagged():
    visual = {
        "title": "TCS disclosure themes",
        "note": "Illustrative emphasis map, not a numeric scorecard.",
        "points": [
            {"label": "Revenue growth", "value": 1.3},
            {"label": "Margin", "value": 1.0},
            {"label": "Dividend", "value": 1.0},
            {"label": "Demand", "value": 1.0},
        ],
    }
    issues = visual_issues(visual)
    assert "self_declared_illustrative" in issues
    assert "placeholder_uniform_values" in issues


def test_real_data_visual_passes():
    visual = {
        "title": "Quarterly revenue (Rs cr)",
        "note": "Source: BSE filings.",
        "points": [
            {"label": "Q1", "value": 38000},
            {"label": "Q2", "value": 38500},
            {"label": "Q3", "value": 39200},
            {"label": "Q4", "value": 40925},
        ],
    }
    assert visual_issues(visual) == []


def test_single_value_visual_flagged():
    visual = {"title": "x", "note": "", "points": [{"label": "a", "value": 5}, {"label": "b", "value": 5}]}
    assert "all_values_identical" in visual_issues(visual)


# ── fabricated URLs ─────────────────────────────────────────────────────────


def test_suspect_url_detects_zero_guid():
    assert is_suspect_url("https://www.bseindia.com/x/0f0f7c7d-0000-4b0f-9f2d-000000000000.pdf")
    assert is_suspect_url("https://example.com/sample-url")


def test_real_url_not_suspect():
    assert not is_suspect_url("https://www.nseindia.com/api/corporate-announcements?symbol=TCS")
    assert not is_suspect_url("https://www.bseindia.com/stock-share-price/tcs/532540/")


def test_suspect_evidence_urls_collects():
    notes = [
        {"claim": "a", "source_url": "https://www.bseindia.com/real.pdf"},
        {"claim": "b", "source_url": "https://x/00000000-0000-0000.pdf"},
    ]
    assert len(suspect_evidence_urls(notes)) == 1


# ── end-to-end enforce ──────────────────────────────────────────────────────


def test_enforce_article_accuracy_cleans_everything():
    data = {
        "title": "TCS Q4 FY25: 1.3% revenue growth and resilient margin",
        "evidence_notes": [
            {"claim": "Results filed on exchanges.", "source_url": "https://www.bseindia.com/real.pdf"},
            {"claim": "Fake.", "source_url": "https://x/0000-0000-0000.pdf"},
        ],
        "timeline": [],
        "visuals": [
            {
                "title": "emphasis",
                "note": "Illustrative emphasis map.",
                "points": [{"label": "a", "value": 1.3}, {"label": "b", "value": 1.0}, {"label": "c", "value": 1.0}],
            }
        ],
    }
    clean, actions = enforce_article_accuracy(data)
    # Fabricated-URL note dropped.
    assert len(clean["evidence_notes"]) == 1
    # Broken visual dropped.
    assert clean["visuals"] == []
    # Ungrounded headline number stripped.
    assert "1.3" not in clean["title"]
    assert len(actions) == 3

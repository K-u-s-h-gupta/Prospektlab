"""Unit tests for company provenance assembly (pure)."""

from __future__ import annotations

from finagent.ikg.company_provenance import assemble_provenance


def _row(predicate, value=None, num=None, url=None, date="2026-03-31", conf=1.0, ev=None):
    return {
        "predicate": predicate, "object_value": value, "value_numeric": num,
        "as_of_date": date, "event_date": None, "confidence": conf,
        "source_table": "shp_raw", "source_url": url, "evidence_text": ev,
    }


def test_empty_rows():
    out = assemble_provenance("LX", "X Ltd", [])
    assert out["summary"]["total_facts"] == 0
    assert out["sections"] == []


def test_grouping_by_predicate():
    rows = [
        _row("has_pledge", num=40.0, url="http://a"),
        _row("has_pledge", num=20.0, url="http://b", date="2025-12-31"),
        _row("audited_by", value="Deloitte", url="http://c"),
    ]
    out = assemble_provenance("LX", "X Ltd", rows)
    preds = {s["predicate"] for s in out["sections"]}
    assert preds == {"has_pledge", "audited_by"}
    pledge = next(s for s in out["sections"] if s["predicate"] == "has_pledge")
    assert len(pledge["facts"]) == 2
    # newest first
    assert pledge["facts"][0]["as_of"] == "2026-03-31"


def test_label_humanization():
    out = assemble_provenance("LX", "X Ltd", [_row("has_promoter_holding", num=55.0)])
    assert out["sections"][0]["label"] == "Promoter Holding"


def test_numeric_value_fallback():
    out = assemble_provenance("LX", "X Ltd", [_row("has_pledge", value=None, num=33.3)])
    assert out["sections"][0]["facts"][0]["value"] == 33.3


def test_citation_ratio():
    rows = [
        _row("has_pledge", num=1, url="http://a"),
        _row("has_pledge", num=2, url=None),
    ]
    out = assemble_provenance("LX", "X Ltd", rows)
    assert out["summary"]["total_facts"] == 2
    assert out["summary"]["cited_facts"] == 1
    assert out["summary"]["citation_ratio"] == 0.5


def test_evidence_truncation_and_shape():
    long_ev = "x" * 500
    out = assemble_provenance("LX", "X Ltd", [_row("has_pledge", num=1, url="http://a", ev=long_ev)])
    fact = out["sections"][0]["facts"][0]
    assert len(fact["evidence"]["detail"]) == 280
    assert fact["evidence"]["source_url"] == "http://a"

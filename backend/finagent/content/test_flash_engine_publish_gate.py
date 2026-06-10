from finagent.content.flash_engine import (
    _evidence_has_numeric_signals,
    _structured_visuals_from_metrics,
)


def test_structured_visuals_from_metrics_skips_diagnostic_rows() -> None:
    visuals = _structured_visuals_from_metrics(
        [
            {"label": "Quality score", "value": "98", "source": "Research run"},
            {"label": "Sources processed", "value": "12", "source": "Research run"},
            {"label": "Revenue", "value": "1200 Cr", "source": "Official filing"},
            {"label": "EBITDA Margin", "value": "18.2%", "source": "Official filing"},
        ]
    )

    assert visuals
    points = visuals[0].get("points") or []
    labels = [str(point.get("label") or "").lower() for point in points]
    assert "quality score" not in labels
    assert "sources processed" not in labels
    assert any("revenue" in label for label in labels)
    assert any("margin" in label for label in labels)


def test_evidence_numeric_signal_detection_ignores_diagnostic_claims() -> None:
    evidence_pack = {"summary": {"attachment_table_count": 0, "attachment_structured_fact_count": 0}}
    diagnostic_claims = [
        {"claim": "Sources processed: 8", "source_title": "Pipeline status", "source_url": "https://example.com"},
        {"claim": "Quality score: 96", "source_title": "Pipeline status", "source_url": "https://example.com"},
    ]
    business_claims = [
        {"claim": "Revenue grew 12% YoY with margin expansion of 120 bps.", "source_title": "Official filing", "source_url": "https://example.com"},
    ]

    assert _evidence_has_numeric_signals(evidence_pack, diagnostic_claims) is False
    assert _evidence_has_numeric_signals(evidence_pack, business_claims) is True

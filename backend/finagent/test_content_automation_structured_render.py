from __future__ import annotations

from finagent.content_automation import (
    ContentArticlePackage,
    _hydrate_structured_article_from_manifest,
    render_article_html,
)


def _base_article_payload() -> dict:
    sections = [
        {
            "heading": "What changed this cycle",
            "paragraphs": [
                "Official disclosures indicate revenue momentum stayed firm while compliance updates became more material for monitoring short-term risk.",
                "The latest update includes enough factual detail to build a clearer monitoring framework for investors tracking quality and execution.",
            ],
            "bullets": ["Revenue momentum: 12.4% YoY", "Operating margin: 18.2% (+120 bps)"],
        },
        {
            "heading": "Business context and market setup",
            "paragraphs": [
                "Demand remained mixed across segments, but higher-priority contracts and better collections supported operating stability in the period.",
                "The filing also highlights where execution discipline matters most over the next two quarters.",
            ],
            "bullets": ["Collection cycle improved vs last quarter"],
        },
        {
            "heading": "Governance and filing trail",
            "paragraphs": [
                "The governance posture remains stable in current filings, with no major disruption in board continuity indicated in the disclosure trail.",
                "This reduces uncertainty in interpreting the latest operational updates.",
            ],
            "bullets": [],
        },
        {
            "heading": "What to monitor next",
            "paragraphs": [
                "Upcoming disclosures should clarify whether margin expansion is durable and whether demand remains resilient in key verticals.",
                "Investors should track whether compliance outcomes and execution pace stay aligned with management commentary.",
            ],
            "bullets": ["Watchpoint: next filing quality and timing"],
        },
    ]
    return {
        "slug": "sample-structured",
        "title": "Structured rendering sample for official disclosure updates",
        "description": (
            "This sample article payload is intentionally plain so the manifest hydration path "
            "must synthesize metrics, tables, visuals, timeline, and evidence notes."
        ),
        "hero_eyebrow": "Research Brief",
        "hero_title": "Official update synthesis with structured evidence",
        "hero_summary": (
            "The generated article should include presentation-ready blocks based on evidence and "
            "section text even when the original payload did not include explicit structured fields."
        ),
        "audience": "Indian investors and market researchers",
        "keywords": ["official disclosure", "earnings context", "structured evidence"],
        "key_takeaways": [],
        "metrics": [],
        "tables": [],
        "visuals": [],
        "timeline": [],
        "evidence_notes": [],
        "sections": sections,
        "faqs": [
            {"question": "What changed?", "answer": "The latest filing shifted the monitoring priorities for investors."},
            {"question": "Why does this matter?", "answer": "It provides fresher evidence on execution and compliance quality."},
            {"question": "What next?", "answer": "Watch upcoming disclosures for confirmation of the reported trajectory."},
        ],
        "cta_label": "Open Dashboard",
        "cta_href": "/#/dashboard",
        "image_prompt": "",
    }


def test_manifest_hydration_adds_structured_blocks() -> None:
    article_data = _base_article_payload()
    manifest = {
        "title": "Sample official update",
        "generated_at": "2026-06-09T08:30:00+00:00",
        "public_url": "https://prospektlab.com/insights/sample-structured/",
        "source_evidence_meta": {
            "source": "NSE",
            "source_url": "https://www.nseindia.com/api/corporate-announcements",
            "attachment_url": "https://example.com/sample.pdf",
            "attachment_extraction_status": "ok",
            "attachment_parser": "docling_markdown",
            "staged_at": "2026-06-09T08:20:00+00:00",
            "attachment_structured_facts": [
                {
                    "name": "sample.xml",
                    "facts": {
                        "facts_count": 42,
                        "period_end": "2026-03-31",
                    },
                }
            ],
        },
        "evidence_claims": [
            {
                "claim": "Revenue momentum remained above ten percent in the latest reporting window.",
                "source_title": "Official disclosure page",
                "source_url": "https://www.nseindia.com/api/corporate-announcements",
                "evidence_snippet": "Announced at: 2026-06-09 08:15:00+00:00",
            },
            {
                "claim": "Operating margin expanded compared with the prior quarter.",
                "source_title": "Official disclosure page",
                "source_url": "https://www.nseindia.com/api/corporate-announcements",
            },
        ],
        "sources_used": [
            {
                "title": "Official filing evidence",
                "url": "https://www.nseindia.com/api/corporate-announcements",
                "snippet": "Disclosure summary with financial and compliance context.",
            }
        ],
    }

    hydrated = _hydrate_structured_article_from_manifest(article_data, manifest)

    assert hydrated["key_takeaways"]
    assert hydrated["metrics"]
    assert hydrated["tables"]
    assert hydrated["visuals"]
    assert hydrated["timeline"]
    assert hydrated["evidence_notes"]
    # Final guard: hydrated payload stays schema-valid for rendering.
    ContentArticlePackage.model_validate(hydrated)


def test_manifest_hydration_filters_diagnostic_only_structured_data() -> None:
    article_data = _base_article_payload()
    article_data["metrics"] = [
        {"label": "Quality score", "value": "98", "change": "", "period": "", "source": "Research run"},
        {"label": "Sources processed", "value": "6", "change": "", "period": "", "source": "Research run"},
    ]
    article_data["tables"] = [
        {
            "title": "Research coverage and limitations",
            "columns": ["Metric", "Value"],
            "rows": [["Specialist findings", "3"], ["Conflicts detected", "0"]],
            "footnote": "",
        }
    ]
    article_data["visuals"] = [
        {
            "kind": "bar",
            "title": "Evidence coverage by source type",
            "points": [{"label": "Official", "value": 2}, {"label": "Trusted", "value": 4}],
            "note": "Diagnostic only",
        }
    ]
    manifest = {
        "title": "Diagnostic-only manifest sample",
        "generated_at": "2026-06-09T08:30:00+00:00",
        "public_url": "https://prospektlab.com/insights/diagnostic-only/",
        "source_evidence_meta": {},
        "evidence_claims": [],
        "sources_used": [],
    }

    hydrated = _hydrate_structured_article_from_manifest(article_data, manifest)

    assert hydrated["metrics"] == []
    assert hydrated["tables"] == []
    assert hydrated["visuals"] == []
    ContentArticlePackage.model_validate(hydrated)


def test_public_renderer_omits_removed_diagnostic_labels() -> None:
    payload = _base_article_payload()
    payload["metrics"] = [
        {"label": "Revenue", "value": "1200 Cr", "change": "+12%", "period": "Q3 FY26", "source": "Official filing"}
    ]
    payload["tables"] = [
        {
            "title": "Research coverage and limitations",
            "columns": ["Metric", "Value"],
            "rows": [["Sources processed", "6"]],
            "footnote": "",
        },
        {
            "title": "Quarterly financial snapshot",
            "columns": ["Metric", "Value"],
            "rows": [["Revenue", "1200 Cr"], ["EBITDA Margin", "18.2%"]],
            "footnote": "",
        },
    ]
    payload["visuals"] = [
        {
            "kind": "bar",
            "title": "Quick visual read of the key data",
            "points": [{"label": "Revenue", "value": 1200.0}, {"label": "Margin", "value": 18.2}],
            "note": "Diagnostic legacy label",
        }
    ]
    article = ContentArticlePackage.model_validate(payload)
    html = render_article_html(
        article,
        "https://prospektlab.com/insights/public-render-check/",
        None,
        "2026-06-10T00:00:00+00:00",
        meta={"sources_used": []},
    )

    assert "Top metrics from the current evidence set" not in html
    assert "Quick visual read of the key data" not in html
    assert "Research coverage and limitations" not in html
    assert "Sources processed" not in html
    assert "Quality score" not in html

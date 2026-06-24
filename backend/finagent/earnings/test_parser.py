from finagent.earnings import parser


def test_parse_earnings_document_prefers_consolidated_table(monkeypatch):
    def fake_extract(_pdf_bytes, *, require_tables=True):
        return {
            "text": "Consolidated financial results for the quarter ended June 2026.",
            "page_count": 1,
            "model": "pymupdf_local",
            "confidence": 0.5,
            "fallback_used": False,
            "error": None,
            "tables": [
                {
                    "page_number": 1,
                    "confidence": 0.5,
                    "page_text": "Statement of consolidated unaudited financial results",
                    "rows": [
                        ["Consolidated financial results", "Quarter ended", "Previous quarter", "Year ago"],
                        ["Revenue from operations", "1,200", "1,000", "900"],
                        ["Profit after tax", "120", "100", "80"],
                        ["Basic EPS", "4.50", "4.00", "3.20"],
                    ],
                }
            ],
        }

    monkeypatch.setattr(parser, "extract_pdf_text", fake_extract)

    parsed = parser.parse_earnings_document(pdf_bytes=b"pdf", metadata={"meeting_date": "2026-06-24"})
    rows = {row["key"]: row for row in parsed["financials"]["rows"]}

    assert parsed["extraction"]["model"] == "pymupdf_local"
    assert parsed["financials"]["metrics"]["revenue"] == 1200.0
    assert rows["revenue"]["current"] == 1200.0
    assert rows["revenue"]["qoq_pct"] == 20.0
    assert rows["pat"]["yoy_pct"] == 50.0
    assert parsed["financials"]["consolidated_tables"][0]["rows"][1][0] == "Revenue from operations"

def test_board_meeting_notice_does_not_require_tables(monkeypatch):
    seen = {}

    def fake_extract(_pdf_bytes, *, require_tables=True):
        seen["require_tables"] = require_tables
        return {
            "text": "Board meeting to consider and approve financial results.",
            "page_count": 1,
            "model": "pymupdf_local",
            "tables": [],
            "error": None,
        }

    monkeypatch.setattr(parser, "extract_pdf_text", fake_extract)

    parser.parse_earnings_document(
        pdf_bytes=b"pdf",
        text="To consider and approve the financial results",
        metadata={"title": "Financial Results - TEST", "summary": "Board meeting to consider financial results"},
    )

    assert seen["require_tables"] is False
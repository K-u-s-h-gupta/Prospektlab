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

def test_parse_labeled_statement_extracts_period_rows_and_derived_ebitda():
    filing_text = """
    AJOONI BIOTECH LIMITED
    Statement of Audited Standalone Financial Results for the Quarter Ended 31 March 2026
    Rs. in Lakhs
    Particulars
    Quarter Ended 31.03.2026 31.12.2025 31.03.2025
    Revenue from operations
    6062.43
    5875.33
    2927.42
    Finance costs
    28.95
    35.80
    26.73
    Depreciation and amortization expenses
    89.79
    99.87
    50.79
    Profit before tax
    112.03
    200.00
    157.50
    Profit for the period
    94.97
    165.00
    154.00
    Earnings per equity share
    Basic
    0.05
    0.08
    0.09
    Notes to financial results
    """

    parsed = parser.parse_earnings_document(
        text=filing_text,
        metadata={"source_url": "https://example.com/result.pdf", "meeting_date": "2026-05-28"},
    )
    rows = {row["key"]: row for row in parsed["financials"]["rows"]}

    assert parsed["financials"]["metrics"]["revenue"] == 60.62
    assert rows["revenue"]["previous_quarter"] == 58.75
    assert rows["revenue"]["same_quarter_last_year"] == 29.27
    assert rows["ebitda"]["current"] == 2.31
    assert rows["eps"]["current"] == 0.05
    assert rows["pat"]["yoy_pct"] == -38.3
    assert parsed["highlights"][0]["text"].startswith("Revenue came in at Rs 60.62 Cr")

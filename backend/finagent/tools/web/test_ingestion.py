from finagent.tools.web.scraper import _extract, _normalize_india_query
from finagent.tools.web.table_parser import extract_layout_preserving_text


def test_table_extraction_preserves_matrix():
    html = """
    <html><head><title>Results</title></head><body>
      <p>Quarterly results announced.</p>
      <table><tr><th>Metric</th><th>Q1</th><th>Q2</th></tr>
      <tr><td>Revenue</td><td>10 Cr</td><td>12 Cr</td></tr></table>
    </body></html>
    """
    title, text, tables = extract_layout_preserving_text(html)
    assert title == "Results"
    assert "| Metric | Q1 | Q2 |" in tables[0]
    assert "| Revenue | 10 Cr | 12 Cr |" in text


def test_extract_adds_unit_annotations_to_tables():
    _title, text = _extract("<table><tr><th>Sales</th></tr><tr><td>500 million</td></tr></table>")
    assert "500 million (50.00 crore)" in text


def test_normalize_query_anchors_indian_terms():
    query = _normalize_india_query("ABC earnings transcript")
    assert "SEBI LODR" in query
    assert "concall" in query

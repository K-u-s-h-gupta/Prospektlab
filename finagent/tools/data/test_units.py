from finagent.tools.data.units import normalize_financial_text_units, normalize_indian_number, parse_number


def test_normalize_indian_number_to_crore():
    assert normalize_indian_number("125 Cr").crore == 125
    assert normalize_indian_number("1,250 lakhs").crore == 12.5
    assert normalize_indian_number("500 million").crore == 50
    assert normalize_indian_number("2 billion").crore == 200


def test_parse_number_keeps_bare_metrics():
    assert parse_number("34.5%") == 34.5
    assert parse_number("1,234", default_unit="cr") == 1234


def test_financial_text_annotation_preserves_original():
    text = normalize_financial_text_units("Revenue was INR 500 million and profit was 20 lakhs.")
    assert "INR 500 million (50.00 crore)" in text
    assert "20 lakhs (0.20 crore)" in text

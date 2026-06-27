from pathlib import Path
path = Path('backend/finagent/earnings/parser.py')
text = path.read_text(encoding='utf-8')
old = '''    source_url = str(metadata.get("source_url") or metadata.get("attachment_url") or "").strip()
    table_current, table_previous, table_year_ago = _metrics_from_tables(selected_tables, full_text=full_text)
    current_metrics = extract_financial_metrics(analysis_text)
    current_metrics.update(table_current)
    comparison_previous = previous_metrics or table_previous
    comparison_year_ago = year_ago_metrics or table_year_ago

    # Detect pre-meeting intimation: text looks like a notice with no actual financial data
    is_intimation = (
        bool(pdf_bytes)
        and _is_intimation_text(full_text)
        and not bool(current_metrics)
    )

    payload = build_document_payload(
        text=analysis_text,
        source_url=source_url,
        current_metrics=current_metrics,
        previous_metrics=comparison_previous,
        year_ago_metrics=comparison_year_ago,
    )
'''
new = '''    source_url = str(metadata.get("source_url") or metadata.get("attachment_url") or "").strip()
    table_current, table_previous, table_year_ago = _metrics_from_tables(selected_tables, full_text=full_text)
    free_text_metrics = extract_financial_metrics(analysis_text)

    # Indian results PDFs often lose table structure in PyMuPDF, but the text
    # still preserves the P&L section as label + sequential values. Prefer that
    # section-level extraction over whole-document regexes so EPS is not confused
    # with face value and EBITDA is not picked from cash-flow working-capital rows.
    standalone_current, standalone_previous, standalone_year_ago = _extract_metric_periods_from_labeled_section(
        full_text,
        "standalone",
    )
    consolidated_current, consolidated_previous, consolidated_year_ago = _extract_metric_periods_from_labeled_section(
        full_text,
        "consolidated",
    )

    consolidated_tables = tables_by_type.get("consolidated") or []
    standalone_tables_only = tables_by_type.get("standalone") or []

    if not consolidated_current and consolidated_tables:
        consolidated_current, consolidated_previous, consolidated_year_ago = _metrics_from_tables(
            consolidated_tables,
            full_text=full_text,
        )

    if not standalone_current and standalone_tables_only:
        cons_pages = {t.get("page_number") for t in consolidated_tables}
        stand_pages = {t.get("page_number") for t in standalone_tables_only}
        if stand_pages != cons_pages:
            standalone_current, standalone_previous, standalone_year_ago = _metrics_from_tables(
                standalone_tables_only,
                full_text=full_text,
            )

    if consolidated_current:
        current_metrics = consolidated_current
        detected_previous = consolidated_previous
        detected_year_ago = consolidated_year_ago
    elif table_current:
        current_metrics = table_current
        detected_previous = table_previous
        detected_year_ago = table_year_ago
    elif standalone_current:
        current_metrics = standalone_current
        detected_previous = standalone_previous
        detected_year_ago = standalone_year_ago
    else:
        current_metrics = free_text_metrics
        detected_previous = {}
        detected_year_ago = {}

    comparison_previous = previous_metrics or detected_previous
    comparison_year_ago = year_ago_metrics or detected_year_ago
    financial_rows = build_financial_comparison_rows(
        current_metrics,
        comparison_previous,
        comparison_year_ago,
    )
    metric_highlights = _build_metric_highlights(financial_rows, source_url)

    # Detect pre-meeting intimation: text looks like a notice with no actual financial data
    is_intimation = (
        bool(pdf_bytes)
        and _is_intimation_text(full_text)
        and not bool(current_metrics)
    )

    payload = build_document_payload(
        text=analysis_text,
        source_url=source_url,
        current_metrics=current_metrics,
        previous_metrics=comparison_previous,
        year_ago_metrics=comparison_year_ago,
    )
'''
if old not in text:
    raise SystemExit('parse metrics block not found')
text = text.replace(old, new)
old = '''    commentary = payload["highlights"][:]
    if analysis_text and not commentary:
        commentary = [
            {
                "text": compact_summary(analysis_text, 180),
                "url": source_url,
                "source_label": "official filing" if source_url else "",
            }
        ]

    financial_rows = payload["financial_comparison"]
    if table_current:
        financial_rows = build_financial_comparison_rows(table_current, comparison_previous, comparison_year_ago)

    # === Extract metrics from both standalone and consolidated sections ===
    # Indian earnings PDFs typically have two distinct sections:
    # 1. "Standalone Statement of Profit and Loss" 
    # 2. "Consolidated Statement of Profit and Loss"
    standalone_metrics_raw: dict[str, Any] = {}
    consolidated_metrics_raw: dict[str, Any] = {}
    
    # Strategy 1: Text-based section extraction (most reliable for Indian filings)
    standalone_metrics_raw = _extract_metrics_from_labeled_section(full_text, "standalone")
    consolidated_metrics_raw = _extract_metrics_from_labeled_section(full_text, "consolidated")
    
    # Strategy 2: Table-based extraction as fallback
    consolidated_tables = tables_by_type.get("consolidated") or []
    standalone_tables_only = tables_by_type.get("standalone") or []
    
    if not consolidated_metrics_raw and consolidated_tables:
        consolidated_metrics_raw, _, _ = _metrics_from_tables(consolidated_tables, full_text=full_text)
    
    if not standalone_metrics_raw and standalone_tables_only:
        cons_pages = {t.get("page_number") for t in consolidated_tables}
        stand_pages = {t.get("page_number") for t in standalone_tables_only}
        if stand_pages != cons_pages:
            standalone_metrics_raw, _, _ = _metrics_from_tables(standalone_tables_only, full_text=full_text)
    
    # If only got consolidated, use it as the main metrics
    if consolidated_metrics_raw and not current_metrics:
        current_metrics = consolidated_metrics_raw.copy()
    
    # Log what we found for debugging
'''
new = '''    commentary = metric_highlights[:] or payload["highlights"][:]
    if analysis_text and not commentary:
        commentary = [
            {
                "text": compact_summary(analysis_text, 180),
                "url": source_url,
                "source_label": "official filing" if source_url else "",
            }
        ]

    standalone_metrics_raw = standalone_current
    consolidated_metrics_raw = consolidated_current
    
    # Log what we found for debugging
'''
if old not in text:
    raise SystemExit('commentary/section block not found')
text = text.replace(old, new)
text = text.replace('        "highlights": payload["highlights"],', '        "highlights": metric_highlights or payload["highlights"],')
path.write_text(text, encoding='utf-8')

# Lazy / optional import for chart generation.
# The gateway can start without matplotlib; chart functions will raise
# a clear error only when actually called.
try:
    from finagent.output.chart_generator import (
        generate_comparison_chart,
        generate_metric_gauge,
        generate_multiseries_line_chart,
        generate_price_chart,
        generate_revenue_chart,
        generate_sparkline,
    )
except ImportError:
    generate_comparison_chart = None
    generate_metric_gauge = None
    generate_multiseries_line_chart = None
    generate_price_chart = None
    generate_revenue_chart = None
    generate_sparkline = None
from finagent.output.confidence_scorer import aggregate_confidence
from finagent.output.conflict_reporter import conflict_block
from finagent.output.contracts import AnswerArtifact, AnswerCitation, AnswerTable, OutputMode, ResponseDepth, ResponseSection
from finagent.output.memo_formatter import MemoSection, format_memo
from finagent.output.renderer import render_markdown

__all__ = [
    "AnswerArtifact",
    "AnswerCitation",
    "AnswerTable",
    "OutputMode",
    "ResponseDepth",
    "ResponseSection",
    "MemoSection",
    "format_memo",
    "render_markdown",
    "aggregate_confidence",
    "conflict_block",
    "generate_price_chart",
    "generate_revenue_chart",
    "generate_comparison_chart",
    "generate_sparkline",
    "generate_multiseries_line_chart",
    "generate_metric_gauge",
]

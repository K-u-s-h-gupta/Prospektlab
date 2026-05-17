from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OutputMode(str, Enum):
    DIRECT_ANSWER = "direct_answer"
    COMPANY_SNAPSHOT = "company_snapshot"
    COMPANY_COMPARISON = "company_comparison"
    VALUATION_MODEL = "valuation_model"
    NEWS_BRIEF = "news_brief"
    FILING_ANALYSIS = "filing_analysis"
    DOCUMENT_VERSION_COMPARISON = "document_version_comparison"
    INVESTMENT_VIEW = "investment_view"
    MARKET_EXPLAINER = "market_explainer"
    DEEP_RESEARCH_REPORT = "deep_research_report"


class ResponseDepth(str, Enum):
    CHAT = "chat"
    STANDARD = "standard"
    DEEP = "deep"


@dataclass
class ResponseSection:
    title: str
    body: str
    confidence: str = "MEDIUM"
    citations: list[str] = field(default_factory=list)


@dataclass
class AnswerTable:
    title: str
    columns: list[str]
    rows: list[list[str]]


@dataclass
class AnswerCitation:
    title: str
    url: str
    kind: str = "source"
    domain: str | None = None


@dataclass
class ChartDataPoint:
    """Single data point for chart series."""
    label: str
    value: float
    secondary_value: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChartSeries:
    """Data series for charts."""
    name: str
    color: str
    data: list[ChartDataPoint]
    unit: str = ""
    chart_type: str = "line"  # line, bar, area, pie


@dataclass
class AnswerChart:
    """Chart visualization component."""
    id: str
    title: str
    subtitle: str = ""
    chart_type: str = "line"  # line, bar, area, pie, comparison
    series: list[ChartSeries] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    dimensions: dict[str, int] = field(default_factory=lambda: {"width": 600, "height": 300})
    svg_data: str = ""
    png_data: str = ""
    is_partial: bool = False


@dataclass
class MetricCard:
    """Metric card component for displaying key metrics."""
    label: str
    value: str
    change: str = ""
    change_type: str = "neutral"  # positive, negative, neutral
    sparkline_svg: str = ""
    tooltip: str = ""
    icon: str = ""
    is_partial: bool = False


@dataclass
class VisualSection:
    """Visual layout section component."""
    section_type: str  # metrics_grid, chart_row, comparison_table, text_block
    title: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    columns: int = 1
    order: int = 0
    is_partial: bool = False


@dataclass
class ComparisonResult:
    """Comparison result between two entities."""
    metric: str
    primary_value: str
    secondary_value: str
    winner: str | None = None  # "primary", "secondary", or None for tie
    delta: str = ""
    primary_entity: str = ""
    secondary_entity: str = ""


@dataclass
class AnswerArtifact:
    mode: OutputMode
    depth: ResponseDepth
    title: str
    summary: str
    sections: list[ResponseSection] = field(default_factory=list)
    tables: list[AnswerTable] = field(default_factory=list)
    citations: list[AnswerCitation] = field(default_factory=list)
    follow_up_suggestions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    charts: list[AnswerChart] = field(default_factory=list)
    metric_cards: list[MetricCard] = field(default_factory=list)
    visual_sections: list[VisualSection] = field(default_factory=list)
    comparison_results: list[ComparisonResult] = field(default_factory=list)


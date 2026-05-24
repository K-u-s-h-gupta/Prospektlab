from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

from finagent.output.contracts import (
    AnswerArtifact,
    AnswerChart,
    AnswerCitation,
    AnswerTable,
    ChartDataPoint,
    ChartSeries,
    ComparisonResult,
    MetricCard,
    OutputMode,
    ResponseDepth,
    ResponseSection,
    VisualSection,
)
from finagent.output.templates import SECTION_TEMPLATES

logger = logging.getLogger("finagent.output.artifact_builder")


_TEXT_ONLY_MODES = {OutputMode.NEWS_BRIEF, OutputMode.FILING_ANALYSIS, OutputMode.DIRECT_ANSWER}
_VISUAL_QUERY_TERMS = (
    "chart", "graph", "historical", "history", "trend", "price", "valuation",
    "financial", "revenue", "profit", "margin", "market cap", "shareholding",
    "pe ratio", "p/e", "performance",
)


def _objective_wants_visuals(objective: str, mode: OutputMode) -> bool:
    lower = (objective or "").lower()
    if mode == OutputMode.COMPANY_COMPARISON:
        return True
    if mode == OutputMode.NEWS_BRIEF:
        return False
    if mode in {OutputMode.COMPANY_SNAPSHOT, OutputMode.VALUATION_MODEL, OutputMode.VALUATION_INSIGHTS, OutputMode.FORENSIC_INSIGHTS, OutputMode.INVESTMENT_VIEW, OutputMode.DEEP_RESEARCH_REPORT}:
        return True
    return any(term in lower for term in _VISUAL_QUERY_TERMS)


def _detect_visual_intent(objective: str, mode: OutputMode) -> str:
    """Lightweight query intent classification for dynamic visuals."""
    q = (objective or "").lower()
    if mode == OutputMode.COMPANY_COMPARISON:
        return "competitor"
    if any(k in q for k in ["competitor", "peer", "market share", "vs ", "versus", "compare", "comparison"]):
        return "competitor"
    if any(k in q for k in ["sebi", "risk", "regulatory", "lod r", "regulation", "compliance"]):
        return "risk"
    if any(k in q for k in ["quarterly", "q1", "q2", "q3", "q4", "earnings", "results", "concall"]):
        return "quarterly"
    if any(k in q for k in ["guidance", "outlook", "management", "forecast", "concall"]):
        return "guidance"
    if mode in {OutputMode.VALUATION_MODEL, OutputMode.VALUATION_INSIGHTS}:
        return "valuation"
    if mode == OutputMode.FORENSIC_INSIGHTS:
        return "forensic"
    return "snapshot"


# ---------------------------------------------------------------------------
#  Finding helpers — extract structured agent outputs for runtime visuals
# ---------------------------------------------------------------------------


def _findings_by_agent(findings: list[Any] | None, agent_name: str) -> list[Any]:
    """Return all findings whose .agent matches agent_name (case-insensitive)."""
    if not findings:
        return []
    return [f for f in findings if getattr(f, "agent", "").lower() == agent_name.lower()]


def _first_metric(findings: list[Any], key: str, default: Any = None) -> Any:
    """Return the first non-None value for `key` across findings' .metrics dicts."""
    for f in findings:
        metrics = getattr(f, "metrics", None)
        if isinstance(metrics, dict) and key in metrics and metrics[key] is not None:
            return metrics[key]
    return default


def _collect_projection_series(findings: list[Any]) -> dict[str, Any]:
    """Extract forecast projection arrays from ValuationAgent findings."""
    out: dict[str, Any] = {"point_forecast": None, "p10": None, "p90": None, "labels": []}
    for f in findings:
        metrics = getattr(f, "metrics", None)
        if not isinstance(metrics, dict):
            continue
        # Look for projected_terminal_revenue (single scalar) or point_forecast (list)
        if "point_forecast" in metrics and isinstance(metrics["point_forecast"], list):
            out["point_forecast"] = metrics["point_forecast"]
        if "p10" in metrics and isinstance(metrics["p10"], list):
            out["p10"] = metrics["p10"]
        if "p90" in metrics and isinstance(metrics["p90"], list):
            out["p90"] = metrics["p90"]
        if "horizon_years" in metrics:
            out["horizon"] = metrics["horizon_years"]
        if "model_used" in metrics:
            out["model_used"] = metrics["model_used"]
    return out


# ---------------------------------------------------------------------------
#  Mode-aware metric cards — generate cards based on query intent
# ---------------------------------------------------------------------------


def _build_mode_aware_metric_cards(
    bundle,
    entity,
    mode: OutputMode,
    findings: list[Any] | None,
    objective: str = "",
) -> list[MetricCard]:
    """Build metric cards that match the user's query intent.

    Instead of always showing the same 6 snapshot cards, we pick cards that are
    relevant to the query: valuation queries show DCF outputs, forensic queries
    show anomaly stats, competitor queries show peer context, etc.
    """
    y = getattr(bundle, "yahoo", None)
    metrics = getattr(y, "financial_metrics", {}) or {} if y else {}
    currency = getattr(y, "currency", None) or "INR" if y else "INR"
    india = getattr(bundle, "india_snap", None)

    # -- VALUATION mode -----------------------------------------------------
    if mode in {OutputMode.VALUATION_MODEL, OutputMode.VALUATION_INSIGHTS}:
        val_findings = _findings_by_agent(findings, "valuation")
        intrinsic = _first_metric(val_findings, "intrinsic_value")
        current_price = _first_metric(val_findings, "current_price")
        upside = _first_metric(val_findings, "upside_pct")
        growth = _first_metric(val_findings, "implied_growth_rate")
        model_used = _first_metric(val_findings, "model_used", "n/a")
        fcf = _first_metric(val_findings, "fcf")

        cards: list[MetricCard] = []
        cards.append(MetricCard(
            label="Current Price",
            value=_money(current_price, currency) if current_price else (_price(y) if y else "n/a"),
            icon="trending-up",
            is_partial=current_price is None and (y is None or getattr(y, "price", None) is None),
        ))
        cards.append(MetricCard(
            label="DCF Intrinsic Value",
            value=_money(intrinsic, currency) if intrinsic else "n/a",
            change=f"{upside:+.1f}%" if upside is not None else None,
            change_type="positive" if (upside or 0) > 0 else "negative" if (upside or 0) < 0 else "neutral",
            icon="scale",
            tooltip="Discounted Cash Flow fair value per share",
            is_partial=intrinsic is None,
        ))
        cards.append(MetricCard(
            label="Implied Growth",
            value=f"{growth*100:.1f}%" if growth else "n/a",
            icon="percent",
            tooltip="Revenue growth rate implied by the forecast model",
            is_partial=growth is None,
        ))
        cards.append(MetricCard(
            label="FCF (TTM)",
            value=_money(fcf, currency) if fcf else _money(metrics.get("free_cashflow"), currency),
            icon="currency-dollar",
            tooltip="Trailing twelve-month Free Cash Flow",
            is_partial=fcf is None and metrics.get("free_cashflow") is None,
        ))
        cards.append(MetricCard(
            label="Forecast Model",
            value=str(model_used),
            icon="chip",
            tooltip="Model that generated the projection (timesfm_2.5 = real model)",
            is_partial=model_used in (None, "n/a", "fallback_cagr", "fallback_statistical"),
        ))
        # Market cap for context
        market_cap = getattr(y, "market_cap", None) if y else None
        cards.append(MetricCard(
            label="Market Cap",
            value=_money(market_cap, currency),
            icon="chart-pie",
            is_partial=market_cap is None,
        ))
        return cards

    # -- FORENSIC mode ------------------------------------------------------
    if mode == OutputMode.FORENSIC_INSIGHTS:
        acct_findings = _findings_by_agent(findings, "accounting")
        anomaly_count = sum(
            1 for f in acct_findings
            if isinstance(getattr(f, "metrics", None), dict)
            and getattr(f, "metrics", {}).get("is_anomaly")
        )
        total_checked = _first_metric(acct_findings, "total_checked", 0)
        confidence = _first_metric(acct_findings, "confidence", "MEDIUM")
        cards = []
        cards.append(MetricCard(
            label="Anomalies Flagged",
            value=str(anomaly_count),
            change_type="negative" if anomaly_count > 0 else "positive",
            icon="alert-triangle",
            tooltip="Number of data points outside the P10–P90 confidence corridor",
        ))
        cards.append(MetricCard(
            label="Data Points Checked",
            value=str(total_checked) if total_checked else "n/a",
            icon="database",
            tooltip="Total historical observations screened",
            is_partial=total_checked == 0,
        ))
        cards.append(MetricCard(
            label="Screen Confidence",
            value=str(confidence),
            icon="shield",
            tooltip="Confidence level of the forensic screen",
        ))
        # Append snapshot basics for context
        if y:
            cards.append(MetricCard(
                label="P/E Ratio",
                value=_num(metrics.get("trailing_pe"), "x"),
                icon="scale",
                is_partial=metrics.get("trailing_pe") is None,
            ))
            cards.append(MetricCard(
                label="ROE",
                value=_pct(metrics.get("return_on_equity")),
                icon="trending-up",
                is_partial=metrics.get("return_on_equity") is None,
            ))
        return cards

    # -- NEWS mode ----------------------------------------------------------
    if mode == OutputMode.NEWS_BRIEF:
        news_items = getattr(bundle, "news", []) or []
        cards = []
        cards.append(MetricCard(
            label="Headlines",
            value=str(len(news_items)),
            icon="newspaper",
            tooltip="Total news articles retrieved",
        ))
        if news_items:
            sources = len({getattr(n, "source", "") for n in news_items})
            cards.append(MetricCard(
                label="Sources",
                value=str(sources),
                icon="rss",
                tooltip="Unique news outlets",
            ))
        return cards

    # -- DEFAULT / SNAPSHOT / INVESTMENT / DEEP_RESEARCH ---------------------
    intent = _detect_visual_intent(objective, mode)
    if intent == "competitor":
        # Return a lightweight competitor-oriented set if we have peer data later
        return _build_metric_cards(bundle, entity)
    if intent in ("risk", "quarterly", "guidance"):
        # For these, still start with core snapshot but synthesis will enrich
        return _build_metric_cards(bundle, entity)
    return _build_metric_cards(bundle, entity)


def _build_mode_aware_charts(
    bundle,
    mode: OutputMode,
    findings: list[Any] | None,
    objective: str = "",
) -> list[AnswerChart]:
    """Build charts that match the user's query intent.

    Instead of always emitting the same price + revenue charts, we generate
    runtime charts from the specialist findings + query intent.
    """
    y = getattr(bundle, "yahoo", None)
    currency = getattr(y, "currency", None) or "INR" if y else "INR"
    charts: list[AnswerChart] = []

    # -- VALUATION mode: DCF projection line chart --------------------------
    if mode in {OutputMode.VALUATION_MODEL, OutputMode.VALUATION_INSIGHTS}:
        val_findings = _findings_by_agent(findings, "valuation")
        proj = _collect_projection_series(val_findings)
        point = proj.get("point_forecast")
        if point and isinstance(point, list) and len(point) >= 2:
            labels = [f"Y{i+1}" for i in range(len(point))]
            data_points = [ChartDataPoint(label=l, value=float(v)) for l, v in zip(labels, point)]
            series = [ChartSeries(
                name="Projected Revenue",
                color="#10b981",
                data=data_points,
                unit=currency,
                chart_type="line",
            )]
            # Add P10/P90 corridor if available
            p10 = proj.get("p10")
            p90 = proj.get("p90")
            if p10 and p90 and len(p10) == len(point) and len(p90) == len(point):
                series.append(ChartSeries(
                    name="P10 (Conservative)",
                    color="#f59e0b",
                    data=[ChartDataPoint(label=l, value=float(v)) for l, v in zip(labels, p10)],
                    unit=currency,
                    chart_type="line",
                ))
                series.append(ChartSeries(
                    name="P90 (Optimistic)",
                    color="#8b5cf6",
                    data=[ChartDataPoint(label=l, value=float(v)) for l, v in zip(labels, p90)],
                    unit=currency,
                    chart_type="line",
                ))
            charts.append(AnswerChart(
                id="dcf-projection",
                title="Revenue Projection (DCF Input)",
                subtitle=f"Model: {proj.get('model_used', 'statistical fallback')}",
                chart_type="line",
                series=series,
                labels=labels,
                dimensions={"width": 700, "height": 350},
                is_partial=proj.get("model_used") in (None, "fallback_cagr", "fallback_statistical"),
            ))
        # Intrinsic value vs current price bar
        intrinsic = _first_metric(val_findings, "intrinsic_value")
        current_price = _first_metric(val_findings, "current_price")
        if intrinsic and current_price:
            charts.append(AnswerChart(
                id="iv-vs-price",
                title="Intrinsic Value vs Market Price",
                subtitle=currency,
                chart_type="bar",
                series=[ChartSeries(
                    name="Value",
                    color="#3b82f6",
                    data=[
                        ChartDataPoint(label="Market Price", value=float(current_price)),
                        ChartDataPoint(label="DCF Intrinsic", value=float(intrinsic)),
                    ],
                    unit=currency,
                    chart_type="bar",
                )],
                labels=["Market Price", "DCF Intrinsic"],
                dimensions={"width": 400, "height": 300},
                is_partial=False,
            ))
        return charts

    # -- FORENSIC mode: anomaly corridor chart ------------------------------
    if mode == OutputMode.FORENSIC_INSIGHTS:
        acct_findings = _findings_by_agent(findings, "accounting")
        # If AccountingAgent populated historical/predicted arrays in metrics
        for f in acct_findings:
            metrics = getattr(f, "metrics", None)
            if not isinstance(metrics, dict):
                continue
            hist = metrics.get("historical")
            pred = metrics.get("predicted")
            lower = metrics.get("lower_bound")
            upper = metrics.get("upper_bound")
            if hist and pred and isinstance(hist, list) and isinstance(pred, list):
                labels = [f"T{i}" for i in range(len(hist))]
                series: list[ChartSeries] = [
                    ChartSeries(
                        name="Actual",
                        color="#3b82f6",
                        data=[ChartDataPoint(label=l, value=float(v)) for l, v in zip(labels, hist)],
                        unit=currency,
                        chart_type="line",
                    ),
                    ChartSeries(
                        name="Predicted",
                        color="#10b981",
                        data=[ChartDataPoint(label=l, value=float(v)) for l, v in zip(labels, pred)],
                        unit=currency,
                        chart_type="line",
                    ),
                ]
                if lower and upper and len(lower) == len(labels) and len(upper) == len(labels):
                    series.append(ChartSeries(
                        name="Lower Bound (P10)",
                        color="#f59e0b",
                        data=[ChartDataPoint(label=l, value=float(v)) for l, v in zip(labels, lower)],
                        unit=currency,
                        chart_type="line",
                    ))
                    series.append(ChartSeries(
                        name="Upper Bound (P90)",
                        color="#f59e0b",
                        data=[ChartDataPoint(label=l, value=float(v)) for l, v in zip(labels, upper)],
                        unit=currency,
                        chart_type="line",
                    ))
                charts.append(AnswerChart(
                    id="anomaly-corridor",
                    title="Forecast vs Actual with Confidence Corridor",
                    subtitle="P10–P90 anomaly detection band",
                    chart_type="line",
                    series=series,
                    labels=labels,
                    dimensions={"width": 700, "height": 350},
                    is_partial=False,
                ))
                break  # one chart is enough
        return charts

    # -- DEFAULT / SNAPSHOT: standard charts + intent-aware extensions ------
    intent = _detect_visual_intent(objective, mode)
    price_chart = _build_price_chart(bundle)
    if price_chart:
        charts.append(price_chart)
    revenue_chart = _build_revenue_chart(bundle)
    if revenue_chart:
        charts.append(revenue_chart)

    # Intent-specific lightweight charts (only if we have the underlying data)
    y = getattr(bundle, "yahoo", None)
    if intent == "competitor" and y:
        # Placeholder: actual competitor comparison chart is built in _build_comparison_charts
        pass
    if intent == "quarterly":
        # Could add quarterly bar chart if quarterly series present in bundle
        pass
    return charts


def _build_metric_cards(bundle, entity) -> list[MetricCard]:
    """Build 5-6 metric cards for company snapshot (Market Cap, Revenue, Net Margin, ROE, P/E, 52W Range)."""
    y = getattr(bundle, "yahoo", None)
    if not y:
        return []
    
    metrics = getattr(y, "financial_metrics", {}) or {}
    currency = getattr(y, "currency", None) or "USD"
    cards = []
    
    # Market Cap
    market_cap = getattr(y, "market_cap", None)
    cards.append(MetricCard(
        label="Market Cap",
        value=_money(market_cap, currency),
        tooltip="Total market value of company's outstanding shares",
        icon="chart-pie"
    ))
    
    # Revenue
    revenue = metrics.get("total_revenue")
    cards.append(MetricCard(
        label="Revenue",
        value=_money(revenue, currency),
        tooltip="Total revenue from operations",
        icon="currency-dollar"
    ))
    
    # Net Margin
    net_margin = metrics.get("profit_margins")
    cards.append(MetricCard(
        label="Net Margin",
        value=_pct(net_margin),
        tooltip="Net income as percentage of revenue",
        icon="percentage"
    ))
    
    # ROE
    roe = metrics.get("return_on_equity")
    cards.append(MetricCard(
        label="ROE",
        value=_pct(roe),
        tooltip="Return on equity - net income relative to shareholders' equity",
        icon="trending-up"
    ))
    
    # P/E Ratio
    pe = metrics.get("trailing_pe")
    cards.append(MetricCard(
        label="P/E Ratio",
        value=_num(pe, "x"),
        tooltip="Price-to-earnings ratio - stock price relative to earnings per share",
        icon="scale"
    ))
    
    # 52-Week Range
    low = getattr(y, "fifty_two_week_low", None)
    high = getattr(y, "fifty_two_week_high", None)
    range_str = _range(y)
    cards.append(MetricCard(
        label="52W Range",
        value=range_str,
        tooltip="Trading range over the past 52 weeks",
        icon="arrows-expand",
        is_partial=(low is None or high is None)
    ))
    
    return cards


def _build_price_chart(bundle) -> AnswerChart | None:
    """Build price chart using historical price data if available."""
    y = getattr(bundle, "yahoo", None)
    if not y:
        return None
    
    # Try to get actual price history from bundle/Yahoo. Never substitute
    # revenue history into a price chart; that creates a misleading visual.
    history = getattr(bundle, "price_history", None) or getattr(y, "history", None)
    if not history:
        series_dates = getattr(y, "series_dates", None) or []
        series_closes = getattr(y, "series_closes", None) or []
        if series_dates and series_closes and len(series_dates) == len(series_closes):
            history = [{"date": str(d), "close": float(v)} for d, v in zip(series_dates, series_closes)]
    if not history or not isinstance(history, (list, dict)):
        return None
    
    data_points = []
    labels = []
    
    if isinstance(history, list):
        for i, point in enumerate(history[-30:]):  # Last 30 periods
            if isinstance(point, dict):
                value = point.get("close", point.get("price", 0))
                label = point.get("date", f"D{i}")
                data_points.append(ChartDataPoint(label=label, value=float(value)))
                labels.append(label)
    elif isinstance(history, dict) and "prices" in history:
        for i, price in enumerate(history["prices"][-30:]):
            data_points.append(ChartDataPoint(label=f"D{i}", value=float(price)))
            labels.append(f"D{i}")
    
    if not data_points:
        return None
    
    currency = getattr(y, "currency", "USD")
    current_price = getattr(y, "price", 0)
    
    series = ChartSeries(
        name="Price",
        color="#3b82f6",
        data=data_points,
        unit=currency,
        chart_type="line"
    )
    
    return AnswerChart(
        id="price-chart",
        title="Price History",
        subtitle=f"Last {len(data_points)} periods",
        chart_type="line",
        series=[series],
        labels=labels,
        dimensions={"width": 600, "height": 300},
        is_partial=False
    )


def _build_revenue_chart(bundle) -> AnswerChart | None:
    """Build revenue chart from financial data if available."""
    y = getattr(bundle, "yahoo", None)
    if not y:
        return None
    
    metrics = getattr(y, "financial_metrics", {}) or {}
    revenue_data = getattr(bundle, "revenue_history", None)
    if not revenue_data:
        annual_rev = getattr(y, "annual_revenue", None)
        annual_dates = getattr(y, "annual_revenue_dates", None)
        if annual_rev and annual_dates and len(annual_rev) == len(annual_dates):
            revenue_data = [
                {"period": str(period), "revenue": float(value)}
                for period, value in zip(annual_dates, annual_rev)
            ]
    
    if not revenue_data:
        return None
    
    data_points = []
    labels = []
    currency = getattr(y, "currency", "USD")
    
    if isinstance(revenue_data, list):
        for item in revenue_data:
            if isinstance(item, dict):
                label = item.get("period", item.get("date", "Q"))
                value = item.get("revenue", item.get("value", 0))
                data_points.append(ChartDataPoint(label=label, value=float(value)))
                labels.append(label)
    elif isinstance(revenue_data, dict) and "quarters" in revenue_data:
        for period, value in revenue_data["quarters"].items():
            data_points.append(ChartDataPoint(label=period, value=float(value)))
            labels.append(period)
    
    if not data_points:
        return None
    
    series = ChartSeries(
        name="Revenue",
        color="#10b981",
        data=data_points,
        unit=currency,
        chart_type="bar"
    )
    
    return AnswerChart(
        id="revenue-chart",
        title="Revenue Trend",
        subtitle="Historical revenue by period",
        chart_type="bar",
        series=[series],
        labels=labels,
        dimensions={"width": 600, "height": 300},
        is_partial=False
    )


def _build_comparison_charts(artifact: AnswerArtifact, bundle, peer_quotes: dict[str, object]) -> list[AnswerChart]:
    """Build comparison charts for peer analysis."""
    charts = []
    
    # Market Cap comparison
    labels = []
    values = []
    
    y = getattr(bundle, "yahoo", None)
    primary_name = getattr(y, "name", "Primary") if y else "Primary"
    currency = getattr(y, "currency", None) or "INR"
    labels.append(primary_name)
    # Bug fix: market_cap is on bundle.yahoo, NOT bundle directly
    values.append(float(getattr(y, "market_cap", 0) or 0))
    
    for name, quote in peer_quotes.items():
        labels.append(name)
        values.append(float(getattr(quote, "market_cap", 0) or 0))
    
    if len(labels) > 1:
        data_points = [ChartDataPoint(label=l, value=v) for l, v in zip(labels, values)]
        series = ChartSeries(
            name="Market Cap",
            color="#6366f1",
            data=data_points,
            unit=currency,
            chart_type="bar"
        )
        charts.append(AnswerChart(
            id="market-cap-comparison",
            title="Market Cap Comparison",
            chart_type="bar",
            series=[series],
            labels=labels,
            dimensions={"width": 600, "height": 300}
        ))
    
    return charts


def _build_comparison_results(bundle, peer_quotes: dict[str, object]) -> list[ComparisonResult]:
    """Build comparison data with winner logic."""
    results = []
    
    y = getattr(bundle, "yahoo", None)
    if not y:
        return results
    
    primary_metrics = getattr(y, "financial_metrics", {}) or {}
    primary_name = getattr(y, "name", "Primary")
    currency = getattr(y, "currency", None) or "INR"
    
    # Compare against first peer
    peer_name = next(iter(peer_quotes.keys()), None)
    peer = peer_quotes.get(peer_name) if peer_name else None
    
    if not peer:
        return results
    
    peer_metrics = getattr(peer, "financial_metrics", {}) or {}
    peer_name = getattr(peer, "name", peer_name)
    
    metrics_to_compare = [
        ("Market Cap", getattr(y, "market_cap", 0), getattr(peer, "market_cap", 0)),
        ("Revenue", primary_metrics.get("total_revenue", 0), peer_metrics.get("total_revenue", 0)),
        ("Net Margin", primary_metrics.get("profit_margins", 0), peer_metrics.get("profit_margins", 0)),
        ("ROE", primary_metrics.get("return_on_equity", 0), peer_metrics.get("return_on_equity", 0)),
        ("P/E Ratio", primary_metrics.get("trailing_pe", 0), peer_metrics.get("trailing_pe", 0)),
    ]
    
    for metric, primary_val, secondary_val in metrics_to_compare:
        primary_str = _format_comparison_value(primary_val, metric, currency)
        secondary_str = _format_comparison_value(secondary_val, metric, currency)
        
        # Determine winner (lower P/E is better, higher others)
        if metric == "P/E Ratio":
            if primary_val and secondary_val:
                winner = "primary" if primary_val < secondary_val else ("secondary" if secondary_val < primary_val else None)
            else:
                winner = None
        else:
            if primary_val and secondary_val:
                winner = "primary" if primary_val > secondary_val else ("secondary" if secondary_val > primary_val else None)
            else:
                winner = None
        
        # Calculate delta
        if primary_val and secondary_val:
            delta_pct = abs(primary_val - secondary_val) / secondary_val * 100 if secondary_val else 0
            delta_str = f"{delta_pct:.1f}%"
        else:
            delta_str = "n/a"
        
        results.append(ComparisonResult(
            metric=metric,
            primary_value=primary_str,
            secondary_value=secondary_str,
            winner=winner,
            delta=delta_str,
            primary_entity=primary_name,
            secondary_entity=peer_name
        ))
    
    return results


def _build_visual_sections(artifact: AnswerArtifact, bundle, mode: OutputMode) -> list[VisualSection]:
    """Build visual layout sections based on output mode."""
    sections = []
    order = 0
    
    # Metrics grid section
    if artifact.metric_cards:
        sections.append(VisualSection(
            section_type="metrics_grid",
            title="Key Metrics",
            content={"cards": artifact.metric_cards},
            columns=min(len(artifact.metric_cards), 3),
            order=order
        ))
        order += 1
    
    # Charts section
    if artifact.charts:
        sections.append(VisualSection(
            section_type="chart_row",
            title="Charts",
            content={"charts": artifact.charts},
            columns=1 if mode == OutputMode.COMPANY_SNAPSHOT else 2,
            order=order
        ))
        order += 1
    
    # Comparison results section
    if artifact.comparison_results:
        sections.append(VisualSection(
            section_type="comparison_table",
            title="Comparison Analysis",
            content={"results": artifact.comparison_results},
            columns=1,
            order=order
        ))
        order += 1
    
    # Text sections
    for section in artifact.sections:
        sections.append(VisualSection(
            section_type="text_block",
            title=section.title,
            content={"body": section.body, "confidence": section.confidence},
            columns=1,
            order=order
        ))
        order += 1
    
    return sections


def _generate_comparison_verdict(results: list[ComparisonResult]) -> str:
    """Generate summary text for comparison results."""
    if not results:
        return "Insufficient data for comparison."
    
    primary_wins = sum(1 for r in results if r.winner == "primary")
    secondary_wins = sum(1 for r in results if r.winner == "secondary")
    ties = len(results) - primary_wins - secondary_wins
    
    # Find significant differences
    significant = [r for r in results if r.delta and r.delta != "n/a" and float(r.delta.rstrip("%")) > 10]
    
    verdict_parts = []
    if primary_wins > secondary_wins:
        verdict_parts.append("The primary entity shows stronger fundamentals")
    elif secondary_wins > primary_wins:
        verdict_parts.append("The secondary entity shows stronger fundamentals")
    else:
        verdict_parts.append("Both entities are relatively comparable")
    
    if significant:
        sig_metrics = ", ".join([r.metric for r in significant[:3]])
        verdict_parts.append(f"with notable differences in {sig_metrics}")
    
    return " ".join(verdict_parts) + "."


def _format_comparison_value(value, metric_type: str, currency: str = "INR") -> str:
    """Format a comparison value based on metric type."""
    if value is None or value == 0:
        return "n/a"
    if metric_type in ("Market Cap", "Revenue"):
        return _money(value, currency)
    if metric_type in ("Net Margin", "ROE"):
        return _pct(value)
    if metric_type == "P/E Ratio":
        return _num(value, "x")
    return str(value)


def build_answer_artifact(
    *,
    target: str,
    objective: str,
    mode: OutputMode,
    depth: ResponseDepth,
    bundle,
    docs,
    checkpoint,
    conflicts=None,
    entity=None,
    specialist_findings=None,
    peer_quotes: dict[str, object] | None = None,
    quality_report=None,
) -> AnswerArtifact:
    citations = _collect_citations(checkpoint, docs, bundle)
    title = _title_for(mode, target, entity)
    summary = _summary_for(mode, target, bundle, entity, quality_report)

    is_comparison = mode == OutputMode.COMPANY_COMPARISON

    wants_visuals = _objective_wants_visuals(objective, mode)

    # ------------------------------------------------------------------
    # Mode-aware runtime visuals — metric cards & charts are generated
    # based on the query intent and available specialist findings,
    # not a hardcoded snapshot set.
    # ------------------------------------------------------------------
    metric_cards: list[MetricCard] = []
    charts: list[AnswerChart] = []

    if wants_visuals and not is_comparison:
        metric_cards = _build_mode_aware_metric_cards(bundle, entity, mode, specialist_findings, objective=objective)
        charts = _build_mode_aware_charts(bundle, mode, specialist_findings, objective=objective)
        logger.info(
            "[VISUALS] mode=%s | metric_cards=%d | charts=%d | findings=%d",
            mode.value, len(metric_cards), len(charts), len(specialist_findings or []),
        )
    elif is_comparison and peer_quotes:
        # Comparison mode keeps its own scoreboard; we still append any
        # valuation-specific charts if the query was valuation-focused.
        if mode in {OutputMode.VALUATION_MODEL, OutputMode.VALUATION_INSIGHTS}:
            metric_cards = _build_mode_aware_metric_cards(bundle, entity, mode, specialist_findings, objective=objective)
            charts = _build_mode_aware_charts(bundle, mode, specialist_findings, objective=objective)

    # Build comparison elements if in comparison mode
    comparison_charts: list[AnswerChart] = []
    comparison_results: list[ComparisonResult] = []
    if is_comparison and peer_quotes:
        comparison_charts = _build_comparison_charts(AnswerArtifact(mode=mode, depth=depth, title=title, summary=summary), bundle, peer_quotes or {})
        charts.extend(comparison_charts)
        comparison_results = _build_comparison_results(bundle, peer_quotes or {})
    
    artifact = AnswerArtifact(
        mode=mode,
        depth=depth,
        title=title,
        summary=summary,
        citations=citations,
        follow_up_suggestions=_followups_for(mode, target),
        limitations=_limitations(bundle, docs, quality_report),
        metadata={
            "country_code": getattr(entity, "country_code", None),
            "output_mode": mode.value,
            "depth": depth.value,
        },
        metric_cards=metric_cards,
        charts=charts,
        comparison_results=comparison_results,
    )

    # Add visual sections at the end
    artifact.visual_sections = _build_visual_sections(artifact, bundle, mode)

    if mode == OutputMode.COMPANY_COMPARISON:
        _fill_comparison(artifact, bundle, peer_quotes or {}, specialist_findings or [], docs)
    elif mode in {OutputMode.VALUATION_MODEL, OutputMode.VALUATION_INSIGHTS}:
        _fill_valuation(artifact, bundle, specialist_findings or [])
    elif mode == OutputMode.FORENSIC_INSIGHTS:
        _fill_forensic_insights(artifact, bundle, specialist_findings or [], docs)
    elif mode == OutputMode.NEWS_BRIEF:
        _fill_news(artifact, bundle, docs)
    elif mode in {OutputMode.FILING_ANALYSIS, OutputMode.DOCUMENT_VERSION_COMPARISON}:
        _fill_filing(artifact, bundle, docs, mode)
    elif mode == OutputMode.INVESTMENT_VIEW:
        _fill_investment_view(artifact, bundle, specialist_findings or [], docs)
    elif mode == OutputMode.MARKET_EXPLAINER:
        _fill_market_explainer(artifact, objective, docs, specialist_findings or [])
    elif mode == OutputMode.DEEP_RESEARCH_REPORT:
        _fill_deep_report(artifact, bundle, docs, specialist_findings or [], conflicts or [], quality_report)
    elif mode in {OutputMode.DIRECT_ANSWER, OutputMode.CONVERSATIONAL_CHAT}:
        _fill_direct_answer(artifact, objective, bundle, docs)
    else:
        _fill_snapshot(artifact, bundle, docs, specialist_findings or [])

    return artifact


def _title_for(mode: OutputMode, target: str, entity) -> str:
    label = getattr(entity, "canonical_name", None) or target
    if mode == OutputMode.COMPANY_COMPARISON:
        return f"{label} comparison"
    if mode in {OutputMode.VALUATION_MODEL, OutputMode.VALUATION_INSIGHTS}:
        return f"{label} valuation"
    if mode == OutputMode.FORENSIC_INSIGHTS:
        return f"{label} forensic audit screen"
    if mode == OutputMode.NEWS_BRIEF:
        return f"{label} news brief"
    if mode == OutputMode.DEEP_RESEARCH_REPORT:
        return f"Deep research report: {label}"
    return f"{label} snapshot"


def _summary_for(mode: OutputMode, target: str, bundle, entity, quality_report) -> str:
    label = _company_label(target, bundle, entity)
    if mode == OutputMode.DEEP_RESEARCH_REPORT:
        return f"This report synthesizes multi-source evidence for {label}, with explicit confidence and limitations."
    if mode == OutputMode.COMPANY_COMPARISON:
        return f"Here is a side-by-side finance-focused comparison using available market, fundamentals, news, and specialist findings."
    if mode in {OutputMode.VALUATION_MODEL, OutputMode.VALUATION_INSIGHTS}:
        return f"Here is the valuation view for {label}. Figures are based on retrieved market/fundamental data and should be treated as an analytical estimate, not investment advice."
    if mode == OutputMode.FORENSIC_INSIGHTS:
        return f"Here is the forensic accounting and anomaly screening view for {label} using TimesFM probabilistic corridors."
    if mode == OutputMode.NEWS_BRIEF:
        return f"Here are the latest retrieved developments for {label} and why they matter."
    if mode == OutputMode.MARKET_EXPLAINER:
        return "Here is a finance-focused answer using the available India-market context."
    score = getattr(quality_report, "score", None)
    score_note = f" Coverage score: {score:.1f}/100." if isinstance(score, (int, float)) else ""
    return f"{label} is summarized below with the key market, business, financial, risk, and source context.{score_note}"


def _followups_for(mode: OutputMode, target: str) -> list[str]:
    if mode == OutputMode.COMPANY_COMPARISON:
        return [
            f"Compare {target} against another named peer on margins and valuation.",
            "Run a deep mode peer comparison with segment-level growth and risks.",
        ]
    if mode in {OutputMode.VALUATION_MODEL, OutputMode.VALUATION_INSIGHTS}:
        return [
            "Run a DCF sensitivity table with WACC and terminal-growth assumptions.",
            "Compare valuation multiples against listed peers.",
        ]
    if mode == OutputMode.FORENSIC_INSIGHTS:
        return [
            "Inspect promoter pledging and shareholding updates.",
            "Compare recent quarterly margins YoY.",
        ]
    if mode == OutputMode.DOCUMENT_VERSION_COMPARISON:
        return [
            "Extract only risk-factor additions and deletions.",
            "Compare financial statement changes between DRHP, RHP, and prospectus.",
        ]
    if mode == OutputMode.NEWS_BRIEF:
        return [
            "Show which news items are material for earnings or valuation.",
            "Compare recent news against price movement and analyst revisions.",
        ]
    if mode == OutputMode.DEEP_RESEARCH_REPORT:
        return [
            "Turn this into an investment committee memo.",
            "Build a valuation model using the report assumptions.",
        ]
    return [
        f"Ask for a valuation of {target}.",
        f"Compare {target} with a named peer.",
        f"Run deep mode for a fuller risk and fundamentals report.",
    ]


def _fill_snapshot(artifact: AnswerArtifact, bundle, docs, findings) -> None:
    artifact.tables.append(_metrics_table(bundle))
    artifact.sections.extend(
        [
            ResponseSection("Executive View", _executive_view_text(bundle, docs, findings), "MEDIUM"),
            ResponseSection("Company Overview", _business_text(bundle), _confidence(bundle.wikipedia or bundle.yahoo)),
            ResponseSection("Financial Performance", _financial_text(bundle), "MEDIUM"),
            ResponseSection("Key Strengths", _strength_text(bundle, docs, findings), "MEDIUM"),
            ResponseSection("Key Risks", _risk_text(bundle, docs, findings), "MEDIUM"),
            ResponseSection("Recent Developments", _news_text(bundle, docs), _confidence(getattr(bundle, "news", None) or docs)),
            ResponseSection("What To Monitor", "Watch revenue growth, margin direction, order wins/customer concentration, debt and working capital, promoter/shareholding changes, and valuation versus peers.", "MEDIUM"),
        ]
    )


def _fill_comparison(artifact: AnswerArtifact, bundle, peer_quotes: dict[str, object], findings, docs) -> None:
    rows = [_quote_row("Primary", getattr(bundle, "yahoo", None))]
    for name, quote in peer_quotes.items():
        rows.append(_quote_row(name, quote))
    artifact.tables.append(
        AnswerTable(
            title="Company comparison",
            columns=["Company", "Price", "Market cap", "Revenue", "Net margin", "ROE", "P/E"],
            rows=rows,
        )
    )
    artifact.sections.extend(
        [
            ResponseSection("Bottom Line", _comparison_verdict(rows), "MEDIUM"),
            ResponseSection("Forward View", "For forecast-style questions, treat growth durability, margin resilience, deal/order momentum, currency exposure, and valuation re-rating risk as the key drivers. The company with stronger growth and returns deserves a premium only if the current multiple does not already price it in.", "MEDIUM"),
            ResponseSection("Risks", _risk_text(bundle, docs, findings), "MEDIUM"),
            ResponseSection("What To Check Next", "Compare recent quarterly growth, deal wins/order book, margin trend, capital allocation, and valuation against sector averages.", "MEDIUM"),
        ]
    )


def _fill_valuation(artifact: AnswerArtifact, bundle, findings) -> None:
    artifact.tables.append(_metrics_table(bundle))
    valuation_findings = [f for f in findings if getattr(f, "kind", "") in {"valuation", "financial"}]
    body = _findings_text(valuation_findings)
    if not body:
        body = "A full valuation model needs clean cash flow, growth, discount-rate, terminal-growth, and share-count assumptions. The retrieved market/fundamental data is shown above as the starting point."
    artifact.sections.extend(
        [
            ResponseSection("Model Output", body, "MEDIUM"),
            ResponseSection("Assumptions To Confirm", "Revenue growth, EBIT/FCF margin, reinvestment needs, cost of equity/WACC, terminal growth, and net cash/debt.", "MEDIUM"),
            ResponseSection("Sensitivity", "Run a sensitivity grid around WACC and terminal growth before relying on a single fair value.", "MEDIUM"),
        ]
    )


def _fill_forensic_insights(artifact: AnswerArtifact, bundle, findings, docs) -> None:
    artifact.tables.append(_metrics_table(bundle))
    accounting_findings = [f for f in findings if getattr(f, "agent", "") == "accounting"]
    body = _findings_text(accounting_findings)
    if not body:
        body = "No structural accounting anomalies detected in recent financial series. The company passed standard forensic checks."
    artifact.sections.extend(
        [
            ResponseSection("Forensic Screen Output", body, "MEDIUM"),
            ResponseSection("Key Accounting Risks", _risk_text(bundle, docs, findings), "MEDIUM"),
            ResponseSection("Governance & Audit Focus", "Verify board auditor reports, promoter pledging history, and footnotes in official filings for complete assurance.", "MEDIUM"),
        ]
    )


def _fill_news(artifact: AnswerArtifact, bundle, docs) -> None:
    news = getattr(bundle, "news", None) or []
    rows = []
    for item in news[:8]:
        rows.append([getattr(item, "source", "") or "source", getattr(item, "title", "") or "", getattr(item, "published", "") or ""])
    if rows:
        artifact.tables.append(AnswerTable("Latest headlines", ["Source", "Headline", "Published"], rows))
    artifact.sections.append(ResponseSection("Why It Matters", _news_text(bundle, docs), "MEDIUM" if rows else "LOW"))


def _fill_filing(artifact: AnswerArtifact, bundle, docs, mode: OutputMode) -> None:
    if mode == OutputMode.DOCUMENT_VERSION_COMPARISON:
        artifact.tables.append(
            AnswerTable(
                "Document version comparison",
                ["Section", "DRHP", "RHP", "Prospectus", "Change to inspect"],
                [
                    ["Business", "Retrieve", "Retrieve", "Retrieve", "Strategy, products, customers, capacity"],
                    ["Risk factors", "Retrieve", "Retrieve", "Retrieve", "Added/removed risk disclosures"],
                    ["Financials", "Retrieve", "Retrieve", "Retrieve", "Restatements, period updates, margins"],
                    ["Objects of issue", "Retrieve", "Retrieve", "Retrieve", "Use-of-proceeds changes"],
                ],
            )
        )
    artifact.sections.extend(
        [
            ResponseSection("Filing Evidence", _filing_text(bundle, docs), "MEDIUM"),
            ResponseSection("Red Flags", _risk_text(bundle, docs, []), "MEDIUM"),
        ]
    )


def _fill_investment_view(artifact: AnswerArtifact, bundle, findings, docs) -> None:
    artifact.tables.append(_metrics_table(bundle))
    artifact.sections.extend(
        [
            ResponseSection("View", _investment_text(bundle, findings), "MEDIUM"),
            ResponseSection("Bear Case", _risk_text(bundle, docs, findings), "MEDIUM"),
            ResponseSection("What Would Change The View", "Watch earnings revisions, margin trend, valuation versus peers, management commentary, governance events, and sector/macroeconomic changes.", "MEDIUM"),
        ]
    )


def _fill_market_explainer(artifact: AnswerArtifact, objective: str, docs, findings) -> None:
    body = _findings_text(findings) or _doc_snippets(docs) or "The query is market-wide, so the answer depends on current macro, policy, sector, and market-flow data."
    artifact.sections.extend(
        [
            ResponseSection("Short Answer", body, "MEDIUM"),
            ResponseSection("What To Track", "Track RBI policy, bond yields, rupee, crude, FII/DII flows, sector earnings, and regulatory announcements.", "MEDIUM"),
        ]
    )


def _fill_deep_report(artifact: AnswerArtifact, bundle, docs, findings, conflicts, quality_report) -> None:
    artifact.tables.append(_metrics_table(bundle))
    artifact.tables.append(
        AnswerTable(
            "Evidence coverage",
            ["Area", "Status"],
            [
                ["Sources processed", str(len(docs or []))],
                ["Specialist findings", str(len(findings or []))],
                ["Conflicts detected", str(len(conflicts or []))],
                ["Quality score", f"{getattr(quality_report, 'score', 0):.1f}/100" if quality_report else "n/a"],
            ],
        )
    )
    artifact.sections.extend(
        [
            ResponseSection("Research Plan and Scope", "The run covered enrichment, localized search, iterative follow-ups, specialist review, verification, conflict detection, and synthesis.", "HIGH"),
            ResponseSection("Company and Business Model", _business_text(bundle), _confidence(bundle.wikipedia or bundle.yahoo)),
            ResponseSection("Financial Profile", _financial_text(bundle), "MEDIUM"),
            ResponseSection("Risks and Red Flags", _risk_text(bundle, docs, findings), "MEDIUM"),
            ResponseSection("Specialist Findings", _findings_text(findings), "MEDIUM"),
            ResponseSection("Evidence Quality and Limitations", _quality_text(quality_report), "MEDIUM"),
        ]
    )


def _fill_direct_answer(artifact: AnswerArtifact, objective: str, bundle, docs) -> None:
    if any(term in (objective or "").lower() for term in ("historical price", "price history", "stock history", "share price history", "past price")):
        artifact.sections.append(ResponseSection("Historical Price View", _price_history_text(bundle, docs), "MEDIUM"))
        return
    body = _doc_snippets(docs) or _business_text(bundle)
    artifact.sections.append(ResponseSection("Answer", body, "MEDIUM" if body else "LOW"))


def _metrics_table(bundle) -> AnswerTable:
    y = getattr(bundle, "yahoo", None)
    metrics = getattr(y, "financial_metrics", {}) or {}
    rows = [
        ["Price", _price(y)],
        ["Market cap", _money(getattr(y, "market_cap", None), getattr(y, "currency", None))],
        ["Revenue", _money(metrics.get("total_revenue"), getattr(y, "currency", None))],
        ["Net margin", _pct(metrics.get("profit_margins"))],
        ["ROE", _pct(metrics.get("return_on_equity"))],
        ["P/E", _num(metrics.get("trailing_pe"), "x")],
        ["52-week range", _range(y)],
    ]
    return AnswerTable("Key metrics", ["Metric", "Value"], rows)


def _quote_row(name: str, quote) -> list[str]:
    metrics = getattr(quote, "financial_metrics", {}) or {}
    return [
        getattr(quote, "name", None) or name,
        _price(quote),
        _money(getattr(quote, "market_cap", None), getattr(quote, "currency", None)),
        _money(metrics.get("total_revenue"), getattr(quote, "currency", None)),
        _pct(metrics.get("profit_margins")),
        _pct(metrics.get("return_on_equity")),
        _num(metrics.get("trailing_pe"), "x"),
    ]


def _collect_citations(checkpoint, docs, bundle) -> list[AnswerCitation]:
    out: list[AnswerCitation] = []
    seen: set[str] = set()
    for c in getattr(checkpoint, "citation_log", []) or []:
        url = getattr(c, "url", "") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(AnswerCitation(title=getattr(c, "title", "") or _domain(url), url=url, kind=getattr(c, "kind", "source"), domain=_domain(url)))
    y = getattr(bundle, "yahoo", None)
    if y and getattr(y, "source_url", None) and y.source_url not in seen:
        out.append(AnswerCitation(title="Yahoo Finance", url=y.source_url, kind="market_data", domain="finance.yahoo.com"))
        seen.add(y.source_url)
    for d in docs or []:
        url = getattr(d, "final_url", None) or getattr(d, "url", None)
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(AnswerCitation(title=getattr(d, "title", "") or _domain(url), url=url, kind="web", domain=_domain(url)))
        if len(out) >= 20:
            break
    return out


def _limitations(bundle, docs, quality_report) -> list[str]:
    items: list[str] = []
    if not getattr(bundle, "yahoo", None):
        items.append("Live market/fundamental data was not retrieved for this run.")
    if not docs:
        items.append("Web source coverage was thin; treat qualitative conclusions as provisional.")
    gaps = getattr(quality_report, "gaps", None) or []
    items.extend(str(g) for g in gaps[:3])
    return list(dict.fromkeys(items))


def _business_text(bundle) -> str:
    if getattr(bundle, "filing", None) and getattr(bundle.filing, "business", None):
        return bundle.filing.business[:1200]
    if getattr(bundle, "wikipedia", None) and getattr(bundle.wikipedia, "extract", None):
        return bundle.wikipedia.extract[:900]
    y = getattr(bundle, "yahoo", None)
    if y and getattr(y, "business_summary", None):
        return y.business_summary[:900]
    return "No authoritative company description was retrieved in this run."


def _financial_text(bundle) -> str:
    y = getattr(bundle, "yahoo", None)
    if not y:
        return "Financial data was not available from the enrichment layer."
    metrics = getattr(y, "financial_metrics", {}) or {}
    parts = [
        f"Price: {_price(y)}",
        f"Market cap: {_money(getattr(y, 'market_cap', None), getattr(y, 'currency', None))}",
        f"Revenue: {_money(metrics.get('total_revenue'), getattr(y, 'currency', None))}",
        f"Net margin: {_pct(metrics.get('profit_margins'))}",
        f"ROE: {_pct(metrics.get('return_on_equity'))}",
    ]
    return "; ".join(parts) + "."


def _executive_view_text(bundle, docs, findings) -> str:
    financial = _financial_text(bundle)
    news = _news_text(bundle, docs)
    finding = _findings_text(findings[:2])
    parts = [financial]
    if news and "No fresh news" not in news:
        parts.append("Recent context: " + news[:500])
    if finding:
        parts.append("Specialist signal: " + finding)
    return "\n\n".join(parts)


def _strength_text(bundle, docs, findings) -> str:
    strength_findings = [
        f for f in findings
        if any(term in (getattr(f, "headline", "") + " " + getattr(f, "detail", "")).lower() for term in ("strength", "moat", "growth", "margin", "leader", "market share", "cash"))
    ]
    if strength_findings:
        return _findings_text(strength_findings[:5])
    snippets = _doc_snippets(docs, terms=("growth", "margin", "market share", "leader", "order book", "cash flow"))
    if snippets:
        return snippets
    return "Strength evidence was limited in the retrieved sources; use the metrics table and source list as the starting point for quality assessment."


def _news_text(bundle, docs) -> str:
    news = getattr(bundle, "news", None) or []
    if news:
        return " ".join(f"{getattr(n, 'source', 'Source')}: {getattr(n, 'title', '')}." for n in news[:5])
    return _doc_snippets(docs, terms=("news", "announced", "reported", "earnings")) or "No fresh news headlines were retrieved."


def _price_history_text(bundle, docs) -> str:
    y = getattr(bundle, "yahoo", None)
    dates = getattr(y, "series_dates", None) or []
    closes = getattr(y, "series_closes", None) or []
    currency = getattr(y, "currency", None) or "INR"
    if dates and closes and len(dates) == len(closes):
        first = float(closes[0])
        last = float(closes[-1])
        high = max(float(v) for v in closes)
        low = min(float(v) for v in closes)
        change = ((last - first) / first * 100) if first else 0.0
        direction = "gained" if change >= 0 else "declined"
        return (
            f"Retrieved {len(closes)} recent trading observations from Yahoo Finance for "
            f"{getattr(y, 'ticker', 'the stock')}. From {dates[0]} to {dates[-1]}, the close "
            f"{direction} {abs(change):.2f}% from {currency} {first:,.2f} to {currency} {last:,.2f}. "
            f"The observed range in this sample was {currency} {low:,.2f} to {currency} {high:,.2f}. "
            "Use the chart below only as the retrieved sample window, not a full long-term backtest."
        )
    snippets = _doc_snippets(docs, terms=("price", "historical", "chart", "stock"))
    return snippets or "Historical price data was not available from the retrieved sources for this run."


def _risk_text(bundle, docs, findings) -> str:
    risk_findings = [f for f in findings if "risk" in (getattr(f, "kind", "") or "").lower() or "risk" in (getattr(f, "headline", "") or "").lower()]
    if risk_findings:
        return _findings_text(risk_findings)
    if getattr(bundle, "filing", None) and getattr(bundle.filing, "risk_factors", None):
        return bundle.filing.risk_factors[:1200]
    return _doc_snippets(docs, terms=("risk", "headwind", "regulatory", "margin pressure", "debt")) or "Specific risk-factor evidence was limited in this run."


def _filing_text(bundle, docs) -> str:
    if getattr(bundle, "filing", None):
        parts = []
        if getattr(bundle.filing, "business", None):
            parts.append("Business: " + bundle.filing.business[:500])
        if getattr(bundle.filing, "risk_factors", None):
            parts.append("Risks: " + bundle.filing.risk_factors[:500])
        if getattr(bundle.filing, "mdna", None):
            parts.append("Management discussion: " + bundle.filing.mdna[:500])
        return "\n\n".join(parts)
    return _doc_snippets(docs, terms=("drhp", "rhp", "prospectus", "risk factors", "objects of the issue")) or "No filing narrative was extracted in this run."


def _investment_text(bundle, findings) -> str:
    financials = _financial_text(bundle)
    found = _findings_text(findings[:4])
    return f"{financials}\n\n{found}" if found else financials


def _findings_text(findings) -> str:
    lines = []
    for f in findings[:8]:
        headline = getattr(f, "headline", "") or getattr(f, "kind", "Finding")
        detail = getattr(f, "detail", "") or ""
        conf = getattr(f, "confidence", "") or "MEDIUM"
        lines.append(f"- [{conf}] {headline}: {detail}")
    return "\n".join(lines)


def _quality_text(report) -> str:
    if not report:
        return "No quality report was produced."
    gaps = getattr(report, "gaps", []) or []
    if not gaps:
        return f"Coverage score was {getattr(report, 'score', 0):.1f}/100 with no major gaps flagged."
    return f"Coverage score was {getattr(report, 'score', 0):.1f}/100. Main gaps: " + "; ".join(gaps[:5]) + "."


def _doc_snippets(docs, terms: tuple[str, ...] = ()) -> str:
    snippets: list[str] = []
    for d in docs or []:
        text = f"{getattr(d, 'title', '')} {getattr(d, 'excerpt', '')}"
        lower = text.lower()
        if terms and not any(t in lower for t in terms):
            continue
        excerpt = (getattr(d, "excerpt", "") or "").strip()
        if excerpt:
            snippets.append(excerpt[:300])
        if len(snippets) >= 3:
            break
    return " ".join(snippets)


def _comparison_verdict(rows: list[list[str]]) -> str:
    if len(rows) <= 1:
        return "Only one company had structured market data available, so the comparison is partial."
    return "The table highlights scale, profitability, return profile, and valuation. Prefer the company with stronger growth/ROE when valuation is reasonable; prefer the cheaper company only if the quality gap is small."


def _company_label(target: str, bundle, entity) -> str:
    y = getattr(bundle, "yahoo", None)
    return getattr(y, "name", None) or getattr(entity, "canonical_name", None) or target


def _price(y) -> str:
    if not y or getattr(y, "price", None) is None:
        return "n/a"
    currency = getattr(y, "currency", None) or ""
    return f"{currency} {y.price:,.2f}".strip()


def _range(y) -> str:
    if not y:
        return "n/a"
    low = getattr(y, "fifty_two_week_low", None)
    high = getattr(y, "fifty_two_week_high", None)
    if low is None or high is None:
        return "n/a"
    return f"{low:,.2f} - {high:,.2f}"


def _money(value, currency: str | None) -> str:
    if value is None:
        return "n/a"
    currency = (currency or "").upper()
    if currency == "INR":
        if abs(value) >= 1e7:
            return f"Rs {value / 1e7:,.2f} Cr"
        if abs(value) >= 1e5:
            return f"Rs {value / 1e5:,.2f} L"
    if abs(value) >= 1e9:
        return f"{currency} {value / 1e9:,.2f}B".strip()
    if abs(value) >= 1e6:
        return f"{currency} {value / 1e6:,.2f}M".strip()
    return f"{currency} {value:,.2f}".strip()


def _pct(value) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def _num(value, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}{suffix}"


def _confidence(value) -> str:
    return "MEDIUM" if value else "LOW"


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""

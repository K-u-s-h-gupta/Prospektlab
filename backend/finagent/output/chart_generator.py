from __future__ import annotations

import base64
import io
from typing import Any

# Lazy matplotlib import — do not pull it at module load time.
# This allows the gateway to start even if matplotlib is not installed.
_matplotlib = None
_plt = None
_np = None


def _ensure_matplotlib():
    """Import matplotlib on first use. Raises a clear error if unavailable."""
    global _matplotlib, _plt, _np
    if _matplotlib is None:
        try:
            import matplotlib
            import matplotlib.pyplot as plt
            import numpy as np
            matplotlib.use("Agg")
            _matplotlib = matplotlib
            _plt = plt
            _np = np

            # Apply our financial chart style on first load
            plt.rcParams.update(CHART_STYLE)
        except ImportError as e:
            raise ImportError(
                "matplotlib is required for chart generation. "
                "Install it with: pip install matplotlib numpy"
            ) from e
    return _matplotlib, _plt, _np

# Financial color scheme
COLORS = {
    "primary": "#10B981",  # Green for positive/growth
    "secondary": "#3B82F6",  # Blue for neutral/primary data
    "negative": "#EF4444",  # Red for negative/decline
    "accent": "#8B5CF6",  # Purple for highlights
    "partial": "#F59E0B",  # Amber for partial data warning
    "text": "#1F2937",  # Dark gray for text
    "grid": "#E5E7EB",  # Light gray for grid lines
    "background": "#FFFFFF",  # White background
}

# Style configuration
CHART_STYLE = {
    "figure.facecolor": COLORS["background"],
    "axes.facecolor": COLORS["background"],
    "axes.edgecolor": COLORS["grid"],
    "axes.labelcolor": COLORS["text"],
    "text.color": COLORS["text"],
    "xtick.color": COLORS["text"],
    "ytick.color": COLORS["text"],
    "grid.color": COLORS["grid"],
    "grid.linestyle": "-",
    "grid.linewidth": 0.5,
    "axes.grid": True,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "font.size": 10,
    "axes.titlesize": 12,
    "axes.labelsize": 10,
}

# Style is applied lazily inside _ensure_matplotlib() when first needed.


def _format_currency(value: float | None, currency: str = "INR") -> str:
    """Format currency value with INR units (Crores, Lakhs).

    Args:
        value: The numeric value to format
        currency: Currency code, defaults to INR

    Returns:
        Formatted currency string
    """
    if value is None:
        return "N/A"

    currency = currency.upper()

    if currency == "INR":
        if abs(value) >= 1e7:
            return f"₹{value / 1e7:,.1f} Cr"
        if abs(value) >= 1e5:
            return f"₹{value / 1e5:,.1f} L"
        return f"₹{value:,.0f}"

    # Generic formatting for other currencies
    if abs(value) >= 1e9:
        return f"{currency} {value / 1e9:,.1f}B"
    if abs(value) >= 1e6:
        return f"{currency} {value / 1e6:,.1f}M"
    if abs(value) >= 1e3:
        return f"{currency} {value / 1e3:,.1f}K"
    return f"{currency} {value:,.0f}"


def _format_price(value: float | None, decimals: int = 2) -> str:
    """Format price value.

    Args:
        value: The price value
        decimals: Number of decimal places

    Returns:
        Formatted price string
    """
    if value is None:
        return "N/A"
    return f"₹{value:,.{decimals}f}"


def _save_figure_both_formats(fig: Any, dpi: int = 100) -> dict[str, str]:
    """Save matplotlib figure to both SVG and PNG as base64-encoded strings.

    Args:
        fig: The matplotlib figure to save
        dpi: DPI for PNG rendering

    Returns:
        Dictionary with 'svg' and 'png' keys containing base64 strings
    """
    # Save to SVG
    svg_buffer = io.BytesIO()
    fig.savefig(svg_buffer, format="svg", bbox_inches="tight", facecolor=COLORS["background"])
    svg_buffer.seek(0)
    svg_base64 = base64.b64encode(svg_buffer.read()).decode("utf-8")
    svg_buffer.close()

    # Save to PNG
    png_buffer = io.BytesIO()
    fig.savefig(png_buffer, format="png", dpi=dpi, bbox_inches="tight", facecolor=COLORS["background"])
    png_buffer.seek(0)
    png_base64 = base64.b64encode(png_buffer.read()).decode("utf-8")
    png_buffer.close()

    return {"svg": svg_base64, "png": png_base64}


def _add_partial_data_indicator(ax: Any, message: str = "Partial Data") -> None:
    """Add a partial data indicator badge to the chart.

    Args:
        ax: The matplotlib axes to add the indicator to
        message: The message to display in the badge
    """
    ax.text(
        0.98,
        0.98,
        message,
        transform=ax.transAxes,
        fontsize=8,
        color=COLORS["partial"],
        ha="right",
        va="top",
        bbox=dict(
            boxstyle="round,pad=0.3",
            facecolor=COLORS["background"],
            edgecolor=COLORS["partial"],
            linewidth=1,
        ),
    )


def generate_price_chart(
    dates: list[str],
    prices: list[float],
    title: str = "Stock Price",
    is_partial: bool = False,
) -> dict[str, str] | None:
    """Generate a stock price line chart.

    Args:
        dates: List of date labels
        prices: List of price values
        title: Chart title
        is_partial: Whether to show partial data indicator

    Returns:
        Dictionary with 'svg' and 'png' base64 strings, or None if input invalid
    """
    if not dates or not prices or len(dates) != len(prices):
        return None

    _, plt, np = _ensure_matplotlib()
    fig, ax = plt.subplots(figsize=(10, 5))

    # Calculate trend for color
    start_price = prices[0]
    end_price = prices[-1]
    is_positive = end_price >= start_price
    line_color = COLORS["primary"] if is_positive else COLORS["negative"]

    # Plot line
    ax.plot(
        range(len(prices)),
        prices,
        color=line_color,
        linewidth=2,
        marker="o",
        markersize=4,
        markerfacecolor=line_color,
        markeredgecolor="white",
        markeredgewidth=0.5,
    )

    # Fill area under line
    ax.fill_between(range(len(prices)), prices, alpha=0.1, color=line_color)

    # Set labels
    ax.set_title(title, fontweight="bold", pad=15)
    ax.set_xlabel("Date")
    ax.set_ylabel("Price (₹)")

    # Set x-ticks
    if len(dates) > 10:
        step = len(dates) // 10
        tick_indices = list(range(0, len(dates), step))
        ax.set_xticks(tick_indices)
        ax.set_xticklabels([dates[i] for i in tick_indices], rotation=45, ha="right")
    else:
        ax.set_xticks(range(len(dates)))
        ax.set_xticklabels(dates, rotation=45, ha="right")

    # Format y-axis as currency
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"₹{x:,.0f}"))

    # Add grid
    ax.grid(True, alpha=0.3)

    # Add partial data indicator if needed
    if is_partial:
        _add_partial_data_indicator(ax)

    plt.tight_layout()
    result = _save_figure_both_formats(fig)
    plt.close(fig)

    return result


def generate_revenue_chart(
    labels: list[str],
    revenue: list[float],
    net_income: list[float] | None = None,
    title: str = "Financial Performance",
    currency: str = "INR",
    is_partial: bool = False,
) -> dict[str, str] | None:
    """Generate a revenue/net income bar chart.

    Args:
        labels: List of period labels (e.g., years, quarters)
        revenue: List of revenue values
        net_income: Optional list of net income values
        title: Chart title
        currency: Currency code
        is_partial: Whether to show partial data indicator

    Returns:
        Dictionary with 'svg' and 'png' base64 strings, or None if input invalid
    """
    if not labels or not revenue or len(labels) != len(revenue):
        return None

    _, plt, np = _ensure_matplotlib()
    fig, ax = plt.subplots(figsize=(10, 5))

    x = np.arange(len(labels))
    width = 0.35

    # Plot revenue bars
    bars1 = ax.bar(
        x - width / 2 if net_income else x,
        revenue,
        width,
        label="Revenue",
        color=COLORS["secondary"],
        edgecolor="white",
        linewidth=0.5,
    )

    # Plot net income bars if provided
    if net_income and len(net_income) == len(labels):
        bars2 = ax.bar(
            x + width / 2,
            net_income,
            width,
            label="Net Income",
            color=COLORS["primary"],
            edgecolor="white",
            linewidth=0.5,
        )

        # Color negative net income bars
        for bar, val in zip(bars2, net_income):
            if val < 0:
                bar.set_color(COLORS["negative"])

    # Set labels
    ax.set_title(title, fontweight="bold", pad=15)
    ax.set_xlabel("Period")
    ax.set_ylabel(f"Amount ({currency})")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")

    # Add legend if multiple series
    if net_income:
        ax.legend(loc="upper left", framealpha=0.9)

    # Add value labels on bars
    def add_labels(bars: Any, values: list[float]) -> None:
        for bar, val in zip(bars, values):
            height = bar.get_height()
            if height != 0:
                label = _format_currency(val, currency)
                ax.annotate(
                    label,
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=7,
                    rotation=90 if len(label) > 8 else 0,
                )

    if net_income:
        add_labels(bars1, revenue)
        add_labels(bars2, net_income)  # type: ignore
    else:
        add_labels(bars1, revenue)

    # Add partial data indicator if needed
    if is_partial:
        _add_partial_data_indicator(ax)

    plt.tight_layout()
    result = _save_figure_both_formats(fig)
    plt.close(fig)

    return result


def generate_comparison_chart(
    categories: list[str],
    values_a: list[float],
    values_b: list[float],
    label_a: str = "Company A",
    label_b: str = "Company B",
    title: str = "Comparison",
    currency: str = "INR",
    is_partial: bool = False,
) -> dict[str, str] | None:
    """Generate a side-by-side comparison bar chart.

    Args:
        categories: List of metric categories
        values_a: Values for company A
        values_b: Values for company B
        label_a: Label for company A
        label_b: Label for company B
        title: Chart title
        currency: Currency code for formatting
        is_partial: Whether to show partial data indicator

    Returns:
        Dictionary with 'svg' and 'png' base64 strings, or None if input invalid
    """
    if not categories or len(values_a) != len(categories) or len(values_b) != len(categories):
        return None

    _, plt, np = _ensure_matplotlib()
    fig, ax = plt.subplots(figsize=(10, 5))

    x = np.arange(len(categories))
    width = 0.35

    # Plot bars
    bars_a = ax.bar(
        x - width / 2,
        values_a,
        width,
        label=label_a,
        color=COLORS["secondary"],
        edgecolor="white",
        linewidth=0.5,
    )

    bars_b = ax.bar(
        x + width / 2,
        values_b,
        width,
        label=label_b,
        color=COLORS["accent"],
        edgecolor="white",
        linewidth=0.5,
    )

    # Set labels
    ax.set_title(title, fontweight="bold", pad=15)
    ax.set_xlabel("Metric")
    ax.set_ylabel(f"Value ({currency})")
    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=30, ha="right")
    ax.legend(loc="upper right", framealpha=0.9)

    # Add value labels
    def add_value_labels(bars: Any, values: list[float]) -> None:
        for bar, val in zip(bars, values):
            height = bar.get_height()
            if height != 0:
                label = _format_currency(val, currency)
                ax.annotate(
                    label,
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3),
                    textcoords="offset points",
                    ha="center",
                    va="bottom",
                    fontsize=7,
                )

    add_value_labels(bars_a, values_a)
    add_value_labels(bars_b, values_b)

    # Add partial data indicator if needed
    if is_partial:
        _add_partial_data_indicator(ax)

    plt.tight_layout()
    result = _save_figure_both_formats(fig)
    plt.close(fig)

    return result


def generate_sparkline(
    values: list[float],
    width: float = 3,
    height: float = 1,
    show_area: bool = True,
) -> dict[str, str] | None:
    """Generate a mini sparkline chart for metric cards.

    Args:
        values: List of numeric values
        width: Figure width in inches
        height: Figure height in inches
        show_area: Whether to fill area under the line

    Returns:
        Dictionary with 'svg' and 'png' base64 strings, or None if input invalid
    """
    if not values or len(values) < 2:
        return None

    _, plt, np = _ensure_matplotlib()
    fig, ax = plt.subplots(figsize=(width, height))

    # Calculate trend for color
    is_positive = values[-1] >= values[0]
    line_color = COLORS["primary"] if is_positive else COLORS["negative"]

    # Remove axes for sparkline look
    ax.axis("off")

    # Plot line
    ax.plot(
        range(len(values)),
        values,
        color=line_color,
        linewidth=1.5,
    )

    # Fill area
    if show_area:
        ax.fill_between(range(len(values)), values, alpha=0.2, color=line_color)

    # Remove margins
    ax.set_xlim(-0.5, len(values) - 0.5)
    ax.set_ylim(min(values) * 0.95, max(values) * 1.05)

    plt.tight_layout(pad=0)
    result = _save_figure_both_formats(fig, dpi=150)
    plt.close(fig)

    return result


def generate_multiseries_line_chart(
    dates: list[str],
    series: dict[str, list[float]],
    title: str = "Trend Comparison",
    ylabel: str = "Value",
    is_partial: bool = False,
) -> dict[str, str] | None:
    """Generate a multi-series line chart for comparing trends.

    Args:
        dates: List of date labels
        series: Dictionary mapping series names to value lists
        title: Chart title
        ylabel: Y-axis label
        is_partial: Whether to show partial data indicator

    Returns:
        Dictionary with 'svg' and 'png' base64 strings, or None if input invalid
    """
    if not dates or not series:
        return None

    # Validate series lengths
    for name, values in series.items():
        if len(values) != len(dates):
            return None

    _, plt, np = _ensure_matplotlib()
    fig, ax = plt.subplots(figsize=(10, 5))

    # Color cycle
    color_cycle = [COLORS["secondary"], COLORS["primary"], COLORS["accent"], COLORS["negative"]]

    # Plot each series
    for i, (name, values) in enumerate(series.items()):
        color = color_cycle[i % len(color_cycle)]
        ax.plot(
            range(len(dates)),
            values,
            label=name,
            color=color,
            linewidth=2,
            marker="o",
            markersize=3,
            markerfacecolor=color,
            markeredgecolor="white",
            markeredgewidth=0.5,
        )

    # Set labels
    ax.set_title(title, fontweight="bold", pad=15)
    ax.set_xlabel("Date")
    ax.set_ylabel(ylabel)

    # Set x-ticks
    if len(dates) > 10:
        step = len(dates) // 10
        tick_indices = list(range(0, len(dates), step))
        ax.set_xticks(tick_indices)
        ax.set_xticklabels([dates[i] for i in tick_indices], rotation=45, ha="right")
    else:
        ax.set_xticks(range(len(dates)))
        ax.set_xticklabels(dates, rotation=45, ha="right")

    # Add legend
    ax.legend(loc="upper left", framealpha=0.9)

    # Add partial data indicator if needed
    if is_partial:
        _add_partial_data_indicator(ax)

    plt.tight_layout()
    result = _save_figure_both_formats(fig)
    plt.close(fig)

    return result


def generate_article_visual(
    visual: dict[str, Any],
    *,
    output_path: str | None = None,
) -> dict[str, str] | None:
    """Render an article visual (kind/title/points/note) to PNG + SVG.

    Args:
        visual: Dict with keys kind, title, points (list of {label, value}), note.
        output_path: If provided, also save the PNG to this file path.

    Returns:
        Dictionary with 'svg' and 'png' base64 strings, or None if input invalid.
    """
    points = visual.get("points") or []
    if len(points) < 2:
        return None
    title = str(visual.get("title") or "Data trend")[:120]
    kind = str(visual.get("kind") or "bar").lower()
    note = str(visual.get("note") or "")

    labels = [str(p.get("label") or "")[:30] for p in points]
    values = []
    for p in points:
        try:
            values.append(float(p.get("value") or 0))
        except (ValueError, TypeError):
            values.append(0.0)

    _, plt, np = _ensure_matplotlib()
    fig, ax = plt.subplots(figsize=(10, 5))

    if kind in ("line", "trend"):
        colors = [COLORS["primary"] if v >= 0 else COLORS["negative"] for v in values]
        ax.plot(range(len(values)), values, color=COLORS["secondary"], linewidth=2,
                marker="o", markersize=5, markerfacecolor=COLORS["secondary"],
                markeredgecolor="white", markeredgewidth=0.5)
        ax.fill_between(range(len(values)), values, alpha=0.08, color=COLORS["secondary"])
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    elif kind == "horizontal_bar":
        y_pos = np.arange(len(labels))
        bar_colors = [COLORS["primary"] if v >= 0 else COLORS["negative"] for v in values]
        ax.barh(y_pos, values, color=bar_colors, edgecolor="white", linewidth=0.5, height=0.6)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels, fontsize=8)
        ax.invert_yaxis()
        for i, v in enumerate(values):
            ax.text(v + max(abs(v) * 0.02, 0.5), i, f"{v:,.1f}", va="center", fontsize=7)
    else:
        x_pos = np.arange(len(labels))
        bar_colors = [COLORS["primary"] if v >= 0 else COLORS["negative"] for v in values]
        bars = ax.bar(x_pos, values, color=bar_colors, edgecolor="white", linewidth=0.5, width=0.6)
        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
        for bar, v in zip(bars, values):
            height = bar.get_height()
            if height != 0:
                ax.annotate(f"{v:,.1f}", xy=(bar.get_x() + bar.get_width() / 2, height),
                            xytext=(0, 3), textcoords="offset points", ha="center",
                            va="bottom", fontsize=7)

    ax.set_title(title, fontweight="bold", pad=15, fontsize=11)
    ax.grid(True, alpha=0.3)

    if note:
        fig.text(0.5, -0.02, note, ha="center", fontsize=7, color="#6B7280", style="italic")

    plt.tight_layout()
    result = _save_figure_both_formats(fig, dpi=150)

    if output_path and result:
        import pathlib
        pathlib.Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        png_bytes = base64.b64decode(result["png"])
        with open(output_path, "wb") as f:
            f.write(png_bytes)

    plt.close(fig)
    return result


def generate_metric_gauge(
    value: float,
    min_value: float = 0,
    max_value: float = 100,
    title: str = "Metric",
    suffix: str = "%",
    is_partial: bool = False,
) -> dict[str, str] | None:
    """Generate a horizontal bar gauge for single metric visualization.

    Args:
        value: The metric value to display
        min_value: Minimum scale value
        max_value: Maximum scale value
        title: Chart title
        suffix: Suffix to append to value (e.g., '%', 'x')
        is_partial: Whether to show partial data indicator

    Returns:
        Dictionary with 'svg' and 'png' base64 strings, or None if input invalid
    """
    _, plt, np = _ensure_matplotlib()
    fig, ax = plt.subplots(figsize=(6, 2))

    # Normalize value
    normalized = (value - min_value) / (max_value - min_value)
    normalized = max(0, min(1, normalized))  # Clamp to 0-1

    # Choose color based on value
    if normalized >= 0.7:
        color = COLORS["primary"]
    elif normalized >= 0.4:
        color = COLORS["partial"]
    else:
        color = COLORS["negative"]

    # Background bar
    ax.barh(0, max_value - min_value, left=min_value, height=0.3, color=COLORS["grid"], alpha=0.5)

    # Value bar
    ax.barh(0, value - min_value, left=min_value, height=0.3, color=color)

    # Add value label
    ax.text(
        max_value,
        0,
        f"{value}{suffix}",
        va="center",
        ha="left",
        fontsize=12,
        fontweight="bold",
        color=COLORS["text"],
    )

    # Customize
    ax.set_xlim(min_value, max_value * 1.2)
    ax.set_ylim(-0.5, 0.5)
    ax.set_title(title, fontweight="bold", pad=10)
    ax.axis("off")

    # Add partial data indicator if needed
    if is_partial:
        _add_partial_data_indicator(ax)

    plt.tight_layout()
    result = _save_figure_both_formats(fig)
    plt.close(fig)

    return result

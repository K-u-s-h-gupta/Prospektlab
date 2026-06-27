from pathlib import Path
path = Path('backend/finagent/earnings/parser.py')
text = path.read_text(encoding='utf-8')
start = text.index('def _extract_metrics_from_labeled_section')
end = text.index('def _extract_metrics_from_text_section')
new = r'''
_SECTION_HEADER_PATTERNS: dict[str, tuple[str, ...]] = {
    "standalone": (
        r"(?:part\s*[i1]|section\s*[i1a])?[^\n]*standalone[^\n]*(?:financial\s+)?results?",
        r"standalone\s+statement\s+of\s+(?:profit|assets|financial)",
        r"standalone\s+(?:audited|unaudited)\s+financial",
        r"statement\s+of\s+standalone",
    ),
    "consolidated": (
        r"(?:part\s*[ii2]|section\s*[ii2b])?[^\n]*consolidated[^\n]*(?:financial\s+)?results?",
        r"consolidated\s+statement\s+of\s+(?:profit|assets|financial)",
        r"consolidated\s+(?:audited|unaudited)\s+financial",
        r"statement\s+of\s+consolidated",
    ),
}

_SECTION_TERMINATORS: tuple[str, ...] = (
    r"\n\s*notes?\s+to\s+(?:the\s+)?(?:financial|standalone|consolidated)",
    r"\n\s*for\s+and\s+on\s+behalf",
    r"\n\s*place\s*:",
    r"\n\s*date\s*:",
    r"\n\s*(?:sd/-|director|chairman)\b",
    r"\n\s*(?:part\s*[iii3iv4]|section\s*[iii3iv4cd])",
)

_PERIOD_METRIC_PATTERNS: dict[str, tuple[str, ...]] = {
    "revenue": (
        r"\brevenue\s+from\s+operations\b",
        r"\bnet\s+sales\b",
        r"\bturnover\b",
        r"\boperating\s+revenue\b",
    ),
    "pat": (
        r"\bnet\s+profit\s*/?\s*\(?\s*loss\s*\)?\s+for\s+the\s+(?:period|quarter|year)\b",
        r"\bprofit\s*/?\s*\(?\s*loss\s*\)?\s+(?:after|for)\s+tax\b",
        r"\bprofit\s+(?:after|for)\s+(?:tax|the\s+(?:period|quarter|year))\b",
    ),
    "ebitda": (
        r"\bebitda\b",
        r"\boperating\s+ebitda\b",
        r"\bpbd(?:i)?t\b",
    ),
    "eps": (
        r"\beps\b",
        r"\bearnings\s+per\s+(?:equity\s+)?share\b",
    ),
    "pbt": (
        r"\bprofit\s*/?\s*\(?\s*loss\s*\)?\s+before\s+(?:exceptional\s+items\s+and\s+)?tax\b",
        r"\bprofit\s+before\s+tax\b",
    ),
    "finance_cost": (r"\bfinance\s+costs?\b",),
    "depreciation": (r"\bdepreciation\s+and\s+amortization\s+expenses?\b", r"\bdepreciation\b"),
}


def _slice_labeled_financial_section(full_text: str, section_type: str) -> str:
    if not full_text:
        return ""
    text_lower = full_text.lower()
    patterns = _SECTION_HEADER_PATTERNS.get(section_type, ())
    section_start = -1
    for pattern in patterns:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            section_start = match.start()
            break

    if section_start < 0 and section_type == "standalone":
        generic = re.search(
            r"statement\s+of\s+(?:audited\s+|unaudited\s+)?(?:standalone\s+)?financial\s+results",
            text_lower,
            re.IGNORECASE,
        )
        if generic:
            section_start = generic.start()

    if section_start < 0:
        return ""

    section_end = len(full_text)
    other_type = "consolidated" if section_type == "standalone" else "standalone"
    for pattern in _SECTION_HEADER_PATTERNS.get(other_type, ()):
        match = re.search(pattern, text_lower[section_start + 100 :], re.IGNORECASE)
        if match:
            section_end = min(section_end, section_start + 100 + match.start())
            break

    for pattern in _SECTION_TERMINATORS:
        match = re.search(pattern, text_lower[section_start + 100 :], re.IGNORECASE)
        if match:
            section_end = min(section_end, section_start + 100 + match.start())

    return full_text[section_start : min(section_end, section_start + 18000)]


def _statement_number_from_token(token: str) -> float | None:
    raw = str(token or "").strip().rstrip("'|]")
    if not raw or raw in {"-", "--"}:
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = raw.strip("()").replace(",", "")
    if cleaned.startswith("-"):
        negative = True
        cleaned = cleaned[1:]
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    digits_only = cleaned.isdigit()
    if digits_only and "." not in raw and "," not in raw:
        if len(cleaned) >= 5:
            value = value / 100.0
        elif len(cleaned) == 3 and cleaned.startswith("0"):
            value = value / 100.0
    return -value if negative else value


def _line_looks_like_period_header(line: str) -> bool:
    lower = line.lower()
    return bool(
        re.search(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", lower)
        or re.search(r"\b(?:quarter|year|nine\s+months|six\s+months)\s+ended\b", lower)
    )


def _numbers_from_statement_line(line: str) -> list[float]:
    if _line_looks_like_period_header(line):
        return []
    values: list[float] = []
    for match in _NUMBER_RE.finditer(line):
        value = _statement_number_from_token(match.group(0))
        if value is not None:
            values.append(value)
    return values


def _line_matches_any(line: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns)


def _is_new_statement_row(line: str) -> bool:
    lower = line.lower().strip()
    if not lower:
        return False
    row_signals = (
        "revenue", "income", "expenses", "cost of", "finance cost", "depreciation",
        "profit", "tax", "comprehensive", "paid-up", "other equity", "eps", "earnings per",
    )
    return any(signal in lower for signal in row_signals)


def _collect_statement_values(lines: list[str], index: int, metric_key: str, patterns: tuple[str, ...]) -> list[float]:
    values: list[float] = []
    line = lines[index]
    lower = line.lower()

    if not (metric_key == "eps" and "face value" in lower):
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                values.extend(_numbers_from_statement_line(line[match.end() :]))
                break

    for next_line in lines[index + 1 : index + 16]:
        clean = next_line.strip()
        if not clean:
            continue
        clean_lower = clean.lower()
        if metric_key == "eps" and "face value" in clean_lower:
            continue
        if values and re.search(r"[A-Za-z]", clean) and _is_new_statement_row(clean):
            break
        if metric_key == "eps" and re.fullmatch(r"[-\s]*(basic|diluted)\s*", clean_lower):
            continue
        nums = _numbers_from_statement_line(clean)
        if nums:
            values.extend(nums)
            if len(values) >= 5:
                break
            continue
        if values and re.search(r"[A-Za-z]", clean):
            break

    return values[:3]


def _first_statement_metric_values(section_text: str, metric_key: str) -> list[float]:
    patterns = _PERIOD_METRIC_PATTERNS[metric_key]
    lines = [line.strip() for line in section_text.splitlines()]
    for idx, line in enumerate(lines):
        if not line or not _line_matches_any(line, patterns):
            continue
        if metric_key == "pat" and re.search(r"before\s+tax", line, re.IGNORECASE):
            continue
        values = _collect_statement_values(lines, idx, metric_key, patterns)
        if values:
            return values
    return []


def _value_at(values: list[float], index: int) -> float | None:
    return values[index] if index < len(values) else None


def _scaled_statement_value(value: float | None, *, scale: float, is_absolute: bool) -> float | None:
    if value is None:
        return None
    result = value * scale if is_absolute else value
    return round(result, 2)


def _add_margin_metrics(metrics: dict[str, float]) -> None:
    revenue = metrics.get("revenue")
    if not revenue:
        return
    pat = metrics.get("pat")
    if pat is not None and "pat_margin" not in metrics:
        margin = (pat / revenue) * 100
        if abs(margin) <= 100:
            metrics["pat_margin"] = round(margin, 2)
    ebitda = metrics.get("ebitda")
    if ebitda is not None and "ebitda_margin" not in metrics:
        margin = (ebitda / revenue) * 100
        if abs(margin) <= 100:
            metrics["ebitda_margin"] = round(margin, 2)


def _extract_metric_periods_from_labeled_section(
    full_text: str,
    section_type: str,
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    section_text = _slice_labeled_financial_section(full_text, section_type)
    if len(section_text) < 120:
        return {}, {}, {}

    scale = _detect_unit_scale([], section_text)
    raw_periods: dict[str, list[float]] = {}
    for key in ("revenue", "pat", "ebitda", "eps", "pbt", "finance_cost", "depreciation"):
        values = _first_statement_metric_values(section_text, key)
        if values:
            raw_periods[key] = values

    if "ebitda" not in raw_periods and raw_periods.get("pbt"):
        derived: list[float] = []
        for idx in range(3):
            pbt = _value_at(raw_periods.get("pbt", []), idx)
            finance = _value_at(raw_periods.get("finance_cost", []), idx) or 0.0
            depreciation = _value_at(raw_periods.get("depreciation", []), idx) or 0.0
            if pbt is None:
                continue
            derived.append(pbt + finance + depreciation)
        if derived:
            raw_periods["ebitda"] = derived

    current: dict[str, float] = {}
    previous: dict[str, float] = {}
    year_ago: dict[str, float] = {}
    period_targets = (current, previous, year_ago)
    for key in ("revenue", "pat", "ebitda", "eps"):
        values = raw_periods.get(key) or []
        is_absolute = key != "eps"
        for idx, target in enumerate(period_targets):
            scaled = _scaled_statement_value(_value_at(values, idx), scale=scale, is_absolute=is_absolute)
            if scaled is not None:
                target[key] = scaled

    for target in period_targets:
        _add_margin_metrics(target)

    return current, previous, year_ago


def _format_metric_for_highlight(value: Any, unit: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "not disclosed"
    if unit == "%":
        return f"{number:.1f}%"
    if unit == "Rs":
        return f"Rs {number:.2f}"
    return f"Rs {number:,.2f} Cr"


def _change_text(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, label in (("qoq_pct", "QoQ"), ("yoy_pct", "YoY")):
        value = row.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        direction = "up" if number >= 0 else "down"
        parts.append(f"{direction} {abs(number):.1f}% {label}")
    return ", ".join(parts)


def _build_metric_highlights(rows: list[dict[str, Any]], source_url: str) -> list[dict[str, str]]:
    by_key = {str(row.get("key") or ""): row for row in rows if row.get("current") is not None}
    highlights: list[str] = []

    revenue = by_key.get("revenue")
    if revenue:
        change = _change_text(revenue)
        tail = f", {change}" if change else ""
        highlights.append(f"Revenue came in at {_format_metric_for_highlight(revenue.get('current'), revenue.get('unit') or 'Rs Cr')}{tail}.")

    pat = by_key.get("pat")
    if pat:
        change = _change_text(pat)
        tail = f", {change}" if change else ""
        highlights.append(f"Profit after tax was {_format_metric_for_highlight(pat.get('current'), pat.get('unit') or 'Rs Cr')}{tail}.")

    ebitda = by_key.get("ebitda")
    margin = by_key.get("ebitda_margin")
    if ebitda:
        change = _change_text(ebitda)
        margin_text = ""
        if margin and margin.get("current") is not None:
            margin_text = f", implying an EBITDA margin of {_format_metric_for_highlight(margin.get('current'), '%')}"
        tail = f"; {change}" if change else ""
        highlights.append(f"EBITDA was {_format_metric_for_highlight(ebitda.get('current'), ebitda.get('unit') or 'Rs Cr')}{margin_text}{tail}.")

    eps = by_key.get("eps")
    if eps:
        change = _change_text(eps)
        tail = f", {change}" if change else ""
        highlights.append(f"EPS was {_format_metric_for_highlight(eps.get('current'), eps.get('unit') or 'Rs')}{tail}.")

    return [
        {
            "text": item,
            "url": source_url or "",
            "source_label": "official filing" if source_url else "",
        }
        for item in highlights[:4]
    ]


def _extract_metrics_from_labeled_section(full_text: str, section_type: str) -> dict[str, Any]:
    """Extract current-period metrics from a standalone/consolidated P&L section."""
    current, _, _ = _extract_metric_periods_from_labeled_section(full_text, section_type)
    return current


'''
text = text[:start] + new + text[end:]
path.write_text(text, encoding='utf-8')

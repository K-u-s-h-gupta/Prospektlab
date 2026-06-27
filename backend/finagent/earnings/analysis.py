"""Shared earnings-analysis primitives.

The functions here intentionally avoid network and database calls. They are used
by the dashboard earnings API, the PDF parser, and the Insights Studio flash
article generator so earnings-specific parsing rules live in one place.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

EARNINGS_MARKERS = (
    "earnings",
    "result",
    "results",
    "quarter",
    "quarterly",
    "q1",
    "q2",
    "q3",
    "q4",
    "fy",
    "concall",
    "conference call",
    "analyst call",
    "investor call",
    "fact sheet",
    "investor release",
    "financial result",
    "financial results",
)

EARNINGS_ANNOUNCEMENT_KEYWORDS = (
    "board meeting",
    "financial results",
    "quarterly results",
    "outcome of board meeting",
    "audited financial results",
    "unaudited financial results",
    "results",
    "earnings",
    "investor presentation",
    "press release",
    "conference call",
    "concall",
    "analyst meet",
)

TIMING_LABELS = ("Pre-market", "During-market", "Post-market", "TAS")

_DATE_PATTERNS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d %B %Y",
)

_DATETIME_PATTERNS = (
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
    "%d-%b-%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)

_QUARTER_RE = re.compile(
    r"\b((?:Q[1-4]|quarter\s*[1-4]|[1-4](?:st|nd|rd|th)\s+quarter)\s*(?:FY|F\.?Y\.?|20)?\s*([0-9]{2,4})?|FY\s*([0-9]{2,4})\s*Q([1-4]))\b",
    re.IGNORECASE,
)

_NUMBER_RE = re.compile(r"([-+]?\d+(?:,\d{2,3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    unit: str
    aliases: tuple[str, ...]
    higher_is_good: bool = True


METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec("revenue", "Revenue", "Rs Cr", (
        "revenue from operations", "revenue", "total income", "income from operations",
        "net sales", "gross revenue", "total revenue", "sales", "turnover",
        "net revenue", "operating income", "operating revenue",
    )),
    MetricSpec("pat", "PAT", "Rs Cr", (
        "profit after tax", "pat", "net profit", "profit for the period",
        "profit for the quarter", "profit for the year", "profit/(loss) after tax",
        "profit / (loss) after tax", "net profit/(loss)", "net profit / (loss)",
        "profit attributable", "profit/(loss) for the period",
        "total comprehensive income", "profit after taxation",
    )),
    MetricSpec("ebitda", "EBITDA", "Rs Cr", (
        "ebitda", "operating ebitda", "operating profit", "pbdit", "pbida",
        "profit before interest", "profit before depreciation",
        "earnings before interest", "operating earnings",
        "profit before finance cost", "profit from operations",
        "segment profit", "total segment profit",
    )),
    MetricSpec("eps", "EPS", "Rs", (
        "basic eps", "diluted eps", "earnings per share", "eps",
        "basic earnings per share", "diluted earnings per share",
        "eps (basic)", "eps (diluted)", "earnings per equity share",
    )),
    MetricSpec("ebitda_margin", "EBITDA Margin", "%", (
        "ebitda margin", "operating margin", "ebitda %", "operating margin %",
    )),
    MetricSpec("pat_margin", "PAT Margin", "%", (
        "pat margin", "net profit margin", "net margin", "profit margin",
        "pat %", "net margin %",
    )),
)


def stable_event_uid(*parts: Any) -> str:
    raw = "|".join(str(part or "").strip().lower() for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    if "T" in text:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            pass
    for fmt in _DATE_PATTERNS:
        try:
            return datetime.strptime(text[:30], fmt).date()
        except ValueError:
            pass
    for fmt in _DATETIME_PATTERNS:
        try:
            return datetime.strptime(text[:32], fmt).date()
        except ValueError:
            pass
    return None


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in _DATETIME_PATTERNS:
        try:
            return datetime.strptime(text[:32], fmt)
        except ValueError:
            pass
    parsed_date = parse_date(text)
    return datetime.combine(parsed_date, time.min) if parsed_date else None


def is_earnings_announcement(title: str, category: str | None = None) -> bool:
    haystack = f"{title or ''} {category or ''}".lower()
    return any(keyword in haystack for keyword in EARNINGS_ANNOUNCEMENT_KEYWORDS)


def fiscal_quarter_from_date(value: date | datetime | None) -> str:
    d = value.date() if isinstance(value, datetime) else value
    if d is None:
        d = date.today()
    if 4 <= d.month <= 6:
        quarter, fiscal_year = 1, d.year + 1
    elif 7 <= d.month <= 9:
        quarter, fiscal_year = 2, d.year + 1
    elif 10 <= d.month <= 12:
        quarter, fiscal_year = 3, d.year + 1
    else:
        quarter, fiscal_year = 4, d.year
    return f"Q{quarter} FY{str(fiscal_year)[-2:]}"


def infer_quarter_ref(text: str, fallback_date: date | datetime | None = None) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or ""))
    match = _QUARTER_RE.search(cleaned)
    if not match:
        return fiscal_quarter_from_date(fallback_date)
    raw = match.group(0).upper().replace("F.Y.", "FY").replace("F Y", "FY")
    q_match = re.search(r"Q([1-4])|QUARTER\s*([1-4])|([1-4])(?:ST|ND|RD|TH)\s+QUARTER", raw)
    fy_match = re.search(r"FY\s*([0-9]{2,4})|20([0-9]{2})", raw)
    quarter = next((group for group in (q_match.groups() if q_match else ()) if group), "")
    fiscal = ""
    if fy_match:
        fiscal = fy_match.group(1) or fy_match.group(2) or ""
    if quarter and fiscal:
        return f"Q{quarter} FY{fiscal[-2:]}"
    if quarter:
        fallback = fiscal_quarter_from_date(fallback_date)
        fy = fallback.split("FY")[-1].strip()
        return f"Q{quarter} FY{fy}"
    return raw[:20]


def infer_call_timing(text: str, announced_at: datetime | None = None) -> str:
    lower = str(text or "").lower()
    if any(token in lower for token in ("tas", "trading after session", "after trading session")):
        return "TAS"
    if any(token in lower for token in ("pre-market", "pre market", "before market", "before trading hours")):
        return "Pre-market"
    if any(token in lower for token in ("during market", "during-market", "trading hours")):
        return "During-market"
    if any(token in lower for token in ("post-market", "post market", "after market", "after trading hours")):
        return "Post-market"
    if announced_at:
        hour = announced_at.hour
        if hour < 9:
            return "Pre-market"
        if 9 <= hour < 16:
            return "During-market"
        return "Post-market"
    return "TAS"


# Common Windows-1252/CP1252 to UTF-8 mojibake patterns and their correct replacements.
# These are raw bytes sequences that appear when UTF-8 text is incorrectly decoded.
_ENCODING_FIXES: dict[str, str] = {
    # Mojibake patterns (triple-byte sequences from UTF-8 misinterpretation)
    "\xc3\xa2\xe2\x82\xac\xc2\xa6": "...",    # ellipsis
    "\xc3\xa2\xe2\x82\xac\xe2\x80\x9c": "-",  # en dash
    "\xc3\xa2\xe2\x82\xac\xe2\x80\x9d": "-",  # em dash
    "\xc3\xa2\xe2\x82\xac\xe2\x84\xa2": "'",  # right single quote
    "\xc3\xa2\xe2\x82\xac\xcb\x9c": "'",      # left single quote
    "\xc3\xa2\xe2\x82\xac\xc5\x93": '"',      # left double quote
    "\xc3\xa2\xe2\x82\xac\xc2\xa2": "-",      # bullet
    # Simpler patterns
    "\xc2\xa0": " ",         # non-breaking space
    "\x00": "",              # null bytes
    "\ufeff": "",            # BOM
    # Unicode replacements
    "\u2019": "'",           # right single quotation mark
    "\u2018": "'",           # left single quotation mark
    "\u201c": '"',           # left double quotation mark
    "\u201d": '"',           # right double quotation mark
    "\u2013": "-",           # en dash
    "\u2014": "-",           # em dash
    "\u2026": "...",         # horizontal ellipsis
    "\u00a0": " ",           # non-breaking space
    "\u2022": "-",           # bullet
}


def sanitize_text(text: str) -> str:
    """Clean encoding artifacts and mojibake from extracted text."""
    if not text:
        return ""
    result = text
    for bad, good in _ENCODING_FIXES.items():
        result = result.replace(bad, good)
    # Normalize multiple spaces
    result = re.sub(r" {2,}", " ", result)
    # Normalize multiple newlines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def compact_summary(text: str, max_chars: int = 180) -> str:
    cleaned = sanitize_text(re.sub(r"\s+", " ", str(text or "")).strip())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip(" ,.;") + "."


def _coerce_number(raw: str) -> float | None:
    if not raw:
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _detect_text_unit_scale(text: str) -> float:
    """Detect currency unit from document text and return Rs Crore scale factor.

    Rs Millions  → 0.1   (1 Crore = 10 Millions)
    Rs Lakhs     → 0.01  (1 Crore = 100 Lakhs)
    Rs Crores    → 1.0   (default, no conversion)

    Searches the FULL text for reliability across long financial documents.
    """
    sample = text.lower()
    if any(p in sample for p in (
        "rs. in millions", "rs in millions", "rupees in millions",
        "₹ in millions", "in millions", "rs. mn", "rs mn",
        "inr millions", "amount in millions", "all amounts are in millions",
        "(millions)", "million rupees",
    )):
        return 0.1
    if any(p in sample for p in (
        "rs. in lakhs", "rs in lakhs", "rupees in lakhs",
        "₹ in lakhs", "in lakhs", "rs. lacs", "rs lacs",
        "in lacs", "amount in lakhs", "(lakhs)", "lakh rupees",
    )):
        return 0.01
    return 1.0


def _metric_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias)
    return re.compile(
        rf"\b{escaped}\b[^0-9+\-]{{0,45}}(?:rs\.?|inr)?\s*{_NUMBER_RE.pattern}\s*(?:crore|cr|mn|million|bn|billion|%|rs\.?)?",
        re.IGNORECASE,
    )


def _extract_metric_from_line(line: str, spec_aliases: tuple[str, ...], scale: float) -> float | None:
    """Extract a metric value from a line that may contain label and number."""
    line_lower = line.lower()
    for alias in spec_aliases:
        if alias.lower() in line_lower:
            # Find all numbers in the line
            numbers = _NUMBER_RE.findall(line)
            for num_str in numbers:
                # Skip dates, percentages that are clearly not the metric
                if '/' in num_str or '-' in num_str[:4]:
                    continue
                value = _coerce_number(num_str)
                if value is not None and abs(value) > 0.01:
                    return value * scale
    return None


def extract_financial_metrics(text: str) -> dict[str, float]:
    """Extract financial metrics from document text.
    
    Uses multiple strategies:
    1. Pattern matching for "metric_name ... value" patterns
    2. Line-by-line extraction for tabular text
    3. Structured table-like text parsing
    """
    body = re.sub(r"\s+", " ", str(text or ""))
    scale = _detect_text_unit_scale(body)
    metrics: dict[str, float] = {}
    
    # Strategy 1: Pattern matching (original)
    for spec in METRIC_SPECS:
        for alias in spec.aliases:
            match = _metric_pattern(alias).search(body)
            if not match:
                continue
            value = _coerce_number(match.group(1))
            if value is not None:
                # Apply unit scale for absolute values (not %, not EPS)
                if spec.unit not in ("%",) and spec.key != "eps":
                    value = round(value * scale, 2)
                metrics[spec.key] = value
                break
    
    # Strategy 2: Line-by-line extraction for metrics still missing
    lines = text.split('\n')
    for spec in METRIC_SPECS:
        if spec.key in metrics:
            continue
        for line in lines:
            # Skip very long lines (likely paragraph text)
            if len(line) > 500:
                continue
            value = _extract_metric_from_line(line, spec.aliases, scale if spec.unit not in ("%",) and spec.key != "eps" else 1.0)
            if value is not None:
                # Sanity checks
                if spec.key in ('ebitda_margin', 'pat_margin') and abs(value) > 100:
                    continue
                if spec.key == 'eps' and abs(value) > 10000:
                    continue
                metrics[spec.key] = round(value, 2)
                break
    
    # Strategy 3: Look for specific patterns common in Indian filings
    # "Revenue from Operations ... 2,69,496"
    # "Profit After Tax ... 22,167"
    specific_patterns = [
        (r"revenue\s+from\s+operations[^\d]*(" + _NUMBER_RE.pattern + r")", "revenue"),
        (r"total\s+income[^\d]*(" + _NUMBER_RE.pattern + r")", "revenue"),
        (r"profit\s+after\s+tax[^\d]*(" + _NUMBER_RE.pattern + r")", "pat"),
        (r"net\s+profit[^\d]*(" + _NUMBER_RE.pattern + r")", "pat"),
        (r"profit\s+for\s+the\s+(?:period|quarter|year)[^\d]*(" + _NUMBER_RE.pattern + r")", "pat"),
        (r"ebitda[^\d]*(" + _NUMBER_RE.pattern + r")", "ebitda"),
        (r"(?:basic|diluted)\s+eps[^\d]*(" + _NUMBER_RE.pattern + r")", "eps"),
        (r"earnings\s+per\s+share[^\d]*(" + _NUMBER_RE.pattern + r")", "eps"),
    ]
    
    for pattern, key in specific_patterns:
        if key in metrics:
            continue
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            value = _coerce_number(match.group(1))
            if value is not None:
                if key in ('revenue', 'pat', 'ebitda'):
                    value = round(value * scale, 2)
                else:
                    value = round(value, 2)
                # Sanity check
                if key in ('ebitda_margin', 'pat_margin') and abs(value) > 100:
                    continue
                metrics[key] = value

    # Compute margins if we have the components
    if "pat_margin" not in metrics and metrics.get("pat") is not None and metrics.get("revenue"):
        margin = (metrics["pat"] / metrics["revenue"]) * 100
        if abs(margin) <= 100:
            metrics["pat_margin"] = round(margin, 2)
    if "ebitda_margin" not in metrics and metrics.get("ebitda") is not None and metrics.get("revenue"):
        margin = (metrics["ebitda"] / metrics["revenue"]) * 100
        if abs(margin) <= 100:
            metrics["ebitda_margin"] = round(margin, 2)
    
    return metrics


def pct_change(current: float | None, reference: float | None) -> float | None:
    if current is None or reference is None:
        return None
    if not math.isfinite(current) or not math.isfinite(reference) or reference == 0:
        return None
    return round(((current - reference) / abs(reference)) * 100, 1)


def build_financial_comparison_rows(
    current: dict[str, Any],
    previous_quarter: dict[str, Any] | None = None,
    same_quarter_last_year: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    previous_quarter = previous_quarter or {}
    same_quarter_last_year = same_quarter_last_year or {}
    rows: list[dict[str, Any]] = []
    for spec in METRIC_SPECS:
        cur = _numeric_or_none(current.get(spec.key))
        prev = _numeric_or_none(previous_quarter.get(spec.key))
        yoy = _numeric_or_none(same_quarter_last_year.get(spec.key))
        rows.append(
            {
                "key": spec.key,
                "label": spec.label,
                "unit": spec.unit,
                "current": cur,
                "previous_quarter": prev,
                "same_quarter_last_year": yoy,
                "qoq_pct": pct_change(cur, prev),
                "yoy_pct": pct_change(cur, yoy),
                "higher_is_good": spec.higher_is_good,
            }
        )
    return rows


def _numeric_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_ai_highlights(text: str, source_url: str | None = None, limit: int = 3) -> list[dict[str, str]]:
    body = re.sub(r"\s+", " ", str(text or "")).strip()
    if not body:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", body)
    scored: list[tuple[int, str]] = []
    signal_words = (
        "revenue",
        "profit",
        "pat",
        "ebitda",
        "margin",
        "growth",
        "guidance",
        "order book",
        "volume",
        "production",
        "management",
        "demand",
    )
    for sentence in sentences:
        clean = compact_summary(sentence, 220)
        if len(clean) < 45:
            continue
        score = sum(2 for word in signal_words if word in clean.lower())
        score += 2 if re.search(r"\d", clean) else 0
        score += 1 if "%" in clean or "crore" in clean.lower() or "million" in clean.lower() else 0
        scored.append((score, clean))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [text for score, text in scored if score > 0][:limit]
    if not selected:
        selected = [compact_summary(body, 180)]
    return [
        {
            "text": item,
            "url": source_url or "",
            "source_label": "official filing" if source_url else "",
        }
        for item in selected[:limit]
    ]


def split_transcript_sections(text: str) -> dict[str, list[dict[str, Any]]]:
    body = str(text or "").strip()
    if not body:
        return {"prepared_remarks": [], "qa": []}
    qna_match = re.search(r"\b(question\s+and\s+answer|q\s*&\s*a|q&a|questions?\s+and\s+answers?)\b", body, re.IGNORECASE)
    prepared_text = body[: qna_match.start()] if qna_match else body
    qa_text = body[qna_match.start() :] if qna_match else ""
    return {
        "prepared_remarks": _paragraph_blocks(prepared_text, section="Prepared remarks")[:8],
        "qa": _paragraph_blocks(qa_text, section="Q&A")[:10],
    }


def _paragraph_blocks(text: str, *, section: str) -> list[dict[str, Any]]:
    chunks = [
        compact_summary(chunk, 700)
        for chunk in re.split(r"\n{2,}|(?<=\.)\s+(?=(?:Operator|Moderator|Analyst|Management|Mr\.|Ms\.|Q:|A:))", text)
    ]
    blocks = []
    for idx, chunk in enumerate(chunks):
        clean = chunk.strip()
        if len(clean) < 40:
            continue
        speaker = ""
        speaker_match = re.match(r"^([A-Z][A-Za-z .'-]{1,50}):\s*(.+)$", clean)
        if speaker_match:
            speaker = speaker_match.group(1).strip()
            clean = speaker_match.group(2).strip()
        blocks.append({"speaker": speaker or section, "text": clean, "order": idx + 1})
    return blocks


def build_earnings_article_structure_brief() -> str:
    return (
        "For earnings-like topics, structure the article around:\n"
        "1. The quarter in one paragraph.\n"
        "2. The metrics that actually moved: revenue, EBITDA, margin, PAT, EPS, cash conversion, and dividend if declared.\n"
        "3. Demand by geography, vertical, product line, client segment, or volume driver.\n"
        "4. Margin quality, input costs, hiring/productivity, utilization, and working capital.\n"
        "5. Management commentary, order book, guidance, analyst-call tone, and what to monitor next.\n"
        "6. Include at least one earnings table with YoY and QoQ deltas and one visual block based on those metrics.\n"
    )


def build_document_payload(
    *,
    text: str,
    source_url: str | None,
    current_metrics: dict[str, Any] | None = None,
    previous_metrics: dict[str, Any] | None = None,
    year_ago_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_metrics = current_metrics or extract_financial_metrics(text)
    return {
        "highlights": build_ai_highlights(text, source_url=source_url, limit=3),
        "transcript": split_transcript_sections(text),
        "financial_comparison": build_financial_comparison_rows(
            current_metrics,
            previous_metrics or {},
            year_ago_metrics or {},
        ),
        "metrics": current_metrics,
    }


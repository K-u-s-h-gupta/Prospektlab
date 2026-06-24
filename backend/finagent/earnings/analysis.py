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
    MetricSpec("revenue", "Revenue", "Rs Cr", ("revenue from operations", "revenue", "total income", "income from operations")),
    MetricSpec("pat", "PAT", "Rs Cr", ("profit after tax", "pat", "net profit", "profit for the period")),
    MetricSpec("ebitda", "EBITDA", "Rs Cr", ("ebitda", "operating ebitda", "operating profit")),
    MetricSpec("eps", "EPS", "Rs", ("basic eps", "diluted eps", "earnings per share", "eps")),
    MetricSpec("ebitda_margin", "EBITDA Margin", "%", ("ebitda margin", "operating margin")),
    MetricSpec("pat_margin", "PAT Margin", "%", ("pat margin", "net profit margin", "net margin")),
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


def compact_summary(text: str, max_chars: int = 180) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
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


def _metric_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias)
    return re.compile(
        rf"\b{escaped}\b[^0-9+\-]{{0,45}}(?:rs\.?|inr)?\s*{_NUMBER_RE.pattern}\s*(?:crore|cr|mn|million|bn|billion|%|rs\.?)?",
        re.IGNORECASE,
    )


def extract_financial_metrics(text: str) -> dict[str, float]:
    body = re.sub(r"\s+", " ", str(text or ""))
    metrics: dict[str, float] = {}
    for spec in METRIC_SPECS:
        for alias in spec.aliases:
            match = _metric_pattern(alias).search(body)
            if not match:
                continue
            value = _coerce_number(match.group(1))
            if value is not None:
                metrics[spec.key] = value
                break
    if "pat_margin" not in metrics and metrics.get("pat") is not None and metrics.get("revenue"):
        metrics["pat_margin"] = round((metrics["pat"] / metrics["revenue"]) * 100, 2)
    if "ebitda_margin" not in metrics and metrics.get("ebitda") is not None and metrics.get("revenue"):
        metrics["ebitda_margin"] = round((metrics["ebitda"] / metrics["revenue"]) * 100, 2)
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


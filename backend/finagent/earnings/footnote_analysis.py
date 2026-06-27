"""Footnote QoQ Diff Engine.

Extracts "Notes to Financial Results" from current and previous quarter PDFs,
runs structural text diff, highlights accounting policy changes.
"""

from __future__ import annotations

import difflib
import logging
import re
from typing import Any

logger = logging.getLogger("finagent.earnings.footnote_analysis")


# Keywords indicating significant accounting changes
ACCOUNTING_CHANGE_KEYWORDS = (
    "accounting policy",
    "change in",
    "revised",
    "modified",
    "valuation method",
    "capitalization",
    "depreciation method",
    "revenue recognition",
    "exceptional item",
    "one-time",
    "reclassified",
    "restated",
    "prior period",
    "ind as",
    "accounting standard",
)

# Severity classification patterns
SEVERITY_PATTERNS: dict[str, tuple[str, ...]] = {
    "high": (
        "accounting policy",
        "valuation method",
        "revenue recognition",
        "restated",
        "restatement",
        "change in accounting",
        "ind as",
    ),
    "medium": (
        "exceptional",
        "one-time",
        "reclassified",
        "depreciation",
        "non-recurring",
        "impairment",
        "write-off",
        "provision",
    ),
    "low": (
        "minor adjustment",
        "rounding",
        "presentation",
    ),
}


def extract_footnotes_section(full_text: str) -> str:
    """Extract the "Notes to Financial Results" section from earnings PDF text.

    Uses multiple patterns to handle different formatting styles used by
    Indian companies in their financial result filings.
    """
    if not full_text:
        return ""

    # Clean text for searching
    text = re.sub(r"\s+", " ", full_text)

    # Patterns to find notes section - ordered by specificity
    patterns = [
        # Standard "Notes to Financial Results"
        r"(?i)(notes?\s+to\s+(?:the\s+)?(?:unaudited\s+)?(?:audited\s+)?financial\s+results?)(.{200,8000}?)(?=\n\s*(?:for\s+and\s+on\s+behalf|place\s*:|date\s*:|sd/-|signed|director|chairman|managing\s+director|chief\s+financial)|$)",
        # "Statement of Notes"
        r"(?i)(statement\s+of\s+notes)(.{200,8000}?)(?=\n\s*(?:for\s+and\s+on\s+behalf|place\s*:|date\s*:)|$)",
        # "Accompanying Notes"
        r"(?i)(accompanying\s+notes)(.{200,8000}?)(?=\n\s*(?:for\s+and\s+on\s+behalf|place\s*:|date\s*:)|$)",
        # Numbered notes starting with "1."
        r"(?i)(?:notes?\s*:?\s*)(\d+\.\s+.{50,}(?:\n\s*\d+\.\s+.{50,}){2,})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            # Return the captured content
            content = match.group(0).strip()
            if len(content) > 100:  # Meaningful content threshold
                return content

    # Fallback: Look for any section with numbered points after financial tables
    notes_match = re.search(
        r"(?i)(?:notes?\s*:?\s*\n?)(\d+\.\s+.{30,}(?:\n\s*\d+\.\s+.{30,})+)",
        full_text,
        re.DOTALL,
    )
    if notes_match:
        return notes_match.group(0).strip()

    return ""


def categorize_clause(text: str) -> tuple[str, str]:
    """Categorize a footnote clause and determine severity.

    Returns:
        Tuple of (category, severity)
    """
    text_lower = text.lower()

    # Determine category
    if any(kw in text_lower for kw in ("accounting policy", "accounting standard", "ind as", "valuation")):
        category = "accounting_policy_change"
    elif any(kw in text_lower for kw in ("exceptional", "one-time", "non-recurring")):
        category = "exceptional_item"
    elif any(kw in text_lower for kw in ("related party", "subsidiary", "associate", "holding company")):
        category = "related_party"
    elif any(kw in text_lower for kw in ("contingent", "liability", "provision", "litigation")):
        category = "contingent_liability"
    elif any(kw in text_lower for kw in ("segment", "business segment", "geographical")):
        category = "segment_reporting"
    elif any(kw in text_lower for kw in ("tax", "deferred tax", "income tax")):
        category = "tax_related"
    else:
        category = "other"

    # Determine severity
    for severity, keywords in SEVERITY_PATTERNS.items():
        if any(kw in text_lower for kw in keywords):
            return category, severity

    return category, "low"


def split_into_clauses(text: str) -> list[str]:
    """Split footnotes text into individual clauses/points.

    Handles various formatting:
    - Numbered points (1., 2., etc.)
    - Lettered points (a), b), etc.)
    - Roman numerals (i., ii., etc.)
    - Sentence-based splitting
    """
    clauses: list[str] = []

    # First try splitting on numbered points
    numbered_split = re.split(r"(?<=[.;])\s*(?=\d+\.\s)|(?<=\n)\s*\d+\.\s*", text)
    if len(numbered_split) > 2:
        clauses = [c.strip() for c in numbered_split if c.strip() and len(c.strip()) > 30]
        if clauses:
            return clauses

    # Try splitting on lettered points
    lettered_split = re.split(r"(?<=[.;])\s*(?=\([a-z]\)\s)|(?<=\n)\s*\([a-z]\)\s*", text)
    if len(lettered_split) > 2:
        clauses = [c.strip() for c in lettered_split if c.strip() and len(c.strip()) > 30]
        if clauses:
            return clauses

    # Fallback: Split on sentence boundaries but keep context
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    clauses = [s.strip() for s in sentences if s.strip() and len(s.strip()) > 50]

    return clauses


def compute_footnote_diff(
    current_text: str,
    previous_text: str,
) -> dict[str, Any]:
    """Compute structural diff between two footnote sections.

    Args:
        current_text: Footnotes from current quarter
        previous_text: Footnotes from previous quarter

    Returns:
        Dict with added_clauses, removed_clauses, summary, alert_level
    """
    current_clauses = set(split_into_clauses(current_text))
    previous_clauses = set(split_into_clauses(previous_text))

    # Find differences
    added = current_clauses - previous_clauses
    removed = previous_clauses - current_clauses

    result: dict[str, Any] = {
        "added_clauses": [],
        "removed_clauses": [],
        "modified_clauses": [],
        "summary": "",
        "alert_level": "none",
    }

    max_severity = "none"
    severity_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}

    # Process added clauses
    for clause in added:
        category, severity = categorize_clause(clause)
        result["added_clauses"].append({
            "text": clause[:800],  # Truncate long clauses
            "category": category,
            "severity": severity,
        })
        if severity_rank.get(severity, 0) > severity_rank.get(max_severity, 0):
            max_severity = severity

    # Process removed clauses
    for clause in removed:
        category, severity = categorize_clause(clause)
        result["removed_clauses"].append({
            "text": clause[:800],
            "category": category,
            "severity": severity,
        })
        if severity_rank.get(severity, 0) > severity_rank.get(max_severity, 0):
            max_severity = severity

    # Try to identify modified clauses (similar but changed)
    for added_clause in list(added):
        for removed_clause in list(removed):
            similarity = _compute_similarity(added_clause, removed_clause)
            if similarity > 0.6:  # 60% similar = likely modified
                category, severity = categorize_clause(added_clause)
                result["modified_clauses"].append({
                    "previous": removed_clause[:400],
                    "current": added_clause[:400],
                    "category": category,
                    "severity": severity,
                    "similarity": round(similarity, 2),
                })

    result["alert_level"] = max_severity

    # Generate summary
    n_added = len(result["added_clauses"])
    n_removed = len(result["removed_clauses"])
    n_modified = len(result["modified_clauses"])
    high_severity = sum(
        1 for c in result["added_clauses"] + result["removed_clauses"]
        if c.get("severity") == "high"
    )

    if high_severity > 0:
        result["summary"] = (
            f"⚠️ {high_severity} significant accounting change(s) detected. "
            f"{n_added} new clauses, {n_removed} removed, {n_modified} modified."
        )
    elif n_modified > 0:
        result["summary"] = (
            f"{n_modified} clause(s) modified, {n_added} new, {n_removed} removed."
        )
    elif n_added + n_removed > 0:
        result["summary"] = (
            f"{n_added} new clause(s) added, {n_removed} removed from previous quarter."
        )
    else:
        result["summary"] = "No significant changes in footnotes."

    return result


def _compute_similarity(text1: str, text2: str) -> float:
    """Compute similarity ratio between two texts."""
    return difflib.SequenceMatcher(None, text1.lower(), text2.lower()).ratio()


def analyze_footnotes_for_earnings(
    current_text: str,
    previous_text: str | None,
    current_quarter: str,
    previous_quarter: str | None,
) -> dict[str, Any]:
    """Full pipeline: extract footnotes from both quarters and compute diff.

    Args:
        current_text: Full text from current quarter PDF
        previous_text: Full text from previous quarter PDF (optional)
        current_quarter: Quarter reference string (e.g., "Q3 FY26")
        previous_quarter: Previous quarter reference string (optional)

    Returns:
        Dict with footnotes analysis or error info
    """
    current_footnotes = extract_footnotes_section(current_text)

    if not current_footnotes:
        return {
            "error": "Could not extract footnotes section from current filing",
            "current_found": False,
            "current_quarter": current_quarter,
        }

    result: dict[str, Any] = {
        "current_quarter": current_quarter,
        "current_footnotes_length": len(current_footnotes),
        "current_footnotes_preview": current_footnotes[:500] + "..." if len(current_footnotes) > 500 else current_footnotes,
    }

    if not previous_text:
        result["error"] = "No previous quarter data available for comparison"
        result["previous_found"] = False
        return result

    previous_footnotes = extract_footnotes_section(previous_text)

    if not previous_footnotes:
        result["error"] = "Could not extract footnotes section from previous quarter filing"
        result["previous_found"] = False
        return result

    result["previous_found"] = True
    result["previous_quarter"] = previous_quarter
    result["previous_footnotes_length"] = len(previous_footnotes)

    # Compute diff
    diff_result = compute_footnote_diff(current_footnotes, previous_footnotes)
    result.update(diff_result)

    return result


def get_accounting_change_indicators(text: str) -> list[dict[str, str]]:
    """Identify specific accounting change indicators in footnotes text.

    Returns list of detected indicators with their context.
    """
    indicators: list[dict[str, str]] = []
    text_lower = text.lower()

    indicator_patterns = [
        (r"(?i)change\s+in\s+accounting\s+polic[yies]", "Accounting Policy Change"),
        (r"(?i)restated|restatement", "Restatement"),
        (r"(?i)ind\s*as\s*\d+", "Ind AS Reference"),
        (r"(?i)exceptional\s+item", "Exceptional Item"),
        (r"(?i)one-?time\s+(?:charge|income|expense)", "One-Time Item"),
        (r"(?i)change\s+in\s+(?:depreciation|amortization)\s+method", "Depreciation Change"),
        (r"(?i)change\s+in\s+valuation", "Valuation Change"),
        (r"(?i)impairment\s+(?:loss|charge)", "Impairment"),
        (r"(?i)write[-\s]?off", "Write-off"),
        (r"(?i)prior\s+period\s+(?:adjustment|item)", "Prior Period Adjustment"),
    ]

    for pattern, indicator_type in indicator_patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            start = max(0, match.start() - 50)
            end = min(len(text), match.end() + 100)
            context = text[start:end].strip()
            indicators.append({
                "type": indicator_type,
                "matched_text": match.group(0),
                "context": f"...{context}...",
            })

    return indicators

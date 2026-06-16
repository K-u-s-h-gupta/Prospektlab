"""Small, lossless XBRL helpers for official exchange filings.

The first goal here is not to perfectly understand every India-specific
taxonomy. It is to preserve every fact with context so later graph/query layers
can reason over the data without re-downloading the filing.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any


_IGNORED_LOCAL_NAMES = {
    "xbrl",
    "context",
    "entity",
    "identifier",
    "period",
    "instant",
    "startdate",
    "enddate",
    "unit",
    "measure",
    "schemaref",
    "roleRef".lower(),
    "arcroleRef".lower(),
}


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    if ":" in tag:
        return tag.rsplit(":", 1)[1]
    return tag


def _namespace(tag: str) -> str | None:
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return None


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").replace("\xa0", " ").split())


def _to_number(value: str) -> float | None:
    raw = _clean_text(value)
    if not raw or raw in {"-", "--", "NA", "N.A.", "Nil", "NIL"}:
        return None
    neg = raw.startswith("(") and raw.endswith(")")
    raw = raw.strip("()").replace(",", "").replace("%", "")
    try:
        number = float(raw)
        return -number if neg else number
    except ValueError:
        return None


def _norm_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


@dataclass(frozen=True)
class XbrlContext:
    context_ref: str
    period_start: str | None = None
    period_end: str | None = None
    instant: str | None = None
    entity_identifier: str | None = None


def is_probable_xbrl(text: str, *, url: str = "", content_type: str = "") -> bool:
    haystack = f"{url} {content_type} {text[:500]}".lower()
    return (
        "<xbrl" in haystack
        or "xbrli:" in haystack
        or "www.xbrl.org" in haystack
        or url.lower().split("?", 1)[0].endswith((".xml", ".xbrl"))
    )


def parse_xbrl_facts(xml_text: str) -> dict[str, Any]:
    """Parse an XBRL/XML document into contexts and leaf facts.

    Returns a dict with ``success=False`` instead of raising for malformed
    input, because exchange attachment feeds may occasionally return HTML error
    pages with XML-looking filenames.
    """
    text = (xml_text or "").strip()
    if not text:
        return {"success": False, "error": "empty XML", "facts": []}
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except Exception as exc:
        return {"success": False, "error": str(exc), "facts": []}

    contexts: dict[str, XbrlContext] = {}
    for elem in root.iter():
        if _local_name(elem.tag).lower() != "context":
            continue
        context_id = str(elem.attrib.get("id") or "").strip()
        if not context_id:
            continue
        period_start = None
        period_end = None
        instant = None
        entity_identifier = None
        for child in elem.iter():
            lname = _local_name(child.tag).lower()
            value = _clean_text(child.text)
            if lname == "identifier" and value:
                entity_identifier = value
            elif lname == "startdate" and value:
                period_start = value[:10]
            elif lname == "enddate" and value:
                period_end = value[:10]
            elif lname == "instant" and value:
                instant = value[:10]
        contexts[context_id] = XbrlContext(
            context_ref=context_id,
            period_start=period_start,
            period_end=period_end,
            instant=instant,
            entity_identifier=entity_identifier,
        )

    facts: list[dict[str, Any]] = []
    taxonomy_namespaces: set[str] = set()
    for elem in root.iter():
        lname = _local_name(elem.tag)
        lname_lower = lname.lower()
        if lname_lower in _IGNORED_LOCAL_NAMES:
            continue
        if list(elem):
            continue
        value_text = _clean_text(elem.text)
        if value_text == "":
            continue
        context_ref = str(elem.attrib.get("contextRef") or elem.attrib.get("contextref") or "").strip()
        ctx = contexts.get(context_ref)
        ns = _namespace(elem.tag)
        if ns:
            taxonomy_namespaces.add(ns)
        facts.append(
            {
                "fact_name": lname,
                "fact_key": _norm_key(lname),
                "namespace": ns,
                "context_ref": context_ref or None,
                "unit_ref": elem.attrib.get("unitRef") or elem.attrib.get("unitref"),
                "decimals": elem.attrib.get("decimals"),
                "value_text": value_text,
                "value_numeric": _to_number(value_text),
                "period_start": ctx.period_start if ctx else None,
                "period_end": ctx.period_end if ctx else None,
                "instant": ctx.instant if ctx else None,
                "entity_identifier": ctx.entity_identifier if ctx else None,
                "attributes": dict(elem.attrib),
            }
        )

    return {
        "success": True,
        "facts": facts,
        "contexts": {key: ctx.__dict__ for key, ctx in contexts.items()},
        "taxonomy_namespaces": sorted(taxonomy_namespaces),
    }


_FINANCIAL_METRIC_PATTERNS: dict[str, tuple[str, ...]] = {
    "revenue_from_operations": (
        "revenuefromoperations",
        "revenuefromcontractswithcustomers",
        "revenuefromsaleofproducts",
        "revenuefromsaleofservices",
    ),
    "total_income": ("totalincome", "income"),
    "profit_before_tax": ("profitbeforetax", "profitlossbeforetax"),
    "profit_after_tax": (
        "profitlossfortheperiod",
        "profitaftertax",
        "netprofitlossfortheperiod",
        "profitloss",
    ),
    "eps_basic": ("basicearningslosspershare", "basiceps"),
    "eps_diluted": ("dilutedearningslosspershare", "dilutedeps"),
    "net_worth": ("networth", "totalnetworth"),
}


def summarize_xbrl_facts(category: str, facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a compact category summary while preserving the full fact list elsewhere."""
    category = (category or "").lower()
    summary: dict[str, Any] = {
        "category": category,
        "facts_count": len(facts),
        "period_start": None,
        "period_end": None,
        "as_of_date": None,
    }
    periods = [
        (
            str(f.get("period_start") or ""),
            str(f.get("period_end") or f.get("instant") or ""),
        )
        for f in facts
        if f.get("period_end") or f.get("instant")
    ]
    if periods:
        period_start, period_end = sorted(periods, key=lambda pair: pair[1])[-1]
        summary["period_start"] = period_start or None
        summary["period_end"] = period_end or None
        summary["as_of_date"] = period_end or None

    if category == "financial_results":
        for metric, patterns in _FINANCIAL_METRIC_PATTERNS.items():
            best: dict[str, Any] | None = None
            for fact in facts:
                key = str(fact.get("fact_key") or "")
                if fact.get("value_numeric") is None:
                    continue
                if any(pattern == key or pattern in key for pattern in patterns):
                    best = fact
            if best:
                summary[metric] = best.get("value_numeric")
                summary[f"{metric}_fact"] = best.get("fact_name")

    elif category == "related_party_transactions":
        numeric_facts = [f for f in facts if f.get("value_numeric") is not None]
        summary["numeric_facts_count"] = len(numeric_facts)
        summary["top_numeric_facts"] = sorted(
            (
                {
                    "fact_name": f.get("fact_name"),
                    "value_numeric": f.get("value_numeric"),
                    "period_end": f.get("period_end") or f.get("instant"),
                }
                for f in numeric_facts
            ),
            key=lambda row: abs(float(row["value_numeric"] or 0)),
            reverse=True,
        )[:25]

    elif category == "corporate_actions":
        joined = " ".join(str(f.get("value_text") or "") for f in facts[:200])
        summary.update(extract_corporate_action_from_text(joined))
        summary["text_facts_count"] = sum(1 for f in facts if f.get("value_numeric") is None)
        summary["numeric_facts_count"] = sum(1 for f in facts if f.get("value_numeric") is not None)

    elif category in {"voting_results", "corporate_governance", "brsr", "insider_trading"}:
        summary["text_facts_count"] = sum(1 for f in facts if f.get("value_numeric") is None)
        summary["numeric_facts_count"] = sum(1 for f in facts if f.get("value_numeric") is not None)

    return summary


def extract_corporate_action_from_text(text: str) -> dict[str, Any]:
    """Extract deterministic corporate-action metadata from announcement text."""
    normalized = _clean_text(text)
    lowered = normalized.lower()
    action_type = "other"
    if "bonus" in lowered:
        action_type = "bonus"
    elif "split" in lowered or "sub-division" in lowered or "subdivision" in lowered:
        action_type = "split"
    elif "rights issue" in lowered or "right issue" in lowered:
        action_type = "rights"
    elif "dividend" in lowered:
        action_type = "dividend"
    elif "buyback" in lowered or "buy-back" in lowered:
        action_type = "buyback"

    ratio = None
    ratio_match = re.search(
        r"(?:ratio\s*(?:of)?\s*)?(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)",
        normalized,
        flags=re.I,
    )
    if ratio_match:
        ratio = f"{ratio_match.group(1)}:{ratio_match.group(2)}"

    record_date = None
    date_match = re.search(
        r"(?:record date|book closure|cut-?off date)[^\dA-Za-z]{0,20}"
        r"(\d{1,2}[-/ ](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|\d{1,2})[-/ ]\d{2,4})",
        normalized,
        flags=re.I,
    )
    if date_match:
        record_date = date_match.group(1)

    return {
        "action_type": action_type,
        "ratio": ratio,
        "record_date_raw": record_date,
    }


def extract_auditor_names_from_text(text: str) -> list[dict[str, str]]:
    """Extract likely statutory auditor names from governance/audit text."""
    normalized = _clean_text(text)
    candidates: list[dict[str, str]] = []
    patterns = (
        r"(?:M/s\.?\s+)?([A-Z][A-Za-z&.,' -]{3,120}?(?:Chartered Accountants|LLP|& Co\.?|Associates|Accountants))",
        r"(?:statutory auditors?|auditors?)\s*(?:of the company)?\s*(?:is|are|:|-)\s*(?:M/s\.?\s+)?([A-Z][A-Za-z&.,' -]{3,120})",
    )
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, normalized, flags=re.I):
            name = _clean_text(match.group(1)).strip(" .,:;-")
            if len(name) < 4:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            candidates.append({"auditor_name": name, "source": "document_section"})
            if len(candidates) >= 5:
                return candidates
    return candidates

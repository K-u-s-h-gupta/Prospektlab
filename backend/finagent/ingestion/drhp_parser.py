"""DRHP section extractor built on MinerU / markdown output.

SEBI ICDR Regulations mandate consistent section naming across DRHP/RHP filings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# SEBI ICDR mandated section headers (normalized aliases)
DRHP_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "business_overview": (
        "our business",
        "business overview",
        "industry overview",
        "about the company",
        "business of the company",
    ),
    "objects_of_issue": (
        "objects of the issue",
        "objects of this issue",
        "objects of the offer",
        "use of proceeds",
        "issue proceeds",
    ),
    "risk_factors": ("risk factors", "risk factor"),
    "financial_information": (
        "financial information",
        "restated financial information",
        "summary financial information",
        "selected financial information",
        "financial statements",
    ),
    "mda": (
        "management's discussion and analysis",
        "management discussion and analysis",
        "md&a",
    ),
    "promoters": (
        "promoters and promoter group",
        "our promoters",
        "promoter and promoter group",
        "promoter group",
    ),
    "related_party": (
        "related party transactions",
        "related party transaction",
    ),
    "legal_proceedings": (
        "outstanding litigation and material developments",
        "pending legal proceedings",
        "legal proceedings",
        "litigation",
    ),
    "kpis": (
        "key performance indicators",
        "basis for issue price",
        "key performance indicator",
    ),
    "capital_structure": ("capital structure",),
    "peer_comparison": (
        "comparison with listed peers",
        "peer comparison",
        "comparison with industry peers",
        "industry comparison",
    ),
    "issue_details": (
        "terms of the issue",
        "details of the issue",
        "issue structure",
    ),
}


@dataclass
class DrhpSection:
    name: str
    text: str
    start_offset: int
    end_offset: int
    present: bool = True


@dataclass
class ParsedDrhp:
    sections: dict[str, DrhpSection] = field(default_factory=dict)
    full_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _find_section_starts(text: str) -> list[tuple[int, str, str]]:
    lower = text.lower()
    hits: list[tuple[int, str, str]] = []
    for section_name, aliases in DRHP_SECTION_ALIASES.items():
        best_pos: int | None = None
        best_alias = ""
        for alias in aliases:
            pattern = re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", re.IGNORECASE)
            match = pattern.search(lower)
            if match and (best_pos is None or match.start() < best_pos):
                best_pos = match.start()
                best_alias = alias
        if best_pos is not None:
            hits.append((best_pos, section_name, best_alias))
    hits.sort(key=lambda item: item[0])
    return hits


def extract_sections(markdown: str, *, max_section_chars: int = 120_000) -> ParsedDrhp:
    """Detect DRHP section boundaries from markdown text."""
    text = markdown or ""
    if not text.strip():
        return ParsedDrhp(full_text="", sections={})

    positions = _find_section_starts(text)
    sections: dict[str, DrhpSection] = {}
    for idx, (start, section_name, alias) in enumerate(positions):
        end = positions[idx + 1][0] if idx + 1 < len(positions) else len(text)
        end = min(end, start + max_section_chars)
        section_text = text[start:end].strip()
        sections[section_name] = DrhpSection(
            name=section_name,
            text=section_text,
            start_offset=start,
            end_offset=end,
            present=bool(section_text),
        )

    for section_name in DRHP_SECTION_ALIASES:
        sections.setdefault(
            section_name,
            DrhpSection(name=section_name, text="", start_offset=-1, end_offset=-1, present=False),
        )

    return ParsedDrhp(sections=sections, full_text=text)


def extract_numbered_risks(risk_section: str) -> list[dict[str, Any]]:
    """Extract numbered risk factors from the Risk Factors section."""
    if not risk_section:
        return []
    risks: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?:^|\n)\s*(\d{1,3})[\.\)]\s+(.+?)(?=(?:\n\s*\d{1,3}[\.\)]\s+)|\Z)",
        re.DOTALL,
    )
    for match in pattern.finditer(risk_section):
        body = _normalize_whitespace(match.group(2))
        if len(body) < 30:
            continue
        risks.append({"number": int(match.group(1)), "text": body[:4000]})
    if not risks:
        # Fallback: split on bullet-like markers
        chunks = re.split(r"\n\s*(?:•|\-|\*)\s+", risk_section)
        for idx, chunk in enumerate(chunks):
            body = _normalize_whitespace(chunk)
            if len(body) >= 40:
                risks.append({"number": idx + 1, "text": body[:4000]})
    return risks


def extract_objects_split(objects_section: str) -> dict[str, Any]:
    """Extract fresh issue vs OFS split and utilization breakdown."""
    text = objects_section or ""
    lower = text.lower()
    result: dict[str, Any] = {
        "fresh_issue_cr": None,
        "ofs_cr": None,
        "total_issue_cr": None,
        "ofs_pct": None,
        "utilization": [],
        "flags": [],
    }

    fresh_match = re.search(
        r"fresh\s+issue[^₹rs.\d]{0,40}(?:rs\.?\s*)?(?:₹\s*)?([\d,]+(?:\.\d+)?)\s*(crore|cr\.?|lakh|million)?",
        lower,
        flags=re.IGNORECASE,
    )
    ofs_match = re.search(
        r"(?:offer for sale|ofs)[^₹rs.\d]{0,40}(?:rs\.?\s*)?(?:₹\s*)?([\d,]+(?:\.\d+)?)\s*(crore|cr\.?|lakh|million)?",
        lower,
        flags=re.IGNORECASE,
    )

    def _to_cr(value: str, unit: str | None) -> float:
        num = float(value.replace(",", ""))
        unit = (unit or "crore").lower()
        if "lakh" in unit:
            return num / 100.0
        if "million" in unit:
            return num / 10.0
        return num

    if fresh_match:
        result["fresh_issue_cr"] = _to_cr(fresh_match.group(1), fresh_match.group(2))
    if ofs_match:
        result["ofs_cr"] = _to_cr(ofs_match.group(1), ofs_match.group(2))

    if result["fresh_issue_cr"] is not None and result["ofs_cr"] is not None:
        total = result["fresh_issue_cr"] + result["ofs_cr"]
        result["total_issue_cr"] = total
        if total > 0:
            result["ofs_pct"] = round(100.0 * result["ofs_cr"] / total, 1)

    utilization_keywords = {
        "debt_repayment": ("repayment of borrowings", "repayment of debt", "debt repayment", "loan repayment"),
        "capex": ("capital expenditure", "capex", "plant and machinery", "expansion"),
        "acquisition": ("acquisition", "inorganic growth"),
        "general_corporate": ("general corporate purposes", "gcp", "working capital"),
        "marketing": ("marketing", "brand building", "advertisement"),
    }
    for key, phrases in utilization_keywords.items():
        for phrase in phrases:
            match = re.search(
                rf"{re.escape(phrase)}[^₹rs.\d]{{0,60}}(?:₹\s*)?([\d,]+(?:\.\d+)?)\s*(crore|cr\.?|lakh)?",
                lower,
                flags=re.IGNORECASE,
            )
            if match:
                result["utilization"].append(
                    {
                        "category": key,
                        "label": phrase.title(),
                        "amount_cr": _to_cr(match.group(1), match.group(2)),
                    }
                )
                break

    if result.get("ofs_pct") and result["ofs_pct"] >= 60:
        result["flags"].append("high_ofs_exit_signal")
    debt_pct = 0.0
    fresh = result.get("fresh_issue_cr") or 0.0
    if fresh > 0:
        debt_total = sum(u["amount_cr"] for u in result["utilization"] if u["category"] == "debt_repayment")
        debt_pct = 100.0 * debt_total / fresh
        if debt_pct >= 40:
            result["flags"].append("high_debt_repayment_allocation")
    gcp_total = sum(u["amount_cr"] for u in result["utilization"] if u["category"] == "general_corporate")
    if fresh > 0 and 100.0 * gcp_total / fresh >= 60:
        result["flags"].append("high_gcp_allocation")

    return result


def extract_promoters(promoters_section: str, legal_section: str = "") -> dict[str, Any]:
    """Extract promoter names and litigation disclosures."""
    text = promoters_section or ""
    legal_text = legal_section or ""
    promoters: list[dict[str, str]] = []
    for match in re.finditer(r"(?:Mr\.|Ms\.|Mrs\.|Dr\.|Shri\.|Smt\.)\s+[A-Z][A-Za-z.\s]{2,40}", text):
        name = _normalize_whitespace(match.group(0))
        if name not in {p["name"] for p in promoters}:
            promoters.append({"name": name})

    litigation_snippets: list[str] = []
    for match in re.finditer(r"(?i)(sebi|sat|high court|supreme court|criminal|regulatory).{0,300}", legal_text):
        snippet = _normalize_whitespace(match.group(0))
        if len(snippet) > 40:
            litigation_snippets.append(snippet[:500])

    return {
        "promoters": promoters[:20],
        "litigation_count": len(litigation_snippets),
        "litigation_snippets": litigation_snippets[:10],
    }


def extract_kpis(kpi_section: str) -> list[dict[str, Any]]:
    """Extract KPI rows with YoY trend hints."""
    if not kpi_section:
        return []
    kpis: list[dict[str, Any]] = []
    rows = re.findall(r"([A-Za-z][A-Za-z0-9 /%-]{2,50})\s+([\d,]+(?:\.\d+)?%?)\s+([\d,]+(?:\.\d+)?%?)", kpi_section)
    for label, current, prior in rows[:30]:
        try:
            cur_val = float(current.replace(",", "").replace("%", ""))
            prior_val = float(prior.replace(",", "").replace("%", ""))
            trend = "stable"
            if prior_val != 0:
                change = 100.0 * (cur_val - prior_val) / abs(prior_val)
                if change <= -5:
                    trend = "deteriorating"
                elif change >= 5:
                    trend = "improving"
            kpis.append({"label": label.strip(), "current": current, "prior": prior, "trend": trend})
        except ValueError:
            continue
    return kpis


def extract_peer_table(peer_section: str) -> list[dict[str, Any]]:
    """Extract peer comparison table rows from markdown/HTML tables."""
    if not peer_section:
        return []
    peers: list[dict[str, Any]] = []
    lines = [line.strip() for line in peer_section.splitlines() if "|" in line]
    if len(lines) < 2:
        return peers
    headers = [cell.strip().lower() for cell in lines[0].strip("|").split("|")]
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        row = dict(zip(headers, cells))
        company = row.get("company") or row.get("name") or row.get("particulars") or cells[0]
        peers.append(
            {
                "company": company,
                "pe": _safe_float(row.get("p/e") or row.get("pe") or row.get("price earnings")),
                "ev_ebitda": _safe_float(row.get("ev/ebitda") or row.get("ev ebitda")),
                "price_sales": _safe_float(row.get("p/s") or row.get("price/sales")),
                "roe": _safe_float(row.get("roe") or row.get("return on equity")),
            }
        )
    return peers


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("x", "").strip())
    except ValueError:
        return None


def parse_drhp_markdown(markdown: str) -> dict[str, Any]:
    """Full DRHP parse pipeline returning structured extraction payload."""
    parsed = extract_sections(markdown)
    sections = parsed.sections
    risk_section = sections["risk_factors"].text
    objects_section = sections["objects_of_issue"].text
    financial_section = sections["financial_information"].text
    promoters_section = sections["promoters"].text
    legal_section = sections["legal_proceedings"].text
    kpi_section = sections["kpis"].text
    peer_section = sections["peer_comparison"].text
    business_section = sections["business_overview"].text

    from finagent.ingestion.financial_table_extractor import extract_restated_financials
    from finagent.ingestion.ipo_score_engine import classify_risks, detect_sme_fraud_signals

    financials = extract_restated_financials(financial_section)
    risks = extract_numbered_risks(risk_section)
    classified_risks = classify_risks(risks)
    objects = extract_objects_split(objects_section)
    promoters = extract_promoters(promoters_section, legal_section)
    kpis = extract_kpis(kpi_section)
    peers = extract_peer_table(peer_section)
    fraud_signals = detect_sme_fraud_signals(
        promoters=promoters,
        objects=objects,
        financials=financials,
        related_party_section=sections["related_party"].text,
        full_text=parsed.full_text,
    )

    return {
        "sections_present": {name: sec.present for name, sec in sections.items()},
        "business_overview_excerpt": business_section[:2500],
        "financials": financials,
        "objects_of_issue": objects,
        "risk_factors": classified_risks,
        "promoters": promoters,
        "kpis": kpis,
        "peers": peers,
        "fraud_signals": fraud_signals,
    }

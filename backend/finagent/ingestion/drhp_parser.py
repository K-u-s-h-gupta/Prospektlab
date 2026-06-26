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
        "description of business",
    ),
    "objects_of_issue": (
        "objects of the issue",
        "objects of this issue",
        "objects of the offer",
        "use of proceeds",
        "issue proceeds",
        "utilisation of net proceeds",
    ),
    "risk_factors": ("risk factors", "risk factor"),
    "financial_information": (
        "financial information",
        "restated financial information",
        "restated consolidated financial information",
        "restated standalone financial information",
        "summary of restated consolidated financial information",
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
        "details of the promoters",
    ),
    "management": (
        "our management",
        "board of directors",
        "key managerial personnel",
        "directors and key managerial personnel",
        "our board of directors",
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
        "material litigation",
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
        "comparison with listed industry peers",
    ),
    "issue_details": (
        "terms of the issue",
        "details of the issue",
        "issue structure",
        "the offer",
    ),
    "strengths": (
        "our strengths",
        "competitive strengths",
        "our competitive strengths",
        "key strengths",
    ),
    "strategies": (
        "our strategies",
        "business strategies",
        "our business strategies",
        "growth strategies",
    ),
}

_SECTION_ALIAS_SCORE_BONUS: dict[str, dict[str, int]] = {
    "business_overview": {
        "our business": 18,
        "business of the company": 14,
        "about the company": 12,
        "description of business": 12,
        "business overview": 8,
        "industry overview": -12,
    },
    "financial_information": {
        "restated consolidated financial information": 24,
        "restated standalone financial information": 20,
        "summary of restated consolidated financial information": 18,
        "restated financial information": 20,
        "summary financial information": 14,
        "selected financial information": 10,
        "financial information": 6,
        "financial statements": -18,
    },
    "kpis": {
        "basis for issue price": 10,
        "key performance indicators": 6,
        "key performance indicator": 4,
    },
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


def _digit_ratio(text: str) -> float:
    cleaned = text or ""
    if not cleaned:
        return 0.0
    digits = sum(1 for char in cleaned if char.isdigit())
    return digits / max(len(cleaned), 1)


def _looks_like_toc_line(line: str) -> bool:
    stripped = (line or "").strip()
    if not stripped:
        return False
    dotted = "." * 4 in stripped or re.search(r"\.{4,}\s*\d{1,4}\s*$", stripped)
    return bool(dotted)


def _is_headingish_line(line: str) -> bool:
    stripped = _normalize_whitespace(line)
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered in _ALIAS_TO_SECTION:
        return True
    if len(stripped) <= 120 and stripped == stripped.upper() and sum(ch.isalpha() for ch in stripped) >= 4:
        return True
    return False


def _is_noisy_copy(text: str) -> bool:
    cleaned = _normalize_whitespace(text)
    if len(cleaned) < 25:
        return True
    if _looks_like_toc_line(cleaned):
        return True
    if cleaned.lower().startswith("## page"):
        return True
    if "| ---" in cleaned or cleaned.count("|") >= 4:
        return True
    if _digit_ratio(cleaned) >= 0.35 and len(cleaned) < 120:
        return True
    # Reject lines that look like financial table rows (label followed immediately by numbers)
    # e.g. "Secured Hypothecation Loans 0.15 28.56" or "Total Capital 14,262.45 13,976.85"
    if re.match(r"^[A-Za-z\s/()&-]{4,60}\s+[\d,]+\.\d{2}\s+[\d,]+\.\d{2}", cleaned):
        return True
    # Reject lines starting with a number (table data cell)
    if re.match(r"^\d[\d,]*\.?\d*\s+\d[\d,]*\.?\d*", cleaned):
        return True
    return False


def _fix_encoding_artifacts(text: str) -> str:
    """Fix common UTF-8 mojibake patterns from PDF extraction."""
    # Indian Rupee (U+20B9) encoded as Latin-1 -> a\xe2\x82\xb9
    text = text.replace("\xe2\x82\xb9", "\u20b9")
    text = text.replace("a\u20ac\u00b9", "\u20b9")
    # Right single quote (U+2019) mojibake
    text = text.replace("\xe2\x80\x99", "\u2019")
    text = text.replace("a\u20ac\u2122", "'")
    # Left single quote (U+2018)
    text = text.replace("\xe2\x80\x98", "\u2018")
    text = text.replace("a\u20ac\u02dc", "'")
    # Right double quote (U+201D)
    text = text.replace("\xe2\x80\x9d", "\u201d")
    # Left double quote (U+201C)
    text = text.replace("\xe2\x80\x9c", "\u201c")
    # Em dash (U+2014)
    text = text.replace("\xe2\x80\x94", "\u2014")
    # En dash (U+2013)
    text = text.replace("\xe2\x80\x93", "\u2013")
    # Generic â?? replacement character sequences from broken UTF-8
    text = re.sub(r"â\?+", "'", text)
    text = re.sub(r"â\u20ac[\u02dc\u2122\u0153\u017e\u0178]", "'", text)
    # Unicode replacement character
    text = text.replace("\ufffd", "'")
    # Normalize smart quotes to ASCII equivalents for display
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u20b9", "\u20b9")  # keep rupee symbol
    return text


def _clean_copy(text: str, *, max_chars: int = 0) -> str:
    cleaned = _fix_encoding_artifacts(text or "")
    cleaned = cleaned.replace("\r", "\n")
    cleaned = re.sub(r"^## Page \d+\s*$", "", cleaned, flags=re.MULTILINE)
    lines = []
    for raw_line in cleaned.splitlines():
        line = _normalize_whitespace(raw_line)
        if not line or _looks_like_toc_line(line):
            continue
        lines.append(line)
    cleaned = _normalize_whitespace(" ".join(lines))
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    if max_chars and len(cleaned) > max_chars:
        clipped = cleaned[: max_chars + 1]
        last_space = clipped.rfind(" ")
        cleaned = clipped[:last_space] if last_space > 0 else clipped[:max_chars]
        cleaned = cleaned.rstrip(" ,;:") + "..."
    return cleaned


def _split_markdown_pages(markdown: str) -> list[tuple[int, str]]:
    if "## Page " not in markdown:
        return [(1, markdown)] if markdown.strip() else []

    pages: list[tuple[int, str]] = []
    chunks = re.split(r"(?=^## Page \d+\s*$)", markdown, flags=re.MULTILINE)
    for chunk in chunks:
        match = re.match(r"^## Page (\d+)\s*$", chunk.strip().splitlines()[0] if chunk.strip() else "")
        if not match:
            continue
        page_number = int(match.group(1))
        lines = chunk.splitlines()[1:]
        pages.append((page_number, "\n".join(lines).strip()))
    return pages


def _page_looks_like_toc(page_text: str) -> bool:
    lines = [line.strip() for line in (page_text or "").splitlines() if line.strip()][:120]
    if not lines:
        return False
    toc_lines = sum(1 for line in lines if _looks_like_toc_line(line))
    alias_hits = 0
    for line in lines:
        lowered = line.lower()
        if any(alias in lowered for alias in _ALIAS_TO_SECTION):
            alias_hits += 1
    return toc_lines >= 3 or (toc_lines >= 2 and alias_hits >= 4)


def _prepare_text_for_parsing(markdown: str) -> str:
    pages = _split_markdown_pages(markdown)
    if not pages:
        return markdown or ""

    retained_pages: list[str] = []
    for page_number, page_text in pages:
        if _page_looks_like_toc(page_text):
            continue
        cleaned = page_text.strip()
        if cleaned:
            retained_pages.append(f"## Page {page_number}\n\n{cleaned}")
    return "\n\n".join(retained_pages) if retained_pages else (markdown or "")


def _extract_clean_paragraphs(section_text: str, *, limit: int = 3, min_chars: int = 80) -> list[str]:
    working = (section_text or "").replace("\r", "\n")
    working = re.sub(r"^## Page \d+\s*$", "", working, flags=re.MULTILINE)

    paragraphs: list[str] = []
    current_lines: list[str] = []
    for raw_line in working.splitlines():
        line = _normalize_whitespace(raw_line)
        if not line:
            if current_lines:
                paragraph = _clean_copy(" ".join(current_lines))
                if paragraph and not _is_noisy_copy(paragraph) and len(paragraph) >= min_chars:
                    paragraphs.append(paragraph)
                current_lines = []
            continue
        if _looks_like_toc_line(line) or _is_headingish_line(line):
            if current_lines:
                paragraph = _clean_copy(" ".join(current_lines))
                if paragraph and not _is_noisy_copy(paragraph) and len(paragraph) >= min_chars:
                    paragraphs.append(paragraph)
                current_lines = []
            continue
        current_lines.append(line)

    if current_lines:
        paragraph = _clean_copy(" ".join(current_lines))
        if paragraph and not _is_noisy_copy(paragraph) and len(paragraph) >= min_chars:
            paragraphs.append(paragraph)

    deduped: list[str] = []
    seen: set[str] = set()
    for paragraph in paragraphs:
        key = paragraph.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(paragraph)
        if len(deduped) >= limit:
            break
    return deduped


def _extract_clean_list_items(section_text: str, *, limit: int = 8) -> list[str]:
    text = (section_text or "").replace("\r", "\n")
    text = re.sub(r"^## Page \d+\s*$", "", text, flags=re.MULTILINE)
    chunks = re.split(r"(?:^|\n)\s*(?:\d{1,2}[\.)]|[•*-])\s+", text, flags=re.MULTILINE)

    items: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        candidate = _clean_copy(chunk, max_chars=420)
        if not candidate or _is_noisy_copy(candidate):
            continue
        if len(candidate) < 35:
            continue
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(candidate)
        if len(items) >= limit:
            return items

    if not items:
        for paragraph in _extract_clean_paragraphs(section_text, limit=limit, min_chars=50):
            key = paragraph.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(paragraph)
            if len(items) >= limit:
                break
    return items


def _is_business_boilerplate(paragraph: str) -> bool:
    lowered = (paragraph or "").lower()
    boilerplate_tokens = (
        "forward-looking statements",
        "our fiscal year ends",
        "unless the context otherwise requires",
        "industry and market data used in this section",
        "technopak report",
        "copy of the technopak report",
        "references to our company",
        "relevant calendar year",
    )
    return any(token in lowered for token in boilerplate_tokens)


# Pre-compile a single combined regex for all section aliases
_COMBINED_SECTION_PATTERN = None

def _get_combined_pattern() -> re.Pattern:
    """Build and cache a combined regex pattern for all section aliases."""
    global _COMBINED_SECTION_PATTERN
    if _COMBINED_SECTION_PATTERN is not None:
        return _COMBINED_SECTION_PATTERN
    
    # Build pattern: (alias1|alias2|...) with word boundaries
    all_aliases = []
    for section_name, aliases in DRHP_SECTION_ALIASES.items():
        for alias in aliases:
            all_aliases.append(re.escape(alias))
    
    # Sort by length descending so longer matches are preferred
    all_aliases.sort(key=len, reverse=True)
    
    pattern_str = r"(?<![a-z0-9])(" + "|".join(all_aliases) + r")(?![a-z0-9])"
    _COMBINED_SECTION_PATTERN = re.compile(pattern_str, re.IGNORECASE)
    return _COMBINED_SECTION_PATTERN


# Build reverse lookup: alias -> section_name
_ALIAS_TO_SECTION: dict[str, str] = {}
for _section_name, _aliases in DRHP_SECTION_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_TO_SECTION[_alias.lower()] = _section_name


def _find_section_starts_fast(text: str) -> list[tuple[int, str, str]]:
    """Find section start positions using a single combined regex (FAST version).
    
    Instead of running 15+ separate regex searches, runs ONE search with all
    patterns combined. Provides 10-20x speedup on large documents.
    """
    pattern = _get_combined_pattern()

    def _candidate_score(match_start: int, match_end: int, section_name: str, alias: str) -> int:
        line_start = text.rfind("\n", 0, match_start) + 1
        line_end = text.find("\n", match_end)
        if line_end == -1:
            line_end = len(text)
        line = text[line_start:line_end].strip()
        lowered = line.lower()

        score = 0
        if _looks_like_toc_line(line):
            score -= 30
        if lowered.startswith(alias):
            score += 8
        if _normalize_whitespace(re.sub(r"[^a-z ]", " ", lowered)) == alias:
            score += 10
        if len(line) <= max(120, len(alias) + 24):
            score += 4
        if match_start - line_start <= 4:
            score += 4
        if line == line.upper() and sum(ch.isalpha() for ch in line) >= 4:
            score += 2
        if _digit_ratio(line) >= 0.25:
            score -= 6
        if len(line) > 180:
            score -= 6
        score += _SECTION_ALIAS_SCORE_BONUS.get(section_name, {}).get(alias, 0)
        return score

    # Find all matches in one pass
    section_hits: dict[str, tuple[int, str, int]] = {}  # section_name -> (position, alias, score)

    for match in pattern.finditer(text):
        alias = match.group(1).lower()
        section_name = _ALIAS_TO_SECTION.get(alias)
        if section_name:
            pos = match.start()
            score = _candidate_score(match.start(), match.end(), section_name, alias)
            current = section_hits.get(section_name)
            if current is None or score > current[2] or (score == current[2] and pos < current[0]):
                section_hits[section_name] = (pos, alias, score)

    # Convert to sorted list
    hits = [(pos, name, alias) for name, (pos, alias, _score) in section_hits.items()]
    hits.sort(key=lambda item: item[0])
    return hits


def _find_section_starts(text: str) -> list[tuple[int, str, str]]:
    """Find section start positions in text (original sequential version)."""
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


def _find_section_for_name(lower_text: str, section_name: str, aliases: tuple[str, ...]) -> tuple[int, str, str] | None:
    """Find best match for a single section name (worker function for parallel search)."""
    best_pos: int | None = None
    best_alias = ""
    for alias in aliases:
        pattern = re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", re.IGNORECASE)
        match = pattern.search(lower_text)
        if match and (best_pos is None or match.start() < best_pos):
            best_pos = match.start()
            best_alias = alias
    if best_pos is not None:
        return (best_pos, section_name, best_alias)
    return None


async def _find_section_starts_parallel(text: str) -> list[tuple[int, str, str]]:
    """Find section start positions using parallel regex search.
    
    Runs each section pattern search in a separate thread for ~2-3x speedup
    on large documents.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    
    # Lowercase once (this is the expensive part - ~0.3s for 800KB)
    lower = text.lower()
    
    # Use a dedicated thread pool with more workers
    def search_section(args):
        section_name, aliases = args
        return _find_section_for_name(lower, section_name, aliases)
    
    # Run all searches in parallel using process pool for true parallelism
    # (threads don't help due to GIL, but processes do)
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor(max_workers=16) as pool:
        tasks = [
            (section_name, aliases)
            for section_name, aliases in DRHP_SECTION_ALIASES.items()
        ]
        results = list(pool.map(search_section, tasks))
    
    # Filter None results and sort
    hits = [r for r in results if r is not None]
    hits.sort(key=lambda item: item[0])
    return hits


def extract_sections(markdown: str, *, max_section_chars: int = 120_000) -> ParsedDrhp:
    """Detect DRHP section boundaries from markdown text (optimized)."""
    text = _prepare_text_for_parsing(markdown or "")
    if not text.strip():
        return ParsedDrhp(full_text="", sections={})

    # Use fast combined regex search
    positions = _find_section_starts_fast(text)
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


async def extract_sections_parallel(markdown: str, *, max_section_chars: int = 120_000) -> ParsedDrhp:
    """Detect DRHP section boundaries (async version, uses fast combined regex).
    
    Note: The fast combined regex is already very efficient (~0.05s for 800KB),
    so the async wrapper is mainly for API consistency.
    """
    text = _prepare_text_for_parsing(markdown or "")
    if not text.strip():
        return ParsedDrhp(full_text="", sections={})

    # Use fast combined regex search (already optimized, no need for threading)
    positions = _find_section_starts_fast(text)
    
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
    generic_disclaimers = (
        "must rely on their own examination",
        "not been recommended or approved by the securities and exchange board of india",
        "specific attention of the investors is invited",
        "company's and selling shareholders' absolute responsibility",
        "you should read this red herring prospectus carefully",
    )

    def _accept_risk(body: str) -> bool:
        cleaned = _clean_copy(body, max_chars=1200)
        lowered = cleaned.lower()
        if len(cleaned) < 50 or _is_noisy_copy(cleaned):
            return False
        if any(token in lowered for token in generic_disclaimers):
            return False
        return True

    pattern = re.compile(
        r"(?:^|\n)\s*(\d{1,3})[\.\)]\s+(.+?)(?=(?:\n\s*\d{1,3}[\.\)]\s+)|\Z)",
        re.DOTALL,
    )
    for match in pattern.finditer(risk_section):
        body = _clean_copy(match.group(2), max_chars=1200)
        if not _accept_risk(body):
            continue
        risks.append({"number": int(match.group(1)), "text": body})
    if not risks:
        # Fallback: split on bullet-like markers
        chunks = re.split(r"\n\s*(?:•|\-|\*)\s+", risk_section)
        for idx, chunk in enumerate(chunks):
            body = _clean_copy(chunk, max_chars=1200)
            if _accept_risk(body):
                risks.append({"number": idx + 1, "text": body})
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

    def _to_cr(value: str, unit: str | None) -> float | None:
        cleaned = str(value or "").replace(",", "").strip()
        if not cleaned:
            return None
        try:
            num = float(cleaned)
        except ValueError:
            return None
        # Reject year-like numbers (2018–2030 range) — these are dates, not amounts
        if 2010 <= num <= 2035:
            return None
        unit = (unit or "crore").lower()
        if "lakh" in unit:
            return round(num / 100.0, 2)
        if "million" in unit:
            return round(num / 10.0, 2)
        return num

    def _extract_amount(text_lower: str, keyword_pattern: str) -> float | None:
        """Extract a crore-normalised amount following a keyword pattern."""
        pattern = re.compile(
            rf"{keyword_pattern}"
            r"[^0-9₹]{0,100}?"          # skip non-numeric chars (up to 100)
            r"(?:₹|rs\.?\s*|inr\s*)?"   # optional currency symbol
            r"([\d,]+(?:\.\d+)?)"        # amount  (group 1)
            r"\s*"
            r"(crore|cr\.?|lakh|lakhs?|million|mn\.?)?",  # unit (group 2)
            re.IGNORECASE,
        )
        m = pattern.search(text_lower)
        if not m:
            return None
        val = _to_cr(m.group(1), m.group(2))
        if val is None or not (0.5 <= val <= 100_000):
            return None
        return val

    fresh_val  = _extract_amount(lower, r"fresh\s+issue")
    ofs_val    = _extract_amount(lower, r"(?:offer\s+for\s+sale|ofs)")
    total_val  = _extract_amount(lower, r"(?:total\s+(?:issue\s+size|offer\s+size)|issue\s+size)")

    if fresh_val is not None:
        result["fresh_issue_cr"] = fresh_val
    if ofs_val is not None:
        result["ofs_cr"] = ofs_val
    if total_val is not None:
        result["total_issue_cr"] = total_val

    if result["fresh_issue_cr"] is not None and result["ofs_cr"] is not None:
        total = result["fresh_issue_cr"] + result["ofs_cr"]
        if result["total_issue_cr"] is None:
            result["total_issue_cr"] = total
        if total > 0:
            result["ofs_pct"] = round(100.0 * result["ofs_cr"] / total, 1)
    elif result["total_issue_cr"] is not None and result["fresh_issue_cr"] is not None:
        ofs = result["total_issue_cr"] - result["fresh_issue_cr"]
        if ofs > 0:
            result["ofs_cr"] = ofs
            result["ofs_pct"] = round(100.0 * ofs / result["total_issue_cr"], 1)

    utilization_keywords = {
        "debt_repayment": ("repayment of borrowings", "repayment of debt", "debt repayment", "loan repayment"),
        "capex": ("capital expenditure", "capex", "plant and machinery", "expansion of", "new branches", "augmentation of capital"),
        "acquisition": ("acquisition", "inorganic growth"),
        "general_corporate": ("general corporate purposes", "gcp", "working capital"),
        "marketing": ("marketing", "brand building", "advertisement"),
    }
    seen_cats: set[str] = set()
    for key, phrases in utilization_keywords.items():
        if key in seen_cats:
            continue
        for phrase in phrases:
            amount_cr = _extract_amount(lower, re.escape(phrase))
            if amount_cr is None:
                continue
            fresh = result.get("fresh_issue_cr") or result.get("total_issue_cr") or 0
            if fresh > 0 and amount_cr > fresh * 1.15:
                # If amount is much larger than issue size, try treating as lakhs
                amount_lakh_to_cr = amount_cr / 100.0
                if amount_lakh_to_cr <= fresh * 1.15:
                    amount_cr = round(amount_lakh_to_cr, 2)
                else:
                    continue  # Still too large — reject
            result["utilization"].append({
                "category": key,
                "label": phrase.title(),
                "amount_cr": amount_cr,
            })
            seen_cats.add(key)
            break

    # NBFC-specific: augmentation of capital base as capex equivalent
    if not result["utilization"] and ("augmentation" in lower or "capital base" in lower):
        fresh = result.get("fresh_issue_cr") or result.get("total_issue_cr")
        if fresh:
            result["utilization"].append({
                "category": "capex",
                "label": "Augmentation of Capital Base",
                "amount_cr": fresh,
            })

    if result.get("ofs_pct") and result["ofs_pct"] >= 60:
        result["flags"].append("high_ofs_exit_signal")
    fresh = result.get("fresh_issue_cr") or 0.0
    if fresh > 0:
        debt_total = sum(u["amount_cr"] for u in result["utilization"] if u["category"] == "debt_repayment")
        if fresh > 0 and 100.0 * debt_total / fresh >= 40:
            result["flags"].append("high_debt_repayment_allocation")
    gcp_total = sum(u["amount_cr"] for u in result["utilization"] if u["category"] == "general_corporate")
    if fresh > 0 and 100.0 * gcp_total / fresh >= 60:
        result["flags"].append("high_gcp_allocation")

    return result


def extract_management(management_section: str, full_text: str = "") -> list[dict[str, Any]]:
    """Extract board of directors and key managerial personnel.
    
    Strategy:
    1. Find the LAST 'OUR MANAGEMENT' / 'Board of Directors' section in full_text
       (last occurrence = actual chapter, not cover page reference)
    2. Parse the DIN-based director profile table (SEBI standard format)
    3. Fall back to titled-name + designation regex scan
    """
    management: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    def _add_person(name: str, desig: str, experience: str | None = None) -> None:
        name = _normalize_whitespace(name).strip(" .,")
        # Truncate at transition words
        for stopper in (" is ", " who ", " has ", " was ", " are ", " din:", "\ndin:", "\nDin:"):
            idx = name.lower().find(stopper)
            if idx > 3:
                name = name[:idx]
        name = re.sub(r"\s+DIN.*$", "", name, flags=re.IGNORECASE).strip(" .,")
        if not name or len(name) < 3:
            return
        key = name.lower()
        if key in seen_names:
            return
        if any(tok in key for tok in ("university", "limited", "ltd.", "llp", "institute", "college", "page ")):
            return
        seen_names.add(key)
        management.append({
            "name": name,
            "designation": desig.strip().title() if desig else "Director",
            "experience": _clean_copy(experience, max_chars=140) if experience else None,
        })

    # Try to use the full document text first — find the LAST occurrence of management section
    search_text = full_text if full_text else management_section
    
    # Strategy 1: Find the actual management chapter using LAST occurrence
    # SEBI prospectuses have "OUR MANAGEMENT" in ToC/cover AND in the actual chapter
    # Do NOT use exact newline matching — headings may have different whitespace
    actual_mgmt_text = ""
    for heading in ["OUR MANAGEMENT", "Our Management", "BOARD OF DIRECTORS",
                     "Board of Directors", "DIRECTORS AND KEY MANAGERIAL", "Directors and Key Managerial"]:
        idx = search_text.rfind(heading)
        if idx != -1:
            candidate = search_text[idx: idx + 80000]
            # Verify this is the actual chapter (has DIN or designation content)
            if re.search(r"DIN[:\s]*\d{8}", candidate, re.IGNORECASE):
                actual_mgmt_text = candidate
                break


    working_text = actual_mgmt_text if actual_mgmt_text else management_section

    # Strategy 2: Parse DIN-based director profile cells in pipe tables
    # SEBI format: table cell with "Name DIN: XXXXXXXX Designation: ..."
    din_pattern = re.compile(
        r"([A-Z][A-Za-z\s.]{2,40}?)\s+DIN[:\s]+(\d{8})\s*(?:\n|Designation[:\s]+|\.?\s+)",
        re.IGNORECASE,
    )
    for match in din_pattern.finditer(working_text):
        name_raw = _normalize_whitespace(match.group(1)).strip()
        # Look ahead for designation
        context = working_text[match.start(): match.start() + 500]
        desig_match = re.search(
            r"Designation[:\s]+([A-Za-z\s&/,.-]{5,60}?)(?:\n|Age[:\s]|Date|\.|$)",
            context, re.IGNORECASE,
        )
        desig = desig_match.group(1).strip() if desig_match else "Director"
        # Look for experience
        exp_match = re.search(r"(\d{1,2}\+?\s+years?\s+of\s+(?:experience|expertise)[^.]{0,100})", context, re.IGNORECASE)
        _add_person(name_raw, desig, exp_match.group(1) if exp_match else None)

    # Strategy 3: Titled name + designation regex
    designations = [
        "managing director & ceo", "managing director and ceo",
        "whole time director", "whole-time director",
        "non-executive independent director", "non-executive non-independent director",
        "independent director", "non-executive director", "executive director",
        "managing director", "joint managing director", "deputy managing director",
        "chief executive officer", "chief financial officer", "chief operating officer",
        "company secretary", "chairman & managing director", "chairman",
        "vice chairman", "director",
    ]
    desig_pattern_str = "|".join(re.escape(d) for d in sorted(designations, key=len, reverse=True))
    for match in re.finditer(
        rf"(?:Mr\.|Ms\.|Mrs\.|Dr\.|Shri\.|Smt\.)\s+([A-Z][A-Za-z.\s]{{2,35}}?)"
        rf"(?:[,\s]{{1,10}}(?:is\s+(?:an?\s+)?)?)?"
        rf"({desig_pattern_str})",
        working_text,
        re.IGNORECASE,
    ):
        name_raw = match.group(1)
        desig_raw = match.group(2)
        context = working_text[match.end(): match.end() + 250]
        exp_match = re.search(r"(\d{1,2}\+?\s+years?\s+of\s+(?:experience|expertise)[^.]{0,100})", context, re.IGNORECASE)
        prefix = working_text[match.start(): match.start() + 4]
        full_name = _normalize_whitespace(prefix + " " + name_raw)
        _add_person(full_name, desig_raw, exp_match.group(1) if exp_match else None)

    # Strategy 4: Pipe table with name | designation columns
    if not management:
        desig_keywords = {"director", "ceo", "cfo", "chairman", "officer", "secretary", "managing", "independent"}
        for line in working_text.splitlines():
            if "|" not in line:
                continue
            cells = [c.strip() for c in line.strip("|").split("|") if c.strip()]
            if len(cells) < 2:
                continue
            name_cell, desig_cell = cells[0], cells[1]
            if not re.search(r"[A-Z][a-z]", name_cell):
                continue
            if any(kw in desig_cell.lower() for kw in desig_keywords):
                _add_person(name_cell, desig_cell)

    # Strategy 5: Fallback — any titled name in working text
    if not management:
        for match in re.finditer(r"(?:Mr\.|Ms\.|Mrs\.|Dr\.|Shri\.|Smt\.)\s+([A-Z][A-Za-z.\s]{2,35})", working_text):
            raw = _normalize_whitespace(match.group(0))
            _add_person(raw, "Director")

    return management[:15]


def extract_promoters(promoters_section: str, legal_section: str = "", full_text: str = "") -> dict[str, Any]:
    """Extract promoter names and litigation disclosures."""
    # Find the best promoter section — use LAST occurrence of promoter chapter heading
    search_text = full_text if full_text else promoters_section
    
    actual_promo_text = ""
    # Search ALL occurrences (not just last) and find the one with shareholding data
    for heading in ["OUR PROMOTERS", "Our Promoters", "PROMOTERS AND PROMOTER GROUP",
                     "Promoters and Promoter Group", "DETAILS OF THE PROMOTERS",
                     "Details of the Promoters"]:
        start = 0
        while True:
            idx = search_text.find(heading, start)
            if idx == -1:
                break
            candidate = search_text[idx: idx + 60000]
            # Verify this section has ACTUAL promoter data (shareholding % near top)
            top_chunk = candidate[:5000]
            if re.search(r"(\d{1,3}(?:\.\d{1,2})?)\s*%\s*(?:of|paid|equity)", top_chunk, re.IGNORECASE):
                actual_promo_text = candidate
                break
            if re.search(r"(?:promoter.{0,30}hold|pre.issued)", top_chunk, re.IGNORECASE):
                actual_promo_text = candidate
                break
            start = idx + 1
        if actual_promo_text:
            break
    
    # Combine section text with found text  
    text = actual_promo_text if actual_promo_text else (promoters_section or "")
    legal_text = legal_section or ""
    promoters: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    def _add_promoter(name: str, shareholding: float | None = None) -> None:
        key = name.lower().strip()
        if not key or key in seen_names or len(name) < 4:
            return
        # Strong noise filter — these are not promoters
        noise_tokens = (
            "sebi", "rbi", "nse", "bse", "court", "tribunal", "registrar",
            "our company", "the issuer", "limited liability", "pursuant",
            "hereinafter", "registered office", "din:", "pan:", "secretary",
            "compliance officer", "auditor", "chartered accountant",
            "lead manager", "underwriter", "market maker", "banker", "legal advisor",
            "address:", "telephone:", "website:", "email:",
            "transfer agent", "depository", "broker",
        )
        if any(tok in key for tok in noise_tokens):
            return
        if re.search(r"\d{4,}", name):
            return
        if name[0].islower():  # starts with lowercase = partial fragment
            return
        if re.search(r"dated|central deposi|depository|period ended|financial year|board resol", key):
            return
        if re.search(r"\d{2,}[\.,]\d{2}", name):
            return
        seen_names.add(key)
        entry: dict[str, Any] = {"name": name.strip()}
        if shareholding is not None:
            entry["shareholding_pct"] = shareholding
        promoters.append(entry)

    # Pre-build KMP exclusion set from glossary (CFO, CS appear in cover before promoter section)
    # Extract named persons in non-promoter roles from cover page (first 80000 chars)
    kmp_exclusions: set[str] = set()
    cover_text = (full_text or text)[:80000]
    kmp_roles = ("chief financial officer", "company secretary", "compliance officer",
                 "lead manager", "registrar", "underwriter", "auditor", "legal advisor",
                 "statutory auditor", "chief financial")
    for role in kmp_roles:
        pattern = re.compile(
            rf"{re.escape(role)}[^.{{50}}]*?(?:Mr\.|Ms\.|Mrs\.|Dr\.)\s+([A-Z][A-Za-z\s]{{2,30}}?)(?:\n|,|\.|$)",
            re.IGNORECASE
        )
        for m in pattern.finditer(cover_text):
            kmp_exclusions.add(m.group(1).lower().strip())
        # Also check reverse: "Mr. X is the CFO"
        rev_pat = re.compile(
            rf"(?:Mr\.|Ms\.|Mrs\.|Dr\.)\s+([A-Z][A-Za-z\s]{{2,30}}?)\s+(?:is|being)\s+(?:the\s+)?(?:{'|'.join(re.escape(r) for r in kmp_roles)})",
            re.IGNORECASE
        )
        for m in rev_pat.finditer(cover_text):
            kmp_exclusions.add(m.group(1).lower().strip())

    def _is_kmp(name: str) -> bool:
        lname = name.lower()
        for excl in kmp_exclusions:
            if excl in lname or lname in excl:
                return True
        return False

    # Noise words that indicate this is not a promoter name
    _NAME_NOISE = re.compile(
        r"(?:issue|public issue|net issue|equity|face value|market|bse|nse|sebi|"
        r"constitution|article|section|chapter|page|clause|regulation|act\b)",
        re.IGNORECASE
    )

    # 1. Shareholding percentage with name — most reliable
    for match in re.finditer(
        rf"(?:Mr\.|Ms\.|Mrs\.|Dr\.|Shri\.|Smt\.)?\s*"
        rf"([A-Z][A-Za-z\s.{{}}]{{3,50}}?)\s+(?:holds?|hold|constituting|representing)\s+"
        rf"(?:\d[\d,]*\s+(?:equity\s+)?shares?\s+constituting\s+)?"
        rf"(\d{{1,3}}(?:\.\d{{1,4}})?)\s*%",
        text, re.IGNORECASE,
    ):
        raw_name = _normalize_whitespace(match.group(1))
        if _NAME_NOISE.search(raw_name):
            continue
        try:
            pct = float(match.group(2))
        except ValueError:
            continue
        if 0 < pct <= 100 and not _is_kmp(raw_name):
            _add_promoter(raw_name, pct)

    # 2. Individual promoters with title — only in the promoter chapter context
    # Limit to first 25000 chars of the promoter section to avoid drift into other chapters
    promo_core = text[:25000] if len(text) > 25000 else text
    for match in re.finditer(
        r"(?:Mr\.|Ms\.|Mrs\.|Dr\.|Shri\.|Smt\.)\s+([A-Z][A-Za-z]{1,20}(?:\s+[A-Z][A-Za-z]{1,20}){0,3})",
        promo_core,
    ):
        raw_name = _normalize_whitespace(match.group(0))
        if _is_kmp(raw_name):
            continue
        if _NAME_NOISE.search(raw_name):
            continue
        # Check if we already have this from shareholding pattern
        already = any(raw_name.lower() in p["name"].lower() for p in promoters)
        if not already:
            # Add only with shareholding from nearby context
            context = promo_core[match.start(): match.start() + 300]
            pct_m = re.search(r"(\d{1,3}(?:\.\d{1,4})?)\s*%", context)
            pct = float(pct_m.group(1)) if pct_m else None
            if pct and (pct <= 0 or pct > 100):
                pct = None
            _add_promoter(raw_name, pct)

    # 4. Corporate entity promoters
    for match in re.finditer(
        r"([A-Z][A-Za-z0-9 ,&.()]{3,60}?)\s+(?:Limited|Pvt\.?\s*Ltd\.?|LLP|Trust)",
        text, re.IGNORECASE,
    ):
        raw_name = _normalize_whitespace(match.group(0))
        if not re.search(r"\d{2,}[\.,]\d{2}", raw_name):
            already = any(raw_name.lower() in p["name"].lower() for p in promoters)
            if not already:
                _add_promoter(raw_name)

    # Litigation extraction
    litigation_snippets: list[str] = []
    litigation_keywords = (
        "litigation", "legal proceeding", "show cause", "criminal",
        "civil suit", "arbitration", "tax demand", "penalty", "complaint",
        "petition", "tribunal", "high court", "supreme court",
    )
    generic_legal_noise = ("sebi icdr regulations", "sebi listing regulations", "companies act", "page ")
    combined_legal = legal_text or text
    for paragraph in _extract_clean_paragraphs(combined_legal, limit=12, min_chars=50):
        lowered = paragraph.lower()
        if not any(keyword in lowered for keyword in litigation_keywords):
            continue
        if any(noise in lowered for noise in generic_legal_noise):
            continue
        if "there are no" in lowered and any(t in lowered for t in ("litigation", "criminal", "civil")):
            continue
        litigation_snippets.append(_clean_copy(paragraph, max_chars=420))

    return {
        "promoters": promoters[:20],
        "litigation_count": len(litigation_snippets),
        "litigation_snippets": litigation_snippets[:10],
    }





def extract_strengths_and_strategies(strengths_section: str, strategies_section: str) -> dict[str, list[str]]:
    """Extract company strengths and business strategies."""
    result: dict[str, list[str]] = {"strengths": [], "strategies": []}

    if strengths_section:
        result["strengths"] = _extract_clean_list_items(strengths_section, limit=8)
    if strategies_section:
        result["strategies"] = _extract_clean_list_items(strategies_section, limit=8)
    
    return result


def extract_kpi_rows(kpi_section: str) -> list[dict[str, Any]]:
    """Extract KPI rows with current/prior values from basis-for-issue-price tables."""
    if not kpi_section:
        return []

    alias_map = {
        "roe": "ROE",
        "return on equity": "ROE",
        "roce": "ROCE",
        "return on capital employed": "ROCE",
        "ebitda margin": "EBITDA Margin",
        "pat margin": "PAT Margin",
        "return on net worth": "RoNW",
        "ronw": "RoNW",
        "debt to equity": "Debt / Equity",
        "debt equity": "Debt / Equity",
        "earning per share": "EPS",
        "eps": "EPS",
        "price/earning": "P/E Ratio",
        "price earning": "P/E Ratio",
        "p/e": "P/E Ratio",
        "net asset value": "NAV",
        "nav": "NAV",
    }

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _trend_for_values(current: float, prior: float) -> str:
        if prior == 0:
            return "stable"
        change = 100.0 * (current - prior) / abs(prior)
        if change <= -5:
            return "deteriorating"
        if change >= 5:
            return "improving"
        return "stable"

    table_lines = [line.strip() for line in kpi_section.splitlines() if line.count("|") >= 2]
    for line in table_lines:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        # Check first 3 cells for label (handle leading empty columns in wide tables)
        matched_label = None
        label_idx = 0
        for ci in range(min(3, len(cells))):
            cell_text = cells[ci]
            if not cell_text:
                continue
            label = re.sub(r"\s*\([ivxlcdm]+\)\s*$", "", cell_text.lower()).strip()
            for alias, display_label in alias_map.items():
                if alias in label:
                    matched_label = display_label
                    label_idx = ci
                    break
            if matched_label:
                break
        if not matched_label or matched_label in seen:
            continue

        numeric_cells = [cell for cell in cells[label_idx + 1:] if re.search(r"\d", cell)]
        if len(numeric_cells) < 2:
            continue
        current_raw = numeric_cells[-1]
        prior_raw = numeric_cells[-2]
        try:
            current_val = float(re.sub(r"[^\d.-]", "", current_raw.replace("(", "-").replace(")", "")))
            prior_val = float(re.sub(r"[^\d.-]", "", prior_raw.replace("(", "-").replace(")", "")))
        except ValueError:
            continue
        rows.append(
            {
                "label": matched_label,
                "current": current_raw,
                "prior": prior_raw,
                "trend": _trend_for_values(current_val, prior_val),
            }
        )
        seen.add(matched_label)

    return rows


def extract_kpis(kpi_section: str) -> dict[str, Any]:
    """Extract normalized KPI values for detail-page display and valuation logic."""
    if not kpi_section:
        return {}

    value_map = {
        "roe": "roe_pct",
        "return on equity": "roe_pct",
        "roce": "roce_pct",
        "return on capital employed": "roce_pct",
        "ebitda margin": "ebitda_margin_pct",
        "pat margin": "pat_margin_pct",
        "return on net worth": "ronw_pct",
        "ronw": "ronw_pct",
        "debt to equity": "debt_equity_ratio",
        "debt equity": "debt_equity_ratio",
        "earning per share": "eps",
        "eps": "eps",
        "price/earning": "pe_ratio",
        "price earning": "pe_ratio",
        "p/e": "pe_ratio",
        "net asset value": "nav",
        "nav": "nav",
    }

    # Reasonable bounds for each field to reject extraction noise
    _BOUNDS: dict[str, tuple[float, float]] = {
        "roe_pct":          (-100.0, 200.0),
        "roce_pct":         (-100.0, 200.0),
        "ebitda_margin_pct":(-100.0, 100.0),
        "pat_margin_pct":   (-100.0, 100.0),
        "ronw_pct":         (-100.0, 200.0),
        "debt_equity_ratio":(0.0,    25.0),   # D/E > 25x is almost certainly wrong
        "eps":              (-10000.0, 100000.0),
        "pe_ratio":         (0.0,    2000.0),
        "nav":              (0.0,    100000.0),
    }

    result: dict[str, Any] = {}
    normalized_text = _clean_copy(kpi_section)

    for alias, field_name in value_map.items():
        if field_name in result:
            continue
        pattern = re.compile(
            rf"{re.escape(alias)}[^\d]{{0,40}}([\d,]+(?:\.\d+)?)\s*(%|x)?",
            re.IGNORECASE,
        )
        match = pattern.search(normalized_text)
        if not match:
            continue
        try:
            val = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        lo, hi = _BOUNDS.get(field_name, (-1e9, 1e9))
        if not (lo <= val <= hi):
            continue
        result[field_name] = val

    for row in extract_kpi_rows(kpi_section):
        label = row.get("label", "").lower()
        for alias, field_name in value_map.items():
            if alias in label and field_name not in result:
                try:
                    raw_val = float(re.sub(r"[^\d.-]", "", str(row.get("current") or "")))
                except ValueError:
                    break
                lo, hi = _BOUNDS.get(field_name, (-1e9, 1e9))
                if lo <= raw_val <= hi:
                    result[field_name] = raw_val
                break

    return result


def extract_peer_table(peer_section: str) -> list[dict[str, Any]]:
    """Extract peer comparison table from SEBI prospectus.
    
    SEBI peer table column format (standard):
    Company Name | CMP | Face Value | EPS | PE Ratio | RONW | NAV | Revenue
    
    Uses Face Value (always 1/2/5/10 in Indian stocks) as an anchor to
    locate PE = face_value_col + 2.
    Uses LAST occurrence of "Name of Company" to skip ToC/intro references.
    """
    if not peer_section:
        return []

    peers: list[dict[str, Any]] = []
    seen: set[str] = set()
    lines = (peer_section or "").splitlines()

    # Find the LAST anchor: line with "Name of Company" in a pipe table
    # (last occurrence = the actual table, not glossary/ToC mentions)
    anchor_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i]
        if "|" in line and re.search(r"name\s*of\s*(?:the\s+)?company|name\s+of\s+issuer", line, re.IGNORECASE):
            anchor_idx = i
            break

    if anchor_idx == -1:
        return []

    # Find separator row after anchor
    sep_idx = anchor_idx
    for j in range(anchor_idx, min(anchor_idx + 15, len(lines))):
        if re.match(r"\s*\|\s*[-:]+", lines[j]):
            sep_idx = j
            break

    # Standard Indian stock face values
    _FACE_VALUES = {0.5, 1.0, 2.0, 5.0, 10.0}

    # Process data rows after separator
    for line in lines[sep_idx + 1: sep_idx + 25]:
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        if all(not c or set(c.replace("-", "")) <= {""} for c in cells):
            continue

        # Find company name (first cell with substantial text)
        company = None
        for ci, cell in enumerate(cells):
            if cell and re.search(r"[A-Za-z]{3,}", cell) and not re.match(r"^[\d.*%-]+$", cell):
                if re.search(r"peer\s+industry|listed\s+peer|note:|source:|from\b|operations", cell, re.IGNORECASE):
                    continue
                company = cell
                break
        if not company:
            continue

        company_clean = _clean_copy(company, max_chars=120)
        lowered = company_clean.lower()
        if lowered in seen:
            continue
        if any(t in lowered for t in ("weighted average", "industry average", "median", "note", "source")):
            continue

        # Extract numeric values
        numeric_cells: list[tuple[int, float]] = []
        for ci, c in enumerate(cells):
            v = _safe_float(c.replace("*", "").replace("%", ""))
            if v is not None:
                numeric_cells.append((ci, v))

        if len(numeric_cells) < 3:
            continue

        # Locate PE using Face Value as anchor
        pe_val = None
        roe_val = None

        fv_idx = None
        for ni, (ci, v) in enumerate(numeric_cells):
            if v in _FACE_VALUES:
                fv_idx = ni
                break

        if fv_idx is not None:
            if fv_idx + 2 < len(numeric_cells):
                pe_candidate = numeric_cells[fv_idx + 2][1]
                if 1 < pe_candidate < 1000:
                    pe_val = pe_candidate
            if fv_idx + 3 < len(numeric_cells):
                roe_candidate = numeric_cells[fv_idx + 3][1]
                if -100 < roe_candidate < 200:
                    roe_val = roe_candidate

        # Fallback heuristic
        if pe_val is None:
            pe_candidates = [v for _, v in numeric_cells if 3 < v < 800]
            if len(pe_candidates) >= 3:
                pe_val = pe_candidates[2]
            elif pe_candidates:
                pe_val = pe_candidates[-1]

        if pe_val is None and roe_val is None:
            continue

        seen.add(lowered)
        peers.append({
            "company": company_clean,
            "pe": round(pe_val, 2) if pe_val else None,
            "ev_ebitda": None,
            "roe": round(roe_val, 2) if roe_val else None,
        })
        if len(peers) >= 15:
            break

    return peers


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("x", "").strip())
    except ValueError:
        return None


def generate_business_synthesis(
    business_section: str,
    objects: dict[str, Any],
    financials: dict[str, Any],
    strengths: list[str],
) -> str:
    """Generate a concise business synthesis from extracted sections."""
    paragraphs = [
        paragraph
        for paragraph in _extract_clean_paragraphs(business_section, limit=40, min_chars=70)
        if not _is_business_boilerplate(paragraph)
    ][:2]
    intro = paragraphs[0] if paragraphs else (strengths[0] if strengths else _clean_copy(business_section, max_chars=420))

    if not intro:
        return ""

    synthesis_parts = [intro]
    if len(paragraphs) > 1 and paragraphs[1].lower() != intro.lower():
        synthesis_parts.append(paragraphs[1])

    trends = financials.get("trends") or {}
    rev_cagr = trends.get("revenue_cagr_pct")
    pat_cagr = trends.get("pat_cagr_pct")

    if rev_cagr is not None or pat_cagr is not None:
        growth_note = "The company has shown "
        if rev_cagr is not None:
            growth_note += f"revenue CAGR of {rev_cagr}%"
            if pat_cagr is not None:
                growth_note += f" and PAT CAGR of {pat_cagr}%"
        elif pat_cagr is not None:
            growth_note += f"PAT CAGR of {pat_cagr}%"
        growth_note += " over the reported periods."
        synthesis_parts.append(growth_note)

    utilization = objects.get("utilization") or []
    if utilization:
        top_uses = ", ".join(item.get("label", "") for item in utilization[:2] if item.get("label"))
        if top_uses:
            synthesis_parts.append(f"The filing states that the fresh issue proceeds are primarily earmarked for {top_uses}.")

    if strengths and len(strengths) > 0:
        synthesis_parts.append(f"Key strength: {strengths[0]}")

    return " ".join(synthesis_parts)


def parse_drhp_markdown(markdown: str) -> dict[str, Any]:
    """Full DRHP parse pipeline returning structured extraction payload (sequential)."""
    parsed = extract_sections(markdown)
    sections = parsed.sections
    risk_section = sections["risk_factors"].text
    objects_section = sections["objects_of_issue"].text
    financial_section = sections["financial_information"].text
    promoters_section = sections["promoters"].text
    management_section = sections.get("management", DrhpSection("management", "", -1, -1, False)).text
    legal_section = sections["legal_proceedings"].text
    kpi_section = sections["kpis"].text
    peer_section = sections["peer_comparison"].text
    business_section = sections["business_overview"].text
    strengths_section = sections.get("strengths", DrhpSection("strengths", "", -1, -1, False)).text
    strategies_section = sections.get("strategies", DrhpSection("strategies", "", -1, -1, False)).text

    from finagent.ingestion.financial_table_extractor import extract_restated_financials
    from finagent.ingestion.ipo_score_engine import classify_risks, detect_sme_fraud_signals

    financials = extract_restated_financials(financial_section)
    risks = extract_numbered_risks(risk_section)
    classified_risks = classify_risks(risks)
    objects = extract_objects_split(objects_section)
    promoters = extract_promoters(promoters_section, legal_section)
    management = extract_management(management_section or promoters_section)
    kpi_rows = extract_kpi_rows(kpi_section)
    kpis = extract_kpis(kpi_section)
    peers = extract_peer_table(peer_section)
    strengths_strategies = extract_strengths_and_strategies(strengths_section, strategies_section)
    fraud_signals = detect_sme_fraud_signals(
        promoters=promoters,
        objects=objects,
        financials=financials,
        related_party_section=sections["related_party"].text,
        full_text=parsed.full_text,
    )
    
    # Generate business synthesis
    business_synthesis = generate_business_synthesis(
        business_section,
        objects,
        financials,
        strengths_strategies.get("strengths", []),
    )
    business_paragraphs = [
        paragraph
        for paragraph in _extract_clean_paragraphs(business_section, limit=40, min_chars=70)
        if not _is_business_boilerplate(paragraph)
    ][:3]
    if not business_paragraphs:
        fallback_paragraphs = [
            item for item in (
                strengths_strategies.get("strengths", [])[:1] + strengths_strategies.get("strategies", [])[:1]
            )
            if item
        ]
        business_paragraphs = fallback_paragraphs[:2]
    business_excerpt = "\n\n".join(business_paragraphs) if business_paragraphs else _clean_copy(business_section, max_chars=3000)

    return {
        "sections_present": {name: sec.present for name, sec in sections.items()},
        "business_synthesis": business_synthesis,
        "business_overview_excerpt": business_excerpt,
        "business_overview_paragraphs": business_paragraphs,
        "financials": financials,
        "objects_of_issue": objects,
        "risk_factors": classified_risks,
        "promoters": promoters,
        "management": management,
        "kpis": kpis,
        "kpi_rows": kpi_rows,
        "peers": peers,
        "strengths": strengths_strategies.get("strengths", []),
        "strategies": strengths_strategies.get("strategies", []),
        "fraud_signals": fraud_signals,
    }


async def parse_drhp_markdown_parallel(markdown: str) -> dict[str, Any]:
    """Full DRHP parse pipeline with PARALLEL section extraction.
    
    Runs all independent extractors concurrently using asyncio.gather() with
    thread pool execution. This can provide 3-6x speedup on multi-core systems.
    
    Pipeline:
    1. extract_sections() — must run first (identifies section boundaries)
    2. Parallel extraction of all sections (financials, risks, objects, etc.)
    3. Merge results and compute derived fields (fraud signals, synthesis)
    """
    import asyncio
    import time
    
    start_total = time.perf_counter()
    
    # Step 1: Extract section boundaries using PARALLEL regex search
    t0 = time.perf_counter()
    parsed = await extract_sections_parallel(markdown)
    sections = parsed.sections
    t_sections = time.perf_counter() - t0
    
    # Prepare section texts
    risk_section = sections["risk_factors"].text
    objects_section = sections["objects_of_issue"].text
    financial_section = sections["financial_information"].text
    promoters_section = sections["promoters"].text
    management_section = sections.get("management", DrhpSection("management", "", -1, -1, False)).text
    legal_section = sections["legal_proceedings"].text
    kpi_section = sections["kpis"].text
    peer_section = sections["peer_comparison"].text
    business_section = sections["business_overview"].text
    strengths_section = sections.get("strengths", DrhpSection("strengths", "", -1, -1, False)).text
    strategies_section = sections.get("strategies", DrhpSection("strategies", "", -1, -1, False)).text
    related_party_section = sections["related_party"].text
    
    # Import extractors
    from finagent.ingestion.financial_table_extractor import extract_restated_financials
    from finagent.ingestion.ipo_score_engine import classify_risks, detect_sme_fraud_signals
    
    # Full text for full-document scanning
    full_text = parsed.full_text or markdown

    # Step 2: Run ALL extractors in PARALLEL using thread pool
    t0 = time.perf_counter()
    
    # Define extraction tasks — all key extractors receive full_text for fallback scanning
    async def extract_financials():
        return await asyncio.to_thread(extract_restated_financials, financial_section, full_text)
    
    async def extract_risks_full():
        # Use the larger of risk_section or full text scan for risks
        text = risk_section if len(risk_section) > 5000 else full_text
        risks = await asyncio.to_thread(extract_numbered_risks, text)
        classified = await asyncio.to_thread(classify_risks, risks)
        return classified
    
    async def extract_objects():
        # Try objects section first, fall back to full text
        obj = await asyncio.to_thread(extract_objects_split, objects_section)
        if obj.get("fresh_issue_cr") is None and obj.get("ofs_cr") is None:
            obj = await asyncio.to_thread(extract_objects_split, full_text)
        return obj
    
    async def extract_promoters_full():
        return await asyncio.to_thread(extract_promoters, promoters_section, legal_section, full_text)
    
    async def extract_mgmt():
        return await asyncio.to_thread(extract_management, management_section or promoters_section, full_text)
    
    async def extract_kpis_section():
        # KPI data is in "Basis for Issue Price" / "Key Performance Indicators" section
        # Always search the full_text for the actual chapter using LAST occurrence
        kpis_text = kpi_section
        found_via_search = False
        for heading in ["BASIS FOR ISSUE PRICE", "Basis for Issue Price",
                         "KEY PERFORMANCE INDICATORS", "Key Performance Indicators",
                         "KPIs of our Company"]:
            idx = full_text.rfind(heading)
            if idx != -1:
                candidate = full_text[idx: idx + 30000]
                # Verify this section has actual KPI data
                from finagent.ingestion.financial_table_extractor import _YEAR_DATE_RE
                if _YEAR_DATE_RE.search(candidate):
                    kpis_text = candidate
                    found_via_search = True
                    break
        if not found_via_search and len(peer_section) > 5000:
            kpis_text = peer_section
        kpis_val = extract_kpis(kpis_text)
        kpi_rows_val = extract_kpi_rows(kpis_text)
        return {"kpis": kpis_val, "kpi_rows": kpi_rows_val}

    async def extract_peers():
        # Find actual peer comparison chapter using LAST occurrence
        result: list = []
        for heading in ["COMPARISON WITH LISTED PEERS", "Comparison with Listed Peers",
                         "PEER COMPARISON", "Basis for Issue Price", "BASIS FOR ISSUE PRICE"]:
            idx = full_text.rfind(heading)
            if idx != -1:
                peer_chunk = full_text[idx: idx + 40000]
                result = await asyncio.to_thread(extract_peer_table, peer_chunk)
                if result:
                    break
        if not result:
            result = await asyncio.to_thread(extract_peer_table, peer_section)
        return result
    
    async def extract_str_strat():
        return await asyncio.to_thread(extract_strengths_and_strategies, strengths_section, strategies_section)
    
    # Execute all in parallel
    results = await asyncio.gather(
        extract_financials(),
        extract_risks_full(),
        extract_objects(),
        extract_promoters_full(),
        extract_mgmt(),
        extract_kpis_section(),
        extract_peers(),
        extract_str_strat(),
        return_exceptions=True,
    )
    
    t_parallel = time.perf_counter() - t0
    
    # Unpack results (handle any exceptions gracefully)
    financials = results[0] if not isinstance(results[0], Exception) else {}
    classified_risks = results[1] if not isinstance(results[1], Exception) else {}
    objects = results[2] if not isinstance(results[2], Exception) else {}
    promoters = results[3] if not isinstance(results[3], Exception) else {}
    management = results[4] if not isinstance(results[4], Exception) else []
    kpi_bundle = results[5] if not isinstance(results[5], Exception) else {}
    kpis = kpi_bundle.get("kpis", {}) if isinstance(kpi_bundle, dict) else {}
    kpi_rows = kpi_bundle.get("kpi_rows", []) if isinstance(kpi_bundle, dict) else []
    peers = results[6] if not isinstance(results[6], Exception) else []
    strengths_strategies = results[7] if not isinstance(results[7], Exception) else {}
    
    # Log any extraction errors
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            import logging
            logging.getLogger("finagent.drhp_parser").warning(
                "Parallel extraction task %d failed: %s", i, r
            )
    
    # Step 3: Compute derived fields (depends on extracted data)
    t0 = time.perf_counter()
    
    fraud_signals = detect_sme_fraud_signals(
        promoters=promoters,
        objects=objects,
        financials=financials,
        related_party_section=related_party_section,
        full_text=parsed.full_text,
    )
    
    business_synthesis = generate_business_synthesis(
        business_section,
        objects,
        financials,
        strengths_strategies.get("strengths", []),
    )
    business_paragraphs = [
        paragraph
        for paragraph in _extract_clean_paragraphs(business_section, limit=40, min_chars=70)
        if not _is_business_boilerplate(paragraph)
    ][:3]
    if not business_paragraphs:
        fallback_paragraphs = [
            item for item in (
                strengths_strategies.get("strengths", [])[:1] + strengths_strategies.get("strategies", [])[:1]
            )
            if item
        ]
        business_paragraphs = fallback_paragraphs[:2]
    business_excerpt = "\n\n".join(business_paragraphs) if business_paragraphs else _clean_copy(business_section, max_chars=3000)
    
    t_derive = time.perf_counter() - t0
    t_total = time.perf_counter() - start_total
    
    # Log timing breakdown
    import logging
    logger = logging.getLogger("finagent.drhp_parser")
    logger.info(
        "[PARALLEL] sections=%.2fs, parallel_extract=%.2fs, derive=%.2fs, TOTAL=%.2fs",
        t_sections, t_parallel, t_derive, t_total
    )
    
    return {
        "sections_present": {name: sec.present for name, sec in sections.items()},
        "business_synthesis": business_synthesis,
        "business_overview_excerpt": business_excerpt,
        "business_overview_paragraphs": business_paragraphs,
        "financials": financials,
        "objects_of_issue": objects,
        "risk_factors": classified_risks,
        "promoters": promoters,
        "management": management,
        "kpis": kpis,
        "kpi_rows": kpi_rows,
        "peers": peers,
        "strengths": strengths_strategies.get("strengths", []),
        "strategies": strengths_strategies.get("strategies", []),
        "fraud_signals": fraud_signals,
        "_timing": {
            "sections_s": round(t_sections, 3),
            "parallel_extract_s": round(t_parallel, 3),
            "derive_s": round(t_derive, 3),
            "total_s": round(t_total, 3),
        },
    }

"""Pull narrative sections out of an actual 10-K / 10-Q HTML filing.

A 10-K body contains TOC anchors like `Item 1A. Risk Factors` and
`Item 7. Management's Discussion and Analysis`. We extract the text between
those headings using a forgiving regex over the de-HTML'd text, then trim the
result down to something an analyst can actually read.

The full filing is often 1-5 MB. We fetch with our identification UA (already
configured for sec.gov) and parse with BeautifulSoup, falling back to raw
regex if BeautifulSoup is unavailable.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from finagent.tools.web.http_fetcher import fetch

logger = logging.getLogger("finagent.sec_filings")

# Each section can have multiple "anchor" patterns to handle the different
# heading styles SEC filers use (Apple uses "Item 1A. Risk Factors"; Microsoft
# sometimes uses just "Risk Factors" with the item number elsewhere).
# Order matters: try the most specific anchor first.
_ITEM_HEADERS = [
    ("business", r"item\s*1\.?\s*(?!a|b)\s*business"),
    (
        "risk_factors",
        r"item\s*1\s*a\.?\s*[\.\s\u2014\u2013\-]*\s*risk\s*factors",
    ),
    # Use Item 1B (Unresolved Staff Comments), Item 1C (Cybersecurity, added by
    # the SEC in 2023), or Properties (Item 2) as the end anchor — whichever
    # appears first after Risk Factors.
    (
        "unresolved_staff",
        r"item\s*1\s*[bc]\.?\s*(?:unresolved\s*staff|cybersecurity)",
    ),
    ("properties", r"item\s*2\.?\s*properties"),
    ("legal", r"item\s*3\.?\s*legal\s*proceedings"),
    (
        "mdna",
        r"(?:item\s*7\.?\s*management.?s?\s*discussion|management.?s?\s*discussion\s*and\s*analysis\s*of)",
    ),
    ("market_risk", r"(?:item\s*7\s*a\.?\s*quantitative|item\s*7a[.\s]+quantitative)"),
    ("financials", r"item\s*8\.?\s*financial\s*statements"),
]

_BOILERPLATE_PHRASES = (
    "table of contents",
    "forward-looking statements",
    "(in millions)",
)


@dataclass
class FilingNarrative:
    business: str | None = None
    risk_factors: str | None = None
    mdna: str | None = None
    source_url: str = ""
    form: str | None = None
    filed_date: str | None = None

    def has_any(self) -> bool:
        return bool(self.business or self.risk_factors or self.mdna)


def _strip_html(raw: str) -> str:
    """Cheap, dependency-light HTML→text. Keeps paragraph breaks."""
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        # Crude regex fallback
        cleaned = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"<style[^>]*>.*?</style>", " ", cleaned, flags=re.IGNORECASE | re.DOTALL)
        cleaned = re.sub(r"<br\s*/?>", "\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"</p\s*>", "\n\n", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"&nbsp;", " ", cleaned)
        cleaned = re.sub(r"&amp;", "&", cleaned)
        cleaned = re.sub(r"&#x?[0-9a-f]+;", " ", cleaned, flags=re.IGNORECASE)
        return re.sub(r"\s+\n", "\n", re.sub(r"[ \t]+", " ", cleaned)).strip()
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    # Insert paragraph breaks
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block_tag in soup.find_all(["p", "div", "tr", "li", "h1", "h2", "h3", "h4"]):
        block_tag.append("\n")
    text = soup.get_text(" ", strip=False)
    text = re.sub(r"\u00a0", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _locate_section(text: str, start_pattern: str, end_pattern: str | None) -> str | None:
    """Find the body between two heading regexes.

    A 10-K contains the TOC version of each Item header AND the body version.
    The TOC version has very little text before the next header; the body
    version has lots. We enumerate all (start, end) candidate pairs and pick
    the pair with the largest distance, which is the real body.
    """
    lowered = text.lower()
    start_iter = list(re.finditer(start_pattern, lowered))
    if not start_iter:
        return None
    ends_iter = list(re.finditer(end_pattern, lowered)) if end_pattern else []

    def _is_cross_reference(text_lc: str, pos: int) -> bool:
        """Return True if the match at `pos` looks like an inline reference
        (e.g. 'Refer to "Item 1A. Risk Factors"…') rather than a heading."""
        prefix = text_lc[max(0, pos - 80) : pos]
        # Real headers are preceded by newlines/whitespace. Cross-refs are
        # preceded by words like 'refer to', 'see', a quote character, or
        # just normal prose continuing on the same line.
        if any(token in prefix for token in ("refer to", "see ", "see\n", "discussed in", "described in")):
            return True
        if prefix.count('"') % 2 == 1 or "\u201c" in prefix[-12:]:
            return True
        # Real headings have at least one newline within the last 8 chars.
        last_chars = prefix[-12:]
        return "\n" not in last_chars

    windows: list[tuple[int, int, int, int]] = []  # (length, is_heading, start, end)
    for sm in start_iter:
        s = sm.end()
        e = None
        for em in ends_iter:
            if em.start() > s:
                e = em.start()
                break
        if e is None:
            e = len(text)
        length = e - s
        if length < 1500:
            continue
        is_heading = 0 if _is_cross_reference(lowered, sm.start()) else 1
        windows.append((length, is_heading, s, e))
    if not windows:
        return None
    # Prefer heading-anchored windows first, then longest within that group.
    windows.sort(key=lambda w: (w[1], w[0]), reverse=True)
    _, _, s, e = windows[0]
    while s < len(text) and text[s] in " .\n\t":
        s += 1
    section = text[s:e].strip()
    return section if section else None


def _clean_section(raw: str, *, max_chars: int = 4500) -> str:
    """Drop boilerplate, table headers, and noise; return readable prose."""
    if not raw:
        return ""
    # Drop the first heading line (e.g. "Risk Factors\n")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    keep: list[str] = []
    for ln in lines:
        low = ln.lower()
        if any(b in low for b in _BOILERPLATE_PHRASES):
            continue
        # Skip lines that are mostly numbers / dates (tables)
        alpha = sum(1 for c in ln if c.isalpha())
        if alpha < max(8, len(ln) * 0.45):
            continue
        # Skip XBRL artifacts
        if "http://" in ln or "us-gaap:" in low or "xbrl" in low:
            continue
        keep.append(ln)
    body = "\n\n".join(keep)
    body = re.sub(r"\s{2,}", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    if len(body) <= max_chars:
        return body
    # Truncate at a sentence boundary
    cut = body[:max_chars]
    last_period = cut.rfind(". ")
    if last_period > max_chars * 0.6:
        cut = cut[: last_period + 1]
    return cut.rstrip() + " …"


async def fetch_filing_narrative(
    url: str,
    *,
    form: str | None = None,
    filed_date: str | None = None,
    timeout_s: float = 30.0,
) -> FilingNarrative | None:
    """Download a 10-K / 10-Q HTML and pull the narrative sections."""
    if not url:
        return None
    # Only forms that actually have Item 1A / Item 7. DEF 14A and 8-K don't.
    if form and form not in ("10-K", "10-Q", "10-K/A", "10-Q/A", "20-F"):
        return None
    res = await fetch(url, respect_robots=False, timeout_s=timeout_s)
    if res.status != 200 or not res.text:
        logger.info("filing fetch failed (%s): %s", res.status, url)
        return None
    # Defensive: drop any leftover replacement / control chars.
    raw_text = res.text.replace("\ufffd", " ")
    raw_text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", " ", raw_text)
    text = _strip_html(raw_text)
    if len(text) < 5000:
        logger.info("filing body too short (%d chars) after strip: %s", len(text), url)
        return None

    # Build {key: pattern} and {key: index} for ordering.
    patterns = dict(_ITEM_HEADERS)

    def section(key: str, end_key: str | None) -> str | None:
        return _locate_section(text, patterns[key], patterns[end_key] if end_key else None)

    business = _clean_section(section("business", "risk_factors") or "")
    risk_factors = _clean_section(
        section("risk_factors", "unresolved_staff")
        or section("risk_factors", "properties")
        or section("risk_factors", "legal")
        or ""
    )
    mdna = _clean_section(section("mdna", "market_risk") or section("mdna", "financials") or "")

    nar = FilingNarrative(
        business=business or None,
        risk_factors=risk_factors or None,
        mdna=mdna or None,
        source_url=url,
        form=form,
        filed_date=filed_date,
    )
    return nar if nar.has_any() else None

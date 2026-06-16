"""Heuristic pump-and-dump / viral falsification detector.

This is *signal*, not adjudication. It downgrades the confidence floor for a claim
when the only supporting source is a social post that reads like hype, then asks
the harness to triangulate against tier-1 sources before accepting the claim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


_HYPE_PHRASES = [
    r"\bto the moon\b",
    r"\bmoon(ing|shot)?\b",
    r"\b100x\b",
    r"\b1000x\b",
    r"\bgo(ing)? parabolic\b",
    r"\bnext (tesla|nvidia|apple|amazon)\b",
    r"\bguaranteed (gains?|returns?)\b",
    r"\bget in (now|before|early)\b",
    r"\bfomo\b",
    r"\bdiamond hands?\b",
    r"\bape (in|into)\b",
    r"\bsqueeze\b",
    r"\bshort squeeze\b",
    r"\bcan't (lose|miss)\b",
    r"\bfree money\b",
    r"\bdon'?t miss\b",
    r"\bpump\b",
    r"\bbreakout incoming\b",
    r"\bmust buy\b",
    r"\binsider tip\b",
    r"\binside info\b",
]
_HYPE_RE = re.compile("|".join(_HYPE_PHRASES), re.I)

_DOLLAR_TICKER_RE = re.compile(r"\$[A-Z]{1,5}\b")
_ALLCAPS_WORD_RE = re.compile(r"\b[A-Z]{4,}\b")
# Common stock tickers / acronyms / market terms that should not count as "shouting".
_TICKER_ALLOWLIST = {
    "AAPL", "MSFT", "NVDA", "GOOG", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC",
    "NFLX", "BRK", "JPM", "BAC", "WMT", "XOM", "CVX", "PYPL", "DIS", "ORCL", "ADBE",
    "CRM", "PFE", "MRK", "ABBV", "JNJ", "KO", "PEP", "COST", "NKE", "MCD", "BABA",
    "SEC", "NYSE", "NASDAQ", "AMEX", "EDGAR", "DRHP", "RHP", "IPO", "ETF", "REIT",
    "OTC", "FINRA", "FDIC", "FOMC", "GDP", "CPI", "PMI", "EBITDA", "GAAP", "IFRS",
    "USD", "EUR", "GBP", "JPY", "INR", "CAGR", "DCF", "WACC", "ROE", "ROIC", "ROA",
    "PDF", "HTML", "JSON", "CSV", "API", "URL", "HTTP", "HTTPS", "AAPL",
}
_EMOJI_HINT_RE = re.compile(r"[\U0001F680\U0001F4C8\U0001F4B0\U0001F525\U0001F31C\u2728]")
_CALL_TO_ACTION_RE = re.compile(r"\b(buy|long|short|sell)\s+(now|today|asap)\b", re.I)

SOCIAL_DOMAINS = {
    "x.com",
    "twitter.com",
    "reddit.com",
    "t.me",
    "telegram.me",
    "stocktwits.com",
    "tiktok.com",
    "discord.gg",
    "youtube.com",
    "youtu.be",
}

# Regulatory / wire / news sources whose all-caps headers are standard formatting,
# not hype. Section titles like "ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d)"
# from a 10-K should never be flagged as pump-and-dump shouting.
_REGULATORY_HOST_SUFFIXES = (
    "sec.gov",
    "investor.gov",
    "edgar.sec.gov",
    "federalreserve.gov",
    "treasury.gov",
    ".gov",
    ".edu",
)


def _is_regulatory_host(domain: str | None) -> bool:
    if not domain:
        return False
    d = domain.removeprefix("www.").lower()
    return any(d == s.lstrip(".") or d.endswith(s) for s in _REGULATORY_HOST_SUFFIXES)


@dataclass
class ViralAssessment:
    score: int  # 0 = clean, higher = more pump-like
    flags: list[str] = field(default_factory=list)
    is_social_only: bool = False
    needs_triangulation: bool = False
    confidence_floor: str = "MEDIUM"  # caller may further demote

    def to_marker(self) -> str:
        if self.score == 0 and not self.is_social_only:
            return "[VIRAL: clean]"
        flag_str = ", ".join(self.flags) if self.flags else "social-only"
        return f"[VIRAL: score={self.score} flags={flag_str}]"


def score_text_for_pump_and_dump(text: str, *, source_domain: str | None = None) -> ViralAssessment:
    flags: list[str] = []
    score = 0
    regulatory = _is_regulatory_host(source_domain)

    hype_hits = _HYPE_RE.findall(text or "")
    if hype_hits:
        flags.append(f"hype-phrases({len(hype_hits)})")
        score += min(len(hype_hits), 5) * 2

    if _CALL_TO_ACTION_RE.search(text or ""):
        flags.append("buy-now-cta")
        score += 3

    tickers = _DOLLAR_TICKER_RE.findall(text or "")
    if tickers and len(text) < 280:
        flags.append(f"ticker-blast({len(tickers)})")
        score += 2

    if not regulatory:
        # ALL-CAPS legalese (e.g. "ANNUAL REPORT PURSUANT TO SECTION 13...") is the
        # default formatting of regulatory filings, not pump-and-dump shouting.
        allcaps_all = _ALLCAPS_WORD_RE.findall(text or "")
        allcaps = [w for w in allcaps_all if w not in _TICKER_ALLOWLIST]
        if len(allcaps) >= 3:
            flags.append(f"shouting-words({len(allcaps)})")
            score += 1

    if _EMOJI_HINT_RE.search(text or ""):
        flags.append("rocket-emojis")
        score += 1

    is_social_only = bool(source_domain and source_domain.removeprefix("www.") in SOCIAL_DOMAINS)
    if is_social_only:
        flags.append(f"social-only({source_domain})")
        score += 2

    needs = score >= 3 or is_social_only
    floor = "LOW" if score >= 5 else ("MEDIUM" if needs else "MEDIUM")
    return ViralAssessment(
        score=score,
        flags=flags,
        is_social_only=is_social_only,
        needs_triangulation=needs,
        confidence_floor=floor,
    )

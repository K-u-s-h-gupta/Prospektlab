from __future__ import annotations

import re
from difflib import SequenceMatcher
from dataclasses import dataclass, field

from finagent.geo.jurisdiction_profiles import JurisdictionProfile, get_jurisdiction_profile
from finagent.geo.ticker_mapper import _ALIAS_TICKERS, canonical_ticker_label, infer_yahoo_ticker


_INDIA_HINTS = (
    "india",
    "nse",
    "bse",
    ".ns",
    ".bo",
    "sebi",
)
_JAPAN_HINTS = ("japan", "tokyo stock exchange", "tse")
_EU_HINTS = ("europe", "germany", "france", "london", "xetra", "euronext", "lse")
_INDIA_SUFFIXES = (" limited", " ltd", " ltd.", " pvt", " private limited")
_STOP_PHRASES = {
    "compare", "analyse", "analyze", "research", "review", "latest",
    "news", "valuation", "metrics", "fundamentals", "show", "provide",
    "give", "me", "its", "their", "and", "with", "against", "versus", "vs",
}

# Words that must NEVER be resolved as tickers by the uppercase regex in resolve_entities.
# This prevents "it", "its", "of", "to", "IT", "ME", "WE", "US", "IS", "BE", etc.
# from being misinterpreted as company tickers in follow-up queries.
PRONOUN_AND_COMMON_WORDS: set[str] = {
    "IT", "ITS", "THE", "AND", "FOR", "OF", "TO", "IN", "ON", "AT", "BY",
    "AS", "IS", "BE", "OR", "NO", "UP", "SO", "IF", "GO", "ME", "MY", "WE",
    "US", "HE", "SHE", "AM", "AN", "DO", "DID", "HAS", "HAD", "WAS", "WERE",
    "BEEN", "HAVE", "ARE", "WILL", "SHALL", "MAY", "MIGHT", "CAN", "COULD",
    "SHOULD", "WOULD", "MUST", "NOT", "NOW", "HOW", "ALL", "ANY", "BUT",
    "GET", "GOT", "HIM", "HER", "THEY", "THEM", "THEIR", "THIS", "THAT",
    "THAN", "THEN", "THESE", "THOSE", "WITH", "FROM", "INTO", "OVER",
    "UNDER", "AGAIN", "FURTHER", "ONCE", "HERE", "THERE", "WHEN", "WHERE",
    "WHY", "WHAT", "WHO", "WHOM", "WHOSE", "WHICH", "WHILE", "BECAUSE",
    "ABOUT", "BEFORE", "AFTER", "ABOVE", "BELOW", "BETWEEN", "THROUGH",
    "DURING", "BEFORE", "AFTER", "ABOVE", "BELOW", "UP", "DOWN", "OUT",
    "OFF", "OVER", "UNDER", "AGAIN", "FURTHER", "THEN", "ONCE",
    # finance/acronyms that were previously skipped
    "NSE", "BSE", "SEBI", "RBI", "DCF", "WACC", "CAGR", "FY",
}
_KNOWN_COUNTRIES = {
    "tcs": "IN",
    "tata consultancy services": "IN",
    "infosys": "IN",
    "infosys limited": "IN",
    "wipro": "IN",
    "wipro limited": "IN",
    "reliance": "IN",
    "reliance industries": "IN",
    "reliance industries limited": "IN",
    "hdfc bank": "IN",
    "hdfc bank limited": "IN",
    "icici bank": "IN",
    "icici bank limited": "IN",
    "nestle india": "IN",
    "adani ports": "IN",
    "adani enterprises": "IN",
    "adani green": "IN",
    "adani power": "IN",
    "bharti airtel": "IN",
    "airtel": "IN",
    "cg power": "IN",
    "cg power and industrial solutions": "IN",
    "cgpower": "IN",
    "vodafone idea": "IN",
    "idea": "IN",
    "hcl technologies": "IN",
    "hcltech": "IN",
    "asian paints": "IN",
    "bajaj finance": "IN",
    "bajaj finserv": "IN",
    "tata motors": "IN",
    "tata steel": "IN",
    "tata power": "IN",
    "tata elxsi": "IN",
    "tata chemicals": "IN",
    "maruti suzuki": "IN",
    "maruti": "IN",
    "sun pharma": "IN",
    "sun pharmaceutical": "IN",
    "dr reddy": "IN",
    "dr reddys": "IN",
    "cipla": "IN",
    "divis laboratories": "IN",
    "divis lab": "IN",
    "kotak mahindra bank": "IN",
    "kotak bank": "IN",
    "axis bank": "IN",
    "sbi": "IN",
    "state bank of india": "IN",
    "punjab national bank": "IN",
    "pnb": "IN",
    "bank of baroda": "IN",
    "larsen toubro": "IN",
    "larsen & toubro": "IN",
    "l&t": "IN",
    "lt": "IN",
    "ultratech cement": "IN",
    "ultratech": "IN",
    "itc": "IN",
    "itc limited": "IN",
    "hindustan unilever": "IN",
    "hul": "IN",
    "power grid corporation": "IN",
    "ntpc": "IN",
    "ongc": "IN",
    "coal india": "IN",
    "ioc": "IN",
    "indian oil": "IN",
    "bpcl": "IN",
    "grasim": "IN",
    "grasim industries": "IN",
    "tech mahindra": "IN",
    "mahindra": "IN",
    "m&m": "IN",
    "hero motocorp": "IN",
    "eicher motors": "IN",
    "titan company": "IN",
    "titan": "IN",
    "zomato": "IN",
    "paytm": "IN",
    "nykaa": "IN",
    "delhivery": "IN",
    "policybazaar": "IN",
    "jsw steel": "IN",
    "jsw energy": "IN",
    "vedanta": "IN",
    "hindalco": "IN",
    "shree cement": "IN",
    # PSU & heavy industry
    "bhel": "IN",
    "bharat heavy electricals": "IN",
    "bharat heavy electricals limited": "IN",
    "bharat electronics": "IN",
    "bel": "IN",
    "hpcl": "IN",
    "hindustan petroleum": "IN",
    "gail": "IN",
    "gail india": "IN",
    "nmdc": "IN",
    "steel authority of india": "IN",
    "sail": "IN",
    "lic": "IN",
    "life insurance corporation": "IN",
    "power finance corporation": "IN",
    "pfc": "IN",
    "rec limited": "IN",
    "rec": "IN",
    "irfc": "IN",
    "indian railway finance corporation": "IN",
    "nhpc": "IN",
    "sjvn": "IN",
    "cochin shipyard": "IN",
    "bharat forge": "IN",
    "bharat petroleum": "IN",
    "iob": "IN",
    "indian overseas bank": "IN",
    "union bank": "IN",
    "canara bank": "IN",
    "bank of india": "IN",
    "central bank of india": "IN",
    "idbi bank": "IN",
    # Mid/small cap popular searches
    "dixon": "IN",
    "dixon technologies": "IN",
    "havells": "IN",
    "havells india": "IN",
    "voltas": "IN",
    "blue star": "IN",
    "whirlpool india": "IN",
    "amber enterprises": "IN",
    "pidilite": "IN",
    "pidilite industries": "IN",
    "godrej consumer": "IN",
    "godrej properties": "IN",
    "godrej": "IN",
    "dabur": "IN",
    "dabur india": "IN",
    "marico": "IN",
    "colgate palmolive india": "IN",
    "berger paints": "IN",
    "kansai nerolac": "IN",
    "page industries": "IN",
    "muthoot finance": "IN",
    "manappuram finance": "IN",
    "cholamandalam": "IN",
    "bajaj auto": "IN",
    "tvs motor": "IN",
    "tvs": "IN",
    "exide industries": "IN",
    "amara raja": "IN",
    "motherson sumi": "IN",
    "minda industries": "IN",
    "ceat": "IN",
    "apollo tyres": "IN",
    "mrf": "IN",
    "balaji amines": "IN",
    "srf limited": "IN",
    "srf": "IN",
    "aarti industries": "IN",
    "deepak nitrite": "IN",
    "pi industries": "IN",
    "upl": "IN",
    "bayer cropscience": "IN",
    "divi": "IN",
    "alkem laboratories": "IN",
    "torrent pharma": "IN",
    "torrent pharmaceuticals": "IN",
    "lupin": "IN",
    "aurobindo pharma": "IN",
    "cadila healthcare": "IN",
    "zydus lifesciences": "IN",
    "glenmark": "IN",
    "biocon": "IN",
    "laurus labs": "IN",
    # IT / Tech
    "mphasis": "IN",
    "hexaware": "IN",
    "ltimindtree": "IN",
    "coforge": "IN",
    "persistent systems": "IN",
    "tata elxsi": "IN",
    "cyient": "IN",
    "kpit technologies": "IN",
    "zensar technologies": "IN",
    # Finance / NBFC
    "hdfc amc": "IN",
    "nippon india": "IN",
    "uti amc": "IN",
    "sbi life insurance": "IN",
    "hdfc life insurance": "IN",
    "icici lombard": "IN",
    "star health": "IN",
    "sbi cards": "IN",
    "credit access grameen": "IN",
    "five star business finance": "IN",
    "shriram finance": "IN",
    "piramal enterprises": "IN",
    "iifl finance": "IN",
    "m&mfin": "IN",
    "mahindra finance": "IN",
    "pidilite": "IN",
    "pidilite industries": "IN",
    "havells": "IN",
    "havells india": "IN",
    "indusind bank": "IN",
    "bandhan bank": "IN",
    "sbi life": "IN",
    "hdfc life": "IN",
    "lic": "IN",
    "life insurance corporation": "IN",
}


@dataclass(frozen=True)
class ResolvedEntity:
    query: str
    canonical_name: str
    normalized_name: str
    country_code: str
    country_name: str
    primary_exchange: str | None
    regulator: str | None
    currency: str
    yahoo_ticker: str | None
    ticker_label: str | None
    search_aliases: tuple[str, ...] = ()
    search_suffix: str = ""
    investor_relations_hint: str | None = None
    confidence: str = "low"
    market_segment: str = "unknown"
    profile: JurisdictionProfile = field(default_factory=lambda: get_jurisdiction_profile("GLOBAL"))

    @property
    def search_label(self) -> str:
        labels = [self.canonical_name]
        if self.ticker_label and self.ticker_label not in labels:
            labels.append(self.ticker_label)
        return " ".join(labels)

    def to_event_payload(self) -> dict[str, object]:
        return {
            "query": self.query,
            "canonical_name": self.canonical_name,
            "country_code": self.country_code,
            "country_name": self.country_name,
            "primary_exchange": self.primary_exchange,
            "regulator": self.regulator,
            "currency": self.currency,
            "yahoo_ticker": self.yahoo_ticker,
            "ticker_label": self.ticker_label,
            "preferred_domains": list(self.profile.preferred_domains),
            "confidence": self.confidence,
            "market_segment": self.market_segment,
        }


def _normalize_name(query: str) -> str:
    name = (query or "").strip()
    name = re.sub(r"\s+", " ", name)
    return name.strip(" ,")


def _strip_corporate_suffixes(value: str) -> str:
    text = (value or "").strip(" ,.-")
    lowered = text.lower()
    suffixes = _INDIA_SUFFIXES + (" industries", " industry", " company", " co", " co.")
    for suffix in sorted(suffixes, key=len, reverse=True):
        if lowered.endswith(suffix):
            text = text[: -len(suffix)].strip(" ,.-")
            lowered = text.lower()
    return text


def _clean_entity_phrase(value: str) -> str:
    text = re.sub(r"[\(\)\[\]{}]", " ", value or "")
    text = re.sub(
        r"\b(?:on|of|for|about|please|tell|latest|news|valuation|metrics|price|prices|historical|history|stock|share|show|provide)\b",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+", " ", text).strip(" ,.-")
    return _strip_corporate_suffixes(text)


def _compound_hypotheses(query: str) -> list[str]:
    text = _clean_entity_phrase(query)
    if not text:
        return []
    pieces = re.split(r"\b(?:vs\.?|versus|against|and|with|compare to|compared with)\b|[,/]", text, flags=re.I)
    candidates: list[str] = []
    for piece in pieces:
        cleaned = _clean_entity_phrase(piece)
        words = [w for w in cleaned.split() if w.lower() not in _STOP_PHRASES]
        if not words:
            continue
        candidates.append(" ".join(words))
        for width in (4, 3, 2):
            for idx in range(0, max(len(words) - width + 1, 0)):
                candidates.append(" ".join(words[idx : idx + width]))
        for word in words:
            if re.fullmatch(r"[A-Z&-]{2,14}", word):
                candidates.append(word)
    seen: set[str] = set()
    out: list[str] = []
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _fuzzy_alias(candidate: str) -> str | None:
    """Recover common misspellings such as 'tata motor' -> 'tata motors'."""

    cleaned = _clean_entity_phrase(candidate).lower()
    if not cleaned or len(cleaned) < 3:
        return None
    if cleaned in _ALIAS_TICKERS:
        return cleaned
    best_alias = None
    best_score = 0.0
    for alias in _ALIAS_TICKERS:
        if abs(len(alias) - len(cleaned)) > max(4, len(cleaned) // 2):
            continue
        score = SequenceMatcher(None, cleaned, alias).ratio()
        if score > best_score:
            best_score = score
            best_alias = alias
    return best_alias if best_alias and best_score >= 0.86 else None


def _guess_country(query: str) -> str:
    q = (query or "").strip().lower()
    if q in _KNOWN_COUNTRIES:
        return _KNOWN_COUNTRIES[q]
    if any(h in q for h in _INDIA_HINTS):
        return "IN"
    if any(h in q for h in _JAPAN_HINTS):
        return "JP"
    if any(h in q for h in _EU_HINTS):
        return "EU"
    if any(q.endswith(suf) for suf in _INDIA_SUFFIXES):
        return "IN"
    # Default to India — ProspektLab is India-focused
    return "IN"


def _market_segment_for(query: str, ticker_label: str | None, confidence: str) -> str:
    lower = (query or "").lower()
    if any(term in lower for term in ("sme", "emerge", "small cap", "small-cap", "microcap", "micro-cap")):
        return "sme_or_smallcap"
    if confidence != "high":
        return "sme_or_smallcap"
    large = {
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN",
        "BHARTIARTL", "ITC", "LT", "HINDUNILVR", "AXISBANK", "KOTAKBANK",
        "BAJFINANCE", "MARUTI", "SUNPHARMA", "TATAMOTORS",
    }
    if ticker_label and ticker_label.upper() not in large:
        return "mid_or_smallcap"
    return "largecap"


def resolve_entity(query: str) -> ResolvedEntity:
    # V3 SINGLE-TICKER VALIDATION BYPASS:
    # Research, comparison, and portfolio-audit prompts are allowed even when
    # they are not standalone ticker strings. If no known alias resolves, use
    # the normalized raw query as the entity label instead of raising a 422.
    hypotheses = _compound_hypotheses(query)
    best = next((h for h in hypotheses if h.lower() in _ALIAS_TICKERS), None)
    if best is None:
        best = next((_fuzzy_alias(h) for h in hypotheses if _fuzzy_alias(h)), None)
    if best is None:
        best = _fuzzy_alias(query)
    canonical_name = _normalize_name(best or query)
    country_code = _guess_country(query)
    ticker_label = canonical_ticker_label(canonical_name)

    raw = canonical_name.strip()
    if not ticker_label and raw == raw.upper() and re.fullmatch(r"[A-Z]{2,12}", raw):
        ticker_label = raw

    profile = get_jurisdiction_profile(country_code)
    yahoo_ticker = infer_yahoo_ticker(canonical_name, profile)

    confidence = "medium" if country_code != "GLOBAL" or yahoo_ticker else "low"
    if ticker_label and yahoo_ticker:
        confidence = "high"

    search_suffix = " ".join(profile.search_suffix_terms[:3]).strip()
    return ResolvedEntity(
        query=query,
        canonical_name=canonical_name,
        normalized_name=canonical_name.lower(),
        country_code=profile.country_code,
        country_name=profile.country_name,
        primary_exchange=profile.exchanges[0] if profile.exchanges else None,
        regulator=profile.regulator,
        currency=profile.primary_currency,
        yahoo_ticker=yahoo_ticker,
        ticker_label=ticker_label,
        search_aliases=tuple(x for x in (canonical_name, ticker_label or "", yahoo_ticker or "") if x),
        search_suffix=search_suffix,
        confidence=confidence,
        market_segment=_market_segment_for(canonical_name, ticker_label, confidence),
        profile=profile,
    )


def resolve_entities(query: str, *, limit: int = 4) -> list[ResolvedEntity]:
    """Resolve one or more Indian-market entities from a conversational query."""

    text = query or ""
    lower = f" {text.lower()} "
    candidates: list[tuple[int, str]] = []
    for alias in sorted(_ALIAS_TICKERS, key=len, reverse=True):
        pattern = r"(?<![a-z0-9&])" + re.escape(alias.lower()) + r"(?![a-z0-9])"
        match = re.search(pattern, lower)
        if match:
            candidates.append((match.start(), alias))
    for match in re.finditer(r"\b[A-Z][A-Z&-]{1,14}(?:\.(?:NS|BO|NSE|BSE))?\b", text):
        token = match.group(0)
        if token.upper() in PRONOUN_AND_COMMON_WORDS:
            continue
        candidates.append((match.start(), token))
    if not candidates:
        candidates.extend((idx, h) for idx, h in enumerate(_compound_hypotheses(text)))

    out: list[ResolvedEntity] = []
    seen: set[str] = set()
    for _, raw in sorted(candidates, key=lambda item: (item[0], -len(item[1]))):
        entity = resolve_entity(raw)
        key = entity.yahoo_ticker or entity.ticker_label or entity.normalized_name
        if key in seen:
            continue
        seen.add(key)
        out.append(entity)
        if len(out) >= limit:
            break
    return out

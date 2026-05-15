from __future__ import annotations

import re
from dataclasses import dataclass, field

from finagent.geo.jurisdiction_profiles import JurisdictionProfile, get_jurisdiction_profile
from finagent.geo.ticker_mapper import canonical_ticker_label, infer_yahoo_ticker


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
_US_SUFFIXES = (" inc", " inc.", " corporation", " corp", " corp.", " holdings")
_INDIA_SUFFIXES = (" limited", " ltd", " ltd.", " pvt", " private limited")
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
        }


def _normalize_name(query: str) -> str:
    name = (query or "").strip()
    name = re.sub(r"\s+", " ", name)
    return name.strip(" ,")


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
    if any(q.endswith(suf) for suf in _US_SUFFIXES):
        return "US"
    # Default to India — ProspektLab is India-focused
    return "IN"


def resolve_entity(query: str) -> ResolvedEntity:
    canonical_name = _normalize_name(query)
    country_code = _guess_country(query)
    ticker_label = canonical_ticker_label(query)

    raw = canonical_name.strip()
    if not ticker_label and raw == raw.upper() and re.fullmatch(r"[A-Z]{2,12}", raw):
        ticker_label = raw

    profile = get_jurisdiction_profile(country_code)
    yahoo_ticker = infer_yahoo_ticker(query, profile)

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
        profile=profile,
    )

from __future__ import annotations

import re

from finagent.geo.jurisdiction_profiles import JurisdictionProfile


_ALIAS_TICKERS: dict[str, tuple[str, str]] = {
    # ── Nifty 50 & Major Large Caps ──
    "tcs": ("TCS.NS", "TCS"),
    "tata consultancy services": ("TCS.NS", "TCS"),
    "infosys": ("INFY.NS", "INFY"),
    "infosys limited": ("INFY.NS", "INFY"),
    "wipro": ("WIPRO.NS", "WIPRO"),
    "wipro limited": ("WIPRO.NS", "WIPRO"),
    "reliance": ("RELIANCE.NS", "RELIANCE"),
    "reliance industries": ("RELIANCE.NS", "RELIANCE"),
    "reliance industries limited": ("RELIANCE.NS", "RELIANCE"),
    "hdfc bank": ("HDFCBANK.NS", "HDFCBANK"),
    "hdfc bank limited": ("HDFCBANK.NS", "HDFCBANK"),
    "icici bank": ("ICICIBANK.NS", "ICICIBANK"),
    "icici bank limited": ("ICICIBANK.NS", "ICICIBANK"),
    "kotak mahindra bank": ("KOTAKBANK.NS", "KOTAKBANK"),
    "kotak bank": ("KOTAKBANK.NS", "KOTAKBANK"),
    "axis bank": ("AXISBANK.NS", "AXISBANK"),
    "sbi": ("SBIN.NS", "SBIN"),
    "state bank of india": ("SBIN.NS", "SBIN"),
    "indusind bank": ("INDUSINDBK.NS", "INDUSINDBK"),
    "bandhan bank": ("BANDHANBNK.NS", "BANDHANBNK"),
    "pnb": ("PNB.NS", "PNB"),
    "punjab national bank": ("PNB.NS", "PNB"),
    "bank of baroda": ("BANKBARODA.NS", "BANKBARODA"),
    "nestle india": ("NESTLEIND.NS", "NESTLEIND"),
    "hindustan unilever": ("HINDUNILVR.NS", "HINDUNILVR"),
    "hul": ("HINDUNILVR.NS", "HINDUNILVR"),
    "itc": ("ITC.NS", "ITC"),
    "itc limited": ("ITC.NS", "ITC"),
    "bharti airtel": ("BHARTIARTL.NS", "BHARTIARTL"),
    "airtel": ("BHARTIARTL.NS", "BHARTIARTL"),
    "cg power": ("CGPOWER.NS", "CGPOWER"),
    "cg power and industrial solutions": ("CGPOWER.NS", "CGPOWER"),
    "cgpower": ("CGPOWER.NS", "CGPOWER"),
    "vodafone idea": ("IDEA.NS", "IDEA"),
    "idea": ("IDEA.NS", "IDEA"),
    "hcl technologies": ("HCLTECH.NS", "HCLTECH"),
    "hcltech": ("HCLTECH.NS", "HCLTECH"),
    "tech mahindra": ("TECHM.NS", "TECHM"),
    "asian paints": ("ASIANPAINT.NS", "ASIANPAINT"),
    "bajaj finance": ("BAJFINANCE.NS", "BAJFINANCE"),
    "bajaj finserv": ("BAJAJFINSV.NS", "BAJAJFINSV"),
    "tata motors": ("TATAMOTORS.NS", "TATAMOTORS"),
    "tata steel": ("TATASTEEL.NS", "TATASTEEL"),
    "tata power": ("TATAPOWER.NS", "TATAPOWER"),
    "tata elxsi": ("TATAELXSI.NS", "TATAELXSI"),
    "tata chemicals": ("TATACHEM.NS", "TATACHEM"),
    "tata consumer": ("TATACONSUM.NS", "TATACONSUM"),
    "maruti suzuki": ("MARUTI.NS", "MARUTI"),
    "maruti": ("MARUTI.NS", "MARUTI"),
    "sun pharma": ("SUNPHARMA.NS", "SUNPHARMA"),
    "sun pharmaceutical": ("SUNPHARMA.NS", "SUNPHARMA"),
    "dr reddy": ("DRREDDY.NS", "DRREDDY"),
    "dr reddys": ("DRREDDY.NS", "DRREDDY"),
    "cipla": ("CIPLA.NS", "CIPLA"),
    "divis laboratories": ("DIVISLAB.NS", "DIVISLAB"),
    "divis lab": ("DIVISLAB.NS", "DIVISLAB"),
    "larsen toubro": ("LT.NS", "LT"),
    "larsen & toubro": ("LT.NS", "LT"),
    "l&t": ("LT.NS", "LT"),
    "lt": ("LT.NS", "LT"),
    "ultratech cement": ("ULTRACEMCO.NS", "ULTRACEMCO"),
    "ultratech": ("ULTRACEMCO.NS", "ULTRACEMCO"),
    "power grid corporation": ("POWERGRID.NS", "POWERGRID"),
    "ntpc": ("NTPC.NS", "NTPC"),
    "ongc": ("ONGC.NS", "ONGC"),
    "coal india": ("COALINDIA.NS", "COALINDIA"),
    "indian oil": ("IOC.NS", "IOC"),
    "ioc": ("IOC.NS", "IOC"),
    "bpcl": ("BPCL.NS", "BPCL"),
    "grasim": ("GRASIM.NS", "GRASIM"),
    "grasim industries": ("GRASIM.NS", "GRASIM"),
    "mahindra": ("M&M.NS", "M&M"),
    "m&m": ("M&M.NS", "M&M"),
    "hero motocorp": ("HEROMOTOCO.NS", "HEROMOTOCO"),
    "eicher motors": ("EICHERMOT.NS", "EICHERMOT"),
    "titan": ("TITAN.NS", "TITAN"),
    "titan company": ("TITAN.NS", "TITAN"),
    "adani ports": ("ADANIPORTS.NS", "ADANIPORTS"),
    "adani enterprises": ("ADANIENT.NS", "ADANIENT"),
    "adani green": ("ADANIGREEN.NS", "ADANIGREEN"),
    "adani power": ("ADANIPOWER.NS", "ADANIPOWER"),
    "jsw steel": ("JSWSTEEL.NS", "JSWSTEEL"),
    "jsw energy": ("JSWENERGY.NS", "JSWENERGY"),
    "vedanta": ("VEDL.NS", "VEDL"),
    "hindalco": ("HINDALCO.NS", "HINDALCO"),
    "shree cement": ("SHREECEM.NS", "SHREECEM"),
    "pidilite": ("PIDILITIND.NS", "PIDILITIND"),
    "pidilite industries": ("PIDILITIND.NS", "PIDILITIND"),
    "havells": ("HAVELLS.NS", "HAVELLS"),
    "havells india": ("HAVELLS.NS", "HAVELLS"),
    "sbi life": ("SBILIFE.NS", "SBILIFE"),
    "hdfc life": ("HDFCLIFE.NS", "HDFCLIFE"),
    "lic": ("LICI.NS", "LICI"),
    "life insurance corporation": ("LICI.NS", "LICI"),
    # ── New-Age Tech ──
    # ── New-Age Tech (verify tickers periodically — these companies rebrand) ──
    "zomato": ("ETERNAL.NS", "ETERNAL"),       # Zomato rebranded to Eternal Limited May 2025
    "eternal": ("ETERNAL.NS", "ETERNAL"),
    "eternal limited": ("ETERNAL.NS", "ETERNAL"),
    "paytm": ("ONE97.NS", "ONE97"),            # Paytm = One97 Communications
    "one97": ("ONE97.NS", "ONE97"),
    "nykaa": ("NYKAA.NS", "NYKAA"),
    "delhivery": ("DELHIVERY.NS", "DELHIVERY"),
    "policybazaar": ("POLICYBZR.NS", "POLICYBZR"),
    "pb fintech": ("POLICYBZR.NS", "POLICYBZR"),
    "ola electric": ("OLAELEC.NS", "OLAELEC"),
    "firstcry": ("BRAINBEES.NS", "BRAINBEES"),
    "swiggy": ("SWIGGY.NS", "SWIGGY"),
    "indigo": ("INDIGO.NS", "INDIGO"),
    "interglobe aviation": ("INDIGO.NS", "INDIGO"),
    "irctc": ("IRCTC.NS", "IRCTC"),
    "dixon technologies": ("DIXON.NS", "DIXON"),
    "dixon": ("DIXON.NS", "DIXON"),
    # PSU & heavy industry
    "bhel": ("BHEL.NS", "BHEL"),
    "bharat heavy electricals": ("BHEL.NS", "BHEL"),
    "bharat electronics": ("BEL.NS", "BEL"),
    "bel": ("BEL.NS", "BEL"),
    "hpcl": ("HINDPETRO.NS", "HINDPETRO"),
    "hindustan petroleum": ("HINDPETRO.NS", "HINDPETRO"),
    "gail": ("GAIL.NS", "GAIL"),
    "gail india": ("GAIL.NS", "GAIL"),
    "nmdc": ("NMDC.NS", "NMDC"),
    "sail": ("SAIL.NS", "SAIL"),
    "steel authority": ("SAIL.NS", "SAIL"),
    "lici": ("LICI.NS", "LICI"),
    "pfc": ("PFC.NS", "PFC"),
    "power finance corporation": ("PFC.NS", "PFC"),
    "rec": ("RECLTD.NS", "RECLTD"),
    "rec limited": ("RECLTD.NS", "RECLTD"),
    "irfc": ("IRFC.NS", "IRFC"),
    "nhpc": ("NHPC.NS", "NHPC"),
    "sjvn": ("SJVN.NS", "SJVN"),
    "bharat forge": ("BHARATFORG.NS", "BHARATFORG"),
    "canara bank": ("CANBK.NS", "CANBK"),
    "bank of baroda": ("BANKBARODA.NS", "BANKBARODA"),
    "union bank": ("UNIONBANK.NS", "UNIONBANK"),
    "pnb": ("PNB.NS", "PNB"),
    "idbi bank": ("IDBI.NS", "IDBI"),
    "iob": ("IOB.NS", "IOB"),
    # Consumer / FMCG
    "havells": ("HAVELLS.NS", "HAVELLS"),
    "voltas": ("VOLTAS.NS", "VOLTAS"),
    "pidilite": ("PIDILITIND.NS", "PIDILITIND"),
    "pidilite industries": ("PIDILITIND.NS", "PIDILITIND"),
    "dabur": ("DABUR.NS", "DABUR"),
    "marico": ("MARICO.NS", "MARICO"),
    "godrej consumer": ("GODREJCP.NS", "GODREJCP"),
    "godrej properties": ("GODREJPROP.NS", "GODREJPROP"),
    "berger paints": ("BERGEPAINT.NS", "BERGEPAINT"),
    "page industries": ("PAGEIND.NS", "PAGEIND"),
    # Auto
    "bajaj auto": ("BAJAJ-AUTO.NS", "BAJAJ-AUTO"),
    "tvs motor": ("TVSMOTOR.NS", "TVSMOTOR"),
    "tvs": ("TVSMOTOR.NS", "TVSMOTOR"),
    "mrf": ("MRF.NS", "MRF"),
    "apollo tyres": ("APOLLOTYRE.NS", "APOLLOTYRE"),
    # Pharma
    "lupin": ("LUPIN.NS", "LUPIN"),
    "torrent pharma": ("TORNTPHARM.NS", "TORNTPHARM"),
    "biocon": ("BIOCON.NS", "BIOCON"),
    "aurobindo": ("AUROPHARMA.NS", "AUROPHARMA"),
    # Finance / NBFC
    "muthoot finance": ("MUTHOOTFIN.NS", "MUTHOOTFIN"),
    "shriram finance": ("SHRIRAMFIN.NS", "SHRIRAMFIN"),
    "hdfc life": ("HDFCLIFE.NS", "HDFCLIFE"),
    "sbi life": ("SBILIFE.NS", "SBILIFE"),
    "icici lombard": ("ICICIGI.NS", "ICICIGI"),
    # IT mid-cap
    "mphasis": ("MPHASIS.NS", "MPHASIS"),
    "persistent": ("PERSISTENT.NS", "PERSISTENT"),
    "ltimindtree": ("LTIM.NS", "LTIM"),
    "coforge": ("COFORGE.NS", "COFORGE"),
}


def infer_yahoo_ticker(query: str, profile: JurisdictionProfile) -> str | None:
    q = (query or "").strip()
    if not q:
        return None
    q_lower = q.lower()
    if q_lower in _ALIAS_TICKERS:
        return _ALIAS_TICKERS[q_lower][0]

    upper = q.upper()
    if "." in upper and re.search(r"\.[A-Z]{1,4}$", upper):
        return upper

    ticker_match = re.fullmatch(r"[A-Z]{1,12}", upper)
    if ticker_match and profile.yahoo_suffixes:
        return upper + profile.yahoo_suffixes[0]

    if profile.country_code == "IN":
        base = re.sub(r"[^A-Za-z]", "", q).upper()
        if 2 <= len(base) <= 12:
            return base + ".NS"
    return None


def canonical_ticker_label(query: str) -> str | None:
    q_lower = (query or "").strip().lower()
    if q_lower in _ALIAS_TICKERS:
        return _ALIAS_TICKERS[q_lower][1]
    return None

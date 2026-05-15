from __future__ import annotations

import re

from finagent.geo.entity_resolver import ResolvedEntity


def localize_search_query(query: str, entity: ResolvedEntity) -> str:
    q = (query or "").strip()
    if not q:
        return q

    profile = entity.profile
    out = q
    if profile.country_code == "IN":
        out = out.replace("site:sec.gov", "(site:sebi.gov.in OR site:nseindia.com OR site:bseindia.com)")
        out = out.replace("10-K", "annual report")
        out = out.replace("10-Q", "quarterly results")
        out = out.replace("8-K", "exchange filing")
        out = out.replace("form 4", "insider trading disclosure")
        out = out.replace("13F", "shareholding pattern")
        out = out.replace("DEF 14A", "annual report corporate governance")
        out = out.replace("SEC DOJ FTC charged", "SEBI investigation regulatory action")
    elif profile.country_code != "US":
        out = out.replace("site:sec.gov", "investor relations regulator filing")
        out = out.replace("10-K", "annual report")
        out = out.replace("10-Q", "quarterly results")
        out = out.replace("form 4", "insider trading disclosure")
        out = out.replace("13F", "institutional holdings")
        out = out.replace("DEF 14A", "annual report governance")
        out = out.replace("SEC DOJ FTC charged", "regulatory action investigation")

    lowered = out.lower()
    if entity.search_suffix and entity.search_suffix.lower() not in lowered:
        out = f"{out} {entity.search_suffix}".strip()
        lowered = out.lower()

    if entity.primary_exchange and entity.primary_exchange.lower() not in lowered:
        out = f"{out} {entity.primary_exchange}".strip()

    return re.sub(r"\s{2,}", " ", out).strip()

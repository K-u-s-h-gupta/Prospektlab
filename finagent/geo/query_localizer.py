from __future__ import annotations

import re

from finagent.geo.entity_resolver import ResolvedEntity


def localize_search_query(query: str, entity: ResolvedEntity) -> str:
    q = (query or "").strip()
    if not q:
        return q

    out = q

    lowered = out.lower()
    if entity.search_suffix and entity.search_suffix.lower() not in lowered:
        out = f"{out} {entity.search_suffix}".strip()
        lowered = out.lower()

    if entity.primary_exchange and entity.primary_exchange.lower() not in lowered:
        out = f"{out} {entity.primary_exchange}".strip()

    return re.sub(r"\s{2,}", " ", out).strip()

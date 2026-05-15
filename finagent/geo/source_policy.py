from __future__ import annotations

from finagent.geo.entity_resolver import ResolvedEntity


def preferred_domains_for_entity(entity: ResolvedEntity) -> list[str]:
    domains = list(entity.profile.preferred_domains)
    if entity.investor_relations_hint:
        domains.insert(0, entity.investor_relations_hint)
    deduped: list[str] = []
    seen = set()
    for domain in domains:
        key = domain.lower().removeprefix("www.")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped

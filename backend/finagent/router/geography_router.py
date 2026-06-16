from __future__ import annotations

from finagent.geo.entity_resolver import ResolvedEntity


def geography_policy_for_entity(entity: ResolvedEntity) -> dict[str, object]:
    return {
        "country_code": entity.country_code,
        "country_name": entity.country_name,
        "preferred_domains": list(entity.profile.preferred_domains),
        "exchange": entity.primary_exchange,
        "regulator": entity.regulator,
        "currency": entity.currency,
    }

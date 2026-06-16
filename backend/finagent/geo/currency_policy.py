from __future__ import annotations

from finagent.geo.entity_resolver import ResolvedEntity


def preferred_currency_for_entity(entity: ResolvedEntity) -> str:
    return entity.currency or entity.profile.primary_currency

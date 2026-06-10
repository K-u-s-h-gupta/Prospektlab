from __future__ import annotations

import re

from finagent.geo.entity_resolver import ResolvedEntity


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _term_tokens(value: str | None) -> set[str]:
    return {match.group(0) for match in _TOKEN_RE.finditer((value or "").lower())}


def localize_search_query(query: str, entity: ResolvedEntity) -> str:
    q = (query or "").strip()
    if not q:
        return q

    out = q
    query_tokens = _term_tokens(out)
    localization_tokens = {term.lower() for term in entity.profile.search_suffix_terms}
    if entity.primary_exchange:
        localization_tokens.add(entity.primary_exchange.lower())
    if entity.regulator:
        localization_tokens |= _term_tokens(entity.regulator)

    if entity.search_suffix:
        suffix_tokens = _term_tokens(entity.search_suffix)
        if suffix_tokens and not (query_tokens & (localization_tokens | suffix_tokens)):
            out = f"{out} {entity.search_suffix}".strip()
            query_tokens |= suffix_tokens

    exchange_tokens = _term_tokens(entity.primary_exchange)
    if entity.primary_exchange and exchange_tokens and not (query_tokens & exchange_tokens):
        if not (query_tokens & localization_tokens):
            out = f"{out} {entity.primary_exchange}".strip()

    return re.sub(r"\s{2,}", " ", out).strip()

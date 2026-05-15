from __future__ import annotations

from typing import TYPE_CHECKING

from finagent.geo.entity_resolver import ResolvedEntity
from finagent.retrieval.dense_index import score_semantic
from finagent.retrieval.fusion import fuse_scores
from finagent.retrieval.graph_index import score_entity_relationship
from finagent.retrieval.sparse_index import score_sparse

if TYPE_CHECKING:
    from finagent.tools.web.scraper import ScrapedDoc


def rerank_docs(
    query: str,
    docs: list[ScrapedDoc],
    *,
    entity: ResolvedEntity | None = None,
    preferred_domains: list[str] | None = None,
) -> list[ScrapedDoc]:
    preferred = [d.lower().removeprefix("www.") for d in (preferred_domains or [])]
    aliases = entity.search_aliases if entity else ()

    def _score(doc: ScrapedDoc) -> float:
        text = " ".join(x for x in (doc.title, doc.excerpt, doc.domain) if x)
        sparse = score_sparse(query, text)
        semantic = score_semantic(query, text)
        relation = score_entity_relationship(query, text, aliases)
        score = fuse_scores(sparse, semantic, relation)
        if preferred and any(doc.domain.endswith(d) for d in preferred):
            score += 2.5
        if doc.tier <= 2:
            score += 1.0
        elif doc.tier <= 4:
            score += 0.5
        if doc.blocked_reason:
            score -= 2.0
        return score

    return sorted(docs, key=_score, reverse=True)

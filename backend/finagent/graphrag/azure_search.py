"""Azure AI Search hybrid retrieval for IKG document sections."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from finagent.env import load_finagent_env

load_finagent_env()

logger = logging.getLogger("finagent.graphrag.azure_search")


@dataclass(frozen=True)
class AzureSearchConfig:
    endpoint: str = ""
    key: str = ""
    index_name: str = "ikg-document-sections"
    semantic_config: str = "default"
    vector_field: str = "embedding"

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.key and self.index_name)


@dataclass
class AzureHybridSearchResult:
    configured: bool
    ok: bool
    query: str = ""
    count: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def get_azure_search_config() -> AzureSearchConfig:
    return AzureSearchConfig(
        endpoint=os.getenv("AZURE_SEARCH_ENDPOINT", "").strip(),
        key=(
            os.getenv("AZURE_SEARCH_KEY", "").strip()
            or os.getenv("AZURE_SEARCH_API_KEY", "").strip()
            or os.getenv("AZURE_AI_SEARCH_KEY", "").strip()
        ),
        index_name=os.getenv("AZURE_SEARCH_INDEX", "ikg-document-sections").strip() or "ikg-document-sections",
        semantic_config=os.getenv("AZURE_SEARCH_SEMANTIC_CONFIG", "default").strip() or "default",
        vector_field=os.getenv("AZURE_SEARCH_VECTOR_FIELD", "embedding").strip() or "embedding",
    )


def is_azure_search_configured() -> bool:
    return get_azure_search_config().configured


def _client(config: AzureSearchConfig | None = None) -> Any:
    config = config or get_azure_search_config()
    if not config.configured:
        raise RuntimeError(
            "Azure AI Search is not configured. Set AZURE_SEARCH_ENDPOINT, "
            "AZURE_SEARCH_KEY, and AZURE_SEARCH_INDEX."
        )
    try:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents import SearchClient
    except ImportError as exc:
        raise RuntimeError(
            "azure-search-documents is required. Run `uv sync` after the pyproject dependency update."
        ) from exc
    return SearchClient(
        endpoint=config.endpoint,
        index_name=config.index_name,
        credential=AzureKeyCredential(config.key),
    )


def hybrid_search_sections(
    query: str,
    *,
    query_vector: list[float] | None = None,
    top_k: int = 8,
    filters: str | None = None,
) -> AzureHybridSearchResult:
    """Run keyword + optional vector hybrid search against document sections."""
    config = get_azure_search_config()
    if not config.configured:
        return AzureHybridSearchResult(
            configured=False,
            ok=False,
            query=query,
            error="Azure AI Search env vars are missing",
        )

    try:
        client = _client(config)
        kwargs: dict[str, Any] = {
            "search_text": query,
            "top": top_k,
            "include_total_count": True,
        }
        if filters:
            kwargs["filter"] = filters

        if query_vector:
            try:
                from azure.search.documents.models import VectorizedQuery

                kwargs["vector_queries"] = [
                    VectorizedQuery(
                        vector=query_vector,
                        k_nearest_neighbors=top_k,
                        fields=config.vector_field,
                    )
                ]
            except ImportError as exc:
                raise RuntimeError("Azure Search vector query models unavailable") from exc

        if os.getenv("AZURE_SEARCH_USE_SEMANTIC", "1").strip().lower() not in {"0", "false", "no", "off"}:
            kwargs["query_type"] = "semantic"
            kwargs["semantic_configuration_name"] = config.semantic_config

        response = client.search(**kwargs)
        rows: list[dict[str, Any]] = []
        for item in response:
            row = dict(item)
            row["@search.score"] = item.get("@search.score")
            row["@search.reranker_score"] = item.get("@search.reranker_score")
            rows.append(row)
        return AzureHybridSearchResult(
            configured=True,
            ok=True,
            query=query,
            count=len(rows),
            results=rows,
        )
    except Exception as exc:
        logger.warning("Azure AI Search hybrid query failed: %s", exc)
        return AzureHybridSearchResult(
            configured=True,
            ok=False,
            query=query,
            error=str(exc),
        )


def check_azure_search() -> dict[str, Any]:
    """Cheap health check used by smoke tests and support commands."""
    config = get_azure_search_config()
    if not config.configured:
        return {
            "configured": False,
            "ok": False,
            "error": "Missing AZURE_SEARCH_ENDPOINT/AZURE_SEARCH_KEY/AZURE_SEARCH_INDEX",
        }
    result = hybrid_search_sections("*", top_k=1)
    return {
        "configured": True,
        "ok": result.ok,
        "index_name": config.index_name,
        "count": result.count,
        "error": result.error,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(check_azure_search(), indent=2, default=str))

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from lawbot.rag.factory import RetrieverSettings, build_retriever


@lru_cache
def _cached_retriever(
    mode: str,
    qdrant_url: str,
    opensearch_url: str,
    embedding_mode: str,
    embedding_dim: int,
):
    settings = get_settings()
    return build_retriever(
        RetrieverSettings(
            mode=mode,
            qdrant_url=qdrant_url,
            qdrant_collection=settings.qdrant_collection,
            opensearch_url=opensearch_url,
            opensearch_index=settings.opensearch_index,
            embedding_model=settings.embedding_model,
            embedding_api_key=settings.embedding_api_key,
            embedding_api_base=settings.embedding_api_base,
            embedding_dim=embedding_dim,
            embedding_mode=embedding_mode,
            top_k=settings.retriever_top_k,
            rrf_k=settings.rrf_k,
        )
    )


def get_retriever():
    s = get_settings()
    return _cached_retriever(
        s.retriever_mode,
        s.qdrant_url,
        s.opensearch_url,
        s.embedding_mode,
        s.embedding_dim,
    )


def clear_retriever_cache() -> None:
    _cached_retriever.cache_clear()

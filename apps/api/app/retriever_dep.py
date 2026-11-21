from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.embedding_config import env_defaults_from_settings
from lawbot.db.session import get_sessionmaker
from lawbot.knowledge.embedding_settings import resolve_embedding_config
from lawbot.paths import resolve_rag_memory_dir
from lawbot.rag.factory import RetrieverSettings, build_retriever, reset_memory_stores_for_tests


@lru_cache
def _cached_retriever(
    mode: str,
    qdrant_url: str,
    opensearch_url: str,
    embedding_mode: str,
    embedding_model: str,
    embedding_dim: int,
    memory_dir: str,
    embedding_api_key: str,
    embedding_api_base: str,
):
    settings = get_settings()
    return build_retriever(
        RetrieverSettings(
            mode=mode,
            qdrant_url=qdrant_url,
            qdrant_collection=settings.qdrant_collection,
            opensearch_url=opensearch_url,
            opensearch_index=settings.opensearch_index,
            embedding_model=embedding_model,
            embedding_api_key=embedding_api_key,
            embedding_api_base=embedding_api_base or None,
            embedding_dim=embedding_dim,
            embedding_mode=embedding_mode,
            top_k=settings.retriever_top_k,
            rrf_k=settings.rrf_k,
            memory_dir=memory_dir,
        )
    )


def get_retriever():
    s = get_settings()
    factory = get_sessionmaker(s.database_url)
    db = factory()
    try:
        resolved = resolve_embedding_config(db, env_defaults_from_settings(s))
    finally:
        db.close()

    # auto → effective (may be fake); litellm/fake keep configured mode
    emb_mode = resolved.effective_mode if resolved.mode == "auto" else resolved.mode

    memory_dir = str(resolve_rag_memory_dir(s.rag_memory_dir))
    return _cached_retriever(
        s.retriever_mode,
        s.qdrant_url,
        s.opensearch_url,
        emb_mode,
        resolved.embedding_model,
        resolved.embedding_dim,
        memory_dir,
        resolved.api_key or "",
        resolved.api_base or "",
    )


def clear_retriever_cache() -> None:
    _cached_retriever.cache_clear()
    reset_memory_stores_for_tests()

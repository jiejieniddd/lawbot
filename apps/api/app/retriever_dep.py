from __future__ import annotations

from functools import lru_cache

from sqlalchemy.orm import Session

from app.config import get_settings
from lawbot.db.session import get_sessionmaker
from lawbot.llm.client import resolve_embedding_credentials
from lawbot.rag.factory import RetrieverSettings, build_retriever, reset_memory_stores_for_tests


def _resolve_embedding_for_settings(db: Session | None = None) -> tuple[str, str | None]:
    settings = get_settings()
    emb = resolve_embedding_credentials(
        db,
        embedding_api_key=settings.embedding_api_key,
        embedding_api_base=settings.embedding_api_base,
        encryption_key=settings.encryption_key or None,
        jwt_secret=settings.secret_key,
    )
    if emb is None:
        return settings.embedding_api_key, settings.embedding_api_base
    return emb.api_key, emb.api_base


@lru_cache
def _cached_retriever(
    mode: str,
    qdrant_url: str,
    opensearch_url: str,
    embedding_mode: str,
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
            embedding_model=settings.embedding_model,
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
    key = s.embedding_api_key
    base = s.embedding_api_base
    if not (key or "").strip():
        factory = get_sessionmaker(s.database_url)
        db = factory()
        try:
            key, base = _resolve_embedding_for_settings(db)
        finally:
            db.close()
    return _cached_retriever(
        s.retriever_mode,
        s.qdrant_url,
        s.opensearch_url,
        s.embedding_mode,
        s.embedding_dim,
        s.rag_memory_dir,
        key or "",
        base or "",
    )


def clear_retriever_cache() -> None:
    _cached_retriever.cache_clear()
    reset_memory_stores_for_tests()

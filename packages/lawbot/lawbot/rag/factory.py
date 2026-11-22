from __future__ import annotations

import logging
from dataclasses import dataclass

from lawbot.knowledge.embedder import embed_texts
from lawbot.paths import DEFAULT_RAG_MEMORY_REL, resolve_rag_memory_dir
from lawbot.rag.fake import FakeRetriever
from lawbot.rag.hybrid import HybridRetriever
from lawbot.rag.memory_persist import RECORDS_NAME, load_memory_index
from lawbot.rag.memory_store import InMemoryBM25Store, InMemoryVectorStore
from lawbot.rag.opensearch_store import OpenSearchArticleStore
from lawbot.rag.qdrant_store import QdrantArticleStore

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_DIR = DEFAULT_RAG_MEMORY_REL


@dataclass
class RetrieverSettings:
    mode: str = "hybrid"  # hybrid | fake | memory
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "lawbot_articles_v1"
    opensearch_url: str = "http://localhost:9200"
    opensearch_index: str = "lawbot_articles_v1"
    embedding_model: str = ""
    embedding_api_key: str = ""
    embedding_api_base: str | None = None
    embedding_dim: int = 384
    embedding_mode: str = "auto"
    top_k: int = 5
    rrf_k: int = 60
    memory_dir: str = DEFAULT_MEMORY_DIR


# process-local memory stores for mode=memory / tests
_MEMORY_VECTOR = InMemoryVectorStore()
_MEMORY_BM25 = InMemoryBM25Store()
_MEMORY_LOADED_DIR: str | None = None


def get_memory_stores() -> tuple[InMemoryVectorStore, InMemoryBM25Store]:
    return _MEMORY_VECTOR, _MEMORY_BM25


def reset_memory_stores_for_tests() -> None:
    global _MEMORY_LOADED_DIR
    _MEMORY_VECTOR._items.clear()
    _MEMORY_BM25._docs.clear()
    _MEMORY_LOADED_DIR = None


def ensure_memory_loaded(memory_dir: str) -> int:
    """Load disk index into process stores once per resolved memory_dir path."""
    global _MEMORY_LOADED_DIR
    resolved_path = resolve_rag_memory_dir(memory_dir)
    resolved = str(resolved_path)
    if _MEMORY_LOADED_DIR == resolved and _MEMORY_VECTOR._items:
        return len(_MEMORY_VECTOR._items)
    _, _, count = load_memory_index(
        resolved_path,
        vector_store=_MEMORY_VECTOR,
        bm25_store=_MEMORY_BM25,
    )
    _MEMORY_LOADED_DIR = resolved
    logger.info("memory index resolved_dir=%s loaded_count=%s", resolved, count)
    if count <= 0:
        expected = resolved_path / RECORDS_NAME
        logger.warning(
            "memory index missing or empty; expected records at %s",
            expected,
        )
    return count


def build_retriever(settings: RetrieverSettings):
    mode = (settings.mode or "hybrid").lower()
    if mode == "fake":
        return FakeRetriever()

    # Thin same-process cache: identical query string reuses one vector (rare double-call guard).
    _embed_query_cache: dict[str, list[float]] = {}

    def embed_query(q: str) -> list[float]:
        key = (q or "").strip()
        cached = _embed_query_cache.get(key)
        if cached is not None:
            return cached
        vec = embed_texts(
            [q],
            model=settings.embedding_model,
            api_key=settings.embedding_api_key,
            api_base=settings.embedding_api_base,
            dim=settings.embedding_dim,
            mode=settings.embedding_mode,
        )[0]
        if len(_embed_query_cache) >= 64:
            _embed_query_cache.clear()
        _embed_query_cache[key] = vec
        return vec

    if mode == "memory":
        mem_dir = settings.memory_dir or DEFAULT_MEMORY_DIR
        resolved = resolve_rag_memory_dir(mem_dir)
        count = ensure_memory_loaded(str(resolved))
        logger.info(
            "memory retriever ready docs=%s dir=%s",
            count,
            resolved,
        )
        vec, bm25 = get_memory_stores()

        def _vec_search(qv: list[float], k: int, domains: list[str] | None = None):
            return vec.search(qv, top_k=k, domains=domains)

        def _bm25_search(q: str, k: int, domains: list[str] | None = None):
            return bm25.search(q, top_k=k, domains=domains)

        return HybridRetriever(
            vector_search=_vec_search,
            bm25_search=_bm25_search,
            embed_query=embed_query,
            rrf_k=settings.rrf_k,
        )

    qdrant = QdrantArticleStore(
        url=settings.qdrant_url,
        collection=settings.qdrant_collection,
        dim=settings.embedding_dim,
    )
    os_store = OpenSearchArticleStore(url=settings.opensearch_url, index=settings.opensearch_index)
    return HybridRetriever(
        vector_search=lambda qv, k: qdrant.search(qv, top_k=k),
        bm25_search=lambda q, k: os_store.search(q, top_k=k),
        embed_query=embed_query,
        rrf_k=settings.rrf_k,
    )


def build_isolated_memory_retriever(settings: RetrieverSettings):
    """Load a memory index into private stores (does not touch the process-global chat index)."""
    mem_dir = settings.memory_dir or DEFAULT_MEMORY_DIR
    resolved = resolve_rag_memory_dir(mem_dir)
    vec = InMemoryVectorStore()
    bm25 = InMemoryBM25Store()
    _, _, count = load_memory_index(resolved, vector_store=vec, bm25_store=bm25)
    logger.info("isolated memory retriever ready docs=%s dir=%s", count, resolved)

    _embed_query_cache: dict[str, list[float]] = {}

    def embed_query(q: str) -> list[float]:
        key = (q or "").strip()
        cached = _embed_query_cache.get(key)
        if cached is not None:
            return cached
        out = embed_texts(
            [q],
            model=settings.embedding_model,
            api_key=settings.embedding_api_key,
            api_base=settings.embedding_api_base,
            dim=settings.embedding_dim,
            mode=settings.embedding_mode,
        )[0]
        if len(_embed_query_cache) >= 64:
            _embed_query_cache.clear()
        _embed_query_cache[key] = out
        return out

    return HybridRetriever(
        vector_search=lambda qv, k, domains=None: vec.search(qv, top_k=k, domains=domains),
        bm25_search=lambda q, k, domains=None: bm25.search(q, top_k=k, domains=domains),
        embed_query=embed_query,
        rrf_k=settings.rrf_k,
    )

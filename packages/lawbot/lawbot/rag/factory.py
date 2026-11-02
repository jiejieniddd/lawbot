from __future__ import annotations

import logging
from dataclasses import dataclass

from lawbot.knowledge.embedder import embed_texts
from lawbot.rag.fake import FakeRetriever
from lawbot.rag.hybrid import HybridRetriever
from lawbot.rag.memory_store import InMemoryBM25Store, InMemoryVectorStore
from lawbot.rag.opensearch_store import OpenSearchArticleStore
from lawbot.rag.qdrant_store import QdrantArticleStore

logger = logging.getLogger(__name__)


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


# process-local memory stores for mode=memory / tests
_MEMORY_VECTOR = InMemoryVectorStore()
_MEMORY_BM25 = InMemoryBM25Store()


def get_memory_stores() -> tuple[InMemoryVectorStore, InMemoryBM25Store]:
    return _MEMORY_VECTOR, _MEMORY_BM25


def build_retriever(settings: RetrieverSettings):
    mode = (settings.mode or "hybrid").lower()
    if mode == "fake":
        return FakeRetriever()

    def embed_query(q: str) -> list[float]:
        return embed_texts(
            [q],
            model=settings.embedding_model,
            api_key=settings.embedding_api_key,
            api_base=settings.embedding_api_base,
            dim=settings.embedding_dim,
            mode=settings.embedding_mode,
        )[0]

    if mode == "memory":
        vec, bm25 = get_memory_stores()
        return HybridRetriever(
            vector_search=lambda qv, k: vec.search(qv, top_k=k),
            bm25_search=lambda q, k: bm25.search(q, top_k=k),
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

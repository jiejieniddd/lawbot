from __future__ import annotations

import logging
from typing import Any

from lawbot.knowledge.embedder import embed_texts
from lawbot.knowledge.hf_import import (
    ALLOWED_CATEGORIES,
    DEFAULT_DATASET,
    DEFAULT_SUBSET,
    ArticleRecord,
    iter_filtered_articles,
)
from lawbot.rag.memory_store import InMemoryBM25Store, InMemoryVectorStore
from lawbot.rag.opensearch_store import OpenSearchArticleStore
from lawbot.rag.qdrant_store import QdrantArticleStore

logger = logging.getLogger(__name__)


def run_import(
    *,
    max_rows: int = 500,
    dataset_id: str = DEFAULT_DATASET,
    subset: str = DEFAULT_SUBSET,
    categories: frozenset[str] = ALLOWED_CATEGORIES,
    qdrant_url: str = "http://localhost:6333",
    opensearch_url: str = "http://localhost:9200",
    collection: str = "lawbot_articles_v1",
    index: str = "lawbot_articles_v1",
    embedding_model: str = "",
    embedding_api_key: str = "",
    embedding_api_base: str | None = None,
    embedding_dim: int = 384,
    embedding_mode: str = "auto",
    recreate: bool = False,
    batch_size: int = 64,
    rows: list[dict[str, Any]] | None = None,
    memory_vector: InMemoryVectorStore | None = None,
    memory_bm25: InMemoryBM25Store | None = None,
    use_memory: bool = False,
) -> dict[str, Any]:
    """Import filtered HF articles into Qdrant + OpenSearch (or in-memory stores)."""
    read = 0
    indexed = 0
    batch: list[ArticleRecord] = []

    qdrant = None
    os_store = None
    if not use_memory:
        qdrant = QdrantArticleStore(url=qdrant_url, collection=collection, dim=embedding_dim)
        os_store = OpenSearchArticleStore(url=opensearch_url, index=index)
        qdrant.ensure_collection(recreate=recreate)
        os_store.ensure_index(recreate=recreate)

    def flush(recs: list[ArticleRecord]) -> None:
        nonlocal indexed
        if not recs:
            return
        vectors = embed_texts(
            [r.chunk_text for r in recs],
            model=embedding_model,
            api_key=embedding_api_key,
            api_base=embedding_api_base,
            dim=embedding_dim,
            mode=embedding_mode,
        )
        if use_memory:
            assert memory_vector is not None and memory_bm25 is not None
            memory_vector.upsert(recs, vectors)
            memory_bm25.upsert(recs)
        else:
            assert qdrant is not None and os_store is not None
            qdrant.upsert(recs, vectors)
            os_store.upsert(recs)
        indexed += len(recs)

    for rec in iter_filtered_articles(
        dataset_id=dataset_id,
        subset=subset,
        max_rows=max_rows,
        categories=categories,
        rows=rows,
    ):
        read += 1
        batch.append(rec)
        if len(batch) >= batch_size:
            flush(batch)
            batch = []

    flush(batch)
    stats = {"read": read, "filtered": read, "indexed": indexed, "skipped": 0}
    logger.info("import finished stats=%s", stats)
    return stats

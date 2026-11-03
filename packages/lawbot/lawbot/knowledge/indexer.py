from __future__ import annotations

import logging
from typing import Any, Literal

from lawbot.knowledge.embedder import embed_texts
from lawbot.knowledge.hf_import import (
    ALLOWED_CATEGORIES,
    DEFAULT_DATASET,
    DEFAULT_SUBSET,
    ArticleRecord,
    iter_filtered_articles,
)
from lawbot.rag.factory import DEFAULT_MEMORY_DIR, get_memory_stores
from lawbot.rag.memory_persist import save_memory_index
from lawbot.rag.memory_store import InMemoryBM25Store, InMemoryVectorStore
from lawbot.rag.opensearch_store import OpenSearchArticleStore
from lawbot.rag.qdrant_store import QdrantArticleStore

logger = logging.getLogger(__name__)

IndexBackend = Literal["memory", "qdrant"]


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
    use_memory: bool | None = None,
    index_backend: IndexBackend | str | None = None,
    memory_dir: str = DEFAULT_MEMORY_DIR,
) -> dict[str, Any]:
    """Import filtered HF articles into memory disk index or Qdrant (+ optional OpenSearch)."""
    backend: str
    if index_backend is not None:
        backend = str(index_backend).lower()
    elif use_memory is True:
        backend = "memory"
    elif use_memory is False:
        backend = "qdrant"
    else:
        backend = "memory"

    if backend not in ("memory", "qdrant"):
        raise ValueError(f"unsupported index_backend={backend!r}")

    read = 0
    indexed = 0
    batch: list[ArticleRecord] = []
    opensearch_status = "skipped"

    qdrant: QdrantArticleStore | None = None
    os_store: OpenSearchArticleStore | None = None
    mem_vec = memory_vector
    mem_bm25 = memory_bm25

    if backend == "memory":
        if mem_vec is None or mem_bm25 is None:
            mem_vec, mem_bm25 = get_memory_stores()
            if recreate:
                mem_vec._items.clear()
                mem_bm25._docs.clear()
    else:
        qdrant = QdrantArticleStore(url=qdrant_url, collection=collection, dim=embedding_dim)
        qdrant.ensure_collection(recreate=recreate)
        os_store = OpenSearchArticleStore(url=opensearch_url, index=index)
        try:
            os_store.ensure_index(recreate=recreate)
            opensearch_status = "ok"
        except Exception:
            logger.exception("OpenSearch ensure_index failed; continuing with Qdrant only")
            opensearch_status = "degraded"
            os_store = None

    def flush(recs: list[ArticleRecord]) -> None:
        nonlocal indexed, opensearch_status, os_store
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
        if backend == "memory":
            assert mem_vec is not None and mem_bm25 is not None
            mem_vec.upsert(recs, vectors)
            mem_bm25.upsert(recs)
        else:
            assert qdrant is not None
            qdrant.upsert(recs, vectors)
            if os_store is not None:
                try:
                    os_store.upsert(recs)
                except Exception:
                    logger.exception("OpenSearch upsert failed; marking degraded")
                    opensearch_status = "degraded"
                    os_store = None
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

    if backend == "memory":
        assert mem_vec is not None and mem_bm25 is not None
        save_memory_index(mem_vec, mem_bm25, memory_dir)

    stats: dict[str, Any] = {
        "read": read,
        "filtered": read,
        "indexed": indexed,
        "skipped": 0,
        "backend": backend,
        "opensearch": opensearch_status,
        "memory_dir": memory_dir if backend == "memory" else None,
    }
    logger.info("import finished stats=%s", stats)
    return stats

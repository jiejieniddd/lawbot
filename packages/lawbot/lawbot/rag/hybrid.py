from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from lawbot.domain.schemas import Citation
from lawbot.rag.base import RetrievedChunk
from lawbot.rag.fake import FakeRetriever

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(
    ranked_lists: list[list[RetrievedChunk]],
    *,
    k: int = 60,
    top_k: int = 8,
) -> list[RetrievedChunk]:
    scores: dict[str, float] = {}
    best: dict[str, Citation] = {}
    for results in ranked_lists:
        for rank, chunk in enumerate(results, start=1):
            sid = chunk.citation.source_id
            scores[sid] = scores.get(sid, 0.0) + 1.0 / (k + rank)
            best[sid] = chunk.citation
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [RetrievedChunk(citation=best[sid], score=score) for sid, score in ordered]


class HybridRetriever:
    def __init__(
        self,
        *,
        vector_search: Callable[[list[float], int], list[RetrievedChunk]] | None = None,
        bm25_search: Callable[[str, int], list[RetrievedChunk]] | None = None,
        embed_query: Callable[[str], list[float]] | None = None,
        rrf_k: int = 60,
        fallback: FakeRetriever | None = None,
    ) -> None:
        self.vector_search = vector_search
        self.bm25_search = bm25_search
        self.embed_query = embed_query
        self.rrf_k = rrf_k
        self.fallback = fallback or FakeRetriever()

    def retrieve(self, query: str, top_k: int = 3) -> list[RetrievedChunk]:
        lists: list[list[RetrievedChunk]] = []
        fetch_k = max(top_k * 3, 10)

        if self.vector_search and self.embed_query:
            try:
                qv = self.embed_query(query)
                lists.append(self.vector_search(qv, fetch_k))
            except Exception:
                logger.exception("vector search failed")

        if self.bm25_search:
            try:
                lists.append(self.bm25_search(query, fetch_k))
            except Exception:
                logger.exception("bm25 search failed")

        lists = [lst for lst in lists if lst]
        if not lists:
            logger.warning("HybridRetriever backends empty; using FakeRetriever")
            return self.fallback.retrieve(query, top_k=top_k)

        return reciprocal_rank_fusion(lists, k=self.rrf_k, top_k=top_k)

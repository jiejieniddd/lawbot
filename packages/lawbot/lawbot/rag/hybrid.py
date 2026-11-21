from __future__ import annotations

import logging
from collections.abc import Callable

from lawbot.domain.schemas import Citation
from lawbot.rag.base import RetrievedChunk

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
    ) -> None:
        self.vector_search = vector_search
        self.bm25_search = bm25_search
        self.embed_query = embed_query
        self.rrf_k = rrf_k

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        *,
        domains: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        lists: list[list[RetrievedChunk]] = []
        fetch_k = max(top_k * 3, 10)
        q_preview = (query or "").strip()[:40]
        allowed = {d for d in (domains or []) if d}

        # Prefer cheap BM25 first; only embed+vector when BM25 has no hits.
        if self.bm25_search:
            try:
                try:
                    bm25_hits = self.bm25_search(query, fetch_k, domains=domains)  # type: ignore[call-arg]
                except TypeError:
                    bm25_hits = self.bm25_search(query, fetch_k)
                if bm25_hits:
                    lists.append(bm25_hits)
            except Exception:
                logger.exception("bm25 search failed")

        if not lists and self.vector_search and self.embed_query:
            try:
                qv = self.embed_query(query)
                try:
                    vec_hits = self.vector_search(qv, fetch_k, domains=domains)  # type: ignore[call-arg]
                except TypeError:
                    vec_hits = self.vector_search(qv, fetch_k)
                if vec_hits:
                    lists.append(vec_hits)
            except Exception:
                logger.exception("vector search failed")

        lists = [lst for lst in lists if lst]
        if not lists:
            logger.warning(
                "HybridRetriever backends empty; returning no citations query=%r",
                q_preview,
            )
            return []

        if len(lists) == 1:
            fused = lists[0][: max(top_k * 3, top_k)]
        else:
            fused = reciprocal_rank_fusion(lists, k=self.rrf_k, top_k=max(top_k * 3, top_k))

        if allowed:
            fused = [c for c in fused if (c.citation.domain or "") in allowed]
        return fused[:top_k]

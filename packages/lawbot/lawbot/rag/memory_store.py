from __future__ import annotations

import math
import re
from collections import Counter

from lawbot.domain.schemas import Citation
from lawbot.knowledge.chunk import KnowledgeChunk
from lawbot.rag.base import RetrievedChunk


def _tokenize(text: str) -> list[str]:
    # Simple CN/EN tokenization for offline BM25 tests
    parts = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", text.lower())
    return parts


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._items: list[tuple[list[float], KnowledgeChunk]] = []

    def upsert(self, records: list[KnowledgeChunk], vectors: list[list[float]]) -> int:
        by_id = {r.source_id: (v, r) for r, v in zip(records, vectors, strict=True)}
        kept = [(v, r) for v, r in self._items if r.source_id not in by_id]
        self._items = kept + list(by_id.values())
        return len(records)

    def search(
        self,
        query_vector: list[float],
        top_k: int = 8,
        *,
        domains: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        scored: list[RetrievedChunk] = []
        allowed = {d for d in (domains or []) if d}
        qn = math.sqrt(sum(x * x for x in query_vector)) or 1.0
        for vec, rec in self._items:
            if allowed and rec.domain not in allowed:
                continue
            dn = math.sqrt(sum(x * x for x in vec)) or 1.0
            dot = sum(a * b for a, b in zip(query_vector, vec, strict=False))
            score = dot / (qn * dn)
            scored.append(RetrievedChunk(citation=rec.to_citation(), score=float(score)))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]


class InMemoryBM25Store:
    def __init__(self) -> None:
        self._docs: list[tuple[Counter[str], KnowledgeChunk]] = []

    def upsert(self, records: list[KnowledgeChunk]) -> int:
        by_id = {r.source_id: r for r in records}
        kept = [(tok, r) for tok, r in self._docs if r.source_id not in by_id]
        self._docs = kept + [(Counter(_tokenize(r.chunk_text)), r) for r in records]
        return len(records)

    def search(
        self,
        query: str,
        top_k: int = 8,
        *,
        domains: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        q = Counter(_tokenize(query))
        if not q:
            return []
        allowed = {d for d in (domains or []) if d}
        scored: list[RetrievedChunk] = []
        for toks, rec in self._docs:
            if allowed and rec.domain not in allowed:
                continue
            score = sum(min(q[t], toks[t]) for t in q)
            if score > 0:
                scored.append(RetrievedChunk(citation=rec.to_citation(), score=float(score)))
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]


def citation_from_payload(payload: dict) -> Citation:
    title = payload.get("title") or payload.get("law_name") or ""
    category = payload.get("category") or payload.get("article_no") or ""
    return Citation(
        law_name=str(title),
        article_no=str(category),
        text=payload.get("text") or "",
        source_id=payload.get("source_id") or "",
        effective_date=payload.get("effective_date"),
        category=payload.get("category"),
        jurisdiction=payload.get("jurisdiction"),
        source_url=payload.get("source_url"),
        status=payload.get("status"),
        domain=payload.get("domain"),
    )

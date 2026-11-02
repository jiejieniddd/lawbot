from __future__ import annotations

import logging
import uuid
from typing import Any

from lawbot.knowledge.hf_import import ArticleRecord
from lawbot.rag.base import RetrievedChunk
from lawbot.rag.memory_store import citation_from_payload

logger = logging.getLogger(__name__)

COLLECTION = "lawbot_articles_v1"
_POINT_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def point_id_for(source_id: str) -> str:
    return str(uuid.uuid5(_POINT_NS, source_id))


class QdrantArticleStore:
    def __init__(self, url: str = "http://localhost:6333", collection: str = COLLECTION, dim: int = 384):
        self.url = url
        self.collection = collection
        self.dim = dim
        self._client = None

    def _get_client(self):
        if self._client is None:
            from qdrant_client import QdrantClient

            self._client = QdrantClient(url=self.url, timeout=30)
        return self._client

    def ensure_collection(self, recreate: bool = False) -> None:
        from qdrant_client.http import models as qm

        client = self._get_client()
        names = {c.name for c in client.get_collections().collections}
        if recreate and self.collection in names:
            client.delete_collection(self.collection)
            names.discard(self.collection)
        if self.collection not in names:
            client.create_collection(
                collection_name=self.collection,
                vectors_config=qm.VectorParams(size=self.dim, distance=qm.Distance.COSINE),
            )

    def upsert(self, records: list[ArticleRecord], vectors: list[list[float]]) -> int:
        from qdrant_client.http import models as qm

        self.ensure_collection()
        client = self._get_client()
        points = []
        for rec, vec in zip(records, vectors, strict=True):
            points.append(
                qm.PointStruct(
                    id=point_id_for(rec.source_id),
                    vector=vec,
                    payload={
                        "source_id": rec.source_id,
                        "doc_id": rec.doc_id,
                        "law_name": rec.law_name,
                        "article_no": rec.article_no,
                        "article_no_num": rec.article_no_num,
                        "text": rec.text,
                        "chunk_text": rec.chunk_text,
                        "category": rec.category,
                        "jurisdiction": rec.jurisdiction,
                        "source_url": rec.source_url,
                        "effective_date": rec.effective_date,
                        "status": rec.status,
                    },
                )
            )
        client.upsert(collection_name=self.collection, points=points)
        return len(points)

    def search(self, query_vector: list[float], top_k: int = 8) -> list[RetrievedChunk]:
        try:
            client = self._get_client()
            hits = client.search(
                collection_name=self.collection,
                query_vector=query_vector,
                limit=top_k,
                with_payload=True,
            )
        except Exception:
            logger.exception("Qdrant search failed")
            return []
        out: list[RetrievedChunk] = []
        for h in hits:
            payload: dict[str, Any] = h.payload or {}
            out.append(
                RetrievedChunk(citation=citation_from_payload(payload), score=float(h.score or 0.0))
            )
        return out

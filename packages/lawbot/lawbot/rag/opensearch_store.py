from __future__ import annotations

import logging
from typing import Any

from lawbot.knowledge.hf_import import ArticleRecord
from lawbot.rag.base import RetrievedChunk
from lawbot.rag.memory_store import citation_from_payload

logger = logging.getLogger(__name__)

INDEX = "lawbot_articles_v1"


class OpenSearchArticleStore:
    def __init__(self, url: str = "http://localhost:9200", index: str = INDEX):
        self.url = url
        self.index = index
        self._client = None

    def _get_client(self):
        if self._client is None:
            from opensearchpy import OpenSearch

            self._client = OpenSearch(hosts=[self.url], use_ssl=False, verify_certs=False)
        return self._client

    def ensure_index(self, recreate: bool = False) -> None:
        client = self._get_client()
        if recreate and client.indices.exists(index=self.index):
            client.indices.delete(index=self.index)
        if not client.indices.exists(index=self.index):
            client.indices.create(
                index=self.index,
                body={
                    "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
                    "mappings": {
                        "properties": {
                            "source_id": {"type": "keyword"},
                            "chunk_text": {"type": "text"},
                            "law_name": {"type": "text"},
                            "article_no": {"type": "keyword"},
                            "text": {"type": "text"},
                            "category": {"type": "keyword"},
                            "jurisdiction": {"type": "keyword"},
                            "source_url": {"type": "keyword"},
                            "effective_date": {"type": "keyword"},
                            "doc_id": {"type": "keyword"},
                            "article_no_num": {"type": "keyword"},
                            "status": {"type": "keyword"},
                        }
                    },
                },
            )

    def upsert(self, records: list[ArticleRecord]) -> int:
        from opensearchpy import helpers

        self.ensure_index()
        client = self._get_client()
        actions = []
        for rec in records:
            actions.append(
                {
                    "_index": self.index,
                    "_id": rec.source_id,
                    "_source": {
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
                }
            )
        helpers.bulk(client, actions)
        client.indices.refresh(index=self.index)
        return len(actions)

    def search(self, query: str, top_k: int = 8) -> list[RetrievedChunk]:
        try:
            client = self._get_client()
            resp = client.search(
                index=self.index,
                body={
                    "size": top_k,
                    "query": {
                        "multi_match": {
                            "query": query,
                            "fields": ["chunk_text^2", "law_name", "text"],
                        }
                    },
                },
            )
        except Exception:
            logger.exception("OpenSearch search failed")
            return []
        out: list[RetrievedChunk] = []
        for hit in resp.get("hits", {}).get("hits", []):
            payload: dict[str, Any] = hit.get("_source") or {}
            out.append(
                RetrievedChunk(
                    citation=citation_from_payload(payload),
                    score=float(hit.get("_score") or 0.0),
                )
            )
        return out

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from lawbot.domain.schemas import Citation


class KnowledgeChunk(BaseModel):
    """CareerBot indexed knowledge unit (replaces law ArticleRecord semantics)."""

    source_id: str
    domain: str
    title: str
    text: str
    chunk_text: str
    category: str | None = None
    skills: list[str] = Field(default_factory=list)
    level: str | None = None
    lang: str | None = None
    source_name: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    # Legacy law-shaped fields kept for store/qdrant payload compatibility
    doc_id: str | None = None
    law_name: str | None = None
    article_no: str | None = None
    article_no_num: str | None = None
    jurisdiction: str | None = None
    source_url: str | None = None
    effective_date: str | None = None
    status: str | None = None

    def to_citation(self) -> Citation:
        return Citation(
            law_name=self.title or self.law_name or "",
            article_no=self.category or self.article_no or "",
            text=self.text,
            source_id=self.source_id,
            effective_date=self.effective_date,
            category=self.category,
            jurisdiction=self.jurisdiction,
            source_url=self.source_url,
            status=self.status,
            domain=self.domain,
        )

    @classmethod
    def from_legacy_dict(cls, data: dict[str, Any]) -> KnowledgeChunk:
        """Load from disk JSON that may still look like ArticleRecord."""
        if "domain" in data and "title" in data:
            return cls.model_validate(data)
        title = str(data.get("law_name") or data.get("title") or "")
        text = str(data.get("text") or "")
        category = data.get("category")
        article_no = str(data.get("article_no") or category or "")
        chunk_text = str(data.get("chunk_text") or f"{title}\n{text}")
        return cls(
            source_id=str(data.get("source_id") or ""),
            domain=str(data.get("domain") or "legacy_law"),
            title=title,
            text=text,
            chunk_text=chunk_text,
            category=str(category) if category is not None else None,
            skills=list(data.get("skills") or []),
            level=data.get("level"),
            lang=data.get("lang"),
            source_name=data.get("source_name"),
            meta=dict(data.get("meta") or {}),
            doc_id=data.get("doc_id"),
            law_name=title,
            article_no=article_no,
            article_no_num=data.get("article_no_num"),
            jurisdiction=data.get("jurisdiction"),
            source_url=data.get("source_url"),
            effective_date=data.get("effective_date"),
            status=data.get("status"),
        )

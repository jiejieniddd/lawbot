from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from pydantic import BaseModel, Field

from lawbot.domain.schemas import Citation

ALLOWED_CATEGORIES = frozenset({"法律", "行政法规", "司法解释"})
DEFAULT_DATASET = "senry5433/china-effective-laws-regulations"
DEFAULT_SUBSET = "articles"


class ArticleRecord(BaseModel):
    source_id: str
    doc_id: str | None = None
    law_name: str
    article_no: str
    article_no_num: str | None = None
    text: str
    chunk_text: str
    category: str | None = None
    jurisdiction: str | None = None
    source_url: str | None = None
    effective_date: str | None = None
    status: str | None = None

    def to_citation(self) -> Citation:
        return Citation(
            law_name=self.law_name,
            article_no=self.article_no,
            text=self.text,
            source_id=self.source_id,
            effective_date=self.effective_date,
            category=self.category,
            jurisdiction=self.jurisdiction,
            source_url=self.source_url,
        )


def build_chunk(title: str, article_no_cn: str, text: str) -> str:
    return f"《{title}》{article_no_cn} {text}"


def filter_article_row(
    row: Mapping[str, Any],
    *,
    categories: frozenset[str] = ALLOWED_CATEGORIES,
) -> bool:
    if row.get("status") != "有效":
        return False
    return row.get("category") in categories


def row_to_record(row: Mapping[str, Any]) -> ArticleRecord:
    title = str(row.get("title") or "")
    article_no_cn = str(row.get("article_no_cn") or row.get("article_no") or "")
    text = str(row.get("text") or "")
    source_id = str(row.get("id") or f"{row.get('doc_id')}:{article_no_cn}")
    source_url = row.get("source_url") or "https://flk.npc.gov.cn/"
    return ArticleRecord(
        source_id=source_id,
        doc_id=str(row["doc_id"]) if row.get("doc_id") is not None else None,
        law_name=title,
        article_no=article_no_cn,
        article_no_num=str(row["article_no"]) if row.get("article_no") is not None else None,
        text=text,
        chunk_text=build_chunk(title, article_no_cn, text),
        category=row.get("category"),
        jurisdiction=row.get("jurisdiction"),
        source_url=str(source_url) if source_url else None,
        effective_date=str(row["filename_date"]) if row.get("filename_date") else None,
        status=row.get("status"),
    )


def iter_filtered_articles(
    *,
    dataset_id: str = DEFAULT_DATASET,
    subset: str = DEFAULT_SUBSET,
    max_rows: int = 500,
    categories: frozenset[str] = ALLOWED_CATEGORIES,
    rows: list[Mapping[str, Any]] | None = None,
) -> Iterator[ArticleRecord]:
    """Yield filtered ArticleRecords. Pass `rows` to avoid HF network (tests)."""
    emitted = 0
    limit = None if max_rows == 0 else max_rows

    if rows is not None:
        source_iter: Iterator[Mapping[str, Any]] = iter(rows)
    else:
        from datasets import load_dataset

        ds = load_dataset(dataset_id, subset, split="train")
        source_iter = (ds[i] for i in range(len(ds)))

    for row in source_iter:
        if not filter_article_row(row, categories=categories):
            continue
        yield row_to_record(row)
        emitted += 1
        if limit is not None and emitted >= limit:
            break

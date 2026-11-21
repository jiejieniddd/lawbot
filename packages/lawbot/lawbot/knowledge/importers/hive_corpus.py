"""Domain C — interview follow-up gotchas (the-hive-corpus)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from typing import Any

from lawbot.knowledge.chunk import KnowledgeChunk

DOMAIN = "gotchas"
SOURCE_NAME = "hive_corpus"


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"hive:{digest}"


def _skills_from_tags(row: Mapping[str, Any]) -> list[str]:
    tags = row.get("tags") or row.get("skills") or row.get("topics") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.replace(";", ",").split(",") if t.strip()]
    out: list[str] = []
    if isinstance(tags, list):
        for t in tags:
            s = str(t).strip()
            if s and s not in out:
                out.append(s)
    return out[:12]


def row_to_chunk(row: Mapping[str, Any]) -> KnowledgeChunk | None:
    title = str(row.get("title") or row.get("question") or "").strip()
    content = str(
        row.get("content") or row.get("answer") or row.get("text") or row.get("body") or ""
    ).strip()
    if not content and not title:
        return None
    if not content:
        content = title
    skills = _skills_from_tags(row)
    category = str(row.get("category") or row.get("topic") or "gotcha")
    chunk_text = f"{title}\n{content}" if title else content
    return KnowledgeChunk(
        source_id=_stable_id(title, content[:80]),
        domain=DOMAIN,
        title=title or category,
        text=content,
        chunk_text=chunk_text,
        category=category,
        skills=skills,
        lang=str(row.get("lang") or "en"),
        source_name=SOURCE_NAME,
        meta={"tags": skills},
        article_no=category,
        law_name=title or category,
    )


def iter_hive_chunks(
    rows: Iterator[Mapping[str, Any]],
    *,
    max_rows: int = 500,
) -> Iterator[KnowledgeChunk]:
    n = 0
    for row in rows:
        if n >= max_rows:
            break
        chunk = row_to_chunk(row)
        if chunk is None:
            continue
        n += 1
        yield chunk

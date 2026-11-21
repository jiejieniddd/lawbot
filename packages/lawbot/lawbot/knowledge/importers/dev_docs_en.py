from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

from lawbot.knowledge.chunk import KnowledgeChunk
from lawbot.knowledge.importers.allowlists import DEFAULT_DEV_TECH_ALLOWLIST

DOMAIN = "tech_docs"
SOURCE_NAME = "dev_knowledge_base"


def _normalize_allowlist(allowlist: Iterable[str] | None) -> frozenset[str]:
    if not allowlist:
        return DEFAULT_DEV_TECH_ALLOWLIST
    return frozenset(str(x).strip().lower() for x in allowlist if str(x).strip())


def row_matches_allowlist(row: Mapping[str, Any], allowlist: frozenset[str]) -> bool:
    blob = " ".join(
        [
            str(row.get("source") or ""),
            str(row.get("title") or ""),
            str(row.get("language") or ""),
            str(row.get("category") or ""),
            str(row.get("content") or "")[:200],
        ]
    ).lower()
    return any(token in blob for token in allowlist)


def _stable_id(source: str, chunk_id: Any, title: str, content: str) -> str:
    raw = f"{source}|{chunk_id}|{title}|{content[:80]}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"dev_docs:{digest}"


def row_to_chunk(
    row: Mapping[str, Any],
    *,
    allowlist: frozenset[str] | None = None,
) -> KnowledgeChunk | None:
    allowed = allowlist or DEFAULT_DEV_TECH_ALLOWLIST
    if not row_matches_allowlist(row, allowed):
        return None
    title = str(row.get("title") or "").strip()
    content = str(row.get("content") or "").strip()
    if not content:
        return None
    source = str(row.get("source") or "devdocs")
    chunk_id = row.get("chunk_id")
    url = row.get("url")
    skills = [source] if source else []
    chunk_text = f"{title}\n{content}" if title else content
    return KnowledgeChunk(
        source_id=_stable_id(source, chunk_id, title, content),
        domain=DOMAIN,
        title=title or source,
        text=content,
        chunk_text=chunk_text,
        category=str(row.get("category") or source or "tech_docs"),
        skills=skills,
        level=None,
        lang=str(row.get("language") or "en"),
        source_name=SOURCE_NAME,
        meta={"hf_source": source, "chunk_id": chunk_id},
        source_url=str(url) if url else None,
        article_no=str(row.get("category") or source or ""),
        law_name=title or source,
    )


def iter_dev_doc_chunks(
    rows: Iterator[Mapping[str, Any]],
    *,
    max_rows: int = 500,
    allowlist: Iterable[str] | None = None,
) -> Iterator[KnowledgeChunk]:
    allowed = _normalize_allowlist(allowlist)
    limit = None if max_rows == 0 else max_rows
    emitted = 0
    for row in rows:
        chunk = row_to_chunk(row, allowlist=allowed)
        if chunk is None:
            continue
        yield chunk
        emitted += 1
        if limit is not None and emitted >= limit:
            break

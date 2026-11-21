from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from typing import Any

from lawbot.knowledge.chunk import KnowledgeChunk
from lawbot.knowledge.importers.allowlists import (
    INTERVIEW_DENYLIST,
    INTERVIEW_HARD_DENYLIST,
    INTERVIEW_TECH_ALLOWLIST,
)

DOMAIN = "interview_qa"
SOURCE_NAME = "chinese_interview_large"


def _stable_id(instruction: str, output: str, index: int) -> str:
    digest = hashlib.sha1(f"{instruction}\n{output}".encode("utf-8")).hexdigest()[:16]
    return f"interview_zh:{digest}:{index}"


def _blob_lower(instruction: str, inp: str, output: str) -> str:
    return f"{instruction}\n{inp}\n{output}".lower()


def _extract_skills(blob: str) -> list[str]:
    hits: list[str] = []
    for token in sorted(INTERVIEW_TECH_ALLOWLIST, key=len, reverse=True):
        needle = token.lower()
        if needle in blob:
            hits.append(token)
        if len(hits) >= 12:
            break
    return hits


def row_to_chunk(row: Mapping[str, Any], *, index: int = 0) -> KnowledgeChunk | None:
    instruction = str(row.get("instruction") or "").strip()
    output = str(row.get("output") or "").strip()
    if not instruction or not output:
        return None
    inp = str(row.get("input") or "").strip()
    blob = _blob_lower(instruction, inp, output)
    if any(d.lower() in blob for d in INTERVIEW_HARD_DENYLIST):
        return None
    skills = _extract_skills(blob)
    # Require at least one tech signal (drops pure soft-skill noise).
    if not skills:
        return None
    # Soft denylist without enough tech signal.
    if any(d.lower() in blob for d in INTERVIEW_DENYLIST) and len(skills) <= 1:
        weak = {"api", "git", "sql", "http", "rest", "gc", "cap"}
        if skills[0].lower() in weak:
            return None

    title = instruction
    text = output
    if inp:
        chunk_text = f"Q: {instruction}\nContext: {inp}\nA: {output}"
    else:
        chunk_text = f"Q: {instruction}\nA: {output}"
    return KnowledgeChunk(
        source_id=_stable_id(instruction, output, index),
        domain=DOMAIN,
        title=title,
        text=text,
        chunk_text=chunk_text,
        category="interview_qa",
        skills=skills,
        level=None,
        lang="zh",
        source_name=SOURCE_NAME,
        meta={"has_input": bool(inp), "skills": skills},
        article_no="interview_qa",
        law_name=title,
    )


def iter_interview_chunks(
    rows: Iterator[Mapping[str, Any]],
    *,
    max_rows: int = 500,
) -> Iterator[KnowledgeChunk]:
    limit = None if max_rows == 0 else max_rows
    emitted = 0
    for i, row in enumerate(rows):
        chunk = row_to_chunk(row, index=i)
        if chunk is None:
            continue
        yield chunk
        emitted += 1
        if limit is not None and emitted >= limit:
            break

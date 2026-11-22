"""Domain mock_interview — oral Q&A bank (isolated index; never main search_kb)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from typing import Any

from lawbot.knowledge.chunk import KnowledgeChunk
from lawbot.knowledge.importers import interview_zh

DOMAIN = "mock_interview"
SOURCE_NAME = "chinese_interview_large_mock"


def _stable_id(instruction: str, output: str, index: int) -> str:
    digest = hashlib.sha1(f"{instruction}\n{output}".encode("utf-8")).hexdigest()[:16]
    return f"mock_interview:{digest}:{index}"


def _infer_track(skills: list[str], blob: str) -> str:
    s = " ".join(skills).lower() + " " + blob
    if any(k in s for k in ("react", "vue", "前端", "javascript", "typescript", "css")):
        return "frontend"
    if any(k in s for k in ("pytorch", "tensorflow", "机器学习", "深度学习", "cnn", "transformer")):
        return "data_ml"
    if any(k in s for k in ("docker", "kubernetes", "k8s", "devops", "ci/cd", "prometheus")):
        return "devops"
    if any(k in s for k in ("java", "spring", "jvm", "mybatis", "hibernate")):
        return "backend_java"
    if any(k in s for k in ("python", "fastapi", "django", "flask", "后端")):
        return "backend_python"
    if any(k in s for k in ("leetcode", "动态规划", "二叉树", "排序", "算法", "bfs", "dfs")):
        return "algo"
    if any(k in s for k in ("操作系统", "计算机网络", "tcp", "udp", "http", "进程", "线程", "数据结构")):
        return "cs_base"
    return "cs_base"


def row_to_chunk(row: Mapping[str, Any], *, index: int = 0) -> KnowledgeChunk | None:
    base = interview_zh.row_to_chunk(row, index=index)
    if base is None:
        return None
    instruction = str(row.get("instruction") or "").strip()
    output = str(row.get("output") or "").strip()
    inp = str(row.get("input") or "").strip()
    blob = f"{instruction}\n{inp}\n{output}".lower()
    track = _infer_track(list(base.skills or []), blob)
    meta = dict(base.meta or {})
    meta["track"] = track
    meta["reference_answer"] = output
    return KnowledgeChunk(
        source_id=_stable_id(instruction, output, index),
        domain=DOMAIN,
        title=base.title,
        text=base.text,
        chunk_text=base.chunk_text,
        category=track,
        skills=list(base.skills or []),
        level=base.level,
        lang=base.lang or "zh",
        source_name=SOURCE_NAME,
        meta=meta,
        article_no=track,
        law_name=base.title,
    )


def iter_mock_interview_chunks(
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

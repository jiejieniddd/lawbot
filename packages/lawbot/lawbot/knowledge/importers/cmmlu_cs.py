"""Domain D — CMMLU CS/security/ML subset for self-test (isolated index)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from typing import Any

from lawbot.knowledge.chunk import KnowledgeChunk

DOMAIN = "self_test"
SOURCE_NAME = "cmmlu_cs"

# Subject / category tokens to keep (Chinese CMMLU names + English aliases).
CS_SUBJECT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "computer_science",
        "computer science",
        "计算机",
        "计算机科学",
        "machine_learning",
        "machine learning",
        "机器学习",
        "deep_learning",
        "深度学习",
        "cybersecurity",
        "network_security",
        "网络安全",
        "信息安全",
        "information_security",
        "operating_system",
        "操作系统",
        "database",
        "数据库",
        "software_engineering",
        "软件工程",
        "programming",
        "编程",
        "algorithm",
        "算法",
        "artificial_intelligence",
        "人工智能",
    }
)


def _subject_blob(row: Mapping[str, Any]) -> str:
    return " ".join(
        [
            str(row.get("subject") or ""),
            str(row.get("category") or ""),
            str(row.get("task") or ""),
            str(row.get("split") or ""),
        ]
    ).lower()


def row_matches_cs(row: Mapping[str, Any]) -> bool:
    blob = _subject_blob(row)
    if not blob.strip():
        # If no subject field, accept rows that look like MCQ with A-D
        q = str(row.get("Question") or row.get("question") or "")
        return bool(q) and any(k in row for k in ("A", "B", "C", "D", "OptionA", "option_a"))
    return any(token in blob for token in CS_SUBJECT_ALLOWLIST)


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(p) for p in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"cmmlu:{digest}"


def _extract_options(row: Mapping[str, Any]) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for key in ("A", "B", "C", "D"):
        val = row.get(key) or row.get(f"Option{key}") or row.get(f"option_{key.lower()}")
        if val is not None and str(val).strip():
            options.append({"key": key, "text": str(val).strip()})
    if not options and isinstance(row.get("choices"), list):
        for i, item in enumerate(row["choices"]):
            options.append({"key": chr(ord("A") + i), "text": str(item)})
    return options


def row_to_chunk(row: Mapping[str, Any]) -> KnowledgeChunk | None:
    if not row_matches_cs(row):
        return None
    question = str(row.get("Question") or row.get("question") or row.get("title") or "").strip()
    if not question:
        return None
    options = _extract_options(row)
    answer = str(row.get("Answer") or row.get("answer") or row.get("answer_key") or "").strip()
    subject = str(row.get("subject") or row.get("category") or "cs")
    opt_text = "\n".join(f"{o['key']}. {o['text']}" for o in options)
    content = f"{question}\n{opt_text}".strip()
    return KnowledgeChunk(
        source_id=_stable_id(subject, question[:80], answer),
        domain=DOMAIN,
        title=question[:200],
        text=content,
        chunk_text=content,
        category=subject,
        skills=[subject],
        lang="zh",
        source_name=SOURCE_NAME,
        meta={
            "options": options,
            "answer_key": answer[:8] if answer else None,
            "subject": subject,
            "explanation": str(row.get("explanation") or "")[:500] or None,
        },
        article_no=subject,
        law_name=question[:120],
    )


def iter_cmmlu_chunks(
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

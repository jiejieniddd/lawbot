"""Domain E — AI job postings (RocXuLi/AI_Job_DataSet_1000_list)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Mapping
from typing import Any

from lawbot.knowledge.chunk import KnowledgeChunk

DOMAIN = "job_skills"
SOURCE_NAME = "ai_job_dataset_1000"

_SKILL_LEXICON = (
    "Python",
    "C++",
    "C/C++",
    "Java",
    "Go",
    "Rust",
    "MATLAB",
    "PyTorch",
    "TensorFlow",
    "OpenCV",
    "CUDA",
    "Linux",
    "ROS",
    "SLAM",
    "NLP",
    "CNN",
    "RNN",
    "Transformer",
    "LLM",
    "AIGC",
    "FastAPI",
    "Django",
    "Redis",
    "MySQL",
    "PostgreSQL",
    "Docker",
    "Kubernetes",
    "Halcon",
    "DSP",
    "OpenGL",
    "PCL",
)


def _stable_id(title: str, text: str) -> str:
    digest = hashlib.sha1(f"{title}|{text[:120]}".encode("utf-8")).hexdigest()[:16]
    return f"ai_job:{digest}"


def _extract_skills(blob: str) -> list[str]:
    found: list[str] = []
    lower = blob.lower()
    for skill in _SKILL_LEXICON:
        token = skill.lower()
        if token in lower and skill not in found:
            found.append(skill)
    # Comma-separated lead skills often appear before 岗位职责
    head = blob.split("岗位")[0][:120]
    for part in re.split(r"[,，/|、\s]+", head):
        part = part.strip()
        if 1 < len(part) <= 24 and re.search(r"[A-Za-z]", part) and part not in found:
            if part.lower() not in {"c", "r"}:
                found.append(part)
    return found[:16]


def _duty_summary(text: str, *, max_chars: int = 280) -> str:
    t = (text or "").strip()
    for marker in ("岗位职责", "工作职责", "职责描述", "工作内容", "职位描述"):
        idx = t.find(marker)
        if idx >= 0:
            t = t[idx:]
            break
    t = re.sub(r"\s+", " ", t)
    return t[:max_chars]


def row_to_chunk(row: Mapping[str, Any]) -> KnowledgeChunk | None:
    title = str(row.get("_c0") or row.get("title") or row.get("job_title") or "").strip()
    text = str(row.get("text") or row.get("content") or row.get("description") or "").strip()
    if not title and not text:
        return None
    if not title:
        title = text[:40]
    skills = _extract_skills(f"{title} {text}")
    duty = _duty_summary(text)
    skill_part = "、".join(skills) if skills else "（未标注）"
    chunk_text = f"{title} | {skill_part} | {duty}"
    return KnowledgeChunk(
        source_id=_stable_id(title, text),
        domain=DOMAIN,
        title=title,
        text=duty or text[:400],
        chunk_text=chunk_text,
        category="job_skills",
        skills=skills,
        lang="zh",
        source_name=SOURCE_NAME,
        meta={"raw_len": len(text), "skills": skills},
        article_no="job_skills",
        law_name=title,
    )


def iter_ai_job_chunks(
    rows: Iterator[Mapping[str, Any]],
    *,
    max_rows: int = 1000,
) -> Iterator[KnowledgeChunk]:
    n = 0
    for row in rows:
        if max_rows and n >= max_rows:
            break
        chunk = row_to_chunk(row)
        if chunk is None:
            continue
        n += 1
        yield chunk

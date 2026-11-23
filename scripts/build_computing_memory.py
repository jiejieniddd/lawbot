#!/usr/bin/env python3
"""Build a computer-career-only RAG index from the current index and O*NET 31.0.

Run locally. Source downloads live under data/hf/onet_31_0 (gitignored). The
output is a separate directory so the active index is never changed on failure.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "lawbot"))

from lawbot.knowledge.chunk import KnowledgeChunk  # noqa: E402
from lawbot.knowledge.embedder import fake_embed  # noqa: E402
from lawbot.rag.memory_persist import load_memory_index, save_memory_index  # noqa: E402
from lawbot.rag.memory_store import InMemoryBM25Store, InMemoryVectorStore  # noqa: E402


TECH_QUESTION = re.compile(
    r"Java|Python|C\+\+|C#|Go语言|Golang|Rust|JavaScript|TypeScript|"
    r"Spring|MySQL|PostgreSQL|Redis|SQL|Vue|React|Docker|Kubernetes|Linux|"
    r"API|HTTP|TCP|JVM|前端|后端|全栈|算法|数据库|编程|软件开发|数据分析|"
    r"大数据|数据结构|操作系统|网络安全|信息安全|自动化测试|软件测试|"
    r"机器学习|深度学习|计算机视觉|自然语言处理|微服务|分布式|"
    r"云计算|容器|消息队列|系统设计|架构设计|接口设计|性能优化|"
    r"推荐系统|搜索引擎|爬虫|DevOps|运维|移动开发|安卓|Android|iOS",
    re.I,
)
ALLOWED_DOMAINS = {"job_skills", "interview_qa", "tech_docs", "gotchas"}
ONET_SOURCE = "O*NET 31.0 Database, U.S. Department of Labor/ETA (CC BY 4.0)"
ONET_URL = "https://www.onetcenter.org/database.html"


def keep_existing(record: KnowledgeChunk) -> bool:
    if record.domain not in ALLOWED_DOMAINS:
        return False
    if record.source_name == "onet_31_0":
        # Rebuild these from the current source files; do not duplicate profiles.
        return False
    if record.domain == "interview_qa":
        return bool(TECH_QUESTION.search(record.title))
    # These three domains are already scoped by their source importers: AI jobs,
    # developer documentation, and five developer troubleshooting notes.
    return True


def load_onet_profiles(onedir: Path, aliases_path: Path) -> list[KnowledgeChunk]:
    aliases: dict[str, list[str]] = json.loads(aliases_path.read_text(encoding="utf-8"))
    occupations = json.loads((onedir / "occupation_data.json").read_text(encoding="utf-8"))["row"]
    skills_by_code: dict[str, list[tuple[str, bool, bool]]] = defaultdict(list)
    with (onedir / "software_skills.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            code = row.get("O*NET-SOC Code", "")
            if code not in aliases:
                continue
            name = (row.get("Workplace Example") or "").strip()
            if name:
                skills_by_code[code].append(
                    (name, row.get("In Demand") == "Y", row.get("Hot Technology") == "Y")
                )

    profiles: list[KnowledgeChunk] = []
    for row in occupations:
        code = row["onetsoc_code"]
        if code not in aliases:
            continue
        names = aliases[code]
        original_title = row["title"]
        description = row["description"].strip()
        selected = sorted(
            skills_by_code[code], key=lambda item: (not item[1], not item[2], item[0].lower())
        )
        seen: set[str] = set()
        skills: list[str] = []
        for name, _, _ in selected:
            if name.lower() not in seen:
                skills.append(name)
                seen.add(name.lower())
            if len(skills) >= 35:
                break
        title = f"{names[0]} / {original_title}"
        text = (
            f"CareerBot 岗位检索别名：{'、'.join(names)}。"
            f"O*NET-SOC {code}: {description} "
            f"Software skill examples for this occupation: {', '.join(skills) or 'none listed'}. "
            "中文岗位名称为 CareerBot 添加的检索别名；具体技术选型以目标公司的 JD 为准。"
        )
        profiles.append(
            KnowledgeChunk(
                source_id=f"onet31:{code}",
                domain="job_skills",
                title=title,
                text=text,
                chunk_text=f"{' '.join(names)} {original_title} {description} {' '.join(skills)}",
                category="job_skills",
                skills=skills,
                lang="en",
                source_name="onet_31_0",
                source_url=ONET_URL,
                meta={"onetsoc_code": code, "zh_aliases": names, "attribution": ONET_SOURCE},
            )
        )
    missing = sorted(set(aliases) - {r.meta["onetsoc_code"] for r in profiles})
    if missing:
        raise ValueError(f"O*NET occupation codes missing from data: {missing}")
    return profiles


def build(source: Path, onedir: Path, output: Path, aliases_path: Path) -> Counter[str]:
    if source.resolve() == output.resolve():
        raise ValueError("output must differ from source index")
    old_vec, _, count = load_memory_index(source)
    if not count:
        raise ValueError(f"source index is empty: {source}")
    if len(old_vec._items) != count:
        raise ValueError("source index vector count mismatch")

    kept = [(vec, rec) for vec, rec in old_vec._items if keep_existing(rec)]
    profiles = load_onet_profiles(onedir, aliases_path)
    dim = len(kept[0][0])
    vector = InMemoryVectorStore()
    bm25 = InMemoryBM25Store()
    records = [rec for _, rec in kept] + profiles
    vectors = [vec for vec, _ in kept] + [fake_embed(rec.chunk_text, dim=dim) for rec in profiles]
    vector.upsert(records, vectors)
    bm25.upsert(records)
    save_memory_index(vector, bm25, output)
    _, _, verified = load_memory_index(output)
    if verified != len(records):
        raise ValueError("output index verification failed")
    stats = Counter(rec.domain for rec in records)
    stats["removed"] = count - len(kept)
    stats["onet_profiles"] = len(profiles)
    stats["total"] = len(records)
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-index", type=Path, default=ROOT / "data/rag_memory")
    parser.add_argument("--onet-dir", type=Path, default=ROOT / "data/hf/onet_31_0")
    parser.add_argument("--output-index", type=Path, default=ROOT / "data/rag_memory_computing")
    parser.add_argument("--aliases", type=Path, default=ROOT / "data/market/computing_role_aliases.json")
    args = parser.parse_args()
    stats = build(args.source_index, args.onet_dir, args.output_index, args.aliases)
    print("computer knowledge index:", dict(stats))
    print("output:", args.output_index)
    print("source attribution:", ONET_SOURCE, ONET_URL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Smoke-test CareerBot computer-role retrieval against a local memory index."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "lawbot"))

from lawbot.agent.graph import make_retrieve  # noqa: E402
from lawbot.rag.factory import RetrieverSettings, build_isolated_memory_retriever  # noqa: E402


CASES = (
    ("我想面试Java全栈开发，应当具备哪些技术栈？", "onet31:15-1252.00"),
    ("前端开发工程师需要具备哪些技术栈？", "onet31:15-1254.00"),
    ("软件测试工程师岗位要求是什么？", "onet31:15-1253.00"),
    ("网络安全工程师技能要求是什么？", "onet31:15-1212.00"),
    ("数据工程师技能要求是什么？", "onet31:15-1243.01"),
    ("移动端开发需要掌握什么技术栈？", "onet31:15-1252.00"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory-dir", default=str(ROOT / "data/rag_memory"))
    args = parser.parse_args()
    retriever = build_isolated_memory_retriever(
        RetrieverSettings(mode="memory", memory_dir=args.memory_dir, embedding_mode="fake")
    )
    retrieve = make_retrieve(retriever)
    failures = 0
    for query, expected in CASES:
        out = retrieve({"query": query, "intent": "interview_qa"})
        ids = [str(hit.get("source_id") or "") for hit in out.get("law_hits") or []]
        ok = expected in ids[:3] and bool(out.get("retrieval_usable"))
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'} {query} => {ids[:3]}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

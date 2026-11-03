#!/usr/bin/env python3
"""Import a small HF / local sample into memory or Qdrant (no OpenSearch required)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT / "packages" / "lawbot"))

from lawbot.knowledge.hf_import import DEFAULT_DATASET  # noqa: E402
from lawbot.knowledge.indexer import run_import  # noqa: E402
from lawbot.rag.factory import (  # noqa: E402
    RetrieverSettings,
    build_retriever,
    reset_memory_stores_for_tests,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Low-spec sample knowledge import")
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="Hub id or local path/parquet")
    parser.add_argument("--subset", default="articles")
    parser.add_argument("--max-rows", type=int, default=200)
    parser.add_argument("--backend", choices=("memory", "qdrant"), default="memory")
    parser.add_argument("--memory-dir", default="data/rag_memory")
    parser.add_argument("--embedding-mode", default="fake")
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument("--query", default="劳动合同", help="Smoke search query after import")
    args = parser.parse_args()

    if args.backend == "memory":
        reset_memory_stores_for_tests()

    stats = run_import(
        max_rows=args.max_rows,
        dataset_id=args.dataset,
        subset=args.subset,
        index_backend=args.backend,
        memory_dir=args.memory_dir,
        embedding_mode=args.embedding_mode,
        qdrant_url=args.qdrant_url,
        recreate=False,
    )
    print("import stats:", stats)
    if int(stats.get("indexed") or 0) <= 0:
        print("ERROR: indexed == 0", file=sys.stderr)
        return 1

    reset_memory_stores_for_tests()
    mode = "memory" if args.backend == "memory" else "hybrid"
    retriever = build_retriever(
        RetrieverSettings(
            mode=mode,
            embedding_mode=args.embedding_mode,
            memory_dir=args.memory_dir,
            qdrant_url=args.qdrant_url,
        )
    )
    hits = retriever.retrieve(args.query, top_k=3)
    print(f"sample search q={args.query!r} hits={len(hits)}")
    for h in hits:
        sid = h.citation.source_id
        print(f"  - {sid} | {h.citation.law_name} {h.citation.article_no}")
        if sid.startswith("fake-"):
            print("ERROR: fake source_id in real retrieval path", file=sys.stderr)
            return 1
    if not hits:
        print("NOTE: no hits for smoke query (index may lack matching terms); indexed>0 still OK")
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

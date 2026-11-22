#!/usr/bin/env python3
"""Import CareerBot Domain A/B samples into memory (or Qdrant)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT / "packages" / "lawbot"))

from lawbot.knowledge.embedding_settings import (  # noqa: E402
    EnvEmbeddingDefaults,
    require_litellm_ready,
    resolve_embedding_config,
)
from lawbot.knowledge.importers import SOURCE_DEFAULT_DATASET  # noqa: E402
from lawbot.knowledge.indexer import run_import  # noqa: E402
from lawbot.paths import resolve_rag_memory_dir  # noqa: E402
from lawbot.rag.factory import (  # noqa: E402
    RetrieverSettings,
    build_retriever,
    reset_memory_stores_for_tests,
)


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = val


def _open_db():
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        return None, None
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
    except ImportError:
        return None, None
    engine = create_engine(url)
    return engine, Session(engine)


def main() -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(description="CareerBot memory/qdrant import")
    parser.add_argument(
        "--source",
        default="interview_zh",
        choices=(
            "interview_zh",
            "dev_docs_en",
            "hive_corpus",
            "cmmlu_cs",
            "ai_job_zh",
            "mock_interview_zh",
            "both",
            "career_all",
        ),
        help="Importer source id",
    )
    parser.add_argument("--dataset-dir", default=None, help="Override local dataset path")
    parser.add_argument("--max-rows", type=int, default=200)
    parser.add_argument("--backend", choices=("memory", "qdrant"), default="memory")
    parser.add_argument("--memory-dir", default="data/rag_memory")
    parser.add_argument("--allowlist", default=None, help="Comma-separated tech allowlist for B")
    parser.add_argument(
        "--embedding-mode",
        default=None,
        choices=("fake", "litellm", "auto"),
    )
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--embedding-api-key", default=None)
    parser.add_argument("--embedding-api-base", default=None)
    parser.add_argument("--embedding-dim", type=int, default=None)
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--qdrant-url", default="http://localhost:6333")
    parser.add_argument("--query", default="Python 后端 面试 常考", help="Smoke search after import")
    args = parser.parse_args()

    memory_dir = str(resolve_rag_memory_dir(args.memory_dir))
    print(f"resolved memory_dir={memory_dir}")

    env = EnvEmbeddingDefaults(
        mode=os.environ.get("EMBEDDING_MODE", "auto"),
        embedding_model=args.embedding_model
        if args.embedding_model is not None
        else os.environ.get("EMBEDDING_MODEL", ""),
        api_key=args.embedding_api_key
        if args.embedding_api_key is not None
        else os.environ.get("EMBEDDING_API_KEY") or os.environ.get("LLM_API_KEY") or "",
        api_base=args.embedding_api_base
        if args.embedding_api_base is not None
        else (os.environ.get("EMBEDDING_API_BASE") or None),
        embedding_dim=args.embedding_dim
        if args.embedding_dim is not None
        else int(os.environ.get("EMBEDDING_DIM") or 384),
        encryption_key=os.environ.get("ENCRYPTION_KEY") or None,
        jwt_secret=os.environ.get("SECRET_KEY")
        or os.environ.get("JWT_SECRET")
        or "dev",
    )

    engine, db = _open_db()
    try:
        resolved = resolve_embedding_config(db, env) if db is not None else None
    finally:
        if db is not None:
            db.close()
        if engine is not None:
            engine.dispose()

    if resolved is None:
        emb_mode = args.embedding_mode or env.mode or "fake"
        emb_model = env.embedding_model
        emb_key = env.api_key
        emb_base = env.api_base
        emb_dim = env.embedding_dim
    else:
        emb_mode = args.embedding_mode or (
            resolved.effective_mode if resolved.mode == "auto" else resolved.mode
        )
        emb_model = args.embedding_model or resolved.embedding_model
        emb_key = args.embedding_api_key or resolved.api_key
        emb_base = args.embedding_api_base or resolved.api_base
        emb_dim = args.embedding_dim or resolved.embedding_dim
        if emb_mode == "litellm":
            err = require_litellm_ready(resolved)
            if err:
                print(f"embedding not ready ({err}); falling back to fake")
                emb_mode = "fake"

    if args.embedding_mode:
        emb_mode = args.embedding_mode

    allowlist = None
    if args.allowlist:
        allowlist = [x.strip() for x in args.allowlist.split(",") if x.strip()]

    if args.source == "both":
        sources = ["interview_zh", "dev_docs_en"]
    elif args.source == "career_all":
        sources = ["interview_zh", "dev_docs_en", "hive_corpus"]
    else:
        sources = [args.source]
    from lawbot.rag.factory import ensure_memory_loaded, get_memory_stores

    # Isolated dirs — never main chat search_kb.
    self_test_dir = str(resolve_rag_memory_dir(os.environ.get("RAG_SELF_TEST_DIR") or "data/rag_memory_self_test"))
    mock_dir = str(
        resolve_rag_memory_dir(os.environ.get("RAG_MOCK_INTERVIEW_DIR") or "data/rag_memory_mock_interview")
    )

    all_stats = []
    for i, src in enumerate(sources):
        dataset = args.dataset_dir or SOURCE_DEFAULT_DATASET.get(src) or ""
        if src == "cmmlu_cs":
            target_dir = self_test_dir
        elif src == "mock_interview_zh":
            target_dir = mock_dir
        else:
            target_dir = memory_dir
        if args.backend == "memory":
            reset_memory_stores_for_tests()
            if not args.recreate:
                loaded = ensure_memory_loaded(target_dir)
                print(f"loaded existing memory docs={loaded} dir={target_dir} before append")
            else:
                get_memory_stores()
        # Only first source may recreate; later sources always append (per target dir).
        recreate = bool(args.recreate) if i == 0 else False
        if args.source not in ("both", "career_all") and not args.recreate:
            recreate = False
        print(
            f"importing source={src} dataset={dataset} max_rows={args.max_rows} "
            f"recreate={recreate} memory_dir={target_dir}"
        )
        stats = run_import(
            max_rows=args.max_rows,
            dataset_id=dataset,
            source=src,
            allowlist=allowlist,
            embedding_model=emb_model or "",
            embedding_api_key=emb_key or "",
            embedding_api_base=emb_base,
            embedding_dim=int(emb_dim or 384),
            embedding_mode=emb_mode or "fake",
            recreate=recreate,
            index_backend=args.backend,
            memory_dir=target_dir,
            qdrant_url=args.qdrant_url,
        )
        print("stats:", stats)
        all_stats.append(stats)

    if args.backend == "memory":
        smoke_dir = mock_dir if args.source == "mock_interview_zh" else memory_dir
        reset_memory_stores_for_tests()
        from lawbot.rag.factory import build_isolated_memory_retriever

        if args.source == "mock_interview_zh":
            retriever = build_isolated_memory_retriever(
                RetrieverSettings(
                    mode="memory",
                    memory_dir=smoke_dir,
                    embedding_mode=emb_mode or "fake",
                    embedding_model=emb_model or "",
                    embedding_api_key=emb_key or "",
                    embedding_api_base=emb_base,
                    embedding_dim=int(emb_dim or 384),
                )
            )
        else:
            retriever = build_retriever(
                RetrieverSettings(
                    mode="memory",
                    memory_dir=smoke_dir,
                    embedding_mode=emb_mode or "fake",
                    embedding_model=emb_model or "",
                    embedding_api_key=emb_key or "",
                    embedding_api_base=emb_base,
                    embedding_dim=int(emb_dim or 384),
                )
            )
        hits = retriever.retrieve(args.query, top_k=3)
        print(f"smoke query={args.query!r} dir={smoke_dir} hits={len(hits)}")
        for h in hits:
            sid = h.citation.source_id
            print(f"  - {sid} | {h.citation.domain} | {h.citation.law_name[:60]}")
            if str(sid).startswith("fake-"):
                print("WARNING: fake citation in memory mode")
            if args.source == "mock_interview_zh" and h.citation.domain != "mock_interview":
                print("WARNING: unexpected domain in mock bank")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
